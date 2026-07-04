"""Active-listing comps from the eBay Browse API. Standard developer keys unlock this."""

from datetime import date

import httpx

from cardtracker.config import Settings
from cardtracker.ebay_auth import EbayTokenProvider
from cardtracker.models import CompSourceName, PriceType
from cardtracker.sources.base import CompRecord, CompSource

SEARCH_PATH = "/buy/browse/v1/item_summary/search"


class BrowseApiSource(CompSource):
    """Pulls active listings and their asking prices. Never produces sold comps."""

    source_name = CompSourceName.BROWSE
    price_type = PriceType.ASK

    def __init__(self, settings: Settings, token_provider: EbayTokenProvider | None = None,
                 client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._token_provider = token_provider or EbayTokenProvider(settings)
        self._client = client or httpx.Client(timeout=30)

    def fetch_comps(self, query: str, limit: int = 50) -> list[CompRecord]:
        token = self._token_provider.get_token()
        response = self._client.get(
            f"{self._settings.ebay_api_base}{SEARCH_PATH}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self._settings.ebay_marketplace_id,
            },
            params={"q": query, "limit": min(limit, 200)},
        )
        response.raise_for_status()
        items = response.json().get("itemSummaries", [])
        today = date.today()
        records = []
        for item in items:
            price = item.get("price", {})
            if "value" not in price:
                continue
            shipping = 0.0
            for option in item.get("shippingOptions", []):
                cost = option.get("shippingCost", {})
                if "value" in cost:
                    shipping = float(cost["value"])
                    break
            records.append(
                CompRecord(
                    price=float(price["value"]),
                    observed_date=today,
                    shipping=shipping,
                    currency=price.get("currency", "USD"),
                    listing_url=item.get("itemWebUrl", ""),
                    title_raw=item.get("title", ""),
                    condition_raw=item.get("condition", ""),
                )
            )
        return records
