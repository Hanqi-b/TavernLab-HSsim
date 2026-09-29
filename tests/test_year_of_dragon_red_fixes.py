"""Individual behavior regressions for the three remaining YOD red cards."""

from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_arcane_amplifier_adds_two_hero_power_damage_only_while_in_play():
    game, owner, opponent = ready_game()
    amplifier = owner.give("YOD_008").play()
    owner.hero.power.use(target=opponent.hero)
    assert opponent.hero.health == 27
    assert amplifier.zone == Zone.PLAY

    amplifier.destroy()
    game.end_turn()
    game.end_turn()
    owner.hero.power.use(target=opponent.hero)
    assert opponent.hero.health == 26


def test_aeon_reaver_uses_target_attack_not_its_own_attack():
    _, owner, opponent = ready_game()
    target = opponent.summon("CS2_182")
    target.atk = 2
    assert target.health == 5
    reaver = owner.give("YOD_014").play(target=target)
    assert reaver.zone == target.zone == Zone.PLAY
    assert target.health == 3


def test_skyvateer_deathrattle_draws_one_card_and_keeps_stealth():
    _, owner, _ = ready_game()
    draw_card = owner.card(WISP, zone=Zone.DECK)
    skyvateer = owner.give("YOD_016").play()
    assert skyvateer.zone == Zone.PLAY and skyvateer.stealthed
    assert skyvateer.has_deathrattle
    skyvateer.destroy()
    assert skyvateer.zone == Zone.GRAVEYARD
    assert draw_card.zone == Zone.HAND
    assert draw_card in owner.hand
