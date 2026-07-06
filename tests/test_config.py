import pytest

from cardtracker.config import Settings, load_settings, normalize_database_url


@pytest.mark.parametrize("raw, expected", [
    ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
    ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("postgresql+psycopg2://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
    ("  postgres://u:p@host/db  ", "postgresql+psycopg://u:p@host/db"),
    ("", ""),
    ("sqlite:////tmp/x.db", "sqlite:////tmp/x.db"),
])
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_load_settings_reads_database_url(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    settings = load_settings(env_file=tmp_path / "nonexistent.env")
    assert settings.database_url == "postgresql+psycopg://u:p@host:5432/db"


def test_settings_defaults_to_no_database_url():
    assert Settings().database_url == ""
