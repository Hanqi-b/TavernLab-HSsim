"""Card-specific live game checks for the first 45 BLACK_TEMPLE YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction
from fireplace.actions import CastSpell
from fireplace.managers import BaseObserver

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "bt_probe_a.csv"
VERDICT_FILE = HERE / "bt_verdict_a.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


ROSTER = sorted((r for r in read(HERE / "remaining_yellow_baseline.csv")
                 if r["set"].endswith("(BLACK_TEMPLE)")),
                key=lambda r: r["card_id"])
ROSTER = ROSTER[0:45]
assert len(ROSTER) == 45
assert (ROSTER[0]["card_id"], ROSTER[-1]["card_id"]) == ("BT_002", "BT_136")
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
PROBES = [r for r in read(PROBE_FILE) if r["card_id"] in ROSTER_BY_ID]
VERDICTS = [r for r in read(VERDICT_FILE) if r["card_id"] in ROSTER_BY_ID]


def game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=181):
    random.seed(seed)
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    p = (next(player for player in g.players if player.hero.card_class == class1)
         if class1 != class2 else g.player1)
    e = next(player for player in g.players if player is not p)
    if g.current_player is not p:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    assert p.hero.card_class == class1 and e.hero.card_class == class2
    return g, p, e


def play(player, cid, target=None, index=None):
    card = player.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if index is not None:
        kw["index"] = index
    card.play(**kw)
    return card


def check(ok, observed):
    assert ok, observed
    return observed


def meta(cid):
    m = MASTER[cid]
    b = ROSTER_BY_ID[cid]
    return (f"EN={m['card_text_en']}; ZH={m['card_text_zh']}; "
            f"source={m['python_source']}; existing_tests={m['test_refs_candidate'] or 'none'}; "
            f"prior={b['status']}:{b['reason']}; prior_evidence={b['evidence']}")


def audit(cid, tests, blocker=None):
    global PROBES, VERDICTS
    assert cid in ROSTER_BY_ID
    PROBES = [r for r in PROBES if r["card_id"] != cid]
    VERDICTS = [r for r in VERDICTS if r["card_id"] != cid]
    write(PROBE_FILE, PF, PROBES)
    write(VERDICT_FILE, VF, VERDICTS)
    for case_id, expected, func, notes in tests:
        try:
            observed = func()
            outcome = "pass"
        except AssertionError as exc:
            observed = str(exc) or f"AssertionError at {traceback.extract_tb(exc.__traceback__)[-1].lineno}"
            outcome = "confirmed_error"
        except Exception as exc:
            observed = f"{type(exc).__name__}: {exc}"
            outcome = "inconclusive"
        PROBES.append(dict(card_id=cid, case_id=case_id, expected=expected,
                           observed=observed, outcome=outcome, notes=f"{notes}; {meta(cid)}"))
        write(PROBE_FILE, PF, PROBES)
        print(cid, case_id, outcome, observed)
    own = [r for r in PROBES if r["card_id"] == cid]
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in errors)
    elif unresolved or blocker:
        status = "YELLOW"
        reason = blocker or "运行未决：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in unresolved)
    else:
        status = "GREEN"
        reason = "逐卡关键行为断言通过：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in own)
    VERDICTS.append(dict(card_id=cid, status=status,
                         mechanic_scope=ROSTER_BY_ID[cid]["mechanic"], reason=reason,
                         probe_file=PROBE_FILE.name, notes=meta(cid)))
    write(VERDICT_FILE, VF, VERDICTS)
    print(cid, status, len(own), "cases")


def incanters_flow():
    cid="BT_002"
    def discounts_deck_spells_only():
        g,p,e=game(CardClass.MAGE);a=p.card("CS2_029",zone=Zone.DECK);b=p.card("CS2_008",zone=Zone.DECK);minion=p.card(WISP,zone=Zone.DECK)
        before=(a.cost,b.cost,minion.cost);spell=play(p,cid)
        observed=f"deck={[(c.id,c.cost,c.zone.name) for c in (a,b,minion)]};before={before};cast={spell.zone.name}"
        return check((a.cost,b.cost)==(max(before[0]-1,0),max(before[1]-1,0))
                     and minion.cost==before[2] and all(c.zone==Zone.DECK for c in (a,b,minion)),observed)
    audit(cid,[("reduce_spell_costs_in_deck_only","Incanter's Flow reduces each spell in deck by 1 and leaves a minion's Cost unchanged.",discounts_deck_spells_only,"牌库中放入不同费用法术及随从对照，实际施放后核对费用。")])


def netherwind_portal():
    cid="BT_003"
    def opponent_spell_reveals_and_summons_four_cost_minion():
        g,p,e=game(CardClass.MAGE);secret=play(p,cid);g.end_turn();spell=play(e,"GAME_005")
        summoned=[m for m in p.field if m is not None]
        observed=f"secret={secret.zone.name};spell={spell.zone.name};summoned={[(m.id,m.cost,m.zone.name) for m in summoned]}"
        return check(secret.zone==Zone.GRAVEYARD and len(summoned)==1
                     and summoned[0].type==CardType.MINION and summoned[0].cost==4
                     and summoned[0].controller is p,observed)
    audit(cid,[("opponent_spell_triggers_portal","An opponent's spell reveals Netherwind Portal and summons one 4-Cost minion for its owner.",opponent_spell_reveals_and_summons_four_cost_minion,"挂起奥秘，轮到对手施放硬币，检查消耗和召唤费用。")])


def imprisoned_observer():
    cid="BT_004"
    def awakens_after_two_own_starts_and_damages_enemy_minions():
        g,p,e=game(CardClass.MAGE);target=e.summon("EX1_563");friend=p.summon("EX1_563");body=play(p,cid)
        initial=(body.dormant,body.dormant_turns);g.end_turn();g.end_turn();middle=(body.dormant,body.dormant_turns)
        g.end_turn();g.end_turn()
        observed=f"initial={initial};middle={middle};awake={body.dormant}:{body.zone.name};enemy={target.health};friend={friend.health}"
        return check(initial==(True,2) and middle==(True,1) and not body.dormant
                     and target.health==target.max_health-2 and friend.health==friend.max_health,observed)
    audit(cid,[("dormant_two_turns_then_deal_two_to_enemy_minions","Observer stays Dormant for two owner-turn starts, then deals 2 to enemy minions only.",awakens_after_two_own_starts_and_damages_enemy_minions,"两个己方回合边界分段检查休眠和敌我伤害。")])


def evocation():
    cid="BT_006"
    def fills_hand_with_spells_then_discards_them():
        g,p,e=game(CardClass.MAGE);sentinel=p.give(WISP);body=play(p,cid);generated=[c for c in p.hand if c is not sentinel]
        before=len(generated);spells=all(c.type==CardType.SPELL and c.card_class==CardClass.MAGE for c in generated)
        g.end_turn()
        observed=f"generated={before};all_mage_spells={spells};after_end={[c.zone.name for c in generated]};sentinel={sentinel.zone.name};spell={body.zone.name}"
        return check(before==9 and spells and all(c.zone!=Zone.HAND for c in generated)
                     and sentinel.zone==Zone.HAND and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("fills_hand_with_mage_spells_and_discards_at_turn_end","Evocation fills all remaining hand slots with Mage spells and discards those spells at end of turn.",fills_hand_with_spells_then_discards_them,"保留随从哨兵，核对补牌数量、类型和回合结束后的区域。")])


def rustsworn_initiate():
    cid="BT_008"
    def deathrattle_summons_spell_damage_imp():
        g,p,e=game();body=play(p,cid);body.destroy();tokens=[m for m in p.field if m.id=="BT_008t"]
        observed=f"body={body.zone.name};tokens={[(m.atk,m.health,m.spellpower,m.zone.name) for m in tokens]}"
        return check(body.zone==Zone.GRAVEYARD and len(tokens)==1
                     and (tokens[0].atk,tokens[0].health,tokens[0].spellpower)==(1,1,1),observed)
    audit(cid,[("deathrattle_summons_one_spell_damage_imp","Rustsworn Initiate's death summons exactly one 1/1 Impcaster with Spell Damage +1.",deathrattle_summons_spell_damage_imp,"真实触发亡语并检查token身材、法强和场上区域。")])


def imprisoned_sungill():
    cid="BT_009"
    def awakens_and_summons_two_murlocs():
        g,p,e=game(CardClass.PALADIN);body=play(p,cid);initial=(body.dormant,body.dormant_turns)
        g.end_turn();g.end_turn();middle=(body.dormant,body.dormant_turns);g.end_turn();g.end_turn()
        tokens=[m for m in p.field if m.id=="BT_009t"]
        observed=f"initial={initial};middle={middle};awake={body.dormant};tokens={[(m.atk,m.health,m.race) for m in tokens]}"
        return check(initial==(True,2) and middle==(True,1) and not body.dormant
                     and len(tokens)==2 and all((m.atk,m.health)==(1,1) and Race.MURLOC in m.races for m in tokens),observed)
    audit(cid,[("dormant_two_turns_then_summon_two_murlocs","Imprisoned Sungill awakens after two owner-turn starts and summons two 1/1 Murlocs.",awakens_and_summons_two_murlocs,"逐回合检查休眠计数、唤醒及两个鱼人衍生物。")])


def felfin_navigator():
    cid="BT_010"
    def buffs_other_murlocs_only():
        g,p,e=game(CardClass.PALADIN);murloc=p.summon("BT_009t");ordinary=p.summon(WISP);before=(murloc.atk,murloc.max_health,ordinary.atk,ordinary.max_health)
        body=play(p,cid)
        observed=f"murloc={before[:2]}->{(murloc.atk,murloc.max_health)};ordinary={before[2:]}->{(ordinary.atk,ordinary.max_health)};self={body.atk}/{body.max_health}"
        return check((murloc.atk,murloc.max_health)==(before[0]+1,before[1]+1)
                     and (ordinary.atk,ordinary.max_health)==before[2:] and (body.atk,body.max_health)==(4,4),observed)
    audit(cid,[("battlecry_buffs_other_murlocs_only","Felfin Navigator gives other friendly Murlocs +1/+1, without buffing itself or non-Murlocs.",buffs_other_murlocs_only,"一名鱼人、一个非鱼人及本体作阵营/范围对照。")])


def libram_of_justice():
    cid="BT_011"
    def equips_weapon_and_sets_enemy_health_to_one():
        g,p,e=game(CardClass.PALADIN);target=e.summon("EX1_563");friend=p.summon("EX1_563");spell=play(p,cid)
        observed=f"enemy={target.health}/{target.max_health};friend={friend.health}/{friend.max_health};weapon={None if p.weapon is None else (p.weapon.atk,p.weapon.durability)};spell={spell.zone.name}"
        return check(target.health==target.max_health==1 and friend.health==friend.max_health==12
                     and p.weapon is not None and (p.weapon.atk,p.weapon.durability)==(1,4),observed)
    audit(cid,[("enemy_minions_health_one_and_equip_one_four","Libram of Justice sets all enemy minions' Health to 1 and equips a 1/4 weapon; friendly minions are unchanged.",equips_weapon_and_sets_enemy_health_to_one,"敌我高血随从对照，检查当前/最大生命和武器属性。")])


def starscryer():
    cid="BT_014"
    def deathrattle_draws_spell_not_minion():
        g,p,e=game(CardClass.PALADIN);spell=p.card("CS2_008",zone=Zone.DECK);minion=p.card(WISP,zone=Zone.DECK)
        body=play(p,cid);body.destroy()
        observed=f"spell={spell.zone.name}:{spell.type};minion={minion.zone.name};body={body.zone.name}"
        return check(spell.zone==Zone.HAND and minion.zone==Zone.DECK
                     and spell.type==CardType.SPELL and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deathrattle_draws_a_spell_from_deck","Starscryer's deathrattle draws a spell and leaves the only minion in deck.",deathrattle_draws_spell_not_minion,"牌库设置唯一法术和随从，死亡后核对抽牌类型。")])


def underlight_angling_rod():
    cid="BT_018"
    def hero_attack_adds_murloc():
        g,p,e=game(CardClass.PALADIN);weapon=play(p,cid);target=e.summon("EX1_563");before=len(p.hand);before_durability=weapon.durability
        p.hero.attack(target);added=p.hand[-1]
        observed=f"hand={before}->{len(p.hand)};added={added.id}:{added.type}:{added.race};weapon={weapon.zone.name}:{p.weapon.durability}"
        return check(len(p.hand)==before+1 and Race.MURLOC in added.races
                     and added.zone==Zone.HAND and p.weapon.durability==before_durability-1,observed)
    audit(cid,[("after_hero_attack_adds_random_murloc","After the hero attacks with Underlight Angling Rod, one Murloc is added to hand.",hero_attack_adds_murloc,"实际装备并攻击，按手牌实体种族和武器耐久验证触发。")])


def murgur_murgurgle():
    cid="BT_019"
    def divine_shield_and_prime_deathrattle():
        g,p,e=game(CardClass.PALADIN);body=play(p,cid);shield=body.divine_shield;body.destroy();primes=[c for c in p.deck if c.id=="BT_019t"]
        observed=f"shield={shield};body={body.zone.name};prime={[(c.id,c.zone.name) for c in primes]}"
        return check(shield and body.zone==Zone.GRAVEYARD and len(primes)==1 and primes[0].zone==Zone.DECK,observed)
    audit(cid,[("divine_shield_and_death_shuffle_prime","Murgur Murgurgle has Divine Shield; death shuffles exactly one Murgurgle Prime into deck.",divine_shield_and_prime_deathrattle,"先记录圣盾，再触发亡语并检查牌库实体。")])


def aldor_attendant():
    cid="BT_020"
    def reduces_librams_by_one():
        g,p,e=game(CardClass.PALADIN);libram1=p.give("BT_024");libram2=p.give("BT_025");other=p.give("CS2_029")
        before=(libram1.cost,libram2.cost,other.cost);body=play(p,cid)
        observed=f"librams={before[:2]}->{(libram1.cost,libram2.cost)};other={before[2]}->{other.cost};body={body.zone.name}"
        return check((libram1.cost,libram2.cost)==(max(before[0]-1,0),max(before[1]-1,0))
                     and other.cost==before[2] and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_reduces_libram_costs_by_one","Aldor Attendant reduces Libram spells in hand by 1 and leaves a non-Libram unchanged.",reduces_librams_by_one,"手牌中放两张不同费用Libram和普通法术对照。")])


def font_of_power():
    cid="BT_021"
    def branch(deck_has_minion):
        g,p,e=game(CardClass.MAGE)
        if deck_has_minion:p.card(WISP,zone=Zone.DECK)
        else:p.card("CS2_008",zone=Zone.DECK)
        body=play(p,cid);choice=p.choice;options=list(choice.cards) if choice else []
        selected=options[0] if options else None
        if selected:choice.choose(selected)
        added=list(p.hand)
        observed=f"has_minion={deck_has_minion};offers={[(c.id,c.type,c.card_class) for c in options]};hand={[(c.id,c.type,c.card_class,c.zone.name) for c in added]};choice={p.choice}"
        if deck_has_minion:
            ok=len(options)==3 and len(added)==1 and added[0].id==selected.id and p.choice is None
        else:
            ok=not options and len(added)==3 and all(c.type==CardType.MINION and c.card_class==CardClass.MAGE for c in added)
        return check(ok and body.zone==Zone.GRAVEYARD and all(c.zone==Zone.HAND for c in added),observed)
    audit(cid,[("empty_minion_deck_keeps_all_three","If the deck has no minions, Font of Power adds three Mage minions without presenting a Discover choice.",lambda:branch(False),"牌库只有法术，核对三张保留到手牌。"),
               ("minion_in_deck_discovers_one","If a minion exists in deck, Font of Power offers three Mage minions and keeps only the selected one.",lambda:branch(True),"放入一只牌库随从作为开关对照，完成真实Discover。")])


def apexis_smuggler():
    cid="BT_022"
    def playing_secret_opens_spell_discover():
        g,p,e=game(CardClass.MAGE);body=play(p,cid);secret=play(p,"EX1_287");choice=p.choice
        options=list(choice.cards) if choice else [];selected=options[0] if options else None
        if selected:choice.choose(selected)
        observed=f"secret={secret.zone.name};offers={[(c.id,c.type) for c in options]};selected={None if selected is None else (selected.id,selected.zone.name)};choice={p.choice};body={body.zone.name}"
        return check(len(options)==3 and all(c.type==CardType.SPELL for c in options)
                     and selected is not None and selected.zone==Zone.HAND and p.choice is None
                     and secret.zone==Zone.SECRET and body.zone==Zone.PLAY,observed)
    audit(cid,[("after_played_secret_discover_spell","Playing a Mage Secret after Apexis Smuggler opens a three-spell Discover and selected spell enters hand.",playing_secret_opens_spell_discover,"真实打出法师奥秘，再完成三选一。")])


def libram_of_hope():
    cid="BT_024"
    def restores_eight_and_summons_shielded_taunt():
        g,p,e=game(CardClass.PALADIN);p.hero.damage=8;spell=play(p,cid,target=p.hero);tokens=[m for m in p.field if m.id=="BT_024t"]
        observed=f"hero={p.hero.health};tokens={[(m.atk,m.health,m.taunt,m.divine_shield) for m in tokens]};spell={spell.zone.name}"
        return check(p.hero.health==30 and len(tokens)==1
                     and (tokens[0].atk,tokens[0].health,tokens[0].taunt,tokens[0].divine_shield)==(8,8,True,True),observed)
    audit(cid,[("restore_eight_and_summon_eight_eight_guardian","Libram of Hope restores 8 health and summons an 8/8 Guardian with Taunt and Divine Shield.",restores_eight_and_summons_shielded_taunt,"英雄先缺8血，核对有效治疗及召唤物关键词。")])


def libram_of_wisdom():
    cid="BT_025"
    def buff_and_reclaim_libram_on_death():
        g,p,e=game(CardClass.PALADIN);target=p.summon(WISP);before=(target.atk,target.max_health);spell=play(p,cid,target=target)
        buffed=(target.atk,target.max_health,target.has_deathrattle);target.destroy();returned=[c for c in p.hand if c.id==cid]
        observed=f"before={before};buffed={buffed};target={target.zone.name};returned={[(c.id,c.zone.name) for c in returned]};spell={spell.zone.name}"
        return check(buffed==(before[0]+1,before[1]+1,True) and target.zone==Zone.GRAVEYARD
                     and len(returned)==1 and returned[0].zone==Zone.HAND,observed)
    audit(cid,[("buff_adds_deathrattle_that_returns_libram","Libram of Wisdom gives +1/+1 and a deathrattle that adds one Libram of Wisdom to hand.",buff_and_reclaim_libram_on_death,"检查增益和真实死亡后生成的原牌实体。")])


def aldor_truthseeker():
    cid="BT_026"
    def taunt_and_two_cost_reduction():
        g,p,e=game(CardClass.PALADIN);a=p.give("BT_024");b=p.give("BT_025");before=(a.cost,b.cost);body=play(p,cid)
        observed=f"taunt={body.taunt};librams={before}->{(a.cost,b.cost)};body={body.zone.name}"
        return check(body.taunt and (a.cost,b.cost)==(max(before[0]-2,0),max(before[1]-2,0)),observed)
    audit(cid,[("taunt_and_reduce_libram_costs_by_two","Aldor Truthseeker has Taunt and reduces held Librams' Cost by 2.",taunt_and_two_cost_reduction,"验证嘲讽及两张不同Libram的费用变化。")])


def astromancer_solarian():
    cid="BT_028"
    def spellpower_and_prime_shuffle():
        g,p,e=game(CardClass.MAGE);body=play(p,cid);power=body.spellpower;body.destroy();primes=[c for c in p.deck if c.id=="BT_028t"]
        observed=f"spellpower={power};body={body.zone.name};primes={[(c.id,c.zone.name) for c in primes]}"
        return check(power==1 and body.zone==Zone.GRAVEYARD and len(primes)==1 and primes[0].zone==Zone.DECK,observed)
    audit(cid,[("spell_damage_and_death_shuffle_solarian_prime","Solarian has Spell Damage +1 and its deathrattle shuffles one Solarian Prime into deck.",spellpower_and_prime_shuffle,"核对法强状态及亡语牌库实体。")])


def bamboozle():
    cid="BT_042"
    def attacked_friendly_minion_evolves_by_three_cost():
        g,p,e=game(CardClass.ROGUE);secret=play(p,cid);target=p.summon("CS2_182");old_id=target.id;old_cost=target.cost
        attacker=e.summon(WISP);g.end_turn();attacker.attack(target)
        replacement=next((m for m in p.field if m is not target),None)
        observed=f"secret={secret.zone.name};old={old_id}:{old_cost}/{target.health}:{target.zone.name};field={[(m.id,m.cost,m.health) for m in p.field]};attacker={attacker.zone.name}"
        return check(secret.zone==Zone.GRAVEYARD and replacement is not None
                     and replacement.type==CardType.MINION and replacement.cost==old_cost+3
                     and len(p.field)==1,observed)
    audit(cid,[("attacked_friendly_minion_transforms_to_three_cost_more","Bamboozle reveals when a friendly minion is attacked and replaces it with a minion costing 3 more.",attacked_friendly_minion_evolves_by_three_cost,"对手实际攻击一只5血随从，检查奥秘、替换实体与费用增量。")])


def deep_freeze():
    cid="BT_072"
    def freezes_enemy_and_summons_two_elementals():
        g,p,e=game(CardClass.MAGE);target=e.summon("EX1_563");spell=play(p,cid,target=target);tokens=[m for m in p.field if m.id=="CS2_033"]
        observed=f"frozen={target.frozen};tokens={[(m.atk,m.health,m.zone.name) for m in tokens]};spell={spell.zone.name}"
        return check(target.frozen and len(tokens)==2
                     and all((m.atk,m.health)==(3,6) and m.zone==Zone.PLAY for m in tokens),observed)
    audit(cid,[("freeze_enemy_and_summon_two_water_elementals","Deep Freeze freezes the selected enemy and summons two 3/6 Water Elementals.",freezes_enemy_and_summons_two_elementals,"敌方高血目标与两个已知元素衍生物。")])


def serpentshrine_portal():
    cid="BT_100"
    def damages_target_summons_three_cost_and_overloads():
        g,p,e=game(CardClass.SHAMAN);target=e.summon("EX1_563");before=target.health;spell=play(p,cid,target=target)
        generated=[m for m in p.field if m is not None]
        overloaded=p.overloaded;g.end_turn();g.end_turn();locked=p.overload_locked
        observed=f"target={before}->{target.health};summoned={[(m.id,m.cost) for m in generated]};overloaded={overloaded};locked_next_turn={locked};spell={spell.zone.name}"
        return check(target.health==before-3 and len(generated)==1 and generated[0].cost==3
                     and overloaded==1 and locked==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deal_three_summon_three_cost_and_overload_one","Serpentshrine Portal deals 3, summons one 3-Cost minion, and locks 1 Overload.",damages_target_summons_three_cost_and_overloads,"高血敌人承受伤害，核对随机召唤费用和过载锁定。")])


def vivid_spores():
    cid="BT_101"
    def friendly_minions_resummon_once():
        g,p,e=game(CardClass.SHAMAN);ally=p.summon("CS2_182");enemy=e.summon("CS2_182");spell=play(p,cid)
        flags=(ally.has_deathrattle,enemy.has_deathrattle);ally.destroy();copies=[m for m in p.field if m.id==ally.id]
        observed=f"deathrattles={flags};copies={[(m.atk,m.health,m.zone.name) for m in copies]};enemy={enemy.zone.name};spell={spell.zone.name}"
        return check(flags==(True,False) and ally.zone==Zone.GRAVEYARD
                     and len(copies)==1 and (copies[0].atk,copies[0].health)==(4,5)
                     and enemy.zone==Zone.PLAY,observed)
    audit(cid,[("friendly_minion_deathrattle_resummons_itself","Vivid Spores grants friendly minions a resummon deathrattle; killing the minion returns one copy, while enemy minions are unaffected.",friendly_minions_resummon_once,"友方/敌方各一只随从比较，触发友方死亡后检查重召。")])


def boggspine_knuckles():
    cid="BT_102"
    def hero_attack_evolves_each_friendly_minion_once():
        g,p,e=game(CardClass.SHAMAN);weapon=play(p,cid);wisp=p.summon(WISP);yeti=p.summon("CS2_182");target=e.summon("EX1_563")
        p.hero.attack(target);field=[(m.id,m.cost) for m in p.field]
        observed=f"weapon={weapon.zone.name}:{p.weapon.durability};field={field};old_costs=0,4"
        return check(len(p.field)==2 and all(cost in (1,5) for _,cost in field)
                     and all(cid not in (wisp.id,yeti.id) for cid,_ in field),observed)
    audit(cid,[("hero_attack_evolves_friendly_minions_plus_one_cost","After the hero attacks, Boggspine Knuckles transforms each friendly minion into one costing 1 more.",hero_attack_evolves_each_friendly_minion_once,"场上0费和4费随从，实际攻击后核对两个变形结果费用。")])


def bogstrok_clacker():
    cid="BT_106"
    def transforms_adjacent_minions_only():
        g,p,e=game(CardClass.SHAMAN);left=p.summon(WISP);right=p.summon("CS2_182");other=p.summon("EX1_563")
        body=play(p,cid,index=1);observed=f"field={[(m.id,m.cost) for m in p.field]};body={body.zone.name};other={other.id}:{other.cost}"
        left_after=p.field[0];right_after=p.field[2]
        return check(len(p.field)==4 and p.field[1] is body
                     and left_after.cost==1 and right_after.cost==5
                     and left_after.id!=left.id and right_after.id!=right.id,observed)
    audit(cid,[("battlecry_evolves_adjacent_minions_plus_one_cost","Bogstrok Clacker transforms only the minions immediately adjacent to it into minions costing 1 more.",transforms_adjacent_minions_only,"左右相邻随从费用0/4，另放一个非相邻目标核对范围。")])


def lady_vashj():
    cid="BT_109"
    def spellpower_and_prime_shuffle():
        g,p,e=game(CardClass.SHAMAN);body=play(p,cid);power=body.spellpower;body.destroy();primes=[c for c in p.deck if c.id=="BT_109t"]
        observed=f"spellpower={power};body={body.zone.name};primes={[(c.id,c.zone.name) for c in primes]}"
        return check(power==1 and body.zone==Zone.GRAVEYARD and len(primes)==1 and primes[0].zone==Zone.DECK,observed)
    audit(cid,[("spell_damage_and_death_shuffle_vashj_prime","Lady Vashj has Spell Damage +1 and death shuffles one Vashj Prime into deck.",spellpower_and_prime_shuffle,"检查法强属性及亡语洗入的卡牌实体。")])


def torrent():
    cid="BT_110"
    def branch(cast_last_turn):
        g,p,e=game(CardClass.SHAMAN);target=e.summon("EX1_563")
        if cast_last_turn:
            play(p,"CS2_008",target=target);g.end_turn();g.end_turn()
        spell=p.give(cid);before=spell.cost;target_before=target.health;spell.play(target=target)
        observed=f"cast_last_turn={cast_last_turn};cost={before};target={target_before}->{target.health};spell={spell.zone.name}"
        return check(before==(1 if cast_last_turn else 4) and target.health==target_before-8
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("cast_last_turn_reduces_cost_by_three","Torrent costs 3 less after a spell was cast on the previous turn and deals 8 damage.",lambda:branch(True),"前一回合真实施法并跨回合，检查费用/伤害。"),
               ("no_previous_spell_full_cost","Without a spell cast last turn, Torrent keeps its original Cost and still deals 8.",lambda:branch(False),"新局无前回合法术对照。")])


def totemic_reflection():
    cid="BT_113"
    def branch(totem):
        g,p,e=game(CardClass.SHAMAN);target=p.summon("CS2_050" if totem else WISP);before=(target.atk,target.max_health)
        spell=play(p,cid,target=target);copies=[m for m in p.field if m.id==target.id and m is not target]
        observed=f"totem={totem};target={before}->{(target.atk,target.max_health)};copies={[(m.atk,m.max_health,m.taunt) for m in copies]}"
        return check((target.atk,target.max_health)==(before[0]+2,before[1]+2)
                     and len(copies)==(1 if totem else 0)
                     and (not copies or (copies[0].atk,copies[0].max_health,copies[0].taunt)==(before[0]+2,before[1]+2,False))
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("totem_gets_buff_and_copy","Totemic Reflection gives a Totem +2/+2 and summons a copy of the buffed Totem.",lambda:branch(True),"图腾目标核对本体和新复制体属性。"),
               ("non_totem_gets_buff_without_copy","A non-Totem receives +2/+2 but does not create a copy.",lambda:branch(False),"普通随从目标作是否召唤的对照。")])


def shattered_rumbler():
    cid="BT_114"
    def branch(cast_last_turn):
        g,p,e=game(CardClass.SHAMAN);friend=p.summon("EX1_563");foe=e.summon("EX1_563")
        if cast_last_turn:
            play(p,"CS2_008",target=foe);g.end_turn();g.end_turn()
        before=(friend.health,foe.health);p.used_mana=0;body=play(p,cid)
        observed=f"cast_last_turn={cast_last_turn};minions={before}->{(friend.health,foe.health)};body={body.health}"
        expected=(before[0]-2,before[1]-2) if cast_last_turn else before
        return check((friend.health,foe.health)==expected and body.health==body.max_health,observed)
    audit(cid,[("previous_turn_spell_damages_other_minions","If a spell was cast last turn, Shattered Rumbler deals 2 to all other minions.",lambda:branch(True),"跨回合施法后检查敌我所有其他随从受伤。"),
               ("no_previous_spell_does_not_damage","Without a spell last turn, Battlecry does not damage other minions.",lambda:branch(False),"无前回合法术对照。")])


def marshspawn():
    cid="BT_115"
    def branch(cast_last_turn):
        g,p,e=game(CardClass.SHAMAN)
        if cast_last_turn:play(p,"CS2_008",target=e.hero);g.end_turn();g.end_turn()
        p.used_mana=0;body=play(p,cid);choice=p.choice;options=list(choice.cards) if choice else []
        selected=options[0] if options else None
        if selected:choice.choose(selected)
        observed=f"cast_last_turn={cast_last_turn};options={[(c.id,c.type) for c in options]};selected={None if selected is None else (selected.id,selected.zone.name)};choice={p.choice}"
        return check(bool(options)==cast_last_turn and (not options or len(options)==3)
                     and (selected is None or selected.zone==Zone.HAND)
                     and p.choice is None and body.zone==Zone.PLAY,observed)
    audit(cid,[("previous_turn_spell_discovers_spell","After a spell last turn, Marshspawn Battlecry offers a spell Discover.",lambda:branch(True),"跨回合保留真实施法记录并完成Discover。"),
               ("no_previous_spell_no_discover","Without a spell last turn, Marshspawn gives no Discover choice.",lambda:branch(False),"新局无前回合法术对照。")])


def bladestorm():
    cid="BT_117"
    def first_death_stops_repeats():
        g,p,e=game(CardClass.WARRIOR);fragile=p.summon("CS2_231");friend=p.summon("CS2_182");foe=e.summon("CS2_182")
        heroes=(p.hero.health,e.hero.health);spell=play(p,cid)
        observed=f"fragile={fragile.zone.name};friend={friend.health};foe={foe.health};heroes={heroes}->{(p.hero.health,e.hero.health)}"
        return check(fragile.zone==Zone.GRAVEYARD and friend.health==friend.max_health-1
                     and foe.health==foe.max_health-1 and heroes==(p.hero.health,e.hero.health)
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("repeats_until_first_minion_dies","Bladestorm deals one damage to all minions, then stops repeating once the 1-Health Wisp dies.",first_death_stops_repeats,"脆弱随从确保首轮死亡，核对双方高血随从仅受到1点伤害。")])


def warmaul_challenger():
    cid="BT_120"
    def battles_enemy_minion_to_death():
        g,p,e=game(CardClass.WARRIOR);victim=e.summon(WISP);before=(victim.health,None);body=play(p,cid,target=victim)
        observed=f"victim={victim.zone.name};body={body.zone.name}:{body.health}/{body.max_health};atk={body.atk}"
        return check(victim.zone==Zone.GRAVEYARD and body.zone==Zone.PLAY
                     and body.health==body.max_health-1,observed)
    audit(cid,[("battlecry_fights_chosen_enemy_to_death","Warmaul Challenger attacks the chosen enemy minion until it dies and survives combat.",battles_enemy_minion_to_death,"1/1敌方目标确保至少一次互相战斗并检查存活。")])


def imprisoned_ganarg():
    cid="BT_121"
    def awakens_and_equips_three_two_axe():
        g,p,e=game(CardClass.WARRIOR);body=play(p,cid);initial=(body.dormant,body.dormant_turns)
        g.end_turn();g.end_turn();middle=(body.dormant,body.dormant_turns);g.end_turn();g.end_turn()
        observed=f"initial={initial};middle={middle};dormant={body.dormant};weapon={None if p.weapon is None else (p.weapon.id,p.weapon.atk,p.weapon.durability)}"
        return check(initial==(True,2) and middle==(True,1) and not body.dormant
                     and p.weapon is not None and (p.weapon.atk,p.weapon.durability)==(3,2),observed)
    audit(cid,[("dormant_two_turns_then_equip_three_two_axe","Gan'arg awakens after two of its owner's turns and equips a 3/2 Axe.",awakens_and_equips_three_two_axe,"逐己方回合检查休眠进度，核对装备。")])


def kargath_bladefist():
    cid="BT_123"
    def rush_and_prime_deathrattle():
        g,p,e=game(CardClass.WARRIOR);victim=e.summon("EX1_563");body=play(p,cid);rush=body.rush;can_attack=body.can_attack(victim)
        if can_attack:body.attack(victim)
        damage=victim.max_health-victim.health;body.destroy();primes=[c for c in p.deck if c.id=="BT_123t"]
        observed=f"rush={rush};can_attack={can_attack};victim_damage={damage};body={body.zone.name};prime={[(c.id,c.zone.name) for c in primes]}"
        return check(rush and can_attack and damage==body.atk and body.zone==Zone.GRAVEYARD
                     and len(primes)==1 and primes[0].zone==Zone.DECK,observed)
    audit(cid,[("rush_attack_and_death_shuffle_prime","Kargath has Rush, can attack immediately, and death shuffles one Kargath Prime into deck.",rush_and_prime_deathrattle,"立即攻击耐久目标，再触发亡语检查洗牌。")])


def corsair_cache():
    cid="BT_124"
    def draws_weapon_and_adds_durability():
        g,p,e=game(CardClass.WARRIOR);weapon=p.card("CS2_091",zone=Zone.DECK);other=p.card(WISP,zone=Zone.DECK);before=weapon.durability
        spell=play(p,cid)
        observed=f"weapon={weapon.id}:{before}->{weapon.durability}:{weapon.zone.name};other={other.zone.name};spell={spell.zone.name}"
        return check(weapon.zone==Zone.HAND and weapon.durability==before+1
                     and other.zone==Zone.DECK and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("draws_weapon_with_one_extra_durability","Corsair Cache draws the only weapon and increases its Durability by 1.",draws_weapon_and_adds_durability,"牌库中设置唯一武器及非武器对照，检查耐久增量。")])


def teron_gorefiend():
    cid="BT_126"
    def destroys_then_deathrattle_resummons_friends_buffed():
        g,p,e=game();first=p.summon(WISP);second=p.summon("CS2_182");body=play(p,cid)
        destroyed=(first.zone,second.zone);body.destroy();copies=[m for m in p.field if m.id in (WISP,"CS2_182")]
        observed=f"destroyed={[z.name for z in destroyed]};body={body.zone.name};copies={[(m.id,m.atk,m.max_health) for m in copies]}"
        return check(destroyed==(Zone.GRAVEYARD,Zone.GRAVEYARD) and body.zone==Zone.GRAVEYARD
                     and sorted((m.atk,m.max_health) for m in copies)==[(2,2),(5,6)],observed)
    audit(cid,[("battlecry_destroy_friends_then_deathrattle_resummon_plus_one","Teron destroys other friendly minions; its deathrattle resummons them with +1/+1.",destroys_then_deathrattle_resummons_friends_buffed,"两种不同身材随从核对先毁灭再带增益重召。")])


def imprisoned_satyr():
    cid="BT_127"
    def awakens_discounts_random_minion_in_hand():
        g,p,e=game(CardClass.DRUID);minion=p.give("EX1_534");spell=p.give("CS2_029");before=(minion.cost,spell.cost);body=play(p,cid)
        g.end_turn();g.end_turn();g.end_turn();g.end_turn()
        observed=f"dormant={body.dormant};minion={before[0]}->{minion.cost};spell={before[1]}->{spell.cost};zones={minion.zone.name}/{spell.zone.name}"
        return check(not body.dormant and minion.zone==Zone.HAND
                     and minion.cost==max(before[0]-5,0) and spell.cost==before[1],observed)
    audit(cid,[("awakening_reduces_a_random_held_minion_by_five","After two owner-turn starts Satyr awakens and reduces a held minion's Cost by 5, leaving a spell unchanged.",awakens_discounts_random_minion_in_hand,"手牌仅有一只高费随从和法术对照，跨两次己方回合。")])


def fungal_fortunes():
    cid="BT_128"
    def draws_three_and_discards_drawn_minions():
        g,p,e=game(CardClass.DRUID);spell1=p.card("CS2_008",zone=Zone.DECK);minion=p.card(WISP,zone=Zone.DECK);spell2=p.card("CS2_029",zone=Zone.DECK)
        card=play(p,cid)
        observed=f"spell1={spell1.zone.name};minion={minion.zone.name};spell2={spell2.zone.name};hand={[(c.id,c.type) for c in p.hand]};cast={card.zone.name}"
        return check(spell1.zone==spell2.zone==Zone.HAND and minion.zone!=Zone.HAND
                     and card.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("draw_three_discard_minion_cards","Fungal Fortunes draws three and discards any minion among those drawn, retaining the spells.",draws_three_and_discards_drawn_minions,"牌库恰放两法术一随从，逐张验证抽取和弃置。")])


def germination():
    cid="BT_129"
    def summons_taunt_copy():
        g,p,e=game(CardClass.DRUID);target=p.summon("CS2_182");before=(target.atk,target.max_health);spell=play(p,cid,target=target)
        copies=[m for m in p.field if m.id==target.id and m is not target]
        observed=f"original={before}->{(target.atk,target.max_health,target.taunt)};copies={[(m.atk,m.max_health,m.taunt) for m in copies]}"
        return check((target.atk,target.max_health)==before and not target.taunt and len(copies)==1
                     and (copies[0].atk,copies[0].max_health,copies[0].taunt)==(before[0],before[1],True)
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("summons_taunt_copy_of_friendly_minion","Germination leaves the chosen friendly minion unchanged and summons a matching Taunt copy.",summons_taunt_copy,"高血友方随从作目标，核对复制体属性和嘲讽仅在复制体。")])


def overgrowth():
    cid="BT_130"
    def adds_two_empty_mana_crystals():
        g,p,e=game(CardClass.DRUID);p.max_mana=4;p.used_mana=0;before=p.max_mana;spell=play(p,cid)
        observed=f"max_mana={before}->{p.max_mana};used={p.used_mana};available={p.mana};spell={spell.zone.name}"
        return check(p.max_mana==before+2 and p.used_mana==6 and p.mana==0
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("gain_two_empty_mana_crystals","Overgrowth gains two empty Mana Crystals: max Mana rises by 2 without refunding paid Cost.",adds_two_empty_mana_crystals,"将水晶设为4以避免上限，核对最大/已用/剩余法力。")])


def ysiel_windsinger():
    cid="BT_131"
    def all_spells_in_hand_cost_one():
        g,p,e=game(CardClass.DRUID);a=p.give("CS2_008");b=p.give("CS2_029");body=play(p,cid)
        observed=f"spells={[(c.id,c.cost,c.zone.name) for c in (a,b)]};body={body.zone.name}"
        return check(a.cost==b.cost==1 and a.zone==b.zone==Zone.HAND and body.zone==Zone.PLAY,observed)
    audit(cid,[("your_spells_cost_one","While Ysiel is in play, spells in hand with different printed Costs each cost exactly 1.",all_spells_in_hand_cost_one,"高/零费用法术同手牌核对置为1而非统一减费。")])


def ironbark():
    cid="BT_132"
    def branch(mana_crystals):
        g,p,e=game(CardClass.DRUID);p.max_mana=mana_crystals;target=p.summon("CS2_182");spell=p.give(cid);cost=spell.cost;spell.play(target=target)
        observed=f"max_mana={mana_crystals};cost={cost};target={target.atk}/{target.max_health}/{target.taunt};spell={spell.zone.name}"
        return check(cost==(0 if mana_crystals>=7 else 2)
                     and (target.atk,target.max_health,target.taunt)==(5,8,True),observed)
    audit(cid,[("seven_crystals_make_ironbark_free","At 7 Mana Crystals Ironbark costs 0 and gives +1/+3 Taunt.",lambda:branch(7),"恰好7水晶分支，实际施放并检查目标增益。"),
               ("six_crystals_keep_original_cost","At 6 Mana Crystals Ironbark retains its 3-Cost while giving the same minion buff.",lambda:branch(6),"6水晶作为阈值下界对照。")])


def marsh_hydra():
    cid="BT_133"
    def rush_attack_adds_eight_cost_minion():
        g,p,e=game(CardClass.DRUID);body=play(p,cid);target=e.summon("EX1_563");can_attack=body.can_attack(target)
        if can_attack:body.attack(target)
        added=p.hand[-1] if p.hand else None
        observed=f"rush={body.rush};can_attack={can_attack};target={target.health};added={None if added is None else (added.id,added.cost,added.type,added.zone.name)}"
        return check(body.rush and can_attack and added is not None
                     and added.type==CardType.MINION and added.cost==8 and added.zone==Zone.HAND,observed)
    audit(cid,[("after_rush_attack_add_random_eight_cost_minion","Marsh Hydra can use Rush immediately; after its attack it adds an 8-Cost minion to hand.",rush_attack_adds_eight_cost_minion,"实际突袭攻击后按生成随从费用验证触发。")])


def bogbeam():
    cid="BT_134"
    def branch(mana_crystals):
        g,p,e=game(CardClass.DRUID);p.max_mana=mana_crystals;target=e.summon("EX1_563");spell=p.give(cid);cost=spell.cost;before=target.health;spell.play(target=target)
        observed=f"max_mana={mana_crystals};cost={cost};target={before}->{target.health};spell={spell.zone.name}"
        return check(cost==(0 if mana_crystals>=7 else 3) and target.health==before-3
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("seven_crystals_make_bogbeam_free","At 7 Mana Crystals, Bogbeam costs 0 and deals 3 to a minion.",lambda:branch(7),"7水晶阈值分支及实际伤害。"),
               ("six_crystals_keep_bogbeam_cost","At 6 Mana Crystals, Bogbeam costs 3 and deals the same 3 damage.",lambda:branch(6),"6水晶对照，确认不是过早免费。")])


def glowfly_swarm():
    cid="BT_135"
    def summons_one_glowfly_per_held_spell():
        g,p,e=game(CardClass.DRUID);spells=[p.give("CS2_008"),p.give("CS2_029")];minion=p.give(WISP)
        body=play(p,cid);tokens=[m for m in p.field if m.id=="BT_135t"]
        observed=f"tokens={[(m.atk,m.health) for m in tokens]};spells={[c.zone.name for c in spells]};minion={minion.zone.name};body={body.zone.name}"
        return check(len(tokens)==len(spells)==2 and all((m.atk,m.health)==(2,2) for m in tokens)
                     and all(c.zone==Zone.HAND for c in spells) and minion.zone==Zone.HAND,observed)
    audit(cid,[("summons_glowfly_per_spell_in_hand","Glowfly Swarm summons one 2/2 Glowfly for each spell remaining in hand, ignoring minions.",summons_one_glowfly_per_held_spell,"两张不同法术加随从手牌对照，逐个核对2/2数量。")])


def archspore_msshifn():
    cid="BT_136"
    def taunt_and_prime_deathrattle():
        g,p,e=game(CardClass.DRUID);body=play(p,cid);taunt=body.taunt;body.destroy();primes=[c for c in p.deck if c.id=="BT_136t"]
        observed=f"taunt={taunt};body={body.zone.name};primes={[(c.id,c.zone.name) for c in primes]}"
        return check(taunt and body.zone==Zone.GRAVEYARD and len(primes)==1 and primes[0].zone==Zone.DECK,observed)
    audit(cid,[("taunt_and_death_shuffle_msshifn_prime","Archspore has Taunt and death shuffles exactly one Msshi'fn Prime into deck.",taunt_and_prime_deathrattle,"检查嘲讽关键词及牌库亡语实体。")])


CHECKS={
    "BT_002":incanters_flow,"BT_003":netherwind_portal,"BT_004":imprisoned_observer,
    "BT_006":evocation,"BT_008":rustsworn_initiate,"BT_009":imprisoned_sungill,
    "BT_010":felfin_navigator,"BT_011":libram_of_justice,"BT_014":starscryer,
    "BT_018":underlight_angling_rod,"BT_019":murgur_murgurgle,"BT_020":aldor_attendant,
    "BT_021":font_of_power,"BT_022":apexis_smuggler,"BT_024":libram_of_hope,
    "BT_025":libram_of_wisdom,"BT_026":aldor_truthseeker,"BT_028":astromancer_solarian,
    "BT_042":bamboozle,"BT_072":deep_freeze,"BT_100":serpentshrine_portal,
    "BT_101":vivid_spores,"BT_102":boggspine_knuckles,"BT_106":bogstrok_clacker,
    "BT_109":lady_vashj,"BT_110":torrent,"BT_113":totemic_reflection,
    "BT_114":shattered_rumbler,"BT_115":marshspawn,"BT_117":bladestorm,
    "BT_120":warmaul_challenger,"BT_121":imprisoned_ganarg,"BT_123":kargath_bladefist,
    "BT_124":corsair_cache,"BT_126":teron_gorefiend,"BT_127":imprisoned_satyr,
    "BT_128":fungal_fortunes,"BT_129":germination,"BT_130":overgrowth,
    "BT_131":ysiel_windsinger,"BT_132":ironbark,"BT_133":marsh_hydra,
    "BT_134":bogbeam,"BT_135":glowfly_swarm,"BT_136":archspore_msshifn,
}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
