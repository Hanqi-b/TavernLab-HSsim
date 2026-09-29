"""Per-card regressions for Un'Goro Adapt and discard-history failures."""

from hearthstone.enums import CardClass, Zone

from fireplace.enums import DISCARDED
from utils import prepare_empty_game


def ready_game(hero_class=CardClass.MAGE):
    game = prepare_empty_game(hero_class, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    return game, game.player1, game.player2


def resolve_adapt_once(owner):
    choice = owner.choice
    assert choice is not None and len(choice.cards) == 3
    selected = choice.cards[0]
    choice.choose(selected)
    assert owner.choice is None
    return selected.id + "e"


def test_gentle_megasaur_adapts_all_and_only_friendly_murlocs():
    _, owner, opponent = ready_game(CardClass.SHAMAN)
    murlocs = [owner.summon("CS2_168"), owner.summon("EX1_506")]
    ordinary = owner.summon("CS2_231")
    enemy_murloc = opponent.summon("CS2_168")
    megasaur = owner.give("UNG_089")
    megasaur.play()
    chosen_buff = resolve_adapt_once(owner)

    assert megasaur.zone == Zone.PLAY
    assert all(sum(buff.id == chosen_buff for buff in murloc.buffs) == 1 for murloc in murlocs)
    assert not ordinary.buffs and not enemy_murloc.buffs


def test_evolving_spores_uses_one_choice_for_all_friendly_minions():
    _, owner, opponent = ready_game(CardClass.DRUID)
    friendly = [owner.summon("CS2_231"), owner.summon("CS2_182")]
    enemy = opponent.summon("CS2_231")
    spores = owner.give("UNG_103")
    spores.play()
    chosen_buff = resolve_adapt_once(owner)

    assert spores.zone == Zone.GRAVEYARD
    assert all(sum(buff.id == chosen_buff for buff in minion.buffs) == 1 for minion in friendly)
    assert not enemy.buffs


def test_lightfused_stegodon_adapts_every_recruit_once():
    _, owner, _ = ready_game(CardClass.PALADIN)
    owner.give("UNG_960").play()
    recruits = [minion for minion in owner.field if minion.id == "CS2_101t"]
    assert len(recruits) == 2
    stegodon = owner.give("UNG_962")
    stegodon.play()
    chosen_buff = resolve_adapt_once(owner)

    assert stegodon.zone == Zone.PLAY and not stegodon.buffs
    assert all(sum(buff.id == chosen_buff for buff in recruit.buffs) == 1 for recruit in recruits)


def test_lightfused_stegodon_without_recruits_offers_no_choice():
    _, owner, _ = ready_game(CardClass.PALADIN)
    stegodon = owner.give("UNG_962")
    stegodon.play()
    assert stegodon.zone == Zone.PLAY and owner.choice is None


def test_single_target_twice_adapt_still_offers_two_separate_choices():
    _, owner, _ = ready_game()
    volcanosaur = owner.give("UNG_002")
    volcanosaur.play()
    assert owner.choice is not None
    first = owner.choice.cards[0]
    owner.choice.choose(first)
    assert owner.choice is not None
    second = owner.choice.cards[0]
    owner.choice.choose(second)
    assert owner.choice is None
    assert sum(buff.id == first.id + "e" for buff in volcanosaur.buffs) >= 1
    assert sum(buff.id == second.id + "e" for buff in volcanosaur.buffs) >= 1


def test_lakkari_sacrifice_counts_six_real_discards_and_opens_portal():
    game, owner, _ = ready_game(CardClass.WARLOCK)
    quest = owner.give("UNG_829")
    quest.play()
    assert quest.zone == Zone.SECRET and quest.progress == 0

    for batch in range(3):
        fillers = [owner.give("CS2_231"), owner.give("CS2_029")]
        felhound = owner.give("UNG_833")
        felhound.play()
        assert felhound.zone == Zone.PLAY
        assert all(card.zone == Zone.REMOVEDFROMGAME and card.tags.get(DISCARDED) for card in fillers)
        assert quest.progress == (batch + 1) * 2
        if batch == 1:
            game.end_turn()
            game.end_turn()

    assert quest.zone == Zone.GRAVEYARD
    reward = next(card for card in owner.hand if card.id == "UNG_829t1")
    reward.play()
    assert reward.zone == Zone.GRAVEYARD
    portal = next(card for card in owner.field if card.id == "UNG_829t2")
    assert portal.dormant and portal.zone == Zone.PLAY
    game.end_turn()
    imps = [card for card in owner.field if card.id == "UNG_829t3"]
    assert len(imps) == 2 and all(card.zone == Zone.PLAY for card in imps)


def test_cruel_dinomancer_summons_a_copy_of_discarded_minion():
    _, owner, opponent = ready_game(CardClass.WARLOCK)
    discarded = owner.give("CS2_231")
    owner.give("EX1_308").play(target=opponent.hero)
    assert discarded.zone == Zone.REMOVEDFROMGAME and discarded.tags.get(DISCARDED)
    dinomancer = owner.give("UNG_830")
    dinomancer.play()
    dinomancer.destroy()

    summoned = [card for card in owner.field if card.id == "CS2_231"]
    assert dinomancer.zone == Zone.GRAVEYARD
    assert len(summoned) == 1
    assert summoned[0] is not discarded
    assert (summoned[0].atk, summoned[0].health) == (1, 1)
    assert discarded.zone == Zone.REMOVEDFROMGAME


def test_cruel_dinomancer_without_discarded_minion_summons_nothing():
    _, owner, _ = ready_game(CardClass.WARLOCK)
    dinomancer = owner.give("UNG_830")
    dinomancer.play()
    dinomancer.destroy()
    assert dinomancer.zone == Zone.GRAVEYARD
    assert not owner.field


def test_discard_history_is_visible_to_blood_queen_lanathel():
    game, owner, opponent = ready_game(CardClass.WARLOCK)
    base_attack = owner.card("ICC_841").atk
    for card_id in ("CS2_231", "CS2_029"):
        card = owner.give(card_id)
        owner.give("EX1_308").play(target=opponent.hero)
        assert card.zone == Zone.REMOVEDFROMGAME
    queen = owner.give("ICC_841")
    queen.play()
    assert queen.atk == base_attack + 2
    late_discard = owner.give("CS2_231")
    owner.give("EX1_308").play(target=opponent.hero)
    assert late_discard.zone == Zone.REMOVEDFROMGAME
    assert queen.atk == base_attack + 3
    game.end_turn()
    enemy_discard = opponent.give("CS2_231")
    opponent.give("EX1_308").play(target=owner.hero)
    assert enemy_discard.zone == Zone.REMOVEDFROMGAME
    assert queen.atk == base_attack + 3


def test_soulwarden_recovers_three_distinct_discarded_cards():
    _, owner, opponent = ready_game(CardClass.WARLOCK)
    discarded = []
    for card_id in ("CS2_231", "CS2_029", "CS2_182"):
        card = owner.give(card_id)
        owner.give("EX1_308").play(target=opponent.hero)
        assert card.zone == Zone.REMOVEDFROMGAME
        discarded.append(card)
    soulwarden = owner.give("TRL_247")
    soulwarden.play()
    assert soulwarden.zone == Zone.PLAY
    assert sorted(card.id for card in owner.hand) == sorted(card.id for card in discarded)
    assert all(card.zone == Zone.REMOVEDFROMGAME for card in discarded)
