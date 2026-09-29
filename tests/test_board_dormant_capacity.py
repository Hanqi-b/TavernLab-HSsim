from hearthstone.enums import CardClass, Zone

from utils import FIREBALL, WISP, prepare_empty_game

from fireplace.cards.utils import ENEMY_BOARD_MINIONS, FULL_BOARD, FRIENDLY_BOARD_MINIONS
from fireplace.dsl import FRIENDLY_MINIONS


def _game_with_board(active_count, dormant=False):
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    for _ in range(active_count):
        player.give(WISP).play()
    dormant_card = None
    if dormant:
        dormant_card = player.give("BT_934").play()
    return game, player, dormant_card


def test_full_board_counts_dormant_without_changing_target_selector():
    game, player, dormant = _game_with_board(6, dormant=True)

    assert len(player.field) == 7
    assert dormant.dormant
    assert len(FRIENDLY_MINIONS.eval(game, player)) == 6
    assert len(FRIENDLY_BOARD_MINIONS.eval(game, player)) == 7
    assert FULL_BOARD.check(player)


def test_full_board_still_counts_seven_active_minions():
    game, player, dormant = _game_with_board(7)

    assert dormant is None
    assert len(player.field) == 7
    assert len(FRIENDLY_BOARD_MINIONS.eval(game, player)) == 7
    assert FULL_BOARD.check(player)


def test_one_free_slot_is_not_full_with_a_dormant_occupant():
    game, player, dormant = _game_with_board(5, dormant=True)

    assert len(player.field) == 6
    assert dormant.dormant
    assert len(FRIENDLY_BOARD_MINIONS.eval(game, player)) == 6
    assert not FULL_BOARD.check(player)


def test_secret_summon_branch_stays_set_when_dormant_fills_seventh_slot():
    game, player, dormant = _game_with_board(6, dormant=True)
    secret = player.give("BT_003").play()

    game.end_turn()
    game.player2.give(FIREBALL).play(target=player.hero)

    assert len(player.field) == 7
    assert dormant in player.field
    assert secret.zone == Zone.SECRET
    assert secret in player.secrets


def test_secret_summon_branch_uses_the_open_slot():
    game, player, dormant = _game_with_board(5, dormant=True)
    secret = player.give("BT_003").play()

    game.end_turn()
    game.player2.give(FIREBALL).play(target=player.hero)

    assert len(player.field) == 7
    assert dormant in player.field
    assert secret.zone == Zone.GRAVEYARD
    assert secret not in player.secrets


def test_spreading_plague_stops_after_filling_slot_behind_dormant_minion():
    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    player = game.player1
    opponent = game.player2

    for _ in range(5):
        player.give(WISP).play()
    dormant = player.give("BT_934").play()
    for _ in range(7):
        opponent.summon(WISP)
    player.used_mana = 0

    player.give("ICC_054").play()

    scarabs = [minion for minion in player.field if minion.id == "ICC_832t4"]
    assert dormant in player.field
    assert len(player.field) == 7
    assert len(scarabs) == 1


def test_spreading_plague_counts_enemy_dormant_minion_when_repeating():
    game = prepare_empty_game(CardClass.DRUID, CardClass.DRUID)
    player = game.player1
    opponent = game.player2
    for _ in range(6):
        opponent.summon(WISP)
    game.end_turn()
    dormant = opponent.give("BT_934").play()
    game.end_turn()
    assert dormant.dormant
    assert len(ENEMY_BOARD_MINIONS.eval(game, player)) == 7

    player.used_mana = 0
    player.give("ICC_054").play()

    assert len(player.field) == 7
    assert [card.id for card in player.field].count("ICC_832t4") == 7
