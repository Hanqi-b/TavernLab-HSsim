"""Asynchronous opponent scheduling for the browser match boundary.

The engine is intentionally synchronous.  This module owns the small amount
of coordination needed by an interactive opponent whose decision may involve
an external process: one daemon worker per match, one in-flight decision, and
an explicit generation token so a result can never apply to a later state.
"""

from __future__ import annotations

import copy
import os
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Generic, Mapping, Sequence, TypeVar


MAX_CODEX_MODEL_LENGTH = 128
DEFAULT_CODEX_TIMEOUT = 90.0
_CODEX_MODEL_ENV = (
    "TAVERNLAB_CODEX_MODEL",
    "FIREPLACE_CODEX_MODEL",
    "CODEX_MODEL",
)
_CODEX_TIMEOUT_ENV = (
    "TAVERNLAB_CODEX_TIMEOUT",
    "FIREPLACE_CODEX_TIMEOUT",
    "CODEX_TIMEOUT",
)


def validate_codex_model(value: object) -> str | None:
    """Validate a public Codex model override.

    An empty string deliberately means "use the adapter default".  The
    adapter owns the actual model allowlist, which can change independently of
    the Fireplace engine; this boundary only enforces its storage contract.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("codex_model must be a string")
    model = value.strip()
    if len(model) > MAX_CODEX_MODEL_LENGTH:
        raise ValueError(
            "codex_model must be at most %d characters" % MAX_CODEX_MODEL_LENGTH
        )
    return model or None


def validate_codex_timeout(value: object) -> float:
    """Return a finite, positive Codex timeout in seconds."""

    # bool is an int subclass but is never a useful timeout configuration.
    if isinstance(value, bool):
        raise ValueError("codex_timeout must be a positive number")
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("codex_timeout must be a positive number") from exc
    if timeout <= 0 or timeout != timeout or timeout == float("inf"):
        raise ValueError("codex_timeout must be a positive number")
    # Keep accidental environment/configuration mistakes bounded.  The agent
    # may impose a tighter limit, but this gives the web boundary a stable
    # archive value and avoids an unbounded worker lifetime.
    if timeout > 24 * 60 * 60:
        raise ValueError("codex_timeout must be at most 86400 seconds")
    return timeout


def _first_env(names: Sequence[str]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return value
    return None


def codex_defaults(
    model: object | None = None, timeout: object | None = None
) -> tuple[str | None, float]:
    """Resolve explicit values or the supported process-level defaults."""

    if model is None:
        model = _first_env(_CODEX_MODEL_ENV)
    if timeout is None:
        timeout = _first_env(_CODEX_TIMEOUT_ENV)
    if timeout is None or timeout == "":
        timeout = DEFAULT_CODEX_TIMEOUT
    return validate_codex_model(model), validate_codex_timeout(timeout)


def codex_config_from_agent(agent: object) -> dict[str, Any]:
    """Read and validate the non-secret configuration exported by an agent."""

    export = getattr(agent, "export_config", None)
    if not callable(export):
        raise ValueError("Codex opponent has no exportable configuration")
    try:
        value = export()
    except (TypeError, ValueError) as exc:
        raise ValueError("Codex opponent has invalid configuration") from exc
    if not isinstance(value, Mapping):
        raise ValueError("Codex opponent has invalid configuration")
    allowed = {"model", "timeout"}
    if set(value) != allowed:
        raise ValueError("Codex opponent configuration contains unsupported keys")
    model = validate_codex_model(value.get("model"))
    timeout = validate_codex_timeout(value.get("timeout"))
    return {"model": model, "timeout": timeout}


def validate_codex_state(value: object) -> dict[str, Any]:
    """Validate an archived Codex state without accepting runtime secrets."""

    if not isinstance(value, Mapping) or value.get("kind") != "codex":
        raise ValueError("invalid archived Codex opponent state")
    # Archive values are pinned inputs.  Missing values must not fall back to
    # a process environment setting which could change between resume calls.
    if set(value) != {"kind", "model", "timeout"}:
        raise ValueError("invalid archived Codex configuration")
    model_value = value.get("model")
    timeout_value = value.get("timeout")
    if model_value is None:
        model = None
    else:
        model = validate_codex_model(model_value)
        if model is None:
            raise ValueError("invalid archived Codex model")
    timeout = validate_codex_timeout(timeout_value)
    return {"kind": "codex", "model": model, "timeout": timeout}


@dataclass(frozen=True)
class AsyncDecision:
    """Detached input captured while the WebGame lock is held."""

    session_id: str
    revision: int
    player: object
    observation: Mapping[str, Any]
    actions: tuple[object, ...]
    generation: int


T = TypeVar("T")


@dataclass(frozen=True)
class _QueuedDecision(Generic[T]):
    item: T
    generation: int


class DetachedDecisionWorker(Generic[T]):
    """Run one detached decision worker with generation based invalidation.

    The worker is deliberately independent of the owner match.  A caller may
    invalidate a running request and enqueue a later request on the same
    worker; the old result is discarded when it returns.  This is important
    for automation pause/resume: replacing the worker would accumulate daemon
    threads while an old MCTS search is still unwinding.
    """

    def __init__(
        self,
        choose: Callable[[T], object],
        *,
        on_result: Callable[[T, object], None],
        on_error: Callable[[T, BaseException], None],
        cancel_for: Callable[[T], object | None] | None = None,
        closeables: Callable[[], Sequence[object]] | None = None,
    ) -> None:
        self._choose = choose
        self._on_result = on_result
        self._on_error = on_error
        self._cancel_for = cancel_for
        self._closeables = closeables or (lambda: ())
        self._queue: queue.Queue[_QueuedDecision[T] | object] = queue.Queue(maxsize=1)
        self._sentinel = object()
        self._lock = threading.Lock()
        self._closed = False
        self._pending: _QueuedDecision[T] | None = None
        self._generation = 0
        self._thread = threading.Thread(
            target=self._run,
            name="fireplace-detached-decision",
            daemon=True,
        )
        self._thread.start()

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def pending(self) -> T | None:
        with self._lock:
            return None if self._pending is None else self._pending.item

    def is_generation_current(self, generation: int) -> bool:
        """Check an item's generation while the owner match lock is held."""

        with self._lock:
            return not self._closed and self._generation == int(generation)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def submit(self, item: T) -> bool:
        """Queue one decision, returning false while another is in flight."""

        with self._lock:
            if self._closed or self._pending is not None:
                return False
            queued = _QueuedDecision(item, self._generation)
            self._pending = queued
            try:
                self._queue.put_nowait(queued)
            except queue.Full:  # pragma: no cover - guarded by _pending
                self._pending = None
                return False
            return True

    def invalidate(self) -> None:
        """Invalidate queued/running work and cancel only its captured target."""

        with self._lock:
            self._generation += 1
            queued = self._pending
            self._pending = None
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
        if queued is not None:
            self._cancel_item(queued.item)

    def close(self, *, wait: bool = False) -> None:
        """Stop the worker and release its current controller instances."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            queued = self._pending
            self._pending = None
            # A queued item may fill the only slot.  Drain it before putting
            # the sentinel so shutdown can never lose its wakeup.
            try:
                while True:
                    self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(self._sentinel)
        targets: list[object] = []
        try:
            targets.extend(self._closeables())
        except Exception:
            pass
        if queued is not None:
            target = self._target_for(queued.item)
            if target is not None and all(target is not value for value in targets):
                targets.append(target)
        for target in targets:
            close = getattr(target, "close", None)
            if not callable(close):
                continue
            if wait:
                self._call_close(close, wait=True)
            else:
                self._close_async(close)
        if wait and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)

    def retire(self, target: object) -> None:
        """Release a replaced controller without stopping this worker."""

        close = getattr(target, "close", None)
        if callable(close):
            self._close_async(close)

    def _target_for(self, item: T) -> object | None:
        if self._cancel_for is None:
            return None
        try:
            return self._cancel_for(item)
        except Exception:
            return None

    def _cancel_item(self, item: T) -> None:
        target = self._target_for(item)
        cancel = getattr(target, "cancel", None) if target is not None else None
        if callable(cancel):
            threading.Thread(
                target=self._call_best_effort,
                args=(cancel,),
                name="fireplace-detached-cancel",
                daemon=True,
            ).start()

    def _close_async(self, close: Callable[..., object]) -> None:
        threading.Thread(
            target=self._call_close,
            args=(close,),
            kwargs={"wait": False},
            name="fireplace-detached-close",
            daemon=True,
        ).start()

    def _current(self, queued: _QueuedDecision[T]) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._pending is queued
                and self._generation == queued.generation
            )

    def _finished(self, queued: _QueuedDecision[T]) -> None:
        with self._lock:
            if self._pending is queued:
                self._pending = None

    @staticmethod
    def _call_best_effort(callback: Callable[..., object]) -> None:
        try:
            callback()
        except Exception:
            pass

    @staticmethod
    def _call_close(callback: Callable[..., object], *, wait: bool) -> None:
        try:
            callback(wait=wait)
        except TypeError:
            try:
                callback()
            except Exception:
                pass
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            queued = self._queue.get()
            if queued is self._sentinel:
                return
            if not isinstance(queued, _QueuedDecision):
                continue
            # Recheck after dequeuing: close/invalidate can race with the
            # worker waking up and must prevent an external call entirely.
            if not self._current(queued):
                self._finished(queued)
                continue
            try:
                result = self._choose(queued.item)
            except BaseException as exc:
                current = self._current(queued)
                self._finished(queued)
                if current:
                    self._on_error(queued.item, exc)
                continue
            current = self._current(queued)
            self._finished(queued)
            if current:
                self._on_result(queued.item, result)


class AsyncOpponentScheduler:
    """Run one asynchronous decision worker for one active match.

    ``on_result`` and ``on_error`` are called from the daemon worker.  They
    must acquire the owning match lock before touching engine state.  The
    scheduler itself never owns that lock, which keeps slow external work out
    of HTTP state/action/concede requests.
    """

    def __init__(
        self,
        agent: object,
        *,
        on_result: Callable[[AsyncDecision, object], None],
        on_error: Callable[[AsyncDecision, BaseException], None],
    ) -> None:
        self.agent = agent
        self._on_result = on_result
        self._on_error = on_error
        self._worker = DetachedDecisionWorker(
            self._choose,
            on_result=on_result,
            on_error=on_error,
            cancel_for=lambda _decision: self.agent,
            closeables=lambda: (self.agent,),
        )

    @property
    def pending(self) -> AsyncDecision | None:
        value = self._worker.pending
        return value if isinstance(value, AsyncDecision) else None

    @property
    def closed(self) -> bool:
        return self._worker.closed

    def schedule(
        self,
        *,
        session_id: str,
        revision: int,
        player: object,
        observation: Mapping[str, Any],
        actions: Sequence[object],
    ) -> AsyncDecision | None:
        """Queue one detached decision, or return ``None`` if already busy."""

        generation = self._worker.generation
        decision = AsyncDecision(
            session_id=str(session_id),
            revision=int(revision),
            player=player,
            observation=copy.deepcopy(dict(observation)),
            actions=tuple(copy.deepcopy(list(actions))),
            generation=generation,
        )
        return decision if self._worker.submit(decision) else None

    def invalidate(self) -> None:
        """Invalidate a queued/running result without waiting for the worker."""

        self._worker.invalidate()

    def close(self, *, wait: bool = False) -> None:
        """Stop scheduling and ask the external agent to release resources."""

        self._worker.close(wait=wait)

    def is_current(self, decision: AsyncDecision) -> bool:
        return self._worker.is_generation_current(decision.generation)

    def _choose(self, decision: AsyncDecision) -> object:
        # The only references supplied to an external agent are plain
        # detached observation/action values.
        return self.agent.choose_action(
            copy.deepcopy(dict(decision.observation)),
            copy.deepcopy(list(decision.actions)),
        )


__all__ = [
    "AsyncDecision",
    "DetachedDecisionWorker",
    "AsyncOpponentScheduler",
    "DEFAULT_CODEX_TIMEOUT",
    "MAX_CODEX_MODEL_LENGTH",
    "codex_config_from_agent",
    "codex_defaults",
    "validate_codex_model",
    "validate_codex_state",
    "validate_codex_timeout",
]
