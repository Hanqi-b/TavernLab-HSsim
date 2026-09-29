"""Card-specific live game checks for the collectible second 45 Saviors of Uldum YELLOW cards."""

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
PROBE_FILE = HERE / "uld_probe_b.csv"
VERDICT_FILE = HERE / "uld_verdict_b.csv"
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
ROSTER = ROSTER[45:90]
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


def beaming_sidekick():
    cid="ULD_191"
    def friendly_health_only():
        g,p,e=game()
        target=p.summon(WISP);enemy=e.summon(WISP)
        body=play(p,cid,target=target)
        observed=f"target={target.atk}/{target.health};enemy={enemy.atk}/{enemy.health};body={body.zone.name}"
        return check((target.atk,target.health)==(1,3) and (enemy.atk,enemy.health)==(1,1),observed)
    audit(cid,[("friendly_target_plus_two_health","Selected friendly Wisp gains exactly 2 Health; enemy Wisp unchanged.",friendly_health_only,"目标身材及阵营对照。")])


def living_monument():
    cid="ULD_193"
    def taunt_redirects_attack():
        g,p,e=game()
        body=play(p,cid);attacker=e.summon("CS2_182")
        g.end_turn()
        target_hero=attacker.can_attack(p.hero);target_taunt=attacker.can_attack(body)
        observed=f"taunt={body.taunt};hero_legal={target_hero};monument_legal={target_taunt};body={body.zone.name}"
        return check(body.taunt and not target_hero and target_taunt,observed)
    audit(cid,[("taunt_blocks_hero_attack","Enemy minion can attack Monument but cannot bypass it to attack hero.",taunt_redirects_attack,"真实目标合法性而非只读 Taunt 标签。")])


def wasteland_scorpid():
    cid="ULD_194"
    def poisonous_kills_high_health():
        g,p,e=game()
        body=play(p,cid);victim=e.summon("CS2_182")
        g.end_turn();g.end_turn()
        ready=body.can_attack(victim)
        if ready:body.attack(victim)
        observed=f"poison={body.poisonous};ready={ready};victim={victim.zone.name};body={body.zone.name}"
        return check(body.poisonous and ready and victim.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("poisonous_combat_kills_yeti","One attack by Poisonous Scorpid kills a 5-Health Yeti.",poisonous_kills_high_health,"实际攻击与目标死亡区域。")])


def frightened_flunky():
    cid="ULD_195"
    def discover_taunt():
        g,p,e=game(CardClass.WARRIOR)
        body=play(p,cid);choice=p.choice
        offered=list(choice.cards) if choice else []
        selected=offered[0] if offered else None
        if selected:choice.choose(selected)
        observed=f"body_taunt={body.taunt};offered={[(c.id,c.taunt) for c in offered]};chosen={None if selected is None else (selected.id,selected.zone.name)};choice_closed={p.choice is None}"
        return check(body.taunt and len(offered)==3 and all(c.taunt for c in offered)
                     and selected.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("discover_three_taunt_minions","Taunt body offers three Taunt minions; chosen one enters hand and Choice closes.",discover_taunt,"候选关键词、区域和交互闭合。")])


def neferset_ritualist():
    cid="ULD_196"
    def full_heal_both_adjacent():
        g,p,e=game()
        left=p.summon("CS2_182");right=p.summon("CS2_182")
        left.damage=3;right.damage=2
        body=play(p,cid,index=1)
        observed=f"field={[m.id for m in p.field]};left={left.health}/{left.max_health};right={right.health}/{right.max_health};body={body.zone.name}"
        return check(p.field[1] is body and left.health==5 and right.health==5,observed)
    audit(cid,[("heal_both_adjacent_to_full","Battlecry heals both damaged adjacent friendly Yetis fully.",full_heal_both_adjacent,"指定入场位置与双邻位生命。")])


def quicksand_elemental():
    cid="ULD_197"
    def debuff_enemies_this_turn():
        g,p,e=game()
        friend=p.summon("CS2_182");enemy=e.summon("CS2_182")
        body=play(p,cid)
        during=(friend.atk,enemy.atk)
        g.end_turn();after=(friend.atk,enemy.atk)
        observed=f"during={during};after_end={after};body={body.zone.name}"
        return check(during==(4,2) and after==(4,4),observed)
    audit(cid,[("enemy_attack_minus_two_expires","Enemy Yeti loses 2 Attack this turn; friendly Yeti stays 4 and enemy returns to 4 next turn.",debuff_enemies_this_turn,"双方身材与回合到期。")])


def conjured_mirage():
    cid="ULD_198"
    def start_turn_shuffle_self():
        g,p,e=game()
        body=play(p,cid);start_taunt=body.taunt
        for _ in range(10):p.card(WISP,zone=Zone.DECK)
        g.end_turn();g.end_turn()
        observed=f"start_taunt={start_taunt};body={body.zone.name};in_deck={body in p.deck};field={[m.id for m in p.field]}"
        return check(start_taunt and body.zone==Zone.DECK and body in p.deck and body not in p.field,observed)
    audit(cid,[("shuffles_into_deck_on_owner_turn_begin","Taunt Mirage moves from battlefield into owner's deck at next own turn start.",start_turn_shuffle_self,"跨回合真实区域移动。")])


def restless_mummy():
    cid="ULD_206"
    def rush_and_reborn():
        g,p,e=game(CardClass.WARRIOR)
        victim=e.summon(WISP);body=play(p,cid)
        hero_legal=body.can_attack(e.hero);minion_legal=body.can_attack(victim)
        body.destroy()
        reborn=[m for m in p.field if m.id==cid]
        observed=f"rush={body.rush};hero_legal={hero_legal};minion_legal={minion_legal};old={body.zone.name};reborn={[(m.health,m.reborn,m.zone.name) for m in reborn]}"
        return check(body.rush and not hero_legal and minion_legal and body.zone==Zone.GRAVEYARD
                     and len(reborn)==1 and reborn[0].health==1,observed)
    audit(cid,[("rush_targeting_and_one_health_reborn","Can attack enemy minion immediately but not hero; first death returns one copy at 1 Health.",rush_and_reborn,"攻击合法性、死亡与复生身材。")])


def ancestral_guardian():
    cid="ULD_207"
    def lifesteal_and_reborn():
        g,p,e=game()
        p.hero.damage=10;victim=e.summon(WISP)
        body=play(p,cid)
        g.end_turn();g.end_turn()
        base=p.hero.health;body.attack(victim);healed=p.hero.health
        body.destroy()
        reborn=[m for m in p.field if m.id==cid]
        observed=f"lifesteal={body.lifesteal};hero={base}->{healed};victim={victim.zone.name};old={body.zone.name};reborn={[(m.health,m.zone.name) for m in reborn]}"
        return check(body.lifesteal and healed==base+body.atk and victim.zone==Zone.GRAVEYARD
                     and len(reborn)==1 and reborn[0].health==1,observed)
    audit(cid,[("lifesteal_heals_on_attack_and_reborn_one_health","Attack kills Wisp and Lifesteal heals by damage; death then returns one 1-Health copy.",lifesteal_and_reborn,"实际战斗、治疗、死亡区域与复生。")])


def khartut_defender():
    cid="ULD_208"
    def both_deaths_heal_and_reborn_once():
        g,p,e=game()
        p.hero.damage=12
        body=p.summon(cid);taunt=body.taunt
        body.destroy();after_first=p.hero.health
        reborn=[m for m in p.field if m.id==cid]
        first_reborn_health=reborn[0].health if reborn else None
        if reborn:reborn[0].destroy()
        after_second=p.hero.health
        observed=f"taunt={taunt};old={body.zone.name};reborn_count={len(reborn)};reborn_initial_health={first_reborn_health};first={after_first};second={after_second};field={[m.id for m in p.field]}"
        return check(taunt and body.zone==Zone.GRAVEYARD and len(reborn)==1 and first_reborn_health==1
                     and after_first==21 and after_second==24 and not any(m.id==cid for m in p.field),observed)
    audit(cid,[("deathrattle_twice_reborn_once","First death heals owner 3 and Reborn returns 1-Health copy; second death heals 3 again without another return.",both_deaths_heal_and_reborn_once,"连续死亡、治疗量、复生次数。")])


def vulpera_scoundrel():
    cid="ULD_209"
    def branch(mystery):
        g,p,e=game()
        body=play(p,cid);choice=p.choice
        options=list(choice.cards) if choice else []
        mystery_card=next((c for c in options if c.id=="ULD_209t"),None)
        chosen=mystery_card if mystery else next((c for c in options if c.id!="ULD_209t"),None)
        if chosen:choice.choose(chosen)
        hand=list(p.hand)
        observed=f"mystery={mystery};offered={[(c.id,int(c.type)) for c in options]};hand={[(c.id,int(c.type),c.zone.name) for c in hand]};choice_closed={p.choice is None}"
        return check(len(options)==4 and mystery_card is not None and len(hand)==1
                     and hand[0].type==CardType.SPELL and (mystery or hand[0].id==chosen.id)
                     and p.choice is None,observed)
    audit(cid,[("choose_visible_spell","Battlecry offers three spells plus mystery; selecting visible spell gives that spell.",lambda:branch(False),"候选数量、明示选项与手牌。"),
               ("choose_mystery_spell","Selecting mystery option gives a random spell instead of mystery token.",lambda:branch(True),"神秘选项结果与交互收束。")])


def wild_bloodstinger():
    cid="ULD_212"
    def summons_enemy_hand_then_attacks():
        g,p,e=game(CardClass.HUNTER)
        victim=e.give("ULD_193")
        body=play(p,cid)
        observed=f"victim={victim.zone.name}:{victim.health};enemy_field={[m.id for m in e.field]};bloodstinger={body.health}:{body.zone.name};enemy_hand={[c.id for c in e.hand]}"
        return check(victim.zone==Zone.PLAY and victim in e.field and victim.health<victim.max_health
                     and body.zone==Zone.GRAVEYARD and victim not in e.hand,observed)
    def lethal_target_goes_to_graveyard():
        g,p,e=game(CardClass.HUNTER)
        victim=e.give("CS2_182");body=play(p,cid)
        observed=f"victim={victim.zone.name};enemy_hand={[c.id for c in e.hand]};enemy_field={[m.id for m in e.field]};body_health={body.health}"
        return check(victim.zone==Zone.GRAVEYARD and victim not in e.hand and body.health<body.max_health,observed)
    audit(cid,[("surviving_hand_target_summoned_and_attacked","Sole high-Health opponent hand minion moves to their board and takes attack damage.",summons_enemy_hand_then_attacks,"高血目标保留战场，证明真实召唤和攻击。"),
               ("lethal_hand_target_dies","A 5-Health hand Yeti is summoned, attacked and ends in graveyard.",lethal_target_goes_to_graveyard,"致死目标分支。")])


def generous_mummy():
    cid="ULD_214"
    def enemy_hand_cost_aura_and_reborn():
        g,p,e=game()
        enemy_card=e.give("CS2_182");base=enemy_card.cost
        body=play(p,cid);during=enemy_card.cost
        body.destroy();reborn=[m for m in p.field if m.id==cid]
        after_reborn=enemy_card.cost
        if reborn:reborn[0].destroy()
        after_final=enemy_card.cost
        observed=f"cost={base}->{during}->{after_reborn}->{after_final};reborn_count={len(reborn)};body={body.zone.name}"
        return check(base==4 and during==3 and len(reborn)==1 and after_reborn==3 and after_final==4,observed)
    audit(cid,[("enemy_cards_one_cheaper_during_both_lives","Opponent hand card costs 1 less during original and Reborn mummy; after second death discount ends.",enemy_hand_cost_aura_and_reborn,"敌方费用光环的建立、复生、撤销。")])


def wrapped_golem():
    cid="ULD_215"
    def end_turn_scarab_and_reborn():
        g,p,e=game()
        body=play(p,cid)
        g.end_turn()
        scarabs=[m for m in p.field if m.id=="ULD_215t"]
        body.destroy();reborn=[m for m in p.field if m.id==cid]
        observed=f"scarabs={[(m.atk,m.health,m.taunt,m.zone.name) for m in scarabs]};old={body.zone.name};reborn={[(m.health,m.zone.name) for m in reborn]}"
        return check(len(scarabs)==1 and (scarabs[0].atk,scarabs[0].health,scarabs[0].taunt)==(1,1,True)
                     and len(reborn)==1 and reborn[0].health==1,observed)
    audit(cid,[("end_turn_scarab_and_reborn","At owner turn end summons one 1/1 Taunt Scarab; death returns one 1-Health copy.",end_turn_scarab_and_reborn,"回合末召唤及复生区域。")])


def micro_mummy():
    cid="ULD_217"
    def buff_other_at_end_and_reborn():
        g,p,e=game(CardClass.PALADIN)
        other=p.summon(WISP);body=play(p,cid)
        g.end_turn();buffed=other.atk
        body.destroy();reborn=[m for m in p.field if m.id==cid]
        observed=f"other_attack={buffed};body={body.zone.name};reborn={[(m.atk,m.health,m.zone.name) for m in reborn]}"
        return check(buffed==2 and len(reborn)==1 and reborn[0].health==1 and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("end_turn_buffs_other_then_reborn","At owner turn end only other Wisp gains +1 Attack; first death returns 1-Health Mummy.",buff_other_at_end_and_reborn,"排除自身、时点和复生。")])


def mischief_maker():
    cid="ULD_229"
    def swap_top_deck_cards():
        g,p,e=game()
        own_bottom=p.card(WISP,zone=Zone.DECK);own_top=p.card("CS2_182",zone=Zone.DECK)
        enemy_bottom=e.card("BOT_445",zone=Zone.DECK);enemy_top=e.card("NEW1_023",zone=Zone.DECK)
        before=(p.deck[-1].id,e.deck[-1].id)
        body=play(p,cid)
        after=(p.deck[-1].id,e.deck[-1].id)
        observed=f"before={before};after={after};own_bottom={own_bottom.zone.name};enemy_bottom={enemy_bottom.zone.name};body={body.zone.name}"
        return check(after==(before[1],before[0]) and own_bottom in p.deck and enemy_bottom in e.deck
                     and body.zone==Zone.PLAY,observed)
    audit(cid,[("only_top_cards_swap_between_decks","Battlecry swaps the top deck card IDs while each lower card remains in its original deck.",swap_top_deck_cards,"双方牌库顶与非顶对照。")])


def whirlkick_master():
    cid="ULD_231"
    def combo_card_generates_combo():
        g,p,e=game(CardClass.ROGUE)
        master=play(p,cid);play(p,"GAME_005")
        victim=e.summon("CS2_182")
        combo=play(p,"EX1_134",target=victim)
        generated=list(p.hand)
        observed=f"victim_health={victim.health};generated={[(c.id,c.has_combo,c.zone.name) for c in generated]};combo={combo.zone.name};master={master.zone.name}"
        return check(victim.health==3 and len(generated)==1 and generated[0].has_combo and generated[0].zone==Zone.HAND,observed)
    def noncombo_no_generation():
        g,p,e=game(CardClass.ROGUE)
        master=play(p,cid);play(p,WISP)
        observed=f"hand={[c.id for c in p.hand]};master={master.zone.name}"
        return check(len(p.hand)==0,observed)
    audit(cid,[("playing_combo_generates_combo_card","After activating Combo, playing SI:7 damages target and adds one random Combo card.",combo_card_generates_combo,"实际连击触发、目标生命及生成卡标签。"),
               ("ordinary_minion_no_card","Playing a non-Combo Wisp generates no card.",noncombo_no_generation,"非连击对照。")])


def tortollan_pilgrim():
    cid="ULD_236"
    def choose_deck_spell_cast_copy():
        g,p,e=game(CardClass.MAGE)
        original=p.card("CS2_093",zone=Zone.DECK)
        body=play(p,cid)
        choice=p.choice;options=list(choice.cards) if choice else []
        chosen=options[0] if options else None
        if chosen:choice.choose(chosen)
        observed=f"offered={[(c.id,c.zone.name) for c in options]};chosen={None if chosen is None else (chosen.id,chosen.zone.name)};deck_original={original.zone.name};enemy_health={e.hero.health};body={body.zone.name};choice_closed={p.choice is None}"
        return check(len(options)>=1 and all(c.id=="CS2_093" for c in options)
                     and original.zone==Zone.DECK and e.hero.health==28 and p.choice is None,observed)
    audit(cid,[("discover_copy_and_cast_consecration","Discover copies sole no-target deck spell, casts selected copy for 2 enemy hero damage, leaves original in deck.",choose_deck_spell_cast_copy,"实际选择、法术效果与牌库原件。")])


def reno_relicologist():
    cid="ULD_238"
    def no_enemy_minion_no_hero_damage():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid)
        observed=f"enemy_hero_health={e.hero.health};body={body.zone.name};enemy_field={len(e.field)}"
        return check(e.hero.health==30 and body.zone==Zone.PLAY,observed)
    def one_enemy_minion_ten_damage_only():
        g,p,e=game(CardClass.MAGE)
        target=e.summon("ULD_193")
        body=play(p,cid)
        observed=f"target={target.health}:{target.zone.name};enemy_hero={e.hero.health};body={body.zone.name}"
        return check(target.zone==Zone.GRAVEYARD and e.hero.health==30,observed)
    audit(cid,[("empty_enemy_board_no_hero_damage","With no enemy minion, the ten damage has no valid minion and enemy hero remains undamaged.",no_enemy_minion_no_hero_damage,"敌方英雄不能替代随从目标。"),
               ("one_enemy_minion_takes_damage","With one 10-Health enemy minion, all ten hits go to it and do not hit hero.",one_enemy_minion_ten_damage_only,"单合法随从目标。")])


def flame_ward():
    cid="ULD_239"
    def enemy_minion_attack_triggers_once():
        g,p,e=game(CardClass.MAGE)
        secret=play(p,cid)
        attacker=e.summon("CS2_182");other=e.summon("CS2_182")
        g.end_turn();attacker.attack(p.hero)
        observed=f"secret={secret.zone.name};attacker={attacker.health}:{attacker.zone.name};other={other.health}:{other.zone.name};hero={p.hero.health}"
        return check(secret.zone==Zone.GRAVEYARD and attacker.health==2 and other.health==2 and p.hero.health==26,observed)
    audit(cid,[("after_enemy_minion_attacks_hero_secret_reveals_aoe","Enemy minion attacks owner hero; secret reveals and deals 3 to every enemy minion.",enemy_minion_attack_triggers_once,"真实攻击、奥秘区域、双方生命。")])


def arcane_flakmage():
    cid="ULD_240"
    def own_secret_aoe_enemy_only():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid);friend=p.summon("CS2_182");foes=[e.summon("CS2_182") for _ in range(2)]
        secret=play(p,"ULD_239")
        observed=f"foes={[m.health for m in foes]};friend={friend.health};enemy_hero={e.hero.health};secret={secret.zone.name};body={body.zone.name}"
        return check([m.health for m in foes]==[3,3] and friend.health==5 and e.hero.health==30
                     and secret.zone==Zone.SECRET,observed)
    audit(cid,[("playing_secret_deals_two_to_enemy_minions","Playing a Secret deals 2 to each enemy minion, not friendly minion or enemy hero.",own_secret_aoe_enemy_only,"奥秘实际打出、双敌与友军对照。")])


def puzzle_box():
    cid="ULD_216"
    def actual_random_cast_count():
        g,p,e=game(CardClass.MAGE,CardClass.PRIEST,seed=181)
        p.summon("CS2_182");e.summon("CS2_182")
        class CastTracker(BaseObserver):
            def __init__(self):self.cast_ids=[]
            def targeted_action(self,action,source,target,*args):
                if isinstance(action,CastSpell) and getattr(source,"id",None)==cid:
                    self.cast_ids.append(getattr(target,"id",None))
        tracker=CastTracker();g.manager.observers.append(tracker)
        spell=play(p,cid)
        observed=f"casts={tracker.cast_ids};count={len(tracker.cast_ids)};spell={spell.zone.name};choice={p.choice};heroes={p.hero.health}/{e.hero.health}"
        return check(len(tracker.cast_ids)==10 and len(set(tracker.cast_ids))>1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("ten_actual_random_spells_resolve","Puzzle Box emits ten actual CastSpell resolutions, with more than one spell identity.",actual_random_cast_count,"观察 CastSpell 目标事件，统计实际施放而非静态乘数。")])


def infested_goblin():
    cid="ULD_250"
    def death_two_scarabs():
        g,p,e=game()
        body=p.summon(cid);taunt=body.taunt;body.destroy()
        scarabs=[c for c in p.hand if c.id=="ULD_215t"]
        observed=f"taunt={taunt};body={body.zone.name};scarabs={[(c.atk,c.health,c.taunt,c.zone.name) for c in scarabs]}"
        return check(taunt and body.zone==Zone.GRAVEYARD and len(scarabs)==2
                     and all((c.atk,c.health,c.taunt,c.zone)==(1,1,True,Zone.HAND) for c in scarabs),observed)
    audit(cid,[("death_adds_two_taunt_scarabs","Taunt Goblin dies and adds two 1/1 Taunt Scarab cards to hand.",death_two_scarabs,"死亡区域、手牌数量与关键词。")])


def tomb_warden():
    cid="ULD_253"
    def summons_exact_taunt_copy():
        g,p,e=game(CardClass.WARRIOR)
        body=play(p,cid);copies=[m for m in p.field if m.id==cid]
        observed=f"copies={[(m.atk,m.health,m.taunt,m.zone.name) for m in copies]};original={body.zone.name}"
        return check(len(copies)==2 and all((m.atk,m.health,m.taunt)==(3,6,True) for m in copies),observed)
    audit(cid,[("battlecry_one_same_taunt_copy","Playing Warden gives two separate 3/6 Taunt bodies, original and copy.",summons_exact_taunt_copy,"召唤数量、身材和嘲讽。")])


def into_the_fray():
    cid="ULD_256"
    def hand_taunt_only():
        g,p,e=game(CardClass.WARRIOR)
        taunts=[p.give("CS1_042"),p.give("ULD_193")];plain=p.give(WISP)
        before=[(c.atk,c.health) for c in taunts]
        spell=play(p,cid)
        observed=f"before={before};after={[(c.atk,c.health) for c in taunts]};plain={plain.atk}/{plain.health};spell={spell.zone.name}"
        return check([(c.atk,c.health) for c in taunts]==[(a+2,h+2) for a,h in before]
                     and (plain.atk,plain.health)==(1,1),observed)
    audit(cid,[("all_hand_taunt_plus_two_two","Both Taunt minions in hand gain +2/+2; non-Taunt Wisp remains unchanged.",hand_taunt_only,"双合法候选、单反例与手牌身材。")])


def armagedillo():
    cid="ULD_258"
    def end_turn_buffs_hand_taunts():
        g,p,e=game(CardClass.WARRIOR)
        taunts=[p.give("CS1_042"),p.give("ULD_193")];plain=p.give(WISP)
        before=[(c.atk,c.health) for c in taunts]
        body=play(p,cid);g.end_turn()
        observed=f"before={before};after={[(c.atk,c.health) for c in taunts]};plain={plain.atk}/{plain.health};body_taunt={body.taunt}"
        return check(body.taunt and [(c.atk,c.health) for c in taunts]==[(a+2,h+2) for a,h in before]
                     and (plain.atk,plain.health)==(1,1),observed)
    audit(cid,[("owner_end_turn_buffs_taunt_hand","At owner turn end, both Taunt hand minions gain +2/+2; Wisp does not.",end_turn_buffs_hand_taunts,"回合触发时点、双目标和非嘲讽对照。")])


def high_priest_amet():
    cid="ULD_262"
    def summoned_health_tracks_amet_current():
        g,p,e=game(CardClass.PRIEST)
        amet=play(p,cid);first=p.summon(WISP)
        first_health=first.health
        amet.damage=2;second=p.summon(WISP)
        observed=f"amet={amet.health}/{amet.max_health};first={first.health}/{first.max_health};second={second.health}/{second.max_health};first_at_summon={first_health}"
        return check(first_health==amet.max_health and second.health==amet.health and first.atk==1 and second.atk==1,observed)
    audit(cid,[("new_minion_health_equals_current_amet","One Wisp summoned at full Amet Health and another after Amet takes 2 damage receive corresponding Health.",summoned_health_tracks_amet_current,"两次真实召唤与施法者当前生命变化。")])


def embalming_ritual():
    cid="ULD_265"
    def grants_reborn_and_resummons_once():
        g,p,e=game(CardClass.PRIEST)
        target=p.summon(WISP);spell=play(p,cid,target=target)
        tag=target.reborn;target.destroy()
        revived=[m for m in p.field if m.id==WISP]
        observed=f"tag={tag};old={target.zone.name};revived={[(m.health,m.reborn,m.zone.name) for m in revived]};spell={spell.zone.name}"
        return check(tag and target.zone==Zone.GRAVEYARD and len(revived)==1
                     and revived[0].health==1 and not revived[0].reborn,observed)
    audit(cid,[("grant_reborn_then_one_resummon","Target gains Reborn; death yields one 1-Health non-Reborn copy.",grants_reborn_and_resummons_once,"实际关键词、死亡与复生区域。")])


def psychopomp():
    cid="ULD_268"
    def resummon_died_friendly_with_reborn():
        g,p,e=game(CardClass.PRIEST)
        dead=p.summon(WISP);dead.destroy()
        body=play(p,cid)
        returned=[m for m in p.field if m.id==WISP]
        observed=f"dead_original={dead.zone.name};returned={[(m.atk,m.health,m.reborn,m.zone.name) for m in returned]};body={body.zone.name}"
        return check(dead.zone==Zone.GRAVEYARD and len(returned)==1 and returned[0].reborn
                     and (returned[0].atk,returned[0].health)==(1,1),observed)
    audit(cid,[("revives_only_dead_friendly_with_reborn","Battlecry returns sole friendly minion that died this game and grants it Reborn.",resummon_died_friendly_with_reborn,"真实友方死亡历史及复活关键词。")])


def wretched_reclaimer():
    cid="ULD_269"
    def kill_damaged_friend_restore_full():
        g,p,e=game(CardClass.PRIEST)
        target=p.summon("CS2_182");target.damage=3
        body=play(p,cid,target=target)
        returned=[m for m in p.field if m.id==target.id]
        observed=f"original={target.zone.name};returned={[(m.health,m.max_health,m.zone.name) for m in returned]};body={body.zone.name}"
        return check(target.zone==Zone.GRAVEYARD and len(returned)==1
                     and (returned[0].health,returned[0].max_health)==(5,5),observed)
    audit(cid,[("destroy_damaged_friendly_and_revive_full","Damaged friendly Yeti is destroyed and replaced by one full-Health copy.",kill_damaged_friend_restore_full,"目标死亡与复活生命。")])


def sandhoof_waterbearer():
    cid="ULD_270"
    def heals_only_damaged_friendly():
        g,p,e=game(CardClass.PRIEST)
        p.hero.damage=8;e.hero.damage=8
        body=play(p,cid);g.end_turn()
        observed=f"own_health={p.hero.health};enemy_health={e.hero.health};body={body.zone.name}"
        return check(p.hero.health==27 and e.hero.health==22,observed)
    audit(cid,[("end_turn_heals_damaged_friendly_five","At owner turn end heals sole damaged friendly hero 5, not equally damaged enemy hero.",heals_only_damaged_friendly,"触发时点、目标阵营和治疗量。")])


def injured_tolvir():
    cid="ULD_271"
    def self_damage_three_and_taunt():
        g,p,e=game(CardClass.PRIEST)
        body=play(p,cid)
        observed=f"health={body.health}/{body.max_health};damage={body.damage};taunt={body.taunt};zone={body.zone.name}"
        return check(body.taunt and body.health==body.max_health-3 and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_three_self_damage","Played Taunt Tol'vir immediately takes 3 damage and remains on board.",self_damage_three_and_taunt,"自身生命和嘲讽。")])


def holy_ripple():
    cid="ULD_272"
    def all_enemy_hit_all_friend_heal():
        g,p,e=game(CardClass.PRIEST)
        p.hero.damage=2;friend=p.summon("CS2_182");friend.damage=2
        foe=e.summon("CS2_182")
        spell=play(p,cid)
        observed=f"own_hero={p.hero.health};friend={friend.health};foe={foe.health};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(p.hero.health==29 and friend.health==4 and foe.health==4 and e.hero.health==29,observed)
    audit(cid,[("all_enemies_one_all_friends_heal_one","Both enemy hero/minion take 1; damaged friendly hero/minion each heal 1.",all_enemy_hit_all_friend_heal,"四类角色范围和实际生命。")])


def overflow():
    cid="ULD_273"
    def heal_all_draw_five():
        g,p,e=game(CardClass.DRUID)
        p.hero.damage=6;e.hero.damage=6
        friend=p.summon("CS2_182");foe=e.summon("CS2_182")
        friend.damage=3;foe.damage=3
        cards=[p.card(WISP,zone=Zone.DECK) for _ in range(5)]
        spell=play(p,cid)
        observed=f"heroes={p.hero.health}/{e.hero.health};minions={friend.health}/{foe.health};drawn={sum(c.zone==Zone.HAND for c in cards)};deck={len(p.deck)};spell={spell.zone.name}"
        return check((p.hero.health,e.hero.health)==(29,29) and (friend.health,foe.health)==(5,5)
                     and all(c.zone==Zone.HAND for c in cards) and not p.deck,observed)
    audit(cid,[("all_characters_heal_five_draw_five","Both heroes and minions heal 5 capped at max; five deck cards enter hand.",heal_all_draw_five,"双方角色治疗与五次实际抽牌区域。")])


def wasteland_assassin():
    cid="ULD_274"
    def stealth_reborn_once():
        g,p,e=game()
        body=play(p,cid);initial=body.stealthed
        untargetable=body not in e.give("CS2_029").play_targets
        body.destroy();reborn=[m for m in p.field if m.id==cid]
        observed=f"initial_stealth={initial};enemy_cannot_target={untargetable};body={body.zone.name};reborn={[(m.health,m.stealthed,m.zone.name) for m in reborn]}"
        return check(initial and untargetable and len(reborn)==1 and reborn[0].health==1,observed)
    audit(cid,[("stealth_target_protection_and_reborn","Starts Stealthed and absent from enemy spell targets; first death returns one 1-Health Assassin.",stealth_reborn_once,"潜行目标规则和复生区域。")])


def bone_wraith():
    cid="ULD_275"
    def taunt_reborn_once():
        g,p,e=game()
        body=play(p,cid);initial=body.taunt
        body.destroy();reborn=[m for m in p.field if m.id==cid]
        observed=f"original_taunt={initial};original={body.zone.name};reborn={[(m.health,m.taunt,m.reborn,m.zone.name) for m in reborn]}"
        return check(initial and body.zone==Zone.GRAVEYARD and len(reborn)==1
                     and reborn[0].health==1 and reborn[0].taunt and not reborn[0].reborn,observed)
    audit(cid,[("taunt_and_one_health_reborn","Taunt Wraith dies once and returns as one 1-Health Taunt minion without another Reborn.",taunt_reborn_once,"嘲讽、死亡及复生次数。")])


def evil_totem():
    cid="ULD_276"
    def end_turn_gives_lackey():
        g,p,e=game(CardClass.SHAMAN)
        body=play(p,cid);g.end_turn()
        generated=list(p.hand)
        observed=f"hand={[(c.id,c.mark_of_evil,c.zone.name) for c in generated]};body={body.zone.name}"
        return check(len(generated)==1 and generated[0].mark_of_evil and generated[0].zone==Zone.HAND,observed)
    audit(cid,[("owner_end_turn_one_lackey","At owner turn end, exactly one Lackey enters hand.",end_turn_gives_lackey,"回合时点、生成牌标记与区域。")])


def sahket_sapper():
    cid="ULD_280"
    def bounce_enemy_only():
        g,p,e=game(CardClass.ROGUE)
        friend=p.summon(WISP);enemy=e.summon("CS2_182")
        body=p.summon(cid);body.destroy()
        observed=f"body={body.zone.name};enemy={enemy.zone.name};enemy_hand={[c.id for c in e.hand]};friend={friend.zone.name}"
        return check(body.zone==Zone.GRAVEYARD and enemy.zone==Zone.HAND and enemy in e.hand
                     and friend.zone==Zone.PLAY,observed)
    audit(cid,[("deathrattle_bounces_enemy_minion","Deathrattle returns sole enemy minion to opponent's hand, leaving friendly Wisp on board.",bounce_enemy_only,"目标阵营与战场/手牌区域。")])


def jar_dealer():
    cid="ULD_282"
    def random_one_cost_minion_to_hand():
        g,p,e=game()
        body=p.summon(cid);body.destroy()
        added=list(p.hand)
        observed=f"body={body.zone.name};added={[(c.id,c.cost,int(c.type),c.zone.name) for c in added]}"
        return check(body.zone==Zone.GRAVEYARD and len(added)==1 and added[0].cost==1
                     and added[0].type==CardType.MINION and added[0].zone==Zone.HAND,observed)
    audit(cid,[("deathrattle_adds_one_cost_minion","Deathrattle adds exactly one random 1-Cost minion to hand.",random_one_cost_minion_to_hand,"死亡、生成卡类型费用与区域。")])


def hooked_scimitar():
    cid="ULD_285"
    def branch(combo):
        g,p,e=game(CardClass.ROGUE)
        if combo:play(p,"GAME_005")
        weapon=play(p,cid)
        observed=f"combo={combo};weapon={weapon.atk}/{weapon.durability}:{weapon.zone.name};hero_weapon={p.weapon.id if p.weapon else None}"
        return check(weapon.atk==(4 if combo else 2) and p.weapon is weapon,observed)
    audit(cid,[("combo_plus_two_attack","After a prior card, weapon equips at 4 Attack.",lambda:branch(True),"真实前置出牌与连击。"),
               ("no_combo_base_attack","As first card, weapon equips at base 2 Attack.",lambda:branch(False),"无连击对照。")])


def shadow_of_death():
    cid="ULD_286"
    def three_shadows_and_on_draw_copy():
        g,p,e=game(CardClass.ROGUE)
        target=e.summon("CS2_182");spell=play(p,cid,target=target)
        shadows=[c for c in p.deck if c.id=="ULD_286t"]
        before=len(shadows)
        if shadows:p.draw()
        copies=[m for m in p.field if m.id==target.id]
        observed=f"shadows_before_draw={before};shadow_zones={[(c.id,c.zone.name) for c in shadows]};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};original={target.zone.name};spell={spell.zone.name}"
        return check(before==3 and len(copies)==1 and target.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("shuffle_three_shadows_and_draw_summons_copy","Selected enemy minion creates three Shadows in own deck; drawing one summons a copy on own board.",three_shadows_and_on_draw_copy,"阴影数量、真实抽牌、复制区域与原目标保留。")])


def anka_buried():
    cid="ULD_288"
    def transform_deathrattle_hand_only():
        g,p,e=game(CardClass.ROGUE)
        dr=p.give("EX1_556");plain=p.give(WISP)
        before=(dr.atk,dr.health,dr.cost)
        body=play(p,cid)
        observed=f"before={before};deathrattle={dr.atk}/{dr.health}:cost{dr.cost}:dr{dr.has_deathrattle};plain={plain.atk}/{plain.health}:cost{plain.cost};body={body.zone.name}"
        return check(before==(2,3,3) and (dr.atk,dr.health,dr.cost)==(1,1,1) and dr.has_deathrattle
                     and (plain.atk,plain.health,plain.cost)==(1,1,0),observed)
    audit(cid,[("held_deathrattle_becomes_one_one_one_cost","Held Deathrattle minion becomes 1/1 costing 1 and retains Deathrattle; held Wisp unchanged.",transform_deathrattle_hand_only,"手牌筛选、身材、费用及亡语。")])


def fishflinger():
    cid="ULD_289"
    def both_players_get_murloc():
        g,p,e=game()
        body=play(p,cid)
        own=list(p.hand);other=list(e.hand)
        observed=f"owner={[(c.id,Race.MURLOC in c.races,c.zone.name) for c in own]};enemy={[(c.id,Race.MURLOC in c.races,c.zone.name) for c in other]};body={body.zone.name}"
        return check(len(own)==len(other)==1 and all(Race.MURLOC in c.races and c.zone==Zone.HAND for c in own+other),observed)
    audit(cid,[("one_random_murloc_each_hand","Both players gain exactly one Murloc hand card.",both_players_get_murloc,"双玩家独立手牌与种族。")])


def history_buff():
    cid="ULD_290"
    def playing_minion_buffs_held_minion():
        g,p,e=game()
        body=play(p,cid);held=p.give("CS2_182");spell=p.give("CS2_029")
        played=play(p,WISP)
        observed=f"held={held.atk}/{held.health}:{held.zone.name};spell={spell.zone.name};played={played.zone.name};body={body.zone.name}"
        return check((held.atk,held.health)==(5,6) and held.zone==Zone.HAND and spell.zone==Zone.HAND,observed)
    audit(cid,[("later_minion_play_buffs_held_minion","Playing Wisp gives sole held minion +1/+1 while held spell stays unchanged.",playing_minion_buffs_held_minion,"后续真实随从出牌事件、手牌目标。")])


def corrupt_the_waters():
    cid="ULD_291"
    def six_battlecries_unlock_double_power():
        g,p,e=game(CardClass.SHAMAN)
        quest=play(p,cid)
        for _ in range(5):
            body=play(p,"ULD_191")
            body.destroy()
        before=quest.progress
        sixth=play(p,"ULD_191")
        power=p.hero.power.id
        sixth.destroy()
        p.used_mana=0
        p.hero.power.use()
        target=p.summon(WISP)
        sidekick=play(p,"ULD_191",target=target)
        observed=f"after_five={before};after_six={quest.progress};quest={quest.zone.name};power={power};target={target.health}/{target.max_health};sidekick={sidekick.zone.name}"
        return check(before==5 and quest.progress==6 and quest.zone==Zone.GRAVEYARD
                     and power=="ULD_291p" and target.health==5,observed)
    audit(cid,[("six_battlecries_reward_doubles_next_battlecry","Six actual Battlecry minion plays complete Quest; hero power makes a +2 Health Battlecry grant +4.",six_battlecries_unlock_double_power,"逐次任务进度、奖励英雄技能与双倍效果。")])


CHECKS={"ULD_191":beaming_sidekick,"ULD_193":living_monument,"ULD_194":wasteland_scorpid,
        "ULD_195":frightened_flunky,"ULD_196":neferset_ritualist,"ULD_197":quicksand_elemental,
        "ULD_198":conjured_mirage,"ULD_206":restless_mummy,"ULD_207":ancestral_guardian,
        "ULD_208":khartut_defender,"ULD_209":vulpera_scoundrel,"ULD_212":wild_bloodstinger,
        "ULD_214":generous_mummy,"ULD_215":wrapped_golem,"ULD_217":micro_mummy}
CHECKS.update({"ULD_229":mischief_maker,"ULD_231":whirlkick_master,"ULD_236":tortollan_pilgrim,
               "ULD_238":reno_relicologist,"ULD_239":flame_ward,"ULD_240":arcane_flakmage})
CHECKS["ULD_216"]=puzzle_box
CHECKS.update({"ULD_250":infested_goblin,"ULD_253":tomb_warden,"ULD_256":into_the_fray,
               "ULD_258":armagedillo,"ULD_262":high_priest_amet,"ULD_265":embalming_ritual,
               "ULD_268":psychopomp,"ULD_269":wretched_reclaimer,"ULD_270":sandhoof_waterbearer,
               "ULD_271":injured_tolvir,"ULD_272":holy_ripple,"ULD_273":overflow})
CHECKS.update({"ULD_274":wasteland_assassin,"ULD_275":bone_wraith,"ULD_276":evil_totem,
               "ULD_280":sahket_sapper,"ULD_282":jar_dealer,"ULD_285":hooked_scimitar,
               "ULD_286":shadow_of_death,"ULD_288":anka_buried,"ULD_289":fishflinger,
               "ULD_290":history_buff,"ULD_291":corrupt_the_waters})

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
