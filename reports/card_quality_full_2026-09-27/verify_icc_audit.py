"""Verify ICECROWN results against the frozen collectible YELLOW roster."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SET = "Knights of the Frozen Throne (ICECROWN)"


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = read("icecrown_yellow_baseline.csv")
    verdicts = read("icc_verdict.csv")
    cases = read("icc_probe.csv")
    exported = read("icc_yellow_quality.csv")
    full = read("icc_quality.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    labels = defaultdict(set)
    for row in read("card_mechanism.csv"):
        labels[row["card_id"]].add(row["mechanic"])
    ids = [row["card_id"] for row in baseline]
    assert len(ids) == len(set(ids)) == len(verdicts) == len(exported) == 132
    assert len(full) == len({row["card_id"] for row in full}) == 135
    assert {row["card_id"] for row in verdicts} == set(ids)
    assert {row["card_id"] for row in exported} == set(ids)
    assert all(row["set"] == SET and row["status"] in {"GREEN", "YELLOW", "RED"}
               for row in full)
    assert all(quality[row["card_id"]]["scope"] == "ordinary_collectible"
               and quality[row["card_id"]]["collectible"] == "yes" for row in full)
    merged_time = min((HERE / name).stat().st_mtime_ns
                      for name in ("icc_verdict.csv", "icc_probe.csv"))
    for suffix in "abc":
        script_time = (HERE / f"icc_probe_{suffix}.py").stat().st_mtime_ns
        for kind in ("probe", "verdict"):
            batch_time = (HERE / f"icc_{kind}_{suffix}.csv").stat().st_mtime_ns
            assert batch_time >= script_time, f"icc_{kind}_{suffix}.csv"
            assert merged_time >= batch_time, f"merged before icc_{kind}_{suffix}.csv"
    cases_by_id = defaultdict(list)
    for case in cases:
        assert case["card_id"] in ids and case["case_id"].startswith(f"{case['card_id']}::")
        assert case["expected"] and case["observed"] and case["outcome"] in {
            "pass", "confirmed_error", "inconclusive"
        }
        cases_by_id[case["card_id"]].append(case)
    verdict_by_id = {row["card_id"]: row for row in verdicts}
    totals = Counter()
    for old in baseline:
        cid = old["card_id"]
        verdict = verdict_by_id[cid]
        own = cases_by_id[cid]
        assert own and verdict["reason"] and verdict["notes"]
        assert verdict["probe_file"] == "icc_probe.csv"
        scope = set(verdict["mechanic_scope"].split("|"))
        assert scope and scope <= labels[cid], (cid, scope, labels[cid])
        if verdict["status"] == "GREEN":
            assert scope == labels[cid] and all(case["outcome"] == "pass" for case in own), cid
        elif verdict["status"] == "RED":
            assert any(case["outcome"] == "confirmed_error" for case in own), cid
        else:
            assert verdict["status"] == "YELLOW" and verdict["reason"], cid
        row = quality[cid]
        assert row["set"] == SET and row["status"] == verdict["status"]
        assert row["reason"] == verdict["reason"]
        assert all(f"icc_probe.csv#{case['case_id']}" in row["evidence"] for case in own)
        totals[row["status"]] += 1
    assert sum(totals.values()) == 132
    print("verified ICECROWN", len(verdicts), "cards", len(cases), "cases", dict(totals))


if __name__ == "__main__":
    main()
