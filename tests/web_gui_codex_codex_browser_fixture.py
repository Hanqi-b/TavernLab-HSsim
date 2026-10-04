#!/usr/bin/env python3
"""Real WebGame boundary for the Codex-vs-Codex spectator browser test.

Both controllers are deterministic local fakes.  They retain and validate
their private observations so this fixture exercises the production
AutomatedGame scheduler's per-seat projection without making a model call.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fireplace import cards
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.automated_game import AutomatedGame
from fireplace.web_gui.server import WebGameManager, make_server


class ScriptedCodex:
    """Small fake Codex adapter with a seat-specific observation contract."""

    async_decisions = True

    def __init__(self, seat: int, model: str, expected_hero: str, *, fail_on_call=None):
        self.seat = int(seat)
        self.model = model
        self.expected_hero = expected_hero
        self.fail_on_call = fail_on_call
        self.calls = 0
        self.observations = []
        self.observation_error = None

    def export_config(self):
        return {"model": self.model, "timeout": 5.0}

    def choose_action(self, observation, actions):
        self.calls += 1
        self.observations.append(copy.deepcopy(observation))
        hero = observation.get("self", {}).get("hero", {})
        if hero.get("card_id") != self.expected_hero:
            self.observation_error = (
                f"seat {self.seat} received {hero.get('card_id')!r}, "
                f"expected {self.expected_hero!r}"
            )
            raise AssertionError(self.observation_error)
        # Keep the detached worker observable long enough for the browser to
        # issue a pause against a thinking snapshot.
        time.sleep(0.18)
        if self.fail_on_call is not None and self.calls == self.fail_on_call:
            raise RuntimeError(f"fixture seat {self.seat} failure")
        return next(
            (action for action in actions if getattr(action, "type", "") == "END_TURN"),
            actions[0],
        )

    def cancel(self):
        return None

    def close(self, *, wait=False):
        del wait


class FixtureAutomatedGame(AutomatedGame):
    """Use production retry scheduling with a local replacement controller."""

    def __init__(self, *args, retry_controller_factory, **kwargs):
        self._retry_controller_factory = retry_controller_factory
        super().__init__(*args, **kwargs)

    def _new_controller(self, seat, state=None):
        if int(seat) == 1:
            return self._retry_controller_factory()
        return super()._new_controller(seat, state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    cards.db.initialize()

    seat0 = ScriptedCodex(0, "fixture-seat0", "HERO_08")
    # The second call deliberately fails.  Its replacement, installed through
    # AutomatedGame.retry_opponent, succeeds and keeps the same seat identity.
    seat1 = ScriptedCodex(1, "fixture-seat1", "HERO_01", fail_on_call=2)
    retries = []

    def replacement():
        controller = ScriptedCodex(1, "fixture-seat1-retry", "HERO_01")
        retries.append(controller)
        return controller

    player0 = Player("Codex seat 0", ["CS2_231"] * 30, "HERO_08")
    player1 = Player("Codex seat 1", ["CS2_231"] * 30, "HERO_01")
    app = FixtureAutomatedGame(
        GameSession(Game((player0, player1), seed=93), {}),
        player0,
        (seat0, seat1),
        battle_mode="codex_codex",
        locale="zhCN",
        retry_controller_factory=replacement,
    )
    manager = WebGameManager(opponent="codex")
    manager._active = app
    server = make_server(manager, host="127.0.0.1", port=args.port)
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
        manager.close()
    # A failed seat projection is a fixture failure even if the browser
    # happened to stop before the mismatch surfaced in the HTTP response.
    if seat0.observation_error or seat1.observation_error:
        print(json.dumps({"fixture_error": seat0.observation_error or seat1.observation_error}), file=sys.stderr)
        return 1
    if not seat0.observations or not seat1.observations:
        print(json.dumps({"fixture_error": "both Codex seats must receive observations"}), file=sys.stderr)
        return 1
    if not retries or not retries[0].observations:
        print(json.dumps({"fixture_error": "retry controller did not receive an observation"}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
