"""CompSource interface and shared persistence helper."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session

from cardtracker.models import Comp, CompSourceName, PriceType


@dataclass
class CompRecord:
    """A single price observation produced by a source, not yet persisted."""

    price: float
    observed_date: date
    shipping: float = 0.0
    currency: str = "USD"
    listing_url: str = ""
    title_raw: str = ""
    condition_raw: str = ""
    extra: dict = field(default_factory=dict)


class CompSource(ABC):
    """One channel of comp data. Every source declares its name and price type."""

    source_name: CompSourceName
    price_type: PriceType

    @abstractmethod
    def fetch_comps(self, query: str, limit: int = 50) -> list[CompRecord]:
        """Return comp records for a search query."""


def save_comps(session: Session, card_id: int, source: CompSource,
               records: list[CompRecord]) -> list[Comp]:
    """Persist records, always stamping source and price_type so analysis never mixes them."""
    comps = [
        Comp(
            card_id=card_id,
            source=source.source_name,
            price_type=source.price_type,
            price=r.price,
            shipping=r.shipping,
            currency=r.currency,
            sold_date_or_seen_date=r.observed_date,
            listing_url=r.listing_url,
            title_raw=r.title_raw,
            condition_raw=r.condition_raw,
        )
        for r in records
    ]
    session.add_all(comps)
    session.commit()
    for comp in comps:
        session.refresh(comp)
    return comps
