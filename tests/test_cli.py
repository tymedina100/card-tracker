import pytest
from tests.conftest import VALID_CSV
from typer.testing import CliRunner

from cardtracker.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)


def add_charizard():
    return runner.invoke(app, [
        "add-card", "--category", "pokemon", "--player", "Charizard",
        "--set", "Base Set", "--year", "1999", "--number", "4",
        "--grader", "PSA", "--grade", "9",
    ])


def test_init_db():
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0
    assert "Database ready" in result.output


def test_add_and_list_card():
    result = add_charizard()
    assert result.exit_code == 0
    assert "Added card 1" in result.output

    result = runner.invoke(app, ["list-cards"])
    assert result.exit_code == 0
    assert "Charizard" in result.output
    assert "PSA 9" in result.output


def test_list_cards_empty():
    result = runner.invoke(app, ["list-cards"])
    assert result.exit_code == 0
    assert "No cards yet" in result.output


def test_import_csv(tmp_path):
    add_charizard()
    csv_path = tmp_path / "solds.csv"
    csv_path.write_text(VALID_CSV, encoding="utf-8")
    result = runner.invoke(app, ["import-csv", str(csv_path)])
    assert result.exit_code == 0
    assert "Imported 2 sold comps" in result.output

    result = runner.invoke(app, ["list-cards"])
    assert "2" in result.output


def test_import_csv_unknown_card(tmp_path):
    csv_path = tmp_path / "solds.csv"
    csv_path.write_text(VALID_CSV, encoding="utf-8")
    result = runner.invoke(app, ["import-csv", str(csv_path)])
    assert result.exit_code == 1
    assert "No card with id 1" in result.output


def test_import_csv_bad_file(tmp_path):
    add_charizard()
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("card_id,price\n1,100\n", encoding="utf-8")
    result = runner.invoke(app, ["import-csv", str(csv_path)])
    assert result.exit_code == 1
    assert "sold_date" in result.output


def test_pull_comps_without_credentials():
    add_charizard()
    result = runner.invoke(app, ["pull-comps", "1", "--query", "charizard"])
    assert result.exit_code == 1
    assert "EBAY_CLIENT_ID" in result.output


def test_pull_comps_unknown_card():
    result = runner.invoke(app, ["pull-comps", "99", "--query", "charizard"])
    assert result.exit_code == 1
    assert "No card with id 99" in result.output
