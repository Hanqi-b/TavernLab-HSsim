"""Card-specific live probes for the first 44 original ICECROWN YELLOW collectibles.

This file intentionally owns only ICC_018 through ICC_093.  Each card gets its
own live-game case(s); a generic play smoke is never used as a GREEN verdict.
"""

import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import InvalidAction

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import MOONFIRE, MURLOC, WISP, prepare_empty_game  # noqa: E402


BASELINE = HERE / "icecrown_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "icc_probe_a.csv"
VERDICT_OUT = HERE / "icc_verdict_a.csv"
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
OWN_ROWS = BASE_ROWS[:44]
OWN_IDS = [row["card_id"] for row in OWN_ROWS]
assert OWN_IDS[0] == "ICC_018" and OWN_IDS[-1] == "ICC_093" and len(OWN_IDS) == 44
MASTER_BY_ID = {row["card_id"]: row for row in read_csv(MASTER)}
QUALITY_BY_ID = {row["card_id"]: row for row in read_csv(QUALITY)}
PROBE_ROWS = [row for row in read_csv(PROBE_OUT) if row["card_id"] not in OWN_IDS]
VERDICT_ROWS = [row for row in read_csv(VERDICT_OUT) if row["card_id"] not in OWN_IDS]


def new_game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=901):
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
    print(f"{card_id} {case_id}: {outcome} — {observed}")
    return outcome


def finish_card(card_id, blocker=None, extra_notes=""):
    rows = [row for row in PROBE_ROWS if row["card_id"] == card_id]
    assert rows and len({row["case_id"] for row in rows}) == len(rows)
    errors = [row for row in rows if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in rows if row["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(
            f"{row['case_id']} expected=[{row['expected']}] actual=[{row['observed']}]"
            for row in errors
        )
    elif unresolved:
        status = "YELLOW"
        reason = "关键行为运行未决：" + "; ".join(
            f"{row['case_id']}={row['observed']}" for row in unresolved
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "本轮逐卡行为用例全部通过：" + "; ".join(
            f"{row['case_id']}={row['observed']}" for row in rows
        )
    master = MASTER_BY_ID[card_id]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != card_id]
    notes = metadata(card_id)
    if extra_notes:
        notes += f"; audit_note={extra_notes}"
    VERDICT_ROWS.append({
        "card_id": card_id, "status": status,
        "mechanic_scope": master["mechanics"], "reason": reason,
        "probe_file": PROBE_OUT.name, "notes": notes,
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{card_id}: {status} ({len(rows)} cases)")
    return status


def audit(card_id, tests, blocker=None, extra_notes=""):
    PROBE_ROWS[:] = [row for row in PROBE_ROWS if row["card_id"] != card_id]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != card_id]
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    for case_id, expected, func, notes in tests:
        record(card_id, case_id, expected, func, notes)
    return finish_card(card_id, blocker, extra_notes)


def phantom_freebooter():
    cid = "ICC_018"

    def gains_weapon_stats():
        g = new_game(); p = g.player1
        weapon = play(p, "CS2_106")
        freebooter = play(p, cid)
        observed = f"weapon={weapon.atk}/{weapon.durability};freebooter={freebooter.atk}/{freebooter.health}/{freebooter.max_health}"
        return checked(observed, (freebooter.atk, freebooter.health, freebooter.max_health) == (6, 5, 5))

    def no_weapon_keeps_printed_stats():
        g = new_game(); p = g.player1
        freebooter = play(p, cid)
        return checked(f"freebooter={freebooter.atk}/{freebooter.health}", (freebooter.atk, freebooter.health) == (3, 3))

    return audit(cid, [
        ("weapon_stats", "Gain attack equal to weapon Attack and Health equal to weapon Durability.", gains_weapon_stats, "装备实际武器后检查攻击力、当前生命和最大生命。"),
        ("no_weapon", "Without a weapon the minion remains 3/3.", no_weapon_keeps_printed_stats, "无武器分支作为条件对照。"),
    ])


def conditional_skeleton(cid, token_id, token_stats, label):
    def opponent_turn_summons():
        g = new_game(); p, e = g.player1, g.player2
        source = play(p, cid)
        g.end_turn()
        source.destroy()
        tokens = [m for m in p.field if m.id == token_id]
        observed = f"current={g.current_player.name};source={source.zone.name};tokens={[(m.id,m.atk,m.health) for m in tokens]}"
        return checked(observed, len(tokens) == 1 and (tokens[0].atk, tokens[0].health) == token_stats and source.zone == Zone.GRAVEYARD)

    def own_turn_no_summon():
        g = new_game(); p = g.player1
        source = play(p, cid)
        source.destroy()
        tokens = [m for m in p.field if m.id == token_id]
        return checked(f"source={source.zone.name};tokens={len(tokens)}", not tokens and source.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("opponent_turn", f"When it dies during the opponent's turn, summon one {label}.", opponent_turn_summons, "真实切换到对手回合后销毁本体，核对己方召唤物身份和身材。"),
        ("own_turn", "When it dies during your own turn, the conditional Deathrattle does not summon.", own_turn_no_summon, "己方回合销毁作为条件不满足对照。"),
    ])


def skelemancer():
    return conditional_skeleton("ICC_019", "ICC_019t", (8, 8), "8/8 Skeleton")


def exploding_bloatbat():
    cid = "ICC_021"

    def damages_only_enemy_minions():
        g = new_game(); p, e = g.player1, g.player2
        friendly = summon(p, "CS2_182")
        first = summon(e, "CS2_182")
        second = summon(e, "CS2_182")
        source = play(p, cid)
        source.destroy()
        observed = f"friendly={friendly.health};enemy={[first.health, second.health]};source={source.zone.name}"
        return checked(observed, friendly.health == 5 and first.health == 3 and second.health == 3 and source.zone == Zone.GRAVEYARD)

    return audit(cid, [("deathrattle_enemy_aoe", "Deathrattle deals exactly 2 damage to every enemy minion and does not damage friendly minions.", damages_only_enemy_minions, "双方各放置两个可存活目标，逐一检查伤害和区域。")])


def rattling_rascal():
    cid = "ICC_025"

    def battlecry_and_deathrattle():
        g = new_game(); p, e = g.player1, g.player2
        source = play(p, cid)
        own = [m for m in p.field if m.id == "ICC_025t"]
        assert len(own) == 1 and (own[0].atk, own[0].health) == (5, 5), own
        source.destroy()
        enemy = [m for m in e.field if m.id == "ICC_025t"]
        observed = f"own_token={len(own)};enemy_token={len(enemy)};source={source.zone.name}"
        return checked(observed, len(enemy) == 1 and (enemy[0].atk, enemy[0].health) == (5, 5) and source.zone == Zone.GRAVEYARD)

    return audit(cid, [("battlecry_and_deathrattle", "Battlecry gives your side one 5/5 Skeleton; Deathrattle gives the opponent one 5/5 Skeleton.", battlecry_and_deathrattle, "实际打出并销毁本体，分别核对双方区域。")])


def grim_necromancer():
    cid = "ICC_026"

    def summons_two_own_skeletons():
        g = new_game(); p, e = g.player1, g.player2
        source = play(p, cid)
        own = [m for m in p.field if m.id == "ICC_026t"]
        observed = f"own={[(m.atk,m.health) for m in own]};enemy={len([m for m in e.field if m.id == 'ICC_026t'])}"
        return checked(observed, len(own) == 2 and all((m.atk, m.health) == (1, 1) for m in own) and not [m for m in e.field if m.id == "ICC_026t"])

    return audit(cid, [("battlecry_two_skeletons", "Battlecry summons exactly two 1/1 Skeletons for the controller.", summons_two_own_skeletons, "以双方场区分别计数，确认没有错误地给对手召唤。")])


def bone_drake():
    cid = "ICC_027"

    def adds_dragon_after_death():
        g = new_game(); p = g.player1
        source = play(p, cid)
        source.destroy()
        dragons = [c for c in p.hand if Race.DRAGON in c.races]
        observed = f"source={source.zone.name};hand={[c.id for c in p.hand]};dragons={[c.id for c in dragons]}"
        return checked(observed, source.zone == Zone.GRAVEYARD and len(dragons) == 1 and dragons[0].type == CardType.MINION)

    return audit(cid, [("deathrattle_random_dragon", "Deathrattle adds one random Dragon minion to hand.", adds_dragon_after_death, "运行真实随机分支并检查新增手牌的 Race.DRAGON 与随从类型。")])


def sunborne_valkyr():
    cid = "ICC_028"

    def buffs_only_adjacent():
        g = new_game(); p = g.player1
        left = summon(p, "CS2_182")
        source = play(p, cid, index=1)
        right = summon(p, "CS2_182")
        # The battlecry resolves before a later summon, so use a second setup with
        # the source inserted between already present minions.
        g = new_game(); p = g.player1
        left = summon(p, "CS2_182")
        right = summon(p, "CS2_182")
        source = play(p, cid, index=1)
        observed = f"field={[m.id for m in p.field]};stats={[ (m.atk,m.health) for m in p.field ]}"
        return checked(observed, p.field[0] is left and p.field[2] is right and p.field[1] is source and left.health == 7 and right.health == 7 and source.health == 4)

    return audit(cid, [("adjacent_health_only", "Battlecry gives exactly +2 Health to both adjacent minions and leaves the Val'kyr unchanged.", buffs_only_adjacent, "通过 index=1 将本体置于两个既有随从之间，核对边界目标。")])


def cobalt_scalebane():
    cid = "ICC_029"

    def end_turn_buffs_one_other_random_minion():
        g = new_game(); p = g.player1
        source = play(p, cid)
        first = summon(p, "CS2_182")
        second = summon(p, "CS2_182")
        before = {id(first): first.atk, id(second): second.atk, id(source): source.atk}
        g.end_turn()
        buffed = [m for m in (first, second) if m.atk == before[id(m)] + 3]
        observed = f"source={source.atk};others={first.atk}/{second.atk};buffed={len(buffed)}"
        return checked(observed, source.atk == before[id(source)] and len(buffed) == 1 and all(m.atk in (before[id(m)], before[id(m)] + 3) for m in (first, second)))

    return audit(cid, [("end_turn_random_other", "At the end of your turn, exactly one other random friendly minion gains +3 Attack.", end_turn_buffs_one_other_random_minion, "两个合法的其他目标用于核对随机目标和排除本体。")])


def night_howler():
    cid = "ICC_031"

    def gains_two_attack_each_damage_event():
        g = new_game(); p = g.player1
        source = play(p, cid)
        play(p, MOONFIRE, target=source)
        first = source.atk
        play(p, MOONFIRE, target=source)
        observed = f"attack_after_one={first};attack_after_two={source.atk};health={source.health}"
        return checked(observed, first == 5 and source.atk == 7 and source.health == 2)

    return audit(cid, [("damage_trigger_stacks", "Each separate damage event gives Night Howler +2 Attack.", gains_two_attack_each_damage_event, "用两次实际法术伤害拆分验证触发次数和攻击力累计。")])


def venomancer():
    cid = "ICC_032"

    def poisonous_kills_large_target_in_combat():
        g = new_game(); p, e = g.player1, g.player2
        source = summon(p, cid)
        target = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        source.attack(target)
        observed = f"source={source.zone.name};target={target.zone.name};target_health={target.health}"
        return checked(observed, source.zone == Zone.PLAY and target.zone == Zone.GRAVEYARD)

    return audit(cid, [("poisonous_combat", "Poisonous destroys an enemy minion in combat even when its remaining Health exceeds ordinary damage.", poisonous_kills_large_target_in_combat, "真实攻击一个4/5目标，确认 Poisonous 的致死效果和双方区域。")])


def arrogant_crusader():
    return conditional_skeleton("ICC_034", "ICC_900t", (2, 2), "2/2 Ghoul")


def righteous_protector():
    cid = "ICC_038"

    def taunt_and_divine_shield():
        g = new_game(); p, e = g.player1, g.player2
        protector = summon(p, cid)
        attacker = summon(e, WISP)
        assert protector.taunt and protector.divine_shield
        g.end_turn()
        attacker.attack(protector)
        observed = f"protector={protector.health};divine_shield={protector.divine_shield};hero={p.hero.health};attacker={attacker.zone.name}"
        return checked(observed, protector.zone == Zone.PLAY and protector.health == 1 and not protector.divine_shield and p.hero.health == 30)

    return audit(cid, [("taunt_divine_shield_combat", "Taunt forces the attack into the minion and Divine Shield absorbs the first damage.", taunt_and_divine_shield, "让敌方随从实际攻击并检查目标、护盾和英雄生命。")])


def dark_conviction():
    cid = "ICC_039"

    def sets_enemy_exactly_three_three():
        g = new_game(); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        spell = play(p, cid, target)
        observed = f"target={target.atk}/{target.health}/{target.max_health};spell={spell.zone.name}"
        return checked(observed, (target.atk, target.health, target.max_health) == (3, 3, 3) and spell.zone == Zone.GRAVEYARD)

    def sets_friendly_exactly_three_three():
        g = new_game(); p = g.player1
        target = summon(p, "CS2_182")
        play(p, cid, target)
        return checked(f"target={target.atk}/{target.health}/{target.max_health}", (target.atk, target.health, target.max_health) == (3, 3, 3))

    return audit(cid, [
        ("enemy_exact_set", "A legal enemy minion becomes exactly 3/3.", sets_enemy_exactly_three_three, "敌方4/5目标核对设值而非增量。"),
        ("friendly_exact_set", "A legal friendly minion becomes exactly 3/3.", sets_friendly_exactly_three_three, "己方目标核对同一效果。"),
    ])


def defile():
    cid = "ICC_041"

    def repeats_through_staggered_deaths():
        g = new_game(); p, e = g.player1, g.player2
        one = summon(p, WISP)  # 1 Health: dies on the first pass.
        two = summon(p, "GVG_093")  # 2 Health: dies on the second pass.
        three = summon(p, "EX1_556")  # 3 Health and a Deathrattle token.
        four = summon(p, "CS2_182")  # survives all three observed passes.
        enemy = summon(e, "CS2_182")
        play(p, cid)
        observed = f"one={one.zone.name};two={two.zone.name};three={three.zone.name};four={four.zone.name}/{four.health};enemy={enemy.zone.name}/{enemy.health};field={[m.id for m in p.field]}"
        # The 1/1, 0/2 and 2/3 are consumed one pass at a time.  Harvest
        # Golem's Deathrattle summons a 2/1 Damaged Golem; that new death
        # causes another pass, so the two 4/5 minions are also consumed.
        tokens = [card for card in g if getattr(card, "id", None) == "skele21"]
        observed += f";damaged_golem_entities={len(tokens)}"
        return checked(observed, one.zone == Zone.GRAVEYARD and two.zone == Zone.GRAVEYARD and three.zone == Zone.GRAVEYARD and four.zone == Zone.GRAVEYARD and enemy.zone == Zone.GRAVEYARD and tokens)

    def stops_without_a_death():
        g = new_game(); p, e = g.player1, g.player2
        friendly = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        play(p, cid)
        observed = f"friendly={friendly.health};enemy={enemy.health};field={len(p.field)}"
        return checked(observed, friendly.health == 4 and enemy.health == 4 and friendly.zone == Zone.PLAY and enemy.zone == Zone.PLAY)

    return audit(cid, [
        ("recursive_staggered_deaths", "Defile repeats through staggered 1/2/3 Health deaths, processes the Deathrattle summon, and eventually consumes the two 4/5 minions after the summoned 2/1 also dies.", repeats_through_staggered_deaths, "以1/1、0/2、2/3亡语和4/5组成阶梯场面，观察递归、死亡处理和新召唤物。"),
        ("no_death_stop", "When no minion dies on the first pass, Defile does not cast again.", stops_without_a_death, "两个4/5目标作为无死亡停止条件。"),
    ])


def fatespinner():
    cid = "ICC_047"

    def damage_deathrattle_branch():
        g = new_game(); p, e = g.player1, g.player2
        play(p, cid, choose="ICC_047b")
        source = next(card for card in p.field if card.id == "ICC_047t")
        own = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        source.destroy()
        observed = f"source={source.zone.name};own={own.zone.name}/{own.health};enemy={enemy.zone.name}/{enemy.health}"
        return checked(observed, source.zone == Zone.GRAVEYARD and own.zone == Zone.PLAY and enemy.zone == Zone.PLAY and own.health == 2 and enemy.health == 2)

    def buff_deathrattle_branch():
        g = new_game(); p, e = g.player1, g.player2
        play(p, cid, choose="ICC_047a")
        source = next(card for card in p.field if card.id == "ICC_047t")
        own = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        source.destroy()
        observed = f"source={source.zone.name};own={own.atk}/{own.health};enemy={enemy.atk}/{enemy.health}"
        return checked(observed, source.zone == Zone.GRAVEYARD and own.atk == 6 and own.health == 7 and enemy.atk == 6 and enemy.health == 7)

    def damage_branch_same_batch_death():
        g = new_game(); p, e = g.player1, g.player2
        play(p, cid, choose="ICC_047b")
        source = next(card for card in p.field if card.id == "ICC_047t")
        own = summon(p, WISP)
        enemy = summon(e, WISP)
        source.destroy()
        observed = f"source={source.zone.name};own={own.zone.name};enemy={enemy.zone.name}"
        return checked(observed, source.zone == Zone.GRAVEYARD and own.zone == Zone.GRAVEYARD and enemy.zone == Zone.GRAVEYARD)

    def growth_same_batch_does_not_rescue_wisp():
        g = new_game(); p = g.player1
        play(p, cid, choose="ICC_047a")
        source = next(card for card in p.field if card.id == "ICC_047t")
        source.hit(source.health - 1)
        wisp = summon(p, WISP)
        play(p, "ICC_064")
        observed = f"source={source.zone.name};source_health={source.health};wisp={wisp.zone.name}/{wisp.health};field={[card.id for card in p.field]}"
        return checked(observed, source.zone == Zone.GRAVEYARD and wisp.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("choose_buff_then_death", "Choosing ICC_047a (Growth) makes the Deathrattle give all minions +2/+2 when the source dies.", buff_deathrattle_branch, "依据 CardDefs 中 Growth 的真实文本选择 a 分支并销毁本体。"),
        ("choose_damage_then_death", "Choosing ICC_047b (Decay) makes the Deathrattle deal 3 to all minions when the source dies.", damage_deathrattle_branch, "依据 CardDefs 中 Decay 的真实文本选择 b 分支并销毁本体。"),
        ("damage_same_batch_death", "The damage Deathrattle resolves against a same-batch 1/1 death on both sides.", damage_branch_same_batch_death, "用双方1/1目标核对亡语实际伤害和同批次死亡处理。"),
        ("growth_same_batch_death", "A friendly 1/1 that dies in the same Blood Razor damage batch is not rescued by the Growth Deathrattle.", growth_same_batch_does_not_rescue_wisp, "先将 Growth 分支降至1生命，再用 Blood Razor 战吼同时击中本体和 Wisp，验证 DEATH-001 同批死亡顺序。"),
    ], extra_notes="两个选项均通过实际 Morph 后的场上实体死亡结算；Growth 分支另外覆盖 Blood Razor 同批次死亡顺序。")


def toxic_arrow():
    cid = "ICC_049"

    def survives_and_gets_poisonous():
        g = new_game(); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        play(p, cid, target)
        observed = f"target={target.health};poisonous={target.poisonous};zone={target.zone.name}"
        return checked(observed, target.health == 3 and target.poisonous and target.zone == Zone.PLAY)

    def lethal_target_does_not_get_poisonous():
        g = new_game(); p, e = g.player1, g.player2
        target = summon(e, WISP)
        play(p, cid, target)
        return checked(f"target_zone={target.zone.name};poisonous={target.poisonous}", target.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("survivor_poisonous", "A target surviving 2 damage gains Poisonous.", survives_and_gets_poisonous, "4/5目标存活后检查生命和关键关键词。"),
        ("lethal_no_poison", "A target killed by the 2 damage is not left as a Poisonous minion.", lethal_target_does_not_get_poisonous, "1/1目标致死分支检查死亡区域。"),
    ])


def webweave():
    cid = "ICC_050"

    def summons_two_poisonous_spiders():
        g = new_game(); p = g.player1
        spell = play(p, cid)
        spiders = [m for m in p.field if m.id == "ICC_832t3"]
        observed = f"spiders={[(m.atk,m.health,m.poisonous) for m in spiders]};spell={spell.zone.name}"
        return checked(observed, len(spiders) == 2 and all((m.atk, m.health) == (1, 2) and m.poisonous for m in spiders) and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("two_poisonous_spiders", "Spell summons exactly two 1/2 Poisonous Spiders.", summons_two_poisonous_spiders, "核对召唤物身份、身材、Poisonous 和法术区域。")])


def druid_of_swarm():
    cid = "ICC_051"

    def poisonous_form():
        g = new_game(); p = g.player1
        play(p, cid, choose="ICC_051a")
        source = next(card for card in p.field if card.id == "ICC_051t")
        return checked(f"id={source.id};stats={source.atk}/{source.health};poisonous={source.poisonous};taunt={source.taunt}", source.id == "ICC_051t" and (source.atk, source.health) == (1, 2) and source.poisonous and not source.taunt)

    def taunt_form():
        g = new_game(); p = g.player1
        play(p, cid, choose="ICC_051b")
        source = next(card for card in p.field if card.id == "ICC_051t2")
        return checked(f"id={source.id};stats={source.atk}/{source.health};poisonous={source.poisonous};taunt={source.taunt}", source.id == "ICC_051t2" and (source.atk, source.health) == (1, 5) and source.taunt and not source.poisonous)

    return audit(cid, [
        ("choose_poisonous", "Choose One transforms into a 1/2 Poisonous minion.", poisonous_form, "真实选择第一分支并检查变形后的身份和关键词。"),
        ("choose_taunt", "Choose One transforms into a 1/5 Taunt minion.", taunt_form, "真实选择第二分支并检查变形后的身份和关键词。"),
    ])


def play_dead():
    cid = "ICC_052"

    def triggers_friendly_deathrattle():
        g = new_game(); p = g.player1
        target = summon(p, "ICC_065")
        spell = play(p, cid, target)
        skeletons = [c for c in p.hand if c.id == "ICC_026t"]
        observed = f"target={target.zone.name};skeletons={[c.id for c in skeletons]};spell={spell.zone.name}"
        return checked(observed, target.zone == Zone.PLAY and len(skeletons) == 2 and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("trigger_bone_baron", "Triggers a targeted friendly minion's Deathrattle without destroying the minion itself.", triggers_friendly_deathrattle, "以 Bone Baron 的实际亡语作为可观测手牌结果，并检查目标仍在场。")])


def spreading_plague():
    cid = "ICC_054"

    def repeats_when_opponent_has_more():
        g = new_game(); p, e = g.player1, g.player2
        summon(e, WISP); summon(e, WISP)
        play(p, cid)
        scarabs = [m for m in p.field if m.id == "ICC_832t4"]
        observed = f"friendly={len(p.field)};enemy={len(e.field)};scarabs={len(scarabs)}"
        return checked(observed, len(scarabs) == 2 and all(m.taunt and (m.atk, m.health) == (1, 5) for m in scarabs))

    def stops_when_counts_not_less():
        g = new_game(); p, e = g.player1, g.player2
        summon(e, WISP)
        play(p, cid)
        scarabs = [m for m in p.field if m.id == "ICC_832t4"]
        return checked(f"enemy={len(e.field)};scarabs={len(scarabs)}", len(scarabs) == 1)

    def stops_at_full_board_after_one_scarab():
        g = new_game(); p, e = g.player1, g.player2
        for _ in range(6):
            summon(p, WISP)
        for _ in range(7):
            summon(e, WISP)
        play(p, cid)
        scarabs = [m for m in p.field if m.id == "ICC_832t4"]
        observed = f"friendly={len(p.field)};enemy={len(e.field)};scarabs={len(scarabs)}"
        return checked(observed, len(p.field) == 7 and len(e.field) == 7 and len(scarabs) == 1)

    def dormant_slot_does_not_recurse_forever():
        g = new_game(CardClass.DRUID, CardClass.MAGE); p, e = g.player1, g.player2
        for _ in range(5):
            summon(p, "CS2_182")
        dormant = summon(p, "BT_009")
        assert dormant.dormant and len(p.field) == 6, (dormant.id, dormant.dormant, len(p.field))
        for _ in range(7):
            summon(e, WISP)
        try:
            play(p, cid)
        except RecursionError as exc:
            raise AssertionError(
                f"BOARD-001 recursion after first Scarab;field={[card.id for card in p.field]}"
            ) from exc
        scarabs = [m for m in p.field if m.id == "ICC_832t4"]
        observed = f"friendly={len(p.field)};enemy={len(e.field)};scarabs={len(scarabs)};dormant={dormant.dormant}"
        return checked(observed, len(scarabs) == 1 and len(p.field) == 7)

    return audit(cid, [
        ("opponent_more_repeats", "Summons a second Scarab while the opponent still has more minions.", repeats_when_opponent_has_more, "敌方两只、己方零只的实际场面核对重复条件。"),
        ("not_more_stops", "Stops after one Scarab when the opponent does not have more minions after the first summon.", stops_when_counts_not_less, "敌方一只作为不重复分支。"),
        ("full_board_cap", "With one remaining friendly slot, the effect summons one Scarab and does not create an eighth minion.", stops_at_full_board_after_one_scarab, "双方场区接近上限，检查召唤上限和重复效果的终止。"),
        ("dormant_slot_recursion", "A Dormant minion still occupies a board slot; the effect must stop after filling the last slot.", dormant_slot_does_not_recurse_forever, "五个活动随从加一个真实 Dormant BT_009，再对七个敌方随从施放，限制 RecursionError 风险并记录 BOARD-001。"),
    ])


def drain_soul():
    cid = "ICC_055"

    def damages_minion_and_lifesteals():
        g = new_game(); p, e = g.player1, g.player2
        p.hero.damage = 10
        target = summon(e, "CS2_182")
        spell = play(p, cid, target)
        observed = f"target={target.health};hero={p.hero.health};spell={spell.zone.name}"
        return checked(observed, target.health == 3 and p.hero.health == 22 and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("damage_and_lifesteal", "Deals 2 to a minion and restores exactly 2 Health to the caster's hero.", damages_minion_and_lifesteals, "预先让英雄受伤，分别检查目标生命、英雄生命和法术区域。")])


def cryostasis():
    cid = "ICC_056"

    def buffs_and_freezes_target():
        g = new_game(); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        spell = play(p, cid, target)
        observed = f"target={target.atk}/{target.health};frozen={target.frozen};spell={spell.zone.name}"
        return checked(observed, (target.atk, target.health, target.max_health) == (7, 8, 8) and target.frozen and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("buff_and_freeze", "Gives a minion +3/+3 and freezes it.", buffs_and_freezes_target, "对4/5目标核对增量、冻结和区域。")])


def brrrloc():
    cid = "ICC_058"

    def freezes_enemy():
        g = new_game(); p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        source = play(p, cid, target)
        return checked(f"target_frozen={target.frozen};source={source.zone.name}", target.frozen and source.zone == Zone.PLAY)

    return audit(cid, [("freeze_enemy", "Battlecry freezes a chosen enemy character/minion.", freezes_enemy, "对敌方随从进行实际目标选择并检查 Frozen 状态。")])


def mountainfire_armor():
    return conditional_armor("ICC_062")


def conditional_armor(cid):
    def opponent_turn_armor():
        g = new_game(); p = g.player1
        source = play(p, cid)
        g.end_turn(); source.destroy()
        return checked(f"armor={p.hero.armor};source={source.zone.name}", p.hero.armor == 6 and source.zone == Zone.GRAVEYARD)

    def own_turn_no_armor():
        g = new_game(); p = g.player1
        source = play(p, cid); source.destroy()
        return checked(f"armor={p.hero.armor};source={source.zone.name}", p.hero.armor == 0 and source.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("opponent_turn_gain_armor", "Deathrattle during opponent's turn grants 6 Armor.", opponent_turn_armor, "切换到对手回合后销毁并检查护甲。"),
        ("own_turn_no_armor", "Deathrattle during own turn does not grant the conditional Armor.", own_turn_no_armor, "己方回合死亡作为条件不满足对照。"),
    ])


def blood_razor():
    cid = "ICC_064"

    def battlecry_and_deathrattle_aoe():
        g = new_game(); p, e = g.player1, g.player2
        own = summon(p, "CS2_182"); enemy = summon(e, "CS2_182")
        weapon = play(p, cid)
        assert own.health == 4 and enemy.health == 4, (own.health, enemy.health)
        weapon.destroy()
        observed = f"own={own.health};enemy={enemy.health};weapon={weapon.zone.name}"
        return checked(observed, own.health == 3 and enemy.health == 3 and weapon.zone == Zone.GRAVEYARD)

    def durability_zero_triggers_deathrattle():
        g = new_game(CardClass.WARRIOR, CardClass.WARRIOR); p, e = g.player1, g.player2
        own = summon(p, "CS2_182")
        first = summon(e, "CS2_200")
        second = summon(e, "CS2_200")
        weapon = play(p, cid)
        p.hero.attack(first)
        assert weapon.durability == 1, weapon.durability
        # A hero cannot attack twice in one turn.  Advance a complete turn
        # pair so the second durability loss is an actual legal attack.
        g.end_turn(); g.end_turn()
        p.hero.attack(second)
        observed = f"weapon={weapon.zone.name};own={own.health};first={first.zone.name}/{first.health};second={second.zone.name}/{second.health}"
        return checked(observed, weapon.zone == Zone.GRAVEYARD and own.health == 3 and first.zone == Zone.PLAY and second.zone == Zone.PLAY and first.health == 3 and second.health == 3)

    def replacement_triggers_old_weapon_deathrattle():
        g = new_game(CardClass.WARRIOR, CardClass.WARRIOR); p, e = g.player1, g.player2
        own = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        old_weapon = play(p, cid)
        new_weapon = play(p, "CS2_106")
        observed = f"old={old_weapon.zone.name};new={new_weapon.zone.name};own={own.health};enemy={enemy.health}"
        return checked(observed, old_weapon.zone == Zone.GRAVEYARD and new_weapon.zone == Zone.PLAY and own.health == 3 and enemy.health == 3)

    return audit(cid, [
        ("battlecry_deathrattle_aoe", "Battlecry and Deathrattle each deal 1 damage to all minions.", battlecry_and_deathrattle_aoe, "分别在装备和销毁时检查双方随从各受到一次伤害。"),
        ("durability_zero", "When the second attack reduces durability to zero, the weapon leaves play and its Deathrattle deals the second 1 damage.", durability_zero_triggers_deathrattle, "通过两次真实英雄攻击消耗武器耐久，而不是直接调用 destroy。"),
        ("replacement_weapon", "Replacing the weapon destroys the old Blood Razor and triggers its Deathrattle.", replacement_triggers_old_weapon_deathrattle, "实际装备新武器，检查旧武器区域和亡语伤害。"),
    ])


def bone_baron():
    cid = "ICC_065"

    def adds_two_skeletons():
        g = new_game(); p = g.player1
        source = play(p, cid); source.destroy()
        skeletons = [c for c in p.hand if c.id == "ICC_026t"]
        observed = f"source={source.zone.name};hand={[c.id for c in skeletons]}"
        return checked(observed, source.zone == Zone.GRAVEYARD and len(skeletons) == 2 and all((c.atk, c.health) == (1, 1) for c in skeletons))

    return audit(cid, [("deathrattle_two_hand_skeletons", "Deathrattle adds two 1/1 Skeletons to the controller's hand.", adds_two_skeletons, "销毁本体并按身份、数量、身材检查手牌。")])


def vryghoul():
    return conditional_skeleton("ICC_067", "ICC_900t", (2, 2), "2/2 Ghoul")


def ice_walker():
    cid = "ICC_068"

    def hero_power_freezes_target():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p, e = g.player1, g.player2
        walker = summon(p, cid)
        target = summon(e, "CS2_182")
        before = target.health
        p.hero.power.use(target=target)
        observed = f"walker={walker.zone.name};target={target.health};frozen={target.frozen}"
        return checked(observed, target.health == before - 1 and target.frozen)

    return audit(cid, [("hero_power_freezes", "The Mage Hero Power still deals its damage and also freezes the targeted enemy minion.", hero_power_freezes_target, "实际使用火焰冲击并分别检查伤害和冻结。")])


def ghastly_conjurer():
    cid = "ICC_069"

    def adds_mirror_image():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p = g.player1
        source = play(p, cid)
        mirrors = [c for c in p.hand if c.id == "CS2_027"]
        observed = f"source={source.zone.name};mirror={[ (c.id,int(c.type),c.cost) for c in mirrors ]}"
        return checked(observed, source.zone == Zone.PLAY and len(mirrors) == 1 and mirrors[0].type == CardType.SPELL)

    return audit(cid, [("add_mirror_image", "Battlecry adds one Mirror Image spell to hand.", adds_mirror_image, "按实际生成卡牌 ID、类型和手牌区域检查。")])


def lights_sorrow():
    cid = "ICC_071"

    def gains_attack_after_shield_loss():
        g = new_game(CardClass.PALADIN, CardClass.PALADIN); p = g.player1
        weapon = play(p, cid)
        target = summon(p, "ICC_038")
        before = weapon.atk
        play(p, MOONFIRE, target=target)
        observed = f"weapon={before}->{weapon.atk};shield={target.divine_shield};target={target.health}"
        return checked(observed, weapon.atk == before + 1 and not target.divine_shield and target.health == 1)

    def ordinary_damage_does_not_trigger():
        g = new_game(CardClass.PALADIN, CardClass.PALADIN); p = g.player1
        weapon = play(p, cid)
        target = summon(p, "CS2_182")
        before = weapon.atk
        play(p, MOONFIRE, target=target)
        return checked(f"weapon={weapon.atk};target={target.health}", weapon.atk == before and target.health == 4)

    return audit(cid, [
        ("divine_shield_loss", "After a friendly Divine Shield is removed, the weapon gains +1 Attack.", gains_attack_after_shield_loss, "用实际带 Divine Shield 的随从承受伤害并检查武器攻击。"),
        ("ordinary_damage_no_trigger", "Damage to a friendly minion without Divine Shield does not increase the weapon.", ordinary_damage_does_not_trigger, "普通受伤作为触发条件对照。"),
    ])


def despicable_dreadlord():
    cid = "ICC_075"

    def end_turn_enemy_aoe():
        g = new_game(); p, e = g.player1, g.player2
        source = play(p, cid)
        first = summon(e, "CS2_182"); second = summon(e, "CS2_182")
        own = summon(p, "CS2_182")
        g.end_turn()
        observed = f"enemy={first.health}/{second.health};own={own.health};source={source.zone.name}"
        return checked(observed, first.health == 4 and second.health == 4 and own.health == 5)

    return audit(cid, [("end_turn_enemy_aoe", "At the end of your turn, deal 1 damage to all enemy minions only.", end_turn_enemy_aoe, "双方放置目标并实际结束回合，检查范围和伤害。")])


def avalanche():
    cid = "ICC_078"

    def freezes_center_and_damages_adjacent():
        g = new_game(); p, e = g.player1, g.player2
        left = summon(e, "CS2_182")
        center = summon(e, "CS2_182")
        right = summon(e, "CS2_182")
        spell = play(p, cid, center)
        observed = f"left={left.health};center={center.health}/{center.frozen};right={right.health};spell={spell.zone.name}"
        return checked(observed, left.health == 2 and right.health == 2 and center.health == 5 and center.frozen and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("center_freeze_adjacent_damage", "Freezes the chosen minion and deals 3 damage to each adjacent minion.", freezes_center_and_damages_adjacent, "三个连续敌方随从明确区分选中目标和相邻目标。")])


def gnash():
    cid = "ICC_079"

    def attack_and_armor_then_expire():
        g = new_game(CardClass.DRUID, CardClass.DRUID); p = g.player1
        try:
            spell = play(p, cid)
        except InvalidAction as exc:
            raise AssertionError(f"card rejected without target: {exc}") from exc
        observed = f"hero_attack={p.hero.atk};armor={p.hero.armor};spell={spell.zone.name}"
        assert p.hero.atk == 3 and p.hero.armor == 3, observed
        g.end_turn()
        return checked(observed + f";after_end_attack={p.hero.atk}", p.hero.atk == 0)

    return audit(cid, [("no_target_attack_armor", "The spell plays without a minion target, gives +3 hero Attack this turn and 3 Armor, then the Attack expires.", attack_and_armor_then_expire, "文本无目标；先检查可执行性，再检查攻击力、护甲和回合结束。")])


def drakkari_defender():
    cid = "ICC_081"

    def taunt_and_overload_three():
        g = new_game(CardClass.SHAMAN, CardClass.SHAMAN); p = g.player1
        source = play(p, cid)
        same_turn = f"taunt={source.taunt};overload={source.overload};overloaded={p.overloaded};locked={p.overload_locked};zone={source.zone.name}"
        assert source.taunt and source.overload == 3 and p.overloaded == 3 and p.overload_locked == 0 and source.zone == Zone.PLAY, same_turn
        g.end_turn(); g.end_turn()
        observed = same_turn + f";next_turn_locked={p.overload_locked};owed={p.overloaded}"
        return checked(observed, p.overload_locked == 3 and p.overloaded == 0)

    return audit(cid, [("taunt_overload", "The minion has Taunt and playing it locks exactly 3 Mana crystals as Overload.", taunt_and_overload_three, "实战打出并同时检查关键字、卡牌过载值和玩家锁定水晶。")])


def frozen_clone():
    cid = "ICC_082"

    def secret_copies_played_minion():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p, e = g.player1, g.player2
        secret = play(p, cid)
        assert secret in p.secrets
        g.end_turn()
        played = play(e, WISP)
        copies = [c for c in p.hand if c.id == WISP]
        observed = f"played={played.zone.name};copies={[c.id for c in copies]};secrets={[c.id for c in p.secrets]}"
        return checked(observed, len(copies) == 2 and not p.secrets)

    def friendly_play_does_not_trigger():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p = g.player1
        secret = play(p, cid)
        play(p, WISP)
        observed = f"hand={[c.id for c in p.hand]};secrets={[c.id for c in p.secrets]};secret_zone={secret.zone.name}"
        return checked(observed, not [c for c in p.hand if c.id == WISP] and len(p.secrets) == 1)

    def near_full_hand_discards_second_copy():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p, e = g.player1, g.player2
        for _ in range(9):
            p.give(WISP)
        secret = play(p, cid)
        g.end_turn()
        play(e, WISP)
        copies_in_hand = [c for c in p.hand if c.id == WISP]
        observed = f"hand_size={len(p.hand)};copies_in_hand={len(copies_in_hand)};secret={secret.zone.name};secrets={len(p.secrets)}"
        return checked(observed, len(p.hand) == p.max_hand_size == 10 and len(copies_in_hand) == 10 and not p.secrets)

    return audit(cid, [
        ("secret_two_copies", "After the opponent plays a minion, add two copies of that minion to hand and reveal the Secret.", secret_copies_played_minion, "实际切换到对手回合打出随从，检查两张复制牌和奥秘移除。"),
        ("friendly_nontrigger", "Playing your own minion does not trigger the opponent-only Secret.", friendly_play_does_not_trigger, "己方打出随从作为非触发对照，并确认奥秘仍在奥秘区。"),
        ("near_full_hand", "With nine cards already in hand, the two-copy trigger respects the ten-card hand cap.", near_full_hand_discards_second_copy, "九张预置手牌后触发，核对手牌上限和奥秘消失。"),
    ])


def doomed_apprentice():
    cid = "ICC_083"

    def opponent_spell_cost_only():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p, e = g.player1, g.player2
        apprentice = summon(p, cid)
        enemy_spell = e.give(MOONFIRE)
        own_spell = p.give(MOONFIRE)
        observed = f"enemy_cost={enemy_spell.cost};own_cost={own_spell.cost};apprentice={apprentice.zone.name}"
        return checked(observed, enemy_spell.cost == 1 and own_spell.cost == 0)

    return audit(cid, [("opponent_spell_aura", "Only the opponent's spell costs increase by 1 while the Apprentice is in play.", opponent_spell_cost_only, "同时读取双方手中同一法术的实时费用。")])


def ultimate_infestation():
    cid = "ICC_085"

    def five_effects():
        g = new_game(CardClass.DRUID, CardClass.DRUID); p, e = g.player1, g.player2
        p.hero.damage = 10
        target = e.hero
        put_deck(p, WISP, 5)
        spell = play(p, cid, target)
        drawn = [c.id for c in p.hand]
        ghouls = [m for m in p.field if m.id == "ICC_085t"]
        observed = f"enemy_hero={e.hero.health};drawn={drawn};armor={p.hero.armor};ghouls={[(m.atk,m.health) for m in ghouls]};spell={spell.zone.name}"
        return checked(observed, e.hero.health == 25 and drawn.count(WISP) == 5 and p.hero.armor == 5 and len(ghouls) == 1 and (ghouls[0].atk, ghouls[0].health) == (5, 5) and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("damage_draw_armor_summon", "Deals 5 damage, draws 5 cards, gains 5 Armor, and summons one 5/5 Ghoul.", five_effects, "用已知牌库和敌方英雄作为目标，逐项断言四个核心结果。")])


def glacial_mysteries():
    cid = "ICC_086"

    def puts_each_deck_secret_into_play():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p = g.player1
        put_deck(p, "EX1_289")
        put_deck(p, "EX1_294")
        spell = play(p, cid)
        observed = f"secrets={[c.id for c in p.secrets]};deck={[c.id for c in p.deck]};spell={spell.zone.name}"
        return checked(observed, {c.id for c in p.secrets} == {"EX1_289", "EX1_294"} and not any(c.id in {"EX1_289", "EX1_294"} for c in p.deck) and spell.zone == Zone.GRAVEYARD)

    def deduplicates_same_secret():
        g = new_game(CardClass.MAGE, CardClass.MAGE); p = g.player1
        put_deck(p, "EX1_289", 2)
        put_deck(p, "EX1_294")
        spell = play(p, cid)
        secrets = [card.id for card in p.secrets]
        deck = [card.id for card in p.deck]
        observed = f"secrets={secrets};deck={deck};spell={spell.zone.name}"
        return checked(observed, secrets.count("EX1_289") == 1 and secrets.count("EX1_294") == 1 and deck.count("EX1_289") == 1 and not deck.count("EX1_294"))

    return audit(cid, [
        ("deck_secrets_to_battlefield", "Puts one copy of each Secret present in the deck into the Secret zone.", puts_each_deck_secret_into_play, "牌库放入两个不同奥秘，核对奥秘区和牌库移除。"),
        ("duplicate_secret_once_each", "With a duplicate Secret in the deck, Glacial Mysteries puts only one copy of that Secret into play.", deduplicates_same_secret, "牌库放入两个 Ice Barrier 和一个 Mirror Entity，检查奥秘区去重以及剩余重复牌。"),
    ])


def voodoo_hexxer():
    cid = "ICC_088"

    def freezes_character_damaged_by_attack():
        g = new_game(CardClass.SHAMAN, CardClass.SHAMAN); p, e = g.player1, g.player2
        source = summon(p, cid)
        target = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        source.attack(target)
        observed = f"target={target.health};frozen={target.frozen};source={source.health}"
        return checked(observed, target.health == 3 and target.frozen and source.zone == Zone.PLAY)

    return audit(cid, [("attack_freezes_damaged_target", "A character damaged by this minion is frozen.", freezes_character_damaged_by_attack, "让本体在下一回合实际攻击敌方随从，检查受伤和冻结。")])


def ice_fishing():
    cid = "ICC_089"

    def draws_two_murlocs_only():
        g = new_game(CardClass.SHAMAN, CardClass.SHAMAN); p = g.player1
        put_deck(p, MURLOC, 2)
        put_deck(p, WISP)
        spell = play(p, cid)
        murlocs = [c for c in p.hand if c.id == MURLOC]
        observed = f"hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]};murlocs={len(murlocs)};spell={spell.zone.name}"
        return checked(observed, len(murlocs) == 2 and not any(c.id == WISP for c in p.hand) and any(c.id == WISP for c in p.deck) and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("draw_two_murlocs", "Draws exactly two Murlocs and leaves a non-Murloc in the deck.", draws_two_murlocs_only, "牌库混入两个鱼人和一个 Wisp，检查抽牌身份及剩余牌库。")])


def snowfury_giant():
    cid = "ICC_090"

    def cost_reduces_per_overloaded_crystal():
        g = new_game(CardClass.SHAMAN, CardClass.SHAMAN); p, e = g.player1, g.player2
        play(p, "EX1_238", target=e.hero)
        giant = p.give(cid)
        observed = f"overloaded_this_game={p.overloaded_this_game};owed={p.overloaded};locked={p.overload_locked};giant_cost={giant.cost}"
        return checked(observed, p.overloaded_this_game == 1 and giant.cost == 10)

    return audit(cid, [("overload_cost_discount", "One overloaded Mana Crystal this game lowers the Giant's cost by exactly 1.", cost_reduces_per_overloaded_crystal, "实际施放带 Overload (1) 的法术后读取手中巨人的费用。")])


def dead_mans_hand():
    cid = "ICC_091"

    def shuffles_hand_copies_into_deck():
        g = new_game(CardClass.WARRIOR, CardClass.WARRIOR); p = g.player1
        p.give(WISP); p.give(MOONFIRE)
        spell = play(p, cid)
        hand_ids = [c.id for c in p.hand]
        deck_ids = [c.id for c in p.deck]
        observed = f"hand={hand_ids};deck={deck_ids};spell={spell.zone.name}"
        return checked(observed, hand_ids.count(WISP) == 1 and hand_ids.count(MOONFIRE) == 1 and deck_ids.count(WISP) == 1 and deck_ids.count(MOONFIRE) == 1 and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [("shuffle_hand_copies", "Leaves the current hand intact and shuffles one copy of each remaining hand card into the deck.", shuffles_hand_copies_into_deck, "在手牌预置两个不同实体，检查手牌保留和牌库副本。")])


def acherus_veteran():
    cid = "ICC_092"

    def buffs_friendly_attack():
        g = new_game(); p = g.player1
        target = summon(p, WISP)
        source = play(p, cid, target)
        observed = f"target={target.atk}/{target.health};source={source.zone.name}"
        return checked(observed, target.atk == 2 and target.health == 1 and source.zone == Zone.PLAY)

    return audit(cid, [("friendly_attack_buff", "Battlecry gives a friendly minion +1 Attack only.", buffs_friendly_attack, "检查己方目标的攻击与生命，并确认本体仍在场。")])


def tuskarr_fisherman():
    cid = "ICC_093"

    def buffs_friendly_spell_damage():
        g = new_game(); p = g.player1
        target = summon(p, WISP)
        source = play(p, cid, target)
        observed = f"target_spellpower={target.spellpower};source={source.zone.name}"
        return checked(observed, target.spellpower == 1 and source.zone == Zone.PLAY)

    def spell_damage_changes_real_damage():
        g = new_game(); p, e = g.player1, g.player2
        target = summon(p, WISP)
        enemy = summon(e, "CS2_200")
        play(p, cid, target)
        before = enemy.health
        spell = play(p, MOONFIRE, target=enemy)
        observed = f"target_spellpower={target.spellpower};enemy={before}->{enemy.health};spell={spell.zone.name}"
        return checked(observed, target.spellpower == 1 and enemy.health == before - 2 and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("friendly_spell_damage", "Battlecry gives a friendly minion Spell Damage +1.", buffs_friendly_spell_damage, "读取目标随从的实际 Spell Damage 属性。"),
        ("spell_damage_real_resolution", "The granted Spell Damage +1 changes a real 1-damage Moonfire into 2 damage.", spell_damage_changes_real_damage, "在增益后实际施放 Moonfire，检查敌方7点生命随从的真实生命变化和法术区域。"),
    ])


def main():
    probes = [
        phantom_freebooter, skelemancer, exploding_bloatbat, rattling_rascal,
        grim_necromancer, bone_drake, sunborne_valkyr, cobalt_scalebane,
        night_howler, venomancer, arrogant_crusader, righteous_protector,
        dark_conviction, defile, fatespinner, toxic_arrow, webweave,
        druid_of_swarm, play_dead, spreading_plague, drain_soul, cryostasis,
        brrrloc, mountainfire_armor, blood_razor, bone_baron, vryghoul,
        ice_walker, ghastly_conjurer, lights_sorrow, despicable_dreadlord,
        avalanche, gnash, drakkari_defender, frozen_clone, doomed_apprentice,
        ultimate_infestation, glacial_mysteries, voodoo_hexxer, ice_fishing,
        snowfury_giant, dead_mans_hand, acherus_veteran, tuskarr_fisherman,
    ]
    statuses = [probe() for probe in probes]
    assert set(OWN_IDS) == set(row["card_id"] for row in VERDICT_ROWS)
    assert all(sum(row["card_id"] == cid for row in PROBE_ROWS) >= 1 for cid in OWN_IDS)
    print(f"SUMMARY cards={len(statuses)} GREEN={statuses.count('GREEN')} YELLOW={statuses.count('YELLOW')} RED={statuses.count('RED')} cases={sum(row['card_id'] in OWN_IDS for row in PROBE_ROWS)}")


if __name__ == "__main__":
    main()
