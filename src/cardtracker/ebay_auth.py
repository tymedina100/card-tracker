"""eBay OAuth 2.0 client-credentials token management."""

import base64
import time

import httpx

from cardtracker.config import Settings

TOKEN_PATH = "/identity/v1/oauth2/token"
SCOPE = "https://api.ebay.com/oauth/api_scope"

# refresh this many seconds before the token actually expires
EXPIRY_BUFFER_SECONDS = 60


class MissingCredentialsError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "eBay credentials are not configured. Set EBAY_CLIENT_ID and "
            "EBAY_CLIENT_SECRET in your .env file (see .env.example). "
            "CSV import works without eBay credentials."
        )


class EbayTokenProvider:
    """Fetches and caches an eBay application access token."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.Client(timeout=30)
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - EXPIRY_BUFFER_SECONDS:
            return self._token
        return self._fetch_token()

    def _fetch_token(self) -> str:
        if not self._settings.has_ebay_credentials:
            raise MissingCredentialsError()
        creds = f"{self._settings.ebay_client_id}:{self._settings.ebay_client_secret}"
        auth_header = base64.b64encode(creds.encode()).decode()
        response = self._client.post(
            f"{self._settings.ebay_api_base}{TOKEN_PATH}",
            headers={
                "Authorization": f"Basic {auth_header}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 7200))
        return self._token
