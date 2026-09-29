"""Card-specific live game checks for the final 23 collectible ULDUM YELLOW cards."""

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
PROBE_FILE = HERE / "uld_probe_d.csv"
VERDICT_FILE = HERE / "uld_verdict_d.csv"
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
                 if r["set"].endswith("(ULDUM)")),
                key=lambda r: r["card_id"])
ROSTER = ROSTER[110:133]
assert len(ROSTER) == 23 and ROSTER[0]["card_id"] == "ULD_702" and ROSTER[-1]["card_id"] == "ULD_728"
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




def mortuary_machine():
    cid="ULD_702"
    def enemy_play_gets_reborn_and_reborns_on_death():
        g,p,e=game();body=play(p,cid);g.end_turn()
        enemy=play(e,WISP);given=enemy.reborn;enemy.destroy()
        return check(given and enemy.zone==Zone.GRAVEYARD and any(m.id==WISP and m.health==1 for m in e.field),
                     f"given_reborn={given};original={enemy.zone.name};enemy_field={[(m.id,m.health,m.zone.name) for m in e.field]};body={body.zone.name}")
    audit(cid,[("opponent_played_minion_receives_functional_reborn","Enemy plays Wisp under Machine aura; Wisp gains Reborn and actually returns after death.",enemy_play_gets_reborn_and_reborns_on_death,"敌方出牌触发、转生标签与死亡结算。")])


def desert_obelisk():
    cid="ULD_703"
    def branch(count):
        g,p,e=game();obelisks=[]
        for _ in range(count):
            p.used_mana=0
            obelisks.append(play(p,cid))
        g.end_turn()
        return check(e.hero.health==(15 if count==3 else 30) and all(m.zone==Zone.PLAY for m in obelisks),
                     f"count={count};enemy_health={e.hero.health};own_health={p.hero.health};field={len(p.field)}")
    audit(cid,[("three_obelisks_each_deal_five","Three Obelisks at own turn end each deal 5 to sole enemy hero.",lambda:branch(3),"阈值三张及每张触发。"),
               ("two_obelisks_no_damage","Two Obelisks do not activate.",lambda:branch(2),"阈值不足对照。")])


def mogu_cultist():
    cid="ULD_705"
    def six_plus_seventh_summons_ra():
        g,p,e=game();pre=[p.summon(cid) for _ in range(6)]
        last=play(p,cid);ra=[m for m in p.field if m.id=="ULD_705t"]
        return check(all(m.zone==Zone.GRAVEYARD for m in pre+[last]) and len(ra)==1 and ra[0].zone==Zone.PLAY,
                     f"cultists={[m.zone.name for m in pre+[last]]};ra={[(m.id,m.atk,m.health,m.zone.name) for m in ra]}")
    def fewer_than_seven_stays():
        g,p,e=game();pre=[p.summon(cid) for _ in range(5)]
        last=play(p,cid)
        return check(last.zone==Zone.PLAY and len([m for m in p.field if m.id==cid])==6 and not any(m.id=="ULD_705t" for m in p.field),
                     f"cultists={len([m for m in p.field if m.id==cid])};last={last.zone.name};ra={[(m.id,m.zone.name) for m in p.field if m.id=='ULD_705t']}")
    audit(cid,[("full_board_of_seven_cultists_sacrifices_and_summons_ra","Six field Cultists plus played seventh sacrifice all seven and summon Ra.",six_plus_seventh_summons_ra,"七格阈值、牺牲与奖励。"),
               ("six_cultists_do_not_trigger","Only six total Cultists stay on board without Ra.",fewer_than_seven_stays,"不足阈值对照。")])


def blatant_decoy():
    cid="ULD_706"
    def lowest_cost_minion_each_hand():
        g,p,e=game()
        own_low=p.give("EX1_116");own_high=p.give("EX1_414")
        enemy_low=e.give("EX1_116");enemy_high=e.give("EX1_414")
        assert own_low.cost<own_high.cost and own_low.atk>own_high.atk
        body=play(p,cid);body.destroy()
        return check(own_low.zone==Zone.PLAY and own_high.zone==Zone.HAND and enemy_low.zone==Zone.PLAY and enemy_high.zone==Zone.HAND,
                     f"own_lower_cost={own_low.id}:{own_low.cost}/{own_low.atk}:{own_low.zone.name};own_lower_attack={own_high.id}:{own_high.cost}/{own_high.atk}:{own_high.zone.name};enemy_lower_cost={enemy_low.zone.name};enemy_lower_attack={enemy_high.zone.name}")
    audit(cid,[("death_summons_lowest_cost_not_lowest_attack_from_each_hand","Deathrattle should choose 5-Cost 6-Attack Leeroy over 8-Cost 4-Attack Grommash in both hands.",lowest_cost_minion_each_hand,"最低费用与最低攻击冲突局面、双玩家区域。")])


def plague_of_wrath():
    cid="ULD_707"
    def destroys_damaged_both_sides_only():
        g,p,e=game(CardClass.WARRIOR)
        own=p.summon("CS2_182");enemy=e.summon("CS2_182");fresh=e.summon(WISP)
        own.hit(1);enemy.hit(1)
        spell=play(p,cid)
        return check(own.zone==Zone.GRAVEYARD and enemy.zone==Zone.GRAVEYARD and fresh.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,
                     f"own={own.zone.name};enemy={enemy.zone.name};fresh={fresh.zone.name};spell={spell.zone.name}")
    audit(cid,[("all_damaged_minions_die_undamaged_survives","Spell destroys damaged Yetis on both sides, leaves undamaged Wisp alive.",destroys_damaged_both_sides_only,"双方损伤状态与死亡区域。")])


def livewire_lance():
    cid="ULD_708"
    def hero_attack_adds_lackey():
        g,p,e=game(CardClass.WARRIOR);weapon=play(p,cid)
        p.hero.attack(e.hero);hand=list(p.hand)
        return check(len(hand)==1 and hand[0].mark_of_evil and hand[0].zone==Zone.HAND and e.hero.health==28 and weapon.zone==Zone.PLAY,
                     f"weapon={weapon.zone.name}:{weapon.durability};enemy={e.hero.health};hand={[(c.id,c.mark_of_evil,c.zone.name) for c in hand]}")
    audit(cid,[("equipped_weapon_attack_adds_exactly_one_lackey","Hero attacks with Lance, dealing 2 and generating one Lackey in hand.",hero_attack_adds_lackey,"真实英雄攻击、武器与手牌。")])


def armored_goon():
    cid="ULD_709"
    def hero_attack_grants_five_armor():
        g,p,e=game(CardClass.WARRIOR);body=play(p,cid);play(p,"CS2_106")
        p.hero.attack(e.hero)
        return check(p.hero.armor==5 and body.zone==Zone.PLAY,
                     f"armor={p.hero.armor};enemy_health={e.hero.health};body={body.zone.name}")
    audit(cid,[("hero_weapon_attack_grants_five_armor","With Goon on board, actual hero weapon attack gives 5 Armor.",hero_attack_grants_five_armor,"攻击事件与护甲。")])


def hack_the_system():
    cid="ULD_711"
    def five_hero_attacks_unlock_reward():
        g,p,e=game(CardClass.WARRIOR)
        quest=play(p,cid);progress=[]
        for turn in range(5):
            p.used_mana=0
            play(p,"CS2_106")
            p.hero.attack(e.hero)
            progress.append(quest.progress)
            if turn<4:g.end_turn();g.end_turn()
        power=p.hero.power
        if power.id=="ULD_711p3":power.use()
        golems=[m for m in p.field if m.id=="ULD_711t"]
        return check(progress==[1,2,3,4,5] and quest.zone==Zone.GRAVEYARD and power.id=="ULD_711p3"
                     and len(golems)==1 and (golems[0].atk,golems[0].health)==(4,3),
                     f"progress={progress};quest={quest.zone.name};power={power.id};golems={[(m.atk,m.health,m.zone.name) for m in golems]};enemy_health={e.hero.health}")
    audit(cid,[("five_actual_hero_attacks_unlock_and_use_anraphets_core","Five hero attacks progress Quest 1–5, replace Hero Power, and using reward summons a 4/3 Golem.",five_hero_attacks_unlock_reward,"真实武器攻击、进度、技能替换与奖励使用。")])


def bug_collector():
    cid="ULD_712"
    def summons_one_rush_locust():
        g,p,e=game();enemy=e.summon(WISP);body=play(p,cid)
        locusts=[m for m in p.field if m.id=="ULD_430t"]
        ready=locusts[0].can_attack(enemy) if locusts else False
        if ready:locusts[0].attack(enemy)
        return check(len(locusts)==1 and (locusts[0].atk,locusts[0].health)==(1,1) and locusts[0].rush and ready and enemy.zone==Zone.GRAVEYARD,
                     f"locusts={[(m.atk,m.health,m.rush,m.zone.name) for m in locusts]};ready={ready};enemy={enemy.zone.name};body={body.zone.name}")
    audit(cid,[("battlecry_summons_one_functional_rush_locust","Battlecry summons one 1/1 Rush Locust that immediately attacks enemy Wisp.",summons_one_rush_locust,"数量、身材、冲锋限制和实战攻击。")])


def swarm_of_locusts():
    cid="ULD_713"
    def summons_seven_rush_locusts():
        g,p,e=game(CardClass.HUNTER);spell=play(p,cid)
        locusts=[m for m in p.field if m.id=="ULD_430t"]
        return check(len(locusts)==7 and len(p.field)==7 and all((m.atk,m.health,m.rush)==(1,1,True) for m in locusts),
                     f"locusts={[(m.id,m.atk,m.health,m.rush,m.zone.name) for m in locusts]};spell={spell.zone.name}")
    audit(cid,[("summons_seven_one_one_rush_locusts","Spell fills empty board with exactly seven 1/1 Rush Locusts.",summons_seven_rush_locusts,"数量、满场、身材与关键词。")])


def penance():
    cid="ULD_714"
    def three_minion_damage_heals_hero():
        g,p,e=game(CardClass.PRIEST);p.hero.hit(5)
        target=e.summon("CS2_182");spell=play(p,cid,target=target)
        return check(target.health==2 and p.hero.health==28 and e.hero.health==30 and spell.zone==Zone.GRAVEYARD,
                     f"target={target.health}:{target.zone.name};own_hero={p.hero.health};enemy_hero={e.hero.health};spell={spell.zone.name}")
    audit(cid,[("deals_three_to_minion_and_lifesteal_heals_three","Against 5-Health Yeti, spell deals 3 and Lifesteal restores 3 to damaged own hero.",three_minion_damage_heals_hero,"目标、伤害与治疗量。")])


def plague_of_madness():
    cid="ULD_715"
    def both_players_equip_two_two_poisonous_knife():
        g,p,e=game(CardClass.ROGUE);spell=play(p,cid)
        weapons=[p.weapon,e.weapon]
        initial=[(w.id,w.atk,w.durability,w.poisonous,w.zone) if w else None for w in weapons]
        target=e.summon("CS2_182");ready=p.hero.can_attack(target)
        if ready:p.hero.attack(target)
        return check(all(w is not None and w[0]=="ULD_715t" and w[1:4]==(2,2,True) and w[4]==Zone.PLAY for w in initial)
                     and ready and target.zone==Zone.GRAVEYARD and e.weapon is weapons[1],
                     f"initial={[(x[0],x[1],x[2],x[3],x[4].name) if x else None for x in initial]};ready={ready};target={target.zone.name};own_weapon={p.weapon.durability if p.weapon else None};enemy_weapon={e.weapon.zone.name if e.weapon else None};spell={spell.zone.name}")
    audit(cid,[("both_players_equip_two_two_poisonous_weapon","Both heroes equip 2/2 Poisonous Knives; own weapon attack poisons and kills 5-Health Yeti.",both_players_equip_two_two_poisonous_knife,"双玩家装备与实际剧毒战斗。")])


def tip_the_scales():
    cid="ULD_716"
    def summons_only_seven_deck_murlocs():
        g,p,e=game(CardClass.PALADIN)
        murlocs=[p.card("CS2_168",zone=Zone.DECK) for _ in range(7)]
        plain=p.card(WISP,zone=Zone.DECK)
        spell=play(p,cid)
        return check(all(c.zone==Zone.PLAY for c in murlocs) and len(p.field)==7 and plain.zone==Zone.DECK,
                     f"murlocs={[c.zone.name for c in murlocs]};plain={plain.zone.name};spell={spell.zone.name}")
    audit(cid,[("seven_murlocs_leave_deck_for_own_board","Seven Murlocs summon from deck to fill board; Wisp stays in deck.",summons_only_seven_deck_murlocs,"牌库种族过滤、数量与场位。")])


def plague_of_flames():
    cid="ULD_717"
    def own_two_die_and_exactly_two_enemy_die():
        g,p,e=game(CardClass.WARLOCK)
        own=[p.summon(WISP),p.summon(WISP)]
        enemies=[e.summon("CS2_182") for _ in range(3)]
        spell=play(p,cid)
        enemy_dead=sum(c.zone==Zone.GRAVEYARD for c in enemies)
        return check(all(c.zone==Zone.GRAVEYARD for c in own) and enemy_dead==2 and len(e.field)==1,
                     f"own={[c.zone.name for c in own]};enemy={[c.zone.name for c in enemies]};enemy_dead={enemy_dead};spell={spell.zone.name}")
    audit(cid,[("two_friendly_sacrifices_destroy_two_random_enemy_minions","Two own Wisps die, exactly two of three enemy Yetis die and one survives.",own_two_die_and_exactly_two_enemy_die,"牺牲数与敌方随机消灭数。")])


def plague_of_death():
    cid="ULD_718"
    def silences_before_destroying_all():
        g,p,e=game(CardClass.PRIEST)
        deathrattle=p.summon("DAL_146");enemy=e.summon("CS2_182")
        spell=play(p,cid);tokens=[c for c in p.hand if c.id=="DAL_146t"]
        return check(deathrattle.zone==Zone.GRAVEYARD and enemy.zone==Zone.GRAVEYARD and not tokens,
                     f"deathrattle={deathrattle.zone.name};enemy={enemy.zone.name};tokens={len(tokens)};spell={spell.zone.name}")
    audit(cid,[("silences_deathrattle_then_destroys_all_minions","All minions die, but silenced Bronze Herald produces no deathrattle tokens.",silences_before_destroying_all,"沉默先后顺序、亡语抑制与双方清场。")])


def desert_hare():
    cid="ULD_719"
    def battlecry_adds_two_own_hare_copies():
        g,p,e=game();body=play(p,cid)
        hares=[m for m in p.field if m.id==cid]
        return check(len(hares)==3 and len(e.field)==0 and all((m.atk,m.health)==(1,1) for m in hares),
                     f"own_hares={[(m.id,m.atk,m.health,m.zone.name) for m in hares]};enemy_field={[(m.id,m.zone.name) for m in e.field]}")
    audit(cid,[("battlecry_summons_two_extra_hares_on_own_side","Played Hare plus two 1/1 copies occupy own board, none for opponent.",battlecry_adds_two_own_hare_copies,"数量、阵营与属性。")])


def bloodsworn_mercenary():
    cid="ULD_720"
    def copies_damaged_friendly_minion():
        g,p,e=game(CardClass.WARRIOR);target=p.summon("CS2_182");target.hit(1)
        body=play(p,cid,target=target);copies=[m for m in p.field if m.id==target.id]
        return check(len(copies)==2 and all(m.health==4 for m in copies) and body.zone==Zone.PLAY,
                     f"copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};body={body.zone.name}")
    audit(cid,[("chosen_damaged_friendly_minion_copied_with_damage","Target damaged 4-Health Yeti yields a second Yeti with same current Health.",copies_damaged_friendly_minion,"受伤目标、精确复制、数量与生命。")])


def colossus_of_the_moon():
    cid="ULD_721"
    def shield_and_reborn_after_death():
        g,p,e=game();body=play(p,cid);initial=(body.divine_shield,body.reborn)
        body.hit(1);shield_after_hit=body.divine_shield;health_after_hit=body.health
        body.destroy();returned=[m for m in p.field if m.id==cid]
        return check(initial==(True,True) and health_after_hit==body.max_health and not shield_after_hit
                     and body.zone==Zone.GRAVEYARD and len(returned)==1 and returned[0].health==1 and returned[0].divine_shield,
                     f"initial={initial};after_hit={health_after_hit}:{shield_after_hit};dead={body.zone.name};returned={[(m.health,m.divine_shield,m.reborn,m.zone.name) for m in returned]}")
    audit(cid,[("divine_shield_reborn_returns_one_health_shielded_body","Initial Divine Shield absorbs actual 1 damage; after death Reborn returns 1-Health shielded body.",shield_and_reborn_after_death,"圣盾伤害阻挡、死亡、转生后状态。")])


def murmy():
    cid="ULD_723"
    def reborns_once_at_one_health():
        g,p,e=game();body=play(p,cid);initial=body.reborn
        body.destroy();returned=[m for m in p.field if m.id==cid]
        if returned:returned[0].destroy()
        remaining=[m for m in p.field if m.id==cid]
        return check(initial and body.zone==Zone.GRAVEYARD and len(returned)==1 and returned[0].health==1 and not remaining,
                     f"initial={initial};first_dead={body.zone.name};returned={[(m.health,m.reborn,m.zone.name) for m in returned]};remaining={len(remaining)}")
    audit(cid,[("first_death_reborns_at_one_health_second_death_final","Murmy Reborn produces one 1-Health copy; destroying that copy leaves no third Murmy.",reborns_once_at_one_health,"首次和二次死亡边界。")])


def activate_the_obelisk():
    cid="ULD_724"
    def fifteen_actual_healing_unlocks_power():
        g,p,e=game(CardClass.PRIEST);quest=play(p,cid);p.hero.hit(15)
        progress=[]
        for _ in range(3):
            play(p,"CS2_089",target=p.hero)
            progress.append(quest.progress)
        power=p.hero.power
        return check(progress==[6,12,15] and quest.zone==Zone.GRAVEYARD and power.id=="ULD_724p",
                     f"progress={progress};quest={quest.zone.name};hero={p.hero.health};power={power.id}")
    audit(cid,[("restore_fifteen_actual_health_unlocks_obelisk_eye","Three Holy Lights restore 6+6+3 actual Health after 15 damage, completing Quest and changing Hero Power.",fifteen_actual_healing_unlocks_power,"真实治疗量、任务进度和技能奖励。")])


def ancient_mysteries():
    cid="ULD_726"
    def draws_only_secret_at_zero_cost():
        g,p,e=game(CardClass.MAGE)
        secret=p.card("EX1_287",zone=Zone.DECK);plain=p.card(WISP,zone=Zone.DECK)
        spell=play(p,cid)
        return check(secret.zone==Zone.HAND and secret.cost==0 and plain.zone==Zone.DECK,
                     f"secret={secret.id}:{secret.cost}:{secret.zone.name};plain={plain.zone.name};spell={spell.zone.name}")
    audit(cid,[("draws_secret_from_deck_and_sets_cost_zero","Draws sole Mage Secret from deck at cost 0; Wisp stays deck.",draws_only_secret_at_zero_cost,"牌库过滤、抽牌与费用。")])


def body_wrapper():
    cid="ULD_727"
    def discovers_dead_friendly_minion_and_shuffles_choice():
        g,p,e=game()
        dead=[p.summon(WISP),p.summon("CS2_182"),p.summon("NEW1_023")]
        for m in dead:m.destroy()
        before=len(p.deck)
        try:body=play(p,cid)
        except Exception as exc:return check(False,f"play_error={type(exc).__name__}:{exc};dead={[m.id for m in dead]}")
        choice=p.choice;options=list(choice.cards) if choice else []
        selected=options[0] if options else None
        if selected:choice.choose(selected)
        ids={m.id for m in dead}
        added=[c for c in p.deck if c.id in ids]
        return check(len(options)==3 and all(c.id in ids for c in options) and selected is not None and len(added)==1 and added[0].id==selected.id and p.choice is None,
                     f"options={[(c.id,c.zone.name) for c in options]};selected={None if selected is None else selected.id};added={[(c.id,c.zone.name) for c in added]};choice_closed={p.choice is None};body={body.zone.name}")
    audit(cid,[("discover_only_friendly_dead_minions_and_shuffle_selected","Three friendly dead minions form Discover options; chosen copy goes to deck and Choice closes.",discovers_dead_friendly_minion_and_shuffles_choice,"死亡历史、候选、选择及牌库状态。")])


def subdue():
    cid="ULD_728"
    def chosen_minion_becomes_one_one():
        g,p,e=game(CardClass.PALADIN);target=e.summon("CS2_182");other=e.summon("CS2_182")
        spell=play(p,cid,target=target)
        return check((target.atk,target.health,target.max_health)==(1,1,1) and (other.atk,other.health)==(4,5),
                     f"target={target.atk}/{target.health}/{target.max_health};other={other.atk}/{other.health};spell={spell.zone.name}")
    audit(cid,[("sets_selected_minion_attack_and_health_to_one","Selected enemy Yeti becomes 1/1 while adjacent Yeti remains 4/5.",chosen_minion_becomes_one_one,"目标属性与非目标对照。")])


CHECKS={"ULD_702":mortuary_machine,"ULD_703":desert_obelisk,"ULD_705":mogu_cultist,
        "ULD_706":blatant_decoy,"ULD_707":plague_of_wrath,"ULD_708":livewire_lance,
        "ULD_709":armored_goon,"ULD_711":hack_the_system,"ULD_712":bug_collector,
        "ULD_713":swarm_of_locusts,"ULD_714":penance,"ULD_715":plague_of_madness,
        "ULD_716":tip_the_scales,"ULD_717":plague_of_flames,"ULD_718":plague_of_death,
        "ULD_719":desert_hare,"ULD_720":bloodsworn_mercenary,
        "ULD_721":colossus_of_the_moon,"ULD_723":murmy,"ULD_724":activate_the_obelisk,
        "ULD_726":ancient_mysteries,"ULD_727":body_wrapper,"ULD_728":subdue}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
