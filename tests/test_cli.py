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


def import_recent_solds(tmp_path):
    from datetime import date, timedelta

    today = date.today()
    csv_path = tmp_path / "recent.csv"
    csv_path.write_text(
        "card_id,sold_date,price,shipping\n"
        f"1,{today - timedelta(days=2)},400.00,5.00\n"
        f"1,{today - timedelta(days=10)},420.00,0\n"
        f"1,{today - timedelta(days=25)},380.00,0\n",
        encoding="utf-8",
    )
    return runner.invoke(app, ["import-csv", str(csv_path)])


def test_refresh_stats_and_stat_line(tmp_path):
    add_charizard()
    assert import_recent_solds(tmp_path).exit_code == 0

    result = runner.invoke(app, ["refresh-stats"])
    assert result.exit_code == 0
    assert "Wrote 1 snapshot(s)" in result.output

    result = runner.invoke(app, ["stats", "1"])
    assert result.exit_code == 0
    assert "sold stats (confirmed sales)" in result.output
    assert "median 7d / 30d / 90d : 405.00 / 405.00 / 405.00" in result.output
    assert "count 30d / 90d       : 3 / 3" in result.output
    assert "ask stats" not in result.output  # no ask comps, no ask block


def test_stats_without_snapshots():
    add_charizard()
    result = runner.invoke(app, ["stats", "1"])
    assert result.exit_code == 0
    assert "No snapshots yet" in result.output


def test_predict_and_backtest_cli(tmp_path):
    from datetime import date, timedelta

    add_charizard()
    today = date.today()
    lines = ["card_id,sold_date,price"]
    for days_ago in range(150, 0, -3):
        age = 150 - days_ago
        lines.append(f"1,{today - timedelta(days=days_ago)},{100 + 0.6 * age:.2f}")
    csv_path = tmp_path / "trend.csv"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert runner.invoke(app, ["import-csv", str(csv_path)]).exit_code == 0

    result = runner.invoke(app, ["predict", "1"])
    assert result.exit_code == 0
    assert "UP, confidence" in result.output
    assert "Rationale:" in result.output
    assert "Logged to predictions table." in result.output

    result = runner.invoke(app, ["backtest"])
    assert result.exit_code == 0
    assert "Hit rate: 100.0%" in result.output

    result = runner.invoke(app, ["score-predictions"])
    assert result.exit_code == 0
    assert "Scored 0 prediction(s)" in result.output  # horizon not elapsed yet


def test_log_buy_and_cost_basis_cli():
    add_charizard()
    result = runner.invoke(app, [
        "log-buy", "1", "--price", "380", "--fees", "5", "--shipping", "10",
        "--taxes", "31.35", "--grading", "25", "--date", "2026-05-01",
        "--platform", "ebay",
    ])
    assert result.exit_code == 0
    assert "total cost 451.35" in result.output

    result = runner.invoke(app, ["cost-basis"])
    assert result.exit_code == 0
    assert "451.35" in result.output
    assert "Charizard" in result.output


def test_log_buy_bad_date():
    add_charizard()
    result = runner.invoke(app, ["log-buy", "1", "--price", "100", "--date", "05/01/2026"])
    assert result.exit_code == 1
    assert "not a valid" in result.output


def test_cost_basis_empty():
    result = runner.invoke(app, ["cost-basis"])
    assert result.exit_code == 0
    assert "No buys logged yet" in result.output


def test_inventory_and_targets_cli():
    add_charizard()
    result = runner.invoke(app, ["set-status", "1", "--status", "listed",
                                 "--quantity", "1", "--listed-price", "475"])
    assert result.exit_code == 0
    assert "listed" in result.output

    result = runner.invoke(app, ["set-targets", "1", "--target", "500", "--min", "440"])
    assert result.exit_code == 0
    assert "target 500.00" in result.output

    result = runner.invoke(app, ["inventory", "--status", "listed"])
    assert result.exit_code == 0
    assert "Charizard" in result.output
    assert "475.00" in result.output

    result = runner.invoke(app, ["targets"])
    assert result.exit_code == 0
    assert "500.00" in result.output
    assert "needs comps" in result.output


def test_set_targets_min_above_target_rejected():
    add_charizard()
    result = runner.invoke(app, ["set-targets", "1", "--target", "400", "--min", "450"])
    assert result.exit_code == 1
    assert "above" in result.output


def test_set_status_invalid_status():
    add_charizard()
    result = runner.invoke(app, ["set-status", "1", "--status", "vaulted"])
    assert result.exit_code == 1
    assert "owned, listed, sold, or watching" in result.output


def test_backtest_without_data():
    result = runner.invoke(app, ["backtest"])
    assert result.exit_code == 0
    assert "Nothing scorable" in result.output


def test_refresh_stats_unknown_card():
    result = runner.invoke(app, ["refresh-stats", "--card-id", "42"])
    assert result.exit_code == 1
    assert "No card with id 42" in result.output
