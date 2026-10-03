#!/usr/bin/env python3
"""Import the pinned 2016 Arena rating and card-definition sources.

The importer deliberately has no project imports.  It can be run from a
fresh checkout (or from a release build) and writes a deterministic bundle
under ``fireplace/arena/data/wild_2016_09_02``.  The Lightforge JSON is
copied byte for byte after its checksum is verified.  CardDefs.xml is an
import-time source only; the generated package contains its fingerprint and
the derived pool metadata, rather than a second seven-megabyte XML copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


RATINGS_URL = (
    "https://raw.githubusercontent.com/rembound/Arena-Helper/"
    "fb14acf093b4c5abb2bfb8fa1187ce497e06900b/data/cardtier.json"
)
RATINGS_SHA256 = "9a832ddff0bbdcb46612ced24948542d29f01feb6148f20d5d0c3feca7b1b447"
CARDDEFS_URL = (
    "https://raw.githubusercontent.com/HearthSim/hsdata/"
    "ca84daa2932b1235f2f38da53e88a2aa2b190f4c/CardDefs.xml"
)
CARDDEFS_SHA256 = "e41ba3137a210361ef51839c03d66eccc37cdf16c249b25f004069dfd0168d6e"

FORMAT_ID = "wild_2016_09_02"
FIXED_SETS = ("BASIC", "EXPERT1", "NAXX", "GVG", "BRM", "TGT", "LOE", "OG", "KARA")
SCORE_COLUMNS = (
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
CLASS_INDEX = {name: index for index, name in enumerate(SCORE_COLUMNS)}
CLASS_BY_XML = {
    "2": "DRUID",
    "3": "HUNTER",
    "4": "MAGE",
    "5": "PALADIN",
    "6": "PRIEST",
    "7": "ROGUE",
    "8": "SHAMAN",
    "9": "WARLOCK",
    "10": "WARRIOR",
    "12": "NEUTRAL",
}
SET_BY_XML = {
    "2": "BASIC",
    "3": "EXPERT1",
    "4": "HOF",
    "11": "PROMO",
    "12": "NAXX",
    "13": "GVG",
    "14": "BRM",
    "15": "TGT",
    "20": "LOE",
    "21": "OG",
    "23": "KARA",
}
TYPE_BY_XML = {"4": "MINION", "5": "SPELL", "7": "WEAPON"}
RARITY_BY_XML = {
    "1": "COMMON",
    "2": "FREE",
    "3": "RARE",
    "4": "EPIC",
    "5": "LEGENDARY",
}

# These are policy exclusions, rather than a filter inferred from an empty
# Lightforge score.  OG_281 is retained as a named uncertain case because the
# exact date-specific ban evidence was not recovered.
CTHUN_EXCLUSIONS = tuple(
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
)
POLICY_EXCLUSIONS = CTHUN_EXCLUSIONS + ("KAR_013",)
UNRATED_SOURCE_ROWS = ("EX1_062", "EX1_112", "NEW1_016", "PRO_001")

OFFER_POLICY: dict[str, Any] = {
    "version": 1,
    "accuracy": "reconstructed",
    "source_note": "Exact 2016 offering rates were not recovered; these weights are an explicit approximation.",
    "rarity_weights": {"COMMON": 68, "RARE": 20, "EPIC": 9, "LEGENDARY": 3},
    "class_weight": 2,
    "expansion_boost": 1,
    "guaranteed_rare_plus_picks": [1, 10, 20, 30],
    "regular_bucket": ["COMMON", "FREE"],
    "rare_plus_bucket": ["RARE", "EPIC", "LEGENDARY"],
    "duplicates_across_rounds": True,
    "offer_size": 3,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _download(url: str, expected: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    actual = _sha256(data)
    if actual != expected:
        raise RuntimeError(f"checksum mismatch for {url}: {actual} != {expected}")
    return data


def _tag_map(entity: ET.Element) -> dict[str, str]:
    return {
        tag.attrib["name"]: tag.attrib.get("value", "")
        for tag in entity.findall("Tag")
        if "name" in tag.attrib
    }


def _card_name(entity: ET.Element) -> str:
    tag = next((tag for tag in entity.findall("Tag") if tag.attrib.get("name") == "CARDNAME"), None)
    if tag is None:
        return entity.attrib.get("CardID", "")
    return (tag.findtext("enUS") or tag.findtext("enGB") or " ".join(tag.itertext())).strip()


def _validate_scores(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, list):
        raise ValueError("cardtier source must be a JSON list")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(raw):
        if not isinstance(row, dict) or set(row) != {"id", "name", "value"}:
            raise ValueError(f"invalid score row at index {index}")
        card_id = row["id"]
        values = row["value"]
        if not isinstance(card_id, str) or not card_id or card_id in seen:
            raise ValueError(f"duplicate or invalid score card ID at index {index}")
        if not isinstance(values, list) or len(values) != 9:
            raise ValueError(f"score row {card_id} must have exactly nine cells")
        for cell in values:
            if not isinstance(cell, str):
                raise ValueError(f"score cell {card_id} is not a string")
            if not cell:
                continue
            marker = cell[:-1] if cell.endswith("*") else cell
            if marker.startswith(">"):
                marker = marker[1:]
            try:
                value = float(marker)
            except ValueError as exc:
                raise ValueError(f"invalid score cell {card_id}: {cell!r}") from exc
            if not math.isfinite(value):
                raise ValueError(f"non-finite score cell {card_id}: {cell!r}")
        seen.add(card_id)
        rows.append({"id": card_id, "name": row["name"], "value": list(values)})
    return tuple(rows)


def _derived_cards(scores: tuple[dict[str, Any], ...], root: ET.Element) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    entities = {
        entity.attrib.get("CardID", ""): entity
        for entity in root.findall("Entity")
        if entity.attrib.get("CardID")
    }
    metadata: dict[str, dict[str, Any]] = {}
    for entity in entities.values():
        tags = _tag_map(entity)
        card_id = entity.attrib.get("CardID", "")
        if tags.get("COLLECTIBLE") != "1" or tags.get("CARDTYPE") not in TYPE_BY_XML:
            continue
        card_class = CLASS_BY_XML.get(tags.get("CLASS", ""))
        card_set = SET_BY_XML.get(tags.get("CARD_SET", ""))
        if card_class is None or card_set is None or not entity.attrib.get("ID"):
            continue
        metadata[card_id] = {
            "id": card_id,
            "name": _card_name(entity),
            "dbf_id": int(entity.attrib["ID"]),
            "card_class": card_class,
            "card_set": card_set,
            "card_type": TYPE_BY_XML[tags["CARDTYPE"]],
            "rarity": RARITY_BY_XML.get(tags.get("RARITY", ""), "INVALID"),
            "cost": int(tags.get("COST", "0") or 0),
        }

    score_ids = {row["id"] for row in scores}
    missing = sorted(score_ids - set(metadata))
    if missing:
        raise ValueError("score rows missing CardDefs metadata: " + ", ".join(missing[:5]))
    # The four all-blank source rows are explicitly outside the candidate
    # boundary.  The 19 policy exclusions remain in this 918-card candidate
    # set so that their exclusion is represented by rationale metadata rather
    # than silently inferred from an empty score.
    candidates = [metadata[row["id"]] for row in scores if row["id"] not in UNRATED_SOURCE_ROWS]
    if len(candidates) != 918:
        raise ValueError(f"expected 918 scored candidates, got {len(candidates)}")
    return sorted(candidates, key=lambda card: card["id"]), metadata


def _exclusions() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for card_id in CTHUN_EXCLUSIONS:
        result.append(
            {
                "id": card_id,
                "category": "cthun_synergy",
                "rationale": "Explicitly excluded from the reconstructed 2016 Arena legal pool as a C'Thun-related card.",
                "source": "approved project reconstruction policy; Blizzard Hearthside Arena-change announcement",
                "source_url": "https://hearthstone.blizzard.com/en-gb/news/20271286/hearthside-chat-upcoming-arena-changes-with-dean-ayala",
                "confidence": "reconstructed",
            }
        )
    # Keep this entry separate and explicit.  The exact date-specific ban
    # evidence for Beckoner of Evil was not recovered.
    result[6]["rationale"] = (
        "Explicitly excluded as a C'Thun-related card; precise date-specific ban evidence is uncertain."
    )
    result[6]["confidence"] = "uncertain"
    result.append(
        {
            "id": "KAR_013",
            "category": "known_arena_ban",
            "rationale": "Purify is explicitly excluded from the reconstructed legal pool.",
            "source": "approved project reconstruction policy; Blizzard Hearthside Arena-change announcement",
            "source_url": "https://hearthstone.blizzard.com/en-gb/news/20271286/hearthside-chat-upcoming-arena-changes-with-dean-ayala",
            "confidence": "reconstructed",
        }
    )
    return result


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def import_bundle(output: Path, *, ratings_bytes: bytes | None = None, carddefs_bytes: bytes | None = None) -> dict[str, Any]:
    """Fetch and generate one deterministic bundle, returning its manifest."""

    ratings_bytes = _download(RATINGS_URL, RATINGS_SHA256) if ratings_bytes is None else ratings_bytes
    carddefs_bytes = _download(CARDDEFS_URL, CARDDEFS_SHA256) if carddefs_bytes is None else carddefs_bytes
    if _sha256(ratings_bytes) != RATINGS_SHA256 or _sha256(carddefs_bytes) != CARDDEFS_SHA256:
        raise RuntimeError("provided source bytes do not match pinned checksums")

    scores = _validate_scores(json.loads(ratings_bytes.decode("utf-8")))
    root = ET.fromstring(carddefs_bytes)
    candidates, metadata = _derived_cards(scores, root)
    exclusions = _exclusions()
    excluded_ids = {entry["id"] for entry in exclusions}
    candidate_ids = {card["id"] for card in candidates}
    if not excluded_ids <= candidate_ids:
        raise ValueError("policy exclusion is missing from scored candidate rows")
    legal = [card for card in candidates if card["id"] not in excluded_ids]
    if len(legal) != 899:
        raise ValueError(f"expected 899 legal cards, got {len(legal)}")

    policy = {
        "format_id": FORMAT_ID,
        "fixed_sets": list(FIXED_SETS),
        "score_columns": list(SCORE_COLUMNS),
        "excluded_ids": list(POLICY_EXCLUSIONS),
        "unrated_source_rows": list(UNRATED_SOURCE_ROWS),
        "offer_policy": OFFER_POLICY,
    }
    policy_sha256 = _sha256(_canonical(OFFER_POLICY))
    pool = {
        "schema_version": 1,
        "cards": legal,
        "exclusions": exclusions,
        "candidate_count": len(candidates),
        "legal_pool_count": len(legal),
        "unrated_source_rows": list(UNRATED_SOURCE_ROWS),
    }
    pool_payload = _canonical(pool) + b"\n"
    policy_payload = _canonical(OFFER_POLICY) + b"\n"
    _write(output / "cardtier.raw.json", ratings_bytes)
    _write(output / "pool.json", pool_payload)
    _write(output / "offer_policy.json", policy_payload)
    manifest = {
        "schema_version": 1,
        "format_id": FORMAT_ID,
        "as_of": "2016-09-02",
        "fixed_sets": list(FIXED_SETS),
        "score_columns": list(SCORE_COLUMNS),
        "ratings": {
            "file": "cardtier.raw.json",
            "url": RATINGS_URL,
            "sha256": RATINGS_SHA256,
            "rows": len(scores),
        },
        "carddefs": {
            "url": CARDDEFS_URL,
            "sha256": CARDDEFS_SHA256,
            "build": root.attrib.get("build"),
            "import_only": True,
        },
        "candidate_count": len(candidates),
        "legal_pool_count": len(legal),
        "pool_file": "pool.json",
        "pool_sha256": _sha256(pool_payload),
        "policy_file": "offer_policy.json",
        "policy_sha256": policy_sha256,
        "unrated_source_rows": list(UNRATED_SOURCE_ROWS),
        "offer_policy": OFFER_POLICY,
    }
    provenance_payload = _canonical(manifest) + b"\n"
    _write(output / "provenance.json", provenance_payload)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "fireplace" / "arena" / "data" / FORMAT_ID,
        help="target data directory (default: fireplace/arena/data/wild_2016_09_02)",
    )
    args = parser.parse_args()
    manifest = import_bundle(args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
