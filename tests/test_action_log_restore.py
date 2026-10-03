"""Partial action-log recovery and checkpoint validation."""

import copy

import pytest
from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.action_log import ActionLog
from fireplace.agent_api import Action
from fireplace.controller import GameSession, decision_player
from fireplace.exceptions import GameOver
from fireplace.game import Game
from fireplace.player import Player
from fireplace.replay import ReplayError, replay_action_log, restore_action_log
from fireplace.replay_state import normalized_game_state


cards.db.initialize()


def _prefix_log():
    players = (
        Player("Alpha", ["CS2_231"] * 5, CardClass.MAGE.default_hero),
        Player("Beta", ["CS2_231"] * 5, CardClass.MAGE.default_hero),
    )
    game = Game(players, seed=31)
    log = ActionLog(game, source_revision="restore-test")
    session = GameSession(game, {}, action_log=log)
    session.start()
    for _ in range(2):
        session.execute(decision_player(game), Action(type="MULLIGAN"))
    return game, session, log.to_dict()


def test_restore_replays_exact_prefix_and_continues_with_next_sequence():
    original, source_session, saved = _prefix_log()
    expected = normalized_game_state(original)
    callbacks = []
    restored = restore_action_log(saved, callbacks.append)
    try:
        assert normalized_game_state(restored.game) == expected
        assert restored.game.random.getstate() == original.random.getstate()
        assert restored.action_log.to_dict()["actions"] == saved["actions"]
        assert callbacks == []

        player = decision_player(restored.game)
        restored.execute(player, Action(type="END_TURN"))
        assert restored.action_log.to_dict()["actions"][-1]["seq"] == 3
        assert callbacks and callbacks[-1]["actions"][-1]["seq"] == 3
    finally:
        restored.close()
        source_session.close()


def test_restore_rejects_tampered_checkpoint_without_callback():
    _original, source_session, saved = _prefix_log()
    try:
        changed = copy.deepcopy(saved)
        changed["checkpoint"]["rng_state"][1] = 0
        callbacks = []
        with pytest.raises(ReplayError):
            restore_action_log(changed, callbacks.append)
        assert callbacks == []
    finally:
        source_session.close()


def test_hydrated_started_preserves_resolved_setup_metadata():
    _original, source_session, saved = _prefix_log()
    try:
        hydrated = ActionLog.from_dict(saved)
        before = hydrated.to_dict()["players"]
        # ``started`` may be invoked again by a session attached to an already
        # started engine; it must not replace the archived resolved values.
        hydrated.started(source_session.game)
        assert hydrated.to_dict()["players"] == before
    finally:
        source_session.close()


def test_restore_repairs_terminal_record_without_finish():
    players = (
        Player("Alpha", ["CS2_231"] * 5, CardClass.MAGE.default_hero),
        Player("Beta", ["CS2_231"] * 5, CardClass.MAGE.default_hero),
    )
    game = Game(players, seed=32)
    log = ActionLog(game, source_revision="restore-test")
    session = GameSession(game, {}, action_log=log)
    session.start()
    # Simulate the durable record landing immediately before finish() during
    # a process crash.  GameSession still records the terminal action.
    log.finish = lambda _game, status="complete": None
    try:
        with pytest.raises(GameOver):
            session.execute(decision_player(game), Action(type="CONCEDE"))
        saved = log.to_dict()
        assert saved["status"] == "in_progress"
        callbacks = []
        restored = restore_action_log(saved, callbacks.append)
        try:
            assert restored.game.ended
            assert restored.action_log.to_dict()["status"] == "complete"
            assert callbacks[-1]["status"] == "complete"
        finally:
            restored.close()
    finally:
        session.close()


def test_pre_start_archive_restores_setup_and_complete_replay():
    players = (
        Player("Alpha", ["CS2_231"] * 30, CardClass.MAGE.default_hero),
        Player("Beta", ["CS2_231"] * 30, CardClass.MAGE.default_hero),
    )
    game = Game(players, seed=43)
    game.random.random()  # A factory may have consumed the seed stream.
    log = ActionLog(game, source_revision="restore-test")
    log.before_start(game)
    saved = log.to_dict()
    source_session = GameSession(game, {}, action_log=log)
    source_session.start()
    callbacks = []
    restored = restore_action_log(saved, callbacks.append)
    try:
        assert normalized_game_state(restored.game) == normalized_game_state(game)
        assert restored.game.random.getstate() == game.random.getstate()
        assert restored.action_log.to_dict()["game_id"] == saved["game_id"]
        assert len(callbacks) == 1
        assert callbacks[0]["checkpoint"]["action_count"] == 0
        with pytest.raises(GameOver):
            restored.execute(decision_player(restored.game), Action(type="CONCEDE"))
        replayed = replay_action_log(restored.action_log.to_dict())
        assert normalized_game_state(replayed) == normalized_game_state(restored.game)
    finally:
        restored.close()
        source_session.close()


def test_missing_checkpoint_after_setup_is_not_pre_start_recovery():
    _game, source_session, saved = _prefix_log()
    try:
        saved.pop("checkpoint")
        callbacks = []
        with pytest.raises(ReplayError, match="checkpoint"):
            restore_action_log(saved, callbacks.append)
        assert callbacks == []
    finally:
        source_session.close()
