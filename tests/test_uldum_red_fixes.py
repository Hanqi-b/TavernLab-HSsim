"""Targeted regressions for the collectible Saviors of Uldum red cards."""

from hearthstone.enums import CardClass, CardType, Zone

from utils import MOONFIRE, WISP, prepare_empty_game


def ready_game(hero_class=CardClass.MAGE, opponent_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, opponent_class)
    owner = next(player for player in game.players if player.name == "Player1")
    opponent = next(player for player in game.players if player.name == "Player2")
    if game.current_player is not owner:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_resources = 20
        player.max_mana = 20
        player.used_mana = 0
    return game, owner, opponent


def test_untapped_potential_counts_only_turns_with_remaining_mana():
    game, owner, _ = ready_game(CardClass.DRUID)
    quest = owner.give("ULD_131")
    quest.play()

    owner.used_mana = owner.max_mana
    game.end_turn()
    game.end_turn()
    assert quest.progress == 0

    owner.max_mana = 10
    for expected in range(1, 5):
        owner.used_mana = 9
        game.end_turn()
        assert quest.progress == expected
        if expected < 4:
            game.end_turn()

    assert quest.zone == Zone.GRAVEYARD
    assert owner.hero.power.id == "ULD_131p"
    assert owner.choose_both


def test_crystal_merchant_draws_only_with_remaining_mana():
    for unspent in (False, True):
        game, owner, _ = ready_game(CardClass.DRUID)
        merchant = owner.summon("ULD_133")
        drawn = owner.card(WISP, zone=Zone.DECK)
        owner.used_mana = 0 if unspent else owner.max_mana

        game.end_turn()

        assert merchant.zone == Zone.PLAY
        assert drawn.zone == (Zone.HAND if unspent else Zone.DECK)


def test_supreme_archaeology_counts_real_draws_and_zeroes_reward_draw():
    game, owner, _ = ready_game(CardClass.WARLOCK)
    owner.max_hand_size = 30
    quest = owner.give("ULD_140")
    quest.play()
    for _ in range(20):
        owner.card(WISP, zone=Zone.DECK)
        owner.draw()

    assert quest.progress == 20
    assert quest.zone == Zone.GRAVEYARD
    assert owner.hero.power.id == "ULD_140p"

    owner.discard_hand()
    drawn = owner.card(WISP, zone=Zone.DECK)
    owner.used_mana = 0
    owner.hero.power.use()

    assert drawn.zone == Zone.HAND
    assert drawn.cost == 0


def test_diseased_vulture_triggers_only_for_owner_damage_on_owner_turn():
    game, owner, opponent = ready_game(CardClass.WARLOCK)
    vulture = owner.summon("ULD_167")
    before = owner.hero.health
    owner.give(MOONFIRE).play(target=owner.hero)
    summoned = [minion for minion in owner.field if minion is not vulture]

    assert owner.hero.health == before - 1
    assert len(summoned) == 1
    assert summoned[0].cost == 3

    game.end_turn()
    before_count = len(owner.field)
    before = owner.hero.health
    opponent.give(MOONFIRE).play(target=owner.hero)
    assert owner.hero.health == before - 1
    assert len(owner.field) == before_count


def test_reno_relicologist_hits_enemy_minions_only():
    game, owner, opponent = ready_game(CardClass.MAGE)
    before_hero = opponent.hero.health
    body = owner.give("ULD_238")
    body.play()
    assert opponent.hero.health == before_hero
    assert body.zone == Zone.PLAY

    target = opponent.summon("EX1_563")
    before = target.health
    owner.give("ULD_238").play()
    assert target.zone == Zone.PLAY
    assert target.health == before - 10
    assert opponent.hero.health == before_hero

    _, owner, opponent = ready_game(CardClass.MAGE)
    owner.card(WISP, zone=Zone.DECK)
    owner.card(WISP, zone=Zone.DECK)
    target = opponent.summon("CS2_182")
    owner.give("ULD_238").play()
    assert target.health == target.max_health
    assert opponent.hero.health == 30


def test_flame_ward_reveals_after_enemy_minion_attacks_owner_hero():
    game, owner, opponent = ready_game(CardClass.MAGE)
    secret = owner.give("ULD_239")
    secret.play()
    attacker = opponent.summon("CS2_182")
    other = opponent.summon("CS2_182")

    game.end_turn()
    attacker.attack(owner.hero)

    assert secret.zone == Zone.GRAVEYARD
    assert attacker.health == 2
    assert other.health == 2
    assert owner.hero.health == 26


def test_shadow_of_death_shuffles_three_shadows_and_summons_copy_on_draw():
    game, owner, opponent = ready_game(CardClass.ROGUE)
    target = opponent.summon("CS2_182")
    spell = owner.give("ULD_286")
    spell.play(target=target)
    shadows = [card for card in owner.deck if card.id == "ULD_286t"]
    assert len(shadows) == 3

    drawn = owner.draw()
    copies = [minion for minion in owner.field if minion.id == target.id]
    assert drawn.zone == Zone.GRAVEYARD
    # Cast-when-drawn replaces a draw. With a deck containing only Shadows,
    # the three Shadows chain into three summons on the same draw.
    assert not [card for card in owner.deck if card.id == "ULD_286t"]
    assert len([card for card in owner.graveyard if card.id == "ULD_286t"]) == 3
    assert len(copies) == 3
    assert all((copy.atk, copy.health) == (target.atk, target.max_health) for copy in copies)
    assert target.zone == Zone.PLAY
    assert spell.zone == Zone.GRAVEYARD


def test_corrupt_the_waters_unlocks_and_temporarily_doubles_battlecries():
    game, owner, _ = ready_game(CardClass.SHAMAN)
    quest = owner.give("ULD_291")
    quest.play()

    for expected in range(1, 7):
        body = owner.give("ULD_712")
        body.play()
        for minion in owner.field[:]:
            minion.destroy()
        assert quest.progress == expected
        if expected == 5:
            assert quest.zone == Zone.SECRET

    assert quest.zone == Zone.GRAVEYARD
    assert owner.hero.power.id == "ULD_291p"

    owner.used_mana = 0
    owner.hero.power.use()
    assert owner.extra_battlecries
    target = owner.summon(WISP)
    sidekick = owner.give("ULD_191")
    sidekick.play(target=target)
    assert target.max_health == 5

    game.end_turn()
    assert not owner.extra_battlecries


def test_oasis_surger_resolves_each_choose_one_branch():
    _, owner, _ = ready_game(CardClass.DRUID)
    buffed = owner.give("ULD_292")
    buffed.play(choose="ULD_292a")
    assert (buffed.atk, buffed.health, buffed.rush) == (5, 5, True)

    _, owner, _ = ready_game(CardClass.DRUID)
    copied = owner.give("ULD_292")
    copied.play(choose="ULD_292b")
    copies = [minion for minion in owner.field if minion.id == "ULD_292"]
    assert len(copies) == 2
    assert all((minion.atk, minion.health, minion.rush) == (3, 3, True) for minion in copies)


def test_bazaar_burglary_counts_each_other_class_card_added():
    _, owner, opponent = ready_game(CardClass.ROGUE)
    quest = owner.give("ULD_326")
    quest.play()

    opponent.give("CS2_004")
    assert quest.progress == 0

    first = owner.give("ULD_328")
    first.play()
    assert quest.progress == 2
    second = owner.give("ULD_328")
    second.play()

    added = list(owner.hand)
    assert quest.progress == 4
    assert quest.zone == Zone.GRAVEYARD
    assert owner.hero.power.id == "ULD_326p"
    assert len(added) == 4
    assert all(card.type == CardType.SPELL for card in added)
    assert all(card.card_class not in (CardClass.ROGUE, CardClass.NEUTRAL) for card in added)

    owner.used_mana = 0
    owner.hero.power.use()
    assert owner.weapon is not None
    assert owner.weapon.id == "ULD_326t"
    assert (owner.weapon.atk, owner.weapon.durability) == (3, 2)


def test_clever_disguise_adds_two_spells_from_other_classes():
    _, owner, _ = ready_game(CardClass.ROGUE)
    before = len(owner.hand)
    body = owner.give("ULD_328")
    body.play()
    added = list(owner.hand)

    assert len(added) == before + 2
    assert body.zone == Zone.GRAVEYARD
    assert all(card.type == CardType.SPELL for card in added)
    assert all(card.card_class not in (CardClass.ROGUE, CardClass.NEUTRAL) for card in added)


def test_mogu_cultist_clears_full_board_before_summoning_ra():
    game, owner, _ = ready_game()
    cultists = [owner.summon("ULD_705") for _ in range(6)]
    last = owner.give("ULD_705")
    last.play()
    ra = [minion for minion in owner.field if minion.id == "ULD_705t"]

    assert all(cultist.zone == Zone.GRAVEYARD for cultist in cultists + [last])
    assert len(ra) == 1
    assert ra[0].zone == Zone.PLAY

    game2, owner2, _ = ready_game()
    cultists2 = [owner2.summon("ULD_705") for _ in range(5)]
    last2 = owner2.give("ULD_705")
    last2.play()
    assert all(cultist.zone == Zone.PLAY for cultist in cultists2 + [last2])
    assert not [minion for minion in owner2.field if minion.id == "ULD_705t"]


def test_blatant_decoy_summons_lowest_cost_minion_for_each_player():
    _, owner, opponent = ready_game()
    own_low = owner.give("EX1_116")
    own_high = owner.give("EX1_414")
    enemy_low = opponent.give("EX1_116")
    enemy_high = opponent.give("EX1_414")
    assert own_low.cost < own_high.cost and own_low.atk > own_high.atk

    body = owner.give("ULD_706")
    body.play()
    body.destroy()

    assert own_low.zone == Zone.PLAY
    assert own_high.zone == Zone.HAND
    assert enemy_low.zone == Zone.PLAY
    assert enemy_high.zone == Zone.HAND


def test_activate_the_obelisk_counts_actual_healing_and_upgrades_power():
    _, owner, _ = ready_game(CardClass.PRIEST)
    quest = owner.give("ULD_724")
    quest.play()
    owner.hero.hit(15)

    progress = []
    for _ in range(3):
        owner.used_mana = 0
        owner.give("CS2_089").play(target=owner.hero)
        progress.append(quest.progress)

    assert progress == [6, 12, 15]
    assert quest.zone == Zone.GRAVEYARD
    assert owner.hero.power.id == "ULD_724p"

    minion = owner.summon("CS2_182")
    minion.damage = 1
    owner.used_mana = 0
    owner.hero.power.use(target=minion)
    assert (minion.atk, minion.health) == (7, 8)
