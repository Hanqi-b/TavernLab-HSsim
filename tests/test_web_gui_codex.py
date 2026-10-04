"""Focused human-vs-Codex scheduling and boundary contracts."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from fireplace import cards
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui import server as web_server
from fireplace.web_gui.account_game import AccountGameRegistry
from fireplace.web_gui.accounts import AccountStore
from fireplace.web_gui.archive_runtime import (
    ArchivePersistenceError,
    capture_agent_state,
    restore_agent_state,
)
from fireplace.web_gui.async_opponent import validate_codex_state
from fireplace.web_gui.http_server import make_server
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebActionError, WebGame, WebGameManager
from fireplace.codex_agent import CodexAgent


cards.db.initialize()


class _ScriptedCodex:
    async_decisions = True

    def __init__(self, mode: str = "block"):
        self.mode = mode
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def export_config(self):
        return {"model": "test-codex", "timeout": 1.0}

    def choose_action(self, _observation, actions):
        self.calls += 1
        self.started.set()
        if self.mode == "block":
            self.release.wait(5)
        elif self.mode == "timeout":
            raise TimeoutError("private stderr must not reach the browser")
        return actions[0]

    def cancel(self):
        return None

    def close(self, *, wait=False):
        del wait
        self.closed = True


class _ArchiveCodex(CodexAgent):
    """A real adapter-shaped object that never starts a Codex process."""

    def __init__(self):
        super().__init__(model=None, timeout=1.0, transport=object())

    def choose_action(self, _observation, actions):
        return actions[0]


def _match(agent):
    human = Player("Human", ["CS2_231"] * 10, "HERO_08")
    opponent = Player("Codex", ["CS2_231"] * 10, "HERO_01")
    return WebGame(
        GameSession(Game((human, opponent), seed=47), {}),
        human,
        agent,
    )


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def _submit_first_human_action(game):
    before = game.snapshot()
    assert before["observation"]["phase"] == "MULLIGAN"
    assert before["llm"]["state"] == "idle"
    response = game.handle_action(
        {
            "session_id": before["session_id"],
            "revision": before["revision"],
            "action": before["legal_actions"][0],
        }
    )
    return before, response


def test_slow_codex_does_not_block_snapshot_or_offturn_concede():
    agent = _ScriptedCodex()
    game = _match(agent)
    try:
        before, response = _submit_first_human_action(game)
        assert response["llm"]["state"] == "thinking"
        assert agent.started.wait(1)

        started = time.monotonic()
        thinking = game.snapshot()
        assert time.monotonic() - started < 0.5
        assert thinking["llm"]["state"] == "thinking"

        started = time.monotonic()
        conceded = game.concede(
            {"session_id": thinking["session_id"], "revision": thinking["revision"]}
        )
        assert time.monotonic() - started < 0.5
        assert conceded["outcome"]["human_won"] is False
        revision = conceded["revision"]

        # A completion from the invalidated worker cannot append an AI action.
        agent.release.set()
        time.sleep(0.1)
        assert game.snapshot()["revision"] == revision
        assert len(game.snapshot()["events"]) == 2
        assert before["revision"] == 0
    finally:
        agent.release.set()
        game.close(wait=True)


def test_codex_timeout_is_paused_and_retry_reuses_revision(monkeypatch):
    failing = _ScriptedCodex("timeout")
    game = _match(failing)
    replacement = _ScriptedCodex("ready")
    monkeypatch.setattr(
        web_server,
        "_create_opponent_agent",
        lambda *_args, **_kwargs: replacement,
    )
    try:
        _before, response = _submit_first_human_action(game)
        assert failing.started.wait(1)
        _wait_until(lambda: game.snapshot()["llm"]["state"] == "error")
        failed = game.snapshot()
        assert failed["llm"]["error"] == "Codex opponent timed out"
        assert "private stderr" not in json.dumps(failed)

        retried = game.retry_opponent(
            {"session_id": failed["session_id"], "revision": failed["revision"]}
        )
        assert retried["revision"] == failed["revision"]
        assert retried["llm"]["state"] == "thinking"
        assert replacement.started.wait(1)
        _wait_until(lambda: game.snapshot()["revision"] > failed["revision"])
    finally:
        replacement.release.set()
        game.close(wait=True)


def test_archive_failure_blocks_retry_before_controller_replacement(monkeypatch):
    agent = _ScriptedCodex()
    game = _match(agent)
    replacements = []

    def replace(*_args, **_kwargs):
        replacements.append(_ScriptedCodex("ready"))
        return replacements[-1]

    def fail_checkpoint(_step):
        raise ArchivePersistenceError("simulated checkpoint failure")

    monkeypatch.setattr(web_server, "_create_opponent_agent", replace)
    try:
        _submit_first_human_action(game)
        assert agent.started.wait(1)
        monkeypatch.setattr(game, "_record_presentation_step_locked", fail_checkpoint)
        agent.release.set()
        _wait_until(lambda: game.archive_failed is not None)
        failed = game.snapshot()
        revision = failed["revision"]
        actions = len(game.session.action_log.to_dict()["actions"])
        calls = agent.calls

        with pytest.raises(WebActionError) as rejected:
            game.retry_opponent(
                {"session_id": failed["session_id"], "revision": revision}
            )
        assert rejected.value.status_code == 503
        assert replacements == []
        assert agent.calls == calls
        assert game.snapshot()["revision"] == revision
        assert len(game.session.action_log.to_dict()["actions"]) == actions
    finally:
        agent.release.set()
        game.close(wait=True)


def test_concurrent_retry_has_one_reserved_replacement(monkeypatch):
    failing = _ScriptedCodex("timeout")
    game = _match(failing)
    entered = threading.Event()
    release = threading.Event()
    created = []

    def factory(*_args, **_kwargs):
        entered.set()
        assert release.wait(2)
        replacement = _ScriptedCodex("ready")
        created.append(replacement)
        return replacement

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    try:
        _before, _response = _submit_first_human_action(game)
        assert failing.started.wait(1)
        _wait_until(lambda: game.snapshot()["llm"]["state"] == "error")
        failed = game.snapshot()
        payload = {"session_id": failed["session_id"], "revision": failed["revision"]}
        result = []

        def first_retry():
            result.append(game.retry_opponent(payload))

        worker = threading.Thread(target=first_retry)
        worker.start()
        assert entered.wait(1)
        with pytest.raises(WebActionError, match="already in progress"):
            game.retry_opponent(payload)
        release.set()
        worker.join(timeout=3)
        assert not worker.is_alive()
        assert len(result) == 1
        assert len(created) == 1
    finally:
        release.set()
        game.close(wait=True)


def test_codex_archive_state_is_flat_strict_and_secret_free(monkeypatch):
    agent = CodexAgent(model=None, timeout=2.0, transport=object())
    archived = capture_agent_state(agent)
    assert archived == {"kind": "codex", "model": None, "timeout": 2.0}
    monkeypatch.setenv("TAVERNLAB_CODEX_MODEL", "changed-after-archive")
    restored = CodexAgent(model=None, timeout=2.0, transport=object())
    try:
        restore_agent_state(restored, archived)
        assert restored.export_config()["model"] is None
        with pytest.raises(ValueError):
            validate_codex_state({"kind": "codex", "model": None})
        with pytest.raises(ValueError):
            validate_codex_state({**archived, "conversation": "secret"})
    finally:
        agent.close()
        restored.close()


def test_retry_route_keeps_account_auth_and_origin_checks(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    registry = AccountGameRegistry(
        accounts=accounts,
        data_root=tmp_path / "users",
        legacy_decks=tmp_path / "missing-decks.json",
        legacy_arena=tmp_path / "missing-arena.json",
        opponent="codex",
    )
    http_server = make_server(registry, host="127.0.0.1", port=0)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:%d" % http_server.server_port
        connection = HTTPConnection("127.0.0.1", http_server.server_port, timeout=3)
        body = json.dumps({"session_id": "missing", "revision": 0}).encode()
        connection.request(
            "POST",
            "/api/opponent/retry",
            body=body,
            headers={"Content-Type": "application/json", "Origin": base},
        )
        response = connection.getresponse()
        assert response.status == 401
        connection.close()

        connection = HTTPConnection("127.0.0.1", http_server.server_port, timeout=3)
        connection.request(
            "POST",
            "/api/opponent/retry",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Origin": "http://attacker.example",
            },
        )
        response = connection.getresponse()
        assert response.status == 403
        connection.close()
    finally:
        http_server.shutdown()
        thread.join(timeout=3)
        http_server.server_close()


def test_manager_archive_resume_pins_codex_config_and_allows_continuation(
    monkeypatch, tmp_path
):
    archive_store = MatchArchiveStore(tmp_path / "matches")
    created = []

    def fake_factory(kind, **_kwargs):
        assert kind == "codex"
        agent = _ArchiveCodex()
        created.append(agent)
        return agent

    monkeypatch.delenv("TAVERNLAB_CODEX_MODEL", raising=False)
    monkeypatch.setenv("TAVERNLAB_CODEX_TIMEOUT", "17")
    monkeypatch.setattr(web_server, "_create_opponent_agent", fake_factory)
    writer = WebGameManager(
        seed=47,
        opponent="codex",
        codex_timeout=1.0,
        archive_store=archive_store,
    )
    try:
        initial = writer.start_match(
            {"nickname": "Archive human", "locale": "enUS", "opponent": "codex"}
        )
        original_session = initial["session_id"]
        envelope = archive_store.list()[0]
        game_id = envelope["game_id"]
        assert envelope["agent_state"] == {
            "kind": "codex",
            "model": None,
            "timeout": 1.0,
        }
        assert envelope["metadata"]["codex_model"] is None
        assert envelope["metadata"]["codex_timeout"] == 1.0
    finally:
        writer.close()

    monkeypatch.setenv("TAVERNLAB_CODEX_MODEL", "changed-after-archive")
    monkeypatch.setenv("TAVERNLAB_CODEX_TIMEOUT", "99")
    reader = WebGameManager(archive_store=archive_store)
    try:
        envelope = archive_store.get(game_id)
        resumed = reader.resume_match(
            {"game_id": game_id, "revision": envelope["revision"]}
        )
        state = resumed["state"]
        assert state["session_id"] != original_session
        assert state["llm"]["model"] is None
        assert reader.active._codex_config == {"model": None, "timeout": 1.0}
        assert len(created) >= 2

        if state["observation"]["phase"] == "MULLIGAN":
            continued = reader.handle_action(
                {
                    "session_id": state["session_id"],
                    "revision": state["revision"],
                    "action": state["legal_actions"][0],
                }
            )
            assert continued["revision"] >= state["revision"] + 1
    finally:
        reader.close()
