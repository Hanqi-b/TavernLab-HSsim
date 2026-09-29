"""Verify every original GVG/BRM/TGT/LOE YELLOW has traceable live cases."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
GROUPS = {
    "Goblins vs Gnomes (GVG)": (118, "gvg_verdict.csv", "gvg_probe.csv", "gvg_yellow_quality.csv"),
    "Blackrock Mountain (BRM)": (30, "brm_verdict.csv", "brm_probe.csv", "brm_yellow_quality.csv"),
    "The Grand Tournament (TGT)": (125, "tgt_verdict.csv", "tgt_probe.csv", "tgt_yellow_quality.csv"),
    "League of Explorers (LOE)": (42, "loe_verdict.csv", "loe_probe.csv", "loe_yellow_quality.csv"),
}


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = read("four_set_yellow_baseline.csv")
    assert len(baseline) == 315 and len({row["card_id"] for row in baseline}) == 315
    assert all(row["status"] == "YELLOW" for row in baseline)
    baseline_by_set = defaultdict(set)
    for row in baseline:
        baseline_by_set[row["set"]].add(row["card_id"])
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    labels = defaultdict(set)
    for row in read("card_mechanism.csv"):
        labels[row["card_id"]].add(row["mechanic"])
    combined = {row["card_id"]: row for row in read("four_set_yellow_quality.csv")}
    assert set(combined) == {row["card_id"] for row in baseline}
    total_cases = 0
    totals = Counter()
    for set_name, (expected, verdict_name, probe_name, export_name) in GROUPS.items():
        target = baseline_by_set[set_name]
        assert len(target) == expected
        verdicts = read(verdict_name)
        cases = read(probe_name)
        exported = read(export_name)
        assert len(verdicts) == len(exported) == expected
        assert {row["card_id"] for row in verdicts} == target
        assert {row["card_id"] for row in exported} == target
        assert (HERE / probe_name).stat().st_mtime_ns >= (HERE / probe_name.replace(".csv", ".py")).stat().st_mtime_ns
        by_card = defaultdict(list)
        for case in cases:
            assert case["card_id"] in target
            assert case["case_id"] and case["expected"] and case["observed"]
            assert case["outcome"] in {"pass", "confirmed_error", "inconclusive"}
            by_card[case["card_id"]].append(case)
        for verdict in verdicts:
            cid, status = verdict["card_id"], verdict["status"]
            assert status in {"GREEN", "YELLOW", "RED"}
            assert verdict["reason"] and verdict["notes"] and verdict["probe_file"] == probe_name
            scope = set(verdict["mechanic_scope"].split("|"))
            assert scope and scope <= labels[cid]
            if status == "GREEN":
                assert scope == labels[cid], cid
            own_cases = by_card[cid]
            assert own_cases and len({case["case_id"] for case in own_cases}) == len(own_cases), cid
            # A reference to a pre-existing test is supporting context, not the
            # card-specific live probe requested for this four-set audit.
            assert any(not case["case_id"].startswith("existing_test_") for case in own_cases), cid
            if status == "GREEN":
                assert all(case["outcome"] == "pass" for case in own_cases), cid
            elif status == "RED":
                assert any(case["outcome"] == "confirmed_error" for case in own_cases), cid
            else:
                assert verdict["reason"] and verdict["notes"]
            row = quality[cid]
            assert row["status"] == status and row["reason"] == verdict["reason"], cid
            assert row["set"] == set_name and row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
            assert combined[cid]["status"] == status
            assert all(f"{probe_name}#{case['case_id']}" in row["evidence"] for case in own_cases)
            totals[status] += 1
            total_cases += len(own_cases)
        assert len(cases) == sum(map(len, by_card.values()))
    assert totals.total() == 315
    print(f"verified 315 individual verdicts, {total_cases} cases, statuses={dict(totals)}")


if __name__ == "__main__":
    main()
