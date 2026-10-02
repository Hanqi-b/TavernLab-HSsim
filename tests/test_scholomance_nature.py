"""Behavioral contracts for the launch-era Scholomance nature cards."""

import pytest
from hearthstone.enums import CardClass, CardType, Race, Zone

from fireplace import cards
from fireplace.agent_api import Action
from fireplace.actions import CastSpell
from fireplace.controller import GameSession
from utils import prepare_empty_game


def ready():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player, opponent = game.current_player, game.current_player.opponent
    for participant in (player, opponent):
        participant.discard_hand()
        participant.max_mana = 10
        participant.used_mana = 0
    game.random.seed(54613)
    return game, player, opponent


def test_sch_133_wolpertinger_copies_itself():
    _, player, _ = ready()
    player.give("SCH_133").play()
    assert [card.id for card in player.field].count("SCH_133") == 2


def test_sch_182_speaker_gidra_gains_the_cast_spell_cost():
    _, player, opponent = ready()
    gidra = player.give("SCH_182").play()
    player.give("CS2_029").play(target=opponent.hero)
    assert (gidra.atk, gidra.health) == (5, 8)


def test_sch_236_diligent_notetaker_returns_the_spell():
    _, player, opponent = ready()
    player.give("SCH_236").play()
    spell = player.give("CS2_029")
    spell.play(target=opponent.hero)
    assert spell.zone == Zone.HAND


def test_sch_239_krolusk_barkstripper_destroys_an_enemy_minion():
    _, player, opponent = ready()
    victim = opponent.summon("CS2_182")
    player.give("SCH_239").play()
    player.give("GAME_005").play()
    assert victim.zone == Zone.GRAVEYARD


def test_sch_242_gibberling_summons_another_gibberling():
    _, player, _ = ready()
    player.give("SCH_242").play()
    player.give("GAME_005").play()
    assert [card.id for card in player.field].count("SCH_242") == 2


def test_sch_244_teachers_pet_recruits_a_three_cost_beast():
    _, player, _ = ready()
    player.give("SCH_244").play().destroy()
    summoned = [card for card in player.field if card.type == CardType.MINION]
    assert summoned and all(Race.BEAST in card.races and card.cost == 3 for card in summoned)


def test_sch_271_molten_blast_summons_as_many_elementals_as_damage():
    _, player, opponent = ready()
    player.give("SCH_271").play(target=opponent.hero)
    assert opponent.hero.health == 28
    assert len([card for card in player.field if card.id == "SCH_271t"]) == 2


def test_sch_279_trueaim_crescent_makes_minions_attack_the_target():
    _, player, opponent = ready()
    attacker = player.summon("CS2_182")
    attacker.turns_in_play = 1
    victim = opponent.summon("CS2_182")
    player.give("SCH_279").play()
    player.hero.attack(victim)
    assert victim.zone == Zone.GRAVEYARD


def test_sch_279_stops_forced_attacks_when_the_target_dies():
    _, player, opponent = ready()
    first = player.summon("CS2_182")
    second = player.summon("CS2_182")
    victim = opponent.summon("CS2_182")
    player.give("SCH_279").play()
    player.hero.attack(victim)
    assert victim.zone == Zone.GRAVEYARD
    assert first.health == 1 and second.health == second.max_health


def test_sch_279_forced_attack_ignores_frozen_and_cant_attack():
    _, player, opponent = ready()
    frozen = player.summon("CS2_182")
    frozen.frozen = True
    blocked = player.summon("CS2_182")
    blocked.cant_attack = True
    victim = opponent.summon("CS2_182")
    victim.max_health = 12
    player.give("SCH_279").play()
    player.hero.attack(victim)
    assert victim.damage == 9


def test_sch_300_carrion_studies_discounts_the_next_deathrattle_minion():
    _, player, _ = ready()
    studies = player.give("SCH_300").play()
    assert player.choice
    choice = next(card for card in player.choice.cards if card.has_deathrattle)
    base_cost = choice.data.cost
    player.choice.choose(choice)
    assert choice in player.hand and choice.cost == max(0, base_cost - 1)
    choice.play()
    assert studies.zone == Zone.GRAVEYARD


def test_sch_301_rune_dagger_grants_spell_damage_for_the_turn():
    game, player, opponent = ready()
    player.give("SCH_301").play()
    player.hero.attack(opponent.hero)
    assert player.spellpower == 1
    player.weapon.destroy()
    assert player.weapon is None and player.spellpower == 1
    game.end_turn()
    game.end_turn()
    assert player.spellpower == 0


def test_sch_333_nature_studies_discounts_the_next_spell():
    _, player, _ = ready()
    player.give("SCH_333").play()
    assert player.choice
    choice = player.choice.cards[0]
    base_cost = choice.data.cost
    player.choice.choose(choice)
    assert choice in player.hand and choice.cost == max(0, base_cost - 1)


def test_sch_340_bloated_python_summons_a_hapless_handler():
    _, player, _ = ready()
    player.give("SCH_340").play().destroy()
    assert any(card.id == "SCH_340t" for card in player.field)


def test_sch_427_lightning_bloom_gives_temporary_mana_and_overload():
    game, player, _ = ready()
    player.used_mana = 5
    player.give("SCH_427").play()
    assert player.temp_mana == 2 and player.overloaded == 2
    game.end_turn()
    assert player.temp_mana == 0


def test_sch_507_instructor_fireheart_repeats_when_the_discovered_spell_is_played():
    _, player, opponent = ready()
    player.give("SCH_507").play()
    choice = next(card for card in player.choice.cards if not card.requires_target())
    player.choice.choose(choice)
    choice.play()
    assert player.choice and all(card.cost >= 1 for card in player.choice.cards)


def test_sch_507_multiple_firehearts_keep_independent_pending_spells():
    _, player, _ = ready()
    player.max_mana = 10
    first = player.give("SCH_507").play()
    first_spell = next(card for card in player.choice.cards if not card.requires_target())
    player.choice.choose(first_spell)
    second = player.give("SCH_507").play()
    second_spell = next(card for card in player.choice.cards if not card.requires_target())
    player.choice.choose(second_spell)

    first_spell.play()
    assert player.choice
    player.choice.choose(player.choice.cards[0])
    second_spell.play()
    assert player.choice


def test_sch_535_tidal_wave_hits_all_minions_and_lifesteals():
    _, player, opponent = ready()
    own = player.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    player.hero.damage = 5
    player.give("SCH_535").play()
    assert own.health == enemy.health == 2
    assert player.hero.health == 30


def test_sch_538_ace_hunter_kreen_protects_other_attacking_characters():
    _, player, opponent = ready()
    player.give("SCH_538").play()
    attacker = player.summon("CS2_182")
    attacker.turns_in_play = 1
    victim = opponent.summon("CS2_182")
    attacker.attack(victim)
    assert attacker.health == 5


def test_sch_539_professor_slate_makes_spell_damage_poisonous():
    _, player, opponent = ready()
    player.give("SCH_539").play()
    victim = opponent.summon("CS2_182")
    player.give("CS2_029").play(target=victim)
    assert victim.zone == Zone.GRAVEYARD


def test_sch_539_professor_slate_marks_indirect_spell_damage_too():
    _, player, opponent = ready()
    player.give("SCH_539").play()
    victim = opponent.summon("CS2_182")
    spell = player.give("CS2_029")
    player.game.cheat_action(player, [CastSpell(spell, victim)])
    assert victim.zone == Zone.GRAVEYARD


def test_sch_600_demon_companion_summons_one_of_its_three_demons():
    _, player, _ = ready()
    player.give("SCH_600").play()
    assert player.field[-1].id in {"SCH_600t1", "SCH_600t2", "SCH_600t3"}


def test_sch_604_overwhelm_scales_with_friendly_beasts():
    _, player, opponent = ready()
    player.summon("SCH_340")
    player.summon("SCH_244")
    victim = opponent.summon("CS2_182")
    player.give("SCH_604").play(target=victim)
    assert victim.health == 1


def test_sch_606_partner_assignment_adds_two_costed_beasts():
    _, player, _ = ready()
    player.give("SCH_606").play()
    assert len(player.hand) == 2
    assert all(card.type == CardType.MINION and Race.BEAST in card.races for card in player.hand)
    assert {card.cost for card in player.hand} == {2, 3}


def test_sch_607_shando_wildclaw_has_both_choose_one_branches():
    _, player, _ = ready()
    deck_beast = player.card("SCH_340", zone=Zone.DECK)
    player.summon("SCH_340")
    wildclaw = player.give("SCH_607").play(choose="SCH_607b")
    assert deck_beast.atk == 2 and deck_beast.max_health == 3

    player.discard_hand()
    target = player.summon("SCH_340")
    wildclaw = player.give("SCH_607").play(target=target, choose="SCH_607a")
    assert wildclaw.morphed and wildclaw.morphed.id == "SCH_340"


def test_sch_607_controller_legal_actions_expose_each_branch_correctly():
    game, player, _ = ready()
    session = GameSession(game, {})
    deck_beast = player.card("SCH_340", zone=Zone.DECK)
    friendly = player.summon("SCH_340")
    wildclaw = player.give("SCH_607")
    branches = {branch.id: branch for branch in wildclaw.choose_cards}
    actions = [action for action in session.legal_actions(player)
               if action.type == "PLAY_CARD"
               and action.source_entity_id == wildclaw.entity_id]
    deck_action = next(
        action for action in actions
        if action.choose_option_entity_id == branches["SCH_607b"].entity_id
    )
    assert deck_action.target_entity_id is None
    session.execute(player, deck_action)
    assert deck_beast.atk == 2 and deck_beast.max_health == 3

    game, player, _ = ready()
    session = GameSession(game, {})
    target = player.summon("SCH_340")
    wildclaw = player.give("SCH_607")
    branches = {branch.id: branch for branch in wildclaw.choose_cards}
    actions = [action for action in session.legal_actions(player)
               if action.type == "PLAY_CARD"
               and action.source_entity_id == wildclaw.entity_id
               and action.choose_option_entity_id == branches["SCH_607a"].entity_id]
    transform_action = next(
        action for action in actions
        if action.target_entity_id == target.entity_id
    )
    session.execute(player, transform_action)
    assert wildclaw.morphed and wildclaw.morphed.id == "SCH_340"


def test_sch_609_survival_of_the_fittest_buffs_hand_deck_and_field():
    _, player, _ = ready()
    hand = player.give("SCH_340")
    deck = player.card("SCH_340", zone=Zone.DECK)
    field = player.summon("SCH_340")
    player.give("SCH_609").play()
    assert (hand.atk, hand.max_health) == (5, 6)
    assert (deck.atk, deck.max_health) == (5, 6)
    assert (field.atk, field.health) == (5, 6)


def test_sch_610_guardian_animals_summons_two_deck_beasts_with_rush():
    _, player, _ = ready()
    player.card("SCH_340", zone=Zone.DECK)
    player.card("SCH_244", zone=Zone.DECK)
    player.give("SCH_610").play()
    animals = [card for card in player.field if card.id in {"SCH_340", "SCH_244"}]
    assert len(animals) == 2 and all(card.rush for card in animals)


def test_sch_612_runic_carvings_branches_and_overload_are_distinct():
    _, player, _ = ready()
    player.give("SCH_612").play(choose="SCH_612a")
    assert len([card for card in player.field if card.id == "SCH_612t"]) == 4

    _, player, _ = ready()
    player.give("SCH_612").play(choose="SCH_612b")
    totems = [card for card in player.field if card.id == "SCH_612t"]
    assert len(totems) == 4 and all(card.rush for card in totems)
    assert player.overloaded == 2


def test_sch_613_groundskeeper_restores_health_when_holding_a_large_spell():
    _, player, _ = ready()
    player.hero.damage = 5
    player.give("SCH_535")
    player.give("SCH_613").play()
    assert player.hero.health == 30


def test_sch_614_omu_spellburst_refreshes_spent_mana():
    _, player, _ = ready()
    omu = player.give("SCH_614").play()
    player.used_mana = 5
    player.give("GAME_005").play()
    assert omu.spellburst_used and player.used_mana == 0


def test_sch_615_totem_goliath_summons_all_basic_totems_on_death():
    _, player, _ = ready()
    player.give("SCH_615").play().destroy()
    assert {card.id for card in player.field} == {"CS2_050", "CS2_051", "CS2_052", "NEW1_009"}


def test_sch_616_twilight_runner_draws_two_after_attacking():
    _, player, opponent = ready()
    first = player.card("CS2_029", zone=Zone.DECK)
    second = player.card("CS2_029", zone=Zone.DECK)
    runner = player.give("SCH_616").play()
    runner.turns_in_play = 1
    runner.attack(opponent.summon("CS2_182"))
    assert first.zone == second.zone == Zone.HAND


def test_sch_617_adorable_infestation_buffs_summons_and_adds_a_cub():
    _, player, _ = ready()
    target = player.summon("CS2_182")
    player.give("SCH_617").play(target=target)
    assert (target.atk, target.health) == (5, 6)
    assert any(card.id == "SCH_617t" for card in player.field)
    assert any(card.id == "SCH_617t" for card in player.hand)


def test_sch_618_blood_herald_gains_attack_and_health_from_hand_deaths():
    _, player, _ = ready()
    herald = player.give("SCH_618")
    victim = player.summon("CS2_182")
    victim.destroy()
    assert (herald.atk, herald.max_health) == (2, 2)
