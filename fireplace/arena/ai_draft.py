"""Deterministic opponent draft for the reconstructed historical Arena mode."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from .formats import (
    HERO_CLASSES,
    WILD_2016_09_02_FORMAT_ID,
    historical_draft_rng,
    historical_profile,
)
from .draft import historical_card_offer
from .pool import historical_eligible_cards
from .ratings import get_rating, parse_score_cell


PICK_COUNT = 30
OFFER_SIZE = 3
REQUIRED_FINGERPRINTS = frozenset(
    ("manifest_sha256", "ratings_sha256", "carddefs_sha256", "policy_sha256", "score_fingerprint")
)


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _finite_number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return value


def _profile_shape(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("data_profile must be a non-empty object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        copied = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("data_profile must be JSON-safe") from exc
    if not isinstance(copied, dict):
        raise ValueError("data_profile must be a JSON object")
    return copied


def _trace_entry(value: object, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"AI draft trace entry {index} must be an object")
    pick_number = value.get("pick_number")
    if type(pick_number) is not int or pick_number != index:
        raise ValueError(f"AI draft trace entry {index} has an invalid pick number")
    offer_ids = value.get("offer_ids")
    offer = value.get("offer")
    if not isinstance(offer_ids, list) or len(offer_ids) != OFFER_SIZE:
        raise ValueError(f"AI draft trace entry {index} must contain three offer IDs")
    if any(not isinstance(card_id, str) or not card_id for card_id in offer_ids):
        raise ValueError(f"AI draft trace entry {index} has an invalid offer ID")
    if len(set(offer_ids)) != OFFER_SIZE:
        raise ValueError(f"AI draft trace entry {index} offer IDs must be distinct")
    if not isinstance(offer, list) or len(offer) != OFFER_SIZE:
        raise ValueError(f"AI draft trace entry {index} must contain three score records")
    seen: set[str] = set()
    for score in offer:
        if not isinstance(score, dict):
            raise ValueError(f"AI draft trace entry {index} score record is invalid")
        card_id = score.get("id")
        if not isinstance(card_id, str) or card_id not in offer_ids or card_id in seen:
            raise ValueError(f"AI draft trace entry {index} score IDs do not match offer IDs")
        seen.add(card_id)
        raw = score.get("raw")
        if "raw_score" in score and score.get("raw_score") != raw:
            raise ValueError(f"AI draft trace entry {index} raw score aliases disagree")
        if not isinstance(raw, str) or not raw:
            raise ValueError(f"AI draft trace entry {index} has an invalid raw score")
        parsed = parse_score_cell(raw, card_id, "trace")
        numeric = _finite_number(score.get("numeric"), f"AI draft trace entry {index} numeric score")
        if "numeric_score" in score and score.get("numeric_score") != numeric:
            raise ValueError(f"AI draft trace entry {index} numeric score aliases disagree")
        if numeric != parsed.numeric:
            raise ValueError(f"AI draft trace entry {index} numeric score disagrees with raw score")
        if type(score.get("starred")) is not bool or type(score.get("over_100")) is not bool:
            raise ValueError(f"AI draft trace entry {index} score flags are invalid")
        if score["starred"] != parsed.starred or score["over_100"] != parsed.over_100:
            raise ValueError(f"AI draft trace entry {index} score flags disagree with raw score")
        flags = score.get("flags")
        if not isinstance(flags, dict) or flags.get("starred") != score["starred"] or flags.get("over_100") != score["over_100"]:
            raise ValueError(f"AI draft trace entry {index} score flags disagree")
        if "marker_flags" in score and score.get("marker_flags") != flags:
            raise ValueError(f"AI draft trace entry {index} marker flag aliases disagree")
    selected = value.get("selected")
    if not isinstance(selected, str) or selected not in offer_ids:
        raise ValueError(f"AI draft trace entry {index} selected ID is not offered")
    if value.get("selected_id", selected) != selected:
        raise ValueError(f"AI draft trace entry {index} selected ID aliases disagree")
    header = value.get("header")
    if not isinstance(header, dict) or header.get("format_id") != WILD_2016_09_02_FORMAT_ID:
        raise ValueError(f"AI draft trace entry {index} header is invalid")
    fingerprints = header.get("fingerprints")
    if not isinstance(fingerprints, dict) or not REQUIRED_FINGERPRINTS <= set(fingerprints):
        raise ValueError(f"AI draft trace entry {index} header fingerprints are missing")
    if any(not isinstance(key, str) or not isinstance(item, str) or not item for key, item in fingerprints.items()):
        raise ValueError(f"AI draft trace entry {index} header fingerprints are invalid")
    # Validate the supplied shape but keep unknown header fields for forward
    # compatible archived traces.
    return copy.deepcopy(value)


@dataclass
class AIDraft:
    """A replayable 30-pick historical AI draft.

    ``from_dict`` validates only persisted shape and finite values.  It does
    not load the historical files, which lets an archived match resume even
    when the optional historical data bundle is unavailable.
    """

    hero_id: str
    deck: list[str]
    trace: list[dict[str, Any]]
    data_profile: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.hero_id = _require_string(self.hero_id, "hero_id")
        if self.hero_id not in HERO_CLASSES:
            raise ValueError(f"unknown AI Arena hero: {self.hero_id!r}")
        if not isinstance(self.deck, list) or len(self.deck) != PICK_COUNT:
            raise ValueError("AI Arena deck must contain exactly 30 cards")
        if any(not isinstance(card_id, str) or not card_id for card_id in self.deck):
            raise ValueError("AI Arena deck IDs must be non-empty strings")
        if not isinstance(self.trace, list) or len(self.trace) != PICK_COUNT:
            raise ValueError("AI Arena trace must contain exactly 30 rounds")
        self.data_profile = _profile_shape(self.data_profile)
        self.trace = [_trace_entry(entry, index) for index, entry in enumerate(self.trace, 1)]
        selected = [entry["selected"] for entry in self.trace]
        if selected != self.deck:
            raise ValueError("AI Arena deck does not match trace selections")
        expected_seed: int | None = None
        for index, entry in enumerate(self.trace, 1):
            header = entry["header"]
            if header.get("hero_id") != self.hero_id:
                raise ValueError(f"AI draft trace entry {index} hero does not match draft hero")
            seed = header.get("seed")
            if type(seed) is not int:
                raise ValueError(f"AI draft trace entry {index} seed is invalid")
            if expected_seed is None:
                expected_seed = seed
            elif seed != expected_seed:
                raise ValueError("AI draft trace seeds are inconsistent")
            fingerprints = header["fingerprints"]
            for key, fingerprint in fingerprints.items():
                if key not in self.data_profile or str(self.data_profile[key]) != fingerprint:
                    raise ValueError(f"AI draft trace entry {index} fingerprint disagrees with data profile")
            ranking = sorted(
                ((item["numeric"], item["id"]) for item in entry["offer"]),
                key=lambda item: (-item[0], item[1]),
            )
            if entry["selected"] != ranking[0][1]:
                raise ValueError(f"AI draft trace entry {index} does not select the maximum score")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hero_id": self.hero_id,
            "deck": list(self.deck),
            "trace": copy.deepcopy(self.trace),
            "data_profile": copy.deepcopy(self.data_profile),
        }

    @classmethod
    def from_dict(cls, value: object) -> "AIDraft":
        if not isinstance(value, dict):
            raise ValueError("AI draft must be an object")
        required = {"hero_id", "deck", "trace", "data_profile"}
        if set(value) != required:
            raise ValueError("AI draft has an unsupported shape")
        # Construction performs all structural checks and intentionally does
        # not call historical_profile(), score_for(), or any data loader.
        return cls(
            hero_id=value["hero_id"],
            deck=copy.deepcopy(value["deck"]),
            trace=copy.deepcopy(value["trace"]),
            data_profile=copy.deepcopy(value["data_profile"]),
        )


def draft_ai(seed: int, human_hero_id: str) -> AIDraft:
    """Draft 30 cards for a deterministic hero different from the human."""

    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if not isinstance(human_hero_id, str) or human_hero_id not in HERO_CLASSES:
        raise ValueError(f"unknown Arena human hero: {human_hero_id!r}")
    profile = historical_profile()
    hero_rng = historical_draft_rng(seed, 0, purpose="ai-hero")
    candidates = tuple(hero_id for hero_id in HERO_CLASSES if hero_id != human_hero_id)
    ai_hero_id = hero_rng.choice(candidates)
    pool = historical_eligible_cards(ai_hero_id)
    ai_class = HERO_CLASSES[ai_hero_id]
    trace: list[dict[str, Any]] = []
    deck: list[str] = []
    header_fingerprints = {
        key: str(profile[key])
        for key in (
            "manifest_sha256",
            "ratings_sha256",
            "carddefs_sha256",
            "policy_sha256",
            "score_fingerprint",
        )
        if key in profile
    }
    for pick_number in range(1, PICK_COUNT + 1):
        rng = historical_draft_rng(seed, pick_number, purpose="ai-offer")
        offer_ids = historical_card_offer(rng, pool, pick_number)
        scores: list[dict[str, Any]] = []
        for card_id in offer_ids:
            score = get_rating(card_id, ai_class)
            scores.append(
                {
                    "id": card_id,
                    "raw": score.raw,
                    "raw_score": score.raw,
                    "numeric": score.numeric,
                    "numeric_score": score.numeric,
                    "starred": score.starred,
                    "over_100": score.over_100,
                    "flags": score.flags,
                    "marker_flags": score.flags,
                }
            )
        selected_score = sorted(scores, key=lambda item: (-item["numeric"], item["id"]))[0]
        selected = str(selected_score["id"])
        deck.append(selected)
        trace.append(
            {
                "pick_number": pick_number,
                "offer_ids": list(offer_ids),
                "offer": scores,
                "selected": selected,
                "selected_id": selected,
                "header": {
                    "format_id": WILD_2016_09_02_FORMAT_ID,
                    "seed": seed,
                    "hero_id": ai_hero_id,
                    "fingerprints": dict(header_fingerprints),
                },
            }
        )
    return AIDraft(hero_id=ai_hero_id, deck=deck, trace=trace, data_profile=profile)


__all__ = ["AIDraft", "OFFER_SIZE", "PICK_COUNT", "draft_ai"]
