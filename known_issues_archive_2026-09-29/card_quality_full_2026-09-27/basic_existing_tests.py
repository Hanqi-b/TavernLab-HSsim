"""Run reviewed Basic card-effect tests and record a reproducible evidence index."""

import csv
import os
import re
import subprocess
import sys
from pathlib import Path

from report_snapshot import source_snapshot


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# The coverage grade reflects inspection of the assertions, not merely a
# passing test name. Partial tests stay YELLOW unless other evidence closes the gap.
CASES = [
    ("CS2_011", "Spell resolution", "tests/test_classic.py::test_savage_roar", "full_candidate"),
    ("CS2_064", "Battlecry", "tests/test_classic.py::test_dread_infernal", "full_candidate"),
    ("CS2_074", "Spell resolution", "tests/test_classic.py::test_deadly_poison", "full_candidate"),
    ("CS2_084", "Spell resolution|Targeting", "tests/test_classic.py::test_hunters_mark", "full_candidate"),
    ("CS2_105", "Spell resolution", "tests/test_classic.py::test_heroic_strike", "full_candidate"),
    ("CS2_122", "Aura|Continuous effect / Update", "tests/test_classic.py::test_raid_leader", "full_candidate"),
    ("CS2_222", "Aura|Continuous effect / Update", "tests/test_classic.py::test_stormwind_champion", "full_candidate"),
    ("DS1_070", "Battlecry|Targeting", "tests/test_classic.py::test_houndmaster", "full_candidate"),
    ("DS1_175", "Aura|Continuous effect / Update", "tests/test_mechanics.py::test_auras", "full_candidate"),
    ("EX1_019", "Battlecry|Targeting", "tests/test_classic.py::test_shattered_sun_cleric", "full_candidate"),
    ("CS2_013", "Spell resolution", "tests/test_classic.py::test_wild_growth", "full_candidate"),
    ("CS2_039", "Spell resolution|Targeting", "tests/test_mechanics.py::test_windfury", "full_candidate"),
    ("CS2_041", "Spell resolution|Targeting", "tests/test_classic.py::test_ancestral_healing", "full_candidate"),
    ("CS2_087", "Spell resolution|Targeting", "tests/test_mechanics.py::test_silence_multiple_buffs", "full_candidate"),
    ("CS2_012", "Spell resolution|Targeting", "tests/test_classic.py::test_knife_juggler_swipe", "partial"),
    ("CS2_097", "Trigger|Weapon", "tests/test_classic.py::test_truesilver_champion", "partial"),
    ("CS2_226", "Battlecry", "tests/test_classic.py::test_frostwolf_warlord", "partial"),
    ("EX1_565", "Aura|Continuous effect / Update", "tests/test_mechanics.py::test_positioning", "partial"),
]


def main():
    nodes = list(dict.fromkeys(case[2] for case in CASES))
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = "tests:."
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--disable-warnings",
                             "--tb=short", *nodes], cwd=ROOT, env=env,
                            capture_output=True, text=True, check=False)
    summary = (result.stdout + "\n" + result.stderr).strip().splitlines()[-1]
    all_pass = result.returncode == 0 and re.search(rf"\b{len(nodes)} passed\b", summary)
    digest, _, _ = source_snapshot()
    rows = [dict(card_id=cid, mechanic=mechanic, test_node=node, coverage_level=coverage,
                 outcome="pass" if all_pass else "test_failed", pytest_summary=summary,
                 source_sha256=digest)
            for cid, mechanic, node, coverage in CASES]
    with (HERE / "basic_existing_tests.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(summary, f"reviewed_cards={len(rows)}", f"full_candidates={sum(r['coverage_level'] == 'full_candidate' for r in rows)}")
    if not all_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
