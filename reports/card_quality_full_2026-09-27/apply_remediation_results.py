"""Apply current-code card retests without changing the archived audit.

The original probe/verdict CSVs remain historical evidence. This script reads
remediation_verdicts_2026-09-29.csv, reruns every declared PASS test, and then
updates the current quality tables and their derived counts together.
"""

import csv
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARCHIVE = ROOT / "known_issues_archive_2026-09-29"
VERDICTS = HERE / "remediation_verdicts_2026-09-29.csv"
ISSUES = {"BOARD-001", "BOARD-002", "DEATH-001", "DEATH-004"}
GRADES = {"GREEN", "YELLOW", "RED"}
OUTCOMES = {"PASS", "FAIL", "PARTIAL"}
SYNC_COLUMNS = ("status", "implementation", "tested", "reason", "evidence", "notes")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def write_csv(path, fields, rows):
    pending = path.with_name(path.name + ".tmp")
    with pending.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    pending.replace(path)


def verify_archive():
    result = subprocess.run(
        ["sha256sum", "-c", "SHA256SUMS", "--quiet"],
        cwd=ARCHIVE,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"Archived CSV snapshot changed: {result.stdout}{result.stderr}")


def load_verdicts(issue_rows, quality_rows):
    fields, rows = read_csv(VERDICTS)
    required = {"issue_id", "card_id", "outcome", "status", "tested", "reason", "test_nodes", "notes"}
    if not required <= set(fields or ()):
        raise ValueError(f"Verdict columns missing: {required - set(fields or ())}")
    issue_by_card = {
        card_id: issue["issue_id"]
        for issue in issue_rows if issue["issue_id"] in ISSUES
        for card_id in issue["confirmed_cards"].split("|")
    }
    expected = set(issue_by_card)
    by_id = {row["card_id"]: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != expected:
        raise ValueError(f"Retest roster differs: missing={expected-set(by_id)}, extra={set(by_id)-expected}")
    quality_ids = {row["card_id"] for row in quality_rows}
    if not expected <= quality_ids:
        raise ValueError(f"Non-collectible IDs in roster: {expected-quality_ids}")
    for row in rows:
        if row["issue_id"] not in ISSUES or row["status"] not in GRADES or row["outcome"] not in OUTCOMES:
            raise ValueError(f"Invalid issue, status or outcome for {row['card_id']}")
        if row["issue_id"] != issue_by_card[row["card_id"]]:
            raise ValueError(f"Card/issue mismatch: {row['card_id']}")
        if not row["reason"].strip() or not row["test_nodes"].strip():
            raise ValueError(f"Missing rationale or test nodes for {row['card_id']}")
        if row["status"] == "GREEN" and (row["outcome"] != "PASS" or row["tested"] != "yes"):
            raise ValueError(f"Unverified GREEN: {row['card_id']}")
        for node in row["test_nodes"].split("|"):
            path = ROOT / node.split("::", 1)[0]
            if not path.is_file() or not node.startswith("tests/test_retest_"):
                raise ValueError(f"Invalid targeted evidence: {node}")
    return by_id


def rerun_pass_cases(verdicts):
    nodes = sorted({
        node
        for row in verdicts.values()
        if row["outcome"] == "PASS"
        for node in row["test_nodes"].split("|")
    })
    environment = os.environ.copy()
    environment.update(PYTHONPATH="tests:.", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    result = subprocess.run(
        [str(ROOT / "venv/bin/python"), "-m", "pytest", "-q", "--tb=short", *nodes],
        cwd=ROOT,
        env=environment,
        text=True,
    )
    if result.returncode:
        raise RuntimeError("A card marked PASS failed its current-code behavior tests")


def sync_quality(row, verdict):
    grade = verdict["status"]
    row["status"] = grade
    row["tested"] = verdict["tested"]
    if grade == "GREEN":
        row["implementation"] = "implemented"
    elif grade == "YELLOW" and row["implementation"] == "none":
        row["implementation"] = "partial"
    row["reason"] = verdict["reason"]
    row["evidence"] = "; ".join(verdict["test_nodes"].split("|"))
    row["notes"] = (
        "本次代码重测；修复前颜色和原始失败证据见 "
        "known_issues_archive_2026-09-29/card_quality_full_2026-09-27/。 "
        + verdict["notes"]
    ).strip()


def validate_tables(quality, mechanisms):
    assert len(quality) == 2497 and len(mechanisms) == 5024
    by_card = defaultdict(list)
    for row in mechanisms:
        by_card[row["card_id"]].append(row)
    for row in quality:
        children = by_card[row["card_id"]]
        grade = "RED" if any(child["status"] == "RED" for child in children) else (
            "YELLOW" if any(child["status"] == "YELLOW" for child in children) else "GREEN"
        )
        if row["status"] != grade:
            raise ValueError(f"Whole-card/mechanism mismatch: {row['card_id']} {row['status']} {grade}")
        if grade == "GREEN" and (row["tested"] != "yes" or any(child["tested"] != "yes" for child in children)):
            raise ValueError(f"Unverified GREEN mechanism: {row['card_id']}")


def main():
    verify_archive()
    quality_fields, quality = read_csv(HERE / "card_quality.csv")
    mechanism_fields, mechanisms = read_csv(HERE / "card_mechanism.csv")
    issue_fields, issues = read_csv(HERE / "mechanism_issues.csv")
    verdicts = load_verdicts(issues, quality)
    rerun_pass_cases(verdicts)

    for row in quality:
        if row["card_id"] in verdicts:
            sync_quality(row, verdicts[row["card_id"]])
    for row in mechanisms:
        if row["card_id"] in verdicts:
            sync_quality(row, verdicts[row["card_id"]])
    validate_tables(quality, mechanisms)
    quality_by_id = {row["card_id"]: row for row in quality}

    # Older probe and verdict CSVs describe the original failures. The files
    # named *quality.csv are current card views and follow the master table.
    for path in sorted(HERE.glob("*.csv")):
        if path.name in {"card_quality.csv", "card_mechanism.csv", "red_cards.csv"}:
            continue
        if "quality" not in path.stem or "baseline" in path.stem:
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
        counts = by_set[row["set"]]
        for grade in GRADES:
            row[f"quality_{grade.lower()}"] = str(counts[grade])
    write_csv(HERE / "set_inventory.csv", inventory_fields, inventory)

    queue_fields, queue = read_csv(HERE / "mechanism_queue.csv")
    by_mechanism = defaultdict(Counter)
    for row in mechanisms:
        by_mechanism[row["mechanic"]][row["status"]] += 1
    for row in queue:
        counts = by_mechanism[row["mechanism"]]
        for grade in GRADES:
            row[grade.lower()] = str(counts[grade])
    write_csv(HERE / "mechanism_queue.csv", queue_fields, queue)

    for row in issues:
        issue_id = row["issue_id"]
        if issue_id not in ISSUES and issue_id != "DEATH-002":
            continue
        members = (
            [verdicts["ULD_266"]] if issue_id == "DEATH-002" else
            [verdicts[card_id] for card_id in row["confirmed_cards"].split("|")]
        )
        passed = [member for member in members if member["outcome"] == "PASS"]
        if len(passed) == len(members):
            row["severity"] = "resolved_tested"
            if not row["summary"].startswith("修复前问题："):
                row["summary"] = "修复前问题：" + row["summary"]
            row["next_test"] = "确认受影响卡已逐张重测；其他候选卡仍需独立验证。"
        elif passed:
            row["severity"] = "partially_resolved"
            row["next_test"] = "TRL_257 仍将2点伤害打到己方英雄；需单独修正卡牌目标后重测。"
        row["evidence"] = (
            row["evidence"].split("; 当前复测：")[0]
            + "; 当前复测：reports/card_quality_full_2026-09-27/remediation_verdicts_2026-09-29.csv#"
            + issue_id
        )
    write_csv(HERE / "mechanism_issues.csv", issue_fields, issues)
    verify_archive()
    print("Current card grades:", dict(Counter(row["status"] for row in quality)))
    print("Retested cards:", len(verdicts))


if __name__ == "__main__":
    main()
