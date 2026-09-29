"""Card-specific behavior tests for ten Basic YELLOW cards.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_h.py

This records runtime observations only. It does not edit card implementations
or the quality-map CSVs.
"""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
OUT = HERE / "basic_card_probe_h.csv"
FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
ROWS = []


def new_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = 10
    game.player1.used_mana = 0
    game.player2.max_mana = 10
    game.player2.used_mana = 0
    return game


def run_case(card_id, case_id, expected, probe, notes):
    try:
        observed, passed = probe()
        outcome = (
            "pass"
            if passed is True
            else "confirmed_error"
            if passed is False
            else "inconclusive"
        )
    except Exception as error:
        observed = f"exception={type(error).__name__}: {error}"
        outcome = "inconclusive"
    ROWS.append(
        {
            "card_id": card_id,
            "case_id": case_id,
            "expected": expected,
            "observed": observed,
            "outcome": outcome,
            "notes": notes,
        }
    )


def card_ex1_011_voodoo_doctor():
    card_id = "EX1_011"

    def heals_injured_friendly_hero_exactly_two():
        game = new_game()
        p1, p2 = game.player1, game.player2
        target = p1.hero
        target.set_current_health(28)
        other_hero_before = p2.hero.health
        doctor = p1.give(card_id)
        legal_target = target in doctor.targets
        before = target.health
        doctor.play(target=target)
        observed = (
            f"friendly_hero_legal={legal_target};friendly_hero={before}->{target.health}/{target.max_health};"
            f"opponent_hero={other_hero_before}->{p2.hero.health};doctor={doctor.zone.name}"
        )
        passed = (
            legal_target
            and before == 28
            and target.health == 30
            and target.max_health == 30
            and p2.hero.health == other_hero_before
            and doctor.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        card_id,
        "voodoo_doctor_heals_friendly_hero_exactly_two",
        "Battlecry restores exactly 2 Health to an injured friendly hero, up to its maximum Health; the opponent's hero remains unchanged.",
        heals_injured_friendly_hero_exactly_two,
        "EN: Battlecry: Restore 2 Health. ZH: 战吼：恢复2点生命值。 Impl: fireplace/cards/classic/neutral_common.py:35-38, "
        "REQ_TARGET_IF_AVAILABLE and Heal(TARGET, 2). Existing tests/test_league.py:446-475 cite this ID only in "
        "Rumbling Elemental setups; they do not assert the Doctor's heal. Audit row EX1_011 was YELLOW/partial.",
    )

    def full_health_target_is_legal_without_overheal():
        game = new_game()
        p1, p2 = game.player1, game.player2
        full_target = p2.summon("CS2_182")
        doctor = p1.give(card_id)
        legal_target = full_target in doctor.targets
        before = (full_target.health, full_target.max_health)
        doctor.play(target=full_target)
        observed = (
            f"full_minion_target_legal={legal_target};health={before}->{(full_target.health, full_target.max_health)};"
            f"doctor={doctor.zone.name},in_field={doctor in p1.field}"
        )
        passed = (
            legal_target
            and before == (5, 5)
            and (full_target.health, full_target.max_health) == before
            and doctor.zone == Zone.PLAY
            and doctor in p1.field
        )
        return observed, passed

    run_case(
        card_id,
        "voodoo_doctor_full_health_target_no_overheal",
        "A full-health minion remains a legal target and is not healed above its maximum Health.",
        full_health_target_is_legal_without_overheal,
        "Tests the observed full-health target rule directly; the card does not say that a target must be damaged.",
    )

    def missing_target_rejected_before_cost_or_entry():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p2.hero.set_current_health(28)
        doctor = p1.give(card_id)
        legal_targets = list(doctor.targets)
        mana_before = p1.mana
        try:
            doctor.play()
            rejected = False
        except Exception as error:
            rejected = type(error).__name__ == "InvalidAction"
        observed = (
            f"legal_target_count={len(legal_targets)};missing_target_rejected={rejected};"
            f"doctor={doctor.zone.name},in_hand={doctor in p1.hand},in_field={doctor in p1.field};"
            f"mana={mana_before}->{p1.mana};enemy_hero_health={p2.hero.health}"
        )
        passed = (
            bool(legal_targets)
            and rejected
            and doctor.zone == Zone.HAND
            and doctor in p1.hand
            and doctor not in p1.field
            and p1.mana == mana_before
            and p2.hero.health == 28
        )
        return observed, passed

    run_case(
        card_id,
        "voodoo_doctor_missing_target_rejected_without_payment",
        "When injured characters are available, omitting the target is rejected before the card leaves hand or mana is spent.",
        missing_target_rejected_before_cost_or_entry,
        "REQ_TARGET_IF_AVAILABLE with legal heal targets present; tests failed-play atomicity and the actual target-required branch.",
    )


def card_ex1_084_warsong_commander():
    card_id = "EX1_084"

    def friendly_charge_buff_attack_and_enemy_control():
        game = new_game()
        p1, p2 = game.player1, game.player2
        noncharge = p1.summon("CS2_231")
        warsong = p1.give(card_id)
        warsong.play()
        boar = p1.give("CS2_171")
        boar.play()
        enemy_boar = p2.summon("CS2_171")
        ready_before_attack = boar.can_attack()
        boar.attack(p2.hero)
        after_attack = p2.hero.health
        attack_before_silence = boar.atk
        warsong.silence()
        after_silence = boar.atk
        observed = (
            f"noncharge_attack={noncharge.atk};friendly_charge={boar.atk};"
            f"friendly_charge_flag={boar.charge};ready_on_entry={ready_before_attack};"
            f"enemy_hero_after_attack={after_attack};friendly_attacks={attack_before_silence}->{after_silence};"
            f"enemy_charge_attack={enemy_boar.atk};warsong_silenced={warsong.silenced}"
        )
        passed = (
            noncharge.atk == 1
            and boar.atk == 1
            and boar.charge
            and ready_before_attack
            and after_attack == 28
            and attack_before_silence == 2
            and after_silence == 1
            and enemy_boar.atk == 1
            and warsong.silenced
        )
        return observed, passed

    run_case(
        card_id,
        "warsong_friendly_charge_only_buff_and_attack",
        "Friendly Charge minions gain +1 Attack and keep Charge; non-Charge and enemy Charge minions do not gain the buff. The buffed Boar can attack immediately, and silence removes the aura.",
        friendly_charge_buff_attack_and_enemy_control,
        "EN: Your Charge minions have +1 Attack. ZH: 你的具有冲锋的随从获得+1攻击力。 Impl: fireplace/cards/classic/warrior.py:206-212, "
        "Refresh(FRIENDLY_MINIONS + CHARGE, buff=+1 Attack). Existing tests/test_classic.py:3602-3618:test_warsong_commander "
        "cover a friendly Wisp vs Boar and silence on the Boar, but not opponent exclusion, immediate attack damage, or aura-source silence. Audit row YELLOW/partial.",
    )

    def charge_keyword_change_updates_membership():
        game = new_game()
        p1 = game.player1
        warsong = p1.give(card_id)
        warsong.play()
        boar = p1.give("CS2_171")
        boar.play()
        buffed = boar.atk
        charge_before = boar.charge
        boar.silence()
        observed = (
            f"before_silence={buffed},charge={charge_before};"
            f"after_silence_attack={boar.atk},charge={boar.charge};"
            f"warsong_attack={warsong.atk},warsong_zone={warsong.zone.name}"
        )
        passed = (
            buffed == 2
            and charge_before
            and not boar.charge
            and boar.atk == 1
            and warsong.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        card_id,
        "warsong_removes_buff_when_charge_is_silenced",
        "A minion that loses Charge no longer matches the aura and loses the +1 Attack enchantment.",
        charge_keyword_change_updates_membership,
        "Targets update after keyword removal; prior test_warsong_commander also checks Boar silence, reproduced with direct attack-stat assertions here.",
    )


def card_ex1_129_fan_of_knives():
    card_id = "EX1_129"

    def damages_every_enemy_minion_and_draws_exact_top_card():
        game = new_game()
        p1, p2 = game.player1, game.player2
        friendly = p1.summon("CS2_182")
        enemy_lethal = p2.summon("CS2_231")
        enemy_survivor = p2.summon("CS2_182")
        enemy_survivor.set_current_health(2)
        draw_card = p1.card("CS2_029", zone=Zone.DECK)
        friendly_before = (friendly.health, friendly.zone)
        survivor_before = enemy_survivor.health
        spell = p1.give(card_id)
        spell.play()
        observed = (
            f"enemy_lethal={enemy_lethal.health}:{enemy_lethal.zone.name},in_field={enemy_lethal in p2.field};"
            f"enemy_survivor_health={survivor_before}->{enemy_survivor.health},zone={enemy_survivor.zone.name};"
            f"friendly={friendly_before}->{(friendly.health, friendly.zone.name)};"
            f"draw={draw_card.id}:{draw_card.zone.name},in_hand={draw_card in p1.hand};"
            f"deck_count={len(p1.deck)};spell={spell.zone.name}"
        )
        passed = (
            enemy_lethal.zone == Zone.GRAVEYARD
            and enemy_lethal not in p2.field
            and enemy_survivor.health == 1
            and enemy_survivor.zone == Zone.PLAY
            and (friendly.health, friendly.zone) == friendly_before
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "fan_of_knives_enemy_aoe_and_draw",
        "Deal 1 to every enemy minion, including lethal damage; leave friendly minions unchanged; draw exactly one known card.",
        damages_every_enemy_minion_and_draws_exact_top_card,
        "EN: Deal 1 damage to all enemy minions. Draw a card. ZH: 对所有敌方随从造成1点伤害，抽一张牌。 Impl: "
        "fireplace/cards/classic/rogue.py:155-158, Hit(ENEMY_MINIONS, 1), Draw(CONTROLLER). No direct Fan of Knives test reference in the audit; row YELLOW/partial.",
    )

    def draw_occurs_with_empty_enemy_board():
        game = new_game()
        p1, p2 = game.player1, game.player2
        draw_card = p1.card("CS2_182", zone=Zone.DECK)
        hero_before = p2.hero.health
        spell = p1.give(card_id)
        spell.play()
        observed = (
            f"enemy_field={len(p2.field)};enemy_hero={hero_before}->{p2.hero.health};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};deck={len(p1.deck)};spell={spell.zone.name}"
        )
        passed = (
            not p2.field
            and p2.hero.health == hero_before
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "fan_of_knives_draw_with_no_enemy_minions",
        "The draw component still resolves when there are no enemy minions to damage; enemy hero is not damaged.",
        draw_occurs_with_empty_enemy_board,
        "Tests the zero-target branch of Hit(ENEMY_MINIONS, 1) and confirms the subsequent unconditional Draw action still runs.",
    )


def card_ex1_173_starfire():
    card_id = "EX1_173"

    def damages_enemy_hero_and_draws():
        game = new_game()
        p1, p2 = game.player1, game.player2
        draw_card = p1.card("CS2_231", zone=Zone.DECK)
        spell = p1.give(card_id)
        legal_hero = p2.hero in spell.targets
        hero_before = p2.hero.health
        spell.play(target=p2.hero)
        observed = (
            f"enemy_hero_target_legal={legal_hero};hero={hero_before}->{p2.hero.health};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};deck={len(p1.deck)};spell={spell.zone.name}"
        )
        passed = (
            legal_hero
            and p2.hero.health == hero_before - 5
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "starfire_enemy_hero_target_damage_and_draw",
        "An enemy hero is a legal target, takes exactly 5 damage, and the caster draws one known card.",
        damages_enemy_hero_and_draws,
        "EN: Deal 5 damage. Draw a card. ZH: 造成5点伤害，抽一张牌。 Impl: fireplace/cards/classic/druid.py:278-281, "
        "REQ_TARGET_TO_PLAY; Hit(TARGET,5), Draw(CONTROLLER). Audit row EX1_173 was YELLOW/partial and had only generic smoke evidence.",
    )

    def lethal_minion_target_also_draws():
        game = new_game()
        p1, p2 = game.player1, game.player2
        target = p2.summon("CS2_182")
        target.set_current_health(4)
        draw_card = p1.card("EX1_066", zone=Zone.DECK)
        spell = p1.give(card_id)
        spell.play(target=target)
        observed = (
            f"target_health={target.health},zone={target.zone.name},in_enemy_field={target in p2.field};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};deck={len(p1.deck)};spell={spell.zone.name}"
        )
        passed = (
            target.zone == Zone.GRAVEYARD
            and target not in p2.field
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "starfire_lethal_minion_damage_still_draws",
        "A target killed by the 5 damage is processed as dead, and the spell still draws one card because its draw is unconditional.",
        lethal_minion_target_also_draws,
        "Uses a 4-health Yeti to force lethal damage and a known single-card deck to make draw observable.",
    )

    def friendly_hero_target_takes_damage_and_draws():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p1.hero.set_current_health(20)
        draw_card = p1.card("CS2_231", zone=Zone.DECK)
        spell = p1.give(card_id)
        friendly_hero_legal = p1.hero in spell.targets
        other_hero_before = p2.hero.health
        spell.play(target=p1.hero)
        observed = (
            f"friendly_hero_legal={friendly_hero_legal};friendly_hero=20->{p1.hero.health};"
            f"opponent_hero={other_hero_before}->{p2.hero.health};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};spell={spell.zone.name}"
        )
        passed = (
            friendly_hero_legal
            and p1.hero.health == 15
            and p2.hero.health == other_hero_before
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "starfire_friendly_hero_target_damage_and_draw",
        "Because the card only requires a target and does not restrict allegiance, the friendly hero is legal, takes 5 damage, and the spell still draws one card.",
        friendly_hero_target_takes_damage_and_draws,
        "Target-domain branch for REQ_TARGET_TO_PLAY without REQ_ENEMY_TARGET or REQ_MINION_TARGET; known deck card makes draw observable.",
    )


def card_ex1_191_plaguebringer():
    card_id = "EX1_191"

    def friendly_target_gets_poisonous_and_kills_large_minion():
        game = new_game()
        p1, p2 = game.player1, game.player2
        boar = p1.give("CS2_171")
        boar.play()
        enemy_yeti = p2.summon("CS2_182")
        plaguebringer = p1.give(card_id)
        target_options = list(plaguebringer.targets)
        friendly_legal = boar in target_options
        enemy_legal = enemy_yeti in target_options
        plaguebringer.play(target=boar)
        poisonous_after_battlecry = boar.poisonous
        source_poisonous = plaguebringer.poisonous
        enemy_poisonous = enemy_yeti.poisonous
        boar.attack(enemy_yeti)
        observed = (
            f"target_options={[c.id for c in target_options]};friendly_legal={friendly_legal};enemy_legal={enemy_legal};"
            f"poisonous_after_battlecry={poisonous_after_battlecry};source_poisonous={source_poisonous};"
            f"enemy_poisonous={enemy_poisonous};"
            f"boar={boar.zone.name};enemy_yeti={enemy_yeti.zone.name},in_field={enemy_yeti in p2.field};"
            f"plaguebringer={plaguebringer.zone.name}"
        )
        passed = (
            friendly_legal
            and not enemy_legal
            and poisonous_after_battlecry
            and not source_poisonous
            and not enemy_poisonous
            and boar.zone == Zone.GRAVEYARD
            and enemy_yeti.zone == Zone.GRAVEYARD
            and enemy_yeti not in p2.field
            and plaguebringer.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        card_id,
        "plaguebringer_friendly_poisonous_combat",
        "Only a friendly minion is a legal target; it gains Poisonous and destroys a 5-health enemy minion in combat, while normal retaliation still kills the 1-health Boar.",
        friendly_target_gets_poisonous_and_kills_large_minion,
        "EN: Battlecry: Give a friendly minion Poisonous. ZH: 战吼：使一个友方随从获得剧毒。 Impl: "
        "fireplace/cards/classic/rogue.py:243-252, friendly/minion target requirements and GivePoisonous(TARGET). No direct test reference in the audit; row YELLOW/partial.",
    )


def card_ex1_193_psychic_conjurer():
    card_id = "EX1_193"

    def copies_single_known_enemy_deck_card_without_moving_original():
        game = new_game()
        p1, p2 = game.player1, game.player2
        enemy_card = p2.card("CS2_182", zone=Zone.DECK)
        original_entity_id = enemy_card.entity_id
        conjurer = p1.give(card_id)
        before_hand_ids = [card.entity_id for card in p1.hand]
        conjurer.play()
        new_hand_cards = [card for card in p1.hand if card.entity_id not in before_hand_ids]
        copies = [card for card in new_hand_cards if card.id == enemy_card.id]
        observed = (
            f"enemy_original={enemy_card.id}:{enemy_card.zone.name},same_entity={enemy_card.entity_id == original_entity_id},"
            f"enemy_deck={[c.id for c in p2.deck]};"
            f"new_hand={[(c.id, c.zone.name, c.entity_id) for c in new_hand_cards]};"
            f"matching_copy_count={len(copies)},copy_is_original={bool(copies) and copies[0] is enemy_card};"
            f"conjurer={conjurer.zone.name}"
        )
        passed = (
            len(copies) == 1
            and copies[0] is not enemy_card
            and copies[0].entity_id != original_entity_id
            and copies[0].zone == Zone.HAND
            and enemy_card.zone == Zone.DECK
            and enemy_card in p2.deck
            and len(p2.deck) == 1
            and conjurer.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        card_id,
        "conjurer_copies_enemy_deck_card_to_hand",
        "With one known card in the opponent's deck, add a distinct copy with the same card ID to the caster's hand; preserve the original in the opponent's deck.",
        copies_single_known_enemy_deck_card_without_moving_original,
        "EN: Battlecry: Copy a card in your opponent's deck and add it to your hand. ZH: 战吼：复制对手牌库中的一张牌并置入手牌。 "
        "Impl: fireplace/cards/classic/priest.py:76-80, Give(CONTROLLER, Copy(RANDOM(ENEMY_DECK))). Audit row EX1_193 was YELLOW/partial with generic smoke only.",
    )

    def empty_enemy_deck_creates_no_copy_but_card_resolves():
        game = new_game()
        p1, p2 = game.player1, game.player2
        starting_hand = list(p1.hand)
        conjurer = p1.give(card_id)
        hand_after_give = list(p1.hand)
        conjurer.play()
        newly_added = [card for card in p1.hand if card not in hand_after_give]
        observed = (
            f"enemy_deck={len(p2.deck)};new_cards={[c.id for c in newly_added]};"
            f"hand_size={len(p1.hand)},starting={len(starting_hand)};"
            f"conjurer={conjurer.zone.name},in_field={conjurer in p1.field}"
        )
        passed = (
            not p2.deck
            and not newly_added
            and conjurer.zone == Zone.PLAY
            and conjurer in p1.field
        )
        return observed, passed

    run_case(
        card_id,
        "conjurer_empty_enemy_deck_no_copy",
        "When the opponent has no deck cards, the Battlecry adds no card and the Conjurer still enters play without an exception.",
        empty_enemy_deck_creates_no_copy_but_card_resolves,
        "Boundary branch for RANDOM(ENEMY_DECK) on an empty selector; this is a defined no-candidate state, not a claim about copying from an empty library.",
    )


def card_ex1_244_totemic_might():
    card_id = "EX1_244"

    def buffs_existing_friendly_totems_only():
        game = new_game()
        p1, p2 = game.player1, game.player2
        searing = p1.summon("CS2_050")
        healing = p1.summon("CS2_052")
        non_totem = p1.summon("CS2_231")
        enemy_totem = p2.summon("CS2_050")
        healing.set_current_health(1)  # Damaged 0/2 Totem.
        before = {
            "searing": (searing.health, searing.max_health),
            "healing": (healing.health, healing.max_health),
            "non_totem": (non_totem.health, non_totem.max_health),
            "enemy_totem": (enemy_totem.health, enemy_totem.max_health),
        }
        spell = p1.give(card_id)
        spell.play()
        after = {
            "searing": (searing.health, searing.max_health),
            "healing": (healing.health, healing.max_health),
            "non_totem": (non_totem.health, non_totem.max_health),
            "enemy_totem": (enemy_totem.health, enemy_totem.max_health),
        }
        later_totem = p1.summon("CS2_051")
        observed = (
            f"before={before};after={after};later_totem={(later_totem.health, later_totem.max_health)};"
            f"spell={spell.zone.name}"
        )
        passed = (
            after["searing"] == (3, 3)
            and after["healing"] == (3, 4)
            and after["non_totem"] == before["non_totem"]
            and after["enemy_totem"] == before["enemy_totem"]
            and (later_totem.health, later_totem.max_health) == (2, 2)
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "totemic_might_buffs_current_friendly_totems",
        "All existing friendly Totems gain +2 maximum and current Health; a non-Totem, an enemy Totem, and a Totem played afterward remain unchanged.",
        buffs_existing_friendly_totems_only,
        "EN: Give your Totems +2 Health. ZH: 使你的图腾获得+2生命值。 Impl: fireplace/cards/classic/shaman.py:134-140, "
        "Buff(FRIENDLY_MINIONS + TOTEM, health=2). Existing tests/test_classic.py:3386-3394:test_totemic_might checks only Searing Totem's health from 1 to 3; audit row YELLOW/partial.",
    )


def card_ex1_246_hex():
    card_id = "EX1_246"

    def enemy_deathrattle_minion_transforms_without_deathrattle():
        game = new_game()
        p1, p2 = game.player1, game.player2
        target = p2.summon("EX1_096")  # Loot Hoarder has a draw Deathrattle.
        draw_card = p2.card("CS2_231", zone=Zone.DECK)
        spell = p1.give(card_id)
        friendly_legal = p1.summon("CS2_182") in spell.targets
        enemy_legal = target in spell.targets
        spell.play(target=target)
        frogs = [card for card in p2.field if card.id == "hexfrog"]
        frog = frogs[0] if frogs else None
        observed = (
            f"friendly_target_legal={friendly_legal};enemy_target_legal={enemy_legal};"
            f"old={target.id}:{target.zone.name},in_field={target in p2.field},in_graveyard={target in p2.graveyard};"
            f"new_field={[(c.id, c.atk, c.health, c.taunt, c.zone.name) for c in p2.field]};"
            f"frog_count={len(frogs)};opponent_draw={draw_card.zone.name},deck_count={len(p2.deck)};spell={spell.zone.name}"
        )
        passed = (
            friendly_legal
            and enemy_legal
            and target.zone == Zone.SETASIDE
            and target not in p2.field
            and target not in p2.graveyard
            and len(frogs) == 1
            and frog.controller is p2
            and frog.atk == 0
            and frog.health == 1
            and frog.taunt
            and draw_card.zone == Zone.DECK
            and len(p2.deck) == 1
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "hex_enemy_target_frog_stats_and_no_deathrattle",
        "Enemy and friendly minions are legal targets; transforming an enemy Loot Hoarder replaces it in the same field with a 0/1 Taunt Frog, moves the original to set-aside, and does not trigger its draw Deathrattle.",
        enemy_deathrattle_minion_transforms_without_deathrattle,
        "EN: Transform a minion into a 0/1 Frog with Taunt. ZH: 使一个随从变形成为0/1并具有嘲讽的青蛙。 Impl: "
        "fireplace/cards/classic/shaman.py:143-146, Morph(TARGET,'hexfrog'). Existing tests/test_mechanics.py:585-590:test_morph "
        "only checks Hex creates Frog; audit row EX1_246 was YELLOW/partial.",
    )

    def friendly_minion_can_be_transformed_and_spell_targets_no_heroes():
        game = new_game()
        p1, p2 = game.player1, game.player2
        target = p1.summon("CS2_182")
        enemy = p2.summon("CS2_182")
        spell = p1.give(card_id)
        legal_targets = list(spell.targets)
        friendly_legal = target in legal_targets
        enemy_legal = enemy in legal_targets
        hero_legal = p1.hero in legal_targets or p2.hero in legal_targets
        spell.play(target=target)
        frog = next((card for card in p1.field if card.id == "hexfrog"), None)
        observed = (
            f"friendly_legal={friendly_legal};enemy_legal={enemy_legal};hero_legal={hero_legal};"
            f"original={target.zone.name};friendly_field={[c.id for c in p1.field]};"
            f"frog={None if frog is None else (frog.controller.name, frog.atk, frog.health, frog.taunt)};"
            f"enemy_remains={enemy.zone.name}"
        )
        passed = (
            friendly_legal
            and enemy_legal
            and not hero_legal
            and target.zone == Zone.SETASIDE
            and frog is not None
            and frog.controller is p1
            and frog.atk == 0
            and frog.health == 1
            and frog.taunt
            and enemy.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        card_id,
        "hex_friendly_target_and_minion_only_domain",
        "A friendly minion can be transformed, enemy minions remain legal, and heroes cannot be targeted.",
        friendly_minion_can_be_transformed_and_spell_targets_no_heroes,
        "Checks target domain and controller/zone preservation for a friendly target, complementing the enemy Deathrattle target case.",
    )


def card_ex1_277_arcane_missiles():
    card_id = "EX1_277"

    def seeded_random_targets_all_enemy_candidates():
        seeds = range(24)
        hit_counts = {"enemy_hero": 0, "enemy_minion_a": 0, "enemy_minion_b": 0}
        failures = []
        per_seed = []
        for seed in seeds:
            game = new_game()
            p1, p2 = game.player1, game.player2
            friendly_minion = p1.summon("CS2_182")
            enemy_minion_a = p2.summon("CS2_182")
            enemy_minion_b = p2.summon("CS2_182")
            enemies = [p2.hero, enemy_minion_a, enemy_minion_b]
            enemy_before = {entity: entity.health for entity in enemies}
            friendly_before = (p1.hero.health, friendly_minion.health)
            game.random.seed(seed)
            spell = p1.give(card_id)
            spell.play()
            enemy_damage = {
                "enemy_hero": enemy_before[p2.hero] - p2.hero.health,
                "enemy_minion_a": enemy_before[enemy_minion_a] - enemy_minion_a.health,
                "enemy_minion_b": enemy_before[enemy_minion_b] - enemy_minion_b.health,
            }
            total = sum(enemy_damage.values())
            for key, damage in enemy_damage.items():
                if damage > 0:
                    hit_counts[key] += 1
            valid = (
                total == 3
                and all(0 <= damage <= 3 for damage in enemy_damage.values())
                and (p1.hero.health, friendly_minion.health) == friendly_before
                and enemy_minion_a.zone == Zone.PLAY
                and enemy_minion_b.zone == Zone.PLAY
                and spell.zone == Zone.GRAVEYARD
            )
            if not valid:
                failures.append(seed)
            per_seed.append((seed, enemy_damage, total))
        all_candidates_hit = all(count > 0 for count in hit_counts.values())
        observed = (
            f"seeds=0..23;hit_counts={hit_counts};all_enemy_candidate_classes_hit={all_candidates_hit};"
            f"invalid_seeds={failures};per_seed={per_seed}"
        )
        return observed, not failures and all_candidates_hit

    run_case(
        card_id,
        "arcane_missiles_seeded_random_targets_all_candidates",
        "Across fixed seeds with an enemy hero and two durable enemy minions present, every candidate class is hit in at least one trial; each trial deals exactly 3 total damage, only to enemies.",
        seeded_random_targets_all_enemy_candidates,
        "EN: Deal 3 damage randomly split among all enemies. ZH: 造成3点伤害，随机分配到所有敌人身上。 Impl: "
        "fireplace/cards/classic/mage.py:131-134, Hit(RANDOM_ENEMY_CHARACTER, 1) * SPELL_DAMAGE(3). Existing tests/test_classic.py:289-294:test_arcane_missiles "
        "only handles one enemy Wisp and a conditional hero delta. Twenty-four independent games reseed game.random to 0..23 and assert per-trial damage/scope plus hit coverage for hero and both minions; audit row EX1_277 was YELLOW/partial.",
    )

    def spell_damage_adds_one_missile():
        game = new_game()
        p1, p2 = game.player1, game.player2
        spellpower_minion = p1.summon("CS2_142")  # Ogre Magi, Spell Damage +1.
        spell = p1.give(card_id)
        hero_before = p2.hero.health
        spellpower = p1.spellpower
        spell.play()
        observed = (
            f"spellpower_minion={spellpower_minion.id};spellpower={spellpower};"
            f"enemy_hero={hero_before}->{p2.hero.health};damage={hero_before-p2.hero.health};spell={spell.zone.name}"
        )
        passed = (
            spellpower == 1
            and p2.hero.health == hero_before - 4
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "arcane_missiles_spell_damage_increases_total",
        "One friendly Spell Damage adds one point to the spell's total, dealing 4 damage when the enemy hero is the only enemy character.",
        spell_damage_adds_one_missile,
        "Specific scaling check for the printed $3 amount and SPELL_DAMAGE(3); one enemy target makes the total deterministic despite random targeting.",
    )


def card_ex1_278_shiv():
    card_id = "EX1_278"

    def nonlethal_hero_damage_and_draw():
        game = new_game()
        p1, p2 = game.player1, game.player2
        draw_card = p1.card("CS2_231", zone=Zone.DECK)
        spell = p1.give(card_id)
        hero_target_legal = p2.hero in spell.targets
        before = p2.hero.health
        spell.play(target=p2.hero)
        observed = (
            f"enemy_hero_target_legal={hero_target_legal};hero={before}->{p2.hero.health};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};deck={len(p1.deck)};spell={spell.zone.name}"
        )
        passed = (
            hero_target_legal
            and p2.hero.health == before - 1
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "shiv_enemy_hero_nonlethal_damage_and_draw",
        "The enemy hero is a legal target, takes 1 damage, and the caster draws exactly one known card.",
        nonlethal_hero_damage_and_draw,
        "EN: Deal 1 damage. Draw a card. ZH: 造成1点伤害，抽一张牌。 Impl: fireplace/cards/classic/rogue.py:200-203, "
        "REQ_TARGET_TO_PLAY; Hit(TARGET,1), Draw(CONTROLLER). Audit row EX1_278 was YELLOW/partial with generic smoke only.",
    )

    def lethal_minion_damage_still_draws():
        game = new_game()
        p1, p2 = game.player1, game.player2
        target = p2.summon("CS2_231")  # 1/1 Wisp.
        draw_card = p1.card("EX1_066", zone=Zone.DECK)
        spell = p1.give(card_id)
        spell.play(target=target)
        observed = (
            f"target_health={target.health},zone={target.zone.name},in_field={target in p2.field};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};deck={len(p1.deck)};spell={spell.zone.name}"
        )
        passed = (
            target.zone == Zone.GRAVEYARD
            and target not in p2.field
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "shiv_lethal_minion_damage_still_draws",
        "Killing a 1-health minion with Shiv still draws one card; the target leaves play and the spell resolves to graveyard.",
        lethal_minion_damage_still_draws,
        "Unconditional draw branch after a lethal 1 damage hit; no direct Shiv effect test reference was found in the audit.",
    )

    def friendly_hero_target_takes_damage_and_draws():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p1.hero.set_current_health(20)
        draw_card = p1.card("CS2_231", zone=Zone.DECK)
        spell = p1.give(card_id)
        friendly_hero_legal = p1.hero in spell.targets
        other_hero_before = p2.hero.health
        spell.play(target=p1.hero)
        observed = (
            f"friendly_hero_legal={friendly_hero_legal};friendly_hero=20->{p1.hero.health};"
            f"opponent_hero={other_hero_before}->{p2.hero.health};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};spell={spell.zone.name}"
        )
        passed = (
            friendly_hero_legal
            and p1.hero.health == 19
            and p2.hero.health == other_hero_before
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and spell.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "shiv_friendly_hero_target_damage_and_draw",
        "Because the card only requires a target and does not restrict allegiance, the friendly hero is legal, takes 1 damage, and the spell still draws one card.",
        friendly_hero_target_takes_damage_and_draws,
        "Target-domain branch for REQ_TARGET_TO_PLAY without REQ_ENEMY_TARGET or REQ_MINION_TARGET; known deck card makes draw observable.",
    )


def all_cases():
    card_ex1_011_voodoo_doctor()
    card_ex1_084_warsong_commander()
    card_ex1_129_fan_of_knives()
    card_ex1_173_starfire()
    card_ex1_191_plaguebringer()
    card_ex1_193_psychic_conjurer()
    card_ex1_244_totemic_might()
    card_ex1_246_hex()
    card_ex1_277_arcane_missiles()
    card_ex1_278_shiv()


def main():
    all_cases()
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    by_card = {}
    for row in ROWS:
        by_card.setdefault(row["card_id"], []).append(row["outcome"])
    for card_id, outcomes in by_card.items():
        verdict = (
            "RED"
            if "confirmed_error" in outcomes
            else "GREEN"
            if all(outcome == "pass" for outcome in outcomes)
            else "YELLOW"
        )
        print(f"{card_id}: {verdict} cases={len(outcomes)} outcomes={outcomes}")
    print(f"wrote {len(ROWS)} cases to {OUT}")
    if any(row["outcome"] != "pass" for row in ROWS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
