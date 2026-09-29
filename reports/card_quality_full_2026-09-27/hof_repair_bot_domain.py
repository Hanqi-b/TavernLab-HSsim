"""Fixed-seed candidate-domain probe for Gelbin's Repair Bot invention."""

import csv
import logging
from pathlib import Path

from fireplace.logging import log
from hof_gelbin_detail import game_with_invention


HERE = Path(__file__).resolve().parent
PROBE = HERE / "hof_probe.csv"
FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
SEEDS = (3, 7, 13, 14, 20, 22, 24, 26, 28)
TARGET_DAMAGE = {
    "owner_hero": 10,
    "enemy_hero": 8,
    "friendly_yeti": 4,
    "enemy_yeti": 3,
    "repair_bot": 1,
}

for handler in log.handlers:
    handler.setLevel(logging.CRITICAL)
log.setLevel(logging.CRITICAL)


class ConfirmedMismatch(Exception):
    """The card resolved, but its observed behavior contradicted its text."""


def repair_bot_candidate_domain():
    selected_by_seed = {}
    healed_by_seed = {}
    candidate_names = set(TARGET_DAMAGE)

    for seed in SEEDS:
        game, gelbin, bot = game_with_invention(seed, "Mekka2")
        owner = game.player1
        enemy = game.player2
        friendly_yeti = owner.summon("CS2_182")
        enemy_yeti = enemy.summon("CS2_182")
        targets = {
            "owner_hero": owner.hero,
            "enemy_hero": enemy.hero,
            "friendly_yeti": friendly_yeti,
            "enemy_yeti": enemy_yeti,
            "repair_bot": bot,
        }
        for name, target in targets.items():
            target.hit(TARGET_DAMAGE[name])
        before = {name: target.health for name, target in targets.items()}
        gelbin_before = (gelbin.atk, gelbin.health)

        game.end_turn()

        after = {name: target.health for name, target in targets.items()}
        healed = [name for name in targets if after[name] > before[name]]
        if len(healed) != 1:
            raise ConfirmedMismatch(
                f"seed={seed}: expected exactly one damaged target to heal; "
                f"before={before}; after={after}; healed={healed}"
            )
        selected = healed[0]
        expected_restore = min(6, TARGET_DAMAGE[selected])
        actual_restore = after[selected] - before[selected]
        if actual_restore != expected_restore:
            raise ConfirmedMismatch(
                f"seed={seed}: target={selected} restore={actual_restore}, "
                f"expected={expected_restore}; before={before}; after={after}"
            )
        if (gelbin.atk, gelbin.health) != gelbin_before:
            raise ConfirmedMismatch(
                f"seed={seed}: undamaged Gelbin changed from {gelbin_before} "
                f"to {(gelbin.atk, gelbin.health)}"
            )
        selected_by_seed[seed] = selected
        healed_by_seed[seed] = actual_restore

    seen = set(selected_by_seed.values())
    if seen != candidate_names:
        raise ConfirmedMismatch(
            f"candidate domain mismatch: expected={sorted(candidate_names)}; "
            f"seen={sorted(seen)}; outcomes={selected_by_seed}"
        )
    return (
        f"seeds={SEEDS};selected={selected_by_seed};restore={healed_by_seed};"
        f"candidate_coverage={sorted(seen)};undamaged_gelbin_unchanged=true"
    )


def main():
    expected = (
        "Across fixed seeds with five damaged characters (both heroes, both Yetis, "
        "and the Repair Bot), each is individually selected and restored by up to "
        "6 Health; only one character changes per trigger and undamaged Gelbin is excluded."
    )
    try:
        observed = repair_bot_candidate_domain()
        outcome = "pass"
    except ConfirmedMismatch as exc:
        observed = str(exc)
        outcome = "confirmed_error"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"

    row = {
        "card_id": "EX1_112",
        "case_id": "repair_bot_fixed_seed_multiple_damaged_character_domain",
        "expected": expected,
        "observed": observed,
        "outcome": outcome,
        "notes": (
            "Nine fixed seeds independently reach every damaged-character candidate; "
            "the set includes both heroes, friendly/enemy minions, and the Repair Bot itself."
        ),
    }
    with PROBE.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    rows = [r for r in rows if (r["card_id"], r["case_id"]) != (row["card_id"], row["case_id"])]
    rows.append(row)
    with PROBE.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{outcome.upper()} {row['case_id']}: {observed}")


if __name__ == "__main__":
    main()
