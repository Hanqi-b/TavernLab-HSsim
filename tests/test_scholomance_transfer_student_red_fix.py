"""Transfer Student chooses its board variant at game start."""

import random

from hearthstone.enums import CardClass, Zone

from fireplace.enums import BoardEnum
from fireplace.player import Player
from utils import BaseTestGame


def fixed_board_game(board):
    class FixedBoardGame(BaseTestGame):
        def setup(self):
            super().setup()
            self.skin = board

    random.seed(401)
    owner = Player("Owner", ["SCH_199"] * 6, CardClass.MAGE.default_hero)
    opponent = Player("Opponent", [], CardClass.MAGE.default_hero)
    game = FixedBoardGame(players=(owner, opponent))
    game.random.seed(401)
    game.start()
    return game, owner, opponent


def test_transfer_student_becomes_orgrimmar_variant_in_hand_and_deck():
    game, owner, opponent = fixed_board_game(BoardEnum.ORGRIMMAR)
    cards = [c for c in owner.hand + owner.deck if c.id.startswith("SCH_199")]
    assert len(cards) == 6
    assert {c.id for c in cards} == {"SCH_199t2"}
    assert all(c.zone in (Zone.HAND, Zone.DECK) for c in cards)
    if game.current_player is not owner:
        game.end_turn()
    owner.max_mana = 10
    owner.used_mana = 0
    target = opponent.summon("CS2_182")
    card = next(c for c in owner.hand if c.id == "SCH_199t2")
    card.play(target=target)
    assert card.zone == Zone.PLAY and target.health == 3


def test_transfer_student_becomes_naxxramas_variant_in_hand_and_deck():
    _, owner, _ = fixed_board_game(BoardEnum.NAXXRAMAS)
    cards = [c for c in owner.hand + owner.deck if c.id.startswith("SCH_199")]
    assert len(cards) == 6
    assert {c.id for c in cards} == {"SCH_199t5"}
    assert all(c.zone in (Zone.HAND, Zone.DECK) for c in cards)
