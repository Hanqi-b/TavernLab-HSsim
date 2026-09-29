"""Card-specific runtime behavior probes for the first half of Classic YELLOW.

Run from the repository root with:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_first.py

Every case plays/uses the real card in a fresh Fireplace game and writes its
observation immediately. The paired verdict is updated after each card.
"""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
PROBE_OUT = HERE / "classic_probe_first.csv"
VERDICT_OUT = HERE / "classic_verdict_first.csv"
PROBE_FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
VERDICT_FIELDS = ["card_id", "status", "mechanic_scope", "reason", "probe_file", "notes"]


def new_game(cls=CardClass.MAGE):
    game = prepare_empty_game(cls, cls)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = 10
    game.player2.max_mana = 10
    return game


def metadata():
    with (HERE / "card_master.csv").open(encoding="utf-8-sig", newline="") as stream:
        cards = {row["card_id"]: row for row in csv.DictReader(stream)}
    with (HERE / "card_quality.csv").open(encoding="utf-8-sig", newline="") as stream:
        quality = {row["card_id"]: row for row in csv.DictReader(stream)}
    return cards, quality


CARDS, QUALITY = metadata()
PROBE_ROWS = []
VERDICT_ROWS = []


def save_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def upsert(rows, row, key_fields):
    key = tuple(row[field] for field in key_fields)
    for index, prior in enumerate(rows):
        if tuple(prior[field] for field in key_fields) == key:
            rows[index] = row
            return
    rows.append(row)


def run_card(card_id, cases, blocker=None):
    """Run this card's bespoke cases and persist evidence before continuing."""
    card_rows = []
    for case_id, expected, probe in cases:
        try:
            observed, passed = probe()
            outcome = "pass" if passed is True else "confirmed_error" if passed is False else "inconclusive"
        except Exception as error:
            observed = f"exception={type(error).__name__}: {error}"
            outcome = "inconclusive"
        card = CARDS[card_id]
        row_notes = (
            f"EN: {card['card_text_en']} ZH: {card['card_text_zh']} "
            f"Impl: {card['python_source'] or 'no per-card Python script; runtime tags/native behavior'}. "
            f"Existing test references: {card['test_refs_candidate'] or 'none'}. "
            "Prior audit: card_quality.csv marked YELLOW; generic play smoke alone is not effect evidence."
        )
        row = {"card_id": card_id, "case_id": case_id, "expected": expected,
               "observed": str(observed), "outcome": outcome, "notes": row_notes}
        upsert(PROBE_ROWS, row, ("card_id", "case_id"))
        card_rows.append(row)
    outcomes = {row["outcome"] for row in card_rows}
    status = "RED" if "confirmed_error" in outcomes else "YELLOW" if "inconclusive" in outcomes or blocker else "GREEN"
    label = "GREEN" if status == "GREEN" else "RED" if status == "RED" else "YELLOW"
    reason = f"{label}: " + "; ".join(
        f"{row['case_id']} {row['outcome']}: {row['expected']} Observed {row['observed'][:220]}"
        + ("…" if len(row["observed"]) > 220 else "")
        for row in card_rows
    )
    if blocker:
        reason += f"; unresolved blocker: {blocker}"
    references = CARDS[card_id]["test_refs_candidate"] or "none"
    verdict = {"card_id": card_id, "status": status, "mechanic_scope": CARDS[card_id]["mechanics"],
               "reason": reason, "probe_file": PROBE_OUT.name,
               "notes": f"Case evidence saved immediately. EN/ZH/source/test refs are recorded in probe CSV; prior test refs: {references}."}
    upsert(VERDICT_ROWS, verdict, ("card_id",))
    save_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    save_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)


def probe_cs1_069_taunt_combat():
    game = new_game()
    defender, attacker_owner = game.player1, game.player2
    creeper = defender.give("CS1_069")
    creeper.play()
    bystander = defender.summon("CS2_231")
    game.end_turn()
    boar = attacker_owner.give("CS2_171")
    boar.play()
    candidates = list(boar.targets)
    can_attack_face = defender.hero in candidates
    can_attack_taunt = creeper in candidates
    boar.attack(creeper)
    observed = (
        f"taunt={creeper.taunt};legal_targets={[getattr(x, 'id', 'HERO') for x in candidates]};"
        f"face_legal={can_attack_face};taunt_legal={can_attack_taunt};"
        f"boar={boar.zone.name};creeper={creeper.health}/{creeper.zone.name};"
        f"bystander={bystander.health}/{bystander.zone.name}"
    )
    return observed, (
        creeper.taunt and can_attack_taunt and not can_attack_face
        and creeper.health == 5 and creeper in defender.field
        and bystander.health == 1 and bystander in defender.field
        and boar.zone == Zone.GRAVEYARD
    )


def probe_cs1_129_attack_matches_current_health():
    observations = []
    outcomes = []
    for side in ("friendly", "enemy"):
        game = new_game()
        caster = game.player1
        owner = game.player1 if side == "friendly" else game.player2
        target = owner.summon("CS2_182")
        target.set_current_health(3)
        inner_fire = caster.give("CS1_129")
        can_target = target in inner_fire.targets
        inner_fire.play(target=target)
        observations.append(
            f"{side}={target.atk}/{target.health}/{target.max_health},legal={can_target},spell={inner_fire.zone.name}"
        )
        outcomes.append(
            can_target and target.atk == 3 and target.health == 3 and target.max_health == 5
            and target in owner.field and inner_fire.zone == Zone.GRAVEYARD
        )
    return ";".join(observations), all(outcomes)


def probe_cs2_028_blizzard_enemy_damage_freeze():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friend = p1.summon("CS2_182")
    fragile_enemy = p2.summon("CS2_231")
    sturdy_enemy = p2.summon("CS2_182")
    spell = p1.give("CS2_028")
    spell.play()
    observed = (
        f"friendly={friend.health}/{friend.zone.name},frozen={friend.frozen};"
        f"enemy_wisp={fragile_enemy.health}/{fragile_enemy.zone.name},frozen={fragile_enemy.frozen};"
        f"enemy_yeti={sturdy_enemy.health}/{sturdy_enemy.zone.name},frozen={sturdy_enemy.frozen};"
        f"spell={spell.zone.name}"
    )
    return observed, (
        friend.health == 5 and not friend.frozen and friend in p1.field
        and fragile_enemy.zone == Zone.GRAVEYARD
        and sturdy_enemy.health == 3 and sturdy_enemy.frozen and sturdy_enemy in p2.field
        and spell.zone == Zone.GRAVEYARD
    )


def probe_cs2_038_ancestral_spirit_resummons_once():
    game = new_game()
    p1 = game.player1
    target = p1.summon("CS2_231")
    spell = p1.give("CS2_038")
    spell.play(target=target)
    enchantments = len(target.buffs)
    target.destroy()
    revived = [minion for minion in p1.field if minion.id == "CS2_231"]
    observed = (
        f"original={target.zone.name},deathrattle_effects={enchantments};"
        f"field={[f'{m.id}:{m.atk}/{m.health}' for m in p1.field]};"
        f"copies={len(revived)};spell={spell.zone.name}"
    )
    return observed, (
        target.zone == Zone.GRAVEYARD and len(revived) == 1
        and revived[0] is not target and revived[0].health == 1
        and spell.zone == Zone.GRAVEYARD
    )


def probe_cs2_038_enemy_target_deathrattle_resummons():
    game = new_game()
    caster, enemy = game.player1, game.player2
    target = enemy.summon("CS2_231")
    spell = caster.give("CS2_038")
    legal = target in spell.targets
    spell.play(target=target)
    target.destroy()
    revived = [minion for player in game.players for minion in player.field if minion.id == "CS2_231"]
    observed = (
        f"legal_enemy_target={legal};original={target.zone.name};"
        f"caster_field={[m.id for m in caster.field]};enemy_field={[m.id for m in enemy.field]};"
        f"revived_count={len(revived)};revived_owners={[m.controller.name for m in revived]}"
    )
    return observed, legal and target.zone == Zone.GRAVEYARD and len(revived) == 1


def probe_cs2_053_far_sight_draw_cost_reduction():
    game = new_game()
    p1 = game.player1
    top = p1.card("CS2_182", zone=Zone.DECK)
    unrelated = p1.give("CS2_231")
    spell = p1.give("CS2_053")
    printed_top_cost = top.data.cost
    spell.play()
    observed = (
        f"top={top.id}:{top.zone.name},cost={top.cost},printed={printed_top_cost};"
        f"unrelated={unrelated.id}:{unrelated.cost};deck={len(p1.deck)};spell={spell.zone.name}"
    )
    return observed, (
        top in p1.hand and top.zone == Zone.HAND and top.cost == max(0, printed_top_cost - 3)
        and unrelated.cost == unrelated.data.cost and not p1.deck
        and spell.zone == Zone.GRAVEYARD
    )


def probe_cs2_053_far_sight_floors_low_cost_at_zero():
    game = new_game()
    p1 = game.player1
    top = p1.card("CS2_075", zone=Zone.DECK)
    printed = top.data.cost
    spell = p1.give("CS2_053")
    spell.play()
    observed = f"top={top.id}:{top.zone.name},cost={top.cost},printed={printed};spell={spell.zone.name}"
    return observed, top in p1.hand and top.cost == 0 and printed == 1 and spell.zone == Zone.GRAVEYARD


def probe_cs2_059_blood_imp_end_turn_buff_other():
    winners = set()
    failures = []
    traces = []
    for seed in range(16):
        game = new_game()
        p1 = game.player1
        first = p1.summon("CS2_231")
        second = p1.summon("CS2_231")
        imp = p1.give("CS2_059")
        imp.play()
        game.random.seed(seed)
        game.end_turn()
        changed = [index for index, unit in enumerate((first, second)) if unit.max_health == 2]
        if len(changed) == 1:
            winners.add(changed[0])
        if not (len(changed) == 1 and imp.max_health == 1 and imp.stealthed):
            failures.append(seed)
        traces.append((seed, changed))
    observed = f"seeds=0..15;winner_indexes={sorted(winners)};failures={failures};traces={traces}"
    return observed, winners == {0, 1} and not failures


def probe_cs2_073_cold_blood_base_and_combo():
    game = new_game()
    enemy_target = game.player2.summon("CS2_231")
    plain_spell = game.player1.give("CS2_073")
    legal = enemy_target in plain_spell.targets
    plain_spell.play(target=enemy_target)
    observed = f"legal_enemy_target={legal};enemy_attack={enemy_target.atk};spell={plain_spell.zone.name}"
    return observed, legal and enemy_target.atk == 3 and plain_spell.zone == Zone.GRAVEYARD


def probe_cs2_073_cold_blood_combo_branch():
    game = new_game()
    friendly_target = game.player1.summon("CS2_231")
    game.player1.give("CS2_008").play(target=game.player2.hero)
    combo_spell = game.player1.give("CS2_073")
    legal = friendly_target in combo_spell.targets
    combo_spell.play(target=friendly_target)
    observed = f"legal_friendly_target={legal};friendly_attack={friendly_target.atk};spell={combo_spell.zone.name}"
    return observed, legal and friendly_target.atk == 5 and combo_spell.zone == Zone.GRAVEYARD


def probe_cs2_104_rampage_requires_damaged_minion():
    game = new_game()
    p1, p2 = game.player1, game.player2
    damaged = p2.summon("CS2_182")
    damaged.set_current_health(3)
    healthy = p2.summon("CS2_182")
    spell = p1.give("CS2_104")
    legal_damaged, illegal_healthy = damaged in spell.targets, healthy in spell.targets
    spell.play(target=damaged)
    observed = (
        f"damaged={damaged.atk}/{damaged.health}/{damaged.max_health},legal={legal_damaged};"
        f"healthy={healthy.atk}/{healthy.health}/{healthy.max_health},legal={illegal_healthy};"
        f"spell={spell.zone.name}"
    )
    return observed, (
        legal_damaged and not illegal_healthy
        and (damaged.atk, damaged.health, damaged.max_health) == (7, 6, 8)
        and (healthy.atk, healthy.health, healthy.max_health) == (4, 5, 5)
        and spell.zone == Zone.GRAVEYARD
    )


def probe_cs2_104_rampage_buffs_damaged_friendly_minion():
    game = new_game()
    p1 = game.player1
    target = p1.summon("CS2_182")
    target.set_current_health(3)
    spell = p1.give("CS2_104")
    legal = target in spell.targets
    spell.play(target=target)
    observed = f"legal_friendly_target={legal};stats={target.atk}/{target.health}/{target.max_health};spell={spell.zone.name}"
    return observed, legal and (target.atk, target.health, target.max_health) == (7, 6, 8)


def probe_cs2_117_farseer_restores_three():
    game = new_game()
    p1 = game.player1
    p1.hero.damage = 4
    before = p1.hero.health
    minion = p1.give("CS2_117")
    minion.play(target=p1.hero)
    observed = f"hero={before}->{p1.hero.health}/30;farseer={minion.atk}/{minion.health}:{minion.zone.name}"
    return observed, p1.hero.health == before + 3 and minion in p1.field


def probe_cs2_117_farseer_heals_enemy_minion_without_overhealing():
    game = new_game()
    p1, p2 = game.player1, game.player2
    target = p2.summon("CS2_182")
    target.set_current_health(2)
    farseer = p1.give("CS2_117")
    legal = target in farseer.targets
    farseer.play(target=target)
    enemy_result = (target.health, target.max_health)

    cap_game = new_game()
    cap_target = cap_game.player1.summon("CS2_231")
    cap_spell = cap_game.player1.give("CS2_117")
    cap_legal = cap_target in cap_spell.targets
    cap_spell.play(target=cap_target)
    observed = (
        f"enemy_minion_legal={legal},enemy_health={enemy_result};"
        f"full_friendly_minion_legal={cap_legal},health={cap_target.health}/{cap_target.max_health};"
        f"farseer={farseer.zone.name},cap_card={cap_spell.zone.name}"
    )
    return observed, (
        legal and enemy_result == (5, 5) and farseer in p1.field
        and cap_legal and cap_target.health == cap_target.max_health == 1
        and cap_spell in cap_game.player1.field
    )


def probe_cs2_146_deckhand_conditional_charge():
    no_weapon = new_game()
    plain = no_weapon.player1.give("CS2_146")
    plain.play()
    plain_charge = bool(plain.charge)

    armed = new_game()
    weapon = armed.player1.give("CS2_091")
    weapon.play()
    deckhand = armed.player1.give("CS2_146")
    deckhand.play()
    can_attack_immediately = deckhand.can_attack()
    deckhand.attack(armed.player2.hero)
    observed = (
        f"no_weapon_charge={plain_charge};armed_weapon={armed.player1.weapon.id if armed.player1.weapon else None};"
        f"armed_charge={deckhand.charge};can_attack={can_attack_immediately};"
        f"enemy_hero={armed.player2.hero.health};deckhand_attacks={deckhand.num_attacks}"
    )
    return observed, (
        not plain_charge and deckhand.charge and can_attack_immediately
        and armed.player2.hero.health == 30 - deckhand.atk and deckhand.num_attacks == 1
    )


def probe_cs2_151_silver_hand_knight_summons_squire():
    game = new_game()
    p1 = game.player1
    before = list(p1.field)
    knight = p1.give("CS2_151")
    knight.play()
    added = [minion for minion in p1.field if minion not in before]
    observed = f"field={[f'{m.id}:{m.atk}/{m.health}' for m in p1.field]};added={len(added)}"
    return observed, (
        knight in p1.field and len(added) == 2
        and any(m.id == "CS2_152" and m.atk == 2 and m.health == 2 for m in added)
    )


def probe_cs2_151_squire_respects_last_board_slot():
    game = new_game()
    p1 = game.player1
    existing = [p1.summon("CS2_231") for _ in range(6)]
    knight = p1.give("CS2_151")
    knight.play()
    observed = f"field_count={len(p1.field)};knight_in_field={knight in p1.field};squires={sum(m.id == 'CS2_152' for m in p1.field)}"
    return observed, len(p1.field) == 7 and all(m in p1.field for m in existing) and knight in p1.field and not any(m.id == "CS2_152" for m in p1.field)


def probe_cs2_161_ravenholdt_stealth():
    game = new_game()
    assassin = game.player1.give("CS2_161")
    assassin.play()
    game.end_turn()
    enemy_targets = list(game.player2.hero.power.targets)
    moonfire = game.player2.give("CS2_008")
    spell_targets = list(moonfire.targets)
    attempted = assassin in spell_targets
    observed = (
        f"stealthed={assassin.stealthed};hero_power_can_target={assassin in enemy_targets};"
        f"opponent_turn={game.current_player is game.player2};moonfire_can_target={attempted};"
        f"spell_targets={[getattr(t, 'id', 'HERO') for t in spell_targets]};moonfire={moonfire.zone.name}"
    )
    return observed, assassin.stealthed and assassin not in enemy_targets and not attempted and moonfire.zone == Zone.HAND


def probe_cs2_169_dragonhawk_windfury_two_attacks():
    game = new_game()
    hawk = game.player1.give("CS2_169")
    hawk.play()
    summoned = hawk.windfury
    game.end_turn()
    game.end_turn()
    ready_at_start = hawk.can_attack()
    hawk.attack(game.player2.hero)
    after_first = (game.player2.hero.health, hawk.can_attack())
    hawk.attack(game.player2.hero)
    after_second = (game.player2.hero.health, hawk.can_attack())
    observed = f"windfury={summoned};ready={ready_at_start};first={after_first};second={after_second}"
    return observed, summoned and ready_at_start and after_first == (29, True) and after_second == (28, False)


def probe_cs2_181_injured_blademaster_self_damage():
    game = new_game()
    blademaster = game.player1.give("CS2_181")
    blademaster.play()
    observed = (
        f"stats={blademaster.atk}/{blademaster.health}/{blademaster.max_health};"
        f"zone={blademaster.zone.name};field={blademaster in game.player1.field}"
    )
    return observed, (
        (blademaster.atk, blademaster.health, blademaster.max_health) == (4, 3, 7)
        and blademaster.zone == Zone.PLAY
    )


def probe_cs2_203_owl_silences_taunt_and_shield():
    game = new_game()
    p1, p2 = game.player1, game.player2
    target = p2.summon("EX1_032")
    owl = p1.give("CS2_203")
    can_target = target in owl.targets
    owl.play(target=target)
    observed = (
        f"target={target.id};taunt={target.taunt};divine_shield={target.divine_shield};"
        f"silenced={target.silenced};owl={owl.zone.name}"
    )
    return observed, (
        can_target and target.silenced and not target.taunt and not target.divine_shield
        and target in p2.field and owl in p1.field
    )


def probe_cs2_203_owl_can_silence_friendly_minion():
    game = new_game()
    p1 = game.player1
    target = p1.summon("EX1_032")
    owl = p1.give("CS2_203")
    legal = target in owl.targets
    owl.play(target=target)
    observed = f"legal_friendly_target={legal};silenced={target.silenced};taunt={target.taunt};shield={target.divine_shield};zone={target.zone.name}"
    return observed, legal and target.silenced and not target.taunt and not target.divine_shield and target in p1.field


def probe_cs2_221_spiteful_smith_enrage_aura_tracks_damage():
    game = new_game()
    p1 = game.player1
    smith = p1.give("CS2_221")
    smith.play()
    weapon = p1.give("CS2_091")
    weapon.play()
    before = weapon.atk
    game.end_turn()
    game.player2.give("CS2_008").play(target=smith)
    enraged = (bool(smith.enraged), weapon.atk)
    game.end_turn()
    game.player1.give("CS2_007").play(target=smith)
    healed = (bool(smith.enraged), weapon.atk)
    observed = f"weapon_attack={before}->{enraged}->{healed};smith_health={smith.health}/{smith.max_health}"
    return observed, before == 1 and enraged == (True, 3) and healed == (False, 1)


def probe_cs2_227_venture_co_cost_aura_updates_and_clears():
    game = new_game()
    p1 = game.player1
    waiting = p1.give("CS2_182")
    mercenary = p1.give("CS2_227")
    base_cost = waiting.data.cost
    mercenary.play()
    while_on_board = waiting.cost
    silenced = mercenary.silence()
    after_silence = waiting.cost
    newly_added = p1.give("CS2_182")
    observed = (
        f"base={base_cost};held_cost={while_on_board};silenced={silenced};"
        f"after_silence={after_silence};new_hand_cost={newly_added.cost};mercenary={mercenary.zone.name}"
    )
    return observed, (
        while_on_board == base_cost + 3 and after_silence == base_cost
        and newly_added.cost == base_cost and mercenary in p1.field
    )


def probe_cs2_233_blade_flurry_weapon_damage_and_destroy():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    dead_enemy = p2.summon("CS2_231")
    surviving_enemy = p2.summon("CS2_182")
    weapon = p1.give("CS2_091")
    weapon.play()
    spell = p1.give("CS2_233")
    spell.play()
    observed = (
        f"weapon={weapon.zone.name},equipped={p1.weapon};"
        f"enemy_wisp={dead_enemy.health}/{dead_enemy.zone.name};"
        f"enemy_yeti={surviving_enemy.health}/{surviving_enemy.zone.name};"
        f"friendly={friendly.health}/{friendly.zone.name};spell={spell.zone.name};enemy_hero={p2.hero.health}"
    )
    return observed, (
        weapon.zone == Zone.GRAVEYARD and p1.weapon is None
        and dead_enemy.zone == Zone.GRAVEYARD and surviving_enemy.health == 4
        and friendly.health == 5 and p2.hero.health == 30
        and spell.zone == Zone.GRAVEYARD
    )


def probe_ds1_188_longbow_hero_immune_during_attack():
    game = new_game()
    p1, p2 = game.player1, game.player2
    weapon = p1.give("DS1_188")
    weapon.play()
    target = p2.summon("CS2_231")
    hero_before = p1.hero.health
    weapon_durability = weapon.durability
    p1.hero.attack(target)
    observed = (
        f"hero_health={hero_before}->{p1.hero.health};target={target.health}/{target.zone.name};"
        f"weapon={weapon.zone.name},durability={weapon.durability}/{weapon_durability};hero_attacks={p1.hero.num_attacks}"
    )
    return observed, (
        p1.hero.health == hero_before and target.zone == Zone.GRAVEYARD
        and weapon.durability == weapon_durability - 1 and p1.hero.num_attacks == 1
    )


def probe_ex1_001_lightwarden_triggers_on_both_sides_heals():
    game = new_game()
    p1, p2 = game.player1, game.player2
    warden = p1.give("EX1_001")
    warden.play()
    p2.hero.damage = 10
    p2_health = p2.hero.health
    p1.give("CS2_007").play(target=p2.hero)
    after_enemy_hero_heal = (p2.hero.health, warden.atk)
    wounded = p1.summon("CS2_182")
    wounded.set_current_health(2)
    p1.give("CS2_007").play(target=wounded)
    after_friendly_minion_heal = (wounded.health, warden.atk)
    observed = (
        f"enemy_hero={p2_health}->{after_enemy_hero_heal};"
        f"friendly_minion={wounded.health}/{wounded.max_health},warden_attack={after_friendly_minion_heal[1]}"
    )
    return observed, (
        after_enemy_hero_heal == (28, 3)
        and after_friendly_minion_heal == (5, 5)
        and warden in p1.field
    )


def probe_ex1_002_black_knight_only_destroys_enemy_taunt():
    game = new_game()
    p1, p2 = game.player1, game.player2
    enemy_taunt = p2.summon("EX1_032")
    enemy_plain = p2.summon("CS2_231")
    friendly_taunt = p1.summon("EX1_032")
    knight = p1.give("EX1_002")
    targets = list(knight.targets)
    legal_enemy_taunt = enemy_taunt in targets
    illegal_enemy_plain = enemy_plain in targets
    illegal_friendly = friendly_taunt in targets
    knight.play(target=enemy_taunt)
    observed = (
        f"legal_enemy_taunt={legal_enemy_taunt};plain_target={illegal_enemy_plain};"
        f"friendly_taunt_target={illegal_friendly};enemy_taunt={enemy_taunt.zone.name};"
        f"enemy_plain={enemy_plain.zone.name};friendly_taunt={friendly_taunt.zone.name}"
    )
    return observed, (
        legal_enemy_taunt and not illegal_enemy_plain and not illegal_friendly
        and enemy_taunt.zone == Zone.GRAVEYARD and enemy_plain in p2.field
        and friendly_taunt in p1.field and knight in p1.field
    )


def probe_ex1_004_young_priestess_random_other_minion_buff():
    winners = set()
    failures = []
    for seed in range(16):
        game = new_game()
        p1 = game.player1
        first, second = p1.summon("CS2_231"), p1.summon("CS2_231")
        priestess = p1.give("EX1_004")
        priestess.play()
        game.random.seed(seed)
        game.end_turn()
        changed = [i for i, unit in enumerate((first, second)) if unit.max_health == 2]
        if len(changed) == 1:
            winners.add(changed[0])
        if not (len(changed) == 1 and priestess.max_health == priestess.data.health):
            failures.append(seed)
    observed = f"seeds=0..15;selected_candidates={sorted(winners)};failures={failures};priestess_health={priestess.health}/{priestess.max_health}"
    return observed, winners == {0, 1} and not failures


def probe_ex1_005_big_game_hunter_seven_threshold():
    exactly_seven = new_game()
    p1, p2 = exactly_seven.player1, exactly_seven.player2
    seven = p2.summon("CS2_231")
    for _ in range(3):
        p1.give("CS2_188").play(target=seven)
    hunter = p1.give("EX1_005")
    seven_legal = seven in hunter.targets
    hunter.play(target=seven)
    seven_result = (seven.atk, seven.zone.name, hunter.zone.name)

    six_game = new_game()
    low = six_game.player2.summon("CS2_182")
    six_game.player1.give("CS2_188").play(target=low)
    low_hunter = six_game.player1.give("EX1_005")
    six_legal = low in low_hunter.targets
    observed = (
        f"seven_atk={seven.atk};seven_legal={seven_legal};seven_after={seven_result};"
        f"six_atk={low.atk};six_legal={six_legal};hunter_stays={low_hunter.zone.name}"
    )
    return observed, (
        seven_legal and seven_result == (7, "GRAVEYARD", "PLAY")
        and not six_legal and low.atk == 6 and low in six_game.player2.field
        and low_hunter.zone == Zone.HAND
    )


def probe_ex1_006_alarmobot_swaps_one_minion_at_turn_start():
    winners = set()
    failures = []
    for seed in range(16):
        game = new_game()
        p1 = game.player1
        bot = p1.give("EX1_006")
        bot.play()
        candidates = [p1.give("CS2_231"), p1.give("CS2_182")]
        game.random.seed(seed)
        game.end_turn()
        game.end_turn()
        pulled = [card.id for card in candidates if card in p1.field]
        if len(pulled) == 1:
            winners.add(pulled[0])
        if not (len(pulled) == 1 and bot in p1.hand and bot.zone == Zone.HAND):
            failures.append(seed)
    observed = f"seeds=0..15;pulled_ids={sorted(winners)};failures={failures};bot_zone={bot.zone.name}"
    return observed, winners == {"CS2_231", "CS2_182"} and not failures


def probe_ex1_008_argent_squire_divine_shield_absorbs_one_hit():
    game = new_game()
    p1, p2 = game.player1, game.player2
    squire = p1.give("EX1_008")
    squire.play()
    initial = (squire.health, squire.divine_shield)
    game.end_turn()
    first_spell = p2.give("CS2_008")
    first_spell.play(target=squire)
    after_first = (squire.health, squire.divine_shield, squire.zone.name)
    second_spell = p2.give("CS2_008")
    second_spell.play(target=squire)
    after_second = (squire.health, squire.divine_shield, squire.zone.name)
    observed = f"initial={initial};after_first={after_first};after_second={after_second}"
    return observed, (
        initial == (1, True) and after_first == (1, False, "PLAY")
        and after_second == (1, False, "GRAVEYARD")
    )


def probe_ex1_009_angry_chicken_enrage_tracks_damage_and_heal():
    game = new_game()
    p1, p2 = game.player1, game.player2
    chicken = p1.give("EX1_009")
    chicken.play()
    p1.give("CS2_004").play(target=chicken)
    while_healthy = (chicken.atk, chicken.health, chicken.max_health)
    game.end_turn()
    p2.give("CS2_008").play(target=chicken)
    while_damaged = (chicken.atk, chicken.health, chicken.max_health, chicken.enraged)
    game.end_turn()
    p1.give("CS2_007").play(target=chicken)
    after_heal = (chicken.atk, chicken.health, chicken.max_health, chicken.enraged)
    observed = f"healthy={while_healthy};damaged={while_damaged};healed={after_heal}"
    return observed, (
        while_healthy == (1, 3, 3) and while_damaged == (6, 2, 3, True)
        and after_heal == (1, 3, 3, False)
    )


def probe_ex1_010_worgen_stealth_expires_after_attack():
    game = new_game()
    p1, p2 = game.player1, game.player2
    worgen = p1.give("EX1_010")
    worgen.play()
    stealth_on_entry = bool(worgen.stealthed)
    game.end_turn()
    hidden_spell = p2.give("CS2_008")
    hidden_targetable = worgen in hidden_spell.targets
    game.end_turn()
    worgen.attack(p2.hero)
    no_longer_stealthed = not worgen.stealthed
    game.end_turn()
    exposed_spell = p2.give("CS2_008")
    exposed_targetable = worgen in exposed_spell.targets
    observed = (
        f"stealth_on_entry={stealth_on_entry};hidden_targetable={hidden_targetable};"
        f"after_attack_stealth={worgen.stealthed};after_attack_targetable={exposed_targetable};"
        f"enemy_hero={p2.hero.health};spell_zones={hidden_spell.zone.name}/{exposed_spell.zone.name}"
    )
    return observed, (
        stealth_on_entry and not hidden_targetable and no_longer_stealthed and exposed_targetable
        and p2.hero.health == 28 and hidden_spell.zone == Zone.HAND and exposed_spell.zone == Zone.HAND
    )


def probe_ex1_012_thalnos_spell_damage_and_deathrattle_draw():
    game = new_game()
    p1, p2 = game.player1, game.player2
    top = p1.card("CS2_182", zone=Zone.DECK)
    enemy = p2.summon("CS2_231")
    thalnos = p1.give("EX1_012")
    thalnos.play()
    power = int(thalnos.spellpower or 0)
    p1.give("CS2_008").play(target=enemy)
    enemy_after = (enemy.health, enemy.zone.name)
    thalnos.destroy()
    observed = (
        f"spell_damage={power};enemy={enemy_after};thalnos={thalnos.zone.name};"
        f"drawn={top.zone.name},in_hand={top in p1.hand};deck={len(p1.deck)}"
    )
    return observed, (
        power == 1 and enemy_after == (1, "GRAVEYARD")
        and thalnos.zone == Zone.GRAVEYARD and top.zone == Zone.HAND and top in p1.hand
    )


def probe_ex1_014_king_mukla_gives_two_bananas_to_opponent():
    game = new_game()
    p1, p2 = game.player1, game.player2
    own_hand_before = list(p1.hand)
    mukla = p1.give("EX1_014")
    mukla.play()
    bananas = [card for card in p2.hand if card.id == "EX1_014t"]
    observed = (
        f"opponent_hand={[f'{c.id}:{c.cost}:{c.zone.name}' for c in p2.hand]};"
        f"banana_count={len(bananas)};own_hand_delta={len(p1.hand)-len(own_hand_before)};mukla={mukla.zone.name}"
    )
    return observed, (
        len(bananas) == 2 and all(card.zone == Zone.HAND for card in bananas)
        and p1.hand == own_hand_before and mukla in p1.field
    )


def probe_ex1_017_jungle_panther_stealth_and_attack():
    game = new_game()
    p1, p2 = game.player1, game.player2
    panther = p1.give("EX1_017")
    panther.play()
    initially_stealthed = panther.stealthed
    game.end_turn()
    opponent_fireblast_targets = list(p2.hero.power.targets)
    legal_while_hidden = panther in opponent_fireblast_targets
    game.end_turn()
    panther.attack(p2.hero)
    observed = (
        f"stealth_on_entry={initially_stealthed};opponent_turn_hidden_target={legal_while_hidden};"
        f"stealth_after_attack={panther.stealthed};hero_health={p2.hero.health};attacks={panther.num_attacks}"
    )
    return observed, initially_stealthed and not legal_while_hidden and not panther.stealthed and p2.hero.health == 30 - panther.atk


def probe_ex1_020_scarlet_crusader_shield_absorbs_combat_hit():
    game = new_game()
    p1, p2 = game.player1, game.player2
    crusader = p1.give("EX1_020")
    crusader.play()
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    boar.attack(crusader)
    observed = (
        f"crusader={crusader.atk}/{crusader.health}/{crusader.max_health},"
        f"shield={crusader.divine_shield},zone={crusader.zone.name};"
        f"boar={boar.health}/{boar.zone.name}"
    )
    return observed, (
        crusader in p1.field and crusader.health == crusader.max_health
        and not crusader.divine_shield and boar.zone == Zone.GRAVEYARD
    )


def probe_ex1_021_thrallmar_farseer_windfury_attacks_twice():
    game = new_game()
    p1, p2 = game.player1, game.player2
    farseer = p1.give("EX1_021")
    farseer.play()
    game.end_turn()
    game.end_turn()
    ready = farseer.can_attack()
    start_health = p2.hero.health
    farseer.attack(p2.hero)
    after_first = (p2.hero.health, farseer.num_attacks, farseer.can_attack())
    farseer.attack(p2.hero)
    observed = (
        f"windfury={farseer.windfury};ready_after_sickness={ready};"
        f"first={after_first};second_hero_health={p2.hero.health};attacks={farseer.num_attacks}"
    )
    damage = farseer.atk
    return observed, (
        farseer.windfury and ready and after_first == (start_health - damage, 1, True)
        and p2.hero.health == start_health - 2 * damage and farseer.num_attacks == 2
    )


def probe_ex1_023_silvermoon_guardian_shield_in_combat():
    game = new_game()
    p1, p2 = game.player1, game.player2
    guardian = p1.give("EX1_023")
    guardian.play()
    original_health = guardian.health
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    boar_targets = list(boar.targets)
    can_attack_guardian = guardian in boar_targets
    boar.attack(guardian)
    observed = (
        f"guardian={guardian.atk}/{guardian.health}/{guardian.max_health};"
        f"initial_health={original_health};shield={guardian.divine_shield};"
        f"boar={boar.health}/{boar.zone.name};guardian_legal={can_attack_guardian}"
    )
    return observed, (
        can_attack_guardian and guardian.health == original_health
        and guardian in p1.field and not guardian.divine_shield
        and boar.zone == Zone.GRAVEYARD
    )


def probe_ex1_028_tiger_stealth_and_post_attack_targeting():
    game = new_game()
    p1, p2 = game.player1, game.player2
    tiger = p1.give("EX1_028")
    tiger.play()
    hidden_on_entry = bool(tiger.stealthed)
    game.end_turn()
    hidden_spell = p2.give("CS2_008")
    legal_while_hidden = tiger in hidden_spell.targets
    hidden_spell_zone = hidden_spell.zone.name
    game.end_turn()
    tiger.attack(p2.hero)
    stealth_after_attack = bool(tiger.stealthed)
    game.end_turn()
    exposed_spell = p2.give("CS2_008")
    legal_after_attack = tiger in exposed_spell.targets
    if legal_after_attack:
        exposed_spell.play(target=tiger)
    finishing_spells = []
    while tiger in p1.field and len(finishing_spells) < 4:
        spell = p2.give("CS2_008")
        if tiger not in spell.targets:
            break
        spell.play(target=tiger)
        finishing_spells.append(spell)
    observed = (
        f"stealth_on_entry={hidden_on_entry};opponent_hidden_targetable={legal_while_hidden};"
        f"hidden_spell={hidden_spell_zone};stealth_after_attack={stealth_after_attack};"
        f"opponent_targetable_after_attack={legal_after_attack};tiger={tiger.zone.name};"
        f"finishing_hits={len(finishing_spells)+1};hero_health={p2.hero.health}"
    )
    return observed, (
        hidden_on_entry and not legal_while_hidden and hidden_spell.zone == Zone.HAND
        and not stealth_after_attack and legal_after_attack and tiger.zone == Zone.GRAVEYARD
        and p2.hero.health == 30 - tiger.atk
    )


def probe_ex1_029_leper_gnome_deathrattle_hits_enemy_hero():
    game = new_game()
    p1, p2 = game.player1, game.player2
    gnome = p1.give("EX1_029")
    gnome.play()
    start_health = p2.hero.health
    game.end_turn()
    kill = p2.give("CS2_008")
    legal = gnome in kill.targets
    kill.play(target=gnome)
    observed = (
        f"enemy_can_target={legal};gnome={gnome.health}/{gnome.zone.name};"
        f"enemy_hero={start_health}->{p2.hero.health};kill_spell={kill.zone.name}"
    )
    return observed, (
        legal and gnome.zone == Zone.GRAVEYARD and p2.hero.health == start_health - 2
        and kill.zone == Zone.GRAVEYARD
    )


def probe_ex1_032_sunwalker_taunt_shield_combat():
    game = new_game()
    p1, p2 = game.player1, game.player2
    sunwalker = p1.give("EX1_032")
    sunwalker.play()
    start_health = sunwalker.health
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    legal_targets = list(boar.targets)
    taunt_target_legal = sunwalker in legal_targets
    hero_target_legal = p1.hero in legal_targets
    boar.attack(sunwalker)
    observed = (
        f"taunt={sunwalker.taunt};shield={sunwalker.divine_shield};"
        f"boar_can_attack_sunwalker={taunt_target_legal};boar_can_attack_hero={hero_target_legal};"
        f"sunwalker={sunwalker.health}/{sunwalker.max_health}/{sunwalker.zone.name};boar={boar.zone.name}"
    )
    return observed, (
        sunwalker.taunt and sunwalker.divine_shield is False and taunt_target_legal
        and not hero_target_legal and sunwalker.health == start_health
        and sunwalker in p1.field and boar.zone == Zone.GRAVEYARD
    )


def probe_ex1_033_windfury_harpy_two_attacks():
    game = new_game()
    p1, p2 = game.player1, game.player2
    harpy = p1.give("EX1_033")
    harpy.play()
    game.end_turn()
    game.end_turn()
    can_attack_after_sickness = harpy.can_attack()
    damage = harpy.atk
    starting_health = p2.hero.health
    harpy.attack(p2.hero)
    after_first = (p2.hero.health, harpy.num_attacks, harpy.can_attack())
    harpy.attack(p2.hero)
    observed = (
        f"windfury={harpy.windfury};ready={can_attack_after_sickness};"
        f"first={after_first};second_hero_health={p2.hero.health};attacks={harpy.num_attacks}"
    )
    return observed, (
        harpy.windfury and can_attack_after_sickness
        and after_first == (starting_health - damage, 1, True)
        and p2.hero.health == starting_health - 2 * damage and harpy.num_attacks == 2
    )


def probe_ex1_043_twilight_drake_counts_other_hand_cards():
    game = new_game()
    p1 = game.player1
    p1.give("CS2_008")
    p1.give("CS2_231")
    p1.give("CS2_182")
    drake = p1.give("EX1_043")
    other_cards = [card for card in p1.hand if card is not drake]
    expected_bonus = len(other_cards)
    drake.play()
    observed = (
        f"other_cards_before_play={expected_bonus};remaining_hand={len(p1.hand)};"
        f"drake={drake.atk}/{drake.health}/{drake.max_health};zone={drake.zone.name}"
    )
    return observed, (
        drake in p1.field and drake.max_health == drake.data.health + expected_bonus
        and drake.health == drake.max_health and len(p1.hand) == expected_bonus
    )


def probe_ex1_044_questing_adventurer_own_card_triggers_only():
    game = new_game()
    p1, p2 = game.player1, game.player2
    adventurer = p1.give("EX1_044")
    adventurer.play()
    base_stats = (adventurer.atk, adventurer.health, adventurer.max_health)
    p1.give("CS2_008").play(target=p2.hero)
    after_spell = (adventurer.atk, adventurer.health, adventurer.max_health)
    wisp = p1.give("CS2_231")
    wisp.play()
    after_minion = (adventurer.atk, adventurer.health, adventurer.max_health)
    game.end_turn()
    enemy_spell = p2.give("CS2_008")
    enemy_spell.play(target=p1.hero)
    after_enemy_card = (adventurer.atk, adventurer.health, adventurer.max_health)
    observed = (
        f"base={base_stats};after_own_spell={after_spell};after_own_minion={after_minion};"
        f"after_enemy_spell={after_enemy_card};wisp={wisp.zone.name};spell_zones={enemy_spell.zone.name}"
    )
    return observed, (
        base_stats == (2, 2, 2) and after_spell == (3, 3, 3)
        and after_minion == (4, 4, 4) and after_enemy_card == after_minion
        and adventurer in p1.field and wisp in p1.field and enemy_spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_045_ancient_watcher_silence_enables_attack():
    game = new_game()
    p1, p2 = game.player1, game.player2
    watcher = p1.give("EX1_045")
    watcher.play()
    initial_can_attack = watcher.can_attack()
    initial_targets = list(watcher.targets)
    game.end_turn()
    game.end_turn()
    still_cannot_attack = watcher.can_attack()
    silence = p1.give("EX1_048")
    legal_silence_target = watcher in silence.targets
    silence.play(target=watcher)
    can_attack_after_silence = watcher.can_attack()
    watcher.attack(p2.hero)
    observed = (
        f"initial_can_attack={initial_can_attack};initial_targets={[getattr(t, 'id', 'HERO') for t in initial_targets]};"
        f"still_cannot_attack_next_turn={still_cannot_attack};silence_target_legal={legal_silence_target};"
        f"after_silence_can_attack={can_attack_after_silence};hero_health={p2.hero.health};"
        f"watcher={watcher.atk}/{watcher.health}/{watcher.zone.name}"
    )
    return observed, (
        not initial_can_attack and not still_cannot_attack
        and legal_silence_target and can_attack_after_silence
        and p2.hero.health == 30 - watcher.atk and watcher in p1.field
        and silence in p1.field
    )


def probe_ex1_046_dark_iron_dwarf_friendly_target_expires():
    game = new_game()
    p1, p2 = game.player1, game.player2
    target = p1.summon("CS2_231")
    game.end_turn()
    game.end_turn()
    dwarf = p1.give("EX1_046")
    target_legal = target in dwarf.targets
    dwarf.play(target=target)
    buffed_attack = target.atk
    can_attack_with_buff = target.can_attack()
    target.attack(p2.hero)
    damage_dealt = 30 - p2.hero.health
    game.end_turn()
    attack_after_turn = target.atk
    observed = (
        f"friendly_target_legal={target_legal};buffed_attack={buffed_attack};"
        f"can_attack_with_buff={can_attack_with_buff};damage_dealt={damage_dealt};"
        f"attack_after_controller_turn={attack_after_turn};dwarf={dwarf.zone.name}"
    )
    return observed, (
        target_legal and buffed_attack == 3 and can_attack_with_buff and damage_dealt == 3
        and attack_after_turn == 1 and dwarf in p1.field
    )


def probe_ex1_046_dark_iron_dwarf_enemy_target_domain_and_expiry():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_231")
    enemy = p2.summon("CS2_182")
    dwarf = p1.give("EX1_046")
    friendly_legal = friendly in dwarf.targets
    enemy_legal = enemy in dwarf.targets
    dwarf.play(target=enemy)
    buffed_attack = enemy.atk
    game.end_turn()
    attack_after_turn = enemy.atk
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"enemy_attack_during_controller_turn={buffed_attack};after_expiry={attack_after_turn};"
        f"enemy_still_in_play={enemy in p2.field}"
    )
    return observed, (
        friendly_legal and enemy_legal and buffed_attack == 6 and attack_after_turn == 4
        and enemy in p2.field and dwarf in p1.field
    )


def probe_ex1_055_mana_addict_own_spells_and_turn_expiry():
    game = new_game()
    p1, p2 = game.player1, game.player2
    addict = p1.give("EX1_055")
    addict.play()
    base_attack = addict.atk
    p1.give("CS2_008").play(target=p2.hero)
    after_first_spell = addict.atk
    p1.give("CS2_008").play(target=p2.hero)
    after_second_spell = addict.atk
    game.end_turn()
    after_own_turn = addict.atk
    enemy_spell = p2.give("CS2_008")
    enemy_spell.play(target=p1.hero)
    after_enemy_spell = addict.atk
    observed = (
        f"base={base_attack};after_own_spells={after_first_spell}/{after_second_spell};"
        f"after_controller_turn={after_own_turn};after_enemy_spell={after_enemy_spell};"
        f"enemy_spell={enemy_spell.zone.name}"
    )
    return observed, (
        base_attack == 1 and after_first_spell == 3 and after_second_spell == 5
        and after_own_turn == 1 and after_enemy_spell == 1
        and enemy_spell.zone == Zone.GRAVEYARD and addict in p1.field
    )


def probe_ex1_057_ancient_brewmaster_friendly_target_and_bounce():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    friendly.set_current_health(2)
    enemy = p2.summon("CS2_182")
    brew = p1.give("EX1_057")
    friendly_legal = friendly in brew.targets
    enemy_legal = enemy in brew.targets
    brew.play(target=friendly)
    bounced_state = (friendly.zone.name, friendly in p1.hand, friendly.health, friendly.max_health)
    if friendly in p1.hand:
        friendly.play()
    replay_state = (friendly.zone.name, friendly.health, friendly.max_health)
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"bounced={bounced_state};replayed={replay_state};enemy_stays={enemy in p2.field}"
    )
    return observed, (
        friendly_legal and not enemy_legal and bounced_state[0] == "HAND"
        and bounced_state[1] and replay_state == ("PLAY", 5, 5)
        and enemy in p2.field and brew in p1.field
    )


def probe_ex1_058_sunfury_protector_adjacent_minions_only():
    game = new_game()
    p1 = game.player1
    left = p1.summon("CS2_231")
    right = p1.summon("CS2_231")
    far = p1.summon("CS2_231")
    protector = p1.give("EX1_058")
    protector.play(index=1)
    board = list(p1.field)
    observed = (
        f"board_order={[unit.id for unit in board]};positions="
        f"left={board.index(left)},protector={board.index(protector)},right={board.index(right)},far={board.index(far)};"
        f"taunts=left:{left.taunt},right:{right.taunt},far:{far.taunt},self:{protector.taunt}"
    )
    return observed, (
        board.index(protector) == 1 and board.index(left) == 0
        and board.index(right) == 2 and board.index(far) == 3
        and left.taunt and right.taunt and not far.taunt and not protector.taunt
    )


def probe_ex1_059_crazed_alchemist_friendly_and_enemy_targets():
    observations = []
    outcomes = []
    for side in ("friendly", "enemy"):
        game = new_game()
        caster = game.player1
        owner = game.player1 if side == "friendly" else game.player2
        target = owner.summon("CS2_182")
        alchemist = caster.give("EX1_059")
        legal = target in alchemist.targets
        alchemist.play(target=target)
        stats = (target.atk, target.health, target.max_health)
        observations.append(f"{side}_legal={legal};after_swap={stats};zone={target.zone.name}")
        outcomes.append(legal and stats == (5, 4, 4) and target in owner.field)
    observed = ";".join(observations)
    return observed, all(outcomes)


def probe_ex1_067_argent_commander_charge_and_shield_combat():
    game = new_game()
    p1, p2 = game.player1, game.player2
    commander = p1.give("EX1_067")
    commander.play()
    can_attack_immediately = commander.can_attack()
    enemy = p2.summon("CS2_182")
    enemy_start = enemy.health
    target_legal = enemy in commander.targets
    commander.attack(enemy)
    observed = (
        f"charge={commander.charge};immediate_attack={can_attack_immediately};"
        f"target_legal={target_legal};enemy={enemy.health}/{enemy.max_health}/{enemy.zone.name};"
        f"commander={commander.health}/{commander.max_health};shield={commander.divine_shield};"
        f"commander_attacks={commander.num_attacks}"
    )
    return observed, (
        commander.charge and can_attack_immediately and target_legal
        and enemy.health == enemy_start - commander.atk and enemy in p2.field
        and commander in p1.field and commander.health == commander.max_health
        and not commander.divine_shield and commander.num_attacks == 1
    )


def probe_ex1_076_pint_sized_summoner_first_minion_discount():
    game = new_game()
    p1 = game.player1
    summoner = p1.summon("EX1_076")
    first = p1.give("CS2_182")
    second = p1.give("CS2_182")
    spell = p1.give("CS2_008")
    first_cost, second_cost, spell_cost = first.cost, second.cost, spell.cost
    first.play()
    after_first = (second.cost, spell.cost, p1.minions_played_this_turn)
    game.end_turn()
    game.end_turn()
    next_turn_cost = second.cost
    observed = (
        f"first_minion_cost={first_cost};second_minion_same_turn={second_cost};spell_cost={spell_cost};"
        f"after_first_play={after_first};next_controller_turn_second_cost={next_turn_cost};"
        f"summoner={summoner.zone.name}"
    )
    return observed, (
        first_cost == 3 and second_cost == 3 and spell_cost == 0
        and after_first == (4, 0, 1) and next_turn_cost == 3
        and summoner in p1.field and first in p1.field
    )


def probe_ex1_080_secretkeeper_triggers_on_secrets_from_both_players():
    game = new_game()
    p1, p2 = game.player1, game.player2
    keeper = p1.give("EX1_080")
    keeper.play()
    base = (keeper.atk, keeper.health, keeper.max_health)
    own_secret = p1.give("EX1_289")
    own_secret.play()
    after_own = (keeper.atk, keeper.health, keeper.max_health)
    game.end_turn()
    enemy_secret = p2.give("EX1_289")
    enemy_secret.play()
    after_enemy = (keeper.atk, keeper.health, keeper.max_health)
    observed = (
        f"base={base};after_friendly_secret={after_own};after_enemy_secret={after_enemy};"
        f"secret_zones={own_secret.zone.name}/{enemy_secret.zone.name};keeper={keeper.zone.name}"
    )
    return observed, (
        base == (1, 2, 2) and after_own == (2, 3, 3)
        and after_enemy == (3, 4, 4) and own_secret in p1.secrets
        and enemy_secret in p2.secrets and keeper in p1.field
    )


def probe_ex1_082_mad_bomber_three_random_hits_other_characters():
    coverage = set()
    failures = []
    totals = []
    for seed in range(32):
        game = new_game()
        p1, p2 = game.player1, game.player2
        friends = [p1.summon("CS2_182"), p1.summon("CS2_182")]
        enemies = [p2.summon("CS2_182"), p2.summon("CS2_182")]
        bomber = p1.give("EX1_082")
        game.random.seed(seed)
        bomber.play()
        characters = [p1.hero, p2.hero, *friends, *enemies]
        damage = [int(character.damage) for character in characters]
        targets_hit = [index for index, amount in enumerate(damage) if amount]
        coverage.update(targets_hit)
        totals.append(sum(damage))
        if (sum(damage) != 3 or bomber.damage != 0 or bomber not in p1.field
                or any(minion not in owner.field for minion, owner in
                       [(friends[0], p1), (friends[1], p1), (enemies[0], p2), (enemies[1], p2)])):
            failures.append(seed)
    observed = (
        f"seeds=0..31;all_damage_totals={sorted(set(totals))};target_indexes_seen={sorted(coverage)};"
        f"expected_target_indexes=0..5;failures={failures};bomber_damage=0"
    )
    return observed, coverage == set(range(6)) and not failures


def probe_ex1_083_tinkmaster_random_target_and_transform_options():
    coverage = set()
    failures = []
    transformations = set()
    for seed in range(64):
        game = new_game()
        p1, p2 = game.player1, game.player2
        friendly = p1.summon("CS2_231")
        enemy = p2.summon("CS2_231")
        tink = p1.give("EX1_083")
        game.random.seed(seed)
        tink.play()
        forms = ("EX1_tk28", "EX1_tk29")
        friendly_form = next((m for m in p1.field if m.id in forms), None)
        enemy_form = next((m for m in p2.field if m.id in forms), None)
        if friendly_form and not enemy_form:
            coverage.add("friendly")
            transformed = friendly_form
            original_other = enemy
            original_changed = friendly
        elif enemy_form and not friendly_form:
            coverage.add("enemy")
            transformed = enemy_form
            original_other = friendly
            original_changed = enemy
        else:
            failures.append((seed, "no_candidate_transformed"))
            continue
        transformations.add(transformed.id)
        valid_form = (
            (transformed.id == "EX1_tk28" and (transformed.atk, transformed.health) == (1, 1))
            or (transformed.id == "EX1_tk29" and (transformed.atk, transformed.health) == (5, 5))
        )
        other_owner = p1.field if original_other is friendly else p2.field
        changed_owner = p1.field if original_changed is friendly else p2.field
        if (original_other not in other_owner or original_changed in changed_owner
                or not valid_form or tink not in p1.field):
            failures.append((seed, f"friendly_form={getattr(friendly_form,'id',None)};"
                                   f"enemy_form={getattr(enemy_form,'id',None)};transformed={transformed.id}"))
    observed = (
        f"seeds=0..63;target_sides_seen={sorted(coverage)};forms_seen={sorted(transformations)};"
        f"expected_sides=['enemy','friendly'];expected_forms=['EX1_tk28','EX1_tk29'];failures={failures}"
    )
    return observed, coverage == {"friendly", "enemy"} and transformations == {"EX1_tk28", "EX1_tk29"} and not failures


def probe_ex1_089_arcane_golem_grants_opponent_crystal():
    game = new_game()
    p1, p2 = game.player1, game.player2
    p1.max_mana = 10
    p2.max_mana = 3
    before = (p1.max_mana, p2.max_mana)
    golem = p1.give("EX1_089")
    golem.play()
    after = (p1.max_mana, p2.max_mana)
    observed = f"max_mana_before={before};after={after};golem={golem.zone.name}"
    return observed, after == (10, 4) and golem in p1.field


def probe_ex1_091_cabal_shadow_priest_steals_only_enemy_minion_with_two_attack():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_231")
    eligible = p2.summon("CS2_231")
    ineligible = p2.summon("CS2_231")
    p1.give("CS2_188").play(target=ineligible)
    priest = p1.give("EX1_091")
    friendly_legal = friendly in priest.targets
    eligible_legal = eligible in priest.targets
    three_attack_legal = ineligible in priest.targets
    priest.play(target=eligible)
    observed = (
        f"friendly_legal={friendly_legal};enemy_2_attack_legal={eligible_legal};"
        f"enemy_3_attack_legal={three_attack_legal};stolen_owner={eligible.controller};"
        f"p1_field={[m.id for m in p1.field]};p2_field={[m.id for m in p2.field]};"
        f"other_enemy={ineligible.atk}/{ineligible.zone.name}"
    )
    return observed, (
        not friendly_legal and eligible_legal and not three_attack_legal
        and eligible in p1.field and eligible not in p2.field and ineligible in p2.field
        and ineligible.atk == 3 and priest in p1.field
    )


def probe_ex1_093_defender_of_argus_buffs_exact_adjacent_positions():
    game = new_game()
    p1 = game.player1
    left = p1.summon("CS2_231")
    right = p1.summon("CS2_231")
    far = p1.summon("CS2_231")
    defender = p1.give("EX1_093")
    defender.play(index=1)
    board = list(p1.field)
    states = [(m.atk, m.health, m.max_health, bool(m.taunt)) for m in (left, right, far, defender)]
    observed = (
        f"board={[m.id for m in board]};positions={[board.index(m) for m in (left, defender, right, far)]};"
        f"left_right_far_defender={states}"
    )
    return observed, (
        [board.index(m) for m in (left, defender, right, far)] == [0, 1, 2, 3]
        and states == [(2, 2, 2, True), (2, 2, 2, True), (1, 1, 1, False), (2, 3, 3, False)]
    )


def probe_ex1_095_gadgetzan_auctioneer_draws_for_own_spell():
    game = new_game()
    p1, p2 = game.player1, game.player2
    p1.card("CS2_182", zone=Zone.DECK)
    p1.card("CS2_231", zone=Zone.DECK)
    expected_top, expected_next = list(p1.deck)[-1], list(p1.deck)[-2]
    auctioneer = p1.give("EX1_095")
    auctioneer.play()
    spell = p1.give("CS2_008")
    spell.play(target=p2.hero)
    after_own = (expected_top in p1.hand, expected_next in p1.deck, spell.zone.name)
    game.end_turn()
    opponent_spell = p2.give("CS2_008")
    opponent_spell.play(target=p1.hero)
    after_enemy = (expected_next in p1.hand, expected_next in p1.deck, opponent_spell.zone.name)
    observed = (
        f"expected_draw_order={[expected_top.id, expected_next.id]};"
        f"after_own_spell={after_own};after_enemy_spell={after_enemy};"
        f"auctioneer={auctioneer.zone.name};hand={[card.id for card in p1.hand]}"
    )
    return observed, (
        after_own == (True, True, "GRAVEYARD")
        and after_enemy == (False, True, "GRAVEYARD") and auctioneer in p1.field
    )


def probe_ex1_096_loot_hoarder_deathrattle_draws_its_owners_card():
    game = new_game()
    p1, p2 = game.player1, game.player2
    top = p1.card("CS2_182", zone=Zone.DECK)
    hoarder = p1.give("EX1_096")
    hoarder.play()
    game.end_turn()
    kill = p2.give("CS2_008")
    target_legal = hoarder in kill.targets
    kill.play(target=hoarder)
    observed = (
        f"enemy_can_target={target_legal};hoarder={hoarder.zone.name};drawn_top={top.zone.name};"
        f"owner_hand_contains_top={top in p1.hand};killer_spell={kill.zone.name}"
    )
    return observed, (
        target_legal and hoarder.zone == Zone.GRAVEYARD and top in p1.hand
        and top.zone == Zone.HAND and kill.zone == Zone.GRAVEYARD
    )


def probe_ex1_097_abomination_deathrattle_hits_all_and_resolves_other_deathrattles():
    game = new_game()
    p1, p2 = game.player1, game.player2
    p1.hero.damage = 5
    p2.hero.damage = 5
    p1_draw = p1.card("CS2_231", zone=Zone.DECK)
    p2_draw = p2.card("CS2_182", zone=Zone.DECK)
    abomination = p1.give("EX1_097")
    abomination.play()
    friendly_hoarder = p1.give("EX1_096")
    friendly_hoarder.play()
    friendly_yeti = p1.summon("CS2_182")
    enemy_hoarder = p2.summon("EX1_096")
    enemy_yeti = p2.summon("CS2_182")
    start_heroes = (p1.hero.health, p2.hero.health)
    game.end_turn()
    for _ in range(4):
        kill = p2.give("CS2_008")
        kill.play(target=abomination)
    observed = (
        f"taunt={abomination.taunt};abomination={abomination.zone.name};"
        f"heroes={start_heroes}->{(p1.hero.health, p2.hero.health)};"
        f"friendly_hoarder={friendly_hoarder.zone.name},draw={p1_draw.zone.name};"
        f"enemy_hoarder={enemy_hoarder.zone.name},draw={p2_draw.zone.name};"
        f"yetis={friendly_yeti.health}/{friendly_yeti.zone.name},{enemy_yeti.health}/{enemy_yeti.zone.name}"
    )
    return observed, (
        abomination.taunt and abomination.zone == Zone.GRAVEYARD
        and (p1.hero.health, p2.hero.health) == (start_heroes[0] - 2, start_heroes[1] - 2)
        and friendly_hoarder.zone == Zone.GRAVEYARD and enemy_hoarder.zone == Zone.GRAVEYARD
        and p1_draw in p1.hand and p2_draw in p2.hand
        and (friendly_yeti.health, enemy_yeti.health) == (3, 3)
        and friendly_yeti in p1.field and enemy_yeti in p2.field
    )


def probe_ex1_100_lorewalker_cho_copies_each_players_spell_to_other_hand():
    game = new_game()
    p1, p2 = game.player1, game.player2
    cho = p1.give("EX1_100")
    cho.play()
    p1_spell = p1.give("CS2_008")
    p1_spell.play(target=p2.hero)
    copy_for_p2 = [card for card in p2.hand if card.id == "CS2_008"]
    after_p1 = (p1_spell.zone.name, len(copy_for_p2), copy_for_p2[0].zone.name if copy_for_p2 else "missing")
    game.end_turn()
    p2_spell = p2.give("CS2_008")
    p2_spell.play(target=p1.hero)
    copy_for_p1 = [card for card in p1.hand if card.id == "CS2_008"]
    after_p2 = (p2_spell.zone.name, len(copy_for_p1), copy_for_p1[0].zone.name if copy_for_p1 else "missing")
    observed = (
        f"after_p1_cast={after_p1};after_p2_cast={after_p2};"
        f"copy_controllers={copy_for_p2[0].controller if copy_for_p2 else 'missing'}/"
        f"{copy_for_p1[0].controller if copy_for_p1 else 'missing'};cho={cho.zone.name}"
    )
    return observed, (
        after_p1 == ("GRAVEYARD", 1, "HAND") and after_p2 == ("GRAVEYARD", 1, "HAND")
        and copy_for_p2[0].controller is p2 and copy_for_p1[0].controller is p1
        and cho in p1.field
    )


def probe_ex1_102_demolisher_start_of_turn_hits_random_enemy():
    coverage = set()
    failures = []
    for seed in range(32):
        game = new_game()
        p1, p2 = game.player1, game.player2
        demolisher = p1.give("EX1_102")
        demolisher.play()
        enemies = [p2.summon("CS2_182"), p2.summon("CS2_182")]
        friendly = p1.summon("CS2_182")
        game.random.seed(seed)
        game.end_turn()
        game.end_turn()
        damage = [int(enemy.damage) for enemy in enemies]
        enemy_hero_damage = int(p2.hero.damage)
        hits = [i for i, amount in enumerate(damage) if amount == 2]
        if hits:
            coverage.add(f"minion_{hits[0]}")
        if enemy_hero_damage >= 2:
            coverage.add("hero")
        if (sum(damage) + enemy_hero_damage != 2 or friendly.damage != 0
                or demolisher.damage != 0 or demolisher not in p1.field):
            failures.append((seed, f"enemy_damage={damage};hero={enemy_hero_damage}"))
    observed = (
        f"seeds=0..31;enemy_targets_seen={sorted(coverage)};expected=['hero','minion_0','minion_1'];"
        f"failures={failures}"
    )
    return observed, coverage == {"hero", "minion_0", "minion_1"} and not failures


def probe_ex1_103_coldlight_seer_buffs_only_other_friendly_murlocs():
    game = new_game()
    p1, p2 = game.player1, game.player2
    wounded_murloc = p1.summon("EX1_509")
    wounded_murloc.set_current_health(1)
    healthy_murloc = p1.summon("EX1_509")
    friendly_non_murloc = p1.summon("CS2_231")
    enemy_murloc = p2.summon("EX1_509")
    before = [(m.health, m.max_health) for m in (wounded_murloc, healthy_murloc, friendly_non_murloc, enemy_murloc)]
    seer = p1.give("EX1_103")
    seer.play()
    after = [(m.health, m.max_health) for m in (wounded_murloc, healthy_murloc, friendly_non_murloc, enemy_murloc)]
    observed = f"before={before};after={after};seer={seer.health}/{seer.max_health}/{seer.zone.name}"
    return observed, (
        before == [(1, 2), (2, 2), (1, 1), (2, 2)]
        and after == [(3, 4), (4, 4), (1, 1), (2, 2)]
        and (seer.health, seer.max_health) == (3, 3)
        and all(m in owner.field for m, owner in [
            (wounded_murloc, p1), (healthy_murloc, p1), (friendly_non_murloc, p1), (enemy_murloc, p2), (seer, p1)
        ])
    )


def probe_ex1_110_cairne_deathrattle_summons_baine():
    game = new_game()
    p1, p2 = game.player1, game.player2
    cairne = p1.give("EX1_110")
    cairne.play()
    game.end_turn()
    destroy = p2.give("CS2_076")
    legal_target = cairne in destroy.targets
    destroy.play(target=cairne)
    baine = [minion for minion in p1.field if minion.id == "EX1_110t"]
    observed = (
        f"enemy_target_legal={legal_target};cairne={cairne.zone.name};"
        f"baine_count={len(baine)};baine_stats={[(m.atk,m.health,m.max_health,m.zone.name) for m in baine]};"
        f"destroy_spell={destroy.zone.name}"
    )
    return observed, (
        legal_target and cairne.zone == Zone.GRAVEYARD and len(baine) == 1
        and (baine[0].atk, baine[0].health, baine[0].max_health) == (4, 5, 5)
        and destroy.zone == Zone.GRAVEYARD
    )


def probe_ex1_124_eviscerate_normal_branch_and_target_domain():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    spell = p1.give("EX1_124")
    friendly_legal = friendly in spell.targets
    enemy_legal = enemy in spell.targets
    no_combo = bool(p1.combo)
    spell.play(target=enemy)
    observed = (
        f"combo_before={no_combo};friendly_target_legal={friendly_legal};enemy_target_legal={enemy_legal};"
        f"enemy_health={enemy.health}/{enemy.max_health};spell={spell.zone.name};combo_after={p1.combo}"
    )
    return observed, (
        not no_combo and friendly_legal and enemy_legal and enemy.health == 3
        and enemy.max_health == 5 and spell.zone == Zone.GRAVEYARD and p1.combo
    )


def probe_ex1_124_eviscerate_combo_branch_deals_four():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    p1.give("CS2_008").play(target=p2.hero)
    spell = p1.give("EX1_124")
    friendly_legal = friendly in spell.targets
    enemy_legal = enemy in spell.targets
    combo_before = bool(p1.combo)
    spell.play(target=friendly)
    observed = (
        f"combo_before={combo_before};friendly_target_legal={friendly_legal};enemy_target_legal={enemy_legal};"
        f"friendly_health={friendly.health}/{friendly.max_health}/{friendly.zone.name};"
        f"enemy_health={enemy.health}/{enemy.max_health};spell={spell.zone.name}"
    )
    return observed, (
        combo_before and friendly_legal and enemy_legal and friendly.health == 1
        and friendly.max_health == 5 and friendly in p1.field and enemy.health == 5
        and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_126_betrayal_damages_only_enemy_targets_adjacent_minions():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    left = p2.summon("CS2_231")
    target = p2.summon("CS2_182")
    right = p2.summon("CS2_182")
    far = p2.summon("CS2_182")
    left.set_current_health(2)
    spell = p1.give("EX1_126")
    friendly_legal = friendly in spell.targets
    enemy_legal = target in spell.targets
    hero_legal = p2.hero in spell.targets
    spell.play(target=target)
    observed = (
        f"friendly_legal={friendly_legal};enemy_minion_legal={enemy_legal};hero_legal={hero_legal};"
        f"left={left.health}/{left.zone.name};target={target.health}/{target.zone.name};"
        f"right={right.health}/{right.zone.name};far={far.health}/{far.zone.name};"
        f"friendly={friendly.health}/{friendly.zone.name};spell={spell.zone.name}"
    )
    return observed, (
        not friendly_legal and enemy_legal and not hero_legal
        and left.zone == Zone.GRAVEYARD and target.health == 5 and target in p2.field
        and right.health == 1 and right in p2.field and far.health == 5 and far in p2.field
        and friendly.health == 5 and friendly in p1.field and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_130_noble_sacrifice_redirects_enemy_attack():
    game = new_game()
    p1, p2 = game.player1, game.player2
    secret = p1.give("EX1_130")
    secret.play()
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    hero_target_legal = p1.hero in boar.targets
    starting_health = p1.hero.health
    boar.attack(p1.hero)
    defender = [card for card in p1.graveyard if card.id == "EX1_130a"]
    observed = (
        f"hero_was_legal={hero_target_legal};secret={secret.zone.name};"
        f"hero={starting_health}->{p1.hero.health};boar={boar.health}/{boar.zone.name};"
        f"defender_graveyard_count={len(defender)};p1_field={[m.id for m in p1.field]}"
    )
    return observed, (
        hero_target_legal and secret.zone == Zone.GRAVEYARD
        and p1.hero.health == starting_health and boar.zone == Zone.GRAVEYARD
        and len(defender) == 1 and defender[0].atk == 2
    )


def probe_ex1_130_noble_sacrifice_dormant_full_board_stays_set():
    game = new_game()
    p1, p2 = game.player1, game.player2
    dormant = p1.give("BT_258")
    dormant.play()
    for _ in range(6):
        p1.summon("CS2_231")
    field_before = len(p1.field)
    secret = p1.give("EX1_130")
    secret.play()
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    hero_legal = p1.hero in boar.targets
    boar.attack(p1.hero)
    defenders = [minion for minion in p1.field if minion.id == "EX1_130a"]
    observed = (
        f"field_before={field_before};dormant={dormant.dormant};hero_legal={hero_legal};"
        f"secret_after_attack={secret.zone.name},still_set={secret in p1.secrets};"
        f"hero_health={p1.hero.health};field_after={len(p1.field)};defenders={len(defenders)};"
        f"attacker={boar.zone.name}"
    )
    return observed, (
        field_before == 7 and dormant.dormant and hero_legal
        and secret in p1.secrets and boar.zone == Zone.PLAY
        and p1.hero.health == 29 and len(p1.field) == 7 and not defenders
    )


def probe_ex1_131_defias_ringleader_without_combo():
    game = new_game()
    p1 = game.player1
    leader = p1.give("EX1_131")
    combo_before = bool(p1.combo)
    leader.play()
    tokens = [m for m in p1.field if m.id == "EX1_131t"]
    observed = f"combo_before={combo_before};leader={leader.atk}/{leader.health}/{leader.zone.name};bandits={len(tokens)}"
    return observed, not combo_before and leader in p1.field and (leader.atk, leader.health) == (2, 2) and not tokens


def probe_ex1_131_defias_ringleader_combo_summons_bandit():
    game = new_game()
    p1, p2 = game.player1, game.player2
    p1.give("CS2_008").play(target=p2.hero)
    leader = p1.give("EX1_131")
    combo_before = bool(p1.combo)
    leader.play()
    tokens = [m for m in p1.field if m.id == "EX1_131t"]
    token_stats = [(m.atk, m.health, m.zone.name) for m in tokens]
    observed = (
        f"combo_before={combo_before};leader={leader.atk}/{leader.health};"
        f"token_count={len(tokens)};token_stats={token_stats};field={[m.id for m in p1.field]}"
    )
    return observed, (
        combo_before and leader in p1.field and (leader.atk, leader.health) == (2, 2)
        and len(tokens) == 1 and token_stats == [(2, 1, "PLAY")]
    )


def probe_ex1_132_eye_for_an_eye_reflects_exact_hero_damage():
    game = new_game()
    p1, p2 = game.player1, game.player2
    secret = p1.give("EX1_132")
    secret.play()
    game.end_turn()
    fireball = p2.give("CS2_029")
    target_legal = p1.hero in fireball.targets
    fireball.play(target=p1.hero)
    observed = (
        f"target_legal={target_legal};friendly_hero={p1.hero.health};enemy_hero={p2.hero.health};"
        f"secret={secret.zone.name};fireball={fireball.zone.name}"
    )
    return observed, (
        target_legal and p1.hero.health == 24 and p2.hero.health == 24
        and secret.zone == Zone.GRAVEYARD and fireball.zone == Zone.GRAVEYARD
    )


def probe_ex1_133_perditions_blade_normal_battlecry_deals_one():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    blade = p1.give("EX1_133")
    friendly_legal = friendly in blade.targets
    enemy_legal = enemy in blade.targets
    combo_before = bool(p1.combo)
    blade.play(target=enemy)
    observed = (
        f"combo_before={combo_before};friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"enemy_health={enemy.health}/{enemy.max_health};weapon={p1.weapon.id if p1.weapon else None};"
        f"durability={blade.durability};blade={blade.zone.name}"
    )
    return observed, (
        not combo_before and friendly_legal and enemy_legal and enemy.health == 4
        and enemy in p2.field and p1.weapon is blade and blade.durability == 2
    )


def probe_ex1_133_perditions_blade_combo_battlecry_deals_two():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    p1.give("CS2_008").play(target=p2.hero)
    blade = p1.give("EX1_133")
    friendly_legal = friendly in blade.targets
    enemy_legal = enemy in blade.targets
    combo_before = bool(p1.combo)
    blade.play(target=friendly)
    observed = (
        f"combo_before={combo_before};friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"friendly_health={friendly.health}/{friendly.max_health};enemy_health={enemy.health};"
        f"weapon={p1.weapon.id if p1.weapon else None};durability={blade.durability}"
    )
    return observed, (
        combo_before and friendly_legal and enemy_legal and friendly.health == 3
        and friendly.max_health == 5 and enemy.health == 5
        and p1.weapon is blade and blade.durability == 2
    )


def probe_ex1_137_headcrack_normal_does_not_return():
    game = new_game()
    p1, p2 = game.player1, game.player2
    spell = p1.give("EX1_137")
    combo_before = bool(p1.combo)
    spell.play()
    after_play = (p2.hero.health, spell.zone.name, any(card.id == spell.id for card in p1.hand))
    game.end_turn()
    after_own_turn_end = any(card.id == spell.id for card in p1.hand)
    game.end_turn()
    after_next_turn_start = any(card.id == spell.id for card in p1.hand)
    observed = (
        f"combo_before={combo_before};after_play={after_play};"
        f"returned_at_own_end={after_own_turn_end};returned_after_full_turn_cycle={after_next_turn_start};"
        f"spell_zone={spell.zone.name}"
    )
    return observed, (
        not combo_before and after_play == (28, "GRAVEYARD", False)
        and not after_own_turn_end and not after_next_turn_start
    )


def probe_ex1_137_headcrack_combo_returns_to_hand_at_turn_end():
    game = new_game()
    p1, p2 = game.player1, game.player2
    p1.give("CS2_008").play(target=p2.hero)
    spell = p1.give("EX1_137")
    combo_before = bool(p1.combo)
    spell.play()
    after_play = (p2.hero.health, spell.zone.name, sum(card.id == spell.id for card in p1.hand))
    game.end_turn()
    after_turn_end = [(card.id, card.zone.name) for card in p1.hand if card.id == spell.id]
    game.end_turn()
    after_opponent_turn = [(card.id, card.zone.name) for card in p1.hand if card.id == spell.id]
    observed = (
        f"combo_before={combo_before};after_play={after_play};"
        f"returned_at_p1_end={after_turn_end};still_one_after_opponent_turn={after_opponent_turn};"
        f"original_zone={spell.zone.name}"
    )
    return observed, (
        combo_before and p2.hero.health == 27 and spell.zone == Zone.GRAVEYARD
        and after_play == (27, "GRAVEYARD", 0) and len(after_turn_end) == 1
        and len(after_opponent_turn) == 1
    )


def probe_ex1_144_shadowstep_bounces_friendly_and_reduces_cost():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    friendly.set_current_health(3)
    enemy = p2.summon("CS2_182")
    shadowstep = p1.give("EX1_144")
    friendly_legal = friendly in shadowstep.targets
    enemy_legal = enemy in shadowstep.targets
    shadowstep.play(target=friendly)
    bounced = (friendly.zone.name, friendly in p1.hand, friendly.cost, friendly.health, friendly.max_health)
    if friendly in p1.hand:
        friendly.play()
    replayed = (friendly.zone.name, friendly.health, friendly.max_health)
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};bounced={bounced};"
        f"replayed={replayed};enemy_stays={enemy in p2.field};shadowstep={shadowstep.zone.name}"
    )
    return observed, (
        friendly_legal and not enemy_legal and bounced == ("HAND", True, 2, 5, 5)
        and replayed == ("PLAY", 5, 5) and enemy in p2.field
        and shadowstep.zone == Zone.GRAVEYARD
    )


def probe_ex1_145_preparation_reduces_only_next_spell():
    game = new_game()
    p1, p2 = game.player1, game.player2
    fireball = p1.give("CS2_029")
    frostbolt = p1.give("CS2_024")
    preparation = p1.give("EX1_145")
    before = (fireball.cost, frostbolt.cost)
    preparation.play()
    discounted = (fireball.cost, frostbolt.cost)
    fireball.play(target=p2.hero)
    after_first_spell = (frostbolt.cost, preparation.zone.name, p2.hero.health)
    observed = (
        f"before={before};discounted={discounted};after_first_spell={after_first_spell};"
        f"fireball={fireball.zone.name}"
    )
    return observed, (
        before == (4, 2) and discounted == (2, 0)
        and after_first_spell == (2, "GRAVEYARD", 24)
        and fireball.zone == Zone.GRAVEYARD
    )


def probe_ex1_154_wrath_three_damage_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    target = p2.summon("CS2_182")
    top = p1.card("CS2_231", zone=Zone.DECK)
    spell = p1.give("EX1_154")
    friendly_legal = p1.summon("CS2_182") in spell.targets
    enemy_legal = target in spell.targets
    spell.play(target=target, choose="EX1_154a")
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};target={target.health}/{target.max_health};"
        f"drawn={top.zone.name},in_hand={top in p1.hand};spell={spell.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal and target.health == 2 and target in p2.field
        and top in p1.deck and top not in p1.hand and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_154_wrath_one_damage_and_draw_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    target = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    top = p1.card("CS2_231", zone=Zone.DECK)
    spell = p1.give("EX1_154")
    friendly_legal = target in spell.targets
    enemy_legal = enemy in spell.targets
    spell.play(target=target, choose="EX1_154b")
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};target={target.health}/{target.max_health};"
        f"drawn={top.zone.name},in_hand={top in p1.hand};spell={spell.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal and target.health == 4 and target in p1.field
        and top in p1.hand and top.zone == Zone.HAND and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_155_mark_of_nature_four_attack_branch_on_enemy():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    spell = p1.give("EX1_155")
    friendly_legal = friendly in spell.targets
    enemy_legal = enemy in spell.targets
    spell.play(target=enemy, choose="EX1_155a")
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"enemy={enemy.atk}/{enemy.health}/{enemy.max_health}/taunt={enemy.taunt};spell={spell.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal and enemy in p2.field
        and (enemy.atk, enemy.health, enemy.max_health, bool(enemy.taunt)) == (8, 5, 5, False)
        and (friendly.atk, friendly.health) == (4, 5) and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_155_mark_of_nature_four_health_taunt_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    spell = p1.give("EX1_155")
    friendly_legal = friendly in spell.targets
    enemy_legal = enemy in spell.targets
    spell.play(target=friendly, choose="EX1_155b")
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"friendly={friendly.atk}/{friendly.health}/{friendly.max_health}/taunt={friendly.taunt};"
        f"enemy={enemy.atk}/{enemy.health}/{enemy.max_health}/taunt={enemy.taunt};spell={spell.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal
        and (friendly.atk, friendly.health, friendly.max_health, bool(friendly.taunt)) == (4, 9, 9, True)
        and (enemy.atk, enemy.health, enemy.max_health, bool(enemy.taunt)) == (4, 5, 5, False)
        and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_158_soul_of_the_forest_simultaneous_deaths_summon_treants():
    game = new_game()
    p1, p2 = game.player1, game.player2
    first, second = p1.summon("CS2_231"), p1.summon("CS2_231")
    enemy = p2.summon("CS2_231")
    soul = p1.give("EX1_158")
    soul.play()
    granted = (first.has_deathrattle, second.has_deathrattle, enemy.has_deathrattle)
    game.end_turn()
    hellfire = p2.give("CS2_062")
    hellfire.play()
    friendly_treants = [m for m in p1.field if m.id == "EX1_158t"]
    enemy_treants = [m for m in p2.field if m.id == "EX1_158t"]
    observed = (
        f"deathrattle_before={granted};friendly_dead={first.zone.name}/{second.zone.name};"
        f"enemy_dead={enemy.zone.name};friendly_treants={[(m.atk,m.health) for m in friendly_treants]};"
        f"enemy_treants={len(enemy_treants)};hellfire={hellfire.zone.name}"
    )
    return observed, (
        granted == (True, True, False) and first.zone == Zone.GRAVEYARD
        and second.zone == Zone.GRAVEYARD and enemy.zone == Zone.GRAVEYARD
        and len(friendly_treants) == 2 and all((m.atk, m.health) == (2, 2) for m in friendly_treants)
        and not enemy_treants and hellfire.zone == Zone.GRAVEYARD
    )


def probe_ex1_164_nourish_gain_mana_crystal_branch():
    game = new_game()
    p1 = game.player1
    p1.max_mana = 8
    before = p1.max_mana
    spell = p1.give("EX1_164")
    spell.play(choose="EX1_164a")
    observed = f"max_mana={before}->{p1.max_mana};spell={spell.zone.name};field={len(p1.field)}"
    return observed, p1.max_mana == 10 and spell.zone == Zone.GRAVEYARD


def probe_ex1_164_nourish_draw_three_branch():
    game = new_game()
    p1 = game.player1
    cards = [p1.card(card_id, zone=Zone.DECK) for card_id in ("CS2_231", "CS2_182", "EX1_008")]
    spell = p1.give("EX1_164")
    spell.play(choose="EX1_164b")
    observed = (
        f"drawn={[card.id for card in p1.hand]};expected={[card.id for card in cards]};"
        f"all_in_hand={all(card in p1.hand and card.zone == Zone.HAND for card in cards)};"
        f"deck={len(p1.deck)};spell={spell.zone.name}"
    )
    return observed, (
        len(p1.hand) == 3 and all(card in p1.hand and card.zone == Zone.HAND for card in cards)
        and not p1.deck and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_165_druid_of_the_claw_charge_branch_attacks_immediately():
    game = new_game()
    p1, p2 = game.player1, game.player2
    card = p1.give("EX1_165")
    card.play(choose="EX1_165a")
    claw = next(m for m in p1.field if m.id == "EX1_165t1")
    can_attack = claw.can_attack()
    claw.attack(p2.hero)
    observed = (
        f"form={claw.id};stats={claw.atk}/{claw.health}/{claw.max_health};charge={claw.charge};"
        f"can_attack_immediately={can_attack};hero_health={p2.hero.health};attacks={claw.num_attacks}"
    )
    return observed, (
        (claw.atk, claw.health, claw.max_health) == (4, 4, 4) and claw.charge
        and can_attack and p2.hero.health == 26 and claw.num_attacks == 1 and claw in p1.field
    )


def probe_ex1_165_druid_of_the_claw_taunt_branch_combat():
    game = new_game()
    p1, p2 = game.player1, game.player2
    card = p1.give("EX1_165")
    card.play(choose="EX1_165b")
    claw = next(m for m in p1.field if m.id == "EX1_165t2")
    initial_stats = (claw.atk, claw.health, claw.max_health)
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    targets = list(boar.targets)
    can_attack_claw = claw in targets
    can_attack_hero = p1.hero in targets
    boar.attack(claw)
    observed = (
        f"form={claw.id};initial_stats={initial_stats};after_stats={claw.atk}/{claw.health}/{claw.max_health};taunt={claw.taunt};"
        f"claw_target={can_attack_claw};hero_target={can_attack_hero};after={claw.health}/{claw.zone.name};boar={boar.zone.name}"
    )
    return observed, (
        initial_stats == (4, 6, 6) and (claw.atk, claw.health, claw.max_health) == (4, 5, 6) and claw.taunt
        and can_attack_claw and not can_attack_hero and claw.health == 5 and claw in p1.field
        and boar.zone == Zone.GRAVEYARD
    )


def probe_ex1_166_keeper_of_the_grove_damage_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS2_182")
    enemy = p2.summon("CS2_182")
    keeper = p1.give("EX1_166")
    friendly_legal = friendly in keeper.targets
    enemy_legal = enemy in keeper.targets
    keeper.play(target=enemy, choose="EX1_166a")
    observed = (
        f"friendly_target_legal={friendly_legal};enemy_target_legal={enemy_legal};"
        f"enemy_health={enemy.health}/{enemy.max_health};friendly_health={friendly.health};keeper={keeper.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal and enemy.health == 3 and enemy in p2.field
        and friendly.health == 5 and keeper in p1.field
    )


def probe_ex1_166_keeper_of_the_grove_silence_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    friendly = p1.summon("CS1_069")
    enemy = p2.summon("CS1_069")
    keeper = p1.give("EX1_166")
    friendly_legal = friendly in keeper.targets
    enemy_legal = enemy in keeper.targets
    keeper.play(target=enemy, choose="EX1_166b")
    observed = (
        f"friendly_target_legal={friendly_legal};enemy_target_legal={enemy_legal};"
        f"enemy={enemy.health}/{enemy.max_health};taunt={enemy.taunt};silenced={enemy.silenced};"
        f"friendly_taunt={friendly.taunt};keeper={keeper.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal and enemy in p2.field and enemy.health == 6
        and not enemy.taunt and enemy.silenced and friendly.taunt and not friendly.silenced
        and keeper in p1.field
    )


def probe_ex1_178_ancient_of_war_health_taunt_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    ancient = p1.give("EX1_178")
    ancient.play(choose="EX1_178a")
    before = (ancient.atk, ancient.health, ancient.max_health, bool(ancient.taunt))
    game.end_turn()
    boar = p2.give("CS2_171")
    boar.play()
    targetable = ancient in boar.targets
    hero_targetable = p1.hero in boar.targets
    boar.attack(ancient)
    observed = (
        f"before_combat={before};taunt_targetable={targetable};hero_targetable={hero_targetable};"
        f"after={ancient.health}/{ancient.max_health};boar={boar.zone.name}"
    )
    return observed, (
        before == (5, 10, 10, True) and targetable and not hero_targetable
        and ancient.health == 9 and ancient in p1.field and boar.zone == Zone.GRAVEYARD
    )


def probe_ex1_178_ancient_of_war_attack_branch():
    game = new_game()
    p1, p2 = game.player1, game.player2
    ancient = p1.give("EX1_178")
    ancient.play(choose="EX1_178b")
    before = (ancient.atk, ancient.health, ancient.max_health, bool(ancient.taunt))
    game.end_turn()
    game.end_turn()
    can_attack = ancient.can_attack()
    ancient.attack(p2.hero)
    observed = (
        f"before_attack={before};can_attack={can_attack};hero_health={p2.hero.health};"
        f"attacks={ancient.num_attacks};zone={ancient.zone.name}"
    )
    return observed, (
        before == (10, 5, 5, False) and can_attack and p2.hero.health == 20
        and ancient.num_attacks == 1 and ancient in p1.field
    )


def probe_ex1_179_icicle_nonfrozen_target_no_draw():
    game = new_game(CardClass.MAGE)
    p1, p2 = game.player1, game.player2
    friendly, enemy = p1.summon("CS2_182"), p2.summon("CS2_182")
    top = p1.card("CS2_231", zone=Zone.DECK)
    spell = p1.give("EX1_179")
    friendly_legal, enemy_legal = friendly in spell.targets, enemy in spell.targets
    spell.play(target=friendly)
    observed = (
        f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
        f"friendly={friendly.health}/{friendly.zone.name};enemy={enemy.health}/{enemy.zone.name};"
        f"top={top.zone.name};spell={spell.zone.name}"
    )
    return observed, (
        friendly_legal and enemy_legal and friendly.health == 3 and friendly in p1.field
        and enemy.health == 5 and enemy in p2.field and top in p1.deck
        and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_179_icicle_frozen_enemy_draws():
    game = new_game(CardClass.MAGE)
    p1, p2 = game.player1, game.player2
    enemy = p2.summon("CS2_182")
    enemy.frozen = True
    top = p1.card("CS2_231", zone=Zone.DECK)
    spell = p1.give("EX1_179")
    legal = enemy in spell.targets
    spell.play(target=enemy)
    observed = (
        f"enemy_legal={legal};frozen_before=True;enemy={enemy.health}/{enemy.zone.name};"
        f"top={top.zone.name},in_hand={top in p1.hand};spell={spell.zone.name}"
    )
    return observed, (
        legal and enemy.health == 3 and enemy.frozen and enemy in p2.field
        and top in p1.hand and top.zone == Zone.HAND and spell.zone == Zone.GRAVEYARD
    )


def probe_ex1_180_tome_gives_random_mage_spell():
    observations, outcomes, generated_ids = [], [], set()
    for seed in range(12):
        game = new_game(CardClass.MAGE)
        player = game.player1
        game.random.seed(seed)
        before = {id(card) for card in player.hand}
        tome = player.give("EX1_180")
        before.add(id(tome))
        tome.play()
        added = [card for card in player.hand if id(card) not in before]
        valid = (
            len(added) == 1 and CardType(added[0].type) == CardType.SPELL
            and CardClass(added[0].card_class) == CardClass.MAGE
            and tome.zone == Zone.GRAVEYARD
        )
        if added:
            generated_ids.add(added[0].id)
        outcomes.append(valid)
        observations.append(
            f"seed{seed}=" + (f"{added[0].id}/class={CardClass(added[0].card_class).name}/type={CardType(added[0].type).name}"
                              if added else "no_new_card")
        )
    return (
        f"added_one_valid_spell_each={all(outcomes)};distinct_generated_ids={sorted(generated_ids)};"
        + ";".join(observations),
        all(outcomes) and len(generated_ids) > 1,
    )


def probe_ex1_181_call_of_the_void_gives_demon_minion():
    observations, outcomes, generated_ids = [], [], set()
    for seed in range(12):
        game = new_game(CardClass.WARLOCK)
        player = game.player1
        game.random.seed(seed)
        before = {id(card) for card in player.hand}
        spell = player.give("EX1_181")
        before.add(id(spell))
        spell.play()
        added = [card for card in player.hand if id(card) not in before]
        valid = (
            len(added) == 1 and CardType(added[0].type) == CardType.MINION
            and Race(added[0].race) == Race.DEMON and spell.zone == Zone.GRAVEYARD
        )
        if added:
            generated_ids.add(added[0].id)
        outcomes.append(valid)
        observations.append(
            f"seed{seed}=" + (f"{added[0].id}/race={Race(added[0].race).name}/type={CardType(added[0].type).name}"
                              if added else "no_new_card")
        )
    return (
        f"added_one_demon_minion_each={all(outcomes)};distinct_generated_ids={sorted(generated_ids)};"
        + ";".join(observations),
        all(outcomes) and len(generated_ids) > 1,
    )


def probe_ex1_182_pilfer_random_other_class_pool():
    observations, outcomes, generated_classes, generated_ids = [], [], set(), set()
    for seed in range(16):
        game = new_game(CardClass.ROGUE)
        player = game.player1
        game.random.seed(seed)
        before = {id(card) for card in player.hand}
        spell = player.give("EX1_182")
        before.add(id(spell))
        spell.play()
        added = [card for card in player.hand if id(card) not in before]
        valid = (
            len(added) == 1 and CardClass(added[0].card_class) not in
            (CardClass.ROGUE, CardClass.NEUTRAL) and spell.zone == Zone.GRAVEYARD
        )
        if added:
            generated_classes.add(CardClass(added[0].card_class).name)
            generated_ids.add(added[0].id)
        outcomes.append(valid)
        observations.append(
            f"seed{seed}=" + (f"{added[0].id}/class={CardClass(added[0].card_class).name}"
                              if added else "no_new_card")
        )
    return (
        f"all_generated_cards_are_other_hero_class={all(outcomes)};"
        f"generated_classes={sorted(generated_classes)};generated_ids={sorted(generated_ids)};"
        + ";".join(observations),
        all(outcomes) and len(generated_classes) > 1,
    )


def run_all():
    run_card("CS1_069", [
        ("fen_creeper_taunt_blocks_hero_attack",
         "Play the 3/6 Taunt minion; an enemy Charge minion can attack it but cannot target the hero or a non-Taunt minion, and dies in combat.",
         probe_cs1_069_taunt_combat),
    ])
    run_card("CS1_129", [
        ("inner_fire_friendly_and_enemy_wounded_targets",
         "Friendly and enemy minions are both legal; on each wounded 4/5 target, set attack to 3 without healing or changing max health.",
         probe_cs1_129_attack_matches_current_health),
    ])
    run_card("CS2_028", [
        ("blizzard_hits_and_freezes_enemy_minions_only",
         "Deal 2 to each enemy minion, freeze survivors, kill a 1-health enemy, and leave friendly minions untouched.",
         probe_cs2_028_blizzard_enemy_damage_freeze),
    ])
    run_card("CS2_038", [
        ("ancestral_spirit_resummons_dead_target",
         "After enchanting a friendly minion, its death resolves one deathrattle and summons one copy with the printed stats.",
         probe_cs2_038_ancestral_spirit_resummons_once),
        ("ancestral_spirit_enemy_target_deathrattle_resummons",
         "The enemy minion is a legal target; after it dies the granted Deathrattle summons one copy of the marked minion.",
         probe_cs2_038_enemy_target_deathrattle_resummons),
    ])
    run_card("CS2_053", [
        ("far_sight_draws_known_card_and_reduces_its_cost",
         "Draw the known 4-cost Yeti into hand and reduce that card's cost by 3 without changing another hand card.",
         probe_cs2_053_far_sight_draw_cost_reduction),
        ("far_sight_low_cost_reduction_floors_at_zero",
         "Draw a 1-cost card and reduce its cost to the minimum of 0 rather than a negative value.",
         probe_cs2_053_far_sight_floors_low_cost_at_zero),
    ])
    run_card("CS2_059", [
        ("blood_imp_random_end_turn_buff_hits_one_other_candidate",
         "Across fixed seeds, at turn end exactly one of two other friendly minions gains +1 Health, both candidates are selected, and the Imp remains Stealthed and unbuffed.",
         probe_cs2_059_blood_imp_end_turn_buff_other),
    ])
    run_card("CS2_073", [
        ("cold_blood_noncombo_enemy_target_gains_two_attack",
         "Without an earlier card, an enemy minion is a legal target and gains exactly +2 Attack.",
         probe_cs2_073_cold_blood_base_and_combo),
        ("cold_blood_combo_friendly_target_gains_four_attack",
         "After another card this turn, a friendly minion is a legal target and gains exactly +4 Attack.",
         probe_cs2_073_cold_blood_combo_branch),
    ])
    run_card("CS2_104", [
        ("rampage_only_targets_damaged_minions",
         "A damaged 4/5 target gains +3/+3 while an undamaged minion is excluded from targets and unchanged.",
         probe_cs2_104_rampage_requires_damaged_minion),
        ("rampage_buffs_damaged_friendly_minion",
         "A damaged friendly minion is also a legal target and gains +3/+3.",
         probe_cs2_104_rampage_buffs_damaged_friendly_minion),
    ])
    run_card("CS2_117", [
        ("farseer_battlecry_restores_three_health",
         "Battlecry restores exactly 3 Health to the wounded friendly hero while the Farseer enters play.",
         probe_cs2_117_farseer_restores_three),
        ("farseer_heals_enemy_minion_and_caps_full_health_target",
         "The enemy minion is a legal target and heals from 2 to 5; a full-health friendly minion remains capped at its maximum.",
         probe_cs2_117_farseer_heals_enemy_minion_without_overhealing),
    ])
    run_card("CS2_146", [
        ("deckhand_charge_depends_on_equipped_weapon",
         "Southsea Deckhand lacks Charge without a weapon; with one equipped it has Charge and makes an actual immediate attack.",
         probe_cs2_146_deckhand_conditional_charge),
    ])
    run_card("CS2_151", [
        ("silver_hand_knight_battlecry_summons_squire",
         "Playing Silver Hand Knight adds the Knight and exactly one 2/2 Silver Hand Recruit to the friendly board.",
         probe_cs2_151_silver_hand_knight_summons_squire),
        ("silver_hand_knight_last_slot_does_not_overfill",
         "With six friendly minions before playing it, the Knight fills the seventh slot and the Squire is not summoned.",
         probe_cs2_151_squire_respects_last_board_slot),
    ])
    run_card("CS2_161", [
        ("ravenholdt_assassin_stealth_blocks_enemy_targets",
         "On the opponent's actual turn, the Stealthed Assassin is absent from hero-power and Moonfire targets and the spell stays in hand.",
         probe_cs2_161_ravenholdt_stealth),
    ])
    run_card("CS2_169", [
        ("dragonhawk_can_attack_twice_per_turn",
         "After summoning sickness expires, Windfury allows exactly two 1-damage attacks in the turn.",
         probe_cs2_169_dragonhawk_windfury_two_attacks),
    ])
    run_card("CS2_181", [
        ("injured_blademaster_takes_four_battlecry_damage",
         "Battlecry leaves the printed 4/7 minion at 4/3 current Health in play.",
         probe_cs2_181_injured_blademaster_self_damage),
    ])
    run_card("CS2_203", [
        ("owl_silence_removes_taunt_and_divine_shield",
         "Ironbeak Owl may target the enemy Sunwalker and removes both Taunt and Divine Shield while leaving it alive.",
         probe_cs2_203_owl_silences_taunt_and_shield),
        ("owl_silences_friendly_minion",
         "A friendly Sunwalker is also a legal target; its Taunt and Divine Shield are removed without killing it.",
         probe_cs2_203_owl_can_silence_friendly_minion),
    ])
    run_card("CS2_221", [
        ("spiteful_smith_enrage_weapon_bonus_enters_and_leaves",
         "Damage to Spiteful Smith adds +2 weapon Attack; healing it back to full removes the bonus.",
         probe_cs2_221_spiteful_smith_enrage_aura_tracks_damage),
    ])
    run_card("CS2_227", [
        ("venture_co_mercenary_cost_aura_and_silence_update",
         "Venture Co. adds 3 cost to minions in hand while alive; silencing it removes the modifier and a newly added minion has printed cost.",
         probe_cs2_227_venture_co_cost_aura_updates_and_clears),
    ])
    run_card("CS2_233", [
        ("blade_flurry_hits_enemy_minions_and_destroys_weapon",
         "Using a 1-Attack weapon deals exactly 1 to every enemy minion, leaves friendly minions and the enemy hero alone, then destroys the weapon.",
         probe_cs2_233_blade_flurry_weapon_damage_and_destroy),
    ])
    run_card("DS1_188", [
        ("gladiators_longbow_hero_immune_during_attack",
         "The armed hero's attack kills the enemy Wisp without taking retaliation damage and consumes one weapon durability.",
         probe_ds1_188_longbow_hero_immune_during_attack),
    ])
    run_card("EX1_001", [
        ("lightwarden_gains_attack_from_enemy_hero_and_friendly_minion_heals",
         "Healing an enemy hero triggers +2 Attack; a later friendly minion heal triggers another +2.",
         probe_ex1_001_lightwarden_triggers_on_both_sides_heals),
    ])
    run_card("EX1_002", [
        ("black_knight_requires_enemy_taunt_and_destroys_it",
         "Only the enemy Taunt minion is a legal target; it is destroyed while a plain enemy and friendly Taunt survive.",
         probe_ex1_002_black_knight_only_destroys_enemy_taunt),
    ])
    run_card("EX1_004", [
        ("young_priestess_randomly_buffs_one_other_minion_at_turn_end",
         "Across fixed seeds, exactly one other friendly minion gains +1 Health each turn end, and both eligible candidates are selected.",
         probe_ex1_004_young_priestess_random_other_minion_buff),
    ])
    run_card("EX1_005", [
        ("big_game_hunter_seven_attack_threshold_and_destroy",
         "A 7-Attack enemy is targetable and destroyed; a 6-Attack enemy is excluded and remains in play.",
         probe_ex1_005_big_game_hunter_seven_threshold),
    ])
    run_card("EX1_006", [
        ("alarmobot_random_minion_swap_at_next_turn_start",
         "Across fixed seeds, a random minion from hand is swapped onto the board, Alarm-o-Bot returns to hand, and both candidates can be selected.",
         probe_ex1_006_alarmobot_swaps_one_minion_at_turn_start),
    ])
    run_card("EX1_008", [
        ("argent_squire_shield_absorbs_first_spell_then_dies",
         "The first 1-damage hit removes Divine Shield without harming the Squire; a second hit kills it.",
         probe_ex1_008_argent_squire_divine_shield_absorbs_one_hit),
    ])
    run_card("EX1_009", [
        ("angry_chicken_enrage_attack_bonus_tracks_damage_and_heal",
         "Damage while alive grants +5 Attack; healing back to full removes that Attack bonus.",
         probe_ex1_009_angry_chicken_enrage_tracks_damage_and_heal),
    ])
    run_card("EX1_010", [
        ("worgen_stealth_blocks_target_until_it_attacks",
         "On the opponent's turn the Stealthed Worgen is untargetable; after its attack it loses Stealth and becomes targetable.",
         probe_ex1_010_worgen_stealth_expires_after_attack),
    ])
    run_card("EX1_012", [
        ("thalnos_spell_damage_and_deathrattle_draw",
         "Spell Damage +1 makes Moonfire deal 2 and kill a Wisp; Thalnos's death draws the known top card into hand.",
         probe_ex1_012_thalnos_spell_damage_and_deathrattle_draw),
    ])
    run_card("EX1_014", [
        ("king_mukla_gives_two_banana_cards_to_opponent",
         "Mukla enters play and adds exactly two Banana cards to the opponent's hand without adding one to its controller's hand.",
         probe_ex1_014_king_mukla_gives_two_bananas_to_opponent),
    ])
    run_card("EX1_017", [
        ("jungle_panther_stealth_hides_then_attack_breaks_it",
         "The Panther is hidden from the opponent's hero-power targets and loses Stealth after making its attack.",
         probe_ex1_017_jungle_panther_stealth_and_attack),
    ])
    run_card("EX1_020", [
        ("scarlet_crusader_shield_absorbs_combat_attack",
         "A Charge Boar's attack consumes Scarlet Crusader's Divine Shield, leaves Crusader alive, and kills the Boar in combat.",
         probe_ex1_020_scarlet_crusader_shield_absorbs_combat_hit),
    ])
    run_card("EX1_021", [
        ("thrallmar_farseer_windfury_allows_two_attacks",
         "After summoning sickness, Farseer makes two same-turn face attacks, each dealing its attack value.",
         probe_ex1_021_thrallmar_farseer_windfury_attacks_twice),
    ])
    run_card("EX1_023", [
        ("silvermoon_guardian_shield_absorbs_combat_damage",
         "A Charge attacker can fight Guardian; Divine Shield absorbs retaliation damage, Guardian stays unharmed, and attacker dies.",
         probe_ex1_023_silvermoon_guardian_shield_in_combat),
    ])
    run_card("EX1_028", [
        ("stranglethorn_tiger_stealth_breaks_on_attack",
         "Opponent cannot target the Stealthed Tiger; after it attacks, Stealth ends and opponent can target and kill it.",
         probe_ex1_028_tiger_stealth_and_post_attack_targeting),
    ])
    run_card("EX1_029", [
        ("leper_gnome_deathrattle_hits_enemy_hero",
         "Killing Leper Gnome sends it to the graveyard and its Deathrattle deals exactly 2 to the opposing hero.",
         probe_ex1_029_leper_gnome_deathrattle_hits_enemy_hero),
    ])
    run_card("EX1_032", [
        ("sunwalker_taunt_shield_combat_targeting",
         "Enemy Charge minion must attack Sunwalker, Divine Shield absorbs the hit, Taunt remains, and attacker dies.",
         probe_ex1_032_sunwalker_taunt_shield_combat),
    ])
    run_card("EX1_033", [
        ("windfury_harpy_makes_two_face_attacks",
         "After summoning sickness, Windfury Harpy makes two same-turn attacks and deals its attack value twice.",
         probe_ex1_033_windfury_harpy_two_attacks),
    ])
    run_card("EX1_043", [
        ("twilight_drake_gains_health_for_each_other_hand_card",
         "On play, Drake gains exactly +1 maximum and current Health for every other card still in its controller's hand.",
         probe_ex1_043_twilight_drake_counts_other_hand_cards),
    ])
    run_card("EX1_044", [
        ("questing_adventurer_triggers_on_own_cards_only",
         "Questing gains +1/+1 from an own spell and an own minion, while an opponent spell causes no further growth.",
         probe_ex1_044_questing_adventurer_own_card_triggers_only),
    ])
    run_card("EX1_045", [
        ("ancient_watcher_silence_removes_cannot_attack",
         "Watcher cannot attack on successive turns; after an opponent-targetable Silence it can attack the enemy hero.",
         probe_ex1_045_ancient_watcher_silence_enables_attack),
    ])
    run_card("EX1_046", [
        ("dark_iron_dwarf_buffs_friendly_target_until_turn_end",
         "A friendly minion gains +2 Attack, attacks for the increased value, then returns to base Attack at controller turn end.",
         probe_ex1_046_dark_iron_dwarf_friendly_target_expires),
        ("dark_iron_dwarf_allows_enemy_target_and_expires",
         "Both friendly and enemy minions are legal targets; chosen enemy gains +2 Attack temporarily and returns to base after caster turn.",
         probe_ex1_046_dark_iron_dwarf_enemy_target_domain_and_expiry),
    ])
    run_card("EX1_055", [
        ("mana_addict_stacks_own_spell_triggers_then_expires",
         "Two own spells each add +2 Attack; buff expires at controller turn end and opponent's spell adds nothing.",
         probe_ex1_055_mana_addict_own_spells_and_turn_expiry),
    ])
    run_card("EX1_057", [
        ("ancient_brewmaster_bounces_only_friendly_target",
         "Wounded friendly minion is legal and returns to hand, enemy minion is illegal, and re-playing returned card restores full Health.",
         probe_ex1_057_ancient_brewmaster_friendly_target_and_bounce),
    ])
    run_card("EX1_058", [
        ("sunfury_protector_gives_taunt_to_adjacent_minions_only",
         "With insertion at index 1, the minions immediately to either side gain Taunt; the farther minion and Protector do not.",
         probe_ex1_058_sunfury_protector_adjacent_minions_only),
    ])
    run_card("EX1_059", [
        ("crazed_alchemist_swaps_attack_health_on_friendly_and_enemy",
         "Both friendly and enemy minions are legal; each full-health 4/5 Yeti becomes 5/4 without leaving play.",
         probe_ex1_059_crazed_alchemist_friendly_and_enemy_targets),
    ])
    run_card("EX1_067", [
        ("argent_commander_charge_and_divine_shield_in_combat",
         "Commander attacks a 4/5 immediately after play; its shield absorbs retaliation and it survives while dealing 4 damage.",
         probe_ex1_067_argent_commander_charge_and_shield_combat),
    ])
    run_card("EX1_076", [
        ("pint_sized_summoner_discounts_first_minion_each_turn",
         "Summoner discounts the first minion by 1, removes discount after it is played, leaves spells unchanged, and refreshes next turn.",
         probe_ex1_076_pint_sized_summoner_first_minion_discount),
    ])
    run_card("EX1_080", [
        ("secretkeeper_gains_stats_when_either_player_plays_secret",
         "Secretkeeper gains +1/+1 when its controller and when the opponent each play a Secret.",
         probe_ex1_080_secretkeeper_triggers_on_secrets_from_both_players),
    ])
    run_card("EX1_082", [
        ("mad_bomber_splits_three_hits_across_other_characters",
         "Across fixed seeds, each battlecry deals exactly 3 total random damage to other characters; every hero/minion candidate is reached and Bomber is excluded.",
         probe_ex1_082_mad_bomber_three_random_hits_other_characters),
    ])
    run_card("EX1_083", [
        ("tinkmaster_randomly_transforms_one_other_minion",
         "Across fixed seeds, either friendly or enemy minions can be chosen; exactly one becomes a 5/5 Devilsaur or a 1/1 Squirrel, never Tinkmaster.",
         probe_ex1_083_tinkmaster_random_target_and_transform_options),
    ])
    run_card("EX1_089", [
        ("arcane_golem_increases_opponent_max_mana",
         "Playing Golem adds one Mana Crystal to opponent's maximum (3 to 4) without changing its controller's maximum.",
         probe_ex1_089_arcane_golem_grants_opponent_crystal),
    ])
    run_card("EX1_091", [
        ("cabal_shadow_priest_steals_enemy_minion_at_two_attack_boundary",
         "Enemy 2-Attack minion is legal and stolen; friendly and enemy 3-Attack minions are excluded.",
         probe_ex1_091_cabal_shadow_priest_steals_only_enemy_minion_with_two_attack),
    ])
    run_card("EX1_093", [
        ("defender_of_argus_buffs_only_two_adjacent_minions",
         "Placed between minions, Argus grants +1/+1 and Taunt to the immediate neighbors only; the farther minion and Argus do not gain either.",
         probe_ex1_093_defender_of_argus_buffs_exact_adjacent_positions),
    ])
    run_card("EX1_095", [
        ("gadgetzan_auctioneer_draws_for_own_spell_not_opponent_spell",
         "Own physical spell draws the known top card; an opponent's spell leaves the next known card in deck.",
         probe_ex1_095_gadgetzan_auctioneer_draws_for_own_spell),
    ], blocker="CAST-001 remains unresolved for listener behavior when another card script casts a spell; ordinary player-cast spell behavior is tested here.")
    run_card("EX1_096", [
        ("loot_hoarder_deathrattle_draws_its_owners_top_card",
         "After the enemy deals lethal damage, Hoarder enters graveyard and its controller draws the known top card.",
         probe_ex1_096_loot_hoarder_deathrattle_draws_its_owners_card),
    ])
    run_card("EX1_097", [
        ("abomination_deathrattle_hits_all_characters_and_resolves_deaths",
         "On death, Abomination deals 2 to both heroes and all minions; both resulting Loot Hoarder deaths resolve and each owner draws.",
         probe_ex1_097_abomination_deathrattle_hits_all_and_resolves_other_deathrattles),
    ])
    run_card("EX1_100", [
        ("lorewalker_cho_copies_each_players_cast_spell_to_other_hand",
         "A spell cast by each player is copied to the other player's hand while the original resolves and enters graveyard.",
         probe_ex1_100_lorewalker_cho_copies_each_players_spell_to_other_hand),
    ])
    run_card("EX1_102", [
        ("demolisher_turn_start_hits_one_random_enemy_for_two",
         "Across fixed seeds, the own-turn-start trigger deals exactly 2 to one random enemy character, reaching enemy hero and both minions.",
         probe_ex1_102_demolisher_start_of_turn_hits_random_enemy),
    ])
    run_card("EX1_103", [
        ("coldlight_seer_gives_two_health_to_other_friendly_murlocs",
         "Other friendly Murlocs gain +2 current and maximum Health; non-Murlocs, enemy Murlocs, and Seer are unchanged.",
         probe_ex1_103_coldlight_seer_buffs_only_other_friendly_murlocs),
    ])
    run_card("EX1_110", [
        ("cairne_deathrattle_summons_one_four_five_baine",
         "After the enemy destroys Cairne, the original enters graveyard and exactly one 4/5 Baine appears for Cairne's controller.",
         probe_ex1_110_cairne_deathrattle_summons_baine),
    ])
    run_card("EX1_124", [
        ("eviscerate_normal_branch_deals_two_and_accepts_both_sides",
         "Without a prior card, Eviscerate deals 2; friendly and enemy minions are legal targets.",
         probe_ex1_124_eviscerate_normal_branch_and_target_domain),
        ("eviscerate_combo_branch_deals_four_and_accepts_both_sides",
         "After a prior card enables Combo, Eviscerate deals 4 to a friendly target; friendly and enemy minions are legal.",
         probe_ex1_124_eviscerate_combo_branch_deals_four),
    ])
    run_card("EX1_126", [
        ("betrayal_enemy_minion_deals_its_attack_to_adjacent_minions",
         "Enemy minion target is legal; its 4 Attack hits only immediate same-board neighbors, not itself, farther minions or friendly minions.",
         probe_ex1_126_betrayal_damages_only_enemy_targets_adjacent_minions),
    ])
    run_card("EX1_130", [
        ("noble_sacrifice_redirects_enemy_attack_to_defender",
         "An enemy Charge attack at the hero reveals the Secret, summons a 2/1 Defender as target, and combat leaves hero unharmed.",
         probe_ex1_130_noble_sacrifice_redirects_enemy_attack),
        ("noble_sacrifice_full_board_with_dormant_minion_stays_set",
         "With six active minions plus one Dormant minion occupying all seven slots, Noble Sacrifice stays set and cannot overfill the board.",
         probe_ex1_130_noble_sacrifice_dormant_full_board_stays_set),
    ])
    run_card("EX1_131", [
        ("defias_ringleader_without_combo_does_not_summon_bandit",
         "With no previous card played this turn, Ringleader enters as a 2/2 and summons no Defias Bandit.",
         probe_ex1_131_defias_ringleader_without_combo),
        ("defias_ringleader_combo_summons_one_two_one_bandit",
         "After a prior card enables Combo, Ringleader summons exactly one 2/1 Defias Bandit.",
         probe_ex1_131_defias_ringleader_combo_summons_bandit),
    ])
    run_card("EX1_132", [
        ("eye_for_an_eye_reflects_hero_damage_amount_once",
         "When Fireball deals 6 to the protected hero, Eye for an Eye deals exactly 6 to the enemy hero and is consumed.",
         probe_ex1_132_eye_for_an_eye_reflects_exact_hero_damage),
    ])
    run_card("EX1_133", [
        ("perditions_blade_normal_battlecry_deals_one_and_equips",
         "Without Combo, Battlecry deals 1 to the chosen enemy minion and Blade equips at 2 durability.",
         probe_ex1_133_perditions_blade_normal_battlecry_deals_one),
        ("perditions_blade_combo_battlecry_deals_two_and_equips",
         "After a prior card enables Combo, Battlecry deals 2 to a friendly target and Blade equips at 2 durability.",
         probe_ex1_133_perditions_blade_combo_battlecry_deals_two),
    ])
    run_card("EX1_137", [
        ("headcrack_without_combo_deals_two_and_does_not_return",
         "Without Combo, Headcrack deals 2 and stays out of hand through the turn transition.",
         probe_ex1_137_headcrack_normal_does_not_return),
        ("headcrack_combo_deals_two_and_returns_to_hand",
         "With Combo, Headcrack deals 2 and returns as one card to its owner's hand at turn end.",
         probe_ex1_137_headcrack_combo_returns_to_hand_at_turn_end),
    ])
    run_card("EX1_144", [
        ("shadowstep_bounces_friendly_minion_and_reduces_its_cost",
         "Friendly minion is legal, enemy is excluded, and returned 4-cost Yeti is in hand at cost 2 before it can be replayed.",
         probe_ex1_144_shadowstep_bounces_friendly_and_reduces_cost),
    ])
    run_card("EX1_145", [
        ("preparation_reduces_next_spell_then_removes_discount",
         "Preparation reduces Fireball and other in-hand spells by 2; casting Fireball consumes the effect and other spell costs return to base.",
         probe_ex1_145_preparation_reduces_only_next_spell),
    ])
    run_card("EX1_154", [
        ("wrath_three_damage_choice_hits_minion_without_drawing",
         "The 3-damage choice deals 3 to an enemy minion and does not draw; friendly and enemy minion targets are legal.",
         probe_ex1_154_wrath_three_damage_branch),
        ("wrath_one_damage_choice_hits_friendly_minion_and_draws",
         "The 1-damage choice deals 1 to a friendly minion and draws the known top card; enemy minions are also valid targets.",
         probe_ex1_154_wrath_one_damage_and_draw_branch),
    ])
    run_card("EX1_155", [
        ("mark_of_nature_four_attack_choice_on_enemy_target",
         "The +4 Attack choice is usable on an enemy minion and leaves its Health and Taunt unchanged.",
         probe_ex1_155_mark_of_nature_four_attack_branch_on_enemy),
        ("mark_of_nature_four_health_taunt_choice_on_friendly_target",
         "The +4 Health choice is usable on a friendly minion and grants +4 maximum/current Health plus Taunt.",
         probe_ex1_155_mark_of_nature_four_health_taunt_branch),
    ])
    run_card("EX1_158", [
        ("soul_of_the_forest_same_batch_deaths_each_summon_treant",
         "Two buffed friendly minions and an unbuffed enemy minion die in one Hellfire resolution; each friendly Deathrattle summons one 2/2 Treant.",
         probe_ex1_158_soul_of_the_forest_simultaneous_deaths_summon_treants),
    ])
    run_card("EX1_164", [
        ("nourish_gain_two_mana_crystals_choice",
         "The Mana branch raises maximum Mana from 8 to 10 and resolves the spell.",
         probe_ex1_164_nourish_gain_mana_crystal_branch),
        ("nourish_draw_three_choice_draws_known_cards",
         "The draw branch draws all three known cards into hand and leaves the deck empty.",
         probe_ex1_164_nourish_draw_three_branch),
    ])
    run_card("EX1_165", [
        ("druid_of_the_claw_charge_choice_attacks_immediately",
         "Charge choice transforms into a 4/4 and makes an immediate 4-damage face attack.",
         probe_ex1_165_druid_of_the_claw_charge_branch_attacks_immediately),
        ("druid_of_the_claw_taunt_choice_blocks_and_survives_combat",
         "Taunt choice transforms into a 4/6; an enemy Charge minion must attack it and dies while it survives.",
         probe_ex1_165_druid_of_the_claw_taunt_branch_combat),
    ])
    run_card("EX1_166", [
        ("keeper_of_the_grove_damage_choice_deals_two",
         "Damage choice deals exactly 2 to an enemy minion; friendly and enemy minion targets are available.",
         probe_ex1_166_keeper_of_the_grove_damage_branch),
        ("keeper_of_the_grove_silence_choice_removes_enemy_taunt",
         "Silence choice removes Taunt from the selected enemy while leaving it alive; friendly and enemy minions are valid targets.",
         probe_ex1_166_keeper_of_the_grove_silence_branch),
    ])
    run_card("EX1_178", [
        ("ancient_of_war_health_choice_gives_five_health_and_taunt",
         "Health choice makes Ancient of War a 5/10 Taunt that forces an enemy Charge minion to attack and survives.",
         probe_ex1_178_ancient_of_war_health_taunt_branch),
        ("ancient_of_war_attack_choice_gives_five_attack",
         "Attack choice makes Ancient of War a 10/5 without Taunt and it deals 10 in an actual attack after summoning sickness.",
         probe_ex1_178_ancient_of_war_attack_branch),
    ])
    run_card("EX1_179", [
        ("icicle_nonfrozen_friendly_target_damages_without_draw",
         "Friendly and enemy minions are legal; hitting the friendly non-Frozen target deals 2 and leaves the known top card in deck.",
         probe_ex1_179_icicle_nonfrozen_target_no_draw),
        ("icicle_frozen_enemy_target_damages_and_draws",
         "A Frozen enemy minion is legal; Icicle deals 2 and draws exactly the known top card.",
         probe_ex1_179_icicle_frozen_enemy_draws),
    ])
    run_card("EX1_180", [
        ("tome_of_intellect_adds_one_random_mage_spell",
         "Across 12 seeded plays, each resolves to exactly one new Mage Spell in hand, with multiple generated spell IDs reached.",
         probe_ex1_180_tome_gives_random_mage_spell),
    ])
    run_card("EX1_181", [
        ("call_of_the_void_adds_one_random_demon_minion",
         "Across 12 seeded plays, each resolves to exactly one Demon Minion in hand, with multiple Demon IDs reached.",
         probe_ex1_181_call_of_the_void_gives_demon_minion),
    ])
    run_card("EX1_182", [
        ("pilfer_adds_only_collectible_cards_from_other_hero_classes",
         "Across 16 seeded plays, each should add exactly one collectible card from a hero class other than Rogue; Neutral cards are not from another class.",
         probe_ex1_182_pilfer_random_other_class_pool),
    ])


if __name__ == "__main__":
    run_all()
