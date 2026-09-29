"""Per-card checks for the confirmed 'you cast a spell' rule."""

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


def ready_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def cast_spell_by_another_friendly_card(game, player):
    player.summon("LOOT_414")  # Grand Archivist casts a deck spell at turn end.
    spell = player.card("CS2_023", zone=Zone.DECK)  # Arcane Intellect
    for card_id in ("CS2_231", "CS2_182", "CS2_033", "CS2_168"):
        player.card(card_id, zone=Zone.DECK)
    deck_before = len(player.deck)
    hand_before = len(player.hand)

    game.end_turn()

    assert spell.zone == Zone.GRAVEYARD
    assert len(player.deck) == deck_before - 3  # Spell leaves deck; it draws two.
    assert len(player.hand) == hand_before + 2


def test_gadgetzan_auctioneer_only_draws_for_player_hand_cast():
    game, player, opponent = ready_game()
    auctioneer = player.summon("EX1_095")
    known_card = player.card("CS2_231", zone=Zone.DECK)

    player.give("CS2_008").play(target=opponent.hero)
    assert known_card.zone == Zone.HAND and known_card in player.hand

    cast_spell_by_another_friendly_card(game, player)
    assert auctioneer.zone == Zone.PLAY
    deck_after_effect = len(player.deck)
    hand_after_effect = len(player.hand)

    opponent.give("CS2_008").play(target=player.hero)
    assert len(player.deck) == deck_after_effect
    assert len(player.hand) == hand_after_effect


def test_arcane_devourer_only_gains_stats_for_player_hand_cast():
    game, player, opponent = ready_game()
    devourer = player.summon("EX1_187")
    base_stats = (devourer.atk, devourer.max_health)

    player.give("CS2_008").play(target=opponent.hero)
    expected_stats = (base_stats[0] + 2, base_stats[1] + 2)
    assert (devourer.atk, devourer.max_health) == expected_stats

    cast_spell_by_another_friendly_card(game, player)
    assert (devourer.atk, devourer.max_health) == expected_stats

    opponent.give("CS2_008").play(target=player.hero)
    assert (devourer.atk, devourer.max_health) == expected_stats


def test_archmage_antonidas_only_adds_fireball_for_player_hand_cast():
    game, player, opponent = ready_game()
    antonidas = player.summon("EX1_559")

    player.give("CS2_008").play(target=opponent.hero)
    fireballs = [card for card in player.hand if card.id == "CS2_029"]
    assert len(fireballs) == 1 and fireballs[0].zone == Zone.HAND

    cast_spell_by_another_friendly_card(game, player)
    assert antonidas.zone == Zone.PLAY
    assert sum(card.id == "CS2_029" for card in player.hand) == 1

    opponent.give("CS2_008").play(target=player.hero)
    assert sum(card.id == "CS2_029" for card in player.hand) == 1
