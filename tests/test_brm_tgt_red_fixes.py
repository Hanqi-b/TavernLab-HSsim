"""Focused behavior checks for the BRM and TGT cards formerly marked RED."""

from hearthstone.enums import CardClass, Zone

from utils import MOONFIRE, WHELP, WISP, prepare_empty_game


def test_flamewaker_splits_exactly_two_random_pings_among_enemies():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    waker = game.player1.summon("BRM_002")
    ally = game.player1.summon(WISP)
    enemy = game.player2.summon("BRM_014")
    initial_total = game.player2.hero.health + enemy.health

    game.player1.give(MOONFIRE).play(target=game.player2.hero)

    assert waker.zone == enemy.zone == ally.zone == Zone.PLAY
    assert ally.health == 1
    assert initial_total - game.player2.hero.health - enemy.health == 3
    assert game.player2.hero.health <= 29


def test_flamewaker_hits_the_only_enemy_twice_after_own_spell():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    game.player1.summon("BRM_002")
    game.player1.give(MOONFIRE).play(target=game.player2.hero)
    assert game.player2.hero.health == 27


def test_rend_readiness_matches_friendly_legendary_target():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    friendly_legend = game.player1.summon("EX1_557")
    ordinary_enemy = game.player2.summon(WISP)
    rend = game.player1.give("BRM_029")
    assert not rend.powered_up
    assert not rend.requires_target()

    game.player1.give(WHELP)
    assert rend.powered_up
    assert rend.requires_target()
    assert rend.targets == [friendly_legend]
    rend.play(target=friendly_legend)
    assert friendly_legend.zone == Zone.GRAVEYARD
    assert ordinary_enemy.zone == rend.zone == Zone.PLAY


def test_rend_can_destroy_enemy_legendary_but_not_ordinary_minion():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    enemy_legend = game.player2.summon("EX1_557")
    ordinary_enemy = game.player2.summon(WISP)
    game.player1.give(WHELP)
    rend = game.player1.give("BRM_029")
    assert rend.powered_up
    assert rend.targets == [enemy_legend]
    rend.play(target=enemy_legend)
    assert enemy_legend.zone == Zone.GRAVEYARD
    assert ordinary_enemy.zone == Zone.PLAY


def test_coldarra_drake_allows_repeated_hero_power_then_reverts_on_death():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    drake = game.player1.give("AT_008")
    drake.play()
    power = game.player1.hero.power
    assert power.additional_activations == -1
    for expected_health in (29, 28, 27):
        game.player1.used_mana = 0
        assert power.is_usable()
        power.use(game.player2.hero)
        assert game.player2.hero.health == expected_health
    assert power.is_usable()

    drake.destroy()
    assert power.additional_activations == 0
    assert not power.is_usable()
    game.end_turn()
    game.end_turn()
    game.player1.used_mana = 0
    assert power.is_usable()
    power.use(game.player2.hero)
    assert not power.is_usable()


def test_thunder_bluff_valiant_gives_only_friendly_totems_two_attack():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    totem1 = game.player1.summon("CS2_050")
    totem2 = game.player1.summon("CS2_051")
    ordinary = game.player1.summon(WISP)
    enemy_totem = game.player2.summon("CS2_050")
    valiant = game.player1.give("AT_049")
    valiant.play()
    before = {m: (m.atk, m.health) for m in (totem1, totem2, ordinary, enemy_totem, valiant)}

    game.player1.hero.power.use()

    for totem in (totem1, totem2):
        assert (totem.atk, totem.health) == (before[totem][0] + 2, before[totem][1])
    for other in (ordinary, enemy_totem, valiant):
        assert (other.atk, other.health) == before[other]


def test_sparring_partner_has_taunt_and_grants_taunt_to_target():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    friendly = game.player1.summon(WISP)
    enemy = game.player2.summon(WISP)
    partner = game.player1.give("AT_069")
    assert partner.taunt
    assert friendly in partner.targets and enemy in partner.targets
    partner.play(target=enemy)
    assert partner.zone == Zone.PLAY and partner.taunt
    assert enemy.taunt and enemy.zone == Zone.PLAY
    assert not friendly.taunt


def test_sparring_partner_keeps_native_taunt_without_optional_target():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    partner = game.player1.give("AT_069")
    assert not partner.requires_target()
    partner.play()
    assert partner.zone == Zone.PLAY and partner.taunt


def test_muklas_champion_buffs_other_friendly_minions_only():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    ally1 = game.player1.summon(WISP)
    ally2 = game.player1.summon("CS2_182")
    enemy = game.player2.summon(WISP)
    champion = game.player1.give("AT_090")
    champion.play()
    before = {m: (m.atk, m.health) for m in (ally1, ally2, enemy, champion)}

    game.player1.hero.power.use()

    for ally in (ally1, ally2):
        assert (ally.atk, ally.health) == (before[ally][0] + 1, before[ally][1] + 1)
    for other in (enemy, champion):
        assert (other.atk, other.health) == before[other]


def test_argent_watchman_attack_permission_lasts_only_this_turn():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    watchman = game.player1.give("AT_109")
    watchman.play()
    game.player1.hero.power.use()
    assert not watchman.cant_attack
    assert not watchman.can_attack()  # Inspire does not bypass summoning sickness.
    game.end_turn()
    game.end_turn()
    assert watchman.zone == Zone.PLAY
    assert watchman.cant_attack and not watchman.can_attack()

    game.player1.hero.power.use()
    assert not watchman.cant_attack and watchman.can_attack()
    assert any(buff.id == "AT_109e" for buff in watchman.buffs)
    watchman.attack(game.player2.hero)
    assert game.player2.hero.health == 28
    game.end_turn()
    game.end_turn()
    assert watchman.cant_attack and not watchman.can_attack()
    assert not any(buff.id == "AT_109e" for buff in watchman.buffs)
