"""Card-specific Basic probes for CS2_196, CS2_234, DS1_055, EX1_360, EX1_371."""

import csv
from pathlib import Path

from hearthstone.enums import Race, Zone

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


def razorfen_summons_boar():
    game = new_game()
    owner = game.player1
    hunter = owner.give("CS2_196")
    hunter.play()
    boars = [m for m in owner.field if m.id == "CS2_boar"]
    assert len(boars) == 1, [m.id for m in owner.field]
    boar = boars[0]
    state = (hunter.zone, boar.zone, boar.atk, boar.health,
             Race(boar.race), len(owner.field))
    assert state == (Zone.PLAY, Zone.PLAY, 1, 1, Race.BEAST, 2), state
    return f"hunter={hunter.zone.name};boar={boar.id}:{boar.atk}/{boar.health}:{Race(boar.race).name};field={len(owner.field)}"


def razorfen_last_slot():
    game = new_game()
    owner = game.player1
    for _ in range(6):
        owner.summon("CS2_231")
    hunter = owner.give("CS2_196")
    hunter.play()
    boars = [m for m in owner.field if m.id == "CS2_boar"]
    state = (len(owner.field), hunter.zone, len(boars))
    assert state == (7, Zone.PLAY, 0), state
    return f"field={len(owner.field)};hunter={hunter.zone.name};boars={len(boars)}"


def pain_attack_threshold_and_destroy():
    game = new_game()
    owner, opponent = game.player1, game.player2
    low = opponent.summon("CS2_125")  # 3 Attack
    high = opponent.summon("CS2_182")  # 4 Attack
    friendly = owner.summon("CS2_231")
    spell = owner.give("CS2_234")
    legal = (low in spell.targets, high in spell.targets,
             friendly in spell.targets, opponent.hero in spell.targets)
    assert legal == (True, False, True, False), legal
    spell.play(target=low)
    state = (low.zone, high.zone, friendly.zone, spell.zone)
    assert state == (Zone.GRAVEYARD, Zone.PLAY, Zone.PLAY, Zone.GRAVEYARD), state
    return f"targets={legal};low={low.zone.name};high={high.zone.name};friendly={friendly.zone.name}"


def pain_friendly_minion():
    game = new_game()
    owner = game.player1
    target = owner.summon("CS2_231")
    spell = owner.give("CS2_234")
    assert target in spell.targets
    spell.play(target=target)
    state = (target.zone, target not in owner.field, spell.zone)
    assert state == (Zone.GRAVEYARD, True, Zone.GRAVEYARD), state
    return f"friendly_target={target.zone.name};spell={spell.zone.name}"


def darkscale_heals_friendlies_only():
    game = new_game()
    owner, opponent = game.player1, game.player2
    owner.hero.damage = 5
    opponent.hero.damage = 5
    injured = owner.summon("CS2_182")
    injured.damage = 3
    full = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    enemy.damage = 3
    healer = owner.give("DS1_055")
    healer.play()
    state = (owner.hero.health, opponent.hero.health, injured.health,
             full.health, enemy.health, healer.zone)
    assert state == (27, 25, 4, 5, 2, Zone.PLAY), state
    return f"friendly_hero={owner.hero.health};enemy_hero={opponent.hero.health};friendly_minions={injured.health}/{full.health};enemy_minion={enemy.health};healer={healer.zone.name}"


def humility_sets_high_attack_to_one():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    friendly = owner.summon("CS2_182")
    spell = owner.give("EX1_360")
    assert target in spell.targets and friendly in spell.targets and opponent.hero not in spell.targets
    spell.play(target=target)
    state = (target.atk, friendly.atk, target.zone, spell.zone)
    assert state == (1, 4, Zone.PLAY, Zone.GRAVEYARD), state
    return f"target_attack={target.atk};untargeted_attack={friendly.atk};spell={spell.zone.name}"


def humility_raises_zero_attack_to_one():
    game = new_game()
    owner = game.player1
    totem = owner.summon("EX1_565")
    assert totem.atk == 0
    owner.give("EX1_360").play(target=totem)
    state = (totem.atk, totem.zone)
    assert state == (1, Zone.PLAY), state
    return f"totem_attack={totem.atk};zone={totem.zone.name}"


def protection_shield_absorbs_hit():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    friendly = owner.summon("CS2_182")
    spell = owner.give("EX1_371")
    assert target in spell.targets and friendly in spell.targets and owner.hero not in spell.targets
    spell.play(target=target)
    assert target.divine_shield and target.health == 5
    owner.give("CS2_008").play(target=target)
    first = (target.health, target.divine_shield)
    owner.give("CS2_008").play(target=target)
    second = (target.health, target.divine_shield)
    assert first == (5, False) and second == (4, False), (first, second)
    return f"first_hit={first};second_hit={second};spell={spell.zone.name}"


def protection_can_target_friendly_minion():
    game = new_game()
    owner = game.player1
    target = owner.summon("CS2_182")
    spell = owner.give("EX1_371")
    spell.play(target=target)
    state = (target.divine_shield, target.zone, spell.zone)
    assert state == (True, Zone.PLAY, Zone.GRAVEYARD), state
    return f"friendly_shield={target.divine_shield};zone={target.zone.name}"


def main():
    cases = [
        ("CS2_196", "CS2_196_boar", "Battlecry summons exactly one 1/1 Beast Boar", razorfen_summons_boar,
         "CardDefs.xml#CS2_196; fireplace/cards/classic/neutral_common.py:159; no prior effect test"),
        ("CS2_196", "CS2_196_last_slot", "Body fills seventh slot and Boar cannot exceed board limit", razorfen_last_slot,
         "CardDefs.xml#CS2_196; fireplace/cards/classic/neutral_common.py:159"),
        ("CS2_234", "CS2_234_threshold", "Only minions with at most 3 Attack targetable; selected one destroyed", pain_attack_threshold_and_destroy,
         "CardDefs.xml#CS2_234; fireplace/cards/classic/priest.py:189; tests/test_classic.py:2942 partial"),
        ("CS2_234", "CS2_234_friendly", "A friendly minion at threshold may also be destroyed", pain_friendly_minion,
         "CardDefs.xml#CS2_234; fireplace/cards/classic/priest.py:189"),
        ("DS1_055", "DS1_055_friendly_scope", "Heal each friendly character by up to two; leave enemies unchanged", darkscale_heals_friendlies_only,
         "CardDefs.xml#DS1_055; fireplace/cards/classic/neutral_common.py:187; no prior effect test"),
        ("EX1_360", "EX1_360_high_attack", "Set chosen minion Attack to one while leaving others unchanged", humility_sets_high_attack_to_one,
         "CardDefs.xml#EX1_360; fireplace/cards/classic/paladin.py:115; tests/test_classic.py:1638 partial"),
        ("EX1_360", "EX1_360_zero_attack", "Set a zero-Attack minion's Attack to one", humility_raises_zero_attack_to_one,
         "CardDefs.xml#EX1_360; fireplace/cards/classic/paladin.py:115"),
        ("EX1_371", "EX1_371_absorb", "Divine Shield absorbs first damage and then falls; second hit damages minion", protection_shield_absorbs_hit,
         "CardDefs.xml#EX1_371; fireplace/cards/classic/paladin.py:150; no prior effect test"),
        ("EX1_371", "EX1_371_friendly", "Friendly minion can receive Divine Shield", protection_can_target_friendly_minion,
         "CardDefs.xml#EX1_371; fireplace/cards/classic/paladin.py:150"),
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
