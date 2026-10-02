"""Arena HTTP lifecycle, including the existing match boundary."""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from fireplace.arena.store import ArenaStore, default_state_path
from fireplace.web_gui.server import WebGameManager, make_server
from tests.web_gui_support import finish_lobby_match, request


SETS = ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"]


def test_default_state_path_honors_tavernlab_override_and_legacy_fallback(
    monkeypatch, tmp_path
):
    tavernlab_override = tmp_path / "tavernlab" / "arena-run.json"
    fireplace_override = tmp_path / "fireplace" / "arena-run.json"
    monkeypatch.setenv("TAVERNLAB_ARENA_STATE", str(tavernlab_override))
    monkeypatch.setenv("FIREPLACE_ARENA_STATE", str(fireplace_override))
    assert default_state_path() == tavernlab_override

    monkeypatch.delenv("TAVERNLAB_ARENA_STATE")
    assert default_state_path() == fireplace_override
    monkeypatch.delenv("FIREPLACE_ARENA_STATE")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert default_state_path() == Path.home() / ".local" / "state" / "fireplace" / "arena-run.json"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_state_path() == tmp_path / "state" / "fireplace" / "arena-run.json"


@pytest.fixture
def arena_http(tmp_path):
    app = WebGameManager(seed=17, arena_store=ArenaStore(tmp_path / "arena.json"))
    server = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _command(base, path, state, **fields):
    return request(
        base,
        path,
        {"run_id": state["run_id"], "revision": state["revision"], **fields},
    )


def test_arena_http_draft_to_real_battle_and_record(arena_http):
    app, base = arena_http
    status, state = request(base, "/api/arena/state")
    assert status == 200 and state["mode"] == "setup"
    assert state["pack_options"]["basic"]["id"] == "BASIC"
    assert state["pack_options"]["classic"]["id"] == "EXPERT1"
    assert "EXPERT1" not in {pack["id"] for pack in state["pack_options"]["large"]}
    assert len(state["pack_options"]["large"]) >= 5
    assert len(state["pack_options"]["small"]) >= 4

    with urlopen(base + "/arena") as response:
        assert response.status == 200
        assert b"arena_app.js" in response.read()

    status, invalid = request(
        base,
        "/api/arena/start",
        {"nickname": "Tester", "locale": "zhCN", "set_ids": ["GVG"]},
    )
    assert status == 400 and invalid["mode"] == "setup"

    status, state = request(
        base,
        "/api/arena/start",
        {"nickname": "Tester", "locale": "zhCN", "set_ids": SETS},
    )
    assert status == 200 and state["mode"] == "hero"
    assert len(state["hero_offer"]) == 3
    status, stale = _command(
        base, "/api/arena/hero", {**state, "revision": -1},
        hero_id=state["hero_offer"][0]["id"],
    )
    assert status == 409 and stale["mode"] == "hero"

    status, state = _command(
        base, "/api/arena/hero", state,
        hero_id=state["hero_offer"][0]["id"],
    )
    assert status == 200 and state["mode"] == "draft"
    for _ in range(30):
        assert len({card["id"] for card in state["card_offer"]}) == 3
        status, state = _command(
            base, "/api/arena/pick", state,
            card_id=state["card_offer"][0]["id"],
        )
        assert status == 200
    assert state["mode"] == "ready" and len(state["deck"]) == 30

    status, state = _command(base, "/api/arena/battle", state)
    assert status == 200 and state["mode"] == "match"
    assert state["match_url"] == "/?arena=1"
    status, game = request(base)
    assert status == 200 and game["mode"] == "match"
    terminal = finish_lobby_match(app, base, state=game)
    status, recorded = request(base, "/api/arena/state")
    assert status == 200 and (recorded["wins"], recorded["losses"]) == (1, 0)
    status, lobby = request(
        base, "/api/return",
        {"session_id": terminal["session_id"], "revision": terminal["revision"]},
    )
    assert status == 200 and lobby["arena_redirect"] is True
    status, run = request(base, "/api/arena/state")
    assert status == 200 and run["mode"] == "ready"
    assert (run["wins"], run["losses"]) == (1, 0)

    # The next Arena battle uses the same ready deck.  Conceding must count as
    # one loss immediately, and returning the terminal match must not count it
    # a second time.
    status, battle = _command(base, "/api/arena/battle", run)
    assert status == 200 and battle["mode"] == "match"
    status, game = request(base)
    assert status == 200 and game["mode"] == "match"
    concede = {
        "session_id": game["session_id"],
        "revision": game["revision"],
    }
    status, terminal_loss = request(base, "/api/concede", concede)
    assert status == 200 and terminal_loss["outcome"]["human_won"] is False
    status, arena_after_concede = request(base, "/api/arena/state")
    assert status == 200 and (arena_after_concede["wins"], arena_after_concede["losses"]) == (1, 1)

    status, repeated = request(base, "/api/concede", {
        "session_id": terminal_loss["session_id"],
        "revision": terminal_loss["revision"],
    })
    assert status == 409 and repeated["error"] == "match is over"
    status, lobby = request(base, "/api/return", {
        "session_id": terminal_loss["session_id"],
        "revision": terminal_loss["revision"],
    })
    assert status == 200 and lobby["arena_redirect"] is True
    status, run = request(base, "/api/arena/state")
    assert status == 200 and (run["wins"], run["losses"]) == (1, 1)

    status, duplicate = request(
        base, "/api/return",
        {"session_id": terminal["session_id"], "revision": terminal["revision"]},
    )
    assert status == 409 and duplicate["mode"] == "lobby"
    assert request(base, "/api/arena/state")[1]["wins"] == 1


def test_second_server_returns_conflict_and_recovers_after_owner_closes(arena_http):
    first_app, first_base = arena_http
    assert request(first_base, "/api/arena/state")[0] == 200
    second_app = WebGameManager(arena_store=ArenaStore(first_app._arena_store.path))
    server = make_server(second_app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, state = request(base, "/api/arena/state")
        assert status == 409 and "error" in state
        status, state = request(
            base,
            "/api/arena/start",
            {"nickname": "Tester", "locale": "zhCN", "set_ids": SETS},
        )
        assert status == 409 and "error" in state
        first_app.close()
        assert request(base, "/api/arena/state")[0] == 200
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("sets,status_code", [
    (["GVG", "TGT", "OG", "GANGS", "NAXX"], 400),  # 13
    (["GVG", "TGT", "OG", "GANGS", "NAXX", "BRM"], 200),  # 14
    (["GVG", "TGT", "OG", "GANGS", "UNGORO", "SCHOLOMANCE"], 200),  # 18
    (["GVG", "TGT", "OG", "GANGS", "UNGORO", "SCHOLOMANCE", "NAXX"], 400),  # 19
])
def test_arena_http_budget_boundaries(arena_http, sets, status_code):
    _, base = arena_http
    status, state = request(base, "/api/arena/start", {
        "nickname": "Tester", "locale": "zhCN", "set_ids": sets,
    })
    assert status == status_code
    if status == 200:
        assert state["mode"] == "hero" and len(state["hero_offer"]) == 3
    else:
        assert state["mode"] == "setup"
