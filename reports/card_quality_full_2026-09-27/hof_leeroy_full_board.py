"""Live full-opponent-board branch for collectible Leeroy Jenkins."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE = HERE / "hof_probe.csv"
VERDICT = HERE / "hof_verdict.csv"
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, data):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


def main():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    owner, opponent = game.player1, game.player2
    for _ in range(7):
        opponent.summon(WISP)
    assert len(opponent.field) == 7
    leeroy = owner.give("EX1_116")
    leeroy.play()
    observed = (f"enemy_field_count={len(opponent.field)};"
                f"enemy_ids={[m.id for m in opponent.field]};"
                f"whelps={sum(m.id == 'EX1_116t' for m in opponent.field)};"
                f"leeroy={leeroy.zone.name}")
    # Full board has no legal slot for the Battlecry's enemy-owned Whelps.
    outcome = "pass" if len(opponent.field) == 7 and not any(m.id == "EX1_116t" for m in opponent.field) else "confirmed_error"
    assert leeroy.zone == Zone.PLAY
    probe_rows = read(PROBE)
    case_id = "battlecry_on_full_enemy_board"
    probe_rows = [r for r in probe_rows if (r["card_id"], r["case_id"]) != ("EX1_116", case_id)]
    probe_rows.append(dict(card_id="EX1_116", case_id=case_id,
                           expected="With seven enemy minions, Leeroy cannot summon either Whelp and enemy field remains seven.",
                           observed=observed, outcome=outcome,
                           notes="Full-board branch; see hof_leeroy_full_board.py. Existing normal-board case stays valid."))
    write(PROBE, ("card_id", "case_id", "expected", "observed", "outcome", "notes"), probe_rows)
    verdict_rows = read(VERDICT)
    for row in verdict_rows:
        if row["card_id"] == "EX1_116":
            row["status"] = "RED" if outcome == "confirmed_error" else "GREEN"
            row["reason"] = ("敌方场上原有7随从时，勒罗伊战吼仍新增两只雏龙，使敌方场上达9个实体；违反7格上限。"
                             if outcome == "confirmed_error" else "普通场面与敌方满场分支均符合召唤和场位限制。")
            row["notes"] = "hof_probe.py 普通场面通过；hof_leeroy_full_board.py 敌方满场复现。"
    write(VERDICT, ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes"), verdict_rows)
    print(f"EX1_116 {outcome}: {observed}")


if __name__ == "__main__":
    main()
