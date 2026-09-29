"""Regression tests for the Basic Demon Hunter card fixes."""

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


def test_bt_142_gives_hero_one_attack_until_turn_end():
    game = prepare_empty_game(CardClass.DEMONHUNTER, CardClass.DEMONHUNTER)
    if game.current_player is not game.player1:
        game.end_turn()
    player = game.player1
    base_attack = player.hero.atk

    player.give("BT_142").play()

    assert player.hero.atk == base_attack + 1
    game.end_turn()
    assert player.hero.atk == base_attack


def test_bt_323_offers_duplicate_physical_cards_and_puts_choice_on_top():
    game = prepare_empty_game(CardClass.DEMONHUNTER, CardClass.DEMONHUNTER)
    if game.current_player is not game.player1:
        game.end_turn()
    player = game.player1
    deck_cards = [player.card("CS2_231", zone=Zone.DECK) for _ in range(3)]
    deck_cards.append(player.card("CS2_182", zone=Zone.DECK))

    player.give("BT_323").play()

    choice = player.choice
    assert choice is not None
    assert len(choice.cards) == 3
    assert len({id(card) for card in choice.cards}) == 3
    assert sum(card.id == "CS2_231" for card in choice.cards) >= 2
    assert all(card in deck_cards for card in choice.cards)

    selected = choice.cards[1]
    choice.choose(selected)

    assert player.choice is None
    assert player.deck[-1] is selected
    assert len(player.deck) == 4
    assert all(card.zone == Zone.DECK for card in deck_cards)
    assert {id(card) for card in player.deck} == {id(card) for card in deck_cards}

    assert player.draw() is selected
    assert selected.zone == Zone.HAND
    assert {id(card) for card in player.deck} == {
        id(card) for card in deck_cards if card is not selected
    }
