"""Export collectible-only ICECROWN card quality CSVs."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
SET = "Knights of the Frozen Throne (ICECROWN)"
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
    baseline = read("icecrown_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    master = {row["card_id"]: row for row in read("card_master.csv")}
    assert len(baseline) == 132 and len(quality) == 2497
    assert len({row["card_id"] for row in baseline}) == 132
    all_rows = [{**row, "card_text_zh": master[row["card_id"]]["card_text_zh"]}
                for row in quality.values() if row["set"] == SET]
    all_rows.sort(key=lambda row: row["card_id"])
    assert len(all_rows) == 135
    assert all(row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
               for row in all_rows)
    write("icc_quality.csv", all_rows)
    original_yellow = []
    for old in baseline:
        row = quality[old["card_id"]]
        assert old["status"] == "YELLOW" and row["set"] == SET
        assert row["version"] == old["version"] and row["reason"] and row["evidence"]
        original_yellow.append({**row, "card_text_zh": master[row["card_id"]]["card_text_zh"]})
    write("icc_yellow_quality.csv", original_yellow)
    print("ICECROWN", len(all_rows), dict(Counter(row["status"] for row in all_rows)))
    print("original YELLOW", len(original_yellow),
          dict(Counter(row["status"] for row in original_yellow)))


if __name__ == "__main__":
    main()
