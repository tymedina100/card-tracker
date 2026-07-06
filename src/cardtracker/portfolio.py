"""My holdings: buy logging and cost basis.

One buy transaction represents one copy of a card. The total cost of a buy
is price plus fees, shipping, taxes, and grading cost. A card's cost basis
is the sum across its buy transactions; per-copy cost is the average.
"""

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from cardtracker import flip
from cardtracker.fees import FeeModel, compute_net
from cardtracker.models import (
    Card,
    Comp,
    Inventory,
    InventoryStatus,
    Prediction,
    PriceSnapshot,
    Transaction,
    TransactionType,
)
from cardtracker.stats import latest_snapshots


def delete_card(session: Session, card_id: int, *, owner: str = "") -> bool:
    """Remove a card and everything hanging off it (comps, snapshots, buys and
    sells, inventory, predictions). Scoped to the owner: returns False and does
    nothing if the card is missing or belongs to someone else."""
    card = session.exec(
        select(Card).where(Card.id == card_id).where(Card.owner == owner)
    ).first()
    if card is None:
        return False
    for model in (Comp, PriceSnapshot, Prediction, Transaction, Inventory):
        for row in session.exec(select(model).where(model.card_id == card_id)).all():
            session.delete(row)
    session.delete(card)
    session.commit()
    return True


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


def get_or_create_inventory(session: Session, card_id: int, *, owner: str = "") -> Inventory:
    inventory = session.exec(
        select(Inventory)
        .where(Inventory.card_id == card_id)
        .where(Inventory.owner == owner)
    ).first()
    if inventory is None:
        inventory = Inventory(card_id=card_id, owner=owner, quantity=0)
        session.add(inventory)
    return inventory


def log_buy(session: Session, card_id: int, price: float, buy_date: date | None = None,
            fees: float = 0.0, shipping: float = 0.0, taxes: float = 0.0,
            grading: float = 0.0, platform: str = "", notes: str = "", *,
            owner: str = "") -> Transaction:
    """Record buying one copy. Creates the transaction and keeps the inventory
    row in sync: owned status, quantity, earliest acquired date, total cost basis."""
    transaction = Transaction(
        card_id=card_id,
        owner=owner,
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
    inventory = get_or_create_inventory(session, card_id, owner=owner)
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


def unrealized_summary(session: Session, fee_model: FeeModel, *, owner: str = "",
                       shipping_cost: float = 0.0) -> list[UnrealizedLine]:
    """Profit if sold now for every held card (owned or listed, quantity > 0):
    market stat minus fees minus cost basis. Cards without snapshots get a line
    with no market value so they are visible rather than silently dropped."""
    holdings = session.exec(
        select(Inventory)
        .where(Inventory.owner == owner)
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


def log_sell(session: Session, card_id: int, price: float, sell_date: date | None = None,
             fees: float = 0.0, shipping_cost: float = 0.0, platform: str = "",
             notes: str = "", *, owner: str = "") -> Transaction:
    """Record selling one copy with actual sale price and actual fees. Inventory
    quantity drops by one; status flips to sold when nothing is left."""
    transaction = Transaction(
        card_id=card_id,
        owner=owner,
        type=TransactionType.SELL,
        date=sell_date or date.today(),
        price=price,
        fees=fees,
        shipping_cost=shipping_cost,
        platform=platform,
        notes=notes,
    )
    session.add(transaction)
    inventory = get_or_create_inventory(session, card_id, owner=owner)
    inventory.quantity = max(0, inventory.quantity - 1)
    if inventory.quantity == 0:
        inventory.status = InventoryStatus.SOLD
    session.add(inventory)
    session.commit()
    session.refresh(transaction)
    return transaction


def avg_cost_per_copy(session: Session, card_id: int, *, owner: str = "") -> float | None:
    """Average total buy cost across all copies of a card ever bought."""
    buys = session.exec(
        select(Transaction)
        .where(Transaction.owner == owner)
        .where(Transaction.type == TransactionType.BUY)
        .where(Transaction.card_id == card_id)
    ).all()
    if not buys:
        return None
    return sum(b.total_cost for b in buys) / len(buys)


@dataclass
class RealizedLine:
    """Actual profit from one logged sale."""

    card: Card
    sale_date: date
    sale_price: float
    fees: float
    shipping_cost: float
    cost_allocated: float | None
    platform: str

    @property
    def net(self) -> float:
        return self.sale_price - self.fees - self.shipping_cost

    @property
    def profit(self) -> float | None:
        return self.net - self.cost_allocated if self.cost_allocated is not None else None

    @property
    def roi_pct(self) -> float | None:
        if self.profit is None or not self.cost_allocated:
            return None
        return self.profit / self.cost_allocated * 100


def realized_summary(session: Session, *, owner: str = "",
                     card_id: int | None = None) -> list[RealizedLine]:
    """Realized P&L across all logged sells. Cost is allocated per copy as the
    average buy cost for that card; sells with no logged buy show no profit."""
    query = (select(Transaction)
             .where(Transaction.owner == owner)
             .where(Transaction.type == TransactionType.SELL))
    if card_id is not None:
        query = query.where(Transaction.card_id == card_id)
    sells = session.exec(query.order_by(Transaction.date)).all()
    costs: dict[int, float | None] = {}
    lines = []
    for sell in sells:
        if sell.card_id not in costs:
            costs[sell.card_id] = avg_cost_per_copy(session, sell.card_id, owner=owner)
        lines.append(RealizedLine(
            card=session.get(Card, sell.card_id),
            sale_date=sell.date,
            sale_price=sell.price,
            fees=sell.fees,
            shipping_cost=sell.shipping_cost,
            cost_allocated=costs[sell.card_id],
            platform=sell.platform,
        ))
    return lines


def set_status(session: Session, card_id: int, status: InventoryStatus | None = None,
               quantity: int | None = None, listed_price: float | None = None, *,
               owner: str = "") -> Inventory:
    """Update inventory status, quantity, or listed price for a card."""
    inventory = get_or_create_inventory(session, card_id, owner=owner)
    if status is not None:
        inventory.status = status
    if quantity is not None:
        inventory.quantity = quantity
    if listed_price is not None:
        inventory.listed_price = listed_price
    session.add(inventory)
    session.commit()
    session.refresh(inventory)
    return inventory


def set_targets(session: Session, card_id: int, target_sell_price: float | None = None,
                min_accept_price: float | None = None, *, owner: str = "") -> Inventory:
    """Store target sell price and minimum acceptable price for a card."""
    inventory = get_or_create_inventory(session, card_id, owner=owner)
    if target_sell_price is not None:
        inventory.target_sell_price = target_sell_price
    if min_accept_price is not None:
        inventory.min_accept_price = min_accept_price
    session.add(inventory)
    session.commit()
    session.refresh(inventory)
    return inventory


def set_market_inputs(session: Session, card_id: int, *, owner: str = "",
                      manual_market_value: float | None = None,
                      last_sold_price: float | None = None,
                      lowest_active_ask: float | None = None,
                      target_roi_pct: float | None = None,
                      date_listed: date | None = None,
                      supplies_cost: float | None = None,
                      buyer_shipping_paid: float | None = None,
                      seller_shipping_cost: float | None = None,
                      promoted_listing_pct: float | None = None) -> Inventory:
    """Persist the hand-entered market values and exit assumptions for a card.

    Each argument overwrites the stored value, so pass the current value to keep
    it and ``None`` to clear it. These feed effective_market_value and the whole
    recommendation engine."""
    inventory = get_or_create_inventory(session, card_id, owner=owner)
    inventory.manual_market_value = manual_market_value
    inventory.last_sold_price = last_sold_price
    inventory.lowest_active_ask = lowest_active_ask
    inventory.target_roi_pct = target_roi_pct
    inventory.date_listed = date_listed
    inventory.supplies_cost = supplies_cost
    inventory.buyer_shipping_paid = buyer_shipping_paid
    inventory.seller_shipping_cost = seller_shipping_cost
    inventory.promoted_listing_pct = promoted_listing_pct
    session.add(inventory)
    session.commit()
    session.refresh(inventory)
    return inventory


@dataclass
class InventoryLine:
    inventory: Inventory
    card: Card
    market_per_copy: float | None
    market_price_type: str | None


def inventory_view(session: Session, status: InventoryStatus | None = None, *,
                   owner: str = "") -> list[InventoryLine]:
    """All inventory rows, optionally filtered by status, with the current
    market stat alongside so targets can be judged at a glance."""
    query = (select(Inventory)
             .where(Inventory.owner == owner)
             .order_by(Inventory.card_id))
    if status is not None:
        query = query.where(Inventory.status == status)
    rows = session.exec(query).all()
    lines = []
    for row in rows:
        market = market_value(session, row.card_id)
        lines.append(InventoryLine(
            inventory=row,
            card=session.get(Card, row.card_id),
            market_per_copy=market[0] if market else None,
            market_price_type=market[1] if market else None,
        ))
    return lines


def cost_basis_summary(session: Session, *, owner: str = "",
                       card_id: int | None = None) -> list[CostBasisLine]:
    """Per-card cost basis built from buy transactions."""
    query = (select(Transaction)
             .where(Transaction.owner == owner)
             .where(Transaction.type == TransactionType.BUY))
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


def effective_market_value(session: Session,
                           inventory: Inventory) -> tuple[float | None, str | None]:
    """Best available per-copy market value for a card, and where it came from.

    Priority, so hand-entered numbers win while automatic comps stay a fallback:
    manual market value -> latest sold/ask snapshot median -> last sold price ->
    lowest active ask. Returns (None, None) when nothing is known.
    """
    if inventory.manual_market_value is not None:
        return inventory.manual_market_value, "manual"
    snapshot = market_value(session, inventory.card_id)
    if snapshot is not None:
        return snapshot[0], snapshot[1]  # (value, 'sold'|'ask')
    if inventory.last_sold_price is not None:
        return inventory.last_sold_price, "last sold"
    if inventory.lowest_active_ask is not None:
        return inventory.lowest_active_ask, "ask"
    return None, None


@dataclass
class CardAssessment:
    """One card's full flip picture: what it cost, what it's worth, what you'd
    net after fees, and what to do about it. Reused by the Portfolio and Cards
    pages and the Card detail summary so every view shows the same numbers."""

    card: Card
    inventory: Inventory
    status: str
    quantity: int
    cost_basis: float                 # total across held copies
    cost_per_copy: float | None
    market_value: float | None        # per copy
    market_source: str | None
    net_if_sold: float | None         # net proceeds for all held copies
    profit: float | None
    roi_pct: float | None
    target_roi_pct: float
    needed_sale_price: float | None   # per copy, to hit target ROI
    max_buy: float | None             # per copy, for watch-list buy decisions
    recommendation: flip.Recommendation
    reason: str

    @property
    def is_underwater(self) -> bool:
        return self.profit is not None and self.profit < 0

    @property
    def missing_market(self) -> bool:
        return self.market_value is None

    @property
    def days_held(self) -> int | None:
        if self.inventory.acquired_date is None:
            return None
        return (date.today() - self.inventory.acquired_date).days


def assess_card(session: Session, inventory: Inventory) -> CardAssessment:
    """Build the full flip assessment for a single inventory row."""
    status = str(inventory.status)
    quantity = inventory.quantity or 0
    cost_basis = inventory.cost_basis or 0.0
    cost_per_copy = cost_basis / quantity if quantity else None

    market_value_per_copy, source = effective_market_value(session, inventory)
    target_roi = (inventory.target_roi_pct
                  if inventory.target_roi_pct is not None
                  else flip.DEFAULT_TARGET_ROI_PCT)

    # Per-card exit assumptions feed the fee model; all None-safe.
    exit_kwargs = {
        "buyer_shipping_paid": inventory.buyer_shipping_paid,
        "seller_shipping_cost": inventory.seller_shipping_cost,
        "supplies_cost": inventory.supplies_cost,
        "promoted_listing_pct": (inventory.promoted_listing_pct or 0.0) / 100,
    }

    net_if_sold = profit = roi_pct = needed = max_buy = None
    if market_value_per_copy is not None:
        # Max buy applies to any card with a market value (drives watch-list buys).
        max_buy = flip.max_buy_price(market_value_per_copy, target_roi, **exit_kwargs)
        # "If sold now" economics only make sense for cards you actually hold;
        # for watching/sold/passed they'd be phantom numbers, so leave them None.
        if status in ("owned", "listed") and quantity:
            net_per_copy = flip.net_proceeds(market_value_per_copy,
                                             **exit_kwargs).net_proceeds
            net_if_sold = round(net_per_copy * quantity, 2)
            profit, roi_pct = flip.profit_and_roi(net_if_sold, cost_basis)
            needed = flip.needed_sale_price(cost_per_copy, target_roi, **exit_kwargs)

    asking = inventory.lowest_active_ask
    recommendation, reason = flip.recommend(
        status=status,
        market_value=market_value_per_copy,
        cost_basis=cost_basis,
        profit_now=profit,
        roi_now=roi_pct,
        target_roi_pct=target_roi,
        asking_price=asking,
        max_buy=max_buy,
    )
    return CardAssessment(
        card=session.get(Card, inventory.card_id),
        inventory=inventory,
        status=status,
        quantity=quantity,
        cost_basis=cost_basis,
        cost_per_copy=cost_per_copy,
        market_value=market_value_per_copy,
        market_source=source,
        net_if_sold=net_if_sold,
        profit=profit,
        roi_pct=roi_pct,
        target_roi_pct=target_roi,
        needed_sale_price=needed,
        max_buy=max_buy,
        recommendation=recommendation,
        reason=reason,
    )


def assess_cards(session: Session, *, owner: str = "") -> list[CardAssessment]:
    """Assess every card the owner tracks, in id order. One row per inventory
    record (watching, owned, listed, sold, or passed)."""
    inventories = session.exec(
        select(Inventory).where(Inventory.owner == owner).order_by(Inventory.card_id)
    ).all()
    return [assess_card(session, inv) for inv in inventories]
