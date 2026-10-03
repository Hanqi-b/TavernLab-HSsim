"""Build an immutable, JSON-friendly arena card pool from the card database."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from hearthstone.enums import CardClass, CardType

from .. import cards
from .rules import BASIC_SET, CLASSIC_SET, HERO_IDS, validate_hero_id, validate_pool_sets


_DRAFT_TYPES = frozenset(
    {
        CardType.MINION,
        CardType.SPELL,
        CardType.WEAPON,
        CardType.HERO,
    }
)


def _enum_name(value: object) -> str:
    return str(getattr(value, "name", value))


def _card_classes(card: object) -> tuple[str, ...]:
    """Return card classes while removing the neutral marker from dual cards."""

    raw_classes = getattr(card, "classes", ()) or ()
    names = tuple(
        name
        for name in (_enum_name(value) for value in raw_classes)
        if name and name != "INVALID"
    )
    if len(names) > 1 and "NEUTRAL" in names:
        names = tuple(name for name in names if name != "NEUTRAL")
    if not names:
        card_class = _enum_name(getattr(card, "card_class", None))
        if card_class and card_class != "INVALID":
            names = (card_class,)
    return tuple(dict.fromkeys(names))


@dataclass(frozen=True, slots=True)
class CardInfo:
    """The scalar card data needed by the draft and UI layers.

    Enum values are represented by their names so ``CardInfo.as_dict()`` can
    be passed to ``json.dumps`` without exposing engine objects.  ``classes``
    is extra metadata for multi-class cards and is optional for callers that
    construct a small synthetic pool in tests.
    """

    id: str
    name: str
    rarity: str
    card_class: str
    card_set: str
    cost: int
    type: str
    classes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation of this card."""

        return {
            "id": self.id,
            "name": self.name,
            "rarity": self.rarity,
            "card_class": self.card_class,
            "card_set": self.card_set,
            "cost": self.cost,
            "type": self.type,
            "classes": list(self.classes),
        }

    def to_dict(self) -> dict[str, Any]:
        """Alias used by callers that prefer an explicit serialization name."""

        return self.as_dict()


@dataclass(frozen=True, slots=True)
class HistoricalCard:
    """Scalar metadata for one card in the frozen 2016 legal pool.

    This is deliberately separate from :class:`CardInfo`: the historical
    bundle carries the source-era DBF ID and exact set/type metadata, while
    ``CardInfo`` mirrors the current card database and its existing callers.
    """

    id: str
    name: str
    dbf_id: int
    card_class: str
    card_set: str
    card_type: str
    rarity: str
    cost: int

    @property
    def classes(self) -> tuple[str, ...]:
        return () if self.card_class == "NEUTRAL" else (self.card_class,)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "dbf_id": self.dbf_id,
            "card_class": self.card_class,
            "card_set": self.card_set,
            "card_type": self.card_type,
            "rarity": self.rarity,
            "cost": self.cost,
            "classes": list(self.classes),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()


def _is_eligible_card(card: object, allowed_sets: frozenset[str], hero_class: str) -> bool:
    card_id = getattr(card, "id", "")
    card_set = _enum_name(getattr(card, "card_set", None))
    card_type = getattr(card, "type", None)

    if card_set not in allowed_sets:
        return False
    if not bool(getattr(card, "collectible", False)):
        return False
    if card_type not in _DRAFT_TYPES:
        return False
    # HERO_01...HERO_10 are starting heroes and HERO_01a... are skins.  They
    # must not become draft picks even though the XML marks most as collectible.
    # Expansion heroes such as BOT_238 remain eligible and are handled like
    # any other card in the selected expansion.
    if card_type == CardType.HERO and (
        str(card_id).startswith("HERO_") or card_set == "HERO_SKINS"
    ):
        return False

    classes = _card_classes(card)
    if hero_class not in classes and "NEUTRAL" not in classes:
        return False
    return True


def eligible_cards(set_ids, hero_id: str) -> tuple[CardInfo, ...]:
    """Return all collectible cards legal for ``hero_id`` and ``set_ids``.

    ``BASIC`` and ``EXPERT1`` are always added to the allowed set list. An old
    saved run may still include ``EXPERT1`` among its selected IDs; it is
    ignored as an expansion choice. The input does not need to satisfy the full
    fourteen-to-eighteen-point budget, which makes this function useful for previews and
    focused tests.  The returned tuple is sorted by card ID and is safe to
    retain between draft rounds.
    """

    requested_sets = tuple(set_ids)
    if requested_sets.count(CLASSIC_SET) > 1:
        raise ValueError("Classic set may appear at most once")
    selected_sets = validate_pool_sets(
        set_id for set_id in requested_sets if set_id != CLASSIC_SET
    )
    validate_hero_id(hero_id)
    hero_class = HERO_IDS[hero_id].name
    allowed_sets = frozenset((BASIC_SET, CLASSIC_SET, *selected_sets))

    # CardDB.initialize is idempotent; using values here avoids CardDB.filter's
    # implicit default type and hero behavior, both of which differ from the
    # arena rules for expansion HERO cards.
    if not cards.db.initialized:
        cards.db.initialize()

    result: list[CardInfo] = []
    for card in cards.db.values():
        if not _is_eligible_card(card, allowed_sets, hero_class):
            continue
        classes = _card_classes(card)
        result.append(
            CardInfo(
                id=str(card.id),
                name=str(getattr(card, "name", card.id)),
                rarity=_enum_name(getattr(card, "rarity", None)),
                card_class=_enum_name(getattr(card, "card_class", None)),
                card_set=_enum_name(getattr(card, "card_set", None)),
                cost=int(getattr(card, "cost", 0) or 0),
                type=_enum_name(getattr(card, "type", None)),
                classes=classes,
            )
        )
    result.sort(key=lambda card: card.id)
    return tuple(result)


def _historical_json(path):
    """Read one historical JSON artifact without importing it at module load."""

    from .formats import HistoricalFormatError

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HistoricalFormatError(f"historical Arena data is unavailable: {path}") from exc
    digest = hashlib.sha256(data).hexdigest()
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalFormatError(f"historical Arena file is not valid JSON: {path}") from exc
    return payload, data, digest


def load_historical_pool() -> tuple[dict[str, Any], bytes, str]:
    """Load and checksum the pinned historical pool artifact lazily."""

    from .formats import PROVENANCE_PATH, POOL_PATH, HistoricalFormatError

    payload, data, digest = _historical_json(POOL_PATH)
    manifest, _, _ = _historical_json(PROVENANCE_PATH)
    if not isinstance(manifest, dict):
        raise HistoricalFormatError("historical Arena manifest must be an object")
    if digest != manifest.get("pool_sha256"):
        raise HistoricalFormatError("historical legal pool checksum does not match manifest")
    if not isinstance(payload, dict) or not isinstance(payload.get("cards"), list):
        raise HistoricalFormatError("historical pool must contain a cards list")
    return payload, data, digest


def _historical_cards_from_payload(payload: dict[str, Any]) -> tuple[HistoricalCard, ...]:
    """Validate frozen metadata and materialize sorted historical cards."""

    from .formats import (
        FIXED_SETS,
        HERO_CLASSES,
        HistoricalFormatError,
        KNOWN_CARD_TYPES,
        KNOWN_RARITIES,
    )

    required = {"id", "name", "dbf_id", "card_class", "card_set", "card_type", "rarity", "cost"}
    cards: list[HistoricalCard] = []
    seen: set[str] = set()
    class_counts = {hero_class: 0 for hero_class in HERO_CLASSES.values()}
    rows = payload["cards"]
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            card_id = row.get("id") if isinstance(row, dict) else None
            raise HistoricalFormatError(f"invalid legal card metadata keys for {card_id!r}")
        card_id = row["id"]
        if not isinstance(card_id, str) or not card_id or card_id in seen:
            raise HistoricalFormatError("historical legal card IDs must be unique strings")
        if not isinstance(row["name"], str) or not row["name"]:
            raise HistoricalFormatError(f"invalid card name for {card_id}")
        if type(row["dbf_id"]) is not int or row["dbf_id"] <= 0:
            raise HistoricalFormatError(f"missing current dbf ID for {card_id}")
        card_class = row["card_class"]
        card_set = row["card_set"]
        card_type = row["card_type"]
        rarity = row["rarity"]
        if card_class not in set(HERO_CLASSES.values()) | {"NEUTRAL"}:
            raise HistoricalFormatError(f"unknown historical card class for {card_id}: {card_class!r}")
        if card_set not in FIXED_SETS:
            raise HistoricalFormatError(f"historical card set is outside fixed manifest for {card_id}")
        if card_type not in KNOWN_CARD_TYPES:
            raise HistoricalFormatError(f"historical card type is not draftable for {card_id}")
        if rarity not in KNOWN_RARITIES:
            raise HistoricalFormatError(f"unknown historical card rarity for {card_id}: {rarity!r}")
        if type(row["cost"]) is not int or row["cost"] < 0:
            raise HistoricalFormatError(f"invalid historical card cost for {card_id}")
        if card_class != "NEUTRAL":
            class_counts[card_class] += 1
        cards.append(
            HistoricalCard(
                id=card_id,
                name=row["name"],
                dbf_id=row["dbf_id"],
                card_class=card_class,
                card_set=card_set,
                card_type=card_type,
                rarity=rarity,
                cost=row["cost"],
            )
        )
        seen.add(card_id)
    if any(count < 3 for count in class_counts.values()):
        missing = [hero_class for hero_class, count in class_counts.items() if count < 3]
        raise HistoricalFormatError(
            "historical legal pool must contain at least three cards for every hero class: "
            + ", ".join(missing)
        )
    return tuple(sorted(cards, key=lambda card: card.id))


def load_historical_cards() -> tuple[HistoricalCard, ...]:
    """Load, validate, and sort the complete pinned legal card pool."""

    payload, _, _ = load_historical_pool()
    return _historical_cards_from_payload(payload)


def historical_eligible_cards(hero_id: str) -> tuple[HistoricalCard, ...]:
    """Return the pinned 2016 legal pool for one classic hero.

    The historical bundle is loaded lazily so importing or using
    ``custom_v1`` keeps the original pool path untouched.
    """

    from .formats import HERO_CLASSES

    value = getattr(hero_id, "name", hero_id)
    if not isinstance(value, str) or value not in HERO_CLASSES:
        raise ValueError(f"unknown historical Arena hero: {hero_id!r}")
    hero_class = HERO_CLASSES[value]
    return tuple(
        card
        for card in load_historical_cards()
        if card.card_class in {"NEUTRAL", hero_class}
    )


__all__ = [
    "CardInfo",
    "HistoricalCard",
    "eligible_cards",
    "historical_eligible_cards",
    "load_historical_cards",
    "load_historical_pool",
]
