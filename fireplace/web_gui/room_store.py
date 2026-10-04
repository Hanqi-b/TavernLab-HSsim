"""Durable server-wide storage for authenticated human-vs-human rooms.

Room files intentionally live outside account archives.  A room contains the
two account bindings and, while a match is live, the private action log needed
to restore the one shared engine session.  Callers still own privacy
projection; this store only validates JSON and serialises file access.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOM_STORE_VERSION = 1
_ROOM_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ACCOUNT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_STATUSES = frozenset({"waiting", "playing", "complete"})


class RoomStoreConflict(RuntimeError):
    """A room was changed by another writer or already exists."""


class RoomStoreCorrupt(ValueError):
    """A room file cannot be trusted and must not be replaced."""


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("room value must be JSON-safe") from exc


def _account_id(value: object) -> str:
    if not isinstance(value, str) or _ACCOUNT_ID_RE.fullmatch(value) is None:
        raise ValueError("invalid account ID")
    return value


def _room_id(value: object) -> str:
    if not isinstance(value, str) or _ROOM_ID_RE.fullmatch(value) is None:
        raise ValueError("invalid room ID")
    return value


def _validate_participant(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RoomStoreCorrupt("room participant is not an object")
    try:
        account_id = _account_id(value.get("account_id"))
    except ValueError as exc:
        raise RoomStoreCorrupt("room participant has an invalid account ID") from exc
    seat = value.get("seat")
    if type(seat) is not int or seat not in (0, 1):
        raise RoomStoreCorrupt("room participant has an invalid seat")
    nickname = value.get("nickname")
    if not isinstance(nickname, str) or not nickname or len(nickname) > 32:
        raise RoomStoreCorrupt("room participant has an invalid nickname")
    locale = value.get("locale")
    if locale not in ("zhCN", "enUS"):
        raise RoomStoreCorrupt("room participant has an invalid locale")
    attached = value.get("attached", True)
    if type(attached) is not bool:
        raise RoomStoreCorrupt("room participant has an invalid attachment")
    return {
        "account_id": account_id,
        "seat": seat,
        "nickname": nickname,
        "locale": locale,
        "attached": attached,
    }


def _validate_record(value: object, *, expected_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RoomStoreCorrupt("room file is not a JSON object")
    try:
        version = value.get("room_store_version")
        if type(version) is not int or version != ROOM_STORE_VERSION:
            raise RoomStoreCorrupt("unsupported room store version")
        room_id = _room_id(value.get("id"))
        if expected_id is not None and room_id != expected_id:
            raise RoomStoreCorrupt("room ID does not match filename")
        status = value.get("status")
        if status not in _STATUSES:
            raise RoomStoreCorrupt("room has an invalid status")
        creator = _account_id(value.get("creator_account_id"))
        participants = value.get("participants")
        if not isinstance(participants, list) or len(participants) not in (1, 2):
            raise RoomStoreCorrupt("room has an invalid participant list")
        normalized = [_validate_participant(item) for item in participants]
        seats = [item["seat"] for item in normalized]
        accounts = [item["account_id"] for item in normalized]
        if len(set(seats)) != len(seats) or len(set(accounts)) != len(accounts):
            raise RoomStoreCorrupt("room participant seats or accounts are duplicated")
        if creator not in accounts or normalized[accounts.index(creator)]["seat"] != 0:
            raise RoomStoreCorrupt("room creator is not seat zero")
        if status == "waiting" and len(normalized) != 1:
            raise RoomStoreCorrupt("waiting room must have one participant")
        if status in ("playing", "complete") and len(normalized) != 2:
            raise RoomStoreCorrupt("active room must have two participants")
        storage_revision = value.get("storage_revision")
        if type(storage_revision) is not int or storage_revision < 1:
            raise RoomStoreCorrupt("room has an invalid storage revision")
        accepted_revision = value.get("accepted_revision", 0)
        if type(accepted_revision) is not int or accepted_revision < 0:
            raise RoomStoreCorrupt("room has an invalid accepted revision")
        invite_hash = value.get("invite_code_hash")
        if not isinstance(invite_hash, str) or len(invite_hash) != 64:
            raise RoomStoreCorrupt("room has an invalid invitation hash")
        seed = value.get("seed")
        if seed is not None and type(seed) is not int:
            raise RoomStoreCorrupt("room has an invalid seed")
        deck_specs = value.get("deck_specs", [None, None])
        if not isinstance(deck_specs, list) or len(deck_specs) != 2:
            raise RoomStoreCorrupt("room has invalid deck specifications")
        log = value.get("log")
        if log is not None and not isinstance(log, Mapping):
            raise RoomStoreCorrupt("room log is not an object")
        views = value.get("views", {})
        if not isinstance(views, Mapping):
            raise RoomStoreCorrupt("room views are not an object")
        terminal_views = value.get("terminal_views", {})
        if not isinstance(terminal_views, Mapping):
            raise RoomStoreCorrupt("room terminal views are not an object")
        # Remaining fields are private opaque JSON.  Validate the whole record
        # below so engine handles or accidental non-finite values never land
        # on disk.
        result = dict(value)
        result.update(
            room_store_version=ROOM_STORE_VERSION,
            id=room_id,
            creator_account_id=creator,
            status=status,
            participants=normalized,
            storage_revision=storage_revision,
            accepted_revision=accepted_revision,
            seed=seed,
            deck_specs=copy.deepcopy(deck_specs),
            log=copy.deepcopy(dict(log)) if isinstance(log, Mapping) else None,
            views=copy.deepcopy(dict(views)),
            terminal_views=copy.deepcopy(dict(terminal_views)),
        )
        return _json_copy(result)
    except RoomStoreCorrupt:
        raise
    except (TypeError, ValueError, OverflowError) as exc:
        raise RoomStoreCorrupt("room file has invalid contents") from exc


class RoomStore:
    """Atomic JSON records under one server-wide ``rooms`` directory.

    The optional owner lock is acquired by :class:`RoomRegistry` only when it
    first creates or joins a room.  A registry that is used solely by existing
    account-local tests therefore does not contend for a room lock.
    """

    def __init__(self, directory: str | os.PathLike[str]):
        self.directory = Path(directory)
        self._owner_stream = None

    def _path(self, room_id: object) -> Path:
        return self.directory / (_room_id(room_id) + ".json")

    def acquire_owner(self) -> None:
        if self._owner_stream is not None:
            return
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = (self.directory / ".owner.lock").open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise RoomStoreConflict("room store is open in another local process") from exc
        self._owner_stream = stream

    def release_owner(self) -> None:
        stream = self._owner_stream
        self._owner_stream = None
        if stream is None:
            return
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    close = release_owner

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = (self.directory / ".store.lock").open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _read_path(self, path: Path, room_id: str) -> dict[str, Any]:
        if path.is_symlink():
            raise RoomStoreCorrupt("room file is a symbolic link")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RoomStoreCorrupt("room file cannot be read") from exc
        return _validate_record(payload, expected_id=room_id)

    def _atomic_replace(self, path: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".room-", suffix=".tmp", dir=self.directory)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            self._sync_directory(self.directory)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def _atomic_create(self, path: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".room-", suffix=".tmp", dir=self.directory)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise RoomStoreConflict("room already exists") from exc
            # The link is the published room.  Remove the temporary directory
            # entry as well; otherwise every create leaves a second hardlink
            # containing the same private room record behind.
            os.unlink(temporary)
            temporary = None
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            self._sync_directory(self.directory)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def create(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(record, Mapping):
            raise ValueError("room record must be an object")
        candidate = dict(record)
        candidate.setdefault("room_store_version", ROOM_STORE_VERSION)
        candidate.setdefault("storage_revision", 1)
        checked = _validate_record(candidate)
        path = self._path(checked["id"])
        with self._locked():
            if path.exists() or path.is_symlink():
                raise RoomStoreConflict("room already exists")
            self._atomic_create(path, checked)
        return copy.deepcopy(checked)

    def get(self, room_id: str) -> dict[str, Any] | None:
        path = self._path(room_id)
        with self._locked():
            try:
                return copy.deepcopy(self._read_path(path, path.stem))
            except FileNotFoundError:
                return None

    def list(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with self._locked():
            try:
                paths = list(self.directory.glob("*.json"))
            except OSError as exc:
                raise RoomStoreCorrupt("room directory cannot be read") from exc
            for path in paths:
                if path.is_symlink() or _ROOM_ID_RE.fullmatch(path.stem) is None:
                    continue
                try:
                    rows.append(self._read_path(path, path.stem))
                except FileNotFoundError:
                    continue
        rows.sort(key=lambda row: (row.get("storage_revision", 0), row["id"]))
        return copy.deepcopy(rows)

    def save(
        self,
        room_id: str,
        *,
        expected_revision: int,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected_revision must be a positive integer")
        if not isinstance(updates, Mapping):
            raise ValueError("room updates must be an object")
        path = self._path(room_id)
        with self._locked():
            try:
                current = self._read_path(path, path.stem)
            except FileNotFoundError as exc:
                raise RoomStoreConflict("room does not exist") from exc
            if current["storage_revision"] != expected_revision:
                raise RoomStoreConflict("room changed")
            candidate = copy.deepcopy(current)
            candidate.update(copy.deepcopy(dict(updates)))
            candidate["storage_revision"] = expected_revision + 1
            checked = _validate_record(candidate, expected_id=path.stem)
            self._atomic_replace(path, checked)
        return copy.deepcopy(checked)

    def delete(self, room_id: str, *, expected_revision: int | None = None) -> None:
        path = self._path(room_id)
        with self._locked():
            try:
                current = self._read_path(path, path.stem)
            except FileNotFoundError:
                return
            if expected_revision is not None and current["storage_revision"] != expected_revision:
                raise RoomStoreConflict("room changed")
            try:
                path.unlink()
                self._sync_directory(self.directory)
            except FileNotFoundError:
                return


__all__ = [
    "ROOM_STORE_VERSION",
    "RoomStore",
    "RoomStoreConflict",
    "RoomStoreCorrupt",
]
