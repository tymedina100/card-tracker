"""Streamlit dashboard for cardtracker. Fully interactive: every feature is
available through forms and buttons, no CLI required.

Run with: cardtracker dashboard
Or directly: streamlit run src/cardtracker/dashboard.py
"""

import streamlit as st

from cardtracker.webui import cards, data_tools, market, overview
from cardtracker.webui.shared import auth_configured
from cardtracker.webui.theme import inject_global_style, sidebar_brand

PAGES = {
    "Portfolio": (":material/account_balance_wallet:", overview.portfolio_page),
    "Cards": (":material/style:", cards.cards_page),
    "Card detail": (":material/search:", cards.card_detail_page),
    "Movers": (":material/trending_up:", market.movers_page),
    "Deals": (":material/sell:", market.deals_page),
    "Calculators": (":material/calculate:", data_tools.calculator_page),
    "Data": (":material/database:", data_tools.data_page),
    "Accuracy": (":material/target:", market.accuracy_page),
}


def _render_landing() -> None:
    """Signed-out home: what the app does and a Google sign-in button."""
    st.markdown(
        '<div class="ct-hero">'
        '<div class="ct-brand-mark ct-hero-mark">CT</div>'
        '<span class="ct-kicker">Collector Intelligence</span>'
        '<h1 class="ct-hero-title">Card Tracker</h1>'
        '<p class="ct-hero-sub">A private valuation desk for serious sports and '
        'Pokemon collections &mdash; cost basis, market comps, explainable '
        'up/down forecasts, and profit, all in one place.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    features = [
        ("Cost basis & P&L", "Every buy and sell tracked to the cent, net of fees."),
        ("Market comps", "Ask-versus-sold price history, never mixed without a label."),
        ("Explainable forecasts", "Up/down calls with the cohort and rationale behind them."),
    ]
    cols = st.columns(3)
    for col, (head, body) in zip(cols, features, strict=True):
        with col:
            st.markdown(
                f'<div class="ct-feature"><div class="ct-feature-head">{head}</div>'
                f'<div class="ct-feature-body">{body}</div></div>',
                unsafe_allow_html=True,
            )
    st.write("")
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
    inject_global_style()
    if not _require_auth():
        return
    sidebar_brand()
    choice = st.sidebar.radio(
        "View", list(PAGES),
        format_func=lambda name: f"{PAGES[name][0]} {name}",
        label_visibility="collapsed",
    )
    if auth_configured() and getattr(st.user, "is_logged_in", False):
        st.sidebar.divider()
        st.sidebar.caption(f"Signed in as {st.user.email}")
        if st.sidebar.button("Sign out", icon="🚪"):
            st.logout()
    PAGES[choice][1]()


if __name__ == "__main__":
    main()
