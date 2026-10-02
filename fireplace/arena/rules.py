"""Configuration and validation for the first arena ruleset.

The selected expansion budget is expressed in weighted slots: a large set
costs three slots and a small set costs one. Basic and Classic are always
present in the card pool and absent from selectable set tuples.
"""

from __future__ import annotations

from collections.abc import Iterable

from hearthstone.enums import CardClass


# A large set is an expansion with at least one hundred collectible cards in
# the bundled card data. Classic (EXPERT1) is fixed and does not use the
# expansion budget. The list is explicit so a future data update cannot
# silently change the arena format.
LARGE_SETS: tuple[str, ...] = (
    "GVG",
    "TGT",
    "OG",
    "GANGS",
    "UNGORO",
    "ICECROWN",
    "LOOTAPALOOZA",
    "GILNEAS",
    "BOOMSDAY",
    "TROLL",
    "DALARAN",
    "ULDUM",
    "DRAGONS",
    "BLACK_TEMPLE",
    "SCHOLOMANCE",
)


# Small sets are chosen as a stable, curated set of mini-expansions.  HOF and
# DEMON_HUNTER_INITIATE are intentionally not selectable in this first mode.
SMALL_SETS: tuple[str, ...] = (
    "NAXX",
    "BRM",
    "LOE",
    "KARA",
    "YEAR_OF_THE_DRAGON",
)


MIN_SET_BUDGET = 14
MAX_SET_BUDGET = 18
LARGE_SET_COST = 3
SMALL_SET_COST = 1
BASIC_SET = "BASIC"
CLASSIC_SET = "EXPERT1"


# The first release offers the nine classic heroes.  HERO_10 is present in
# the card data but is intentionally left for a later demon hunter ruleset.
HERO_IDS: dict[str, CardClass] = {
    "HERO_01": CardClass.WARRIOR,
    "HERO_02": CardClass.SHAMAN,
    "HERO_03": CardClass.ROGUE,
    "HERO_04": CardClass.PALADIN,
    "HERO_05": CardClass.HUNTER,
    "HERO_06": CardClass.DRUID,
    "HERO_07": CardClass.WARLOCK,
    "HERO_08": CardClass.MAGE,
    "HERO_09": CardClass.PRIEST,
}


_SELECTABLE_SETS = frozenset(LARGE_SETS + SMALL_SETS)


def validate_sets(ids: Iterable[str]) -> tuple[str, ...]:
    """Validate and return the requested arena expansion IDs in input order.

    A valid selection contains distinct known expansion IDs and has a total
    weighted cost between fourteen and eighteen, inclusive. ``BASIC`` and
    ``EXPERT1`` are locked into every arena pool and cannot be supplied as
    selectable IDs.
    """

    if isinstance(ids, (str, bytes)):
        raise ValueError("set IDs must be an iterable of strings")

    try:
        selected = tuple(ids)
    except TypeError as exc:
        raise ValueError("set IDs must be an iterable of strings") from exc

    if not selected:
        raise ValueError("at least one expansion set is required")
    if any(type(set_id) is not str for set_id in selected):
        raise ValueError("set IDs must be strings")
    if len(set(selected)) != len(selected):
        raise ValueError("set IDs must be distinct")

    unknown = [set_id for set_id in selected if set_id not in _SELECTABLE_SETS]
    if unknown:
        raise ValueError(f"unknown or locked arena set: {unknown[0]}")

    large_count = sum(set_id in LARGE_SETS for set_id in selected)
    small_count = sum(set_id in SMALL_SETS for set_id in selected)
    budget = large_count * LARGE_SET_COST + small_count * SMALL_SET_COST
    if not MIN_SET_BUDGET <= budget <= MAX_SET_BUDGET:
        raise ValueError(
            f"arena set selection budget must be between {MIN_SET_BUDGET} and "
            f"{MAX_SET_BUDGET} points"
        )

    return selected


def validate_hero_id(hero_id: str) -> str:
    """Return a classic arena hero ID or raise a clear validation error."""

    if hero_id not in HERO_IDS:
        raise ValueError(f"unknown arena hero: {hero_id!r}")
    return hero_id


def validate_pool_sets(ids: Iterable[str]) -> tuple[str, ...]:
    """Validate expansion IDs for a card-pool lookup.

    Pool lookups are also useful for diagnostics and UI previews, where a
    single expansion is often requested before a complete selection meets
    the budget range. They therefore validate membership and uniqueness but
    leave the full budget check to :func:`validate_sets`.
    """

    if isinstance(ids, (str, bytes)):
        raise ValueError("set IDs must be an iterable of strings")
    try:
        selected = tuple(ids)
    except TypeError as exc:
        raise ValueError("set IDs must be an iterable of strings") from exc
    if not selected:
        raise ValueError("at least one expansion set is required")
    if any(type(set_id) is not str for set_id in selected):
        raise ValueError("set IDs must be strings")
    if len(set(selected)) != len(selected):
        raise ValueError("set IDs must be distinct")
    unknown = [set_id for set_id in selected if set_id not in _SELECTABLE_SETS]
    if unknown:
        raise ValueError(f"unknown or locked arena set: {unknown[0]}")
    return selected


__all__ = [
    "BASIC_SET",
    "CLASSIC_SET",
    "HERO_IDS",
    "LARGE_SETS",
    "MIN_SET_BUDGET",
    "MAX_SET_BUDGET",
    "SMALL_SETS",
    "validate_hero_id",
    "validate_pool_sets",
    "validate_sets",
]
