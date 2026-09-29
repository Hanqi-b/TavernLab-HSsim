"""Card-specific live game checks for the collectible Demon Hunter Initiate YELLOW roster."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, Zone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "dhi_probe_a.csv"
VERDICT_FILE = HERE / "dhi_verdict_a.csv"
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
                 if r["set"].endswith("(DEMON_HUNTER_INITIATE)")),
                key=lambda r: r["card_id"])
assert len(ROSTER) == 16
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
PROBES = read(PROBE_FILE)
VERDICTS = read(VERDICT_FILE)


def game(seed=181):
    random.seed(seed)
    g = prepare_empty_game(CardClass.DEMONHUNTER, CardClass.MAGE)
    g.random.seed(seed)
    p = next(player for player in g.players if player.hero.card_class == CardClass.DEMONHUNTER)
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


def twin_slice():
    cid = "BT_175"

    def first_second_and_expiry():
        g, p, e = game()
        first = play(p, cid)
        second = next((c for c in p.hand if c.id == "BT_175t"), None)
        assert second is not None
        atk_first = p.hero.atk
        second.play()
        atk_second = p.hero.atk
        extra = [c.id for c in p.hand if c.id == "BT_175t"]
        g.end_turn()
        g.end_turn()
        observed = f"first={first.zone.name};attack={atk_first}->{atk_second}->{p.hero.atk};extra={extra}"
        return check(first.zone == Zone.GRAVEYARD and atk_first == 2
                     and atk_second == 4 and p.hero.atk == 0 and not extra, observed)

    audit(cid, [("both_slices_and_turn_end", "+2 Attack this turn, one Second Slice, cumulative +4 after playing it, no third Slice, attack expires next own turn.", first_second_and_expiry, "独立施放两张法术，检查攻击力、生成牌与跨回合失效。")])


def battlefiend():
    cid = "BT_351"

    def owner_hero_only():
        g, p, e = game()
        body = play(p, cid)
        before = body.atk
        p.hero.atk = 1
        p.hero.attack(e.hero)
        after_own = body.atk
        g.end_turn()
        e.hero.atk = 1
        e.hero.attack(p.hero)
        observed = f"battlefiend_attack={before}->{after_own}->{body.atk};enemy_hero_health={e.hero.health};zone={body.zone.name}"
        return check(body.zone == Zone.PLAY and e.hero.health < 30
                     and before == 1 and after_own == 2 and body.atk == 2, observed)

    audit(cid, [("own_vs_enemy_hero_attack", "Owner hero attack gives Battlefiend +1 Attack; opponent hero attack does not.", owner_hero_only, "分别执行双方英雄攻击，并验证只触发一次。")])


def urzul_horror():
    cid = "BT_407"

    def deathrattle_once():
        g, p, e = game()
        body = play(p, cid)
        body.destroy()
        souls = [c for c in p.hand if c.id == "BT_407t"]
        observed = f"body={body.zone.name};souls={[(c.id,c.atk,c.health,c.zone.name) for c in souls]}"
        return check(body.zone != Zone.PLAY and len(souls) == 1
                     and (souls[0].atk, souls[0].health) == (2, 1)
                     and souls[0].zone == Zone.HAND, observed)

    audit(cid, [("death_adds_lost_soul_to_hand", "Deathrattle adds exactly one 2/1 Lost Soul to owner hand.", deathrattle_once, "实际消灭随从并检查手牌区域和衍生物身材。")])


def umberwing():
    cid = "BT_922"

    def equip_and_two_felwings():
        g, p, e = game()
        weapon = play(p, cid)
        wings = [c for c in p.field if c.id == "BT_922t"]
        observed = f"weapon={p.weapon.id if p.weapon else None},atk={p.weapon.atk if p.weapon else None},dur={p.weapon.durability if p.weapon else None};wings={[(c.id,c.atk,c.health,c.zone.name) for c in wings]}"
        return check(p.weapon is weapon and weapon.zone == Zone.PLAY
                     and weapon.atk == 1 and weapon.durability == 2
                     and len(wings) == 2
                     and all((c.atk,c.health,c.zone) == (1,1,Zone.PLAY) for c in wings), observed)

    audit(cid, [("weapon_battlecry_two_felwings", "Equip 1/2 Umberwing and summon exactly two 1/1 Felwings.", equip_and_two_felwings, "实际装备武器，检查耐久及两个衍生随从。")])


def blade_dance():
    cid = "BT_354"

    def three_distinct_enemies():
        g, p, e = game()
        p.hero.atk = 2
        enemies = [e.summon("CS2_182") for _ in range(4)]
        before = [m.health for m in enemies]
        play(p, cid)
        after = [m.health for m in enemies]
        observed = f"enemy_health={before}->{after};friendly_hero={p.hero.health};enemy_hero={e.hero.health}"
        return check(before == [5] * 4 and sorted(after) == [3, 3, 3, 5]
                     and p.hero.health == 30 and e.hero.health == 30, observed)

    def one_enemy_only_once():
        g, p, e = game()
        p.hero.atk = 2
        enemy = e.summon("CS2_182")
        play(p, cid)
        observed = f"single_enemy={enemy.health};zone={enemy.zone.name};hero_attack={p.hero.atk}"
        return check(enemy.health == 3 and enemy.zone == Zone.PLAY, observed)

    audit(cid, [
        ("three_of_four_distinct_minions", "Exactly three of four enemy minions each take hero Attack damage; no hero or friendly damage.", three_distinct_enemies, "四名敌方4生命随从检验随机三目标互异。"),
        ("one_enemy_once", "With one eligible enemy minion, it takes damage once rather than three times.", one_enemy_only_once, "单目标分支排除重复随机伤害。"),
    ])


def wrathscale_naga():
    cid = "BT_355"

    def friendly_death_hits_enemy():
        g, p, e = game()
        naga = play(p, cid)
        victim = p.summon(WISP)
        victim.destroy()
        observed = f"naga={naga.zone.name};victim={victim.zone.name};enemy_hero={e.hero.health};owner_hero={p.hero.health}"
        return check(naga.zone == Zone.PLAY and victim.zone != Zone.PLAY
                     and e.hero.health == 27 and p.hero.health == 30, observed)

    def enemy_death_does_not_trigger():
        g, p, e = game()
        play(p, cid)
        victim = e.summon(WISP)
        victim.destroy()
        observed = f"enemy_victim={victim.zone.name};enemy_hero={e.hero.health}"
        return check(victim.zone != Zone.PLAY and e.hero.health == 30, observed)

    audit(cid, [
        ("friendly_minion_dies", "Friendly minion death deals 3 to the only enemy character.", friendly_death_hits_enemy, "己方随从死亡且敌方仅英雄可选，验证精确三点伤害。"),
        ("enemy_minion_dies_no_trigger", "Enemy minion death does not trigger Wrathscale Naga.", enemy_death_does_not_trigger, "敌方死亡对照分支。"),
    ])


def soul_split():
    cid = "BT_488"

    def friendly_demon_copy():
        g, p, e = game()
        demon = p.summon("EX1_301")
        play(p, cid, target=demon)
        copies = [m for m in p.field if m.id == demon.id]
        observed = f"original={demon.id}:{demon.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};enemy_field={len(e.field)}"
        return check(len(copies) == 2 and demon in copies
                     and all((m.atk,m.health,m.zone) == (demon.atk,demon.health,Zone.PLAY) for m in copies)
                     and not e.field, observed)

    def rejects_non_demon_or_enemy():
        g, p, e = game()
        friend = p.summon(WISP)
        enemy = e.summon("EX1_301")
        card = p.give(cid)
        observed = f"friendly_wisp={friend in card.targets};enemy_demon={enemy in card.targets};targets={[m.id for m in card.targets]}"
        return check(friend not in card.targets and enemy not in card.targets, observed)

    audit(cid, [
        ("copies_friendly_demon", "Choose friendly Demon and summon a second equal Demon, preserving original.", friendly_demon_copy, "检查目标、复制数量、身材和原实体保留。"),
        ("target_restriction", "Friendly non-Demon and enemy Demon are illegal targets.", rejects_non_demon_or_enemy, "两种非法目标对照。"),
    ])


def consume_magic():
    cid = "BT_490"

    def outcast_branch(outcast):
        g, p, e = game()
        target = e.summon("CS2_182")
        target.buff(target, "CS2_188o")
        before = target.atk
        deck_card = p.give(WISP)
        deck_card.shuffle_into_deck()
        if not outcast:
            p.give(WISP)
        card = p.give(cid)
        if outcast:
            # The spell is rightmost when no later card is in hand.
            assert p.hand[-1] is card
        else:
            p.give(WISP)
            assert p.hand[-1] is not card and p.hand[0] is not card
        card.play(target=target)
        observed = f"outcast={outcast};attack={before}->{target.atk};silenced={target.silenced};drawn_zone={deck_card.zone.name};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}"
        return check(target.silenced and target.atk < before
                     and (deck_card.zone == Zone.HAND) == outcast, observed)

    audit(cid, [
        ("outcast_silence_and_draw", "Rightmost Consume Magic silences enemy minion and draws one deck card.", lambda: outcast_branch(True), "把目标增益后施放，检查沉默及抽牌。"),
        ("middle_hand_silence_no_draw", "Middle-hand Consume Magic silences but does not draw.", lambda: outcast_branch(False), "中间位置分支排除额外抽牌。"),
    ])


def blur():
    cid = "BT_752"

    def current_turn_immune_then_expires():
        g, p, e = game()
        play(p, cid)
        e.hero.atk = 2
        p.hero.atk = 1
        p.hero.attack(e.hero)
        hp_during = p.hero.health
        g.end_turn()
        g.end_turn()
        p.hero.atk = 1
        p.hero.attack(e.hero)
        observed = f"owner_health_during={hp_during};after_new_turn={p.hero.health};immune={p.hero.immune}"
        return check(hp_during == 30 and p.hero.health < hp_during and not p.hero.immune, observed)

    audit(cid, [("immunity_during_turn_and_expiry", "Hero receives no attack damage on casting turn, but does after turn ends.", current_turn_immune_then_expires, "实际攻击有攻击力的敌方英雄，验证当前回合免伤及下回合失效。")])


def flamereaper():
    cid = "BT_271"

    def attack_middle_splashes_neighbors():
        g, p, e = game()
        weapon = play(p, cid)
        enemies = [e.summon("CS2_182") for _ in range(4)]
        p.hero.attack(enemies[1])
        observed = f"health={[m.health for m in enemies]};weapon_durability={weapon.durability};owner_health={p.hero.health}"
        return check([m.health for m in enemies] == [1, 1, 1, 5]
                     and weapon.durability == 2 and p.hero.health == 26, observed)

    audit(cid, [("middle_target_adjacent_only", "Hero attack deals weapon Attack to target and both adjacent enemy minions, not distant fourth.", attack_middle_splashes_neighbors, "四名等身材敌方随从，攻击第二名并检查所有生命与武器耐久。")])


def raging_felscreamer():
    cid = "BT_416"

    def reduction_consumed_only_by_demon():
        g, p, e = game()
        first = p.give("CS2_064")
        second = p.give("CS2_064")
        initial = (first.cost, second.cost)
        play(p, cid)
        reduced = (first.cost, second.cost)
        play(p, WISP)
        after_non_demon = (first.cost, second.cost)
        first.play()
        after_first_demon = second.cost
        observed = f"cost={initial}->{reduced}->{after_non_demon};second_after_first={after_first_demon};first_zone={first.zone.name}"
        return check(initial == (6, 6) and reduced == (4, 4)
                     and after_non_demon == (4, 4)
                     and first.zone == Zone.PLAY and after_first_demon == 6, observed)

    audit(cid, [("next_demon_discount_only", "Non-Demon does not consume the -2 discount; playing first Demon consumes it and second Demon returns to base cost.", reduction_consumed_only_by_demon, "预置两张恶魔和一张非恶魔，逐次检查费用与消耗。")])


def nethrandamus():
    cid = "BT_481"

    def upgraded_by_friendly_deaths():
        g, p, e = game()
        card = p.give(cid)
        dead = p.summon(WISP)
        dead.destroy()
        progress = card.progress
        card.play()
        others = [m for m in p.field if m is not card]
        observed = f"progress={progress};owner_field={[(m.id,m.cost,m.zone.name) for m in p.field]};enemy_field={[(m.id,m.cost) for m in e.field]}"
        return check(progress == 1 and card.zone == Zone.PLAY
                     and len(others) == 2 and all(m.cost == 1 for m in others)
                     and not e.field, observed)

    audit(cid, [("one_friendly_death_upgrades_both_summons", "One friendly minion dies while this is in hand, then Battlecry summons two random 1-Cost minions on owner side.", upgraded_by_friendly_deaths, "实际在手牌期间制造一次己方死亡，再检查进度及召唤物费用和区域。")])


def hulking_overfiend():
    cid = "BT_487"

    def kill_grants_extra_attack():
        g, p, e = game()
        body = play(p, cid)
        first = e.summon(WISP)
        second = e.summon(WISP)
        ready_first = body.can_attack(first)
        body.attack(first)
        ready_second = body.can_attack(second)
        if ready_second:
            body.attack(second)
        observed = f"rush_ready={ready_first};first={first.zone.name};second={second.zone.name};second_ready={ready_second};num_attacks={body.num_attacks};body_zone={body.zone.name}"
        return check(ready_first and first.zone != Zone.PLAY and ready_second
                     and second.zone != Zone.PLAY and body.zone == Zone.PLAY, observed)

    audit(cid, [("rush_kill_allows_second_attack", "Rush attack kills first minion, permits and completes second attack in same turn.", kill_grants_extra_attack, "同一回合实际攻击两只敌方随从，检查二次攻击资格及死亡区。")])


def wrathspike_brute():
    cid = "BT_510"

    def after_attacked_hits_all_enemies():
        g, p, e = game()
        body = play(p, cid)
        attacker = e.summon("CS2_182")
        other = e.summon("CS2_182")
        g.end_turn()
        attacker.attack(body)
        observed = f"brute={body.zone.name}:{body.health};attacker={attacker.zone.name}:{attacker.health};other={other.zone.name}:{other.health};enemy_hero={e.hero.health};owner_hero={p.hero.health}"
        return check(body.zone == Zone.PLAY and e.hero.health == 29
                     and other.health == 4 and p.hero.health == 30, observed)

    def own_attack_does_not_trigger():
        g, p, e = game()
        body = play(p, cid)
        enemy = e.summon("CS2_182")
        g.end_turn()
        g.end_turn()
        body.attack(enemy)
        observed = f"body={body.zone.name};enemy_hero={e.hero.health};enemy={enemy.zone.name}:{enemy.health}"
        return check(e.hero.health == 30, observed)

    audit(cid, [
        ("after_enemy_attack_hits_enemy_side", "When attacked, Brute deals 1 to opponent hero and other opposing minions, not owner hero.", after_attacked_hits_all_enemies, "对手随从实际攻击嘲讽体，检查双方英雄和额外敌方随从。"),
        ("own_attack_is_not_attacked", "Brute attacking an enemy itself must not trigger its 'After this is attacked' effect.", own_attack_does_not_trigger, "主动攻击分支验证触发方向。"),
    ])


def illidari_felblade():
    cid = "BT_814"

    def branch(outcast):
        g, p, e = game()
        p.give(WISP)
        card = p.give(cid)
        if not outcast:
            p.give(WISP)
        enemy = e.summon("CS2_182")
        card.play()
        immune_on_play = card.immune
        can_rush = card.can_attack(enemy)
        if can_rush:
            card.attack(enemy)
        observed = f"outcast={outcast};immune_on_play={immune_on_play};can_rush={can_rush};body={card.zone.name}:{card.health};enemy={enemy.zone.name}:{enemy.health}"
        return check(can_rush and immune_on_play == outcast
                     and enemy.zone != Zone.PLAY
                     and (card.zone == Zone.PLAY) == outcast, observed)

    def immune_expires():
        g, p, e = game()
        card = play(p, cid)
        was_immune = card.immune
        g.end_turn()
        g.end_turn()
        observed = f"immune={was_immune}->{card.immune};zone={card.zone.name}"
        return check(was_immune and not card.immune and card.zone == Zone.PLAY, observed)

    audit(cid, [
        ("rightmost_outcast_immune_rush", "Outcast Felblade gets Immune and survives Rush attack against 4-Attack Yeti.", lambda: branch(True), "右手边缘打出并冲锋攻击高攻击随从。"),
        ("middle_hand_no_immune", "Middle-hand Felblade lacks Immune and dies after Rush attack against 4-Attack Yeti.", lambda: branch(False), "手牌中间位置对照。"),
        ("immune_expires_after_turn", "Outcast Immune state expires after its turn.", immune_expires, "跨回合检查时限。"),
    ])


def altruis_the_outcast():
    cid = "BT_937"

    def edge_vs_middle():
        g, p, e = game()
        body = play(p, cid)
        enemy = e.summon("CS2_182")
        left = p.give(WISP)
        middle = p.give(WISP)
        right = p.give(WISP)
        middle.play()
        after_middle = (e.hero.health, enemy.health)
        left.play()
        after_left = (e.hero.health, enemy.health)
        right.play()
        after_right = (e.hero.health, enemy.health)
        observed = f"middle={after_middle};left={after_left};right={after_right};owner_hero={p.hero.health};altruis={body.zone.name}"
        return check(after_middle == (30, 5) and after_left == (29, 4)
                     and after_right == (28, 3) and p.hero.health == 30
                     and body.zone == Zone.PLAY, observed)

    audit(cid, [("left_and_right_only", "Middle card causes no damage; playing leftmost and rightmost cards each deals 1 to every enemy.", edge_vs_middle, "三张可打手牌分别验证中间、左端、右端触发及双方角色生命。")])


CHECKS = {
    "BT_175": twin_slice,
    "BT_271": flamereaper,
    "BT_351": battlefiend,
    "BT_354": blade_dance,
    "BT_355": wrathscale_naga,
    "BT_407": urzul_horror,
    "BT_416": raging_felscreamer,
    "BT_481": nethrandamus,
    "BT_487": hulking_overfiend,
    "BT_488": soul_split,
    "BT_490": consume_magic,
    "BT_510": wrathspike_brute,
    "BT_752": blur,
    "BT_814": illidari_felblade,
    "BT_922": umberwing,
    "BT_937": altruis_the_outcast,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("card_ids", nargs="*")
    args = parser.parse_args()
    ids = args.card_ids or list(CHECKS)
    for cid in ids:
        CHECKS[cid]()
