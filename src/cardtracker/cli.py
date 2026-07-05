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


@app.command("log-sell")
def log_sell_command(
    card_id: Annotated[int, typer.Argument(help="Card id that was sold")],
    price: Annotated[float, typer.Option("--price", help="Actual sale price")],
    sell_date: Annotated[
        str, typer.Option("--date", help="Sale date YYYY-MM-DD, default today")
    ] = "",
    fees: Annotated[float, typer.Option(help="Actual total fees on the sale")] = 0.0,
    estimate_fees: Annotated[
        bool, typer.Option("--estimate-fees", help="Estimate fees from the fee model "
                           "instead of passing --fees")
    ] = False,
    shipping_cost: Annotated[
        float, typer.Option("--shipping-cost", help="What shipping cost me")
    ] = 0.0,
    platform: Annotated[str, typer.Option(help="Where it sold")] = "",
    notes: Annotated[str, typer.Option(help="Free-form notes")] = "",
) -> None:
    """Record selling one copy and show realized profit for the sale."""
    from datetime import date as date_type

    from cardtracker.fees import FeeModel, compute_net
    from cardtracker.portfolio import avg_cost_per_copy, log_sell

    settings, engine = _engine()
    parsed_date = None
    if sell_date:
        try:
            parsed_date = date_type.fromisoformat(sell_date)
        except ValueError:
            typer.secho(f"--date '{sell_date}' is not a valid YYYY-MM-DD date", fg="red")
            raise typer.Exit(code=1) from None
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        if estimate_fees:
            if fees:
                typer.secho("Use either --fees or --estimate-fees, not both", fg="red")
                raise typer.Exit(code=1)
            breakdown = compute_net(FeeModel.from_settings(settings), price)
            fees = breakdown.total_fees
            typer.echo(f"Estimated fees from fee model: {fees:,.2f}")
        transaction = log_sell(session, card_id, price, sell_date=parsed_date,
                               fees=fees, shipping_cost=shipping_cost,
                               platform=platform, notes=notes)
        cost = avg_cost_per_copy(session, card_id)
        net = price - fees - shipping_cost
        typer.secho(f"Logged sell of card {card_id} ({_describe(card)}) on "
                    f"{transaction.date}: net {net:,.2f} after fees {fees:,.2f} "
                    f"and shipping {shipping_cost:,.2f}", fg="green")
        if cost is not None:
            profit = net - cost
            roi = f" ({profit / cost * 100:+.1f}%)" if cost else ""
            typer.secho(f"Realized profit vs avg cost {cost:,.2f}: "
                        f"{profit:+,.2f}{roi}", bold=True)
        else:
            typer.echo("No buy logged for this card, so no cost basis to compare.")


@app.command("realized")
def realized_command(
    card_id: Annotated[int, typer.Option("--card-id", help="One card only")] = None,
) -> None:
    """Realized P&L across all sold cards."""
    from cardtracker.portfolio import realized_summary

    _, engine = _engine()
    with get_session(engine) as session:
        if card_id is not None:
            _get_card_or_exit(session, card_id)
        lines = realized_summary(session, card_id=card_id)
        if not lines:
            typer.echo("No sells logged yet. Record one with 'cardtracker log-sell'.")
            return
        header = (f"{'date':<10}  {'card':<48}  {'sale':>9}  {'fees':>8}  {'ship':>7}  "
                  f"{'net':>9}  {'cost':>9}  {'profit':>9}  {'roi':>8}")
        typer.echo(header)
        typer.echo("-" * len(header))
        for line in lines:
            cost = f"{line.cost_allocated:,.2f}" if line.cost_allocated is not None else "n/a"
            profit = f"{line.profit:+,.2f}" if line.profit is not None else "n/a"
            roi = f"{line.roi_pct:+.1f}%" if line.roi_pct is not None else "n/a"
            typer.echo(
                f"{line.sale_date}  {_describe(line.card):<48}  {line.sale_price:>9,.2f}  "
                f"{line.fees:>8,.2f}  {line.shipping_cost:>7,.2f}  {line.net:>9,.2f}  "
                f"{cost:>9}  {profit:>9}  {roi:>8}"
            )
        with_profit = [line for line in lines if line.profit is not None]
        if with_profit:
            total = sum(line.profit for line in with_profit)
            typer.secho(f"Total realized profit: {total:+,.2f} across "
                        f"{len(with_profit)} sale(s)", bold=True)


@app.command("unrealized")
def unrealized_command(
    shipping_cost: Annotated[
        float, typer.Option("--shipping-cost", help="Assumed cost to ship a sale")
    ] = 0.0,
) -> None:
    """Profit and ROI if each held card were sold at market right now."""
    from cardtracker.fees import FeeModel
    from cardtracker.portfolio import unrealized_summary

    settings, engine = _engine()
    with get_session(engine) as session:
        lines = unrealized_summary(session, FeeModel.from_settings(settings),
                                   shipping_cost=shipping_cost)
        if not lines:
            typer.echo("No held cards. Log a buy first with 'cardtracker log-buy'.")
            return
        header = (f"{'id':>4}  {'card':<52}  {'qty':>3}  {'cost':>10}  {'market':>10}  "
                  f"{'net value':>10}  {'profit':>10}  {'roi':>8}")
        typer.echo(header)
        typer.echo("-" * len(header))
        flagged = False
        for line in lines:
            if line.market_per_copy is None:
                typer.echo(f"{line.card.id:>4}  {_describe(line.card):<52}  "
                           f"{line.quantity:>3}  {line.cost_basis:>10,.2f}  "
                           f"{'no data':>10}  {'':>10}  {'':>10}  {'':>8}")
                continue
            flag = " *" if line.market_price_type == "ask" else ""
            if flag:
                flagged = True
            roi = f"{line.roi_pct:+.1f}%" if line.roi_pct is not None else "n/a"
            typer.echo(
                f"{line.card.id:>4}  {_describe(line.card):<52}  {line.quantity:>3}  "
                f"{line.cost_basis:>10,.2f}  {line.market_per_copy:>8,.2f}{flag:<2}  "
                f"{line.net_value:>10,.2f}  {line.profit:>+10,.2f}  {roi:>8}"
            )
        priced = [line for line in lines if line.profit is not None]
        if priced:
            total_cost = sum(line.cost_basis for line in priced)
            total_profit = sum(line.profit for line in priced)
            total_roi = f" ({total_profit / total_cost * 100:+.1f}%)" if total_cost else ""
            typer.secho(f"Unrealized profit: {total_profit:+,.2f}{total_roi} "
                        f"on cost basis {total_cost:,.2f}", bold=True)
        if flagged:
            typer.secho("* based on ask median, no sold data for this card",
                        fg="yellow")
        stale = [line for line in lines if line.market_per_copy is None]
        if stale:
            typer.echo("Cards showing 'no data' need comps and a refresh-stats run.")


@app.command("set-status")
def set_status_command(
    card_id: Annotated[int, typer.Argument(help="Card id to update")],
    status: Annotated[
        str, typer.Option("--status", help="owned, listed, sold, or watching")
    ] = None,
    quantity: Annotated[int, typer.Option("--quantity", help="Copies held")] = None,
    listed_price: Annotated[
        float, typer.Option("--listed-price", help="Current listing price")
    ] = None,
) -> None:
    """Set inventory status, quantity, or listed price for a card."""
    from cardtracker.models import InventoryStatus
    from cardtracker.portfolio import set_status

    _, engine = _engine()
    parsed_status = None
    if status is not None:
        try:
            parsed_status = InventoryStatus(status.lower())
        except ValueError:
            typer.secho(f"--status must be owned, listed, sold, or watching, "
                        f"got '{status}'", fg="red")
            raise typer.Exit(code=1) from None
    if parsed_status is None and quantity is None and listed_price is None:
        typer.secho("Nothing to update. Pass --status, --quantity, or --listed-price.",
                    fg="red")
        raise typer.Exit(code=1)
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        inventory = set_status(session, card_id, status=parsed_status,
                               quantity=quantity, listed_price=listed_price)
        listed = (f", listed at {inventory.listed_price:,.2f}"
                  if inventory.listed_price else "")
        typer.secho(f"Card {card_id} ({_describe(card)}): {inventory.status}, "
                    f"quantity {inventory.quantity}{listed}", fg="green")


@app.command("inventory")
def inventory_command(
    status: Annotated[
        str, typer.Option("--status", help="Filter: owned, listed, sold, or watching")
    ] = None,
) -> None:
    """Inventory with status, quantity, and current market stat."""
    from cardtracker.models import InventoryStatus
    from cardtracker.portfolio import inventory_view

    _, engine = _engine()
    parsed_status = None
    if status is not None:
        try:
            parsed_status = InventoryStatus(status.lower())
        except ValueError:
            typer.secho(f"--status must be owned, listed, sold, or watching, "
                        f"got '{status}'", fg="red")
            raise typer.Exit(code=1) from None
    with get_session(engine) as session:
        lines = inventory_view(session, status=parsed_status)
        if not lines:
            typer.echo("No inventory rows match. Track a card with "
                       "'cardtracker set-status' or 'cardtracker log-buy'.")
            return
        header = (f"{'id':>4}  {'card':<52}  {'status':<8}  {'qty':>3}  "
                  f"{'cost':>10}  {'listed':>9}  {'market':>10}")
        typer.echo(header)
        typer.echo("-" * len(header))
        for line in lines:
            cost = f"{line.inventory.cost_basis:,.2f}" if line.inventory.cost_basis else ""
            listed = f"{line.inventory.listed_price:,.2f}" if line.inventory.listed_price else ""
            if line.market_per_copy is not None:
                flag = "*" if line.market_price_type == "ask" else ""
                market = f"{line.market_per_copy:,.2f}{flag}"
            else:
                market = "no data"
            typer.echo(f"{line.card.id:>4}  {_describe(line.card):<52}  "
                       f"{line.inventory.status:<8}  {line.inventory.quantity:>3}  "
                       f"{cost:>10}  {listed:>9}  {market:>10}")
        if any(line.market_price_type == "ask" for line in lines):
            typer.secho("* market stat from ask median, no sold data", fg="yellow")


@app.command("set-targets")
def set_targets_command(
    card_id: Annotated[int, typer.Argument(help="Card id to update")],
    target: Annotated[
        float, typer.Option("--target", help="Target sell price")
    ] = None,
    min_accept: Annotated[
        float, typer.Option("--min", help="Minimum acceptable price")
    ] = None,
) -> None:
    """Set target sell price and minimum acceptable price for a card."""
    from cardtracker.portfolio import set_targets

    _, engine = _engine()
    if target is None and min_accept is None:
        typer.secho("Nothing to update. Pass --target or --min.", fg="red")
        raise typer.Exit(code=1)
    if target is not None and min_accept is not None and min_accept > target:
        typer.secho(f"--min ({min_accept:,.2f}) is above --target ({target:,.2f})",
                    fg="red")
        raise typer.Exit(code=1)
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        inventory = set_targets(session, card_id, target_sell_price=target,
                                min_accept_price=min_accept)
        target_text = (f"{inventory.target_sell_price:,.2f}"
                       if inventory.target_sell_price else "unset")
        min_text = (f"{inventory.min_accept_price:,.2f}"
                    if inventory.min_accept_price else "unset")
        typer.secho(f"Card {card_id} ({_describe(card)}): target {target_text}, "
                    f"min accept {min_text}", fg="green")


@app.command("targets")
def targets_command() -> None:
    """Compare each card's target and min accept prices with the market."""
    from cardtracker.portfolio import inventory_view

    _, engine = _engine()
    with get_session(engine) as session:
        lines = [line for line in inventory_view(session)
                 if line.inventory.target_sell_price or line.inventory.min_accept_price]
        if not lines:
            typer.echo("No targets set. Use 'cardtracker set-targets'.")
            return
        header = (f"{'id':>4}  {'card':<52}  {'market':>10}  {'target':>9}  "
                  f"{'min':>9}  {'verdict':<24}")
        typer.echo(header)
        typer.echo("-" * len(header))
        for line in lines:
            inv = line.inventory
            target_text = f"{inv.target_sell_price:,.2f}" if inv.target_sell_price else ""
            min_text = f"{inv.min_accept_price:,.2f}" if inv.min_accept_price else ""
            if line.market_per_copy is None:
                market_text, verdict, color = "no data", "needs comps + refresh", None
            else:
                flag = "*" if line.market_price_type == "ask" else ""
                market_text = f"{line.market_per_copy:,.2f}{flag}"
                if inv.target_sell_price:
                    gap = (line.market_per_copy - inv.target_sell_price) \
                        / inv.target_sell_price * 100
                    if gap >= 0:
                        verdict, color = f"market above target {gap:+.1f}%", "green"
                    elif inv.min_accept_price and line.market_per_copy >= inv.min_accept_price:
                        verdict, color = f"between min and target {gap:+.1f}%", "yellow"
                    else:
                        verdict, color = f"below target {gap:+.1f}%", "red"
                else:
                    ok = line.market_per_copy >= inv.min_accept_price
                    verdict = "market above min" if ok else "market below min"
                    color = "green" if ok else "red"
            typer.secho(f"{line.card.id:>4}  {_describe(line.card):<52}  "
                        f"{market_text:>10}  {target_text:>9}  {min_text:>9}  "
                        f"{verdict:<24}", fg=color)
        if any(line.market_price_type == "ask" and line.market_per_copy is not None
               for line in lines):
            typer.secho("* market stat from ask median, no sold data", fg="yellow")


@app.command("max-buy")
def max_buy_command(
    card_id: Annotated[int, typer.Argument(help="Card id to analyze")],
    target_roi: Annotated[
        float, typer.Option("--target-roi", help="Target ROI percent")
    ] = None,
    target_profit: Annotated[
        float, typer.Option("--target-profit", help="Target profit in dollars")
    ] = None,
    shipping_cost: Annotated[
        float, typer.Option("--shipping-cost", help="Assumed cost to ship the resale")
    ] = 0.0,
) -> None:
    """Most I should pay for this card to hit a target ROI or profit."""
    from cardtracker.deals import max_buy_price
    from cardtracker.fees import FeeModel

    settings, engine = _engine()
    if target_roi is None and target_profit is None:
        target_roi = 30.0
    with get_session(engine) as session:
        card = _get_card_or_exit(session, card_id)
        try:
            result = max_buy_price(session, card_id, FeeModel.from_settings(settings),
                                   target_roi_pct=target_roi,
                                   target_profit=target_profit,
                                   shipping_cost=shipping_cost)
        except ValueError as exc:
            typer.secho(str(exc), fg="red")
            raise typer.Exit(code=1) from None
        typer.echo(f"Card {card_id}: {_describe(card)}")
        if result is None:
            typer.echo("No market data. Import comps and run refresh-stats first.")
            raise typer.Exit(code=1)
        flag = " [ask median, no sold data]" if result.market_price_type == "ask" else ""
        target_text = (f"{result.target_roi_pct:.0f}% ROI" if result.target_roi_pct
                       is not None else f"{result.target_profit:,.2f} profit")
        typer.echo(f"Market ({result.market_price_type} median 30d){flag}: "
                   f"{result.market:,.2f}")
        typer.echo(f"Net proceeds if sold at market: {result.net_at_market:,.2f}")
        typer.secho(f"Max buy price for {target_text}: {result.max_buy:,.2f} "
                    "(delivered, price plus shipping)", fg="green", bold=True)


@app.command("deals")
def deals_command(
    target_roi: Annotated[
        float, typer.Option("--target-roi", help="Target ROI percent")
    ] = 30.0,
    days: Annotated[
        int, typer.Option("--days", help="Only consider asks seen this recently")
    ] = 14,
    shipping_cost: Annotated[
        float, typer.Option("--shipping-cost", help="Assumed cost to ship the resale")
    ] = 0.0,
) -> None:
    """Active listings priced below my max buy price."""
    from cardtracker.deals import find_deals
    from cardtracker.fees import FeeModel

    settings, engine = _engine()
    with get_session(engine) as session:
        deals = find_deals(session, FeeModel.from_settings(settings),
                           target_roi_pct=target_roi, days=days,
                           shipping_cost=shipping_cost)
        if not deals:
            typer.echo(f"No deals found at {target_roi:.0f}% target ROI among asks "
                       f"seen in the last {days} days. Pull fresh asks with "
                       "'cardtracker pull-comps'.")
            return
        typer.echo(f"Deals at {target_roi:.0f}% target ROI (asks from last {days} days):")
        for deal in deals:
            flag = " *" if deal.market_price_type == "ask" else ""
            typer.echo(f"  card {deal.card.id} {_describe(deal.card)}{flag}")
            typer.secho(f"    {deal.delivered_price:,.2f} delivered vs max buy "
                        f"{deal.max_buy:,.2f} ({deal.discount_pct:.0f}% under), "
                        f"seen {deal.seen_date}", fg="green")
            if deal.title:
                typer.echo(f"    {deal.title}")
            if deal.listing_url:
                typer.echo(f"    {deal.listing_url}")
        if any(d.market_price_type == "ask" for d in deals):
            typer.secho("* market stat from ask median, no sold data", fg="yellow")


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
