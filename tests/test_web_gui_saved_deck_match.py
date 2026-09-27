"""Saved collection decks flow through the real local match boundary."""

from collections import Counter

from fireplace.web_gui.catalog import CardCatalog
from fireplace.web_gui.server import WebGameManager, make_server
from fireplace.web_gui.decks import DeckStore
from tests.web_gui_support import request
import threading


def _neutral_minions(count):
    catalog = CardCatalog()
    found = []
    page = 1
    while len(found) < count:
        result = catalog.list_cards(
            locale="enUS", card_class="NEUTRAL", scope="collectible",
            page=page, page_size=100,
        )
        found.extend(
            card["id"] for card in result["items"]
            if card["type"] == "MINION" and not card["id"].startswith("HERO_")
        )
        if page * 100 >= result["total"]:
            break
        page += 1
    assert len(found) >= count
    return found[:count]


def test_saved_deck_can_start_match_while_random_match_remains_available(tmp_path):
    app = WebGameManager(seed=31, deck_store=DeckStore(tmp_path / "decks.json"))
    server = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, empty = request(base, "/api/decks")
        assert status == 200 and empty["decks"] == []

        ids = _neutral_minions(30)
        status, saved = request(base, "/api/decks/save", {
            "name": "Neutral test", "hero_id": "HERO_08",
            "card_ids": ids, "locale": "zhCN",
        })
        assert status == 200
        deck = saved["decks"][0]
        assert saved["saved_id"] == deck["id"]
        assert deck["complete"] is True and deck["card_ids"] == ids

        status, started = request(base, "/api/start", {
            "nickname": "Tester", "locale": "zhCN", "deck_id": deck["id"],
        })
        assert status == 200 and started["mode"] == "match"
        human = app.active.human
        assert human.hero.id == "HERO_08"
        assert Counter(card.id for card in human.starting_deck) == Counter(ids)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_incomplete_saved_deck_cannot_start_match(tmp_path):
    app = WebGameManager(seed=31, deck_store=DeckStore(tmp_path / "decks.json"))
    server = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, invalid = request(base, "/api/decks/save", {
            "name": "Invalid", "hero_id": [], "card_ids": [], "locale": "zhCN",
        })
        assert status == 400 and invalid["mode"] == "lobby"
        status, invalid = request(base, "/api/decks/save", {
            "name": "Invalid", "hero_id": "HERO_08", "card_ids": [], "locale": [],
        })
        assert status == 400 and invalid["mode"] == "lobby"
        status, saved = request(base, "/api/decks/save", {
            "name": "Work in progress", "hero_id": "HERO_08",
            "card_ids": _neutral_minions(2), "locale": "zhCN",
        })
        assert status == 200
        deck_id = saved["decks"][0]["id"]
        status, rejected = request(base, "/api/start", {
            "nickname": "Tester", "locale": "zhCN", "deck_id": deck_id,
        })
        assert status == 400 and rejected["mode"] == "lobby"
        assert app.active is None
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_deck_storage_failures_return_json_service_error(tmp_path, monkeypatch):
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("file", encoding="utf-8")
    store = DeckStore(blocked_parent / "decks.json")
    app = WebGameManager(seed=31, deck_store=store)
    server = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, result = request(base, "/api/decks")
        assert status == 503 and result["error"] == "deck storage is unavailable"
        status, result = request(base, "/api/decks/save", {
            "name": "测试", "hero_id": "HERO_08", "card_ids": [],
        })
        assert status == 503 and result["error"] == "deck storage is unavailable"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    write_store = DeckStore(tmp_path / "decks.json")
    def fail_write(_decks):
        raise OSError("disk full")
    monkeypatch.setattr(write_store, "_write_unlocked", fail_write)
    app = WebGameManager(seed=31, deck_store=write_store)
    server = make_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, result = request(base, "/api/decks/save", {
            "name": "测试", "hero_id": "HERO_08", "card_ids": [],
        })
        assert status == 503 and result["error"] == "deck storage is unavailable"
        assert not write_store.path.exists()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
