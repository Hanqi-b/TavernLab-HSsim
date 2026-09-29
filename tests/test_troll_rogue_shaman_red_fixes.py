"""Targeted regressions for the collectible TROLL Rogue and Shaman red cards."""

from hearthstone.enums import CardClass, Zone

from utils import MOONFIRE, WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
    return game, game.player1, game.player2


def test_bloodsail_howler_counts_only_other_pirates():
    _, owner, _ = ready_game(CardClass.ROGUE, CardClass.MAGE)
    pirate_a = owner.summon("CS2_146")
    pirate_b = owner.summon("CS2_146")
    plain = owner.summon(WISP)

    howler = owner.give("TRL_071").play()

    assert howler.zone == Zone.PLAY
    assert (howler.atk, howler.max_health) == (3, 3)
    assert pirate_a.zone == pirate_b.zone == plain.zone == Zone.PLAY


def test_bloodsail_howler_gets_no_self_buff_without_another_pirate():
    _, owner, _ = ready_game(CardClass.ROGUE, CardClass.MAGE)

    howler = owner.give("TRL_071").play()

    assert howler.zone == Zone.PLAY
    assert (howler.atk, howler.max_health) == (1, 1)
    assert howler.rush


def test_zentimo_recasts_targeted_spell_once_on_each_adjacent_minion():
    _, owner, opponent = ready_game(CardClass.SHAMAN, CardClass.MAGE)
    zentimo = owner.give("TRL_085").play()
    enemies = [opponent.summon("CS2_182") for _ in range(4)]

    spell = owner.give(MOONFIRE)
    spell.play(target=enemies[1])

    # The original cast hits the selected target once. Zentimo then creates
    # one independent cast on each neighbor, leaving the distant minion alone.
    assert [minion.health for minion in enemies] == [4, 4, 4, 5]
    assert spell.zone == Zone.GRAVEYARD
    assert zentimo.zone == Zone.PLAY


def test_zentimo_does_not_randomly_recast_when_the_target_has_no_neighbor():
    _, owner, opponent = ready_game(CardClass.SHAMAN, CardClass.MAGE)
    zentimo = owner.give("TRL_085").play()
    target = opponent.summon("CS2_182")

    spell = owner.give(MOONFIRE)
    spell.play(target=target)

    assert target.health == 4
    assert spell.zone == Zone.GRAVEYARD
    assert zentimo.zone == Zone.PLAY


def test_zentimo_keeps_neighbor_targets_when_original_spell_kills_middle():
    _, owner, opponent = ready_game(CardClass.SHAMAN, CardClass.MAGE)
    owner.give("TRL_085").play()
    left, middle, right = [opponent.summon("CS2_182") for _ in range(3)]
    middle.max_health = 1

    owner.give(MOONFIRE).play(target=middle)

    assert middle.zone == Zone.GRAVEYARD
    assert left.zone == right.zone == Zone.PLAY
    assert (left.health, right.health) == (4, 4)


def test_spirit_of_the_shark_doubles_own_minion_battlecry_and_combo_only():
    game, owner, opponent = ready_game(CardClass.ROGUE, CardClass.MAGE)
    shark = owner.give("TRL_092").play()
    assert shark.stealthed
    friendly_mech = owner.summon("BOT_031")

    owner.give("BOT_079").play(target=friendly_mech)
    assert (friendly_mech.atk, friendly_mech.max_health) == (2, 4)

    enemy = opponent.summon("BOT_031")
    game.end_turn()
    opponent.give("BOT_079").play(target=enemy)
    assert (enemy.atk, enemy.max_health) == (1, 3)

    game.end_turn()
    combo_target = opponent.summon("CS2_182")
    owner.give(WISP).play()
    owner.give("EX1_134").play(target=combo_target)
    assert combo_target.health == 1

    game.end_turn()
    game.end_turn()
    assert not shark.stealthed
