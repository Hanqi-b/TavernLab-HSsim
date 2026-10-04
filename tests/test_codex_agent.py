import json
import threading
import time
from collections import deque

import pytest

from fireplace.agent_api import Action
from fireplace.codex_agent import CodexAgent, CodexAgentError
from fireplace.codex_transport import CodexTransportError


class _FakeTransport:
    cwd = "/tmp/tavernlab-card-agent-test"

    def __init__(self, texts=None, *, wait_error=None, wait_delay=0):
        self.texts = deque(texts or ['{"action_id": 0}'])
        self.wait_error = wait_error
        self.wait_delay = wait_delay
        self.events = deque()
        self.requests = []
        self.notifications = []
        self.start_count = 0
        self.reset_count = 0
        self.close_count = 0
        self.turn_count = 0

    def start(self):
        self.start_count += 1

    def notify(self, method, params=None):
        self.notifications.append((method, params))

    def request(self, method, params, timeout=None):
        self.requests.append((method, params))
        if method == "initialize":
            return {}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            self.turn_count += 1
            turn_id = "turn-%s" % self.turn_count
            self.events.append(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turnId": turn_id,
                        "item": {
                            "type": "agentMessage",
                            "text": self.texts.popleft(),
                        },
                    },
                }
            )
            self.events.append(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "thread-1",
                        "turn": {"id": turn_id, "status": "completed", "items": []},
                    },
                }
            )
            return {"turn": {"id": turn_id}}
        raise AssertionError(method)

    def wait_for_notification(self, timeout=None):
        if self.wait_delay:
            time.sleep(self.wait_delay)
        if self.wait_error is not None:
            raise self.wait_error
        if not self.events:
            raise CodexTransportError("fake event stream exhausted")
        return self.events.popleft()

    def reset(self):
        self.reset_count += 1
        self.events.clear()

    def close(self):
        self.close_count += 1


def _actions():
    return [Action(type="END_TURN"), Action(type="CONCEDE")]


def test_agent_starts_once_and_returns_original_action():
    transport = _FakeTransport(['{"action_id": 1}', '{"action_id": 0}'])
    agent = CodexAgent(transport=transport, timeout=1)
    actions = _actions()

    assert agent.choose_action({"phase": "MAIN"}, actions) is actions[1]
    assert agent.choose_action({"phase": "MAIN"}, actions) is actions[0]
    assert transport.start_count == 1
    assert [method for method, _ in transport.requests] == [
        "initialize",
        "thread/start",
        "turn/start",
        "turn/start",
    ]
    turn_params = transport.requests[2][1]
    assert turn_params["outputSchema"]["properties"]["action_id"]["enum"] == [0, 1]
    prompt = turn_params["input"][0]["text"]
    assert "chain of thought" not in prompt


def test_one_legal_action_skips_transport_and_returns_same_object():
    transport = _FakeTransport()
    agent = CodexAgent(transport=transport)
    action = Action(type="END_TURN")
    assert agent.choose_action({"phase": "MAIN"}, [action]) is action
    assert transport.start_count == 0
    assert transport.requests == []


@pytest.mark.parametrize(
    "text",
    [
        "true",
        '{"action_id": true}',
        '{"action_id": -1}',
        '{"action_id": 2}',
        '{"action_id": 0, "extra": "ignore me"}',
        "not-json",
    ],
)
def test_agent_rejects_non_exact_action_ids(text):
    transport = _FakeTransport([text])
    agent = CodexAgent(transport=transport, timeout=1)
    with pytest.raises(CodexAgentError, match="action"):
        agent.choose_action({"phase": "MAIN"}, _actions())
    assert transport.reset_count == 1


def test_agent_ignores_stale_turn_notifications():
    transport = _FakeTransport(['{"action_id": 0}'])
    transport.events.extendleft(
        [
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "old-thread",
                    "turn": {"id": "old-turn", "status": "completed", "items": []},
                },
            }
        ]
    )
    agent = CodexAgent(transport=transport, timeout=1)
    assert agent.choose_action({"phase": "MAIN"}, _actions()) is not None


def test_agent_resets_after_eof_and_timeout():
    eof = _FakeTransport(wait_error=CodexTransportError("Codex app-server exited unexpectedly"))
    with pytest.raises(CodexAgentError, match="unavailable"):
        CodexAgent(transport=eof, timeout=1).choose_action({"phase": "MAIN"}, _actions())
    assert eof.reset_count == 1

    timed = _FakeTransport(wait_delay=0.2)
    with pytest.raises(CodexAgentError, match="too long"):
        CodexAgent(transport=timed, timeout=0.03).choose_action({"phase": "MAIN"}, _actions())
    assert timed.reset_count == 1


def test_visible_catalog_does_not_include_hidden_opponent_cards(monkeypatch):
    class Card:
        name = "Visible Card"
        text = "Draw a card."
        type = "SPELL"
        race = None
        mechanics = ["DRAW"]

    class CardData:
        @staticmethod
        def load_card_data():
            return {"VISIBLE": Card(), "HIDDEN": Card()}, object()

    monkeypatch.setattr("fireplace.card_data.load_card_data", CardData.load_card_data)
    transport = _FakeTransport(['{"action_id": 0}'])
    agent = CodexAgent(transport=transport, timeout=1)
    observation = {
        "phase": "MAIN",
        "self": {"hand": [{"card_id": "VISIBLE"}]},
        "opponent": {"hand": [{"card_id": "HIDDEN"}], "hand_count": 1},
    }
    agent.choose_action(observation, _actions())
    prompt = transport.requests[-1][1]["input"][0]["text"]
    assert "VISIBLE" in prompt
    assert "HIDDEN" not in prompt
    assert "Visible Card" in prompt


def test_explicit_timeout_wins_over_environment(monkeypatch):
    monkeypatch.setenv("TAVERNLAB_CODEX_TIMEOUT", "0.001")
    assert CodexAgent(timeout=3, transport=_FakeTransport()).timeout == 3
    assert CodexAgent(transport=_FakeTransport()).timeout == 0.001


def test_explicit_none_model_does_not_read_environment(monkeypatch):
    monkeypatch.setenv("TAVERNLAB_CODEX_MODEL", "env-model")
    assert CodexAgent(transport=_FakeTransport()).model == "env-model"
    assert CodexAgent(model=None, transport=_FakeTransport()).model is None


def test_close_cleans_transport():
    transport = _FakeTransport()
    agent = CodexAgent(transport=transport)
    agent.close()
    assert transport.close_count == 1
    with pytest.raises(CodexAgentError, match="closed"):
        agent.choose_action({}, _actions())
