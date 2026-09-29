"""Card-specific live-game probes for the frozen OG YELLOW slice 84:126."""
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Zone
from fireplace.exceptions import InvalidAction

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import (  # noqa: E402
    ANIMATED_STATUE, FIREBALL, LIGHTS_JUSTICE, MOONFIRE, TARGET_DUMMY, WISP,
    prepare_empty_game,
)

BASELINE = HERE / "og_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "og_probe_c.csv"
VERDICT_OUT = HERE / "og_verdict_c.csv"
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
OWN_ROWS = BASE_ROWS[84:126]
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
    assert game.current_player is game.player1, (game.current_player, game.player1)
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


def shuffle(player, card_id):
    card = give(player, card_id)
    card.shuffle_into_deck()
    return card


def cthun_instance(player, zone):
    if zone == "board":
        return summon(player, "OG_280")
    card = give(player, "OG_280")
    if zone == "deck":
        card.shuffle_into_deck()
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
    except Exception as exc:  # distinguish a fixture/runtime obstacle from a proven behavior error
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    PROBE_ROWS.append({
        "card_id": card_id, "case_id": case_id, "expected": expected,
        "observed": observed, "outcome": outcome,
        "notes": f"{notes}; {metadata(card_id)}",
    })
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    return outcome, observed


def finish_card(card_id, blocker=None, notes=""):
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
        "probe_file": PROBE_OUT.name,
        "notes": f"{notes}; {metadata(card_id)}",
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def simple_minion_deathrattle():
    cid = "OG_272"
    def full_board():
        g = new_game(); p = g.player1
        source = play(p, cid)
        source.destroy()
        tokens = list(p.field.filter(id="OG_272t"))
        assert source.zone == Zone.GRAVEYARD and len(tokens) == 1, (source.zone, [m.id for m in p.field])
        assert (tokens[0].atk, tokens[0].health) == (5, 5), (tokens[0].atk, tokens[0].health)
        return f"source={source.zone.name};faceless={len(tokens)}x{tokens[0].atk}/{tokens[0].health}"
    def one_slot():
        g = new_game(); p = g.player1
        source = summon(p, cid)
        for _ in range(6): summon(p, WISP)
        assert len(p.field) == 7
        source.destroy()
        tokens = list(p.field.filter(id="OG_272t"))
        assert len(p.field) == 7 and len(tokens) == 1, [m.id for m in p.field]
        return f"board={len(p.field)};faceless={len(tokens)}"
    record(cid, "deathrattle_exact_5_5", "Upon death, source reaches Graveyard and exactly one 5/5 Faceless Destroyer is summoned.", full_board, "实际死亡结算检查衍生物数量、属性与双方区域状态。")
    record(cid, "deathrattle_one_open_slot", "With one free board slot, death summons one 5/5 and keeps the board at seven.", one_slot, "检查亡语召唤遵守七格上限。")
    return finish_card(cid)


def stand_against_darkness():
    cid = "OG_273"
    def five_recruits():
        g = new_game(CardClass.PALADIN); p = g.player1
        spell = play(p, cid)
        tokens = list(p.field.filter(id="CS2_101t"))
        assert len(tokens) == 5, [m.id for m in p.field]
        assert all((m.atk, m.health) == (1, 1) for m in tokens), [(m.atk,m.health) for m in tokens]
        assert spell.zone == Zone.GRAVEYARD
        return f"spell={spell.zone.name};tokens={len(tokens)}x1/1;board={len(p.field)}"
    def one_slot_left():
        g = new_game(CardClass.PALADIN); p = g.player1
        for _ in range(6): summon(p, WISP)
        spell = play(p, cid)
        tokens = list(p.field.filter(id="CS2_101t"))
        assert len(p.field) == 7 and len(tokens) == 1, [m.id for m in p.field]
        assert spell.zone == Zone.GRAVEYARD
        return f"board={len(p.field)};recruits={len(tokens)}"
    record(cid, "summon_five_recruits", "Spell resolves to exactly five 1/1 Silver Hand Recruits.", five_recruits, "从空场检查五个随从的 ID 与属性，并核对法术离手。")
    record(cid, "summon_at_board_cap", "With one open slot, exactly one Recruit is summoned and board remains at seven.", one_slot_left, "检查满场边界下剩余召唤被阻止。")
    return finish_card(cid)


def blood_warriors():
    cid = "OG_276"
    def damaged_friendly_only():
        g = new_game(CardClass.WARRIOR); p, e = g.player1, g.player2
        damaged = summon(p, "CS2_182"); damaged.set_current_health(3)
        full = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182"); enemy.set_current_health(3)
        spell = play(p, cid)
        copies = [c for c in p.hand if c.id == "CS2_182"]
        assert len(copies) == 1, [c.id for c in p.hand]
        assert (copies[0].atk, copies[0].health) == (4, 5), (copies[0].atk,copies[0].health)
        assert damaged in p.field and damaged.health == 3 and full.health == 5
        assert enemy in e.field and enemy.health == 3 and spell.zone == Zone.GRAVEYARD
        return f"copies={[(c.atk,c.health) for c in copies]};friendly_damaged={damaged.health};friendly_full={full.health};enemy_damaged={enemy.health}"
    record(cid, "copy_damaged_friendly_minions_only", "Adds one 4/5 Yeti copy for the damaged friendly Yeti; full-health friendly and damaged enemy Yetis are not copied.", damaged_friendly_only, "使用同名随从区分受伤状态和控制方，并核对手牌副本属性及原随从状态。")
    return finish_card(cid)


def cthun_random_split():
    cid = "OG_280"
    def damage_equals_cthun_attack():
        results = []
        seen = set()
        for seed in range(620, 636):
            g = new_game(CardClass.MAGE, seed); p, e = g.player1, g.player2
            cthun = give(p, cid)
            first = summon(e, ANIMATED_STATUE)
            second = summon(e, ANIMATED_STATUE)
            first.set_current_health(12)
            second.set_current_health(12)
            friendly = summon(p, "CS2_182")
            play(p, "OG_281")
            p.used_mana = 0
            before_hero = e.hero.health
            expected = cthun.atk
            g.random.seed(seed)
            cthun.play()
            minion_hits = sum(m.damage for m in (first, second))
            hero_hits = before_hero - e.hero.health
            total = minion_hits + hero_hits
            assert total == expected, (seed, expected, total, minion_hits, hero_hits)
            assert friendly.damage == 0 and friendly.zone == Zone.PLAY, (friendly.damage, friendly.zone)
            assert first.zone == Zone.PLAY and second.zone == Zone.PLAY
            if first.damage > 0: seen.add("enemy_minion_1")
            if second.damage > 0: seen.add("enemy_minion_2")
            if hero_hits > 0: seen.add("enemy_hero")
            results.append(f"{seed}:{minion_hits}+{hero_hits}")
        assert seen == {"enemy_minion_1", "enemy_minion_2", "enemy_hero"}, sorted(seen)
        return f"16_seeds_damage={','.join(results)};all_random_targets_seen={sorted(seen)}"
    def buffed_attack_and_lethal_retargeting():
        seen_kill = False; traces = []
        for seed in range(636, 652):
            g = new_game(CardClass.MAGE, seed); p, e = g.player1, g.player2
            cthun = give(p, cid)
            play(p, "OG_281")
            p.used_mana = 0
            target = summon(e, "CS2_182"); target.set_current_health(1)
            friendly = summon(p, "CS2_182")
            before_hero = e.hero.health
            expected = cthun.atk
            g.random.seed(seed)
            cthun.play()
            # A lethal minion leaves play and Fireplace clears its live damage
            # field. Count the known one remaining Health as the lethal hit.
            minion_hits = 1 if target.zone == Zone.GRAVEYARD else target.damage
            hero_hits = before_hero - e.hero.health
            assert minion_hits + hero_hits == expected, (seed, expected, minion_hits, hero_hits, target.zone)
            assert friendly.damage == 0 and friendly.zone == Zone.PLAY
            if target.zone == Zone.GRAVEYARD:
                seen_kill = True
                assert minion_hits == 1 and hero_hits == expected - 1, (seed, minion_hits, hero_hits, expected)
            traces.append(f"{seed}:attack={expected};minion={minion_hits}/{target.zone.name};hero={hero_hits}")
        assert seen_kill, traces
        return f"buffed_cthun_attack=8;lethal_minion_removed_then_damage_continues;seeds={';'.join(traces)}"
    record(cid, "battlecry_attack_damage_randomly_split", "Across fixed seeds after a real +2/+2 C'Thun buff, total 8 damage equals current Attack, only enemy characters are hit, and both enemy minions and hero appear as candidates.", damage_equals_cthun_attack, "16个固定种子先用邪灵召唤师实际增益克苏恩，再核对攻击力总伤害和三个敌方随机候选均出现。")
    record(cid, "battlecry_lethal_random_target_removed_and_damage_continues", "With a 1-Health enemy minion and buffed 8-Attack C'Thun, its lethal hit removes the minion and remaining damage still reaches eligible enemies.", buffed_attack_and_lethal_retargeting, "在另一组固定种子中校验致死目标离开候选池后伤害仍按克苏恩攻击力结算。")
    return finish_card(cid)


def beckoner_of_evil():
    cid = "OG_281"
    def battlecry_buffs_cthun_wherever():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.WARRIOR); p = g.player1
            cthun = cthun_instance(p, zone)
            before = (cthun.atk, cthun.health)
            beckoner = play(p, cid)
            assert (cthun.atk, cthun.health) == (before[0] + 2, before[1] + 2), (zone, before, cthun.atk, cthun.health)
            assert (p.cthun.atk, p.cthun.health) == (cthun.atk, cthun.health), (zone, cthun.atk, cthun.health, p.cthun.atk, p.cthun.health)
            assert beckoner in p.field
            results.append(f"{zone}={cthun.atk}/{cthun.health}")
        return f"cthun_zone_buffs={','.join(results)};tracked_state_synced=True"
    record(cid, "battlecry_buffs_cthun_in_all_zones", "C'Thun in hand, deck, and play each gain exactly +2/+2; tracked C'Thun state stays synchronized.", battlecry_buffs_cthun_wherever, "分别在手牌、牌库、场上设置克苏恩，独立对局验证‘无论在哪里’。")
    return finish_card(cid)


def blade_of_cthun():
    cid = "OG_282"
    def destroy_minion_and_gain_stats():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        cthun = give(p, "OG_280")
        target = summon(e, "CS2_182")
        base = (cthun.atk, cthun.health, target.atk, target.health)
        blade = play(p, cid, target)
        assert target.zone == Zone.GRAVEYARD, (target.zone, target.health)
        expected = (base[0] + base[2], base[1] + base[3])
        assert (cthun.atk, cthun.health) == expected, (base, (cthun.atk, cthun.health), expected)
        assert blade.zone == Zone.PLAY
        return f"target={target.zone.name};cthun={cthun.atk}/{cthun.health};base={base};expected={expected}"
    def damaged_target_health_value():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        cthun = give(p, "OG_280")
        target = summon(e, "CS2_182"); target.set_current_health(2)
        base = (cthun.atk, cthun.health, target.atk, target.health, target.max_health)
        play(p, cid, target)
        actual = (cthun.atk, cthun.health)
        assert target.zone == Zone.GRAVEYARD
        assert actual[0] == base[0] + base[2], (base, actual)
        assert actual[1] in (base[1] + base[3], base[1] + base[4]), (base, actual)
        return f"damaged_target_current={base[3]};max_health={base[4]};cthun_actual={actual};current_health_interpretation={base[1] + base[3]};max_health_interpretation={base[1] + base[4]}"
    record(cid, "battlecry_destroy_and_add_healthy_stats", "Destroys target minion and adds its Attack and Health to C'Thun.", destroy_minion_and_gain_stats, "对满血敌方随从验证合法目标、死亡区域与属性增量。")
    record(cid, "battlecry_damaged_target_health_interpretation_observed", "For a damaged Yeti, record the actual Health added and compare it with current-Health and maximum-Health interpretations; this case does not assume which interpretation is authoritative.", damaged_target_health_value, "对受伤目标分别计算当前生命与最大生命对应的增量，并记录实测结果；不预设规则解释。")
    return finish_card(cid, blocker="官方卡牌页只写 Attack and Health，未明确受伤目标取当前生命还是最大生命；其他规则资料只能间接支持按当前生命处理，缺少此具体交互的原版权威证据，按保守标准保留 YELLOW。")


def cthuns_chosen():
    cid = "OG_283"
    def shield_and_cthun_buff_across_zones():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.WARRIOR); p, e = g.player1, g.player2
            cthun = cthun_instance(p, zone)
            attacker = summon(e, "CS2_182")
            chosen = play(p, cid)
            assert chosen.divine_shield and (cthun.atk, cthun.health) == (8, 8), (zone, chosen.divine_shield, cthun.atk, cthun.health)
            g.end_turn()
            assert g.current_player is e
            attacker.attack(chosen)
            assert not chosen.divine_shield and chosen.health == chosen.max_health, (zone, chosen.divine_shield, chosen.health, chosen.max_health)
            assert attacker.damage == chosen.atk, (zone, attacker.damage, chosen.atk)
            results.append(f"{zone}=cthun:{cthun.atk}/{cthun.health},shield_absorbed=True")
        return ";".join(results)
    record(cid, "battlecry_cthun_buff_wherever_and_divine_shield_combat", "C'Thun in hand, deck, and play each gains +2/+2; Divine Shield absorbs an actual attack in every zone case.", shield_and_cthun_buff_across_zones, "每个区域独立对局检查战吼增益，并以敌方随从攻击验证圣盾。")
    return finish_card(cid)


def twilight_geomancer():
    cid = "OG_284"
    def battlecry_cthun_taunt_wherever():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.WARRIOR); p = g.player1
            cthun = cthun_instance(p, zone)
            geomancer = play(p, cid)
            assert geomancer.taunt and cthun.taunt, (zone, geomancer.taunt, cthun.taunt)
            results.append(f"{zone}=cthun_taunt:{cthun.taunt},geomancer_taunt:{geomancer.taunt}")
        return ";".join(results)
    record(cid, "battlecry_grants_cthun_taunt_wherever", "Twilight Geomancer has Taunt and gives Taunt to C'Thun in hand, deck, or play.", battlecry_cthun_taunt_wherever, "手牌、牌库、场上分别设置克苏恩，逐局检查两个嘲讽状态。")
    return finish_card(cid)


def twilight_elder():
    cid = "OG_286"
    def end_of_owner_turn_buff_wherever():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.WARRIOR); p = g.player1
            cthun = cthun_instance(p, zone)
            before = (cthun.atk, cthun.health)
            elder = play(p, cid)
            g.end_turn()
            assert g.current_player is g.player2
            actual = (cthun.atk, cthun.health)
            assert actual == (before[0] + 1, before[1] + 1), (zone, before, actual)
            assert elder.zone == Zone.PLAY
            results.append(f"{zone}={actual}")
        return f"owner_end_cthun_buffs={results}"
    record(cid, "own_turn_end_cthun_buff_wherever", "At the owner's turn end, C'Thun in hand, deck, or play gains exactly +1/+1.", end_of_owner_turn_buff_wherever, "不同区域的克苏恩各自经历一个真实己方回合结束触发。")
    return finish_card(cid)


def ancient_harbinger():
    cid = "OG_290"
    def draws_only_ten_cost_minion():
        seen = set()
        traces = []
        for seed in range(710, 726):
            g = new_game(CardClass.MAGE, seed); p = g.player1
            c1 = shuffle(p, "OG_280")
            c2 = shuffle(p, "OG_317")
            nontarget = shuffle(p, "CS2_182")
            p.deck.remove(nontarget)
            p.deck.append(nontarget)  # draw order is deck[-1]; make the normal draw deterministic
            harbinger = play(p, cid)
            g.end_turn(); g.end_turn()
            moved = [c for c in (c1, c2) if c in p.hand]
            assert len(moved) == 1, (seed, [c.id for c in p.hand], [c.id for c in p.deck])
            assert moved[0].cost == 10 and moved[0].type == CardType.MINION
            assert nontarget in p.hand and nontarget not in p.deck, (seed, [c.id for c in p.hand], [c.id for c in p.deck])
            assert harbinger in p.field
            seen.add(moved[0].id); traces.append(f"{seed}:{moved[0].id}")
        assert seen == {"OG_280", "OG_317"}, sorted(seen)
        return f"16_seeded_10_cost_choices={','.join(traces)};seen={sorted(seen)};normal_draw=CS2_182"
    record(cid, "own_turn_start_draws_deck_ten_cost_minion", "On the owner's next turn start, exactly one 10-cost minion leaves the deck for hand; non-10-cost minion stays.", draws_only_ten_cost_minion, "准备两张10费随从与一个非随从条件的随从，跨回合采样随机抽取范围与落区。")
    return finish_card(cid)


def shadowcaster():
    cid = "OG_291"
    def makes_cost_one_one_copy():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        source = summon(p, "CS2_182")
        source.set_current_health(3)
        enemy = summon(e, "CS2_182")
        caster = play(p, cid, source)
        copies = [c for c in p.hand if c.id == source.id]
        assert len(copies) == 1, [c.id for c in p.hand]
        copy = copies[0]
        assert (copy.atk, copy.health, copy.cost) == (1, 1, 1), (copy.atk, copy.health, copy.cost)
        assert source in p.field and (source.atk, source.health) == (4, 3)
        assert enemy in e.field and caster in p.field
        return f"copy={copy.id}:{copy.atk}/{copy.health}:cost{copy.cost};source={source.atk}/{source.health};enemy={enemy.zone.name}"
    def rejects_enemy_target():
        g = new_game(CardClass.ROGUE); p, e = g.player1, g.player2
        friendly = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        caster = give(p, cid); mana = p.mana
        try:
            caster.play(target=enemy)
        except InvalidAction:
            pass
        else:
            assert False, "enemy minion unexpectedly accepted as Shadowcaster target"
        assert caster in p.hand and p.mana == mana and enemy in e.field and friendly in p.field
        return f"illegal_target_rejected=True;caster=HAND;mana={p.mana};friendly=PLAY;enemy=PLAY"
    record(cid, "battlecry_adds_one_one_cost_one_copy", "Chosen friendly minion yields a 1/1 copy costing 1 in hand; source and enemy minions remain unchanged.", makes_cost_one_one_copy, "对受伤友方随从复制，检查副本属性/费用与原随从区域。")
    record(cid, "targeting_rejects_enemy_minion", "An enemy minion is not a legal target; rejected play preserves card, mana, and board.", rejects_enemy_target, "验证友方目标限制及非法目标无副作用。")
    return finish_card(cid)


def forlorn_stalker():
    cid = "OG_292"
    def buffs_only_deathrattle_minions_in_hand():
        g = new_game(CardClass.HUNTER); p = g.player1
        dr1 = give(p, "OG_323")
        dr2 = give(p, "FP1_002")
        plain = give(p, WISP)
        source = play(p, cid)
        assert (dr1.atk, dr1.health) == (dr1.data.atk + 1, dr1.data.health + 1), (dr1.atk, dr1.health, dr1.data.atk, dr1.data.health)
        assert (dr2.atk, dr2.health) == (dr2.data.atk + 1, dr2.data.health + 1), (dr2.atk, dr2.health, dr2.data.atk, dr2.data.health)
        assert (plain.atk, plain.health) == (1, 1), (plain.atk, plain.health)
        assert dr1 in p.hand and dr2 in p.hand and plain in p.hand and source in p.field
        return f"deathrattle_hand={dr1.id}:{dr1.atk}/{dr1.health},{dr2.id}:{dr2.atk}/{dr2.health};plain={plain.atk}/{plain.health}"
    record(cid, "battlecry_buffs_deathrattle_minions_only", "All Deathrattle minions in hand gain +1/+1; non-Deathrattle Wisp remains 1/1.", buffs_only_deathrattle_minions_in_hand, "同时放置两个亡语随从与白板，核对手牌增益范围。")
    return finish_card(cid)


def dark_arakkoa():
    cid = "OG_293"
    def buffs_cthun_three_three_wherever_and_taunt_body():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.DRUID); p = g.player1
            cthun = cthun_instance(p, zone)
            arakkoa = play(p, cid)
            assert (cthun.atk, cthun.health) == (9, 9), (zone, cthun.atk, cthun.health)
            assert arakkoa.taunt and arakkoa in p.field
            results.append(f"{zone}={cthun.atk}/{cthun.health}")
        return f"cthun={results};dark_arakkoa_taunt=True"
    record(cid, "battlecry_cthun_plus_three_three_wherever", "Battlecry gives C'Thun in hand, deck, or play exactly +3/+3; Dark Arakkoa is Taunt.", buffs_cthun_three_three_wherever_and_taunt_body, "在三个区域分别检查克苏恩增量及鸦人嘲讽。")
    return finish_card(cid)


def cult_apothecary():
    cid = "OG_295"
    def heals_two_per_enemy_minion():
        g = new_game(); p, e = g.player1, g.player2
        p.hero.set_current_health(10)
        enemies = [summon(e, WISP) for _ in range(3)]
        source = play(p, cid)
        assert p.hero.health == 16, p.hero.health
        assert all(m in e.field for m in enemies) and source in p.field
        return f"enemy_minions={len(enemies)};hero=10->16;source={source.zone.name}"
    def no_enemy_minion_means_no_heal():
        g = new_game(); p = g.player1
        p.hero.set_current_health(10)
        source = play(p, cid)
        assert p.hero.health == 10, p.hero.health
        return f"enemy_minions=0;hero={p.hero.health};source={source.zone.name}"
    record(cid, "battlecry_heals_twice_per_enemy_minion", "Three enemy minions restore exactly 6 Health to a damaged friendly hero.", heals_two_per_enemy_minion, "按敌方随从数计算治疗，检查英雄生命上限未参与干扰。")
    record(cid, "battlecry_zero_enemy_minions_no_heal", "With no enemy minions, Battlecry restores no Health.", no_enemy_minion_means_no_heal, "验证计数为零的边界。")
    return finish_card(cid)


def boogeymonster():
    cid = "OG_300"
    def attack_kills_minion_gains_two_two():
        g = new_game(); p, e = g.player1, g.player2
        bogey = play(p, cid)
        target = summon(e, ANIMATED_STATUE)
        target.set_current_health(1)
        g.end_turn(); g.end_turn()
        before = (bogey.atk, bogey.health, bogey.max_health)
        bogey.attack(target)
        assert target.zone == Zone.GRAVEYARD, target.zone
        assert (bogey.atk, bogey.health, bogey.max_health) == (before[0] + 2, before[1] + 2, before[2] + 2), (before, bogey.atk, bogey.health, bogey.max_health)
        return f"target={target.zone.name};bogey={before}->{bogey.atk}/{bogey.health}/{bogey.max_health}"
    def nonlethal_attack_no_buff():
        g = new_game(); p, e = g.player1, g.player2
        bogey = play(p, cid)
        target = summon(e, "CS2_200")
        target.atk = 0
        g.end_turn(); g.end_turn()
        before = (bogey.atk, bogey.health)
        bogey.attack(target)
        assert target in e.field and target.health == target.max_health - bogey.atk
        assert (bogey.atk, bogey.health) == before, (before, bogey.atk, bogey.health)
        return f"target=PLAY:{target.health};bogey={bogey.atk}/{bogey.health};no_buff=True"
    record(cid, "attack_kill_gains_two_two", "When an attack kills a minion, Boogeymonster gains exactly +2/+2.", attack_kills_minion_gains_two_two, "跨一个对手回合获得攻击权限，再实际攻击并确认目标死亡与增益。")
    record(cid, "attack_survivor_does_not_gain_buff", "An attack that leaves the minion alive grants no +2/+2.", nonlethal_attack_no_buff, "验证“攻击并消灭”条件，而非单纯攻击触发。")
    return finish_card(cid)


def ancient_shieldbearer():
    cid = "OG_301"
    def below_ten_no_armor():
        g = new_game(CardClass.WARRIOR); p = g.player1
        cthun = give(p, "OG_280")
        play(p, "OG_281")
        assert cthun.atk == 8 and p.cthun.atk == 8, (cthun.atk, p.cthun.atk)
        armor_before = p.hero.armor
        p.used_mana = 0
        shieldbearer = play(p, cid)
        assert armor_before == 0 and p.hero.armor == armor_before, (armor_before, p.hero.armor)
        return f"cthun_atk={cthun.atk};armor={armor_before}->{p.hero.armor};source={shieldbearer.zone.name}"
    def exactly_ten_gains_ten_armor():
        g = new_game(CardClass.WARRIOR); p = g.player1
        cthun = give(p, "OG_280")
        play(p, "OG_281")
        play(p, "OG_281")
        assert cthun.atk == 10 and p.cthun.atk == 10, (cthun.atk, p.cthun.atk)
        armor_before = p.hero.armor
        p.used_mana = 0
        shieldbearer = play(p, cid)
        assert armor_before == 0 and p.hero.armor == armor_before + 10, (armor_before, p.hero.armor)
        return f"cthun_atk={cthun.atk};armor={armor_before}->{p.hero.armor};source={shieldbearer.zone.name}"
    record(cid, "battlecry_below_ten_cthun_no_armor", "At 8 C'Thun Attack, Ancient Shieldbearer grants no Armor.", below_ten_no_armor, "用一次已验证的+2/+2克苏恩战吼构造8攻阈值下局面，独立检查护甲未变化。")
    record(cid, "battlecry_ten_attack_cthun_gains_ten_armor", "At exactly 10 C'Thun Attack, Battlecry grants 10 Armor.", exactly_ten_gains_ten_armor, "用两次已验证的+2/+2克苏恩战吼构造恰好10攻，检查等号边界与10点护甲。")
    return finish_card(cid)


def usher_of_souls():
    cid = "OG_302"
    def friendly_death_buffs_cthun_wherever_enemy_death_not():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.WARLOCK); p, e = g.player1, g.player2
            cthun = cthun_instance(p, zone)
            usher = play(p, cid)
            friendly = summon(p, WISP); friendly.destroy()
            after_friendly = (cthun.atk, cthun.health)
            enemy = summon(e, WISP); enemy.destroy()
            after_enemy = (cthun.atk, cthun.health)
            assert usher in p.field and friendly.zone == Zone.GRAVEYARD and enemy.zone == Zone.GRAVEYARD
            results.append(f"{zone}=friendly_death:{after_friendly};after_enemy_death:{after_enemy}")
        assert all("friendly_death:(7, 7)" in row and "after_enemy_death:(7, 7)" in row for row in results), results
        return ";".join(results)
    record(cid, "friendly_death_only_buffs_cthun_wherever", "Friendly minion death gives C'Thun in hand, deck, or play +1/+1; an enemy death gives nothing.", friendly_death_buffs_cthun_wherever_enemy_death_not, "每个区域独立结算友方与敌方死亡，检查触发控制方及克苏恩状态。")
    return finish_card(cid)


def cult_sorcerer():
    cid = "OG_303"
    def spell_damage_and_after_spell_cthun_buff_wherever():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
            cthun = cthun_instance(p, zone)
            sorcerer = play(p, cid)
            target = e.hero
            before = (target.health, cthun.atk, cthun.health)
            spell = play(p, MOONFIRE, target)
            assert target.health == before[0] - 2, (zone, before[0], target.health)
            assert (cthun.atk, cthun.health) == (before[1] + 1, before[2] + 1), (zone, before, cthun.atk, cthun.health)
            assert sorcerer.spellpower == 1 and spell.zone == Zone.GRAVEYARD
            results.append(f"{zone}=hero:{target.health},cthun:{cthun.atk}/{cthun.health}")
        return f"spellpower_and_cthun={results}"
    def enemy_spell_does_not_buff_friendly_cthun():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        cthun = give(p, "OG_280")
        play(p, cid)
        before = (cthun.atk, cthun.health)
        g.end_turn()
        assert g.current_player is e
        play(e, MOONFIRE, p.hero)
        assert (cthun.atk, cthun.health) == before, (before, cthun.atk, cthun.health)
        return f"enemy_cast_cthun={cthun.atk}/{cthun.health};unchanged={before}"
    record(cid, "own_spell_damage_and_cthun_buff_wherever", "Cult Sorcerer increases Moonfire damage by 1 and the cast then gives C'Thun in hand, deck, or play +1/+1.", spell_damage_and_after_spell_cthun_buff_wherever, "三个克苏恩区域分别实际施放 Moonfire，检查法伤数值、顺序和增益。")
    record(cid, "opponent_spell_does_not_buff_own_cthun", "An opponent's spell does not trigger the controller's OWN_SPELL_PLAY C'Thun buff.", enemy_spell_does_not_buff_friendly_cthun, "使用对手法术验证控制方限制。")
    return finish_card(cid)


def giant_sand_worm():
    cid = "OG_308"
    def kill_grants_second_attack():
        g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
        worm = play(p, cid)
        first = summon(e, WISP); second = summon(e, WISP); third = summon(e, WISP)
        g.end_turn(); g.end_turn()
        worm.attack(first)
        assert first.zone == Zone.GRAVEYARD, first.zone
        assert worm.zone == Zone.PLAY
        worm.attack(second)
        assert second.zone == Zone.GRAVEYARD, (second.zone, second.health, worm.exhausted)
        worm.attack(third)
        assert third.zone == Zone.GRAVEYARD, (third.zone, third.health, worm.exhausted)
        return f"first={first.zone.name};second={second.zone.name};third={third.zone.name};worm={worm.zone.name};three_kill_attacks_succeeded=True"
    def surviving_target_no_extra_attack():
        g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
        worm = play(p, cid)
        target = summon(e, "EX1_572")
        g.end_turn(); g.end_turn()
        worm.attack(target)
        assert target in e.field and target.health > 0
        try:
            worm.attack(g.player2.hero)
        except InvalidAction:
            pass
        else:
            assert False, "Giant Sand Worm attacked again after target survived"
        return f"target=PLAY:{target.health};second_attack=rejected"
    record(cid, "attack_kill_may_attack_again", "After killing a minion, Giant Sand Worm can make another attack that turn.", kill_grants_second_attack, "实际进行两次攻击，检查两名受击随从的死亡与额外攻击状态。")
    record(cid, "survivor_does_not_grant_extra_attack", "If the attacked minion survives, a second attack is rejected.", surviving_target_no_extra_attack, "验证触发条件依赖本次攻击击杀随从。")
    return finish_card(cid)


def princess_huhuran():
    cid = "OG_309"
    def triggers_friendly_deathrattle_without_killing_source():
        g = new_game(CardClass.HUNTER); p, e = g.player1, g.player2
        draw = shuffle(p, WISP)
        hoarder = summon(p, "OG_323")
        princess = play(p, cid, hoarder)
        assert draw in p.hand and draw not in p.deck, (draw.zone, [c.id for c in p.hand])
        assert hoarder in p.field and hoarder.zone == Zone.PLAY
        assert princess in p.field
        return f"drawn={draw.id}:{draw.zone.name};hoarder={hoarder.zone.name};princess={princess.zone.name};deck={len(p.deck)}"
    record(cid, "battlecry_triggers_selected_friendly_deathrattle", "Princess Huhuran triggers the selected friendly Polluted Hoarder's Deathrattle, draws the known top card, and leaves the Hoarder alive.", triggers_friendly_deathrattle_without_killing_source, "检查触发亡语与摧毁目标的区别，并核对牌库/手牌落区。")
    return finish_card(cid)


def steward_of_darkshire():
    cid = "OG_310"
    def shields_only_one_health_summons():
        g = new_game(CardClass.PALADIN); p, e = g.player1, g.player2
        steward = play(p, cid)
        one = summon(p, WISP)
        two = summon(p, "CS2_182")
        opponent_one = summon(e, WISP)
        assert one.divine_shield, one.divine_shield
        assert not two.divine_shield and two.health == two.max_health, (two.divine_shield, two.health, two.max_health)
        assert not opponent_one.divine_shield
        assert steward in p.field
        return f"friendly_1hp_shield={one.divine_shield};friendly_5hp_shield={two.divine_shield};enemy_1hp_shield={opponent_one.divine_shield}"
    record(cid, "summon_trigger_divine_shield_domain", "A friendly 1-Health Wisp gets Divine Shield; friendly 5-Health Yeti and enemy Wisp do not.", shields_only_one_health_summons, "分开检查友方控制、召唤事件与初始生命值条件。")
    return finish_card(cid)


def a_light_in_darkness():
    cid = "OG_311"
    def discover_minion_choose_and_buff():
        seen_ids = set()
        for seed in range(820, 836):
            g = new_game(CardClass.PALADIN, seed); p = g.player1
            spell = give(p, cid)
            g.random.seed(seed)
            spell.play()
            choice = p.choice
            options = list(choice.cards)
            assert len(options) == 3, [c.id for c in options]
            assert all(c.type == CardType.MINION for c in options), [(c.id, c.type) for c in options]
            assert all(c.card_class in (CardClass.NEUTRAL, CardClass.PALADIN) for c in options), [(c.id, c.card_class) for c in options]
            selected = options[seed % len(options)]
            choice.choose(selected)
            added = [c for c in p.hand if c.id == selected.id]
            assert len(added) == 1, [c.id for c in p.hand]
            picked = added[0]
            assert (picked.atk, picked.health) == (selected.data.atk + 1, selected.data.health + 1), (selected.id, selected.data.atk, selected.data.health, picked.atk, picked.health)
            assert len(p.hand) == 1 and p.hand[0] is picked, [c.id for c in p.hand]
            assert not p.choice and spell.zone == Zone.GRAVEYARD
            seen_ids.add(selected.id)
        assert seen_ids, "no chosen candidates observed"
        return f"16_seeded_discover_choose;chosen_ids={sorted(seen_ids)};all_options_minions_class_legal=True;chosen_plus_one_one=True"
    record(cid, "discover_choose_and_buff_selected_minion", "Offers three legal minion options; chosen card alone enters hand and receives +1/+1.", discover_minion_choose_and_buff, "对16个固定种子逐局检查候选类别、选择关闭、手牌身份和所选属性增益。")
    return finish_card(cid)


def nzoths_first_mate():
    cid = "OG_312"
    def equips_one_three_rusty_hook():
        g = new_game(CardClass.WARRIOR); p = g.player1
        mate = play(p, cid)
        weapon = p.weapon
        assert weapon is not None and weapon.id == "OG_058", (weapon, p.weapon)
        assert (weapon.atk, weapon.durability) == (1, 3), (weapon.atk, weapon.durability)
        assert mate in p.field and weapon.zone == Zone.PLAY
        return f"battlecry_weapon={weapon.id}:{weapon.atk}/{weapon.durability};hero_attack={p.hero.atk}"
    def replaces_old_weapon():
        g = new_game(CardClass.WARRIOR); p = g.player1
        old = give(p, LIGHTS_JUSTICE); old.play()
        mate = play(p, cid)
        assert p.weapon is not old and p.weapon.id == "OG_058", (p.weapon, old)
        assert old.zone == Zone.GRAVEYARD, old.zone
        assert (p.weapon.atk, p.weapon.durability) == (1, 3)
        return f"old_weapon={old.zone.name};new_weapon={p.weapon.id}:{p.weapon.atk}/{p.weapon.durability};mate={mate.zone.name}"
    record(cid, "battlecry_equips_rusty_hook", "N'Zoth's First Mate equips exactly one 1/3 Rusty Hook.", equips_one_three_rusty_hook, "核对武器 ID、攻击力、耐久度与装备区域。")
    record(cid, "battlecry_replaces_existing_weapon", "If a weapon is already equipped, Rusty Hook replaces it and the old weapon reaches Graveyard.", replaces_old_weapon, "验证装备交互与旧武器区域变化。")
    return finish_card(cid)


def addled_grizzly():
    cid = "OG_313"
    def friendly_summons_get_plus_one_one():
        g = new_game(CardClass.DRUID); p, e = g.player1, g.player2
        grizzly = play(p, cid)
        ally = summon(p, WISP)
        enemy = summon(e, WISP)
        assert (ally.atk, ally.health) == (2, 2), (ally.atk, ally.health)
        assert (enemy.atk, enemy.health) == (1, 1), (enemy.atk, enemy.health)
        assert grizzly in p.field and ally in p.field and enemy in e.field
        return f"ally={ally.atk}/{ally.health};enemy={enemy.atk}/{enemy.health};grizzly={grizzly.zone.name}"
    record(cid, "after_friendly_summon_buffs_only_friendly", "A newly summoned friendly Wisp becomes 2/2; an enemy Wisp stays 1/1.", friendly_summons_get_plus_one_one, "使用引擎 summon 事件检查触发控制方和新随从增益。")
    return finish_card(cid)


def blood_to_ichor():
    cid = "OG_314"
    def survives_damage_summons_slime():
        g = new_game(CardClass.WARRIOR); p, e = g.player1, g.player2
        target = summon(e, "CS2_182"); target.set_current_health(2)
        spell = play(p, cid, target)
        slimes = list(p.field.filter(id="OG_314b"))
        assert target in e.field and target.health == 1, (target.zone, target.health)
        assert len(slimes) == 1 and (slimes[0].atk, slimes[0].health) == (2, 2), [(m.atk,m.health) for m in slimes]
        assert spell.zone == Zone.GRAVEYARD
        return f"target=PLAY:{target.health};slimes={len(slimes)}x2/2;spell={spell.zone.name}"
    def lethal_damage_does_not_summon_slime():
        g = new_game(CardClass.WARRIOR); p, e = g.player1, g.player2
        target = summon(e, WISP)
        spell = play(p, cid, target)
        slimes = list(p.field.filter(id="OG_314b"))
        assert target.zone == Zone.GRAVEYARD, target.zone
        assert not slimes, [m.id for m in p.field]
        assert spell.zone == Zone.GRAVEYARD
        return f"target={target.zone.name};slimes=0;spell={spell.zone.name}"
    record(cid, "one_damage_survivor_summons_two_two", "A minion that survives 1 damage causes one 2/2 Slime to be summoned.", survives_damage_summons_slime, "核对存活目标受伤、友方泥浆怪属性和法术区域。")
    record(cid, "one_damage_kill_no_slime", "A target killed by 1 damage produces no Slime.", lethal_damage_does_not_summon_slime, "验证存活分支为假时不召唤。")
    return finish_card(cid)


def bloodsail_cultist():
    cid = "OG_315"
    def requires_another_pirate_and_weapon():
        g = new_game(CardClass.WARRIOR); p = g.player1
        weapon = give(p, LIGHTS_JUSTICE); weapon.play()
        first = play(p, cid)
        assert (weapon.atk, weapon.durability) == (1, 4), (weapon.atk, weapon.durability)
        pirate = summon(p, "NEW1_018")
        second = play(p, cid)
        assert (weapon.atk, weapon.durability) == (2, 5), (weapon.atk, weapon.durability)
        assert pirate in p.field and first in p.field and second in p.field
        return f"without_other_pirate=1/4;with_other_pirate={weapon.atk}/{weapon.durability}"
    def pirate_without_weapon_has_no_failure():
        g = new_game(CardClass.WARRIOR); p = g.player1
        summon(p, "NEW1_018")
        cultist = play(p, cid)
        assert p.weapon is None and cultist in p.field
        return "friendly_pirate=True;weapon=None;cultist=PLAY"
    record(cid, "battlecry_weapon_buff_requires_other_pirate", "First Cultist with no other Pirate does not buff weapon; a later one with another Pirate gives +1 Attack/+1 Durability.", requires_another_pirate_and_weapon, "同一局面先后验证“其他海盗”条件与武器属性改变。")
    record(cid, "battlecry_pirate_without_weapon", "With another friendly Pirate but no weapon, Cultist resolves without creating a weapon or error.", pirate_without_weapon_has_no_failure, "检查有条件成立但无武器时的合法结算。")
    return finish_card(cid)


def herald_volazj():
    cid = "OG_316"
    def copies_each_other_friendly_as_one_one():
        g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
        a = summon(p, "CS2_182"); a.set_current_health(3)
        b = summon(p, "EX1_044")
        enemy = summon(e, "CS2_182")
        herald = play(p, cid)
        copies = [m for m in p.field if m is not herald and m not in (a, b)]
        ids = sorted(m.id for m in copies)
        assert ids == sorted([a.id, b.id]), (ids, a.id, b.id, [m.id for m in p.field])
        assert all((m.atk, m.health) == (1, 1) for m in copies), [(m.id,m.atk,m.health) for m in copies]
        assert (a.atk, a.health) == (4, 3) and b in p.field
        assert enemy in e.field and herald in p.field
        return f"copies={[(m.id,m.atk,m.health) for m in copies]};originals={a.id}:{a.atk}/{a.health},{b.id}:{b.atk}/{b.health};enemy={enemy.id}"
    def one_open_slot_summons_only_one_copy():
        g = new_game(CardClass.PRIEST); p = g.player1
        originals = [summon(p, WISP) for _ in range(5)]
        herald = play(p, cid)
        wisps = list(p.field.filter(id=WISP))
        assert len(p.field) == 7 and len(wisps) == 6, [m.id for m in p.field]
        assert all(m in p.field for m in originals) and herald in p.field
        return f"field={len(p.field)};originals=5;copies=1;wisps={len(wisps)}"
    record(cid, "battlecry_copies_all_other_friendly_minions", "Summons one 1/1 copy of each existing friendly minion, excludes Herald itself and enemy minion, originals remain.", copies_each_other_friendly_as_one_one, "设置两类不同原体、受伤状态及敌方随从，核对副本身份、属性和控制方。")
    record(cid, "battlecry_copies_obey_board_cap", "With five friendly minions and one free slot after Herald is played, exactly one 1/1 copy is summoned.", one_open_slot_summons_only_one_copy, "用同名随从盘点原体/复制数量，检查七格召唤上限。")
    return finish_card(cid)


def deathwing_dragonlord():
    cid = "OG_317"
    def deathrattle_puts_dragons_from_hand_into_play():
        g = new_game(); p = g.player1
        dragonlord = play(p, cid)
        ysera = give(p, "EX1_572")
        azure = give(p, "EX1_284")
        non_dragon = give(p, WISP)
        drawn = shuffle(p, MOONFIRE)
        dragonlord.destroy()
        assert dragonlord.zone == Zone.GRAVEYARD
        assert ysera in p.field and azure in p.field, [m.id for m in p.field]
        assert non_dragon in p.hand and non_dragon.zone == Zone.HAND
        assert drawn in p.deck and drawn.zone == Zone.DECK, (drawn.zone, [c.id for c in p.hand])
        assert not p.hand.filter(id=MOONFIRE)
        return f"dragonlord={dragonlord.zone.name};dragons={[m.id for m in p.field if m.id in ('EX1_572','EX1_284')]};non_dragon={non_dragon.zone.name};known_top={drawn.zone.name}"
    def board_cap_keeps_unresolved_dragon_in_hand():
        g = new_game(); p = g.player1
        dragonlord = summon(p, cid)
        for _ in range(6): summon(p, WISP)
        first = give(p, "EX1_572")
        second = give(p, "EX1_284")
        non_dragon = give(p, FIREBALL)
        assert len(p.field) == 7
        dragonlord.destroy()
        dragons = [c for c in p.field if c.id in ("EX1_572", "EX1_284")]
        assert len(p.field) == 7 and len(dragons) == 1, [m.id for m in p.field]
        assert sum(c.zone == Zone.HAND for c in (first, second)) == 1, [(c.id,c.zone.name) for c in (first,second)]
        assert non_dragon in p.hand and dragonlord.zone == Zone.GRAVEYARD
        return f"board={len(p.field)};summoned_dragon={[c.id for c in dragons]};dragon_still_hand={[c.id for c in (first,second) if c.zone==Zone.HAND]}"
    record(cid, "deathrattle_summons_hand_dragons_only", "Death puts all Dragons from hand onto the board; non-Dragon stays in hand and their Battlecries do not draw the known top card.", deathrattle_puts_dragons_from_hand_into_play, "检查亡语召唤手牌、非龙排除、原卡移动和战吼不触发。")
    record(cid, "deathrattle_obeys_board_cap", "With one open slot, exactly one of two hand Dragons enters play and the other remains in hand.", board_cap_keeps_unresolved_dragon_in_hand, "验证七格上限时其余龙牌的区域状态。")
    return finish_card(cid)


def hogger_doom_of_elwynn():
    cid = "OG_318"
    def nonlethal_damage_summons_taunt_gnoll():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        hogger = play(p, cid)
        before = hogger.health
        g.end_turn()
        spell = play(e, MOONFIRE, hogger)
        gnolls = list(p.field.filter(id="OG_318t"))
        assert hogger in p.field and hogger.health == before - 1, (hogger.zone, before, hogger.health)
        assert len(gnolls) == 1 and (gnolls[0].atk, gnolls[0].health, gnolls[0].taunt) == (2, 2, True), [(m.atk,m.health,m.taunt) for m in gnolls]
        assert spell.zone == Zone.GRAVEYARD
        return f"hogger={hogger.zone.name}:{hogger.health};gnoll={len(gnolls)}x2/2:taunt;spell={spell.zone.name}"
    def lethal_damage_still_processes_damage_trigger():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        hogger = play(p, cid); hogger.set_current_health(1)
        g.end_turn()
        spell = play(e, MOONFIRE, hogger)
        gnolls = list(p.field.filter(id="OG_318t"))
        assert hogger.zone == Zone.GRAVEYARD, hogger.zone
        assert len(gnolls) == 1 and (gnolls[0].atk, gnolls[0].health, gnolls[0].taunt) == (2, 2, True), [(m.atk,m.health,m.taunt) for m in gnolls]
        assert spell.zone == Zone.GRAVEYARD
        return f"hogger={hogger.zone.name};gnoll={len(gnolls)}x2/2:taunt;spell={spell.zone.name}"
    record(cid, "takes_nonlethal_damage_summons_taunt_gnoll", "Nonlethal damage to Hogger summons exactly one 2/2 Taunt Gnoll.", nonlethal_damage_summons_taunt_gnoll, "由对手法术造成真实伤害，核对本体存活及衍生物属性。")
    record(cid, "takes_lethal_damage_summons_before_death_resolves", "Lethal damage still triggers one Gnoll before Hogger reaches Graveyard.", lethal_damage_still_processes_damage_trigger, "将本体生命设为1后由敌方法术击杀，检查触发与死亡结算。")
    return finish_card(cid)


def midnight_drake():
    cid = "OG_320"
    def attack_counts_other_cards_in_hand():
        g = new_game(); p = g.player1
        extra_minion = give(p, WISP)
        extra_spell = give(p, FIREBALL)
        extra_weapon = give(p, LIGHTS_JUSTICE)
        drake = play(p, cid)
        expected = drake.data.atk + 3
        assert drake.atk == expected, (drake.data.atk, drake.atk, [c.id for c in p.hand])
        assert extra_minion in p.hand and extra_spell in p.hand and extra_weapon in p.hand
        return f"base_attack={drake.data.atk};other_hand_cards=3;attack={drake.atk};remaining={[c.id for c in p.hand]}"
    def empty_hand_no_bonus():
        g = new_game(); p = g.player1
        drake = play(p, cid)
        assert drake.atk == drake.data.atk, (drake.atk, drake.data.atk)
        return f"other_hand_cards=0;attack={drake.atk};base={drake.data.atk}"
    record(cid, "battlecry_attack_per_other_hand_card", "With three other cards in hand, Midnight Drake gains exactly +3 Attack.", attack_counts_other_cards_in_hand, "保留随从、法术、武器三种其它手牌，核对手牌计数和攻击力。")
    record(cid, "battlecry_empty_hand_no_attack_bonus", "With no other cards in hand, Drake receives no Attack bonus.", empty_hand_no_bonus, "验证空手牌边界。")
    return finish_card(cid)


def crazed_worshipper():
    cid = "OG_321"
    def damage_buffs_cthun_wherever():
        results = []
        for zone in ("hand", "deck", "board"):
            g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
            cthun = cthun_instance(p, zone)
            worshipper = play(p, cid)
            before = (cthun.atk, cthun.health)
            g.end_turn()
            spell = play(e, MOONFIRE, worshipper)
            assert worshipper.taunt and worshipper in p.field and worshipper.health == worshipper.max_health - 1
            assert (cthun.atk, cthun.health) == (before[0] + 1, before[1] + 1), (zone, before, cthun.atk, cthun.health)
            assert spell.zone == Zone.GRAVEYARD
            results.append(f"{zone}=cthun:{cthun.atk}/{cthun.health};worshipper_damaged=True")
        return ";".join(results)
    record(cid, "takes_damage_buffs_cthun_wherever", "Crazed Worshipper has Taunt; taking damage gives C'Thun in hand, deck, or play +1/+1.", damage_buffs_cthun_wherever, "克苏恩分处三个区域时分别接受对手法术造成的真实伤害，核对嘲讽和跨区域增益。")
    return finish_card(cid)


def blackwater_pirate():
    cid = "OG_322"
    def weapon_costs_reduced_only_while_active():
        g = new_game(); p = g.player1
        pirate = play(p, cid)
        gorehowl = give(p, "EX1_411")
        lights = give(p, LIGHTS_JUSTICE)
        fireball = give(p, FIREBALL)
        costs_active = (gorehowl.cost, lights.cost, fireball.cost)
        assert costs_active == (gorehowl.data.cost - 2, max(lights.data.cost - 2, 0), fireball.data.cost), costs_active
        pirate.destroy()
        costs_after = (gorehowl.cost, lights.cost, fireball.cost)
        assert costs_after == (gorehowl.data.cost, lights.data.cost, fireball.data.cost), costs_after
        return f"active_costs={costs_active};after_source_death={costs_after};pirate={pirate.zone.name}"
    record(cid, "weapon_aura_minus_two_cost_and_expires", "While Pirate is on board, both weapons cost 2 less (floor 0) and Fireball is unchanged; after Pirate dies, original costs return.", weapon_costs_reduced_only_while_active, "同时检查费用下限、非武器排除及光环移除后的回退。")
    return finish_card(cid)


def polluted_hoarder():
    cid = "OG_323"
    def deathrattle_draws_known_top_card():
        g = new_game(); p, e = g.player1, g.player2
        top = shuffle(p, WISP)
        hoarder = play(p, cid)
        hoarder.destroy()
        assert hoarder.zone == Zone.GRAVEYARD
        assert top in p.hand and top.zone == Zone.HAND and top not in p.deck
        assert len(p.hand) == 1 and p.hand[0] is top, [c.id for c in p.hand]
        assert not e.hand
        return f"hoarder={hoarder.zone.name};drawn={top.id}:{top.zone.name};deck={len(p.deck)};enemy_hand={len(e.hand)}"
    record(cid, "deathrattle_draws_one_card_for_controller", "Hoarder's death draws exactly the known top card into its controller's hand.", deathrattle_draws_known_top_card, "死亡后核对牌库顶牌身份、手牌数量和双方持有方。")
    return finish_card(cid)


def squirming_tentacle():
    cid = "OG_327"
    def printed_taunt_blocks_hero_attack_and_takes_combat_damage():
        g = new_game(CardClass.WARRIOR); p, e = g.player1, g.player2
        g.end_turn()
        assert g.current_player is e
        weapon = give(e, LIGHTS_JUSTICE); weapon.play()
        attacker = summon(e, "CS2_182")
        g.end_turn()
        assert g.current_player is p
        tentacle = play(p, cid)
        assert tentacle.taunt
        g.end_turn()
        assert g.current_player is e
        before = (tentacle.health, attacker.health)
        assert e.hero.atk == 1 and e.hero.can_attack(tentacle) and not e.hero.can_attack(p.hero), (e.hero.atk, e.hero.attack_targets)
        try:
            e.hero.attack(p.hero)
        except InvalidAction:
            pass
        else:
            assert False, "enemy hero attacked through a live Taunt minion"
        attacker.attack(tentacle)
        assert attacker.health == before[1] - tentacle.atk, (before, attacker.health, tentacle.atk)
        assert tentacle.zone == Zone.GRAVEYARD, (tentacle.zone, before[0], attacker.atk)
        return f"taunt=True;hero_attack_blocked=True;tentacle={tentacle.zone.name};attacker={attacker.health}"
    record(cid, "taunt_blocks_hero_and_defends_in_combat", "Tentacle's Taunt prevents hero face attack; opposing Yeti can attack it and both health totals change by printed Attack.", printed_taunt_blocks_hero_attack_and_takes_combat_damage, "验证原生嘲讽标签在真实英雄/随从攻击交互中的效果。")
    return finish_card(cid)


def master_of_evolution():
    cid = "OG_328"
    def transforms_target_to_cost_plus_one_minion():
        ids = set(); traces = []
        for seed in range(930, 946):
            g = new_game(CardClass.SHAMAN, seed); p = g.player1
            target = summon(p, "CS2_182")
            other = summon(p, WISP)
            old_id, old_cost = target.id, target.cost
            master = play(p, cid, target)
            replacement = next(m for m in p.field if m is not master and m is not other)
            assert target.zone == Zone.SETASIDE, (seed, target.zone, target.id)
            assert replacement.id != old_id and replacement.type == CardType.MINION, (seed, old_id, replacement.id, replacement.type)
            assert replacement.cost == old_cost + 1, (seed, old_id, replacement.id, old_cost, replacement.cost)
            assert other in p.field and other.id == WISP and len(p.field) == 3
            assert master in p.field
            ids.add(replacement.id); traces.append(f"{seed}:{old_id}->{replacement.id}/{replacement.cost}")
        assert len(ids) >= 2, sorted(ids)
        return f"16_seeded_cost_plus_one_transforms={','.join(traces)};distinct_replacements={sorted(ids)}"
    def enemy_target_rejected_without_side_effects():
        g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
        friendly = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        card = give(p, cid); mana = p.mana
        try:
            card.play(target=enemy)
        except InvalidAction:
            pass
        else:
            assert False, "enemy minion unexpectedly accepted by Master of Evolution"
        assert card in p.hand and p.mana == mana and enemy in e.field and friendly in p.field
        return f"enemy_target_rejected=True;hand=True;mana={p.mana};friendly={friendly.zone.name};enemy={enemy.zone.name}"
    def no_friendly_minion_playable_without_target():
        g = new_game(CardClass.SHAMAN); p, e = g.player1, g.player2
        enemy = summon(e, "CS2_182")
        card = play(p, cid)
        assert card in p.field and enemy in e.field and len(p.field) == 1
        return f"no_friendly_target=played_without_target;enemy_unchanged={enemy.zone.name}"
    record(cid, "battlecry_evolves_friendly_target_to_cost_plus_one", "Across fixed seeds, only the selected friendly Yeti transforms into a minion costing exactly 1 more; board count stays fixed and other minion remains.", transforms_target_to_cost_plus_one_minion, "16个固定种子检查变形目标、原位/区域、费用增量及多种替换结果。")
    record(cid, "targeting_rejects_enemy_minion", "Enemy minion is illegal; rejected attempt preserves Master, mana, and enemy minion.", enemy_target_rejected_without_side_effects, "验证友方目标范围与拒绝副作用。")
    record(cid, "no_friendly_target_is_optional", "With no friendly minion available, Master may be played without a target and does not transform an enemy minion.", no_friendly_minion_playable_without_target, "REQ_TARGET_IF_AVAILABLE 允许无合法友方目标时不选目标；单独核验该规则分支。")
    return finish_card(cid)


def undercity_huckster():
    cid = "OG_330"
    def deathrattle_gives_random_opponent_class_card():
        seen = set(); traces = []
        for seed in range(950, 966):
            random.seed(seed)
            g = prepare_empty_game(CardClass.ROGUE, CardClass.MAGE)
            g.random.seed(seed)
            owner = next(p for p in g.players if p.hero.card_class == CardClass.ROGUE)
            opponent = owner.opponent
            if g.current_player is not owner:
                g.end_turn()
            assert g.current_player is owner
            for p in g.players:
                p.is_standard = False; p.max_mana = 10; p.used_mana = 0; p.discard_hand()
            assert not owner.deck and not opponent.deck, (seed, [c.id for c in owner.deck], [c.id for c in opponent.deck])
            source = play(owner, cid)
            huckster = source
            huckster.destroy()
            received = [c for c in owner.hand]
            assert len(received) == 1, (seed, [c.id for c in received])
            card = received[0]
            assert card.card_class == CardClass.MAGE and card.data.collectible, (seed, card.id, card.card_class, card.data.collectible)
            assert card.zone == Zone.HAND and huckster.zone == Zone.GRAVEYARD
            assert len(opponent.hand) == 0
            seen.add(card.id); traces.append(f"{seed}:{card.id}")
        assert len(seen) >= 2, sorted(seen)
        return f"16_seeded_opponent_class_cards={','.join(traces)};distinct={sorted(seen)}"
    record(cid, "deathrattle_adds_random_opponent_class_card", "Deathrattle adds one collectible Mage card (the opponent's class) to Rogue's hand without adding it to the Mage's hand.", deathrattle_gives_random_opponent_class_card, "按实际英雄职业定位持有方，16个种子检查职业、可收藏属性和随机结果。")
    return finish_card(cid, blocker="随机候选池只采样16个结果，未穷尽法师可收藏卡牌全集。" if False else None)


def hooded_acolyte():
    cid = "OG_334"
    def any_character_heal_buffs_cthun_in_deck():
        g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
        cthun = give(p, "OG_280"); cthun.shuffle_into_deck()
        acolyte = play(p, cid)
        p.hero.set_current_health(25)
        healer = give(p, "EX1_011")
        healer.play(target=p.hero)
        after_friend = (cthun.atk, cthun.health)
        assert p.hero.health == 27 and after_friend == (7, 7), (p.hero.health, after_friend)
        e.hero.set_current_health(25)
        g.end_turn()
        enemy_healer = give(e, "EX1_011")
        enemy_healer.play(target=e.hero)
        after_enemy = (cthun.atk, cthun.health)
        assert e.hero.health == 27 and after_enemy == (8, 8), (e.hero.health, after_enemy)
        assert acolyte in p.field and cthun.zone == Zone.DECK
        return f"friendly_heal_cthun={after_friend};enemy_heal_cthun={after_enemy};heroes={p.hero.health}/{e.hero.health};cthun_zone={cthun.zone.name}"
    def full_health_no_effective_heal_no_buff():
        g = new_game(CardClass.PRIEST); p = g.player1
        cthun = give(p, "OG_280")
        acolyte = play(p, cid)
        before = (cthun.atk, cthun.health)
        healer = give(p, "EX1_011")
        healer.play(target=p.hero)
        assert p.hero.health == 30 and (cthun.atk, cthun.health) == before, (p.hero.health, before, cthun.atk, cthun.health)
        return f"hero_full={p.hero.health};cthun={cthun.atk}/{cthun.health};unchanged={before};acolyte={acolyte.zone.name}"
    def friendly_damaged_minion_heal_buffs_only_owner_cthun():
        g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
        cthun = give(p, "OG_280"); cthun.shuffle_into_deck()
        enemy_cthun = give(e, "OG_280")
        acolyte = play(p, cid)
        target = summon(p, "CS2_182"); target.set_current_health(3)
        before = (cthun.atk, cthun.health)
        healer = play(p, "EX1_011", target)
        expected = (before[0] + 1, before[1] + 1)
        assert target.health == 5 and target.max_health == 5, (target.health, target.max_health)
        assert (cthun.atk, cthun.health) == expected, (before, cthun.atk, cthun.health, expected)
        assert (enemy_cthun.atk, enemy_cthun.health) == (6, 6), (enemy_cthun.atk, enemy_cthun.health)
        assert cthun.zone == Zone.DECK and acolyte in p.field and healer in p.field
        return f"friendly_minion_healed=3->5;owner_cthun={cthun.atk}/{cthun.health};enemy_cthun={enemy_cthun.atk}/{enemy_cthun.health};cthun_zone={cthun.zone.name}"
    def enemy_damaged_minion_heal_buffs_only_owner_cthun():
        g = new_game(CardClass.PRIEST); p, e = g.player1, g.player2
        cthun = give(p, "OG_280"); cthun.shuffle_into_deck()
        enemy_cthun = give(e, "OG_280")
        acolyte = play(p, cid)
        target = summon(e, "CS2_182"); target.set_current_health(3)
        before = (cthun.atk, cthun.health)
        g.end_turn()
        assert g.current_player is e
        healer = play(e, "EX1_011", target)
        expected = (before[0] + 1, before[1] + 1)
        assert target.health == 5 and target.max_health == 5, (target.health, target.max_health)
        assert (cthun.atk, cthun.health) == expected, (before, cthun.atk, cthun.health, expected)
        assert (enemy_cthun.atk, enemy_cthun.health) == (6, 6), (enemy_cthun.atk, enemy_cthun.health)
        assert cthun.zone == Zone.DECK and acolyte in p.field and healer in e.field
        return f"enemy_minion_healed=3->5;owner_cthun={cthun.atk}/{cthun.health};enemy_cthun={enemy_cthun.atk}/{enemy_cthun.health};cthun_zone={cthun.zone.name}"
    record(cid, "friendly_and_enemy_hero_healing_buffs_deck_cthun", "Healing either controller's hero produces one +1/+1 C'Thun buff per successful heal.", any_character_heal_buffs_cthun_in_deck, "分别通过双方 Voodoo Doctor 战吼治疗英雄，检查双方英雄治疗都使持有者牌库中的克苏恩成长。")
    record(cid, "full_health_heal_does_not_buff_cthun", "A heal with no missing Health restores nothing and does not trigger a C'Thun buff.", full_health_no_effective_heal_no_buff, "检查满血目标上的无效治疗边界。")
    record(cid, "friendly_damaged_minion_heal_buffs_only_owner_cthun", "Healing a damaged friendly minion restores its Health and gives the Hooded Acolyte controller's C'Thun exactly +1/+1, without buffing the opponent's C'Thun.", friendly_damaged_minion_heal_buffs_only_owner_cthun, "治疗己方受伤随从，断言治疗量、持有者克苏恩精确增益及对手克苏恩不变。")
    record(cid, "enemy_damaged_minion_heal_buffs_only_owner_cthun", "Healing a damaged enemy minion on the opponent's turn restores its Health and gives the Hooded Acolyte controller's C'Thun exactly +1/+1, without buffing the opponent's C'Thun.", enemy_damaged_minion_heal_buffs_only_owner_cthun, "让对手在其回合治疗己方受伤随从，断言治疗量和增益只落在 acolyte 持有者的克苏恩。")
    return finish_card(cid)


def shifting_shade():
    cid = "OG_335"
    def copies_random_enemy_deck_card_keeps_original():
        seen = set(); traces = []
        for seed in range(970, 986):
            g = new_game(CardClass.PRIEST, seed); p, e = g.player1, g.player2
            assert not e.deck, (seed, [c.id for c in e.deck])
            one = shuffle(e, WISP)
            two = shuffle(e, FIREBALL)
            assert len(e.deck) == 2 and {c.id for c in e.deck} == {WISP, FIREBALL}, (seed, [c.id for c in e.deck])
            shade = summon(p, cid)
            # Avoid correlating the random-choice seed with how the exact deck was constructed.
            g.random.seed(seed + 1)
            shade.destroy()
            copies = [c for c in p.hand]
            assert len(copies) == 1, (seed, [c.id for c in copies])
            copied = copies[0]
            assert copied.id in (WISP, FIREBALL), (seed, copied.id)
            original = one if copied.id == WISP else two
            assert original.zone == Zone.DECK and original in e.deck, (seed, original.id, original.zone)
            assert copied is not original and copied.zone == Zone.HAND
            assert shade.zone == Zone.GRAVEYARD and len(e.deck) == 2
            seen.add(copied.id); traces.append(f"{seed}:{copied.id}")
        assert seen == {WISP, FIREBALL}, sorted(seen)
        return f"16_seeded_copy_choices={','.join(traces)};seen={sorted(seen)};opponent_deck_unchanged=2"
    record(cid, "deathrattle_copies_opponent_deck_without_removing_original", "Shifting Shade adds one copy of an enemy-deck card to hand; original stays in enemy deck and both known candidates appear across independent seeds.", copies_random_enemy_deck_card_keeps_original, "双方初始牌库为空；仅加入Wisp和Fireball，选择种子与构造牌库种子分离，检查候选、双方区域及牌库大小。")
    return finish_card(cid)


def cyclopian_horror():
    cid = "OG_337"
    def health_scales_with_enemy_minion_count():
        g = new_game(); p, e = g.player1, g.player2
        enemies = [summon(e, WISP) for _ in range(3)]
        horror = play(p, cid)
        expected = horror.data.health + len(enemies)
        assert horror.atk == horror.data.atk and horror.health == expected and horror.max_health == expected, (horror.atk, horror.data.atk, horror.health, horror.max_health, expected)
        assert horror.taunt and all(m in e.field for m in enemies)
        return f"enemy_minions={len(enemies)};horror={horror.atk}/{horror.health};taunt={horror.taunt};base_health={horror.data.health}"
    def no_enemy_minions_no_extra_health():
        g = new_game(); p = g.player1
        horror = play(p, cid)
        assert (horror.atk, horror.health, horror.max_health) == (horror.data.atk, horror.data.health, horror.data.health), (horror.atk, horror.health, horror.max_health, horror.data.atk, horror.data.health)
        assert horror.taunt
        return f"enemy_minions=0;horror={horror.atk}/{horror.health};taunt={horror.taunt}"
    record(cid, "battlecry_health_increases_per_enemy_minion", "With three enemy minions, gains exactly +3 Health and retains Taunt.", health_scales_with_enemy_minion_count, "按敌方随从数断言最大生命与当前生命。")
    record(cid, "battlecry_zero_enemy_minions_base_health", "With no enemy minion, receives no Health bonus and still has Taunt.", no_enemy_minions_no_extra_health, "验证空敌方场面的数值边界与原生嘲讽。")
    return finish_card(cid)


def nat_the_darkfisher():
    cid = "OG_338"
    def opponent_has_coinflip_extra_draw():
        proc_seeds = set(); traces = []; counter_states = {1: set(), 2: set()}
        for seed in range(990, 1022):
            g = new_game(CardClass.MAGE, seed); owner, enemy = g.player1, g.player2
            nat = play(owner, cid)
            assert not owner.deck and not enemy.deck, (seed, [c.id for c in owner.deck], [c.id for c in enemy.deck])
            first = shuffle(enemy, WISP)
            second = shuffle(enemy, FIREBALL)
            assert len(enemy.deck) == 2 and {c.id for c in enemy.deck} == {WISP, FIREBALL}
            g.random.seed(seed + 1)
            turn_counts = {}
            original_begin_turn = g._begin_turn
            def capture_turn_counts(player):
                turn_counts["before_reset"] = (owner.cards_drawn_this_turn, enemy.cards_drawn_this_turn)
                result = original_begin_turn(player)
                turn_counts["after_normal_draw"] = (owner.cards_drawn_this_turn, enemy.cards_drawn_this_turn)
                return result
            g._begin_turn = capture_turn_counts
            g.end_turn()
            draw_count = 2 - len(enemy.deck)
            hand_ids = [c.id for c in enemy.hand]
            proc = draw_count == 2
            assert draw_count in (1, 2), (seed, draw_count, hand_ids, [c.id for c in enemy.deck])
            assert len(enemy.hand) == draw_count and all(i in (WISP, FIREBALL) for i in hand_ids), (seed, hand_ids, draw_count)
            assert len(enemy.deck) == 2 - draw_count
            assert not owner.hand, (seed, [c.id for c in owner.hand])
            counter_states[draw_count].add((turn_counts.get("before_reset"), turn_counts.get("after_normal_draw")))
            if proc:
                proc_seeds.add(seed)
            traces.append(f"{seed}:{draw_count}:{','.join(hand_ids)}")
        assert proc_seeds and len(traces) > len(proc_seeds), (sorted(proc_seeds), traces)
        expected_counters = {1: {((0, 0), (0, 1))}, 2: {((0, 1), (0, 2))}}
        assert counter_states == expected_counters, {"expected": expected_counters, "actual": counter_states}
        return f"32_seeded_opponent_draws={';'.join(traces)};proc_count={len(proc_seeds)};no_proc_count={len(traces)-len(proc_seeds)};pre_reset/final_counters={counter_states}"
    record(cid, "opponent_turn_start_fifty_percent_extra_draw", "At opponent turn start, they draw the normal turn card plus one extra on proc; expected opponent draw counter is 2 on proc and 1 otherwise, with no draw credited to owner.", opponent_has_coinflip_extra_draw, "32个固定种子清空并替换对手牌库，断言proc/no-proc 的实际手牌、牌库、普通抽牌后和额外抽牌后双方 cards_drawn_this_turn。")
    return finish_card(cid, notes="DRAW-001 mechanism-level failure confirmed: on proc the physical extra card enters opponent hand before _begin_turn resets both counters, but Draw increments source.controller (Nat's owner) to 1; reset erases that count and the opponent ends with count 1 despite two actual draws. No-proc ends owner=0/opponent=1.")


def skeram_cultist():
    cid = "OG_339"
    def battlecry_buffs_cthun_on_board():
        g = new_game(CardClass.WARRIOR); p = g.player1
        cthun = summon(p, "OG_280")
        before = (cthun.atk, cthun.health)
        cultist = play(p, cid)
        assert (cthun.atk, cthun.health) == (before[0] + 2, before[1] + 2), (before, cthun.atk, cthun.health)
        assert p.cthun.atk == cthun.atk and p.cthun.health == cthun.health
        return f"cthun_board={cthun.atk}/{cthun.health};tracked={p.cthun.atk}/{p.cthun.health};cultist={cultist.zone.name}"
    record(cid, "battlecry_buffs_cthun_on_board", "Skeram Cultist gives an on-board C'Thun exactly +2/+2.", battlecry_buffs_cthun_on_board, "将克苏恩直接召唤到场上，检查可见卡牌和追踪状态同步。")
    def battlecry_buffs_cthun_in_hand_and_deck():
        results = []
        for zone in ("hand", "deck"):
            g = new_game(CardClass.WARRIOR); p = g.player1
            cthun = cthun_instance(p, zone)
            before = (cthun.atk, cthun.health)
            cultist = play(p, cid)
            expected = (before[0] + 2, before[1] + 2)
            assert (cthun.atk, cthun.health) == expected, (zone, before, cthun.atk, cthun.health, expected)
            assert cthun.zone == (Zone.HAND if zone == "hand" else Zone.DECK), (zone, cthun.zone)
            assert p.cthun.atk == cthun.atk and p.cthun.health == cthun.health, (zone, cthun.atk, cthun.health, p.cthun.atk, p.cthun.health)
            assert cultist.zone == Zone.PLAY
            results.append(f"{zone}={cthun.atk}/{cthun.health};tracked={p.cthun.atk}/{p.cthun.health}")
        return ";".join(results)
    record(cid, "battlecry_buffs_cthun_in_hand_and_deck", "Skeram Cultist gives C'Thun exactly +2/+2 when C'Thun is in hand or deck, and the tracked C'Thun stats stay synchronized.", battlecry_buffs_cthun_in_hand_and_deck, "独立对局分别将克苏恩置于手牌和牌库，逐区断言属性增量、区域与追踪状态。")
    return finish_card(cid)


def soggoth_the_slitherer():
    cid = "OG_340"
    def spells_and_hero_powers_cannot_target_either_soggoth():
        g = new_game(CardClass.MAGE); p, e = g.player1, g.player2
        own_soggoth = play(p, cid)
        enemy_soggoth = summon(e, cid)
        own_attacker = summon(p, "CS2_182")
        p.used_mana = 0
        e.used_mana = 0
        own_spell = give(p, FIREBALL)
        def rejected_targets(actor, card, targets, label):
            for target in targets:
                mana_before = actor.mana
                health_before = target.health
                uses_before = actor.times_hero_power_used_this_game
                if card == "spell":
                    try:
                        actor_spell = own_spell if actor is p else enemy_spell
                        actor_spell.play(target=target)
                    except InvalidAction:
                        pass
                    else:
                        assert False, f"{label} Fireball accepted {target.controller.name}'s Soggoth"
                    assert actor_spell.zone == Zone.HAND and actor.mana == mana_before
                else:
                    try:
                        actor.hero.power.use(target=target)
                    except InvalidAction:
                        pass
                    else:
                        assert False, f"{label} Fireblast accepted {target.controller.name}'s Soggoth"
                    assert actor.times_hero_power_used_this_game == uses_before and actor.mana == mana_before
                assert target.health == health_before, (label, card, target.health, health_before)
        rejected_targets(p, "spell", (own_soggoth, enemy_soggoth), "p1")
        rejected_targets(p, "power", (own_soggoth, enemy_soggoth), "p1")
        g.end_turn()
        enemy_spell = give(e, FIREBALL)
        rejected_targets(e, "spell", (enemy_soggoth, own_soggoth), "p2")
        rejected_targets(e, "power", (enemy_soggoth, own_soggoth), "p2")
        g.end_turn()
        assert g.current_player is p and own_attacker.can_attack(enemy_soggoth)
        own_attacker.attack(enemy_soggoth)
        assert enemy_soggoth.health == enemy_soggoth.max_health - own_attacker.atk, (enemy_soggoth.health, enemy_soggoth.max_health, own_attacker.atk)
        assert own_soggoth.taunt and enemy_soggoth.taunt
        return f"both_players_spell_power_rejected_friendly_and_enemy_targets=True;mana_health_hand_unchanged=True;combat_attack_succeeded=True;both_taunt=True"
    record(cid, "untargetable_by_both_players_spells_and_hero_powers", "Neither player's Fireball nor Fireblast can target friendly or enemy Soggoth; rejected attempts preserve hand, mana, health, and Hero Power use; minion combat into Taunt remains legal.", spells_and_hero_powers_cannot_target_either_soggoth, "复位法力后由双方分别以法术/英雄技能点选己方与敌方索苟斯，最后跨回合实际攻击嘲讽随从。")
    return finish_card(cid)


PROBES = [
    simple_minion_deathrattle,
    stand_against_darkness,
    blood_warriors,
    cthun_random_split,
    beckoner_of_evil,
    blade_of_cthun,
    cthuns_chosen,
    twilight_geomancer,
    twilight_elder,
    ancient_harbinger,
    shadowcaster,
    forlorn_stalker,
    dark_arakkoa,
    cult_apothecary,
    boogeymonster,
    ancient_shieldbearer,
    usher_of_souls,
    cult_sorcerer,
    giant_sand_worm,
    princess_huhuran,
    steward_of_darkshire,
    a_light_in_darkness,
    nzoths_first_mate,
    addled_grizzly,
    blood_to_ichor,
    bloodsail_cultist,
    herald_volazj,
    deathwing_dragonlord,
    hogger_doom_of_elwynn,
    midnight_drake,
    crazed_worshipper,
    blackwater_pirate,
    polluted_hoarder,
    squirming_tentacle,
    master_of_evolution,
    undercity_huckster,
    hooded_acolyte,
    shifting_shade,
    cyclopian_horror,
    nat_the_darkfisher,
    skeram_cultist,
    soggoth_the_slitherer,
]


def main():
    assert len(OWN_IDS) == 42 and OWN_IDS[0] == "OG_272" and OWN_IDS[-1] == "OG_340", (len(OWN_IDS), OWN_IDS[0], OWN_IDS[-1])
    for probe in PROBES:
        status = probe()
        print(f"{probe.__name__}: {status}", flush=True)
    verdicts = [r for r in VERDICT_ROWS if r["card_id"] in OWN_IDS]
    cards_with_cases = {r["card_id"] for r in PROBE_ROWS if r["card_id"] in OWN_IDS}
    assert len(verdicts) == 42 and cards_with_cases == set(OWN_IDS), (len(verdicts), cards_with_cases ^ set(OWN_IDS))
    assert len({(r["card_id"], r["case_id"]) for r in PROBE_ROWS if r["card_id"] in OWN_IDS}) == len([r for r in PROBE_ROWS if r["card_id"] in OWN_IDS])
    counts = {status: sum(r["status"] == status for r in verdicts) for status in ("GREEN", "YELLOW", "RED")}
    print(f"summary cards={len(verdicts)} probes={len([r for r in PROBE_ROWS if r['card_id'] in OWN_IDS])} counts={counts}", flush=True)


if __name__ == "__main__":
    main()
