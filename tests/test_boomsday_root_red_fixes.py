"""Card-specific checks for Crystalsmith Kangor and Cloakscale Chemist."""

from hearthstone.enums import CardClass, Zone

from utils import FIREBALL, MOONFIRE, prepare_empty_game


def ready_game(hero_class=CardClass.PALADIN):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_crystalsmith_kangor_doubles_spell_healing_and_lifesteal_healing():
    game, owner, opponent = ready_game()
    owner.give(FIREBALL).play(target=owner.hero)
    owner.used_mana = 0
    owner.give(FIREBALL).play(target=owner.hero)
    assert owner.hero.health == 18
    kangor = owner.give("BOT_236").play()
    assert kangor.divine_shield and kangor.lifesteal
    owner.used_mana = 0
    holy_light = owner.give("CS2_089")
    holy_light.play(target=owner.hero)
    assert holy_light.zone == Zone.GRAVEYARD
    assert owner.hero.health == 30

    owner.give(FIREBALL).play(target=owner.hero)
    assert owner.hero.health == 24
    enemy = opponent.summon("CS2_182")
    game.end_turn()
    game.end_turn()
    kangor.attack(enemy)
    assert kangor.zone == Zone.PLAY and kangor.health == 2
    assert not kangor.divine_shield
    assert enemy.health == 4
    assert owner.hero.health == 26


def test_cloakscale_chemist_stealth_and_shield_resolve_in_attack_order():
    game, owner, opponent = ready_game(CardClass.MAGE)
    chemist = owner.summon("BOT_414")
    enemy = opponent.summon("CS2_182")
    opposing_spell = opponent.give(MOONFIRE)
    assert chemist.stealthed and chemist.divine_shield and chemist.health == 2
    assert chemist not in opposing_spell.play_targets

    chemist.turns_in_play = 1
    chemist.attack(enemy)
    assert not chemist.stealthed
    assert not chemist.divine_shield  # Retaliation consumes the shield.
    assert chemist.health == 2 and enemy.health == 4

    game.end_turn()
    assert chemist in opposing_spell.play_targets
    opposing_spell.play(target=chemist)
    assert opposing_spell.zone == Zone.GRAVEYARD
    assert chemist.health == 1 and chemist.zone == Zone.PLAY
