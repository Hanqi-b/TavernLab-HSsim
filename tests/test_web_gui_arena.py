"""Arena HTTP lifecycle, including the existing match boundary."""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.request import urlopen

import pytest

from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore, default_state_path
from fireplace.mcts_agent import MCTSAgent
from fireplace.web_gui.server import WebGameManager, make_server
from tests.test_web_gui_accounts_http import Browser, account_server
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
    # Radical is the normal match default; Arena must still select MCTS.
    app = WebGameManager(
        seed=17,
        opponent="radical",
        arena_store=ArenaStore(tmp_path / "arena.json"),
    )
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


def _draft_ready(base):
    status, state = request(base, "/api/arena/start", {
        "nickname": "Retiring tester", "locale": "zhCN", "set_ids": SETS,
    })
    assert status == 200 and state["mode"] == "hero"
    status, state = _command(base, "/api/arena/hero", state, hero_id=state["hero_offer"][0]["id"])
    assert status == 200 and state["mode"] == "draft"
    for _ in range(30):
        status, state = _command(base, "/api/arena/pick", state, card_id=state["card_offer"][0]["id"])
        assert status == 200
    assert state["mode"] == "ready" and len(state["deck"]) == 30
    return state


def _ready_run(seed=17):
    run = ArenaRun.create(SETS, "Account tester", "zhCN", seed=seed)
    run.choose_hero(run.hero_choices[0])
    for _ in range(30):
        run.choose_card(run.choices[0])
    return run


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

    assert app.opponent_default == "radical"
    # An omitted Arena policy must ignore the normal-match default.
    status, state = _command(base, "/api/arena/battle", state)
    assert status == 200 and state["mode"] == "match"
    assert state["match_url"] == "/?arena=1"
    assert app.active is not None
    assert isinstance(app.active.opponent_agent, MCTSAgent)
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

    # Arena ignores a requested Heuristic policy as well.
    status, battle = _command(base, "/api/arena/battle", run, opponent="heuristic")
    assert status == 200 and battle["mode"] == "match"
    assert app.active is not None
    assert isinstance(app.active.opponent_agent, MCTSAgent)
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

    # And an explicit Radical request remains fixed to MCTS.
    status, battle = _command(base, "/api/arena/battle", run, opponent="radical")
    assert status == 200 and battle["mode"] == "match"
    assert app.active is not None
    assert isinstance(app.active.opponent_agent, MCTSAgent)
    status, game = request(base)
    assert status == 200 and game["mode"] == "match"
    status, terminal_third = request(base, "/api/concede", {
        "session_id": game["session_id"],
        "revision": game["revision"],
    })
    assert status == 200 and terminal_third["outcome"]["human_won"] is False
    status, lobby = request(base, "/api/return", {
        "session_id": terminal_third["session_id"],
        "revision": terminal_third["revision"],
    })
    assert status == 200 and lobby["arena_redirect"] is True

    status, duplicate = request(
        base, "/api/return",
        {"session_id": terminal["session_id"], "revision": terminal["revision"]},
    )
    assert status == 409 and duplicate["mode"] == "lobby"
    assert request(base, "/api/arena/state")[1]["wins"] == 1


def test_arena_retire_requires_ready_cas_rejects_active_match_and_allows_restart(arena_http):
    _app, base = arena_http
    ready = _draft_ready(base)
    before_revision = ready["revision"]

    status, wrong_run = _command(base, "/api/arena/retire", {
        **ready, "run_id": "wrong-run",
    })
    assert status == 409 and wrong_run["mode"] == "ready"
    assert wrong_run["revision"] == before_revision

    status, stale = _command(base, "/api/arena/retire", {
        **ready, "revision": before_revision - 1,
    })
    assert status == 409 and stale["mode"] == "ready"
    assert stale["revision"] == before_revision

    status, battle = _command(base, "/api/arena/battle", ready)
    assert status == 200 and battle["mode"] == "match"
    status, active_rejected = _command(base, "/api/arena/retire", battle)
    assert status == 409 and active_rejected["mode"] == "match"

    status, game = request(base)
    assert status == 200 and game["mode"] == "match"
    status, terminal = request(base, "/api/concede", {
        "session_id": game["session_id"], "revision": game["revision"],
    })
    assert status == 200
    status, lobby = request(base, "/api/return", {
        "session_id": terminal["session_id"], "revision": terminal["revision"],
    })
    assert status == 200 and lobby["arena_redirect"] is True

    status, ready_again = request(base, "/api/arena/state")
    assert status == 200 and ready_again["mode"] == "ready"
    status, retired = _command(base, "/api/arena/retire", ready_again)
    assert status == 200
    assert retired["mode"] == "complete" and retired["retired"] is True
    assert retired["deck"] == ready_again["deck"]
    assert (retired["wins"], retired["losses"]) == (0, 1)

    status, fresh = request(base, "/api/arena/start", {
        "nickname": "Fresh run", "locale": "zhCN", "set_ids": SETS,
    })
    assert status == 200 and fresh["mode"] == "hero"
    assert fresh["run_id"] != retired["run_id"]


def test_arena_retire_requires_authentication_and_stays_account_scoped(tmp_path):
    with account_server(tmp_path) as base:
        anonymous = Browser(base)
        assert anonymous.request("/api/arena/retire", {})[0] == 401

        alice = Browser(base)
        bob = Browser(base)
        alice_id = alice.register("Alice")["id"]
        bob_id = bob.register("Bob")["id"]
        alice_run = _ready_run()
        bob_run = _ready_run(seed=19)
        ArenaStore(tmp_path / "users" / alice_id / "arena-run.json").save(alice_run)
        ArenaStore(tmp_path / "users" / bob_id / "arena-run.json").save(bob_run)

        status, alice_state = alice.request("/api/arena/state")
        assert status == 200 and alice_state["mode"] == "ready"
        status, bob_state = bob.request("/api/arena/state")
        assert status == 200 and bob_state["mode"] == "ready"

        status, rejected = bob.request("/api/arena/retire", {
            "run_id": alice_state["run_id"], "revision": alice_state["revision"],
        })
        assert status == 409 and rejected["mode"] == "ready"
        assert bob.request("/api/arena/state")[1]["retired"] is False
        assert alice.request("/api/arena/state")[1]["retired"] is False


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
