"""Targeted regressions for four Journey to Un'Goro card-local fixes."""

from hearthstone.enums import CardClass, CardType, Zone

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


def test_elder_longneck_adapts_for_a_five_attack_minion_in_hand():
    _, owner, _ = ready_game(CardClass.DRUID)
    held_minion = owner.give("UNG_086")
    assert held_minion.atk >= 5

    longneck = owner.give("UNG_109")
    longneck.play()

    assert longneck.zone == Zone.PLAY
    assert owner.choice is not None
    selected = owner.choice.cards[0]
    owner.choice.choose(selected)
    assert owner.choice is None
    assert [buff.id for buff in longneck.buffs] == [f"{selected.id}e"]


def test_elder_longneck_ignores_high_attack_minions_already_on_board():
    _, owner, _ = ready_game(CardClass.DRUID)
    board_minion = owner.summon("UNG_086")
    held_minion = owner.give(WISP)
    assert board_minion.atk >= 5 and held_minion.atk < 5

    longneck = owner.give("UNG_109")
    longneck.play()

    assert owner.choice is None
    assert longneck.zone == Zone.PLAY
    assert not longneck.buffs


def test_golakka_crawler_destroys_targeted_pirate_and_gains_exactly_one_one():
    _, owner, opponent = ready_game(CardClass.MAGE)
    pirate = opponent.summon("CS2_146")
    crawler = owner.give("UNG_807")

    crawler.play(target=pirate)

    assert pirate.zone == Zone.GRAVEYARD
    assert crawler.zone == Zone.PLAY
    assert (crawler.atk, crawler.max_health) == (3, 4)


def test_golakka_crawler_without_a_pirate_keeps_its_base_stats():
    _, owner, opponent = ready_game(CardClass.MAGE)
    ordinary = opponent.summon(WISP)
    crawler = owner.give("UNG_807")

    crawler.play(target=ordinary)

    assert ordinary.zone == Zone.PLAY
    assert crawler.zone == Zone.PLAY
    assert (crawler.atk, crawler.max_health) == (2, 3)


def test_primordial_drake_damages_every_other_minion_but_not_itself():
    _, owner, opponent = ready_game(CardClass.MAGE)
    friendly = owner.summon("CS2_182")
    enemy = opponent.summon("CS2_182")

    drake = owner.give("UNG_848")
    drake.play()

    assert friendly.zone == Zone.PLAY
    assert enemy.zone == Zone.PLAY
    assert friendly.health == friendly.max_health - 2
    assert enemy.health == enemy.max_health - 2
    assert (drake.health, drake.max_health) == (drake.max_health, drake.max_health)
    assert drake.taunt


def test_hallucination_offers_collectible_cards_of_the_actual_opponent_class():
    saw_nonspell = False
    for seed in range(417, 437):
        _, owner, opponent = ready_game(CardClass.ROGUE, CardClass.WARLOCK)
        owner.game.random.seed(seed)
        spell = owner.give("UNG_856")
        spell.play()

        assert owner.choice is not None
        offered = list(owner.choice.cards)
        assert len(offered) == 3
        assert all(
            card.data.collectible and opponent.hero.card_class in card.data.classes
            for card in offered
        )
        saw_nonspell |= any(CardType(card.type) != CardType.SPELL for card in offered)

        selected = offered[0]
        owner.choice.choose(selected)
        assert owner.choice is None
        assert selected.id in [card.id for card in owner.hand]
        assert spell.zone == Zone.GRAVEYARD

    assert saw_nonspell
