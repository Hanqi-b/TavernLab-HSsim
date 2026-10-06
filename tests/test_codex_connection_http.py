"""Connection controls remain lazy, authenticated and local to this machine."""

import json
from types import SimpleNamespace

import pytest

from fireplace.codex_agent import CodexAgentError
from fireplace.web_gui import http_server, server as web_server
from tests.test_web_gui_accounts_http import Browser, account_server


class ConnectionFixture:
    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append("status")
        return {"available": False, "connected": False, "login_pending": False}

    def check(self):
        self.calls.append("check")
        return {"available": True, "connected": True}

    def save_settings(self, payload):
        self.calls.append(("settings", payload))
        return {"connected": False}

    def test_connection(self, *, model=None):
        self.calls.append(("test", model))
        return {"success": True}

    def close(self):
        self.calls.append("close")


def test_normal_http_never_creates_codex_connection(tmp_path, monkeypatch):
    from fireplace.web_gui import codex_connection

    def unexpected():
        pytest.fail("ordinary GUI use initialized Codex")

    monkeypatch.setattr(codex_connection, "get_codex_connection", unexpected)
    with account_server(tmp_path) as base:
        browser = Browser(base)
        browser.register("ordinary-player")
        assert browser.request("/api/state")[0] == 200
        status, match = browser.request("/api/start", {
            "nickname": "Player", "locale": "enUS", "opponent": "radical",
        })
        assert status == 200 and match["mode"] == "match"


def test_connection_requires_session_and_exact_origin(tmp_path, monkeypatch):
    from fireplace.web_gui import codex_connection

    connection = ConnectionFixture()
    monkeypatch.setattr(codex_connection, "get_codex_connection", lambda: connection)
    with account_server(tmp_path) as base:
        browser = Browser(base)
        assert browser.request("/api/codex/status")[0] == 401
        assert connection.calls == []
        browser.register("connection-player")
        assert browser.request("/api/codex/check", {}, origin=False)[0] == 403
        assert connection.calls == []
        assert browser.request("/api/codex/status")[1]["available"] is False
        assert connection.calls == ["status"]
        assert browser.request("/api/codex/check", {})[1]["connected"] is True
        assert browser.request("/api/codex/settings", {"proxy_url": "http://127.0.0.1:7890"})[0] == 200
        assert browser.request("/api/codex/test", {"model": "selected-model"})[1]["success"] is True
        before = list(connection.calls)
        assert browser.request("/api/codex/test", {"model": 42})[0] == 400
        assert browser.request("/api/codex/check", ["invalid"])[0] == 400
        assert connection.calls == before
    assert connection.calls[-1] == "close"


def test_connection_controls_are_disabled_for_lan_server():
    sent = []
    handler = object.__new__(http_server._RequestHandler)
    handler.server = SimpleNamespace(remote_access=True)
    handler.client_address = ("127.0.0.1", 1234)
    handler._send_json = lambda status, value: sent.append((status, value))
    handler._require_account = lambda: pytest.fail("LAN checked local credentials")
    assert handler._codex_access_allowed() is False
    assert sent[0][0] == 403


def test_child_errors_are_never_exposed_in_http(tmp_path, monkeypatch):
    from fireplace.web_gui import codex_connection

    connection = ConnectionFixture()

    def fail():
        raise RuntimeError("private-token-in-child-error")

    connection.check = fail
    monkeypatch.setattr(codex_connection, "get_codex_connection", lambda: connection)
    with account_server(tmp_path) as base:
        browser = Browser(base)
        browser.register("safe-player")
        status, body = browser.request("/api/codex/check", {})
        assert status == 503
        assert "private-token" not in json.dumps(body)


@pytest.mark.parametrize("reason, expected", [
    ("timeout", "proxy"), ("unavailable", "installed program"),
    ("invalid_action", "invalid action"), ("request", "connection test"),
])
def test_real_agent_error_has_safe_actionable_diagnostic(reason, expected):
    error = CodexAgentError("private external details", reason=reason)
    message = web_server.WebGame._sanitize_codex_error(error)
    assert expected in message
    assert "private" not in message
