"""Check follow-up cases for the 25 legacy-set YELLOW cards."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
SET_CODES = ("(BASIC)", "(EXPERT1)", "(GVG)", "(LOE)", "(GANGS)", "(OG)")


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = [row for row in read("remaining_yellow_baseline.csv")
                if row["set"].endswith(SET_CODES)]
    verdicts = read("residual_verdict.csv")
    probes = read("residual_probe.csv")
    quality = {row["card_id"]: row for row in read("card_quality.csv")}
    ids = {row["card_id"] for row in baseline}
    assert len(baseline) == len(ids) == len(verdicts) == 25
    assert {row["card_id"] for row in verdicts} == ids
    cases = defaultdict(list)
    for row in probes:
        assert row["card_id"] in ids and row["case_id"].startswith(f"{row['card_id']}::")
        assert row["expected"] and row["observed"] and row["notes"]
        assert row["outcome"] in {"pass", "confirmed_error", "inconclusive"}
        cases[row["card_id"]].append(row)
    assert len(probes) == len({row["case_id"] for row in probes})
    for verdict in verdicts:
        card_id = verdict["card_id"]
        own = cases[card_id]
        assert own and verdict["reason"] and verdict["notes"]
        assert any("EN=" in row["notes"] and "ZH=" in row["notes"] for row in own)
        assert verdict["probe_file"] == "residual_probe.csv"
        assert verdict["status"] in {"GREEN", "YELLOW", "RED"}
        if verdict["status"] == "GREEN":
            assert all(row["outcome"] == "pass" for row in own)
        elif verdict["status"] == "RED":
            assert any(row["outcome"] == "confirmed_error" for row in own)
        else:
            assert not any(row["outcome"] == "confirmed_error" for row in own)
        row = quality[card_id]
        assert row["status"] == verdict["status"] and row["reason"] == verdict["reason"]
        assert all(f"residual_probe.csv#{case['case_id']}" in row["evidence"] for case in own)
    print("verified residual", len(verdicts), "cards", len(probes), "cases",
          dict(Counter(row["status"] for row in verdicts)))


if __name__ == "__main__":
    main()
