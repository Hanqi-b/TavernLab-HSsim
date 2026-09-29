"""Targeted regressions for Leeching Poison and Valeera the Hollow."""

from hearthstone.enums import CardClass, GameTag, Zone

from utils import prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.ROGUE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_leeching_poison_grants_weapon_lifesteal_only_this_turn():
    game, owner, opponent = ready_game()
    weapon = owner.give("CS2_091")
    weapon.play()
    assert weapon.zone == Zone.PLAY and not weapon.lifesteal
    owner.hero.damage = 5
    poison = owner.give("ICC_221")
    poison.play()
    assert poison.zone == Zone.GRAVEYARD and weapon.lifesteal

    before_health = owner.hero.health
    owner.hero.attack(opponent.hero)
    assert owner.hero.health == before_health + weapon.atk
    assert weapon.durability == 3

    game.end_turn()
    assert weapon.zone == Zone.PLAY and not weapon.lifesteal
    game.end_turn()
    before_health = owner.hero.health
    owner.hero.attack(opponent.hero)
    assert owner.hero.health == before_health


def test_leeching_poison_expiry_preserves_native_weapon_lifesteal():
    game, owner, _ = ready_game()
    weapon = owner.give("CS2_091")
    weapon.play()
    weapon.tags[GameTag.LIFESTEAL] = True
    owner.give("ICC_221").play()
    assert weapon.lifesteal
    game.end_turn()
    assert weapon.zone == Zone.PLAY and weapon.lifesteal
    assert not any(buff.id == "ICC_221e" for buff in weapon.buffs)


def test_valeera_used_shadow_reflection_expires_at_turn_end():
    game, owner, _ = ready_game()
    valeera = owner.give("ICC_827")
    valeera.play()
    assert valeera.zone == Zone.PLAY and owner.hero.stealthed
    reflection = next(card for card in owner.hand if card.id == "ICC_827t")

    owner.give("CS2_231").play()
    assert reflection.zone == Zone.SETASIDE
    transformed = next(card for card in owner.hand if card.id == "CS2_231")
    assert transformed.zone == Zone.HAND
    assert any(buff.id == "ICC_827e" for buff in transformed.buffs)
    game.end_turn()
    assert transformed.zone == Zone.GRAVEYARD and transformed not in owner.hand

    game.end_turn()
    assert not owner.hero.stealthed
    assert sum(card.id == "ICC_827t" for card in owner.hand) == 1


def test_valeera_unused_shadow_reflection_expires_at_turn_end():
    game, owner, _ = ready_game()
    owner.give("ICC_827").play()
    reflection = next(card for card in owner.hand if card.id == "ICC_827t")
    game.end_turn()
    assert reflection.zone == Zone.GRAVEYARD and reflection not in owner.hand
    game.end_turn()
    assert sum(card.id == "ICC_827t" for card in owner.hand) == 1
