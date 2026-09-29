"""Focused behavior checks for three OG Battlecry regressions."""

import pytest
from hearthstone.enums import CardClass, Zone
from fireplace.exceptions import InvalidAction

from utils import prepare_empty_game


def test_ravaging_ghoul_hits_all_other_minions_once():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    ally = game.player1.summon("CS2_182")
    enemy1 = game.player2.summon("CS2_182")
    enemy2 = game.player2.summon("CS2_182")
    ghoul = game.player1.give("OG_149")
    ghoul.play()

    assert ghoul.zone == Zone.PLAY and ghoul.damage == 0
    assert all(m.zone == Zone.PLAY and m.damage == 1 for m in (ally, enemy1, enemy2))
    assert game.player1.hero.health == game.player2.hero.health == 30


def test_klaxxi_amber_weaver_gains_exactly_five_health_at_threshold():
    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    game.player1.give("OG_281").play()
    game.player1.give("OG_281").play()
    assert game.player1.cthun.atk == 10
    weaver = game.player1.give("OG_188")
    weaver.play()
    assert weaver.zone == Zone.PLAY
    assert (weaver.atk, weaver.health, weaver.max_health) == (4, 10, 10)


def test_klaxxi_amber_weaver_gets_no_bonus_below_threshold():
    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    game.player1.give("OG_281").play()
    assert game.player1.cthun.atk == 8
    weaver = game.player1.give("OG_188")
    weaver.play()
    assert (weaver.atk, weaver.health, weaver.max_health) == (4, 5, 5)


def test_shadowcaster_adds_one_cost_one_one_copy_without_changing_source():
    game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
    source = game.player1.summon("CS2_182")
    source.set_current_health(2)
    enemy = game.player2.summon("CS2_182")
    caster = game.player1.give("OG_291")
    assert source in caster.targets and enemy not in caster.targets
    before = (source.atk, source.health, source.max_health, source.zone)

    caster.play(target=source)

    copies = [card for card in game.player1.hand if card.id == source.id]
    assert len(copies) == 1
    copy = copies[0]
    assert copy is not source and copy.zone == Zone.HAND
    assert (copy.atk, copy.health, copy.max_health, copy.cost) == (1, 1, 1, 1)
    assert (source.atk, source.health, source.max_health, source.zone) == before
    assert enemy.zone == Zone.PLAY and caster.zone == Zone.PLAY


def test_shadowcaster_rejects_enemy_target_before_playing():
    game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
    friendly = game.player1.summon("CS2_182")
    enemy = game.player2.summon("CS2_182")
    caster = game.player1.give("OG_291")
    mana_before = game.player1.mana
    assert caster.requires_target() and friendly in caster.targets

    with pytest.raises(InvalidAction):
        caster.play(target=enemy)

    assert caster.zone == Zone.HAND and caster in game.player1.hand
    assert game.player1.mana == mana_before
    assert enemy.zone == Zone.PLAY
