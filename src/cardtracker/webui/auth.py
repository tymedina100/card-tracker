"""Google sign-in wiring for the hosted app.

Streamlit's built-in st.login reads an [auth] block from .streamlit/secrets.toml.
On Railway we do not commit that file; instead the four auth values arrive as
environment variables and are materialized into secrets.toml at startup. When
those variables are absent (local development), nothing is written and the app
runs in open, single-owner mode.
"""

import os
from pathlib import Path

from cardtracker.config import PROJECT_ROOT

DEFAULT_SECRETS_PATH = PROJECT_ROOT / ".streamlit" / "secrets.toml"
GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"

_REQUIRED_ENV = (
    "AUTH_REDIRECT_URI",
    "AUTH_COOKIE_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
)


def auth_env() -> dict[str, str] | None:
    """The four auth values from the environment, or None if any are missing."""
    values = {key: os.getenv(key, "").strip() for key in _REQUIRED_ENV}
    return values if all(values.values()) else None


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_auth_secrets(path: Path = DEFAULT_SECRETS_PATH) -> bool:
    """Write the [auth] block Streamlit expects when the auth env vars are set.
    Returns True if secrets were written, False if auth is not configured."""
    values = auth_env()
    if values is None:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    toml = (
        "[auth]\n"
        f'redirect_uri = "{_toml_escape(values["AUTH_REDIRECT_URI"])}"\n'
        f'cookie_secret = "{_toml_escape(values["AUTH_COOKIE_SECRET"])}"\n'
        f'client_id = "{_toml_escape(values["GOOGLE_CLIENT_ID"])}"\n'
        f'client_secret = "{_toml_escape(values["GOOGLE_CLIENT_SECRET"])}"\n'
        f'server_metadata_url = "{GOOGLE_METADATA_URL}"\n'
    )
    path.write_text(toml, encoding="utf-8")
    return True
