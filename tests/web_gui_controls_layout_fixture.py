#!/usr/bin/env python3
"""Deterministic battle state for browser control-layout checks."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from collections.abc import Mapping

from hearthstone.enums import Zone

from fireplace import cards
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.server import WebGame, make_server


class PassAgent:
    def choose_action(self, observation, actions):
        return next((action for action in actions if action.type == "END_TURN"), actions[0])


class ControlsLayoutScenario(WebGame):
    """Expose full board/hand controls after the opening mulligan."""

    def __init__(self, *args, **kwargs):
        self.prepared = False
        super().__init__(*args, **kwargs)

    def _localized_observation_locked(self, observation):
        localized = super()._localized_observation_locked(observation)
        for side, name in (
            ("self", "测试超长武器名称用于检查英雄遮挡与换行布局"),
            ("opponent", "VeryLongEnglishWeaponNameForPortraitClearanceLayout"),
        ):
            player = localized.get(side)
            weapon = player.get("weapon") if isinstance(player, Mapping) else None
            if isinstance(weapon, dict):
                weapon["name"] = name
                weapon["atk"] = 3
                weapon["durability"] = 2
        return localized

    def handle_action(self, payload):
        response = super().handle_action(payload)
        action = payload.get("action") if isinstance(payload, Mapping) else None
        if not self.prepared and isinstance(action, Mapping) and action.get("type") == "MULLIGAN":
            with self.lock:
                human = self.human
                for card in list(human.hand):
                    card.zone = Zone.SETASIDE
                for _ in range(10):
                    human.give("CS2_231")
                for _ in range(7):
                    human.summon("CS2_231")
                for _ in range(7):
                    human.opponent.summon("CS2_231")
                weapon = human.card("CS2_080")
                weapon.zone = Zone.PLAY
                opponent_weapon = human.opponent.card("CS2_080")
                opponent_weapon.zone = Zone.PLAY
                human.max_mana = 10
                human.used_mana = 1
                self.prepared = True
                self._revision += 1
                response = self.snapshot()
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--locale", choices=("zhCN", "enUS"), default="zhCN")
    args = parser.parse_args()

    cards.db.initialize()
    human = Player("Controls layout tester", ["CS2_231"] * 30, "HERO_08")
    opponent = Player("Controls layout opponent", ["CS2_231"] * 30, "HERO_01")
    app = ControlsLayoutScenario(
        GameSession(Game((human, opponent), seed=31), {}),
        human,
        PassAgent(),
        locale=args.locale,
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
