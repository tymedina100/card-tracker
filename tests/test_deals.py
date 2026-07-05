from datetime import date

import pytest

from cardtracker.deals import find_deals, max_buy_price
from cardtracker.fees import FeeModel
from cardtracker.models import Comp, CompSourceName, PriceSnapshot, PriceType

AS_OF = date(2026, 7, 4)


def add_snapshot(session, card_id, median, price_type=PriceType.SOLD):
    session.add(PriceSnapshot(card_id=card_id, as_of_date=AS_OF,
                              price_type=price_type, median_30d=median))
    session.commit()


def add_ask(session, card_id, price, shipping=0.0, days_ago=1, title="", url=""):
    from datetime import timedelta

    session.add(Comp(card_id=card_id, source=CompSourceName.BROWSE,
                     price_type=PriceType.ASK, price=price, shipping=shipping,
                     sold_date_or_seen_date=AS_OF - timedelta(days=days_ago),
                     title_raw=title, listing_url=url))
    session.commit()


NO_FEES = FeeModel(final_value_pct=0.0, per_order_fee=0.0)


def test_max_buy_from_target_roi(session, sample_card):
    add_snapshot(session, sample_card.id, 130.0)
    result = max_buy_price(session, sample_card.id, NO_FEES, target_roi_pct=30.0)
    assert result.net_at_market == 130.0
    assert result.max_buy == 100.0
    assert result.market_price_type == "sold"


def test_max_buy_accounts_for_fees(session, sample_card):
    add_snapshot(session, sample_card.id, 100.0)
    model = FeeModel(final_value_pct=10.0, per_order_fee=0.0)
    result = max_buy_price(session, sample_card.id, model, target_roi_pct=0.0)
    assert result.net_at_market == 90.0
    assert result.max_buy == 90.0


def test_max_buy_from_target_profit(session, sample_card):
    add_snapshot(session, sample_card.id, 130.0)
    result = max_buy_price(session, sample_card.id, NO_FEES, target_profit=25.0)
    assert result.max_buy == 105.0


def test_max_buy_requires_exactly_one_target(session, sample_card):
    add_snapshot(session, sample_card.id, 130.0)
    with pytest.raises(ValueError):
        max_buy_price(session, sample_card.id, NO_FEES)
    with pytest.raises(ValueError):
        max_buy_price(session, sample_card.id, NO_FEES,
                      target_roi_pct=30.0, target_profit=10.0)


def test_max_buy_none_without_market_data(session, sample_card):
    assert max_buy_price(session, sample_card.id, NO_FEES, target_roi_pct=30.0) is None


def test_find_deals_flags_cheap_recent_asks(session, sample_card):
    add_snapshot(session, sample_card.id, 130.0)  # max buy 100 at 30% ROI
    add_ask(session, sample_card.id, 89.0, shipping=5.0, title="cheap one",
            url="https://ebay.com/itm/1")  # delivered 94, deal
    add_ask(session, sample_card.id, 120.0)  # over max buy
    deals = find_deals(session, NO_FEES, target_roi_pct=30.0, as_of=AS_OF)
    assert len(deals) == 1
    deal = deals[0]
    assert deal.delivered_price == 94.0
    assert deal.max_buy == 100.0
    assert deal.title == "cheap one"
    assert round(deal.discount_pct) == 6


def test_find_deals_ignores_stale_asks(session, sample_card):
    add_snapshot(session, sample_card.id, 130.0)
    add_ask(session, sample_card.id, 50.0, days_ago=20)  # cheap but stale
    assert find_deals(session, NO_FEES, target_roi_pct=30.0, days=14, as_of=AS_OF) == []


def test_deals_sorted_by_discount(session, sample_card):
    add_snapshot(session, sample_card.id, 130.0)
    add_ask(session, sample_card.id, 95.0)
    add_ask(session, sample_card.id, 60.0)
    deals = find_deals(session, NO_FEES, target_roi_pct=30.0, as_of=AS_OF)
    assert [d.delivered_price for d in deals] == [60.0, 95.0]
