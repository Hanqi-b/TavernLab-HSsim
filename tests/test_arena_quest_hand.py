"""A legal Arena deck with multiple quests must still enter mulligan."""

from fireplace.controller import GameSession
from fireplace.web_gui.arena_factory import build_arena_game


def test_more_quests_than_starting_slots_do_not_break_game_start():
    game, human, _opponent = build_arena_game(
        seed=100_038,
        nickname="Quest tester",
        hero_id="HERO_08",
        deck=["ULD_433"] * 4 + ["CS2_231"] * 26,
        selected_sets=("UNGORO", "ULDUM", "GVG", "TGT", "OG", "NAXX"),
    )
    session = GameSession(game, {})
    try:
        session.start()
        assert len(human.starting_hand) == human.start_hand_size
    finally:
        session.close()
