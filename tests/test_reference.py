from cardtracker import reference
from cardtracker.models import Card, Category, Grader
from cardtracker.reference import players_for, sets_for
from cardtracker.webui.shared import distinct_values, merge_options


def test_seed_lists_are_non_empty():
    for name in ("POKEMON_SETS", "SPORTS_SETS", "PARALLELS",
                 "POPULAR_PLAYERS", "POPULAR_CHARACTERS", "GRADES"):
        assert getattr(reference, name), f"{name} should not be empty"


def test_sets_for_branches_by_category():
    assert sets_for(Category.POKEMON) is reference.POKEMON_SETS
    assert sets_for(Category.SPORTS) is reference.SPORTS_SETS
    assert sets_for("pokemon") is reference.POKEMON_SETS


def test_players_for_branches_by_category():
    assert players_for(Category.POKEMON) is reference.POPULAR_CHARACTERS
    assert players_for(Category.SPORTS) is reference.POPULAR_PLAYERS


def test_merge_options_puts_existing_first_and_dedupes():
    merged = merge_options(["Jungle", "Custom Set"], ["Base Set", "Jungle"])
    assert merged == ["Jungle", "Custom Set", "Base Set"]


def test_merge_options_is_case_insensitive_and_trims():
    merged = merge_options(["  base set "], ["Base Set", "BASE SET"])
    assert merged == ["base set"]


def test_merge_options_drops_blanks():
    assert merge_options(["", "  "], ["", "Holo"]) == ["Holo"]


def test_distinct_values_returns_used_column_values(session):
    session.add(Card(category=Category.POKEMON, player_or_character="Charizard",
                     set_name="Base Set", year=1999, grader=Grader.PSA, grade="9"))
    session.add(Card(category=Category.POKEMON, player_or_character="Pikachu",
                     set_name="Jungle", year=1999, grader=Grader.RAW, grade=""))
    session.add(Card(category=Category.POKEMON, player_or_character="Charizard",
                     set_name="Base Set", year=1999, grader=Grader.PSA, grade="10"))
    session.commit()
    assert distinct_values(session, Card.set_name) == ["Base Set", "Jungle"]
    assert distinct_values(session, Card.player_or_character) == ["Charizard", "Pikachu"]
    # blank grades are excluded
    assert distinct_values(session, Card.grade) == ["10", "9"]
