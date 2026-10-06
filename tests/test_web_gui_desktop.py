"""Unit tests for the systemd-backed TavernLab desktop launcher."""

from __future__ import annotations

import subprocess

import pytest

from fireplace.web_gui import desktop


def _status(active: str = "active", sub: str = "running", pid: int = 1234):
    return desktop.ServiceStatus(active, sub, pid)


def _completed(command, *, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        command,
        returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _instant_readiness(monkeypatch, statuses):
    values = iter(statuses)
    monkeypatch.setattr(desktop, "_read_service_status", lambda: next(values))
    monkeypatch.setattr(
        desktop,
        "_pid_owns_listening_socket",
        lambda pid, host, port: (
            pid > 0
            and host == desktop.SERVICE_HOST
            and port == desktop.SERVICE_PORT
        ),
    )
    monkeypatch.setattr(desktop, "_http_ready", lambda url: url == desktop.SERVICE_URL)


def test_launch_starts_inactive_service_and_opens_browser(monkeypatch):
    commands = []
    opened = []

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return _completed(command)

    def popen(command, **kwargs):
        opened.append((command, kwargs))

    monkeypatch.setattr(desktop.subprocess, "run", run)
    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    _instant_readiness(
        monkeypatch,
        [_status("inactive", "dead", 0), _status(), _status()],
    )

    assert desktop.main([]) == 0
    assert [command for command, _ in commands] == [
        ["systemctl", "--user", "start", desktop.SERVICE_UNIT],
    ]
    assert opened and opened[0][0] == ["xdg-open", desktop.SERVICE_URL]
    assert opened[0][1]["start_new_session"] is True


def test_repeated_launch_reuses_active_service(monkeypatch):
    commands = []
    opened = []

    def run(command, **kwargs):
        commands.append(command)
        return _completed(command)

    monkeypatch.setattr(desktop.subprocess, "run", run)
    monkeypatch.setattr(
        desktop.subprocess,
        "Popen",
        lambda command, **kwargs: opened.append(command),
    )
    _instant_readiness(
        monkeypatch,
        [_status(), _status(), _status(), _status(), _status(), _status()],
    )

    assert desktop.main([]) == 0
    assert desktop.main([]) == 0
    assert commands == []
    assert opened == [["xdg-open", desktop.SERVICE_URL]] * 2


def test_stop_calls_user_systemd(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return _completed(command)

    monkeypatch.setattr(desktop.subprocess, "run", run)

    assert desktop.main(["--stop"]) == 0
    assert commands == [["systemctl", "--user", "stop", desktop.SERVICE_UNIT]]


def test_status_prints_systemd_output_and_returns_exit_code(monkeypatch, capsys):
    command_seen = []

    def run(command, **kwargs):
        command_seen.append(command)
        return _completed(command, returncode=3, stdout="inactive\n")

    monkeypatch.setattr(desktop.subprocess, "run", run)

    assert desktop.main(["--status"]) == 3
    assert command_seen == [["systemctl", "--user", "status", desktop.SERVICE_UNIT, "--no-pager"]]
    assert capsys.readouterr().out == "inactive\n"


def test_readiness_timeout_never_opens_browser(monkeypatch, capsys):
    opened = []
    notifications = []
    monkeypatch.setattr(
        desktop.subprocess,
        "Popen",
        lambda command, **kwargs: opened.append(command),
    )
    monkeypatch.setattr(desktop, "_notify_failure", notifications.append)
    monkeypatch.setattr(desktop, "_read_service_status", lambda: _status())
    monkeypatch.setattr(desktop, "_pid_owns_listening_socket", lambda pid, host, port: False)
    monkeypatch.setattr(desktop, "_port_is_reachable", lambda host, port: False)
    ticks = iter((0.0, 16.0))
    monkeypatch.setattr(desktop.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(desktop.time, "sleep", lambda delay: None)

    assert desktop.main([]) == 1
    assert opened == []
    error = capsys.readouterr().err
    assert "did not become ready" in error
    assert notifications and "did not become ready" in notifications[0]


def test_occupied_port_is_never_opened_as_tavernlab(monkeypatch, capsys):
    opened = []
    notifications = []
    monkeypatch.setattr(
        desktop.subprocess,
        "Popen",
        lambda command, **kwargs: opened.append(command),
    )
    monkeypatch.setattr(desktop, "_notify_failure", notifications.append)
    monkeypatch.setattr(desktop, "_read_service_status", lambda: _status())
    monkeypatch.setattr(desktop, "_pid_owns_listening_socket", lambda pid, host, port: False)
    monkeypatch.setattr(desktop, "_port_is_reachable", lambda host, port: True)
    ticks = iter((0.0, 16.0))
    monkeypatch.setattr(desktop.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(desktop.time, "sleep", lambda delay: None)

    assert desktop.main([]) == 1
    assert opened == []
    error = capsys.readouterr().err
    assert "refusing to open an unrelated server" in error
    assert notifications and "refusing to open an unrelated server" in notifications[0]


def test_readiness_probe_disables_http_proxy(monkeypatch):
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def getcode(self):
            return self.status

    class Opener:
        def open(self, url, timeout):
            calls.append((url, timeout))
            return Response()

    def build(handler):
        assert isinstance(handler, desktop.ProxyHandler)
        return Opener()

    monkeypatch.setattr(desktop, "build_opener", build)

    assert desktop._http_ready(desktop.SERVICE_URL) is True
    assert calls == [(desktop.SERVICE_URL, desktop.READINESS_REQUEST_TIMEOUT)]


def test_parse_service_status_requires_machine_fields():
    assert desktop._parse_service_status(
        "ActiveState=active\nSubState=running\nMainPID=77\n"
    ) == desktop.ServiceStatus("active", "running", 77)
    with pytest.raises(desktop.LauncherError, match="incomplete status"):
        desktop._parse_service_status("ActiveState=active\nMainPID=77\n")
