"""Targeted behavior checks for the remaining Rise of Shadows red cards."""

from hearthstone.enums import CardClass, CardType, Rarity, Zone

from utils import FIREBALL, MOONFIRE, WISP, prepare_empty_game


def ready_game(player_class=CardClass.MAGE, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(player_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_blastmaster_boom_counts_only_bombs_in_the_opponents_deck():
    _, owner, opponent = ready_game(CardClass.WARRIOR)
    owner.card("BOT_511t", zone=Zone.DECK)
    for _ in range(2):
        opponent.card("BOT_511t", zone=Zone.DECK)

    blastmaster = owner.give("DAL_064")
    blastmaster.play()

    assert blastmaster.zone == Zone.PLAY
    assert len(owner.field) == 5
    assert [card.id for card in owner.field].count("GVG_110t") == 4
    assert len(opponent.deck.filter(id="BOT_511t")) == 2


def test_blastmaster_without_opponent_bombs_does_not_summon_bots():
    _, owner, opponent = ready_game(CardClass.WARRIOR)
    owner.card("BOT_511t", zone=Zone.DECK)

    blastmaster = owner.give("DAL_064")
    blastmaster.play()

    assert blastmaster.zone == Zone.PLAY
    assert len(owner.field) == 1
    assert not opponent.field


def test_vereesa_equips_thoridal_and_grants_spell_damage_after_hero_attack():
    game, owner, opponent = ready_game(CardClass.HUNTER)
    vereesa = owner.give("DAL_379")
    vereesa.play()

    weapon = owner.weapon
    assert weapon is not None and weapon.id == "DAL_379t"
    assert (weapon.atk, weapon.durability) == (2, 3)

    before = opponent.hero.health
    owner.hero.attack(opponent.hero)
    assert owner.spellpower == 2
    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == before - 2 - 3

    game.end_turn()
    game.end_turn()
    assert owner.spellpower == 0
    owner.give(MOONFIRE).play(target=opponent.hero)
    assert opponent.hero.health == before - 2 - 3 - 1


def test_rafaam_replaces_every_hand_and_deck_card_with_a_legendary_minion():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    owner.give(WISP)
    owner.give(FIREBALL)
    owner.card(WISP, zone=Zone.DECK)
    owner.card(FIREBALL, zone=Zone.DECK)

    rafaam = owner.give("DAL_422")
    rafaam.play()

    assert rafaam.zone == Zone.PLAY
    assert len(owner.hand) == 2
    assert len(owner.deck) == 2
    for card in list(owner.hand) + list(owner.deck):
        assert card.type == CardType.MINION
        assert card.rarity == Rarity.LEGENDARY


def test_sunreaver_warmage_deals_four_when_holding_a_five_plus_cost_spell():
    _, owner, opponent = ready_game()
    owner.give("CS2_028")
    target = opponent.summon("CS2_182")
    warmage = owner.give("DAL_539")

    warmage.play(target=target)

    assert warmage.zone == Zone.PLAY
    assert target.health == 1


def test_sunreaver_warmage_does_nothing_without_a_qualifying_spell():
    _, owner, opponent = ready_game()
    owner.give(FIREBALL)
    target = opponent.summon("CS2_182")
    warmage = owner.give("DAL_539")

    warmage.play()

    assert warmage.zone == Zone.PLAY
    assert target.health == target.max_health


def test_underbelly_fence_gains_stats_and_rush_for_a_foreign_class_card():
    _, owner, _ = ready_game(CardClass.ROGUE)
    foreign = owner.give(FIREBALL)
    fence = owner.give("DAL_714")
    fence.play()

    assert foreign.card_class == CardClass.MAGE
    assert fence.zone == Zone.PLAY
    assert (fence.atk, fence.max_health) == (3, 4)
    assert fence.rush


def test_underbelly_fence_stays_base_stats_without_a_foreign_class_card():
    _, owner, _ = ready_game(CardClass.ROGUE)
    fence = owner.give("DAL_714")
    fence.play()

    assert fence.zone == Zone.PLAY
    assert (fence.atk, fence.max_health) == (2, 3)
    assert not fence.rush


def test_vendetta_costs_zero_with_a_foreign_class_card_and_deals_four():
    _, owner, opponent = ready_game(CardClass.ROGUE)
    owner.give(FIREBALL)
    vendetta = owner.give("DAL_716")
    target = opponent.summon("CS2_182")
    assert vendetta.cost == 0

    vendetta.play(target=target)

    assert vendetta.zone == Zone.GRAVEYARD
    assert target.health == target.max_health - 4


def test_vendetta_keeps_four_cost_without_a_foreign_class_card():
    _, owner, opponent = ready_game(CardClass.ROGUE)
    vendetta = owner.give("DAL_716")
    target = opponent.summon("CS2_182")
    assert vendetta.cost == 4

    vendetta.play(target=target)

    assert vendetta.zone == Zone.GRAVEYARD
    assert target.health == target.max_health - 4


def test_call_to_adventure_draws_lowest_cost_minion_and_buffs_it():
    _, owner, _ = ready_game(CardClass.PALADIN)
    cheapest = owner.card("EX1_045", zone=Zone.DECK)
    expensive = owner.card("EX1_396", zone=Zone.DECK)
    call = owner.give("DAL_727")

    call.play()

    assert call.zone == Zone.GRAVEYARD
    assert cheapest.zone == Zone.HAND
    assert (cheapest.atk, cheapest.max_health) == (6, 7)
    assert expensive.zone == Zone.DECK


def test_mad_summoner_fills_both_empty_boards_to_seven_with_imps():
    _, owner, opponent = ready_game()
    summoner = owner.give("DAL_751")
    summoner.play()

    assert summoner.zone == Zone.PLAY
    assert len(owner.field) == 7
    assert len(opponent.field) == 7
    assert [card.id for card in owner.field].count("DAL_751t") == 6
    assert [card.id for card in opponent.field] == ["DAL_751t"] * 7
    assert all((card.atk, card.max_health) == (1, 1) for card in owner.field if card.id == "DAL_751t")
    assert all((card.atk, card.max_health) == (1, 1) for card in opponent.field)


def test_mad_summoner_respects_existing_board_capacity_on_both_sides():
    _, owner, opponent = ready_game()
    owner.summon(WISP)
    for _ in range(6):
        opponent.summon(WISP)
    summoner = owner.give("DAL_751")
    summoner.play()

    assert len(owner.field) == 7
    assert len(opponent.field) == 7
    assert [card.id for card in owner.field].count("DAL_751t") == 5
    assert [card.id for card in opponent.field].count("DAL_751t") == 1
