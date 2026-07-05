from datetime import date

from sqlmodel import select

from cardtracker.models import (
    Card,
    Comp,
    CompSourceName,
    Inventory,
    PredictedDirection,
    Prediction,
    PriceSnapshot,
    PriceType,
    Transaction,
    TransactionType,
)


def test_models_module_reexecution_is_idempotent():
    """Streamlit Cloud can re-execute the models module in one process. The
    second pass must extend the existing tables, not raise 'already defined'.
    Runs in a subprocess because reloading mapped classes poisons the current
    process for every later test."""
    import subprocess
    import sys

    code = (
        "import importlib\n"
        "from cardtracker import models\n"
        "importlib.reload(models)\n"
        "print('reimport ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "reimport ok" in result.stdout


def test_card_round_trip(session, sample_card):
    fetched = session.exec(select(Card)).one()
    assert fetched.player_or_character == "Charizard"
    assert fetched.grader == "PSA"
    assert fetched.grade == "9"


def test_comp_stores_source_and_price_type(session, sample_card):
    comp = Comp(
        card_id=sample_card.id,
        source=CompSourceName.CSV,
        price_type=PriceType.SOLD,
        price=415.0,
        sold_date_or_seen_date=date(2026, 6, 28),
    )
    session.add(comp)
    session.commit()
    fetched = session.exec(select(Comp)).one()
    assert fetched.source == "csv"
    assert fetched.price_type == "sold"
    assert fetched.ingested_at is not None


def test_enums_stored_as_values_not_names(session, sample_card):
    """Raw SQL and pandas must see 'csv' and 'sold', not the member names CSV and SOLD."""
    comp = Comp(
        card_id=sample_card.id,
        source=CompSourceName.CSV,
        price_type=PriceType.SOLD,
        price=100.0,
        sold_date_or_seen_date=date(2026, 6, 28),
    )
    session.add(comp)
    session.commit()
    raw = session.connection().exec_driver_sql(
        "select source, price_type from comps"
    ).fetchone()
    assert raw == ("csv", "sold")
    raw_card = session.connection().exec_driver_sql(
        "select category, grader from cards"
    ).fetchone()
    assert raw_card == ("pokemon", "PSA")


def test_all_tables_accept_rows(session, sample_card):
    session.add(PriceSnapshot(card_id=sample_card.id, as_of_date=date(2026, 7, 1),
                              price_type=PriceType.SOLD, median_30d=420.0))
    session.add(Transaction(card_id=sample_card.id, type=TransactionType.BUY,
                            date=date(2026, 5, 1), price=380.0))
    session.add(Inventory(card_id=sample_card.id, cost_basis=380.0))
    session.add(Prediction(card_id=sample_card.id, as_of_date=date(2026, 7, 1),
                           predicted_direction=PredictedDirection.UP, confidence=0.7))
    session.commit()
    assert session.exec(select(PriceSnapshot)).one().median_30d == 420.0
    assert session.exec(select(Prediction)).one().was_correct is None
