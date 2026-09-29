"""Apply verified BRM and TGT fixes to current quality views."""

import os
import subprocess
from collections import Counter, defaultdict

from apply_remediation_results import (
    HERE, ROOT, SYNC_COLUMNS, read_csv, validate_tables, verify_archive, write_csv,
)


VERDICT_FILE = HERE / "brm_tgt_red_fix_verdicts_2026-09-29.csv"
EXPECTED_IDS = {
    "BRM_002", "BRM_029", "AT_008", "AT_049", "AT_069", "AT_090", "AT_109",
}
RESOLVED_ISSUES = {
    "RANDOM-002": {"BRM_002"},
    "READY-001": {"BRM_029"},
    "ATTACK-001": {"AT_109"},
}


def main():
    verify_archive()
    _, verdict_rows = read_csv(VERDICT_FILE)
    verdicts = {row["card_id"]: row for row in verdict_rows}
    assert len(verdict_rows) == len(EXPECTED_IDS) and set(verdicts) == EXPECTED_IDS
    assert all(row["status"] == "GREEN" and row["tested"] == "yes" for row in verdict_rows)

    nodes = sorted({node for row in verdict_rows for node in row["test_nodes"].split("|")})
    assert all((ROOT / node.split("::", 1)[0]).is_file() for node in nodes)
    environment = os.environ.copy()
    environment.update(PYTHONPATH="tests:.", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    subprocess.run(
        [str(ROOT / "venv/bin/python"), "-m", "pytest", "-q", "--show-capture=no", *nodes],
        cwd=ROOT, env=environment, check=True,
    )

    quality_fields, quality = read_csv(HERE / "card_quality.csv")
    mechanism_fields, mechanisms = read_csv(HERE / "card_mechanism.csv")
    assert {row["card_id"] for row in quality if row["card_id"] in verdicts} == EXPECTED_IDS
    for rows in (quality, mechanisms):
        for row in rows:
            verdict = verdicts.get(row["card_id"])
            if verdict:
                for column in ("status", "implementation", "tested", "reason"):
                    row[column] = verdict[column]
                row["evidence"] = "; ".join(verdict["test_nodes"].split("|"))
                row["notes"] = (
                    "原始RED结论保留于known_issues_archive_2026-09-29/。 "
                    + verdict["notes"]
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
            source = quality_by_id.get(row["card_id"])
            if source and row["card_id"] in verdicts:
                for column in SYNC_COLUMNS:
                    if column in row:
                        row[column] = source[column]
                touched = True
        if touched:
            write_csv(path, fields, rows)

    write_csv(HERE / "card_quality.csv", quality_fields, quality)
    write_csv(HERE / "card_mechanism.csv", mechanism_fields, mechanisms)
    red_fields, _ = read_csv(HERE / "red_cards.csv")
    write_csv(
        HERE / "red_cards.csv", red_fields,
        [{key: row.get(key, "") for key in red_fields} for row in quality if row["status"] == "RED"],
    )

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

    issue_fields, issues = read_csv(HERE / "mechanism_issues.csv")
    for row in issues:
        issue_id = row["issue_id"]
        if issue_id not in RESOLVED_ISSUES:
            continue
        assert set(row["confirmed_cards"].split("|")) == RESOLVED_ISSUES[issue_id]
        row["severity"] = "resolved_tested"
        if not row["summary"].startswith("修复前问题："):
            row["summary"] = "修复前问题：" + row["summary"]
        row["next_test"] = "确认受影响卡已逐张重测；其他候选卡仍需独立验证。"
        row["evidence"] = (
            row["evidence"].split("; 当前复测：")[0]
            + "; 当前复测：reports/card_quality_full_2026-09-27/"
            + VERDICT_FILE.name + "#" + issue_id
        )
    write_csv(HERE / "mechanism_issues.csv", issue_fields, issues)
    verify_archive()
    print("Current card grades:", dict(Counter(row["status"] for row in quality)))


if __name__ == "__main__":
    main()
