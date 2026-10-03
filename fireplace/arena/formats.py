"""Arena format configuration and the pinned 2016 historical data boundary.

``custom_v1`` remains the existing Arena mode.  The historical format is
deliberately self-contained: it reads only the checked-in bundle, validates
the source fingerprints before a new offer, and never changes the game
engine's card database.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


CUSTOM_FORMAT_ID = "custom_v1"
WILD_2016_09_02_FORMAT_ID = "wild_2016_09_02"
DATA_DIR = Path(__file__).resolve().parent / "data" / WILD_2016_09_02_FORMAT_ID
PROVENANCE_PATH = DATA_DIR / "provenance.json"
RATINGS_PATH = DATA_DIR / "cardtier.raw.json"
POOL_PATH = DATA_DIR / "pool.json"
OFFER_POLICY_PATH = DATA_DIR / "offer_policy.json"

CARDDEFS_SHA256 = "e41ba3137a210361ef51839c03d66eccc37cdf16c249b25f004069dfd0168d6e"
RATINGS_SHA256 = "9a832ddff0bbdcb46612ced24948542d29f01feb6148f20d5d0c3feca7b1b447"
FIXED_SETS: tuple[str, ...] = (
    "BASIC",
    "EXPERT1",
    "NAXX",
    "GVG",
    "BRM",
    "TGT",
    "LOE",
    "OG",
    "KARA",
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
KNOWN_CARD_TYPES = frozenset(("MINION", "SPELL", "WEAPON"))
KNOWN_RARITIES = frozenset(("FREE", "COMMON", "RARE", "EPIC", "LEGENDARY"))
HERO_CLASSES = {
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
EXCLUDED_IDS: tuple[str, ...] = tuple(
    f"OG_{suffix}"
    for suffix in (
        "096",
        "131",
        "162",
        "188",
        "255",
        "280",
        "281",
        "282",
        "283",
        "284",
        "286",
        "293",
        "301",
        "302",
        "303",
        "321",
        "334",
        "339",
    )
) + ("KAR_013",)
UNRATED_SOURCE_ROWS: tuple[str, ...] = ("EX1_062", "EX1_112", "NEW1_016", "PRO_001")

REGULAR_RARITIES = frozenset(("COMMON", "FREE"))
RARE_PLUS_RARITIES = frozenset(("RARE", "EPIC", "LEGENDARY"))
RARITY_WEIGHTS: Mapping[str, int] = MappingProxyType(
    {"COMMON": 68, "RARE": 20, "EPIC": 9, "LEGENDARY": 3}
)
GUARANTEED_RARE_PLUS_PICKS = frozenset((1, 10, 20, 30))
CLASS_WEIGHT = 2
EXPANSION_BOOST = 1
OFFER_SIZE = 3
HISTORICAL_PROFILE_HASHES: Mapping[str, str] = MappingProxyType(
    {
        # These identify the checked-in immutable bundle.  historical_profile
        # recomputes and verifies them when a run is created or offers resume.
        "manifest_sha256": "15b1a8343f4b3d67bb76b4ea83b39f0735952111bc29c06cfdc927f41cf0a972",
        "ratings_sha256": RATINGS_SHA256,
        "carddefs_sha256": CARDDEFS_SHA256,
        "pool_sha256": "2c318c6288d45c2b0487156907ce5e997a28cc22b9ea6e8e8183a7a04f6b47a6",
        "policy_sha256": "25d5b8a532b276d07382b4e3ab7f3ab6f56b38eb3da1753ae6a2553e38dc59fa",
        "score_fingerprint": "0fea4d5b397e1517b1bf14e8ff5af4ad567807a56902f9ceaa8c04d90ab08688",
    }
)


class HistoricalFormatError(ValueError):
    """The pinned historical bundle failed validation."""


@dataclass(frozen=True, slots=True)
class FormatConfig:
    id: str
    max_wins: int
    max_losses: int
    fixed_sets: tuple[str, ...] = ()
    profile_hashes: Mapping[str, str] = field(default_factory=dict)
    offer_policy_accuracy: str = "existing"

    def __post_init__(self) -> None:
        object.__setattr__(self, "fixed_sets", tuple(self.fixed_sets))
        object.__setattr__(self, "profile_hashes", MappingProxyType(dict(self.profile_hashes)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "max_wins": self.max_wins,
            "max_losses": self.max_losses,
            "fixed_sets": list(self.fixed_sets),
            "profile_hashes": dict(self.profile_hashes),
            "offer_policy_accuracy": self.offer_policy_accuracy,
        }


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(path: Path) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HistoricalFormatError(f"historical Arena data is unavailable: {path}") from exc
    return data, hashlib.sha256(data).hexdigest()


def _json(path: Path) -> tuple[Any, bytes, str]:
    data, digest = _sha256(path)
    try:
        return json.loads(data.decode("utf-8")), data, digest
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalFormatError(f"historical Arena file is not valid JSON: {path}") from exc


def _manifest() -> tuple[dict[str, Any], bytes, str]:
    payload, data, digest = _json(PROVENANCE_PATH)
    if not isinstance(payload, dict):
        raise HistoricalFormatError("historical Arena manifest must be an object")
    return payload, data, digest


def historical_draft_rng(seed: int, pick_number: int, *, purpose: str = "human") -> random.Random:
    """Return an independent deterministic stream derived from SHA-256."""

    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(pick_number) is not int or pick_number < 0:
        raise ValueError("pick_number must be a non-negative integer")
    if not isinstance(purpose, str) or not purpose:
        raise ValueError("purpose must be a non-empty string")
    material = f"fireplace-arena:{WILD_2016_09_02_FORMAT_ID}:{seed}:{pick_number}:{purpose}".encode(
        "utf-8"
    )
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big"))


def validate_historical_data() -> dict[str, Any]:
    """Validate all source, metadata, checksum and class-boundary invariants."""

    manifest, _, manifest_sha = _manifest()
    if manifest_sha != HISTORICAL_PROFILE_HASHES["manifest_sha256"]:
        raise HistoricalFormatError("historical manifest checksum is not the pinned artifact")
    if manifest.get("format_id") != WILD_2016_09_02_FORMAT_ID:
        raise HistoricalFormatError("historical manifest has the wrong format ID")
    if tuple(manifest.get("fixed_sets", ())) != FIXED_SETS:
        raise HistoricalFormatError("historical manifest fixed set list changed")
    if tuple(manifest.get("score_columns", ())) != SCORE_COLUMNS:
        raise HistoricalFormatError("historical manifest score columns changed")
    carddefs_sha = str(manifest.get("carddefs", {}).get("sha256", ""))
    if carddefs_sha != CARDDEFS_SHA256:
        raise HistoricalFormatError("historical CardDefs provenance checksum changed")

    from .ratings import MissingHistoricalScore, load_ratings, validate_ratings

    ratings_info = validate_ratings()
    ratings_payload, _, ratings_sha = _json(RATINGS_PATH)
    if ratings_sha != RATINGS_SHA256 or manifest.get("ratings", {}).get("sha256") != RATINGS_SHA256:
        raise HistoricalFormatError("historical ratings checksum metadata changed")
    if not isinstance(ratings_payload, list) or len(ratings_payload) != ratings_info["rows"]:
        raise HistoricalFormatError("historical ratings row count changed")
    ratings = load_ratings()
    if len(ratings) != 922:
        raise HistoricalFormatError("historical rating IDs are not unique")

    from .pool import _historical_cards_from_payload, load_historical_pool

    pool, _, pool_sha = load_historical_pool()
    if pool_sha != HISTORICAL_PROFILE_HASHES["pool_sha256"]:
        raise HistoricalFormatError("historical legal pool is not the pinned artifact")
    cards = _historical_cards_from_payload(pool)
    if len(cards) != 899 or manifest.get("legal_pool_count") != 899:
        raise HistoricalFormatError(f"expected 899 legal historical cards, got {len(cards)}")
    # The frozen pool stores the historical DBF ID and card ID separately.
    # Check the latter against the current Fireplace database so a generated
    # bundle cannot silently refer to cards the runtime cannot instantiate.
    from .. import cards as current_cards

    try:
        if not current_cards.db.initialized:
            current_cards.db.initialize()
        missing_current_ids = [card.id for card in cards if card.id not in current_cards.db]
    except Exception as exc:
        raise HistoricalFormatError("current Fireplace card database is unavailable") from exc
    if missing_current_ids:
        raise HistoricalFormatError(
            "historical legal pool IDs are absent from the current Fireplace database: "
            + ", ".join(missing_current_ids[:5])
        )
    card_ids = {card.id for card in cards}
    if len(card_ids) != len(cards):
        raise HistoricalFormatError("historical legal card IDs are not unique")
    class_counts = {hero_class: 0 for hero_class in SCORE_COLUMNS}
    for card in cards:
        if card.dbf_id <= 0:
            raise HistoricalFormatError(f"missing current dbf ID for {card.id}")
        if card.card_class not in set(SCORE_COLUMNS) | {"NEUTRAL"}:
            raise HistoricalFormatError(f"missing class metadata for {card.id}")
        if card.card_class != "NEUTRAL":
            class_counts[card.card_class] += 1
        if card.id not in ratings:
            required_class = card.card_class if card.card_class != "NEUTRAL" else SCORE_COLUMNS[0]
            raise MissingHistoricalScore(card.id, required_class)
        row = ratings[card.id]
        if card.card_class != "NEUTRAL":
            row.score_for(card.card_class)
        else:
            for hero_class in SCORE_COLUMNS:
                row.score_for(hero_class)
    if any(count < 3 for count in class_counts.values()):
        raise HistoricalFormatError("historical legal pool is missing one or more hero class buckets")
    for hero_class in SCORE_COLUMNS:
        eligible = [card for card in cards if card.card_class in {"NEUTRAL", hero_class}]
        bucket_counts = {
            "COMMON": sum(card.rarity in REGULAR_RARITIES for card in eligible),
            "RARE": sum(card.rarity == "RARE" for card in eligible),
            "EPIC": sum(card.rarity == "EPIC" for card in eligible),
            "LEGENDARY": sum(card.rarity == "LEGENDARY" for card in eligible),
        }
        if any(count < OFFER_SIZE for count in bucket_counts.values()):
            raise HistoricalFormatError(
                f"historical eligible pool for {hero_class} has an undersized rarity bucket"
            )

    if pool.get("candidate_count") != 918 or pool.get("legal_pool_count") != 899:
        raise HistoricalFormatError("historical pool counts changed")
    if tuple(pool.get("unrated_source_rows", ())) != UNRATED_SOURCE_ROWS:
        raise HistoricalFormatError("historical pool unrated boundary changed")
    exclusions = pool.get("exclusions")
    if not isinstance(exclusions, list) or len(exclusions) != len(EXCLUDED_IDS):
        raise HistoricalFormatError("historical exclusion records changed")
    exclusion_ids = [entry.get("id") if isinstance(entry, dict) else None for entry in exclusions]
    if tuple(exclusion_ids) != EXCLUDED_IDS or len(set(exclusion_ids)) != len(EXCLUDED_IDS):
        raise HistoricalFormatError("historical exclusion IDs changed")
    for entry in exclusions:
        if not isinstance(entry, dict) or not all(entry.get(key) for key in ("rationale", "source", "confidence")):
            raise HistoricalFormatError(f"incomplete exclusion rationale for {entry.get('id')!r}")
    policy, _, _ = _json(OFFER_POLICY_PATH)
    if not isinstance(policy, dict) or policy.get("accuracy") != "reconstructed":
        raise HistoricalFormatError("historical policy is malformed")
    expected_policy_sha = hashlib.sha256(_canonical(policy)).hexdigest()
    if expected_policy_sha != manifest.get("policy_sha256"):
        raise HistoricalFormatError("historical policy checksum changed")
    if expected_policy_sha != HISTORICAL_PROFILE_HASHES["policy_sha256"]:
        raise HistoricalFormatError("historical policy is not the pinned artifact")

    unrated = tuple(manifest.get("unrated_source_rows", ()))
    if unrated != UNRATED_SOURCE_ROWS:
        raise HistoricalFormatError("historical unrated source-row boundary changed")
    candidate_ids = set(ratings) - set(UNRATED_SOURCE_ROWS)
    if len(candidate_ids) != 918 or not set(EXCLUDED_IDS) <= candidate_ids:
        raise HistoricalFormatError("historical 918-card candidate boundary changed")
    if candidate_ids - set(EXCLUDED_IDS) != card_ids:
        raise HistoricalFormatError("historical legal pool does not match exclusions")
    if pool_sha != manifest.get("pool_sha256"):
        raise HistoricalFormatError("historical legal pool checksum changed")
    exclusions_sha = hashlib.sha256(_canonical(exclusions)).hexdigest()

    score_fingerprint = hashlib.sha256(
        _canonical([{"id": card_id, "value": list(ratings[card_id].values)} for card_id in sorted(card_ids)])
    ).hexdigest()
    if score_fingerprint != HISTORICAL_PROFILE_HASHES["score_fingerprint"]:
        raise HistoricalFormatError("historical score fingerprint is not the pinned artifact")
    return {
        "format_id": WILD_2016_09_02_FORMAT_ID,
        "as_of": "2016-09-02",
        "fixed_sets": list(FIXED_SETS),
        "score_columns": list(SCORE_COLUMNS),
        "candidate_count": 918,
        "legal_pool_count": 899,
        "manifest_sha256": manifest_sha,
        "ratings_sha256": ratings_sha,
        "carddefs_sha256": str(manifest.get("carddefs", {}).get("sha256", CARDDEFS_SHA256)),
        "cards_sha256": pool_sha,
        "pool_sha256": pool_sha,
        "exclusions_sha256": exclusions_sha,
        "policy_sha256": expected_policy_sha,
        "score_fingerprint": score_fingerprint,
        "offer_policy_accuracy": str(policy.get("accuracy", "reconstructed")),
    }


def historical_profile() -> dict[str, Any]:
    """Return a freshly verified profile suitable for persisted run headers."""

    return validate_historical_data()


def historical_eligible_cards(hero_id: str):
    """Compatibility wrapper for the lazy historical pool implementation."""

    from .pool import historical_eligible_cards as _historical_eligible_cards

    return _historical_eligible_cards(hero_id)


def historical_card_offer(rng, pool, pick_number):
    """Compatibility wrapper for the historical offer implementation."""

    from .draft import historical_card_offer as _historical_card_offer

    return _historical_card_offer(rng, pool, pick_number)


def __getattr__(name: str):
    # Keep the original formats.HistoricalCard import surface without making
    # formats load the current card database or historical JSON at import time.
    if name == "HistoricalCard":
        from .pool import HistoricalCard

        return HistoricalCard
    raise AttributeError(name)


_CUSTOM_FORMAT = FormatConfig(CUSTOM_FORMAT_ID, max_wins=7, max_losses=3)


def get_format(format_id: str) -> FormatConfig:
    """Resolve a format without loading historical data for ``custom_v1``."""

    if format_id == CUSTOM_FORMAT_ID:
        return _CUSTOM_FORMAT
    if format_id != WILD_2016_09_02_FORMAT_ID:
        raise ValueError(f"unknown Arena format: {format_id!r}")
    return FormatConfig(
        WILD_2016_09_02_FORMAT_ID,
        max_wins=12,
        max_losses=3,
        fixed_sets=FIXED_SETS,
        profile_hashes=HISTORICAL_PROFILE_HASHES,
        offer_policy_accuracy="reconstructed",
    )


__all__ = [
    "CARDDEFS_SHA256",
    "CLASS_WEIGHT",
    "CUSTOM_FORMAT_ID",
    "DATA_DIR",
    "EXCLUDED_IDS",
    "EXPANSION_BOOST",
    "FIXED_SETS",
    "FormatConfig",
    "GUARANTEED_RARE_PLUS_PICKS",
    "HistoricalCard",
    "HistoricalFormatError",
    "KNOWN_CARD_TYPES",
    "KNOWN_RARITIES",
    "OFFER_SIZE",
    "OFFER_POLICY_PATH",
    "POOL_PATH",
    "PROVENANCE_PATH",
    "RARITY_WEIGHTS",
    "RARE_PLUS_RARITIES",
    "REGULAR_RARITIES",
    "SCORE_COLUMNS",
    "WILD_2016_09_02_FORMAT_ID",
    "get_format",
    "historical_card_offer",
    "historical_draft_rng",
    "historical_eligible_cards",
    "historical_profile",
    "validate_historical_data",
]
