"""Verify every original OG YELLOW has traceable individual live-game evidence."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SET = "Whispers of the Old Gods (OG)"


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = read("og_yellow_baseline.csv")
    ids = [row["card_id"] for row in baseline]
    assert len(ids) == len(set(ids)) == 126
    assert all(row["status"] == "YELLOW" and row["set"] == SET for row in baseline)
    verdicts = read("og_verdict.csv")
    cases = read("og_probe.csv")
    exported = read("og_yellow_quality.csv")
    complete = read("og_quality.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    labels = defaultdict(set)
    for row in read("card_mechanism.csv"):
        labels[row["card_id"]].add(row["mechanic"])
    assert len(verdicts) == len(exported) == 126
    assert len(complete) == len({row["card_id"] for row in complete}) == 134
    assert all(row["set"] == SET for row in complete)
    assert {row["card_id"] for row in verdicts} == set(ids)
    assert {row["card_id"] for row in exported} == set(ids)
    assert {row["card_id"]: row for row in complete if row["card_id"] in ids} == {row["card_id"]: row for row in exported}
    for segment in "abc":
        script_mtime = (HERE / f"og_probe_{segment}.py").stat().st_mtime_ns
        for output in (f"og_probe_{segment}.csv", f"og_verdict_{segment}.csv"):
            assert (HERE / output).stat().st_mtime_ns >= script_mtime, output
    merged_mtime = min((HERE / name).stat().st_mtime_ns
                       for name in ("og_probe.csv", "og_verdict.csv"))
    assert merged_mtime >= max((HERE / f"og_{kind}_{segment}.csv").stat().st_mtime_ns
                               for kind in ("probe", "verdict") for segment in "abc")
    by_card = defaultdict(list)
    for case in cases:
        assert case["card_id"] in ids
        assert case["case_id"] and case["expected"] and case["observed"]
        assert case["outcome"] in {"pass", "confirmed_error", "inconclusive"}
        by_card[case["card_id"]].append(case)
    totals = Counter()
    for verdict in verdicts:
        cid, state = verdict["card_id"], verdict["status"]
        assert state in {"GREEN", "YELLOW", "RED"}
        assert verdict["reason"] and verdict["notes"] and verdict["probe_file"] == "og_probe.csv"
        scope = set(verdict["mechanic_scope"].split("|"))
        assert scope and scope <= labels[cid]
        if state == "GREEN":
            assert scope == labels[cid], cid
        own = by_card[cid]
        assert own and len({case["case_id"] for case in own}) == len(own), cid
        assert any(not case["case_id"].startswith("existing_test_") for case in own), cid
        if state == "GREEN":
            assert all(case["outcome"] == "pass" for case in own), cid
        elif state == "RED":
            assert any(case["outcome"] == "confirmed_error" for case in own), cid
        row = quality[cid]
        assert row["status"] == state and row["reason"] == verdict["reason"], cid
        assert row["set"] == SET and row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
        assert all(f"og_probe.csv#{case['case_id']}" in row["evidence"] for case in own)
        totals[state] += 1
    assert totals.total() == 126
    print(f"verified 126 OG verdicts, {len(cases)} cases, statuses={dict(totals)}")


if __name__ == "__main__":
    main()
