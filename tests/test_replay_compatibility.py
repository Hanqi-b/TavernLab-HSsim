"""Compatibility checks for archives written by the audited predecessor."""

import copy
import json
from pathlib import Path

import pytest

from fireplace.agent_api import Action
from fireplace.controller import decision_player
from fireplace.replay import ReplayError, replay_action_log, restore_action_log
from fireplace.replay_compatibility import (
    ALLOWED_SOURCE_PAIRS,
    CURRENT_SOURCE_SHA256,
    PREDECESSOR_SOURCE_SHA256,
    PRE_RNG_FIX_SOURCE_SHA256,
    current_signature,
    signature_is_compatible,
)
from fireplace.replay_state import _REPLAY_SOURCE_FILES, normalized_game_state


FIXTURE_DIR = Path(__file__).parent / "fixtures"
AUDITED_SOURCE_SHA256 = (
    PREDECESSOR_SOURCE_SHA256,
    PRE_RNG_FIX_SOURCE_SHA256,
)


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_only_audited_source_pairs_are_accepted():
    current = current_signature()
    predecessor = _fixture("pre_battle_prefix.json")["replay"]["code_signature"]

    assert current["source_sha256"] == CURRENT_SOURCE_SHA256
    assert predecessor["source_sha256"] == PREDECESSOR_SOURCE_SHA256
    assert signature_is_compatible(predecessor, current)
    assert signature_is_compatible(current, current)
    assert ALLOWED_SOURCE_PAIRS == {
        (PREDECESSOR_SOURCE_SHA256, CURRENT_SOURCE_SHA256),
        (PRE_RNG_FIX_SOURCE_SHA256, CURRENT_SOURCE_SHA256),
    }
    # The policy module must not become part of the digest it validates.
    assert "replay_compatibility.py" not in _REPLAY_SOURCE_FILES

    future = copy.deepcopy(current)
    future["source_sha256"] = "future-engine-source"
    assert not signature_is_compatible(predecessor, future)
    future_card_data = copy.deepcopy(current)
    future_card_data["hearthstone_data_version"] = "future-card-data"
    assert not signature_is_compatible(predecessor, future_card_data)


@pytest.mark.parametrize("source_sha256", AUDITED_SOURCE_SHA256)
def test_complete_fixture_replays_for_each_audited_source(source_sha256):
    saved = _fixture("pre_battle_complete.json")
    # The fixture is a deterministic predecessor archive. Re-tagging its
    # signature in memory exercises each separately audited source path
    # without changing the recorded actions, state, or RNG values.
    saved["replay"]["code_signature"]["source_sha256"] = source_sha256

    game = replay_action_log(saved)

    assert game.ended
    assert normalized_game_state(game) == saved["replay"]["final_state"]


@pytest.mark.parametrize("source_sha256", AUDITED_SOURCE_SHA256)
def test_prefix_restore_rebases_signature_and_continues(source_sha256):
    saved = _fixture("pre_battle_prefix.json")
    # See the complete replay test: this is an in-memory source tag only, so
    # both audited paths use the same deterministic checkpoint fixture.
    saved["replay"]["code_signature"]["source_sha256"] = source_sha256
    callbacks = []

    restored = restore_action_log(saved, callbacks.append)
    try:
        assert normalized_game_state(restored.game) == saved["checkpoint"]["state"]
        assert (
            restored.action_log.to_dict()["replay"]["code_signature"]
            == current_signature()
        )
        assert len(callbacks) == 1
        assert (
            callbacks[-1]["replay"]["code_signature"]
            == current_signature()
        )
        assert (
            saved["replay"]["code_signature"]["source_sha256"]
            == source_sha256
        )

        restored.execute(decision_player(restored.game), Action(type="END_TURN"))
        updated = restored.action_log.to_dict()
        assert updated["actions"][-1]["seq"] == len(saved["actions"]) + 1
        assert updated["replay"]["code_signature"] == current_signature()
        assert callbacks[-1]["actions"][-1]["seq"] == len(saved["actions"]) + 1
    finally:
        restored.close()


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "wrong source",
            lambda signature: signature.__setitem__("source_sha256", "wrong"),
        ),
        (
            "wrong current digest",
            lambda signature: signature.__setitem__("source_sha256", "0" * 64),
        ),
        (
            "future card data",
            lambda signature: signature.__setitem__(
                "hearthstone_data_version", "future"
            ),
        ),
        (
            "wrong dependency",
            lambda signature: signature["dependencies"].__setitem__(
                "hearthstone", "future"
            ),
        ),
        (
            "wrong runtime",
            lambda signature: signature.__setitem__("python_version", "3.11"),
        ),
        (
            "extra dependency",
            lambda signature: signature["dependencies"].__setitem__(
                "unexpected", "value"
            ),
        ),
    ],
)
def test_predecessor_metadata_mismatch_is_rejected(label, mutate):
    saved = _fixture("pre_battle_complete.json")
    mutate(saved["replay"]["code_signature"])
    # A source_revision string cannot turn an unverified source digest into an
    # accepted archive.
    saved["source_revision"] = "current"

    with pytest.raises(ReplayError, match="code or dependency"):
        replay_action_log(saved)


def test_tampered_checkpoint_is_still_rejected_for_compatible_source():
    saved = _fixture("pre_battle_prefix.json")
    saved["checkpoint"]["rng_state"][1] = 0
    callbacks = []

    with pytest.raises(ReplayError, match="checkpoint|RNG state"):
        restore_action_log(saved, callbacks.append)
    assert callbacks == []


@pytest.mark.parametrize("source_sha256", AUDITED_SOURCE_SHA256)
@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        (
            "RNG state",
            lambda saved: saved["checkpoint"]["rng_state"].__setitem__(1, 0),
        ),
        (
            "normalized state",
            lambda saved: saved["checkpoint"]["state"].__setitem__(
                "turn", saved["checkpoint"]["state"]["turn"] + 1
            ),
        ),
    ],
)
def test_repair_does_not_happen_until_full_checkpoint_validation(
    source_sha256, label, mutate
):
    saved = _fixture("pre_battle_prefix.json")
    # Retag in memory to cover both audited migration paths with the same
    # deterministic fixture; the tampered checkpoint must fail before repair.
    saved["replay"]["code_signature"]["source_sha256"] = source_sha256
    mutate(saved)
    callbacks = []

    with pytest.raises(ReplayError, match=label):
        restore_action_log(saved, callbacks.append)
    assert callbacks == []
    assert (
        saved["replay"]["code_signature"]["source_sha256"] == source_sha256
    )


def _manager_fixture(tmp_path, monkeypatch):
    """Install one real archive and a recording local Radical controller."""

    from fireplace.radical_agent import RadicalAgent
    from fireplace.web_gui import server as web_server
    from fireplace.web_gui.archive_runtime import capture_agent_state
    from fireplace.web_gui.match_archives import MatchArchiveStore

    saved = _fixture("pre_battle_opponent_prefix.json")
    store = MatchArchiveStore(tmp_path / "matches")

    class RecordingRadical(RadicalAgent):
        def __init__(self):
            super().__init__(
                seed=31,
                time_budget=0,
                max_iterations=1,
                max_depth=1,
                action_limit=4,
            )
            self.calls = 0
            self.seen_sources = []

        def choose_action(self, _observation, actions):
            self.calls += 1
            durable = store.get(saved["game_id"])
            self.seen_sources.append(
                durable["log"]["replay"]["code_signature"]["source_sha256"]
            )
            return actions[0]

    agent = RecordingRadical()
    store.create(
        saved,
        {
            "mode": "normal",
            "opponent": "radical",
            "seed": 31,
            "locale": "enUS",
            "human_seat": 0,
        },
        agent_state=capture_agent_state(agent),
        public={"snapshot": {}, "events": []},
    )
    monkeypatch.setattr(
        web_server,
        "_create_opponent_agent",
        lambda _kind, **_kwargs: agent,
    )
    return saved, store, agent


def test_manager_persists_repaired_signature_before_controller_start(
    tmp_path, monkeypatch
):
    from fireplace.web_gui.server import WebGameManager

    saved, store, agent = _manager_fixture(tmp_path, monkeypatch)
    manager = WebGameManager(archive_store=store)
    try:
        manager.resume_match({"game_id": saved["game_id"], "revision": 1})

        assert agent.calls == 1
        assert agent.seen_sources == [CURRENT_SOURCE_SHA256]
        durable = store.get(saved["game_id"])
        assert durable["revision"] >= 2
        assert (
            durable["log"]["replay"]["code_signature"]["source_sha256"]
            == CURRENT_SOURCE_SHA256
        )
    finally:
        manager.close()


def test_manager_save_failure_prevents_controller_start(tmp_path, monkeypatch):
    from fireplace.web_gui.contracts import WebLifecycleError
    from fireplace.web_gui.server import WebGameManager

    saved, store, agent = _manager_fixture(tmp_path, monkeypatch)

    def fail_save(*_args, **_kwargs):
        raise OSError("blocked archive write")

    monkeypatch.setattr(store, "save", fail_save)
    manager = WebGameManager(archive_store=store)
    try:
        with pytest.raises(WebLifecycleError, match="could not be saved"):
            manager.resume_match({"game_id": saved["game_id"], "revision": 1})
        assert agent.calls == 0
        # ``get`` remains available while the failed migration leaves the old
        # predecessor envelope untouched.
        durable = store.get(saved["game_id"])
        assert durable["revision"] == 1
        assert (
            durable["log"]["replay"]["code_signature"]["source_sha256"]
            == PREDECESSOR_SOURCE_SHA256
        )
    finally:
        manager.close()
