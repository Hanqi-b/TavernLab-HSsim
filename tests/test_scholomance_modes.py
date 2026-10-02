"""Scholomance eligibility across collection, random play and Arena."""
from collections import Counter
from random import Random
from types import SimpleNamespace

import pytest
from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.arena.pool import eligible_cards
from fireplace.arena.rules import HERO_IDS, validate_sets
from fireplace.random_setup import random_draft
from fireplace.web_gui.arena_service import ArenaService
from fireplace.arena.store import ArenaStore
from fireplace.web_gui.catalog import CardCatalog
from fireplace.web_gui.decks import DeckStore
from fireplace.web_gui.server import WebGameManager


class RecordingRandom(Random):
    def choice(self, population):
        self.pool = tuple(population)
        return super().choice(population)


@pytest.mark.parametrize("hero_class", tuple(HERO_IDS.values()))
def test_random_draft_pool_respects_every_class_on_dual_class_cards(hero_class):
    if not cards.db.initialized:
        cards.db.initialize()
    rng = RecordingRandom(19)
    deck = random_draft(hero_class, game=SimpleNamespace(random=rng))
    assert len(deck) == 30
    for card in rng.pool:
        classes = set(card.classes)
        if len(classes) > 1:
            classes.discard(CardClass.NEUTRAL)
        assert hero_class in classes or classes == {CardClass.NEUTRAL}, card.id
    assert all(count <= cards.db[cid].max_count_in_deck
               for cid, count in Counter(deck).items())
    pool_ids = {card.id for card in rng.pool}
    assert ("SCH_350" in pool_ids) == (hero_class in (CardClass.MAGE, CardClass.ROGUE))
    assert ("SCH_126" in pool_ids) == (hero_class in (CardClass.PRIEST, CardClass.WARLOCK))


@pytest.mark.parametrize("hero_id", tuple(HERO_IDS))
def test_scholomance_arena_pool_has_exactly_the_legal_launch_cards(hero_id):
    if not cards.db.initialized:
        cards.db.initialize()
    pool = eligible_cards(("SCHOLOMANCE",), hero_id)
    actual = {card.id for card in pool if card.card_set == "SCHOLOMANCE"}
    hero_class = HERO_IDS[hero_id]
    expected = {
        cid for cid, card in cards.db.items()
        if cid.startswith("SCH_") and card.collectible
        and (hero_class in card.classes or set(card.classes) == {CardClass.NEUTRAL})
    }
    assert actual == expected
    assert "SCH_199" in actual
    assert not any(card.id.startswith("SCH_") for card in eligible_cards(("GVG",), hero_id))


def test_arena_setup_exposes_scholomance_with_three_point_budget(tmp_path):
    selected = ("SCHOLOMANCE", "GVG", "TGT", "OG", "GANGS", "NAXX")
    assert validate_sets(selected) == selected
    service = ArenaService(store=ArenaStore(tmp_path / "arena.json"))
    try:
        option = next(pack for pack in service.state()["pack_options"]["large"]
                      if pack["id"] == "SCHOLOMANCE")
        assert option["count"] == 135 and option["label"] == "通灵学园"
    finally:
        service.close()


def test_collection_saves_all_scholomance_deck_and_starts_real_match(tmp_path):
    catalog = CardCatalog()
    candidates = [card for card in catalog.list_cards(
        card_set="SCHOLOMANCE", page_size=100,
    )["items"] if card["rarity"] != "LEGENDARY"
        and ("MAGE" in card["classes"] or card["classes"] == ["NEUTRAL"])]
    assert len(candidates) >= 15
    ids = [card["id"] for card in candidates[:15] for _ in range(2)]
    app = WebGameManager(seed=31, deck_store=DeckStore(tmp_path / "decks.json"),
                         asset_resolver=None)
    try:
        saved = app.decks_save({"name": "通灵学园", "hero_id": "HERO_08", "card_ids": ids})
        deck = saved["decks"][0]
        assert deck["complete"]
        state = app.start_match({"nickname": "Tester", "locale": "zhCN", "deck_id": deck["id"]})
        assert state["mode"] == "match"
        assert Counter(card.id for card in app.active.human.starting_deck) == Counter(ids)
    finally:
        app.close()
