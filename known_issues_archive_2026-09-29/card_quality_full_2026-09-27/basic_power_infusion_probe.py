"""Compare Basic EX1_194's printed +2/+6 with its actual buff."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
OUT = Path(__file__).with_suffix(".csv")


def main():
    game = prepare_empty_game(CardClass.PRIEST, CardClass.MAGE)
    player = game.current_player
    target = player.summon("CS2_179")
    spell = player.give("EX1_194")
    before = (target.atk, target.health, target.max_health)
    legal = target in spell.targets
    spell.play(target=target)
    after = (target.atk, target.health, target.max_health)
    expected = (before[0] + 2, before[1] + 6, before[2] + 6)
    observed = (f"legal_target={legal};stats={before}->{after};expected={expected};"
                f"target_zone={target.zone.name};spell_zone={spell.zone.name}")
    row = dict(case_id="BASIC-INFUSION-01", card_id="EX1_194",
               mechanic="Spell resolution|Targeting",
               expected="A minion gains +2 Attack and +6 current/max Health; spell enters graveyard",
               observed=observed,
               outcome=("pass" if legal and after == expected and target.zone == Zone.PLAY
                        and spell.zone == Zone.GRAVEYARD else "confirmed_error"))
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(row["outcome"], observed)


if __name__ == "__main__":
    main()
