"""Freeze the collectible YELLOW roster before continuing later set audits.

The file is intentionally immutable after creation: downstream per-card probes
can be merged into card_quality.csv without changing their assigned roster.
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "card_quality.csv"
TARGET = HERE / "remaining_yellow_baseline.csv"
SUMMARY = HERE / "remaining_set_baseline.csv"


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    if TARGET.exists() or SUMMARY.exists():
        raise SystemExit("baseline already exists; preserve the original roster")
    rows = read(SOURCE)
    assert len(rows) == 2497 == len({row["card_id"] for row in rows})
    yellow = sorted((row for row in rows if row["status"] == "YELLOW"),
                    key=lambda row: (row["set"], row["card_id"]))
    assert len(yellow) == 1139
    assert all(row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
               for row in yellow)
    fields = list(yellow[0])
    write(TARGET, fields, yellow)
    by_set = defaultdict(list)
    for row in rows:
        by_set[row["set"]].append(row)
    summary = []
    for name, group in sorted(by_set.items()):
        counts = Counter(row["status"] for row in group)
        if not counts["YELLOW"]:
            continue
        assert len({row["version"] for row in group}) == 1
        summary.append(dict(version=group[0]["version"], set=name,
                            collectible=len(group), green=counts["GREEN"],
                            yellow=counts["YELLOW"], red=counts["RED"]))
    assert len(summary) == 17 and sum(int(row["yellow"]) for row in summary) == 1139
    write(SUMMARY, ("version", "set", "collectible", "green", "yellow", "red"), summary)
    print("frozen", len(yellow), "YELLOW cards across", len(summary), "sets")


if __name__ == "__main__":
    main()
