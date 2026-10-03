"""Regression coverage for Blink Fox class pools and generated-card metadata."""

import pytest

from hearthstone.enums import CardClass, GameTag, MultiClassGroup

from fireplace import cards
from fireplace.dsl.random_picker import RandomCardPicker
from utils import prepare_empty_game


OPPONENT_CLASSES = (
    CardClass.DRUID,
    CardClass.HUNTER,
    CardClass.MAGE,
    CardClass.PALADIN,
    CardClass.PRIEST,
    CardClass.ROGUE,
    CardClass.SHAMAN,
    CardClass.WARLOCK,
    CardClass.WARRIOR,
    CardClass.DEMONHUNTER,
)


def ready_blink_fox_game(opponent_class):
    game = prepare_empty_game(CardClass.ROGUE, opponent_class)
    player, opponent = game.players
    if game.current_player is not player:
        game.end_turn()
    for participant in (player, opponent):
        participant.discard_hand()
        participant.max_mana = 10
        participant.used_mana = 0
    return game, player, opponent


def blink_fox_picker(source):
    action = source.data.scripts.play[0]
    return action._args[1]


def generated_by(player, source):
    return [card for card in player.hand if card.creator is source]


@pytest.mark.parametrize("opponent_class", OPPONENT_CLASSES)
def test_blink_fox_pool_matches_each_opponent_class(opponent_class):
    _, player, _ = ready_blink_fox_game(opponent_class)
    source = player.give("GIL_827")

    pool = blink_fox_picker(source).find_cards(source)

    assert pool
    assert "CS2_182" not in pool
    assert all(opponent_class in cards.db[card_id].classes for card_id in pool)
    assert all(CardClass.NEUTRAL not in cards.db[card_id].classes for card_id in pool)


@pytest.mark.parametrize("opponent_class", OPPONENT_CLASSES)
def test_blink_fox_battlecry_generates_an_opponent_class_card(opponent_class):
    game, player, _ = ready_blink_fox_game(opponent_class)
    game.random.seed(17)
    source = player.give("GIL_827")

    source.play()

    generated = generated_by(player, source)
    assert len(generated) == 1
    assert opponent_class in generated[0].data.classes
    assert opponent_class in generated[0].classes
    assert CardClass.NEUTRAL not in generated[0].classes


def test_blink_fox_uses_original_class_after_neutral_hero_replacement():
    game, player, opponent = ready_blink_fox_game(CardClass.MAGE)
    if game.current_player is player:
        game.end_turn()

    majordomo = opponent.give("BRM_027")
    majordomo.play()
    majordomo.destroy()

    assert opponent.hero.card_class == CardClass.NEUTRAL
    assert opponent.starting_hero.card_class == CardClass.MAGE

    game.end_turn()
    source = player.give("GIL_827")
    pool = blink_fox_picker(source).find_cards(source)
    assert pool
    assert "CS2_182" not in pool
    assert all(CardClass.MAGE in cards.db[card_id].classes for card_id in pool)
    assert all(CardClass.NEUTRAL not in cards.db[card_id].classes for card_id in pool)

    source.play()
    generated = generated_by(player, source)
    assert len(generated) == 1
    assert CardClass.MAGE in generated[0].data.classes
    assert CardClass.MAGE in generated[0].classes
    assert CardClass.NEUTRAL not in generated[0].classes


@pytest.mark.parametrize("is_standard", [True, False], ids=["standard", "wild"])
def test_generated_scholomance_dual_class_card_keeps_runtime_membership_and_dump(
    monkeypatch, is_standard
):
    game, player, opponent = ready_blink_fox_game(CardClass.MAGE)
    player.is_standard = is_standard
    opponent.is_standard = is_standard
    source = player.give("GIL_827")
    assert "SCH_350" in blink_fox_picker(source).find_cards(source)

    def force_scholomance_card(self, source, **filters):
        return ["SCH_350"]

    monkeypatch.setattr(RandomCardPicker, "find_cards", force_scholomance_card)
    source.play()

    generated = generated_by(player, source)
    assert len(generated) == 1
    assert generated[0].classes == generated[0].data.classes
    assert generated[0].classes == [CardClass.MAGE, CardClass.ROGUE]
    assert generated[0].dump()["classes"] == [int(CardClass.MAGE), int(CardClass.ROGUE)]


def test_multiple_classes_without_legacy_group_use_card_data_membership():
    _, player, _ = ready_blink_fox_game(CardClass.MAGE)
    generated = player.give("TB_RoadToNR_Brann")

    assert generated.multi_class_group == MultiClassGroup.INVALID
    assert generated.classes == [CardClass.HUNTER, CardClass.WARRIOR]
    assert generated.classes == generated.data.classes
    assert generated.dump()["classes"] == [
        int(CardClass.HUNTER),
        int(CardClass.WARRIOR),
    ]


def test_runtime_class_membership_preserves_neutral_single_and_legacy_triple_cards():
    _, player, _ = ready_blink_fox_game(CardClass.MAGE)
    neutral = player.give("CS2_182")
    single_class = player.give("EX1_182")
    legacy_triple = player.give("CFM_321")

    assert neutral.classes == [CardClass.NEUTRAL]
    assert single_class.classes == [CardClass.ROGUE]
    assert legacy_triple.classes == MultiClassGroup.GRIMY_GOONS.card_classes


def test_runtime_single_class_membership_tracks_live_class_tag():
    _, player, _ = ready_blink_fox_game(CardClass.MAGE)
    card = player.give("EX1_182")

    card.tags[GameTag.CLASS] = CardClass.MAGE

    assert card.classes == [CardClass.MAGE]
