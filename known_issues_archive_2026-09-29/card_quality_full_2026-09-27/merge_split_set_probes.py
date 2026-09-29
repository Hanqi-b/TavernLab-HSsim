"""Merge separately executed GVG/TGT tail probes into canonical per-set CSVs.

Run only after each front script finishes. The pre-merge front results are saved
as *_front.csv so both independently executed batches remain inspectable.
"""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
GROUPS = {
    "gvg": ("Goblins vs Gnomes (GVG)", 101, 17),
    "tgt": ("The Grand Tournament (TGT)", 95, 30),
}


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    baseline = read(HERE / "four_set_yellow_baseline.csv")
    for short, (set_name, front_count, tail_count) in GROUPS.items():
        base_ids = [row["card_id"] for row in baseline if row["set"] == set_name]
        front_verdict = read(HERE / f"{short}_verdict.csv")
        front_probe = read(HERE / f"{short}_probe.csv")
        tail_verdict = read(HERE / f"{short}_verdict_tail.csv")
        tail_probe = read(HERE / f"{short}_probe_tail.csv")
        front_ids = {row["card_id"] for row in front_verdict}
        tail_ids = {row["card_id"] for row in tail_verdict}
        assert len(front_verdict) == len(front_ids) == front_count, short
        assert len(tail_verdict) == len(tail_ids) == tail_count, short
        assert front_ids.isdisjoint(tail_ids), short
        assert front_ids | tail_ids == set(base_ids), short
        assert all(row["card_id"] in front_ids for row in front_probe), short
        assert all(row["card_id"] in tail_ids for row in tail_probe), short
        write(HERE / f"{short}_verdict_front.csv", front_verdict, front_verdict[0].keys())
        write(HERE / f"{short}_probe_front.csv", front_probe, front_probe[0].keys())
        for row in tail_verdict:
            row["probe_file"] = f"{short}_probe.csv"
        verdict_by_id = {row["card_id"]: row for row in front_verdict + tail_verdict}
        cases_by_id = defaultdict(list)
        for row in front_probe + tail_probe:
            cases_by_id[row["card_id"]].append(row)
        verdict = [verdict_by_id[cid] for cid in base_ids]
        cases = [row for cid in base_ids for row in cases_by_id[cid]]
        for row in verdict:
            own = cases_by_id[row["card_id"]]
            assert own and len({case["case_id"] for case in own}) == len(own), row["card_id"]
            if row["status"] == "GREEN":
                assert all(case["outcome"] == "pass" for case in own), row["card_id"]
            elif row["status"] == "RED":
                assert any(case["outcome"] == "confirmed_error" for case in own), row["card_id"]
            else:
                assert row["status"] == "YELLOW", row["card_id"]
        write(HERE / f"{short}_verdict.csv", verdict, verdict[0].keys())
        write(HERE / f"{short}_probe.csv", cases, cases[0].keys())
        print(f"{short}: cards={len(verdict)}, cases={len(cases)}, statuses={dict(Counter(row['status'] for row in verdict))}")


if __name__ == "__main__":
    main()
