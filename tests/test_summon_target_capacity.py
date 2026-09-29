from fireplace.actions import Summon
from hearthstone.enums import Zone

from utils import WISP, prepare_empty_game


def _summon_from(source, target, card):
    source.game.cheat_action(source, [Summon(target, card)])


def test_summon_uses_target_board_capacity_when_source_is_full():
    game = prepare_empty_game()
    for _ in range(7):
        game.player1.summon(WISP)

    card = game.player1.card(WISP)
    _summon_from(game.player1, game.player2, card)

    assert len(game.player1.field) == 7
    assert len(game.player2.field) == 1
    assert game.player2.field[0] is card
    assert card.controller is game.player2
    assert card.zone == Zone.PLAY


def test_summon_rejects_full_target_and_restores_card_state():
    game = prepare_empty_game()
    for _ in range(7):
        game.player2.summon(WISP)

    card = game.player1.card(WISP)
    _summon_from(game.player1, game.player2, card)

    assert len(game.player1.field) == 0
    assert len(game.player2.field) == 7
    assert card.controller is game.player1
    assert card.zone == Zone.SETASIDE


def test_repeated_summons_stop_at_seven_target_minions():
    game = prepare_empty_game()
    for _ in range(6):
        game.player2.summon(WISP)

    cards = [game.player1.card(WISP) for _ in range(3)]
    _summon_from(game.player1, game.player2, cards)

    assert len(game.player2.field) == 7
    assert sum(card.zone == Zone.PLAY for card in cards) == 1
    assert sum(card.zone == Zone.SETASIDE for card in cards) == 2
    assert sum(card.controller is game.player2 for card in cards) == 1
    assert sum(card.controller is game.player1 for card in cards) == 2


def test_cross_player_summon_rejects_a_minion_already_in_play():
    game = prepare_empty_game()
    card = game.player1.summon(WISP)

    _summon_from(game.player1, game.player2, card)

    assert card.controller is game.player1
    assert card in game.player1.field
    assert card not in game.player2.field
    assert card.zone == Zone.PLAY


def test_cross_player_summon_removes_card_from_original_hand():
    game = prepare_empty_game()
    card = game.player1.give(WISP)

    _summon_from(game.player1, game.player2, card)

    assert card not in game.player1.hand
    assert card in game.player2.field
    assert card.controller is game.player2
    assert card.zone == Zone.PLAY
