from __future__ import annotations

import json
from pathlib import Path

import pytest

from fireplace.arena.rules import HERO_IDS
from fireplace.web_gui.decks import (
    DeckConflict,
    DeckService,
    DeckStore,
    DeckStoreCorrupt,
    default_state_path,
)


class FakeCatalog:
    source_path = None

    def __init__(self):
        self.cards = {}
        for hero_id, hero_class in HERO_IDS.items():
            self.cards[hero_id] = self._card(
                hero_id,
                hero_id,
                hero_class.name,
                "HERO",
                "BASIC",
                "FREE",
            )
        for index in range(1, 16):
            card_id = f"N_{index:02d}"
            self.cards[card_id] = self._card(
                card_id, f"中立{index}", "NEUTRAL", "MINION", "EXPERT1", "COMMON"
            )
        self.cards["MAGE_SPELL"] = self._card(
            "MAGE_SPELL", "法师法术", "MAGE", "SPELL", "EXPERT1", "RARE"
        )
        self.cards["MAGE_HERO"] = self._card(
            "MAGE_HERO", "扩展英雄", "MAGE", "HERO", "BOOMSDAY", "LEGENDARY"
        )
        self.cards["WARRIOR_SPELL"] = self._card(
            "WARRIOR_SPELL", "战士法术", "WARRIOR", "SPELL", "EXPERT1", "COMMON"
        )
        self.cards["SKIN_01"] = self._card(
            "SKIN_01", "皮肤", "MAGE", "HERO", "HERO_SKINS", "EPIC"
        )
        self.cards["TOKEN"] = self._card(
            "TOKEN", "衍生物", "MAGE", "MINION", "EXPERT1", "COMMON", collectible=False
        )

    @staticmethod
    def _card(card_id, name, card_class, card_type, card_set, rarity, *, collectible=True):
        return {
            "id": card_id,
            "name": name,
            "text": "",
            "card_set": card_set,
            "catalog_set": card_set,
            "class": card_class,
            "classes": [card_class],
            "type": card_type,
            "cost": 2,
            "attack": 2,
            "health": 2,
            "rarity": rarity,
            "collectible": collectible,
            "has_python_script": False,
        }

    def get_card(self, card_id, locale="zhCN"):
        card = self.cards.get(card_id)
        return None if card is None else dict(card, classes=list(card["classes"]))


def _service(tmp_path: Path) -> DeckService:
    return DeckService(store=DeckStore(tmp_path / "decks.json"), catalog=FakeCatalog())


def test_default_state_path_honors_tavernlab_override_and_legacy_fallback(
    monkeypatch, tmp_path: Path
):
    tavernlab_override = tmp_path / "tavernlab" / "decks.json"
    fireplace_override = tmp_path / "fireplace" / "decks.json"
    monkeypatch.setenv("TAVERNLAB_DECK_STATE", str(tavernlab_override))
    monkeypatch.setenv("FIREPLACE_DECK_STATE", str(fireplace_override))
    assert default_state_path() == tavernlab_override

    monkeypatch.delenv("TAVERNLAB_DECK_STATE")
    assert default_state_path() == fireplace_override
    monkeypatch.delenv("FIREPLACE_DECK_STATE")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert default_state_path() == Path.home() / ".local" / "state" / "fireplace" / "decks.json"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_state_path() == tmp_path / "state" / "fireplace" / "decks.json"


def test_save_lists_localized_metadata_and_persists(tmp_path: Path):
    service = _service(tmp_path)
    created = service.save({"name": "法师测试", "hero_id": "HERO_08", "card_ids": []})

    assert created["locale"] == "zhCN"
    assert len(created["heroes"]) == 9
    assert len(created["decks"]) == 1
    deck = created["decks"][0]
    assert deck["revision"] == 1
    assert deck["hero_id"] == "HERO_08"
    assert deck["card_ids"] == []
    assert deck["cards"] == []
    assert deck["complete"] is False
    with pytest.raises(ValueError, match="exactly 30"):
        service.get_complete(deck["id"])

    restored = DeckService(
        store=DeckStore(tmp_path / "decks.json"), catalog=FakeCatalog()
    ).list("enUS")
    assert restored["locale"] == "enUS"
    assert restored["decks"][0]["id"] == deck["id"]
    assert restored["decks"][0]["revision"] == 1


def test_update_requires_revision_and_complete_deck_is_available_to_match(tmp_path):
    service = _service(tmp_path)
    created = service.save({"name": "完整法师", "hero_id": "HERO_08", "card_ids": []})
    deck = created["decks"][0]
    card_ids = [f"N_{index:02d}" for index in range(1, 16)] * 2

    updated = service.save(
        {
            "id": deck["id"],
            "revision": deck["revision"],
            "name": deck["name"],
            "hero_id": deck["hero_id"],
            "card_ids": card_ids,
        }
    )
    assert updated["decks"][0]["revision"] == 2
    assert updated["decks"][0]["complete"] is True
    trusted = service.get_complete(deck["id"])
    assert trusted == {"hero_id": "HERO_08", "card_ids": card_ids}

    with pytest.raises(DeckConflict):
        service.save(
            {
                "id": deck["id"],
                "revision": 1,
                "name": "旧版本",
                "hero_id": "HERO_08",
                "card_ids": [],
            }
        )


@pytest.mark.parametrize(
    ("card_ids", "message"),
    [
        (["HERO_01"], "initial heroes"),
        (["SKIN_01"], "skins"),
        (["TOKEN"], "not collectible"),
        (["WARRIOR_SPELL"], "does not belong"),
        (["MAGE_SPELL"] * 3, "too many copies"),
        (["MAGE_HERO", "MAGE_HERO"], "too many copies"),
    ],
)
def test_save_rejects_cards_outside_deck_rules(tmp_path, card_ids, message):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match=message):
        service.save({"name": "非法", "hero_id": "HERO_08", "card_ids": card_ids})


def test_delete_requires_current_revision(tmp_path: Path):
    service = _service(tmp_path)
    deck = service.save({"name": "待删除", "hero_id": "HERO_08", "card_ids": []})[
        "decks"
    ][0]
    with pytest.raises(DeckConflict):
        service.delete({"id": deck["id"], "revision": 2})
    remaining = service.delete({"id": deck["id"], "revision": 1})
    assert remaining["decks"] == []
    with pytest.raises(ValueError, match="unknown deck"):
        service.get_complete(deck["id"])


def test_corrupt_save_is_not_overwritten(tmp_path: Path):
    path = tmp_path / "decks.json"
    path.write_text("{broken", encoding="utf-8")
    service = DeckService(store=DeckStore(path), catalog=FakeCatalog())
    with pytest.raises(DeckStoreCorrupt):
        service.save({"name": "新卡组", "hero_id": "HERO_08", "card_ids": []})
    assert path.read_text(encoding="utf-8") == "{broken"


def test_store_json_is_small_and_json_safe(tmp_path: Path):
    service = _service(tmp_path)
    service.save({"name": "JSON", "hero_id": "HERO_08", "card_ids": []})
    payload = json.loads((tmp_path / "decks.json").read_text(encoding="utf-8"))
    assert set(payload) == {"decks"}
    assert len(payload["decks"]) == 1


def test_removed_catalog_card_does_not_block_other_decks(tmp_path: Path):
    service = _service(tmp_path)
    old = service.save({
        "name": "旧卡组", "hero_id": "HERO_08", "card_ids": ["N_01"] * 2,
    })["decks"][0]
    service.catalog.cards.pop("N_01")

    created = service.save({"name": "新卡组", "hero_id": "HERO_08", "card_ids": []})
    assert created["saved_id"] != old["id"]
    stale = next(deck for deck in created["decks"] if deck["id"] == old["id"])
    assert stale["valid"] is False
    assert stale["complete"] is False
    assert stale["cards"][0]["name"] == "N_01"

    remaining = service.delete({"id": old["id"], "revision": old["revision"]})
    assert [deck["id"] for deck in remaining["decks"]] == [created["saved_id"]]
