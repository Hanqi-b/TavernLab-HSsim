"""A complete decision log must reconstruct the same game from its start."""

import copy
import json

import pytest
from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.action_log import ActionLog
from fireplace.agents import RandomAgent
from fireplace.agent_api import Action
from fireplace.controller import GameSession, decision_player
from fireplace.game import Game
from fireplace.player import Player
from fireplace.replay import ReplayError, replay_action_log
from fireplace.replay_state import code_signature, normalized_game_state
from fireplace.utils import setup_game
from fireplace.exceptions import GameOver


cards.db.initialize()


def recorded_match(tmp_path, *, deck=None, seed=19, consume_before_start=False,
                   first_hand_size=None):
    deck = deck or ["CS2_231"] * 5
    hero = CardClass.MAGE.default_hero
    players = (Player("Alpha", deck[:], hero), Player("Beta", deck[:], hero))
    if first_hand_size is not None:
        players[0]._start_hand_size = first_hand_size
    game = Game(players, seed=seed)
    if consume_before_start:
        game.random.random()
        game.random.random()
    path = tmp_path / "replay.json"
    log = ActionLog(game, output_path=path)
    agents = {player: RandomAgent(seed=seat + 100) for seat, player in enumerate(players)}
    GameSession(game, agents, action_log=log).run()
    return game, path, json.loads(path.read_text(encoding="utf-8"))


def test_complete_log_replays_from_json_and_matches_state(tmp_path):
    original, path, saved = recorded_match(tmp_path, consume_before_start=True)
    replayed = replay_action_log(path)
    replayed_again = replay_action_log(saved)
    expected = normalized_game_state(original)
    assert normalized_game_state(replayed) == expected
    assert normalized_game_state(replayed_again) == expected
    assert replayed.manager.observers == []
    assert replayed_again.manager.observers == []
    assert saved["replay"]["final_state"] == expected
    assert saved["seed"] == 19


def test_concede_log_replays_as_a_terminal_action(tmp_path):
    hero = CardClass.MAGE.default_hero
    players = (Player("Alpha", ["CS2_231"] * 5, hero),
               Player("Beta", ["CS2_231"] * 5, hero))
    game = Game(players, seed=23)
    path = tmp_path / "concede-replay.json"
    log = ActionLog(game, output_path=path)
    session = GameSession(game, {}, action_log=log)
    session.start()
    player = decision_player(session.game)
    with pytest.raises(GameOver):
        session.execute(player, Action(type="CONCEDE"))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["status"] == "complete"
    assert saved["actions"][-1]["action"] == {
        "schema_version": 1,
        "type": "CONCEDE",
    }
    replayed = replay_action_log(saved)
    assert normalized_game_state(replayed) == normalized_game_state(game)


def test_replay_rejects_changed_code_and_action(tmp_path):
    _, _, saved = recorded_match(tmp_path)
    changed = copy.deepcopy(saved)
    changed["replay"]["code_signature"] = "wrong"
    with pytest.raises(ReplayError, match="code or dependency"):
        replay_action_log(changed)

    changed = copy.deepcopy(saved)
    changed["actions"][0]["action"] = {"schema_version": 1, "type": "END_TURN"}
    with pytest.raises(ReplayError, match="Action 1 diverged"):
        replay_action_log(changed)


def test_replay_rejects_log_without_prestart_snapshot(tmp_path):
    _, _, saved = recorded_match(tmp_path)
    saved.pop("replay")
    with pytest.raises(ReplayError, match="replay metadata"):
        replay_action_log(saved)


def test_replay_rejects_changed_initial_deck(tmp_path):
    _, _, saved = recorded_match(tmp_path)
    saved["players"][0]["deck_card_ids"][0] = "CS2_029"
    with pytest.raises(ReplayError, match="setup diverged"):
        replay_action_log(saved)


def test_code_signature_ignores_presentation_only_sources(tmp_path):
    (tmp_path / "game.py").write_text("RULE_VERSION = 1\n", encoding="utf-8")
    cards_root = tmp_path / "cards"
    cards_root.mkdir()
    (cards_root / "CardDefs.xml").write_text("<cards />\n", encoding="utf-8")
    web_root = tmp_path / "web_gui"
    web_root.mkdir()
    web_file = web_root / "server.py"
    web_file.write_text("PRESENTATION_VERSION = 1\n", encoding="utf-8")

    before = code_signature(source_root=tmp_path)
    web_file.write_text("PRESENTATION_VERSION = 2\n", encoding="utf-8")

    assert code_signature(source_root=tmp_path) == before


def test_code_signature_includes_engine_and_card_changes(tmp_path):
    game_file = tmp_path / "game.py"
    game_file.write_text("RULE_VERSION = 1\n", encoding="utf-8")
    cards_root = tmp_path / "cards"
    cards_root.mkdir()
    card_defs = cards_root / "CardDefs.xml"
    card_defs.write_text("<cards />\n", encoding="utf-8")

    baseline = code_signature(source_root=tmp_path)["source_sha256"]
    game_file.write_text("RULE_VERSION = 2\n", encoding="utf-8")
    engine_changed = code_signature(source_root=tmp_path)["source_sha256"]
    assert engine_changed != baseline

    card_defs.write_text("<cards version=\"2\" />\n", encoding="utf-8")
    assert code_signature(source_root=tmp_path)["source_sha256"] != engine_changed


def test_seed_controls_random_class_and_deck_setup():
    first = setup_game(seed=73, start=False)
    second = setup_game(seed=73, start=False)
    assert [(player.starting_hero, player.starting_deck) for player in first.players] == [
        (player.starting_hero, player.starting_deck) for player in second.players
    ]
    assert first.random.getstate() == second.random.getstate()


def test_discover_choice_replays_with_generated_entity_ids(tmp_path):
    original, _, saved = recorded_match(tmp_path, deck=["LOE_006"] * 5)
    assert any(entry["action"]["type"] == "CHOOSE" for entry in saved["actions"])
    replayed = replay_action_log(saved)
    assert normalized_game_state(replayed) == normalized_game_state(original)


def test_nondefault_initial_hand_size_replays(tmp_path):
    original, _, saved = recorded_match(tmp_path, first_hand_size=1)
    assert saved["players"][0]["initial_settings"]["_start_hand_size"] == 1
    assert normalized_game_state(replay_action_log(saved)) == normalized_game_state(original)


def test_bytes_seed_is_saved_as_provenance_and_replays(tmp_path):
    original, _, saved = recorded_match(tmp_path, seed=b"custom-seed")
    assert saved["seed"] == {"type": "bytes", "hex": b"custom-seed".hex()}
    assert normalized_game_state(replay_action_log(saved)) == normalized_game_state(original)


def test_normalized_state_does_not_consume_game_rng():
    hero = CardClass.MAGE.default_hero
    players = (
        Player("Alpha", ["KAR_702"] * 5, hero),
        Player("Beta", ["KAR_702"] * 5, hero),
    )
    game = Game(players, seed=12)
    GameSession(game, {}).start()
    before = game.random.getstate()
    normalized_game_state(game)
    assert game.random.getstate() == before
