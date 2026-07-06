"""Streamlit dashboard for cardtracker. Fully interactive: every feature is
available through forms and buttons, no CLI required.

Run with: cardtracker dashboard
Or directly: streamlit run src/cardtracker/dashboard.py
"""

import streamlit as st

from cardtracker.webui import cards, data_tools, market, overview
from cardtracker.webui.shared import auth_configured

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


def _render_landing() -> None:
    """Signed-out home: what the app does and a Google sign-in button."""
    st.title("🃏 Card Tracker")
    st.subheader("Comps, market stats, predictions, and P&L for your card collection.")
    st.write(
        "Track sports and Pokemon cards: log buys and sells, import sold comps, "
        "watch ask-versus-sold price history, get explainable up/down predictions, "
        "and see your cost basis and profit. Your collection is private to your "
        "account."
    )
    st.divider()
    if st.button("Sign in with Google", type="primary", icon="🔐"):
        st.login()
    st.caption("We use your Google account only to sign you in and keep your "
               "collection separate. We store the cards and transactions you "
               "enter, nothing from your Google account beyond your email.")


def _require_auth() -> bool:
    """Gate the app behind Google sign-in when auth is configured. In local dev
    (no auth secrets) the app runs open under the local owner."""
    if not auth_configured():
        return True
    if getattr(st.user, "is_logged_in", False):
        return True
    _render_landing()
    return False


def main() -> None:
    """Render the app. Called on every Streamlit rerun by the entry script."""
    st.set_page_config(page_title="Card Tracker", page_icon="🃏", layout="wide")
    if not _require_auth():
        return
    st.sidebar.title("🃏 Card Tracker")
    choice = st.sidebar.radio(
        "View", list(PAGES),
        format_func=lambda name: f"{PAGES[name][0]}  {name}",
        label_visibility="collapsed",
    )
    st.sidebar.caption("Comps, market stats, predictions, and P&L for sports "
                       "and Pokemon cards. Sold and ask prices are never mixed "
                       "without a label.")
    if auth_configured() and getattr(st.user, "is_logged_in", False):
        st.sidebar.divider()
        st.sidebar.caption(f"Signed in as {st.user.email}")
        if st.sidebar.button("Sign out", icon="🚪"):
            st.logout()
    PAGES[choice][1]()


if __name__ == "__main__":
    main()
