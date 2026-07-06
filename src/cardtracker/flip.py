"""Card-flipping intelligence: eBay net proceeds, ROI, max buy price, and the
buy/hold/list/sell/pass recommendation engine.

This is the money brain of the app. Every formula lives here once so the
Portfolio, Cards, Card detail, Deals, and Calculators pages all agree. Pure
Python and fully testable: no database, no Streamlit.

All inputs tolerate ``None`` (treated as 0) and every division guards against a
zero denominator, so a half-filled card never raises.

Fee model (eBay managed payments for trading cards):

    gross_sale_total = sale_price + buyer_shipping_paid + sales_tax_collected
    ebay_fee         = gross_sale_total * fee_rate + fixed_order_fee
    promoted_fee     = sale_price * promoted_listing_pct
    net_proceeds     = sale_price + buyer_shipping_paid
                       - ebay_fee - promoted_fee - seller_shipping_cost - supplies_cost

Sales tax is collected by eBay and never reaches the seller, but it *does* raise
the fee base, which is why it appears in ``gross_sale_total`` but not in the
final ``net_proceeds`` credit.
"""

from dataclasses import dataclass
from enum import StrEnum

# ---- Defaults (overridable per call / per card) -------------------------------
DEFAULT_FEE_RATE = 0.1325        # 13.25% eBay final value fee
DEFAULT_FIXED_ORDER_FEE = 0.40   # per-order fixed fee, in dollars
DEFAULT_TARGET_ROI_PCT = 20.0    # used when a card has no target of its own
DEFAULT_STALE_DAYS = 45          # holdings older than this are "stale inventory"
LIST_BAND_PCT = 5.0              # ROI within this many points of target -> "List"


class Recommendation(StrEnum):
    """The action a card is telling you to take."""

    BUY = "Buy"
    HOLD = "Hold"
    LIST = "List"
    SELL_NOW = "Sell Now"
    PASS = "Pass"
    UNDERWATER = "Underwater"
    MISSING_DATA = "Missing Data"
    SOLD = "Sold"


def _num(value: float | None) -> float:
    """Coalesce an optional number to a float, treating ``None`` as 0."""
    return float(value) if value is not None else 0.0


@dataclass
class NetResult:
    """Itemized outcome of selling one item at ``sale_price``."""

    sale_price: float
    gross_sale_total: float   # amount the buyer pays, incl. shipping and tax
    ebay_fee: float
    promoted_fee: float
    net_proceeds: float       # what actually lands in the seller's pocket

    @property
    def total_cost_of_sale(self) -> float:
        """Everything the sale costs the seller (fees plus promo)."""
        return self.ebay_fee + self.promoted_fee

    @property
    def net_margin_pct(self) -> float | None:
        """Net proceeds as a percentage of the sale price. None if sale is 0."""
        if not self.sale_price:
            return None
        return self.net_proceeds / self.sale_price * 100


def net_proceeds(
    sale_price: float | None,
    *,
    buyer_shipping_paid: float | None = 0.0,
    sales_tax_collected: float | None = 0.0,
    seller_shipping_cost: float | None = 0.0,
    supplies_cost: float | None = 0.0,
    promoted_listing_pct: float | None = 0.0,
    fee_rate: float = DEFAULT_FEE_RATE,
    fixed_order_fee: float = DEFAULT_FIXED_ORDER_FEE,
) -> NetResult:
    """Net proceeds from selling one item, following the documented fee model.

    ``promoted_listing_pct`` is a fraction (0.02 for 2%), matching ``fee_rate``.
    """
    sale = _num(sale_price)
    buyer_ship = _num(buyer_shipping_paid)
    tax = _num(sales_tax_collected)

    # Buyer's total payment is the base eBay charges its percentage fee on.
    gross_sale_total = sale + buyer_ship + tax
    ebay_fee = gross_sale_total * fee_rate + fixed_order_fee
    # Promoted listing fee is charged on the item price only, not shipping/tax.
    promoted_fee = sale * _num(promoted_listing_pct)
    # Seller keeps item + shipping charged, minus every cost of doing the sale.
    net = (sale + buyer_ship - ebay_fee - promoted_fee
           - _num(seller_shipping_cost) - _num(supplies_cost))
    return NetResult(
        sale_price=sale,
        gross_sale_total=round(gross_sale_total, 2),
        ebay_fee=round(ebay_fee, 2),
        promoted_fee=round(promoted_fee, 2),
        net_proceeds=round(net, 2),
    )


def profit_and_roi(net: float | None,
                   total_cost_basis: float | None) -> tuple[float | None, float | None]:
    """(profit, roi_pct) of a sale netting ``net`` against ``total_cost_basis``.

    profit = net - cost. roi = profit / cost. Returns (None, None) when net is
    unknown, and roi None when there is no cost basis to divide by.
    """
    if net is None:
        return None, None
    cost = _num(total_cost_basis)
    profit = net - cost
    roi = (profit / cost * 100) if cost else None
    return round(profit, 2), (round(roi, 1) if roi is not None else None)


def max_buy_price(
    expected_sale_price: float | None,
    target_roi_pct: float | None,
    *,
    buyer_shipping_paid: float | None = 0.0,
    sales_tax_collected: float | None = 0.0,
    seller_shipping_cost: float | None = 0.0,
    supplies_cost: float | None = 0.0,
    promoted_listing_pct: float | None = 0.0,
    fee_rate: float = DEFAULT_FEE_RATE,
    fixed_order_fee: float = DEFAULT_FIXED_ORDER_FEE,
) -> float | None:
    """Most you can pay (delivered) and still clear ``target_roi_pct`` when you
    resell at ``expected_sale_price``. Works backward from net proceeds:

        max_buy = net_at_market / (1 + target_roi / 100)

    None when there is no expected sale price to work from.
    """
    if not expected_sale_price:
        return None
    net = net_proceeds(
        expected_sale_price,
        buyer_shipping_paid=buyer_shipping_paid,
        sales_tax_collected=sales_tax_collected,
        seller_shipping_cost=seller_shipping_cost,
        supplies_cost=supplies_cost,
        promoted_listing_pct=promoted_listing_pct,
        fee_rate=fee_rate,
        fixed_order_fee=fixed_order_fee,
    ).net_proceeds
    roi = _num(target_roi_pct)
    return round(net / (1 + roi / 100), 2)


def needed_sale_price(
    total_cost_basis: float | None,
    target_roi_pct: float | None,
    *,
    buyer_shipping_paid: float | None = 0.0,
    sales_tax_collected: float | None = 0.0,
    seller_shipping_cost: float | None = 0.0,
    supplies_cost: float | None = 0.0,
    promoted_listing_pct: float | None = 0.0,
    fee_rate: float = DEFAULT_FEE_RATE,
    fixed_order_fee: float = DEFAULT_FIXED_ORDER_FEE,
) -> float | None:
    """Sale price required to hit ``target_roi_pct`` on ``total_cost_basis``.

    Inverts the (linear) net-proceeds formula. Because net proceeds are linear
    in the sale price, we solve net(sale) = cost * (1 + roi/100) for ``sale``.
    None when the cost basis is unknown or the fee/promo rates make the
    denominator non-positive (a degenerate, unsolvable case).
    """
    cost = _num(total_cost_basis)
    if not cost:
        return None
    target_net = cost * (1 + _num(target_roi_pct) / 100)
    # net = sale*(1 - fee_rate - promo) + buyer_ship*(1 - fee_rate)
    #       - tax*fee_rate - fixed - seller_ship - supplies
    denom = 1 - fee_rate - _num(promoted_listing_pct)
    if denom <= 0:
        return None
    numerator = (target_net
                 - _num(buyer_shipping_paid) * (1 - fee_rate)
                 + _num(sales_tax_collected) * fee_rate
                 + fixed_order_fee
                 + _num(seller_shipping_cost)
                 + _num(supplies_cost))
    return round(numerator / denom, 2)


def recommend(
    *,
    status: str,
    market_value: float | None,
    cost_basis: float | None,
    profit_now: float | None,
    roi_now: float | None,
    target_roi_pct: float | None,
    asking_price: float | None = None,
    max_buy: float | None = None,
) -> tuple[Recommendation, str]:
    """Recommend an action and a one-sentence reason.

    Decision order (first match wins):
      1. sold                                   -> Sold
      2. owned/listed but no market value       -> Missing Data
      3. watching, asking at/under max buy      -> Buy
      4. watching, asking over max buy          -> Pass
      5. profit if sold now is negative         -> Underwater
      6. ROI >= target                          -> Sell Now
      7. ROI within LIST_BAND_PCT of target     -> List
      8. otherwise                              -> Hold
    """
    target = target_roi_pct if target_roi_pct is not None else DEFAULT_TARGET_ROI_PCT

    if status == "sold":
        return Recommendation.SOLD, "Already sold — no action needed."

    if market_value is None and status in ("owned", "listed"):
        return (Recommendation.MISSING_DATA,
                "No current market value set. Add one to get a recommendation.")

    if status == "watching":
        if asking_price is not None and max_buy is not None:
            if asking_price <= max_buy:
                return (Recommendation.BUY,
                        f"Asking ${asking_price:,.2f} is at or below your max buy "
                        f"${max_buy:,.2f} for a {target:.0f}% return. Good buy.")
            return (Recommendation.PASS,
                    f"Asking ${asking_price:,.2f} is above your max buy "
                    f"${max_buy:,.2f} for a {target:.0f}% return. "
                    f"Pass unless it drops ${asking_price - max_buy:,.2f}.")
        if market_value is None:
            return (Recommendation.MISSING_DATA,
                    "Watching, but no market value or asking price to judge a buy.")
        return (Recommendation.HOLD,
                "Watching. Add an asking price to see if it clears your max buy.")

    # From here the card is owned or listed and has a market value.
    if profit_now is not None and profit_now < 0:
        return (Recommendation.UNDERWATER,
                f"Net if sold today is below cost by ${abs(profit_now):,.2f}. "
                "Hold for recovery or sell to stop the bleed.")
    if roi_now is not None and roi_now >= target:
        return (Recommendation.SELL_NOW,
                f"Net ROI of {roi_now:+.1f}% meets your {target:.0f}% target. "
                "Lock in the profit.")
    if roi_now is not None and roi_now >= target - LIST_BAND_PCT:
        return (Recommendation.LIST,
                f"Net ROI of {roi_now:+.1f}% is within {LIST_BAND_PCT:.0f} points "
                f"of your {target:.0f}% target. List it and hold out for the ask.")
    if roi_now is not None:
        return (Recommendation.HOLD,
                f"Net ROI of {roi_now:+.1f}% is below your {target:.0f}% target. "
                "Hold unless you need the cash.")
    return (Recommendation.HOLD,
            f"Below your {target:.0f}% target for now. Hold.")


def confidence_bucket(confidence: float | None) -> str:
    """Map a 0..1 model confidence to Low / Medium / High. Deliberately
    conservative so predictions never read as more certain than they are."""
    c = _num(confidence)
    if c >= 0.6:
        return "High"
    if c >= 0.35:
        return "Medium"
    return "Low"


# ---- Scan: is this price a good buy? ----------------------------------------
# A single 0..100 score and a six-step rating scale for judging an asking price
# against market. Fed by the scan feature: enter a price now, and once comps
# (or a manual market value) exist, the same call grades it.

PENDING_RATING = "Pending comps"

# Ordered worst -> best. The scan meter and legend read off this list.
BUY_RATINGS = ["Overpriced", "Slight Overpay", "Fair",
               "Good Buy", "Great Buy", "Steal"]


def _score_to_rating(score: int) -> str:
    if score >= 90:
        return "Steal"
    if score >= 75:
        return "Great Buy"
    if score >= 60:
        return "Good Buy"
    if score >= 45:
        return "Fair"
    if score >= 30:
        return "Slight Overpay"
    return "Overpriced"


@dataclass
class BuyGrade:
    """How good a buy a given price is against market, on a 0..100 scale."""

    price: float
    market_value: float | None
    roi_at_price: float | None   # net ROI if bought here and resold at market
    max_buy: float | None        # most you'd pay for the target ROI
    score: int | None            # 0..100, None until a market value exists
    rating: str                  # one of BUY_RATINGS, or PENDING_RATING
    reason: str

    @property
    def is_pending(self) -> bool:
        return self.score is None


def grade_buy(
    price: float | None,
    market_value: float | None,
    *,
    target_roi_pct: float | None = DEFAULT_TARGET_ROI_PCT,
    **exit_kwargs,
) -> BuyGrade:
    """Grade paying ``price`` for a card worth ``market_value``.

    ``exit_kwargs`` are the same resale assumptions net_proceeds accepts
    (buyer_shipping_paid, seller_shipping_cost, supplies_cost,
    promoted_listing_pct, fee_rate, fixed_order_fee).

    Until a market value is known (no comps and no manual value), the grade is
    "Pending comps": the price is remembered and graded the moment a value
    lands. The scoring anchors on ROI relative to the target: break-even scores
    ~40, hitting the target scores ~70, doubling it scores ~100.
    """
    target = target_roi_pct if target_roi_pct is not None else DEFAULT_TARGET_ROI_PCT
    max_buy = (max_buy_price(market_value, target, **exit_kwargs)
               if market_value else None)

    if not price or market_value is None:
        return BuyGrade(
            price=_num(price), market_value=market_value, roi_at_price=None,
            max_buy=max_buy, score=None, rating=PENDING_RATING,
            reason=("Saved. We'll grade this the moment comps or a market value "
                    "exist for the card."),
        )

    net_at_market = net_proceeds(market_value, **exit_kwargs).net_proceeds
    _, roi = profit_and_roi(net_at_market, price)  # ROI buying here, selling at market
    roi = roi if roi is not None else 0.0

    if target > 0:
        raw = 40 + (roi / target) * 30
    else:
        raw = 50 + roi
    score = int(max(0, min(100, round(raw))))
    rating = _score_to_rating(score)

    reason = (f"At ${price:,.2f} you'd net about {roi:+.1f}% after fees against "
              f"your {target:.0f}% target (max buy ${max_buy:,.2f}). Rated "
              f"{rating}.")
    return BuyGrade(
        price=_num(price), market_value=market_value, roi_at_price=round(roi, 1),
        max_buy=max_buy, score=score, rating=rating, reason=reason,
    )
