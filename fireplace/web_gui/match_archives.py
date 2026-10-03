"""Atomic, account-local persistence for completed and resumable matches.

The store keeps one JSON envelope per game UUID.  It is intentionally a
backend primitive: callers receive detached dictionaries and are responsible
for projecting only the public fields to a browser.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ARCHIVE_VERSION = 1
_UNSET = object()
_DEFAULT_METADATA = {
    "mode": "normal",
    "opponent": None,
    "seed": None,
    "locale": "zhCN",
    "human_seat": 0,
    "arena": None,
}


class MatchArchiveConflict(ValueError):
    """A match archive was changed by another writer or already exists."""


class MatchArchiveCorrupt(ValueError):
    """An existing archive cannot be trusted and must not be replaced."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _clone_json(value: Any) -> Any:
    """Return a detached JSON value, rejecting NaN and engine objects."""

    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("archive value must be JSON-safe") from exc


def _merge_dict(base: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in update.items():
        if not isinstance(key, str):
            raise ValueError("archive metadata keys must be strings")
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _canonical_game_id(value: Any) -> str:
    """Validate the UUID spelling used both by callers and filenames."""

    if isinstance(value, uuid.UUID):
        return str(value)
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


def _metadata(value: Mapping[str, Any] | None, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if value is not None and not isinstance(value, Mapping):
        raise ValueError("metadata must be a mapping")
    merged = _merge_dict(base or _DEFAULT_METADATA, value or {})
    mode = merged.get("mode")
    if mode not in {"normal", "arena"}:
        raise ValueError("metadata.mode must be 'normal' or 'arena'")
    human_seat = merged.get("human_seat")
    if type(human_seat) is not int or human_seat < 0:
        raise ValueError("metadata.human_seat must be a non-negative integer")
    locale = merged.get("locale")
    if locale is not None and not isinstance(locale, str):
        raise ValueError("metadata.locale must be a string or null")
    arena = merged.get("arena")
    if arena is not None and not isinstance(arena, Mapping):
        raise ValueError("metadata.arena must be a mapping or null")
    return _clone_json(merged)


def _raw_log(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise ValueError("log must be an ActionLog or mapping")
    return _clone_json(dict(value))


def _envelope(
    game_id: str,
    revision: int,
    metadata: Mapping[str, Any],
    log: Mapping[str, Any],
    agent_state: Any,
    public: Any,
) -> dict[str, Any]:
    return _clone_json(
        {
            "archive_version": ARCHIVE_VERSION,
            "game_id": game_id,
            "revision": revision,
            "metadata": metadata,
            "log": log,
            "agent_state": agent_state,
            "public": public,
        }
    )


class MatchArchiveStore:
    """Store one detached archive envelope per canonical game UUID."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self._owner_stream = None

    def _path(self, game_id: Any) -> Path:
        canonical = _canonical_game_id(game_id)
        return self.directory / (canonical + ".json")

    def acquire_owner(self) -> None:
        """Take the account lock, rejecting a second local writer process."""

        if self._owner_stream is not None:
            return
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = (self.directory / ".owner.lock").open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise MatchArchiveConflict(
                "match archive store is open in another local process"
            ) from exc
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
        """Serialize individual reads/writes across threads and processes."""

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
    def _validate_envelope(
        payload: Any, *, expected_game_id: str | None = None
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise MatchArchiveCorrupt("match archive is not a JSON object")
        if (
            type(payload.get("archive_version")) is not int
            or payload.get("archive_version") != ARCHIVE_VERSION
        ):
            raise MatchArchiveCorrupt("unsupported match archive version")
        try:
            game_id = _canonical_game_id(payload.get("game_id"))
        except ValueError as exc:
            raise MatchArchiveCorrupt("match archive has an invalid game_id") from exc
        if expected_game_id is not None and game_id != expected_game_id:
            raise MatchArchiveCorrupt("match archive game_id does not match filename")
        revision = payload.get("revision")
        if type(revision) is not int or revision < 1:
            raise MatchArchiveCorrupt("match archive has an invalid revision")
        required = ("metadata", "log", "agent_state", "public")
        if any(key not in payload for key in required):
            raise MatchArchiveCorrupt("match archive is missing required fields")
        try:
            metadata = _metadata(payload.get("metadata"))
            log = _raw_log(payload.get("log"))
            agent_state = _clone_json(payload.get("agent_state"))
            public = _clone_json(payload.get("public"))
        except (TypeError, ValueError, KeyError) as exc:
            raise MatchArchiveCorrupt("match archive has invalid contents") from exc
        if "game_id" in log and log["game_id"] != game_id:
            raise MatchArchiveCorrupt("match archive log game_id does not match envelope")
        return _envelope(game_id, revision, metadata, log, agent_state, public)

    def _read_path(self, path: Path, game_id: str) -> dict[str, Any]:
        if path.is_symlink():
            raise MatchArchiveCorrupt("match archive is a symbolic link")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MatchArchiveCorrupt("match archive cannot be read") from exc
        return self._validate_envelope(payload, expected_game_id=game_id)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _atomic_replace(self, target: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(
                prefix=".match-archive-", suffix=".tmp", dir=self.directory
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
            self._sync_directory(self.directory)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def _atomic_create(self, target: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(
                prefix=".match-archive-", suffix=".tmp", dir=self.directory
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Linking the fully fsynced temporary file publishes a new
                # UUID atomically while refusing to replace an existing one.
                os.link(temporary, target)
            except FileExistsError as exc:
                raise MatchArchiveConflict("match archive already exists") from exc
            self._sync_directory(self.directory)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def create(
        self,
        log: Any,
        metadata: Mapping[str, Any] | None,
        agent_state: Any = None,
        public: Any = None,
    ) -> dict[str, Any]:
        raw_log = _raw_log(log)
        try:
            game_id = _canonical_game_id(raw_log.get("game_id"))
        except ValueError as exc:
            raise ValueError("log game_id must be a canonical UUID") from exc
        envelope = _envelope(
            game_id,
            1,
            _metadata(metadata),
            raw_log,
            _clone_json(agent_state),
            _clone_json(public),
        )
        target = self._path(game_id)
        with self._locked():
            if target.exists() or target.is_symlink():
                # Surface corruption distinctly and never overwrite it.
                if target.is_symlink():
                    raise MatchArchiveCorrupt("match archive is a symbolic link")
                try:
                    self._read_path(target, game_id)
                except FileNotFoundError:
                    pass
                raise MatchArchiveConflict("match archive already exists")
            self._atomic_create(target, envelope)
        return copy.deepcopy(envelope)

    def get(self, game_id: Any) -> dict[str, Any]:
        target = self._path(game_id)
        canonical = target.stem
        with self._locked():
            return copy.deepcopy(self._read_path(target, canonical))

    @staticmethod
    def _listed_status(envelope: Mapping[str, Any]) -> str | None:
        metadata = envelope.get("metadata", {})
        if isinstance(metadata, Mapping) and metadata.get("status") == "abandoned":
            return "abandoned"
        log = envelope.get("log", {})
        return log.get("status") if isinstance(log, Mapping) else None

    def list(self) -> list[dict[str, Any]]:
        rows: list[tuple[int, dict[str, Any]]] = []
        with self._locked():
            try:
                paths = list(self.directory.glob("*.json"))
            except OSError:
                return []
            for path in paths:
                try:
                    game_id = _canonical_game_id(path.stem)
                    envelope = self._read_path(path, game_id)
                    status = self._listed_status(envelope)
                    # ``status`` is a list projection.  The on-disk envelope
                    # remains the exact raw log/metadata contract.
                    envelope["status"] = status
                    mtime = path.stat().st_mtime_ns
                except (OSError, ValueError, MatchArchiveCorrupt):
                    # A corrupt or inaccessible history entry must remain on
                    # disk for diagnosis while healthy matches stay usable.
                    continue
                rows.append((mtime, envelope))
        rows.sort(key=lambda row: (row[0], row[1]["game_id"]), reverse=True)
        return [copy.deepcopy(envelope) for _mtime, envelope in rows]

    def save(
        self,
        game_id: Any,
        *,
        log: Any = None,
        metadata: Mapping[str, Any] | None = None,
        agent_state: Any = _UNSET,
        public: Any = _UNSET,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        target = self._path(game_id)
        canonical = target.stem
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("expected_revision must be a positive integer or null")
        with self._locked():
            current = self._read_path(target, canonical)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise MatchArchiveConflict("match archive revision changed")
            next_log = current["log"] if log is None else _raw_log(log)
            if "game_id" in next_log and next_log["game_id"] != canonical:
                raise ValueError("log game_id does not match archive game_id")
            next_metadata = _metadata(metadata, current["metadata"])
            next_agent_state = (
                current["agent_state"] if agent_state is _UNSET else _clone_json(agent_state)
            )
            next_public = current["public"] if public is _UNSET else _clone_json(public)
            envelope = _envelope(
                canonical,
                current["revision"] + 1,
                next_metadata,
                next_log,
                next_agent_state,
                next_public,
            )
            self._atomic_replace(target, envelope)
            return copy.deepcopy(envelope)

    def mark_abandoned(
        self, game_id: Any, expected_revision: int | None = None
    ) -> dict[str, Any]:
        return self.save(
            game_id,
            metadata={"status": "abandoned", "finished_at": _utc_now()},
            expected_revision=expected_revision,
        )

    def find_arena(self, match_id: Any) -> dict[str, Any] | None:
        if not isinstance(match_id, str) or not match_id:
            return None
        # Arena settlement uses this lookup to decide whether a result was
        # already recorded.  Silently skipping a damaged archive here could
        # therefore count a match twice, so scan strictly and surface any
        # canonical archive whose identity/content cannot be trusted.
        rows: list[tuple[int, dict[str, Any]]] = []
        with self._locked():
            try:
                paths = list(self.directory.glob("*.json"))
            except OSError as exc:
                raise MatchArchiveCorrupt("match archive directory cannot be read") from exc
            for path in paths:
                try:
                    canonical = _canonical_game_id(path.stem)
                except ValueError:
                    # Temporary/foreign JSON files are outside this store's
                    # UUID namespace and cannot identify an Arena match.
                    continue
                try:
                    envelope = self._read_path(path, canonical)
                    mtime = path.stat().st_mtime_ns
                except FileNotFoundError as exc:
                    raise MatchArchiveCorrupt("match archive disappeared during lookup") from exc
                except (OSError, MatchArchiveCorrupt) as exc:
                    raise MatchArchiveCorrupt(
                        "match archive cannot be trusted during Arena lookup"
                    ) from exc
                rows.append((mtime, envelope))
        rows.sort(key=lambda row: (row[0], row[1]["game_id"]), reverse=True)
        for _mtime, envelope in rows:
            metadata = envelope.get("metadata", {})
            arena = metadata.get("arena") if isinstance(metadata, Mapping) else None
            if (
                isinstance(metadata, Mapping)
                and metadata.get("mode") == "arena"
                and isinstance(arena, Mapping)
                and arena.get("match_id") == match_id
            ):
                return copy.deepcopy(envelope)
        return None


__all__ = [
    "ARCHIVE_VERSION",
    "MatchArchiveConflict",
    "MatchArchiveCorrupt",
    "MatchArchiveStore",
]
