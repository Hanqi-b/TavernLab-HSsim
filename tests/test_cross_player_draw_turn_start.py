"""Draws triggered at turn start count toward the new turn's player."""

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


def test_nat_extra_draw_counts_for_opponent_on_new_turn():
    observed_draw_counts = set()
    for seed in range(16):
        game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
        owner = game.current_player
        opponent = owner.opponent
        owner.summon("OG_338")
        deck_cards = [
            opponent.card("CS2_231", zone=Zone.DECK),
            opponent.card("CS2_182", zone=Zone.DECK),
        ]
        game.random.seed(seed)

        game.end_turn()

        drawn = sum(card.zone == Zone.HAND for card in deck_cards)
        assert drawn in (1, 2)
        assert len(opponent.deck) == 2 - drawn
        assert owner.cards_drawn_this_turn == 0
        assert opponent.cards_drawn_this_turn == drawn
        observed_draw_counts.add(drawn)

    assert observed_draw_counts == {1, 2}
