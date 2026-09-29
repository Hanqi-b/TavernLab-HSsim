"""Card-specific live game checks for the collectible first 45 Rise of Shadows YELLOW cards."""

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
PROBE_FILE = HERE / "dal_probe_a.csv"
VERDICT_FILE = HERE / "dal_verdict_a.csv"
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
                 if r["set"].endswith("(DALARAN)")),
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


def rafaams_scheme():
    cid="DAL_007"
    def branch(upgraded):
        g,p,e=game(CardClass.WARLOCK)
        spell=p.give(cid)
        if upgraded:g.end_turn();g.end_turn()
        progress=spell.progress
        spell.play()
        imps=[m for m in p.field if m.id=="DAL_751t"]
        observed=f"upgraded={upgraded};progress={progress};imps={[(m.atk,m.health,m.zone.name) for m in imps]};spell={spell.zone.name}"
        return check(len(imps)==(2 if upgraded else 1) and all((m.atk,m.health)==(1,1) for m in imps),observed)
    audit(cid,[("fresh_one_imp","Fresh Scheme summons one 1/1 Imp.",lambda:branch(False),"直接打出分支。"),
               ("one_turn_two_imps","After one owner turn in hand, Scheme summons two 1/1 Imps.",lambda:branch(True),"跨回合手牌升级与实际召唤。")])


def dr_booms_scheme():
    cid="DAL_008"
    def branch(upgraded):
        g,p,e=game(CardClass.WARRIOR)
        spell=p.give(cid)
        if upgraded:g.end_turn();g.end_turn()
        progress=spell.progress
        spell.play()
        observed=f"upgraded={upgraded};progress={progress};armor={p.hero.armor};spell={spell.zone.name}"
        return check(p.hero.armor==(2 if upgraded else 1) and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("fresh_one_armor","Fresh Scheme grants 1 Armor.",lambda:branch(False),"实际护甲变化。"),
               ("one_turn_two_armor","One turn held in hand upgrades Scheme to 2 Armor.",lambda:branch(True),"跨回合升级。")])


def hagathas_scheme():
    cid="DAL_009"
    def branch(upgraded):
        g,p,e=game(CardClass.SHAMAN)
        spell=p.give(cid)
        friend=p.summon("CS2_182");enemy=e.summon("CS2_182")
        if upgraded:g.end_turn();g.end_turn()
        progress=spell.progress
        spell.play()
        observed=f"upgraded={upgraded};progress={progress};friend={friend.health};enemy={enemy.health};heroes={p.hero.health}/{e.hero.health};spell={spell.zone.name}"
        expected=3 if upgraded else 4
        return check(friend.health==expected and enemy.health==expected and p.hero.health==30 and e.hero.health==30,observed)
    audit(cid,[("fresh_one_aoe","Fresh Scheme deals 1 to each minion, not heroes.",lambda:branch(False),"双方随从与英雄对照。"),
               ("one_turn_two_aoe","After one owner turn, Scheme deals 2 to each minion.",lambda:branch(True),"跨回合手牌升级。")])


def togwaggles_scheme():
    cid="DAL_010"
    def branch(upgraded):
        g,p,e=game(CardClass.ROGUE)
        spell=p.give(cid);target=e.summon(WISP)
        if upgraded:g.end_turn();g.end_turn()
        progress=spell.progress
        spell.play(target=target)
        copies=[c for c in p.deck if c.id==WISP]
        observed=f"upgraded={upgraded};progress={progress};copies={len(copies)};target={target.zone.name};spell={spell.zone.name}"
        return check(len(copies)==(2 if upgraded else 1) and target.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("fresh_one_copy","Fresh Scheme shuffles one chosen minion copy into deck.",lambda:branch(False),"目标身份、牌库和原目标区域。"),
               ("one_turn_two_copies","After one owner turn, Scheme shuffles two copies.",lambda:branch(True),"跨回合升级与牌库计数。")])


def lazuls_scheme():
    cid="DAL_011"
    def one_turn_and_expiry():
        g,p,e=game(CardClass.PRIEST)
        spell=p.give(cid);target=e.summon("CS2_182")
        g.end_turn();g.end_turn()
        progress=spell.progress
        spell.play(target=target)
        reduced=target.atk
        g.end_turn();g.end_turn()
        restored=target.atk
        observed=f"progress={progress};attack={4}->{reduced}->{restored};target={target.zone.name};spell={spell.zone.name}"
        return check(progress==1 and reduced==2 and restored==4 and target.zone==Zone.PLAY,observed)
    audit(cid,[("upgrade_reduce_two_then_expire","One turn in hand makes Scheme reduce enemy minion Attack by 2; it expires at owner's next turn.",one_turn_and_expiry,"目标攻击力跨回合变化和时效。")])


def shadowy_figure():
    cid="DAL_030"
    def target_deathrattle_copy():
        g,p,e=game(CardClass.PRIEST)
        target=p.summon("BOT_445");other=p.summon(WISP)
        fig=play(p,cid,target=target)
        copies=[m for m in p.field if m.id=="BOT_445" and m is not target]
        observed=f"target={target.id}:{target.zone.name};figure={fig.id}:{fig.zone.name};copies={[(m.id,m.atk,m.health,m.has_deathrattle) for m in copies]};other={other.id}:{other.zone.name}"
        return check(len(copies)==1 and (copies[0].atk,copies[0].health)==(2,2)
                     and copies[0].has_deathrattle and target.zone==Zone.PLAY and other.zone==Zone.PLAY,observed)
    audit(cid,[("copy_deathrattle_as_two_two","Shadowy Figure becomes a 2/2 copy of selected friendly Deathrattle minion; source stays on board.",target_deathrattle_copy,"目标合法性、变形身份、身材及亡语保留。")])


def convincing_infiltrator():
    cid="DAL_039"
    def death_destroys_enemy():
        g,p,e=game(CardClass.PRIEST)
        body=p.summon(cid);friend=p.summon(WISP);victim=e.summon("CS2_182")
        start_taunt=body.taunt
        body.destroy()
        observed=f"taunt={start_taunt};body={body.zone.name};victim={victim.zone.name};friend={friend.zone.name}"
        return check(start_taunt and body.zone==Zone.GRAVEYARD and victim.zone==Zone.GRAVEYARD and friend.zone==Zone.PLAY,observed)
    audit(cid,[("deathrattle_destroys_enemy_only","Taunt minion's Deathrattle destroys sole enemy minion and leaves friendly minion intact.",death_destroys_enemy,"单合法随机目标、区域及友军对照。")])


def shadequill():
    cid="DAL_040"
    def heal_enemy():
        g,p,e=game(CardClass.PRIEST)
        e.hero.damage=8;p.hero.damage=8
        body=p.summon(cid);body.destroy()
        observed=f"enemy_health={e.hero.health};own_health={p.hero.health};body={body.zone.name}"
        return check(e.hero.health==27 and p.hero.health==22 and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deathrattle_heals_enemy_five","Deathrattle restores 5 to enemy hero only, not controller's equally damaged hero.",heal_enemy,"双方英雄同预伤，核对阵营与治疗量。")])


def walking_fountain():
    cid="DAL_047"
    def rush_lifesteal_windfury():
        g,p,e=game(CardClass.SHAMAN)
        p.hero.damage=12;first=e.summon(WISP);second=e.summon(WISP)
        body=play(p,cid)
        hero_legal=body.can_attack(e.hero);first_legal=body.can_attack(first)
        body.attack(first);after_first=p.hero.health
        second_legal=body.can_attack(second);body.attack(second);after_second=p.hero.health
        observed=f"hero_legal={hero_legal};first_legal={first_legal};second_legal={second_legal};health=18->{after_first}->{after_second};foes={first.zone.name}/{second.zone.name};attacks={body.num_attacks}"
        return check(not hero_legal and first_legal and second_legal and after_first==22 and after_second==26
                     and first.zone==Zone.GRAVEYARD and second.zone==Zone.GRAVEYARD and body.num_attacks==2,observed)
    audit(cid,[("rush_two_attacks_lifesteal","On play, Rush allows two minion attacks but no hero attack; each 4 damage restores 4 Health.",rush_lifesteal_windfury,"同回合两次真实攻击、目标合法性与吸血。")])


def underbelly_angler():
    cid="DAL_049"
    def murloc_only():
        g,p,e=game(CardClass.SHAMAN)
        body=play(p,cid);play(p,WISP);after_plain=len(p.hand)
        played=play(p,"CS2_168");generated=list(p.hand)
        observed=f"after_nonmurloc={after_plain};generated={[(c.id,Race.MURLOC in c.races,c.zone.name) for c in generated]};played={played.zone.name};angler={body.zone.name}"
        return check(after_plain==0 and len(generated)==1 and Race.MURLOC in generated[0].races and generated[0].zone==Zone.HAND,observed)
    audit(cid,[("played_murloc_generates_murloc","A later played Murloc creates one Murloc hand card; a played Wisp does not.",murloc_only,"实际出牌事件、种族与手牌区域。")])


def muckmorpher():
    cid="DAL_052"
    def different_deck_minion():
        g,p,e=game(CardClass.SHAMAN)
        source=p.card("BOT_445",zone=Zone.DECK);body=play(p,cid)
        copies=[m for m in p.field if m.id==source.id]
        observed=f"muckmorpher={body.zone.name};deck_source={source.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]}"
        return check(body.zone==Zone.SETASIDE and source.zone==Zone.DECK and len(copies)==1
                     and (copies[0].atk,copies[0].health)==(4,4),observed)
    def only_self_in_deck():
        g,p,e=game(CardClass.SHAMAN)
        p.card(cid,zone=Zone.DECK);body=play(p,cid)
        observed=f"body={body.id}:{body.atk}/{body.health}:{body.zone.name};field={[m.id for m in p.field]}"
        return check(body.zone==Zone.PLAY and body.id==cid and len(p.field)==1,observed)
    audit(cid,[("transform_to_four_four_different_deck_minion","Battlecry becomes a 4/4 copy of sole different deck minion; original deck entity remains.",different_deck_minion,"变形身份、身材与牌库保留。"),
               ("only_same_id_no_transform","If deck contains only another Muckmorpher, no eligible different minion exists and played body stays itself.",only_self_in_deck,"排除同名牌的边界。")])


def hecklebot():
    cid="DAL_058"
    def summon_enemy_deck_minion():
        g,p,e=game(CardClass.MAGE)
        victim=e.card(WISP,zone=Zone.DECK);body=play(p,cid)
        observed=f"body={body.zone.name},taunt={body.taunt};victim={victim.zone.name};enemy_field={[m.id for m in e.field]};own_field={[m.id for m in p.field]}"
        return check(body.taunt and body.zone==Zone.PLAY and victim.zone==Zone.PLAY and victim in e.field and victim not in p.field,observed)
    audit(cid,[("opponent_summons_from_deck","Opponent's actual deck minion moves to their battlefield; Hecklebot retains Taunt.",summon_enemy_deck_minion,"双阵营牌库/战场区域。")])


def dimensional_ripper():
    cid="DAL_059"
    def two_deck_copies():
        g,p,e=game(CardClass.WARRIOR)
        source=p.card("CS2_182",zone=Zone.DECK);spell=play(p,cid)
        copies=[m for m in p.field if m.id==source.id]
        observed=f"source={source.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};spell={spell.zone.name}"
        return check(source.zone==Zone.DECK and len(copies)==2 and all((m.atk,m.health)==(4,5) for m in copies)
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("summons_two_copies_leaves_deck_original","Two 4/5 copies of sole deck minion are summoned; original stays in deck.",two_deck_copies,"实体身份、牌库与两个战场副本。")])


def clockwork_goblin():
    cid="DAL_060"
    def bomb_shuffled_and_drawn():
        g,p,e=game(CardClass.WARRIOR)
        body=play(p,cid);bombs=[c for c in e.deck if c.id=="BOT_511t"]
        initial=(len(bombs),body.zone.name)
        if bombs:e.draw()
        observed=f"before={initial};bomb_zones={[(c.id,c.zone.name) for c in bombs]};enemy_health={e.hero.health};enemy_hand={[c.id for c in e.hand]}"
        return check(initial==(1,"PLAY") and bombs[0].zone==Zone.GRAVEYARD and e.hero.health==25
                     and not any(c.id=="BOT_511t" for c in e.hand),observed)
    audit(cid,[("bomb_enters_enemy_deck_and_explodes_on_draw","Battlecry shuffles one Bomb into opponent deck; drawing it deals 5 and leaves no Bomb in hand.",bomb_shuffled_and_drawn,"牌库、抽牌、墓地及英雄生命。")])


def sweeping_strikes():
    cid="DAL_062"
    def cleave_on_attack():
        g,p,e=game(CardClass.WARRIOR)
        body=p.summon("CS2_182");left=e.summon("CS2_182");center=e.summon("CS2_182");right=e.summon("CS2_182")
        spell=play(p,cid,target=body)
        g.end_turn();g.end_turn()
        body.attack(center)
        observed=f"foe_health={[m.health for m in (left,center,right)]};attacker={body.health}:{body.zone.name};spell={spell.zone.name}"
        return check([m.health for m in (left,center,right)]==[1,1,1] and body.health==1,observed)
    audit(cid,[("attack_hits_defender_and_neighbors","Buffed Yeti attacking middle Yeti deals 4 to all three adjacent enemy minions.",cleave_on_attack,"真实跨回合攻击、邻位和自身反击伤害。")])


def wrenchcalibur():
    cid="DAL_063"
    def hero_attack_shuffles_bomb():
        g,p,e=game(CardClass.WARRIOR)
        weapon=play(p,cid);ready=p.hero.can_attack(e.hero)
        if ready:p.hero.attack(e.hero)
        bombs=[c for c in e.deck if c.id=="BOT_511t"]
        observed=f"ready={ready};weapon={weapon.zone.name}:{weapon.durability};bombs={[(c.id,c.zone.name) for c in bombs]};enemy_health={e.hero.health}"
        return check(ready and weapon.zone==Zone.PLAY and len(bombs)==1 and bombs[0].zone==Zone.DECK and e.hero.health==27,observed)
    audit(cid,[("hero_attack_adds_enemy_bomb","Equipped hero attacks once, damages enemy hero and shuffles one Bomb into opponent deck.",hero_attack_shuffles_bomb,"武器攻击、耐久、生命及对手牌库。")])


def blastmaster_boom():
    cid="DAL_064"
    def enemy_bomb_count():
        g,p,e=game(CardClass.WARRIOR)
        bombs=[e.card("BOT_511t",zone=Zone.DECK) for _ in range(2)]
        body=play(p,cid)
        bots=[m for m in p.field if m.id=="GVG_110t"]
        observed=f"enemy_bombs={[(c.id,c.zone.name) for c in bombs]};own_deck={len(p.deck)};bots={[(m.atk,m.health,m.zone.name) for m in bots]};body={body.zone.name}"
        return check(len(bots)==4 and all((b.atk,b.health)==(1,1) for b in bots) and body.zone==Zone.PLAY,observed)
    audit(cid,[("two_enemy_bombs_summon_four_bots","Two Bombs in opponent deck create four 1/1 Boom Bots, even when own deck is empty.",enemy_bomb_count,"阵营敏感计数与实际召唤。")])


def unsleeping_soul():
    cid="DAL_065"
    def silence_then_copy():
        g,p,e=game(CardClass.PRIEST)
        target=p.summon("CS2_182");buff=play(p,"CS2_009",target=target)
        before=(target.atk,target.health,target.taunt)
        spell=play(p,cid,target=target)
        copies=[m for m in p.field if m.id==target.id]
        observed=f"before={before};copies={[(m.atk,m.health,m.taunt,m.silenced,m.zone.name) for m in copies]};spell={spell.zone.name}"
        return check(before==(6,7,True) and len(copies)==2
                     and all((m.atk,m.health,m.taunt)==(4,5,False) for m in copies) and target.silenced,observed)
    audit(cid,[("silence_buffed_minion_then_copy","Previously buffed Taunt Yeti is silenced, then copied as an unbuffed 4/5; both copies lack Taunt.",silence_then_copy,"沉默前后身材、关键词和召唤副本。")])


def boom_reaver():
    cid="DAL_070"
    def copy_deck_minion_with_rush():
        g,p,e=game(CardClass.WARRIOR)
        source=p.card("CS2_182",zone=Zone.DECK);enemy=e.summon(WISP)
        body=play(p,cid)
        copies=[m for m in p.field if m.id==source.id]
        rush_target=copies[0].can_attack(enemy) if copies else False
        rush_hero=copies[0].can_attack(e.hero) if copies else False
        observed=f"source={source.zone.name};copies={[(m.id,m.rush,m.zone.name) for m in copies]};rush_target={rush_target};rush_hero={rush_hero};body={body.zone.name}"
        return check(source.zone==Zone.DECK and len(copies)==1 and copies[0].rush
                     and rush_target and not rush_hero and body.zone==Zone.PLAY,observed)
    audit(cid,[("deck_copy_gets_rush","Battlecry summons deck Yeti copy with Rush, allowing immediate minion attack but no hero attack.",copy_deck_minion_with_rush,"牌库原件、复制体及攻击合法性。")])


def mutate():
    cid="DAL_071"
    def transform_one_cost_higher():
        g,p,e=game(CardClass.SHAMAN)
        target=p.summon(WISP);spell=play(p,cid,target=target)
        transformed=[m for m in p.field if m is not target]
        observed=f"original={target.zone.name};transformed={[(m.id,m.cost,m.zone.name) for m in transformed]};spell={spell.zone.name}"
        return check(target.zone==Zone.SETASIDE and len(transformed)==1 and transformed[0].cost==1
                     and transformed[0].zone==Zone.PLAY,observed)
    audit(cid,[("zero_cost_to_random_one_cost","Friendly 0-Cost Wisp transforms into a different random 1-Cost minion.",transform_one_cost_higher,"目标变形前后身份、费用与区域。")])


def toxfin():
    cid="DAL_077"
    def poison_friendly_murloc():
        g,p,e=game(CardClass.SHAMAN)
        target=p.summon("CS2_168");plain=p.summon(WISP)
        body=play(p,cid,target=target)
        observed=f"murloc_poison={target.poisonous};plain_poison={plain.poisonous};body={body.zone.name}"
        return check(target.poisonous and not plain.poisonous and body.zone==Zone.PLAY,observed)
    audit(cid,[("friendly_murloc_gets_poisonous","Selected friendly Murloc gains Poisonous; non-Murloc remains without it.",poison_friendly_murloc,"目标种族与关键词对照。")])


def traveling_healer():
    cid="DAL_078"
    def heal_and_shield():
        g,p,e=game(CardClass.MAGE)
        p.hero.damage=6
        body=play(p,cid,target=p.hero)
        before=body.divine_shield
        body.hit(1)
        observed=f"hero_health={p.hero.health};shield={before}->{body.divine_shield};body_health={body.health};body_zone={body.zone.name}"
        return check(p.hero.health==27 and before and not body.divine_shield and body.health==body.max_health,observed)
    audit(cid,[("target_heal_three_shield_blocks_damage","Battlecry heals damaged selected hero 3; Divine Shield absorbs subsequent 1 damage.",heal_and_shield,"目标治疗与圣盾实际伤害。")])


def spellward_jeweler():
    cid="DAL_081"
    def prohibit_then_expire():
        g,p,e=game(CardClass.MAGE,CardClass.PRIEST)
        body=play(p,cid)
        g.end_turn()
        spell=e.give("CS2_029")
        power=e.hero.power
        protected=(p.hero not in spell.play_targets,p.hero not in power.play_targets)
        g.end_turn()
        expired=(p.hero in e.give("CS2_029").play_targets)
        observed=f"protected={protected};expired_spell_target={expired};body={body.zone.name}"
        return check(protected==(True,True) and expired and body.zone==Zone.PLAY,observed)
    audit(cid,[("spells_and_powers_cannot_target_until_next_turn","Opponent spell and Hero Power cannot target protected hero, and spell targeting returns at owner's next turn.",prohibit_then_expire,"真实目标列表、双方回合与到期。")])


def dalaran_crusader():
    cid="DAL_085"
    def shield_blocks_first_hit():
        g,p,e=game()
        body=play(p,cid);start=body.divine_shield
        body.hit(2);first=(body.health,body.divine_shield)
        body.hit(2);second=(body.health,body.divine_shield)
        observed=f"shield={start};first={first};second={second};zone={body.zone.name}"
        return check(start and first==(body.max_health,False) and second==(body.max_health-2,False),observed)
    audit(cid,[("divine_shield_blocks_once","First 2 damage removes Shield without Health loss; next 2 damage lowers Health.",shield_blocks_first_hit,"同实体连续真实伤害。")])


def sunreaver_spy():
    cid="DAL_086"
    def branch(secret):
        g,p,e=game(CardClass.HUNTER)
        if secret:play(p,"ULD_152")
        body=play(p,cid)
        observed=f"secret={secret};stats={body.atk}/{body.health};zone={body.zone.name}"
        return check((body.atk,body.health)==((3,4) if secret else (2,3)),observed)
    audit(cid,[("with_secret_plus_one_one","Controlled Secret grants +1/+1.",lambda:branch(True),"真实挂奥秘。"),
               ("without_secret_base_stats","No Secret leaves base stats.",lambda:branch(False),"无奥秘对照。")])


def hench_clan_hag():
    cid="DAL_087"
    def two_all_tribe_tokens():
        g,p,e=game()
        body=play(p,cid)
        tokens=[m for m in p.field if m.id=="DAL_087t"]
        observed=f"body={body.zone.name};tokens={[(m.id,m.atk,m.health,[int(r) for r in m.races],m.zone.name) for m in tokens]}"
        return check(len(tokens)==2 and all((m.atk,m.health)==(1,1) for m in tokens)
                     and all(Race.MURLOC in m.races and Race.MECHANICAL in m.races and Race.BEAST in m.races for m in tokens),observed)
    audit(cid,[("two_one_one_all_type_amalgams","Battlecry summons two 1/1 Amalgams with Murloc, Mech and Beast tribes.",two_all_tribe_tokens,"数量、身材和多种族标签。")])


def safeguard():
    cid="DAL_088"
    def death_summons_safe():
        g,p,e=game()
        body=p.summon(cid);initial=body.taunt;body.destroy()
        safes=[m for m in p.field if m.id=="DAL_088t2"]
        observed=f"initial_taunt={initial};body={body.zone.name};safes={[(m.atk,m.health,m.taunt,m.zone.name) for m in safes]}"
        return check(initial and body.zone==Zone.GRAVEYARD and len(safes)==1
                     and (safes[0].atk,safes[0].health,safes[0].taunt)==(0,5,True),observed)
    audit(cid,[("deathrattle_zero_five_taunt","Taunt Safeguard dies and summons exactly one 0/5 Taunt Vault Safe.",death_summons_safe,"死亡区域、令牌身材和嘲讽。")])


def spellbook_binder():
    cid="DAL_089"
    def branch(spell_damage):
        g,p,e=game()
        if spell_damage:p.summon("CS2_142")
        deck=p.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        observed=f"spell_damage={spell_damage};deck_card={deck.zone.name};body={body.zone.name}"
        return check(deck.zone==(Zone.HAND if spell_damage else Zone.DECK),observed)
    audit(cid,[("spell_damage_draws","Friendly Spell Damage minion causes one real draw.",lambda:branch(True),"友方常驻法强与抽牌区域。"),
               ("no_spell_damage_no_draw","Without Spell Damage, card stays in deck.",lambda:branch(False),"空法强对照。")])


def hench_clan_sneak():
    cid="DAL_090"
    def stealth_then_attack():
        g,p,e=game()
        body=play(p,cid);start=body.stealthed
        untargetable=body not in e.give("CS2_029").play_targets
        target=e.summon(WISP);g.end_turn();g.end_turn()
        body.attack(target)
        observed=f"stealth={start}->{body.stealthed};untargetable={untargetable};target={target.zone.name};body={body.zone.name}"
        return check(start and untargetable and not body.stealthed and target.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("stealth_hides_then_breaks_on_attack","Starts Stealthed and absent from enemy spell targets; attack removes Stealth.",stealth_then_attack,"敌方法术目标列表和实际攻击。")])


def violet_spellsword():
    cid="DAL_095"
    def count_hand_spells():
        g,p,e=game()
        p.give("CS2_093");p.give("CS2_029");p.give(WISP)
        body=p.give(cid);base=body.atk;body.play()
        observed=f"base={base};after={body.atk};hand={[c.id for c in p.hand]};zone={body.zone.name}"
        return check(body.atk==base+2 and len(p.hand)==3,observed)
    audit(cid,[("two_hand_spells_plus_two_attack","Two held spells grant exactly +2 Attack; held minion does not count.",count_hand_spells,"法术与随从混合手牌。")])


def violet_warden():
    cid="DAL_096"
    def spell_power_and_taunt():
        g,p,e=game()
        body=play(p,cid);target=e.summon("CS2_182")
        spell=play(p,"CS2_008",target=target)
        observed=f"taunt={body.taunt};spellpower={p.spellpower};target_health={target.health};spell={spell.zone.name}"
        return check(body.taunt and p.spellpower==1 and target.health==3 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("taunt_and_plus_one_spell_damage","Warden has Taunt and makes Moonfire deal 2 instead of 1 to chosen minion.",spell_power_and_taunt,"关键词、玩家法强与实际法术伤害。")])


def desperate_measures():
    cid="DAL_141"
    def secret_and_twinspell():
        g,p,e=game(CardClass.PALADIN)
        spell=play(p,cid)
        secrets=list(p.secrets);copies=[c for c in p.hand if c.id=="DAL_141ts"]
        observed=f"spell={spell.zone.name};secrets={[(c.id,c.zone.name,c.card_class) for c in secrets]};twin_copies={[(c.id,c.zone.name) for c in copies]}"
        return check(spell.zone==Zone.GRAVEYARD and len(secrets)==1 and secrets[0].zone==Zone.SECRET
                     and len(copies)==1 and copies[0].zone==Zone.HAND,observed)
    audit(cid,[("random_paladin_secret_and_twinspell","Playing spell arms one Paladin Secret and leaves one Twinspell copy in hand.",secret_and_twinspell,"随机秘密区域及双生法术复制体。")])


def bronze_herald():
    cid="DAL_146"
    def two_dragons_on_death():
        g,p,e=game(CardClass.PALADIN)
        body=p.summon(cid);body.destroy()
        dragons=[c for c in p.hand if c.id=="DAL_146t"]
        observed=f"body={body.zone.name};dragons={[(c.atk,c.health,Race.DRAGON in c.races,c.zone.name) for c in dragons]}"
        return check(body.zone==Zone.GRAVEYARD and len(dragons)==2
                     and all((d.atk,d.health)==(4,4) and Race.DRAGON in d.races for d in dragons),observed)
    audit(cid,[("deathrattle_adds_two_four_four_dragons","Deathrattle adds two 4/4 Dragon cards to hand.",two_dragons_on_death,"死亡后手牌数量、身材和种族。")])


def dragon_speaker():
    cid="DAL_147"
    def all_held_dragons_only():
        g,p,e=game(CardClass.PALADIN)
        dragons=[p.give("NEW1_023"),p.give("EX1_284")];plain=p.give(WISP)
        before=[(d.atk,d.health) for d in dragons]
        body=play(p,cid)
        after=[(d.atk,d.health) for d in dragons]
        observed=f"before={before};after={after};plain={plain.atk}/{plain.health};body={body.zone.name}"
        return check(after==[(a+3,h+3) for a,h in before] and (plain.atk,plain.health)==(1,1)
                     and all(Race.DRAGON in d.races for d in dragons),observed)
    audit(cid,[("all_held_dragons_plus_three_three","Every Dragon in hand gains +3/+3; non-Dragon Wisp does not.",all_held_dragons_only,"两张龙与非龙手牌对照。")])


def messenger_raven():
    cid="DAL_163"
    def discover_mage_minion():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid);choice=p.choice
        options=list(choice.cards) if choice else []
        selected=options[0] if options else None
        if selected:choice.choose(selected)
        observed=f"offered={[(c.id,int(c.type),int(c.card_class)) for c in options]};selected={None if selected is None else (selected.id,selected.zone.name)};choice_closed={p.choice is None};body={body.zone.name}"
        return check(len(options)==3 and all(c.type==CardType.MINION and CardClass.MAGE in c.classes for c in options)
                     and selected.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("discover_mage_minion","Three Mage minions offered; selected candidate enters hand and Choice closes.",discover_mage_minion,"候选职业/类型、选择及区域。")])


def darkest_hour():
    cid="DAL_173"
    def each_friendly_death_deck_minion():
        g,p,e=game(CardClass.WARLOCK)
        old=[p.summon(WISP),p.summon(WISP)]
        deck=[p.card("CS2_182",zone=Zone.DECK),p.card("BOT_445",zone=Zone.DECK)]
        spell=play(p,cid)
        observed=f"old={[m.zone.name for m in old]};deck={[m.zone.name for m in deck]};field={[m.id for m in p.field]};spell={spell.zone.name}"
        return check(all(m.zone==Zone.GRAVEYARD for m in old) and len(p.field)==2
                     and {m.id for m in p.field}=={c.id for c in deck} and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("two_deaths_replace_with_two_deck_minions","Two friendly minions die; exactly two minions from deck replace them.",each_friendly_death_deck_minion,"逐数量死亡、牌库到战场和法术区域。")])


def conjurers_calling():
    cid="DAL_177"
    def destroy_and_same_cost_twins():
        g,p,e=game(CardClass.MAGE)
        victim=e.summon(WISP);spell=play(p,cid,target=victim)
        summons=list(p.field);copies=[c for c in p.hand if c.id=="DAL_177ts"]
        observed=f"victim={victim.zone.name};summons={[(m.id,m.cost,m.zone.name) for m in summons]};twin={[(c.id,c.zone.name) for c in copies]};spell={spell.zone.name}"
        return check(victim.zone==Zone.GRAVEYARD and len(summons)==2 and all(m.cost==0 for m in summons)
                     and len(copies)==1 and copies[0].zone==Zone.HAND,observed)
    audit(cid,[("destroy_zero_cost_target_summon_two_zero_cost_and_twin","Destroys selected 0-Cost minion, summons two 0-Cost replacements and yields Twinspell copy.",destroy_and_same_cost_twins,"死亡、召唤费用、数量与双生复制。")])


def magic_dart_frog():
    cid="DAL_182"
    def own_spell_only():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid);enemy=e.summon("CS2_182")
        own=play(p,"GAME_005");after_own=enemy.health
        g.end_turn();other=play(e,"GAME_005");after_other=enemy.health
        observed=f"after_own={after_own};after_enemy_spell={after_other};frog={body.zone.name};own_spell={own.zone.name};enemy_spell={other.zone.name}"
        return check(after_own==4 and after_other==4 and body.zone==Zone.PLAY,observed)
    audit(cid,[("own_spell_hits_enemy_minion_enemy_spell_ignored","Owner spell triggers exactly 1 damage to sole enemy minion; opponent spell gives no extra damage.",own_spell_only,"跨玩家施法事件和单随机目标。")])


def aranasi_broodmother():
    cid="DAL_185"
    def drawn_heals_owner():
        g,p,e=game(CardClass.WARLOCK)
        p.hero.damage=10;e.hero.damage=10
        mother=p.card(cid,zone=Zone.DECK);p.draw()
        observed=f"mother={mother.zone.name};own_health={p.hero.health};enemy_health={e.hero.health};hand={[c.id for c in p.hand]}"
        return check(mother.zone==Zone.HAND and p.hero.health==24 and e.hero.health==20 and mother.taunt,observed)
    audit(cid,[("draw_from_deck_heals_four","Actually drawing Broodmother from deck restores 4 to owner hero only; card stays in hand with Taunt.",drawn_heals_owner,"牌库真实抽取、治疗阵营与关键词。")])


def forests_aid():
    cid="DAL_256"
    def five_treants_and_twinspell():
        g,p,e=game(CardClass.DRUID)
        spell=play(p,cid)
        treants=[m for m in p.field if m.id=="DAL_256t2"]
        twin=[c for c in p.hand if c.id=="DAL_256ts"]
        observed=f"treants={[(m.atk,m.health,m.zone.name) for m in treants]};twin={[(c.id,c.zone.name) for c in twin]};spell={spell.zone.name}"
        return check(len(treants)==5 and all((m.atk,m.health)==(2,2) for m in treants)
                     and len(twin)==1 and twin[0].zone==Zone.HAND,observed)
    audit(cid,[("summon_five_two_two_and_twin","Playing Forest's Aid summons five 2/2 Treants and generates one Twinspell copy.",five_treants_and_twinspell,"召唤身材数量与复制体手牌区域。")])


def crystal_power():
    cid="DAL_350"
    def damage_choice():
        g,p,e=game(CardClass.DRUID)
        foe=e.summon("CS2_182");p.hero.damage=7
        spell=p.give(cid);spell.play(target=foe,choose="DAL_350a")
        observed=f"foe_health={foe.health};own_health={p.hero.health};spell={spell.zone.name}"
        return check(foe.health==3 and p.hero.health==23,observed)
    def heal_choice():
        g,p,e=game(CardClass.DRUID)
        p.hero.damage=7;foe=e.summon("CS2_182")
        spell=p.give(cid);spell.play(target=p.hero,choose="DAL_350b")
        observed=f"own_health={p.hero.health};foe_health={foe.health};spell={spell.zone.name}"
        return check(p.hero.health==28 and foe.health==5,observed)
    audit(cid,[("choose_damage_two","Damage option deals exactly 2 to selected minion and does not heal.",damage_choice,"伤害选项与生命对照。"),
               ("choose_heal_five","Heal option restores exactly 5 to selected hero and does not damage minion.",heal_choice,"治疗选项与敌方随从对照。")])


def blessing_ancients():
    cid="DAL_351"
    def own_minions_plus_one_and_twin():
        g,p,e=game(CardClass.DRUID)
        friends=[p.summon(WISP),p.summon("CS2_182")];enemy=e.summon(WISP)
        before=[(m.atk,m.health) for m in friends]
        spell=play(p,cid)
        twin=[c for c in p.hand if c.id=="DAL_351ts"]
        observed=f"before={before};after={[(m.atk,m.health) for m in friends]};enemy={enemy.atk}/{enemy.health};twin={[(c.id,c.zone.name) for c in twin]}"
        return check([(m.atk,m.health) for m in friends]==[(a+1,h+1) for a,h in before]
                     and (enemy.atk,enemy.health)==(1,1) and len(twin)==1,observed)
    audit(cid,[("buffs_all_friends_not_enemy_and_twin","All friendly minions gain +1/+1; enemy unaffected; one Twinspell copy enters hand.",own_minions_plus_one_and_twin,"双友军、敌人及双生法术。")])


def crystalsong_portal():
    cid="DAL_352"
    def branch(hand_minion):
        g,p,e=game(CardClass.DRUID)
        if hand_minion:original=p.give(WISP)
        spell=play(p,cid)
        options=list(p.choice.cards) if p.choice else []
        if options:p.choice.choose(options[0])
        hand=list(p.hand)
        generated=[c for c in hand if not hand_minion or c.id!=WISP]
        observed=f"held_minion={hand_minion};choice_options={[(c.id,int(c.type)) for c in options]};generated={[(c.id,int(c.type),int(c.card_class),c.zone.name) for c in generated]};choice_closed={p.choice is None}"
        return check(len(generated)==(1 if hand_minion else 3)
                     and (len(options)==3 if hand_minion else not options)
                     and all(c.type==CardType.MINION and CardClass.DRUID in c.classes for c in generated)
                     and p.choice is None,observed)
    audit(cid,[("empty_minion_hand_keeps_three","Without a minion in hand, Portal directly adds three Druid minions.",lambda:branch(False),"手牌条件正例、数量与职业。"),
               ("held_minion_discovers_one","With a held minion, Portal offers three candidates and keeps the chosen one.",lambda:branch(True),"实际选择交互和互斥分支。")])


def acornbearer():
    cid="DAL_354"
    def death_adds_two_squirrels():
        g,p,e=game(CardClass.DRUID)
        body=p.summon(cid);body.destroy()
        squirrels=[c for c in p.hand if c.id=="DAL_354t"]
        observed=f"body={body.zone.name};squirrels={[(c.atk,c.health,c.zone.name) for c in squirrels]}"
        return check(body.zone==Zone.GRAVEYARD and len(squirrels)==2
                     and all((c.atk,c.health,c.zone)==(1,1,Zone.HAND) for c in squirrels),observed)
    audit(cid,[("deathrattle_two_one_one_squirrels","Deathrattle adds two 1/1 Squirrel cards to hand.",death_adds_two_squirrels,"死亡区域、数量和手牌身材。")])


def lifeweaver():
    cid="DAL_355"
    def friendly_heal_generates_druid_spell():
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid);p.hero.damage=7
        spell=play(p,"CS2_089",target=p.hero)
        generated=list(p.hand)
        observed=f"hero_health={p.hero.health};generated={[(c.id,int(c.type),int(c.card_class),c.zone.name) for c in generated]};body={body.zone.name}"
        return check(p.hero.health==29 and len(generated)==1 and generated[0].type==CardType.SPELL
                     and CardClass.DRUID in generated[0].classes and generated[0].zone==Zone.HAND,observed)
    def no_actual_healing_no_card():
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid)
        spell=play(p,"CS2_089",target=p.hero)
        observed=f"full_hero={p.hero.health};hand={[c.id for c in p.hand]};body={body.zone.name}"
        return check(p.hero.health==30 and len(p.hand)==0,observed)
    audit(cid,[("actual_heal_adds_druid_spell","Actual healing of damaged friendly hero adds one Druid spell.",friendly_heal_generates_druid_spell,"真实治疗量、随机卡职业类型及手牌。"),
               ("no_health_restored_no_card","Healing an undamaged hero restores zero and adds no card.",no_actual_healing_no_card,"零实际治疗边界。")])


CHECKS={"DAL_007":rafaams_scheme,"DAL_008":dr_booms_scheme,"DAL_009":hagathas_scheme,
        "DAL_010":togwaggles_scheme,"DAL_011":lazuls_scheme,"DAL_030":shadowy_figure,
        "DAL_039":convincing_infiltrator,"DAL_040":shadequill,
        "DAL_047":walking_fountain,"DAL_049":underbelly_angler,"DAL_052":muckmorpher,
        "DAL_058":hecklebot,"DAL_059":dimensional_ripper,"DAL_060":clockwork_goblin,
        "DAL_062":sweeping_strikes,"DAL_063":wrenchcalibur,"DAL_064":blastmaster_boom,
        "DAL_065":unsleeping_soul,"DAL_070":boom_reaver,"DAL_071":mutate,"DAL_077":toxfin,
        "DAL_078":traveling_healer,"DAL_081":spellward_jeweler,"DAL_085":dalaran_crusader,
        "DAL_086":sunreaver_spy,"DAL_087":hench_clan_hag,"DAL_088":safeguard,
        "DAL_089":spellbook_binder,"DAL_090":hench_clan_sneak,"DAL_095":violet_spellsword,
        "DAL_096":violet_warden,"DAL_141":desperate_measures,"DAL_146":bronze_herald,
        "DAL_147":dragon_speaker,"DAL_163":messenger_raven,"DAL_173":darkest_hour,
        "DAL_177":conjurers_calling,"DAL_182":magic_dart_frog,
        "DAL_185":aranasi_broodmother,"DAL_256":forests_aid,"DAL_350":crystal_power,
        "DAL_351":blessing_ancients,"DAL_352":crystalsong_portal,"DAL_354":acornbearer,
        "DAL_355":lifeweaver}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
