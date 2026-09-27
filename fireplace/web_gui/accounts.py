"""Local username/password accounts and opaque login sessions.

The web GUI currently runs as a small local server, so account data lives in a
SQLite database on the host.  Passwords are stored as salted scrypt digests;
session tokens are returned only to the caller and the database stores their
SHA-256 digests.  ``Account`` deliberately contains only the public identity
fields that callers need when scoping decks and matches.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Tuple


class AccountConflict(RuntimeError):
    """The requested username is already registered."""


class AccountAuthError(RuntimeError):
    """The supplied username or password is not valid."""


class Account(namedtuple("Account", ("id", "username"))):
    """Public account identity returned by the account store.

    This is intentionally a tiny immutable DTO: password material and session
    tokens never appear in it.
    """

    __slots__ = ()


_MIN_USERNAME_LENGTH = 1
_MAX_USERNAME_LENGTH = 64
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 256

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_SALT_BYTES = 16
_SESSION_TOKEN_BYTES = 32
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

_DUMMY_SALT = b"fireplace-invalid-salt"
_DUMMY_PASSWORD_HASH = hashlib.scrypt(
    b"fireplace-invalid-password",
    salt=_DUMMY_SALT,
    n=_SCRYPT_N,
    r=_SCRYPT_R,
    p=_SCRYPT_P,
    dklen=_SCRYPT_DKLEN,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    password_salt BLOB NOT NULL,
    password_hash BLOB NOT NULL,
    scrypt_n INTEGER NOT NULL,
    scrypt_r INTEGER NOT NULL,
    scrypt_p INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash BLOB PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
"""


def default_state_path() -> Path:
    """Return the account database path used by a local server."""

    configured = os.environ.get("TAVERNLAB_ACCOUNT_STATE") or os.environ.get(
        "FIREPLACE_ACCOUNT_STATE"
    )
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "fireplace" / "accounts.sqlite3"


def _validate_username(value: object) -> Tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("username must be a string")
    username = value.strip()
    if not _MIN_USERNAME_LENGTH <= len(username) <= _MAX_USERNAME_LENGTH:
        raise ValueError(
            "username must contain between "
            f"{_MIN_USERNAME_LENGTH} and {_MAX_USERNAME_LENGTH} characters"
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in username):
        raise ValueError("username cannot contain control characters")
    return username, username.casefold()


def _validate_password(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("password must be a string")
    if not _MIN_PASSWORD_LENGTH <= len(value) <= _MAX_PASSWORD_LENGTH:
        raise ValueError(
            "password must contain between "
            f"{_MIN_PASSWORD_LENGTH} and {_MAX_PASSWORD_LENGTH} characters"
        )
    return value


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )


def _token_hash(raw_token: str) -> bytes:
    return hashlib.sha256(raw_token.encode("utf-8")).digest()


class AccountStore:
    """Concurrent SQLite-backed account and session storage."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else default_state_path()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # Apply the private mode when creating the state directory without
        # changing permissions on a caller-provided existing parent (the
        # override may intentionally point at a shared temporary directory).
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            # Keep schema creation in the same serialized transaction as the
            # other writers.  Changing SQLite's journal mode on every store
            # construction takes an exclusive lock and makes simultaneous
            # server requests unnecessarily fragile.
            connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA + "\nCOMMIT;")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _account(row: sqlite3.Row) -> Account:
        return Account(id=row["id"], username=row["username"])

    def register(self, username: str, password: str) -> Account:
        """Create and return an account with a case-insensitive username."""

        display_name, username_key = _validate_username(username)
        password = _validate_password(password)
        salt = secrets.token_bytes(_SALT_BYTES)
        digest = _password_hash(password, salt)

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT 1 FROM accounts WHERE username_key = ?",
                    (username_key,),
                ).fetchone()
                if existing is not None:
                    raise AccountConflict("username is already registered")

                # UUID4 hex is stable, URL-safe, and is the ID format shared
                # with the account-scoped deck/match registry.
                for _ in range(3):
                    account_id = uuid.uuid4().hex
                    try:
                        connection.execute(
                            """
                            INSERT INTO accounts (
                                id, username, username_key, password_salt,
                                password_hash, scrypt_n, scrypt_r, scrypt_p,
                                created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                account_id,
                                display_name,
                                username_key,
                                sqlite3.Binary(salt),
                                sqlite3.Binary(digest),
                                _SCRYPT_N,
                                _SCRYPT_R,
                                _SCRYPT_P,
                                time.time(),
                            ),
                        )
                    except sqlite3.IntegrityError as exc:
                        # A UUID collision is extraordinarily unlikely; a
                        # username collision can still race another process.
                        if connection.execute(
                            "SELECT 1 FROM accounts WHERE username_key = ?",
                            (username_key,),
                        ).fetchone() is not None:
                            raise AccountConflict("username is already registered") from exc
                        continue
                    account = Account(account_id, display_name)
                    connection.commit()
                    return account
                raise RuntimeError("could not allocate a unique account ID")
            except Exception:
                connection.rollback()
                raise

    def login(self, username: str, password: str) -> Tuple[Account, str]:
        """Authenticate an account and return its identity and raw session token."""

        _display_name, username_key = _validate_username(username)
        password = _validate_password(password)

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, username, password_salt, password_hash,
                       scrypt_n, scrypt_r, scrypt_p
                FROM accounts WHERE username_key = ?
                """,
                (username_key,),
            ).fetchone()

            if row is None:
                candidate = _password_hash(password, _DUMMY_SALT)
                expected = _DUMMY_PASSWORD_HASH
            else:
                try:
                    candidate = hashlib.scrypt(
                        password.encode("utf-8"),
                        salt=bytes(row["password_salt"]),
                        n=int(row["scrypt_n"]),
                        r=int(row["scrypt_r"]),
                        p=int(row["scrypt_p"]),
                        dklen=len(bytes(row["password_hash"])),
                    )
                    expected = bytes(row["password_hash"])
                except (TypeError, ValueError, OverflowError):
                    # A damaged password record must still take the same
                    # verification path and produce a generic auth failure.
                    candidate = _password_hash(password, _DUMMY_SALT)
                    expected = _DUMMY_PASSWORD_HASH

            valid = hmac.compare_digest(candidate, expected)
            if row is None or not valid:
                raise AccountAuthError("invalid username or password")

            raw_token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
            now = time.time()
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
                connection.execute(
                    """
                    INSERT INTO sessions(token_hash, account_id, expires_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        sqlite3.Binary(_token_hash(raw_token)),
                        row["id"],
                        now + SESSION_TTL_SECONDS,
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            return self._account(row), raw_token

    def authenticate(self, raw_token: str) -> Optional[Account]:
        """Resolve a live session token, returning ``None`` when it is invalid."""

        if not isinstance(raw_token, str):
            raise ValueError("session token must be a string")
        if not raw_token:
            return None

        now = time.time()
        token_digest = sqlite3.Binary(_token_hash(raw_token))
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT a.id, a.username, s.expires_at
                FROM sessions AS s
                JOIN accounts AS a ON a.id = s.account_id
                WHERE s.token_hash = ?
                """,
                (token_digest,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest,))
                connection.commit()
                return None
            return self._account(row)

    def logout(self, raw_token: str) -> None:
        """Invalidate a session token.  Repeated logout is harmless."""

        if not isinstance(raw_token, str):
            raise ValueError("session token must be a string")
        if not raw_token:
            return None
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (sqlite3.Binary(_token_hash(raw_token)),),
            )
            connection.commit()
        return None


__all__ = [
    "Account",
    "AccountAuthError",
    "AccountConflict",
    "AccountStore",
    "SESSION_TTL_SECONDS",
    "default_state_path",
]
