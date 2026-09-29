"""Card-specific Basic-card behavior probes for the current audit.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_c.py

Each testcase below uses a separate minimal game and asserts observable state.
The Chinese and English card texts are transcribed from CardDefs.xml for the
17.6 card snapshot; implementation, prior audit row, and existing test context
are included in each CSV row's notes.
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


# Texts are from fireplace/cards/CardDefs.xml; source and prior evidence point
# into the Basic card-quality/audit rows. Existing tests named here were read
# before designing these new card-specific cases.
CONTEXT = {
    "CS1_130": (
        "Deal $3 damage to a minion. / 对一个随从造成$3点伤害。",
        "fireplace/cards/classic/priest.py:173",
        "tests/test_classic.py::test_preparation (mana only); tests/test_gvg.py::test_gazlowe (spell interaction)",
    ),
    "CS2_003": (
        "Put a copy of a random card in your opponent's hand into your hand. / 随机复制对手手牌中的一张牌，将其置入你的手牌。",
        "fireplace/cards/classic/priest.py:183",
        "tests/test_classic.py::test_mind_vision (empty hand and copied id/creator)",
    ),
    "CS2_004": (
        "Give a minion +2 Health. / 使一个随从获得+2生命值。",
        "fireplace/cards/classic/priest.py:131",
        "tests/test_classic.py::test_power_word_shield (+2 health, then Silence); tests/test_blackrock.py::test_dragonkin_sorcerer; tests/test_misc.py::test_silence",
    ),
    "CS2_005": (
        "Give your hero +2 Attack this turn. Gain 2 Armor. / 使你的英雄获得2点护甲值，并在本回合中获得+2攻击力。",
        "fireplace/cards/classic/druid.py:107",
        "No direct CS2_005 reference found in tests.",
    ),
    "CS2_007": (
        "Restore #8 Health. / 恢复#8点生命值。",
        "fireplace/cards/classic/druid.py:116",
        "No direct CS2_007 reference found in tests.",
    ),
    "CS2_008": (
        "Deal $1 damage. / 造成$1点伤害。",
        "fireplace/cards/classic/druid.py:123",
        "tests/test_gangs.py::test_weasel_tunneler (lethal interaction, not a general damage assertion)",
    ),
    "CS2_024": (
        "Deal $3 damage to a character and Freeze it. / 对一个角色造成$3点伤害，并使其冻结。",
        "fireplace/cards/classic/mage.py:72",
        "No direct CS2_024 reference found in tests.",
    ),
    "CS2_027": (
        "Summon two 0/2 minions with Taunt. / 召唤两个0/2，并具有嘲讽的随从。",
        "fireplace/cards/classic/mage.py:91",
        "tests/test_classic.py::test_mirror_image (count and ids only)",
    ),
    "CS2_032": (
        "Deal $4 damage to all enemy minions. / 对所有敌方随从造成$4点伤害。",
        "fireplace/cards/classic/mage.py:118",
        "tests/test_karazhan.py::test_cat_trick (spell interaction, not resolved AoE state)",
    ),
    "CS2_033": (
        "Freeze any character damaged by this minion. / 冻结任何受到该随从伤害的角色。",
        "fireplace/cards/classic/mage.py:8",
        "tests/test_classic.py::test_water_elemental (freeze after combat damage); tests/test_icecrown.py::test_defile; tests/test_ungoro.py::test_swamp_king_dred",
    ),
    "CS2_037": (
        "Deal $1 damage to an enemy character and Freeze it. / 对一个敌方角色造成$1点伤害，并使其冻结。",
        "fireplace/cards/classic/shaman.py:54",
        "tests/test_mechanics.py::test_freeze (freeze timing, not exact damage/target boundaries)",
    ),
}


def new_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    # Empty-deck games may start with The Coin. Keep each testcase's hand
    # deterministic and make player1 the actor for card resolution.
    game.player1.discard_hand()
    game.player2.discard_hand()
    return game


def summon(player, card_id, damage=0):
    minion = player.summon(card_id)
    if damage:
        minion.damage = damage
    return minion


def reject_invalid_action(action):
    try:
        action()
    except InvalidAction:
        return
    raise AssertionError("expected InvalidAction, but action was accepted")


def context_notes(card_id, scenario):
    text, source, existing = CONTEXT[card_id]
    return (
        f"text={text}; implementation={source}; existing={existing}; "
        f"prior audit=basic_quality.csv/card_mechanism.csv: YELLOW, only generic-play-smoke "
        f"(except separately noted targeting-prerequisite evidence); scenario={scenario}"
    )


def record(card_id, case_id, expected, fn, scenario):
    try:
        observed = fn()
        outcome = "pass"
    except AssertionError as error:
        observed = f"assertion failed: {error}"
        outcome = "confirmed_error"
    except Exception as error:  # Keep incomplete setup/API failures distinct.
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
            "notes": context_notes(card_id, scenario),
        }
    )


# CS1_130 — minion-only targeting, exact 3 damage, and death processing.
def smite_survives_at_exact_health():
    game = new_game()
    victim = summon(game.player2, "CS2_182")  # 4/5 Yeti.
    spell = game.player1.give("CS1_130")
    assert victim in spell.targets and game.player2.hero not in spell.targets
    spell.play(target=victim)
    assert victim.zone == Zone.PLAY and victim.health == 2 and victim.damage == 3
    assert spell.zone == Zone.GRAVEYARD
    return {"victim": f"{victim.zone.name},4/{victim.health},damage={victim.damage}", "spell": spell.zone.name}


def smite_kills_three_health_minion():
    game = new_game()
    victim = summon(game.player2, "CS2_231")  # 1 health, lethal under 3 damage.
    spell = game.player1.give("CS1_130")
    spell.play(target=victim)
    assert victim.dead and victim.zone == Zone.GRAVEYARD
    return {"victim_dead": victim.dead, "victim_zone": victim.zone.name}


def smite_can_target_friendly_minion():
    game = new_game()
    victim = summon(game.player1, "CS2_182")
    spell = game.player1.give("CS1_130")
    assert victim in spell.targets
    spell.play(target=victim)
    assert victim.health == 2 and victim.damage == 3 and victim.zone == Zone.PLAY
    return {"friendly_target": True, "health": victim.health, "damage": victim.damage, "zone": victim.zone.name}


def smite_rejects_hero():
    game = new_game()
    legal_minion = summon(game.player2, "CS2_182")
    hero = game.player2.hero
    spell = game.player1.give("CS1_130")
    before = hero.health
    assert legal_minion in spell.targets and hero not in spell.targets
    reject_invalid_action(lambda: spell.play(target=hero))
    assert spell.zone == Zone.HAND and hero.health == before
    return {"hero_health": hero.health, "spell_zone": spell.zone.name, "hero_in_targets": hero in spell.targets}


# CS2_003 — random selection must copy a card entity and leave the source.
def mind_vision_copies_one_opponent_card():
    game = new_game()
    opponent_cards = [game.player2.give(cid) for cid in ("CS2_231", "CS2_029", "CS2_024")]
    spell = game.player1.give("CS2_003")
    spell.play()
    assert len(game.player1.hand) == 1
    copied = game.player1.hand[0]
    source_ids = {card.id for card in opponent_cards}
    assert copied.id in source_ids
    assert copied.creator is spell and copied.zone == Zone.HAND
    assert len(game.player2.hand) == 3 and all(card.zone == Zone.HAND for card in opponent_cards)
    return {"copied_id": copied.id, "source_ids": sorted(source_ids), "source_hand": [c.id for c in game.player2.hand], "creator": copied.creator.id}


def mind_vision_empty_opponent_hand():
    game = new_game()
    spell = game.player1.give("CS2_003")
    spell.play()
    assert not game.player1.hand and not game.player2.hand
    assert spell.zone == Zone.GRAVEYARD
    return {"own_hand": len(game.player1.hand), "opponent_hand": len(game.player2.hand), "spell": spell.zone.name}


def mind_vision_uses_random_candidate_across_seeded_games():
    candidate_ids = {"CS2_231", "CS2_029", "CS2_024"}
    selected = []
    for seed in range(12):
        game = new_game()
        game.random.seed(seed)
        for card_id in sorted(candidate_ids):
            game.player2.give(card_id)
        game.player1.give("CS2_003").play()
        selected.append(game.player1.hand[0].id)
    assert set(selected) <= candidate_ids
    assert len(set(selected)) >= 2
    return {"seed_count": len(selected), "selected_counts": {cid: selected.count(cid) for cid in sorted(candidate_ids)}}


# CS2_004 — +2 current/max health, minion-only target, no extra draw in this text.
def shield_adds_health_and_does_not_draw():
    game = new_game()
    target = summon(game.player2, "CS2_182", damage=2)
    draw_candidate = game.player1.give("CS2_231")
    draw_candidate.shuffle_into_deck()
    deck_before = [card.id for card in game.player1.deck]
    hp_before, max_before, atk_before = target.health, target.max_health, target.atk
    spell = game.player1.give("CS2_004")
    spell.play(target=target)
    assert target.health == hp_before + 2 and target.max_health == max_before + 2
    assert target.atk == atk_before and target.zone == Zone.PLAY
    assert [card.id for card in game.player1.deck] == deck_before
    assert not game.player1.hand
    return {"health": f"{hp_before}->{target.health}", "max_health": f"{max_before}->{target.max_health}", "atk": target.atk, "deck": deck_before, "hand": len(game.player1.hand)}


def shield_rejects_hero_target():
    game = new_game()
    minion = summon(game.player1, "CS2_182")
    hero = game.player1.hero
    spell = game.player1.give("CS2_004")
    before = (hero.health, hero.max_health)
    assert minion in spell.targets and hero not in spell.targets
    reject_invalid_action(lambda: spell.play(target=hero))
    assert (hero.health, hero.max_health) == before and spell.zone == Zone.HAND
    return {"hero": [hero.health, hero.max_health], "spell_zone": spell.zone.name, "minion_valid": minion in spell.targets}


# CS2_005 — attack expires at turn end; armor remains and absorbs later damage.
def claw_attack_expires_armor_persists():
    game = new_game()
    hero = game.player1.hero
    health_before = hero.health
    spell = game.player1.give("CS2_005")
    spell.play()
    assert hero.atk == 2 and hero.armor == 2
    game.end_turn()
    assert hero.atk == 0 and hero.armor == 2
    weapon = game.player2.give("CS2_091")
    weapon.play()
    game.player2.hero.attack(target=hero)
    assert hero.armor == 1 and hero.health == health_before
    return {"after_claw": {"atk": 2, "armor": 2}, "after_turn": {"atk": hero.atk, "armor": 2}, "after_enemy_1_damage": {"armor": hero.armor, "health": hero.health}}


# CS2_007 — exact 8 point heal, any character targeting, and max-health cap.
def healing_touch_restores_eight_to_friendly_hero():
    game = new_game()
    hero = game.player1.hero
    hero.damage = 12  # 18/30.
    spell = game.player1.give("CS2_007")
    assert hero in spell.targets
    spell.play(target=hero)
    assert hero.health == 26 and hero.damage == 4
    return {"hero": f"{hero.health}/{hero.max_health}", "damage_remaining": hero.damage}


def healing_touch_accepts_enemy_minion_and_caps_at_max():
    game = new_game()
    target = summon(game.player2, "CS2_182", damage=4)  # 1/5.
    spell = game.player1.give("CS2_007")
    assert target in spell.targets
    spell.play(target=target)
    assert target.health == 5 and target.damage == 0 and target.max_health == 5
    return {"target_owner": "opponent", "health": f"{target.health}/{target.max_health}", "damage": target.damage}


# CS2_008 — exact 1 damage, including characters on either side.
def moonfire_deals_one_to_enemy_minion():
    game = new_game()
    target = summon(game.player2, "CS2_182")
    spell = game.player1.give("CS2_008")
    before = target.health
    assert target in spell.targets
    spell.play(target=target)
    assert target.health == before - 1 and target.zone == Zone.PLAY
    return {"target_health": f"{before}->{target.health}", "target_damage": target.damage}


def moonfire_can_target_friendly_hero():
    game = new_game()
    own_hero, enemy_hero = game.player1.hero, game.player2.hero
    spell = game.player1.give("CS2_008")
    own_before, enemy_before = own_hero.health, enemy_hero.health
    assert own_hero in spell.targets
    spell.play(target=own_hero)
    assert own_hero.health == own_before - 1 and enemy_hero.health == enemy_before
    return {"own_hero": f"{own_before}->{own_hero.health}", "enemy_hero": enemy_hero.health}


# CS2_024 — 3 damage and Freeze on any character, including own characters.
def frostbolt_damages_and_freezes_enemy_minion():
    game = new_game()
    target = summon(game.player2, "CS2_182")
    spell = game.player1.give("CS2_024")
    spell.play(target=target)
    assert target.health == 2 and target.damage == 3 and target.frozen
    return {"health": target.health, "damage": target.damage, "frozen": target.frozen}


def frostbolt_can_target_own_hero():
    game = new_game()
    own_hero = game.player1.hero
    spell = game.player1.give("CS2_024")
    before = own_hero.health
    assert own_hero in spell.targets
    spell.play(target=own_hero)
    assert own_hero.health == before - 3 and own_hero.frozen
    return {"own_hero_health": f"{before}->{own_hero.health}", "frozen": own_hero.frozen}


def frostbolt_requires_a_target():
    game = new_game()
    spell = game.player1.give("CS2_024")
    before = game.player2.hero.health
    reject_invalid_action(lambda: spell.play())
    assert spell.zone == Zone.HAND and game.player2.hero.health == before
    return {"spell_zone": spell.zone.name, "enemy_hero_health": before}


# CS2_027 — two 0/2 Taunts, board-cap truncation, and full-board legality.
def mirror_image_summons_two_zero_two_taunts():
    game = new_game()
    spell = game.player1.give("CS2_027")
    spell.play()
    mirrors = [minion for minion in game.player1.field if minion.id == "CS2_mirror"]
    assert len(mirrors) == 2
    assert all((m.atk, m.health, m.max_health, m.taunt) == (0, 2, 2, True) for m in mirrors)
    return {"count": len(mirrors), "tokens": [[m.id, m.atk, m.health, m.taunt] for m in mirrors]}


def mirror_image_taunt_restricts_enemy_attack_targets():
    game = new_game()
    spell = game.player1.give("CS2_027")
    spell.play()
    mirrors = [minion for minion in game.player1.field if minion.id == "CS2_mirror"]
    game.end_turn()
    weapon = game.player2.give("CS2_091")
    weapon.play()
    attack_targets = list(game.player2.hero.attack_targets)
    assert set(attack_targets) == set(mirrors)
    reject_invalid_action(lambda: game.player2.hero.attack(target=game.player1.hero))
    game.player2.hero.attack(target=mirrors[0])
    assert mirrors[0].health == 1 and mirrors[1].health == 2
    return {"enemy_attack_targets": [t.id for t in attack_targets], "mirror_health": [m.health for m in mirrors]}


def mirror_image_summons_only_one_when_one_slot_remains():
    game = new_game()
    for _ in range(6):
        summon(game.player1, "CS2_231")
    spell = game.player1.give("CS2_027")
    spell.play()
    mirrors = [minion for minion in game.player1.field if minion.id == "CS2_mirror"]
    assert len(game.player1.field) == 7 and len(mirrors) == 1
    assert (mirrors[0].atk, mirrors[0].health, mirrors[0].taunt) == (0, 2, True)
    return {"field_size": len(game.player1.field), "mirror_count": len(mirrors)}


def mirror_image_is_not_playable_on_full_board():
    game = new_game()
    for _ in range(7):
        summon(game.player1, "CS2_231")
    spell = game.player1.give("CS2_027")
    before = len(game.player1.field)
    assert not spell.is_playable()
    reject_invalid_action(lambda: spell.play())
    assert spell.zone == Zone.HAND and len(game.player1.field) == before
    return {"is_playable": spell.is_playable(), "spell_zone": spell.zone.name, "field_size": len(game.player1.field)}


# CS2_032 — enemy minions only, four damage, lethal/Divine Shield handling.
def flamestrike_hits_all_enemy_minions_only():
    game = new_game()
    enemy_survivor = summon(game.player2, "CS2_182")  # 4/5 -> 4/1.
    enemy_lethal = summon(game.player2, "CS2_231")  # lethal.
    enemy_shielded = summon(game.player2, "EX1_020")  # 3/1 Divine Shield.
    friendly = summon(game.player1, "CS2_182")
    friendly_before = (friendly.health, friendly.damage)
    heroes_before = (game.player1.hero.health, game.player2.hero.health)
    spell = game.player1.give("CS2_032")
    spell.play()
    assert enemy_survivor.health == 1 and enemy_survivor.damage == 4
    assert enemy_lethal.dead and enemy_lethal.zone == Zone.GRAVEYARD
    assert enemy_shielded.divine_shield is False and enemy_shielded.health == 1
    assert (friendly.health, friendly.damage) == friendly_before
    assert (game.player1.hero.health, game.player2.hero.health) == heroes_before
    return {
        "enemy_survivor": f"{enemy_survivor.health}/5,damage={enemy_survivor.damage}",
        "enemy_lethal": enemy_lethal.zone.name,
        "shielded_enemy": {"health": enemy_shielded.health, "divine_shield": enemy_shielded.divine_shield},
        "friendly": [friendly.health, friendly.damage],
        "heroes": [game.player1.hero.health, game.player2.hero.health],
    }


# CS2_033 — its outgoing damage freezes; prevented damage must not trigger it.
def water_elemental_freezes_hero_damaged_by_its_attack():
    game = new_game()
    elemental = game.player1.give("CS2_033")
    elemental.play()
    assert (elemental.atk, elemental.health, elemental.max_health) == (3, 6, 6)
    game.end_turn()
    game.end_turn()
    before = game.player2.hero.health
    elemental.attack(target=game.player2.hero)
    assert game.player2.hero.health == before - 3 and game.player2.hero.frozen
    return {"elemental": [elemental.atk, elemental.health, elemental.max_health], "enemy_hero": f"{before}->{game.player2.hero.health}", "frozen": game.player2.hero.frozen}


def water_elemental_freezes_minion_damaged_in_retaliation():
    game = new_game()
    elemental = game.player1.give("CS2_033")
    elemental.play()
    attacker = summon(game.player2, "CS2_182")  # 4/5 attacks the 3/6 Elemental.
    game.end_turn()
    attacker.attack(target=elemental)
    assert attacker.health == 2 and attacker.frozen
    assert elemental.health == 2 and elemental.zone == Zone.PLAY
    return {"attacker": {"health": attacker.health, "frozen": attacker.frozen}, "elemental": {"health": elemental.health, "zone": elemental.zone.name}}


def water_elemental_does_not_freeze_when_divine_shield_prevents_damage():
    game = new_game()
    elemental = game.player1.give("CS2_033")
    elemental.play()
    shielded = summon(game.player2, "EX1_020")  # 3/1 Divine Shield absorbs the 3 attack.
    game.end_turn()
    game.end_turn()
    shield_before = shielded.divine_shield
    health_before = shielded.health
    elemental.attack(target=shielded)
    assert shield_before and not shielded.divine_shield
    assert shielded.health == health_before and not shielded.frozen
    return {"target_health": f"{health_before}->{shielded.health}", "shield": f"{shield_before}->{shielded.divine_shield}", "frozen": shielded.frozen}


# CS2_037 — enemy-only target, exact 1 damage, and Freeze.
def frost_shock_damages_and_freezes_enemy_minion():
    game = new_game()
    target = summon(game.player2, "CS2_182")
    spell = game.player1.give("CS2_037")
    spell.play(target=target)
    assert target.health == 4 and target.damage == 1 and target.frozen
    return {"health": target.health, "damage": target.damage, "frozen": target.frozen}


def frost_shock_damages_and_freezes_enemy_hero():
    game = new_game()
    target = game.player2.hero
    spell = game.player1.give("CS2_037")
    spell.play(target=target)
    assert target.health == 29 and target.frozen
    return {"health": target.health, "frozen": target.frozen}


def frost_shock_rejects_friendly_character():
    game = new_game()
    legal_target = game.player2.hero
    illegal_target = game.player1.hero
    spell = game.player1.give("CS2_037")
    before = illegal_target.health
    assert legal_target in spell.targets and illegal_target not in spell.targets
    reject_invalid_action(lambda: spell.play(target=illegal_target))
    assert illegal_target.health == before and spell.zone == Zone.HAND
    return {"friendly_hero_health": illegal_target.health, "spell_zone": spell.zone.name, "friendly_in_targets": illegal_target in spell.targets}


CASES = [
    ("CS1_130", "CS1_130_damage_exact", "Deal exactly 3 damage to a minion; leave a 4/5 minion at 4/2 in PLAY.", smite_survives_at_exact_health, "legal enemy minion, exact damage, surviving zone"),
    ("CS1_130", "CS1_130_lethal_zone", "Three damage kills a 1-health minion and moves it to GRAVEYARD.", smite_kills_three_health_minion, "lethal damage and zone/death state"),
    ("CS1_130", "CS1_130_friendly_minion", "Friendly minion is also a legal target and takes exactly 3 damage.", smite_can_target_friendly_minion, "friendly-versus-enemy minion target boundary"),
    ("CS1_130", "CS1_130_reject_hero", "Hero is not a legal target; failed play leaves spell in hand and hero unchanged.", smite_rejects_hero, "illegal hero target with a legal minion present"),
    ("CS2_003", "CS2_003_random_copy", "Exactly one card ID from opponent hand is copied to own hand; source cards remain; creator is this spell.", mind_vision_copies_one_opponent_card, "random-choice membership and source/destination zones"),
    ("CS2_003", "CS2_003_empty_hand", "Empty opponent hand yields no copied card and resolves spell normally.", mind_vision_empty_opponent_hand, "empty-source edge case"),
    ("CS2_003", "CS2_003_seeded_random", "Across fixed RNG seeds, every result is an opponent hand card and more than one candidate is selected.", mind_vision_uses_random_candidate_across_seeded_games, "12 reproducible seeds check random selection is not a fixed first-card pick"),
    ("CS2_004", "CS2_004_health_no_draw", "+2 current and maximum Health, no Attack change, and no draw under snapshot text.", shield_adds_health_and_does_not_draw, "wounded enemy minion and one known card in own deck"),
    ("CS2_004", "CS2_004_reject_hero", "Hero is not a legal target; failed play does not change hero health or spell zone.", shield_rejects_hero_target, "illegal hero target while a legal minion is available"),
    ("CS2_005", "CS2_005_temp_attack_armor", "+2 hero Attack expires at turn end; 2 Armor remains and absorbs 1 later damage.", claw_attack_expires_armor_persists, "temporary-duration boundary and armor absorption"),
    ("CS2_007", "CS2_007_heal_eight", "Restore exactly 8 Health to a damaged friendly hero.", healing_touch_restores_eight_to_friendly_hero, "friendly hero target and exact amount"),
    ("CS2_007", "CS2_007_enemy_cap", "Enemy minion is targetable and heals only to its 5 maximum Health.", healing_touch_accepts_enemy_minion_and_caps_at_max, "enemy minion legality and overheal cap"),
    ("CS2_008", "CS2_008_damage_one", "Enemy minion takes exactly 1 damage and remains in PLAY.", moonfire_deals_one_to_enemy_minion, "exact damage and nonlethal zone"),
    ("CS2_008", "CS2_008_friendly_target", "Friendly hero is legal; only that character loses 1 Health.", moonfire_can_target_friendly_hero, "unrestricted character target boundary"),
    ("CS2_024", "CS2_024_minion_damage_freeze", "Enemy minion takes exactly 3 damage and is frozen.", frostbolt_damages_and_freezes_enemy_minion, "enemy minion target, damage, freeze"),
    ("CS2_024", "CS2_024_friendly_hero", "Friendly hero is a legal character target and takes 3 damage plus Freeze.", frostbolt_can_target_own_hero, "any-character target scope"),
    ("CS2_024", "CS2_024_requires_target", "Playing without a target is rejected without consuming the spell or changing enemy health.", frostbolt_requires_a_target, "required-target branch"),
    ("CS2_027", "CS2_027_two_taunts", "Summon exactly two 0/2 minions with Taunt.", mirror_image_summons_two_zero_two_taunts, "normal board capacity, count/stats/keyword"),
    ("CS2_027", "CS2_027_taunt_blocks_hero", "Enemy attack targets are limited to both Mirror Images; attack on hero rejected.", mirror_image_taunt_restricts_enemy_attack_targets, "actual attack-target restriction and combat"),
    ("CS2_027", "CS2_027_one_slot", "With one slot free, summon one 0/2 Taunt and stop at seven minions.", mirror_image_summons_only_one_when_one_slot_remains, "partial summon at board capacity"),
    ("CS2_027", "CS2_027_full_board", "Full board makes spell unplayable; no spell/field mutation.", mirror_image_is_not_playable_on_full_board, "zero available slots"),
    ("CS2_032", "CS2_032_enemy_only_four", "All enemy minions take 4; lethal minion dies, Divine Shield prevents health damage; friendly minion and heroes unchanged.", flamestrike_hits_all_enemy_minions_only, "multi-target AoE, death zone, Divine Shield, side boundary"),
    ("CS2_033", "CS2_033_attack_hero", "Water Elemental is 3/6; its attack deals 3 and freezes the damaged enemy hero.", water_elemental_freezes_hero_damaged_by_its_attack, "printed body, direct combat damage, hero freeze"),
    ("CS2_033", "CS2_033_retaliation_freeze", "Elemental retaliation deals 3 to attacker and freezes it; 4 attack retaliation leaves Elemental at 2 Health.", water_elemental_freezes_minion_damaged_in_retaliation, "trigger when Elemental deals combat damage as defender"),
    ("CS2_033", "CS2_033_prevented_damage", "Divine Shield absorbs Elemental attack; target Health unchanged and target does not freeze.", water_elemental_does_not_freeze_when_divine_shield_prevents_damage, "prevented-damage branch"),
    ("CS2_037", "CS2_037_enemy_minion", "Enemy minion takes exactly 1 damage and freezes.", frost_shock_damages_and_freezes_enemy_minion, "enemy minion target, damage, freeze"),
    ("CS2_037", "CS2_037_enemy_hero", "Enemy hero takes exactly 1 damage and freezes.", frost_shock_damages_and_freezes_enemy_hero, "enemy hero target"),
    ("CS2_037", "CS2_037_reject_friendly", "Friendly character is illegal; failed play leaves it unchanged and spell in hand.", frost_shock_rejects_friendly_character, "legal enemy target remains available during rejection"),
]


def main():
    # Force CardDB initialization before any player/card setup.
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
