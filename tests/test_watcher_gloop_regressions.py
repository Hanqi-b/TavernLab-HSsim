"""Regression coverage for Arcane Watcher and Gloop Sprayer."""

import pytest
from hearthstone.enums import CardClass, Zone

from utils import WISP, prepare_empty_game


def ready_game(player_class=CardClass.MAGE, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(player_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


@pytest.mark.parametrize("zone", [Zone.HAND, Zone.DECK, Zone.GRAVEYARD])
def test_arcane_watcher_ignores_offboard_spell_damage(zone):
    _, owner, _ = ready_game()
    owner.card("CS2_142", zone=zone)

    watcher = owner.summon("DAL_434")
    watcher.turns_in_play = 1

    assert owner.spellpower == 0
    assert watcher.cant_attack
    assert not watcher.can_attack()


def test_arcane_watcher_unlocks_only_for_active_owner_spellpower_and_relocks():
    _, owner, _ = ready_game()
    watcher = owner.summon("DAL_434")
    watcher.turns_in_play = 1
    spellpower = owner.summon("CS2_142")

    assert owner.spellpower == 1
    assert not watcher.cant_attack
    assert watcher.can_attack()

    spellpower.destroy()
    assert owner.spellpower == 0
    assert watcher.cant_attack
    assert not watcher.can_attack()

    spellpower = owner.summon("CS2_142")
    spellpower.silence()
    assert owner.spellpower == 0
    assert watcher.cant_attack
    assert not watcher.can_attack()


def test_arcane_watcher_ignores_opponent_spellpower_and_can_be_silenced():
    _, owner, opponent = ready_game()
    opponent.summon("CS2_142")
    watcher = owner.summon("DAL_434")
    watcher.turns_in_play = 1

    assert opponent.spellpower == 1
    assert owner.spellpower == 0
    assert watcher.cant_attack
    assert not watcher.can_attack()

    watcher.silence()
    assert watcher.silenced
    assert not watcher.cant_attack
    assert watcher.can_attack()


def test_arcane_watcher_accepts_controller_spellpower_aura():
    _, owner, opponent = ready_game(CardClass.HUNTER)
    watcher = owner.summon("DAL_434")
    watcher.turns_in_play = 1
    vereesa = owner.give("DAL_379")
    vereesa.play()
    owner.hero.attack(opponent.hero)

    assert owner.spellpower == 2
    assert not watcher.cant_attack
    assert watcher.can_attack()


def test_gloop_sprayer_copies_each_original_to_its_matching_side():
    _, owner, _ = ready_game()
    left = owner.summon("CS2_142")
    right = owner.summon("EX1_563")
    owner.give("GVG_010").play(target=left)
    right.hit(2)
    gloop = owner.give("BOT_507")

    gloop.play(index=1)

    assert [card.id for card in owner.field] == [
        "CS2_142",
        "CS2_142",
        "BOT_507",
        "EX1_563",
        "EX1_563",
    ]
    left_copy = owner.field[1]
    right_copy = owner.field[3]
    assert (left_copy.atk, left_copy.max_health, left_copy.spellpower) == (
        left.atk,
        left.max_health,
        left.spellpower,
    )
    assert (right_copy.atk, right_copy.max_health, right_copy.damage) == (
        right.atk,
        right.max_health,
        right.damage,
    )


def test_gloop_sprayer_copies_trigger_knife_juggler():
    _, owner, opponent = ready_game()
    owner.summon("NEW1_019")
    owner.summon(WISP)
    owner.summon(WISP)
    gloop = owner.give("BOT_507")
    before = opponent.hero.health

    gloop.play(index=2)

    assert opponent.hero.health == before - 3


def test_gloop_sprayer_copies_trigger_khadgar_with_board_capacity():
    _, owner, _ = ready_game()
    owner.summon("DAL_575")
    owner.summon(WISP)
    owner.summon(WISP)
    gloop = owner.give("BOT_507")

    gloop.play(index=2)

    assert len(owner.field) == 7
    assert [card.id for card in owner.field].count("DAL_575") == 1
    assert [card.id for card in owner.field].count(WISP) == 5
    assert [card.id for card in owner.field].count("BOT_507") == 1


def test_gloop_sprayer_keeps_lone_copies_on_their_original_side():
    _, owner, _ = ready_game()
    owner.summon(WISP)
    gloop = owner.give("BOT_507")
    gloop.play(index=1)
    assert [card.id for card in owner.field] == [WISP, WISP, "BOT_507"]

    _, owner, _ = ready_game()
    right = owner.summon(WISP)
    gloop = owner.give("BOT_507")
    gloop.play(index=0)
    assert [card.id for card in owner.field] == ["BOT_507", WISP, WISP]


@pytest.mark.parametrize("filler_count", [4, 3])
def test_gloop_sprayer_respects_remaining_board_capacity(filler_count):
    _, owner, _ = ready_game()
    left = owner.summon("CS2_142")
    right = owner.summon("EX1_563")
    for _ in range(filler_count):
        owner.summon(WISP)
    gloop = owner.give("BOT_507")

    gloop.play(index=1)

    assert len(owner.field) == 7
    if filler_count == 4:
        assert owner.field[1].id == "BOT_507"
        assert [card.id for card in owner.field].count("CS2_142") == 1
        assert [card.id for card in owner.field].count("EX1_563") == 1
    else:
        assert owner.field[2].id == "BOT_507"
        assert [card.id for card in owner.field].count("CS2_142") == 2
        assert [card.id for card in owner.field].count("EX1_563") == 1
