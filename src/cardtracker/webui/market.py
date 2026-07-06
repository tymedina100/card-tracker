"""Movers, deals, and prediction accuracy pages."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from cardtracker.deals import find_deals
from cardtracker.predict import backtest, predict_card
from cardtracker.webui.shared import (
    ASK_NOTE,
    GOLD,
    all_cards,
    card_label,
    current_owner,
    fee_model,
    open_session,
    show_flash,
    style_chart,
)


def movers_page() -> None:
    show_flash()
    st.title("📈 Movers")
    horizon = st.slider("Horizon (days)", 7, 90, 30, step=1, key="movers_horizon")
    owner = current_owner()
    with open_session() as session:
        cards = all_cards(session, owner)
        if not cards:
            st.info("No cards yet. Add one in the Cards view.")
            return
        results = [(card, predict_card(session, card.id, horizon_days=horizon,
                                       log=False)) for card in cards]
    up = sorted((r for r in results if str(r[1].direction) == "up"),
                key=lambda r: r[1].confidence, reverse=True)
    down = sorted((r for r in results if str(r[1].direction) == "down"),
                  key=lambda r: r[1].confidence, reverse=True)
    flat = [r for r in results if str(r[1].direction) == "flat"]

    col_up, col_down = st.columns(2)
    for column, badge, group in ((col_up, ":green[▲ Predicted up]", up),
                                 (col_down, ":red[▼ Predicted down]", down)):
        with column, st.container(border=True):
            st.markdown(f"#### {badge}")
            if not group:
                st.caption("none at this horizon")
            for card, result in group:
                with st.expander(
                    f"{card_label(card)}  ({result.confidence:.2f} confidence, "
                    f"{result.expected_move_pct:+.1f}% expected)"
                ):
                    st.write(result.rationale)
    st.caption(f"{len(flat)} card(s) predicted flat at this horizon.")


def deals_page() -> None:
    show_flash()
    st.title("💰 Deals")
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
    st.title("🎯 Prediction accuracy")
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
    with c1, st.container(border=True):
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
