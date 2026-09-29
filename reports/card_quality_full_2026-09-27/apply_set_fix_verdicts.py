"""Apply one verified expansion's per-card verdicts to current quality views.

Usage: python apply_set_fix_verdicts.py <verdict.csv>
The archived pre-fix audit is checked before and after, never rewritten.
"""

import os
import subprocess
import sys
from collections import Counter, defaultdict

from apply_remediation_results import (
    HERE, ROOT, SYNC_COLUMNS, read_csv, validate_tables, verify_archive, write_csv,
)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_set_fix_verdicts.py <verdict.csv>")
    verdict_file = HERE / sys.argv[1]
    if verdict_file.parent != HERE or not verdict_file.is_file():
        raise ValueError("Verdict CSV must be inside the current quality-report folder")
    verify_archive()
    _, verdict_rows = read_csv(verdict_file)
    verdicts = {row["card_id"]: row for row in verdict_rows}
    if len(verdicts) != len(verdict_rows) or not verdicts:
        raise ValueError("Duplicate or empty card verdict roster")
    for row in verdict_rows:
        verified_green = (
            row["status"] == "GREEN"
            and row["tested"] == "yes"
            and row["implementation"] == "implemented"
        )
        partially_verified_yellow = (
            row["status"] == "YELLOW"
            and row["tested"] == "partial"
            and row["implementation"] in {"partial", "implemented"}
        )
        if not (verified_green or partially_verified_yellow):
            raise ValueError(f"Unsupported verdict: {row['card_id']}")
        if not row["reason"] or not row["test_nodes"]:
            raise ValueError(f"Missing evidence: {row['card_id']}")

    nodes = sorted({node for row in verdict_rows for node in row["test_nodes"].split("|")})
    if not all((ROOT / node.split("::", 1)[0]).is_file() for node in nodes):
        raise ValueError("Missing targeted test file")
    environment = os.environ.copy()
    environment.update(PYTHONPATH="tests:.", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    subprocess.run(
        [str(ROOT / "venv/bin/python"), "-m", "pytest", "-q", "--show-capture=no", "--disable-warnings", *nodes],
        cwd=ROOT, env=environment, check=True,
    )

    quality_fields, quality = read_csv(HERE / "card_quality.csv")
    mechanism_fields, mechanisms = read_csv(HERE / "card_mechanism.csv")
    if {row["card_id"] for row in quality if row["card_id"] in verdicts} != set(verdicts):
        raise ValueError("Verdict includes a non-collectible or unknown card")
    for rows in (quality, mechanisms):
        for row in rows:
            verdict = verdicts.get(row["card_id"])
            if verdict:
                for column in ("status", "implementation", "tested", "reason"):
                    row[column] = verdict[column]
                row["evidence"] = "; ".join(verdict["test_nodes"].split("|"))
                row["notes"] = (
                    "原始结论保留于known_issues_archive_2026-09-29/。 " + verdict["notes"]
                )
    validate_tables(quality, mechanisms)
    quality_by_id = {row["card_id"]: row for row in quality}
    for path in HERE.glob("*quality*.csv"):
        if path.name in {"card_quality.csv", "card_mechanism.csv"} or "baseline" in path.stem:
            continue
        fields, rows = read_csv(path)
        if not fields or not {"card_id", "status"} <= set(fields):
            continue
        touched = False
        for row in rows:
            if row["card_id"] in verdicts:
                source = quality_by_id[row["card_id"]]
                for column in SYNC_COLUMNS:
                    if column in row:
                        row[column] = source[column]
                touched = True
        if touched:
            write_csv(path, fields, rows)
    write_csv(HERE / "card_quality.csv", quality_fields, quality)
    write_csv(HERE / "card_mechanism.csv", mechanism_fields, mechanisms)
    red_fields, _ = read_csv(HERE / "red_cards.csv")
    write_csv(HERE / "red_cards.csv", red_fields, [
        {key: row.get(key, "") for key in red_fields} for row in quality if row["status"] == "RED"
    ])

    inventory_fields, inventory = read_csv(HERE / "set_inventory.csv")
    by_set = defaultdict(Counter)
    for row in quality:
        by_set[row["set"]][row["status"]] += 1
    for row in inventory:
        for grade in ("GREEN", "YELLOW", "RED"):
            row[f"quality_{grade.lower()}"] = str(by_set[row["set"]][grade])
    write_csv(HERE / "set_inventory.csv", inventory_fields, inventory)

    queue_fields, queue = read_csv(HERE / "mechanism_queue.csv")
    by_mechanism = defaultdict(Counter)
    for row in mechanisms:
        by_mechanism[row["mechanic"]][row["status"]] += 1
    for row in queue:
        for grade in ("GREEN", "YELLOW", "RED"):
            row[grade.lower()] = str(by_mechanism[row["mechanism"]][grade])
    write_csv(HERE / "mechanism_queue.csv", queue_fields, queue)
    verify_archive()
    print(f"Applied {verdict_file.name}:", dict(Counter(row["status"] for row in quality)))


if __name__ == "__main__":
    main()
