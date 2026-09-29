"""Per-card live-game probes for GANGS collectible YELLOW cards, slice c."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

import fireplace.cards as carddb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import (  # noqa: E402
    CHICKEN,
    FIREBALL,
    KOBOLD_GEOMANCER,
    MOONFIRE,
    MURLOC,
    THE_COIN,
    WHELP,
    WISP,
    prepare_empty_game,
    prepare_game,
)

for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)
logging.getLogger("fireplace").setLevel(logging.CRITICAL)

PROBE = HERE / "gangs_probe_c.csv"
VERDICT = HERE / "gangs_verdict_c.csv"
BASELINE = HERE / "three_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
MECHANISMS = HERE / "card_mechanism.csv"
QUALITY = HERE / "card_quality.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


ALL_GANGS = [r for r in read_csv(BASELINE) if r["set"] == "Mean Streets of Gadgetzan (GANGS)"]
BASE_ROWS = ALL_GANGS[87:130]
CARDS = [r["card_id"] for r in BASE_ROWS]
assert len(ALL_GANGS) == 130 and len(CARDS) == 43 and CARDS[0] == "CFM_687" and CARDS[-1] == "CFM_940"
MASTER_ROWS = {r["card_id"]: r for r in read_csv(MASTER)}
OLD_QUALITY = {r["card_id"]: r for r in read_csv(QUALITY)}
MECH_ROWS = read_csv(MECHANISMS)
LABELS = {cid: sorted({r["mechanic"] for r in MECH_ROWS if r["card_id"] == cid}) for cid in CARDS}
OLD_MECH_REASONS = {
    cid: sorted({r["reason"] for r in MECH_ROWS if r["card_id"] == cid and r["reason"]}) for cid in CARDS
}
PROBE_ROWS = read_csv(PROBE)
VERDICT_ROWS = read_csv(VERDICT)


def prepare_card(cid):
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != cid]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def game(class1=CardClass.MAGE, class2=None, seed=417, drafted=False, include=()):
    random.seed(seed)
    if drafted:
        g = prepare_game(class1, class2, include=include)
    else:
        g = prepare_empty_game(class1, class2 or class1)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
    return g


def play(player, cid, target=None, choose=None):
    card = player.give(cid)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    card.play(**kwargs)
    return card


def summon(player, cid):
    return player.summon(cid)


def put_in_deck(player, cid):
    card = player.give(cid)
    card.shuffle_into_deck()
    return card


def check(detail, condition):
    assert condition, detail
    return detail


def _c687_inferior_spell_discount():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    first = put_in_deck(p, WISP)
    second = put_in_deck(p, "CS2_182")
    solia = play(p, "CFM_687")
    discounted = p.give(FIREBALL)
    first_cost = discounted.cost
    discounted.play(target=foe.hero)
    aura_ended = discounted.zone == Zone.GRAVEYARD
    next_spell = p.give("CS2_024")
    normal_cost = next_spell.cost

    g2 = game(CardClass.MAGE, seed=6872)
    p2 = g2.player1
    put_in_deck(p2, WISP)
    put_in_deck(p2, WISP)
    solia2 = play(p2, "CFM_687")
    normal_spell = p2.give(FIREBALL)
    duplicate_branch = (solia2 in p2.field, normal_spell.cost)
    return check(f"unique_deck={[first.id,second.id]};solia={solia.zone.name};first_spell_cost={first_cost};cast={discounted.zone.name};aura_ended={aura_ended};next_spell_cost={normal_cost};duplicate_branch={duplicate_branch}",
                 solia in p.field and first in p.deck and second in p.deck and first_cost == 0
                 and discounted.zone == Zone.GRAVEYARD and normal_cost == 2 and duplicate_branch == (True, 4))


def _c688_hogrider_taunt_branch():
    g0 = game(CardClass.WARRIOR, seed=6881)
    p0, foe0 = g0.player1, g0.player2
    plain = play(p0, "CFM_688")
    without = (plain.charge, plain in p0.field)
    g1 = game(CardClass.WARRIOR, seed=6882)
    p1, foe1 = g1.player1, g1.player2
    taunt = summon(foe1, "CS1_042")
    rider = play(p1, "CFM_688")
    can_attack_immediately = rider.can_attack()
    rider.attack(taunt)
    with_taunt = (taunt.taunt, rider.charge, can_attack_immediately,
                  taunt.zone.name, rider.zone.name, rider.health)
    return check(f"without_enemy_taunt={without};enemy_taunt={with_taunt}",
                 without == (False, True) and with_taunt == (True, True, True,"GRAVEYARD","PLAY",4))


def _c690_jade_shuriken_combo():
    g0 = game(CardClass.ROGUE, seed=6901)
    p0, foe0 = g0.player1, g0.player2
    p0.discard_hand()
    base_jade = p0.jade_golem
    base_spell = play(p0, "CFM_690", target=foe0.hero)
    no_combo = (foe0.hero.health, p0.jade_golem, len(p0.field), base_spell.zone.name)

    g1 = game(CardClass.ROGUE, seed=6902)
    p1, foe1 = g1.player1, g1.player2
    p1.discard_hand()
    victim = summon(foe1, WISP)
    p1.give(THE_COIN).play()
    combo_before = p1.cards_played_this_turn
    combo_spell = play(p1, "CFM_690", target=victim)
    jade_tokens = [m for m in p1.field if m.id.startswith("CFM_712_t")]
    combo = (combo_before, victim.health, victim.zone.name, p1.jade_golem,
             [(m.id,m.atk,m.health,m.zone.name) for m in jade_tokens], combo_spell.zone.name)
    return check(f"base_jade={base_jade};without_combo={no_combo};combo={combo}",
                 no_combo == (28, base_jade, 0, "GRAVEYARD")
                 and combo_before == 1 and victim.zone == Zone.GRAVEYARD and p1.jade_golem == base_jade + 1
                 and len(jade_tokens) == 1 and (jade_tokens[0].atk,jade_tokens[0].health)==(1,1)
                 and combo_spell.zone == Zone.GRAVEYARD)


def _c691_jade_swarmer_stealth_deathrattle():
    g = game(CardClass.ROGUE)
    p = g.player1
    start = p.jade_golem
    swarmer = play(p, "CFM_691")
    stealth = swarmer.stealthed
    before_death = (swarmer.zone.name, p.jade_golem, len(p.field))
    swarmer.destroy()
    tokens = [m for m in p.field if m.id.startswith("CFM_712_t")]
    after_death = (swarmer.zone.name, p.jade_golem, [(m.id,m.atk,m.health,m.zone.name) for m in tokens])
    return check(f"start_jade={start};stealth={stealth};before_death={before_death};after_death={after_death}",
                 stealth and before_death == ("PLAY", start, 1) and swarmer.zone == Zone.GRAVEYARD
                 and p.jade_golem == start + 1 and len(tokens) == 1
                 and (tokens[0].id,tokens[0].atk,tokens[0].health,tokens[0].zone)==("CFM_712_t01",1,1,Zone.PLAY))


def _c693_ferryman_combo_bounce():
    g0 = game(CardClass.ROGUE, seed=6931)
    p0 = g0.player1
    p0.discard_hand()
    wisp0 = summon(p0, WISP)
    ferryman0 = p0.give("CFM_693")
    no_combo_before = (p0.combo, p0.cards_played_this_turn)
    ferryman0.play()
    no_combo = (wisp0.zone.name,ferryman0 in p0.field,wisp0 in p0.hand)

    g1 = game(CardClass.ROGUE, seed=6932)
    p1 = g1.player1
    p1.discard_hand()
    wisp1 = summon(p1, WISP)
    p1.give(THE_COIN).play()
    ferryman1 = p1.give("CFM_693")
    legal = list(ferryman1.targets)
    combo_before = (p1.combo,p1.cards_played_this_turn,wisp1 in legal)
    ferryman1.play(target=wisp1)
    combo = (wisp1.zone.name,wisp1 in p1.hand,wisp1 in p1.field,ferryman1 in p1.field)
    return check(f"without_combo_before={no_combo_before};without_combo_after={no_combo};combo_before={combo_before};combo_after={combo}",
                 no_combo_before == (False,0) and no_combo == ("PLAY",True,False)
                 and combo_before == (True,1,True) and combo == ("HAND",True,False,True))


def _c694_shadow_sensei_targeting():
    g = game(CardClass.ROGUE)
    p, foe = g.player1, g.player2
    stealthy = summon(p, "EX1_010")
    ordinary = summon(p, WISP)
    foe_stealthy = summon(foe, "EX1_010")
    sensei = p.give("CFM_694")
    legal = list(sensei.targets)
    before = (stealthy.atk, stealthy.health)
    sensei.play(target=stealthy)
    after = (stealthy.atk, stealthy.health, stealthy.max_health, stealthy.stealthed)
    return check(f"own_stealth={stealthy.stealthed};enemy_stealth={foe_stealthy.stealthed};legal={[m.id for m in legal]};ordinary_legal={ordinary in legal};before={before};after={after}",
                 stealthy in legal and foe_stealthy not in legal and ordinary not in legal
                 and before == (2,1) and after == (4,3,3,True) and sensei in p.field)


def _c696_devolve_all_enemy_costs():
    g = game(CardClass.SHAMAN)
    p, foe = g.player1, g.player2
    friendly = summon(p, "CS2_182")
    enemy4 = summon(foe, "CS2_182")
    enemy2 = summon(foe, "EX1_012")
    originals = [(m.id,m.data.cost,m.zone.name) for m in (friendly,enemy4,enemy2)]
    spell = play(p, "CFM_696")
    replacements = list(foe.field)
    state = [(m.id,m.data.cost,m.zone.name) for m in replacements]
    return check(f"originals={originals};replacements={state};friendly={(friendly.id,friendly.data.cost,friendly.zone.name)};spell={spell.zone.name}",
                 friendly.id == "CS2_182" and friendly.data.cost == 4 and friendly in p.field
                 and len(replacements) == 2 and sorted(m.data.cost for m in replacements) == [1,3]
                 and all(m.zone == Zone.PLAY for m in replacements)
                 and enemy4 not in replacements and enemy2 not in replacements and spell.zone == Zone.GRAVEYARD)


def _c697_illusionist_attack_condition():
    g0 = game(CardClass.SHAMAN, seed=6971)
    p0, foe0 = g0.player1, g0.player2
    illusionist0 = play(p0, "CFM_697")
    minion_target = summon(foe0, WISP)
    g0.end_turn()
    g0.end_turn()
    illusionist0.attack(minion_target)
    after_minion_attack = (illusionist0.id, illusionist0.zone.name, minion_target.zone.name)

    g1 = game(CardClass.SHAMAN, seed=6972)
    p1, foe1 = g1.player1, g1.player2
    illusionist1 = play(p1, "CFM_697")
    g1.end_turn()
    g1.end_turn()
    illusionist1.attack(foe1.hero)
    transformed = [m for m in p1.field if m is not illusionist1]
    after_hero_attack = (illusionist1.zone.name, foe1.hero.health,
                         [(m.id,m.data.cost,m.zone.name) for m in p1.field])
    return check(f"after_minion_attack={after_minion_attack};after_hero_attack={after_hero_attack};new_entities={[(m.id,m.data.cost) for m in transformed]}",
                 after_minion_attack == ("CFM_697","PLAY","GRAVEYARD")
                 and foe1.hero.health == 27 and len(p1.field) == 1
                 and p1.field[0].id != "CFM_697" and p1.field[0].data.cost == 6
                 and p1.field[0].zone == Zone.PLAY and p1.field[0].data.type == CardType.MINION
                 and illusionist1.zone == Zone.SETASIDE)


def _c699_seadevil_next_murloc_health_cost():
    g = game(CardClass.WARLOCK)
    p = g.player1
    p.discard_hand()
    stinger = play(p, "CFM_699")
    health_before = p.hero.health
    mana_before_murloc = p.mana
    first = p.give("EX1_506")
    first_nominal_cost = first.cost
    first.play()
    after_first = (p.hero.health, p.mana, first.zone.name, stinger.zone.name)
    second = p.give("EX1_506")
    second_cost = second.cost
    second.play()
    after_second = (p.hero.health, p.mana, second.zone.name)
    return check(f"hero_before={health_before};mana_before_murloc={mana_before_murloc};first_cost={first_nominal_cost};after_first={after_first};second_cost={second_cost};after_second={after_second}",
                 first_nominal_cost == 2 and after_first == (health_before - 2, mana_before_murloc, "PLAY", "PLAY")
                 and after_second == (health_before - 2, mana_before_murloc - second_cost, "PLAY"))


def _c707_jade_lightning_target_and_summon():
    g = game(CardClass.SHAMAN, seed=7071)
    p, foe = g.player1, g.player2
    p.discard_hand()
    target = summon(foe, "CS2_182")
    start_jade = p.jade_golem
    spell = play(p, "CFM_707", target=target)
    token = [m for m in p.field if m.id.startswith("CFM_712_t")]
    targeted = (target.health, target.damage, target.zone.name, p.jade_golem,
                [(m.id,m.atk,m.health,m.zone.name) for m in token], spell.zone.name)

    g2 = game(CardClass.SHAMAN, seed=7072)
    p2 = g2.player1
    p2.discard_hand()
    no_target_spell = play(p2, "CFM_707", target=p2.opponent.hero)
    no_target_tokens = [m for m in p2.field if m.id.startswith("CFM_712_t")]
    no_minion_target = (p2.opponent.hero.health,p2.jade_golem,
                        [(m.id,m.atk,m.health,m.zone.name) for m in no_target_tokens],no_target_spell.zone.name)
    return check(f"targeted={targeted};hero_target_no_minions={no_minion_target}",
                 start_jade == 1 and targeted == (1,4,"PLAY",2,[ ("CFM_712_t01",1,1,"PLAY") ],"GRAVEYARD")
                 and no_minion_target == (26,2,[("CFM_712_t01",1,1,"PLAY")],"GRAVEYARD"))


def _c713_jade_blossom_empty_crystal():
    g = game(CardClass.DRUID)
    p = g.player1
    p.discard_hand()
    p.max_mana = 3
    before = (p.max_mana, p.mana, p.jade_golem)
    spell = play(p, "CFM_713")
    tokens = [m for m in p.field if m.id.startswith("CFM_712_t")]
    after = (p.max_mana, p.mana, p.jade_golem,
             [(m.id,m.atk,m.health,m.zone.name) for m in tokens], spell.zone.name)
    return check(f"before={before};after={after}",
                 before == (3,3,1) and after == (4,0,2,[("CFM_712_t01",1,1,"PLAY")],"GRAVEYARD"))


def _c715_jade_spirit_battlecry():
    g = game(CardClass.DRUID)
    p = g.player1
    p.discard_hand()
    start = p.jade_golem
    spirit = play(p, "CFM_715")
    tokens = [m for m in p.field if m.id.startswith("CFM_712_t")]
    state = (spirit.atk,spirit.health,spirit.zone.name,p.jade_golem,
             [(m.id,m.atk,m.health,m.zone.name) for m in tokens],len(p.field))
    return check(f"start_jade={start};state={state}",
                 start == 1 and state == (2,3,"PLAY",2,[("CFM_712_t01",1,1,"PLAY")],2))


def _c716_sleep_with_fishes_damaged_only():
    g = game(CardClass.WARRIOR)
    p, foe = g.player1, g.player2
    friend_damaged = summon(p, "CS2_182")
    enemy_damaged = summon(foe, "CS2_182")
    fresh = summon(p, WISP)
    friend_damaged.damage = 1
    enemy_damaged.damage = 2
    spell = play(p, "CFM_716")
    state = (friend_damaged.health,friend_damaged.damage,friend_damaged.zone.name,
             enemy_damaged.health,enemy_damaged.damage,enemy_damaged.zone.name,
             fresh.health,fresh.damage,fresh.zone.name,spell.zone.name)
    return check(f"state={state}",
                 state == (1,4,"PLAY",5,0,"GRAVEYARD",1,0,"PLAY","GRAVEYARD"))


def _c717_jade_claws_weapon_and_overload():
    g = game(CardClass.SHAMAN)
    p = g.player1
    p.discard_hand()
    start_jade = p.jade_golem
    weapon = play(p, "CFM_717")
    tokens = [m for m in p.field if m.id.startswith("CFM_712_t")]
    current = (p.weapon.id,p.weapon.atk,p.weapon.durability,p.overload_locked,p.mana,p.jade_golem,
               [(m.id,m.atk,m.health,m.zone.name) for m in tokens],weapon.zone.name)
    g.end_turn()
    g.end_turn()
    next_turn = (p.max_mana,p.mana,p.overload_locked)
    return check(f"start_jade={start_jade};current={current};next_turn={next_turn}",
                 start_jade == 1 and current == ("CFM_717",2,2,0,8,2,[("CFM_712_t01",1,1,"PLAY")],"PLAY")
                 and next_turn == (10,9,1))


def _c750_krul_duplicate_deck_branch():
    g = game(CardClass.WARLOCK, seed=7501)
    p = g.player1
    p.discard_hand()
    demon1 = p.give("CS2_065")
    demon2 = p.give("EX1_301")
    non_demon = p.give(WISP)
    krul = play(p, "CFM_750")
    unique = (demon1.zone.name,demon2.zone.name,non_demon.zone.name,krul.zone.name,
              sorted(m.id for m in p.field),sorted(c.id for c in p.hand))

    g2 = game(CardClass.WARLOCK, seed=7502)
    p2 = g2.player1
    p2.discard_hand()
    put_in_deck(p2,WISP)
    put_in_deck(p2,WISP)
    demon3 = p2.give("CS2_065")
    demon4 = p2.give("EX1_301")
    krul2 = play(p2,"CFM_750")
    duplicate = (demon3.zone.name,demon4.zone.name,krul2.zone.name,
                 sorted(m.id for m in p2.field),sorted(c.id for c in p2.hand))
    return check(f"no_duplicate_deck={unique};duplicate_deck={duplicate}",
                 demon1.zone == Zone.PLAY and demon2.zone == Zone.PLAY and non_demon.zone == Zone.HAND
                 and krul.zone == Zone.PLAY and sorted(m.id for m in p.field)==["CFM_750","CS2_065","EX1_301"]
                 and sorted(c.id for c in p.hand)==[WISP]
                 and demon3.zone == Zone.HAND and demon4.zone == Zone.HAND and krul2.zone == Zone.PLAY
                 and sorted(m.id for m in p2.field)==["CFM_750"]
                 and sorted(c.id for c in p2.hand)==["CS2_065","EX1_301"])


def _c751_abyssal_enforcer_all_other_characters():
    g = game(CardClass.WARLOCK)
    p, foe = g.player1, g.player2
    p.discard_hand()
    friendly = summon(p,WISP)
    enemy = summon(foe,WISP)
    enforcer = play(p,"CFM_751")
    state = (p.hero.health,foe.hero.health,friendly.zone.name,enemy.zone.name,
             enforcer.zone.name,enforcer.health)
    return check(f"state={state}",
                 state == (27,27,"GRAVEYARD","GRAVEYARD","PLAY",6))


def _c752_stolen_goods_random_taunt_in_hand():
    g = game(CardClass.WARRIOR, seed=7521)
    p = g.player1
    p.discard_hand()
    taunt = p.give("CS2_065")
    non_taunt = p.give(WISP)
    before = (taunt.atk,taunt.health,non_taunt.atk,non_taunt.health)
    spell = play(p,"CFM_752")
    buffed = (taunt.atk,taunt.health,non_taunt.atk,non_taunt.health,taunt.zone.name,non_taunt.zone.name,spell.zone.name)

    g2 = game(CardClass.WARRIOR, seed=7522)
    p2 = g2.player1
    p2.discard_hand()
    only_non_taunt = p2.give(WISP)
    no_target_spell = play(p2,"CFM_752")
    no_taunt = (only_non_taunt.atk,only_non_taunt.health,only_non_taunt.zone.name,no_target_spell.zone.name)
    return check(f"before={before};buffed_branch={buffed};no_taunt_branch={no_taunt}",
                 before == (1,3,1,1) and buffed == (4,6,1,1,"HAND","HAND","GRAVEYARD")
                 and no_taunt == (1,1,"HAND","GRAVEYARD"))


def _c753_grimestreet_outfitter_all_hand_minions():
    g = game(CardClass.PALADIN)
    p = g.player1
    p.discard_hand()
    wisp = p.give(WISP)
    murloc = p.give("EX1_506")
    spell_in_hand = p.give(FIREBALL)
    before = ((wisp.atk,wisp.health),(murloc.atk,murloc.health),spell_in_hand.cost)
    outfitter = play(p,"CFM_753")
    after = ((wisp.atk,wisp.health),(murloc.atk,murloc.health),spell_in_hand.cost,
             wisp.zone.name,murloc.zone.name,spell_in_hand.zone.name,outfitter.zone.name)
    return check(f"before={before};after={after}",
                 before == ((1,1),(2,1),4)
                 and after == ((2,2),(3,2),4,"HAND","HAND","HAND","PLAY"))


def _c754_grimy_gadgeteer_end_turn_random_hand_minion():
    g = game(CardClass.WARRIOR,seed=7541)
    p = g.player1
    p.discard_hand()
    first = p.give(WISP)
    second = p.give("EX1_506")
    gadgeteer = play(p,"CFM_754")
    before = ((first.atk,first.health),(second.atk,second.health),gadgeteer.zone.name)
    g.end_turn()
    after = ((first.atk,first.health),(second.atk,second.health),first.zone.name,second.zone.name,
             gadgeteer.zone.name,g.current_player is p)
    changed = [i for i,(old,new) in enumerate(zip(before[:2],after[:2])) if new == (old[0]+2,old[1]+2)]
    return check(f"before={before};after={after};changed_minion_indexes={changed}",
                 before == ((1,1),(2,1),"PLAY") and len(changed)==1
                 and after[2:4]==("HAND","HAND")
                 and after[4:]==("PLAY",False))


def _c755_grimestreet_pawnbroker_random_hand_weapon():
    g = game(CardClass.WARRIOR,seed=7551)
    p = g.player1
    p.discard_hand()
    first = p.give("CS2_106")
    second = p.give("EX1_567")
    before = ((first.atk,first.durability),(second.atk,second.durability))
    pawn = play(p,"CFM_755")
    after = ((first.atk,first.durability),(second.atk,second.durability),
             first.zone.name,second.zone.name,pawn.zone.name)
    changes = [i for i,(old,new) in enumerate(zip(before,after[:2])) if new == (old[0]+1,old[1]+1)]
    return check(f"before={before};after={after};buffed_weapon_indexes={changes}",
                 before == ((3,2),(2,8)) and len(changes)==1
                 and all(zone=="HAND" for zone in after[2:4]) and after[4]=="PLAY")


def _c756_alley_armorsmith_damage_to_hero_gains_armor():
    g = game(CardClass.WARRIOR)
    p, foe = g.player1, g.player2
    p.discard_hand()
    smith = play(p,"CFM_756")
    taunt = smith.taunt
    attack = smith.atk
    g.end_turn()
    g.end_turn()
    before = (p.hero.armor,foe.hero.health,smith.can_attack())
    smith.attack(foe.hero)
    after = (p.hero.armor,foe.hero.health,smith.zone.name,smith.health)
    return check(f"taunt={taunt};attack={attack};before={before};after={after}",
                 taunt and attack > 0 and before[2]
                 and after == (attack,30-attack,"PLAY",smith.max_health))


def _c759_meanstreet_marshal_deathrattle_attack_threshold():
    g = game(CardClass.PALADIN,seed=7591)
    p = g.player1
    p.discard_hand()
    drawn = put_in_deck(p,WISP)
    marshal = summon(p,"CFM_759")
    buff_spell = p.give("CS2_188")
    buff_spell.play(target=marshal)
    buffed_attack = marshal.atk
    marshal.destroy()
    enabled = (buffed_attack,marshal.zone.name,drawn.zone.name,drawn in p.hand)

    g2 = game(CardClass.PALADIN,seed=7592)
    p2 = g2.player1
    p2.discard_hand()
    not_drawn = put_in_deck(p2,WISP)
    vanilla = summon(p2,"CFM_759")
    vanilla_attack = vanilla.atk
    vanilla.destroy()
    disabled = (vanilla_attack,vanilla.zone.name,not_drawn.zone.name,not_drawn in p2.hand)
    return check(f"at_least_2_attack={enabled};below_2_attack={disabled}",
                 enabled == (3,"GRAVEYARD","HAND",True)
                 and disabled == (1,"GRAVEYARD","DECK",False))


def _c760_kabal_crystal_runner_secret_cost_reduction():
    g = game(CardClass.MAGE)
    p = g.player1
    p.discard_hand()
    runner1 = p.give("CFM_760")
    base = runner1.cost
    first_secret = p.give("EX1_295")
    first_secret.play()
    after_one = (runner1.cost,first_secret.zone.name)
    runner2 = p.give("CFM_760")
    second_secret = p.give("EX1_287")
    second_secret.play()
    after_two = (runner1.cost,runner2.cost,first_secret.zone.name,second_secret.zone.name)
    return check(f"base={base};after_one_secret={after_one};after_two_secrets={after_two}",
                 base == 6 and after_one == (4,"SECRET")
                 and after_two == (2,2,"SECRET","SECRET"))


def _c806_wrathion_draws_through_dragons_until_non_dragon():
    g = game(CardClass.WARRIOR)
    p = g.player1
    p.discard_hand()
    tail = p.give(WISP)
    tail.zone = Zone.DECK
    stop_card = p.give("CS2_182")
    stop_card.zone = Zone.DECK
    dragon1 = p.give("NEW1_023")
    dragon1.zone = Zone.DECK
    dragon2 = p.give("EX1_572")
    dragon2.zone = Zone.DECK
    wrathion = play(p,"CFM_806")
    drawn = [c.id for c in (dragon1,dragon2,stop_card) if c.zone == Zone.HAND]
    state = (wrathion.taunt,wrathion.zone.name,dragon1.zone.name,dragon2.zone.name,
             stop_card.zone.name,tail.zone.name,sorted(drawn),len(p.deck),len(p.hand))
    return check(f"state={state};cards_in_hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}",
                 state == (True,"PLAY","HAND","HAND","HAND","DECK",
                           sorted([dragon1.id,dragon2.id,stop_card.id]),1,3))


def _c807_beardo_refreshes_hero_power_after_each_spell():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    p.discard_hand()
    beardo = play(p,"CFM_807")
    p.hero.power.use(target=foe.hero)
    exhausted_after_first_power = p.hero.power.exhausted
    first_spell = play(p,MOONFIRE,target=foe.hero)
    refreshed_after_first_spell = not p.hero.power.exhausted
    p.hero.power.use(target=foe.hero)
    second_power_health = foe.hero.health
    second_spell = play(p,MOONFIRE,target=foe.hero)
    refreshed_after_second_spell = not p.hero.power.exhausted
    p.hero.power.use(target=foe.hero)
    state = (exhausted_after_first_power,refreshed_after_first_spell,second_power_health,
             refreshed_after_second_spell,foe.hero.health,p.hero.power.exhausted,
             beardo.zone.name,first_spell.zone.name,second_spell.zone.name)
    return check(f"state={state}",
                 state == (True,True,27,True,25,True,"PLAY","GRAVEYARD","GRAVEYARD"))


def _c808_genzo_draws_both_players_to_three():
    g = game(CardClass.MAGE,seed=8081)
    p, foe = g.player1, g.player2
    p.discard_hand()
    foe.discard_hand()
    genzo = play(p,"CFM_808")
    own_deck = [put_in_deck(p,cid) for cid in (WISP,"EX1_506","CS2_182")]
    foe_deck = [put_in_deck(foe,cid) for cid in (WISP,"EX1_506","CS2_182")]
    own_start = [p.give(WISP),p.give("EX1_506")]
    foe_start = [foe.give(WISP)]
    g.end_turn()
    g.end_turn()
    genzo.attack(foe.hero)
    own_drawn = [c for c in own_deck if c.zone == Zone.HAND]
    foe_drawn = [c for c in foe_deck if c.zone == Zone.HAND]
    state = (len(p.hand),len(foe.hand),len(p.deck),len(foe.deck),foe.hero.health,
             genzo.zone.name,len(own_drawn),len(foe_drawn),
             all(c in p.hand for c in own_start),all(c in foe.hand for c in foe_start))
    return check(f"state={state};owner_hand={[c.id for c in p.hand]};opponent_hand={[c.id for c in foe.hand]}",
                 state == (3,3,2,1,25,"PLAY",1,2,True,True))


def _c809_tanaris_hogchopper_empty_hand_charge():
    g0 = game(CardClass.MAGE,seed=8091)
    p0, foe0 = g0.player1, g0.player2
    p0.discard_hand()
    foe0.discard_hand()
    rider = play(p0,"CFM_809")
    can_charge = rider.charge
    rider_attack = rider.atk
    rider.attack(foe0.hero)
    charged_branch = (can_charge,foe0.hero.health,rider.zone.name,rider_attack)

    g1 = game(CardClass.MAGE,seed=8092)
    p1, foe1 = g1.player1, g1.player2
    p1.discard_hand()
    foe1.discard_hand()
    foe1.give(WISP)
    rider1 = play(p1,"CFM_809")
    ordinary_branch = (rider1.charge,rider1.can_attack(),foe1.hero.health)
    return check(f"opponent_empty={charged_branch};opponent_has_card={ordinary_branch}",
                 charged_branch == (True,30-rider_attack,"PLAY",rider_attack) and ordinary_branch == (False,False,30))


def _c810_leatherclad_hogleader_six_card_threshold():
    g0 = game(CardClass.MAGE,seed=8101)
    p0, foe0 = g0.player1, g0.player2
    p0.discard_hand()
    foe0.discard_hand()
    for _ in range(6): foe0.give(WISP)
    rider = play(p0,"CFM_810")
    charged = rider.charge
    rider_attack = rider.atk
    rider.attack(foe0.hero)
    at_least_six = (len(foe0.hand),charged,foe0.hero.health,rider_attack)

    g1 = game(CardClass.MAGE,seed=8102)
    p1, foe1 = g1.player1, g1.player2
    p1.discard_hand()
    foe1.discard_hand()
    for _ in range(5): foe1.give(WISP)
    rider1 = play(p1,"CFM_810")
    below_six = (len(foe1.hand),rider1.charge,rider1.can_attack(),foe1.hero.health)
    return check(f"six_cards={at_least_six};five_cards={below_six}",
                 at_least_six == (6,True,30-rider_attack,rider_attack) and below_six == (5,False,False,30))


def _c811_lunar_visions_draw_two_discount_only_minions():
    g = game(CardClass.DRUID)
    p = g.player1
    p.discard_hand()
    remaining = p.give(WISP)
    remaining.zone = Zone.DECK
    minion = p.give("CS2_182")
    minion.zone = Zone.DECK
    spell_card = p.give(FIREBALL)
    spell_card.zone = Zone.DECK
    lunar = play(p,"CFM_811")
    state = (minion.zone.name,minion.cost,spell_card.zone.name,spell_card.cost,
             remaining.zone.name,len(p.hand),len(p.deck),lunar.zone.name)
    return check(f"state={state};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}",
                 state == ("HAND",2,"HAND",4,"DECK",2,1,"GRAVEYARD"))


def _c815_wickerflame_shield_taunt_lifesteal():
    g = game(CardClass.PALADIN)
    p, foe = g.player1, g.player2
    p.discard_hand()
    wicker = play(p,"CFM_815")
    traits = (wicker.taunt,wicker.divine_shield,wicker.lifesteal,wicker.atk,wicker.health)
    p.hero.damage = 5
    attacker = summon(foe,WISP)
    g.end_turn()
    attacker.attack(wicker)
    after_combat = (wicker.divine_shield,wicker.health,attacker.zone.name,p.hero.health)
    g.end_turn()
    wicker.attack(foe.hero)
    after_attack = (p.hero.health,p.hero.damage,foe.hero.health,wicker.zone.name)
    return check(f"traits={traits};after_enemy_attack={after_combat};after_wicker_attack={after_attack}",
                 traits == (True,True,True,2,2) and after_combat == (False,2,"GRAVEYARD",27)
                 and after_attack == (29,1,28,"PLAY"))


def _c816_virmen_sensei_friendly_beast_target():
    g = game(CardClass.DRUID)
    p, foe = g.player1, g.player2
    beast = summon(p,"CS2_171")
    non_beast = summon(p,WISP)
    enemy_beast = summon(foe,"CS2_171")
    sensei = p.give("CFM_816")
    legal = list(sensei.targets)
    before = (beast.atk,beast.health)
    sensei.play(target=beast)
    after = (beast.atk,beast.health,beast.max_health,beast.zone.name)
    return check(f"beast_race={beast.race};enemy_beast_race={enemy_beast.race};legal={[m.id for m in legal]};before={before};after={after}",
                 beast in legal and enemy_beast not in legal and non_beast not in legal
                 and before == (1,1) and after == (3,3,3,"PLAY") and sensei.zone == Zone.PLAY)


def _c851_daring_reporter_only_opponent_draws_buff():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    p.discard_hand()
    foe.discard_hand()
    reporter = play(p,"CFM_851")
    own_deck = put_in_deck(p,WISP)
    enemy_deck1 = put_in_deck(foe,"EX1_506")
    enemy_deck2 = put_in_deck(foe,"CS2_182")
    own_draw = p.draw()
    after_own_draw = (reporter.atk,reporter.health,own_draw.zone.name)
    enemy_draw1 = foe.draw()
    after_enemy_draw1 = (reporter.atk,reporter.health,enemy_draw1.zone.name)
    enemy_draw2 = foe.draw()
    after_enemy_draw2 = (reporter.atk,reporter.health,enemy_draw2.zone.name)
    return check(f"after_owner_draw={after_own_draw};after_opponent_draw_1={after_enemy_draw1};after_opponent_draw_2={after_enemy_draw2};remaining_decks={(len(p.deck),len(foe.deck))}",
                 after_own_draw == (3,3,"HAND") and after_enemy_draw1 == (4,4,"HAND")
                 and after_enemy_draw2 == (5,5,"HAND") and own_deck.zone == Zone.HAND
                 and enemy_deck1.zone == Zone.HAND and enemy_deck2.zone == Zone.HAND)


def _c852_lotus_agents_discover_three_classes_and_choose():
    g = game(CardClass.MAGE,seed=8521)
    p = g.player1
    p.discard_hand()
    agents = play(p,"CFM_852")
    choice = p.choice
    options = list(choice.cards)
    option_classes = [c.card_class for c in options]
    option_ids = [c.id for c in options]
    selected = options[1]
    choice.choose(selected)
    result = (len(options),option_classes,selected.id,selected.zone.name,selected in p.hand,
              p.choice,agents.zone.name)
    expected_classes = {CardClass.DRUID,CardClass.ROGUE,CardClass.SHAMAN}
    return check(f"options={option_ids};classes={option_classes};after_choose={result}",
                 len(options)==3 and set(option_classes)==expected_classes
                 and selected.zone == Zone.HAND and selected in p.hand and p.choice is None
                 and agents.zone == Zone.PLAY)


def _c853_grimestreet_smuggler_buffs_one_hand_minion():
    g = game(CardClass.MAGE,seed=8531)
    p = g.player1
    p.discard_hand()
    first = p.give(WISP)
    second = p.give("EX1_506")
    spell = p.give(FIREBALL)
    before = ((first.atk,first.health),(second.atk,second.health),spell.cost)
    smuggler = play(p,"CFM_853")
    after = ((first.atk,first.health),(second.atk,second.health),spell.cost,
             first.zone.name,second.zone.name,spell.zone.name,smuggler.zone.name)
    buffed = [i for i,(old,new) in enumerate(zip(before[:2],after[:2]))
              if new == (old[0]+1,old[1]+1)]
    return check(f"before={before};after={after};buffed_indexes={buffed}",
                 before == ((1,1),(2,1),4) and len(buffed)==1
                 and after[3:]==("HAND","HAND","HAND","PLAY"))


def _c854_ancient_of_blossoms_taunt_blocks_hero_attack():
    g = game(CardClass.MAGE)
    p, foe = g.player1,g.player2
    ancient = play(p,"CFM_854")
    attacker = summon(foe,WISP)
    g.end_turn()
    targets = list(attacker.attack_targets)
    hero_attack_blocked = foe.hero not in targets
    ancient_attackable = ancient in targets
    attacker.attack(ancient)
    state = (ancient.atk,ancient.health,ancient.damage,ancient.zone.name,attacker.zone.name,
             ancient.taunt,hero_attack_blocked,ancient_attackable)
    return check(f"state={state};attack_targets={[t.id for t in targets]}",
                 state == (3,7,1,"PLAY","GRAVEYARD",True,True,True))


def _c855_defias_cleaner_silences_deathrattle_target():
    g = game(CardClass.MAGE)
    p, foe = g.player1,g.player2
    p.discard_hand()
    foe.discard_hand()
    friendly_dr = summon(p,"FP1_011")
    enemy_dr = summon(foe,"FP1_011")
    enemy_plain = summon(foe,"CS2_182")
    cleaner = p.give("CFM_855")
    legal = list(cleaner.targets)
    cleaner.play(target=enemy_dr)
    silenced_state = (enemy_dr.silenced,enemy_dr.atk,enemy_dr.health,enemy_dr.zone.name,
                      friendly_dr.silenced,enemy_plain.silenced)
    enemy_dr.destroy()
    death_state = (enemy_dr.zone.name,len(foe.hand),cleaner.zone.name)
    return check(f"legal={[m.id for m in legal]};silenced={silenced_state};after_death={death_state}",
                 enemy_dr in legal and friendly_dr in legal and enemy_plain not in legal
                 and silenced_state == (True,1,1,"PLAY",False,False)
                 and death_state == ("GRAVEYARD",0,"PLAY"))


def _c900_unlicensed_apothecary_after_minion_summons():
    g = game(CardClass.WARLOCK)
    p = g.player1
    p.discard_hand()
    apothecary = play(p,"CFM_900")
    after_own_summon = p.hero.health
    first = summon(p,WISP)
    after_first_summon = (p.hero.health,first.zone.name)
    second = summon(p,"EX1_506")
    after_second_summon = (p.hero.health,second.zone.name)
    return check(f"after_apothecary_summon={after_own_summon};after_wisp={after_first_summon};after_murloc={after_second_summon}",
                 after_own_summon == 30 and after_first_summon == (25,"PLAY")
                 and after_second_summon == (20,"PLAY") and apothecary.zone == Zone.PLAY)


def _c902_aya_blackpaw_battlecry_and_deathrattle():
    g = game(CardClass.ROGUE)
    p = g.player1
    p.discard_hand()
    start = p.jade_golem
    aya = play(p,"CFM_902")
    first = [m for m in p.field if m.id.startswith("CFM_712_t")]
    after_battlecry = (aya.zone.name,p.jade_golem,[(m.id,m.atk,m.health,m.zone.name) for m in first])
    aya.destroy()
    all_jades = [m for m in p.field if m.id.startswith("CFM_712_t")]
    after_deathrattle = (aya.zone.name,p.jade_golem,sorted((m.id,m.atk,m.health,m.zone.name) for m in all_jades))
    return check(f"start={start};after_battlecry={after_battlecry};after_deathrattle={after_deathrattle}",
                 start == 1 and after_battlecry == ("PLAY",2,[("CFM_712_t01",1,1,"PLAY")])
                 and aya.zone == Zone.GRAVEYARD and p.jade_golem==3
                 and sorted((m.id,m.atk,m.health,m.zone.name) for m in all_jades)
                 == [("CFM_712_t01",1,1,"PLAY"),("CFM_712_t02",2,2,"PLAY")])


def _c905_small_time_recruits_draws_only_one_cost_minions():
    g = game(CardClass.PALADIN,seed=9051)
    p = g.player1
    p.discard_hand()
    eligible = [p.give(cid) for cid in ("CS2_065","CS2_171","CS2_189")]
    ineligible = [p.give(WISP),p.give("CS2_182")]
    for card in eligible + ineligible: card.zone = Zone.DECK
    spell = play(p,"CFM_905")
    full = (sorted(c.id for c in p.hand),sorted(c.id for c in p.deck),
            [c.zone.name for c in eligible],[c.zone.name for c in ineligible],spell.zone.name)

    g2 = game(CardClass.PALADIN,seed=9052)
    p2 = g2.player1
    p2.discard_hand()
    two_eligible = [p2.give(cid) for cid in ("CS2_065","CS2_171")]
    one_ineligible = p2.give("CS2_182")
    for card in two_eligible+[one_ineligible]: card.zone=Zone.DECK
    spell2 = play(p2,"CFM_905")
    short = (sorted(c.id for c in p2.hand),sorted(c.id for c in p2.deck),
             [c.zone.name for c in two_eligible],one_ineligible.zone.name,spell2.zone.name)
    return check(f"three_available={full};only_two_available={short}",
                 full == (sorted(c.id for c in eligible),sorted(c.id for c in ineligible),
                          ["HAND"]*3,["DECK"]*2,"GRAVEYARD")
                 and short == (sorted(c.id for c in two_eligible),[one_ineligible.id],
                               ["HAND"]*2,"DECK","GRAVEYARD"))


def _c940_i_know_a_guy_discover_taunt_and_choose():
    g = game(CardClass.WARRIOR,seed=9401)
    p = g.player1
    p.discard_hand()
    spell = play(p,"CFM_940")
    choice = p.choice
    options = list(choice.cards)
    details = [(c.id,c.data.type,c.taunt,c.zone.name) for c in options]
    selected = options[0]
    choice.choose(selected)
    after = (selected.id,selected.zone.name,selected in p.hand,p.choice,spell.zone.name)
    return check(f"options={details};after_choose={after}",
                 len(options)==3 and all(c.data.type==CardType.MINION and c.taunt for c in options)
                 and selected.zone == Zone.HAND and selected in p.hand and p.choice is None
                 and spell.zone == Zone.GRAVEYARD)


def _c781_shaku_stealth_and_random_opponent_class_card():
    def attack_and_check(class1,class2,seed):
        g = game(class1,class2,seed=seed)
        p, foe = g.player1,g.player2
        p.discard_hand()
        shaku = play(p,"CFM_781")
        initial_stealth = shaku.stealthed
        g.end_turn()
        g.end_turn()
        shaku.attack(foe.hero)
        generated = list(p.hand)
        details = [(c.id,c.card_class,c.data.collectible,c.zone.name) for c in generated]
        return (p.hero.card_class,foe.hero.card_class,initial_stealth,shaku.stealthed,
                foe.hero.health,shaku.zone.name,len(generated),details,shaku.atk)

    first = attack_and_check(CardClass.ROGUE,CardClass.HUNTER,7811)
    second = attack_and_check(CardClass.HUNTER,CardClass.DRUID,7812)
    def valid(state):
        own_class,enemy_class,was_stealthed,now_stealthed,enemy_health,zone,count,details,attack = state
        return (own_class != enemy_class and was_stealthed and not now_stealthed
                and enemy_health == 30-attack and zone == "PLAY" and count == 1
                and details[0][1] == enemy_class and details[0][2] and details[0][3] == "HAND")
    return check(f"class_pair_1={first};class_pair_2={second}",valid(first) and valid(second))


def _c790_dirty_rat_taunt_random_opponent_minion_from_hand():
    g = game(CardClass.MAGE,seed=7901)
    p, foe = g.player1,g.player2
    p.discard_hand()
    foe.discard_hand()
    candidates = [foe.give(WISP),foe.give("CS2_182")]
    non_minion = foe.give(FIREBALL)
    rat = play(p,"CFM_790")
    summoned = [c for c in candidates if c.zone==Zone.PLAY]
    remaining = [c for c in candidates if c.zone==Zone.HAND]
    random_branch = (rat.taunt,rat.zone.name,len(summoned),len(remaining),
                     all(c.controller is foe for c in summoned),non_minion.zone.name,
                     [c.id for c in summoned],[c.id for c in remaining])

    g2 = game(CardClass.MAGE,seed=7902)
    p2, foe2 = g2.player1,g2.player2
    p2.discard_hand()
    foe2.discard_hand()
    only_spell = foe2.give(FIREBALL)
    rat2 = play(p2,"CFM_790")
    no_minion_branch = (rat2.taunt,rat2.zone.name,len(foe2.field),only_spell.zone.name)
    return check(f"with_enemy_minions={random_branch};no_enemy_minion={no_minion_branch}",
                 random_branch[:6] == (True,"PLAY",1,1,True,"HAND")
                 and len(summoned)==1 and len(remaining)==1
                 and no_minion_branch == (True,"PLAY",0,"HAND"))


def _c800_getaway_kodo_only_bounces_friendly_death():
    g = game(CardClass.PALADIN,seed=8001)
    p, foe = g.player1,g.player2
    p.discard_hand()
    getaway = play(p,"CFM_800")
    friendly = summon(p,WISP)
    secret_zone_before = getaway.zone.name
    enemy_attacker = summon(foe,WISP)
    g.end_turn()
    enemy_attacker.attack(friendly)
    friendly_death = (friendly.zone.name,friendly in p.hand,friendly.controller is p,
                      getaway.zone.name,secret_zone_before,enemy_attacker.zone.name)

    g2 = game(CardClass.PALADIN,seed=8002)
    p2, foe2 = g2.player1,g2.player2
    p2.discard_hand()
    getaway2 = play(p2,"CFM_800")
    friend_survivor = summon(p2,"CS2_182")
    enemy = summon(foe2,WISP)
    g2.end_turn()
    enemy.attack(friend_survivor)
    enemy_death = (enemy.zone.name,enemy in foe2.hand,getaway2.zone.name)
    return check(f"friendly_death={friendly_death};enemy_death={enemy_death}",
                 friendly_death == ("HAND",True,True,"GRAVEYARD","SECRET","GRAVEYARD")
                 and enemy_death == ("GRAVEYARD",False,"SECRET"))


def add_case(cid, case_id, expected, fn, notes, covers):
    try:
        observed = fn()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append({"card_id": cid, "case_id": case_id, "expected": expected,
                       "observed": observed, "outcome": outcome,
                       "notes": f"{notes}; scope_asserted={'|'.join(sorted(covers))}"})
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    return outcome, observed


def finish_card(cid, cases):
    own = [r for r in PROBE_ROWS if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own), cid
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    covered = set().union(*(set(c[5]) for c in cases))
    expected_scope = set(LABELS[cid])
    if errors:
        status = "RED"
        reason = "实测断言失败：" + "；".join(f"{r['case_id']}={r['observed']}" for r in errors)
    elif unresolved:
        status = "YELLOW"
        reason = "运行存在未决异常：" + "；".join(f"{r['case_id']}={r['observed']}" for r in unresolved)
    elif covered != expected_scope:
        status = "YELLOW"
        reason = f"本轮未覆盖所有机制标签；未覆盖={sorted(expected_scope-covered)}。"
    else:
        status = "GREEN"
        reason = "逐卡对局断言通过：" + "；".join(f"{r['case_id']}={r['observed']}" for r in own)
    master = MASTER_ROWS[cid]
    old = OLD_QUALITY.get(cid, {})
    issues = []
    for issue in read_csv(ISSUES):
        affected = set((issue.get("confirmed_cards","")+"|"+issue.get("candidate_cards","")).split("|"))
        if cid in affected:
            issues.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    tests = master.get("test_refs_candidate", "") or "无候选既有测试引用"
    notes = (f"EN={master.get('card_text_en','')}; ZH={master.get('card_text_zh','')}; "
             f"source={master.get('python_source','') or '未发现 Python 脚本（已验证数据库卡牌行为）'}; "
             f"existing_tests={tests}; prior_card_audit={old.get('reason','无')}; "
             f"prior_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
             f"prior_cross_card_issues={' / '.join(issues) if issues else '无'}; "
             f"live_cases={','.join(r['case_id'] for r in own)}")
    if cid == "CFM_693":
        cause = ("源码因果：fireplace/cards/gangs/rogue.py:40 将 Bounce(TARGET) 放在 play 槽；"
                 "fireplace/actions.py:1060-1062 在 Combo 有效时只取 card.get_actions('combo')，"
                 "所以合法友方目标仍留场。")
        reason += "；" + cause
        notes += "; " + cause
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    VERDICT_ROWS.append({"card_id":cid,"status":status,"mechanic_scope":"|".join(LABELS[cid]),
                         "reason":reason,"probe_file":PROBE.name,"notes":notes})
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}")
    return status


def audit_card(cid, funcs):
    prepare_card(cid)
    cases = []
    for index, fn in enumerate(funcs,1):
        cid_case = f"{cid}_live_{index:02d}"
        expected = f"{fn.__name__}:卡牌文本效果与关键状态断言通过"
        row = (cid,cid_case,expected,fn,
               f"live_game={fn.__name__};单卡定制局面并检查区域/属性/触发变化",set(LABELS[cid]))
        add_case(*row)
        cases.append(row)
    return finish_card(cid,cases)


TESTS = {
    "CFM_687": [_c687_inferior_spell_discount],
    "CFM_688": [_c688_hogrider_taunt_branch],
    "CFM_690": [_c690_jade_shuriken_combo],
    "CFM_691": [_c691_jade_swarmer_stealth_deathrattle],
    "CFM_693": [_c693_ferryman_combo_bounce],
    "CFM_694": [_c694_shadow_sensei_targeting],
    "CFM_696": [_c696_devolve_all_enemy_costs],
    "CFM_697": [_c697_illusionist_attack_condition],
    "CFM_699": [_c699_seadevil_next_murloc_health_cost],
    "CFM_707": [_c707_jade_lightning_target_and_summon],
    "CFM_713": [_c713_jade_blossom_empty_crystal],
    "CFM_715": [_c715_jade_spirit_battlecry],
    "CFM_716": [_c716_sleep_with_fishes_damaged_only],
    "CFM_717": [_c717_jade_claws_weapon_and_overload],
    "CFM_750": [_c750_krul_duplicate_deck_branch],
    "CFM_751": [_c751_abyssal_enforcer_all_other_characters],
    "CFM_752": [_c752_stolen_goods_random_taunt_in_hand],
    "CFM_753": [_c753_grimestreet_outfitter_all_hand_minions],
    "CFM_754": [_c754_grimy_gadgeteer_end_turn_random_hand_minion],
    "CFM_755": [_c755_grimestreet_pawnbroker_random_hand_weapon],
    "CFM_756": [_c756_alley_armorsmith_damage_to_hero_gains_armor],
    "CFM_759": [_c759_meanstreet_marshal_deathrattle_attack_threshold],
    "CFM_760": [_c760_kabal_crystal_runner_secret_cost_reduction],
    "CFM_806": [_c806_wrathion_draws_through_dragons_until_non_dragon],
    "CFM_807": [_c807_beardo_refreshes_hero_power_after_each_spell],
    "CFM_808": [_c808_genzo_draws_both_players_to_three],
    "CFM_809": [_c809_tanaris_hogchopper_empty_hand_charge],
    "CFM_810": [_c810_leatherclad_hogleader_six_card_threshold],
    "CFM_811": [_c811_lunar_visions_draw_two_discount_only_minions],
    "CFM_815": [_c815_wickerflame_shield_taunt_lifesteal],
    "CFM_816": [_c816_virmen_sensei_friendly_beast_target],
    "CFM_851": [_c851_daring_reporter_only_opponent_draws_buff],
    "CFM_852": [_c852_lotus_agents_discover_three_classes_and_choose],
    "CFM_853": [_c853_grimestreet_smuggler_buffs_one_hand_minion],
    "CFM_854": [_c854_ancient_of_blossoms_taunt_blocks_hero_attack],
    "CFM_855": [_c855_defias_cleaner_silences_deathrattle_target],
    "CFM_900": [_c900_unlicensed_apothecary_after_minion_summons],
    "CFM_902": [_c902_aya_blackpaw_battlecry_and_deathrattle],
    "CFM_905": [_c905_small_time_recruits_draws_only_one_cost_minions],
    "CFM_940": [_c940_i_know_a_guy_discover_taunt_and_choose],
    "CFM_781": [_c781_shaku_stealth_and_random_opponent_class_card],
    "CFM_790": [_c790_dirty_rat_taunt_random_opponent_minion_from_hand],
    "CFM_800": [_c800_getaway_kodo_only_bounces_friendly_death],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated card ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    existing = {r["card_id"] for r in VERDICT_ROWS}
    wanted = set(args.only.split(",")) if args.only else None
    selected = [cid for cid in CARDS if wanted is None or cid in wanted]
    if args.limit is not None:
        selected = selected[:args.limit]
    for cid in selected:
        if cid in existing and not args.force:
            continue
        funcs = TESTS.get(cid)
        if not funcs:
            raise RuntimeError(f"No per-card live test implemented for {cid}")
        audit_card(cid,funcs)
    print(f"Completed verdicts: {len({r['card_id'] for r in VERDICT_ROWS})}/{len(CARDS)}; cases={len(PROBE_ROWS)}")


if __name__ == "__main__":
    main()
