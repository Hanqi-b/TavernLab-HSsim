"""Verify individual Classic, Hall of Fame, and Naxxramas Yellow-card verdicts."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
GROUPS = {
    "classic_first": ("Classic (EXPERT1)", "classic_verdict_first.csv", "classic_probe_first.csv"),
    "classic_middle_a": ("Classic (EXPERT1)", "classic_verdict_middle_a.csv", "classic_probe_middle_a.csv"),
    "classic_second": ("Classic (EXPERT1)", "classic_verdict_second.csv", "classic_probe_second.csv"),
    "classic_middle_b": ("Classic (EXPERT1)", "classic_verdict_middle_b.csv", "classic_probe_middle_b.csv"),
    "classic_final10": ("Classic (EXPERT1)", "classic_verdict_final10.csv", "classic_probe_final10.csv"),
    "classic_tail": ("Classic (EXPERT1)", "classic_verdict_tail.csv", "classic_probe_tail.csv"),
    "hof": ("Hall of Fame (HOF)", "hof_verdict.csv", "hof_probe.csv"),
    "naxx": ("Curse of Naxxramas (NAXX)", "naxx_verdict.csv", "naxx_probe.csv"),
}


def read_csv(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = read_csv("expansion_yellow_baseline.csv")
    assert len(baseline) == 291
    original = {row["card_id"]: row for row in baseline}
    assert len(original) == len(baseline)
    by_set = defaultdict(list)
    for row in baseline:
        by_set[row["set"]].append(row["card_id"])
    classic_ids = sorted(by_set["Classic (EXPERT1)"])
    half = len(classic_ids) // 2
    expected = {
        "classic_first": set(classic_ids[:85]),
        "classic_middle_a": set(classic_ids[85:half]),
        "classic_second": set(classic_ids[half:179]),
        "classic_middle_b": set(classic_ids[179:199]),
        "classic_final10": set(classic_ids[199:-20]),
        "classic_tail": set(classic_ids[-20:]),
        "hof": set(by_set["Hall of Fame (HOF)"]),
        "naxx": set(by_set["Curse of Naxxramas (NAXX)"]),
    }
    assert list(map(len, expected.values())) == [85, 29, 65, 20, 10, 20, 34, 28]
    quality = {row["card_id"]: row for row in read_csv("card_quality.csv")}
    labels = defaultdict(set)
    for row in read_csv("card_mechanism.csv"):
        labels[row["card_id"]].add(row["mechanic"])

    verdict_count = case_count = 0
    outcomes = Counter()
    for group, (set_name, verdict_name, probe_name) in GROUPS.items():
        verdicts = read_csv(verdict_name)
        cases = read_csv(probe_name)
        assert {row["card_id"] for row in verdicts} == expected[group], group
        assert len(verdicts) == len(expected[group]), group
        assert all(original[row["card_id"]]["set"] == set_name for row in verdicts)
        assert (HERE / probe_name).stat().st_mtime_ns >= (HERE / probe_name.replace(".csv", ".py")).stat().st_mtime_ns
        by_card = defaultdict(list)
        for case in cases:
            assert case["card_id"] in expected[group], (group, case["card_id"])
            assert case["outcome"] in {"pass", "confirmed_error", "inconclusive"}
            assert case["expected"] and case["observed"] and case["case_id"] and case["notes"]
            by_card[case["card_id"]].append(case)
        for verdict in verdicts:
            cid, status = verdict["card_id"], verdict["status"]
            assert status in {"GREEN", "YELLOW", "RED"}
            assert verdict["probe_file"] == probe_name
            assert verdict["reason"] and verdict["notes"]
            scope = set(verdict["mechanic_scope"].split("|"))
            assert scope and scope <= labels[cid], cid
            if status == "GREEN":
                assert scope == labels[cid], cid
            card_cases = by_card[cid]
            assert card_cases and len({case["case_id"] for case in card_cases}) == len(card_cases), cid
            if status == "GREEN":
                assert all(case["outcome"] == "pass" for case in card_cases), cid
            elif status == "RED":
                assert any(case["outcome"] == "confirmed_error" for case in card_cases), cid
            assert quality[cid]["status"] == status and quality[cid]["reason"] == verdict["reason"], cid
            assert all(f"{probe_name}#{case['case_id']}" in quality[cid]["evidence"] for case in card_cases), cid
            verdict_count += 1
            case_count += len(card_cases)
            outcomes[status] += 1
        assert len(cases) == sum(map(len, by_card.values()))
    assert verdict_count == len(original)
    exported = read_csv("expansion_yellow_quality.csv")
    assert len(exported) == 291 and {row["card_id"] for row in exported} == set(original)
    for set_name, filename in (("Classic (EXPERT1)", "classic_yellow_quality.csv"),
                               ("Hall of Fame (HOF)", "hof_yellow_quality.csv"),
                               ("Curse of Naxxramas (NAXX)", "naxx_yellow_quality.csv")):
        subset = read_csv(filename)
        assert {row["card_id"] for row in subset} == set(by_set[set_name])
        assert all(row["set"] == set_name and quality[row["card_id"]]["status"] == row["status"]
                   for row in subset)
    print(f"verified {verdict_count} expansion verdicts, {case_count} individual cases, statuses={dict(outcomes)}")


if __name__ == "__main__":
    main()
