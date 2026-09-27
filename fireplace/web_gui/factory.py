"""Game construction shared by the installed web GUI and source example."""

from __future__ import annotations

from fireplace.game import Game
from fireplace.match_factory import build_random_game
from fireplace.player import Player
from fireplace.random_setup import random_class, random_draft


def build_game(
    seed: int | None = None,
    opponent_name: str = "Heuristic",
    nickname: str = "Human",
) -> tuple[Game, Player, Player]:
    """Create the same seeded random match used by the terminal example.

    The web GUI must also work from an installed wheel, where the repository's
    ``examples`` directory is not available.  Keeping this small factory in
    the package preserves the existing game setup without importing example
    modules from an installed application.
    """

    return build_random_game(
        seed,
        player_names=(nickname, opponent_name),
    )


def build_saved_deck_game(
    *,
    seed: int | None,
    nickname: str,
    opponent_name: str,
    hero_id: str,
    card_ids: list[str],
) -> tuple[Game, Player, Player]:
    """Use a validated saved deck for the human and draft an AI opponent."""

    from fireplace import cards

    if not cards.db.initialized:
        cards.db.initialize()
    human = Player(nickname, list(card_ids), hero_id)
    opponent = Player(opponent_name, [], "HERO_01")
    game = Game((human, opponent), seed=seed)
    opponent_class = random_class(game)
    opponent.starting_hero = opponent_class.default_hero
    opponent.starting_deck = random_draft(opponent_class, game=game)
    return game, human, opponent


__all__ = ["build_game", "build_saved_deck_game"]
