"""Desktop launcher for the user-scoped TavernLab web service.

The Debian launcher invokes this module instead of starting the web server in
the foreground.  The server itself is owned by ``tavernlab.service``; this
module only manages that unit, waits for the exact service process to bind the
configured loopback socket, and opens the local UI.

Only the Python standard library is used here so the launcher remains usable
when an installation is still being repaired or when optional game packages
are unavailable.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.request import ProxyHandler, build_opener


SERVICE_UNIT = "tavernlab.service"
SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 8765
SERVICE_URL = f"http://{SERVICE_HOST}:{SERVICE_PORT}/"
STARTUP_TIMEOUT = 15.0
POLL_INTERVAL = 0.1
READINESS_REQUEST_TIMEOUT = 1.0
SYSTEMCTL_TIMEOUT = 5.0
SYSTEMCTL = "systemctl"


class LauncherError(RuntimeError):
    """An actionable error which should be shown to the desktop user."""


class ReadinessError(LauncherError):
    """The service did not safely become ready for browser use."""


@dataclass(frozen=True)
class ServiceStatus:
    """The subset of systemd state needed by the launcher."""

    active_state: str
    sub_state: str
    main_pid: int

    @property
    def running(self) -> bool:
        """Return whether systemd reports a process-backed active unit."""

        return self.active_state == "active" and self.main_pid > 0

    def describe(self) -> str:
        return (
            f"ActiveState={self.active_state or 'unknown'}, "
            f"SubState={self.sub_state or 'unknown'}, MainPID={self.main_pid}"
        )


def _run_command(
    command: list[str],
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with captured text output and a useful OS error."""

    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise LauncherError(
            f"Required command {command[0]!r} was not found; install systemd "
            "and ensure it is available in PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        rendered = " ".join(command)
        raise LauncherError(f"Command timed out while running: {rendered}") from exc
    except OSError as exc:
        rendered = " ".join(command)
        raise LauncherError(f"Could not run {rendered}: {exc}") from exc


def _result_detail(result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    detail = " ".join(detail.split())
    if len(detail) > 400:
        detail = detail[:397] + "..."
    return detail


def _systemctl(
    *arguments: str,
    timeout: float | None = SYSTEMCTL_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    return _run_command(
        [SYSTEMCTL, "--user", *arguments],
        timeout=timeout,
    )


def _parse_service_status(output: str) -> ServiceStatus:
    properties: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key.strip()] = value.strip()

    active_state = properties.get("ActiveState", "")
    sub_state = properties.get("SubState", "")
    raw_pid = properties.get("MainPID", "")
    try:
        main_pid = int(raw_pid)
    except (TypeError, ValueError) as exc:
        raise LauncherError(
            f"systemd returned an invalid MainPID for {SERVICE_UNIT!r}: "
            f"{raw_pid!r}"
        ) from exc
    if not active_state or not sub_state:
        raise LauncherError(
            f"systemd returned incomplete status for {SERVICE_UNIT!r}; "
            "check the user unit installation."
        )
    return ServiceStatus(active_state, sub_state, main_pid)


def _read_service_status() -> ServiceStatus:
    """Read stable machine-readable state from the user service manager."""

    result = _systemctl(
        "show",
        SERVICE_UNIT,
        "--property=ActiveState",
        "--property=SubState",
        "--property=MainPID",
        "--no-pager",
    )
    if result.returncode != 0:
        detail = _result_detail(result)
        suffix = f": {detail}" if detail else f" (exit {result.returncode})"
        raise LauncherError(
            f"Could not query {SERVICE_UNIT!r}; install the user service and "
            f"run systemctl --user status {SERVICE_UNIT}{suffix}"
        )
    return _parse_service_status(result.stdout or "")


def _start_service() -> None:
    result = _systemctl("start", SERVICE_UNIT, timeout=SYSTEMCTL_TIMEOUT)
    if result.returncode != 0:
        detail = _result_detail(result)
        suffix = f": {detail}" if detail else f" (exit {result.returncode})"
        raise LauncherError(
            f"Could not start {SERVICE_UNIT!r}{suffix}. Inspect it with "
            f"systemctl --user status {SERVICE_UNIT} --no-pager."
        )


def _stop_service() -> None:
    result = _systemctl("stop", SERVICE_UNIT, timeout=SYSTEMCTL_TIMEOUT)
    if result.returncode != 0:
        detail = _result_detail(result)
        suffix = f": {detail}" if detail else f" (exit {result.returncode})"
        raise LauncherError(
            f"Could not stop {SERVICE_UNIT!r}{suffix}. Inspect it with "
            f"systemctl --user status {SERVICE_UNIT} --no-pager."
        )


def _decode_proc_address(raw_address: str, family: int) -> str | None:
    try:
        packed = bytes.fromhex(raw_address)
        if family == socket.AF_INET:
            if len(packed) != 4:
                return None
            # Linux displays IPv4 /proc addresses in host byte order.
            return str(ipaddress.IPv4Address(packed[::-1]))
        if family == socket.AF_INET6:
            if len(packed) != 16:
                return None
            # IPv6 entries use little-endian 32-bit words in /proc/net/tcp6.
            normalized = b"".join(
                packed[offset : offset + 4][::-1]
                for offset in range(0, len(packed), 4)
            )
            return str(ipaddress.IPv6Address(normalized))
    except (ValueError, OSError):
        return None
    return None


def _listening_socket_inodes(host: str, port: int) -> set[str]:
    """Return /proc socket inodes listening on the exact host and port."""

    try:
        target = ipaddress.ip_address(host)
    except ValueError:
        return set()
    family_path = (
        (socket.AF_INET, "/proc/net/tcp")
        if target.version == 4
        else (socket.AF_INET6, "/proc/net/tcp6")
    )
    family, proc_path = family_path
    inodes: set[str] = set()
    try:
        with open(proc_path, encoding="ascii") as proc_file:
            next(proc_file, None)
            for line in proc_file:
                fields = line.split()
                if len(fields) <= 9 or fields[3] != "0A":
                    continue
                address, separator, raw_port = fields[1].partition(":")
                if not separator:
                    continue
                try:
                    listening_port = int(raw_port, 16)
                except ValueError:
                    continue
                if listening_port != port:
                    continue
                decoded_address = _decode_proc_address(address, family)
                if decoded_address == str(target):
                    inodes.add(fields[9])
    except (OSError, UnicodeError):
        return set()
    return inodes


def _pid_owns_listening_socket(pid: int, host: str, port: int) -> bool:
    """Verify that ``pid`` owns the exact listening socket being probed.

    A browser must never be opened merely because some unrelated process
    answers on port 8765.  Linux exposes both the listening socket inode and
    the service process' file descriptors through ``/proc``; requiring both
    sides to match gives the launcher that ownership check without adding a
    protocol endpoint to the web server.
    """

    if pid <= 0:
        return False
    inodes = _listening_socket_inodes(host, port)
    if not inodes:
        return False
    descriptor_directory = f"/proc/{pid}/fd"
    try:
        with os.scandir(descriptor_directory) as descriptors:
            for descriptor in descriptors:
                try:
                    target = os.readlink(descriptor.path)
                except OSError:
                    continue
                if target.startswith("socket:[") and target.endswith("]"):
                    if target[8:-1] in inodes:
                        return True
    except OSError:
        return False
    return False


def urlopen(url: str, *, timeout: float):
    """Open a URL with proxy handling disabled for local readiness checks."""

    # A desktop may have HTTP_PROXY set for unrelated work.  Sending the
    # readiness probe through that proxy can both fail and accidentally probe
    # a remote service, so use an opener with proxy handling disabled.
    return build_opener(ProxyHandler({})).open(url, timeout=timeout)


def _open_local_url(url: str):
    return urlopen(url, timeout=READINESS_REQUEST_TIMEOUT)


def _http_ready(url: str) -> bool:
    """Return whether the local UI root responds successfully."""

    try:
        with _open_local_url(url) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            return 200 <= int(status) < 300
    except Exception:
        # Readiness is polled while the server finishes construction.  The
        # detailed systemd state is reported if the bounded wait expires.
        return False


def _port_is_reachable(host: str, port: int) -> bool:
    try:
        connection = socket.create_connection((host, port), timeout=0.2)
    except OSError:
        return False
    try:
        connection.close()
    except OSError:
        pass
    return True


def _readiness_failure(
    status: ServiceStatus | None,
    *,
    timed_out: bool,
    port_reachable: bool,
    timeout: float = STARTUP_TIMEOUT,
) -> ReadinessError:
    status_text = status.describe() if status is not None else "no service status"
    inspect = f"systemctl --user status {SERVICE_UNIT} --no-pager"
    if port_reachable:
        return ReadinessError(
            f"Port {SERVICE_PORT} is reachable, but it is not owned by "
            f"TavernLab MainPID ({status_text}); refusing to open an unrelated "
            f"server. Inspect it with {inspect}."
        )
    if timed_out:
        return ReadinessError(
            f"TavernLab did not become ready at {SERVICE_URL} within "
            f"{timeout:g} seconds ({status_text}). Inspect it with {inspect}."
        )
    if status is not None and status.active_state in {"failed", "inactive", "deactivating"}:
        return ReadinessError(
            f"TavernLab service stopped before becoming ready "
            f"({status_text}). Inspect it with {inspect}."
        )
    return ReadinessError(
        f"TavernLab could not become ready ({status_text}). Inspect it with {inspect}."
    )


def wait_for_readiness(
    *,
    timeout: float = STARTUP_TIMEOUT,
    status_reader: Callable[[], ServiceStatus] | None = None,
    socket_checker: Callable[[int, str, int], bool] | None = None,
    http_checker: Callable[[str], bool] | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> ServiceStatus:
    """Wait for the service PID to own and answer on the configured socket.

    The call is deliberately dependency-injectable so unit tests can model
    systemd transitions without requiring a live user unit or a real port.
    """

    if timeout <= 0:
        raise ValueError("readiness timeout must be positive")
    read_status = status_reader or _read_service_status
    owns_socket = socket_checker or _pid_owns_listening_socket
    is_http_ready = http_checker or _http_ready
    monotonic = clock or time.monotonic
    sleep = sleeper or time.sleep

    started_at = monotonic()
    deadline = started_at + timeout
    last_status: ServiceStatus | None = None
    while True:
        try:
            current = read_status()
        except LauncherError:
            raise
        except Exception as exc:
            raise ReadinessError(f"Could not read {SERVICE_UNIT} readiness: {exc}") from exc
        last_status = current

        if current.running and owns_socket(current.main_pid, SERVICE_HOST, SERVICE_PORT):
            if is_http_ready(SERVICE_URL):
                # Re-check after the HTTP request so a service restart or a
                # same-port process cannot win a race between validation and
                # opening the browser.
                try:
                    final_status = read_status()  # type: ignore[operator]
                except Exception:
                    final_status = None
                if (
                    final_status is not None
                    and final_status.running
                    and final_status.main_pid == current.main_pid
                    and owns_socket(final_status.main_pid, SERVICE_HOST, SERVICE_PORT)
                ):
                    return final_status

        if current.active_state in {"failed", "inactive", "deactivating"}:
            raise _readiness_failure(
                current,
                timed_out=False,
                port_reachable=_port_is_reachable(SERVICE_HOST, SERVICE_PORT),
                timeout=timeout,
            )

        remaining = deadline - monotonic()
        if remaining <= 0:
            raise _readiness_failure(
                last_status,
                timed_out=True,
                port_reachable=_port_is_reachable(SERVICE_HOST, SERVICE_PORT),
                timeout=timeout,
            )
        sleep(min(POLL_INTERVAL, remaining))


def _open_browser() -> None:
    """Launch the desktop browser without making the launcher wait for it."""

    try:
        subprocess.Popen(
            ["xdg-open", SERVICE_URL],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise LauncherError(
            f"TavernLab is ready at {SERVICE_URL}, but xdg-open was not found; "
            f"open that URL manually or install xdg-utils."
        ) from exc
    except OSError as exc:
        raise LauncherError(
            f"TavernLab is ready at {SERVICE_URL}, but the browser could not be "
            f"opened: {exc}. Open the URL manually."
        ) from exc


def _notify_failure(message: str) -> None:
    """Best-effort desktop notification for an already printed failure."""

    notify_send = shutil.which("notify-send")
    if not notify_send:
        return
    try:
        subprocess.Popen(
            [notify_send, "TavernLab", message[:400]],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        # stderr remains the authoritative failure channel.
        return


def _print_status() -> int:
    result = _systemctl("status", SERVICE_UNIT, "--no-pager")
    output = result.stdout or ""
    if result.stderr:
        output += result.stderr
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    return result.returncode


def _launch() -> None:
    status = _read_service_status()
    if status.active_state not in {"active", "activating"}:
        _start_service()
    wait_for_readiness()
    _open_browser()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--stop", action="store_true", help="stop the user service")
    modes.add_argument("--status", action="store_true", help="print user service status")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the desktop launch, stop, or status action."""

    args = _build_parser().parse_args(argv)
    if args.status:
        try:
            return _print_status()
        except LauncherError as exc:
            message = str(exc)
            print(f"TavernLab status failed: {message}", file=sys.stderr)
            _notify_failure(message)
            return 1
    try:
        if args.stop:
            _stop_service()
        else:
            _launch()
    except LauncherError as exc:
        message = str(exc)
        action = "stop" if args.stop else "launch"
        print(f"TavernLab {action} failed: {message}", file=sys.stderr)
        _notify_failure(message)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LauncherError",
    "ReadinessError",
    "SERVICE_HOST",
    "SERVICE_PORT",
    "SERVICE_URL",
    "SERVICE_UNIT",
    "ServiceStatus",
    "main",
    "wait_for_readiness",
]
