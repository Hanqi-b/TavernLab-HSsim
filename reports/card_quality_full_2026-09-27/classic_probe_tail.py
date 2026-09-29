"""Individual behavior probes for the final 20 original Classic Yellow cards."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from fireplace.exceptions import InvalidAction
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE_OUT = HERE / "classic_probe_tail.csv"
VERDICT_OUT = HERE / "classic_verdict_tail.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


MASTER = {row["card_id"]: row for row in read_rows(HERE / "card_master.csv")}
BASELINE = sorted(
    (row["card_id"] for row in read_rows(HERE / "expansion_yellow_baseline.csv")
     if row["set"] == "Classic (EXPERT1)"))
ASSIGNED = set(BASELINE[-20:])
assert len(BASELINE) == 229 and len(ASSIGNED) == 20


def write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def game_for(card_class=CardClass.MAGE):
    game = prepare_empty_game(card_class, card_class)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = 10
    game.player2.max_mana = 10
    return game


def check(condition, observation):
    if not condition:
        raise AssertionError(observation)


def record_card(card_id, cases, reason, blocker=None):
    assert card_id in ASSIGNED
    old_cases = {(row["card_id"], row["case_id"]): row for row in read_rows(PROBE_OUT)}
    old_verdicts = {row["card_id"]: row for row in read_rows(VERDICT_OUT)}
    for key in list(old_cases):
        if key[0] == card_id:
            del old_cases[key]
    outcomes = []
    card = MASTER[card_id]
    notes = (f"enUS: {card['card_text_en']}; zhCN: {card['card_text_zh']}; "
             f"script: {card['python_source'] or 'native runtime'}; "
             f"existing test references: {card['test_refs_candidate'] or 'none'}; "
             "prior card_quality: YELLOW")
    for case_id, expected, probe in cases:
        try:
            observed = probe()
            outcome = "pass"
        except AssertionError as error:
            observed = f"AssertionError: {error}"
            outcome = "confirmed_error"
        except Exception as error:
            observed = f"{type(error).__name__}: {error}"
            outcome = "inconclusive"
        old_cases[(card_id, case_id)] = dict(card_id=card_id, case_id=case_id,
                                             expected=expected, observed=str(observed),
                                             outcome=outcome, notes=notes)
        outcomes.append(outcome)
    status = ("RED" if "confirmed_error" in outcomes else
              "YELLOW" if blocker or "inconclusive" in outcomes else "GREEN")
    if status == "YELLOW":
        reason += f" 未决：{blocker or '探针异常尚未定位，不能判定卡牌实现。'}"
    old_verdicts[card_id] = dict(card_id=card_id, status=status,
                                 mechanic_scope=card["mechanics"], reason=reason,
                                 probe_file=PROBE_OUT.name,
                                 notes=f"逐卡真实对局：{len(cases)} 个独立 case；{','.join(outcomes)}。")
    order = {cid: index for index, cid in enumerate(BASELINE[-20:])}
    write_rows(PROBE_OUT, PROBE_FIELDS,
               sorted(old_cases.values(), key=lambda row: (order[row["card_id"]], row["case_id"])))
    write_rows(VERDICT_OUT, VERDICT_FIELDS,
               sorted(old_verdicts.values(), key=lambda row: order[row["card_id"]]))
    print(f"{card_id}: {status}; cases={len(cases)}; outcomes={outcomes}", flush=True)


def hungry_crab_enemy_murloc():
    game = game_for()
    owner, opponent = game.player1, game.player2
    victim = opponent.summon("CS2_168")
    crab = owner.give("NEW1_017")
    check(victim in crab.targets, f"victim_not_targetable={victim.id}")
    crab.play(target=victim)
    observed = f"victim={victim.zone.name};crab={crab.atk}/{crab.health}:{crab.zone.name}"
    check(victim.zone == Zone.GRAVEYARD and victim not in opponent.field, observed)
    check((crab.atk, crab.health, crab.zone) == (3, 4, Zone.PLAY), observed)
    return observed


def hungry_crab_friendly_murloc_and_reject_nonmurloc():
    game = game_for()
    owner = game.player1
    friendly = owner.summon("CS2_168")
    nonmurloc = owner.summon(WISP)
    crab = owner.give("NEW1_017")
    check(friendly in crab.targets and nonmurloc not in crab.targets,
          f"targets={[x.id for x in crab.targets]}")
    crab.play(target=friendly)
    observed = f"friendly={friendly.zone.name};other={nonmurloc.zone.name};crab={crab.atk}/{crab.health}"
    check(friendly.zone == Zone.GRAVEYARD and nonmurloc.zone == Zone.PLAY, observed)
    check((crab.atk, crab.health) == (3, 4), observed)
    return observed


def hungry_crab_no_murloc():
    game = game_for()
    owner = game.player1
    crab = owner.give("NEW1_017")
    playable = crab.is_playable()
    before_mana = owner.mana
    crab.play()
    observed = f"playable={playable};mana={before_mana}->{owner.mana};crab={crab.zone.name}:{crab.atk}/{crab.health}"
    # REQ_TARGET_IF_AVAILABLE permits a minion play when no Murloc exists.
    check(playable and owner.mana == before_mana - crab.cost, observed)
    check((crab.zone, crab.atk, crab.health) == (Zone.PLAY, 1, 2), observed)
    return observed


def bloodsail_raider_weapon():
    game = game_for(CardClass.WARRIOR)
    owner = game.player1
    weapon = owner.give("CS2_106")  # Fiery War Axe: 3 Attack.
    weapon.play()
    raider = owner.give("NEW1_018")
    raider.play()
    observed = f"weapon={weapon.atk}/{weapon.durability};raider={raider.atk}/{raider.health}"
    check(weapon.zone == Zone.PLAY and (raider.atk, raider.health) == (5, 3), observed)
    return observed


def bloodsail_raider_no_own_weapon():
    game = game_for(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    game.end_turn()
    opponent.give("CS2_106").play()
    game.end_turn()
    raider = owner.give("NEW1_018")
    raider.play()
    observed = f"enemy_weapon={opponent.weapon.atk};raider={raider.atk}/{raider.health}"
    check((raider.atk, raider.health) == (2, 3), observed)
    return observed


def knife_juggler_friendly_summon():
    game = game_for()
    owner, opponent = game.player1, game.player2
    juggler = owner.give("NEW1_019")
    juggler.play()
    before = opponent.hero.health
    owner.summon(WISP)
    observed = f"hero={before}->{opponent.hero.health};juggler={juggler.health}"
    check(opponent.hero.health == before - 1 and juggler.health == 2, observed)
    return observed


def knife_juggler_enemy_summon_excluded():
    game = game_for()
    owner, opponent = game.player1, game.player2
    juggler = owner.give("NEW1_019")
    juggler.play()
    enemy_health = opponent.hero.health
    opponent.summon(WISP)
    observed = f"enemy_hero={enemy_health}->{opponent.hero.health};juggler={juggler.health}"
    check(opponent.hero.health == enemy_health and juggler.health == 2, observed)
    return observed


def knife_juggler_random_enemy_character_domain():
    reached = set()
    for seed in range(24):
        game = game_for()
        game.random.seed(seed)
        owner, opponent = game.player1, game.player2
        a = opponent.summon("CS2_182")
        b = opponent.summon("CS2_182")
        juggler = owner.give("NEW1_019")
        juggler.play()
        before = (opponent.hero.health, a.health, b.health, owner.hero.health)
        owner.summon(WISP)
        after = (opponent.hero.health, a.health, b.health, owner.hero.health)
        changes = tuple(x-y for x, y in zip(before, after))
        check(sum(changes) == 1 and changes[3] == 0 and all(x in (0, 1) for x in changes),
              f"seed={seed};before={before};after={after}")
        reached.add(changes.index(1))
    observed = f"24 seeds; reached enemy hero/minions={sorted(reached)}"
    check(reached == {0, 1, 2}, observed)
    return observed


def wild_pyromancer_own_spell_all_minions():
    game = game_for()
    owner, opponent = game.player1, game.player2
    pyro = owner.give("NEW1_020")
    pyro.play()
    ally = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    own_hero, enemy_hero = owner.hero.health, opponent.hero.health
    owner.give("CS2_024").play(target=opponent.hero)  # Frostbolt.
    observed = (f"minions={pyro.health},{ally.health},{enemy.health};"
                f"heroes={own_hero}->{owner.hero.health},{enemy_hero}->{opponent.hero.health}")
    check((pyro.health, ally.health, enemy.health) == (1, 4, 4), observed)
    check(owner.hero.health == own_hero and opponent.hero.health == enemy_hero - 3, observed)
    return observed


def wild_pyromancer_enemy_spell_no_trigger():
    game = game_for()
    owner, opponent = game.player1, game.player2
    pyro = owner.give("NEW1_020")
    pyro.play()
    game.end_turn()
    opponent.give("CS2_024").play(target=owner.hero)
    observed = f"pyro={pyro.health};own_hero={owner.hero.health}"
    check(pyro.health == 2 and owner.hero.health == 27, observed)
    return observed


def doomsayer_own_turn_begin():
    game = game_for()
    owner, opponent = game.player1, game.player2
    doomsayer = owner.give("NEW1_021")
    doomsayer.play()
    ally = owner.summon(WISP)
    enemy = opponent.summon("CS2_182")
    game.end_turn()
    check(all(c.zone == Zone.PLAY for c in (doomsayer, ally, enemy)),
          f"destroyed_at_enemy_turn={[c.zone.name for c in (doomsayer, ally, enemy)]}")
    game.end_turn()
    observed = f"zones={[c.zone.name for c in (doomsayer, ally, enemy)]};fields={len(owner.field)}/{len(opponent.field)}"
    check(all(c.zone == Zone.GRAVEYARD for c in (doomsayer, ally, enemy)), observed)
    check(len(owner.field) == len(opponent.field) == 0, observed)
    return observed


def dread_corsair_weapon_cost_and_taunt():
    game = game_for(CardClass.WARRIOR)
    owner = game.player1
    corsair = owner.give("NEW1_022")
    check(corsair.cost == 4, f"unarmed_cost={corsair.cost}")
    axe = owner.give("CS2_106")
    axe.play()
    check(corsair.cost == 1, f"axe_attack={axe.atk};corsair_cost={corsair.cost}")
    corsair.play()
    observed = f"cost=1;zone={corsair.zone.name};taunt={corsair.taunt}"
    check(corsair.zone == Zone.PLAY and corsair.taunt, observed)
    return observed


def dread_corsair_weapon_change_and_enemy_excluded():
    game = game_for(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    corsair = owner.give("NEW1_022")
    game.end_turn()
    opponent.give("CS2_106").play()
    game.end_turn()
    check(corsair.cost == 4, f"enemy_weapon_discount={corsair.cost}")
    own = owner.give("CS2_091")  # Light's Justice: one Attack.
    own.play()
    check(corsair.cost == 3, f"one_attack_discount={corsair.cost}")
    own.destroy()
    observed = f"after_destroy={corsair.cost};enemy_weapon={opponent.weapon.atk}"
    check(corsair.cost == 4, observed)
    return observed


def faerie_dragon_target_gate_and_battlecry():
    game = game_for()
    owner, opponent = game.player1, game.player2
    dragon = owner.give("NEW1_023")
    dragon.play()
    own_bolt = owner.give("CS2_024")
    check(dragon not in own_bolt.targets and dragon not in owner.hero.power.targets,
          f"own_spell_targets={[c.id for c in own_bolt.targets]};own_power_targets={[c.id for c in owner.hero.power.targets]}")
    game.end_turn()
    bolt = opponent.give("CS2_024")
    power = opponent.hero.power
    archer = opponent.give("CS2_189")
    observed = (f"bolt_targets={[c.id for c in bolt.targets]};"
                f"power_targets={[c.id for c in power.targets]};"
                f"archer_targets={[c.id for c in archer.targets]}")
    check(dragon not in bolt.targets and dragon not in power.targets, observed)
    check(dragon in archer.targets, observed)
    try:
        bolt.play(target=dragon)
    except InvalidAction:
        pass
    else:
        raise AssertionError("targeted Frostbolt was illegally accepted")
    archer.play(target=dragon)
    observed += f";post_battlecry_health={dragon.health}"
    check(dragon.zone == Zone.PLAY and dragon.health == 1, observed)
    return observed


def captain_greenskin_own_weapon_buff():
    game = game_for(CardClass.WARRIOR)
    owner = game.player1
    axe = owner.give("CS2_106")
    axe.play()
    before = (axe.atk, axe.durability)
    greenskin = owner.give("NEW1_024")
    greenskin.play()
    observed = f"weapon={before}->{(axe.atk, axe.durability)};captain={greenskin.zone.name}"
    check((axe.atk, axe.durability) == (before[0] + 1, before[1] + 1), observed)
    check(greenskin.zone == Zone.PLAY, observed)
    return observed


def captain_greenskin_enemy_weapon_not_buffed():
    game = game_for(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    game.end_turn()
    enemy_axe = opponent.give("CS2_106")
    enemy_axe.play()
    game.end_turn()
    greenskin = owner.give("NEW1_024")
    greenskin.play()
    observed = f"own_weapon={owner.weapon};enemy_weapon={enemy_axe.atk}/{enemy_axe.durability}"
    check(owner.weapon is None and (enemy_axe.atk, enemy_axe.durability) == (3, 2), observed)
    check(greenskin.zone == Zone.PLAY, observed)
    return observed


def bloodsail_corsair_breaks_enemy_weapon():
    game = game_for(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    own = owner.give("CS2_106")
    own.play()
    game.end_turn()
    enemy = opponent.give("CS2_106")
    enemy.play()
    enemy.hit(1)
    check(enemy.durability == 1, f"precondition_durability={enemy.durability}")
    game.end_turn()
    corsair = owner.give("NEW1_025")
    corsair.play()
    observed = f"own={own.zone.name}:{own.durability};enemy={enemy.zone.name};corsair={corsair.zone.name}"
    check(opponent.weapon is None and enemy.zone != Zone.PLAY, observed)
    check(owner.weapon is own and own.durability == 2 and corsair.zone == Zone.PLAY, observed)
    return observed


def bloodsail_corsair_removes_one_not_two():
    game = game_for(CardClass.WARRIOR)
    owner, opponent = game.player1, game.player2
    game.end_turn()
    enemy = opponent.give("CS2_106")
    enemy.play()
    game.end_turn()
    owner.give("NEW1_025").play()
    observed = f"enemy={enemy.zone.name}:{enemy.durability};owner_weapon={owner.weapon}"
    check(opponent.weapon is enemy and enemy.durability == 1, observed)
    return observed


def violet_teacher_own_spell_summons_apprentice():
    game = game_for()
    owner, opponent = game.player1, game.player2
    teacher = owner.give("NEW1_026")
    teacher.play()
    owner.give("CS2_024").play(target=opponent.hero)
    apprentices = [minion for minion in owner.field if minion.id == "NEW1_026t"]
    observed = f"field={[c.id for c in owner.field]};apprentices={[(c.atk,c.health) for c in apprentices]}"
    check(len(apprentices) == 1 and (apprentices[0].atk, apprentices[0].health) == (1, 1), observed)
    check(teacher.zone == Zone.PLAY and opponent.hero.health == 27, observed)
    return observed


def violet_teacher_enemy_spell_no_summon():
    game = game_for()
    owner, opponent = game.player1, game.player2
    teacher = owner.give("NEW1_026")
    teacher.play()
    game.end_turn()
    opponent.give("CS2_024").play(target=owner.hero)
    observed = f"friendly_field={[c.id for c in owner.field]};enemy_field={[c.id for c in opponent.field]}"
    check(len(owner.field) == 1 and owner.field[0] is teacher, observed)
    return observed


def violet_teacher_full_board_no_extra():
    game = game_for()
    owner, opponent = game.player1, game.player2
    teacher = owner.give("NEW1_026")
    teacher.play()
    for _ in range(6):
        owner.summon(WISP)
    owner.give("CS2_024").play(target=opponent.hero)
    observed = f"field_count={len(owner.field)};apprentices={[c.id for c in owner.field if c.id == 'NEW1_026t']}"
    check(len(owner.field) == 7 and not any(c.id == "NEW1_026t" for c in owner.field), observed)
    return observed


def southsea_captain_other_pirates_only_and_revert():
    game = game_for()
    owner = game.player1
    pirate = owner.summon("NEW1_018")
    neutral = owner.summon(WISP)
    captain = owner.give("NEW1_027")
    captain.play()
    during = (pirate.atk, pirate.health, neutral.atk, neutral.health, captain.atk, captain.health)
    check(during == (3, 4, 1, 1, 3, 3), f"during={during}")
    captain.destroy()
    after = (pirate.atk, pirate.health, neutral.atk, neutral.health, captain.zone.name)
    observed = f"during={during};after={after}"
    check(after == (2, 3, 1, 1, "GRAVEYARD"), observed)
    return observed


def southsea_captain_enemy_pirate_excluded():
    game = game_for()
    owner, opponent = game.player1, game.player2
    enemy_pirate = opponent.summon("NEW1_018")
    owner.give("NEW1_027").play()
    observed = f"enemy_pirate={enemy_pirate.atk}/{enemy_pirate.health}"
    check((enemy_pirate.atk, enemy_pirate.health) == (2, 3), observed)
    return observed


def millhouse_enemy_spells_free_for_one_turn():
    game = game_for()
    owner, opponent = game.player1, game.player2
    own_spell = owner.give("CS2_029")
    enemy_spell = opponent.give("CS2_029")
    enemy_minion = opponent.give("CS2_182")
    check((own_spell.cost, enemy_spell.cost, enemy_minion.cost) == (4, 4, 4),
          "precondition_costs_invalid")
    owner.give("NEW1_029").play()
    immediate = (own_spell.cost, enemy_spell.cost, enemy_minion.cost)
    check(immediate == (4, 0, 4), f"immediate={immediate}")
    game.end_turn()
    enemy_turn = enemy_spell.cost
    game.end_turn()
    expired = enemy_spell.cost
    observed = f"immediate={immediate};enemy_turn={enemy_turn};expired={expired}"
    check(enemy_turn == 0 and expired == 4, observed)
    return observed


def deathwing_destroys_others_and_discards_hand():
    game = game_for()
    owner, opponent = game.player1, game.player2
    ally = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    spare = owner.give("CS2_024")
    deathwing = owner.give("NEW1_030")
    deathwing.play()
    observed = (f"ally={ally.zone.name};enemy={enemy.zone.name};spare={spare.zone.name};"
                f"deathwing={deathwing.zone.name}:{deathwing.atk}/{deathwing.health};hand={len(owner.hand)}")
    check(ally.zone == enemy.zone == Zone.GRAVEYARD, observed)
    check(spare.zone == Zone.REMOVEDFROMGAME and len(owner.hand) == 0, observed)
    check(deathwing.zone == Zone.PLAY and (deathwing.atk, deathwing.health) == (12, 12), observed)
    return observed


def master_swordsmith_end_turn_other_friendly():
    game = game_for()
    owner, opponent = game.player1, game.player2
    smith = owner.give("NEW1_037")
    smith.play()
    ally = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    game.end_turn()
    observed = f"smith={smith.atk};ally={ally.atk};enemy={enemy.atk}"
    check(smith.atk == 1 and ally.atk == 5 and enemy.atk == 4, observed)
    game.end_turn()
    check(ally.atk == 5, f"buffed_on_enemy_turn={ally.atk}")
    return observed


def master_swordsmith_no_other_minion():
    game = game_for()
    smith = game.player1.give("NEW1_037")
    smith.play()
    game.end_turn()
    observed = f"smith={smith.zone.name}:{smith.atk}/{smith.health};field={len(game.player1.field)}"
    check(smith.zone == Zone.PLAY and smith.atk == 1, observed)
    return observed


def master_swordsmith_random_other_friendly_domain():
    reached = set()
    for seed in range(24):
        game = game_for()
        game.random.seed(seed)
        owner = game.player1
        smith = owner.give("NEW1_037")
        smith.play()
        first = owner.summon("CS2_182")
        second = owner.summon("CS2_168")
        before = (first.atk, second.atk, smith.atk)
        game.end_turn()
        changes = (first.atk-before[0], second.atk-before[1], smith.atk-before[2])
        check(changes in ((1, 0, 0), (0, 1, 0)), f"seed={seed};changes={changes}")
        reached.add(changes.index(1))
    observed = f"24 seeds; reached two other friendlies={sorted(reached)}"
    check(reached == {0, 1}, observed)
    return observed


def gruul_each_turn_end_and_no_early_buff():
    game = game_for()
    gruul = game.player1.give("NEW1_038")
    gruul.play()
    pre = (gruul.atk, gruul.health)
    game.end_turn()
    after_own = (gruul.atk, gruul.health)
    game.end_turn()
    after_enemy = (gruul.atk, gruul.health)
    observed = f"pre={pre};own_end={after_own};enemy_end={after_enemy}"
    check((pre, after_own, after_enemy) == ((7, 7), (8, 8), (9, 9)), observed)
    return observed


def hogger_own_end_turn_taunt_gnoll():
    game = game_for()
    owner = game.player1
    hogger = owner.give("NEW1_040")
    hogger.play()
    game.end_turn()
    gnolls = [c for c in owner.field if c.id == "NEW1_040t"]
    check(len(gnolls) == 1, f"first_end_field={[c.id for c in owner.field]}")
    gnoll = gnolls[0]
    observed = f"gnoll={gnoll.atk}/{gnoll.health}:taunt={gnoll.taunt}"
    check((gnoll.atk, gnoll.health, gnoll.taunt) == (2, 2, True), observed)
    game.end_turn()
    check(len([c for c in owner.field if c.id == "NEW1_040t"]) == 1,
          "extra_gnoll_on_enemy_end")
    return observed


def hogger_full_board_no_eighth_minion():
    game = game_for()
    owner = game.player1
    hogger = owner.give("NEW1_040")
    hogger.play()
    for _ in range(6):
        owner.summon(WISP)
    game.end_turn()
    observed = f"field_count={len(owner.field)};gnolls={[c.id for c in owner.field if c.id == 'NEW1_040t']}"
    check(len(owner.field) == 7 and not any(c.id == "NEW1_040t" for c in owner.field), observed)
    return observed


def stampeding_kodo_low_attack_only():
    game = game_for()
    owner, opponent = game.player1, game.player2
    low = opponent.summon(WISP)
    high = opponent.summon("CS2_182")
    friendly_low = owner.summon(WISP)
    kodo = owner.give("NEW1_041")
    kodo.play()
    observed = f"enemy_low={low.zone.name};enemy_high={high.zone.name};friendly_low={friendly_low.zone.name}"
    check(low.zone == Zone.GRAVEYARD and high.zone == Zone.PLAY, observed)
    check(friendly_low.zone == Zone.PLAY and kodo.zone == Zone.PLAY, observed)
    return observed


def stampeding_kodo_no_eligible_target():
    game = game_for()
    owner, opponent = game.player1, game.player2
    high = opponent.summon("CS2_182")
    kodo = owner.give("NEW1_041")
    kodo.play()
    observed = f"enemy_high={high.zone.name};kodo={kodo.zone.name}"
    check(high.zone == Zone.PLAY and kodo.zone == Zone.PLAY, observed)
    return observed


def stampeding_kodo_random_candidate_reachability():
    reached = set()
    for seed in range(24):
        game = game_for()
        game.random.seed(seed)
        owner, opponent = game.player1, game.player2
        a = opponent.summon("CS2_168")  # Murloc Raider, 2 Attack.
        b = opponent.summon("CS2_168")
        owner.give("NEW1_041").play()
        zones = (a.zone, b.zone)
        check(zones.count(Zone.GRAVEYARD) == 1, f"seed={seed};zones={[z.name for z in zones]}")
        reached.add(zones.index(Zone.GRAVEYARD))
    observed = f"24 seeds; reached indices={sorted(reached)}"
    check(reached == {0, 1}, observed)
    return observed


def flesheating_ghoul_both_sides_deaths_and_no_play_trigger():
    game = game_for()
    owner, opponent = game.player1, game.player2
    ghoul = owner.give("tt_004")
    ghoul.play()
    ally = owner.summon(WISP)
    enemy = opponent.summon(WISP)
    initial = ghoul.atk
    ally.destroy()
    enemy.destroy()
    observed = f"atk={initial}->{ghoul.atk};deaths={ally.zone.name},{enemy.zone.name}"
    check(initial == 2 and ghoul.atk == 4, observed)
    return observed


def flesheating_ghoul_no_buff_without_death():
    game = game_for()
    owner = game.player1
    ghoul = owner.give("tt_004")
    ghoul.play()
    owner.summon(WISP)
    observed = f"ghoul_atk={ghoul.atk};field={len(owner.field)}"
    check(ghoul.atk == 2 and len(owner.field) == 2, observed)
    return observed


def spellbender_redirect_enemy_targeted_spell():
    game = game_for()
    owner, opponent = game.player1, game.player2
    secret = owner.give("tt_010")
    secret.play()
    target = owner.summon("CS2_182")
    game.end_turn()
    opponent.give("CS2_008").play(target=target)  # Moonfire: one damage.
    tokens = [c for c in owner.field if c.id == "tt_010a"]
    observed = (f"secret={secret.zone.name};target={target.health};"
                f"tokens={[(c.atk,c.health,c.taunt) for c in tokens]}")
    check(secret not in owner.secrets and target.health == 5, observed)
    check(len(tokens) == 1 and (tokens[0].atk, tokens[0].health) == (1, 2), observed)
    return observed


def spellbender_hero_target_and_friendly_spell_excluded():
    game = game_for()
    owner, opponent = game.player1, game.player2
    secret = owner.give("tt_010")
    secret.play()
    friendly = owner.summon("CS2_182")
    owner.give("CS2_024").play(target=friendly)  # Friendly targeted spell does not trigger.
    check(secret in owner.secrets and friendly.health == 2,
          f"friendly_spell_secret={secret.zone.name};minion={friendly.health}")
    game.end_turn()
    opponent.give("CS2_008").play(target=owner.hero)
    observed = f"secret={secret.zone.name};hero={owner.hero.health};tokens={[c.id for c in owner.field]}"
    check(secret in owner.secrets and owner.hero.health == 29, observed)
    check(not any(c.id == "tt_010a" for c in owner.field), observed)
    return observed


def spellbender_full_board_preserves_secret():
    game = game_for()
    owner, opponent = game.player1, game.player2
    secret = owner.give("tt_010")
    secret.play()
    target = owner.summon("CS2_182")
    for _ in range(6):
        owner.summon(WISP)
    game.end_turn()
    opponent.give("CS2_008").play(target=target)
    observed = (f"secret={secret.zone.name};target_health={target.health};"
                f"field_count={len(owner.field)};token_count={sum(c.id=='tt_010a' for c in owner.field)}")
    check(secret in owner.secrets and target.health == 4, observed)
    check(len(owner.field) == 7 and not any(c.id == "tt_010a" for c in owner.field), observed)
    return observed


def commanding_shout_floor_and_draw():
    game = game_for(CardClass.WARRIOR)
    owner = game.player1
    owner.deck.clear()
    known = owner.card("CS2_182")
    known.zone = Zone.DECK
    ally = owner.summon("CS2_182")
    spell = owner.give("NEW1_036")
    before_hand = len(owner.hand)
    spell.play()
    # A large hit checks the protection independently of the draw clause.
    ally.hit(20)
    observed = (f"ally={ally.zone.name}:{ally.health};deck={len(owner.deck)};"
                f"hand={before_hand}->{len(owner.hand)};known={known.zone.name}")
    check(ally.zone == Zone.PLAY and ally.health == 1, observed)
    check(known.zone == Zone.HAND and len(owner.deck) == 0 and len(owner.hand) == before_hand + 1,
          observed)
    return observed


def main():
    record_card("NEW1_017", [
        ("NEW1_017_enemy_murloc_destroy_and_buff", "Enemy Murloc is destroyed; Crab gains +2/+2.", hungry_crab_enemy_murloc),
        ("NEW1_017_friendly_murloc_and_race_gate", "Friendly Murloc may be destroyed; non-Murloc is excluded.", hungry_crab_friendly_murloc_and_reject_nonmurloc),
        ("NEW1_017_no_murloc_optional_battlecry", "With no Murloc target, Crab is played as an unbuffed 1/2.", hungry_crab_no_murloc),
    ], "友敌鱼人均可作为战吼目标并被摧毁，螃蟹准确获得+2/+2；非鱼人非法；无鱼人时本体可无目标入场且保持1/2。")
    record_card("NEW1_018", [
        ("NEW1_018_owned_weapon_attack", "Own 3-Attack weapon grants +3 Attack to the 2/3 Raider.", bloodsail_raider_weapon),
        ("NEW1_018_enemy_weapon_excluded", "Enemy weapon without own weapon grants no Attack.", bloodsail_raider_no_own_weapon),
    ], "战吼读取己方武器攻击力并准确增攻；敌方武器不计入。")
    record_card("NEW1_019", [
        ("NEW1_019_friendly_summon_pings_enemy", "Friendly summon pings the sole enemy character exactly once; playing Juggler itself does not ping.", knife_juggler_friendly_summon),
        ("NEW1_019_enemy_summon_no_ping", "Enemy summon does not trigger the friendly Juggler.", knife_juggler_enemy_summon_excluded),
        ("NEW1_019_random_enemy_character_domain", "Across deterministic seeds each enemy character is a reachable random target, with exactly one point per summon.", knife_juggler_random_enemy_character_domain),
    ], "友方召唤后随机对敌方角色造成恰好1点，多个随机种子覆盖敌方英雄和两名随从；敌方召唤和本体入场不触发。")
    record_card("NEW1_020", [
        ("NEW1_020_own_spell_all_minions", "Own spell deals 1 to every friendly and enemy minion after its effect; heroes are not hit by Pyromancer.", wild_pyromancer_own_spell_all_minions),
        ("NEW1_020_enemy_spell_excluded", "Enemy spell does not trigger friendly Pyromancer.", wild_pyromancer_enemy_spell_no_trigger),
    ], "己方法术后对友敌所有随从各造成1点，排除英雄；敌方法术不触发。")
    record_card("NEW1_021", [
        ("NEW1_021_own_turn_start_wipe", "Doomsayer survives opponent's turn start, then destroys all minions at its owner's next turn start.", doomsayer_own_turn_begin),
    ], "在持有者下一回合开始消灭包括自身和双方其他随从；对手回合开始不触发。")
    record_card("NEW1_022", [
        ("NEW1_022_weapon_cost_and_taunt", "Own 3-Attack weapon discounts cost 4 to 1 and played Corsair has Taunt.", dread_corsair_weapon_cost_and_taunt),
        ("NEW1_022_change_and_enemy_weapon_excluded", "Own weapon loss restores printed cost; enemy weapon never discounts.", dread_corsair_weapon_change_and_enemy_excluded),
    ], "己方武器攻击力实时降低手牌费用，武器移除后复原；敌方武器不影响；入场嘲讽有效。")
    record_card("NEW1_023", [
        ("NEW1_023_spell_power_gate_battlecry_allowed", "Enemy spell and hero power cannot target Dragon, direct invalid cast is rejected, but Battlecry deals damage.", faerie_dragon_target_gate_and_battlecry),
    ], "敌方法术及英雄技能目标列表排除该牌，实际强行施法被拒；随从战吼仍可选中并造成伤害。")
    record_card("NEW1_024", [
        ("NEW1_024_own_weapon_plus_one_plus_one", "Battlecry gives equipped friendly weapon +1 Attack and +1 Durability.", captain_greenskin_own_weapon_buff),
        ("NEW1_024_enemy_weapon_excluded", "Enemy weapon unchanged if owner has none.", captain_greenskin_enemy_weapon_not_buffed),
    ], "战吼准确提高己方武器攻击与耐久各1；敌方武器无影响。")
    record_card("NEW1_025", [
        ("NEW1_025_break_one_durability_enemy_weapon", "Enemy one-Durability weapon breaks, friendly weapon remains untouched.", bloodsail_corsair_breaks_enemy_weapon),
        ("NEW1_025_remove_exactly_one", "Enemy two-Durability weapon remains equipped with one Durability.", bloodsail_corsair_removes_one_not_two),
    ], "敌方武器恰减1耐久：一耐久摧毁、二耐久保留；己方武器不受影响。")
    record_card("NEW1_026", [
        ("NEW1_026_own_spell_apprentice", "Own spell summons exactly one 1/1 Violet Apprentice.", violet_teacher_own_spell_summons_apprentice),
        ("NEW1_026_enemy_spell_excluded", "Enemy spell does not summon an apprentice for this Teacher.", violet_teacher_enemy_spell_no_summon),
        ("NEW1_026_full_board", "At seven friendly minions, spell cannot add an eighth apprentice.", violet_teacher_full_board_no_extra),
    ], "己方法术召唤恰好一个1/1学徒，敌方法术不触发，己方满场时不会超出七随从。")
    record_card("NEW1_027", [
        ("NEW1_027_friendly_other_pirate_aura_revert", "Only other friendly Pirates gain +1/+1; effect reverts when Captain dies.", southsea_captain_other_pirates_only_and_revert),
        ("NEW1_027_enemy_pirate_excluded", "Enemy Pirate is never buffed.", southsea_captain_enemy_pirate_excluded),
    ], "光环只增强其他友方海盗+1/+1，非海盗及敌方海盗不变；船长死亡后准确撤销。")
    record_card("NEW1_029", [
        ("NEW1_029_enemy_spell_zero_next_turn", "Enemy spells cost zero during enemy next turn only; own spells and enemy minions keep costs.", millhouse_enemy_spells_free_for_one_turn),
    ], "敌方下回合法术费用变0，随后恢复；己方法术及敌方随从费用不变。")
    record_card("NEW1_030", [
        ("NEW1_030_destroy_both_sides_discard_hand", "Battlecry destroys both sides' other minions and discards all own remaining hand; Deathwing survives as 12/12.", deathwing_destroys_others_and_discards_hand),
    ], "战吼消灭双方其他随从、弃掉己方余牌，自身12/12留场。")
    record_card("NEW1_037", [
        ("NEW1_037_end_turn_other_friendly", "Own turn end buffs only another friendly minion +1 Attack; enemy turn does not retrigger.", master_swordsmith_end_turn_other_friendly),
        ("NEW1_037_no_other_friendly", "With no other friendly minion, Swordsmith does not buff itself.", master_swordsmith_no_other_minion),
        ("NEW1_037_random_other_friendly_domain", "Both distinct other friendly minions are reachable random targets; exactly one gains +1 Attack per turn.", master_swordsmith_random_other_friendly_domain),
    ], "只在己方回合结束时使随机其他友方随从攻击+1；两种候选均可命中且一次只命中一个，无其他随从时不自我增益。")
    record_card("NEW1_038", [
        ("NEW1_038_both_turn_ends", "Gruul gains +1/+1 at each player's turn end, not on play.", gruul_each_turn_end_and_no_early_buff),
    ], "登场不立即增益，双方每次回合结束各准确获得+1/+1。")
    record_card("NEW1_040", [
        ("NEW1_040_own_turn_gnoll_taunt", "Own turn end summons exactly one 2/2 Taunt Gnoll; enemy end does not.", hogger_own_end_turn_taunt_gnoll),
        ("NEW1_040_full_board", "Full board blocks the Gnoll without creating an eighth minion.", hogger_full_board_no_eighth_minion),
    ], "己方回合结束召唤一个2/2嘲讽豺狼人，对方回合结束不触发；满场不越界。")
    record_card("NEW1_041", [
        ("NEW1_041_low_attack_enemy_only", "Kodo destroys only the eligible enemy minion; higher Attack enemy and friendly minion survive.", stampeding_kodo_low_attack_only),
        ("NEW1_041_no_eligible_enemy", "Without an enemy at 2 or less Attack, Kodo enters without a kill.", stampeding_kodo_no_eligible_target),
        ("NEW1_041_random_eligible_domain", "With two eligible enemies, exactly one dies and both are reachable over deterministic seeds.", stampeding_kodo_random_candidate_reachability),
    ], "战吼随机消灭恰好一个攻击≤2的敌方随从；友方/高攻排除，无合法目标可入场；种子覆盖双候选。")
    record_card("tt_004", [
        ("tt_004_both_sides_minion_deaths", "Ghoul gains +1 Attack per friendly or enemy minion death; no bonus on its own play.", flesheating_ghoul_both_sides_deaths_and_no_play_trigger),
        ("tt_004_summon_without_death", "Summoning another minion without a death does not buff Ghoul.", flesheating_ghoul_no_buff_without_death),
    ], "友敌随从各死亡一次后各加1攻击，共+2；单纯召唤不触发。")
    record_card("tt_010", [
        ("tt_010_enemy_minion_spell_redirect", "Enemy single-target minion spell is redirected to a summoned 1/3, leaving original target untouched.", spellbender_redirect_enemy_targeted_spell),
        ("tt_010_hero_and_friendly_spell_excluded", "Friendly targeted spell and enemy hero-targeted spell do not reveal Spellbender.", spellbender_hero_target_and_friendly_spell_excluded),
        ("tt_010_full_board_no_redirect", "With a full friendly board, enemy minion spell resolves on original target and Secret remains.", spellbender_full_board_preserves_secret),
    ], "敌方指向随从的法术转向新召唤的1/3且原目标不受伤；己方法术及指向英雄的敌方法术不触发；满场无法召唤时维持秘密。")
    record_card("NEW1_036", [
        ("NEW1_036_floor_and_draw", "Friendly minion survives lethal damage at 1 Health and the card draws the known deck card.", commanding_shout_floor_and_draw),
    ], "命令怒吼文本含本回合最低1血与抽牌；逐项实测。")


if __name__ == "__main__":
    main()
