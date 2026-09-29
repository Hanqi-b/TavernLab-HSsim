"""Summarize progress against the frozen remaining-YELLOW roster."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
FIELDS = ("version", "set", "baseline_yellow", "audited", "green", "yellow",
          "red", "cases", "audit_state")


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    baseline = read(HERE / "remaining_yellow_baseline.csv")
    quality = {row["card_id"]: row for row in read(HERE / "card_quality.csv")}
    by_set = defaultdict(list)
    for row in baseline:
        by_set[row["set"]].append(row)
    audited = set()
    case_counts = Counter()
    for verdict_file in sorted(HERE.glob("set_verdict_*.csv")):
        code = verdict_file.stem.removeprefix("set_verdict_")
        probe_file = HERE / f"set_probe_{code}.csv"
        assert probe_file.exists(), probe_file
        verdicts = read(verdict_file)
        for row in verdicts:
            if (quality[row["card_id"]]["status"] == row["status"]
                    and quality[row["card_id"]]["reason"] == row["reason"]):
                assert row["card_id"] not in audited
                audited.add(row["card_id"])
        case_counts.update(row["card_id"] for row in read(probe_file)
                           if row["card_id"] in audited)
    residual_file = HERE / "residual_verdict.csv"
    residual_probe = HERE / "residual_probe.csv"
    if residual_file.exists() and residual_probe.exists():
        for row in read(residual_file):
            if (quality[row["card_id"]]["status"] == row["status"]
                    and quality[row["card_id"]]["reason"] == row["reason"]):
                assert row["card_id"] not in audited
                audited.add(row["card_id"])
        case_counts.update(row["card_id"] for row in read(residual_probe)
                           if row["card_id"] in audited)
    result = []
    for set_name, old in sorted(by_set.items()):
        current = [quality[row["card_id"]] for row in old]
        statuses = Counter(row["status"] for row in current)
        own_audited = sum(row["card_id"] in audited for row in old)
        result.append(dict(version=old[0]["version"], set=set_name,
                           baseline_yellow=len(old), audited=own_audited,
                           green=statuses["GREEN"], yellow=statuses["YELLOW"],
                           red=statuses["RED"],
                           cases=sum(case_counts[row["card_id"]] for row in old),
                           audit_state="complete" if own_audited == len(old) else "in_progress" if own_audited else "pending"))
    assert sum(int(row["baseline_yellow"]) for row in result) == 1139
    with (HERE / "remaining_set_progress.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(result)
    print("audited", len(audited), "of 1139;", Counter(row["audit_state"] for row in result))


if __name__ == "__main__":
    main()
