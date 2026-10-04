"""Room privacy projections and restart/ownership boundaries."""

from __future__ import annotations

import json
from pathlib import Path

from fireplace.web_gui.rooms import RoomRegistry


ALICE = "a" * 32
BOB = "b" * 32
WISP_DECK = {"hero_id": "HERO_08", "card_ids": ["CS2_231"] * 5}


def _create_pair(registry: RoomRegistry):
    created = registry.create(
        ALICE,
        {"nickname": "Alice", "locale": "enUS"},
        deck_spec=WISP_DECK,
    )
    registry.join(
        BOB,
        {
            "invite_code": created["room"]["invite_code"],
            "nickname": "Bob",
            "locale": "zhCN",
        },
        deck_spec=WISP_DECK,
    )
    return created


def _advance_to_main(registry: RoomRegistry) -> None:
    for _ in range(4):
        views = [(ALICE, registry.snapshot(ALICE)), (BOB, registry.snapshot(BOB))]
        assert all(view is not None for _, view in views)
        current = next(
            ((account, view) for account, view in views if view["legal_actions"]),
            None,
        )
        assert current is not None, "room should expose one current legal decision"
        account, state = current
        if state["observation"]["phase"] == "MAIN":
            return
        action = state["legal_actions"][0]
        registry.handle_action(
            account,
            {
                "session_id": state["session_id"],
                "revision": state["revision"],
                "action": action,
            },
        )
    raise AssertionError("room did not reach a main-action phase after mulligans")


def _current_view(registry: RoomRegistry):
    for account in (ALICE, BOB):
        state = registry.snapshot(account)
        if state is not None and state["legal_actions"]:
            return account, state
    raise AssertionError("neither room participant has the current legal actions")


def _player(registry: RoomRegistry, room_id: str, account: str):
    runtime = registry._rooms[room_id]
    return runtime.players[runtime.seat_for(account)]


def _identity_action(state, card, action_type="PLAY_CARD"):
    return next(
        action
        for action in state["legal_actions"]
        if action["type"] == action_type
        and action.get("source_entity_id") == card.entity_id
    )


def _assert_not_serialized(state, *, card_id: str, name: str, entity_id: int):
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)
    assert card_id not in encoded
    assert name not in encoded

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("entity_id"):
                    assert child != entity_id
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(state)


def _assert_option_private(state, option, previously_visible: str) -> None:
    encoded = json.dumps(state, ensure_ascii=False, sort_keys=True)

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.endswith("entity_id"):
                    assert child != option["entity_id"]
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(state)
    if option["card_id"] not in previously_visible:
        assert option["card_id"] not in encoded
    if option["name"] not in previously_visible:
        assert option["name"] not in encoded


def _last_frame(state):
    assert state["frames"]
    frame = state["frames"][-1]
    assert isinstance(frame["effects"], list)
    assert frame["event"] == state["events"][-1]
    return frame


def test_secret_play_and_discover_choices_stay_private_in_both_serialized_views(
    tmp_path: Path,
):
    registry = RoomRegistry(tmp_path, seed=21)
    try:
        created = _create_pair(registry)
        room_id = created["room"]["id"]
        _advance_to_main(registry)

        # Inject only the card under test. Every action that changes game state
        # below is selected from and accepted through the legal-action API.
        secret_actor, _ = _current_view(registry)
        secret = _player(registry, room_id, secret_actor).give("EX1_289")
        secret_player = _player(registry, room_id, secret_actor)
        secret_player.max_mana = 10
        secret_player.used_mana = 0
        before_secret = registry.snapshot(secret_actor)
        secret_card = next(
            card
            for card in before_secret["observation"]["self"]["hand"]
            if card["entity_id"] == secret.entity_id
        )
        assert secret_card["card_id"] == "EX1_289"
        secret_action = _identity_action(before_secret, secret)
        after_secret = registry.handle_action(
            secret_actor,
            {
                "session_id": before_secret["session_id"],
                "revision": before_secret["revision"],
                "action": secret_action,
            },
        )
        secret_viewer = BOB if secret_actor == ALICE else ALICE
        secret_opponent = registry.snapshot(secret_viewer)
        assert after_secret["events"][-1]["type"] == "PLAY_CARD"
        assert after_secret["events"][-1]["source_entity_id"] == secret.entity_id
        secret_frame = _last_frame(after_secret)
        opponent_secret_frame = _last_frame(secret_opponent)
        assert secret_frame["event"]["source_entity_id"] == secret.entity_id
        assert opponent_secret_frame["event"]["type"] == "PLAY_CARD"
        _assert_not_serialized(
            secret_opponent,
            card_id="EX1_289",
            name=secret_card["name"],
            entity_id=secret.entity_id,
        )

        # End the current turn with a legal action so the second participant
        # owns the discover action in the same shared game.
        end_turn = next(
            action for action in after_secret["legal_actions"]
            if action["type"] == "END_TURN"
        )
        after_turn = registry.handle_action(
            secret_actor,
            {
                "session_id": after_secret["session_id"],
                "revision": after_secret["revision"],
                "action": end_turn,
            },
        )
        discover_actor, before_discover = _current_view(registry)
        assert discover_actor != secret_actor
        discover_player = _player(registry, room_id, discover_actor)
        scarab = discover_player.give("LOE_029")
        discover_player.max_mana = 10
        discover_player.used_mana = 0
        before_discover = registry.snapshot(discover_actor)
        scarab_action = _identity_action(before_discover, scarab)
        after_scarab = registry.handle_action(
            discover_actor,
            {
                "session_id": before_discover["session_id"],
                "revision": before_discover["revision"],
                "action": scarab_action,
            },
        )
        discover_viewer = BOB if discover_actor == ALICE else ALICE
        discover_opponent = registry.snapshot(discover_viewer)
        previously_visible = json.dumps(
            discover_opponent, ensure_ascii=False, sort_keys=True
        )
        options = after_scarab["observation"]["pending_choice"]["options"]
        assert len(options) == 3
        assert after_scarab["legal_actions"]
        scarab_event = after_scarab["events"][-1]
        assert scarab_event["type"] == "PLAY_CARD"
        assert scarab_event["source_entity_id"] == scarab.entity_id
        frame = _last_frame(after_scarab)
        assert any(effect["event"]["type"] == "BATTLECRY" for effect in frame["effects"])
        opponent_frame = _last_frame(discover_opponent)
        assert opponent_frame["event"]["actor"] == "opponent"
        assert opponent_frame["event"]["source_entity_id"] == scarab.entity_id
        for option in options:
            assert option.get("card_id") and option.get("name")
            _assert_option_private(discover_opponent, option, previously_visible)

        choose_action = next(
            action for action in after_scarab["legal_actions"]
            if action["type"] == "CHOOSE"
        )
        chosen = next(
            option for option in options
            if option["entity_id"] == choose_action["choice_entity_id"]
        )
        after_choice = registry.handle_action(
            discover_actor,
            {
                "session_id": after_scarab["session_id"],
                "revision": after_scarab["revision"],
                "action": choose_action,
            },
        )
        opponent_after_choice = registry.snapshot(discover_viewer)
        assert after_choice["events"][-1]["type"] == "CHOOSE"
        assert after_choice["events"][-1]["source_entity_id"] == chosen["entity_id"]
        assert _last_frame(after_choice)["event"]["type"] == "CHOOSE"
        assert _last_frame(opponent_after_choice)["event"]["type"] == "CHOOSE"
        for option in options:
            _assert_option_private(
                opponent_after_choice, option, previously_visible
            )
        assert after_turn["revision"] + 1 == after_scarab["revision"]
    finally:
        registry.close()


def test_accepted_action_restores_and_terminal_views_survive_restart_and_detach(
    tmp_path: Path,
):
    registry = RoomRegistry(tmp_path, seed=22)
    try:
        created = _create_pair(registry)
        room_id = created["room"]["id"]
        actor, before = _current_view(registry)
        assert before["observation"]["phase"] == "MULLIGAN"
        action = next(
            action for action in before["legal_actions"]
            if action["type"] == "MULLIGAN"
        )
        accepted = registry.handle_action(
            actor,
            {
                "session_id": before["session_id"],
                "revision": before["revision"],
                "action": action,
            },
        )
        accepted_revision = accepted["revision"]
        assert accepted_revision > 0
        persisted = registry._store.get(room_id)
        assert persisted["accepted_revision"] == accepted_revision
        assert len(persisted["log"]["actions"]) == accepted_revision
        assert persisted["views"]["0"]["events"]
        assert persisted["views"]["1"]["frames"]
    finally:
        registry.close()

    restored = RoomRegistry(tmp_path, seed=22)
    try:
        alice = restored.snapshot(ALICE)
        bob = restored.snapshot(BOB)
        assert alice["session_id"] == bob["session_id"]
        assert alice["session_id"] != accepted["session_id"]
        assert alice["revision"] == bob["revision"] == accepted_revision
        assert alice["events"] == restored._rooms[room_id]._events[0]
        assert bob["events"] == restored._rooms[room_id]._events[1]
        assert alice["frames"] and bob["frames"]

        _advance_to_main(restored)
        on_turn, _ = _current_view(restored)
        off_turn = BOB if on_turn == ALICE else ALICE
        assert restored.snapshot(off_turn)["legal_actions"] == []
        names = {ALICE: "Alice", BOB: "Bob"}

        # The participant without game actions concedes; the terminal result
        # and each seat's event projection must survive another restart.
        terminal = restored.concede(
            off_turn,
            {
                "session_id": restored.snapshot(off_turn)["session_id"],
                "revision": restored.snapshot(off_turn)["revision"],
            },
        )
        terminal_revision = terminal["revision"]
        assert terminal["room"]["status"] == "complete"
        assert terminal["events"][-1]["type"] == "CONCEDE"
        winner_name = names[on_turn]
    finally:
        restored.close()

    terminal_registry = RoomRegistry(tmp_path, seed=22)
    try:
        alice_terminal = terminal_registry.snapshot(ALICE)
        bob_terminal = terminal_registry.snapshot(BOB)
        assert alice_terminal["revision"] == bob_terminal["revision"] == terminal_revision
        assert alice_terminal["outcome"]["winner"] == winner_name
        assert bob_terminal["outcome"]["winner"] == winner_name
        assert alice_terminal["frames"][-1]["event"]["type"] == "CONCEDE"
        assert bob_terminal["frames"][-1]["event"]["type"] == "CONCEDE"

        assert terminal_registry.leave(
            ALICE,
            {"session_id": alice_terminal["session_id"], "revision": terminal_revision},
        ) == {"mode": "lobby"}
        assert terminal_registry.snapshot(ALICE) is None
        assert terminal_registry.snapshot(BOB)["outcome"]["winner"] == winner_name
        assert terminal_registry.leave(
            BOB,
            {"session_id": bob_terminal["session_id"], "revision": terminal_revision},
        ) == {"mode": "lobby"}
        assert terminal_registry.snapshot(BOB) is None
        record = terminal_registry._store.get(room_id)
        assert all(not participant["attached"] for participant in record["participants"])
    finally:
        terminal_registry.close()

    detached = RoomRegistry(tmp_path, seed=22)
    try:
        assert detached.snapshot(ALICE) is None
        assert detached.snapshot(BOB) is None
    finally:
        detached.close()
