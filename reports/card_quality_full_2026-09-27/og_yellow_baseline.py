"""Freeze the original collectible YELLOW roster for Whispers of the Old Gods."""

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "card_quality.csv"
DEST = HERE / "og_yellow_baseline.csv"
SET = "Whispers of the Old Gods (OG)"
FIELDS = ("version", "set", "card_id", "name_en", "name_zh", "status")


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    if DEST.exists():
        rows = read(DEST)
        assert len(rows) == len({row["card_id"] for row in rows}) == 126
        assert all(row["set"] == SET and row["status"] == "YELLOW" for row in rows)
        print("existing OG baseline verified: 126 cards")
        return
    rows = [row for row in read(SOURCE)
            if row["set"] == SET and row["status"] == "YELLOW"
            and row["collectible"] == "yes" and row["scope"] == "ordinary_collectible"]
    rows.sort(key=lambda row: row["card_id"])
    assert len(rows) == len({row["card_id"] for row in rows}) == 126
    with DEST.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in FIELDS} for row in rows)
    print("frozen OG baseline: 126 cards")


if __name__ == "__main__":
    main()
