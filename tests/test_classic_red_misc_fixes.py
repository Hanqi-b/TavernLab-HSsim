"""Behavior regressions for three Classic cards previously graded RED."""

from hearthstone.enums import CardClass, Zone

from fireplace import cards
from fireplace.dsl.random_picker import RandomCollectible
from fireplace.dsl.selector import ANOTHER_CLASS
from utils import prepare_empty_game


def ready_rogue_game():
    game = prepare_empty_game(CardClass.ROGUE, CardClass.MAGE)
    player, opponent = game.players
    if game.current_player is not player:
        game.end_turn()
    for participant in (player, opponent):
        participant.discard_hand()
        participant.max_mana = 10
        participant.used_mana = 0
    return game, player, opponent


def test_pilfer_pool_and_actual_cards_are_collectible_other_hero_classes():
    _, player, _ = ready_rogue_game()
    source = player.give("EX1_182")
    pool = RandomCollectible(card_class=ANOTHER_CLASS).find_cards(source)
    assert pool
    assert all(cards.db[card_id].collectible for card_id in pool)
    assert all(cards.db[card_id].card_class not in (
        CardClass.ROGUE, CardClass.NEUTRAL, CardClass.INVALID,
        CardClass.DREAM, CardClass.WHIZBANG,
    ) for card_id in pool)

    for seed in range(12):
        game, player, _ = ready_rogue_game()
        game.random.seed(seed)
        pilfer = player.give("EX1_182")
        pilfer.play()
        assert pilfer.zone == Zone.GRAVEYARD
        assert len(player.hand) == 1
        generated = player.hand[0]
        assert generated.zone == Zone.HAND
        assert generated.data.collectible
        assert generated.card_class not in (
            CardClass.ROGUE, CardClass.NEUTRAL, CardClass.INVALID,
            CardClass.DREAM, CardClass.WHIZBANG,
        )


def test_kidnapper_combo_returns_stolen_minion_to_current_controller():
    _, player, opponent = ready_rogue_game()
    stolen = opponent.summon("CS2_231")
    player.steal(stolen)
    assert stolen.zone == Zone.PLAY and stolen.controller is player

    player.give("CS2_008").play(target=opponent.hero)
    kidnapper = player.give("NEW1_005")
    kidnapper.play(target=stolen)

    assert kidnapper.zone == Zone.PLAY
    assert stolen.zone == Zone.HAND
    assert stolen.controller is player
    assert any(card is stolen for card in player.hand)
    assert all(card is not stolen for card in opponent.hand)


def test_kidnapper_combo_bounces_ordinary_enemy_and_no_combo_does_not():
    _, player, opponent = ready_rogue_game()
    enemy = opponent.summon("CS2_231")
    player.give("CS2_008").play(target=opponent.hero)
    player.give("NEW1_005").play(target=enemy)
    assert enemy.zone == Zone.HAND and enemy.controller is opponent

    _, player, opponent = ready_rogue_game()
    enemy = opponent.summon("CS2_231")
    player.give("NEW1_005").play()
    assert enemy.zone == Zone.PLAY and enemy.controller is opponent


def test_kidnapper_ignores_original_owners_full_hand():
    _, player, opponent = ready_rogue_game()
    opponent.max_hand_size = 1
    held = opponent.give("CS2_182")
    stolen = opponent.summon("CS2_231")
    player.steal(stolen)
    player.give("CS2_008").play(target=opponent.hero)

    player.give("NEW1_005").play(target=stolen)

    assert opponent.hand == [held]
    assert stolen.zone == Zone.HAND and stolen.controller is player
    assert any(card is stolen for card in player.hand)


def test_kidnapper_combo_can_return_friendly_minion():
    _, player, opponent = ready_rogue_game()
    friendly = player.summon("CS2_231")
    player.give("CS2_008").play(target=opponent.hero)

    player.give("NEW1_005").play(target=friendly)

    assert friendly.zone == Zone.HAND and friendly.controller is player
    assert any(card is friendly for card in player.hand)


def test_vanish_returns_each_minion_to_its_current_controllers_hand():
    _, player, opponent = ready_rogue_game()
    stolen = opponent.summon("CS2_231")
    player.steal(stolen)
    friendly = player.summon("CS2_182")
    enemy = opponent.summon("CS2_182")

    player.give("NEW1_004").play()

    assert all(card.zone == Zone.HAND for card in (stolen, friendly, enemy))
    assert any(card is stolen for card in player.hand)
    assert any(card is friendly for card in player.hand)
    assert any(card is enemy for card in opponent.hand)
    assert all(card is not stolen for card in opponent.hand)


def test_vanish_destroys_minion_returned_to_full_hand():
    _, player, opponent = ready_rogue_game()
    friendly = player.summon("CS2_231")
    enemy = opponent.summon("CS2_231")
    held = player.give("CS2_182")
    vanish = player.give("NEW1_004")
    player.max_hand_size = 1

    vanish.play()

    assert friendly.zone == Zone.GRAVEYARD
    assert all(card is not friendly for card in player.hand)
    assert player.hand == [held]
    assert enemy.zone == Zone.HAND and enemy in opponent.hand


def test_commanding_shout_draws_known_card_and_protects_existing_minion():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.MAGE)
    player = game.players[0]
    if game.current_player is not player:
        game.end_turn()
    player.discard_hand()
    player.max_mana = 10
    player.used_mana = 0
    known = player.card("CS2_182", zone=Zone.DECK)
    minion = player.summon("CS2_231")

    shout = player.give("NEW1_036")
    shout.play()
    assert shout.zone == Zone.GRAVEYARD
    assert known.zone == Zone.HAND and any(card is known for card in player.hand)
    assert len(player.deck) == 0

    minion.hit(20)
    assert minion.zone == Zone.PLAY and minion.health == 1


def test_commanding_shout_protects_later_summons_only_this_turn():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.MAGE)
    player = game.players[0]
    if game.current_player is not player:
        game.end_turn()
    player.discard_hand()
    player.max_mana = 10
    player.used_mana = 0
    player.give("NEW1_036").play()
    later = player.summon("CS2_231")
    later.hit(20)
    assert later.zone == Zone.PLAY and later.health == 1

    game.end_turn()
    later.hit(20)
    assert later.zone == Zone.GRAVEYARD


def test_commanding_shout_does_not_protect_enemy_minions():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.MAGE)
    player = game.players[0]
    if game.current_player is not player:
        game.end_turn()
    player.max_mana = 10
    player.used_mana = 0
    enemy = player.opponent.summon("CS2_231")

    player.give("NEW1_036").play()
    enemy.hit(20)

    assert enemy.zone == Zone.GRAVEYARD
