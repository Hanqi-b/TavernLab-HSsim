"""Behavior checks for the remaining cast-rule yellow cards."""

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


def test_red_mana_wyrm_only_gains_attack_for_own_hand_casts():
    game, owner, opponent = ready_game()
    wyrm = owner.summon("CFM_060")
    initial_attack = wyrm.atk

    owner.give("CS2_008").play(target=opponent.hero)
    owner.give("CS2_008").play(target=opponent.hero)
    assert wyrm.atk == initial_attack + 4

    archivist = owner.summon("LOOT_414")
    spell = owner.card("CS2_023", zone=Zone.DECK)
    for card_id in ("CS2_231", "CS2_182", "CS2_033"):
        owner.card(card_id, zone=Zone.DECK)
    game.end_turn()
    assert spell.zone == Zone.GRAVEYARD
    assert archivist.zone == Zone.PLAY
    assert wyrm.atk == initial_attack + 4

    opponent.give("CS2_008").play(target=owner.hero)
    assert wyrm.atk == initial_attack + 4


def test_grand_archivist_casts_a_deck_spell_with_a_legal_random_target():
    game, owner, opponent = ready_game()
    own_minion = owner.summon("EX1_572")
    enemy_minion = opponent.summon("EX1_572")
    archivist = owner.summon("LOOT_414")
    frostbolt = owner.card("CS2_024", zone=Zone.DECK)
    targets = (owner.hero, opponent.hero, own_minion, enemy_minion, archivist)
    old_damage = {target: target.damage for target in targets}

    game.end_turn()

    assert frostbolt.zone == Zone.GRAVEYARD
    assert frostbolt not in owner.deck
    assert frostbolt.target in targets
    assert archivist.zone == Zone.PLAY
    assert sum(target.damage == old_damage[target] + 3 for target in targets) == 1
    if frostbolt.target.controller is opponent:
        assert frostbolt.target.frozen
    assert all(target.damage == old_damage[target] for target in targets if target is not frostbolt.target)


def test_grand_archivist_does_not_cast_on_opponent_turn_or_without_deck_spell():
    game, owner, opponent = ready_game()
    archivist = owner.summon("LOOT_414")
    minion = owner.card("CS2_231", zone=Zone.DECK)

    game.end_turn()
    assert minion.zone == Zone.DECK
    assert minion in owner.deck
    assert archivist.zone == Zone.PLAY

    frostbolt = owner.card("CS2_024", zone=Zone.DECK)
    game.end_turn()  # The opponent's turn ends; Archivist must not cast yet.
    # Owner draws at the start of their new turn; that is not Archivist casting it.
    assert frostbolt.zone in (Zone.DECK, Zone.HAND)
    assert frostbolt.target is None
