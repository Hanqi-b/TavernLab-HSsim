"""Check secret board-cap gating when a dormant minion occupies a slot."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
HERE = Path(__file__).resolve().parent


def main():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    secret = owner.give("EX1_136")
    secret.play()
    cairne = owner.summon("EX1_110")
    for _ in range(5):
        owner.summon("CS2_231")
    dormant = owner.summon("BT_934")
    before = len(owner.field)
    game.end_turn()
    opponent.give("CS2_029").play(target=cairne)
    observed = (f"initial_field={before};dormant={dormant.dormant};"
                f"after_field={len(owner.field)};after_ids={[card.id for card in owner.field]};"
                f"secret_zone={secret.zone.name};secret_still_set={secret in owner.secrets}")
    correct = (before == 7 and dormant.dormant and len(owner.field) == 7
               and any(card.id == "EX1_110t" for card in owner.field)
               and secret.zone == Zone.SECRET and secret in owner.secrets)
    row = dict(case_id="SECRET-BOARD-01", mechanism="Secret / Summon / Dormant",
               card_ids="EX1_136|EX1_110|BT_934", expected="Cairne deathrattle fills sole open slot; Redemption stays set because board is full",
               observed=observed, outcome="pass" if correct else "confirmed_error")
    with (HERE / "dormant_full_board_probe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(row)


if __name__ == "__main__":
    main()
