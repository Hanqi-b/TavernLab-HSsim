"""Focused backend coverage for the Codex-vs-Codex spectator mode."""

from __future__ import annotations

import threading
import time

import pytest

from fireplace import cards
from fireplace.codex_agent import CodexAgent
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from hearthstone.enums import CardClass
from fireplace.web_gui.automated_game import AutomatedGame
from fireplace.web_gui import server as web_server
from fireplace.web_gui.contracts import WebActionError
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebGameManager


cards.db.initialize()


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


class _DuelCodex:
    async_decisions = True
    _counter = 0

    def __init__(self, model, hero=None, *, block=False, fail=False):
        type(self)._counter += 1
        self.transport_id = type(self)._counter
        self.model = model
        self.hero = hero
        self.block = block
        self.fail = fail
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.closed = False
        self.observations = []

    def export_config(self):
        return {"model": self.model, "timeout": 1.0}

    def choose_action(self, observation, actions):
        self.calls += 1
        self.started.set()
        self.observations.append(observation)
        assert observation["self"].get("hero", {}).get("card_id")
        assert "hand" not in observation["opponent"]
        assert "secrets" not in observation["opponent"]
        if self.block:
            self.release.wait(3)
        if self.fail:
            self.fail = False
            raise RuntimeError("private fixture failure")
        return next(
            (action for action in actions if action.type == "END_TURN"), actions[0]
        )

    def cancel(self):
        return None

    def close(self, *, wait=False):
        del wait
        self.closed = True


class _ArchiveCodex(CodexAgent):
    def __init__(self, model):
        super().__init__(model=model, timeout=2.0, transport=object())

    def choose_action(self, _observation, actions):
        return actions[0]


def _start(manager, self_model="self-model", opponent_model="opponent-model"):
    return manager.start_match(
        {
            "nickname": "Duel viewer",
            "locale": "enUS",
            "battle_mode": "codex_codex",
            "codex_self_model": self_model,
            "codex_model": opponent_model,
        }
    )


def test_duel_uses_two_private_observations_and_models(monkeypatch):
    created = []

    def factory(kind, **kwargs):
        assert kind == "codex"
        model = kwargs["model"]
        agent = _DuelCodex(model)
        created.append(agent)
        return agent

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    manager = WebGameManager(seed=101, opponent="codex")
    try:
        state = _start(manager)
        assert state["battle_mode"] == "codex_codex"
        assert state["automation"]["controllers"] == [
            {"kind": "codex", "model": "self-model"},
            {"kind": "codex", "model": "opponent-model"},
        ]
        assert state["llm"]["seat"] == 0
        first = manager.automation(
            {"command": "step", "session_id": state["session_id"], "revision": 0}
        )
        _wait_until(lambda: manager.snapshot()["revision"] == 1)
        after_first = manager.snapshot()
        assert after_first["automation"]["current_seat"] == 1
        assert after_first["llm"]["seat"] == 1
        second = manager.automation(
            {
                "command": "step",
                "session_id": first["session_id"],
                "revision": after_first["revision"],
            }
        )
        _wait_until(lambda: manager.snapshot()["revision"] == 2)
        assert all(agent.observations for agent in created)
        assert created[0].transport_id != created[1].transport_id
        assert manager.snapshot()["automation"]["paused"] is True
    finally:
        manager.close()


def test_duel_pause_pending_seat_one_recreates_only_that_codex(monkeypatch):
    created = []

    def factory(kind, **kwargs):
        model = kwargs["model"]
        agent = _DuelCodex(
            model,
            block=model == "opponent-model",
        )
        created.append(agent)
        return agent

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    manager = WebGameManager(seed=102, opponent="codex")
    try:
        state = _start(manager)
        manager.automation({"command": "step", "session_id": state["session_id"], "revision": 0})
        _wait_until(lambda: manager.snapshot()["revision"] == 1)
        state = manager.snapshot()
        manager.automation({"command": "step", "session_id": state["session_id"], "revision": 1})
        old = created[1]
        assert old.started.wait(1)
        paused = manager.automation({"command": "pause", "session_id": state["session_id"], "revision": 1})
        assert paused["automation"]["paused"] is True
        manager.automation({"command": "step", "session_id": state["session_id"], "revision": 1})
        assert old is not manager.active.controllers[1]
        old.release.set()
        _wait_until(lambda: len(created) >= 3 and created[2].started.is_set())
        created[2].release.set()
        _wait_until(lambda: manager.snapshot()["revision"] == 2)
        assert manager.active.controllers[0] is created[0]
        assert manager.active.controllers[1] is created[2]
        assert manager.snapshot()["automation"]["controllers"][1]["model"] == "opponent-model"
    finally:
        for agent in created:
            agent.release.set()
        manager.close()


def test_duel_retry_replaces_failed_seat_one_only(monkeypatch):
    created = []

    def factory(kind, **kwargs):
        model = kwargs["model"]
        agent = _DuelCodex(
            model,
            fail=model == "opponent-model" and len(created) == 1,
        )
        created.append(agent)
        return agent

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    manager = WebGameManager(seed=103, opponent="codex")
    try:
        state = _start(manager)
        manager.automation({"command": "step", "session_id": state["session_id"], "revision": 0})
        _wait_until(lambda: manager.snapshot()["revision"] == 1)
        state = manager.snapshot()
        manager.automation({"command": "step", "session_id": state["session_id"], "revision": 1})
        _wait_until(lambda: manager.snapshot()["llm"]["state"] == "error")
        failed = manager.snapshot()
        assert failed["automation"]["error_seat"] == 1
        old_self, old_opponent = manager.active.controllers
        retried = manager.retry_opponent(
            {"session_id": failed["session_id"], "revision": failed["revision"]}
        )
        assert retried["llm"]["seat"] == 1
        _wait_until(lambda: manager.snapshot()["revision"] == 2)
        assert manager.active.controllers[0] is old_self
        assert manager.active.controllers[1] is not old_opponent
        assert manager.active.controllers[1].model == "opponent-model"
    finally:
        manager.close()


def test_duel_archive_restores_both_pinned_models(monkeypatch, tmp_path):
    def factory(kind, **kwargs):
        assert kind == "codex"
        return _ArchiveCodex(kwargs["model"])

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    store = MatchArchiveStore(tmp_path / "matches")
    writer = WebGameManager(seed=104, opponent="codex", archive_store=store)
    try:
        initial = _start(writer, "archive-self", "archive-opponent")
        game_id = store.list()[0]["game_id"]
        envelope = store.get(game_id)
        assert envelope["metadata"]["codex_self_model"] == "archive-self"
        assert envelope["metadata"]["codex_model"] == "archive-opponent"
        assert envelope["agent_state"]["controllers"][0]["model"] == "archive-self"
        assert envelope["agent_state"]["controllers"][1]["model"] == "archive-opponent"
    finally:
        writer.close()

    reader = WebGameManager(archive_store=store, opponent="codex")
    try:
        resumed = reader.resume_match(
            {"game_id": game_id, "revision": store.get(game_id)["revision"]}
        )
        assert resumed["state"]["session_id"] != initial["session_id"]
        assert resumed["state"]["battle_mode"] == "codex_codex"
        assert resumed["state"]["automation"]["controllers"] == [
            {"kind": "codex", "model": "archive-self"},
            {"kind": "codex", "model": "archive-opponent"},
        ]
    finally:
        reader.close()


def test_duel_scripted_end_turn_reaches_terminal_action_log():
    player0 = Player("Duel seat 0", [], CardClass.MAGE.default_hero)
    player1 = Player("Duel seat 1", [], CardClass.MAGE.default_hero)
    session = GameSession(Game((player0, player1), seed=105), {})
    controllers = [_DuelCodex("seat0"), _DuelCodex("seat1")]
    game = AutomatedGame(
        session,
        player0,
        controllers,
        battle_mode="codex_codex",
        automation_paused=True,
    )
    try:
        initial = game.snapshot()
        game.automation(
            {
                "command": "resume",
                "session_id": initial["session_id"],
                "revision": initial["revision"],
            }
        )
        _wait_until(lambda: game.snapshot()["outcome"] is not None, timeout=5.0)
        log = session.action_log.to_dict()
        assert log["status"] == "complete"
        assert log["actions"]
        assert all(entry["player"] in (0, 1) for entry in log["actions"])
        assert all(
            entry["action"]["type"] in {"MULLIGAN", "END_TURN"}
            for entry in log["actions"]
        )
        assert all(controller.calls for controller in controllers)
        assert all(controller.observations for controller in controllers)
    finally:
        game.close()
    assert all(controller.closed for controller in controllers)
