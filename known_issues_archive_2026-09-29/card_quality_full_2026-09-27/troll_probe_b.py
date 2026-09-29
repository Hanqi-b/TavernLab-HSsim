"""Targeted live-game probes for the frozen indices 45:90 ordinary TROLL YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, MOONFIRE, THE_COIN, prepare_empty_game  # noqa: E402

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "troll_probe_b.csv"
VERDICT_OUT = HERE / "troll_verdict_b.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_ROWS = [r for r in read_csv(BASELINE) if r["set"].startswith("Rastakhan's Rumble") and r["scope"] == "ordinary_collectible"]
OWN_ROWS = BASE_ROWS[45:90]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
assert len(OWN_IDS) == 45 and OWN_IDS[0] == "TRL_260" and OWN_IDS[-1] == "TRL_409"
assert len(set(OWN_IDS)) == 45 and OWN_IDS == sorted(OWN_IDS)
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY)}
PROBE_ROWS = read_csv(PROBE_OUT) if PROBE_OUT.exists() else []
VERDICT_ROWS = read_csv(VERDICT_OUT) if VERDICT_OUT.exists() else []


def new_game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=904):
    random.seed(seed)
    game = prepare_empty_game(class1, class2)
    game.random.seed(seed)
    if game.current_player is not game.player1:
        game.end_turn()
    assert game.current_player is game.player1
    for player in game.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    return game


def play(player, card_id, target=None, choose=None, index=None):
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    if index is not None:
        kwargs["index"] = index
    card.play(**kwargs)
    return card


def summon(player, card_id):
    return player.summon(card_id)


def put_deck(player, card_id, count=1):
    for _ in range(count):
        player.give(card_id).shuffle_into_deck()


def find_hand(player, *card_ids):
    return next((card for card in player.hand if card.id in card_ids), None)


def card_state(card):
    if card is None:
        return None
    stats = (card.atk, card.health) if card.type == CardType.MINION else None
    return (card.id, int(card.type), card.zone.name, card.cost, stats)


def end_round(game):
    game.end_turn()
    game.end_turn()


def checked(observed, condition):
    assert condition, observed
    return observed


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    old = QUALITY_BY_ID.get(card_id, {})
    return (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or master.get('xml_source', '')}; "
        f"existing_tests={master.get('test_refs_candidate', '') or 'none'}; "
        f"previous={old.get('status', 'unknown')}:{old.get('reason', 'no prior reason')}"
    )


def record(card_id, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except AssertionError as exc:
        observed = str(exc)
        if not observed:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    PROBE_ROWS.append({
        "card_id": card_id,
        "case_id": case_id,
        "expected": expected,
        "observed": observed,
        "outcome": outcome,
        "notes": f"{notes}; {metadata(card_id)}",
    })
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    print(f"{card_id} {case_id}: {outcome} — {observed}")
    return outcome


def finish_card(card_id, blocker=None):
    rows = [r for r in PROBE_ROWS if r["card_id"] == card_id]
    assert rows and len({r["case_id"] for r in rows}) == len(rows)
    errors = [r for r in rows if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in rows if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{r['case_id']} expected=[{r['expected']}] actual=[{r['observed']}]" for r in errors)
    elif unresolved:
        status = "YELLOW"
        reason = "关键行为运行未决：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in unresolved)
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "本轮逐卡行为用例全部通过：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in rows)
    master = MASTER_BY_ID[card_id]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS.append({
        "card_id": card_id,
        "status": status,
        "mechanic_scope": QUALITY_BY_ID[card_id]["mechanic"],
        "reason": reason,
        "probe_file": PROBE_OUT.name,
        "notes": metadata(card_id),
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{card_id}: {status} ({len(rows)} cases)")
    return status


def audit(card_id, tests, blocker=None):
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    for case_id, expected, func, notes in tests:
        record(card_id, case_id, expected, func, notes)
    return finish_card(card_id, blocker)


def bwonsamdi_the_dead():
    cid = "TRL_260"

    def draws_one_cost_minions_until_hand_full():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=2601)
        p = g.player1
        fillers = [p.give(WISP) for _ in range(7)]
        put_deck(p, "EX1_011", 3)
        put_deck(p, "CS2_182", 2)
        minion = play(p, cid)
        drawn = [c for c in p.hand if c.id == "EX1_011"]
        observed = f"body={minion.id}:{minion.atk}/{minion.health}:{minion.zone.name};hand_count={len(p.hand)};filler_count={sum(c.id == WISP for c in p.hand)};drawn_one_cost={[card_state(c) for c in drawn]};deck={[c.id for c in p.deck]};filler_entities={[c.zone.name for c in fillers]}"
        return checked(observed, minion.zone == Zone.PLAY and (minion.atk, minion.health) == (7, 7) and len(p.hand) == 10 and sum(c.id == WISP for c in p.hand) == 7 and len(drawn) == 3 and all(c.cost == 1 and c.type == CardType.MINION and c.zone == Zone.HAND for c in drawn) and sum(c.id == "CS2_182" for c in p.deck) == 2)

    def stops_when_no_one_cost_minions_remain():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=2602)
        p = g.player1
        p.give(WISP)
        p.give("CS2_029")
        put_deck(p, "EX1_011", 1)
        put_deck(p, "CS2_182", 2)
        minion = play(p, cid)
        drawn = [c for c in p.hand if c.id == "EX1_011"]
        observed = f"hand_count={len(p.hand)};drawn={[card_state(c) for c in drawn]};ineligible_left={sum(c.id == 'CS2_182' for c in p.deck)};deck={[c.id for c in p.deck]}"
        return checked(observed, minion.zone == Zone.PLAY and len(p.hand) == 3 and len(drawn) == 1 and drawn[0].zone == Zone.HAND and sum(c.id == "CS2_182" for c in p.deck) == 2)

    return audit(cid, [
        ("draw_one_cost_minions_to_hand_limit", "Bwonsamdi draws 1-Cost minions from deck until hand reaches 10, without drawing ineligible higher-cost minions.", draws_one_cost_minions_until_hand_full, "手牌先留7张Wisp，牌库放3张1费随从及2张高费Yeti；打出7/7后检查手牌补满、三张1费均进手且两张Yeti留牌库。"),
        ("stop_when_no_eligible_minions", "When the deck has only one eligible 1-Cost minion, draw it and stop even though hand has room and higher-cost minions remain.", stops_when_no_one_cost_minions_remain, "保留两张手牌，牌库仅有一张1费随从及两张高费Yeti；核对只抽取唯一合格牌后停止并保留不合格牌。"),
    ])


bwonsamdi_the_dead.card_id = "TRL_260"


def shirvallah_the_tiger():
    cid = "TRL_300"

    def discounts_by_spell_mana_and_keeps_keywords():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3001)
        p = g.player1
        tiger = p.give(cid)
        initial = tiger.cost
        play(p, "CS2_024", target=g.player2.hero)  # Frostbolt, 2 mana
        after = tiger.cost
        observed = f"base_cost={initial};after_2_mana_spell={after};spent_spell_mana={getattr(p, 'spent_mana_on_spells_this_game', 'attr-unavailable')};keywords={{shield:{tiger.divine_shield},rush:{tiger.rush},lifesteal:{tiger.lifesteal}}}"
        return checked(observed, initial == 25 and after == 23 and tiger.divine_shield and tiger.rush and tiger.lifesteal)

    return audit(cid, [("spell_mana_discount_and_keywords", "Shirvallah costs 1 less for each mana spent on spells and has Divine Shield, Rush, and Lifesteal.", discounts_by_spell_mana_and_keeps_keywords, "先记录手中25费基础消耗，实际施放2费寒冰箭后检查减费为23并逐个核对三项关键词。")])


shirvallah_the_tiger.card_id = "TRL_300"


def time_out():
    cid = "TRL_302"

    def immune_until_next_turn():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3021)
        p, e = g.player1, g.player2
        timeout = play(p, cid)
        during = (p.hero.health, p.hero.armor, p.hero.cant_be_damaged, len(p.hero.buffs), [(b.id, b.zone.name) for b in timeout.buffs])
        g.end_turn()
        g.end_turn()
        after = (p.hero.health, p.hero.armor, p.hero.cant_be_damaged)
        observed = f"during={during};after_own_turn_begins={after}"
        return checked(observed, during[0:3] == (30, 0, True) and after[2] is False)

    def prevents_combat_damage_during_window():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3022)
        p, e = g.player1, g.player2
        play(p, cid)
        g.end_turn()
        weapon = e.give("CS2_091").play()
        before = p.hero.health
        e.hero.attack(p.hero)
        observed = f"weapon={weapon.id}:{weapon.atk}/{weapon.durability};hero_health_before={before};after={p.hero.health};immune={p.hero.cant_be_damaged}"
        return checked(observed, p.hero.health == before and p.hero.cant_be_damaged)

    return audit(cid, [
        ("immune_to_spell_until_expiry", "Time Out prevents spell damage until the Paladin's next turn, then expires.", immune_until_next_turn, "施放后由敌方法术指定英雄验证免疫阻止伤害，再经过敌方回合到己方回合开始确认效果清除。"),
        ("immune_to_combat_damage", "The immune hero takes no weapon combat damage during the window.", prevents_combat_damage_during_window, "在免疫持续的敌方回合装备公正之剑并攻击己方英雄，核对生命不变。"),
    ])


time_out.card_id = "TRL_302"


def farraki_battleaxe():
    cid = "TRL_304"

    def overkill_buffs_a_minion_in_hand():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3041)
        p, e = g.player1, g.player2
        hand_minion = p.give("CS2_182")
        weapon = play(p, cid)
        target = summon(e, WISP)
        before = (hand_minion.atk, hand_minion.health)
        p.hero.attack(target)
        observed = f"weapon={weapon.id}:{weapon.atk}/{weapon.durability};target_zone={target.zone.name};hand_minion_before={before};after={(hand_minion.atk, hand_minion.health)};hand_entity={hand_minion.zone.name}"
        return checked(observed, target.zone == Zone.GRAVEYARD and (hand_minion.atk, hand_minion.health) == (before[0] + 2, before[1] + 2) and hand_minion.zone == Zone.HAND)

    return audit(cid, [("overkill_hand_minion_buff", "A minion killed with excess weapon damage triggers Overkill and grants a hand minion +2/+2.", overkill_buffs_a_minion_in_hand, "装备战斧后以武器攻击1/1 Wisp，核对超杀使手中4/5 Yeti变成6/7且仍留在手牌。")])


farraki_battleaxe.card_id = "TRL_304"


def a_new_challenger():
    cid = "TRL_305"

    def discovers_six_cost_and_summons_keyworded_minion():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3051)
        p = g.player1
        play(p, cid)
        choice = p.choice
        offered = [(c.id, c.cost, int(c.type)) for c in choice.cards]
        assert len(offered) >= 1 and all(cost == 6 and kind == int(CardType.MINION) for _, cost, kind in offered), offered
        selected = choice.cards[0]
        selected_id = selected.id
        choice.choose(selected)
        summoned = next((c for c in p.field if c.id == selected_id), None)
        observed = f"offered={offered};selected={selected_id};summoned={card_state(summoned)};taunt={getattr(summoned, 'taunt', False)};divine_shield={getattr(summoned, 'divine_shield', False)};choice_open={bool(p.choice)}"
        return checked(observed, summoned is not None and summoned.zone == Zone.PLAY and summoned.cost == 6 and summoned.taunt and summoned.divine_shield and not p.choice)

    return audit(cid, [("discover_six_cost_and_summon", "Discover only 6-Cost minions, then summon the selected one with Taunt and Divine Shield.", discovers_six_cost_and_summons_keyworded_minion, "实际打开发现选项、逐个核对候选费用/类型、选择其中一张后检查它进入场上且获得嘲讽和圣盾。")])


a_new_challenger.card_id = "TRL_305"


def immortal_prelate():
    cid = "TRL_306"

    def deathrattle_shuffles_same_buffed_minion():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3061)
        p = g.player1
        prelate = play(p, cid)
        p.give("CS2_087").play(target=prelate)  # Blessing of Might, +3 Attack
        buffed = prelate.atk
        prelate.destroy()
        shuffled = [c for c in p.deck if c.id == cid]
        observed = f"prelate_zone={prelate.zone.name};buffed_attack={buffed};deck={[card_state(c) for c in shuffled]};deck_size={len(p.deck)}"
        return checked(observed, prelate.zone == Zone.DECK and len(shuffled) == 1 and shuffled[0].atk == 4 and shuffled[0].health == 3 and shuffled[0].zone == Zone.DECK)

    return audit(cid, [("deathrattle_shuffle_keeps_enchantment", "Immortal Prelate shuffles into its owner's deck after death and retains its enchantment.", deathrattle_shuffles_same_buffed_minion, "对场上先知施放力量祝福后摧毁，按牌库区域与4/2当前身材检查同一张牌被洗回并保留+3攻击附魔。")])


immortal_prelate.card_id = "TRL_306"


def flash_of_light():
    cid = "TRL_307"

    def heals_target_and_draws():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3071)
        p = g.player1
        put_deck(p, WISP)
        p.hero.hit(6)
        before = (p.hero.health, len(p.hand), len(p.deck))
        play(p, cid, target=p.hero)
        observed = f"before={before};after={(p.hero.health, len(p.hand), len(p.deck))};drawn={[card_state(c) for c in p.hand if c.id == WISP]}"
        return checked(observed, p.hero.health == 28 and len(p.hand) == 1 and len(p.deck) == 0 and find_hand(p, WISP) is not None)

    def can_heal_a_damaged_minion_and_draw():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3072)
        p = g.player1
        put_deck(p, "CS2_182")
        target = summon(p, "CS2_182")
        target.damage = 3
        before = target.health
        play(p, cid, target=target)
        observed = f"target_before={before};target_after={target.health};target_damage={target.damage};drawn_yeti={sum(c.id == 'CS2_182' for c in p.hand)};deck={len(p.deck)}"
        return checked(observed, target.health == target.max_health == 5 and target.damage == 0 and sum(c.id == "CS2_182" for c in p.hand) == 1 and len(p.deck) == 0)

    return audit(cid, [
        ("heal_hero_and_draw", "Restore 4 health to the chosen hero and draw one card.", heals_target_and_draws, "让己方英雄先受6点伤害，再以英雄为目标施放并检查恢复4点及牌库顶牌进入手牌。"),
        ("heal_minion_and_draw", "Restore 4 health to a damaged minion and still draw one card.", can_heal_a_damaged_minion_and_draw, "使友方4/5 Yeti受3伤后作为目标，核对治疗至满血并抽到牌库中唯一的Yeti。"),
    ])


flash_of_light.card_id = "TRL_307"


def high_priest_thekal():
    cid = "TRL_308"

    def preserves_one_health_converts_rest_to_armor():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3081)
        p = g.player1
        p.hero.hit(7)
        before = (p.hero.health, p.hero.armor)
        play(p, cid)
        observed = f"before={before};after={(p.hero.health, p.hero.armor)}"
        return checked(observed, before == (23, 0) and (p.hero.health, p.hero.armor) == (1, 22))

    return audit(cid, [("health_to_armor_with_one_health_floor", "High Priest Thekal converts all but 1 of current hero health to armor.", preserves_one_health_converts_rest_to_armor, "先让英雄受7伤，再检查剩余23生命转换成22护甲并保留1生命。")])


high_priest_thekal.card_id = "TRL_308"


def spirit_of_the_tiger():
    cid = "TRL_309"

    def spell_cost_sets_summoned_tiger_stats():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3091)
        p = g.player1
        spirit = play(p, cid)
        spell = p.give("CS2_029")
        spell_cost = spell.cost
        spell.play(target=g.player2.hero)
        tigers = [c for c in p.field if c.id == "TRL_309t"]
        tiger = tigers[0] if tigers else None
        observed = f"spirit={spirit.zone.name};stealth={spirit.stealthed};spell_cost={spell_cost};tigers={[card_state(c) for c in tigers]}"
        return checked(observed, spirit.zone == Zone.PLAY and spirit.stealthed and spell_cost == 4 and len(tigers) == 1 and (tiger.atk, tiger.health) == (4, 4))

    def one_cost_spell_summons_one_one_tiger():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=3092)
        p = g.player1
        play(p, cid)
        spell = p.give("CS2_027")  # Mirror Image, 1-Cost spell
        spell_cost = spell.cost
        spell.play()
        tigers = [c for c in p.field if c.id == "TRL_309t"]
        observed = f"mirror_image_cost={spell_cost};field_tigers={[card_state(c) for c in tigers]};other_tokens={[c.id for c in p.field if c.id != 'TRL_309' and c.id != 'TRL_309t']}"
        return checked(observed, spell_cost == 1 and len(tigers) == 1 and (tigers[0].atk, tigers[0].health) == (1, 1) and tigers[0].zone == Zone.PLAY)

    return audit(cid, [
        ("spell_cost_copies_to_tiger_stats", "After a spell resolves, summon a Tiger with attack and health equal to that spell's cost.", spell_cost_sets_summoned_tiger_stats, "潜行精魂在场时施放4费火球术，核对生成4/4老虎而不是卡牌基础身材。"),
        ("one_cost_spell_branch", "A 1-Cost spell creates a 1/1 Tiger.", one_cost_spell_summons_one_one_tiger, "用1费镜像施放分支补充检查低费用法术也按施法费用生成1/1老虎。"),
    ])


spirit_of_the_tiger.card_id = "TRL_309"


def elemental_evocation():
    cid = "TRL_310"

    def discounts_next_elemental_then_expires():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=3101)
        p = g.player1
        first = p.give("TRL_311")
        second = p.give("TRL_311")
        base = (first.cost, second.cost)
        play(p, cid)
        during = (first.cost, second.cost)
        first.play()
        after_first_elemental = (second.cost, len([c for c in p.field if c.id == "TRL_310e"]))
        observed = f"base={base};after_evocation={during};after_elemental={after_first_elemental};first_zone={first.zone.name}"
        return checked(observed, base == (6, 6) and during == (4, 4) and first.zone == Zone.PLAY and after_first_elemental == (6, 0))

    return audit(cid, [("discount_only_next_elemental_this_turn", "Both held Elementals are discounted by 2 until the first one is played; the effect then expires.", discounts_next_elemental_then_expires, "手中同时放两张6费元素随从；施放元素唤醒后两张均临时降至4费，打出一张后检查另一张恢复6费且减费效果被消耗。")])


elemental_evocation.card_id = "TRL_310"


def arcanosaur():
    cid = "TRL_311"

    def deals_three_to_all_other_minions_only_after_last_turn_elemental():
        def scenario(prior_elemental, seed):
            g = new_game(CardClass.MAGE, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            if prior_elemental:
                p.give("UNG_809t1").play()
                end_round(g)
            ally = summon(p, "CS2_182")
            foe = summon(e, "CS2_182")
            dino = play(p, cid)
            observed = f"prior_elemental={prior_elemental};arcanosaur={dino.zone.name};ally_health={ally.health};ally_damage={ally.damage};enemy_health={foe.health};enemy_damage={foe.damage};enemy_zone={foe.zone.name}"
            if prior_elemental:
                return checked(observed, ally.health == 2 and ally.damage == 3 and foe.health == 2 and foe.damage == 3 and dino.zone == Zone.PLAY)
            return checked(observed, ally.health == 5 and ally.damage == 0 and foe.health == 5 and foe.damage == 0 and dino.zone == Zone.PLAY)

        return scenario(True, 3111) + "; " + scenario(False, 3112)

    return audit(cid, [("elemental_last_turn_condition_and_self_exclusion", "If an Elemental was played last turn, deal 3 to all other minions; otherwise do not deal damage. Arcanosaur itself is excluded.", deals_three_to_all_other_minions_only_after_last_turn_elemental, "用上一回合真实打出元素和没有打出元素的两个子局面，对友方/敌方5血随从及正在进场的本体检查3点伤害与条件关闭分支。")])


arcanosaur.card_id = "TRL_311"


def spellzerker():
    cid = "TRL_312"

    def gains_spell_damage_while_damaged_and_loses_it_when_healed():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=3121)
        p, e = g.player1, g.player2
        z = play(p, cid)
        base = (z.atk, z.max_health, z.spellpower)
        target = summon(e, "CS2_182")
        p.give(MOONFIRE).play(target=z)
        damaged = (z.health, z.damage, z.spellpower)
        p.give(MOONFIRE).play(target=target)
        after_damaged_cast = (target.health, target.damage)
        p.give("CS2_089").play(target=z)
        healed = (z.health, z.damage, z.spellpower)
        p.give(MOONFIRE).play(target=target)
        after_healed_cast = (target.health, target.damage)
        observed = f"base={base};damaged={damaged};target_after_spell_while_damaged={after_damaged_cast};healed={healed};target_after_spell_when_healed={after_healed_cast};zone={z.zone.name}"
        return checked(observed, base[2] == 0 and damaged[0] == damaged[1] and damaged[2] == 2 and after_damaged_cast == (2, 3) and healed == (z.max_health, 0, 0) and after_healed_cast == (1, 4) and z.zone == Zone.PLAY)

    return audit(cid, [("spell_damage_enrage_toggles", "Spellzerker gains +2 spell damage while damaged and loses the bonus when restored to full health.", gains_spell_damage_while_damaged_and_loses_it_when_healed, "召唤法術狂熱者后以月火術打伤，再以圣光术恢复满血，核对法术伤害+2动态开启并在满血时关闭。")])


spellzerker.card_id = "TRL_312"


def scorch():
    cid = "TRL_313"

    def elemental_discount_and_four_damage():
        def scenario(prior_elemental, seed):
            g = new_game(CardClass.MAGE, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            if prior_elemental:
                p.give("UNG_809t1").play()
                end_round(g)
            target = summon(e, "CS2_182")
            scorch = p.give(cid)
            cost = scorch.cost
            scorch.play(target=target)
            observed = f"prior_elemental={prior_elemental};cost={cost};target_health={target.health};target_damage={target.damage};target_zone={target.zone.name}"
            expected_cost = 1 if prior_elemental else 4
            return checked(observed, cost == expected_cost and target.zone == Zone.PLAY and target.health == 1 and target.damage == 4)

        return scenario(False, 3131) + "; " + scenario(True, 3132)

    return audit(cid, [("conditional_cost_and_damage", "Scorch costs 1 after an Elemental last turn (otherwise 4) and deals 4 damage to a minion.", elemental_discount_and_four_damage, "分开验证普通费用与上回合打出元素后的1费分支，两局均以5血Yeti承受4点法术伤害。")])


scorch.card_id = "TRL_313"


def pyromaniac():
    cid = "TRL_315"

    def draws_only_when_hero_power_kills_minion():
        def scenario(kill, seed):
            g = new_game(CardClass.MAGE, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            pyromaniac = play(p, cid)
            put_deck(p, WISP)
            target = summon(e, WISP if kill else "CS2_182")
            p.hero.power.use(target=target)
            drawn = find_hand(p, WISP) is not None
            observed = f"kill={kill};pyromaniac={pyromaniac.zone.name};target_zone={target.zone.name};target_health={target.health};target_damage={target.damage};hand_wisp={drawn};deck={len(p.deck)}"
            if kill:
                return checked(observed, target.zone == Zone.GRAVEYARD and drawn and len(p.deck) == 0)
            return checked(observed, target.zone == Zone.PLAY and target.damage == 1 and not drawn and len(p.deck) == 1)

        return scenario(True, 3151) + "; " + scenario(False, 3152)

    return audit(cid, [("hero_power_kill_trigger_only", "A hero-power kill draws one card; merely damaging a surviving minion does not.", draws_only_when_hero_power_kills_minion, "用法師英雄技能分別击杀1血Wisp和仅打伤5血Yeti，对照牌库抽牌/目标区域。")])


pyromaniac.card_id = "TRL_315"


def janalai_the_dragonhawk():
    cid = "TRL_316"

    def threshold_summons_ragnaros_at_eight_and_not_below():
        def scenario(power_uses, seed):
            g = new_game(CardClass.HUNTER, CardClass.HUNTER, seed=seed)
            p = g.player1
            for _ in range(power_uses):
                p.hero.power.use()
                if _ + 1 < power_uses:
                    end_round(g)
            card = p.give(cid)
            ready = card.powered_up
            card.play()
            ragnaros = [c for c in p.field if c.id == "TRL_316t"]
            observed = f"hero_power_uses={power_uses};hero_health={p.hero.health};ready={ready};ragnaros={[card_state(c) for c in ragnaros]};field={[c.id for c in p.field]}"
            return checked(observed, (len(ragnaros) == 1) == (power_uses >= 4) and (not ragnaros or ragnaros[0].zone == Zone.PLAY))

        return scenario(4, 3161) + "; " + scenario(3, 3162)

    return audit(cid, [("eight_hero_power_damage_threshold", "Summons Ragnaros after the Hunter Hero Power has dealt 8 total damage this game, and not after only 6.", threshold_summons_ragnaros_at_eight_and_not_below, "使用猎人英雄技能（每次打脸2点）真实跨回合累计4次/3次，对照8点阈值与未达阈值时炎魔生成。")])


janalai_the_dragonhawk.card_id = "TRL_316"


def blast_wave():
    cid = "TRL_317"

    def damages_all_minions_and_generates_spell_only_on_overkill():
        def scenario(overkill, seed):
            g = new_game(CardClass.MAGE, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            low = summon(p, WISP if overkill else "CS2_182")
            other = summon(e, "CS2_182")
            before = len(p.hand)
            play(p, cid)
            mage_spells = [c for c in p.hand if c.type == CardType.SPELL and c.card_class == CardClass.MAGE]
            observed = f"overkill={overkill};ally_zone={low.zone.name};ally_damage={low.damage};enemy_zone={other.zone.name};enemy_health={other.health};enemy_damage={other.damage};hand_delta={len(p.hand)-before};generated={[card_state(c) for c in mage_spells]}"
            if overkill:
                return checked(observed, low.zone == Zone.GRAVEYARD and other.damage == 2 and len(mage_spells) == 1)
            return checked(observed, low.zone == Zone.PLAY and low.damage == 2 and other.zone == Zone.PLAY and other.damage == 2 and not mage_spells)

        return scenario(True, 3171) + "; " + scenario(False, 3172)

    return audit(cid, [("all_minion_damage_and_overkill_reward", "Deals 2 to all minions; only excess lethal damage adds a random Mage spell.", damages_all_minions_and_generates_spell_only_on_overkill, "分别以1血Wisp构造超杀与两只5血Yeti构造非超杀，检查双方全场受伤及法师法术奖励是否仅在超杀时生成。")])


blast_wave.card_id = "TRL_317"


def hex_lord_malacrass():
    cid = "TRL_318"

    def copies_opening_hand_but_not_itself():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=3181)
        p = g.player1
        opening_card = p.give("CS2_182")
        p.starting_hand = [opening_card]
        malacrass = play(p, cid)
        copies = [c for c in p.hand if c.id == "CS2_182"]
        observed = f"malacrass_zone={malacrass.zone.name};opening_hand={[c.id for c in p.starting_hand]};hand_yetis={[card_state(c) for c in copies]};hand={[c.id for c in p.hand]}"
        return checked(observed, len(copies) == 2 and opening_card in copies and all(c.zone == Zone.HAND for c in copies) and malacrass.zone == Zone.PLAY)

    return audit(cid, [("copy_opening_hand_except_self", "Adds a copy of the opening-hand minion to hand while leaving the played Malacrass out.", copies_opening_hand_but_not_itself, "把Yeti作为起始手牌快照，随后打出马拉克拉斯，确认手中保留原牌并加入副本且不复制它自身。")])


hex_lord_malacrass.card_id = "TRL_318"


def spirit_of_the_dragonhawk():
    cid = "TRL_319"

    def hero_power_hits_target_and_adjacent_minions():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=3191)
        p, e = g.player1, g.player2
        spirit = play(p, cid)
        targets = [summon(e, "CS2_182") for _ in range(3)]
        p.hero.power.use(target=targets[1])
        observed = f"spirit_stealthed={spirit.stealthed};minions={[(c.id,c.health,c.damage,c.zone.name) for c in targets]}"
        return checked(observed, all(c.zone == Zone.PLAY and c.damage == 1 and c.health == 4 for c in targets))

    def stealth_expires_at_start_of_next_turn():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=3192)
        p = g.player1
        spirit = play(p, cid)
        stealth_now = spirit.stealthed
        end_round(g)
        observed = f"initial_stealth={stealth_now};after_next_own_turn={spirit.stealthed};zone={spirit.zone.name}"
        return checked(observed, stealth_now and not spirit.stealthed and spirit.zone == Zone.PLAY)

    return audit(cid, [
        ("hero_power_adjacent_targets", "A targeted Hero Power also affects both adjacent minions.", hero_power_hits_target_and_adjacent_minions, "場上排放三只高生命敌方随从，点选中间目标后核对左、中、右三者均受到法师英雄技能1点伤害。"),
        ("stealth_one_turn", "Spirit of the Dragonhawk is Stealthed for one turn and loses Stealth at its controller's next turn.", stealth_expires_at_start_of_next_turn, "分别检查刚打出时潜行有效以及跨越敌方回合到下一己方回合后潜行解除。"),
    ])


spirit_of_the_dragonhawk.card_id = "TRL_319"


def devastate():
    cid = "TRL_321"

    def four_damage_finishes_a_damaged_minion():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3211)
        p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        target.damage = 1
        before = (target.health, target.damage)
        play(p, cid, target=target)
        observed = f"before={before};after={(target.health,target.damage)};zone={target.zone.name};graveyard={[c.id for c in e.graveyard]}"
        return checked(observed, before == (4, 1) and target.zone == Zone.GRAVEYARD)

    return audit(cid, [("damaged_minion_takes_four", "Devastate deals 4 damage to a minion that is already damaged.", four_damage_finishes_a_damaged_minion, "先把敌方4/5 Yeti降至4点当前生命，再施放1费Devastate并检查其进入墓地。")])


devastate.card_id = "TRL_321"


def emberscale_drake():
    cid = "TRL_323"

    def armor_requires_dragon_in_hand():
        def scenario(dragon, seed):
            g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=seed)
            p = g.player1
            dragon_card = p.give("EX1_561") if dragon else None
            played = play(p, cid)
            observed = f"dragon_in_hand={dragon};dragon_card={(dragon_card.id if dragon_card else None)};armor={p.hero.armor};drake={(played.id,played.atk,played.health,played.zone.name)}"
            return checked(observed, p.hero.armor == (5 if dragon else 0) and played.zone == Zone.PLAY)

        return scenario(True, 3231) + "; " + scenario(False, 3232)

    return audit(cid, [("dragon_condition_for_five_armor", "Gain 5 armor only while holding a Dragon.", armor_requires_dragon_in_hand, "一局持有阿莱克丝塔萨龙牌、一局没有龙牌，分别打出龙鳞 drake 并核对护甲变化。")])


emberscale_drake.card_id = "TRL_323"


def heavy_metal():
    cid = "TRL_324"

    def random_minion_cost_matches_armor_with_ten_cap():
        def scenario(cap, seed):
            g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=seed)
            p = g.player1
            if cap:
                play(p, "LOOT_285t")  # Tower Shield +10: total 15 armor
                armor = p.hero.armor
                expected = 10
            else:
                play(p, "LOOT_285")  # Unidentified Shield, 5 armor
                armor = p.hero.armor
                expected = 5
            # The Coin cannot raise resources above 10, so spend the 6-cost
            # armor spell first and use two Coins to refill to 6 for this spell.
            p.give(THE_COIN).play()
            p.give(THE_COIN).play()
            before = len(p.field)
            play(p, cid)
            summoned = p.field[before:]
            observed = f"cap_case={cap};armor={armor};mana_after_coins={p.mana};temp_mana={p.temp_mana};summoned={[card_state(c) for c in summoned]};field={[c.id for c in p.field]}"
            return checked(observed, len(summoned) == 1 and summoned[0].type == CardType.MINION and summoned[0].cost == expected and summoned[0].zone == Zone.PLAY)

        return scenario(False, 3241) + "; " + scenario(True, 3242)

    return audit(cid, [("random_minion_cost_equals_armor_capped_at_ten", "Summons a random minion whose cost matches armor, capped at 10.", random_minion_cost_matches_armor_with_ten_cap, "先用未升级护盾获得5甲检查召唤5费随从，再用Tower Shield获得15甲并用幸运币支付后检查上限是10费。")])


heavy_metal.card_id = "TRL_324"


def sulthraze():
    cid = "TRL_325"

    def overkill_grants_another_hero_attack():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3251)
        p, e = g.player1, g.player2
        weapon = play(p, cid)
        first = summon(e, WISP)
        atk = weapon.atk
        p.hero.attack(first)
        can_reattack = p.hero.can_attack()
        enemy_health_before = e.hero.health
        if can_reattack:
            p.hero.attack(e.hero)
        observed = f"weapon={weapon.id}:{atk}/{weapon.durability};first_target_zone={first.zone.name};can_reattack_after_overkill={can_reattack};enemy_health_before_second={enemy_health_before};after={e.hero.health};hero_attack={p.hero.atk}"
        return checked(observed, first.zone == Zone.GRAVEYARD and can_reattack and e.hero.health == enemy_health_before - atk)

    return audit(cid, [("weapon_overkill_extra_attack", "Overkill with Sul'thraze grants an additional hero attack, usable against another target.", overkill_grants_another_hero_attack, "装备武器后攻击1/1 Wisp形成超杀，检查英雄仍可攻击并实际攻击敌方英雄一次。")])


sulthraze.card_id = "TRL_325"


def smolderthorn_lancer():
    cid = "TRL_326"

    def dragon_enables_destroy_of_damaged_enemy_only():
        def scenario(dragon, seed):
            g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            if dragon:
                p.give("EX1_561")
            target = summon(e, "CS2_182")
            target.damage = 1
            before = (target.health, target.damage)
            played = play(p, cid, target=target) if dragon else play(p, cid)
            observed = f"dragon={dragon};target_before={before};target_after={(target.health,target.damage)};target_zone={target.zone.name};lancer={played.zone.name}"
            if dragon:
                return checked(observed, target.zone == Zone.GRAVEYARD and played.zone == Zone.PLAY)
            return checked(observed, target.zone == Zone.PLAY and target.damage == 1 and played.zone == Zone.PLAY)

        return scenario(True, 3261) + "; " + scenario(False, 3262)

    return audit(cid, [("dragon_condition_destroys_damaged_target", "With a Dragon in hand, destroy a damaged enemy minion; without one, leave it alive.", dragon_enables_destroy_of_damaged_enemy_only, "两局均对敌方5血Yeti预先造成1点伤害；只在手握龙牌的局面指定其并核对死亡，无龙局核对随从存活。")])


smolderthorn_lancer.card_id = "TRL_326"


def spirit_of_the_rhino():
    cid = "TRL_327"

    def grants_same_turn_rush_immunity_then_expires():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3271)
        p, e = g.player1, g.player2
        spirit = play(p, cid)
        stealth_at_play = spirit.stealthed
        rush = play(p, "GIL_143")  # Vicious Scalehide, Rush
        target = summon(e, "CS2_182")
        rush.attack(target)
        same_turn = (rush.zone.name, rush.cant_be_damaged, target.health, target.damage)
        end_round(g)
        next_turn = (rush.zone.name, rush.cant_be_damaged)
        observed = f"spirit_stealth_at_play={stealth_at_play};same_turn_rush={same_turn};next_turn_rush={next_turn}"
        return checked(observed, stealth_at_play and same_turn == ("PLAY", True, 4, 1) and next_turn == ("PLAY", False))

    return audit(cid, [("same_turn_rush_minion_immunity", "Rush minions are immune to damage during the turn they are summoned; immunity ends next turn.", grants_same_turn_rush_immunity_then_expires, "召唤潜行的犀牛精魂与1/3突袭鳞皮兽后，当回合攻击4/5 Yeti，检查己方不受反伤且敌方仍受攻击伤害；下回合再次检查免疫解除。")])


spirit_of_the_rhino.card_id = "TRL_327"


def war_master_voone():
    cid = "TRL_328"

    def copies_every_dragon_but_not_non_dragons():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3281)
        p = g.player1
        dragon = p.give("EX1_561")
        other = p.give("CS2_182")
        played = play(p, cid)
        dragons = [c for c in p.hand if Race.DRAGON in c.races]
        yetis = [c for c in p.hand if c.id == "CS2_182"]
        observed = f"voone={played.zone.name};dragon_cards={[card_state(c) for c in dragons]};dragon_count={len(dragons)};yetis={[card_state(c) for c in yetis]};original_dragon={dragon.zone.name};original_yeti={other.zone.name}"
        return checked(observed, len(dragons) == 2 and dragon in dragons and all(c.zone == Zone.HAND for c in dragons) and len(yetis) == 1 and other in yetis and played.zone == Zone.PLAY)

    return audit(cid, [("copy_all_hand_dragons", "Copies each Dragon in hand and leaves non-Dragon cards uncopied.", copies_every_dragon_but_not_non_dragons, "同时持有一张龙牌与一张Yeti打出沃恩，核对手牌龙从1张增为2张、非龙仍只有原牌。")])


war_master_voone.card_id = "TRL_328"


def akali_the_rhino():
    cid = "TRL_329"

    def overkill_draws_and_buffs_a_rush_minion():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3291)
        p, e = g.player1, g.player2
        put_deck(p, "GIL_143")
        put_deck(p, "CS2_182")
        akali = play(p, cid)
        target = summon(e, WISP)
        akali.attack(target)
        drawn = [c for c in p.hand if c.id == "GIL_143"]
        observed = f"akali={(akali.atk,akali.health,akali.zone.name)};target={target.zone.name};drawn={[card_state(c) for c in drawn]};deck={[c.id for c in p.deck]}"
        return checked(observed, target.zone == Zone.GRAVEYARD and len(drawn) == 1 and (drawn[0].atk, drawn[0].health) == (6, 8) and drawn[0].zone == Zone.HAND and sum(c.id == "CS2_182" for c in p.deck) == 1)

    return audit(cid, [("overkill_draws_rush_and_buffs_five_five", "Overkill draws a Rush minion and gives it +5/+5, leaving non-Rush minions in the deck.", overkill_draws_and_buffs_a_rush_minion, "以突袭的Akali超杀击杀1/1目标；牌库只含一只1/3突袭鳞皮兽与一只非突袭Yeti，核对抽到前者并成为6/8。")])


akali_the_rhino.card_id = "TRL_329"


def masters_call():
    cid = "TRL_339"

    def all_beasts_draws_three_but_mixed_deck_discovers_one():
        def all_beasts(seed):
            g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=seed)
            p = g.player1
            ids = ("NEW1_032", "NEW1_033", "NEW1_034")
            for card_id in ids:
                put_deck(p, card_id)
            play(p, cid)
            observed = f"choice_open={bool(p.choice)};hand={[card_state(c) for c in p.hand]};deck={[c.id for c in p.deck]}"
            return checked(observed, not p.choice and len(p.hand) == 3 and {c.id for c in p.hand} == set(ids) and not p.deck)

        def mixed(seed):
            g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=seed)
            p = g.player1
            ids = (WISP, "NEW1_033", "NEW1_034")
            for card_id in ids:
                put_deck(p, card_id)
            play(p, cid)
            choice = p.choice
            options = [c.id for c in choice.cards]
            selected = choice.cards[0]
            choice.choose(selected)
            observed = f"options={options};selected={selected.id};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}"
            return checked(observed, choice and len(options) == 3 and len(p.hand) == 1 and p.hand[0].id == selected.id and p.hand[0].zone == Zone.HAND)

        return all_beasts(3391) + "; " + mixed(3392)

    return audit(cid, [("beast_all_draw_vs_mixed_discover", "Draw all three when the deck's three minions are Beasts; otherwise Discover one.", all_beasts_draws_three_but_mixed_deck_discovers_one, "第一局牌库恰好三种野兽，验证无选择且三张全抽；第二局混入Wisp触发三选一，选定一张后确认仅抽一张。")])


masters_call.card_id = "TRL_339"


def treespeaker():
    cid = "TRL_341"

    def transforms_treants_only_and_preserves_other_minions():
        def scenario(with_treants, seed):
            g = new_game(CardClass.DRUID, CardClass.MAGE, seed=seed)
            p = g.player1
            if with_treants:
                play(p, "EX1_571")  # Force of Nature summons three Treants
            other = summon(p, "CS2_182")
            speaker = play(p, cid)
            ancients = [c for c in p.field if c.id == "TRL_341t"]
            observed = f"with_treants={with_treants};ancients={[card_state(c) for c in ancients]};other={(other.id,other.atk,other.health,other.zone.name)};speaker={speaker.zone.name};field={[c.id for c in p.field]}"
            if with_treants:
                return checked(observed, len(ancients) == 3 and all((c.atk, c.health) == (5, 5) for c in ancients) and other.id == "CS2_182" and other.zone == Zone.PLAY)
            return checked(observed, not ancients and other.zone == Zone.PLAY and other.health == 5)

        return scenario(True, 3411) + "; " + scenario(False, 3412)

    return audit(cid, [("transform_treants_only", "Transforms all Treants into 5/5 Ancients while leaving other minions unchanged; no-Treant case is a no-op.", transforms_treants_only_and_preserves_other_minions, "分别用自然之力实际召唤三只树人和无树人局面，核对所有树人变成5/5古树且Yeti不变。")])


treespeaker.card_id = "TRL_341"


def wardruid_loti():
    cid = "TRL_343"

    def each_choose_branch_morphs_into_its_form():
        forms = ("TRL_343at2", "TRL_343bt2", "TRL_343ct2", "TRL_343dt2")
        observed_forms = []
        for index, option in enumerate(forms):
            g = new_game(CardClass.DRUID, CardClass.MAGE, seed=3430 + index)
            p = g.player1
            played = play(p, cid, choose=option)
            current = next((c for c in p.field if c.zone == Zone.PLAY), None)
            observed_forms.append((option, played.zone.name, current.id if current else None, (current.atk, current.health) if current else None, current.taunt if current else None, current.stealth if current and hasattr(current, "stealth") else None))
            assert current is not None and current.id == option.replace("t2", "t1") and current.zone == Zone.PLAY, observed_forms[-1]
        return checked(f"choices={observed_forms}", len(observed_forms) == 4 and len({row[2] for row in observed_forms}) == 4)

    return audit(cid, [("all_four_choose_one_forms", "Choose One transforms Loti into exactly the selected one of four forms.", each_choose_branch_morphs_into_its_form, "四个独立对局分别传入四个选项ID，检查每局场上本体变形成对应恐龙形态而非保留罗缇或始终变为同一形态。")])


wardruid_loti.card_id = "TRL_343"


def kragwa_the_frog():
    cid = "TRL_345"

    def returns_only_spells_from_immediately_previous_turn():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE, seed=3451)
        p, e = g.player1, g.player2
        old_spell = p.give(THE_COIN)
        old_spell.play()
        end_round(g)
        recent_spell = p.give(MOONFIRE)
        recent_spell.play(target=e.hero)
        end_round(g)
        frog = play(p, cid)
        hand_ids = [c.id for c in p.hand]
        observed = f"frog={frog.zone.name};hand={hand_ids};recent_spell_original={recent_spell.zone.name};older_coin_original={old_spell.zone.name}"
        return checked(observed, hand_ids.count(MOONFIRE) == 1 and THE_COIN not in hand_ids and frog.zone == Zone.PLAY)

    return audit(cid, [("return_last_turn_spells_only", "Krag'wa returns spells played last turn, not older spells.", returns_only_spells_from_immediately_previous_turn, "先一回合施放幸运币、下一回合施放月火术，再过到下一己方回合打出蛙神，核对仅月火术从紧邻的上回合返回。")])


kragwa_the_frog.card_id = "TRL_345"


def baited_arrow():
    cid = "TRL_347"

    def overkill_summons_devilsaur_but_exact_non_overkill_does_not():
        def scenario(overkill, seed):
            g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            target = summon(e, WISP if overkill else "CS2_182")
            play(p, cid, target=target)
            saurs = [c for c in p.field if c.id == "TRL_347t"]
            observed = f"overkill={overkill};target={(target.id,target.health,target.damage,target.zone.name)};devilsaurs={[card_state(c) for c in saurs]}"
            if overkill:
                return checked(observed, target.zone == Zone.GRAVEYARD and len(saurs) == 1 and (saurs[0].atk, saurs[0].health) == (5, 5))
            return checked(observed, target.zone == Zone.PLAY and target.health == 2 and target.damage == 3 and not saurs)

        return scenario(True, 3471) + "; " + scenario(False, 3472)

    return audit(cid, [("three_damage_and_overkill_devilsaurs", "Deals 3 damage; excess lethal damage summons a 5/5 Devilsaur only on Overkill.", overkill_summons_devilsaur_but_exact_non_overkill_does_not, "分别以1血Wisp超杀和5血Yeti剩2血的非超杀目标，核对3点伤害及5/5魔暴龙分支。")])


baited_arrow.card_id = "TRL_347"


def springpaw():
    cid = "TRL_348"

    def rush_attacks_now_and_battlecry_adds_rush_lynx():
        g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=3481)
        p, e = g.player1, g.player2
        springpaw = play(p, cid)
        token = find_hand(p, "TRL_348t")
        target = summon(e, "CS2_182")
        springpaw.attack(target)
        token_stats = (token.atk, token.health, token.rush, token.zone.name) if token else None
        observed = f"springpaw={(springpaw.atk,springpaw.health,springpaw.rush,springpaw.zone.name)};target={(target.health,target.damage,target.zone.name)};lynx={token_stats};hand={[c.id for c in p.hand]}"
        return checked(observed, springpaw.rush and target.damage == 1 and target.zone == Zone.PLAY and token is not None and token_stats == (1, 1, True, "HAND"))

    return audit(cid, [("rush_battlecry_linx", "Springpaw has Rush and can attack immediately; its Battlecry adds a 1/1 Rush Lynx to hand.", rush_attacks_now_and_battlecry_adds_rush_lynx, "打出春爪后立即攻击敌方Yeti并检查其受伤，另检查战吼手牌中的TRL_348t确为1/1突袭山猫。")])


springpaw.card_id = "TRL_348"


def bloodscalp_strategist():
    cid = "TRL_349"

    def weapon_enables_spell_discover():
        def scenario(with_weapon, seed):
            g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=seed)
            p = g.player1
            if with_weapon:
                play(p, "CS2_091")
            played = play(p, cid)
            if with_weapon:
                choice = p.choice
                options = [(c.id, int(c.type)) for c in choice.cards]
                selected = choice.cards[0]
                choice.choose(selected)
                observed = f"weapon=True;strategist={played.zone.name};options={options};selected={selected.id};hand={[c.id for c in p.hand]}"
                return checked(observed, bool(options) and all(kind == int(CardType.SPELL) for _, kind in options) and selected in p.hand and not p.choice)
            observed = f"weapon=False;strategist={played.zone.name};choice={bool(p.choice)};hand={[c.id for c in p.hand]}"
            return checked(observed, not p.choice and played.zone == Zone.PLAY)

        return scenario(True, 3491) + "; " + scenario(False, 3492)

    return audit(cid, [("weapon_conditional_discover_spell", "With a weapon equipped, Discover a spell; without one, no Discover occurs.", weapon_enables_spell_discover, "有武器局装备公正之剑并核对发现选项全是法术、选择后入手；无武器局打出随从并确认没有选择窗口。")])


bloodscalp_strategist.card_id = "TRL_349"


def rain_of_toads():
    cid = "TRL_351"

    def summons_three_taunt_toads_and_locks_three_mana():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE, seed=3511)
        p = g.player1
        play(p, cid)
        toads = [c for c in p.field if c.id == "TRL_351t"]
        end_round(g)
        observed = f"toads={[card_state(c) for c in toads]};taunts={[c.taunt for c in toads]};overload_locked_next_turn={p.overload_locked};next_turn_mana={p.mana};used_mana={p.used_mana}"
        return checked(observed, len(toads) == 3 and all((c.atk, c.health) == (2, 4) and c.taunt and c.zone == Zone.PLAY for c in toads) and p.overload_locked == 3 and p.mana == 7)

    return audit(cid, [("three_taunt_toads_overload_three", "Summons three 2/4 Taunt Toads and locks 3 mana crystals for next turn.", summons_three_taunt_toads_and_locks_three_mana, "施放暴雨蛙群后数场上令牌并检查每只2/4嘲讽、牌手过载锁定3点。")])


rain_of_toads.card_id = "TRL_351"


def likkim():
    cid = "TRL_352"

    def gains_attack_while_overloaded_then_loses_it():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE, seed=3521)
        p = g.player1
        play(p, "TRL_351")  # Overload (3)
        weapon = play(p, cid)
        same_turn = (weapon.atk, weapon.durability, p.overload_locked)
        end_round(g)
        overloaded_turn = (weapon.atk, weapon.durability, p.overload_locked)
        end_round(g)
        normal_turn = (weapon.atk, weapon.durability, p.overload_locked)
        observed = f"same_turn={same_turn};overloaded_turn={overloaded_turn};normal_turn={normal_turn}"
        return checked(observed, same_turn[0] == 1 and overloaded_turn[0] == 3 and normal_turn[0] == 1 and weapon.durability == 3)

    return audit(cid, [("attack_aura_tracks_overloaded_crystals", "Likkim gains +2 attack with overloaded crystals and returns to base attack when no longer overloaded.", gains_attack_while_overloaded_then_loses_it, "先施放过载3的暴雨蛙群后装备Likkim，按本回合/过载下回合/过载解除后攻击力检查基础1→3→1。")])


likkim.card_id = "TRL_352"


def overlords_whip():
    cid = "TRL_360"

    def damages_only_each_newly_played_minion():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3601)
        p = g.player1
        old = summon(p, "CS2_182")
        weapon = play(p, cid)
        new = play(p, "CS2_182")
        observed = f"weapon={weapon.id}:{weapon.atk}/{weapon.durability};old={(old.health,old.damage,old.zone.name)};new={(new.health,new.damage,new.zone.name)}"
        return checked(observed, old.damage == 0 and old.health == old.max_health == 5 and new.damage == 1 and new.health == 4 and new.zone == Zone.PLAY)

    return audit(cid, [("after_play_minion_deals_one_to_that_minion", "After a minion is played, Overlord's Whip deals exactly 1 damage to that minion and not older allies.", damages_only_each_newly_played_minion, "先控制一只健康Yeti再装备鞭子，随后打出第二只，核对只有新随从受1伤且未被触发误伤的旧随从仍满血。")])


overlords_whip.card_id = "TRL_360"


def dragon_roar():
    cid = "TRL_362"

    def adds_exactly_two_dragons():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3621)
        p = g.player1
        filler = p.give(WISP)
        play(p, cid)
        dragons = [c for c in p.hand if Race.DRAGON in c.races]
        observed = f"hand={[card_state(c) for c in p.hand]};dragons={[card_state(c) for c in dragons]};filler_zone={filler.zone.name};deck={len(p.deck)}"
        return checked(observed, len(dragons) == 2 and all(c.type == CardType.MINION and c.zone == Zone.HAND for c in dragons) and filler in p.hand and len(p.hand) == 3 and not p.deck)

    return audit(cid, [("add_two_random_dragons", "Adds exactly two random Dragon cards to hand while preserving existing hand cards.", adds_exactly_two_dragons, "已有Wisp留手时施放龙吼，核对新增两张均为龙牌随从且原卡仍在手中。")])


dragon_roar.card_id = "TRL_362"


def saronite_taskmaster():
    cid = "TRL_363"

    def deathrattle_summons_opponent_taunt_token():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=3631)
        p, e = g.player1, g.player2
        taskmaster = play(p, cid)
        taskmaster.destroy()
        tokens = [c for c in e.field if c.id == "TRL_363t"]
        observed = f"taskmaster={taskmaster.zone.name};friendly_tokens={[c.id for c in p.field if c.id == 'TRL_363t']};enemy_tokens={[card_state(c) for c in tokens]};enemy_taunt={[c.taunt for c in tokens]}"
        return checked(observed, taskmaster.zone == Zone.GRAVEYARD and len(tokens) == 1 and (tokens[0].atk, tokens[0].health) == (0, 3) and tokens[0].taunt and tokens[0].zone == Zone.PLAY)

    return audit(cid, [("deathrattle_gives_opponent_free_agent", "Death summons a 0/3 Taunt Free Agent on the opponent's board.", deathrattle_summons_opponent_taunt_token, "实际打出并摧毁萨隆铁矿监工，分开检查双方场地区域，确认0/3嘲讽自由矿工只给对手。")])


saronite_taskmaster.card_id = "TRL_363"


def daring_fire_eater():
    cid = "TRL_390"

    def buffs_one_hero_power_this_turn_only():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=3901)
        p, e = g.player1, g.player2
        first = summon(e, "CS2_182")
        second = summon(e, "CS2_182")
        eater = play(p, cid)
        p.hero.power.use(target=first)
        after_first = (first.health, first.damage, eater.zone.name)
        end_round(g)
        p.hero.power.use(target=second)
        observed = f"first_after_buffed_power={after_first};second_after_next_turn={(second.health,second.damage)};eater_after={eater.zone.name};hero_power_cost={p.hero.power.cost}"
        return checked(observed, after_first[0] == 2 and after_first[1] == 3 and eater.zone == Zone.PLAY and second.damage == 1 and second.health == 4)

    return audit(cid, [("next_hero_power_plus_two_once", "The next Hero Power this turn deals 2 extra damage, and the bonus is consumed.", buffs_one_hero_power_this_turn_only, "打出火食者后对5血目标施放法师技能检查3伤；跨回合再对第二个5血目标施放，确认只受普通1伤。")])


daring_fire_eater.card_id = "TRL_390"


def splitting_image():
    cid = "TRL_400"

    def copies_attacked_friendly_minion_but_not_when_hero_is_attacked():
        def scenario(attack_minion, seed):
            g = new_game(CardClass.MAGE, CardClass.MAGE, seed=seed)
            p, e = g.player1, g.player2
            secret = play(p, cid)
            defender = summon(p, "CS2_182")
            g.end_turn()
            play(e, "CS2_091")
            if attack_minion:
                e.hero.attack(defender)
            else:
                e.hero.attack(p.hero)
            copies = [c for c in p.field if c.id == "CS2_182"]
            observed = f"attack_minion={attack_minion};secret_zone={secret.zone.name};secret_live={secret in p.secrets};defender={(defender.health,defender.damage,defender.zone.name)};yeti_copies={[card_state(c) for c in copies]};hero_health={p.hero.health}"
            if attack_minion:
                return checked(observed, secret not in p.secrets and len(copies) == 2 and defender.damage == 1 and copies[1].health == copies[1].max_health == 5)
            return checked(observed, secret in p.secrets and len(copies) == 1 and p.hero.health == 29)

        return scenario(True, 4001) + "; " + scenario(False, 4002)

    return audit(cid, [("secret_triggers_only_when_friendly_minion_attacked", "When an enemy attacks a friendly minion, summon a copy; attacking the hero does not consume the Secret.", copies_attacked_friendly_minion_but_not_when_hero_is_attacked, "敌方英雄装备武器后分别攻击友方Yeti及英雄，前者应触发秘密并复制受伤随从，后者应保留秘密且不复制。")])


splitting_image.card_id = "TRL_400"


def untamed_beastmaster():
    cid = "TRL_405"

    def drawn_beast_gets_two_two_but_nonbeast_does_not():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=4051)
        p = g.player1
        beastmaster = play(p, cid)
        put_deck(p, "NEW1_032")
        put_deck(p, "CS2_182")
        play(p, "CS2_023")  # Arcane Intellect draws both cards
        beast = find_hand(p, "NEW1_032")
        nonbeast = find_hand(p, "CS2_182")
        observed = f"beastmaster={beastmaster.zone.name};beast={card_state(beast)};beast_races={beast.races if beast else None};nonbeast={card_state(nonbeast)};nonbeast_races={nonbeast.races if nonbeast else None};deck={[c.id for c in p.deck]}"
        return checked(observed, beast is not None and (beast.atk, beast.health) == (6, 6) and Race.BEAST in beast.races and beast.zone == Zone.HAND and nonbeast is not None and (nonbeast.atk, nonbeast.health) == (4, 5) and Race.BEAST not in nonbeast.races and nonbeast.zone == Zone.HAND and not p.deck)

    return audit(cid, [("draw_beast_enchants_only_beast", "Drawing a Beast gives it +2/+2; the simultaneously drawn non-Beast is unchanged.", drawn_beast_gets_two_two_but_nonbeast_does_not, "场上有驯兽大师、牌库仅有一张4/4野兽和一张4/5非野兽，用奥术智慧同时抽取并逐张核对身材。")])


untamed_beastmaster.card_id = "TRL_405"


def dozing_marksman():
    cid = "TRL_406"

    def attack_gains_four_while_damaged_and_reverts_after_heal():
        g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=4061)
        p = g.player1
        marksman = play(p, cid)
        base = (marksman.atk, marksman.max_health)
        p.give(MOONFIRE).play(target=marksman)
        damaged = (marksman.atk, marksman.health, marksman.damage)
        p.give("CS2_089").play(target=marksman)
        healed = (marksman.atk, marksman.health, marksman.damage)
        observed = f"base={base};damaged={damaged};healed={healed};zone={marksman.zone.name}"
        return checked(observed, damaged[0] == base[0] + 4 and damaged[2] == 1 and healed == (base[0], base[1], 0) and marksman.zone == Zone.PLAY)

    return audit(cid, [("attack_bonus_toggles_with_damage", "Dozing Marksman has +4 attack while damaged, then loses the bonus when healed.", attack_gains_four_while_damaged_and_reverts_after_heal, "对睡眠射手施放月火造成1伤后检查攻击力+4，再治疗至满血检查回到基础攻击。")])


dozing_marksman.card_id = "TRL_406"


def waterboy():
    cid = "TRL_407"

    def next_hero_power_is_free_then_cost_returns():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=4071)
        p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        baseline = p.hero.power.cost
        boy = play(p, cid)
        free_cost = p.hero.power.cost
        p.hero.power.use(target=target)
        after_use = p.hero.power.cost
        end_round(g)
        next_turn = p.hero.power.cost
        observed = f"baseline={baseline};after_waterboy={free_cost};target={(target.health,target.damage)};after_power={after_use};next_turn={next_turn};waterboy={boy.zone.name}"
        return checked(observed, baseline == 2 and free_cost == 0 and target.damage == 1 and after_use == 2 and next_turn == 2 and boy.zone == Zone.PLAY)

    return audit(cid, [("next_hero_power_cost_zero_once", "Waterboy makes the next Hero Power this turn cost 0, then the normal cost returns.", next_hero_power_is_free_then_cost_returns, "记录法师技能2费基准，打出水童后当回合0费使用并实际造成伤害，再检查本回合使用后及下一回合恢复2费。")])


waterboy.card_id = "TRL_407"


def grave_horror():
    cid = "TRL_408"

    def cost_reduces_for_each_spell_cast_this_game():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=4081)
        p, e = g.player1, g.player2
        horror = p.give(cid)
        base = horror.cost
        p.give(MOONFIRE).play(target=e.hero)
        after_one = horror.cost
        p.give(MOONFIRE).play(target=e.hero)
        after_two = horror.cost
        horror.play()
        observed = f"base={base};after_one_spell={after_one};after_two_spells={after_two};played={(horror.zone.name,horror.atk,horror.health,horror.taunt)};mana={p.mana}"
        return checked(observed, base == 12 and after_one == 11 and after_two == 10 and horror.zone == Zone.PLAY and horror.taunt)

    return audit(cid, [("one_cost_discount_per_spell_and_taunt", "Each spell cast this game reduces Grave Horror by 1; it retains Taunt when played.", cost_reduces_for_each_spell_cast_this_game, "先持有12费墓穴恐魔，分别施放两张0费月火检查12→11→10，再实际打出并确认嘲讽。")])


grave_horror.card_id = "TRL_408"


def gral_the_shark():
    cid = "TRL_409"

    def battlecry_eats_deck_minion_and_deathrattle_returns_copy():
        g = new_game(CardClass.ROGUE, CardClass.MAGE, seed=4091)
        p = g.player1
        put_deck(p, "CS2_182")
        gral = play(p, cid)
        eaten = [c for c in p.graveyard if c.id == "CS2_182"]
        after_battlecry = (gral.atk, gral.health, len(p.deck))
        gral.destroy()
        returned = [c for c in p.hand if c.id == "CS2_182"]
        observed = f"after_battlecry={after_battlecry};eaten={[card_state(c) for c in eaten]};gral_zone={gral.zone.name};returned={[card_state(c) for c in returned]};deck={[c.id for c in p.deck]}"
        return checked(observed, after_battlecry == (6, 7, 0) and len(eaten) == 1 and gral.zone == Zone.GRAVEYARD and len(returned) == 1 and (returned[0].atk, returned[0].health) == (4, 5) and returned[0].zone == Zone.HAND)

    return audit(cid, [("eat_deck_minion_gain_stats_and_return_it", "Gral eats a deck minion, gains its stats, then its Deathrattle returns that minion to hand.", battlecry_eats_deck_minion_and_deathrattle_returns_copy, "牌库仅放4/5 Yeti，打出5费鲨鱼后检查其变成6/7且牌库消耗；摧毁鲨鱼后检查Yeti副本回手。")])


gral_the_shark.card_id = "TRL_409"


AUDITS = [bwonsamdi_the_dead, shirvallah_the_tiger, time_out, farraki_battleaxe, a_new_challenger, immortal_prelate, flash_of_light, high_priest_thekal, spirit_of_the_tiger, elemental_evocation, arcanosaur, spellzerker, scorch, pyromaniac, janalai_the_dragonhawk, blast_wave, hex_lord_malacrass, spirit_of_the_dragonhawk, devastate, emberscale_drake, heavy_metal, sulthraze, smolderthorn_lancer, spirit_of_the_rhino, war_master_voone, akali_the_rhino, masters_call, treespeaker, wardruid_loti, kragwa_the_frog, baited_arrow, springpaw, bloodscalp_strategist, rain_of_toads, likkim, overlords_whip, dragon_roar, saronite_taskmaster, daring_fire_eater, splitting_image, untamed_beastmaster, dozing_marksman, waterboy, grave_horror, gral_the_shark]
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="zero-based frozen-roster index")
    parser.add_argument("--limit", type=int, default=45, help="number of cards to run")
    args = parser.parse_args()
    assert 0 <= args.start < 45 and 1 <= args.limit <= 45
    selected = AUDITS[args.start : args.start + args.limit]
    statuses = []
    for expected_id, fn in zip(OWN_IDS[args.start : args.start + args.limit], selected):
        assert expected_id == fn.card_id
        statuses.append(fn())
    from collections import Counter
    print(f"audited={len(statuses)} statuses={dict(Counter(statuses))}; roster={OWN_IDS[args.start:args.start + len(statuses)]}")


if __name__ == "__main__":
    main()
