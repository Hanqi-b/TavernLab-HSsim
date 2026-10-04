#!/usr/bin/env python3
"""Real WebGame boundary for the Codex-vs-MCTS spectator browser test.

The fixture keeps both controllers local and deterministic.  Codex is a
delayed scripted chooser and MCTS is a tiny fake search policy; neither makes
an inference or network request.
"""

from __future__ import annotations

import argparse
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
    async_decisions = True

    def export_config(self):
        return {"model": "fixture-codex", "timeout": 5.0}

    def choose_action(self, _observation, actions):
        time.sleep(0.24)
        return next(
            (action for action in actions if getattr(action, "type", "") == "END_TURN"),
            actions[0],
        )

    def cancel(self):
        return None

    def close(self, *, wait=False):
        del wait


class FakeMcts:
    policy_version = "fixture_search"
    seed = 97

    def __init__(self):
        self.search_positions = []

    def choose_action(self, _observation, actions):
        # Keep the MCTS turn pending long enough for the browser to issue a
        # pause request against the same revision deterministically.
        time.sleep(0.30)
        return next(
            (action for action in actions if getattr(action, "type", "") == "END_TURN"),
            actions[0],
        )

    def choose_action_with_search(self, observation, actions, position):
        """Accept the detached search position used by production automation."""

        self.search_positions.append(position)
        return self.choose_action(observation, actions)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    cards.db.initialize()
    codex = Player("Codex seat", ["CS2_231"] * 30, "HERO_08")
    mcts = Player("MCTS seat", ["CS2_231"] * 30, "HERO_01")
    app = AutomatedGame(
        GameSession(Game((codex, mcts), seed=91), {}),
        codex,
        (ScriptedCodex(), FakeMcts()),
        locale="zhCN",
    )
    # Keep the production manager/HTTP lifecycle in the fixture.  The
    # manager's stop path therefore exercises the same detach behavior used
    # by archived spectator matches while the active game remains the real
    # AutomatedGame with only its controllers replaced by local fakes.
    manager = WebGameManager(opponent="mcts")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
