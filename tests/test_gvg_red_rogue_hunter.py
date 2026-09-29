from hearthstone.enums import CardClass

from utils import *


def test_tinkers_sharpsword_oil_noncombo_only_buffs_weapon():
    game = prepare_empty_game()
    hero_base_attack = game.player1.hero.atk
    weapon = game.player1.summon(LIGHTS_JUSTICE)

    assert not game.player1.combo
    oil = game.player1.give("GVG_022")
    oil.play()

    assert weapon.atk == 4
    assert game.player1.hero.atk == hero_base_attack + weapon.atk
    assert not game.player1.field


def test_tinkers_sharpsword_oil_combo_buffs_exactly_one_minion():
    game = prepare_empty_game()
    hero_base_attack = game.player1.hero.atk
    weapon = game.player1.summon(LIGHTS_JUSTICE)
    minion_one = game.player1.summon(WISP)
    minion_two = game.player1.summon(WISP)
    game.player1.give(THE_COIN).play()

    # Make the random selector deterministic so the test checks that exactly
    # one of the two friendly minions receives the combo buff.
    game.random.sample = lambda population, count: list(population)[:count]
    oil = game.player1.give("GVG_022")
    oil.play()

    assert len(game.player1.field) == 2
    assert minion_one.atk == 4
    assert minion_two.atk == 1
    assert weapon.atk == 4
    assert game.player1.hero.atk == hero_base_attack + weapon.atk
    assert not any(buff.id == "GVG_022b" for buff in game.player1.hero.buffs)


def test_tinkers_sharpsword_oil_combo_without_minions_still_buffs_weapon():
    game = prepare_empty_game()
    weapon = game.player1.summon(LIGHTS_JUSTICE)
    game.player1.give(THE_COIN).play()

    oil = game.player1.give("GVG_022")
    oil.play()

    assert weapon.atk == 4
    assert not game.player1.field
    assert not any(buff.id == "GVG_022b" for buff in game.player1.hero.buffs)


def test_king_of_beasts_counts_other_friendly_beasts_only():
    for beast_count in (0, 1, 2):
        game = prepare_empty_game()
        other_beasts = [game.player1.summon("GVG_046") for _ in range(beast_count)]
        non_beast = game.player1.summon(WISP)
        king = game.player1.give("GVG_046")
        base_attack = king.atk
        king.play()

        assert king.atk == base_attack + beast_count
        assert non_beast.atk == 1
        assert all(beast.atk == 2 for beast in other_beasts)


def test_metaltooth_leaper_buffs_all_other_friendly_mechs():
    game = prepare_empty_game()
    mech_one = game.player1.summon(MECH)
    mech_two = game.player1.summon(MECH)
    non_mech = game.player1.summon(WISP)
    enemy_mech = game.player2.summon(MECH)
    leaper = game.player1.give("GVG_048")
    leaper.play()

    assert mech_one.atk == 3
    assert mech_two.atk == 3
    assert non_mech.atk == 1
    assert leaper.atk == 3
    assert enemy_mech.atk == 1


def test_steamwheedle_sniper_enables_and_reverts_steady_shot_minion_targeting():
    game = prepare_empty_game(
        class1=CardClass.HUNTER,
        class2=CardClass.HUNTER,
    )
    target = game.player2.summon("GVG_046")
    hero_power = game.player1.hero.power

    assert not hero_power.steady_shot_can_target
    assert target not in hero_power.play_targets

    sniper = game.player1.give("GVG_087")
    sniper.play()

    assert hero_power.steady_shot_can_target
    assert target in hero_power.play_targets
    hero_power.use(target=target)
    assert target.damage == 2
    assert target in game.player2.field

    sniper.destroy()

    assert not hero_power.steady_shot_can_target
    assert target not in hero_power.play_targets


def test_steamwheedle_sniper_silence_removes_targeting_aura():
    game = prepare_empty_game(
        class1=CardClass.HUNTER,
        class2=CardClass.HUNTER,
    )
    target = game.player2.summon("GVG_046")
    hero_power = game.player1.hero.power
    sniper = game.player1.give("GVG_087")
    sniper.play()

    assert target in hero_power.play_targets

    sniper.silence()

    assert not hero_power.steady_shot_can_target
    assert target not in hero_power.play_targets
