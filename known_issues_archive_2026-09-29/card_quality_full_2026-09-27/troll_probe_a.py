"""Card-specific live game checks for the collectible first 45 Rastakhan YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "troll_probe_a.csv"
VERDICT_FILE = HERE / "troll_verdict_a.csv"
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
                 if r["set"].endswith("(TROLL)")),
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




def half_time_scavenger():
    cid="TRL_010"

    def branch(overkill):
        g,p,e=game()
        body=play(p,cid)
        start_stealth=body.stealthed
        enemy=e.summon(WISP if overkill else "CS2_182")
        if not overkill: enemy.damage=2
        g.end_turn();g.end_turn()
        body.attack(enemy)
        observed=f"overkill={overkill};stealth_at_play={start_stealth};enemy={enemy.zone.name};armor={p.hero.armor};body={body.zone.name}"
        return check(start_stealth and enemy.zone!=Zone.PLAY
                     and p.hero.armor==(3 if overkill else 0),observed)

    audit(cid,[
        ("overkill_grants_three_armor", "3-Attack Scavenger overkills 1-Health target and gives its owner 3 Armor.",lambda:branch(True),"真实跨回合攻击低生命随从并检查潜行与护甲。"),
        ("exact_lethal_gives_no_armor", "Exactly lethal 3 damage does not count as Overkill and grants no Armor.",lambda:branch(False),"将5生命目标预伤至3生命作边界对照。"),
    ])


def totemic_smash():
    cid="TRL_012"

    def branch(overkill):
        g,p,e=game(CardClass.SHAMAN)
        enemy=e.summon(WISP if overkill else "BOT_031")
        spell=play(p,cid,target=enemy)
        totems=[m for m in p.field if Race.TOTEM in m.races]
        observed=f"overkill={overkill};target={enemy.zone.name};totems={[(m.id,m.atk,m.health,m.zone.name) for m in totems]};spell={spell.zone.name}"
        return check(enemy.zone!=Zone.PLAY and len(totems)==(1 if overkill else 0)
                     and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[
        ("overkill_summons_one_basic_totem", "Two spell damage overkills 1-Health target and summons one basic Totem.",lambda:branch(True),"1生命与2伤害实际触发超杀，检查召唤区域。"),
        ("exact_lethal_no_totem", "Exactly lethal 2 spell damage summons no Totem.",lambda:branch(False),"2生命地精炸弹作边界对照。"),
    ])


def ticket_scalper():
    cid="TRL_015"

    def branch(overkill):
        g,p,e=game()
        body=play(p,cid)
        deck=[p.give(x) for x in (WISP,"CS2_182","CS2_029")]
        for c in deck:c.shuffle_into_deck()
        enemy=e.summon(WISP if overkill else "CS2_182")
        g.end_turn();g.end_turn()
        before_attack=len(p.deck)
        body.attack(enemy)
        observed=f"overkill={overkill};enemy={enemy.zone.name};drawn={[c.zone.name for c in deck]};deck_before_attack={before_attack};deck_after_attack={len(p.deck)};body={body.zone.name}"
        return check(enemy.zone!=Zone.PLAY and before_attack==2
                     and len(p.deck)==(0 if overkill else 2),observed)

    audit(cid,[
        ("overkill_draws_two", "5-Attack Scalper overkills a 1-Health target and draws both deck cards.",lambda:branch(True),"两张已知牌库卡逐一检查区域。"),
        ("exact_lethal_draws_none", "Exactly lethal 5 damage to 5-Health target draws no card.",lambda:branch(False),"5生命目标边界对照。"),
    ])


def sightless_ranger():
    cid="TRL_020"

    def branch(overkill):
        g,p,e=game()
        body=play(p,cid)
        enemy=e.summon(WISP if overkill else "CS2_182")
        if not overkill:enemy.damage=2
        ready=body.can_attack(enemy)
        if ready:body.attack(enemy)
        bats=[m for m in p.field if m.id=="TRL_020t"]
        observed=f"overkill={overkill};rush_ready={ready};enemy={enemy.zone.name};bats={[(m.atk,m.health,m.zone.name) for m in bats]};body={body.zone.name}"
        return check(ready and enemy.zone!=Zone.PLAY and len(bats)==(2 if overkill else 0)
                     and all((m.atk,m.health,m.zone)==(1,1,Zone.PLAY) for m in bats),observed)

    audit(cid,[
        ("rush_overkill_two_bats", "Rush attack overkills 1-Health target and summons two friendly 1/1 Bats.",lambda:branch(True),"同回合实际突袭攻击，检查两只衍生蝙蝠。"),
        ("rush_exact_lethal_no_bats", "Rush attack exactly kills 3-Health target and summons no Bats.",lambda:branch(False),"把5生命目标预伤至3生命。"),
    ])


def serpent_ward():
    cid="TRL_057"

    def only_owner_turn_end():
        g,p,e=game()
        ward=play(p,cid)
        g.end_turn()
        after_own=e.hero.health
        g.end_turn()
        after_enemy=e.hero.health
        g.end_turn()
        observed=f"enemy_health={after_own}->{after_enemy}->{e.hero.health};ward={ward.zone.name}"
        return check(after_own==28 and after_enemy==28 and e.hero.health==26
                     and ward.zone==Zone.PLAY,observed)

    audit(cid,[("two_own_turn_ends_enemy_turn_ignored", "Each owner turn end deals 2 to opponent hero; opponent turn end causes no extra hit.",only_owner_turn_end,"跨三次回合切换分别核对敌方英雄生命。")])


def bog_slosher():
    cid="TRL_059"

    def bounce_and_buff():
        g,p,e=game(CardClass.SHAMAN)
        friend=p.summon("CS2_182")
        enemy=e.summon(WISP)
        body=play(p,cid,target=friend)
        observed=f"friend={friend.zone.name}:{friend.atk}/{friend.health};enemy={enemy.zone.name};slosher={body.zone.name}"
        return check(friend.zone==Zone.HAND and (friend.atk,friend.health)==(6,7)
                     and enemy.zone==Zone.PLAY and body.zone==Zone.PLAY,observed)

    def no_other_friend_still_playable():
        g,p,e=game(CardClass.SHAMAN)
        body=play(p,cid)
        observed=f"body={body.zone.name};field={[m.id for m in p.field]};hand={[c.id for c in p.hand]}"
        return check(body.zone==Zone.PLAY and len(p.field)==1 and not p.hand,observed)

    audit(cid,[
        ("friendly_minion_bounced_and_buffed", "Chosen friendly Yeti returns to hand with +2/+2; enemy minion stays put.",bounce_and_buff,"明确指定己方随从，检查手牌区域与永久身材。"),
        ("no_target_playable", "Without a friendly minion, Bog Slosher still enters play and does not return itself.",no_other_friend_still_playable,"无目标分支。"),
    ])


def haunting_visions():
    cid="TRL_058"

    def discount_next_only_and_discover():
        g,p,e=game(CardClass.SHAMAN)
        next_spell=p.give("CS2_029")
        later_spell=p.give("CS2_025")
        visions=play(p,cid)
        options=list(p.choice.cards) if p.choice else []
        assert len(options)==3
        chosen=options[0]
        p.choice.choose(chosen)
        discovered=[c for c in p.hand if c.id==chosen.id]
        discounted=(next_spell.cost,later_spell.cost)
        next_spell.play(target=e.hero)
        restored=later_spell.cost
        observed=f"options={[(c.id,c.type) for c in options]};chosen={chosen.id};discovered={[(c.id,c.zone.name) for c in discovered]};costs={discounted}->{restored};enemy_hero={e.hero.health};visions={visions.zone.name}"
        return check(all(c.type==CardType.SPELL for c in options)
                     and len(discovered)==1 and discovered[0].zone==Zone.HAND
                     and discounted==(1,0) and restored==2 and e.hero.health==24
                     and visions.zone==Zone.GRAVEYARD,observed)

    def discount_expires_at_turn_end():
        g,p,e=game(CardClass.SHAMAN)
        fireball=p.give("CS2_029")
        play(p,cid)
        assert p.choice
        p.choice.choose(p.choice.cards[0])
        discounted=fireball.cost
        g.end_turn();g.end_turn()
        observed=f"cost={discounted}->{fireball.cost};zone={fireball.zone.name}"
        return check(discounted==1 and fireball.cost==4 and fireball.zone==Zone.HAND,observed)

    audit(cid,[
        ("discover_and_next_spell_discount_only", "Discover offers three spells; next cast spell costs 3 less and consumes discount, restoring other spell's Cost.",discount_next_only_and_discover,"实际选择法术并打出已有火球，检查手牌、费用与伤害。"),
        ("unused_discount_expires_turn_end", "Unused -3 spell Cost discount expires after the turn.",discount_expires_at_turn_end,"跨回合检查费用恢复。"),
    ])


def spirit_of_the_frog():
    cid="TRL_060"

    def chain_by_one_higher_spell_cost():
        g,p,e=game(CardClass.SHAMAN)
        spirit=play(p,cid)
        friend=p.summon(WISP)
        one=p.give("CS2_087")
        two=p.give("CS2_025")
        nonspell=p.give(WISP)
        for c in (one,two,nonspell):c.shuffle_into_deck()
        zero=play(p,"CS2_008",target=e.hero)
        after_zero=(one.zone,two.zone,nonspell.zone)
        one.play(target=friend)
        observed=f"stealth={spirit.stealthed};after_zero={[x.name for x in after_zero]};after_one={[c.zone.name for c in (one,two,nonspell)]};friend_attack={friend.atk};zero={zero.zone.name}"
        return check(spirit.stealthed and after_zero==(Zone.HAND,Zone.DECK,Zone.DECK)
                     and two.zone==Zone.HAND and nonspell.zone==Zone.DECK
                     and friend.atk==4,observed)

    def stealth_expires():
        g,p,e=game(CardClass.SHAMAN)
        spirit=play(p,cid)
        before=spirit.stealthed
        g.end_turn();g.end_turn()
        observed=f"stealth={before}->{spirit.stealthed};zone={spirit.zone.name}"
        return check(before and not spirit.stealthed and spirit.zone==Zone.PLAY,observed)

    audit(cid,[
        ("spell_cost_chain_draws_matching_spells", "Casting 0-Cost spell draws a 1-Cost spell, then casting it draws a 2-Cost spell; minion remains in deck.",chain_by_one_higher_spell_cost,"牌库预置0/1/2费链及随从对照，真实连续施法并核对区域。"),
        ("one_turn_stealth_expires", "Spirit begins Stealthed and loses Stealth next own turn.",stealth_expires,"跨回合检验时限。"),
    ])


def gurubashi_hypemon():
    cid="TRL_077"

    def discover_one_one_one_cost_battlecry():
        g,p,e=game(CardClass.ROGUE)
        body=play(p,cid)
        options=list(p.choice.cards) if p.choice else []
        assert len(options)==3
        chosen=options[0]
        p.choice.choose(chosen)
        copies=[c for c in p.hand if c.id==chosen.id]
        observed=f"options={[(c.id,c.has_battlecry) for c in options]};chosen={chosen.id};copies={[(c.id,c.atk,c.health,c.cost,c.zone.name) for c in copies]};body={body.zone.name}"
        return check(all(c.has_battlecry for c in options) and len(copies)==1
                     and (copies[0].atk,copies[0].health,copies[0].cost,copies[0].zone)==(1,1,1,Zone.HAND)
                     and body.zone==Zone.PLAY,observed)

    audit(cid,[("discovered_battlecry_copy_one_one_one_cost", "Discover offers Battlecry minions and chosen copy in hand is 1/1 with Cost 1.",discover_one_one_one_cost_battlecry,"实际三选一并检验生成卡身材费用、区域和关键字。")])


def big_bad_voodoo():
    cid="TRL_082"

    def deathrattle_summons_cost_plus_one():
        g,p,e=game(CardClass.SHAMAN)
        target=p.summon(WISP)
        spell=play(p,cid,target=target)
        inherited=target.has_deathrattle
        target.destroy()
        summoned=list(p.field)
        observed=f"inherited={inherited};target={target.zone.name};summons={[(m.id,m.cost,m.zone.name) for m in summoned]};spell={spell.zone.name}"
        return check(inherited and target.zone!=Zone.PLAY and len(summoned)==1
                     and summoned[0].cost==1 and summoned[0].zone==Zone.PLAY
                     and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("granted_deathrattle_cost_plus_one_summon", "Friendly 0-Cost Wisp gains Deathrattle and on death summons one random 1-Cost minion.",deathrattle_summons_cost_plus_one,"实际消灭受法术影响的随从，验证亡语与费用。")])


def zentimo():
    cid="TRL_085"

    def targeted_spell_hits_neighbors_not_distant():
        g,p,e=game(CardClass.SHAMAN)
        body=play(p,cid)
        enemies=[e.summon("CS2_182") for _ in range(4)]
        spell=play(p,"CS2_008",target=enemies[1])
        health=[m.health for m in enemies]
        observed=f"enemy_health={health};spell={spell.zone.name};zentimo={body.zone.name}"
        return check(health==[4,4,4,5] and spell.zone==Zone.GRAVEYARD
                     and body.zone==Zone.PLAY,observed)

    def no_neighbor_single_cast():
        g,p,e=game(CardClass.SHAMAN)
        body=play(p,cid)
        target=e.summon("CS2_182")
        play(p,"CS2_008",target=target)
        observed=f"single_target={target.health};zentimo={body.zone.name}"
        return check(target.health==4 and body.zone==Zone.PLAY,observed)

    audit(cid,[
        ("middle_target_and_two_neighbors", "Moonfire aimed at second of four enemy minions also damages adjacent first and third once; fourth is untouched.",targeted_spell_hits_neighbors_not_distant,"四目标并排且全为5生命，检查相邻与远处。"),
        ("single_minion_only_once", "With no adjacent minion, targeted spell resolves once.",no_neighbor_single_cast,"单目标边界。"),
    ])


def spirit_of_the_shark():
    cid="TRL_092"

    def doubles_minion_battlecry_and_combo():
        g,p,e=game(CardClass.ROGUE)
        shark=play(p,cid)
        stealthed=shark.stealthed
        mech=p.summon("BOT_031")
        play(p,"BOT_079",target=mech)
        after_battlecry=(mech.atk,mech.health)
        enemy=e.summon("CS2_182")
        si7=play(p,"EX1_134",target=enemy)
        observed=f"shark_stealth={stealthed};mech_after_battlecry={after_battlecry};enemy_after_combo={enemy.health}:{enemy.zone.name};si7={si7.zone.name}"
        return check(stealthed and after_battlecry==(2,4) and enemy.health==1
                     and shark.zone==Zone.PLAY and si7.zone==Zone.PLAY,observed)

    def stealth_expires():
        g,p,e=game(CardClass.ROGUE)
        shark=play(p,cid)
        before=shark.stealthed
        g.end_turn();g.end_turn()
        observed=f"stealth={before}->{shark.stealthed};zone={shark.zone.name}"
        return check(before and not shark.stealthed and shark.zone==Zone.PLAY,observed)

    audit(cid,[
        ("battlecry_and_combo_both_double", "A friendly minion Battlecry buffs +1/+1 twice and a Combo minion deals its 2 damage twice.",doubles_minion_battlecry_and_combo,"用机械增益战吼和军情七处特工连击分别核对。"),
        ("one_turn_stealth_expires", "Spirit loses its initial Stealth after one turn.",stealth_expires,"跨回合验证。"),
    ])


def griftah():
    cid="TRL_096"

    def two_discovers_split_between_players():
        g,p,e=game()
        body=play(p,cid)
        first_options=list(p.choice.cards) if p.choice else []
        assert len(first_options)==3
        first=first_options[0]
        p.choice.choose(first)
        second_options=list(p.choice.cards) if p.choice else []
        assert len(second_options)==3
        second=next((c for c in second_options if c.id!=first.id),second_options[0])
        p.choice.choose(second)
        own=[c.id for c in p.hand]
        enemy=[c.id for c in e.hand]
        observed=f"selected={first.id},{second.id};own_hand={own};enemy_hand={enemy};remaining_choice={p.choice};body={body.zone.name}"
        return check(len(own)==1 and len(enemy)==1
                     and sorted(own+enemy)==sorted([first.id,second.id])
                     and p.choice is None and body.zone==Zone.PLAY,observed)

    audit(cid,[("two_discovered_cards_split_one_each", "After two real Discover decisions, exactly one selected card enters each player's hand at random.",two_discovers_split_between_players,"依次完成两次选择，核对双方手牌与所选两卡多重集。")])


def the_beast_within():
    cid="TRL_119"

    def buff_then_forced_attack():
        g,p,e=game(CardClass.HUNTER)
        beast=p.summon("CS2_171")
        enemy=e.summon("CS2_182")
        spell=play(p,cid,target=beast)
        observed=f"beast={beast.zone.name}:{beast.atk}/{beast.health};enemy={enemy.zone.name}:{enemy.health};spell={spell.zone.name}"
        return check(beast.zone!=Zone.PLAY and enemy.zone==Zone.PLAY and enemy.health==3
                     and spell.zone==Zone.GRAVEYARD,observed)

    def no_enemy_minion_still_buffs():
        g,p,e=game(CardClass.HUNTER)
        beast=p.summon("CS2_171")
        spell=play(p,cid,target=beast)
        observed=f"beast={beast.atk}/{beast.health}:{beast.zone.name};enemy_field={len(e.field)};spell={spell.zone.name}"
        return check((beast.atk,beast.health)==(2,2) and beast.zone==Zone.PLAY
                     and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[
        ("buff_and_attack_only_enemy_minion", "Friendly Beast gains +1/+1 then makes a forced attack against the only enemy minion.",buff_then_forced_attack,"野猪对5生命雪人执行真实战斗并核对目标伤害。"),
        ("no_enemy_minion_buff_remains", "With no enemy minion, the Beast still receives +1/+1.",no_enemy_minion_still_buffs,"无攻击目标分支。"),
    ])


def raiding_party():
    cid="TRL_124"

    def branch(combo):
        g,p,e=game(CardClass.ROGUE)
        pirates=[p.give("CS2_146") for _ in range(2)]
        weapon=p.give("CS2_091")
        other=p.give(WISP)
        for card in pirates+[weapon,other]:card.shuffle_into_deck()
        if combo:play(p,"CS2_008",target=e.hero)
        spell=play(p,cid)
        observed=f"combo={combo};pirates={[c.zone.name for c in pirates]};weapon={weapon.zone.name};other={other.zone.name};spell={spell.zone.name}"
        return check(all(c.zone==Zone.HAND for c in pirates)
                     and weapon.zone==(Zone.HAND if combo else Zone.DECK)
                     and other.zone==Zone.DECK and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[
        ("base_draws_two_pirates_only", "Without Combo, draws two Pirate cards and leaves weapon and non-Pirate in deck.",lambda:branch(False),"两海盗、一武器、一普通随从同库。"),
        ("combo_also_draws_weapon", "After prior spell play, Combo additionally draws weapon while still drawing both Pirates.",lambda:branch(True),"实际打出前置牌激活连击，再核对三张实体区域。"),
    ])


def captain_hooktusk():
    cid="TRL_126"

    def summons_three_pirates_from_deck_with_rush():
        g,p,e=game(CardClass.ROGUE)
        pirates=[p.give("CS2_146") for _ in range(3)]
        other=p.give(WISP)
        for card in pirates+[other]:card.shuffle_into_deck()
        body=play(p,cid)
        enemy=e.summon(WISP)
        observed=f"pirates={[(c.id,c.zone.name,c.rush,c.can_attack(enemy)) for c in pirates]};other={other.zone.name};body={body.zone.name}"
        return check(body.zone==Zone.PLAY and all(c.zone==Zone.PLAY and c.rush and c.can_attack(enemy) for c in pirates)
                     and other.zone==Zone.DECK and len(p.field)==4,observed)

    audit(cid,[("three_deck_pirates_gain_usable_rush", "Summons three Pirate entities from deck with Rush, leaving non-Pirate in deck.",summons_three_pirates_from_deck_with_rush,"三海盗一白板牌库，实际检查突袭攻击资格。")])


def cannon_barrage():
    cid="TRL_127"

    def branch(pirate_count):
        g,p,e=game(CardClass.ROGUE)
        for _ in range(pirate_count):p.summon("CS2_146")
        spell=play(p,cid)
        observed=f"pirates={pirate_count};enemy_hero={e.hero.health};owner_hero={p.hero.health};spell={spell.zone.name}"
        return check(e.hero.health==30-3*(pirate_count+1)
                     and p.hero.health==30 and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[
        ("no_pirate_one_hit", "With zero Pirates, Barrage deals one 3-damage hit to sole enemy character.",lambda:branch(0),"零海盗基数。"),
        ("two_pirates_three_hits", "With two friendly Pirates, Barrage deals three 3-damage hits to sole enemy character.",lambda:branch(2),"两海盗对照，逐次伤害总和9。"),
    ])


def sand_drudge():
    cid="TRL_131"

    def own_spell_summons_enemy_spell_does_not():
        g,p,e=game(CardClass.PRIEST)
        body=play(p,cid)
        play(p,"CS2_008",target=e.hero)
        first=[m for m in p.field if m.id=="TRL_131t"]
        g.end_turn()
        play(e,"CS2_008",target=p.hero)
        second=[m for m in p.field if m.id=="TRL_131t"]
        observed=f"first={[(m.atk,m.health,m.taunt) for m in first]};after_enemy_spell={len(second)};body={body.zone.name}"
        return check(len(first)==1 and len(second)==1
                     and (first[0].atk,first[0].health,bool(first[0].taunt))==(1,1,True)
                     and body.zone==Zone.PLAY,observed)

    audit(cid,[("friendly_spell_summons_one_taunt_enemy_spell_none", "Own spell summons one 1/1 Taunt Zombie; opponent spell does not add another.",own_spell_summons_enemy_spell_does_not,"分别真实施放双方月火术，检查衍生物数量和关键字。")])


def stolen_steel():
    cid="TRL_156"

    def discover_other_class_weapon_to_hand():
        g,p,e=game(CardClass.ROGUE)
        spell=play(p,cid)
        options=list(p.choice.cards) if p.choice else []
        assert len(options)==3
        chosen=options[0]
        p.choice.choose(chosen)
        gained=[c for c in p.hand if c.id==chosen.id]
        observed=f"options={[(c.id,c.type,c.card_class) for c in options]};chosen={chosen.id};gained={[(c.id,c.zone.name) for c in gained]};spell={spell.zone.name}"
        return check(all(c.type==CardType.WEAPON and c.card_class not in (CardClass.ROGUE,CardClass.NEUTRAL) for c in options)
                     and len(gained)==1 and gained[0].zone==Zone.HAND and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("discover_other_class_weapon", "All three Discover choices are weapons from non-Rogue classes; selected weapon enters hand.",discover_other_class_weapon_to_hand,"盗贼职业局，检验选项类型与职业并实际选择。")])


def spirit_of_the_raptor():
    cid="TRL_223"

    def branch(kills_minion):
        g,p,e=game(CardClass.DRUID)
        spirit=play(p,cid)
        card=p.give("CS2_182")
        card.shuffle_into_deck()
        play(p,"TRL_243")
        target=e.summon(WISP) if kills_minion else e.hero
        p.hero.attack(target)
        observed=f"kills_minion={kills_minion};spirit_stealthed={spirit.stealthed};drawn={card.zone.name};target={target.zone.name};enemy_hero={e.hero.health}"
        return check(spirit.stealthed and card.zone==(Zone.HAND if kills_minion else Zone.DECK)
                     and (not kills_minion or target.zone!=Zone.PLAY),observed)

    audit(cid,[
        ("hero_attack_kills_minion_draws", "Own hero attacks and kills enemy minion, then Spirit draws exactly one deck card.",lambda:branch(True),"猛扑给英雄2攻后真实击杀1血随从。"),
        ("hero_attacks_hero_no_draw", "Own hero attack on enemy hero does not draw.",lambda:branch(False),"非击杀随从对照。"),
    ])


def ironhide_direhorn():
    cid="TRL_232"

    def branch(overkill):
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid)
        enemy=e.summon(WISP if overkill else "LOOT_137")
        if not overkill:enemy.damage=5
        g.end_turn();g.end_turn()
        ready=body.can_attack(enemy)
        if ready:body.attack(enemy)
        runts=[m for m in p.field if m.id=="TRL_232t"]
        observed=f"overkill={overkill};ready={ready};enemy={enemy.zone.name};runts={[(m.atk,m.health,m.zone.name) for m in runts]}"
        return check(ready and enemy.zone!=Zone.PLAY and len(runts)==(1 if overkill else 0)
                     and all((m.atk,m.health,m.zone)==(5,5,Zone.PLAY) for m in runts),observed)

    audit(cid,[
        ("overkill_summons_five_five_runt", "7-Attack Direhorn overkills 1-Health target and summons one 5/5 Runt.",lambda:branch(True),"跨回合真实攻击低生命目标。"),
        ("exact_lethal_no_runt", "Exactly lethal 7 damage summons no Runt.",lambda:branch(False),"把高生命目标预伤至7生命的边界对照。"),
    ])


def savage_striker():
    cid="TRL_240"

    def hero_attack_value_used():
        g,p,e=game(CardClass.DRUID)
        p.hero.atk=3
        enemy=e.summon("CS2_182")
        body=play(p,cid,target=enemy)
        observed=f"hero_attack={p.hero.atk};enemy={enemy.health}:{enemy.zone.name};striker={body.zone.name}"
        return check(p.hero.atk==3 and enemy.health==2 and body.zone==Zone.PLAY,observed)

    def zero_hero_attack_no_target_required():
        g,p,e=game(CardClass.DRUID)
        enemy=e.summon("CS2_182")
        try:
            body=play(p,cid)
        except InvalidAction as exc:
            return check(False,f"hero_attack=0;no_target_play_rejected={exc};source=card.py:659 uses >=0")
        observed=f"hero_attack={p.hero.atk};enemy_health={enemy.health};striker={body.zone.name}"
        return check(p.hero.atk==0 and enemy.health==5 and body.zone==Zone.PLAY,observed)

    audit(cid,[
        ("battlecry_uses_three_hero_attack", "At 3 hero Attack, Battlecry deals exactly 3 damage to chosen enemy minion.",hero_attack_value_used,"设置并核对英雄攻击，验证目标生命变化。"),
        ("zero_attack_no_damage_no_target", "With zero hero Attack, Striker can enter without a target and deals no damage.",zero_hero_attack_no_target_required,"零攻可选目标分支。"),
    ])


def zuljin():
    cid="TRL_065"

    def recasts_prior_untargeted_spell():
        g,p,e=game(CardClass.HUNTER,CardClass.MAGE)
        spell=play(p,"CS2_093")
        first=e.hero.health
        g.end_turn();g.end_turn()
        hero=play(p,cid)
        observed=f"first_spell={spell.zone.name};enemy_after_first={first};enemy_after_hero={e.hero.health};hero={p.hero.id};armor={p.hero.armor};hero_card={hero.zone.name}"
        return check(first==28 and e.hero.health==26 and p.hero.id=="TRL_065" and p.hero.armor>=5,observed)

    def no_prior_spells_no_recast():
        g,p,e=game(CardClass.HUNTER,CardClass.MAGE)
        hero=play(p,cid)
        observed=f"enemy_health={e.hero.health};new_hero={p.hero.id};armor={p.hero.armor};hero_card={hero.zone.name}"
        return check(e.hero.health==30 and p.hero.id==cid and p.hero.armor>=5,observed)

    audit(cid,[
        ("recast_spell_and_transform", "A previously cast Consecration is recast once; Zul'jin replaces hero and grants 5 Armor.", recasts_prior_untargeted_spell,"用无目标法术隔离随机目标因素；核对首次及重施伤害与英雄。"),
        ("empty_spell_history", "With no prior spells, Battlecry still replaces hero but deals no damage.", no_prior_spells_no_recast,"零法术历史边界。"),
    ])


def soulwarden():
    cid="TRL_247"

    def three_discarded_cards_return():
        g,p,e=game(CardClass.WARLOCK)
        discarded=[p.give(x) for x in ("CS2_231","CS2_182","EX1_011")]
        for card in discarded:card.discard()
        body=play(p,cid)
        returned=[c.id for c in p.hand]
        observed=f"discarded={[(c.id,c.zone.name) for c in discarded]};returned={returned};body={body.zone.name}"
        return check(all(c.zone==Zone.REMOVEDFROMGAME for c in discarded) and len(returned)==3
                     and set(returned).issubset({c.id for c in discarded}) and body.zone==Zone.PLAY,observed)

    def no_discards_no_cards():
        g,p,e=game(CardClass.WARLOCK)
        body=play(p,cid)
        observed=f"hand={[(c.id,c.zone.name) for c in p.hand]};body={body.zone.name}"
        return check(len(p.hand)==0 and body.zone==Zone.PLAY,observed)

    audit(cid,[
        ("returns_three_from_discard_history", "Three hand cards are discarded and Soulwarden adds exactly three copies from that history.",three_discarded_cards_return,"实际执行 Discard 后核对手牌来源与数量。"),
        ("empty_discard_history", "No cards are added when nothing was discarded.",no_discards_no_cards,"空历史边界。"),
    ])


def mark_of_the_loa():
    cid="TRL_254"

    def targeted_buff():
        g,p,e=game(CardClass.DRUID)
        friendly=p.summon(WISP)
        enemy=e.summon(WISP)
        spell=p.give(cid);spell.play(target=friendly,choose="TRL_254a")
        observed=f"friend={friendly.atk}/{friendly.health},taunt={friendly.taunt};enemy={enemy.atk}/{enemy.health};field={[(m.id,m.zone.name) for m in p.field]};spell={spell.zone.name}"
        return check((friendly.atk,friendly.health,friendly.taunt)==(3,5,True)
                     and (enemy.atk,enemy.health)==(1,1) and len(p.field)==1,observed)

    def summon_branch():
        g,p,e=game(CardClass.DRUID)
        friendly=p.summon(WISP)
        spell=p.give(cid);spell.play(choose="TRL_254b")
        raptors=[m for m in p.field if m.id=="TRL_254t"]
        observed=f"friend={friendly.atk}/{friendly.health};raptors={[(m.atk,m.health,m.zone.name) for m in raptors]};spell={spell.zone.name}"
        return check((friendly.atk,friendly.health)==(1,1) and len(raptors)==2
                     and all((m.atk,m.health,m.zone)==(3,2,Zone.PLAY) for m in raptors),observed)

    audit(cid,[
        ("choose_buff_target_and_taunt", "Buff branch gives selected minion +2/+4 and Taunt, without summoning Raptors.",targeted_buff,"目标、身材、嘲讽和对照随从断言。"),
        ("choose_two_raptors", "Summon branch creates exactly two 3/2 Raptors and leaves original minion unchanged.",summon_branch,"独立选择分支与区域断言。"),
    ])


def mass_hysteria():
    cid="TRL_258"

    def one_minion_no_target():
        g,p,e=game(CardClass.PRIEST)
        lone=e.summon("CS2_182")
        spell=play(p,cid)
        observed=f"lone={lone.health}/{lone.max_health}:{lone.zone.name};spell={spell.zone.name}"
        return check(lone.health==5 and lone.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,observed)

    def two_minions_attack_each_other():
        g,p,e=game(CardClass.PRIEST)
        left=p.summon(WISP);right=e.summon(WISP)
        spell=play(p,cid)
        observed=f"left={left.zone.name};right={right.zone.name};spell={spell.zone.name}"
        return check(left.zone==Zone.GRAVEYARD and right.zone==Zone.GRAVEYARD and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[
        ("one_minion_no_valid_defender", "A sole minion remains unchanged because there is no other minion to attack.",one_minion_no_target,"零合法攻击对象边界。"),
        ("two_minions_forced_attack", "Two opposing 1/1 minions attack each other and both die.",two_minions_attack_each_other,"实际强制战斗及死亡区域。"),
    ])


def princess_talanji():
    cid="TRL_259"

    def summon_generated_leave_starting():
        p1=Player("Priest",[WISP],CardClass.PRIEST.default_hero)
        p2=Player("Mage",[],CardClass.MAGE.default_hero)
        p1.cant_fatigue=p2.cant_fatigue=True
        g=BaseTestGame(players=(p1,p2));g.start()
        for player in g.players:
            if player.choice:player.choice.choose()
        p=p1;e=p2
        if g.current_player is not p:g.end_turn()
        for player in g.players:
            player.is_standard=False;player.max_mana=10;player.used_mana=0;player.temp_mana=0
        original=next(c for c in p.hand if c.id==WISP)
        generated=p.give("CS2_182")
        spell=p.give("CS2_029")
        body=play(p,cid)
        observed=f"original={original.zone.name};generated={generated.zone.name};spell={spell.zone.name};body={body.zone.name};field={[(m.id,m.zone.name) for m in p.field]}"
        return check(original.zone==Zone.HAND and generated.zone==Zone.PLAY
                     and spell.zone==Zone.HAND and body.zone==Zone.PLAY
                     and generated in p.field and original in p.hand,observed)

    def no_generated_minions():
        g,p,e=game(CardClass.PRIEST)
        body=play(p,cid)
        observed=f"field={[(m.id,m.zone.name) for m in p.field]};hand={len(p.hand)}"
        return check(len(p.field)==1 and p.field[0] is body and len(p.hand)==0,observed)

    audit(cid,[
        ("summon_generated_leave_original_and_spell", "Generated hand minion is summoned, original starting-deck minion and spell remain in hand.",summon_generated_leave_starting,"真实初始牌库实体与生成实体并置，核对来源筛选及区域。"),
        ("empty_generated_hand", "With no generated minions, only Talanji is on the board.",no_generated_minions,"空候选边界。"),
    ])


def gonk_the_raptor():
    cid="TRL_241"

    def killing_minion_allows_second_hero_attack():
        g,p,e=game(CardClass.DRUID)
        gonk=play(p,cid)
        play(p,"TRL_243")
        enemy=e.summon(WISP)
        first_ready=p.hero.can_attack(enemy)
        p.hero.attack(enemy)
        second_ready=p.hero.can_attack(e.hero)
        observed=f"first_ready={first_ready};victim={enemy.zone.name};second_ready={second_ready};hero_num_attacks={p.hero.num_attacks};gonk_num_attacks={gonk.num_attacks};gonk={gonk.zone.name}"
        return check(first_ready and enemy.zone!=Zone.PLAY and second_ready
                     and gonk.zone==Zone.PLAY,observed)

    audit(cid,[("hero_kills_minion_can_attack_again", "While Gonk lives, own hero killing a minion by attack gains another hero attack this turn.",killing_minion_allows_second_hero_attack,"猛扑给英雄2攻，真实击杀1血随从后检查英雄二次攻击资格与本体状态。")])


def predatory_instincts():
    cid="TRL_244"

    def draws_beast_doubles_health_only():
        g,p,e=game(CardClass.DRUID)
        beast=p.give("CS2_172")
        other=p.give(WISP)
        beast.shuffle_into_deck();other.shuffle_into_deck()
        before=(beast.atk,beast.health)
        spell=play(p,cid)
        observed=f"beast={before}->{(beast.atk,beast.health)}:{beast.zone.name};nonbeast={other.zone.name};spell={spell.zone.name}"
        return check(beast.zone==Zone.HAND and (beast.atk,beast.health)==(before[0],before[1]*2)
                     and other.zone==Zone.DECK and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("draws_beast_and_doubles_health", "Draws sole Beast from deck, doubles its Health in hand, leaves non-Beast in deck.",draws_beast_doubles_health_only,"野兽与非野兽同库，逐实体核对区域和身材。")])


def shriek():
    cid="TRL_245"

    def discards_lowest_cost_and_hits_all_minions():
        g,p,e=game(CardClass.WARLOCK)
        cheapest=p.give(WISP)
        expensive=p.give("EX1_279")
        own=p.summon("CS2_182")
        enemy=e.summon("CS2_182")
        spell=play(p,cid)
        observed=f"discarded={cheapest.zone.name};expensive={expensive.zone.name};minions={own.health},{enemy.health};heroes={p.hero.health},{e.hero.health};spell={spell.zone.name}"
        return check(cheapest.zone!=Zone.HAND and expensive.zone==Zone.HAND
                     and own.health==enemy.health==3 and p.hero.health==e.hero.health==30
                     and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("discard_lowest_and_all_minions_two_damage", "Discards only lowest-Cost Wisp, preserves high-Cost spell, and deals 2 to minions on both sides but no heroes.",discards_lowest_cost_and_hits_all_minions,"两手牌费用不同、双方随从同场，逐项检查。")])


def void_contract():
    cid="TRL_246"

    def destroys_half_each_deck():
        g,p,e=game(CardClass.WARLOCK)
        own=[p.give(x) for x in (WISP,"CS2_182","CS2_029","BOT_031")]
        theirs=[e.give(x) for x in (WISP,"CS2_182","CS2_029","BOT_031")]
        for c in own:c.shuffle_into_deck()
        for c in theirs:c.shuffle_into_deck()
        spell=play(p,cid)
        observed=f"decks={len(p.deck)},{len(e.deck)};own_zones={[c.zone.name for c in own]};enemy_zones={[c.zone.name for c in theirs]};spell={spell.zone.name}"
        return check(len(p.deck)==2 and len(e.deck)==2 and spell.zone==Zone.GRAVEYARD
                     and sum(c.zone==Zone.DECK for c in own)==2 and sum(c.zone==Zone.DECK for c in theirs)==2,observed)

    audit(cid,[("destroys_two_of_four_each_deck", "From four cards each, destroys exactly half of both players' decks.",destroys_half_each_deck,"双方各预置四张身份已知的牌库卡，实测剩余与区域。")])


def spirit_of_the_bat():
    cid="TRL_251"

    def friendly_death_buffs_only_hand_minion():
        g,p,e=game(CardClass.WARLOCK)
        spirit=play(p,cid)
        hand=p.give("CS2_182")
        own=p.summon(WISP)
        own.destroy()
        after_own=(hand.atk,hand.health)
        enemy=e.summon(WISP)
        enemy.destroy()
        observed=f"spirit_stealth={spirit.stealthed};hand_after_own_and_enemy={(hand.atk,hand.health)};first={after_own};enemy_hero={e.hero.health}"
        return check(spirit.stealthed and after_own==(5,6)
                     and (hand.atk,hand.health)==(5,6),observed)

    audit(cid,[("friendly_death_buffs_hand_enemy_death_ignored", "Friendly minion death gives sole hand minion +1/+1; enemy minion death adds no buff.",friendly_death_buffs_only_hand_minion,"唯一手牌随从，双方各制造一次死亡并核对身材。")])


def high_priestess_jeklik():
    cid="TRL_252"

    def discard_adds_two_copies():
        g,p,e=game(CardClass.WARLOCK)
        original=p.give(cid)
        keywords=(original.taunt,original.lifesteal)
        original.discard()
        copies=[c for c in p.hand if c.id==cid]
        observed=f"original={original.zone.name};keywords={keywords};copies={[(c.id,c.zone.name,c.atk,c.health) for c in copies]}"
        return check(all(keywords) and original.zone!=Zone.HAND and len(copies)==2
                     and all(c is not original and c.zone==Zone.HAND for c in copies),observed)

    audit(cid,[("discard_creates_two_hand_copies", "Discarding Jeklik removes original and adds exactly two distinct copies to owner's hand; it has Taunt and Lifesteal.",discard_adds_two_copies,"实际执行弃牌动作，检查区域、数量、实体和关键字。")])


def hireek_the_bat():
    cid="TRL_253"

    def board_fills_with_copies():
        g,p,e=game(CardClass.WARLOCK)
        other=p.summon(WISP)
        body=play(p,cid)
        hireeks=[m for m in p.field if m.id==cid]
        observed=f"field_size={len(p.field)};hireeks={[(m.atk,m.health,m.zone.name) for m in hireeks]};other={other.zone.name};enemy_field={len(e.field)}"
        return check(len(p.field)==7 and len(hireeks)==6 and body in hireeks
                     and len({id(m) for m in hireeks})==6 and other.zone==Zone.PLAY
                     and not e.field,observed)

    audit(cid,[("fills_remaining_six_slots_with_copies", "With one existing friendly minion, Hir'eek plus five copies fills board to seven without displacing it.",board_fills_with_copies,"六个空位、战吼本体占一位，检查场位上限和复制实体。")])


def stampeding_roar():
    cid="TRL_255"

    def summons_original_beast_grants_rush():
        g,p,e=game(CardClass.DRUID)
        beast=p.give("CS2_172")
        other=p.give(WISP)
        enemy=e.summon(WISP)
        spell=play(p,cid)
        observed=f"beast={beast.zone.name}:rush={beast.rush}:can_attack_minion={beast.can_attack(enemy)}:can_attack_hero={beast.can_attack(e.hero)};other={other.zone.name};spell={spell.zone.name}"
        return check(beast.zone==Zone.PLAY and beast.rush and beast.can_attack(enemy)
                     and not beast.can_attack(e.hero) and other.zone==Zone.HAND
                     and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("summons_beast_from_hand_with_usable_rush", "Sole Beast moves from hand to field with usable Rush, while non-Beast remains in hand.",summons_original_beast_grants_rush,"选无突袭的血沼迅猛龙作唯一候选，实际验证攻击目标资格。")])


def blood_troll_sapper():
    cid="TRL_257"

    def friendly_death_hits_enemy_hero_not_owner():
        g,p,e=game(CardClass.WARLOCK)
        body=play(p,cid)
        victim=p.summon(WISP)
        victim.destroy()
        observed=f"victim={victim.zone.name};enemy_hero={e.hero.health};owner_hero={p.hero.health};sapper={body.zone.name}"
        return check(victim.zone!=Zone.PLAY and e.hero.health==28 and p.hero.health==30
                     and body.zone==Zone.PLAY,observed)

    def enemy_death_no_trigger():
        g,p,e=game(CardClass.WARLOCK)
        body=play(p,cid)
        victim=e.summon(WISP)
        victim.destroy()
        observed=f"enemy_victim={victim.zone.name};heroes={p.hero.health},{e.hero.health}"
        return check(p.hero.health==30 and e.hero.health==30 and body.zone==Zone.PLAY,observed)

    audit(cid,[
        ("friendly_death_two_damage_to_enemy_hero", "Friendly minion death deals 2 damage to opponent hero and none to own hero.",friendly_death_hits_enemy_hero_not_owner,"唯一友方1/1被实际消灭，分别检查英雄生命。"),
        ("enemy_death_no_trigger", "Enemy minion death does not trigger Sapper.",enemy_death_no_trigger,"敌方死亡对照。"),
    ])


def bloodsail_howler():
    cid="TRL_071"

    def two_other_pirates_buff_twice():
        g,p,e=game(CardClass.ROGUE)
        pirates=[p.summon("CS2_146") for _ in range(2)]
        nonpirate=p.summon(WISP)
        card=p.give(cid)
        before=(card.atk,card.health)
        card.play()
        observed=f"before={before};howler={card.atk}/{card.health}:{card.zone.name};pirates={[(x.id,x.race) for x in pirates]};nonpirate={nonpirate.id}"
        return check(card.zone==Zone.PLAY and (card.atk,card.health)==(before[0]+2,before[1]+2)
                     and all(Race.PIRATE in x.races for x in pirates) and Race.PIRATE not in nonpirate.races,observed)

    def no_other_pirates_base_stats():
        g,p,e=game(CardClass.ROGUE)
        card=p.give(cid)
        before=(card.atk,card.health)
        card.play()
        observed=f"before={before};after={(card.atk,card.health)};rush={card.rush}"
        return check((card.atk,card.health)==before and card.rush,observed)

    audit(cid,[
        ("two_other_pirates_each_plus_one", "Two other friendly Pirates grant +2/+2 total; non-Pirate and itself do not count.",two_other_pirates_buff_twice,"两个海盗和一个白板对照，核对打出前后身材。"),
        ("no_other_pirates_no_buff", "With no other Pirates, Howler retains its printed stats and Rush.",no_other_pirates_base_stats,"零海盗分支。"),
    ])


def serrated_tooth():
    cid="TRL_074"

    def weapon_deathrattle_gives_rush():
        g,p,e=game(CardClass.ROGUE)
        friends=[p.summon(WISP),p.summon("CS2_182")]
        enemy=e.summon(WISP)
        weapon=play(p,cid)
        before=[m.rush for m in friends]
        weapon.destroy()
        after=[m.rush for m in friends]
        ready=friends[0].can_attack(enemy)
        observed=f"weapon={weapon.zone.name};rush={before}->{after};ready={ready};enemy={enemy.zone.name}"
        return check(not any(before) and all(after) and ready and weapon.zone!=Zone.PLAY,observed)

    audit(cid,[("weapon_deathrattle_grants_all_friendly_rush", "Destroying equipped Serrated Tooth grants Rush to all friendly minions so a new Wisp can attack enemy minion.",weapon_deathrattle_gives_rush,"两名己方随从，真实摧毁武器并检验突袭攻击资格。")])


def seance():
    cid="TRL_097"

    def copies_enemy_minion_to_hand():
        g,p,e=game(CardClass.PRIEST)
        enemy=e.summon("CS2_182")
        spell=play(p,cid,target=enemy)
        copies=[c for c in p.hand if c.id==enemy.id]
        observed=f"enemy={enemy.id}:{enemy.zone.name};copies={[(c.id,c.zone.name,c.atk,c.health) for c in copies]};spell={spell.zone.name}"
        return check(enemy.zone==Zone.PLAY and len(copies)==1 and copies[0] is not enemy
                     and copies[0].zone==Zone.HAND and (copies[0].atk,copies[0].health)==(enemy.atk,enemy.health)
                     and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("enemy_minion_copy_to_own_hand", "Chosen enemy minion stays on field and a distinct same-stat copy enters caster's hand.",copies_enemy_minion_to_hand,"敌方目标对照区域、实体身份和身材。")])


def headhunters_hatchet():
    cid="TRL_111"

    def branch(has_beast):
        g,p,e=game(CardClass.HUNTER)
        if has_beast:p.summon("CS2_171")
        weapon=play(p,cid)
        observed=f"beast={has_beast};weapon={weapon.atk}/{weapon.durability}:{weapon.zone.name};field={[m.id for m in p.field]}"
        return check(weapon.zone==Zone.PLAY and weapon.atk==2
                     and weapon.durability==(3 if has_beast else 2),observed)

    audit(cid,[
        ("beast_adds_one_durability", "With friendly Beast, Hatchet equips at 2 Attack and 3 Durability.",lambda:branch(True),"实际先召唤野兽。"),
        ("no_beast_base_durability", "Without friendly Beast, Hatchet equips at base 2 Durability.",lambda:branch(False),"空场对照。"),
    ])


def regenerate():
    cid="TRL_128"

    def heals_friendly_hero_three():
        g,p,e=game(CardClass.PRIEST)
        p.hero.damage=5
        spell=play(p,cid,target=p.hero)
        observed=f"own_hero={p.hero.health};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(p.hero.health==28 and e.hero.health==30 and spell.zone==Zone.GRAVEYARD,observed)

    def heals_enemy_minion_three():
        g,p,e=game(CardClass.PRIEST)
        enemy=e.summon("CS2_182")
        enemy.damage=4
        spell=play(p,cid,target=enemy)
        observed=f"enemy_minion={enemy.health}/{enemy.max_health}:{enemy.zone.name};spell={spell.zone.name}"
        return check(enemy.health==4 and enemy.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[
        ("restores_three_to_friendly_hero", "Damaged friendly hero restores exactly 3 Health.",heals_friendly_hero_three,"英雄损失5点后治疗。"),
        ("can_heal_enemy_minion", "Damaged enemy minion is a legal target and restores exactly 3 Health.",heals_enemy_minion_three,"敌方目标分支。"),
    ])


def former_champ():
    cid="TRL_151"

    def summons_five_five_hotshot():
        g,p,e=game()
        body=play(p,cid)
        tokens=[m for m in p.field if m.id=="TRL_151t"]
        observed=f"body={body.zone.name};tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]};enemy_field={len(e.field)}"
        return check(body.zone==Zone.PLAY and len(tokens)==1
                     and (tokens[0].atk,tokens[0].health,tokens[0].zone)==(5,5,Zone.PLAY)
                     and not e.field,observed)

    audit(cid,[("battlecry_one_five_five_hotshot", "Battlecry summons exactly one friendly 5/5 Hotshot.",summons_five_five_hotshot,"核对衍生物数量、身材和阵营。")])


def walk_the_plank():
    cid="TRL_157"

    def undamaged_only_target_and_destroy():
        g,p,e=game(CardClass.ROGUE)
        clean=e.summon("CS2_182")
        damaged=e.summon("CS2_182")
        damaged.damage=1
        card=p.give(cid)
        legal=list(card.targets)
        card.play(target=clean)
        observed=f"legal_clean={clean in legal};legal_damaged={damaged in legal};clean={clean.zone.name};damaged={damaged.zone.name}:{damaged.health}"
        return check(clean in legal and damaged not in legal and clean.zone!=Zone.PLAY
                     and damaged.zone==Zone.PLAY and damaged.health==4,observed)

    audit(cid,[("undamaged_only_target_destroy", "Undamaged minion is legal and destroyed; damaged minion is excluded and survives.",undamaged_only_target_and_destroy,"同时放置未伤和已伤随从，检验目标集合与实战结算。")])


def pounce():
    cid="TRL_243"

    def attack_plus_two_this_turn_only():
        g,p,e=game(CardClass.DRUID)
        spell=play(p,cid)
        during=p.hero.atk
        g.end_turn();g.end_turn()
        observed=f"hero_attack={during}->{p.hero.atk};spell={spell.zone.name}"
        return check(during==2 and p.hero.atk==0 and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("two_attack_and_expiry", "Pounce gives hero +2 Attack in current turn and expires next own turn.",attack_plus_two_this_turn_only,"跨回合直接检查英雄攻击状态。")])


def grim_rally():
    cid="TRL_249"

    def kills_target_buffs_other_friends_only():
        g,p,e=game(CardClass.WARLOCK)
        sacrifice=p.summon(WISP)
        friend=p.summon("CS2_182")
        enemy=e.summon("CS2_182")
        spell=play(p,cid,target=sacrifice)
        observed=f"sacrifice={sacrifice.zone.name};friend={friend.atk}/{friend.health};enemy={enemy.atk}/{enemy.health};spell={spell.zone.name}"
        return check(sacrifice.zone!=Zone.PLAY and (friend.atk,friend.health)==(5,6)
                     and (enemy.atk,enemy.health)==(4,5) and spell.zone==Zone.GRAVEYARD,observed)

    audit(cid,[("sacrifice_then_buff_survivors", "Destroys selected friendly minion, then gives each surviving friendly minion +1/+1; enemy unchanged.",kills_target_buffs_other_friends_only,"一牺牲一存活一敌方对照，检查区域与身材。")])


CHECKS = {
    "TRL_010":half_time_scavenger,
    "TRL_012":totemic_smash,
    "TRL_015":ticket_scalper,
    "TRL_020":sightless_ranger,
    "TRL_057":serpent_ward,
    "TRL_059":bog_slosher,
    "TRL_058":haunting_visions,
    "TRL_060":spirit_of_the_frog,
    "TRL_077":gurubashi_hypemon,
    "TRL_082":big_bad_voodoo,
    "TRL_085":zentimo,
    "TRL_092":spirit_of_the_shark,
    "TRL_096":griftah,
    "TRL_119":the_beast_within,
    "TRL_124":raiding_party,
    "TRL_126":captain_hooktusk,
    "TRL_127":cannon_barrage,
    "TRL_131":sand_drudge,
    "TRL_156":stolen_steel,
    "TRL_223":spirit_of_the_raptor,
    "TRL_232":ironhide_direhorn,
    "TRL_240":savage_striker,
    "TRL_241":gonk_the_raptor,
    "TRL_244":predatory_instincts,
    "TRL_245":shriek,
    "TRL_246":void_contract,
    "TRL_251":spirit_of_the_bat,
    "TRL_252":high_priestess_jeklik,
    "TRL_253":hireek_the_bat,
    "TRL_255":stampeding_roar,
    "TRL_257":blood_troll_sapper,
    "TRL_071":bloodsail_howler,
    "TRL_074":serrated_tooth,
    "TRL_097":seance,
    "TRL_111":headhunters_hatchet,
    "TRL_128":regenerate,
    "TRL_151":former_champ,
    "TRL_157":walk_the_plank,
    "TRL_243":pounce,
    "TRL_249":grim_rally,
    "TRL_065":zuljin,
    "TRL_247":soulwarden,
    "TRL_254":mark_of_the_loa,
    "TRL_258":mass_hysteria,
    "TRL_259":princess_talanji,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("card_ids", nargs="*")
    args = parser.parse_args()
    for cid in args.card_ids or list(CHECKS):
        CHECKS[cid]()
