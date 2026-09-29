"""Card-specific regressions for Kobolds & Catacombs red cards."""

from hearthstone.enums import CardClass, CardType, Zone

from utils import MOONFIRE, WISP, prepare_empty_game


def ready_game(hero_class=CardClass.SHAMAN):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def test_sapphire_spellstone_upgrades_after_three_overload_and_summons_two_copies():
    _, owner, opponent = ready_game()
    target = owner.summon("EX1_399")
    enemy = opponent.summon("EX1_399")
    stone = owner.give("LOOT_064")

    owner.give("LOOT_060").play(target=enemy)
    assert stone.zone == Zone.SETASIDE
    upgraded = [card for card in owner.hand if card.id == "LOOT_064t1"]
    assert len(upgraded) == 1

    upgraded[0].play(target=target)
    copies = [card for card in owner.field if card.id == target.id and card is not target]
    assert len(copies) == 2
    assert all(card.zone == Zone.PLAY for card in copies)


def test_sapphire_spellstone_ignores_deathrattle_plays():
    _, owner, _ = ready_game()
    stone = owner.give("LOOT_064")
    owner.give("EX1_399").play()
    assert stone.zone == Zone.HAND and stone.id == "LOOT_064"


def test_sapphire_spellstone_second_upgrade_summons_three_copies():
    _, owner, opponent = ready_game()
    target = owner.summon(WISP)
    first_enemy = opponent.summon("EX1_399")
    second_enemy = opponent.summon("EX1_399")
    owner.give("LOOT_064")
    owner.give("LOOT_060").play(target=first_enemy)
    assert len([card for card in owner.hand if card.id == "LOOT_064t1"]) == 1
    owner.give("LOOT_060").play(target=second_enemy)
    final = [card for card in owner.hand if card.id == "LOOT_064t2"]
    assert len(final) == 1
    owner.used_mana = 0
    final[0].play(target=target)
    assert [card.id for card in owner.field].count(WISP) == 4


def test_unstable_evolution_repeat_copy_expires_from_hand_at_turn_end():
    game, owner, _ = ready_game()
    game.random.seed(100)
    target = owner.summon(WISP)
    owner.give("LOOT_504").play(target=target)
    assert len(owner.field) == 1 and owner.field[0].cost == 1
    token = next(card for card in owner.hand if card.id == "LOOT_504t")
    token.play(target=owner.field[0])
    assert len(owner.field) == 1 and owner.field[0].cost == 2
    assert len([card for card in owner.hand if card.id == "LOOT_504t"]) == 1

    game.end_turn()
    assert not [card for card in owner.hand if card.id == "LOOT_504t"]


def test_valanyr_buffs_hand_minion_and_reequips_when_that_minion_dies():
    _, owner, _ = ready_game(CardClass.PALADIN)
    hand_minion = owner.give(WISP)
    board_minion = owner.summon("EX1_399")
    board_stats = (board_minion.atk, board_minion.max_health)
    weapon = owner.give("LOOT_500")
    weapon.play()
    owner.give("CS2_091").play()

    assert weapon.zone == Zone.GRAVEYARD
    assert hand_minion.zone == Zone.HAND
    assert (hand_minion.atk, hand_minion.max_health) == (5, 3)
    assert (board_minion.atk, board_minion.max_health) == board_stats
    hand_minion.play()
    owner.give(MOONFIRE).play(target=hand_minion)
    owner.give(MOONFIRE).play(target=hand_minion)
    owner.give(MOONFIRE).play(target=hand_minion)
    assert hand_minion.zone == Zone.GRAVEYARD
    assert owner.weapon is not None and owner.weapon.id == "LOOT_500"


def test_murmuring_elemental_doubles_next_battlecry_once():
    _, owner, opponent = ready_game()
    opponent.summon(WISP)
    owner.give("LOOT_517").play()
    assert owner.extra_battlecries
    owner.give("LOOT_367").play()
    assert owner.hero.armor == 4
    assert not owner.extra_battlecries
    owner.give("LOOT_367").play()
    assert owner.hero.armor == 6


def _runespear_choice_for(owner, opponent, card_id):
    weapon = owner.give("LOOT_506")
    weapon.play()
    owner.hero.attack(opponent.hero)
    choice = owner.choice
    assert choice is not None and len(choice.cards) == 3
    assert all(card.type == CardType.SPELL for card in choice.cards)
    selected = owner.card(card_id, zone=Zone.SETASIDE)
    # Hold the randomly rolled choice interface fixed while exercising its
    # real choose/callback/cast pipeline with a known spell.
    choice.cards = [selected]
    choice.choose(selected)
    return weapon, selected


def test_runespear_discovers_and_casts_target_spell_with_random_legal_target():
    _, owner, opponent = ready_game()
    friendly = owner.summon(WISP)
    weapon, spell = _runespear_choice_for(owner, opponent, "LOOT_064")

    assert spell.zone == Zone.GRAVEYARD
    assert owner.choice is None
    assert [card.id for card in owner.field].count(WISP) == 2
    assert weapon is owner.weapon and weapon.durability == 2
    assert friendly.zone == Zone.PLAY


def test_runespear_discovers_and_casts_nontarget_spell_without_hand_cast_trigger():
    _, owner, opponent = ready_game()
    friendly = owner.summon(WISP)
    wyrm = owner.summon("CFM_060")
    initial_attack = wyrm.atk
    _, spell = _runespear_choice_for(owner, opponent, "BT_101")

    assert spell.zone == Zone.GRAVEYARD
    assert owner.choice is None
    assert friendly.has_deathrattle
    assert wyrm.atk == initial_attack
    friendly.destroy()
    assert friendly.zone == Zone.GRAVEYARD
    assert [card.id for card in owner.field].count(WISP) == 1


def test_runespear_original_discover_option_is_cast_after_choice():
    game, owner, opponent = ready_game()
    game.random.seed(23)
    owner.summon("EX1_399")
    opponent.summon("EX1_399")
    owner.give("LOOT_506").play()
    owner.hero.attack(opponent.hero)
    choice = owner.choice
    assert choice is not None and len(choice.cards) == 3
    assert all(card.type == CardType.SPELL for card in choice.cards)
    selected = next(
        card for card in choice.cards if not card.requires_target() or card.targets
    )
    choice.choose(selected)
    assert selected.zone == Zone.GRAVEYARD
    assert owner.choice is None


def test_runespear_discover_choices_in_separate_games_keep_their_cast_callbacks():
    games = []
    for _ in range(2):
        _, owner, opponent = ready_game()
        target = owner.summon(WISP)
        owner.give("LOOT_506").play()
        owner.hero.attack(opponent.hero)
        choice = owner.choice
        assert choice is not None
        games.append((owner, target, choice))

    for owner, target, choice in games:
        spell = owner.card("BT_101", zone=Zone.SETASIDE)
        choice.cards = [spell]
        choice.choose(spell)
        assert owner.choice is None
        assert spell.zone == Zone.GRAVEYARD
        assert target.has_deathrattle
