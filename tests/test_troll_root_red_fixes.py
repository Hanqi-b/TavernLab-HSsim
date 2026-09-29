"""Independent behavior checks for six Rastakhan red cards."""

import pytest
from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction
from utils import FIREBALL, MOONFIRE, WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_spellzerker_has_two_spell_damage_only_while_damaged():
    _, owner, opponent = ready_game()
    zerker = owner.summon("TRL_312")
    assert zerker.spellpower == 0 and owner.spellpower == 0
    owner.give(MOONFIRE).play(target=zerker)
    assert zerker.zone == Zone.PLAY and zerker.health == 2
    assert zerker.spellpower == 2 and owner.spellpower == 2
    before = opponent.hero.health
    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == before - 3

    owner.give("CS2_089").play(target=zerker)
    assert zerker.health == zerker.max_health
    assert zerker.spellpower == 0 and owner.spellpower == 0
    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == before - 4


def test_scorch_costs_four_without_previous_elemental_and_deals_four():
    _, owner, opponent = ready_game(CardClass.MAGE)
    target = opponent.summon("CS2_182")
    scorch = owner.give("TRL_313")
    assert scorch.cost == 4
    before = owner.mana
    scorch.play(target=target)
    assert scorch.zone == Zone.GRAVEYARD
    assert owner.mana == before - 4
    assert target.health == 1


def test_scorch_costs_one_after_elemental_played_last_turn():
    game, owner, opponent = ready_game(CardClass.MAGE)
    elemental = owner.give("CS2_033").play()
    assert elemental.zone == Zone.PLAY
    game.end_turn()
    game.end_turn()
    target = opponent.summon("CS2_182")
    scorch = owner.give("TRL_313")
    assert scorch.cost == 1
    before = owner.mana
    scorch.play(target=target)
    assert scorch.zone == Zone.GRAVEYARD
    assert owner.mana == before - 1
    assert target.health == 1


def test_untamed_beastmaster_buffs_only_beast_drawn_into_hand():
    _, owner, opponent = ready_game()
    beastmaster = owner.summon("TRL_405")
    beast = owner.card("CS2_172", zone=Zone.DECK)
    owner.draw()
    assert beastmaster.zone == Zone.PLAY
    assert beast.zone == Zone.HAND and (beast.atk, beast.max_health) == (5, 4)

    plain = owner.card("CS2_182", zone=Zone.DECK)
    owner.draw()
    assert plain.zone == Zone.HAND and (plain.atk, plain.max_health) == (4, 5)
    enemy_beast = opponent.card("CS2_172", zone=Zone.DECK)
    opponent.draw()
    assert enemy_beast.zone == Zone.HAND and (enemy_beast.atk, enemy_beast.max_health) == (3, 2)


def test_auchenai_phantasm_converts_healing_only_until_owners_turn_end():
    game, owner, opponent = ready_game(CardClass.PRIEST)
    owner.give(FIREBALL).play(target=owner.hero)
    assert owner.hero.health == 24
    phantasm = owner.give("TRL_501").play()
    assert phantasm.zone == Zone.PLAY and owner.healing_as_damage
    owner.give("TRL_128").play(target=owner.hero)
    assert owner.hero.health == 21
    game.end_turn()
    assert not owner.healing_as_damage
    game.end_turn()
    owner.give("TRL_128").play(target=owner.hero)
    assert owner.hero.health == 24


def test_shieldbreaker_silences_only_enemy_taunt_target():
    _, owner, opponent = ready_game()
    taunt = opponent.summon("CS1_042")
    plain = opponent.summon("CS2_182")
    card = owner.give("TRL_524")
    assert taunt in card.play_targets and plain not in card.play_targets
    card.play(target=taunt)
    assert card.zone == Zone.PLAY
    assert taunt.zone == Zone.PLAY and taunt.silenced and not taunt.taunt
    assert not plain.silenced


def test_shieldbreaker_ignores_non_taunt_target_when_no_taunt_exists():
    _, owner, opponent = ready_game()
    plain = opponent.summon("CS2_182")
    card = owner.give("TRL_524")
    mana = owner.mana
    assert not card.play_targets
    card.play(target=plain)
    assert card.zone == Zone.PLAY and owner.mana == mana - card.cost
    assert not plain.silenced and plain.zone == Zone.PLAY


def test_shieldbreaker_rejects_non_taunt_when_taunt_target_exists():
    _, owner, opponent = ready_game()
    opponent.summon("CS1_042")
    plain = opponent.summon("CS2_182")
    card = owner.give("TRL_524")
    mana = owner.mana
    with pytest.raises(InvalidAction):
        card.play(target=plain)
    assert card.zone == Zone.HAND and owner.mana == mana
    assert not plain.silenced


def test_drakkari_trickster_gives_each_player_copy_from_opponents_deck():
    _, owner, opponent = ready_game()
    own_deck_spell = owner.card(FIREBALL, zone=Zone.DECK)
    enemy_deck_minion = opponent.card(WISP, zone=Zone.DECK)
    trickster = owner.give("TRL_527").play()
    assert trickster.zone == Zone.PLAY
    assert own_deck_spell.zone == Zone.DECK and enemy_deck_minion.zone == Zone.DECK
    own_received = [card for card in owner.hand if card.id == WISP]
    enemy_received = [card for card in opponent.hand if card.id == FIREBALL]
    assert len(own_received) == len(enemy_received) == 1
    assert own_received[0] is not enemy_deck_minion and own_received[0].zone == Zone.HAND
    assert enemy_received[0] is not own_deck_spell and enemy_received[0].zone == Zone.HAND
