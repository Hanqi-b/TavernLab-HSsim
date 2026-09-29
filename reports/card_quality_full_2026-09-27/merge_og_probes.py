"""Merge three independently executed OG card-probe batches."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SEGMENTS = ("a", "b", "c")


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    baseline = read("og_yellow_baseline.csv")
    ids = [row["card_id"] for row in baseline]
    assert len(ids) == len(set(ids)) == 126
    all_verdicts = []
    all_cases = []
    for index, segment in enumerate(SEGMENTS):
        expected = set(ids[index * 42:(index + 1) * 42])
        verdicts = read(f"og_verdict_{segment}.csv")
        cases = read(f"og_probe_{segment}.csv")
        actual = {row["card_id"] for row in verdicts}
        assert len(verdicts) == len(actual) == len(expected) == 42, segment
        assert actual == expected, segment
        assert all(case["card_id"] in expected for case in cases), segment
        for row in verdicts:
            row["probe_file"] = "og_probe.csv"
        all_verdicts.extend(verdicts)
        all_cases.extend(cases)
    by_id = {row["card_id"]: row for row in all_verdicts}
    cases_by_id = defaultdict(list)
    for row in all_cases:
        cases_by_id[row["card_id"]].append(row)
    verdicts = [by_id[card_id] for card_id in ids]
    cases = [row for card_id in ids for row in cases_by_id[card_id]]
    for row in verdicts:
        own = cases_by_id[row["card_id"]]
        assert own and len({case["case_id"] for case in own}) == len(own), row["card_id"]
        assert any(not case["case_id"].startswith("existing_test_") for case in own)
        if row["status"] == "GREEN":
            assert all(case["outcome"] == "pass" for case in own), row["card_id"]
        elif row["status"] == "RED":
            assert any(case["outcome"] == "confirmed_error" for case in own), row["card_id"]
        else:
            assert row["status"] == "YELLOW" and row["reason"], row["card_id"]
    write("og_verdict.csv", verdicts)
    write("og_probe.csv", cases)
    print(f"OG: cards={len(verdicts)}, cases={len(cases)}, statuses={dict(Counter(row['status'] for row in verdicts))}")


if __name__ == "__main__":
    main()
