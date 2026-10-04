"""Focused shared human-room lifecycle and privacy checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from fireplace.web_gui.contracts import WebActionError, WebLifecycleError
from fireplace.web_gui.rooms import RoomRegistry


ALICE = "a" * 32
BOB = "b" * 32
CAROL = "c" * 32
DECK = {"hero_id": "HERO_08", "card_ids": ["CS2_231"] * 5}


def _room(registry: RoomRegistry):
    created = registry.create(
        ALICE, {"nickname": "Alice", "locale": "enUS"}, deck_spec=DECK
    )
    registry.join(
        BOB,
        {
            "invite_code": created["room"]["invite_code"],
            "nickname": "Bob",
            "locale": "zhCN",
        },
        deck_spec=DECK,
    )
    return created


def test_two_views_share_one_session_and_filter_private_hand(tmp_path: Path):
    registry = RoomRegistry(tmp_path, seed=7)
    try:
        created = _room(registry)
        alice = registry.snapshot(ALICE)
        bob = registry.snapshot(BOB)
        assert created["room"]["invite_code"]
        assert "invite_code" not in registry.snapshot(ALICE)["room"]
        assert alice["room"]["id"] == bob["room"]["id"]
        assert alice["room"]["seat"] == 0
        assert bob["room"]["seat"] == 1
        assert alice["session_id"] == bob["session_id"]
        assert alice["revision"] == bob["revision"] == 0
        assert alice["observation"]["self"]["hand"]
        assert "hand" not in bob["observation"]["opponent"]
        assert "card_id" not in bob["observation"]["opponent"].get("hand", {})

        # ``seat`` is intentionally ignored; the authenticated account owns
        # the player object used by the engine boundary.
        action = alice["legal_actions"][0]
        accepted = registry.handle_action(
            ALICE,
            {
                "session_id": alice["session_id"],
                "revision": alice["revision"],
                "seat": 1,
                "action": action,
            },
        )
        assert accepted["revision"] == 1
        assert registry.snapshot(BOB)["revision"] == 1
        assert accepted["events"][-1]["actor"] == "self"
        assert registry.snapshot(BOB)["events"][-1]["actor"] == "opponent"
    finally:
        registry.close()


def test_stale_concurrent_action_has_one_winner(tmp_path: Path):
    registry = RoomRegistry(tmp_path, seed=8)
    try:
        _room(registry)
        snapshot = registry.snapshot(ALICE)
        payload = {
            "session_id": snapshot["session_id"],
            "revision": snapshot["revision"],
            "action": snapshot["legal_actions"][0],
        }

        def attempt():
            try:
                return registry.handle_action(ALICE, payload)["revision"]
            except WebActionError as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _item: attempt(), range(2)))
        assert sorted(results) == [1, 409]
        assert registry.snapshot(ALICE)["revision"] == 1
    finally:
        registry.close()


def test_off_turn_concede_has_consistent_winner_and_terminal_leave(tmp_path: Path):
    registry = RoomRegistry(tmp_path, seed=9)
    try:
        _room(registry)
        bob = registry.snapshot(BOB)
        terminal = registry.concede(
            BOB,
            {"session_id": bob["session_id"], "revision": bob["revision"]},
        )
        alice = registry.snapshot(ALICE)
        assert terminal["revision"] == alice["revision"] == 1
        assert terminal["room"]["status"] == alice["room"]["status"] == "complete"
        assert terminal["outcome"]["winner"] == alice["outcome"]["winner"] == "Alice"
        assert terminal["outcome"]["human_won"] is False
        assert alice["outcome"]["human_won"] is True
        assert registry.leave(BOB, {"session_id": bob["session_id"], "revision": 1}) == {
            "mode": "lobby"
        }
        assert registry.snapshot(BOB) is None
        assert registry.snapshot(ALICE)["outcome"]["winner"] == "Alice"
    finally:
        registry.close()


def test_waiting_leave_and_restart_reconnect(tmp_path: Path):
    registry = RoomRegistry(tmp_path, seed=10)
    created = registry.create(ALICE, {"nickname": "Alice", "locale": "zhCN"})
    assert not list((tmp_path / "rooms").glob(".room-*.tmp"))
    assert registry.leave(ALICE, {}) == {"mode": "lobby"}
    assert registry.snapshot(ALICE) is None

    created = registry.create(ALICE, {"nickname": "Alice", "locale": "zhCN"}, DECK)
    registry.join(
        BOB,
        {"code": created["room"]["invite_code"], "nickname": "Bob", "locale": "enUS"},
        DECK,
    )
    before = registry.snapshot(ALICE)
    registry.close()

    restored = RoomRegistry(tmp_path, seed=10)
    try:
        after_alice = restored.snapshot(ALICE)
        after_bob = restored.snapshot(BOB)
        assert after_alice["room"]["id"] == before["room"]["id"]
        assert after_alice["session_id"] == after_bob["session_id"]
        assert after_alice["session_id"] != before["session_id"]
        assert after_alice["revision"] == after_bob["revision"] == before["revision"]
        with pytest.raises(WebLifecycleError):
            restored.join(
                CAROL,
                {"code": "bad", "nickname": "Carol", "locale": "zhCN"},
                DECK,
            )
    finally:
        restored.close()

def test_restart_recovers_if_playing_row_published_before_start(tmp_path: Path, monkeypatch):
    registry = RoomRegistry(tmp_path, seed=11)
    created = registry.create(ALICE, {"nickname": "Alice", "locale": "enUS"}, DECK)
    original_save = registry._store.save

    def publish_then_crash(*args, **kwargs):
        saved = original_save(*args, **kwargs)
        updates = kwargs.get("updates", {})
        if updates.get("status") == "playing":
            raise RuntimeError("injected crash after playing publication")
        return saved

    monkeypatch.setattr(registry._store, "save", publish_then_crash)
    with pytest.raises(WebLifecycleError):
        registry.join(
            BOB,
            {"code": created["room"]["invite_code"], "nickname": "Bob", "locale": "zhCN"},
            DECK,
        )
    registry.close()

    restored = RoomRegistry(tmp_path, seed=11)
    try:
        alice = restored.snapshot(ALICE)
        bob = restored.snapshot(BOB)
        assert alice["room"]["status"] == bob["room"]["status"] == "playing"
        assert alice["session_id"] == bob["session_id"]
        assert alice["revision"] == bob["revision"] == 0
        assert alice["legal_actions"]
    finally:
        restored.close()


def test_restart_keeps_previous_public_prefix_if_checkpoint_fails(tmp_path: Path, monkeypatch):
    registry = RoomRegistry(tmp_path, seed=12)
    try:
        _room(registry)
        before = registry.snapshot(ALICE)
        runtime = registry._rooms[before["room"]["id"]]

        def crash_checkpoint():
            raise OSError("injected checkpoint interruption")

        monkeypatch.setattr(runtime, "_persist_public_locked", crash_checkpoint)
        with pytest.raises(WebActionError) as failure:
            registry.handle_action(
                ALICE,
                {
                    "session_id": before["session_id"],
                    "revision": before["revision"],
                    "action": before["legal_actions"][0],
                },
            )
        assert failure.value.status_code == 503
        assert registry.snapshot(ALICE)["revision"] == 1
    finally:
        registry.close()

    restored = RoomRegistry(tmp_path, seed=12)
    try:
        after = restored.snapshot(ALICE)
        assert after["revision"] == 0
        assert after["events"] == []
        accepted = restored.handle_action(
            ALICE,
            {
                "session_id": after["session_id"],
                "revision": after["revision"],
                "action": after["legal_actions"][0],
            },
        )
        assert accepted["revision"] == 1
        assert accepted["events"]
    finally:
        restored.close()
