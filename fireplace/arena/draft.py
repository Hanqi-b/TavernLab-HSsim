"""Deterministic hero and card offers for the arena draft."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

from .pool import CardInfo
from .rules import HERO_IDS


CLASS_CARD_WEIGHT = 2
OFFER_SIZE = 3


def hero_offer(rng: random.Random) -> tuple[str, str, str]:
    """Draw three distinct classic hero IDs from the supplied RNG."""

    if not isinstance(rng, random.Random):
        raise TypeError("rng must be an instance of random.Random")
    return tuple(rng.sample(tuple(HERO_IDS), OFFER_SIZE))


def _field(card: CardInfo | Mapping[str, Any], name: str, default: Any = None) -> Any:
    if isinstance(card, Mapping):
        return card.get(name, default)
    return getattr(card, name, default)


def _is_class_card(card: CardInfo | Mapping[str, Any]) -> bool:
    classes = _field(card, "classes", ()) or ()
    if isinstance(classes, str):
        classes = (classes,)
    if any(value != "NEUTRAL" for value in classes):
        return True
    return _field(card, "card_class") not in (None, "", "NEUTRAL", "INVALID")


def _weighted_choice(
    rng: random.Random,
    cards: Sequence[CardInfo | Mapping[str, Any]],
    weights: Sequence[int],
) -> CardInfo | Mapping[str, Any]:
    total = sum(weights)
    if total <= 0:
        raise ValueError("card weights must contain a positive total")
    needle = rng.random() * total
    cumulative = 0
    for card, weight in zip(cards, weights):
        cumulative += weight
        if needle < cumulative:
            return card
    return cards[-1]


def _weighted_sample(
    rng: random.Random,
    cards: Sequence[CardInfo | Mapping[str, Any]],
    count: int,
    class_weight: int,
) -> list[CardInfo | Mapping[str, Any]]:
    remaining = list(cards)
    chosen: list[CardInfo | Mapping[str, Any]] = []
    for _ in range(count):
        weights = [
            class_weight if _is_class_card(card) else 1 for card in remaining
        ]
        selected = _weighted_choice(rng, remaining, weights)
        chosen.append(selected)
        remaining.remove(selected)
    return chosen


def card_offer(
    rng: random.Random,
    pool: Sequence[CardInfo | Mapping[str, Any]],
    *,
    class_weight: int = CLASS_CARD_WEIGHT,
) -> tuple[str, str, str]:
    """Draw three distinct IDs, favoring class cards two-to-one by default.

    The first weighted draw chooses an anchor card.  When at least three cards
    share its rarity, all offered cards come from that rarity; when a rarity
    is too small, the complete pool is used as a deterministic fallback.  The
    pool may contain ``CardInfo`` instances or equivalent JSON mappings so the
    draft layer can consume persisted UI data in tests and previews.
    """

    if not isinstance(rng, random.Random):
        raise TypeError("rng must be an instance of random.Random")
    if type(class_weight) is not int or class_weight < 1:
        raise ValueError("class_weight must be a positive integer")

    unique: list[CardInfo | Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for card in pool:
        card_id = _field(card, "id")
        if not isinstance(card_id, str):
            raise ValueError("each card in pool must have a string id")
        if card_id not in seen_ids:
            seen_ids.add(card_id)
            unique.append(card)
    if len(unique) < OFFER_SIZE:
        raise ValueError("card pool must contain at least three distinct cards")

    weights = [class_weight if _is_class_card(card) else 1 for card in unique]
    anchor = _weighted_choice(rng, unique, weights)
    rarity = _field(anchor, "rarity")
    same_rarity = [card for card in unique if _field(card, "rarity") == rarity]
    source = same_rarity if len(same_rarity) >= OFFER_SIZE else unique
    selected = _weighted_sample(rng, source, OFFER_SIZE, class_weight)
    return tuple(_field(card, "id") for card in selected)


__all__ = [
    "CLASS_CARD_WEIGHT",
    "OFFER_SIZE",
    "card_offer",
    "hero_offer",
]
