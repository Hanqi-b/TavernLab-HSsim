"""Export final per-card quality for the four newly audited YELLOW sets."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIELDS = ("version", "set", "card_id", "name_en", "name_zh", "mechanic",
          "status", "implementation", "tested", "reason", "evidence", "notes",
          "card_text_en", "card_text_zh", "python_source")
SET_FILES = {
    "Goblins vs Gnomes (GVG)": (118, "gvg_yellow_quality.csv"),
    "Blackrock Mountain (BRM)": (30, "brm_yellow_quality.csv"),
    "The Grand Tournament (TGT)": (125, "tgt_yellow_quality.csv"),
    "League of Explorers (LOE)": (42, "loe_yellow_quality.csv"),
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
    baseline = read("four_set_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    master = {row["card_id"]: row for row in read("card_master.csv")}
    assert len(baseline) == 315 and len(quality) == 2497
    grouped = {name: [] for name in SET_FILES}
    for original in baseline:
        row = {**quality[original["card_id"]],
               "card_text_zh": master[original["card_id"]]["card_text_zh"]}
        assert original["status"] == "YELLOW"
        assert row["version"] == original["version"] and row["set"] == original["set"]
        assert row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
        assert row["reason"] and row["evidence"] and row["status"] in {"GREEN", "YELLOW", "RED"}
        grouped[row["set"]].append(row)
    combined = []
    for name, (expected, filename) in SET_FILES.items():
        rows = sorted(grouped[name], key=lambda row: row["card_id"])
        assert len(rows) == expected
        write(filename, rows)
        combined.extend(rows)
        print(name, len(rows), dict(Counter(row["status"] for row in rows)))
    write("four_set_yellow_quality.csv", combined)
    assert len(combined) == len({row["card_id"] for row in combined}) == 315


if __name__ == "__main__":
    main()
