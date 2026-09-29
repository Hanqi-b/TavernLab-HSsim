"""Kobold Monk protects its controller's hero from chosen spell/power targets."""

import pytest
from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction
from utils import prepare_empty_game


def test_kobold_monk_protects_only_friendly_hero_while_in_play():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    owner, opponent = game.player1, game.player2
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0

    monk = owner.give("LOOT_382").play()
    assert monk.zone == Zone.PLAY
    game.end_turn()
    spell = opponent.give("CS2_029")
    mana = opponent.mana
    assert owner.hero not in spell.play_targets
    assert opponent.hero in spell.play_targets
    assert owner.hero not in opponent.hero.power.play_targets
    assert opponent.hero in opponent.hero.power.play_targets
    with pytest.raises(InvalidAction):
        spell.play(target=owner.hero)
    assert spell.zone == Zone.HAND and opponent.mana == mana

    monk.destroy()
    assert monk.zone == Zone.GRAVEYARD
    assert owner.hero in spell.play_targets
    assert owner.hero in opponent.hero.power.play_targets
