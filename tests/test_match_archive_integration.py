"""Integration checks for archive-backed engine recovery."""

from contextlib import contextmanager
import copy
import threading
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore
from fireplace.action_log import ActionLog
from fireplace.agent_api import Action
from fireplace.controller import GameSession, decision_player
from fireplace.exceptions import GameOver
from fireplace.game import Game
from fireplace.mcts_agent import MCTSAgent
from fireplace.radical_agent import RadicalAgent
from fireplace.player import Player
from fireplace.replay import replay_action_log, restore_action_log
from fireplace.replay_state import normalized_game_state
from fireplace.web_gui import server as web_server
from fireplace.web_gui.archive_runtime import capture_agent_state
from fireplace.web_gui.contracts import WebActionError, WebLifecycleError
from fireplace.web_gui.match_archives import MatchArchiveStore
from fireplace.web_gui.server import WebGameManager, make_server


cards.db.initialize()

_ARENA_SETS = ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"]


@contextmanager
def _http_server(app):
    server = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _request(base, route, payload=None):
    import json

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = Request(base + route, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def _ready_arena_run(seed=17):
    run = ArenaRun.create(_ARENA_SETS, "Archive tester", "zhCN", seed=seed)
    run.choose_hero(run.hero_choices[0])
    for _ in range(30):
        run.choose_card(run.choices[0])
    assert run.stage == "ready"
    return run


def _arena_metadata(run, match_id, seed):
    return {
        "mode": "arena",
        "opponent": "mcts",
        "seed": seed,
        "locale": "zhCN",
        "human_seat": 0,
        "arena": {
            "run_id": run.run_id,
            "match_id": match_id,
            "match_index": run.match_index,
        },
    }


def _arena_files(tmp_path, seed=17):
    arena_path = tmp_path / "arena.json"
    run = _ready_arena_run(seed)
    match_id = run.start_match()
    arena_store = ArenaStore(arena_path)
    arena_store.save(run)
    archive_dir = tmp_path / "matches"
    return arena_path, run, match_id, arena_store, archive_dir


def _action_log(game_id, *, seed, terminal_winner=None, finish=True, mode="arena"):
    """Build a replayable accepted prefix, optionally ending at CONCEDE."""

    game = Game(
        (
            Player("Human", ["CS2_231"] * 10, CardClass.MAGE.default_hero),
            Player("Opponent", ["CS2_231"] * 10, CardClass.MAGE.default_hero),
        ),
        seed=seed,
    )
    log = ActionLog(
        game,
        source_revision="archive-integration-test",
        game_id=game_id,
        mode=mode,
        seed=seed,
    )
    session = GameSession(game, {}, action_log=log)
    session.start()
    for _ in range(2):
        session.execute(decision_player(game), Action(type="MULLIGAN"))
    if terminal_winner is not None:
        # True means the opponent concedes; False means the human concedes.
        conceding_player = game.players[1] if terminal_winner else game.players[0]
        for _ in range(4):
            actor = decision_player(game)
            if actor is conceding_player:
                break
            assert actor is not None
            session.execute(actor, Action(type="END_TURN"))
        assert decision_player(game) is conceding_player
        if not finish:
            log.finish = lambda _game, status="complete": None
        with pytest.raises(GameOver):
            session.execute(conceding_player, Action(type="CONCEDE"))
    value = log.to_dict()
    session.close()
    return value


def _create_arena_archive(
    archive_dir,
    run,
    match_id,
    *,
    game_id=None,
    seed=None,
    terminal_winner=None,
    finish=True,
    metadata_update=None,
    agent_state=None,
):
    game_id = game_id or str(uuid.uuid4())
    seed = run.seed + 100_000 + run.match_index if seed is None else seed
    log = _action_log(
        game_id, seed=seed, terminal_winner=terminal_winner, finish=finish
    )
    metadata = _arena_metadata(run, match_id, seed)
    if metadata_update:
        metadata["arena"].update(metadata_update)
    store = MatchArchiveStore(archive_dir)
    envelope = store.create(
        log,
        metadata=metadata,
        agent_state=(
            capture_agent_state(MCTSAgent(seed=seed))
            if agent_state is None
            else agent_state
        ),
        public={"snapshot": None, "events": []},
    )
    return store, envelope


def _manager(archive_dir, arena_path):
    return WebGameManager(
        seed=17,
        archive_store=MatchArchiveStore(archive_dir),
        arena_store=ArenaStore(arena_path),
    )


def test_jaraxxus_archive_restore_preserves_setup_header_and_replays_to_completion(
    tmp_path,
):
    """A real hero transformation must not rewrite the setup used for replay."""

    game_id = "c7012040-8afc-4c6c-a019-f6419c47e859"
    starting_warlock_deck = ["EX1_323"] + ["CS2_231"] * 29
    players = (
        Player("Warlock", starting_warlock_deck, CardClass.WARLOCK.default_hero),
        Player("Mage", ["CS2_231"] * 30, CardClass.MAGE.default_hero),
    )
    game = Game(players, seed=4)
    log = ActionLog(
        game,
        source_revision="archive-recovery-test",
        game_id=game_id,
        mode="normal",
        seed=4,
    )
    store = MatchArchiveStore(tmp_path / "matches")
    envelope = store.create(log, metadata={"mode": "normal"}, public={})
    revision = envelope["revision"]

    def save_log(value):
        nonlocal revision
        revision = store.save(
            game_id, log=value, expected_revision=revision
        )["revision"]

    log.on_save = save_log
    source_session = GameSession(game, {}, action_log=log)
    restored_session = None
    try:
        source_session.start()
        for _ in range(2):
            source_session.execute(decision_player(game), Action(type="MULLIGAN"))

        warlock = game.players[0]
        for _ in range(40):
            if warlock.max_mana >= 9 and any(
                card.id == "EX1_323" for card in warlock.hand
            ):
                break
            actor = decision_player(game)
            assert actor is not None
            assert any(
                action.type == "END_TURN"
                for action in source_session.legal_actions(actor)
            )
            source_session.execute(actor, Action(type="END_TURN"))
        else:
            raise AssertionError("Warlock did not reach a playable Jaraxxus")

        jaraxxus = next(card for card in warlock.hand if card.id == "EX1_323")
        play_jaraxxus = next(
            action
            for action in source_session.legal_actions(warlock)
            if action.type == "PLAY_CARD"
            and action.source_entity_id == jaraxxus.entity_id
        )
        source_session.execute(
            warlock,
            play_jaraxxus,
        )
        assert warlock.hero.id == "EX1_323h"

        archived_before_resume = store.get(game_id)
        original_player_header = archived_before_resume["log"]["players"][0]
        assert original_player_header["hero_id"] == "HERO_07"
        assert original_player_header["resolved_hero_id"] == "HERO_07"
        assert original_player_header["deck_card_ids"] == starting_warlock_deck
        assert original_player_header["resolved_deck_card_ids"] == starting_warlock_deck

        restored_session = restore_action_log(
            archived_before_resume["log"], on_save=save_log
        )
        assert normalized_game_state(restored_session.game) == normalized_game_state(
            game
        )
        assert restored_session.game.players[0].hero.id == "EX1_323h"
        assert restored_session.action_log.to_dict()["players"][0] == original_player_header

        with pytest.raises(GameOver):
            restored_session.execute(
                decision_player(restored_session.game), Action(type="CONCEDE")
            )

        completed = store.get(game_id)["log"]
        assert completed["status"] == "complete"
        assert completed["players"][0] == original_player_header
        assert completed["actions"][:-1] == archived_before_resume["log"]["actions"]
        assert completed["actions"][-1]["action"]["type"] == "CONCEDE"

        replayed = replay_action_log(completed)
        assert normalized_game_state(replayed) == normalized_game_state(
            restored_session.game
        )
    finally:
        if restored_session is not None:
            restored_session.close()
        source_session.close()
        store.close()


def test_archive_callback_write_failure_returns_http_503_and_rejects_retry(
    tmp_path, monkeypatch
):
    archive_store = MatchArchiveStore(tmp_path / "matches")
    manager = WebGameManager(seed=23, archive_store=archive_store)
    try:
        with _http_server(manager) as base:
            status, state = _request(
                base,
                "/api/start",
                {"nickname": "Fail-closed tester", "locale": "zhCN"},
            )
            assert status == 200 and state["mode"] == "match"
            before = archive_store.list()[0]
            original_revision = before["revision"]
            original_actions = before["log"]["actions"]
            action = next(
                value for value in state["legal_actions"] if value["type"] == "MULLIGAN"
            )
            payload = {
                "session_id": state["session_id"],
                "revision": state["revision"],
                "action": action,
            }
            real_save = archive_store.save
            failed = False

            def fail_first_write(game_id, **kwargs):
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("simulated archive write failure")
                return real_save(game_id, **kwargs)

            monkeypatch.setattr(archive_store, "save", fail_first_write)
            failed_status, failed_response = _request(base, "/api/action", payload)
            assert failed_status == 503, failed_response
            assert "archive" in failed_response["error"].lower()

            retry_status, retry_response = _request(base, "/api/action", payload)
            assert retry_status == 503, retry_response
            assert "latest durable checkpoint" in retry_response["error"]
            after = archive_store.get(before["game_id"])
            assert after["revision"] == original_revision
            assert after["log"]["actions"] == original_actions
            assert manager.active.archive_failed is not None
    finally:
        manager.close()


def test_signature_mismatch_preserves_in_progress_archive_for_explicit_abandon(
    tmp_path,
):
    game_id = "b1012040-8afc-4c6c-a019-f6419c47e859"
    seed = 37
    log = _action_log(game_id, seed=seed, mode="normal")
    archive_store = MatchArchiveStore(tmp_path / "matches")
    envelope = archive_store.create(
        log,
        metadata={
            "mode": "normal",
            "opponent": "radical",
            "seed": seed,
            "locale": "enUS",
            "human_seat": 0,
        },
        agent_state=capture_agent_state(RadicalAgent(seed=seed)),
        public={"snapshot": None, "events": []},
    )
    bad_log = copy.deepcopy(envelope["log"])
    bad_log["replay"]["code_signature"] = "different-engine-signature"
    corrupted = archive_store.save(
        game_id,
        log=bad_log,
        expected_revision=envelope["revision"],
    )
    manager = WebGameManager(
        seed=seed,
        archive_store=MatchArchiveStore(tmp_path / "matches"),
    )
    try:
        with pytest.raises(WebLifecycleError) as mismatch:
            manager.resume_match(
                {"game_id": game_id, "revision": corrupted["revision"]}
            )
        assert mismatch.value.status_code == 409
        preserved = manager._archive_store.get(game_id)
        assert preserved["revision"] == corrupted["revision"]
        assert preserved["log"]["status"] == "in_progress"
        assert preserved["log"]["replay"]["code_signature"] == "different-engine-signature"
        with pytest.raises(WebLifecycleError) as unfinished:
            manager.match_download(game_id)
        assert unfinished.value.status_code == 409

        abandoned = manager.abandon_match(
            {"game_id": game_id, "revision": corrupted["revision"]}
        )
        assert abandoned["match"]["status"] == "abandoned"
        _downloaded_id, downloaded = manager.match_download(game_id)
        assert downloaded["status"] == "abandoned"
        assert downloaded["replay"]["code_signature"] == "different-engine-signature"
    finally:
        manager.close()
        archive_store.close()


def test_terminal_record_before_finish_recovers_and_settles_arena_loss_once(
    tmp_path,
):
    arena_path, run, match_id, _arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a1012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, envelope = _create_arena_archive(
        archive_dir,
        run,
        match_id,
        game_id=game_id,
        terminal_winner=False,
        finish=False,
    )
    try:
        assert envelope["log"]["status"] == "in_progress"
        assert envelope["log"]["actions"][-1]["action"]["type"] == "CONCEDE"

        manager = _manager(archive_dir, arena_path)
        try:
            arena = manager.arena_state()
            assert arena["mode"] == "resume"
            resumed = manager.resume_match(
                {"game_id": game_id, "revision": envelope["revision"]}
            )
            assert resumed["state"]["outcome"]["human_won"] is False
            completed = manager._archive_store.get(game_id)
            assert completed["log"]["status"] == "complete"
            assert manager.arena_state()["losses"] == 1
            assert manager.arena_state()["wins"] == 0
        finally:
            manager.close()

        after_restart = _manager(archive_dir, arena_path)
        try:
            state = after_restart.arena_state()
            assert (state["wins"], state["losses"]) == (0, 1)
            assert state["mode"] == "ready"
        finally:
            after_restart.close()
    finally:
        archive_store.close()


def test_terminal_win_checkpoint_cannot_be_abandoned_and_resume_counts_win_once(
    tmp_path,
):
    arena_path, run, match_id, _arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a2012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, envelope = _create_arena_archive(
        archive_dir,
        run,
        match_id,
        game_id=game_id,
        terminal_winner=True,
        finish=False,
    )
    manager = None
    try:
        manager = _manager(archive_dir, arena_path)
        with pytest.raises(WebLifecycleError) as rejected:
            manager.abandon_match(
                {"game_id": game_id, "revision": envelope["revision"]}
            )
        assert rejected.value.status_code == 409
        still_pending = manager._archive_store.get(game_id)
        assert still_pending["revision"] == envelope["revision"]
        assert still_pending["metadata"].get("status") != "abandoned"
        assert manager._arena_locked().run.losses == 0
        assert manager._arena_locked().run.wins == 0

        resumed = manager.resume_match(
            {"game_id": game_id, "revision": envelope["revision"]}
        )
        assert resumed["state"]["outcome"]["human_won"] is True
        settled = manager.arena_state()
        assert (settled["wins"], settled["losses"]) == (1, 0)
        assert manager._archive_store.get(game_id)["log"]["status"] == "complete"
    finally:
        if manager is not None:
            manager.close()
        archive_store.close()

    restarted = _manager(archive_dir, arena_path)
    try:
        state = restarted.arena_state()
        assert (state["wins"], state["losses"]) == (1, 0)
    finally:
        restarted.close()


def test_abandon_intent_is_reconciled_after_arena_result_write_failure(tmp_path, monkeypatch):
    arena_path, run, match_id, _arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a3012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, envelope = _create_arena_archive(
        archive_dir, run, match_id, game_id=game_id
    )
    manager = _manager(archive_dir, arena_path)
    try:
        manager.arena_state()

        def fail_arena_write(*_args, **_kwargs):
            raise OSError("simulated crash before Arena loss was written")

        monkeypatch.setattr(manager._arena_store, "save", fail_arena_write)
        with pytest.raises(WebLifecycleError) as failure:
            manager.abandon_match(
                {"game_id": game_id, "revision": envelope["revision"]}
            )
        assert failure.value.status_code == 503
        abandoned = manager._archive_store.get(game_id)
        assert abandoned["metadata"]["status"] == "abandoned"
        assert abandoned["revision"] == envelope["revision"] + 1
        assert manager._arena_locked().run.losses == 0
    finally:
        manager.close()
        archive_store.close()

    restarted = _manager(archive_dir, arena_path)
    try:
        state = restarted.arena_state()
        assert (state["wins"], state["losses"]) == (0, 1)
        assert state["mode"] == "ready"
        assert restarted.arena_state()["losses"] == 1
    finally:
        restarted.close()


def test_corrupt_pending_arena_archive_does_not_reset_run_to_ready(tmp_path):
    arena_path, run, match_id, arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a4012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, _envelope = _create_arena_archive(
        archive_dir, run, match_id, game_id=game_id
    )
    manager = _manager(archive_dir, arena_path)
    try:
        archive_path = archive_dir / f"{game_id}.json"
        archive_path.write_text("{corrupt archive", encoding="utf-8")
        with pytest.raises(WebLifecycleError) as corrupt:
            manager.arena_state()
        assert corrupt.value.status_code == 409
        persisted = arena_store.load()
        assert persisted is not None
        assert persisted.stage == "match"
        assert persisted.pending_match_id == match_id
    finally:
        manager.close()
        archive_store.close()


def test_arena_resume_rejects_run_mismatch_before_mutating_archive(tmp_path, monkeypatch):
    arena_path, run, match_id, _arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a5012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, envelope = _create_arena_archive(
        archive_dir,
        run,
        match_id,
        game_id=game_id,
        metadata_update={"run_id": str(uuid.uuid4())},
    )
    manager = _manager(archive_dir, arena_path)
    try:
        monkeypatch.setattr(
            web_server,
            "restore_action_log",
            lambda _log: pytest.fail("run identity must be checked before replay"),
        )
        with pytest.raises(WebLifecycleError) as mismatch:
            manager.resume_match(
                {"game_id": game_id, "revision": envelope["revision"]}
            )
        assert mismatch.value.status_code == 409
        assert manager.active is None
        unchanged = manager._archive_store.get(game_id)
        assert unchanged["revision"] == envelope["revision"]
        assert unchanged["metadata"]["arena"]["run_id"] != run.run_id
    finally:
        manager.close()
        archive_store.close()


def test_arena_resume_failure_after_replay_closes_entity_index(tmp_path, monkeypatch):
    arena_path, run, match_id, _arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a6012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, envelope = _create_arena_archive(
        archive_dir,
        run,
        match_id,
        game_id=game_id,
        agent_state={"kind": "heuristic"},
    )
    manager = _manager(archive_dir, arena_path)
    captured = []
    original_restore = web_server.restore_action_log

    def capture_restored_session(log):
        session = original_restore(log)
        captured.append(session)
        return session

    try:
        monkeypatch.setattr(web_server, "restore_action_log", capture_restored_session)
        with pytest.raises(WebLifecycleError) as failure:
            manager.resume_match(
                {"game_id": game_id, "revision": envelope["revision"]}
            )
        assert failure.value.status_code == 409
        assert len(captured) == 1
        session = captured[0]
        assert session.index not in session.game.manager.observers
        assert manager.active is None
        assert manager._archive_store.get(game_id)["revision"] == envelope["revision"]
    finally:
        manager.close()
        archive_store.close()


def test_completed_arena_win_cannot_be_changed_to_loss_by_abandon(tmp_path):
    arena_path, run, match_id, _arena_store, archive_dir = _arena_files(tmp_path)
    game_id = "a7012040-8afc-4c6c-a019-f6419c47e859"
    archive_store, envelope = _create_arena_archive(
        archive_dir,
        run,
        match_id,
        game_id=game_id,
        terminal_winner=True,
        finish=True,
    )
    manager = _manager(archive_dir, arena_path)
    try:
        with pytest.raises(WebLifecycleError) as rejected:
            manager.abandon_match(
                {"game_id": game_id, "revision": envelope["revision"]}
            )
        assert rejected.value.status_code == 409
        assert manager._archive_store.get(game_id)["log"]["status"] == "complete"
        state = manager.arena_state()
        assert (state["wins"], state["losses"]) == (1, 0)
    finally:
        manager.close()
        archive_store.close()
