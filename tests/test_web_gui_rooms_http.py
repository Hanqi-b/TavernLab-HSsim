"""Authenticated HTTP integration for the process-wide room registry."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from fireplace.web_gui.account_game import AccountGameRegistry
from fireplace.web_gui.accounts import AccountStore
from fireplace.web_gui.server import make_server


@contextmanager
def room_server(tmp_path, *, idle_seconds: float = 300):
    accounts = AccountStore(tmp_path / "accounts.sqlite3")
    registry = AccountGameRegistry(
        accounts=accounts,
        data_root=tmp_path / "users",
        seed=17,
        idle_seconds=idle_seconds,
        legacy_decks=tmp_path / "missing-decks.json",
        legacy_arena=tmp_path / "missing-arena.json",
    )
    server = make_server(registry, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield accounts, registry, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


class Browser:
    def __init__(self, base: str):
        self.base = base
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def request(self, path: str, payload: object = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if data is not None:
            headers["Origin"] = self.base
        request = Request(self.base + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def register(self, username: str):
        status, payload = self.request(
            "/api/account/register",
            {"username": username, "password": "local-password-123"},
        )
        assert status == 200, payload
        return payload["account"]


def test_accounts_create_join_isolated_state_and_restore_after_restart(tmp_path):
    with room_server(tmp_path) as (accounts, _registry, base):
        alice = Browser(base)
        bob = Browser(base)
        carol = Browser(base)
        alice_account = alice.register("Alice")
        bob_account = bob.register("Bob")
        carol.register("Carol")

        status, created = alice.request(
            "/api/rooms/create", {"nickname": "Alice", "locale": "enUS"}
        )
        assert status == 200 and created["mode"] == "lobby"
        waiting = created["room"]
        assert waiting["status"] == "waiting"
        assert waiting["seat"] == 0
        assert waiting["invite_code"]
        invite = waiting["invite_code"]

        status, current = alice.request("/api/rooms/current")
        assert status == 200 and current["room"]["id"] == waiting["id"]
        assert current["room"].get("invite_code") is None
        status, carol_state = carol.request("/api/state")
        assert status == 200 and carol_state["mode"] == "lobby"

        status, joined = bob.request(
            "/api/rooms/join",
            {"code": invite, "nickname": "Bob", "locale": "zhCN"},
        )
        assert status == 200 and joined["mode"] == "match"
        assert joined["room"]["status"] == "playing"
        assert joined["room"]["seat"] == 1
        assert {p["nickname"] for p in joined["room"]["participants"]} == {"Alice", "Bob"}

        status, alice_state = alice.request("/api/state")
        assert status == 200 and alice_state["mode"] == "match"
        assert alice_state["room"]["seat"] == 0
        status, bob_state = bob.request("/api/state")
        assert status == 200 and bob_state["room"]["seat"] == 1
        assert alice_state["session_id"] == bob_state["session_id"]
        assert alice_state["revision"] == bob_state["revision"]

        status, rejected = carol.request(
            "/api/rooms/join", {"code": invite, "nickname": "Carol", "locale": "zhCN"}
        )
        assert status in (404, 409)
        assert rejected["mode"] == "lobby"

        # Reusing the creator's authenticated session remains account-scoped.
        assert alice_account["id"] != bob_account["id"]
        status, current = bob.request("/api/rooms/current")
        assert status == 200 and current["room"]["seat"] == 1

    # The room record is process-wide and survives manager/server teardown.
    with room_server(tmp_path) as (_accounts_again, _registry_again, base_again):
        alice_again = Browser(base_again)
        bob_again = Browser(base_again)
        # AccountStore tokens are durable; log in again also exercises the
        # normal reconnect path when a browser did not retain its cookie.
        assert alice_again.register("Alice-2")["id"]
        status, login = alice_again.request(
            "/api/account/login",
            {"username": "Alice", "password": "local-password-123"},
        )
        assert status == 200, login
        status, state = alice_again.request("/api/state")
        assert status == 200 and state["mode"] == "match"
        assert state["room"]["seat"] == 0

        status, login = bob_again.request(
            "/api/account/login",
            {"username": "Bob", "password": "local-password-123"},
        )
        assert status == 200, login
        status, restored = bob_again.request("/api/state")
        assert status == 200 and restored["mode"] == "match"
        assert restored["room"]["seat"] == 1
        assert restored["revision"] == state["revision"]

        # The restored action log remains authoritative: a stale revision is
        # rejected for the authenticated seat and cannot affect the other.
        status, rejected = bob_again.request(
            "/api/action",
            {"session_id": restored["session_id"], "revision": restored["revision"] - 1, "action": {}},
        )
        assert status == 409 and rejected["revision"] == restored["revision"]


def test_account_manager_eviction_keeps_shared_waiting_room(tmp_path):
    with room_server(tmp_path, idle_seconds=0) as (_accounts, registry, base):
        alice = Browser(base)
        bob = Browser(base)
        alice.register("Alice")
        bob.register("Bob")
        status, created = alice.request(
            "/api/rooms/create", {"nickname": "Alice", "locale": "enUS"}
        )
        assert status == 200
        room_id = created["room"]["id"]
        invite = created["room"]["invite_code"]

        assert registry.evict_idle() == 1
        status, current = alice.request("/api/rooms/current")
        assert status == 200 and current["room"]["id"] == room_id

        status, joined = bob.request(
            "/api/rooms/join", {"code": invite, "nickname": "Bob", "locale": "zhCN"}
        )
        assert status == 200 and joined["room"]["id"] == room_id
