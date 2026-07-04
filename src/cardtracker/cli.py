"""Command line interface for cardtracker."""

from collections import defaultdict
from pathlib import Path
from typing import Annotated

import typer
from sqlmodel import select

from cardtracker.config import load_settings
from cardtracker.db import get_engine, get_session, init_db
from cardtracker.ebay_auth import MissingCredentialsError
from cardtracker.models import Card, Category, Comp, Grader
from cardtracker.sources import BrowseApiSource, CsvImportError, CsvImportSource, save_comps
from cardtracker.stats import latest_snapshots, refresh_snapshots

app = typer.Typer(help="Track card price comps and market stats.", no_args_is_help=True)


def _engine():
    settings = load_settings()
    engine = get_engine(settings)
    init_db(engine)
    return settings, engine


def _get_card_or_exit(session, card_id: int) -> Card:
    card = session.get(Card, card_id)
    if card is None:
        typer.secho(f"No card with id {card_id}. Run 'cardtracker list-cards'.", fg="red")
        raise typer.Exit(code=1)
    return card


@app.command("init-db")
def init_db_command() -> None:
    """Create the database and all tables."""
    settings, _ = _engine()
    typer.echo(f"Database ready at {settings.db_path}")


@app.command("add-card")
def add_card(
    category: Annotated[Category, typer.Option(help="sports or pokemon")],
    player: Annotated[str, typer.Option("--player", help="Player or character name")],
    set_name: Annotated[str, typer.Option("--set", help="Set name")],
    year: Annotated[int, typer.Option(help="Set year")],
    number: Annotated[str, typer.Option("--number", help="Card number")] = "",
    parallel: Annotated[str, typer.Option("--parallel", help="Variation or parallel")] = "",
    grader: Annotated[Grader, typer.Option(help="PSA, BGS, SGC, CGC, or raw")] = Grader.RAW,
    grade: Annotated[str, typer.Option(help="Grade, e.g. 10 or 9.5")] = "",
    cert: Annotated[str, typer.Option("--cert", help="Cert number")] = None,
    notes: Annotated[str, typer.Option(help="Free-form notes")] = "",
) -> None:
    """Add a card identity. A PSA 10 and a PSA 9 of the same card are two cards."""
    _, engine = _engine()
    card = Card(
        category=category,
        player_or_character=player,
        set_name=set_name,
        year=year,
        card_number=number,
        variation_or_parallel=parallel,
        grader=grader,
        grade=grade,
        cert_number=cert,
        notes=notes,
    )
    with get_session(engine) as session:
        session.add(card)
        session.commit()
        session.refresh(card)
        typer.secho(f"Added card {card.id}: {_describe(card)}", fg="green")


def _describe(card: Card) -> str:
    grade_part = f"{card.grader} {card.grade}".strip() if card.grader != Grader.RAW else "raw"
    bits = [str(card.year), card.set_name, card.player_or_character]
    if card.card_number:
        bits.append(f"#{card.card_number}")
    if card.variation_or_parallel:
        bits.append(card.variation_or_parallel)
    bits.append(grade_part)
    return " ".join(bits)


@app.command("list-cards")
def list_cards() -> None:
    """List all cards with comp counts."""
    _, engine = _engine()
    with get_session(engine) as session:
        cards = session.exec(select(Card).order_by(Card.id)).all()
        if not cards:
            typer.echo("No cards yet. Add one with 'cardtracker add-card'.")
            return
        comps = session.exec(select(Comp.card_id, Comp.price_type)).all()
        counts: dict[tuple[int, str], int] = defaultdict(int)
        for card_id, price_type in comps:
            counts[(card_id, price_type)] += 1
        header = f"{'id':>4}  {'category':<8}  {'card':<60}  {'asks':>5}  {'solds':>5}"
        typer.echo(header)
        typer.echo("-" * len(header))
        for card in cards:
            typer.echo(
                f"{card.id:>4}  {card.category:<8}  {_describe(card):<60}  "
                f"{counts[(card.id, 'ask')]:>5}  {counts[(card.id, 'sold')]:>5}"
            )


@app.command("pull-comps")
def pull_comps(
    card_id: Annotated[int, typer.Argument(help="Card id to attach comps to")],
    query: Annotated[str, typer.Option("--query", help="eBay search terms")],
    limit: Annotated[int, typer.Option(help="Max listings to pull")] = 50,
) -> None:
    """Pull active listings (ask prices) from the eBay Browse API."""
    settings, engine = _engine()
    with get_session(engine) as session:
        _get_card_or_exit(session, card_id)
        source = BrowseApiSource(settings)
        try:
            records = source.fetch_comps(query, limit=limit)
        except MissingCredentialsError as exc:
            typer.secho(str(exc), fg="red")
            raise typer.Exit(code=1) from None
        saved = save_comps(session, card_id, source, records)
        typer.secho(
            f"Saved {len(saved)} ask comps for card {card_id} "
            f"(source: browse, env: {settings.ebay_env})",
            fg="green",
        )


@app.command("import-csv")
def import_csv(
    path: Annotated[Path, typer.Argument(help="Path to the sold-comp CSV file")],
    card_id: Annotated[int, typer.Option("--card-id", help="Card id for rows without one")] = None,
    skip_bad_rows: Annotated[
        bool, typer.Option(help="Skip invalid rows instead of aborting")
    ] = False,
) -> None:
    """Import confirmed sales from a CSV. See the README for the schema."""
    _, engine = _engine()
    source = CsvImportSource(path, default_card_id=card_id, skip_bad_rows=skip_bad_rows)
    try:
        rows = source.read_rows()
    except CsvImportError as exc:
        typer.secho(f"Import failed: {exc}", fg="red")
        raise typer.Exit(code=1) from None
    by_card: dict[int, list] = defaultdict(list)
    for row in rows:
        by_card[row.card_id].append(row.record)
    with get_session(engine) as session:
        for cid in by_card:
            _get_card_or_exit(session, cid)
        total = 0
        for cid, records in by_card.items():
            total += len(save_comps(session, cid, source, records))
    typer.secho(f"Imported {total} sold comps across {len(by_card)} card(s)", fg="green")
    for message in source.skipped:
        typer.secho(f"Skipped {message}", fg="yellow")


@app.command("refresh-stats")
def refresh_stats(
    card_id: Annotated[int, typer.Option("--card-id", help="Refresh one card only")] = None,
) -> None:
    """Compute and store price snapshots from comps, ask and sold separately."""
    _, engine = _engine()
    with get_session(engine) as session:
        if card_id is not None:
            _get_card_or_exit(session, card_id)
        written = refresh_snapshots(session, card_id=card_id)
    typer.secho(f"Wrote {len(written)} snapshot(s)", fg="green")


def _money(value: float | None) -> str:
    return f"{value:,.2f}" if value is not None else "n/a"


def _slope_text(value: float | None) -> str:
    return f"{value:+.2f}/day" if value is not None else "n/a"


@app.command("stats")
def stats(
    card_id: Annotated[int, typer.Argument(help="Card id to show stats for")],
) -> None:
    """Print the full stat line for a card, ask and sold kept separate."""
    _, engine = _engine()
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        snapshots = latest_snapshots(session, card_id)
        typer.echo(f"Card {card_id}: {_describe(card)}")
        if not snapshots:
            typer.echo("No snapshots yet. Run 'cardtracker refresh-stats' after adding comps.")
            return
        labels = {
            "sold": "sold stats (confirmed sales)",
            "ask": "ask stats (active listings, not sale prices)",
        }
        for price_type in ("sold", "ask"):
            snapshot = snapshots.get(price_type)
            if snapshot is None:
                continue
            typer.echo("")
            typer.secho(f"{labels[price_type]} as of {snapshot.as_of_date}", bold=True)
            typer.echo(f"  median 7d / 30d / 90d : {_money(snapshot.median_7d)} / "
                       f"{_money(snapshot.median_30d)} / {_money(snapshot.median_90d)}")
            typer.echo(f"  mean 30d              : {_money(snapshot.mean_30d)}")
            typer.echo(f"  count 30d / 90d       : {snapshot.sale_count_30d} / "
                       f"{snapshot.sale_count_90d}")
            typer.echo(f"  low / high 30d        : {_money(snapshot.low_30d)} / "
                       f"{_money(snapshot.high_30d)}")
            typer.echo(f"  spread 30d            : {_money(snapshot.spread_30d)}")
            typer.echo(f"  volatility 30d        : {_money(snapshot.volatility_30d)}")
            typer.echo(f"  velocity 30d          : {snapshot.velocity_30d:.1f} per week")
            typer.echo(f"  slope 30d / 90d       : {_slope_text(snapshot.trend_slope_30d)} / "
                       f"{_slope_text(snapshot.trend_slope_90d)}")


@app.command("schedule-refresh")
def schedule_refresh(
    interval_hours: Annotated[
        float, typer.Option("--interval-hours", help="Hours between refresh runs")
    ] = 12.0,
) -> None:
    """Run the snapshot refresh on a schedule until stopped with Ctrl+C."""
    from cardtracker.scheduler import run_scheduler

    run_scheduler(interval_hours)


if __name__ == "__main__":
    app()
