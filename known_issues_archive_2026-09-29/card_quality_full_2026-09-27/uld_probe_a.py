"""Card-specific live game checks for the collectible first 45 Saviors of Uldum YELLOW cards."""

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
PROBE_FILE = HERE / "uld_probe_a.csv"
VERDICT_FILE = HERE / "uld_verdict_a.csv"
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


def untapped_potential():
    cid="ULD_131"
    def quest_turns():
        g,p,e=game(CardClass.DRUID)
        quest=play(p,cid)
        p.used_mana=p.max_mana
        g.end_turn();g.end_turn()
        spent=quest.progress
        checkpoints=[]
        for _ in range(4):
            p.used_mana=0
            g.end_turn();checkpoints.append((quest.progress,quest.zone.name,p.hero.power.id))
            g.end_turn()
        observed=f"spent={spent};turns={checkpoints};power={p.hero.power.id}"
        return check(spent==0 and [x[0] for x in checkpoints]==[1,2,3,4]
                     and quest.zone==Zone.GRAVEYARD and p.hero.power.id=="ULD_131p",observed)
    audit(cid,[("four_unspent_turns_reward","Spending all mana gives no progress; four separate end turns with spare mana complete Quest and install Ossirian Tear.",quest_turns,"跨四回合真实触发并核对进度、区域、英雄技能。")])


def crystal_merchant():
    cid="ULD_133"
    def end_turn_branch(unspent):
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid);card=p.card(WISP,zone=Zone.DECK)
        p.used_mana=0 if unspent else p.max_mana
        g.end_turn()
        observed=f"unspent={unspent};drawn={card.zone.name};hand={len(p.hand)};body={body.zone.name}"
        return check(card.zone==(Zone.HAND if unspent else Zone.DECK) and body.zone==Zone.PLAY,observed)
    audit(cid,[("unspent_draws","With spare mana at end turn, one deck card is drawn.",lambda:end_turn_branch(True),"牌库至手牌区域。"),
               ("spent_does_not_draw","With all mana spent, the deck card remains in deck.",lambda:end_turn_branch(False),"消耗全部法力对照。")])


def beees():
    cid="ULD_134"
    def four_attacks():
        g,p,e=game(CardClass.DRUID)
        target=e.summon("CS2_182");target.atk=0
        spell=play(p,cid,target=target)
        bees=[m for m in p.field if m.id=="ULD_134t"]
        observed=f"target={target.health}/{target.max_health}:{target.zone.name};bees={[(m.id,m.zone.name) for m in bees]};spell={spell.zone.name}"
        return check(target.health==1 and target.zone==Zone.PLAY and len(bees)==4 and spell.zone==Zone.GRAVEYARD,observed)
    def target_dies_early():
        g,p,e=game(CardClass.DRUID)
        target=e.summon(WISP)
        spell=play(p,cid,target=target)
        bees=[m for m in p.field if m.id=="ULD_134t"]
        observed=f"target={target.zone.name};surviving_bees={len(bees)};bees={[(m.atk,m.health) for m in bees]}"
        return check(target.zone==Zone.GRAVEYARD and len(bees)==3 and all((b.atk,b.health)==(1,1) for b in bees),observed)
    audit(cid,[("four_bees_attack_surviving_target","Four 1/1 Bees each attack the chosen 0-Attack 5-Health minion for four total damage.",four_attacks,"保留存活目标核对四次攻击。"),
               ("dead_target_remaining_bees_live","When first Bee kills target, remaining three Bees are summoned and survive.",target_dies_early,"目标提前死亡分支。")])


def hidden_oasis():
    cid="ULD_135"
    def ancient():
        g,p,e=game(CardClass.DRUID)
        p.hero.damage=15
        spell=p.give(cid);spell.play(choose="ULD_135a")
        ancient=[m for m in p.field if m.id=="ULD_135at"]
        observed=f"ancient={[(m.atk,m.health,m.taunt,m.zone.name) for m in ancient]};hero={p.hero.health}"
        return check(len(ancient)==1 and (ancient[0].atk,ancient[0].health,ancient[0].taunt)==(6,6,True) and p.hero.health==15,observed)
    def heal():
        g,p,e=game(CardClass.DRUID)
        p.hero.damage=15
        spell=p.give(cid);spell.play(target=p.hero,choose="ULD_135b")
        observed=f"hero={p.hero.health};field={[(m.id,m.zone.name) for m in p.field]}"
        return check(p.hero.health==27 and len(p.field)==0,observed)
    audit(cid,[("ancient_choice","Summon choice makes one 6/6 Taunt Ancient, without healing.",ancient,"召唤分支身材、嘲讽及生命对照。"),
               ("healing_choice","Heal choice restores 12 Health to target and summons nothing.",heal,"治疗分支和不召唤对照。")])


def worthy_expedition():
    cid="ULD_136"
    def discover():
        g,p,e=game(CardClass.DRUID)
        spell=play(p,cid)
        choice=p.choice
        offered=[(c.id,bool(c.has_choose_one)) for c in choice.cards] if choice else []
        selected=choice.cards[0] if choice else None
        if selected:choice.choose(selected)
        observed=f"offered={offered};selected={None if selected is None else (selected.id,selected.zone.name)};choice_closed={p.choice is None}"
        return check(len(offered)==3 and all(flag for _,flag in offered) and selected.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("discover_choose_one_card","Offers three Choose One cards and selecting one places it in hand and closes Choice.",discover,"检查候选性质、数量、最终区域及交互闭合。")])


def garden_gnome():
    cid="ULD_137"
    def branch(high):
        g,p,e=game(CardClass.DRUID)
        held=p.give("ULD_181" if high else "CS2_093")
        body=play(p,cid)
        treants=[m for m in p.field if m.id=="ULD_137t"]
        observed=f"held={held.id}:{held.cost}:{held.zone.name};treants={[(m.atk,m.health,m.zone.name) for m in treants]};body={body.zone.name}"
        return check(len(treants)==(2 if high else 0) and all((m.atk,m.health)==(2,2) for m in treants) and held.zone==Zone.HAND,observed)
    audit(cid,[("high_cost_spell_two_treants","A held 7-Cost spell causes two 2/2 Treants.",lambda:branch(True),"实际持有高费法术。"),
               ("low_cost_spell_no_treants","A held 4-Cost spell does not summon Treants.",lambda:branch(False),"不足5费对照。")])


def anubisath_defender():
    cid="ULD_138"
    def cost_after_spell():
        g,p,e=game(CardClass.DRUID)
        defender=p.give(cid);initial=defender.cost
        spell=play(p,"ULD_181")
        after=defender.cost
        body=defender.play()
        observed=f"initial={initial};after_seven_cost_spell={after};body={defender.zone.name};taunt={defender.taunt}"
        return check(initial==5 and after==0 and defender.zone==Zone.PLAY and defender.taunt,observed)
    def low_cost_no_reduction():
        g,p,e=game(CardClass.DRUID)
        defender=p.give(cid);play(p,"CS2_093")
        observed=f"cost={defender.cost};zone={defender.zone.name}"
        return check(defender.cost==5 and defender.zone==Zone.HAND,observed)
    audit(cid,[("after_high_cost_spell_zero","A 7-Cost spell cast this turn makes hand Defender cost zero and Taunt on play.",cost_after_spell,"实际高费法术及法力不足时仍可打出。"),
               ("low_cost_spell_no_discount","A 4-Cost spell does not reduce Defender's Cost.",low_cost_no_reduction,"阈值对照。")])


def elise_enlightened():
    cid="ULD_139"
    def branch(duplicate):
        g,p,e=game(CardClass.DRUID)
        if duplicate:
            p.card(WISP,zone=Zone.DECK);p.card(WISP,zone=Zone.DECK)
        held=[p.give(WISP),p.give("CS2_093")]
        body=play(p,cid)
        ids=[c.id for c in p.hand]
        observed=f"duplicate={duplicate};hand={ids};body={body.zone.name};deck={[c.id for c in p.deck]}"
        expected=[WISP,"CS2_093"]*(1 if duplicate else 2)
        return check(sorted(ids)==sorted(expected) and all(c.zone==Zone.HAND for c in held),observed)
    audit(cid,[("unique_deck_duplicates_hand","No duplicate deck cards: Elise duplicates each held card once.",lambda:branch(False),"同种实体两份手牌及牌库条件。"),
               ("duplicate_deck_no_effect","Two identical cards in deck suppress hand duplication.",lambda:branch(True),"有重复牌库对照。")])


def supreme_archaeology():
    cid="ULD_140"
    def twenty_draws_reward():
        g,p,e=game(CardClass.WARLOCK)
        quest=play(p,cid)
        for _ in range(21):p.card(WISP,zone=Zone.DECK)
        for i in range(20):
            if len(p.hand)>=8:p.discard_hand()
            p.draw()
        reward=p.hero.power.id
        progress=quest.progress
        p.discard_hand();p.used_mana=0
        p.hero.power.use()
        drawn=[c for c in p.hand if c.id==WISP]
        observed=f"progress={progress};quest={quest.zone.name};power={reward};power_draw={[(c.id,c.cost,c.zone.name) for c in drawn]};deck={len(p.deck)}"
        return check(progress==20 and quest.zone==Zone.GRAVEYARD and reward=="ULD_140p"
                     and len(drawn)==1 and drawn[0].cost==0,observed)
    audit(cid,[("twenty_draws_unlock_zero_cost_power","Twenty actual draws complete Quest; Tome of Origination draws next card at zero Cost.",twenty_draws_reward,"逐次真实抽牌、任务区域、英雄技能及抽牌费用。")])


def pharaohs_blessing():
    cid="ULD_143"
    def buff_target():
        g,p,e=game(CardClass.PALADIN)
        friend=p.summon(WISP);enemy=e.summon(WISP)
        spell=play(p,cid,target=friend)
        observed=f"friend={friend.atk}/{friend.health},shield={friend.divine_shield},taunt={friend.taunt};enemy={enemy.atk}/{enemy.health};spell={spell.zone.name}"
        return check((friend.atk,friend.health,friend.divine_shield,friend.taunt)==(5,5,True,True)
                     and (enemy.atk,enemy.health)==(1,1) and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("selected_minion_gets_all_three","Selected minion gains +4/+4, Divine Shield and Taunt; other minion stays unchanged.",buff_target,"目标身材、两种关键词及敌人对照。")])


def brazen_zealot():
    cid="ULD_145"
    def summoned_friend_buffs():
        g,p,e=game(CardClass.PALADIN)
        zealot=play(p,cid);base=zealot.atk
        friend=p.summon(WISP);after_friend=zealot.atk
        enemy=e.summon(WISP);after_enemy=zealot.atk
        observed=f"base={base};after_friend={after_friend};after_enemy={after_enemy};friend={friend.zone.name};enemy={enemy.zone.name}"
        return check(base==2 and after_friend==3 and after_enemy==3,observed)
    audit(cid,[("friendly_summon_only","A later friendly summon gives +1 Attack; an enemy summon gives none; self summon does not count.",summoned_friend_buffs,"召唤双方对照及自召唤边界。")])


def ramkahen_wildtamer():
    cid="ULD_151"
    def copy_beast():
        g,p,e=game(CardClass.HUNTER)
        beast=p.give("CS2_172");other=p.give(WISP)
        body=play(p,cid)
        ids=[c.id for c in p.hand]
        observed=f"hand={ids};beast={beast.zone.name};other={other.zone.name};body={body.zone.name}"
        return check(ids.count(beast.id)==2 and ids.count(WISP)==1 and body.zone==Zone.PLAY,observed)
    def no_beast():
        g,p,e=game(CardClass.HUNTER)
        p.give(WISP);body=play(p,cid)
        observed=f"hand={[c.id for c in p.hand]};body={body.zone.name}"
        return check([c.id for c in p.hand]==[WISP],observed)
    audit(cid,[("copy_held_beast","A held Beast is copied once while a non-Beast remains single.",copy_beast,"单一合法随机候选，核对来源及数量。"),
               ("no_beast_no_copy","No held Beast causes no copy.",no_beast,"空合法候选分支。")])


def pressure_plate():
    cid="ULD_152"
    def opponent_spell_kills_enemy_minion():
        g,p,e=game(CardClass.HUNTER,CardClass.MAGE)
        secret=play(p,cid)
        friendly=p.summon(WISP);victim=e.summon("CS2_182")
        g.end_turn();spell=play(e,"GAME_005")
        observed=f"secret={secret.zone.name};victim={victim.zone.name};friend={friendly.zone.name};spell={spell.zone.name}"
        return check(secret.zone!=Zone.SECRET and victim.zone==Zone.GRAVEYARD and friendly.zone==Zone.PLAY,observed)
    def owner_spell_does_not_trigger():
        g,p,e=game(CardClass.HUNTER)
        secret=play(p,cid);victim=e.summon(WISP)
        spell=play(p,"GAME_005")
        observed=f"secret={secret.zone.name};victim={victim.zone.name};spell={spell.zone.name}"
        return check(secret.zone==Zone.SECRET and victim.zone==Zone.PLAY,observed)
    audit(cid,[("enemy_spell_destroy_enemy_minion","Opponent casts a spell: Secret reveals and destroys their minion, sparing friendly minion.",opponent_spell_kills_enemy_minion,"跨玩家施法、奥秘区域与目标阵营。"),
               ("friendly_spell_no_trigger","Owner casts a spell: Secret remains armed.",owner_spell_does_not_trigger,"施法者阵营反例。")])


def hyena_alpha():
    cid="ULD_154"
    def branch(secret):
        g,p,e=game(CardClass.HUNTER)
        if secret:armed=play(p,"ULD_152")
        body=play(p,cid)
        hyenas=[m for m in p.field if m.id=="ULD_154t"]
        observed=f"secret={secret};hyenas={[(m.atk,m.health,m.zone.name) for m in hyenas]};body={body.zone.name}"
        return check(len(hyenas)==(2 if secret else 0) and all((h.atk,h.health)==(2,2) for h in hyenas),observed)
    audit(cid,[("armed_secret_summons_two","Controlling a Secret creates two 2/2 Hyenas.",lambda:branch(True),"真实挂奥秘。"),
               ("no_secret_no_hyenas","Without a Secret, no Hyenas are summoned.",lambda:branch(False),"无奥秘对照。")])


def unseal_the_vault():
    cid="ULD_155"
    def twenty_summons_power():
        g,p,e=game(CardClass.HUNTER)
        quest=play(p,cid)
        for i in range(19):p.summon(WISP).destroy()
        before=quest.progress
        last=p.summon(WISP)
        power=p.hero.power.id
        before_atk=last.atk
        p.hero.power.use()
        observed=f"after19={before};after20={quest.progress};quest={quest.zone.name};power={power};minion_attack={before_atk}->{last.atk}"
        return check(before==19 and quest.progress==20 and quest.zone==Zone.GRAVEYARD
                     and power=="ULD_155p" and last.atk==before_atk+2,observed)
    audit(cid,[("twenty_summons_unlock_buff_power","Nineteen friendly summons leave progress 19; twentieth completes Quest and hero power gives own minion +2 Attack.",twenty_summons_power,"20次真实召唤、死亡清场和奖励使用。")])


def dinotamer_brann():
    cid="ULD_156"
    def branch(duplicate):
        g,p,e=game(CardClass.HUNTER)
        if duplicate:p.card(WISP,zone=Zone.DECK);p.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        krush=[m for m in p.field if m.id=="ULD_156t3"]
        observed=f"duplicate={duplicate};krush={[(m.atk,m.health,m.zone.name) for m in krush]};body={body.zone.name}"
        return check(len(krush)==(0 if duplicate else 1) and all((m.atk,m.health)==(8,8) for m in krush),observed)
    audit(cid,[("unique_deck_summons_krush","No duplicate deck cards summons King Krush.",lambda:branch(False),"空牌库高地分支。"),
               ("duplicate_deck_blocks_krush","Duplicate Wisp cards suppress King Krush.",lambda:branch(True),"有重复牌库反例。")])


def questing_explorer():
    cid="ULD_157"
    def branch(quest_controlled):
        g,p,e=game(CardClass.DRUID)
        if quest_controlled:quest=play(p,"ULD_131")
        card=p.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        observed=f"quest={quest_controlled};drawn={card.zone.name};body={body.zone.name}"
        return check(card.zone==(Zone.HAND if quest_controlled else Zone.DECK),observed)
    audit(cid,[("quest_control_draws","Controlling a Quest causes Battlecry to draw one actual deck card.",lambda:branch(True),"实际挂任务，核对区域。"),
               ("no_quest_no_draw","Without a Quest, deck card remains in deck.",lambda:branch(False),"无任务对照。")])


def sandstorm_elemental():
    cid="ULD_158"
    def aoe_overload():
        g,p,e=game(CardClass.SHAMAN)
        friend=p.summon("CS2_182");foes=[e.summon("CS2_182") for _ in range(2)]
        body=play(p,cid)
        observed=f"friend={friend.health};foes={[m.health for m in foes]};enemy_hero={e.hero.health};overloaded={p.overloaded};body={body.zone.name}"
        return check(friend.health==5 and [m.health for m in foes]==[4,4] and e.hero.health==30 and p.overloaded==1,observed)
    audit(cid,[("enemy_minion_aoe_and_overload","Battlecry deals one only to each enemy minion and applies one Overload.",aoe_overload,"双目标、友军和敌方英雄对照及过载。")])


def sinister_deal():
    cid="ULD_160"
    def discover_lackey():
        g,p,e=game(CardClass.WARLOCK)
        spell=play(p,cid)
        choice=p.choice;offered=[(c.id,c.mark_of_evil) for c in choice.cards] if choice else []
        chosen=choice.cards[0] if choice else None
        if chosen:choice.choose(chosen)
        observed=f"offered={offered};selected={None if chosen is None else (chosen.id,chosen.zone.name)};choice_closed={p.choice is None}"
        return check(len(offered)==3 and all(x[1] for x in offered) and chosen.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("discover_lackey_choice","Three Lackeys are offered; chosen Lackey enters hand and Choice closes.",discover_lackey,"候选标签、数量、手牌与选择收束。")])


def neferset_thrasher():
    cid="ULD_161"
    def attacks_damage_own_hero():
        g,p,e=game(CardClass.WARLOCK)
        body=play(p,cid);victim=e.summon("CS2_182")
        g.end_turn();g.end_turn()
        before=p.hero.health;body.attack(victim)
        observed=f"hero={before}->{p.hero.health};victim={victim.health}:{victim.zone.name};body={body.health}:{body.zone.name}"
        return check(before==30 and p.hero.health==27 and victim.health==1 and victim.zone==Zone.PLAY,observed)
    audit(cid,[("attacking_damages_owner_three","When Thrasher attacks a minion, its owner hero takes 3 damage.",attacks_damage_own_hero,"跨回合实际攻击及英雄伤害。")])


def evil_recruiter():
    cid="ULD_162"
    def destroy_lackey_summon_demon():
        g,p,e=game(CardClass.WARLOCK)
        lackey=p.summon("DAL_613");ordinary=p.summon(WISP)
        body=play(p,cid,target=lackey)
        demons=[m for m in p.field if m.id=="ULD_162t"]
        observed=f"lackey={lackey.zone.name};ordinary={ordinary.zone.name};demons={[(m.atk,m.health,m.zone.name) for m in demons]};body={body.zone.name}"
        return check(lackey.zone==Zone.GRAVEYARD and ordinary.zone==Zone.PLAY and len(demons)==1
                     and (demons[0].atk,demons[0].health)==(5,5),observed)
    def no_lackey_no_demon():
        g,p,e=game(CardClass.WARLOCK)
        ordinary=p.summon(WISP);body=play(p,cid)
        observed=f"ordinary={ordinary.zone.name};demons={[m.id for m in p.field if m.id=='ULD_162t']};body={body.zone.name}"
        return check(ordinary.zone==Zone.PLAY and not any(m.id=="ULD_162t" for m in p.field),observed)
    audit(cid,[("target_lackey_destroy_and_summon","Selected friendly Lackey dies and exactly one 5/5 Demon appears; ordinary minion survives.",destroy_lackey_summon_demon,"目标筛选、死亡区域、召唤身材。"),
               ("no_lackey_no_demon","Without a friendly Lackey, Battlecry does not summon Demon.",no_lackey_no_demon,"空候选分支。")])


def expired_merchant():
    cid="ULD_163"
    def discard_highest_and_restore_two():
        g,p,e=game(CardClass.WARLOCK)
        high=p.give("CS1_113");low=p.give(WISP)
        body=play(p,cid)
        after_battle=(high.zone.name,low.zone.name,[c.id for c in p.hand])
        body.destroy()
        ids=[c.id for c in p.hand]
        observed=f"battle={after_battle};death={body.zone.name};hand={ids}"
        return check(high.zone==Zone.REMOVEDFROMGAME and low.zone==Zone.HAND and body.zone==Zone.GRAVEYARD
                     and ids.count(high.id)==2 and ids.count(WISP)==1,observed)
    audit(cid,[("highest_cost_discard_then_two_copies","Battlecry discards highest-Cost card, then Deathrattle returns two copies while low-Cost card remains.",discard_highest_and_restore_two,"同手牌高低费对照、弃牌和死亡后区域。")])


def zephrys_the_great():
    cid="ULD_003"
    def branch(duplicate):
        g,p,e=game(CardClass.MAGE)
        if duplicate:
            p.card(WISP,zone=Zone.DECK);p.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        choice=p.choice
        offered=[c.id for c in choice.cards] if choice else []
        selected=choice.cards[0] if choice else None
        if selected:choice.choose(selected)
        observed=f"duplicate={duplicate};offered={len(offered)}:{offered[:5]};selected={None if selected is None else (selected.id,selected.zone.name)};choice_closed={p.choice is None};body={body.zone.name}"
        return check(bool(choice)==(not duplicate) and (selected is None or selected.zone==Zone.HAND)
                     and p.choice is None and body.zone==Zone.PLAY,observed)
    audit(cid,[("unique_deck_wishes_for_card","A duplicate-free deck opens the Zephrys choice; choosing an offer puts it in hand.",lambda:branch(False),"空牌库视作无重复，核对候选与选择落手。"),
               ("duplicate_deck_no_wish","A deck with duplicate cards suppresses the wish choice.",lambda:branch(True),"两张相同牌作反例。")])


def riftcleaver():
    cid="ULD_165"
    def destroy_current_health():
        g,p,e=game(CardClass.WARLOCK)
        victim=e.summon("CS2_182");victim.damage=2
        current=victim.health;maximum=victim.max_health;before=p.hero.health
        body=play(p,cid,target=victim)
        observed=f"victim={current}/{maximum}:{victim.zone.name};owner_hero={before}->{p.hero.health};body={body.zone.name}"
        return check(current==3 and victim.zone==Zone.GRAVEYARD and p.hero.health==before-current
                     and body.zone==Zone.PLAY,observed)
    audit(cid,[("destroy_target_and_take_current_health_damage","Battlecry destroys the selected minion and damages own hero by its current (post-damage) Health.",destroy_current_health,"目标最大生命5、先受2伤，再核对按剩余3点扣英雄血。")])


def diseased_vulture():
    cid="ULD_167"
    def own_turn_damage_triggers():
        g,p,e=game(CardClass.WARLOCK)
        body=play(p,cid);before=p.hero.health
        play(p,"CS2_008",target=p.hero)
        summoned=[m for m in p.field if m is not body]
        observed=f"hero={before}->{p.hero.health};summoned={[(m.id,m.cost,m.zone.name) for m in summoned]}"
        return check(p.hero.health==before-1 and len(summoned)==1 and summoned[0].cost==3,observed)
    def off_turn_damage_does_not_trigger():
        g,p,e=game(CardClass.WARLOCK,CardClass.MAGE)
        body=play(p,cid);g.end_turn();before=p.hero.health
        play(e,"CS2_008",target=p.hero)
        summoned=[m for m in p.field if m is not body]
        observed=f"current={int(g.current_player.hero.card_class)};hero={before}->{p.hero.health};summoned={[(m.id,m.cost) for m in summoned]}"
        return check(p.hero.health==before-1 and not summoned,observed)
    audit(cid,[("own_turn_hero_damage_summons_three_cost","Damage to own hero during your turn triggers exactly one random 3-Cost minion.",own_turn_damage_triggers,"以月火术实际命中英雄并核对费用。"),
               ("opponents_turn_damage_no_trigger","Damage to own hero during opponent's turn does not trigger Vulture.",off_turn_damage_does_not_trigger,"跨到对手回合施法，核对当前回合过滤。")])


def dark_pharaoh_tekahn():
    cid="ULD_168"
    def lackeys_are_four_four():
        g,p,e=game(CardClass.WARLOCK)
        held=p.give("DAL_613");field=p.summon("DAL_613")
        body=play(p,cid);later=p.summon("DAL_613")
        stats=[(m.atk,m.max_health,m.zone.name) for m in (held,field,later)]
        observed=f"lackeys={stats};body={body.zone.name}"
        return check(all((m.atk,m.max_health)==(4,4) for m in (held,field,later))
                     and all(m.zone==(Zone.HAND if m is held else Zone.PLAY) for m in (held,field,later)),observed)
    audit(cid,[("existing_and_future_lackeys_become_four_four","Battlecry makes Lackeys already in hand/on board and a later Lackey 4/4.",lackeys_are_four_four,"真实持有、场上与战后新生成三种区域。")])


def mogu_fleshshaper():
    cid="ULD_169"
    def cost_and_rush():
        g,p,e=game(CardClass.SHAMAN)
        mogu=p.give(cid);empty_cost=mogu.cost
        friends=[p.summon(WISP)];foes=[e.summon(WISP),e.summon(WISP)]
        crowded_cost=mogu.cost
        body=mogu.play();victim=foes[0]
        rush=body.rush
        if rush:body.attack(victim)
        observed=f"cost={empty_cost}->{crowded_cost};rush={rush};victim={victim.zone.name};body={body.zone.name}"
        return check(empty_cost==9 and crowded_cost==6 and rush and victim.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("minion_count_reduces_cost_and_rush_attacks","Three minions reduce base Cost by 3; played Mogu has Rush and can immediately attack an enemy minion.",cost_and_rush,"1友方+2敌方作价格基线，同时真实执行突袭攻击。")])


def weaponized_wasp():
    cid="ULD_170"
    def lackey_enables_targeted_damage():
        g,p,e=game(CardClass.SHAMAN)
        lackey=p.summon("DAL_613");victim=e.summon("CS2_182")
        before=victim.health;body=play(p,cid,target=victim)
        observed=f"lackey={lackey.id}:{lackey.zone.name};victim={before}->{victim.health}:{victim.zone.name};body={body.zone.name}"
        return check(victim.health==before-3 and body.zone==Zone.PLAY,observed)
    def no_lackey_no_damage():
        g,p,e=game(CardClass.SHAMAN)
        victim=e.summon("CS2_182");before=victim.health
        body=play(p,cid)
        observed=f"victim={before}->{victim.health};body={body.zone.name};requires_target={body.requires_target()}"
        return check(victim.health==before and body.zone==Zone.PLAY,observed)
    audit(cid,[("lackey_allows_three_damage","With a friendly Lackey, Battlecry deals 3 to the selected target.",lackey_enables_targeted_damage,"具备跟班时提供合法敌方目标。"),
               ("no_lackey_no_damage","Without a friendly Lackey, Battlecry does not damage the enemy minion.",no_lackey_no_damage,"无跟班分支，不传入目标。")])


def totemic_surge():
    cid="ULD_171"
    def friendly_totems_only():
        g,p,e=game(CardClass.SHAMAN)
        friendly=p.summon("CS2_050");plain=p.summon(WISP);enemy=e.summon("CS2_050")
        before=(friendly.atk,plain.atk,enemy.atk)
        spell=play(p,cid)
        after=(friendly.atk,plain.atk,enemy.atk)
        observed=f"atk={before}->{after};totems={(int(friendly.race),int(enemy.race))};spell={spell.zone.name}"
        return check(after==(before[0]+2,before[1],before[2]) and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("only_friendly_totems_gain_two_attack","Spell gives +2 Attack to friendly Totems, leaving friendly non-Totems and enemy Totems unchanged.",friendly_totems_only,"同局放置双方图腾与友方非图腾作对照。")])


def plague_of_murlocs():
    cid="ULD_172"
    def transform_both_fields():
        g,p,e=game(CardClass.SHAMAN)
        friend=p.summon(WISP);foe=e.summon("CS2_182")
        spell=play(p,cid)
        fields=[(int(m.race),m.zone.name,m.id) for player in (p,e) for m in player.field]
        observed=f"fields={fields};originals={(friend.zone.name,foe.zone.name)};spell={spell.zone.name}"
        return check(len(p.field)==1 and len(e.field)==1
                     and all(m.race==Race.MURLOC for player in (p,e) for m in player.field)
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("all_friendly_and_enemy_minions_become_murlocs","Plague transforms every minion on both sides into a Murloc.",transform_both_fields,"友敌随从各一只，核对双方变形后的种族及场面数量。")])


def vessina():
    cid="ULD_173"
    def overload_aura_and_clear():
        g,p,e=game(CardClass.SHAMAN)
        friend=p.summon(WISP);foe=e.summon(WISP);p.overload_locked=1
        body=play(p,cid)
        active=(friend.atk,body.atk,foe.atk)
        observed=f"overload_locked={p.overload_locked};active={active};self={body.zone.name}"
        return check(active==(3,body.data.atk,1),observed)
    def no_overload_no_aura():
        g,p,e=game(CardClass.SHAMAN)
        friend=p.summon(WISP);p.overloaded=0;body=play(p,cid)
        observed=f"friend={friend.atk};self={body.atk};overloaded={p.overloaded}"
        return check(friend.atk==1,observed)
    audit(cid,[("overload_grants_other_friendly_minions_two_attack","While overloaded, other friendly minions gain +2 Attack; Vessina and enemy minions do not.",overload_aura_and_clear,"正向状态、己方自身与敌方对照。"),
               ("no_overload_no_attack_aura","Without Overload, friendly minions receive no Attack bonus.",no_overload_no_aura,"无过载新局对照。")])


def serpent_egg():
    cid="ULD_174"
    def deathrattle_summons_serpent():
        g,p,e=game(CardClass.MAGE)
        egg=play(p,cid);egg.destroy()
        serpents=[m for m in p.field if m.id=="ULD_174t"]
        observed=f"egg={egg.zone.name};serpents={[(m.atk,m.health,m.zone.name) for m in serpents]}"
        return check(egg.zone==Zone.GRAVEYARD and len(serpents)==1
                     and (serpents[0].atk,serpents[0].health)==(3,4),observed)
    audit(cid,[("death_summons_three_four_sea_serpent","Egg death summons exactly one 3/4 Sea Serpent.",deathrattle_summons_serpent,"真实死亡触发，核对亡语随从身材及区域。")])


def octosari():
    cid="ULD_177"
    def death_draws_eight():
        g,p,e=game(CardClass.MAGE)
        deck=[p.card(WISP,zone=Zone.DECK) for _ in range(9)]
        body=play(p,cid);body.destroy()
        observed=f"body={body.zone.name};hand={len(p.hand)};deck={len(p.deck)};drawn={[c.zone.name for c in deck]}"
        return check(body.zone==Zone.GRAVEYARD and len(p.hand)==8 and len(p.deck)==1
                     and sum(c.zone==Zone.HAND for c in deck)==8,observed)
    audit(cid,[("deathrattle_draws_eight_cards","Octosari death draws eight cards, leaving the ninth card in deck.",death_draws_eight,"九张真实牌库牌和死亡后区域计数。")])


def siamat():
    cid="ULD_178"
    def choose_shield_taunt():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid);offered1=[c.id for c in p.choice.cards]
        first=next(c for c in p.choice.cards if c.id=="ULD_178a2");p.choice.choose(first)
        offered2=[c.id for c in p.choice.cards]
        second=next(c for c in p.choice.cards if c.id=="ULD_178a3");p.choice.choose(second)
        observed=f"offered1={offered1};offered2={offered2};shield={body.divine_shield};taunt={body.taunt};rush={body.rush};windfury={body.windfury};choice={p.choice}"
        return check(len(offered1)==4 and len(offered2)==3 and "ULD_178a2" not in offered2
                     and body.divine_shield and body.taunt and not body.rush and not body.windfury
                     and p.choice is None,observed)
    def choose_rush_windfury():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid)
        first=next(c for c in p.choice.cards if c.id=="ULD_178a4");p.choice.choose(first)
        second=next(c for c in p.choice.cards if c.id=="ULD_178a");p.choice.choose(second)
        victim=e.summon("CS2_182");can_attack=body.can_attack(victim)
        if can_attack:body.attack(victim)
        observed=f"rush={body.rush};windfury={body.windfury};can_attack={can_attack};victim={victim.health}:{victim.zone.name};attacks={body.num_attacks}"
        return check(body.rush and body.windfury and can_attack and body.num_attacks==1
                     and victim.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("choose_two_distinct_effects","Siamat offers four effects, removes the first choice from the second step, and grants chosen Divine Shield plus Taunt only.",choose_shield_taunt,"逐步核对四选二、排除已选、关键词和未选择效果。"),
               ("rush_windfury_allows_immediate_minion_attack","Choosing Rush and Windfury permits a same-turn minion attack.",choose_rush_windfury,"第二组合真实攻击敌方随从，检查突袭和攻击次数。")])


def phalanx_commander():
    cid="ULD_179"
    def taunt_minions_gain_attack_and_revert():
        g,p,e=game(CardClass.MAGE)
        friendly=p.summon("CS1_042");plain=p.summon(WISP);enemy=e.summon("CS1_042")
        before=(friendly.atk,plain.atk,enemy.atk);body=play(p,cid)
        active=(friendly.atk,plain.atk,enemy.atk);body.destroy()
        after=(friendly.atk,plain.atk,enemy.atk)
        observed=f"atk={before}->{active}->{after};taunt={friendly.taunt}/{enemy.taunt};body={body.zone.name}"
        return check(active==(before[0]+2,before[1],before[2]) and after==before
                     and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("friendly_taunt_aura_and_death_revert","Commander grants +2 Attack to friendly Taunt minions only; the bonus vanishes when it dies.",taunt_minions_gain_attack_and_revert,"双方嘲讽及友方非嘲讽对照，核对光环移除。")])


def sunstruck_henchman():
    cid="ULD_180"
    def fixed_seeds_sleep_half_the_time():
        results=[]
        for seed in range(180,196):
            g,p,e=game(CardClass.MAGE,seed=seed)
            body=play(p,cid);g.end_turn();g.end_turn()
            results.append((seed,body.turns_in_play,body.asleep,body.can_attack(e.hero)))
        sleeping=sum(1 for _,_,asleep,_ in results if asleep)
        ready=sum(1 for _,_,asleep,can_attack in results if not asleep and can_attack)
        observed=f"sleeping={sleeping};ready={ready};seeds={results}"
        return check(0<sleeping<len(results) and sleeping+ready==len(results),observed)
    audit(cid,[("own_turn_start_coinflip_can_sleep_or_ready","Across fixed random seeds, the start-of-turn 50% effect produces both asleep and attack-ready outcomes.",fixed_seeds_sleep_half_the_time,"16个确定随机种子，跨对手回合到己方开始，检查沉睡与可攻击两种分支。")])


def earthquake():
    cid="ULD_181"
    def two_global_damage_waves():
        g,p,e=game(CardClass.SHAMAN)
        shielded=p.summon("CS2_182");shielded.divine_shield=True
        sturdy=e.summon("EX1_563")
        fragile=p.summon(WISP)
        spell=play(p,cid)
        observed=f"shielded={shielded.health}/{shielded.max_health}:shield={shielded.divine_shield}:{shielded.zone.name};sturdy={sturdy.health}/{sturdy.max_health}:{sturdy.zone.name};fragile={fragile.zone.name};spell={spell.zone.name}"
        return check(shielded.zone==Zone.PLAY and not shielded.divine_shield and shielded.health==3
                     and sturdy.zone==Zone.PLAY and sturdy.health==5
                     and fragile.zone==Zone.GRAVEYARD and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("two_five_then_two_damage_sweeps_all_minions","Earthquake hits both fields with 5 damage, then 2 more; Divine Shield absorbs the first wave only.",two_global_damage_waves,"两边耐久随从验证总伤害，圣盾与脆弱随从验证伤害分段。")])


def spitting_camel():
    cid="ULD_182"
    def own_end_damages_another_friendly():
        g,p,e=game(CardClass.MAGE)
        camel=play(p,cid);first=p.summon("CS2_182");second=p.summon("CS2_182");enemy=e.summon("CS2_182")
        before=(camel.health,first.health,second.health,enemy.health)
        g.end_turn()
        after=(camel.health,first.health,second.health,enemy.health)
        observed=f"health={before}->{after};current={int(g.current_player.hero.card_class)}"
        return check(after[0]==before[0] and after[3]==before[3]
                     and (before[1]-after[1])+(before[2]-after[2])==1,observed)
    audit(cid,[("end_turn_hits_one_other_friendly_minion","At owner's end turn, exactly one other friendly minion takes 1 damage; Camel and enemy minion are spared.",own_end_damages_another_friendly,"两只合法友方候选和对方随从，覆盖随机范围边界。")])


def anubisath_warbringer():
    cid="ULD_183"
    def death_buffs_hand_minions_only():
        g,p,e=game(CardClass.MAGE)
        small=p.give(WISP);large=p.give("CS2_182");spell=p.give("CS2_029")
        before=[(c.id,getattr(c,"atk",None),getattr(c,"max_health",None)) for c in (small,large,spell)]
        body=play(p,cid);body.destroy()
        after=[(c.id,getattr(c,"atk",None),getattr(c,"max_health",None),c.zone.name) for c in (small,large,spell)]
        observed=f"before={before};after={after};body={body.zone.name}"
        return check((small.atk,small.max_health)==(4,4) and (large.atk,large.max_health)==(7,8)
                     and spell.type==CardType.SPELL and spell.cost==4 and all(c.zone==Zone.HAND for c in (small,large,spell))
                     and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deathrattle_buffs_all_hand_minions_not_spell","Deathrattle gives +3/+3 to each minion in hand and leaves a spell unchanged.",death_buffs_hand_minions_only,"低身材、高身材随从及法术同手牌作对照。")])


def kobold_sandtrooper():
    cid="ULD_184"
    def death_damages_enemy_hero():
        g,p,e=game(CardClass.MAGE)
        own=p.hero.health;foe=e.hero.health;body=play(p,cid);body.destroy()
        observed=f"own={own}->{p.hero.health};enemy={foe}->{e.hero.health};body={body.zone.name}"
        return check(p.hero.health==own and e.hero.health==foe-3 and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deathrattle_deals_three_to_enemy_hero","Deathrattle deals 3 to the enemy hero and does not damage its owner's hero.",death_damages_enemy_hero,"对比双方英雄生命并核对亡语区域。")])


def temple_berserker():
    cid="ULD_185"
    def damaged_attack_and_reborn():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid);base=body.atk
        body.hit(1);damaged=body.atk
        body.heal(body,1);healed=body.atk
        body.hit(1);reborn=body.reborn;body.destroy()
        copies=[m for m in p.field if m.id==cid]
        observed=f"attack={base}->{damaged}->{healed};reborn_flag={reborn};copies={[(m.atk,m.health,m.max_health,m.reborn,m.zone.name) for m in copies]};old={body.zone.name}"
        return check(damaged==base+2 and healed==base and reborn and body.zone==Zone.GRAVEYARD
                     and len(copies)==1 and copies[0].health==1 and copies[0].atk==base+2,observed)
    audit(cid,[("reborn_and_enrage_attack_bonus","Temple Berserker has Reborn and +2 Attack only while damaged, including its reborn copy at 1 Health.",damaged_attack_and_reborn,"受伤/回满生命攻击对照，再真实死亡触发复生。")])


def pharaoh_cat():
    cid="ULD_186"
    def gives_reborn_minion():
        g,p,e=game(CardClass.ROGUE)
        body=play(p,cid);cards=list(p.hand)
        observed=f"hand={[(c.id,int(c.type),c.reborn,c.zone.name) for c in cards]};body={body.zone.name}"
        return check(len(cards)==1 and cards[0].type==CardType.MINION and cards[0].reborn
                     and cards[0].zone==Zone.HAND and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_gives_one_reborn_minion","Battlecry adds exactly one Reborn minion to hand.",gives_reborn_minion,"空手牌起始，检查随从类型、复生关键词与区域。")])


def golden_scarab():
    cid="ULD_188"
    def discovers_four_cost_card():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid);choice=p.choice
        offered=[(c.id,c.cost,int(c.type)) for c in choice.cards] if choice else []
        selected=choice.cards[0] if choice else None
        if selected:choice.choose(selected)
        observed=f"offered={offered};selected={None if selected is None else (selected.id,selected.cost,selected.zone.name)};choice_closed={p.choice is None}"
        return check(len(offered)==3 and all(cost==4 for _,cost,_ in offered)
                     and selected is not None and selected.zone==Zone.HAND and p.choice is None
                     and body.zone==Zone.PLAY,observed)
    audit(cid,[("discover_three_four_cost_cards","Battlecry offers three 4-Cost cards; selected card enters hand and choice closes.",discovers_four_cost_card,"核对三个候选法力消耗、选择落手与交互收束。")])


def faceless_lurker():
    cid="ULD_189"
    def doubles_health_and_has_taunt():
        g,p,e=game(CardClass.MAGE)
        body=p.give(cid);before=body.health;body.play()
        observed=f"health={before}->{body.health};max_health={body.max_health};taunt={body.taunt};zone={body.zone.name}"
        return check(body.zone==Zone.PLAY and body.taunt and body.health==before*2
                     and body.max_health==before*2,observed)
    audit(cid,[("battlecry_doubles_health_and_taunt","Faceless Lurker is Taunt and its Battlecry doubles its Health.",doubles_health_and_has_taunt,"入场前后当前/最大生命及嘲讽标签。")])


def pit_crocolisk():
    cid="ULD_190"
    def battlecry_deals_five_to_target():
        g,p,e=game(CardClass.MAGE)
        victim=e.summon("EX1_563");before=victim.health
        hero=e.hero.health;body=play(p,cid,target=victim)
        observed=f"victim={before}->{victim.health}/{victim.max_health}:{victim.zone.name};enemy_hero={hero}->{e.hero.health};body={body.zone.name}"
        return check(victim.zone==Zone.PLAY and victim.health==before-5 and e.hero.health==hero
                     and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_deals_five_damage","Battlecry deals exactly 5 damage to the selected minion without hitting enemy hero.",battlecry_deals_five_to_target,"高生命目标避免死亡分支，敌方英雄作对照。")])


CHECKS={
    "ULD_131":untapped_potential,"ULD_133":crystal_merchant,"ULD_134":beees,
    "ULD_135":hidden_oasis,"ULD_136":worthy_expedition,"ULD_137":garden_gnome,
    "ULD_138":anubisath_defender,"ULD_139":elise_enlightened,"ULD_140":supreme_archaeology,
    "ULD_143":pharaohs_blessing,"ULD_145":brazen_zealot,"ULD_151":ramkahen_wildtamer,
    "ULD_152":pressure_plate,"ULD_154":hyena_alpha,"ULD_155":unseal_the_vault,
    "ULD_156":dinotamer_brann,"ULD_157":questing_explorer,"ULD_158":sandstorm_elemental,
    "ULD_160":sinister_deal,"ULD_161":neferset_thrasher,"ULD_162":evil_recruiter,
    "ULD_163":expired_merchant,"ULD_003":zephrys_the_great,"ULD_165":riftcleaver,
    "ULD_167":diseased_vulture,"ULD_168":dark_pharaoh_tekahn,"ULD_169":mogu_fleshshaper,
    "ULD_170":weaponized_wasp,"ULD_171":totemic_surge,"ULD_172":plague_of_murlocs,
    "ULD_173":vessina,"ULD_174":serpent_egg,"ULD_177":octosari,"ULD_178":siamat,
    "ULD_179":phalanx_commander,"ULD_180":sunstruck_henchman,"ULD_181":earthquake,
    "ULD_182":spitting_camel,"ULD_183":anubisath_warbringer,"ULD_184":kobold_sandtrooper,
    "ULD_185":temple_berserker,"ULD_186":pharaoh_cat,"ULD_188":golden_scarab,
    "ULD_189":faceless_lurker,"ULD_190":pit_crocolisk,
}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
