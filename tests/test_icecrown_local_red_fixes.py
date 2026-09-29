"""Targeted regressions for the ICECROWN card-local red fixes."""

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


def test_avalanche_freezes_target_and_damages_only_adjacent_minions():
    _, owner, opponent = ready_game(CardClass.SHAMAN)
    left = opponent.summon("EX1_399")
    target = opponent.summon("EX1_399")
    right = opponent.summon("EX1_399")
    before = (left.health, target.health, right.health)

    spell = owner.give("ICC_078")
    spell.play(target=target)

    assert spell.zone == Zone.GRAVEYARD
    assert target.zone == Zone.PLAY and target.frozen
    assert (left.health, target.health, right.health) == (
        before[0] - 3,
        before[1],
        before[2] - 3,
    )


def test_shadow_essence_summons_a_five_five_copy_and_keeps_deck_source():
    _, owner, _ = ready_game(CardClass.PRIEST)
    source_a = owner.give(WISP)
    source_a.shuffle_into_deck()
    source_b = owner.give("EX1_399")
    source_b.shuffle_into_deck()
    source_ids = {source_a.id, source_b.id}

    spell = owner.give("ICC_235")
    spell.play()

    summoned = list(owner.field)
    assert spell.zone == Zone.GRAVEYARD
    assert len(summoned) == 1
    assert summoned[0].id in source_ids
    assert (summoned[0].atk, summoned[0].health, summoned[0].max_health) == (5, 5, 5)
    assert source_a in owner.deck and source_b in owner.deck


def test_rotface_summons_legendary_only_after_surviving_damage():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    rotface = owner.summon("ICC_405")
    owner.give(MOONFIRE).play(target=rotface)

    legendary = [card for card in owner.field if card is not rotface]
    assert rotface.zone == Zone.PLAY and rotface.damage == 1
    assert len(legendary) == 1
    assert legendary[0].rarity == Rarity.LEGENDARY


def test_rotface_does_not_summon_after_lethal_damage():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    rotface = owner.summon("ICC_405")
    owner.give(FIREBALL).play(target=rotface)

    assert rotface.zone == Zone.GRAVEYARD
    assert not [card for card in owner.field if card.rarity == Rarity.LEGENDARY]


def test_valkyr_soulclaimer_summons_ghoul_only_after_surviving_damage():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    valkyr = owner.summon("ICC_408")
    owner.give(MOONFIRE).play(target=valkyr)

    ghouls = [card for card in owner.field if card.id == "ICC_900t"]
    assert valkyr.zone == Zone.PLAY and valkyr.damage == 1
    assert len(ghouls) == 1
    assert (ghouls[0].atk, ghouls[0].health) == (2, 2)


def test_valkyr_soulclaimer_does_not_summon_after_lethal_damage():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    valkyr = owner.summon("ICC_408")
    owner.give(FIREBALL).play(target=valkyr)

    assert valkyr.zone == Zone.GRAVEYARD
    assert not [card for card in owner.field if card.id == "ICC_900t"]


def test_crypt_lord_gains_health_after_any_friendly_summon_only():
    _, owner, opponent = ready_game(CardClass.DRUID)
    crypt = owner.give("ICC_808").play()
    before = (crypt.health, crypt.max_health)

    owner.summon(WISP)
    after_plain = (crypt.health, crypt.max_health)
    opponent.summon(WISP)
    after_enemy = (crypt.health, crypt.max_health)
    owner.summon("CS1_042")
    after_taunt = (crypt.health, crypt.max_health)

    assert after_plain == (before[0] + 1, before[1] + 1)
    assert after_enemy == after_plain
    assert after_taunt == (before[0] + 2, before[1] + 2)


def test_meat_wagon_requires_strictly_lower_attack_in_deck():
    _, owner, _ = ready_game()
    equal = owner.give(WISP)
    equal.shuffle_into_deck()
    wagon = owner.give("ICC_812").play()
    wagon_attack = wagon.atk
    wagon.destroy()

    assert wagon.zone == Zone.GRAVEYARD
    assert equal in owner.deck
    assert not [card for card in owner.field if card.id == WISP]
    assert equal.atk == wagon_attack

    _, owner, _ = ready_game()
    lower = owner.give("ICC_838t")
    lower.shuffle_into_deck()
    wagon = owner.give("ICC_812").play()
    wagon_attack = wagon.atk
    wagon.destroy()

    summoned = [card for card in owner.field if card.id == "ICC_838t"]
    assert len(summoned) == 1
    assert summoned[0].atk < wagon_attack
    assert lower not in owner.deck


def test_prince_valanar_gains_keywords_when_deck_has_no_four_cost_card():
    _, owner, _ = ready_game()
    blocker = owner.give("CS2_120")
    blocker.shuffle_into_deck()
    assert blocker.cost == 2

    prince = owner.give("ICC_853").play()

    assert prince.zone == Zone.PLAY
    assert prince.taunt and prince.lifesteal


def test_prince_valanar_does_not_gain_keywords_when_deck_has_four_cost_card():
    _, owner, _ = ready_game()
    blocker = owner.give("CS2_179")
    blocker.shuffle_into_deck()
    assert blocker.cost == 4

    prince = owner.give("ICC_853").play()

    assert prince.zone == Zone.PLAY
    assert not prince.taunt and not prince.lifesteal
