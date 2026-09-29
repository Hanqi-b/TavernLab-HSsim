"""Card-specific live behavior probes for the frozen KARA YELLOW baseline.

Run with ``venv/bin/python reports/.../kara_probe_a.py``. Rows are persisted
after each case/card; importing this module never clears existing evidence.
"""

import csv
import argparse
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Rarity, Zone

import fireplace.cards as carddb
from fireplace.managers import BaseObserver

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import (  # noqa: E402
    CHICKEN,
    FIREBALL,
    KOBOLD_GEOMANCER,
    MOONFIRE,
    MURLOC,
    SOULFIRE,
    THE_COIN,
    WHELP,
    WISP,
    prepare_empty_game,
    prepare_game,
)

for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)
logging.getLogger("fireplace").setLevel(logging.CRITICAL)

PROBE = HERE / "kara_probe_a.csv"
VERDICT = HERE / "kara_verdict_a.csv"
BASELINE = HERE / "three_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
MECHANISMS = HERE / "card_mechanism.csv"
QUALITY = HERE / "card_quality.csv"
ISSUES = HERE / "mechanism_issues.csv"
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


BASE_ROWS = [r for r in read_csv(BASELINE) if r["set"].startswith("One Night in Karazhan")]
CARDS = [r["card_id"] for r in BASE_ROWS]
assert len(CARDS) == 43 and CARDS[0] == "KAR_004" and CARDS[-1] == "KAR_712"
MASTER_ROWS = {r["card_id"]: r for r in read_csv(MASTER)}
OLD_QUALITY = {r["card_id"]: r for r in read_csv(QUALITY)}
MECH_ROWS = read_csv(MECHANISMS)
LABELS = {cid: sorted({r["mechanic"] for r in MECH_ROWS if r["card_id"] == cid}) for cid in CARDS}
OLD_MECH_REASONS = {
    cid: sorted({r["reason"] for r in MECH_ROWS if r["card_id"] == cid and r["reason"]})
    for cid in CARDS
}
PROBE_ROWS = read_csv(PROBE)
VERDICT_ROWS = read_csv(VERDICT)


def prepare_card(cid):
    """Replace only a card's stale rows once its fresh behavior tests start."""
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != cid]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def game(class1=CardClass.MAGE, class2=None, seed=417, drafted=False, include=()):
    random.seed(seed)
    if drafted:
        g = prepare_game(class1, class2, include=include)
    else:
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


def play(player, cid, target=None, choose=None):
    card = player.give(cid)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    card.play(**kwargs)
    return card


def summon(player, cid):
    return player.summon(cid)


def put_in_deck(player, cid):
    card = player.give(cid)
    card.shuffle_into_deck()
    return card


def observe(detail, condition):
    assert condition, detail
    return detail


def case(cid, case_id, expected, fn, notes):
    return (cid, case_id, expected, fn, notes, set(LABELS[cid]))


def _k004_spell_trap():
    g = game(CardClass.HUNTER)
    p, foe = g.player1, g.player2
    secret = play(p, "KAR_004")
    g.end_turn()
    foe_minion = summon(foe, WISP)
    no_trigger = len(p.field)
    spell = play(foe, MOONFIRE, target=foe.hero)
    panthers = [m for m in p.field if m.id == "KAR_004a"]
    state = (secret in p.secrets, secret.zone.name, no_trigger, spell.zone.name,
             [(m.atk, m.health, m.stealthed, m.zone.name) for m in panthers], foe_minion.zone.name)
    return observe(f"secret_live={state[0]};secret_zone={state[1]};after_enemy_minion_field_count={state[2]};spell={state[3]};panthers={state[4]};enemy_minion={state[5]}",
                   state[0] is False and state[1] == Zone.GRAVEYARD.name and state[2] == 0 and spell.zone == Zone.GRAVEYARD
                   and len(panthers) == 1 and (panthers[0].atk, panthers[0].health, panthers[0].stealthed) == (4, 2, True)
                   and foe_minion in foe.field)


def _k005_deathrattle():
    g = game(CardClass.HUNTER)
    p = g.player1
    grandma = play(p, "KAR_005")
    wolf_expected = carddb.db["KAR_005a"]
    play(p, MOONFIRE, target=grandma)
    wolves = [m for m in p.field if m.id == "KAR_005a"]
    return observe(f"grandmother={grandma.zone.name};wolves={[(m.atk,m.health,m.zone.name) for m in wolves]};token_data={(wolf_expected.atk,wolf_expected.health)}",
                   grandma.zone == Zone.GRAVEYARD and len(wolves) == 1
                   and (wolves[0].atk, wolves[0].health, wolves[0].zone) == (3, 2, Zone.PLAY))


def _k006_secret_cost_and_aura_end():
    g = game(CardClass.HUNTER)
    p = g.player1
    hunter = play(p, "KAR_006")
    secret = p.give("EX1_611")
    nonsecret = p.give(MOONFIRE)
    after_aura = (secret.cost, nonsecret.cost)
    hunter.destroy()
    after_leave = (secret.cost, nonsecret.cost, hunter.zone.name)
    return observe(f"while_huntress={after_aura};after_death={after_leave}",
                   after_aura == (0, 0) and after_leave == (2, 0, Zone.GRAVEYARD.name))


def _k009_random_mage_spell():
    results = []
    for seed in range(12):
        g = game(CardClass.MAGE, seed=900 + seed)
        p = g.player1
        book = play(p, "KAR_009")
        gained = [c for c in p.hand if c is not book]
        assert book in p.field and len(gained) == 1, (seed, [c.id for c in p.hand])
        got = gained[0]
        assert got.type == CardType.SPELL and CardClass.MAGE in got.data.classes, (seed, got.id, got.data.classes)
        results.append(got.id)
    return observe(f"12_seeds_spell_ids={results};distinct={len(set(results))}", len(set(results)) > 1)


def _k010_holding_dragon_branch():
    no_dragon = game(CardClass.PALADIN, seed=1001)
    p0 = no_dragon.player1
    card0 = play(p0, "KAR_010")
    without = [m.id for m in p0.field]
    with_dragon = game(CardClass.PALADIN, seed=1002)
    p1, foe = with_dragon.player1, with_dragon.player2
    dragon = p1.give(WHELP)
    card1 = play(p1, "KAR_010")
    tokens = [m for m in p1.field if m.id == "KAR_010a"]
    token_state = [(m.atk, m.health, m.zone.name) for m in tokens]
    return observe(f"no_dragon_field={without};holding_dragon={dragon.zone.name};dragon_branch_field={[m.id for m in p1.field]};tokens={token_state};enemy_field={[m.id for m in foe.field]}",
                   len(without) == 1 and card0 in p0.field and dragon in p1.hand and card1 in p1.field
                   and len(tokens) == 2 and token_state == [(1, 1, "PLAY")] * 2 and len(foe.field) == 0)


def _k011_taunt_whiteboard():
    g = game(CardClass.WARRIOR)
    p = g.player1
    thespian = play(p, "KAR_011")
    return observe(f"id={thespian.id};stats={(thespian.atk,thespian.health,thespian.max_health)};taunt={thespian.taunt};zone={thespian.zone.name}",
                   thespian in p.field and thespian.taunt and (thespian.atk, thespian.health, thespian.max_health) == (3, 2, 2))


def _k011_taunt_blocks_attack_then_releases():
    g = game(CardClass.WARRIOR)
    p, foe = g.player1, g.player2
    guard = play(p, "KAR_011")
    attacker = summon(foe, "CS2_182")
    g.end_turn()
    before = (guard in attacker.attack_targets, p.hero in attacker.attack_targets)
    attacker.attack(guard)
    after = (guard.zone.name, p.hero.health, p.hero in attacker.attack_targets)
    return observe(f"taunt_target_gate={before};after_attack={after}",
                   before == (True, False) and after == ("GRAVEYARD", 30, True))


def _k013_silence_and_draw():
    g = game(CardClass.PRIEST)
    p = g.player1
    drawn = put_in_deck(p, WISP)
    target = summon(p, WISP)
    play(p, "CS2_009", target=target)  # Mark of the Wild: stats and Taunt are removable.
    before = (target.atk, target.max_health, target.taunt)
    purify = play(p, "KAR_013", target=target)
    after = (target.atk, target.health, target.max_health, target.taunt, target.zone.name)
    return observe(f"before={before};after={after};drawn={drawn.zone.name};hand={[c.id for c in p.hand]};spell={purify.zone.name}",
                   before == (3, 3, True) and after == (1, 1, 1, False, "PLAY")
                   and drawn in p.hand and purify.zone == Zone.GRAVEYARD)


def _k021_witchdoctor_trigger():
    totem_ids = {"CS2_050", "CS2_051", "CS2_052", "NEW1_009"}
    results = []
    for seed in range(16):
        g = game(CardClass.SHAMAN, seed=2100 + seed)
        p, foe = g.player1, g.player2
        witch = play(p, "KAR_021")
        own_spell = play(p, THE_COIN)
        own_tokens = [m.id for m in p.field if m is not witch]
        assert len(own_tokens) == 1 and own_tokens[0] in totem_ids, (seed, own_tokens)
        g.end_turn()
        foe_spell = play(foe, MOONFIRE, target=p.hero)
        after_foe = [m.id for m in p.field if m is not witch]
        assert len(after_foe) == 1, (seed, own_tokens, after_foe)
        results.append(own_tokens[0])
    return observe(f"16_own_coin_totems={results};distinct={len(set(results))};opponent_spell_no_trigger=true",
                   len(set(results)) > 1)


def _k025_token_pack_and_capacity():
    g = game(CardClass.MAGE)
    p = g.player1
    spell = play(p, "KAR_025")
    first = sorted((m.id, m.atk, m.health) for m in p.field)
    g2 = game(CardClass.MAGE, seed=2502)
    p2 = g2.player1
    for _ in range(6):
        summon(p2, WISP)
    second_spell = play(p2, "KAR_025")
    second = sorted((m.id, m.atk, m.health) for m in p2.field if m.id.startswith("KAR_025"))
    return observe(f"first_pack={first};one_free_slot_result={second};spell_zones={(spell.zone.name,second_spell.zone.name)};boards={(len(p.field),len(p2.field))}",
                   first == [("KAR_025a", 1, 1), ("KAR_025b", 2, 2), ("KAR_025c", 3, 3)]
                   and second == [("KAR_025a", 1, 1)] and len(p.field) == 3 and len(p2.field) == 7
                   and spell.zone == second_spell.zone == Zone.GRAVEYARD)


def _k026_pawns_equal_enemy_count():
    g = game(CardClass.WARRIOR)
    p, foe = g.player1, g.player2
    enemies = [summon(foe, cid) for cid in (WISP, WHELP, CHICKEN)]
    spell = play(p, "KAR_026")
    pawns = [m for m in p.field if m.id == "KAR_026t"]
    state = [(m.atk, m.health, m.taunt, m.zone.name) for m in pawns]
    return observe(f"enemy_count={len(enemies)};pawn_count={len(pawns)};pawns={state};spell={spell.zone.name}",
                   len(pawns) == len(enemies) == 3 and state == [(1, 1, True, "PLAY")] * 3
                   and spell.zone == Zone.GRAVEYARD)


def _k028_weapon_attack_limits():
    g = game(CardClass.WARRIOR)
    p, foe = g.player1, g.player2
    weapon = play(p, "KAR_028")
    targets = [summon(foe, WISP) for _ in range(4)]
    hero_target_available = foe.hero in p.hero.attack_targets
    attack_while_equipped = p.hero.atk
    attacks = []
    for target in targets:
        can_attack = p.hero.can_attack()
        if can_attack:
            p.hero.attack(target)
        attacks.append((can_attack, target.zone.name, p.weapon.durability if p.weapon else 0))
    state = (weapon.id, attack_while_equipped, p.hero.atk, hero_target_available, attacks, p.weapon)
    return observe(f"weapon={state[0]};attack_while_equipped={state[1]};attack_after_break={state[2]};enemy_hero_legal={state[3]};attacks={state[4]};weapon_after={state[5]}",
                   state[0] == "KAR_028" and state[1] == 3 and state[2] == 0 and not hero_target_available
                   and all(row[0] and row[1] == Zone.GRAVEYARD.name for row in attacks)
                   and state[5] is None)


def _k029_egg_death_draw():
    g = game(CardClass.WARRIOR)
    p = g.player1
    drawn = put_in_deck(p, WISP)
    egg = play(p, "KAR_029")
    before = len(p.hand)
    egg.destroy()
    return observe(f"egg={egg.zone.name};draw={drawn.zone.name};hand={[c.id for c in p.hand]};hand_delta={len(p.hand)-before}",
                   egg.zone == Zone.GRAVEYARD and drawn in p.hand and len(p.hand) == before + 1)


def _k030_spider_summon():
    g = game(CardClass.HUNTER)
    p = g.player1
    spider = play(p, "KAR_030a")
    tokens = [m for m in p.field if m.id == "KAR_030"]
    return observe(f"body={(spider.atk,spider.health,spider.zone.name)};spider_tokens={[(m.atk,m.health,m.zone.name) for m in tokens]}",
                   spider in p.field and len(tokens) == 1 and (tokens[0].atk, tokens[0].health, tokens[0].zone) == (1, 3, Zone.PLAY))


def _k033_book_wyrm_branches():
    g0 = game(CardClass.PRIEST, seed=3301)
    p0 = g0.player1
    wyrm0 = play(p0, "KAR_033")
    no_dragon = (len(p0.field), wyrm0.zone.name, wyrm0.powered_up)
    g1 = game(CardClass.PRIEST, seed=3302)
    p1, enemy1 = g1.player1, g1.player2
    p1.give(WHELP)
    victim_small = summon(enemy1, WISP)
    victim_large = summon(enemy1, "CS2_182")
    victim_large.atk = 4
    wyrm1 = p1.give("KAR_033")
    legal = list(wyrm1.targets)
    wyrm1.play(target=victim_small)
    with_dragon = (victim_small.zone.name, victim_large.zone.name, wyrm1.zone.name,
                   victim_large in legal, victim_small in legal)
    return observe(f"without_dragon={no_dragon};with_dragon={with_dragon};legal_targets={[m.id for m in legal]}",
                   no_dragon == (1, "PLAY", False)
                   and with_dragon == ("GRAVEYARD", "PLAY", "PLAY", False, True))


def _k035_own_spell_heal_only():
    g = game(CardClass.PRIEST)
    p, foe = g.player1, g.player2
    p.hero.set_current_health(20)
    priest = play(p, "KAR_035")
    play(p, THE_COIN)
    after_own = p.hero.health
    g.end_turn()
    play(foe, THE_COIN)
    after_foe = p.hero.health
    return observe(f"priest={priest.zone.name};after_own_spell={after_own};after_opponent_spell={after_foe}",
                   priest in p.field and after_own == 23 and after_foe == 23)


def _k036_own_spell_health_only():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    anomaly = play(p, "KAR_036")
    initial = (anomaly.health, anomaly.max_health)
    play(p, THE_COIN)
    after_own = (anomaly.health, anomaly.max_health)
    g.end_turn()
    play(foe, THE_COIN)
    after_foe = (anomaly.health, anomaly.max_health)
    return observe(f"initial={initial};after_own_spell={after_own};after_opponent_spell={after_foe}",
                   initial == (1, 1) and after_own == (2, 2) and after_foe == (2, 2))


def _k037_secret_condition():
    g0 = game(CardClass.HUNTER, seed=3701)
    p0 = g0.player1
    plain = play(p0, "KAR_037")
    base = (plain.atk, plain.health, plain.taunt)
    g1 = game(CardClass.HUNTER, seed=3702)
    p1 = g1.player1
    secret = play(p1, "EX1_130")
    watcher = play(p1, "KAR_037")
    powered = (secret in p1.secrets, watcher.atk, watcher.health, watcher.taunt)
    return observe(f"without_secret={base};with_secret={powered}",
                   base == (3, 6, False) and powered == (True, 4, 7, True))


def _k041_lurker_destroy_and_resummon_owner():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    victim = summon(foe, WISP)
    lurker = play(p, "KAR_041", target=victim)
    after_battlecry = (victim.zone.name, lurker in p.field, len(foe.field))
    lurker.destroy()
    returned = [m for m in foe.field if m.id == WISP]
    after_death = (lurker.zone.name, [(m.atk, m.health, m.zone.name) for m in returned], len(p.field))
    return observe(f"after_battlecry={after_battlecry};after_lurker_death={after_death}",
                   after_battlecry == ("GRAVEYARD", True, 0)
                   and after_death == ("GRAVEYARD", [(1, 1, "PLAY")], 0))


def _k044_moroes_stealth_and_turn_trigger():
    g = game(CardClass.ROGUE)
    p = g.player1
    moroes = play(p, "KAR_044")
    before = (moroes.stealthed, [m.id for m in p.field])
    g.end_turn()
    stewards = [m for m in p.field if m.id == "KAR_044a"]
    after = [(m.atk, m.health, m.zone.name) for m in stewards]
    return observe(f"before_end={before};stewards={after};moroes={moroes.zone.name}",
                   before[0] and before[1] == ["KAR_044"] and moroes in p.field
                   and len(stewards) == 1 and after == [(1, 1, "PLAY")])


def _k044_stealth_blocks_enemy_target_and_attack():
    g = game(CardClass.ROGUE)
    p, foe = g.player1, g.player2
    moroes = play(p, "KAR_044")
    friendly_spell = p.give(FIREBALL)
    own_target = moroes in friendly_spell.play_targets
    attacker = summon(foe, "CS2_182")
    g.end_turn()
    enemy_spell = foe.give(FIREBALL)
    enemy_target = moroes in enemy_spell.play_targets
    enemy_attack = moroes in attacker.attack_targets
    attacker.attack(p.hero)
    return observe(f"friendly_spell_target={own_target};enemy_spell_target={enemy_target};enemy_attack_target={enemy_attack};moroes={moroes.zone.name};hero_health={p.hero.health}",
                   own_target and not enemy_target and not enemy_attack
                   and moroes.zone == Zone.PLAY and p.hero.health == 26)


def _k057_ivory_knight_discover_and_heal():
    results = []
    for seed in range(12):
        g = game(CardClass.PALADIN, seed=5700 + seed)
        p = g.player1
        p.hero.set_current_health(10)
        knight = play(p, "KAR_057")
        options = list(p.choice.cards)
        assert len(options) == 3, (seed, [c.id for c in options])
        assert all(c.type == CardType.SPELL and (CardClass.NEUTRAL in c.data.classes or CardClass.PALADIN in c.data.classes)
                   for c in options), (seed, [(c.id, c.type, c.data.classes) for c in options])
        chosen = options[0]
        cost = chosen.cost
        p.choice.choose(chosen)
        state = (p.choice, chosen in p.hand, p.hero.health, cost, knight.zone.name)
        assert state == (None, True, min(30, 10 + cost), cost, "PLAY"), (seed, state)
        results.append((seed, [c.id for c in options], chosen.id, cost, p.hero.health))
    return observe(f"12_seeded_paladin_discover_choices_and_heals={results}", len(results) == 12)


def _k061_curator_draw_tribes():
    g = game(CardClass.PALADIN)
    p = g.player1
    murloc = put_in_deck(p, MURLOC)
    dragon = put_in_deck(p, WHELP)
    beast = put_in_deck(p, CHICKEN)
    curator = play(p, "KAR_061")
    drawn = (murloc in p.hand, dragon in p.hand, beast in p.hand)
    board = (curator in p.field, curator.taunt, len(p.hand), len(p.deck))
    return observe(f"drawn_murloc_dragon_beast={drawn};curator={board};hand={[c.id for c in p.hand]}",
                   drawn == (True, True, True) and board == (True, True, 3, 0))


def _k062_historian_discover_branch():
    g0 = game(CardClass.PRIEST, seed=6201)
    p0 = g0.player1
    plain = play(p0, "KAR_062")
    without = (plain in p0.field, p0.choice)
    g1 = game(CardClass.PRIEST, seed=6202)
    p1 = g1.player1
    held_dragon = p1.give(WHELP)
    historian = play(p1, "KAR_062")
    options = list(p1.choice.cards)
    eligible = [(c.id, c.type, Race.DRAGON in c.data.races) for c in options]
    chosen = options[0]
    p1.choice.choose(chosen)
    after = (p1.choice, chosen in p1.hand, held_dragon in p1.hand, historian in p1.field)
    return observe(f"without_dragon={without};held_dragon={held_dragon.zone.name};options={eligible};after_choice={after}",
                   without == (True, None) and len(options) == 3
                   and all(typ == CardType.MINION and dragon for _, typ, dragon in eligible)
                   and after == (None, True, True, True))


def _k063_spell_damage_aura():
    g = game(CardClass.SHAMAN)
    p, foe = g.player1, g.player2
    weapon = play(p, "KAR_063")
    base_attack = p.hero.atk
    enemy_spellpower = summon(foe, KOBOLD_GEOMANCER)
    with_enemy = p.hero.atk
    friendly_spellpower = summon(p, KOBOLD_GEOMANCER)
    with_friendly = p.hero.atk
    friendly_spellpower.destroy()
    after_remove = p.hero.atk
    return observe(f"weapon={weapon.id};base={base_attack};enemy_spellpower={with_enemy};friendly_spellpower={with_friendly};after_friendly_death={after_remove};enemy_stays={enemy_spellpower.zone.name}",
                   weapon.id == "KAR_063" and (base_attack, with_enemy, with_friendly, after_remove) == (1, 1, 3, 1)
                   and enemy_spellpower in foe.field)


def _k065_warden_copy_beast():
    g = game(CardClass.DRUID)
    p, foe = g.player1, g.player2
    beast = summon(p, CHICKEN)
    play(p, "CS2_009", target=beast)
    enemy_beast = summon(foe, CHICKEN)
    warden = p.give("KAR_065")
    legal = list(warden.targets)
    before = (beast.id, beast.atk, beast.max_health, beast.taunt)
    warden.play(target=beast)
    copies = [m for m in p.field if m.id == CHICKEN and m is not beast]
    after = [(m.atk, m.health, m.max_health, m.taunt, m.zone.name) for m in copies]
    return observe(f"friendly_before={before};enemy_target_legal={enemy_beast in legal};copy={after};field={[m.id for m in p.field]}",
                   enemy_beast not in legal and len(copies) == 1 and before == (CHICKEN, 3, 3, True)
                   and after == [(3, 3, 3, True, "PLAY")] and warden in p.field)


def _k069_swashburglar_class_pool():
    results = []
    for seed in range(12):
        g = game(CardClass.ROGUE, CardClass.PRIEST, seed=6900 + seed)
        p = g.player1
        burglar = play(p, "KAR_069")
        gained = list(p.hand)
        assert burglar in p.field and len(gained) == 1, (seed, [c.id for c in gained])
        c = gained[0]
        enemy_class = p.opponent.hero.card_class
        assert c.data.collectible and (enemy_class in c.data.classes or CardClass.NEUTRAL in c.data.classes), (seed, c.id, c.data.classes, enemy_class)
        results.append((c.id, CardClass(enemy_class).name, [CardClass(cl).name for cl in c.data.classes]))
    distinct = len({row[0] for row in results})
    return observe(f"12_seeds_opponent_class_cards={results};distinct={distinct}", distinct > 1)


def _k070_peddler_class_costs():
    # CoinRules reorders the two players at game start; this order gives p1 Rogue.
    g = game(CardClass.PRIEST, CardClass.ROGUE)
    p = g.player1
    mc = p.give("CS1_113")
    shadow_madness = p.give("EX1_334")
    eviscerate = p.give("EX1_124")
    wisp = p.give(WISP)
    before = (mc.cost, shadow_madness.cost, eviscerate.cost, wisp.cost)
    peddler = play(p, "KAR_070")
    after = (mc.cost, shadow_madness.cost, eviscerate.cost, wisp.cost)
    return observe(f"hero_class={CardClass(p.hero.card_class).name};before_offclass1_offclass2_own_neutral={before};after={after};peddler={peddler.zone.name}",
                   p.hero.card_class == CardClass.ROGUE and before == (10, 3, 2, 0)
                   and after == (8, 1, 2, 0) and peddler in p.field)


def _k073_maelstrom_portal():
    g = game(CardClass.SHAMAN)
    p, foe = g.player1, g.player2
    friendly = summon(p, WISP)
    enemies = [summon(foe, WISP), summon(foe, "CS2_182")]
    for enemy in enemies:
        enemy.max_health = 6
        enemy.set_current_health(6)
    heroes_before = (p.hero.health, foe.hero.health)
    spell = play(p, "KAR_073")
    spawned = [m for m in p.field if m is not friendly]
    enemy_after = [(m.health, m.zone.name) for m in enemies]
    heroes_after = (p.hero.health, foe.hero.health)
    state = (friendly.health, enemy_after, heroes_before, heroes_after,
             [(m.id, m.data.cost, m.zone.name) for m in spawned], spell.zone.name)
    return observe(f"friendly_health={state[0]};two_enemies={state[1]};heroes={state[2]}->{state[3]};portal_summon={state[4]};spell={state[5]}",
                   state[0] == 1 and state[1] == [(5, "PLAY"), (5, "PLAY")]
                   and state[2] == state[3] == (30, 30) and len(spawned) == 1
                   and spawned[0].data.cost == 1 and spawned[0].zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def _k075_moonglade_portal():
    g = game(CardClass.DRUID)
    p = g.player1
    p.hero.set_current_health(20)
    spell = play(p, "KAR_075", target=p.hero)
    summoned = [m for m in p.field]
    return observe(f"hero_health={p.hero.health};summoned={[(m.id,m.data.cost,m.zone.name) for m in summoned]};spell={spell.zone.name}",
                   p.hero.health == 26 and len(summoned) == 1 and summoned[0].data.cost == 6
                   and summoned[0].zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def _k076_firelands_portal():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    target = summon(foe, WISP)
    target.max_health = 10
    target.set_current_health(10)
    spell = play(p, "KAR_076", target=target)
    summoned = list(p.field)
    return observe(f"target_health={target.health};target_zone={target.zone.name};summoned={[(m.id,m.data.cost,m.zone.name) for m in summoned]};spell={spell.zone.name}",
                   target.health == 5 and target.zone == Zone.PLAY and len(summoned) == 1
                   and summoned[0].data.cost == 5 and summoned[0].zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def _k077_silvermoon_portal():
    g = game(CardClass.PALADIN)
    p = g.player1
    target = summon(p, WISP)
    spell = play(p, "KAR_077", target=target)
    summoned = [m for m in p.field if m is not target]
    state = (target.atk, target.health, target.max_health, len(summoned),
             [(m.id, m.data.cost, m.zone.name) for m in summoned], spell.zone.name)
    return observe(f"target={(state[0],state[1],state[2])};summoned={state[4]};spell={state[5]}",
                   state[:4] == (3, 3, 3, 1) and summoned[0].data.cost == 2
                   and summoned[0].zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def _k089_imp_discard_draw():
    g = game(CardClass.WARLOCK)
    p = g.player1
    p.discard_hand()  # Remove any starting Coin so Soulfire has one legal discard.
    imp = play(p, "KAR_089")
    discarded = p.give(WISP)
    deck_top = put_in_deck(p, "CS2_182")
    soulfire = p.give(SOULFIRE)
    before = [c.id for c in p.hand]
    soulfire.play(target=p.opponent.hero)
    state = (discarded.zone.name, deck_top.zone.name, [c.id for c in p.hand], soulfire.zone.name, imp in p.field)
    return observe(f"hand_before={before};discarded={state[0]};drawn={state[1]};hand_after={state[2]};soulfire={state[3]};imp_play={state[4]}",
                   discarded.zone == Zone.REMOVEDFROMGAME and deck_top in p.hand
                   and soulfire.zone == Zone.GRAVEYARD and imp in p.field)


def _k091_ironforge_portal():
    g = game(CardClass.WARRIOR)
    p = g.player1
    p.hero.armor = 0
    spell = play(p, "KAR_091")
    summoned = list(p.field)
    return observe(f"armor={p.hero.armor};summoned={[(m.id,m.data.cost,m.zone.name) for m in summoned]};spell={spell.zone.name}",
                   p.hero.armor == 4 and len(summoned) == 1 and summoned[0].data.cost == 4
                   and summoned[0].zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def _k092_valet_secret_branches():
    g0 = game(CardClass.MAGE, seed=9201)
    p0, foe0 = g0.player1, g0.player2
    valet0 = play(p0, "KAR_092")
    no_secret = (foe0.hero.health, valet0 in p0.field)
    g1 = game(CardClass.MAGE, seed=9202)
    p1, foe1 = g1.player1, g1.player2
    secret = play(p1, "EX1_130")
    valet1 = p1.give("KAR_092")
    targets = list(valet1.targets)
    valet1.play(target=foe1.hero)
    with_secret = (secret in p1.secrets, foe1.hero.health, foe1.hero.zone.name, valet1 in p1.field, foe1.hero in targets)
    return observe(f"without_secret={no_secret};with_secret={with_secret}",
                   no_secret == (30, True) and with_secret == (True, 27, "PLAY", True, True))


def _k095_zoobot_tribal_buffs():
    g = game(CardClass.HUNTER)
    p, foe = g.player1, g.player2
    murloc = summon(p, MURLOC)
    beast = summon(p, CHICKEN)
    dragon = summon(p, WHELP)
    enemy = summon(foe, CHICKEN)
    before = [(m.atk, m.health) for m in (murloc, beast, dragon, enemy)]
    zoobot = play(p, "KAR_095")
    after = [(m.atk, m.health) for m in (murloc, beast, dragon, enemy)]
    return observe(f"before={before};after={after};zoobot={zoobot.zone.name}",
                   before == [(1, 1)] * 4 and after == [(2, 2), (2, 2), (2, 2), (1, 1)] and zoobot in p.field)


def _k096_malchezaar_start_of_game():
    g = game(CardClass.MAGE, drafted=True, include=("KAR_096",), seed=9601)
    p = g.player1
    cards = list(p.deck) + list(p.hand)
    legendaries = [c for c in cards if c.data.rarity == Rarity.LEGENDARY]
    result = (len(cards), sum(c.id == "KAR_096" for c in cards), len(legendaries),
              [(c.id, c.data.rarity.name) for c in legendaries])
    return observe(f"deck_plus_hand={result[0]};prince_count={result[1]};legendary_count={result[2]};legendary_ids={result[3]}",
                   len(cards) == 35 and result[1] == 1 and len(legendaries) >= 5)


def _k097_medivh_atiesh_trigger():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    medivh = play(p, "KAR_097")
    weapon_before = (p.weapon.id, p.weapon.durability) if p.weapon else None
    g.end_turn()
    g.end_turn()
    spell = play(p, FIREBALL, target=foe.hero)
    summons = [m for m in p.field if m is not medivh]
    state = (weapon_before, (p.weapon.id, p.weapon.durability) if p.weapon else None,
             [(m.id, m.data.cost, m.zone.name) for m in summons], foe.hero.health, spell.zone.name)
    return observe(f"weapon_before={state[0]};weapon_after={state[1]};spell_summon={state[2]};enemy_health={state[3]};spell={state[4]}",
                   state[0] == ("KAR_097t", 3) and state[1] == ("KAR_097t", 2)
                   and len(summons) == 1 and summons[0].data.cost == 4 and summons[0].zone == Zone.PLAY
                   and foe.hero.health == 24 and spell.zone == Zone.GRAVEYARD and medivh in p.field)


def _k114_barnes_deck_copy():
    g = game(CardClass.DRUID)
    p = g.player1
    original = put_in_deck(p, KOBOLD_GEOMANCER)
    nonminion = put_in_deck(p, MOONFIRE)
    barnes = play(p, "KAR_114")
    copies = [m for m in p.field if m.id == KOBOLD_GEOMANCER]
    state = (original.zone.name, nonminion.zone.name, barnes.zone.name,
             [(m.atk, m.health, m.max_health, m.zone.name) for m in copies], [c.id for c in p.deck])
    return observe(f"original={state[0]};nonminion={state[1]};barnes={state[2]};copy={state[3]};deck={state[4]}",
                   original in p.deck and nonminion in p.deck and barnes in p.field
                   and len(copies) == 1 and (copies[0].atk, copies[0].health, copies[0].max_health) == (1, 1, 1))


def _k204_onyx_bishop_dead_minion():
    g = game(CardClass.PRIEST)
    p = g.player1
    dead = summon(p, WISP)
    play(p, "CS2_009", target=dead)
    dead.destroy()
    before = dead.zone.name
    bishop = play(p, "KAR_204")
    revived = [m for m in p.field if m.id == WISP]
    return observe(f"dead_card_zone={before};bishop={bishop.zone.name};revived={[(m.atk,m.health,m.zone.name) for m in revived]};board={[m.id for m in p.field]}",
                   before == "GRAVEYARD" and bishop in p.field and len(revived) == 1
                   and (revived[0].atk, revived[0].health, revived[0].zone) == (1, 1, Zone.PLAY))


def _k205_discarded_golem_summons():
    g = game(CardClass.WARLOCK)
    p = g.player1
    p.discard_hand()
    golem = p.give("KAR_205")
    soulfire = p.give(SOULFIRE)
    # The Golem is the only card Soulfire can discard after Soulfire leaves hand.
    soulfire.play(target=p.opponent.hero)
    summoned = [m for m in p.field if m.id == "KAR_205"]
    state = (golem.zone.name, soulfire.zone.name, [(m.atk, m.health, m.zone.name) for m in summoned], [c.id for c in p.hand])
    return observe(f"original_zone={state[0]};soulfire={state[1]};golem_on_board={state[2]};hand={state[3]}",
                   soulfire.zone == Zone.GRAVEYARD and len(summoned) == 1
                   and (summoned[0].atk, summoned[0].health, summoned[0].zone) == (3, 3, Zone.PLAY))


def _k702_magician_tribal_buffs():
    g = game(CardClass.HUNTER)
    p, foe = g.player1, g.player2
    murloc = summon(p, MURLOC)
    beast = summon(p, CHICKEN)
    dragon = summon(p, WHELP)
    enemy = summon(foe, WHELP)
    magician = play(p, "KAR_702")
    after = [(m.atk, m.health) for m in (murloc, beast, dragon, enemy)]
    return observe(f"tribal_friendly_enemy_stats={after};magician={magician.zone.name}",
                   after == [(3, 3), (3, 3), (3, 3), (1, 1)] and magician in p.field)


def _k710_arcanosmith_token():
    g = game(CardClass.MAGE)
    p = g.player1
    smith = play(p, "KAR_710")
    tokens = [m for m in p.field if m.id == "KAR_710m"]
    return observe(f"smith={(smith.atk,smith.health,smith.zone.name)};token={[(m.atk,m.health,m.max_health,m.taunt,m.zone.name) for m in tokens]}",
                   smith in p.field and len(tokens) == 1
                   and (tokens[0].atk, tokens[0].health, tokens[0].max_health, tokens[0].taunt, tokens[0].zone)
                   == (0, 5, 5, True, Zone.PLAY))


def _k711_arcane_giant_spells_this_game():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    giant = p.give("KAR_711")
    initial = giant.cost
    play(p, THE_COIN)
    after_one = giant.cost
    play(p, MOONFIRE, target=foe.hero)
    after_two = giant.cost
    g.end_turn()
    play(foe, MOONFIRE, target=p.hero)
    after_opponent = giant.cost
    return observe(f"cost_initial={initial};after_coin={after_one};after_own_moonfire={after_two};after_enemy_spell={after_opponent}",
                   (initial, after_one, after_two, after_opponent) == (12, 11, 10, 10))


def _k712_turn_aura_immune():
    g = game(CardClass.MAGE)
    p, foe = g.player1, g.player2
    illusionist = play(p, "KAR_712")
    immune_own_turn = p.hero.immune
    infernal = play(p, "CS2_064")
    during = (p.hero.health, foe.hero.health, p.hero.immune)
    g.end_turn()
    immune_foe_turn = p.hero.immune
    before_attack = p.hero.health
    foe.give("CS2_064").play()
    after_foe_spell = p.hero.health
    return observe(f"illusionist={illusionist.zone.name};own_turn_immune={immune_own_turn};friendly_infernal={infernal.zone.name};after_friendly={during};opponent_turn_immune={immune_foe_turn};enemy_infernal_health={before_attack}->{after_foe_spell}",
                   immune_own_turn and during == (30, 29, True) and not immune_foe_turn
                   and before_attack == 30 and after_foe_spell == 29 and illusionist in p.field)


TESTS = {
    "KAR_004": [_k004_spell_trap],
    "KAR_005": [_k005_deathrattle],
    "KAR_006": [_k006_secret_cost_and_aura_end],
    "KAR_009": [_k009_random_mage_spell],
    "KAR_010": [_k010_holding_dragon_branch],
    "KAR_011": [_k011_taunt_whiteboard, _k011_taunt_blocks_attack_then_releases],
    "KAR_013": [_k013_silence_and_draw],
    "KAR_021": [_k021_witchdoctor_trigger],
    "KAR_025": [_k025_token_pack_and_capacity],
    "KAR_026": [_k026_pawns_equal_enemy_count],
    "KAR_028": [_k028_weapon_attack_limits],
    "KAR_029": [_k029_egg_death_draw],
    "KAR_030a": [_k030_spider_summon],
    "KAR_033": [_k033_book_wyrm_branches],
    "KAR_035": [_k035_own_spell_heal_only],
    "KAR_036": [_k036_own_spell_health_only],
    "KAR_037": [_k037_secret_condition],
    "KAR_041": [_k041_lurker_destroy_and_resummon_owner],
    "KAR_044": [_k044_moroes_stealth_and_turn_trigger, _k044_stealth_blocks_enemy_target_and_attack],
    "KAR_057": [_k057_ivory_knight_discover_and_heal],
    "KAR_061": [_k061_curator_draw_tribes],
    "KAR_062": [_k062_historian_discover_branch],
    "KAR_063": [_k063_spell_damage_aura],
    "KAR_065": [_k065_warden_copy_beast],
    "KAR_069": [_k069_swashburglar_class_pool],
    "KAR_070": [_k070_peddler_class_costs],
    "KAR_073": [_k073_maelstrom_portal],
    "KAR_075": [_k075_moonglade_portal],
    "KAR_076": [_k076_firelands_portal],
    "KAR_077": [_k077_silvermoon_portal],
    "KAR_089": [_k089_imp_discard_draw],
    "KAR_091": [_k091_ironforge_portal],
    "KAR_092": [_k092_valet_secret_branches],
    "KAR_095": [_k095_zoobot_tribal_buffs],
    "KAR_096": [_k096_malchezaar_start_of_game],
    "KAR_097": [_k097_medivh_atiesh_trigger],
    "KAR_114": [_k114_barnes_deck_copy],
    "KAR_204": [_k204_onyx_bishop_dead_minion],
    "KAR_205": [_k205_discarded_golem_summons],
    "KAR_702": [_k702_magician_tribal_buffs],
    "KAR_710": [_k710_arcanosmith_token],
    "KAR_711": [_k711_arcane_giant_spells_this_game],
    "KAR_712": [_k712_turn_aura_immune],
}


def add_case(cid, case_id, expected, fn, notes, covers):
    try:
        observed = fn()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append({"card_id": cid, "case_id": case_id, "expected": expected,
                       "observed": observed, "outcome": outcome,
                       "notes": f"{notes}; scope_asserted={'|'.join(sorted(covers))}"})
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    return outcome, observed


def finish_card(cid, case_results):
    own = [r for r in PROBE_ROWS if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own), cid
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    covered = set().union(*(set(result[5]) for result in case_results))
    expected_scope = set(LABELS[cid])
    if errors:
        status = "RED"
        reason = "实测断言失败：" + "；".join(f"{r['case_id']}={r['observed']}" for r in errors)
    elif unresolved:
        status = "YELLOW"
        reason = "执行存在未决异常：" + "；".join(f"{r['case_id']}={r['observed']}" for r in unresolved)
    elif covered != expected_scope:
        status = "YELLOW"
        reason = f"本轮未覆盖所有既有机制标签；未覆盖={sorted(expected_scope - covered)}。"
    else:
        status = "GREEN"
        reason = "逐卡对局断言通过：" + "；".join(f"{r['case_id']}={r['observed']}" for r in own)
    master = MASTER_ROWS[cid]
    old = OLD_QUALITY.get(cid, {})
    affected = []
    for issue in read_csv(ISSUES):
        cards = set((issue.get("confirmed_cards", "") + "|" + issue.get("candidate_cards", "")).split("|"))
        if cid in cards:
            affected.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    refs = master.get("test_refs_candidate", "") or "无候选既有测试引用"
    notes = (f"EN={master.get('card_text_en','')}; ZH={master.get('card_text_zh','')}; "
             f"source={master.get('python_source','') or '未发现 Python 卡牌脚本（验证卡牌数据库行为）'}; "
             f"existing_tests={refs}; prior_card_audit={old.get('reason','无')}; "
             f"prior_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
             f"cross_card_issues={' / '.join(affected) if affected else '无'}; "
             f"probe_cases={','.join(r['case_id'] for r in own)}")
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    VERDICT_ROWS.append({"card_id": cid, "status": status, "mechanic_scope": "|".join(LABELS[cid]),
                         "reason": reason, "probe_file": PROBE.name, "notes": notes})
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}")
    return status


def audit_card(cid, funcs):
    prepare_card(cid)
    results = []
    for ix, fn in enumerate(funcs, 1):
        case_id = f"{cid}_live_{ix:02d}"
        expected = f"{fn.__doc__ or fn.__name__}:牌面效果及对应状态变化符合预期"
        row = case(cid, case_id, expected, fn,
                   f"live_game={fn.__name__};每张卡独立设局并断言核心文本状态",)
        outcome, observed = add_case(cid, row[1], row[2], row[3], row[4], row[5])
        results.append(row)
    return finish_card(cid, results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated baseline card ids")
    parser.add_argument("--limit", type=int, help="maximum cards in this invocation")
    parser.add_argument("--force", action="store_true", help="rerun selected card(s)")
    args = parser.parse_args()
    existing = {r["card_id"] for r in VERDICT_ROWS}
    selected = [cid for cid in CARDS if not args.only or cid in set(args.only.split(","))]
    if args.limit is not None:
        selected = selected[:args.limit]
    for cid in selected:
        if cid in existing and not args.force:
            continue
        funcs = TESTS.get(cid)
        if not funcs:
            raise RuntimeError(f"No card-specific behavior probe for {cid}")
        audit_card(cid, funcs)
    print(f"Completed verdicts: {len({r['card_id'] for r in VERDICT_ROWS})}/{len(CARDS)}; probes={len(PROBE_ROWS)}")


if __name__ == "__main__":
    main()
