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
        "GREEN": 2494, "YELLOW": 3,
    }
    assert {row["card_id"] for row in quality if row["status"] == "YELLOW"} == {
        "EX1_560", "LOOT_516", "SCH_199",
    }
    for verdict_name in (
        "cast_rule_remaining_yellow_verdicts_2026-09-29.csv",
        "kara_red_fix_verdicts_2026-09-29.csv",
        "gangs_remaining_red_fix_verdicts_2026-09-29.csv",
        "ungoro_red_fix_verdicts_2026-09-29.csv",
        "ungoro_discard_cross_set_verdicts_2026-09-29.csv",
        "icecrown_red_fix_verdicts_2026-09-29.csv",
        "loot_hero_target_cross_set_verdict_2026-09-29.csv",
        "loot_red_fix_verdicts_2026-09-29.csv",
        "gilneas_red_fix_verdicts_2026-09-29.csv",
        "boomsday_red_fix_verdicts_2026-09-29.csv",
        "troll_red_fix_verdicts_2026-09-29.csv",
        "year_of_dragon_red_fix_verdicts_2026-09-29.csv",
        "demon_hunter_initiate_red_fix_verdicts_2026-09-29.csv",
        "scholomance_red_fix_verdicts_2026-09-29.csv",
        "black_temple_red_fix_verdicts_2026-09-29.csv",
        "dalaran_red_fix_verdicts_2026-09-29.csv",
        "uldum_red_fix_verdicts_2026-09-29.csv",
        "dragons_red_fix_verdicts_2026-09-29.csv",
    ):
        _, current_verdicts = read_csv(HERE / verdict_name)
        for verdict in current_verdicts:
            card = by_id[verdict["card_id"]]
            if verdict["card_id"] == "SCH_199":
                assert card["status"] == verdict["status"] == "YELLOW"
                assert card["tested"] == verdict["tested"] == "partial"
            else:
                assert card["status"] == verdict["status"] == "GREEN"
                assert card["tested"] == verdict["tested"] == "yes"
            assert card["reason"] == verdict["reason"]
            for node in verdict["test_nodes"].split("|"):
                assert node in card["evidence"]
                assert (ROOT / node.split("::", 1)[0]).is_file()
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
        assert card["status"] == verdict["status"] and card["tested"] == verdict["tested"]
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    _, cast_verdicts = read_csv(HERE / "classic_cast_rule_verdict_2026-09-29.csv")
    assert {row["card_id"] for row in cast_verdicts} == {"EX1_095", "EX1_187", "EX1_559"}
    assert issue_status["CAST-001"] == "rule_confirmed_tested"
    for verdict in cast_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == "GREEN" and card["tested"] == "yes"
        assert card["reason"] == verdict["reason"]
        assert card["evidence"] == verdict["evidence"]
        assert (ROOT / verdict["evidence"].split("::", 1)[0]).is_file()
    _, loe_cast_verdicts = read_csv(HERE / "loe_cast_rule_verdict_2026-09-29.csv")
    assert len(loe_cast_verdicts) == 1 and loe_cast_verdicts[0]["card_id"] == "LOE_086"
    loe_verdict = loe_cast_verdicts[0]
    loe_card = by_id["LOE_086"]
    assert loe_card["status"] == loe_verdict["status"] == "GREEN"
    assert loe_card["tested"] == loe_verdict["tested"] == "yes"
    assert loe_card["reason"] == loe_verdict["reason"]
    assert loe_card["evidence"] == loe_verdict["evidence"]
    for node in loe_verdict["evidence"].split("|"):
        assert (ROOT / node.split("::", 1)[0]).is_file()
    _, og_blade_verdicts = read_csv(HERE / "og_blade_current_health_verdict_2026-09-29.csv")
    assert len(og_blade_verdicts) == 1 and og_blade_verdicts[0]["card_id"] == "OG_282"
    og_verdict = og_blade_verdicts[0]
    og_card = by_id["OG_282"]
    assert og_card["status"] == og_verdict["status"] == "GREEN"
    assert og_card["tested"] == og_verdict["tested"] == "yes"
    assert og_card["reason"] == og_verdict["reason"]
    assert og_card["evidence"] == og_verdict["evidence"]
    for node in og_verdict["evidence"].split("|"):
        assert (ROOT / node.split("::", 1)[0]).is_file()
    _, classic_red_verdicts = read_csv(HERE / "classic_red_fix_verdicts_2026-09-29.csv")
    assert {row["card_id"] for row in classic_red_verdicts} == {
        "EX1_080", "EX1_182", "EX1_509", "EX1_560", "EX1_584",
        "NEW1_005", "NEW1_036", "NEW1_004",
    }
    for verdict in classic_red_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == verdict["status"] and card["tested"] == verdict["tested"]
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert all(issue_status[issue_id] == "resolved_tested" for issue_id in (
        "TRIGGER-002", "RANDOM-001", "SPELLPOWER-001",
    ))
    assert issue_status["TIME-001"] == "confirmed"
    assert issue_status["BOUNCE-001"] == "audit_false_positive"
    _, naxx_hof_verdicts = read_csv(HERE / "naxx_hof_draw_fix_verdicts_2026-09-29.csv")
    assert {row["card_id"] for row in naxx_hof_verdicts} == {
        "EX1_050", "EX1_085", "EX1_161", "FP1_016", "FP1_025", "FP1_029", "OG_338",
    }
    for verdict in naxx_hof_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == verdict["status"] == "GREEN"
        assert card["tested"] == verdict["tested"] == "yes"
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert all(issue_status[issue_id] == "resolved_tested" for issue_id in (
        "DRAW-001", "BOARD-003", "CONTROL-001",
    ))
    _, gvg_verdicts = read_csv(HERE / "gvg_red_fix_verdicts_2026-09-29.csv")
    assert {row["card_id"] for row in gvg_verdicts} == {
        "GVG_022", "GVG_046", "GVG_048", "GVG_054", "GVG_087", "GVG_113",
        "AT_067", "LOOT_078",
    }
    for verdict in gvg_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == verdict["status"] == "GREEN"
        assert card["tested"] == verdict["tested"] == "yes"
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert all(issue_status[issue_id] == "resolved_tested" for issue_id in (
        "CLEAVE-001", "FORGETFUL-001", "HEROPOWER-002",
    ))
    _, brm_tgt_verdicts = read_csv(HERE / "brm_tgt_red_fix_verdicts_2026-09-29.csv")
    assert {row["card_id"] for row in brm_tgt_verdicts} == {
        "BRM_002", "BRM_029", "AT_008", "AT_049", "AT_069", "AT_090", "AT_109",
    }
    for verdict in brm_tgt_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == verdict["status"] == "GREEN"
        assert card["tested"] == verdict["tested"] == "yes"
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert all(issue_status[issue_id] == "resolved_tested" for issue_id in (
        "RANDOM-002", "READY-001", "ATTACK-001",
    ))
    _, og_red_verdicts = read_csv(HERE / "og_red_fix_verdicts_2026-09-29.csv")
    assert {row["card_id"] for row in og_red_verdicts} == {
        "OG_087", "OG_121", "OG_134", "OG_149", "OG_188", "OG_291", "BT_753",
    }
    for verdict in og_red_verdicts:
        card = by_id[verdict["card_id"]]
        assert card["status"] == verdict["status"] == "GREEN"
        assert card["tested"] == verdict["tested"] == "yes"
        assert card["reason"] == verdict["reason"]
        for node in verdict["test_nodes"].split("|"):
            assert node in card["evidence"]
            assert (ROOT / node.split("::", 1)[0]).is_file()
    assert issue_status["TRIGGER-001"] == "resolved_tested"
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
                or row["card_id"] in {v["card_id"] for v in cast_verdicts}
                or row["card_id"] in {v["card_id"] for v in classic_red_verdicts}
                or row["card_id"] in {v["card_id"] for v in naxx_hof_verdicts}
                or row["card_id"] in {v["card_id"] for v in gvg_verdicts}
                or row["card_id"] in {v["card_id"] for v in brm_tgt_verdicts}
                or row["card_id"] == "LOE_086"
                or row["card_id"] == "OG_282"
                or row["card_id"] in {v["card_id"] for v in og_red_verdicts}
            ):
                assert row["status"] == by_id[row["card_id"]]["status"], path
    print("Verified: archive unchanged; 30 earlier, 6 Basic-fix, 3 Classic CAST-001, 1 LOE CAST-001, 1 OG current-Health, 8 Classic/HOF, 7 NAXX/HOF/OG, 8 GVG/cleave, 7 BRM/TGT and 7 OG/Mana Burn verdicts; 2497 active cards; 24 sets; derived CSVs consistent")


if __name__ == "__main__":
    main()
