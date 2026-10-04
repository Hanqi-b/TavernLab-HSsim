"""Focused Codex-vs-MCTS automation scheduling and archive contracts."""

from __future__ import annotations

import threading
import time

import pytest

from fireplace import cards
from fireplace.agent_api import Action
from fireplace.codex_agent import CodexAgent
from fireplace.mcts_agent import MCTSAgent
from fireplace.search_simulation import EngineSearchPosition
from fireplace.web_gui import server as web_server
from fireplace.web_gui.automated_game import AutomatedDecisionScheduler
from fireplace.web_gui.archive_runtime import ArchivePersistenceError
from fireplace.web_gui.contracts import WebActionError, WebLifecycleError
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebGameManager


cards.db.initialize()


class _Codex:
    async_decisions = True

    def __init__(self, *, block: bool = False, model=None):
        self.block = block
        self.model = model
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.closed = False

    def export_config(self):
        return {"model": self.model, "timeout": 1.0}

    def choose_action(self, _observation, actions):
        self.calls += 1
        self.started.set()
        if self.block:
            self.release.wait(3)
        return actions[0]

    def cancel(self):
        return None

    def close(self, *, wait=False):
        del wait
        self.closed = True


class _MCTS:
    seed = 7

    def __init__(self, *, block: bool = False):
        self.block = block
        self.started = threading.Event()
        self.release = threading.Event()
        self.search_calls = 0
        self.calls = 0
        self.closed = False

    def choose_action_with_search(self, _observation, actions, _position):
        self.search_calls += 1
        self.started.set()
        if self.block:
            self.release.wait(3)
        return actions[0]

    def choose_action(self, _observation, actions):
        self.calls += 1
        return actions[0]

    def close(self, *, wait=False):
        del wait
        self.closed = True


class _ArchiveCodex(CodexAgent):
    def __init__(self, model=None):
        super().__init__(model=model, timeout=2.0, transport=object())

    def choose_action(self, _observation, actions):
        return actions[0]


def _wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


@pytest.fixture
def fake_factory(monkeypatch):
    codex = _Codex()
    mcts = _MCTS()

    def factory(kind, **_kwargs):
        if kind == "codex":
            codex.model = _kwargs.get("model")
            return codex
        return mcts

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    return codex, mcts


def _start(manager, model=""):
    return manager.start_match(
        {
            "nickname": "Viewer",
            "locale": "enUS",
            "battle_mode": "codex_mcts",
            "codex_self_model": model,
        }
    )


def test_automation_starts_paused_and_viewer_cannot_submit_action(fake_factory):
    manager = WebGameManager(seed=31)
    try:
        state = _start(manager)
        assert state["automation"] == {
            "enabled": True,
            "paused": True,
            "pending": False,
            "current_seat": 0,
            "controllers": [
                {"kind": "codex", "model": None},
                {"kind": "mcts", "model": None},
            ],
        }
        assert state["legal_actions"] == []
        with pytest.raises(WebActionError):
            manager.handle_action(
                {
                    "session_id": state["session_id"],
                    "revision": state["revision"],
                    "action": {"schema_version": 1, "type": "END_TURN"},
                }
            )
    finally:
        manager.close()


def test_paused_automation_close_releases_both_controllers(fake_factory):
    codex, mcts = fake_factory
    manager = WebGameManager(seed=38)
    _start(manager)
    manager.close()
    assert codex.closed is True
    assert mcts.closed is True


def test_codex_self_model_is_validated_and_pinned(fake_factory):
    codex, _mcts = fake_factory
    manager = WebGameManager(seed=35)
    try:
        state = manager.start_match(
            {
                "nickname": "Viewer",
                "locale": "enUS",
                "battle_mode": "codex_mcts",
                "codex_self_model": "seat0-model",
            }
        )
        assert codex.model == "seat0-model"
        assert state["automation"]["controllers"][0]["model"] == "seat0-model"
        invalid_manager = WebGameManager(seed=36)
        try:
            for invalid_model, message in (
                (True, "codex_model must be a string"),
                ("x" * 129, "at most 128"),
            ):
                with pytest.raises(WebLifecycleError, match=message):
                    invalid_manager.start_match(
                        {
                            "nickname": "Viewer",
                            "locale": "enUS",
                            "battle_mode": "codex_mcts",
                            "codex_self_model": invalid_model,
                        }
                    )
        finally:
            invalid_manager.close()
    finally:
        manager.close()


def test_step_accepts_one_action_then_mcts_uses_search(fake_factory):
    _codex, mcts = fake_factory
    manager = WebGameManager(seed=32)
    try:
        state = _start(manager)
        stepped = manager.automation(
            {
                "command": "step",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        assert stepped["automation"]["paused"] is False
        _wait_until(lambda: manager.snapshot()["revision"] == state["revision"] + 1)
        after_codex = manager.snapshot()
        assert after_codex["automation"]["paused"] is True
        assert after_codex["automation"]["current_seat"] == 1

        stepped_again = manager.automation(
            {
                "command": "step",
                "session_id": after_codex["session_id"],
                "revision": after_codex["revision"],
            }
        )
        assert stepped_again["automation"]["paused"] is False
        _wait_until(lambda: manager.snapshot()["revision"] == after_codex["revision"] + 1)
        after_mulligan = manager.snapshot()
        assert mcts.calls == 1
        assert after_mulligan["automation"]["paused"] is True

        # The next Codex step ends its turn; the following MCTS turn has a
        # detached EngineSearchPosition and must use the real search method.
        stepped_again = manager.automation(
            {
                "command": "step",
                "session_id": after_mulligan["session_id"],
                "revision": after_mulligan["revision"],
            }
        )
        assert stepped_again["automation"]["paused"] is False
        _wait_until(lambda: manager.snapshot()["revision"] == after_mulligan["revision"] + 1)
        after_main_codex = manager.snapshot()
        assert after_main_codex["automation"]["current_seat"] == 1
        mcts.block = True
        manager.automation(
            {
                "command": "step",
                "session_id": after_main_codex["session_id"],
                "revision": after_main_codex["revision"],
            }
        )
        _wait_until(
            lambda: manager.active._automation_scheduler is not None
            and manager.active._automation_scheduler.pending is not None
        )
        assert isinstance(
            manager.active._automation_scheduler.pending.search_position,
            EngineSearchPosition,
        )
        mcts.release.set()
        _wait_until(lambda: mcts.search_calls == 1)
        _wait_until(
            lambda: manager.snapshot()["revision"] == after_main_codex["revision"] + 1
        )
        assert manager.snapshot()["automation"]["paused"] is True
    finally:
        manager.close()


def test_production_pause_resume_reuses_worker_and_discards_old_codex(
    monkeypatch,
):
    old = _Codex(block=True)
    replacement = _Codex(block=True)
    mcts = _MCTS()
    codex_instances = iter((old, replacement))

    def factory(kind, **_kwargs):
        return next(codex_instances) if kind == "codex" else mcts

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    manager = WebGameManager(seed=37)
    try:
        state = _start(manager)
        resumed = manager.automation(
            {
                "command": "resume",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        assert resumed["automation"]["pending"] is True
        assert old.started.wait(1)
        scheduler = manager.active._automation_scheduler
        worker = scheduler._worker._thread

        paused = manager.automation(
            {
                "command": "pause",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        assert paused["revision"] == state["revision"]
        assert paused["automation"]["paused"] is True

        stepped = manager.automation(
            {
                "command": "step",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        assert manager.active._automation_scheduler._worker._thread is worker
        old.release.set()
        assert replacement.started.wait(1)
        with pytest.raises(WebActionError, match="paused before stepping"):
            manager.automation(
                {
                    "command": "step",
                    "session_id": state["session_id"],
                    "revision": state["revision"],
                }
            )
        assert manager.snapshot()["revision"] == state["revision"]
        replacement.release.set()
        _wait_until(lambda: manager.snapshot()["revision"] == state["revision"] + 1)

        paused = manager.automation(
            {
                "command": "pause",
                "session_id": state["session_id"],
                "revision": state["revision"] + 1,
            }
        )
        manager.automation(
            {
                "command": "step",
                "session_id": paused["session_id"],
                "revision": paused["revision"],
            }
        )
        with pytest.raises(WebActionError, match="paused before stepping"):
            manager.automation(
                {
                    "command": "step",
                    "session_id": paused["session_id"],
                    "revision": paused["revision"],
                }
            )
    finally:
        old.release.set()
        replacement.release.set()
        manager.close()


def test_pause_resume_keeps_one_worker_and_discards_late_result():
    first = _Codex(block=True)
    second = _MCTS()
    results = []
    errors = []
    scheduler = AutomatedDecisionScheduler(
        [first, second],
        on_result=lambda decision, action: results.append((decision, action)),
        on_error=lambda decision, error: errors.append((decision, error)),
    )
    try:
        worker = scheduler._worker._thread
        old = scheduler.schedule(
            session_id="s",
            revision=0,
            seat=0,
            player=object(),
            observation={},
            actions=[Action(type="END_TURN")],
            search_position=None,
        )
        assert old is not None and first.started.wait(1)
        scheduler.invalidate()
        fresh = scheduler.schedule(
            session_id="s",
            revision=0,
            seat=1,
            player=object(),
            observation={},
            actions=[Action(type="END_TURN")],
            search_position=object(),
        )
        assert fresh is not None
        first.release.set()
        _wait_until(lambda: len(results) == 1)
        assert results[0][0] is fresh
        assert scheduler._worker._thread is worker
        assert not errors
    finally:
        first.release.set()
        scheduler.close(wait=True)


def test_automation_stop_abandons_archive_and_detaches(monkeypatch, tmp_path):
    monkeypatch.setattr(
        web_server,
        "_create_opponent_agent",
            lambda kind, **kwargs: _ArchiveCodex(model=kwargs.get("model"))
        if kind == "codex"
        else MCTSAgent(
            seed=kwargs.get("seed"),
            time_budget=0,
            max_iterations=1,
        ),
    )
    archive_store = MatchArchiveStore(tmp_path / "matches")
    manager = WebGameManager(seed=33, archive_store=archive_store)
    try:
        state = _start(manager)
        envelope = archive_store.list()[0]
        response = manager.automation(
            {
                "command": "stop",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        assert response["mode"] == "lobby"
        assert manager.active is None
        assert archive_store.get(envelope["game_id"])["metadata"]["status"] == "abandoned"
    finally:
        manager.close()


def test_automation_archive_restores_pinned_controller_config(monkeypatch, tmp_path):
    def factory(kind, **kwargs):
        if kind == "codex":
            return _ArchiveCodex(model=kwargs.get("model"))
        return MCTSAgent(
            seed=kwargs.get("seed"),
            policy_version=kwargs.get("policy_version") or "legacy_v1",
            time_budget=0,
            max_iterations=1,
        )

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    store = MatchArchiveStore(tmp_path / "matches")
    writer = WebGameManager(seed=34, archive_store=store)
    try:
        initial = _start(writer, model="pinned-self-model")
        game_id = store.list()[0]["game_id"]
        envelope = store.get(game_id)
        assert envelope["metadata"]["battle_mode"] == "codex_mcts"
        assert envelope["metadata"]["codex_self_model"] == "pinned-self-model"
        assert envelope["agent_state"]["controllers"][0] == {
            "kind": "codex",
            "model": "pinned-self-model",
            "timeout": 2.0,
        }
        assert envelope["agent_state"]["controllers"][1]["kind"] == "mcts"
    finally:
        writer.close()

    reader = WebGameManager(archive_store=store)
    try:
        resumed = reader.resume_match(
            {"game_id": game_id, "revision": store.get(game_id)["revision"]}
        )
        restored = resumed["state"]
        assert restored["session_id"] != initial["session_id"]
        assert restored["automation"]["enabled"] is True
        assert restored["automation"]["paused"] is True
        assert reader.active._codex_config == {
            "model": "pinned-self-model",
            "timeout": 2.0,
        }
    finally:
        reader.close()


def test_archive_failure_quarantines_automation_retry_and_step(
    monkeypatch,
):
    codex = _Codex()
    mcts = _MCTS()
    factory_calls = []

    def factory(kind, **_kwargs):
        factory_calls.append(kind)
        return codex if kind == "codex" else mcts

    monkeypatch.setattr(web_server, "_create_opponent_agent", factory)
    manager = WebGameManager(seed=39)
    try:
        state = _start(manager)
        active = manager.active
        assert active is not None

        def fail_presentation(_step):
            raise ArchivePersistenceError("simulated checkpoint failure")

        active._record_presentation_step_locked = fail_presentation
        manager.automation(
            {
                "command": "resume",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        assert codex.started.wait(2)
        _wait_until(lambda: active.archive_failed is not None)
        failed = manager.snapshot()
        log_count = len(active.session.action_log.to_dict().get("actions", []))
        revision = failed["revision"]
        calls = codex.calls
        constructions = len(factory_calls)

        with pytest.raises(WebActionError) as retry_error:
            manager.retry_opponent(
                {"session_id": failed["session_id"], "revision": revision}
            )
        assert retry_error.value.status_code == 503

        with pytest.raises(WebActionError) as step_error:
            manager.automation(
                {
                    "command": "step",
                    "session_id": failed["session_id"],
                    "revision": revision,
                }
            )
        assert step_error.value.status_code == 503
        assert manager.snapshot()["revision"] == revision
        assert len(active.session.action_log.to_dict().get("actions", [])) == log_count
        assert codex.calls == calls
        assert len(factory_calls) == constructions
    finally:
        manager.close()


def test_duplicate_resume_during_action_gap_keeps_timer_live(fake_factory):
    manager = WebGameManager(seed=40)
    try:
        state = _start(manager)
        first = manager.automation(
            {
                "command": "step",
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
        )
        _wait_until(lambda: manager.snapshot()["revision"] == first["revision"] + 1)
        paused = manager.snapshot()
        active = manager.active
        assert active is not None
        # Force the next scheduling request into the minimum-gap timer window.
        active._automation_last_action = time.monotonic()
        pending = manager.automation(
            {
                "command": "step",
                "session_id": paused["session_id"],
                "revision": paused["revision"],
            }
        )
        assert pending["automation"]["paused"] is False
        duplicate = manager.automation(
            {
                "command": "resume",
                "session_id": paused["session_id"],
                "revision": paused["revision"],
            }
        )
        assert duplicate["revision"] == paused["revision"]
        _wait_until(lambda: manager.snapshot()["revision"] == paused["revision"] + 1)
    finally:
        manager.close()
