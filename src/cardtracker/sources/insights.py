"""Marketplace Insights adapter stub. Sold comps via API, if eBay ever approves access.

The Marketplace Insights API is gated to approved business partners. This adapter
keeps the slot open so approval later means implementing one method, not refactoring.
"""

from cardtracker.config import Settings
from cardtracker.models import CompSourceName, PriceType
from cardtracker.sources.base import CompRecord, CompSource


class InsightsNotEnabledError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Marketplace Insights is not enabled. It requires eBay partner approval. "
            "Set INSIGHTS_ENABLED=true in .env once approved. Until then, use CSV "
            "import for sold comps."
        )


class MarketplaceInsightsSource(CompSource):
    """Sold comps from the Marketplace Insights API. Disabled until approved."""

    source_name = CompSourceName.INSIGHTS
    price_type = PriceType.SOLD

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch_comps(self, query: str, limit: int = 50) -> list[CompRecord]:
        if not self._settings.insights_enabled:
            raise InsightsNotEnabledError()
        raise NotImplementedError(
            "Marketplace Insights fetch is not implemented yet. Implement this "
            "method against /buy/marketplace_insights/v1_beta/item_sales/search "
            "once eBay grants access."
        )
