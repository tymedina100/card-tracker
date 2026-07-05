"""Dashboard smoke tests using Streamlit's AppTest harness. No browser needed."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from cardtracker.config import load_settings
from cardtracker.db import get_engine, get_session, init_db
from cardtracker.models import Card, Category, Comp, CompSourceName, Grader, PriceType
from cardtracker.portfolio import log_buy, set_targets
from cardtracker.stats import refresh_snapshots

DASHBOARD = str(Path(__file__).resolve().parents[1] / "src" / "cardtracker" / "dashboard.py")


@pytest.fixture(autouse=True)
def fresh_streamlit_caches():
    """The dashboard caches its engine with st.cache_resource, which is process
    wide. Clear it so every test sees its own DB_PATH."""
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dash.db"))
    settings = load_settings()
    engine = get_engine(settings)
    init_db(engine)
    today = date.today()
    with get_session(engine) as session:
        card = Card(category=Category.POKEMON, player_or_character="Charizard",
                    set_name="Base Set", year=1999, card_number="4",
                    grader=Grader.PSA, grade="9")
        session.add(card)
        session.commit()
        session.refresh(card)
        comps = []
        for days_ago in range(120, 0, -4):
            age = 120 - days_ago
            comps.append(Comp(card_id=card.id, source=CompSourceName.CSV,
                              price_type=PriceType.SOLD, price=300 + 0.5 * age,
                              sold_date_or_seen_date=today - timedelta(days=days_ago)))
        comps.append(Comp(card_id=card.id, source=CompSourceName.BROWSE,
                          price_type=PriceType.ASK, price=250.0,
                          sold_date_or_seen_date=today - timedelta(days=1),
                          title_raw="cheap ask", listing_url="https://ebay.com/itm/1"))
        session.add_all(comps)
        session.commit()
        log_buy(session, card.id, price=280.0, buy_date=today - timedelta(days=60))
        set_targets(session, card.id, target_sell_price=380.0, min_accept_price=330.0)
        refresh_snapshots(session)
    return card


def run_view(view: str) -> AppTest:
    at = AppTest.from_file(DASHBOARD, default_timeout=60)
    at.run()
    if view != "Portfolio":
        at.sidebar.radio[0].set_value(view).run()
    assert not at.exception, f"{view} raised: {at.exception}"
    return at


def test_portfolio_view(seeded_db):
    at = run_view("Portfolio")
    labels = [metric.label for metric in at.metric]
    assert "Total cost basis" in labels
    assert "Realized P&L" in labels


def test_card_view(seeded_db):
    at = run_view("Card")
    assert at.selectbox[0].value is not None
    headers = " ".join(h.value for h in at.subheader)
    assert "Price history" in headers
    assert "Prediction" in headers


def test_movers_view(seeded_db):
    at = run_view("Movers")
    headers = " ".join(h.value for h in at.subheader)
    assert "Predicted up" in headers
    assert "Predicted down" in headers


def test_deals_view(seeded_db):
    at = run_view("Deals")
    # the 250 ask sits under max buy for the rising sold median at 5 percent ROI
    at.slider[0].set_value(5).run()
    assert not at.exception
    assert len(at.dataframe) == 1


def test_accuracy_view(seeded_db):
    at = run_view("Accuracy")
    labels = [metric.label for metric in at.metric]
    assert "Hit rate" in labels


def test_empty_database_renders_everywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "empty.db"))
    for view in ("Portfolio", "Card", "Movers", "Deals", "Accuracy"):
        run_view(view)
