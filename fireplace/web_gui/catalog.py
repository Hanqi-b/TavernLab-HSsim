"""Read-only, metadata-only access to the local Hearthstone card catalog.

The game database in :mod:`fireplace.cards` merges XML records with Python
card implementations and has a deliberately eager initialization path.  The
browser card browser only needs the XML metadata, so this module uses
``hearthstone.cardxml`` directly and never imports the game database.
"""

from __future__ import annotations

import csv
import html
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from types import MappingProxyType
from typing import Any

from hearthstone import cardxml
from hearthstone.enums import CardSet, GameTag

from fireplace.card_data import DEFAULT_CARD_DEFS_PATH, load_card_data

from .script_index import PythonScriptIndex


_VALID_LOCALES = frozenset(("zhCN", "enUS"))
_VALID_SCOPES = frozenset(("collectible", "all"))
_CARD_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,128}$")
_MAX_PAGE_SIZE = 100
_MAX_QUERY_LENGTH = 100
_CARD_MARKUP_RE = re.compile(r"<[^>]*>")
_CARD_VALUE_RE = re.compile(r"\$(\d+)")
_CARD_TOKEN_RE = re.compile(r"\[x\]", re.IGNORECASE)
_QUALITY_STATUSES = frozenset(("GREEN", "YELLOW", "RED"))
_QUALITY_REPORT_RELATIVE_PATH = Path(
    "reports", "card_quality_full_2026-09-27", "card_quality.csv"
)

# Hearthstone's enum module intentionally exposes stable IDs rather than UI
# translations.  Keep this small display-only table here so the catalog API
# can offer useful filter labels without importing the game database.
_SET_LABELS = {
    "BASIC": ("基础", "Basic"),
    "BATTLEGROUNDS": ("酒馆战棋", "Battlegrounds"),
    "BLACK_TEMPLE": ("外域的灰烬", "Ashes of Outland"),
    "BOOMSDAY": ("砰砰计划", "The Boomsday Project"),
    "BRM": ("黑石山的火焰", "Blackrock Mountain"),
    "CREDITS": ("制作人员", "Credits"),
    "DALARAN": ("暗影崛起", "Rise of Shadows"),
    "DEMON_HUNTER_INITIATE": ("恶魔猎手新兵", "Demon Hunter Initiate"),
    "DRAGONS": ("巨龙降临", "Descent of Dragons"),
    "EXPERT1": ("经典", "Classic"),
    "GANGS": ("加基森", "Mean Streets of Gadgetzan"),
    "GILNEAS": ("女巫森林", "The Witchwood"),
    "GVG": ("地精大战侏儒", "Goblins vs. Gnomes"),
    "HEROES": ("英雄", "Heroes"),
    "HERO_SKINS": ("英雄皮肤", "Hero Skins"),
    "HOF": ("荣誉室", "Hall of Fame"),
    "ICECROWN": ("冰封王座", "Knights of the Frozen Throne"),
    "KARA": ("卡拉赞之夜", "One Night in Karazhan"),
    "LOE": ("探险者协会", "The League of Explorers"),
    "LOOTAPALOOZA": ("狗头人与地下世界", "Kobolds & Catacombs"),
    "MISSIONS": ("任务", "Missions"),
    "NAXX": ("纳克萨玛斯", "Curse of Naxxramas"),
    "OG": ("上古之神的低语", "Whispers of the Old Gods"),
    "SCHOLOMANCE": ("通灵学园", "Scholomance Academy"),
    "TAVERNS_OF_TIME": ("时光酒馆", "Taverns of Time"),
    "TB": ("乱斗模式", "Tavern Brawl"),
    "TGT": ("冠军的试炼", "The Grand Tournament"),
    "TROLL": ("拉斯塔哈的大乱斗", "Rastakhan's Rumble"),
    "ULDUM": ("奥丹姆", "Saviors of Uldum"),
    "UNGORO": ("安戈洛环形山", "Journey to Un'Goro"),
    "WILD_EVENT": ("狂野活动", "Wild Event"),
    "YEAR_OF_THE_DRAGON": ("巨龙年", "Year of the Dragon"),
}
_CLASS_LABELS = {
    "DEATHKNIGHT": ("死亡骑士", "Death Knight"),
    "DEMONHUNTER": ("恶魔猎手", "Demon Hunter"),
    "DREAM": ("梦境", "Dream"),
    "DRUID": ("德鲁伊", "Druid"),
    "HUNTER": ("猎人", "Hunter"),
    "MAGE": ("法师", "Mage"),
    "NEUTRAL": ("中立", "Neutral"),
    "PALADIN": ("圣骑士", "Paladin"),
    "PRIEST": ("牧师", "Priest"),
    "ROGUE": ("盗贼", "Rogue"),
    "SHAMAN": ("萨满祭司", "Shaman"),
    "WARLOCK": ("术士", "Warlock"),
    "WARRIOR": ("战士", "Warrior"),
    "WHIZBANG": ("威兹班", "Whizbang"),
}


def _default_source_path() -> Path:
    return DEFAULT_CARD_DEFS_PATH


def _default_quality_report_path() -> Path:
    return Path(__file__).resolve().parents[2] / _QUALITY_REPORT_RELATIVE_PATH


def _read_quality_statuses(path: Path) -> dict[str, str]:
    """Read validated per-card quality statuses from the fixed aggregate report."""

    statuses: dict[str, str | None] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or not {
                "card_id",
                "status",
            }.issubset(reader.fieldnames):
                return {}
            for row in reader:
                card_id = row.get("card_id")
                status = row.get("status")
                if not isinstance(card_id, str):
                    continue
                card_id = card_id.strip()
                if not _CARD_ID_RE.fullmatch(card_id):
                    continue
                normalized_status = status if isinstance(status, str) else None
                if normalized_status not in _QUALITY_STATUSES:
                    normalized_status = None
                previous = statuses.get(card_id)
                if card_id in statuses and previous != normalized_status:
                    # Conflicting duplicate rows are ambiguous; do not choose
                    # an arbitrary classification.
                    statuses[card_id] = None
                elif card_id not in statuses:
                    statuses[card_id] = normalized_status
    except (OSError, UnicodeError, csv.Error):
        return {}
    return {
        card_id: status
        for card_id, status in statuses.items()
        if status in _QUALITY_STATUSES
    }


def _enum_name(value: object) -> str | None:
    """Return an enum's stable JSON representation without importing cards."""

    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    if value is None:
        return None
    return str(value)


def _localized_value(
    card: object,
    tag: GameTag,
    locale: str,
    card_id: str,
    *,
    fallback: str | None = None,
) -> str:
    """Choose a localized field and provide a stable fallback.

    ``CardXML`` already falls back from Chinese to English for its properties,
    but reading the string map directly also covers empty values and keeps the
    fallback behavior explicit for catalog records.
    """

    strings = getattr(card, "strings", {})
    values = strings.get(tag, {}) if hasattr(strings, "get") else {}
    if not isinstance(values, dict):
        values = {}
    candidates = (locale, "enUS") if locale == "zhCN" else (locale,)
    for candidate in candidates:
        value = values.get(candidate)
        if isinstance(value, str) and value:
            return value
    return card_id if fallback is None else fallback


def _display_text(value: str) -> str:
    """Turn CardDefs' small presentation markup into safe display text."""

    value = _CARD_TOKEN_RE.sub("", value)
    value = _CARD_VALUE_RE.sub(r"\1", value)
    value = _CARD_MARKUP_RE.sub("", value)
    return html.unescape(value.replace("_", " "))


def _filter_label(value: str, locale: str, labels: dict[str, tuple[str, str]]) -> str:
    translated = labels.get(value)
    if translated is not None:
        return translated[0] if locale == "zhCN" else translated[1]
    return value.replace("_", " ").title()


def _class_names(card: object) -> tuple[str, ...]:
    """Return applicable profession names for a card.

    Multi-class XML records commonly carry ``NEUTRAL`` in their base CLASS
    tag even though their MULTIPLE_CLASSES tag lists the actual professions.
    Removing that neutral marker keeps those cards out of the neutral filter.
    """

    raw_classes = getattr(card, "classes", ()) or ()
    names = [
        name
        for name in (_enum_name(value) for value in raw_classes)
        if name and name != "INVALID"
    ]
    if len(names) > 1:
        non_neutral = [name for name in names if name != "NEUTRAL"]
        if non_neutral:
            names = non_neutral
    return tuple(dict.fromkeys(names))


@dataclass(frozen=True, slots=True)
class _CardRecord:
    """Immutable data needed for one locale's catalog index."""

    id: str
    name: str
    text: str
    chinese_name: str
    english_name: str
    card_set: str | None
    class_name: str | None
    classes: tuple[str, ...]
    type: str | None
    cost: int
    attack: int
    health: int
    durability: int
    rarity: str | None
    collectible: bool
    catalog_set: str | None
    has_python_script: bool
    quality_status: str | None

    @property
    def search_text(self) -> str:
        return " ".join(
            (self.id, self.name, self.chinese_name, self.english_name)
        ).casefold()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "text": self.text,
            "card_set": self.card_set,
            "catalog_set": self.catalog_set,
            "class": self.class_name,
            "classes": list(self.classes),
            "type": self.type,
            "cost": self.cost,
            "attack": self.attack,
            "health": self.health,
            "durability": self.durability,
            "rarity": self.rarity,
            "collectible": self.collectible,
            "has_python_script": self.has_python_script,
            "quality_status": self.quality_status,
        }


@dataclass(frozen=True, slots=True)
class _CatalogIndex:
    records: tuple[_CardRecord, ...]
    by_id: MappingProxyType


class CardCatalog:
    """Thread-safe lazy index over one local ``CardDefs.xml`` file.

    Loading is done once per requested locale while holding a small lock.  A
    complete immutable index is published only after XML parsing and record
    conversion finish, so readers never observe a partially loaded catalog.
    """

    def __init__(
        self,
        source_path: Path | None = None,
        *,
        quality_csv_path: Path | None = None,
    ):
        self._uses_shared_default_data = source_path is None
        self.source_path = Path(source_path) if source_path is not None else _default_source_path()
        self._lock = RLock()
        self._indexes: dict[str, _CatalogIndex] = {}
        self._script_index = PythonScriptIndex(self.source_path.parent)
        self._quality_csv_path = (
            Path(quality_csv_path)
            if quality_csv_path is not None
            else _default_quality_report_path()
        )
        self._quality_statuses: dict[str, str] | None = None

    def _get_quality_statuses(self) -> dict[str, str]:
        current = self._quality_statuses
        if current is None:
            current = _read_quality_statuses(self._quality_csv_path)
            self._quality_statuses = current
        return current

    def _validate_locale(self, locale: str) -> str:
        if not isinstance(locale, str) or locale not in _VALID_LOCALES:
            raise ValueError("locale must be one of: zhCN, enUS")
        return locale

    @staticmethod
    def _validate_card_id(card_id: str) -> str:
        if not isinstance(card_id, str) or not _CARD_ID_RE.fullmatch(card_id):
            raise ValueError("card_id must contain only ASCII letters, digits, and underscores")
        return card_id

    @staticmethod
    def _validate_scope(scope: str) -> str:
        if not isinstance(scope, str) or scope not in _VALID_SCOPES:
            raise ValueError("scope must be one of: collectible, all")
        return scope

    @staticmethod
    def _validate_page(page: int, page_size: int) -> tuple[int, int]:
        if type(page) is not int or page < 1:
            raise ValueError("page must be a positive integer")
        if type(page_size) is not int or not 1 <= page_size <= _MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {_MAX_PAGE_SIZE}")
        return page, page_size

    @staticmethod
    def _validate_query(query: str) -> str:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if len(query) > _MAX_QUERY_LENGTH:
            raise ValueError(f"query must be at most {_MAX_QUERY_LENGTH} characters")
        return query.strip()

    @staticmethod
    def _enum_filter(value: str | None, enum_type: object, field: str) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        candidate = value.upper()
        members = getattr(enum_type, "__members__", {})
        if candidate in members:
            return candidate
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None:
            for member in members.values():
                if getattr(member, "value", None) == numeric:
                    return getattr(member, "name", str(numeric))
        raise ValueError(f"unknown {field}: {value}")

    def _get_index(self, locale: str) -> _CatalogIndex:
        locale = self._validate_locale(locale)
        with self._lock:
            current = self._indexes.get(locale)
            if current is not None:
                return current

            if self._uses_shared_default_data:
                loaded, _ = load_card_data(locale=locale)
            else:
                loaded, _ = load_card_data(
                    locale=locale,
                    source_path=self.source_path,
                    include_scholomance=False,
                )
            quality_statuses = self._get_quality_statuses()
            dbf_to_id = {
                card.dbf_id: card_id
                for card_id, card in loaded.items()
                if isinstance(card_id, str)
                and isinstance(getattr(card, "dbf_id", None), int)
            }
            records: list[_CardRecord] = []
            for card_id, card in loaded.items():
                if not isinstance(card_id, str) or not _CARD_ID_RE.fullmatch(card_id):
                    continue
                classes = _class_names(card)
                card_type = _enum_name(getattr(card, "type", None))
                card_set_name = _enum_name(getattr(card, "card_set", None))
                # The ten BASIC hero records are the starting heroes shown in
                # their own catalog section.  Expansion heroes are real cards
                # with their own set, mana cost, and battle effects, so keep
                # them in the source expansion instead of collapsing every
                # HERO record into the synthetic HEROES section.
                catalog_set = (
                    "HEROES"
                    if card_type == "HERO" and card_set_name == "BASIC"
                    else card_set_name
                )
                has_python_script = self._script_index.has_definition(card_id)
                if not has_python_script:
                    tags = getattr(card, "tags", {})
                    alias_dbf = (
                        tags.get(GameTag.DECK_RULE_COUNT_AS_COPY_OF_CARD_ID)
                        if hasattr(tags, "get")
                        else None
                    )
                    card_dbf = getattr(card, "dbf_id", None)
                    target_id = (
                        dbf_to_id.get(alias_dbf)
                        if isinstance(alias_dbf, int)
                        and isinstance(card_dbf, int)
                        and alias_dbf < card_dbf
                        else None
                    )
                    has_python_script = bool(
                        target_id is not None
                        and self._script_index.has_definition(target_id)
                    )
                record = _CardRecord(
                    id=card_id,
                    name=_localized_value(card, GameTag.CARDNAME, locale, card_id),
                    chinese_name=_localized_value(
                        card, GameTag.CARDNAME, "zhCN", card_id
                    ),
                    text=_display_text(
                        _localized_value(
                            card,
                            GameTag.CARDTEXT,
                            locale,
                            card_id,
                            fallback="",
                        )
                    ),
                    english_name=_localized_value(card, GameTag.CARDNAME, "enUS", card_id),
                    card_set=card_set_name,
                    class_name=classes[0] if classes else None,
                    classes=classes,
                    type=card_type,
                    cost=int(getattr(card, "cost", 0) or 0),
                    attack=int(getattr(card, "atk", 0) or 0),
                    health=int(getattr(card, "health", 0) or 0),
                    durability=int(getattr(card, "durability", 0) or 0),
                    rarity=_enum_name(getattr(card, "rarity", None)),
                    collectible=bool(getattr(card, "collectible", False)),
                    catalog_set=catalog_set,
                    has_python_script=has_python_script,
                    quality_status=quality_statuses.get(card_id),
                )
                records.append(record)

            records.sort(key=lambda record: (record.name.casefold(), record.id))
            index = _CatalogIndex(
                records=tuple(records),
                by_id=MappingProxyType({record.id: record for record in records}),
            )
            self._indexes[locale] = index
            return index

    @staticmethod
    def _filter_metadata(
        records: tuple[_CardRecord, ...], locale: str
    ) -> dict[str, list[dict[str, Any]]]:
        sets = Counter(record.catalog_set for record in records if record.catalog_set)
        classes: Counter[str] = Counter()
        for record in records:
            classes.update(record.classes)
        return {
            "sets": [
                {
                    "id": value,
                    "label": _filter_label(value, locale, _SET_LABELS),
                    "count": sets[value],
                }
                for value in sorted(sets, key=lambda value: (value != "HEROES", value))
            ],
            "classes": [
                {
                    "id": value,
                    "label": _filter_label(value, locale, _CLASS_LABELS),
                    "count": classes[value],
                }
                for value in sorted(classes)
            ],
        }

    def list_cards(
        self,
        *,
        locale: str = "zhCN",
        card_set: str | None = None,
        card_class: str | None = None,
        query: str = "",
        scope: str = "collectible",
        sort: str = "name",
        page: int = 1,
        page_size: int = 48,
    ) -> dict[str, Any]:
        """Return one deterministic page and filter metadata.

        ``scope="collectible"`` excludes non-collectible records and hero
        skins.  ``scope="all"`` includes every XML record, including those
        generated or used only by the game client.  ``sort="cost"`` orders
        the filtered records before pagination.
        """

        locale = self._validate_locale(locale)
        scope = self._validate_scope(scope)
        if not isinstance(sort, str) or sort not in {"name", "cost"}:
            raise ValueError("sort must be one of: name, cost")
        page, page_size = self._validate_page(page, page_size)
        query = self._validate_query(query)
        if isinstance(card_set, str) and card_set.upper() == "HEROES":
            card_set = "HEROES"
        else:
            card_set = self._enum_filter(card_set, CardSet, "card_set")

        # CardClass is imported lazily here to keep the module's public import
        # surface small; it is still an enum-only dependency, never cards.db.
        from hearthstone.enums import CardClass

        card_class = self._enum_filter(card_class, CardClass, "card_class")
        index = self._get_index(locale)
        scoped = tuple(
            record
            for record in index.records
            if scope == "all"
            or (record.collectible and record.card_set != CardSet.HERO_SKINS.name)
        )
        metadata = self._filter_metadata(scoped, locale)
        if card_class is not None:
            class_scoped = tuple(record for record in scoped if card_class in record.classes)
            metadata["sets"] = self._filter_metadata(class_scoped, locale)["sets"]
        needle = query.casefold()
        filtered = tuple(
            record
            for record in scoped
            if (card_set is None or record.catalog_set == card_set)
            and (card_class is None or card_class in record.classes)
            and (not needle or needle in record.search_text)
        )
        if sort == "cost":
            filtered = tuple(
                sorted(
                    filtered,
                    key=lambda record: (record.cost, record.name.casefold(), record.id),
                )
            )
        total = len(filtered)
        start = (page - 1) * page_size
        items = [record.as_dict() for record in filtered[start : start + page_size]]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            **metadata,
        }

    def get_card(self, card_id: str, locale: str = "zhCN") -> dict[str, Any] | None:
        """Return one safe JSON DTO, or ``None`` when the ID is unknown."""

        card_id = self._validate_card_id(card_id)
        index = self._get_index(locale)
        card = index.by_id.get(card_id)
        return card.as_dict() if card is not None else None

    def contains(self, card_id: str) -> bool:
        """Return whether an XML record exists for a safe card ID."""

        card_id = self._validate_card_id(card_id)
        return card_id in self._get_index("zhCN").by_id


__all__ = ["CardCatalog"]
