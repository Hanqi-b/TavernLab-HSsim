"""Format isolation, durable AI drafts, and archive recovery boundaries."""
import copy
import json

import pytest

from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore
from fireplace.web_gui.arena_service import ArenaService
from fireplace.web_gui.contracts import WebLifecycleError
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebGameManager

WILD = "wild_2016_09_02"


def ready(seed=17):
    run = ArenaRun.create([], "History tester", "zhCN", seed=seed, format_id=WILD)
    run.choose_hero(run.hero_choices[0])
    for _ in range(30):
        run.choose_card(run.choices[0])
    return run


def manager(tmp_path, run):
    store = ArenaStore(tmp_path / "arena.json")
    store.save(run)
    return WebGameManager(seed=17, arena_store=store,
                          archive_store=MatchArchiveStore(tmp_path / "matches"))


def test_historical_offer_survives_restart_and_v2_pool_is_fixed():
    run = ArenaRun.create([], "Tester", "enUS", seed=17, format_id=WILD)
    run.choose_hero(run.hero_choices[0])
    payload = run.to_dict()
    assert payload["version"] == 2 and payload["format_id"] == WILD
    restored = ArenaRun.from_dict(json.loads(json.dumps(payload)))
    assert restored.choices == run.choices
    run.choose_card(run.choices[1])
    restored.choose_card(restored.choices[1])
    assert restored.to_dict() == run.to_dict()
    invalid = copy.deepcopy(payload)
    invalid["selected_sets"].append("UNGORO")
    with pytest.raises(ValueError, match="card pool"):
        ArenaRun.from_dict(invalid)
    invalid["format_id"] = "unknown"
    with pytest.raises(ValueError):
        ArenaRun.from_dict(invalid)


@pytest.mark.parametrize("won, rounds", [(True, 12), (False, 3)])
def test_historical_record_uses_twelve_wins_three_losses(won, rounds):
    run = ready()
    for index in range(rounds):
        run.settle_match(run.start_match(), won)
        assert run.stage == ("complete" if index == rounds - 1 else "ready")


def test_format_start_is_server_owned_and_cannot_switch(tmp_path):
    service = ArenaService(store=ArenaStore(tmp_path / "arena.json"))
    try:
        with pytest.raises(WebLifecycleError, match="fixed card pool"):
            service.start({"format_id": WILD, "nickname": "Tester", "locale": "zhCN", "set_ids": ["UNGORO"]}, seed=17)
        state = service.start({"format_id": WILD, "nickname": "Tester", "locale": "zhCN"}, seed=17)
        assert state["mode"] == "hero" and state["format_id"] == WILD
        assert state["max_wins"] == 12 and state["max_losses"] == 3
        before = service.run.to_dict()
        with pytest.raises(WebLifecycleError, match="cannot change"):
            service.choose_hero({"run_id": state["run_id"], "revision": state["revision"], "format_id": "custom_v1", "hero_id": state["hero_offer"][0]["id"]})
        assert service.run.to_dict() == before
        assert "ai_drafts" not in state and "data_profile" not in state
    finally:
        service.close()


def test_scoring_failure_leaves_ready_state_and_disk_unchanged(tmp_path, monkeypatch):
    from fireplace.arena import ai_draft
    app = manager(tmp_path, ready())
    try:
        service = app._arena_locked()
        before = service.run.to_dict()
        def missing(*args, **kwargs):
            raise ValueError("ArenaRatingMissing card_id=CS2_029 class=MAGE")
        monkeypatch.setattr(ai_draft, "draft_ai", missing)
        with pytest.raises(WebLifecycleError, match="card_id=CS2_029 class=MAGE"):
            app.arena_start_battle({"run_id": service.run.run_id, "revision": service.run.revision})
        assert app.active is None
        assert service.run.to_dict() == before
        assert service.store.load().to_dict() == before
        assert app._archive_store.list() == []
    finally:
        app.close()


def test_draft_and_pending_commit_are_atomic_on_write_failure(tmp_path, monkeypatch):
    app = manager(tmp_path, ready())
    try:
        service = app._arena_locked()
        before = service.run.to_dict()
        def fail(*args, **kwargs):
            raise OSError("simulated Arena save failure")
        monkeypatch.setattr(service.store, "save", fail)
        with pytest.raises(OSError, match="save failure"):
            app.arena_start_battle({"run_id": service.run.run_id, "revision": service.run.revision})
        assert app.active is None and service.run.to_dict() == before
        assert service.store.load().to_dict() == before
        assert app._archive_store.list() == []
    finally:
        app.close()


def test_historical_battle_trace_private_and_resume_does_not_redraft(tmp_path, monkeypatch):
    from fireplace.arena import ai_draft, formats
    run = ready()
    app = manager(tmp_path, run)
    try:
        state = app.arena_start_battle({"run_id": run.run_id, "revision": run.revision})
        assert state["mode"] == "match" and "ai_drafts" not in state
        saved = app._arena_locked().run.ai_drafts["0"]
        assert len(saved["trace"]) == 30
        game_id = app.active.archive_game_id
        envelope = app._archive_store.get(game_id)
        assert envelope["metadata"]["arena"]["ai_draft"] == saved
        assert "ai_draft" not in json.dumps(app.matches_list())
        assert "ai_draft" not in json.dumps(app.match_detail(game_id))
    finally:
        app.close()
    def forbidden(*args, **kwargs):
        raise AssertionError("resume must not load historical ratings or draft")
    monkeypatch.setattr(ai_draft, "draft_ai", forbidden)
    monkeypatch.setattr(formats, "historical_profile", forbidden)
    restarted = WebGameManager(seed=17, arena_store=ArenaStore(tmp_path / "arena.json"), archive_store=MatchArchiveStore(tmp_path / "matches"))
    try:
        assert restarted.arena_state()["mode"] == "resume"
        current = restarted._archive_store.get(game_id)
        restarted.resume_match({"game_id": game_id, "revision": current["revision"]})
        assert restarted._arena_locked().run.ai_drafts["0"] == saved
        current = restarted._archive_store.get(game_id)
        restarted.abandon_match({"game_id": game_id, "revision": current["revision"]})
        _, downloaded = restarted.match_download(game_id)
        assert downloaded["arena_draft"]["ai_draft"] == saved
    finally:
        restarted.close()


def test_no_archive_save_failure_does_not_construct_game(tmp_path, monkeypatch):
    from fireplace.web_gui import arena_factory
    run = ready()
    store = ArenaStore(tmp_path / "arena.json")
    store.save(run)
    app = WebGameManager(seed=17, arena_store=store)
    try:
        service = app._arena_locked()
        before = service.run.to_dict()
        def fail(*args, **kwargs):
            raise OSError("simulated Arena save failure")
        def forbidden(*args, **kwargs):
            raise AssertionError("game must not be constructed before durable pending")
        monkeypatch.setattr(service.store, "save", fail)
        monkeypatch.setattr(arena_factory, "build_arena_game", forbidden)
        with pytest.raises(OSError, match="save failure"):
            app.arena_start_battle({"run_id": run.run_id, "revision": run.revision})
        assert app.active is None and service.run.to_dict() == before
    finally:
        app.close()


def test_historical_preflight_reports_unavailable_current_card_id(monkeypatch):
    from fireplace import cards
    from fireplace.arena.formats import HistoricalFormatError, historical_profile
    if not cards.db.initialized:
        cards.db.initialize()
    monkeypatch.delitem(cards.db, "CS2_029")
    with pytest.raises(HistoricalFormatError, match="absent.*CS2_029"):
        historical_profile()
