"""Targeted regressions for the Raza, Rat Pack, and Piranha Launcher fixes."""

from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_raza_only_sets_hero_power_cost_to_zero_for_a_unique_deck():
    _, owner, _ = ready_game(CardClass.PRIEST)
    owner.give("CS2_231").shuffle_into_deck()
    owner.give("CS2_182").shuffle_into_deck()

    raza = owner.give("CFM_020")
    raza.play()

    assert raza.zone == Zone.PLAY
    assert owner.hero.power.cost == 0


def test_raza_does_not_set_hero_power_cost_to_zero_for_duplicate_deck_cards():
    _, owner, _ = ready_game(CardClass.PRIEST)
    owner.give(WISP).shuffle_into_deck()
    owner.give(WISP).shuffle_into_deck()
    before = owner.hero.power.cost

    raza = owner.give("CFM_020")
    raza.play()

    assert raza.zone == Zone.PLAY
    assert owner.hero.power.cost == before


def test_rat_pack_summons_one_one_rat_for_each_base_attack():
    _, owner, _ = ready_game(CardClass.HUNTER)
    rat_pack = owner.give("CFM_316")
    rat_pack.play()

    rat_pack.destroy()

    rats = [minion for minion in owner.field if minion.id == "CFM_316t"]
    assert rat_pack.zone == Zone.GRAVEYARD
    assert len(rats) == 2
    assert all((rat.atk, rat.health) == (1, 1) for rat in rats)


def test_rat_pack_uses_its_current_attack_for_deathrattle_count():
    _, owner, _ = ready_game(CardClass.HUNTER)
    rat_pack = owner.give("CFM_316")
    rat_pack.play()
    owner.give("CS2_087").play(target=rat_pack)
    assert rat_pack.atk == 5

    rat_pack.destroy()

    rats = [minion for minion in owner.field if minion.id == "CFM_316t"]
    assert rat_pack.zone == Zone.GRAVEYARD
    assert len(rats) == 5
    assert all((rat.atk, rat.health) == (1, 1) for rat in rats)


def test_piranha_launcher_summons_after_a_hero_attack_on_a_minion():
    _, owner, opponent = ready_game(CardClass.HUNTER)
    target = opponent.summon(WISP)
    launcher = owner.give("CFM_337")
    launcher.play()

    owner.hero.attack(target)

    piranhas = [minion for minion in owner.field if minion.id == "CFM_337t"]
    assert launcher.zone == Zone.PLAY
    assert target.zone == Zone.GRAVEYARD
    assert len(piranhas) == 1
    assert (piranhas[0].atk, piranhas[0].health) == (1, 1)


def test_piranha_launcher_summons_after_a_hero_attack_on_the_enemy_hero():
    _, owner, opponent = ready_game(CardClass.HUNTER)
    launcher = owner.give("CFM_337")
    launcher.play()
    before_health = opponent.hero.health

    owner.hero.attack(opponent.hero)

    piranhas = [minion for minion in owner.field if minion.id == "CFM_337t"]
    assert launcher.zone == Zone.PLAY
    assert opponent.hero.health == before_health - owner.hero.atk
    assert len(piranhas) == 1
    assert (piranhas[0].atk, piranhas[0].health) == (1, 1)
