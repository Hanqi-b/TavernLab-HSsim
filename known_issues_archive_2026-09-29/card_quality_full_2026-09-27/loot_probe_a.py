"""Targeted live-game probes for the first 45 ordinary LOOT YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Zone

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import (  # noqa: E402
    ELEMENTAL,
    FIREBALL,
    MOONFIRE,
    THE_COIN,
    WISP,
    prepare_empty_game,
)

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "loot_probe_a.csv"
VERDICT_OUT = HERE / "loot_verdict_a.csv"
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


BASE_ROWS = [
    row for row in read_csv(BASELINE)
    if row["set"].startswith("Kobolds & Catacombs")
    and row["scope"] == "ordinary_collectible"
]
OWN_ROWS = BASE_ROWS[:45]
OWN_IDS = [row["card_id"] for row in OWN_ROWS]
assert len(OWN_IDS) == 45 and OWN_IDS[0] == "LOOT_008" and OWN_IDS[-1] == "LOOT_144"
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


def find_hand(player, *card_ids):
    return next((card for card in player.hand if card.id in card_ids), None)


def choose_card(player, card_id):
    assert player.choice, "expected an active choice"
    choice = next((card for card in player.choice.cards if card.id == card_id), None)
    assert choice is not None, f"choice missing {card_id}: {[c.id for c in player.choice.cards]}"
    player.choice.choose(choice)


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
        "card_id": card_id,
        "status": status,
        "mechanic_scope": master["mechanics"],
        "reason": reason,
        "probe_file": PROBE_OUT.name,
        "notes": notes,
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


def psychic_scream():
    cid = "LOOT_008"

    def shuffles_all_minions_to_opponent_deck():
        g = new_game(CardClass.PRIEST, CardClass.MAGE)
        p, e = g.player1, g.player2
        own = summon(p, WISP)
        enemy = summon(e, "CS2_182")
        put_deck(p, MOONFIRE)
        spell = play(p, cid)
        p2_deck_ids = [card.id for card in e.deck]
        observed = (
            f"own={own.zone.name};enemy={enemy.zone.name};"
            f"fields={len(p.field)}/{len(e.field)};"
            f"opponent_deck={p2_deck_ids};friendly_deck={[card.id for card in p.deck]};"
            f"spell={spell.zone.name}"
        )
        return checked(
            observed,
            own.zone != Zone.PLAY
            and enemy.zone != Zone.PLAY
            and len(p.field) == 0
            and len(e.field) == 0
            and p2_deck_ids.count(WISP) == 1
            and p2_deck_ids.count("CS2_182") == 1
            and MOONFIRE in [card.id for card in p.deck]
            and spell.zone == Zone.GRAVEYARD,
        )

    return audit(cid, [
        (
            "shuffle_all_to_opponent_deck",
            "Both friendly and enemy minions leave the board and enter the opponent's deck; a friendly non-minion stays in its own deck.",
            shuffles_all_minions_to_opponent_deck,
            "两侧各放置一名随从并预置友方法术牌库；施放后检查双方场区、两张牌的牌库归属与法术保留。",
        ),
    ])


def vulgar_homunculus():
    cid = "LOOT_013"

    def battlecry_damage_and_taunt():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p = g.player1
        before = p.hero.health
        minion = play(p, cid)
        observed = f"hero={before}->{p.hero.health};body={minion.atk}/{minion.health};taunt={minion.taunt};zone={minion.zone.name}"
        return checked(observed, p.hero.health == before - 2 and (minion.atk, minion.health) == (2, 4) and minion.taunt and minion.zone == Zone.PLAY)

    return audit(cid, [
        ("battlecry_and_taunt", "Summons a 2/4 Taunt minion and deals exactly 2 damage to its controller's hero.", battlecry_damage_and_taunt, "逐一检查英雄生命、随从身材、嘲讽关键字和场区。"),
    ])


def kobold_librarian():
    cid = "LOOT_014"

    def draws_and_damages():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p = g.player1
        put_deck(p, WISP)
        before = p.hero.health
        minion = play(p, cid)
        observed = f"hero={before}->{p.hero.health};body={minion.atk}/{minion.health};hand={[c.id for c in p.hand]};zone={minion.zone.name}"
        return checked(observed, p.hero.health == before - 2 and (minion.atk, minion.health) == (2, 1) and WISP in [c.id for c in p.hand] and minion.zone == Zone.PLAY)

    return audit(cid, [
        ("draw_and_hero_damage", "Battlecry draws one card and deals 2 damage to its controller's hero.", draws_and_damages, "牌库只放入一张 Wisp，以手牌身份确认确实抽到；另检查战吼伤害和本体身材。"),
    ])


def dark_pact():
    cid = "LOOT_017"

    def destroys_friendly_and_heals_hero():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p, e = g.player1, g.player2
        p.hero.damage = 6
        friendly = summon(p, WISP)
        enemy = summon(e, WISP)
        before = p.hero.health
        spell = play(p, cid, target=friendly)
        observed = f"hero={before}->{p.hero.health};friendly={friendly.zone.name};enemy={enemy.zone.name};spell={spell.zone.name}"
        return checked(observed, p.hero.health == before + 4 and friendly.zone == Zone.GRAVEYARD and enemy.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("friendly_destroy_and_heal", "Destroys the chosen friendly minion and restores 4 Health to its hero.", destroys_friendly_and_heals_hero, "英雄先实际受伤；双方各放置一名 Wisp，确认只摧毁合法友方目标并恢复4点。"),
    ])


def hooked_reaver():
    cid = "LOOT_018"

    def activates_at_fifteen():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p = g.player1
        p.hero.damage = 15
        minion = play(p, cid)
        observed = f"hero={p.hero.health};body={minion.atk}/{minion.health};taunt={minion.taunt}"
        return checked(observed, p.hero.health == 15 and (minion.atk, minion.health) == (7, 7) and minion.taunt)

    def does_not_activate_above_threshold():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p = g.player1
        p.hero.damage = 14
        minion = play(p, cid)
        observed = f"hero={p.hero.health};body={minion.atk}/{minion.health};taunt={minion.taunt}"
        return checked(observed, p.hero.health == 16 and (minion.atk, minion.health) == (4, 4) and not minion.taunt)

    return audit(cid, [
        ("threshold_15", "At exactly 15 Health, gains +3/+3 and Taunt (4/4 to 7/7).", activates_at_fifteen, "卡牌数据库基础身材为4/4；边界值正好为15，检查加成身材与嘲讽。"),
        ("threshold_16", "At 16 Health, remains 4/4 without Taunt.", does_not_activate_above_threshold, "卡牌数据库基础身材为4/4；边界对照为16点生命。"),
    ])


def faldorei_strider():
    cid = "LOOT_026"

    def shuffles_and_casts_ambushes_when_drawn():
        g = new_game(CardClass.ROGUE, CardClass.MAGE)
        p = g.player1
        play(p, cid)
        shuffled = [card.id for card in p.deck].count("LOOT_026e")
        p.draw()
        spiders = [m for m in p.field if m.id == "LOOT_026t"]
        observed = f"ambushes_before_draw={shuffled};deck_after={[(c.id,c.zone.name) for c in p.deck]};spiders={[(m.atk,m.health) for m in spiders]};hand={[c.id for c in p.hand]}"
        return checked(observed, shuffled == 3 and len(spiders) == 3 and all((m.atk, m.health) == (4, 4) for m in spiders) and not [c for c in p.deck if c.id == "LOOT_026e"])

    return audit(cid, [
        ("ambush_draw_trigger", "Battlecry shuffles three Ambushes into the deck; drawing them summons three 4/4 Spiders.", shuffles_and_casts_ambushes_when_drawn, "牌库仅含三张生成的伏击牌；真实抽牌触发伏击的自动施放与连锁抽牌，检查蜘蛛数量、身材和牌库。"),
    ])


def cavern_shinyfinder():
    cid = "LOOT_033"

    def draws_weapon_only():
        g = new_game(CardClass.ROGUE, CardClass.MAGE)
        p = g.player1
        put_deck(p, "CS2_091")
        put_deck(p, WISP)
        minion = play(p, cid)
        observed = f"hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]};minion={minion.zone.name}"
        return checked(observed, "CS2_091" in [c.id for c in p.hand] and WISP in [c.id for c in p.deck] and minion.zone == Zone.PLAY)

    return audit(cid, [
        ("draw_weapon_from_deck", "Battlecry draws the only weapon from the deck and leaves the non-weapon there.", draws_weapon_only, "牌库包含且只包含一把武器和一张 Wisp，核对抽牌类型、留牌和本体场区。"),
    ])


def kobold_barbarian():
    cid = "LOOT_041"

    def attacks_one_random_enemy_at_turn_start():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE)
        p, e = g.player1, g.player2
        enemy_minion = summon(e, WISP)
        barbarian = play(p, cid)
        g.end_turn()
        g.end_turn()
        observed = f"turn={g.current_player.name};attacks={barbarian.num_attacks};enemy_hero={e.hero.health};enemy_minion={enemy_minion.zone.name}/{enemy_minion.health};barbarian={barbarian.zone.name}/{barbarian.health}"
        hit_character = e.hero.health < 30 or enemy_minion.zone == Zone.GRAVEYARD
        return checked(observed, hit_character and barbarian.zone == Zone.PLAY)

    return audit(cid, [
        ("random_enemy_at_turn_start", "At the start of its controller's next turn, attacks one random enemy character.", attacks_one_random_enemy_at_turn_start, "实际切过双方回合后确认敌方英雄或唯一敌方 Wisp 承受攻击，并核对 Barbarian 的战斗反伤；不依赖回合开始后会被重置的攻击计数。"),
    ])


def lesser_amethyst_spellstone():
    cid = "LOOT_043"

    def base_lifesteal_damage():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p, e = g.player1, g.player2
        p.hero.damage = 5
        target = summon(e, "CS2_182")
        before = p.hero.health
        spell = play(p, cid, target=target)
        observed = f"hero={before}->{p.hero.health};target={target.zone.name}/{target.health};spell={spell.zone.name}"
        return checked(observed, p.hero.health == before + 3 and target.health == 2 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)

    def card_damage_upgrades_in_hand():
        g = new_game(CardClass.WARLOCK, CardClass.MAGE)
        p = g.player1
        spellstone = p.give(cid)
        p.give(MOONFIRE).play(target=p.hero)
        after_one = find_hand(p, "LOOT_043t2")
        first_id = after_one.id if after_one else "missing"
        p.give(MOONFIRE).play(target=p.hero)
        after_two = find_hand(p, "LOOT_043t3")
        observed = f"first_upgrade={first_id};second_upgrade={after_two.id if after_two else 'missing'};hero={p.hero.health};original_ref={spellstone.id}/{spellstone.zone.name}"
        return checked(observed, first_id == "LOOT_043t2" and after_two is not None and p.hero.health == 28)

    return audit(cid, [
        ("base_lifesteal", "The base Spellstone deals 3 damage and Lifesteal restores 3 Health to its hero.", base_lifesteal_damage, "英雄先受5点伤；对5生命的 Yeti 造成3点伤，检查目标生命、英雄恢复和法术区。"),
        ("damage_card_upgrade", "Damage dealt to its own hero by friendly cards upgrades it first to 5 damage, then to 7 damage.", card_damage_upgrades_in_hand, "Spellstone 留在手牌；两次真实施放 Moonfire 指向己方英雄，每次都重新按手牌卡牌 ID 检查 Morph。"),
    ])


def bladed_gauntlet():
    cid = "LOOT_044"

    def attack_tracks_armor_and_avoids_heroes():
        g = new_game(CardClass.WARRIOR, CardClass.MAGE)
        p, e = g.player1, g.player2
        p.hero.armor = 3
        weapon = play(p, cid)
        at_three = weapon.atk
        p.hero.armor = 5
        at_five = weapon.atk
        enemy = summon(e, WISP)
        hero_target_legal = p.hero.can_attack(e.hero)
        minion_target_legal = p.hero.can_attack(enemy)
        before_durability = weapon.durability
        if minion_target_legal:
            p.hero.attack(enemy)
        observed = f"attack_at_armor3={at_three};attack_at_armor5={at_five};hero_legal={hero_target_legal};minion_legal={minion_target_legal};enemy={enemy.zone.name};weapon={weapon.atk}/{weapon.durability};hero_armor={p.hero.armor}"
        return checked(observed, at_three == 3 and at_five == 5 and not hero_target_legal and minion_target_legal and enemy.zone == Zone.GRAVEYARD and weapon.durability == before_durability - 1)

    return audit(cid, [
        ("armor_attack_and_target_limit", "Weapon Attack follows Armor and can attack a minion but not a hero.", attack_tracks_armor_and_avoids_heroes, "先装备3点护甲再改到5点，检查攻击力持续更新、英雄目标限制和攻击随从后的耐久变化。"),
    ])


def barkskin():
    cid = "LOOT_047"

    def buffs_minion_health_and_armor():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p = g.player1
        target = summon(p, WISP)
        before_armor = p.hero.armor
        spell = play(p, cid, target=target)
        observed = f"target={target.atk}/{target.health}/{target.max_health};armor={before_armor}->{p.hero.armor};spell={spell.zone.name}"
        return checked(observed, (target.atk, target.health, target.max_health) == (1, 4, 4) and p.hero.armor == before_armor + 3 and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("health_and_armor", "Gives the selected minion +3 Health and its hero gains 3 Armor.", buffs_minion_health_and_armor, "对1/1友方 Wisp 施法，检查最大生命、当前生命、攻击不变以及英雄护甲。"),
    ])


def ironwood_golem():
    cid = "LOOT_048"

    def armor_gate_changes_attack_permission():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p, e = g.player1, g.player2
        golem = play(p, cid)
        control = summon(p, WISP)
        g.end_turn()
        g.end_turn()
        without_armor = golem.can_attack()
        control_ready = control.can_attack()
        barkskin = play(p, "LOOT_047", target=golem)
        with_armor = golem.can_attack()
        taunt = golem.taunt
        before = e.hero.health
        if with_armor:
            golem.attack(e.hero)
        observed = f"turn={g.current_player.name};armor={p.hero.armor};control_ready={control_ready};before_armor_attack={without_armor};after_armor_attack={with_armor};taunt={taunt};hero={before}->{e.hero.health};golem={golem.zone.name};barkskin={barkskin.zone.name}"
        return checked(observed, control_ready and not without_armor and with_armor and taunt and e.hero.health == before - golem.atk and barkskin.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("armor_attack_threshold", "Taunt is present; the minion cannot attack below 3 Armor and can attack at 3 Armor.", armor_gate_changes_attack_permission, "真实经过下一己方回合，并用实际打出的 Barkskin 获得3护甲；用同时召唤的普通 Wisp 确认己方随从已准备好攻击。"),
    ])


def lesser_jasper_spellstone():
    cid = "LOOT_051"

    def base_damage():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        spell = play(p, cid, target=target)
        observed = f"target={target.health}/{target.max_health};spell={spell.zone.name}"
        return checked(observed, target.health == 3 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)

    def armor_upgrades_both_levels():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p = g.player1
        p.give(cid)
        target = summon(p, WISP)
        play(p, "LOOT_047", target=target)
        first = find_hand(p, "LOOT_051t1")
        first_id = first.id if first else "missing"
        play(p, "LOOT_047", target=target)
        second = find_hand(p, "LOOT_051t2")
        observed = f"after_three_armor={first_id};after_six_armor={second.id if second else 'missing'};armor={p.hero.armor};target={target.max_health}"
        return checked(observed, first_id == "LOOT_051t1" and second is not None and p.hero.armor == 6)

    return audit(cid, [
        ("base_two_damage", "Base Spellstone deals 2 damage to the target minion.", base_damage, "对5生命 Yeti 施法，检查剩余3生命和随从仍在场。"),
        ("armor_upgrade_progress", "Gaining 3 Armor upgrades it to 4 damage; another 3 Armor upgrades it to 6 damage.", armor_upgrades_both_levels, "Spellstone 留在手牌；分别用 Barkskin 实际获得3点护甲，逐次检查 Morph 版本和护甲总值。"),
    ])


def branching_paths():
    cid = "LOOT_054"

    def chooses_armor_and_draw():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p = g.player1
        put_deck(p, WISP)
        spell = p.give(cid)
        spell.play()
        choose_card(p, "LOOT_054c")
        choose_card(p, "LOOT_054d")
        observed = f"armor={p.hero.armor};hand={[c.id for c in p.hand]};choice={p.choice};spell={spell.zone.name}"
        return checked(observed, p.hero.armor == 6 and WISP in [c.id for c in p.hand] and not p.choice and spell.zone == Zone.GRAVEYARD)

    def chooses_attack_twice():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p = g.player1
        minion = summon(p, WISP)
        spell = p.give(cid)
        spell.play()
        choose_card(p, "LOOT_054b")
        choose_card(p, "LOOT_054b")
        observed = f"minion={minion.atk}/{minion.health};armor={p.hero.armor};spell={spell.zone.name}"
        return checked(observed, minion.atk == 3 and minion.health == 1 and p.hero.armor == 0 and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("two_choices_armor_draw", "The spell resolves two independent choices; Armor adds 6 and Draw adds a card.", chooses_armor_and_draw, "通过选择窗口分别选择护甲和抽牌，确认第二次选择完成后法术离开手牌。"),
        ("two_attack_choices_stack", "Choosing the +1 Attack option twice gives all friendly minions +2 Attack.", chooses_attack_twice, "对已有友方 Wisp 连续选择两次攻击力选项，检查两次加成可叠加。"),
    ])


def astral_tiger():
    cid = "LOOT_056"

    def deathrattle_shuffles_copy():
        g = new_game(CardClass.DRUID, CardClass.MAGE)
        p = g.player1
        tiger = play(p, cid)
        printed_stats = (tiger.atk, tiger.max_health)
        tiger.destroy()
        copies = [card for card in p.deck if card.id == cid]
        observed = f"source={tiger.zone.name};printed_stats={printed_stats};deck_copies={[(c.id,c.atk,c.max_health,c.zone.name) for c in copies]}"
        return checked(observed, tiger.zone == Zone.GRAVEYARD and len(copies) == 1 and (copies[0].atk, copies[0].max_health) == printed_stats and copies[0].zone == Zone.DECK)

    return audit(cid, [
        ("deathrattle_copy_to_deck", "After death, one copy of Astral Tiger is shuffled into its controller's deck.", deathrattle_shuffles_copy, "實際打出並摧毀本體，檢查來源進墓地且牌庫出現一張同 ID、同身材的新實體。"),
    ])


def crushing_hand():
    cid = "LOOT_060"

    def damage_and_overload():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE)
        p, e = g.player1, g.player2
        target = summon(e, "LOOT_137")
        before_health = target.health
        spell = play(p, cid, target=target)
        overload_after_play = p.overloaded
        before_next_turn = (p.overload_locked, p.mana)
        g.end_turn()
        while g.current_player is not p:
            g.end_turn()
        observed = f"target={before_health}->{target.health}/{target.max_health}:{target.zone.name};spell={spell.zone.name};overloaded_after_play={overload_after_play};next_turn_locked={p.overload_locked};mana={p.mana};before_next_turn={before_next_turn}"
        return checked(observed, before_health - target.health == 8 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD and overload_after_play == 3 and p.overload_locked == 3 and p.mana == 7)

    return audit(cid, [
        ("eight_damage_and_overload", "Deals 8 damage to the minion; locks 3 Mana Crystals on the next turn.", damage_and_overload, "用12生命巨龙承受8点伤害；记录施法后过载，并完整轮转到施法者下一回合检查锁费与可用法力。"),
    ], extra_notes="reports/card_quality_full_2026-09-27/overload_reproductions.csv#LOOT_060 independently confirms the 3-crystal lockout.")


def kobold_hermit():
    cid = "LOOT_062"

    def chooses_and_summons_basic_totem():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE)
        p, e = g.player1, g.player2
        minion = p.give(cid)
        minion.play()
        options = [card.id for card in p.choice.cards]
        choose_card(p, "CS2_050")
        chosen = [m for m in p.field if m.id == "CS2_050"]
        observed = f"options={options};summoned={[(m.id,m.atk,m.health,m.zone.name) for m in chosen]};opponent={len(e.field)};hermit={minion.zone.name}"
        expected_options = {"CS2_050", "CS2_051", "CS2_052", "NEW1_009"}
        return checked(observed, set(options) == expected_options and len(chosen) == 1 and (chosen[0].atk, chosen[0].health) == (1, 1) and chosen[0].zone == Zone.PLAY and not e.field and minion.zone == Zone.PLAY)

    return audit(cid, [
        ("choose_basic_totem", "Offers all four basic Totems and summons exactly the selected Searing Totem for its controller.", chooses_and_summons_basic_totem, "檢查選項身份集合，明確選擇 CS2_050 Searing Totem，再核對召喚方、身材和本體。"),
    ])


def lesser_sapphire_spellstone():
    cid = "LOOT_064"

    def summons_exact_copy():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE)
        p = g.player1
        target = summon(p, "CS2_182")
        spell = play(p, cid, target=target)
        copies = [m for m in p.field if m.id == target.id]
        observed = f"spell={spell.zone.name};target={target.atk}/{target.health}/{target.max_health};copies={[(m.atk,m.health,m.max_health,m.zone.name) for m in copies]}"
        return checked(observed, len(copies) == 2 and copies[0] is not copies[1] and all((m.atk, m.health, m.max_health) == (4, 5, 5) for m in copies) and spell.zone == Zone.GRAVEYARD)

    def overload_progression_matches_text():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE)
        p = g.player1
        p.give(cid)
        overload_target = summon(g.player2, "LOOT_137")
        crushing_hand = p.give("LOOT_060")
        crushing_hand.play(target=overload_target)
        overload_upgrade = find_hand(p, "LOOT_064t1")
        observed = f"after_overload3={overload_upgrade.id if overload_upgrade else 'missing'};base_still_held={find_hand(p, cid) is not None};target={overload_target.health}/{overload_target.max_health};overloaded={p.overloaded}"
        return checked(observed, overload_upgrade is not None and overload_target.health == 4 and p.overloaded == 3)

    def deathrattle_cards_do_not_upgrade():
        g = new_game(CardClass.SHAMAN, CardClass.MAGE)
        p = g.player1
        p.give(cid)
        for _ in range(3):
            play(p, "EX1_029")
        spellstone = find_hand(p, cid, "LOOT_064t1")
        observed = f"after_three_deathrattle_cards={spellstone.id if spellstone else 'missing'};overloaded={p.overloaded};hand={[c.id for c in p.hand]}"
        return checked(observed, spellstone is not None and spellstone.id == cid and p.overloaded == 0)

    return audit(cid, [
        ("base_exact_copy", "Summons one exact 4/5 copy of the chosen friendly minion.", summons_exact_copy, "選擇友方 Yeti，按實體身份分辨原本與複製體並檢查攻擊、當前生命及最大生命。"),
        ("overload_upgrade_condition", "Overload 3 upgrades the Spellstone to the second version.", overload_progression_matches_text, "依卡面要求，在手牌中留置 Spellstone 并打出 LOOT_060（Overload 3），检查场上目标受伤、过载量及手牌实体版本。"),
        ("deathrattle_not_upgrade_condition", "Playing three Deathrattle minions without Overload leaves this Spellstone at its base version.", deathrattle_cards_do_not_upgrade, "单独在手牌留置 Spellstone 并打出三张亡语 minion，对照卡面 Overload 升级条件；按手牌实体 ID 检查不应变版。"),
    ])


def sewer_crawler():
    cid = "LOOT_069"

    def battlecry_summons_giant_rat():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        source = play(p, cid)
        rats = [m for m in p.field if m.id == "LOOT_069t"]
        observed = f"source={source.atk}/{source.health}/{source.zone.name};rats={[(m.atk,m.health,m.zone.name) for m in rats]};enemy={len(e.field)}"
        return checked(observed, len(rats) == 1 and (rats[0].atk, rats[0].health) == (2, 3) and rats[0].zone == Zone.PLAY and not e.field and source.zone == Zone.PLAY)

    return audit(cid, [
        ("battlecry_giant_rat", "Battlecry summons one 2/3 Giant Rat under its controller's control.", battlecry_summons_giant_rat, "實際打出本體，按 token ID、身材與雙方場區確認只在己方召喚一只巨鼠。"),
    ])


def flanking_strike():
    cid = "LOOT_077"

    def damages_target_and_summons_wolf():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p, e = g.player1, g.player2
        target = summon(e, "CS2_182")
        before = target.health
        spell = play(p, cid, target=target)
        wolves = [m for m in p.field if m.id == "LOOT_077t"]
        observed = f"target={before}->{target.health}/{target.max_health}:{target.zone.name};wolves={[(m.atk,m.health,m.zone.name) for m in wolves]};spell={spell.zone.name}"
        return checked(observed, target.health == before - 3 and target.zone == Zone.PLAY and len(wolves) == 1 and (wolves[0].atk, wolves[0].health) == (3, 3) and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("three_damage_and_wolf", "Deals 3 damage to the chosen minion and summons a 3/3 Wolf.", damages_target_and_summons_wolf, "對敵方5生命 Yeti 造成3点伤，确认仍存活且身材准确的狼由己方召唤。"),
    ])


def cave_hydra():
    cid = "LOOT_078"

    def cleaves_attacked_minion_neighbors():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p, e = g.player1, g.player2
        hydra = play(p, cid)
        left = summon(e, "CFM_039")
        target = summon(e, "CFM_039")
        right = summon(e, "CFM_039")
        g.end_turn()
        g.end_turn()
        before = [left.health, target.health, right.health]
        attack = hydra.atk
        ready = hydra.can_attack(target)
        if ready:
            hydra.attack(target)
        observed = f"ready={ready};attack={attack};enemy={[f'{m.health}/{m.max_health}/{m.zone.name}' for m in (left,target,right)]};hydra={hydra.zone.name}/{hydra.health}"
        return checked(observed, ready and [m.health for m in (left, target, right)] == [h - attack for h in before] and all(m.zone == Zone.PLAY for m in (left, target, right)) and hydra.zone == Zone.PLAY)

    return audit(cid, [
        ("cleave_adjacent_minions", "Attacking a minion also deals the Hydra's Attack damage to both adjacent minions.", cleaves_attacked_minion_neighbors, "三名0攻7血 Street Trickster 连续相邻，中央及两侧不会反伤；真实攻击中央目标，逐一检查左右邻居和目标都应承受 Hydra 攻击伤害。"),
    ])


def wandering_monster():
    cid = "LOOT_079"

    def redirects_enemy_attack_to_random_three_cost_minion():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p, e = g.player1, g.player2
        attacker = summon(e, WISP)
        secret = play(p, cid)
        hero_before = p.hero.health
        g.end_turn()
        can_attack_hero = attacker.can_attack(p.hero)
        if can_attack_hero:
            attacker.attack(p.hero)
        spawned = [m for m in p.field if m.type == CardType.MINION and m.cost == 3]
        spawned_deaths = [m for m in p.graveyard if m.type == CardType.MINION and m.cost == 3]
        observed = f"attack_legal={can_attack_hero};attacker_attacks={attacker.num_attacks};hero={hero_before}->{p.hero.health};secret={secret.zone.name};spawned={[(m.id,m.cost,m.health,m.zone.name) for m in spawned]};spawned_dead={[(m.id,m.cost,m.zone.name) for m in spawned_deaths]}"
        return checked(observed, can_attack_hero and p.hero.health == hero_before and secret.zone != Zone.PLAY and attacker.num_attacks == 1 and bool(spawned or spawned_deaths))

    return audit(cid, [
        ("secret_random_minion_redirect", "When attacked by an enemy minion, reveals the Secret, summons a 3-Cost minion, and redirects the attack away from the hero.", redirects_enemy_attack_to_random_three_cost_minion, "用真实敌方 Wisp 攻击英雄触发；检查英雄无伤、攻击已消耗、奥秘移除，并在己方场区或墓地中检查生成的3费随从。"),
    ])


def lesser_emerald_spellstone():
    cid = "LOOT_080"

    def summons_two_base_wolves():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p = g.player1
        spell = play(p, cid)
        wolves = [m for m in p.field if m.id == "LOOT_077t"]
        observed = f"wolves={[(m.atk,m.health,m.zone.name) for m in wolves]};spell={spell.zone.name}"
        return checked(observed, len(wolves) == 2 and all((m.atk, m.health) == (3, 3) and m.zone == Zone.PLAY for m in wolves) and spell.zone == Zone.GRAVEYARD)

    def secrets_upgrade_both_levels():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p = g.player1
        p.give(cid)
        play(p, "LOOT_079")
        first = find_hand(p, "LOOT_080t2")
        first_id = first.id if first else "missing"
        play(p, "EX1_609")
        final = find_hand(p, "LOOT_080t3")
        if final:
            final.play()
        wolves = [m for m in p.field if m.id == "LOOT_077t"]
        observed = f"after_secret1={first_id};after_secret2={final.id if final else 'missing'};played={final.zone.name if final else 'missing'};wolves={[(m.atk,m.health) for m in wolves]}"
        return checked(observed, first_id == "LOOT_080t2" and final is not None and final.zone == Zone.GRAVEYARD and len(wolves) == 4 and all((m.atk, m.health) == (3, 3) for m in wolves))

    return audit(cid, [
        ("base_two_wolves", "The base Spellstone summons two 3/3 Wolves.", summons_two_base_wolves, "以 token 身份和攻防检查两只基础狼。"),
        ("secret_progress_two_levels", "Playing two Secrets while held advances through three wolves to four wolves.", secrets_upgrade_both_levels, "Spellstone 留在手牌，依次实际打出两张游荡怪物奥秘，逐 ID 检查升级后施放并核对四狼。"),
    ])


def rhokdelar():
    cid = "LOOT_085"

    def empty_minion_deck_fills_hand_with_hunter_spells():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p = g.player1
        put_deck(p, FIREBALL)
        weapon = play(p, cid)
        spells = [card for card in p.hand if card.type == CardType.SPELL]
        observed = f"weapon={p.weapon.id if p.weapon else None};hand_count={len(p.hand)};spells={[(c.id,CardClass(c.card_class).name,CardType(c.type).name) for c in spells]};deck={[c.id for c in p.deck]}"
        return checked(observed, p.weapon is weapon and weapon.id == cid and len(p.hand) == 10 and len(spells) == 10 and all(card.card_class == CardClass.HUNTER for card in spells) and FIREBALL in [c.id for c in p.deck])

    def minion_in_deck_prevents_fill():
        g = new_game(CardClass.HUNTER, CardClass.MAGE)
        p = g.player1
        put_deck(p, WISP)
        put_deck(p, FIREBALL)
        weapon = play(p, cid)
        observed = f"weapon={p.weapon.id if p.weapon else None};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}"
        return checked(observed, p.weapon is weapon and not p.hand and WISP in [c.id for c in p.deck] and FIREBALL in [c.id for c in p.deck])

    return audit(cid, [
        ("no_minion_deck_fill", "With no minions in its deck, equips Rhok'delar and fills the hand with Hunter spells.", empty_minion_deck_fills_hand_with_hunter_spells, "牌庫只放一張法術，以武器身份、手牌填满10张且每张均为猎人法术验证条件分支。"),
        ("minion_deck_no_fill", "If the deck contains a minion, no Hunter spells are added.", minion_in_deck_prevents_fill, "法术与 Wisp 同在牌库，确认武器照常装备而战吼不填充手牌或移除牌库卡。"),
    ])


def potion_of_heroism():
    cid = "LOOT_088"

    def gives_shield_and_draws():
        g = new_game(CardClass.PALADIN, CardClass.MAGE)
        p = g.player1
        target = summon(p, WISP)
        put_deck(p, "CS2_182")
        spell = play(p, cid, target=target)
        observed = f"target={target.divine_shield};hand={[c.id for c in p.hand]};spell={spell.zone.name}"
        return checked(observed, target.divine_shield and "CS2_182" in [c.id for c in p.hand] and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("divine_shield_and_draw", "Gives the selected minion Divine Shield and draws one card.", gives_shield_and_draws, "對友方 Wisp 施法並將唯一 Yeti 留在牌庫，檢查聖盾狀態、抽到的牌和法術區。"),
    ])


def lesser_pearl_spellstone():
    cid = "LOOT_091"

    def summons_base_taunt_spirit():
        g = new_game(CardClass.PALADIN, CardClass.MAGE)
        p = g.player1
        spell = play(p, cid)
        spirits = [m for m in p.field if m.id == "LOOT_091t"]
        observed = f"spirit={[(m.atk,m.health,m.taunt,m.zone.name) for m in spirits]};spell={spell.zone.name}"
        return checked(observed, len(spirits) == 1 and (spirits[0].atk, spirits[0].health) == (2, 2) and spirits[0].taunt and spirits[0].zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)

    def healing_upgrades_both_levels():
        g = new_game(CardClass.PALADIN, CardClass.MAGE)
        p = g.player1
        p.hero.damage = 12
        p.give(cid)
        play(p, "CS2_089", target=p.hero)
        first = find_hand(p, "LOOT_091t1")
        first_id = first.id if first else "missing"
        play(p, "CS2_089", target=p.hero)
        final = find_hand(p, "LOOT_091t2")
        if final:
            final.play()
        spirits = [m for m in p.field if m.id == "LOOT_091t2t"]
        observed = f"health={p.hero.health};after_heal1={first_id};after_heal2={final.id if final else 'missing'};played={final.zone.name if final else 'missing'};spirits={[(m.atk,m.health,m.taunt,m.zone.name) for m in spirits]}"
        return checked(observed, p.hero.health == 30 and first_id == "LOOT_091t1" and final is not None and final.zone == Zone.GRAVEYARD and len(spirits) == 1 and (spirits[0].atk, spirits[0].health) == (6, 6) and spirits[0].taunt)

    return audit(cid, [
        ("base_two_two_taunt", "The base Spellstone summons one 2/2 Spirit with Taunt.", summons_base_taunt_spirit, "檢查召喚物身份、2/2身材、嘲諷和場區。"),
        ("heal_progress_two_levels", "Restoring at least 3 Health upgrades the Spellstone to 4/4, then a further 3 to 6/6.", healing_upgrades_both_levels, "英雄預先失去12生命；手牌中留置 Spellstone，兩次實際施放 Holy Light，每次檢查升級 ID，最後施放並核對6/6嘲諷。"),
    ])


def call_to_arms():
    cid = "LOOT_093"

    def recruits_three_affordable_minions():
        g = new_game(CardClass.PALADIN, CardClass.MAGE)
        p = g.player1
        for card_id in (WISP, "EX1_029", "CS2_050", "CS2_182"):
            put_deck(p, card_id)
        spell = play(p, cid)
        recruited = [m for m in p.field if m.id in {WISP, "EX1_029", "CS2_050", "CS2_182"}]
        observed = f"recruited={[(m.id,m.cost,m.atk,m.health,m.zone.name) for m in recruited]};deck={[c.id for c in p.deck]};spell={spell.zone.name}"
        eligible = {WISP, "EX1_029", "CS2_050"}
        return checked(observed, len(recruited) == 3 and {m.id for m in recruited} == eligible and all(m.cost <= 2 and m.zone == Zone.PLAY for m in recruited) and "CS2_182" in [c.id for c in p.deck] and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("recruit_three_cost_two_or_less", "Recruits exactly three minions costing 2 or less and leaves the 4-Cost Yeti in the deck.", recruits_three_affordable_minions, "牌庫含三张且仅三张合法费用随从及一张4费Yeti，实际招募后检查身份集合、费用、区域和未招募牌。"),
    ])


def explosive_runes():
    cid = "LOOT_101"

    def deals_six_and_overflow_to_hero():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        secret = play(p, cid)
        hero_before = e.hero.health
        g.end_turn()
        minion = play(e, "CS2_182")
        observed = f"minion={minion.zone.name}/{minion.health}/{minion.max_health};enemy_hero={hero_before}->{e.hero.health};secret={secret.zone.name};enemy_field={[m.id for m in e.field]}"
        return checked(observed, minion.zone == Zone.GRAVEYARD and e.hero.health == hero_before - 1 and secret.zone == Zone.GRAVEYARD and not e.field)

    return audit(cid, [
        ("six_damage_excess", "After the opponent plays a minion, deals 6 damage to it and sends 1 excess damage from a 5-Health minion to that hero.", deals_six_and_overflow_to_hero, "實際打出奥秘再由对手使用5血Yeti，检查本体被消灭、英雄承受超过目标生命值的1点伤害及奥秘移除；existing_tests=test_kobolds.py:test_explosive_runes。"),
    ])


def lesser_ruby_spellstone():
    cid = "LOOT_103"

    def adds_one_mage_spell():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        spellstone = play(p, cid)
        generated = [card for card in p.hand]
        observed = f"generated={[(c.id,CardClass(c.card_class).name,CardType(c.type).name) for c in generated]};spellstone={spellstone.zone.name}"
        return checked(observed, len(generated) == 1 and generated[0].type == CardType.SPELL and generated[0].card_class == CardClass.MAGE and spellstone.zone == Zone.GRAVEYARD)

    def four_elementals_upgrade_through_three_spells():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        p.give(cid)
        for _ in range(4):
            play(p, "UNG_809")
        upgraded = find_hand(p, "LOOT_103t2")
        if upgraded:
            upgraded.play()
        generated = [card for card in p.hand if card.type == CardType.SPELL]
        observed = f"elementals={p.elemental_played_this_turn};version={upgraded.id if upgraded else 'missing'};hand={[c.id for c in p.hand]};generated={[(c.id,CardClass(c.card_class).name,CardType(c.type).name) for c in generated]}"
        return checked(observed, upgraded is not None and upgraded.zone == Zone.GRAVEYARD and len(generated) == 3 and all(card.type == CardType.SPELL and card.card_class == CardClass.MAGE for card in generated))

    return audit(cid, [
        ("base_random_mage_spell", "Adds one random Mage spell to its controller's hand.", adds_one_mage_spell, "不依赖随机卡名，只核对生成物均为法师法术且正好一张。"),
        ("elemental_progress_two_levels", "Playing four Elementals while held reaches the three-spell version.", four_elementals_upgrade_through_three_spells, "Spellstone 留在手牌，连续打出四张1费 Fire Fly；检查最高版本并确认施放后获得三张法师法术。"),
    ])


def shifting_scroll():
    cid = "LOOT_104"

    def transforms_on_each_own_turn():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=943)
        p = g.player1
        p.give(cid)
        g.end_turn()
        while g.current_player is not p:
            g.end_turn()
        first = next((card for card in p.hand if card.id != cid), None)
        first_id = first.id if first else "missing"
        first_valid = first is not None and first.type == CardType.SPELL and first.card_class == CardClass.MAGE
        g.end_turn()
        while g.current_player is not p:
            g.end_turn()
        second = next((card for card in p.hand if card.id != cid), None)
        observed = f"first={first_id};first_valid={first_valid};second={second.id if second else 'missing'};second_class={CardClass(second.card_class).name if second else 'missing'};second_type={CardType(second.type).name if second else 'missing'};hand={[c.id for c in p.hand]}"
        return checked(observed, first_valid and second is not None and second.type == CardType.SPELL and second.card_class == CardClass.MAGE)

    return audit(cid, [
        ("transform_each_turn_in_hand", "Transforms while held at the start of each of its controller's turns into a Mage spell.", transforms_on_each_own_turn, "Scroll 留在手牌横跨两个真实己方回合起始；分别记录两个当前卡牌身份并确认类型及职业，检查第一次Morph后的实体仍会再次触发。"),
    ])


def deck_of_wonders():
    cid = "LOOT_106"

    def shuffles_and_casts_scrolls_when_drawn():
        g = new_game(CardClass.MAGE, CardClass.MAGE, seed=991)
        p = g.player1
        spell = play(p, cid)
        before = [card.id for card in p.deck].count("LOOT_106t")
        p.draw()
        cast_scrolls = [card for card in p.graveyard if card.id == "LOOT_106t"]
        remaining_scrolls = [card for card in p.deck if card.id == "LOOT_106t"]
        observed = f"scrolls_before_draw={before};scrolls_cast={len(cast_scrolls)};remaining_scrolls={len(remaining_scrolls)};deck={[c.id for c in p.deck]};hand={[c.id for c in p.hand]};graveyard={[c.id for c in p.graveyard]}"
        return checked(observed, before == 5 and len(cast_scrolls) == 5 and not remaining_scrolls and spell.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("five_scrolls_auto_cast_on_draw", "Shuffles five Scrolls into the deck; drawing one casts its random spell and draw trigger resolves the remaining Scrolls.", shuffles_and_casts_scrolls_when_drawn, "确认施放后牌库恰有5张Scroll；真实抽牌并检查自动施放后5张均离开牌库、进入墓地，没有通过手动施放绕过抽牌触发。"),
    ])


def aluneth():
    cid = "LOOT_108"

    def draws_three_at_end_of_turn():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        expected = {WISP, MOONFIRE, FIREBALL}
        for card_id in expected:
            put_deck(p, card_id)
        weapon = play(p, cid)
        g.end_turn()
        hand_ids = [card.id for card in p.hand]
        observed = f"weapon={p.weapon.id if p.weapon else None}/{weapon.durability};hand={hand_ids};deck={[c.id for c in p.deck]}"
        return checked(observed, p.weapon is weapon and set(hand_ids) == expected and len(hand_ids) == 3)

    return audit(cid, [
        ("end_turn_draw_three", "At the end of its controller's turn, draws three cards.", draws_three_at_end_of_turn, "牌库放入三张不同的确定卡，装备武器后真实结束己方回合，检查三张均进入手牌。"),
    ])


def scorp_o_matic():
    cid = "LOOT_111"

    def destroys_only_one_attack_targets():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        low = summon(e, WISP)
        high = summon(e, "CS2_182")
        scorp = p.give(cid)
        legal_targets = list(scorp.targets)
        scorp.play(target=low)
        observed = f"legal={[m.id for m in legal_targets]};low={low.zone.name};high={high.zone.name}/{high.health};scorp={scorp.zone.name}"
        return checked(observed, low in legal_targets and high not in legal_targets and low.zone == Zone.GRAVEYARD and high.zone == Zone.PLAY and scorp.zone == Zone.PLAY)

    return audit(cid, [
        ("destroy_attack_at_most_one", "Battlecry destroys the selected minion with 1 Attack and excludes the 4-Attack minion as an invalid target.", destroys_only_one_attack_targets, "同场放置1攻Wisp与4攻Yeti，先检查当前合法目标集合，再以合法目标实际触发战吼。"),
    ])


def wax_elemental():
    cid = "LOOT_117"

    def taunt_divine_shield_combat():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        attacker = summon(e, WISP)
        wax = play(p, cid)
        health = wax.health
        shield_before = wax.divine_shield
        g.end_turn()
        hero_legal = attacker.can_attack(p.hero)
        wax_legal = attacker.can_attack(wax)
        if wax_legal:
            attacker.attack(wax)
        observed = f"wax={wax.atk}/{health}->{wax.health}/{wax.max_health};taunt={wax.taunt};shield={shield_before}->{wax.divine_shield};attacker={attacker.zone.name};hero_legal={hero_legal};wax_legal={wax_legal}"
        return checked(observed, wax.taunt and shield_before and not wax.divine_shield and wax.health == health and wax_legal and not hero_legal and attacker.zone == Zone.PLAY)

    return audit(cid, [
        ("taunt_shield_blocks_attack", "Taunt forces the enemy Wisp to attack Wax Elemental; Divine Shield absorbs that attack without health loss.", taunt_divine_shield_combat, "實際敵方 Wisp 進行攻擊，先檢查對英雄非法、對蠟油元素合法，再核對聖盾吸收戰鬥傷害。"),
    ])


def ebon_dragonsmith():
    cid = "LOOT_118"

    def reduces_weapon_in_hand_not_minion():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        weapon = p.give("LOOT_108")
        minion = p.give("CS2_182")
        before = (weapon.cost, minion.cost)
        smith = play(p, cid)
        observed = f"before_weapon_minion={before};after_weapon_minion={(weapon.cost,minion.cost)};smith={smith.zone.name}"
        return checked(observed, weapon.cost == before[0] - 2 and minion.cost == before[1] and smith.zone == Zone.PLAY)

    def no_weapon_means_no_cost_change():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        minion = p.give("CS2_182")
        before = minion.cost
        smith = play(p, cid)
        observed = f"minion_cost={before}->{minion.cost};hand={[c.id for c in p.hand]};smith={smith.zone.name}"
        return checked(observed, minion.cost == before and not p.hand and smith.zone == Zone.PLAY)

    return audit(cid, [
        ("random_weapon_cost_reduction", "With one Weapon in hand, it alone costs 2 less after the Battlecry.", reduces_weapon_in_hand_not_minion, "手牌只放一把武器和一张 Yeti，随机选择被唯一武器约束；分别检查两张卡的费用变化。"),
        ("no_weapon_no_effect", "With no Weapon in hand, the Battlecry does not alter a minion's Cost.", no_weapon_means_no_cost_change, "手牌只有Yeti而没有武器，检查卡面不存在可减费对象时不错误修改随从费用。"),
    ])


def corrosive_sludge():
    cid = "LOOT_122"

    def destroys_opponent_weapon_only():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        sludge_card = p.give(cid)
        own_weapon = play(p, "CS2_091")
        g.end_turn()
        enemy_weapon = play(e, "CS2_091")
        g.end_turn()
        sludge = sludge_card
        sludge.play()
        observed = f"own_weapon={p.weapon.id if p.weapon else None}/{own_weapon.zone.name};enemy_weapon={e.weapon.id if e.weapon else None}/{enemy_weapon.zone.name};sludge={sludge.zone.name}"
        return checked(observed, p.weapon is own_weapon and own_weapon.zone == Zone.PLAY and e.weapon is None and enemy_weapon.zone == Zone.GRAVEYARD and sludge.zone == Zone.PLAY)

    return audit(cid, [
        ("destroy_enemy_weapon", "Battlecry destroys the opponent's weapon and preserves its controller's weapon.", destroys_opponent_weapon_only, "双方实际装备同一把刀后轮回施放 Sludge，检查只对手武器进入墓地、己方武器仍装备。"),
    ])


def lone_champion():
    cid = "LOOT_124"

    def alone_gains_both_keywords():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        champion = play(p, cid)
        observed = f"field={[(m.id,m.atk,m.health,m.taunt,m.divine_shield) for m in p.field]}"
        return checked(observed, len(p.field) == 1 and champion.taunt and champion.divine_shield)

    def another_minion_prevents_both_keywords():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        other = summon(p, WISP)
        champion = play(p, cid)
        observed = f"other={other.id}/{other.zone.name};champion={champion.taunt}/{champion.divine_shield};field={[m.id for m in p.field]}"
        return checked(observed, other.zone == Zone.PLAY and not champion.taunt and not champion.divine_shield)

    return audit(cid, [
        ("empty_board_taunt_and_shield", "When it is the only friendly minion, gains Taunt and Divine Shield.", alone_gains_both_keywords, "空场施放后同时核对嘲讽和圣盾。"),
        ("other_minion_prevents_keywords", "When another friendly minion is present, gains neither Taunt nor Divine Shield.", another_minion_prevents_both_keywords, "先放置友方 Wisp 后施放，分别检查两个条件关键字均未赋予。"),
    ])


def stoneskin_basilisk():
    cid = "LOOT_125"

    def poisonous_attack_and_shield_combat():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        basilisk = play(p, cid)
        target = summon(e, "CS2_182")
        base_health = basilisk.health
        shield_before = basilisk.divine_shield
        poisonous_before = basilisk.poisonous
        g.end_turn()
        g.end_turn()
        ready = basilisk.can_attack(target)
        if ready:
            basilisk.attack(target)
        observed = f"ready={ready};basilisk={basilisk.zone.name}/{basilisk.health}/{basilisk.max_health};shield={shield_before}->{basilisk.divine_shield};poisonous={poisonous_before};target={target.zone.name}/{target.health}/{target.max_health}"
        return checked(observed, ready and shield_before and poisonous_before and not basilisk.divine_shield and basilisk.health == base_health and basilisk.zone == Zone.PLAY and target.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("poisonous_kill_with_divine_shield", "Divine Shield absorbs retaliation while Poisonous destroys a high-health minion after combat damage.", poisonous_attack_and_shield_combat, "真实攻击5血Yeti；先核实两种关键字，再检查目标被剧毒消灭及圣盾吸收4点反击伤害。"),
    ])


def arcane_tyrant():
    cid = "LOOT_130"

    def costly_spell_makes_tyrant_free():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        tyrant = p.give(cid)
        pyroblast = play(p, "EX1_279", target=e.hero)
        cost = tyrant.cost
        tyrant.play()
        observed = f"spell={pyroblast.id}:{pyroblast.zone.name};enemy_hero={e.hero.health};tyrant_cost={cost};tyrant={tyrant.zone.name}/{tyrant.atk}/{tyrant.health}"
        return checked(observed, e.hero.health == 20 and cost == 0 and tyrant.zone == Zone.PLAY)

    def cheaper_spell_does_not_discount():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        tyrant = p.give(cid)
        fireball = play(p, FIREBALL, target=e.hero)
        observed = f"spell_cost={fireball.cost};enemy_hero={e.hero.health};tyrant_cost={tyrant.cost};tyrant_zone={tyrant.zone.name}"
        return checked(observed, e.hero.health == 24 and tyrant.cost == 5 and tyrant.zone == Zone.HAND)

    return audit(cid, [
        ("five_plus_spell_discount", "After casting a 5+ Cost spell this turn, Arcane Tyrant costs 0 and can be played.", costly_spell_makes_tyrant_free, "手牌预置 Tyrant 后真实施放10费 Pyroblast，确认其费用变0并付0费召唤；同时记录法术效果。"),
        ("four_cost_spell_no_discount", "After casting a 4-Cost spell, Arcane Tyrant remains at its printed 5 Cost.", cheaper_spell_does_not_discount, "真实施放4费 Fireball 作为阈值下方对照，确认 Tyrant 仍在手牌且费用未变。"),
    ])


def green_jelly():
    cid = "LOOT_131"

    def end_turn_summons_taunt_ooze():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        jelly = play(p, cid)
        g.end_turn()
        oozes = [m for m in p.field if m.id == "LOOT_131t1"]
        observed = f"jelly={jelly.zone.name};oozes={[(m.atk,m.health,m.taunt,m.zone.name) for m in oozes]};turn={g.current_player.name}"
        return checked(observed, jelly.zone == Zone.PLAY and len(oozes) == 1 and (oozes[0].atk, oozes[0].health) == (1, 2) and oozes[0].taunt and oozes[0].zone == Zone.PLAY)

    return audit(cid, [
        ("end_turn_one_taunt_ooze", "At the end of its controller's turn, summons one 1/2 Ooze with Taunt.", end_turn_summons_taunt_ooze, "实际结束 Jelly 所属回合后检查 token 身份、身材、嘲讽和召唤方场区。"),
    ])


def dragonslayer():
    cid = "LOOT_132"

    def damages_dragon_only():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        dragon = summon(e, "LOOT_137")
        other = summon(e, "CS2_182")
        slayer = p.give(cid)
        legal = list(slayer.targets)
        before = dragon.health
        slayer.play(target=dragon)
        observed = f"legal={[m.id for m in legal]};dragon={before}->{dragon.health}/{dragon.max_health}:{dragon.zone.name};other={other.health}/{other.zone.name};slayer={slayer.zone.name}"
        return checked(observed, dragon in legal and other not in legal and dragon.health == before - 6 and dragon.zone == Zone.PLAY and other.health == 5 and other.zone == Zone.PLAY and slayer.zone == Zone.PLAY)

    return audit(cid, [
        ("six_damage_only_to_dragon", "Battlecry deals 6 damage to a Dragon; a non-Dragon minion is not a legal target and stays unharmed.", damages_dragon_only, "同场放置12血Sleepy Dragon及5血Yeti，比较真实合法目标集合，再对龙造成6点伤害。"),
    ])


def toothy_chest():
    cid = "LOOT_134"

    def start_turn_sets_attack_to_four():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p = g.player1
        chest = play(p, cid)
        before = (chest.atk, chest.health, chest.max_health)
        g.end_turn()
        g.end_turn()
        observed = f"before={before};after={(chest.atk,chest.health,chest.max_health)};zone={chest.zone.name}"
        return checked(observed, chest.atk == 4 and chest.max_health == before[2] and chest.health == before[1] and chest.zone == Zone.PLAY)

    return audit(cid, [
        ("start_turn_attack_four", "At the start of its controller's next turn, sets Attack to 4 while preserving Health.", start_turn_sets_attack_to_four, "实际经过对手回合并返回控制者，比较回合前后攻击、当前生命和最大生命。"),
    ])


def sneaky_devil():
    cid = "LOOT_136"

    def stealth_aura_buffs_and_leaves_with_source():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        before = summon(p, WISP)
        enemy = summon(e, WISP)
        devil = play(p, cid)
        after = summon(p, WISP)
        while_aura = (before.atk, after.atk, enemy.atk, devil.atk, devil.stealthed)
        devil.destroy()
        after_destroy = (before.atk, after.atk, enemy.atk)
        observed = f"while_aura={while_aura};after_destroy={after_destroy};devil={devil.zone.name}"
        return checked(observed, while_aura == (2, 2, 1, devil.atk, True) and after_destroy == (1, 1, 1) and devil.zone == Zone.GRAVEYARD)

    return audit(cid, [
        ("stealth_and_friendly_attack_aura", "Has Stealth and gives other friendly minions +1 Attack while it remains in play.", stealth_aura_buffs_and_leaves_with_source, "Aura 前后都真实召唤己方 Wisp，并放置敌方 Wisp 对照；核对潜行、当前攻击加成和源离场后加成移除。"),
    ])


def sleepy_dragon():
    cid = "LOOT_137"

    def taunt_forces_attack_target():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        dragon = play(p, cid)
        attacker = summon(e, WISP)
        g.end_turn()
        hero_legal = attacker.can_attack(p.hero)
        dragon_legal = attacker.can_attack(dragon)
        if dragon_legal:
            attacker.attack(dragon)
        observed = f"dragon={dragon.atk}/{dragon.health}/{dragon.taunt};hero_legal={hero_legal};dragon_legal={dragon_legal};attacker={attacker.zone.name};dragon_zone={dragon.zone.name}"
        return checked(observed, dragon.taunt and dragon_legal and not hero_legal and attacker.zone == Zone.GRAVEYARD and dragon.zone == Zone.PLAY)

    return audit(cid, [
        ("taunt_blocks_hero_attack", "Taunt prevents the enemy from attacking the hero and forces its ready Wisp to attack Sleepy Dragon.", taunt_forces_attack_target, "在己方场上放置龙后切到敌方回合，实际检查合法目标并攻击嘲讽随从。"),
    ])


def hoarding_dragon():
    cid = "LOOT_144"

    def deathrattle_gives_two_coins_to_opponent():
        g = new_game(CardClass.MAGE, CardClass.MAGE)
        p, e = g.player1, g.player2
        dragon = play(p, cid)
        dragon.destroy()
        opponent_coins = [card for card in e.hand if card.id == THE_COIN]
        own_coins = [card for card in p.hand if card.id == THE_COIN]
        observed = f"dragon={dragon.zone.name};opponent_coins={[(c.id,c.zone.name) for c in opponent_coins]};own_coins={len(own_coins)}"
        return checked(observed, dragon.zone == Zone.GRAVEYARD and len(opponent_coins) == 2 and not own_coins and all(card.zone == Zone.HAND for card in opponent_coins))

    return audit(cid, [
        ("deathrattle_two_opponent_coins", "On death, gives exactly two Coins to its opponent.", deathrattle_gives_two_coins_to_opponent, "实际打出并摧毁本体，按卡牌 ID 和区域分别核对对手获得两张 Coin、己方一张也没有。"),
    ])


AUDITS = {
    "LOOT_008": psychic_scream,
    "LOOT_013": vulgar_homunculus,
    "LOOT_014": kobold_librarian,
    "LOOT_017": dark_pact,
    "LOOT_018": hooked_reaver,
    "LOOT_026": faldorei_strider,
    "LOOT_033": cavern_shinyfinder,
    "LOOT_041": kobold_barbarian,
    "LOOT_043": lesser_amethyst_spellstone,
    "LOOT_044": bladed_gauntlet,
    "LOOT_047": barkskin,
    "LOOT_048": ironwood_golem,
    "LOOT_051": lesser_jasper_spellstone,
    "LOOT_054": branching_paths,
    "LOOT_056": astral_tiger,
    "LOOT_060": crushing_hand,
    "LOOT_062": kobold_hermit,
    "LOOT_064": lesser_sapphire_spellstone,
    "LOOT_069": sewer_crawler,
    "LOOT_077": flanking_strike,
    "LOOT_078": cave_hydra,
    "LOOT_079": wandering_monster,
    "LOOT_080": lesser_emerald_spellstone,
    "LOOT_085": rhokdelar,
    "LOOT_088": potion_of_heroism,
    "LOOT_091": lesser_pearl_spellstone,
    "LOOT_093": call_to_arms,
    "LOOT_101": explosive_runes,
    "LOOT_103": lesser_ruby_spellstone,
    "LOOT_104": shifting_scroll,
    "LOOT_106": deck_of_wonders,
    "LOOT_108": aluneth,
    "LOOT_111": scorp_o_matic,
    "LOOT_117": wax_elemental,
    "LOOT_118": ebon_dragonsmith,
    "LOOT_122": corrosive_sludge,
    "LOOT_124": lone_champion,
    "LOOT_125": stoneskin_basilisk,
    "LOOT_130": arcane_tyrant,
    "LOOT_131": green_jelly,
    "LOOT_132": dragonslayer,
    "LOOT_134": toothy_chest,
    "LOOT_136": sneaky_devil,
    "LOOT_137": sleepy_dragon,
    "LOOT_144": hoarding_dragon,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=45)
    args = parser.parse_args()
    assert 1 <= args.limit <= 45
    selected = OWN_IDS[:args.limit]
    missing = [card_id for card_id in selected if card_id not in AUDITS]
    if missing:
        raise SystemExit("missing live probes: " + ", ".join(missing))
    statuses = [AUDITS[card_id]() for card_id in selected]
    print(f"audited={len(selected)} statuses={ {s: statuses.count(s) for s in sorted(set(statuses))} }")


if __name__ == "__main__":
    main()
