"""Export final per-card quality for the original OG YELLOW roster."""

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


def main():
    baseline = read("og_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    master = {row["card_id"]: row for row in read("card_master.csv")}
    assert len(baseline) == 126 and len(quality) == 2497
    complete = [
        {**row, "card_text_zh": master[row["card_id"]]["card_text_zh"]}
        for row in quality.values()
        if row["set"] == "Whispers of the Old Gods (OG)"
    ]
    complete.sort(key=lambda row: row["card_id"])
    assert len(complete) == 134
    rows = []
    for original in baseline:
        row = {**quality[original["card_id"]],
               "card_text_zh": master[original["card_id"]]["card_text_zh"]}
        assert original["status"] == "YELLOW"
        assert row["version"] == original["version"] and row["set"] == original["set"]
        assert row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
        assert row["reason"] and row["evidence"] and row["status"] in {"GREEN", "YELLOW", "RED"}
        rows.append(row)
    assert len(rows) == len({row["card_id"] for row in rows}) == 126
    for name, output in (("og_yellow_quality.csv", rows), ("og_quality.csv", complete)):
        with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({field: row[field] for field in FIELDS} for row in output)
    print("OG", len(rows), dict(Counter(row["status"] for row in rows)))
    print("OG whole set", len(complete), dict(Counter(row["status"] for row in complete)))


if __name__ == "__main__":
    main()
