#!/usr/bin/env python3
"""Launch a deterministic, real-engine match for browser acceptance checks.

This fixture uses Fireplace's GameSession and normal legal actions.  After a
browser submits its Mulligan, it adds a small set of showcase cards and gives
the opponent a low but non-terminal health total so every interaction can be
exercised in one match.  Mana is refreshed after each accepted action only in
this fixture, so all of those independent UI paths fit into one short match.
The resulting lethal action still goes through the same GUI, Action.from_dict(),
and GameSession.execute() path as a normal game.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Mapping

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fireplace import cards
from fireplace.agents import HeuristicAgent
from fireplace.controller import GameSession, decision_player
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.server import WebGame, make_server


class ShowcaseGame(WebGame):
    """Add deterministic coverage cards after the actual Mulligan decision."""

    def __init__(self, *args, **kwargs):
        self._fixture_ready = False
        super().__init__(*args, **kwargs)

    def _advance_ai_locked(self, presentation_steps=None) -> None:
        # The base game refreshes mana at turn start. Refill once at the AI
        # resolution boundary so this fixture can expose multiple real legal
        # Heuristic plays in one presentation queue.
        if self._fixture_ready and decision_player(self.session.game) is self.human.opponent:
            opponent = self.human.opponent
            opponent.max_mana = 10
            opponent.used_mana = 0
            opponent.hand.clear()
            for _ in range(3):
                opponent.give("CS2_231")
        super()._advance_ai_locked(presentation_steps)

    def handle_action(self, payload: object) -> dict[str, object]:
        response = super().handle_action(payload)
        presentation_steps = response.get("presentation_steps")
        action = payload.get("action") if isinstance(payload, Mapping) else None
        if (
            not self._fixture_ready
            and isinstance(action, Mapping)
            and action.get("type") == "MULLIGAN"
            and response.get("outcome") is None
        ):
            with self.lock:
                human = self.human
                opponent = human.opponent
                # Restore ten mana after each accepted action below so this
                # deterministic UI showcase fits in one human turn.
                human.max_mana = 10
                human.used_mana = 0
                opponent.hero.damage = opponent.hero.max_health - 8
                # The opening hand and replacement flow were exercised above;
                # keep the showcase hand small and deterministic from here.
                human.hand.clear()
                for card_id in (
                    "CS2_231",  # Wisp: summon at a chosen position.
                    "CS2_171",  # Stonetusk Boar: charge attack.
                    "LOE_006",  # Museum Curator: Discover choice.
                    "EX1_164",  # Nourish: choose-one branch.
                    "CS2_029",  # Six damage plus Charge and Hero Power is lethal.
                ):
                    human.give(card_id)
                self._fixture_ready = True
                self._revision += 1
                response = self.snapshot()
        elif self._fixture_ready and response.get("outcome") is None:
            with self.lock:
                self.human.max_mana = 10
                self.human.used_mana = 0
                self._revision += 1
                response = self.snapshot()
        if presentation_steps is not None:
            # Showcase-only mana/hand adjustments add a final fixture revision
            # after the real Action and AI resolutions. Preserve the real
            # per-Action frames so the browser can present the same history.
            response["presentation_steps"] = presentation_steps
        return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1701)
    args = parser.parse_args()

    cards.db.initialize()
    human = Player("Human", ["CS2_231"] * 30, "HERO_08")
    opponent = Player("Heuristic", ["CS2_231"] * 30, "HERO_01")
    game = Game((human, opponent), seed=args.seed)
    web_game = ShowcaseGame(
        GameSession(game, {}), human, HeuristicAgent()
    )
    server = make_server(web_game, host="127.0.0.1", port=args.port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(
        json.dumps(
            {"url": f"http://127.0.0.1:{server.server_port}/", "port": server.server_port}
        ),
        flush=True,
    )
    try:
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
