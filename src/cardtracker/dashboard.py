"""Streamlit dashboard for cardtracker.

Run with: cardtracker dashboard
Or directly: streamlit run src/cardtracker/dashboard.py

Every view opens its own session and reads live from the SQLite database.
Predictions rendered here are never logged, so browsing the dashboard does
not write to the predictions table.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlmodel import select

from cardtracker.config import load_settings
from cardtracker.db import get_engine, get_session, init_db
from cardtracker.deals import find_deals
from cardtracker.fees import FeeModel
from cardtracker.models import Card, Comp, PriceSnapshot, describe_card
from cardtracker.portfolio import (
    cost_basis_summary,
    realized_summary,
    unrealized_summary,
)
from cardtracker.predict import backtest, predict_card
from cardtracker.stats import latest_snapshots

st.set_page_config(page_title="cardtracker", layout="wide")

ASK_NOTE = "* market stat from ask median, no sold data"


def money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "n/a"


@st.cache_resource
def _engine():
    settings = load_settings()
    engine = get_engine(settings)
    init_db(engine)
    return settings, engine


settings, engine = _engine()
fee_model = FeeModel.from_settings(settings)


def card_label(card: Card) -> str:
    return f"{card.id}: {describe_card(card)}"


def portfolio_page() -> None:
    st.header("Portfolio")
    with get_session(engine) as session:
        holdings = unrealized_summary(session, fee_model)
        realized = realized_summary(session)
    cost_total = sum(line.cost_basis for line in holdings)
    market_total = sum(line.market_per_copy * line.quantity
                       for line in holdings if line.market_per_copy is not None)
    unreal_lines = [line for line in holdings if line.profit is not None]
    unreal_total = sum(line.profit for line in unreal_lines)
    realized_lines = [line for line in realized if line.profit is not None]
    realized_total = sum(line.profit for line in realized_lines)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total cost basis", money(cost_total))
    c2.metric("Market value of holdings", money(market_total))
    c3.metric("Unrealized P&L (net of fees)", money(unreal_total),
              delta=f"{unreal_total:+,.2f}")
    c4.metric("Realized P&L", money(realized_total),
              delta=f"{realized_total:+,.2f}")

    st.subheader("Holdings")
    if holdings:
        rows = []
        for line in holdings:
            flag = " *" if line.market_price_type == "ask" else ""
            rows.append({
                "card": card_label(line.card),
                "qty": line.quantity,
                "cost basis": round(line.cost_basis, 2),
                "market/copy": (round(line.market_per_copy, 2)
                                if line.market_per_copy is not None else None),
                "stat": (line.market_price_type or "no data") + flag,
                "net value": (round(line.net_value, 2)
                              if line.net_value is not None else None),
                "profit": round(line.profit, 2) if line.profit is not None else None,
                "roi %": round(line.roi_pct, 1) if line.roi_pct is not None else None,
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        if any(line.market_price_type == "ask" for line in holdings):
            st.caption(ASK_NOTE)
    else:
        st.info("No held cards. Log a buy with: cardtracker log-buy")

    st.subheader("Realized sales")
    if realized:
        rows = [{
            "date": line.sale_date,
            "card": card_label(line.card),
            "sale": round(line.sale_price, 2),
            "fees": round(line.fees, 2),
            "shipping": round(line.shipping_cost, 2),
            "net": round(line.net, 2),
            "cost": (round(line.cost_allocated, 2)
                     if line.cost_allocated is not None else None),
            "profit": round(line.profit, 2) if line.profit is not None else None,
            "roi %": round(line.roi_pct, 1) if line.roi_pct is not None else None,
        } for line in realized]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No sells logged yet.")


def card_page() -> None:
    st.header("Card detail")
    with get_session(engine) as session:
        cards = session.exec(select(Card).order_by(Card.id)).all()
        if not cards:
            st.info("No cards yet. Add one with: cardtracker add-card")
            return
        card = st.selectbox("Card", cards, format_func=card_label)
        comps = session.exec(select(Comp).where(Comp.card_id == card.id)).all()
        snapshots = latest_snapshots(session, card.id)
        snapshot_history = session.exec(
            select(PriceSnapshot).where(PriceSnapshot.card_id == card.id)
            .order_by(PriceSnapshot.as_of_date)
        ).all()
        prediction = predict_card(session, card.id, log=False)
        basis = cost_basis_summary(session, card_id=card.id)
        holdings = [line for line in unrealized_summary(session, fee_model)
                    if line.card.id == card.id]
        from cardtracker.portfolio import get_or_create_inventory
        inventory = get_or_create_inventory(session, card.id)

        st.subheader("Price history: ask vs sold")
        if comps:
            df = pd.DataFrame({
                "date": [c.sold_date_or_seen_date for c in comps],
                "delivered price": [c.price + c.shipping for c in comps],
                "type": [str(c.price_type) for c in comps],
                "title": [c.title_raw for c in comps],
            })
            fig = go.Figure()
            colors = {"sold": "#2ca02c", "ask": "#888888"}
            for price_type in ("sold", "ask"):
                sub = df[df["type"] == price_type]
                if not sub.empty:
                    fig.add_trace(go.Scatter(
                        x=sub["date"], y=sub["delivered price"], mode="markers",
                        name=f"{price_type} comps", text=sub["title"],
                        marker={"color": colors[price_type], "size": 8},
                    ))
            history = pd.DataFrame({
                "date": [s.as_of_date for s in snapshot_history],
                "median_30d": [s.median_30d for s in snapshot_history],
                "type": [str(s.price_type) for s in snapshot_history],
            }).dropna()
            for price_type in ("sold", "ask"):
                sub = history[history["type"] == price_type]
                if len(sub) > 1:
                    fig.add_trace(go.Scatter(
                        x=sub["date"], y=sub["median_30d"], mode="lines",
                        name=f"{price_type} 30d median",
                        line={"color": colors[price_type], "dash": "dot"},
                    ))
            fig.update_layout(height=420, xaxis_title=None,
                              yaxis_title="delivered price")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No comps yet. Pull asks or import a sold CSV.")

        left, right = st.columns(2)
        with left:
            st.subheader("Stat line")
            if snapshots:
                fields = ["as_of_date", "median_7d", "median_30d", "median_90d",
                          "mean_30d", "sale_count_30d", "sale_count_90d", "low_30d",
                          "high_30d", "spread_30d", "volatility_30d", "velocity_30d",
                          "trend_slope_30d", "trend_slope_90d"]
                table = {price_type: {f: getattr(snap, f) for f in fields}
                         for price_type, snap in snapshots.items()}
                st.dataframe(pd.DataFrame(table), width="stretch")
            else:
                st.info("No snapshots. Run: cardtracker refresh-stats")

        with right:
            st.subheader("Prediction")
            arrows = {"up": "▲ UP", "down": "▼ DOWN", "flat": "► FLAT"}
            st.metric(f"{prediction.horizon_days} day call",
                      arrows[str(prediction.direction)],
                      delta=f"confidence {prediction.confidence:.2f}")
            st.write(prediction.rationale)

            st.subheader("Position")
            per_copy = basis[0].cost_per_copy if basis else None
            profit = holdings[0].profit if holdings else None
            roi = holdings[0].roi_pct if holdings else None
            rows = {
                "status": str(inventory.status),
                "quantity": inventory.quantity,
                "cost basis": money(inventory.cost_basis),
                "cost per copy": money(per_copy),
                "profit if sold now": money(profit) if profit is not None else "n/a",
                "ROI if sold now": f"{roi:+.1f}%" if roi is not None else "n/a",
                "listed price": money(inventory.listed_price),
                "target sell": money(inventory.target_sell_price),
                "min accept": money(inventory.min_accept_price),
            }
            st.dataframe(pd.DataFrame(rows.items(), columns=["", "value"]),
                         width="stretch", hide_index=True)


def movers_page() -> None:
    st.header("Movers")
    horizon = st.slider("Horizon (days)", 7, 90, 30, step=1)
    with get_session(engine) as session:
        cards = session.exec(select(Card).order_by(Card.id)).all()
        if not cards:
            st.info("No cards yet.")
            return
        results = [(card, predict_card(session, card.id, horizon_days=horizon,
                                       log=False)) for card in cards]
    up = sorted((r for r in results if str(r[1].direction) == "up"),
                key=lambda r: r[1].confidence, reverse=True)
    down = sorted((r for r in results if str(r[1].direction) == "down"),
                  key=lambda r: r[1].confidence, reverse=True)
    flat = [r for r in results if str(r[1].direction) == "flat"]

    col_up, col_down = st.columns(2)
    for column, title, group in ((col_up, "Predicted up", up),
                                 (col_down, "Predicted down", down)):
        with column:
            st.subheader(title)
            if not group:
                st.caption("none")
            for card, result in group:
                with st.expander(
                    f"{card_label(card)}  |  confidence {result.confidence:.2f}, "
                    f"expected {result.expected_move_pct:+.1f}%"
                ):
                    st.write(result.rationale)
    st.caption(f"{len(flat)} card(s) predicted flat at this horizon.")


def deals_page() -> None:
    st.header("Deals")
    col1, col2, col3 = st.columns(3)
    target_roi = col1.slider("Target ROI %", 5, 100, 30, step=5)
    days = col2.slider("Asks seen within (days)", 1, 60, 14)
    shipping_cost = col3.number_input("Assumed resale shipping cost", 0.0, 100.0,
                                      0.0, step=0.5)
    with get_session(engine) as session:
        deals = find_deals(session, fee_model, target_roi_pct=float(target_roi),
                           days=days, shipping_cost=shipping_cost)
    if not deals:
        st.info(f"No active listings under max buy price at {target_roi}% target "
                "ROI. Pull fresh asks with: cardtracker pull-comps")
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
    st.header("Prediction accuracy")
    col1, col2 = st.columns(2)
    horizon = col1.slider("Horizon (days)", 7, 90, 30, step=1)
    step = col2.slider("Replay step (days)", 1, 30, 7)
    with get_session(engine) as session:
        report = backtest(session, horizon_days=horizon, step_days=step)
    if not report.scored:
        st.info("Nothing scorable yet. Backtesting needs sold comps spanning at "
                f"least {30 + horizon} days for a card.")
        return
    c1, c2 = st.columns(2)
    c1.metric("Hit rate", f"{report.hit_rate:.1%}",
              delta=f"{report.hits} of {report.scored}")
    by_direction = report.by_direction()
    c2.dataframe(pd.DataFrame(
        [{"predicted": d, "correct": hits, "total": total,
          "accuracy": f"{hits / total:.0%}"}
         for d, (hits, total) in sorted(by_direction.items())]
    ), hide_index=True)

    df = pd.DataFrame([{
        "as_of": row.as_of, "correct": int(row.correct),
        "predicted": str(row.predicted), "realized": str(row.realized),
        "confidence": row.confidence,
    } for row in report.rows]).sort_values("as_of")
    df["cumulative hit rate"] = df["correct"].expanding().mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["as_of"], y=df["cumulative hit rate"],
                             mode="lines+markers", name="cumulative hit rate"))
    fig.update_layout(height=350, yaxis={"tickformat": ".0%", "range": [0, 1.05]},
                      xaxis_title="prediction date")
    st.plotly_chart(fig, width="stretch")
    with st.expander("Every scored prediction"):
        st.dataframe(df.drop(columns=["cumulative hit rate"]), width="stretch",
                     hide_index=True)


PAGES = {
    "Portfolio": portfolio_page,
    "Card": card_page,
    "Movers": movers_page,
    "Deals": deals_page,
    "Accuracy": accuracy_page,
}

st.sidebar.title("cardtracker")
choice = st.sidebar.radio("View", list(PAGES))
PAGES[choice]()
