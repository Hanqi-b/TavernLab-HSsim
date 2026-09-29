"""Card-specific behavior probes for eight remaining Basic YELLOW cards.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_j.py

Every case builds a fresh match, resolves the card, and asserts visible game
state. Text is transcribed from CardDefs.xml for the 17.6 card snapshot; notes
also identify implementation, old tests, and prior audit evidence.
"""

import csv
import json
import logging
from pathlib import Path

import fireplace.cards as carddb
from fireplace.exceptions import InvalidAction
from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


OUT = Path(__file__).with_suffix(".csv")
FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
ROWS = []


CONTEXT = {
    "CS2_237": (
        "Whenever you summon a Beast, draw a card. / 每当你召唤一个野兽，抽一张牌。",
        "fireplace/cards/classic/hunter.py:8",
        "tests/test_classic.py::test_starving_buzzard (Beast draws); tests/test_mechanics.py::test_morph (no draw after transformation); tests/test_misc.py::test_event_queue_summon",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior smoke only, no cited direct effect-evidence row.",
    ),
    "DS1_178": (
        "Your Beasts have Charge. / 你的野兽获得冲锋。",
        "fireplace/cards/classic/hunter.py:38",
        "No direct DS1_178 assertion found in tests.",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior smoke only.",
    ),
    "DS1_183": (
        "Deal $3 damage to two random enemy minions. / 随机对两个敌方随从造成$3点伤害。",
        "fireplace/cards/classic/hunter.py:86",
        "No direct DS1_183 assertion found in tests.",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior smoke only.",
    ),
    "DS1_185": (
        "Deal $2 damage. / 造成$2点伤害。",
        "fireplace/cards/classic/hunter.py:99",
        "tests/test_wog.py::test_undercity_huckster (Arcane Shot resolves against a minion, but does not assert damage).",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior smoke plus target-prerequisite sweep, no direct damage assertion.",
    ),
    "EX1_306": (
        "Battlecry: Discard a random card. / 战吼：随机弃一张牌。",
        "fireplace/cards/classic/warlock.py:43",
        "tests/test_mechanics.py::test_card_draw (hand shrinks by minion plus one discarded card; no selected-card assertion).",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior smoke only, no direct discard evidence.",
    ),
    "EX1_308": (
        "Deal $4 damage. Discard a random card. / 造成$4点伤害，随机弃一张牌。",
        "fireplace/cards/classic/warlock.py:148",
        "later_stage_probes.csv#DISCARD-01 (4 damage and one spare card discarded); targeting_prereq_sweep.csv (missing target rejected).",
        "card_mechanism.csv marks spell resolution/targeting/discard GREEN from DISCARD-01 but Random effects remains YELLOW; one spare card did not test choice among candidates.",
    ),
    "EX1_399": (
        "Whenever this minion takes damage, gain +3 Attack. / 每当该随从受到伤害，便获得+3攻击力。",
        "fireplace/cards/classic/neutral_common.py:69",
        "tests/test_classic.py::test_inner_fire (buff interaction, not damage trigger); tests/test_mechanics.py::test_divine_shield (shield prevents trigger); tests/test_auchenai_soulpriest.py::test_auchenai_soulpriest_divine_shield.",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior smoke only, no normal damage-trigger assertion.",
    ),
    "EX1_400": (
        "Deal $1 damage to ALL minions. / 对所有随从造成$1点伤害。",
        "fireplace/cards/classic/warrior.py:136",
        "tests/test_classic.py::test_whirlwind (both sides and hero health); tests/test_classic.py::test_armorsmith; tests/test_gvg.py::test_dr_boom; tests/test_wog.py::test_blood_warriors.",
        "basic_quality.csv and card_mechanism.csv: YELLOW; prior cited tests assert partial damage/trigger interactions, not a complete per-card scope/death-state check.",
    ),
}


def new_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.discard_hand()
    game.player2.discard_hand()
    return game


def summon(player, card_id):
    return player.summon(card_id)


def reject_invalid_action(action):
    try:
        action()
    except InvalidAction:
        return
    raise AssertionError("expected InvalidAction, but action was accepted")


def make_notes(card_id, scenario):
    text, implementation, existing, prior = CONTEXT[card_id]
    return (
        f"text={text}; implementation={implementation}; existing={existing}; "
        f"prior audit={prior}; scenario={scenario}"
    )


def record(card_id, case_id, expected, fn, scenario):
    try:
        observed = fn()
        outcome = "pass"
    except AssertionError as error:
        observed = f"assertion failed: {error}"
        outcome = "confirmed_error"
    except Exception as error:
        observed = f"{type(error).__name__}: {error}"
        outcome = "inconclusive"
    ROWS.append(
        {
            "card_id": card_id,
            "case_id": case_id,
            "expected": expected,
            "observed": json.dumps(observed, ensure_ascii=False, sort_keys=True)
            if isinstance(observed, dict)
            else str(observed),
            "outcome": outcome,
            "notes": make_notes(card_id, scenario),
        }
    )


# CS2_237 — trigger only for a Beast summoned by its controller, while active.
def buzzard_trigger_domain_and_draw_zone():
    game = new_game()
    player, opponent = game.player1, game.player2
    known_draw = player.give("CS2_231")
    known_draw.shuffle_into_deck()
    buzzard = player.give("CS2_237")
    buzzard.play()
    # The Buzzard itself is a Beast, but its own entry is not a draw trigger.
    assert not player.hand and known_draw in player.deck
    summon(opponent, "CS2_119")  # Opponent's Beast must not trigger this Buzzard.
    summon(player, "CS2_182")  # Controller's non-Beast must not trigger it.
    assert not player.hand and known_draw in player.deck
    summon(player, "CS2_119")  # Controller's Beast draws the known deck card.
    assert player.hand == [known_draw] and known_draw.zone == Zone.HAND
    assert not player.deck and buzzard.zone == Zone.PLAY
    return {
        "buzzard_zone": buzzard.zone.name,
        "drawn_id": player.hand[0].id,
        "drawn_zone": player.hand[0].zone.name,
        "deck_size": len(player.deck),
        "friendly_field": [m.id for m in player.field],
        "enemy_field": [m.id for m in opponent.field],
    }


def buzzard_stops_triggering_after_death():
    game = new_game()
    player = game.player1
    buzzard = player.give("CS2_237")
    buzzard.play()
    kill = player.give("CS2_029")
    kill.play(target=buzzard)
    assert buzzard.dead and buzzard.zone == Zone.GRAVEYARD
    known_draw = player.give("CS2_231")
    known_draw.shuffle_into_deck()
    summon(player, "CS2_119")
    assert not player.hand and player.deck == [known_draw]
    return {"buzzard_zone": buzzard.zone.name, "hand": len(player.hand), "deck": [c.id for c in player.deck]}


# DS1_178 — current/future friendly Beasts gain Charge; non-Beasts/opponent
# Beasts do not; removing the aura source removes the granted keyword.
def rhino_aura_grants_charge_to_beasts_only():
    game = new_game()
    player, opponent = game.player1, game.player2
    existing_beast = summon(player, "CS2_119")
    friendly_nonbeast = summon(player, "CS2_182")
    enemy_beast = summon(opponent, "CS2_119")
    rhino = player.give("DS1_178")
    rhino.play()
    later_beast = summon(player, "CS2_119")
    assert existing_beast.charge and rhino.charge and later_beast.charge
    assert existing_beast.can_attack() and later_beast.can_attack() and rhino.can_attack()
    assert not friendly_nonbeast.charge and not enemy_beast.charge
    enemy_health = opponent.hero.health
    existing_beast.attack(target=opponent.hero)
    assert opponent.hero.health == enemy_health - existing_beast.atk
    return {
        "existing_beast_charge": existing_beast.charge,
        "rhino_self_charge": rhino.charge,
        "later_beast_charge": later_beast.charge,
        "friendly_nonbeast_charge": friendly_nonbeast.charge,
        "enemy_beast_charge": enemy_beast.charge,
        "enemy_hero_health": opponent.hero.health,
    }


def rhino_silence_removes_charge_aura():
    game = new_game()
    player = game.player1
    beast = summon(player, "CS2_119")
    rhino = player.give("DS1_178")
    rhino.play()
    assert beast.charge and beast.can_attack()
    player.give("EX1_332").play(target=rhino)
    assert not beast.charge and not beast.can_attack()
    assert rhino.zone == Zone.PLAY and not rhino.charge
    return {"beast_charge_after_silence": beast.charge, "beast_can_attack": beast.can_attack(), "rhino_zone": rhino.zone.name}


# DS1_183 — two distinct random enemy minions take 3; eligible set and
# singleton behavior are asserted separately.
def multi_shot_hits_two_distinct_random_enemy_minions():
    candidate_ids = {"CS2_119", "CS2_182"}
    selected_sets = []
    for seed in range(12):
        game = new_game()
        game.random.seed(seed)
        # Keep every candidate above 3 Health so each selected target survives
        # and its damage/zone can be checked without conflating death handling.
        enemies = [summon(game.player2, cid) for cid in ("CS2_119", "CS2_182", "CS2_119")]
        friendly = summon(game.player1, "CS2_182")
        heroes_before = (game.player1.hero.health, game.player2.hero.health)
        spell = game.player1.give("DS1_183")
        spell.play()
        hit = [m for m in enemies if m.damage == 3]
        untouched = [m for m in enemies if m.damage == 0]
        assert len(hit) == 2 and len(untouched) == 1, f"expected two hit targets, got {[m.damage for m in enemies]}"
        assert all(m.health == m.max_health - 3 and m.zone == Zone.PLAY for m in hit), f"wrong hit health/zone: {[(m.health, m.max_health, m.zone.name) for m in hit]}"
        assert friendly.damage == 0, f"friendly minion took {friendly.damage} damage"
        assert (game.player1.hero.health, game.player2.hero.health) == heroes_before, "hero was damaged"
        assert {m.id for m in hit} <= candidate_ids, f"ineligible card ids selected: {[m.id for m in hit]}"
        assert spell.zone == Zone.GRAVEYARD, f"spell zone={spell.zone.name}"
        selected_sets.append(tuple(sorted(enemies.index(m) for m in hit)))
    assert len(set(selected_sets)) == 3, f"fixed seeds must cover all three 2-target combinations: {selected_sets}"
    return {"games": len(selected_sets), "selected_pairs": selected_sets, "distinct_pairs": len(set(selected_sets))}


def multi_shot_with_one_enemy_minion_hits_available_target_once():
    game = new_game()
    target = summon(game.player2, "CS2_182")
    spell = game.player1.give("DS1_183")
    assert spell.is_playable()
    spell.play()
    assert target.damage == 3 and target.health == 2 and target.zone == Zone.PLAY
    return {"playable_with_one": True, "target_health": target.health, "damage": target.damage}


def multi_shot_requires_an_enemy_minion():
    game = new_game()
    spell = game.player1.give("DS1_183")
    assert not spell.is_playable()
    reject_invalid_action(lambda: spell.play())
    assert spell.zone == Zone.HAND and not game.player2.field
    return {"playable_without_enemy_minions": spell.is_playable(), "spell_zone": spell.zone.name}


# DS1_185 — target is any character, exact two damage, and target required.
def arcane_shot_deals_two_to_enemy_minion():
    game = new_game()
    target = summon(game.player2, "CS2_182")
    spell = game.player1.give("DS1_185")
    spell.play(target=target)
    assert target.health == 3 and target.damage == 2 and target.zone == Zone.PLAY
    return {"health": target.health, "damage": target.damage, "zone": target.zone.name}


def arcane_shot_can_hit_friendly_hero():
    game = new_game()
    own_hero, enemy_hero = game.player1.hero, game.player2.hero
    before = own_hero.health
    spell = game.player1.give("DS1_185")
    assert own_hero in spell.targets
    spell.play(target=own_hero)
    assert own_hero.health == before - 2 and enemy_hero.health == 30
    return {"own_hero": f"{before}->{own_hero.health}", "enemy_hero": enemy_hero.health}


def arcane_shot_requires_a_target():
    game = new_game()
    spell = game.player1.give("DS1_185")
    before = game.player2.hero.health
    reject_invalid_action(lambda: spell.play())
    assert spell.zone == Zone.HAND and game.player2.hero.health == before
    return {"spell_zone": spell.zone.name, "enemy_hero_health": before}


# EX1_306 — battlecry discards exactly one other hand card selected randomly.
def felstalker_discards_one_random_remaining_hand_card():
    candidates = ("CS2_231", "CS2_029", "CS2_182")
    selected_ids = []
    for seed in range(12):
        game = new_game()
        game.random.seed(seed)
        player = game.player1
        cards = [player.give(cid) for cid in candidates]
        felstalker = player.give("EX1_306")
        felstalker.play()
        discarded = [card for card in cards if card.zone == Zone.REMOVEDFROMGAME]
        remaining = [card for card in cards if card.zone == Zone.HAND]
        assert len(discarded) == 1 and len(remaining) == 2
        assert felstalker.zone == Zone.PLAY and felstalker in player.field
        assert discarded[0].id in candidates
        selected_ids.append(discarded[0].id)
    assert set(selected_ids) == set(candidates), f"fixed seeds must select all three candidate card IDs: {selected_ids}"
    return {"games": len(selected_ids), "discarded_ids": selected_ids, "distinct_cards": sorted(set(selected_ids))}


def felstalker_with_no_other_hand_card_keeps_minion():
    game = new_game()
    felstalker = game.player1.give("EX1_306")
    felstalker.play()
    assert felstalker.zone == Zone.PLAY and felstalker in game.player1.field
    assert not game.player1.hand
    return {"felstalker_zone": felstalker.zone.name, "hand": len(game.player1.hand), "field": [m.id for m in game.player1.field]}


# EX1_308 — $4 target damage plus one random discard from the remaining hand.
def soulfire_damage_and_random_discard_candidates():
    candidates = ("CS2_231", "CS2_029", "CS2_182")
    discarded_ids = []
    for seed in range(12):
        game = new_game()
        game.random.seed(seed)
        player = game.player1
        cards = [player.give(cid) for cid in candidates]
        spell = player.give("EX1_308")
        enemy_hero = game.player2.hero
        spell.play(target=enemy_hero)
        discarded = [card for card in cards if card.zone == Zone.REMOVEDFROMGAME]
        remaining = [card for card in cards if card.zone == Zone.HAND]
        assert enemy_hero.health == 26
        assert spell.zone == Zone.GRAVEYARD
        assert len(discarded) == 1 and len(remaining) == 2
        assert discarded[0].id in candidates
        discarded_ids.append(discarded[0].id)
    assert set(discarded_ids) == set(candidates), f"fixed seeds must select all three candidate card IDs: {discarded_ids}"
    return {"games": len(discarded_ids), "enemy_hero_health": 26, "discarded_ids": discarded_ids, "distinct_cards": sorted(set(discarded_ids))}


def soulfire_can_target_friendly_hero_and_discards():
    game = new_game()
    player = game.player1
    candidates = [player.give(cid) for cid in ("CS2_231", "CS2_029", "CS2_182")]
    spell = player.give("EX1_308")
    own_hero, enemy_hero = player.hero, game.player2.hero
    own_before, enemy_before = own_hero.health, enemy_hero.health
    spell.play(target=own_hero)
    discarded = [card for card in candidates if card.zone == Zone.REMOVEDFROMGAME]
    remaining = [card for card in candidates if card.zone == Zone.HAND]
    assert own_hero.health == own_before - 4
    assert enemy_hero.health == enemy_before
    assert len(discarded) == 1 and len(remaining) == 2
    assert spell.zone == Zone.GRAVEYARD
    assert set(player.hand) == set(remaining)
    return {
        "own_hero": f"{own_before}->{own_hero.health}",
        "enemy_hero": enemy_hero.health,
        "discarded_id": discarded[0].id,
        "remaining_hand": [card.id for card in player.hand],
        "spell_zone": spell.zone.name,
    }


def soulfire_without_spare_card_still_deals_four():
    game = new_game()
    spell = game.player1.give("EX1_308")
    enemy_hero = game.player2.hero
    spell.play(target=enemy_hero)
    assert enemy_hero.health == 26 and spell.zone == Zone.GRAVEYARD
    assert not game.player1.hand
    return {"enemy_hero_health": enemy_hero.health, "spell_zone": spell.zone.name, "remaining_hand": len(game.player1.hand)}


def soulfire_requires_target_without_spending_card():
    game = new_game()
    spell = game.player1.give("EX1_308")
    before = game.player2.hero.health
    reject_invalid_action(lambda: spell.play())
    assert spell.zone == Zone.HAND and game.player2.hero.health == before
    return {"spell_zone": spell.zone.name, "enemy_hero_health": before}


# EX1_399 — one +3 Attack per actual damage event, including combat/area hits;
# Divine Shield prevents the trigger.
def gurubashi_gains_three_on_combat_damage_then_on_whirlwind():
    game = new_game()
    berserker = summon(game.player1, "EX1_399")
    attacker = summon(game.player2, "CS2_182")  # 4/5 Yeti.
    game.end_turn()
    assert attacker.can_attack()
    attacker.attack(target=berserker)
    assert berserker.atk == 5 and berserker.health == 3
    assert attacker.health == 3
    game.end_turn()
    game.player1.give("EX1_400").play()
    assert berserker.atk == 8 and berserker.health == 2
    assert attacker.health == 2
    return {"after_combat": {"berserker_atk": 5, "berserker_health": 3, "attacker_health": 3}, "after_whirlwind": {"berserker_atk": berserker.atk, "berserker_health": berserker.health, "attacker_health": attacker.health}}


def gurubashi_divine_shield_blocks_damage_trigger():
    game = new_game()
    berserker = summon(game.player1, "EX1_399")
    game.player1.give("EX1_371").play(target=berserker)
    game.player1.give("EX1_400").play()
    assert not berserker.divine_shield and berserker.health == 7 and berserker.atk == 2
    game.player1.give("EX1_400").play()
    assert berserker.health == 6 and berserker.atk == 5
    return {"after_shielded_hit": {"shield": False, "health": 7, "atk": 2}, "after_real_damage": {"shield": berserker.divine_shield, "health": berserker.health, "atk": berserker.atk}}


# EX1_400 — one damage to every minion on both sides; not heroes. Include death,
# Divine Shield, and Gurubashi trigger as observable secondary state.
def whirlwind_hits_all_minions_not_heroes():
    game = new_game()
    friendly_yeti = summon(game.player1, "CS2_182")
    friendly_wisp = summon(game.player1, "CS2_231")
    berserker = summon(game.player1, "EX1_399")
    shielded = summon(game.player1, "EX1_020")
    enemy_yeti = summon(game.player2, "CS2_182")
    enemy_wisp = summon(game.player2, "CS2_231")
    game.player1.give("EX1_371").play(target=shielded)
    heroes_before = (game.player1.hero.health, game.player2.hero.health)
    spell = game.player1.give("EX1_400")
    spell.play()
    assert friendly_yeti.health == 4 and friendly_yeti.damage == 1
    assert enemy_yeti.health == 4 and enemy_yeti.damage == 1
    assert friendly_wisp.dead and friendly_wisp.zone == Zone.GRAVEYARD
    assert enemy_wisp.dead and enemy_wisp.zone == Zone.GRAVEYARD
    assert not shielded.divine_shield and shielded.health == 1
    assert berserker.health == 6 and berserker.atk == 5
    assert (game.player1.hero.health, game.player2.hero.health) == heroes_before
    assert spell.zone == Zone.GRAVEYARD
    return {
        "friendly_yeti": [friendly_yeti.health, friendly_yeti.damage],
        "enemy_yeti": [enemy_yeti.health, enemy_yeti.damage],
        "friendly_wisp": friendly_wisp.zone.name,
        "enemy_wisp": enemy_wisp.zone.name,
        "shielded": {"health": shielded.health, "shield": shielded.divine_shield},
        "berserker": {"health": berserker.health, "atk": berserker.atk},
        "heroes": [game.player1.hero.health, game.player2.hero.health],
        "spell": spell.zone.name,
    }


CASES = [
    ("CS2_237", "CS2_237_trigger_domain", "Buzzard's own entry, opponent Beast, and friendly non-Beast draw nothing; a friendly Beast draws the known deck card to hand.", buzzard_trigger_domain_and_draw_zone, "trigger source, Beast predicate, draw card identity/zone"),
    ("CS2_237", "CS2_237_after_death", "After Buzzard dies, a later friendly Beast does not draw; minion is in GRAVEYARD.", buzzard_stops_triggering_after_death, "listener lifetime after trigger source leaves board"),
    ("DS1_178", "DS1_178_beasts_only", "Existing, self, and later friendly Beasts gain usable Charge; friendly non-Beast and enemy Beast do not.", rhino_aura_grants_charge_to_beasts_only, "current/future aura recipients, source itself, side/type boundary, actual attack"),
    ("DS1_178", "DS1_178_silence_update", "Silencing Rhino removes granted Charge and attack readiness from existing Beast.", rhino_silence_removes_charge_aura, "aura cleanup/update after source is silenced"),
    ("DS1_183", "DS1_183_random_two", "Across fixed seeds, all three possible pairs among three enemy minions are observed; each game hits exactly two distinct minions for 3; friendly minion and heroes are unchanged.", multi_shot_hits_two_distinct_random_enemy_minions, "random eligible-set and all distinct-target pairings across 12 fixed seeds"),
    ("DS1_183", "DS1_183_single_enemy", "With one enemy minion the spell is playable and that sole eligible minion takes 3 once.", multi_shot_with_one_enemy_minion_hits_available_target_once, "single-viable-target behavior"),
    ("DS1_183", "DS1_183_no_enemy", "With no enemy minions the spell is unplayable and remains in hand.", multi_shot_requires_an_enemy_minion, "zero-target requirement"),
    ("DS1_185", "DS1_185_minion_damage", "Enemy minion takes exactly 2 damage and remains in PLAY.", arcane_shot_deals_two_to_enemy_minion, "exact damage and minion zone"),
    ("DS1_185", "DS1_185_friendly_hero", "Friendly hero is a legal target and alone takes 2 damage.", arcane_shot_can_hit_friendly_hero, "unrestricted character targeting"),
    ("DS1_185", "DS1_185_requires_target", "No-target play is rejected without spending the spell or changing hero health.", arcane_shot_requires_a_target, "required target branch"),
    ("EX1_306", "EX1_306_random_discard", "Across fixed seeds, each of the three other hand-card IDs is selected at least once; exactly one is discarded per game and Felstalker enters PLAY.", felstalker_discards_one_random_remaining_hand_card, "Battlecry timing, hand candidates/zones, all candidate IDs observed across 12 fixed seeds"),
    ("EX1_306", "EX1_306_empty_hand", "With no other hand card, Felstalker still enters PLAY and nothing is discarded.", felstalker_with_no_other_hand_card_keeps_minion, "empty discard-pool branch"),
    ("EX1_308", "EX1_308_damage_random_discard", "Across fixed seeds, each of the three remaining hand-card IDs is selected at least once; enemy hero takes exactly 4, one card is discarded per game, and spell resolves to GRAVEYARD.", soulfire_damage_and_random_discard_candidates, "damage plus random choice from post-cast hand; all candidate IDs observed across 12 fixed seeds"),
    ("EX1_308", "EX1_308_friendly_target", "Friendly hero takes exactly 4, enemy hero is unchanged, exactly one candidate card is discarded, and spell resolves to GRAVEYARD.", soulfire_can_target_friendly_hero_and_discards, "actual friendly-character target plus damage and remaining-hand/discard zones"),
    ("EX1_308", "EX1_308_no_spare_card", "With no spare hand card, target still takes 4 and spell resolves normally.", soulfire_without_spare_card_still_deals_four, "empty discard-pool branch"),
    ("EX1_308", "EX1_308_requires_target", "No-target play is rejected without spending the spell or changing hero health.", soulfire_requires_target_without_spending_card, "required target branch"),
    ("EX1_399", "EX1_399_damage_events", "A 4-damage combat event grants exactly +3 Attack once; a later 1-damage Whirlwind grants another +3.", gurubashi_gains_three_on_combat_damage_then_on_whirlwind, "actual combat source, amount-independent trigger, repeated event"),
    ("EX1_399", "EX1_399_divine_shield", "Damage absorbed by Divine Shield grants no Attack; next actual 1 damage grants exactly +3 Attack.", gurubashi_divine_shield_blocks_damage_trigger, "prevented versus actual damage branch"),
    ("EX1_400", "EX1_400_all_minions", "One damage reaches every friendly/enemy minion; lethal minions die, shield absorbs, Gurubashi triggers, and heroes remain unchanged.", whirlwind_hits_all_minions_not_heroes, "complete side scope, death processing, Divine Shield, dependent trigger, hero exclusion"),
]


def main():
    carddb.filter(collectible=True)
    for card_id, case_id, expected, fn, scenario in CASES:
        record(card_id, case_id, expected, fn, scenario)
    with OUT.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    by_card = {}
    for row in ROWS:
        by_card.setdefault(row["card_id"], {}).setdefault(row["outcome"], 0)
        by_card[row["card_id"]][row["outcome"]] += 1
    for card_id, counts in by_card.items():
        print(f"{card_id}: {counts}")
    print(f"Wrote {len(ROWS)} cases to {OUT}")
    if any(row["outcome"] == "confirmed_error" for row in ROWS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
