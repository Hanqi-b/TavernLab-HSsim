"""Distinguish Tracking's choice transfer from a normal draw."""

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


def game_with_chromaggus():
    game = prepare_empty_game(CardClass.HUNTER, CardClass.MAGE)
    player = game.player1
    player.discard_hand()
    player.summon("BRM_031")
    return game, player


def test_normal_draw_triggers_chromaggus_and_updates_draw_state():
    game, player = game_with_chromaggus()
    deck_card = player.card("CS2_182", zone=Zone.DECK)
    before = player.cards_drawn_this_turn

    drawn = player.draw()

    assert drawn is deck_card and drawn.zone == Zone.HAND
    assert player.cards_drawn_this_turn == before + 1
    assert drawn.turn_drawn == game.turn
    assert len([card for card in player.hand if card.id == deck_card.id]) == 2


def test_tracking_choice_does_not_count_as_draw_or_trigger_chromaggus():
    game, player = game_with_chromaggus()
    top_three = [
        player.card("CS2_231", zone=Zone.DECK),
        player.card("CS2_182", zone=Zone.DECK),
        player.card("CS2_029", zone=Zone.DECK),
    ]
    before = player.cards_drawn_this_turn

    tracking = player.give("DS1_184")
    tracking.play()
    assert list(player.choice.cards) == top_three
    selected = top_three[1]
    player.choice.choose(selected)

    assert tracking.zone == Zone.GRAVEYARD
    assert selected.zone == Zone.HAND
    assert all(card.zone == Zone.REMOVEDFROMGAME for card in (top_three[0], top_three[2]))
    assert player.cards_drawn_this_turn == before
    assert selected.turn_drawn != game.turn
    assert len([card for card in player.hand if card.id == selected.id]) == 1
