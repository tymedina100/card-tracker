"""Dashboard tests using Streamlit's AppTest harness. No browser needed.

Covers every view rendering with data and empty, plus the interactive forms:
add card, log buy, log sell, status and targets, and the maintenance buttons.
"""

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

ALL_VIEWS = ("Portfolio", "Cards", "Card detail", "Movers", "Deals",
             "Calculators", "Data", "Accuracy")


@pytest.fixture(autouse=True)
def fresh_streamlit_caches():
    """The dashboard caches its engine with st.cache_resource, which is process
    wide. Clear it so every test sees its own DB_PATH."""
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


TEST_OWNER = "local"


@pytest.fixture(autouse=True)
def pin_owner(monkeypatch):
    """Pin the signed-in identity so current_owner() is deterministic in tests
    (no Google sign-in) and matches the owner seeded data is created under."""
    monkeypatch.setenv("CARDTRACKER_OWNER", TEST_OWNER)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "dash.db"))
    settings = load_settings()
    engine = get_engine(settings)
    init_db(engine)
    today = date.today()
    with get_session(engine) as session:
        card = Card(owner=TEST_OWNER, category=Category.POKEMON,
                    player_or_character="Charizard", set_name="Base Set",
                    year=1999, card_number="4", grader=Grader.PSA, grade="9")
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
        log_buy(session, card.id, price=280.0, buy_date=today - timedelta(days=60),
                owner=TEST_OWNER)
        set_targets(session, card.id, target_sell_price=380.0,
                    min_accept_price=330.0, owner=TEST_OWNER)
        refresh_snapshots(session, owner=TEST_OWNER)
    return card


def run_view(view: str) -> AppTest:
    at = AppTest.from_file(DASHBOARD, default_timeout=60)
    at.run()
    if view != "Portfolio":
        at.sidebar.radio[0].set_value(view).run()
    assert not at.exception, f"{view} raised: {at.exception}"
    return at


def submit(at: AppTest, label: str) -> AppTest:
    """Click the button or form submit button with the given label."""
    buttons = [b for b in at.button if b.label == label]
    assert buttons, f"no button labeled '{label}'"
    buttons[0].click()
    at.run()
    assert not at.exception, f"submit '{label}' raised: {at.exception}"
    return at


def success_text(at: AppTest) -> str:
    return " ".join(s.value for s in at.success)


class TestViewsRender:
    def test_portfolio_view(self, seeded_db):
        at = run_view("Portfolio")
        labels = [metric.label for metric in at.metric]
        assert "Total cost basis" in labels
        assert "Realized P&L" in labels

    def test_card_detail_view(self, seeded_db):
        at = run_view("Card detail")
        assert at.selectbox[0].value is not None
        headers = " ".join(h.value for h in at.subheader)
        assert "Price history" in headers
        assert "Prediction" in headers
        assert "Actions" in headers

    def test_movers_view(self, seeded_db):
        at = run_view("Movers")
        assert not at.exception

    def test_deals_view(self, seeded_db):
        at = run_view("Deals")
        at.slider[0].set_value(5).run()
        assert not at.exception
        assert len(at.dataframe) == 1

    def test_accuracy_view(self, seeded_db):
        at = run_view("Accuracy")
        labels = [metric.label for metric in at.metric]
        assert "Hit rate" in labels

    def test_empty_database_renders_everywhere(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "empty.db"))
        for view in ALL_VIEWS:
            run_view(view)


class TestForms:
    def test_add_card_form(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "forms.db"))
        at = run_view("Cards")
        at.selectbox(key="add_category").set_value("pokemon").run()
        # Player and set suggestions are narrowed by category.
        at.selectbox(key="add_player_pokemon").set_value("Pikachu")
        at.selectbox(key="add_set_pokemon").set_value("Jungle")
        at.number_input(key="add_year").set_value(1999)
        submit(at, "Add card")
        assert "Added card" in success_text(at)
        # the new card shows up in the table on rerender
        at2 = run_view("Cards")
        assert len(at2.dataframe) == 1

    def test_add_card_requires_player_and_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "forms.db"))
        at = run_view("Cards")
        submit(at, "Add card")
        assert any("required" in e.value for e in at.error)

    def test_log_buy_form(self, seeded_db):
        at = run_view("Card detail")
        at.number_input(key="buy_price").set_value(250.0)
        at.number_input(key="buy_taxes").set_value(20.0)
        submit(at, "Log buy")
        assert "total cost of $270.00" in success_text(at)

    def test_log_sell_form_reports_profit(self, seeded_db):
        at = run_view("Card detail")
        at.number_input(key="sell_price").set_value(400.0)
        submit(at, "Log sell")
        text = success_text(at)
        assert "Logged sell" in text
        assert "Realized profit" in text

    def test_status_and_targets_form(self, seeded_db):
        at = run_view("Card detail")
        at.selectbox(key="status_value").set_value("listed")
        at.number_input(key="status_listed").set_value(399.0)
        at.number_input(key="target_price").set_value(420.0)
        at.number_input(key="min_price").set_value(380.0)
        submit(at, "Save")
        assert "saved" in success_text(at).lower()

    def test_targets_min_above_target_rejected(self, seeded_db):
        at = run_view("Card detail")
        at.number_input(key="target_price").set_value(300.0)
        at.number_input(key="min_price").set_value(350.0)
        submit(at, "Save")
        assert any("above" in e.value for e in at.error)

    def test_pull_comps_without_credentials_warns(self, seeded_db, monkeypatch):
        monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
        monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
        at = run_view("Card detail")
        submit(at, "Pull active listings")
        assert any("EBAY_CLIENT_ID" in w.value for w in at.warning)

    def test_refresh_and_score_buttons(self, seeded_db):
        at = run_view("Data")
        submit(at, "🔄 Refresh now")
        assert "snapshot" in success_text(at)
        at = run_view("Data")
        submit(at, "✅ Score now")
        assert "Scored" in success_text(at)

    def test_log_prediction_button(self, seeded_db):
        at = run_view("Card detail")
        submit(at, "📌 Log this prediction for scoring")
        assert "Prediction logged" in success_text(at)


class TestManageCard:
    def test_delete_card(self, seeded_db):
        at = run_view("Card detail")
        at.checkbox(key="delete_confirm").set_value(True).run()
        submit(at, "🗑️ Delete card")
        assert "deleted" in success_text(at).lower()
        at2 = run_view("Cards")
        assert not at2.dataframe  # collection is empty again

    def test_edit_card_updates_fields(self, seeded_db):
        at = run_view("Card detail")
        at.text_input(key="edit_notes").set_value("gem mint corners")
        submit(at, "Save changes")
        assert "updated" in success_text(at).lower()

    def test_export_button_present(self, seeded_db):
        at = run_view("Data")
        headers = " ".join(h.value for h in at.subheader)
        assert "Backup" in headers


class TestCalculators:
    def test_net_calculator(self, seeded_db):
        at = run_view("Calculators")
        at.number_input(key="net_price").set_value(450.0)
        at.run()
        labels = [metric.label for metric in at.metric]
        assert "Net proceeds" in labels

    def test_max_buy_calculator(self, seeded_db):
        at = run_view("Calculators")
        labels = [metric.label for metric in at.metric]
        assert any("Max buy" in label for label in labels)
