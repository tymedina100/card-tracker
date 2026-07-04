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
