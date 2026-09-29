"""Regression tests for the confirmed NAXX collectible card fixes."""

from hearthstone.enums import CardClass, Zone

from utils import GOLDSHIRE_FOOTMAN, prepare_empty_game


def test_wailing_soul_silences_other_friendly_minions_only():
    game = prepare_empty_game(CardClass.PRIEST, CardClass.MAGE)
    player = game.current_player
    opponent = player.opponent

    friendly = player.summon(GOLDSHIRE_FOOTMAN)
    enemy = opponent.summon(GOLDSHIRE_FOOTMAN)
    soul = player.give("FP1_016")
    soul.play()

    assert friendly.silenced
    assert not friendly.taunt
    assert not soul.silenced
    assert not enemy.silenced
    assert enemy.taunt


def test_reincarnate_resummons_to_each_target_controller_at_full_health():
    game = prepare_empty_game(CardClass.SHAMAN, CardClass.MAGE)
    player = game.current_player
    opponent = player.opponent

    friendly = player.summon(GOLDSHIRE_FOOTMAN)
    friendly.hit(1)
    player.give("FP1_025").play(target=friendly)
    friendly_copy = player.field[0]
    assert friendly.zone == Zone.GRAVEYARD
    assert friendly_copy is not friendly
    assert friendly_copy.controller is player
    assert friendly_copy.health == friendly_copy.max_health == 2

    enemy = opponent.summon(GOLDSHIRE_FOOTMAN)
    enemy.hit(1)
    player.give("FP1_025").play(target=enemy)
    enemy_copy = opponent.field[0]
    assert enemy.zone == Zone.GRAVEYARD
    assert enemy_copy is not enemy
    assert enemy_copy.controller is opponent
    assert enemy_copy.health == enemy_copy.max_health == 2
    assert all(card.controller is player for card in player.field)
    assert enemy_copy not in player.field


def test_reincarnate_enemy_cthun_uses_its_controllers_permanent_buffs():
    game = prepare_empty_game(CardClass.SHAMAN, CardClass.MAGE)
    player = game.current_player
    opponent = player.opponent
    opponent.cthun.buff(opponent.cthun, "OG_281e", atk=4, max_health=4)
    cthun = opponent.summon("OG_280")
    assert (cthun.atk, cthun.max_health) == (10, 10)

    spell = player.give("FP1_025")
    spell.play(target=cthun)

    reborn = opponent.field[0]
    assert cthun.zone == Zone.GRAVEYARD
    assert reborn is not cthun
    assert reborn.controller is opponent
    assert reborn.creator is spell
    assert (reborn.atk, reborn.health, reborn.max_health) == (10, 10, 10)


def test_dancing_swords_draws_known_opponent_card_and_updates_target_counter():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.MAGE)
    player = game.current_player
    opponent = player.opponent
    player.discard_hand()
    opponent.discard_hand()

    known = opponent.card("CS2_182", zone=Zone.DECK)
    swords = player.summon("FP1_029")
    player_draws_before = player.cards_drawn_this_turn
    opponent_draws_before = opponent.cards_drawn_this_turn

    swords.destroy()

    assert swords.zone == Zone.GRAVEYARD
    assert known.zone == Zone.HAND
    assert known in opponent.hand and not opponent.deck
    assert player.cards_drawn_this_turn == player_draws_before
    assert opponent.cards_drawn_this_turn == opponent_draws_before + 1
