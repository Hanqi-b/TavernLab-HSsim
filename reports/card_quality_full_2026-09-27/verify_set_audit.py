"""Check a completed collectible set audit against its frozen roster."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("set_code")
    args = parser.parse_args()
    code = args.set_code.upper()
    baseline = [row for row in read("remaining_yellow_baseline.csv")
                if row["set"].endswith(f"({code})")]
    verdict_name = f"set_verdict_{code}.csv"
    probe_name = f"set_probe_{code}.csv"
    verdicts = read(verdict_name)
    probes = read(probe_name)
    exported = read(f"quality_{code}.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    baseline_ids = {row["card_id"] for row in baseline}
    verdict_ids = {row["card_id"] for row in verdicts}
    assert baseline and len(baseline) == len(baseline_ids) == len(verdicts)
    assert verdict_ids == baseline_ids
    assert len(exported) == len({row["card_id"] for row in exported})
    assert all(row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
               for row in baseline)
    assert all(row["set"].endswith(f"({code})") for row in exported)
    by_card = defaultdict(list)
    for case in probes:
        card_id = case["card_id"]
        assert card_id in baseline_ids and case["case_id"].startswith(f"{card_id}::")
        assert case["expected"] and case["observed"] and case["notes"]
        assert case["outcome"] in {"pass", "confirmed_error", "inconclusive"}
        by_card[card_id].append(case)
    assert len(probes) == len({row["case_id"] for row in probes})
    for verdict in verdicts:
        card_id = verdict["card_id"]
        own = by_card[card_id]
        assert own and verdict["reason"] and verdict["notes"]
        assert verdict["probe_file"] == probe_name
        assert verdict["status"] in {"GREEN", "YELLOW", "RED"}
        if verdict["status"] == "GREEN":
            assert all(row["outcome"] == "pass" for row in own), card_id
        elif verdict["status"] == "RED":
            assert any(row["outcome"] == "confirmed_error" for row in own), card_id
        row = quality[card_id]
        assert row["status"] == verdict["status"] and row["reason"] == verdict["reason"]
        assert row["scope"] == "ordinary_collectible" and row["collectible"] == "yes"
        assert all(f"{probe_name}#{case['case_id']}" in row["evidence"] for case in own)
    print("verified", code, len(verdicts), "cards", len(probes), "cases",
          dict(Counter(row["status"] for row in verdicts)))


if __name__ == "__main__":
    main()
