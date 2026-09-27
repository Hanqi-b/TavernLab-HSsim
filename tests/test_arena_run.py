"""Arena draft and record transitions that span multiple game sessions."""

from pathlib import Path

import pytest

from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore, ArenaStoreConflict, ArenaStoreCorrupt
from fireplace.web_gui.arena_service import ArenaService


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
