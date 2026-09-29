"""Apply targeted Classic red-card retests to current quality views."""

import os
import subprocess
from collections import Counter, defaultdict

from apply_remediation_results import (
    HERE, ROOT, SYNC_COLUMNS, read_csv, validate_tables, verify_archive, write_csv,
)


VERDICT_FILE = HERE / "classic_red_fix_verdicts_2026-09-29.csv"
EXPECTED_IDS = {
    "EX1_080", "EX1_182", "EX1_509", "EX1_560", "EX1_584",
    "NEW1_005", "NEW1_036", "NEW1_004",
}
RESOLVED_ISSUES = {"TRIGGER-002", "RANDOM-001", "SPELLPOWER-001"}


def main():
    verify_archive()
    _, verdict_rows = read_csv(VERDICT_FILE)
    verdicts = {row["card_id"]: row for row in verdict_rows}
    assert len(verdict_rows) == len(EXPECTED_IDS) and set(verdicts) == EXPECTED_IDS
    assert all(
        row["status"] == ("YELLOW" if row["card_id"] == "EX1_560" else "GREEN")
        and row["tested"] == ("partial" if row["card_id"] == "EX1_560" else "yes")
        for row in verdict_rows
    )

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
        if issue_id in RESOLVED_ISSUES:
            assert set(row["confirmed_cards"].split("|")) <= EXPECTED_IDS
            row["severity"] = "resolved_tested"
            if not row["summary"].startswith("修复前问题："):
                row["summary"] = "修复前问题：" + row["summary"]
            row["next_test"] = "确认受影响卡已逐张重测；其他候选卡仍需独立验证。"
        elif issue_id == "TIME-001":
            row["severity"] = "confirmed"
            row["summary"] = (
                "诺兹多姆现能把双方Player.timeout及序列化值改为15，沉默或死亡后恢复75；"
                "但项目尚无按墙钟计时并在时限到达时结束回合的消费者，完整限时效果未验证。"
            )
            row["next_test"] = "实现或明确接入回合计时执行器，再验证15秒自动结束回合及移除光环后的75秒恢复。"
        elif issue_id == "BOUNCE-001":
            assert set(row["confirmed_cards"].split("|")) == {"NEW1_004", "NEW1_005"}
            row["severity"] = "audit_false_positive"
            row["summary"] = (
                "原审计误把卡面‘拥有者’解释为原始创建者。炉石回手按当前控制者进入手牌；"
                "消失和劫持者的偷取后回手状态经逐卡复测正确。"
            )
            row["next_test"] = "通用Bounce保持原实现；其他回手卡仍需按正确规则逐卡验证。"
        else:
            continue
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
