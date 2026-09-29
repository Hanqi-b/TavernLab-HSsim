"""Targeted regressions for Karazhan collectible cards formerly graded RED."""

from hearthstone.enums import CardClass, CardType, Zone

from fireplace.dsl.random_picker import RandomSpell
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


def test_babbling_book_adds_exactly_one_mage_spell_to_hand():
    _, player, _ = ready_game(CardClass.WARRIOR)
    pool = RandomSpell(card_class=CardClass.MAGE).find_cards(player.give("KAR_009"))
    assert pool
    assert all(player.card(card_id).card_class == CardClass.MAGE for card_id in pool)

    for seed in range(8):
        game, player, _ = ready_game(CardClass.WARRIOR)
        game.random.seed(seed)
        book = player.give("KAR_009")
        book.play()
        assert book.zone == Zone.PLAY
        assert len(player.hand) == 1
        generated = player.hand[0]
        assert generated.type == CardType.SPELL
        assert generated.card_class == CardClass.MAGE
        assert generated.zone == Zone.HAND


def test_cat_trick_consumes_secret_once_after_enemy_spell():
    game, owner, opponent = ready_game()
    secret = owner.give("KAR_004")
    secret.play()
    assert secret.zone == Zone.SECRET and secret in owner.secrets

    owner.give("CS2_008").play(target=opponent.hero)
    assert secret.zone == Zone.SECRET and not owner.field

    game.end_turn()
    opponent.give("CS2_008").play(target=owner.hero)
    panthers = [card for card in owner.field if card.id == "KAR_004a"]
    assert secret.zone == Zone.GRAVEYARD
    assert secret not in owner.secrets
    assert len(panthers) == 1
    assert (panthers[0].atk, panthers[0].max_health, panthers[0].stealthed) == (4, 2, True)

    opponent.give("CS2_008").play(target=owner.hero)
    assert sum(card.id == "KAR_004a" for card in owner.field) == 1


def test_cat_trick_full_board_still_consumes_secret():
    game, owner, opponent = ready_game()
    for _ in range(7):
        owner.summon("CS2_231")
    secret = owner.give("KAR_004")
    secret.play()
    game.end_turn()
    opponent.give("CS2_008").play(target=owner.hero)
    assert secret.zone == Zone.GRAVEYARD
    assert secret not in owner.secrets
    assert len(owner.field) == 7
    assert not any(card.id == "KAR_004a" for card in owner.field)
