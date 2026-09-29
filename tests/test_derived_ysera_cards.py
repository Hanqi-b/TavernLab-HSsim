"""Strict behavior checks for Ysera and the five Dream cards she creates."""

import pytest

from hearthstone.enums import CardClass, Race, Zone

from fireplace import cards
from fireplace.dsl.random_picker import RandomCard
from fireplace.exceptions import InvalidAction
from utils import prepare_empty_game


DREAM_CARD_IDS = {
    "DREAM_01",
    "DREAM_02",
    "DREAM_03",
    "DREAM_04",
    "DREAM_05",
}


def ready_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_ysera_gives_a_dream_card_to_her_owner_at_the_end_of_her_turn_only():
    game, owner, opponent = ready_game()
    ysera = owner.summon("EX1_572")

    game.end_turn()

    assert len(owner.hand) == 1
    assert owner.hand[0].card_class == CardClass.DREAM
    assert opponent.hand == []

    owner.discard_hand()
    game.end_turn()

    assert owner.hand == []
    assert opponent.hand == []
    assert ysera.zone == Zone.PLAY


def test_ysera_random_dream_pool_contains_only_the_five_parent_cards():
    _, owner, _ = ready_game()
    ysera = owner.summon("EX1_572")

    pool = RandomCard(card_class=CardClass.DREAM).find_cards(ysera)

    assert set(pool) == DREAM_CARD_IDS
    assert all(cards.db[card_id].card_class == CardClass.DREAM for card_id in pool)


def test_dream_awakens_damages_every_character_except_all_yseras():
    _, owner, opponent = ready_game()
    friendly_ysera = owner.summon("EX1_572")
    enemy_ysera = opponent.summon("EX1_572")
    friendly_minion = owner.summon("CS2_231")
    enemy_minion = opponent.summon("CS2_231")

    awakens = owner.give("DREAM_02")
    awakens.play()

    assert (owner.hero.health, opponent.hero.health) == (25, 25)
    assert friendly_minion.zone == Zone.GRAVEYARD
    assert enemy_minion.zone == Zone.GRAVEYARD
    assert (friendly_ysera.health, enemy_ysera.health) == (12, 12)
    assert (friendly_ysera.damage, enemy_ysera.damage) == (0, 0)
    assert awakens.zone == Zone.GRAVEYARD


def test_laughing_sister_has_spell_and_hero_power_immunity_and_its_printed_stats():
    _, owner, _ = ready_game()
    sister = owner.summon("DREAM_01")

    assert (sister.atk, sister.max_health, sister.health) == (3, 5, 5)
    assert sister.cant_be_targeted_by_abilities
    assert sister.cant_be_targeted_by_hero_powers

    dream = owner.give("DREAM_04")
    assert sister not in dream.play_targets
    assert sister not in owner.hero.power.play_targets
    with pytest.raises(InvalidAction):
        dream.play(target=sister)
    with pytest.raises(InvalidAction):
        owner.hero.power.use(target=sister)
    assert dream.zone == Zone.HAND
    assert sister.zone == Zone.PLAY


def test_emerald_drake_has_its_printed_stats_and_dragon_race():
    _, owner, _ = ready_game()
    drake = owner.summon("DREAM_03")

    assert (drake.atk, drake.max_health, drake.health) == (7, 6, 6)
    assert Race.DRAGON in drake.races


def test_dream_returns_a_friendly_or_enemy_minion_to_its_owner_hand():
    _, owner, opponent = ready_game()
    friendly_minion = owner.summon("CS2_231")
    enemy_minion = opponent.summon("CS2_231")

    owner.give("DREAM_04").play(target=friendly_minion)
    assert friendly_minion.zone == Zone.HAND
    assert friendly_minion in owner.hand

    owner.give("DREAM_04").play(target=enemy_minion)
    assert enemy_minion.zone == Zone.HAND
    assert enemy_minion in opponent.hand


def test_dream_returns_a_stolen_minion_to_its_current_controller_hand():
    _, original_owner, current_controller = ready_game()
    minion = original_owner.summon("CS2_231")
    current_controller.steal(minion)
    assert minion.controller is current_controller

    original_owner.give("DREAM_04").play(target=minion)

    assert minion.zone == Zone.HAND
    assert minion in current_controller.hand
    assert minion not in original_owner.hand


@pytest.mark.parametrize("target_side", ("friendly", "enemy"))
def test_nightmare_gives_either_side_minions_plus_five_plus_five(target_side):
    _, owner, opponent = ready_game()
    controller = owner if target_side == "friendly" else opponent
    target = controller.summon("CS2_231")
    old_stats = (target.atk, target.max_health, target.health)

    nightmare = owner.give("DREAM_05")
    nightmare.play(target=target)

    assert (target.atk, target.max_health, target.health) == tuple(
        value + 5 for value in old_stats
    )
    assert nightmare.zone == Zone.GRAVEYARD


def test_nightmare_destroys_its_target_at_the_start_of_owners_next_turn():
    game, owner, opponent = ready_game()
    target = opponent.summon("CS2_231")

    owner.give("DREAM_05").play(target=target)
    assert target.zone == Zone.PLAY

    game.end_turn()
    assert game.current_player is opponent
    assert target.zone == Zone.PLAY

    game.end_turn()
    assert game.current_player is owner
    assert target.zone == Zone.GRAVEYARD


def test_nightmare_adds_health_without_healing_existing_damage():
    _, owner, opponent = ready_game()
    target = opponent.summon("CS2_200")
    for _ in range(3):
        owner.give("CS2_008").play(target=target)
    assert (target.health, target.max_health) == (4, 7)

    owner.give("DREAM_05").play(target=target)

    assert (target.atk, target.health, target.max_health) == (11, 9, 12)
    assert target.damage == 3


def test_nightmare_rejects_heroes_as_targets_without_consuming_the_spell():
    _, owner, _ = ready_game()
    nightmare = owner.give("DREAM_05")
    mana_before = owner.mana

    with pytest.raises(InvalidAction):
        nightmare.play(target=owner.hero)

    assert nightmare.zone == Zone.HAND
    assert owner.mana == mana_before
