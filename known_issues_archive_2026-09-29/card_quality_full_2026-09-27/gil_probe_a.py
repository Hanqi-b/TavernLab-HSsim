"""Targeted live-game probes for the first 42 ordinary GILNEAS YELLOW cards."""

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
from utils import WISP, MOONFIRE, prepare_empty_game  # noqa: E402

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "gil_probe_a.csv"
VERDICT_OUT = HERE / "gil_verdict_a.csv"
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


BASE_ROWS = [r for r in read_csv(BASELINE) if r["set"].startswith("The Witchwood") and r["scope"] == "ordinary_collectible"]
OWN_ROWS = BASE_ROWS[:42]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
assert len(OWN_IDS) == 42 and OWN_IDS[0] == "GIL_116" and OWN_IDS[-1] == "GIL_537"
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


def arcane_keysmith():
    cid = "GIL_116"

    def discover_secret_and_put_it_into_play():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1161)
        p = g.player1
        minion = play(p, cid)
        choice = p.choice
        assert choice is not None, "battlecry did not open a Discover choice"
        offered = list(choice.cards)
        details = [(c.id, int(c.card_class), int(c.type), c.zone.name) for c in offered]
        candidate = offered[0]
        p.choice.choose(candidate)
        secrets = list(p.secrets)
        observed = (
            f"body={minion.id}:{minion.atk}/{minion.health}:{minion.zone.name};"
            f"offered={details};selected={candidate.id}:{int(candidate.card_class)}:{candidate.zone.name};"
            f"secrets={[c.id for c in secrets]};hand={[c.id for c in p.hand]}"
        )
        return checked(
            observed,
            len(offered) == 3
            and all(c.type == CardType.SPELL and c.data.secret and c.card_class == CardClass.MAGE for c in offered)
            and (minion.atk, minion.health, minion.zone) == (2, 2, Zone.PLAY)
            and p.choice is None
            and candidate in secrets
            and candidate.zone == Zone.SECRET
            and candidate not in p.hand,
        )

    def adds_discovered_secret_alongside_existing_secret():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1162)
        p = g.player1
        existing = play(p, "EX1_287")
        minion = play(p, cid)
        offered = list(p.choice.cards)
        options = [(c.id, int(c.card_class), int(c.type), c.data.secret) for c in offered]
        candidate = next((c for c in offered if c.id != existing.id), None)
        assert candidate is not None, f"no distinct secret offered alongside active secret: {options}"
        p.choice.choose(candidate)
        observed = f"body={minion.atk}/{minion.health}:{minion.zone.name};existing={existing.id}:{existing.zone.name};offers={options};selected={candidate.id}:{candidate.zone.name};secrets={[c.id for c in p.secrets]};hand={[c.id for c in p.hand]}"
        return checked(observed, len(offered) == 3 and all(c.type == CardType.SPELL and c.data.secret and c.card_class == CardClass.MAGE for c in offered) and existing in p.secrets and existing.zone == Zone.SECRET and candidate in p.secrets and candidate.zone == Zone.SECRET and len(p.secrets) == 2 and candidate not in p.hand and (minion.atk, minion.health, minion.zone) == (2, 2, Zone.PLAY))

    return audit(cid, [(
        "discover_mage_secret_enters_battlefield",
        "Battlecry offers three Mage Secret choices; selecting one places that Secret directly on the battlefield while the 2/2 Keysmith remains in play.",
        discover_secret_and_put_it_into_play,
        "实际打出随从，检查三项 Discover、职业/法术/奥秘类型，选择一项后确认其在奥秘区而非手牌，并核对 2/2 本体。",
    ), (
        "discover_when_secret_already_active",
        "With an existing Mage Secret active, Keysmith still offers three Mage Secrets; choosing a distinct one leaves both Secrets on the battlefield.",
        adds_discovered_secret_alongside_existing_secret,
        "先实际施放法师奥秘，再打出Keysmith并选择与现有奥秘不同的选项；检查两张奥秘仍在SECRET区、选择不进入手牌且本体2/2。",
    )])


def worgen_abomination():
    cid = "GIL_117"

    def only_other_damaged_minions_are_hit_at_turn_end():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1171)
        p, e = g.player1, g.player2
        monster = summon(p, cid)
        friendly_damaged = summon(p, "CFM_039")
        enemy_damaged = summon(e, "CFM_039")
        friendly_untouched = summon(p, "CS2_179")
        play(p, "CS2_008", target=friendly_damaged)
        play(p, "CS2_008", target=enemy_damaged)
        before = (friendly_damaged.health, enemy_damaged.health, friendly_untouched.health)
        g.end_turn()
        observed = (
            f"worgen={monster.atk}/{monster.health};damaged={before}->"
            f"({friendly_damaged.health},{enemy_damaged.health});"
            f"undamaged={friendly_untouched.health};zones="
            f"{friendly_damaged.zone.name}/{enemy_damaged.zone.name}"
        )
        return checked(
            observed,
            friendly_damaged.health == before[0] - 2
            and enemy_damaged.health == before[1] - 2
            and friendly_untouched.health == before[2],
        )

    return audit(cid, [(
        "turn_end_hits_only_damaged_other_minions",
        "At its controller's end of turn, deal 2 to each other already-damaged minion on either side; leave undamaged minions unchanged.",
        only_other_damaged_minions_are_hit_at_turn_end,
        "友敌两侧各用实际法术预先造成伤害，另留一只未受伤随从；结束控制者回合后逐只核对生命值。",
    )])


def deranged_doctor():
    cid = "GIL_118"

    def deathrattle_restores_eight_to_own_hero():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1181)
        p, e = g.player1, g.player2
        doctor = summon(p, cid)
        for _ in range(15):
            play(p, "CS2_008", target=p.hero)
        before, enemy_before = p.hero.health, e.hero.health
        for _ in range(8):
            play(p, "CS2_008", target=doctor)
        observed = f"hero={before}->{p.hero.health};enemy={enemy_before}->{e.hero.health};doctor={doctor.zone.name};friendly_field={[m.id for m in p.field]}"
        return checked(observed, before == 15 and p.hero.health == 23 and e.hero.health == enemy_before and doctor.zone == Zone.GRAVEYARD)

    return audit(cid, [(
        "deathrattle_heals_controller",
        "When Deranged Doctor dies, restore exactly 8 Health to its controller's hero and do not heal the opponent.",
        deathrattle_restores_eight_to_own_hero,
        "先用15次月火将己方英雄降至15，再用8次月火击杀8/8医生，核对死亡区、英雄生命和敌方英雄。",
    )])


def cauldron_elemental():
    cid = "GIL_119"

    def aura_buffs_other_friendly_elementals_only():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1191)
        p, e = g.player1, g.player2
        cauldron = summon(p, cid)
        friend_elemental = summon(p, "UNG_809t1")
        enemy_elemental = summon(e, "UNG_809t1")
        friend_non_elemental = summon(p, WISP)
        observed = (
            f"cauldron={cauldron.atk}/{cauldron.health};friendly_elemental={friend_elemental.atk}/{friend_elemental.health};"
            f"enemy_elemental={enemy_elemental.atk}/{enemy_elemental.health};non_elemental={friend_non_elemental.atk}/{friend_non_elemental.health}"
        )
        return checked(observed, (cauldron.atk, friend_elemental.atk, enemy_elemental.atk, friend_non_elemental.atk) == (7, 3, 1, 1))

    return audit(cid, [(
        "aura_only_buffs_other_friendly_elementals",
        "Other friendly Elementals gain +2 Attack; the Cauldron itself, enemy Elementals, and friendly non-Elementals do not gain Attack.",
        aura_buffs_other_friendly_elementals_only,
        "召唤本体、友方/敌方元素随从和友方非元素随从，直接检查四个实际攻击力。",
    )])


def furious_ettin():
    cid = "GIL_120"

    def base_stats_and_taunt():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1201)
        ettin = summon(g.player1, cid)
        observed = f"body={ettin.id}:{ettin.atk}/{ettin.health};taunt={ettin.taunt};zone={ettin.zone.name}"
        return checked(observed, (ettin.atk, ettin.health, ettin.taunt, ettin.zone) == (5, 9, True, Zone.PLAY))

    return audit(cid, [("printed_taunt_body", "Furious Ettin is a 5/9 minion with Taunt.", base_stats_and_taunt, "真实召唤后断言基础攻防、嘲讽关键字及场区。")])


def darkmire_moonkin():
    cid = "GIL_121"

    def spell_damage_plus_two_applies_to_spell_resolution():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1211)
        p, e = g.player1, g.player2
        moonkin = summon(p, cid)
        target = summon(e, "CFM_039")
        before = target.health
        play(p, "CS2_008", target=target)
        observed = f"moonkin={moonkin.atk}/{moonkin.health};target={before}->{target.health};spell_damage={p.spellpower}"
        return checked(observed, (moonkin.atk, moonkin.health, p.spellpower, target.health) == (2, 8, 2, before - 3))

    return audit(cid, [("spell_damage_increases_spell_damage", "Darkmire Moonkin is a 2/8 with Spell Damage +2; a 1-damage Moonfire deals 3 to a minion.", spell_damage_plus_two_applies_to_spell_resolution, "检查随从身材、玩家法伤值，并用实际月火核对目标损失3点生命。")])


def mossy_horror():
    cid = "GIL_124"

    def destroys_all_other_minions_at_two_or_less_attack():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1241)
        p, e = g.player1, g.player2
        friend_low = summon(p, WISP)
        enemy_low = summon(e, "CFM_039")
        friend_high = summon(p, "CS2_179")
        horror = play(p, cid)
        observed = (
            f"horror={horror.atk}/{horror.health}:{horror.zone.name};low="
            f"{friend_low.zone.name}/{enemy_low.zone.name};high={friend_high.atk}/{friend_high.health}:{friend_high.zone.name};"
            f"fields={[m.id for m in p.field]}/{[m.id for m in e.field]}"
        )
        return checked(observed, horror.zone == Zone.PLAY and (horror.atk, horror.health) == (2, 7) and friend_low.zone == enemy_low.zone == Zone.GRAVEYARD and friend_high.zone == Zone.PLAY and friend_high.atk == 3 and friend_high.health == 5)

    return audit(cid, [("battlecry_destroys_low_attack_on_both_sides", "Mossy Horror destroys every other minion with 2 or less Attack on either side, while retaining itself and minions with more than 2 Attack.", destroys_all_other_minions_at_two_or_less_attack, "友敌各放置低攻目标，另放置3攻嘲讽随从；实际打出后检查每个实体的存活区和身材。")])


def mad_hatter():
    cid = "GIL_125"

    def three_random_hats_buff_other_minions_only():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1251)
        p, e = g.player1, g.player2
        left = summon(p, "CFM_039")
        right = summon(e, "CFM_039")
        before = [(m.atk, m.health) for m in (left, right)]
        hatter = play(p, cid)
        deltas = [(m.atk - a, m.health - h) for m, (a, h) in zip((left, right), before)]
        observed = f"hatter={hatter.atk}/{hatter.health};other_before={before};deltas={deltas};enemy_zone={right.zone.name}"
        return checked(observed, (hatter.atk, hatter.health, hatter.zone) == (3, 2, Zone.PLAY) and left.zone == right.zone == Zone.PLAY and sum(a for a, _ in deltas) == 3 and sum(h for _, h in deltas) == 3 and all(a == h and a >= 0 for a, h in deltas))

    return audit(cid, [("battlecry_distributes_three_hats", "The Battlecry gives exactly three total +1/+1 hats to other minions, allowing repeated hits on a minion but never buffing Mad Hatter itself.", three_random_hats_buff_other_minions_only, "在友敌各放置一个7血高血量目标，实测随机结果；汇总两目标增益必须恰为+3/+3。")])


def emeriss():
    cid = "GIL_128"

    def battlecry_doubles_hand_minion_attack_and_health():
        g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=1281)
        p = g.player1
        wisp = p.give(WISP)
        yeti = p.give("CS2_182")
        spell = p.give("CS2_029")
        before = [(wisp.atk, wisp.health), (yeti.atk, yeti.health)]
        dragon = play(p, cid)
        observed = f"emeriss={dragon.atk}/{dragon.health};hand_minions={wisp.id}:{wisp.atk}/{wisp.health},{yeti.id}:{yeti.atk}/{yeti.health};spell={spell.id}:{spell.cost};hand={[c.id for c in p.hand]}"
        return checked(observed, (before, (wisp.atk, wisp.health), (yeti.atk, yeti.health), spell.zone, dragon.zone) == ([(1, 1), (4, 5)], (2, 2), (8, 10), Zone.HAND, Zone.PLAY))

    return audit(cid, [("battlecry_doubles_only_minions_in_hand", "Emeriss doubles Attack and Health of each minion in hand, leaves spells unchanged, and is an 8/8 body.", battlecry_doubles_hand_minion_attack_and_health, "把1/1和4/5随从及法术留在手牌，打出艾莫莉丝后核对随从攻防翻倍、法术仍在手、本体8/8。")])


def holy_water():
    cid = "GIL_134"

    def nonlethal_damage_does_not_copy_target():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1341)
        p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        before = target.health
        play(p, cid, target=target)
        observed = f"target={before}->{target.health}:{target.zone.name};matching_hand={[c.id for c in p.hand if c.id == 'CS2_182']}"
        return checked(observed, target.zone == Zone.PLAY and target.health == before - 4 and not any(c.id == "CS2_182" for c in p.hand))

    def lethal_damage_adds_a_fresh_copy():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1342)
        p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        play(p, "CS2_008", target=target)
        before = target.health
        play(p, cid, target=target)
        copies = [c for c in p.hand if c.id == "CS2_182"]
        observed = f"target={target.id}:{target.zone.name};before_spell={before};copies={[(c.id,c.atk,c.health,c.zone.name) for c in copies]}"
        return checked(observed, target.zone == Zone.GRAVEYARD and len(copies) == 1 and (copies[0].atk, copies[0].health, copies[0].zone) == (4, 5, Zone.HAND))

    return audit(cid, [
        ("nonlethal_damage_no_copy", "Holy Water deals 4 to a minion that survives and creates no copy.", nonlethal_damage_does_not_copy_target, "对5血Yeti直接施放后核对余2血留场且手中无同名副本。"),
        ("lethal_damage_adds_copy", "If Holy Water kills its target, add a fresh copy of that minion to hand.", lethal_damage_adds_a_fresh_copy, "先对5血Yeti造成1点伤害，再施放圣水；检查原实体入墓地及一张满血Yeti副本入手。"),
    ])


def chameleos():
    cid = "GIL_142"

    def hand_card_morphs_each_own_turn_and_tracks_current_entity():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1421)
        p, e = g.player1, g.player2
        original = p.give(cid)
        e.give("CS2_182")
        end_round(g)
        first = find_hand(p, "CS2_182")
        first_snapshot = None if first is None else (first.id, first.zone.name, first.atk, first.health)
        e.discard_hand()
        e.give("CS2_029")
        end_round(g)
        current = find_hand(p, "CS2_029")
        observed = f"original_now={original.id}:{original.zone.name};first={first_snapshot};active={[card_state(c) for c in p.hand]};second_copy={card_state(current)}"
        return checked(observed, first_snapshot is not None and first_snapshot[:2] == ("CS2_182", "HAND") and current is not None and current.id == "CS2_029" and current.zone == Zone.HAND and current.cost == 4 and not any(c.id == cid for c in p.hand))

    def empty_opponent_hand_leaves_chameleos_unchanged():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1422)
        p, e = g.player1, g.player2
        card = p.give(cid)
        e.discard_hand()
        end_round(g)
        active = find_hand(p, cid)
        observed = f"hand={[ (c.id,c.zone.name) for c in p.hand]};enemy_hand={len(e.hand)}"
        return checked(observed, active is not None and active is card and active.zone == Zone.HAND and not e.hand)

    return audit(cid, [
        ("morph_each_turn_from_opponent_hand", "On successive owner turns, the in-hand card becomes a current hand copy of a card held by the opponent; inspect the active hand entities after each Morph.", hand_card_morphs_each_own_turn_and_tracks_current_entity, "对手先持Yeti，首个己方回合检查现存手牌实体；随后替换成火球术，第二回合验证持续触发并查当前实体而非只信旧Morph引用。"),
        ("empty_opponent_hand_no_transform", "If the opponent holds no cards when the owner turn begins, Chameleos stays in hand and does not fabricate a copy.", empty_opponent_hand_leaves_chameleos_unchanged, "清空敌方手牌后推进完整回合，核对卡米洛斯仍在原手牌区且敌方手牌为空。"),
    ])


def sound_the_bells():
    cid = "GIL_145"

    def echo_returns_copy_and_each_cast_buffs_target():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=1451)
        p = g.player1
        target = summon(p, WISP)
        spell = play(p, cid, target=target)
        first_copy = find_hand(p, cid)
        first = (target.atk, target.health, target.max_health)
        second_spell = play(p, cid, target=target)
        second_copy = find_hand(p, cid)
        observed = f"target_first={first};target_second={target.atk}/{target.health}/{target.max_health};first_spell={spell.zone.name};second_spell={second_spell.zone.name};echo_copy={None if second_copy is None else (second_copy.id,second_copy.zone.name)};mana={p.mana}"
        return checked(observed, first_copy is not None and first_copy.zone == Zone.HAND and first == (2, 3, 3) and (target.atk, target.health, target.max_health) == (3, 5, 5) and second_spell.zone == Zone.GRAVEYARD and second_copy is not None and second_copy.zone == Zone.HAND)

    return audit(cid, [("echo_repeats_and_buffs_same_minion", "Echo returns a playable copy after the first cast; each cast gives its chosen minion +1/+2.", echo_returns_copy_and_each_cast_buffs_target, "连续实际施放两次回声法术并选同一Wisp，检查每次攻防增量及回声副本持续回手。")])


def cinderstorm():
    cid = "GIL_147"

    def damage_is_split_only_across_enemy_characters():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1471)
        p, e = g.player1, g.player2
        friendly = summon(p, "CFM_039")
        enemy_a = summon(e, "CFM_039")
        enemy_b = summon(e, "CS2_179")
        before = (e.hero.health, enemy_a.health, enemy_b.health, friendly.health)
        play(p, cid)
        after = (e.hero.health, enemy_a.health, enemy_b.health, friendly.health)
        observed = f"enemy_hero={before[0]}->{after[0]};enemy_minions={(before[1],before[2])}->{(after[1],after[2])};friendly={before[3]}->{after[3]};total_enemy_damage={sum(before[:3])-sum(after[:3])}"
        expected_total = 5 + p.spellpower
        return checked(observed, sum(before[:3]) - sum(after[:3]) == expected_total and friendly.health == before[3] and enemy_a.zone == enemy_b.zone == Zone.PLAY)

    def enemy_hero_is_valid_only_target():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1472)
        p, e = g.player1, g.player2
        before = e.hero.health
        play(p, cid)
        observed = f"enemy_hero={before}->{e.hero.health};friendly_hero={p.hero.health}"
        return checked(observed, e.hero.health == before - 5 and p.hero.health == 30)

    return audit(cid, [
        ("five_random_damage_enemy_only", "Deal 5 damage randomly split among enemies, with the amount correctly increased by any active Spell Damage; leave friendly characters untouched.", damage_is_split_only_across_enemy_characters, "敌方英雄和两只高血量随从共同作为随机目标，并放置友方高血量随从；按实测当前法伤检查总敌方损失等于5加法伤且友方不变。"),
        ("hero_only_target_receives_all_damage", "When the enemy hero is the only enemy character, it receives all 5 damage.", enemy_hero_is_valid_only_target, "无敌方随从时实际施放并逐点核对敌方英雄与己方英雄生命。"),
    ])


def blackhowl_gunspire():
    cid = "GIL_152"

    def damaged_trigger_hits_only_enemy_hero_and_cannot_attack():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=1521)
        p, e = g.player1, g.player2
        gun = summon(p, cid)
        play(p, "CS2_008", target=gun)
        observed = f"gun={gun.atk}/{gun.health}:cant_attack={gun.cant_attack};enemy_hero={e.hero.health};enemy_field={[m.id for m in e.field]}"
        return checked(observed, (gun.atk, gun.health, gun.cant_attack, gun.zone, e.hero.health) == (3, 7, True, Zone.PLAY, 27) and not gun.can_attack())

    return audit(cid, [("self_damage_triggers_three_enemy_damage", "The non-attacking Gunspire deals 3 damage to a random enemy character when it takes damage; with only the enemy hero available, that hero loses 3.", damaged_trigger_hits_only_enemy_hero_and_cannot_attack, "以实际月火造成炮塔自身1点伤害，敌方仅留英雄作为有效随机目标，同时核对炮塔场区、剩余生命、不可攻击及英雄失血。")])


def redband_wasp():
    cid = "GIL_155"

    def rush_and_enrage_attack_bonus_are_live():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=1551)
        p, e = g.player1, g.player2
        target = summon(e, "CFM_039")
        wasp = summon(p, cid)
        can_minion, can_hero = wasp.can_attack(target), wasp.can_attack(e.hero)
        play(p, "CS2_008", target=wasp)
        attack_damaged = wasp.atk
        wasp.attack(target)
        observed = f"rush={wasp.rush};atk_damaged={attack_damaged};enemy_minion={target.health}:{target.zone.name};wasp={wasp.atk}/{wasp.health};can_minion={can_minion};can_hero={can_hero}"
        return checked(observed, wasp.rush and can_minion and not can_hero and attack_damaged == 4 and target.health == 3 and wasp.zone == Zone.PLAY and wasp.health == 2)

    return audit(cid, [("rush_cannot_hit_hero_and_damaged_attack_gains_three", "Redband Wasp has Rush, cannot attack the enemy hero on the turn it is summoned, and gains +3 Attack while damaged.", rush_and_enrage_attack_bonus_are_live, "本回合召唤1/3蜂，验证Rush仅能选敌方随从；实际受伤后攻击0攻7血目标，核对攻击力4与目标损失。")])


def quartz_elemental():
    cid = "GIL_156"

    def can_attack_healthy_but_not_while_damaged():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1561)
        p, e = g.player1, g.player2
        elemental = summon(p, cid)
        target = summon(e, "CFM_039")
        end_round(g)
        healthy_ready = elemental.can_attack(target)
        before = elemental.health
        play(p, "CS2_008", target=elemental)
        damaged_ready = elemental.can_attack(target)
        observed = f"body={elemental.atk}/{elemental.health};before_damage={before};healthy_can_attack={healthy_ready};damaged={elemental.damage};damaged_can_attack={damaged_ready};cant_attack={elemental.cant_attack}"
        return checked(observed, (elemental.atk, elemental.health, healthy_ready, elemental.damage, damaged_ready, elemental.cant_attack) == (5, 7, True, 1, False, True))

    return audit(cid, [("attack_permission_tracks_damage_state", "After it has become ready, Quartz Elemental can attack while at full Health, but loses attack permission immediately when damaged.", can_attack_healthy_but_not_while_damaged, "先结束一轮使5/8元素获得攻击准备，实际检查健康状态可攻击；再用月火造成1伤，重新检查当前攻击权限及CANT_ATTACK更新。")])


def druid_of_the_scythe():
    cid = "GIL_188"

    def rush_choice_transforms_and_attacks_minion():
        g = new_game(CardClass.DRUID, CardClass.MAGE, seed=1881)
        p, e = g.player1, g.player2
        target = summon(e, "CFM_039")
        play(p, cid, choose="GIL_188a")
        form = p.field[-1]
        can_minion, can_hero = form.can_attack(target), form.can_attack(e.hero)
        form.attack(target)
        observed = f"form={form.id}:{form.atk}/{form.health}:rush={form.rush}:taunt={form.taunt};can_minion={can_minion};can_hero={can_hero};target={target.health}"
        return checked(observed, form.id == "GIL_188t" and (form.atk, form.health, form.rush, form.taunt) == (4, 2, True, False) and can_minion and not can_hero and target.health == 3)

    def taunt_choice_transforms_to_two_four():
        g = new_game(CardClass.DRUID, CardClass.MAGE, seed=1882)
        p = g.player1
        play(p, cid, choose="GIL_188b")
        form = p.field[-1]
        observed = f"form={form.id}:{form.atk}/{form.health}:rush={form.rush}:taunt={form.taunt};zone={form.zone.name}"
        return checked(observed, form.id == "GIL_188t2" and (form.atk, form.health, form.rush, form.taunt, form.zone) == (2, 4, False, True, Zone.PLAY))

    return audit(cid, [
        ("choose_rush_four_two", "Choosing Rush transforms the minion into a 4/2 with Rush; it can attack an enemy minion immediately but not the hero.", rush_choice_transforms_and_attacks_minion, "通过Choose One实际选择Rush分支，检查场上当前变形实体并立即攻击敌方随从，同时确认不能选敌方英雄。"),
        ("choose_taunt_two_four", "Choosing Taunt transforms the minion into a 2/4 with Taunt and no Rush.", taunt_choice_transforms_to_two_four, "新局选择嘲讽分支后直接读取场上的当前变形实体、身材、关键字和场区。"),
    ])


def nightscale_matriarch():
    cid = "GIL_190"

    def healing_friendly_minion_summons_one_whelp():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1901)
        p = g.player1
        matriarch = summon(p, cid)
        wounded = summon(p, "CFM_039")
        play(p, "CS2_008", target=wounded)
        before = wounded.health
        play(p, "CS2_089", target=wounded)
        whelps = [m for m in p.field if m.id == "GIL_190t"]
        observed = f"matriarch={matriarch.atk}/{matriarch.health};wounded={before}->{wounded.health};whelps={[(m.atk,m.health,m.zone.name) for m in whelps]};field={[m.id for m in p.field]}"
        return checked(observed, wounded.health > before and wounded.health == wounded.max_health and len(whelps) == 1 and (whelps[0].atk, whelps[0].health) == (3, 3))

    def healing_only_hero_does_not_trigger():
        g = new_game(CardClass.PRIEST, CardClass.MAGE, seed=1902)
        p = g.player1
        summon(p, cid)
        for _ in range(4):
            play(p, "CS2_008", target=p.hero)
        before = p.hero.health
        play(p, "CS2_089", target=p.hero)
        observed = f"hero={before}->{p.hero.health};field={[m.id for m in p.field]}"
        return checked(observed, p.hero.health > before and not any(m.id == "GIL_190t" for m in p.field))

    return audit(cid, [
        ("healed_friendly_minion_summons_whelp", "Whenever a friendly minion is healed, summon one 3/3 Whelp.", healing_friendly_minion_summons_one_whelp, "场上有夜鳞龙后与受伤友方高血量随从，实际治疗后核对生命恢复及唯一一只3/3龙雏。"),
        ("healing_hero_does_not_trigger", "Healing only the friendly hero does not trigger a minion-heal effect.", healing_only_hero_does_not_trigger, "只治疗己方英雄，核对生命确实恢复且未召唤龙雏，区分随从治疗触发范围。"),
    ])


def fiendish_circle():
    cid = "GIL_191"

    def summons_four_one_one_imps_on_open_board():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE, seed=1911)
        p = g.player1
        play(p, cid)
        imps = [m for m in p.field if m.id == "GIL_191t"]
        observed = f"imps={[(m.atk,m.health,m.zone.name) for m in imps]};field_count={len(p.field)}"
        return checked(observed, len(imps) == 4 and all((m.atk, m.health, m.zone) == (1, 1, Zone.PLAY) for m in imps) and len(p.field) == 4)

    def multi_summon_respects_last_open_board_slot():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE, seed=1912)
        p = g.player1
        controls = [summon(p, "CS2_182") for _ in range(6)]
        play(p, cid)
        imps = [m for m in p.field if m.id == "GIL_191t"]
        observed = f"starting={len(controls)};final={len(p.field)};imp_count={len(imps)};ids={[m.id for m in p.field]}"
        return checked(observed, len(p.field) == 7 and len(imps) == 1 and all(m.zone == Zone.PLAY for m in controls))

    return audit(cid, [
        ("summon_four_imps", "Fiendish Circle summons four 1/1 Imps when four board slots are available.", summons_four_one_one_imps_on_open_board, "在空场实际施放，逐只检查四个衍生物身材、场区与数量。"),
        ("cap_at_last_open_slot", "With six friendly minions before casting, the four-summon effect fills only the seventh slot and never overflows the board.", multi_summon_respects_last_open_board_slot, "预先召唤六只Yeti占位后施放，逐实体核对最终场上正好七只、只出现一只Imp。"),
    ])


def azalina_soulthief():
    cid = "GIL_198"

    def replaces_hand_with_independent_copies_of_enemy_hand():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1981)
        p, e = g.player1, g.player2
        enemy_cards = [e.give("CS2_182"), e.give("CS2_029")]
        p.give("CS2_231")
        p.give("CS2_182")
        p.give("CS2_029")
        az = play(p, cid)
        observed = f"az={az.atk}/{az.health}:{az.zone.name};p_hand={[card_state(c) for c in p.hand]};e_hand={[card_state(c) for c in e.hand]}"
        copies_match = sorted(c.id for c in p.hand) == sorted(c.id for c in enemy_cards)
        return checked(observed, copies_match and len(p.hand) == 2 and len(e.hand) == 2 and all(pc is not ec for pc in p.hand for ec in e.hand) and az.zone == Zone.PLAY and (az.atk, az.health) == (3, 3))

    def replaces_hand_with_empty_enemy_hand():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=1982)
        p, e = g.player1, g.player2
        p.give("CS2_231")
        p.give("CS2_029")
        e.discard_hand()
        az = play(p, cid)
        observed = f"p_hand={[c.id for c in p.hand]};e_hand={len(e.hand)};az={az.id}:{az.zone.name}"
        return checked(observed, not p.hand and not e.hand and az.zone == Zone.PLAY)

    return audit(cid, [
        ("replace_hand_with_copies", "Azalina removes the controller's old hand and replaces it with independent copies of every card in the opponent's hand.", replaces_hand_with_independent_copies_of_enemy_hand, "己方先持三张不同牌，敌方持Yeti与火球；打出后核对手牌ID多重集与数量完全对应，且副本对象不等于敌方原牌。"),
        ("empty_enemy_hand_clears_own_hand", "If the opponent's hand is empty, Azalina clears the controller's hand without affecting her board presence.", replaces_hand_with_empty_enemy_hand, "打出前己方持Wisp与火球并清空敌方手牌，核对战吼清空己手且阿扎莉娜仍在场。"),
    ])


def duskhaven_hunter():
    cid = "GIL_200"

    def hand_form_swaps_attack_and_health_each_turn():
        g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=2001)
        p = g.player1
        p.give(cid)
        end_round(g)
        first = find_hand(p, "GIL_200", "GIL_200t")
        first_stats = None if first is None else (first.id, first.atk, first.health, first.zone.name)
        end_round(g)
        second = find_hand(p, "GIL_200", "GIL_200t")
        second_stats = None if second is None else (second.id, second.atk, second.health, second.zone.name)
        observed = f"first={first_stats};second={second_stats};active={[card_state(c) for c in p.hand]}"
        return checked(observed, first_stats is not None and first_stats[1:3] == (5, 2) and second_stats is not None and second_stats[1:3] == (2, 5) and second_stats[3] == "HAND")

    return audit(cid, [("hand_attack_health_swap_toggles", "While kept in hand, Duskhaven Hunter alternates its 2/5 and 5/2 Attack/Health forms at the start of its owner's successive turns.", hand_form_swaps_attack_and_health_each_turn, "连续推进两个真实己方回合，在每次变形后从当前手牌重新定位实体，断言5/2、2/5交替且仍在手牌。")])


def pumpkin_peasant():
    cid = "GIL_201"

    def in_hand_stats_swap_and_lifesteal_heals_after_attack():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=2011)
        p, e = g.player1, g.player2
        for _ in range(5):
            play(p, "CS2_008", target=p.hero)
        peasant_hand = p.give(cid)
        end_round(g)
        current = find_hand(p, cid, "GIL_201t")
        hand_stats = None if current is None else (current.id, current.atk, current.health, current.lifesteal)
        peasant = play(p, current.id)
        end_round(g)
        before_attack = p.hero.health
        attack = peasant.atk
        peasant.attack(e.hero)
        observed = f"original={peasant_hand.id}:{peasant_hand.zone.name};hand_form={hand_stats};board={peasant.id}:{peasant.atk}/{peasant.health}:lifesteal={peasant.lifesteal};hero={before_attack}->{p.hero.health};dealt={attack}"
        return checked(observed, current is not None and hand_stats is not None and hand_stats[1:3] == (4, 2) and peasant.zone == Zone.PLAY and peasant.lifesteal and p.hero.health == before_attack + attack and e.hero.health == 30 - attack)

    return audit(cid, [("hand_swap_and_lifesteal_attack", "Pumpkin Peasant swaps its 2/4 stats to 4/2 while in hand at its turn start; when played its Lifesteal attack restores the controller for damage dealt.", in_hand_stats_swap_and_lifesteal_heals_after_attack, "先实际降低己方英雄生命，推进Peasant手牌形态切换，再召唤并等到下一己方回合攻击敌方英雄；核对现行手牌形态、Lifesteal与治疗量。")])


def gilnean_royal_guard():
    cid = "GIL_202"

    def hand_swap_keeps_keywords_and_rush_only_hits_minions():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=2021)
        p, e = g.player1, g.player2
        enemy = summon(e, "CFM_039")
        p.give(cid)
        end_round(g)
        card = find_hand(p, cid, "GIL_202t")
        hand_stats = None if card is None else (card.id, card.atk, card.health)
        guard = play(p, card.id)
        can_minion, can_hero = guard.can_attack(enemy), guard.can_attack(e.hero)
        if can_minion:
            guard.attack(enemy)
        observed = f"hand_form={hand_stats};guard={guard.id}:{guard.atk}/{guard.health}:rush={guard.rush}:shield={guard.divine_shield};can_minion={can_minion};can_hero={can_hero};enemy={enemy.health};zone={guard.zone.name}"
        return checked(observed, hand_stats is not None and hand_stats[1:3] == (8, 3) and (guard.atk, guard.health, guard.rush, guard.divine_shield) == (8, 3, True, True) and can_minion and not can_hero and enemy.zone == Zone.GRAVEYARD and enemy not in e.field and guard.zone == Zone.PLAY)

    return audit(cid, [("hand_swap_and_rush_divine_shield", "In hand, the Guard swaps from 3/8 to 8/3; it retains Rush and Divine Shield, attacks an enemy minion immediately, and cannot attack the enemy hero that turn.", hand_swap_keeps_keywords_and_rush_only_hits_minions, "推进一个己方回合触发手牌形态切换，打出后检查Rush、圣盾；对7血目标实际攻击并确认只可选随从。")])


def rebuke():
    cid = "GIL_203"

    def enemy_spell_cost_increases_for_one_turn_then_expires():
        g = new_game(CardClass.PALADIN, CardClass.MAGE, seed=2031)
        p, e = g.player1, g.player2
        fireball_a, fireball_b = e.give("CS2_029"), e.give("CS2_029")
        play(p, cid)
        g.end_turn()
        cost_during = (fireball_a.cost, fireball_b.cost)
        mana_before = e.mana
        played = play(e, "CS2_029", target=p.hero)
        mana_after = e.mana
        g.end_turn()
        cost_after = fireball_b.cost
        observed = f"enemy_mana={mana_before}->{mana_after};cost_during={cost_during};played={played.zone.name};remaining_cost_after_expiry={cost_after};p_health={p.hero.health}"
        return checked(observed, cost_during == (9, 9) and mana_before == 10 and mana_after == 1 and played.zone == Zone.GRAVEYARD and cost_after == 4 and p.hero.health < 30)

    return audit(cid, [("enemy_spells_cost_five_more_until_next_turn", "Enemy spells cost 5 more during the opponent's next turn, then return to their normal costs at the Rebuke player's following turn.", enemy_spell_cost_increases_for_one_turn_then_expires, "对手预持两张4费火球；施放责难并结束回合，核对两张变9费；实际支付9费施放一张，再回到己方回合检查剩余火球恢复4费。")])


def phantom_militia():
    cid = "GIL_207"

    def echo_replays_taunt_minion_and_returns_next_copy():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=2071)
        p = g.player1
        first = play(p, cid)
        copy = find_hand(p, cid)
        first_state = (first.atk, first.health, first.taunt, first.zone)
        second = play(p, cid)
        observed = f"first={first_state};second={second.id}:{second.atk}/{second.health}:taunt={second.taunt}:{second.zone.name};echo_copy={card_state(find_hand(p,cid))};field_count={len(p.field)}"
        return checked(observed, first_state == (2, 4, True, Zone.PLAY) and copy is not None and second.zone == Zone.PLAY and (second.atk, second.health, second.taunt) == (2, 4, True) and find_hand(p, cid) is not None and len(p.field) == 2)

    return audit(cid, [("echo_taunt_minion_replays", "Phantom Militia is a 2/4 Taunt minion; Echo creates a hand copy that can be played again with the same body and Taunt.", echo_replays_taunt_minion_and_returns_next_copy, "连续打出两次实际回声民兵，检查首只和次只2/4嘲讽本体，以及回声副本再次回手。")])


def ravencaller():
    cid = "GIL_212"

    def adds_two_random_one_cost_minions():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=2121)
        p = g.player1
        play(p, cid)
        added = list(p.hand)
        observed = f"added={[card_state(c) for c in added]};count={len(added)}"
        return checked(observed, len(added) == 2 and all(c.type == CardType.MINION and c.cost == 1 and c.zone == Zone.HAND for c in added))

    return audit(cid, [("battlecry_gives_two_one_cost_minions", "Ravencaller's Battlecry adds exactly two random 1-Cost minions to hand.", adds_two_random_one_cost_minions, "空手牌实际打出唤鸦者，逐张检查新增牌的数量、随从类型、当前费用和手牌区。")])


def tanglefur_mystic():
    cid = "GIL_213"

    def gives_each_player_a_two_cost_minion():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=2131)
        p, e = g.player1, g.player2
        mystic = play(p, cid)
        observed = f"mystic={mystic.atk}/{mystic.health}:{mystic.zone.name};friendly_hand={[card_state(c) for c in p.hand]};enemy_hand={[card_state(c) for c in e.hand]}"
        return checked(observed, (mystic.atk, mystic.health, mystic.zone) == (3, 4, Zone.PLAY) and len(p.hand) == 1 and len(e.hand) == 1 and all(c.type == CardType.MINION and c.cost == 2 and c.zone == Zone.HAND for c in list(p.hand) + list(e.hand)))

    return audit(cid, [("battlecry_gives_one_two_cost_minion_each", "Tanglefur Mystic is a 3/4 and adds one random 2-Cost minion to each player's hand.", gives_each_player_a_two_cost_minion, "双方空手牌时实际打出，分别检查两侧生成手牌恰一张、类型为随从、当前费用为2；另核对3/4本体。")])


def hagatha_the_witch():
    cid = "GIL_504"

    def battlecry_damages_all_minions_and_passive_grants_spell():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE, seed=5041)
        p, e = g.player1, g.player2
        friendly_wisp = summon(p, WISP)
        friendly_large = summon(p, "CFM_039")
        enemy_large = summon(e, "CS2_179")
        p_hero_before, e_hero_before = p.hero.health, e.hero.health
        play(p, cid)
        hero = p.hero
        play(p, WISP)
        generated = list(p.hand)
        observed = f"hero={hero.id}:{hero.health};minions={friendly_wisp.zone.name}/{friendly_large.health}/{enemy_large.health};heroes={p_hero_before}->{p.hero.health},{e_hero_before}->{e.hero.health};new_minion={[m.id for m in p.field]};passive_cards={[card_state(c) for c in generated]}"
        return checked(observed, hero.id == cid and friendly_wisp.zone == Zone.GRAVEYARD and (friendly_large.health, enemy_large.health) == (4, 2) and (p.hero.health, e.hero.health) == (p_hero_before, e_hero_before) and any(m.id == WISP for m in p.field) and len(generated) == 1 and generated[0].type == CardType.SPELL and generated[0].card_class == CardClass.SHAMAN and generated[0].zone == Zone.HAND)

    return audit(cid, [("hero_battlecry_and_passive_spell_generation", "Hagatha's Battlecry deals 3 to all minions only; after her passive power is active, playing a minion adds one random Shaman spell to hand.", battlecry_damages_all_minions_and_passive_grants_spell, "以高血量友敌随从和Wisp实测英雄牌战吼，检查友敌生命/死亡区、双方英雄不变；随后实际打出Wisp并检查被动新加的Shaman法术。")])


def cheap_shot():
    cid = "GIL_506"

    def echo_repeats_damage_and_leaves_hand_copy():
        g = new_game(CardClass.ROGUE, CardClass.MAGE, seed=5061)
        p, e = g.player1, g.player2
        target = summon(e, "CFM_039")
        first_before, spellpower = target.health, p.spellpower
        first = play(p, cid, target=target)
        after_first = target.health
        copy = find_hand(p, cid)
        second = play(p, cid, target=target)
        expected = 2 + spellpower
        observed = f"target={first_before}->{after_first}->{target.health};spellpower={spellpower};echo_copy={None if copy is None else (copy.id,copy.zone.name)};spells={first.zone.name}/{second.zone.name}"
        return checked(observed, after_first == first_before - expected and target.health == after_first - expected and copy is not None and copy.zone == Zone.HAND and second.zone == Zone.GRAVEYARD)

    return audit(cid, [("echo_repeats_two_damage", "Each Echo cast deals 2 damage to its selected minion, increased by active Spell Damage, and Echo returns a second cast to hand.", echo_repeats_damage_and_leaves_hand_copy, "对7血高血量随从连续施放两次，按开局法伤核对每次扣血并检查回声副本与两张法术区。")])


def bewitched_guardian():
    cid = "GIL_507"

    def battlecry_gains_health_for_other_cards_in_hand():
        g = new_game(CardClass.DRUID, CardClass.MAGE, seed=5071)
        p = g.player1
        p.give(WISP)
        p.give("CS2_029")
        guardian = play(p, cid)
        observed = f"body={guardian.atk}/{guardian.health}/{guardian.max_health};taunt={guardian.taunt};other_hand={[c.id for c in p.hand]}"
        return checked(observed, (guardian.atk, guardian.health, guardian.max_health, guardian.taunt, guardian.zone) == (4, 3, 3, True, Zone.PLAY) and len(p.hand) == 2)

    def no_other_hand_cards_means_base_health():
        g = new_game(CardClass.DRUID, CardClass.MAGE, seed=5072)
        guardian = play(g.player1, cid)
        observed = f"body={guardian.atk}/{guardian.health}/{guardian.max_health};taunt={guardian.taunt}"
        return checked(observed, (guardian.atk, guardian.health, guardian.max_health, guardian.taunt) == (4, 1, 1, True))

    return audit(cid, [
        ("battlecry_counts_remaining_hand", "Bewitched Guardian gains +1 Health per other card remaining in hand when its Battlecry resolves, while retaining Taunt.", battlecry_gains_health_for_other_cards_in_hand, "打出前留两张手牌；随从离手后检查Guardian成长为4/3嘲讽且两张其他手牌未变。"),
        ("empty_hand_base_taunt_body", "With no other cards in hand, Bewitched Guardian remains its printed 4/1 Taunt body.", no_other_hand_cards_means_base_health, "空手牌实际打出后核对未凭空获得生命且保留嘲讽。"),
    ])


def duskbat():
    cid = "GIL_508"

    def undamaged_hero_does_not_enable_bats():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE, seed=5081)
        p = g.player1
        before = p.hero.health
        bat = play(p, cid)
        bats = [m for m in p.field if m.id == "GIL_508t"]
        observed = f"hero={before}->{p.hero.health};body={bat.atk}/{bat.health};bats={[(m.atk,m.health) for m in bats]};field={[m.id for m in p.field]}"
        return checked(observed, before == p.hero.health == 30 and len(bats) == 0 and (bat.atk, bat.health) == (2, 4))

    def hero_power_self_damage_enables_two_bats():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE, seed=5082)
        p = g.player1
        before = p.hero.health
        p.hero.power.use()
        after_power = p.hero.health
        bat = play(p, cid)
        bats = [m for m in p.field if m.id == "GIL_508t"]
        observed = f"hero={before}->{after_power};body={bat.atk}/{bat.health};bats={[(m.atk,m.health,m.zone.name) for m in bats]}"
        return checked(observed, after_power < before and len(bats) == 2 and all((m.atk, m.health, m.zone) == (1, 1, Zone.PLAY) for m in bats) and (bat.atk, bat.health) == (2, 4))

    return audit(cid, [
        ("no_damage_no_bats", "Without hero damage during this turn, Duskbat summons no Bats.", undamaged_hero_does_not_enable_bats, "未对己方英雄造成伤害直接打出Duskbat，核对本体和场上无蝙蝠。"),
        ("hero_damage_summons_two_bats", "After the controller's hero takes damage this turn, Duskbat summons exactly two 1/1 Bats.", hero_power_self_damage_enables_two_bats, "本回合先实际使用术士英雄技能触发自伤，再打出Duskbat，核对英雄生命变化、两只衍生物的身材与场区。"),
    ])


def mistwraith():
    cid = "GIL_510"

    def echo_play_gives_plus_one_plus_one_but_non_echo_does_not():
        g = new_game(CardClass.ROGUE, CardClass.MAGE, seed=5101)
        p = g.player1
        mist = summon(p, cid)
        before = (mist.atk, mist.health)
        play(p, "GIL_145", target=mist)
        after_echo = (mist.atk, mist.health)
        play(p, "CS2_008", target=p.hero)
        after_non_echo = (mist.atk, mist.health)
        observed = f"mist={before}->{after_echo}->{after_non_echo};echo_copy={find_hand(p,'GIL_145') is not None};hero={p.hero.health}"
        return checked(observed, before == (3, 5) and after_echo == (5, 8) and after_non_echo == after_echo and find_hand(p, "GIL_145") is not None)

    return audit(cid, [("echo_only_trigger_buffs_mistwraith", "Playing an Echo card gives Mistwraith +1/+1; playing a non-Echo card does not add another buff.", echo_play_gives_plus_one_plus_one_but_non_echo_does_not, "先实际打出回声法术并定位回手副本，再打出月火作为非Echo对照，前后读取迷雾幽灵身材。")])


def lost_spirit():
    cid = "GIL_513"

    def deathrattle_buffs_friendly_minions_not_enemy():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=5131)
        p, e = g.player1, g.player2
        spirit = summon(p, cid)
        friendly = summon(p, WISP)
        enemy = summon(e, WISP)
        play(p, "CS2_008", target=spirit)
        observed = f"spirit={spirit.zone.name};friendly={friendly.atk}/{friendly.health}:{friendly.zone.name};enemy={enemy.atk}/{enemy.health}:{enemy.zone.name}"
        return checked(observed, spirit.zone == Zone.GRAVEYARD and (friendly.atk, friendly.health, friendly.zone) == (2, 1, Zone.PLAY) and (enemy.atk, enemy.health, enemy.zone) == (1, 1, Zone.PLAY))

    return audit(cid, [("deathrattle_buffs_friendly_attack", "When Lost Spirit dies, its friendly minions gain +1 Attack and enemy minions remain unchanged.", deathrattle_buffs_friendly_minions_not_enemy, "实际击杀Lost Spirit，检查死亡区及友敌各一只Wisp的攻击力，确认只给友方加1攻击。")])


def ratcatcher():
    cid = "GIL_515"

    def destroys_target_and_gains_its_attack_and_current_health():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE, seed=5151)
        p, e = g.player1, g.player2
        target = summon(p, "CS2_182")
        play(p, "CS2_008", target=target)
        source_stats = (target.atk, target.health, target.max_health)
        catcher = play(p, cid, target=target)
        observed = f"sacrificed={source_stats}:{target.zone.name};catcher={catcher.id}:{catcher.atk}/{catcher.health}/{catcher.max_health}:rush={catcher.rush};enemy_field={[m.id for m in e.field]}"
        return checked(observed, target.zone == Zone.GRAVEYARD and (catcher.atk, catcher.health, catcher.max_health, catcher.rush, catcher.zone) == (2 + source_stats[0], 2 + source_stats[1], 2 + source_stats[1], True, Zone.PLAY) and target not in p.field)

    return audit(cid, [("battlecry_consumes_friendly_and_gains_stats", "Ratcatcher destroys the selected friendly minion and gains its Attack and Health while retaining Rush.", destroys_target_and_gains_its_attack_and_current_health, "将4/5友方Yeti实际预伤至4点当前生命，选择它作为战吼目标；核对目标墓地、捕鼠人获得4攻击与4当前生命加成、且Rush留存。")])


def wing_blast():
    cid = "GIL_518"

    def no_death_keeps_four_cost_and_deals_four_plus_spellpower():
        g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=5181)
        p, e = g.player1, g.player2
        target = summon(e, "CFM_039")
        spell = p.give(cid)
        before, cost, spellpower = target.health, spell.cost, p.spellpower
        play(p, cid, target=target)
        observed = f"cost={cost};target={before}->{target.health};spellpower={spellpower};zone={target.zone.name}"
        return checked(observed, cost == 4 and target.zone == Zone.PLAY and target.health == before - 4 - spellpower)

    def death_this_turn_reduces_cost_to_one():
        g = new_game(CardClass.HUNTER, CardClass.MAGE, seed=5182)
        p, e = g.player1, g.player2
        dead = summon(e, WISP)
        play(p, "CS2_008", target=dead)
        spell = p.give(cid)
        target = summon(e, "CFM_039")
        before, cost, spellpower = target.health, spell.cost, p.spellpower
        play(p, cid, target=target)
        observed = f"killed_this_turn={p.minions_killed_this_turn};cost={cost};target={before}->{target.health};spellpower={spellpower};dead_zone={dead.zone.name}"
        return checked(observed, dead.zone == Zone.GRAVEYARD and cost == 1 and target.zone == Zone.PLAY and target.health == before - 4 - spellpower)

    return audit(cid, [
        ("no_death_normal_cost", "Without a minion death this turn, Wing Blast costs 4 and deals 4 plus active Spell Damage to a minion.", no_death_keeps_four_cost_and_deals_four_plus_spellpower, "新局无死亡先记录卡牌费用与法伤，再对高血量随从施放并核对生命损失。"),
        ("death_this_turn_cost_one", "After a minion dies this turn, Wing Blast costs 1 while retaining its 4-damage effect plus Spell Damage.", death_this_turn_reduces_cost_to_one, "先用真实月火击杀敌方Wisp，再将飞翼冲击加入手牌检查降费，随后对高血量目标实测伤害。"),
    ])


def wyrmguard():
    cid = "GIL_526"

    def dragon_in_hand_grants_attack_and_taunt():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=5261)
        p = g.player1
        dragon = p.give("EX1_563")
        guard = play(p, cid)
        observed = f"held={dragon.id}:{dragon.race};guard={guard.atk}/{guard.health}:taunt={guard.taunt}:zone={guard.zone.name}"
        return checked(observed, dragon.zone == Zone.HAND and dragon.race == Race.DRAGON and (guard.atk, guard.health, guard.taunt, guard.zone) == (4, 11, True, Zone.PLAY))

    def no_dragon_keeps_base_body():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=5262)
        guard = play(g.player1, cid)
        observed = f"guard={guard.atk}/{guard.health}:taunt={guard.taunt}"
        return checked(observed, (guard.atk, guard.health, guard.taunt) == (3, 11, False))

    return audit(cid, [
        ("holding_dragon_gets_plus_attack_taunt", "Holding a Dragon as Wyrmguard enters play grants +1 Attack and Taunt.", dragon_in_hand_grants_attack_and_taunt, "手持真实龙族随从玛里苟斯后打出，检查龙留在手中且守卫成为4/11嘲讽。"),
        ("no_dragon_no_bonus", "Without a Dragon in hand, Wyrmguard remains a 3/11 without Taunt.", no_dragon_keeps_base_body, "空手牌直接打出并读取基础身材和嘲讽状态。"),
    ])


def felsoul_inquisitor():
    cid = "GIL_527"

    def attack_damages_enemy_and_lifesteal_heals_controller():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=5271)
        p, e = g.player1, g.player2
        for _ in range(5):
            play(p, "CS2_008", target=p.hero)
        inquisitor = summon(p, cid)
        target = summon(e, "CFM_039")
        end_round(g)
        before_hero = p.hero.health
        inquisitor.attack(target)
        observed = f"body={inquisitor.atk}/{inquisitor.health}:taunt={inquisitor.taunt}:lifesteal={inquisitor.lifesteal};hero={before_hero}->{p.hero.health};target={target.health}:{target.zone.name}"
        return checked(observed, (inquisitor.atk, inquisitor.taunt, inquisitor.lifesteal) == (1, True, True) and p.hero.health == before_hero + 1 and target.health == 6 and target.zone == Zone.PLAY)

    return audit(cid, [("taunt_lifesteal_attack_heals", "Felsoul Inquisitor is a 1/6 Taunt with Lifesteal; its 1-damage attack heals its controller for 1.", attack_damages_enemy_and_lifesteal_heals_controller, "实际预先损失己方英雄生命，召唤1/6嘲讽吸血随从并推进到就绪回合；攻击0攻高血目标后检查敌方伤害与自身回复。")])


def swift_messenger():
    cid = "GIL_528"

    def hand_swap_form_retains_rush_and_can_attack_minion():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=5281)
        p, e = g.player1, g.player2
        target = summon(e, "CFM_039")
        p.give(cid)
        end_round(g)
        active = find_hand(p, cid, "GIL_528t")
        snapshot = None if active is None else (active.id, active.atk, active.health)
        messenger = play(p, active.id)
        can_minion, can_hero = messenger.can_attack(target), messenger.can_attack(e.hero)
        messenger.attack(target)
        observed = f"hand_form={snapshot};messenger={messenger.id}:{messenger.atk}/{messenger.health}:rush={messenger.rush};can_minion={can_minion};can_hero={can_hero};target_zone={target.zone.name};messenger_zone={messenger.zone.name}"
        return checked(observed, snapshot is not None and snapshot[1:] == (6, 2) and (messenger.atk, messenger.health, messenger.rush) == (6, 2, True) and can_minion and not can_hero and target.health == 1 and target.zone == Zone.PLAY and messenger.zone == Zone.PLAY)

    return audit(cid, [("hand_swap_and_rush_target_limit", "Swift Messenger swaps from 2/6 to 6/2 while in hand; its Rush permits a same-turn attack on a minion but not the enemy hero.", hand_swap_form_retains_rush_and_can_attack_minion, "在手牌推进一轮后从当前手牌实体读取6/2形态，实际打出并攻击0攻7血敌方随从，验证Rush目标限制及双方实体最终区。")])


def spellshifter():
    cid = "GIL_529"

    def hand_swap_form_keeps_spell_damage():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=5291)
        p, e = g.player1, g.player2
        base_spellpower = p.spellpower
        p.give(cid)
        end_round(g)
        current = find_hand(p, cid, "GIL_529t")
        snapshot = None if current is None else (current.id, current.atk, current.health)
        minion = play(p, current.id)
        target = summon(e, "CFM_039")
        before, total_spellpower = target.health, p.spellpower
        play(p, "CS2_008", target=target)
        observed = f"hand_form={snapshot};body={minion.id}:{minion.atk}/{minion.health}:spellpower={minion.spellpower};player_spellpower={base_spellpower}->{total_spellpower};target={before}->{target.health}"
        return checked(observed, snapshot is not None and snapshot[1:] == (4, 1) and minion.zone == Zone.PLAY and minion.spellpower == 1 and total_spellpower == base_spellpower + 1 and target.health == before - 1 - total_spellpower)

    return audit(cid, [("hand_stats_swap_and_spell_damage_applies", "Spellshifter swaps from 1/4 to 4/1 in hand and provides Spell Damage +1 after being played; a spell's damage reflects that bonus.", hand_swap_form_keeps_spell_damage, "先记录基础法伤，推进一轮并在当前手牌定位4/1形态，打出后检查法伤关键字，再用月火对高血量目标核对基础伤害与总法伤。")])


def witchs_apprentice():
    cid = "GIL_531"

    def battlecry_adds_random_shaman_spell_and_keeps_taunt():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE, seed=5311)
        p = g.player1
        apprentice = play(p, cid)
        added = list(p.hand)
        observed = f"body={apprentice.atk}/{apprentice.health}:taunt={apprentice.taunt};hand={[card_state(c) for c in added]}"
        return checked(observed, (apprentice.atk, apprentice.health, apprentice.taunt, apprentice.zone) == (0, 1, True, Zone.PLAY) and len(added) == 1 and added[0].type == CardType.SPELL and added[0].card_class == CardClass.SHAMAN and added[0].zone == Zone.HAND)

    return audit(cid, [("battlecry_shaman_spell_and_taunt", "Witch's Apprentice is a 0/1 Taunt and adds one random Shaman spell to hand.", battlecry_adds_random_shaman_spell_and_keeps_taunt, "实际打出后检查0/1嘲讽本体与一张新增手牌的类型、职业及区。")])


def hench_clan_thug():
    cid = "GIL_534"

    def friendly_hero_attack_buffs_thug():
        g = new_game(CardClass.ROGUE, CardClass.MAGE, seed=5341)
        p, e = g.player1, g.player2
        thug = summon(p, cid)
        target = summon(e, "CFM_039")
        play(p, "CS2_091")
        before = (thug.atk, thug.health)
        p.hero.attack(target)
        observed = f"thug={before}->{(thug.atk,thug.health)};hero_attack={p.hero.atk};enemy_target={target.health}:{target.zone.name};weapon={p.weapon.id}:{p.weapon.durability}"
        return checked(observed, before == (3, 3) and (thug.atk, thug.health) == (4, 4) and target.health == 6 and p.weapon.durability == 3)

    return audit(cid, [("hero_attack_gives_thug_plus_one_plus_one", "After its controller's hero attacks, Hench-Clan Thug gains +1/+1.", friendly_hero_attack_buffs_thug, "先将荆棘帮暴徒与敌方高血量目标置场，再实际装备1攻武器并由英雄攻击，核对事件后暴徒成长、目标生命和武器耐久。")])


def deadly_arsenal():
    cid = "GIL_537"

    def reveals_weapon_attack_and_hits_every_minion():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=5371)
        p, e = g.player1, g.player2
        weapon = p.give("CS2_091")
        weapon.shuffle_into_deck()
        friendly = summon(p, "CFM_039")
        enemy = summon(e, "CS2_179")
        before = (friendly.health, enemy.health)
        spellpower = p.spellpower
        spell = play(p, cid)
        observed = f"weapon={weapon.id}:{weapon.zone.name}:in_deck={weapon in p.deck};minions={before}->{(friendly.health,enemy.health)};spell={spell.zone.name}"
        expected_damage = weapon.atk + spellpower
        return checked(observed, weapon.zone == Zone.DECK and weapon in p.deck and (friendly.health, enemy.health) == (before[0] - expected_damage, before[1] - expected_damage) and friendly.zone == enemy.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)

    def no_weapon_means_no_minion_damage():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE, seed=5372)
        p, e = g.player1, g.player2
        friendly, enemy = summon(p, "CFM_039"), summon(e, "CS2_179")
        before = (friendly.health, enemy.health)
        play(p, cid)
        observed = f"no_weapon_deck={[c.id for c in p.deck]};minions={before}->{(friendly.health,enemy.health)};zones={friendly.zone.name}/{enemy.zone.name}"
        return checked(observed, (friendly.health, enemy.health) == before and friendly.zone == enemy.zone == Zone.PLAY)

    return audit(cid, [
        ("weapon_attack_is_damage_to_all_minions", "With a 1-Attack weapon in deck, Deadly Arsenal reveals but does not draw it and deals its Attack plus active Spell Damage to every minion on both sides.", reveals_weapon_attack_and_hits_every_minion, "牌库仅放一把1攻武器，场上置放友敌高血随从；施放后核对武器仍在牌库、双方每只随从均损1攻加当前法伤。"),
        ("empty_weapon_deck_no_damage", "With no weapon in deck, Deadly Arsenal leaves minions unchanged.", no_weapon_means_no_minion_damage, "牌库无武器时对相同高血随从施放，核对双方当前生命与场区不变。"),
    ])


arcane_keysmith.card_id = "GIL_116"
worgen_abomination.card_id = "GIL_117"
deranged_doctor.card_id = "GIL_118"
cauldron_elemental.card_id = "GIL_119"
furious_ettin.card_id = "GIL_120"
darkmire_moonkin.card_id = "GIL_121"
mossy_horror.card_id = "GIL_124"
mad_hatter.card_id = "GIL_125"
emeriss.card_id = "GIL_128"
holy_water.card_id = "GIL_134"
chameleos.card_id = "GIL_142"
sound_the_bells.card_id = "GIL_145"
cinderstorm.card_id = "GIL_147"
blackhowl_gunspire.card_id = "GIL_152"
redband_wasp.card_id = "GIL_155"
quartz_elemental.card_id = "GIL_156"
druid_of_the_scythe.card_id = "GIL_188"
nightscale_matriarch.card_id = "GIL_190"
fiendish_circle.card_id = "GIL_191"
azalina_soulthief.card_id = "GIL_198"
duskhaven_hunter.card_id = "GIL_200"
pumpkin_peasant.card_id = "GIL_201"
gilnean_royal_guard.card_id = "GIL_202"
rebuke.card_id = "GIL_203"
phantom_militia.card_id = "GIL_207"
ravencaller.card_id = "GIL_212"
tanglefur_mystic.card_id = "GIL_213"
hagatha_the_witch.card_id = "GIL_504"
cheap_shot.card_id = "GIL_506"
bewitched_guardian.card_id = "GIL_507"
duskbat.card_id = "GIL_508"
mistwraith.card_id = "GIL_510"
lost_spirit.card_id = "GIL_513"
ratcatcher.card_id = "GIL_515"
wing_blast.card_id = "GIL_518"
wyrmguard.card_id = "GIL_526"
felsoul_inquisitor.card_id = "GIL_527"
swift_messenger.card_id = "GIL_528"
spellshifter.card_id = "GIL_529"
witchs_apprentice.card_id = "GIL_531"
hench_clan_thug.card_id = "GIL_534"
deadly_arsenal.card_id = "GIL_537"

AUDITS = [
    arcane_keysmith,
    worgen_abomination,
    deranged_doctor,
    cauldron_elemental,
    furious_ettin,
    darkmire_moonkin,
    mossy_horror,
    mad_hatter,
    emeriss,
    holy_water,
    chameleos,
    sound_the_bells,
    cinderstorm,
    blackhowl_gunspire,
    redband_wasp,
    quartz_elemental,
    druid_of_the_scythe,
    nightscale_matriarch,
    fiendish_circle,
    azalina_soulthief,
    duskhaven_hunter,
    pumpkin_peasant,
    gilnean_royal_guard,
    rebuke,
    phantom_militia,
    ravencaller,
    tanglefur_mystic,
    hagatha_the_witch,
    cheap_shot,
    bewitched_guardian,
    duskbat,
    mistwraith,
    lost_spirit,
    ratcatcher,
    wing_blast,
    wyrmguard,
    felsoul_inquisitor,
    swift_messenger,
    spellshifter,
    witchs_apprentice,
    hench_clan_thug,
    deadly_arsenal,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="zero-based roster index")
    parser.add_argument("--limit", type=int, default=42, help="number of cards to run")
    args = parser.parse_args()
    assert 0 <= args.start < 42 and 1 <= args.limit <= 42
    selected = AUDITS[args.start : args.start + args.limit]
    statuses = []
    for expected_id, fn in zip(OWN_IDS[args.start : args.start + args.limit], selected):
        assert expected_id == fn.card_id
        statuses.append(fn())
    from collections import Counter
    print(f"audited={len(statuses)} statuses={dict(Counter(statuses))}; roster={OWN_IDS[args.start:args.start + len(statuses)]}")


if __name__ == "__main__":
    main()
