import pytest

from hearthstone.enums import Zone

from fireplace.exceptions import InvalidAction
from utils import prepare_empty_game


def test_ex1_194_gives_a_minion_plus_two_attack_and_plus_six_health():
    game = prepare_empty_game()
    player = game.current_player

    target = player.give("CS1_042")
    target.play()
    target.set_current_health(1)
    infusion = player.give("EX1_194")

    assert target.zone == Zone.PLAY
    assert infusion.zone == Zone.HAND
    assert (target.atk, target.max_health, target.health) == (1, 2, 1)

    infusion.play(target=target)

    assert (target.atk, target.max_health, target.health) == (3, 8, 7)
    assert target.zone == Zone.PLAY
    assert infusion.zone == Zone.GRAVEYARD


def test_ex1_194_rejects_non_minion_targets_without_consuming_the_spell():
    game = prepare_empty_game()
    player = game.current_player
    infusion = player.give("EX1_194")
    mana_before = player.mana
    hero_health_before = player.hero.health

    with pytest.raises(InvalidAction):
        infusion.play(target=player.hero)

    assert infusion.zone == Zone.HAND
    assert player.mana == mana_before
    assert player.hero.health == hero_health_before
