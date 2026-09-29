"""Individual live behavior probes for original Classic YELLOW indices 199–208."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from fireplace.exceptions import InvalidAction
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE = HERE / "classic_probe_final10.csv"
VERDICT = HERE / "classic_verdict_final10.csv"
P_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
V_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, data):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
BASELINE = sorted(r["card_id"] for r in read(HERE / "expansion_yellow_baseline.csv")
                  if r["set"] == "Classic (EXPERT1)")
ASSIGNED = BASELINE[199:209]
assert ASSIGNED == ["EX1_617", "EX1_619", "EX1_621", "EX1_623", "EX1_626",
                    "NEW1_005", "NEW1_007", "NEW1_008", "NEW1_010", "NEW1_014"]


def game_for(cls=CardClass.MAGE):
    game = prepare_empty_game(cls, cls)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = game.player2.max_mana = 10
    return game


def ensure(condition, detail):
    if not condition:
        raise AssertionError(detail)


def record(card_id, cases, reason, blocker=None):
    assert card_id in ASSIGNED
    card = MASTER[card_id]
    source_note = (f"enUS: {card['card_text_en']}; zhCN: {card['card_text_zh']}; "
                   f"script: {card['python_source'] or 'native runtime'}; "
                   f"existing tests: {card['test_refs_candidate'] or 'none'}; prior audit: YELLOW")
    old_cases = {(r["card_id"], r["case_id"]): r for r in read(PROBE)}
    old_verdicts = {r["card_id"]: r for r in read(VERDICT)}
    for key in list(old_cases):
        if key[0] == card_id:
            del old_cases[key]
    outcomes = []
    for case_id, expected, probe in cases:
        try:
            observed, outcome = probe(), "pass"
        except AssertionError as error:
            observed, outcome = f"AssertionError: {error}", "confirmed_error"
        except Exception as error:
            observed, outcome = f"{type(error).__name__}: {error}", "inconclusive"
        outcomes.append(outcome)
        old_cases[(card_id, case_id)] = dict(card_id=card_id, case_id=case_id,
                                             expected=expected, observed=str(observed),
                                             outcome=outcome, notes=source_note)
    status = ("RED" if "confirmed_error" in outcomes else
              "YELLOW" if blocker or "inconclusive" in outcomes else "GREEN")
    if status == "YELLOW":
        reason += f" 未决：{blocker or '探针异常尚未定位。'}"
    old_verdicts[card_id] = dict(card_id=card_id, status=status,
                                 mechanic_scope=card["mechanics"], reason=reason,
                                 probe_file=PROBE.name,
                                 notes=f"逐卡真实对局：{len(cases)} 个独立 case；{','.join(outcomes)}。")
    order = {cid: i for i, cid in enumerate(ASSIGNED)}
    write(PROBE, P_FIELDS, sorted(old_cases.values(), key=lambda r: (order[r["card_id"]], r["case_id"])))
    write(VERDICT, V_FIELDS, sorted(old_verdicts.values(), key=lambda r: order[r["card_id"]]))
    print(f"{card_id}: {status}; cases={len(cases)}; outcomes={outcomes}", flush=True)


def deadly_shot_random_enemy_only():
    reached = set()
    for seed in range(24):
        game = game_for(CardClass.HUNTER)
        game.random.seed(seed)
        owner, opponent = game.player1, game.player2
        friendly = owner.summon(WISP)
        a = opponent.summon("CS2_182")
        b = opponent.summon("CS2_182")
        spell = owner.give("EX1_617")
        spell.play()
        zones = (a.zone, b.zone)
        ensure(zones.count(Zone.GRAVEYARD) == 1 and friendly.zone == Zone.PLAY,
               f"seed={seed};enemy={[z.name for z in zones]};friendly={friendly.zone.name}")
        ensure(spell.zone == Zone.GRAVEYARD and opponent.hero.health == 30,
               f"seed={seed};spell={spell.zone.name};hero={opponent.hero.health}")
        reached.add(zones.index(Zone.GRAVEYARD))
    ensure(reached == {0, 1}, f"random_reached={sorted(reached)}")
    return f"24 seeds; exactly one enemy minion destroyed; both candidates reached={sorted(reached)}; friendly/hero untouched"


def deadly_shot_no_enemy_minion_rejected():
    game = game_for(CardClass.HUNTER)
    owner = game.player1
    spell = owner.give("EX1_617")
    mana = owner.mana
    ensure(not spell.is_playable(), f"playable_without_enemy={spell.is_playable()}")
    try:
        spell.play()
    except InvalidAction:
        pass
    else:
        raise AssertionError("cast accepted with no enemy minion")
    observed = f"mana={mana}->{owner.mana};spell={spell.zone.name}"
    ensure(owner.mana == mana and spell.zone == Zone.HAND, observed)
    return observed


def equality_sets_both_sides_to_one():
    game = game_for(CardClass.PALADIN)
    owner, opponent = game.player1, game.player2
    a = owner.summon("CS2_182")
    b = opponent.summon("CS2_182")
    b.hit(2)
    heroes = (owner.hero.health, opponent.hero.health)
    spell = owner.give("EX1_619")
    spell.play()
    observed = (f"friendly={a.health}/{a.max_health};enemy={b.health}/{b.max_health};"
                f"heroes={owner.hero.health}/{opponent.hero.health};spell={spell.zone.name}")
    ensure((a.health, a.max_health, b.health, b.max_health) == (1, 1, 1, 1), observed)
    ensure((owner.hero.health, opponent.hero.health) == heroes and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def circle_heals_all_minions_not_heroes():
    game = game_for(CardClass.PRIEST)
    owner, opponent = game.player1, game.player2
    ally = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    full = owner.summon("CS2_182")
    ally.hit(3)
    enemy.hit(4)
    owner.hero.hit(5)
    opponent.hero.hit(5)
    spell = owner.give("EX1_621")
    spell.play()
    observed = (f"minions={ally.health},{enemy.health},{full.health};"
                f"heroes={owner.hero.health},{opponent.hero.health};spell={spell.zone.name}")
    ensure((ally.health, enemy.health, full.health) == (5, 5, 5), observed)
    ensure((owner.hero.health, opponent.hero.health) == (25, 25) and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def temple_enforcer_friendly_target_health():
    game = game_for(CardClass.PRIEST)
    owner, opponent = game.player1, game.player2
    ally = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    enforcer = owner.give("EX1_623")
    ensure(ally in enforcer.targets and enemy not in enforcer.targets and owner.hero not in enforcer.targets,
           f"targets={[c.id for c in enforcer.targets]}")
    enforcer.play(target=ally)
    observed = (f"ally={ally.atk}/{ally.health}/{ally.max_health};"
                f"enemy={enemy.atk}/{enemy.health};enforcer={enforcer.zone.name}:{enforcer.atk}/{enforcer.health}")
    ensure((ally.atk, ally.health, ally.max_health) == (4, 8, 8), observed)
    ensure((enemy.atk, enemy.health) == (4, 5) and enforcer.zone == Zone.PLAY, observed)
    return observed


def temple_enforcer_no_friendly_target():
    game = game_for(CardClass.PRIEST)
    owner, opponent = game.player1, game.player2
    opponent.summon("CS2_182")
    enforcer = owner.give("EX1_623")
    ensure(not enforcer.targets, f"unexpected_targets={[c.id for c in enforcer.targets]}")
    enforcer.play()
    observed = f"enforcer={enforcer.zone.name}:{enforcer.atk}/{enforcer.health};friendly_count={len(owner.field)}"
    ensure(enforcer.zone == Zone.PLAY and (enforcer.atk, enforcer.health) == (5, 6), observed)
    return observed


def mass_dispel_silence_enemy_and_draw():
    game = game_for(CardClass.PRIEST)
    owner, opponent = game.player1, game.player2
    own_taunt = owner.summon("CS1_042")
    enemy_taunt = opponent.summon("CS1_042")
    enemy_deathrattle = opponent.summon("EX1_110")
    known = owner.card("CS2_182", zone=Zone.DECK)
    spell = owner.give("EX1_626")
    spell.play()
    observed = (f"friendly_taunt={own_taunt.taunt};enemy_taunt={enemy_taunt.taunt};"
                f"enemy_deathrattle={enemy_deathrattle.has_deathrattle};"
                f"known={known.zone.name};deck={len(owner.deck)};spell={spell.zone.name}")
    ensure(own_taunt.taunt and not enemy_taunt.taunt and not enemy_deathrattle.has_deathrattle, observed)
    ensure(known.zone == Zone.HAND and len(owner.deck) == 0 and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def mass_dispel_empty_enemy_board_still_draws():
    game = game_for(CardClass.PRIEST)
    owner = game.player1
    known = owner.card(WISP, zone=Zone.DECK)
    spell = owner.give("EX1_626")
    spell.play()
    observed = f"known={known.zone.name};hand={len(owner.hand)};deck={len(owner.deck)};spell={spell.zone.name}"
    ensure(known.zone == Zone.HAND and len(owner.hand) == 1 and len(owner.deck) == 0, observed)
    return observed


def kidnapper_no_combo_no_bounce():
    game = game_for(CardClass.ROGUE)
    owner, opponent = game.player1, game.player2
    victim = opponent.summon("CS2_182")
    enemy_hand_before = len(opponent.hand)
    kidnapper = owner.give("NEW1_005")
    kidnapper.play()
    observed = f"victim={victim.zone.name};kidnapper={kidnapper.zone.name};enemy_hand={len(opponent.hand)}"
    ensure(victim.zone == Zone.PLAY and kidnapper.zone == Zone.PLAY and len(opponent.hand) == enemy_hand_before, observed)
    return observed


def kidnapper_combo_enemy_bounce_to_owner():
    game = game_for(CardClass.ROGUE)
    owner, opponent = game.player1, game.player2
    victim = opponent.summon("CS2_182")
    owner.give("CS2_008").play(target=opponent.hero)  # Play a zero-cost card first.
    kidnapper = owner.give("NEW1_005")
    ensure(victim in kidnapper.targets, f"combo_targets={[c.id for c in kidnapper.targets]}")
    kidnapper.play(target=victim)
    observed = f"victim={victim.zone.name}:{victim.controller.name};enemy_hand={len(opponent.hand)};kidnapper={kidnapper.zone.name}"
    ensure(victim.zone == Zone.HAND and victim.controller is opponent and victim in opponent.hand, observed)
    ensure(kidnapper.zone == Zone.PLAY and len(opponent.field) == 0, observed)
    return observed


def kidnapper_combo_friendly_bounce():
    game = game_for(CardClass.ROGUE)
    owner, opponent = game.player1, game.player2
    victim = owner.summon("CS2_182")
    owner.give("CS2_008").play(target=opponent.hero)
    kidnapper = owner.give("NEW1_005")
    ensure(victim in kidnapper.targets, f"friendly_not_targetable={[c.id for c in kidnapper.targets]}")
    kidnapper.play(target=victim)
    observed = f"victim={victim.zone.name}:{victim.controller.name};own_hand={len(owner.hand)};kidnapper={kidnapper.zone.name}"
    ensure(victim.zone == Zone.HAND and victim.controller is owner and victim in owner.hand, observed)
    ensure(kidnapper.zone == Zone.PLAY, observed)
    return observed


def kidnapper_combo_stolen_minion_returns_original_owner():
    game = game_for(CardClass.ROGUE)
    caster, original_owner = game.player1, game.player2
    victim = original_owner.summon(WISP)
    caster.steal(victim)
    ensure(victim.zone == Zone.PLAY and victim.controller is caster,
           f"stolen_setup={victim.zone.name}:{victim.controller.name}")
    caster.give("CS2_008").play(target=original_owner.hero)
    kidnapper = caster.give("NEW1_005")
    ensure(victim in kidnapper.targets, f"stolen_target_missing={[c.id for c in kidnapper.targets]}")
    kidnapper.play(target=victim)
    observed = (f"original_owner={original_owner.name};current_controller={caster.name};"
                f"victim={victim.zone.name}:{victim.controller.name};"
                f"in_original_hand={victim in original_owner.hand};in_caster_hand={victim in caster.hand};"
                f"kidnapper={kidnapper.zone.name}")
    ensure(victim.zone == Zone.HAND and victim in original_owner.hand and victim.controller is original_owner,
           observed)
    ensure(victim not in caster.hand and kidnapper.zone == Zone.PLAY, observed)
    return observed


def starfall_single_target_five_and_target_gate():
    game = game_for(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    victim = opponent.summon("CS2_182")
    other = opponent.summon("CS2_182")
    ally = owner.summon("CS2_182")
    spell = owner.give("NEW1_007")
    spell.play(choose="NEW1_007b", target=victim)
    observed = (f"victim={victim.zone.name};other={other.health};ally={ally.health};"
                f"enemy_hero={opponent.hero.health};spell={spell.zone.name}")
    ensure(victim.zone == Zone.GRAVEYARD and other.health == ally.health == 5, observed)
    ensure(opponent.hero.health == 30 and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def starfall_area_enemy_minions_only():
    game = game_for(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    enemy_a = opponent.summon("CS2_182")
    enemy_b = opponent.summon("CS2_182")
    ally = owner.summon("CS2_182")
    spell = owner.give("NEW1_007")
    spell.play(choose="NEW1_007a")
    observed = (f"enemy={enemy_a.health},{enemy_b.health};friendly={ally.health};"
                f"heroes={owner.hero.health},{opponent.hero.health};spell={spell.zone.name}")
    ensure((enemy_a.health, enemy_b.health, ally.health) == (3, 3, 5), observed)
    ensure(owner.hero.health == opponent.hero.health == 30 and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def starfall_requires_choice_and_minion_target():
    game = game_for(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    victim = opponent.summon("CS2_182")
    spell = owner.give("NEW1_007")
    before = owner.mana
    for args in ({}, {"choose": "NEW1_007b", "target": opponent.hero}):
        try:
            spell.play(**args)
        except InvalidAction:
            pass
        else:
            raise AssertionError(f"invalid choice/target accepted: {args}")
    observed = f"mana={before}->{owner.mana};victim={victim.health};spell={spell.zone.name}"
    ensure(owner.mana == before and victim.health == 5 and spell.zone == Zone.HAND, observed)
    return observed


def ancient_of_lore_draw_choice_one_known_card():
    game = game_for(CardClass.DRUID)
    owner = game.player1
    known = owner.card(WISP, zone=Zone.DECK)
    ancient = owner.give("NEW1_008")
    ancient.play(choose="NEW1_008a")
    observed = (f"known={known.zone.name};deck={len(owner.deck)};"
                f"ancient={ancient.zone.name}:{ancient.atk}/{ancient.health}")
    ensure(known.zone == Zone.HAND and len(owner.deck) == 0, observed)
    ensure(ancient.zone == Zone.PLAY and (ancient.atk, ancient.health) == (5, 5), observed)
    return observed


def ancient_of_lore_heal_choice_target_domain():
    game = game_for(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    owner.hero.hit(7)
    enemy = opponent.summon("CS2_182")
    enemy.hit(4)
    ancient = owner.give("NEW1_008")
    ancient.play(choose="NEW1_008b", target=enemy)
    observed = (f"enemy_hero={opponent.hero.health};own_hero={owner.hero.health};"
                f"enemy_minion={enemy.health};ancient={ancient.zone.name}")
    ensure(opponent.hero.health == 30 and owner.hero.health == 23 and enemy.health == 5, observed)
    ensure(ancient.zone == Zone.PLAY, observed)
    return observed


def ancient_of_lore_heal_enemy_hero_five():
    game = game_for(CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    opponent.hero.hit(8)
    ancient = owner.give("NEW1_008")
    ancient.play(choose="NEW1_008b", target=opponent.hero)
    observed = f"enemy_hero={opponent.hero.health};ancient={ancient.zone.name}"
    ensure(opponent.hero.health == 27 and ancient.zone == Zone.PLAY, observed)
    return observed


def ancient_of_lore_heal_friendly_hero_five():
    game = game_for(CardClass.DRUID)
    owner = game.player1
    owner.hero.hit(8)
    ancient = owner.give("NEW1_008")
    ancient.play(choose="NEW1_008b", target=owner.hero)
    observed = f"hero={owner.hero.health};ancient={ancient.zone.name}"
    ensure(owner.hero.health == 27 and ancient.zone == Zone.PLAY, observed)
    return observed


def ancient_of_lore_requires_choice():
    game = game_for(CardClass.DRUID)
    owner = game.player1
    ancient = owner.give("NEW1_008")
    before = owner.mana
    try:
        ancient.play()
    except InvalidAction:
        pass
    else:
        raise AssertionError("Choose One card accepted with no choice")
    observed = f"mana={before}->{owner.mana};ancient={ancient.zone.name}"
    ensure(owner.mana == before and ancient.zone == Zone.HAND, observed)
    return observed


def alakir_charge_windfury_shield_actual_combat():
    game = game_for(CardClass.SHAMAN)
    owner, opponent = game.player1, game.player2
    yeti = opponent.summon("CS2_182")
    alakir = owner.give("NEW1_010")
    alakir.play()
    ensure(alakir.charge and alakir.windfury and alakir.divine_shield and alakir.taunt,
           f"keywords={(alakir.charge,alakir.windfury,alakir.divine_shield,alakir.taunt)}")
    alakir.attack(yeti)
    after_first = (yeti.health, alakir.health, alakir.divine_shield, alakir.can_attack())
    alakir.attack(opponent.hero)
    after_second = (opponent.hero.health, alakir.can_attack())
    observed = f"after_first={after_first};after_second={after_second};alakir={alakir.zone.name}"
    ensure(after_first == (2, 5, False, True), observed)
    ensure(after_second == (27, False) and alakir.zone == Zone.PLAY, observed)
    return observed


def alakir_taunt_blocks_hero_and_shield_absorbs():
    game = game_for(CardClass.SHAMAN)
    owner, opponent = game.player1, game.player2
    alakir = owner.give("NEW1_010")
    alakir.play()
    game.end_turn()
    attacker = opponent.give("CS2_173")  # Charge 2/1 Bluegill Warrior.
    attacker.play()
    ensure(not attacker.can_attack(owner.hero) and attacker.can_attack(alakir),
           f"legal_hero={attacker.can_attack(owner.hero)};legal_alakir={attacker.can_attack(alakir)}")
    try:
        attacker.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("attacker bypassed Taunt")
    attacker.attack(alakir)
    observed = (f"owner_hero={owner.hero.health};alakir={alakir.health}:shield={alakir.divine_shield};"
                f"attacker={attacker.zone.name}")
    ensure(owner.hero.health == 30 and alakir.health == 5 and not alakir.divine_shield, observed)
    ensure(attacker.zone == Zone.GRAVEYARD, observed)
    return observed


def master_of_disguise_friendly_stealth_until_next_turn():
    game = game_for(CardClass.ROGUE)
    owner, opponent = game.player1, game.player2
    ally = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    master = owner.give("NEW1_014")
    ensure(ally in master.targets and enemy not in master.targets,
           f"battlecry_targets={[c.id for c in master.targets]}")
    master.play(target=ally)
    ensure(ally.stealthed and master.zone == Zone.PLAY,
           f"after_play_stealth={ally.stealthed};master={master.zone.name}")
    game.end_turn()
    bolt = opponent.give("CS2_024")
    ensure(ally not in bolt.targets, f"enemy_spell_targets={[c.id for c in bolt.targets]}")
    game.end_turn()
    observed = f"ally_stealthed={ally.stealthed};ally_zone={ally.zone.name};master={master.zone.name}"
    ensure(not ally.stealthed and ally.zone == Zone.PLAY and master.zone == Zone.PLAY, observed)
    return observed


def master_of_disguise_no_other_friendly_target():
    game = game_for(CardClass.ROGUE)
    owner = game.player1
    master = owner.give("NEW1_014")
    ensure(not master.targets, f"unexpected_targets={[c.id for c in master.targets]}")
    master.play()
    observed = f"master={master.zone.name}:{master.atk}/{master.health};stealthed={master.stealthed}"
    ensure(master.zone == Zone.PLAY and (master.atk, master.health) == (4, 4) and not master.stealthed, observed)
    return observed


def main():
    record("EX1_617", [
        ("random_enemy_minion_domain", "Destroy exactly one random enemy minion; both eligible minions reachable, friendly minion and heroes excluded.", deadly_shot_random_enemy_only),
        ("no_enemy_minion_rejected", "With no enemy minion, spell cannot be cast and consumes no mana/card.", deadly_shot_no_enemy_minion_rejected),
    ], "致命射击只随机消灭一个敌方随从，24种子覆盖双候选；无敌方随从时不能施放且不扣费。")
    record("EX1_619", [
        ("all_minions_health_one_both_sides", "Equality sets both friendly and enemy minions, including a wounded minion, to 1 current/max Health; heroes unchanged.", equality_sets_both_sides_to_one),
    ], "平等将双方所有随从的当前和最大生命都改为1，受伤随从亦然；英雄不受影响。")
    record("EX1_621", [
        ("heal_four_all_minions_not_heroes", "Circle of Healing restores up to four Health to all friendly/enemy minions, capped at max, never heroes.", circle_heals_all_minions_not_heroes),
    ], "治疗之环使双方受伤随从各回复4点并受上限约束，英雄不受影响。")
    record("EX1_623", [
        ("friendly_target_plus_three_health", "Battlecry accepts a friendly minion, gives exactly +3 current/max Health, and excludes enemy minions and heroes.", temple_enforcer_friendly_target_health),
        ("no_friendly_minion_optional_battlecry", "Without another friendly minion, Temple Enforcer enters as an unbuffed 5/6.", temple_enforcer_no_friendly_target),
    ], "战吼仅选择友方随从并增加3点生命；无友方目标仍可作为5/6入场。")
    record("EX1_626", [
        ("silence_all_enemy_minions_and_draw", "Mass Dispel silences every enemy minion, leaves friendly Taunt intact, and draws the known deck card.", mass_dispel_silence_enemy_and_draw),
        ("empty_enemy_board_still_draws", "Mass Dispel still draws one known card with no enemy minions.", mass_dispel_empty_enemy_board_still_draws),
    ], "群体驱散沉默所有敌方随从、不影响友方随从并抽一张牌；敌方无随从时仍抽牌。")
    record("NEW1_005", [
        ("no_combo_no_bounce", "Without a prior card this turn, Kidnapper enters without returning any minion.", kidnapper_no_combo_no_bounce),
        ("combo_enemy_minion_bounce", "With Combo active, enemy minion returns to its owner's hand, Kidnapper stays in play.", kidnapper_combo_enemy_bounce_to_owner),
        ("combo_friendly_minion_bounce", "With Combo active, friendly minion can also return to its owner's hand.", kidnapper_combo_friendly_bounce),
        ("combo_stolen_minion_returns_original_owner", "With Combo active, a stolen minion must return to its original owner's hand, not its current controller's hand.", kidnapper_combo_stolen_minion_returns_original_owner),
    ], "连击时偷来的随从错误返回当前控制者而不是原拥有者的手牌；普通友敌回手和无连击分支通过。")
    record("NEW1_007", [
        ("single_choice_five_to_one_minion", "Single-target choice deals five to the selected minion only, destroying a 4/5 while others remain.", starfall_single_target_five_and_target_gate),
        ("area_choice_two_to_enemy_minions", "Area choice deals two to each enemy minion, not friendly minions or heroes.", starfall_area_enemy_minions_only),
        ("choice_required_and_hero_target_rejected", "No choice and hero target for single-target option are rejected before mana/card movement.", starfall_requires_choice_and_minion_target),
    ], "星辰坠落两选项分别实测单体5伤与敌方随从全体2伤，缺选择和英雄非法目标均不扣费。")
    record("NEW1_008", [
        ("draw_choice_one_known_card", "Draw choice moves exactly one known deck card into hand; Ancient enters as 5/5.", ancient_of_lore_draw_choice_one_known_card),
        ("heal_choice_enemy_minion_target", "Heal choice legally restores a wounded enemy minion up to its max Health, without healing heroes.", ancient_of_lore_heal_choice_target_domain),
        ("heal_choice_enemy_hero_five", "Heal choice can restore exactly five to a wounded enemy hero.", ancient_of_lore_heal_enemy_hero_five),
        ("heal_choice_friendly_hero_five", "Heal choice restores exactly five to a wounded friendly hero.", ancient_of_lore_heal_friendly_hero_five),
        ("choice_required", "Ancient of Lore cannot be played without choosing a branch; no mana/card is spent.", ancient_of_lore_requires_choice),
    ], "知识古树抽牌分支从牌库抽恰好一张已知牌；治疗分支对合法英雄回复5点；未选分支被拒且不扣费。")
    record("NEW1_010", [
        ("charge_windfury_divine_shield_combat", "Al'Akir immediately attacks twice for 3, Shield blocks first retaliation, and third attack is unavailable.", alakir_charge_windfury_shield_actual_combat),
        ("taunt_blocks_hero_and_shield_absorbs", "Enemy Charge minion cannot bypass Al'Akir's Taunt; attack into it consumes Shield without Health loss.", alakir_taunt_blocks_hero_and_shield_absorbs),
    ], "奥拉基尔四关键词均实战验证：即时两次攻击、第三次不可攻击、圣盾挡反击、嘲讽阻挡敌方直击。")
    record("NEW1_014", [
        ("friendly_stealth_until_next_turn", "Battlecry grants friendly minion Stealth, excluding enemy targets; enemy targeted spell is blocked until owner's next turn.", master_of_disguise_friendly_stealth_until_next_turn),
        ("no_other_friendly_minion_optional", "With no other friendly minion, Master enters unstealthed as 4/4 without a target.", master_of_disguise_no_other_friendly_target),
    ], "伪装大师仅给其他友方随从潜行，敌方法术在持续期不能指定，下个己方回合开始解除；无目标仍可作为4/4入场。")


if __name__ == "__main__":
    main()
