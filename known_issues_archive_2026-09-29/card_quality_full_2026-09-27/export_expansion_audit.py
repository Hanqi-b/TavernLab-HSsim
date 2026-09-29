"""Export final collectible per-card verdicts for the three original YELLOW sets."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIELDS = ("version", "set", "card_id", "name_en", "name_zh", "mechanic",
          "status", "implementation", "tested", "reason", "evidence", "notes",
          "card_text_en", "python_source")
SET_FILES = {
    "Classic (EXPERT1)": "classic_yellow_quality.csv",
    "Hall of Fame (HOF)": "hof_yellow_quality.csv",
    "Curse of Naxxramas (NAXX)": "naxx_yellow_quality.csv",
}


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row[field] for field in FIELDS} for row in rows)


def main():
    original = read("expansion_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    assert len(original) == 291 and len(quality) == 2497
    grouped = {name: [] for name in SET_FILES}
    for baseline in original:
        row = quality[baseline["card_id"]]
        assert baseline["status"] == "YELLOW"
        assert row["set"] == baseline["set"] and row["version"] == baseline["version"]
        assert row["collectible"] == "yes" and row["scope"] == "ordinary_collectible"
        assert row["status"] in {"GREEN", "YELLOW", "RED"}
        assert row["reason"] and row["evidence"]
        grouped[row["set"]].append(row)
    assert {name: len(rows) for name, rows in grouped.items()} == {
        "Classic (EXPERT1)": 229,
        "Hall of Fame (HOF)": 34,
        "Curse of Naxxramas (NAXX)": 28,
    }
    combined = []
    for name, rows in grouped.items():
        rows.sort(key=lambda row: row["card_id"])
        write(SET_FILES[name], rows)
        combined.extend(rows)
        print(name, len(rows), dict(Counter(row["status"] for row in rows)))
    write("expansion_yellow_quality.csv", combined)
    assert len(combined) == 291 == len({row["card_id"] for row in combined})


if __name__ == "__main__":
    main()
