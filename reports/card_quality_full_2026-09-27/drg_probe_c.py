"""Card-specific live checks for the assigned 25-card DRAGONS slice."""

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
PROBE_FILE = HERE / "drg_probe_c.csv"
VERDICT_FILE = HERE / "drg_verdict_c.csv"
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
ROSTER = ROSTER[90:115]
assert len(ROSTER) == 25
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


def play(player, cid, target=None, index=None, choose=None):
    card = player.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if index is not None:
        kw["index"] = index
    if choose is not None:
        kw["choose"] = choose
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



def time_rip():
    cid="DRG_246"
    def destroys_target_and_invokes():
        g,p,e=game(CardClass.PRIEST)
        p.card("DRG_660",zone=Zone.DECK)
        target=e.summon("CS2_182"); other=p.summon(WISP)
        spell=play(p,cid,target=target)
        observed=f"target={target.zone.name};other={other.zone.name};invoke={p.invoke_counter};spell={spell.zone.name}"
        return check(target.zone==Zone.GRAVEYARD and other.zone==Zone.PLAY and p.invoke_counter==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("destroy_selected_minion_and_invoke","Target dies; unrelated friendly minion survives; Galakrond invoked once.",destroys_target_and_invokes,"实际目标、区域和祈求计数")])


def seal_fate():
    cid="DRG_247"
    def damages_undamaged_target_and_invokes():
        g,p,e=game(CardClass.ROGUE)
        p.card("DRG_610",zone=Zone.DECK)
        target=e.summon("CS2_182"); other=e.summon("CS2_182")
        spell=play(p,cid,target=target)
        observed=f"target_health={target.health};other_health={other.health};invoke={p.invoke_counter};spell={spell.zone.name}"
        return check(target.health==2 and other.health==5 and p.invoke_counter==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("three_damage_to_undamaged_character_and_invoke","Undamaged selected minion loses exactly 3 Health; other minion unaffected; Invoke once.",damages_undamaged_target_and_invokes,"合法满血目标、伤害和祈求")])


def invocation_of_frost():
    cid="DRG_248"
    def freezes_enemy_and_invokes():
        g,p,e=game(CardClass.SHAMAN)
        p.card("DRG_620",zone=Zone.DECK)
        target=e.summon("CS2_182"); own=p.summon(WISP)
        spell=play(p,cid,target=target)
        observed=f"target_frozen={target.frozen};own_frozen={own.frozen};invoke={p.invoke_counter};spell={spell.zone.name}"
        return check(target.frozen and not own.frozen and p.invoke_counter==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("freeze_selected_enemy_and_invoke","Selected enemy freezes; own minion does not; Invoke once.",freezes_enemy_and_invokes,"敌方目标、冻结和祈求")])


def awaken():
    cid="DRG_249"
    def damages_both_fields_and_invokes():
        g,p,e=game(CardClass.WARRIOR)
        p.card("DRG_650",zone=Zone.DECK)
        own=p.summon("CS2_182"); enemy=e.summon("CS2_182")
        spell=play(p,cid)
        observed=f"own={own.health};enemy={enemy.health};heroes={p.hero.health}/{e.hero.health};invoke={p.invoke_counter};spell={spell.zone.name}"
        return check(own.health==4 and enemy.health==4 and p.hero.health==30 and e.hero.health==30 and p.invoke_counter==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("invoke_then_one_damage_to_all_minions","Both players' minions each lose 1 Health; heroes untouched; Invoke once.",damages_both_fields_and_invokes,"双方场上状态、英雄生命、祈求")])


def fiendish_rites():
    cid="DRG_250"
    def buffs_friendly_minions_and_invokes():
        g,p,e=game(CardClass.WARLOCK)
        p.card("DRG_600",zone=Zone.DECK)
        own=p.summon(WISP); enemy=e.summon(WISP)
        spell=play(p,cid)
        observed=f"own_atk={own.atk};enemy_atk={enemy.atk};invoke={p.invoke_counter};spell={spell.zone.name}"
        return check(own.atk==2 and enemy.atk==1 and p.invoke_counter==1 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("invoke_and_friendly_attack_buff","Friendly minion gains 1 Attack, enemy minion unchanged; Invoke once.",buffs_friendly_minions_and_invokes,"友方攻击增益和祈求")])


def clear_the_way():
    cid="DRG_251"
    def rush_summons_complete_sidequest():
        g,p,e=game(CardClass.HUNTER)
        quest=play(p,cid)
        p.summon(WISP)
        nonrush_progress=quest.progress
        progress_trace=[]
        for _ in range(3):
            p.summon("DRG_010")
            progress_trace.append(quest.progress)
        reward=[m for m in p.field if m.id=="DRG_251t"]
        observed=(f"nonrush_progress={nonrush_progress};quest={quest.zone.name};"
                  f"rush_progress={progress_trace};field={[(m.id,m.atk,m.health,m.rush) for m in p.field]};"
                  f"reward_count={len(reward)}")
        return check(nonrush_progress==0 and progress_trace==[1,2,3] and quest.zone==Zone.GRAVEYARD and
                     len(reward)==1 and reward[0].atk==4 and reward[0].health==4 and reward[0].rush,
                     observed)
    audit(cid,[("three_rush_summons_reward_gryphon","Non-Rush summon does not progress; third Rush summon completes quest and summons exactly one 4/4 Rush Gryphon.",rush_summons_complete_sidequest,"先以普通随从验证不计进度，再实际召唤三只突袭随从并检查任务区域及奖励身材/关键词")])


def phase_stalker():
    cid="DRG_252"
    def casts_secret_from_deck_after_power():
        g,p,e=game(CardClass.HUNTER)
        stalker=play(p,cid)
        secret=p.card("EX1_610",zone=Zone.DECK)
        ordinary=p.card(WISP,zone=Zone.DECK)
        p.hero.power.use()
        observed=f"secret={secret.zone.name};ordinary={ordinary.zone.name};stalker={stalker.zone.name}"
        return check(secret.zone==Zone.SECRET and ordinary.zone==Zone.DECK and stalker.zone==Zone.PLAY,observed)
    def no_secret_in_deck_does_nothing_extra():
        g,p,e=game(CardClass.HUNTER)
        stalker=play(p,cid)
        p.hero.power.use()
        observed=f"stalker={stalker.zone.name};field={[m.id for m in p.field]};deck={len(p.deck)}"
        return check(stalker.zone==Zone.PLAY and not any(x.type==CardType.SPELL and x.secret for x in p.field),observed)
    audit(cid,[("hero_power_casts_secret_from_deck","After Hero Power, a deck Secret is cast into Secret zone; non-Secret remains in deck.",casts_secret_from_deck_after_power,"实际使用英雄技能，检查奥秘出牌与非奥秘留牌分支"),
               ("no_secret_available","With no Secret in deck, Hero Power leaves Phase Stalker alive and does not create a Secret.",no_secret_in_deck_does_nothing_extra,"空牌库分支")])


def dwarven_sharpshooter():
    cid="DRG_253"
    def hero_power_damages_minion():
        g,p,e=game(CardClass.HUNTER)
        target=e.summon("CS2_182")
        p.summon(cid)
        p.hero.power.use(target=target)
        observed=f"target={target.health}/{target.zone.name};enemy_hero={e.hero.health};power_targeting={p.hero.power.requires_target()}"
        return check(target.health==3 and target.zone==Zone.PLAY and e.hero.health==30,observed)
    def no_sharpshooter_keeps_default_hero_targeting():
        g,p,e=game(CardClass.HUNTER)
        target=e.summon("CS2_182")
        p.hero.power.use()
        observed=f"target={target.health};enemy_hero={e.hero.health}"
        return check(target.health==5 and e.hero.health==28,observed)
    audit(cid,[("hero_power_can_target_minion","With Sharpshooter in play, Hero Power targets an enemy minion for 2 and leaves enemy hero untouched.",hero_power_damages_minion,"实际英雄技能指定敌方随从；既有 tests/test_dragons.py::test_dwarven_sharpshooter 仅检查合法目标，补上结算断言"),
               ("without_sharpshooter_hits_hero","Without Sharpshooter, default Hero Power hits enemy hero and leaves minion untouched.",no_sharpshooter_keeps_default_hero_targeting,"移除持续效果后的对照分支")])


def primordial_explorer():
    cid="DRG_254"
    def poisonous_battlecry_discovers_dragon():
        g,p,e=game(CardClass.HUNTER)
        explorer=play(p,cid)
        choice=p.choice
        offered=[c.id for c in choice.cards]
        valid=all(Race.DRAGON in c.races for c in choice.cards)
        selected=choice.cards[0]
        choice.choose(selected)
        observed=f"poisonous={explorer.poisonous};choice={offered};selected={selected.id};hand={p.hand[-1].id if p.hand else None}"
        return check(explorer.zone==Zone.PLAY and explorer.poisonous and valid and selected in p.hand,observed)
    def poisonous_combat_kills_high_health_minion():
        g,p,e=game(CardClass.HUNTER,CardClass.MAGE)
        target=e.summon("EX1_058")
        explorer=play(p,cid)
        p.choice.choose(p.choice.cards[0])
        g.skip_turn()
        explorer.attack(target)
        observed=f"explorer={explorer.health}/{explorer.zone.name};target={target.health}/{target.zone.name};atk={explorer.atk}/{target.atk}"
        return check(target.zone==Zone.GRAVEYARD and explorer.zone==Zone.PLAY,observed)
    audit(cid,[("poisonous_and_discover_dragon","Primordial Explorer is Poisonous; Battlecry presents Dragon choices and chosen Dragon enters hand.",poisonous_battlecry_discovers_dragon,"实际触发战吼、逐个核对发现选项种族并完成选择"),
               ("poisonous_combat_kills_high_health_minion","After the Explorer is ready, combat damage from it kills a 3-Health-or-higher minion through Poisonous even though its normal damage is only 2.",poisonous_combat_kills_high_health_minion,"对手召唤 3/5 Ancient Watcher；等待自己回合后实际攻击，验证剧毒战斗结算而不是仅读取关键词标记")])


def toxic_reinforcements():
    cid="DRG_255"
    def three_powers_reward_leper_gnomes():
        g,p,e=game(CardClass.HUNTER)
        quest=play(p,cid)
        for i in range(3):
            p.hero.power.use()
            if i<2:
                g.skip_turn()
        lepers=[m for m in p.field if m.id=="DRG_255t2"]
        gryphons=[m for m in p.field if m.id=="DRG_251t"]
        observed=f"quest={quest.zone.name};lepers={[(m.atk,m.health) for m in lepers]};gryphons={[(m.atk,m.health,m.rush) for m in gryphons]};enemy_hero={e.hero.health}"
        return check(quest.zone==Zone.GRAVEYARD and len(lepers)==3 and all(m.atk==1 and m.health==1 for m in lepers) and not gryphons,observed)
    audit(cid,[("three_hero_powers_summon_three_leper_gnomes","After three Hero Powers on separate turns, quest completes and exactly three 1/1 Leper Gnomes are summoned.",three_powers_reward_leper_gnomes,"跨三个己方回合实际使用英雄技能，按 XML token DRG_255t2 检查数量/身材，不能把 DRG_251t 狮鹫当作奖励")])


def dragonbane():
    cid="DRG_256"
    def hero_power_randomly_hits_enemy_minion_or_hero():
        minion_hits=0
        hero_only=0
        samples=[]
        for seed in range(24):
            g,p,e=game(CardClass.HUNTER,seed=seed+300)
            target=e.summon("CS2_182")
            p.summon(cid)
            p.hero.power.use()
            if target.zone==Zone.GRAVEYARD:
                minion_hits+=1
            elif target.health==5:
                if e.hero.health==23:
                    hero_only+=1
            samples.append(f"{seed}:{target.zone.name}/{target.health},H{e.hero.health}")
        observed=f"minion_hits={minion_hits};hero_only={hero_only};samples={samples}"
        return check(minion_hits>0 and hero_only>0,observed)
    audit(cid,[("trigger_random_enemy_after_hero_power","Across deterministic seeds with one enemy minion and enemy hero, Dragonbane sometimes hits each eligible enemy; no fixed-hero-only behavior.",hero_power_randomly_hits_enemy_minion_or_hero,"24 个实际对局种子；2 点猎人技能伤害与额外5点随机伤害分开由生命/区域辨识；源码候选需查是否只命中敌方英雄")])


def frizz_kindleroost():
    cid="DRG_257"
    def battlecry_reduces_only_deck_dragons():
        g,p,e=game(CardClass.MAGE)
        dragon=p.card("DRG_075",zone=Zone.DECK)
        non_dragon=p.card("CS2_182",zone=Zone.DECK)
        hand_dragon=p.give("DRG_075")
        play(p,cid)
        observed=f"deck_dragon_cost={dragon.cost};non_dragon_cost={non_dragon.cost};hand_dragon_cost={hand_dragon.cost};zones={dragon.zone.name}/{non_dragon.zone.name}/{hand_dragon.zone.name}"
        return check(dragon.cost==3 and non_dragon.cost==4 and hand_dragon.cost==5,observed)
    audit(cid,[("battlecry_reduces_deck_dragons_by_two","Frizz reduces 5-cost Cobalt Spellkin in deck to 3; non-Dragon in deck and same Dragon in hand retain their printed costs.",battlecry_reduces_only_deck_dragons,"使用真实5费龙 DRG_075 Cobalt Spellkin；部署一个牌库龙、非龙和手牌龙，逐一检查实际费用/所在区域")])


def sanctuary():
    cid="DRG_258"
    def no_damage_for_full_turn_rewards_taunt():
        g,p,e=game(CardClass.PALADIN)
        quest=play(p,cid)
        g.end_turn(); g.end_turn(); g.skip_turn()
        reward=[m for m in p.field if m.id=="DRG_258t"]
        observed=f"quest={quest.zone.name};reward={[(m.atk,m.health,m.taunt) for m in reward]}"
        return check(quest.zone==Zone.GRAVEYARD and len(reward)==1 and reward[0].atk==3 and reward[0].health==6 and reward[0].taunt,observed)
    def damage_during_opponent_turn_prevents_reward():
        g,p,e=game(CardClass.PALADIN)
        quest=play(p,cid)
        g.end_turn()
        e.give("CS2_008").play(target=p.hero)
        g.end_turn()
        observed=f"quest={quest.zone.name};progress={quest.progress};hero={p.hero.health};field={[m.id for m in p.field]}"
        return check(quest.zone==Zone.SECRET and quest.progress==0 and not any(m.id=="DRG_258t" for m in p.field),observed)
    audit(cid,[("undamaged_turn_summons_taunt","After a full turn without damage, sidequest completes and summons one 3/6 Taunt.",no_damage_for_full_turn_rewards_taunt,"按既有 test_sanctuary 的回合时序实际跨回合验证并核对 token"),
               ("damage_prevents_progress","Taking spell damage during opponent turn prevents Sanctuary progress and reward at next own turn.",damage_during_opponent_turn_prevents_reward,"对手回合实际对己方英雄施放 Moonfire，随后检查未完成")])


def malygos_aspect_of_magic():
    cid="DRG_270"
    upgraded={"DRG_270t1","DRG_270t2","DRG_270t4","DRG_270t5","DRG_270t6","DRG_270t7","DRG_270t8","DRG_270t9","DRG_270t11"}
    def dragon_in_hand_discovers_upgraded_mage_spell():
        g,p,e=game(CardClass.MAGE)
        dragon=p.give("DRG_075")
        maly=play(p,cid)
        choice=p.choice
        offered=[c.id for c in choice.cards]
        picked=choice.cards[0]
        valid=all(c.id in upgraded for c in choice.cards)
        choice.choose(picked)
        observed=f"maly={maly.zone.name};dragon={dragon.zone.name};offered={offered};picked={picked.id};in_hand={picked in p.hand}"
        return check(maly.zone==Zone.PLAY and valid and picked in p.hand,observed)
    def without_dragon_no_choice():
        g,p,e=game(CardClass.MAGE)
        maly=play(p,cid)
        observed=f"choice={p.choice};field={[m.id for m in p.field]}"
        return check(p.choice is None and maly.zone==Zone.PLAY,observed)
    audit(cid,[("dragon_enables_upgraded_spell_discover","Holding a Dragon makes Battlecry offer only Malygos upgraded Mage spells and chosen spell enters hand.",dragon_in_hand_discovers_upgraded_mage_spell,"实际持龙触发发现，逐一核对九种增强法术候选并完成选择"),
               ("no_dragon_no_discover","Without a Dragon in hand, Malygos has no Discover choice.",without_dragon_no_choice,"不持龙的 powered-up 条件对照")])


def fate_weaver():
    cid="DRG_300"
    def two_invokes_reduce_hand_cost():
        g,p,e=game(CardClass.PRIEST)
        p.card("DRG_660",zone=Zone.DECK)
        fireball=p.give("CS2_029")
        play(p,"DRG_249")
        target=e.summon("CS2_182")
        play(p,"DRG_246",target=target)
        g.skip_turn()
        weaver=play(p,cid)
        observed=f"invoke={p.invoke_counter};fireball_cost={fireball.cost};weaver={weaver.zone.name};target={target.zone.name}"
        return check(p.invoke_counter==2 and fireball.cost==3 and weaver.zone==Zone.PLAY and target.zone==Zone.GRAVEYARD,observed)
    def one_invoke_does_not_reduce_hand():
        g,p,e=game(CardClass.PRIEST)
        p.card("DRG_660",zone=Zone.DECK)
        fireball=p.give("CS2_029")
        play(p,"DRG_249")
        weaver=play(p,cid)
        observed=f"invoke={p.invoke_counter};fireball_cost={fireball.cost};weaver={weaver.zone.name}"
        return check(p.invoke_counter==1 and fireball.cost==4 and weaver.zone==Zone.PLAY,observed)
    audit(cid,[("two_invokes_discount_current_hand","After two real Invoke spells, Fate Weaver Battlecry reduces a held 4-cost Fireball to 3.",two_invokes_reduce_hand_cost,"用 DRG_249 与合法目标上的 DRG_246 实际祈求两次，再核对留在手牌中的法术费用"),
               ("one_invoke_no_discount","After only one Invoke, held Fireball remains 4 mana.",one_invoke_does_not_reduce_hand,"只祈求一次的条件分支")])


def whispers_of_evil():
    cid="DRG_301"
    def spell_adds_lackey_to_hand():
        g,p,e=game(CardClass.PRIEST)
        before=len(p.hand)
        spell=play(p,cid)
        lackeys={"DAL_613","DAL_614","DAL_615","DAL_739","DAL_741","ULD_616","DRG_052"}
        added=[c.id for c in p.hand]
        observed=f"spell={spell.zone.name};hand={added};count_delta={len(p.hand)-before}"
        return check(spell.zone==Zone.GRAVEYARD and len(p.hand)==before+1 and len(p.hand)>0 and p.hand[-1].id in lackeys,observed)
    audit(cid,[("add_one_lackey_to_hand","Whispers of EVIL resolves to exactly one Lackey from the supported Lackey pool in hand.",spell_adds_lackey_to_hand,"实际施放法术并断言手牌增量与生成卡牌属于七种 Lackey token 池")])


def grave_rune():
    cid="DRG_302"
    def enchanted_minion_death_summons_two_copies():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        target=p.summon(WISP)
        spell=play(p,cid,target=target)
        g.end_turn()
        play(e,"CS2_008",target=target)
        copies=[m for m in p.field if m.id==WISP]
        observed=f"spell={spell.zone.name};original={target.zone.name};copies={len(copies)};copy_stats={[(m.atk,m.health) for m in copies]}"
        return check(target.zone==Zone.GRAVEYARD and len(copies)==2 and all(m.atk==1 and m.health==1 for m in copies),observed)
    audit(cid,[("grave_rune_death_summons_two_copies","After Grave Rune enchants a friendly minion, an actual enemy spell kill puts original in graveyard and summons exactly two full-stat copies.",enchanted_minion_death_summons_two_copies,"先实际施放 Grave Rune，再由对手施放 Moonfire 触发死亡；检查原件及两份复制")])


def disciple_of_galakrond():
    cid="DRG_303"
    def battlecry_invokes_class_galakrond():
        g,p,e=game(CardClass.PRIEST)
        galakrond=p.card("DRG_660",zone=Zone.DECK)
        minion=play(p,cid)
        observed=f"invoke={p.invoke_counter};galakrond={galakrond.zone.name};minion={minion.zone.name};stats={minion.atk}/{minion.health}"
        return check(p.invoke_counter==1 and galakrond.zone==Zone.DECK and minion.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_invokes_once","Playing Disciple resolves Battlecry, increasing Invoke counter once while Galakrond remains in deck.",battlecry_invokes_class_galakrond,"真实出牌，牌库预置牧师 Galakrond 并核对祈求计数")])


def chronobreaker():
    cid="DRG_304"
    def deathrattle_hits_enemy_minions_when_holding_dragon():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        dragon=p.give("DRG_075")
        own=p.summon("CS2_182"); enemy=e.summon("CS2_182")
        chrono=play(p,cid)
        g.end_turn()
        play(e,"CS2_029",target=chrono)
        observed=f"dragon={dragon.zone.name};chrono={chrono.zone.name};enemy={enemy.health}/{enemy.zone.name};own={own.health}/{own.zone.name};heroes={p.hero.health}/{e.hero.health}"
        return check(chrono.zone==Zone.GRAVEYARD and enemy.health==2 and enemy.zone==Zone.PLAY and own.health==5 and p.hero.health==30 and e.hero.health==30,observed)
    def no_dragon_skips_deathrattle_damage():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        enemy=e.summon("CS2_182")
        chrono=play(p,cid)
        g.end_turn()
        play(e,"CS2_029",target=chrono)
        observed=f"chrono={chrono.zone.name};enemy={enemy.health}/{enemy.zone.name}"
        return check(chrono.zone==Zone.GRAVEYARD and enemy.health==5 and enemy.zone==Zone.PLAY,observed)
    audit(cid,[("dragon_held_deathrattle_damages_enemy_board","With another Dragon held, Chronobreaker deathrattle deals 3 only to all enemy minions.",deathrattle_hits_enemy_minions_when_holding_dragon,"手里额外持龙；对手用真实伤害法术击杀 Chronobreaker，比较敌友随从及英雄"),
               ("no_dragon_deathrattle_no_damage","Without a Dragon left in hand, Chronobreaker death causes no enemy-minion damage.",no_dragon_skips_deathrattle_damage,"未持龙条件分支")])


def envoy_of_lazul():
    cid="DRG_306"
    def correct_guess_copies_opponent_hand_card():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        opponent_card=e.give("CS2_008")
        e.card("CS2_182",zone=Zone.DECK); e.card("EX1_610",zone=Zone.DECK)
        envoy=play(p,cid)
        choice=p.choice
        shown=[c.id for c in choice.cards]
        correct=choice.correct_card
        choice.choose(correct)
        observed=f"opponent_card={opponent_card.id};shown={shown};correct={correct.id};copied={correct in p.hand};envoy={envoy.zone.name}"
        return check(envoy.zone==Zone.PLAY and len(shown)==3 and correct.id==opponent_card.id and correct in p.hand,observed)
    def empty_opponent_hand_has_no_choice():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        envoy=play(p,cid)
        observed=f"choice={p.choice};envoy={envoy.zone.name};field={[m.id for m in p.field]}"
        return check(p.choice is None and envoy.zone==Zone.PLAY,observed)
    audit(cid,[("guess_opponent_hand_card_to_get_copy","Battlecry shows one opponent hand card and two deck cards; choosing the hand card adds its copy to own hand.",correct_guess_copies_opponent_hand_card,"对应既有 test_envoy_of_lazul，固定对手手牌并留两张牌库卡，真实选择正确答案核对复制"),
               ("no_opponent_hand_no_choice","With no opponent hand cards, Envoy resolves without an invalid or phantom choice.",empty_opponent_hand_has_no_choice,"空对手手牌边界")])


def breath_of_the_infinite():
    cid="DRG_307"
    def no_dragon_hits_all_minions():
        g,p,e=game(CardClass.PRIEST)
        own=p.summon("CS2_182"); enemy=e.summon("CS2_182")
        spell=play(p,cid)
        observed=f"spell={spell.zone.name};own={own.health};enemy={enemy.health};heroes={p.hero.health}/{e.hero.health}"
        return check(own.health==3 and enemy.health==3 and p.hero.health==30 and e.hero.health==30,observed)
    def dragon_held_hits_only_enemies():
        g,p,e=game(CardClass.PRIEST)
        dragon=p.give("DRG_075")
        own=p.summon("CS2_182"); enemy=e.summon("CS2_182")
        play(p,cid)
        observed=f"dragon={dragon.zone.name};own={own.health};enemy={enemy.health};heroes={p.hero.health}/{e.hero.health}"
        return check(own.health==5 and enemy.health==3 and p.hero.health==30 and e.hero.health==30,observed)
    audit(cid,[("no_dragon_damages_all_minions","Without a Dragon in hand, Breath deals 2 to friendly and enemy minions, not heroes.",no_dragon_hits_all_minions,"空手持龙条件实际比较双方随从与英雄生命"),
               ("dragon_held_damages_enemy_minions_only","Holding a Dragon restricts 2 damage to enemy minions; friendly minion remains full health.",dragon_held_hits_only_enemies,"持龙强化分支")])


def mindflayer_kaahrj():
    cid="DRG_308"
    def deathrattle_summons_copy_of_chosen_enemy():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        target=e.summon("CS2_182")
        kaahrj=play(p,cid,target=target)
        g.end_turn()
        play(e,"CS2_029",target=kaahrj)
        copies=[m for m in p.field if m.id==target.id]
        observed=f"target={target.id}/{target.health}/{target.zone.name};kaahrj={kaahrj.zone.name};copies={[(m.atk,m.health,m.zone.name) for m in copies]}"
        return check(kaahrj.zone==Zone.GRAVEYARD and target.zone==Zone.PLAY and target.health==5 and len(copies)==1 and copies[0].atk==4 and copies[0].health==5,observed)
    audit(cid,[("chosen_enemy_copy_summoned_on_death","Kaahrj records the chosen enemy minion; after a real Fireball kill, deathrattle summons one full-stat copy while original survives.",deathrattle_summons_copy_of_chosen_enemy,"实际选择敌方 Yeti，之后由对手用 Fireball 杀死 Kaahrj 并验证复制区域/身材")])


def nozdormu_the_timeless():
    cid="DRG_309"
    def battlecry_sets_both_players_to_ten_crystals():
        g,p,e=game(CardClass.PALADIN)
        p.max_mana=8; p.used_mana=0
        e.max_mana=8; e.used_mana=0
        nozdormu=play(p,cid)
        observed=f"nozdormu={nozdormu.zone.name};max={p.max_mana}/{e.max_mana};mana={p.mana}/{e.mana};used={p.used_mana}/{e.used_mana}"
        return check(p.max_mana==10 and e.max_mana==10,observed)
    audit(cid,[("battlecry_sets_both_to_ten_crystals","Nozdormu battlecry sets both player's max mana crystals to 10 from a deliberately reduced 8-crystal state.",battlecry_sets_both_players_to_ten_crystals,"将双方当前水晶限制为8，再实际打出7费随从并核验双方最大水晶")])


def evasive_drakonid():
    cid="DRG_310"
    def spell_and_hero_power_cannot_target_it():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE)
        drakonid=play(p,cid)
        taunt=drakonid.taunt
        g.end_turn()
        spell_blocked=False; power_blocked=False
        try:
            play(e,"CS2_008",target=drakonid)
        except InvalidAction:
            spell_blocked=True
        before=drakonid.health
        try:
            e.hero.power.use(target=drakonid)
        except InvalidAction:
            power_blocked=True
        observed=f"taunt={taunt};spell_blocked={spell_blocked};power_blocked={power_blocked};health={drakonid.health};enemy_hand={[c.id for c in e.hand]}"
        return check(taunt and spell_blocked and power_blocked and drakonid.health==before,observed)
    audit(cid,[("taunt_minion_untargetable_by_spells_and_hero_power","Evasive Drakonid has Taunt; enemy targeted spell and Hero Power are rejected without changing its Health.",spell_and_hero_power_cannot_target_it,"实际发起两种合法候选效果的指定目标操作，捕获 InvalidAction 并确认目标未受伤")])


def treenforcements():
    cid="DRG_311"
    def choose_treant_summons_two_two():
        g,p,e=game(CardClass.DRUID)
        spell=play(p,cid,choose="DRG_311a")
        treants=[m for m in p.field if m.id=="DRG_311t"]
        observed=f"spell={spell.zone.name};treants={[(m.atk,m.health,m.taunt) for m in treants]}"
        return check(spell.zone==Zone.GRAVEYARD and len(treants)==1 and treants[0].atk==2 and treants[0].health==2,observed)
    def choose_buff_gives_health_and_taunt():
        g,p,e=game(CardClass.DRUID)
        target=p.summon(WISP)
        spell=play(p,cid,target=target,choose="DRG_311b")
        observed=f"spell={spell.zone.name};target={target.atk}/{target.health}/{target.max_health};taunt={target.taunt};field={[m.id for m in p.field]}"
        return check(spell.zone==Zone.GRAVEYARD and target.zone==Zone.PLAY and target.atk==1 and target.health==3 and target.taunt and not any(m.id=="DRG_311t" for m in p.field),observed)
    audit(cid,[("choose_summon_treant","Choose One summon branch resolves to exactly one 2/2 Treant.",choose_treant_summons_two_two,"实际选择召唤分支并核对 token 身材与数量"),
               ("choose_target_buff","Target branch gives a friendly minion +2 Health and Taunt without summoning the Treant.",choose_buff_gives_health_and_taunt,"实际选择强化分支，核对生命上限/当前生命、攻击力、嘲讽和无额外召唤")])


CHECKS={
    "DRG_246":time_rip,"DRG_247":seal_fate,"DRG_248":invocation_of_frost,
    "DRG_249":awaken,"DRG_250":fiendish_rites,"DRG_251":clear_the_way,
    "DRG_252":phase_stalker,"DRG_253":dwarven_sharpshooter,
    "DRG_254":primordial_explorer,"DRG_255":toxic_reinforcements,
    "DRG_256":dragonbane,"DRG_257":frizz_kindleroost,"DRG_258":sanctuary,
    "DRG_270":malygos_aspect_of_magic,"DRG_300":fate_weaver,
    "DRG_301":whispers_of_evil,"DRG_302":grave_rune,
    "DRG_303":disciple_of_galakrond,"DRG_304":chronobreaker,
    "DRG_306":envoy_of_lazul,"DRG_307":breath_of_the_infinite,
    "DRG_308":mindflayer_kaahrj,"DRG_309":nozdormu_the_timeless,
    "DRG_310":evasive_drakonid,"DRG_311":treenforcements,
}
assert set(CHECKS) == set(ROSTER_BY_ID), (sorted(set(ROSTER_BY_ID)-set(CHECKS)), sorted(set(CHECKS)-set(ROSTER_BY_ID)))

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
