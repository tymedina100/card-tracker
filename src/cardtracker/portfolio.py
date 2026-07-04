"""My holdings: buy logging and cost basis.

One buy transaction represents one copy of a card. The total cost of a buy
is price plus fees, shipping, taxes, and grading cost. A card's cost basis
is the sum across its buy transactions; per-copy cost is the average.
"""

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from cardtracker.models import Card, Inventory, InventoryStatus, Transaction, TransactionType


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
