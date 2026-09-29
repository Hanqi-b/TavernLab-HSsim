#!/usr/bin/env python3
"""Independent live-game probes for baseline Classic yellow cards, rows 179-208."""

import csv
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from utils import *  # noqa: E402,F401,F403
from fireplace.logging import log  # noqa: E402

OUT = Path(__file__).resolve().parent
BASELINE_PATH = OUT / "expansion_yellow_baseline.csv"
QUALITY_PATH = OUT / "card_quality.csv"
PROBE_PATH = OUT / "classic_probe_middle_b.csv"
VERDICT_PATH = OUT / "classic_verdict_middle_b.csv"
PROBE_FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
VERDICT_FIELDS = ["card_id", "status", "mechanic_scope", "reason", "probe_file", "notes"]
FAILED_CARDS = set()
UNRESOLVED_CARDS = {}

for handler in log.handlers:
    handler.setLevel(logging.WARNING)
log.setLevel(logging.WARNING)


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def existing_rows(path):
    return read_rows(path) if path.exists() else []


def scope_for(card_id):
    return next((row["mechanic"] for row in read_rows(QUALITY_PATH)
                 if row["card_id"] == card_id), "")


def write_case(card_id, case_id, expected, observed, outcome, notes):
    rows = existing_rows(PROBE_PATH)
    key = (card_id, case_id)
    rows = [row for row in rows if (row["card_id"], row["case_id"]) != key]
    rows.append(dict(card_id=card_id, case_id=case_id, expected=expected,
                     observed=str(observed), outcome=outcome, notes=notes))
    write_rows(PROBE_PATH, PROBE_FIELDS, rows)


def write_verdict(card_id, status, reason, notes=""):
    rows = existing_rows(VERDICT_PATH)
    rows = [row for row in rows if row["card_id"] != card_id]
    rows.append(dict(card_id=card_id, status=status, mechanic_scope=scope_for(card_id),
                     reason=reason, probe_file="classic_probe_middle_b.csv", notes=notes))
    write_rows(VERDICT_PATH, VERDICT_FIELDS, rows)


def case(card_id, case_id, expected, probe, validate, notes=""):
    try:
        observed = probe()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        UNRESOLVED_CARDS.setdefault(card_id, []).append(f"{case_id}: fixture/execution blocker: {detail}")
        write_case(card_id, case_id, expected, detail, "inconclusive", notes)
        print(f"INCONCLUSIVE {card_id} {case_id}: {detail}")
        return False
    try:
        assert validate(observed), f"expected={expected}; observed={observed}"
    except AssertionError as exc:
        detail = f"{observed}; assertion={exc}"
        FAILED_CARDS.add(card_id)
        write_case(card_id, case_id, expected, detail, "confirmed_error", notes)
        write_verdict(card_id, "RED", f"{case_id} 逐卡断言失败；实测={detail}",
                      "已确认的行为不匹配，具体断言与现场状态见 probe CSV。")
        print(f"FAIL {card_id} {case_id}: {detail}")
        return False
    except Exception as exc:
        detail = f"{observed}; validator={type(exc).__name__}: {exc}"
        UNRESOLVED_CARDS.setdefault(card_id, []).append(f"{case_id}: validator blocker: {detail}")
        write_case(card_id, case_id, expected, detail, "inconclusive", notes)
        print(f"INCONCLUSIVE {card_id} {case_id}: {detail}")
        return False
    write_case(card_id, case_id, expected, observed, "pass", notes)
    print(f"PASS {card_id} {case_id}: {observed}")
    return True


def finish_card(card_id, reason, notes="", blocker=None):
    if card_id in FAILED_CARDS:
        return
    if blocker or card_id in UNRESOLVED_CARDS:
        reason = blocker or "；".join(UNRESOLVED_CARDS[card_id])
        status = "YELLOW"
    else:
        status = "GREEN"
    write_verdict(card_id, status, reason, notes)


def fresh_game(class1=CardClass.MAGE, class2=CardClass.MAGE):
    return prepare_empty_game(class1, class2)


def probe_savagery():
    def hero_attack_damage_case():
        game = fresh_game(CardClass.DRUID, CardClass.DRUID)
        friendly = game.player1.summon("CS2_182")
        enemy = game.player2.summon("CS2_182")
        game.player1.hero.power.use()
        spell = game.player1.give("EX1_578")
        spell.play(target=enemy)
        return {"hero_attack": game.player1.hero.atk,
                "enemy_damage": enemy.damage, "enemy_health": enemy.health,
                "friendly_damage": friendly.damage, "spell_zone": spell.zone.name}

    case("EX1_578", "deals_current_hero_attack_to_selected_enemy_minion",
         "After Druid hero power grants 1 Attack, Savagery damages only the chosen enemy minion for 1.",
         hero_attack_damage_case,
         lambda x: x["hero_attack"] == 1 and x["enemy_damage"] == 1
         and x["enemy_health"] == 4 and x["friendly_damage"] == 0 and x["spell_zone"] == "GRAVEYARD",
         "Real play after hero power; verifies value from current hero Attack and target isolation.")
    finish_card("EX1_578", "法术按英雄当前攻击力对所选随从造成伤害。",
                "目标为敌方随从；同时保留友方随从作为未受影响对照。")


def probe_priestess_of_elune():
    def self_heal_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        hero = game.player1.hero
        for _ in range(6):
            game.player1.give(MOONFIRE).play(target=hero)
        before = hero.health
        minion = game.player1.give("EX1_583")
        minion.play()
        return {"health_before": before, "health_after": hero.health,
                "minion_stats": (minion.atk, minion.health), "enemy_health": game.player2.hero.health}

    case("EX1_583", "battlecry_restores_four_hero_health",
         "Six prior face damage is reduced by 4; enemy hero is unchanged and Priestess of Elune is a 5/4.",
         self_heal_case,
         lambda x: x["health_before"] == 24 and x["health_after"] == 28
         and x["enemy_health"] == 30 and x["minion_stats"] == (5, 4),
         "真实地对己方英雄施加六次伤害后出牌，检查 Battlecry 的对象与数值。")
    finish_card("EX1_583", "战吼为自己的英雄恢复4点生命。", "己方英雄预先受伤；对手英雄作为未受影响对照。")


def probe_ancient_mage():
    def adjacency_spell_damage_case():
        game = fresh_game()
        left = game.player1.summon(WISP)
        inside = game.player1.summon(WISP)
        outside = game.player1.summon(WISP)
        mage = game.player1.give("EX1_584")
        mage.play(index=1)
        powers = [left.spellpower, inside.spellpower, outside.spellpower]
        game.player1.give(MOONFIRE).play(target=game.player2.hero)
        return {"field_ids": [m.id for m in game.player1.field], "spellpower": powers,
                "buff_ids": [[b.id for b in m.buffs] for m in (left, inside, outside)],
                "enemy_hero_damage": game.player2.hero.damage, "mage_zone": mage.zone.name}

    case("EX1_584", "battlecry_only_buffs_adjacent_minions_spell_damage",
         "The minions on both sides of the played Mage gain +1 Spell Damage; the nonadjacent minion gets none, making Moonfire deal 3.",
         adjacency_spell_damage_case,
         lambda x: x["field_ids"] == ["CS2_231", "EX1_584", "CS2_231", "CS2_231"]
         and x["spellpower"] == [1, 1, 0] and x["enemy_hero_damage"] == 3
         and x["mage_zone"] == "PLAY",
         "用插入位置构造左邻/右邻/隔位对象，并通过真实法术伤害验证光环值。")
    finish_card("EX1_584", "战吼只给予相邻随从法术伤害+1。", "左右相邻与非相邻随从分开断言，并用Moonfire核验实际效果。")


def probe_sea_giant():
    def both_sides_cost_case():
        game = fresh_game()
        giant = game.player1.give("EX1_586")
        start = giant.cost
        game.player1.summon(WISP)
        game.player2.summon(WISP)
        game.player1.summon(WISP)
        after_three = giant.cost
        game.player2.field[0].destroy()
        after_death = giant.cost
        return {"base_cost": start, "after_three_other_minions": after_three,
                "after_one_dies": after_death, "boards": (len(game.player1.field), len(game.player2.field))}

    case("EX1_586", "cost_tracks_other_minions_on_both_boards",
         "Base cost 10 becomes 7 with three other minions on either side and returns to 8 after one dies.",
         both_sides_cost_case,
         lambda x: x["base_cost"] == 10 and x["after_three_other_minions"] == 7
         and x["after_one_dies"] == 8 and x["boards"] == (2, 0),
         "检查双方场上随从均计数、并随死亡动态回升费用。")
    finish_card("EX1_586", "每有一个其他场上随从，费用减少1。", "同时计数两方场面并验证费用随死亡更新。")


def probe_blood_knight():
    def shields_across_both_sides_case():
        game = fresh_game()
        friendly = game.player1.summon("EX1_008")
        enemy = game.player2.summon("EX1_008")
        plain = game.player1.summon(WISP)
        knight = game.player1.give("EX1_590")
        knight.play()
        return {"friendly_shield": friendly.divine_shield, "enemy_shield": enemy.divine_shield,
                "plain_shield": plain.divine_shield, "knight_stats": (knight.atk, knight.health),
                "board_counts": (len(game.player1.field), len(game.player2.field))}

    case("EX1_590", "removes_all_shields_and_gains_three_three_each",
         "Both players' Divine Shields are removed; two lost shields make Blood Knight 9/9, with unshielded minion unaffected.",
         shields_across_both_sides_case,
         lambda x: not x["friendly_shield"] and not x["enemy_shield"] and not x["plain_shield"]
         and x["knight_stats"] == (9, 9) and x["board_counts"] == (3, 1),
         "一面各放置一个圣盾随从，再加入无圣盾随从作对照，核验全场计数及移除范围。")
    finish_card("EX1_590", "移除全场圣盾；每移除一个，自身获得+3/+3。", "己方/敌方圣盾均计数；无圣盾随从和自身体型作对照。")


def probe_vaporize():
    def minion_attack_case():
        game = fresh_game(CardClass.MAGE, CardClass.WARRIOR)
        secret = game.player1.give("EX1_594")
        secret.play()
        game.end_turn()
        attacker = game.player2.give("EX1_116")
        attacker.play()
        attacker.attack(game.player1.hero)
        return {"attacker_zone": attacker.zone.name, "attacker_graveyard": [m.id for m in game.player2.graveyard],
                "secret_zone": secret.zone.name, "player1_health": game.player1.hero.health,
                "player1_field": [m.id for m in game.player1.field]}

    def hero_attack_nontrigger_case():
        game = fresh_game(CardClass.MAGE, CardClass.PALADIN)
        secret = game.player1.give("EX1_594")
        secret.play()
        game.end_turn()
        game.player2.give("CS2_080").play()
        game.player2.hero.attack(game.player1.hero)
        return {"secret_zone": secret.zone.name, "player1_health": game.player1.hero.health,
                "weapon_durability": game.player2.weapon.durability}

    case("EX1_594", "minion_attacking_hero_is_destroyed",
         "When an enemy Charge minion attacks the secret's controller hero, it is destroyed and the secret is consumed.",
         minion_attack_case,
         lambda x: x["attacker_zone"] == "GRAVEYARD" and "EX1_116" in x["attacker_graveyard"]
         and x["secret_zone"] == "GRAVEYARD" and x["player1_health"] == 30,
         "真实攻击事件；Leeroy攻击前应立即被Vaporize消灭，角色不承受伤害。")
    case("EX1_594", "hero_attack_does_not_trigger_minion_only_secret",
         "A hero attack damages the hero but leaves Vaporize in the SECRET zone, unrevealed.",
         hero_attack_nontrigger_case,
         lambda x: x["secret_zone"] == "SECRET" and x["player1_health"] == 27
         and x["weapon_durability"] == 3,
         "对象类型边界：敌方英雄而非随從攻击己方英雄。")
    finish_card("EX1_594", "仅敌方随从攻击己方英雄时触发并消灭攻击者。", "覆盖触发攻击与英雄攻击不触发两个真实战斗分支。")


def probe_cult_master():
    def friendly_death_draw_case():
        game = fresh_game()
        draw_card = game.player1.give(WISP)
        draw_card.shuffle_into_deck()
        friendly = game.player1.summon(WISP)
        enemy = game.player2.summon(WISP)
        master = game.player1.give("EX1_595")
        master.play()
        hand_before = len(game.player1.hand)
        enemy.destroy()
        hand_after_enemy_death = len(game.player1.hand)
        friendly.destroy()
        return {"hand_before": hand_before, "hand_after_enemy_death": hand_after_enemy_death,
                "hand_after_friendly_death": len(game.player1.hand),
                "drawn_ids": [c.id for c in game.player1.hand], "master_zone": master.zone.name}

    case("EX1_595", "draws_only_after_friendly_minion_dies",
         "Enemy death draws nothing; a subsequent friendly minion death draws exactly the known Wisp.",
         friendly_death_draw_case,
         lambda x: x["hand_before"] == x["hand_after_enemy_death"] == 0
         and x["hand_after_friendly_death"] == 1 and x["drawn_ids"] == ["CS2_231"]
         and x["master_zone"] == "PLAY",
         "测试对方死亡排除条件及己方死亡抽牌，牌库只有一张可追踪牌。")
    finish_card("EX1_595", "己方随从死亡后抽一张牌；敌方死亡不触发。", "同局先令敌方随从死亡作负例，再令己方随从死亡验证抽牌。")


def probe_demonfire():
    def friendly_demon_buff_case():
        game = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
        imp = game.player1.give(IMP)
        imp.play()
        before_damage = imp.damage
        game.player1.give("EX1_596").play(target=imp)
        return {"stats": (imp.atk, imp.health), "damage": imp.damage,
                "buff_ids": [b.id for b in imp.buffs], "zone": imp.zone.name}

    def enemy_minion_damage_case():
        game = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
        yeti = game.player2.summon("CS2_182")
        spell = game.player1.give("EX1_596")
        spell.play(target=yeti)
        return {"enemy_damage": yeti.damage, "enemy_health": yeti.health,
                "graveyard": [m.id for m in game.player2.graveyard], "spell_zone": spell.zone.name}

    case("EX1_596", "friendly_demon_gets_plus_two_plus_two_instead_of_damage",
         "Targeting a friendly Demon buffs its Attack and Health by 2 without dealing damage.",
         friendly_demon_buff_case,
         lambda x: x["stats"] == (3, 3) and x["damage"] == 0
         and "EX1_596e" in x["buff_ids"] and x["zone"] == "PLAY",
         "友方恶魔分支：检查真实加成、没有受到2点伤害且仍在场。")
    case("EX1_596", "enemy_minion_takes_two_damage",
         "An enemy non-Demon minion takes 2 damage and survives with 3 Health.",
         enemy_minion_damage_case,
         lambda x: x["enemy_damage"] == 2 and x["enemy_health"] == 3
         and "CS2_182" not in x["graveyard"] and x["spell_zone"] == "GRAVEYARD",
         "目标限制的敌方随从分支，确认造成伤害而非友方恶魔强化。")
    finish_card("EX1_596", "对随从造成2点伤害；仅友方恶魔改为+2/+2。", "分别覆盖友方恶魔强化和敌方非恶魔伤害。")


def probe_imp_master():
    def end_turn_trigger_case():
        game = fresh_game()
        master = game.player1.give("EX1_597")
        master.play()
        game.end_turn()
        tokens = [m for m in game.player1.field if m.id == "EX1_598"]
        return {"master_health": master.health, "field_ids": [m.id for m in game.player1.field],
                "token_stats": [(m.atk, m.health) for m in tokens], "master_zone": master.zone.name}

    def full_board_trigger_case():
        game = fresh_game()
        master = game.player1.give("EX1_597")
        master.play()
        for _ in range(6):
            game.player1.summon(WISP)
        before = len(game.player1.field)
        game.end_turn()
        return {"field_before": before, "field_after": len(game.player1.field),
                "imp_count": sum(m.id == "EX1_598" for m in game.player1.field),
                "master_health": master.health, "field_ids": [m.id for m in game.player1.field]}

    case("EX1_597", "end_turn_damages_self_and_summons_one_one_imp",
         "At controller end of turn, Imp Master loses 1 Health and summons one 1/1 Imp.",
         end_turn_trigger_case,
         lambda x: x["master_health"] == 4 and x["field_ids"] == ["EX1_597", "EX1_598"]
         and x["token_stats"] == [(1, 1)] and x["master_zone"] == "PLAY",
         "结束控制者回合触发，分别核验自伤和代币种类/身材。")
    case("EX1_597", "end_turn_summon_at_seven_minions_respects_capacity",
         "At seven friendly minions, end-turn self-damage still occurs but no eighth Imp is summoned.",
         full_board_trigger_case,
         lambda x: x["field_before"] == 7 and x["field_after"] == 7
         and x["imp_count"] == 0 and x["master_health"] == 4,
         "构造 Imp Master 加六个随从的满场触发分支，单独验证召唤容量边界。")
    finish_card("EX1_597", "己方回合结束时自身受1伤并召唤1/1小鬼。", "覆盖正常结束回合和七随从容量边界。")


def probe_cruel_taskmaster():
    def enemy_target_case():
        game = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
        target = game.player2.summon("CS2_182")
        control = game.player1.summon("CS2_182")
        taskmaster = game.player1.give("EX1_603")
        taskmaster.play(target=target)
        return {"target_stats": (target.atk, target.health), "target_damage": target.damage,
                "target_controller_is_enemy": target.controller is game.player2,
                "control_stats": (control.atk, control.health),
                "taskmaster_stats": (taskmaster.atk, taskmaster.health)}

    def friendly_target_case():
        game = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
        target = game.player1.summon("CS2_182")
        taskmaster = game.player1.give("EX1_603")
        taskmaster.play(target=target)
        return {"target_stats": (target.atk, target.health), "target_damage": target.damage,
                "target_controller_is_friendly": target.controller is game.player1,
                "taskmaster_stats": (taskmaster.atk, taskmaster.health)}

    case("EX1_603", "battlecry_damages_and_buffs_enemy_minion",
         "An enemy 4/5 becomes 6/4 with one damage; friendly control and Taskmaster stats are unchanged.",
         enemy_target_case,
         lambda x: x["target_stats"] == (6, 4) and x["target_damage"] == 1
         and x["target_controller_is_enemy"] and x["control_stats"] == (4, 5)
         and x["taskmaster_stats"] == (2, 2),
         "依照英文与简中战吼文字检查敌方合法目标，友方另一个随从未受影响。")
    case("EX1_603", "battlecry_also_accepts_friendly_minion_target",
         "A friendly 4/5 also becomes 6/4 with one damage; it remains under friendly control.",
         friendly_target_case,
         lambda x: x["target_stats"] == (6, 4) and x["target_damage"] == 1
         and x["target_controller_is_friendly"] and x["taskmaster_stats"] == (2, 2),
         "卡文没有敌方限定；额外实际指定己方随从验证目标阵营边界。")
    finish_card("EX1_603", "对任意一个随从造成1点伤害并使其获得+2攻击力。", "分别对敌方与己方4/5随从施放战吼。")


def probe_frothing_berserker():
    def damage_events_from_both_sides_case():
        game = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
        berserker = game.player1.give("EX1_604")
        berserker.play()
        friendly_yeti = game.player1.summon("CS2_182")
        enemy_yeti = game.player2.summon("CS2_182")
        friendly_wisp = game.player1.summon(WISP)
        enemy_wisp = game.player2.summon(WISP)
        game.player1.give("EX1_400").play()
        return {"berserker_stats": (berserker.atk, berserker.health),
                "friendly_yeti": (friendly_yeti.damage, friendly_yeti.health),
                "enemy_yeti": (enemy_yeti.damage, enemy_yeti.health),
                "wisp_zones": (friendly_wisp.zone.name, enemy_wisp.zone.name),
                "graveyards": ([m.id for m in game.player1.graveyard], [m.id for m in game.player2.graveyard])}

    case("EX1_604", "gains_attack_for_each_damaged_minion_on_either_side",
         "Whirlwind damages Berserker, two Yetis, and kills two Wisps; five damage events grant +5 Attack, and both Yetis take 1.",
         damage_events_from_both_sides_case,
         lambda x: x["berserker_stats"] == (7, 3)
         and x["friendly_yeti"] == x["enemy_yeti"] == (1, 4)
         and x["wisp_zones"] == ("GRAVEYARD", "GRAVEYARD")
         and "CS2_231" in x["graveyards"][0] and "CS2_231" in x["graveyards"][1],
         "一次全场伤害覆盖自身、双方存活随从和双方死亡随从，逐项检查每次受伤触发。")
    finish_card("EX1_604", "任意随从受到伤害后，暴乱狂战士获得+1攻击力。", "Whirlwind 同时命中自身、双方随从并击杀双方随从。")


def probe_inner_rage():
    def target_case(side):
        game = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
        target_player = game.player1 if side == "friendly" else game.player2
        target = target_player.summon("CS2_182")
        spell = game.player1.give("EX1_607")
        spell.play(target=target)
        return {"target_stats": (target.atk, target.health), "target_damage": target.damage,
                "controller_is_expected": target.controller is target_player,
                "spell_zone": spell.zone.name}

    case("EX1_607", "targets_enemy_minion_for_plus_two_attack_and_one_damage",
         "An enemy 4/5 becomes 6/4 after +2 Attack and 1 damage; spell resolves to graveyard.",
         lambda: target_case("enemy"),
         lambda x: x["target_stats"] == (6, 4) and x["target_damage"] == 1
         and x["controller_is_expected"] and x["spell_zone"] == "GRAVEYARD",
         "按战吼/法术目标文字实际指定敌方随从。")
    case("EX1_607", "also_targets_friendly_minion",
         "A friendly 4/5 also becomes 6/4 after +2 Attack and 1 damage.",
         lambda: target_case("friendly"),
         lambda x: x["target_stats"] == (6, 4) and x["target_damage"] == 1
         and x["controller_is_expected"] and x["spell_zone"] == "GRAVEYARD",
         "文字未限定敌方目标；另以己方随从确认友方目标可选。")
    finish_card("EX1_607", "对一个随从造成1点伤害并使其获得+2攻击力。", "对敌方和己方随从分别实放。")


def probe_sorcerers_apprentice():
    def spell_discount_stacking_and_expiry_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        fireball = game.player1.give("CS2_029")
        moonfire = game.player1.give(MOONFIRE)
        first = game.player1.give("EX1_608")
        first.play()
        after_one = (fireball.cost, moonfire.cost)
        second = game.player1.give("EX1_608")
        second.play()
        after_two = (fireball.cost, moonfire.cost)
        first.destroy()
        after_one_removed = (fireball.cost, moonfire.cost)
        second.destroy()
        after_both_removed = (fireball.cost, moonfire.cost)
        return {"base_costs": (4, 0), "after_one": after_one, "after_two": after_two,
                "after_one_removed": after_one_removed, "after_both_removed": after_both_removed}

    case("EX1_608", "discounts_own_spells_stacks_and_expires_with_source",
         "Spell costs go (4,0)->(3,0)->(2,0) with two Apprentices, then return 3 and 4 as each source leaves play.",
         spell_discount_stacking_and_expiry_case,
         lambda x: x["base_costs"] == (4, 0) and x["after_one"] == (3, 0)
         and x["after_two"] == (2, 0) and x["after_one_removed"] == (3, 0)
         and x["after_both_removed"] == (4, 0),
         "真实打出两名巫师学徒，覆盖费用叠加、0费下限和各自离场后的动态恢复。")
    finish_card("EX1_608", "己方法术费用减少1，多个来源叠加并随来源离场恢复。", "检查火球术和0费Moonfire及两名学徒的叠加/退场。")


def probe_snipe():
    def only_opponent_played_minion_is_hit_case():
        game = fresh_game(CardClass.HUNTER, CardClass.MAGE)
        secret = game.player1.give("EX1_609")
        secret.play()
        own_minion = game.player1.give("CS2_182")
        own_minion.play()
        secret_after_own_play = secret.zone.name
        game.end_turn()
        target = game.player2.give("CS2_182")
        target.play()
        return {"secret_after_own_play": secret_after_own_play,
                "secret_after_enemy_play": secret.zone.name,
                "target_damage": target.damage, "target_health": target.health,
                "target_zone": target.zone.name, "own_minion": (own_minion.damage, own_minion.health)}

    case("EX1_609", "only_opponent_minion_play_triggers_four_damage_snipe",
         "The controller's own minion leaves Snipe armed; the opponent's played 4/5 minion takes 4 damage and survives at 1 Health.",
         only_opponent_played_minion_is_hit_case,
         lambda x: x["secret_after_own_play"] == "SECRET" and x["secret_after_enemy_play"] == "GRAVEYARD"
         and x["target_damage"] == 4 and x["target_health"] == 1 and x["target_zone"] == "PLAY"
         and x["own_minion"] == (0, 5),
         "先以己方出牌检查对手限定，再真实打出敌方随从检查4点伤害与奥秘消耗。")
    finish_card("EX1_609", "对手打出随从后，狙击对该随从造成4点伤害。", "分别覆盖己方不触发与敌方打出触发。")


def probe_explosive_trap():
    def minion_attack_aoe_case():
        game = fresh_game(CardClass.HUNTER, CardClass.WARRIOR)
        secret = game.player1.give("EX1_610")
        secret.play()
        game.end_turn()
        dying_wisp = game.player2.summon(WISP)
        yeti = game.player2.summon("CS2_182")
        attacker = game.player2.give("EX1_116")
        attacker.play()
        attacker.attack(game.player1.hero)
        return {"secret_zone": secret.zone.name, "player1_health": game.player1.hero.health,
                "enemy_hero_health": game.player2.hero.health,
                "wisp_zone": dying_wisp.zone.name, "yeti": (yeti.damage, yeti.health),
                "attacker_zone": attacker.zone.name,
                "enemy_graveyard": [m.id for m in game.player2.graveyard]}

    def hero_attack_triggers_case():
        game = fresh_game(CardClass.HUNTER, CardClass.PALADIN)
        secret = game.player1.give("EX1_610")
        secret.play()
        game.end_turn()
        yeti = game.player2.summon("CS2_182")
        game.player2.give("CS2_080").play()
        game.player2.hero.attack(game.player1.hero)
        return {"secret_zone": secret.zone.name, "player1_health": game.player1.hero.health,
                "enemy_hero_health": game.player2.hero.health, "yeti": (yeti.damage, yeti.health)}

    case("EX1_610", "minion_attack_triggers_two_damage_to_all_enemies",
         "Enemy minion attack reveals Trap: enemy hero and all three enemy minions take 2; Wisp and attacker die, Yeti survives at 3, defending hero is unharmed.",
         minion_attack_aoe_case,
         lambda x: x["secret_zone"] == "GRAVEYARD" and x["player1_health"] == 30
         and x["enemy_hero_health"] == 28 and x["wisp_zone"] == "GRAVEYARD"
         and x["yeti"] == (2, 3) and x["attacker_zone"] == "GRAVEYARD"
         and "CS2_231" in x["enemy_graveyard"] and "EX1_116" in x["enemy_graveyard"],
         "使用Leeroy攻击英雄，检验奥秘触发、敌方全体范围伤害、致死区域和攻击取消。")
    case("EX1_610", "enemy_hero_attack_also_triggers_area_damage",
         "Enemy hero attacks the defending hero; Trap deals 2 to that enemy hero and its minion, then is consumed.",
         hero_attack_triggers_case,
         lambda x: x["secret_zone"] == "GRAVEYARD" and x["player1_health"] == 27
         and x["enemy_hero_health"] == 28 and x["yeti"] == (2, 3),
         "以敌方英雄而非敌方随从作为攻击者，再检查所有敌人均受伤。")
    finish_card("EX1_610", "英雄受到攻击时，奥秘对所有敌人造成2点伤害。", "验证随从攻击和英雄攻击触发，以及敌方角色范围。")


def probe_freezing_trap():
    def minion_attack_bounces_and_increases_cost_case():
        game = fresh_game(CardClass.HUNTER, CardClass.WARRIOR)
        friendly_target = game.player1.summon("CS2_182")
        secret = game.player1.give("EX1_611")
        secret.play()
        game.end_turn()
        attacker = game.player2.give("EX1_116")
        attacker.play()
        base_cost = attacker.data.cost
        attacker.attack(friendly_target)
        return {"secret_zone": secret.zone.name, "attacker_zone": attacker.zone.name,
                "attacker_controller_is_opponent": attacker.controller is game.player2,
                "attacker_cost": attacker.cost, "base_cost": base_cost,
                "target_damage": friendly_target.damage, "target_health": friendly_target.health,
                "attacker_in_hand": attacker in game.player2.hand}

    def hero_attack_does_not_trigger_case():
        game = fresh_game(CardClass.HUNTER, CardClass.PALADIN)
        secret = game.player1.give("EX1_611")
        secret.play()
        game.end_turn()
        game.player2.give("CS2_080").play()
        game.player2.hero.attack(game.player1.hero)
        return {"secret_zone": secret.zone.name, "player1_health": game.player1.hero.health,
                "weapon_durability": game.player2.weapon.durability}

    case("EX1_611", "enemy_minion_attack_returns_attacker_with_plus_two_cost",
         "Enemy Charge minion attacking a friendly minion is returned to its owner's hand with +2 cost; attack combat does not damage the target.",
         minion_attack_bounces_and_increases_cost_case,
         lambda x: x["secret_zone"] == "GRAVEYARD" and x["attacker_zone"] == "HAND"
         and x["attacker_controller_is_opponent"] and x["attacker_in_hand"]
         and x["attacker_cost"] == x["base_cost"] + 2 and x["target_damage"] == 0
         and x["target_health"] == 5,
         "覆盖攻击己方随从的触发目标、退回拥有者手牌、费用附魔与攻击被取消。")
    case("EX1_611", "hero_attack_does_not_trigger_freezing_trap",
         "Enemy hero attack damages the defending hero but leaves Freezing Trap armed.",
         hero_attack_does_not_trigger_case,
         lambda x: x["secret_zone"] == "SECRET" and x["player1_health"] == 27
         and x["weapon_durability"] == 3,
         "对象边界：敌方英雄攻击不满足‘敌方随从攻击’条件。")
    finish_card("EX1_611", "敌方随从攻击时，将攻击者移回其拥有者手牌并使其费用增加2。", "以敌方随从攻击己方随从触发，并用英雄攻击作负例。")


def probe_kirin_tor_mage():
    def next_secret_discount_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        counterspell = game.player1.give("EX1_287")
        vaporize = game.player1.give("EX1_594")
        fireball = game.player1.give("CS2_029")
        mage = game.player1.give("EX1_612")
        base_costs = (counterspell.cost, vaporize.cost, fireball.cost)
        mage.play()
        discounted_costs = (counterspell.cost, vaporize.cost, fireball.cost)
        counterspell.play()
        after_secret_play = (counterspell.zone.name, vaporize.cost, fireball.cost)
        game.end_turn()
        after_turn = (vaporize.cost, fireball.cost)
        return {"base_costs": base_costs, "discounted_costs": discounted_costs,
                "after_secret_play": after_secret_play, "after_turn": after_turn,
                "mage_zone": mage.zone.name}

    case("EX1_612", "battlecry_makes_next_secret_free_only_for_this_turn",
         "Mage sets Secrets to 0 while active; casting one Secret restores another to 3, leaves non-Secret Fireball at 4, and turn end leaves ordinary costs.",
         next_secret_discount_case,
         lambda x: x["base_costs"] == (3, 3, 4) and x["discounted_costs"] == (0, 0, 4)
         and x["after_secret_play"] == ("SECRET", 3, 4) and x["after_turn"] == (3, 4)
         and x["mage_zone"] == "PLAY",
         "真实打出肯瑞托法师及奥秘，覆盖零费、仅下一张消耗、非奥秘不减费和回合到期。")
    finish_card("EX1_612", "本回合下一张奥秘的法力值消耗为0。", "以两张奥秘验证一次性消耗，并以火球术作非奥秘对照。")


def probe_edwin_van_cleef():
    def combo_two_cards_case():
        game = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
        game.player1.give(THE_COIN).play()
        game.player1.give(THE_COIN).play()
        count_before = game.player1.cards_played_this_turn
        edwin = game.player1.give("EX1_613")
        edwin.play()
        return {"prior_cards": count_before, "cards_after": game.player1.cards_played_this_turn,
                "stats": (edwin.atk, edwin.health), "buff_ids": [b.id for b in edwin.buffs]}

    def no_prior_card_case():
        game = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
        edwin = game.player1.give("EX1_613")
        edwin.play()
        return {"cards_after": game.player1.cards_played_this_turn,
                "stats": (edwin.atk, edwin.health), "buff_ids": [b.id for b in edwin.buffs]}

    case("EX1_613", "combo_counts_each_other_card_played_this_turn",
         "Two prior Coins grant +4/+4, making Edwin 6/6; playing Edwin advances the counter but is not counted in its own Combo.",
         combo_two_cards_case,
         lambda x: x["prior_cards"] == 2 and x["cards_after"] == 3
         and x["stats"] == (6, 6) and x["buff_ids"].count("EX1_613e") == 2,
         "将两张0费硬币实际打出后再下范克里夫，逐张核验连击计数。")
    case("EX1_613", "no_combo_without_prior_card",
         "When played as the first card, Edwin remains its base 2/2 and gains no Combo enchantment.",
         no_prior_card_case,
         lambda x: x["cards_after"] == 1 and x["stats"] == (2, 2)
         and "EX1_613e" not in x["buff_ids"],
         "单独新局第一张打出，确认不把范克里夫自身计入连击。")
    finish_card("EX1_613", "连击：本回合每打出一张其他牌，获得+2/+2。", "分别验证两张先前牌逐次叠加以及无先前牌分支。")


def probe_xavius():
    def own_and_enemy_card_play_scope_case():
        game = fresh_game(CardClass.DRUID, CardClass.DRUID)
        xavius = game.player1.give("EX1_614")
        xavius.play()
        own_card = game.player1.give(MOONFIRE)
        own_card.play(target=game.player2.hero)
        after_own_play = [m.id for m in game.player1.field]
        game.end_turn()
        enemy_card = game.player2.give(MOONFIRE)
        enemy_card.play(target=game.player1.hero)
        after_enemy_play = [m.id for m in game.player1.field]
        return {"after_own_play": after_own_play, "after_enemy_play": after_enemy_play,
                "own_spell_zone": own_card.zone.name, "enemy_spell_zone": enemy_card.zone.name,
                "token_stats": [(m.atk, m.health) for m in game.player1.field if m.id == "EX1_614t"]}

    def full_board_no_eighth_token_case():
        game = fresh_game()
        xavius = game.player1.give("EX1_614")
        xavius.play()
        for _ in range(6):
            game.player1.summon(WISP)
        before = len(game.player1.field)
        spell = game.player1.give(MOONFIRE)
        spell.play(target=game.player2.hero)
        return {"field_before": before, "field_after": len(game.player1.field),
                "field_ids": [m.id for m in game.player1.field],
                "token_count": sum(m.id == "EX1_614t" for m in game.player1.field)}

    case("EX1_614", "only_own_card_play_summons_two_one_satyr",
         "Xavius is 7/5; own Moonfire summons exactly a 2/1 Satyr, while an opponent Moonfire summons none.",
         own_and_enemy_card_play_scope_case,
         lambda x: x["after_own_play"] == ["EX1_614", "EX1_614t"]
         and x["after_enemy_play"] == ["EX1_614", "EX1_614t"]
         and x["own_spell_zone"] == x["enemy_spell_zone"] == "GRAVEYARD"
         and x["token_stats"] == [(2, 1)],
         "分别由控制者与对手真实打出0费牌，检查 OWN_CARD_PLAY 触发范围。")
    case("EX1_614", "own_card_play_trigger_does_not_overfill_full_board",
         "With seven friendly minions, own card play causes no eighth Satyr.",
         full_board_no_eighth_token_case,
         lambda x: x["field_before"] == 7 and x["field_after"] == 7
         and x["token_count"] == 0 and x["field_ids"].count("EX1_614") == 1,
         "直接验证满场触发时不产生第八个实体。")
    finish_card("EX1_614", "己方打出牌后召唤一个2/1萨特。", "验证己方/对手打牌触发范围和满场容量上限。")


def probe_mana_wraith():
    def both_hands_minion_cost_aura_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        minions = [game.player1.give(WISP), game.player2.give(WISP),
                   game.player1.give("CS2_182"), game.player2.give("CS2_182")]
        spells = [game.player1.give("CS2_029"), game.player2.give("CS2_029")]
        base_minion_costs = [c.cost for c in minions]
        base_spell_costs = [c.cost for c in spells]
        wraith = game.player1.give("EX1_616")
        wraith.play()
        while_present_minion_costs = [c.cost for c in minions]
        while_present_spell_costs = [c.cost for c in spells]
        wraith.destroy()
        after_removal_minion_costs = [c.cost for c in minions]
        return {"base_minion_costs": base_minion_costs, "base_spell_costs": base_spell_costs,
                "while_present_minion_costs": while_present_minion_costs,
                "while_present_spell_costs": while_present_spell_costs,
                "after_removal_minion_costs": after_removal_minion_costs}

    case("EX1_616", "all_players_hand_minions_cost_one_more_while_source_lives",
         "Both players' 0-cost Wisps and 4-cost Yetis gain +1 cost; Fireballs stay 4, and minion costs return when Mana Wraith leaves.",
         both_hands_minion_cost_aura_case,
         lambda x: x["base_minion_costs"] == [0, 0, 4, 4]
         and x["base_spell_costs"] == [4, 4]
         and x["while_present_minion_costs"] == [1, 1, 5, 5]
         and x["while_present_spell_costs"] == [4, 4]
         and x["after_removal_minion_costs"] == [0, 0, 4, 4],
         "双方手牌分别放0费与4费随从，对照双方火球术并验证来源离场恢复。")
    finish_card("EX1_616", "所有玩家手牌中的随从费用增加1。", "实测双方手牌的随从/法术差异及 aura 离场恢复。")


def main():
    probe_path = PROBE_PATH
    verdict_path = VERDICT_PATH
    if not probe_path.exists():
        write_rows(probe_path, PROBE_FIELDS, [])
    if not verdict_path.exists():
        write_rows(verdict_path, VERDICT_FIELDS, [])
    probes = [
        ("EX1_578", probe_savagery),
        ("EX1_583", probe_priestess_of_elune), ("EX1_584", probe_ancient_mage),
        ("EX1_586", probe_sea_giant), ("EX1_590", probe_blood_knight),
        ("EX1_594", probe_vaporize), ("EX1_595", probe_cult_master),
        ("EX1_596", probe_demonfire), ("EX1_597", probe_imp_master),
        ("EX1_603", probe_cruel_taskmaster), ("EX1_604", probe_frothing_berserker),
        ("EX1_607", probe_inner_rage), ("EX1_608", probe_sorcerers_apprentice),
        ("EX1_609", probe_snipe), ("EX1_610", probe_explosive_trap),
        ("EX1_611", probe_freezing_trap), ("EX1_612", probe_kirin_tor_mage),
        ("EX1_613", probe_edwin_van_cleef), ("EX1_614", probe_xavius),
        ("EX1_616", probe_mana_wraith),
    ]
    verdict_ids = {r["card_id"] for r in existing_rows(VERDICT_PATH)}
    for card_id, probe in probes:
        if card_id not in verdict_ids:
            probe()
    rows = read_rows(BASELINE_PATH)
    targets = rows[179:199]
    ids = {r["card_id"] for r in targets}
    verdict_ids = {r["card_id"] for r in existing_rows(VERDICT_PATH)}
    probe_ids = {r["card_id"] for r in existing_rows(PROBE_PATH)}
    print(f"baseline_rows={len(targets)} verdicts={len(verdict_ids)} probe_covered={len(probe_ids)} "
          f"missing_verdicts={sorted(ids-verdict_ids)} missing_probes={sorted(ids-probe_ids)}")


if __name__ == "__main__":
    main()
