"""Focused contracts for versioned MCTS archive state."""

import json

import pytest

from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore
from fireplace.agent_factory import create_agent
from fireplace.mcts_agent import MCTSAgent
from fireplace.web_gui.archive_runtime import capture_agent_state, restore_agent_state
from fireplace.web_gui import server as web_server
from fireplace.web_gui.contracts import WebLifecycleError
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebGameManager, _resolve_mcts_archive_options


def _tactical_agent(seed=19):
    return MCTSAgent(
        seed=seed,
        policy_version="tactical_v2",
        time_budget=None,
        max_iterations=4,
        max_depth=3,
        action_limit=8,
    )


def test_capture_restore_preserves_mcts_policy_config_and_rng_position():
    source = _tactical_agent()
    source.random.random()
    archived = capture_agent_state(source)
    expected = [source.random.choice(("left", "right")) for _ in range(8)]

    restored = create_agent(
        "mcts",
        seed=archived["seed"],
        policy_version=archived["policy_version"],
        search_config=archived["search_config"],
    )
    restore_agent_state(restored, archived)
    actual = [restored.random.choice(("left", "right")) for _ in range(8)]

    assert archived["policy_version"] == "tactical_v2"
    assert archived["search_config"] == source.export_config()
    assert actual == expected


def test_unversioned_mcts_state_is_restored_as_legacy_policy():
    source = create_agent("mcts", seed=7, policy_version="legacy_v1")
    archived = capture_agent_state(source)
    archived.pop("policy_version")
    archived.pop("search_config")

    restored = create_agent("mcts", seed=7, policy_version="legacy_v1")
    restore_agent_state(restored, archived)
    assert restored.policy_version == "legacy_v1"


def test_conflicting_archive_policy_metadata_is_rejected_before_replay():
    metadata = {
        "mcts_policy_version": "tactical_v2",
        "mcts_search_config": {"max_depth": 3},
    }
    state = {
        "kind": "mcts",
        "policy_version": "legacy_v1",
        "search_config": {"max_depth": 3},
    }

    with pytest.raises(ValueError, match="policy versions conflict"):
        _resolve_mcts_archive_options(metadata, state)

    metadata = {"mcts_policy_version": "tactical_v2"}
    state = {"kind": "mcts", "policy_version": "tactical_v2"}
    with pytest.raises(ValueError, match="missing search configuration"):
        _resolve_mcts_archive_options(metadata, state)


def test_factory_rejects_search_options_for_non_mcts_policies():
    with pytest.raises(ValueError, match="only valid for mcts"):
        create_agent("radical", search_config={"max_depth": 2})
    with pytest.raises(ValueError, match="only valid for mcts"):
        create_agent("heuristic", policy_version="legacy_v1")


def test_new_normal_match_archive_records_tactical_policy_metadata(tmp_path):
    archive_store = MatchArchiveStore(tmp_path / "matches")
    manager = WebGameManager(seed=11, archive_store=archive_store)
    try:
        manager.start_match({"nickname": "Archive tester", "locale": "enUS", "opponent": "mcts"})
        agent = manager.active.opponent_agent
        envelope = archive_store.list()[0]
        assert envelope["metadata"]["mcts_policy_version"] == "tactical_v2"
        assert envelope["metadata"]["mcts_search_config"] == agent.export_config()
        assert envelope["agent_state"]["policy_version"] == "tactical_v2"
        assert envelope["agent_state"]["search_config"] == agent.export_config()
    finally:
        manager.close()


def test_new_arena_match_archive_records_tactical_policy_metadata(tmp_path):
    arena_store = ArenaStore(tmp_path / "arena.json")
    run = ArenaRun.create(
        ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"],
        "Archive tester",
        "zhCN",
        seed=17,
    )
    run.choose_hero(run.hero_choices[0])
    for _ in range(30):
        run.choose_card(run.choices[0])
    arena_store.save(run)
    archive_store = MatchArchiveStore(tmp_path / "matches")
    manager = WebGameManager(
        seed=17,
        archive_store=archive_store,
        arena_store=arena_store,
    )
    try:
        ready = manager.arena_state()
        manager.arena_start_battle(
            {"run_id": ready["run_id"], "revision": ready["revision"]}
        )
        agent = manager.active.opponent_agent
        envelope = archive_store.list()[0]
        assert envelope["metadata"]["mode"] == "arena"
        assert envelope["metadata"]["mcts_policy_version"] == "tactical_v2"
        assert envelope["metadata"]["mcts_search_config"] == agent.export_config()
    finally:
        manager.close()


@pytest.mark.parametrize("conflict", ["version", "config"])
def test_resume_rejects_conflicting_mcts_archive_fields_before_replay(
    tmp_path, monkeypatch, conflict
):
    archive_store = MatchArchiveStore(tmp_path / "matches")
    writer = WebGameManager(seed=13, archive_store=archive_store)
    try:
        writer.start_match(
            {"nickname": "Archive tester", "locale": "zhCN", "opponent": "mcts"}
        )
        envelope = archive_store.list()[0]
        game_id = envelope["game_id"]
    finally:
        writer.close()

    archive_path = tmp_path / "matches" / (game_id + ".json")
    raw = json.loads(archive_path.read_text(encoding="utf-8"))
    if conflict == "version":
        raw["metadata"]["mcts_policy_version"] = "legacy_v1"
    else:
        raw["metadata"]["mcts_search_config"]["max_depth"] += 1
    archive_path.write_text(json.dumps(raw), encoding="utf-8")

    manager = WebGameManager(
        seed=13,
        archive_store=MatchArchiveStore(tmp_path / "matches"),
    )
    replay_called = False

    def fail_replay(*_args, **_kwargs):
        nonlocal replay_called
        replay_called = True
        raise AssertionError("conflicting policy metadata must be rejected before replay")

    monkeypatch.setattr(web_server, "restore_action_log", fail_replay)
    try:
        before = manager._archive_store.get(game_id)
        with pytest.raises(WebLifecycleError, match="conflict"):
            manager.resume_match({"game_id": game_id, "revision": before["revision"]})
        assert not replay_called
        assert manager.active is None
        assert manager._archive_store.get(game_id) == before
    finally:
        manager.close()
