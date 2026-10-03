"""Replay a complete decision log from the beginning of a standard game."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from . import cards
from .action_log import ActionLog, _INITIAL_PLAYER_FIELDS
from .agent_api import Action
from .controller import ActionError, GameSession, decision_player, phase_for
from .exceptions import GameOver
from .game import Game
from .player import Player
from .replay_state import (
    code_signature,
    normalized_game_state,
    restore_rng_state,
    serialize_rng_state,
)


class ReplayError(ValueError):
    """A log cannot be replayed or diverges from its recorded game."""


def _load_log(value: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(value, (str, Path)):
        try:
            with Path(value).open(encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayError("Cannot read action log: %s" % exc) from exc
    if not isinstance(value, dict):
        raise ReplayError("Action log must be a JSON object")
    return value


def _first_difference(expected: Any, actual: Any, path: str = "state") -> str | None:
    if type(expected) is not type(actual):
        return path
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return path + ".keys"
        for key in expected:
            difference = _first_difference(expected[key], actual[key], path + "." + str(key))
            if difference is not None:
                return difference
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return path + ".length"
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = _first_difference(left, right, path + "[%d]" % index)
            if difference is not None:
                return difference
    elif expected != actual:
        return path
    return None


def _validate_setup(
    session: GameSession,
    log: dict[str, Any],
    player_data: list[dict[str, Any]],
) -> None:
    """Verify setup results against the values captured by the source log."""

    game = session.game
    first_player = log.get("first_player_seat")
    if type(first_player) is not int or first_player != game.players.index(game.player1):
        raise ReplayError("First player diverged during setup")
    actual_players = session.action_log.to_dict().get("players", [])
    if not isinstance(actual_players, list) or len(actual_players) != len(player_data):
        raise ReplayError("Player setup diverged")
    for seat, entry in enumerate(player_data):
        actual = actual_players[seat]
        if (
            entry.get("resolved_hero_id") != actual.get("resolved_hero_id")
            or entry.get("resolved_deck_card_ids")
            != actual.get("resolved_deck_card_ids")
        ):
            raise ReplayError("Player %d setup diverged" % seat)


def _apply_actions(
    session: GameSession,
    log: dict[str, Any],
    actions: list[Any],
) -> None:
    """Apply an accepted action prefix while checking its exact contexts."""

    game = session.game
    for index, entry in enumerate(actions, 1):
        if (
            not isinstance(entry, dict)
            or type(entry.get("seq")) is not int
            or entry["seq"] != index
        ):
            raise ReplayError("Invalid action sequence at entry %d" % index)
        player = decision_player(game)
        if player is None:
            raise ReplayError("Action %d occurs after game over" % index)
        seat = game.players.index(player)
        phase = phase_for(game, player)
        if (
            entry.get("player") != seat
            or entry.get("turn") != game.turn
            or entry.get("phase") != phase
        ):
            raise ReplayError("Action %d context diverged (turn/player/phase)" % index)
        try:
            action = Action.from_dict(entry.get("action"))
            session.execute(player, action)
        except GameOver:
            if index != len(actions):
                raise ReplayError("Action %d ended the game before the log ended" % index)
        except (ActionError, ValueError, TypeError) as exc:
            raise ReplayError("Action %d diverged: %s" % (index, exc)) from exc


def _checkpoint_from_log(log: Mapping[str, Any]) -> dict[str, Any]:
    """Read the deterministic recovery checkpoint."""

    checkpoint = log.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ReplayError("Action log has no recovery checkpoint")
    if type(checkpoint.get("action_count")) is not int:
        raise ReplayError("Action log has an invalid recovery checkpoint")
    if not isinstance(checkpoint.get("state"), dict):
        raise ReplayError("Action log has no normalized recovery state")
    if not isinstance(checkpoint.get("rng_state"), list):
        raise ReplayError("Action log has no recovery RNG state")
    return checkpoint


def _validate_checkpoint(
    log: Mapping[str, Any], game: Game, action_count: int
) -> None:
    checkpoint = _checkpoint_from_log(log)
    if checkpoint["action_count"] != action_count:
        raise ReplayError("Recovery checkpoint action count diverged")
    actual_state = normalized_game_state(game)
    difference = _first_difference(checkpoint["state"], actual_state)
    if difference is not None:
        raise ReplayError("Recovery normalized state diverged at %s" % difference)
    actual_rng = serialize_rng_state(game.random.getstate())
    difference = _first_difference(checkpoint["rng_state"], actual_rng, "rng_state")
    if difference is not None:
        raise ReplayError("Recovery RNG state diverged at %s" % difference)


def _replay_session(
    session: GameSession,
    log: dict[str, Any],
    replay: dict[str, Any],
    player_data: list[dict[str, Any]],
    actions: list[Any],
) -> Game:
    """Apply and verify a log through one owned replay session."""

    game = session.game
    try:
        session.start()
    except Exception as exc:
        raise ReplayError("Game setup diverged: %s" % exc) from exc

    _validate_setup(session, log, player_data)
    _apply_actions(session, log, actions)

    if not game.ended:
        raise ReplayError("Action log ended before the game")
    actual_result = session.action_log.to_dict()["result"]
    if actual_result != log.get("result"):
        raise ReplayError("Final result diverged")
    actual_state = normalized_game_state(game)
    difference = _first_difference(replay["final_state"], actual_state)
    if difference is not None:
        raise ReplayError("Final normalized state diverged at %s" % difference)
    if "checkpoint" in log or (
        isinstance(replay, Mapping) and "checkpoint" in replay
    ):
        _validate_checkpoint(log, game, len(actions))
    return game


def replay_action_log(value: Mapping[str, Any] | str | Path) -> Game:
    """Recreate a complete standard game and verify its normalized final state.

    Logs made by attaching to an already-started game cannot be replayed:
    they have no pre-setup RNG state.  Source and dependency versions must
    match the logging process exactly.
    """

    log = _load_log(value)
    if type(log.get("schema_version")) is not int or log["schema_version"] != 1:
        raise ReplayError("Unsupported action log schema_version")
    if log.get("status") != "complete":
        raise ReplayError("Replay requires a complete action log")
    replay = log.get("replay")
    if not isinstance(replay, dict) or replay.get("format_version") != 1:
        raise ReplayError("Action log has no supported replay metadata")
    if replay.get("game_class") != "fireplace.game.Game":
        raise ReplayError("Replay supports standard fireplace.game.Game only")
    if replay.get("code_signature") != code_signature():
        raise ReplayError("Game code or dependency version differs from the log")
    if not isinstance(replay.get("setup_rng_state"), list):
        raise ReplayError("Action log has no pre-start RNG state")
    if not isinstance(replay.get("final_state"), dict):
        raise ReplayError("Action log has no normalized final state")

    player_data = log.get("players")
    players = _restore_players(log)

    actions = log.get("actions")
    if not isinstance(actions, list):
        raise ReplayError("Action log actions must be a list")
    cards.db.initialize()
    # The captured pre-start state is authoritative.  The provenance seed may
    # be bytes or may have been consumed while drafting before it was saved.
    game = Game(tuple(players))
    try:
        game.random.setstate(restore_rng_state(replay["setup_rng_state"]))
    except (TypeError, ValueError) as exc:
        raise ReplayError("Invalid pre-start RNG state") from exc
    session = GameSession(game, {})
    try:
        return _replay_session(session, log, replay, player_data, actions)
    finally:
        session.close()


def _restore_players(log: Mapping[str, Any]) -> list[Player]:
    """Build the same initial player configurations used by full replay."""

    player_data = log.get("players")
    if not isinstance(player_data, list) or len(player_data) != 2:
        raise ReplayError("Action log requires two player configurations")
    players: list[Player] = []
    for seat, entry in enumerate(player_data):
        if not isinstance(entry, dict) or entry.get("seat") != seat:
            raise ReplayError("Invalid player seat %d" % seat)
        name, hero, deck = (
            entry.get("name"),
            entry.get("hero_id"),
            entry.get("deck_card_ids"),
        )
        if (
            not isinstance(name, str)
            or not isinstance(hero, str)
            or not isinstance(deck, list)
            or not all(isinstance(card, str) for card in deck)
        ):
            raise ReplayError("Invalid player configuration at seat %d" % seat)
        is_standard = entry.get("is_standard", True)
        if type(is_standard) is not bool:
            raise ReplayError("Invalid is_standard at seat %d" % seat)
        settings = entry.get("initial_settings")
        if not isinstance(settings, dict) or set(settings) != set(_INITIAL_PLAYER_FIELDS):
            raise ReplayError("Invalid initial player settings at seat %d" % seat)
        for field in _INITIAL_PLAYER_FIELDS:
            expected_type = bool if field in ("cant_draw", "cant_fatigue") else int
            if type(settings[field]) is not expected_type:
                raise ReplayError("Invalid %s at seat %d" % (field, seat))
        player = Player(name, deck[:], hero, is_standard=is_standard)
        for field in _INITIAL_PLAYER_FIELDS:
            setattr(player, field, settings[field])
        players.append(player)
    return players


def _validate_recovery_header(
    log: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[Player]]:
    """Validate common replay metadata for an in-progress recovery."""

    if type(log.get("schema_version")) is not int or log["schema_version"] != 1:
        raise ReplayError("Unsupported action log schema_version")
    if log.get("status") != "in_progress":
        raise ReplayError("Recovery requires an in-progress action log")
    replay = log.get("replay")
    if not isinstance(replay, dict) or replay.get("format_version") != 1:
        raise ReplayError("Action log has no supported replay metadata")
    if replay.get("game_class") != "fireplace.game.Game":
        raise ReplayError("Replay supports standard fireplace.game.Game only")
    if replay.get("code_signature") != code_signature():
        raise ReplayError("Game code or dependency version differs from the log")
    if not isinstance(replay.get("setup_rng_state"), list):
        raise ReplayError("Action log has no pre-start RNG state")
    player_data = log.get("players")
    if not isinstance(player_data, list) or len(player_data) != 2:
        raise ReplayError("Action log requires two player configurations")
    # Keep validation and construction in one place while returning the
    # original dictionaries used for resolved setup comparison.
    players = _restore_players(log)
    return replay, player_data, players


def restore_action_log(
    value: Mapping[str, Any] | str | Path,
    on_save=None,
) -> GameSession:
    """Restore a live session from a validated in-progress action prefix.

    The accepted prefix is replayed into a fresh engine Game.  The hydrated
    ActionLog is attached only after setup, every action context, normalized
    state, and RNG position have all matched the archive checkpoint.
    """

    log = _load_log(value)
    replay, player_data, players = _validate_recovery_header(log)
    actions = log.get("actions")
    if not isinstance(actions, list):
        raise ReplayError("Action log actions must be a list")
    # The first durable archive may precede game.start().  Its pre-start RNG
    # and player configuration are enough to initialize the same game.  A
    # missing checkpoint in any already-started log remains a corruption.
    pre_start = (
        not actions
        and log.get("checkpoint") is None
        and replay.get("checkpoint") is None
        and replay.get("final_state") is None
        and log.get("first_player_seat") is None
        and log.get("result") is None
        and log.get("finished_at") is None
        and all(
            "resolved_hero_id" not in player
            and "resolved_deck_card_ids" not in player
            for player in player_data
        )
    )
    if not pre_start:
        _checkpoint_from_log(log)
    cards.db.initialize()
    game = Game(tuple(players))
    try:
        game.random.setstate(restore_rng_state(replay["setup_rng_state"]))
    except (TypeError, ValueError) as exc:
        raise ReplayError("Invalid pre-start RNG state") from exc

    # Replay through a throw-away log so executing the prefix cannot mutate
    # the archive-backed log before validation succeeds.  This also handles
    # the terminal record/finish crash window safely.
    replay_log = ActionLog(game)
    session = GameSession(game, {}, action_log=replay_log)
    hydrated = ActionLog.from_dict(log)
    repaired = pre_start
    try:
        session.start()
        if pre_start:
            hydrated.started(game)
        else:
            _validate_setup(session, log, player_data)
            _apply_actions(session, log, actions)
            _validate_checkpoint(log, game, len(actions))
        if game.ended:
            # ``status=in_progress`` with a terminal checkpoint means the
            # action record was durable while finish() was interrupted.
            hydrated.finish(game)
            repaired = True
        session.action_log = hydrated
        if on_save is not None:
            hydrated.on_save = on_save
            if repaired:
                on_save(hydrated.to_dict())
        return session
    except ReplayError:
        session.close()
        raise
    except Exception as exc:
        session.close()
        raise ReplayError("Action log recovery diverged: %s" % exc) from exc


__all__ = ["ReplayError", "replay_action_log", "restore_action_log"]
