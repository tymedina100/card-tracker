"""Multi-tenant isolation: one owner must never see another owner's data.

This is the security-critical guarantee of the hosted app. Every read path that
powers a dashboard view is exercised here with two owners sharing one database.
"""

from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from cardtracker.deals import find_deals
from cardtracker.fees import FeeModel
from cardtracker.models import Card, Category, Comp, CompSourceName, Grader, PriceType
from cardtracker.portfolio import (
    cost_basis_summary,
    inventory_view,
    log_buy,
    realized_summary,
    set_status,
    unrealized_summary,
)
from cardtracker.predict import backtest, predict_card, score_due_predictions
from cardtracker.stats import refresh_snapshots
from cardtracker.webui.shared import all_cards, distinct_values

NO_FEES = FeeModel(final_value_pct=0.0, per_order_fee=0.0)
TODAY = date(2026, 7, 4)


def _make_card(session, owner, player="Charizard", set_name="Base Set"):
    card = Card(owner=owner, category=Category.POKEMON, player_or_character=player,
                set_name=set_name, year=1999, grader=Grader.PSA, grade="9")
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def _add_ask(session, card_id, price, days_ago=1):
    session.add(Comp(card_id=card_id, source=CompSourceName.BROWSE,
                     price_type=PriceType.ASK, price=price,
                     sold_date_or_seen_date=TODAY - timedelta(days=days_ago)))
    session.commit()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def two_owners(session):
    """Alice and Bob each own one card with a buy logged."""
    alice = _make_card(session, "alice@example.com", player="Charizard")
    bob = _make_card(session, "bob@example.com", player="Pikachu")
    log_buy(session, alice.id, price=100.0, owner="alice@example.com")
    log_buy(session, bob.id, price=200.0, owner="bob@example.com")
    return alice, bob


def test_all_cards_scoped_to_owner(session, two_owners):
    alice, bob = two_owners
    assert [c.id for c in all_cards(session, "alice@example.com")] == [alice.id]
    assert [c.id for c in all_cards(session, "bob@example.com")] == [bob.id]


def test_distinct_values_scoped_to_owner(session, two_owners):
    assert distinct_values(session, Card.player_or_character, "alice@example.com") == [
        "Charizard"]
    assert distinct_values(session, Card.player_or_character, "bob@example.com") == [
        "Pikachu"]


def test_cost_basis_and_holdings_scoped(session, two_owners):
    alice, bob = two_owners
    alice_basis = cost_basis_summary(session, owner="alice@example.com")
    assert [line.card.id for line in alice_basis] == [alice.id]
    assert alice_basis[0].total_cost == 100.0

    alice_holdings = unrealized_summary(session, NO_FEES, owner="alice@example.com")
    assert [line.card.id for line in alice_holdings] == [alice.id]

    bob_holdings = unrealized_summary(session, NO_FEES, owner="bob@example.com")
    assert [line.card.id for line in bob_holdings] == [bob.id]


def test_inventory_and_realized_scoped(session, two_owners):
    alice, bob = two_owners
    set_status(session, alice.id, owner="alice@example.com")
    assert [line.card.id for line in inventory_view(session, owner="alice@example.com")] \
        == [alice.id]

    from cardtracker.portfolio import log_sell
    log_sell(session, alice.id, price=150.0, owner="alice@example.com")
    assert [line.card.id for line in realized_summary(session, owner="alice@example.com")] \
        == [alice.id]
    assert realized_summary(session, owner="bob@example.com") == []


def test_deals_scoped_to_owner(session, two_owners):
    alice, bob = two_owners
    # give both a market and a cheap ask
    for card, owner in ((alice, "alice@example.com"), (bob, "bob@example.com")):
        _add_ask(session, card.id, price=1.0)
        refresh_snapshots(session, as_of=TODAY, card_id=card.id, owner=owner)
    alice_deals = find_deals(session, NO_FEES, as_of=TODAY, owner="alice@example.com")
    assert all(d.card.owner == "alice@example.com" for d in alice_deals)


def test_predictions_cohort_and_scoring_scoped(session):
    # Two owners with an identical card identity. Alice's cohort must not include
    # Bob's card even though player, set, year, and grade all match.
    alice1 = _make_card(session, "alice@example.com")
    _make_card(session, "bob@example.com")  # same identity, different owner
    from cardtracker.predict import find_cohort
    assert find_cohort(session, alice1) == []

    predict_card(session, alice1.id, as_of=TODAY, horizon_days=30)
    # Bob scoring must not touch Alice's logged prediction
    assert score_due_predictions(session, today=TODAY, owner="bob@example.com") == 0


def test_delete_card_cannot_delete_another_owner(session, two_owners):
    alice, bob = two_owners
    from cardtracker.portfolio import delete_card

    assert delete_card(session, alice.id, owner="bob@example.com") is False
    assert session.get(Card, alice.id) is not None
    assert delete_card(session, alice.id, owner="alice@example.com") is True
    assert session.get(Card, alice.id) is None
    # Bob's card is untouched
    assert session.get(Card, bob.id) is not None


def test_backtest_scoped_to_owner(session):
    alice = _make_card(session, "alice@example.com")
    for days_ago in range(150, 0, -3):
        age = 150 - days_ago
        session.add(Comp(card_id=alice.id, source=CompSourceName.CSV,
                         price_type=PriceType.SOLD, price=100 + 0.6 * age,
                         sold_date_or_seen_date=TODAY - timedelta(days=days_ago)))
    session.commit()
    assert backtest(session, owner="bob@example.com").scored == 0
    assert backtest(session, owner="alice@example.com").scored > 0
