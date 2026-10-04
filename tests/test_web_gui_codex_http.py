"""HTTP responsiveness and account isolation for asynchronous Codex matches."""

from __future__ import annotations

import queue
import threading
import time

from fireplace.codex_agent import CodexAgent
from tests.test_web_gui_accounts_http import Browser, account_server


class _NoopTransport:
    def close(self):
        pass


class ControlledCodex(CodexAgent):

    def __init__(self, *, model, timeout, block=False, fail=False):
        super().__init__(model=model, timeout=timeout, transport=_NoopTransport())
        self.block = block
        self.fail = fail
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def export_config(self):
        return {"model": self.model, "timeout": self.timeout}

    def choose_action(self, observation, actions):
        del observation
        self.started.set()
        try:
            if self.block and not self.release.wait(timeout=15):
                raise TimeoutError("test fake was not released")
            if self.fail:
                raise RuntimeError("temporary fake Codex failure")
            return actions[0]
        finally:
            self.finished.set()

    def close(self, *, wait=False):
        self.release.set()
        super().close(wait=wait)


def _factory(monkeypatch, build_agent):
    created = []

    def create_agent(kind, seed=None, *, model=None, timeout=None, **kwargs):
        assert kind == "codex"
        assert not kwargs
        agent = build_agent(len(created), model=model, timeout=timeout)
        created.append(agent)
        return agent

    monkeypatch.setattr("fireplace.web_gui.server._create_opponent_agent", create_agent)
    return created


def _start_codex(browser, nickname):
    status, state = browser.request("/api/start", {
        "nickname": nickname,
        "locale": "enUS",
        "opponent": "codex",
    })
    assert status == 200, state
    assert state["mode"] == "match"
    return state


def _submit_first_mulligan_action(browser, state):
    assert state["observation"]["phase"] == "MULLIGAN"
    status, advanced = browser.request("/api/action", {
        "session_id": state["session_id"],
        "revision": state["revision"],
        "action": state["legal_actions"][0],
    })
    assert status == 200, advanced
    return advanced


def _wait_for_llm(browser, session_id, expected, timeout=5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        status, last = browser.request("/api/state")
        assert status == 200, last
        if last.get("session_id") == session_id and last.get("llm", {}).get("state") == expected:
            return last
        time.sleep(0.02)
    raise AssertionError(f"Codex state did not become {expected!r}: {last!r}")


def _request_before_release(browser, path, payload, delayed_agent, *, timeout=2):
    """Make a request on a helper thread and release the fake only on a stall."""

    result = queue.Queue(maxsize=1)

    def perform():
        try:
            result.put(("response", browser.request(path, payload)))
        except BaseException as exc:  # surface worker-thread failures in pytest
            result.put(("exception", exc))

    thread = threading.Thread(target=perform, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    responsive = not thread.is_alive()
    if not responsive:
        delayed_agent.release.set()
        thread.join(timeout=5)
    assert responsive, f"{path} blocked while Codex was waiting for a decision"
    kind, value = result.get(timeout=1)
    if kind == "exception":
        raise value
    return value


def test_state_and_concede_remain_responsive_during_delayed_codex(tmp_path, monkeypatch):
    agents = _factory(
        monkeypatch,
        lambda _index, **config: ControlledCodex(**config, block=True),
    )
    with account_server(tmp_path) as base:
        alice = Browser(base)
        alice.register("CodexAlice")
        started = _submit_first_mulligan_action(
            alice, _start_codex(alice, "Alice")
        )
        agent = agents[0]
        try:
            assert agent.started.wait(timeout=5), "Codex decision worker did not start"
            state_status, state = _request_before_release(
                alice, "/api/state", None, agent
            )
            assert state_status == 200, state
            assert state["session_id"] == started["session_id"]
            assert state["llm"]["state"] == "thinking"

            payload = {
                "session_id": state["session_id"],
                "revision": state["revision"],
            }
            concede_status, conceded = _request_before_release(
                alice, "/api/concede", payload, agent
            )
            assert concede_status == 200, conceded
            assert conceded["outcome"]["human_won"] is False
            terminal_revision = conceded["revision"]
        finally:
            agent.release.set()

        assert agent.finished.wait(timeout=5), "delayed fake did not finish after release"
        final = _wait_for_llm(alice, started["session_id"], "idle")
        assert final["outcome"]["human_won"] is False
        assert final["revision"] == terminal_revision


def test_retry_requires_origin_account_session_and_current_revision(tmp_path, monkeypatch):
    def build(index, **config):
        return ControlledCodex(**config, fail=(index == 0), block=(index > 0))

    agents = _factory(monkeypatch, build)
    with account_server(tmp_path) as base:
        alice = Browser(base)
        bob = Browser(base)
        alice.register("RetryAlice")
        bob.register("RetryBob")

        alice_started = _submit_first_mulligan_action(
            alice, _start_codex(alice, "Alice")
        )
        alice_error = _wait_for_llm(
            alice, alice_started["session_id"], "error"
        )
        assert agents[0].started.wait(timeout=5)
        retry_payload = {
            "session_id": alice_error["session_id"],
            "revision": alice_error["revision"],
        }

        bob_started = _submit_first_mulligan_action(
            bob, _start_codex(bob, "Bob")
        )
        bob_agent = agents[1]
        try:
            assert bob_agent.started.wait(timeout=5), "second account Codex worker did not start"
            bob_before = bob.request("/api/state")[1]

            status, rejected = bob.request("/api/opponent/retry", retry_payload)
            assert status == 409
            assert rejected["error"] == "stale session"
            status, rejected = bob.request("/api/concede", retry_payload)
            assert status == 409
            assert rejected["error"] == "stale session"
            bob_after = bob.request("/api/state")[1]
            assert bob_after["session_id"] == bob_started["session_id"]
            assert bob_after["revision"] == bob_before["revision"]
            assert bob_after["outcome"] is None

            alice_after_cross_account = alice.request("/api/state")[1]
            assert alice_after_cross_account["session_id"] == alice_started["session_id"]
            assert alice_after_cross_account["revision"] == alice_error["revision"]
            assert alice_after_cross_account["llm"]["state"] == "error"
            assert alice_after_cross_account["outcome"] is None

            status, rejected = alice.request(
                "/api/opponent/retry", retry_payload, origin=False
            )
            assert status == 403, rejected
            status, rejected = alice.request("/api/opponent/retry", {
                **retry_payload,
                "session_id": "stale-session",
            })
            assert status == 409
            assert rejected["error"] == "stale session"
            status, rejected = alice.request("/api/opponent/retry", {
                **retry_payload,
                "revision": retry_payload["revision"] + 1,
            })
            assert status == 409
            assert rejected["error"] == "stale revision"

            status, retried = alice.request("/api/opponent/retry", retry_payload)
            assert status == 200, retried
            assert retried["session_id"] == alice_started["session_id"]
            assert retried["llm"]["state"] == "thinking"
            assert len(agents) == 3
            assert agents[2].started.wait(timeout=5)
        finally:
            for agent in agents:
                agent.release.set()
