from hearthstone.enums import Zone

from utils import MOONFIRE, MURLOC, WISP, prepare_empty_game


def test_secretkeeper_buffs_for_secrets_played_by_either_player():
    game = prepare_empty_game()
    player = game.current_player
    opponent = player.opponent

    secretkeeper = player.give("EX1_080")
    secretkeeper.play()
    assert secretkeeper.atk == 1
    base_health = secretkeeper.max_health

    player.give("EX1_295").play()
    assert secretkeeper.atk == 2
    assert secretkeeper.max_health == base_health + 1

    game.end_turn()
    opponent.give("EX1_295").play()
    assert secretkeeper.atk == 3
    assert secretkeeper.max_health == base_health + 2


def test_tidecaller_buffs_only_for_other_friendly_murloc_summons():
    game = prepare_empty_game()
    player = game.current_player
    opponent = player.opponent

    tidecaller = player.give("EX1_509")
    tidecaller.play()
    assert tidecaller.atk == 1

    game.end_turn()
    opponent.give(MURLOC).play()
    assert tidecaller.atk == 1

    game.end_turn()
    player.give(MURLOC).play()
    assert tidecaller.atk == 2


def test_ancient_mage_grants_adjacent_spell_damage_and_silence_removes_it():
    game = prepare_empty_game()
    player = game.current_player
    opponent = player.opponent

    left = player.summon(WISP)
    right = player.summon(WISP)
    nonadjacent = player.summon(WISP)
    mage = player.give("EX1_584")
    mage.play(index=1)

    assert mage.zone == Zone.PLAY
    assert (left.spellpower, right.spellpower, nonadjacent.spellpower) == (1, 1, 0)

    player.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == 27

    player.give("EX1_332").play(target=left)
    assert (left.spellpower, right.spellpower, nonadjacent.spellpower) == (0, 1, 0)

    player.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == 25
