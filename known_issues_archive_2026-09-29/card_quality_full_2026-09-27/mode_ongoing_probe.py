"""Check representative adventure and Battlegrounds continuous effects."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)
HERE = Path(__file__).resolve().parent


def fresh():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    return game.current_player


def main():
    rows = []
    player = fresh()
    source = player.summon("DALA_504")
    fireball = player.give("CS2_029")
    before = player.opponent.hero.health
    fireball.play(target=player.opponent.hero)
    damage = before - player.opponent.hero.health
    rows.append(dict(case_id="MODE-01", mechanism="Spell repeat", card_ids="DALA_504|CS2_029",
                     expected="one Fireball cast twice deals 12 total to enemy hero",
                     observed=f"damage={damage};source_zone={source.zone.name};spell_zone={fireball.zone.name}",
                     outcome="pass" if damage == 12 and source.zone == Zone.PLAY and fireball.zone == Zone.GRAVEYARD
                     else "confirmed_error"))
    for case_id, aura_id, minion_id, expected_attack in (
        ("MODE-02", "TB_BaconUps_008", "CS2_168", 6),
        ("MODE-03", "TB_BaconUps_038", "CS1_042", 5),
    ):
        player = fresh()
        source = player.summon(aura_id)
        recipient = player.summon(minion_id)
        rows.append(dict(case_id=case_id, mechanism="Aura", card_ids=f"{aura_id}|{minion_id}",
                         expected=f"recipient Attack becomes {expected_attack} while source is in play",
                         observed=f"recipient_attack={recipient.atk};recipient_taunt={recipient.taunt};source_zone={source.zone.name};recipient_zone={recipient.zone.name}",
                         outcome="pass" if recipient.atk == expected_attack
                         and source.zone == recipient.zone == Zone.PLAY
                         and (case_id != "MODE-03" or recipient.taunt) else "confirmed_error"))
    with (HERE / "mode_ongoing_probe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
