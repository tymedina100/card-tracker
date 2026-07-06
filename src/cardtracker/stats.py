"""Rolling market statistics computed from comps.

Conventions:
- All stats use the delivered price, item price plus shipping, since that is
  the real cost to the buyer.
- Ask stats and sold stats are never mixed. Each snapshot row carries the
  price_type it was computed from.
- A window of N days covers the as_of date and the previous N-1 days.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, select

from cardtracker.models import Card, Comp, PriceSnapshot, PriceType


def comps_to_frame(comps: list[Comp]) -> pd.DataFrame:
    """Comp rows to a DataFrame with a delivered-price column."""
    return pd.DataFrame(
        {
            "date": [c.sold_date_or_seen_date for c in comps],
            "price_type": [str(c.price_type) for c in comps],
            "delivered": [c.price + c.shipping for c in comps],
        }
    )


def _window(df: pd.DataFrame, as_of: date, days: int) -> pd.DataFrame:
    cutoff = as_of - timedelta(days=days)
    return df[(df["date"] > cutoff) & (df["date"] <= as_of)]


def _median(window: pd.DataFrame) -> float | None:
    return float(window["delivered"].median()) if len(window) else None


def _slope(window: pd.DataFrame, as_of: date) -> float | None:
    """Linear trend of delivered price in dollars per day. Needs two distinct dates."""
    if window["date"].nunique() < 2:
        return None
    x = np.array([(d - as_of).days for d in window["date"]], dtype=float)
    y = window["delivered"].to_numpy(dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def compute_snapshot(card_id: int, df: pd.DataFrame, price_type: PriceType,
                     as_of: date) -> PriceSnapshot | None:
    """Build one snapshot for one card and one price type. Returns None when the
    card has no comps of this type inside the 90 day window."""
    df = df[df["price_type"] == str(price_type)]
    w90 = _window(df, as_of, 90)
    if w90.empty:
        return None
    w30 = _window(df, as_of, 30)
    w7 = _window(df, as_of, 7)
    return PriceSnapshot(
        card_id=card_id,
        as_of_date=as_of,
        price_type=price_type,
        median_7d=_median(w7),
        median_30d=_median(w30),
        median_90d=_median(w90),
        mean_30d=float(w30["delivered"].mean()) if len(w30) else None,
        sale_count_30d=len(w30),
        sale_count_90d=len(w90),
        low_30d=float(w30["delivered"].min()) if len(w30) else None,
        high_30d=float(w30["delivered"].max()) if len(w30) else None,
        spread_30d=float(w30["delivered"].max() - w30["delivered"].min())
        if len(w30) else None,
        volatility_30d=float(w30["delivered"].std()) if len(w30) >= 2 else None,
        velocity_30d=len(w30) * 7 / 30,
        trend_slope_30d=_slope(w30, as_of),
        trend_slope_90d=_slope(w90, as_of),
    )


def refresh_snapshots(session: Session, as_of: date | None = None,
                      card_id: int | None = None,
                      owner: str | None = None) -> list[PriceSnapshot]:
    """Compute and store snapshots for every card, one row per price type that
    has comps. Rerunning for the same date replaces that date's rows. When owner
    is given, only that owner's cards are refreshed."""
    as_of = as_of or date.today()
    card_query = select(Card)
    if card_id is not None:
        card_query = card_query.where(Card.id == card_id)
    if owner is not None:
        card_query = card_query.where(Card.owner == owner)
    cards = session.exec(card_query).all()
    written: list[PriceSnapshot] = []
    for card in cards:
        comps = session.exec(select(Comp).where(Comp.card_id == card.id)).all()
        if not comps:
            continue
        df = comps_to_frame(comps)
        for price_type in (PriceType.ASK, PriceType.SOLD):
            snapshot = compute_snapshot(card.id, df, price_type, as_of)
            if snapshot is None:
                continue
            stale = session.exec(
                select(PriceSnapshot)
                .where(PriceSnapshot.card_id == card.id)
                .where(PriceSnapshot.as_of_date == as_of)
                .where(PriceSnapshot.price_type == price_type)
            ).all()
            for row in stale:
                session.delete(row)
            session.add(snapshot)
            written.append(snapshot)
    session.commit()
    for snapshot in written:
        session.refresh(snapshot)
    return written


def latest_snapshots(session: Session, card_id: int) -> dict[str, PriceSnapshot]:
    """Most recent snapshot per price type for a card, keyed 'ask' and 'sold'."""
    result: dict[str, PriceSnapshot] = {}
    for price_type in (PriceType.ASK, PriceType.SOLD):
        snapshot = session.exec(
            select(PriceSnapshot)
            .where(PriceSnapshot.card_id == card_id)
            .where(PriceSnapshot.price_type == price_type)
            .order_by(PriceSnapshot.as_of_date.desc())
            .limit(1)
        ).first()
        if snapshot is not None:
            result[str(price_type)] = snapshot
    return result
