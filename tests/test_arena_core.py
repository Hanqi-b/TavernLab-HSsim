"""Focused tests for the standalone arena rules and draft primitives."""

from __future__ import annotations

import json
import random

import pytest
from hearthstone.enums import CardClass

from fireplace.arena.draft import card_offer, hero_offer
from fireplace.arena.pool import eligible_cards
from fireplace.arena.rules import HERO_IDS, LARGE_SETS, SMALL_SETS, validate_sets


def test_classic_hero_offer_has_nine_heroes_and_is_repeatable():
    assert len(HERO_IDS) == 9
    assert set(HERO_IDS.values()) == {
        CardClass.WARRIOR,
        CardClass.SHAMAN,
        CardClass.ROGUE,
        CardClass.PALADIN,
        CardClass.HUNTER,
        CardClass.DRUID,
        CardClass.WARLOCK,
        CardClass.MAGE,
        CardClass.PRIEST,
    }

    first = hero_offer(random.Random(17))
    second = hero_offer(random.Random(17))
    assert first == second
    assert len(first) == 3
    assert len(set(first)) == 3
    assert set(first) <= set(HERO_IDS)


def test_set_budget_requires_unique_known_expansions():
    valid = ("GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX")
    assert validate_sets(valid) == valid
    assert validate_sets(("GVG", "TGT", "OG", "GANGS", "NAXX", "BRM", "LOE", "KARA"))

    with pytest.raises(ValueError, match="distinct"):
        validate_sets(("GVG", "GVG", "TGT", "OG", "GANGS", "NAXX"))
    with pytest.raises(ValueError, match=r"budget|3 \* large"):
        validate_sets(("GVG", "TGT"))
    with pytest.raises(ValueError, match="unknown|locked"):
        validate_sets(("GVG", "TGT", "OG", "GANGS", "UNGORO", "BASIC"))
    with pytest.raises(ValueError, match="unknown|locked"):
        validate_sets(("EXPERT1", "GVG", "TGT", "OG", "GANGS", "NAXX"))
    with pytest.raises(ValueError, match="unknown|locked"):
        validate_sets(("GVG", "TGT", "OG", "GANGS", "UNGORO", "HOF"))

    assert "EXPERT1" not in LARGE_SETS + SMALL_SETS
    assert {"NAXX", "BRM", "LOE", "KARA", "YEAR_OF_THE_DRAGON"} <= set(SMALL_SETS)
    assert "HOF" not in LARGE_SETS + SMALL_SETS
    assert "DEMON_HUNTER_INITIATE" not in LARGE_SETS + SMALL_SETS


def test_pool_includes_basic_and_class_neutral_cards_and_playable_heroes():
    pool = eligible_cards(("BOOMSDAY",), "HERO_01")
    by_id = {card.id: card for card in pool}

    # Basic and Classic are locked into every pool, while a selected expansion can add a
    # playable HERO card such as Dr. Boom.
    assert any(card.card_set == "BASIC" for card in pool)
    assert any(card.card_set == "EXPERT1" for card in pool)
    assert "BOT_238" in by_id
    assert by_id["BOT_238"].type == "HERO"
    assert by_id["BOT_238"].card_class == "WARRIOR"

    # Starting heroes and skins are never draft picks.
    assert not any(card.id.startswith("HERO_") for card in pool)
    assert all(card.card_class in {"WARRIOR", "NEUTRAL"} for card in pool)
    assert all(card.card_set != "HERO_SKINS" for card in pool)
    json.dumps([card.as_dict() for card in pool])

    dragon_pool = {card.id: card for card in eligible_cards(("DRAGONS",), "HERO_01")}
    assert dragon_pool["DRG_650"].type == "HERO"


def test_card_offer_is_distinct_repeatable_and_prefers_same_rarity():
    pool = tuple(
        {
            "id": f"CARD_{index}",
            "rarity": "COMMON" if index < 4 else "RARE",
            "card_class": "MAGE" if index % 2 == 0 else "NEUTRAL",
            "classes": ("MAGE",) if index % 2 == 0 else ("NEUTRAL",),
        }
        for index in range(6)
    )

    first = card_offer(random.Random(29), pool)
    second = card_offer(random.Random(29), pool)
    assert first == second
    assert len(first) == 3
    assert len(set(first)) == 3
    assert all(card_id in {card["id"] for card in pool} for card_id in first)
    assert {
        next(card["rarity"] for card in pool if card["id"] == card_id)
        for card_id in first
    } == {"COMMON"}
