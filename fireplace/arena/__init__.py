"""Independent building blocks for the arena draft mode.

The arena flow is intentionally kept outside the match engine.  These modules
only turn the existing card database into immutable draft data, so a later
arena run/session layer can persist the choices and hand the finished deck to
the normal game setup code.
"""

from .draft import card_offer, hero_offer
from .pool import CardInfo, eligible_cards
from .rules import HERO_IDS, LARGE_SETS, SMALL_SETS, validate_sets

__all__ = [
    "CardInfo",
    "HERO_IDS",
    "LARGE_SETS",
    "SMALL_SETS",
    "card_offer",
    "eligible_cards",
    "hero_offer",
    "validate_sets",
]
