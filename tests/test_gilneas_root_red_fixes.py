"""Card-specific Witchwood regressions for targeting, summons, and cost effects."""

from hearthstone.enums import CardClass, Zone

from utils import MOONFIRE, WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_woodcutters_axe_buffs_only_friendly_rush_minion_without_granting_rush():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    rush = owner.summon("GIL_515")
    plain = owner.summon(WISP)
    rush_before = (rush.atk, rush.max_health)
    plain_before = (plain.atk, plain.max_health)
    axe = owner.give("GIL_653")
    axe.play()
    owner.give("CS2_091").play()

    assert axe.zone == Zone.GRAVEYARD
    assert (rush.atk, rush.max_health) == (rush_before[0] + 2, rush_before[1] + 1)
    assert rush.rush
    assert (plain.atk, plain.max_health) == plain_before
    assert not plain.rush


def test_woodcutters_axe_without_rush_target_does_not_buff_plain_minion():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    plain = owner.summon(WISP)
    axe = owner.give("GIL_653")
    axe.play()
    owner.give("CS2_091").play()
    assert (plain.atk, plain.max_health) == (1, 1)
    assert not plain.rush


def test_witchwood_apple_adds_three_two_two_treants_to_hand():
    _, owner, _ = ready_game(CardClass.DRUID)
    apple = owner.give("GIL_663")
    apple.play()
    treants = [card for card in owner.hand if card.id == "GIL_663t"]
    assert apple.zone == Zone.GRAVEYARD
    assert len(treants) == 3
    assert all(card.zone == Zone.HAND and (card.atk, card.max_health) == (2, 2) for card in treants)


def test_muck_hunter_respects_full_enemy_board_capacity():
    _, owner, opponent = ready_game()
    for _ in range(7):
        opponent.summon(WISP)
    hunter = owner.give("GIL_682").play()
    assert hunter.zone == Zone.PLAY
    assert len(opponent.field) == 7
    assert not [card for card in opponent.field if card.id == "GIL_682t"]


def test_muck_hunter_fills_only_one_enemy_slot_when_six_are_occupied():
    _, owner, opponent = ready_game()
    for _ in range(6):
        opponent.summon(WISP)
    owner.give("GIL_682").play()
    assert len(opponent.field) == 7
    assert len([card for card in opponent.field if card.id == "GIL_682t"]) == 1


def test_marsh_drake_does_not_summon_into_full_enemy_board():
    _, owner, opponent = ready_game()
    for _ in range(7):
        opponent.summon(WISP)
    drake = owner.give("GIL_683").play()
    assert drake.zone == Zone.PLAY
    assert len(opponent.field) == 7
    assert not [card for card in opponent.field if card.id == "GIL_683t"]


def test_marsh_drake_summons_poisonous_drakeslayer_when_one_slot_available():
    _, owner, opponent = ready_game()
    for _ in range(6):
        opponent.summon(WISP)
    owner.give("GIL_683").play()
    tokens = [card for card in opponent.field if card.id == "GIL_683t"]
    assert len(opponent.field) == 7 and len(tokens) == 1
    assert tokens[0].poisonous and (tokens[0].atk, tokens[0].max_health) == (2, 1)


def test_duskfallen_aviana_makes_each_players_first_card_free_once_per_turn():
    game, owner, opponent = ready_game(CardClass.DRUID)
    aviana = owner.give("GIL_800").play()
    assert aviana.zone == Zone.PLAY
    game.end_turn()

    enemy_first = opponent.give("EX1_399")
    enemy_second = opponent.give("EX1_399")
    assert enemy_first.cost == enemy_second.cost == 0
    before = opponent.mana
    enemy_first.play()
    assert opponent.mana == before
    assert enemy_second.cost == 5
    enemy_second.play()
    assert opponent.mana == before - 5

    game.end_turn()
    own_first = owner.give("EX1_399")
    own_second = owner.give("EX1_399")
    assert own_first.cost == own_second.cost == 0
    before = owner.mana
    own_first.play()
    assert owner.mana == before
    assert own_second.cost == 5
    own_second.play()
    assert owner.mana == before - 5


def test_hidden_wisdom_triggers_only_after_opponents_third_card_and_draws_two():
    game, owner, opponent = ready_game(CardClass.PALADIN)
    secret = owner.give("GIL_903")
    secret.play()
    draw_a = owner.card(WISP, zone=Zone.DECK)
    draw_b = owner.card("EX1_399", zone=Zone.DECK)
    game.end_turn()

    for index in range(2):
        opponent.give(MOONFIRE).play(target=owner.hero)
        assert secret.zone == Zone.SECRET
        assert draw_a.zone == Zone.DECK and draw_b.zone == Zone.DECK
    opponent.give(MOONFIRE).play(target=owner.hero)
    assert secret.zone == Zone.GRAVEYARD
    assert draw_a.zone == Zone.HAND and draw_b.zone == Zone.HAND
    assert draw_a in owner.hand and draw_b in owner.hand
