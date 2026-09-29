"""Reproduce death-event selector behavior without changing card implementations."""

import csv
import logging
import sys
from pathlib import Path

from hearthstone.enums import CardClass, Zone


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tests"))
from utils import WISP, prepare_empty_game  # noqa: E402


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
FIELDS = ("case_id", "card_id", "expected", "observed", "outcome", "evidence")


def game():
    result = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    result.player1.discard_hand()
    return result, result.player1


def main():
    rows = []
    for card_id, expected_token in (("GIL_819", None), ("ICC_900", "ICC_900t")):
        _, player = game()
        listener = player.summon(card_id)
        victim = player.summon(WISP)
        victim.destroy()
        if expected_token:
            observed_count = sum(card.id == expected_token for card in player.field)
            expectation = f"one {expected_token} summoned after a friendly minion dies"
        else:
            observed_count = len(player.hand)
            expectation = "one random Shaman spell added to hand after a friendly minion dies"
        assert listener.zone == Zone.PLAY and victim.zone == Zone.GRAVEYARD
        rows.append(dict(case_id=f"death_zone_{card_id}", card_id=card_id,
                         expected=expectation,
                         observed=f"effect_count={observed_count};victim_zone={victim.zone.name}",
                         outcome="confirmed_error" if observed_count == 0 else "pass",
                         evidence="fireplace/actions.py:345-374; fireplace/dsl/selector.py:532,549"))

    _, player = game()
    player.summon("EX1_595")
    top = player.give(WISP)
    top.shuffle_into_deck()
    victim = player.summon(WISP)
    victim.destroy()
    observed = top in player.hand and len(player.deck) == 0
    rows.append(dict(case_id="death_zone_control_EX1_595", card_id="EX1_595",
                     expected="zone-independent Death(FRIENDLY + MINION) draws the known top card",
                     observed=f"drawn={observed};hand={[card.id for card in player.hand]};victim_zone={victim.zone.name}",
                     outcome="pass" if observed else "confirmed_error",
                     evidence="fireplace/cards/classic/neutral_common.py:96"))
    assert [row["outcome"] for row in rows] == ["confirmed_error", "confirmed_error", "pass"]
    with (HERE / "og_death_selector_probe.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print("Death event selector cases:", [(row["card_id"], row["outcome"]) for row in rows])


if __name__ == "__main__":
    main()
