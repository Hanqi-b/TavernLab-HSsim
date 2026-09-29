"""Regression tests for attack based GVG/TGT/Kobolds card effects."""

from hearthstone.enums import CardClass

from utils import prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    if game.current_player is not game.player1:
        game.end_turn()
    return game, game.player1, game.player2


def test_gvg_054_ogre_warmaul_equips_four_attack_two_durability():
    game, player, _ = ready_game()

    weapon = player.give("GVG_054")
    weapon.play()

    assert player.weapon is weapon
    assert weapon.atk == 4
    assert weapon.durability == 2


def test_gvg_054_ogre_warmaul_uses_the_hero_as_attacker_for_redirects():
    game, player, opponent = ready_game()
    weapon = player.give("GVG_054")
    weapon.play()
    enemies = [opponent.summon("CS2_200") for _ in range(3)]

    # Seed 1 makes the 50% check fail, so the selected defender is hit.
    game.random.seed(1)
    player.hero.attack(enemies[1])
    assert [enemy.health for enemy in enemies] == [7, 3, 7]

    # A fresh weapon and seed 0 exercise the redirect branch.  With this board
    # ordering the wrong enemy is the left neighbor of the selected defender.
    game, player, opponent = ready_game()
    weapon = player.give("GVG_054")
    weapon.play()
    enemies = [opponent.summon("CS2_200") for _ in range(3)]
    game.random.seed(0)
    player.hero.attack(enemies[1])

    assert [enemy.health for enemy in enemies] == [3, 7, 7]


def _attack_center_with_cleave(card_id):
    game, player, opponent = ready_game()
    attacker = player.summon(card_id)
    enemies = [opponent.summon("CS2_200") for _ in range(3)]
    attack = attacker.atk

    # The summoned attacker needs a turn to become eligible to attack.  The
    # enemy minions have enough health to survive the cleave for every card.
    game.end_turn()
    game.end_turn()
    attacker.attack(enemies[1])

    return attack, enemies


def test_gvg_113_foe_reaper_cleaves_the_actual_attack_defender():
    attack, enemies = _attack_center_with_cleave("GVG_113")

    assert [enemy.health for enemy in enemies] == [7 - attack, 7 - attack, 7 - attack]


def test_at_067_magnataur_alpha_cleaves_the_actual_attack_defender():
    attack, enemies = _attack_center_with_cleave("AT_067")

    assert [enemy.health for enemy in enemies] == [7 - attack, 7 - attack, 7 - attack]


def test_loot_078_cave_hydra_cleaves_the_actual_attack_defender():
    attack, enemies = _attack_center_with_cleave("LOOT_078")

    assert [enemy.health for enemy in enemies] == [7 - attack, 7 - attack, 7 - attack]
