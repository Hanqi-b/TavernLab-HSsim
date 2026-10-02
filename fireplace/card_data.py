"""Shared, metadata-only loading for the bundled card definitions.

The repository's original ``CardDefs.xml`` remains the base data source.  A
small XML overlay carries the complete Scholomance Academy launch data from
the historical hs-data build 54613.  This module owns the merge so the game
database and the read-only web catalog observe the same records without
importing any card-script modules.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from hearthstone import cardxml


_PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_CARD_DEFS_PATH = _PACKAGE_ROOT / "cards" / "CardDefs.xml"
SCHOLOMANCE_CARD_DEFS_PATH = _PACKAGE_ROOT / "cards" / "Scholomance.xml"

# The overlay is extracted from this immutable hs-data revision.  Keep these
# values here as machine-readable provenance in addition to the human-facing
# extraction notes in docs/scholomance-data.md.
SCHOLOMANCE_SOURCE_BUILD = 54613
SCHOLOMANCE_SOURCE_VERSION = "18.0.0.54613"
SCHOLOMANCE_SOURCE_COMMIT = "9b95dea77dbb4d116e861df8b650d80b1b4385d1"
SCHOLOMANCE_SOURCE_URL = (
    "https://raw.githubusercontent.com/HearthSim/hsdata/"
    f"{SCHOLOMANCE_SOURCE_COMMIT}/CardDefs.xml"
)
# SHA-256 of the pinned upstream CardDefs.xml before the SCH-only extraction.
SCHOLOMANCE_SOURCE_FILE_SHA256 = (
    "e04e474fab17364e4ec39fb89e04de50d0d90938b01e6713db2b12bfe842d86c"
)
# SHA-256 of the checked-in SCH-only overlay generated from that source.
SCHOLOMANCE_SOURCE_SHA256 = (
    "28de307a73b208fd0a58fffcb021748978a9930b75e366248f57826b739f9998"
)
# ``*_CHECKSUM`` is a convenient spelling for callers that do not need to
# distinguish the digest algorithm from the value.
SCHOLOMANCE_SOURCE_CHECKSUM = SCHOLOMANCE_SOURCE_SHA256
SCHOLOMANCE_RECORD_COUNT = 259
SCHOLOMANCE_COLLECTIBLE_COUNT = 135

_BUILD_RE = re.compile(rb"<CardDefs\b[^>]*\bbuild=\"([^\"]+)\"")


@dataclass(frozen=True, slots=True)
class CardDataProvenance:
    """Sources and verification data for one loaded card registry."""

    locale: str
    base_path: Path
    base_build: str | None
    base_sha256: str
    overlay_path: Path | None
    overlay_build: str | None
    overlay_sha256: str | None
    source_sha256: str | None
    source_version: str | None
    source_commit: str | None
    source_url: str | None
    overlay_records: int
    overlay_collectible: int

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-safe provenance for diagnostics and reports."""

        value = asdict(self)
        value["base_path"] = str(self.base_path)
        value["overlay_path"] = (
            str(self.overlay_path) if self.overlay_path is not None else None
        )
        return value


@lru_cache(maxsize=None)
def _file_metadata(path: str) -> tuple[str | None, str]:
    """Read the XML build attribute and SHA-256 for one immutable file."""

    source = Path(path)
    digest = hashlib.sha256()
    prefix = b""
    with source.open("rb") as stream:
        prefix = stream.read(4096)
        digest.update(prefix)
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    match = _BUILD_RE.search(prefix)
    build = match.group(1).decode("ascii") if match is not None else None
    return build, digest.hexdigest()


def _load_xml(path: Path, locale: str) -> dict[str, cardxml.CardXML]:
    loaded, _ = cardxml.load(path=path, locale=locale)
    return loaded


def _overlay_counts(overlay: dict[str, cardxml.CardXML]) -> tuple[int, int]:
    """Validate the overlay boundary and return total/collectible counts."""

    invalid = [card_id for card_id in overlay if not card_id.startswith("SCH_")]
    if invalid:
        raise ValueError(
            "Scholomance overlay contains non-SCH records: "
            + ", ".join(sorted(invalid)[:5])
        )
    collectible = sum(bool(card.collectible) for card in overlay.values())
    return len(overlay), collectible


def load_card_data(
    locale: str = "enUS",
    *,
    source_path: Path | str | None = None,
    include_scholomance: bool | None = None,
) -> tuple[dict[str, cardxml.CardXML], CardDataProvenance]:
    """Load card XML and optionally merge the launch-era Scholomance overlay.

    ``source_path=None`` selects the bundled base plus Scholomance overlay.
    Passing an explicit path always loads exactly that XML file unless the
    caller explicitly requests the overlay; combining an explicit custom
    source with the bundled overlay is rejected so catalog fixtures cannot
    accidentally inherit production data.
    """

    custom_source = source_path is not None
    if include_scholomance is None:
        include_scholomance = not custom_source
    if custom_source and include_scholomance:
        raise ValueError(
            "custom card-data sources must be isolated from the Scholomance overlay"
        )

    base_path = Path(source_path) if custom_source else DEFAULT_CARD_DEFS_PATH
    base_build, base_sha256 = _file_metadata(str(base_path))
    cards = dict(_load_xml(base_path, locale))

    overlay_path: Path | None = None
    overlay_build: str | None = None
    overlay_sha256: str | None = None
    source_version: str | None = None
    source_commit: str | None = None
    source_url: str | None = None
    overlay_records = 0
    overlay_collectible = 0

    if include_scholomance:
        overlay_path = SCHOLOMANCE_CARD_DEFS_PATH
        overlay_build, overlay_sha256 = _file_metadata(str(overlay_path))
        overlay = _load_xml(overlay_path, locale)
        overlay_records, overlay_collectible = _overlay_counts(overlay)
        if overlay_build != str(SCHOLOMANCE_SOURCE_BUILD):
            raise ValueError(
                "unexpected Scholomance overlay build: "
                f"{overlay_build!r} (expected {SCHOLOMANCE_SOURCE_BUILD})"
            )
        if overlay_sha256 != SCHOLOMANCE_SOURCE_SHA256:
            raise ValueError(
                "unexpected Scholomance overlay checksum: "
                f"{overlay_sha256!r} (expected {SCHOLOMANCE_SOURCE_SHA256})"
            )
        if overlay_records != SCHOLOMANCE_RECORD_COUNT:
            raise ValueError(
                "unexpected Scholomance overlay record count: "
                f"{overlay_records} (expected {SCHOLOMANCE_RECORD_COUNT})"
            )
        if overlay_collectible != SCHOLOMANCE_COLLECTIBLE_COUNT:
            raise ValueError(
                "unexpected Scholomance collectible count: "
                f"{overlay_collectible} (expected {SCHOLOMANCE_COLLECTIBLE_COUNT})"
            )
        cards.update(overlay)
        source_version = SCHOLOMANCE_SOURCE_VERSION
        source_commit = SCHOLOMANCE_SOURCE_COMMIT
        source_url = SCHOLOMANCE_SOURCE_URL

    provenance = CardDataProvenance(
        locale=locale,
        base_path=base_path,
        base_build=base_build,
        base_sha256=base_sha256,
        overlay_path=overlay_path,
        overlay_build=overlay_build,
        overlay_sha256=overlay_sha256,
        source_sha256=(
            SCHOLOMANCE_SOURCE_FILE_SHA256 if include_scholomance else None
        ),
        source_version=source_version,
        source_commit=source_commit,
        source_url=source_url,
        overlay_records=overlay_records,
        overlay_collectible=overlay_collectible,
    )
    return cards, provenance


__all__ = [
    "CardDataProvenance",
    "DEFAULT_CARD_DEFS_PATH",
    "SCHOLOMANCE_CARD_DEFS_PATH",
    "SCHOLOMANCE_COLLECTIBLE_COUNT",
    "SCHOLOMANCE_RECORD_COUNT",
    "SCHOLOMANCE_SOURCE_BUILD",
    "SCHOLOMANCE_SOURCE_CHECKSUM",
    "SCHOLOMANCE_SOURCE_COMMIT",
    "SCHOLOMANCE_SOURCE_FILE_SHA256",
    "SCHOLOMANCE_SOURCE_SHA256",
    "SCHOLOMANCE_SOURCE_URL",
    "SCHOLOMANCE_SOURCE_VERSION",
    "load_card_data",
]
