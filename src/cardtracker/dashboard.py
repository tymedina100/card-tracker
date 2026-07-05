"""Streamlit dashboard for cardtracker. Fully interactive: every feature is
available through forms and buttons, no CLI required.

Run with: cardtracker dashboard
Or directly: streamlit run src/cardtracker/dashboard.py
"""

import streamlit as st

st.set_page_config(page_title="Card Tracker", page_icon="🃏", layout="wide")

from cardtracker.webui import cards, data_tools, market, overview  # noqa: E402

PAGES = {
    "Portfolio": ("🏠", overview.portfolio_page),
    "Cards": ("🗂️", cards.cards_page),
    "Card detail": ("🔎", cards.card_detail_page),
    "Movers": ("📈", market.movers_page),
    "Deals": ("💰", market.deals_page),
    "Calculators": ("🧮", data_tools.calculator_page),
    "Data": ("📥", data_tools.data_page),
    "Accuracy": ("🎯", market.accuracy_page),
}

st.sidebar.title("🃏 Card Tracker")
choice = st.sidebar.radio(
    "View", list(PAGES),
    format_func=lambda name: f"{PAGES[name][0]}  {name}",
    label_visibility="collapsed",
)
st.sidebar.caption("Comps, market stats, predictions, and P&L for sports and "
                   "Pokemon cards. Sold and ask prices are never mixed without "
                   "a label.")
PAGES[choice][1]()
