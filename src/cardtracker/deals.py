"""Deal analyzer: the most I should pay for a card to hit a target return.

Max buy price works backward from the exit: take the current market stat
(30 day sold median, ask median as a flagged fallback), compute net proceeds
after the fee model, then divide by 1 + target ROI (or subtract a target
profit). Any active ask listing delivered below that number is a deal.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session, select

from cardtracker.fees import FeeModel, compute_net
from cardtracker.models import Card, Comp, PriceType
from cardtracker.portfolio import market_value


@dataclass
class MaxBuyResult:
    card: Card
    market: float
    market_price_type: str
    net_at_market: float
    max_buy: float
    target_roi_pct: float | None
    target_profit: float | None


@dataclass
class Deal:
    card: Card
    max_buy: float
    delivered_price: float
    seen_date: date
    title: str
    listing_url: str
    market_price_type: str

    @property
    def discount_pct(self) -> float:
        return (self.max_buy - self.delivered_price) / self.max_buy * 100


def max_buy_price(session: Session, card_id: int, fee_model: FeeModel,
                  target_roi_pct: float | None = None,
                  target_profit: float | None = None,
                  shipping_cost: float = 0.0) -> MaxBuyResult | None:
    """Highest total price (delivered) to pay and still hit the target when
    selling at the current market stat. None when the card has no market data."""
    if (target_roi_pct is None) == (target_profit is None):
        raise ValueError("Set exactly one of target_roi_pct or target_profit")
    market = market_value(session, card_id)
    if market is None:
        return None
    value, price_type, _ = market
    net = compute_net(fee_model, value, shipping_cost=shipping_cost).net
    if target_roi_pct is not None:
        max_buy = net / (1 + target_roi_pct / 100)
    else:
        max_buy = net - target_profit
    return MaxBuyResult(
        card=session.get(Card, card_id),
        market=value,
        market_price_type=price_type,
        net_at_market=net,
        max_buy=round(max_buy, 2),
        target_roi_pct=target_roi_pct,
        target_profit=target_profit,
    )


def find_deals(session: Session, fee_model: FeeModel, target_roi_pct: float = 30.0,
               days: int = 14, shipping_cost: float = 0.0,
               as_of: date | None = None, *, owner: str = "") -> list[Deal]:
    """Active ask listings from the last N days delivered below max buy price,
    across the owner's cards, best discount first."""
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=days)
    deals: list[Deal] = []
    for card in session.exec(select(Card).where(Card.owner == owner)).all():
        result = max_buy_price(session, card.id, fee_model,
                               target_roi_pct=target_roi_pct,
                               shipping_cost=shipping_cost)
        if result is None:
            continue
        asks = session.exec(
            select(Comp)
            .where(Comp.card_id == card.id)
            .where(Comp.price_type == PriceType.ASK)
            .where(Comp.sold_date_or_seen_date > cutoff)
            .where(Comp.sold_date_or_seen_date <= as_of)
        ).all()
        for ask in asks:
            delivered = ask.price + ask.shipping
            if delivered <= result.max_buy:
                deals.append(Deal(
                    card=card,
                    max_buy=result.max_buy,
                    delivered_price=delivered,
                    seen_date=ask.sold_date_or_seen_date,
                    title=ask.title_raw,
                    listing_url=ask.listing_url,
                    market_price_type=result.market_price_type,
                ))
    deals.sort(key=lambda d: d.discount_pct, reverse=True)
    return deals
