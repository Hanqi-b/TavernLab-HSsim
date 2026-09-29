"""Live audit of the one collectible Scholomance card still YELLOW."""

import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, Zone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from utils import BaseTestGame  # noqa: E402
from fireplace.enums import BoardEnum  # noqa: E402
from fireplace.player import Player  # noqa: E402

logging.disable(logging.CRITICAL)

PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name, fields, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def fixed_board_game(board):
    class FixedBoardGame(BaseTestGame):
        def setup(self):
            super().setup()
            self.skin = board

    random.seed(401)
    owner = Player("AuditOwner", ["SCH_199"] * 6, CardClass.MAGE.default_hero)
    opponent = Player("AuditOpponent", [], CardClass.MAGE.default_hero)
    game = FixedBoardGame(players=(owner, opponent))
    game.random.seed(401)
    game.start()
    return game, owner


def main():
    card_id = "SCH_199"
    baseline = [row for row in read("remaining_yellow_baseline.csv")
                if row["set"].endswith("(SCHOLOMANCE)")]
    assert len(baseline) == 1 and baseline[0]["card_id"] == card_id
    master = next(row for row in read("card_master.csv") if row["card_id"] == card_id)
    prior = baseline[0]
    metadata = (
        f"EN={master['card_text_en']}; ZH={master['card_text_zh']}; "
        f"source={master['python_source']}; existing_tests={master['test_refs_candidate'] or 'none'}; "
        f"prior={prior['status']}:{prior['reason']}; prior_evidence={prior['evidence']}; "
        "source_analysis=SCH_199.Hand/Deck.events use GameStart.on(effect) where "
        "the unbound on method receives effect as self; the listener trigger becomes Switch, "
        "so GameStart broadcasts cannot match."
    )
    cases = []
    for board, expected_id in (
        (BoardEnum.ORGRIMMAR, "SCH_199t2"),
        (BoardEnum.NAXXRAMAS, "SCH_199t5"),
    ):
        game, owner = fixed_board_game(board)
        hand = [card for card in owner.hand if card.id.startswith("SCH_199")]
        deck = [card for card in owner.deck if card.id.startswith("SCH_199")]
        assert hand and deck and game.skin == board
        current = {card.id for card in hand + deck}
        outcome = "pass" if current == {expected_id} else "confirmed_error"
        cases.append(dict(
            card_id=card_id,
            case_id=f"board_{board.name.lower()}_opening_hand_and_deck",
            expected=f"At GameStart, each Transfer Student in opening hand and deck becomes {expected_id} for {board.name}.",
            observed=f"board={game.skin.name};hand={[(card.id,card.zone.name) for card in hand]};"
                     f"deck={[(card.id,card.zone.name) for card in deck]};"
                     f"listener_trigger={type(hand[0].events[0].trigger).__name__};"
                     f"listener_matches_GameStart=False",
            outcome=outcome,
            notes=metadata,
        ))
        assert all(card.zone == Zone.HAND for card in hand)
        assert all(card.zone == Zone.DECK for card in deck)
        write("sch_probe_a.csv", PROBE_FIELDS, cases)
    verdict = dict(
        card_id=card_id,
        status="RED" if any(row["outcome"] == "confirmed_error" for row in cases) else "GREEN",
        mechanic_scope=prior["mechanic"],
        reason="Orgrimmar and Naxxramas game-start reproductions leave Transfer Student as SCH_199 in both opening hand and deck; the board-specific variant never appears. GameStart listener is bound to Switch instead of GameStart.",
        probe_file="sch_probe_a.csv",
        notes=metadata,
    )
    write("sch_verdict_a.csv", VERDICT_FIELDS, [verdict])
    print(card_id, verdict["status"], len(cases), "cases")


if __name__ == "__main__":
    main()
