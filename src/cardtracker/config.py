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


def normalize_database_url(url: str) -> str:
    """Rewrite a Postgres URL to use the psycopg 3 driver.

    Railway (and most hosts) hand out URLs like 'postgres://...' or
    'postgresql://...', which SQLAlchemy would route to the psycopg2 driver.
    We ship psycopg 3, so force the '+psycopg' driver. Non-Postgres URLs
    (for example a sqlite:/// path) are returned unchanged."""
    url = url.strip()
    if not url:
        return ""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass
class Settings:
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_env: str = "sandbox"
    ebay_marketplace_id: str = "EBAY_US"
    insights_enabled: bool = False
    database_url: str = ""
    db_path: str = field(default_factory=_default_db_path)
    fee_final_value_pct: float = 13.25
    fee_per_order: float = 0.30
    fee_promoted_pct: float = 0.0
    fee_payment_pct: float = 0.0
    fee_payment_fixed: float = 0.0
    fee_fvf_on_shipping: bool = True
    fee_fvf_on_tax: bool = True

    @property
    def ebay_api_base(self) -> str:
        return EBAY_API_BASE[self.ebay_env]

    @property
    def has_ebay_credentials(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got '{raw}'") from None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


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
        database_url=normalize_database_url(os.getenv("DATABASE_URL", "")),
        db_path=os.getenv("DB_PATH", "").strip() or _default_db_path(),
        fee_final_value_pct=_env_float("FEE_FINAL_VALUE_PCT", 13.25),
        fee_per_order=_env_float("FEE_PER_ORDER", 0.30),
        fee_promoted_pct=_env_float("FEE_PROMOTED_PCT", 0.0),
        fee_payment_pct=_env_float("FEE_PAYMENT_PCT", 0.0),
        fee_payment_fixed=_env_float("FEE_PAYMENT_FIXED", 0.0),
        fee_fvf_on_shipping=_env_bool("FEE_FVF_ON_SHIPPING", True),
        fee_fvf_on_tax=_env_bool("FEE_FVF_ON_TAX", True),
    )
