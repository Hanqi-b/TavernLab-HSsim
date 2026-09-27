"""Small atomic local save for the Arena draft and win/loss record."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .run import ArenaRun

_UNSET = object()


class ArenaStoreConflict(ValueError):
    """Another local server changed the saved run since it was loaded."""


class ArenaStoreCorrupt(ValueError):
    """The existing save cannot be read safely and must not be replaced."""


def default_state_path() -> Path:
    configured = os.environ.get("FIREPLACE_ARENA_STATE")
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "fireplace" / "arena-run.json"


class ArenaStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_state_path()
        self._owner_stream = None

    def acquire_owner(self) -> None:
        """Allow one live Arena service to own this save path at a time."""

        import fcntl

        if self._owner_stream is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        owner_path = self.path.with_name(self.path.name + ".owner")
        stream = owner_path.open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise ArenaStoreConflict("Arena save is open in another local server") from exc
        self._owner_stream = stream

    def release_owner(self) -> None:
        import fcntl

        stream = self._owner_stream
        self._owner_stream = None
        if stream is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()

    @contextmanager
    def _locked(self):
        """Serialize writers in separate local server processes."""

        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> ArenaRun | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return ArenaRun.from_dict(payload)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ArenaStoreCorrupt(f"Arena save cannot be read: {self.path}") from exc

    def load(self) -> ArenaRun | None:
        with self._locked():
            return self._read_unlocked()

    def _check_expected(self, expected: ArenaRun | None | object) -> None:
        if expected is _UNSET:
            return
        current = self._read_unlocked()
        actual = None if current is None else (current.run_id, current.revision)
        wanted = None if expected is None else (expected.run_id, expected.revision)
        if actual != wanted:
            raise ArenaStoreConflict("Arena save changed in another local server")

    def save(self, run: ArenaRun, *, expected: ArenaRun | None | object = _UNSET) -> None:
        with self._locked():
            self._check_expected(expected)
            self._write_unlocked(run)

    def _write_unlocked(self, run: ArenaRun) -> None:
        data = json.dumps(run.to_dict(), ensure_ascii=False, separators=(",", ":"))
        fd, temporary = tempfile.mkstemp(prefix=".arena-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def clear(self, *, expected: ArenaRun | None | object = _UNSET) -> None:
        with self._locked():
            self._check_expected(expected)
            try:
                self.path.unlink()
            except FileNotFoundError:
                return


__all__ = ["ArenaStore", "ArenaStoreConflict", "ArenaStoreCorrupt", "default_state_path"]
