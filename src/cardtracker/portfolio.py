"""My holdings: buy logging and cost basis.

One buy transaction represents one copy of a card. The total cost of a buy
is price plus fees, shipping, taxes, and grading cost. A card's cost basis
is the sum across its buy transactions; per-copy cost is the average.
"""

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from cardtracker.fees import FeeModel, compute_net
from cardtracker.models import Card, Inventory, InventoryStatus, Transaction, TransactionType
from cardtracker.stats import latest_snapshots


def market_value(session: Session, card_id: int) -> tuple[float, str, date] | None:
    """Current market stat for a card: latest 30 day sold median, falling back
    to the ask median flagged as such. (value, 'sold'|'ask', as_of) or None."""
    snapshots = latest_snapshots(session, card_id)
    for price_type in ("sold", "ask"):
        snapshot = snapshots.get(price_type)
        if snapshot is not None and snapshot.median_30d:
            return snapshot.median_30d, price_type, snapshot.as_of_date
    return None


@dataclass
class CostBasisLine:
    """Cost basis for one card across all owned copies."""

    card: Card
    copies: int
    price_total: float
    fees_total: float
    shipping_total: float
    taxes_total: float
    grading_total: float

    @property
    def total_cost(self) -> float:
        return (self.price_total + self.fees_total + self.shipping_total
                + self.taxes_total + self.grading_total)

    @property
    def cost_per_copy(self) -> float:
        return self.total_cost / self.copies if self.copies else 0.0


def get_or_create_inventory(session: Session, card_id: int) -> Inventory:
    inventory = session.exec(
        select(Inventory).where(Inventory.card_id == card_id)
    ).first()
    if inventory is None:
        inventory = Inventory(card_id=card_id, quantity=0)
        session.add(inventory)
    return inventory


def log_buy(session: Session, card_id: int, price: float, buy_date: date | None = None,
            fees: float = 0.0, shipping: float = 0.0, taxes: float = 0.0,
            grading: float = 0.0, platform: str = "", notes: str = "") -> Transaction:
    """Record buying one copy. Creates the transaction and keeps the inventory
    row in sync: owned status, quantity, earliest acquired date, total cost basis."""
    transaction = Transaction(
        card_id=card_id,
        type=TransactionType.BUY,
        date=buy_date or date.today(),
        price=price,
        fees=fees,
        shipping_cost=shipping,
        taxes=taxes,
        grading_cost=grading,
        platform=platform,
        notes=notes,
    )
    session.add(transaction)
    inventory = get_or_create_inventory(session, card_id)
    inventory.status = InventoryStatus.OWNED
    inventory.quantity += 1
    if inventory.acquired_date is None or transaction.date < inventory.acquired_date:
        inventory.acquired_date = transaction.date
    inventory.cost_basis = (inventory.cost_basis or 0.0) + transaction.total_cost
    session.add(inventory)
    session.commit()
    session.refresh(transaction)
    return transaction


@dataclass
class UnrealizedLine:
    """Profit and ROI if one card's owned copies were sold at market now."""

    card: Card
    quantity: int
    cost_basis: float
    market_per_copy: float | None
    market_price_type: str | None
    market_as_of: date | None
    net_per_copy: float | None

    @property
    def net_value(self) -> float | None:
        return self.net_per_copy * self.quantity if self.net_per_copy is not None else None

    @property
    def profit(self) -> float | None:
        return self.net_value - self.cost_basis if self.net_value is not None else None

    @property
    def roi_pct(self) -> float | None:
        if self.profit is None or not self.cost_basis:
            return None
        return self.profit / self.cost_basis * 100


def unrealized_summary(session: Session, fee_model: FeeModel,
                       shipping_cost: float = 0.0) -> list[UnrealizedLine]:
    """Profit if sold now for every held card (owned or listed, quantity > 0):
    market stat minus fees minus cost basis. Cards without snapshots get a line
    with no market value so they are visible rather than silently dropped."""
    holdings = session.exec(
        select(Inventory)
        .where(Inventory.quantity > 0)
        .where(Inventory.status.in_((InventoryStatus.OWNED, InventoryStatus.LISTED)))
        .order_by(Inventory.card_id)
    ).all()
    lines = []
    for holding in holdings:
        market = market_value(session, holding.card_id)
        if market is not None:
            value, price_type, as_of = market
            net = compute_net(fee_model, value, shipping_cost=shipping_cost).net
        else:
            value, price_type, as_of, net = None, None, None, None
        lines.append(UnrealizedLine(
            card=session.get(Card, holding.card_id),
            quantity=holding.quantity,
            cost_basis=holding.cost_basis or 0.0,
            market_per_copy=value,
            market_price_type=price_type,
            market_as_of=as_of,
            net_per_copy=net,
        ))
    return lines


def cost_basis_summary(session: Session, card_id: int | None = None) -> list[CostBasisLine]:
    """Per-card cost basis built from buy transactions."""
    query = select(Transaction).where(Transaction.type == TransactionType.BUY)
    if card_id is not None:
        query = query.where(Transaction.card_id == card_id)
    buys = session.exec(query).all()
    by_card: dict[int, list[Transaction]] = {}
    for buy in buys:
        by_card.setdefault(buy.card_id, []).append(buy)
    lines = []
    for cid, card_buys in sorted(by_card.items()):
        card = session.get(Card, cid)
        lines.append(CostBasisLine(
            card=card,
            copies=len(card_buys),
            price_total=sum(b.price for b in card_buys),
            fees_total=sum(b.fees for b in card_buys),
            shipping_total=sum(b.shipping_cost for b in card_buys),
            taxes_total=sum(b.taxes for b in card_buys),
            grading_total=sum(b.grading_cost for b in card_buys),
        ))
    return lines
