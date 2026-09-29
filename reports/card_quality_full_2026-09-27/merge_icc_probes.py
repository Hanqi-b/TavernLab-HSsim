"""Merge the three frozen ICECROWN per-card audit slices."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(name, fields, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    baseline = read("icecrown_yellow_baseline.csv")
    ids = [row["card_id"] for row in baseline]
    assert len(ids) == len(set(ids)) == 132
    assert ids == sorted(ids)
    assert all(row["set"] == "Knights of the Frozen Throne (ICECROWN)"
               and row["scope"] == "ordinary_collectible"
               and row["collectible"] == "yes"
               and row["status"] == "YELLOW" for row in baseline)
    verdicts_by_id = {}
    cases_by_id = defaultdict(list)
    for index, suffix in enumerate("abc"):
        expected = set(ids[index * 44:(index + 1) * 44])
        script_time = (HERE / f"icc_probe_{suffix}.py").stat().st_mtime_ns
        for name in (f"icc_probe_{suffix}.csv", f"icc_verdict_{suffix}.csv"):
            assert (HERE / name).stat().st_mtime_ns >= script_time, name
        verdicts = read(f"icc_verdict_{suffix}.csv")
        cases = read(f"icc_probe_{suffix}.csv")
        actual = {row["card_id"] for row in verdicts}
        assert len(verdicts) == len(actual) == 44 and actual == expected, suffix
        assert cases and all(row["card_id"] in expected for row in cases), suffix
        for row in verdicts:
            assert row["status"] in {"GREEN", "YELLOW", "RED"}, row
            assert row["reason"] and row["notes"] and row["mechanic_scope"], row["card_id"]
            verdicts_by_id[row["card_id"]] = {**row, "probe_file": "icc_probe.csv"}
        for row in cases:
            assert row["case_id"] and row["expected"] and row["observed"], row
            assert row["outcome"] in {"pass", "confirmed_error", "inconclusive"}, row
            cases_by_id[row["card_id"]].append({
                **row,
                "case_id": f"{row['card_id']}::{row['case_id']}",
                "notes": f"batch=icc_{suffix}; {row['notes']}",
            })
    verdicts, cases = [], []
    for card_id in ids:
        verdict = verdicts_by_id[card_id]
        own = cases_by_id[card_id]
        assert own and len({row["case_id"] for row in own}) == len(own), card_id
        assert any(not row["case_id"].split("::", 1)[1].startswith("existing_test_") for row in own)
        if verdict["status"] == "GREEN":
            assert all(row["outcome"] == "pass" for row in own), card_id
        elif verdict["status"] == "RED":
            assert any(row["outcome"] == "confirmed_error" for row in own), card_id
        verdicts.append(verdict)
        cases.extend(own)
    assert len(verdicts) == 132 == len({row["card_id"] for row in verdicts})
    assert len(cases) == len({row["case_id"] for row in cases})
    write("icc_verdict.csv", VERDICT_FIELDS, verdicts)
    write("icc_probe.csv", PROBE_FIELDS, cases)
    print("ICECROWN", len(verdicts), "cards", len(cases), "cases",
          dict(Counter(row["status"] for row in verdicts)))


if __name__ == "__main__":
    main()
