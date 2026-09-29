"""Verify Basic CS2_063 target and delayed destruction across turn starts."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
OUT = Path(__file__).with_suffix(".csv")


def main():
    game = prepare_empty_game(CardClass.WARLOCK, CardClass.MAGE)
    player = game.current_player
    opponent = player.opponent
    enemy = opponent.summon("CS2_179")
    friendly = player.summon("CS2_231")
    spell = player.give("CS2_063")
    target_ok = (enemy in spell.targets and friendly not in spell.targets
                 and opponent.hero not in spell.targets)
    spell.play(target=enemy)
    after_cast = (spell.zone == Zone.GRAVEYARD and enemy.zone == Zone.PLAY
                  and any(buff.id == "CS2_063e" for buff in enemy.buffs))
    game.end_turn()
    opponent_turn = (game.current_player is opponent and enemy.zone == Zone.PLAY)
    game.end_turn()
    next_caster_turn = (game.current_player is player and enemy.zone == Zone.GRAVEYARD
                        and enemy in opponent.graveyard)
    observed = (f"target_restrictions={target_ok};after_cast={after_cast};"
                f"opponent_turn_alive={opponent_turn};caster_next_turn_destroyed={next_caster_turn}")
    row = dict(case_id="BASIC-CORRUPTION-01", card_id="CS2_063",
               mechanic="Spell resolution|Targeting|Trigger",
               expected="Only enemy minion target; persists through opponent turn; destroyed at caster next turn start",
               observed=observed,
               outcome="pass" if all((target_ok, after_cast, opponent_turn, next_caster_turn)) else "confirmed_error")
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(row["outcome"], observed)


if __name__ == "__main__":
    main()
