from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from fireplace.web_gui.accounts import (
    AccountAuthError,
    AccountConflict,
    AccountStore,
    SESSION_TTL_SECONDS,
    default_state_path,
)


def test_two_accounts_have_isolated_identities_and_sessions(tmp_path: Path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    alice = store.register("Alice", "alice-password")
    bob = store.register("Bob", "bob-password")

    assert alice.id != bob.id
    assert alice.username == "Alice"
    assert bob.username == "Bob"

    alice_again, alice_token = store.login("alice", "alice-password")
    bob_again, bob_token = store.login("BOB", "bob-password")
    assert alice_again == alice
    assert bob_again == bob
    assert store.authenticate(alice_token) == alice
    assert store.authenticate(bob_token) == bob
    assert store.authenticate(alice_token) != bob

    # The DTO exposes only the public identity needed by callers.
    assert set(alice._fields) == {"id", "username"}
    assert "password" not in repr(alice).lower()
    assert alice_token not in repr(alice)


def test_wrong_password_and_unknown_user_use_auth_error(tmp_path: Path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    store.register("Alice", "alice-password")

    with pytest.raises(AccountAuthError):
        store.login("Alice", "wrong-password")
    with pytest.raises(AccountAuthError):
        store.login("missing", "wrong-password")


def test_case_insensitive_username_collision_and_persistence(tmp_path: Path):
    path = tmp_path / "accounts.sqlite3"
    store = AccountStore(path)
    account = store.register("Alice", "alice-password")

    with pytest.raises(AccountConflict):
        store.register("alice", "another-password")

    restored = AccountStore(path)
    assert restored.login("ALICE", "alice-password")[0] == account


def test_logout_and_expired_session_are_invalid(tmp_path: Path):
    path = tmp_path / "accounts.sqlite3"
    store = AccountStore(path)
    account = store.register("Alice", "alice-password")
    _, logged_out_token = store.login("Alice", "alice-password")
    store.logout(logged_out_token)
    assert store.authenticate(logged_out_token) is None
    store.logout(logged_out_token)

    _, expired_token = store.login("Alice", "alice-password")
    expired_at = time.time() - 1
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE sessions SET expires_at = ?",
            (expired_at,),
        )
    assert store.authenticate(expired_token) is None
    assert store.authenticate(expired_token) is None
    assert store.authenticate("unknown-token") is None
    assert account.username == "Alice"


def test_database_contains_hashes_but_no_passwords_or_raw_tokens(tmp_path: Path):
    path = tmp_path / "accounts.sqlite3"
    store = AccountStore(path)
    password = "alice-password"
    account = store.register("Alice", password)
    _, raw_token = store.login("Alice", password)

    raw_database = path.read_bytes()
    assert password.encode("utf-8") not in raw_database
    assert raw_token.encode("utf-8") not in raw_database

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT password_salt, password_hash, scrypt_n, scrypt_r, scrypt_p "
            "FROM accounts WHERE id = ?",
            (account.id,),
        ).fetchone()
        session = connection.execute(
            "SELECT token_hash, expires_at FROM sessions",
        ).fetchone()
    assert row is not None
    assert row[0] and row[1]
    assert row[2:] == (2**14, 8, 1)
    assert session is not None
    assert session[0] != raw_token.encode("utf-8")
    assert session[1] > time.time()
    assert session[1] <= time.time() + SESSION_TTL_SECONDS + 1


def test_default_state_path_honors_account_override(monkeypatch, tmp_path: Path):
    override = tmp_path / "custom" / "accounts.sqlite3"
    monkeypatch.setenv("FIREPLACE_ACCOUNT_STATE", str(override))
    assert default_state_path() == override

    monkeypatch.delenv("FIREPLACE_ACCOUNT_STATE")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_state_path() == tmp_path / "state" / "fireplace" / "accounts.sqlite3"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "valid-password"),
        ("valid-user", "short"),
        (None, "valid-password"),
        ("valid-user", None),
    ],
)
def test_bad_registration_input_is_value_error(tmp_path, username, password):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    with pytest.raises(ValueError):
        store.register(username, password)
