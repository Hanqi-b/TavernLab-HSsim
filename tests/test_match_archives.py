"""Account-local match archive persistence contracts."""

import uuid

import pytest

from fireplace.web_gui.match_archives import (
    MatchArchiveConflict,
    MatchArchiveCorrupt,
    MatchArchiveStore,
)


def _log(game_id, status="in_progress"):
    return {"game_id": game_id, "status": status, "actions": []}


def test_create_get_save_cas_and_list_status(tmp_path):
    store = MatchArchiveStore(tmp_path)
    game_id = str(uuid.uuid4())
    created = store.create(
        _log(game_id),
        {
            "mode": "arena",
            "opponent": "mcts",
            "arena": {"run_id": "run", "match_id": "match", "match_index": 1},
        },
        agent_state={"kind": "mcts"},
        public={"snapshot": {"turn": 1}},
    )
    assert created["revision"] == 1
    assert store.get(game_id) == created

    saved = store.save(game_id, metadata={"status": "abandoned"}, expected_revision=1)
    assert saved["revision"] == 2
    assert saved["metadata"]["arena"]["match_id"] == "match"
    assert store.list()[0]["status"] == "abandoned"
    assert store.find_arena("match")["game_id"] == game_id

    with pytest.raises(MatchArchiveConflict):
        store.save(game_id, expected_revision=1)


def test_corrupt_archive_is_not_overwritten_and_good_history_survives(tmp_path):
    store = MatchArchiveStore(tmp_path)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    store.create(_log(first), {})
    store.create(_log(second), {})
    corrupt_path = tmp_path / (first + ".json")
    corrupt_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(MatchArchiveCorrupt):
        store.save(first, metadata={"opponent": "mcts"})
    assert corrupt_path.read_text(encoding="utf-8") == "{broken"
    assert [row["game_id"] for row in store.list()] == [second]


def test_invalid_game_id_and_owner_conflict(tmp_path):
    store = MatchArchiveStore(tmp_path)
    with pytest.raises(ValueError):
        store.get("../escape")

    owner = MatchArchiveStore(tmp_path)
    contender = MatchArchiveStore(tmp_path)
    owner.acquire_owner()
    try:
        with pytest.raises(MatchArchiveConflict):
            contender.acquire_owner()
    finally:
        owner.release_owner()


def test_envelope_values_are_detached(tmp_path):
    store = MatchArchiveStore(tmp_path)
    game_id = str(uuid.uuid4())
    raw = {"game_id": game_id, "status": "complete", "nested": {"value": 1}}
    saved = store.create(raw, {}, public={"events": []})
    saved["log"]["nested"]["value"] = 99
    saved["public"]["events"].append({"private": "copy"})
    loaded = store.get(game_id)
    assert loaded["log"]["nested"]["value"] == 1
    assert loaded["public"]["events"] == []
