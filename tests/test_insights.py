import pytest

from cardtracker.config import Settings
from cardtracker.sources import InsightsNotEnabledError, MarketplaceInsightsSource


def test_disabled_by_default():
    source = MarketplaceInsightsSource(Settings())
    with pytest.raises(InsightsNotEnabledError, match="CSV"):
        source.fetch_comps("anything")


def test_enabled_but_unimplemented():
    source = MarketplaceInsightsSource(Settings(insights_enabled=True))
    with pytest.raises(NotImplementedError):
        source.fetch_comps("anything")
