from collections import Counter

from hearthstone.enums import CardClass, Zone

from utils import MOONFIRE, TARGET_DUMMY, WISP, prepare_empty_game


DEATH_KNIGHT_CARDS = {f"ICC_314t{index}" for index in range(1, 9)}


def ready_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()

    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0

    return game, game.player1, game.player2


def shuffle_into_deck(player, *card_ids):
    cards = []
    for card_id in card_ids:
        card = player.give(card_id)
        card.shuffle_into_deck()
        cards.append(card)
    return cards


def test_lich_king_adds_one_death_knight_card_at_each_of_its_controller_turn_ends():
    game, owner, _ = ready_game()
    lich_king = owner.give("ICC_314").play()

    assert lich_king.taunt
    assert not owner.hand

    game.end_turn()
    assert len(owner.hand) == 1
    assert owner.hand[0].id in DEATH_KNIGHT_CARDS

    game.end_turn()
    assert len(owner.hand) == 1  # The opponent's turn end does not trigger it.

    game.end_turn()
    assert len(owner.hand) == 2
    assert all(card.id in DEATH_KNIGHT_CARDS for card in owner.hand)


def test_frostmourne_resummons_every_minion_killed_by_it_when_it_breaks():
    game, owner, opponent = ready_game()
    weapon = owner.give("ICC_314t1").play()
    victims = [opponent.summon(WISP) for _ in range(3)]

    for index, victim in enumerate(victims):
        if game.current_player is not owner:
            game.end_turn()
        owner.hero.attack(victim)
        assert victim.zone == Zone.GRAVEYARD
        if index < len(victims) - 1:
            game.end_turn()
            game.end_turn()

    assert weapon.zone == Zone.GRAVEYARD
    assert Counter(minion.id for minion in owner.field) == Counter({WISP: 3})


def test_army_of_the_dead_summons_each_milled_minion_and_mills_nonminions():
    _, owner, _ = ready_game()
    shuffle_into_deck(owner, WISP, TARGET_DUMMY, MOONFIRE, "CS2_029", "CS2_008")
    spell = owner.give("ICC_314t2")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert not owner.deck
    assert Counter(minion.id for minion in owner.field) == Counter(
        {WISP: 1, TARGET_DUMMY: 1}
    )


def test_army_of_the_dead_mills_and_summons_from_a_deck_with_fewer_than_five_cards():
    _, owner, _ = ready_game()
    shuffle_into_deck(owner, WISP, MOONFIRE)
    spell = owner.give("ICC_314t2")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert not owner.deck
    assert [minion.id for minion in owner.field] == [WISP]


def test_army_of_the_dead_mills_cards_but_respects_the_full_board_limit():
    _, owner, _ = ready_game()
    for _ in range(7):
        owner.summon(WISP)
    shuffle_into_deck(owner, TARGET_DUMMY)

    owner.give("ICC_314t2").play()

    assert not owner.deck
    assert len(owner.field) == 7
    assert all(minion.id == WISP for minion in owner.field)


def test_doom_pact_destroys_all_minions_then_mills_one_card_per_minion():
    _, owner, opponent = ready_game()
    owner.summon(WISP)
    owner.summon("CS2_231")
    opponent.summon("CS2_200")
    shuffle_into_deck(owner, MOONFIRE, "CS2_008", "CS2_029")
    spell = owner.give("ICC_314t3")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert not owner.field and not opponent.field
    assert not owner.deck


def test_doom_pact_mills_only_for_minions_it_actually_destroys():
    _, owner, opponent = ready_game()
    active_minion = owner.summon(WISP)
    dormant_minion = opponent.summon("BT_934")
    assert dormant_minion.dormant
    shuffle_into_deck(owner, MOONFIRE, "CS2_008")
    spell = owner.give("ICC_314t3")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert active_minion.zone == Zone.GRAVEYARD
    assert dormant_minion.zone == Zone.PLAY and dormant_minion.dormant
    assert len(owner.deck) == 1


def test_death_grip_takes_a_minion_from_the_enemy_deck_into_hand():
    _, owner, opponent = ready_game()
    shuffle_into_deck(opponent, WISP, MOONFIRE)
    spell = owner.give("ICC_314t4")

    spell.play()

    stolen = [card for card in owner.hand if card.id == WISP]
    assert spell.zone == Zone.GRAVEYARD
    assert len(stolen) == 1
    assert all(card.id != WISP for card in opponent.deck)
    assert [card.id for card in opponent.deck] == [MOONFIRE]


def test_death_grip_leaves_a_minionless_enemy_deck_untouched():
    _, owner, opponent = ready_game()
    shuffle_into_deck(opponent, MOONFIRE, "CS2_029")
    spell = owner.give("ICC_314t4")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert not owner.hand
    assert Counter(card.id for card in opponent.deck) == Counter(
        {MOONFIRE: 1, "CS2_029": 1}
    )


def test_death_coil_damages_an_enemy_character_and_heals_a_friendly_character():
    _, owner, opponent = ready_game()
    enemy_health = opponent.hero.health
    damage_spell = owner.give("ICC_314t5")

    damage_spell.play(target=opponent.hero)

    assert damage_spell.zone == Zone.GRAVEYARD
    assert opponent.hero.health == enemy_health - 5

    _, owner, _ = ready_game()
    for _ in range(5):
        owner.give(MOONFIRE).play(target=owner.hero)
    assert owner.hero.health == 25
    heal_spell = owner.give("ICC_314t5")

    heal_spell.play(target=owner.hero)

    assert heal_spell.zone == Zone.GRAVEYARD
    assert owner.hero.health == 30


def test_death_coil_damages_an_enemy_minion_and_heals_a_friendly_minion():
    _, owner, opponent = ready_game()
    enemy = opponent.summon("CS2_200")
    friendly = owner.summon("CS2_200")
    owner.give(MOONFIRE).play(target=friendly)
    assert friendly.health == 6

    owner.give("ICC_314t5").play(target=enemy)
    assert enemy.health == 2
    assert friendly.health == 6

    owner.give("ICC_314t5").play(target=friendly)
    assert friendly.health == 7
    assert enemy.health == 2


def test_obliterate_damages_its_controller_for_the_target_minions_current_health():
    _, owner, opponent = ready_game()
    target = opponent.summon("CS2_200")
    assert target.atk == 6
    for _ in range(5):
        owner.give(MOONFIRE).play(target=target)
    assert target.health == 2
    hero_health = owner.hero.health
    spell = owner.give("ICC_314t6")

    spell.play(target=target)

    assert spell.zone == Zone.GRAVEYARD
    assert target.zone == Zone.GRAVEYARD
    assert owner.hero.health == hero_health - 2


def test_anti_magic_shell_buffs_only_friendly_minions_and_grants_both_immunities():
    _, owner, opponent = ready_game()
    friendly = owner.summon(WISP)
    enemy = opponent.summon(WISP)
    spell = owner.give("ICC_314t7")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert (friendly.atk, friendly.health, friendly.max_health) == (3, 3, 3)
    assert friendly.cant_be_targeted_by_abilities
    assert friendly.cant_be_targeted_by_hero_powers
    assert (enemy.atk, enemy.health, enemy.max_health) == (1, 1, 1)

    spell = owner.give(MOONFIRE)
    assert friendly not in spell.targets
    assert enemy in spell.targets
    assert friendly not in owner.hero.power.targets
    assert enemy in owner.hero.power.targets


def test_death_and_decay_damages_all_enemy_characters_only():
    _, owner, opponent = ready_game()
    friendly = owner.summon("CS2_200")
    fragile_enemy = opponent.summon(WISP)
    durable_enemy = opponent.summon("CS2_200")
    friendly_health = friendly.health
    enemy_hero_health = opponent.hero.health
    spell = owner.give("ICC_314t8")

    spell.play()

    assert spell.zone == Zone.GRAVEYARD
    assert friendly.health == friendly_health
    assert fragile_enemy.zone == Zone.GRAVEYARD
    assert durable_enemy.zone == Zone.PLAY
    assert durable_enemy.health == 4
    assert opponent.hero.health == enemy_hero_health - 3
