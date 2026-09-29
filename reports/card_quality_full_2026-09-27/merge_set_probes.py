"""Merge one set's frozen per-card probe slices after all slices finish."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("set_code", help="CardSet code, e.g. LOOTAPALOOZA")
    parser.add_argument("prefix", help="Slice-file prefix, e.g. loot")
    parser.add_argument("sizes", nargs="+", type=int, help="Consecutive slice sizes")
    args = parser.parse_args()
    assert args.sizes and all(size > 0 for size in args.sizes)
    assert len(args.sizes) <= 26
    set_code = args.set_code.upper()
    all_yellow = read(HERE / "remaining_yellow_baseline.csv")
    roster = sorted((row for row in all_yellow if row["set"].endswith(f"({set_code})")),
                    key=lambda row: row["card_id"])
    ids = [row["card_id"] for row in roster]
    assert ids and len(ids) == len(set(ids)) == sum(args.sizes)
    merged_probe_name = f"set_probe_{set_code}.csv"
    merged_verdict_name = f"set_verdict_{set_code}.csv"
    verdict_by_id = {}
    cases_by_id = defaultdict(list)
    start = 0
    for i, size in enumerate(args.sizes):
        suffix = chr(ord("a") + i)
        end = start + size
        expected = set(ids[start:end])
        script = HERE / f"{args.prefix}_probe_{suffix}.py"
        probe_file = HERE / f"{args.prefix}_probe_{suffix}.csv"
        verdict_file = HERE / f"{args.prefix}_verdict_{suffix}.csv"
        assert script.is_file() and probe_file.is_file() and verdict_file.is_file()
        assert probe_file.stat().st_mtime_ns >= script.stat().st_mtime_ns, probe_file
        assert verdict_file.stat().st_mtime_ns >= script.stat().st_mtime_ns, verdict_file
        verdicts = read(verdict_file)
        probes = read(probe_file)
        actual = [row["card_id"] for row in verdicts]
        assert len(actual) == len(set(actual)) == size and set(actual) == expected, suffix
        assert probes and all(row["card_id"] in expected for row in probes), suffix
        for row in verdicts:
            assert row["status"] in {"GREEN", "YELLOW", "RED"} and row["reason"]
            assert row["mechanic_scope"] and row["notes"]
            verdict_by_id[row["card_id"]] = {**row, "probe_file": merged_probe_name}
        for row in probes:
            assert row["case_id"] and row["expected"] and row["observed"]
            assert row["outcome"] in {"pass", "confirmed_error", "inconclusive"}
            cases_by_id[row["card_id"]].append({
                **row,
                "case_id": f"{row['card_id']}::{row['case_id']}",
                "notes": f"batch={args.prefix}_{suffix}; {row['notes']}",
            })
        start = end
    assert start == len(ids) == len(verdict_by_id)
    verdicts, cases = [], []
    for card_id in ids:
        verdict = verdict_by_id[card_id]
        own = cases_by_id[card_id]
        assert own and len(own) == len({row["case_id"] for row in own}), card_id
        assert (("EN=" in verdict["notes"] and "ZH=" in verdict["notes"])
                or any("EN=" in row["notes"] and "ZH=" in row["notes"] for row in own)), card_id
        if verdict["status"] == "GREEN":
            assert all(row["outcome"] == "pass" for row in own), card_id
        elif verdict["status"] == "RED":
            assert any(row["outcome"] == "confirmed_error" for row in own), card_id
        else:
            # A tested branch may pass while another documented rules branch
            # remains unresolved (for example, an effect-cast event boundary).
            assert verdict["reason"] and not any(
                row["outcome"] == "confirmed_error" for row in own), card_id
        verdicts.append(verdict)
        cases.extend(own)
    assert len(cases) == len({row["case_id"] for row in cases})
    write(HERE / merged_verdict_name, VERDICT_FIELDS, verdicts)
    write(HERE / merged_probe_name, PROBE_FIELDS, cases)
    print(set_code, len(verdicts), "cards", len(cases), "cases",
          dict(Counter(row["status"] for row in verdicts)))


if __name__ == "__main__":
    main()
