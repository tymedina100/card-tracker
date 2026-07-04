from datetime import date

import httpx
from sqlmodel import select

from cardtracker.ebay_auth import EbayTokenProvider
from cardtracker.models import Comp
from cardtracker.sources import BrowseApiSource, save_comps

SAMPLE_PAYLOAD = {
    "itemSummaries": [
        {
            "title": "1999 Pokemon Base Set Charizard PSA 9",
            "price": {"value": "450.00", "currency": "USD"},
            "condition": "Graded",
            "itemWebUrl": "https://ebay.com/itm/111",
            "shippingOptions": [{"shippingCost": {"value": "4.99", "currency": "USD"}}],
        },
        {
            "title": "Charizard Base Set Holo PSA 9",
            "price": {"value": "469.99", "currency": "USD"},
            "itemWebUrl": "https://ebay.com/itm/222",
        },
        {
            "title": "Listing with no price should be skipped",
            "price": {},
        },
    ]
}


class FakeTokenProvider(EbayTokenProvider):
    def __init__(self):
        pass

    def get_token(self) -> str:
        return "fake-token"


def make_source(settings, handler):
    return BrowseApiSource(
        settings,
        token_provider=FakeTokenProvider(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_fetch_maps_listings_to_ask_records(settings_with_creds):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers["Authorization"]
        seen["marketplace"] = request.headers["X-EBAY-C-MARKETPLACE-ID"]
        seen["q"] = request.url.params["q"]
        return httpx.Response(200, json=SAMPLE_PAYLOAD)

    source = make_source(settings_with_creds, handler)
    records = source.fetch_comps("charizard psa 9", limit=50)

    assert seen["path"] == "/buy/browse/v1/item_summary/search"
    assert seen["auth"] == "Bearer fake-token"
    assert seen["marketplace"] == "EBAY_US"
    assert seen["q"] == "charizard psa 9"
    assert len(records) == 2  # priceless listing skipped
    assert records[0].price == 450.0
    assert records[0].shipping == 4.99
    assert records[1].shipping == 0.0
    assert records[0].observed_date == date.today()


def test_saved_browse_comps_stamped_ask(session, sample_card, settings_with_creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_PAYLOAD)

    source = make_source(settings_with_creds, handler)
    save_comps(session, sample_card.id, source, source.fetch_comps("charizard"))
    comps = session.exec(select(Comp)).all()
    assert len(comps) == 2
    assert all(c.source == "browse" and c.price_type == "ask" for c in comps)


def test_limit_capped_at_200(settings_with_creds):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["limit"] = request.url.params["limit"]
        return httpx.Response(200, json={"itemSummaries": []})

    make_source(settings_with_creds, handler).fetch_comps("q", limit=500)
    assert seen["limit"] == "200"
