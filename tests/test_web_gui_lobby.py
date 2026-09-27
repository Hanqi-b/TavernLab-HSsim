"""Lobby lifecycle and cross-match concurrency checks for the browser game."""

import threading
import time
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from fireplace.web_gui.server import WebGameManager
from tests.web_gui_support import (
    action,
    finish_lobby_match,
    lobby_server,
    request,
)


def test_lobby_start_locale_nickname_and_terminal_return(lobby_server):
    app, base = lobby_server()
    status, lobby = request(base)
    assert status == 200
    assert lobby == {"mode": "lobby", "opponent": "heuristic"}

    status, started = request(
        base,
        "/api/start",
        {"nickname": "  Alice  ", "locale": "enUS"},
    )
    assert status == 200
    assert started["mode"] == "match"
    assert started["locale"] == "enUS"
    assert started["nickname"] == "Alice"
    assert started["observation"]["phase"] == "MULLIGAN"

    status, rejected = request(
        base,
        "/api/start",
        {"nickname": "Second", "locale": "zhCN"},
    )
    assert status == 409 and rejected["session_id"] == started["session_id"]

    terminal = finish_lobby_match(app, base, state=started)
    status, lobby = request(
        base,
        "/api/return",
        {"session_id": terminal["session_id"], "revision": terminal["revision"]},
    )
    assert status == 200 and lobby["mode"] == "lobby"


def test_lobby_concede_finishes_match_and_rejects_retries(lobby_server):
    app, base = lobby_server()
    status, started = request(
        base,
        "/api/start",
        {"nickname": "Alice", "locale": "zhCN"},
    )
    assert status == 200 and started["mode"] == "match"
    payload = {
        "session_id": started["session_id"],
        "revision": started["revision"],
    }

    status, terminal = request(base, "/api/concede", payload)
    assert status == 200
    assert terminal["outcome"]["human_won"] is False
    assert terminal["outcome"]["winner"]
    assert terminal["revision"] == started["revision"] + 1

    active = app.active
    assert active is not None
    log = active.session.action_log.to_dict()
    assert log["status"] == "complete"
    assert log["finished_at"] is not None

    # A browser that retries the original request cannot concede again or
    # overwrite the terminal result with a stale revision.
    status, stale = request(base, "/api/concede", payload)
    assert status == 409
    assert stale["session_id"] == terminal["session_id"]
    assert stale["revision"] == terminal["revision"]

    status, repeated = request(
        base,
        "/api/concede",
        {
            "session_id": terminal["session_id"],
            "revision": terminal["revision"],
        },
    )
    assert status == 409 and repeated["error"] == "match is over"

    status, lobby = request(
        base,
        "/api/return",
        {
            "session_id": terminal["session_id"],
            "revision": terminal["revision"],
        },
    )
    assert status == 200 and lobby["mode"] == "lobby"
    status, no_match = request(base, "/api/concede", payload)
    assert status == 409 and no_match["error"] == "no active match"


def test_lobby_rejects_removed_random_policy(lobby_server):
    with pytest.raises(ValueError, match="heuristic"):
        WebGameManager(opponent="random")
    app, base = lobby_server()
    status, rejected = request(
        base,
        "/api/start",
        {"nickname": "Alice", "opponent": "random", "locale": "zhCN"},
    )
    assert status == 400
    assert rejected["mode"] == "lobby"
    assert app.active is None


def test_lobby_rejects_stale_actions_after_return_and_new_match(lobby_server):
    app, base = lobby_server(seed=21)
    first_terminal = finish_lobby_match(app, base)
    old_action = (
        action(first_terminal, "END_TURN")
        if first_terminal["legal_actions"]
        else {"schema_version": 1, "type": "END_TURN"}
    )
    status, lobby = request(
        base,
        "/api/return",
        {
            "session_id": first_terminal["session_id"],
            "revision": first_terminal["revision"],
        },
    )
    assert status == 200 and lobby["mode"] == "lobby"

    status, stale = request(
        base,
        "/api/action",
        {
            "session_id": first_terminal["session_id"],
            "revision": first_terminal["revision"],
            "action": old_action,
        },
    )
    assert status == 409 and stale["mode"] == "lobby"

    status, second = request(
        base,
        "/api/start",
        {"nickname": "Bob", "locale": "zhCN"},
    )
    assert status == 200 and second["session_id"] != first_terminal["session_id"]
    status, stale = request(
        base,
        "/api/action",
        {
            "session_id": first_terminal["session_id"],
            "revision": first_terminal["revision"],
            "action": old_action,
        },
    )
    assert status == 409
    assert stale["session_id"] == second["session_id"]


def test_lobby_start_and_return_keep_local_http_guards(lobby_server):
    _app, base = lobby_server()
    status, rejected = request(
        base,
        "/api/start",
        {"nickname": "Alice", "locale": "zhCN"},
        {"Origin": "http://attacker.example"},
    )
    assert status == 403 and rejected["mode"] == "lobby"
    status, rejected = request(
        base,
        "/api/start",
        {"nickname": "Alice", "locale": "zhCN"},
        {"Content-Type": "text/plain"},
    )
    assert status == 415 and rejected["mode"] == "lobby"

    status, started = request(
        base,
        "/api/start",
        {"nickname": "Alice", "locale": "zhCN"},
    )
    assert status == 200
    payload = {"session_id": started["session_id"], "revision": started["revision"]}
    status, rejected = request(
        base,
        "/api/concede",
        payload,
        {"Origin": "http://attacker.example"},
    )
    assert status == 403 and rejected["session_id"] == started["session_id"]
    status, rejected = request(
        base,
        "/api/concede",
        payload,
        {"Content-Type": "text/plain"},
    )
    assert status == 415 and rejected["session_id"] == started["session_id"]


def test_return_to_lobby_does_not_wait_for_slow_asset_resolver(lobby_server):
    resolving = threading.Event()
    release = threading.Event()

    class SlowResolver:
        def describe(self, card_id, *, locale):
            del card_id, locale
            return None

        def resolve(self, card_id, *, kind, locale):
            del card_id, kind, locale
            resolving.set()
            release.wait(timeout=10)
            return None

    app, base = lobby_server(asset_resolver=SlowResolver())
    terminal = finish_lobby_match(app, base)
    card_id = terminal["observation"]["self"]["hand"][0]["card_id"]
    try:
        with urlopen(base + "/assets/render/" + card_id, timeout=3) as response:
            assert response.status == 202
            response.read()
        assert resolving.wait(timeout=3)

        started = time.monotonic()
        status, lobby = request(
            base,
            "/api/return",
            {
                "session_id": terminal["session_id"],
                "revision": terminal["revision"],
            },
        )
        elapsed = time.monotonic() - started
        assert status == 200 and lobby["mode"] == "lobby"
        assert elapsed < 1.0

        started = time.monotonic()
        status, current = request(base)
        elapsed = time.monotonic() - started
        assert status == 200 and current["mode"] == "lobby"
        assert elapsed < 1.0
    finally:
        release.set()


def test_manager_snapshot_does_not_wait_for_active_asset_call(monkeypatch):
    class Resolver:
        def describe(self, card_id, *, locale):
            del card_id, locale
            return None

        def resolve(self, card_id, *, kind, locale):
            del card_id, kind, locale
            return None

    manager = WebGameManager(seed=23, asset_resolver=Resolver())
    asset_started = threading.Event()
    release_asset = threading.Event()
    snapshot_done = threading.Event()
    asset_result = []
    snapshot_result = []
    try:
        started = manager.start_match({"nickname": "Alice", "locale": "zhCN"})
        active = manager.active
        assert active is not None
        card_id = started["observation"]["self"]["hand"][0]["card_id"]

        def blocking_asset(kind, requested_card_id):
            assert kind == "render"
            assert requested_card_id == card_id
            asset_started.set()
            assert release_asset.wait(timeout=5)
            return None

        monkeypatch.setattr(active, "asset", blocking_asset)
        asset_thread = threading.Thread(
            target=lambda: asset_result.append(manager.asset("render", card_id)),
            daemon=True,
        )
        asset_thread.start()
        assert asset_started.wait(timeout=3)

        def read_snapshot():
            snapshot_result.append(manager.snapshot())
            snapshot_done.set()

        snapshot_thread = threading.Thread(target=read_snapshot, daemon=True)
        snapshot_thread.start()
        # The asset call is still blocked.  A manager-level lock around the
        # active call would keep this state request from completing.
        assert snapshot_done.wait(timeout=1)
        assert snapshot_result[0]["session_id"] == started["session_id"]
    finally:
        release_asset.set()
        if "asset_thread" in locals():
            asset_thread.join(timeout=5)
        if "snapshot_thread" in locals():
            snapshot_thread.join(timeout=5)
        manager.close()
    assert asset_result == [None]


def test_manager_reuses_asset_service_across_overlapping_matches(lobby_server):
    first_description_started = threading.Event()
    release_first_description = threading.Event()
    overlapping_description = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    class RacingResolver:
        def describe(self, card_id, *, locale):
            nonlocal calls
            with calls_lock:
                call = calls
                calls += 1
            if call == 0:
                first_description_started.set()
                assert release_first_description.wait(timeout=5)
            elif not release_first_description.is_set():
                # Separate AssetService instances let a new match enter the
                # resolver while the previous match is still initializing its
                # catalog.  AssetResolver can then return an ID fallback.
                overlapping_description.set()
                return SimpleNamespace(name=card_id, text="", locale="und")
            return SimpleNamespace(name=f"Card {card_id}", text="", locale=locale)

        def resolve(self, card_id, *, kind, locale):
            del card_id, kind, locale
            return None

    resolver = RacingResolver()
    app, base = lobby_server(asset_resolver=resolver)
    try:
        terminal = finish_lobby_match(app, base)
        assert first_description_started.wait(timeout=5)

        status, lobby = request(
            base,
            "/api/return",
            {"session_id": terminal["session_id"], "revision": terminal["revision"]},
        )
        assert status == 200 and lobby["mode"] == "lobby"

        status, second = request(
            base,
            "/api/start",
            {"nickname": "Bob", "locale": "zhCN"},
        )
        assert status == 200 and second["mode"] == "match"
        # The second match may queue a description, but it must not enter the
        # resolver until the first match's call has finished.
        assert not overlapping_description.is_set()
    finally:
        release_first_description.set()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status, current = request(base)
        assert status == 200
        if all(
            card.get("name", "").startswith("Card ")
            for card in current["observation"]["self"]["hand"]
        ):
            break
        time.sleep(0.02)
    assert current["observation"]["self"]["hand"]
    assert all(
        card.get("name", "").startswith("Card ")
        for card in current["observation"]["self"]["hand"]
    )
    assert not overlapping_description.is_set()
