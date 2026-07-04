from datetime import date, timedelta

from sqlmodel import select

from cardtracker.models import (
    Card,
    Category,
    Comp,
    CompSourceName,
    Grader,
    PredictedDirection,
    Prediction,
    PriceType,
)
from cardtracker.predict import (
    backtest,
    find_cohort,
    predict_card,
    score_due_predictions,
)

AS_OF = date(2026, 7, 4)


def make_card(session, grader=Grader.PSA, grade="9", parallel="",
              player="Charizard", set_name="Base Set", year=1999):
    card = Card(category=Category.POKEMON, player_or_character=player,
                set_name=set_name, year=year, grader=grader, grade=grade,
                variation_or_parallel=parallel)
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def add_sold_series(session, card_id, start_price, daily_change, days_ago_range,
                    price_type=PriceType.SOLD):
    """Comps every 3 days across the range, price moving by daily_change per day."""
    source = CompSourceName.CSV if price_type == PriceType.SOLD else CompSourceName.BROWSE
    comps = []
    for days_ago in range(days_ago_range[0], days_ago_range[1], -3):
        age = days_ago_range[0] - days_ago
        comps.append(Comp(
            card_id=card_id,
            source=source,
            price_type=price_type,
            price=start_price + daily_change * age,
            sold_date_or_seen_date=AS_OF - timedelta(days=days_ago),
        ))
    session.add_all(comps)
    session.commit()


class TestCohort:
    def test_nearby_grade_included_distant_excluded(self, session):
        target = make_card(session, grade="9")
        near = make_card(session, grade="10")
        far = make_card(session, grade="6")
        cohort = find_cohort(session, target)
        ids = {c.id for c in cohort}
        assert near.id in ids
        assert far.id not in ids

    def test_raw_only_matches_raw(self, session):
        target = make_card(session, grader=Grader.RAW, grade="")
        raw = make_card(session, grader=Grader.RAW, grade="")
        graded = make_card(session, grade="9")
        ids = {c.id for c in find_cohort(session, target)}
        assert raw.id in ids
        assert graded.id not in ids

    def test_different_player_set_year_excluded(self, session):
        target = make_card(session)
        other_player = make_card(session, player="Blastoise")
        other_set = make_card(session, set_name="Jungle")
        other_year = make_card(session, year=2000)
        ids = {c.id for c in find_cohort(session, target)}
        assert not ids & {other_player.id, other_set.id, other_year.id}

    def test_parallel_same_or_base_included(self, session):
        target = make_card(session, parallel="Silver")
        same = make_card(session, parallel="Silver")
        base = make_card(session, parallel="")
        different = make_card(session, parallel="Gold")
        ids = {c.id for c in find_cohort(session, target)}
        assert same.id in ids
        assert base.id in ids
        assert different.id not in ids


class TestPredict:
    def test_rising_prices_predict_up(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.5, days_ago_range=(30, 0))
        result = predict_card(session, card.id, as_of=AS_OF, log=False)
        assert result.direction == PredictedDirection.UP
        assert 0 < result.confidence <= 1
        assert result.expected_move_pct > 3
        assert "Own trend" in result.rationale

    def test_falling_prices_predict_down(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=-0.5, days_ago_range=(30, 0))
        result = predict_card(session, card.id, as_of=AS_OF, log=False)
        assert result.direction == PredictedDirection.DOWN

    def test_stable_prices_predict_flat(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.0, days_ago_range=(30, 0))
        result = predict_card(session, card.id, as_of=AS_OF, log=False)
        assert result.direction == PredictedDirection.FLAT

    def test_cohort_momentum_moves_flat_target(self, session):
        target = make_card(session, grade="9")
        peer = make_card(session, grade="10")
        add_sold_series(session, target.id, 100, daily_change=0.0, days_ago_range=(30, 0))
        add_sold_series(session, peer.id, 100, daily_change=1.0, days_ago_range=(30, 0))
        result = predict_card(session, target.id, as_of=AS_OF, log=False)
        assert result.direction == PredictedDirection.UP
        assert f"card {peer.id}" in result.rationale
        assert "Cohort of 1" in result.rationale

    def test_ask_fallback_is_flagged(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.5,
                        days_ago_range=(30, 0), price_type=PriceType.ASK)
        result = predict_card(session, card.id, as_of=AS_OF, log=False)
        assert "ask prices, no sold data" in result.rationale

    def test_insufficient_data_flat_low_confidence(self, session):
        card = make_card(session)
        result = predict_card(session, card.id, as_of=AS_OF, log=False)
        assert result.direction == PredictedDirection.FLAT
        assert result.confidence <= 0.1
        assert "Insufficient data" in result.rationale

    def test_prediction_logged_and_rerun_replaces(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.5, days_ago_range=(30, 0))
        predict_card(session, card.id, as_of=AS_OF)
        predict_card(session, card.id, as_of=AS_OF)
        rows = session.exec(select(Prediction)).all()
        assert len(rows) == 1
        assert rows[0].predicted_direction == "up"
        assert rows[0].rationale
        assert rows[0].realized_direction is None


class TestBacktestAndScoring:
    def test_backtest_scores_steady_trend(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.6,
                        days_ago_range=(150, 0))
        report = backtest(session, horizon_days=30, step_days=7)
        assert report.scored > 5
        assert report.hit_rate == 1.0
        assert set(report.by_direction()) == {"up"}

    def test_backtest_does_not_log_predictions(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.6,
                        days_ago_range=(150, 0))
        backtest(session, horizon_days=30, step_days=7)
        assert session.exec(select(Prediction)).all() == []

    def test_backtest_empty_without_history(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.5, days_ago_range=(20, 0))
        report = backtest(session, horizon_days=30, step_days=7)
        assert report.scored == 0
        assert report.hit_rate is None

    def test_score_due_predictions(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.6,
                        days_ago_range=(90, 0))
        old_as_of = AS_OF - timedelta(days=40)
        predict_card(session, card.id, as_of=old_as_of, horizon_days=30)
        scored = score_due_predictions(session, today=AS_OF)
        assert scored == 1
        row = session.exec(select(Prediction)).one()
        assert row.realized_direction == "up"
        assert row.was_correct is True

    def test_score_skips_not_yet_due(self, session):
        card = make_card(session)
        add_sold_series(session, card.id, 100, daily_change=0.6,
                        days_ago_range=(90, 0))
        predict_card(session, card.id, as_of=AS_OF, horizon_days=30)
        scored = score_due_predictions(session, today=AS_OF)
        assert scored == 0
        row = session.exec(select(Prediction)).one()
        assert row.realized_direction is None
