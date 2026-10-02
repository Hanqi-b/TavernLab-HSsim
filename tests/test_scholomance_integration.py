"""A complete logged match exercises the new set through the decision API."""
import json

from hearthstone.enums import CardClass

from fireplace.action_log import ActionLog
from fireplace.agents import RandomAgent
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.replay import replay_action_log
from fireplace.replay_state import normalized_game_state


def test_scholomance_decision_match_replays_with_identical_state(tmp_path):
    deck = [
        "SCH_270", "SCH_310", "SCH_351", "SCH_352", "SCH_350",
        "SCH_400", "SCH_243", "SCH_241", "SCH_248", "SCH_199",
    ] * 2
    hero = CardClass.MAGE.default_hero
    players = (Player("A", deck[:], hero), Player("B", deck[:], hero))
    game = Game(players, seed=43)
    path = tmp_path / "scholomance-replay.json"
    log = ActionLog(game, output_path=path)
    agents = {p: RandomAgent(seed=seat + 100) for seat, p in enumerate(players)}
    GameSession(game, agents, action_log=log).run()
    saved = json.loads(path.read_text())
    assert saved["status"] == "complete"
    assert any(row["action"]["type"] == "CHOOSE" for row in saved["actions"])
    replayed = replay_action_log(path)
    assert normalized_game_state(replayed) == normalized_game_state(game)
