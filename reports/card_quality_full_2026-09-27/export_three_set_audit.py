"""Publish complete collectible quality lists for KARA, GANGS and UNGORO."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SETS = (
    ("kara", "One Night in Karazhan (KARA)", 45),
    ("gangs", "Mean Streets of Gadgetzan (GANGS)", 132),
    ("ungoro", "Journey to Un'Goro (UNGORO)", 135),
)
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
    baseline = read("three_set_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    master = {row["card_id"]: row for row in read("card_master.csv")}
    assert len(baseline) == 306 and len(quality) == 2497
    assert len({row["card_id"] for row in baseline}) == len(baseline)
    yellow_rows = []
    for prefix, set_name, expected_count in SETS:
        rows = [
            {**row, "card_text_zh": master[row["card_id"]]["card_text_zh"]}
            for row in quality.values() if row["set"] == set_name
        ]
        rows.sort(key=lambda row: row["card_id"])
        assert len(rows) == expected_count, (prefix, len(rows))
        assert all(row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
                   for row in rows)
        write(f"{prefix}_quality.csv", rows)
        print(prefix, len(rows), dict(Counter(row["status"] for row in rows)))
        for original in (row for row in baseline if row["set"] == set_name):
            current = quality[original["card_id"]]
            assert original["status"] == "YELLOW"
            assert current["set"] == set_name and current["version"] == original["version"]
            assert current["reason"] and current["evidence"]
            yellow_rows.append({**current,
                                "card_text_zh": master[original["card_id"]]["card_text_zh"]})
    assert len(yellow_rows) == 306
    write("three_set_yellow_quality.csv", yellow_rows)
    print("original YELLOW roster", dict(Counter(row["status"] for row in yellow_rows)))


if __name__ == "__main__":
    main()
