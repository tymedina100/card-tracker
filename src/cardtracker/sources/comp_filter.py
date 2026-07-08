"""Filter Browse API ask comps down to the exact card.

The eBay Browse API takes a loose keyword query, so a search for a base
PSA 9 also returns autos, refractors, serial-numbered parallels, and other
grades that merely share the same words. Mixing those into the comp pool
skews the median that drives market value, max-buy, and deal math.

This module inspects each listing title against the card's structured fields
(grader, grade, parallel, number) and drops listings that clearly do not
match. It is heuristic and title-based: it cannot catch listings whose title
omits the distinguishing detail, so it errs toward keeping a listing when the
title is silent. Callers can turn it off (strict=False) for obscure cards
where a stricter pass would leave too few comps.
"""

import re

from cardtracker.models import Card, Grader
from cardtracker.sources.base import CompRecord

# A grader token followed, within a few non-digit characters, by its grade.
# Matches "PSA 9", "PSA GEM MT 10", "BGS 9.5", "PSA10" (no space), and the
# non-numeric "PSA Authentic" / "PSA Auth" grade. The non-greedy skip lets
# qualifier words ("GEM MT", "MINT") sit between the grader and the grade.
_GRADE_RE = re.compile(
    r"\b(PSA|BGS|SGC|CGC)[^0-9]{0,12}?(10|[1-9](?:\.5)?|authentic|auth)\b",
    re.IGNORECASE,
)


def _norm_grade(grade: str) -> str:
    """Normalize a grade for comparison: lower-cased, 'auth' folded to 'authentic'."""
    g = grade.strip().lower()
    return "authentic" if g == "auth" else g

# Words that mark a parallel, insert, autograph, or memorabilia card. A plain
# base card is none of these, so their presence means a different product.
_PARALLEL_RE = re.compile(
    r"\b(refractors?|x-?fractors?|superfractors?|prizms?|sapphire|mojo|atomic|"
    r"shimmer|velocity|speckle|cracked ice|printing plate|die[- ]?cut|"
    r"patch|relic|jersey|insert|ssp|1\s?/\s?1|1 of 1)\b",
    re.IGNORECASE,
)
# A serial number like "/50" or "/ 499" marks a numbered parallel.
_SERIAL_RE = re.compile(r"/\s?\d{1,4}\b")
# Autograph markers, handled separately so they apply to any non-auto card.
_AUTO_RE = re.compile(r"\bauto(graph(ed)?)?\b", re.IGNORECASE)


def _grade_pairs(title: str) -> list[tuple[str, str]]:
    """All (grader, grade) pairs mentioned in a title, grader upper-cased and
    grade normalized (lower-cased, 'auth' folded to 'authentic')."""
    return [(g.upper(), _norm_grade(n)) for g, n in _GRADE_RE.findall(title)]


def _matches_card(title: str, card: Card) -> bool:
    """True if a listing title is consistent with this card's identity."""
    if not title.strip():
        return True  # nothing to judge on, keep it

    title_l = title.lower()
    variant_l = (card.variation_or_parallel or "").strip().lower()
    pairs = _grade_pairs(title)

    # Grader and grade must agree.
    if card.grader == Grader.RAW:
        if pairs:
            return False  # a graded slab is not a raw card
    else:
        # grader may be a Grader enum or a plain str when loaded from the DB.
        target = (str(card.grader).upper(), _norm_grade(card.grade))
        if not any(pair == target for pair in pairs):
            return False  # wrong grade, wrong grader, or no grade shown

    # An autograph is a different product unless this card is itself an auto.
    if "auto" not in variant_l and _AUTO_RE.search(title):
        return False

    is_base = variant_l in ("", "base")
    if is_base:
        # A base card is not a parallel or a serial-numbered card.
        if _PARALLEL_RE.search(title) or _SERIAL_RE.search(title):
            return False
    else:
        # A parallel listing should name the parallel. Require each meaningful
        # word of the stored variation to appear in the title.
        for token in re.split(r"[^a-z0-9]+", variant_l):
            if len(token) >= 3 and token not in title_l:
                return False

    # If the title cites card numbers and none is ours, it is a different card.
    target_num = (card.card_number or "").lstrip("#").strip()
    if target_num.isdigit():
        cited = re.findall(r"#\s?(\d+)", title)
        if cited and target_num not in cited:
            return False

    return True


def filter_comps_for_card(
    records: list[CompRecord], card: Card, strict: bool = True
) -> tuple[list[CompRecord], list[CompRecord]]:
    """Split records into (kept, dropped) by whether each matches the card.

    With strict=False nothing is dropped, so the caller keeps the raw pull.
    """
    if not strict:
        return list(records), []
    kept: list[CompRecord] = []
    dropped: list[CompRecord] = []
    for record in records:
        (kept if _matches_card(record.title_raw, card) else dropped).append(record)
    return kept, dropped
