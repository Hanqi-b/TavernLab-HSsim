"""Small helpers for account-scoped match archives.

The archive file format and engine restore implementation are shared contracts.
This module centralises strict UUID/privacy checks and the known-agent state
projection used by the web GUI.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Mapping
from typing import Any, Callable

from hearthstone.enums import State


_MCTS_LEGACY_POLICY = "legacy_v1"
_MCTS_TACTICAL_POLICY = "tactical_v2"


class ArchivePersistenceError(RuntimeError):
    """The live match changed but its durable archive could not be updated."""


def canonical_game_id(value: object) -> str:
    """Validate and canonicalise one UUID used by the HTTP archive API."""

    if not isinstance(value, str):
        raise ValueError("game_id must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("game_id must be a canonical UUID") from exc
    canonical = str(parsed)
    if value != canonical:
        raise ValueError("game_id must be a canonical UUID")
    return canonical


def as_envelope(value: object) -> dict[str, Any]:
    """Return a detached mapping for a store envelope."""

    if not isinstance(value, Mapping):
        raise ValueError("invalid match archive envelope")
    return copy.deepcopy(dict(value))


def envelope_log(envelope: object) -> dict[str, Any]:
    value = envelope.get("log") if isinstance(envelope, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError("match archive has no action log")
    return copy.deepcopy(dict(value))


def envelope_metadata(envelope: object) -> dict[str, Any]:
    value = envelope.get("metadata", {}) if isinstance(envelope, Mapping) else {}
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def envelope_public(envelope: object) -> dict[str, Any]:
    value = envelope.get("public", {}) if isinstance(envelope, Mapping) else {}
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def envelope_revision(envelope: object) -> int:
    value = envelope.get("revision", 0) if isinstance(envelope, Mapping) else 0
    if type(value) is not int or value < 1:
        raise ValueError("match archive has invalid revision")
    return value


def log_status(log: Mapping[str, Any]) -> str:
    value = log.get("status")
    if value in ("complete", "abandoned"):
        return str(value)
    return "in_progress"


def checkpoint_is_terminal(log: Mapping[str, Any]) -> bool:
    """Return whether an unfinished log has already reached game over.

    ``ActionLog.record`` checkpoints the engine state before its terminal
    ``finish`` write.  A crash in that small window leaves ``status`` as
    ``in_progress`` even though the durable checkpoint is a completed game;
    treating that row as an abandonment would discard the recorded winner.
    """

    checkpoint = log.get("checkpoint")
    if not isinstance(checkpoint, Mapping):
        replay = log.get("replay")
        checkpoint = replay.get("checkpoint") if isinstance(replay, Mapping) else None
    if not isinstance(checkpoint, Mapping):
        return False
    state = checkpoint.get("state")
    if not isinstance(state, Mapping):
        return False
    value = state.get("state")
    return value == State.COMPLETE or value == State.COMPLETE.value


def envelope_status(envelope: object) -> str:
    metadata = envelope_metadata(envelope)
    if metadata.get("status") == "abandoned":
        return "abandoned"
    return log_status(envelope_log(envelope))


def action_log_dict(log: object) -> dict[str, Any]:
    if isinstance(log, Mapping):
        return copy.deepcopy(dict(log))
    to_dict = getattr(log, "to_dict", None)
    if not callable(to_dict):
        raise TypeError("action log must provide to_dict()")
    value = to_dict()
    if not isinstance(value, Mapping):
        raise TypeError("action log to_dict() must return a mapping")
    return copy.deepcopy(dict(value))


def attach_on_save(log: object, callback: Callable[..., object]) -> None:
    """Attach the engine callback through ActionLog's stable public field."""

    setattr(log, "on_save", callback)


def capture_agent_state(agent: object) -> object | None:
    """Capture only the engine's validated, known-agent state if available."""

    from ..mcts_agent import MCTSAgent
    from ..radical_agent import RadicalAgent
    from ..replay_state import serialize_rng_state

    if isinstance(agent, MCTSAgent):
        kind = "mcts"
    elif isinstance(agent, RadicalAgent):
        kind = "radical"
    else:
        # HeuristicAgent has no mutable RNG/search state.  Keep a known kind
        # marker so restore cannot deserialize arbitrary Python objects.
        from ..heuristic_agent import HeuristicAgent

        if isinstance(agent, HeuristicAgent):
            return {"kind": "heuristic"}
        return None

    state: dict[str, Any] = {
        "kind": kind,
        "seed": int(getattr(agent, "seed", 0)),
        "turn_key": list(getattr(agent, "_turn_key", ()))
        if getattr(agent, "_turn_key", None) is not None
        else None,
        "turn_actions": int(getattr(agent, "_turn_actions", 0)),
    }
    random_object = getattr(agent, "random", None)
    if kind == "mcts":
        policy_version = getattr(agent, "policy_version", _MCTS_LEGACY_POLICY)
        if not isinstance(policy_version, str) or not policy_version:
            raise ValueError("MCTS opponent has an invalid policy version")
        export_config = getattr(agent, "export_config", None)
        if not callable(export_config):
            raise ValueError("MCTS opponent has no exportable search configuration")
        try:
            search_config = export_config()
        except (TypeError, ValueError) as exc:
            raise ValueError("MCTS opponent has an invalid search configuration") from exc
        if not isinstance(search_config, Mapping):
            raise ValueError("MCTS opponent has an invalid search configuration")
        state["policy_version"] = policy_version
        state["search_config"] = copy.deepcopy(dict(search_config))
        if random_object is None or not callable(getattr(random_object, "getstate", None)):
            raise ValueError("MCTS opponent has no usable RNG state")
        state["random_state"] = serialize_rng_state(random_object.getstate())
    return state


def restore_agent_state(agent: object, state: object) -> None:
    """Restore a known agent through an engine supplied validator."""

    from ..mcts_agent import MCTSAgent
    from ..radical_agent import RadicalAgent
    from ..replay_state import restore_rng_state

    if not isinstance(state, Mapping) or not isinstance(state.get("kind"), str):
        raise ValueError("invalid archived opponent state")
    expected = "mcts" if isinstance(agent, MCTSAgent) else "radical" if isinstance(agent, RadicalAgent) else "heuristic"
    if state["kind"] != expected:
        raise ValueError("archived opponent kind does not match the match")
    if expected == "heuristic":
        return
    seed = state.get("seed")
    if type(seed) is not int or seed != int(getattr(agent, "seed", 0)):
        raise ValueError("archived opponent seed does not match the match")
    turn_key = state.get("turn_key")
    if turn_key is None:
        agent._turn_key = None
    elif (
        isinstance(turn_key, list)
        and len(turn_key) == 2
        and all(item is None or type(item) is int for item in turn_key)
    ):
        agent._turn_key = tuple(turn_key)
    else:
        raise ValueError("invalid archived opponent turn key")
    turn_actions = state.get("turn_actions")
    if type(turn_actions) is not int or turn_actions < 0:
        raise ValueError("invalid archived opponent turn count")
    agent._turn_actions = turn_actions
    random_state = state.get("random_state")
    random_object = getattr(agent, "random", None)
    if expected == "mcts":
        state_policy_version = state.get("policy_version", _MCTS_LEGACY_POLICY)
        actual_policy_version = getattr(agent, "policy_version", _MCTS_LEGACY_POLICY)
        if not isinstance(state_policy_version, str) or not state_policy_version:
            raise ValueError("invalid archived MCTS policy version")
        if not isinstance(actual_policy_version, str) or not actual_policy_version:
            raise ValueError("MCTS opponent has an invalid policy version")
        if state_policy_version != actual_policy_version:
            raise ValueError("archived MCTS policy version does not match the match")

        has_search_config = "search_config" in state
        if actual_policy_version == _MCTS_TACTICAL_POLICY and not has_search_config:
            raise ValueError("archived tactical MCTS state is missing search configuration")
        if has_search_config:
            search_config = state.get("search_config")
            if not isinstance(search_config, Mapping):
                raise ValueError("invalid archived MCTS search configuration")
            export_config = getattr(agent, "export_config", None)
            if not callable(export_config):
                raise ValueError("MCTS opponent has no exportable search configuration")
            try:
                actual_config = export_config()
            except (TypeError, ValueError) as exc:
                raise ValueError("MCTS opponent has an invalid search configuration") from exc
            if not isinstance(actual_config, Mapping):
                raise ValueError("MCTS opponent has an invalid search configuration")
            if dict(search_config) != dict(actual_config):
                raise ValueError("archived MCTS search configuration does not match the match")
        if (
            random_object is None
            or not callable(getattr(random_object, "setstate", None))
            or not isinstance(random_state, list)
        ):
            raise ValueError("invalid archived opponent RNG state")
        try:
            random_object.setstate(restore_rng_state(random_state))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid archived opponent RNG state") from exc


def restore_action_log(log: Mapping[str, Any], *, on_save: Callable[..., object] | None = None):
    """Resolve the engine's strict partial-prefix restore function."""

    from ..replay import restore_action_log

    return restore_action_log(copy.deepcopy(dict(log)), on_save=on_save)


def store_create(store: object, log: object, metadata: Mapping[str, Any], *, agent_state=None, public=None):
    return store.create(
        action_log_dict(log),
        metadata=dict(metadata),
        agent_state=copy.deepcopy(agent_state),
        public=copy.deepcopy(public),
    )


def store_save(
    store: object,
    game_id: str,
    *,
    log: object | None = None,
    metadata: Mapping[str, Any] | None = None,
    agent_state: object | None = None,
    public: Mapping[str, Any] | None = None,
    expected_revision: int | None = None,
):
    kwargs: dict[str, Any] = {"expected_revision": expected_revision}
    if log is not None:
        kwargs["log"] = action_log_dict(log)
    if metadata is not None:
        kwargs["metadata"] = dict(metadata)
    if agent_state is not None:
        kwargs["agent_state"] = copy.deepcopy(agent_state)
    if public is not None:
        kwargs["public"] = copy.deepcopy(dict(public))
    return store.save(game_id, **kwargs)


def store_list(store: object) -> list[dict[str, Any]]:
    rows = store.list()
    if rows is None:
        return []
    return [as_envelope(row) for row in rows]


def store_get(store: object, game_id: str) -> dict[str, Any] | None:
    try:
        value = store.get(game_id)
    except FileNotFoundError:
        return None
    return None if value is None else as_envelope(value)


def store_find_arena(store: object, match_id: str) -> dict[str, Any] | None:
    value = store.find_arena(match_id)
    return None if value is None else as_envelope(value)


def store_mark_abandoned(store: object, game_id: str, expected_revision: int | None = None):
    if expected_revision is None:
        return store.mark_abandoned(game_id)
    return store.mark_abandoned(game_id, expected_revision=expected_revision)


def public_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Store only browser-safe state and event history."""

    return {
        "snapshot": copy.deepcopy(dict(snapshot)),
        "events": copy.deepcopy(snapshot.get("events", [])),
    }


def archive_summary(envelope: object) -> dict[str, Any]:
    """Project a private envelope into the list/detail API summary."""

    row = as_envelope(envelope)
    log = envelope_log(row)
    metadata = envelope_metadata(row)
    public = envelope_public(row)
    players = log.get("players")
    if not isinstance(players, list):
        players = []
    human = players[0] if len(players) > 0 and isinstance(players[0], Mapping) else {}
    opponent = players[1] if len(players) > 1 and isinstance(players[1], Mapping) else {}
    result = log.get("result")
    winning = result.get("winning_seats") if isinstance(result, Mapping) else None
    human_won = True if isinstance(winning, list) and 0 in winning else None
    if isinstance(winning, list) and winning and 0 not in winning:
        human_won = False
    snapshot = public.get("snapshot")
    observation = snapshot.get("observation") if isinstance(snapshot, Mapping) else None
    turn = observation.get("turn") if isinstance(observation, Mapping) else None
    if turn is None:
        agent_state = row.get("agent_state")
        if isinstance(agent_state, Mapping):
            turn = agent_state.get("turn")

    def hero_name(player: Mapping[str, Any]) -> Any:
        fallback = player.get("resolved_hero_id", player.get("hero_id"))
        if isinstance(snapshot, Mapping):
            snapshot_observation = snapshot.get("observation")
            if isinstance(snapshot_observation, Mapping):
                seat = player.get("seat")
                key = "self" if seat == 0 else "opponent" if seat == 1 else None
                if key is not None:
                    projection = snapshot_observation.get(key)
                    if isinstance(projection, Mapping):
                        hero = projection.get("hero")
                        if isinstance(hero, Mapping) and hero.get("name"):
                            return hero.get("name")
        return fallback

    game_id = canonical_game_id(row.get("game_id") or log.get("game_id"))
    status = "abandoned" if metadata.get("status") == "abandoned" else log_status(log)
    finished_at = log.get("finished_at")
    if status == "abandoned" and metadata.get("finished_at") is not None:
        finished_at = metadata.get("finished_at")
    return {
        "game_id": game_id,
        "revision": envelope_revision(row),
        "mode": metadata.get("mode", log.get("mode")),
        "status": status,
        "started_at": log.get("started_at"),
        "finished_at": finished_at,
        "turn": turn,
        "action_count": len(log.get("actions", [])) if isinstance(log.get("actions"), list) else 0,
        "human_name": human.get("name"),
        "opponent_name": opponent.get("name"),
        "human_hero": hero_name(human),
        "opponent_hero": hero_name(opponent),
        "human_won": human_won,
        "resumable": status == "in_progress",
        "downloadable": status in {"complete", "abandoned"},
    }


__all__ = [
    "ArchivePersistenceError",
    "action_log_dict",
    "archive_summary",
    "as_envelope",
    "attach_on_save",
    "capture_agent_state",
    "canonical_game_id",
    "checkpoint_is_terminal",
    "envelope_log",
    "envelope_metadata",
    "envelope_public",
    "envelope_revision",
    "envelope_status",
    "log_status",
    "public_payload",
    "restore_action_log",
    "restore_agent_state",
    "store_create",
    "store_find_arena",
    "store_get",
    "store_list",
    "store_mark_abandoned",
    "store_save",
]
