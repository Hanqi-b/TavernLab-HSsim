"""Apply the confirmed current-Health rule to Blade of C'Thun."""

import os
import subprocess
from collections import Counter, defaultdict

from apply_remediation_results import (
    HERE, ROOT, SYNC_COLUMNS, read_csv, validate_tables, verify_archive, write_csv,
)


CARD_IDS = {"OG_282"}
VERDICT_FILE = HERE / "og_blade_current_health_verdict_2026-09-29.csv"


def main():
    verify_archive()
    _, verdict_rows = read_csv(VERDICT_FILE)
    verdicts = {row["card_id"]: row for row in verdict_rows}
    assert len(verdict_rows) == len(CARD_IDS) and set(verdicts) == CARD_IDS
    assert all(row["status"] == "GREEN" and row["tested"] == "yes" for row in verdict_rows)

    nodes = sorted(node for row in verdict_rows for node in row["evidence"].split("|"))
    assert all((ROOT / node.split("::", 1)[0]).is_file() for node in nodes)
    environment = os.environ.copy()
    environment.update(PYTHONPATH="tests:.", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    subprocess.run(
        [str(ROOT / "venv/bin/python"), "-m", "pytest", "-q", "--show-capture=no", *nodes],
        cwd=ROOT, env=environment, check=True,
    )

    quality_fields, quality = read_csv(HERE / "card_quality.csv")
    mechanism_fields, mechanisms = read_csv(HERE / "card_mechanism.csv")
    assert {row["card_id"] for row in quality if row["card_id"] in CARD_IDS} == CARD_IDS
    for rows in (quality, mechanisms):
        for row in rows:
            verdict = verdicts.get(row["card_id"])
            if verdict:
                for column in SYNC_COLUMNS:
                    row[column] = verdict[column]
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
            if source and row["card_id"] in CARD_IDS:
                for column in SYNC_COLUMNS:
                    if column in row:
                        row[column] = source[column]
                touched = True
        if touched:
            write_csv(path, fields, rows)

    write_csv(HERE / "card_quality.csv", quality_fields, quality)
    write_csv(HERE / "card_mechanism.csv", mechanism_fields, mechanisms)

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
    print("Current card grades:", dict(Counter(row["status"] for row in quality)))


if __name__ == "__main__":
    main()
