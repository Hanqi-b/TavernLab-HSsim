"""Pinned Lightforge Arena scores for the 2016-09-02 historical format.

The source contains one nine-cell row per card.  A cell is either an empty
string (the source did not rate that class) or a score such as ``"64*"``.
The original cell is always retained; callers that request an empty cell get
an error containing the card and class instead of a random fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping


DATA_DIR = Path(__file__).resolve().parent / "data" / "wild_2016_09_02"
RATINGS_PATH = DATA_DIR / "cardtier.raw.json"
RATINGS_SHA256 = "9a832ddff0bbdcb46612ced24948542d29f01feb6148f20d5d0c3feca7b1b447"
RATINGS_URL = (
    "https://raw.githubusercontent.com/rembound/Arena-Helper/"
    "fb14acf093b4c5abb2bfb8fa1187ce497e06900b/data/cardtier.json"
)
SCORE_COLUMNS: tuple[str, ...] = (
    "WARRIOR",
    "SHAMAN",
    "ROGUE",
    "PALADIN",
    "HUNTER",
    "DRUID",
    "WARLOCK",
    "MAGE",
    "PRIEST",
)
SCORE_INDEX = {name: index for index, name in enumerate(SCORE_COLUMNS)}


class HistoricalRatingsError(ValueError):
    """The pinned ratings file is malformed or does not match its checksum."""


class MissingHistoricalScore(HistoricalRatingsError):
    """A requested card/class cell is blank in the original source."""

    def __init__(self, card_id: str, hero_class: str):
        self.card_id = card_id
        self.hero_class = hero_class
        super().__init__(f"missing historical Arena score for {card_id}/{hero_class}")


_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")


def _numeric(value: str, card_id: str, hero_class: str) -> int | float:
    marker = value[:-1] if value.endswith("*") else value
    if marker.startswith(">"):
        marker = marker[1:]
    if _NUMBER_RE.fullmatch(marker) is None:
        raise HistoricalRatingsError(
            f"invalid historical Arena score for {card_id}/{hero_class}: {value!r}"
        )
    try:
        number = float(marker)
    except ValueError as exc:
        raise HistoricalRatingsError(
            f"invalid historical Arena score for {card_id}/{hero_class}: {value!r}"
        ) from exc
    if not math.isfinite(number):
        raise HistoricalRatingsError(
            f"non-finite historical Arena score for {card_id}/{hero_class}: {value!r}"
        )
    return int(number) if number.is_integer() else number


@dataclass(frozen=True, slots=True)
class ScoreCell:
    """One source score plus machine-readable marker flags."""

    raw: str
    numeric: int | float
    starred: bool = False
    over_100: bool = False

    @property
    def flags(self) -> dict[str, bool]:
        return {"starred": self.starred, "over_100": self.over_100}

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "numeric": self.numeric,
            "starred": self.starred,
            "over_100": self.over_100,
        }


@dataclass(frozen=True, slots=True)
class RatingRow:
    """A complete raw Lightforge row."""

    card_id: str
    name: str
    values: tuple[str, ...]

    @property
    def id(self) -> str:
        return self.card_id

    def raw_for(self, hero_class: str) -> str:
        return self.values[_class_index(hero_class)]

    def score_for(self, hero_class: str) -> ScoreCell:
        hero_class = _normalise_class(hero_class)
        raw = self.values[SCORE_INDEX[hero_class]]
        if raw == "":
            raise MissingHistoricalScore(self.card_id, hero_class)
        return _parse_cell(raw, self.card_id, hero_class)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.card_id, "name": self.name, "value": list(self.values)}


# Names retained as aliases for callers that use either terminology.
ArenaScore = ScoreCell
CardRating = RatingRow


def _normalise_class(hero_class: object) -> str:
    value = getattr(hero_class, "name", hero_class)
    if not isinstance(value, str):
        raise ValueError(f"unknown historical Arena class: {hero_class!r}")
    value = value.upper()
    # Accept the stable classic hero IDs without importing the arena rules
    # module (which keeps the data provider usable during package bootstrap).
    hero_map = {
        "HERO_01": "WARRIOR",
        "HERO_02": "SHAMAN",
        "HERO_03": "ROGUE",
        "HERO_04": "PALADIN",
        "HERO_05": "HUNTER",
        "HERO_06": "DRUID",
        "HERO_07": "WARLOCK",
        "HERO_08": "MAGE",
        "HERO_09": "PRIEST",
    }
    value = hero_map.get(value, value)
    if value not in SCORE_INDEX:
        raise ValueError(f"unknown historical Arena class: {hero_class!r}")
    return value


def _class_index(hero_class: object) -> int:
    return SCORE_INDEX[_normalise_class(hero_class)]


def _parse_cell(raw: str, card_id: str, hero_class: str) -> ScoreCell:
    if not isinstance(raw, str) or raw == "":
        raise MissingHistoricalScore(card_id, hero_class)
    starred = raw.endswith("*")
    marker = raw[:-1] if starred else raw
    over_100 = marker.startswith(">")
    numeric = _numeric(raw, card_id, hero_class)
    # Numeric values above 100 are retained as-is and carry the same explicit
    # flag as a source ``>100`` marker.  Never clamp or turn them into infinity.
    over_100 = over_100 or numeric > 100
    return ScoreCell(raw=raw, numeric=numeric, starred=starred, over_100=over_100)


def _parse_payload(payload: Any) -> tuple[RatingRow, ...]:
    if not isinstance(payload, list):
        raise HistoricalRatingsError("historical rating source must be a JSON list")
    result: list[RatingRow] = []
    seen: set[str] = set()
    for index, row in enumerate(payload):
        if not isinstance(row, dict) or set(row) != {"id", "name", "value"}:
            raise HistoricalRatingsError(f"invalid historical rating row at index {index}")
        card_id = row["id"]
        name = row["name"]
        values = row["value"]
        if not isinstance(card_id, str) or not card_id or card_id in seen:
            raise HistoricalRatingsError(f"duplicate or invalid rating card ID at index {index}")
        if not isinstance(name, str):
            raise HistoricalRatingsError(f"invalid rating name for {card_id}")
        if not isinstance(values, list) or len(values) != len(SCORE_COLUMNS):
            raise HistoricalRatingsError(f"rating {card_id} must contain exactly nine cells")
        for cell in values:
            if not isinstance(cell, str):
                raise HistoricalRatingsError(f"rating {card_id} has a non-string cell")
            if cell:
                # Parse every nonblank cell now so malformed source data fails
                # before an offer or AI draft can consume it.
                _parse_cell(cell, card_id, "source")
        seen.add(card_id)
        result.append(RatingRow(card_id=card_id, name=name, values=tuple(values)))
    return tuple(result)


def _raw_bytes() -> bytes:
    try:
        data = RATINGS_PATH.read_bytes()
    except OSError as exc:
        raise HistoricalRatingsError(f"historical ratings are unavailable: {RATINGS_PATH}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != RATINGS_SHA256:
        raise HistoricalRatingsError(
            f"historical ratings checksum mismatch: {actual} != {RATINGS_SHA256}"
        )
    return data


@lru_cache(maxsize=1)
def _load_cached() -> Mapping[str, RatingRow]:
    data = _raw_bytes()
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalRatingsError("historical ratings are not valid UTF-8 JSON") from exc
    return {row.card_id: row for row in _parse_payload(payload)}


def load_ratings() -> Mapping[str, RatingRow]:
    """Load all pinned rows, verifying bytes and schema once per process."""

    return _load_cached()


def iter_ratings() -> Iterable[RatingRow]:
    return load_ratings().values()


def get_rating(card_id: str, hero_class: object) -> ScoreCell:
    """Return one score cell, raising on an original blank cell."""

    if not isinstance(card_id, str) or not card_id:
        raise ValueError("card_id must be a non-empty string")
    normalised_class = _normalise_class(hero_class)
    row = load_ratings().get(card_id)
    if row is None:
        raise MissingHistoricalScore(card_id, normalised_class)
    return row.score_for(normalised_class)


def score_for(card_id: str, hero_class: object) -> ScoreCell:
    return get_rating(card_id, hero_class)


def parse_score_cell(raw: str, card_id: str = "<trace>", hero_class: str = "<trace>") -> ScoreCell:
    """Parse one preserved raw cell without loading the ratings file.

    Archived AI traces use this pure parser during structural validation so a
    saved match can be checked even when the optional historical bundle is
    unavailable.
    """

    return _parse_cell(raw, card_id, hero_class)


def numeric_score(card_id: str, hero_class: object) -> int | float:
    return get_rating(card_id, hero_class).numeric


def raw_score(card_id: str, hero_class: object) -> str:
    return get_rating(card_id, hero_class).raw


def ratings_fingerprint() -> str:
    """Return the verified upstream file fingerprint."""

    return hashlib.sha256(_raw_bytes()).hexdigest()


def validate_ratings() -> dict[str, Any]:
    """Perform strict source validation and return compact source metadata."""

    rows = tuple(iter_ratings())
    if len(rows) != 922:
        raise HistoricalRatingsError(f"expected 922 historical rating rows, got {len(rows)}")
    marker_counts = {"starred": 0, "over_100": 0}
    for row in rows:
        for hero_class, raw in zip(SCORE_COLUMNS, row.values):
            if not raw:
                continue
            cell = _parse_cell(raw, row.card_id, hero_class)
            marker_counts["starred"] += cell.starred
            marker_counts["over_100"] += cell.over_100
    return {
        "rows": len(rows),
        "columns": list(SCORE_COLUMNS),
        "sha256": RATINGS_SHA256,
        "marker_counts": marker_counts,
    }


__all__ = [
    "ArenaScore",
    "CardRating",
    "DATA_DIR",
    "HistoricalRatingsError",
    "MissingHistoricalScore",
    "RATINGS_PATH",
    "RATINGS_SHA256",
    "RATINGS_URL",
    "RatingRow",
    "SCORE_COLUMNS",
    "SCORE_INDEX",
    "ScoreCell",
    "get_rating",
    "iter_ratings",
    "load_ratings",
    "numeric_score",
    "parse_score_cell",
    "ratings_fingerprint",
    "raw_score",
    "score_for",
    "validate_ratings",
]
