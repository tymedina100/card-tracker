"""Movers, deals, and prediction accuracy pages."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlmodel import select

from cardtracker import flip
from cardtracker.deals import find_deals
from cardtracker.models import Inventory
from cardtracker.portfolio import assess_cards, effective_market_value
from cardtracker.predict import backtest, predict_card
from cardtracker.webui.shared import (
    ASK_NOTE,
    GOLD,
    all_cards,
    card_label,
    card_picker,
    current_owner,
    fee_model,
    open_session,
    show_flash,
    style_chart,
)
from cardtracker.webui.theme import badge, page_header


def _mover_reason(result) -> str:
    """One-line, deliberately hedged reason for a predicted move."""
    trend = {"up": "Positive recent price trend",
             "down": "Negative recent price trend",
             "flat": "Roughly flat pricing"}[str(result.direction)]
    bucket = flip.confidence_bucket(result.confidence)
    if bucket == "Low":
        return f"{trend}, but limited or noisy sales history."
    return f"{trend}; {bucket.lower()} confidence from the data available."


def _mover_action(result, roi_now: float | None, held: bool) -> str:
    """Suggested action for a mover, tied to holdings when we own it."""
    direction = str(result.direction)
    if held and roi_now is not None:
        if direction == "up":
            return "Hold or list high — momentum is on your side."
        if direction == "down":
            return "Consider listing or selling before it slips further."
        return "Hold; no strong signal either way."
    if direction == "up":
        return "Watch for a buy; upside looks likely."
    if direction == "down":
        return "Hold off buying — it may get cheaper."
    return "No edge right now; keep watching."


def movers_page() -> None:
    show_flash()
    page_header("Movers",
                "Where prices are headed at your horizon — with confidence, a "
                "reason, and a suggested action. Read these as directional, not gospel.")
    horizon = st.slider("Horizon (days)", 7, 90, 30, step=1, key="movers_horizon")
    owner = current_owner()
    with open_session() as session:
        cards = all_cards(session, owner)
        if not cards:
            st.info("No cards yet. Add one in the Cards view.")
            return
        results = [(card, predict_card(session, card.id, horizon_days=horizon,
                                       log=False)) for card in cards]
        # ROI-if-owned comes from the shared assessment engine.
        roi_by_card = {a.card.id: (a.roi_pct, a.status)
                       for a in assess_cards(session, owner=owner)}

    up = sorted((r for r in results if str(r[1].direction) == "up"),
                key=lambda r: r[1].confidence, reverse=True)
    down = sorted((r for r in results if str(r[1].direction) == "down"),
                  key=lambda r: r[1].confidence, reverse=True)
    flat = [r for r in results if str(r[1].direction) == "flat"]

    col_up, col_down = st.columns(2)
    columns = ((col_up, "▲ Predicted Up", "ct-badge-green", up),
               (col_down, "▼ Predicted Down", "ct-badge-red", down))
    for column, heading, css, group in columns:
        with column, st.container(border=True):
            st.markdown(f"#### {heading}")
            if not group:
                st.caption("Nothing at this horizon.")
            for card, result in group:
                roi_now, status = roi_by_card.get(card.id, (None, "watching"))
                held = status in ("owned", "listed")
                bucket = flip.confidence_bucket(result.confidence)
                bucket_css = {"High": "ct-badge-green", "Medium": "ct-badge-gold",
                              "Low": "ct-badge-gray"}[bucket]
                with st.expander(f"{card_label(card)}"):
                    st.markdown(
                        badge(f"Confidence: {bucket}", bucket_css) + " &nbsp; "
                        + badge(str(result.direction).upper(), css),
                        unsafe_allow_html=True)
                    st.caption(f"Expected {result.expected_move_pct:+.1f}% over "
                               f"{result.horizon_days} days")
                    st.markdown(f"**Reason:** {_mover_reason(result)}")
                    st.markdown(f"**Suggested action:** "
                                f"{_mover_action(result, roi_now, held)}")
                    if held and roi_now is not None:
                        st.markdown(f"**Current ROI if sold now:** {roi_now:+.1f}%")
                    with st.expander("Full model rationale"):
                        st.write(result.rationale)
    st.caption(f"{len(flat)} card(s) predicted flat at this horizon.")


def _manual_deal_analyzer() -> None:
    """Judge a single asking price against a manually entered market value.
    Works with no automatic comps at all — everything is typed in."""
    st.subheader("Manual deal analyzer")
    st.caption("Type in an asking price and what you think the card is worth. "
               "We work out the most you should pay and the verdict.")
    owner = current_owner()
    prefill_market = 400.0
    with open_session() as session:
        card = card_picker(session, owner, key="deal_card")
        if card is not None:
            inv = session.exec(
                select(Inventory).where(Inventory.card_id == card.id,
                                        Inventory.owner == owner)
            ).first()
            if inv is not None:
                value, _ = effective_market_value(session, inv)
                if value is not None:
                    prefill_market = round(value, 2)
    c1, c2, c3 = st.columns(3)
    asking = c1.number_input("Asking price (delivered)", 0.0, value=300.0, step=5.0,
                             format="%.2f", key="deal_asking")
    market = c2.number_input("Estimated market value", 0.0, value=prefill_market,
                             step=5.0, format="%.2f", key="deal_market")
    target_roi = c3.number_input("Target ROI %", 0.0, 500.0, 20.0, step=5.0,
                                 key="deal_target_roi")
    c4, c5, c6, c7 = st.columns(4)
    buyer_ship = c4.number_input("Buyer ship charged", 0.0, step=0.5, format="%.2f",
                                 key="deal_buyer_ship")
    seller_ship = c5.number_input("My ship cost", 0.0, step=0.5, format="%.2f",
                                  key="deal_seller_ship")
    supplies = c6.number_input("Supplies cost", 0.0, step=0.25, format="%.2f",
                               key="deal_supplies")
    promoted = c7.number_input("Promoted %", 0.0, 20.0, step=0.5, format="%.1f",
                               key="deal_promoted")

    if not market:
        st.info("Enter an estimated market value to run the numbers.")
        return

    exit_kwargs = dict(buyer_shipping_paid=buyer_ship, seller_shipping_cost=seller_ship,
                       supplies_cost=supplies, promoted_listing_pct=promoted / 100)
    net_at_market = flip.net_proceeds(market, **exit_kwargs).net_proceeds
    max_buy = flip.max_buy_price(market, target_roi, **exit_kwargs)
    # Profit and ROI if bought at the asking price and resold at market.
    profit, roi = flip.profit_and_roi(net_at_market, asking)
    come_down = round(max(0.0, asking - (max_buy or 0.0)), 2)

    if max_buy is not None and asking <= max_buy:
        verdict, css = "BUY", "ct-badge-green"
    elif max_buy is not None and asking <= max_buy * 1.10:
        verdict, css = "NEGOTIATE", "ct-badge-gold"
    else:
        verdict, css = "PASS", "ct-badge-red"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Net if sold at market", f"${net_at_market:,.2f}")
    m2.metric("Expected profit", f"${profit:,.2f}" if profit is not None else "n/a",
              delta=f"{roi:+.1f}% ROI" if roi is not None else None)
    m3.metric("Max buy (delivered)", f"${max_buy:,.2f}" if max_buy is not None else "n/a")
    m4.metric("Come down by", f"${come_down:,.2f}" if come_down else "$0.00")

    tail = (f" Seller needs to come down ${come_down:,.2f}."
            if come_down else " This asking price already works.")
    st.markdown(badge(f"Verdict: {verdict}", css) + f" &nbsp; {tail}",
                unsafe_allow_html=True)


def deals_page() -> None:
    show_flash()
    page_header("Deals",
                "Should you buy this card at this price? Analyze any asking "
                "price by hand, or scan active asks pulled from comps.")
    _manual_deal_analyzer()

    st.divider()
    st.subheader("Active listings under max buy (from comps)")
    st.caption("Automatic scan of pulled ask comps. Empty until comps are pulled "
               "or imported — the manual analyzer above always works.")
    col1, col2, col3 = st.columns(3)
    target_roi = col1.slider("Target ROI %", 5, 100, 30, step=5, key="deals_roi")
    days = col2.slider("Asks seen within (days)", 1, 60, 14, key="deals_days")
    shipping_cost = col3.number_input("Assumed resale shipping cost", 0.0, 100.0,
                                      0.0, step=0.5, key="deals_shipping")
    with open_session() as session:
        deals = find_deals(session, fee_model(), target_roi_pct=float(target_roi),
                           days=days, shipping_cost=shipping_cost,
                           owner=current_owner())
    if not deals:
        st.info(f"No active listings under max buy price at {target_roi}% target "
                "ROI. Pull fresh asks from a card's detail page.")
        return
    rows = [{
        "card": card_label(deal.card),
        "delivered": round(deal.delivered_price, 2),
        "max buy": round(deal.max_buy, 2),
        "under by %": round(deal.discount_pct, 1),
        "seen": deal.seen_date,
        "title": deal.title,
        "listing": deal.listing_url,
    } for deal in deals]
    st.dataframe(
        pd.DataFrame(rows), width="stretch", hide_index=True,
        column_config={"listing": st.column_config.LinkColumn("listing")},
    )
    if any(deal.market_price_type == "ask" for deal in deals):
        st.caption(ASK_NOTE)


def accuracy_page() -> None:
    show_flash()
    page_header("Prediction Accuracy",
                "Backtested hit rate and per-direction accuracy over time.")
    col1, col2 = st.columns(2)
    horizon = col1.slider("Horizon (days)", 7, 90, 30, step=1, key="acc_horizon")
    step = col2.slider("Replay step (days)", 1, 30, 7, key="acc_step")
    with open_session() as session:
        report = backtest(session, horizon_days=horizon, step_days=step,
                          owner=current_owner())
    if not report.scored:
        st.info("Nothing scorable yet. Backtesting needs sold comps spanning at "
                f"least {30 + horizon} days for a card.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Hit rate", f"{report.hit_rate:.1%}",
                  delta=f"{report.hits} of {report.scored}")
    with c2, st.container(border=True):
        st.dataframe(pd.DataFrame(
            [{"predicted": d, "correct": hits, "total": total,
              "accuracy": f"{hits / total:.0%}"}
             for d, (hits, total) in sorted(report.by_direction().items())]
        ), hide_index=True, width="stretch")

    df = pd.DataFrame([{
        "as_of": row.as_of, "correct": int(row.correct),
        "predicted": str(row.predicted), "realized": str(row.realized),
        "confidence": row.confidence,
    } for row in report.rows]).sort_values("as_of")
    df["cumulative hit rate"] = df["correct"].expanding().mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["as_of"], y=df["cumulative hit rate"],
                             mode="lines+markers", name="cumulative hit rate",
                             line={"color": GOLD}))
    fig.update_layout(yaxis={"tickformat": ".0%", "range": [0, 1.05]},
                      xaxis_title="prediction date")
    style_chart(fig, height=350)
    st.plotly_chart(fig, width="stretch")
    with st.expander("Every scored prediction"):
        st.dataframe(df.drop(columns=["cumulative hit rate"]), width="stretch",
                     hide_index=True)
