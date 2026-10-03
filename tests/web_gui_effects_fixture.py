#!/usr/bin/env python3
"""Real-engine effect animation scenarios; all match state stays in memory."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hearthstone.enums import Zone

from fireplace import cards
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.server import WebGame, make_server


class PassAgent:
    def choose_action(self, observation, actions):
        return next((action for action in actions if action.type == "END_TURN"), actions[0])


class EffectScenario(WebGame):
    def __init__(self, *args, scenario, **kwargs):
        self.scenario = scenario
        self.prepared = False
        super().__init__(*args, **kwargs)

    def handle_action(self, payload):
        response = super().handle_action(payload)
        if not self.prepared and payload.get("action", {}).get("type") == "MULLIGAN":
            with self.lock:
                human, opponent = self.human, self.human.opponent
                human.max_mana = 10
                human.used_mana = 0
                for card in list(human.hand):
                    card.zone = Zone.SETASIDE
                if self.scenario == "battlecry":
                    human.give("CS2_189")  # Elven Archer: targeted battlecry.
                    creeper = opponent.summon("FP1_002")
                    creeper.damage = 1  # One health; its death summons two spiders.
                elif self.scenario == "reflow":
                    human.give("CS2_189")  # Elven Archer: targeted battlecry.
                    creeper = opponent.summon("FP1_002")
                    creeper.damage = 1  # One health; its death summons two spiders.
                    opponent.summon("CS2_182")  # A survivor keeps board reflow visible.
                elif self.scenario == "draw":
                    human.give("EX1_015")  # Novice Engineer: battlecry draws a card.
                elif self.scenario == "depletion":
                    # Leave exactly one public deck card so Arcane Intellect
                    # emits a normal draw followed by one real fatigue tick.
                    for card in list(human.deck)[1:]:
                        card.zone = Zone.SETASIDE
                    human.give("CS2_023")  # Arcane Intellect: draw two.
                    human.give("EX1_015")  # Empty-deck fatigue 2.
                    human.give("EX1_015")  # Empty-deck fatigue 3.
                elif self.scenario == "elysiana":
                    # Keep more than ten cards so the full deck destruction is
                    # visible as one coalesced, privacy-safe effect record.
                    for card in list(human.deck)[11:]:
                        card.zone = Zone.SETASIDE
                    human.give("DAL_736")  # Archivist Elysiana.
                elif self.scenario == "combat":
                    attacker = human.summon("CS2_182")
                    attacker.turns_in_play = 1
                    sheep = opponent.summon("GVG_076")
                    sheep.damage = 1
                elif self.scenario in ("hero_combat", "hero_combat_trigger", "hero_combat_hero"):
                    human.summon("EX1_133" if self.scenario == "hero_combat_hero" else "CS2_106")
                    if self.scenario == "hero_combat_hero":
                        # Exhaust the weapon while hitting an armored hero.
                        human.weapon.damage = human.weapon.max_durability - 1
                        opponent.hero.armor = 3
                    if self.scenario == "hero_combat_trigger":
                        human.summon("CS2_182")  # A survivor receives deathrattle damage.
                        opponent.summon("GVG_076")
                    elif self.scenario == "hero_combat":
                        opponent.summon("CS2_182")
                elif self.scenario == "hero_power":
                    # Jaina's Fireblast supplies a source-free hero-power
                    # effect against the public opposing hero.
                    pass
                else:
                    human.give("CS2_032")  # Flamestrike: simultaneous enemy damage.
                    opponent.summon("GVG_076")  # Explosive Sheep: two damage to minions.
                    opponent.summon("CS2_231")
                    abomination = human.summon("EX1_097")
                    abomination.damage = abomination.max_health - 2
                    yeti = human.summon("CS2_182")
                    yeti.damage = yeti.max_health - 3
                self.prepared = True
                self._revision += 1
                response = self.snapshot()
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=(
            "battlecry", "chain", "combat", "hero_combat", "hero_combat_trigger",
            "hero_combat_hero", "draw", "depletion", "elysiana", "hero_power", "reflow",
        ),
        required=True,
    )
    args = parser.parse_args()
    cards.db.initialize()
    human = Player("Animation tester", ["CS2_231"] * 30, "HERO_08")
    opponent = Player("Opponent", ["CS2_231"] * 30, "HERO_01")
    app = EffectScenario(GameSession(Game((human, opponent), seed=7), {}), human,
                         PassAgent(), scenario=args.scenario)
    server = make_server(app, host="127.0.0.1", port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/"}), flush=True)
    try:
        worker.join()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    main()
