from __future__ import annotations

from pathlib import Path

from hearthstone.enums import CardSet

from fireplace import cards as runtime_cards
from fireplace.card_data import (
    DEFAULT_CARD_DEFS_PATH,
    SCHOLOMANCE_SOURCE_COMMIT,
    SCHOLOMANCE_SOURCE_FILE_SHA256,
    SCHOLOMANCE_SOURCE_SHA256,
    load_card_data,
)
from fireplace.web_gui.catalog import CardCatalog
from fireplace.web_gui.decks import DeckService, DeckStore


def _card_fingerprint(card):
    return (
        card.dbf_id,
        dict(card.tags),
        dict(card.strings),
        dict(card.referenced_tags),
    )


def test_scholomance_overlay_has_launch_counts_and_provenance():
    loaded, provenance = load_card_data(locale="enUS")
    scholomance = {
        card_id: card
        for card_id, card in loaded.items()
        if card_id.startswith("SCH_")
    }

    assert len(scholomance) == 259
    assert sum(bool(card.collectible) for card in scholomance.values()) == 135
    assert provenance.overlay_build == "54613"
    assert provenance.overlay_records == 259
    assert provenance.overlay_collectible == 135
    assert provenance.source_commit == SCHOLOMANCE_SOURCE_COMMIT
    assert provenance.source_sha256 == SCHOLOMANCE_SOURCE_FILE_SHA256
    assert provenance.overlay_sha256 == SCHOLOMANCE_SOURCE_SHA256


def test_overlay_preserves_every_non_scholomance_baseline_record():
    baseline, _ = load_card_data(
        locale="enUS",
        source_path=DEFAULT_CARD_DEFS_PATH,
        include_scholomance=False,
    )
    merged, _ = load_card_data(locale="enUS")

    baseline_ids = {card_id for card_id in baseline if not card_id.startswith("SCH_")}
    assert baseline_ids <= merged.keys()
    for card_id in baseline_ids:
        assert _card_fingerprint(merged[card_id]) == _card_fingerprint(baseline[card_id])


def test_default_game_and_catalog_share_scholomance_metadata():
    if not runtime_cards.db.initialized:
        runtime_cards.db.initialize()

    runtime_ids = {
        card_id for card_id in runtime_cards.db if card_id.startswith("SCH_")
    }
    assert len(runtime_ids) == 259
    assert sum(bool(runtime_cards.db[card_id].collectible) for card_id in runtime_ids) == 135

    catalog = CardCatalog()
    all_cards = catalog.list_cards(
        card_set=CardSet.SCHOLOMANCE.name,
        scope="all",
        page_size=100,
    )
    assert all_cards["total"] == 259
    for card_id in ("SCH_120", "SCH_126", "SCH_199", "SCH_199t"):
        game_card = runtime_cards.db[card_id]
        catalog_card = catalog.get_card(card_id, locale="enUS")
        assert catalog_card is not None
        assert catalog_card["name"] == game_card.name
        assert catalog_card["card_set"] == game_card.card_set.name


def test_explicit_catalog_source_path_does_not_receive_overlay():
    baseline_catalog = CardCatalog(Path(DEFAULT_CARD_DEFS_PATH))
    production_catalog = CardCatalog()

    assert baseline_catalog.list_cards(
        card_set="SCHOLOMANCE", scope="all", page_size=100
    )["total"] == 30
    assert production_catalog.list_cards(
        card_set="SCHOLOMANCE", scope="all", page_size=100
    )["total"] == 259


def test_dual_class_scholomance_card_is_accepted_by_deck_service(tmp_path: Path):
    catalog = CardCatalog()
    card = catalog.get_card("SCH_126", locale="zhCN")
    assert card is not None
    assert card["classes"] == ["PRIEST", "WARLOCK"]

    service = DeckService(
        store=DeckStore(tmp_path / "decks.json"),
        catalog=catalog,
    )
    saved = service.save(
        {
            "name": "通灵双职业测试",
            "hero_id": "HERO_09",
            "card_ids": ["SCH_126"],
        }
    )
    assert saved["decks"][0]["card_ids"] == ["SCH_126"]


def test_all_forty_dual_class_cards_belong_to_both_runtime_pools():
    runtime_cards.db.initialize()
    dual = [card for card in runtime_cards.db.values()
            if card.id.startswith('SCH_') and card.collectible and len(card.classes) == 2]
    assert len(dual) == 40
    for card in dual:
        for card_class in card.classes:
            pool = runtime_cards.db.filter(collectible=True, card_class=card_class)
            assert card.id in pool, (card.id, card_class)

def test_every_collectible_has_runtime_implementation_and_catalog_badge():
    runtime_cards.db.initialize()
    catalog = CardCatalog()
    collectible = [card for card in runtime_cards.db.values()
                   if card.id.startswith("SCH_") and card.collectible]
    assert len(collectible) == 135
    for card in collectible:
        implementation = card.scripts.__bases__[0]
        assert implementation.__module__.startswith("fireplace.cards.scholomance."), card.id
        assert catalog.get_card(card.id)["has_python_script"], card.id
