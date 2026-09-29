"""Check no-target rejection for every collectible card with a targeting prerequisite."""

import csv
import logging
import random
from collections import Counter
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from fireplace.cards import db
from fireplace.exceptions import InvalidAction
from fireplace.targeting import TARGETING_PREREQUISITES
from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def run(card_id, seed):
    random.seed(seed)
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    player.summon("CS2_231")
    game.player2.summon("CS2_231")
    card = player.give(card_id)
    before_zone = card.zone
    before_mana = player.mana
    row = dict(card_id=card_id, playable=card.is_playable(), requires_target=card.requires_target(),
               target_count=len(card.targets), outcome="", exception="", zone_after="", mana_after="",
               invalid_self_outcome="")
    if not row["playable"] or not row["requires_target"]:
        row["outcome"] = "condition_not_met"
        return row
    try:
        card.play()
        row["outcome"] = "accepted_without_target"
    except InvalidAction as error:
        row["outcome"] = ("rejected_no_target" if "requires a target" in str(error) else
                          "choice_required_first" if "requires a choice" in str(error) else
                          "other_invalid_action")
        row["exception"] = str(error)
    except Exception as error:
        row["outcome"] = "unexpected_exception"
        row["exception"] = f"{type(error).__name__}: {error}"
    row["zone_after"] = card.zone.name
    row["mana_after"] = player.mana
    if row["outcome"] == "rejected_no_target" and (card.zone != before_zone or player.mana != before_mana):
        row["outcome"] = "rejected_but_state_changed"
    if row["outcome"] == "rejected_no_target":
        try:
            card.play(target=card)
            row["invalid_self_outcome"] = "accepted"
        except InvalidAction:
            row["invalid_self_outcome"] = "rejected"
        except Exception as error:
            row["invalid_self_outcome"] = f"{type(error).__name__}: {error}"
        if row["invalid_self_outcome"] != "rejected" or card.zone != before_zone or player.mana != before_mana:
            row["outcome"] = "invalid_self_problem"
    return row


def main():
    db.initialize()
    ids = [card_id for card_id, card in sorted(db.items())
           if card.collectible and card.card_set.name != "HERO_SKINS" and
           any(key in TARGETING_PREREQUISITES for key in card.requirements)]
    rows = [run(card_id, 4100 + index) for index, card_id in enumerate(ids)]
    path = Path(__file__).with_name("targeting_prereq_sweep.csv")
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts = Counter(row["outcome"] for row in rows)
    print("targeting prerequisite cards", len(rows), dict(counts))
    for row in rows:
        if row["outcome"] not in {"condition_not_met", "rejected_no_target", "choice_required_first"}:
            print(row)


if __name__ == "__main__":
    main()
