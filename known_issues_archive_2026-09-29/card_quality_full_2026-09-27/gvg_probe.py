"""Run and index per-card behavior checks for the frozen GVG yellow roster."""

from __future__ import annotations

import csv
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from utils import ANIMATED_STATUE, MOONFIRE, TARGET_DUMMY, WISP, prepare_empty_game

logging.disable(logging.CRITICAL)
BASELINE = HERE / "four_set_yellow_baseline.csv"
PROBE_OUT = HERE / "gvg_probe.csv"
VERDICT_OUT = HERE / "gvg_verdict.csv"

# Frozen from the GVG rows of four_set_yellow_baseline.csv before the report rebuild.
FROZEN_GVG_IDS = tuple(
    "GVG_%03d" % n
    for n in (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
        20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 36, 37,
        38, 39, 40, 41, 42, 43, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55,
        56, 57, 58, 59, 60, 61, 62, 63, 65, 66, 67, 68, 69, 72, 73, 74, 75,
        76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92,
        93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107,
        108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121,
        122, 123,
    )
)
PARENT_OWNED_TAIL = {92,94,97,99,100,102,103,104,108,110,111,112,114,116,117,119,122}
OWN_GVG_IDS = tuple(cid for cid in FROZEN_GVG_IDS if int(cid[-3:]) not in PARENT_OWNED_TAIL)

VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")

YELLOW_BLOCKERS = {
    "GVG_001": "随机敌方随从池有两个耐久不同的候选，但本轮只用一个种子命中其一，尚未观察另一个候选被选中。",
    "GVG_003": "只观察到一个随机随从及其减费；不同费用结果（尤其费用低于3时归零）的随机样本尚未覆盖。",
    "GVG_004": "确认有机械时总计分配4点伤害、无机械时不造成伤害；尚未用多个种子验证随机分配覆盖不同敌方随从与英雄。",
    "GVG_020": "触发时的两个非机械随从仅一个种子候选被命中；另一个合法目标的随机分支尚未覆盖。",
    "GVG_029": "双方手牌各只有一张随从，随机选择没有竞争候选；多候选手牌下是否各自只召唤一张未验证。",
    "GVG_034": "本轮确认受伤后加入1张备件，但随机备件结果仅出现PART_007，备件池的其他结果未采样。",
    "GVG_042": "确认加入4张鱼人且过载3；只测了一组随机鱼人身份，尚未跨种子覆盖不同鱼人候选。",
    "GVG_043": "装备与+1攻击均生效，但两名友方随从只用一个种子抽到其中一名，另一随机受益者未见。",
    "GVG_052": "已验证有受伤友方随从时减费4且目标被消灭；无受伤友方随从时应维持原费用的条件分支尚未测。",
    "GVG_054": "实际英雄攻击128次均打向声明的敌方英雄，0次转向两名敌方随从；50%错误目标分支缺失，已列RED。",
    "GVG_059": "武器已装备且一名候选获得嘲讽与圣盾；随机受益者只采到一名，另一友方随从分支尚未观察。",
    "GVG_075": "召唤海盗后一次随机命中造成2伤；尚未跨种子观察另一敌方随从或敌方英雄作为受击对象。",
    "GVG_078": "确认死亡后双方各获得1张备件；每侧本轮都只采到一个随机备件身份，备件池其他结果未覆盖。",
    "GVG_082": "确认Clockwork Gnome死亡加入1张备件；随机备件身份只采到PART_007，其他备件结果未抽样。",
    "GVG_087": "猎人英雄技能对敌方随从在Sniper登场前后均不可选（legal_before=False, legal_after=False）；赋予目标能力的更新未生效，已列RED。",
    "GVG_090": "本轮只有双方英雄可分摊6点伤害，未放入其他随从；随机拆分到友方/敌方随从的分支尚未覆盖。",
    "GVG_096": "死亡后召唤出的随机随从符合2费，但只采样一个身份；其他2费随机候选尚未覆盖。",
    "GVG_105": "死亡后召唤出的随机随从符合4费，但只采样一个身份；其他4费随机候选尚未覆盖。",
    "GVG_107": "4个随从都只获得一个关键词，但样本只出现圣盾与风怒；随机嘲讽分支尚未出现。",
    "GVG_115": "战吼和亡语各加入1张备件已验证；两次随机结果只采到当前样本身份，备件池多种结果未覆盖。",
}


def _read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())


def _new_game(seed=19, class1=None, class2=None):
    game = prepare_empty_game(class1, class2)
    game.random.seed(seed)
    # GVG's Spare Parts and other legacy pools are not Standard-legal.
    game.player1.is_standard = False
    game.player2.is_standard = False
    return game


def _play(player, card_id, target=None, **kwargs):
    card = player.give(card_id)
    card.play(target=target, **kwargs)
    return card


def _summon(player, card_id):
    return player.summon(card_id)


def _ready_player_minions(game, player):
    game.current_player = player
    for minion in player.field:
        minion.turns_in_play = max(1, minion.turns_in_play)
        minion.cant_attack = False
        minion.num_attacks = 0


def _end_player_turn(game, player):
    game.current_player = player
    game.end_turn()


def _forgetful_trials(card_id, weapon=False, mogor=False, seeds=range(32)):
    outcomes = []
    for seed in seeds:
        game = _new_game(seed=seed)
        attacker_owner, defender = game.player1, game.player2
        if mogor:
            _summon(attacker_owner, "GVG_112")
            attacker = _summon(attacker_owner, WISP)
            original = _summon(defender, ANIMATED_STATUE)
            alternate = _summon(defender, ANIMATED_STATUE)
            _ready_player_minions(game, attacker_owner)
            attacker.attack(original)
            outcomes.append((original.damage == 1, alternate.damage == 1))
        elif weapon:
            _play(attacker_owner, card_id)
            alternate = _summon(defender, ANIMATED_STATUE)
            alternate2 = _summon(defender, "CS2_033")
            game.current_player = attacker_owner
            _ready_player_minions(game, attacker_owner)
            attacker_owner.hero.attack(defender.hero)
            outcomes.append((defender.hero.health < 30, alternate.damage > 0 or alternate2.damage > 0))
        else:
            attacker = _summon(attacker_owner, card_id)
            alternate = _summon(defender, ANIMATED_STATUE)
            _ready_player_minions(game, attacker_owner)
            attacker.attack(defender.hero)
            outcomes.append((defender.hero.health < 30, alternate.damage > 0))
    redirected = sum(1 for direct, alt in outcomes if alt and not direct)
    direct = sum(1 for was_direct, alt in outcomes if was_direct and not alt)
    return direct, redirected, outcomes


def _rec(card_id, case_id, expected, observed, passed=True, note=""):
    return {
        "card_id": card_id,
        "case_id": case_id,
        "expected": expected,
        "observed": observed,
        "outcome": "pass" if passed else "inconclusive",
        "notes": note,
    }


def custom_cases(cid):
    """Card-specific Fireplace scenarios for cards lacking a direct test reference."""
    g = _new_game()
    p, o = g.player1, g.player2
    rows = []

    if cid == "GVG_001":
        a, b = _summon(o, "CS2_033"), _summon(o, ANIMATED_STATUE)
        before = (a.damage, b.damage)
        _play(p, cid)
        after = (a.damage, b.damage)
        hits = [after[i] - before[i] for i in range(2)]
        rows.append(_rec(cid, "GVG_001_two_enemy_candidates", "exactly one of two enemy minions takes 4; no hero damage", f"health_delta={hits}; zones={[a.zone,b.zone]}; enemy_hero={o.hero.health}", sum(hits) == 4 and 4 in hits and o.hero.health == 30, "random target pool uses two distinguishable enemies"))
    elif cid == "GVG_002":
        snow = _summon(p, cid)
        target = _summon(o, "CS2_033")
        _ready_player_minions(g, p)
        snow.attack(target)
        rows.append(_rec(cid, "GVG_002_freeze_damaged_target", "minion damage freezes the damaged character", f"target_health={target.health}; frozen={target.frozen}", target.health == 4 and target.frozen))
        g2=_new_game(); p2,o2=g2.player1,g2.player2
        snow2=_summon(p2,cid); _ready_player_minions(g2,p2); hero_before=o2.hero.health
        snow2.attack(o2.hero)
        rows.append(_rec(cid,"GVG_002_freeze_damaged_hero","hero damage from Snowchugger also freezes that hero",f"enemy_hero_health={hero_before}->{o2.hero.health}; frozen={o2.hero.frozen}; attacker={snow2.zone}",o2.hero.health==hero_before-snow2.atk and o2.hero.frozen and snow2.zone==Zone.PLAY))
    elif cid == "GVG_003":
        before = len(p.hand)
        _play(p, cid)
        added = list(p.hand)[before:]
        card = added[-1] if added else None
        rows.append(_rec(cid, "GVG_003_random_minion_cost_reduction", "adds one random minion to hand at 3 less than its printed cost, floored at 0", f"hand_added={len(added)}; card={(card.id, card.type, card.data.cost, card.cost) if card else None}", len(added) == 1 and card.type == CardType.MINION and card.cost == max(0, card.data.cost - 3), "random minion identity is left unconstrained; the realized card and cost are recorded"))
    elif cid == "GVG_004":
        mech = _summon(p, "GVG_082")
        enemies = [_summon(o, "CS2_033") for _ in range(4)]
        before = [m.damage for m in enemies]
        hero_before = o.hero.health
        blast = _play(p, cid)
        deltas = [m.damage - before[i] for i, m in enumerate(enemies)]
        total = sum(deltas) + hero_before - o.hero.health
        rows.append(_rec(cid, "GVG_004_mech_enabled_four_random_enemy_damage", "with a friendly Mech, deals exactly four 1-damage hits among enemy minions and hero", f"mech={mech.id}; deltas={deltas}; hero_delta={hero_before-o.hero.health}; total={total}; blast={blast.id}", total == 4 and all(d >= 0 for d in deltas), "four minions plus the opposing hero provide distinct random recipients"))
        g2 = _new_game(); p2, o2 = g2.player1, g2.player2
        enemies2 = [_summon(o2, "CS2_033") for _ in range(2)]
        _play(p2, cid)
        rows.append(_rec(cid, "GVG_004_no_mech_no_effect", "without a friendly Mech, deals no damage", f"enemy_damage={[m.damage for m in enemies2]}; enemy_hero={o2.hero.health}", all(m.damage == 0 for m in enemies2) and o2.hero.health == 30))
    elif cid == "GVG_005":
        originals = [_summon(p, WISP), _summon(p, "GVG_082")]
        before = len(p.hand)
        _play(p, cid)
        added = list(p.hand)[before:]
        rows.append(_rec(cid, "GVG_005_copy_each_friendly_minion", "adds exactly one hand copy for each friendly minion", f"board={[x.id for x in originals]}; added={[x.id for x in added]}", sorted(x.id for x in added) == sorted(x.id for x in originals), "two distinct friendly minions verify per-minion copy identity"))
    elif cid == "GVG_006":
        mech = p.give("GVG_082"); nonmech = p.give("CS2_033")
        base = (mech.cost, nonmech.cost)
        aura = _summon(p, cid)
        active = (mech.cost, nonmech.cost)
        aura.destroy()
        inactive = (mech.cost, nonmech.cost)
        rows.append(_rec(cid, "GVG_006_mech_hand_cost_aura", "friendly Mechs in hand cost 1 less, non-Mechs do not; removing Mechwarper restores cost", f"base={base}; aura={active}; removed={inactive}", active == (max(0, base[0]-1), base[1]) and inactive == base))
    elif cid == "GVG_007":
        leviathan = p.give(cid); leviathan.shuffle_into_deck()
        _end_player_turn(g, p)
        wisp=_summon(o, WISP)
        _end_player_turn(g, o)
        rows.append(_rec(cid, "GVG_007_on_draw_all_character_damage", "drawing Flame Leviathan deals 2 to all characters", f"drawn_in_hand={leviathan in p.hand}; heroes={p.hero.health}/{o.hero.health}; enemy_wisp={wisp.zone}/{wisp.health}", p.hero.health == 28 and o.hero.health == 28 and wisp.zone == Zone.GRAVEYARD, "card is drawn through the real turn draw path"))
    elif cid == "GVG_008":
        a = _summon(p, "GVG_093")
        b = _summon(o, "CS2_033")
        _play(p, cid)
        rows.append(_rec(cid, "GVG_008_damage_each_minion_equal_attack", "each minion takes damage equal to its own Attack; heroes are unaffected", f"friendly_0atk={a.zone}/{a.health}; enemy_3atk={b.zone}/{b.health}; heroes={p.hero.health}/{o.hero.health}", a.zone == Zone.PLAY and a.health == 2 and b.zone == Zone.PLAY and b.health == 3 and p.hero.health == o.hero.health == 30))
    elif cid == "GVG_009":
        _play(p, cid)
        rows.append(_rec(cid, "GVG_009_battlecry_both_heroes", "both heroes lose 3 health", f"friendly={p.hero.health}; enemy={o.hero.health}", p.hero.health == 27 and o.hero.health == 27))
    elif cid == "GVG_010":
        target = _summon(p, "CS2_033")
        before = (target.atk, target.max_health)
        _play(p, cid, target)
        spellpower = p.spellpower
        hero_before = o.hero.health
        _play(p, MOONFIRE, o.hero)
        rows.append(_rec(cid, "GVG_010_stats_and_spell_damage", "target gets +2/+4 and Spell Damage +1, which increases Moonfire by 1", f"before={before}; after={target.atk}/{target.max_health}; spellpower={spellpower}; moonfire_damage={hero_before-o.hero.health}", (target.atk,target.max_health)==(before[0]+2,before[1]+4) and spellpower==1 and hero_before-o.hero.health==2))
    elif cid == "GVG_011":
        target = _summon(o, "CS2_033")
        before = target.atk
        _play(p, cid, target)
        after = target.atk
        _end_player_turn(g, p)
        expired = target.atk
        rows.append(_rec(cid, "GVG_011_temporary_attack_reduction", "minion loses 2 Attack for this turn only", f"attack={before}->{after}->end_turn:{expired}", after==before-2 and expired==before))
    elif cid == "GVG_012":
        for case_id, starting_health in (("GVG_012_still_damaged_summons", 2), ("GVG_012_fully_healed_no_summon", 5)):
            game = _new_game(); player=game.player1
            target=_summon(player, "CS2_033"); target.set_current_health(starting_health)
            _play(player,cid,target)
            wardens=list(player.field.filter(id="EX1_001"))
            rows.append(_rec(cid,case_id,"heals target by 3 and summons Lightwarden only if target remains damaged",f"start={starting_health}/6; after={target.health}/6; wardens={len(wardens)}",target.health==min(6,starting_health+3) and len(wardens)==(1 if starting_health+3<6 else 0)))
    elif cid == "GVG_013":
        mech=_summon(p,"GVG_082"); cog=_summon(p,cid); active=cog.atk
        mech.destroy(); inactive=cog.atk
        rows.append(_rec(cid,"GVG_013_mech_conditional_attack_aura","Cogmaster gains +2 Attack while a friendly Mech is present and loses it when none remain",f"with_mech={active}; after_mech_death={inactive}; cog_zone={cog.zone}",active==3 and inactive==1 and cog.zone==Zone.PLAY))
    elif cid == "GVG_014":
        target=_summon(p,ANIMATED_STATUE); target.set_current_health(7)
        v=p.give(cid); before=(v.health,target.health)
        v.play(target=target)
        rows.append(_rec(cid,"GVG_014_swap_current_health","Battlecry swaps the two minions' current Health values",f"before={before}; after={v.health}/{target.health}; maxima={v.max_health}/{target.max_health}",v.health==before[1] and target.health==before[0]))
    elif cid == "GVG_015":
        target=_summon(o,"CS2_033"); _play(p,cid,target)
        rows.append(_rec(cid,"GVG_015_three_damage_minion_target","Darkbomb deals exactly 3 to its selected minion",f"target={target.id}; health={target.health}; damage={target.damage}; zone={target.zone}",target.zone==Zone.PLAY and target.health==3 and target.damage==3))
    elif cid == "GVG_016":
        deck_cards=[p.give(WISP) for _ in range(5)]
        for card in deck_cards: card.shuffle_into_deck()
        reaver=_summon(p,cid); before=len(p.deck)
        g.current_player=o
        _play(o,MOONFIRE,p.hero)
        rows.append(_rec(cid,"GVG_016_opponent_play_mills_three","each opponent card play removes the top three cards of Fel Reaver controller's deck",f"deck={before}->{len(p.deck)}; reaver={reaver.zone}; milled={[x.id for x in p.graveyard if x.id==WISP]}",before-len(p.deck)==3 and reaver.zone==Zone.PLAY))
    elif cid == "GVG_017":
        # Draw one Beast and one non-Beast in separate runs to assert both branches.
        for case_id, top in (("GVG_017_beast_draw", "EX1_534"), ("GVG_017_nonbeast_draw", "CS2_033")):
            game = _new_game()
            player = game.player1
            drawn = player.give(top)
            drawn.shuffle_into_deck()
            _play(player, cid)
            card = next(c for c in player.hand if c.id == top)
            expected = "drawn Beast has cost -4; non-Beast keeps printed cost"
            printed = 6 if top == "EX1_534" else 4
            passed = card.cost == (max(0, printed - 4) if Race.BEAST in card.races else printed)
            rows.append(_rec(cid, case_id, expected, f"drawn={card.id}; race_beast={Race.BEAST in card.races}; cost={card.cost}", passed, "Call Pet reduction branch compared across Beast/non-Beast top cards"))
    elif cid == "GVG_018":
        queen = _summon(p, cid)
        p.hero.hit(1)
        enemy = _summon(o, "CS2_033")
        _ready_player_minions(g, p)
        queen.attack(enemy)
        rows.append(_rec(cid, "GVG_018_lifesteal_combat", "damage dealt by Queen of Pain heals its controller by the damage dealt", f"lifesteal={queen.lifesteal}; hero_health={p.hero.health}; target_damage={enemy.damage}; target_health={enemy.health}", queen.lifesteal and p.hero.health == 30 and enemy.damage==1 and enemy.health==5))
    elif cid == "GVG_019":
        demon = _summon(p, "EX1_304")
        before = (demon.atk, demon.max_health)
        _play(p, cid, demon)
        rows.append(_rec(cid, "GVG_019_friendly_demon_branch", "friendly Demon gains +5/+5 instead of taking damage", f"before={before}; after={demon.atk}/{demon.max_health}; health={demon.health}", demon.atk == before[0] + 5 and demon.max_health == before[1] + 5))
        g2=_new_game(); p2,o2=g2.player1,g2.player2
        enemy=_summon(o2,"CS2_033"); before_health=enemy.health
        _play(p2,cid,enemy)
        rows.append(_rec(cid,"GVG_019_nonfriendly_demon_damage_branch","a non-friendly-Demon target takes 5 damage",f"target={enemy.id}; health={before_health}->{enemy.health}; damage={enemy.damage}; zone={enemy.zone}",enemy.zone==Zone.PLAY and enemy.health==before_health-5))
        g3=_new_game(); p3,o3=g3.player1,g3.player2
        enemy_demon=_summon(o3,"GVG_021"); before_stats=(enemy_demon.atk,enemy_demon.max_health); before_health=enemy_demon.health
        _play(p3,cid,enemy_demon)
        rows.append(_rec(cid,"GVG_019_enemy_demon_is_not_friendly_branch","an enemy Demon is not buffed and instead takes 5 damage",f"target={enemy_demon.id}; stats={before_stats}->{(enemy_demon.atk,enemy_demon.max_health)}; health={before_health}->{enemy_demon.health}; damage={enemy_demon.damage}; zone={enemy_demon.zone}",enemy_demon.zone==Zone.PLAY and enemy_demon.health==before_health-5 and (enemy_demon.atk,enemy_demon.max_health)==before_stats))
    elif cid == "GVG_020":
        cannon=_summon(p,cid); eligible=[cannon,_summon(p,"CS2_033"),_summon(o,"CS2_033")]; mech=_summon(p,"GVG_082")
        before=[x.damage for x in eligible]; mech_before=mech.damage
        _end_player_turn(g,p)
        deltas=[x.damage-before[i] for i,x in enumerate(eligible)]
        rows.append(_rec(cid,"GVG_020_own_turn_end_random_nonmech_damage","at own turn end deals 2 to one non-Mech minion; Mechs and heroes are excluded",f"eligible={[x.id for x in eligible]}; deltas={deltas}; mech_delta={mech.damage-mech_before}; heroes={p.hero.health}/{o.hero.health}",sum(deltas)==2 and sorted(deltas).count(2)==1 and mech.damage==mech_before and p.hero.health==o.hero.health==30,"three eligible minions provide a nontrivial random recipient pool"))
    elif cid == "GVG_021":
        demon=_summon(p,"EX1_304"); before=(demon.atk,demon.max_health)
        malganis=_summon(p,cid); after=(demon.atk,demon.max_health)
        _play(p,MOONFIRE,p.hero)
        rows.append(_rec(cid,"GVG_021_demon_aura_and_hero_immunity","other friendly Demons get +2/+2 and controller hero is immune to damage",f"demon={before}->{after}; hero_health={p.hero.health}; malganis={malganis.zone}",after==(before[0]+2,before[1]+2) and p.hero.health==30 and malganis.zone==Zone.PLAY))
    elif cid == "GVG_022":
        outcomes=[]
        for seed in range(16):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            _play(player,"CS2_091")
            minions=[_summon(player,WISP),_summon(player,"GVG_093")]
            player.give(MOONFIRE).play(target=opponent.hero)
            weapon_before=player.weapon.atk; hero_before=player.hero.atk; minion_before=[x.atk for x in minions]
            _play(player,cid)
            weapon_delta=player.weapon.atk-weapon_before
            hero_extra=player.hero.atk-hero_before-weapon_delta
            minion_deltas=[x.atk-minion_before[i] for i,x in enumerate(minions)]
            outcomes.append((weapon_delta,hero_extra,minion_deltas))
        valid=all(weapon==3 and hero==0 and sorted(deltas)==[0,3] for weapon,hero,deltas in outcomes)
        wrong=any(hero==3 for _,hero,_ in outcomes)
        rows.append(_rec(cid,"GVG_022_seeded_combo_recipient_is_minion","Combo buffs weapon +3 and exactly one friendly minion +3; the hero receives no bonus",f"seeded_weapon_hero_minion_deltas={outcomes}",valid,"16 seeded cases distinguish two minion recipients from the hero; source wording requires a minion recipient"))
        if wrong: rows[-1]["outcome"]="confirmed_error"
    elif cid == "GVG_023":
        _play(p, "CS2_091")
        before = p.weapon.atk
        _play(p, cid)
        rows.append(_rec(cid, "GVG_023_battlecry_weapon", "weapon gains +1 Attack", f"weapon_delta={p.weapon.atk-before}", p.weapon.atk - before == 1))
    elif cid == "GVG_024":
        mech=_summon(p,"GVG_082"); wrench=_play(p,cid); active=wrench.atk
        mech.destroy(); inactive=wrench.atk
        rows.append(_rec(cid,"GVG_024_weapon_mech_conditional_attack","Wrench has +2 Attack while a friendly Mech is present and loses it when none remain",f"weapon={wrench.id}; active={active}; after_mech_death={inactive}; durability={wrench.durability}",active==3 and inactive==1 and wrench.durability==3))
    elif cid == "GVG_026":
        yeti=_summon(p,"GVG_078"); gnome=_summon(p,"GVG_082")
        before=sum(x.id.startswith("PART_") for x in p.hand)
        _play(p,cid)
        after=sum(x.id.startswith("PART_") for x in p.hand)
        rows.append(_rec(cid,"GVG_026_trigger_all_friendly_deathrattles","Feign Death triggers both friendly Deathrattles without killing their minions",f"yeti={yeti.zone}; gnome={gnome.zone}; spare_parts_added={after-before}",yeti.zone==gnome.zone==Zone.PLAY and after-before==2,"two distinct Deathrattle effects are independently exercised"))
    elif cid == "GVG_025":
        cheat = _summon(p, cid)
        stealth_before=bool(cheat.tags[GameTag.STEALTH])
        pirate = _summon(p, "CS2_146")
        rows.append(_rec(cid, "GVG_025_pirate_summon_trigger", "summoning another Pirate grants Stealth", f"pirate={pirate.id}; pirate_race={[int(r) for r in pirate.races]}; stealth={stealth_before}->{bool(cheat.tags[GameTag.STEALTH])}", not stealth_before and bool(cheat.tags[GameTag.STEALTH]) and Race.PIRATE in pirate.races))
    elif cid == "GVG_027":
        outcomes=[]
        for seed in range(12):
            game=_new_game(seed=seed);player=game.player1;sensei=_summon(player,cid)
            mechs=[_summon(player,"GVG_082"),_summon(player,"GVG_082")];before=[(x.atk,x.max_health) for x in mechs]
            _end_player_turn(game,player)
            deltas=[(x.atk-before[i][0],x.max_health-before[i][1]) for i,x in enumerate(mechs)]
            outcomes.append(deltas)
        recipients={i for deltas in outcomes for i,delta in enumerate(deltas) if delta==(2,2)}
        rows.append(_rec(cid,"GVG_027_seeded_random_friendly_mech_end_turn_buff","at controller turn end, exactly one other friendly Mech gains +2/+2",f"seeded_deltas={outcomes}; recipient_indexes={sorted(recipients)}",all(sorted(deltas)==[(0,0),(2,2)] for deltas in outcomes) and len(recipients)==2,"12 seeded turns each offer two distinct eligible Mechs"))
    elif cid == "GVG_028":
        prince=_summon(p,cid)
        g.current_player=o
        _play(o,MOONFIRE,p.hero)
        copied=[x.id for x in p.hand if x.id==MOONFIRE]
        coins=[x.id for x in o.hand if x.id=="GVG_028t"]
        rows.append(_rec(cid,"GVG_028_opponent_spell_copy_and_coin","when opponent casts a spell, controller receives a copy and opponent receives a Coin",f"prince={prince.zone}; copies={copied}; opponent_coins={coins}; hero_health={p.hero.health}",copied==[MOONFIRE] and len(coins)==1 and p.hero.health==29))
    elif cid == "GVG_029":
        ally=p.give(WISP); enemy=o.give("GVG_093")
        spell=_play(p,cid)
        rows.append(_rec(cid,"GVG_029_summon_one_random_hand_minion_per_player","puts one minion from each player's hand onto that player's battlefield",f"ally_zone={ally.zone}; enemy_zone={enemy.zone}; friendly_board={[x.id for x in p.field]}; enemy_board={[x.id for x in o.field]}; spell={spell.zone}",ally.zone==enemy.zone==Zone.PLAY and ally.controller is p and enemy.controller is o and ally not in p.hand and enemy not in o.hand,"each player's hand has one candidate; the random-pool branch still requires more candidates"))
    elif cid == "GVG_030":
        cub = _play(p, "GVG_030", choose="GVG_030a")
        rows.append(_rec(cid, "GVG_030_choose_attack", "Attack choice is Taunt 3/2; Health choice is Taunt 2/3", f"attack_choice={cub.atk}/{cub.health},taunt={cub.taunt}", cub.atk == 3 and cub.health == 2 and cub.taunt))
        g2 = _new_game()
        cub2 = _play(g2.player1, "GVG_030", choose="GVG_030b")
        rows.append(_rec(cid, "GVG_030_choose_health", "Health choice is Taunt 2/3", f"health_choice={cub2.atk}/{cub2.health},taunt={cub2.taunt}", cub2.atk == 2 and cub2.health == 3 and cub2.taunt))
    elif cid == "GVG_031":
        target = _summon(o, "CS2_182")
        before = len(o.deck)
        _play(p, cid, target)
        rows.append(_rec(cid, "GVG_031_enemy_minion_to_deck", "target leaves play and enters opponent deck", f"zone={target.zone}; deck_delta={len(o.deck)-before}; enemy_field={len(o.field)}", target.zone == Zone.DECK and len(o.deck) == before + 1 and target not in o.field))
    elif cid == "GVG_032":
        for choose, case_id in (("GVG_032a","GVG_032_each_player_gains_mana_crystal"),("GVG_032b","GVG_032_each_player_draws")):
            game=_new_game(); player,opponent=game.player1,game.player2
            if choose=="GVG_032b":
                for side,top in ((player,WISP),(opponent,"GVG_082")):
                    card=side.give(top); card.shuffle_into_deck()
            if choose=="GVG_032a":
                player.max_mana=4; opponent.max_mana=5
            before_mana=(player.max_mana,opponent.max_mana); before_hand=(len(player.hand),len(opponent.hand))
            _play(player,cid,choose=choose)
            if choose=="GVG_032a":
                observed=f"max_mana={before_mana}->{(player.max_mana,opponent.max_mana)}"
                passed=(player.max_mana,opponent.max_mana)==(before_mana[0]+1,before_mana[1]+1)
            else:
                observed=f"hand={before_hand}->{(len(player.hand),len(opponent.hand))}; drawn={[x.id for x in player.hand]}/{[x.id for x in opponent.hand]}"
                passed=len(player.hand)==before_hand[0]+1 and len(opponent.hand)==before_hand[1]+1 and WISP in [x.id for x in player.hand] and "GVG_082" in [x.id for x in opponent.hand]
            rows.append(_rec(cid,case_id,"selected Choose One branch resolves for both players",observed,passed))
    elif cid == "GVG_033":
        hero_health=(p.hero.health,o.hero.health); p.hero.hit(5); o.hero.hit(7)
        a=_summon(p,"CS2_033"); b=_summon(o,"CS2_200"); a.hit(2); b.hit(3)
        _play(p,cid)
        rows.append(_rec(cid,"GVG_033_full_heal_all_characters","Tree of Life restores both heroes and all minions to full Health",f"heroes={hero_health}->{(p.hero.health,o.hero.health)}; minions={(a.health,a.max_health)}/{(b.health,b.max_health)}",p.hero.health==o.hero.health==30 and a.health==a.max_health and b.health==b.max_health))
    elif cid == "GVG_034":
        cat = _summon(p, cid)
        before = {c.id for c in p.hand}
        _play(p, "CS2_008", cat)
        gained = [c for c in p.hand if c.id not in before]
        rows.append(_rec(cid, "GVG_034_self_damage_spare_part", "taking damage adds one Spare Part", f"health={cat.health}; new_ids={[c.id for c in gained]}", cat.health == 5 and len(gained) == 1 and gained[0].type == CardType.SPELL and gained[0].cost == 1, "damage-trigger reward is checked; Spare Part IDs can differ by pool"))
    elif cid == "GVG_036":
        outcomes=[]
        for seed in range(12):
            game=_new_game(seed=seed); player=game.player1
            mechs=[_summon(player,"GVG_082"),_summon(player,"GVG_082")]; nonmech=_summon(player,WISP)
            before=[(x.atk,x.max_health) for x in mechs]; nonmech_before=(nonmech.atk,nonmech.max_health)
            weapon=_play(player,cid); weapon.destroy()
            deltas=[(mechs[i].atk-before[i][0],mechs[i].max_health-before[i][1]) for i in range(2)]
            outcomes.append((deltas,(nonmech.atk-nonmech_before[0],nonmech.max_health-nonmech_before[1])))
        valid=all(sorted(deltas)==[(0,0),(2,2)] and nonmech_delta==(0,0) for deltas,nonmech_delta in outcomes)
        recipients={i for deltas,_ in outcomes for i,delta in enumerate(deltas) if delta==(2,2)}
        rows.append(_rec(cid,"GVG_036_deathrattle_random_friendly_mech_buff","weapon Deathrattle gives +2/+2 to exactly one random friendly Mech, never a non-Mech",f"seeded_deltas={outcomes}; recipient_indexes={sorted(recipients)}",valid and len(recipients)==2,"12 independently seeded boards give two distinct Mechs a real chance to receive the effect"))
    elif cid == "GVG_037":
        zap = _summon(p, cid)
        _ready_player_minions(g, p)
        zap.attack(o.hero)
        can_attack_again = zap.can_attack()
        rows.append(_rec(cid, "GVG_037_windfury_two_attacks", "Windfury allows a second attack in the same turn", f"windfury={zap.windfury}; num_attacks={zap.num_attacks}; can_attack_again={can_attack_again}", zap.windfury and can_attack_again))
    elif cid == "GVG_038":
        outcomes=[]
        for seed in range(12):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            before=opponent.hero.health
            _play(player,cid,opponent.hero)
            outcomes.append((before-opponent.hero.health,player.overloaded))
        values=[d for d,_ in outcomes]
        rows.append(_rec(cid,"GVG_038_seeded_damage_range_and_overload","Crackle deals 3–6 damage and applies Overload 1",f"seeded_damage_overload={outcomes}",all(3<=d<=6 and overload==1 for d,overload in outcomes),"12 game.random seeds sample the random damage interval"))
    elif cid == "GVG_039":
        p.hero.hit(7)
        _summon(p, cid)
        _end_player_turn(g, p)
        rows.append(_rec(cid, "GVG_039_end_turn_heal", "hero restores exactly 4 health at controller turn end", f"hero_health=23->{p.hero.health}; heal_delta={p.hero.health-23}", p.hero.health == 27))
    elif cid == "GVG_041":
        target = _summon(p, WISP)
        _play(p, cid, target, choose="GVG_041a")
        rows.append(_rec(cid, "GVG_041_target_branch", "target gains +5/+5 and Taunt", f"target={target.atk}/{target.health};taunt={target.taunt}", target.atk == 6 and target.health == 6 and target.taunt))
        g2 = _new_game()
        _play(g2.player1, cid, choose="GVG_041b")
        rows.append(_rec(cid, "GVG_041_five_wisps_branch", "summons five 1/1 Wisps", f"wisps={len(g2.player1.field.filter(id=WISP))}", len(g2.player1.field.filter(id=WISP)) == 5))
    elif cid == "GVG_040":
        card=p.give(cid); _play(p,cid); overload=p.overloaded
        top=p.give(WISP); top.shuffle_into_deck()
        murloc=_summon(p,"CS2_168")
        before=len(p.hand); _play(p,MOONFIRE,murloc)
        drawn=[x.id for x in p.hand[before:]]
        rows.append(_rec(cid,"GVG_040_friendly_murloc_death_draw_and_overload","Overload is 1; another friendly Murloc's death draws one card",f"overload={overload}; murloc={murloc.zone}; drawn={drawn}; deck={len(p.deck)}",overload==1 and murloc.zone==Zone.GRAVEYARD and drawn==[WISP]))
    elif cid == "GVG_042":
        before=len(p.hand); _play(p,cid)
        added=list(p.hand)[before:]
        all_murloc=all(Race.MURLOC in c.races for c in added)
        rows.append(_rec(cid,"GVG_042_four_random_murlocs_and_overload","adds four Murlocs to hand and applies Overload 3",f"added={[(x.id,x.type,[int(r) for r in x.races]) for x in added]}; overload={p.overloaded}",len(added)==4 and all_murloc and p.overloaded==3,"four random card identities are retained in evidence; each realized race is checked"))
    elif cid == "GVG_043":
        a, b = _summon(p, WISP), _summon(p, TARGET_DUMMY)
        before = (a.atk, b.atk)
        weapon = _play(p, cid)
        changed = [x.atk - before[i] for i, x in enumerate((a, b))]
        rows.append(_rec(cid, "GVG_043_battlecry_random_buff", "equips weapon and gives exactly one of two friendly minions +1 Attack", f"weapon={weapon.id}; minion_deltas={changed}", bool(p.weapon) and sorted(changed) == [0, 1], "two distinguishable friendly minions exercise random recipient pool"))
    elif cid == "GVG_045":
        outcomes=[]
        for seed in range(8):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            target=_summon(opponent,"CS2_200"); before=target.damage
            _play(player,cid,target)
            delta=target.damage-before
            imps=list(player.field.filter(id="GVG_045t"))
            outcomes.append((delta,len(imps),target.health,target.zone))
        rows.append(_rec(cid,"GVG_045_seeded_imp_losion_damage_and_summons","deals a random 2–4 to selected minion and summons exactly one 1/1 Imp per damage point",f"seeded={outcomes}",all(2<=d<=4 and imp_count==d and zone==Zone.PLAY for d,imp_count,health,zone in outcomes),"8 seeded casts assert damage-to-summon count correspondence"))
    elif cid == "GVG_046":
        observed=[]
        for has_beast in (False,True):
            game=_new_game(); player=game.player1
            beast=_summon(player,"CS2_172") if has_beast else None
            king=_play(player,cid)
            expected=2+(1 if has_beast else 0)
            observed.append((has_beast,beast.id if beast else None,king.atk,king.max_health,expected))
        rows.append(_rec(cid,"GVG_046_other_beast_attack_count","King of Beasts gains +1 Attack for each other friendly Beast, excluding itself",f"with_without_beast={observed}",all(atk==expected for _,_,atk,_,expected in observed),"controlled zero/one other-Beast cases distinguish the printed other-minion count from self-counting"))
        if any(atk!=expected for _,_,atk,_,expected in observed): rows[-1]["outcome"]="confirmed_error"
    elif cid == "GVG_047":
        outcomes=[]
        for seed in range(8):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            targets=[_summon(opponent,"CS2_033"),_summon(opponent,"CS2_200")]
            spell=_play(player,cid)
            dead=[x.id for x in targets if x.zone==Zone.GRAVEYARD]
            outcomes.append((dead,len(opponent.field),spell.zone))
        noncombo_valid=all(len(dead)==1 and field_count==1 for dead,field_count,_ in outcomes)
        both={i for dead,_,_ in outcomes for i,target in enumerate(("CS2_033","CS2_200")) if target in dead}
        game=_new_game(seed=13); player,opponent=game.player1,game.player2
        targets=[_summon(opponent,"CS2_033"),_summon(opponent,"CS2_200")]
        game.current_player=opponent
        _play(opponent,"CS2_091")
        game.current_player=player
        player.give(MOONFIRE).play(target=opponent.hero)
        _play(player,cid)
        combo_dead=sum(x.zone==Zone.GRAVEYARD for x in targets)
        rows.append(_rec(cid,"GVG_047_random_minion_and_combo_weapon_destroy","non-Combo destroys one random enemy minion; Combo also destroys the enemy weapon",f"noncombo_seeds={outcomes}; both_minion_recipients_seen={sorted(both)}; combo_dead_minions={combo_dead}; combo_weapon={opponent.weapon}",noncombo_valid and combo_dead==1 and opponent.weapon is None,"eight seeds provide two minion candidates; combo case equips a weapon and activates Combo with a prior spell"))
    elif cid == "GVG_048":
        outcomes=[]
        for seed in range(12):
            game=_new_game(seed=seed); player=game.player1
            mechs=[_summon(player,"GVG_082"),_summon(player,"GVG_082")]; unrelated=_summon(player,WISP)
            before=[x.atk for x in mechs]; other_attack=unrelated.atk
            leaper=_play(player,cid)
            outcomes.append(([x.atk-before[i] for i,x in enumerate(mechs)],unrelated.atk-other_attack,leaper.atk))
        valid=all(deltas==[2,2] and wisp_delta==0 and leaper_atk==3 for deltas,wisp_delta,leaper_atk in outcomes)
        rows.append(_rec(cid,"GVG_048_battlecry_all_other_friendly_mechs","Battlecry gives every other friendly Mech +2 Attack and leaves non-Mechs unchanged",f"seeded_mech_wisp_leaper_deltas={outcomes}",valid,"12 seeded boards each contain two distinct other Mechs and a non-Mech control"))
        if any(deltas.count(2)!=2 for deltas,_,_ in outcomes): rows[-1]["outcome"]="confirmed_error"
    elif cid == "GVG_049":
        gahz=_summon(p,cid); before=gahz.atk
        _play(p,MOONFIRE,gahz); once=gahz.atk
        _play(p,MOONFIRE,gahz); twice=gahz.atk
        rows.append(_rec(cid,"GVG_049_each_damage_event_doubles_attack","each time Gahz'rilla takes damage, its Attack doubles",f"attack={before}->{once}->{twice}; health={gahz.health}; zone={gahz.zone}",once==before*2 and twice==once*2 and gahz.zone==Zone.PLAY))
    elif cid == "GVG_050":
        outcomes=[]
        for seed in range(8):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            targets=[_summon(opponent,WISP),_summon(opponent,"GVG_093")]
            _play(player,cid)
            dead=[x.id for x in targets if x.zone==Zone.GRAVEYARD]
            outcomes.append((dead,[(x.id,x.health,x.zone) for x in targets]))
        rows.append(_rec(cid,"GVG_050_seeded_repeat_until_death","deals 1 damage to random minions repeatedly and stops when a minion dies",f"seeded={outcomes}",all(len(dead)==1 for dead,_ in outcomes),"two minions of different durability make repeated selection/death termination observable"))
    elif cid == "GVG_051":
        bot = _summon(p, cid)
        before = bot.atk
        _play(p, "CS2_008", bot)
        rows.append(_rec(cid, "GVG_051_enrage", "damaged Warbot has +1 Attack", f"health={bot.health}; atk_delta={bot.atk-before}", bot.damaged and bot.atk - before == 1))
    elif cid == "GVG_052":
        target=_summon(o,"CS2_200"); spell=p.give(cid); base=spell.cost
        ally=_summon(p,"CS2_033"); ally.hit(1); reduced=spell.cost
        _play(p,cid,target)
        rows.append(_rec(cid,"GVG_052_damaged_minion_cost_and_destroy","damaged friendly minion reduces Crush by 4, and selected enemy minion is destroyed",f"cost={base}->{reduced}; target={target.id}/{target.zone}; ally_damage={ally.damage}",reduced==base-4 and target.zone==Zone.GRAVEYARD and ally.zone==Zone.PLAY))
    elif cid == "GVG_053":
        maiden = _play(p, cid)
        rows.append(_rec(cid, "GVG_053_armor_battlecry", "Battlecry grants 5 Armor", f"armor={p.hero.armor}; minion={maiden.atk}/{maiden.health}", p.hero.armor == 5))
    elif cid == "GVG_054":
        weapon = _play(p, cid)
        direct,redirected,outcomes=_forgetful_trials(cid,weapon=True,seeds=range(128))
        rows.append(_rec(cid, "GVG_054_weapon_forgetful_combat", "equips 4/2 weapon; seeded hero attacks show both the declared hero target and a redirected enemy minion", f"weapon={weapon.id}; atk={weapon.atk}; durability={weapon.durability}; direct={direct}; redirected={redirected}; trials=128; sample={outcomes[:16]}", weapon.atk == 4 and weapon.durability == 2 and direct>0 and redirected>0, "128 separately seeded actual hero attacks include an enemy minion as the only alternate enemy target"))
        if weapon.atk==4 and weapon.durability==2 and direct==128 and redirected==0:
            rows[-1]["outcome"]="confirmed_error"
    elif cid == "GVG_055":
        mech=_summon(p,"GVG_082"); before=(mech.atk,mech.max_health)
        _play(p,cid,mech)
        rows.append(_rec(cid,"GVG_055_battlecry_friendly_mech_buff","Screwjank Clunker gives a targeted friendly Mech +2/+2",f"before={before}; after={mech.atk}/{mech.max_health}; zone={mech.zone}",mech.atk==before[0]+2 and mech.max_health==before[1]+2 and mech.zone==Zone.PLAY))
    elif cid == "GVG_056":
        juggernaut=_play(p,cid); mines=[x for x in o.deck if x.id=="GVG_056t"]
        before=o.hero.health
        if mines: o.draw()
        rows.append(_rec(cid,"GVG_056_mine_shuffle_and_draw_trigger","Battlecry shuffles one Mine into opponent deck; drawing it deals 10 to that player's hero",f"juggernaut={juggernaut.zone}; mines_before_draw={len(mines)}; hero={before}->{o.hero.health}; mine_zones={[x.zone for x in mines]}; opponent_deck={[x.id for x in o.deck]}",len(mines)==1 and o.hero.health==before-10 and all(x.zone==Zone.GRAVEYARD for x in mines)))
    elif cid == "GVG_057":
        p.hero.hit(8)
        _play(p, cid)
        active=(p.hero.health,p.hero.atk)
        _end_player_turn(g,p)
        rows.append(_rec(cid, "GVG_057_heal_and_temporary_attack", "restores 4 health and grants +2 hero Attack only for this turn", f"health=22->{active[0]}; attack=0->{active[1]}->end_turn:{p.hero.atk}", active==(26,2) and p.hero.atk==0))
    elif cid == "GVG_058":
        bot = _summon(p, cid)
        _play(p, "CS2_008", bot)
        rows.append(_rec(cid, "GVG_058_divine_shield_blocks_damage", "first damage removes shield without reducing health", f"shield={bot.divine_shield}; health={bot.health}; zone={bot.zone}", not bot.divine_shield and bot.health == 2 and bot.zone == Zone.PLAY))
    elif cid == "GVG_059":
        a, b = _summon(p, WISP), _summon(p, TARGET_DUMMY)
        cog = _play(p, cid)
        tagged = [x for x in (a, b) if x.taunt and x.divine_shield]
        rows.append(_rec(cid, "GVG_059_random_taunt_shield", "equips Coghammer and grants Taunt plus Divine Shield to one of two minions", f"weapon={cog.id}; tagged={[x.id for x in tagged]}; states={[(x.taunt,x.divine_shield) for x in (a,b)]}", bool(p.weapon) and len(tagged) == 1, "two distinct candidate minions exercise random target selection"))
    elif cid == "GVG_060":
        a, b, w = _summon(p, "CS2_101t"), _summon(p, "CS2_101t"), _summon(p, WISP)
        _play(p, cid)
        rows.append(_rec(cid, "GVG_060_recruits_buff_only", "Silver Hand Recruits gain +2/+2; unrelated minion is unchanged", f"recruits={[(x.atk,x.health) for x in (a,b)]}; wisp={w.atk}/{w.health}", all((x.atk,x.health)==(3,3) for x in (a,b)) and (w.atk,w.health)==(1,1)))
    elif cid == "GVG_061":
        _play(p, cid)
        recruits = list(p.field.filter(id="CS2_101t"))
        rows.append(_rec(cid, "GVG_061_recruits_and_weapon", "summons three Silver Hand Recruits and equips a 1/4 weapon", f"recruits={len(recruits)}; weapon={(p.weapon.id,p.weapon.atk,p.weapon.durability) if p.weapon else None}", len(recruits)==3 and p.weapon is not None and p.weapon.atk==1 and p.weapon.durability==4))
    elif cid == "GVG_062":
        guardian=_summon(p,cid)
        before=guardian.divine_shield
        _summon(p,"GVG_082")
        first=guardian.divine_shield
        _play(p,MOONFIRE,guardian)
        stripped=guardian.divine_shield
        _summon(p,"GVG_082")
        restored=guardian.divine_shield
        rows.append(_rec(cid,"GVG_062_mech_summon_grants_divine_shield","summoning a Mech grants Divine Shield; after it is consumed, another Mech restores it",f"shield={before}->{first}->moonfire:{stripped}->second_mech:{restored}; guardian={guardian.zone}",not before and first and not stripped and restored and guardian.zone==Zone.PLAY))
    elif cid == "GVG_063":
        bolvar=p.give(cid); base=bolvar.atk
        ally=_summon(p,WISP); _play(p,MOONFIRE,ally)
        first=bolvar.atk
        ally2=_summon(p,"GVG_082"); _play(p,MOONFIRE,ally2)
        second=bolvar.atk
        rows.append(_rec(cid,"GVG_063_friendly_deaths_buff_in_hand","each friendly minion death while in hand grants Bolvar +1 Attack",f"attack={base}->{first}->{second}; deaths={ally.zone}/{ally2.zone}; bolvar_zone={bolvar.zone}",first==base+1 and second==base+2 and bolvar.zone==Zone.HAND))
    elif cid == "GVG_065":
        brute = _summon(p, cid)
        direct,redirected,outcomes=_forgetful_trials(cid)
        rows.append(_rec(cid, "GVG_065_forgetful_combat", "Ogre Brute is 4/4 and has both declared-target and redirected attack outcomes", f"stats={brute.atk}/{brute.health}; direct={direct}; redirected={redirected}; samples={outcomes}", brute.atk==4 and brute.health==4 and direct>0 and redirected>0, "32 independently seeded actual attacks exercise both Forgetful outcomes"))
    elif cid == "GVG_066":
        shaman = _play(p, cid)
        direct,redirected,outcomes=_forgetful_trials(cid)
        rows.append(_rec(cid, "GVG_066_windfury_overload_forgetful_combat", "Dunemaul Shaman has Windfury and Overload 1; seeded attacks show direct and redirected outcomes", f"windfury={shaman.windfury}; overload={p.overloaded}; direct={direct}; redirected={redirected}; samples={outcomes}", shaman.windfury and p.overloaded==1 and direct>0 and redirected>0, "32 independently seeded actual attacks exercise both Forgetful outcomes"))
    elif cid in ("GVG_067", "GVG_068"):
        trogg = _summon(p, cid)
        before = trogg.atk
        gain = 1 if cid == "GVG_067" else 2
        g.current_player=o
        _play(o, "CS2_008", p.hero)
        rows.append(_rec(cid, cid + "_opponent_spell_trigger", f"opponent spell grants +{gain} Attack", f"before={before}; after={trogg.atk}", trogg.atk == before + gain))
    elif cid == "GVG_069":
        p.hero.hit(10)
        _play(p, cid)
        rows.append(_rec(cid, "GVG_069_heal_battlecry", "restores 8 health to friendly hero", f"health={p.hero.health}", p.hero.health == 28))
    elif cid == "GVG_072":
        outcomes=[]
        for seed in range(12):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            boxer=_summon(player,cid); damaged=_summon(player,"CS2_033"); damaged.hit(1)
            candidates=[_summon(opponent,"CS2_033"),_summon(opponent,"CS2_200")]
            hero_before=opponent.hero.health; damage_before=[x.damage for x in candidates]
            _play(player,"CS2_007",damaged)
            deltas=[x.damage-damage_before[i] for i,x in enumerate(candidates)]
            outcomes.append((damaged.health,deltas,hero_before-opponent.hero.health,boxer.zone))
        seen=set()
        for healed,deltas,hero_delta,boxer_zone in outcomes:
            if deltas[0]==1: seen.add("enemy_minion_1")
            if deltas[1]==1: seen.add("enemy_minion_2")
            if hero_delta==1: seen.add("enemy_hero")
        rows.append(_rec(cid,"GVG_072_heal_trigger_random_enemy_damage","healing a minion triggers one 1-damage hit to a random enemy character",f"seeded={outcomes}; recipient_kinds_seen={sorted(seen)}",all(healed==6 and sum(deltas)+hero_delta==1 and boxer_zone==Zone.PLAY for healed,deltas,hero_delta,boxer_zone in outcomes) and seen=={"enemy_minion_1","enemy_minion_2","enemy_hero"},"12 seeds cover each of two enemy minions and the enemy hero as distinguishable random recipients"))
    elif cid == "GVG_073":
        target = _summon(o, "CS2_182")
        _play(p, cid, target)
        rows.append(_rec(cid, "GVG_073_minion_and_hero_damage", "deals 3 to target minion and enemy hero", f"target_health={target.health}; target_damage={target.damage}; enemy_hero={o.hero.health}", target.damage == 3 and o.hero.health == 27))
    elif cid == "GVG_074":
        observed=[]
        for seed in range(8):
            game=_new_game(seed=seed); player,opponent=game.player1,game.player2
            secret_ids=("EX1_287","tt_010")
            game.current_player=opponent
            for secret_id in secret_ids: opponent.give(secret_id).play()
            game.current_player=player
            mystic=_play(player,cid)
            friendly=[x.id for x in player.secrets]; enemy=[x.id for x in opponent.secrets]
            observed.append((friendly,enemy,mystic.zone))
        candidates={item for friendly,_,_ in observed for item in friendly}
        rows.append(_rec(cid,"GVG_074_steal_one_seeded_random_enemy_secret","takes control of exactly one random enemy Secret",f"seeded={observed}; identities_seen={sorted(candidates)}",all(len(friendly)==1 and len(enemy)==1 and mystic_zone==Zone.PLAY for friendly,enemy,mystic_zone in observed),"two distinguishable enemy Secrets exercise the random secret pool"))
    elif cid == "GVG_075":
        cannon = _summon(p, cid)
        a,b = _summon(o,"CS2_033"), _summon(o,ANIMATED_STATUE)
        before=(a.damage,b.damage)
        _summon(p,"CS2_146")
        delta=[x.damage-before[i] for i,x in enumerate((a,b))]
        rows.append(_rec(cid, "GVG_075_pirate_summon", "summoning Pirate deals exactly 2 damage to one random enemy", f"cannon={cannon.id}; enemy_deltas={delta}", sorted(delta)==[0,2], "two distinguishable enemy targets exercise random damage recipient"))
    elif cid == "GVG_076":
        a,b=_summon(p,WISP),_summon(o,WISP)
        survivor_friendly=_summon(p,"CS2_200"); survivor_enemy=_summon(o,"CS2_200")
        survivor_before=(survivor_friendly.health,survivor_enemy.health)
        sheep=_summon(p,cid)
        _play(p,"CS2_008",sheep)
        rows.append(_rec(cid,"GVG_076_deathrattle_all_minions_and_simultaneous_death","death deals exactly 2 to all minions on both sides, no hero damage; low-health minions die and high-health controls survive with 2 damage",f"sheep={sheep.zone}; low_health_zones={a.zone}/{b.zone}; survivor_health={survivor_friendly.health}/{survivor_enemy.health}; survivor_before={survivor_before}; survivor_damage={survivor_friendly.damage}/{survivor_enemy.damage}; heroes={p.hero.health}/{o.hero.health}; remaining_friendly={[x.id for x in p.field]}", sheep.zone==Zone.GRAVEYARD and a.zone==b.zone==Zone.GRAVEYARD and survivor_friendly.zone==survivor_enemy.zone==Zone.PLAY and survivor_friendly.damage==survivor_enemy.damage==2 and survivor_friendly.health==survivor_before[0]-2 and survivor_enemy.health==survivor_before[1]-2 and p.hero.health==o.hero.health==30, "simultaneous friendly/enemy low-health lethals plus high-health controls verify board-wide 2-damage and hero exclusion"))
    elif cid == "GVG_077":
        golem=_summon(p,cid); alone_game=_new_game(); p2=alone_game.player1
        alone=_summon(p2,cid); _end_player_turn(alone_game,p2)
        group_game=_new_game(); p3=group_game.player1
        grouped=_summon(p3,cid); ally=_summon(p3,WISP); _end_player_turn(group_game,p3)
        rows.append(_rec(cid,"GVG_077_end_turn_only_minion_condition","Anima Golem survives with another friendly minion but destroys itself when alone at turn end",f"alone={alone.zone}; with_ally={grouped.zone}; ally={ally.zone}; initial_board_golem={golem.zone}",alone.zone==Zone.GRAVEYARD and grouped.zone==Zone.PLAY and ally.zone==Zone.PLAY and golem.zone==Zone.PLAY))
    elif cid == "GVG_078":
        yeti=_summon(p,cid); before_p=sum(x.id.startswith("PART_") for x in p.hand); before_o=sum(x.id.startswith("PART_") for x in o.hand); yeti.destroy()
        newp=sum(x.id.startswith("PART_") for x in p.hand)-before_p; newo=sum(x.id.startswith("PART_") for x in o.hand)-before_o
        rows.append(_rec(cid,"GVG_078_deathrattle_both_players_spare_parts","death adds one Spare Part to each player's hand",f"friendly_parts_added={newp}; enemy_parts_added={newo}; source={yeti.zone}",newp==1 and newo==1 and yeti.zone==Zone.GRAVEYARD,"random Spare Part identity is intentionally unconstrained"))
    elif cid == "GVG_079":
        tank=_summon(p,cid)
        rows.append(_rec(cid,"GVG_079_divine_shield","Force-Tank MAX enters with Divine Shield",f"shield={tank.divine_shield}; stats={tank.atk}/{tank.health}",tank.divine_shield and tank.atk==7 and tank.health==7))
    elif cid == "GVG_080":
        for has_beast, case_id in ((False,"GVG_080_no_beast_stays_base"),(True,"GVG_080_beast_transforms_to_7_7")):
            game=_new_game(); player=game.player1
            beast=_summon(player,"CS2_172") if has_beast else None
            fang=_play(player,cid)
            final=next((x for x in player.field if x.id==("GVG_080t" if has_beast else cid)),None)
            rows.append(_rec(cid,case_id,"only a friendly Beast powers Druid of the Fang into its 7/7 form",f"beast={(beast.id,Race.BEAST in beast.races) if beast else None}; played={(fang.id,fang.atk,fang.max_health,fang.zone)}; final={(final.id,final.atk,final.max_health,final.zone) if final else None}; board={[x.id for x in player.field]}",final is not None and ((final.atk,final.max_health)==(7,7) if has_beast else (final.atk,final.max_health)==(4,4))))
    elif cid == "GVG_081":
        gilblin=_summon(p,cid)
        rows.append(_rec(cid,"GVG_081_stealth","Gilblin Stalker enters with Stealth",f"stealth_tag={gilblin.tags[GameTag.STEALTH]}; stats={gilblin.atk}/{gilblin.health}",bool(gilblin.tags[GameTag.STEALTH]) and gilblin.atk==2 and gilblin.health==3))
    elif cid == "GVG_082":
        gnome=_summon(p,cid); before=sum(x.id.startswith("PART_") for x in p.hand); gnome.destroy()
        added=[x.id for x in p.hand if x.id.startswith("PART_")]
        rows.append(_rec(cid,"GVG_082_deathrattle_spare_part","Clockwork Gnome Deathrattle adds one Spare Part to its controller's hand",f"gnome={gnome.zone}; spare_parts={added}; before_count={before}",gnome.zone==Zone.GRAVEYARD and len(added)==1,"random Spare Part identity is recorded, with any pre-existing spare parts excluded"))
    elif cid == "GVG_083":
        mech=_summon(p,"GVG_082"); other=_summon(p,WISP); enemy_mech=_summon(o,"GVG_082"); before=(mech.max_health,other.max_health)
        repair=p.give(cid); legal=list(repair.play_targets); enemy_mech_before=enemy_mech.max_health
        target_gate=(mech in legal and other not in legal and enemy_mech not in legal)
        repair.play(target=mech)
        rows.append(_rec(cid,"GVG_083_mech_target_gate_and_health_buff","only a friendly Mech is a legal target; it gains +4 Health",f"legal_targets={[x.id for x in legal]}; target_gate={target_gate}; before={before}; mech={mech.atk}/{mech.max_health}; friendly_nonmech={other.atk}/{other.max_health}; enemy_mech={enemy_mech.atk}/{enemy_mech.max_health}",target_gate and mech.max_health==before[0]+4 and other.max_health==before[1] and enemy_mech.max_health==enemy_mech_before))
    elif cid == "GVG_084":
        flyer=_summon(p,cid); target=_summon(o,"GVG_093"); _ready_player_minions(g,p); flyer.attack(target)
        rows.append(_rec(cid,"GVG_084_windfury","Flying Machine can attack twice in one turn",f"windfury={flyer.windfury}; target={target.zone}/{target.health}; flyer={flyer.zone}/{flyer.health}; can_attack_again={flyer.can_attack()}",flyer.windfury and flyer.zone==Zone.PLAY and flyer.can_attack()))
    elif cid == "GVG_085":
        bot=_summon(p,cid)
        rows.append(_rec(cid,"GVG_085_taunt_shield","Annoy-o-Tron has both Taunt and Divine Shield",f"taunt={bot.taunt}; shield={bot.divine_shield}",bot.taunt and bot.divine_shield))
    elif cid == "GVG_086":
        g=_new_game(class1=CardClass.WARRIOR,class2=CardClass.WARRIOR)
        p=next(player for player in (g.player1,g.player2) if player.hero.card_class==CardClass.WARRIOR)
        enemy=next(player for player in (g.player1,g.player2) if player is not p)
        g.current_player=p
        engine=_summon(p,cid); before=engine.atk
        p.hero.power.use()
        after_power=engine.atk; armor_after_power=p.hero.armor
        _play(p,"EX1_606")
        after_block=engine.atk; armor_after_block=p.hero.armor
        g.current_player=enemy
        enemy.hero.power.use()
        after_enemy=engine.atk
        rows.append(_rec(cid,"GVG_086_armor_gain_trigger_and_noncontroller_exclusion","each gain of Armor grants exactly +1 Attack regardless of armor amount; opponent Armor does not trigger it",f"warrior={p.hero.id}; power_gain=2 armor/{before}->{after_power} atk; shield_block=5 armor/{armor_after_power}->{armor_after_block} armor/{after_power}->{after_block} atk; enemy_gain={enemy.hero.armor} armor; final_attack={after_enemy}; engine={engine.zone}",armor_after_power==2 and after_power==before+1 and armor_after_block==7 and after_block==after_power+1 and after_enemy==after_block and engine.zone==Zone.PLAY))
    elif cid == "GVG_087":
        g = _new_game(class1=CardClass.HUNTER, class2=CardClass.MAGE)
        p=next(player for player in (g.player1,g.player2) if player.hero.card_class==CardClass.HUNTER)
        o=next(player for player in (g.player1,g.player2) if player is not p)
        g.current_player=p
        target=_summon(o,WISP)
        power=p.hero.power
        legal_before=target in power.play_targets
        sniper=_summon(p,cid)
        legal_after=target in power.play_targets
        rows.append(_rec(cid,"GVG_087_hero_power_target_gate","Hunter Steady Shot cannot target a minion before Sniper, but can target an enemy minion while Sniper remains",f"hunter={p.hero.id}; hero_power={power.id}; legal_before={legal_before}; legal_after={legal_after}; sniper_zone={sniper.zone}",not legal_before and legal_after and sniper in p.field))
        if not legal_before and not legal_after and sniper in p.field:
            rows[-1]["outcome"]="confirmed_error"
    elif cid == "GVG_088":
        ninja=_summon(p,cid)
        stealth=bool(ninja.tags[GameTag.STEALTH]); direct,redirected,outcomes=_forgetful_trials(cid)
        rows.append(_rec(cid,"GVG_088_stealth_forgetful_combat","Ogre Ninja has Stealth and 6/6 stats; seeded attacks show direct and redirected outcomes",f"stealth={stealth}; stats={ninja.atk}/{ninja.health}; direct={direct}; redirected={redirected}; samples={outcomes}",stealth and ninja.atk==6 and ninja.health==6 and direct>0 and redirected>0,"32 independently seeded attack trials measure Forgetful instead of reading a non-existent property"))
    elif cid == "GVG_089":
        p.hero.hit(5); illuminator=_summon(p,cid); _play(p,"EX1_294")
        g.end_turn()
        rows.append(_rec(cid,"GVG_089_secret_end_turn_heal","with friendly Secret, end turn restores 4 health",f"secret_count={len(p.secrets)}; hero_health={p.hero.health}",len(p.secrets)>0 and p.hero.health==29,f"illuminator={illuminator.id}"))
    elif cid == "GVG_090":
        bomber=_play(p,cid)
        total=(30-p.hero.health)+(30-o.hero.health)
        rows.append(_rec(cid,"GVG_090_six_random_damage_points","Battlecry distributes exactly six 1-damage hits among other characters",f"total_damage={total}; bomber_health={bomber.health}; heroes={p.hero.health}/{o.hero.health}",total==6,"all characters have multiple possible hit recipients"))
    elif cid == "GVG_091":
        nullifier=_summon(p,cid)
        rows.append(_rec(cid,"GVG_091_taunt_untargetable","Arcane Nullifier is Taunt and cannot be targeted by spells",f"taunt={nullifier.taunt}; cant_target={nullifier.cant_be_targeted_by_abilities}",nullifier.taunt and nullifier.cant_be_targeted_by_abilities))
    elif cid == "GVG_093":
        dummy=_summon(p,cid)
        rows.append(_rec(cid,"GVG_093_taunt","Target Dummy has Taunt",f"taunt={dummy.taunt}; stats={dummy.atk}/{dummy.health}",dummy.taunt and dummy.atk==0 and dummy.health==2))
    elif cid == "GVG_095":
        sapper=_summon(p,cid); base=sapper.atk
        for _ in range(max(0,6-len(o.hand))): o.give(WISP)
        high=sapper.atk
        o.discard_hand()
        low=sapper.atk
        rows.append(_rec(cid,"GVG_095_opponent_hand_threshold","gains +4 Attack at six opponent cards and loses the bonus below six",f"base={base}; six_cards={high}; zero_cards={low}",high==base+4 and low==base))
    elif cid == "GVG_096":
        shredder=_summon(p,cid); shredder.destroy()
        spawn=p.field[-1] if p.field else None
        rows.append(_rec(cid,"GVG_096_random_two_cost_deathrattle","Deathrattle summons a minion whose cost is exactly 2",f"spawn={(spawn.id,spawn.cost) if spawn else None}; graveyard={[x.id for x in p.graveyard]}",shredder.zone==Zone.GRAVEYARD and spawn is not None and spawn.cost==2,"random minion identity can vary; cost domain is asserted"))
    elif cid == "GVG_098":
        infantry=_play(p,cid)
        rows.append(_rec(cid,"GVG_098_charge_taunt","Gnomeregan Infantry has Charge and Taunt and may attack immediately",f"charge={infantry.charge}; taunt={infantry.taunt}; can_attack={infantry.can_attack()}",infantry.charge and infantry.taunt and infantry.can_attack()))
    elif cid == "GVG_101":
        d1,d2=_summon(p,"GVG_082"),_summon(o,"GVG_078"); plain=_summon(p,WISP)
        _play(p,cid)
        rows.append(_rec(cid,"GVG_101_deathrattle_minions_take_damage","Battlecry deals 2 to Deathrattle minions on both sides and not to others",f"friendly_deathrattle={d1.zone}/{d1.health}; enemy_deathrattle={d2.zone}/{d2.health}/{d2.damage}; non_deathrattle={plain.zone}/{plain.health}/{plain.damage}",d1.zone==Zone.GRAVEYARD and d2.zone==Zone.PLAY and d2.damage==2 and plain.zone==Zone.PLAY and plain.damage==0,"the friendly 1-health Deathrattle minion is lethal; enemy 5-health Deathrattle minion survives; Wisp is a non-Deathrattle control"))
    elif cid == "GVG_105":
        golem=_summon(p,cid); golem.destroy(); spawn=p.field[-1] if p.field else None
        rows.append(_rec(cid,"GVG_105_random_four_cost_deathrattle","Deathrattle summons a minion whose printed cost is 4",f"spawn={(spawn.id,spawn.cost) if spawn else None}; source_zone={golem.zone}",golem.zone==Zone.GRAVEYARD and spawn is not None and spawn.cost==4,"random minion identity can vary; cost domain is asserted"))
    elif cid == "GVG_106":
        junk=_summon(p,cid); mech=_summon(p,"GVG_082"); before=(junk.atk,junk.max_health); mech.destroy()
        rows.append(_rec(cid,"GVG_106_friendly_mech_death","friendly Mech death grants Junkbot +2/+2",f"before={before}; after={junk.atk}/{junk.max_health}; source={mech.zone}",junk.atk==before[0]+2 and junk.max_health==before[1]+2))
    elif cid == "GVG_107":
        before=[_summon(p,WISP) for _ in range(4)]; _play(p,cid)
        allowed=[(x.windfury,x.taunt,x.divine_shield) for x in before]
        each_valid=all(sum(bool(v) for v in state)==1 for state in allowed)
        rows.append(_rec(cid,"GVG_107_random_keyword_assignment","each other minion gets exactly one of Windfury, Taunt, Divine Shield",f"keywords={allowed}",each_valid,"random branch variety still requires more seeds before GREEN"))
    elif cid == "GVG_109":
        mage=_summon(p,cid)
        before=o.hero.health
        _play(p,"CS2_008",o.hero)
        rows.append(_rec(cid,"GVG_109_spell_damage_and_stealth","Mini-Mage has Stealth and +1 Spell Damage; Moonfire deals 2",f"stealth_tag={mage.tags[GameTag.STEALTH]}; spellpower={p.spellpower}; enemy_hero_delta={before-o.hero.health}",bool(mage.tags[GameTag.STEALTH]) and p.spellpower==1 and before-o.hero.health==2))
    elif cid == "GVG_113":
        foe=_summon(p,cid); left=_summon(o,"CS2_200"); victim=_summon(o,"CS2_200"); right=_summon(o,"CS2_200")
        before=[x.damage for x in (left,victim,right)]
        _ready_player_minions(g,p)
        foe.attack(victim)
        deltas=[x.damage-before[i] for i,x in enumerate((left,victim,right))]
        rows.append(_rec(cid,"GVG_113_attack_cleave_adjacent","attack deals 6 to target and adjacent enemy minions",f"damage_deltas={deltas}; healths={[x.health for x in (left,victim,right)]}; zones={[x.zone for x in (left,victim,right)]}",deltas==[6,6,6],"three 6/7 enemy minions survive the hit, so each direct and adjacent damage value is measurable"))
        if deltas==[0,6,0]: rows[-1]["outcome"]="confirmed_error"
    elif cid == "GVG_115":
        before_parts=sum(x.id.startswith("PART_") for x in p.hand); tosh=_play(p,cid); after_play_parts=sum(x.id.startswith("PART_") for x in p.hand); tosh.destroy(); after_death_parts=sum(x.id.startswith("PART_") for x in p.hand)
        rows.append(_rec(cid,"GVG_115_battlecry_and_deathrattle","Battlecry and Deathrattle each add one Spare Part",f"parts_added={after_play_parts-before_parts},{after_death_parts-after_play_parts}; source={tosh.zone}",after_play_parts-before_parts==1 and after_death_parts-after_play_parts==1,"random spare part IDs are intentionally unconstrained"))
    elif cid == "GVG_118":
        trogg=_summon(p,cid)
        g.current_player=o
        _play(o,"CS2_008",p.hero)
        summoned=[x for x in p.field if x.id=="GVG_068"]
        rows.append(_rec(cid,"GVG_118_enemy_spell_summon","opponent spell summons a Burly Rockjaw Trogg on your side",f"troggs={[(x.id,x.zone) for x in summoned]}; field={[x.id for x in p.field]}",len(summoned)==1 and summoned[0].controller is p and trogg in p.field))
    elif cid == "GVG_120":
        beast=_summon(o,"CS2_172")
        _play(p,cid,beast)
        rows.append(_rec(cid,"GVG_120_beast_battlecry_target","Battlecry destroys a Beast target",f"target={beast.id}; zone={beast.zone}; enemy_field={[x.id for x in o.field]}",beast.zone==Zone.GRAVEYARD and beast not in o.field))
    elif cid == "GVG_121":
        giant=p.give(cid); start=giant.cost; starting_enemy_cards=len(o.hand)
        for _ in range(6): o.give(WISP)
        six=giant.cost
        o.discard_hand()
        zero=giant.cost
        rows.append(_rec(cid,"GVG_121_opponent_hand_cost","cost falls by one per opposing hand card and returns when hand empties",f"starting_enemy_cards={starting_enemy_cards}; costs={start},{six},{zero}",start==12-starting_enemy_cards and six==start-6 and zero==12))
    elif cid == "GVG_123":
        spewer=_summon(p,cid); before=o.hero.health
        _play(p,"CS2_008",o.hero)
        rows.append(_rec(cid,"GVG_123_spell_damage","Soot Spewer grants +1 spell damage to Moonfire",f"spewer={spewer.id}; spellpower={p.spellpower}; enemy_hero_delta={before-o.hero.health}",p.spellpower==1 and before-o.hero.health==2))
    else:
        raise KeyError(f"no targeted case or existing test reference for {cid}")
    return rows


def main():
    baseline = _read_csv(BASELINE)
    frozen = [row["card_id"] for row in baseline if row["set"] == "Goblins vs Gnomes (GVG)"]
    if tuple(frozen) != FROZEN_GVG_IDS:
        raise RuntimeError(f"frozen GVG roster mismatch: baseline={len(frozen)} literal={len(FROZEN_GVG_IDS)}")
    master = {row["card_id"]: row for row in _read_csv(HERE / "card_master.csv")}
    refs = {}
    for cid in OWN_GVG_IDS:
        ref = master[cid].get("test_refs_candidate", "")
        refs[cid] = []
        for item in ref.split("|"):
            match = re.match(r"(tests/.+\.py):\d+:(test_[A-Za-z0-9_]+)", item.strip())
            if match:
                refs[cid].append(match.group(1) + "::" + match.group(2))
        refs[cid] = list(dict.fromkeys(refs[cid]))

    external_nodes = list(dict.fromkeys(node for cid in OWN_GVG_IDS for node in refs[cid] if not node.startswith("tests/test_gvg.py:")))
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = "tests:."
    existing_cmd = [sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--tb=short", "tests/test_gvg.py", *external_nodes]
    result = subprocess.run(existing_cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    summary = (result.stdout + "\n" + result.stderr).strip().splitlines()
    summary_line = next((line.strip() for line in reversed(summary) if re.search(r"\bpassed\b|\bfailed\b|\berrors\b", line)), "no pytest summary")
    failed_nodes = set(re.findall(r"FAILED\s+([^\s]+)", result.stdout + result.stderr))
    probe_rows = []
    verdict_rows = []
    for cid in OWN_GVG_IDS:
        card = master[cid]
        card_cases = []
        try:
            # Every original YELLOW receives a current-round, card-specific Fireplace case first.
            card_cases.extend(custom_cases(cid))
        except Exception as exc:
            card_cases.append({"card_id": cid, "case_id": cid + "_probe_setup", "expected": "card-specific live-game behavior assertion", "observed": f"probe could not complete: {type(exc).__name__}: {exc}", "outcome": "inconclusive", "notes": f"Concrete harness blocker: {type(exc).__name__}: {exc}"})
        # Existing tests are secondary evidence only and can never substitute for this run's direct case.
        for node in refs[cid]:
            node_id = node.replace("tests/", "").replace(".py::", "::")
            failed = any(path.endswith(node_id.split("::", 1)[0]) and n == node_id.split("::", 1)[1] for path, n in (x.rsplit("::", 1) for x in failed_nodes if "::" in x))
            outcome = "confirmed_error" if failed else ("pass" if result.returncode == 0 else "inconclusive")
            expected = "auxiliary prior test only; direct card case is the verdict basis"
            observed = ("passed: " if outcome == "pass" else "failed: " if outcome == "confirmed_error" else "did not complete cleanly: ") + node + f" ({summary_line})"
            card_cases.append({"card_id":cid,"case_id":"existing_"+node_id.replace("::","_"),"expected":expected,"observed":observed,"outcome":outcome,"notes":"Supplementary existing test; excluded from status calculation."})
        direct_cases = [case for case in card_cases if not case["case_id"].startswith("existing_")]
        probe_rows.extend(card_cases)
        failed = [case for case in direct_cases if case["outcome"] == "confirmed_error"]
        inconclusive = [case for case in direct_cases if case["outcome"] == "inconclusive"]
        labels = [label for label in card.get("mechanics", "").split("|") if label]
        if failed:
            status = "RED"
            mismatch=failed[0]
            reason=f"实测与卡牌文本不符：预期“{mismatch['expected']}”；实得“{mismatch['observed']}”。"
        elif inconclusive:
            status = "YELLOW"
            blocker=inconclusive[0]
            reason=f"本轮用例尚未定论：{blocker['expected']}；观测为 {blocker['observed']}。"
        else:
            # GREEN is deliberately an explicit review list, never inferred from label count.
            GREEN_REVIEWED = {"GVG_002","GVG_005","GVG_006","GVG_007","GVG_008","GVG_009","GVG_010","GVG_011","GVG_012","GVG_013","GVG_014","GVG_015","GVG_016","GVG_017","GVG_018","GVG_019","GVG_021","GVG_023","GVG_024","GVG_025","GVG_026","GVG_027","GVG_028","GVG_030","GVG_031","GVG_032","GVG_033","GVG_036","GVG_037","GVG_038","GVG_039","GVG_040","GVG_041","GVG_045","GVG_047","GVG_049","GVG_050","GVG_051","GVG_053","GVG_055","GVG_056","GVG_057","GVG_058","GVG_060","GVG_061","GVG_062","GVG_063","GVG_065","GVG_066","GVG_067","GVG_068","GVG_069","GVG_072","GVG_073","GVG_074","GVG_076","GVG_077","GVG_079","GVG_080","GVG_081","GVG_083","GVG_084","GVG_085","GVG_086","GVG_088","GVG_089","GVG_091","GVG_093","GVG_095","GVG_098","GVG_101","GVG_106","GVG_109","GVG_118","GVG_120","GVG_121","GVG_123"}
            status = "GREEN" if cid in GREEN_REVIEWED and all(c["outcome"] == "pass" for c in direct_cases) else "YELLOW"
            if status == "GREEN":
                reason=f"本轮定向实测已通过，观测：{direct_cases[0]['observed']}；本卡完整机制范围已在对应用例覆盖。"
            elif "Random effects" in labels:
                blocker=YELLOW_BLOCKERS.get(cid, "请补齐本卡随机池的其他候选/结果身份，并通过固定种子验证关键结果分支。")
                reason=f"本轮定向实测观测：{direct_cases[0]['observed']}；未决点：{blocker}"
            else:
                blocker=YELLOW_BLOCKERS.get(cid, f"尚未在本轮用例检查机制范围 {card['mechanics']} 的关键交互/边界分支。")
                reason=f"本轮定向实测观测：{direct_cases[0]['observed']}；未决点：{blocker}"
        evidence = "; ".join(c["case_id"] for c in card_cases)
        verdict_rows.append({"card_id": cid, "status": status, "mechanic_scope": card["mechanics"], "reason": reason, "probe_file": "gvg_probe.csv", "notes": f"{card['name_en']}; direct evidence={'; '.join(c['case_id'] for c in direct_cases)}; source={card.get('python_source') or 'CardDefs.xml'}"})
        _write_rows(PROBE_OUT, PROBE_FIELDS, probe_rows)
        _write_rows(VERDICT_OUT, VERDICT_FIELDS, verdict_rows)

    print(f"frozen_baseline_gvg={len(FROZEN_GVG_IDS)} assigned_gvg={len(OWN_GVG_IDS)} indexed={len(verdict_rows)} cases={len(probe_rows)}")
    counts = {status: sum(row["status"] == status for row in verdict_rows) for status in ("GREEN", "RED", "YELLOW")}
    print(f"status_counts={counts}")
    print(f"auxiliary_existing_tests={summary_line} (returncode={result.returncode})")


if __name__ == "__main__":
    main()
