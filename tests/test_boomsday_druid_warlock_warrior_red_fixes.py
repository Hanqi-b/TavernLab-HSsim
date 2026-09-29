"""Targeted behavior tests for the Boomsday warrior/druid/warlock red cards."""

from hearthstone.enums import CardClass, CardType, Race, Zone

from fireplace.dsl.selector import TREANT
from fireplace.exceptions import InvalidAction

from utils import MOONFIRE, WISP, prepare_empty_game


def ready_game(player_class=CardClass.MAGE, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(player_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_omega_assembly_at_ten_crystals_keeps_three_distinct_mechs():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    owner.max_resources = 10
    owner.max_mana = 10

    spell = owner.give("BOT_299")
    spell.play()

    mechs = list(owner.hand)
    assert spell.zone == Zone.GRAVEYARD
    assert owner.choice is None
    assert len(mechs) == 3
    assert len({card.id for card in mechs}) == 3
    assert all(card.type == CardType.MINION for card in mechs)
    assert all(Race.MECHANICAL in card.races for card in mechs)


def test_omega_assembly_below_ten_crystals_opens_normal_discover():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    # max_resources is the cap; max_mana is the current crystal count.
    owner.max_resources = 10
    owner.max_mana = 9

    spell = owner.give("BOT_299")
    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert owner.choice is not None
    options = list(owner.choice.cards)
    assert len(options) == 3
    assert len({card.id for card in options}) == 3
    assert all(card.type == CardType.MINION for card in options)
    assert all(Race.MECHANICAL in card.races for card in options)

    selected = options[0]
    owner.choice.choose(selected)
    assert owner.choice is None
    assert selected in owner.hand
    assert selected.zone == Zone.HAND


def test_landscaping_summons_two_live_two_two_treants():
    _, owner, _ = ready_game(CardClass.DRUID)

    spell = owner.give("BOT_420")
    spell.play()

    treants = [minion for minion in owner.field if minion.id == "EX1_158t"]
    assert spell.zone == Zone.GRAVEYARD
    assert len(treants) == 2
    assert all(minion.zone == Zone.PLAY for minion in treants)
    assert all((minion.atk, minion.health, minion.max_health) == (2, 2, 2) for minion in treants)
    assert TREANT.eval(treants, owner) == treants


def test_landscaping_is_unplayable_with_no_minion_slots():
    _, owner, _ = ready_game(CardClass.DRUID)
    for _ in range(7):
        owner.summon(WISP)

    spell = owner.give("BOT_420")
    assert owner.minion_slots == 0
    assert not spell.is_playable()
    try:
        spell.play()
    except InvalidAction:
        pass
    else:
        raise AssertionError("Landscaping unexpectedly played on a full board")


def test_dr_morrigan_deathrattle_summons_a_deck_minion_and_decks_morrigan():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    chosen = owner.give("CS2_182")
    chosen.shuffle_into_deck()
    spell = owner.give(MOONFIRE)
    spell.shuffle_into_deck()
    morrigan = owner.summon("BOT_433")

    morrigan.destroy()

    replacement = [minion for minion in owner.field if minion.id == chosen.id]
    assert morrigan.zone == Zone.DECK
    assert chosen.zone == Zone.PLAY
    assert len(replacement) == 1
    assert replacement[0] is chosen
    assert spell.zone == Zone.DECK


def test_dr_morrigan_without_a_deck_minion_stays_dead():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    spell = owner.give(MOONFIRE)
    spell.shuffle_into_deck()
    morrigan = owner.summon("BOT_433")

    morrigan.destroy()

    assert morrigan.zone == Zone.GRAVEYARD
    assert spell.zone == Zone.DECK
    assert not owner.field


def test_flobbidinous_floop_tracks_last_minion_in_hand_at_three_four():
    _, owner, opponent = ready_game(CardClass.DRUID)
    floop = owner.give("BOT_434")

    owner.give("CS2_182").play()
    first_copy = next(card for card in owner.hand if card.id == "CS2_182")
    assert floop.zone == Zone.SETASIDE
    assert first_copy.zone == Zone.HAND
    assert first_copy.data.id == "CS2_182"
    assert (first_copy.atk, first_copy.health, first_copy.max_health) == (3, 4, 4)
    assert first_copy.cost == 4

    owner.give("EX1_016").play()
    second_copy = next(card for card in owner.hand if card.id == "EX1_016")
    assert first_copy.zone == Zone.SETASIDE
    assert second_copy.zone == Zone.HAND
    assert second_copy.data.id == "EX1_016"
    assert (second_copy.atk, second_copy.health, second_copy.max_health) == (3, 4, 4)
    assert second_copy.cost == 4

    owner.give(MOONFIRE).play(target=opponent.hero)
    spell_copy = next(card for card in owner.hand if card.zone == Zone.HAND)
    assert spell_copy is second_copy
    assert spell_copy.data.id == "EX1_016"
    assert (spell_copy.atk, spell_copy.health, spell_copy.max_health) == (3, 4, 4)

    owner.give(WISP).play()
    cheap_copy = next(card for card in owner.hand if card.id == WISP)
    assert second_copy.zone == Zone.SETASIDE
    assert (cheap_copy.cost, cheap_copy.atk, cheap_copy.health) == (4, 3, 4)


def test_flobbidinous_floop_ignores_a_spell_until_a_minion_is_played():
    _, owner, opponent = ready_game(CardClass.DRUID)
    floop = owner.give("BOT_434")

    owner.give(MOONFIRE).play(target=opponent.hero)

    assert floop.zone == Zone.HAND
    assert floop.data.id == "BOT_434"
    assert (floop.atk, floop.health, floop.max_health) == (3, 4, 4)
