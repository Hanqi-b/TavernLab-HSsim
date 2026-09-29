"""Individual behavior checks for the remaining Demon Hunter Initiate red cards."""

import pytest
from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction
from utils import WISP, prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.DEMONHUNTER, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_battlefiend_only_gains_attack_after_owners_hero_attack():
    game, owner, opponent = ready_game()
    fiend = owner.give("BT_351").play()
    owner.hero.atk = 1
    owner.hero.attack(opponent.hero)
    assert fiend.atk == 2 and opponent.hero.health == 29
    game.end_turn()
    opponent.hero.atk = 1
    opponent.hero.attack(owner.hero)
    assert fiend.atk == 2 and fiend.zone == Zone.PLAY


def test_feast_of_souls_draws_for_friendly_deaths_this_turn_only():
    game, owner, opponent = ready_game()
    cards = [owner.card(WISP, zone=Zone.DECK) for _ in range(4)]
    owner.summon(WISP).destroy()
    owner.summon(WISP).destroy()
    opponent.summon(WISP).destroy()
    feast = owner.give("BT_427").play()
    assert feast.zone == Zone.GRAVEYARD
    assert len([c for c in cards if c.zone == Zone.HAND]) == 2
    game.end_turn()
    game.end_turn()
    drawn_before_second_feast = len([c for c in cards if c.zone == Zone.HAND])
    owner.give("BT_427").play()
    assert len([c for c in cards if c.zone == Zone.HAND]) == drawn_before_second_feast
    assert any(c.zone == Zone.DECK for c in cards)


def test_nethrandamus_upgrades_after_friendly_death_and_summons_two_to_owner():
    _, owner, opponent = ready_game()
    card = owner.give("BT_481")
    owner.summon(WISP).destroy()
    assert card.progress == 1
    card.play()
    summons = [m for m in owner.field if m is not card]
    assert card.zone == Zone.PLAY
    assert len(summons) == 2 and all(m.cost == 1 for m in summons)
    assert not opponent.field


def test_wrathspike_brute_hits_opponent_side_only_after_it_is_attacked():
    game, owner, opponent = ready_game()
    brute = owner.give("BT_510").play()
    attacker = opponent.summon("CS2_182")
    other = opponent.summon("CS2_182")
    game.end_turn()
    attacker.attack(brute)
    assert brute.zone == Zone.PLAY
    assert opponent.hero.health == 29 and other.health == 4
    assert owner.hero.health == 30


def test_wrathspike_brute_own_attack_does_not_trigger_damage():
    game, owner, opponent = ready_game()
    brute = owner.give("BT_510").play()
    target = opponent.summon("CS2_182")
    game.end_turn()
    game.end_turn()
    brute.attack(target)
    assert opponent.hero.health == 30


def test_eye_beam_requires_minion_and_heals_for_actual_damage():
    _, owner, opponent = ready_game()
    owner.hero.hit(5)
    target = opponent.summon("CS2_182")
    beam = owner.give("BT_801")
    with pytest.raises(InvalidAction):
        beam.play()
    assert beam.zone == Zone.HAND and owner.hero.health == 25
    beam.play(target=target)
    assert beam.zone == Zone.GRAVEYARD and target.health == 2
    assert owner.hero.health == 28


def test_eye_beam_costs_one_only_in_outcast_position():
    _, owner, opponent = ready_game()
    target = opponent.summon("CS2_182")
    owner.give(WISP)
    middle = owner.give("BT_801")
    owner.give(WISP)
    assert middle.cost == 3
    middle.play(target=target)
    assert target.health == 2

    target2 = opponent.summon("CS2_182")
    right = owner.give("BT_801")
    assert right.cost == 1
    right.play(target=target2)
    assert target2.health == 2
