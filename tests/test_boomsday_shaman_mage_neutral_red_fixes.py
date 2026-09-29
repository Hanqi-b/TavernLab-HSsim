"""Targeted behavior tests for four BOOMSDAY red-card fixes."""

import pytest

from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction
from utils import FIREBALL, MOONFIRE, WISP, prepare_empty_game


def ready_game(owner_class=CardClass.SHAMAN, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(owner_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_electra_doubles_only_the_next_spell_and_queues_both_overloads():
    _, owner, opponent = ready_game()
    before = opponent.hero.health

    owner.give("BOT_411").play()
    owner.give("EX1_238").play(target=opponent.hero)

    assert opponent.hero.health == before - 6
    assert owner.overloaded == 2
    assert not [buff for buff in owner.buffs if buff.id == "BOT_411e"]

    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == before - 7


def test_electra_expires_at_its_controller_turn_end_without_a_spell():
    game, owner, _ = ready_game()

    owner.give("BOT_411").play()
    assert [buff for buff in owner.buffs if buff.id == "BOT_411e"]

    game.end_turn()

    assert not [buff for buff in owner.buffs if buff.id == "BOT_411e"]


def test_voltaic_burst_summons_rush_sparks_and_locks_one_mana_next_turn():
    game, owner, opponent = ready_game()
    owner.give("BOT_451").play()

    sparks = [card for card in owner.field if card.id == "BOT_102t"]
    assert len(sparks) == 2
    assert all(
        (spark.atk, spark.health, spark.rush, spark.turns_in_play)
        == (1, 1, True, 0)
        for spark in sparks
    )
    assert owner.overloaded == 1
    assert owner.overload_locked == 0

    enemy = opponent.summon(WISP)
    assert sparks[0].can_attack(enemy)
    assert not sparks[1].can_attack(opponent.hero)
    with pytest.raises(InvalidAction):
        sparks[1].attack(opponent.hero)
    sparks[0].attack(enemy)
    assert enemy.zone == Zone.GRAVEYARD

    game.end_turn()
    game.end_turn()
    assert owner.overloaded == 0
    assert owner.overload_locked == 1


def test_celestial_emissary_gives_spell_damage_to_only_the_next_spell():
    _, owner, opponent = ready_game(CardClass.MAGE)
    before = opponent.hero.health

    owner.give("BOT_531").play()
    assert owner.spellpower == 2
    owner.give(MOONFIRE).play(target=opponent.hero)

    assert opponent.hero.health == before - 3
    assert owner.spellpower == 0

    owner.give(FIREBALL).play(target=opponent.hero)
    assert opponent.hero.health == before - 9


def test_celestial_emissary_expires_at_its_controller_turn_end():
    game, owner, _ = ready_game(CardClass.MAGE)

    owner.give("BOT_531").play()
    assert owner.spellpower == 2
    game.end_turn()

    assert owner.spellpower == 0
    assert not [buff for buff in owner.buffs if buff.id == "BOT_531e"]


def test_loose_specimen_splits_six_damage_among_other_friendly_minions():
    game, owner, opponent = ready_game(CardClass.HUNTER)
    game.random.seed(17)
    first = owner.summon("EX1_399")
    second = owner.summon("EX1_399")
    before = (first.health, second.health)
    specimen = owner.give("BOT_544").play()

    assert specimen.zone == Zone.PLAY
    assert specimen.damage == 0
    assert owner.hero.health == 30
    assert opponent.hero.health == 30
    assert first.zone == Zone.PLAY and second.zone == Zone.PLAY
    assert (before[0] - first.health) + (before[1] - second.health) == 6


def test_loose_specimen_with_no_other_friendly_minion_does_not_hit_itself():
    _, owner, opponent = ready_game(CardClass.HUNTER)
    specimen = owner.give("BOT_544").play()
    assert specimen.zone == Zone.PLAY
    assert specimen.damage == 0
    assert owner.hero.health == 30 and opponent.hero.health == 30
