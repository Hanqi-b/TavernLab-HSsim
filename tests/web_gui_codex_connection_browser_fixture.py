#!/usr/bin/env python3
"""Isolated browser fixture for the optional Codex connection panel.

The connection adapter is fake, and CodexTransport.start is blocked before it
can launch a process. Account, state, and Codex home paths all point inside the
temporary directory created by the paired browser test.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fireplace.codex_transport import CodexTransport
from fireplace.web_gui.server import make_server


class FakeCodexConnection:
    """Record explicit UI actions and return deterministic, safe responses."""

    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.lock = threading.Lock()
        self.calls: list[dict[str, object]] = []
        self.child_start_attempts = 0
        self.login_count = 0
        self.available = False
        self.connected = False
        self.login_pending = False
        self.proxy_url = ""
        self.binary_path = ""
        self.error = "Codex CLI is unavailable. Install Codex CLI or set an executable binary in Codex settings."
        self._write_state()

    def _status(self) -> dict[str, object]:
        return {
            "available": self.available,
            "connected": self.connected,
            "account": (
                {"email": "browser-fixture@example.invalid", "plan_type": "fixture"}
                if self.connected else None
            ),
            "login_pending": self.login_pending,
            "error": self.error,
            "proxy_url": self.proxy_url,
            "binary_path": self.binary_path,
            "shared_login": True,
        }

    def _record(self, method: str, **details: object) -> None:
        with self.lock:
            self.calls.append({"method": method, **details})
            self._write_state_locked()

    def _write_state_locked(self) -> None:
        self.state_path.write_text(
            json.dumps({
                "calls": self.calls,
                "child_start_attempts": self.child_start_attempts,
                "status": self._status(),
            }),
            encoding="utf-8",
        )

    def _write_state(self) -> None:
        with self.lock:
            self._write_state_locked()

    def status(self) -> dict[str, object]:
        self._record("status")
        return self._status()

    def check(self) -> dict[str, object]:
        self.available = True
        self.error = None
        self._record("check")
        return self._status()

    def start_login(self) -> dict[str, object]:
        self.login_count += 1
        if self.login_count == 1:
            self.login_pending = True
            self.connected = False
        else:
            self.login_pending = False
            self.connected = True
        self.available = True
        self.error = None
        self._record("start_login", login_count=self.login_count)
        return {
            **self._status(),
            "auth_url": "https://auth.openai.com/codex-fixture",
        }

    def cancel_login(self) -> dict[str, object]:
        self.login_pending = False
        self._record("cancel_login")
        return self._status()

    def logout(self) -> dict[str, object]:
        self.connected = False
        self.login_pending = False
        self._record("logout")
        return self._status()

    def save_settings(self, payload: object) -> dict[str, object]:
        values = payload if isinstance(payload, dict) else {}
        self.proxy_url = str(values.get("proxy_url") or "")
        self.binary_path = str(values.get("binary_path") or "")
        self._record("save_settings", payload=values)
        return self._status()

    def test_connection(self, *, model: str | None = None) -> dict[str, object]:
        self._record("test_connection", model=model)
        if model == "force-unsuccessful":
            return {
                **self._status(),
                "success": False,
                "error": "Codex connection test failed. Verify the selected model and retry.",
            }
        if model == "force-error":
            raise RuntimeError("fixture-only connection failure")
        return {**self._status(), "success": True}

    def close(self) -> None:
        self._record("close")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--port":
        raise SystemExit("usage: web_gui_codex_connection_browser_fixture.py --port PORT")
    port = int(sys.argv[2])
    state_path = Path(os.environ["FIREPLACE_CODEX_FIXTURE_STATE"])

    # A regression must never reach an installed Codex CLI or any auth profile.
    def blocked_transport_start(self, *args, **kwargs):
        del self, args, kwargs
        fixture.child_start_attempts += 1
        fixture._write_state()
        raise RuntimeError("Codex CLI process start blocked by browser fixture")

    CodexTransport.start = blocked_transport_start
    fixture = FakeCodexConnection(state_path)
    server = make_server(host="127.0.0.1", port=port, seed=7301)
    server.codex_connection = fixture
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/", "state_path": str(state_path)}), flush=True)
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
