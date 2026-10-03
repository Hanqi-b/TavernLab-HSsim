"""Isolated, information-limited engine branches for current-turn search.

Visible effects use Fireplace's rules. Unknown decks, the rival hand and
concealed rival Secrets are inert placeholders, not guesses at their actual
identities. Drawn placeholders cannot be played. A pending choice ends a
branch: deepcopy cannot safely rebind the engine's deferred callback closures.
The real controller resolves that choice and agents replan afterwards.
"""

from __future__ import annotations

import copy
import logging
from contextvars import ContextVar
from types import FunctionType, MethodType

from hearthstone.enums import PlayState, Zone

from . import cards
from .agent_api import ATTACK, END_TURN, Action
from .card import Minion, Secret
from .controller import EntityIndex, execute_action, legal_actions, phase_for
from .exceptions import GameOver
from .observation import build_observation, _secret_kind
from .search_api import SearchUnavailable
from .search_uncertainty import hidden_effect_possible


_LOGGER = logging.getLogger("fireplace.search")
_LOGGER.addHandler(logging.NullHandler())
_LOGGER.propagate = False
_SPECULATING = ContextVar("fireplace_speculating", default=False)


class _SpeculationLogFilter(logging.Filter):
    def filter(self, record):
        return not _SPECULATING.get()


# Action scripts also use the shared engine logger. Suppress those messages
# only in this search context; real actions in other threads keep their logs.
logging.getLogger("fireplace").addFilter(_SpeculationLogFilter())
_LOGGER.addFilter(_SpeculationLogFilter())


class _UnknownCard(Minion):
    ignore_scripts = True

    def __init__(self):
        super().__init__(cards.db["CS2_231"])
        self.id = "UNKNOWN"
        self._events = []
        self.cost = 1000

    def is_playable(self):
        return False


class _UnknownSecret(Secret):
    ignore_scripts = True

    def __init__(self):
        super().__init__(cards.db["EX1_287"])
        self.id = "UNKNOWN"
        self._events = []

    @property
    def events(self):
        return []


class _SearchIndex(EntityIndex):
    def new_entity(self, entity):
        entity.logger = _LOGGER
        super().new_entity(entity)


def _copy_game(game, *, hidden=None):
    # Observers include WebGame timelines and their locks. They must neither
    # be copied nor see speculative effects. A fresh index is installed later.
    memo = {id(game.manager.observers): []}
    for entity in game:
        manager = getattr(entity, "manager", None)
        if manager is not None:
            memo[id(manager.observers)] = []
    if hidden:
        memo.update(hidden)
    try:
        branch = copy.deepcopy(game, memo)
    except Exception as exc:
        raise SearchUnavailable("Cannot isolate the current engine state") from exc
    _check_callbacks(branch, game)
    return branch


def _check_callbacks(branch, original):
    """Reject dynamic functions that deepcopy left attached to live entities."""
    pending = [branch]
    visited = set()
    while pending:
        value = pending.pop()
        if id(value) in visited:
            continue
        visited.add(id(value))
        if value is original or getattr(value, "game", None) is original:
            raise SearchUnavailable("A deferred callback references the live game")
        if isinstance(value, FunctionType):
            captures = list(value.__defaults__ or ())
            captures.extend((value.__kwdefaults__ or {}).values())
            for cell in value.__closure__ or ():
                try:
                    captures.append(cell.cell_contents)
                except ValueError:  # An empty closure cell.
                    pass
            captures_pending = captures[:]
            captures_seen = set()
            while captures_pending:
                capture = captures_pending.pop()
                if id(capture) in captures_seen:
                    continue
                captures_seen.add(id(capture))
                if capture is original or getattr(capture, "game", None) is original:
                    raise SearchUnavailable("A deferred callback references the live game")
                if isinstance(capture, dict):
                    captures_pending.extend(capture.values())
                elif isinstance(capture, (list, tuple, set)):
                    captures_pending.extend(capture)
            pending.extend(captures)
        elif isinstance(value, MethodType):
            pending.append(value.__self__)
        elif isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
        elif not isinstance(value, (type, logging.Logger)) and hasattr(value, "__dict__"):
            pending.extend(vars(value).values())


def _placeholder(card, *, secret=False):
    replacement = _UnknownSecret() if secret else _UnknownCard()
    replacement.entity_id = card.entity_id
    replacement._zone = card.zone
    replacement.play_counter = card.play_counter
    replacement.logger = _LOGGER
    return replacement


class EngineSearchPosition:
    """An immutable search handle; transitions return new isolated positions."""

    def __init__(self, game, viewer_seat, *, actor_seat=None, attacks_only=False,
                 stopped=False, secret_classes=None, uncertain=False):
        self._game = game
        self._viewer_seat = viewer_seat
        self._actor_seat = viewer_seat if actor_seat is None else actor_seat
        self._attacks_only = attacks_only
        self._stopped = stopped
        self._secret_classes = dict(secret_classes or {})
        self._uncertain = bool(uncertain)
        self._index = _SearchIndex(game)

    @classmethod
    def from_game(cls, game, player, *, seed=0):
        if phase_for(game, player) != "MAIN" or any(p.choice for p in game.players):
            raise SearchUnavailable("Forward search starts only at a main-action boundary")
        viewer_seat = next(i for i, p in enumerate(game.players) if p is player)
        root_view = build_observation(game, player)
        hidden = {}
        for participant in game.players:
            for card in participant.deck:
                hidden[id(card)] = _placeholder(card)
            if participant is not player:
                for card in participant.hand:
                    hidden[id(card)] = _placeholder(card)
                for card in participant.secrets:
                    if _secret_kind(card) == "secret":
                        hidden[id(card)] = _placeholder(card, secret=True)
        branch = _copy_game(game, hidden=hidden)
        for participant in branch.players:
            participant.starting_deck = ["UNKNOWN"] * len(participant.starting_deck)
            for card in (*participant.deck, *participant.hand, *participant.secrets):
                if card.id == "UNKNOWN":
                    card.controller = participant
        # Use a search seed, never the live game's future random stream.
        branch.random.seed(seed)
        concealed = [card for card in player.opponent.secrets
                     if _secret_kind(card) == "secret"]
        classes_by_id = {
            card.entity_id: tuple(classes)
            for card, classes in zip(concealed, root_view["opponent"].get("secret_classes", ()))
        }
        return cls(branch, viewer_seat, secret_classes=classes_by_id,
                   uncertain=bool(concealed))

    @property
    def terminal(self):
        actor = self._game.players[self._actor_seat]
        return (self._stopped or self._game.ended
                or self._game.current_player is not actor
                or any(p.choice for p in self._game.players))

    def observation(self):
        viewer = self._game.players[self._viewer_seat]
        view = build_observation(self._game, viewer)
        view["search_terminal"] = self.terminal
        # Only speculative observations carry this flag. A sampled random
        # outcome or an inert hidden Secret cannot certify a winning line.
        view["search_uncertain"] = self._uncertain
        if self._game.ended:
            view["search_outcome"] = {
                PlayState.WON: "win", PlayState.LOST: "loss", PlayState.TIED: "draw",
            }.get(viewer.playstate)
        for hand_card in view["self"].get("hand", ()):
            if hand_card.get("card_id") == "UNKNOWN":
                entity_id = hand_card["entity_id"]
                hand_card.clear()
                hand_card.update(entity_id=entity_id, card_id=None,
                                 type="UNKNOWN", cost=None, unknown=True)
        view["opponent"]["secret_classes"] = [
            list(self._secret_classes.get(card.entity_id, ()))
            for card in viewer.opponent.secrets if _secret_kind(card) == "secret"
        ]
        for secret in view["self"].get("secrets", ()):
            if secret.get("card_id") == "UNKNOWN":
                entity_id = secret["entity_id"]
                secret.clear()
                secret.update(entity_id=entity_id, card_id=None, cost=None, unknown=True)
        return view

    def legal_actions(self):
        if self.terminal:
            return []
        actions = legal_actions(self._game, self._game.players[self._actor_seat])
        if self._attacks_only:
            actions = [a for a in actions if a.type in (ATTACK, END_TURN)]
        return actions

    def transition(self, action, *, seed=None):
        if self.terminal or action not in self.legal_actions():
            raise SearchUnavailable("Unavailable speculative action")
        game = _copy_game(self._game)
        if seed is not None:
            game.random.seed(seed)
        position = type(self)(game, self._viewer_seat, actor_seat=self._actor_seat,
                              attacks_only=self._attacks_only,
                              secret_classes=self._secret_classes,
                              uncertain=self._uncertain)
        if self._attacks_only and action.type == END_TURN:
            position._stopped = True
            return position
        token = _SPECULATING.set(True)
        rng_before = game.random.getstate()
        unknown_before = self._unknown_zones(game)
        hidden_dependency = hidden_effect_possible(game, action)
        try:
            try:
                execute_action(game, game.players[self._actor_seat], action, position._index)
            except GameOver:
                pass
            except Exception as exc:
                raise SearchUnavailable("Cannot model this speculative continuation") from exc
        finally:
            _SPECULATING.reset(token)
        position._uncertain = (
            position._uncertain
            or hidden_dependency
            or game.random.getstate() != rng_before
            or self._unknown_zones(game) != unknown_before
        )
        if action.type == END_TURN:
            position._stopped = True
        return position

    @staticmethod
    def _unknown_zones(game):
        return tuple(
            (card.entity_id, card.zone)
            for participant in game.players
            for card in (*participant.deck, *participant.hand, *participant.secrets,
                         *participant.field)
            if card.id == "UNKNOWN"
        )

    def opponent_attack_position(self):
        if any(p.choice for p in self._game.players):
            raise SearchUnavailable("Cannot invert an unresolved choice")
        game = _copy_game(self._game)
        actor_seat = 1 - self._viewer_seat
        actor = game.players[actor_seat]
        game.current_player = actor
        for character in actor.characters:
            character.num_attacks = 0
            if hasattr(character, "turns_in_play"):
                character.turns_in_play = max(1, character.turns_in_play)
        return type(self)(game, self._viewer_seat, actor_seat=actor_seat,
                          attacks_only=True, secret_classes=self._secret_classes,
                          uncertain=self._uncertain)
