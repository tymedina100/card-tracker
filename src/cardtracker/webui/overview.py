"""Portfolio overview page."""

import pandas as pd
import streamlit as st

from cardtracker.portfolio import realized_summary, unrealized_summary
from cardtracker.webui.shared import (
    ASK_NOTE,
    card_label,
    current_owner,
    fee_model,
    money,
    open_session,
    show_flash,
)
from cardtracker.webui.theme import page_header


def portfolio_page() -> None:
    show_flash()
    page_header("Portfolio",
                "Cost basis, live market value, and realized and unrealized "
                "profit across your holdings.")
    owner = current_owner()
    with open_session() as session:
        holdings = unrealized_summary(session, fee_model(), owner=owner)
        realized = realized_summary(session, owner=owner)

    cost_total = sum(line.cost_basis for line in holdings)
    market_total = sum(line.market_per_copy * line.quantity
                       for line in holdings if line.market_per_copy is not None)
    unreal_total = sum(line.profit for line in holdings if line.profit is not None)
    realized_total = sum(line.profit for line in realized if line.profit is not None)

    columns = st.columns(4)
    metrics = [
        ("Total cost basis", money(cost_total), None),
        ("Market value of holdings", money(market_total), None),
        ("Unrealized P&L (net of fees)", money(unreal_total), f"{unreal_total:+,.2f}"),
        ("Realized P&L", money(realized_total), f"{realized_total:+,.2f}"),
    ]
    for column, (label, value, delta) in zip(columns, metrics, strict=True):
        with column:
            st.metric(label, value, delta=delta)

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
        st.info("No held cards yet. Add a card in the Cards view, then log a "
                "buy from its detail page.")

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
        st.info("No sells logged yet. Log one from a card's detail page.")
