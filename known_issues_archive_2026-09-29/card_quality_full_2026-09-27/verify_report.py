"""Check audit CSV population, status consistency, and evidence carryover."""

import csv
from collections import Counter, defaultdict
from pathlib import Path

from report_snapshot import source_snapshot


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "card_quality_2026-09-27/deathrattle_quality_map.csv"


def rows(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def main():
    digest, source_count, latest_source_mtime = source_snapshot()
    snapshot = rows("code_snapshot.csv")
    assert len(snapshot) == 1
    assert snapshot[0]["source_sha256"] == digest
    assert int(snapshot[0]["source_files"]) == source_count
    evidence_paths = [OLD, HERE / "collectible_play_smoke.json"] + [
        HERE / name for name in (
            "foundation_probes.csv", "overload_reproductions.csv", "targeting_prereq_sweep.csv",
            "later_stage_probes.csv", "cross_player_draw_probe.csv", "dormant_full_board_probe.csv",
            "discover_pool_probe.csv", "castspell_trigger_probe.csv", "conditional_stats_probe.csv",
            "mode_ongoing_probe.csv", "infectious_sporeling_probe.csv", "basic_corruption_probe.csv",
            "basic_runtime_probe.csv", "vanilla_runtime_probe.csv", "basic_existing_tests.csv", "basic_power_infusion_probe.csv",
            "targeted_reproductions.csv", "hero_power_reproductions.csv", "og_death_selector_probe.csv",
        )
    ]
    assert all(path.stat().st_mtime_ns >= latest_source_mtime for path in evidence_paths), "evidence predates current card/engine source"
    for stem in ("foundation_probes", "targeting_prereq_sweep", "later_stage_probes",
                 "cross_player_draw_probe", "dormant_full_board_probe", "discover_pool_probe",
                 "castspell_trigger_probe", "conditional_stats_probe", "mode_ongoing_probe",
                 "infectious_sporeling_probe", "basic_corruption_probe", "basic_runtime_probe", "vanilla_runtime_probe",
                 "basic_existing_tests", "basic_power_infusion_probe", "og_death_selector_probe"):
        assert (HERE / f"{stem}.csv").stat().st_mtime_ns >= (HERE / f"{stem}.py").stat().st_mtime_ns, stem
    assert (HERE / "basic_existing_tests.csv").stat().st_mtime_ns >= max(
        (HERE.parents[1] / path).stat().st_mtime_ns
        for path in ("tests/test_classic.py", "tests/test_mechanics.py"))
    master = rows("card_master.csv")
    quality = rows("card_quality.csv")
    basic_quality = rows("basic_quality.csv")
    mechanisms = rows("card_mechanism.csv")
    inventory = rows("set_inventory.csv")
    smoke = rows("runtime_smoke.csv")
    with OLD.open(encoding="utf-8-sig", newline="") as file:
        prior = list(csv.DictReader(file))
    assert len(master) == len(quality) == len(smoke) == 2497
    assert len({r["card_id"] for r in master}) == len(master)
    assert len({r["card_id"] for r in quality}) == len(quality)
    assert len(inventory) == 24
    assert sum(int(r["ordinary_collectible"]) for r in inventory) == 2497
    assert all(r["scope"] == "ordinary_collectible" and r["collectible"] == "yes"
               for r in master + quality + mechanisms + smoke)
    assert {r["card_id"] for r in quality} == {r["card_id"] for r in master}
    assert len(basic_quality) == 143
    assert basic_quality == [r for r in quality if r["set"].endswith("(BASIC)")]
    assert not ({f"HERO_{number:02d}" for number in range(1, 11)} &
                {r["card_id"] for r in quality})
    assert {r["status"] for r in quality + mechanisms} <= {"GREEN", "YELLOW", "RED"}
    assert len(mechanisms) == len({(r["card_id"], r["mechanic"]) for r in mechanisms})
    count = Counter(r["card_id"] for r in mechanisms)
    assert set(count) == {r["card_id"] for r in quality}
    by_card = defaultdict(list)
    for row in mechanisms:
        by_card[row["card_id"]].append(row)
    for row in quality:
        assert row["reason"] and row["evidence"] and count[row["card_id"]] > 0
        child = by_card[row["card_id"]]
        expected = "RED" if any(r["status"] == "RED" for r in child) else "YELLOW" if any(r["status"] == "YELLOW" for r in child) else "GREEN"
        assert row["status"] == expected, row["card_id"]
        if row["status"] == "GREEN":
            assert row["tested"] == "yes" and all(r["tested"] == "yes" for r in child)
    current = {(r["card_id"], r["mechanic"]): r for r in mechanisms}
    expansion_retested = ({r["card_id"] for r in rows("expansion_yellow_baseline.csv")}
                          | {r["card_id"] for r in rows("four_set_yellow_baseline.csv")}
                          | {r["card_id"] for r in rows("og_yellow_baseline.csv")}
                          | {r["card_id"] for r in rows("three_set_yellow_baseline.csv")}
                          | {r["card_id"] for r in rows("icecrown_yellow_baseline.csv")})
    for verdict_path in sorted(HERE.glob("set_verdict_*.csv")):
        with verdict_path.open(encoding="utf-8-sig", newline="") as stream:
            expansion_retested.update(row["card_id"] for row in csv.DictReader(stream))
    residual_verdict_path = HERE / "residual_verdict.csv"
    residual_verdicts = rows("residual_verdict.csv") if residual_verdict_path.exists() else []
    refined_ids = ({row["card_id"] for row in residual_verdicts}
                   if len(residual_verdicts) == 25 else set())
    expansion_retested.update(refined_ids)
    for old in prior:
        key = (old["card_id"], "Deathrattle")
        if key in current and old["card_id"] not in expansion_retested:
            row = current[key]
            assert row["status"] == old["status"] and row["tested"] == old["tested"]
    status = {r["card_id"]: r["status"] for r in quality}
    assert all(status[cid] == "RED" for cid in ("BT_427", "BT_753", "BT_801", "BT_731", "EX1_194", "YOD_008",
                                                 "YOD_016", "EX1_050", "EX1_136", "DRG_058",
                                                 "DRG_088", "ICC_841", "GIL_819", "ICC_900"))
    assert status["AT_003"] == "GREEN"
    assert status["CS2_022"] == "GREEN" and status["EX1_049"] == "GREEN"
    assert status["NEW1_012"] == "GREEN" and status["EX1_287"] == "GREEN"
    assert status["CS2_063"] == "GREEN"
    death_zone = {r["card_id"]: r for r in rows("og_death_selector_probe.csv")}
    assert {cid: row["outcome"] for cid, row in death_zone.items()} == {
        "GIL_819": "confirmed_error", "ICC_900": "confirmed_error", "EX1_595": "pass"
    }
    if "EX1_559" not in expansion_retested:
        assert status["EX1_559"] == "YELLOW"
    assert len(rows("targeting_static_audit.csv")) == 3
    foundation = rows("foundation_probes.csv")
    assert len(foundation) == 16
    assert Counter(r["outcome"] for r in foundation) == {"pass": 8, "confirmed_error": 8}
    sweep = rows("targeting_prereq_sweep.csv")
    assert len(sweep) == 425
    assert Counter(r["outcome"] for r in sweep) == {"rejected_no_target": 342, "condition_not_met": 72, "choice_required_first": 11}
    assert all(r["invalid_self_outcome"] == "rejected" for r in sweep if r["outcome"] == "rejected_no_target")
    assert len(rows("red_cards.csv")) == sum(r["status"] == "RED" for r in quality)
    queue = rows("mechanism_queue.csv")
    assert sum(int(r["candidate_entities"]) for r in queue) == len(mechanisms)
    assert sum(int(r["green"]) + int(r["yellow"]) + int(r["red"]) for r in queue) == len(mechanisms)
    overload = rows("overload_reproductions.csv")
    assert len(overload) == 35 and all(r["outcome"] == "pass" for r in overload)
    # An audited card's overall conservative verdict is copied to each of its
    # mechanism rows. A card can remain YELLOW for a different effect even
    # when its separate Overload reproduction passed.
    assert all(current[(r["card_id"], "Overload")]["status"] ==
               (status[r["card_id"]] if r["card_id"] in expansion_retested else "GREEN")
               for r in overload)
    effects = rows("later_stage_probes.csv")
    assert len(effects) == 24 == len({r["case_id"] for r in effects})
    assert all(r["outcome"] == "pass" for r in effects)
    assert rows("cross_player_draw_probe.csv")[0]["outcome"] == "confirmed_error"
    assert rows("dormant_full_board_probe.csv")[0]["outcome"] == "confirmed_error"
    assert rows("discover_pool_probe.csv")[0]["outcome"] == "confirmed_error"
    assert len(rows("castspell_trigger_probe.csv")) == 3
    assert all(r["outcome"] == "inconclusive" for r in rows("castspell_trigger_probe.csv"))
    stats = rows("conditional_stats_probe.csv")
    assert len(stats) == 10 and Counter(r["outcome"] for r in stats) == {"confirmed_error": 9, "pass": 1}
    assert len(rows("mode_ongoing_probe.csv")) == 3
    assert all(r["outcome"] == "confirmed_error" for r in rows("mode_ongoing_probe.csv"))
    spores = {r["case_id"]: r for r in rows("infectious_sporeling_probe.csv")}
    assert spores["SPORE-01"]["outcome"] == "pass"
    assert spores["SPORE-02"]["outcome"] == "confirmed_error"
    assert rows("basic_corruption_probe.csv")[0]["outcome"] == "pass"
    assert rows("basic_power_infusion_probe.csv")[0]["outcome"] == "confirmed_error"
    basic_runtime = rows("basic_runtime_probe.csv")
    assert len(basic_runtime) == 61 and all(r["outcome"] == "PASS" for r in basic_runtime)
    assert sum(r["case_id"].startswith("entry_") for r in basic_runtime) == 28
    assert all(status[r["card_id"]] == "GREEN" for r in basic_runtime
               if r["case_id"].startswith("entry_") and r["card_id"] != "CS2_142")
    assert status["CS2_142"] == "RED", "independent Silence probe shows native Spell Damage persists after silence"
    assert status["EX1_332"] == "RED", "the Silence spell itself does not remove native Spell Damage"
    vanilla = rows("vanilla_runtime_probe.csv")
    plain_ids = {r["card_id"] for r in mechanisms
                 if r["mechanic"] == "Vanilla" and not r["card_text_en"].strip()}
    assert len(vanilla) == len(plain_ids) == 32
    assert {r["card_id"] for r in vanilla} == plain_ids
    assert all(r["outcome"] == "PASS" and status[r["card_id"]] == "GREEN" for r in vanilla)
    basic_tests = rows("basic_existing_tests.csv")
    assert len(basic_tests) == 18 and all(r["outcome"] == "pass" for r in basic_tests)
    assert sum(r["coverage_level"] == "full_candidate" for r in basic_tests) == 14
    assert all(r["source_sha256"] == digest for r in basic_tests)
    card_verdicts = rows("basic_card_verdicts.csv")
    assert len(card_verdicts) == 83, "every Basic card that began this pass YELLOW needs an individual verdict"
    assert len(card_verdicts) == len({r["card_id"] for r in card_verdicts})
    quality_by_id = {r["card_id"]: r for r in quality}
    for verdict in card_verdicts:
        cid, state = verdict["card_id"], verdict["status"]
        if cid in refined_ids:
            # A later targeted audit supersedes this earlier Basic verdict.
            continue
        assert quality_by_id[cid]["set"].endswith("(BASIC)")
        assert state in {"GREEN", "RED", "YELLOW"} and status[cid] == state
        assert quality_by_id[cid]["reason"] == verdict["reason"]
        scope = set(verdict["mechanic_scope"].split("|"))
        actual = {r["mechanic"] for r in by_card[cid]}
        assert scope and scope <= actual
        if state == "GREEN":
            assert scope == actual
        probe_name = verdict["probe_file"]
        assert probe_name.startswith("basic_card_probe_") and probe_name.endswith(".csv")
        probe_file = HERE / probe_name
        probe_script = probe_file.with_suffix(".py")
        assert probe_file.stat().st_mtime_ns >= max(probe_script.stat().st_mtime_ns, latest_source_mtime)
        cases = [r for r in rows(probe_name) if r["card_id"] == cid]
        assert cases and len({r["case_id"] for r in cases}) == len(cases)
        assert all(f"{probe_name}#{r['case_id']}" in quality_by_id[cid]["evidence"] for r in cases)
        if state == "GREEN":
            assert all(r["outcome"] == "pass" for r in cases)
        elif state == "RED":
            assert any(r["outcome"] == "confirmed_error" for r in cases)
        else:
            assert verdict["reason"] and verdict["notes"]
    issue_ids = {r["issue_id"] for r in rows("mechanism_issues.csv")}
    assert {"DRAW-001", "BOARD-001", "BOARD-002", "BOARD-003", "BOUNCE-001", "CONTROL-001", "RANDOM-001", "TIME-001", "TRIGGER-002", "SPELLPOWER-001", "SILENCE-001",
            "DISCOVER-001", "STATS-001", "MODE-001", "TARGET-004"} <= issue_ids
    assert next(r for r in rows("mechanism_issues.csv") if r["issue_id"] == "CAST-001")["severity"] == "semantics_pending"
    sweep_sets = rows("set_sweep.csv")
    matrix = rows("set_mechanism_matrix.csv")
    assert len(sweep_sets) == len(inventory) == 24
    assert all(r["coverage_reconciled"] == "yes" for r in sweep_sets)
    assert sum(int(r["applicable_entities"]) for r in sweep_sets) == len(quality)
    assert sum(int(r["mechanism_rows"]) for r in sweep_sets) == len(mechanisms)
    assert sum(int(r["smoke_played"]) + int(r["smoke_not_playable"]) + int(r["smoke_exception"])
               for r in sweep_sets) == len(smoke)
    assert all(int(r["smoke_played"]) + int(r["smoke_not_playable"]) + int(r["smoke_exception"])
               == int(r["ordinary_collectible"]) for r in sweep_sets)
    assert sum(int(r["candidate_entities"]) for r in matrix) == len(mechanisms)
    assert {(r["set"], r["mechanism"]) for r in matrix} == {(r["set"], r["mechanic"]) for r in mechanisms}
    print("verified", len(master), "master;", len(quality), "quality;", len(mechanisms), "mechanism;", len(smoke), "smoke")
    print("quality", dict(Counter(r["status"] for r in quality)))


if __name__ == "__main__":
    main()
