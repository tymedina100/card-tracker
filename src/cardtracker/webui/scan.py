"""Scan page: enter the price you see on a card and get a graded buy verdict.

Camera / photo scanning is not built yet — this is the pricing brain it will
feed. For now you pick a card and type the price; the grade compares it to the
card's market value on a red-to-green scale. Because it reads market value the
same manual-first way as everything else, a price saved before comps exist gets
graded automatically the moment comps (or a manual value) land.
"""

import pandas as pd
import streamlit as st
from sqlmodel import select

from cardtracker import flip
from cardtracker.models import Card, Inventory
from cardtracker.portfolio import (
    effective_market_value,
    grade_scanned_card,
    set_scanned_price,
)
from cardtracker.webui.shared import (
    card_label,
    card_picker,
    current_owner,
    flash_and_rerun,
    open_session,
    show_flash,
)
from cardtracker.webui.theme import buy_meter, page_header, rating_badge, rating_dot


def _grade_price(card, price: float, market_override: float | None,
                 target_roi: float, owner: str) -> flip.BuyGrade:
    """Grade a price for the (optional) selected card. A typed market override
    wins so you can grade before comps exist; otherwise we use the card's
    effective (manual-first) market value and its saved resale assumptions."""
    market = market_override if market_override else None
    exit_kwargs: dict = {}
    if card is not None:
        with open_session() as session:
            inv = session.exec(
                select(Inventory).where(Inventory.card_id == card.id,
                                        Inventory.owner == owner)
            ).first()
            if inv is not None:
                if market is None:
                    market, _ = effective_market_value(session, inv)
                exit_kwargs = {
                    "buyer_shipping_paid": inv.buyer_shipping_paid,
                    "seller_shipping_cost": inv.seller_shipping_cost,
                    "supplies_cost": inv.supplies_cost,
                    "promoted_listing_pct": (inv.promoted_listing_pct or 0.0) / 100,
                }
    return flip.grade_buy(price, market, target_roi_pct=target_roi, **exit_kwargs)


def _render_grade(grade: flip.BuyGrade) -> None:
    st.markdown(buy_meter(grade.score, grade.rating), unsafe_allow_html=True)
    cols = st.columns(3)
    cols[0].metric("Your price", f"${grade.price:,.2f}")
    cols[1].metric("Market value",
                   f"${grade.market_value:,.2f}" if grade.market_value is not None
                   else "not set yet")
    cols[2].metric("Max buy (target ROI)",
                   f"${grade.max_buy:,.2f}" if grade.max_buy is not None else "n/a")
    if grade.roi_at_price is not None:
        st.caption(f"ROI at this price, resold at market: {grade.roi_at_price:+.1f}%")
    st.markdown(rating_badge(grade.rating) + f" &nbsp; {grade.reason}",
                unsafe_allow_html=True)


def scan_page() -> None:
    show_flash()
    page_header("Scan",
                "Enter the price you see and get an instant buy grade. Camera "
                "scanning is coming; the grading works today.")
    owner = current_owner()

    st.info("Photo/QR scanning isn't wired up yet. For now, pick a card and type "
            "the price you're looking at. Save it and it grades against comps "
            "automatically once comp data is available.", icon="📷")

    # ---- Grade a price ----
    st.subheader("Grade a price")
    c1, c2 = st.columns([3, 2])
    with c1, open_session() as session:
        card = card_picker(session, owner, key="scan_card")
    price = c2.number_input("Price you see (delivered)", 0.0, value=100.0, step=1.0,
                            format="%.2f", key="scan_price")

    with st.expander("Market value & target (optional overrides)"):
        o1, o2 = st.columns(2)
        market_override = o1.number_input(
            "Market value (0 = use the card's own)", 0.0, value=0.0, step=5.0,
            format="%.2f", key="scan_market_override",
            help="Type an estimate to grade before comps exist. Leave 0 to use "
                 "the card's own market value.")
        target_roi = o2.number_input("Target ROI %", 0.0, 500.0, 20.0, step=5.0,
                                     key="scan_target_roi")

    grade = _grade_price(card, price, market_override or None, target_roi, owner)
    _render_grade(grade)

    if card is not None and price > 0:
        if st.button("💾 Save this scan to the card", type="primary",
                     key="scan_save"):
            with open_session() as session:
                set_scanned_price(session, card.id, price, owner=owner)
            flash_and_rerun(f"Saved a ${price:,.2f} scan for {card_label(card)}.")
    elif card is None:
        st.caption("Add a card (Cards view) to save a scan for later grading.")

    # ---- Saved scans ----
    st.divider()
    st.subheader("Saved scans")
    st.caption("Prices you've captured, graded against each card's current "
               "market value. Pending ones grade themselves once comps arrive.")
    with open_session() as session:
        scanned = session.exec(
            select(Inventory)
            .where(Inventory.owner == owner)
            .where(Inventory.scanned_price != None)  # noqa: E711
            .order_by(Inventory.card_id)
        ).all()
        rows = []
        for inv in scanned:
            grade = grade_scanned_card(session, inv)
            if grade is None:
                continue
            rows.append({
                "card": card_label(session.get(Card, inv.card_id)),
                "scanned price": round(grade.price, 2),
                "market value": grade.market_value,
                "score": grade.score,
                "verdict": rating_dot(grade.rating),
                "scanned on": inv.scanned_at,
            })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.caption("No saved scans yet. Grade a price above and save it.")
