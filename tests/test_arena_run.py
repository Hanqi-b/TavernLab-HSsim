"""Arena draft and record transitions that span multiple game sessions."""

from pathlib import Path

import pytest

from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore, ArenaStoreConflict, ArenaStoreCorrupt
from fireplace.web_gui.arena_service import ArenaService
from fireplace.web_gui.contracts import WebLifecycleError


SETS = ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"]


def _ready(seed: int = 17) -> ArenaRun:
    run = ArenaRun.create(SETS, "Tester", "zhCN", seed=seed)
    run.choose_hero(run.hero_choices[0])
    for _ in range(30):
        assert len(run.choices) == 3
        run.choose_card(run.choices[0])
    assert run.stage == "ready" and len(run.deck) == 30
    return run


def test_arena_run_draft_is_repeatable_and_saved_offer_survives_restart(tmp_path: Path):
    first = ArenaRun.create(SETS, "Tester", "zhCN", seed=17)
    second = ArenaRun.create(SETS, "Tester", "zhCN", seed=17)
    assert first.hero_choices == second.hero_choices
    first.choose_hero(first.hero_choices[0])
    second.choose_hero(second.hero_choices[0])
    assert first.choices == second.choices

    store = ArenaStore(tmp_path / "arena.json")
    store.save(first)
    loaded = store.load()
    assert loaded is not None
    assert loaded.choices == first.choices
    assert loaded.hero_id == first.hero_id
    first.choose_card(first.choices[1])
    loaded.choose_card(loaded.choices[1])
    assert loaded.choices == first.choices


def test_arena_run_ends_at_seven_wins_or_three_losses():
    winning = _ready()
    for index in range(7):
        match_id = winning.start_match()
        with pytest.raises(ValueError, match="not ready"):
            winning.start_match()
        winning.settle_match(match_id, True)
        with pytest.raises(ValueError, match="already recorded"):
            winning.settle_match(match_id, True)
        assert winning.wins == index + 1
    assert winning.stage == "complete"
    assert winning.losses == 0

    losing = _ready(seed=19)
    for _ in range(3):
        losing.settle_match(losing.start_match(), False)
    assert losing.stage == "complete"
    assert losing.losses == 3


def test_arena_run_can_be_retired_without_changing_record_or_deck(tmp_path: Path):
    run = _ready()
    for _ in range(2):
        run.settle_match(run.start_match(), True)
    deck = list(run.deck)
    revision = run.revision

    run.retire()

    assert run.stage == "complete"
    assert run.retired is True
    assert run.pending_match_id is None
    assert (run.wins, run.losses) == (2, 0)
    assert run.deck == deck
    assert run.revision == revision + 1

    store = ArenaStore(tmp_path / "retired.json")
    store.save(run)
    loaded = store.load()
    assert loaded is not None
    assert loaded.retired is True
    assert loaded.stage == "complete"
    assert (loaded.wins, loaded.losses) == (2, 0)
    assert loaded.deck == deck


def test_old_version_one_run_without_retired_marker_defaults_to_false():
    run = _ready()
    payload = run.to_dict()
    payload.pop("retired")

    restored = ArenaRun.from_dict(payload)

    assert restored.retired is False


def test_arena_service_retire_rejects_stale_or_wrong_run_without_mutation(tmp_path: Path):
    run = _ready()
    store = ArenaStore(tmp_path / "retire-cas.json")
    store.save(run)
    service = ArenaService(store=store)
    try:
        before = service.run.to_dict()
        for payload in (
            {"run_id": "wrong-run", "revision": run.revision},
            {"run_id": run.run_id, "revision": run.revision - 1},
        ):
            with pytest.raises(WebLifecycleError) as error:
                service.retire(payload)
            assert error.value.status_code == 409
            assert service.run.to_dict() == before
            assert store.load().to_dict() == before

        state = service.retire({"run_id": run.run_id, "revision": run.revision})
        assert state["mode"] == "complete"
        assert state["retired"] is True
        assert service.run.revision == run.revision + 1
    finally:
        service.close()


def test_arena_service_retire_only_allows_ready_stage(tmp_path: Path):
    service = ArenaService(store=ArenaStore(tmp_path / "retire-stages.json"))
    try:
        state = service.start({"set_ids": SETS, "nickname": "Tester", "locale": "zhCN"}, seed=17)
        with pytest.raises(WebLifecycleError) as error:
            service.retire({"run_id": state["run_id"], "revision": state["revision"]})
        assert error.value.status_code == 409 and error.value.snapshot["mode"] == "hero"

        state = service.choose_hero({
            "run_id": state["run_id"], "revision": state["revision"],
            "hero_id": state["hero_offer"][0]["id"],
        })
        with pytest.raises(WebLifecycleError) as error:
            service.retire({"run_id": state["run_id"], "revision": state["revision"]})
        assert error.value.status_code == 409 and error.value.snapshot["mode"] == "draft"

        for _ in range(30):
            state = service.choose_card({
                "run_id": state["run_id"], "revision": state["revision"],
                "card_id": state["card_offer"][0]["id"],
            })
        state = service.retire({"run_id": state["run_id"], "revision": state["revision"]})
        with pytest.raises(WebLifecycleError) as error:
            service.retire({"run_id": state["run_id"], "revision": state["revision"]})
        assert error.value.status_code == 409 and error.value.snapshot["mode"] == "complete"
    finally:
        service.close()


def test_unfinished_battle_recovers_without_counting_a_loss(tmp_path: Path):
    run = _ready()
    old_match_id = run.start_match()
    store = ArenaStore(tmp_path / "arena.json")
    store.save(run)
    loaded = store.load()
    assert loaded is not None
    loaded.recover_without_match()
    assert loaded.stage == "ready" and loaded.wins == loaded.losses == 0
    assert loaded.start_match() == old_match_id


def test_old_saved_run_with_classic_as_a_choice_remains_playable(tmp_path: Path):
    current = ArenaRun.create(SETS, "Tester", "zhCN", seed=17)
    payload = current.to_dict()
    payload["selected_sets"] = ["EXPERT1", "GVG", "TGT", "OG", "GANGS", "NAXX"]
    legacy = ArenaRun.from_dict(payload)
    legacy.choose_hero(legacy.hero_choices[0])
    assert len(legacy.choices) == 3
    store = ArenaStore(tmp_path / "legacy.json")
    store.save(legacy)
    restored = store.load()
    assert restored is not None and restored.choices == legacy.choices


def test_store_preserves_invalid_save_and_rejects_a_second_owner(tmp_path: Path):
    path = tmp_path / "arena.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ArenaStoreCorrupt):
        ArenaService(store=ArenaStore(path))
    assert path.read_text(encoding="utf-8") == "{broken"

    path.unlink()
    first = ArenaService(store=ArenaStore(path))
    try:
        with pytest.raises(ArenaStoreConflict):
            ArenaService(store=ArenaStore(path))
    finally:
        first.close()
    second = ArenaService(store=ArenaStore(path))
    second.close()


def test_failed_save_does_not_advance_in_memory_run(tmp_path: Path):
    class FailingStore(ArenaStore):
        fail = False

        def save(self, run, *, expected=None):
            if self.fail:
                raise OSError("disk unavailable")
            return super().save(run, expected=expected)

    store = FailingStore(tmp_path / "arena.json")
    service = ArenaService(store=store)
    try:
        service.start({"set_ids": SETS, "nickname": "Tester", "locale": "zhCN"}, seed=17)
        before = service.run.to_dict()
        store.fail = True
        with pytest.raises(OSError, match="disk unavailable"):
            service.choose_hero({
                "run_id": service.run.run_id,
                "revision": service.run.revision,
                "hero_id": service.run.hero_choices[0],
            })
        assert service.run.to_dict() == before
        assert store.load().to_dict() == before
    finally:
        service.close()


@pytest.mark.parametrize("sets", [
    ["GVG", "TGT", "OG", "GANGS", "NAXX", "BRM"],  # 14
    ["GVG", "TGT", "OG", "GANGS", "UNGORO"],  # 15
    SETS,  # 16
    ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX", "BRM"],  # 17
    ["GVG", "TGT", "OG", "GANGS", "UNGORO", "SCHOLOMANCE"],  # 18
])
def test_new_budget_runs_survive_save_and_reload(sets, tmp_path):
    run = ArenaRun.create(sets, "Tester", "zhCN", seed=17)
    run.choose_hero(run.hero_choices[0])
    store = ArenaStore(tmp_path / "arena.json")
    store.save(run)
    loaded = store.load()
    assert loaded.selected_sets == tuple(sets)
    assert loaded.hero_id == run.hero_id
    assert loaded.choices == run.choices
