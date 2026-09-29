"""Small normal-deck controls for errors found by generic collectible smoke."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass
from utils import prepare_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def run(card_id):
    game = prepare_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    if card_id == "BT_427":
        player.summon("CS2_231").destroy()
    else:
        player.summon("CS2_231")
        game.player2.summon("CS2_231")
    card = player.give(card_id)
    targets = list(card.targets)
    result = dict(card_id=card_id, setup="normal_decks; 10 mana; Wisp on board",
                  target_count=len(targets), killed_this_turn=player.minions_killed_this_turn,
                  outcome="", exception_type="", exception_message="")
    try:
        card.play(target=targets[0] if targets else None)
        result["outcome"] = "played"
    except Exception as error:
        result["outcome"] = "exception"
        result["exception_type"] = type(error).__name__
        result["exception_message"] = str(error)
    return result


def main():
    rows = [run(cid) for cid in ("BT_427", "BT_753", "BT_801", "UNG_035", "DAL_059")]
    dest = Path(__file__).with_name("targeted_reproductions.csv")
    with dest.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)
    power_rows = []
    for cid, expected in (("AT_003", 2), ("YOD_008", 3)):
        game = prepare_game(CardClass.MAGE, CardClass.MAGE)
        game.player1.summon(cid)
        before = game.player2.hero.health
        game.player1.hero_power.use(target=game.player2.hero)
        actual = before - game.player2.hero.health
        power_rows.append(dict(card_id=cid, setup="normal_decks; Mage Fireblast against enemy hero",
                               expected_damage=expected, actual_damage=actual,
                               outcome="pass" if actual == expected else "wrong_effect"))
    dest = Path(__file__).with_name("hero_power_reproductions.csv")
    with dest.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(power_rows[0]))
        writer.writeheader()
        writer.writerows(power_rows)
    for row in power_rows:
        print(row)


if __name__ == "__main__":
    main()
