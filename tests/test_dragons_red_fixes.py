from hearthstone.enums import CardClass, CardType, Rarity, Zone
import pytest

from fireplace.exceptions import InvalidAction
from utils import *


def _put_in_deck(player, card_id):
    card = player.give(card_id)
    card.zone = Zone.DECK
    return card


def test_scion_of_ruin_summons_two_friendly_copies_after_two_invokes():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    _put_in_deck(game.player1, "DRG_650")
    game.player1.give("DRG_303").play()
    game.player1.give("DRG_303").play()
    assert game.player1.invoke_counter == 2

    game.player1.give("DRG_019").play()

    scions = game.player1.field.filter(id="DRG_019")
    assert len(scions) == 3
    assert all(card.rush for card in scions)
    assert not game.player2.field.filter(id="DRG_019")

    no_invoke = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    no_invoke.player1.give("DRG_019").play()
    assert len(no_invoke.player1.field.filter(id="DRG_019")) == 1


def test_wing_commander_attack_tracks_dragons_in_hand():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    dragon1 = game.player1.give("DRG_073")
    dragon2 = game.player1.give("DRG_073")
    wing = game.player1.give("DRG_058").play()
    assert wing.atk == 2 + 4

    dragon1.discard()
    assert wing.atk == 2 + 2
    dragon2.discard()
    assert wing.atk == 2


def test_troll_batrider_only_hits_an_enemy_minion():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    enemy = game.player2.summon("CS2_182")
    enemy.max_health = 10

    game.player1.give("DRG_067").play()

    assert enemy.health == 7
    assert game.player2.hero.health == 30

    empty_enemy_board = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    empty_enemy_board.player1.give("DRG_067").play()
    assert empty_enemy_board.player2.hero.health == 30


def test_dread_raven_scales_by_each_other_raven_and_updates_on_death():
    game = prepare_empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
    first = game.player1.summon("DRG_088")
    base_attack = first.data.atk
    assert first.atk == base_attack

    second = game.player1.summon("DRG_088")
    third = game.player1.summon("DRG_088")
    assert first.atk == base_attack + 6
    assert second.atk == base_attack + 6
    assert third.atk == base_attack + 6

    third.destroy()
    assert first.atk == base_attack + 3
    assert second.atk == base_attack + 3


def test_bandersmosh_in_hand_becomes_a_five_five_legendary():
    game = prepare_empty_game(CardClass.SHAMAN, CardClass.SHAMAN)
    bandersmosh = game.player1.give("DRG_096")

    # Cover either initial-player assignment while allowing the hand trigger
    # to fire on the controller's next turn.
    for _ in range(2):
        if bandersmosh.morphed:
            break
        game.end_turn()

    assert bandersmosh.morphed
    transformed = bandersmosh.morphed
    assert transformed.zone == Zone.HAND
    assert transformed.id != "DRG_096"
    assert transformed.rarity == Rarity.LEGENDARY
    assert transformed.atk == 5
    assert transformed.health == 5

    game.end_turn()
    game.end_turn()
    next_form = transformed.morphed
    assert next_form is not None and next_form.zone == Zone.HAND
    assert next_form.rarity == Rarity.LEGENDARY
    assert (next_form.atk, next_form.health) == (5, 5)


def test_arcane_breath_discovers_spells_only_while_holding_a_dragon():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    game.player1.give("DRG_073")
    target = game.player2.summon("CS2_182")
    target.max_health = 10
    spell = game.player1.give("DRG_106")
    spell.play(target=target)
    assert target.health == 8
    assert game.player1.choice
    assert len(game.player1.choice.cards) == 3
    assert all(card.type == CardType.SPELL for card in game.player1.choice.cards)
    chosen = game.player1.choice.cards[0]
    game.player1.choice.choose(chosen)
    assert chosen in game.player1.hand
    assert not game.player1.choice

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    target = game.player2.summon("CS2_182")
    target.max_health = 10
    spell = game.player1.give("DRG_106")
    spell.play(target=target)
    assert target.health == 8
    assert not game.player1.choice


def test_lightning_breath_hits_target_and_neighbors_only_with_dragon():
    game = prepare_empty_game(CardClass.SHAMAN, CardClass.SHAMAN)
    dragon = game.player1.give("DRG_073")
    left = game.player2.summon("CS2_182")
    middle = game.player2.summon("CS2_182")
    right = game.player2.summon("CS2_182")
    for minion in (left, middle, right):
        minion.max_health = 10
    game.player1.give("DRG_219").play(target=middle)
    assert [minion.health for minion in (left, middle, right)] == [6, 6, 6]

    dragon.discard()
    left = game.player2.summon("CS2_182")
    middle = game.player2.summon("CS2_182")
    right = game.player2.summon("CS2_182")
    for minion in (left, middle, right):
        minion.max_health = 10
    game.player1.give("DRG_219").play(target=middle)
    assert [minion.health for minion in (left, middle, right)] == [10, 6, 10]


def test_lightforged_crusader_adds_five_paladin_cards_only_for_neutral_free_deck():
    game = prepare_empty_game(CardClass.PALADIN, CardClass.PALADIN)
    before = list(game.player1.hand)
    game.player1.give("DRG_231").play()
    added = [card for card in game.player1.hand if card not in before]
    assert len(added) == 5
    assert all(card.card_class == CardClass.PALADIN for card in added)

    game = prepare_empty_game(CardClass.PALADIN, CardClass.PALADIN)
    _put_in_deck(game.player1, WISP)
    before = list(game.player1.hand)
    game.player1.give("DRG_231").play()
    assert [card for card in game.player1.hand if card not in before] == []


def test_clear_the_way_rewards_once_after_three_rush_summons():
    game = prepare_empty_game(CardClass.HUNTER, CardClass.HUNTER)
    quest = game.player1.give("DRG_251").play()
    game.player1.summon(WISP)
    assert quest.progress == 0

    for _ in range(3):
        game.player1.summon("DRG_010")
    assert quest.zone == Zone.GRAVEYARD
    assert len(game.player1.field.filter(id="DRG_251t")) == 1


def test_toxic_reinforcements_rewards_three_leper_gnomes_after_hero_powers():
    game = prepare_empty_game(CardClass.HUNTER, CardClass.HUNTER)
    quest = game.player1.give("DRG_255").play()
    assert quest.progress == 0

    # The opponent's power is not progress for this sidequest.
    game.end_turn()
    game.player2.hero.power.use()
    assert quest.progress == 0
    game.end_turn()

    for index in range(3):
        game.player1.hero.power.use()
        if index < 2:
            game.end_turn()
            game.end_turn()

    lepers = game.player1.field.filter(id="DRG_255t2")
    assert quest.zone == Zone.GRAVEYARD
    assert len(lepers) == 3
    assert all((card.atk, card.health) == (1, 1) for card in lepers)


def test_dragonbane_hits_a_random_enemy_character_after_hero_power():
    outcomes = set()
    for seed in range(32):
        game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
        game.random.seed(seed)
        enemy_minion = game.player2.summon("CS2_182")
        enemy_minion.max_health = 20
        game.player1.summon("DRG_256")
        game.player1.hero.power.use()
        if enemy_minion.damage:
            assert enemy_minion.damage == 5
            outcomes.add("minion")
        else:
            assert game.player2.hero.health == 25
            outcomes.add("hero")
    assert outcomes == {"minion", "hero"}


def test_treenforcements_choice_subcards_have_their_own_effects():
    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    target = game.player1.summon(WISP)
    game.player1.give("DRG_311").play(choose="DRG_311b", target=target)
    assert target.max_health == 3
    assert target.health == 3
    assert target.taunt

    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    game.player1.give("DRG_311").play(choose="DRG_311a")
    treants = game.player1.field.filter(id="DRG_311t")
    assert len(treants) == 1
    assert (treants[0].atk, treants[0].health) == (2, 2)

    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    spell = game.player1.give("DRG_311")
    enemy_hero = game.player2.hero
    with pytest.raises(InvalidAction):
        spell.play(choose="DRG_311b", target=enemy_hero)
    assert spell.zone == Zone.HAND
    assert enemy_hero.max_health == 30 and not enemy_hero.taunt


def test_blowtorch_saboteur_sets_only_the_opponents_next_power_to_three():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    own_power = game.player1.hero.power
    enemy_power = game.player2.hero.power
    assert own_power.cost == 2
    assert enemy_power.cost == 2

    saboteur = game.player1.give("DRG_403").play()
    assert own_power.cost == 2
    assert enemy_power.cost == 3

    saboteur.destroy()
    assert enemy_power.cost == 3

    game.end_turn()
    enemy_power.use(target=game.player1.hero)
    assert enemy_power.cost == 2


def test_galakrond_the_nightmare_draws_one_cost_cards_at_each_rank():
    game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
    _put_in_deck(game.player1, WISP)
    hero = game.player1.give("DRG_610").play()
    assert game.player1.hero.id == "DRG_610"
    assert game.player1.hand[-1].id == WISP
    assert game.player1.hand[-1].cost == 1

    game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
    _put_in_deck(game.player1, WISP)
    _put_in_deck(game.player1, WISP)
    game.player1.give("DRG_610t2").play()
    assert len(game.player1.hand.filter(id=WISP)) == 2
    assert all(card.cost == 1 for card in game.player1.hand.filter(id=WISP))

    game = prepare_empty_game(CardClass.ROGUE, CardClass.ROGUE)
    for _ in range(4):
        _put_in_deck(game.player1, WISP)
    game.player1.give("DRG_610t3").play()
    drawn = game.player1.hand.filter(id=WISP)
    assert len(drawn) == 4
    assert all(card.cost == 1 for card in drawn)
    assert game.player1.weapon.id == "DRG_238ht"
