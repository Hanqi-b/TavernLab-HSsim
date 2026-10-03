"""Private decision logs are atomic, resumable and absent from public APIs."""

import json
from types import SimpleNamespace

import pytest

from fireplace.agent_api import Action
from fireplace.web_gui.ai_decisions import capture_decision, restore_decisions, trim_decisions
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebGameManager


def test_capture_is_detached_and_json_safe():
    action = Action(type="END_TURN")
    trace = {"selected_action": action.to_dict(), "candidates": [{"score": 3.0}]}
    agent = SimpleNamespace(last_search_stats={"decision_trace": trace}, policy_version="tactical_v2")
    row = capture_decision(agent, action, action_seq=4, turn=3, seat=1)
    trace["candidates"][0]["score"] = -1
    assert row["trace"]["candidates"][0]["score"] == 3.0
    json.dumps(row, allow_nan=False)


@pytest.mark.parametrize("trace,reason", [
    ({"selected_action": {"type": "ATTACK"}}, "stale_trace"),
    ({"score": float("inf")}, "trace_not_json_safe"),
    ({"score": object()}, "trace_not_json_safe"),
    ({"text": "x" * 262145}, "trace_size_limit"),
])
def test_bad_diagnostics_are_explicit_without_rejecting_gameplay(trace, reason):
    agent = SimpleNamespace(last_search_stats={"decision_trace": trace}, policy_version="tactical_v2")
    row = capture_decision(agent, Action(type="END_TURN"), action_seq=1, turn=1, seat=1)
    assert row["trace"]["reason"] == reason
    assert row["trace"]["complete"] is False


def test_old_archives_have_no_private_rows():
    assert restore_decisions({}) == []
    rows = [{"action_seq": 3}]
    restored = restore_decisions({"ai_decisions": rows})
    rows[0]["action_seq"] = 8
    assert restored == [{"action_seq": 3}]


def test_trace_retention_is_bounded_and_reports_dropped_rows():
    rows = [{"action_seq": n, "text": "x" * 100} for n in range(6)]
    assert trim_decisions(rows, max_rows=4, max_bytes=10000) == 2
    assert [row["action_seq"] for row in rows] == [2, 3, 4, 5]
    assert trim_decisions(rows, max_rows=4, max_bytes=300) == 2
    assert [row["action_seq"] for row in rows] == [4, 5]


def pass_agent(agent):
    def choose(observation, actions, *args):
        action = next(a for a in actions if a.type in {"MULLIGAN", "END_TURN"})
        agent.last_search_stats = {"decision_trace": {
            "selected_action": action.to_dict(), "reason": "test_private_marker",
            "candidates": [{"card_id": "PRIVATE_CANDIDATE_SENTINEL", "score": 4.0}],
            "complete": True}}
        return action
    agent.choose_action_with_search = choose
    agent.choose_action = choose


def human_pass(manager):
    state = manager.snapshot()
    action = next(a for a in state["legal_actions"] if a["type"] in {"MULLIGAN", "END_TURN"})
    return manager.handle_action({"session_id": state["session_id"],
                                  "revision": state["revision"], "action": action})


def test_private_rows_persist_and_resume_without_public_leak_or_duplicate(tmp_path):
    store = MatchArchiveStore(tmp_path / "matches")
    manager = WebGameManager(seed=11, archive_store=store)
    try:
        manager.start_match({"nickname": "Trace tester", "locale": "enUS", "opponent": "mcts"})
        pass_agent(manager.active.opponent_agent)
        for _ in range(3):
            human_pass(manager)
        envelope = store.list()[0]
        game_id = envelope["game_id"]
        rows = envelope["metadata"]["ai_decisions"]
        assert any(row["trace"].get("reason") == "test_private_marker" for row in rows)
        assert len({row["action_seq"] for row in rows}) == len(rows)
        actions = envelope["log"]["actions"]
        for row in rows:
            accepted = actions[row["action_seq"] - 1]
            assert row["action"] == accepted["action"]
            assert row["seat"] == accepted["player"]
            assert row["turn"] == accepted["turn"]
        public = [manager.snapshot(), manager.matches_list(), manager.match_detail(game_id), envelope["public"], envelope["log"]]
        assert "PRIVATE_CANDIDATE_SENTINEL" not in json.dumps(public)
    finally:
        manager.close()

    resumed_store = MatchArchiveStore(tmp_path / "matches")
    resumed = WebGameManager(seed=11, archive_store=resumed_store)
    try:
        resumed.resume_match({"game_id": game_id, "revision": envelope["revision"]})
        assert resumed.active._ai_decisions == rows
        pass_agent(resumed.active.opponent_agent)
        human_pass(resumed)
        new_rows = resumed_store.get(game_id)["metadata"]["ai_decisions"]
        assert new_rows[:len(rows)] == rows
        assert len(new_rows) > len(rows)
        state = resumed.snapshot()
        resumed.concede({"session_id": state["session_id"], "revision": state["revision"]})
        _, downloaded = resumed.match_download(game_id)
        assert "PRIVATE_CANDIDATE_SENTINEL" not in json.dumps(downloaded)
    finally:
        resumed.close()


def test_real_mcts_producer_is_saved_as_diagnostics_not_an_unavailable_stub(tmp_path):
    store = MatchArchiveStore(tmp_path / "matches")
    manager = WebGameManager(seed=11, archive_store=store)
    try:
        manager.start_match({"nickname": "Real trace", "locale": "enUS", "opponent": "mcts"})
        human_pass(manager)
        human_pass(manager)
        envelope = store.list()[0]
        rows = envelope["metadata"]["ai_decisions"]
        assert rows
        assert all(row["trace"]["reason"] not in {
            "trace_unavailable", "stale_trace", "trace_not_json_safe", "trace_size_limit"} for row in rows)
        assert any(row["trace"].get("search") for row in rows)
        assert any(len(row["trace"].get("candidates", [])) > 1 for row in rows)
        json.dumps(rows, allow_nan=False)
    finally:
        manager.close()
