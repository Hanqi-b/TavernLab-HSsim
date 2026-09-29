"""Blade of C'Thun uses the destroyed minion's current Health."""

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
    cthun = game.player1.give("OG_280")
    blade = game.player1.give("OG_282")
    return game, cthun, blade


def test_blade_of_cthun_adds_wounded_targets_current_health():
    game, cthun, blade = ready_game()
    target = game.player2.summon("CS2_182")
    target.set_current_health(2)
    assert target.health == 2 and target.max_health > target.health
    before = (cthun.atk, cthun.health)
    attack, current_health = target.atk, target.health

    blade.play(target=target)

    assert target.zone == Zone.GRAVEYARD
    assert blade.zone == Zone.PLAY and cthun.zone == Zone.HAND
    assert (cthun.atk, cthun.health) == (before[0] + attack, before[1] + current_health)


def test_blade_of_cthun_adds_healthy_targets_full_current_health():
    game, cthun, blade = ready_game()
    target = game.player2.summon("CS2_182")
    assert target.health == target.max_health
    before = (cthun.atk, cthun.health)
    attack, current_health = target.atk, target.health

    blade.play(target=target)

    assert target.zone == Zone.GRAVEYARD
    assert blade.zone == Zone.PLAY
    assert (cthun.atk, cthun.health) == (before[0] + attack, before[1] + current_health)


def test_blade_of_cthun_buffs_cthun_while_it_is_in_deck():
    game, cthun, blade = ready_game()
    cthun.shuffle_into_deck()
    target = game.player2.summon("CS2_182")
    target.set_current_health(2)
    before = (cthun.atk, cthun.health)
    attack, current_health = target.atk, target.health

    blade.play(target=target)

    assert target.zone == Zone.GRAVEYARD
    assert cthun.zone == Zone.DECK and cthun in game.player1.deck
    assert (cthun.atk, cthun.health) == (before[0] + attack, before[1] + current_health)


def test_blade_of_cthun_without_minion_target_does_not_buff_cthun():
    game, cthun, blade = ready_game()
    before = (cthun.atk, cthun.health)
    assert not blade.requires_target()

    blade.play()

    assert blade.zone == Zone.PLAY and cthun.zone == Zone.HAND
    assert (cthun.atk, cthun.health) == before
