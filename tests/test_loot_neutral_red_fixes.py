"""Targeted regressions for the card-local LOOTAPALOOZA red fixes.

Each test builds a fresh live Fireplace game and checks the state that the
card text promises.  The tests intentionally keep the fixtures small so a
failure identifies the card-local selector or condition that regressed.
"""

from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction

from utils import FIREBALL, WISP, prepare_empty_game


def ready_game(player_class=CardClass.MAGE, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(player_class, opponent_class)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_ironwood_golem_uses_hero_armor_for_attack_threshold():
    game, owner, opponent = ready_game(CardClass.DRUID)
    golem = owner.give("LOOT_048").play()
    control = owner.summon(WISP)
    target = opponent.summon("EX1_399")

    game.end_turn()
    game.end_turn()
    assert not golem.can_attack()
    assert control.can_attack()

    owner.give("LOOT_047").play(target=golem)
    assert owner.hero.armor == 3
    assert golem.taunt
    assert golem.can_attack()
    golem.attack(opponent.hero)
    assert opponent.hero.health == 30 - golem.atk
    assert target.zone == Zone.PLAY


def test_ebon_dragonsmith_reduces_only_a_weapon_and_has_no_weapon_noop():
    game, owner, _ = ready_game()
    weapon = owner.give("LOOT_108")
    minion = owner.give("CS2_182")
    before = (weapon.cost, minion.cost)

    smith = owner.give("LOOT_118").play()

    assert smith.zone == Zone.PLAY
    assert weapon.cost == before[0] - 2
    assert minion.cost == before[1]

    game2, owner2, _ = ready_game()
    minion_only = owner2.give("CS2_182")
    before_minion = minion_only.cost
    smith2 = owner2.give("LOOT_118").play()

    assert smith2.zone == Zone.PLAY
    assert minion_only.cost == before_minion


def test_lone_champion_gains_keywords_only_when_alone():
    _, owner, _ = ready_game()
    champion = owner.give("LOOT_124").play()
    assert champion.taunt and champion.divine_shield

    _, owner, _ = ready_game()
    other = owner.summon(WISP)
    champion = owner.give("LOOT_124").play()
    assert other.zone == Zone.PLAY
    assert not champion.taunt
    assert not champion.divine_shield


def test_kobold_apprentice_splits_damage_across_all_enemy_characters():
    _, owner, opponent = ready_game()
    friendly = owner.summon("EX1_399")
    enemies = [opponent.summon("EX1_399"), opponent.summon("CS2_182")]
    before = [minion.health for minion in enemies]
    hero_before = opponent.hero.health

    apprentice = owner.give("LOOT_347").play()

    minion_damage = sum(before[i] - enemies[i].health for i in range(2))
    hero_damage = hero_before - opponent.hero.health
    assert apprentice.zone == Zone.PLAY
    assert minion_damage + hero_damage == 3
    assert friendly.damage == 0

    _, owner, opponent = ready_game()
    apprentice = owner.give("LOOT_347").play()
    assert apprentice.zone == Zone.PLAY
    assert opponent.hero.health == 27
    assert not opponent.field


def test_gemstudded_golem_uses_hero_armor_for_attack_threshold():
    game, owner, opponent = ready_game(CardClass.WARRIOR)
    golem = owner.summon("LOOT_365")
    control = owner.summon("CS2_182")
    target = opponent.summon("EX1_399")

    game.end_turn()
    game.end_turn()
    control.attack(target)
    assert target.damage == control.atk
    with_invalid_attack = None
    try:
        golem.attack(target)
    except InvalidAction:
        with_invalid_attack = True
    assert with_invalid_attack

    game2, owner2, opponent2 = ready_game(CardClass.WARRIOR)
    golem2 = owner2.summon("LOOT_365")
    control2 = owner2.summon("CS2_182")
    target2 = opponent2.summon("EX1_399")
    owner2.give("EX1_606").play()
    game2.end_turn()
    game2.end_turn()
    assert owner2.hero.armor == 5
    control2.attack(target2)
    golem2.attack(target2)
    assert target2.zone == Zone.GRAVEYARD
    assert golem2.zone == Zone.PLAY


def test_master_oakheart_recruits_by_attack_not_cost():
    _, owner, _ = ready_game(CardClass.WARRIOR)
    cost_decoys = [owner.give(card_id) for card_id in ("CS2_059", "FP1_007", "DRG_010")]
    attack_matches = [owner.give(card_id) for card_id in (WISP, "CS2_119", "AT_006")]
    for card in cost_decoys + attack_matches:
        card.shuffle_into_deck()

    oakheart = owner.give("LOOT_521").play()

    recruited = [minion for minion in owner.field if minion is not oakheart]
    assert oakheart.zone == Zone.PLAY
    assert sorted(minion.atk for minion in recruited) == [1, 2, 3]
    assert all(minion.zone == Zone.PLAY for minion in recruited)
    assert all(card in owner.deck for card in cost_decoys)
    assert all(card not in owner.deck for card in attack_matches)


def test_darkness_shuffles_candles_into_opponent_deck():
    _, owner, opponent = ready_game()
    darkness = owner.give("LOOT_526").play()

    assert darkness.zone == Zone.PLAY
    assert darkness.dormant
    assert darkness.progress == 0
    assert sum(card.id == "LOOT_526t" for card in opponent.deck) == 3
    assert not any(card.id == "LOOT_526t" for card in owner.deck)


def test_darkness_awakens_after_three_actual_opponent_candle_draws():
    game, owner, opponent = ready_game()
    for _ in range(6):
        owner.summon(WISP)
    darkness = owner.give("LOOT_526").play()
    assert len(owner.field) == 7

    candles = []
    draw_sequence = []
    for _ in range(3):
        candle = opponent.card("LOOT_526t", source=darkness)
        candles.append(candle)
        draw_sequence.extend((candle, opponent.card(WISP)))
    for card in draw_sequence:
        card.zone = Zone.DECK
    opponent.deck[:] = list(reversed(draw_sequence))

    states = []
    for index in range(1, 4):
        drawn = opponent.draw()
        states.append((drawn.id, darkness.progress, darkness.dormant, len(owner.field)))
        assert drawn.id == "LOOT_526t"
        assert darkness.progress == index
        assert darkness.dormant is (index < 3)
        assert len(owner.field) == 7

    assert all(candle.zone != Zone.DECK for candle in candles)
    assert len([card for card in opponent.hand if card.id == WISP]) == 3
    assert darkness.zone == Zone.PLAY
    assert states[-1][2] is False


def test_leyline_manipulator_reduces_only_nonstarting_hand_cards():
    _, owner, _ = ready_game(CardClass.MAGE)
    starting = owner.give("CS2_200")
    owner.starting_deck = [starting]
    generated = owner.give(FIREBALL)
    before = (starting.cost, generated.cost)

    manipulator = owner.give("LOOT_537").play()

    assert manipulator.zone == Zone.PLAY
    assert starting.cost == before[0]
    assert generated.cost == before[1] - 2
    assert starting in owner.hand and generated in owner.hand


def test_leyline_manipulator_does_not_change_starting_deck_only_hand():
    _, owner, _ = ready_game(CardClass.MAGE)
    starting = owner.give("CS2_200")
    owner.starting_deck = [starting]
    before = starting.cost

    manipulator = owner.give("LOOT_537").play()

    assert manipulator.zone == Zone.PLAY
    assert starting.cost == before
    assert starting in owner.hand
