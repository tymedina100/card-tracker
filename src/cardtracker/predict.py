"""Comparable-cohort prediction engine. Explainable by design, not a black box.

How a prediction is made:
1. Build a cohort of comparable cards: same player or character, same set,
   same year, grade within GRADE_TOLERANCE points (raw only matches raw),
   and the same parallel or a base version.
2. Measure momentum for the target and each cohort card as the 30 day trend
   slope divided by the 30 day median, in percent per day. Sold comps are
   preferred; ask prices are used only as a fallback and are flagged.
3. Combine the target's own momentum with the cohort median momentum
   (WEIGHT_OWN vs WEIGHT_COHORT), extrapolate over the horizon, and call
   up, down, or flat against UP_THRESHOLD_PCT.
4. Confidence blends the size of the expected move, how much data backs it,
   and how many signals agree on the direction.
5. Every prediction gets a written rationale naming the cards and numbers
   that drove it, and is logged to the predictions table.

Realized outcomes are always scored against sold medians, never asks.
"""

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func
from sqlmodel import Session, select

from cardtracker.models import (
    Card,
    Comp,
    Grader,
    PredictedDirection,
    Prediction,
    PriceType,
    describe_card,
)
from cardtracker.stats import comps_to_frame, compute_snapshot

UP_THRESHOLD_PCT = 3.0
WEIGHT_OWN = 0.6
WEIGHT_COHORT = 0.4
GRADE_TOLERANCE = 1.0


def _parse_grade(card: Card) -> float | None:
    if card.grader == Grader.RAW:
        return None
    try:
        return float(card.grade)
    except ValueError:
        return None


def _grades_comparable(a: Card, b: Card, tolerance: float = GRADE_TOLERANCE) -> bool:
    ga, gb = _parse_grade(a), _parse_grade(b)
    if ga is None and gb is None:
        return True
    if ga is None or gb is None:
        return False
    return abs(ga - gb) <= tolerance


def _parallel_similar(a: Card, b: Card) -> bool:
    pa = a.variation_or_parallel.strip().lower()
    pb = b.variation_or_parallel.strip().lower()
    return pa == pb or not pa or not pb


def find_cohort(session: Session, card: Card) -> list[Card]:
    """Comparable cards: same player or character, set, and year, with a nearby
    grade and the same or a base parallel. Scoped to the card's owner so one
    user's collection never leaks into another user's cohort."""
    candidates = session.exec(
        select(Card).where(
            Card.id != card.id,
            Card.owner == card.owner,
            func.lower(Card.player_or_character) == card.player_or_character.lower(),
            func.lower(Card.set_name) == card.set_name.lower(),
            Card.year == card.year,
        )
    ).all()
    return [c for c in candidates
            if _grades_comparable(card, c) and _parallel_similar(card, c)]


@dataclass
class MomentumSignal:
    """One card's recent momentum, used as an input to a prediction."""

    card_id: int
    label: str
    price_type: str
    pct_per_day: float
    count_30d: int
    median_30d: float
    velocity_30d: float


@dataclass
class PredictionResult:
    card_id: int
    as_of: date
    direction: PredictedDirection
    confidence: float
    expected_move_pct: float
    rationale: str
    horizon_days: int


def _card_momentum(session: Session, card: Card, as_of: date) -> MomentumSignal | None:
    comps = session.exec(select(Comp).where(Comp.card_id == card.id)).all()
    if not comps:
        return None
    df = comps_to_frame(comps)
    for price_type in (PriceType.SOLD, PriceType.ASK):
        snapshot = compute_snapshot(card.id, df, price_type, as_of)
        if (snapshot is not None and snapshot.median_30d
                and snapshot.trend_slope_30d is not None):
            return MomentumSignal(
                card_id=card.id,
                label=describe_card(card),
                price_type=str(price_type),
                pct_per_day=snapshot.trend_slope_30d / snapshot.median_30d * 100,
                count_30d=snapshot.sale_count_30d,
                median_30d=snapshot.median_30d,
                velocity_30d=snapshot.velocity_30d,
            )
    return None


def _direction_for_move(move_pct: float) -> PredictedDirection:
    if move_pct >= UP_THRESHOLD_PCT:
        return PredictedDirection.UP
    if move_pct <= -UP_THRESHOLD_PCT:
        return PredictedDirection.DOWN
    return PredictedDirection.FLAT


def _signal_text(s: MomentumSignal) -> str:
    flag = " [ask prices, no sold data]" if s.price_type == "ask" else ""
    return (f"card {s.card_id} ({s.label}): {s.pct_per_day:+.2f}%/day from "
            f"{s.count_30d} {s.price_type} comps in 30d, median {s.median_30d:.2f}{flag}")


def predict_card(session: Session, card_id: int, as_of: date | None = None,
                 horizon_days: int = 30, log: bool = True) -> PredictionResult:
    """Predict direction over the horizon for one card. Logs to the predictions
    table unless log is False. Rerunning for the same card, date, and horizon
    replaces the earlier logged row."""
    card = session.get(Card, card_id)
    if card is None:
        raise ValueError(f"No card with id {card_id}")
    as_of = as_of or date.today()

    own = _card_momentum(session, card, as_of)
    cohort_cards = find_cohort(session, card)
    cohort_signals = [signal for c in cohort_cards
                      if (signal := _card_momentum(session, c, as_of)) is not None]

    if own is None and not cohort_signals:
        result = PredictionResult(
            card_id=card_id,
            as_of=as_of,
            direction=PredictedDirection.FLAT,
            confidence=0.05,
            expected_move_pct=0.0,
            rationale=("Insufficient data: no comps within 90 days for this card "
                       "or any comparable card."),
            horizon_days=horizon_days,
        )
        if log:
            _log_prediction(session, result, owner=card.owner)
        return result

    signals = ([own] if own else []) + cohort_signals
    cohort_median = (statistics.median(s.pct_per_day for s in cohort_signals)
                     if cohort_signals else None)
    if own is not None and cohort_median is not None:
        combined = WEIGHT_OWN * own.pct_per_day + WEIGHT_COHORT * cohort_median
    elif own is not None:
        combined = own.pct_per_day
    else:
        combined = cohort_median

    expected_move = combined * horizon_days
    direction = _direction_for_move(expected_move)

    if direction == PredictedDirection.FLAT:
        agreeing = [s for s in signals
                    if abs(s.pct_per_day * horizon_days) < UP_THRESHOLD_PCT]
    else:
        agreeing = [s for s in signals
                    if (s.pct_per_day > 0) == (combined > 0) and s.pct_per_day != 0]
    agreement = len(agreeing) / len(signals)

    if direction == PredictedDirection.FLAT:
        strength = 1 - min(1.0, abs(expected_move) / UP_THRESHOLD_PCT)
    else:
        strength = min(1.0, abs(expected_move) / 10.0)
    data_factor = min(1.0, sum(s.count_30d for s in signals) / 10.0)
    confidence = round(min(1.0, 0.2 + 0.8 * strength * data_factor * agreement), 3)

    lines = [f"Expected {horizon_days}d move {expected_move:+.1f}% "
             f"(threshold {UP_THRESHOLD_PCT:.0f}%)."]
    if own is not None:
        lines.append(f"Own trend: {_signal_text(own)}, "
                     f"velocity {own.velocity_30d:.1f} per week.")
    else:
        lines.append("No usable trend for this card itself; cohort signal only.")
    if cohort_signals:
        cohort_text = "; ".join(_signal_text(s) for s in cohort_signals)
        lines.append(f"Cohort of {len(cohort_signals)}: {cohort_text}. "
                     f"Cohort median momentum {cohort_median:+.2f}%/day.")
        if own is not None:
            lines.append(f"Weights: {WEIGHT_OWN:.0%} own trend, "
                         f"{WEIGHT_COHORT:.0%} cohort median.")
    else:
        lines.append("No comparable cards found (same player, set, year, "
                     "nearby grade), so the card's own trend stands alone.")
    lines.append(f"{len(agreeing)} of {len(signals)} signal(s) agree with "
                 f"the {direction} call.")

    result = PredictionResult(
        card_id=card_id,
        as_of=as_of,
        direction=direction,
        confidence=confidence,
        expected_move_pct=round(expected_move, 2),
        rationale=" ".join(lines),
        horizon_days=horizon_days,
    )
    if log:
        _log_prediction(session, result, owner=card.owner)
    return result


def _log_prediction(session: Session, result: PredictionResult, *,
                    owner: str) -> Prediction:
    stale = session.exec(
        select(Prediction)
        .where(Prediction.owner == owner)
        .where(Prediction.card_id == result.card_id)
        .where(Prediction.as_of_date == result.as_of)
        .where(Prediction.horizon_days == result.horizon_days)
    ).all()
    for row in stale:
        session.delete(row)
    prediction = Prediction(
        card_id=result.card_id,
        owner=owner,
        as_of_date=result.as_of,
        predicted_direction=result.direction,
        confidence=result.confidence,
        rationale=result.rationale,
        horizon_days=result.horizon_days,
    )
    session.add(prediction)
    session.commit()
    session.refresh(prediction)
    return prediction


def realized_direction_for(card_id: int, df: pd.DataFrame, as_of: date,
                           horizon_days: int) -> tuple[PredictedDirection, float] | None:
    """What actually happened: sold median at as_of vs sold median at the horizon.
    Scored against sold comps only, never asks. None when either side lacks data."""
    base = compute_snapshot(card_id, df, PriceType.SOLD, as_of)
    future = compute_snapshot(card_id, df, PriceType.SOLD,
                              as_of + timedelta(days=horizon_days))
    if base is None or not base.median_30d or future is None or not future.median_30d:
        return None
    move_pct = (future.median_30d - base.median_30d) / base.median_30d * 100
    return _direction_for_move(move_pct), move_pct


@dataclass
class BacktestRow:
    card_id: int
    as_of: date
    predicted: PredictedDirection
    confidence: float
    realized: PredictedDirection
    realized_move_pct: float

    @property
    def correct(self) -> bool:
        return self.predicted == self.realized


@dataclass
class BacktestReport:
    horizon_days: int
    step_days: int
    rows: list[BacktestRow]

    @property
    def scored(self) -> int:
        return len(self.rows)

    @property
    def hits(self) -> int:
        return sum(1 for r in self.rows if r.correct)

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.scored if self.rows else None

    def by_direction(self) -> dict[str, tuple[int, int]]:
        """Predicted direction to (hits, total)."""
        result: dict[str, tuple[int, int]] = {}
        for row in self.rows:
            key = str(row.predicted)
            hits, total = result.get(key, (0, 0))
            result[key] = (hits + int(row.correct), total + 1)
        return result


def backtest(session: Session, horizon_days: int = 30, step_days: int = 7,
             min_history_days: int = 30, card_id: int | None = None,
             owner: str | None = None) -> BacktestReport:
    """Replay history: predict at past dates using only comps up to each date,
    then score against the sold median that followed. Keeps the model honest.
    Backtest predictions are not written to the predictions table. When owner is
    given, only that owner's cards are replayed."""
    card_query = select(Card)
    if card_id is not None:
        card_query = card_query.where(Card.id == card_id)
    if owner is not None:
        card_query = card_query.where(Card.owner == owner)
    cards = session.exec(card_query).all()
    rows: list[BacktestRow] = []
    for card in cards:
        comps = session.exec(select(Comp).where(Comp.card_id == card.id)).all()
        if not comps:
            continue
        df = comps_to_frame(comps)
        sold_dates = df[df["price_type"] == "sold"]["date"]
        if sold_dates.empty:
            continue
        as_of = sold_dates.min() + timedelta(days=min_history_days)
        end = sold_dates.max() - timedelta(days=horizon_days)
        while as_of <= end:
            realized = realized_direction_for(card.id, df, as_of, horizon_days)
            if realized is not None:
                prediction = predict_card(session, card.id, as_of=as_of,
                                          horizon_days=horizon_days, log=False)
                rows.append(BacktestRow(
                    card_id=card.id,
                    as_of=as_of,
                    predicted=prediction.direction,
                    confidence=prediction.confidence,
                    realized=realized[0],
                    realized_move_pct=round(realized[1], 2),
                ))
            as_of += timedelta(days=step_days)
    return BacktestReport(horizon_days=horizon_days, step_days=step_days, rows=rows)


def score_due_predictions(session: Session, today: date | None = None,
                          owner: str | None = None) -> int:
    """Fill realized_direction and was_correct on logged predictions whose
    horizon has elapsed. Returns how many rows were scored. When owner is given,
    only that owner's predictions are scored."""
    today = today or date.today()
    query = select(Prediction).where(Prediction.realized_direction == None)  # noqa: E711
    if owner is not None:
        query = query.where(Prediction.owner == owner)
    pending = session.exec(query).all()
    frames: dict[int, pd.DataFrame] = {}
    scored = 0
    for prediction in pending:
        due = prediction.as_of_date + timedelta(days=prediction.horizon_days)
        if due > today:
            continue
        if prediction.card_id not in frames:
            comps = session.exec(
                select(Comp).where(Comp.card_id == prediction.card_id)
            ).all()
            frames[prediction.card_id] = comps_to_frame(comps) if comps else None
        df = frames[prediction.card_id]
        if df is None:
            continue
        realized = realized_direction_for(prediction.card_id, df,
                                          prediction.as_of_date,
                                          prediction.horizon_days)
        if realized is None:
            continue
        prediction.realized_direction = realized[0]
        prediction.was_correct = str(prediction.predicted_direction) == str(realized[0])
        session.add(prediction)
        scored += 1
    session.commit()
    return scored
