"""Per-card regressions for five Gadgetzan cards formerly graded RED."""

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_sergeant_sally_deathrattle_only_hits_enemy_minions_for_current_attack():
    _, owner, opponent = ready_game(CardClass.PALADIN)
    friendly = owner.summon("CS2_231")
    enemy_small = opponent.summon("CS2_231")
    enemy_large = opponent.summon("CS2_182")
    sally = owner.give("CFM_341")
    sally.play()
    owner.give("CS2_087").play(target=sally)
    assert sally.atk == 4

    sally.destroy()

    assert sally.zone == Zone.GRAVEYARD
    assert friendly.zone == Zone.PLAY and friendly.health == 1
    assert enemy_small.zone == Zone.GRAVEYARD
    assert enemy_large.zone == Zone.PLAY and enemy_large.health == enemy_large.max_health - 4


def test_grimscale_chum_buffs_exactly_one_held_murloc():
    game, owner, _ = ready_game(CardClass.PALADIN)
    game.random.seed(650)
    murlocs = [owner.give("CS2_168"), owner.give("EX1_506")]
    ordinary = owner.give("CS2_231")
    before = [(card.atk, card.max_health) for card in murlocs]
    ordinary_before = (ordinary.atk, ordinary.max_health)
    chum = owner.give("CFM_650")
    chum.play()

    assert chum.zone == Zone.PLAY
    assert sum((card.atk, card.max_health) == (atk + 1, health + 1)
               for card, (atk, health) in zip(murlocs, before)) == 1
    assert sum((card.atk, card.max_health) == initial
               for card, initial in zip(murlocs, before)) == 1
    assert (ordinary.atk, ordinary.max_health) == ordinary_before


def test_grimscale_chum_with_no_held_murloc_changes_nothing():
    _, owner, _ = ready_game(CardClass.PALADIN)
    ordinary = owner.give("CS2_231")
    before = (ordinary.atk, ordinary.max_health)
    owner.give("CFM_650").play()
    assert (ordinary.atk, ordinary.max_health) == before


def test_cryomancer_only_gains_stats_if_enemy_character_is_frozen():
    _, owner, _ = ready_game()
    ordinary = owner.give("CFM_671")
    ordinary.play()
    assert (ordinary.atk, ordinary.max_health) == (5, 5)

    _, owner, opponent = ready_game()
    enemy = opponent.summon("CS2_200")
    owner.give("CS2_024").play(target=enemy)
    assert enemy.zone == Zone.PLAY and enemy.frozen
    powered = owner.give("CFM_671")
    powered.play()
    assert (powered.atk, powered.max_health) == (7, 7)


def test_gadgetzan_ferryman_bounces_only_when_combo_is_active():
    _, owner, _ = ready_game(CardClass.ROGUE)
    friendly = owner.summon("CS2_231")
    ferryman = owner.give("CFM_693")
    ferryman.play()
    assert ferryman.zone == Zone.PLAY
    assert friendly.zone == Zone.PLAY and friendly not in owner.hand

    _, owner, _ = ready_game(CardClass.ROGUE)
    friendly = owner.summon("CS2_231")
    owner.give("GAME_005").play()
    ferryman = owner.give("CFM_693")
    assert friendly in ferryman.targets
    ferryman.play(target=friendly)
    assert ferryman.zone == Zone.PLAY
    assert friendly.zone == Zone.HAND and friendly in owner.hand


def test_mayor_noggenfogger_random_target_aura_and_hero_attack():
    redirected = False
    for seed in range(760, 776):
        game, owner, opponent = ready_game()
        game.random.seed(seed)
        weapon = owner.give("CS2_091")
        weapon.play()
        mayor = owner.give("CFM_670")
        mayor.play()
        assert owner.all_targets_random and opponent.all_targets_random
        enemy = opponent.summon("CS2_200")
        before_hero, before_minion = opponent.hero.health, enemy.health

        owner.hero.attack(opponent.hero)

        assert weapon.zone == Zone.PLAY and weapon.durability == 3
        assert opponent.hero.health < before_hero or enemy.health < before_minion
        redirected |= opponent.hero.health == before_hero and enemy.health < before_minion
        mayor.destroy()
        assert not owner.all_targets_random and not opponent.all_targets_random
    assert redirected
