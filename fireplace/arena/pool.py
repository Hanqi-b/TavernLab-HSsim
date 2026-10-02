"""Build an immutable, JSON-friendly arena card pool from the card database."""

from __future__ import annotations

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


__all__ = ["CardInfo", "eligible_cards"]
