"""Local saved-deck service used by the web game.

The browser is allowed to edit a deck, but it is never the authority for
whether a card may be used.  :class:`DeckService` validates every submitted
card against :class:`~fireplace.web_gui.catalog.CardCatalog` and returns
catalog DTOs for display.  :class:`DeckStore` keeps only the small trusted
record needed to rebuild a match.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from hearthstone import cardxml
from hearthstone.enums import GameTag

from fireplace.arena.rules import HERO_IDS

from .catalog import CardCatalog


_DECK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_VALID_CARD_TYPES = frozenset(("MINION", "SPELL", "WEAPON", "HERO"))
_VALID_LOCALES = frozenset(("zhCN", "enUS"))
_MISSING = object()


class DeckConflict(RuntimeError):
    """The caller tried to update a deck from an out-of-date revision."""


class DeckStoreCorrupt(ValueError):
    """The existing JSON save is invalid and must not be overwritten."""


def default_state_path() -> Path:
    """Return the user-local deck save path, honoring the test override."""

    configured = os.environ.get("TAVERNLAB_DECK_STATE") or os.environ.get(
        "FIREPLACE_DECK_STATE"
    )
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "fireplace" / "decks.json"


def _copy_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy one persisted record without exposing store-owned dictionaries."""

    card_ids = record["card_ids"]
    if not isinstance(card_ids, list) or any(
        not isinstance(card_id, str) for card_id in card_ids
    ):
        raise ValueError("card_ids must be a list of strings")
    return {
        "id": record["id"],
        "revision": record["revision"],
        "name": record["name"],
        "hero_id": record["hero_id"],
        "card_ids": list(card_ids),
    }


class DeckStore:
    """Atomic JSON storage with an exclusive writer lock.

    The file contains ``{"decks": {id: record}}``.  A read and its matching
    write happen under the same lock in :meth:`put` and :meth:`delete`, so two
    processes cannot pass the revision check and then overwrite one another.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_state_path()

    @contextmanager
    def _locked(self):
        """Serialize all access to this store between local processes."""

        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise DeckStoreCorrupt(f"Deck save cannot be read: {self.path}") from exc

        if not isinstance(payload, dict) or set(payload) != {"decks"}:
            raise DeckStoreCorrupt(f"Deck save has an invalid shape: {self.path}")
        decks = payload["decks"]
        if not isinstance(decks, dict):
            raise DeckStoreCorrupt(f"Deck save has an invalid deck map: {self.path}")

        result: dict[str, dict[str, Any]] = {}
        for deck_id, raw in decks.items():
            if not isinstance(deck_id, str) or not _DECK_ID_RE.fullmatch(deck_id):
                raise DeckStoreCorrupt(f"Deck save has an invalid deck ID: {self.path}")
            if not isinstance(raw, dict):
                raise DeckStoreCorrupt(f"Deck save has an invalid deck record: {self.path}")
            try:
                record = _copy_record(raw)
            except (KeyError, TypeError, ValueError) as exc:
                raise DeckStoreCorrupt(f"Deck save has an incomplete deck: {self.path}") from exc
            if record["id"] != deck_id:
                raise DeckStoreCorrupt(f"Deck save has mismatched deck IDs: {self.path}")
            if (
                type(record["revision"]) is not int
                or record["revision"] < 1
                or not isinstance(record["name"], str)
                or not isinstance(record["hero_id"], str)
                or not isinstance(record["card_ids"], list)
                or any(not isinstance(card_id, str) for card_id in record["card_ids"])
            ):
                raise DeckStoreCorrupt(f"Deck save has an invalid deck record: {self.path}")
            result[deck_id] = record
        return result

    @staticmethod
    def _payload(decks: Mapping[str, Mapping[str, Any]]) -> str:
        return json.dumps(
            {"decks": decks}, ensure_ascii=False, separators=(",", ":")
        )

    def _write_unlocked(self, decks: Mapping[str, Mapping[str, Any]]) -> None:
        data = self._payload(decks)
        fd, temporary = tempfile.mkstemp(
            prefix=".decks-", suffix=".json", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self) -> dict[str, dict[str, Any]]:
        """Load all trusted records, or an empty mapping for a new store."""

        with self._locked():
            return self._read_unlocked()

    def get(self, deck_id: str) -> dict[str, Any] | None:
        with self._locked():
            record = self._read_unlocked().get(deck_id)
            return None if record is None else _copy_record(record)

    def put(
        self,
        record: Mapping[str, Any],
        *,
        expected_revision: int | None | object = _MISSING,
    ) -> dict[str, Any]:
        """Create or update one record with an atomic revision check.

        ``expected_revision`` omitted means create and requires the ID to be
        unused.  An integer means update and must match the stored revision.
        ``None`` is accepted as an explicit create expectation for callers
        that prefer not to rely on the sentinel.
        """

        candidate = _copy_record(record)
        deck_id = candidate["id"]
        with self._locked():
            decks = self._read_unlocked()
            current = decks.get(deck_id)
            if expected_revision is _MISSING or expected_revision is None:
                if current is not None:
                    raise DeckConflict(f"deck {deck_id!r} already exists")
            else:
                if type(expected_revision) is not int:
                    raise ValueError("expected_revision must be an integer")
                if current is None or current["revision"] != expected_revision:
                    raise DeckConflict(f"deck {deck_id!r} has changed")
            decks[deck_id] = candidate
            self._write_unlocked(decks)
        return _copy_record(candidate)

    # ``save`` is a small compatibility alias for callers that think in terms
    # of saving a record rather than putting it into a map.
    save = put

    def delete(self, deck_id: str, *, expected_revision: int) -> None:
        with self._locked():
            decks = self._read_unlocked()
            current = decks.get(deck_id)
            if current is None or current["revision"] != expected_revision:
                raise DeckConflict(f"deck {deck_id!r} has changed")
            del decks[deck_id]
            self._write_unlocked(decks)


class DeckService:
    """Validate, persist, and project user-created decks."""

    def __init__(
        self,
        *,
        store: DeckStore | None = None,
        catalog: CardCatalog | None = None,
    ) -> None:
        self.store = store if store is not None else DeckStore()
        self.catalog = catalog if catalog is not None else CardCatalog()
        self._copy_aliases: dict[str, str] | None = None

    @staticmethod
    def _locale(locale: str) -> str:
        if not isinstance(locale, str) or locale not in _VALID_LOCALES:
            raise ValueError("locale must be one of: zhCN, enUS")
        return locale

    @staticmethod
    def _body(body: object) -> Mapping[str, Any]:
        if not isinstance(body, Mapping):
            raise ValueError("deck body must be a JSON object")
        return body

    @staticmethod
    def _deck_id(value: object) -> str:
        if not isinstance(value, str) or not _DECK_ID_RE.fullmatch(value):
            raise ValueError("id must be a valid deck ID")
        return value

    @staticmethod
    def _name(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("name must be a string")
        name = value.strip()
        if not name or len(name) > 80:
            raise ValueError("name must contain between 1 and 80 characters")
        return name

    @staticmethod
    def _revision(value: object) -> int:
        if type(value) is not int or value < 1:
            raise ValueError("revision must be a positive integer")
        return value

    def _copy_alias_map(self) -> dict[str, str]:
        """Read stable deck-copy aliases when the catalog exposes its source.

        Current CardDefs data has no collectible records carrying this tag,
        but resolving it here makes duplicate limits safe for future data and
        for catalogs that already expose the standard XML source path.
        """

        if self._copy_aliases is not None:
            return self._copy_aliases
        aliases: dict[str, str] = {}
        source = getattr(self.catalog, "source_path", None)
        if source is None:
            self._copy_aliases = aliases
            return aliases
        try:
            loaded, _ = cardxml.load(path=source, locale="zhCN")
            by_dbf = {
                int(getattr(card, "dbf_id")): card_id
                for card_id, card in loaded.items()
                if isinstance(card_id, str)
                and isinstance(getattr(card, "dbf_id", None), int)
            }
            for card_id, card in loaded.items():
                if not isinstance(card_id, str):
                    continue
                tags = getattr(card, "tags", {})
                alias_dbf = tags.get(GameTag.DECK_RULE_COUNT_AS_COPY_OF_CARD_ID)
                target = by_dbf.get(alias_dbf) if isinstance(alias_dbf, int) else None
                if target is not None and target != card_id:
                    aliases[card_id] = target
        except (OSError, TypeError, ValueError, KeyError):
            # Metadata validation remains correct when a test double has no
            # XML source or a custom source is unavailable.
            aliases = {}
        self._copy_aliases = aliases
        return aliases

    def _copy_key(self, card_id: str) -> str:
        aliases = self._copy_alias_map()
        seen: set[str] = set()
        current = card_id
        while current in aliases and current not in seen:
            seen.add(current)
            current = aliases[current]
        return current

    def _validate_cards(self, hero_id: str, card_ids: object) -> list[str]:
        if not isinstance(hero_id, str) or hero_id not in HERO_IDS:
            raise ValueError("hero_id must be one of the nine classic heroes")
        if not isinstance(card_ids, list):
            raise ValueError("card_ids must be a list")
        if len(card_ids) > 30:
            raise ValueError("a deck may contain at most 30 cards")

        hero_class = HERO_IDS[hero_id].name
        counts: Counter[str] = Counter()
        result: list[str] = []
        for card_id in card_ids:
            if not isinstance(card_id, str):
                raise ValueError("card_ids must contain strings")
            card = self.catalog.get_card(card_id, locale="zhCN")
            if card is None:
                raise ValueError(f"unknown card: {card_id}")
            if not card.get("collectible"):
                raise ValueError(f"card is not collectible: {card_id}")
            if card_id.startswith("HERO_") or card.get("card_set") == "HERO_SKINS":
                raise ValueError(f"initial heroes and skins cannot be added: {card_id}")
            if card.get("type") not in _VALID_CARD_TYPES:
                raise ValueError(f"card type is not allowed: {card_id}")
            classes = card.get("classes") or []
            if not isinstance(classes, list) or (
                hero_class not in classes and "NEUTRAL" not in classes
            ):
                raise ValueError(f"card does not belong to {hero_class}: {card_id}")

            key = self._copy_key(card_id)
            counts[key] += 1
            rarity = card.get("rarity")
            limit = 1 if rarity == "LEGENDARY" else 2
            if counts[key] > limit:
                raise ValueError(f"too many copies of card: {card_id}")
            result.append(card_id)
        return result

    def _metadata(self, card_id: str, locale: str) -> dict[str, Any]:
        card = self.catalog.get_card(card_id, locale=locale)
        if card is None:
            # Stored records were validated on write.  Keep a clear failure if
            # a later data update removes one instead of returning untrusted
            # browser supplied values.
            raise DeckStoreCorrupt(f"saved card is missing from catalog: {card_id}")
        return card

    def _project(self, record: Mapping[str, Any], locale: str) -> dict[str, Any]:
        card_ids = list(record["card_ids"])
        try:
            self._validate_cards(record["hero_id"], card_ids)
            valid = True
        except ValueError:
            # A catalog update may remove or change a formerly legal card.
            # Keep the saved deck visible and deletable, but never offer it
            # for a match until the owner edits it into a legal deck again.
            valid = False

        def stored_card(card_id: str) -> dict[str, Any]:
            card = self.catalog.get_card(card_id, locale=locale)
            return card if card is not None else {"id": card_id, "name": card_id, "cost": None}

        return {
            "id": record["id"],
            "revision": record["revision"],
            "name": record["name"],
            "hero_id": record["hero_id"],
            "hero": stored_card(record["hero_id"]),
            "cards": [stored_card(card_id) for card_id in card_ids],
            "card_ids": card_ids,
            "complete": valid and len(card_ids) == 30,
            "valid": valid,
        }

    def _heroes(self, locale: str) -> list[dict[str, Any]]:
        return [self._metadata(hero_id, locale) for hero_id in HERO_IDS]

    def list(self, locale: str = "zhCN") -> dict[str, Any]:
        locale = self._locale(locale)
        records = self.store.load()
        return {
            "decks": [self._project(records[key], locale) for key in sorted(records)],
            "heroes": self._heroes(locale),
            "locale": locale,
        }

    def save(self, body: object, locale: str = "zhCN") -> dict[str, Any]:
        locale = self._locale(locale)
        data = self._body(body)
        hero_id = data.get("hero_id")
        if not isinstance(hero_id, str) or hero_id not in HERO_IDS:
            raise ValueError("hero_id must be one of the nine classic heroes")
        name = self._name(data.get("name"))
        card_ids = self._validate_cards(hero_id, data.get("card_ids"))

        raw_id = data.get("id", _MISSING)
        if raw_id is _MISSING or raw_id is None:
            deck_id = f"deck-{uuid.uuid4().hex}"
            expected: int | None | object = _MISSING
            revision = 1
        else:
            deck_id = self._deck_id(raw_id)
            revision = self._revision(data.get("revision"))
            expected = revision
            revision += 1

        record = {
            "id": deck_id,
            "revision": revision,
            "name": name,
            "hero_id": hero_id,
            "card_ids": card_ids,
        }
        self.store.put(record, expected_revision=expected)
        response = self.list(locale)
        response["saved_id"] = deck_id
        return response

    def delete(self, body: object, locale: str = "zhCN") -> dict[str, Any]:
        locale = self._locale(locale)
        data = self._body(body)
        deck_id = self._deck_id(data.get("id"))
        revision = self._revision(data.get("revision"))
        self.store.delete(deck_id, expected_revision=revision)
        return self.list(locale)

    def get_complete(self, deck_id: str) -> dict[str, Any]:
        """Return the trusted persisted record for match construction.

        This is deliberately stricter than the browser listing: incomplete
        drafts may be saved, but only a complete and still-valid deck may
        cross the boundary into a running match.
        """

        deck_id = self._deck_id(deck_id)
        record = self.store.get(deck_id)
        if record is None:
            raise ValueError(f"unknown deck: {deck_id}")
        card_ids = list(record["card_ids"])
        if len(card_ids) != 30:
            raise ValueError("deck must contain exactly 30 cards for a match")
        # Re-read current catalog metadata so a hand-edited/stale save cannot
        # smuggle cards into the engine after the browser validation step.
        self._validate_cards(record["hero_id"], card_ids)
        return {
            "hero_id": record["hero_id"],
            "card_ids": card_ids,
        }


__all__ = [
    "DeckConflict",
    "DeckService",
    "DeckStore",
    "DeckStoreCorrupt",
    "default_state_path",
]
