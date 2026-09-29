"""Verify traceable, collectible-only KARA/GANGS/UNGORO card verdicts."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SETS = (
    ("kara", "One Night in Karazhan (KARA)", 45, "a"),
    ("gangs", "Mean Streets of Gadgetzan (GANGS)", 132, "abc"),
    ("ungoro", "Journey to Un'Goro (UNGORO)", 135, "abc"),
)


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = read("three_set_yellow_baseline.csv")
    verdicts = read("three_set_verdict.csv")
    cases = read("three_set_probe.csv")
    exported_yellow = read("three_set_yellow_quality.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    labels = defaultdict(set)
    for row in read("card_mechanism.csv"):
        labels[row["card_id"]].add(row["mechanic"])
    ids = [row["card_id"] for row in baseline]
    assert len(ids) == len(set(ids)) == len(verdicts) == len(exported_yellow) == 306
    assert all(row["status"] == "YELLOW" for row in baseline)
    assert {row["card_id"] for row in verdicts} == set(ids)
    assert {row["card_id"] for row in exported_yellow} == set(ids)
    assert len(cases) == len({row["case_id"] for row in cases})
    merged_time = min((HERE / name).stat().st_mtime_ns
                      for name in ("three_set_verdict.csv", "three_set_probe.csv"))
    for prefix, set_name, count, suffixes in SETS:
        output = read(f"{prefix}_quality.csv")
        assert len(output) == len({row["card_id"] for row in output}) == count
        assert all(row["set"] == set_name and row["status"] in {"GREEN", "YELLOW", "RED"}
                   for row in output)
        assert all(quality[row["card_id"]]["scope"] == "ordinary_collectible"
                   and quality[row["card_id"]]["collectible"] == "yes" for row in output)
        for suffix in suffixes:
            script_time = (HERE / f"{prefix}_probe_{suffix}.py").stat().st_mtime_ns
            for kind in ("verdict", "probe"):
                batch_time = (HERE / f"{prefix}_{kind}_{suffix}.csv").stat().st_mtime_ns
                assert batch_time >= script_time, f"{prefix}_{kind}_{suffix}.csv"
                assert merged_time >= batch_time, f"merged before {prefix}_{kind}_{suffix}.csv"
    by_card = defaultdict(list)
    for case in cases:
        assert case["card_id"] in ids and case["case_id"].startswith(f"{case['card_id']}::")
        assert case["expected"] and case["observed"] and case["outcome"] in {
            "pass", "confirmed_error", "inconclusive"
        }
        by_card[case["card_id"]].append(case)
    verdict_by_id = {row["card_id"]: row for row in verdicts}
    totals = Counter()
    for baseline_row in baseline:
        cid = baseline_row["card_id"]
        verdict = verdict_by_id[cid]
        own = by_card[cid]
        assert own and verdict["reason"] and verdict["notes"]
        assert verdict["probe_file"] == "three_set_probe.csv"
        scope = set(verdict["mechanic_scope"].split("|"))
        assert scope and scope <= labels[cid], (cid, scope, labels[cid])
        if verdict["status"] == "GREEN":
            assert scope == labels[cid] and all(case["outcome"] == "pass" for case in own), cid
        elif verdict["status"] == "RED":
            assert any(case["outcome"] == "confirmed_error" for case in own), cid
        else:
            assert verdict["status"] == "YELLOW" and verdict["reason"], cid
        row = quality[cid]
        assert row["set"] == baseline_row["set"] and row["status"] == verdict["status"]
        assert row["reason"] == verdict["reason"]
        assert row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
        assert all(f"three_set_probe.csv#{case['case_id']}" in row["evidence"] for case in own)
        totals[row["status"]] += 1
    assert totals.total() == 306
    print("verified three sets", len(verdicts), "cards,", len(cases), "cases,", dict(totals))


if __name__ == "__main__":
    main()
