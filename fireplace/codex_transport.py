"""Small JSON-RPC transport for a local Codex app-server process.

The transport intentionally has no knowledge of Fireplace or of the card
agent's prompt.  It owns the process, JSONL framing, bounded reader queues,
and the small amount of JSON-RPC bookkeeping needed by ``CodexAgent``.
"""

from __future__ import annotations

import json
import os
import queue
import re
import select
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping


DEFAULT_CODEX_BINARY = "/usr/lib/chatgpt/resources/codex"
DEFAULT_MAX_LINE_BYTES = 1024 * 1024
DEFAULT_QUEUE_SIZE = 512


class CodexTransportError(RuntimeError):
    """A local app-server transport failed without exposing process output."""


class _EndOfStream:
    pass


class _ProtocolFailure:
    def __init__(self, reason: str):
        self.reason = reason


_END_OF_STREAM = _EndOfStream()


def resolve_codex_binary(value: str | os.PathLike[str] | None = None) -> str:
    """Resolve the executable without invoking a shell.

    An explicit value wins, followed by the task-local environment override,
    a user-local ``~/.local/bin/codex``, ``PATH``, and finally the ChatGPT
    desktop location.  No bundled runtime is downloaded or imported.
    """

    candidate = value
    if candidate is None:
        candidate = os.environ.get("TAVERNLAB_CODEX_BINARY")
    if candidate:
        candidate = os.fspath(candidate)
        resolved = shutil.which(candidate)
        return resolved or candidate
    local_candidate = Path.home() / ".local" / "bin" / "codex"
    if local_candidate.is_file() and os.access(local_candidate, os.X_OK):
        return str(local_candidate)
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    return DEFAULT_CODEX_BINARY


def _config_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the config path for the effective child environment.

    ``CodexTransport`` may be given a private ``CODEX_HOME``.  Looking at the
    parent process environment here would accidentally enumerate MCP servers
    from the user's regular Codex profile before the child is started.
    """

    effective_env = os.environ if env is None else env
    configured_home = effective_env.get("CODEX_HOME")
    if configured_home:
        return Path(configured_home) / "config.toml"
    return Path.home() / ".codex" / "config.toml"


def _mcp_server_names(
    path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Find all MCP server names without printing any config values.

    Parsing the whole TOML document is intentional: a line-oriented table
    scan misses inline tables, quoted names, and arrays.  When parsing is not
    possible we fail closed instead of starting a process with unknown MCP
    access.
    """

    source = _config_path(env) if path is None else path
    if not source.exists():
        return ()
    try:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef,import-not-found]
        with source.open("rb") as stream:
            document = tomllib.load(stream)
    except ModuleNotFoundError as exc:
        raise CodexTransportError(
            "Codex config cannot be checked for MCP servers; install tomli and retry"
        ) from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise CodexTransportError(
            "Codex config could not be read safely; fix the local config and retry"
        ) from exc
    if not isinstance(document, dict):
        raise CodexTransportError("Codex config is invalid; fix the local config and retry")
    names: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, list):
            for child in value:
                collect(child)
            return
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if key == "mcp_servers":
                if child is None:
                    continue
                if not isinstance(child, dict):
                    raise CodexTransportError(
                        "Codex MCP configuration is invalid; fix the local config and retry"
                    )
                for name in child:
                    if not isinstance(name, str) or not name:
                        raise CodexTransportError(
                            "Codex MCP configuration is invalid; fix the local config and retry"
                        )
                    if name not in names:
                        names.append(name)
            collect(child)

    collect(document)
    return tuple(names)


def _toml_key(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _feature_config() -> dict[str, Any]:
    """Return the stable feature restrictions for a card-only turn."""

    return {
        "features": {
            "shell_tool": False,
            "apps": False,
            "browser_use": False,
            "computer_use": False,
            "plugins": False,
            "multi_agent": False,
            "multi_agent_v2": False,
            "memories": False,
            "skill_search": False,
            "skill_mcp_dependency_install": False,
            "hooks": False,
            "image_generation": False,
            "view_image": False,
            "sleep_tool": False,
            "tool_suggest": False,
            "code_mode_host": False,
        },
        "web_search": "disabled",
        "tools": {"view_image": False},
        # This is deliberately a config value, rather than an attempt to
        # inspect or rewrite the user's Codex configuration.  Per-server
        # overrides below cover named table configs on older app-servers.
        "mcp_servers": {},
    }


def _build_command(
    binary: str,
    extra_args: tuple[str, ...],
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    command = [binary, "app-server", "--listen", "stdio://"]
    for key, value in _feature_config()["features"].items():
        command.extend(("-c", f"features.{key}={str(value).lower()}"))
    command.extend(("-c", 'web_search="disabled"'))
    command.extend(("-c", "tools.view_image=false"))
    # Keep this override independent of the user's model/provider/network or
    # inherited local authentication.  It only removes MCP server access.
    command.extend(("-c", "mcp_servers={}"))
    for name in _mcp_server_names(env=env):
        command.extend(("-c", f"mcp_servers.{_toml_key(name)}.enabled=false"))
    command.extend(extra_args)
    return command


class CodexTransport:
    """Own one local ``codex app-server`` child and its JSONL stream."""

    def __init__(
        self,
        binary: str | os.PathLike[str] | None = None,
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        extra_args: tuple[str, ...] = (),
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        process_factory: Callable[..., Any] | None = None,
    ) -> None:
        if isinstance(max_line_bytes, bool) or not isinstance(max_line_bytes, int):
            raise ValueError("max_line_bytes must be a positive integer")
        if max_line_bytes < 1024:
            raise ValueError("max_line_bytes must be at least 1024")
        if isinstance(queue_size, bool) or not isinstance(queue_size, int):
            raise ValueError("queue_size must be a positive integer")
        if queue_size < 16:
            raise ValueError("queue_size must be at least 16")
        self.binary = resolve_codex_binary(binary)
        self._requested_cwd = None if cwd is None else os.fspath(cwd)
        self._env = None if env is None else dict(env)
        self._extra_args = tuple(extra_args)
        self.max_line_bytes = max_line_bytes
        self.queue_size = queue_size
        self._process_factory = process_factory or subprocess.Popen
        self._process: Any | None = None
        self._cwd_temp: tempfile.TemporaryDirectory[str] | None = None
        self.cwd: str | None = self._requested_cwd
        self._closed = False
        self._request_counter = 0
        self._generation = 0
        self._state_lock = threading.RLock()
        self._start_lock = threading.Lock()
        self._request_lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._incoming: queue.Queue[Any] = queue.Queue(maxsize=queue_size)
        self._pending_notifications: deque[dict[str, Any]] = deque(maxlen=queue_size)
        self._pending_responses: dict[object, dict[str, Any]] = {}
        self._reader_threads: list[threading.Thread] = []
        self._process_grouped = False
        self._process_group_id: int | None = None

    @property
    def process(self) -> Any | None:
        with self._state_lock:
            return self._process

    @property
    def started(self) -> bool:
        with self._state_lock:
            process = self._process
            return process is not None and process.poll() is None

    def _make_cwd(self) -> str:
        if self.cwd is None:
            self._cwd_temp = tempfile.TemporaryDirectory(prefix="tavernlab-codex-")
            self.cwd = self._cwd_temp.name
        Path(self.cwd).mkdir(parents=True, exist_ok=True)
        return self.cwd

    def start(self) -> None:
        """Start the child and reader threads once, lazily."""
        # Serialise startup itself, but never make reset/close acquire this
        # lock.  A factory or a child write can be slow; lifecycle operations
        # must still be able to invalidate the generation and terminate it.
        with self._start_lock:
            with self._state_lock:
                if self._closed:
                    raise CodexTransportError("Codex transport is closed")
                process = self._process
                if process is not None and process.poll() is None:
                    return
                old_queue = self._incoming
                if process is not None:
                    self._generation += 1
                generation = self._generation
                self._incoming = queue.Queue(maxsize=self.queue_size)
                old_process, old_threads, old_grouped, old_group_id = (
                    self._detach_process_locked()
                )
            self._wake_queue(old_queue)
            self._close_process_instance(
                old_process, old_threads, old_grouped, old_group_id
            )

            child_env = os.environ.copy()
            if self._env is not None:
                child_env.update(self._env)
            cwd = self._make_cwd()
            command = _build_command(self.binary, self._extra_args, env=child_env)
            process_kwargs = {
                "cwd": cwd,
                "env": child_env,
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "bufsize": 1,
                "shell": False,
            }
            use_process_group = (
                os.name == "posix" and self._process_factory is subprocess.Popen
            )
            if use_process_group:
                process_kwargs["start_new_session"] = True
            try:
                process = self._process_factory(
                    command,
                    **process_kwargs,
                )
            except (OSError, TypeError) as exc:
                raise CodexTransportError(
                    "Unable to start the Codex app-server; install Codex or set "
                    "TAVERNLAB_CODEX_BINARY to its executable"
                ) from exc

            process_group_id: int | None = None
            if use_process_group:
                try:
                    # Popen(start_new_session=True) creates a session and
                    # process group whose id is the child pid.  Capture it
                    # directly before a fast-exiting leader can be reaped;
                    # descendants may still hold stdout/stderr afterwards.
                    process_group_id = int(process.pid)
                except (AttributeError, TypeError, ValueError):
                    process_group_id = None

            with self._state_lock:
                stale = self._closed or generation != self._generation
                if not stale:
                    incoming = self._incoming
                    self._process = process
                    self._process_grouped = use_process_group
                    self._process_group_id = process_group_id
                    self._reader_threads = [
                        threading.Thread(
                            target=self._read_stdout,
                            args=(process, incoming, generation),
                            name="tavernlab-codex-stdout",
                            daemon=True,
                        ),
                        threading.Thread(
                            target=self._drain_stderr,
                            args=(process,),
                            name="tavernlab-codex-stderr",
                            daemon=True,
                        ),
                    ]
                    threads = list(self._reader_threads)
                else:
                    threads = []
            if stale:
                self._close_process_instance(
                    process, (), use_process_group, process_group_id
                )
                if self._closed:
                    raise CodexTransportError("Codex transport is closed")
                raise CodexTransportError("Codex transport was reset")
            for thread in threads:
                thread.start()

    def _detach_process_locked(
        self,
    ) -> tuple[Any | None, list[threading.Thread], bool, int | None]:
        process = self._process
        threads = self._reader_threads
        grouped = self._process_grouped
        group_id = self._process_group_id
        self._process = None
        self._reader_threads = []
        self._process_grouped = False
        self._process_group_id = None
        return process, threads, grouped, group_id

    def _enqueue(
        self,
        value: Any,
        *,
        incoming: queue.Queue[Any],
        generation: int,
        noisy: bool = False,
    ) -> None:
        # Reader threads retain their process-specific queue.  Once reset or
        # close advances the generation, they can only discard messages and
        # can never inject an EOF/response into a later child session.
        with self._state_lock:
            if generation != self._generation or incoming is not self._incoming:
                return
            try:
                incoming.put_nowait(value)
                return
            except queue.Full:
                if noisy:
                    return
            # Keep the stream bounded.  A full queue is itself a protocol
            # error; preserve a compact marker so the caller resets instead
            # of silently accepting a response after output was dropped.
            try:
                incoming.get_nowait()
            except queue.Empty:
                pass
            try:
                incoming.put_nowait(_ProtocolFailure("Codex output queue overflow"))
            except queue.Full:
                pass

    def _read_stdout(
        self,
        process: Any,
        incoming: queue.Queue[Any],
        generation: int,
    ) -> None:
        stream = getattr(process, "stdout", None)
        if stream is None:
            self._enqueue(
                _ProtocolFailure("Codex stdout is unavailable"),
                incoming=incoming,
                generation=generation,
            )
            self._enqueue(_END_OF_STREAM, incoming=incoming, generation=generation)
            return
        try:
            while True:
                line = stream.readline(self.max_line_bytes + 1)
                if line in ("", b""):
                    break
                if self._line_size(line) > self.max_line_bytes:
                    while not self._line_ended(line):
                        line = stream.readline(self.max_line_bytes + 1)
                        if line in ("", b""):
                            break
                    self._enqueue(
                        _ProtocolFailure("Codex sent an oversized JSON message"),
                        incoming=incoming,
                        generation=generation,
                    )
                    continue
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    self._enqueue(
                        _ProtocolFailure("Codex sent malformed JSON"),
                        incoming=incoming,
                        generation=generation,
                    )
                    continue
                if not isinstance(message, dict):
                    self._enqueue(
                        _ProtocolFailure("Codex sent a non-object JSON message"),
                        incoming=incoming,
                        generation=generation,
                    )
                    continue
                if self._is_server_request(message):
                    self._deny_server_request(message, process, generation)
                    continue
                noisy = message.get("method") in {
                    "item/agentMessage/delta",
                    "command/exec/outputDelta",
                    "process/outputDelta",
                    "item/commandExecution/outputDelta",
                    "item/reasoning/textDelta",
                }
                self._enqueue(
                    message,
                    incoming=incoming,
                    generation=generation,
                    noisy=noisy,
                )
        except Exception:
            # A broken fake stream or a closed pipe is equivalent to EOF for
            # callers; do not publish exception text from the child process.
            self._enqueue(
                _ProtocolFailure("Codex stdout reader failed"),
                incoming=incoming,
                generation=generation,
            )
        finally:
            self._enqueue(_END_OF_STREAM, incoming=incoming, generation=generation)
            try:
                stream.close()
            except Exception:
                pass

    def _drain_stderr(self, process: Any) -> None:
        stream = getattr(process, "stderr", None)
        if stream is None:
            return
        try:
            while True:
                line = stream.readline(self.max_line_bytes + 1)
                if line in ("", b""):
                    break
                while not self._line_ended(line):
                    line = stream.readline(self.max_line_bytes + 1)
                    if line in ("", b""):
                        break
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    @staticmethod
    def _line_size(line: object) -> int:
        if isinstance(line, bytes):
            return len(line)
        if isinstance(line, str):
            return len(line.encode("utf-8", errors="replace"))
        return 0

    @staticmethod
    def _line_ended(line: object) -> bool:
        if isinstance(line, bytes):
            return line.endswith((b"\n", b"\r"))
        if isinstance(line, str):
            return line.endswith(("\n", "\r"))
        return True

    @staticmethod
    def _is_server_request(message: Mapping[str, Any]) -> bool:
        return "id" in message and isinstance(message.get("method"), str)

    def _deny_server_request(
        self,
        message: Mapping[str, Any],
        process: Any,
        generation: int,
    ) -> None:
        request_id = message.get("id")
        try:
            self._send_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32001,
                        "message": "TavernLab card agent denies server requests",
                    },
                },
                process=process,
                generation=generation,
            )
        except CodexTransportError:
            pass

    def _check_generation(self, process: Any, generation: int) -> None:
        with self._state_lock:
            if (
                self._closed
                or generation != self._generation
                or process is not self._process
            ):
                raise CodexTransportError("Codex transport was reset")

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexTransportError("Timed out waiting for Codex app-server")
        return remaining

    def _acquire_interruptibly(
        self,
        lock: threading.Lock | threading.RLock,
        *,
        deadline: float | None,
        process: Any | None = None,
        generation: int | None = None,
    ) -> None:
        while True:
            if process is not None and generation is not None:
                self._check_generation(process, generation)
            elif self._closed:
                raise CodexTransportError("Codex transport is closed")
            remaining = self._remaining(deadline)
            wait = 0.05 if remaining is None else min(remaining, 0.05)
            if lock.acquire(timeout=wait):
                return

    def _write_fd(
        self,
        fd: int,
        encoded: bytes,
        *,
        process: Any,
        generation: int,
        deadline: float | None,
    ) -> None:
        try:
            os.set_blocking(fd, False)
        except (AttributeError, OSError) as exc:
            raise CodexTransportError("Codex app-server input is unavailable") from exc
        offset = 0
        while offset < len(encoded):
            self._check_generation(process, generation)
            remaining = self._remaining(deadline)
            wait = 0.1 if remaining is None else min(remaining, 0.1)
            try:
                _readable, writable, _errors = select.select([], [fd], [], wait)
            except InterruptedError:
                continue
            except (OSError, ValueError) as exc:
                raise CodexTransportError("Codex app-server input is unavailable") from exc
            if not writable:
                continue
            # ``reset``/``close`` detach and close the old descriptor while
            # holding this same lock.  Keep validation and the nonblocking
            # write atomic with respect to that lifecycle transition: a
            # restarted child may otherwise reuse the same fd between
            # select() and os.write().
            with self._state_lock:
                if (
                    self._closed
                    or generation != self._generation
                    or process is not self._process
                ):
                    raise CodexTransportError("Codex transport was reset")
                try:
                    written = os.write(fd, encoded[offset:])
                except BlockingIOError:
                    continue
                except (BrokenPipeError, OSError) as exc:
                    raise CodexTransportError("Codex app-server closed its input") from exc
            if written <= 0:
                raise CodexTransportError("Codex app-server closed its input")
            offset += written

    def _write_stream_thread(
        self,
        stream: Any,
        text: str,
        *,
        process: Any,
        generation: int,
        deadline: float | None,
    ) -> None:
        result: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)

        def writer() -> None:
            try:
                stream.write(text)
                stream.flush()
            except BaseException as exc:  # pragma: no cover - platform/fake seam
                try:
                    result.put_nowait(exc)
                except queue.Full:
                    pass
            else:
                result.put_nowait(None)

        threading.Thread(
            target=writer,
            name="tavernlab-codex-stdin",
            daemon=True,
        ).start()
        while True:
            self._check_generation(process, generation)
            remaining = self._remaining(deadline)
            wait = 0.05 if remaining is None else min(remaining, 0.05)
            try:
                failure = result.get(timeout=wait)
            except queue.Empty:
                continue
            if failure is None:
                return
            raise CodexTransportError("Codex app-server closed its input") from failure

    def _send_message(
        self,
        message: Mapping[str, Any],
        *,
        deadline: float | None = None,
        process: Any | None = None,
        generation: int | None = None,
    ) -> None:
        if process is None or generation is None:
            with self._state_lock:
                process = self._process
                generation = self._generation
        stream = getattr(process, "stdin", None)
        if process is None or process.poll() is not None or stream is None:
            raise CodexTransportError("Codex app-server is not running")
        self._check_generation(process, generation)
        text = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = text.encode("utf-8")
        self._acquire_interruptibly(
            self._write_lock,
            deadline=deadline,
            process=process,
            generation=generation,
        )
        try:
            self._check_generation(process, generation)
            try:
                fd = stream.fileno()
            except (AttributeError, OSError, ValueError):
                fd = None
            if fd is not None:
                self._write_fd(
                    fd,
                    encoded,
                    process=process,
                    generation=generation,
                    deadline=deadline,
                )
            else:
                self._write_stream_thread(
                    stream,
                    text,
                    process=process,
                    generation=generation,
                    deadline=deadline,
                )
        finally:
            self._write_lock.release()

    def send_notification(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        self.start()
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send_message(message)

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        self.send_notification(method, params)

    def _next_message(
        self,
        timeout: float | None,
        generation: int | None = None,
        incoming: queue.Queue[Any] | None = None,
    ) -> Any:
        if incoming is None:
            with self._state_lock:
                incoming = self._incoming
        started = time.monotonic()
        while True:
            if generation is not None:
                with self._state_lock:
                    if generation != self._generation:
                        raise CodexTransportError("Codex transport was reset")
            remaining = None
            if timeout is not None:
                remaining = float(timeout) - (time.monotonic() - started)
                if remaining <= 0:
                    raise CodexTransportError("Timed out waiting for Codex app-server")
                # Polling lets reset/close wake a blocked request promptly.
                remaining = min(remaining, 0.1)
            else:
                # A caller without a deadline must still be interruptible by
                # reset/close from another thread.
                remaining = 0.1
            try:
                value = incoming.get(timeout=remaining)
            except queue.Empty:
                continue
            if generation is not None:
                with self._state_lock:
                    if generation != self._generation:
                        raise CodexTransportError("Codex transport was reset")
            return value

    def _store_pending_response(
        self,
        message: Mapping[str, Any],
        generation: int | None = None,
    ) -> None:
        message_id = self._message_id(message)
        if message_id is None:
            raise CodexTransportError("Codex app-server sent an invalid response")
        with self._state_lock:
            if generation is not None and generation != self._generation:
                raise CodexTransportError("Codex transport was reset")
            if len(self._pending_responses) >= self.queue_size:
                oldest = next(iter(self._pending_responses))
                del self._pending_responses[oldest]
            self._pending_responses[message_id] = dict(message)

    @staticmethod
    def _message_id(message: Mapping[str, Any]) -> object | None:
        if "id" not in message:
            return None
        value = message.get("id")
        # JSON-RPC request IDs are strings or numbers.  Reject booleans and
        # containers before they reach the bounded pending-response map.
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return None
        return value

    def _consume_message(
        self,
        message: Any,
        request_id: object,
        generation: int,
    ) -> dict[str, Any] | None:
        if isinstance(message, _ProtocolFailure):
            raise CodexTransportError(message.reason)
        if message is _END_OF_STREAM:
            raise CodexTransportError("Codex app-server exited unexpectedly")
        if not isinstance(message, dict):
            raise CodexTransportError("Codex app-server sent an invalid message")
        if "method" in message:
            with self._state_lock:
                if generation != self._generation:
                    raise CodexTransportError("Codex transport was reset")
                self._pending_notifications.append(message)
            return None
        message_id = self._message_id(message)
        if message_id == request_id:
            return message
        if message_id is not None:
            self._store_pending_response(message, generation)
        else:
            raise CodexTransportError("Codex app-server sent an invalid response")
        return None

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Send one request and return its result payload."""
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        self._acquire_interruptibly(self._request_lock, deadline=deadline)
        try:
            self.start()
            with self._state_lock:
                process = self._process
                generation = self._generation
                incoming = self._incoming
                self._request_counter += 1
                request_id = self._request_counter
            self._send_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                },
                deadline=deadline,
                process=process,
                generation=generation,
            )
        finally:
            self._request_lock.release()
        while True:
            with self._state_lock:
                if generation != self._generation:
                    raise CodexTransportError("Codex transport was reset")
                response = self._pending_responses.pop(request_id, None)
            if response is not None:
                break
            if deadline is None:
                remaining = None
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CodexTransportError("Timed out waiting for Codex response")
            response = self._consume_message(
                self._next_message(remaining, generation, incoming),
                request_id,
                generation,
            )
            if response is not None:
                break
        if "error" in response:
            # Do not include server diagnostics, which can contain account or
            # environment details, in an application error.
            raise CodexTransportError("Codex app-server rejected the request")
        if "result" not in response:
            raise CodexTransportError("Codex app-server sent an invalid response")
        return response["result"]

    def wait_for_notification(
        self,
        predicate: Callable[[Mapping[str, Any]], bool] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Wait for one notification, discarding stale unmatched events."""

        started = time.monotonic()
        with self._state_lock:
            generation = self._generation
            incoming = self._incoming
        while True:
            with self._state_lock:
                if generation != self._generation:
                    raise CodexTransportError("Codex transport was reset")
            message: Any | None = None
            with self._state_lock:
                if self._pending_notifications:
                    message = self._pending_notifications.popleft()
            if message is None:
                remaining = None
                if timeout is not None:
                    remaining = float(timeout) - (time.monotonic() - started)
                    if remaining <= 0:
                        raise CodexTransportError("Timed out waiting for Codex notification")
                message = self._next_message(remaining, generation, incoming)
            if isinstance(message, _ProtocolFailure):
                raise CodexTransportError(message.reason)
            if message is _END_OF_STREAM:
                raise CodexTransportError("Codex app-server exited unexpectedly")
            if not isinstance(message, dict):
                raise CodexTransportError("Codex app-server sent an invalid notification")
            if "method" not in message:
                # Responses can be queued while a fake or another caller is
                # waiting.  Preserve them for the corresponding request.
                message_id = self._message_id(message)
                if message_id is not None:
                    self._store_pending_response(message, generation)
                continue
            if predicate is None or predicate(message):
                return message

    @staticmethod
    def _wake_queue(incoming: queue.Queue[Any]) -> None:
        try:
            incoming.put_nowait(_END_OF_STREAM)
            return
        except queue.Full:
            pass
        try:
            incoming.get_nowait()
        except queue.Empty:
            pass
        try:
            incoming.put_nowait(_END_OF_STREAM)
        except queue.Full:
            pass

    def _close_process_instance(
        self,
        process: Any | None,
        threads: tuple[threading.Thread, ...] | list[threading.Thread],
        grouped: bool = False,
        group_id: int | None = None,
    ) -> None:
        if process is None:
            return
        stream = getattr(process, "stdin", None)
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        if grouped and os.name == "posix":
            if group_id is None:
                try:
                    group_id = os.getpgid(process.pid)
                except (AttributeError, OSError, ValueError):
                    group_id = None
        try:
            if group_id is not None:
                try:
                    os.killpg(group_id, signal.SIGTERM)
                except OSError:
                    pass
            elif process.poll() is None:
                process.terminate()
            process.wait(timeout=0.5)
        except Exception:
            try:
                if group_id is not None:
                    try:
                        os.killpg(group_id, signal.SIGKILL)
                    except OSError:
                        pass
                elif process.poll() is None:
                    process.kill()
                process.wait(timeout=0.5)
            except Exception:
                pass
        if group_id is not None:
            # The direct child may have exited while a descendant still owns
            # stdout/stderr.  The group id was captured at spawn time, so it
            # remains usable after the group leader has reaped.
            try:
                os.killpg(group_id, signal.SIGKILL)
            except OSError:
                pass
        # The stdout/stderr readers own their TextIOWrapper instances and
        # close them in their finally blocks.  Closing a wrapper here can
        # wait forever for a reader blocked on a pipe inherited by a child.
        for thread in threads:
            if thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=0.1)

    def reset(self) -> None:
        """Discard the current child and protocol queues, allowing restart."""
        with self._state_lock:
            if self._closed:
                return
            self._generation += 1
            old_queue = self._incoming
            self._incoming = queue.Queue(maxsize=self.queue_size)
            process, threads, grouped, group_id = self._detach_process_locked()
            self._pending_notifications.clear()
            self._pending_responses.clear()
        self._wake_queue(old_queue)
        self._close_process_instance(process, threads, grouped, group_id)

    def close(self) -> None:
        """Terminate the child and release the isolated temporary directory."""
        with self._state_lock:
            self._closed = True
            self._generation += 1
            old_queue = self._incoming
            self._incoming = queue.Queue(maxsize=self.queue_size)
            process, threads, grouped, group_id = self._detach_process_locked()
            self._pending_notifications.clear()
            self._pending_responses.clear()
            if self._cwd_temp is not None:
                self._cwd_temp.cleanup()
                self._cwd_temp = None
        self._wake_queue(old_queue)
        self._close_process_instance(process, threads, grouped, group_id)

    def _drain_incoming(self, incoming: queue.Queue[Any] | None = None) -> None:
        if incoming is None:
            with self._state_lock:
                incoming = self._incoming
        while True:
            try:
                incoming.get_nowait()
            except queue.Empty:
                return


__all__ = [
    "CodexTransport",
    "CodexTransportError",
    "DEFAULT_CODEX_BINARY",
    "resolve_codex_binary",
]
