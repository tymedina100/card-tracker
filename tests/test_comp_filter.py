"""Tests for filtering Browse API asks down to the exact card."""

from datetime import date

from cardtracker.models import Card, Category, Grader
from cardtracker.sources import filter_comps_for_card
from cardtracker.sources.base import CompRecord


def rec(title: str) -> CompRecord:
    return CompRecord(price=100.0, observed_date=date.today(), title_raw=title)


def titles(records: list[CompRecord]) -> list[str]:
    return [r.title_raw for r in records]


def base_psa9() -> Card:
    """The base PSA 9 Cooper Flagg from the reported bug."""
    return Card(
        category=Category.SPORTS,
        player_or_character="Cooper Flagg",
        set_name="Bowman Chrome U",
        year=2024,
        card_number="16",
        variation_or_parallel="",
        grader=Grader.PSA,
        grade="9",
    )


def test_keeps_the_matching_base_card():
    kept, dropped = filter_comps_for_card(
        [rec("2024 Bowman Chrome U Cooper Flagg #16 Base PSA 9")], base_psa9()
    )
    assert len(kept) == 1
    assert dropped == []


def test_drops_autograph_version():
    kept, dropped = filter_comps_for_card(
        [rec("COOPER FLAGG AUTOGRAPHED 2024 BOWMAN CHROME U AUTO ROOKIE #16 PSA MINT 9")],
        base_psa9(),
    )
    assert kept == []
    assert len(dropped) == 1


def test_drops_serial_numbered_refractor_and_wrong_grade():
    kept, dropped = filter_comps_for_card(
        [rec("2024 BOWMAN U BEST COOPER FLAGG #16 GOLD REFRACTOR /50 PSA 10 POP 9")],
        base_psa9(),
    )
    assert kept == []
    assert len(dropped) == 1


def test_drops_same_card_wrong_grade():
    kept, _ = filter_comps_for_card(
        [rec("2024 Bowman Chrome U Cooper Flagg #16 PSA 10")], base_psa9()
    )
    assert kept == []


def test_drops_different_card_number():
    kept, _ = filter_comps_for_card(
        [rec("2024 Bowman Chrome U Cooper Flagg #25 PSA 9")], base_psa9()
    )
    assert kept == []


def test_keeps_listing_with_no_number_cited():
    kept, _ = filter_comps_for_card(
        [rec("2024 Bowman Chrome U Cooper Flagg Base Rookie PSA 9")], base_psa9()
    )
    assert len(kept) == 1


def test_mixed_batch_splits_correctly():
    records = [
        rec("2024 Bowman Chrome U Cooper Flagg #16 Base PSA 9"),
        rec("Cooper Flagg #16 Auto PSA 9"),
        rec("Cooper Flagg #16 Gold Refractor /50 PSA 9"),
        rec("Cooper Flagg #16 PSA 10"),
    ]
    kept, dropped = filter_comps_for_card(records, base_psa9())
    assert titles(kept) == ["2024 Bowman Chrome U Cooper Flagg #16 Base PSA 9"]
    assert len(dropped) == 3


def test_non_strict_keeps_everything():
    records = [
        rec("Cooper Flagg #16 Base PSA 9"),
        rec("Cooper Flagg #16 Auto PSA 10 Gold Refractor /50"),
    ]
    kept, dropped = filter_comps_for_card(records, base_psa9(), strict=False)
    assert len(kept) == 2
    assert dropped == []


def test_empty_title_is_kept():
    kept, _ = filter_comps_for_card([rec("")], base_psa9())
    assert len(kept) == 1


def test_raw_card_drops_graded_slabs():
    raw = Card(
        category=Category.POKEMON,
        player_or_character="Charizard",
        set_name="Base Set",
        year=1999,
        card_number="4",
        grader=Grader.RAW,
        grade="",
    )
    records = [
        rec("1999 Pokemon Base Set Charizard #4 Holo"),
        rec("1999 Pokemon Base Set Charizard #4 PSA 9"),
    ]
    kept, dropped = filter_comps_for_card(records, raw)
    assert titles(kept) == ["1999 Pokemon Base Set Charizard #4 Holo"]
    assert len(dropped) == 1


def test_parallel_card_requires_its_keywords():
    card = Card(
        category=Category.SPORTS,
        player_or_character="Cooper Flagg",
        set_name="Bowman Chrome U",
        year=2024,
        card_number="16",
        variation_or_parallel="Gold Refractor",
        grader=Grader.PSA,
        grade="10",
    )
    records = [
        rec("Cooper Flagg #16 Gold Refractor /50 PSA 10"),
        rec("Cooper Flagg #16 Base PSA 10"),
    ]
    kept, dropped = filter_comps_for_card(records, card)
    assert titles(kept) == ["Cooper Flagg #16 Gold Refractor /50 PSA 10"]
    assert len(dropped) == 1


def test_grade_filter_on_db_loaded_card(session):
    """A card loaded from the DB has grader as a plain str, not a Grader enum.

    Regression: the filter must not assume card.grader is an enum member.
    """
    card = base_psa9()
    session.add(card)
    session.commit()
    reloaded = session.get(Card, card.id)
    assert isinstance(reloaded.grader, str)  # DB round-trip yields a str
    kept, dropped = filter_comps_for_card(
        [
            rec("2024 Bowman Chrome U Cooper Flagg #16 Base PSA 9"),
            rec("2024 Bowman Chrome U Cooper Flagg #16 PSA 10"),
        ],
        reloaded,
    )
    assert len(kept) == 1
    assert len(dropped) == 1


def authentic_card() -> Card:
    return Card(
        category=Category.SPORTS,
        player_or_character="Cooper Flagg",
        set_name="Bowman Chrome U",
        year=2024,
        card_number="16",
        grader=Grader.PSA,
        grade="Authentic",
    )


def test_authentic_grade_keeps_authentic_listings():
    records = [
        rec("2024 Bowman Chrome U Cooper Flagg #16 PSA Authentic"),
        rec("2024 Bowman Chrome U Cooper Flagg #16 PSA AUTH"),
        rec("2024 Bowman Chrome U Cooper Flagg #16 PSA 9"),
    ]
    kept, dropped = filter_comps_for_card(records, authentic_card())
    assert titles(kept) == [
        "2024 Bowman Chrome U Cooper Flagg #16 PSA Authentic",
        "2024 Bowman Chrome U Cooper Flagg #16 PSA AUTH",
    ]
    assert len(dropped) == 1  # the numeric PSA 9 is a different grade


def test_numeric_card_drops_authentic_listing():
    kept, _ = filter_comps_for_card(
        [rec("2024 Bowman Chrome U Cooper Flagg #16 PSA Authentic")], base_psa9()
    )
    assert kept == []


def test_bgs_half_grade_matches():
    card = Card(
        category=Category.SPORTS,
        player_or_character="Cooper Flagg",
        set_name="Bowman Chrome U",
        year=2024,
        card_number="16",
        grader=Grader.BGS,
        grade="9.5",
    )
    kept, _ = filter_comps_for_card(
        [rec("Cooper Flagg #16 BGS 9.5 Gem Mint")], card
    )
    assert len(kept) == 1
