"""Merge the seven independent per-card KARA/GANGS/UNGORO audit slices."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SETS = (
    ("kara", "One Night in Karazhan (KARA)", (43,)),
    ("gangs", "Mean Streets of Gadgetzan (GANGS)", (44, 43, 43)),
    ("ungoro", "Journey to Un'Goro (UNGORO)", (45, 44, 44)),
)
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name, rows, fields):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    baseline = read("three_set_yellow_baseline.csv")
    assert len(baseline) == len({row["card_id"] for row in baseline}) == 306
    all_verdicts, all_cases = [], []
    for prefix, set_name, sizes in SETS:
        ids = [row["card_id"] for row in baseline if row["set"] == set_name]
        assert len(ids) == sum(sizes), (set_name, len(ids))
        by_id = {}
        cases_by_id = defaultdict(list)
        start = 0
        for index, size in enumerate(sizes):
            suffix = chr(ord("a") + index)
            stem = f"{prefix}_{suffix}"
            expected = set(ids[start:start + size])
            start += size
            script_time = (HERE / f"{prefix}_probe_{suffix}.py").stat().st_mtime_ns
            for name in (f"{prefix}_probe_{suffix}.csv", f"{prefix}_verdict_{suffix}.csv"):
                assert (HERE / name).stat().st_mtime_ns >= script_time, name
            verdicts = read(f"{prefix}_verdict_{suffix}.csv")
            cases = read(f"{prefix}_probe_{suffix}.csv")
            actual = {row["card_id"] for row in verdicts}
            assert len(verdicts) == len(actual) == size and actual == expected, stem
            assert cases and all(row["card_id"] in expected for row in cases), stem
            for verdict in verdicts:
                assert verdict["status"] in {"GREEN", "YELLOW", "RED"}, verdict
                assert verdict["reason"] and verdict["notes"], verdict["card_id"]
                by_id[verdict["card_id"]] = {**verdict, "probe_file": "three_set_probe.csv"}
            for case in cases:
                assert case["case_id"] and case["expected"] and case["observed"], case
                assert case["outcome"] in {"pass", "confirmed_error", "inconclusive"}, case
                cases_by_id[case["card_id"]].append({
                    **case,
                    "case_id": f"{case['card_id']}::{case['case_id']}",
                    "notes": f"batch={stem}; {case['notes']}",
                })
        for card_id in ids:
            verdict = by_id[card_id]
            own = cases_by_id[card_id]
            assert own and len({row["case_id"] for row in own}) == len(own), card_id
            assert any(not row["case_id"].split("::", 1)[1].startswith("existing_test_") for row in own)
            if verdict["status"] == "GREEN":
                assert all(row["outcome"] == "pass" for row in own), card_id
            elif verdict["status"] == "RED":
                assert any(row["outcome"] == "confirmed_error" for row in own), card_id
            all_verdicts.append(verdict)
            all_cases.extend(own)
    assert len(all_verdicts) == 306 == len({row["card_id"] for row in all_verdicts})
    assert len(all_cases) == len({row["case_id"] for row in all_cases})
    write("three_set_verdict.csv", all_verdicts, VERDICT_FIELDS)
    write("three_set_probe.csv", all_cases, PROBE_FIELDS)
    print("three sets:", len(all_verdicts), "cards,", len(all_cases), "cases,",
          dict(Counter(row["status"] for row in all_verdicts)))


if __name__ == "__main__":
    main()
