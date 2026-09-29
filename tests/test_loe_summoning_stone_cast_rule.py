"""Summoning Stone follows the confirmed player hand-cast rule."""

from hearthstone.enums import CardClass, Zone

from utils import MOONFIRE, WISP, prepare_empty_game


def test_summoning_stone_ignores_djinni_effect_cast_copy():
    game = prepare_empty_game(CardClass.PRIEST, CardClass.PRIEST)
    player = game.player1
    stone = player.summon("LOE_086")
    djinni = player.summon("LOE_053")
    target = player.summon(WISP)
    initial_djinni_attack = djinni.atk
    assert initial_djinni_attack != djinni.max_health

    spell = player.give("CS1_129")  # Inner Fire: 1-cost, targets a friendly minion.
    assert spell.cost == 1
    spell.play(target=target)

    generated = [m for m in player.field if m not in (stone, djinni, target)]
    assert spell.zone == Zone.GRAVEYARD
    assert (djinni.atk, djinni.max_health) == (djinni.max_health, djinni.max_health)
    assert len(generated) == 1  # Hand cast triggers; Djinni's copy does not.
    assert generated[0].data.cost == spell.data.cost
    assert generated[0].zone == Zone.PLAY


def test_summoning_stone_only_responds_to_its_players_spell():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    stone = game.player1.summon("LOE_086")
    game.end_turn()

    game.player2.give(MOONFIRE).play(target=game.player1.hero)
    assert stone.zone == Zone.PLAY
    assert game.player1.field == [stone]

    game.end_turn()
    spell = game.player1.give("CS2_029")  # Fireball: 4-cost.
    spell.play(target=game.player2.hero)
    generated = [m for m in game.player1.field if m is not stone]
    assert spell.zone == Zone.GRAVEYARD
    assert len(generated) == 1
    assert generated[0].data.cost == spell.data.cost == 4
    assert generated[0].zone == Zone.PLAY
