"""Full-opponent-board control for Deathlord's existing-deck-card summon."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE = HERE / "naxx_probe.csv"
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def main():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    owner, opponent = game.player1, game.player2
    for _ in range(7):
        opponent.summon(WISP)
    known = opponent.give("CS2_182")
    known.shuffle_into_deck()
    deathlord = owner.give("FP1_009")
    deathlord.play()
    deathlord.destroy()
    observed = (f"enemy_field_count={len(opponent.field)};"
                f"known_card_zone={known.zone.name};enemy_deck_count={len(opponent.deck)};"
                f"deathlord_zone={deathlord.zone.name}")
    assert len(opponent.field) == 7 and known.zone == Zone.DECK and len(opponent.deck) == 1, observed
    assert deathlord.zone == Zone.GRAVEYARD, observed
    case = dict(card_id="FP1_009", case_id="full_enemy_board_no_eighth_from_deck",
                expected="When the enemy board already has seven minions, Deathlord cannot pull an eighth; the known minion remains in its owner's deck.",
                observed=observed, outcome="pass",
                notes="Control for Summon(OPPONENT, existing enemy-owned deck card); see naxx_deathlord_full_board.py")
    with PROBE.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows = [r for r in rows if (r["card_id"], r["case_id"]) != (case["card_id"], case["case_id"])]
    rows.append(case)
    with PROBE.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("card_id", "case_id", "expected", "observed", "outcome", "notes"))
        writer.writeheader()
        writer.writerows(rows)
    print(f"FP1_009 pass: {observed}")


if __name__ == "__main__":
    main()
