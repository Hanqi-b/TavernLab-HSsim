"""Focused live-game audit for GANGS baseline YELLOW cards, slice a (0:44).

Rows are written after each case and after each verdict. Importing this module
does not modify any report; execution supports --start/--limit for recovery.
"""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import MOONFIRE, MURLOC, WISP, prepare_empty_game  # noqa: E402

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

BASELINE = HERE / "three_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
MECHANISMS = HERE / "card_mechanism.csv"
QUALITY = HERE / "card_quality.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE = HERE / "gangs_probe_a.csv"
VERDICT = HERE / "gangs_verdict_a.csv"
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
GANGS_ROWS = [row for row in BASE_ROWS if row["set"] == "Mean Streets of Gadgetzan (GANGS)"]
CARDS = [row["card_id"] for row in GANGS_ROWS[:44]]
assert len(CARDS) == 44 and CARDS[0] == "CFM_020" and CARDS[-1] == "CFM_609"
MASTER_ROWS = {row["card_id"]: row for row in read_csv(MASTER)}
OLD_QUALITY = {row["card_id"]: row for row in read_csv(QUALITY)}
MECH_ROWS = read_csv(MECHANISMS)
LABELS = {
    cid: sorted({row["mechanic"] for row in MECH_ROWS if row["card_id"] == cid})
    for cid in CARDS
}
OLD_MECH_REASONS = {
    cid: sorted({row["reason"] for row in MECH_ROWS if row["card_id"] == cid and row["reason"]})
    for cid in CARDS
}
PROBE_ROWS = read_csv(PROBE)
VERDICT_ROWS = read_csv(VERDICT)


def game(class1=CardClass.MAGE, class2=None, seed=417):
    """Deterministic empty Wild game with enough mana for controlled probes."""
    random.seed(seed)
    if class2 is None:
        class2 = class1
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
    return g


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


def summon_enemy_then_return(g, card_id):
    """Summon for the actual opponent turn so the entity gets the right controller."""
    if g.current_player is not g.player1:
        raise AssertionError(f"fixture expected Player1 turn, got {g.current_player.name}")
    g.end_turn()
    minion = g.player2.summon(card_id)
    g.end_turn()
    return minion


def checked(observed, condition):
    assert condition, observed
    return observed


def prepare_card(cid):
    """Remove only the current card's old rows when that card starts running."""
    PROBE_ROWS[:] = [row for row in PROBE_ROWS if row["card_id"] != cid]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def add_case(cid, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append({"card_id": cid, "case_id": case_id, "expected": expected,
                       "observed": observed, "outcome": outcome, "notes": notes})
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    return outcome


def finish_card(cid, cases, blocker=None):
    own = [row for row in PROBE_ROWS if row["card_id"] == cid]
    assert own and len({row["case_id"] for row in own}) == len(own), cid
    errors = [row for row in own if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in own if row["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "；".join(
            f"{row['case_id']}预期[{row['expected']}]，实际[{row['observed']}]" for row in errors
        )
    elif unresolved:
        status, reason = "YELLOW", "行为测试未完成：" + "；".join(
            f"{row['case_id']}={row['observed']}" for row in unresolved
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "逐卡实际对局断言通过：" + "；".join(
            f"{row['case_id']}={row['observed']}" for row in own
        )
    master = MASTER_ROWS[cid]
    quality = OLD_QUALITY.get(cid, {})
    affected = []
    for issue in read_csv(ISSUES):
        linked = set((issue.get("confirmed_cards", "") + "|" + issue.get("candidate_cards", "")).split("|"))
        if cid in linked:
            affected.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    notes = (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or '未发现 Python 卡脚本'}; "
        f"existing_tests={master.get('test_refs_candidate', '') or '无候选既有测试引用'}; "
        f"previous_card_audit={quality.get('reason', '无')}; "
        f"previous_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
        f"prior_cross_card_issues={' / '.join(affected) if affected else '无'}; audit_scope=本轮实际运行断言。"
    )
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != cid]
    VERDICT_ROWS.append({"card_id": cid, "status": status,
                         "mechanic_scope": "|".join(LABELS[cid]), "reason": reason,
                         "probe_file": PROBE.name, "notes": notes})
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}")
    return status


def audit_card(cid, tests, blocker=None):
    prepare_card(cid)
    for case_id, expected, func, notes in tests:
        add_case(cid, case_id, expected, func, notes)
    return finish_card(cid, tests, blocker)


def cfm020_no_duplicate_deck():
    g = game(CardClass.PRIEST)
    p = g.player1
    for card_id in ("CS2_231", "CS2_182"):
        p.give(card_id).shuffle_into_deck()
    raza = play(p, "CFM_020")
    cost = p.hero.power.cost
    raza.destroy()
    g.end_turn()
    g.end_turn()
    return checked(f"deck={[c.id for c in p.deck]};hero_power_cost={cost};raza={raza.zone.name};after_death={p.hero.power.cost}",
                   cost == 0 and raza.zone == Zone.GRAVEYARD and p.hero.power.cost == 0)


def cfm020_duplicate_deck():
    g = game(CardClass.PRIEST)
    p = g.player1
    for _ in range(2):
        p.give("CS2_231").shuffle_into_deck()
    raza = play(p, "CFM_020")
    cost = p.hero.power.cost
    return checked(f"deck={[c.id for c in p.deck]};hero_power_cost={cost};raza={raza.zone.name}",
                   cost > 0 and raza in p.field)


def cfm021_freeze_enemy_minion():
    g = game(CardClass.MAGE)
    enemy = summon_enemy_then_return(g, WISP)
    spell = play(g.player1, "CFM_021", enemy)
    return checked(f"enemy_controller={enemy.controller.name};enemy_frozen={enemy.frozen};enemy_zone={enemy.zone.name};spell={spell.zone.name}",
                   enemy.controller is g.player2 and enemy.frozen and enemy.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def cfm021_freeze_enemy_hero():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    before = (enemy.hero.health, enemy.hero.frozen)
    spell = play(p, "CFM_021", enemy.hero)
    return checked(f"enemy_hero={before}->{(enemy.hero.health,enemy.hero.frozen)};spell={spell.zone.name}",
                   before == (30, False) and enemy.hero.health == 30 and enemy.hero.frozen and spell.zone == Zone.GRAVEYARD)


def cfm025_survives_and_draws():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, WISP)
    burglar = play(p, "CFM_025")
    g.end_turn()
    g.end_turn()
    p.give("CS2_182").shuffle_into_deck()
    before = [c.id for c in p.hand]
    burglar.attack(target)
    drawn = [c.id for c in p.hand if c.id not in before]
    return checked(f"burglar={(burglar.health, burglar.zone.name)};target={target.zone.name};drawn={drawn};deck={[c.id for c in p.deck]}",
                   burglar in p.field and target.zone == Zone.GRAVEYARD and drawn == ["CS2_182"])


def cfm025_dies_no_draw():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_200")
    burglar = play(p, "CFM_025")
    g.end_turn()
    g.end_turn()
    p.give("CS2_182").shuffle_into_deck()
    before = len(p.hand)
    burglar.attack(target)
    return checked(f"burglar={burglar.zone.name};target={target.zone.name};hand_before={before};hand_after={len(p.hand)};deck={[c.id for c in p.deck]}",
                   burglar.zone == Zone.GRAVEYARD and len(p.hand) == before and [c.id for c in p.deck] == ["CS2_182"])


def cfm026_secret_buffs_random_hand_minion():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    hand_minions = [p.give(WISP), p.give("CS2_182")]
    secret = play(p, "CFM_026")
    secret_zone = secret.zone.name
    g.end_turn()
    played = play(enemy, WISP)
    stats = [(c.id, c.atk, c.health, c.max_health) for c in hand_minions]
    buffs = [c for c in hand_minions if c.atk == c.data.atk + 2 and c.max_health == c.data.health + 2]
    unchanged = [c for c in hand_minions if c not in buffs and c.atk == c.data.atk and c.max_health == c.data.health]
    return checked(f"secret_before={secret_zone};secret_after={secret.zone.name};opponent_card={played.zone.name};hand_stats={stats};buffed={[c.id for c in buffs]}",
                   secret_zone == Zone.SECRET.name and secret.zone == Zone.GRAVEYARD and played in enemy.field and
                   len(buffs) == 1 and len(unchanged) == 1 and buffs[0] in p.hand)


def cfm039_spell_damage_applies():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_182")
    trickster = play(p, "CFM_039")
    target.damage = 0
    spell = play(p, MOONFIRE, target)
    return checked(f"spellpower={p.spellpower};target_controller={target.controller.name};target_health={target.health};target_damage={target.damage};target_zone={target.zone.name};spell={spell.zone.name}",
                   p.spellpower == 1 and target.controller is enemy and target.health == 3 and target.damage == 2 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def cfm060_own_spell_and_opponent_scope():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    wyrm = play(p, "CFM_060")
    initial = wyrm.atk
    for _ in range(2):
        play(p, MOONFIRE, enemy.hero)
    after_own = wyrm.atk
    g.end_turn()
    play(enemy, MOONFIRE, p.hero)
    after_enemy = wyrm.atk
    return checked(f"attack={initial}->{after_own}->{after_enemy};enemy_health={enemy.hero.health};player_health={p.hero.health}",
                   after_own == initial + 4 and after_enemy == after_own)


def cfm061_heal_and_overload():
    g = game(CardClass.SHAMAN)
    p = g.player1
    p.hero.damage = 10
    before = p.hero.health
    minion = play(p, "CFM_061", p.hero)
    after = p.hero.health
    return checked(f"hero_health={before}->{after};overloaded={p.overloaded};card={minion.zone.name};mana={p.mana}",
                   after == before + 6 and p.overloaded == 1 and minion in p.field)


def cfm061_heal_friendly_minion_and_overload():
    g = game(CardClass.SHAMAN)
    p = g.player1
    target = summon(p, "CS2_182")
    target.damage = 3
    before = target.health
    card = play(p, "CFM_061", target)
    return checked(f"minion={before}->{target.health}/{target.max_health};overloaded={p.overloaded};card={card.zone.name}",
                   before == 2 and target.health == target.max_health == 5 and p.overloaded == 1 and card in p.field)


def cfm062_adjacent_divine_shields():
    g = game(CardClass.PALADIN)
    p, enemy = g.player1, g.player2
    foe = summon_enemy_then_return(g, WISP)
    left = summon(p, WISP)
    right = summon(p, "CS2_182")
    protector = play(p, "CFM_062", index=1)
    return checked(f"field={[m.id for m in p.field]};adjacent={(left.divine_shield, right.divine_shield)};protector={protector.divine_shield};enemy={(foe.controller.name,foe.divine_shield)}",
                   len(p.field) == 3 and p.field[1] is protector and left.divine_shield and right.divine_shield and
                   not protector.divine_shield and foe.controller is enemy and not foe.divine_shield)


def cfm063_swap_attack_health():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    opposing = summon_enemy_then_return(g, "CS2_182")
    friendly = summon(p, "CS2_182")
    before = (friendly.atk, friendly.health, friendly.max_health)
    card = play(p, "CFM_063", friendly)
    after = (friendly.atk, friendly.health, friendly.max_health)
    return checked(f"before={before};after={after};opposing={(opposing.atk, opposing.health)};card={card.zone.name}",
                   before == (4, 5, 5) and after == (5, 4, 4) and (opposing.atk, opposing.health) == (4, 5) and card in p.field)


def cfm064_buffs_only_while_in_hand():
    g = game(CardClass.MAGE)
    p = g.player1
    baron = p.give("CFM_064")
    base = (baron.atk, baron.health, baron.max_health)
    alleycat = play(p, "CFM_315")
    in_hand = (baron.atk, baron.health, baron.max_health)
    baron.play()
    after_play = (baron.atk, baron.health, baron.max_health)
    second = play(p, "CFM_315")
    after_later_summon = (baron.atk, baron.health, baron.max_health)
    return checked(f"baron={base}->{in_hand}->{after_play}->{after_later_summon};alleycat={alleycat.zone.name};token={[m.id for m in p.field]}",
                   in_hand == (base[0] + 1, base[1] + 1, base[2] + 1) and after_play == in_hand and
                   after_later_summon == after_play and baron in p.field and second in p.field)


def cfm065_minions_not_characters():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    foe = summon_enemy_then_return(g, "CS2_182")
    own = summon(p, "CS2_182")
    own_before, foe_before = own.health, foe.health
    heroes_before = (p.hero.health, enemy.hero.health)
    spell = play(p, "CFM_065")
    return checked(f"minions={own_before}->{own.health},{foe_before}->{foe.health};heroes={heroes_before}->{(p.hero.health, enemy.hero.health)};spell={spell.zone.name}",
                   own.health == own_before - 2 and foe.health == foe_before - 2 and
                   (p.hero.health, enemy.hero.health) == heroes_before and spell.zone == Zone.GRAVEYARD)


def cfm066_next_secret_is_free_only_once():
    g = game(CardClass.MAGE)
    p = g.player1
    lackey = play(p, "CFM_066")
    first = p.give("EX1_289")
    second = p.give("EX1_295")
    initial_costs = (first.data.cost, first.cost, second.data.cost, second.cost)
    first.play()
    after_first = (first.zone.name, second.cost, len(p.secrets))
    second.play()
    after_second = (second.zone.name, len(p.secrets))
    return checked(f"lackey={lackey.zone.name};costs={initial_costs};after_first={after_first};after_second={after_second};mana={p.mana}",
                   initial_costs == (3, 0, 3, 0) and after_first == (Zone.SECRET.name, 3, 1) and
                   after_second == (Zone.SECRET.name, 2))


def cfm067_heals_selected_minion_to_full():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_182")
    target.damage = 3
    before = (target.health, target.max_health)
    healer = play(p, "CFM_067", target)
    after = (target.health, target.max_health)
    return checked(f"enemy_target={before}->{after};healer={healer.zone.name};target_controller={target.controller.name};target_zone={target.zone.name}",
                   before == (2, 5) and after == (5, 5) and healer in p.field and target.controller is enemy and target.zone == Zone.PLAY)


def cfm094_hits_all_characters_for_five():
    g = game(CardClass.WARLOCK)
    p, enemy = g.player1, g.player2
    foe = summon_enemy_then_return(g, "CS2_182")
    own = summon(p, "CS2_182")
    spell = play(p, "CFM_094")
    return checked(f"heroes={(p.hero.health, enemy.hero.health)};minions={(own.zone.name, foe.zone.name)};spell={spell.zone.name}",
                   (p.hero.health, enemy.hero.health) == (25, 25) and own.zone == Zone.GRAVEYARD and
                   foe.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD)


def cfm120_deathrattle_heals_both_heroes():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    p.hero.damage = 10
    enemy.hero.damage = 12
    before = (p.hero.health, enemy.hero.health)
    mistress = play(p, "CFM_120")
    mistress.destroy()
    after = (p.hero.health, enemy.hero.health)
    return checked(f"heroes={before}->{after};mistress={mistress.zone.name}",
                   before == (20, 18) and after == (24, 22) and mistress.zone == Zone.GRAVEYARD)


def cfm300_taunt_blocks_face_attack():
    g = game(CardClass.PALADIN, CardClass.WARRIOR)
    p, enemy = g.player1, g.player2
    defender = play(p, "CFM_300")
    g.end_turn()
    enemy.give("CS2_091").play()
    face_blocked = False
    try:
        enemy.hero.attack(p.hero)
    except InvalidAction:
        face_blocked = True
    enemy.hero.attack(defender)
    return checked(f"stats={(defender.atk, defender.health, defender.max_health)};taunt={defender.taunt};face_blocked={face_blocked};enemy_attack={enemy.hero.atk};defender_health={defender.health}",
                   (defender.atk, defender.max_health) == (0, 7) and defender.taunt and face_blocked and defender.health == 6)


def cfm305_buffs_all_hand_minions_not_spell_or_summon_token():
    g = game(CardClass.PALADIN)
    p = g.player1
    wisp = p.give(WISP)
    alleycat = p.give("CFM_315")
    moonfire = p.give(MOONFIRE)
    before = ((wisp.atk, wisp.max_health), (alleycat.atk, alleycat.max_health), moonfire.zone.name)
    spell = play(p, "CFM_305")
    after = ((wisp.atk, wisp.max_health), (alleycat.atk, alleycat.max_health), moonfire.zone.name)
    wisp.play()
    alleycat.play()
    cat_token = [m for m in p.field if m.id == "CFM_315t"]
    return checked(f"before={before};after={after};played_wisp={(wisp.atk,wisp.health)};played_alleycat={(alleycat.atk,alleycat.health)};token={[(m.atk,m.health) for m in cat_token]};spell={spell.zone.name}",
                   after == ((2, 2), (2, 2), Zone.HAND.name) and (wisp.atk, wisp.health) == (2, 2) and
                   (alleycat.atk, alleycat.health) == (2, 2) and len(cat_token) == 1 and
                   (cat_token[0].atk, cat_token[0].health) == (1, 1) and spell.zone == Zone.GRAVEYARD)


def cfm308_gain_ten_armor_choice():
    g = game(CardClass.DRUID)
    p = g.player1
    card = play(p, "CFM_308", choose="CFM_308a")
    return checked(f"armor={p.hero.armor};mana={p.mana};field={[m.id for m in p.field]};choice={p.choice};card={card.zone.name}",
                   p.hero.armor == 10 and p.mana == 0 and card in p.field and p.choice is None)


def cfm308_refill_mana_choice():
    g = game(CardClass.DRUID)
    p = g.player1
    card = play(p, "CFM_308", choose="CFM_308b")
    return checked(f"armor={p.hero.armor};mana={p.mana};max_mana={p.max_mana};used_mana={p.used_mana};card={card.zone.name};choice={p.choice}",
                   p.hero.armor == 0 and p.mana == 10 and p.max_mana == 10 and p.used_mana == 0 and card in p.field and p.choice is None)


def cfm310_summons_four_murlocs():
    g = game(CardClass.SHAMAN)
    p = g.player1
    spell = play(p, "CFM_310")
    tokens = [m for m in p.field if m.id == "CFM_310t"]
    return checked(f"tokens={[(m.atk,m.health,m.zone.name) for m in tokens]};field={len(p.field)};spell={spell.zone.name}",
                   len(tokens) == 4 and all((m.atk, m.health) == (1, 1) for m in tokens) and spell.zone == Zone.GRAVEYARD)


def cfm310_stops_at_seven_minions():
    g = game(CardClass.SHAMAN)
    p = g.player1
    for _ in range(5):
        summon(p, WISP)
    spell = play(p, "CFM_310")
    tokens = [m for m in p.field if m.id == "CFM_310t"]
    return checked(f"field={len(p.field)};tokens={len(tokens)};spell={spell.zone.name};slots={p.minion_slots}",
                   len(p.field) == 7 and len(tokens) == 2 and spell.zone == Zone.GRAVEYARD and p.minion_slots == 0)


def cfm312_summons_taunt_jade_golem():
    g = game(CardClass.SHAMAN)
    p = g.player1
    chieftain = play(p, "CFM_312")
    golems = [m for m in p.field if m.id.startswith("CFM_712_t")]
    return checked(f"field={[(m.id,m.atk,m.health,m.taunt) for m in p.field]};chieftain={chieftain.zone.name};jade_counter={p.jade_golem}",
                   len(golems) == 1 and golems[0].id == "CFM_712_t01" and
                   (golems[0].atk, golems[0].health, golems[0].taunt) == (1, 1, True) and
                   chieftain in p.field and not chieftain.taunt)


def cfm313_discover_overload_shaman_card():
    g = game(CardClass.SHAMAN)
    p = g.player1
    spell = play(p, "CFM_313")
    choice = p.choice
    offered = [(card.id, card.data.card_class.name, card.overload, card.data.collectible)
               for card in choice.cards]
    assert len(offered) == 3, offered
    assert all(card_class == "SHAMAN" and overload > 0 and collectible
               for _, card_class, overload, collectible in offered), offered
    selected = choice.cards[0]
    selected_id = selected.id
    choice.choose(selected)
    return checked(f"overloaded={p.overloaded};offered={offered};selected={selected_id};choice={p.choice};hand={[c.id for c in p.hand]};spell={spell.zone.name}",
                   p.overloaded == 1 and p.choice is None and any(c.id == selected_id for c in p.hand) and spell.zone == Zone.GRAVEYARD)


def cfm315_alleycat_summons_one_cat():
    g = game(CardClass.HUNTER)
    p = g.player1
    alleycat = play(p, "CFM_315")
    cats = [m for m in p.field if m.id == "CFM_315t"]
    return checked(f"field={[(m.id,m.atk,m.health) for m in p.field]};card={alleycat.zone.name};cats={len(cats)}",
                   len(p.field) == 2 and alleycat in p.field and (alleycat.atk, alleycat.health) == (1, 1) and
                   len(cats) == 1 and (cats[0].atk, cats[0].health) == (1, 1))


def cfm316_deathrattle_counts_current_attack():
    g = game(CardClass.HUNTER)
    p = g.player1
    rat_pack = play(p, "CFM_316")
    original = rat_pack.atk
    buff = play(p, "CS2_087", rat_pack)
    boosted = rat_pack.atk
    rat_pack.destroy()
    summoned = list(p.field)
    return checked(f"attack={original}->{boosted};rat_pack={rat_pack.zone.name};summoned={[(m.id,m.atk,m.health) for m in summoned]};buff={buff.zone.name}",
                   original == 2 and boosted == 5 and rat_pack.zone == Zone.GRAVEYARD and len(summoned) == boosted and
                   all(m.id == "CFM_316t" and (m.atk, m.health) == (1, 1) for m in summoned) and buff.zone == Zone.GRAVEYARD)


def cfm321_discover_only_three_classes():
    g = game(CardClass.MAGE)
    p = g.player1
    informant = play(p, "CFM_321")
    choice = p.choice
    offered = [(card.id, card.data.card_class.name, card.data.collectible) for card in choice.cards]
    assert len(offered) == 3, offered
    allowed = {"HUNTER", "PALADIN", "WARRIOR"}
    assert all(card_class in allowed and collectible for _, card_class, collectible in offered), offered
    selected = choice.cards[-1]
    selected_id = selected.id
    choice.choose(selected)
    return checked(f"offered={offered};selected={selected_id};choice={p.choice};hand={[c.id for c in p.hand]};informant={informant.zone.name}",
                   p.choice is None and any(c.id == selected_id for c in p.hand) and informant in p.field)


def cfm324_deathrattle_shuffles_storm_guardian():
    g = game(CardClass.SHAMAN)
    p = g.player1
    p.give("CS2_231").shuffle_into_deck()
    white_eyes = play(p, "CFM_324")
    white_eyes.destroy()
    guardian = [card for card in p.deck if card.id == "CFM_324t"]
    return checked(f"white_eyes={white_eyes.zone.name};deck={[card.id for card in p.deck]};guardian_count={len(guardian)};guardian_zone={[card.zone.name for card in guardian]}",
                   white_eyes.zone == Zone.GRAVEYARD and len(guardian) == 1 and guardian[0].zone == Zone.DECK and
                   any(card.id == "CS2_231" for card in p.deck))


def cfm325_weapon_aura_enters_and_leaves():
    g = game(CardClass.ROGUE)
    p, enemy = g.player1, g.player2
    buccaneer = play(p, "CFM_325")
    without = buccaneer.atk
    weapon = play(p, "CS2_091")
    with_weapon = buccaneer.atk
    for swing in range(4):
        p.hero.attack(enemy.hero)
        if swing < 3:
            g.end_turn()
            g.end_turn()
    after_break = buccaneer.atk
    return checked(f"attack={without}->{with_weapon}->{after_break};weapon={weapon.zone.name};equipped={p.weapon};durability={weapon.durability}",
                   without == 1 and with_weapon == 3 and after_break == 1 and weapon.zone == Zone.GRAVEYARD and p.weapon is None)


def cfm328_draws_two_at_six_current_health():
    g = game(CardClass.MAGE)
    p = g.player1
    qualifying = summon(p, "CS2_200")
    qualifying.damage = 1  # 6 current health from 7 maximum.
    for card_id in ("CS2_231", "CS2_182"):
        p.give(card_id).shuffle_into_deck()
    promoter = play(p, "CFM_328")
    drawn = [card.id for card in p.hand if card.id in {"CS2_231", "CS2_182"}]
    return checked(f"qualifier={(qualifying.health,qualifying.max_health)};drawn={drawn};deck={[card.id for card in p.deck]};promoter={promoter.zone.name}",
                   qualifying.health == qualifying.max_health - 1 and qualifying.health == 6 and
                   len(drawn) == 2 and not p.deck and promoter in p.field)


def cfm328_does_not_draw_at_five_current_health():
    g = game(CardClass.MAGE)
    p = g.player1
    nonqualifying = summon(p, "CS2_200")
    nonqualifying.damage = 2  # max 7, current 5.
    p.give("CS2_231").shuffle_into_deck()
    promoter = play(p, "CFM_328")
    return checked(f"qualifier={(nonqualifying.health,nonqualifying.max_health)};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]};promoter={promoter.zone.name}",
                   (nonqualifying.health, nonqualifying.max_health) == (5, 7) and
                   not any(c.id == "CS2_231" for c in p.hand) and [c.id for c in p.deck] == ["CS2_231"] and promoter in p.field)


def cfm333_attack_minion_also_hits_hero():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, WISP)
    knuckles = play(p, "CFM_333")
    g.end_turn()
    g.end_turn()
    hero_before = enemy.hero.health
    knuckles.attack(target)
    return checked(f"target={target.zone.name};knuckles={(knuckles.health,knuckles.zone.name)};enemy_hero={hero_before}->{enemy.hero.health};hero_attack={knuckles.atk}",
                   target.zone == Zone.GRAVEYARD and knuckles in p.field and knuckles.health == knuckles.max_health - 1 and
                   enemy.hero.health == hero_before - knuckles.atk)


def cfm334_buffs_exactly_one_random_hand_beast():
    g = game(CardClass.HUNTER)
    p = g.player1
    beasts = [p.give("CFM_315"), p.give("CS2_125")]
    nonbeast = p.give(WISP)
    before = [(c.id, int(c.race), c.atk, c.max_health) for c in beasts + [nonbeast]]
    spell = play(p, "CFM_334")
    after = [(c.id, int(c.race), c.atk, c.max_health) for c in beasts + [nonbeast]]
    buffed = [c for c in beasts if c.atk == c.data.atk + 2 and c.max_health == c.data.health + 2]
    untouched_beast = [c for c in beasts if c not in buffed and c.atk == c.data.atk and c.max_health == c.data.health]
    return checked(f"before={before};after={after};buffed={[c.id for c in buffed]};nonbeast={(nonbeast.atk,nonbeast.max_health)};spell={spell.zone.name}",
                   len(buffed) == 1 and len(untouched_beast) == 1 and nonbeast.atk == nonbeast.data.atk and
                   nonbeast.max_health == nonbeast.data.health and spell.zone == Zone.GRAVEYARD)


def cfm335_battlecry_damages_enemy_minion():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_182")
    target.damage = 1  # 4 current Health.
    before = target.health
    kodo = play(p, "CFM_335", target)
    return checked(f"target_controller={target.controller.name};target={before}->{target.health}/{target.max_health};kodo={(kodo.atk,kodo.health,kodo.zone.name)}",
                   target.controller is enemy and before == 4 and target.health == before - kodo.atk and
                   target.zone == Zone.PLAY and kodo in p.field)


def cfm335_battlecry_can_target_enemy_hero():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    before = enemy.hero.health
    kodo = play(p, "CFM_335", enemy.hero)
    return checked(f"enemy_hero={before}->{enemy.hero.health};kodo={kodo.zone.name};target={enemy.hero.zone.name}",
                   enemy.hero.health == before - kodo.atk and kodo in p.field)


def cfm336_deathrattle_buffs_random_hand_minion():
    g = game(CardClass.HUNTER)
    p = g.player1
    minions = [p.give(WISP), p.give("CS2_182")]
    spell_in_hand = p.give(MOONFIRE)
    zipgunner = play(p, "CFM_336")
    zipgunner.destroy()
    buffed = [c for c in minions if c.atk == c.data.atk + 2 and c.max_health == c.data.health + 2]
    untouched = [c for c in minions if c not in buffed and c.atk == c.data.atk and c.max_health == c.data.health]
    return checked(f"zipgunner={zipgunner.zone.name};minions={[(c.id,c.atk,c.max_health) for c in minions]};spell={(spell_in_hand.id,spell_in_hand.cost,spell_in_hand.zone.name)};buffed={[c.id for c in buffed]}",
                   zipgunner.zone == Zone.GRAVEYARD and len(buffed) == 1 and len(untouched) == 1 and
                   spell_in_hand in p.hand and spell_in_hand.cost == spell_in_hand.data.cost)


def cfm337_attack_minion_summons_piranha():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, WISP)
    launcher = play(p, "CFM_337")
    p.hero.attack(target)
    piranhas = [m for m in p.field if m.id == "CFM_337t"]
    return checked(f"launcher={launcher.zone.name};target={target.zone.name};piranhas={[(m.atk,m.health) for m in piranhas]};weapon={p.weapon.id if p.weapon else None}",
                   target.zone == Zone.GRAVEYARD and len(piranhas) == 1 and (piranhas[0].atk, piranhas[0].health) == (1, 1))


def cfm337_attack_hero_also_summons_piranha():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    launcher = play(p, "CFM_337")
    p.hero.attack(enemy.hero)
    piranhas = [m for m in p.field if m.id == "CFM_337t"]
    return checked(f"launcher={launcher.zone.name};enemy_hero={enemy.hero.health};piranhas={[(m.atk,m.health) for m in piranhas]};weapon={p.weapon.id if p.weapon else None}",
                   enemy.hero.health == 30 - p.hero.atk and len(piranhas) == 1 and (piranhas[0].atk, piranhas[0].health) == (1, 1))


def cfm338_battlecry_buffs_one_random_hand_beast():
    g = game(CardClass.SHAMAN)
    p = g.player1
    beasts = [p.give("CFM_315"), p.give("CS2_125")]
    nonbeast = p.give(WISP)
    trogg = play(p, "CFM_338")
    buffed = [c for c in beasts if c.atk == c.data.atk + 1 and c.max_health == c.data.health + 1]
    untouched = [c for c in beasts if c not in buffed and c.atk == c.data.atk and c.max_health == c.data.health]
    return checked(f"trogg={trogg.zone.name};beasts={[(c.id,c.atk,c.max_health) for c in beasts]};nonbeast={(nonbeast.atk,nonbeast.max_health)};buffed={[c.id for c in buffed]}",
                   len(buffed) == 1 and len(untouched) == 1 and nonbeast.atk == nonbeast.data.atk and
                   nonbeast.max_health == nonbeast.data.health and trogg in p.field)


def cfm341_deathrattle_damages_enemy_minions_only():
    g = game(CardClass.PALADIN)
    p, enemy = g.player1, g.player2
    enemy_small = summon_enemy_then_return(g, WISP)
    enemy_large = summon_enemy_then_return(g, "CS2_182")
    friendly = summon(p, WISP)
    sally = play(p, "CFM_341")
    buff = play(p, "CS2_087", sally)
    sally_attack = sally.atk
    sally.destroy()
    return checked(f"attack={sally_attack};sally={sally.zone.name};friendly={friendly.zone.name};enemy_small={enemy_small.zone.name};enemy_large={enemy_large.health}/{enemy_large.max_health};buff={buff.zone.name}",
                   sally_attack == 4 and sally.zone == Zone.GRAVEYARD and friendly.zone == Zone.PLAY and
                   friendly.health == 1 and enemy_small.zone == Zone.GRAVEYARD and enemy_large.health == enemy_large.max_health - 4)


def cfm342_weapon_below_three_attack_no_buff():
    g = game(CardClass.SHAMAN)
    p = g.player1
    weapon = play(p, "CFM_717")  # Jade Claws is 2 Attack with only one Overload.
    buccaneer = play(p, "CFM_342")
    before = (buccaneer.atk, buccaneer.max_health)
    return checked(f"weapon_attack={weapon.atk};overload={weapon.overload};buccaneer={before};weapon={p.weapon.id};mana={p.mana}",
                   weapon.atk == 2 and before == (buccaneer.data.atk, buccaneer.data.health) and buccaneer in p.field)


def cfm342_weapon_at_three_attack_buff():
    g = game(CardClass.ROGUE)
    p = g.player1
    weapon = play(p, "CS2_106")  # Fiery War Axe is 3 Attack.
    buccaneer = play(p, "CFM_342")
    stats = (buccaneer.atk, buccaneer.max_health)
    return checked(f"weapon_attack={weapon.atk};buccaneer={stats};base={(buccaneer.data.atk,buccaneer.data.health)};weapon={p.weapon.id}",
                   weapon.atk == 3 and stats == (buccaneer.data.atk + 4, buccaneer.data.health + 4) and buccaneer in p.field)


def cfm343_first_jade_golem_and_behemoth_taunt():
    g = game(CardClass.DRUID)
    p = g.player1
    behemoth = play(p, "CFM_343")
    golems = [m for m in p.field if m.id.startswith("CFM_712_t")]
    return checked(f"field={[(m.id,m.atk,m.health,m.taunt) for m in p.field]};behemoth={(behemoth.atk,behemoth.health,behemoth.taunt)};jade_counter={p.jade_golem}",
                   behemoth in p.field and behemoth.taunt and len(golems) == 1 and
                   golems[0].id == "CFM_712_t01" and (golems[0].atk,golems[0].health) == (1,1))


def cfm343_scales_after_prior_jade_golem():
    g = game(CardClass.DRUID)
    p = g.player1
    blossom = play(p, "CFM_713")
    first = [m for m in p.field if m.id.startswith("CFM_712_t")][0]
    behemoth = play(p, "CFM_343")
    golems = [m for m in p.field if m.id.startswith("CFM_712_t")]
    return checked(f"blossom={blossom.zone.name};golems={[(m.id,m.atk,m.health,m.taunt) for m in golems]};behemoth={(behemoth.atk,behemoth.health,behemoth.taunt)};jade_counter={p.jade_golem}",
                   len(golems) == 2 and first.id == "CFM_712_t01" and
                   any(m.id == "CFM_712_t02" and (m.atk,m.health) == (2,2) for m in golems) and
                   behemoth in p.field and behemoth.taunt)


def cfm344_kill_summons_two_murlocs_from_deck():
    g = game(CardClass.HUNTER)
    p = g.player1
    target = summon_enemy_then_return(g, WISP)
    finja = play(p, "CFM_344")
    g.end_turn()
    g.end_turn()
    for _ in range(3):
        p.give(MURLOC).shuffle_into_deck()
    before_deck = [card.id for card in p.deck]
    finja.attack(target)
    murlocs = [m for m in p.field if m is not finja and m.race == Race.MURLOC]
    return checked(f"target={target.zone.name};finja={(finja.health,finja.zone.name)};deck={before_deck}->{[c.id for c in p.deck]};murlocs={[(m.id,m.atk,m.health,m.zone.name) for m in murlocs]}",
                   target.zone == Zone.GRAVEYARD and finja in p.field and len(murlocs) == 2 and
                   len(p.deck) == 1 and all(m.race == Race.MURLOC for m in murlocs))


def cfm344_nonlethal_attack_does_not_recruit():
    g = game(CardClass.HUNTER)
    p = g.player1
    target = summon_enemy_then_return(g, "CS2_182")
    finja = play(p, "CFM_344")
    g.end_turn()
    g.end_turn()
    for _ in range(3):
        p.give(MURLOC).shuffle_into_deck()
    finja.attack(target)
    recruited = [m for m in p.field if m.race == Race.MURLOC]
    return checked(f"target={target.health}/{target.max_health}:{target.zone.name};finja={finja.zone.name};deck={[c.id for c in p.deck]};recruited={[(m.id,m.zone.name) for m in recruited]}",
                   target.zone == Zone.PLAY and target.health == target.max_health - finja.atk and
                   finja.zone == Zone.GRAVEYARD and not recruited and len(p.deck) == 3)


def cfm602_choose_summon_jade_golem():
    g = game(CardClass.DRUID)
    p = g.player1
    idol = play(p, "CFM_602", choose="CFM_602a")
    golems = [m for m in p.field if m.id.startswith("CFM_712_t")]
    return checked(f"idol={idol.zone.name};golems={[(m.id,m.atk,m.health) for m in golems]};deck={[c.id for c in p.deck]};choice={p.choice}",
                   idol.zone == Zone.GRAVEYARD and len(golems) == 1 and
                   golems[0].id == "CFM_712_t01" and (golems[0].atk,golems[0].health) == (1,1) and p.choice is None)


def cfm602_choose_shuffle_three_idols():
    g = game(CardClass.DRUID)
    p = g.player1
    p.give("CS2_231").shuffle_into_deck()
    idol = play(p, "CFM_602", choose="CFM_602b")
    ids = [c.id for c in p.deck]
    return checked(f"idol={idol.zone.name};deck={ids};idol_copies={ids.count('CFM_602')};field={[m.id for m in p.field]};choice={p.choice}",
                   idol.zone == Zone.GRAVEYARD and ids.count("CFM_602") == 3 and "CS2_231" in ids and
                   not p.field and p.choice is None)


def cfm603_steals_two_attack_until_turn_end():
    g = game(CardClass.PRIEST)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_168")  # Murloc Tidehunter has exactly 2 Attack.
    assert target.atk == 2, (target.id, target.atk)
    spell = play(p, "CFM_603", target)
    stolen = (target.controller is p, target in p.field, target.charge)
    g.end_turn()
    returned = (target.controller is enemy, target in enemy.field, target.zone == Zone.PLAY, target.charge)
    return checked(f"attack={target.atk};stolen={stolen};returned={returned};spell={spell.zone.name}",
                   stolen == (True, True, True) and returned == (True, True, True, False) and spell.zone == Zone.GRAVEYARD)


def cfm603_rejects_three_attack_target():
    g = game(CardClass.PRIEST)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_182")
    spell = p.give("CFM_603")
    before_mana = p.mana
    blocked = False
    try:
        spell.play(target=target)
    except InvalidAction:
        blocked = True
    return checked(f"target_attack={target.atk};blocked={blocked};target_controller={target.controller.name};spell={spell.zone.name};mana={p.mana};before_mana={before_mana}",
                   target.atk == 4 and blocked and target.controller is enemy and target in enemy.field and
                   spell in p.hand and p.mana == before_mana)


def cfm604_heals_friendly_hero_twelve():
    g = game(CardClass.PRIEST)
    p, enemy = g.player1, g.player2
    p.hero.damage = 18
    before = p.hero.health
    enemy_before = enemy.hero.health
    spell = play(p, "CFM_604", p.hero)
    return checked(f"friendly_hero={before}->{p.hero.health};enemy_hero={enemy_before}->{enemy.hero.health};spell={spell.zone.name}",
                   p.hero.health == before + 12 and enemy.hero.health == enemy_before and spell.zone == Zone.GRAVEYARD)


def cfm604_heals_friendly_minion_to_full():
    g = game(CardClass.PRIEST)
    p = g.player1
    target = summon(p, "CS2_182")
    target.damage = 3
    before = target.health
    hero_before = p.hero.health
    spell = play(p, "CFM_604", target)
    return checked(f"friendly_minion={before}->{target.health}/{target.max_health};hero={hero_before}->{p.hero.health};spell={spell.zone.name}",
                   before == 2 and target.health == target.max_health == 5 and p.hero.health == hero_before and spell.zone == Zone.GRAVEYARD)


def seed_enemy_deck(g, ids):
    if g.current_player is not g.player1:
        raise AssertionError("fixture expected Player1 turn before opponent deck setup")
    g.end_turn()
    for card_id in ids:
        g.player2.give(card_id).shuffle_into_deck()
    g.end_turn()
    return [card.id for card in g.player2.deck]


def cfm605_dragon_unlocks_opponent_deck_discover():
    g = game(CardClass.PRIEST)
    p, enemy = g.player1, g.player2
    enemy_ids = seed_enemy_deck(g, [WISP, "CS2_182", "CFM_315"])
    dragon = p.give("EX1_561")
    operative = play(p, "CFM_605")
    choice = p.choice
    offered = [card.id for card in choice.cards]
    assert len(offered) == 3 and set(offered) <= set(enemy_ids), (offered, enemy_ids)
    selected = choice.cards[0]
    selected_id = selected.id
    choice.choose(selected)
    return checked(f"dragon={(dragon.id,int(dragon.race))};opponent_deck={enemy_ids}->{[c.id for c in enemy.deck]};offered={offered};selected={selected_id};own_hand={[c.id for c in p.hand]};operative={operative.zone.name};choice={p.choice}",
                   dragon.race == Race.DRAGON and [c.id for c in enemy.deck] == enemy_ids and
                   p.choice is None and any(card.id == selected_id for card in p.hand) and operative in p.field)


def cfm605_without_dragon_has_no_choice():
    g = game(CardClass.PRIEST)
    p, enemy = g.player1, g.player2
    seed_enemy_deck(g, [WISP, "CS2_182", "CFM_315"])
    operative = play(p, "CFM_605")
    return checked(f"dragon_in_hand={any(c.race == Race.DRAGON for c in p.hand)};choice={p.choice};hand={[c.id for c in p.hand]};operative={operative.zone.name};enemy_deck={[c.id for c in enemy.deck]}",
                   not any(c.race == Race.DRAGON for c in p.hand) and p.choice is None and not p.hand and
                   operative in p.field and len(enemy.deck) == 3)


def cfm606_healing_geode_summons_crystal():
    g = game(CardClass.PRIEST)
    p = g.player1
    geode = play(p, "CFM_606")
    before = geode.health
    damage = play(p, MOONFIRE, geode)
    damaged = geode.health
    p.hero.power.use(target=geode)
    crystals = [m for m in p.field if m.id == "CFM_606t"]
    return checked(f"geode={before}->{damaged}->{geode.health}/{geode.max_health};crystals={[(m.atk,m.health,m.zone.name) for m in crystals]};damage_spell={damage.zone.name};mana={p.mana}",
                   damaged == before - 1 and geode.health == geode.max_health and len(crystals) == 1 and
                   (crystals[0].atk,crystals[0].health) == (2,2) and damage.zone == Zone.GRAVEYARD)


def cfm608_destroys_minion_and_one_max_mana():
    g = game(CardClass.WARLOCK)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_182")
    before = (p.max_mana, p.mana)
    spell = play(p, "CFM_608", target)
    after = (p.max_mana, p.mana)
    return checked(f"target={target.zone.name};mana={before}->{after};used={p.used_mana};spell={spell.zone.name}",
                   target.zone == Zone.GRAVEYARD and before == (10,10) and after == (9,6) and spell.zone == Zone.GRAVEYARD)


def cfm609_hits_self_only_at_own_turn_start():
    g = game(CardClass.MAGE)
    p = g.player1
    soulfiend = play(p, "CFM_609")
    initial = soulfiend.health
    g.end_turn()
    after_opponent_start = soulfiend.health
    g.end_turn()
    after_first_own_start = soulfiend.health
    g.end_turn()
    g.end_turn()
    after_second_own_start = soulfiend.health
    g.end_turn()
    g.end_turn()
    after_third_own_start = soulfiend.health
    g.end_turn()
    g.end_turn()
    after_fourth_own_start = soulfiend.zone.name
    return checked(f"health={initial}->{after_opponent_start}->{after_first_own_start}->{after_second_own_start}->{after_third_own_start};after_fourth_own_start={after_fourth_own_start}",
                   after_opponent_start == initial and after_first_own_start == initial - 2 and
                   after_second_own_start == initial - 4 and after_third_own_start == initial - 6 and
                   after_fourth_own_start == Zone.GRAVEYARD.name)


CASES = {
    "CFM_020": [
        ("unique_deck_sets_zero_this_game", "No duplicate cards sets Hero Power cost to 0 and survives minion death/turn change.", cfm020_no_duplicate_deck, "Constructed two distinct deck entries; checked Hero Power cost immediately and after death/turn change."),
        ("duplicate_deck_does_not_set_zero", "A repeated card in deck leaves Hero Power at its ordinary cost.", cfm020_duplicate_deck, "Deck contains two identical Wisp entries before Battlecry."),
    ],
    "CFM_021": [
        ("freeze_enemy_minion", "Freezing Potion freezes the selected enemy minion and goes to graveyard.", cfm021_freeze_enemy_minion, "Selected an opposing Wisp; asserted frozen state, true opposing controller and both zones."),
        ("freeze_enemy_hero", "Freezing Potion can freeze the enemy hero without changing its Health.", cfm021_freeze_enemy_hero, "Targeted enemy hero and checked frozen state, unchanged Health and spell zone."),
    ],
    "CFM_025": [
        ("survives_attack_draws", "Attacking a minion and surviving draws exactly one known deck card.", cfm025_survives_and_draws, "Readied Burglebot, attacked a Wisp, and checked draw, death zone, and deck."),
        ("dies_attack_no_draw", "Dying during its minion attack does not draw a card.", cfm025_dies_no_draw, "Attacked a 6/7 Boulderfist Ogre with one known card in deck; checked death and hand/deck counts."),
    ],
    "CFM_026": [("secret_triggers_after_opponent_minion_play", "The secret triggers on opponent Play and buffs exactly one random minion in hand by +2/+2.", cfm026_secret_buffs_random_hand_minion, "Armed Secret, played a minion from opponent hand, then checked secret zone and both minion hand cards' stats.")],
    "CFM_039": [("spell_damage_adds_one", "Street Trickster adds one spell damage to Moonfire against an enemy minion.", cfm039_spell_damage_applies, "Used Moonfire on a 4/5 enemy minion and asserted the exact damage and spell zone.")],
    "CFM_060": [("own_casts_buff_enemy_cast_does_not", "Each own played spell grants +2 Attack; an opponent's spell grants none.", cfm060_own_spell_and_opponent_scope, "Played two own Moonfires, then one opposing Moonfire; did not infer behavior for spell effects that cast spells." )],
    "CFM_061": [
        ("heal_friendly_hero_and_overload", "Battlecry restores six to selected friendly hero and applies one Overload.", cfm061_heal_and_overload, "Set own hero to 20 health, targeted it, and read health/overload/minion zone after play."),
        ("heal_friendly_minion_and_overload", "Battlecry restores a damaged friendly minion by six up to full and applies one Overload.", cfm061_heal_friendly_minion_and_overload, "Selected a damaged friendly 4/5 minion and checked exact full health/Overload."),
    ],
    "CFM_062": [("both_adjacent_friendly_minions_gain_shield", "Both adjacent friendly minions gain Divine Shield; self and enemy do not.", cfm062_adjacent_divine_shields, "Inserted protector between a friendly Wisp and Ogre; checked shields and enemy control." )],
    "CFM_063": [("swap_stats_on_selected_minion", "The target's Attack and Health swap while an unrelated enemy minion stays unchanged.", cfm063_swap_attack_health, "Used a 4/5 target and asserted 5/4 current/max health after the card resolves." )],
    "CFM_064": [("hand_trigger_stops_after_play", "A summoned Battlecry minion buffs Baron by +1/+1 only while Baron remains in hand.", cfm064_buffs_only_while_in_hand, "Played Alleycat while Baron was held, played Baron, then summoned a second Alleycat and compared stats." )],
    "CFM_065": [("damage_all_minions_only", "Volcanic Potion deals exactly two to all minions and leaves both heroes unchanged.", cfm065_minions_not_characters, "Placed one 4/5 minion on each side and read all four characters after spell." )],
    "CFM_066": [("next_secret_free_once", "Kabal Lackey makes the next Secret this turn free; following Secret costs normally.", cfm066_next_secret_is_free_only_once, "Measured both base/current costs, played two distinct Secrets, and checked secret zone count." )],
    "CFM_067": [("restore_selected_minion_to_full", "Hozen Healer fully heals the selected minion regardless of controller.", cfm067_heals_selected_minion_to_full, "Selected a damaged opposing 4/5 minion; checked exact full health and unchanged control/zone." )],
    "CFM_094": [("five_damage_all_characters", "Felfire Potion hits both heroes and all minions for five.", cfm094_hits_all_characters_for_five, "Placed a 4/5 minion on both sides; verified both die and both heroes lose five." )],
    "CFM_120": [("deathrattle_heals_both_heroes", "Mistress death restores exactly four to each damaged hero.", cfm120_deathrattle_heals_both_heroes, "Set both heroes to known health, triggered actual death, and checked both hero totals and card zone." )],
    "CFM_300": [("taunt_blocks_hero_face", "Public Defender is a 0/7 Taunt and forces a legal hero attack onto it.", cfm300_taunt_blocks_face_attack, "Opposing hero equipped a 1-Attack weapon; face attack was attempted then Taunt was attacked." )],
    "CFM_305": [("buffs_all_minions_in_hand", "Smuggler's Run buffs every minion in hand by +1/+1, not a spell or a later summoned token.", cfm305_buffs_all_hand_minions_not_spell_or_summon_token, "Checked two held minions and spell, then played both minions and checked Alleycat's unbuffed 1/1 token." )],
    "CFM_308": [
        ("choose_gain_10_armor", "Kun's Armor branch grants exactly 10 Armor.", cfm308_gain_ten_armor_choice, "Played the actual minion using the Armor choice and checked choice closure/field/mana." ),
        ("choose_refill_mana", "Kun's refresh branch restores all ten mana spent on Kun.", cfm308_refill_mana_choice, "Played the actual minion using Refresh Mana Crystals and checked mana, max mana and used-mana state." ),
    ],
    "CFM_310": [
        ("normal_summon_four", "Call in the Finishers summons four 1/1 Murlocs.", cfm310_summons_four_murlocs, "Played on an empty board and inspected all token stats and spell zone." ),
        ("summon_respects_board_cap", "With two open slots, only two of the four 1/1 Murlocs can be summoned.", cfm310_stops_at_seven_minions, "Started with five minions; checked cap, token count, spell resolution and open slots." ),
    ],
    "CFM_312": [("chieftain_golem_taunt", "Jade Chieftain summons a 1/1 Jade Golem with Taunt; the Chieftain itself has no Taunt.", cfm312_summons_taunt_jade_golem, "Played on empty board and inspected generated golem identity/stats/keywords and source minion." )],
    "CFM_313": [("discover_overload_shaman_card", "Finders Keepers offers three collectible Shaman cards, all with Overload; selection resolves and applies Overload (1).", cfm313_discover_overload_shaman_card, "Inspected each live Discover choice's class/Overload/collectible metadata, chose one and checked hand/choice/Overload state." )],
    "CFM_315": [("summons_cat_token", "Alleycat's Battlecry summons exactly one 1/1 Cat in addition to its own body.", cfm315_alleycat_summons_one_cat, "Played Alleycat and checked both minion identities, stats, and board count." )],
    "CFM_316": [("deathrattle_uses_current_attack", "After +3 Attack, Rat Pack death summons five 1/1 Rats, matching its current Attack.", cfm316_deathrattle_counts_current_attack, "Buffed with Blessing of Might before triggering actual death; checked token count/stats and card zones." )],
    "CFM_321": [("discover_three_allowed_classes", "Grimestreet Informant offers collectible Hunter, Paladin, or Warrior cards and puts the selected card in hand.", cfm321_discover_only_three_classes, "Read all three live choice card classes and collectible flags, then selected one and checked choice closure/hand." )],
    "CFM_324": [("deathrattle_shuffles_storm_guardian", "White Eyes death puts exactly one Storm Guardian in its owner's deck without removing the existing deck card.", cfm324_deathrattle_shuffles_storm_guardian, "Seeded a known deck card, triggered actual death and checked deck IDs, count, zones." )],
    "CFM_325": [("weapon_aura_tracks_equip_break", "Small-Time Buccaneer gains +2 while a weapon is equipped and loses it when the weapon breaks.", cfm325_weapon_aura_enters_and_leaves, "Measured no-weapon baseline, equipped Lights Justice, depleted all four durability through real attacks, and checked graveyard/equipment/Attack." )],
    "CFM_328": [
        ("draws_two_with_six_current_health", "A controlled minion at exactly 6 current Health enables two draws.", cfm328_draws_two_at_six_current_health, "Used a 7-health minion with one damage and two known deck cards; checked current/max health and hand/deck deltas." ),
        ("no_draw_with_five_current_health", "A minion with 7 maximum but only 5 current Health does not enable draws.", cfm328_does_not_draw_at_five_current_health, "Used a 7-health minion with two damage and one known deck card; checked current/max health and hand/deck." ),
    ],
    "CFM_333": [("attacks_minion_hits_hero", "After Knuckles attacks a minion, it also deals its Attack to the enemy hero.", cfm333_attack_minion_also_hits_hero, "Readied Knuckles on a later own turn, attacked a real opposing Wisp, and checked target/hero/attacker health." )],
    "CFM_334": [("random_beast_handbuff", "Smuggler's Crate gives exactly one held Beast +2/+2; the other Beast and non-Beast remain unchanged.", cfm334_buffs_exactly_one_random_hand_beast, "Held two distinct Beasts and a Wisp, resolved the spell, and compared all hand stats." )],
    "CFM_335": [
        ("battlecry_four_damage_minion", "Dispatch Kodo deals its current 4 Attack to a selected enemy minion.", cfm335_battlecry_damages_enemy_minion, "Selected a real opposing 4-current-Health minion; checked its death and Kodo body." ),
        ("battlecry_four_damage_hero", "Dispatch Kodo can target the enemy hero and deal damage equal to its Attack.", cfm335_battlecry_can_target_enemy_hero, "Targeted opposing hero and checked exact health loss against Kodo's Attack." ),
    ],
    "CFM_336": [("deathrattle_random_hand_minion_buff", "Shaky Zipgunner death buffs exactly one minion in hand by +2/+2 and leaves the spell alone.", cfm336_deathrattle_buffs_random_hand_minion, "Held two minions and Moonfire, triggered actual death and compared resulting hand stats." )],
    "CFM_337": [
        ("hero_attack_minion_summons_piranha", "After a hero attack on a minion, Piranha Launcher summons one 1/1 Piranha.", cfm337_attack_minion_summons_piranha, "Equipped launcher and attacked an opposing minion; checked minion death and token stats." ),
        ("hero_attack_face_summons_piranha", "After a hero attack on the enemy hero, Piranha Launcher also summons one 1/1 Piranha.", cfm337_attack_hero_also_summons_piranha, "Equipped launcher and attacked the opposing hero; checked exact hero damage and token stats." ),
    ],
    "CFM_338": [("battlecry_random_hand_beast_buff", "Trogg Beastrager gives exactly one held Beast +1/+1 and leaves the other Beast/non-Beast unchanged.", cfm338_battlecry_buffs_one_random_hand_beast, "Held two Beasts and a Wisp, played Trogg and compared hand stats and board zone." )],
    "CFM_341": [("deathrattle_enemy_minions_only", "Sergeant Sally deals Attack-based damage to all enemy minions while friendly minions remain undamaged.", cfm341_deathrattle_damages_enemy_minions_only, "Buffed Sally to 4 Attack; placed a friendly 1/1 and opposing 1/1 plus 4/5 minions, then triggered death." )],
    "CFM_342": [
        ("two_attack_weapon_no_buff", "A 2-Attack weapon does not trigger Luckydo Buccaneer's +4/+4.", cfm342_weapon_below_three_attack_no_buff, "Equipped Doomhammer (2 Attack), then played Buccaneer and read exact Attack/Health." ),
        ("three_attack_weapon_buff", "A 3-Attack weapon triggers exactly +4/+4.", cfm342_weapon_at_three_attack_buff, "Equipped Fiery War Axe (3 Attack), then played Buccaneer and read exact Attack/Health." ),
    ],
    "CFM_343": [
        ("first_golem_and_taunt", "Jade Behemoth has Taunt and summons a first 1/1 Jade Golem.", cfm343_first_jade_golem_and_behemoth_taunt, "Played alone and checked Behemoth's keyword separately from the first generated Jade Golem." ),
        ("golem_scales_with_prior_jade", "After a prior Jade Golem, Behemoth summons the 2/2 Jade Golem while retaining its own Taunt.", cfm343_scales_after_prior_jade_golem, "Played Jade Blossom first, then Behemoth; checked token sequence/stats and both bodies." ),
    ],
    "CFM_344": [
        ("kill_recruits_two_from_deck", "Finja killing a minion recruits exactly two Murlocs from the deck.", cfm344_kill_summons_two_murlocs_from_deck, "Readied Finja, seeded three Murlocs after turn draw, killed a real opposing Wisp, and inspected board/deck." ),
        ("nonlethal_attack_does_not_recruit", "Attacking without killing the defender recruits no Murlocs; deck remains unchanged.", cfm344_nonlethal_attack_does_not_recruit, "Readied Finja, attacked a real opposing 4/5; checked target/Finja death and remaining Murloc deck." ),
    ],
    "CFM_602": [
        ("choose_summon_golem", "Jade Idol's first choice summons a 1/1 Jade Golem.", cfm602_choose_summon_jade_golem, "Explicitly chose summon branch and checked token identity/stats, spell zone, and choice completion." ),
        ("choose_shuffle_three", "Jade Idol's second choice shuffles exactly three copies into deck and summons none.", cfm602_choose_shuffle_three_idols, "Seeded a known deck card, chose shuffle branch, then counted exact added card IDs and zones." ),
    ],
    "CFM_603": [
        ("steal_two_attack_then_return", "Potion of Madness temporarily steals a 2-Attack enemy minion and returns it at end of turn.", cfm603_steals_two_attack_until_turn_end, "Stole a real opposing 2-Attack Tidehunter, verified control/Charge, ended turn and checked return." ),
        ("reject_three_attack_target", "A 4-Attack enemy minion cannot be selected; card/mana/control remain unchanged.", cfm603_rejects_three_attack_target, "Attempted an illegal target and asserted InvalidAction before movement or payment." ),
    ],
    "CFM_604": [
        ("heal_friendly_hero_twelve", "Greater Healing Potion restores exactly 12 to a friendly hero and leaves the enemy hero unchanged.", cfm604_heals_friendly_hero_twelve, "Set own hero to 12 health, cast on own hero and checked exact health delta/card zone."),
        ("heal_friendly_minion_to_full", "Greater Healing Potion restores a damaged friendly minion to its Health cap without healing the hero.", cfm604_heals_friendly_minion_to_full, "Selected a damaged friendly 4/5 minion and checked full health/unchanged hero/card zone."),
    ],
    "CFM_605": [
        ("dragon_enables_copied_deck_discover", "Holding a Dragon opens Discover from the opponent deck; chosen card is copied to hand and original deck stays intact.", cfm605_dragon_unlocks_opponent_deck_discover, "Seeded three distinct opponent deck cards, held Alexstrasza, inspected actual choices, selected one, and compared opponent deck." ),
        ("no_dragon_no_choice", "Without a Dragon in hand, Battlecry gives no Discover choice and does not alter opponent deck.", cfm605_without_dragon_has_no_choice, "Seeded opponent deck with three cards but no Dragon in own hand; checked choice, hand, board and deck." ),
    ],
    "CFM_606": [("healing_self_summons_2_2", "Healing Mana Geode after damage summons exactly one 2/2 Crystal.", cfm606_healing_geode_summons_crystal, "Damaged Geode with Moonfire, healed it with Priest Hero Power, and checked health/token stats/zones." )],
    "CFM_608": [("destroy_minion_and_reduce_max_mana", "Blastcrystal Potion destroys the selected minion, reduces max Mana by one, and refunds the crystal destruction's spend.", cfm608_destroys_minion_and_one_max_mana, "Captured max/current Mana, destroyed a real enemy minion, then checked post-cost values and zones." )],
    "CFM_609": [("self_damage_at_own_turn_start", "Fel Orc Soulfiend is unchanged at opponent turn start, takes 2 at own turn start, then dies on next own start when lethal.", cfm609_hits_self_only_at_own_turn_start, "Played minion, stepped through opponent start and two own starts, reading health/zone after each." )],
}

BLOCKERS = {
    "CFM_060": "直接由玩家打出的法术已验证会加攻，但 CAST-001 的随机/效果代施法事件语义尚未证实；依现有底层机制核查结果保留黄卡。",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="index in frozen first-44 slice")
    parser.add_argument("--limit", type=int, default=44, help="maximum cards to run")
    args = parser.parse_args()
    end = min(len(CARDS), args.start + args.limit)
    selected = CARDS[args.start:end]
    for cid in selected:
        if cid not in CASES:
            print(f"{cid}: not yet implemented; stopping at card boundary")
            break
        audit_card(cid, CASES[cid], blocker=BLOCKERS.get(cid))
    print(f"slice={args.start}:{end}; completed={sum(1 for row in VERDICT_ROWS if row['card_id'] in selected)}")


if __name__ == "__main__":
    main()
