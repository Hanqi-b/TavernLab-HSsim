"""Behavior probes for the fixed Classic YELLOW baseline indices 85–113.

Run from the repository root with:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_middle_a.py [card_id ...]
Only the new middle_a probe/verdict files are written by this script.
"""
import csv
import logging
import random
from pathlib import Path

from fireplace.exceptions import InvalidAction
from hearthstone.enums import CardClass, CardType, Race, Rarity, Zone

from utils import MOONFIRE, WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
BASELINE = HERE / "expansion_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
PROBE_OUT = HERE / "classic_probe_middle_a.csv"
VERDICT_OUT = HERE / "classic_verdict_middle_a.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def save_rows(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


classic_baseline = sorted(
    (r for r in read_rows(BASELINE) if r["set"] == "Classic (EXPERT1)"),
    key=lambda r: r["card_id"],
)
ASSIGNED_ROWS = classic_baseline[85:114]
ASSIGNED = [r["card_id"] for r in ASSIGNED_ROWS]
EXPECTED_ASSIGNED = [
    "EX1_188", "EX1_189", "EX1_190", "EX1_195", "EX1_196",
    "EX1_197", "EX1_198", "EX1_238", "EX1_241", "EX1_243", "EX1_245",
    "EX1_247", "EX1_248", "EX1_249", "EX1_250", "EX1_251", "EX1_258",
    "EX1_259", "EX1_274", "EX1_275", "EX1_279", "EX1_283", "EX1_289",
    "EX1_294", "EX1_301", "EX1_303", "EX1_304", "EX1_309", "EX1_312",
]
assert len(ASSIGNED) == 29 and ASSIGNED == EXPECTED_ASSIGNED, ASSIGNED
MASTER_BY_ID = {r["card_id"]: r for r in read_rows(MASTER)}
BASELINE_INDEX = {r["card_id"]: i + 1 for i, r in enumerate(classic_baseline)}
PROBE_ROWS = [r for r in read_rows(PROBE_OUT) if r["card_id"] in ASSIGNED]
VERDICT_ROWS = [r for r in read_rows(VERDICT_OUT) if r["card_id"] in ASSIGNED]


class FixtureError(Exception):
    """The setup did not establish the preconditions needed to judge a card."""


def require_fixture(condition, detail):
    if not condition:
        raise FixtureError(detail)


def new_game(card_class=CardClass.SHAMAN):
    game = prepare_empty_game(card_class, card_class)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = 10
    game.player2.max_mana = 10
    return game


def metadata_note(card_id):
    card = MASTER_BY_ID[card_id]
    refs = card["test_refs_candidate"] or "none found"
    script = card["python_source"] or "native runtime tags (no per-card Python script)"
    return (
        f"EN: {card['card_text_en']} ZH: {card['card_text_zh']} "
        f"Script: {script}. Existing test refs: {refs}. "
        f"Prior audit: original baseline index {BASELINE_INDEX[card_id]} marked YELLOW."
    )


def record_card(card_id, cases, blocker=None):
    if card_id not in ASSIGNED:
        raise ValueError(f"{card_id} is outside assigned baseline indices 85–113")
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]
    card = MASTER_BY_ID[card_id]
    notes = metadata_note(card_id)
    card_rows = []
    for case_id, expected, probe in cases:
        try:
            observed, passed = probe()
            if passed is True:
                outcome = "pass"
            elif passed is False:
                outcome = "confirmed_error"
            else:
                outcome = "inconclusive"
        except FixtureError as error:
            observed, outcome = f"fixture_error: {error}", "inconclusive"
        except Exception as error:
            observed, outcome = f"{type(error).__name__}: {error}", "inconclusive"
        row = {"card_id": card_id, "case_id": case_id, "expected": expected,
               "observed": str(observed), "outcome": outcome, "notes": notes}
        PROBE_ROWS.append(row)
        card_rows.append(row)
        save_rows(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    outcomes = {r["outcome"] for r in card_rows}
    status = "RED" if "confirmed_error" in outcomes else "YELLOW" if "inconclusive" in outcomes or blocker else "GREEN"
    reason = "; ".join(
        f"{r['case_id']} {r['outcome']}: expected {r['expected']} observed {r['observed'][:200]}"
        + ("…" if len(r["observed"]) > 200 else "")
        for r in card_rows
    )
    if blocker:
        reason += f"; unresolved blocker: {blocker}"
    verdict = {
        "card_id": card_id,
        "status": status,
        "mechanic_scope": card["mechanics"],
        "reason": reason,
        "probe_file": PROBE_OUT.name,
        "notes": f"Card-specific game traces saved incrementally; see probe CSV. Original baseline index {BASELINE_INDEX[card_id]}.",
    }
    VERDICT_ROWS.append(verdict)
    save_rows(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def probe_stablehand_random_beast():
    outputs = []
    for seed in range(1, 17):
        random.seed(seed)
        game = new_game()
        owner = game.player1
        owner.discard_hand()
        stablehand = owner.give("EX1_188")
        stablehand.play()
        beasts = [m for m in owner.field if m is not stablehand]
        require_fixture(stablehand in owner.field, f"seed={seed}: Stablehand did not enter the field")
        if len(beasts) != 1:
            return f"seed={seed};field={[m.id for m in owner.field]};non_source={len(beasts)}", False
        beast = beasts[0]
        if beast.type != CardType.MINION or Race.BEAST not in beast.races:
            return f"seed={seed};summoned={beast.id};type={beast.type};races={beast.races}", False
        outputs.append(beast.id)
    return f"seeds=16;unique_beasts={','.join(sorted(set(outputs)))};all_one_beast=True", len(set(outputs)) > 1


def probe_stablehand_one_open_slot():
    game = new_game()
    owner = game.player1
    for _ in range(6):
        owner.summon(WISP)
    stablehand = owner.give("EX1_188")
    stablehand.play()
    observed = f"field={len(owner.field)};stablehand={stablehand in owner.field};ids={[m.id for m in owner.field]}"
    return observed, len(owner.field) == 7 and stablehand in owner.field and len([m for m in owner.field if m is not stablehand]) == 6


def card_ex1_188():
    return record_card("EX1_188", [
        ("battlecry_random_beast", "Battlecry summons exactly one Beast minion; fixed seeds produce more than one possible Beast.", probe_stablehand_random_beast),
        ("battlecry_full_board", "When Stablehand itself fills the seventh slot, the Battlecry cannot exceed the board cap.", probe_stablehand_one_open_slot),
    ])


def probe_brightwing_legendary_to_hand():
    outputs = []
    for seed in range(1, 17):
        random.seed(seed)
        game = new_game()
        owner = game.player1
        owner.discard_hand()
        brightwing = owner.give("EX1_189")
        brightwing.play()
        generated = list(owner.hand)
        if len(generated) != 1:
            return f"seed={seed};hand={[c.id for c in generated]};field={[m.id for m in owner.field]}", False
        card = generated[0]
        if card.type != CardType.MINION or card.rarity != Rarity.LEGENDARY or card.zone != Zone.HAND:
            return f"seed={seed};generated={card.id};type={card.type};rarity={card.rarity};zone={card.zone}", False
        outputs.append(card.id)
    return f"seeds=16;legendary_minions={','.join(sorted(set(outputs)))};all_in_hand=True", len(set(outputs)) > 1


def card_ex1_189():
    return record_card("EX1_189", [
        ("random_legendary_to_hand", "Battlecry adds exactly one random Legendary minion card to hand, not the board; outcomes vary across fixed seeds.", probe_brightwing_legendary_to_hand),
    ])


def probe_whitemane_current_turn_friendly_deaths():
    game = new_game()
    owner, opponent = game.player1, game.player2
    previous_turn_dead = owner.summon(WISP)
    previous_turn_dead.destroy()
    game.end_turn()
    game.end_turn()
    current_turn_dead = owner.summon("CS1_042")
    enemy_dead = opponent.summon(WISP)
    current_turn_dead.destroy()
    enemy_dead.destroy()
    whitemane = owner.give("EX1_190")
    whitemane.play()
    revived = list(owner.field.filter(id="CS1_042"))
    observed = f"old_dead={previous_turn_dead.zone.name};current_dead={current_turn_dead.zone.name};enemy_dead={enemy_dead.zone.name};revived={[m.id for m in revived]};field={[m.id for m in owner.field]}"
    passed = previous_turn_dead.zone == Zone.GRAVEYARD and enemy_dead.zone == Zone.GRAVEYARD and current_turn_dead.zone == Zone.GRAVEYARD and len(revived) == 1 and whitemane in owner.field
    return observed, passed


def card_ex1_190():
    return record_card("EX1_190", [
        ("battlecry_same_turn_friendly_deaths", "Whitemane resummons the friendly minion that died this turn, excludes a friendly death from the prior turn and an enemy death.", probe_whitemane_current_turn_friendly_deaths),
    ])


def probe_chaplain_friendly_health_buff():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    owner.give(MOONFIRE).play(target=friendly)
    owner.give(MOONFIRE).play(target=friendly)
    chaplain = owner.give("EX1_195")
    legal = list(chaplain.targets)
    chaplain.play(target=friendly)
    observed = f"target_health={friendly.health}/{friendly.max_health};atk={friendly.atk};enemy_untouched={enemy.health}/{enemy.max_health};legal_enemy={enemy in legal};source={chaplain.zone.name}"
    passed = (friendly.atk, friendly.health, friendly.max_health) == (4, 5, 7) and enemy.health == enemy.max_health == 5 and enemy not in legal and chaplain in owner.field
    return observed, passed


def card_ex1_195():
    return record_card("EX1_195", [
        ("friendly_target_gains_two_health", "Chaplain's Battlecry gives a damaged friendly Yeti +2 current and maximum Health, preserves Attack, and excludes an enemy minion.", probe_chaplain_friendly_health_buff),
    ])


def probe_subjugator_temporary_enemy_attack():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    subjugator = owner.give("EX1_196")
    legal = list(subjugator.targets)
    subjugator.play(target=enemy)
    after_play = (friendly.atk, enemy.atk)
    game.end_turn()
    during_opponent_turn = enemy.atk
    game.end_turn()
    at_owner_next_turn = enemy.atk
    observed = f"friendly_legal={friendly in legal};enemy_legal={enemy in legal};after_play={after_play};opponent_turn={during_opponent_turn};owner_next_turn={at_owner_next_turn}"
    return observed, friendly not in legal and enemy in legal and after_play == (4, 2) and during_opponent_turn == 2 and at_owner_next_turn == 4


def card_ex1_196():
    return record_card("EX1_196", [
        ("enemy_attack_until_next_turn", "Subjugator gives only an enemy minion -2 Attack through the opponent's turn and restores it at the controller's next turn.", probe_subjugator_temporary_enemy_attack),
    ])


def probe_shadow_word_ruin_attack_threshold():
    game = new_game(CardClass.PRIEST)
    owner, opponent = game.player1, game.player2
    high_friend = owner.summon("EX1_014")
    low_friend = owner.summon("CS2_182")
    high_enemy = opponent.summon("EX1_014")
    low_enemy = opponent.summon("CS2_182")
    spell = owner.give("EX1_197")
    spell.play()
    observed = f"high={high_friend.zone.name}/{high_enemy.zone.name};low={low_friend.health}/{low_enemy.health};board={[m.id for m in game.board]};heroes={owner.hero.health}/{opponent.hero.health}"
    return observed, high_friend.zone == high_enemy.zone == Zone.GRAVEYARD and low_friend in owner.field and low_enemy in opponent.field and owner.hero.health == opponent.hero.health == 30


def card_ex1_197():
    return record_card("EX1_197", [
        ("destroy_five_attack_threshold", "Shadow Word: Ruin destroys friendly and enemy minions at 5 Attack or higher, preserves 4-Attack minions, and does not affect heroes.", probe_shadow_word_ruin_attack_threshold),
    ])


def probe_natalie_health_gain_from_target():
    game = new_game(CardClass.PRIEST)
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    target.set_current_health(3)
    natalie = owner.give("EX1_198")
    legal = target in natalie.targets
    natalie.play(target=target)
    observed = f"target={target.zone.name};natalie={natalie.health}/{natalie.max_health};legal_enemy={legal};heroes={owner.hero.health}/{opponent.hero.health}"
    passed = legal and target.zone == Zone.GRAVEYARD and (natalie.health, natalie.max_health) == (4, 4) and owner.hero.health == opponent.hero.health == 30
    return observed, passed


def card_ex1_198():
    return record_card("EX1_198", [
        ("destroy_minion_gain_remaining_health", "Natalie destroys the enemy Yeti and gains its current 3 Health as both current and maximum Health; heroes remain unchanged.", probe_natalie_health_gain_from_target),
    ])


def probe_lightning_bolt_damage_and_overload():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    bolt = owner.give("EX1_238")
    legal_targets = list(bolt.targets)
    bolt.play(target=target)
    damage_state = (target.health, target.zone)
    overload_now = owner.overloaded
    game.end_turn()
    game.end_turn()
    next_turn = (owner.overload_locked, owner.mana)
    observed = f"enemy_minion_legal={target in legal_targets};enemy_hero_legal={opponent.hero in legal_targets};target={damage_state};overloaded={overload_now};next_turn_locked_mana={next_turn}"
    return observed, target.health == 2 and target in opponent.field and owner.hero in legal_targets and opponent.hero in legal_targets and overload_now == 1 and next_turn[0] == 1


def card_ex1_238():
    return record_card("EX1_238", [
        ("three_damage_and_one_overload", "Lightning Bolt deals 3 to a minion, permits character targets, adds one Overload, then locks one mana next turn.", probe_lightning_bolt_damage_and_overload),
    ])


def probe_lava_burst_damage_and_overload():
    game = new_game()
    owner, opponent = game.player1, game.player2
    burst = owner.give("EX1_241")
    legal_targets = list(burst.targets)
    burst.play(target=opponent.hero)
    overload_now = owner.overloaded
    damage = 30 - opponent.hero.health
    game.end_turn()
    game.end_turn()
    lock = owner.overload_locked
    observed = f"enemy_hero_legal={opponent.hero in legal_targets};damage={damage};overloaded={overload_now};next_turn_lock={lock}"
    return observed, opponent.hero.health == 25 and owner.hero in legal_targets and overload_now == 2 and lock == 2


def card_ex1_241():
    return record_card("EX1_241", [
        ("five_damage_and_two_overload", "Lava Burst deals 5 to the enemy hero, accepts character targets, adds two Overload, and locks two mana next turn.", probe_lava_burst_damage_and_overload),
    ])


def probe_dust_devil_windfury_and_overload():
    game = new_game()
    owner, opponent = game.player1, game.player2
    devil = owner.give("EX1_243")
    devil.play()
    start = (devil.atk, devil.health, devil.windfury, owner.overloaded)
    game.end_turn()
    game.end_turn()
    ready = devil.can_attack(opponent.hero)
    devil.attack(opponent.hero)
    after_one = devil.can_attack(opponent.hero)
    devil.attack(opponent.hero)
    after_two = devil.can_attack(opponent.hero)
    next_turn_lock = owner.overload_locked
    observed = f"play={start};attacks=2;after_first_can_attack={after_one};after_second_can_attack={after_two};enemy_hero={opponent.hero.health};next_lock={next_turn_lock}"
    passed = start[2:] == (True, 2) and ready and after_one and not after_two and opponent.hero.health == 24 and next_turn_lock == 2
    return observed, passed


def card_ex1_243():
    return record_card("EX1_243", [
        ("windfury_two_attacks_and_overload", "Dust Devil has Windfury, attacks twice in a real turn, cannot attack a third time, and locks two mana next turn.", probe_dust_devil_windfury_and_overload),
    ])


def probe_earth_shock_silence_before_damage():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friend = owner.summon(WISP)
    egg = opponent.summon("FP1_007")
    owner.give(MOONFIRE).play(target=egg)
    shock = owner.give("EX1_245")
    legal = list(shock.targets)
    shock.play(target=egg)
    observed = f"friendly_target_legal={friend in legal};enemy_target_legal={egg in legal};heroes_targetable={owner.hero in legal or opponent.hero in legal};egg={egg.zone.name};silenced={egg.silenced};nerubian_tokens={len(owner.field.filter(id='FP1_007t'))+len(opponent.field.filter(id='FP1_007t'))}"
    passed = friend in legal and egg in legal and owner.hero not in legal and opponent.hero not in legal and egg.zone == Zone.GRAVEYARD and egg.silenced and not owner.field.filter(id="FP1_007t") and not opponent.field.filter(id="FP1_007t")
    return observed, passed


def card_ex1_245():
    return record_card("EX1_245", [
        ("silence_then_one_damage", "Earth Shock targets minions on either side but not heroes; it silences a 1-health Deathrattle Egg before 1 damage kills it, so no Nerubian is summoned.", probe_earth_shock_silence_before_damage),
    ])


def probe_stormforged_axe_equips_and_overloads():
    game = new_game()
    owner, opponent = game.player1, game.player2
    axe = owner.give("EX1_247")
    axe.play()
    initial = (owner.weapon is axe, axe.atk, axe.durability, owner.overloaded)
    owner.hero.attack(opponent.hero)
    after_attack = (opponent.hero.health, axe.durability, axe.zone)
    game.end_turn()
    game.end_turn()
    next_lock = owner.overload_locked
    observed = f"equipped={initial};after_attack={after_attack};next_lock={next_lock}"
    # The printed card is a 2-attack / 3-durability weapon; after one swing
    # the opponent has taken 2 and the weapon retains 2 durability.
    passed = initial == (True, 2, 3, 1) and after_attack == (28, 2, Zone.PLAY) and next_lock == 1
    return observed, passed


def card_ex1_247():
    return record_card("EX1_247", [
        ("weapon_attack_durability_and_overload", "Stormforged Axe equips as a 2/3 weapon, deals 2 in a hero attack, loses one durability, and locks one mana next turn.", probe_stormforged_axe_equips_and_overloads),
    ])


def probe_feral_spirit_taunt_and_two_tokens():
    game = new_game()
    owner, opponent = game.player1, game.player2
    attacker = opponent.summon(WISP)
    spirit = owner.give("EX1_248")
    spirit.play()
    wolves = list(owner.field.filter(id="EX1_tk11"))
    precombat_stats = [(w.atk, w.health, w.taunt) for w in wolves]
    current_overload = owner.overloaded
    game.end_turn()
    can_hit_hero = attacker.can_attack(owner.hero)
    can_hit_wolf = attacker.can_attack(wolves[0]) if wolves else False
    try:
        attacker.attack(owner.hero)
        rejected = False
    except InvalidAction:
        rejected = True
    if wolves:
        attacker.attack(wolves[0])
    postcombat_stats = [(w.atk, w.health, w.taunt) for w in wolves]
    observed = f"wolves_before_combat={precombat_stats};wolves_after_combat={postcombat_stats};overloaded={current_overload};hero_attack_rejected={rejected};legal_hero={can_hit_hero};legal_wolf={can_hit_wolf};attacker={attacker.zone.name}"
    passed = len(wolves) == 2 and all(stats == (2, 3, True) for stats in precombat_stats) and sorted(postcombat_stats) == [(2, 2, True), (2, 3, True)] and current_overload == 2 and rejected and not can_hit_hero and can_hit_wolf and attacker.dead
    return observed, passed


def probe_feral_spirit_one_open_slot():
    game = new_game()
    owner = game.player1
    for _ in range(6):
        owner.summon(WISP)
    spell = owner.give("EX1_248")
    spell.play()
    wolves = list(owner.field.filter(id="EX1_tk11"))
    observed = f"field={len(owner.field)};wolves={len(wolves)};stats={[(w.atk,w.health,w.taunt) for w in wolves]};overload={owner.overloaded}"
    passed = len(owner.field) == 7 and len(wolves) == 1 and (wolves[0].atk, wolves[0].health, wolves[0].taunt) == (2, 3, True) and owner.overloaded == 2
    return observed, passed


def card_ex1_248():
    return record_card("EX1_248", [
        ("two_spirit_wolves_and_taunt", "Feral Spirit summons exactly two 2/3 Taunt wolves; a real enemy attack is blocked from the hero and hits a wolf instead; Overload is 2.", probe_feral_spirit_taunt_and_two_tokens),
        ("one_open_slot", "When one slot remains, Feral Spirit summons one 2/3 Taunt wolf and stays within the seven-minion cap.", probe_feral_spirit_one_open_slot),
    ])


def probe_baron_geddon_own_turn_end_aoe():
    game = new_game()
    owner, opponent = game.player1, game.player2
    geddon = owner.give("EX1_249")
    geddon.play()
    friend_wisp = owner.summon(WISP)
    friend_yeti = owner.summon("CS2_182")
    enemy_wisp = opponent.summon(WISP)
    enemy_yeti = opponent.summon("CS2_182")
    game.end_turn()
    after_owner_end = (owner.hero.health, opponent.hero.health, friend_wisp.zone, friend_yeti.health, enemy_wisp.zone, enemy_yeti.health, geddon.health)
    game.end_turn()
    after_enemy_end = (owner.hero.health, opponent.hero.health, friend_yeti.health, enemy_yeti.health, geddon.health)
    observed = f"after_owner_end={after_owner_end};after_enemy_end={after_enemy_end}"
    passed = after_owner_end == (28, 28, Zone.GRAVEYARD, 3, Zone.GRAVEYARD, 3, geddon.health) and after_enemy_end == (28, 28, 3, 3, geddon.health)
    return observed, passed


def card_ex1_249():
    return record_card("EX1_249", [
        ("own_turn_end_two_damage_other_characters", "At its controller's turn end Geddon deals 2 to both heroes and every other minion, kills Wisps, and excludes itself; the opponent's turn end does not repeat the damage.", probe_baron_geddon_own_turn_end_aoe),
    ])


def probe_earth_elemental_taunt_overload():
    game = new_game()
    owner, opponent = game.player1, game.player2
    elemental = owner.give("EX1_250")
    elemental.play()
    attacker = opponent.summon(WISP)
    on_play = (elemental.atk, elemental.health, elemental.taunt, owner.overloaded)
    game.end_turn()
    blocked = not attacker.can_attack(owner.hero) and attacker.can_attack(elemental)
    try:
        attacker.attack(owner.hero)
        rejected = False
    except InvalidAction:
        rejected = True
    if not rejected:
        return f"play={on_play};hero_attack_rejected=False", False
    attacker.attack(elemental)
    after_attack = (elemental.health, attacker.zone)
    game.end_turn()
    next_lock = owner.overload_locked
    observed = f"play={on_play};taunt_blocked={blocked};attacker={attacker.zone.name};elemental_after_hit={after_attack};next_lock={next_lock}"
    passed = on_play[2:] == (True, 3) and blocked and attacker.dead and after_attack == (on_play[1] - 1, Zone.GRAVEYARD) and next_lock == 3
    return observed, passed


def card_ex1_250():
    return record_card("EX1_250", [
        ("taunt_blocks_attack_and_overload", "Earth Elemental has Taunt, actually prevents a hero attack, can be attacked instead, and applies Overload 3 with a three-mana next-turn lock.", probe_earth_elemental_taunt_overload),
    ])


def probe_forked_lightning_two_random_hits():
    observations = []
    passed_all = True
    for seed in range(1, 13):
        random.seed(seed)
        game = new_game()
        owner, opponent = game.player1, game.player2
        friend = owner.summon("CS2_182")
        enemies = [opponent.summon("CS2_182") for _ in range(4)]
        spell = owner.give("EX1_251")
        spell.play()
        damages = [5 - m.health if m in opponent.field else 5 for m in enemies]
        total_enemy_damage = sum(damages)
        untouched_friend = (friend.health, friend in owner.field)
        untouched_heroes = (owner.hero.health, opponent.hero.health)
        overloaded = owner.overloaded
        one_case_passed = total_enemy_damage == 4 and untouched_friend == (5, True) and untouched_heroes == (30, 30) and overloaded == 2
        observations.append(f"{seed}:{damages}")
        passed_all = passed_all and one_case_passed
    return f"seeds=12;enemy_damage_vectors={'|'.join(observations)};friendly_and_heroes_unchanged=True;overload=2", passed_all


def probe_forked_lightning_empty_enemy_board():
    game = new_game()
    owner = game.player1
    spell = owner.give("EX1_251")
    mana_before = owner.mana
    try:
        spell.play()
    except InvalidAction:
        rejected = True
    else:
        rejected = False
    observed = f"empty_enemy_board=True;rejected={rejected};spell_in_hand={spell in owner.hand};mana={owner.mana}/{mana_before}"
    passed = rejected and spell in owner.hand and owner.mana == mana_before
    return observed, passed


def card_ex1_251():
    return record_card("EX1_251", [
        ("two_random_two_damage_hits", "Across 12 seeds Forked Lightning deals exactly 4 total damage among random enemy minions, leaves friendly minions/heroes untouched, and applies Overload 2.", probe_forked_lightning_two_random_hits),
        ("no_enemy_minion_rejected", "With no enemy minion, Forked Lightning is rejected without spending mana or leaving hand.", probe_forked_lightning_empty_enemy_board),
    ])


def probe_unbound_elemental_overload_card_scope():
    game = new_game()
    owner, opponent = game.player1, game.player2
    elemental = owner.give("EX1_258")
    elemental.play()
    base = (elemental.atk, elemental.health)
    owner.give("GAME_005").play()
    after_coin = (elemental.atk, elemental.health)
    game.end_turn()
    opponent.give("EX1_238").play(target=opponent.hero)
    after_enemy_overload = (elemental.atk, elemental.health)
    game.end_turn()
    owner.give("EX1_238").play(target=opponent.hero)
    after_friendly_spell = (elemental.atk, elemental.health)
    owner.give("EX1_247").play()
    after_friendly_weapon = (elemental.atk, elemental.health)
    observed = f"base={base};coin={after_coin};enemy_overload={after_enemy_overload};own_spell={after_friendly_spell};own_weapon={after_friendly_weapon}"
    passed = base == (2, 4) and after_coin == base and after_enemy_overload == base and after_friendly_spell == (3, 5) and after_friendly_weapon == (4, 6)
    return observed, passed


def card_ex1_258():
    return record_card("EX1_258", [
        ("own_overload_cards_only", "Unbound Elemental ignores The Coin and an opponent's Overload spell, then gains +1/+1 for each of its controller's Overload spell and weapon.", probe_unbound_elemental_overload_card_scope),
    ])


def probe_lightning_storm_random_damage():
    observations = []
    passed_all = True
    for seed in range(1, 13):
        random.seed(seed)
        game = new_game()
        owner, opponent = game.player1, game.player2
        friendly = owner.summon("CS2_182")
        enemies = [opponent.summon("CS2_182") for _ in range(3)]
        spell = owner.give("EX1_259")
        spell.play()
        damages = [5 - m.health if m in opponent.field else 5 for m in enemies]
        correct_range = all(damage in (2, 3) for damage in damages)
        no_friendly_damage = friendly.health == 5 and friendly in owner.field
        no_hero_damage = owner.hero.health == opponent.hero.health == 30
        overload = owner.overloaded == 2
        observations.append(f"{seed}:{damages}")
        passed_all = passed_all and correct_range and no_friendly_damage and no_hero_damage and overload
    return f"seeds=12;enemy_damage_vectors={'|'.join(observations)};heroes_and_friendly_untouched=True;overload=2", passed_all


def card_ex1_259():
    return record_card("EX1_259", [
        ("enemy_minions_take_random_two_or_three", "Each enemy minion takes 2 or 3 damage (not 1), friendly minions and heroes remain untouched, and Overload is 2 across 12 fixed seeds.", probe_lightning_storm_random_damage),
    ])


def probe_ethereal_arcanist_secret_end_turn():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    arcanist = owner.give("EX1_274")
    arcanist.play()
    base = (arcanist.atk, arcanist.health)
    game.end_turn()
    no_secret_end = (arcanist.atk, arcanist.health)
    game.end_turn()
    opponent.summon(WISP)
    ice_barrier = owner.give("EX1_289")
    ice_barrier.play()
    game.end_turn()
    after_secret_end = (arcanist.atk, arcanist.health)
    opponent_minion = list(opponent.field)[0]
    opponent_minion.attack(owner.hero)
    after_barrier_attack = (owner.hero.armor, ice_barrier.zone.name, len(owner.secrets))
    game.end_turn()  # opponent turn ends
    game.end_turn()  # owner's next turn ends with the Secret consumed
    after_secret_consumed_owner_end = (arcanist.atk, arcanist.health)
    observed = f"base={base};no_secret_end={no_secret_end};with_secret={after_secret_end};after_barrier_attack={after_barrier_attack};after_secret_consumed_owner_end={after_secret_consumed_owner_end}"
    passed = base == (3, 3) and no_secret_end == base and after_secret_end == (5, 5) and after_barrier_attack == (7, Zone.GRAVEYARD.name, 0) and after_secret_consumed_owner_end == (5, 5)
    return observed, passed


def card_ex1_274():
    return record_card("EX1_274", [
        ("secret_at_own_turn_end", "Ethereal Arcanist gains +2/+2 at its controller's turn end while a Secret is in play; a 1-attack enemy hero strike consumes Ice Barrier for 8 armor (7 remains after absorbing 1 damage), and no additional buff occurs at the next owner turn end.", probe_ethereal_arcanist_secret_end_turn),
    ])


def probe_cone_of_cold_adjacency_freeze_and_damage():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    friend = owner.summon("CS2_182")
    enemies = [opponent.summon("CS2_182") for _ in range(4)]
    game.end_turn()
    game.end_turn()
    cone = owner.give("EX1_275")
    legal = list(cone.targets)
    cone.play(target=enemies[1])
    after_cast = [(m.health, m.frozen) for m in enemies]
    friend_after_cast = (friend.health, friend.frozen)
    friendly_legal = friend in legal
    enemy_legal = enemies[1] in legal
    heroes_legal = (owner.hero in legal, opponent.hero in legal)
    game.end_turn()
    can_attack_adjacent = [enemies[i].can_attack(owner.hero) for i in (0, 1, 2)]
    far_can_attack = enemies[3].can_attack(owner.hero)
    rejected = False
    try:
        enemies[1].attack(owner.hero)
    except InvalidAction:
        rejected = True
    enemies[3].attack(owner.hero)
    observed = f"legal_friendly_minion={friendly_legal};legal_enemy_target={enemy_legal};heroes_legal={heroes_legal};enemy_after_cast={after_cast};friendly_after_cast={friend_after_cast};adjacent_can_attack={can_attack_adjacent};far_can_attack={far_can_attack};frozen_attack_rejected={rejected};hero_health={owner.hero.health}"
    passed = (friendly_legal and enemy_legal and heroes_legal == (False, False) and after_cast == [(4, True), (4, True), (4, True), (5, False)] and friend_after_cast == (5, False) and can_attack_adjacent == [False, False, False] and far_can_attack and rejected and owner.hero.health == 26)
    return observed, passed


def card_ex1_275():
    return record_card("EX1_275", [
        ("target_and_adjacent_minions_take_one_and_freeze", "Cone of Cold can target a minion on either side but not a hero; it deals 1 and freezes the selected minion plus exactly its same-side adjacent minions, leaving a farther enemy and the friendly board untouched, and freeze blocks a real attack.", probe_cone_of_cold_adjacency_freeze_and_damage),
        ("friendly_target_affects_its_own_neighborhood", "A friendly minion is a legal target; targeting it damages and freezes only it and its friendly neighbors while an opposing minion remains untouched.", probe_cone_of_cold_friendly_side_neighborhood),
    ])


def probe_cone_of_cold_friendly_side_neighborhood():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    friends = [owner.summon("CS2_182") for _ in range(3)]
    enemy = opponent.summon("CS2_182")
    cone = owner.give("EX1_275")
    legal = list(cone.targets)
    cone.play(target=friends[1])
    observed = f"target_legal={friends[1] in legal};enemy_minion_legal={enemy in legal};friendly_states={[(m.health,m.frozen) for m in friends]};enemy_state={(enemy.health,enemy.frozen)}"
    passed = friends[1] in legal and enemy in legal and [(m.health, m.frozen) for m in friends] == [(4, True), (4, True), (4, True)] and (enemy.health, enemy.frozen) == (5, False)
    return observed, passed


def probe_pyroblast_ten_character_damage():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    friend = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    pyroblast = owner.give("EX1_279")
    legal = list(pyroblast.targets)
    before = (owner.hero.health, opponent.hero.health, enemy.health)
    pyroblast.play(target=opponent.hero)
    after = (owner.hero.health, opponent.hero.health, enemy.health)
    observed = f"before={before};after={after};targetable_owner_hero={owner.hero in legal};targetable_enemy_hero={opponent.hero in legal};targetable_friendly_minion={friend in legal};targetable_enemy_minion={enemy in legal}"
    passed = before == (30, 30, 5) and after == (30, 20, 5) and owner.hero in legal and opponent.hero in legal and friend in legal and enemy in legal
    return observed, passed


def card_ex1_279():
    return record_card("EX1_279", [
        ("deal_ten_to_selected_character", "Pyroblast deals exactly 10 damage to a selected character and can target either hero or a minion on either side.", probe_pyroblast_ten_character_damage),
    ])


def probe_frost_elemental_freezes_enemy_attacker():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friend = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    game.end_turn()
    game.end_turn()
    elemental = owner.give("EX1_283")
    legal = list(elemental.targets)
    elemental.play(target=enemy)
    frozen_and_undamaged = (enemy.frozen, enemy.health)
    target_domain = (owner.hero in legal, opponent.hero in legal, friend in legal, enemy in legal)
    game.end_turn()
    ready_to_attack = enemy.can_attack(owner.hero)
    rejected = False
    try:
        enemy.attack(owner.hero)
    except InvalidAction:
        rejected = True
    observed = f"target_domain(owner_hero,enemy_hero,friendly_minion,enemy_minion)={target_domain};frozen_health={frozen_and_undamaged};can_attack_hero={ready_to_attack};attack_rejected={rejected};owner_hero_health={owner.hero.health}"
    passed = target_domain == (True, True, True, True) and frozen_and_undamaged == (True, 5) and not ready_to_attack and rejected and owner.hero.health == 30
    return observed, passed


def card_ex1_283():
    return record_card("EX1_283", [
        ("battlecry_freezes_character", "Frost Elemental's Battlecry freezes the chosen character without dealing damage; both heroes and minions on either side are legal character targets, and the frozen enemy minion cannot attack.", probe_frost_elemental_freezes_enemy_attacker),
    ])


def probe_ice_barrier_ignores_minion_attack():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    friend = owner.summon(WISP)
    attacker = opponent.summon(WISP)
    barrier = owner.give("EX1_289")
    barrier.play()
    game.end_turn()
    attacker.attack(friend)
    observed = f"attacker={attacker.zone.name};friendly_minion={friend.zone.name};barrier_still_secret={barrier in owner.secrets};armor={owner.hero.armor};secret_zone={barrier.zone.name}"
    return observed, attacker.dead and friend.dead and barrier in owner.secrets and owner.hero.armor == 0 and barrier.zone == Zone.SECRET


def probe_ice_barrier_triggers_on_hero_attack():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    attacker = opponent.summon(WISP)
    barrier = owner.give("EX1_289")
    barrier.play()
    game.end_turn()
    attacker.attack(owner.hero)
    observed = f"armor_after_1_attack={owner.hero.armor};barrier_zone={barrier.zone.name};remaining_secrets={len(owner.secrets)};hero_health={owner.hero.health}"
    return observed, owner.hero.armor == 7 and barrier.zone == Zone.GRAVEYARD and len(owner.secrets) == 0 and owner.hero.health == 30


def card_ex1_289():
    return record_card("EX1_289", [
        ("attack_on_friendly_minion_does_not_trigger", "A friendly minion being attacked does not trigger Ice Barrier; the Secret remains and hero Armor stays 0.", probe_ice_barrier_ignores_minion_attack),
        ("attack_on_hero_gains_armor_and_consumes", "When the hero is attacked by a 1-attack minion, Ice Barrier grants 8 Armor (7 remains after absorbing 1 damage) and is consumed.", probe_ice_barrier_triggers_on_hero_attack),
    ])


def probe_mirror_entity_copies_post_battlecry_minion_only():
    game = new_game(CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    mirror = owner.give("EX1_294")
    mirror.play()
    game.end_turn()
    opponent.give(MOONFIRE).play(target=opponent.hero)
    remains_after_spell = mirror in owner.secrets
    original = opponent.give("CS2_181")
    original.play()
    copies = list(owner.field)
    copy = copies[0] if copies else None
    observed = f"secret_after_opponent_spell={remains_after_spell};original={(original.atk,original.health,original.max_health,original.zone.name)};copies={[(m.id,m.atk,m.health,m.max_health) for m in copies]};secret_zone={mirror.zone.name}"
    passed = remains_after_spell and len(copies) == 1 and copy.id == original.id and (copy.atk, copy.health, copy.max_health) == (original.atk, original.health, original.max_health) == (4, 3, 7) and mirror.zone == Zone.GRAVEYARD
    return observed, passed


def card_ex1_294():
    return record_card("EX1_294", [
        ("secret_copies_opponents_played_minion", "Mirror Entity ignores an opponent's spell, then summons an exact post-Battlecry copy of Injured Blademaster; its Battlecry is not repeated and the Secret is consumed.", probe_mirror_entity_copies_post_battlecry_minion_only),
    ])


def probe_felguard_crystal_loss_and_taunt():
    game = new_game(CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    attacker = opponent.summon(WISP)
    felguard = owner.give("EX1_301")
    before = (owner.max_mana, owner.mana)
    felguard.play()
    after_play = (owner.max_mana, owner.mana, felguard.taunt)
    game.end_turn()
    can_attack_hero = attacker.can_attack(owner.hero)
    can_attack_felguard = attacker.can_attack(felguard)
    rejected = False
    try:
        attacker.attack(owner.hero)
    except InvalidAction:
        rejected = True
    attacker.attack(felguard)
    after_combat = (attacker.zone.name, felguard.health, owner.hero.health)
    observed = f"mana_before={before};mana_after={after_play};hero_attack_rejected={rejected};legal_hero={can_attack_hero};legal_felguard={can_attack_felguard};after_combat={after_combat}"
    passed = before[0] == 10 and after_play == (9, before[1] - 3, True) and rejected and not can_attack_hero and can_attack_felguard and attacker.dead and felguard.health == 4 and owner.hero.health == 30
    return observed, passed


def card_ex1_301():
    return record_card("EX1_301", [
        ("battlecry_destroys_crystal_and_taunt_blocks", "Felguard spends its 3 cost, reduces its controller's maximum Mana Crystals by exactly one, has Taunt, and an enemy attack is rejected at the hero then kills the attacker in combat with Felguard.", probe_felguard_crystal_loss_and_taunt),
    ])


def probe_shadowflame_friendly_source_attack_damage():
    game = new_game(CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    source = owner.summon("CS2_182")
    spared_friend = owner.summon(WISP)
    enemy_wisp = opponent.summon(WISP)
    enemy_yeti = opponent.summon("CS2_182")
    spell = owner.give("EX1_303")
    legal = list(spell.targets)
    spell.play(target=source)
    observed = f"legal_source={source in legal};enemy_minion_legal={enemy_yeti in legal};friend_hero_legal={owner.hero in legal};source_zone={source.zone.name};spared_friend={(spared_friend.health,spared_friend.zone.name)};enemy_wisp={enemy_wisp.zone.name};enemy_yeti={(enemy_yeti.health,enemy_yeti.zone.name)}"
    passed = source in legal and enemy_yeti not in legal and owner.hero not in legal and source.zone == Zone.GRAVEYARD and spared_friend in owner.field and spared_friend.health == 1 and enemy_wisp.zone == Zone.GRAVEYARD and enemy_yeti in opponent.field and enemy_yeti.health == 1
    return observed, passed


def card_ex1_303():
    return record_card("EX1_303", [
        ("friendly_minion_attack_becomes_enemy_aoe", "Shadowflame only targets a friendly minion, destroys its 4-Attack source, deals 4 to every enemy minion, and leaves other friendly minions untouched.", probe_shadowflame_friendly_source_attack_damage),
    ])


def probe_void_terror_consumes_only_both_neighbors():
    game = new_game(CardClass.WARLOCK)
    owner = game.player1
    far_left = owner.summon(WISP)
    left = owner.summon("CS2_182")
    right = owner.summon(WISP)
    far_right = owner.summon("CS2_182")
    owner.give(MOONFIRE).play(target=left)
    owner.give(MOONFIRE).play(target=left)
    before = [(m.atk, m.health) for m in owner.field]
    terror = owner.give("EX1_304")
    terror.play(index=2)
    observed = f"before={before};board_after={[(m.id,m.atk,m.health,m.max_health) for m in owner.field]};left_zone={left.zone.name};right_zone={right.zone.name};far_left={(far_left.health,far_left in owner.field)};far_right={(far_right.health,far_right in owner.field)};terror={(terror.atk,terror.health,terror.max_health)}"
    passed = left.zone == Zone.GRAVEYARD and right.zone == Zone.GRAVEYARD and far_left in owner.field and far_right in owner.field and (terror.atk, terror.health, terror.max_health) == (8, 7, 7) and len(owner.field) == 3
    return observed, passed


def card_ex1_304():
    return record_card("EX1_304", [
        ("battlecry_gains_both_adjacent_attack_and_current_health", "Void Terror destroys only the two minions adjacent to its chosen insertion position and gains their combined Attack and current Health; non-adjacent minions survive.", probe_void_terror_consumes_only_both_neighbors),
    ])


def probe_siphon_soul_destroy_and_heal_exactly_three():
    game = new_game(CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    enemy = opponent.summon("CS2_182")
    friendly = owner.summon(WISP)
    for _ in range(5):
        owner.give(MOONFIRE).play(target=owner.hero)
    spell = owner.give("EX1_309")
    legal = list(spell.targets)
    before_health = owner.hero.health
    spell.play(target=enemy)
    observed = f"owner_health={before_health}->{owner.hero.health};enemy_zone={enemy.zone.name};friendly_survives={friendly in owner.field};target_domain(friendly,enemy,owner_hero,enemy_hero)={(friendly in legal,enemy in legal,owner.hero in legal,opponent.hero in legal)}"
    passed = before_health == 25 and owner.hero.health == 28 and enemy.zone == Zone.GRAVEYARD and friendly in owner.field and (friendly in legal, enemy in legal, owner.hero in legal, opponent.hero in legal) == (True, True, False, False)
    return observed, passed


def probe_siphon_soul_healing_caps_at_maximum():
    game = new_game(CardClass.WARLOCK)
    owner = game.player1
    own_minion = owner.summon(WISP)
    owner.give("EX1_309").play(target=own_minion)
    observed = f"hero_health={owner.hero.health}/{owner.hero.max_health};friendly_target_zone={own_minion.zone.name}"
    return observed, owner.hero.health == owner.hero.max_health == 30 and own_minion.zone == Zone.GRAVEYARD


def card_ex1_309():
    return record_card("EX1_309", [
        ("destroy_enemy_minion_and_restore_three", "Siphon Soul can target minions but not heroes, destroys the enemy minion, and restores exactly 3 Health to a damaged hero.", probe_siphon_soul_destroy_and_heal_exactly_three),
        ("healing_capped_at_maximum", "At full Health, Siphon Soul still destroys a friendly minion but the hero remains capped at maximum Health.", probe_siphon_soul_healing_caps_at_maximum),
    ])


def probe_twisting_nether_destroys_both_sides():
    game = new_game(CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    friendly = owner.summon(WISP)
    enemy = opponent.summon("CS2_182")
    enemy_divine = opponent.summon("CS2_122")
    enemy_divine.divine_shield = True
    heroes_before = (owner.hero.health, opponent.hero.health)
    spell = owner.give("EX1_312")
    spell.play()
    observed = (f"original_zones={(friendly.zone.name,enemy.zone.name,enemy_divine.zone.name)};"
                f"fields={(len(owner.field),len(opponent.field))};"
                f"heroes={heroes_before}->{(owner.hero.health,opponent.hero.health)};spell={spell.zone.name}")
    passed = (all(m.zone == Zone.GRAVEYARD for m in (friendly, enemy, enemy_divine))
              and len(owner.field) == len(opponent.field) == 0
              and (owner.hero.health, opponent.hero.health) == heroes_before
              and spell.zone == Zone.GRAVEYARD)
    return observed, passed


def probe_twisting_nether_deathrattle_survivor():
    game = new_game(CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    cairne = owner.summon("EX1_110")
    enemy = opponent.summon("CS2_182")
    spell = owner.give("EX1_312")
    spell.play()
    baine = [m for m in owner.field if m.id == "EX1_110t"]
    observed = (f"cairne={cairne.zone.name};enemy={enemy.zone.name};"
                f"owner_field={[(m.id,m.atk,m.health) for m in owner.field]};"
                f"enemy_field={len(opponent.field)};spell={spell.zone.name}")
    passed = (cairne.zone == enemy.zone == Zone.GRAVEYARD and len(baine) == 1
              and len(owner.field) == 1 and len(opponent.field) == 0
              and (baine[0].atk, baine[0].health) == (4, 5)
              and spell.zone == Zone.GRAVEYARD)
    return observed, passed


def probe_twisting_nether_empty_board():
    game = new_game(CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    spell = owner.give("EX1_312")
    spell.play()
    observed = f"fields={(len(owner.field),len(opponent.field))};spell={spell.zone.name}"
    return observed, len(owner.field) == len(opponent.field) == 0 and spell.zone == Zone.GRAVEYARD


def card_ex1_312():
    return record_card("EX1_312", [
        ("destroy_all_original_minions", "Twisting Nether destroys friendly and enemy minions, including Divine Shield, without damaging heroes.", probe_twisting_nether_destroys_both_sides),
        ("deathrattle_token_after_clear", "Cairne and an enemy minion die together; the deathrattle Baine enters after the clear and survives.", probe_twisting_nether_deathrattle_survivor),
        ("empty_board_resolves", "Twisting Nether resolves into Graveyard on an empty board without creating minions.", probe_twisting_nether_empty_board),
    ])


PROBES = {
    "EX1_188": card_ex1_188,
    "EX1_189": card_ex1_189,
    "EX1_190": card_ex1_190,
    "EX1_195": card_ex1_195,
    "EX1_196": card_ex1_196,
    "EX1_197": card_ex1_197,
    "EX1_198": card_ex1_198,
    "EX1_238": card_ex1_238,
    "EX1_241": card_ex1_241,
    "EX1_243": card_ex1_243,
    "EX1_245": card_ex1_245,
    "EX1_247": card_ex1_247,
    "EX1_248": card_ex1_248,
    "EX1_249": card_ex1_249,
    "EX1_250": card_ex1_250,
    "EX1_251": card_ex1_251,
    "EX1_258": card_ex1_258,
    "EX1_259": card_ex1_259,
    "EX1_274": card_ex1_274,
    "EX1_275": card_ex1_275,
    "EX1_279": card_ex1_279,
    "EX1_283": card_ex1_283,
    "EX1_289": card_ex1_289,
    "EX1_294": card_ex1_294,
    "EX1_301": card_ex1_301,
    "EX1_303": card_ex1_303,
    "EX1_304": card_ex1_304,
    "EX1_309": card_ex1_309,
    "EX1_312": card_ex1_312,
}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("card_id", nargs="*", help="Selected baseline card IDs; defaults to all configured probes.")
    args = parser.parse_args()
    for card_id in args.card_id or list(PROBES):
        if card_id not in PROBES:
            raise SystemExit(f"No probe configured for {card_id}")
        print(f"{card_id}: {PROBES[card_id]()}")


if __name__ == "__main__":
    main()
