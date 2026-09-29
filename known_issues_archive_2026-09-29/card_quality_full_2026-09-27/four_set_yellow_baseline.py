"""Freeze the original YELLOW collectible roster for GVG, BRM, TGT, and LOE."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "card_quality.csv"
DEST = HERE / "four_set_yellow_baseline.csv"
EXPECTED = {
    "Goblins vs Gnomes (GVG)": 118,
    "Blackrock Mountain (BRM)": 30,
    "The Grand Tournament (TGT)": 125,
    "League of Explorers (LOE)": 42,
}
FIELDS = ("version", "set", "card_id", "name_en", "name_zh", "status")


def main():
    if DEST.exists():
        with DEST.open(encoding="utf-8-sig", newline="") as stream:
            existing = list(csv.DictReader(stream))
        counts = Counter(row["set"] for row in existing)
        assert counts == EXPECTED and len(existing) == 315
        assert len({row["card_id"] for row in existing}) == 315
        assert all(row["status"] == "YELLOW" for row in existing)
        print("existing four-set baseline verified", dict(counts))
        return
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream)
                if row["set"] in EXPECTED and row["status"] == "YELLOW"
                and row["collectible"] == "yes" and row["scope"] == "ordinary_collectible"]
    rows.sort(key=lambda row: (row["set"], row["card_id"]))
    counts = Counter(row["set"] for row in rows)
    assert counts == EXPECTED and len(rows) == 315
    assert len({row["card_id"] for row in rows}) == 315
    with DEST.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in FIELDS} for row in rows)
    print("frozen four-set baseline", dict(counts))


if __name__ == "__main__":
    main()
