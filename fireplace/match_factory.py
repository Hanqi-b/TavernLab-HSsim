"""Shared construction for seeded random Fireplace matches.

The web UI, source examples, and batch helpers all need the same setup
ordering: construct the game before making class and deck choices so those
choices consume the game-owned random stream, then let ``Game.start`` consume
the next part of that stream. Keeping that ordering here prevents the entry
points from drifting apart.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import cards
from .game import Game
from .player import Player
from .random_setup import random_class, random_draft


DEFAULT_PLAYER_NAMES = ("Player1", "Player2")


def build_random_game(
    seed=None,
    *,
    player_names: Sequence[str] = DEFAULT_PLAYER_NAMES,
    start: bool = False,
) -> tuple[Game, Player, Player]:
    """Build a two-player random match from one deterministic setup flow.

    ``start`` is false by default so callers can construct their
    ``GameSession`` and action log before Fireplace creates the initial state.
    The game and its players are still fully wired together; only
    ``Game.start`` is deferred.
    """

    names = tuple(player_names)
    if len(names) != 2:
        raise ValueError("player_names must contain exactly two names")

    if not cards.db.initialized:
        cards.db.initialize()

    # Placeholder values are replaced below before Game.start prepares the
    # players.  Constructing the players before Game is important: Game then
    # owns their references from the beginning instead of receiving a
    # post-construction mutation of ``players``.
    players = (
        Player(names[0], [], "HERO_01"),
        Player(names[1], [], "HERO_01"),
    )
    game = Game(players, seed=seed)

    card_classes = [random_class(game) for _player in players]
    for player, card_class in zip(players, card_classes):
        player.starting_hero = card_class.default_hero

    for player, card_class in zip(players, card_classes):
        player.starting_deck = random_draft(card_class, game=game)

    if start:
        game.start()

    return game, players[0], players[1]


__all__ = ["DEFAULT_PLAYER_NAMES", "build_random_game"]
