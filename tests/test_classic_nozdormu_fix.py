"""Regression tests for Nozdormu's player timeout aura."""

from hearthstone.enums import CardClass

from utils import prepare_empty_game


def _game_with_nozdormu():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    nozdormu = game.player1.give("EX1_560").play()
    return game, nozdormu


def _serialized_timeouts(game):
    return [
        (player.timeout, player.dump()["timeout"], player.dump_hidden()["timeout"])
        for player in game.players
    ]


def test_nozdormu_sets_both_player_timeouts_and_serializes_them():
    game, _ = _game_with_nozdormu()

    assert _serialized_timeouts(game) == [(15, 15, 15), (15, 15, 15)]


def test_nozdormu_timeout_restores_after_silence():
    game, nozdormu = _game_with_nozdormu()

    nozdormu.silence()
    assert _serialized_timeouts(game) == [(75, 75, 75), (75, 75, 75)]


def test_nozdormu_timeout_restores_after_death():
    game, nozdormu = _game_with_nozdormu()

    nozdormu.destroy()
    assert _serialized_timeouts(game) == [(75, 75, 75), (75, 75, 75)]
