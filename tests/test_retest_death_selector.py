"""Card-specific live checks for Death selectors after the zone-state fix."""

from hearthstone.enums import CardClass, CardType, Zone

from utils import WISP, prepare_empty_game


def empty_game(class1=CardClass.MAGE, class2=CardClass.MAGE):
    game = prepare_empty_game(class1, class2)
    game.player1.discard_hand()
    game.player2.discard_hand()
    return game


def test_OG_302_friendly_death_buffs_cthun_in_each_zone_and_ignores_enemy_death():
    """Usher of Souls must buff C'Thun wherever it is, only for friendly deaths."""
    for zone in (Zone.HAND, Zone.DECK, Zone.PLAY):
        game = empty_game()
        player = game.player1
        player.summon("OG_302")
        cthun = player.give("OG_280")
        if zone == Zone.DECK:
            cthun.shuffle_into_deck()
        elif zone == Zone.PLAY:
            player.summon(cthun)
        assert cthun.zone == zone
        assert (cthun.atk, cthun.health) == (6, 6)

        friendly_victim = player.summon(WISP)
        friendly_victim.destroy()
        assert friendly_victim.zone == Zone.GRAVEYARD
        assert (cthun.atk, cthun.health) == (7, 7)

        enemy_victim = game.player2.summon(WISP)
        enemy_victim.destroy()
        assert enemy_victim.zone == Zone.GRAVEYARD
        assert (cthun.atk, cthun.health) == (7, 7)


def test_GIL_819_friendly_death_gives_shaman_spell_but_enemy_death_does_not():
    game = empty_game(CardClass.SHAMAN, CardClass.MAGE)
    player = game.player1
    cauldron = player.summon("GIL_819")
    victim = player.summon(WISP)

    victim.destroy()

    assert cauldron.zone == Zone.PLAY
    assert victim.zone == Zone.GRAVEYARD
    assert len(player.hand) == 1
    reward = player.hand[0]
    assert reward.type == CardType.SPELL
    assert reward.card_class == CardClass.SHAMAN

    enemy_victim = game.player2.summon(WISP)
    enemy_victim.destroy()
    assert enemy_victim.zone == Zone.GRAVEYARD
    assert player.hand == [reward]


def test_GIL_819_random_reward_stays_in_shaman_spell_pool():
    seen = set()
    for seed in range(24):
        game = empty_game(CardClass.SHAMAN, CardClass.MAGE)
        game.random.seed(seed)
        player = game.player1
        player.summon("GIL_819")
        player.summon(WISP).destroy()
        assert len(player.hand) == 1
        spell = player.hand[0]
        assert spell.type == CardType.SPELL
        assert spell.card_class == CardClass.SHAMAN
        seen.add(spell.id)
    assert len(seen) > 1


def test_ICC_900_summons_one_2_2_ghoul_for_another_friendly_death_only():
    game = empty_game()
    player = game.player1
    geist = player.summon("ICC_900")
    victim = player.summon(WISP)

    victim.destroy()

    ghouls = [card for card in player.field if card.id == "ICC_900t"]
    assert geist.zone == Zone.PLAY
    assert victim.zone == Zone.GRAVEYARD
    assert len(ghouls) == 1
    assert ghouls[0].controller is player
    assert (ghouls[0].atk, ghouls[0].health) == (2, 2)

    enemy_victim = game.player2.summon(WISP)
    enemy_victim.destroy()
    assert enemy_victim.zone == Zone.GRAVEYARD
    assert [card for card in player.field if card.id == "ICC_900t"] == ghouls


def test_ICC_900_does_not_summon_when_itself_dies():
    game = empty_game()
    player = game.player1
    geist = player.summon("ICC_900")

    geist.destroy()

    assert geist.zone == Zone.GRAVEYARD
    assert not [card for card in player.field if card.id == "ICC_900t"]


def test_BT_850_tracks_enemy_warder_deaths_then_clears_board_and_awakens():
    game = empty_game()
    player = game.player1
    opponent = game.player2
    player.max_mana = 10
    magtheridon = player.give("BT_850")
    magtheridon.play()

    warders = [card for card in opponent.field if card.id == "BT_850t"]
    friendly_control = player.summon(WISP)
    enemy_control = opponent.summon(WISP)
    assert magtheridon.dormant
    assert len(warders) == 3
    assert all(card.controller is opponent for card in warders)
    assert all((card.atk, card.health) == (1, 3) for card in warders)

    # A different enemy minion's death must not count as a Warder death.
    enemy_control.destroy()
    assert enemy_control.zone == Zone.GRAVEYARD
    assert magtheridon.dormant
    assert friendly_control.zone == Zone.PLAY

    warders[0].destroy()
    assert warders[0].zone == Zone.GRAVEYARD
    assert magtheridon.dormant
    assert friendly_control.zone == Zone.PLAY
    assert enemy_control.zone == Zone.GRAVEYARD

    warders[1].destroy()
    assert warders[1].zone == Zone.GRAVEYARD
    assert magtheridon.dormant
    assert friendly_control.zone == Zone.PLAY
    assert enemy_control.zone == Zone.GRAVEYARD

    warders[2].destroy()
    assert warders[2].zone == Zone.GRAVEYARD
    assert not magtheridon.dormant
    assert magtheridon.zone == Zone.PLAY
    assert (magtheridon.atk, magtheridon.health) == (12, 12)
    assert friendly_control.zone == Zone.GRAVEYARD
    assert enemy_control.zone == Zone.GRAVEYARD
    assert not [card for card in player.field + opponent.field if card.id == "BT_850t"]


def test_BT_850_awaken_progress_counts_three_warders_killed_in_one_batch():
    game = empty_game()
    player = game.player1
    opponent = game.player2
    player.max_mana = 10
    magtheridon = player.give("BT_850")
    magtheridon.play()
    warders = [card for card in opponent.field if card.id == "BT_850t"]
    assert len(warders) == 3

    # Restore fixture mana after playing Magtheridon so Flamestrike can kill
    # all three Warders in one damage/death batch.
    player.used_mana = 0
    flamestrike = player.give("CS2_032")
    flamestrike.play()

    assert flamestrike.zone == Zone.GRAVEYARD
    assert all(card.zone == Zone.GRAVEYARD for card in warders)
    assert not magtheridon.dormant
    assert magtheridon.zone == Zone.PLAY
    assert (magtheridon.atk, magtheridon.health) == (12, 12)
    assert not [card for card in player.field + opponent.field if card.id == "BT_850t"]


def test_TRL_251_friendly_death_buffs_hand_minion_and_enemy_death_is_ignored():
    game = empty_game()
    player = game.player1
    spirit = player.summon("TRL_251")
    hand_minion = player.give(WISP)
    victim = player.summon(WISP)

    victim.destroy()

    assert spirit.zone == Zone.PLAY
    assert spirit.stealthed
    assert victim.zone == Zone.GRAVEYARD
    assert hand_minion.zone == Zone.HAND
    assert (hand_minion.atk, hand_minion.health) == (2, 2)

    enemy_victim = game.player2.summon(WISP)
    enemy_victim.destroy()
    assert enemy_victim.zone == Zone.GRAVEYARD
    assert (hand_minion.atk, hand_minion.health) == (2, 2)

    game.skip_turn()
    assert not spirit.stealthed


def test_TRL_257_friendly_death_damages_enemy_hero():
    game = empty_game()
    player = game.player1
    opponent = game.player2
    sapper = player.summon("TRL_257")
    victim = player.summon(WISP)

    victim.destroy()

    assert sapper.zone == Zone.PLAY
    assert victim.zone == Zone.GRAVEYARD
    assert (opponent.hero.health, player.hero.health) == (28, 30)


def test_TRL_257_enemy_death_does_not_trigger():
    game = empty_game()
    player = game.player1
    opponent = game.player2
    player.summon("TRL_257")
    enemy_victim = opponent.summon(WISP)
    enemy_victim.destroy()
    assert enemy_victim.zone == Zone.GRAVEYARD
    assert opponent.hero.health == 30
    assert player.hero.health == 30


def test_TRL_257_two_friendly_deaths_hit_enemy_twice_but_own_death_does_not():
    game = empty_game()
    player = game.player1
    opponent = game.player2
    sapper = player.summon("TRL_257")
    victims = [player.summon(WISP) for _ in range(2)]

    player.give("EX1_400").play()

    assert all(victim.zone == Zone.GRAVEYARD for victim in victims)
    assert sapper.zone == Zone.PLAY
    assert (opponent.hero.health, player.hero.health) == (26, 30)

    sapper.destroy()
    assert sapper.zone == Zone.GRAVEYARD
    assert (opponent.hero.health, player.hero.health) == (26, 30)


def test_TRL_502_shuffles_one_cost_copy_of_friendly_death_not_enemy_death():
    game = empty_game()
    player = game.player1
    spirit = player.summon("TRL_502")
    assert spirit.stealthed
    friendly_victim = player.summon(WISP)

    friendly_victim.destroy()

    copies = [card for card in player.deck if card.id == WISP]
    assert spirit.zone == Zone.PLAY
    assert friendly_victim.zone == Zone.GRAVEYARD
    assert len(copies) == 1
    assert copies[0].zone == Zone.DECK
    assert copies[0].cost == 1
    assert copies[0] is not friendly_victim

    enemy_victim = game.player2.summon(WISP)
    enemy_victim.destroy()
    copies = [card for card in player.deck if card.id == WISP]
    assert enemy_victim.zone == Zone.GRAVEYARD
    assert len(copies) == 1
    assert copies[0].cost == 1

    game.skip_turn()
    assert not spirit.stealthed
