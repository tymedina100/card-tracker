import pytest

from cardtracker.webui.auth import GOOGLE_METADATA_URL, auth_env, write_auth_secrets

AUTH_KEYS = {
    "AUTH_REDIRECT_URI": "https://app.example.com/oauth2callback",
    "AUTH_COOKIE_SECRET": "supersecretcookie",
    "GOOGLE_CLIENT_ID": "client-id.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "client-secret",
}


def _set_auth_env(monkeypatch):
    for key, value in AUTH_KEYS.items():
        monkeypatch.setenv(key, value)


def test_auth_env_none_when_incomplete(monkeypatch):
    for key in AUTH_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "only-one")
    assert auth_env() is None


def test_auth_env_complete(monkeypatch):
    _set_auth_env(monkeypatch)
    values = auth_env()
    assert values == AUTH_KEYS


def test_write_auth_secrets_noop_without_env(monkeypatch, tmp_path):
    for key in AUTH_KEYS:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".streamlit" / "secrets.toml"
    assert write_auth_secrets(path) is False
    assert not path.exists()


def test_write_auth_secrets_writes_auth_block(monkeypatch, tmp_path):
    _set_auth_env(monkeypatch)
    path = tmp_path / ".streamlit" / "secrets.toml"
    assert write_auth_secrets(path) is True
    text = path.read_text(encoding="utf-8")
    assert "[auth]" in text
    assert AUTH_KEYS["GOOGLE_CLIENT_ID"] in text
    assert GOOGLE_METADATA_URL in text
    assert 'redirect_uri = "https://app.example.com/oauth2callback"' in text


def test_current_owner_falls_back_without_login(monkeypatch):
    from cardtracker.webui.shared import current_owner

    monkeypatch.setenv("CARDTRACKER_OWNER", "solo")
    assert current_owner() == "solo"


@pytest.mark.parametrize("value", ['a"b', "a\\b"])
def test_write_auth_secrets_escapes_special_chars(monkeypatch, tmp_path, value):
    _set_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_COOKIE_SECRET", value)
    path = tmp_path / ".streamlit" / "secrets.toml"
    write_auth_secrets(path)
    # The written value must be valid TOML that round-trips to the original.
    import tomllib

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["auth"]["cookie_secret"] == value
