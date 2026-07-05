"""eBay net-after-fees calculator with a configurable fee model.

Defaults mirror eBay managed payments for trading cards: a final value fee
around 13.25 percent applied to the full amount the buyer pays (item price
plus shipping plus sales tax), plus a small per-order fixed fee. Payment
processing is bundled into the final value fee on eBay, so the separate
processing knobs default to zero but exist for other platforms.

Every knob can be overridden in .env (see .env.example) or per call.
"""

from dataclasses import dataclass, field

from cardtracker.config import Settings


@dataclass
class FeeModel:
    final_value_pct: float = 13.25
    per_order_fee: float = 0.30
    promoted_pct: float = 0.0
    payment_pct: float = 0.0
    payment_fixed: float = 0.0
    fvf_on_shipping: bool = True
    fvf_on_tax: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> "FeeModel":
        return cls(
            final_value_pct=settings.fee_final_value_pct,
            per_order_fee=settings.fee_per_order,
            promoted_pct=settings.fee_promoted_pct,
            payment_pct=settings.fee_payment_pct,
            payment_fixed=settings.fee_payment_fixed,
            fvf_on_shipping=settings.fee_fvf_on_shipping,
            fvf_on_tax=settings.fee_fvf_on_tax,
        )


@dataclass
class FeeLine:
    label: str
    amount: float


@dataclass
class FeeBreakdown:
    sale_price: float
    shipping_charged: float
    tax_collected: float
    shipping_cost: float
    lines: list[FeeLine] = field(default_factory=list)

    @property
    def gross_to_seller(self) -> float:
        """What the buyer pays that the seller would keep before fees.
        Sales tax is collected by eBay and never reaches the seller."""
        return self.sale_price + self.shipping_charged

    @property
    def total_fees(self) -> float:
        return sum(line.amount for line in self.lines)

    @property
    def net(self) -> float:
        return self.gross_to_seller - self.total_fees - self.shipping_cost


def compute_net(model: FeeModel, sale_price: float, shipping_charged: float = 0.0,
                tax_collected: float = 0.0, shipping_cost: float = 0.0,
                promoted_pct: float | None = None) -> FeeBreakdown:
    """Itemized net proceeds for a sale. promoted_pct overrides the model's
    default promoted-listing rate for this one sale when given."""
    fee_base = sale_price
    if model.fvf_on_shipping:
        fee_base += shipping_charged
    if model.fvf_on_tax:
        fee_base += tax_collected
    promo_rate = model.promoted_pct if promoted_pct is None else promoted_pct

    lines = [FeeLine(f"final value fee {model.final_value_pct}% of {fee_base:.2f}",
                     round(fee_base * model.final_value_pct / 100, 2))]
    if promo_rate:
        lines.append(FeeLine(f"promoted listing {promo_rate}% of {fee_base:.2f}",
                             round(fee_base * promo_rate / 100, 2)))
    if model.per_order_fee:
        lines.append(FeeLine("per-order fee", model.per_order_fee))
    if model.payment_pct or model.payment_fixed:
        amount = round(fee_base * model.payment_pct / 100 + model.payment_fixed, 2)
        lines.append(FeeLine(f"payment processing {model.payment_pct}% + "
                             f"{model.payment_fixed:.2f}", amount))
    return FeeBreakdown(
        sale_price=sale_price,
        shipping_charged=shipping_charged,
        tax_collected=tax_collected,
        shipping_cost=shipping_cost,
        lines=lines,
    )
