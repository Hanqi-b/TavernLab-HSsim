"""Check weighted Discover choices when fewer than three cards qualify."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass

from fireplace.utils import weighted_card_choice
from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
HERE = Path(__file__).resolve().parent


def main():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    source = game.player1.summon("CS2_231")
    try:
        choices = weighted_card_choice(source, [1], [["CS2_231"]], 3)
        observed = "choices=" + str([card.id for card in choices])
        outcome = "pass" if len(choices) == 1 else "wrong_state"
    except Exception as error:
        observed = f"{type(error).__name__}: {error}"
        outcome = "confirmed_error"
    row = dict(case_id="DISCOVER-POOL-01", mechanism="Discover / Choice",
               card_ids="CS2_231", expected="one-card eligible pool returns one choice without exception",
               observed=observed, outcome=outcome)
    with (HERE / "discover_pool_probe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(row)


if __name__ == "__main__":
    main()
