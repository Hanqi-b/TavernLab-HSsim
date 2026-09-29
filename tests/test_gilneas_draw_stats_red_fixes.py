"""Targeted behavior checks for four Witchwood draw/stat red cards."""

from hearthstone.enums import CardClass, Zone

from utils import FIREBALL, WISP, prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def put_on_top(player, card_id):
    card = player.card(card_id, zone=Zone.DECK)
    return card


def test_dollmaster_dorian_summons_a_one_one_copy_for_a_drawn_minion_only():
    _, owner, opponent = ready_game()
    dorian = owner.give("GIL_620").play()
    drawn_minion = put_on_top(owner, WISP)

    owner.draw()

    copies = [card for card in owner.field if card.id == WISP]
    assert drawn_minion.zone == Zone.HAND
    assert len(copies) == 1
    assert copies[0] is not drawn_minion
    assert (copies[0].atk, copies[0].health, copies[0].max_health) == (1, 1, 1)
    assert dorian.zone == Zone.PLAY

    drawn_spell = put_on_top(owner, FIREBALL)
    owner.draw()
    assert drawn_spell.zone == Zone.HAND
    assert len([card for card in owner.field if card.id == FIREBALL]) == 0
    assert len([card for card in owner.field if card.id == WISP]) == 1

    # The trigger belongs to Dorian's controller; an opponent's draw is inert.
    put_on_top(opponent, WISP)
    opponent.draw()
    assert len([card for card in owner.field if card.id == WISP]) == 1


def test_witchwood_grizzly_loses_current_health_for_opponent_hand_cards():
    _, owner, opponent = ready_game()
    for card_id in (WISP, FIREBALL, "CS2_182"):
        opponent.give(card_id)

    grizzly = owner.give("GIL_623").play()

    assert grizzly.zone == Zone.PLAY
    assert grizzly.taunt
    assert grizzly.max_health == 12
    assert grizzly.health == 9

    _, owner, opponent = ready_game()
    grizzly = owner.give("GIL_623").play()
    assert grizzly.zone == Zone.PLAY
    assert grizzly.taunt
    assert (grizzly.max_health, grizzly.health) == (12, 12)


def test_curio_collector_buffs_itself_for_each_card_drawn():
    _, owner, opponent = ready_game()
    collector = owner.give("GIL_640").play()
    drawn_minion = put_on_top(owner, WISP)
    drawn_spell = put_on_top(owner, FIREBALL)

    owner.draw()
    assert drawn_spell.zone == Zone.HAND
    assert (collector.atk, collector.health, collector.max_health) == (5, 5, 5)
    assert drawn_spell.cost == 4

    owner.draw()
    assert drawn_minion.zone == Zone.HAND
    assert (collector.atk, collector.health, collector.max_health) == (6, 6, 6)
    assert (drawn_minion.atk, drawn_minion.health, drawn_minion.max_health) == (1, 1, 1)

    put_on_top(opponent, WISP)
    opponent.draw()
    assert (collector.atk, collector.health, collector.max_health) == (6, 6, 6)


def test_archmage_arugal_copies_drawn_minions_but_not_spells():
    _, owner, opponent = ready_game()
    arugal = owner.give("GIL_691").play()
    drawn_minion = put_on_top(owner, WISP)

    owner.draw()

    minion_cards = [card for card in owner.hand if card.id == WISP]
    assert arugal.zone == Zone.PLAY
    assert drawn_minion.zone == Zone.HAND
    assert len(minion_cards) == 2
    assert minion_cards[0] is drawn_minion or minion_cards[1] is drawn_minion
    assert minion_cards[0] is not minion_cards[1]

    drawn_spell = put_on_top(owner, FIREBALL)
    owner.draw()
    assert drawn_spell.zone == Zone.HAND
    assert len([card for card in owner.hand if card.id == FIREBALL]) == 1
    assert len([card for card in owner.hand if card.id == WISP]) == 2

    put_on_top(opponent, WISP)
    opponent.draw()
    assert len([card for card in owner.hand if card.id == WISP]) == 2
