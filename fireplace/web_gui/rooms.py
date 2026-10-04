"""Shared authenticated human-vs-human room coordinator.

Each :class:`RoomRegistry` room owns one Fireplace ``GameSession`` and one
action revision.  Account IDs select the participant seat at the backend
boundary; request bodies never do.  Two small ``EffectTimeline`` observers
watch the same engine execution and retain independently filtered presentation
frames for the two browser views.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import re
import secrets
import threading
import uuid
from collections import deque
from collections.abc import Mapping
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from hearthstone.enums import PlayState

from .. import cards
from ..action_log import ActionLog
from ..agent_api import Action, CONCEDE
from ..arena.rules import HERO_IDS
from ..controller import ActionError, GameSession, decision_player
from ..exceptions import GameOver
from ..game import Game
from ..match_factory import build_random_game
from ..player import Player
from ..random_setup import random_class, random_draft
from ..replay import ReplayError
from .archive_runtime import restore_action_log
from .assets import AssetService
from .contracts import ASSET_PENDING, WebActionError, WebLifecycleError
from .effect_timeline import EffectTimeline
from .public_events import (
    decorate_visible_cards,
    localize_events,
    project_action,
    visible_card_ids,
)
from .room_store import RoomStore, RoomStoreConflict, RoomStoreCorrupt


_ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CARD_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,128}$")
_LOCALES = frozenset({"zhCN", "enUS"})
_ASSET_KINDS = frozenset({"render", "art", "tile"})
_FRAME_LIMIT = 32
_EVENT_LIMIT = 256


def _validate_account_id(value: object) -> str:
    if not isinstance(value, str) or _ACCOUNT_ID_RE.fullmatch(value) is None:
        raise ValueError("invalid account ID")
    return value


def _validate_locale(value: object) -> str:
    if value not in _LOCALES:
        raise ValueError("locale must be 'zhCN' or 'enUS'")
    return str(value)


def _validate_nickname(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("nickname must be a string")
    nickname = value.strip()
    if not nickname:
        raise ValueError("nickname must not be empty")
    if len(nickname) > 32:
        raise ValueError("nickname must be at most 32 characters")
    return nickname


def _validate_deck_spec(value: object | None) -> dict[str, Any] | None:
    """Validate a backend-resolved deck without consulting browser input.

    ``DeckStore`` performs catalog/class/duplicate validation before passing a
    specification here.  The room boundary still checks shape and bounded
    values so malformed trusted-context data cannot poison a durable room.
    """

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("deck_spec must be an object")
    hero_id = value.get("hero_id")
    card_ids = value.get("card_ids")
    if not isinstance(hero_id, str) or hero_id not in HERO_IDS:
        raise ValueError("deck_spec.hero_id is invalid")
    if not isinstance(card_ids, list) or len(card_ids) > 30:
        raise ValueError("deck_spec.card_ids must contain at most 30 cards")
    if any(
        not isinstance(card_id, str) or _CARD_ID_RE.fullmatch(card_id) is None
        for card_id in card_ids
    ):
        raise ValueError("deck_spec.card_ids contains an invalid card ID")
    return {"hero_id": hero_id, "card_ids": list(card_ids)}


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _game_ended(game: object) -> bool:
    return bool(getattr(game, "ended", False))


def _player_seat(game: object, player: object) -> int:
    for seat, candidate in enumerate(getattr(game, "players", ())):
        if candidate is player:
            return seat
    raise ValueError("player is not in game")


def _build_deck_game(
    seed: int | None,
    names: tuple[str, str],
    specs: tuple[dict[str, Any] | None, dict[str, Any] | None],
) -> tuple[Game, Player, Player]:
    """Build one deterministic game for any combination of saved decks."""

    if specs[0] is None and specs[1] is None:
        return build_random_game(seed, player_names=names)
    if not cards.db.initialized:
        cards.db.initialize()
    players = (
        Player(names[0], [], "HERO_01"),
        Player(names[1], [], "HERO_01"),
    )
    game = Game(players, seed=seed)
    for player, spec in zip(players, specs):
        if spec is not None:
            player.starting_hero = spec["hero_id"]
            player.starting_deck = list(spec["card_ids"])
            continue
        card_class = random_class(game)
        player.starting_hero = card_class.default_hero
        player.starting_deck = random_draft(card_class, game=game)
    return game, players[0], players[1]


def _winning_seats(game: object) -> list[int]:
    seats = []
    for seat, player in enumerate(getattr(game, "players", ())):
        state = getattr(player, "playstate", None)
        state_name = getattr(state, "name", state)
        if str(state_name).upper() == "WON" or state == PlayState.WON:
            seats.append(seat)
    return seats


class _RoomRuntime:
    """One room's shared engine, lock, privacy projections, and history."""

    def __init__(
        self,
        registry: "RoomRegistry",
        record: Mapping[str, Any],
        session: GameSession | None,
    ) -> None:
        self.registry = registry
        self.record = _clone(dict(record))
        self.session = session
        self.lock = threading.RLock()
        self._closed = False
        self._archive_failed: str | None = None
        # ActionLog invokes ``on_save`` from inside GameSession.execute,
        # before the two filtered timelines have completed.  Defer that
        # callback while an action is in flight so the durable row never gets
        # ahead of its public event/frame prefix.
        self._in_action = False
        self._session_id = str(uuid.uuid4())
        self._revision = int(self.record.get("accepted_revision", 0))
        self._status = str(self.record.get("status", "playing"))
        raw_views = self.record.get("views", {})
        self._events: list[list[dict[str, Any]]] = [[], []]
        self._frames: list[deque[dict[str, Any]]] = [
            deque(maxlen=_FRAME_LIMIT),
            deque(maxlen=_FRAME_LIMIT),
        ]
        if isinstance(raw_views, Mapping):
            for seat in (0, 1):
                raw = raw_views.get(str(seat), {})
                if not isinstance(raw, Mapping):
                    continue
                events = raw.get("events", [])
                if isinstance(events, list):
                    self._events[seat] = [
                        _clone(event) for event in events[-_EVENT_LIMIT:] if isinstance(event, Mapping)
                    ]
                frames = raw.get("frames", [])
                if isinstance(frames, list):
                    self._frames[seat].extend(
                        _clone(frame) for frame in frames[-_FRAME_LIMIT:] if isinstance(frame, Mapping)
                    )
        self._terminal_views: dict[str, dict[str, Any]] = {
            str(seat): _clone(value)
            for seat, value in (self.record.get("terminal_views", {}) or {}).items()
            if str(seat) in {"0", "1"} and isinstance(value, Mapping)
        }
        self.players: tuple[object, object] | None = None
        self._timelines: list[EffectTimeline] = []
        if session is not None:
            self.players = tuple(session.game.players)  # type: ignore[assignment]
            if len(self.players) != 2:
                raise ValueError("human room requires exactly two players")
            self._timelines = [
                EffectTimeline(session, self.players[0]),
                EffectTimeline(session, self.players[1]),
            ]
            for timeline in self._timelines:
                timeline.register()

    @property
    def room_id(self) -> str:
        return str(self.record["id"])

    @property
    def status(self) -> str:
        return self._status

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def archive_failed(self) -> str | None:
        return self._archive_failed

    def attach_on_save(self) -> None:
        if self.session is not None:
            self.session.action_log.on_save = self._on_log_save

    def _on_log_save(self, log: Mapping[str, Any]) -> None:
        """Persist each accepted ActionLog checkpoint before returning."""

        with self.lock:
            if self._closed:
                return
            if self._in_action:
                return
            try:
                actions = log.get("actions", []) if isinstance(log, Mapping) else []
                accepted = len(actions) if isinstance(actions, list) else self._revision
                status = "complete" if log.get("status") == "complete" else self._status
                self._persist_locked(
                    {
                        "log": _clone(dict(log)),
                        "accepted_revision": accepted,
                        "status": status,
                    }
                )
            except Exception as exc:
                self._archive_failed = str(exc)
                raise

    def _persist_locked(self, updates: Mapping[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("room is closed")
        saved = self.registry._store.save(
            self.room_id,
            expected_revision=int(self.record["storage_revision"]),
            updates=updates,
        )
        self.record = saved
        self.registry._records[self.room_id] = _clone(saved)
        self._status = str(saved.get("status", self._status))

    def _participant(self, seat: int) -> dict[str, Any]:
        for participant in self.record.get("participants", ()):
            if isinstance(participant, Mapping) and participant.get("seat") == seat:
                return dict(participant)
        raise ValueError("room participant is missing")

    def seat_for(self, account_id: str) -> int | None:
        for participant in self.record.get("participants", ()):
            if (
                isinstance(participant, Mapping)
                and participant.get("account_id") == account_id
                and participant.get("attached", True)
            ):
                return participant.get("seat")
        return None

    def _room_dto(self, seat: int) -> dict[str, Any]:
        return {
            "id": self.room_id,
            "status": self._status,
            "seat": seat,
            "participants": [
                {
                    "seat": int(participant["seat"]),
                    "nickname": str(participant["nickname"]),
                }
                for participant in sorted(
                    self.record.get("participants", ()),
                    key=lambda item: int(item.get("seat", 0)),
                )
                if isinstance(participant, Mapping)
            ],
        }

    def _descriptions(self, card_ids: set[str], locale: str) -> Mapping[str, object]:
        if not card_ids:
            return {}
        try:
            return self.registry._assets.describe_visible(card_ids, locale=locale)
        except Exception:
            return {}

    def _localized_observation(self, observation: object, locale: str) -> object:
        localized = _clone(observation)
        if not isinstance(localized, (dict, list)):
            return localized
        descriptions = self._descriptions(visible_card_ids(localized), locale)
        if descriptions:
            decorate_visible_cards(localized, descriptions)
        return localized

    def _localized_events(self, events: list[Mapping[str, Any]], locale: str) -> list[dict[str, Any]]:
        copied = [_clone(dict(event)) for event in events if isinstance(event, Mapping)]
        card_ids = {
            card_id
            for event in copied
            for key in ("_source_card_id", "_target_card_id")
            if isinstance(card_id := event.get(key), str) and card_id
        }
        return localize_events(copied, self._descriptions(card_ids, locale))

    def _localized_effects(self, effects: list[Mapping[str, Any]], locale: str) -> list[dict[str, Any]]:
        localized: list[dict[str, Any]] = []
        for effect in effects:
            if not isinstance(effect, Mapping):
                continue
            event = effect.get("event")
            if not isinstance(event, Mapping):
                continue
            public_event = self._localized_events([event], locale)[0]
            observation = self._localized_observation(effect.get("observation", {}), locale)
            localized.append({"event": public_event, "observation": observation})
        return localized

    def _outcome(self, seat: int) -> dict[str, Any] | None:
        if self.session is not None:
            if not _game_ended(self.session.game):
                return None
            winners = _winning_seats(self.session.game)
        else:
            log = self.record.get("log")
            result = log.get("result") if isinstance(log, Mapping) else None
            winners = result.get("winning_seats", []) if isinstance(result, Mapping) else []
            if not isinstance(winners, list):
                winners = []
        winner_name = None
        for winner in winners:
            if type(winner) is int and winner in (0, 1):
                winner_name = self._participant(winner).get("nickname")
                break
        return {
            "winner": winner_name,
            "human_won": (seat in winners) if winner_name is not None else None,
        }

    def _snapshot_live_locked(self, seat: int) -> dict[str, Any]:
        assert self.session is not None and self.players is not None
        player = self.players[seat]
        observation = self._localized_observation(
            self.session.observation(player),
            str(self._participant(seat)["locale"]),
        )
        decision = decision_player(self.session.game)
        actions = (
            self.session.legal_actions(player)
            if decision is player
            else []
        )
        locale = str(self._participant(seat)["locale"])
        payload = {
            "mode": "match",
            "session_id": self._session_id,
            "revision": self._revision,
            "locale": locale,
            "nickname": str(self._participant(seat)["nickname"]),
            "observation": observation,
            "legal_actions": [action.to_dict() for action in actions],
            "outcome": self._outcome(seat),
            "events": self._localized_events(self._events[seat], locale),
            "presentation_steps": self._localized_frames(seat, locale),
        }
        payload["frames"] = copy.deepcopy(payload["presentation_steps"])
        payload["room"] = self._room_dto(seat)
        return payload

    def _localized_frames(self, seat: int, locale: str) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        for frame in self._frames[seat]:
            if not isinstance(frame, Mapping):
                continue
            copied = _clone(dict(frame))
            event = copied.get("event")
            if isinstance(event, Mapping):
                copied["event"] = self._localized_events([event], locale)[0]
            copied["observation"] = self._localized_observation(
                copied.get("observation", {}), locale
            )
            if isinstance(copied.get("effects"), list):
                copied["effects"] = self._localized_effects(copied["effects"], locale)
            frames.append(copied)
        return frames

    def _snapshot_terminal_locked(self, seat: int) -> dict[str, Any]:
        saved = self._terminal_views.get(str(seat))
        if saved is None:
            # A process can crash after the terminal ActionLog checkpoint and
            # before its public view.  Keep the room private and useful while
            # making the missing observation explicit rather than restoring a
            # second live engine from a complete log.
            payload: dict[str, Any] = {
                "mode": "match",
                "session_id": self._session_id,
                "revision": self._revision,
                "locale": str(self._participant(seat)["locale"]),
                "nickname": str(self._participant(seat)["nickname"]),
                "observation": {},
                "legal_actions": [],
                "outcome": self._outcome(seat),
                "events": self._localized_events(self._events[seat], str(self._participant(seat)["locale"])),
                "presentation_steps": [],
            }
        else:
            payload = _clone(saved)
            payload["session_id"] = self._session_id
            payload["revision"] = self._revision
            payload["room"] = self._room_dto(seat)
            payload["outcome"] = self._outcome(seat)
        payload["room"] = self._room_dto(seat)
        payload["frames"] = copy.deepcopy(payload.get("presentation_steps", []))
        return payload

    def snapshot(self, account_id: str) -> dict[str, Any]:
        with self.lock:
            seat = self.seat_for(account_id)
            if seat not in (0, 1):
                raise KeyError(account_id)
            if self.session is None:
                return self._snapshot_terminal_locked(int(seat))
            return self._snapshot_live_locked(int(seat))

    def _source_for(self, action: Action) -> object | None:
        if self.session is None or action.type != "PLAY_CARD" or action.source_entity_id is None:
            return None
        try:
            return self.session.index.get(action.source_entity_id)
        except ActionError:
            return None

    def _project_events_locked(
        self,
        player: object,
        action: Action,
        observations: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        source = self._source_for(action)
        return [
            project_action(
                player,
                self.players[seat],  # type: ignore[index]
                action,
                observations[seat],
                seq=self._revision + 1,
                source=source,
            )
            for seat in (0, 1)
        ]

    def _append_presentation_locked(
        self,
        events: list[dict[str, Any]],
        effects: list[list[dict[str, Any]]],
        effects_truncated: list[bool],
    ) -> None:
        assert self.session is not None
        post_observations = [
            self.session.observation(self.players[seat])  # type: ignore[index]
            for seat in (0, 1)
        ]
        outcome = [self._outcome(seat) for seat in (0, 1)]
        for seat in (0, 1):
            self._events[seat].append(_clone(events[seat]))
            del self._events[seat][:-_EVENT_LIMIT]
            frame: dict[str, Any] = {
                "revision": self._revision,
                "observation": _clone(post_observations[seat]),
                "event": _clone(events[seat]),
                "outcome": _clone(outcome[seat]),
                "effects": _clone(effects[seat]),
            }
            if effects_truncated[seat]:
                frame["effects_truncated"] = True
            self._frames[seat].append(frame)

    def _persist_public_locked(self) -> None:
        views = {
            str(seat): {
                "events": _clone(self._events[seat]),
                "frames": _clone(list(self._frames[seat])),
            }
            for seat in (0, 1)
        }
        updates: dict[str, Any] = {
            "status": self._status,
            "accepted_revision": self._revision,
            "log": _clone(self.session.action_log.to_dict()) if self.session is not None else self.record.get("log"),
            "views": views,
        }
        if self._status == "complete":
            updates["terminal_views"] = {
                str(seat): self._snapshot_live_locked(seat) for seat in (0, 1)
            }
        self._persist_locked(updates)
        if self._status == "complete":
            self._terminal_views = {
                str(seat): _clone(self.record.get("terminal_views", {}).get(str(seat), {}))
                for seat in (0, 1)
            }

    def _validate_request_locked(
        self, account_id: str, payload: object
    ) -> tuple[int, dict[str, Any]]:
        current = self.snapshot(account_id)
        if not isinstance(payload, Mapping):
            raise WebActionError("request body must be a JSON object", 400, current)
        if payload.get("session_id") != self._session_id:
            raise WebActionError("stale session", 409, current)
        revision = payload.get("revision")
        if type(revision) is not int:
            raise WebActionError("revision must be an integer", 400, current)
        if revision != self._revision:
            raise WebActionError("stale revision", 409, current)
        seat = self.seat_for(account_id)
        if seat not in (0, 1):
            raise WebActionError("account is not a room participant", 409, current)
        return int(seat), current

    def _execute_locked(
        self, account_id: str, payload: object, *, concession: bool
    ) -> dict[str, Any]:
        if self._archive_failed is not None:
            current = self.snapshot(account_id)
            raise WebActionError(
                "room archive is unavailable; resume from the latest durable checkpoint",
                503,
                current,
            )
        if self.session is None or self.players is None:
            current = self.snapshot(account_id)
            if current.get("outcome") is not None:
                raise WebActionError("match is over", 409, current)
            raise WebActionError("room is unavailable", 503, current)
        seat, current = self._validate_request_locked(account_id, payload)
        if current.get("outcome") is not None:
            raise WebActionError("match is over", 409, current)
        player = self.players[seat]
        if concession:
            action = Action(type=CONCEDE)
        else:
            raw_action = payload.get("action") if isinstance(payload, Mapping) else None
            try:
                action = Action.from_dict(raw_action)
            except (TypeError, ValueError) as exc:
                raise WebActionError(str(exc), 400, current) from exc
            decision = decision_player(self.session.game)
            legal = list(self.session.legal_actions(player)) if decision is player else []
            if decision is not player:
                raise WebActionError("it is not this player's turn", 409, current)
            if action not in legal:
                raise WebActionError("action is unavailable or stale", 409, current)

        observations = [
            self.session.observation(self.players[view_seat])
            for view_seat in (0, 1)
        ]
        try:
            events = self._project_events_locked(player, action, observations)
            for view_seat in (0, 1):
                self._timelines[view_seat].begin(
                    player,
                    observation=observations[view_seat],
                    public_event=events[view_seat],
                )
        except Exception as exc:
            self._archive_failed = str(exc)
            raise WebActionError(
                "room presentation is unavailable; resume from the latest durable checkpoint",
                503,
                self.snapshot(account_id),
            ) from exc
        before = len(self.session.action_log.to_dict().get("actions", []))
        terminal = False
        action_error: ActionError | None = None
        execution_error: Exception | None = None
        collected: list[list[dict[str, Any]]] = [[], []]
        truncated = [False, False]
        presentation_error: Exception | None = None
        self._in_action = True
        try:
            try:
                self.session.execute(player, action)
            except GameOver:
                terminal = True
            except ActionError as exc:
                action_error = exc
            except Exception as exc:
                execution_error = exc
        finally:
            try:
                collected = [timeline.end() for timeline in self._timelines]
                truncated = [timeline.last_truncated for timeline in self._timelines]
            except Exception as exc:
                presentation_error = exc
            finally:
                self._in_action = False

        after = len(self.session.action_log.to_dict().get("actions", []))
        accepted = after > before
        if presentation_error is not None:
            self._archive_failed = str(presentation_error)
            raise WebActionError(
                "room presentation is unavailable; resume from the latest durable checkpoint",
                503,
                self.snapshot(account_id),
            ) from presentation_error
        if action_error is not None and not accepted:
            raise WebActionError(str(action_error), 409, self.snapshot(account_id)) from action_error
        if execution_error is not None and not accepted:
            self._archive_failed = str(execution_error)
            raise WebActionError("room archive is unavailable", 503, self.snapshot(account_id)) from execution_error

        # The GameSession has accepted exactly one action.  Even when its
        # persistence callback failed, record the in-memory projection before
        # freezing further mutations so the caller sees the authoritative
        # state that must be recovered from disk.
        self._revision = after
        self._status = "complete" if _game_ended(self.session.game) or terminal else "playing"
        try:
            self._append_presentation_locked(events, collected, truncated)
            # This is the one durable checkpoint for the accepted action:
            # raw ActionLog, revision, both filtered timelines, and terminal
            # views advance together.  If it fails, freeze the in-memory
            # session; after restart the prior accepted prefix is restored.
            self._persist_public_locked()
        except Exception as exc:
            self._archive_failed = str(exc)
            raise WebActionError(
                "room archive is unavailable; resume from the latest durable checkpoint",
                503,
                self.snapshot(account_id),
            ) from exc
        if execution_error is not None:
            self._archive_failed = str(execution_error)
            raise WebActionError("room archive is unavailable", 503, self.snapshot(account_id)) from execution_error
        return self.snapshot(account_id)

    def handle_action(self, account_id: str, payload: object) -> dict[str, Any]:
        with self.lock:
            return self._execute_locked(account_id, payload, concession=False)

    def concede(self, account_id: str, payload: object) -> dict[str, Any]:
        with self.lock:
            return self._execute_locked(account_id, payload, concession=True)

    def close(self) -> None:
        with self.lock:
            if self._closed:
                return
            self._closed = True
            for timeline in self._timelines:
                timeline.unregister()
            if self.session is not None:
                self.session.close()


class RoomRegistry:
    """Own all server-wide human-vs-human rooms for one local server."""

    def __init__(
        self,
        data_root: Path,
        seed: int | None = None,
        asset_service: AssetService | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        # AccountGameRegistry passes its already-scoped ``users/rooms`` path,
        # while direct callers commonly pass the server ``users`` root.  Keep
        # both forms compatible without creating ``rooms/rooms``.
        room_root = self.data_root if self.data_root.name == "rooms" else self.data_root / "rooms"
        self._store = RoomStore(room_root)
        self._base_seed = seed
        if seed is not None and type(seed) is not int:
            raise ValueError("seed must be an integer or None")
        self._seed_counter = 0
        self._lock = threading.RLock()
        self._closed = False
        self._owner_claimed = False
        self._records: dict[str, dict[str, Any]] = {}
        self._rooms: dict[str, _RoomRuntime] = {}
        self._account_rooms: dict[str, str] = {}
        self._assets = asset_service if asset_service is not None else AssetService()
        self._owns_assets = asset_service is None
        self._refresh_locked()

    def _claim_owner_locked(self) -> None:
        if self._owner_claimed:
            return
        try:
            self._store.acquire_owner()
        except RoomStoreConflict as exc:
            raise WebLifecycleError(
                "room store is open in another local process", 503, {"mode": "lobby"}
            ) from exc
        self._owner_claimed = True

    def _refresh_locked(self) -> None:
        rows = self._store.list()
        records = {str(row["id"]): row for row in rows}
        self._records = records
        self._account_rooms = {}
        max_offset = 0
        for record in rows:
            seed = record.get("seed")
            if self._base_seed is not None and isinstance(seed, int):
                max_offset = max(max_offset, seed - self._base_seed + 1)
            for participant in record.get("participants", ()):
                if not isinstance(participant, Mapping) or not participant.get("attached", True):
                    continue
                account_id = participant.get("account_id")
                if isinstance(account_id, str) and account_id not in self._account_rooms:
                    self._account_rooms[account_id] = str(record["id"])
        self._seed_counter = max(self._seed_counter, max_offset, len(rows))
        for room_id in list(self._rooms):
            if room_id not in records:
                self._rooms.pop(room_id, None)

    @staticmethod
    def _lobby() -> dict[str, Any]:
        return {"mode": "lobby"}

    def _room_for_account_locked(self, account_id: str) -> tuple[str, dict[str, Any]] | None:
        room_id = self._account_rooms.get(account_id)
        if room_id is None:
            return None
        record = self._records.get(room_id)
        if record is None:
            self._account_rooms.pop(account_id, None)
            return None
        return room_id, record

    def _caller_snapshot_locked(self, account_id: str) -> dict[str, Any]:
        current = self._room_for_account_locked(account_id)
        if current is None:
            return self._lobby()
        room_id, record = current
        if record.get("status") == "waiting":
            seat = 0
            participants = record.get("participants", [])
            if participants and isinstance(participants[0], Mapping):
                seat = int(participants[0].get("seat", 0))
            return {
                "mode": "lobby",
                "room": {
                    "id": room_id,
                    "status": "waiting",
                    "seat": seat,
                    "participants": [
                        {"seat": int(item["seat"]), "nickname": str(item["nickname"])}
                        for item in participants
                        if isinstance(item, Mapping)
                    ],
                },
            }
        runtime = self._ensure_runtime_locked(record)
        if runtime is None:
            return self._lobby()
        return runtime.snapshot(account_id)

    def _lifecycle_error_locked(
        self, account_id: str, message: str, status: int
    ) -> WebLifecycleError:
        return WebLifecycleError(message, status, self._caller_snapshot_locked(account_id))

    @staticmethod
    def _participant_record(
        account_id: str, seat: int, nickname: str, locale: str
    ) -> dict[str, Any]:
        return {
            "account_id": account_id,
            "seat": seat,
            "nickname": nickname,
            "locale": locale,
            "attached": True,
        }

    @staticmethod
    def _invite_hash(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _seed_locked(self) -> int | None:
        if self._base_seed is None:
            return None
        value = self._base_seed + self._seed_counter
        self._seed_counter += 1
        return value

    def _ensure_runtime_locked(self, record: Mapping[str, Any]) -> _RoomRuntime | None:
        room_id = str(record["id"])
        runtime = self._rooms.get(room_id)
        if runtime is not None:
            return runtime
        status = record.get("status")
        if status == "waiting":
            return None
        if status == "complete":
            runtime = _RoomRuntime(self, record, None)
            self._rooms[room_id] = runtime
            return runtime
        # A live engine is a process-owned resource.  Claim the room store
        # before restoring it so a second server cannot hydrate the same raw
        # log and accept a competing action stream.
        self._claim_owner_locked()
        log = record.get("log")
        if not isinstance(log, Mapping):
            raise WebLifecycleError("room has no recoverable action log", 503, self._lobby())
        try:
            session = restore_action_log(log)
            runtime = _RoomRuntime(self, record, session)
            runtime.attach_on_save()
        except (ReplayError, ValueError, TypeError, OSError) as exc:
            raise WebLifecycleError(
                "room could not be restored", 503, self._lobby()
            ) from exc
        self._rooms[room_id] = runtime
        return runtime

    def _waiting_payload(self, record: Mapping[str, Any], seat: int) -> dict[str, Any]:
        return {
            "mode": "lobby",
            "room": {
                "id": str(record["id"]),
                "status": "waiting",
                "seat": seat,
                "participants": [
                    {"seat": int(item["seat"]), "nickname": str(item["nickname"])}
                    for item in record.get("participants", [])
                    if isinstance(item, Mapping)
                ],
            },
        }

    def create(
        self,
        account_id: str,
        payload: object,
        deck_spec: object | None = None,
    ) -> dict[str, Any]:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                raise WebLifecycleError("room registry is closed", 503, self._lobby())
            self._refresh_locked()
            if self._room_for_account_locked(account_id) is not None:
                raise self._lifecycle_error_locked(account_id, "account already has a room", 409)
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, self._lobby())
            try:
                nickname = _validate_nickname(payload.get("nickname"))
                locale = _validate_locale(payload.get("locale", "zhCN"))
                deck = _validate_deck_spec(deck_spec)
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, self._lobby()) from exc
            self._claim_owner_locked()
            room_id = uuid.uuid4().hex
            invite_code = secrets.token_urlsafe(24)
            record = {
                "room_store_version": 1,
                "id": room_id,
                "storage_revision": 1,
                "status": "waiting",
                "creator_account_id": account_id,
                "invite_code_hash": self._invite_hash(invite_code),
                "seed": self._seed_locked(),
                "participants": [self._participant_record(account_id, 0, nickname, locale)],
                "deck_specs": [deck, None],
                "accepted_revision": 0,
                "log": None,
                "views": {},
                "terminal_views": {},
            }
            try:
                saved = self._store.create(record)
            except (RoomStoreConflict, RoomStoreCorrupt, OSError, ValueError) as exc:
                raise WebLifecycleError("room storage is unavailable", 503, self._lobby()) from exc
            self._records[room_id] = saved
            self._account_rooms[account_id] = room_id
            result = self._waiting_payload(saved, 0)
            result["room"]["invite_code"] = invite_code
            return result

    def join(
        self,
        account_id: str,
        payload: object,
        deck_spec: object | None = None,
    ) -> dict[str, Any]:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                raise WebLifecycleError("room registry is closed", 503, self._lobby())
            self._refresh_locked()
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, self._lobby())
            try:
                code = payload.get("code", payload.get("invite_code"))
                if not isinstance(code, str) or not code:
                    raise ValueError("code must be a string")
                nickname = _validate_nickname(payload.get("nickname"))
                locale = _validate_locale(payload.get("locale", "zhCN"))
                deck = _validate_deck_spec(deck_spec)
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, self._lobby()) from exc
            current = self._room_for_account_locked(account_id)
            if current is not None:
                _current_id, current_record = current
                own_hash = current_record.get("invite_code_hash")
                if (
                    current_record.get("status") == "waiting"
                    and isinstance(own_hash, str)
                    and hmac.compare_digest(own_hash, self._invite_hash(code))
                ):
                    raise self._lifecycle_error_locked(
                        account_id, "creator cannot join their own room", 409
                    )
                raise self._lifecycle_error_locked(account_id, "account already has a room", 409)
            target = None
            for record in self._records.values():
                if record.get("status") != "waiting":
                    continue
                stored_hash = record.get("invite_code_hash")
                if isinstance(stored_hash, str) and hmac.compare_digest(
                    stored_hash, self._invite_hash(code)
                ):
                    target = record
                    break
            if target is None:
                raise WebLifecycleError("room invitation is invalid", 404, self._lobby())
            room_id = str(target["id"])
            creator = str(target["creator_account_id"])
            if account_id == creator:
                raise self._lifecycle_error_locked(account_id, "creator cannot join their own room", 409)
            self._claim_owner_locked()
            participants = [
                _clone(item) for item in target.get("participants", []) if isinstance(item, Mapping)
            ]
            if len(participants) != 1:
                raise WebLifecycleError("room already has two participants", 409, self._lobby())
            names = (str(participants[0]["nickname"]), nickname)
            specs = (
                _validate_deck_spec(target.get("deck_specs", [None, None])[0]),
                deck,
            )
            try:
                game, _player0, _player1 = _build_deck_game(
                    target.get("seed"), names, specs
                )
                log = ActionLog(
                    game,
                    mode="human_room",
                    game_id=room_id,
                    seed=target.get("seed"),
                )
                # Capture the pre-start RNG/setup checkpoint before publishing
                # the row as ``playing``.  A crash after the CAS publication
                # but before ``session.start()`` must still be restartable.
                log.before_start(game)
                session = GameSession(game, {}, action_log=log)
                updated = _clone(target)
                updated["status"] = "playing"
                updated["participants"] = participants + [
                    self._participant_record(account_id, 1, nickname, locale)
                ]
                updated["deck_specs"] = [specs[0], specs[1]]
                updated["log"] = log.to_dict()
                updated["accepted_revision"] = 0
                saved = self._store.save(
                    room_id,
                    expected_revision=int(target["storage_revision"]),
                    updates={
                        "status": updated["status"],
                        "participants": updated["participants"],
                        "deck_specs": updated["deck_specs"],
                        "log": updated["log"],
                        "accepted_revision": 0,
                    },
                )
                runtime = _RoomRuntime(self, saved, session)
                self._records[room_id] = saved
                self._rooms[room_id] = runtime
                self._account_rooms[creator] = room_id
                self._account_rooms[account_id] = room_id
                runtime.attach_on_save()
                session.start()
            except WebLifecycleError:
                raise
            except Exception as exc:
                # The room row remains waiting if game construction/startup
                # failed before its CAS publication.  A published row is
                # frozen and surfaced as a service failure for safe retry.
                if self._records.get(room_id, {}).get("status") == "playing":
                    raise WebLifecycleError(
                        "room could not be started", 503, self._lobby()
                    ) from exc
                raise WebLifecycleError("room could not be started", 503, self._lobby()) from exc
            return runtime.snapshot(account_id)

    def snapshot(self, account_id: str) -> dict[str, Any] | None:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                return None
            self._refresh_locked()
            current = self._room_for_account_locked(account_id)
            if current is None:
                return None
            _room_id, record = current
            if record.get("status") == "waiting":
                self._claim_owner_locked()
                participant = next(
                    item for item in record.get("participants", []) if item.get("account_id") == account_id
                )
                return self._waiting_payload(record, int(participant["seat"]))
            runtime = self._ensure_runtime_locked(record)
            if runtime is None:
                return None
            return runtime.snapshot(account_id)

    def has_current(self, account_id: str) -> bool:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                return False
            self._refresh_locked()
            return self._room_for_account_locked(account_id) is not None

    def _runtime_for_account_locked(self, account_id: str) -> _RoomRuntime:
        current = self._room_for_account_locked(account_id)
        if current is None:
            raise WebActionError("no active room", 409, self._lobby())
        _room_id, record = current
        if record.get("status") == "waiting":
            raise WebActionError(
                "room is waiting for another participant", 409,
                self._caller_snapshot_locked(account_id),
            )
        runtime = self._ensure_runtime_locked(record)
        if runtime is None:
            raise WebActionError("room is unavailable", 503, self._lobby())
        return runtime

    def handle_action(self, account_id: str, payload: object) -> dict[str, Any]:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                raise WebActionError("room registry is closed", 503, self._lobby())
            self._refresh_locked()
            runtime = self._runtime_for_account_locked(account_id)
            try:
                return runtime.handle_action(account_id, payload)
            except WebActionError:
                raise
            except (RoomStoreConflict, RoomStoreCorrupt, OSError) as exc:
                raise WebActionError("room storage is unavailable", 503, runtime.snapshot(account_id)) from exc

    def concede(self, account_id: str, payload: object) -> dict[str, Any]:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                raise WebActionError("room registry is closed", 503, self._lobby())
            self._refresh_locked()
            runtime = self._runtime_for_account_locked(account_id)
            try:
                return runtime.concede(account_id, payload)
            except WebActionError:
                raise
            except (RoomStoreConflict, RoomStoreCorrupt, OSError) as exc:
                raise WebActionError("room storage is unavailable", 503, runtime.snapshot(account_id)) from exc

    def leave(self, account_id: str, payload: object = None) -> dict[str, Any]:
        account_id = _validate_account_id(account_id)
        with self._lock:
            if self._closed:
                raise WebLifecycleError("room registry is closed", 503, self._lobby())
            self._refresh_locked()
            current = self._room_for_account_locked(account_id)
            if current is None:
                raise self._lifecycle_error_locked(account_id, "no active room", 409)
            room_id, record = current
            if payload is not None and not isinstance(payload, Mapping):
                raise self._lifecycle_error_locked(
                    account_id, "request body must be a JSON object", 400
                )
            if isinstance(payload, Mapping):
                requested_room = payload.get("room_id")
                if requested_room is not None and requested_room != room_id:
                    raise self._lifecycle_error_locked(account_id, "stale room", 409)
            if record.get("status") == "waiting":
                self._claim_owner_locked()
                try:
                    self._store.delete(room_id, expected_revision=int(record["storage_revision"]))
                except (RoomStoreConflict, RoomStoreCorrupt, OSError) as exc:
                    raise self._lifecycle_error_locked(account_id, "room storage is unavailable", 503) from exc
                runtime = self._rooms.pop(room_id, None)
                if runtime is not None:
                    runtime.close()
                self._records.pop(room_id, None)
                self._account_rooms.pop(account_id, None)
                return self._lobby()
            runtime = self._ensure_runtime_locked(record)
            if runtime is None:
                raise self._lifecycle_error_locked(account_id, "room is unavailable", 503)
            current_snapshot = runtime.snapshot(account_id)
            if isinstance(payload, Mapping):
                requested_session = payload.get("session_id")
                requested_revision = payload.get("revision")
                if requested_session not in (None, "", runtime._session_id):
                    raise WebLifecycleError("stale session", 409, current_snapshot)
                if requested_revision not in (None, ""):
                    if type(requested_revision) is not int:
                        raise WebLifecycleError("revision must be an integer", 400, current_snapshot)
                    if requested_revision != runtime.revision:
                        raise WebLifecycleError("stale revision", 409, current_snapshot)
            if current_snapshot.get("outcome") is None:
                raise WebLifecycleError(
                    "finish the match before leaving the room", 409, current_snapshot
                )
            participant_updates = []
            for participant in record.get("participants", []):
                item = _clone(participant)
                if item.get("account_id") == account_id:
                    item["attached"] = False
                participant_updates.append(item)
            try:
                self._claim_owner_locked()
                saved = self._store.save(
                    room_id,
                    expected_revision=int(runtime.record["storage_revision"]),
                    updates={"participants": participant_updates},
                )
            except (RoomStoreConflict, RoomStoreCorrupt, OSError) as exc:
                raise WebLifecycleError(
                    "room storage is unavailable", 503, current_snapshot
                ) from exc
            runtime.record = saved
            self._records[room_id] = saved
            self._account_rooms.pop(account_id, None)
            if not any(item.get("attached", True) for item in participant_updates):
                self._rooms.pop(room_id, None)
                runtime.close()
            return self._lobby()

    def asset(self, account_id: str, kind: str, card_id: str) -> tuple[bytes, str, bool] | object | None:
        account_id = _validate_account_id(account_id)
        if kind not in _ASSET_KINDS or not isinstance(card_id, str):
            return None
        with self._lock:
            if self._closed:
                return None
            self._refresh_locked()
            current = self._room_for_account_locked(account_id)
            if current is None:
                return None
            _room_id, record = current
            runtime = self._ensure_runtime_locked(record)
            if runtime is None:
                return None
            seat = runtime.seat_for(account_id)
            if seat not in (0, 1):
                return None
            if runtime.session is not None and runtime.players is not None:
                observation = runtime.session.observation(runtime.players[int(seat)])
            else:
                terminal = runtime._terminal_views.get(str(seat), {})
                observation = terminal.get("observation", {}) if isinstance(terminal, Mapping) else {}
            if card_id not in visible_card_ids(observation):
                return None
            locale = str(runtime._participant(int(seat))["locale"])
        future = self._assets.request_asset(card_id, kind, locale=locale)
        try:
            asset = future.result(timeout=0.05)
        except FutureTimeout:
            return ASSET_PENDING
        except Exception:
            return None
        if asset is None:
            return None
        return asset.data, asset.media_type, asset.is_placeholder

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for runtime in list(self._rooms.values()):
                runtime.close()
            self._rooms.clear()
            if self._owner_claimed:
                self._store.release_owner()
                self._owner_claimed = False
            if self._owns_assets:
                self._assets.close()


__all__ = ["RoomRegistry"]
