"""Verify every ordinary collectible minion with no text or card script.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/vanilla_runtime_probe.py
"""

import csv
from collections import Counter
from pathlib import Path

import fireplace.cards as carddb
from fireplace.cards import get_script_definition
from hearthstone.enums import CardType

from basic_runtime_probe import FIELDS, ROWS, no_script_entry_probe


HERE = Path(__file__).resolve().parent
OUT = HERE / "vanilla_runtime_probe.csv"


def read_rows(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    carddb.db.initialize()
    master = {row["card_id"]: row for row in read_rows("card_master.csv")}
    vanilla_ids = {
        row["card_id"]
        for row in read_rows("card_mechanism.csv")
        if row["mechanic"] == "Vanilla"
        and not row["card_text_en"].strip()
    }
    ROWS.clear()
    for card_id in sorted(vanilla_ids):
        row = master[card_id]
        data = carddb.db[card_id]
        assert row["scope"] == "ordinary_collectible"
        assert row["card_type"] == "MINION" and data.type == CardType.MINION
        assert not row["python_source"] and get_script_definition(card_id, data) is None
        no_script_entry_probe(card_id)

    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)

    outcomes = Counter(row["outcome"] for row in ROWS)
    print(f"plain-vanilla cards={len(vanilla_ids)}; outcomes={dict(outcomes)}; csv={OUT}")
    for row in ROWS:
        if row["outcome"] != "PASS":
            print(f"{row['case_id']}: {row['outcome']}: {row['observed']}")
    if outcomes.get("FAIL"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
