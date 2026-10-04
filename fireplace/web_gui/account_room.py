"""Account-scoped facade for the process-wide LAN room registry.

Personal matches continue to live in :class:`WebGameManager`.  A room is
owned by the shared ``RoomRegistry`` instead, so account-manager eviction and
logout can release a personal manager without terminating a room that still
has another participant.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .contracts import WebActionError, WebLifecycleError
from .server import _validate_locale, _validate_nickname


_ROOM_CREATE_KEYS = frozenset({"nickname", "locale", "deck_id"})
_ROOM_JOIN_KEYS = frozenset({"code", "invite_code", "nickname", "locale", "deck_id"})
_ROOM_LEAVE_KEYS = frozenset({"room_id", "session_id", "revision"})


class AccountRoomBackend:
    """Present one account's personal manager and shared room as one backend."""

    def __init__(self, manager: object, account_id: str, rooms: object):
        self.manager = manager
        self.account_id = str(account_id)
        self.rooms = rooms

    @property
    def _catalog(self):
        return getattr(self.manager, "_catalog", None)

    def _room_snapshot(self) -> dict[str, Any] | None:
        if not self.rooms.has_current(self.account_id):
            return None
        value = self.rooms.snapshot(self.account_id)
        return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else None

    def has_current_room(self) -> bool:
        return bool(self.rooms.has_current(self.account_id))

    def snapshot(self) -> dict[str, Any]:
        room = self._room_snapshot()
        return room if room is not None else self.manager.snapshot()

    def error_payload(self, message: str) -> dict[str, Any]:
        payload = self.snapshot()
        payload["error"] = str(message)
        return payload

    def _room_busy(self, operation: str) -> None:
        if self.has_current_room():
            raise WebLifecycleError(
                "leave the current room before %s" % operation,
                409,
                self.snapshot(),
            )

    def _validate_payload(self, payload: object, allowed: frozenset[str]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise WebLifecycleError(
                "request body must be a JSON object", 400, self.snapshot()
            )
        unknown = set(payload) - allowed
        if unknown:
            raise WebLifecycleError(
                "unsupported room fields", 400, self.snapshot()
            )
        return dict(payload)

    def _deck_spec(self, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        deck_id = payload.get("deck_id")
        if deck_id is None or deck_id == "":
            return None
        if not isinstance(deck_id, str):
            raise WebLifecycleError("deck_id must be a string", 400, self.snapshot())
        try:
            with self.manager._lock:
                saved = self.manager._decks_locked().get_complete(deck_id)
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 400, self.snapshot()) from exc
        except OSError as exc:
            raise WebLifecycleError(
                "deck storage is unavailable", 503, self.snapshot()
            ) from exc
        return {
            "hero_id": saved["hero_id"],
            "card_ids": list(saved["card_ids"]),
        }

    @staticmethod
    def _room_fields(payload: Mapping[str, Any], *, join: bool) -> dict[str, Any]:
        nickname = _validate_nickname(payload.get("nickname"))
        locale = _validate_locale(payload.get("locale"))
        if join:
            code_value = payload.get("code")
            invite_value = payload.get("invite_code")
            if code_value is not None and invite_value is not None and code_value != invite_value:
                raise ValueError("code and invite_code do not match")
            invite_code = code_value if code_value is not None else invite_value
            if not isinstance(invite_code, str) or not invite_code.strip():
                raise ValueError("invite_code must be a non-empty string")
            return {
                "code": invite_code.strip(),
                "nickname": nickname,
                "locale": locale,
            }
        return {"nickname": nickname, "locale": locale}

    def room_create(self, payload: object) -> dict[str, Any]:
        values = self._validate_payload(payload, _ROOM_CREATE_KEYS)
        try:
            room_payload = self._room_fields(values, join=False)
            deck_spec = self._deck_spec(values)
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 400, self.snapshot()) from exc
        try:
            return self.rooms.create(
                self.account_id, room_payload, deck_spec=deck_spec
            )
        except (WebActionError, WebLifecycleError):
            raise
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 409, self.snapshot()) from exc

    def room_join(self, payload: object) -> dict[str, Any]:
        values = self._validate_payload(payload, _ROOM_JOIN_KEYS)
        try:
            room_payload = self._room_fields(values, join=True)
            deck_spec = self._deck_spec(values)
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 400, self.snapshot()) from exc
        try:
            return self.rooms.join(
                self.account_id, room_payload, deck_spec=deck_spec
            )
        except (WebActionError, WebLifecycleError):
            raise
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 409, self.snapshot()) from exc

    def room_current(self) -> dict[str, Any]:
        room = self._room_snapshot()
        if room is not None:
            return room
        return {"mode": "lobby", "room": None}

    def room_leave(self, payload: object = None) -> dict[str, Any]:
        if payload is not None:
            payload = self._validate_payload(payload, _ROOM_LEAVE_KEYS)
        try:
            result = self.rooms.leave(self.account_id, payload or {})
        except (WebActionError, WebLifecycleError):
            raise
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 409, self.snapshot()) from exc
        return result

    def handle_action(self, payload: object) -> dict[str, Any]:
        room = self._room_snapshot()
        if room is not None:
            return self.rooms.handle_action(self.account_id, payload)
        return self.manager.handle_action(payload)

    def concede(self, payload: object) -> dict[str, Any]:
        room = self._room_snapshot()
        if room is not None:
            return self.rooms.concede(self.account_id, payload)
        return self.manager.concede(payload)

    def return_to_lobby(self, payload: object) -> dict[str, Any]:
        self._room_busy("returning to the lobby")
        return self.manager.return_to_lobby(payload)

    def start_match(self, payload: object) -> dict[str, Any]:
        self._room_busy("starting a personal match")
        return self.manager.start_match(payload)

    def resume_match(self, payload: object) -> dict[str, Any]:
        self._room_busy("resuming a personal match")
        return self.manager.resume_match(payload)

    def retry_opponent(self, payload: object) -> dict[str, Any]:
        self._room_busy("retrying a personal opponent")
        return self.manager.retry_opponent(payload)

    def automation(self, payload: object) -> dict[str, Any]:
        self._room_busy("controlling a personal match")
        return self.manager.automation(payload)

    def abandon_match(self, payload: object) -> dict[str, Any]:
        self._room_busy("abandoning a personal match")
        return self.manager.abandon_match(payload)

    def asset(self, kind: str, card_id: str):
        if self.has_current_room():
            return self.rooms.asset(self.account_id, kind, card_id)
        return self.manager.asset(kind, card_id)

    def decks_state(self, *, locale: str = "zhCN"):
        return self.manager.decks_state(locale=locale)

    def decks_save(self, payload: object):
        return self.manager.decks_save(payload)

    def decks_delete(self, payload: object):
        return self.manager.decks_delete(payload)

    def matches_list(self, *, offset: int = 0, limit: int = 50):
        return self.manager.matches_list(offset=offset, limit=limit)

    def match_detail(self, game_id: str):
        return self.manager.match_detail(game_id)

    def match_download(self, game_id: str):
        return self.manager.match_download(game_id)

    def _arena_busy(self, method: str, *args, **kwargs):
        self._room_busy("using Arena")
        return getattr(self.manager, method)(*args, **kwargs)

    def arena_state(self, *, locale: str = "zhCN"):
        # Reading the personal Arena setup is harmless while an account is in
        # a shared room; only Arena mutations are fenced below.
        return self.manager.arena_state(locale=locale)

    def arena_start(self, payload: object):
        return self._arena_busy("arena_start", payload)

    def arena_choose_hero(self, payload: object):
        return self._arena_busy("arena_choose_hero", payload)

    def arena_choose_card(self, payload: object):
        return self._arena_busy("arena_choose_card", payload)

    def arena_start_battle(self, payload: object):
        return self._arena_busy("arena_start_battle", payload)

    def arena_retire(self, payload: object):
        return self._arena_busy("arena_retire", payload)

    def arena_reset(self, payload: object):
        return self._arena_busy("arena_reset", payload)

    def close(self) -> None:
        # RoomRegistry is process-owned and must outlive one account manager.
        self.manager.close()


__all__ = ["AccountRoomBackend"]
