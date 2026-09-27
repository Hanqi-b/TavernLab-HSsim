"""Random class and deck selection used by match construction entry points."""

from __future__ import annotations

import random

from hearthstone.enums import CardClass, CardType


def random_draft(card_class: CardClass, exclude=[], include=[], game=None):
    """Return a deck of 30 random cards for the ``card_class``."""

    from . import cards
    from .deck import Deck

    deck = list(include)
    collection = []

    for card in cards.db.keys():
        if card in exclude:
            continue
        cls = cards.db[card]
        if not cls.collectible:
            continue
        if cls.type == CardType.HERO:
            # Heroes are collectible...
            continue
        if cls.card_class and cls.card_class not in [card_class, CardClass.NEUTRAL]:
            # Play with more possibilities
            continue
        collection.append(cls)

    while len(deck) < Deck.MAX_CARDS:
        if game:
            card = game.random.choice(collection)
        else:
            card = random.choice(collection)
        if deck.count(card.id) < card.max_count_in_deck:
            deck.append(card.id)

    return deck


def random_class(game=None):
    if game:
        return CardClass(game.random.randint(2, 10))
    return CardClass(random.randint(2, 10))


__all__ = ["random_class", "random_draft"]
