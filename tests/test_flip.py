"""Unit tests for the flip intelligence engine (fees, ROI, max buy, recs)."""

import pytest

from cardtracker import flip
from cardtracker.flip import Recommendation


def test_net_proceeds_default_fees():
    # 13.25% of 100 plus the $0.40 fixed order fee.
    result = flip.net_proceeds(100.0)
    assert result.gross_sale_total == 100.0
    assert result.ebay_fee == 13.65
    assert result.promoted_fee == 0.0
    assert result.net_proceeds == 86.35


def test_net_proceeds_includes_shipping_tax_and_promoted():
    result = flip.net_proceeds(
        400.0, buyer_shipping_paid=5.0, sales_tax_collected=30.0,
        seller_shipping_cost=6.0, supplies_cost=1.0, promoted_listing_pct=0.02,
    )
    # gross = 400 + 5 + 30 = 435; fee = 435*0.1325 + 0.40 = 58.0375 -> 58.04
    assert result.gross_sale_total == 435.0
    assert result.ebay_fee == 58.04
    # promoted is on the item price only: 400 * 0.02 = 8.00
    assert result.promoted_fee == 8.0
    # net = 400 + 5 - 58.04 - 8 - 6 - 1 = 331.96
    assert result.net_proceeds == 331.96


def test_net_proceeds_handles_none_without_crashing():
    result = flip.net_proceeds(None)
    # Selling nothing still incurs the fixed order fee; must not raise.
    assert result.net_proceeds == -0.40


def test_net_margin_pct():
    result = flip.net_proceeds(200.0)
    assert result.net_margin_pct == pytest.approx(86.6, abs=0.1)
    assert flip.net_proceeds(0.0).net_margin_pct is None


def test_profit_and_roi():
    profit, roi = flip.profit_and_roi(346.60, 300.0)
    assert profit == 46.60
    assert roi == pytest.approx(15.5, abs=0.1)


def test_profit_and_roi_zero_cost_gives_no_roi():
    profit, roi = flip.profit_and_roi(50.0, 0.0)
    assert profit == 50.0
    assert roi is None


def test_profit_and_roi_unknown_net():
    assert flip.profit_and_roi(None, 100.0) == (None, None)


def test_max_buy_price_backs_out_target_roi():
    # net at market $400 default = 346.60; /1.2 = 288.83
    assert flip.max_buy_price(400.0, 20.0) == 288.83


def test_max_buy_price_none_without_market():
    assert flip.max_buy_price(None, 20.0) is None
    assert flip.max_buy_price(0.0, 20.0) is None


def test_needed_sale_price_round_trips_through_net():
    needed = flip.needed_sale_price(308.20, 20.0)
    # Selling at `needed` should net roughly cost * 1.20.
    net = flip.net_proceeds(needed).net_proceeds
    assert net == pytest.approx(308.20 * 1.20, abs=0.05)


def test_needed_sale_price_none_without_cost():
    assert flip.needed_sale_price(None, 20.0) is None
    assert flip.needed_sale_price(0.0, 20.0) is None


def _rec(**kwargs):
    defaults = dict(status="owned", market_value=400.0, cost_basis=300.0,
                    profit_now=40.0, roi_now=13.0, target_roi_pct=20.0)
    defaults.update(kwargs)
    return flip.recommend(**defaults)[0]


def test_recommend_sold():
    assert _rec(status="sold") == Recommendation.SOLD


def test_recommend_missing_data():
    assert _rec(status="owned", market_value=None) == Recommendation.MISSING_DATA


def test_recommend_buy_and_pass_for_watching():
    assert _rec(status="watching", asking_price=280.0,
                max_buy=288.83) == Recommendation.BUY
    assert _rec(status="watching", asking_price=300.0,
                max_buy=288.83) == Recommendation.PASS


def test_recommend_underwater():
    assert _rec(profit_now=-25.0, roi_now=-8.0) == Recommendation.UNDERWATER


def test_recommend_sell_now_at_or_above_target():
    assert _rec(roi_now=25.0) == Recommendation.SELL_NOW
    assert _rec(roi_now=20.0) == Recommendation.SELL_NOW


def test_recommend_list_within_band():
    # 17% is within 5 points of a 20% target.
    assert _rec(roi_now=17.0) == Recommendation.LIST


def test_recommend_hold_below_band():
    assert _rec(roi_now=5.0) == Recommendation.HOLD


def test_recommend_returns_reason_sentence():
    label, reason = flip.recommend(
        status="owned", market_value=400.0, cost_basis=300.0,
        profit_now=40.0, roi_now=25.0, target_roi_pct=20.0)
    assert label == Recommendation.SELL_NOW
    assert isinstance(reason, str) and reason


def test_confidence_buckets():
    assert flip.confidence_bucket(0.75) == "High"
    assert flip.confidence_bucket(0.5) == "Medium"
    assert flip.confidence_bucket(0.2) == "Low"
    assert flip.confidence_bucket(None) == "Low"


def test_grade_buy_pending_without_market():
    grade = flip.grade_buy(300.0, None)
    assert grade.is_pending
    assert grade.score is None
    assert grade.rating == flip.PENDING_RATING


def test_grade_buy_pending_without_price():
    grade = flip.grade_buy(None, 400.0)
    assert grade.is_pending
    # max buy can still be shown even before a price is entered
    assert grade.max_buy is not None


def test_grade_buy_cheap_price_scores_high():
    # Market 400 nets ~346.60; buying at 250 is a strong ROI -> Steal/Great.
    grade = flip.grade_buy(250.0, 400.0, target_roi_pct=20.0)
    assert grade.score is not None and grade.score >= 75
    assert grade.rating in {"Great Buy", "Steal"}
    assert grade.roi_at_price is not None and grade.roi_at_price > 20


def test_grade_buy_at_market_is_overpriced():
    grade = flip.grade_buy(400.0, 400.0, target_roi_pct=20.0)
    assert grade.score is not None and grade.score < 45
    assert grade.rating in {"Overpriced", "Slight Overpay"}


def test_grade_buy_score_is_bounded():
    assert 0 <= flip.grade_buy(10.0, 400.0).score <= 100
    assert 0 <= flip.grade_buy(5000.0, 400.0).score <= 100


def test_grade_buy_reason_mentions_rating():
    grade = flip.grade_buy(250.0, 400.0)
    assert grade.rating in grade.reason
