"""Command line interface for cardtracker."""

from collections import defaultdict
from pathlib import Path
from typing import Annotated

import typer
from sqlmodel import select

from cardtracker.config import load_settings
from cardtracker.db import get_engine, get_session, init_db
from cardtracker.ebay_auth import MissingCredentialsError
from cardtracker.models import Card, Category, Comp, Grader, describe_card
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


_describe = describe_card


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


@app.command("net")
def net_command(
    sale_price: Annotated[float, typer.Argument(help="Sale price to evaluate")],
    shipping_charged: Annotated[
        float, typer.Option("--shipping-charged", help="Shipping the buyer pays me")
    ] = 0.0,
    tax: Annotated[
        float, typer.Option("--tax", help="Sales tax eBay collects from the buyer")
    ] = 0.0,
    shipping_cost: Annotated[
        float, typer.Option("--shipping-cost", help="What it costs me to ship")
    ] = 0.0,
    promoted: Annotated[
        float, typer.Option("--promoted", help="Promoted listing percent for this sale")
    ] = None,
) -> None:
    """Net proceeds after eBay fees, with the full breakdown."""
    from cardtracker.fees import FeeModel, compute_net

    settings = load_settings()
    model = FeeModel.from_settings(settings)
    breakdown = compute_net(model, sale_price, shipping_charged=shipping_charged,
                            tax_collected=tax, shipping_cost=shipping_cost,
                            promoted_pct=promoted)
    typer.echo(f"Sale price            {sale_price:>10,.2f}")
    if shipping_charged:
        typer.echo(f"Shipping charged      {shipping_charged:>10,.2f}")
    if tax:
        typer.echo(f"Sales tax (eBay keeps){tax:>10,.2f}  [fees apply to it, "
                   "seller never receives it]")
    typer.echo(f"Gross to seller       {breakdown.gross_to_seller:>10,.2f}")
    for line in breakdown.lines:
        typer.echo(f"  - {line.label:<40} {line.amount:>8,.2f}")
    if shipping_cost:
        typer.echo(f"  - shipping cost{'':<27} {shipping_cost:>8,.2f}")
    typer.echo(f"Total fees            {breakdown.total_fees:>10,.2f}")
    typer.secho(f"Net proceeds          {breakdown.net:>10,.2f}", fg="green", bold=True)


@app.command("log-buy")
def log_buy_command(
    card_id: Annotated[int, typer.Argument(help="Card id that was bought")],
    price: Annotated[float, typer.Option("--price", help="Purchase price")],
    buy_date: Annotated[
        str, typer.Option("--date", help="Purchase date YYYY-MM-DD, default today")
    ] = "",
    fees: Annotated[float, typer.Option(help="Buyer-side fees")] = 0.0,
    shipping: Annotated[float, typer.Option(help="Shipping paid")] = 0.0,
    taxes: Annotated[float, typer.Option(help="Sales tax paid")] = 0.0,
    grading: Annotated[float, typer.Option(help="Grading cost for this copy")] = 0.0,
    platform: Annotated[str, typer.Option(help="Where it was bought")] = "",
    notes: Annotated[str, typer.Option(help="Free-form notes")] = "",
) -> None:
    """Record buying one copy of a card with the full cost breakdown."""
    from datetime import date as date_type

    from cardtracker.portfolio import log_buy

    _, engine = _engine()
    parsed_date = None
    if buy_date:
        try:
            parsed_date = date_type.fromisoformat(buy_date)
        except ValueError:
            typer.secho(f"--date '{buy_date}' is not a valid YYYY-MM-DD date", fg="red")
            raise typer.Exit(code=1) from None
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        transaction = log_buy(session, card_id, price, buy_date=parsed_date,
                              fees=fees, shipping=shipping, taxes=taxes,
                              grading=grading, platform=platform, notes=notes)
        typer.secho(
            f"Logged buy of card {card_id} ({_describe(card)}) on {transaction.date}: "
            f"total cost {transaction.total_cost:,.2f} "
            f"(price {price:,.2f} + fees {fees:,.2f} + shipping {shipping:,.2f} "
            f"+ taxes {taxes:,.2f} + grading {grading:,.2f})",
            fg="green",
        )


@app.command("cost-basis")
def cost_basis_command(
    card_id: Annotated[int, typer.Option("--card-id", help="One card only")] = None,
) -> None:
    """Show total cost basis per card and per copy owned."""
    from cardtracker.portfolio import cost_basis_summary

    _, engine = _engine()
    with get_session(engine) as session:
        if card_id is not None:
            _get_card_or_exit(session, card_id)
        lines = cost_basis_summary(session, card_id=card_id)
        if not lines:
            typer.echo("No buys logged yet. Record one with 'cardtracker log-buy'.")
            return
        header = (f"{'id':>4}  {'card':<52}  {'copies':>6}  {'price':>10}  "
                  f"{'fees':>8}  {'ship':>8}  {'taxes':>8}  {'grading':>8}  "
                  f"{'total':>10}  {'per copy':>10}")
        typer.echo(header)
        typer.echo("-" * len(header))
        for line in lines:
            typer.echo(
                f"{line.card.id:>4}  {_describe(line.card):<52}  {line.copies:>6}  "
                f"{line.price_total:>10,.2f}  {line.fees_total:>8,.2f}  "
                f"{line.shipping_total:>8,.2f}  {line.taxes_total:>8,.2f}  "
                f"{line.grading_total:>8,.2f}  {line.total_cost:>10,.2f}  "
                f"{line.cost_per_copy:>10,.2f}"
            )
        if len(lines) > 1:
            grand_total = sum(line.total_cost for line in lines)
            typer.secho(f"Total cost basis across {len(lines)} cards: {grand_total:,.2f}",
                        bold=True)


@app.command("predict")
def predict(
    card_id: Annotated[int, typer.Argument(help="Card id to predict")],
    horizon_days: Annotated[
        int, typer.Option("--horizon-days", help="Days ahead to predict")
    ] = 30,
    log: Annotated[bool, typer.Option(help="Log the prediction for later scoring")] = True,
) -> None:
    """Predict direction with confidence and a written rationale."""
    from cardtracker.predict import predict_card

    _, engine = _engine()
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        result = predict_card(session, card_id, horizon_days=horizon_days, log=log)
        typer.echo(f"Card {card_id}: {_describe(card)}")
        color = {"up": "green", "down": "red", "flat": "yellow"}[str(result.direction)]
        typer.secho(
            f"Prediction as of {result.as_of} ({horizon_days} day horizon): "
            f"{str(result.direction).upper()}, confidence {result.confidence:.2f}",
            fg=color, bold=True,
        )
        typer.echo(f"Rationale: {result.rationale}")
        if log:
            typer.echo("Logged to predictions table.")


@app.command("backtest")
def backtest_command(
    horizon_days: Annotated[
        int, typer.Option("--horizon-days", help="Prediction horizon to test")
    ] = 30,
    step_days: Annotated[
        int, typer.Option("--step-days", help="Days between replayed prediction dates")
    ] = 7,
    card_id: Annotated[int, typer.Option("--card-id", help="Backtest one card only")] = None,
) -> None:
    """Replay historical comps and report prediction hit rate."""
    from cardtracker.predict import backtest

    _, engine = _engine()
    with get_session(engine) as session:
        if card_id is not None:
            _get_card_or_exit(session, card_id)
        report = backtest(session, horizon_days=horizon_days, step_days=step_days,
                          card_id=card_id)
    typer.echo(f"Backtest: {horizon_days} day horizon, replayed every {step_days} day(s)")
    if not report.scored:
        typer.echo("Nothing scorable. Backtesting needs sold comps spanning at least "
                   f"{30 + horizon_days} days for a card.")
        return
    cards_covered = len({row.card_id for row in report.rows})
    typer.echo(f"Scored {report.scored} prediction(s) across {cards_covered} card(s)")
    typer.secho(f"Hit rate: {report.hit_rate:.1%} ({report.hits}/{report.scored})",
                bold=True)
    for direction, (hits, total) in sorted(report.by_direction().items()):
        typer.echo(f"  predicted {direction}: {hits}/{total} correct")


@app.command("score-predictions")
def score_predictions_command() -> None:
    """Fill in realized outcomes for logged predictions whose horizon has passed."""
    from cardtracker.predict import score_due_predictions

    _, engine = _engine()
    with get_session(engine) as session:
        scored = score_due_predictions(session)
    typer.secho(f"Scored {scored} prediction(s)", fg="green")


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
