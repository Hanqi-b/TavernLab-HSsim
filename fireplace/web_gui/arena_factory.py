"""Build one battle from a completed Arena draft."""

from __future__ import annotations

from fireplace import cards
from fireplace.arena.pool import eligible_cards
from fireplace.arena.rules import HERO_IDS
from fireplace.game import Game
from fireplace.player import Player


def _card_id(value: object) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "id"):
        return str(value.id)
    return str(value["id"])


def build_arena_game(
    *,
    seed: int,
    nickname: str,
    hero_id: str,
    deck: list[str],
    selected_sets: tuple[str, ...],
    ai_draft: object | None = None,
) -> tuple[Game, Player, Player]:
    """Return a configured game; ``WebGame`` starts its session afterward."""

    if hero_id not in HERO_IDS or len(deck) != 30:
        raise ValueError("Arena requires a classic hero and a 30-card deck")
    if not cards.db.initialized:
        cards.db.initialize()
    human = Player(nickname, list(deck), hero_id)
    opponent = Player("MCTS", [], "HERO_01")
    game = Game((human, opponent), seed=seed)
    if ai_draft is not None:
        from fireplace.arena.ai_draft import AIDraft
        prepared = AIDraft.from_dict(ai_draft)
        opponent.starting_hero = prepared.hero_id
        opponent.starting_deck = list(prepared.deck)
        return game, human, opponent
    opponent_heroes = [candidate for candidate in HERO_IDS if candidate != hero_id]
    opponent_hero = game.random.choice(opponent_heroes)
    opponent_pool = eligible_cards(selected_sets, opponent_hero)
    if not opponent_pool:
        raise ValueError("selected Arena sets have no opponent cards")
    opponent.starting_hero = opponent_hero
    opponent.starting_deck = [
        _card_id(game.random.choice(opponent_pool)) for _ in range(30)
    ]
    return game, human, opponent


__all__ = ["build_arena_game"]
