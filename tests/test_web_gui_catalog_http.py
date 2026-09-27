"""HTTP boundaries for the public, read-only card catalog."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from fireplace.web_gui.assets import AssetService
from fireplace.web_gui.server import WebGameManager, make_server


@pytest.fixture
def catalog_http(tmp_path):
    image = tmp_path / "card.png"
    image.write_bytes(b"catalog-image")

    class Resolver:
        def resolve(self, card_id, kind="tile", locale="zhCN"):
            return SimpleNamespace(
                path=image,
                media_type="image/png",
                locale=None if kind == "tile" else locale,
                is_placeholder=False,
            )

    backend = WebGameManager(seed=11, asset_resolver=None)
    assets = AssetService(resolver=Resolver())
    server = make_server(
        backend, host="127.0.0.1", port=0, catalog_assets=assets
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def fetch(base, path):
    try:
        with urlopen(base + path, timeout=10) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, error.read()


def fetch_json(base, path):
    status, _headers, body = fetch(base, path)
    return status, json.loads(body)


def test_catalog_lists_without_starting_a_match(catalog_http):
    status, payload = fetch_json(
        catalog_http, "/api/catalog?locale=zhCN&page_size=2&q=AT_003"
    )
    assert status == 200
    assert payload["total"] >= 1
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert any(card["id"] == "AT_003" for card in payload["items"])

    status, detail = fetch_json(catalog_http, "/api/catalog/cards/AT_003?locale=enUS")
    assert status == 200
    assert detail["id"] == "AT_003"
    assert detail["name"] == "Fallen Hero"


def test_catalog_heroes_are_separate_and_script_badge_is_data_only(catalog_http):
    status, heroes = fetch_json(
        catalog_http, "/api/catalog?set=HEROES&q=HERO_01&page_size=10"
    )
    assert status == 200
    assert any(card["id"] == "HERO_01" for card in heroes["items"])
    assert next(card for card in heroes["items"] if card["id"] == "HERO_01")[
        "catalog_set"
    ] == "HEROES"

    status, basic = fetch_json(catalog_http, "/api/catalog?set=BASIC&q=HERO_01")
    assert status == 200
    assert basic["total"] == 0

    status, hero = fetch_json(catalog_http, "/api/catalog/cards/HERO_01")
    assert status == 200
    assert hero["card_set"] == "BASIC"
    assert hero["has_python_script"] is False

    status, fireball = fetch_json(catalog_http, "/api/catalog/cards/CS2_029")
    assert status == 200
    assert fireball["has_python_script"] is True

    status, death_knight = fetch_json(
        catalog_http, "/api/catalog/cards/ICC_828"
    )
    assert status == 200
    assert death_knight["card_set"] == "ICECROWN"
    assert death_knight["catalog_set"] == "ICECROWN"

    status, boom_boss = fetch_json(catalog_http, "/api/catalog/cards/BOT_238")
    assert status == 200
    assert boom_boss["card_set"] == "BOOMSDAY"
    assert boom_boss["catalog_set"] == "BOOMSDAY"

    status, heroes = fetch_json(catalog_http, "/api/catalog?set=HEROES")
    assert status == 200
    assert heroes["total"] == 10
    assert all(card["type"] == "HERO" for card in heroes["items"])

    status, icecrown = fetch_json(
        catalog_http, "/api/catalog?set=ICECROWN&q=ICC_828"
    )
    assert status == 200
    assert any(card["id"] == "ICC_828" for card in icecrown["items"])

    status, boomsday = fetch_json(
        catalog_http, "/api/catalog?set=BOOMSDAY&q=BOT_238"
    )
    assert status == 200
    assert any(card["id"] == "BOT_238" for card in boomsday["items"])


@pytest.mark.parametrize(
    "path",
    [
        "/api/catalog?page=0",
        "/api/catalog?page_size=101",
        "/api/catalog?scope=unknown",
        "/api/catalog?locale=frFR",
        "/api/catalog?page=1&page=2",
        "/api/catalog?unknown=1",
    ],
)
def test_catalog_rejects_invalid_query(catalog_http, path):
    status, payload = fetch_json(catalog_http, path)
    assert status == 400
    assert isinstance(payload["error"], str)


def test_catalog_static_page_and_asset_boundary(catalog_http):
    for path, media in (
        ("/cards", "text/html"),
        ("/catalog_app.js", "text/javascript"),
        ("/style-catalog.css", "text/css"),
    ):
        status, headers, body = fetch(catalog_http, path)
        assert status == 200 and body
        assert headers["Content-Type"].startswith(media)

    # The match asset path still requires a visible card in an active match.
    assert fetch(catalog_http, "/assets/tile/AT_003")[0] == 404
    assert fetch(catalog_http, "/catalog/assets/tile/DOES_NOT_EXIST")[0] == 404
    for kind in ("tile", "art", "render"):
        deadline = time.monotonic() + 5
        while True:
            status, headers, body = fetch(
                catalog_http, f"/catalog/assets/{kind}/AT_003"
            )
            if status != 202:
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert status == 200
        assert headers["Content-Type"] == "image/png"
        assert body == b"catalog-image"


def test_catalog_detail_rejects_unknown_id(catalog_http):
    assert fetch(catalog_http, "/api/catalog/cards/DOES_NOT_EXIST")[0] == 404
