"""Apply the confirmed Tracking draw-trigger rule to current quality views."""

from collections import Counter, defaultdict

from apply_remediation_results import (
    HERE, read_csv, validate_tables, verify_archive, write_csv,
)


CARD_ID = "DS1_184"


def main():
    verify_archive()
    verdict_fields, verdict_rows = read_csv(HERE / "tracking_rule_verdict_2026-09-29.csv")
    assert len(verdict_rows) == 1 and verdict_rows[0]["card_id"] == CARD_ID
    verdict = verdict_rows[0]
    assert verdict["status"] == "GREEN" and verdict["tested"] == "yes"
    assert verdict_fields == [
        "card_id", "status", "implementation", "tested", "reason", "evidence", "notes",
    ]

    quality_fields, quality = read_csv(HERE / "card_quality.csv")
    mechanism_fields, mechanisms = read_csv(HERE / "card_mechanism.csv")
    assert sum(row["card_id"] == CARD_ID for row in quality) == 1
    assert sum(row["card_id"] == CARD_ID for row in mechanisms) == 2
    for rows in (quality, mechanisms):
        for row in rows:
            if row["card_id"] == CARD_ID:
                for key in ("status", "implementation", "tested", "reason", "evidence", "notes"):
                    row[key] = verdict[key]
    validate_tables(quality, mechanisms)

    for path in HERE.glob("*quality*.csv"):
        if path.name in {"card_quality.csv", "card_mechanism.csv"} or "baseline" in path.stem:
            continue
        fields, rows = read_csv(path)
        if not fields or not {"card_id", "status"} <= set(fields):
            continue
        changed = False
        for row in rows:
            if row["card_id"] == CARD_ID:
                for key in ("status", "implementation", "tested", "reason", "evidence", "notes"):
                    if key in row:
                        row[key] = verdict[key]
                changed = True
        if changed:
            write_csv(path, fields, rows)

    write_csv(HERE / "card_quality.csv", quality_fields, quality)
    write_csv(HERE / "card_mechanism.csv", mechanism_fields, mechanisms)

    inventory_fields, inventory = read_csv(HERE / "set_inventory.csv")
    by_set = defaultdict(Counter)
    for row in quality:
        by_set[row["set"]][row["status"].lower()] += 1
    for row in inventory:
        for grade in ("green", "yellow", "red"):
            row[f"quality_{grade}"] = str(by_set[row["set"]][grade])
    write_csv(HERE / "set_inventory.csv", inventory_fields, inventory)

    queue_fields, queue = read_csv(HERE / "mechanism_queue.csv")
    by_mechanism = defaultdict(Counter)
    for row in mechanisms:
        by_mechanism[row["mechanic"]][row["status"].lower()] += 1
    for row in queue:
        for grade in ("green", "yellow", "red"):
            row[grade] = str(by_mechanism[row["mechanism"]][grade])
    write_csv(HERE / "mechanism_queue.csv", queue_fields, queue)

    verify_archive()
    print("DS1_184 current status: GREEN; archive unchanged")


if __name__ == "__main__":
    main()
