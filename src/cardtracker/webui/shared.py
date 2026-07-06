"""Shared helpers for the dashboard views."""

import streamlit as st
from sqlmodel import Session, select

from cardtracker.config import Settings, load_settings
from cardtracker.db import get_engine, get_session, init_db
from cardtracker.fees import FeeModel
from cardtracker.models import Card, describe_card

ASK_NOTE = "Values marked with an asterisk use the ask median because no sold data exists yet."

SOLD_COLOR = "#35c26b"
ASK_COLOR = "#8b97a8"
GOLD = "#e8b339"
UP_COLOR = "#35c26b"
DOWN_COLOR = "#e5534b"


@st.cache_resource
def _engine():
    settings = load_settings()
    engine = get_engine(settings)
    init_db(engine)
    return settings, engine


def get_settings() -> Settings:
    return _engine()[0]


def open_session() -> Session:
    return get_session(_engine()[1])


def fee_model() -> FeeModel:
    return FeeModel.from_settings(get_settings())


def money(value: float | None) -> str:
    return f"${value:,.2f}" if value is not None else "n/a"


def card_label(card: Card) -> str:
    return f"#{card.id}  {describe_card(card)}"


def flash_and_rerun(message: str) -> None:
    """Store a success message that survives the rerun triggered by a form."""
    st.session_state["_flash"] = message
    st.rerun()


def show_flash() -> None:
    message = st.session_state.pop("_flash", None)
    if message:
        st.success(message)


def all_cards(session: Session) -> list[Card]:
    return session.exec(select(Card).order_by(Card.id)).all()


def distinct_values(session: Session, column) -> list[str]:
    """Sorted, de-duplicated non-empty values already stored in a Card column,
    for example every set name the collection has used. Feeds the entry
    dropdowns so previously typed values resurface."""
    rows = session.exec(select(column).distinct()).all()
    values = {str(v).strip() for v in rows if v is not None and str(v).strip()}
    return sorted(values, key=str.casefold)


def merge_options(existing: list[str], curated: list[str]) -> list[str]:
    """Existing collection values first, then curated suggestions, trimmed and
    de-duplicated case-insensitively. The order surfaces what the user actually
    uses above the generic popular list."""
    options: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *curated]:
        cleaned = (value or "").strip()
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            options.append(cleaned)
    return options


def combo(label: str, curated: list[str], existing: list[str] = (), *,
          key: str, help: str | None = None) -> str:
    """A dropdown of popular plus previously used values that also accepts a new
    typed entry. Returns '' when nothing is chosen."""
    choice = st.selectbox(
        label, merge_options(existing, curated), index=None,
        placeholder=f"Select or type a {label.lower()}",
        accept_new_options=True, key=key, help=help,
    )
    return (choice or "").strip()


def card_picker(session: Session, label: str = "Card",
                key: str = "card_picker") -> Card | None:
    cards = all_cards(session)
    if not cards:
        return None
    return st.selectbox(label, cards, format_func=card_label, key=key)


def style_chart(fig, height: int = 420) -> None:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
    )
