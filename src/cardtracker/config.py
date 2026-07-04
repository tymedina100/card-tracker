"""Application settings loaded from environment variables and a local .env file."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EBAY_API_BASE = {
    "sandbox": "https://api.sandbox.ebay.com",
    "production": "https://api.ebay.com",
}


def _default_db_path() -> str:
    return str(PROJECT_ROOT / "data" / "cardtracker.db")


@dataclass
class Settings:
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_env: str = "sandbox"
    ebay_marketplace_id: str = "EBAY_US"
    insights_enabled: bool = False
    db_path: str = field(default_factory=_default_db_path)

    @property
    def ebay_api_base(self) -> str:
        return EBAY_API_BASE[self.ebay_env]

    @property
    def has_ebay_credentials(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Build Settings from the environment, loading .env from the project root by default."""
    load_dotenv(env_file or PROJECT_ROOT / ".env")
    ebay_env = os.getenv("EBAY_ENV", "sandbox").strip().lower()
    if ebay_env not in EBAY_API_BASE:
        raise ValueError(f"EBAY_ENV must be 'sandbox' or 'production', got '{ebay_env}'")
    return Settings(
        ebay_client_id=os.getenv("EBAY_CLIENT_ID", "").strip(),
        ebay_client_secret=os.getenv("EBAY_CLIENT_SECRET", "").strip(),
        ebay_env=ebay_env,
        ebay_marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US").strip(),
        insights_enabled=os.getenv("INSIGHTS_ENABLED", "").strip().lower() in ("1", "true", "yes"),
        db_path=os.getenv("DB_PATH", "").strip() or _default_db_path(),
    )
