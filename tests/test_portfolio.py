from datetime import date

from sqlmodel import select

from cardtracker.models import Inventory, Transaction
from cardtracker.portfolio import cost_basis_summary, log_buy


def test_buy_total_cost_sums_all_components(session, sample_card):
    transaction = log_buy(session, sample_card.id, price=400.0, fees=5.0,
                          shipping=12.5, taxes=33.0, grading=25.0,
                          buy_date=date(2026, 5, 1), platform="ebay")
    assert transaction.total_cost == 475.5
    assert transaction.type == "buy"


def test_buy_creates_and_syncs_inventory(session, sample_card):
    log_buy(session, sample_card.id, price=100.0, buy_date=date(2026, 5, 10))
    log_buy(session, sample_card.id, price=120.0, taxes=8.0, buy_date=date(2026, 4, 1))
    inventory = session.exec(select(Inventory)).one()
    assert inventory.status == "owned"
    assert inventory.quantity == 2
    assert inventory.acquired_date == date(2026, 4, 1)  # earliest buy
    assert inventory.cost_basis == 228.0


def test_cost_basis_summary_per_card_and_per_copy(session, sample_card):
    log_buy(session, sample_card.id, price=100.0, fees=2.0, buy_date=date(2026, 5, 1))
    log_buy(session, sample_card.id, price=140.0, shipping=6.0, grading=20.0,
            buy_date=date(2026, 6, 1))
    lines = cost_basis_summary(session)
    assert len(lines) == 1
    line = lines[0]
    assert line.copies == 2
    assert line.price_total == 240.0
    assert line.fees_total == 2.0
    assert line.shipping_total == 6.0
    assert line.grading_total == 20.0
    assert line.total_cost == 268.0
    assert line.cost_per_copy == 134.0


def test_cost_basis_filter_by_card(session, sample_card):
    from cardtracker.models import Card, Category

    other = Card(category=Category.SPORTS, player_or_character="Luka Doncic",
                 set_name="Prizm", year=2018)
    session.add(other)
    session.commit()
    session.refresh(other)
    log_buy(session, sample_card.id, price=100.0)
    log_buy(session, other.id, price=50.0)
    lines = cost_basis_summary(session, card_id=other.id)
    assert len(lines) == 1
    assert lines[0].card.id == other.id
    assert lines[0].total_cost == 50.0


class TestUnrealized:
    def _snapshot(self, session, card_id, median, price_type="sold"):
        from cardtracker.models import PriceSnapshot, PriceType

        session.add(PriceSnapshot(card_id=card_id, as_of_date=date(2026, 7, 4),
                                  price_type=PriceType(price_type), median_30d=median))
        session.commit()

    def test_profit_and_roi_from_sold_median(self, session, sample_card):
        from cardtracker.fees import FeeModel
        from cardtracker.portfolio import unrealized_summary

        log_buy(session, sample_card.id, price=300.0)
        self._snapshot(session, sample_card.id, 400.0)
        model = FeeModel(final_value_pct=10.0, per_order_fee=0.0)
        lines = unrealized_summary(session, model)
        assert len(lines) == 1
        line = lines[0]
        assert line.market_per_copy == 400.0
        assert line.market_price_type == "sold"
        assert line.net_per_copy == 360.0
        assert line.profit == 60.0
        assert line.roi_pct == 20.0

    def test_ask_fallback_flagged(self, session, sample_card):
        from cardtracker.fees import FeeModel
        from cardtracker.portfolio import unrealized_summary

        log_buy(session, sample_card.id, price=300.0)
        self._snapshot(session, sample_card.id, 500.0, price_type="ask")
        lines = unrealized_summary(session, FeeModel(final_value_pct=0, per_order_fee=0))
        assert lines[0].market_price_type == "ask"
        assert lines[0].market_per_copy == 500.0

    def test_sold_preferred_over_ask(self, session, sample_card):
        from cardtracker.fees import FeeModel
        from cardtracker.portfolio import unrealized_summary

        log_buy(session, sample_card.id, price=300.0)
        self._snapshot(session, sample_card.id, 400.0, price_type="sold")
        self._snapshot(session, sample_card.id, 500.0, price_type="ask")
        lines = unrealized_summary(session, FeeModel())
        assert lines[0].market_price_type == "sold"

    def test_card_without_snapshot_visible_with_no_market(self, session, sample_card):
        from cardtracker.fees import FeeModel
        from cardtracker.portfolio import unrealized_summary

        log_buy(session, sample_card.id, price=300.0)
        lines = unrealized_summary(session, FeeModel())
        assert lines[0].market_per_copy is None
        assert lines[0].profit is None

    def test_quantity_multiplies_value(self, session, sample_card):
        from cardtracker.fees import FeeModel
        from cardtracker.portfolio import unrealized_summary

        log_buy(session, sample_card.id, price=100.0)
        log_buy(session, sample_card.id, price=120.0)
        self._snapshot(session, sample_card.id, 200.0)
        model = FeeModel(final_value_pct=0.0, per_order_fee=0.0)
        line = unrealized_summary(session, model)[0]
        assert line.quantity == 2
        assert line.net_value == 400.0
        assert line.profit == 180.0


class TestRealized:
    def test_sell_decrements_inventory_and_flips_status(self, session, sample_card):
        from cardtracker.portfolio import log_sell

        log_buy(session, sample_card.id, price=100.0)
        log_buy(session, sample_card.id, price=100.0)
        log_sell(session, sample_card.id, price=180.0)
        inventory = session.exec(select(Inventory)).one()
        assert inventory.quantity == 1
        assert inventory.status == "owned"
        log_sell(session, sample_card.id, price=190.0)
        session.refresh(inventory)
        assert inventory.quantity == 0
        assert inventory.status == "sold"

    def test_realized_profit_and_roi(self, session, sample_card):
        from cardtracker.portfolio import log_sell, realized_summary

        log_buy(session, sample_card.id, price=90.0, fees=5.0, taxes=5.0)  # cost 100
        log_sell(session, sample_card.id, price=180.0, fees=24.0, shipping_cost=6.0,
                 sell_date=date(2026, 7, 1))
        lines = realized_summary(session)
        assert len(lines) == 1
        line = lines[0]
        assert line.net == 150.0
        assert line.cost_allocated == 100.0
        assert line.profit == 50.0
        assert line.roi_pct == 50.0

    def test_avg_cost_allocation_across_copies(self, session, sample_card):
        from cardtracker.portfolio import log_sell, realized_summary

        log_buy(session, sample_card.id, price=100.0)
        log_buy(session, sample_card.id, price=200.0)  # avg 150
        log_sell(session, sample_card.id, price=250.0)
        line = realized_summary(session)[0]
        assert line.cost_allocated == 150.0
        assert line.profit == 100.0

    def test_sell_without_buy_shows_no_profit(self, session, sample_card):
        from cardtracker.portfolio import log_sell, realized_summary

        log_sell(session, sample_card.id, price=50.0)
        line = realized_summary(session)[0]
        assert line.cost_allocated is None
        assert line.profit is None
        assert line.net == 50.0


class TestInventoryAndTargets:
    def test_set_status_and_quantity(self, session, sample_card):
        from cardtracker.models import InventoryStatus
        from cardtracker.portfolio import set_status

        inventory = set_status(session, sample_card.id,
                               status=InventoryStatus.WATCHING)
        assert inventory.status == "watching"
        inventory = set_status(session, sample_card.id,
                               status=InventoryStatus.LISTED, quantity=3,
                               listed_price=450.0)
        assert inventory.status == "listed"
        assert inventory.quantity == 3
        assert inventory.listed_price == 450.0

    def test_inventory_view_filters_by_status(self, session, sample_card):
        from cardtracker.models import Card, Category, InventoryStatus
        from cardtracker.portfolio import inventory_view, set_status

        other = Card(category=Category.SPORTS, player_or_character="Luka Doncic",
                     set_name="Prizm", year=2018)
        session.add(other)
        session.commit()
        session.refresh(other)
        set_status(session, sample_card.id, status=InventoryStatus.OWNED, quantity=1)
        set_status(session, other.id, status=InventoryStatus.WATCHING)
        listed_only = inventory_view(session, status=InventoryStatus.WATCHING)
        assert [line.card.id for line in listed_only] == [other.id]
        assert len(inventory_view(session)) == 2

    def test_set_targets_persists(self, session, sample_card):
        from cardtracker.portfolio import set_targets

        inventory = set_targets(session, sample_card.id, target_sell_price=500.0,
                                min_accept_price=440.0)
        assert inventory.target_sell_price == 500.0
        assert inventory.min_accept_price == 440.0
        # partial update keeps the other value
        inventory = set_targets(session, sample_card.id, min_accept_price=430.0)
        assert inventory.target_sell_price == 500.0
        assert inventory.min_accept_price == 430.0

    def test_inventory_view_includes_market(self, session, sample_card):
        from cardtracker.models import PriceSnapshot, PriceType
        from cardtracker.portfolio import inventory_view, set_targets

        set_targets(session, sample_card.id, target_sell_price=500.0)
        session.add(PriceSnapshot(card_id=sample_card.id, as_of_date=date(2026, 7, 4),
                                  price_type=PriceType.SOLD, median_30d=480.0))
        session.commit()
        line = inventory_view(session)[0]
        assert line.market_per_copy == 480.0
        assert line.market_price_type == "sold"


def test_delete_card_removes_card_and_dependents(session, sample_card):
    from cardtracker.models import (
        Card,
        Comp,
        CompSourceName,
        PredictedDirection,
        Prediction,
        PriceSnapshot,
        PriceType,
    )
    from cardtracker.portfolio import delete_card

    log_buy(session, sample_card.id, price=100.0)
    session.add(Comp(card_id=sample_card.id, source=CompSourceName.CSV,
                     price_type=PriceType.SOLD, price=1.0,
                     sold_date_or_seen_date=date(2026, 6, 1)))
    session.add(PriceSnapshot(card_id=sample_card.id, as_of_date=date(2026, 7, 1),
                              price_type=PriceType.SOLD, median_30d=1.0))
    session.add(Prediction(card_id=sample_card.id, as_of_date=date(2026, 7, 1),
                           predicted_direction=PredictedDirection.UP, confidence=0.5))
    session.commit()

    assert delete_card(session, sample_card.id) is True
    assert session.get(Card, sample_card.id) is None
    assert session.exec(select(Comp)).all() == []
    assert session.exec(select(PriceSnapshot)).all() == []
    assert session.exec(select(Prediction)).all() == []
    assert session.exec(select(Transaction)).all() == []
    assert session.exec(select(Inventory)).all() == []


def test_delete_missing_card_returns_false(session, sample_card):
    from cardtracker.portfolio import delete_card

    assert delete_card(session, 9999) is False


def test_migration_adds_new_columns(tmp_path):
    import sqlite3

    from sqlmodel import Session, create_engine

    from cardtracker.db import init_db

    db_path = tmp_path / "old.db"
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, card_id INTEGER, "
        "type VARCHAR, date DATE, price FLOAT, fees FLOAT, shipping_cost FLOAT, "
        "platform VARCHAR, notes VARCHAR)"
    )
    con.execute(
        "INSERT INTO transactions (card_id, type, date, price, fees, shipping_cost, "
        "platform, notes) VALUES (1, 'buy', '2026-05-01', 100.0, 0, 0, '', '')"
    )
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{db_path}")
    init_db(engine)  # must add taxes and grading_cost without losing the row
    with Session(engine) as session:
        row = session.exec(select(Transaction)).one()
        assert row.price == 100.0
        assert row.taxes == 0.0
        assert row.grading_cost == 0.0


def test_effective_market_value_prefers_manual(session, sample_card):
    from cardtracker.models import Inventory
    from cardtracker.portfolio import effective_market_value

    inv = Inventory(card_id=sample_card.id, owner="", status="owned", quantity=1,
                    manual_market_value=420.0, last_sold_price=390.0)
    session.add(inv)
    session.commit()
    value, source = effective_market_value(session, inv)
    assert value == 420.0
    assert source == "manual"


def test_effective_market_value_falls_back_to_last_sold(session, sample_card):
    from cardtracker.models import Inventory
    from cardtracker.portfolio import effective_market_value

    inv = Inventory(card_id=sample_card.id, owner="", status="owned", quantity=1,
                    last_sold_price=375.0)
    session.add(inv)
    session.commit()
    value, source = effective_market_value(session, inv)
    assert value == 375.0
    assert source == "last sold"


def test_assess_card_owned_recommendation_and_math(session, sample_card):
    from cardtracker.flip import Recommendation
    from cardtracker.portfolio import assess_card, log_buy, set_market_inputs

    # Paid 300 total for one copy; market 400; target 20% ROI.
    log_buy(session, sample_card.id, price=300.0, buy_date=date(2026, 5, 1))
    set_market_inputs(session, sample_card.id, manual_market_value=400.0,
                      target_roi_pct=20.0)
    inv = session.exec(select(Inventory)).one()
    a = assess_card(session, inv)
    assert a.market_value == 400.0
    assert a.net_if_sold is not None and a.net_if_sold > 0
    # Net (~346.60) is above the 300 cost, so there is a real profit.
    assert a.profit is not None and a.profit > 0
    assert a.recommendation in {Recommendation.SELL_NOW, Recommendation.LIST,
                                Recommendation.HOLD}


def test_assess_card_missing_market_is_flagged(session, sample_card):
    from cardtracker.flip import Recommendation
    from cardtracker.portfolio import assess_card, log_buy

    log_buy(session, sample_card.id, price=100.0, buy_date=date(2026, 5, 1))
    inv = session.exec(select(Inventory)).one()
    a = assess_card(session, inv)
    assert a.missing_market
    assert a.recommendation == Recommendation.MISSING_DATA


def test_set_and_grade_scanned_price(session, sample_card):
    from cardtracker.portfolio import (
        grade_scanned_card,
        set_market_inputs,
        set_scanned_price,
    )

    # No scan yet -> nothing to grade.
    inv = set_scanned_price(session, sample_card.id, 250.0)
    assert inv.scanned_price == 250.0
    assert inv.scanned_at is not None

    # No market value yet -> grade is pending, but the price is remembered.
    grade = grade_scanned_card(session, inv)
    assert grade is not None and grade.is_pending

    # Once a market value exists, the same scan grades on the scale.
    set_market_inputs(session, sample_card.id, manual_market_value=400.0,
                      target_roi_pct=20.0)
    inv = session.exec(select(Inventory)).one()
    graded = grade_scanned_card(session, inv)
    assert graded is not None and not graded.is_pending
    assert 0 <= graded.score <= 100
    assert graded.rating in {"Great Buy", "Steal", "Good Buy"}


def test_clear_scanned_price(session, sample_card):
    from cardtracker.portfolio import grade_scanned_card, set_scanned_price

    set_scanned_price(session, sample_card.id, 250.0)
    inv = set_scanned_price(session, sample_card.id, None)
    assert inv.scanned_price is None
    assert inv.scanned_at is None
    assert grade_scanned_card(session, inv) is None
