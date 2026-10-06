import json
import os
import queue
import stat
import threading
import time
from pathlib import Path

import pytest

import fireplace.codex_transport as codex_transport_module
from fireplace.codex_transport import CodexTransport, CodexTransportError
from fireplace.web_gui.codex_connection import (
    ERROR_NO_ACCOUNT,
    ERROR_UNAVAILABLE,
    CodexConnection,
    resolve_external_binary,
)


class _FakeTransport:
    def __init__(self, *, account=None, login_url="https://auth.openai.com/authorize?state=1"):
        self.account = account
        self.login_url = login_url
        self.requests = []
        self.notifications = []
        self.events = queue.Queue()
        self.closed = False

    def start(self):
        self.notifications.append(("start", None))

    def notify(self, method, params=None):
        self.notifications.append((method, params))

    def request(self, method, params, timeout=None):
        self.requests.append((method, params, timeout))
        if method == "initialize":
            return {}
        if method == "account/read":
            return self.account
        if method == "account/login/start":
            return {"authUrl": self.login_url}
        if method == "account/logout":
            return {}
        raise AssertionError(method)

    def wait_for_notification(self, timeout=None):
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError from exc

    def close(self):
        self.closed = True


def _binary(tmp_path):
    path = tmp_path / "codex"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_status_is_passive_and_does_not_create_home_or_child(tmp_path):
    created = []

    def factory(binary, env):
        created.append((binary, env))
        return _FakeTransport()

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(tmp_path / "missing-codex"),
    )
    status = manager.status()
    assert status["available"] is False
    assert status["connected"] is False
    assert status["error"] == ERROR_UNAVAILABLE
    assert status["binary_path"] == ""
    assert created == []
    assert not (tmp_path / "private").exists()


def test_default_profile_is_shared_but_game_state_stays_separate(tmp_path, monkeypatch):
    binary = _binary(tmp_path)
    state_root = tmp_path / "state"
    external_home = tmp_path / "external-profile"
    external_home.mkdir()
    external_home.chmod(0o755)
    transports = []

    def factory(binary_path, env):
        transport = _FakeTransport(account={"email": "player@example.com", "planType": "plus"})
        transports.append((transport, binary_path, env))
        return transport

    monkeypatch.setenv("XDG_STATE_HOME", str(state_root))
    monkeypatch.setenv("CODEX_HOME", str(external_home))
    monkeypatch.delenv("TAVERNLAB_CODEX_HOME", raising=False)
    manager = CodexConnection(
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
    )

    assert manager.home == state_root / "fireplace" / "codex"
    assert manager.settings_path == manager.home / "settings.json"
    assert manager.auth_home == external_home
    assert manager.status()["shared_login"] is True
    assert not manager.home.exists()
    assert not manager.settings_path.exists()
    assert manager.status()["login_pending"] is False
    assert transports == []

    checked = manager.check()
    assert checked["connected"] is True
    assert transports[0][1] == str(binary)
    assert transports[0][2]["CODEX_HOME"] == str(external_home)
    assert external_home.stat().st_mode & 0o777 == 0o755
    assert not (external_home / "settings.json").exists()
    assert not manager.settings_path.exists()

    logged_out = manager.logout()
    assert logged_out["shared_login"] is True
    assert transports[-1][2]["CODEX_HOME"] == str(external_home)
    assert any(request[0] == "account/logout" for request in transports[-1][0].requests)


def test_status_does_not_initialize_default_profile(tmp_path, monkeypatch):
    binary = _binary(tmp_path)
    state_root = tmp_path / "state"
    external_home = tmp_path / "external-profile"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_root))
    monkeypatch.setenv("CODEX_HOME", str(external_home))
    monkeypatch.delenv("TAVERNLAB_CODEX_HOME", raising=False)

    manager = CodexConnection(binary_resolver=lambda _value: str(binary))
    status = manager.status()

    assert status["shared_login"] is True
    assert status["connected"] is False
    assert not external_home.exists()
    assert not manager.home.exists()


def test_saved_game_settings_keep_shared_profile_proxy_and_location(tmp_path, monkeypatch):
    binary = _binary(tmp_path)
    state_root = tmp_path / "state"
    external_home = tmp_path / "external-profile"
    transports = []

    def factory(binary_path, env):
        transport = _FakeTransport(account={"email": "player@example.com", "planType": "plus"})
        transports.append((transport, binary_path, env))
        return transport

    monkeypatch.setenv("XDG_STATE_HOME", str(state_root))
    monkeypatch.setenv("CODEX_HOME", str(external_home))
    monkeypatch.delenv("TAVERNLAB_CODEX_HOME", raising=False)
    manager = CodexConnection(
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
    )

    saved = manager.save_settings({"proxy_url": "http://proxy.example:3128"})
    assert saved["proxy_url"] == "http://proxy.example:3128"
    assert manager.settings_path == state_root / "fireplace" / "codex" / "settings.json"
    assert manager.settings_path.exists()
    assert not (external_home / "settings.json").exists()
    assert not external_home.exists()

    assert manager.check()["connected"] is True
    child_env = transports[0][2]
    assert child_env["CODEX_HOME"] == str(external_home)
    assert child_env["HTTP_PROXY"] == "http://proxy.example:3128"
    assert child_env["HTTPS_PROXY"] == "http://proxy.example:3128"
    assert child_env["ALL_PROXY"] == "http://proxy.example:3128"
    assert not (external_home / "settings.json").exists()


def test_tavernlab_override_is_an_isolated_auth_profile(tmp_path, monkeypatch):
    binary = _binary(tmp_path)
    state_root = tmp_path / "state"
    parent_home = tmp_path / "parent-codex"
    isolated_home = tmp_path / "isolated-codex"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_root))
    monkeypatch.setenv("CODEX_HOME", str(parent_home))
    monkeypatch.setenv("TAVERNLAB_CODEX_HOME", str(isolated_home))

    manager = CodexConnection(binary_resolver=lambda _value: str(binary))

    assert manager.home == state_root / "fireplace" / "codex"
    assert manager.auth_home == isolated_home
    assert manager.status()["shared_login"] is False


def test_settings_are_validated_atomic_and_protected(tmp_path):
    binary = _binary(tmp_path)
    home = tmp_path / "private"
    manager = CodexConnection(home=home, binary_resolver=lambda _value: str(binary))
    saved = manager.save_settings({"proxy_url": "https://proxy.example:8443", "binary_path": str(binary)})
    assert saved["proxy_url"] == "https://proxy.example:8443"
    assert home.stat().st_mode & 0o777 == 0o700
    assert manager.settings_path.stat().st_mode & 0o777 == 0o600
    raw = json.loads(manager.settings_path.read_text(encoding="utf-8"))
    assert raw == {"binary_path": str(binary), "proxy_url": "https://proxy.example:8443"}

    loaded = CodexConnection(home=home, binary_resolver=lambda _value: "unused")
    assert loaded.status()["proxy_url"] == "https://proxy.example:8443"
    assert loaded.status()["binary_path"] == str(binary)

    with pytest.raises(ValueError):
        manager.save_settings({"proxy_url": "http://user:pass@proxy.example:8080"})
    with pytest.raises(ValueError):
        manager.save_settings({"proxy_url": "http://proxy.example:8080/path"})
    with pytest.raises(ValueError):
        manager.save_settings({"binary_path": "codex"})


def test_check_and_login_whitelist_account_and_reject_raw_data(tmp_path):
    binary = _binary(tmp_path)
    transports = []

    def factory(binary_path, env):
        transport = _FakeTransport(
            account={"account": {"email": "player@example.com", "planType": "plus", "token": "secret"}}
        )
        transports.append((transport, binary_path, env))
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
        login_timeout=1,
    )
    checked = manager.check()
    assert checked["account"] == {"email": "player@example.com", "plan_type": "plus"}
    assert "secret" not in json.dumps(checked)
    assert transports[0][0].closed
    assert any(request[0] == "account/read" and request[1] == {"refreshToken": False} for request in transports[0][0].requests)

    started = manager.start_login()
    assert started["auth_url"].startswith("https://auth.openai.com/")
    assert started["login_pending"] is True
    login_transport = transports[-1][0]
    login_transport.events.put({"method": "account/login/completed", "params": {"success": True, "token": "secret"}})
    deadline = time.monotonic() + 1
    while manager.status()["login_pending"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.status()["login_pending"] is False
    assert login_transport.closed
    assert "secret" not in json.dumps(manager.status())


def test_chatgpt_account_with_null_email_is_still_connected(tmp_path):
    binary = _binary(tmp_path)

    def factory(_binary_path, _env):
        return _FakeTransport(account={"account": {"type": "chatgpt", "email": None, "planType": "plus"}})

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
    )
    status = manager.check()
    assert status["connected"] is True
    assert status["account"] == {"email": "", "plan_type": "plus"}


def test_login_waiter_continues_after_idle_notification_timeout(tmp_path):
    binary = _binary(tmp_path)
    transports = []

    class IdleOnce(_FakeTransport):
        def __init__(self):
            super().__init__(account={"email": "player@example.com", "planType": "plus"})
            self.idled = False

        def wait_for_notification(self, timeout=None):
            if not self.idled:
                self.idled = True
                raise TimeoutError
            return {"method": "account/login/completed", "params": {"success": True}}

    def factory(_binary_path, _env):
        transport = IdleOnce()
        transports.append(transport)
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
        login_timeout=1,
    )
    assert manager.start_login()["login_pending"] is True
    deadline = time.monotonic() + 1
    while manager.status()["login_pending"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.status()["connected"] is True
    assert transports[0].closed


def test_login_waiter_recognizes_real_transport_idle_timeout():
    transport = CodexTransport("/bin/true")
    with pytest.raises(CodexTransportError) as raised:
        transport.wait_for_notification(timeout=0.02)
    assert CodexConnection._is_notification_timeout(raised.value)


def test_login_waiter_ignores_foreign_or_failed_completion(tmp_path):
    binary = _binary(tmp_path)
    transports = []

    class Correlated(_FakeTransport):
        def request(self, method, params, timeout=None):
            result = super().request(method, params, timeout)
            if method == "account/login/start":
                return {"authUrl": self.login_url, "loginId": "current-login"}
            return result

    def factory(_binary_path, _env):
        transport = Correlated(account={"email": "player@example.com", "planType": "plus"})
        transports.append(transport)
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
        login_timeout=1,
    )
    assert manager.start_login()["login_pending"] is True
    transport = transports[0]
    transport.events.put({
        "method": "account/login/completed",
        "params": {"loginId": "old-login", "success": True},
    })
    time.sleep(0.02)
    assert manager.status()["login_pending"] is True
    transport.events.put({
        "method": "account/login/completed",
        "params": {"loginId": "current-login", "success": False, "token": "secret"},
    })
    deadline = time.monotonic() + 1
    while manager.status()["login_pending"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.status()["login_pending"] is False
    assert manager.status()["connected"] is False
    assert "secret" not in json.dumps(manager.status())


def test_cancel_login_invalidates_old_result_and_closes_child(tmp_path):
    binary = _binary(tmp_path)
    transports = []

    def factory(_binary_path, _env):
        transport = _FakeTransport(account={"email": "new@example.com", "planType": "free"})
        transports.append(transport)
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
        login_timeout=1,
    )
    result = manager.start_login()
    assert result["login_pending"] is True
    old = transports[-1]
    assert manager.cancel_login()["login_pending"] is False
    assert old.closed
    old.events.put({"method": "account/login/completed", "params": {}})
    time.sleep(0.02)
    assert manager.status()["account"] is None


def test_close_does_not_wait_for_blocked_check_and_invalidates_result(tmp_path):
    binary = _binary(tmp_path)
    started = threading.Event()
    released = threading.Event()
    close_returned = threading.Event()
    transports = []

    class Blocking(_FakeTransport):
        def request(self, method, params, timeout=None):
            if method == "account/read":
                started.set()
                released.wait(timeout=10)
            return super().request(method, params, timeout)

        def close(self):
            super().close()
            released.set()

    def factory(_binary_path, _env):
        transport = Blocking(account={"email": "stale@example.com", "planType": "plus"})
        transports.append(transport)
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
    )
    result_holder = []
    check_thread = threading.Thread(target=lambda: result_holder.append(manager.check()))
    check_thread.start()
    assert started.wait(timeout=1)

    close_thread = threading.Thread(target=lambda: (manager.close(), close_returned.set()))
    close_thread.start()
    try:
        assert close_returned.wait(timeout=1)
    finally:
        released.set()
        close_thread.join(timeout=1)
        check_thread.join(timeout=1)

    assert not close_thread.is_alive()
    assert not check_thread.is_alive()
    assert result_holder and result_holder[0]["connected"] is False
    assert manager.status()["account"] is None
    assert transports[0].closed


def test_queued_check_cannot_reopen_manager_after_close(tmp_path):
    binary = _binary(tmp_path)
    started = threading.Event()
    released = threading.Event()
    transports = []

    class BlockingInitialize(_FakeTransport):
        def request(self, method, params, timeout=None):
            if method == "initialize":
                started.set()
                released.wait(timeout=10)
            return super().request(method, params, timeout)

        def close(self):
            super().close()
            released.set()

    def factory(_binary_path, _env):
        if not transports:
            transport = BlockingInitialize(
                account={"email": "stale@example.com", "planType": "plus"}
            )
        else:
            transport = _FakeTransport(
                account={"email": "should-not-connect@example.com", "planType": "plus"}
            )
        transports.append(transport)
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        binary_resolver=lambda _value: str(binary),
    )
    results = []
    first = threading.Thread(target=lambda: results.append(manager.check()))
    second = threading.Thread(target=lambda: results.append(manager.check()))
    first.start()
    assert started.wait(timeout=1)
    second.start()
    manager.close()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(transports) == 1
    assert all(result["connected"] is False for result in results)
    assert manager.status()["account"] is None


def test_test_connection_uses_same_private_proxy_and_bounded_agent(tmp_path):
    binary = _binary(tmp_path)
    transports = []
    agents = []

    class FakeAgent:
        def __init__(self, **kwargs):
            agents.append(kwargs)

        def choose_action(self, observation, actions):
            assert observation["phase"] == "MAIN"
            assert len(actions) == 2
            return actions[0]

        def close(self):
            return None

    def factory(_binary_path, env):
        transport = _FakeTransport(account={"email": "player@example.com", "planType": "plus"})
        transports.append((transport, env))
        return transport

    manager = CodexConnection(
        home=tmp_path / "private",
        transport_factory=factory,
        agent_factory=FakeAgent,
        binary_resolver=lambda _value: str(binary),
    )
    manager.save_settings({"proxy_url": "http://proxy.example:3128"})
    result = manager.test_connection(model="gpt-test")
    assert result["success"] is True
    assert agents[0]["timeout"] <= 45
    assert agents[0]["model"] == "gpt-test"
    assert transports[-1][1]["CODEX_HOME"] == str(tmp_path / "private")
    assert transports[-1][1]["HTTP_PROXY"] == "http://proxy.example:3128"
    assert transports[-1][1]["HTTPS_PROXY"] == "http://proxy.example:3128"


def test_external_resolver_prefers_user_local_binary(monkeypatch, tmp_path):
    home = tmp_path / "home"
    local = home / ".local" / "bin" / "codex"
    local.parent.mkdir(parents=True)
    local.write_text("#!/bin/sh\n", encoding="utf-8")
    local.chmod(0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TAVERNLAB_CODEX_BINARY", raising=False)
    monkeypatch.setattr(
        codex_transport_module.shutil,
        "which",
        lambda name: "/path/from/PATH" if name == "codex" else None,
    )
    assert resolve_external_binary() == str(local)
