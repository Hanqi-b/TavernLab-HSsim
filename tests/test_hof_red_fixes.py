"""Behavior regressions for the remaining HOF red cards."""

from hearthstone.enums import Zone

from utils import WISP, prepare_empty_game


def _deck_cards(player, count=2):
    return [player.card("CS2_182", zone=Zone.DECK) for _ in range(count)]


def test_coldlight_oracle_counts_draws_for_each_target_player():
    game = prepare_empty_game()
    game.player1.discard_hand()
    game.player2.discard_hand()
    first_cards = _deck_cards(game.player1)
    second_cards = _deck_cards(game.player2)

    oracle = game.player1.give("EX1_050")
    oracle.play()

    assert game.player1.cards_drawn_this_turn == 2
    assert game.player2.cards_drawn_this_turn == 2
    assert all(card.zone == Zone.HAND and card in game.player1.hand for card in first_cards)
    assert all(card.zone == Zone.HAND and card in game.player2.hand for card in second_cards)
    assert not game.player1.deck and not game.player2.deck


def test_naturalize_kills_target_and_counts_opponent_draws():
    game = prepare_empty_game()
    game.player1.discard_hand()
    game.player2.discard_hand()
    opponent_cards = _deck_cards(game.player2)
    target = game.player2.summon(WISP)

    naturalize = game.player1.give("EX1_161")
    naturalize.play(target=target)

    assert target.zone == Zone.GRAVEYARD
    assert game.player1.cards_drawn_this_turn == 0
    assert game.player2.cards_drawn_this_turn == 2
    assert all(card.zone == Zone.HAND and card in game.player2.hand for card in opponent_cards)
    assert not game.player2.deck


def test_mind_control_tech_steals_with_room_on_receiving_board():
    game = prepare_empty_game()
    for _ in range(4):
        game.player1.summon(WISP)
    game.end_turn()

    mct = game.player2.give("EX1_085")
    mct.play()

    assert len(game.player1.field) == 3
    assert len(game.player2.field) == 2
    assert all(minion.controller is game.player1 for minion in game.player1.field)
    stolen = [minion for minion in game.player2.field if minion is not mct]
    assert len(stolen) == 1
    assert stolen[0].controller is game.player2


def test_mind_control_tech_destroys_target_when_receiving_board_is_full():
    game = prepare_empty_game()
    enemy_minions = [game.player1.summon(WISP) for _ in range(4)]
    for _ in range(6):
        game.player2.summon(WISP)
    game.end_turn()

    mct = game.player2.give("EX1_085")
    mct.play()

    assert len(game.player1.field) == 3
    assert len(game.player2.field) == 7
    assert len([minion for minion in enemy_minions if minion.zone == Zone.GRAVEYARD]) == 1
    assert all(minion.controller is game.player1 for minion in game.player1.field)
    assert mct in game.player2.field


def test_steal_destroys_in_play_minion_when_receiving_board_is_full():
    game = prepare_empty_game()
    target = game.player1.summon(WISP)
    for _ in range(7):
        game.player2.summon(WISP)

    game.player2.steal(target)

    assert target.zone == Zone.GRAVEYARD
    assert target not in game.player1.field
    assert len(game.player2.field) == 7


def test_temporary_control_return_destroys_minion_if_original_board_fills():
    game = prepare_empty_game()
    original_owner = game.current_player.opponent
    caster = game.current_player
    target = original_owner.summon(WISP)

    caster.give("EX1_334").play(target=target)
    assert target.controller is caster
    for _ in range(7):
        original_owner.summon(WISP)

    game.end_turn()

    assert target.zone == Zone.GRAVEYARD
    assert target not in caster.field
    assert len(original_owner.field) == 7
