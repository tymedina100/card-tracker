"""Data management (CSV import/export, refresh, backup, reset) and calculators."""

import tempfile
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from cardtracker import flip
from cardtracker.models import Card, Category, Grader
from cardtracker.portfolio import assess_cards, delete_card, market_value
from cardtracker.predict import score_due_predictions
from cardtracker.sources import CsvImportError, CsvImportSource, save_comps
from cardtracker.stats import refresh_snapshots
from cardtracker.webui.shared import (
    all_cards,
    card_label,
    card_picker,
    current_owner,
    flash_and_rerun,
    open_session,
    show_flash,
)
from cardtracker.webui.theme import page_header

CSV_EXAMPLE = """card_id,sold_date,price,shipping,currency,title,condition,listing_url
1,2026-06-28,415.00,4.99,USD,1999 Pokemon Base Set Charizard PSA 9,Graded,https://ebay.com/itm/123
1,2026-06-30,432.50,0,USD,Charizard Base Set Holo PSA 9 MINT,Graded,
"""

# Columns of the cards export/import file. Kept in one place so export and
# import always agree on the schema.
CARD_COLUMNS = ["category", "player_or_character", "set_name", "year",
                "card_number", "variation_or_parallel", "grader", "grade",
                "cert_number", "notes"]


def _cards_dataframe(cards: list[Card]) -> pd.DataFrame:
    return pd.DataFrame([{
        "id": c.id,
        "category": str(c.category),
        "player_or_character": c.player_or_character,
        "set_name": c.set_name,
        "year": c.year,
        "card_number": c.card_number,
        "variation_or_parallel": c.variation_or_parallel,
        "grader": str(c.grader),
        "grade": c.grade,
        "cert_number": c.cert_number or "",
        "notes": c.notes,
    } for c in cards])


def _portfolio_dataframe(assessments: list) -> pd.DataFrame:
    """The full flip picture per card, for an export you can open in a sheet."""
    return pd.DataFrame([{
        "card": card_label(a.card),
        "category": str(a.card.category),
        "status": a.status,
        "quantity": a.quantity,
        "cost_basis": round(a.cost_basis, 2),
        "market_value": a.market_value,
        "net_if_sold": a.net_if_sold,
        "profit": a.profit,
        "roi_pct": a.roi_pct,
        "target_roi_pct": a.target_roi_pct,
        "needed_sale_price": a.needed_sale_price,
        "recommendation": str(a.recommendation),
    } for a in assessments])


def _import_cards_from_df(df: pd.DataFrame, owner: str) -> tuple[int, list[str]]:
    """Insert cards from an uploaded dataframe. Returns (added, errors)."""
    errors: list[str] = []
    added = 0
    valid_categories = {c.value for c in Category}
    valid_graders = {g.value for g in Grader}
    with open_session() as session:
        for i, row in df.iterrows():
            line = i + 2  # header is line 1
            category = str(row.get("category", "")).strip().lower()
            player = str(row.get("player_or_character", "")).strip()
            set_name = str(row.get("set_name", "")).strip()
            if category not in valid_categories:
                errors.append(f"line {line}: category '{category}' is not "
                              f"{' or '.join(sorted(valid_categories))}")
                continue
            if not player or not set_name:
                errors.append(f"line {line}: player_or_character and set_name required")
                continue
            grader = str(row.get("grader", "raw")).strip() or "raw"
            if grader not in valid_graders:
                grader = "raw"
            try:
                year = int(float(row.get("year", 0) or 0))
            except (ValueError, TypeError):
                year = 0
            session.add(Card(
                owner=owner,
                category=Category(category),
                player_or_character=player,
                set_name=set_name,
                year=year,
                card_number=str(row.get("card_number", "") or "").strip(),
                variation_or_parallel=str(row.get("variation_or_parallel", "") or "").strip(),
                grader=Grader(grader),
                grade=str(row.get("grade", "") or "").strip(),
                cert_number=(str(row.get("cert_number", "")).strip() or None),
                notes=str(row.get("notes", "") or "").strip(),
            ))
            added += 1
        session.commit()
    return added, errors


def data_page() -> None:
    show_flash()
    page_header("Data",
                "Import comps and cards, refresh stats, and back up your "
                "collection. Your data is only as safe as your last export.")
    owner = current_owner()

    st.warning(
        "**Back up regularly.** On the free hosted (Streamlit Community Cloud) "
        "tier, storage is temporary — the database can be wiped on redeploys or "
        "when the app sleeps. Export your portfolio and cards below and keep the "
        "files. A local install stores a durable database on disk.",
        icon="💾",
    )

    # ---- Import sold comps (existing) ----
    st.subheader("Import sold comps from CSV")
    st.caption("Export solds from eBay Terapeak or build the file yourself. "
               "Required columns: sold_date (YYYY-MM-DD) and price. Optional: "
               "card_id, shipping, currency, title, condition, listing_url.")
    uploaded = st.file_uploader("Sold-comp CSV", type=["csv"], key="csv_upload")
    with open_session() as session:
        cards = all_cards(session, owner)
    c1, c2 = st.columns(2)
    options: list[Card | None] = [None] + cards
    default_card = c1.selectbox(
        "Card for rows without a card_id column", options,
        format_func=lambda c: "rows include their own card_id" if c is None
        else card_label(c),
        key="csv_default_card")
    skip_bad = c2.checkbox("Skip invalid rows instead of stopping", key="csv_skip")
    if uploaded is not None and st.button("Import", type="primary", key="csv_import"):
        tmp = Path(tempfile.gettempdir()) / f"cardtracker_upload_{uploaded.name}"
        tmp.write_bytes(uploaded.getvalue())
        source = CsvImportSource(tmp,
                                 default_card_id=default_card.id if default_card
                                 else None,
                                 skip_bad_rows=skip_bad)
        try:
            rows = source.read_rows()
        except CsvImportError as exc:
            st.error(f"Import failed: {exc}")
        else:
            by_card = defaultdict(list)
            for row in rows:
                by_card[row.card_id].append(row.record)
            with open_session() as session:
                missing = [cid for cid in by_card
                           if (c := session.get(Card, cid)) is None
                           or c.owner != owner]
                if missing:
                    st.error(f"Unknown card id(s) in the file: "
                             f"{', '.join(map(str, sorted(missing)))}. Add those "
                             "cards first or pick a card above.")
                else:
                    total = 0
                    for cid, records in by_card.items():
                        total += len(save_comps(session, cid, source, records))
                        refresh_snapshots(session, card_id=cid, owner=owner)
                    skipped = (f", skipped {len(source.skipped)} bad row(s)"
                               if source.skipped else "")
                    flash_and_rerun(f"Imported {total} sold comps across "
                                    f"{len(by_card)} card(s) and refreshed "
                                    f"stats{skipped}.")
    with st.expander("CSV format example"):
        st.code(CSV_EXAMPLE, language="csv")

    # ---- Maintenance (existing) ----
    st.divider()
    st.subheader("Maintenance")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Refresh all stats**")
        st.caption("Recompute every card's rolling stats from its comps. "
                   "Run after importing or pulling new comps.")
        if st.button("🔄 Refresh now", key="refresh_all"):
            with open_session() as session:
                written = refresh_snapshots(session, owner=owner)
            flash_and_rerun(f"Wrote {len(written)} snapshot(s).")
    with c2, st.container(border=True):
        st.markdown("**Score logged predictions**")
        st.caption("Fill in what actually happened for predictions whose "
                   "horizon has passed.")
        if st.button("✅ Score now", key="score_predictions"):
            with open_session() as session:
                scored = score_due_predictions(session, owner=owner)
            flash_and_rerun(f"Scored {scored} prediction(s).")

    # ---- Backup: export & import ----
    st.divider()
    st.subheader("Backup: export & import")
    with open_session() as session:
        export_cards = all_cards(session, owner)
        assessments = assess_cards(session, owner=owner)
    e1, e2, e3 = st.columns(3)
    if assessments:
        e1.download_button(
            "⬇️ Export portfolio CSV",
            _portfolio_dataframe(assessments).to_csv(index=False).encode("utf-8"),
            file_name="cardtracker_portfolio.csv", mime="text/csv",
            key="export_portfolio", help="Every card with cost, market, net, "
            "profit, ROI, and recommendation.")
    else:
        e1.caption("No holdings to export yet.")
    if export_cards:
        e2.download_button(
            "⬇️ Download cards backup",
            _cards_dataframe(export_cards).to_csv(index=False).encode("utf-8"),
            file_name="cardtracker_cards.csv", mime="text/csv",
            key="export_cards", help="Your card catalog, re-importable below.")
    else:
        e2.caption("No cards to export yet.")

    with e3.popover("⬆️ Import cards from CSV"):
        st.caption(f"Columns: {', '.join(CARD_COLUMNS)}. Extra columns are ignored.")
        cards_file = st.file_uploader("Cards CSV", type=["csv"], key="cards_import_file")
        if cards_file is not None and st.button("Import cards", key="cards_import_btn"):
            try:
                df = pd.read_csv(cards_file)
            except Exception as exc:  # noqa: BLE001 surface any parse error in UI
                st.error(f"Could not read CSV: {exc}")
            else:
                added, errors = _import_cards_from_df(df, owner)
                if errors:
                    st.warning("Some rows were skipped:\n\n" + "\n".join(
                        f"- {e}" for e in errors[:20]))
                if added:
                    flash_and_rerun(f"Imported {added} card(s).")
                else:
                    st.error("No cards imported. Check the column names and values.")

    # ---- Danger zone: reset demo data ----
    st.divider()
    with st.expander("⚠️ Reset — delete all my cards"):
        st.caption("Permanently deletes every card in your collection along with "
                   "its comps, stats, buys, sells, and predictions. Export a "
                   "backup first. This cannot be undone.")
        confirm = st.checkbox("I understand — delete everything", key="reset_confirm")
        if st.button("🗑️ Delete all my data", disabled=not confirm, key="reset_btn"):
            with open_session() as session:
                ids = [c.id for c in all_cards(session, owner)]
                for cid in ids:
                    delete_card(session, cid, owner=owner)
            flash_and_rerun(f"Deleted {len(ids)} card(s) and all related data.")


def _net_calculator() -> None:
    """Net-after-fees, driven entirely by the flip engine."""
    c1, c2, c3 = st.columns(3)
    sale_price = c1.number_input("Sale price", 0.0, value=100.0, step=5.0,
                                 format="%.2f", key="net_price")
    buyer_ship = c2.number_input("Shipping buyer pays", 0.0, step=0.5,
                                 format="%.2f", key="net_ship_charged")
    tax = c3.number_input("Sales tax eBay collects", 0.0, step=0.5, format="%.2f",
                          key="net_tax")
    c4, c5, c6 = st.columns(3)
    seller_ship = c4.number_input("Seller shipping cost", 0.0, step=0.5,
                                  format="%.2f", key="net_ship_cost")
    supplies = c5.number_input("Supplies cost", 0.0, step=0.25, format="%.2f",
                               key="net_supplies")
    promoted = c6.number_input("Promoted listing %", 0.0, 20.0, step=0.5,
                               format="%.1f", key="net_promoted")
    c7, c8 = st.columns(2)
    fee_rate = c7.number_input("Fee rate %", 0.0, 30.0,
                               value=flip.DEFAULT_FEE_RATE * 100, step=0.25,
                               format="%.2f", key="net_fee_rate")
    fixed_fee = c8.number_input("Fixed order fee", 0.0,
                                value=flip.DEFAULT_FIXED_ORDER_FEE, step=0.05,
                                format="%.2f", key="net_fixed_fee")

    result = flip.net_proceeds(
        sale_price, buyer_shipping_paid=buyer_ship, sales_tax_collected=tax,
        seller_shipping_cost=seller_ship, supplies_cost=supplies,
        promoted_listing_pct=promoted / 100, fee_rate=fee_rate / 100,
        fixed_order_fee=fixed_fee)

    rows = [
        {"item": "Gross sale total (buyer pays)", "amount": result.gross_sale_total},
        {"item": f"eBay final value fee ({fee_rate:.2f}% + ${fixed_fee:.2f})",
         "amount": -result.ebay_fee},
        {"item": f"Promoted listing fee ({promoted:.1f}%)",
         "amount": -result.promoted_fee},
        {"item": "Seller shipping cost", "amount": -seller_ship},
        {"item": "Supplies cost", "amount": -supplies},
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    m1, m2 = st.columns(2)
    m1.metric("Net proceeds", f"${result.net_proceeds:,.2f}")
    margin = result.net_margin_pct
    m2.metric("Net margin", f"{margin:.1f}%" if margin is not None else "n/a")
    if tax:
        st.caption("Sales tax raises the fee base but never reaches the seller.")


def _max_buy_calculator() -> None:
    """Max buy price from a manually entered (or comp-derived) market value."""
    owner = current_owner()
    prefill = 400.0
    with open_session() as session:
        card = card_picker(session, owner, key="maxbuy_card")
        if card is not None:
            market = market_value(session, card.id)
            if market is not None:
                prefill = round(market[0], 2)

    c1, c2, c3 = st.columns(3)
    expected = c1.number_input("Expected sale / market value", 0.0, value=prefill,
                               step=5.0, format="%.2f", key="maxbuy_market")
    target_roi = c2.number_input("Target ROI %", 0.0, 500.0, 20.0, step=5.0,
                                 key="maxbuy_roi")
    asking = c3.number_input("Asking price (optional, 0 = none)", 0.0, step=5.0,
                             format="%.2f", key="maxbuy_asking")
    c4, c5, c6 = st.columns(3)
    ship = c4.number_input("Shipping + supplies cost", 0.0, step=0.5, format="%.2f",
                           key="maxbuy_ship")
    fee_rate = c5.number_input("Fee rate %", 0.0, 30.0,
                               value=flip.DEFAULT_FEE_RATE * 100, step=0.25,
                               format="%.2f", key="maxbuy_fee_rate")
    fixed_fee = c6.number_input("Fixed order fee", 0.0,
                                value=flip.DEFAULT_FIXED_ORDER_FEE, step=0.05,
                                format="%.2f", key="maxbuy_fixed_fee")

    if not expected:
        st.info("Enter an expected sale / market value to compute a max buy price.")
        return

    kwargs = dict(seller_shipping_cost=ship, fee_rate=fee_rate / 100,
                  fixed_order_fee=fixed_fee)
    net_at_market = flip.net_proceeds(expected, **kwargs).net_proceeds
    max_buy = flip.max_buy_price(expected, target_roi, **kwargs)
    # A safety buffer: pay a little under max buy to leave room for a soft market.
    safety = round(max_buy * 0.95, 2) if max_buy is not None else None

    m1, m2, m3 = st.columns(3)
    m1.metric("Net if sold at market", f"${net_at_market:,.2f}")
    m2.metric("Max buy (delivered)", f"${max_buy:,.2f}" if max_buy is not None else "n/a")
    m3.metric("Safe buy (5% buffer)", f"${safety:,.2f}" if safety is not None else "n/a")
    if asking and max_buy is not None:
        if asking <= max_buy:
            st.success(f"At ${asking:,.2f} this clears your {target_roi:.0f}% "
                       f"target with ${max_buy - asking:,.2f} to spare. Buy.")
        else:
            st.error(f"At ${asking:,.2f} you're ${asking - max_buy:,.2f} over max "
                     f"buy for a {target_roi:.0f}% return. Negotiate or pass.")
    st.caption("Pay at or below max buy, delivered (price plus shipping), and "
               "selling at your expected market hits the target after fees.")


def calculator_page() -> None:
    show_flash()
    page_header("Calculators",
                "Net-after-fees and max-buy-price, live as you type.")
    net_tab, maxbuy_tab = st.tabs(["💵 Net after fees", "🎯 Max buy price"])
    with net_tab:
        _net_calculator()
    with maxbuy_tab:
        _max_buy_calculator()
