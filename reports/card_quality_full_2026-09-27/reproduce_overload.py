"""Exercise every ordinary collectible Overload card through the next turn."""

import csv
import logging
import random
from pathlib import Path

from hearthstone.enums import CardClass, GameTag

from fireplace.cards import db
from utils import prepare_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def run(card_id, expected, seed):
    random.seed(seed)
    game = prepare_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    player.summon("CS2_231")
    game.player2.summon("CS2_231")
    card = player.give(card_id)
    row = dict(card_id=card_id, expected_overload=expected, outcome="", overloaded_after_play="",
               overloaded_next_turn="", locked_next_turn="", mana_next_turn="", exception="")
    try:
        if not card.is_playable():
            row["outcome"] = "unplayable_in_setup"
            return row
        targets = list(card.targets)
        card.play(target=targets[0] if targets else None)
        if player.choice:
            player.choice.choose(player.choice.cards[0])
        row["overloaded_after_play"] = player.overloaded
        game.end_turn()
        game.end_turn()
        row["overloaded_next_turn"] = player.overloaded
        row["locked_next_turn"] = player.overload_locked
        row["mana_next_turn"] = player.mana
        row["outcome"] = ("pass" if player.overloaded == 0 and
                          row["overloaded_after_play"] == expected and
                          player.overload_locked == expected and
                          player.mana == 10 - expected else "wrong_state")
    except Exception as error:
        row["outcome"] = "exception"
        row["exception"] = f"{type(error).__name__}: {error}"
    return row


def main():
    db.initialize()
    cards = [(card_id, int(card.tags[GameTag.OVERLOAD])) for card_id, card in sorted(db.items())
             if card.collectible and card.card_set.name != "HERO_SKINS" and card.tags.get(GameTag.OVERLOAD)]
    rows = [run(card_id, expected, 1900 + index) for index, (card_id, expected) in enumerate(cards)]
    path = Path(__file__).with_name("overload_reproductions.csv")
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(len(rows), "Overload cards", {outcome: sum(row["outcome"] == outcome for row in rows) for outcome in sorted({r["outcome"] for r in rows})})
    assert len(rows) == 35 and all(row["outcome"] == "pass" for row in rows)


if __name__ == "__main__":
    main()
