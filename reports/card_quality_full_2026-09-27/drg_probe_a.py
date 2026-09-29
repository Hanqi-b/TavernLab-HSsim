"""Card-specific live game checks for the first 45 collectible DRAGONS YELLOW cards."""

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
PROBE_FILE = HERE / "drg_probe_a.csv"
VERDICT_FILE = HERE / "drg_verdict_a.csv"
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
                 if r["set"].endswith("(DRAGONS)")),
                key=lambda r: r["card_id"])
ROSTER = ROSTER[:45]
assert len(ROSTER) == 45
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
PROBES = read(PROBE_FILE)
VERDICTS = read(VERDICT_FILE)


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


def corrosive_breath():
    cid="DRG_006"
    def branch(holding_dragon):
        g,p,e=game(CardClass.HUNTER)
        target=e.summon("CS2_182")
        if holding_dragon:dragon=p.give("NEW1_023")
        spell=play(p,cid,target=target)
        observed=f"dragon={holding_dragon};target={target.health};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(target.health==2 and e.hero.health==(27 if holding_dragon else 30),observed)
    audit(cid,[("held_dragon_hits_minion_and_hero","Holding Dragon: chosen minion and enemy hero each take 3.",lambda:branch(True),"真实手牌龙条件与双目标。"),
               ("no_dragon_only_minion","No Dragon: only chosen minion takes 3.",lambda:branch(False),"无龙对照。")])


def stormhammer():
    cid="DRG_007"
    def branch(dragon_controlled):
        g,p,e=game(CardClass.HUNTER)
        if dragon_controlled:dragon=p.summon("NEW1_023")
        weapon=play(p,cid);before=weapon.durability
        ready=p.hero.can_attack(e.hero)
        if ready:p.hero.attack(e.hero)
        observed=f"dragon={dragon_controlled};before={before};after={weapon.durability};ready={ready};enemy_health={e.hero.health};weapon={weapon.zone.name}"
        return check(ready and before==2 and weapon.durability==(2 if dragon_controlled else 1)
                     and e.hero.health==27,observed)
    audit(cid,[("dragon_prevents_durability_loss","Controlling Dragon: hero attack damages enemy but leaves weapon at 2 Durability.",lambda:branch(True),"实际英雄攻击与耐久。"),
               ("without_dragon_loses_one","Without Dragon: same attack spends one Durability.",lambda:branch(False),"无龙对照。")])


def righteous_cause():
    cid="DRG_008"
    def five_summons_reward():
        g,p,e=game(CardClass.PALADIN)
        sidequest=play(p,cid)
        bodies=[]
        for _ in range(4):bodies.append(p.summon(WISP))
        before=sidequest.progress
        fifth=p.summon(WISP);bodies.append(fifth)
        observed=f"after_four={before};after_five={sidequest.progress};quest={sidequest.zone.name};stats={[(m.atk,m.health,m.zone.name) for m in bodies]}"
        return check(before==4 and sidequest.progress==5 and sidequest.zone==Zone.GRAVEYARD
                     and all((m.atk,m.health)==(2,2) for m in bodies),observed)
    audit(cid,[("five_actual_summons_buff_all_friends","Four summons give progress 4; fifth completes Sidequest and gives all five bodies +1/+1.",five_summons_reward,"逐次召唤、进度、任务区域与全体增益。")])


def diving_gryphon():
    cid="DRG_010"
    def draws_rush_minion_only():
        g,p,e=game(CardClass.HUNTER)
        rush=p.card("ULD_206",zone=Zone.DECK);plain=p.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        observed=f"rush={body.rush};drawn={rush.id}:{rush.zone.name};plain={plain.zone.name};body={body.zone.name}"
        return check(body.rush and rush.zone==Zone.HAND and plain.zone==Zone.DECK,observed)
    audit(cid,[("battlecry_draws_only_rush_minion","Rush Gryphon draws sole Rush deck minion, leaving ordinary Wisp in deck.",draws_rush_minion_only,"牌库筛选、手牌区域和 Rush。")])


def scion_of_ruin():
    cid="DRG_019"
    def branch(invoked_twice):
        g,p,e=game(CardClass.WARRIOR)
        if invoked_twice:
            p.card("DRG_650",zone=Zone.DECK)
            play(p,"DRG_021");play(p,"DRG_249")
            p.used_mana=0
        count=p.invoke_counter
        try:body=play(p,cid)
        except AttributeError as exc:
            return check(False,f"invoked={count};play_error={type(exc).__name__}:{exc};source=warrior.py:DRG_019 uses SummonBothSides(SELF,...)")
        scions=[m for m in p.field if m.id==cid]
        observed=f"invoked={count};scions={[(m.atk,m.health,m.rush,m.zone.name) for m in scions]};body={body.zone.name}"
        return check(count==(2 if invoked_twice else 0) and len(scions)==(3 if invoked_twice else 1)
                     and all(m.rush for m in scions),observed)
    audit(cid,[("two_real_invokes_summon_two_copies","After two actual Invoke cards, Rush Scion appears with two copies.",lambda:branch(True),"真实祈求计数与召唤。"),
               ("no_invokes_no_extra_copies","Without Invoke, only original Scion appears.",lambda:branch(False),"未祈求对照。")])


def evil_quartermaster():
    cid="DRG_020"
    def lackey_and_armor():
        g,p,e=game(CardClass.WARRIOR)
        body=play(p,cid);hand=list(p.hand)
        observed=f"armor={p.hero.armor};hand={[(c.id,c.mark_of_evil,c.zone.name) for c in hand]};body={body.zone.name}"
        return check(p.hero.armor==3 and len(hand)==1 and hand[0].mark_of_evil and hand[0].zone==Zone.HAND,observed)
    audit(cid,[("add_one_lackey_gain_three_armor","Battlecry adds one Lackey to hand and grants 3 Armor.",lackey_and_armor,"双效果手牌与护甲。")])


def ritual_chopper():
    cid="DRG_021"
    def equips_and_invokes():
        g,p,e=game(CardClass.WARRIOR)
        galakrond=p.card("DRG_650",zone=Zone.DECK)
        weapon=play(p,cid)
        observed=f"invoke_count={p.invoke_counter};hero_attack={p.hero.atk};weapon={weapon.id}:{weapon.zone.name}:{weapon.durability};galakrond={galakrond.zone.name}"
        return check(p.invoke_counter==1 and p.hero.atk==4 and p.weapon is weapon
                     and weapon.zone==Zone.PLAY and galakrond.zone==Zone.DECK,observed)
    audit(cid,[("weapon_equips_and_invokes_warrior_galakrond","Battlecry performs one actual Invoke while a Warrior Galakrond is in deck, granting hero 3 temporary Attack in addition to 1-Attack weapon.",equips_and_invokes,"真实祈求计数、英雄攻击与装备区域。")])


def ramming_speed():
    cid="DRG_022"
    def forces_neighbor_combat():
        g,p,e=game(CardClass.WARRIOR)
        left=e.summon(WISP);center=e.summon("CS2_182");right=e.summon(WISP)
        spell=play(p,cid,target=center)
        dead_sides=sum(m.zone==Zone.GRAVEYARD for m in (left,right))
        observed=f"center={center.health}:{center.zone.name};sides={left.zone.name}/{right.zone.name};spell={spell.zone.name}"
        return check(center.health==4 and center.zone==Zone.PLAY and dead_sides==1
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("selected_minion_attacks_one_neighbor","Selected middle Yeti attacks exactly one adjacent Wisp, killing it and taking 1 retaliation damage.",forces_neighbor_combat,"真实强制战斗、相邻筛选和死亡。")])


def skybarge():
    cid="DRG_023"
    def pirate_summon_triggers_damage():
        g,p,e=game(CardClass.WARRIOR)
        body=play(p,cid);ordinary=play(p,WISP)
        before=e.hero.health
        pirate=play(p,"CS2_146")
        observed=f"before_pirate={before};after={e.hero.health};pirate={pirate.zone.name};barge={body.zone.name}"
        return check(before==30 and e.hero.health==28 and pirate.zone==Zone.PLAY,observed)
    audit(cid,[("later_pirate_summon_hits_enemy_two","Non-Pirate Wisp causes no damage; later Pirate summon deals 2 to sole enemy character hero.",pirate_summon_triggers_damage,"召唤事件、种族和随机目标隔离。")])


def sky_raider():
    cid="DRG_024"
    def adds_pirate():
        g,p,e=game(CardClass.WARRIOR)
        body=play(p,cid);hand=list(p.hand)
        observed=f"body={body.zone.name};hand={[(c.id,Race.PIRATE in c.races,c.zone.name) for c in hand]}"
        return check(len(hand)==1 and Race.PIRATE in hand[0].races and hand[0].zone==Zone.HAND,observed)
    audit(cid,[("battlecry_adds_one_pirate","Battlecry adds exactly one Pirate card to hand.",adds_pirate,"生成卡数量、种族及区域。")])


def ancharrr():
    cid="DRG_025"
    def attack_draws_only_deck_pirate():
        g,p,e=game(CardClass.WARRIOR)
        pirate=p.card("CS2_146",zone=Zone.DECK);plain=p.card(WISP,zone=Zone.DECK)
        weapon=play(p,cid);ready=p.hero.can_attack(e.hero)
        if ready:p.hero.attack(e.hero)
        observed=f"ready={ready};pirate={pirate.zone.name};plain={plain.zone.name};weapon={weapon.zone.name}:{weapon.durability};enemy_health={e.hero.health}"
        return check(ready and pirate.zone==Zone.HAND and plain.zone==Zone.DECK
                     and weapon.zone==Zone.PLAY and e.hero.health==28,observed)
    audit(cid,[("hero_attack_draws_pirate_only","Weapon hero attack draws sole Pirate from deck while Wisp stays; hero damages opponent.",attack_draws_only_deck_pirate,"真实武器攻击、牌库筛选与区域。")])


def deathwing_mad_aspect():
    cid="DRG_026"
    def attacks_all_other_minions():
        g,p,e=game(CardClass.WARRIOR)
        friendly=p.summon(WISP);foes=[e.summon(WISP),e.summon(WISP)]
        body=play(p,cid)
        observed=f"friendly={friendly.zone.name};foes={[m.zone.name for m in foes]};deathwing={body.health}:{body.zone.name};enemy_hero={e.hero.health}"
        return check(friendly.zone==Zone.GRAVEYARD and all(m.zone==Zone.GRAVEYARD for m in foes)
                     and body.zone==Zone.PLAY and e.hero.health==30,observed)
    audit(cid,[("attacks_each_friendly_and_enemy_minion","Battlecry actually fights own Wisp and both enemy Wisps, killing all three without hitting enemy hero.",attacks_all_other_minions,"包含己方随从、敌方复数目标及战斗结算。")])


def umbral_skulker():
    cid="DRG_027"
    def branch(invocations):
        g,p,e=game(CardClass.ROGUE)
        p.card("DRG_610",zone=Zone.DECK)
        play(p,"DRG_050")
        if invocations==2:play(p,"DRG_242")
        p.used_mana=0
        body=play(p,cid)
        coins=[c for c in p.hand if c.id=="GAME_005"]
        observed=f"invoke_count={p.invoke_counter};coins={[(c.id,c.zone.name) for c in coins]};body={body.zone.name}"
        return check(p.invoke_counter==invocations and len(coins)==(3 if invocations>=2 else 0) and body.zone==Zone.PLAY,observed)
    audit(cid,[("invoked_twice_adds_three_coins","After two actual Invoke cards, Battlecry adds three Coins.",lambda:branch(2),"真实祈求计数与三张手牌。"),
               ("one_invoke_no_coins","After one actual Invoke card, Battlecry adds none.",lambda:branch(1),"阈值不足对照。")])


def dragons_hoard():
    cid="DRG_028"
    def discover_other_class_legendary():
        g,p,e=game(CardClass.ROGUE)
        spell=play(p,cid);choice=p.choice
        options=list(choice.cards) if choice else []
        selected=options[0] if options else None
        if selected:choice.choose(selected)
        observed=f"options={[(c.id,int(c.rarity),[int(x) for x in c.classes]) for c in options]};selected={None if selected is None else (selected.id,selected.zone.name)};choice_closed={p.choice is None}"
        return check(len(options)==3 and all(c.type==CardType.MINION and c.rarity==5
                     and CardClass.ROGUE not in c.classes and CardClass.NEUTRAL not in c.classes for c in options)
                     and selected.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("discover_other_class_legendary_minion","Offers three Legendary minions from other classes; selected card enters hand.",discover_other_class_legendary,"候选类型稀有度职业及 Choice 闭合。")])


def praise_galakrond():
    cid="DRG_030"
    def buff_target_and_invoke():
        g,p,e=game(CardClass.ROGUE)
        galakrond=p.card("DRG_610",zone=Zone.DECK)
        target=p.summon(WISP);enemy=e.summon(WISP)
        spell=play(p,cid,target=target)
        observed=f"target={target.atk}/{target.health};enemy={enemy.atk}/{enemy.health};invoke_count={p.invoke_counter};spell={spell.zone.name};galakrond={galakrond.zone.name}"
        return check((target.atk,target.health)==(2,1) and (enemy.atk,enemy.health)==(1,1)
                     and p.invoke_counter==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("selected_minion_plus_one_attack_and_invoke","Selected minion gains 1 Attack and Galakrond Invoke counter rises once; enemy minion unchanged.",buff_target_and_invoke,"目标与祈求双效果。")])


def necrium_apothecary():
    cid="DRG_031"
    def combo_draw_and_copy_deathrattle():
        g,p,e=game(CardClass.ROGUE)
        source=p.card("DAL_146",zone=Zone.DECK);plain=p.card(WISP,zone=Zone.DECK)
        play(p,"GAME_005")
        body=play(p,cid)
        copied_dr=body.has_deathrattle
        body.destroy()
        dragons=[c for c in p.hand if c.id=="DAL_146t"]
        observed=f"drawn_source={source.zone.name};plain={plain.zone.name};apothecary_dr={copied_dr};body={body.zone.name};dragons={[(c.id,c.zone.name) for c in dragons]}"
        return check(source.zone==Zone.HAND and plain.zone==Zone.DECK and copied_dr
                     and body.zone==Zone.GRAVEYARD and len(dragons)==2,observed)
    audit(cid,[("combo_draws_deathrattle_and_repeats_it_on_death","After prior card, Apothecary draws sole Deathrattle minion and on death adds its two Dragon tokens.",combo_draw_and_copy_deathrattle,"真实连击、抽牌过滤、复制亡语的实际死亡效果。")])


def candle_breath():
    cid="DRG_033"
    def branch(dragon):
        g,p,e=game(CardClass.ROGUE)
        cards=[p.card(WISP,zone=Zone.DECK) for _ in range(3)]
        if dragon:p.give("NEW1_023")
        spell=p.give(cid);cost=spell.cost;spell.play()
        observed=f"dragon={dragon};cost={cost};drawn={[c.zone.name for c in cards]};spell={spell.zone.name}"
        return check(cost==(3 if dragon else 6) and all(c.zone==Zone.HAND for c in cards),observed)
    audit(cid,[("dragon_reduces_cost_and_draws_three","Holding Dragon reduces cost by 3 and draws three cards.",lambda:branch(True),"手牌龙条件、费用与抽牌。"),
               ("without_dragon_full_cost_and_draws_three","Without Dragon cost remains 6 and still draws three.",lambda:branch(False),"条件反支。")])


def stowaway():
    cid="DRG_034"
    def branch(add_generated):
        g,p,e=game(CardClass.ROGUE)
        original=p.card(WISP,zone=Zone.DECK);p.starting_deck.append(original)
        extras=[]
        if add_generated:
            for _ in range(2):
                card=p.give("CS2_146");card.shuffle_into_deck();extras.append(card)
        body=play(p,cid)
        observed=f"generated={add_generated};extras={[c.zone.name for c in extras]};original={original.zone.name};body={body.zone.name}"
        return check(all(c.zone==Zone.HAND for c in extras) and original.zone==Zone.DECK and body.zone==Zone.PLAY,observed)
    audit(cid,[("draws_only_two_nonstarting_deck_cards","Two later shuffled Pirates are drawn and original Wisp stays deck.",lambda:branch(True),"新增牌、原始牌及两次抽取。"),
               ("no_generated_cards_draws_nothing","No added cards: original Wisp remains deck.",lambda:branch(False),"空候选分支。")])


def bloodsail_flybooter():
    cid="DRG_035"
    def adds_two_pirates():
        g,p,e=game(CardClass.ROGUE);body=play(p,cid);hand=list(p.hand)
        observed=f"hand={[(c.id,c.atk,c.health,c.zone.name) for c in hand]};body={body.zone.name}"
        return check(len(hand)==2 and all(c.id=="DRG_035t" and (c.atk,c.health)==(1,1) and c.zone==Zone.HAND for c in hand),observed)
    audit(cid,[("adds_exactly_two_one_one_pirates","Battlecry adds exactly two 1/1 Pirate tokens to hand.",adds_two_pirates,"数量、身份、身材和区域。")])


def waxadred():
    cid="DRG_036"
    def candle_resummons_on_draw():
        g,p,e=game(CardClass.ROGUE);body=play(p,cid);body.destroy()
        candles=[c for c in p.deck if c.id=="DRG_036t"]
        if candles:candles[0].draw()
        summoned=[m for m in p.field if m.id==cid]
        observed=f"dead={body.zone.name};candle_deck_before={len(candles)};candle_after={candles[0].zone.name if candles else 'none'};summoned={[(m.id,m.zone.name) for m in summoned]}"
        return check(body.zone==Zone.GRAVEYARD and len(candles)==1 and len(summoned)==1 and candles[0].zone!=Zone.HAND,observed)
    audit(cid,[("deathrattle_candle_cast_when_drawn_resummons","Deathrattle shuffles Candle, then drawing it casts and summons Waxadred.",candle_resummons_on_draw,"实际死亡、洗牌、抽中触发与战场。")])


def flik_skyshiv():
    cid="DRG_037"
    def destroys_matching_id_across_zones():
        g,p,e=game(CardClass.ROGUE)
        target=e.summon(WISP);other=e.summon(WISP);own=p.summon(WISP)
        deck_copy=e.card(WISP,zone=Zone.DECK);hand_copy=e.give(WISP)
        own_deck_copy=p.card(WISP,zone=Zone.DECK);own_hand_copy=p.give(WISP)
        unrelated=e.summon("CS2_182")
        body=play(p,cid,target=target)
        copies=(target,other,own,deck_copy,hand_copy,own_deck_copy,own_hand_copy)
        observed=f"copies={[c.zone.name for c in copies]};unrelated={unrelated.zone.name};flik={body.zone.name}"
        return check(all(c.zone not in (Zone.PLAY,Zone.DECK,Zone.HAND) for c in copies)
                     and unrelated.zone==Zone.PLAY and body.zone==Zone.PLAY,observed)
    audit(cid,[("destroys_all_id_copies_both_sides_and_zones","Selected Wisp and copies on both fields, both hands and both decks destroyed; unrelated Yeti survives.",destroys_matching_id_across_zones,"目标与双方各区域同名牌。")])


def tasty_flyfish():
    cid="DRG_049"
    def death_buffs_hand_dragon():
        g,p,e=game();dragon=p.give("NEW1_023");plain=p.give(WISP)
        attack,health=dragon.atk,dragon.health
        body=play(p,cid);body.destroy()
        observed=f"dragon={dragon.atk}/{dragon.health}:{dragon.zone.name};plain={plain.atk}/{plain.health};body={body.zone.name}"
        return check((dragon.atk,dragon.health)==(attack+2,health+2) and (plain.atk,plain.health)==(1,1),observed)
    audit(cid,[("deathrattle_buffs_only_hand_dragon","Actual death gives hand Dragon +2/+2, ordinary hand Wisp unchanged.",death_buffs_hand_dragon,"死亡触发、种族和手牌增益。")])


def devoted_maniac():
    cid="DRG_050"
    def rush_and_invoke():
        g,p,e=game(CardClass.WARRIOR);p.card("DRG_650",zone=Zone.DECK)
        body=play(p,cid)
        observed=f"rush={body.rush};invoke={p.invoke_counter};hero_attack={p.hero.atk};body={body.zone.name}"
        return check(body.rush and p.invoke_counter==1 and p.hero.atk==3 and body.zone==Zone.PLAY,observed)
    audit(cid,[("rush_body_and_real_warrior_invoke","Rush body enters play and actual Invoke gives Warrior hero +3 Attack.",rush_and_invoke,"关键词、祈求计数与英雄状态。")])


def strength_in_numbers():
    cid="DRG_051"
    def spend_mana_completes_and_summons():
        g,p,e=game(CardClass.DRUID)
        quest=play(p,cid)
        first=play(p,"CS2_201");progress=quest.progress
        g.end_turn();g.end_turn()
        deck_minion=p.card("CS2_182",zone=Zone.DECK)
        second=play(p,"CS2_201")
        observed=f"first={first.zone.name};progress_after_first={progress};second={second.zone.name};final={quest.progress}:{quest.zone.name};reward={deck_minion.zone.name}"
        return check(progress==7 and quest.progress>=10 and quest.zone==Zone.GRAVEYARD and deck_minion.zone==Zone.PLAY,observed)
    audit(cid,[("spend_ten_on_minions_summons_deck_minion","Two 7-Mana minions advance progress first to 7, then beyond 10 and summon sole deck minion; quest leaves play.",spend_mana_completes_and_summons,"费用支出进度、奖励与区域。")])


def big_ol_whelp():
    cid="DRG_054"
    def draws_one():
        g,p,e=game();deck=p.card(WISP,zone=Zone.DECK);body=play(p,cid)
        observed=f"drawn={deck.zone.name};body={body.zone.name};hand={len(p.hand)}"
        return check(deck.zone==Zone.HAND and body.zone==Zone.PLAY and len(p.hand)==1,observed)
    audit(cid,[("battlecry_draws_one_deck_card","Battlecry draws exactly one deck Wisp into hand.",draws_one,"牌库与手牌区域。")])


def hoard_pillager():
    cid="DRG_055"
    def requips_destroyed_weapon():
        g,p,e=game(CardClass.WARRIOR)
        weapon=play(p,"CS2_106");weapon.destroy()
        body=play(p,cid)
        observed=f"old={weapon.zone.name};new={None if p.weapon is None else (p.weapon.id,p.weapon.zone.name,p.weapon.durability)};body={body.zone.name}"
        return check(weapon.zone==Zone.GRAVEYARD and p.weapon is not weapon and p.weapon.id=="CS2_106" and p.weapon.zone==Zone.PLAY,observed)
    audit(cid,[("equips_copy_of_destroyed_weapon","After actual destruction, Battlecry equips a copy of sole prior weapon.",requips_destroyed_weapon,"摧毁历史、复制装备与武器区域。")])


def parachute_brigand():
    cid="DRG_056"
    def triggers_only_for_pirate():
        g,p,e=game(CardClass.WARRIOR);brigand=p.give(cid)
        ordinary=play(p,WISP);before=brigand.zone
        pirate=play(p,"CS2_146")
        observed=f"after_wisp={before.name};after_pirate={brigand.zone.name};pirate={pirate.zone.name};ordinary={ordinary.zone.name}"
        return check(before==Zone.HAND and brigand.zone==Zone.PLAY and pirate.zone==Zone.PLAY,observed)
    audit(cid,[("hand_trigger_only_after_played_pirate","Wisp leaves Brigand in hand; playing Pirate summons it to board.",triggers_only_for_pirate,"手牌监听、种族条件与召唤。")])


def hot_air_balloon():
    cid="DRG_057"
    def gains_health_each_own_turn():
        g,p,e=game();body=play(p,cid);initial=body.max_health
        g.end_turn();opponent_turn=body.max_health
        g.end_turn();own_turn=body.max_health
        observed=f"initial={initial};opponent_turn={opponent_turn};own_turn={own_turn};zone={body.zone.name}"
        return check(opponent_turn==initial and own_turn==initial+1 and body.zone==Zone.PLAY,observed)
    audit(cid,[("only_start_of_own_turn_adds_one_health","Opponent turn start gives no Health; next own turn start gives +1 maximum Health.",gains_health_each_own_turn,"回合归属与生命上限。")])


def goboglide_tech():
    cid="DRG_059"
    def branch(mech):
        g,p,e=game()
        if mech:p.summon("BOT_020")
        body=play(p,cid)
        observed=f"mech={mech};stats={body.atk}/{body.health};rush={body.rush};zone={body.zone.name}"
        return check((body.atk,body.health,body.rush)==((4,4,True) if mech else (3,3,False)),observed)
    audit(cid,[("friendly_mech_adds_stats_and_rush","With friendly Mech, gains +1/+1 and Rush.",lambda:branch(True),"有机械条件。"),
               ("without_mech_no_buff","Without Mech, no buff or Rush.",lambda:branch(False),"条件反支。")])


def fire_hawk():
    cid="DRG_060"
    def attack_scales_with_enemy_hand():
        g,p,e=game();base=p.card(cid).atk
        e.give(WISP);e.give(WISP);e.give(WISP)
        body=play(p,cid)
        observed=f"base={base};enemy_hand={len(e.hand)};attack={body.atk};health={body.health}"
        return check(len(e.hand)==3 and body.atk==base+3,observed)
    audit(cid,[("one_attack_per_opponent_hand_card","Three enemy hand cards give Battlecry +3 Attack.",attack_scales_with_enemy_hand,"对手手牌计数与攻击。")])


def gyrocopter():
    cid="DRG_061"
    def rush_windfury_two_attacks():
        g,p,e=game();body=play(p,cid);one=e.summon(WISP);two=e.summon(WISP)
        ready1=body.can_attack(one)
        if ready1:body.attack(one)
        ready2=body.can_attack(two)
        if ready2:body.attack(two)
        observed=f"rush={body.rush};windfury={body.windfury};ready={ready1}/{ready2};victims={one.zone.name}/{two.zone.name};attacks={body.num_attacks}"
        return check(body.rush and body.windfury and ready1 and ready2 and one.zone==Zone.GRAVEYARD and two.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("rush_and_windfury_allow_two_immediate_minion_attacks","On play Rush Gyrocopter attacks and kills two enemy Wisps in same turn.",rush_windfury_two_attacks,"关键词转为真实战斗验证。")])


def wyrmrest_purifier():
    cid="DRG_062"
    def transforms_neutral_deck_cards_only():
        g,p,e=game(CardClass.MAGE)
        neutral=[p.card(WISP,zone=Zone.DECK) for _ in range(3)]
        class_card=p.card("CS2_029",zone=Zone.DECK)
        before=set(p.deck)
        body=play(p,cid)
        after=list(p.deck)
        observed=f"original_neutral={[c.zone.name for c in neutral]};after={[(c.id,[int(x) for x in c.classes],c.zone.name) for c in after]};class_card={class_card.zone.name}"
        return check(len(after)==4 and class_card.zone==Zone.DECK and class_card in after
                     and all(CardClass.MAGE in c.classes for c in after if c is not class_card)
                     and all(c not in after for c in neutral),observed)
    audit(cid,[("only_neutral_deck_cards_become_class_cards","Three neutral deck Wisps are replaced by Mage cards while Mage spell remains unchanged.",transforms_neutral_deck_cards_only,"牌库身份、职业归属与非中立对照。")])


def dragonmaw_poacher():
    cid="DRG_063"
    def branch(dragon):
        g,p,e=game()
        if dragon:e.summon("NEW1_023")
        body=play(p,cid)
        observed=f"enemy_dragon={dragon};stats={body.atk}/{body.health};rush={body.rush}"
        return check((body.atk,body.health,body.rush)==((8,8,True) if dragon else (4,4,False)),observed)
    audit(cid,[("enemy_dragon_gives_four_four_and_rush","Enemy Dragon grants +4/+4 and Rush.",lambda:branch(True),"敌方龙条件。"),
               ("no_enemy_dragon_no_buff","No enemy Dragon leaves stats and Rush unchanged.",lambda:branch(False),"条件反支。")])


def zuldak_ritualist():
    cid="DRG_064"
    def summons_three_one_cost_enemies():
        g,p,e=game();body=play(p,cid);enemies=list(e.field)
        observed=f"taunt={body.taunt};enemy_bodies={[(m.id,m.cost,m.zone.name) for m in enemies]};friendly={[(m.id,m.zone.name) for m in p.field]}"
        return check(body.taunt and len(enemies)==3 and all(m.cost==1 and m.zone==Zone.PLAY for m in enemies)
                     and len(p.field)==1,observed)
    audit(cid,[("taunt_and_three_one_cost_enemy_minions","Battlecry summons three 1-Cost bodies on opponent board; own body has Taunt.",summons_three_one_cost_enemies,"数量、费用、阵营和嘲讽。")])


def hippogryph():
    cid="DRG_065"
    def rush_taunt_combat():
        g,p,e=game();enemy=e.summon(WISP);body=play(p,cid)
        ready=body.can_attack(enemy)
        if ready:body.attack(enemy)
        observed=f"rush={body.rush};taunt={body.taunt};ready={ready};enemy={enemy.zone.name};body={body.zone.name}"
        return check(body.rush and body.taunt and ready and enemy.zone==Zone.GRAVEYARD and body.zone==Zone.PLAY,observed)
    audit(cid,[("rush_taunt_immediate_attack","Rush Hippogryph can attack and kill enemy Wisp on turn played, retaining Taunt.",rush_taunt_combat,"实际攻击和关键词。")])


def evasive_chimaera():
    cid="DRG_066"
    def poisonous_and_untargetable():
        g,p,e=game();body=play(p,cid);large=e.summon("CS2_182")
        spell=e.give("CS2_029")
        targetable=body in spell.targets
        g.end_turn();g.end_turn()
        ready=body.can_attack(large)
        if ready:body.attack(large)
        observed=f"poisonous={body.poisonous};spell_targetable={targetable};ready={ready};large={large.zone.name};body={body.zone.name}"
        return check(body.poisonous and not targetable and ready and large.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("poisonous_kills_big_minion_and_enemy_spell_cannot_target","After waiting a turn, Poisonous kills 4/5 Yeti in combat and enemy Fireball has no valid target on Chimaera.",poisonous_and_untargetable,"实际战斗与法术目标集合。")])


def troll_batrider():
    cid="DRG_067"
    def minion_target_not_hero():
        g,p,e=game();enemy=e.summon("CS2_182");body=play(p,cid)
        observed=f"enemy={enemy.health}:{enemy.zone.name};enemy_hero={e.hero.health};body={body.zone.name}"
        return check(enemy.health==2 and e.hero.health==30,observed)
    audit(cid,[("only_enemy_minion_takes_three","With sole enemy Yeti, Battlecry deals 3 to minion and leaves hero intact.",minion_target_not_hero,"敌方随从与英雄目标区分。")])


def living_dragonbreath():
    cid="DRG_068"
    def prevents_friendly_freeze():
        g,p,e=game();body=play(p,cid);ally=p.summon("CS2_182")
        g.end_turn();spell=play(e,"CS2_024",target=ally)
        observed=f"ally_frozen={ally.frozen};ally_health={ally.health};body_frozen={body.frozen};ally_cant={ally.cant_be_frozen};spell={spell.zone.name}"
        return check(not ally.frozen and ally.health==2 and not body.frozen,observed)
    audit(cid,[("friendly_minions_resist_actual_freeze","Enemy Frostbolt damages but cannot Freeze friendly Yeti while Dragonbreath aura active.",prevents_friendly_freeze,"真实敌方冰冻法术与实时光环。")])


def platebreaker():
    cid="DRG_069"
    def removes_only_enemy_armor():
        g,p,e=game();e.hero.armor=13;p.hero.armor=5;body=play(p,cid)
        observed=f"enemy_armor={e.hero.armor};own_armor={p.hero.armor};body={body.zone.name}"
        return check(e.hero.armor==0 and p.hero.armor==5,observed)
    audit(cid,[("enemy_armor_destroyed_friendly_armor_retained","Battlecry removes 13 opponent Armor; 5 friendly Armor remains.",removes_only_enemy_armor,"阵营与护甲。")])


def dragon_breeder():
    cid="DRG_070"
    def copies_target_friendly_dragon():
        g,p,e=game();dragon=p.summon("NEW1_023");other=p.summon(WISP)
        body=play(p,cid,target=dragon);copies=[c for c in p.hand if c.id==dragon.id]
        observed=f"target={dragon.zone.name};copies={[(c.id,c.zone.name) for c in copies]};body={body.zone.name};other={other.zone.name}"
        return check(len(copies)==1 and copies[0] is not dragon and dragon.zone==Zone.PLAY and body.zone==Zone.PLAY,observed)
    audit(cid,[("selected_friendly_dragon_copy_enters_hand","Choosing friendly Dragon adds separate copy to hand without removing original.",copies_target_friendly_dragon,"目标、复制身份及区域。")])


def bad_luck_albatross():
    cid="DRG_071"
    def shuffles_two_enemy_deck_tokens():
        g,p,e=game();body=play(p,cid);body.destroy()
        birds=[c for c in e.deck if c.id=="DRG_071t"]
        own=[c for c in p.deck if c.id=="DRG_071t"]
        observed=f"dead={body.zone.name};enemy={[(c.id,c.atk,c.health,c.zone.name) for c in birds]};own={len(own)}"
        return check(body.zone==Zone.GRAVEYARD and len(birds)==2 and all((c.atk,c.health)==(1,1) for c in birds) and not own,observed)
    audit(cid,[("death_shuffles_two_one_one_into_opponent_deck","Actual death shuffles exactly two 1/1 Albatross into opponent deck, none into own.",shuffles_two_enemy_deck_tokens,"死亡、数量、身材、牌库归属。")])


def skyfin():
    cid="DRG_072"
    def branch(holding):
        g,p,e=game()
        if holding:p.give("NEW1_023")
        body=play(p,cid)
        others=[m for m in p.field if m is not body]
        observed=f"holding={holding};other={[(m.id,[int(x) for x in m.races],m.zone.name) for m in others]};body={body.zone.name}"
        return check(len(others)==(2 if holding else 0) and all(Race.MURLOC in m.races for m in others),observed)
    audit(cid,[("held_dragon_summons_two_murlocs","Held Dragon: two Murlocs summoned on own board.",lambda:branch(True),"条件满足数量及种族。"),
               ("no_dragon_summons_none","No Dragon: no extra summons.",lambda:branch(False),"条件反支。")])


def evasive_feywing():
    cid="DRG_073"
    def excludes_spell_and_hero_power_targets():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        body=play(p,cid);g.end_turn()
        spell=e.give("CS2_029")
        power=e.hero.power
        observed=f"spell_targetable={body in spell.targets};hero_power_targetable={body in power.targets};body={body.zone.name}"
        return check(body not in spell.targets and body not in power.targets and body.zone==Zone.PLAY,observed)
    audit(cid,[("excluded_from_enemy_spell_and_hero_power_target_lists","Enemy Fireball and Mage Hero Power cannot target Feywing.",excludes_spell_and_hero_power_targets,"两个实际目标集合。")])


def camouflaged_dirigible():
    cid="DRG_074"
    def stealth_mechs_excluding_self_until_next_turn():
        g,p,e=game();mech=p.summon("BOT_020");other=p.summon(WISP)
        body=play(p,cid)
        now=(mech.stealthed,other.stealthed,body.stealthed)
        g.end_turn();enemy_turn=mech.stealthed
        g.end_turn();next_own=mech.stealthed
        observed=f"now={now};enemy_turn={enemy_turn};next_own={next_own};mech={mech.zone.name};body={body.zone.name}"
        return check(now==(True,False,False) and enemy_turn and not next_own,observed)
    audit(cid,[("other_mech_stealth_expires_next_own_turn","Only other friendly Mech gains Stealth through enemy turn, removed at next own turn.",stealth_mechs_excluding_self_until_next_turn,"机械筛选、自身排除、回合到期。")])


def cobalt_spellkin():
    cid="DRG_075"
    def adds_two_one_cost_class_spells():
        g,p,e=game(CardClass.MAGE);body=play(p,cid);hand=list(p.hand)
        observed=f"hand={[(c.id,c.cost,int(c.type),[int(x) for x in c.classes],c.zone.name) for c in hand]};body={body.zone.name}"
        return check(len(hand)==2 and all(c.cost==1 and c.type==CardType.SPELL and CardClass.MAGE in c.classes and c.zone==Zone.HAND for c in hand),observed)
    audit(cid,[("adds_two_one_cost_mage_spells","Mage owner receives exactly two 1-Cost Mage spells in hand.",adds_two_one_cost_class_spells,"数量、费用、法术类型、职业和区域。")])


CHECKS={"DRG_006":corrosive_breath,"DRG_007":stormhammer,"DRG_008":righteous_cause,
        "DRG_010":diving_gryphon,"DRG_019":scion_of_ruin,"DRG_020":evil_quartermaster,
        "DRG_021":ritual_chopper,"DRG_022":ramming_speed,"DRG_023":skybarge,
        "DRG_024":sky_raider,"DRG_025":ancharrr,"DRG_026":deathwing_mad_aspect,
        "DRG_027":umbral_skulker,"DRG_028":dragons_hoard,"DRG_030":praise_galakrond,
        "DRG_031":necrium_apothecary,"DRG_033":candle_breath,"DRG_034":stowaway,
        "DRG_035":bloodsail_flybooter,"DRG_036":waxadred,"DRG_037":flik_skyshiv,
        "DRG_049":tasty_flyfish,"DRG_050":devoted_maniac,"DRG_051":strength_in_numbers,
        "DRG_054":big_ol_whelp,"DRG_055":hoard_pillager,"DRG_056":parachute_brigand,
        "DRG_057":hot_air_balloon,"DRG_059":goboglide_tech,"DRG_060":fire_hawk,
        "DRG_061":gyrocopter,"DRG_062":wyrmrest_purifier,"DRG_063":dragonmaw_poacher,
        "DRG_064":zuldak_ritualist,"DRG_065":hippogryph,"DRG_066":evasive_chimaera,
        "DRG_067":troll_batrider,"DRG_068":living_dragonbreath,"DRG_069":platebreaker,
        "DRG_070":dragon_breeder,"DRG_071":bad_luck_albatross,"DRG_072":skyfin,
        "DRG_073":evasive_feywing,"DRG_074":camouflaged_dirigible,"DRG_075":cobalt_spellkin}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
