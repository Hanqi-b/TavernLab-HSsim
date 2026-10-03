"""Unit tests for the independent XML-backed web card catalog."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from fireplace.web_gui import catalog as catalog_module
from fireplace.web_gui.catalog import CardCatalog


def _tag(enum_id: int, name: str, value: int) -> str:
    return (
        f'<Tag enumID="{enum_id}" name="{name}" type="Int" '
        f'value="{value}" />'
    )


def _localized_tag(enum_id: int, name: str, **values: str) -> str:
    body = "".join(
        f"<{locale}>{escape(text)}</{locale}>" for locale, text in values.items()
    )
    return f'<Tag enumID="{enum_id}" name="{name}" type="LocString">{body}</Tag>'


def _entity(
    card_id: str,
    *,
    name: dict[str, str],
    text: dict[str, str] | None = None,
    card_set: int = 2,
    card_class: int = 12,
    card_type: int = 4,
    rarity: int = 1,
    collectible: bool = True,
    cost: int = 2,
    attack: int = 0,
    health: int = 0,
    durability: int | None = None,
    multiple_classes: int | None = None,
    dbf_id: int = 1,
    copy_of_dbf: int | None = None,
) -> str:
    tags = [
        _localized_tag(185, "CARDNAME", **name),
        _localized_tag(184, "CARDTEXT", **(text or {})),
        _tag(183, "CARD_SET", card_set),
        _tag(199, "CLASS", card_class),
        _tag(202, "CARDTYPE", card_type),
        _tag(203, "RARITY", rarity),
        _tag(321, "COLLECTIBLE", int(collectible)),
        _tag(48, "COST", cost),
        _tag(47, "ATK", attack),
        _tag(45, "HEALTH", health),
    ]
    if durability is not None:
        tags.append(_tag(187, "DURABILITY", durability))
    if multiple_classes is not None:
        tags.append(_tag(476, "MULTIPLE_CLASSES", multiple_classes))
    if copy_of_dbf is not None:
        tags.append(
            _tag(
                1413,
                "DECK_RULE_COUNT_AS_COPY_OF_CARD_ID",
                copy_of_dbf,
            )
        )
    return f'<Entity CardID="{card_id}" ID="{dbf_id}">{"".join(tags)}</Entity>'


@pytest.fixture
def card_defs(tmp_path: Path) -> Path:
    path = tmp_path / "CardDefs.xml"
    path.write_text(
        "<CardDefs>"
        + _entity(
            "A_CARD",
            name={"zhCN": "阿尔法", "enUS": "Alpha"},
            text={"zhCN": "造成$6点伤害。<b>测试</b>[x]"},
            card_class=4,
            card_type=5,
            cost=4,
            attack=0,
            health=0,
        )
        + _entity(
            "B_MULTI",
            name={"zhCN": "多职业", "enUS": "Multi Class"},
            text={"enUS": "Draw a_card."},
            card_set=25,
            card_class=12,
            card_type=4,
            multiple_classes=40,
            attack=3,
            health=3,
        )
        + _entity(
            "C_TOKEN",
            name={"enUS": "Token"},
            text={"enUS": "Generated token"},
            collectible=False,
        )
        + _entity(
            "D_SKIN",
            name={"zhCN": "皮肤", "enUS": "Skin"},
            card_set=17,
            card_class=4,
        )
        + "</CardDefs>",
        encoding="utf-8",
    )
    return path


def test_catalog_is_lazy_and_returns_json_safe_localized_dto(
    card_defs: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[tuple[Path, str]] = []
    original_load = catalog_module.cardxml.load

    def load(*, path, locale, **kwargs):
        calls.append((Path(path), locale))
        return original_load(path=path, locale=locale, **kwargs)

    monkeypatch.setattr(catalog_module.cardxml, "load", load)
    catalog = CardCatalog(card_defs)
    assert calls == []

    card = catalog.get_card("A_CARD")
    assert card == {
        "id": "A_CARD",
        "name": "阿尔法",
        "text": "造成6点伤害。测试",
        "card_set": "BASIC",
        "catalog_set": "BASIC",
        "class": "MAGE",
        "classes": ["MAGE"],
        "type": "SPELL",
        "cost": 4,
        "attack": 0,
        "health": 0,
        "durability": 0,
        "rarity": "COMMON",
        "collectible": True,
        "has_python_script": False,
        "quality_status": None,
    }
    assert json.loads(json.dumps(card, ensure_ascii=False)) == card
    assert calls == [(card_defs, "zhCN")]
    assert catalog.get_card("A_CARD") == card
    assert len(calls) == 1


def test_catalog_searches_both_names_and_ids_and_supports_filters(card_defs: Path):
    catalog = CardCatalog(card_defs)

    by_english_name = catalog.list_cards(query="alpha")
    assert [item["id"] for item in by_english_name["items"]] == ["A_CARD"]
    by_id = catalog.list_cards(query="b_multi")
    assert [item["id"] for item in by_id["items"]] == ["B_MULTI"]

    mage = catalog.list_cards(card_class="MAGE", scope="all")
    ids = {item["id"] for item in mage["items"]}
    assert {"A_CARD", "B_MULTI", "D_SKIN"} <= ids
    assert "B_MULTI" in ids
    assert "NEUTRAL" not in next(
        item for item in mage["items"] if item["id"] == "B_MULTI"
    )["classes"]
    neutral = catalog.list_cards(card_class="NEUTRAL", scope="all")
    assert "B_MULTI" not in {item["id"] for item in neutral["items"]}
    assert catalog.list_cards(card_class="NEUTRAL")["sets"] == []


def test_scope_excludes_tokens_and_hero_skins_by_default(card_defs: Path):
    catalog = CardCatalog(card_defs)
    collectible = catalog.list_cards(page_size=100)
    assert collectible["total"] == 2
    assert {item["id"] for item in collectible["items"]} == {"A_CARD", "B_MULTI"}

    all_cards = catalog.list_cards(scope="all", page_size=100)
    assert all_cards["total"] == 4
    assert {item["id"] for item in all_cards["items"]} == {
        "A_CARD",
        "B_MULTI",
        "C_TOKEN",
        "D_SKIN",
    }


def test_cost_sort_applies_before_pagination(card_defs: Path):
    catalog = CardCatalog(card_defs)
    first = catalog.list_cards(sort="cost", page_size=1, page=1)
    second = catalog.list_cards(sort="cost", page_size=1, page=2)
    assert [item["id"] for item in first["items"]] == ["B_MULTI"]
    assert [item["id"] for item in second["items"]] == ["A_CARD"]
    with pytest.raises(ValueError, match="sort must be one of"):
        catalog.list_cards(sort="unknown")


def test_heroes_use_a_separate_catalog_set(card_defs: Path):
    catalog = CardCatalog(card_defs)
    # The fixture's A_CARD is a spell, so this test also locks in the
    # non-hero behavior while the HTTP integration test covers real heroes.
    card = catalog.get_card("A_CARD")
    assert card is not None
    assert card["card_set"] == "BASIC"
    assert card["catalog_set"] == "BASIC"
    assert catalog.list_cards(card_set="HEROES")["total"] == 0


def test_python_script_flag_is_json_safe_and_metadata_only(card_defs: Path):
    catalog = CardCatalog(card_defs)
    card = catalog.get_card("A_CARD")
    assert card is not None
    assert card["has_python_script"] is False
    assert card["quality_status"] is None
    assert json.loads(json.dumps(card))["has_python_script"] is False


def test_real_quality_status_is_present_in_list_and_detail():
    catalog = CardCatalog()

    listed = catalog.list_cards(query="EX1_560", page_size=10)
    yellow = next(item for item in listed["items"] if item["id"] == "EX1_560")
    assert yellow["quality_status"] == "YELLOW"
    assert catalog.get_card("EX1_560")["quality_status"] == "YELLOW"
    assert catalog.get_card("BT_035")["quality_status"] == "GREEN"


def test_quality_status_reader_accepts_red_and_silently_ignores_unknown_values(
    card_defs: Path, tmp_path: Path
):
    quality_csv = tmp_path / "quality.csv"
    quality_csv.write_text(
        "\ufeffcard_id,status\n"
        "A_CARD,RED\n"
        "B_MULTI,BLUE\n"
        "C_TOKEN,\n"
        "D_SKIN, green\n"
        "NOT_A_CARD,UNKNOWN\n",
        encoding="utf-8",
    )

    catalog = CardCatalog(card_defs, quality_csv_path=quality_csv)
    cards = catalog.list_cards(scope="all", page_size=100)["items"]
    by_id = {card["id"]: card for card in cards}
    assert by_id["A_CARD"]["quality_status"] == "RED"
    assert by_id["B_MULTI"]["quality_status"] is None
    assert by_id["C_TOKEN"]["quality_status"] is None
    assert by_id["D_SKIN"]["quality_status"] is None


def test_missing_quality_report_does_not_break_catalog(card_defs: Path, tmp_path: Path):
    catalog = CardCatalog(
        card_defs, quality_csv_path=tmp_path / "missing-quality-report.csv"
    )
    assert catalog.get_card("A_CARD")["quality_status"] is None


def test_real_catalog_separates_heroes_and_reports_script_presence():
    catalog = CardCatalog()
    heroes = catalog.list_cards(card_set="HEROES", page_size=1)
    assert heroes["total"] == 10
    assert next(entry for entry in heroes["sets"] if entry["id"] == "HEROES") == {
        "id": "HEROES",
        "label": "英雄",
        "count": 10,
    }

    all_heroes = catalog.list_cards(card_set="HEROES", scope="all", page_size=1)
    assert all_heroes["total"] == 10
    assert next(entry for entry in all_heroes["sets"] if entry["id"] == "HEROES")[
        "count"
    ] == 10

    hero = catalog.get_card("HERO_01")
    fireball = catalog.get_card("CS2_029")
    death_knight = catalog.get_card("ICC_828")
    boom_boss = catalog.get_card("BOT_238")
    weapon = catalog.get_card("CS2_080")
    hero_skin = catalog.get_card("HERO_01a")
    assert hero is not None and fireball is not None
    assert (
        death_knight is not None
        and boom_boss is not None
        and weapon is not None
        and hero_skin is not None
    )
    assert hero["card_set"] == "BASIC"
    assert hero["catalog_set"] == "HEROES"
    assert hero["has_python_script"] is False
    assert death_knight["card_set"] == "ICECROWN"
    assert death_knight["catalog_set"] == "ICECROWN"
    assert boom_boss["card_set"] == "BOOMSDAY"
    assert boom_boss["catalog_set"] == "BOOMSDAY"
    assert weapon["type"] == "WEAPON"
    assert weapon["attack"] == 3
    assert weapon["durability"] == 4
    assert hero_skin["card_set"] == "HERO_SKINS"
    assert hero_skin["catalog_set"] == "HERO_SKINS"
    assert "HERO_01a" in {
        item["id"]
        for item in catalog.list_cards(
            card_set="HERO_SKINS", scope="all", page_size=100
        )["items"]
    }
    assert "ICC_828" in {
        item["id"]
        for item in catalog.list_cards(card_set="ICECROWN", page_size=100)["items"]
    }
    assert "BOT_238" in {
        item["id"]
        for item in catalog.list_cards(card_set="BOOMSDAY", page_size=100)["items"]
    }
    assert fireball["has_python_script"] is True


def test_catalog_exposes_printed_weapon_durability_and_zero_for_spells(tmp_path: Path):
    source = tmp_path / "CardDefs.xml"
    source.write_text(
        "<CardDefs>"
        + _entity(
            "FIXTURE_WEAPON",
            name={"enUS": "Fixture Weapon"},
            card_class=10,
            card_type=7,
            cost=3,
            attack=4,
            durability=2,
        )
        + _entity(
            "FIXTURE_SPELL",
            name={"enUS": "Fixture Spell"},
            card_class=4,
            card_type=5,
            cost=2,
        )
        + "</CardDefs>",
        encoding="utf-8",
    )

    cards = CardCatalog(source).list_cards(scope="all", page_size=100)["items"]
    by_id = {card["id"]: card for card in cards}
    assert by_id["FIXTURE_WEAPON"]["durability"] == 2
    assert by_id["FIXTURE_SPELL"]["durability"] == 0


def test_dbf_copy_alias_inherits_the_target_script_flag(tmp_path: Path):
    source = tmp_path / "CardDefs.xml"
    source.write_text(
        "<CardDefs>"
        + _entity("SCRIPTED", name={"enUS": "Scripted"}, dbf_id=10)
        + _entity(
            "COPY_OF_SCRIPTED",
            name={"enUS": "Copy"},
            dbf_id=20,
            copy_of_dbf=10,
        )
        + "</CardDefs>",
        encoding="utf-8",
    )
    card_set = tmp_path / "example"
    card_set.mkdir()
    (card_set / "__init__.py").write_text(
        "from .cards import *\n", encoding="utf-8"
    )
    (card_set / "cards.py").write_text(
        "class SCRIPTED:\n    play = ()\n", encoding="utf-8"
    )

    catalog = CardCatalog(source)
    assert catalog.get_card("SCRIPTED")["has_python_script"] is True
    assert catalog.get_card("COPY_OF_SCRIPTED")["has_python_script"] is True


def test_multiclass_metadata_has_each_profession_and_filter_metadata(card_defs: Path):
    catalog = CardCatalog(card_defs)
    result = catalog.list_cards(card_set="GANGS")
    assert [item["id"] for item in result["items"]] == ["B_MULTI"]
    assert result["items"][0]["classes"] == ["MAGE", "PRIEST"]
    assert {entry["id"] for entry in result["classes"]} == {"MAGE", "PRIEST"}
    assert {entry["id"] for entry in result["sets"]} == {"BASIC", "GANGS"}
    assert next(entry for entry in result["sets"] if entry["id"] == "GANGS")["label"] == "加基森"
    english = catalog.list_cards(locale="enUS", card_set="GANGS")
    assert next(entry for entry in english["sets"] if entry["id"] == "GANGS")["label"] == "Mean Streets of Gadgetzan"


def test_localization_falls_back_to_english(card_defs: Path):
    card = CardCatalog(card_defs).get_card("C_TOKEN", locale="zhCN")
    assert card is not None
    assert card["name"] == "Token"
    assert card["text"] == "Generated token"


def test_missing_rules_text_is_empty_but_missing_name_uses_card_id(card_defs: Path):
    card = CardCatalog(card_defs).get_card("D_SKIN", locale="zhCN")
    assert card is not None
    assert card["name"] == "皮肤"
    assert card["text"] == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"locale": "frFR"},
        {"scope": "missing"},
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"query": "x" * 101},
        {"card_set": "MISSING"},
        {"card_class": "MISSING"},
    ],
)
def test_invalid_catalog_parameters_raise_value_error(card_defs: Path, kwargs):
    with pytest.raises(ValueError):
        CardCatalog(card_defs).list_cards(**kwargs)


def test_card_ids_are_validated_and_unknown_ids_return_none(card_defs: Path):
    catalog = CardCatalog(card_defs)
    assert catalog.get_card("UNKNOWN") is None
    assert not catalog.contains("UNKNOWN")
    with pytest.raises(ValueError):
        catalog.get_card("../unsafe")
    with pytest.raises(ValueError):
        catalog.contains("not-safe!")


def test_concurrent_first_reads_publish_one_complete_index(
    card_defs: Path, monkeypatch: pytest.MonkeyPatch
):
    original_load = catalog_module.cardxml.load
    call_count = 0
    count_lock = threading.Lock()

    def load(*, path, locale, **kwargs):
        nonlocal call_count
        with count_lock:
            call_count += 1
        time.sleep(0.01)
        return original_load(path=path, locale=locale, **kwargs)

    monkeypatch.setattr(catalog_module.cardxml, "load", load)
    catalog = CardCatalog(card_defs)
    results: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def read() -> None:
        try:
            results.append(catalog.list_cards(query="A_CARD"))
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not errors
    assert len(results) == len(threads)
    assert all(result["total"] == 1 for result in results)
    assert call_count == 1
