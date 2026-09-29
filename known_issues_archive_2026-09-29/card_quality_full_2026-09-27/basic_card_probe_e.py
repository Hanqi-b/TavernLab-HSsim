"""Card-specific Basic behavior probes: CS2_093, CS2_094, CS2_103, CS2_108, CS2_114."""

import csv
from pathlib import Path

from hearthstone.enums import Zone
from fireplace.exceptions import InvalidAction

from basic_runtime_probe import new_game


OUT = Path(__file__).with_suffix(".csv")
FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
ROWS = []


def run(card_id, case_id, expected, probe, notes):
    try:
        observed = probe()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "confirmed_error"
    ROWS.append(dict(card_id=card_id, case_id=case_id, expected=expected,
                     observed=observed, outcome=outcome, notes=notes))


def consecration_enemy_scope():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    spell = owner.give("CS2_093")
    spell.play()
    observed = (friendly.health, enemy.health, owner.hero.health,
                opponent.hero.health, spell.zone)
    assert observed == (5, 3, 30, 28, Zone.GRAVEYARD), observed
    return f"friendly={friendly.health};enemy={enemy.health};heroes={owner.hero.health}/{opponent.hero.health};spell={spell.zone.name}"


def hammer_damage_and_draw():
    game = new_game()
    owner, opponent = game.player1, game.player2
    owner.discard_hand()
    seeded = owner.give("CS2_231")
    seeded.shuffle_into_deck()
    target = opponent.summon("CS2_182")
    spell = owner.give("CS2_094")
    assert target in spell.targets, "enemy minion should be a legal target"
    spell.play(target=target)
    observed = (target.health, seeded.zone, seeded in owner.hand,
                len(owner.deck), spell.zone)
    assert observed == (2, Zone.HAND, True, 0, Zone.GRAVEYARD), observed
    return f"target_health={target.health};drawn={seeded.id}:{seeded.zone.name};deck={len(owner.deck)};spell={spell.zone.name}"


def hammer_hero_target():
    game = new_game()
    owner, opponent = game.player1, game.player2
    owner.discard_hand()
    seeded = owner.give("CS2_231")
    seeded.shuffle_into_deck()
    spell = owner.give("CS2_094")
    assert opponent.hero in spell.targets, "enemy hero should be a legal target"
    spell.play(target=opponent.hero)
    observed = (opponent.hero.health, seeded in owner.hand, len(owner.deck))
    assert observed == (27, True, 0), observed
    return f"enemy_hero={opponent.hero.health};drawn={seeded in owner.hand};deck={len(owner.deck)}"


def hammer_friendly_target():
    game = new_game()
    owner, opponent = game.player1, game.player2
    owner.discard_hand()
    seeded = owner.give("CS2_231")
    seeded.shuffle_into_deck()
    friendly = owner.summon("CS2_182")
    spell = owner.give("CS2_094")
    assert friendly in spell.targets, "friendly minion should be a legal target"
    spell.play(target=friendly)
    observed = (friendly.health, opponent.hero.health, seeded in owner.hand,
                len(owner.deck), spell.zone)
    assert observed == (2, 30, True, 0, Zone.GRAVEYARD), observed
    return f"friendly_health={friendly.health};enemy_hero={opponent.hero.health};drawn={seeded in owner.hand};deck={len(owner.deck)}"


def charge_attack_restriction():
    game = new_game()
    owner, opponent = game.player1, game.player2
    charger = owner.give("CS2_231")
    charger.play()
    defender = opponent.summon("CS2_182")
    spell = owner.give("CS2_103")
    assert charger in spell.targets and defender not in spell.targets
    spell.play(target=charger)
    before = (charger.charge, charger.can_attack(defender),
              charger.can_attack(opponent.hero), charger.cannot_attack_heroes)
    assert before == (True, True, False, True), before
    charger.attack(defender)
    after = (defender.health, charger.zone, spell.zone)
    assert after == (4, Zone.GRAVEYARD, Zone.GRAVEYARD), after
    return f"before={before};after={after}"


def charge_next_turn_expiry():
    game = new_game()
    owner, opponent = game.player1, game.player2
    charger = owner.give("CS2_182")
    charger.play()
    owner.give("CS2_103").play(target=charger)
    assert charger.cannot_attack_heroes
    game.end_turn()
    game.end_turn()
    observed = (charger.charge, charger.cannot_attack_heroes,
                charger.can_attack(opponent.hero), charger.zone)
    assert observed == (True, False, True, Zone.PLAY), observed
    return f"charge={charger.charge};cannot_attack_heroes={charger.cannot_attack_heroes};hero_legal={charger.can_attack(opponent.hero)}"


def execute_target_limits():
    game = new_game()
    owner, opponent = game.player1, game.player2
    undamaged = opponent.summon("CS2_182")
    friendly = owner.summon("CS2_182")
    spell = owner.give("CS2_108")
    before = (spell.zone, owner.mana)
    assert undamaged not in spell.targets and friendly not in spell.targets
    owner.give("CS2_008").play(target=undamaged)
    assert undamaged.health == 4
    owner.give("CS2_008").play(target=friendly)
    assert friendly.health == 4
    assert undamaged in spell.targets and friendly not in spell.targets
    before_rejection = (spell.zone, owner.mana, friendly.health, undamaged.health)
    try:
        spell.play(target=friendly)
    except InvalidAction:
        pass
    else:
        raise AssertionError("Execute accepted a damaged friendly minion")
    assert (spell.zone, owner.mana, friendly.health, undamaged.health) == before_rejection
    observed = (before, undamaged.health, spell.zone)
    assert spell.zone == Zone.HAND, observed
    return f"initial_zone={before[0].name};damaged_target_health={undamaged.health};target_legal={undamaged in spell.targets};friendly_legal={friendly in spell.targets}"


def execute_destroys_damaged_enemy():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    survivor = opponent.summon("CS2_182")
    owner.give("CS2_008").play(target=target)
    spell = owner.give("CS2_108")
    spell.play(target=target)
    observed = (target.zone, target in opponent.field, survivor.zone,
                survivor.health, spell.zone)
    assert observed == (Zone.GRAVEYARD, False, Zone.PLAY, 5, Zone.GRAVEYARD), observed
    return f"target={target.zone.name};survivor={survivor.zone.name}:{survivor.health};spell={spell.zone.name}"


def cleave_two_distinct_enemies():
    game = new_game()
    owner, opponent = game.player1, game.player2
    enemies = [opponent.summon("CS2_182") for _ in range(3)]
    friend = owner.summon("CS2_182")
    spell = owner.give("CS2_114")
    spell.play()
    healths = sorted(minion.health for minion in enemies)
    observed = (healths, friend.health, opponent.hero.health, spell.zone)
    assert observed == ([3, 3, 5], 5, 30, Zone.GRAVEYARD), observed
    return f"enemy_healths={healths};friendly={friend.health};hero={opponent.hero.health};spell={spell.zone.name}"


def cleave_random_pool_coverage():
    selected_pairs = set()
    for seed in range(12):
        game = new_game()
        owner, opponent = game.player1, game.player2
        enemies = [opponent.summon("CS2_186") for _ in range(3)]
        friendly = owner.summon("CS2_186")
        game.random.seed(seed)
        owner.give("CS2_114").play()
        damages = tuple(7 - minion.health for minion in enemies)
        pair = tuple(index for index, damage in enumerate(damages) if damage == 2)
        assert sorted(damages) == [0, 2, 2], (seed, damages)
        assert friendly.health == 7 and opponent.hero.health == 30, (seed, damages)
        selected_pairs.add(pair)
    assert len(selected_pairs) == 3, selected_pairs
    return f"seeds=0..11;observed_pairs={sorted(selected_pairs)};each_seed_two_distinct_enemies_hit_for_2"


def cleave_one_or_zero_enemy():
    game = new_game()
    owner, opponent = game.player1, game.player2
    spell = owner.give("CS2_114")
    assert not spell.is_playable(), "Cleave should not be playable with zero enemy minions"
    lone = opponent.summon("CS2_182")
    assert spell.is_playable(), "Cleave should be playable with one enemy minion"
    spell.play()
    observed = (lone.health, spell.zone)
    assert observed == (3, Zone.GRAVEYARD), observed
    return f"one_enemy_health={lone.health};spell={spell.zone.name}"


def main():
    cases = [
        ("CS2_093", "CS2_093_enemy_scope", "All enemy characters take 2; friendly characters remain intact", consecration_enemy_scope,
         "CardDefs.xml#CS2_093; fireplace/cards/classic/paladin.py:78; no existing test reference"),
        ("CS2_094", "CS2_094_minion_draw", "Target takes 3 and one known deck card enters hand", hammer_damage_and_draw,
         "CardDefs.xml#CS2_094; fireplace/cards/classic/paladin.py:84; tests/test_secrets.py:249 is contextual only"),
        ("CS2_094", "CS2_094_hero_draw", "Hero is legal target; 3 damage plus draw", hammer_hero_target,
         "CardDefs.xml#CS2_094; fireplace/cards/classic/paladin.py:84"),
        ("CS2_094", "CS2_094_friendly_draw", "Friendly minion is legal target; 3 damage plus draw", hammer_friendly_target,
         "CardDefs.xml#CS2_094; fireplace/cards/classic/paladin.py:84"),
        ("CS2_103", "CS2_103_attack_limit", "Friendly minion gains immediate minion attack but not hero attack", charge_attack_restriction,
         "CardDefs.xml#CS2_103; fireplace/cards/classic/warrior.py:56; tests/test_mechanics.py:185 is partial"),
        ("CS2_103", "CS2_103_next_turn", "Hero-attack prohibition ends next turn, Charge remains", charge_next_turn_expiry,
         "CardDefs.xml#CS2_103; fireplace/cards/classic/warrior.py:56"),
        ("CS2_108", "CS2_108_target_limits", "Only damaged enemy minion is targetable", execute_target_limits,
         "CardDefs.xml#CS2_108; fireplace/cards/classic/warrior.py:103; no existing test reference"),
        ("CS2_108", "CS2_108_destroy", "Damaged enemy minion destroyed; other enemy remains", execute_destroys_damaged_enemy,
         "CardDefs.xml#CS2_108; fireplace/cards/classic/warrior.py:103"),
        ("CS2_114", "CS2_114_two_distinct", "Exactly two distinct random enemy minions take 2", cleave_two_distinct_enemies,
         "CardDefs.xml#CS2_114; fireplace/cards/classic/warrior.py:115; tests/test_classic.py:676 covers smaller pools"),
        ("CS2_114", "CS2_114_random_pool", "Across fixed seeds all three pairs of eligible enemies can be selected", cleave_random_pool_coverage,
         "CardDefs.xml#CS2_114; fireplace/cards/classic/warrior.py:115; per-seed damage and candidate-pool assertions"),
        ("CS2_114", "CS2_114_pool_edges", "Zero enemy rejects; one enemy receives 2", cleave_one_or_zero_enemy,
         "CardDefs.xml#CS2_114; fireplace/cards/classic/warrior.py:115; tests/test_classic.py:676"),
    ]
    for card_id, case_id, expected, probe, notes in cases:
        run(card_id, case_id, expected, probe, notes)
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    print(f"cases={len(ROWS)}; pass={sum(r['outcome'] == 'pass' for r in ROWS)}; failures={sum(r['outcome'] != 'pass' for r in ROWS)}")
    for row in ROWS:
        if row["outcome"] != "pass":
            print(row["case_id"], row["observed"])
    if any(row["outcome"] != "pass" for row in ROWS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
