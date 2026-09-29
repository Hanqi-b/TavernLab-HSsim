"""Fill traceable per-card notes for completed HOF/NAXX verdict rows."""

import csv
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def write(name, fields, rows):
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    _, master_rows = read("card_master.csv")
    master = {row["card_id"]: row for row in master_rows}
    for verdict_name, probe_name in (("hof_verdict.csv", "hof_probe.csv"),
                                     ("naxx_verdict.csv", "naxx_probe.csv")):
        fields, verdicts = read(verdict_name)
        _, cases = read(probe_name)
        case_counts = Counter(row["card_id"] for row in cases)
        filled = 0
        for verdict in verdicts:
            if verdict["notes"].strip():
                continue
            card = master[verdict["card_id"]]
            verdict["notes"] = (
                f"{case_counts[verdict['card_id']]} 条独立实战行为 case；"
                f"EN/ZH 文案、脚本与已有测试引用见 {probe_name} 对应 notes；"
                f"源码={card['python_source'] or '原生标签/规则引擎'}；"
                f"既有测试={card['test_refs_candidate'] or '无'}；"
                "前次 audit 状态为 YELLOW。"
            )
            filled += 1
        write(verdict_name, fields, verdicts)
        print(verdict_name, "filled_notes", filled, "cards", len(verdicts))


if __name__ == "__main__":
    main()
