import pytest
from sqlmodel import select
from tests.conftest import VALID_CSV

from cardtracker.models import Comp
from cardtracker.sources import CsvImportError, CsvImportSource, save_comps


def test_valid_csv_imports_all_rows(sold_csv):
    source = CsvImportSource(sold_csv(VALID_CSV))
    rows = source.read_rows()
    assert len(rows) == 2
    assert rows[0].card_id == 1
    assert rows[0].record.price == 415.0
    assert rows[0].record.shipping == 4.99
    assert rows[1].record.currency == "USD"


def test_default_card_id_used_when_column_absent(sold_csv):
    path = sold_csv("sold_date,price\n2026-06-28,100.00\n")
    rows = CsvImportSource(path, default_card_id=7).read_rows()
    assert rows[0].card_id == 7


def test_missing_required_column_rejected(sold_csv):
    path = sold_csv("card_id,price\n1,100.00\n")
    with pytest.raises(CsvImportError, match="sold_date"):
        CsvImportSource(path).read_rows()


def test_no_card_id_anywhere_rejected(sold_csv):
    path = sold_csv("sold_date,price\n2026-06-28,100.00\n")
    with pytest.raises(CsvImportError, match="card_id"):
        CsvImportSource(path).read_rows()


def test_bad_price_rejected_with_line_number(sold_csv):
    path = sold_csv("card_id,sold_date,price\n1,2026-06-28,abc\n")
    with pytest.raises(CsvImportError, match="line 2.*not a number"):
        CsvImportSource(path).read_rows()


def test_negative_price_rejected(sold_csv):
    path = sold_csv("card_id,sold_date,price\n1,2026-06-28,-5\n")
    with pytest.raises(CsvImportError, match="positive"):
        CsvImportSource(path).read_rows()


def test_bad_date_rejected(sold_csv):
    path = sold_csv("card_id,sold_date,price\n1,06/28/2026,100\n")
    with pytest.raises(CsvImportError, match="YYYY-MM-DD"):
        CsvImportSource(path).read_rows()


def test_skip_bad_rows_collects_errors(sold_csv):
    path = sold_csv(
        "card_id,sold_date,price\n"
        "1,2026-06-28,100\n"
        "1,bad-date,100\n"
        "1,2026-06-30,200\n"
    )
    source = CsvImportSource(path, skip_bad_rows=True)
    rows = source.read_rows()
    assert len(rows) == 2
    assert len(source.skipped) == 1
    assert "line 3" in source.skipped[0]


def test_missing_file_rejected(tmp_path):
    with pytest.raises(CsvImportError, match="not found"):
        CsvImportSource(tmp_path / "nope.csv").read_rows()


def test_saved_comps_stamped_sold_and_csv(session, sample_card, sold_csv):
    source = CsvImportSource(sold_csv(VALID_CSV))
    records = [row.record for row in source.read_rows()]
    save_comps(session, sample_card.id, source, records)
    comps = session.exec(select(Comp)).all()
    assert len(comps) == 2
    assert all(c.source == "csv" and c.price_type == "sold" for c in comps)
