"""Explicit connection management for the user's Codex account.

Importing this module is passive.  It does not start a Codex process, inspect
the normal Codex profile, make a network request, or create a state directory.
A manager uses its effective ``CODEX_HOME`` only after an explicit
connect/check/test operation (or when the first card transport is created).

``proxy_url`` is an optional HTTP(S) proxy consisting of a host and optional
port.  Credentials, query strings, fragments, and path components are not
accepted.  A blank value means inherit the caller's proxy environment.  When
set, the same proxy value and effective ``CODEX_HOME`` are passed to every
child transport created by this manager, including authentication and card
calls.  The manager never copies credentials between Codex homes.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import weakref
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from ..codex_transport import (
    DEFAULT_CODEX_BINARY,
    CodexTransport,
    CodexTransportError,
    resolve_codex_binary,
)


DEFAULT_LOGIN_TIMEOUT = 10 * 60.0
DEFAULT_CHECK_TIMEOUT = 30.0
DEFAULT_TEST_TIMEOUT = 45.0
SETTINGS_MODE = 0o600
HOME_MODE = 0o700

ERROR_UNAVAILABLE = (
    "Codex CLI executable is unavailable. Install Codex CLI or set an executable binary "
    "in Codex settings."
)
ERROR_NO_ACCOUNT = (
    "No Codex account is connected. Run codex login with the profile used by "
    "TavernLab, then retry."
)
ERROR_NETWORK = "Codex could not reach the OpenAI service. Check your network or proxy settings and retry."
ERROR_CHECK = "Codex account check failed. Verify Codex installation, login, and proxy settings, then retry."
ERROR_LOGIN_URL = "Codex returned an unsafe login URL. Start login again or update Codex."
ERROR_LOGIN_TIMEOUT = "Codex login timed out. Retry Connect and finish sign-in in the browser."
ERROR_TEST = "Codex connection test failed. Verify the selected model and retry."
ERROR_SETTINGS = "Codex settings could not be read or saved. Check the settings path and retry."

_ALLOWED_SETTINGS = frozenset({"proxy_url", "binary_path"})
_LOGIN_EVENTS = frozenset({"account/login/completed", "account/updated"})


def resolve_external_binary(value: str | os.PathLike[str] | None = None) -> str:
    """Resolve the shared external Codex executable without starting it."""

    return resolve_codex_binary(value)


def _validate_proxy_url(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("proxy_url must be an HTTP(S) URL or blank")
    value = value.strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("proxy_url must use http or https")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("proxy_url must contain a host without credentials")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("proxy_url may contain only a host and optional port")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("proxy_url has an invalid port") from exc
    return value


def _validate_binary_setting(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("binary_path must be an absolute executable path or blank")
    value = value.strip()
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("binary_path must be an absolute executable path or blank")
    return str(path)


def _safe_text(value: object, *, limit: int = 320) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        return None
    return value


def _safe_account(value: object) -> dict[str, str] | None:
    """Extract only the two public account fields used by the web UI."""

    if not isinstance(value, Mapping):
        return None
    candidate = value.get("account")
    if not isinstance(candidate, Mapping):
        # Small injected transports and older app-servers may return the
        # account object directly.  Do not recurse into arbitrary envelopes.
        candidate = value
    account_type = candidate.get("type")
    if account_type is not None and account_type != "chatgpt":
        return None
    email = _safe_text(candidate.get("email")) or ""
    plan_type = _safe_text(candidate.get("planType"))
    if plan_type is None:
        plan_type = _safe_text(candidate.get("plan_type"))
    if not email and plan_type is None and account_type != "chatgpt":
        return None
    return {"email": email, "plan_type": plan_type or ""}


def _login_url(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for key in ("auth_url", "authUrl"):
        text = _safe_text(value.get(key), limit=2048)
        if text is not None:
            return text
    return None


def _safe_model(value: object) -> str | None:
    if value is None:
        return None
    return _safe_text(value, limit=160)


class CodexConnection:
    """Manage one explicitly user-triggered Codex connection."""

    def __init__(
        self,
        *,
        home: str | os.PathLike[str] | None = None,
        state_home: str | os.PathLike[str] | None = None,
        settings_path: str | os.PathLike[str] | None = None,
        auth_home: str | os.PathLike[str] | None = None,
        transport_factory: Callable[..., Any] | None = None,
        agent_factory: Callable[..., Any] | None = None,
        binary_resolver: Callable[[str | os.PathLike[str] | None], str] | None = None,
        login_timeout: float = DEFAULT_LOGIN_TIMEOUT,
    ) -> None:
        if isinstance(login_timeout, bool) or not isinstance(login_timeout, (int, float)):
            raise ValueError("login_timeout must be a positive number")
        if float(login_timeout) <= 0:
            raise ValueError("login_timeout must be a positive number")
        injected_home = home is not None or settings_path is not None
        if home is None and settings_path is not None:
            home = Path(settings_path).expanduser().parent
        self.home = self._resolve_home(home, state_home)
        self.settings_path = (
            Path(settings_path).expanduser()
            if settings_path is not None
            else self.home / "settings.json"
        )
        self.auth_home, self._shared_login = self._resolve_auth_home(
            auth_home,
            self.home,
            injected_home=injected_home,
        )
        self._transport_factory = transport_factory
        self._agent_factory = agent_factory
        self._binary_resolver = binary_resolver or resolve_external_binary
        self._login_timeout = float(login_timeout)

        self._lock = threading.RLock()
        self._auth_lock = threading.RLock()
        self._proxy_url = ""
        self._binary_setting = ""
        self._settings_error: str | None = None
        self._account: dict[str, str] | None = None
        self._error: str | None = None
        self._closed = False
        self._generation = 0
        self._transports: weakref.WeakSet[Any] = weakref.WeakSet()
        self._login_transport: Any | None = None
        self._login_thread: threading.Thread | None = None
        self._login_cancel: threading.Event | None = None
        self._login_auth_url: str | None = None
        self._login_id: str | None = None
        self._login_pending = False
        self._load_settings()

    @staticmethod
    def _resolve_home(
        home: str | os.PathLike[str] | None,
        state_home: str | os.PathLike[str] | None,
    ) -> Path:
        if home is not None:
            return Path(home).expanduser()
        base = state_home
        if base is None:
            base = os.environ.get("XDG_STATE_HOME")
        if base is None:
            base = Path.home() / ".local" / "state"
        return Path(base).expanduser() / "fireplace" / "codex"

    @staticmethod
    def _resolve_auth_home(
        auth_home: str | os.PathLike[str] | None,
        state_home: Path,
        *,
        injected_home: bool,
    ) -> tuple[Path, bool]:
        """Resolve the Codex profile separately from the game's state path.

        Explicit constructor paths remain useful for tests and embedding
        applications, so they retain the old isolated-home behavior.  The
        normal factory uses an opt-in TavernLab override when present and
        otherwise reuses the profile selected by the external Codex CLI.
        """

        if auth_home is not None:
            return Path(auth_home).expanduser(), False
        if injected_home:
            return state_home, False
        configured = os.environ.get("TAVERNLAB_CODEX_HOME")
        if configured:
            return Path(configured).expanduser(), False
        configured = os.environ.get("CODEX_HOME")
        if configured:
            return Path(configured).expanduser(), True
        return Path.home() / ".codex", True

    def _load_settings(self) -> None:
        try:
            with self.settings_path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
            if not isinstance(raw, Mapping) or set(raw) - _ALLOWED_SETTINGS:
                raise ValueError
            self._proxy_url = _validate_proxy_url(raw.get("proxy_url", ""))
            stored_binary = raw.get("binary_path", "")
            if stored_binary in (None, ""):
                self._binary_setting = ""
            elif isinstance(stored_binary, str) and Path(stored_binary).is_absolute():
                # A previously valid executable may be temporarily absent
                # after an upgrade.  Keep it for status diagnostics; saving
                # a new value still requires a current executable.
                self._binary_setting = stored_binary
            else:
                raise ValueError
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            self._settings_error = ERROR_SETTINGS

    def _ensure_home(self) -> None:
        self.auth_home.mkdir(parents=True, exist_ok=True, mode=HOME_MODE)
        # The default profile belongs to the user's Codex CLI.  Preserve its
        # existing permissions; an isolated TavernLab profile keeps the old
        # private-directory guarantee.
        if not self._shared_login:
            try:
                os.chmod(self.auth_home, HOME_MODE)
            except OSError:
                pass

    def _binary_path(self) -> str:
        if self._binary_setting:
            return self._binary_setting
        try:
            value = os.fspath(self._binary_resolver(None))
            if isinstance(value, bytes):
                return os.fsdecode(value)
            return value
        except Exception:
            return DEFAULT_CODEX_BINARY

    @staticmethod
    def _is_executable(path: str) -> bool:
        resolved = shutil.which(path) if os.sep not in path else path
        return bool(resolved and Path(resolved).is_file() and os.access(resolved, os.X_OK))

    def _status_locked(self) -> dict[str, Any]:
        binary_path = self._binary_path()
        available = self._is_executable(binary_path)
        error = self._error or self._settings_error
        if not available and error is None:
            error = ERROR_UNAVAILABLE
        return {
            "available": available,
            "connected": self._account is not None,
            "shared_login": self._shared_login,
            "account": dict(self._account) if self._account is not None else None,
            "login_pending": self._login_pending,
            "error": error,
            "proxy_url": self._proxy_url,
            # Keep blank as blank for auto-detection.  Returning the resolved
            # fallback here would make the UI save a machine-specific path
            # that may not exist on the next host.
            "binary_path": self._binary_setting,
        }

    def status(self) -> dict[str, Any]:
        """Return cached state without starting a child or contacting Codex."""

        with self._lock:
            return self._status_locked()

    def _status_result_locked(self, **extra: Any) -> dict[str, Any]:
        result = self._status_locked()
        result.update(extra)
        return result

    def _child_env(self) -> dict[str, str]:
        env = {"CODEX_HOME": str(self.auth_home)}
        if self._proxy_url:
            for key in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env[key] = self._proxy_url
        return env

    def _create_transport(self) -> Any:
        """Create a lazy transport owned by this still-live manager."""

        with self._lock:
            if self._closed:
                raise CodexTransportError("Codex connection is closed")
            binary = self._binary_path()
            env = self._child_env()
            if self._transport_factory is None:
                transport = CodexTransport(binary, env=env)
            else:
                try:
                    transport = self._transport_factory(binary, env)
                except TypeError:
                    transport = self._transport_factory(binary=binary, env=env)
            try:
                self._transports.add(transport)
            except TypeError:
                # A test double may intentionally be unhashable.  It is still
                # usable; its lifecycle is handled by the caller's finally.
                pass
            return transport

    def create_transport(self) -> Any:
        """Create a lazy transport using this manager's effective environment."""

        with self._lock:
            if self._closed:
                raise CodexTransportError("Codex connection is closed")
        self._ensure_home()
        return self._create_transport()

    def _forget_transport_locked(self, transport: Any) -> None:
        try:
            self._transports.discard(transport)
        except TypeError:
            pass

    @staticmethod
    def _close_transport(transport: Any) -> None:
        close = getattr(transport, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _request(self, transport: Any, method: str, params: Mapping[str, Any], timeout: float) -> Any:
        request = getattr(transport, "request", None)
        if not callable(request):
            raise CodexTransportError("missing request method")
        return request(method, dict(params), timeout=timeout)

    def _initialize(self, transport: Any, timeout: float) -> None:
        start = getattr(transport, "start", None)
        if callable(start):
            start()
        self._request(
            transport,
            "initialize",
            {
                "clientInfo": {
                    "name": "tavernlab-codex-connection",
                    "title": "TavernLab Codex Connection",
                    "version": "1",
                }
            },
            timeout,
        )
        notify = getattr(transport, "notify", None)
        if not callable(notify):
            notify = getattr(transport, "send_notification", None)
        if callable(notify):
            notify("initialized")

    def _set_error(self, value: str | None) -> None:
        with self._lock:
            self._error = value

    @staticmethod
    def _failure_diagnostic(exc: BaseException, *, operation: str) -> str:
        # Classify locally while deliberately excluding exception text: server
        # diagnostics can contain account identifiers, tokens, or proxy data.
        name = type(exc).__name__.lower()
        if isinstance(exc, (FileNotFoundError, PermissionError)) or "executable" in name:
            return ERROR_UNAVAILABLE
        if isinstance(exc, (TimeoutError, ConnectionError)) or any(
            token in name for token in ("network", "connect", "timeout")
        ):
            return ERROR_NETWORK
        return ERROR_TEST if operation == "test" else ERROR_CHECK

    def check(self) -> dict[str, Any]:
        """Explicitly initialize Codex and refresh ``account/read``."""

        with self._auth_lock:
            with self._lock:
                if self._login_pending:
                    return self._status_result_locked()
                if self._closed:
                    return self._status_result_locked()
                operation_generation = self._generation
            self._ensure_home()
            with self._lock:
                if self._closed or operation_generation != self._generation:
                    return self._status_locked()
                if not self._is_executable(self._binary_path()):
                    self._account = None
                    self._error = ERROR_UNAVAILABLE
                    return self._status_locked()
            try:
                transport = self._create_transport()
            except BaseException as exc:
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_locked()
                    self._account = None
                    self._error = self._failure_diagnostic(exc, operation="check")
                    return self._status_locked()
            try:
                self._initialize(transport, DEFAULT_CHECK_TIMEOUT)
                result = self._request(
                    transport,
                    "account/read",
                    {"refreshToken": False},
                    DEFAULT_CHECK_TIMEOUT,
                )
                account = _safe_account(result)
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_locked()
                    self._account = account
                    self._error = None if account is not None else ERROR_NO_ACCOUNT
                    return self._status_locked()
            except BaseException as exc:
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_locked()
                    self._account = None
                    self._error = self._failure_diagnostic(exc, operation="check")
                    return self._status_locked()
            finally:
                with self._lock:
                    self._forget_transport_locked(transport)
                self._close_transport(transport)

    def connect(self) -> dict[str, Any]:
        """Compatibility alias for the explicit account check operation."""

        return self.check()

    def _invalidate_login_locked(self) -> tuple[Any | None, threading.Event | None, threading.Thread | None]:
        self._generation += 1
        cancel = self._login_cancel
        if cancel is not None:
            cancel.set()
        transport = self._login_transport
        thread = self._login_thread
        self._login_cancel = None
        self._login_transport = None
        self._login_thread = None
        self._login_auth_url = None
        self._login_id = None
        self._login_pending = False
        return transport, cancel, thread

    def start_login(self) -> dict[str, Any]:
        """Start the explicit ChatGPT login flow and return a safe URL/status."""

        with self._auth_lock:
            with self._lock:
                if self._login_pending:
                    return self._status_result_locked(auth_url=self._login_auth_url)
                if self._closed:
                    return self._status_result_locked(auth_url=None)
                operation_generation = self._generation
            self._ensure_home()
            with self._lock:
                if self._closed or operation_generation != self._generation:
                    return self._status_result_locked(auth_url=None)
                if not self._is_executable(self._binary_path()):
                    self._error = ERROR_UNAVAILABLE
                    return self._status_result_locked(auth_url=None)
            try:
                transport = self._create_transport()
            except BaseException as exc:
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_result_locked(auth_url=None)
                    self._error = self._failure_diagnostic(exc, operation="check")
                    return self._status_result_locked(auth_url=None)
            try:
                self._initialize(transport, DEFAULT_CHECK_TIMEOUT)
                result = self._request(
                    transport,
                    "account/login/start",
                    {"type": "chatgpt"},
                    DEFAULT_CHECK_TIMEOUT,
                )
                auth_url = _login_url(result)
                if auth_url is None or not self._is_safe_login_url(auth_url):
                    raise ValueError("unsafe login URL")
                login_id = None
                if isinstance(result, Mapping):
                    login_id = _safe_text(result.get("loginId")) or _safe_text(result.get("login_id"))
            except BaseException as exc:
                with self._lock:
                    self._forget_transport_locked(transport)
                    if self._closed or operation_generation != self._generation:
                        result = self._status_result_locked(auth_url=None)
                    else:
                        self._error = (
                            ERROR_LOGIN_URL
                            if isinstance(exc, ValueError)
                            else self._failure_diagnostic(exc, operation="check")
                        )
                        result = self._status_result_locked(auth_url=None)
                self._close_transport(transport)
                return result
            cancel = threading.Event()
            with self._lock:
                if self._closed or operation_generation != self._generation:
                    self._forget_transport_locked(transport)
                    stale = True
                else:
                    stale = False
                    self._generation += 1
                    generation = self._generation
                    self._login_transport = transport
                    self._login_cancel = cancel
                    self._login_auth_url = auth_url
                    self._login_id = login_id
                    self._login_pending = True
                    self._error = None
                    thread = threading.Thread(
                        target=self._login_waiter,
                        args=(generation, transport, cancel),
                        name="tavernlab-codex-login",
                        daemon=True,
                    )
                    self._login_thread = thread
                    thread.start()
                    result = self._status_result_locked(auth_url=auth_url)
            if stale:
                self._close_transport(transport)
                return self.status()
            return result

    @staticmethod
    def _is_safe_login_url(value: str) -> bool:
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").lower().rstrip(".")
            return (
                parsed.scheme.lower() == "https"
                and parsed.username is None
                and parsed.password is None
                and (host == "auth.openai.com" or host == "chatgpt.com" or host.endswith(".chatgpt.com"))
            )
        except ValueError:
            return False

    def _login_waiter(self, generation: int, transport: Any, cancel: threading.Event) -> None:
        deadline = time.monotonic() + self._login_timeout
        with self._lock:
            expected_login_id = self._login_id
        while not cancel.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._finish_login(generation, transport, cancel, None, ERROR_LOGIN_TIMEOUT)
                return
            wait_for = getattr(transport, "wait_for_notification", None)
            if not callable(wait_for):
                self._finish_login(generation, transport, cancel, None, ERROR_CHECK)
                return
            try:
                event = wait_for(timeout=min(remaining, 1.0))
            except BaseException as exc:
                if cancel.is_set():
                    return
                if self._is_notification_timeout(exc):
                    continue
                self._finish_login(
                    generation,
                    transport,
                    cancel,
                    None,
                    self._failure_diagnostic(exc, operation="check"),
                )
                return
            if not isinstance(event, Mapping) or event.get("method") not in _LOGIN_EVENTS:
                continue
            params = event.get("params")
            if not isinstance(params, Mapping):
                continue
            event_login_id = _safe_text(params.get("loginId")) or _safe_text(params.get("login_id"))
            if event_login_id is not None and event_login_id != expected_login_id:
                continue
            if expected_login_id is not None and event_login_id != expected_login_id:
                continue
            if event.get("method") == "account/login/completed":
                success = params.get("success")
                if success is False:
                    self._finish_login(generation, transport, cancel, False, ERROR_CHECK)
                    return
                if success is True:
                    self._finish_login(generation, transport, cancel, True, None)
                    return
                continue
            auth_mode = params.get("authMode")
            if auth_mode is None:
                auth_mode = params.get("auth_mode")
            if auth_mode == "chatgpt":
                # An update is only a useful completion signal once the
                # account/read refresh returns an actual account object.  A
                # positive-looking event with no account must not turn an
                # unfinished browser login into a connected state.
                finished = self._finish_login(
                    generation,
                    transport,
                    cancel,
                    True,
                    None,
                    require_account=True,
                )
                if finished:
                    return

    @staticmethod
    def _is_notification_timeout(exc: BaseException) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        if not isinstance(exc, CodexTransportError):
            return False
        # CodexTransport deliberately keeps its public error type stable.
        # This text is used only for local control flow and is never returned
        # to the caller.
        message = str(exc).lower()
        return any(
            phrase in message
            for phrase in (
                "timed out waiting for codex notification",
                "timed out waiting for codex app-server",
            )
        )

    def _finish_login(
        self,
        generation: int,
        transport: Any,
        cancel: threading.Event,
        completed: bool | None,
        error: str | None,
        *,
        require_account: bool = False,
    ) -> bool:
        if cancel.is_set():
            return False
        if completed:
            try:
                result = self._request(
                    transport,
                    "account/read",
                    {"refreshToken": False},
                    DEFAULT_CHECK_TIMEOUT,
                )
                account = _safe_account(result)
            except BaseException as exc:
                account = None
                error = self._failure_diagnostic(exc, operation="check")
            if require_account and account is None and error is None:
                return False
        else:
            account = None
        to_close: Any | None = None
        with self._auth_lock:
            with self._lock:
                if (
                    cancel.is_set()
                    or generation != self._generation
                    or transport is not self._login_transport
                ):
                    return False
                if completed:
                    self._account = account
                self._error = error or (None if account is not None else ERROR_NO_ACCOUNT)
                self._login_pending = False
                self._login_auth_url = None
                self._login_cancel = None
                self._login_thread = None
                self._login_transport = None
                self._login_id = None
                self._forget_transport_locked(transport)
                to_close = transport
        self._close_transport(to_close)
        return True

    def cancel_login(self) -> dict[str, Any]:
        """Cancel the pending login and close its dedicated child process."""

        with self._auth_lock:
            with self._lock:
                transport, cancel, thread = self._invalidate_login_locked()
                self._error = None
                self._forget_transport_locked(transport) if transport is not None else None
            self._close_transport(transport)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=0.2)
            return self.status()

    def logout(self) -> dict[str, Any]:
        """Explicitly sign out of this manager's effective Codex home."""

        with self._auth_lock:
            with self._lock:
                if self._closed:
                    return self._status_locked()
                pending, _cancel, thread = self._invalidate_login_locked()
                operation_generation = self._generation
                active_transports = list(self._transports)
                self._transports.clear()
                if pending is not None and pending not in active_transports:
                    active_transports.append(pending)
                self._account = None
            for transport in active_transports:
                self._close_transport(transport)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=0.2)
            self._ensure_home()
            with self._lock:
                if self._closed or operation_generation != self._generation:
                    return self._status_locked()
                if not self._is_executable(self._binary_path()):
                    self._error = ERROR_UNAVAILABLE
                    return self._status_locked()
            try:
                transport = self._create_transport()
            except BaseException as exc:
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_locked()
                    self._error = self._failure_diagnostic(exc, operation="check")
                    return self._status_locked()
            try:
                self._initialize(transport, DEFAULT_CHECK_TIMEOUT)
                self._request(transport, "account/logout", {}, DEFAULT_CHECK_TIMEOUT)
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_locked()
                    self._error = None
                    return self._status_locked()
            except BaseException as exc:
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        return self._status_locked()
                    self._error = self._failure_diagnostic(exc, operation="check")
                    return self._status_locked()
            finally:
                with self._lock:
                    self._forget_transport_locked(transport)
                self._close_transport(transport)

    def test_connection(self, model: str | None = None) -> dict[str, Any]:
        """Run one bounded two-action CodexAgent decision after account check."""

        safe_model = _safe_model(model)
        if model is not None and safe_model is None:
            with self._lock:
                if self._closed:
                    result = self._status_locked()
                    result["success"] = False
                    return result
                self._error = ERROR_TEST
                return self._status_result_locked(success=False)
        with self._auth_lock:
            checked = self.check()
            if not checked["connected"]:
                checked["success"] = False
                return checked
            with self._lock:
                if self._closed:
                    checked = self._status_locked()
                    checked["success"] = False
                    return checked
                operation_generation = self._generation
            try:
                transport = self._create_transport()
            except BaseException:
                with self._lock:
                    result = self._status_locked()
                    result["success"] = False
                    return result
            agent = None
            try:
                if self._agent_factory is None:
                    from ..codex_agent import CodexAgent

                    agent_type = CodexAgent
                else:
                    agent_type = self._agent_factory
                agent = agent_type(
                    model=safe_model,
                    timeout=DEFAULT_TEST_TIMEOUT,
                    transport=transport,
                )
                from ..agent_api import Action

                agent.choose_action(
                    {"phase": "MAIN", "self": {}, "opponent": {}},
                    [Action(type="END_TURN"), Action(type="CONCEDE")],
                )
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        result = self._status_locked()
                        result["success"] = False
                        return result
                    self._error = None
                    return self._status_result_locked(success=True)
            except BaseException:
                with self._lock:
                    if self._closed or operation_generation != self._generation:
                        result = self._status_locked()
                        result["success"] = False
                        return result
                    self._error = ERROR_TEST
                    return self._status_result_locked(success=False)
            finally:
                close_agent = getattr(agent, "close", None)
                if callable(close_agent):
                    try:
                        close_agent()
                    except Exception:
                        pass
                with self._lock:
                    self._forget_transport_locked(transport)
                self._close_transport(transport)

    def save_settings(self, settings: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and atomically persist non-secret connection settings."""

        if not isinstance(settings, Mapping):
            raise ValueError("settings must be a mapping")
        unknown = set(settings) - _ALLOWED_SETTINGS
        if unknown:
            raise ValueError("unsupported Codex settings")
        proxy = _validate_proxy_url(settings.get("proxy_url", self._proxy_url))
        if "binary_path" in settings:
            binary = _validate_binary_setting(settings.get("binary_path"))
        else:
            binary = self._binary_setting
        payload = {"proxy_url": proxy, "binary_path": binary}

        with self._auth_lock:
            with self._lock:
                if self._closed:
                    return self._status_locked()
            self.settings_path.parent.mkdir(parents=True, exist_ok=True, mode=HOME_MODE)
            temporary: str | None = None
            try:
                fd, temporary = tempfile.mkstemp(
                    prefix=".settings-",
                    suffix=".tmp",
                    dir=str(self.settings_path.parent),
                )
                os.fchmod(fd, SETTINGS_MODE)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.settings_path)
                temporary = None
                try:
                    os.chmod(self.settings_path, SETTINGS_MODE)
                except OSError:
                    pass
            except (OSError, TypeError, ValueError) as exc:
                if temporary is not None:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                raise ValueError(ERROR_SETTINGS) from exc

            with self._lock:
                if self._closed:
                    return self._status_locked()
                self._generation += 1
                transport_values = list(self._transports)
                self._transports.clear()
                login_transport, _cancel, thread = self._invalidate_login_locked()
                if login_transport is not None and login_transport not in transport_values:
                    transport_values.append(login_transport)
                self._proxy_url = proxy
                self._binary_setting = binary
                self._settings_error = None
                self._error = None
            for transport in transport_values:
                self._close_transport(transport)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=0.2)
            return self.status()

    def close(self) -> None:
        """Invalidate login results and close every child owned by the manager."""

        # Do not wait for the authentication-operation lock here.  A check,
        # login start, or test can be blocked in a child RPC for tens of
        # seconds; shutdown must still invalidate its generation immediately.
        with self._lock:
            self._closed = True
            self._generation += 1
            login_transport, _cancel, thread = self._invalidate_login_locked()
            transports = list(self._transports)
            self._transports.clear()
            if login_transport is not None and login_transport not in transports:
                transports.append(login_transport)
            self._account = None
            self._error = None
        for transport in transports:
            self._close_transport(transport)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.2)

    def __enter__(self) -> "CodexConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


CodexConnectionManager = CodexConnection


_singleton_lock = threading.Lock()
_singleton: CodexConnection | None = None


def get_codex_connection() -> CodexConnection:
    """Return the process-local connection manager singleton."""

    global _singleton
    with _singleton_lock:
        if _singleton is None or _singleton._closed:
            _singleton = CodexConnection()
        return _singleton


__all__ = [
    "CodexConnection",
    "CodexConnectionManager",
    "DEFAULT_LOGIN_TIMEOUT",
    "ERROR_CHECK",
    "ERROR_LOGIN_TIMEOUT",
    "ERROR_LOGIN_URL",
    "ERROR_NETWORK",
    "ERROR_NO_ACCOUNT",
    "ERROR_TEST",
    "ERROR_UNAVAILABLE",
    "get_codex_connection",
    "resolve_external_binary",
]
