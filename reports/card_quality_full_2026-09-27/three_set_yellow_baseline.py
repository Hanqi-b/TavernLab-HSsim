"""Freeze the original collectible YELLOW roster for KARA, GANGS and UNGORO."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SET_ORDER = (
    "One Night in Karazhan (KARA)",
    "Mean Streets of Gadgetzan (GANGS)",
    "Journey to Un'Goro (UNGORO)",
)
FIELDS = ("version", "set", "card_id", "name_en", "name_zh", "status")


def main():
    with (HERE / "card_quality.csv").open(encoding="utf-8-sig", newline="") as stream:
        quality = list(csv.DictReader(stream))
    rows = sorted(
        (row for row in quality if row["set"] in SET_ORDER and row["status"] == "YELLOW"),
        key=lambda row: (SET_ORDER.index(row["set"]), row["card_id"]),
    )
    counts = Counter(row["set"] for row in rows)
    assert [counts[set_name] for set_name in SET_ORDER] == [43, 130, 133], counts
    assert len(rows) == len({row["card_id"] for row in rows}) == 306
    assert all(row["scope"] == "ordinary_collectible" and row["collectible"] == "yes" for row in rows)
    with (HERE / "three_set_yellow_baseline.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in FIELDS} for row in rows)
    print("frozen", dict(counts))


if __name__ == "__main__":
    main()
