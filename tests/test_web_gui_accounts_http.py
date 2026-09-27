"""Account cookies scope saved decks, Arena runs, and live matches."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest

from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore
from fireplace.web_gui.account_game import AccountGameRegistry
from fireplace.web_gui.accounts import AccountStore
from fireplace.web_gui.decks import DeckStore
from fireplace.web_gui.server import make_server
from tests.test_web_gui_saved_deck_match import _neutral_minions


@contextmanager
def account_server(tmp_path, *, legacy_decks=None, legacy_arena=None):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    registry = AccountGameRegistry(
        accounts=accounts,
        data_root=tmp_path / "users",
        seed=31,
        legacy_decks=legacy_decks or tmp_path / "missing-legacy-decks.json",
        legacy_arena=legacy_arena or tmp_path / "missing-legacy-arena.json",
    )
    server = make_server(registry, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_account_data_root_honors_tavernlab_alias_and_legacy_fallback(
    monkeypatch, tmp_path
):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    tavernlab_root = tmp_path / "tavernlab-users"
    fireplace_root = tmp_path / "fireplace-users"
    monkeypatch.setenv("TAVERNLAB_ACCOUNT_DATA_ROOT", str(tavernlab_root))
    monkeypatch.setenv("FIREPLACE_ACCOUNT_DATA_ROOT", str(fireplace_root))

    registry = AccountGameRegistry(accounts=accounts, catalog=object())
    assert registry.data_root == tavernlab_root

    monkeypatch.delenv("TAVERNLAB_ACCOUNT_DATA_ROOT")
    registry = AccountGameRegistry(accounts=accounts, catalog=object())
    assert registry.data_root == fireplace_root

    monkeypatch.delenv("FIREPLACE_ACCOUNT_DATA_ROOT")
    registry = AccountGameRegistry(accounts=accounts, catalog=object())
    assert registry.data_root == tmp_path / "users"


class Browser:
    def __init__(self, base: str):
        self.base = base
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, path: str, payload: object = None, *, origin: bool = True):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if data is not None and origin:
            headers["Origin"] = self.base
        request = Request(self.base + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=15) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def register(self, username: str):
        status, payload = self.request("/api/account/register", {
            "username": username, "password": "local-password-123",
        })
        assert status == 200 and payload["authenticated"] is True
        return payload["account"]


def test_two_accounts_cannot_read_or_start_each_others_decks_and_matches(tmp_path):
    with account_server(tmp_path) as base:
        alice = Browser(base)
        bob = Browser(base)
        assert alice.request("/api/decks")[0] == 401
        assert alice.request("/api/state")[0] == 401
        assert alice.request("/api/arena/state")[0] == 401
        alice_id = alice.register("Alice")["id"]
        bob_id = bob.register("Bob")["id"]
        assert alice_id != bob_id
        assert alice.request("/api/decks/save", {
            "name": "Blocked", "hero_id": "HERO_08", "card_ids": [],
        }, origin=False)[0] == 403

        cards = _neutral_minions(30)
        status, saved = alice.request("/api/decks/save", {
            "name": "Alice deck", "hero_id": "HERO_08", "card_ids": cards,
        })
        assert status == 200, saved
        deck_id = saved["saved_id"]
        assert [deck["name"] for deck in bob.request("/api/decks")[1]["decks"]] == []
        status, rejected = bob.request("/api/start", {
            "nickname": "Bob", "locale": "zhCN", "deck_id": deck_id,
        })
        assert status == 400 and "unknown deck" in rejected["error"]
        status, own = alice.request("/api/start", {
            "nickname": "Alice", "locale": "zhCN", "deck_id": deck_id,
        })
        assert status == 200 and own["mode"] == "match"
        status, other = bob.request("/api/start", {"nickname": "Bob", "locale": "zhCN"})
        assert status == 200 and other["mode"] == "match"
        assert own["session_id"] != other["session_id"]
        assert alice.request("/api/state")[1]["session_id"] == own["session_id"]
        assert bob.request("/api/state")[1]["session_id"] == other["session_id"]

        own_concede = {"session_id": own["session_id"], "revision": own["revision"]}
        status, rejected = bob.request("/api/concede", own_concede)
        assert status == 409 and rejected["session_id"] == other["session_id"]
        assert bob.request("/api/state")[1]["outcome"] is None
        status, conceded = alice.request("/api/concede", own_concede)
        assert status == 200 and conceded["outcome"]["human_won"] is False
        assert bob.request("/api/state")[1]["outcome"] is None

        assert alice.request("/api/account/logout", {})[0] == 200
        assert alice.request("/api/state")[0] == 401
        assert alice.request("/api/concede", own_concede)[0] == 401
        assert bob.request("/api/state")[0] == 200


def test_arena_run_is_scoped_to_account(tmp_path):
    with account_server(tmp_path) as base:
        alice = Browser(base)
        bob = Browser(base)
        alice.register("Alice")
        bob.register("Bob")
        status, state = alice.request("/api/arena/state")
        assert status == 200 and state["mode"] == "setup"
        selected = [option["id"] for option in state["pack_options"]["large"][:5]]
        selected += [state["pack_options"]["small"][0]["id"]]
        status, started = alice.request("/api/arena/start", {
            "nickname": "Alice", "locale": "zhCN", "set_ids": selected,
        })
        assert status == 200 and started["mode"] == "hero"
        assert bob.request("/api/arena/state")[1]["mode"] == "setup"
        status, bob_started = bob.request("/api/arena/start", {
            "nickname": "Bob", "locale": "zhCN", "set_ids": selected,
        })
        assert status == 200 and bob_started["mode"] == "hero"
        assert bob_started["run_id"] != started["run_id"]


def test_legacy_deck_import_is_explicit_and_single_owner(tmp_path):
    old_path = tmp_path / "old-decks.json"
    DeckStore(old_path).put({
        "id": "legacy-deck", "revision": 1, "name": "Old deck",
        "hero_id": "HERO_08", "card_ids": [],
    })
    with account_server(tmp_path, legacy_decks=old_path) as base:
        alice = Browser(base)
        bob = Browser(base)
        alice_id = alice.register("Alice")["id"]
        bob.register("Bob")
        assert alice.request("/api/account/session")[1]["legacy_available"] is True
        assert alice.request("/api/decks")[1]["decks"] == []
        assert bob.request("/api/account/import-legacy", {"account_id": alice_id})[0] == 409
        status, result = alice.request("/api/account/import-legacy", {"account_id": alice_id})
        assert status == 200 and result["imported"] == {"decks": True, "arena": False}
        assert alice.request("/api/decks")[1]["decks"][0]["id"] == "legacy-deck"
        assert bob.request("/api/decks")[1]["decks"] == []
        assert bob.request("/api/account/import-legacy", {"account_id": alice_id})[0] == 409
    assert old_path.is_file()


def test_legacy_arena_run_is_imported_into_one_account(tmp_path):
    old_path = tmp_path / "old-arena.json"
    old_run = ArenaRun.create(
        ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"],
        "Former player", "zhCN", seed=7,
    )
    ArenaStore(old_path).save(old_run)
    with account_server(tmp_path, legacy_arena=old_path) as base:
        alice = Browser(base)
        bob = Browser(base)
        alice_id = alice.register("Alice")["id"]
        bob.register("Bob")
        assert alice.request("/api/arena/state")[1]["mode"] == "setup"
        status, result = alice.request("/api/account/import-legacy", {"account_id": alice_id})
        assert status == 200 and result["imported"] == {"decks": False, "arena": True}
        assert alice.request("/api/arena/state")[1]["run_id"] == old_run.run_id
        assert bob.request("/api/arena/state")[1]["mode"] == "setup"
    assert old_path.is_file()


def test_interrupted_legacy_import_resumes_identical_files(tmp_path, monkeypatch):
    old_decks = tmp_path / "old-decks.json"
    old_arena = tmp_path / "old-arena.json"
    DeckStore(old_decks).put({
        "id": "legacy-deck", "revision": 1, "name": "Old deck",
        "hero_id": "HERO_08", "card_ids": [],
    })
    ArenaStore(old_arena).save(ArenaRun.create(
        ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"],
        "Former player", "zhCN", seed=9,
    ))
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    account = accounts.register("Alice", "local-password-123")
    bob = accounts.register("Bob", "local-password-123")
    registry = AccountGameRegistry(
        accounts=accounts, data_root=tmp_path / "users",
        legacy_decks=old_decks, legacy_arena=old_arena,
    )
    real_copy = registry._atomic_copy

    def crash_before_arena(data, target):
        if target.name == "arena-run.json":
            raise KeyboardInterrupt("simulated process interruption")
        return real_copy(data, target)

    monkeypatch.setattr(registry, "_atomic_copy", crash_before_arena)
    with pytest.raises(KeyboardInterrupt):
        registry.import_legacy(account.id)
    assert (tmp_path / "users" / account.id / "decks.json").is_file()
    assert registry.legacy_available(account.id) is True
    assert registry.legacy_available(bob.id) is False
    with pytest.raises(ValueError, match="claimed by another account"):
        registry.import_legacy(bob.id)
    assert not (tmp_path / "users" / bob.id / "decks.json").exists()

    monkeypatch.setattr(registry, "_atomic_copy", real_copy)
    assert registry.import_legacy(account.id) == {"decks": True, "arena": True}
    assert (tmp_path / "users" / account.id / "arena-run.json").is_file()
    assert registry.legacy_available(account.id) is False


def test_idle_account_manager_releases_resources_and_shares_catalog(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    account = accounts.register("Alice", "local-password-123")
    registry = AccountGameRegistry(accounts=accounts, data_root=tmp_path / "users", idle_seconds=0)
    server = make_server(registry, host="127.0.0.1", port=0)
    try:
        assert server.catalog is registry.catalog
        game = registry.acquire(account.id)
        assert game._catalog is registry.catalog
        assert registry.evict_idle() == 0  # The active request holds a lease.
        registry.release(account.id)
        assert registry.evict_idle() == 1
        assert registry.acquire(account.id) is not game
        registry.release(account.id)
    finally:
        server.server_close()


def test_idle_eviction_waits_for_old_manager_to_release_owner(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    account = accounts.register("Alice", "local-password-123")
    registry = AccountGameRegistry(accounts=accounts, data_root=tmp_path / "users", idle_seconds=0)
    closing = threading.Event()
    may_close = threading.Event()
    acquired = threading.Event()

    class OldManager:
        active = None

        def close(self):
            closing.set()
            assert may_close.wait(3)

    old_manager = OldManager()
    registry._games[account.id] = old_manager
    registry._last_used[account.id] = 0
    evict_thread = threading.Thread(target=registry.evict_idle)
    acquire_thread = threading.Thread(target=lambda: (registry.acquire(account.id), acquired.set()))
    try:
        evict_thread.start()
        assert closing.wait(3)
        acquire_thread.start()
        assert not acquired.wait(0.1)
        may_close.set()
        evict_thread.join(3)
        acquire_thread.join(3)
        assert acquired.is_set()
        assert registry._games[account.id] is not old_manager
    finally:
        may_close.set()
        registry.release(account.id)
        registry.close()


def test_idle_eviction_finalizes_terminal_match_before_close(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    account = accounts.register("Alice", "local-password-123")
    registry = AccountGameRegistry(accounts=accounts, data_root=tmp_path / "users", idle_seconds=0)
    events = []

    class FinishedManager:
        active = object()

        def snapshot(self):
            return {"session_id": "finished", "revision": 8, "outcome": {"human_won": True}}

        def return_to_lobby(self, payload):
            events.append(("finalize", payload))

        def close(self):
            events.append(("close", None))

    registry._games[account.id] = FinishedManager()
    registry._last_used[account.id] = 0
    assert registry.evict_idle() == 1
    assert events == [
        ("finalize", {"session_id": "finished", "revision": 8}),
        ("close", None),
    ]


def test_broken_terminal_settlement_does_not_block_other_accounts(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    alice = accounts.register("Alice", "local-password-123")
    bob = accounts.register("Bob", "local-password-123")
    registry = AccountGameRegistry(accounts=accounts, data_root=tmp_path / "users", idle_seconds=0)
    attempts = []

    class BrokenTerminal:
        active = object()

        def snapshot(self):
            return {"session_id": "broken", "revision": 8, "outcome": {"human_won": True}}

        def return_to_lobby(self, _payload):
            attempts.append("settle")
            raise RuntimeError("arena store broken")

        def close(self):
            attempts.append("close")

    broken = BrokenTerminal()
    registry._games[alice.id] = broken
    registry._last_used[alice.id] = 0
    try:
        game = registry.acquire(bob.id)
        assert game is registry._games[bob.id]
        assert registry._games[alice.id] is broken
        assert attempts == ["settle"]
        registry.release(bob.id)
        registry.acquire(bob.id)
        assert attempts == ["settle"]  # Another request does not retry immediately.
        registry.release(bob.id)
    finally:
        registry._games.pop(alice.id, None)
        registry.close()
