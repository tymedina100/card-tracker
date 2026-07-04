from datetime import date, timedelta

from sqlmodel import select

from cardtracker.models import Comp, CompSourceName, PriceSnapshot, PriceType
from cardtracker.stats import (
    comps_to_frame,
    compute_snapshot,
    latest_snapshots,
    refresh_snapshots,
)

AS_OF = date(2026, 7, 4)


def make_comp(card_id: int, days_ago: int, price: float, shipping: float = 0.0,
              price_type: PriceType = PriceType.SOLD,
              source: CompSourceName = CompSourceName.CSV) -> Comp:
    return Comp(
        card_id=card_id,
        source=source,
        price_type=price_type,
        price=price,
        shipping=shipping,
        sold_date_or_seen_date=AS_OF - timedelta(days=days_ago),
    )


def add_comps(session, comps):
    session.add_all(comps)
    session.commit()


def frame_for(session, card_id):
    comps = session.exec(select(Comp).where(Comp.card_id == card_id)).all()
    return comps_to_frame(comps)


def test_medians_and_windows(session, sample_card):
    cid = sample_card.id
    add_comps(session, [
        make_comp(cid, 1, 100),
        make_comp(cid, 5, 110),
        make_comp(cid, 20, 200),
        make_comp(cid, 60, 300),
    ])
    snap = compute_snapshot(cid, frame_for(session, cid), PriceType.SOLD, AS_OF)
    assert snap.median_7d == 105.0
    assert snap.median_30d == 110.0
    assert snap.median_90d == 155.0
    assert snap.mean_30d == (100 + 110 + 200) / 3
    assert snap.sale_count_30d == 3
    assert snap.sale_count_90d == 4
    assert snap.low_30d == 100.0
    assert snap.high_30d == 200.0
    assert snap.spread_30d == 100.0
    assert snap.velocity_30d == 3 * 7 / 30


def test_window_boundary_inclusive_exclusive(session, sample_card):
    cid = sample_card.id
    add_comps(session, [
        make_comp(cid, 30, 100),  # exactly 30 days ago, outside the 30d window
        make_comp(cid, 29, 200),  # inside
    ])
    snap = compute_snapshot(cid, frame_for(session, cid), PriceType.SOLD, AS_OF)
    assert snap.sale_count_30d == 1
    assert snap.median_30d == 200.0
    assert snap.sale_count_90d == 2


def test_delivered_price_includes_shipping(session, sample_card):
    cid = sample_card.id
    add_comps(session, [make_comp(cid, 1, 100, shipping=9.5)])
    snap = compute_snapshot(cid, frame_for(session, cid), PriceType.SOLD, AS_OF)
    assert snap.median_30d == 109.5


def test_trend_slope_sign(session, sample_card):
    cid = sample_card.id
    add_comps(session, [
        make_comp(cid, 20, 100),
        make_comp(cid, 10, 150),
        make_comp(cid, 1, 200),
    ])
    snap = compute_snapshot(cid, frame_for(session, cid), PriceType.SOLD, AS_OF)
    assert snap.trend_slope_30d > 0
    assert snap.trend_slope_90d > 0


def test_slope_needs_two_distinct_dates(session, sample_card):
    cid = sample_card.id
    add_comps(session, [make_comp(cid, 3, 100), make_comp(cid, 3, 120)])
    snap = compute_snapshot(cid, frame_for(session, cid), PriceType.SOLD, AS_OF)
    assert snap.trend_slope_30d is None
    assert snap.volatility_30d is not None  # two prices still give a std dev


def test_no_comps_in_90d_gives_no_snapshot(session, sample_card):
    cid = sample_card.id
    add_comps(session, [make_comp(cid, 91, 100)])
    snap = compute_snapshot(cid, frame_for(session, cid), PriceType.SOLD, AS_OF)
    assert snap is None


def test_ask_and_sold_never_mixed(session, sample_card):
    cid = sample_card.id
    add_comps(session, [
        make_comp(cid, 1, 100, price_type=PriceType.SOLD),
        make_comp(cid, 1, 999, price_type=PriceType.ASK, source=CompSourceName.BROWSE),
    ])
    written = refresh_snapshots(session, as_of=AS_OF)
    assert len(written) == 2
    by_type = {str(s.price_type): s for s in written}
    assert by_type["sold"].median_30d == 100.0
    assert by_type["ask"].median_30d == 999.0


def test_refresh_replaces_same_day_rows(session, sample_card):
    cid = sample_card.id
    add_comps(session, [make_comp(cid, 1, 100)])
    refresh_snapshots(session, as_of=AS_OF)
    add_comps(session, [make_comp(cid, 1, 200)])
    refresh_snapshots(session, as_of=AS_OF)
    rows = session.exec(select(PriceSnapshot)).all()
    assert len(rows) == 1
    assert rows[0].median_30d == 150.0


def test_refresh_single_card_only(session, sample_card):
    from cardtracker.models import Card, Category

    other = Card(category=Category.SPORTS, player_or_character="Luka Doncic",
                 set_name="Prizm", year=2018)
    session.add(other)
    session.commit()
    session.refresh(other)
    add_comps(session, [make_comp(sample_card.id, 1, 100), make_comp(other.id, 1, 50)])
    written = refresh_snapshots(session, as_of=AS_OF, card_id=other.id)
    assert len(written) == 1
    assert written[0].card_id == other.id


def test_latest_snapshots_picks_newest(session, sample_card):
    cid = sample_card.id
    add_comps(session, [make_comp(cid, 1, 100)])
    refresh_snapshots(session, as_of=AS_OF - timedelta(days=1))
    refresh_snapshots(session, as_of=AS_OF)
    latest = latest_snapshots(session, cid)
    assert set(latest) == {"sold"}
    assert latest["sold"].as_of_date == AS_OF
