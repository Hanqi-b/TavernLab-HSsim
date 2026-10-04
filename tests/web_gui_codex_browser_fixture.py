#!/usr/bin/env python3
"""Deterministic async Codex-shaped match for the browser acceptance test.

The fixture uses the real WebGame HTTP boundary and presentation-step store,
but replaces the external Codex adapter with a small delayed scripted agent.
It never makes a network or model call.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Mapping

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fireplace import cards
from fireplace.controller import GameSession, decision_player
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.server import WebActionError, WebGame, make_server


class ScriptedCodex:
    """Async agent with a deterministic failure, retry, and delayed turn."""

    async_decisions = True

    def __init__(self, *, attempt: int = 0):
        self.attempt = attempt
        self.calls = 0

    def export_config(self):
        return {"model": "fixture-codex", "timeout": 5.0}

    def choose_action(self, _observation, actions):
        self.calls += 1
        if self.attempt == 0:
            time.sleep(0.35)
            raise RuntimeError("fixture Codex failure")
        # The first retry turn deliberately takes several visible actions.
        # The last call is held long enough for the browser to concede while
        # the LLM status remains thinking.
        if self.calls >= 3:
            time.sleep(1.2)
        else:
            time.sleep(0.12)
        play = next((action for action in actions if getattr(action, "type", "") == "PLAY_CARD"), None)
        if play is not None and self.calls <= 2:
            return play
        return next((action for action in actions if getattr(action, "type", "") == "END_TURN"), actions[0])

    def cancel(self):
        return None

    def close(self, *, wait=False):
        del wait


class CodexFixtureGame(WebGame):
    def __init__(self, *args, **kwargs):
        self._prepared = False
        super().__init__(*args, **kwargs)

    def _advance_ai_locked(self, presentation_steps=None):
        if not self._prepared and decision_player(self.session.game) is self.human.opponent:
            opponent = self.human.opponent
            opponent.max_mana = 10
            opponent.used_mana = 0
            self._prepared = True
        return super()._advance_ai_locked(presentation_steps)

    def retry_opponent(self, payload):
        """Use the scripted adapter while retaining the production contract."""
        with self.lock:
            current = self._snapshot_locked()
            if not isinstance(payload, Mapping):
                raise WebActionError("request body must be a JSON object", 400, current)
            if payload.get("session_id") != self._session_id:
                current["error"] = "stale session"
                raise WebActionError(current["error"], 409, current)
            if type(payload.get("revision")) is not int or payload["revision"] != self._revision:
                current["error"] = "stale revision"
                raise WebActionError(current["error"], 409, current)
            if self._llm_state != "error":
                current["error"] = "opponent retry is unavailable"
                raise WebActionError(current["error"], 409, current)
            old = self._async_scheduler
            self._async_scheduler = None
            if old is not None:
                old.invalidate()
                old.close(wait=False)
            self.opponent_agent = ScriptedCodex(attempt=1)
            self._codex_config = {"model": "fixture-codex", "timeout": 5.0}
            self._llm_state = "idle"
            self._llm_error = None
            self._schedule_async_ai_locked()
            return self._snapshot_locked()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    cards.db.initialize()
    human = Player("Codex fixture human", ["CS2_231"] * 30, "HERO_08")
    opponent = Player("Codex fixture opponent", ["CS2_231"] * 30, "HERO_01")
    app = CodexFixtureGame(
        GameSession(Game((human, opponent), seed=47), {}),
        human,
        ScriptedCodex(),
        locale="zhCN",
    )
    server = make_server(app, host="127.0.0.1", port=args.port)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stop.set())
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/"}), flush=True)
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
