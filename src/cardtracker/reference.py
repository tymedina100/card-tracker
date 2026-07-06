"""Curated seed lists for the entry dropdowns.

These are representative popular values, not exhaustive catalogs. The dashboard
merges them with the values a user has already entered and still lets them type
anything new, so a missing set or player here is never a dead end.
"""

from cardtracker.models import Category

POKEMON_SETS = [
    "Base Set",
    "Base Set 2",
    "Jungle",
    "Fossil",
    "Team Rocket",
    "Gym Heroes",
    "Gym Challenge",
    "Neo Genesis",
    "Neo Destiny",
    "Expedition",
    "EX Ruby & Sapphire",
    "EX Dragon",
    "Diamond & Pearl",
    "HeartGold SoulSilver",
    "Black & White",
    "XY Evolutions",
    "Sun & Moon",
    "Hidden Fates",
    "Cosmic Eclipse",
    "Sword & Shield",
    "Vivid Voltage",
    "Shining Fates",
    "Chilling Reign",
    "Evolving Skies",
    "Fusion Strike",
    "Brilliant Stars",
    "Astral Radiance",
    "Lost Origin",
    "Silver Tempest",
    "Crown Zenith",
    "Scarlet & Violet",
    "Paldea Evolved",
    "Obsidian Flames",
    "Paldean Fates",
    "Temporal Forces",
    "Twilight Masquerade",
    "151",
    "Prismatic Evolutions",
]

SPORTS_SETS = [
    "Topps",
    "Topps Chrome",
    "Topps Update",
    "Bowman",
    "Bowman Chrome",
    "Panini Prizm",
    "Panini Select",
    "Panini Mosaic",
    "Panini Optic",
    "Panini Donruss",
    "Panini Contenders",
    "Panini National Treasures",
    "Panini Flawless",
    "Panini Immaculate",
    "Panini Obsidian",
    "Panini Chronicles",
    "Panini Spectra",
    "Upper Deck",
    "Upper Deck Young Guns",
    "Fleer",
    "Score",
    "Leaf",
]

PARALLELS = [
    "Base",
    "Holo",
    "Reverse Holo",
    "1st Edition",
    "Shadowless",
    "Unlimited",
    "Full Art",
    "Alt Art",
    "Secret Rare",
    "Rainbow Rare",
    "Gold",
    "Refractor",
    "X-Fractor",
    "Prizm Silver",
    "Prizm",
    "Prizm Red",
    "Prizm Blue",
    "Prizm Green",
    "Prizm Gold /10",
    "Prizm Black /1",
    "Silver",
    "Sapphire",
    "Wave",
    "Shimmer",
    "Numbered /99",
    "Numbered /25",
    "Numbered /10",
    "1/1",
]

POKEMON_PARALLELS = [
    "Base",
    "Holo",
    "Reverse Holo",
    "1st Edition",
    "Shadowless",
    "Unlimited",
    "Full Art",
    "Alt Art",
    "Secret Rare",
    "Rainbow Rare",
    "Gold",
]

SPORTS_PARALLELS = [
    "Base",
    "Refractor",
    "X-Fractor",
    "Prizm Silver",
    "Prizm",
    "Prizm Red",
    "Prizm Blue",
    "Prizm Green",
    "Prizm Gold /10",
    "Prizm Black /1",
    "Silver",
    "Sapphire",
    "Wave",
    "Shimmer",
    "Numbered /99",
    "Numbered /25",
    "Numbered /10",
    "1/1",
]

POPULAR_PLAYERS = [
    "Michael Jordan",
    "LeBron James",
    "Kobe Bryant",
    "Stephen Curry",
    "Victor Wembanyama",
    "Tom Brady",
    "Patrick Mahomes",
    "Mike Trout",
    "Shohei Ohtani",
    "Mickey Mantle",
    "Wayne Gretzky",
    "Connor McDavid",
    "Lionel Messi",
    "Cristiano Ronaldo",
]

POPULAR_CHARACTERS = [
    "Charizard",
    "Pikachu",
    "Blastoise",
    "Venusaur",
    "Mewtwo",
    "Mew",
    "Umbreon",
    "Rayquaza",
    "Lugia",
    "Gengar",
    "Eevee",
    "Gyarados",
    "Snorlax",
    "Dragonite",
]

GRADES = ["10", "9.5", "9", "8.5", "8", "7", "6", "5", "4", "3", "2", "1", "Authentic"]


def sets_for(category: str | Category) -> list[str]:
    """Curated set list for a category. Pokemon and sports have different sets."""
    if str(category) == Category.POKEMON:
        return POKEMON_SETS
    return SPORTS_SETS


def players_for(category: str | Category) -> list[str]:
    """Curated player or character list for a category."""
    if str(category) == Category.POKEMON:
        return POPULAR_CHARACTERS
    return POPULAR_PLAYERS


def parallels_for(category: str | Category) -> list[str]:
    """Curated parallel list for a category."""
    if str(category) == Category.POKEMON:
        return POKEMON_PARALLELS
    return SPORTS_PARALLELS
