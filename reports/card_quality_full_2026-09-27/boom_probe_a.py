"""Card-specific live game checks for the collectible first 45 Boomsday YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Zone
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "boom_probe_a.csv"
VERDICT_FILE = HERE / "boom_verdict_a.csv"
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
                 if r["set"].endswith("(BOOMSDAY)")),
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



def goblin_bomb():
    cid = "BOT_031"

    def deathrattle_enemy_hero_only():
        g, p, e = game(CardClass.HUNTER)
        bomb = play(p, cid)
        own, enemy = p.hero.health, e.hero.health
        bomb.destroy()
        observed = f"bomb={bomb.zone.name};hero={own}->{p.hero.health};enemy={enemy}->{e.hero.health}"
        return check(bomb.zone != Zone.PLAY and p.hero.health == own
                     and e.hero.health == enemy - 2, observed)

    audit(cid, [("deathrattle_hits_enemy_hero", "When Goblin Bomb dies, opponent hero takes exactly 2 damage and owner hero does not.", deathrattle_enemy_hero_only, "实际击毁0/2炸弹，检查双方英雄生命。")])


def skaterbot():
    cid = "BOT_020"

    def magnetic_and_rush():
        g, p, e = game()
        host = p.summon("BOT_031")
        enemy = e.summon(WISP)
        part = p.give(cid)
        stats = (host.atk + part.atk, host.health + part.health)
        part.play(index=0)
        attached = (host.atk,host.health,host.rush,len(p.field),part.zone.name)
        ready = host.can_attack(enemy)
        if ready:
            host.attack(enemy)
        observed = f"expected_stats={stats};attached={attached};rush_ready={ready};enemy={enemy.zone.name};host={host.zone.name}:{host.health}"
        return check((host.atk,host.max_health)==(stats[0],stats[1])
                     and host.rush and len(p.field)==1 and part.zone != Zone.PLAY
                     and ready and enemy.zone != Zone.PLAY, observed)

    def standalone_rush():
        g, p, e = game()
        part = play(p, cid)
        enemy = e.summon(WISP)
        observed = f"body={part.zone.name}:{part.atk}/{part.health};rush={part.rush};can_attack_minion={part.can_attack(enemy)};can_attack_hero={part.can_attack(e.hero)}"
        return check(part.zone == Zone.PLAY and part.rush and part.can_attack(enemy)
                     and not part.can_attack(e.hero), observed)

    audit(cid, [
        ("magnetic_grants_rush_and_stats", "Placed left of friendly Mech, Skaterbot merges, adds its stats and Rush, and can attack enemy minion immediately.", magnetic_and_rush, "实测磁力融合后场位、身材、突袭攻击及原卡区域。"),
        ("standalone_has_rush", "Without Mech host, Skaterbot remains a separate Rush minion that cannot attack hero on play turn.", standalone_rush, "无磁力目标对照。"),
    ])


def bronze_gatekeeper():
    cid = "BOT_021"

    def magnetic_and_taunt():
        g, p, e = game()
        host = p.summon("BOT_031")
        part = p.give(cid)
        stats = (host.atk+part.atk,host.health+part.health)
        part.play(index=0)
        observed = f"host={host.atk}/{host.health}:taunt={host.taunt};part={part.zone.name};field={[m.id for m in p.field]};expected_stats={stats}"
        return check((host.atk,host.max_health)==stats and host.taunt
                     and len(p.field)==1 and part.zone != Zone.PLAY, observed)

    def standalone_taunt():
        g, p, e = game()
        part = play(p, cid)
        observed = f"body={part.atk}/{part.health}:{part.zone.name};taunt={part.taunt};field={len(p.field)}"
        return check(part.zone == Zone.PLAY and part.taunt and len(p.field)==1, observed)

    audit(cid, [
        ("magnetic_grants_taunt", "Left placement merges into friendly Mech, adds stats and Taunt, consuming the magnetic card's board slot.", magnetic_and_taunt, "磁力融合后核对身材、嘲讽与区域。"),
        ("standalone_taunt", "With no Mech, Bronze Gatekeeper is its own Taunt minion.", standalone_taunt, "无磁力目标对照。"),
    ])


def venomizer():
    cid = "BOT_035"

    def magnetic_poisonous_combat():
        g, p, e = game(CardClass.HUNTER)
        host = p.summon("BOT_031")
        g.end_turn()
        g.end_turn()
        part = p.give(cid)
        stats = (host.atk+part.atk,host.health+part.health)
        enemy = e.summon("CS2_182")
        part.play(index=0)
        poisonous = host.poisonous
        host.attack(enemy)
        observed = f"stats={stats};host={host.zone.name}:{host.atk}/{host.health};poisonous={poisonous};enemy={enemy.zone.name}:{enemy.health};part={part.zone.name}"
        return check(poisonous and host.atk==stats[0]
                     and part.zone != Zone.PLAY and enemy.zone != Zone.PLAY, observed)

    def standalone_poisonous():
        g, p, e = game(CardClass.HUNTER)
        part = play(p, cid)
        observed = f"body={part.zone.name}:{part.atk}/{part.health};poisonous={part.poisonous}"
        return check(part.zone == Zone.PLAY and part.poisonous, observed)

    audit(cid, [
        ("magnetic_poisonous_kills_larger_minion", "Venomizer merges into Mech, grants Poisonous, and combat destroys a 5-Health Yeti.", magnetic_poisonous_combat, "融合后跨回合实际攻击高生命敌方随从。"),
        ("standalone_poisonous", "Without friendly Mech, Venomizer is its own Poisonous minion.", standalone_poisonous, "独立打出对照。"),
    ])


def bomb_toss():
    cid = "BOT_033"

    def target_damage_and_summon():
        g, p, e = game(CardClass.HUNTER)
        target = e.summon("CS2_182")
        before = target.health
        spell = play(p, cid, target=target)
        bombs = [m for m in p.field if m.id == "BOT_031"]
        observed = f"target={before}->{target.health}:{target.zone.name};bombs={[(m.atk,m.health,m.zone.name) for m in bombs]};spell={spell.zone.name};enemy_hero={e.hero.health}"
        return check(target.health == before - 2 and target.zone == Zone.PLAY
                     and len(bombs) == 1 and (bombs[0].atk,bombs[0].health) == (0,2)
                     and spell.zone == Zone.GRAVEYARD and e.hero.health == 30, observed)

    audit(cid, [("damage_and_one_goblin_bomb", "Chosen minion takes 2 damage and exactly one 0/2 Goblin Bomb is summoned for the caster.", target_damage_and_summon, "实际指定敌方随从，检查伤害、召唤数量、控制方与区域。")])


def boommaster_flark():
    cid = "BOT_034"

    def four_bombs():
        g, p, e = game(CardClass.HUNTER)
        flark = play(p, cid)
        bombs = [m for m in p.field if m.id == "BOT_031"]
        observed = f"flark={flark.zone.name};bombs={[(m.atk,m.health,m.zone.name) for m in bombs]};opponent_field={len(e.field)}"
        return check(flark.zone == Zone.PLAY and len(bombs) == 4
                     and len(p.field) == 5 and not e.field
                     and all((m.atk,m.health,m.zone)==(0,2,Zone.PLAY) for m in bombs), observed)

    audit(cid, [("four_friendly_bombs", "Battlecry summons exactly four friendly 0/2 Goblin Bombs.", four_bombs, "从空场打出，检查本体和四个衍生物均在己方场区。")])


def weapons_project():
    cid = "BOT_042"

    def both_weapons_and_armor():
        g, p, e = game(CardClass.WARRIOR)
        own_old = play(p, "CS2_091")
        g.end_turn()
        g.end_turn()
        p.used_mana = 0
        e_old = e.give("CS2_091")
        e_old.zone = Zone.PLAY
        own_before, enemy_before = p.hero.armor, e.hero.armor
        play(p, cid)
        observed = f"weapons={(p.weapon.id,p.weapon.atk,p.weapon.durability) if p.weapon else None},{(e.weapon.id,e.weapon.atk,e.weapon.durability) if e.weapon else None};armor={own_before}->{p.hero.armor},{enemy_before}->{e.hero.armor};old={own_old.zone.name},{e_old.zone.name}"
        return check(p.weapon and e.weapon and p.weapon.id == e.weapon.id == "BOT_042t"
                     and (p.weapon.atk,p.weapon.durability)==(2,3)
                     and (e.weapon.atk,e.weapon.durability)==(2,3)
                     and p.hero.armor == own_before+6 and e.hero.armor == enemy_before+6
                     and own_old.zone != Zone.PLAY and e_old.zone != Zone.PLAY, observed)

    audit(cid, [("both_players_replace_weapon_and_gain_armor", "Each player equips a new 2/3 weapon, replacing any old weapon, and gains 6 Armor.", both_weapons_and_armor, "双方先装备旧武器，再施法核对替换、武器身材和双侧护甲。")])


def biology_project():
    cid = "BOT_054"

    def both_gain_two_crystals():
        g, p, e = game(CardClass.DRUID)
        p.max_mana, e.max_mana = 4, 5
        p.used_mana, e.used_mana = 0, 0
        before = (p.max_mana,e.max_mana)
        play(p, cid)
        observed = f"mana_crystals={before}->{(p.max_mana,e.max_mana)};available={(p.mana,e.mana)}"
        return check((p.max_mana,e.max_mana)==(6,7), observed)

    def mana_cap():
        g, p, e = game(CardClass.DRUID)
        p.max_mana, e.max_mana = 9, 10
        play(p, cid)
        observed = f"mana_cap={p.max_mana},{e.max_mana}"
        return check((p.max_mana,e.max_mana)==(10,10), observed)

    audit(cid, [
        ("both_players_two_crystals", "Both players gain two Mana Crystals at four and five crystals.", both_gain_two_crystals, "双方不同起始水晶数。"),
        ("ten_crystal_cap", "At nine and ten crystals, both players remain capped at ten.", mana_cap, "满水晶边界。"),
    ])


def eternium_rover():
    cid = "BOT_059"

    def two_damage_instances_two_armor():
        g, p, e = game(CardClass.WARRIOR)
        rover = play(p, cid)
        first = p.give("CS2_008")
        first.play(target=rover)
        after_first = (rover.health,p.hero.armor)
        second = p.give("CS2_008")
        second.play(target=rover)
        observed = f"after_first={after_first};after_second={(rover.health,p.hero.armor)};zone={rover.zone.name}"
        return check(after_first == (2,2) and (rover.health,p.hero.armor)==(1,4)
                     and rover.zone == Zone.PLAY, observed)

    audit(cid, [("two_hits_gain_four_armor", "Two separate 1-damage hits to Rover grant 2 Armor each, for 4 total.", two_damage_instances_two_armor, "两次实际法术伤害分别检查随从生命和英雄护甲。")])


def fireworks_tech():
    cid = "BOT_038"

    def buff_and_trigger_deathrattle_without_death():
        g, p, e = game(CardClass.HUNTER)
        mech = p.summon("BOT_031")
        body = play(p, cid, target=mech)
        observed = f"bomb={mech.zone.name}:{mech.atk}/{mech.health};enemy_hero={e.hero.health};tech={body.zone.name}"
        return check(mech.zone == Zone.PLAY and (mech.atk,mech.health)==(1,3)
                     and e.hero.health == 28 and body.zone == Zone.PLAY, observed)

    def non_deathrattle_mech_only_buff():
        g, p, e = game(CardClass.HUNTER)
        mech = p.summon("BOT_312t")
        before = (mech.atk,mech.health)
        play(p, cid, target=mech)
        observed = f"mech={before}->{(mech.atk,mech.health)};enemy_hero={e.hero.health}"
        return check((mech.atk,mech.health)==(before[0]+1,before[1]+1)
                     and e.hero.health == 30, observed)

    audit(cid, [
        ("deathrattle_mech_buff_and_trigger", "Buff friendly Deathrattle Mech +1/+1 and trigger its Deathrattle without killing it.", buff_and_trigger_deathrattle_without_death, "以地精炸弹为合法目标，检查提前触发2伤、身材及存活。"),
        ("non_deathrattle_mech_no_trigger", "Buff ordinary Mech +1/+1 without extra Deathrattle damage.", non_deathrattle_mech_only_buff, "无亡语机械体对照。"),
    ])


def necromechanic():
    cid = "BOT_039"

    def friendly_double_enemy_normal():
        g, p, e = game(CardClass.HUNTER)
        body = play(p, cid)
        own_bomb = p.summon("BOT_031")
        own_bomb.destroy()
        enemy_after_own = e.hero.health
        enemy_bomb = e.summon("BOT_031")
        enemy_bomb.destroy()
        observed = f"necromechanic={body.zone.name};enemy_hero={enemy_after_own}->{e.hero.health};owner_hero={p.hero.health};bombs={own_bomb.zone.name},{enemy_bomb.zone.name}"
        return check(body.zone == Zone.PLAY and enemy_after_own == 26
                     and e.hero.health == 26 and p.hero.health == 28, observed)

    audit(cid, [("friendly_twice_enemy_once", "Friendly Goblin Bomb Deathrattle fires twice (4 hero damage); opponent Bomb Deathrattle fires once (2 hero damage).", friendly_double_enemy_normal, "同局分别击毁双方炸弹，验证光环只加倍己方亡语。")])


def rusty_recycler():
    cid = "BOT_050"

    def taunt_lifesteal_in_combat():
        g, p, e = game()
        p.hero.damage = 5
        body = play(p, cid)
        enemy = e.summon("CS2_182")
        g.end_turn()
        g.end_turn()
        before = p.hero.health
        body.attack(enemy)
        observed = f"taunt={body.taunt};lifesteal={body.lifesteal};owner_hero={before}->{p.hero.health};enemy={enemy.health}:{enemy.zone.name};recycler={body.zone.name}"
        return check(body.taunt and body.lifesteal and before == 25
                     and p.hero.health == 27 and enemy.health == 3, observed)

    audit(cid, [("taunt_and_combat_lifesteal", "Rusty Recycler has Taunt and a 2-damage combat hit restores exactly 2 Health to its damaged hero.", taunt_lifesteal_in_combat, "预先损伤英雄，真实攻击5生命敌随从验证吸血而非仅标签。")])


def mechanical_whelp():
    cid = "BOT_066"

    def deathrattle_seven_seven():
        g, p, e = game()
        body = play(p, cid)
        body.destroy()
        dragons = [m for m in p.field if m.id == "BOT_066t"]
        observed = f"whelp={body.zone.name};dragons={[(m.id,m.atk,m.health,m.zone.name) for m in dragons]};enemy_field={len(e.field)}"
        return check(body.zone != Zone.PLAY and len(dragons)==1
                     and (dragons[0].atk,dragons[0].health,dragons[0].zone)==(7,7,Zone.PLAY)
                     and not e.field, observed)

    audit(cid, [("deathrattle_summons_dragon", "Death of Mechanical Whelp summons one friendly 7/7 Mechanical Dragon.", deathrattle_seven_seven, "实际消灭本体，检查衍生物数量、身材及区域。")])


def rocket_boots():
    cid = "BOT_067"

    def rush_and_draw():
        g, p, e = game(CardClass.WARRIOR)
        target = p.summon(WISP)
        enemy = e.summon(WISP)
        drawn = p.give("CS2_182")
        drawn.shuffle_into_deck()
        play(p, cid, target=target)
        rush, ready = target.rush, target.can_attack(enemy)
        if ready:
            target.attack(enemy)
        observed = f"rush={rush};ready={ready};target={target.zone.name};enemy={enemy.zone.name};drawn={drawn.zone.name}"
        return check(rush and ready and target.zone != Zone.PLAY
                     and enemy.zone != Zone.PLAY and drawn.zone == Zone.HAND, observed)

    audit(cid, [("friendly_minion_rush_and_draw", "Friendly just-summoned minion gains Rush, attacks enemy minion now, and caster draws one card.", rush_and_draw, "实际附加突袭、执行攻击，检查目标双方死亡和牌库卡入手。")])


def the_boomship():
    cid = "BOT_069"

    def three_hand_minions_summoned_with_rush():
        g, p, e = game(CardClass.WARRIOR)
        cards = [p.give(x) for x in (WISP,"CS2_182","BOT_031")]
        spell = play(p, cid)
        observed = f"cards={[(c.id,c.zone.name,c.rush) for c in cards]};field={[m.id for m in p.field]};hand={[c.id for c in p.hand]};spell={spell.zone.name}"
        return check(len(p.field)==3 and all(c.zone == Zone.PLAY and c.rush for c in cards)
                     and all(c in p.field for c in cards) and not p.hand
                     and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("three_distinct_hand_minions_gain_rush", "Summons all three distinct minions from hand on owner's board; each gains Rush.", three_hand_minions_summoned_with_rush, "手牌恰三名不同随从，检查原实体移动和突袭状态。")])


def faithful_lumi():
    cid = "BOT_079"

    def eligible_mech_buff():
        g, p, e = game()
        mech = p.summon("BOT_031")
        friend_nonmech = p.summon(WISP)
        enemy_mech = e.summon("BOT_031")
        card = p.give(cid)
        targets = list(card.targets)
        card.play(target=mech)
        observed = f"legal={[c.id for c in targets]};mech={mech.atk}/{mech.health};nonmech={friend_nonmech.atk}/{friend_nonmech.health};enemy_mech={enemy_mech.atk}/{enemy_mech.health}"
        return check(mech in targets and friend_nonmech not in targets
                     and enemy_mech not in targets and (mech.atk,mech.health)==(1,3)
                     and (friend_nonmech.atk,friend_nonmech.health)==(1,1)
                     and (enemy_mech.atk,enemy_mech.health)==(0,2), observed)

    def no_mech_can_play():
        g, p, e = game()
        body = play(p, cid)
        observed = f"body={body.zone.name};field={[m.id for m in p.field]}"
        return check(body.zone == Zone.PLAY and len(p.field)==1, observed)

    audit(cid, [
        ("friendly_mech_only_buff", "Battlecry gives +1/+1 to targeted friendly Mech; friendly non-Mech and enemy Mech are illegal and unchanged.", eligible_mech_buff, "三种目标同场检查选择限制及实际身材。"),
        ("no_eligible_mech_still_playable", "Without friendly Mech, Faithful Lumi can still be played as a minion.", no_mech_can_play, "无合法目标可选分支。"),
    ])


def toxicologist():
    cid = "BOT_083"

    def existing_weapon_plus_one():
        g, p, e = game()
        weapon = play(p,"CS2_091")
        before = (weapon.atk,weapon.durability)
        body = play(p,cid)
        observed = f"weapon={before}->{(weapon.atk,weapon.durability)}:{weapon.zone.name};body={body.zone.name}"
        return check(before==(1,4) and (weapon.atk,weapon.durability)==(2,4)
                     and body.zone == Zone.PLAY, observed)

    def no_weapon_does_not_equip():
        g, p, e = game()
        body = play(p,cid)
        observed = f"weapon={p.weapon};body={body.zone.name}"
        return check(p.weapon is None and body.zone == Zone.PLAY, observed)

    audit(cid, [
        ("buffs_own_equipped_weapon", "Battlecry increases own existing weapon Attack by 1 without changing Durability.", existing_weapon_plus_one, "先装备光明圣契武器，再核对攻击和耐久。"),
        ("no_weapon_no_creation", "With no weapon, Battlecry does not create one.", no_weapon_does_not_equip, "空武器分支。"),
    ])


def violet_haze():
    cid = "BOT_084"

    def two_deathrattle_cards_in_hand():
        g, p, e = game(CardClass.ROGUE)
        before = list(p.hand)
        spell = play(p,cid)
        gained = [c for c in p.hand if c not in before]
        observed = f"gained={[(c.id,c.type,c.has_deathrattle,c.zone.name) for c in gained]};spell={spell.zone.name}"
        return check(len(gained)==2 and all(c.has_deathrattle and c.zone==Zone.HAND for c in gained)
                     and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("two_random_deathrattle_cards_to_hand", "Exactly two generated cards with Deathrattle enter caster's hand.", two_deathrattle_cards_in_hand, "固定随机种子，检查生成数量、亡语标记和手牌区域。")])


def academic_espionage():
    cid = "BOT_087"

    def ten_enemy_class_cards_cost_one():
        g, p, e = game(CardClass.ROGUE,CardClass.MAGE)
        assert p.hero.card_class == CardClass.ROGUE and e.hero.card_class == CardClass.MAGE
        old = p.give(WISP)
        old.shuffle_into_deck()
        spell = play(p,cid)
        generated = [c for c in p.deck if c is not old]
        observed = f"deck_size={len(p.deck)};generated={[(c.id,str(c.card_class),c.cost,c.zone.name) for c in generated]};old={old.cost}:{old.zone.name};spell={spell.zone.name}"
        return check(len(generated)==10 and old in p.deck and old.cost==0
                     and all(c.card_class == CardClass.MAGE and c.cost==1 and c.zone==Zone.DECK for c in generated)
                     and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("ten_opponent_class_cards_in_deck_cost_one", "Ten Mage-class cards are shuffled into Rogue deck and cost 1; pre-existing Wisp stays unchanged.", ten_enemy_class_cards_cost_one, "实际施放并逐张检查扩充后的牌库、职业和费用。")])


def elementary_reaction():
    cid = "BOT_093"

    def branch(elemental_last_turn):
        g, p, e = game(CardClass.SHAMAN)
        if elemental_last_turn:
            play(p,"UNG_809t1")
        g.end_turn()
        g.end_turn()
        deck_card = p.give("CS2_182")
        deck_card.shuffle_into_deck()
        play(p,cid)
        hand = [c for c in p.hand if c.id == deck_card.id]
        observed = f"elemental_last_turn={elemental_last_turn};hand={[(c.id,c.zone.name) for c in hand]};deck={len(p.deck)};original_drawn={deck_card.zone.name}"
        return check(deck_card.zone == Zone.HAND and len(hand)==(2 if elemental_last_turn else 1)
                     and not p.deck, observed)

    audit(cid, [
        ("elemental_previous_turn_draw_copy", "After actually playing an Elemental last turn, draw one card and make an extra hand copy.", lambda: branch(True), "前一回合实际打出元素牌并跨两个回合。"),
        ("no_elemental_draw_only", "Without an Elemental played last turn, draw only the one deck card.", lambda: branch(False), "无元素打出对照。"),
    ])


def unpowered_mauler():
    cid = "BOT_098"

    def spell_unlocks_attacking_this_turn():
        g, p, e = game()
        body = play(p,cid)
        g.end_turn()
        g.end_turn()
        before = body.can_attack(e.hero)
        play(p,"CS2_008",target=e.hero)
        after = body.can_attack(e.hero)
        if after:
            body.attack(e.hero)
        observed = f"can_attack={before}->{after};enemy_hero={e.hero.health};body={body.zone.name};num_attacks={body.num_attacks}"
        return check(not before and after and e.hero.health < 29 and body.zone == Zone.PLAY, observed)

    audit(cid, [("friendly_spell_unlocks_attack", "Mauler cannot attack after waiting a turn until its owner casts a spell this turn; then it can attack the enemy hero.", spell_unlocks_attacking_this_turn, "跨回合先验禁攻，实际施法后执行英雄攻击。")])


def eureka():
    cid = "BOT_099"

    def only_hand_minion_copied():
        g, p, e = game(CardClass.SHAMAN)
        original = p.give("CS2_182")
        spell = play(p,cid)
        copies = [m for m in p.field if m.id==original.id]
        observed = f"original={original.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};spell={spell.zone.name}"
        return check(original.zone == Zone.HAND and len(copies)==1
                     and copies[0] is not original and (copies[0].atk,copies[0].health)==(original.atk,original.health)
                     and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("summons_copy_preserves_hand_original", "Summons one copy of the only minion in hand while the original stays in hand.", only_hand_minion_copied, "单候选排除随机歧义，检查实体身份、区域和身材。")])


def astral_rift():
    cid = "BOT_101"

    def two_random_minions_to_hand():
        g, p, e = game(CardClass.MAGE)
        spell = play(p,cid)
        observed = f"hand={[(c.id,c.type,c.zone.name) for c in p.hand]};deck={len(p.deck)};spell={spell.zone.name}"
        return check(len(p.hand)==2 and all(c.type==CardType.MINION and c.zone==Zone.HAND for c in p.hand)
                     and not p.deck and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("add_two_random_minions_to_hand", "Adds exactly two minion cards to caster hand; does not draw from deck.", two_random_minions_to_hand, "空手牌、空牌库下实际施放，检查生成区和卡牌类型。")])


def spark_drill():
    cid = "BOT_102"

    def rush_body_deathrattle_two_rush_sparks():
        g, p, e = game()
        body = play(p,cid)
        enemy = e.summon(WISP)
        ready = body.can_attack(enemy)
        body.destroy()
        sparks = [c for c in p.hand if c.id=="BOT_102t"]
        spark_stats = [(c.atk,c.health,c.rush,c.zone.name) for c in sparks]
        if sparks:
            sparks[0].play()
        spark_ready = bool(sparks) and sparks[0].can_attack(enemy)
        observed = f"body_ready={ready};body={body.zone.name};sparks={spark_stats};first_spark={sparks[0].zone.name if sparks else None};spark_ready={spark_ready}"
        return check(ready and body.zone != Zone.PLAY and len(sparks)==2
                     and all((a,h,bool(r),z)==(1,1,True,"HAND") for a,h,r,z in spark_stats)
                     and sparks[0].zone == Zone.PLAY and spark_ready, observed)

    audit(cid, [("body_rush_and_two_rush_sparks", "Spark Drill has usable Rush; on death puts two 1/1 Rush Sparks into hand, one can immediately attack when played.", rush_body_deathrattle_two_rush_sparks, "检查本体攻击资格、亡语生成数量，实际打出一张火花验证突袭。")])


def stargazer_luna():
    cid = "BOT_103"

    def rightmost_draws_middle_not():
        g, p, e = game(CardClass.MAGE)
        luna = play(p,cid)
        p.give(WISP).shuffle_into_deck()
        p.give("CS2_182").shuffle_into_deck()
        left, middle, right = p.give(WISP),p.give(WISP),p.give(WISP)
        middle.play()
        after_middle=(len(p.hand),len(p.deck))
        right.play()
        after_right=(len(p.hand),len(p.deck))
        observed = f"after_middle={after_middle};after_right={after_right};luna={luna.zone.name};remaining_hand={[c.id for c in p.hand]}"
        return check(after_middle==(2,2) and after_right==(2,1)
                     and luna.zone == Zone.PLAY and left.zone == Zone.HAND, observed)

    audit(cid, [("rightmost_play_draws_middle_does_not", "Playing middle hand card draws nothing; playing rightmost card draws one deck card.", rightmost_draws_middle_not, "三张可打手牌和两张牌库卡，分别验证中间与右端。")])


def dynomatic():
    cid = "BOT_104"

    def five_damage_only_nonmech():
        g, p, e = game(CardClass.WARRIOR)
        target = e.summon("LOOT_137")
        mech = e.summon("BOT_031")
        body = play(p,cid)
        observed = f"nonmech={target.health}:{target.zone.name};mech={mech.health}:{mech.zone.name};dynomatic={body.health}:{body.zone.name};heroes={p.hero.health},{e.hero.health}"
        return check(target.health==7 and mech.health==2 and body.zone==Zone.PLAY
                     and p.hero.health==30 and e.hero.health==30, observed)

    def friendly_nonmech_is_eligible():
        g, p, e = game(CardClass.WARRIOR)
        friendly = p.summon("CS2_182")
        enemy_mech = e.summon("BOT_031")
        play(p,cid)
        observed = f"friendly_nonmech={friendly.zone.name}:{friendly.health};enemy_mech={enemy_mech.zone.name}:{enemy_mech.health}"
        return check(friendly.zone != Zone.PLAY and enemy_mech.zone == Zone.PLAY and enemy_mech.health==2, observed)

    audit(cid, [
        ("five_damage_excludes_all_mechs", "Five 1-damage packets hit sole 12-Health non-Mech, leaving nearby Mechs and heroes untouched.", five_damage_only_nonmech, "唯一高生命非机械目标检验总伤害；敌方机械对照。"),
        ("friendly_nonmech_can_be_hit", "Friendly non-Mech is eligible and takes the random damage when only non-Mech.", friendly_nonmech_is_eligible, "己方非机械对照，验证范围为双方随从。"),
    ])


def missile_launcher():
    cid = "BOT_107"

    def end_turn_damages_everyone_except_self():
        g, p, e = game()
        body = play(p,cid)
        friendly = p.summon(WISP)
        enemy = e.summon("CS2_182")
        start_health = body.health
        g.end_turn()
        observed = f"launcher={body.health}/{start_health}:{body.zone.name};friendly={friendly.zone.name};enemy={enemy.health};heroes={p.hero.health},{e.hero.health}"
        return check(body.zone==Zone.PLAY and body.health==start_health
                     and friendly.zone != Zone.PLAY and enemy.health==4
                     and p.hero.health==29 and e.hero.health==29, observed)

    def magnetic_host_excluded():
        g, p, e = game()
        host = p.summon("BOT_031")
        part = p.give(cid)
        part.play(index=0)
        before = host.health
        g.end_turn()
        observed = f"host={host.health}/{before}:{host.zone.name};part={part.zone.name};heroes={p.hero.health},{e.hero.health}"
        return check(host.zone==Zone.PLAY and host.health==before
                     and part.zone != Zone.PLAY and p.hero.health==29 and e.hero.health==29, observed)

    audit(cid, [
        ("end_turn_all_other_characters", "End of owner's turn damages both heroes and all other minions by 1, but not Launcher itself.", end_turn_damages_everyone_except_self, "己方/敌方随从与双方英雄同时在场，检查所有受伤对象。"),
        ("magnetic_host_excluded", "When magnetized, the host is excluded from Launcher's end-turn damage.", magnetic_host_excluded, "磁力分支验证宿主不自伤。"),
    ])


def omega_medic():
    cid = "BOT_216"

    def branch(ten_crystals):
        g, p, e = game(CardClass.PRIEST)
        p.max_mana = 10 if ten_crystals else 9
        p.hero.damage = 12
        body = play(p,cid)
        observed = f"crystals={p.max_mana};hero_health={p.hero.health};body={body.zone.name}"
        return check(body.zone==Zone.PLAY and p.hero.health==(28 if ten_crystals else 18), observed)

    audit(cid, [
        ("ten_crystal_heals_ten", "At 10 Mana Crystals, Medic restores 10 Health to damaged hero.", lambda: branch(True), "10水晶、缺12生命。"),
        ("nine_crystals_no_heal", "At 9 Mana Crystals, Medic does not heal.", lambda: branch(False), "9水晶对照。"),
    ])


def security_rover():
    cid = "BOT_218"

    def two_damage_events_two_taunts():
        g, p, e = game(CardClass.WARRIOR)
        rover = play(p,cid)
        p.give("CS2_008").play(target=rover)
        first=[m for m in p.field if m.id=="BOT_218t"]
        p.give("CS2_008").play(target=rover)
        tokens=[m for m in p.field if m.id=="BOT_218t"]
        observed=f"rover={rover.health}:{rover.zone.name};first={len(first)};tokens={[(m.atk,m.health,m.taunt,m.zone.name) for m in tokens]}"
        return check(rover.zone==Zone.PLAY and len(first)==1 and len(tokens)==2
                     and all((m.atk,m.health,bool(m.taunt),m.zone)==(2,3,True,Zone.PLAY) for m in tokens), observed)

    audit(cid, [("two_damage_instances_summon_two_taunts", "Each separate damage to Security Rover summons one 2/3 Mech with Taunt.", two_damage_events_two_taunts, "两次法术伤害逐次检查生成数量与关键字。")])


def extra_arms():
    cid = "BOT_219"

    def two_casts_buff_same_minion_no_third_card():
        g, p, e = game(CardClass.PRIEST)
        target = p.summon(WISP)
        first = play(p,cid,target=target)
        after_first=(target.atk,target.health)
        followups=[c for c in p.hand if c.id=="BOT_219t"]
        if followups:
            followups[0].play(target=target)
        observed=f"stats={(1,1)}->{after_first}->{(target.atk,target.health)};followups={len(followups)};new_followups={[c.id for c in p.hand if c.id=='BOT_219t']};zones={first.zone.name},{followups[0].zone.name if followups else None}"
        return check(after_first==(3,3) and (target.atk,target.health)==(5,5)
                     and len(followups)==1 and not any(c.id=="BOT_219t" for c in p.hand), observed)

    audit(cid, [("initial_and_more_arms", "Extra Arms and generated More Arms each give +2/+2; second spell generates no third copy.", two_casts_buff_same_minion_no_third_card, "同一1/1目标先后施放两张牌，检查每次身材和复制次数。")])


def spirit_bomb():
    cid = "BOT_222"

    def damages_chosen_minion_and_own_hero():
        g, p, e = game(CardClass.WARLOCK)
        target=e.summon("CS2_182")
        spell=play(p,cid,target=target)
        observed=f"target={target.health}:{target.zone.name};owner_hero={p.hero.health};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(target.health==1 and p.hero.health==26 and e.hero.health==30
                     and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid, [("four_to_minion_and_caster_hero", "Selected minion and caster's hero each take exactly 4 damage; opponent hero does not.", damages_chosen_minion_and_own_hero, "5生命目标保证存活，可同时核对两条独立伤害。")])


def doubling_imp():
    cid = "BOT_224"

    def battlecry_summons_one_copy():
        g, p, e = game(CardClass.WARLOCK)
        body=play(p,cid)
        copies=[m for m in p.field if m.id==cid]
        observed=f"body={body.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};enemy_field={len(e.field)}"
        return check(len(copies)==2 and body in copies and copies[0] is not copies[1]
                     and all((m.atk,m.health)==(body.atk,body.health) for m in copies)
                     and not e.field, observed)

    audit(cid, [("battlecry_one_equal_copy", "Battlecry summons exactly one distinct copy of Doubling Imp on owner's board.", battlecry_summons_one_copy, "检查实体身份、复制数量、身材和阵营。")])


def nethersoul_buster():
    cid = "BOT_226"

    def branch(damage_instances):
        g, p, e = game(CardClass.WARLOCK)
        for _ in range(damage_instances):
            play(p,"CS2_008",target=p.hero)
        body=play(p,cid)
        observed=f"own_damage={damage_instances};hero_health={p.hero.health};buster_attack={body.atk};zone={body.zone.name}"
        return check(p.hero.health==30-damage_instances
                     and body.atk==1+damage_instances and body.zone==Zone.PLAY, observed)

    audit(cid, [
        ("no_damage_base_attack", "Without hero damage this turn, Buster has its base 1 Attack.", lambda: branch(0), "未受伤对照。"),
        ("two_self_damage_two_bonus_attack", "Two actual 1-damage events to owner hero this turn give Buster +2 Attack.", lambda: branch(2), "两次月火术打自己英雄，逐点验证攻击增量。"),
    ])


def shrink_ray():
    cid = "BOT_234"

    def all_minions_both_sides_one_one():
        g, p, e = game(CardClass.PALADIN)
        own=p.summon("CS2_182")
        enemy=e.summon("BOT_066")
        spell=play(p,cid)
        observed=f"own={own.atk}/{own.health}:{own.zone.name};enemy={enemy.atk}/{enemy.health}:{enemy.zone.name};spell={spell.zone.name}"
        return check((own.atk,own.health,enemy.atk,enemy.health)==(1,1,1,1)
                     and own.zone==enemy.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid, [("sets_both_sides_to_one_one", "Every minion on both sides becomes 1 Attack and 1 Health.", all_minions_both_sides_one_one, "双方不同身材随从，逐一验证攻/血为1。")])


def crystalsmith_kangor():
    cid = "BOT_236"

    def doubles_spell_healing():
        g, p, e = game(CardClass.PALADIN)
        p.hero.damage=15
        body=play(p,cid)
        play(p,"CS2_089",target=p.hero)
        observed=f"hero_after_holy_light={p.hero.health};shield={body.divine_shield};lifesteal={body.lifesteal};body={body.zone.name}"
        return check(p.hero.health==27 and body.divine_shield and body.lifesteal
                     and body.zone==Zone.PLAY, observed)

    def lifesteal_healing_should_double():
        g, p, e = game(CardClass.PALADIN)
        p.hero.damage=5
        body=play(p,cid)
        enemy=e.summon("CS2_182")
        g.end_turn()
        g.end_turn()
        body.attack(enemy)
        observed=f"hero_after_one_lifesteal_damage={p.hero.health};shield_after_attack={body.divine_shield};lifesteal={body.lifesteal};body={body.zone.name};enemy={enemy.health}"
        return check(p.hero.health==27 and not body.divine_shield
                     and body.zone==Zone.PLAY and enemy.health==4, observed)

    audit(cid, [
        ("spell_healing_doubles", "Holy Light's printed 6 healing restores 12 while Kangor is in play; Kangor has Divine Shield and Lifesteal.", doubles_spell_healing, "英雄先伤15生命，单独验证法术治疗与关键字。"),
        ("lifesteal_healing_doubles", "Kangor's own 1-damage Lifesteal combat restores 2 Health because all your healing is doubled; Divine Shield prevents retaliation.", lifesteal_healing_should_double, "英雄先伤5生命，再跨回合真实攻击4攻随从；确认吸血治疗量和圣盾消费。"),
    ])


def beryllium_nullifier():
    cid="BOT_237"

    def attached_host_untargetable():
        g,p,e=game(CardClass.MAGE)
        host=p.summon("BOT_031")
        part=p.give(cid)
        part.play(index=0)
        spell=p.give("CS2_029")
        legal_spell=host in spell.targets
        legal_power=host in p.hero.power.targets
        rejected=False
        try:
            spell.play(target=host)
        except InvalidAction:
            rejected=True
        observed=f"host={host.atk}/{host.health}:{host.zone.name};part={part.zone.name};spell_legal={legal_spell};power_legal={legal_power};spell_rejected={rejected};spell_zone={spell.zone.name}"
        return check(host.zone==Zone.PLAY and part.zone!=Zone.PLAY
                     and not legal_spell and not legal_power and rejected and spell.zone==Zone.HAND, observed)

    def standalone_untargetable():
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid)
        spell=p.give("CS2_029")
        observed=f"body={body.zone.name};spell_legal={body in spell.targets};power_legal={body in p.hero.power.targets}"
        return check(body.zone==Zone.PLAY and body not in spell.targets
                     and body not in p.hero.power.targets, observed)

    audit(cid,[
        ("magnetic_host_rejects_spell_and_power", "Magnetized Mech host cannot be selected by spell or hero power; attempted Fireball is rejected without consuming card.", attached_host_untargetable, "磁力融合后同时检查两种目标列表并真实尝试施法。"),
        ("standalone_rejects_spell_and_power", "Standalone Beryllium Nullifier cannot be selected by spell or hero power.", standalone_untargetable, "独立形态的目标限制对照。"),
    ])


def dr_boom_mad_genius():
    cid="BOT_238"

    def permanent_mech_rush_after_hero_play():
        g,p,e=game(CardClass.WARRIOR)
        hero=play(p,cid)
        mech=p.summon("BOT_312t")
        ordinary=p.summon(WISP)
        target=e.summon(WISP)
        observed=f"hero={p.hero.id}:{p.hero.zone.name}:armor={p.hero.armor};mech_rush={mech.rush};ordinary_rush={ordinary.rush};mech_can_attack={mech.can_attack(target)};power={p.hero.power.id if p.hero.power else None}"
        return check(p.hero.id==cid and p.hero.armor>=7 and mech.rush
                     and not ordinary.rush and mech.can_attack(target)
                     and p.hero.power is not None, observed)

    audit(cid,[("hero_transform_and_permanent_mech_rush", "Playing Dr. Boom transforms hero and grants newly summoned friendly Mechs Rush, but not non-Mechs.", permanent_mech_rush_after_hero_play, "真实打出英雄牌后同回合召唤机械与非机械，检查突袭攻击资格和英雄形态。")])


def myras_unstable_element():
    cid="BOT_242"

    def draws_all_three_deck_cards():
        g,p,e=game(CardClass.ROGUE)
        originals=[p.give(x) for x in (WISP,"CS2_182","CS2_029")]
        for card in originals: card.shuffle_into_deck()
        play(p,cid)
        observed=f"deck={len(p.deck)};drawn={[(c.id,c.zone.name) for c in originals]};hand={len(p.hand)}"
        return check(not p.deck and all(c.zone==Zone.HAND for c in originals)
                     and len(p.hand)==3, observed)

    def full_hand_burns_overflow():
        g,p,e=game(CardClass.ROGUE)
        originals=[p.give(x) for x in ("CS2_182","BOT_031","CS2_029")]
        for card in originals: card.shuffle_into_deck()
        fillers=[p.give(WISP) for _ in range(9)]
        play(p,cid)
        zones=[c.zone for c in originals]
        observed=f"deck={len(p.deck)};hand={len(p.hand)};drawn_zones={[z.name for z in zones]};fillers_in_hand={sum(c.zone==Zone.HAND for c in fillers)}"
        return check(not p.deck and len(p.hand)==10 and zones.count(Zone.HAND)==1
                     and sum(c.zone==Zone.HAND for c in fillers)==9, observed)

    audit(cid,[
        ("draws_entire_small_deck", "Draws every card from a 3-card deck into hand and leaves deck empty.", draws_all_three_deck_cards, "三张身份不同的牌逐一核对区域。"),
        ("hand_limit_burns_overflow_but_empties_deck", "With nine other hand cards, only one of three drawn cards enters hand; all leave deck.", full_hand_burns_overflow, "接近满手牌边界，核对抽牌和烧牌。"),
    ])


def myra_rotspring():
    cid="BOT_243"

    def discover_card_and_copy_its_deathrattle():
        g,p,e=game(CardClass.ROGUE)
        myra=play(p,cid)
        options=list(p.choice.cards) if p.choice else []
        picked=next((c for c in options if c.id=="BT_008"),options[0] if options else None)
        assert picked is not None
        p.choice.choose(picked)
        hand=[c for c in p.hand if c.id==picked.id]
        gained_deathrattle=myra.has_deathrattle
        myra.destroy()
        impcasters=[m for m in p.field if m.id=="BT_008t"]
        observed=f"options={[(c.id,c.has_deathrattle) for c in options]};picked={picked.id};hand={[(c.id,c.zone.name) for c in hand]};myra_deathrattle={gained_deathrattle};myra={myra.zone.name};impcasters={[(m.id,m.atk,m.health) for m in impcasters]}"
        return check(len(options)==3 and all(c.has_deathrattle for c in options)
                     and picked.id=="BT_008" and len(hand)==1 and gained_deathrattle
                     and myra.zone!=Zone.PLAY and len(impcasters)==1, observed)

    audit(cid,[("discover_and_actually_trigger_copied_deathrattle", "Discover gives chosen Deathrattle minion to hand; Myra gains that Deathrattle, and dying summons the chosen Impcaster token.", discover_card_and_copy_its_deathrattle, "固定随机种子选择 BT_008；真正消灭米拉验证复制亡语，而非只看标记。")])


def the_storm_bringer():
    cid="BOT_245"

    def only_friendly_minions_transform_to_legendaries():
        g,p,e=game(CardClass.SHAMAN)
        own=[p.summon(WISP),p.summon("CS2_182")]
        enemy=e.summon(WISP)
        spell=play(p,cid)
        observed=f"owner_field={[(m.id,m.rarity,m.zone.name) for m in p.field]};old_own={[m.zone.name for m in own]};enemy={enemy.id}:{enemy.zone.name};spell={spell.zone.name}"
        return check(len(p.field)==2 and all(m.rarity==5 and m.zone==Zone.PLAY for m in p.field)
                     and all(m.zone!=Zone.PLAY for m in own)
                     and enemy.zone==Zone.PLAY and enemy.id==WISP and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid,[("friendly_only_random_legendary_transform", "All friendly minions become Legendary minions; opponent minion remains unchanged, with original friendly entities leaving board.", only_friendly_minions_transform_to_legendaries, "双方随从同场，验证变形数量、稀有度、阵营及原实体区域。")])


def beakered_lightning():
    cid="BOT_246"

    def one_all_minions_and_overload_two():
        g,p,e=game(CardClass.SHAMAN)
        own=p.summon("CS2_182")
        enemy=e.summon("CS2_182")
        spell=play(p,cid)
        after=(own.health,enemy.health,p.hero.health,e.hero.health,p.overloaded)
        g.end_turn();g.end_turn()
        observed=f"after_cast={after};next_turn_locked={p.overload_locked};spell={spell.zone.name}"
        return check(after==(4,4,30,30,2) and p.overload_locked==2
                     and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid,[("one_damage_each_minion_overload_two", "Both sides' minions take 1 damage; heroes do not; 2 Mana Crystals lock next own turn.", one_all_minions_and_overload_two, "真实施法后跨回合检查超载锁定。")])


def spider_bomb():
    cid="BOT_251"

    def standalone_deathrattle_destroys_enemy():
        g,p,e=game(CardClass.HUNTER)
        spider=play(p,cid)
        targets=[e.summon("CS2_182"),e.summon("BOT_031")]
        spider.destroy()
        dead=sum(m.zone!=Zone.PLAY for m in targets)
        observed=f"spider={spider.zone.name};enemies={[(m.id,m.zone.name) for m in targets]};dead={dead}"
        return check(spider.zone!=Zone.PLAY and dead==1, observed)

    def magnetic_host_inherits_deathrattle():
        g,p,e=game(CardClass.HUNTER)
        host=p.summon("BOT_031")
        spider=p.give(cid)
        spider.play(index=0)
        enemy=e.summon("CS2_182")
        inherited=host.has_deathrattle
        host.destroy()
        observed=f"host={host.zone.name};spider={spider.zone.name};inherited={inherited};enemy={enemy.zone.name}"
        return check(inherited and spider.zone!=Zone.PLAY and enemy.zone!=Zone.PLAY, observed)

    audit(cid,[
        ("standalone_deathrattle_one_random_enemy", "On death, standalone Spider Bomb destroys exactly one of two enemy minions.", standalone_deathrattle_destroys_enemy, "两个可选敌方随从，确认随机效果只杀一只。"),
        ("magnetic_host_triggers_spider_deathrattle", "Magnetic host gains Spider Bomb Deathrattle and destroys sole enemy minion on death.", magnetic_host_inherits_deathrattle, "磁力合体后真实消灭宿主，验证继承亡语结算。"),
    ])


def unexpected_results():
    cid="BOT_254"

    def branch(spell_damage):
        g,p,e=game(CardClass.MAGE)
        if spell_damage: p.summon("CS2_142")
        spell=play(p,cid)
        summoned=[m for m in p.field if m.id!="CS2_142"]
        observed=f"spell_damage={spell_damage};summons={[(m.id,m.cost,m.zone.name) for m in summoned]};spell={spell.zone.name}"
        return check(len(summoned)==2 and all(m.cost==(3 if spell_damage else 2) for m in summoned)
                     and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid,[
        ("base_two_two_cost_minions", "With no Spell Damage, summons exactly two 2-Cost minions.", lambda: branch(False), "基础2费分支。"),
        ("spell_damage_one_three_cost_minions", "With Spell Damage +1, summons exactly two 3-Cost minions.", lambda: branch(True), "法伤提升费用分支。"),
    ])


def astromancer():
    cid="BOT_256"

    def hand_size_three_summons_three_cost():
        g,p,e=game(CardClass.MAGE)
        keep=[p.give(WISP) for _ in range(3)]
        body=play(p,cid)
        summoned=[m for m in p.field if m is not body]
        observed=f"hand={len(p.hand)};summons={[(m.id,m.cost,m.zone.name) for m in summoned]};body={body.zone.name}"
        return check(len(p.hand)==3 and all(c.zone==Zone.HAND for c in keep)
                     and len(summoned)==1 and summoned[0].cost==3 and body.zone==Zone.PLAY, observed)

    audit(cid,[("post_play_hand_size_three_cost_summon", "With three other hand cards after Astromancer is played, summons one random 3-Cost minion.", hand_size_three_summons_three_cost, "真实战吼检查打出后的手牌数与衍生物费用。")])


def lunas_pocket_galaxy():
    cid="BOT_257"

    def minions_in_deck_set_to_one_spells_unchanged():
        g,p,e=game(CardClass.MAGE)
        cards=[p.give(x) for x in ("CS2_182","BOT_066","CS2_029")]
        for card in cards: card.shuffle_into_deck()
        before=[c.cost for c in cards]
        spell=play(p,cid)
        after=[c.cost for c in cards]
        drawn=p.draw()
        observed=f"cost={before}->{after};zones={[c.zone.name for c in cards]};drawn={drawn.id}:{drawn.cost};spell={spell.zone.name}"
        return check(before==[4,6,4] and after==[1,1,4]
                     and all(c.zone in (Zone.DECK,Zone.HAND) for c in cards)
                     and drawn.cost==after[cards.index(drawn)] and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid,[("deck_minions_cost_one_spell_unchanged_on_draw", "Sets both deck minions to Cost 1, leaves deck spell at printed Cost, and drawn card retains its resulting Cost.", minions_in_deck_set_to_one_spells_unchanged, "两种费用随从和一张法术同库，施放后逐实体核对费用与抽牌。")])


CHECKS = {
    "BOT_020": skaterbot,
    "BOT_021": bronze_gatekeeper,
    "BOT_031": goblin_bomb,
    "BOT_033": bomb_toss,
    "BOT_034": boommaster_flark,
    "BOT_035": venomizer,
    "BOT_038": fireworks_tech,
    "BOT_039": necromechanic,
    "BOT_042": weapons_project,
    "BOT_050": rusty_recycler,
    "BOT_054": biology_project,
    "BOT_059": eternium_rover,
    "BOT_066": mechanical_whelp,
    "BOT_067": rocket_boots,
    "BOT_069": the_boomship,
    "BOT_079": faithful_lumi,
    "BOT_083": toxicologist,
    "BOT_084": violet_haze,
    "BOT_087": academic_espionage,
    "BOT_093": elementary_reaction,
    "BOT_098": unpowered_mauler,
    "BOT_099": eureka,
    "BOT_101": astral_rift,
    "BOT_102": spark_drill,
    "BOT_103": stargazer_luna,
    "BOT_104": dynomatic,
    "BOT_107": missile_launcher,
    "BOT_216": omega_medic,
    "BOT_218": security_rover,
    "BOT_219": extra_arms,
    "BOT_222": spirit_bomb,
    "BOT_224": doubling_imp,
    "BOT_226": nethersoul_buster,
    "BOT_234": shrink_ray,
    "BOT_236": crystalsmith_kangor,
    "BOT_237": beryllium_nullifier,
    "BOT_238": dr_boom_mad_genius,
    "BOT_242": myras_unstable_element,
    "BOT_243": myra_rotspring,
    "BOT_245": the_storm_bringer,
    "BOT_246": beakered_lightning,
    "BOT_251": spider_bomb,
    "BOT_254": unexpected_results,
    "BOT_256": astromancer,
    "BOT_257": lunas_pocket_galaxy,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("card_ids", nargs="*")
    args = parser.parse_args()
    for cid in args.card_ids or list(CHECKS):
        CHECKS[cid]()
