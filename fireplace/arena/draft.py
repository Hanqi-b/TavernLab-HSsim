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


def _historical_field(card: object, name: str, default: Any = None) -> Any:
    if isinstance(card, Mapping):
        return card.get(name, default)
    return getattr(card, name, default)


def _historical_rarity(card: object) -> str:
    return str(_historical_field(card, "rarity", "")).upper()


def _historical_offer_weight(card: object) -> int:
    # The source material does not establish a measured expansion-rate boost.
    # The frozen reconstruction therefore uses the documented Karazhan
    # multiplier of one and gives class cards the documented two-to-one weight.
    from .formats import CLASS_WEIGHT, EXPANSION_BOOST

    card_class = str(
        _historical_field(
            card,
            "card_class",
            _historical_field(card, "class", "NEUTRAL"),
        )
    ).upper()
    card_set = str(_historical_field(card, "card_set", "")).upper()
    weight = EXPANSION_BOOST if card_set == "KARA" else 1
    if card_class != "NEUTRAL":
        weight *= CLASS_WEIGHT
    return weight


def historical_card_offer(
    rng: random.Random,
    pool: Sequence[CardInfo | Mapping[str, Any] | object],
    pick_number: int,
) -> tuple[str, str, str]:
    """Offer three distinct IDs from one reconstructed rarity bucket.

    Picks 1, 10, 20, and 30 select the entire three-card offer from one
    Rare/Epic/Legendary bucket. Other rounds select the entire offer from the
    shared Basic/Common bucket or one of those three rare-plus buckets. A
    bucket with fewer than three unique cards is a deterministic error; no
    fallback or silent renormalization is applied.
    """

    from .formats import (
        GUARANTEED_RARE_PLUS_PICKS,
        OFFER_SIZE,
        RARITY_WEIGHTS,
        RARE_PLUS_RARITIES,
        REGULAR_RARITIES,
    )

    if not isinstance(rng, random.Random):
        raise TypeError("rng must be an instance of random.Random")
    if type(pick_number) is not int or pick_number < 1:
        raise ValueError("pick_number must be a positive integer")

    unique: list[object] = []
    seen: set[str] = set()
    for card in pool:
        card_id = _historical_field(card, "id", _historical_field(card, "card_id"))
        if not isinstance(card_id, str) or not card_id:
            raise ValueError("each historical offer card must have a string id")
        if card_id not in seen:
            unique.append(card)
            seen.add(card_id)
    if len(unique) < OFFER_SIZE:
        raise ValueError("historical card pool must contain at least three distinct cards")

    category_candidates: dict[str, list[object]] = {
        "COMMON": [card for card in unique if _historical_rarity(card) in REGULAR_RARITIES],
        "RARE": [card for card in unique if _historical_rarity(card) == "RARE"],
        "EPIC": [card for card in unique if _historical_rarity(card) == "EPIC"],
        "LEGENDARY": [card for card in unique if _historical_rarity(card) == "LEGENDARY"],
    }
    if any(len(cards) < OFFER_SIZE for cards in category_candidates.values()):
        raise ValueError("historical offer requires at least three cards in every rarity bucket")

    eligible_categories = list(category_candidates)
    if pick_number in GUARANTEED_RARE_PLUS_PICKS:
        eligible_categories = [
            category for category in eligible_categories if category in RARE_PLUS_RARITIES
        ]
    category = _weighted_choice(
        rng,
        eligible_categories,
        [RARITY_WEIGHTS[category] for category in eligible_categories],
    )

    remaining = list(category_candidates[category])
    selected: list[object] = []
    while len(selected) < OFFER_SIZE:
        weights = [_historical_offer_weight(card) for card in remaining]
        chosen = _weighted_choice(rng, remaining, weights)
        selected.append(chosen)
        remaining.remove(chosen)
    return tuple(
        str(_historical_field(card, "id", _historical_field(card, "card_id")))
        for card in selected
    )  # type: ignore[return-value]


__all__.append("historical_card_offer")
