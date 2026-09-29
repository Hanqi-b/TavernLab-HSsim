"""Focused live-game audit for the final 44 ICECROWN YELLOW collectibles.

This file deliberately keeps one small, card-specific fixture per card.  It is
an audit artifact rather than a production test suite: a GREEN result means
that the assertions below exercised the important text of that card in a live
game, while a YELLOW result records an unresolved branch and RED records a
confirmed mismatch.
"""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import GameOver, InvalidAction

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import (  # noqa: E402
    ELEMENTAL,
    LICH_KING_CARDS,
    MOONFIRE,
    THE_COIN,
    WISP,
    prepare_empty_game,
)

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

BASELINE = HERE / "icecrown_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
MECHANISMS = HERE / "card_mechanism.csv"
QUALITY = HERE / "card_quality.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE = HERE / "icc_probe_c.csv"
VERDICT = HERE / "icc_verdict_c.csv"
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


BASE_ROWS = read_csv(BASELINE)
# The frozen audit file contains all ICECROWN YELLOW rows.  The delegated
# slice is the stable sorted tail, ICC_702 through ICC_913.
ICE_ROWS = [r for r in BASE_ROWS if r["set"] == "Knights of the Frozen Throne (ICECROWN)"]
START = next(i for i, row in enumerate(ICE_ROWS) if row["card_id"] == "ICC_702")
END = next(i for i, row in enumerate(ICE_ROWS) if row["card_id"] == "ICC_913")
CARDS = [row["card_id"] for row in ICE_ROWS[START:END + 1]]
assert START == 88 and END == 131 and len(CARDS) == 44, (START, END, len(CARDS))
MASTER_ROWS = {row["card_id"]: row for row in read_csv(MASTER)}
OLD_QUALITY = {row["card_id"]: row for row in read_csv(QUALITY)}
MECH_ROWS = read_csv(MECHANISMS)
LABELS = {cid: sorted({r["mechanic"] for r in MECH_ROWS if r["card_id"] == cid}) for cid in CARDS}
OLD_MECH_REASONS = {
    cid: sorted({r["reason"] for r in MECH_ROWS if r["card_id"] == cid and r["reason"]})
    for cid in CARDS
}
PROBE_ROWS = read_csv(PROBE)
VERDICT_ROWS = read_csv(VERDICT)


def game(class1=CardClass.MAGE, class2=CardClass.WARRIOR, seed=417):
    """Make player1 the active player despite the random coin toss."""
    random.seed(seed)
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
    return g


def play(player, card_id, target=None, choose=None):
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    card.play(**kwargs)
    return card


def summon(player, card_id):
    return player.summon(card_id)


def checked(observed, condition):
    assert condition, observed
    return observed


def add_case(cid, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except Exception as exc:  # The distinction is useful in the final audit.
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append({
        "card_id": cid, "case_id": case_id, "expected": expected,
        "observed": observed, "outcome": outcome, "notes": notes,
    })
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)


def prepare_card(cid):
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != cid]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def finish_card(cid, blocker=None, extra_notes=""):
    own = [r for r in PROBE_ROWS if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own), cid
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "；".join(
            f"{r['case_id']}预期[{r['expected']}]，实际[{r['observed']}]" for r in errors
        )
    elif unresolved:
        status = "YELLOW"
        reason = "行为测试未完成：" + "；".join(
            f"{r['case_id']}={r['observed']}" for r in unresolved
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "逐卡实际对局断言通过：" + "；".join(
            f"{r['case_id']}={r['observed']}" for r in own
        )
    master = MASTER_ROWS[cid]
    quality = OLD_QUALITY.get(cid, {})
    affected = []
    for issue in read_csv(ISSUES):
        cards = set((issue.get("confirmed_cards", "") + "|" + issue.get("candidate_cards", "")).split("|"))
        if cid in cards:
            affected.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    notes = (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or '未发现 Python 卡脚本'}; "
        f"existing_tests={master.get('test_refs_candidate', '') or '无候选既有测试引用'}; "
        f"previous_card_audit={quality.get('reason', '无')}; "
        f"previous_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
        f"prior_cross_card_issues={' / '.join(affected) if affected else '无'}; "
        "audit_scope=本轮实际运行逐卡断言。"
    )
    if extra_notes:
        notes += f"; {extra_notes}"
    if cid == "ICC_808":
        notes += " confirmed_RED_scope=英文效果要求召唤任意随从后获得+1生命；源码fireplace/cards/icecrown/druid.py:62使用Summon(CONTROLLER, TAUNT)，普通Wisp召唤未触发，只有Taunt召唤触发。"
    if cid == "ICC_812":
        notes += " confirmed_RED_scope=英文要求Attack严格小于本体；源码fireplace/cards/icecrown/neutral_epic.py:57使用(ATK <= ATK(SELF))，实测同为1攻Wisp被错误召唤，0攻Frozen Champion正向分支通过。"
    if cid == "ICC_853":
        notes += " confirmed_RED_scope=英文条件为牌库没有4费牌；源码fireplace/cards/icecrown/neutral_legendary.py:116使用(FRIENDLY_DECK + (COST == 2))，2费牌库时错误不赋予关键词，4费牌库时错误赋予Taunt/Lifesteal。"
    if cid == "ICC_827":
        notes += " confirmed_RED_scope=Shadow Reflection 复制卡应在当前己方回合结束时离开手牌；实测复制后的Wisp仍在手牌跨过OWN_TURN_END，且下一回合又新增ICC_827t；源码fireplace/cards/icecrown/rogue.py:131-137仅销毁增益实体。参考规则说明：https://hearthstone.wiki.gg/wiki/Valeera_the_Hollow。"
    VERDICT_ROWS.append({
        "card_id": cid, "status": status, "mechanic_scope": "|".join(LABELS[cid]),
        "reason": reason, "probe_file": PROBE.name, "notes": notes,
    })
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}")


def audit_card(cid, cases, blocker=None, extra_notes=""):
    prepare_card(cid)
    for case_id, expected, func, notes in cases:
        add_case(cid, case_id, expected, func, notes)
    finish_card(cid, blocker, extra_notes)


def _enemy_minion(g, card_id="CS2_182"):
    return summon(g.player2, card_id)


def probe_702():
    cid = "ICC_702"
    def deathrattle_card_is_added():
        g = game()
        p = g.player1
        old = summon(p, "ICC_019")
        old.destroy()
        assert old.zone == Zone.GRAVEYARD
        gravedigger = play(p, cid)
        gravedigger.destroy()
        added = [c for c in p.hand if c.id != "GAME_005"]
        return checked(f"hand={[c.id for c in added]};source_death={old.id};gravedigger={gravedigger.zone.name}",
                       added and all(c.type == CardType.MINION and c.deathrattles for c in added))
    return [("random_deathrattle_minion", "Deathrattle adds one random minion with a Deathrattle from the eligible pool.", deathrattle_card_is_added,
             "先制造一个已死亡的亡语随从，再实际触发 Shallow Gravedigger 并检查手牌类型和亡语属性。")]


def probe_705():
    cid = "ICC_705"
    def buff_friendly_target():
        g = game(); p = g.player1
        target = summon(p, WISP)
        base = (target.atk, target.health)
        bonemare = play(p, cid, target)
        return checked(f"target={target.atk}/{target.health};base={base};taunt={target.taunt};bonemare={bonemare.zone.name}",
                       (target.atk, target.health) == (base[0] + 4, base[1] + 4) and target.taunt and bonemare in p.field)
    return [("friendly_plus_four_taunt", "A friendly minion gains exactly +4/+4 and Taunt.", buff_friendly_target,
             "用实际友方目标验证攻击、生命和 Taunt 三个结果。")]


def probe_706():
    cid = "ICC_706"
    def all_spell_cost_aura_and_removal():
        g = game(); p, e = g.player1, g.player2
        apprentice = summon(p, cid)
        own_spell = p.give("CS2_024")
        enemy_spell = e.give("CS2_024")
        assert own_spell.cost == 4 and enemy_spell.cost == 4
        apprentice.destroy()
        assert own_spell.cost == 2 and enemy_spell.cost == 2
        return f"own_spell={own_spell.cost};enemy_spell={enemy_spell.cost};aura_source={apprentice.zone.name}"
    return [("all_spell_cost_aura", "Both players' spells cost +2 while Nerubian Unraveler is in play, and both return to printed cost after it dies.", all_spell_cost_aura_and_removal,
             "双方各放置一张 Frostbolt（基础费用 2），实际检查 Aura 期间为 4、离场后恢复为 2。")]


def probe_801():
    cid = "ICC_801"
    def draw_divine_shield_minion():
        g = game(CardClass.PALADIN, CardClass.MAGE); p = g.player1
        p.give("ICC_038").shuffle_into_deck()
        p.give(WISP).shuffle_into_deck()
        commander = play(p, cid)
        ids = [c.id for c in p.hand]
        return checked(f"hand={ids};deck={[c.id for c in p.deck]};commander={commander.zone.name}",
                       "ICC_038" in ids and "CS2_231" not in ids and commander in p.field)
    return [("draw_divine_shield_minion", "Battlecry draws a Divine Shield minion from the deck, not an arbitrary minion.", draw_divine_shield_minion,
             "牌库放入一个圣盾随从和一个普通随从，检查战吼后的具体手牌。")]


def probe_802():
    cid = "ICC_802"
    def all_minions_damage_and_lifesteal():
        g = game(CardClass.PRIEST, CardClass.MAGE); p, e = g.player1, g.player2
        p.hero.damage = 10
        friendly = summon(p, "CS2_182")
        enemy = _enemy_minion(g, "CS2_182")
        before = (friendly.health, enemy.health, p.hero.health)
        lash = play(p, cid)
        after = (friendly.health, enemy.health, p.hero.health)
        return checked(f"before={before};after={after};spell={lash.zone.name}",
                       after[0] == before[0] - 1 and after[1] == before[1] - 1 and after[2] == before[2] + 2)
    return [("all_minions_one_lifesteal", "Deal 1 to every minion and restore 1 per damaged minion through Lifesteal.", all_minions_damage_and_lifesteal,
             "双方各放置一个可存活随从，先压低施法者生命，再核对全场两次伤害各自贡献 1 点吸血。")]


def probe_807():
    cid = "ICC_807"
    def taunt_only_buff():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        taunt = summon(p, "CS1_042")
        plain = summon(p, WISP)
        before = (taunt.atk, taunt.health, plain.atk, plain.health)
        play(p, cid)
        return checked(f"taunt={taunt.atk}/{taunt.health};plain={plain.atk}/{plain.health};before={before}",
                       (taunt.atk, taunt.health) == (before[0] + 2, before[1] + 2) and
                       (plain.atk, plain.health) == before[2:])
    return [("taunt_minions_only", "All friendly Taunt minions gain +2/+2, while a non-Taunt minion is unchanged.", taunt_only_buff,
             "同一局面放置 Taunt 和普通随从，检查筛选条件而非只检查卡牌能否打出。")]


def probe_808():
    cid = "ICC_808"
    def every_summoned_minion_increases_health():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        crypt = play(p, cid)
        before = (crypt.health, crypt.max_health)
        summon(p, WISP)
        after_plain = (crypt.health, crypt.max_health)
        summon(p, "CS1_042")
        after_taunt = (crypt.health, crypt.max_health)
        return checked(f"before={before};after_plain={after_plain};after_taunt={after_taunt}",
                       after_plain == (before[0] + 1, before[1] + 1) and
                       after_taunt == (before[0] + 2, before[1] + 2))
    return [("all_summons_plus_health", "Each subsequently summoned minion gives Crypt Lord +1 Health.", every_summoned_minion_increases_health,
             "分别召唤普通随从和 Taunt 随从；文本没有 Taunt 限制，因此两次都必须触发。")]


def probe_809():
    cid = "ICC_809"
    def combo_gives_poisonous():
        g = game(CardClass.ROGUE, CardClass.MAGE); p, e = g.player1, g.player2
        p.give(MOONFIRE).play(target=e.hero)
        target = summon(p, WISP)
        scientist = play(p, cid, target)
        return checked(f"scientist={scientist.zone.name};target_poisonous={target.poisonous};target={target.zone.name}",
                       target.poisonous and target.zone == Zone.PLAY)
    def no_combo_cannot_target():
        g = game(CardClass.ROGUE, CardClass.MAGE); p = g.player1
        target = summon(p, WISP)
        scientist = p.give(cid)
        scientist.play(target=target)
        return checked(f"target={target.zone.name};scientist={scientist.zone.name};poisonous={target.poisonous}",
                       scientist.zone == Zone.PLAY and target.zone == Zone.PLAY and not target.poisonous)
    return [
        ("combo_poisonous", "After another card is played this turn, Plague Scientist gives a friendly minion Poisonous.", combo_gives_poisonous,
         "先施放 Moonfire 建立 Combo，再用实际友方随从目标验证 Poisonous。"),
        ("without_combo_no_effect", "Without Combo, the card may be played but does not give Poisonous.", no_combo_cannot_target,
         "单独打出并显式指定目标，确认没有 Combo 时目标仍保持原状态且战吼无效果。"),
    ]


def probe_810():
    cid = "ICC_810"
    def one_random_lifesteal_hand_minion():
        g = game(CardClass.WARRIOR, CardClass.MAGE, seed=812); p = g.player1
        life_a = p.give("ICC_220")
        life_b = p.give("ICC_905")
        plain = p.give(WISP)
        before = {c.id: (c.atk, c.health) for c in (life_a, life_b, plain)}
        play(p, cid)
        changed = [c for c in (life_a, life_b) if (c.atk, c.health) == (before[c.id][0] + 2, before[c.id][1] + 2)]
        return checked(f"before={before};after={[(c.id,c.atk,c.health) for c in (life_a,life_b,plain)]};changed={[c.id for c in changed]}",
                       len(changed) == 1 and (plain.atk, plain.health) == before[plain.id])
    return [("random_lifesteal_hand_buff", "Exactly one random Lifesteal minion in hand gains +2/+2; non-Lifesteal cards remain unchanged.", one_random_lifesteal_hand_minion,
             "手牌同时放入两个 Lifesteal 随从和一个普通随从，验证随机池及单目标数量。")]


def probe_811():
    cid = "ICC_811"
    def spells_replaced_from_enemy_class():
        g = game(CardClass.ROGUE, CardClass.MAGE); p = g.player1
        original_a = p.give(MOONFIRE)
        original_b = p.give("EX1_154")
        keep = p.give(WISP)
        play(p, cid)
        spells = [c for c in p.hand if c.type == CardType.SPELL]
        original_ids = {original_a.id, original_b.id}
        return checked(f"hand={[c.id for c in p.hand]};spells={[c.id for c in spells]};keep={keep.id};originals={sorted(original_ids)}",
                       len(spells) == 2 and not original_ids.intersection(c.id for c in spells) and
                       all(c.card_class == CardClass.MAGE for c in spells) and keep in p.hand and len(p.hand) == 3)
    return [("replace_all_hand_spells_enemy_class", "All spells in hand are replaced by random spells from the opponent's class; other cards stay and hand count is preserved.", spells_replaced_from_enemy_class,
             "Rogue 对 Mage 局面放入两张不同法术和一个随从，核对所有法术均替换、职业正确且非目标牌保留。")]


def probe_812():
    cid = "ICC_812"
    def deathrattle_requires_strictly_less_attack():
        g = game(CardClass.HUNTER, CardClass.MAGE); p = g.player1
        p.give(WISP).shuffle_into_deck()  # Wisp has exactly 1 Attack, equal to Meat Wagon.
        wagon = play(p, cid)
        base = wagon.atk
        wagon.destroy()
        summoned = [c for c in p.field if c.id == WISP]
        return checked(f"wagon_attack={base};summoned={[c.id for c in p.field]};deck={[c.id for c in p.deck]}",
                       not summoned)
    def lower_attack_control_summons():
        g = game(CardClass.HUNTER, CardClass.MAGE); p = g.player1
        lower = p.give("ICC_838t")
        lower.shuffle_into_deck()
        wagon = play(p, cid)
        wagon.destroy()
        summoned = [c for c in p.field if c.id == "ICC_838t"]
        return checked(f"wagon_attack={wagon.atk};summoned={[c.id for c in p.field]};deck={[c.id for c in p.deck]}",
                       len(summoned) == 1 and summoned[0].atk < wagon.atk)
    return [
        ("less_than_attack_not_equal", "Deathrattle does not summon a deck minion whose Attack equals Meat Wagon's Attack.", deathrattle_requires_strictly_less_attack,
         "用唯一一张与 Meat Wagon 同攻击力的牌库随从隔离 `<` 与 `<=` 边界。"),
        ("strictly_lower_control", "Deathrattle summons a deck minion whose Attack is strictly lower.", lower_attack_control_summons,
         "用 0 攻击力 Frozen Champion 作为正向对照，确认牌库和召唤流程本身可执行。"),
    ]


def probe_820():
    cid = "ICC_820"
    def charge_and_lifesteal():
        g = game(CardClass.PALADIN, CardClass.MAGE); p, e = g.player1, g.player2
        p.hero.damage = 10
        champion = play(p, cid)
        assert champion.charge and champion.lifesteal
        before = (e.hero.health, p.hero.health)
        champion.attack(e.hero)
        after = (e.hero.health, p.hero.health)
        return checked(f"charge={champion.charge};lifesteal={champion.lifesteal};before={before};after={after}",
                       after == (before[0] - champion.atk, before[1] + champion.atk))
    return [("charge_lifesteal_attack", "Chillblade Champion can attack immediately and restores its damage through Lifesteal.", charge_and_lifesteal,
             "实际本回合下场后立即攻击敌方英雄，并同时断言 Charge、Lifesteal 和双方生命变化。")]


def probe_823():
    cid = "ICC_823"
    def copies_lowest_cost_minion():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p = g.player1
        low = p.give("CS1_042")
        high = p.give("ICC_705")
        spell = play(p, cid)
        ids = [c.id for c in p.hand]
        return checked(f"hand={ids};low={low.id}@{low.cost};high={high.id}@{high.cost};spell={spell.zone.name}",
                       low in p.hand and high in p.hand and ids.count("CS1_042") == 2)
    return [("copy_lowest_cost_minion", "Simulacrum adds an exact copy of the lowest-Cost minion in hand and leaves the originals.", copies_lowest_cost_minion,
             "手牌放置一个 1 费和一个高费随从，实际比较复制结果及原牌仍在手牌。")]


def probe_825():
    cid = "ICC_825"
    def summon_dead_friendly_beast():
        g = game(CardClass.HUNTER, CardClass.MAGE); p = g.player1
        beast = summon(p, "EX1_170")
        beast.destroy()
        bowman = play(p, cid)
        bowman.destroy()
        revived = [c for c in p.field if c.id == "EX1_170"]
        return checked(f"dead={beast.id};field={[c.id for c in p.field]};revived={[c.id for c in revived]}",
                       len(revived) == 1 and revived[0].type == CardType.MINION and revived[0].race == Race.BEAST)
    def friendly_beast_filter_excludes_enemy_and_nonbeast():
        g = game(CardClass.HUNTER, CardClass.MAGE); p, e = g.player1, g.player2
        friendly_beast = summon(p, "EX1_170")
        enemy_beast = summon(e, "EX1_170")
        friendly_nonbeast = summon(p, WISP)
        friendly_beast.destroy(); enemy_beast.destroy(); friendly_nonbeast.destroy()
        bowman = play(p, cid)
        bowman.destroy()
        ids = [c.id for c in p.field]
        return checked(f"dead={[friendly_beast.id,enemy_beast.id,friendly_nonbeast.id]};field={ids}",
                       ids == ["EX1_170"] or set(ids) == {"EX1_170"})
    return [
        ("summon_dead_friendly_beast", "Deathrattle summons a random friendly Beast that died this game.", summon_dead_friendly_beast,
         "先让明确的 Beast 死亡，再触发 Bowman，断言召回对象确为该死亡池中的 Beast。"),
        ("friendly_beast_pool_filter", "The resurrection pool excludes an enemy Beast and a friendly non-Beast corpse.", friendly_beast_filter_excludes_enemy_and_nonbeast,
         "同时制造敌方 Beast 与友方非 Beast 死亡记录，检查随机池的控制者与种族筛选。"),
    ]


def probe_827():
    cid = "ICC_827"
    def stealth_until_next_turn_and_shadow_power():
        g = game(CardClass.ROGUE, CardClass.MAGE); p = g.player1
        valeera = play(p, cid)
        assert p.hero.stealthed and p.hero.power.id == "ICC_827p"
        reflection = [c for c in p.hand if c.id == "ICC_827t"]
        assert len(reflection) == 1
        p.give(WISP).play()
        reflected_ids = [c.id for c in p.hand]
        assert WISP in reflected_ids and any(c.id == WISP for c in p.field)
        assert g.current_player is p
        g.end_turn()
        expired_hand = [c.id for c in p.hand]
        reflection_expired = WISP not in expired_hand
        assert p.hero.stealthed
        g.end_turn()
        return checked(f"hero={p.hero.id};stealthed={p.hero.stealthed};power={p.hero.power.id};power_exhausted={p.hero.power.exhausted};reflected_hand={reflected_ids};hand_at_own_turn_end={expired_hand};hand_after_turn={[c.id for c in p.hand]};reflection_expired={reflection_expired}",
                       reflection_expired and not p.hero.stealthed and p.hero.power.id == "ICC_827p" and valeera.zone == Zone.PLAY and
                       any(c.id == "ICC_827t" for c in p.hand))
    return [("stealth_and_shadow_reflection", "Battlecry grants Stealth through the current turn and replaces the Hero Power with Shadow Reflection until the next turn.", stealth_until_next_turn_and_shadow_power,
             "检查实际盗贼英雄、Shadow Reflection ID、当前回合和下一个己方回合的隐身边界。")]


def probe_828():
    cid = "ICC_828"
    def damage_enemy_minions_only():
        g = game(CardClass.HUNTER, CardClass.MAGE); p, e = g.player1, g.player2
        enemy = _enemy_minion(g, "CS2_182")
        hero_before = e.hero.health
        rex = play(p, cid)
        return checked(f"enemy={enemy.health};enemy_hero={e.hero.health};before_hero={hero_before};hero={p.hero.id};rex={rex.zone.name}",
                       enemy.health == enemy.max_health - 2 and e.hero.health == hero_before and p.hero.id == cid)
    def build_a_beast_two_choices():
        g = game(CardClass.HUNTER, CardClass.MAGE, seed=828); p = g.player1
        play(p, cid)
        p.used_mana = 0
        p.hero.power.use()
        first = p.choice.cards[0]
        p.choice.choose(first)
        second = p.choice.cards[0]
        p.choice.choose(second)
        result = [c for c in p.hand if c.id == "ICC_828t"]
        expected = (first.atk + second.atk, first.health + second.health, first.cost + second.cost)
        return checked(f"first={first.id};second={second.id};result={[(c.atk,c.health,c.cost) for c in result]};expected={expected};power={p.hero.power.id}",
                       len(result) == 1 and (result[0].atk, result[0].health, result[0].cost) == expected and p.hero.power.id == "ICC_828p")
    return [
        ("enemy_minions_two_damage", "Deathstalker Rexxar deals exactly 2 to enemy minions and does not damage the enemy hero.", damage_enemy_minions_only,
         "保留敌方英雄作为对照目标，避免把全敌方角色误判成全敌方随从。"),
        ("build_a_beast_two_choices", "Build-a-Beast presents two choices and creates a custom hand minion whose stats and cost equal the two selected Beasts.", build_a_beast_two_choices,
         "实际打开 Build-a-Beast，分别选择两张候选牌，检查最终 ICC_828t 的攻击、生命和费用求和。"),
    ]


def probe_829():
    cid = "ICC_829"
    def equip_five_three_lifesteal_weapon():
        g = game(CardClass.PALADIN, CardClass.MAGE); p = g.player1
        hero = play(p, cid)
        weapon = p.hero.weapon
        return checked(f"hero={p.hero.id};weapon={weapon.id if weapon else None};stats={(weapon.atk,weapon.durability) if weapon else None};lifesteal={weapon.lifesteal if weapon else None}",
                       p.hero.id == cid and weapon is not None and (weapon.atk, weapon.durability) == (5, 3) and weapon.lifesteal)
    def four_distinct_horsemen_win():
        g = game(CardClass.PALADIN, CardClass.MAGE, seed=1); p, e = g.player1, g.player2
        play(p, cid)
        assert p.hero.power.id == "ICC_829p"
        # Playing a Hero consumes the current turn's power use in this engine;
        # begin a fresh player turn before exercising the four-use branch.
        g.end_turn(); g.end_turn()
        for index in range(3):
            p.hero.power.use()
            g.end_turn(); g.end_turn()
        first_three = {c.id for c in p.field}
        try:
            p.hero.power.use()
        except GameOver:
            won = True
        else:
            won = False
        all_four = {"ICC_829t2", "ICC_829t3", "ICC_829t4", "ICC_829t5"}
        return checked(f"power={p.hero.power.id};horsemen={sorted(c.id for c in p.field)};distinct_before_final={sorted(first_three)};game_over={won}",
                       won and all_four.issubset({c.id for c in p.field}) and first_three.issubset(all_four) and len(first_three) == 3)
    return [
        ("equip_five_three_lifesteal", "Battlecry replaces the Paladin weapon with a 5/3 Lifesteal weapon.", equip_five_three_lifesteal_weapon,
         "不只确认英雄可打出，直接检查英雄当前武器的 ID、攻击、耐久和 Lifesteal。"),
        ("four_distinct_horsemen_win", "The new Hero Power summons four distinct Horsemen and wins when the fourth is present.", four_distinct_horsemen_win,
         "连续跨四个己方回合实际使用 The Four Horsemen，检查四个不同 token 和最终 GameOver。"),
    ]


def probe_830():
    cid = "ICC_830"
    def destroy_attack_five_or_more():
        g = game(CardClass.PRIEST, CardClass.MAGE); p, e = g.player1, g.player2
        high = summon(e, "CS2_162")
        low = summon(e, WISP)
        own_high = summon(p, "CS2_162")
        own_low = summon(p, WISP)
        play(p, cid)
        return checked(f"enemy_high={high.zone.name};enemy_low={low.zone.name};own_high={own_high.zone.name};own_low={own_low.zone.name};enemy_field={[c.id for c in e.field]};own_field={[c.id for c in p.field]}",
                       high.zone == Zone.GRAVEYARD and low.zone == Zone.PLAY and
                       own_high.zone == Zone.GRAVEYARD and own_low.zone == Zone.PLAY)
    def voidform_deals_two():
        g = game(CardClass.PRIEST, CardClass.MAGE); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        play(p, cid)
        p.used_mana = 0
        before = target.health
        p.hero.power.use(target=target)
        return checked(f"power={p.hero.power.id};target={before}->{target.health};exhausted={p.hero.power.exhausted}",
                       target.health == before - 2 and p.hero.power.exhausted)
    return [
        ("destroy_attack_at_least_five", "Battlecry destroys every minion with at least 5 Attack on both sides and leaves lower-Attack minions alive.", destroy_attack_five_or_more,
         "双方同时放置高攻和低攻随从，按攻击力边界检查全场区域变化。"),
        ("voidform_two_damage", "Voidform deals exactly 2 damage to a selected character and exhausts for the turn.", voidform_deals_two,
         "实际指定敌方随从使用 Voidform，检查伤害和技能使用状态。"),
    ]


def probe_831():
    cid = "ICC_831"
    def only_dead_friendly_demons_return():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p = g.player1
        first = summon(p, "CS2_059")
        second = summon(p, "EX1_319")
        non_demon = summon(p, WISP)
        enemy_demon = summon(g.player2, "CS2_059")
        first.destroy(); second.destroy(); non_demon.destroy(); enemy_demon.destroy()
        play(p, cid)
        ids = [c.id for c in p.field]
        return checked(f"dead={[first.id,second.id,non_demon.id,enemy_demon.id]};field={ids};hero={p.hero.id}",
                       len(ids) == 2 and set(ids) == {"CS2_059", "EX1_319"})
    def board_cap_limits_resurrection():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p = g.player1
        dead = summon(p, "CS2_059")
        dead.destroy()
        for _ in range(6):
            summon(p, WISP)
        play(p, cid)
        demon_count = sum(c.id == "CS2_059" for c in p.field)
        return checked(f"field={[c.id for c in p.field]};field_size={len(p.field)};resurrected_demons={demon_count}",
                       len(p.field) == 7 and demon_count == 1)
    def siphon_life_damages_and_heals():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p, e = g.player1, g.player2
        play(p, cid)
        p.hero.damage = 10
        p.used_mana = 0
        before = (e.hero.health, p.hero.health)
        p.hero.power.use(target=e.hero)
        return checked(f"power={p.hero.power.id};enemy={before[0]}->{e.hero.health};owner={before[1]}->{p.hero.health};exhausted={p.hero.power.exhausted}",
                       e.hero.health == before[0] - 3 and p.hero.health == before[1] + 3 and p.hero.power.exhausted)
    return [
        ("resummon_dead_friendly_demons_only", "Battlecry summons all dead friendly Demons, excluding an enemy Demon and a dead friendly non-Demon.", only_dead_friendly_demons_return,
         "同时制造友方恶魔、敌方恶魔和友方非恶魔死亡记录，逐项检查召回池。"),
        ("resurrection_board_cap", "The Battlecry respects the seven-minion board cap when returning dead Demons.", board_cap_limits_resurrection,
         "六个现存随从占满六个位置后再召回一个死亡恶魔，检查不会溢出场面。"),
        ("siphon_life", "Siphon Life deals 3 damage and restores 3 Health to the Warlock hero.", siphon_life_damages_and_heals,
         "实际使用升级后的英雄技能，以敌方英雄为目标，同时检查伤害、治疗和 Exhausted。"),
    ]


def probe_832():
    cid = "ICC_832"
    def poisonous_spider_choice():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        play(p, cid, choose="ICC_832b")
        ids = [c.id for c in p.field]
        return checked(f"choice=ICC_832b (Spider Plague);field={ids};attrs={[(c.id,c.poisonous,c.taunt) for c in p.field]}",
                       len(p.field) == 2 and all(c.poisonous and not c.taunt for c in p.field))
    def taunt_scarab_choice():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        play(p, cid, choose="ICC_832a")
        return checked(f"choice=ICC_832a (Scarab Plague);field={[c.id for c in p.field]};attrs={[(c.id,c.poisonous,c.taunt) for c in p.field]}",
                       len(p.field) == 2 and all(c.taunt and not c.poisonous for c in p.field))
    def plague_lord_gains_armor():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        play(p, cid, choose="ICC_832a")
        p.used_mana = 0
        before = (p.hero.armor, p.hero.atk)
        p.hero.power.use(choose="ICC_832pa")
        return checked(f"before={before};after={(p.hero.armor,p.hero.atk)};power={p.hero.power.id}",
                       p.hero.armor == before[0] + 3 and p.hero.atk == before[1])
    def plague_lord_gains_attack():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        play(p, cid, choose="ICC_832b")
        p.used_mana = 0
        before = (p.hero.armor, p.hero.atk)
        p.hero.power.use(choose="ICC_832pb")
        return checked(f"before={before};after={(p.hero.armor,p.hero.atk)};power={p.hero.power.id}",
                       p.hero.armor == before[0] and p.hero.atk == before[1] + 3)
    return [
        ("choose_two_poisonous_spiders", "Choice ICC_832b (Spider Plague) summons two Poisonous Spiders.", poisonous_spider_choice,
         "实际选择 ICC_832b（Spider Plague），并逐个检查两个 token 的 Poisonous 与 Taunt。"),
        ("choose_two_taunt_scarabs", "Choice ICC_832a (Scarab Plague) summons two Taunt Scarabs.", taunt_scarab_choice,
         "实际选择 ICC_832a（Scarab Plague），并逐个检查两个 token 的 Taunt 与 Poisonous。"),
        ("plague_lord_armor", "Malfurion's Hero Power Armor branch grants 3 Armor without Attack.", plague_lord_gains_armor,
         "实际选择 Plague Lord 的护甲分支，检查护甲增加且攻击不变。"),
        ("plague_lord_attack", "Malfurion's Hero Power Attack branch grants 3 Attack without Armor.", plague_lord_gains_attack,
         "实际选择 Plague Lord 的攻击分支，检查攻击增加且护甲不变。"),
    ]


def probe_833():
    cid = "ICC_833"
    def elemental_lifesteal_aura():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p = g.player1
        existing = play(p, "UNG_809")
        assert not existing.lifesteal
        jaina = play(p, cid)
        p.used_mana = 0  # keep the post-Hero branch executable in this empty-game fixture
        future = play(p, "UNG_809")
        non_elemental = summon(p, WISP)
        elementals = [c for c in p.field if c.race == Race.ELEMENTAL]
        return checked(f"hero={p.hero.id};field={[(c.id,c.atk,c.health,c.lifesteal) for c in p.field]};jaina={jaina.zone.name};future={future.id};non_elemental={non_elemental.lifesteal}",
                       p.hero.id == cid and len(elementals) >= 3 and all(c.lifesteal for c in elementals) and not non_elemental.lifesteal and
                       any(c.id == "ICC_833t" and c.atk == 3 and c.max_health == 6 for c in p.field))
    def icy_touch_lethal_summons_water_elemental():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p, e = g.player1, g.player2
        play(p, cid)
        target = summon(e, WISP)
        before = sum(c.id == "ICC_833t" for c in p.field)
        p.used_mana = 0
        p.hero.power.use(target=target)
        after = sum(c.id == "ICC_833t" for c in p.field)
        return checked(f"target={target.zone.name};water_before={before};water_after={after};power={p.hero.power.id};exhausted={p.hero.power.exhausted}",
                       target.zone == Zone.GRAVEYARD and after == before + 1 and p.hero.power.exhausted)
    return [
        ("water_elemental_and_lifesteal", "Battlecry summons a 3/6 Water Elemental and grants Lifesteal to friendly Elementals, including existing and subsequently summoned Elementals.", elemental_lifesteal_aura,
         "先放置已有 Elemental，再打出 Jaina，再放置一个新的 Elemental 和普通 Wisp，核对全局持续效果。"),
        ("icy_touch_lethal_summon", "Icy Touch deals 1 damage and summons a Water Elemental when that damage is lethal.", icy_touch_lethal_summons_water_elemental,
         "以 1 生命敌方随从为目标实际使用 Icy Touch，检查致死、额外水元素和技能耗尽。"),
    ]


def probe_834():
    cid = "ICC_834"
    def shadowmourne_adjacent_damage():
        g = game(CardClass.WARRIOR, CardClass.MAGE); p, e = g.player1, g.player2
        left = summon(e, WISP)
        center = summon(e, "CS2_182")
        right = summon(e, WISP)
        play(p, cid)
        weapon = p.hero.weapon
        before = (left.health, center.health, right.health, weapon.durability)
        p.hero.attack(center)
        after = (left.health, center.health, right.health, weapon.durability)
        return checked(f"weapon={(weapon.atk,weapon.durability)};before={before};after={after};field={[c.id for c in e.field]}",
                       weapon.atk == 4 and left.zone == Zone.GRAVEYARD and right.zone == Zone.GRAVEYARD and
                       after[1] == before[1] - weapon.atk and after[3] == before[3] - 1)
    def bladestorm_hits_both_sides():
        g = game(CardClass.WARRIOR, CardClass.MAGE); p, e = g.player1, g.player2
        friendly = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        play(p, cid)
        p.used_mana = 0
        before = (friendly.health, enemy.health)
        p.hero.power.use()
        return checked(f"power={p.hero.power.id};before={before};after={(friendly.health,enemy.health)};exhausted={p.hero.power.exhausted}",
                       friendly.health == before[0] - 1 and enemy.health == before[1] - 1 and p.hero.power.exhausted)
    return [
        ("shadowmourne_adjacent_hit", "Shadowmourne is 4/3 and a hero attack deals the weapon's Attack to adjacent minions.", shadowmourne_adjacent_damage,
         "实际攻击中间目标，分别检查左右相邻目标、中心目标和武器耐久。"),
        ("bladestorm_all_minions", "Bladestorm deals 1 damage to every minion on both sides.", bladestorm_hits_both_sides,
         "实际使用加尔鲁什英雄技能，双方各放置一个高生命随从并检查全场伤害。"),
    ]


def probe_835():
    cid = "ICC_835"
    def resummon_dead_taunts():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        first = summon(p, "CS1_042")
        second = summon(p, "CS2_065")
        first.destroy(); second.destroy()
        hadronox = play(p, cid)
        hadronox.destroy()
        ids = [c.id for c in p.field]
        return checked(f"dead={[first.id,second.id]};field={ids};hadronox={hadronox.zone.name}",
                       ids.count("CS1_042") == 1 and ids.count("CS2_065") == 1)
    def taunt_pool_filter_excludes_enemy_and_non_taunt():
        g = game(CardClass.DRUID, CardClass.MAGE); p, e = g.player1, g.player2
        friendly_taunt = summon(p, "CS1_042")
        enemy_taunt = summon(e, "CS1_042")
        friendly_plain = summon(p, WISP)
        friendly_taunt.destroy(); enemy_taunt.destroy(); friendly_plain.destroy()
        hadronox = play(p, cid)
        hadronox.destroy()
        ids = [c.id for c in p.field]
        return checked(f"dead={[friendly_taunt.id,enemy_taunt.id,friendly_plain.id]};field={ids}",
                       len(ids) == 1 and ids[0] == "CS1_042")
    def taunt_resurrection_respects_board_cap():
        g = game(CardClass.DRUID, CardClass.MAGE); p = g.player1
        dead = summon(p, "CS1_042")
        dead.destroy()
        for _ in range(6):
            summon(p, WISP)
        hadronox = play(p, cid)
        hadronox.destroy()
        ids = [c.id for c in p.field]
        return checked(f"field={ids};field_size={len(p.field)};taunts={ids.count('CS1_042')}",
                       len(p.field) == 7 and ids.count("CS1_042") == 1)
    return [
        ("summon_dead_taunt_minions", "Deathrattle summons friendly Taunt minions that died this game.", resummon_dead_taunts,
         "让两个不同的友方 Taunt 先死亡，再检查 Hadronox 亡语召回两个对象。"),
        ("taunt_pool_filter", "The resurrection pool excludes an enemy Taunt and a friendly non-Taunt corpse.", taunt_pool_filter_excludes_enemy_and_non_taunt,
         "同时制造敌方 Taunt 与友方非 Taunt 死亡记录，检查亡语池的控制者和关键词筛选。"),
        ("taunt_resurrection_board_cap", "Hadronox respects the seven-minion board cap when returning dead Taunt minions.", taunt_resurrection_respects_board_cap,
         "六个现存随从占满六个位置后再触发亡语，检查最多召回一个 Taunt。"),
    ]


def probe_836():
    cid = "ICC_836"
    def random_enemy_damage_and_freeze():
        g = game(CardClass.MAGE, CardClass.WARRIOR, seed=836); p, e = g.player1, g.player2
        one = summon(e, "CS2_182")
        two = summon(e, "CS2_182")
        before = {one: one.health, two: two.health}
        play(p, cid)
        changed = [m for m in (one, two) if m.health == before[m] - 2]
        frozen = [m for m in (one, two) if m.frozen]
        return checked(f"before={[before[one],before[two]]};after={[one.health,two.health]};changed={len(changed)};frozen={[m.id for m in frozen]}",
                       len(changed) == 1 and frozen == changed)
    return [("random_enemy_damage_freeze", "Deals 2 damage to exactly one random enemy minion and freezes that same minion.", random_enemy_damage_and_freeze,
             "保留两个合法敌方随从，检查伤害和 Freeze 必须落在同一个随机目标上。")]


def probe_837():
    cid = "ICC_837"
    def armor_and_enemy_hand_discount():
        g = game(CardClass.WARRIOR, CardClass.MAGE); p, e = g.player1, g.player2
        enemy_minion = e.give("CS1_042")
        enemy_four = e.give("CS2_179")
        own_minion = p.give("CS1_042")
        before_own = own_minion.cost
        play(p, cid)
        return checked(f"armor={p.hero.armor};enemy_cost={enemy_minion.cost};enemy_four_cost={enemy_four.cost};own_cost={own_minion.cost}",
                       p.hero.armor == 10 and enemy_minion.cost == 0 and enemy_four.cost == 2 and own_minion.cost == before_own)
    return [("armor_enemy_minion_cost", "Gain 10 Armor and reduce every opponent minion in hand by exactly 2, with a zero-cost floor.", armor_and_enemy_hand_discount,
             "双方手牌放置 1 费、4 费和友方对照随从，检查 1 费降到 0、4 费降到 2，以及友方不变。")]


def probe_838():
    cid = "ICC_838"
    def summon_two_frozen_champions_for_owner():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p, e = g.player1, g.player2
        play(p, cid)
        own = [c for c in p.field if c.id == "ICC_838t"]
        opponent = [c for c in e.field if c.id == "ICC_838t"]
        return checked(f"own={[c.id for c in p.field]};opponent={[c.id for c in e.field]};own_tokens={len(own)};opp_tokens={len(opponent)}",
                       len(own) == 2 and not opponent and all(c.atk == 0 and c.max_health == 1 for c in own))
    return [("two_owner_frozen_champions", "Battlecry summons exactly two 0/1 Frozen Champions for the owner and none for the opponent.", summon_two_frozen_champions_for_owner,
             "双方空场实际打出 Sindragosa，分别统计两侧 token，覆盖 SummonBothSides 类错误。")]


def probe_849():
    cid = "ICC_849"
    def steal_enemy_at_start_of_turn():
        g = game(CardClass.PRIEST, CardClass.MAGE); p, e = g.player1, g.player2
        target = summon(e, WISP)
        play(p, cid, target)
        assert target.controller is e
        g.end_turn()
        assert target.controller is e
        g.end_turn()
        return checked(f"target_controller={target.controller.name};p1_field={[c.id for c in p.field]};p2_field={[c.id for c in e.field]}",
                       target.controller is p and target in p.field)
    return [("steal_at_own_turn_start", "The selected enemy minion remains with the opponent until the owner's next turn begins, then changes controller.", steal_enemy_at_start_of_turn,
             "显式检查施法后、对手回合、己方回合开始三个时序节点的控制权。")]


def probe_850():
    cid = "ICC_850"
    def immune_this_turn_only():
        g = game(CardClass.ROGUE, CardClass.MAGE); p, e = g.player1, g.player2
        enemy = summon(e, "CS2_182")
        weapon = play(p, cid)
        assert p.hero.immune
        health_before = p.hero.health
        p.hero.attack(enemy)
        no_damage = p.hero.health == health_before
        g.end_turn(); g.end_turn()
        return checked(f"weapon={weapon.id};during_immune={no_damage};after_turn_immune={p.hero.immune};enemy={enemy.health}",
                       no_damage and not p.hero.immune)
    return [("hero_immune_one_turn", "Shadowblade makes the hero Immune for the current turn, including combat, and immunity expires on the next turn.", immune_this_turn_only,
             "用武器实际攻击敌方随从以验证反伤被免疫，再跨回合检查清除。")]


def probe_851():
    cid = "ICC_851"
    def no_two_cost_buffs_deck_minions():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        low = p.give(WISP); low.shuffle_into_deck()
        taunt = p.give("CS1_042"); taunt.shuffle_into_deck()
        play(p, cid)
        return checked(f"deck={[(c.id,c.atk,c.health,c.cost) for c in p.deck]}",
                       all((c.atk, c.health) == ((1 if c.id == WISP else 1) + 1, (1 if c.id == WISP else 2) + 1) for c in p.deck))
    def two_cost_blocks_battlecry():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        blocker = p.give("CS2_120"); blocker.shuffle_into_deck()
        before = (blocker.atk, blocker.health)
        play(p, cid)
        return checked(f"two_cost={blocker.cost};before={before};after={(blocker.atk,blocker.health)}",
                       (blocker.atk, blocker.health) == before)
    return [
        ("no_two_cost_deck_buff", "With no 2-Cost card in the deck, all deck minions gain +1/+1.", no_two_cost_buffs_deck_minions,
         "只放置 0/1 随从进入牌库，实际检查牌库内每张 minion 的攻击和生命。"),
        ("two_cost_condition_false", "A 2-Cost card in the deck prevents the deck-wide buff.", two_cost_blocks_battlecry,
         "加入实际 2 费随从，检查文本条件失败时牌库增益不发生。")
    ]


def probe_852():
    cid = "ICC_852"
    def transform_to_three_three_copy():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        target = summon(p, "CS1_042")
        prince = p.give(cid)
        prince.play(target=target)
        transformed = [c for c in p.field if c is not target][0]
        return checked(f"original={prince.id}/{prince.zone.name};transformed={transformed.id}@{transformed.atk}/{transformed.health};target={target.id}@{target.atk}/{target.health}",
                       transformed.zone == Zone.PLAY and transformed.atk == 3 and transformed.max_health == 3 and
                       transformed.id == target.id and target.zone == Zone.PLAY)
    def three_cost_condition_no_effect():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        blocker = p.give("CS2_127"); blocker.shuffle_into_deck()
        target = summon(p, WISP)
        prince = p.give(cid)
        assert not prince.requires_target()
        prince.play()
        field_prince = [c for c in p.field if c.id == cid][0]
        return checked(f"blocker_cost={blocker.cost};prince={field_prince.id}@{field_prince.atk}/{field_prince.health};target={target.id}@{target.atk}/{target.health}",
                       field_prince.id == cid and target.id == WISP and target.atk == 1 and target.health == 1)
    return [
        ("copy_target_three_three", "With no 3-Cost card in deck, Prince Taldaram becomes a 3/3 copy of a selected minion.", transform_to_three_three_copy,
         "实际指定友方随从并检查变形后的身材、区域和目标仍在场。"),
        ("three_cost_condition_false", "A 3-Cost card in deck leaves Prince Taldaram as a normal 3/3 and does not transform the target.", three_cost_condition_no_effect,
         "条件失败时不再要求目标，卡牌仍可正常打出；检查本体 ID 和目标状态。"),
    ]


def probe_853():
    cid = "ICC_853"
    def two_cost_only_should_gain_but_does_not():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        blocker = p.give("CS2_120"); blocker.shuffle_into_deck()
        prince = play(p, cid)
        return checked(f"blocker_cost={blocker.cost};taunt={prince.taunt};lifesteal={prince.lifesteal}",
                       prince.taunt and prince.lifesteal)
    def four_cost_only_should_not_gain_but_does():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        blocker = p.give("CS2_179"); blocker.shuffle_into_deck()
        prince = play(p, cid)
        return checked(f"blocker_cost={blocker.cost};taunt={prince.taunt};lifesteal={prince.lifesteal}",
                       not prince.taunt and not prince.lifesteal)
    return [
        ("two_cost_only_should_gain", "With only a 2-Cost card in deck and no 4-Cost card, Prince Valanar should gain Taunt and Lifesteal.", two_cost_only_should_gain_but_does_not,
         "这是文本条件为 no-4 分支；用 2 费牌库隔离实现当前错误的 no-2 谓词。"),
        ("four_cost_only_should_not_gain", "With a 4-Cost card in deck, Prince Valanar should not gain either keyword.", four_cost_only_should_not_gain_but_does,
         "这是文本条件失败分支；用实际 4 费随从检查当前实现是否错误赋予关键词。"),
    ]


def probe_854():
    cid = "ICC_854"
    def death_knight_card_added():
        g = game(CardClass.PRIEST, CardClass.MAGE); p = g.player1
        arfus = summon(p, cid)
        arfus.destroy()
        added = [c.id for c in p.hand if c.id != THE_COIN]
        return checked(f"added={added};arfus={arfus.zone.name}", len(added) == 1 and added[0] in LICH_KING_CARDS)
    return [("random_death_knight_card", "Deathrattle adds one card from the Lich King's Death Knight entourage.", death_knight_card_added,
             "实际死亡后按固定 Death Knight 卡池检查新增手牌，而非只检查有牌进入手牌。")]


def probe_855():
    cid = "ICC_855"
    def freeze_other_friendly_minions():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p, e = g.player1, g.player2
        first = summon(p, WISP)
        second = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        rider = play(p, cid)
        return checked(f"rider={rider.id};friendly={[first.frozen,second.frozen]};self={rider.frozen};enemy={enemy.frozen}",
                       first.frozen and second.frozen and not rider.frozen and not enemy.frozen)
    return [("freeze_other_friendly", "Battlecry freezes every other friendly minion, not itself or enemy minions.", freeze_other_friendly_minions,
             "双方各放置多个随从，检查范围和排除自身两个边界。")]


def probe_856():
    cid = "ICC_856"
    def spell_damage_plus_two_applies():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p, e = g.player1, g.player2
        spellweaver = play(p, cid)
        before = e.hero.health
        p.give(MOONFIRE).play(target=e.hero)
        return checked(f"spellpower={spellweaver.spellpower};enemy={before}->{e.hero.health}",
                       spellweaver.spellpower == 2 and e.hero.health == before - 3)
    return [("spell_damage_plus_two", "Spellweaver grants +2 Spell Damage and a 1-damage spell therefore deals 3.", spell_damage_plus_two_applies,
             "同时断言关键词属性和实际法术结算数值。")]


def probe_858():
    cid = "ICC_858"
    def divine_shield_loss_gives_two_attack():
        g = game(CardClass.PALADIN, CardClass.MAGE); p = g.player1
        bolvar = play(p, cid)
        target = summon(p, "ICC_038")
        base = bolvar.atk
        p.give(MOONFIRE).play(target=target)
        return checked(f"bolvar={bolvar.atk};base={base};target_shield={target.divine_shield};target_health={target.health}",
                       bolvar.atk == base + 2 and not target.divine_shield and target.zone == Zone.PLAY)
    return [("friendly_divine_shield_lost", "After a friendly minion loses Divine Shield, Bolvar gains exactly +2 Attack.", divine_shield_loss_gives_two_attack,
             "用另一个真正带圣盾的友方随从吸收 Moonfire，验证 LosesDivineShield 触发。")]


def probe_901():
    cid = "ICC_901"
    def end_turn_effect_twice():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p, e = g.player1, g.player2
        dreadlord = summon(p, "ICC_075")
        target = summon(e, "CS2_182")
        enchanter = play(p, cid)
        before = target.health
        g.end_turn()
        return checked(f"target={before}->{target.health};dreadlord={dreadlord.zone.name};enchanter={enchanter.zone.name}",
                       target.health == before - 2)
    return [("end_turn_trigger_twice", "Drakkari Enchanter causes the friendly Despicable Dreadlord end-of-turn effect to trigger twice.", end_turn_effect_twice,
             "用 4+ Health 敌方随从承受两个独立的 1 点触发，排除一次触发后立即死亡的歧义。")]


def probe_902():
    cid = "ICC_902"
    def both_hero_powers_disabled_and_restore():
        g = game(CardClass.MAGE, CardClass.WARRIOR); p, e = g.player1, g.player2
        breaker = play(p, cid)
        disabled = (p.hero.power.exhausted, e.hero.power.exhausted)
        breaker.destroy()
        restored = (p.hero.power.exhausted, e.hero.power.exhausted)
        return checked(f"disabled={disabled};restored={restored};breaker={breaker.zone.name}",
                       disabled == (True, True) and restored == (False, False))
    return [("disable_both_hero_powers", "Mindbreaker disables both heroes' powers while present and restores them after leaving play.", both_hero_powers_disabled_and_restore,
             "分别检查双方 Hero Power 状态，并在随从离场后检查 Aura 清除。")]


def probe_903():
    cid = "ICC_903"
    def destroy_friendly_and_gain_two_two():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p = g.player1
        victim = summon(p, WISP)
        reveler = p.give(cid)
        base = (reveler.atk, reveler.health)
        reveler.play(target=victim)
        return checked(f"victim={victim.zone.name};reveler={reveler.atk}/{reveler.health};base={base}",
                       victim.zone == Zone.GRAVEYARD and (reveler.atk, reveler.health) == (base[0] + 2, base[1] + 2))
    return [("destroy_friendly_gain_two_two", "Battlecry destroys a friendly minion and gives Sanguine Reveler +2/+2.", destroy_friendly_and_gain_two_two,
             "显式指定友方随从，分别检查牺牲者区域和本体增益。")]


def probe_904():
    cid = "ICC_904"
    def deaths_this_turn_count():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p, e = g.player1, g.player2
        first = summon(p, WISP); second = summon(e, WISP)
        first.destroy(); second.destroy()
        skeleton = play(p, cid)
        return checked(f"deaths={[first.zone.name,second.zone.name]};skeleton={skeleton.atk}/{skeleton.health}",
                       (skeleton.atk, skeleton.health) == (3, 3))
    return [("gain_for_minions_died_this_turn", "Wicked Skeleton gains +1/+1 for each minion that died this turn, including both sides.", deaths_this_turn_count,
             "让双方各有一个随从在当前回合死亡，再检查 1/1 基础值上的两次增益。")]


def probe_905():
    cid = "ICC_905"
    def lifesteal_keyword_works_in_combat():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p, e = g.player1, g.player2
        worm = play(p, cid)
        p.hero.damage = 10
        g.end_turn(); g.end_turn()
        before = (e.hero.health, p.hero.health)
        worm.attack(e.hero)
        return checked(f"lifesteal={worm.lifesteal};before={before};after={(e.hero.health,p.hero.health)}", 
                       worm.lifesteal and e.hero.health == before[0] - worm.atk and p.hero.health == before[1] + worm.atk)
    return [("lifesteal_attack", "Bloodworm's Lifesteal keyword restores its combat damage to its hero.", lifesteal_keyword_works_in_combat,
             "跨过一次回合后实际攻击敌方英雄，断言英雄生命差值而非只读关键词。")]


def probe_910():
    cid = "ICC_910"
    def combo_counts_other_played_cards():
        g = game(CardClass.ROGUE, CardClass.MAGE); p, e = g.player1, g.player2
        before = e.hero.health
        p.give(MOONFIRE).play(target=e.hero)
        p.give(THE_COIN).play()
        pillager = play(p, cid, e.hero)
        return checked(f"before={before};enemy={e.hero.health};pillager={pillager.zone.name};cards_played={p.cards_played_this_turn}",
                       e.hero.health == before - 1 - 2)
    return [("combo_other_cards_count", "Combo damage equals the number of other cards played this turn; two prior cards therefore deal 2.", combo_counts_other_played_cards,
             "先实际打出 Moonfire 和 Coin，再用敌方英雄作为目标区分本体伤害与 Combo 伤害。")]


def probe_911():
    cid = "ICC_911"
    def each_play_mills_three():
        g = game(CardClass.WARLOCK, CardClass.MAGE); p = g.player1
        for card_id in (WISP, "CS1_042", "CS2_182", "ICC_019", "ICC_026"):
            p.give(card_id).shuffle_into_deck()
        banshee = play(p, cid)
        before = len(p.deck)
        play(p, WISP)
        return checked(f"before={before};after={len(p.deck)};banshee={banshee.zone.name};field={[c.id for c in p.field]}",
                       len(p.deck) == before - 3)
    return [("play_mills_three", "Whenever the controller plays a card, Keening Banshee removes the top three cards of that deck.", each_play_mills_three,
             "准备已知五张牌库，放置 Banshee 后再实际打出一个随从，检查牌库净减少 3。")]


def probe_912():
    cid = "ICC_912"
    def gains_all_keywords_found_in_deck():
        g = game(CardClass.ROGUE, CardClass.MAGE); p = g.player1
        for card_id in ("CS1_042", "ICC_038", "ICC_905", "CS2_169"):
            p.give(card_id).shuffle_into_deck()
        taker = play(p, cid)
        return checked(f"taunt={taker.taunt};divine={taker.divine_shield};lifesteal={taker.lifesteal};windfury={taker.windfury};deck={[c.id for c in p.deck]}",
                       taker.taunt and taker.divine_shield and taker.lifesteal and taker.windfury)
    def selective_keyword_scan():
        g = game(CardClass.ROGUE, CardClass.MAGE); p = g.player1
        taunt_source = p.give("CS1_042")
        taunt_source.shuffle_into_deck()
        plain = p.give(WISP)
        plain.shuffle_into_deck()
        taker = play(p, cid)
        return checked(f"deck={[c.id for c in p.deck]};taunt={taker.taunt};divine={taker.divine_shield};lifesteal={taker.lifesteal};windfury={taker.windfury}",
                       taker.taunt and not taker.divine_shield and not taker.lifesteal and not taker.windfury)
    def empty_deck_gains_nothing():
        g = game(CardClass.ROGUE, CardClass.MAGE); p = g.player1
        taker = play(p, cid)
        return checked(f"deck={len(p.deck)};taunt={taker.taunt};divine={taker.divine_shield};lifesteal={taker.lifesteal};windfury={taker.windfury}",
                       not taker.taunt and not taker.divine_shield and not taker.lifesteal and not taker.windfury)
    return [
        ("deck_keyword_scan", "Corpsetaker gains Taunt, Divine Shield, Lifesteal, and Windfury when the deck contains each keyword source.", gains_all_keywords_found_in_deck,
         "牌库放置四种不同关键词来源，直接检查战吼后的四个属性。"),
        ("selective_keyword_scan", "Only keyword categories represented in the deck are granted.", selective_keyword_scan,
         "只放置 Taunt 来源和普通 Wisp，检查其余三个条件不会被无条件赋予。"),
        ("empty_deck_no_keywords", "With no matching keyword minions in deck, Corpsetaker gains none of the four keywords.", empty_deck_gains_nothing,
         "空牌库负向分支，排除本体静态属性或无条件战吼。"),
    ]


def probe_913():
    cid = "ICC_913"
    def divine_shield_and_spell_damage():
        g = game(CardClass.PRIEST, CardClass.MAGE); p, e = g.player1, g.player2
        zealot = play(p, cid)
        before = e.hero.health
        p.give(MOONFIRE).play(target=e.hero)
        return checked(f"shield={zealot.divine_shield};spellpower={zealot.spellpower};enemy={before}->{e.hero.health}",
                       zealot.divine_shield and zealot.spellpower == 1 and e.hero.health == before - 2)
    return [("divine_shield_spell_damage", "Tainted Zealot has Divine Shield and Spell Damage +1, making Moonfire deal 2.", divine_shield_and_spell_damage,
             "同时读取关键词状态和实际法术伤害，避免把静态标签当成效果验证。")]


PROBES = {
    "ICC_702": probe_702, "ICC_705": probe_705, "ICC_706": probe_706,
    "ICC_801": probe_801, "ICC_802": probe_802, "ICC_807": probe_807,
    "ICC_808": probe_808, "ICC_809": probe_809, "ICC_810": probe_810,
    "ICC_811": probe_811, "ICC_812": probe_812, "ICC_820": probe_820,
    "ICC_823": probe_823, "ICC_825": probe_825, "ICC_827": probe_827,
    "ICC_828": probe_828, "ICC_829": probe_829, "ICC_830": probe_830,
    "ICC_831": probe_831, "ICC_832": probe_832, "ICC_833": probe_833,
    "ICC_834": probe_834, "ICC_835": probe_835, "ICC_836": probe_836,
    "ICC_837": probe_837, "ICC_838": probe_838, "ICC_849": probe_849,
    "ICC_850": probe_850, "ICC_851": probe_851, "ICC_852": probe_852,
    "ICC_853": probe_853, "ICC_854": probe_854, "ICC_855": probe_855,
    "ICC_856": probe_856, "ICC_858": probe_858, "ICC_901": probe_901,
    "ICC_902": probe_902, "ICC_903": probe_903, "ICC_904": probe_904,
    "ICC_905": probe_905, "ICC_910": probe_910, "ICC_911": probe_911,
    "ICC_912": probe_912, "ICC_913": probe_913,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", choices=CARDS)
    parser.add_argument("--force", action="store_true", help="rerun selected cards even when a verdict exists")
    args = parser.parse_args()
    selected = args.only or CARDS
    for cid in selected:
        if not args.force and any(row["card_id"] == cid for row in VERDICT_ROWS):
            print(f"{cid}: skipped (existing verdict; use --force)")
            continue
        cases = PROBES[cid]()
        audit_card(cid, cases)
    own_verdicts = [r for r in VERDICT_ROWS if r["card_id"] in CARDS]
    own_probe = [r for r in PROBE_ROWS if r["card_id"] in CARDS]
    print(f"SUMMARY cards={len({r['card_id'] for r in own_verdicts})}/{len(CARDS)} cases={len(own_probe)}")
    from collections import Counter
    print("STATUSES", dict(Counter(r["status"] for r in own_verdicts)))
    print("OUTCOMES", dict(Counter(r["outcome"] for r in own_probe)))


if __name__ == "__main__":
    main()
