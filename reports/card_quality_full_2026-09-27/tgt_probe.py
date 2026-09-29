"""Card-specific TGT behavior probes against the current Fireplace runtime.

Run from the repository root with:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/tgt_probe.py

The exact input roster is the frozen four-set baseline. This script records
one or more real-game state assertions per card and flushes the CSV files after
each card so an interrupted run still has a usable checkpoint.
"""

import csv
import logging
import random
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Zone

from utils import (
    ANIMATED_STATUE,
    CIRCLE_OF_HEALING,
    FIREBALL,
    HAND_OF_PROTECTION,
    IMP,
    KOBOLD_GEOMANCER,
    LIGHTS_JUSTICE,
    MOONFIRE,
    PYROBLAST,
    SILENCE,
    THE_COIN,
    WISP,
    prepare_empty_game,
)


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASELINE = HERE / "four_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "tgt_probe.csv"
VERDICT_OUT = HERE / "tgt_verdict.csv"
PROBE_FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
VERDICT_FIELDS = ["card_id", "status", "mechanic_scope", "reason", "probe_file", "notes"]

CASES = {}
OUT_ROWS = []
VERDICTS = []


def fresh_game(c1=CardClass.MAGE, c2=CardClass.MAGE, seed=173):
    random.seed(seed)
    game = prepare_empty_game(c1, c2)
    # Card pools and other in-game random choices use BaseGame.random, not the
    # module-global random generator. Seed both so a case is reproducible.
    game.random.seed(seed)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.max_mana = 10
        player.is_standard = False
    return game


def play(player, card_id, target=None, choose=None):
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    card.play(**kwargs)
    return card


def setup_probe(card_id, case_id, expected, fn, extra_note=""):
    CASES.setdefault(card_id, []).append((case_id, expected, fn, extra_note))


def state(zone_obj):
    return getattr(getattr(zone_obj, "zone", None), "name", "?")


def ids(cards):
    return [getattr(card, "id", "?") for card in cards]


def safe_probe(card_id, case_id, expected, fn, meta):
    try:
        observed, passed = fn()
        outcome = "pass" if passed is True else "confirmed_error" if passed is False else "inconclusive"
    except Exception as exc:
        observed = f"exception={type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    OUT_ROWS.append({
        "card_id": card_id,
        "case_id": case_id,
        "expected": expected,
        "observed": observed,
        "outcome": outcome,
        "notes": meta,
    })
    return outcome


def save_checkpoints():
    for path, fields, rows in (
        (PROBE_OUT, PROBE_FIELDS, OUT_ROWS),
        (VERDICT_OUT, VERDICT_FIELDS, VERDICTS),
    ):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


# Card-specific probes are defined below. Each function returns an observed
# state string and a boolean comparison against the EN/ZH card-text contract.


def probe_at001():
    g = fresh_game()
    y = g.player2.summon("EX1_572")
    y.set_current_health(12)
    spell = play(g.player1, "AT_001", target=y)
    return f"target={y.zone.name}/damage={y.damage}/health={y.health};spell={spell.zone.name};opponent_field={ids(g.player2.field)}", y.zone == Zone.PLAY and y.damage == 8 and y.health == 4 and spell.zone == Zone.GRAVEYARD


def probe_at002():
    seen = set(); samples = []
    for seed in range(301, 317):
        g = fresh_game(seed=seed)
        secret = play(g.player1, "AT_002")
        dying = g.player1.summon("CS2_182")
        dying.set_current_health(1)
        g.end_turn()
        fireball = play(g.player2, FIREBALL, target=dying)
        spawned = [m for m in g.player1.field if m is not dying]
        ok = dying.zone == Zone.GRAVEYARD and secret not in g.player1.secrets and len(spawned) == 1 and spawned[0].cost == dying.cost and spawned[0].zone == Zone.PLAY
        if not ok:
            return f"seed={seed};dead={dying.zone.name};secret_active={secret in g.player1.secrets};fireball={fireball.zone.name};spawned={[(m.id,m.cost,m.zone.name) for m in spawned]}", False
        seen.add(spawned[0].id)
        samples.append((spawned[0].id, spawned[0].cost))
    return f"16 seeded deaths;same_cost=4;random_minion_ids={sorted(seen)};samples={samples}", len(seen) >= 2


def probe_at004():
    g = fresh_game()
    target = g.player2.summon("EX1_572")
    g.player1.summon(KOBOLD_GEOMANCER)
    g.player1.summon(KOBOLD_GEOMANCER)
    spell = play(g.player1, "AT_004", target=target)
    return f"spellpower={g.player1.spellpower};damage={target.damage};health={target.health};spell={spell.zone.name}", target.damage == 6 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD


def probe_at005():
    g = fresh_game()
    target = g.player2.summon("CS2_182")
    spell = play(g.player1, "AT_005", target=target)
    transformed = g.player2.field[0] if g.player2.field else None
    observed = f"original={target.id}/{target.zone.name};transformed={None if transformed is None else (transformed.id,transformed.atk,transformed.health,transformed.charge,transformed.zone.name)};spell={spell.zone.name}"
    return observed, transformed is not None and transformed.id == "AT_005t" and transformed.atk == 4 and transformed.health == 2 and transformed.charge and transformed.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD


def probe_at006():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    aspirant = play(g.player1, "AT_006")
    g.player1.hero.power.use()
    return f"inspire_count={aspirant.spellpower};player_spellpower={g.player1.spellpower}", aspirant.spellpower == 1 and g.player1.spellpower == 1


def probe_at007():
    seen = set(); samples = []
    for seed in range(321, 337):
        g = fresh_game(CardClass.MAGE, CardClass.HUNTER, seed)
        old1 = {id(card) for card in g.player1.hand}
        old2 = {id(card) for card in g.player2.hand}
        minion = play(g.player1, "AT_007")
        added1 = [card for card in g.player1.hand if id(card) not in old1]
        added2 = [card for card in g.player2.hand if id(card) not in old2]
        ok = len(added1) == 1 and len(added2) == 1 and all(card.type == CardType.SPELL and card.zone == Zone.HAND for card in added1 + added2) and minion.zone == Zone.PLAY
        if not ok:
            return f"seed={seed};p1_added={[(c.id,int(c.type),c.zone.name) for c in added1]};p2_added={[(c.id,int(c.type),c.zone.name) for c in added2]};slinger={minion.zone.name}", False
        seen.update(c.id for c in added1 + added2)
        samples.append((added1[0].id, added2[0].id))
    return f"16 seeded battlecries;random_spell_ids={sorted(seen)};p1_p2_samples={samples}", len(seen) >= 2


def probe_at008():
    g = fresh_game(CardClass.MAGE, CardClass.MAGE)
    drake = play(g.player1, "AT_008")
    g.player1.used_mana = 0
    power = g.player1.hero.power
    activations = 0
    failures = []
    for _ in range(3):
        g.player1.used_mana = 0
        if not power.is_usable():
            failures.append(f"not_usable_before_activation_{activations+1}")
            break
        try:
            power.use(g.player2.hero)
            activations += 1
        except Exception as exc:
            failures.append(f"{type(exc).__name__}:{exc}")
            break
    expected_ok = drake.zone == Zone.PLAY and activations == 3 and g.player2.hero.health == 27
    return f"drake={drake.zone.name};activation_count={activations};additional={power.additional_activations};enemy_health={g.player2.hero.health};failures={failures}", expected_ok


def probe_at009():
    g = fresh_game()
    rhonin = play(g.player1, "AT_009")
    rhonin.destroy()
    cards = [card for card in g.player1.hand if card.id == "EX1_277"]
    return f"rhonin={rhonin.zone.name};missiles={[card.id+':'+card.zone.name for card in cards]};hand={ids(g.player1.hand)}", rhonin.zone == Zone.GRAVEYARD and len(cards) == 3 and all(card.zone == Zone.HAND for card in cards)


def probe_at010():
    seen = set(); samples = []
    for seed in range(341, 357):
        g = fresh_game(seed=seed)
        beast = g.player1.summon("CS2_171")
        wrangler = play(g.player1, "AT_010")
        added = [m for m in g.player1.field if m is not beast and m is not wrangler]
        ok = wrangler.zone == Zone.PLAY and len(added) == 1 and added[0].race == 20 and added[0].zone == Zone.PLAY
        if not ok:
            return f"seed={seed};beast={beast.id};wrangler={wrangler.zone.name};added={[(m.id,m.race,m.atk,m.health,m.zone.name) for m in added]}", False
        seen.add(added[0].id)
        samples.append(added[0].id)
    return f"16 seeded Battlecries with a friendly Beast;random_beast_ids={sorted(seen)};samples={samples}", len(seen) >= 2


def probe_at010_no_beast():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    wrangler = play(g.player1, "AT_010")
    return f"friendly_beasts_before=0;wrangler={wrangler.zone.name};field={[(m.id,m.race,m.zone.name) for m in g.player1.field]}", wrangler.zone == Zone.PLAY and g.player1.field == [wrangler]


def probe_at011():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    champ = play(g.player1, "AT_011")
    g.player1.hero.set_current_health(20)
    heal = play(g.player1, "CS2_089", target=g.player1.hero)
    return f"hero_health={g.player1.hero.health};champion_attack={champ.atk};champion_zone={champ.zone.name};heal={heal.zone.name}", g.player1.hero.health == 26 and champ.atk == 5 and champ.zone == Zone.PLAY and heal.zone == Zone.GRAVEYARD


def probe_at012():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    g.player1.hero.set_current_health(20)
    spawn = play(g.player1, "AT_012")
    g.player1.hero.power.use(g.player1.hero)
    return f"spawn={spawn.zone.name};own_health={g.player1.hero.health};enemy_health={g.player2.hero.health}", spawn.zone == Zone.PLAY and g.player1.hero.health == 18 and g.player2.hero.health == 26


def probe_at013():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    friend = g.player1.summon("CS2_182")
    g.player1.hero.set_current_health(20)
    glory = play(g.player1, "AT_013", target=friend)
    g.end_turn()
    g.end_turn()
    friend.attack(g.player2.hero)
    return f"glory={glory.zone.name};friendly_attack={friend.atk};owner_hero={g.player1.hero.health};enemy_hero={g.player2.hero.health}", glory.zone == Zone.GRAVEYARD and g.player1.hero.health == 24 and g.player2.hero.health == 26


def probe_at014():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    fiend = play(g.player1, "AT_014")
    top = g.player1.give("CS2_182")
    top.shuffle_into_deck()
    draw = play(g.player1, "AT_053")
    return f"fiend={fiend.zone.name};drawn={top.id}/{top.zone.name}/cost={top.cost},base={top.data.cost};drawspell={draw.zone.name};hand={ids(g.player1.hand)}", fiend.zone == Zone.PLAY and top.zone == Zone.HAND and top.cost == top.data.cost - 1


def probe_at015():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    target = g.player2.summon("EX1_572")
    spell = play(g.player1, "AT_015", target=target)
    copies = [c for c in g.player1.hand if c.id == target.id]
    return f"target={target.id}/{target.zone.name};spell={spell.zone.name};copies={[(c.id,c.zone.name,c is target) for c in copies]}", target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD and len(copies) == 1 and copies[0] is not target and copies[0].zone == Zone.HAND


def probe_at016():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    y = g.player1.summon("CS2_182")
    c = g.player2.summon("CS2_235")
    spell = play(g.player1, "AT_016")
    return f"friendly={y.atk}/{y.health};enemy={c.atk}/{c.health};spell={spell.zone.name}", (y.atk, y.health) == (5, 4) and (c.atk, c.health) == (3, 1) and spell.zone == Zone.GRAVEYARD


def probe_at017():
    g = fresh_game()
    dragon = g.player1.give("EX1_572")
    guardian = play(g.player1, "AT_017")
    return f"dragon_in_hand={dragon in g.player1.hand};guardian={guardian.atk}/{guardian.health}/taunt={guardian.taunt}/zone={guardian.zone.name}", dragon in g.player1.hand and guardian.atk == 3 and guardian.health == 6 and guardian.taunt and guardian.zone == Zone.PLAY


def probe_at017_no_dragon():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    non_dragon = g.player1.give(WISP)
    guardian = play(g.player1, "AT_017")
    return f"held_non_dragon={non_dragon.id};guardian={guardian.atk}/{guardian.health}/taunt={guardian.taunt}/zone={guardian.zone.name}", guardian.atk == guardian.data.atk and guardian.health == guardian.data.health and not guardian.taunt and guardian.zone == Zone.PLAY


def probe_at018():
    seen = set(); samples = []
    for seed in range(361, 377):
        g = fresh_game(CardClass.PRIEST, CardClass.PRIEST, seed)
        paletress = play(g.player1, "AT_018")
        g.player1.used_mana = 0
        paletress_count = len(g.player1.field)
        g.player1.hero.power.use(g.player1.hero)
        added = [m for m in g.player1.field if m is not paletress]
        ok = paletress.zone == Zone.PLAY and len(g.player1.field) == paletress_count + 1 and len(added) == 1 and added[0].data.rarity.name == "LEGENDARY" and added[0].zone == Zone.PLAY
        if not ok:
            return f"seed={seed};paletress={paletress.zone.name};added={[(m.id,m.data.rarity.name,m.zone.name) for m in added]};hand={ids(g.player1.hand)}", False
        seen.add(added[0].id)
        samples.append(added[0].id)
    return f"16 seeded Inspires;legendary_ids={sorted(seen)};samples={samples}", len(seen) >= 2


def probe_at019():
    g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
    steed = play(g.player1, "AT_019")
    steed.destroy()
    dead_zone = steed.zone
    g.end_turn()
    spawned = [m for m in g.player1.field if m.id == "AT_019"]
    return f"dead_original={dead_zone.name};end_turn_field={[(m.id,m.zone.name) for m in g.player1.field]};replacement_count={len(spawned)}", dead_zone == Zone.GRAVEYARD and len(spawned) == 1 and spawned[0] is not steed and spawned[0].zone == Zone.PLAY


def probe_at021():
    g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
    knight = play(g.player1, "AT_021")
    discarded = g.player1.give(WISP)
    soul = g.player1.give("EX1_308")
    soul.play(target=g.player2.hero)
    return f"discarded={discarded.zone.name};soulfire={soul.zone.name};knight={knight.atk}/{knight.health}/zone={knight.zone.name};hand={ids(g.player1.hand)}", discarded.zone == Zone.REMOVEDFROMGAME and knight.atk == 4 and knight.health == 3 and knight.zone == Zone.PLAY


def probe_at022():
    seen = set()
    evidence = []
    for seed in range(20, 36):
        g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK, seed)
        ysera1 = g.player2.summon("EX1_572")
        ysera2 = g.player2.summon("EX1_572")
        spell = play(g.player1, "AT_022")
        changed = []
        if g.player2.hero.health < 30:
            changed.append("enemy_hero")
        for name, m in (("enemy_ysera_left", ysera1), ("enemy_ysera_right", ysera2)):
            if m.damage or m.zone == Zone.GRAVEYARD:
                changed.append(name)
        seen.update(changed)
        evidence.append((changed, g.player2.hero.health, [(m.id,m.damage,m.health,m.zone.name) for m in (ysera1,ysera2)]))
        if spell.zone != Zone.GRAVEYARD or len(changed) != 1 or any(m.zone != Zone.PLAY for m in (ysera1,ysera2)):
            return f"seed={seed};spell={spell.zone.name};evidence={evidence}", False
        if changed[0] == "enemy_hero":
            exact = g.player2.hero.health == 26 and ysera1.damage == ysera2.damage == 0
        else:
            selected = ysera1 if changed[0] == "enemy_ysera_left" else ysera2
            other = ysera2 if selected is ysera1 else ysera1
            exact = selected.damage == 4 and other.damage == 0 and g.player2.hero.health == 30
        if not exact:
            return f"seed={seed};wrong 4-damage amount or secondary recipient;hero={g.player2.hero.health};evidence={evidence[-1]}", False
    return f"16 seeded casts;exactly 4 damage to one enemy character;random_recipients={sorted(seen)};samples={evidence[:6]}", len(seen) >= 2


def probe_at022_discard():
    seen = set(); samples = []
    for seed in range(421, 437):
        g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK, seed)
        hero = g.player2.hero
        ysera1 = g.player2.summon("EX1_572")
        ysera2 = g.player2.summon("EX1_572")
        fist = g.player1.give("AT_022")
        soul = g.player1.give("EX1_308")
        for card in list(g.player1.hand):
            if card not in (fist, soul):
                card.discard()
        soul.play(target=hero)
        changed = []
        if hero.health < 26: changed.append("enemy_hero")
        for label, minion in (("enemy_ysera_left", ysera1), ("enemy_ysera_right", ysera2)):
            if minion.damage: changed.append(label)
        if fist.zone != Zone.REMOVEDFROMGAME or soul.zone != Zone.GRAVEYARD or len(changed) != 1:
            return f"seed={seed};fist={fist.zone.name};soulfire={soul.zone.name};changed={changed};enemy={[(m.id,m.damage,m.zone.name) for m in (ysera1,ysera2)]};hero={hero.health}", False
        if changed[0] == "enemy_hero":
            exact = hero.health == 22 and ysera1.damage == ysera2.damage == 0
        else:
            selected = ysera1 if changed[0] == "enemy_ysera_left" else ysera2
            other = ysera2 if selected is ysera1 else ysera1
            exact = hero.health == 26 and selected.damage == 4 and other.damage == 0
        if not exact:
            return f"seed={seed};incorrect discard-trigger 4 damage;changed={changed};enemy={[(m.id,m.damage,m.zone.name) for m in (ysera1,ysera2)]};hero={hero.health}", False
        seen.update(changed)
        samples.append((changed[0], hero.health, ysera1.damage, ysera2.damage, fist.zone.name))
    return f"16 end-to-end Soulfire discards;Fist moved to REMOVEDFROMGAME;exact discard-trigger recipient={sorted(seen)};samples={samples}", len(seen) >= 2


def probe_at023():
    own_seen, enemy_seen, samples = set(), set(), []
    for seed in range(50, 66):
        g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK, seed)
        own_a = g.player1.summon("CS2_231")
        own_b = g.player1.summon("CS2_182")
        enemy_a = g.player2.summon("CS2_231")
        enemy_b = g.player2.summon("CS2_182")
        crusher = play(g.player1, "AT_023")
        g.player1.hero.power.use()
        own_dead = [m for m in (own_a, own_b, crusher) if m.zone == Zone.GRAVEYARD]
        enemy_dead = [m for m in (enemy_a, enemy_b) if m.zone == Zone.GRAVEYARD]
        if len(own_dead) != 1 or len(enemy_dead) != 1:
            return f"seed={seed};own_dead={[(m.id,m.zone.name) for m in own_dead]};enemy_dead={[(m.id,m.zone.name) for m in enemy_dead]}", False
        own_seen.add("crusher" if own_dead[0] is crusher else "wisp" if own_dead[0] is own_a else "yeti")
        enemy_seen.add("wisp" if enemy_dead[0] is enemy_a else "yeti")
        samples.append((own_dead[0].id, enemy_dead[0].id))
    return f"16 seeded inspires;friendly_candidates_destroyed={sorted(own_seen)};enemy_candidates_destroyed={sorted(enemy_seen)};samples={samples[:6]}", len(own_seen) >= 2 and len(enemy_seen) == 2


def probe_at024():
    g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
    demon = g.player1.summon(IMP)
    old_stats = (demon.atk, demon.health)
    g.player2.max_mana = 9
    spell = play(g.player1, "AT_024", target=demon)
    return f"demon={demon.atk}/{demon.health},before={old_stats};opponent_max_mana={g.player2.max_mana};spell={spell.zone.name}", demon.atk == old_stats[0] + 3 and demon.health == old_stats[1] + 3 and g.player2.max_mana == 10 and spell.zone == Zone.GRAVEYARD


def probe_at025():
    g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
    enemies = [g.player2.summon("CS2_231"), g.player2.summon("EX1_012"), g.player2.summon("CS2_182")]
    held = [g.player1.give(WISP), g.player1.give("EX1_012"), g.player1.give("CS2_182")]
    spell = play(g.player1, "AT_025")
    dead = [m for m in enemies if m.zone == Zone.GRAVEYARD]
    discarded = [c for c in held if c.zone not in (Zone.HAND, Zone.DECK, Zone.PLAY)]
    ok = len(dead) == 2 and len({id(m) for m in dead}) == 2 and len(discarded) == 2 and spell.zone == Zone.GRAVEYARD
    return f"enemy_dead={[(m.id,m.zone.name) for m in dead]};enemy_field={ids(g.player2.field)};discarded={[(c.id,c.zone.name) for c in discarded]};hand={ids(g.player1.hand)};spell={spell.zone.name}", ok


def probe_at026():
    g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
    wrath = play(g.player1, "AT_026")
    spell = play(g.player1, FIREBALL, target=wrath)
    hero_damage = 30 - g.player1.hero.health
    return f"wrath_damage_after_death={wrath.damage}/{wrath.zone.name};owner_damage={hero_damage};owner_health={g.player1.hero.health};spell={spell.zone.name}", wrath.zone == Zone.GRAVEYARD and hero_damage == 6 and spell.zone == Zone.GRAVEYARD


def probe_at027():
    g = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
    fizz = play(g.player1, "AT_027")
    fireball = g.player1.give(FIREBALL)
    fireball.shuffle_into_deck()
    g.player1.hero.power.use()
    return f"fizz={fizz.zone.name};draw={fireball.id}/{fireball.zone.name}/cost={fireball.cost}/base={fireball.data.cost};hand={ids(g.player1.hand)}", fizz.zone == Zone.PLAY and fireball.zone == Zone.HAND and fireball.cost == 0


def probe_at028():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    plain = play(g.player1, "AT_028")
    plain_atk = plain.atk
    # Play a second copy after a card has already been played this turn.
    g.player1.give(THE_COIN).play()
    combo = play(g.player1, "AT_028")
    return f"without_combo={plain_atk};with_combo={combo.atk};zones={plain.zone.name}/{combo.zone.name}", plain_atk == plain.data.atk and combo.atk == combo.data.atk + 3 and plain.zone == combo.zone == Zone.PLAY


def probe_at029():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    buccaneer = play(g.player1, "AT_029")
    weapon = g.player1.give(LIGHTS_JUSTICE)
    weapon.play()
    return f"buccaneer={buccaneer.zone.name};weapon={weapon.id}/{weapon.atk}/{weapon.durability}/{weapon.zone.name};equipped={g.player1.weapon is weapon}", buccaneer.zone == Zone.PLAY and weapon.atk == weapon.data.atk + 1 and g.player1.weapon is weapon and weapon.zone == Zone.PLAY


def probe_at030():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    g.player2.summon("CS2_182")
    g.player1.give(THE_COIN).play()
    target = g.player2.field[0]
    valiant = play(g.player1, "AT_030", target=target)
    return f"target_damage={target.damage};target_health={target.health};valiant={valiant.zone.name};spell_combo_targets={ids(valiant.targets)}", target.damage == 1 and target.zone == Zone.PLAY and valiant.zone == Zone.PLAY


def probe_at030_no_combo():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    target = g.player2.summon("EX1_572")
    valiant = play(g.player1, "AT_030")
    return f"prior_card_played=False;target={target.damage}/{target.health}/{target.zone.name};valiant={valiant.zone.name}", target.damage == 0 and target.zone == Zone.PLAY and valiant.zone == Zone.PLAY


def probe_at031():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    cutpurse = play(g.player1, "AT_031")
    g.end_turn()
    g.end_turn()
    cutpurse.attack(g.player2.hero)
    coins = [c for c in g.player1.hand if c.id == THE_COIN]
    return f"cutpurse={cutpurse.zone.name};enemy_health={g.player2.hero.health};coin_cards={[(c.id,c.zone.name) for c in coins]};hand={ids(g.player1.hand)}", g.player2.hero.health == 28 and len(coins) == 1 and coins[0].zone == Zone.HAND


def probe_at032():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    pirate = g.player1.summon("CS2_146")
    dealer = play(g.player1, "AT_032")
    return f"pirate={pirate.id}/{pirate.race};dealer={dealer.atk}/{dealer.health}/zone={dealer.zone.name}", pirate.race == 23 and dealer.atk == dealer.data.atk + 1 and dealer.health == dealer.data.health + 1 and dealer.zone == Zone.PLAY


def probe_at032_no_pirate():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    dealer = play(g.player1, "AT_032")
    return f"friendly_pirates_before=0;dealer={dealer.atk}/{dealer.health}/base={dealer.data.atk}/{dealer.data.health}/zone={dealer.zone.name}", (dealer.atk,dealer.health) == (dealer.data.atk,dealer.data.health) and dealer.zone == Zone.PLAY


def probe_at033():
    g = fresh_game(CardClass.ROGUE, CardClass.WARRIOR)
    old = {id(c) for c in g.player1.hand}
    spell = play(g.player1, "AT_033")
    added = [c for c in g.player1.hand if id(c) not in old]
    expected_class = g.player2.hero.card_class
    ok = spell.zone == Zone.GRAVEYARD and len(added) == 2 and all(expected_class in c.classes and c.data.collectible and c.zone == Zone.HAND for c in added)
    return f"burgle={spell.zone.name};added={[(c.id,[int(x) for x in c.classes],c.data.collectible,c.zone.name) for c in added]};hand={ids(g.player1.hand)}", ok


def probe_at034():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    blade = play(g.player1, "AT_034")
    base = blade.atk
    g.player1.hero.power.use()
    first = (blade.atk, blade.durability, g.player1.weapon is blade)
    g.end_turn(); g.end_turn()
    g.player1.hero.power.use()
    second = (blade.atk, blade.durability, g.player1.weapon is blade)
    return f"base={base};after_first={first};after_second={second};hero_power_uses={g.player1.times_hero_power_used_this_game}", first == (base + 1, blade.durability, True) and second[0] == base + 2 and second[2]


def probe_at035():
    samples=[]; positive=False
    for seed in range(200,216):
        g = fresh_game(CardClass.ROGUE, CardClass.ROGUE, seed)
        spell = play(g.player1, "AT_035")
        ordinary = g.player2.give(WISP); ordinary.shuffle_into_deck()
        traps = [c for c in g.player2.deck if c.id == "AT_035t"]
        g.end_turn()
        nerubians = [m for m in g.player1.field if m.id == "AT_036t"]
        remain = [c for c in g.player2.deck if c.id == "AT_035t"]
        triggers = len(traps) - len(remain)
        ok = spell.zone == Zone.GRAVEYARD and len(traps) == 3 and len(nerubians) == triggers and all((m.atk,m.health,m.zone)==(4,4,Zone.PLAY) for m in nerubians) and ordinary.zone in (Zone.HAND, Zone.DECK)
        samples.append((triggers,len(remain),ordinary.zone.name,len(nerubians)))
        positive = positive or triggers > 0
        if not ok:
            return f"seed={seed};initial=3 traps + 1 ordinary;sample={samples[-1]};field={[(m.id,m.atk,m.health,m.zone.name) for m in nerubians]};deck={ids(g.player2.deck)}",False
    return f"16 seeded deck orders;drawn_traps/remaining/ordinary_zone/nerubians={samples};each cast-when-drawn trap leaves deck and summons exactly one body",positive


def probe_at036():
    g = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
    anub = play(g.player1, "AT_036")
    anub.destroy()
    token = [m for m in g.player1.field if m.id == "AT_036t"]
    copies = [c for c in g.player1.hand if c.id == "AT_036"]
    return f"anub={anub.zone.name};token={[(m.atk,m.health,m.zone.name) for m in token]};returned={[(c.zone.name,c is anub) for c in copies]}", anub.zone == Zone.HAND and len(copies) == 1 and copies[0] is anub and len(token) == 1 and token[0].atk == token[0].health == 4 and token[0].zone == Zone.PLAY


def probe_at037a():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    target = g.player2.summon("CS2_182")
    spell = play(g.player1, "AT_037", target=target, choose="AT_037a")
    return f"target={target.damage}/{target.health}/{target.zone.name};spell={spell.zone.name};p1_field={ids(g.player1.field)}", target.damage == 2 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD and not g.player1.field


def probe_at037b():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    spell = play(g.player1, "AT_037", choose="AT_037b")
    saplings = [m for m in g.player1.field if m.id == "AT_037t"]
    return f"spell={spell.zone.name};saplings={[(m.atk,m.health,m.zone.name) for m in saplings]};field={ids(g.player1.field)}", spell.zone == Zone.GRAVEYARD and len(saplings) == 2 and all((m.atk,m.health,m.zone) == (1,1,Zone.PLAY) for m in saplings)


def probe_at038():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    g.player1.max_mana = 5
    before = (g.player1.max_mana, g.player1.mana)
    aspirant = play(g.player1, "AT_038")
    after_play = (g.player1.max_mana, g.player1.mana)
    aspirant.destroy()
    after_death = (g.player1.max_mana, g.player1.mana, aspirant.zone.name)
    return f"before={before};after_play={after_play};after_death={after_death}", after_play == (6, 3) and after_death == (5,2,"GRAVEYARD")


def probe_at039():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    combatant = play(g.player1, "AT_039")
    g.player1.hero.power.use()
    after_power = (g.player1.hero.atk, g.player1.hero.armor, combatant.zone.name)
    g.end_turn()
    after_turn = g.player1.hero.atk
    return f"after_inspire={after_power};after_turn_attack={after_turn}", after_power[0] == 3 and combatant.zone == Zone.PLAY and after_turn == 0


def probe_at040():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    beast = g.player1.summon("CS2_171")
    base = (beast.atk, beast.health)
    walker = play(g.player1, "AT_040", target=beast)
    return f"target_race={beast.race};beast={beast.atk}/{beast.health},base={base},zone={beast.zone.name};walker={walker.zone.name}", beast.race == 20 and beast.atk == base[0] and beast.health == base[1] + 3 and beast.zone == Zone.PLAY and walker.zone == Zone.PLAY


def probe_at041():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    knight = g.player1.give("AT_041")
    start = knight.cost
    g.player1.summon("CS2_171")
    after_beast = knight.cost
    g.player1.summon("CS2_231")
    after_nonbeast = knight.cost
    return f"costs={start}->{after_beast}->{after_nonbeast};knight_zone={knight.zone.name}", after_beast == start - 1 and after_nonbeast == after_beast and knight.zone == Zone.HAND


def probe_at042():
    results = []
    for choice, expected in (("AT_042a", (2,1,True,False)), ("AT_042b", (3,2,False,True))):
        g = fresh_game(CardClass.DRUID, CardClass.DRUID, 180 + len(results))
        original = play(g.player1, "AT_042", choose=choice)
        form = g.player1.field[0] if g.player1.field else None
        current = None if form is None else (form.atk, form.health, form.charge, form.stealthed)
        results.append((choice, original.zone.name, None if form is None else (form.id,current,form.zone.name)))
        if form is None or current != expected or form.zone != Zone.PLAY:
            return f"choices={results}", False
    return f"choices={results}", len(results) == 2


def probe_at043():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    discarded = [g.player1.give(WISP), g.player1.give("CS2_182")]
    spell = play(g.player1, "AT_043")
    after_play = (g.player1.max_mana, g.player1.mana, [(c.id,c.zone.name) for c in discarded])
    g2 = fresh_game(CardClass.DRUID, CardClass.DRUID)
    g2.player1.used_mana = 0
    g2.player1.max_mana = 10
    hand_card = g2.player1.give("CS2_182")
    full = play(g2.player1, "AT_043")
    innervates = [c for c in g2.player1.hand if c.id == "CS2_013t"]
    ok = spell.zone == Zone.GRAVEYARD and g.player1.max_mana == 10 and all(c.zone == Zone.REMOVEDFROMGAME for c in discarded) and full.zone == Zone.GRAVEYARD and len(innervates) == 1 and hand_card.zone == Zone.REMOVEDFROMGAME
    return f"under_cap=(max={after_play[0]},mana={after_play[1]},hand={after_play[2]});at_cap=(max={g2.player1.max_mana},hand={ids(g2.player1.hand)},innervate={len(innervates)})", ok


def probe_at044():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    target = g.player2.summon("CS2_182")
    spell = play(g.player1, "AT_044", target=target)
    added = [c for c in g.player2.hand if c.type == CardType.MINION]
    return f"target={target.zone.name};spell={spell.zone.name};opponent_hand={[(c.id,int(c.type),c.zone.name) for c in added]}", target.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD and len(added) == 1 and added[0].zone == Zone.HAND


def probe_at045():
    g = fresh_game(CardClass.DRUID, CardClass.DRUID)
    aviana = play(g.player1, "AT_045")
    wisp = g.player1.give(WISP)
    deathwing = g.player1.give("NEW1_030")
    other_spell = g.player1.give(MOONFIRE)
    costs_with = (wisp.cost, deathwing.cost, other_spell.cost)
    aviana.destroy()
    costs_after = (wisp.cost, deathwing.cost, other_spell.cost)
    return f"aviana={aviana.zone.name};costs_with_aura={costs_with};costs_after_leave={costs_after};hand={[c.id for c in g.player1.hand]}", costs_with == (1,1,0) and costs_after == (0,10,0) and aviana.zone == Zone.GRAVEYARD


def probe_at046():
    ids_seen = set()
    cases = []
    for seed in range(90, 102):
        g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN, seed)
        before = set(id(m) for m in g.player1.field)
        totemcarver = play(g.player1, "AT_046")
        added = [m for m in g.player1.field if id(m) not in before and m is not totemcarver]
        if len(added) != 1 or added[0].race != 21 or added[0].zone != Zone.PLAY:
            return f"seed={seed};added={[(m.id,m.race,m.zone.name) for m in added]};field={ids(g.player1.field)}", False
        ids_seen.add(added[0].id)
        cases.append(added[0].id)
    return f"12 seeded summons;basic_totem_ids={sorted(ids_seen)};samples={cases}", len(ids_seen) >= 2


def probe_at047():
    g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
    totems = [g.player1.summon("CS2_050"), g.player1.summon("CS2_051"), g.player1.summon("CS2_052")]
    before = [(m.atk,m.health) for m in totems]
    carver = play(g.player1, "AT_047")
    expected = (carver.data.atk + 3, carver.data.health + 3)
    return f"friendly_totems={[(m.id,m.race) for m in totems]};carver={carver.atk}/{carver.health},expected={expected};before={before}", all(m.race == 21 for m in totems) and (carver.atk,carver.health) == expected and carver.zone == Zone.PLAY


def probe_at048():
    outcomes = set(); samples = []
    for seed in range(441, 465):
        g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN, seed)
        own_cards = [g.player1.give(card_id) for card_id in ("NEW1_030", WISP)]
        enemy_cards = [g.player2.give(card_id) for card_id in ("EX1_572", "CS2_182")]
        for card in own_cards + enemy_cards: card.shuffle_into_deck()
        g.player1.hero.set_current_health(10)
        spell = play(g.player1, "AT_048", target=g.player1.hero)
        healed = g.player1.hero.health - 10
        outcomes.add(healed)
        samples.append((seed, healed, [(c.id,c.data.cost,c.zone.name) for c in own_cards], [(c.id,c.data.cost,c.zone.name) for c in enemy_cards]))
        if healed not in (7,14) or spell.zone != Zone.GRAVEYARD or any(c.zone != Zone.DECK for c in own_cards + enemy_cards):
            return f"24 seeded mixed-cost Jousts;outcomes={samples}", False
    return f"24 seeded Jousts over own costs 10/0 vs opponent costs 9/4;heal_amounts={sorted(outcomes)};samples={samples[:8]}", outcomes == {7,14}


def probe_at049():
    g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
    totem = g.player1.summon("CS2_050")
    valiant = play(g.player1, "AT_049")
    base = totem.atk
    g.player1.hero.power.use()
    observed = f"totem={totem.id}/{totem.atk},before={base};all_totems={[(m.id,m.atk,m.zone.name) for m in g.player1.field if m.race == 21]};valiant={valiant.zone.name}"
    return observed, totem.atk == base + 2 and valiant.zone == Zone.PLAY


def probe_at050():
    g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
    weapon = play(g.player1, "AT_050")
    weapon.destroy()
    power = g.player1.hero.power
    target = g.player2.hero
    before = target.health
    power.use(target)
    return f"weapon={weapon.zone.name};hero_power={power.id}/cost={power.cost};target={target.health},before={before};equipped={g.player1.weapon}", weapon.zone == Zone.GRAVEYARD and power.id == "AT_050t" and target.health == before - 2


def probe_at051():
    results = []; seen = set()
    for seed in range(551, 567):
        g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN, seed)
        own = g.player1.summon("EX1_572")
        enemy = g.player2.summon("EX1_572")
        spell = play(g.player1, "AT_051")
        damages = (own.damage, enemy.damage)
        overloaded = g.player1.overloaded
        if spell.zone != Zone.GRAVEYARD or own.zone != Zone.PLAY or enemy.zone != Zone.PLAY or any(d not in (4,5) for d in damages) or overloaded != 5:
            return f"seed={seed};spell={spell.zone.name};own={own.zone.name}/damage={own.damage}/health={own.health};enemy={enemy.zone.name}/damage={enemy.damage}/health={enemy.health};overloaded={overloaded}", False
        seen.update(damages)
        g.end_turn(); g.end_turn()
        next_turn_mana = g.player1.mana
        results.append((seed, damages, (own.health,enemy.health), next_turn_mana))
        if next_turn_mana != 5:
            return f"seed={seed};wrong next-turn mana;results={results[-1]}", False
    return f"16 seeded casts against 12-health minions;damage_rolls={sorted(seen)};all bodies survived;Overload=5 and next-turn mana=5;sample={results[:8]}", seen == {4,5}


def probe_at053():
    g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
    first = g.player1.give(WISP); first.shuffle_into_deck()
    second = g.player1.give("CS2_182"); second.shuffle_into_deck()
    spell = play(g.player1, "AT_053")
    drawn = (first.zone, second.zone)
    overloaded = g.player1.overloaded
    g.end_turn(); g.end_turn()
    return f"spell={spell.zone.name};drawn={first.zone.name}/{second.zone.name};overloaded={overloaded};next_turn_mana={g.player1.mana}", spell.zone == Zone.GRAVEYARD and drawn == (Zone.HAND,Zone.HAND) and overloaded == 2 and g.player1.mana == 8


def probe_at054():
    g = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
    hand_minion = g.player1.give(WISP)
    deck_minion = g.player1.give("CS2_182"); deck_minion.shuffle_into_deck()
    board_minion = g.player1.summon("CS2_182")
    before_board = (board_minion.atk, board_minion.health)
    mistcaller = play(g.player1, "AT_054")
    return f"hand={hand_minion.atk}/{hand_minion.health}/{hand_minion.zone.name};deck={deck_minion.atk}/{deck_minion.health}/{deck_minion.zone.name};board={board_minion.atk}/{board_minion.health},before={before_board};mistcaller={mistcaller.atk}/{mistcaller.health}", (hand_minion.atk,hand_minion.health)==(2,2) and (deck_minion.atk,deck_minion.health)==(5,6) and (board_minion.atk,board_minion.health)==before_board and mistcaller.zone == Zone.PLAY


def probe_at055():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    g.player2.hero.set_current_health(20)
    spell = play(g.player1, "AT_055", target=g.player2.hero)
    return f"enemy_hero={g.player2.hero.health};spell={spell.zone.name};p1_hero={g.player1.hero.health}", g.player2.hero.health == 25 and spell.zone == Zone.GRAVEYARD and g.player1.hero.health == 30


def probe_at056():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    left = g.player2.summon("CS2_182")
    target = g.player2.summon("CS2_182")
    right = g.player2.summon("CS2_182")
    far = g.player2.summon("CS2_182")
    spell = play(g.player1, "AT_056", target=target)
    return f"damage_by_position={[(m.damage,m.zone.name) for m in (left,target,right,far)]};spell={spell.zone.name};board={ids(g.player2.field)}", (left.damage,target.damage,right.damage,far.damage)==(2,2,2,0) and spell.zone == Zone.GRAVEYARD


def probe_at057():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    beast = g.player1.summon("CS2_171")
    stable = play(g.player1, "AT_057", target=beast)
    play(g.player1, FIREBALL, target=beast)
    immune_during = beast.immune
    g.end_turn()
    g.end_turn()
    return f"stablemaster={stable.zone.name};beast={beast.zone.name}/damage={beast.damage}/health={beast.health}/immune_during={immune_during}/immune_after={beast.immune}", stable.zone == Zone.PLAY and immune_during and beast.damage == 0 and beast.immune is False


def probe_at058():
    drawn_ids = set(); samples = []
    for seed in range(471, 487):
        g = fresh_game(CardClass.HUNTER, CardClass.HUNTER, seed)
        own_high = [g.player1.give(card_id) for card_id in ("NEW1_030", "EX1_572")]
        enemy_low = [g.player2.give(card_id) for card_id in (WISP, "EX1_508")]
        for card in own_high + enemy_low: card.shuffle_into_deck()
        elekk = play(g.player1, "AT_058")
        drawn = [c for c in own_high if c.zone == Zone.HAND]
        samples.append((seed, [c.id for c in drawn], [(c.id,c.data.cost,c.zone.name) for c in enemy_low]))
        if elekk.zone != Zone.PLAY or len(drawn) != 1 or drawn[0].data.cost <= max(c.data.cost for c in enemy_low) or any(c.zone != Zone.DECK for c in enemy_low) or any(c is not drawn[0] and c.zone != Zone.DECK for c in own_high):
            return f"16 seeded win Jousts over two distinct candidate minions;draws={samples}", False
        drawn_ids.add(drawn[0].id)
    loss_samples = []
    for seed in range(491, 507):
        g = fresh_game(CardClass.HUNTER, CardClass.HUNTER, seed)
        own_low = [g.player1.give(card_id) for card_id in (WISP, "EX1_508")]
        enemy_high = [g.player2.give(card_id) for card_id in ("NEW1_030", "EX1_572")]
        for card in own_low + enemy_high: card.shuffle_into_deck()
        elekk = play(g.player1, "AT_058")
        loss_samples.append((seed, [c.id for c in own_low if c.zone == Zone.HAND], [(c.id,c.data.cost,c.zone.name) for c in enemy_high]))
        if elekk.zone != Zone.PLAY or any(c.zone != Zone.DECK for c in own_low + enemy_high):
            return f"16 seeded loss Jousts over two distinct candidate minions;draws={loss_samples}", False
    return f"16 win + 16 loss Jousts;winning_draw_ids={sorted(drawn_ids)};loss_cases_no_draw;win_samples={samples[:6]};loss_samples={loss_samples[:6]}", len(drawn_ids) >= 2 and len(loss_samples) == 16


def probe_at059():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    archer = play(g.player1, "AT_059")
    g.player1.used_mana = 0
    g.player1.hero.power.use()
    empty_hand_enemy = g.player2.hero.health
    g.end_turn(); g.end_turn()
    g.player1.give(WISP)
    g.player1.hero.power.use()
    held_enemy = g.player2.hero.health
    return f"archer={archer.zone.name};enemy_after_empty_hand={empty_hand_enemy};enemy_after_held_card={held_enemy};hand={ids(g.player1.hand)}", empty_hand_enemy == 26 and held_enemy == 24 and archer.zone == Zone.PLAY


def probe_at060():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    secret = play(g.player1, "AT_060")
    attacker = g.player2.summon("CS2_196")
    g.end_turn()
    attacker.attack(g.player1.hero)
    bears = [m for m in g.player1.field if m.id == "CS2_125"]
    return f"secret_active={secret in g.player1.secrets};attacker={attacker.zone.name}/{attacker.atk};p1_hero={g.player1.hero.health};bears={[(m.atk,m.health,m.taunt,m.zone.name) for m in bears]}", secret not in g.player1.secrets and g.player1.hero.health == 30-attacker.atk and len(bears)==1 and (bears[0].atk,bears[0].health,bears[0].taunt,bears[0].zone)==(3,3,True,Zone.PLAY)


def probe_at061():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    lock = play(g.player1, "AT_061")
    old = {id(c) for c in g.player1.hand}
    for _ in range(2):
        play(g.player1, MOONFIRE, target=g.player2.hero)
    added = [c for c in g.player1.hand if id(c) not in old]
    same_turn_ok = len(added)==2 and all(CardClass.HUNTER in c.classes and c.data.collectible and c.zone == Zone.HAND for c in added)
    g.end_turn(); g.end_turn()
    third = play(g.player1, MOONFIRE, target=g.player2.hero)
    added_after_expiry = [c for c in g.player1.hand if id(c) not in old and c not in added]
    ok = lock.zone == Zone.GRAVEYARD and same_turn_ok and third.zone == Zone.GRAVEYARD and not added_after_expiry
    return f"lock={lock.zone.name};same_turn_hunter_cards={[(c.id,[int(x) for x in c.classes],c.zone.name) for c in added]};next_turn_added={ids(added_after_expiry)};enemy_health={g.player2.hero.health}", ok


def probe_at062():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    spell = play(g.player1, "AT_062")
    spiders = [m for m in g.player1.field if m.id == "FP1_011"]
    return f"spell={spell.zone.name};webspinners={[(m.atk,m.health,m.race,m.zone.name) for m in spiders]};field={ids(g.player1.field)}", spell.zone == Zone.GRAVEYARD and len(spiders)==3 and all((m.atk,m.health,m.zone)==(1,1,Zone.PLAY) for m in spiders)


def probe_at063():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    acid = play(g.player1, "AT_063")
    own = g.player1.summon("EX1_572")
    enemy = g.player2.summon("EX1_572")
    self_hit = play(g.player1, MOONFIRE, target=acid)
    acid_after_self_hit = (acid.zone.name,acid.damage,acid.health)
    own_hit = play(g.player1, MOONFIRE, target=own)
    enemy_hit = play(g.player1, MOONFIRE, target=enemy)
    return f"acid_after_own_damage={acid_after_self_hit};acid_final={acid.zone.name}/{acid.damage};friendly_12_health_minion={own.zone.name}/remaining_damage={own.damage};enemy_12_health_minion={enemy.zone.name}/remaining_damage={enemy.damage};spells={self_hit.zone.name}/{own_hit.zone.name}/{enemy_hit.zone.name}", acid_after_self_hit == ("PLAY",1,1) and acid.zone == Zone.PLAY and own.zone == enemy.zone == Zone.GRAVEYARD and own.max_health == enemy.max_health == 12 and all(s.zone == Zone.GRAVEYARD for s in (self_hit,own_hit,enemy_hit))


def probe_at063t():
    g = fresh_game(CardClass.HUNTER, CardClass.HUNTER)
    own = g.player1.summon("CS2_231")
    enemy = g.player2.summon("CS2_231")
    dreadscale = play(g.player1, "AT_063t")
    g.end_turn()
    return f"dreadscale={dreadscale.zone.name}/damage={dreadscale.damage};own={own.zone.name}/damage={own.damage};enemy={enemy.zone.name}/damage={enemy.damage}", dreadscale.zone == Zone.PLAY and own.zone == enemy.zone == Zone.GRAVEYARD


def probe_at064():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    target = g.player2.summon("EX1_572")
    target.set_current_health(12)
    spell = play(g.player1, "AT_064", target=target)
    return f"spell={spell.zone.name};target={target.zone.name}/damage={target.damage}/health={target.health};armor={g.player1.hero.armor};health={g.player1.hero.health}", spell.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY and target.damage == 3 and target.health == 9 and g.player1.hero.armor == 3 and g.player1.hero.health == 30


def probe_at065():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    taunt = g.player1.summon("CS1_042")
    weapon = play(g.player1, "AT_065")
    return f"taunt={taunt.taunt};weapon={weapon.atk}/{weapon.durability};equipped={g.player1.weapon is weapon}", taunt.taunt and weapon.durability == weapon.data.durability + 1 and g.player1.weapon is weapon


def probe_at065_no_taunt():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    weapon = play(g.player1, "AT_065")
    return f"friendly_taunts_before=0;weapon={weapon.atk}/{weapon.durability}/base_durability={weapon.data.durability};equipped={g.player1.weapon is weapon}", weapon.durability == weapon.data.durability and g.player1.weapon is weapon and weapon.zone == Zone.PLAY


def probe_at066():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    weapon = g.player1.give(LIGHTS_JUSTICE); weapon.play()
    aspirant = play(g.player1, "AT_066")
    before = weapon.atk
    g.player1.hero.power.use()
    return f"aspirant={aspirant.zone.name};weapon_attack={weapon.atk},before={before};equipped={g.player1.weapon is weapon}", weapon.atk == before + 1 and g.player1.weapon is weapon and aspirant.zone == Zone.PLAY


def probe_at067():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    alpha = play(g.player1, "AT_067")
    left = g.player2.summon("CS2_231")
    target = g.player2.summon("EX1_572")
    right = g.player2.summon("CS2_231")
    g.end_turn(); g.end_turn()
    alpha.attack(target)
    return f"alpha={alpha.atk}/{alpha.damage};left={left.zone.name}/damage={left.damage};target={target.zone.name}/damage={target.damage};right={right.zone.name}/damage={right.damage};enemy_field={ids(g.player2.field)}", alpha.damage == target.atk and target.damage == alpha.atk and left.zone == right.zone == Zone.GRAVEYARD


def probe_at068():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    taunt = g.player1.summon("CS1_042")
    plain = g.player1.summon(WISP)
    spell = play(g.player1, "AT_068")
    return f"taunt={taunt.atk}/{taunt.health};plain={plain.atk}/{plain.health};spell={spell.zone.name}", (taunt.atk,taunt.health)==(3,4) and (plain.atk,plain.health)==(1,1) and spell.zone == Zone.GRAVEYARD


def probe_at069():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    target = g.player2.summon(WISP)
    partner = play(g.player1, "AT_069", target=target)
    return f"partner={partner.atk}/{partner.health}/taunt={partner.taunt}/zone={partner.zone.name};target={target.atk}/{target.health}/taunt={target.taunt}/zone={target.zone.name}", partner.taunt and target.taunt and partner.zone == target.zone == Zone.PLAY


def probe_at070():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    pirate1 = g.player1.summon("CS2_146")
    pirate2 = g.player1.summon("AT_029")
    enemy_pirate = g.player2.summon("CS2_146")
    kragg = g.player1.give("AT_070")
    reduced = kragg.cost
    kragg.play()
    can_charge = kragg.charge and kragg.can_attack()
    if can_charge:
        kragg.attack(g.player2.hero)
    return f"pirates={[(p.id,p.controller is g.player1) for p in (pirate1,pirate2,enemy_pirate)]};cost={reduced};kragg={kragg.zone.name}/charge={kragg.charge}/can_attack={can_charge};enemy_health={g.player2.hero.health}", reduced == 5 and can_charge and g.player2.hero.health == 26


def probe_at071():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    dragon = g.player1.give("EX1_572")
    champion = play(g.player1, "AT_071")
    return f"dragon_in_hand={dragon in g.player1.hand};champion={champion.atk}/{champion.health}/charge={champion.charge}/can_attack={champion.can_attack()};enemy_health={g.player2.hero.health}", champion.atk == champion.data.atk + 1 and champion.charge and champion.can_attack() and champion.zone == Zone.PLAY


def probe_at071_no_dragon():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    non_dragon = g.player1.give(WISP)
    champion = play(g.player1, "AT_071")
    return f"held_non_dragon={non_dragon.id};champion={champion.atk}/{champion.health}/charge={champion.charge}/can_attack={champion.can_attack()}/zone={champion.zone.name}", champion.atk == champion.data.atk and not champion.charge and not champion.can_attack() and champion.zone == Zone.PLAY


def probe_at072():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    spell_card = g.player1.give(FIREBALL); spell_card.shuffle_into_deck()
    minion_a = g.player1.give(WISP); minion_a.shuffle_into_deck()
    minion_b = g.player1.give("CS2_182"); minion_b.shuffle_into_deck()
    varian = play(g.player1, "AT_072")
    return f"varian={varian.zone.name};drawn_spell={spell_card.zone.name};drawn_minions={minion_a.zone.name}/{minion_b.zone.name};hand={ids(g.player1.hand)};field={ids(g.player1.field)}", varian.zone == Zone.PLAY and spell_card.zone == Zone.HAND and minion_a.zone == minion_b.zone == Zone.PLAY and len(g.player1.field) == 3


def probe_at074():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    target = g.player1.summon("CS2_182")
    spell = play(g.player1, "AT_074", target=target)
    after_spell = (target.atk,target.divine_shield,target.zone.name)
    damage = play(g.player1, MOONFIRE, target=target)
    return f"after_seal={after_spell};after_damage={target.atk}/{target.divine_shield}/{target.damage}/{target.zone.name};spell_zones={spell.zone.name}/{damage.zone.name}", after_spell[0] == target.data.atk + 3 and after_spell[1] and not target.divine_shield and target.damage == 0 and target.zone == Zone.PLAY


def probe_at075():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    recruit = g.player1.summon("CS2_101t")
    trainer = play(g.player1, "AT_075")
    existing_attack = recruit.atk
    new_recruit = g.player1.summon("CS2_101t")
    new_attack = new_recruit.atk
    trainer.destroy()
    reverted = (recruit.atk,new_recruit.atk)
    return f"trainer={trainer.zone.name};existing={existing_attack};new={new_attack};after_leave={reverted}", existing_attack == 2 and new_attack == 2 and reverted == (1,1)


def probe_at076():
    seen = set(); samples = []
    for seed in range(381, 397):
        g = fresh_game(CardClass.PALADIN, CardClass.PALADIN, seed)
        knight = play(g.player1, "AT_076")
        g.player1.used_mana = 0
        before = {id(m) for m in g.player1.field}
        g.player1.hero.power.use()
        added = [m for m in g.player1.field if id(m) not in before]
        murlocs = [m for m in added if m.race == 14]
        recruits = [m for m in added if m.id == "CS2_101t"]
        ok = knight.zone == Zone.PLAY and len(murlocs) == 1 and murlocs[0].zone == Zone.PLAY and len(recruits) == 1
        if not ok:
            return f"seed={seed};knight={knight.zone.name};added={[(m.id,m.race,m.zone.name) for m in added]};murlocs={ids(murlocs)};recruits={ids(recruits)}", False
        seen.add(murlocs[0].id)
        samples.append(murlocs[0].id)
    return f"16 seeded Inspires;random_murloc_ids={sorted(seen)};samples={samples};each also produces recruit from base Hero Power", len(seen) >= 2


def probe_at077():
    outcomes = set(); samples = []
    for seed in range(511, 535):
        g = fresh_game(CardClass.PALADIN, CardClass.PALADIN, seed)
        own_cards = [g.player1.give(card_id) for card_id in ("NEW1_030", WISP)]
        enemy_cards = [g.player2.give(card_id) for card_id in ("EX1_572", "CS2_182")]
        for card in own_cards + enemy_cards: card.shuffle_into_deck()
        weapon = play(g.player1, "AT_077")
        bonus = weapon.durability - weapon.data.durability
        outcomes.add(bonus)
        samples.append((seed, bonus, [(c.id,c.data.cost,c.zone.name) for c in own_cards], [(c.id,c.data.cost,c.zone.name) for c in enemy_cards]))
        if bonus not in (0,1) or weapon.zone != Zone.PLAY or g.player1.weapon is not weapon or any(c.zone != Zone.DECK for c in own_cards + enemy_cards):
            return f"24 seeded mixed-cost Jousts;outcomes={samples}", False
    return f"24 seeded Jousts over own costs 10/0 vs opponent costs 9/4;durability_bonus={sorted(outcomes)};samples={samples[:8]}", outcomes == {0,1}


def probe_at078():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    friendly1 = g.player1.summon("NEW1_030")
    friendly2 = g.player1.summon("CS2_182")
    friendly_low = g.player1.summon(WISP)
    enemy1 = g.player2.summon("CS2_182")
    enemy_low = g.player2.summon(WISP)
    spell = play(g.player1, "AT_078")
    return f"friendly={[(m.id,m.atk,m.zone.name) for m in (friendly1,friendly2,friendly_low)]};enemy={[(m.id,m.atk,m.zone.name) for m in (enemy1,enemy_low)]};spell={spell.zone.name}", friendly1.zone == enemy1.zone == Zone.PLAY and friendly2.zone == friendly_low.zone == enemy_low.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD


def probe_at079():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    secrets = [g.player1.give("EX1_130"),g.player1.give("EX1_130"),g.player1.give("EX1_132")]
    other = g.player1.give(WISP)
    for card in secrets + [other]: card.shuffle_into_deck()
    challenger = play(g.player1, "AT_079")
    active = sorted(c.id for c in g.player1.secrets)
    remaining = sorted(c.id for c in g.player1.deck)
    return f"challenger={challenger.zone.name};secrets={active};deck={remaining};secret_zones={[c.zone.name for c in secrets]};other={other.zone.name}", challenger.zone == Zone.PLAY and active == ["EX1_130","EX1_132"] and remaining.count("EX1_130")==1 and other.zone == Zone.DECK


def probe_at080():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    power = g.player1.hero.power
    power.use()
    before = g.player1.hero.armor
    commander = play(g.player1, "AT_080")
    power.use()
    after = g.player1.hero.armor
    return f"commander={commander.zone.name};power_armor={before}->{after};power_usable={power.is_usable()};extra={power.additional_activations}", commander.zone == Zone.PLAY and before == 2 and after == 4 and not power.is_usable()


def probe_at081():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    enemy_a = g.player2.summon("CS2_182")
    enemy_b = g.player2.summon("EX1_572")
    friendly = g.player1.summon("CS2_182")
    old = [(m.atk,m.health) for m in (enemy_a,enemy_b,friendly)]
    eadric = play(g.player1, "AT_081")
    return f"old={old};after={[(m.atk,m.health,m.zone.name) for m in (enemy_a,enemy_b,friendly)]};eadric={eadric.zone.name}", (enemy_a.atk,enemy_b.atk)==(1,1) and (enemy_a.health,enemy_b.health)==(old[0][1],old[1][1]) and (friendly.atk,friendly.health)==old[2] and eadric.zone == Zone.PLAY


def probe_at082():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    squire = play(g.player1, "AT_082")
    before = (squire.atk,squire.health)
    g.player1.hero.power.use()
    return f"before={before};after={squire.atk}/{squire.health};zone={squire.zone.name}", (squire.atk,squire.health)==(before[0]+1,before[1]) and squire.zone == Zone.PLAY


def probe_at083():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    rider = play(g.player1, "AT_083")
    g.end_turn(); g.end_turn()
    g.player1.hero.power.use()
    gained = rider.windfury
    rider.attack(g.player2.hero)
    rider.attack(g.player2.hero)
    damage = 30 - g.player2.hero.health
    g.end_turn()
    return f"windfury_after_inspire={gained};two_attacks_damage={damage};windfury_after_turn={rider.windfury};zone={rider.zone.name}", gained and damage == rider.atk * 2 and not rider.windfury and rider.zone == Zone.PLAY


def probe_at084():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    target = g.player1.summon(WISP)
    base = target.atk
    carrier = play(g.player1, "AT_084", target=target)
    return f"target_attack={target.atk},base={base};carrier={carrier.zone.name};target={target.zone.name}", target.atk == base + 2 and target.zone == Zone.PLAY and carrier.zone == Zone.PLAY


def probe_at085():
    g = fresh_game(CardClass.MAGE, CardClass.MAGE)
    maiden = play(g.player1, "AT_085")
    cost_with = g.player1.hero.power.cost
    g.player1.hero.power.use(g.player2.hero)
    maiden.destroy()
    cost_after = g.player1.hero.power.cost
    return f"maiden={maiden.zone.name};hero_power_cost={cost_with}->{cost_after};enemy_health={g.player2.hero.health}", cost_with == 1 and cost_after == 2 and g.player2.hero.health == 29


def probe_at086():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    saboteur = play(g.player1, "AT_086")
    before_p2 = g.player2.hero.power.cost
    g.end_turn()
    next_p2 = g.player2.hero.power.cost
    g.end_turn(); g.end_turn()
    after_expiry = g.player2.hero.power.cost
    return f"saboteur={saboteur.zone.name};costs={before_p2}->{next_p2}->{after_expiry}", before_p2 == 2 and next_p2 == 7 and after_expiry == 2


def probe_at087():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    rider = play(g.player1, "AT_087")
    before = (rider.charge,rider.divine_shield,rider.can_attack())
    victim = g.player2.summon(WISP)
    rider.attack(victim)
    return f"before_attack={before};after={rider.zone.name}/shield={rider.divine_shield}/can_attack={rider.can_attack()};victim={victim.zone.name};enemy_hero={g.player2.hero.health}", before == (True,True,True) and not rider.divine_shield and rider.zone == Zone.PLAY and victim.zone == Zone.GRAVEYARD


def probe_at088():
    outcomes = set()
    samples = []
    for seed in range(130,150):
        g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR, seed)
        champion = play(g.player1, "AT_088")
        intended = g.player2.summon("CS2_231")
        alternate = g.player2.summon("CS2_182")
        g.end_turn(); g.end_turn()
        champion.attack(intended)
        result = (intended.damage > 0 or intended.zone == Zone.GRAVEYARD, alternate.damage > 0 or alternate.zone == Zone.GRAVEYARD, g.player2.hero.health < 30)
        samples.append(result)
        if sum(result) != 1:
            return f"seed={seed};attacker={champion.zone.name};result={result};samples={samples}", False
        outcomes.add(result)
    return f"20 seeded attacks;outcomes={sorted(outcomes)};samples={samples[:8]}", len(outcomes) >= 2 and (True,False,False) in outcomes


def probe_at089():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    lieutenant = play(g.player1, "AT_089")
    base = (lieutenant.atk,lieutenant.health)
    g.player1.hero.power.use()
    return f"base={base};after={lieutenant.atk}/{lieutenant.health};zone={lieutenant.zone.name}", (lieutenant.atk,lieutenant.health)==(base[0],base[1]+1) and lieutenant.zone == Zone.PLAY


def probe_at090():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    other = g.player1.summon(WISP)
    mukla = play(g.player1, "AT_090")
    before_mukla = (mukla.atk,mukla.health)
    before_other = (other.atk,other.health)
    g.player1.hero.power.use()
    return f"mukla={mukla.atk}/{mukla.health},before={before_mukla};other={other.atk}/{other.health},before={before_other};field={[(m.id,m.atk,m.health) for m in g.player1.field]}", (mukla.atk,mukla.health)==before_mukla and (other.atk,other.health)==(before_other[0]+1,before_other[1]+1)


def probe_at091():
    g = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
    g.player1.hero.set_current_health(20)
    medic = play(g.player1, "AT_091")
    g.player1.hero.power.use(g.player1.hero)
    return f"medic={medic.zone.name};hero_health={g.player1.hero.health};hero_power_used={g.player1.times_hero_power_used_this_game}", medic.zone == Zone.PLAY and g.player1.hero.health == 24


def probe_at093():
    g = fresh_game(CardClass.MAGE, CardClass.MAGE)
    kobold = play(g.player1, "AT_093")
    spell = play(g.player1, MOONFIRE, target=g.player2.hero)
    return f"kobold={kobold.spellpower};player_spellpower={g.player1.spellpower};enemy_damage={30-g.player2.hero.health};spell={spell.zone.name}", g.player1.spellpower == 1 and g.player2.hero.health == 28 and spell.zone == Zone.GRAVEYARD


def probe_at094():
    seen = set(); samples=[]
    for seed in range(160,176):
        g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR, seed)
        wisp = g.player2.summon(WISP)
        yeti = g.player2.summon("CS2_182")
        juggle = play(g.player1, "AT_094")
        hit=[]
        if g.player2.hero.health < 30: hit.append("hero")
        for label,m in (("wisp",wisp),("yeti",yeti)):
            if m.damage or m.zone == Zone.GRAVEYARD: hit.append(label)
        seen.update(hit); samples.append((hit,[(m.id,m.damage,m.zone.name) for m in (wisp,yeti)],g.player2.hero.health))
        if juggle.zone != Zone.PLAY or len(hit) != 1:
            return f"seed={seed};hit={hit};samples={samples}",False
    return f"16 battlecries;candidate_outcomes={sorted(seen)};samples={samples[:5]}", len(seen)>=2


def probe_at095():
    g = fresh_game(CardClass.MAGE, CardClass.MAGE)
    knight = play(g.player1, "AT_095")
    stealth_before = knight.stealthed
    shield_before = knight.divine_shield
    hidden_targets = knight in g.player2.give("CS2_029").targets
    g.end_turn(); g.end_turn()
    victim = g.player2.summon("CS2_182")
    knight.attack(victim)
    stealth_after, shield_after = knight.stealthed, knight.divine_shield
    return f"after_play=stealth:{stealth_before},shield:{shield_before};opponent_spell_targets_knight={hidden_targets};after_attack=stealth:{stealth_after},shield:{shield_after},victim:{victim.zone.name}/damage={victim.damage}", stealth_before and shield_before and not hidden_targets and not stealth_after and not shield_after and victim.damage == knight.atk and victim.zone == Zone.PLAY


def probe_at096():
    g = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
    mech = g.player1.summon("BOT_309")
    base = (mech.atk,mech.health)
    nonmech = g.player1.summon("CS2_182")
    base_nonmech = (nonmech.atk,nonmech.health)
    knight = play(g.player1, "AT_096", target=mech)
    return f"mech_race={mech.race};mech={mech.atk}/{mech.health},base={base};nonmech={nonmech.atk}/{nonmech.health},base={base_nonmech};knight={knight.zone.name}", mech.race == 17 and (mech.atk,mech.health)==(base[0]+1,base[1]+1) and (nonmech.atk,nonmech.health)==base_nonmech and knight.zone == Zone.PLAY


def probe_at097():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    attendee = play(g.player1, "AT_097")
    attacker = g.player2.summon("AT_087")
    legal = attendee in attacker.attack_targets
    face_legal = g.player1.hero in attacker.attack_targets
    return f"attendee={attendee.zone.name}/taunt={attendee.taunt};attacker_targets={[(x.id,x.controller is g.player1) for x in attacker.attack_targets]};taunt_legal={legal};hero_legal={face_legal}", attendee.taunt and legal and not face_legal


def probe_at098():
    g = fresh_game(CardClass.MAGE, CardClass.WARLOCK)
    mage = next(p for p in g.players if p.hero.card_class == CardClass.MAGE)
    warlock = next(p for p in g.players if p.hero.card_class == CardClass.WARLOCK)
    if g.current_player is not mage:
        g.end_turn()
    lifetap = warlock.hero.power
    spelleater = play(mage, "AT_098")
    cloned = mage.hero.power
    deck_card = mage.give("CS2_182"); deck_card.shuffle_into_deck()
    mage.used_mana = 0
    health = mage.hero.health
    cloned.use()
    return f"mage_owner={CardClass(mage.hero.card_class).name};warlock_opponent={CardClass(warlock.hero.card_class).name};spelleater={spelleater.zone.name};enemy_power={lifetap.id};copied_power={cloned.id};drawn={deck_card.zone.name};mage_health={mage.hero.health},before={health}", spelleater.zone == Zone.PLAY and cloned.id == lifetap.id and deck_card.zone == Zone.HAND and mage.hero.health == health - 2


def probe_at099():
    g = fresh_game(CardClass.WARRIOR, CardClass.WARRIOR)
    rider = play(g.player1, "AT_099")
    g.player1.used_mana = 0
    before = {id(m) for m in g.player1.field}
    g.player1.hero.power.use()
    added = [m for m in g.player1.field if id(m) not in before]
    kodos = [m for m in added if m.id == "AT_099t"]
    recruits = [m for m in added if m.id == "CS2_101t"]
    return f"rider={rider.zone.name};added={[(m.id,m.atk,m.health,m.zone.name) for m in added]};kodos={ids(kodos)};recruits={ids(recruits)}", rider.zone == Zone.PLAY and len(kodos)==1 and (kodos[0].atk,kodos[0].health,kodos[0].zone)==(3,5,Zone.PLAY) and len(recruits)==0


MULTI_CASES = {
    "AT_022": [
        ("tgt_at022_play_trigger", "Playing this card deals 4 damage to one random enemy character.", probe_at022),
        ("tgt_at022_discard_trigger", "Discarding this card deals 4 damage to one random enemy character.", probe_at022_discard),
    ],
    "AT_010": [
        ("tgt_at010_with_beast", "With a friendly Beast, summon a random Beast.", probe_at010),
        ("tgt_at010_without_beast", "Without a friendly Beast, summon no Beast.", probe_at010_no_beast),
    ],
    "AT_017": [
        ("tgt_at017_holding_dragon", "Holding a Dragon gives +1 Attack and Taunt.", probe_at017),
        ("tgt_at017_no_dragon", "Without a Dragon, grant neither bonus.", probe_at017_no_dragon),
    ],
    "AT_030": [
        ("tgt_at030_combo", "With Combo active, deal 1 damage.", probe_at030),
        ("tgt_at030_no_combo", "Without Combo, deal no damage.", probe_at030_no_combo),
    ],
    "AT_032": [
        ("tgt_at032_with_pirate", "With a friendly Pirate, gain +1/+1.", probe_at032),
        ("tgt_at032_without_pirate", "Without a friendly Pirate, gain no stats.", probe_at032_no_pirate),
    ],
    "AT_065": [
        ("tgt_at065_with_taunt", "With a friendly Taunt minion, gain +1 Durability.", probe_at065),
        ("tgt_at065_without_taunt", "Without a friendly Taunt minion, gain no Durability.", probe_at065_no_taunt),
    ],
    "AT_071": [
        ("tgt_at071_holding_dragon", "Holding a Dragon gives +1 Attack and Charge.", probe_at071),
        ("tgt_at071_no_dragon", "Without a Dragon, grant neither bonus.", probe_at071_no_dragon),
    ],
    "AT_037": [
        ("tgt_at037_choose_damage", "Choose the damage option and deal 2 to the selected minion.", probe_at037a),
        ("tgt_at037_choose_saplings", "Choose the summon option and create two 1/1 Saplings.", probe_at037b),
    ],
}


def main():
    with BASELINE.open(encoding="utf-8-sig", newline="") as handle:
        baseline_rows = [r for r in csv.DictReader(handle) if r["set"] == "The Grand Tournament (TGT)"]
    with MASTER.open(encoding="utf-8-sig", newline="") as handle:
        master = {r["card_id"]: r for r in csv.DictReader(handle)}
    with QUALITY.open(encoding="utf-8-sig", newline="") as handle:
        quality = {r["card_id"]: r for r in csv.DictReader(handle)}

    our_rows = [r for r in baseline_rows if int(r["card_id"][3:6]) < 100]
    if len(our_rows) != 95:
        raise SystemExit(f"expected exactly 95 frozen TGT IDs below AT_100; found {len(our_rows)}")
    missing = []

    for baseline_row in our_rows:
        card_id = baseline_row["card_id"]
        card = master.get(card_id)
        if not card:
            missing.append(card_id)
            continue
        cases = MULTI_CASES.get(card_id)
        if cases is None:
            fn = globals().get("probe_at" + card_id[3:].lower())
            if fn is None:
                missing.append(card_id)
                continue
            cases = [(f"tgt_{card_id.lower()}_core_behavior", card["card_text_en"], fn)]

        previous = quality.get(card_id, {})
        source = card["python_source"] or "CardDefs.xml/runtime native card tags"
        test_refs = card["test_refs_candidate"] or "none referenced"
        prior = f"baseline conclusion=YELLOW; current prior status={previous.get('status','missing')}; prior reason={previous.get('reason','not available')}"
        meta = (
            f"EN: {card['card_text_en']} || ZH: {card['card_text_zh']} || "
            f"Implementation source: {source} || Existing test refs: {test_refs} || {prior}"
        )

        outcomes = []
        for case_id, expected, fn in cases:
            outcome = safe_probe(card_id, case_id, expected, fn, meta)
            outcomes.append(outcome)

        failures = [r for r in OUT_ROWS if r["card_id"] == card_id and r["outcome"] == "confirmed_error"]
        uncertain = [r for r in OUT_ROWS if r["card_id"] == card_id and r["outcome"] == "inconclusive"]
        if failures:
            status = "RED"
            first = failures[0]
            reason = f"Confirmed runtime mismatch in {first['case_id']}: expected {first['expected']}; observed {first['observed']}"
        elif uncertain or not outcomes:
            status = "YELLOW"
            details = "; ".join(f"{r['case_id']}: {r['observed']}" for r in uncertain) or "no executable bespoke case"
            reason = f"YELLOW blocker: behavior assertion is inconclusive: {details}"
        else:
            status = "GREEN"
            reason = "All listed mechanism labels were exercised by the card-specific case(s); every state assertion passed."
        VERDICTS.append({
            "card_id": card_id,
            "status": status,
            "mechanic_scope": card["mechanics"],
            "reason": reason,
            "probe_file": "tgt_probe.csv",
            "notes": meta,
        })
        save_checkpoints()
        print(f"{card_id}: {status} ({len(cases)} case(s))", flush=True)

    if missing:
        save_checkpoints()
        raise SystemExit(f"missing bespoke probe functions or card_master rows: {missing}")
    print(f"completed={len(VERDICTS)} cases={len(OUT_ROWS)} counts=" + str({s: sum(v['status']==s for v in VERDICTS) for s in ("GREEN","YELLOW","RED")}))


if __name__ == "__main__":
    main()
