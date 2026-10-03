"""Compact, JSON-safe logs of player decisions.

The engine emits many internal actions while resolving one player decision.
``ActionLog`` records only the value action accepted at the agent boundary,
plus enough initial metadata to identify the game that produced the log.  It
deliberately keeps no references to a ``Game`` or any other engine object.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
import copy
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA_VERSION = 1
_MISSING = object()
_INITIAL_PLAYER_FIELDS = (
    "_start_hand_size",
    "max_hand_size",
    "max_resources",
    "max_deck_size",
    "cant_draw",
    "cant_fatigue",
)


def _utc_now() -> str:
    """Return a compact, unambiguous UTC timestamp for the log."""

    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _json_safe(value: Any) -> Any:
    """Copy a small value tree into values accepted by :mod:`json`.

    Action implementations are expected to return JSON-safe dictionaries.
    This helper still normalizes enum, UUID, tuple, and mapping values so the
    log remains safe when a caller supplies a light test double.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, (uuid.UUID, Path)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError("action log contains a non-JSON value: %r" % (type(value),))


def _card_id(value: Any) -> str | None:
    """Return a card definition id from either an id string or a Card value."""

    if value is None:
        return None
    if isinstance(value, str):
        return value
    card_id = getattr(value, "id", _MISSING)
    if card_id is not _MISSING:
        return None if card_id is None else str(card_id)
    # The public constructor accepts strings or Card objects.  Converting a
    # scalar fallback keeps malformed test fixtures serializable without
    # retaining an engine object in the log.
    if isinstance(value, (int, float, bool)):
        return str(value)
    return str(value)


def _player_name(player: Any) -> str | None:
    name = getattr(player, "name", None)
    return None if name is None else str(name)


def _initial_player_settings(player: Any) -> dict[str, Any]:
    return {
        name: _json_safe(getattr(player, name))
        for name in _INITIAL_PLAYER_FIELDS
        if hasattr(player, name)
    }


def _hero_id(player: Any) -> str | None:
    hero = getattr(player, "hero", None)
    if hero is not None:
        return _card_id(hero)
    return _card_id(getattr(player, "starting_hero", None))


def _deck_values(player: Any) -> list[str | None]:
    """Read the configured deck order without changing the engine state."""

    deck = getattr(player, "starting_deck", _MISSING)
    if deck is _MISSING or deck is None:
        deck = getattr(player, "deck", ())
    try:
        return [_card_id(card) for card in deck]
    except TypeError:
        return []


def _state_value(playstate: Any) -> Any:
    """Normalize a PlayState (or a test double) to a JSON scalar."""

    if isinstance(playstate, Enum):
        return _json_safe(playstate.value)
    if playstate is None or isinstance(playstate, (str, int, float, bool)):
        return playstate
    return str(playstate)


def _state_is_won(playstate: Any) -> bool:
    if isinstance(playstate, Enum):
        name = getattr(playstate, "name", "")
        if name == "WON":
            return True
        playstate = playstate.value
    return playstate == 4 or playstate == "WON"


def _repository_metadata() -> tuple[str | None, bool | None]:
    """Return the current repository revision and dirty state when available."""

    repo_dir = Path(__file__).resolve().parent
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    return revision or None, bool(status.strip())


class ActionLog:
    """Record accepted agent actions and optionally persist them as JSON.

    The log schema is intentionally small and stable.  ``players`` contains
    the input deck order captured at construction.  Once the engine has
    started, ``started`` adds resolved hero/deck fields for configurations
    such as Whizbang and Zayle whose effective deck is chosen during setup.
    """

    schema_version = SCHEMA_VERSION

    def __init__(
        self,
        game: Any,
        *,
        mode: str = "unspecified",
        output_path: str | os.PathLike[str] | None = None,
        game_id: str | uuid.UUID | None = None,
        source_revision: str | None = None,
        seed: Any = None,
        on_save: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.output_path = Path(output_path) if output_path is not None else None
        # ``on_save`` deliberately remains a public attribute.  Account
        # backends construct the log before they have created the archive
        # envelope, then attach the callback once the initial row exists.
        self.on_save = on_save
        self._actions: list[dict[str, Any]] = []
        self._players = self._snapshot_players(game)
        self._first_player_seat: int | None = None
        self._result: dict[str, Any] | None = None
        self._status = "in_progress"
        self._started_at = _utc_now()
        self._finished_at: str | None = None
        self._replay: dict[str, Any] | None = None
        self._checkpoint: dict[str, Any] | None = None
        self._started = False

        if source_revision is None:
            repository_revision, source_dirty = _repository_metadata()
            self._source_revision = repository_revision
            self._source_dirty = source_dirty
        else:
            # An explicit revision is already sufficient metadata for callers
            # that run outside a checkout.  Avoid an unnecessary git probe in
            # that case; dirty state is unknown rather than inferred.
            self._source_revision = str(source_revision)
            self._source_dirty = None
        self._game_id = str(game_id) if game_id is not None else str(uuid.uuid4())
        self._mode = _json_safe(mode)
        if seed is None:
            seed = getattr(game, "seed", None)
        if isinstance(seed, (bytes, bytearray)):
            self._seed = {"type": "bytes", "hex": bytes(seed).hex()}
        else:
            self._seed = _json_safe(seed) if seed is not None else None

        self._save_if_configured()

    @staticmethod
    def _snapshot_players(game: Any) -> list[dict[str, Any]]:
        players = getattr(game, "players", ())
        snapshot = []
        for seat, player in enumerate(players):
            snapshot.append(
                {
                    "seat": seat,
                    "name": _player_name(player),
                    "hero_id": _hero_id(player),
                    "deck_card_ids": _deck_values(player),
                    "is_standard": bool(getattr(player, "is_standard", True)),
                    "initial_settings": _initial_player_settings(player),
                }
            )
        return snapshot

    @staticmethod
    def _seat(game: Any, player: Any) -> int:
        players = list(getattr(game, "players", ()))
        if type(player) is int and 0 <= player < len(players):
            return player
        for seat, candidate in enumerate(players):
            if candidate is player:
                return seat
        raise ValueError("player is not present in game.players")

    def _save_if_configured(self) -> None:
        if self.output_path is not None:
            self.save()
        callback = self.on_save
        if callback is not None:
            # ``to_dict`` already walks the complete value tree.  Keep an
            # additional copy at this boundary so a callback that annotates
            # or retains its argument can never mutate the live log.
            callback(copy.deepcopy(self.to_dict()))

    @staticmethod
    def _checkpoint_for(game: Any, action_count: int) -> dict[str, Any]:
        """Capture deterministic recovery state without retaining engine objects."""

        from .replay_state import normalized_game_state, serialize_rng_state

        random_object = getattr(game, "random", None)
        getstate = getattr(random_object, "getstate", None)
        if not callable(getstate):
            raise ValueError("game has no usable RNG state")
        return {
            "action_count": action_count,
            "state": normalized_game_state(game),
            "rng_state": serialize_rng_state(getstate()),
        }

    def _capture_checkpoint(self, game: Any) -> None:
        """Store the latest state/RNG position after one accepted boundary."""

        random_object = getattr(game, "random", None)
        if not callable(getattr(random_object, "getstate", None)):
            # Lightweight test doubles and historical in-memory callers may
            # not expose the engine RNG.  Their logs remain useful for
            # recording decisions, but cannot claim to support recovery.
            return
        self._checkpoint = self._checkpoint_for(game, len(self._actions))
        if self._replay is not None:
            # Keep replay metadata self-contained for consumers that already
            # treat ``replay`` as the deterministic verification namespace;
            # the top-level copy remains convenient for archive projections.
            self._replay["checkpoint"] = copy.deepcopy(self._checkpoint)

    def before_start(self, game: Any) -> None:
        """Capture the exact input and RNG position immediately before setup.

        A factory may already have consumed ``game.random`` while choosing
        decks.  The seed alone therefore cannot restore the setup stream.
        """

        from .game import Game
        from .replay_state import code_signature, serialize_rng_state

        # A hydrated log already contains the authoritative pre-start RNG
        # position.  Re-recording it here would make a resumed session depend
        # on whatever stream the caller happened to use while constructing its
        # temporary Game.
        if self._replay is None:
            self._players = self._snapshot_players(game)
            self._replay = {
                "format_version": 1,
                "game_class": "fireplace.game.Game" if type(game) is Game else None,
                "code_signature": code_signature(),
                "setup_rng_state": serialize_rng_state(game.random.getstate()),
                "final_state": None,
            }
        self._save_if_configured()

    def started(self, game: Any) -> None:
        """Record setup-derived values after ``game.start()`` has completed."""

        # GameSession invokes ``started`` in its constructor for an already
        # started engine.  A recovered log must retain the original resolved
        # hero/deck (for example, a random setup hero), so only fill those
        # fields on the first call or when a legacy/header-only log lacks them.
        first_start = not self._started
        first_player = getattr(game, "player1", None)
        if first_player is None:
            players = list(getattr(game, "players", ()))
            first_player = next(
                (player for player in players if getattr(player, "first_player", False)),
                getattr(game, "current_player", None),
            )
        if first_start and first_player is not None:
            try:
                self._first_player_seat = self._seat(game, first_player)
            except ValueError:
                self._first_player_seat = None

        players = list(getattr(game, "players", ()))
        for seat, player in enumerate(players):
            if seat >= len(self._players):
                self._players.append(
                    {
                        "seat": seat,
                        "name": _player_name(player),
                        "hero_id": None,
                        "deck_card_ids": [],
                        "is_standard": bool(getattr(player, "is_standard", True)),
                        "initial_settings": _initial_player_settings(player),
                    }
                )
            entry = self._players[seat]
            if first_start or "resolved_hero_id" not in entry:
                entry["resolved_hero_id"] = _hero_id(player)
            if first_start or "resolved_deck_card_ids" not in entry:
                entry["resolved_deck_card_ids"] = _deck_values(player)

        self._started = True
        self._capture_checkpoint(game)

        self._save_if_configured()

    def record(
        self,
        game: Any,
        player: Any,
        phase: Any,
        action: Any,
        turn: Any = None,
    ) -> None:
        """Append one accepted decision using its pre-action context."""

        if not hasattr(action, "to_dict"):
            raise TypeError("action must provide to_dict()")
        action_data = action.to_dict()
        if not isinstance(action_data, Mapping):
            raise TypeError("action.to_dict() must return a mapping")

        entry = {
            "seq": len(self._actions) + 1,
            "turn": _json_safe(getattr(game, "turn", None) if turn is None else turn),
            "player": self._seat(game, player),
            "phase": _json_safe(phase),
            "action": _json_safe(action_data),
        }
        self._actions.append(entry)
        self._capture_checkpoint(game)
        self._save_if_configured()

    def finish(self, game: Any, status: str = "complete") -> None:
        """Store terminal player states and mark the log finished."""

        players = list(getattr(game, "players", ()))
        playstates = [_state_value(getattr(player, "playstate", None)) for player in players]
        winning_seats = [
            seat
            for seat, player in enumerate(players)
            if _state_is_won(getattr(player, "playstate", None))
        ]
        self._result = {
            "winning_seats": winning_seats,
            "playstates": playstates,
        }
        self._status = str(status)
        self._finished_at = _utc_now()
        if self._replay is not None:
            from .replay_state import normalized_game_state

            self._replay["final_state"] = normalized_game_state(game)
        self._capture_checkpoint(game)
        self._save_if_configured()

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        on_save: Callable[[dict[str, Any]], Any] | None = None,
    ) -> "ActionLog":
        """Hydrate a detached log header and accepted action prefix.

        No engine object is reconstructed here.  ``restore_action_log`` owns
        replay validation and only attaches a callback after that validation
        succeeds; keeping this constructor side-effect free makes a corrupt
        archive safe to inspect.
        """

        if not isinstance(value, Mapping):
            raise ValueError("Action log must be a mapping")
        result = cls.__new__(cls)
        result.output_path = None
        result.on_save = on_save
        result._actions = copy.deepcopy(list(value.get("actions", [])))
        result._players = copy.deepcopy(list(value.get("players", [])))
        result._first_player_seat = copy.deepcopy(value.get("first_player_seat"))
        result._result = copy.deepcopy(value.get("result"))
        result._status = str(value.get("status", "in_progress"))
        result._started_at = copy.deepcopy(value.get("started_at"))
        result._finished_at = copy.deepcopy(value.get("finished_at"))
        result._replay = copy.deepcopy(value.get("replay"))
        checkpoint = value.get("checkpoint")
        if checkpoint is None and isinstance(result._replay, Mapping):
            checkpoint = result._replay.get("checkpoint")
        result._checkpoint = copy.deepcopy(checkpoint)
        result._game_id = str(value.get("game_id"))
        result._mode = copy.deepcopy(value.get("mode", "unspecified"))
        result._source_revision = copy.deepcopy(value.get("source_revision"))
        result._source_dirty = copy.deepcopy(value.get("source_dirty"))
        result._seed = copy.deepcopy(value.get("seed")) if "seed" in value else None
        result._started = any(
            isinstance(player, Mapping)
            and ("resolved_hero_id" in player or "resolved_deck_card_ids" in player)
            for player in result._players
        )
        return result

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible representation of this log."""

        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "game_id": self._game_id,
            "mode": self._mode,
            "source_revision": self._source_revision,
            "source_dirty": self._source_dirty,
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "status": self._status,
            "players": self._players,
            "first_player_seat": self._first_player_seat,
            "actions": self._actions,
            "result": self._result,
        }
        if self._checkpoint is not None:
            result["checkpoint"] = self._checkpoint
        if self._replay is not None:
            result["replay"] = self._replay
        if self._seed is not None:
            result["seed"] = self._seed
        return _json_safe(result)

    def save(self, path: str | os.PathLike[str] | None = None) -> Path | None:
        """Atomically write the current log to ``path`` or ``output_path``."""

        target = Path(path) if path is not None else self.output_path
        if target is None:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=".%s." % target.name,
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = stream.name
                json.dump(self.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        except Exception:
            # Ordinary write errors should not leave a litter of temporary
            # files.  BaseException (for example KeyboardInterrupt) bypasses
            # this cleanup and leaves the partial temporary document for
            # inspection while the previous target remains intact.
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
            raise
        return target


__all__ = ["ActionLog", "SCHEMA_VERSION"]
