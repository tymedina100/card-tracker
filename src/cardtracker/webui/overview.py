"""Portfolio overview page: action-first, then the numbers behind the actions."""

import pandas as pd
import streamlit as st

from cardtracker.flip import DEFAULT_STALE_DAYS
from cardtracker.portfolio import assess_cards, realized_summary
from cardtracker.webui.shared import card_label, current_owner, open_session, show_flash
from cardtracker.webui.theme import money_html, page_header, rec_badge

# Statuses that represent something you actually hold.
HELD = ("owned", "listed")


def _action_card(count: int, title: str, subtitle: str, tone: str = "") -> str:
    """HTML for one 'Today's Actions' tile."""
    css = "ct-action-card" + (f" {tone}" if tone else "")
    return (f'<div class="{css}"><div class="ct-action-count">{count}</div>'
            f'<div class="ct-action-title">{title}</div>'
            f'<div class="ct-action-sub">{subtitle}</div></div>')


def _render_bucket(title: str, assessments: list, *, empty: str) -> None:
    """List the cards in one action bucket with their key flip numbers."""
    with st.expander(f"{title}  ·  {len(assessments)}", expanded=False):
        if not assessments:
            st.caption(empty)
            return
        for a in assessments:
            cols = st.columns([4, 2, 2, 2])
            cols[0].markdown(f"**{card_label(a.card)}**")
            cols[1].markdown(
                "Net: " + money_html(a.net_if_sold), unsafe_allow_html=True)
            cols[2].markdown(
                "P&L: " + money_html(a.profit, signed=True, color=True),
                unsafe_allow_html=True)
            roi = f"{a.roi_pct:+.1f}%" if a.roi_pct is not None else "n/a"
            cols[3].markdown(f"{rec_badge(a.recommendation)} &nbsp; {roi}",
                             unsafe_allow_html=True)


def portfolio_page() -> None:
    show_flash()
    page_header("Portfolio",
                "What you're into your cards for, what they're worth, and what "
                "to do next — net of eBay fees.")
    owner = current_owner()
    with open_session() as session:
        assessments = assess_cards(session, owner=owner)
        realized = realized_summary(session, owner=owner)

    held = [a for a in assessments if a.status in HELD and a.quantity > 0]

    # ---- Headline metrics (manual-market aware) ----
    cost_total = sum(a.cost_basis for a in held)
    market_total = sum((a.market_value or 0) * a.quantity for a in held)
    unreal_total = sum(a.profit for a in held if a.profit is not None)
    realized_total = sum(line.profit for line in realized if line.profit is not None)

    m = st.columns(4)
    m[0].metric("Total cost basis", f"${cost_total:,.2f}")
    m[1].metric("Market value of holdings", f"${market_total:,.2f}")
    m[2].metric("Unrealized P&L (net of fees)", f"${unreal_total:,.2f}",
                delta=f"{unreal_total:+,.2f}")
    m[3].metric("Realized P&L", f"${realized_total:,.2f}",
                delta=f"{realized_total:+,.2f}")

    # ---- Today's Actions ----
    st.subheader("Today's Actions")
    sell_candidates = [a for a in held if a.roi_pct is not None
                       and a.roi_pct >= a.target_roi_pct]
    underwater = [a for a in held if a.is_underwater]
    deals = [a for a in assessments if a.status == "watching"
             and a.inventory.lowest_active_ask is not None and a.max_buy is not None
             and a.inventory.lowest_active_ask <= a.max_buy]
    stale = [a for a in held if (a.days_held or 0) > DEFAULT_STALE_DAYS]
    listed = [a for a in assessments if a.status == "listed"]
    missing = [a for a in held if a.missing_market]

    buckets = [
        ("Sell Candidates", sell_candidates,
         "Owned/listed at or above target ROI.", "is-good"),
        ("Underwater Cards", underwater,
         "Net if sold today is below cost.", "is-alert"),
        ("Deals Under Max Buy", deals,
         "Watched cards asking at/under max buy.", "is-good"),
        ("Stale Inventory", stale,
         f"Held longer than {DEFAULT_STALE_DAYS} days.", ""),
        ("Listed Cards", listed, "Currently up for sale.", ""),
        ("Missing Market Value", missing,
         "Owned/listed with no market value.", "is-alert" if missing else ""),
    ]
    row1 = st.columns(3)
    row2 = st.columns(3)
    for col, (title, items, sub, tone) in zip(row1 + row2, buckets, strict=True):
        col.markdown(_action_card(len(items), title, sub, tone),
                     unsafe_allow_html=True)

    st.write("")
    for title, items, _sub, _tone in buckets:
        empties = {
            "Sell Candidates": "Nothing has hit its target ROI yet.",
            "Underwater Cards": "No cards are underwater. Nice.",
            "Deals Under Max Buy": "No watched cards are under max buy. Add an "
                                   "asking price on a watched card's detail page.",
            "Stale Inventory": "Nothing has gone stale.",
            "Listed Cards": "No active listings.",
            "Missing Market Value": "Every held card has a market value set.",
        }
        _render_bucket(title, items, empty=empties[title])

    # ---- Holdings table ----
    st.subheader("Holdings")
    if held:
        rows = []
        for a in held:
            rows.append({
                "card": card_label(a.card),
                "status": a.status,
                "qty": a.quantity,
                "cost basis": round(a.cost_basis, 2),
                "market/copy": round(a.market_value, 2) if a.market_value is not None else None,
                "net if sold": round(a.net_if_sold, 2) if a.net_if_sold is not None else None,
                "profit": round(a.profit, 2) if a.profit is not None else None,
                "roi %": round(a.roi_pct, 1) if a.roi_pct is not None else None,
                "recommendation": str(a.recommendation),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No held cards yet. Add a card in the Cards view, then log a "
                "buy from its detail page.")

    # ---- Realized sales ----
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
