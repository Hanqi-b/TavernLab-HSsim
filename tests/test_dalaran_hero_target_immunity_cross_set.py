"""Cross-set regression for hero spell/power target immunity."""

import pytest
from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction
from utils import prepare_empty_game


def test_spellward_jeweler_protects_hero_until_owner_next_turn():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    owner, opponent = game.player1, game.player2
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0

    jeweler = owner.give("DAL_081")
    jeweler.play()
    assert jeweler.zone == Zone.PLAY
    game.end_turn()
    spell = opponent.give("CS2_029")
    before_mana = opponent.mana
    assert owner.hero not in spell.play_targets
    assert owner.hero not in opponent.hero.power.play_targets
    with pytest.raises(InvalidAction):
        spell.play(target=owner.hero)
    assert spell.zone == Zone.HAND and opponent.mana == before_mana

    game.end_turn()
    assert owner.hero in opponent.give("CS2_029").play_targets
    assert jeweler.zone == Zone.PLAY
