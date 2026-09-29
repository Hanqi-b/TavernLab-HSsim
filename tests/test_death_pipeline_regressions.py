"""Regression cases for simultaneous deaths and Death event matching."""

import pytest
from hearthstone.enums import CardClass, PlayState, Zone

from fireplace.actions import Bounce, Death, Deaths
from fireplace.dsl.selector import FRIENDLY, MINION
from fireplace.exceptions import GameOver
from utils import WISP, prepare_empty_game


def empty_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    game.player1.discard_hand()
    return game, game.player1


def test_same_batch_lethal_minion_cannot_be_saved_by_deathrattle_buff():
    _, player = empty_game()
    spawn = player.summon("OG_256")
    yeti = player.summon("CS2_182")
    sheep = player.summon("GVG_076")
    yeti.set_current_health(2)

    sheep.destroy()

    assert sheep.zone == Zone.GRAVEYARD
    assert spawn.zone == Zone.GRAVEYARD
    assert yeti.zone == Zone.GRAVEYARD
    assert yeti not in player.field


def test_death_event_matches_friendly_minion_after_zone_move():
    _, player = empty_game()
    listener = player.summon("GIL_819")
    victim = player.summon(WISP)
    hand_before = len(player.hand)

    victim.destroy()

    assert listener.zone == Zone.PLAY
    assert victim.zone == Zone.GRAVEYARD
    assert len(player.hand) == hand_before + 1


def test_death_event_summons_token_for_friendly_minion():
    _, player = empty_game()
    listener = player.summon("ICC_900")
    victim = player.summon(WISP)

    victim.destroy()

    assert listener.zone == Zone.PLAY
    assert victim.zone == Zone.GRAVEYARD
    assert [card.id for card in player.field].count("ICC_900t") == 1


def test_zone_independent_death_listener_still_fires_once():
    _, player = empty_game()
    player.summon("EX1_595")
    known = player.give(WISP)
    known.shuffle_into_deck()
    victim = player.summon(WISP)

    victim.destroy()

    assert victim.zone == Zone.GRAVEYARD
    assert known.zone == Zone.HAND
    assert player.hand.count(known) == 1


def test_same_batch_dead_ally_is_never_bounced_before_its_death(monkeypatch):
    game, player = empty_game()
    ambusher = player.summon("FP1_026")
    ally = player.summon(WISP)
    ambusher.set_current_health(1)
    ally.set_current_health(1)

    bounced = []
    original = game.manager.targeted_action

    def record_bounce(action, source, target, *args):
        if isinstance(action, Bounce):
            bounced.append(target)
        return original(action, source, target, *args)

    monkeypatch.setattr(game.manager, "targeted_action", record_bounce)
    player.give("EX1_400").play()

    assert ambusher.zone == Zone.GRAVEYARD
    assert ally.zone == Zone.GRAVEYARD
    assert ally not in bounced


def test_nested_death_processing_does_not_process_pending_corpse_twice(monkeypatch):
    game, player = empty_game()
    first = player.summon(WISP)
    second = player.summon(WISP)
    player.hero._events.append(Death(FRIENDLY + MINION).on(Deaths()))

    processed = []
    original = game.manager.game_action

    def record_death(action, source, *args):
        if isinstance(action, Death):
            processed.extend(args)
        return original(action, source, *args)

    monkeypatch.setattr(game.manager, "game_action", record_death)
    player.give("EX1_400").play()

    assert first.zone == second.zone == Zone.GRAVEYARD
    assert processed.count(first) == 1
    assert processed.count(second) == 1


def test_deathrattle_summons_after_all_same_batch_board_slots_are_freed():
    game, player = empty_game()
    creeper = player.summon("FP1_002")
    creeper.set_current_health(1)
    wisps = [player.summon(WISP) for _ in range(6)]

    player.give("EX1_400").play()

    assert creeper.zone == Zone.GRAVEYARD
    assert all(wisp.zone == Zone.GRAVEYARD for wisp in wisps)
    assert [card.id for card in player.field].count("FP1_002t") == 2


def test_dead_knife_juggler_does_not_observe_same_batch_deathrattle_summon():
    game, player = empty_game()
    creeper = player.summon("FP1_002")
    juggler = player.summon("NEW1_019")
    creeper.set_current_health(1)
    juggler.set_current_health(1)
    enemy_health = game.player2.hero.health

    player.give("EX1_400").play()

    assert creeper.zone == juggler.zone == Zone.GRAVEYARD
    assert [card.id for card in player.field].count("FP1_002t") == 2
    assert game.player2.hero.health == enemy_health


def test_both_heroes_dying_in_one_damage_batch_is_a_tie():
    game, player = empty_game()
    player.hero.set_current_health(1)
    game.player2.hero.set_current_health(1)

    with pytest.raises(GameOver):
        player.give("CS2_062").play()

    assert player.hero.zone == Zone.GRAVEYARD
    assert game.player2.hero.zone == Zone.GRAVEYARD
    assert player.playstate == PlayState.TIED
    assert game.player2.playstate == PlayState.TIED


def test_two_same_batch_reborn_minions_each_return_once():
    _, player = empty_game()
    originals = [player.summon("ULD_208") for _ in range(2)]
    for card in originals:
        card.set_current_health(1)

    player.give("EX1_400").play()

    assert all(card.zone == Zone.GRAVEYARD for card in originals)
    returned = [card for card in player.field if card.id == "ULD_208"]
    assert len(returned) == 2
    assert all(card.health == 1 and not card.reborn for card in returned)
