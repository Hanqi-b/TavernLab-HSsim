from __future__ import annotations

import os.path
from bisect import bisect
from importlib import import_module
from pkgutil import iter_modules
from typing import List, TypeVar, overload
from weakref import WeakKeyDictionary
from xml.etree import ElementTree

from hearthstone.enums import CardType

from .logging import log
from .entity import Entity
from .random_setup import random_class, random_draft


# Autogenerate the list of cardset modules
_cards_module = os.path.join(os.path.dirname(__file__), "cards")
CARD_SETS = [cs for _, cs, ispkg in iter_modules([_cards_module]) if ispkg]
T = TypeVar("T")


# ``play_turn(game)`` predates GameSession and is commonly called once per
# loop iteration by batch scripts.  Keep only the policy's random stream in a
# weak compatibility registry; the GameSession itself remains an explicit,
# short-lived owner for each call and never gets attached to ``Game``.
_legacy_random_agents = WeakKeyDictionary()


class CardList(list[T], Entity):
    def __contains__(self, x: T) -> bool:
        for item in self:
            if x is item:
                return True
        return False

    @overload
    def __getitem__(self, index: int) -> T:
        pass

    @overload
    def __getitem__(self, index: slice) -> CardList[T]:
        pass

    def __getitem__(self, key):
        ret = super().__getitem__(key)
        if isinstance(key, slice):
            return self.__class__(ret)
        return ret

    def __int__(self) -> int:
        # Used in Kettle to easily serialize CardList to json
        return len(self)

    def contains(self, x: T | str) -> bool:
        """
        True if list contains any instance of x
        """
        for item in self:
            if x == item:
                return True
        return False

    def index(self, x: T) -> int:
        for i, item in enumerate(self):
            if x is item:
                return i
        raise ValueError

    def remove(self, x: T):
        for i, item in enumerate(self):
            if x is item:
                del self[i]
                return
        raise ValueError

    def exclude(self, *args, **kwargs):
        if args:
            return self.__class__(e for e in self for arg in args if e is not arg)
        else:
            return self.__class__(
                e for k, v in kwargs.items() for e in self if getattr(e, k) != v
            )

    def filter(self, **kwargs):
        def conditional(e, k, v):
            p = getattr(e, k, 0)
            if hasattr(p, "__iter__"):
                return v in p
            return p == v

        return self.__class__(
            e for k, v in kwargs.items() for e in self if conditional(e, k, v)
        )


def entity_to_xml(entity):
    e = ElementTree.Element("Entity")
    for tag, value in entity.tags.items():
        if value and not isinstance(value, str):
            te = ElementTree.Element("Tag")
            te.attrib["enumID"] = str(int(tag))
            te.attrib["value"] = str(int(value))
            e.append(te)
    return e


def game_state_to_xml(game):
    tree = ElementTree.Element("HSGameState")
    tree.append(entity_to_xml(game))
    for player in game.players:
        tree.append(entity_to_xml(player))
    for entity in game:
        if entity.type in (CardType.GAME, CardType.PLAYER):
            # Serialized those above
            continue
        e = entity_to_xml(entity)
        e.attrib["CardID"] = entity.id
        tree.append(e)

    return ElementTree.tostring(tree)


def weighted_card_choice(source, weights: List[int], card_sets: List[str], count: int):
    """
    Take a list of weights and a list of card pools and produce
    a random weighted sample without replacement.
    len(weights) == len(card_sets) (one weight per card set)
    """

    chosen_cards = []

    # sum all the weights
    cum_weights = []
    totalweight = 0
    for i, w in enumerate(weights):
        totalweight += w * len(card_sets[i])
        cum_weights.append(totalweight)

    if totalweight == 0:
        return []

    # for each card
    for i in range(count):
        # choose a set according to weighting
        chosen_set = bisect(cum_weights, source.game.random.random() * totalweight)

        # choose a random card from that set
        chosen_card_index = source.game.random.randint(
            0, len(card_sets[chosen_set]) - 1
        )

        chosen_cards.append(card_sets[chosen_set].pop(chosen_card_index))
        totalweight -= weights[chosen_set]
        cum_weights[chosen_set:] = [
            x - weights[chosen_set] for x in cum_weights[chosen_set:]
        ]

    return [source.controller.card(card, source=source) for card in chosen_cards]


def setup_game(seed=None, start=True):
    """Build the historical random batch game entry point.

    The actual construction lives in :mod:`fireplace.match_factory` so the
    web and terminal entry points consume the same seeded setup stream.
    """
    from .match_factory import build_random_game

    game, _player1, _player2 = build_random_game(
        seed, player_names=("Player1", "Player2"), start=start
    )
    return game


def play_turn(game, session=None):
    """Play decisions until the current player changes.

    ``session`` is optional for compatibility with the historical helper.
    Long-running callers should keep and pass one explicitly so the policy
    state and action-log ownership remain outside the engine ``Game`` object.
    """
    from .agents import RandomAgent

    temporary_session = session is None
    if session is None:
        from .controller import GameSession

        # Keep policy choices on their own stream. Replaying recorded actions
        # skips those policy draws, so sharing ``game.random`` would shift
        # every later engine decision.
        agent = _legacy_random_agents.get(game)
        if agent is None:
            agent = RandomAgent(seed=getattr(game, "seed", None))
            _legacy_random_agents[game] = agent
        session = GameSession(game, {player: agent for player in game.players})
    elif session.game is not game:
        raise ValueError("session belongs to a different game")

    try:
        session.run_turn()
    finally:
        if temporary_session:
            session.close()
            if game.ended:
                _legacy_random_agents.pop(game, None)
    return game


def play_full_game(seed=None, action_log=None):
    """Run a seeded random match until its terminal action.

    The terminal action is recorded and then raises ``GameOver`` for
    compatibility with the historical batch entry point.  The return below
    remains a defensive fallback for an engine that reaches a completed state
    without raising that signal.
    """
    from .agents import RandomAgent
    from .action_log import ActionLog
    from .controller import GameSession

    game = setup_game(seed=seed, start=False)
    # The game RNG is reserved for setup and engine effects.  The policy gets
    # a separate deterministic stream when a seed was supplied.
    agent = RandomAgent(seed=seed)
    if action_log is None:
        action_log = ActionLog(game, seed=seed)
    elif isinstance(action_log, (str, os.PathLike)):
        action_log = ActionLog(game, output_path=action_log, seed=seed)
    session = GameSession(
        game, {player: agent for player in game.players}, action_log=action_log
    )
    try:
        while not game.ended:
            session.run_turn()
    finally:
        session.close()

    return game
