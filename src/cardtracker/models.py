"""SQLModel table definitions for all cardtracker entities."""

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def enum_column(*, index: bool = False, nullable: bool = False) -> Column:
    """Store StrEnum fields as plain text so the database holds the enum value,
    for example 'csv' and 'sold', never the Python member name like CSV."""
    return Column(String, index=index, nullable=nullable)


class Category(StrEnum):
    SPORTS = "sports"
    POKEMON = "pokemon"


class Grader(StrEnum):
    PSA = "PSA"
    BGS = "BGS"
    SGC = "SGC"
    CGC = "CGC"
    RAW = "raw"


class CompSourceName(StrEnum):
    BROWSE = "browse"
    INSIGHTS = "insights"
    CSV = "csv"


class PriceType(StrEnum):
    ASK = "ask"
    SOLD = "sold"


class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"


class InventoryStatus(StrEnum):
    OWNED = "owned"
    LISTED = "listed"
    SOLD = "sold"
    WATCHING = "watching"
    PASSED = "passed"


class PredictedDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class Card(SQLModel, table=True):
    """A specific gradable card identity. A PSA 10 and a PSA 9 are two rows."""

    __tablename__ = "cards"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    owner: str = Field(default="", index=True)
    category: Category = Field(sa_column=enum_column())
    player_or_character: str = Field(index=True)
    set_name: str = Field(index=True)
    year: int
    card_number: str = ""
    variation_or_parallel: str = ""
    grader: Grader = Field(default=Grader.RAW, sa_column=enum_column())
    grade: str = ""
    cert_number: str | None = None
    notes: str = ""


def describe_card(card: "Card") -> str:
    """Short human-readable label, e.g. '1999 Base Set Charizard #4 PSA 9'."""
    grade_part = f"{card.grader} {card.grade}".strip() if card.grader != Grader.RAW else "raw"
    bits = [str(card.year), card.set_name, card.player_or_character]
    if card.card_number:
        bits.append(f"#{card.card_number}")
    if card.variation_or_parallel:
        bits.append(card.variation_or_parallel)
    bits.append(grade_part)
    return " ".join(bits)


class Comp(SQLModel, table=True):
    """One price observation, either an active ask or a confirmed sale."""

    __tablename__ = "comps"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="cards.id", index=True)
    source: CompSourceName = Field(sa_column=enum_column())
    price_type: PriceType = Field(sa_column=enum_column(index=True))
    price: float
    shipping: float = 0.0
    currency: str = "USD"
    sold_date_or_seen_date: date = Field(index=True)
    listing_url: str = ""
    title_raw: str = ""
    condition_raw: str = ""
    ingested_at: datetime = Field(default_factory=utcnow)


class PriceSnapshot(SQLModel, table=True):
    """Rolling aggregates per card per refresh run. Ask and sold stats are separate rows."""

    __tablename__ = "price_snapshots"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="cards.id", index=True)
    as_of_date: date = Field(index=True)
    price_type: PriceType = Field(sa_column=enum_column())
    median_7d: float | None = None
    median_30d: float | None = None
    median_90d: float | None = None
    mean_30d: float | None = None
    sale_count_30d: int = 0
    sale_count_90d: int = 0
    low_30d: float | None = None
    high_30d: float | None = None
    spread_30d: float | None = None
    volatility_30d: float | None = None
    velocity_30d: float | None = None
    trend_slope_30d: float | None = None
    trend_slope_90d: float | None = None


class Transaction(SQLModel, table=True):
    """My own buys and sells."""

    __tablename__ = "transactions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    owner: str = Field(default="", index=True)
    card_id: int = Field(foreign_key="cards.id", index=True)
    type: TransactionType = Field(sa_column=enum_column())
    date: date
    price: float
    fees: float = 0.0
    shipping_cost: float = 0.0
    taxes: float = 0.0
    grading_cost: float = 0.0
    platform: str = ""
    notes: str = ""

    @property
    def total_cost(self) -> float:
        """Full cost of a buy: price plus fees, shipping, taxes, and grading."""
        return self.price + self.fees + self.shipping_cost + self.taxes + self.grading_cost


class Inventory(SQLModel, table=True):
    """Current holding status per card."""

    __tablename__ = "inventory"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    owner: str = Field(default="", index=True)
    card_id: int = Field(foreign_key="cards.id", index=True)
    status: InventoryStatus = Field(default=InventoryStatus.WATCHING, sa_column=enum_column())
    quantity: int = 1
    acquired_date: date | None = None
    cost_basis: float | None = None
    listed_price: float | None = None
    target_sell_price: float | None = None
    min_accept_price: float | None = None
    # Manual market inputs. Until automatic comps are reliable, these hand-entered
    # values drive the market-value, recommendation, and deal math. When automatic
    # comps come online they can populate the same fields (see effective_market_value).
    manual_market_value: float | None = None  # current market value, per copy
    last_sold_price: float | None = None      # most recent known sold price
    lowest_active_ask: float | None = None     # cheapest active listing seen
    target_roi_pct: float | None = None        # per-card ROI goal for sell/list calls
    date_listed: date | None = None            # when this card was listed for sale
    # Per-card exit assumptions, fed into the eBay net-proceeds formula. All default
    # to zero/none when unset so blank cards never break the calculations.
    supplies_cost: float | None = None
    buyer_shipping_paid: float | None = None
    seller_shipping_cost: float | None = None
    promoted_listing_pct: float | None = None
    # Scan feature: a price captured for a card (typed now, later from a scanner).
    # It is graded against market whenever a market value exists, so a scan saved
    # before comps arrive gets graded automatically once they do.
    scanned_price: float | None = None
    scanned_at: date | None = None


class Prediction(SQLModel, table=True):
    """Logged forecasts, scored later against realized direction."""

    __tablename__ = "predictions"
    __table_args__ = {"extend_existing": True}

    id: int | None = Field(default=None, primary_key=True)
    owner: str = Field(default="", index=True)
    card_id: int = Field(foreign_key="cards.id", index=True)
    as_of_date: date
    predicted_direction: PredictedDirection = Field(sa_column=enum_column())
    confidence: float
    rationale: str = ""
    horizon_days: int = 30
    realized_direction: PredictedDirection | None = Field(
        default=None, sa_column=enum_column(nullable=True)
    )
    was_correct: bool | None = None
