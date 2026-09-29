"""Silence must remove native and granted Spell Damage from minions."""

import pytest
from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.PRIEST, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    player = game.player1
    player.discard_hand()
    player.max_mana = 10
    player.used_mana = 0
    return game, player, game.player2


@pytest.mark.parametrize(
    "card_id,base_spellpower", [("CS2_142", 1), ("EX1_563", 5)]
)
def test_silence_removes_native_spell_damage_and_damage_bonus(card_id, base_spellpower):
    _, player, opponent = ready_game()
    minion = player.summon(card_id)
    assert minion.zone == Zone.PLAY
    assert minion.spellpower == player.spellpower == base_spellpower

    first_health = opponent.hero.health
    player.give("CS2_008").play(target=opponent.hero)
    assert opponent.hero.health == first_health - (1 + base_spellpower)

    player.give("EX1_332").play(target=minion)
    assert minion.zone == Zone.PLAY and minion.silenced
    assert minion.spellpower == player.spellpower == 0

    second_health = opponent.hero.health
    player.give("CS2_008").play(target=opponent.hero)
    assert opponent.hero.health == second_health - 1


def test_silence_removes_granted_spell_damage_and_stats():
    _, player, opponent = ready_game()
    minion = player.summon(WISP)
    player.give("GVG_010").play(target=minion)
    assert (minion.atk, minion.health, minion.spellpower) == (3, 5, 1)
    assert player.spellpower == 1

    player.give("EX1_332").play(target=minion)
    assert minion.zone == Zone.PLAY and minion.silenced
    assert (minion.atk, minion.health, minion.spellpower) == (1, 1, 0)
    assert player.spellpower == 0

    prior = opponent.hero.health
    player.give("CS2_008").play(target=opponent.hero)
    assert opponent.hero.health == prior - 1


def test_copy_of_silenced_spell_damage_minion_stays_silenced():
    _, player, _ = ready_game()
    minion = player.summon("CS2_142")
    player.give("EX1_332").play(target=minion)
    assert minion.spellpower == 0

    faceless = player.give("EX1_564")
    faceless.play(target=minion)
    assert faceless.morphed.silenced
    assert faceless.morphed.spellpower == 0
    assert player.spellpower == 0
