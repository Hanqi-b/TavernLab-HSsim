"""Verify active card-quality CSVs after remediation without rewriting them."""

import csv
from collections import Counter, defaultdict
from pathlib import Path

from apply_remediation_results import HERE, ROOT, read_csv, validate_tables, verify_archive


def main():
    verify_archive()
    _, quality = read_csv(HERE / "card_quality.csv")
    _, mechanisms = read_csv(HERE / "card_mechanism.csv")
    _, verdicts = read_csv(HERE / "remediation_verdicts_2026-09-29.csv")
    _, red = read_csv(HERE / "red_cards.csv")
    _, inventory = read_csv(HERE / "set_inventory.csv")
    _, queue = read_csv(HERE / "mechanism_queue.csv")
    _, issues = read_csv(HERE / "mechanism_issues.csv")

    validate_tables(quality, mechanisms)
    by_id = {row["card_id"]: row for row in quality}
    assert len(by_id) == len(quality) == 2497
    assert len(verdicts) == len({row["card_id"] for row in verdicts}) == 30
    assert Counter(row["status"] for row in verdicts) == {"GREEN": 30}
    assert Counter(row["status"] for row in quality) == {
        "GREEN": 2311, "YELLOW": 8, "RED": 178,
    }
    for verdict in verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == verdict["status"]
        assert card["reason"] == verdict["reason"]
        assert card["tested"] == verdict["tested"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert {row["card_id"] for row in red} == {
        row["card_id"] for row in quality if row["status"] == "RED"
    }

    by_set = defaultdict(Counter)
    for row in quality:
        by_set[row["set"]][row["status"].lower()] += 1
    assert len(inventory) == len(by_set) == 24
    for row in inventory:
        counts = by_set[row["set"]]
        assert sum(counts.values()) == int(row["ordinary_collectible"])
        for grade in ("green", "yellow", "red"):
            assert counts[grade] == int(row[f"quality_{grade}"])

    by_mechanism = defaultdict(Counter)
    for row in mechanisms:
        by_mechanism[row["mechanic"]][row["status"].lower()] += 1
    for row in queue:
        counts = by_mechanism[row["mechanism"]]
        for grade in ("green", "yellow", "red"):
            assert counts[grade] == int(row[grade])

    issue_status = {row["issue_id"]: row["severity"] for row in issues}
    assert all(issue_status[issue_id] == "resolved_tested" for issue_id in (
        "DEATH-001", "DEATH-002", "DEATH-004", "BOARD-001", "BOARD-002",
        "SILENCE-001",
    ))
    _, basic_fix_verdicts = read_csv(HERE / "basic_red_fix_verdicts_2026-09-29.csv")
    assert len(basic_fix_verdicts) == 6
    for verdict in basic_fix_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == "GREEN" and card["tested"] == "yes"
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert by_id["TRL_257"]["status"] == "GREEN"
    assert by_id["DS1_184"]["status"] == "GREEN"
    _, tracking_verdicts = read_csv(HERE / "tracking_rule_verdict_2026-09-29.csv")
    assert len(tracking_verdicts) == 1
    assert tracking_verdicts[0]["card_id"] == "DS1_184"
    assert tracking_verdicts[0]["reason"] == by_id["DS1_184"]["reason"]

    for path in HERE.glob("*quality*.csv"):
        if path.name in {"card_quality.csv", "card_mechanism.csv"} or "baseline" in path.stem:
            continue
        fields, rows = read_csv(path)
        if not fields or not {"card_id", "status"} <= set(fields):
            continue
        for row in rows:
            if row["card_id"] in by_id and (
                row["card_id"] == "DS1_184"
                or row["card_id"] in {v["card_id"] for v in verdicts}
                or row["card_id"] in {v["card_id"] for v in basic_fix_verdicts}
            ):
                assert row["status"] == by_id[row["card_id"]]["status"], path
    print("Verified: archive unchanged; 30 earlier and 6 new verdicts; 2497 active cards; 24 sets; derived CSVs consistent")


if __name__ == "__main__":
    main()
