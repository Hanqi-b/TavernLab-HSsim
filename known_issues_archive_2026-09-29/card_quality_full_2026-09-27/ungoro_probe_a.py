"""Card-specific live probes for the first 45 original Un'Goro YELLOW collectibles."""
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import FIREBALL, HOLY_LIGHT, MOONFIRE, WISP, prepare_empty_game, prepare_game  # noqa: E402

BASELINE = HERE / "three_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "ungoro_probe_a.csv"
VERDICT_OUT = HERE / "ungoro_verdict_a.csv"
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


BASE_ROWS = [r for r in read_csv(BASELINE) if r["set"] == "Journey to Un'Goro (UNGORO)"]
BASE_ROWS.sort(key=lambda r: r["card_id"])
OWN_ROWS = BASE_ROWS[:45]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY)}
PROBE_ROWS = [r for r in read_csv(PROBE_OUT) if r["card_id"] not in OWN_IDS]
VERDICT_ROWS = [r for r in read_csv(VERDICT_OUT) if r["card_id"] not in OWN_IDS]


def new_game(card_class=CardClass.MAGE, seed=913):
    random.seed(seed)
    game = prepare_empty_game(card_class, card_class)
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


def give(player, card_id):
    return player.give(card_id)


def summon(player, card_id):
    return player.summon(card_id)


def play(player, card_id, target=None):
    card = give(player, card_id)
    if target is None:
        card.play()
    else:
        card.play(target=target)
    return card


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    old = QUALITY_BY_ID.get(card_id, {})
    return (
        f"EN={master['card_text_en']}; ZH={master['card_text_zh']}; "
        f"source={master['python_source'] or master['xml_source']}; "
        f"existing_tests={master['test_refs_candidate'] or 'none'}; "
        f"prior={old.get('status', 'unknown')}:{old.get('reason', 'no prior reason')}"
    )


def record(card_id, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except AssertionError as exc:
        observed = str(exc) or "AssertionError"
        if not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    PROBE_ROWS.append({
        "card_id": card_id, "case_id": case_id, "expected": expected,
        "observed": observed, "outcome": outcome,
        "notes": f"{notes}; {metadata(card_id)}",
    })
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    return outcome, observed


def finish_card(card_id, blocker=None):
    rows = [r for r in PROBE_ROWS if r["card_id"] == card_id]
    errors = [r for r in rows if r["outcome"] == "confirmed_error"]
    inconclusive = [r for r in rows if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实战断言确认偏差：" + "；".join(
            f"{r['case_id']} expected={r['expected']} actual={r['observed']}" for r in errors
        )
    elif inconclusive:
        status = "YELLOW"
        reason = "关键行为运行未决：" + "；".join(
            f"{r['case_id']}={r['observed']}" for r in inconclusive
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "本轮逐卡行为用例全部通过：" + "; ".join(
            f"{r['case_id']}={r['observed']}" for r in rows
        )
    master = MASTER_BY_ID[card_id]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS.append({
        "card_id": card_id, "status": status,
        "mechanic_scope": master["mechanics"], "reason": reason,
        "probe_file": PROBE_OUT.name, "notes": metadata(card_id),
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def adapt_choice(player, minion, expect_next=False):
    assert player.choice is not None, "Adapt choice was not offered"
    choices = list(player.choice.cards)
    assert len(choices) == 3, [(c.id, c.name) for c in choices]
    selected = choices[0]
    player.choice.choose(selected)
    assert (player.choice is not None) if expect_next else (player.choice is None)
    assert any(buff.id == f"{selected.id}e" for buff in minion.buffs), (selected.id, [b.id for b in minion.buffs])
    return selected.id


def pterrordax_hatchling():
    cid = "UNG_001"
    def battlecry_adapts_once():
        g = new_game(CardClass.HUNTER); p = g.player1
        hatchling = play(p, cid)
        before = len(hatchling.buffs)
        choice_id = adapt_choice(p, hatchling)
        assert len(hatchling.buffs) == before + 1, [b.id for b in hatchling.buffs]
        assert hatchling.zone == Zone.PLAY
        return f"adapt_choice={choice_id};buffs={[b.id for b in hatchling.buffs]};zone={hatchling.zone.name}"
    record(cid, "battlecry_offers_and_applies_one_adapt", "Battlecry offers an Adapt choice; selecting one applies exactly one Adapt buff and closes the choice.", battlecry_adapts_once, "实际选择一个 Adapt 选项，断言选项关闭且随从仅获得一个对应增益。")
    return finish_card(cid)


def volcanosaur():
    cid = "UNG_002"
    def battlecry_adapts_twice():
        g = new_game(CardClass.HUNTER); p = g.player1
        saur = play(p, cid)
        selected_ids = []
        for index in range(2):
            selected_ids.append(adapt_choice(p, saur, expect_next=index == 0))
        assert len(saur.buffs) == 2, [b.id for b in saur.buffs]
        assert saur.zone == Zone.PLAY and p.choice is None
        return f"adapt_choices={selected_ids};buffs={[b.id for b in saur.buffs]};zone={saur.zone.name};choice={p.choice}"
    record(cid, "battlecry_runs_two_sequential_adapt_choices", "Battlecry presents two sequential Adapt choices, applies both selected buffs, and leaves no open choice.", battlecry_adapts_twice, "连续两次真实选择 Adapt，核对两项增益及 Choice 状态关闭。")
    return finish_card(cid)


def dinosize():
    cid = "UNG_004"
    def sets_friendly_target_to_ten_ten():
        g = new_game(CardClass.PALADIN); p = g.player1
        target = summon(p, "CS2_182")
        spell = play(p, cid, target)
        assert (target.atk, target.max_health, target.health) == (10, 10, 10), (target.atk, target.max_health, target.health)
        assert target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD
        return f"target={target.atk}/{target.health}/{target.max_health};target_zone={target.zone.name};spell={spell.zone.name}"
    def sets_enemy_target_to_ten_ten():
        g = new_game(CardClass.PALADIN); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        spell = play(p, cid, target)
        assert (target.atk, target.max_health, target.health) == (10, 10, 10), (target.atk, target.max_health, target.health)
        assert target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD
        return f"enemy_target={target.atk}/{target.health}/{target.max_health};target_zone={target.zone.name};spell={spell.zone.name}"
    record(cid, "spell_sets_friendly_minion_stats_exactly_ten_ten", "Targeted friendly minion's Attack and Health become exactly 10/10.", sets_friendly_target_to_ten_ten, "以己方4/5随从验证是设为10/10而非增加10点，并确认区域。")
    record(cid, "spell_can_target_enemy_minion_and_sets_ten_ten", "The spell may target an enemy minion and sets it to exactly 10/10.", sets_enemy_target_to_ten_ten, "以敌方4/5随从验证敌方目标合法以及精确设值。")
    return finish_card(cid)


def ravasaur_runt():
    cid = "UNG_009"
    def no_adapt_with_fewer_than_two_other_minions():
        g = new_game(CardClass.HUNTER); p = g.player1
        runt = play(p, cid)
        assert p.choice is None, f"unexpected Adapt choices={[c.id for c in p.choice.cards]}"
        assert runt.zone == Zone.PLAY and (runt.atk, runt.health) == (2, 2)
        return f"friendly_minions={len(p.field)};choice={p.choice};runt={runt.atk}/{runt.health}"
    def adapts_with_two_other_minions():
        g = new_game(CardClass.HUNTER); p = g.player1
        first = summon(p, WISP); second = summon(p, WISP)
        runt = play(p, cid)
        assert len(p.field) == 3 and first in p.field and second in p.field
        choice_id = adapt_choice(p, runt)
        assert runt.zone == Zone.PLAY and len(runt.buffs) == 1
        return f"other_minions=2;choice={choice_id};buffs={[b.id for b in runt.buffs]};field={len(p.field)}"
    record(cid, "battlecry_does_not_adapt_below_two_other_minions", "With fewer than two other friendly minions, Ravasaur Runt gets no Adapt choice.", no_adapt_with_fewer_than_two_other_minions, "零个其他己方随从时验证条件不触发。")
    record(cid, "battlecry_adapts_with_two_other_minions", "With exactly two other friendly minions, Ravasaur Runt offers and applies one Adapt.", adapts_with_two_other_minions, "恰有两个其他己方随从时实际选择 Adapt 并核对增益。")
    return finish_card(cid)


def sated_threshadon():
    cid = "UNG_010"
    def deathrattle_summons_three_murlocs():
        g = new_game(CardClass.SHAMAN); p = g.player1
        source = play(p, cid)
        source.destroy()
        tokens = [m for m in p.field if m.id == "UNG_201t"]
        assert source.zone == Zone.GRAVEYARD, source.zone
        assert len(tokens) == 3, [(m.id, m.zone.name) for m in p.field]
        assert all((m.atk, m.health, m.max_health) == (1, 1, 1) and Race.MURLOC in m.races for m in tokens), [(m.id, m.atk, m.health, m.max_health, m.races) for m in tokens]
        return f"source={source.zone.name};tokens={[(m.id,m.atk,m.health,sorted(int(r) for r in m.races)) for m in tokens]}"
    def deathrattle_respects_board_capacity():
        g = new_game(CardClass.SHAMAN); p = g.player1
        others = [summon(p, WISP) for _ in range(5)]
        source = play(p, cid)
        source.destroy()
        tokens = [m for m in p.field if m.id == "UNG_201t"]
        assert source.zone == Zone.GRAVEYARD and all(m in p.field for m in others)
        assert len(tokens) == 2 and len(p.field) == 7, [(m.id, m.zone.name) for m in p.field]
        assert all((m.atk, m.health) == (1, 1) for m in tokens)
        return f"source={source.zone.name};existing={len(others)};tokens={len(tokens)};field={len(p.field)}"
    record(cid, "deathrattle_summons_three_one_one_murlocs", "On death, Sated Threshadon leaves play and summons exactly three 1/1 Murlocs.", deathrattle_summons_three_murlocs, "实际消灭随从，断言亡语触发、令牌数量、身材及鱼人种族。")
    record(cid, "deathrattle_summons_only_available_board_slots", "On a board with five other minions, death opens a slot and the Deathrattle fills the two available slots.", deathrattle_respects_board_capacity, "设置五个其他随从加本体后触发亡语，检查死亡处理后的场位上限。")
    return finish_card(cid)


def hydrologist():
    cid = "UNG_011"
    def discovers_secret_for_non_secret_class_and_adds_selected_card():
        g = new_game(CardClass.WARRIOR); p = g.player1
        hydrologist_minion = play(p, cid)
        assert p.choice is not None
        options = list(p.choice.cards)
        assert len(options) == 3 and all(c.type == CardType.SPELL and c.card_class == CardClass.PALADIN for c in options), [(c.id, c.type, c.card_class) for c in options]
        selected = options[1]
        p.choice.choose(selected)
        assert p.choice is None and selected in p.hand and selected.zone == Zone.HAND
        assert hydrologist_minion in p.field
        return f"class=WARRIOR;options={[(c.id,int(c.card_class)) for c in options]};selected={selected.id};hand={[c.id for c in p.hand]};choice={p.choice}"
    def discovers_own_class_secret_for_mage():
        g = new_game(CardClass.MAGE); p = g.player1
        play(p, cid)
        assert p.choice is not None
        options = list(p.choice.cards)
        assert len(options) == 3 and all(c.type == CardType.SPELL and c.card_class == CardClass.MAGE for c in options), [(c.id, c.type, c.card_class) for c in options]
        selected = options[0]
        p.choice.choose(selected)
        assert p.choice is None and selected in p.hand and selected.zone == Zone.HAND
        return f"class=MAGE;options={[(c.id,int(c.card_class)) for c in options]};selected={selected.id};hand={[c.id for c in p.hand]}"
    record(cid, "battlecry_discovers_secret_and_selected_card_enters_hand", "Hydrologist offers three Secret spells from an eligible class pool; choosing one closes Discover and places the chosen card in hand.", discovers_secret_for_non_secret_class_and_adds_selected_card, "非奥秘职业下验证候选均为圣骑士奥秘，实际选择后进入手牌并关闭 Choice。")
    record(cid, "battlecry_uses_mage_secret_pool_for_mage", "When controlled by a Mage, the Discover options are Mage Secret spells.", discovers_own_class_secret_for_mage, "法师职业分支验证候选职业池并完成一次真实选择。")
    return finish_card(cid)


def sunkeeper_tarim():
    cid = "UNG_015"
    def battlecry_sets_all_other_minions_to_three_three():
        g = new_game(CardClass.PALADIN); p, e = g.player1, g.player2
        friendly = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        tarim = play(p, cid)
        assert (friendly.atk, friendly.max_health, friendly.health) == (3, 3, 3), (friendly.atk, friendly.max_health, friendly.health)
        assert (enemy.atk, enemy.max_health, enemy.health) == (3, 3, 3), (enemy.atk, enemy.max_health, enemy.health)
        assert (tarim.atk, tarim.max_health, tarim.health) == (3, 7, 7) and tarim.taunt
        assert tarim in p.field and friendly in p.field and enemy in e.field
        return f"friendly={friendly.atk}/{friendly.health}/{friendly.max_health};enemy={enemy.atk}/{enemy.health}/{enemy.max_health};tarim={tarim.atk}/{tarim.health}/{tarim.max_health};taunt={tarim.taunt}"
    record(cid, "battlecry_sets_friendly_and_enemy_minions_to_three_three", "Battlecry sets every other minion on both sides to 3/3; Tarim remains a 3/7 Taunt.", battlecry_sets_all_other_minions_to_three_three, "己方和敌方场上各有一个4/5随从，检查双方被设为3/3且塔林姆本身未变。")
    return finish_card(cid)


def flame_geyser():
    cid = "UNG_018"
    def damages_target_and_adds_elemental_to_hand():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        spell = play(p, cid, target)
        added = [c for c in p.hand if c.id == "UNG_809t1"]
        assert target.health == 3 and target.max_health == 5 and target.zone == Zone.PLAY, (target.health, target.max_health, target.zone)
        assert spell.zone == Zone.GRAVEYARD and len(added) == 1 and added[0].zone == Zone.HAND
        assert (added[0].atk, added[0].health, added[0].type, Race.ELEMENTAL in added[0].races) == (1, 2, CardType.MINION, True)
        return f"target_health=3/5;target_zone={target.zone.name};spell={spell.zone.name};added={[(c.id,c.atk,c.health,c.zone.name) for c in added]}"
    record(cid, "spell_deals_two_and_adds_one_elemental", "Flame Geyser deals 2 damage to its selected target and adds exactly one 1/2 Elemental to its controller's hand.", damages_target_and_adds_elemental_to_hand, "对敌方4/5随从实际施法，断言伤害、目标区域、法术去向和生成牌身材/种族/手牌区域。")
    return finish_card(cid)


def air_elemental():
    cid = "UNG_019"
    def rejects_spell_and_hero_power_targets_without_cost_or_damage():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        elemental = play(p, cid)
        g.end_turn()
        assert g.current_player is e
        spell = give(e, "CS2_008")
        mana_before = e.mana
        health_before = elemental.health
        try:
            spell.play(target=elemental)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "Moonfire accepted Air Elemental as target"
        assert spell.zone == Zone.HAND and e.mana == mana_before and elemental.health == health_before, (spell.zone, e.mana, mana_before, elemental.health, health_before)
        power_uses = e.times_hero_power_used_this_game
        try:
            e.hero.power.use(target=elemental)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "Fireblast accepted Air Elemental as target"
        assert e.times_hero_power_used_this_game == power_uses and e.mana == mana_before and elemental.health == health_before
        return f"spell_rejected={spell.zone.name};hero_power_rejected=True;mana={e.mana};health={elemental.health};power_uses={power_uses}"
    record(cid, "cannot_be_targeted_by_spell_or_hero_power", "Moonfire and Mage Hero Power cannot target Air Elemental; rejected actions preserve spell zone, mana, health, and Hero Power use.", rejects_spell_and_hero_power_targets_without_cost_or_damage, "由对手实际尝试法术和英雄技能指向空气元素，检查 InvalidAction 与状态不变。")
    return finish_card(cid)


def arcanologist():
    cid = "UNG_020"
    def draws_secret_not_nonsecret_from_mixed_deck():
        g = new_game(CardClass.MAGE); p = g.player1
        secret = give(p, "EX1_287"); secret.shuffle_into_deck()
        ordinary = give(p, WISP); ordinary.shuffle_into_deck()
        minion = play(p, cid)
        assert secret in p.hand and secret.zone == Zone.HAND
        assert ordinary in p.deck and ordinary.zone == Zone.DECK
        assert minion in p.field and len(p.hand) == 1
        return f"secret={secret.id}/{secret.zone.name};ordinary={ordinary.id}/{ordinary.zone.name};hand={[c.id for c in p.hand]};minion={minion.zone.name}"
    def does_not_draw_nonsecret_when_deck_has_no_secret():
        g = new_game(CardClass.MAGE); p = g.player1
        ordinary = give(p, WISP); ordinary.shuffle_into_deck()
        minion = play(p, cid)
        assert ordinary in p.deck and ordinary.zone == Zone.DECK and len(p.hand) == 0
        assert minion in p.field
        return f"ordinary={ordinary.id}/{ordinary.zone.name};hand={list(p.hand)};minion={minion.zone.name}"
    record(cid, "battlecry_draws_secret_from_mixed_deck", "With a Secret and a non-Secret in the deck, Arcanologist draws the Secret and leaves the non-Secret in the deck.", draws_secret_not_nonsecret_from_mixed_deck, "牌库放入一张法师奥秘和一张普通随从，检查抽牌来源与牌库剩余。")
    record(cid, "battlecry_does_not_draw_nonsecret_without_secret", "With only a non-Secret in the deck, Arcanologist does not draw that card.", does_not_draw_nonsecret_when_deck_has_no_secret, "无奥秘牌库分支验证不会误抽普通牌。")
    return finish_card(cid)


def steam_surger():
    cid = "UNG_021"
    def prior_turn_elemental_adds_flame_geyser():
        g = new_game(CardClass.MAGE); p = g.player1
        elemental = play(p, "UNG_809")
        g.end_turn(); g.end_turn()
        assert g.current_player is p
        surger = play(p, cid)
        added = [c for c in p.hand if c.id == "UNG_018"]
        assert elemental in p.field and len(added) == 1 and added[0].zone == Zone.HAND
        assert surger in p.field
        return f"last_turn_elemental={elemental.id}/{elemental.zone.name};surger={surger.zone.name};geyser={[c.id for c in added]}"
    def same_turn_elemental_does_not_count_as_last_turn():
        g = new_game(CardClass.MAGE); p = g.player1
        elemental = play(p, "UNG_809")
        surger = play(p, cid)
        assert elemental in p.field and surger in p.field
        assert not any(c.id == "UNG_018" for c in p.hand)
        return f"same_turn_elemental={elemental.id};surger={surger.zone.name};flame_geyser_in_hand=False"
    record(cid, "battlecry_rewards_if_elemental_played_last_turn", "An Elemental played on the previous turn causes exactly one Flame Geyser to enter hand.", prior_turn_elemental_adds_flame_geyser, "实际跨过对手回合后打出蒸汽涌动者，检查上回合状态和奖励牌。")
    record(cid, "battlecry_does_not_reward_elemental_played_this_turn", "Playing an Elemental earlier in the current turn alone does not satisfy 'last turn'.", same_turn_elemental_does_not_count_as_last_turn, "本回合刚打出元素后立即打出，验证不误用本回合事件。")
    return finish_card(cid)


def mirage_caller():
    cid = "UNG_022"
    def makes_one_one_copy_of_targeted_friendly_minion():
        g = new_game(CardClass.PRIEST); p = g.player1
        target = summon(p, WISP)
        shield = play(p, "CS2_004", target)
        assert (target.atk, target.health, target.max_health) == (1,3,3) and shield.zone == Zone.GRAVEYARD
        caller = play(p, cid, target)
        copies = [m for m in p.field if m.id == WISP]
        assert len(copies) == 2 and target in copies and target.zone == Zone.PLAY
        clone = next(m for m in copies if m is not target)
        assert (clone.atk, clone.health, clone.max_health) == (1, 1, 1), (clone.atk, clone.health, clone.max_health)
        assert (target.atk, target.health, target.max_health) == (1, 3, 3), (target.atk, target.health, target.max_health)
        assert caller in p.field and clone.zone == Zone.PLAY
        return f"buffed_original={target.id}/{target.atk}/{target.health}/{target.max_health};clone={clone.id}/{clone.atk}/{clone.health}/{clone.max_health};field={[m.id for m in p.field]}"
    def no_target_available_still_plays_without_clone():
        g = new_game(CardClass.PRIEST); p = g.player1
        caller = play(p, cid)
        assert caller in p.field and len(p.field) == 1 and p.choice is None
        return f"field={[m.id for m in p.field]};caller={caller.zone.name};choice={p.choice}"
    record(cid, "battlecry_summons_one_one_copy_of_friendly_target", "Choosing a friendly 1/3 buffed minion summons one 1/1 same-card copy and leaves the original buffed.", makes_one_one_copy_of_targeted_friendly_minion, "先用真言术：盾使目标1/3，再分别断言原随从与复制体身材、卡牌 ID、区域和数量。")
    record(cid, "battlecry_optional_target_no_friendly_minion", "With no other friendly minion available, Mirage Caller can be played without a target and summons no copy.", no_target_available_still_plays_without_clone, "无可选目标分支检查战吼交互跳过及不生成复制体。")
    return finish_card(cid)


def mana_bind():
    cid = "UNG_024"
    def opponent_spell_consumes_secret_and_creates_zero_cost_copy():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        secret = play(p, cid)
        assert secret in p.secrets and secret.zone == Zone.SECRET
        g.end_turn(); assert g.current_player is e
        spell = give(e, "CS2_008")
        spell.play(target=p.hero)
        copies = [c for c in p.hand if c.id == spell.id]
        assert len(copies) == 1 and copies[0].cost == 0 and copies[0].zone == Zone.HAND, [(c.id, c.cost, c.zone) for c in p.hand]
        assert spell.zone == Zone.GRAVEYARD and p.hero.health == 29
        assert secret.zone == Zone.GRAVEYARD and secret not in p.secrets
        return f"secret={secret.zone.name};opponent_spell={spell.id}/{spell.zone.name};copied={[(c.id,c.cost,c.zone.name) for c in copies]};hero_health={p.hero.health}"
    def opponent_minion_does_not_consume_secret():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        secret = play(p, cid)
        g.end_turn(); assert g.current_player is e
        minion = play(e, WISP)
        assert minion in e.field and secret in p.secrets and secret.zone == Zone.SECRET
        assert len(p.hand) == 0
        return f"minion={minion.id}/{minion.zone.name};secret={secret.zone.name};copied_hand={list(p.hand)}"
    record(cid, "secret_copies_opponent_spell_at_zero_cost", "When the opponent casts a spell, Mana Bind is consumed and a copy of that spell enters its owner's hand at 0 cost.", opponent_spell_consumes_secret_and_creates_zero_cost_copy, "对手实际施放月火术并指定英雄，核对原法术结算、奥秘离场及零费复制。")
    record(cid, "secret_does_not_trigger_on_opponent_minion", "An opponent minion play does not trigger or consume Mana Bind.", opponent_minion_does_not_consume_secret, "对手打出随从，检查法术限定触发器保持奥秘。")
    return finish_card(cid)


def volcano():
    cid = "UNG_025"
    def splits_fifteen_damage_across_minions_and_overloads_two():
        seen_controllers = set()
        traces = []
        for seed in range(3025, 3041):
            g = new_game(CardClass.SHAMAN, seed); p, e = g.player1, g.player2
            minions = [summon(p, "CS2_182"), summon(p, WISP), summon(e, "CS2_182"), summon(e, WISP)]
            for minion in minions:
                minion.max_health = 30
                minion.set_current_health(30)
            owner_hero_before, enemy_hero_before = p.hero.health, e.hero.health
            spell = play(p, cid)
            damage = sum(m.damage for m in minions)
            assert damage == 15, (seed, damage, [(m.id, m.damage, m.zone.name) for m in minions])
            assert all(m.zone == Zone.PLAY and m.health == 30 - m.damage for m in minions), (seed, [(m.id, m.damage, m.health, m.zone.name) for m in minions])
            assert p.hero.health == owner_hero_before and e.hero.health == enemy_hero_before
            assert p.overloaded == 2 and spell.zone == Zone.GRAVEYARD, (seed, p.overloaded, spell.zone)
            for minion in minions:
                if minion.damage:
                    seen_controllers.add(minion.controller.name)
            traces.append(f"{seed}:{[(m.damage,m.controller.name) for m in minions]}")
        assert seen_controllers == {"Player1", "Player2"}, traces
        return f"seeds={';'.join(traces)};eligible_controllers_hit={len(seen_controllers)};damage_each_run=15;overload=2"
    record(cid, "spell_splits_exactly_fifteen_damage_among_all_minions", "Across fixed seeds, Volcano deals exactly 15 total one-point hits among minions on both sides, does not hit heroes, and applies Overload (2).", splits_fifteen_damage_across_minions_and_overloads_two, "四个高生命随从分布于双方场上，跨固定种子断言15点总伤害、目标范围和过载。")
    return finish_card(cid)


def pyros():
    cid = "UNG_027"
    def deathrattle_returns_successive_larger_forms():
        g = new_game(CardClass.MAGE); p = g.player1
        first = play(p, cid)
        assert (first.atk, first.max_health, first.cost) == (2, 2, 2), (first.atk, first.max_health, first.cost)
        first.destroy()
        six_form = next((c for c in p.hand if c.id == "UNG_027t2"), None)
        assert first.zone == Zone.SETASIDE and six_form is not None and (six_form.atk, six_form.max_health, six_form.cost) == (6, 6, 6), (first.zone, [(c.id,c.atk,c.max_health,c.cost) for c in p.hand])
        p.used_mana = 0
        six_form.play()
        assert six_form in p.field
        six_form.destroy()
        ten_form = next((c for c in p.hand if c.id == "UNG_027t4"), None)
        assert six_form.zone == Zone.SETASIDE and ten_form is not None and (ten_form.atk, ten_form.max_health, ten_form.cost, ten_form.zone) == (10, 10, 10, Zone.HAND), (six_form.zone, [(c.id,c.atk,c.max_health,c.cost,c.zone) for c in p.hand])
        return f"first_form=UNG_027t2/6/6/cost6;second_form={ten_form.id}/{ten_form.atk}/{ten_form.max_health}/cost{ten_form.cost}/{ten_form.zone.name};old_instances=SETASIDE"
    record(cid, "deathrattle_returns_six_six_then_ten_ten", "The original 2/2 Pyros returns to hand as a 6/6 costing 6; when that form dies, it returns as a 10/10 costing 10.", deathrattle_returns_successive_larger_forms, "连续两次实际死亡并重打，核对手牌区域、身材及费用递进。")
    return finish_card(cid)


def open_the_waygate():
    cid = "UNG_028"
    def counts_only_nonstarting_spells_then_gives_extra_turn_spell():
        random.seed(2828)
        g = prepare_game(include=tuple([cid] + [MOONFIRE] * 29))
        g.random.seed(2828)
        p, e = g.player2, g.player1
        assert any(c.id == cid for c in p.hand)
        quest = next(c for c in p.hand if c.id == cid)
        if g.current_player is not p:
            g.end_turn()
        assert g.current_player is p
        quest.play()
        assert quest.progress == 0 and quest.zone == Zone.SECRET
        coin = next(c for c in p.hand if c.id == "GAME_005")
        coin.play()
        assert quest.progress == 1, ("Coin should count as a non-starting spell", quest.progress)
        starting_spell = next(c for c in p.hand if c.id == MOONFIRE)
        starting_spell.play(target=e.hero)
        assert quest.progress == 1, ("starting-deck spell should not count", quest.progress)
        for expected_progress in range(2, 9):
            generated_spell = give(p, MOONFIRE)
            generated_spell.play(target=e.hero)
            assert quest.progress == expected_progress, (expected_progress, quest.progress)
        rewards = [c for c in p.hand if c.id == "UNG_028t"]
        assert quest.zone == Zone.GRAVEYARD and len(rewards) == 1 and rewards[0].zone == Zone.HAND
        return f"quest_progress={quest.progress};quest={quest.zone.name};reward={[c.id for c in rewards]};starting_spell_excluded=True;coin_counted=True"
    record(cid, "quest_requires_eight_nonstarting_spells_and_rewards_time_warp", "A starting-deck spell does not advance the quest; The Coin and seven generated spells reach eight, complete the quest, and add Time Warp to hand.", counts_only_nonstarting_spells_then_gives_extra_turn_spell, "在带已知起始套牌法术的真实对局中逐步检查进度、起始牌排除、硬币计数与奖励进入手牌。")
    return finish_card(cid)


def shadow_visions():
    cid = "UNG_029"
    def discovers_copy_from_deck_without_removing_original():
        g = new_game(CardClass.PRIEST, 2929); p = g.player1
        known_ids = {MOONFIRE, FIREBALL, HOLY_LIGHT}
        originals = {card_id: give(p, card_id) for card_id in known_ids}
        for card in originals.values(): card.shuffle_into_deck()
        before_deck = len(p.deck)
        spell = play(p, cid)
        assert p.choice is not None
        options = list(p.choice.cards)
        option_ids = [c.id for c in options]
        assert len(options) == 3 and len(set(option_ids)) == 3 and set(option_ids) == known_ids, option_ids
        selected = options[1]
        p.choice.choose(selected)
        copies = [c for c in p.hand if c.id == selected.id]
        assert p.choice is None and len(copies) == 1 and copies[0] is selected and selected.zone == Zone.HAND
        assert len(p.deck) == before_deck and all(original in p.deck for original in originals.values())
        assert spell.zone == Zone.GRAVEYARD
        return f"options={option_ids};chosen={selected.id};copy_zone={selected.zone.name};deck={[c.id for c in p.deck]};deck_size={len(p.deck)}"
    record(cid, "discover_offers_distinct_spells_and_adds_copy", "Discover offers the three distinct spells in the deck; the chosen copy enters hand while all deck originals remain.", discovers_copy_from_deck_without_removing_original, "放入三张已知不同法术，断言候选集合、实际选择、手牌复制和牌库原牌保留。")
    return finish_card(cid)


def binding_heal():
    cid = "UNG_030"
    def heals_friendly_minion_and_own_hero():
        g = new_game(CardClass.PRIEST); p = g.player1
        target = summon(p, "CS2_182"); target.set_current_health(2)
        p.hero.set_current_health(20)
        spell = play(p, cid, target)
        assert target.health == 5 and target.max_health == 5 and p.hero.health == 25, (target.health, target.max_health, p.hero.health)
        assert spell.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY
        return f"friendly_minion={target.health}/{target.max_health};own_hero={p.hero.health};spell={spell.zone.name}"
    def heals_enemy_minion_and_own_hero_only():
        g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
        target = summon(e, "CS2_182"); target.set_current_health(2)
        p.hero.set_current_health(20); e.hero.set_current_health(20)
        spell = play(p, cid, target)
        assert target.health == 5 and target.max_health == 5 and p.hero.health == 25 and e.hero.health == 20, (target.health, target.max_health, p.hero.health, e.hero.health)
        assert spell.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY
        return f"enemy_minion={target.health}/{target.max_health};own_hero={p.hero.health};enemy_hero={e.hero.health};spell={spell.zone.name}"
    record(cid, "spell_restores_five_to_friendly_minion_and_hero", "Binding Heal restores 5 Health to the selected friendly minion and its caster's hero.", heals_friendly_minion_and_own_hero, "己方受伤随从及英雄均缺5点以上生命，逐项断言治疗上限和区域。")
    record(cid, "spell_can_heal_enemy_minion_and_own_hero", "Binding Heal may target an enemy minion; it heals that minion and the caster's hero, not the enemy hero.", heals_enemy_minion_and_own_hero_only, "敌方随从作为目标，分别断言目标、施法者英雄和对手英雄生命变化。")
    return finish_card(cid)


def crystalline_oracle():
    cid = "UNG_032"
    def deathrattle_copies_random_card_from_enemy_deck():
        seen = set(); traces = []
        for seed in range(3232, 3248):
            g = new_game(CardClass.PRIEST, seed); p, e = g.player1, g.player2
            assert not p.deck and not e.deck
            first = give(e, WISP); first.shuffle_into_deck()
            second = give(e, FIREBALL); second.shuffle_into_deck()
            oracle = summon(p, cid)
            g.random.seed(seed + 1)
            oracle.destroy()
            copied = list(p.hand)
            assert oracle.zone == Zone.GRAVEYARD and len(copied) == 1, (seed, oracle.zone, [c.id for c in copied])
            copy = copied[0]
            assert copy.id in {WISP, FIREBALL} and copy.zone == Zone.HAND, (seed, copy.id, copy.zone)
            assert first in e.deck and second in e.deck and len(e.deck) == 2, (seed, [c.id for c in e.deck])
            assert copy is not first and copy is not second
            seen.add(copy.id); traces.append(f"{seed}:{copy.id}")
        assert seen == {WISP, FIREBALL}, traces
        return f"copies={';'.join(traces)};distinct={sorted(seen)};enemy_originals_preserved=True"
    record(cid, "deathrattle_copies_one_enemy_deck_card_to_hand", "Across fixed seeds, death copies one card from the opponent's known two-card deck into hand without removing either original.", deathrattle_copies_random_card_from_enemy_deck, "清空默认牌库，仅放两张已知敌方卡并跨种子触发亡语；检查来源、复制区域、原牌保留和随机多样性。")
    return finish_card(cid)


def radiant_elemental():
    cid = "UNG_034"
    def aura_reduces_owner_spells_stacks_and_expires():
        g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
        fireball = give(p, FIREBALL)
        moonfire = give(p, MOONFIRE)
        enemy_fireball = give(e, FIREBALL)
        assert fireball.cost == 4 and moonfire.cost == 0 and enemy_fireball.cost == 4
        first = play(p, cid)
        assert fireball.cost == 3 and moonfire.cost == 0 and enemy_fireball.cost == 4, (fireball.cost, moonfire.cost, enemy_fireball.cost)
        second = play(p, cid)
        assert fireball.cost == 2 and moonfire.cost == 0 and enemy_fireball.cost == 4, (fireball.cost, moonfire.cost, enemy_fireball.cost)
        first.destroy()
        assert first.zone == Zone.GRAVEYARD and fireball.cost == 3 and enemy_fireball.cost == 4, (fireball.cost, enemy_fireball.cost)
        second.destroy()
        assert second.zone == Zone.GRAVEYARD and fireball.cost == 4 and moonfire.cost == 0 and enemy_fireball.cost == 4
        return f"fireball_cost=4->3->2->3->4;moonfire=0;opponent_fireball=4;auras_removed=True"
    record(cid, "aura_reduces_only_owner_spell_costs_and_stacks", "Each Radiant Elemental reduces its controller's hand spell costs by 1, never below 0; reductions stack and disappear when the source leaves play.", aura_reduces_owner_spells_stacks_and_expires, "同时检查高费、零费法术、对手手牌、双光照叠加及两个来源离场后的费用恢复。")
    return finish_card(cid)


def curious_glimmerroot():
    cid = "UNG_035"
    def correct_guess_adds_copy_of_starting_deck_card():
        random.seed(3535)
        g = prepare_game(CardClass.PRIEST, CardClass.MAGE)
        g.random.seed(3535)
        p = g.player1
        if g.current_player is not p: g.end_turn()
        initial_hand = len(p.hand)
        minion = play(p, cid)
        choice = p.choice
        assert choice is not None and len(choice.cards) == 3
        starting_ids = {c.id for c in g.player2.starting_deck}
        assert choice.starting_card.id in starting_ids
        assert all(c.id not in starting_ids for c in (choice.other_card_1, choice.other_card_2)), (choice.starting_card.id, choice.other_card_1.id, choice.other_card_2.id)
        selected = choice.starting_card
        choice.choose(selected)
        assert p.choice is None and selected in p.hand and selected.zone == Zone.HAND
        assert len(p.hand) == initial_hand + 1, (initial_hand + 1, len(p.hand))
        assert minion in p.field
        return f"options={[c.id for c in choice.cards]};correct={selected.id};hand_delta={len(p.hand)-initial_hand};choice={p.choice}"
    def wrong_guess_does_not_add_card_to_hand():
        random.seed(3536)
        g = prepare_game(CardClass.PRIEST, CardClass.MAGE)
        g.random.seed(3536)
        p = g.player1
        if g.current_player is not p: g.end_turn()
        initial_hand = len(p.hand)
        minion = play(p, cid)
        choice = p.choice
        assert choice is not None and choice.starting_card.id in {c.id for c in g.player2.starting_deck}
        wrong = choice.other_card_1
        choice.choose(wrong)
        assert p.choice is None and len(p.hand) == initial_hand, (initial_hand, len(p.hand), wrong.id)
        assert minion in p.field
        return f"wrong={wrong.id};actual_starting={choice.starting_card.id};hand_delta={len(p.hand)-initial_hand};choice={p.choice}"
    record(cid, "battlecry_correct_guess_copies_opponent_starting_deck_card", "One of three cards is from the opponent's starting deck; choosing it adds that card to hand and closes the choice.", correct_guess_adds_copy_of_starting_deck_card, "使用真实起始套牌检验候选来源并选择正确答案，确认复制进入手牌。")
    record(cid, "battlecry_wrong_guess_gives_no_copy", "Choosing either non-starting-deck option does not add a card to hand.", wrong_guess_does_not_add_card_to_hand, "新对局选择错误选项，断言没有卡牌加入手牌且 Choice 关闭。")
    return finish_card(cid)


def ravenous_pterrordax():
    cid = "UNG_047"
    def destroys_friendly_minion_then_adapts_twice():
        g = new_game(CardClass.WARLOCK); p = g.player1
        victim = summon(p, WISP)
        beast = play(p, cid, victim)
        assert victim.zone == Zone.GRAVEYARD and victim not in p.field
        chosen = [adapt_choice(p, beast, expect_next=True), adapt_choice(p, beast)]
        assert len(beast.buffs) == 2 and beast in p.field and p.choice is None, [b.id for b in beast.buffs]
        return f"victim={victim.zone.name};adapt_choices={chosen};buffs={[b.id for b in beast.buffs]};field={[m.id for m in p.field]}"
    def no_friendly_minion_skips_optional_target_and_adapt():
        g = new_game(CardClass.WARLOCK); p = g.player1
        beast = play(p, cid)
        assert beast in p.field and p.choice is None and len(p.field) == 1
        return f"beast={beast.zone.name};field={[m.id for m in p.field]};choice={p.choice}"
    record(cid, "battlecry_destroys_selected_friendly_minion_and_adapts_twice", "Selecting a friendly minion destroys it and produces two sequential Adapt choices for Ravenous Pterrordax.", destroys_friendly_minion_then_adapts_twice, "实际牺牲一个己方随从，断言其进墓地、本体保留并完成两次进化。")
    record(cid, "battlecry_without_friendly_target_does_not_adapt", "Without another friendly minion, the optional target may be skipped and no Adapt is granted.", no_friendly_minion_skips_optional_target_and_adapt, "无可牺牲随从分支检查可跳过目标以及不触发进化。")
    return finish_card(cid)


def tar_lurker():
    cid = "UNG_049"
    def attack_bonus_follows_opponent_turn_and_taunt_persists():
        g = new_game(CardClass.WARLOCK); p = g.player1
        lurker = play(p, cid)
        own_turn_attack = lurker.atk
        assert own_turn_attack == 1 and lurker.taunt
        g.end_turn()
        opponent_turn_attack = lurker.atk
        assert g.current_player is p.opponent and opponent_turn_attack == 4 and lurker.taunt
        g.end_turn()
        assert g.current_player is p and lurker.atk == 1 and lurker.taunt
        return f"own_turn_attack={own_turn_attack};opponent_turn_attack={opponent_turn_attack};returned_attack={lurker.atk};taunt={lurker.taunt}"
    record(cid, "continuous_effect_adds_three_attack_only_during_opponent_turn", "Tar Lurker is a Taunt; its Attack is 1 on its controller's turn, 4 on the opponent's turn, then returns to 1.", attack_bonus_follows_opponent_turn_and_taunt_persists, "逐次切换回合核对攻击光环开启/关闭及嘲讽持续状态。")
    return finish_card(cid)


def razorpetal_volley():
    cid = "UNG_057"
    def adds_two_one_damage_spells_and_casting_one_deals_damage():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        volley = play(p, cid)
        petals = [c for c in p.hand if c.id == "UNG_057t1"]
        assert volley.zone == Zone.GRAVEYARD and len(petals) == 2, [(c.id, c.zone.name) for c in p.hand]
        assert all(c.type == CardType.SPELL and c.cost == 1 and c.zone == Zone.HAND for c in petals)
        target = summon(e, "CS2_182")
        petal = petals[0]
        petal.play(target=target)
        assert target.health == 4 and target.max_health == 5 and petal.zone == Zone.GRAVEYARD
        assert len([c for c in p.hand if c.id == "UNG_057t1"]) == 1
        return f"volley={volley.zone.name};petals_before=2;cast_target=4/5;cast={petal.zone.name};remaining_petals=1"
    record(cid, "spell_adds_two_razorpetals_and_one_deals_one_damage", "Volley adds exactly two 1-cost Razorpetals; casting one deals 1 damage to the chosen target and leaves the other in hand.", adds_two_one_damage_spells_and_casting_one_deals_damage, "核对生成数量及费用，再实际施放一张刀瓣验证伤害、区域和剩余手牌。")
    return finish_card(cid)


def razorpetal_lasher():
    cid = "UNG_058"
    def battlecry_adds_one_functional_razorpetal():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        lasher = play(p, cid)
        petals = [c for c in p.hand if c.id == "UNG_057t1"]
        assert lasher in p.field and len(petals) == 1 and petals[0].cost == 1 and petals[0].zone == Zone.HAND
        target = summon(e, "CS2_182")
        petal = petals[0]; petal.play(target=target)
        assert target.health == 4 and target.max_health == 5 and petal.zone == Zone.GRAVEYARD
        return f"lasher={lasher.zone.name};petal={petal.id}/{petal.zone.name};target={target.health}/{target.max_health}"
    record(cid, "battlecry_adds_one_razorpetal_that_deals_one_damage", "Battlecry adds one Razorpetal to hand, and that generated spell deals exactly 1 damage to its target.", battlecry_adds_one_functional_razorpetal, "实战执行战吼与生成法术，逐项检查手牌、费用、目标生命和区域。")
    return finish_card(cid)


def mimic_pod():
    cid = "UNG_060"
    def draws_card_then_adds_a_copy_without_second_deck_draw():
        g = new_game(CardClass.ROGUE); p = g.player1
        original = give(p, WISP); original.shuffle_into_deck()
        spell = play(p, cid)
        copies = [c for c in p.hand if c.id == WISP]
        assert len(copies) == 2 and original in copies and all(c.zone == Zone.HAND for c in copies), [(c.id, c.zone.name) for c in p.hand]
        assert copies[0] is not copies[1] and len(p.deck) == 0 and spell.zone == Zone.GRAVEYARD
        return f"original_and_copy={[(c.id,c.zone.name,c is original) for c in copies]};deck_size={len(p.deck)};spell={spell.zone.name}"
    def empty_deck_does_not_copy_nonexistent_draw():
        g = new_game(CardClass.ROGUE); p = g.player1
        p.cant_fatigue = False
        before = (p.hero.health, p.fatigue_counter)
        spell = play(p, cid)
        after = (p.hero.health, p.fatigue_counter)
        assert spell.zone == Zone.GRAVEYARD and not p.hand and not p.deck
        assert before == (30,0) and after == (29,1), (before,after)
        return f"spell={spell.zone.name};hand={list(p.hand)};deck={list(p.deck)};fatigue_disabled={p.cant_fatigue};hero_and_fatigue={before}->{after}"
    record(cid, "spell_draws_card_and_adds_distinct_copy", "With one known card in deck, Mimic Pod draws it and adds a distinct second copy to hand without drawing a second deck card.", draws_card_then_adds_a_copy_without_second_deck_draw, "单牌库中放入已知随从，断言抽到原牌及另一张独立复制、牌库耗尽。")
    record(cid, "spell_empty_deck_has_no_card_to_copy", "With an empty deck and fatigue enabled, the attempted draw causes one fatigue damage, and no copy enters hand.", empty_deck_does_not_copy_nonexistent_draw, "开启真实疲劳，检查空牌库边界仅疲劳一次、英雄掉1血、没有错误复制或额外牌张。")
    return finish_card(cid)


def obsidian_shard():
    cid = "UNG_061"
    def cost_reduction_counts_other_class_plays_and_equips_weapon():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        weapon_card = give(p, cid)
        assert weapon_card.cost == 4, weapon_card.cost
        other_one = give(p, MOONFIRE)
        other_two = give(p, FIREBALL)
        own_class_spell = give(p, "EX1_124")
        assert own_class_spell.card_class == CardClass.ROGUE
        other_one.play(target=e.hero)
        assert weapon_card.cost == 3, (weapon_card.cost, other_one.zone)
        other_two.play(target=e.hero)
        assert weapon_card.cost == 2, (weapon_card.cost, other_two.zone)
        own_class_spell.play(target=e.hero)
        assert weapon_card.cost == 2, (weapon_card.cost, own_class_spell.zone)
        mana_before_equip = p.used_mana
        weapon_card.play()
        assert weapon_card.zone == Zone.PLAY and p.weapon is weapon_card and p.used_mana == mana_before_equip + 2, (weapon_card.zone, p.weapon is weapon_card, p.used_mana, mana_before_equip)
        assert (p.weapon.atk, p.weapon.durability) == (3, 3)
        return f"base=4;after_other_class_1=3;after_other_class_2=2;after_own_class=2;equip_mana_delta={p.used_mana-mana_before_equip};weapon={p.weapon.id}/{p.weapon.atk}/{p.weapon.durability};runtime_cost_after_equip={weapon_card.cost}"
    record(cid, "weapon_cost_reduced_per_other_class_card_played", "Obsidian Shard costs 1 less for each other-class card played, does not reduce for Rogue cards, and equips with the reduced cost.", cost_reduction_counts_other_class_plays_and_equips_weapon, "以两张不同职业法术和一张本职业法术逐步检查费用，再实际装备武器。")
    return finish_card(cid)


def biteweed():
    cid = "UNG_063"
    def combo_buffs_per_other_card_played_this_turn():
        traces = []
        for count in range(3):
            g = new_game(CardClass.ROGUE, 6363 + count); p = g.player1
            if count >= 1:
                give(p, "GAME_005").play()
            if count >= 2:
                give(p, MOONFIRE).play(target=p.opponent.hero)
            biteweed_minion = play(p, cid)
            expected = (biteweed_minion.data.atk + count, biteweed_minion.data.health + count)
            assert (biteweed_minion.atk, biteweed_minion.health) == expected, (count, biteweed_minion.atk, biteweed_minion.health, expected)
            assert biteweed_minion.zone == Zone.PLAY
            traces.append(f"prior_cards={count}:{biteweed_minion.atk}/{biteweed_minion.health}")
        return ";".join(traces)
    record(cid, "combo_attack_health_scale_with_prior_cards", "Biteweed stays 3/2 with no earlier cards, becomes 4/3 after one, and 5/4 after two cards played earlier that turn.", combo_buffs_per_other_card_played_this_turn, "分别以零、一、两张先行卡验证连击计数不包含自身并逐张+1/+1。")
    return finish_card(cid)


def vilespine_slayer():
    cid = "UNG_064"
    def combo_destroys_target_and_no_combo_skips_effect():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        slayer = play(p, cid)
        assert slayer in p.field and target in e.field and target.zone == Zone.PLAY
        second_target = summon(e, "CS2_182")
        give(p, "GAME_005").play()
        combo_slayer = play(p, cid, second_target)
        assert combo_slayer in p.field and second_target.zone == Zone.GRAVEYARD and second_target not in e.field
        assert target in e.field and target.zone == Zone.PLAY
        return f"no_combo_target_survives={target.zone.name};combo_target={second_target.zone.name};slayers={[m.id for m in p.field]}"
    record(cid, "combo_only_destroys_target_after_prior_card", "Without Combo the Slayer can be played without removing a minion; after a prior card, its chosen minion is destroyed.", combo_destroys_target_and_no_combo_skips_effect, "同一局面先检查无连击无目标效果，再打出硬币激活连击并指定另一敌方随从。")
    return finish_card(cid)


def sherazin_corpse_flower():
    cid = "UNG_065"
    def death_goes_dormant_turn_counter_resets_and_four_same_turn_plays_revive():
        g = new_game(CardClass.ROGUE); p = g.player1
        flower = play(p, cid)
        flower.destroy()
        dormant = next((m for m in p.field if m.id == "UNG_065t"), None)
        assert flower.zone == Zone.GRAVEYARD and dormant is not None and dormant.zone == Zone.PLAY, (flower.zone, [(m.id,m.zone.name) for m in p.field])
        for _ in range(3): give(p, MOONFIRE).play(target=p.opponent.hero)
        assert dormant in p.field and dormant.id == "UNG_065t" and dormant.progress == 3, (dormant.id, dormant.progress)
        g.end_turn(); g.end_turn()
        assert g.current_player is p and dormant in p.field and dormant.progress == 0, (g.current_player.name, dormant.progress)
        for _ in range(3): give(p, MOONFIRE).play(target=p.opponent.hero)
        assert dormant in p.field and dormant.progress == 3, (dormant.id, dormant.progress)
        give(p, MOONFIRE).play(target=p.opponent.hero)
        revived = next((m for m in p.field if m.id == "UNG_065"), None)
        assert revived is not None and revived.zone == Zone.PLAY and (revived.atk, revived.max_health) == (5, 3), [(m.id,m.atk,m.max_health,m.zone.name) for m in p.field]
        assert dormant not in p.field
        return f"dead_instance={flower.zone.name};dormant_progress_after3={3};after_turn_reset=0;dormant_progress_before4=3;revived={revived.id}/{revived.atk}/{revived.max_health}/{revived.zone.name};dormant_final={dormant.zone.name}"
    record(cid, "deathrattle_dormant_resets_each_turn_and_revives_after_four_plays", "On death Sherazin becomes Dormant; three plays do not revive it, progress clears across turns, and four plays in one turn revive a 5/3 Sherazin.", death_goes_dormant_turn_counter_resets_and_four_same_turn_plays_revive, "实际触发亡语，分别检查休眠区域、三牌阈值、跨回合计数清零及同回合四牌复苏。")
    return finish_card(cid)


def caverns_below():
    cid = "UNG_067"
    def quest_counts_five_same_named_minions_and_crystal_core_buffs_all_zones():
        g = new_game(CardClass.ROGUE); p = g.player1
        quest = play(p, cid)
        assert quest.progress == 0 and quest.zone == Zone.SECRET
        wisp = play(p, WISP)
        assert quest.progress == 1
        different = play(p, "GVG_093")
        assert quest.progress == 1, (different.id, quest.progress)
        for expected in range(2, 6):
            play(p, WISP)
            assert quest.progress == expected, (expected, quest.progress)
        reward = next((c for c in p.hand if c.id == "UNG_067t1"), None)
        assert quest.zone == Zone.GRAVEYARD and reward is not None and reward.zone == Zone.HAND
        hand_wisp = give(p, WISP)
        deck_wisp = give(p, WISP); deck_wisp.shuffle_into_deck()
        reward.play()
        board_wisps = [m for m in p.field if m.id == WISP]
        assert board_wisps and all((m.atk,m.max_health,m.health)==(4,4,4) for m in board_wisps), [(m.atk,m.health,m.max_health) for m in board_wisps]
        assert (hand_wisp.atk, hand_wisp.max_health, hand_wisp.zone) == (4,4,Zone.HAND), (hand_wisp.atk, hand_wisp.max_health, hand_wisp.zone)
        assert (deck_wisp.atk, deck_wisp.max_health, deck_wisp.zone) == (4,4,Zone.DECK), (deck_wisp.atk, deck_wisp.max_health, deck_wisp.zone)
        assert different.zone == Zone.PLAY and reward.zone == Zone.GRAVEYARD
        return f"quest_progress={quest.progress};different_name_not_counted=True;reward={reward.zone.name};board={[ (m.atk,m.health) for m in board_wisps ]};hand_wisp={hand_wisp.atk}/{hand_wisp.max_health};deck_wisp={deck_wisp.atk}/{deck_wisp.max_health}"
    record(cid, "quest_requires_five_same_name_minions_and_core_buffs_every_zone", "Five played Wisps complete the quest while a differently named minion does not count; Crystal Core sets friendly minions in play, hand, and deck to 4/4.", quest_counts_five_same_named_minions_and_crystal_core_buffs_all_zones, "逐步检查任务进度区分名称，并验证奖励对场上、手牌和牌库随从的状态刷新。")
    return finish_card(cid)


def tolvir_stoneshaper():
    cid = "UNG_070"
    def gains_taunt_and_divine_shield_only_after_prior_turn_elemental():
        g = new_game(CardClass.WARRIOR); p = g.player1
        elemental = play(p, "UNG_809")
        g.end_turn(); g.end_turn()
        stoneshaper = play(p, cid)
        assert elemental in p.field and stoneshaper.taunt and stoneshaper.divine_shield, (stoneshaper.taunt, stoneshaper.divine_shield)
        assert (stoneshaper.atk, stoneshaper.health) == (3,5)
        return f"last_turn_elemental={elemental.id};stoneshaper={stoneshaper.atk}/{stoneshaper.health};taunt={stoneshaper.taunt};shield={stoneshaper.divine_shield}"
    def same_turn_elemental_does_not_grant_keywords():
        g = new_game(CardClass.WARRIOR); p = g.player1
        elemental = play(p, "UNG_809")
        stoneshaper = play(p, cid)
        assert elemental in p.field and not stoneshaper.taunt and not stoneshaper.divine_shield, (stoneshaper.taunt, stoneshaper.divine_shield)
        return f"same_turn_elemental={elemental.id};taunt={stoneshaper.taunt};shield={stoneshaper.divine_shield}"
    record(cid, "battlecry_gains_taunt_and_shield_after_previous_turn_elemental", "An Elemental played on the previous turn gives Tol'vir Stoneshaper Taunt and Divine Shield.", gains_taunt_and_divine_shield_only_after_prior_turn_elemental, "真实跨回合打出元素，再逐项验证战吼获得嘲讽和圣盾。")
    record(cid, "battlecry_ignores_elemental_played_this_turn", "An Elemental played only this turn does not grant either keyword.", same_turn_elemental_does_not_grant_keywords, "本回合元素分支检查不误认作上回合触发条件。")
    return finish_card(cid)


def giant_mastodon():
    cid = "UNG_071"
    def taunt_blocks_enemy_charge_attack_to_hero():
        g = new_game(CardClass.WARRIOR); p, e = g.player1, g.player2
        mastodon = play(p, cid)
        assert mastodon.taunt and mastodon.zone == Zone.PLAY and mastodon.atk == mastodon.data.atk and mastodon.max_health == mastodon.data.health
        g.end_turn(); assert g.current_player is e
        attacker = play(e, "CS2_173")
        assert attacker.can_attack(), (attacker.id, attacker.can_attack())
        hero_health = p.hero.health
        try:
            attacker.attack(p.hero)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "enemy Charge minion attacked through Giant Mastodon Taunt"
        assert p.hero.health == hero_health and attacker.can_attack()
        mastodon_health = mastodon.health
        attacker.attack(mastodon)
        assert mastodon.health == mastodon_health - attacker.atk and attacker.zone == Zone.GRAVEYARD
        return f"mastodon={mastodon.atk}/{mastodon.health}/{mastodon.max_health};taunt={mastodon.taunt};face_blocked=True;attacker={attacker.zone.name}"
    record(cid, "taunt_blocks_face_and_can_be_attacked_in_combat", "Giant Mastodon's Taunt blocks a Charge minion from attacking the hero; it can instead attack Mastodon and deal combat damage.", taunt_blocks_enemy_charge_attack_to_hero, "敌方冲锋随从实际尝试攻击英雄被嘲讽阻挡，再改为攻击乳齿象。")
    return finish_card(cid)


def stonehill_defender():
    cid = "UNG_072"
    def battlecry_discovers_taunt_minion_and_adds_selected_one():
        g = new_game(CardClass.PALADIN, 7272); p = g.player1
        defender = play(p, cid)
        assert p.choice is not None
        options = list(p.choice.cards)
        assert len(options) == 3 and len({c.id for c in options}) == 3
        assert all(c.type == CardType.MINION and c.taunt for c in options), [(c.id,c.type,c.taunt) for c in options]
        selected = options[1]
        p.choice.choose(selected)
        assert p.choice is None and selected in p.hand and selected.zone == Zone.HAND
        assert defender in p.field and defender.taunt
        return f"options={[(c.id,c.taunt) for c in options]};selected={selected.id};hand={[c.id for c in p.hand]};defender_taunt={defender.taunt}"
    record(cid, "battlecry_discovers_only_taunt_minions_and_adds_choice", "Stonehill Defender's Discover offers three distinct Taunt minions; choosing one adds it to hand and closes Choice.", battlecry_discovers_taunt_minion_and_adds_selected_one, "检验三个候选的类型/嘲讽/多样性，实际选择并核对手牌和本体嘲讽。")
    return finish_card(cid)


def rockpool_hunter():
    cid = "UNG_073"
    def battlecry_buffs_only_eligible_friendly_murloc():
        g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
        friendly_murloc = summon(p, "UNG_201t")
        enemy_murloc = summon(e, "UNG_201t")
        friendly_non_murloc = summon(p, WISP)
        before_enemy = (enemy_murloc.atk, enemy_murloc.max_health)
        before_nonmurloc = (friendly_non_murloc.atk, friendly_non_murloc.max_health)
        hunter = play(p, cid, friendly_murloc)
        assert (friendly_murloc.atk, friendly_murloc.max_health, friendly_murloc.health) == (2,2,2), (friendly_murloc.atk, friendly_murloc.max_health, friendly_murloc.health)
        assert (enemy_murloc.atk, enemy_murloc.max_health) == before_enemy
        assert (friendly_non_murloc.atk, friendly_non_murloc.max_health) == before_nonmurloc
        assert hunter in p.field and friendly_murloc in p.field
        return f"friendly_murloc={friendly_murloc.atk}/{friendly_murloc.health};enemy_murloc={enemy_murloc.atk}/{enemy_murloc.max_health};friendly_nonmurloc={friendly_non_murloc.atk}/{friendly_non_murloc.max_health}"
    record(cid, "battlecry_gives_one_one_only_to_friendly_murloc", "A selected friendly Murloc gains exactly +1/+1; enemy Murlocs and friendly non-Murlocs remain unchanged.", battlecry_buffs_only_eligible_friendly_murloc, "同场布置敌我鱼人及己方非鱼人，针对己方鱼人施放并检查目标限制。")
    return finish_card(cid)


def vicious_fledgling():
    cid = "UNG_075"
    def attack_hero_triggers_adapt():
        g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
        fledgling = play(p, cid)
        g.end_turn(); g.end_turn()
        before = e.hero.health
        attack = fledgling.atk
        fledgling.attack(e.hero)
        assert e.hero.health == before - attack and p.choice is not None
        choice_id = adapt_choice(p, fledgling)
        assert len(fledgling.buffs) == 1 and fledgling.zone == Zone.PLAY
        return f"hero_health={before}->{e.hero.health};adapt={choice_id};buffs={[b.id for b in fledgling.buffs]}"
    def attack_minion_does_not_trigger_adapt():
        g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
        fledgling = play(p, cid)
        target = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        before = target.health
        fledgling.attack(target)
        assert target.health == before - fledgling.atk and p.choice is None and not fledgling.buffs, (target.health, before, p.choice, [b.id for b in fledgling.buffs])
        return f"attacked_minion_health={before}->{target.health};choice={p.choice};buffs={fledgling.buffs}"
    record(cid, "after_attack_hero_offers_adapt", "After Vicious Fledgling attacks an enemy hero, that hero takes combat damage and the minion offers one Adapt.", attack_hero_triggers_adapt, "等到下一回合真实攻击敌方英雄，检查攻击伤害与进化 Choice。")
    record(cid, "after_attack_minion_does_not_offer_adapt", "Attacking an enemy minion deals combat damage but does not trigger this hero-only Adapt effect.", attack_minion_does_not_trigger_adapt, "用同样的随从攻击敌方随从，验证文本限制为攻击英雄。")
    return finish_card(cid)


def eggnapper():
    cid = "UNG_076"
    def deathrattle_summons_two_one_one_raptors():
        g = new_game(CardClass.HUNTER); p = g.player1
        source = play(p, cid)
        source.destroy()
        tokens = [m for m in p.field if m.id == "UNG_076t1"]
        assert source.zone == Zone.GRAVEYARD and len(tokens) == 2, (source.zone, [(m.id,m.zone.name) for m in p.field])
        assert all((m.atk,m.health,m.max_health)==(1,1,1) for m in tokens)
        return f"source={source.zone.name};raptors={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]}"
    def deathrattle_respects_two_available_slots():
        g = new_game(CardClass.HUNTER); p = g.player1
        existing = [summon(p, WISP) for _ in range(5)]
        source = play(p, cid)
        source.destroy()
        tokens = [m for m in p.field if m.id == "UNG_076t1"]
        assert source.zone == Zone.GRAVEYARD and all(m in p.field for m in existing)
        assert len(tokens) == 2 and len(p.field) == 7 and all((m.atk,m.health)==(1,1) for m in tokens), [(m.id,m.zone.name) for m in p.field]
        return f"source={source.zone.name};existing={len(existing)};tokens={len(tokens)};field={len(p.field)}"
    record(cid, "deathrattle_summons_two_one_one_raptors", "Eggnapper's Deathrattle leaves it in the graveyard and summons exactly two 1/1 Raptors.", deathrattle_summons_two_one_one_raptors, "实际死亡后断言亡语令牌数量、身材和区域。")
    record(cid, "deathrattle_respects_available_board_slots", "With five other minions, the Deathrattle uses the two slots freed/available after source death and ends at seven minions.", deathrattle_respects_two_available_slots, "设置五个其他随从加本体，确认死亡处理后只占用两个空位而不超场。")
    return finish_card(cid)


def tortollan_forager():
    cid = "UNG_078"
    def battlecry_adds_eligible_random_minion_to_hand():
        seen = set(); traces = []
        for seed in range(7878, 7894):
            g = new_game(CardClass.DRUID, seed); p = g.player1
            g.random.seed(seed + 1)
            forager = play(p, cid)
            generated = list(p.hand)
            assert len(generated) == 1 and generated[0].type == CardType.MINION and generated[0].atk >= 5 and generated[0].zone == Zone.HAND, (seed, [(c.id,c.type,c.atk,c.zone.name) for c in generated])
            assert forager in p.field
            seen.add(generated[0].id); traces.append(f"{seed}:{generated[0].id}/{generated[0].atk}")
        assert len(seen) >= 2, sorted(seen)
        return f"random_eligible_cards={';'.join(traces)};distinct={sorted(seen)}"
    record(cid, "battlecry_adds_random_minion_with_at_least_five_attack", "Across fixed seeds, Forager adds exactly one minion with at least 5 Attack to hand; it does not alter a deck or summon it.", battlecry_adds_eligible_random_minion_to_hand, "固定种子实际触发随机战吼，逐次断言随从类型、攻击门槛、手牌区域和至少两种候选。")
    return finish_card(cid)


def frozen_crusher():
    cid = "UNG_079"
    def attack_freezes_self_and_blocks_next_turn_attack():
        g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
        crusher = play(p, cid)
        target = summon(e, "CS2_182"); target.max_health = 30; target.set_current_health(30)
        g.end_turn(); g.end_turn()
        assert g.current_player is p and crusher.can_attack()
        crusher.attack(target)
        assert crusher.frozen and target.health == 30 - crusher.atk and crusher.zone == Zone.PLAY, (crusher.frozen, target.health, target.zone)
        g.end_turn(); g.end_turn()
        assert g.current_player is p and crusher.frozen and not crusher.can_attack(), (crusher.frozen, crusher.can_attack())
        enemy_health = e.hero.health
        try:
            crusher.attack(e.hero)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "Frozen Crusher attacked while frozen"
        assert e.hero.health == enemy_health
        g.end_turn(); g.end_turn()
        assert g.current_player is p and not crusher.frozen and crusher.can_attack()
        return f"after_attack_frozen=True;next_owner_turn_cannot_attack=True;following_turn_frozen={crusher.frozen};can_attack={crusher.can_attack()}"
    record(cid, "after_attack_freezes_self_until_its_next_turn_expires", "After attacking, Frozen Crusher freezes itself; it cannot attack during its next turn, then can attack after that turn ends.", attack_freezes_self_and_blocks_next_turn_attack, "对敌方高生命随从真实攻击，逐回合检查自我冻结、阻止攻击和解冻后可攻击。")
    return finish_card(cid)


def thunder_lizard():
    cid = "UNG_082"
    def prior_turn_elemental_offers_one_adapt():
        g = new_game(CardClass.HUNTER); p = g.player1
        elemental = play(p, "UNG_809")
        g.end_turn(); g.end_turn()
        lizard = play(p, cid)
        choice_id = adapt_choice(p, lizard)
        assert elemental in p.field and lizard in p.field
        return f"elemental_last_turn={elemental.id};adapt={choice_id};buffs={[b.id for b in lizard.buffs]}"
    def no_last_turn_elemental_means_no_adapt():
        g = new_game(CardClass.HUNTER); p = g.player1
        lizard = play(p, cid)
        assert p.choice is None and not lizard.buffs
        return f"elemental_last_turn=False;choice={p.choice};buffs={lizard.buffs}"
    record(cid, "battlecry_adapts_if_elemental_played_last_turn", "A previous-turn Elemental causes Thunder Lizard to offer and apply one Adapt.", prior_turn_elemental_offers_one_adapt, "真实跨回合打出元素后检查战吼 Choice 与单次进化。")
    record(cid, "battlecry_without_last_turn_elemental_has_no_adapt", "Without an Elemental played on the prior turn, Thunder Lizard offers no Adapt.", no_last_turn_elemental_means_no_adapt, "无条件分支检查不出现 Choice 或错误增益。")
    return finish_card(cid)


def devilsaur_egg():
    cid = "UNG_083"
    def deathrattle_summons_one_five_five_devilsaur():
        g = new_game(CardClass.HUNTER); p = g.player1
        egg = play(p, cid)
        egg.destroy()
        tokens = [m for m in p.field if m.id == "UNG_083t1"]
        assert egg.zone == Zone.GRAVEYARD and len(tokens) == 1, (egg.zone, [(m.id,m.zone.name) for m in p.field])
        assert (tokens[0].atk,tokens[0].health,tokens[0].max_health)==(5,5,5) and tokens[0].zone==Zone.PLAY
        return f"egg={egg.zone.name};devilsaur={tokens[0].id}/{tokens[0].atk}/{tokens[0].health}/{tokens[0].zone.name}"
    record(cid, "deathrattle_summons_five_five_devilsaur", "When Devilsaur Egg dies, it enters the graveyard and summons exactly one 5/5 Devilsaur.", deathrattle_summons_one_five_five_devilsaur, "实际消灭蛋，断言亡语发生、随从 ID、身材和所在区域。")
    return finish_card(cid)


def fire_plume_phoenix():
    cid = "UNG_084"
    def battlecry_can_hit_enemy_minion_or_hero():
        g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
        minion = summon(e, "CS2_182")
        phoenix = play(p, cid, minion)
        assert minion.health == 3 and minion.max_health == 5 and phoenix in p.field
        e.hero.set_current_health(20)
        second = play(p, cid, e.hero)
        assert e.hero.health == 18 and minion.health == 3 and second in p.field
        return f"minion_target={minion.health}/{minion.max_health};hero_target={20}->{e.hero.health};phoenixes={[m.zone.name for m in (phoenix,second)]}"
    record(cid, "battlecry_deals_two_to_selected_minion_or_hero", "Fire Plume Phoenix can deal 2 damage to an enemy minion or hero while both Phoenixes remain in play.", battlecry_can_hit_enemy_minion_or_hero, "分别指定敌方随从和英雄，核对两点伤害且不误伤其他目标。")
    return finish_card(cid)


def emerald_hive_queen():
    cid = "UNG_085"
    def aura_increases_owner_minion_costs_and_expires():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        yeti = give(p, "CS2_182")
        wisp_to_play = give(p, WISP)
        wisp_remaining = give(p, WISP)
        enemy_yeti = give(e, "CS2_182")
        queen = play(p, cid)
        assert (yeti.cost,wisp_to_play.cost,wisp_remaining.cost,enemy_yeti.cost) == (6,2,2,4), (yeti.cost,wisp_to_play.cost,wisp_remaining.cost,enemy_yeti.cost)
        mana_before = p.used_mana
        wisp_to_play.play()
        assert p.used_mana == mana_before + 2 and wisp_to_play in p.field, (p.used_mana,mana_before,wisp_to_play.zone)
        queen.destroy()
        assert queen.zone == Zone.GRAVEYARD and yeti.cost == 4 and wisp_remaining.cost == 0 and enemy_yeti.cost == 4
        return f"while_aura=yeti6/wisp2/enemy_yeti4;played_wisp_mana_delta={p.used_mana-mana_before};after_source_death=yeti{yeti.cost}/wisp{wisp_remaining.cost}/enemy_yeti{enemy_yeti.cost}"
    record(cid, "aura_adds_two_to_owner_minions_and_reverts_when_removed", "Emerald Hive Queen adds 2 cost to minions in its controller's hand, charges that amount when one is played, leaves opponent costs unchanged, and restores costs after leaving play.", aura_increases_owner_minion_costs_and_expires, "检查已有手牌、零费和高费随从、对手牌费用、实际付费以及光环源死亡后的费用恢复。")
    return finish_card(cid)


def giant_anaconda():
    cid = "UNG_086"
    def deathrattle_summons_only_high_attack_hand_minion():
        seen = set(); traces = []
        for seed in range(8686, 8702):
            g = new_game(CardClass.DRUID, seed); p = g.player1
            source = play(p, cid)
            high_a = give(p, "UNG_087")
            high_b = give(p, "UNG_071")
            low_a = give(p, WISP)
            low_b = give(p, "CS2_182")
            g.random.seed(seed + 1)
            source.destroy()
            summoned = [c for c in (high_a,high_b) if c.zone == Zone.PLAY]
            assert source.zone == Zone.GRAVEYARD and len(summoned) == 1, (seed, source.zone, [(c.id,c.zone.name,c.atk) for c in (high_a,high_b,low_a,low_b)])
            assert all(c.zone == Zone.HAND for c in (low_a,low_b)) and len([c for c in (high_a,high_b) if c.zone == Zone.HAND]) == 1
            chosen = summoned[0]
            assert chosen.atk >= 5 and chosen in p.field
            seen.add(chosen.id); traces.append(f"{seed}:{chosen.id}/{chosen.atk}")
        assert seen == {"UNG_087", "UNG_071"}, (seen,traces)
        return f"summoned_across_seeds={';'.join(traces)};distinct_eligible={sorted(seen)};low_attack_stayed_in_hand=True"
    record(cid, "deathrattle_randomly_summons_from_hand_only_minions_at_least_five_attack", "Across fixed seeds, Anaconda summons exactly one hand minion with at least 5 Attack, leaves lower-Attack minions in hand, and preserves the unsummoned eligible option.", deathrattle_summons_only_high_attack_hand_minion, "每局放入两张合格及两张不合格手牌，触发亡语后检查资格筛选、随机选择、区域和多样性。")
    return finish_card(cid)


def bittertide_hydra():
    cid = "UNG_087"
    def each_damage_event_hits_own_hero_three():
        g = new_game(CardClass.HUNTER); p = g.player1
        hydra = play(p, cid)
        p.hero.set_current_health(20)
        for expected_health in (17,14):
            spell = give(p, MOONFIRE)
            spell.play(target=hydra)
            assert p.hero.health == expected_health, (expected_health,p.hero.health)
            assert hydra.zone == Zone.PLAY and hydra.damage == (hydra.max_health - hydra.health), (hydra.zone,hydra.damage,hydra.health,hydra.max_health)
        assert hydra.health == hydra.max_health - 2 and hydra.damage == 2
        return f"two_one_damage_events=2;hydra={hydra.health}/{hydra.max_health};hero=20->{p.hero.health}"
    def lethal_damage_still_triggers_hero_penalty():
        g = new_game(CardClass.HUNTER); p = g.player1
        hydra = play(p, cid)
        hydra.set_current_health(1)
        p.hero.set_current_health(20)
        spell = give(p, MOONFIRE); spell.play(target=hydra)
        assert hydra.zone == Zone.GRAVEYARD and p.hero.health == 17, (hydra.zone,p.hero.health)
        return f"hydra={hydra.zone.name};hero=20->{p.hero.health};spell={spell.zone.name}"
    record(cid, "trigger_deals_three_hero_damage_for_each_damage_event", "Each of two separate 1-damage events to Hydra deals 3 damage to its controller's hero.", each_damage_event_hits_own_hero_three, "连续两次非致死法术伤害，检查触发次数、随从伤害和英雄累计损失。")
    record(cid, "trigger_still_deals_hero_damage_on_lethal_hit", "A lethal damage event still deals 3 damage to the Hydra controller's hero before/with death processing.", lethal_damage_still_triggers_hero_penalty, "将海德拉降至1点生命后造成致死伤害，核对亡语前的触发和墓地状态。")
    return finish_card(cid)


PROBES = [pterrordax_hatchling, volcanosaur, dinosize, ravasaur_runt, sated_threshadon,
          hydrologist, sunkeeper_tarim, flame_geyser, air_elemental, arcanologist,
          steam_surger, mirage_caller, mana_bind, volcano, pyros, open_the_waygate,
          shadow_visions, binding_heal, crystalline_oracle, radiant_elemental,
          curious_glimmerroot, ravenous_pterrordax, tar_lurker, razorpetal_volley,
          razorpetal_lasher, mimic_pod, obsidian_shard, biteweed, vilespine_slayer,
          sherazin_corpse_flower, caverns_below, tolvir_stoneshaper, giant_mastodon,
          stonehill_defender, rockpool_hunter, vicious_fledgling, eggnapper,
          tortollan_forager, frozen_crusher, thunder_lizard, devilsaur_egg,
          fire_plume_phoenix, emerald_hive_queen, giant_anaconda, bittertide_hydra]


def main():
    assert len(OWN_IDS) == 45 and OWN_IDS[0] == "UNG_001" and OWN_IDS[-1] == "UNG_087", (len(OWN_IDS), OWN_IDS[:3], OWN_IDS[-3:])
    for probe in PROBES:
        status = probe()
        print(f"{probe.__name__}: {status}", flush=True)
    expected_now = {"UNG_001", "UNG_002", "UNG_004", "UNG_009", "UNG_010", "UNG_011", "UNG_015", "UNG_018", "UNG_019", "UNG_020", "UNG_021", "UNG_022", "UNG_024", "UNG_025", "UNG_027", "UNG_028", "UNG_029", "UNG_030", "UNG_032", "UNG_034", "UNG_035", "UNG_047", "UNG_049", "UNG_057", "UNG_058", "UNG_060", "UNG_061", "UNG_063", "UNG_064", "UNG_065", "UNG_067", "UNG_070", "UNG_071", "UNG_072", "UNG_073", "UNG_075", "UNG_076", "UNG_078", "UNG_079", "UNG_082", "UNG_083", "UNG_084", "UNG_085", "UNG_086", "UNG_087"}
    verdicts = [r for r in VERDICT_ROWS if r["card_id"] in OWN_IDS]
    active_verdicts = [r for r in verdicts if r["card_id"] in expected_now]
    cards_with_cases = {r["card_id"] for r in PROBE_ROWS if r["card_id"] in expected_now}
    assert len(active_verdicts) == len(expected_now) and cards_with_cases == expected_now, (len(active_verdicts), cards_with_cases ^ expected_now)
    active_probes = [r for r in PROBE_ROWS if r["card_id"] in expected_now]
    assert len({(r["card_id"], r["case_id"]) for r in active_probes}) == len(active_probes)
    counts = {status: sum(r["status"] == status for r in active_verdicts) for status in ("GREEN", "YELLOW", "RED")}
    print(f"summary batch_cards={len(active_verdicts)} probes={len(active_probes)} counts={counts}", flush=True)


if __name__ == "__main__":
    main()
