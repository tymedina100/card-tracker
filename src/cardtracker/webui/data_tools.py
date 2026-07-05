"""Data management (CSV import, refresh, scoring) and calculators."""

import tempfile
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from cardtracker.fees import compute_net
from cardtracker.models import Card
from cardtracker.portfolio import market_value
from cardtracker.predict import score_due_predictions
from cardtracker.sources import CsvImportError, CsvImportSource, save_comps
from cardtracker.stats import refresh_snapshots
from cardtracker.webui.shared import (
    all_cards,
    card_label,
    card_picker,
    fee_model,
    flash_and_rerun,
    money,
    open_session,
    show_flash,
)

CSV_EXAMPLE = """card_id,sold_date,price,shipping,currency,title,condition,listing_url
1,2026-06-28,415.00,4.99,USD,1999 Pokemon Base Set Charizard PSA 9,Graded,https://ebay.com/itm/123
1,2026-06-30,432.50,0,USD,Charizard Base Set Holo PSA 9 MINT,Graded,
"""


def data_page() -> None:
    show_flash()
    st.title("📥 Data")

    st.subheader("Import sold comps from CSV")
    st.caption("Export solds from eBay Terapeak or build the file yourself. "
               "Required columns: sold_date (YYYY-MM-DD) and price. Optional: "
               "card_id, shipping, currency, title, condition, listing_url.")
    uploaded = st.file_uploader("Sold-comp CSV", type=["csv"], key="csv_upload")
    with open_session() as session:
        cards = all_cards(session)
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
                missing = [cid for cid in by_card if session.get(Card, cid) is None]
                if missing:
                    st.error(f"Unknown card id(s) in the file: "
                             f"{', '.join(map(str, sorted(missing)))}. Add those "
                             "cards first or pick a card above.")
                else:
                    total = 0
                    for cid, records in by_card.items():
                        total += len(save_comps(session, cid, source, records))
                        refresh_snapshots(session, card_id=cid)
                    skipped = (f", skipped {len(source.skipped)} bad row(s)"
                               if source.skipped else "")
                    flash_and_rerun(f"Imported {total} sold comps across "
                                    f"{len(by_card)} card(s) and refreshed "
                                    f"stats{skipped}.")
    with st.expander("CSV format example"):
        st.code(CSV_EXAMPLE, language="csv")

    st.divider()
    st.subheader("Maintenance")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("**Refresh all stats**")
        st.caption("Recompute every card's rolling stats from its comps. "
                   "Run after importing or pulling new comps.")
        if st.button("🔄 Refresh now", key="refresh_all"):
            with open_session() as session:
                written = refresh_snapshots(session)
            flash_and_rerun(f"Wrote {len(written)} snapshot(s).")
    with c2, st.container(border=True):
        st.markdown("**Score logged predictions**")
        st.caption("Fill in what actually happened for predictions whose "
                   "horizon has passed.")
        if st.button("✅ Score now", key="score_predictions"):
            with open_session() as session:
                scored = score_due_predictions(session)
            flash_and_rerun(f"Scored {scored} prediction(s).")
    st.caption("To refresh automatically on a schedule, keep this running in a "
               "terminal: cardtracker schedule-refresh --interval-hours 12")


def calculator_page() -> None:
    show_flash()
    st.title("🧮 Calculators")
    net_tab, maxbuy_tab = st.tabs(["💵 Net after fees", "🎯 Max buy price"])

    with net_tab:
        c1, c2, c3 = st.columns(3)
        sale_price = c1.number_input("Sale price", 0.0, value=100.0, step=5.0,
                                     format="%.2f", key="net_price")
        shipping_charged = c2.number_input("Shipping the buyer pays", 0.0,
                                           step=0.5, format="%.2f",
                                           key="net_ship_charged")
        tax = c3.number_input("Sales tax eBay collects", 0.0, step=0.5,
                              format="%.2f", key="net_tax")
        c4, c5 = st.columns(2)
        shipping_cost = c4.number_input("What shipping costs me", 0.0, step=0.5,
                                        format="%.2f", key="net_ship_cost")
        promoted = c5.number_input("Promoted listing %", 0.0, 20.0, step=0.5,
                                   format="%.1f", key="net_promoted")
        breakdown = compute_net(fee_model(), sale_price,
                                shipping_charged=shipping_charged,
                                tax_collected=tax, shipping_cost=shipping_cost,
                                promoted_pct=promoted or None)
        rows = [{"item": "gross to seller",
                 "amount": round(breakdown.gross_to_seller, 2)}]
        rows += [{"item": line.label, "amount": -line.amount}
                 for line in breakdown.lines]
        if shipping_cost:
            rows.append({"item": "shipping cost", "amount": -shipping_cost})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        with st.container(border=True):
            st.metric("Net proceeds", money(breakdown.net),
                      delta=f"-{money(breakdown.total_fees + shipping_cost)} "
                      "total costs")
        if tax:
            st.caption("Sales tax raises the fee base but never reaches the "
                       "seller.")

    with maxbuy_tab:
        from cardtracker.deals import max_buy_price

        with open_session() as session:
            card = card_picker(session, key="maxbuy_card")
            if card is None:
                st.info("Add a card first to compute its max buy price.")
                return
            has_market = market_value(session, card.id) is not None
            c1, c2, c3 = st.columns(3)
            mode = c1.radio("Target", ["ROI %", "Profit $"], key="maxbuy_mode",
                            horizontal=True)
            if mode == "ROI %":
                roi = c2.number_input("Target ROI %", 1.0, 500.0, 30.0, step=5.0,
                                      key="maxbuy_roi")
                profit = None
            else:
                profit = c2.number_input("Target profit $", 1.0, value=25.0,
                                         step=5.0, key="maxbuy_profit")
                roi = None
            ship = c3.number_input("Assumed resale shipping cost", 0.0, step=0.5,
                                   format="%.2f", key="maxbuy_ship")
            if not has_market:
                st.info("No market data for this card yet. Import sold comps or "
                        "pull asks, then refresh stats.")
                return
            result = max_buy_price(session, card.id, fee_model(),
                                   target_roi_pct=roi, target_profit=profit,
                                   shipping_cost=ship)
        flag = " *" if result.market_price_type == "ask" else ""
        m1, m2, m3 = st.columns(3)
        with m1, st.container(border=True):
            st.metric(f"Market ({result.market_price_type} median){flag}",
                      money(result.market))
        with m2, st.container(border=True):
            st.metric("Net if sold at market", money(result.net_at_market))
        with m3, st.container(border=True):
            st.metric("Max buy price (delivered)", money(result.max_buy))
        if flag:
            st.caption("* market stat from ask median, no sold data")
        st.caption("Pay this or less, delivered (price plus shipping), and "
                   "selling at today's market hits your target after fees.")
