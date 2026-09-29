"""Reproduce Draw's cross-player counter attribution without changing card code."""

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
    for player in (owner, opponent):
        for _ in range(4):
            player.give("CS2_231").shuffle_into_deck()
    before = {player.name: (len(player.hand), len(player.deck), player.cards_drawn_this_turn)
              for player in (owner, opponent)}
    oracle = owner.give("EX1_050")
    oracle.play()
    after = {player.name: (len(player.hand), len(player.deck), player.cards_drawn_this_turn)
             for player in (owner, opponent)}
    actual_draw = {player.name: (after[player.name][0] - before[player.name][0],
                                 before[player.name][1] - after[player.name][1])
                   for player in (owner, opponent)}
    counter_change = {player.name: after[player.name][2] - before[player.name][2]
                      for player in (owner, opponent)}
    expected = "both players hand/deck +2/-2; each player's cards_drawn_this_turn +2"
    observed = (f"actual_draw={actual_draw};counter_change={counter_change};"
                f"oracle_zone={oracle.zone.name}")
    valid = (all(actual_draw[player.name] == (2, 2) for player in (owner, opponent))
             and counter_change == {owner.name: 2, opponent.name: 2}
             and oracle.zone == Zone.PLAY)
    row = dict(case_id="DRAW-01", mechanism="Draw / Discard", card_ids="EX1_050",
               expected=expected, observed=observed,
               outcome="pass" if valid else "confirmed_error")
    with (HERE / "cross_player_draw_probe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    print(row)


if __name__ == "__main__":
    main()
