"""Shared HTTP fixtures and helpers for the browser game tests."""

from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.agents import HeuristicAgent
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.server import WebGame, WebGameManager, make_server


cards.db.initialize()


def request(base, path="/api/state", payload=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    request_headers = {"Content-Type": "application/json"} if data is not None else {}
    request_headers.update(headers or {})
    req = Request(base + path, data=data, headers=request_headers)
    try:
        with urlopen(req, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def submit(base, state, action_value):
    return request(
        base,
        "/api/action",
        {
            "session_id": state["session_id"],
            "revision": state["revision"],
            "action": action_value,
        },
    )


def action(state, kind, **fields):
    return next(
        item
        for item in state["legal_actions"]
        if item["type"] == kind
        and all(item.get(key) == value for key, value in fields.items())
    )


def ready(base):
    status, state = request(base)
    assert status == 200 and state["observation"]["phase"] == "MULLIGAN"
    status, state = submit(
        base, state, action(state, "MULLIGAN", mulligan_entity_ids=[])
    )
    assert status == 200 and state["observation"]["phase"] == "MAIN"
    return state


def wait_asset(base, path, timeout=10):
    deadline = time.monotonic() + timeout
    while True:
        with urlopen(base + path, timeout=timeout) as response:
            status = response.status
            media_type = response.headers.get("Content-Type")
            data = response.read()
        if status != 202:
            return status, media_type, data
        if time.monotonic() >= deadline:
            raise AssertionError("asset never became ready")
        time.sleep(0.05)


@pytest.fixture
def web_game():
    servers = []

    def create(
        *,
        hero=CardClass.MAGE.default_hero,
        seed=3,
        asset_resolver=None,
        deck_size=10,
        locale="zhCN",
    ):
        human = Player("Human", ["CS2_231"] * deck_size, hero)
        opponent = Player("Computer", ["CS2_231"] * deck_size, hero)
        game = Game((human, opponent), seed=seed)
        app = WebGame(
            GameSession(game, {}),
            human,
            HeuristicAgent(),
            asset_resolver=asset_resolver,
            locale=locale,
        )
        server = make_server(app, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return app, human, opponent, f"http://127.0.0.1:{server.server_port}"

    yield create
    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture
def lobby_server():
    servers = []

    def create(*, seed=11, opponent="radical", asset_resolver=None):
        app = WebGameManager(
            seed=seed, opponent=opponent, asset_resolver=asset_resolver
        )
        server = make_server(app, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread, app))
        return app, f"http://127.0.0.1:{server.server_port}"

    yield create
    for server, thread, _app in servers:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def finish_lobby_match(app, base, state=None):
    if state is None:
        status, state = request(base)
        assert status == 200 and state["mode"] == "lobby"
        status, state = request(
            base,
            "/api/start",
            {"nickname": "Alice", "locale": "enUS"},
        )
        assert status == 200 and state["mode"] == "match"
    status, state = submit(
        base, state, action(state, "MULLIGAN", mulligan_entity_ids=[])
    )
    assert status == 200 and state["observation"]["phase"] == "MAIN"
    active = app.active
    assert active is not None
    active.human.max_mana = 10
    opponent = next(
        player for player in active.session.game.players if player is not active.human
    )
    opponent.hero.damage = opponent.hero.max_health - 1
    fireball = active.human.give("CS2_029")
    _, state = request(base)
    status, state = submit(
        base,
        state,
        action(
            state,
            "PLAY_CARD",
            source_entity_id=fireball.entity_id,
            target_entity_id=opponent.hero.entity_id,
        ),
    )
    assert status == 200 and state["outcome"] is not None
    return state


__all__ = [
    "action",
    "finish_lobby_match",
    "lobby_server",
    "ready",
    "request",
    "submit",
    "wait_asset",
    "web_game",
]
