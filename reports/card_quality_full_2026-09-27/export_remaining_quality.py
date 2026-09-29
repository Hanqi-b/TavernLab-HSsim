"""Publish collectible-only quality CSVs for completed set audits.

The frozen baseline remains unchanged.  The combined view is refreshed after
each completed set so it shows both resolved cards and work still pending.
"""

import argparse
import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIELDS = ("version", "set", "card_id", "name_en", "name_zh", "mechanic",
          "status", "implementation", "tested", "reason", "evidence", "notes",
          "card_text_en", "card_text_zh", "python_source")


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in FIELDS} for row in rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-code", help="Also export a completed set, e.g. LOOTAPALOOZA")
    args = parser.parse_args()
    baseline = read("remaining_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    master = {row["card_id"]: row for row in read("card_master.csv")}
    assert len(baseline) == 1139 and len(quality) == len(master) == 2497
    assert len({row["card_id"] for row in baseline}) == len(baseline)

    remaining = []
    for old in baseline:
        card_id = old["card_id"]
        row = quality[card_id]
        assert row["set"] == old["set"] and row["version"] == old["version"]
        assert row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
        remaining.append({**row, "card_text_zh": master[card_id]["card_text_zh"]})
    remaining.sort(key=lambda row: (row["set"], row["card_id"]))
    write("remaining_yellow_quality.csv", remaining)
    print("remaining original YELLOW", len(remaining),
          dict(Counter(row["status"] for row in remaining)))

    if args.set_code:
        code = args.set_code.upper()
        own = sorted((row for row in quality.values() if row["set"].endswith(f"({code})")),
                     key=lambda row: row["card_id"])
        own_baseline = [row for row in baseline if row["set"].endswith(f"({code})")]
        assert own and own_baseline and len({row["set"] for row in own}) == 1
        verdict_file = HERE / f"set_verdict_{code}.csv"
        assert verdict_file.is_file(), verdict_file
        verdict_ids = {row["card_id"] for row in read(verdict_file.name)}
        assert verdict_ids == {row["card_id"] for row in own_baseline}
        assert all(row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
                   for row in own)
        enriched = [{**row, "card_text_zh": master[row["card_id"]]["card_text_zh"]}
                    for row in own]
        write(f"quality_{code}.csv", enriched)
        print(code, len(enriched), dict(Counter(row["status"] for row in enriched)))


if __name__ == "__main__":
    main()
