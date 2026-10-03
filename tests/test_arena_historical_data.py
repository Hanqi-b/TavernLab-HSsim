"""Regression tests for the pinned 2016 Arena data and draft policy."""

from __future__ import annotations

import copy
import hashlib
import json
import random

import pytest

from fireplace import cards
from fireplace.arena import formats, ratings
from fireplace.arena import ai_draft
from fireplace.arena import draft as arena_draft
from fireplace.arena import pool as arena_pool
from fireplace.arena.run import ArenaRun


EXPECTED_EXCLUSIONS = (
    "OG_096",
    "OG_131",
    "OG_162",
    "OG_188",
    "OG_255",
    "OG_280",
    "OG_281",
    "OG_282",
    "OG_283",
    "OG_284",
    "OG_286",
    "OG_293",
    "OG_301",
    "OG_302",
    "OG_303",
    "OG_321",
    "OG_334",
    "OG_339",
    "KAR_013",
)


@pytest.fixture(scope="module")
def seeded_real_ai_draft():
    return ai_draft.draft_ai(1729, "HERO_01")


def test_raw_ratings_preserve_nine_source_cells_and_class_specific_scores():
    rows = ratings.load_ratings()
    assert len(rows) == 922
    assert all(len(row.values) == 9 for row in rows.values())
    assert ratings.validate_ratings()["rows"] == 922

    # These values are representative source rows, including a score above
    # 100 and different scores for the same neutral card in different classes.
    assert ratings.get_rating("CS2_106", "WARRIOR").raw == "100"
    assert ratings.get_rating("CS2_106", "WARRIOR").numeric == 100
    assert ratings.get_rating("KAR_076", "MAGE").numeric == 84
    assert ratings.get_rating("CS2_029", "MAGE").numeric == 80
    assert ratings.get_rating("GVG_110", "WARRIOR").numeric == 130
    assert ratings.get_rating("GVG_110", "WARLOCK").numeric == 124
    assert ratings.get_rating("GVG_110", "PRIEST").numeric == 134

    mind_control = ratings.get_rating("CS1_113", "PRIEST")
    assert (mind_control.raw, mind_control.numeric, mind_control.starred) == (
        "64*",
        64,
        True,
    )
    assert ratings.get_rating("GVG_110", "WARRIOR").over_100 is True

    marked = ratings._parse_cell(">100*", "SYNTHETIC", "MAGE")
    assert marked.to_dict() == {
        "raw": ">100*",
        "numeric": 100,
        "starred": True,
        "over_100": True,
    }


def test_missing_rating_id_and_blank_class_cell_are_explicit_errors():
    with pytest.raises(ratings.MissingHistoricalScore, match="NO_SUCH_CARD/MAGE") as missing:
        ratings.get_rating("NO_SUCH_CARD", "HERO_08")
    assert (missing.value.card_id, missing.value.hero_class) == (
        "NO_SUCH_CARD",
        "MAGE",
    )

    # Fiery War Axe was only rated for Warrior in the source.
    assert ratings.load_ratings()["CS2_106"].raw_for("MAGE") == ""
    with pytest.raises(ratings.MissingHistoricalScore, match="CS2_106/MAGE") as blank:
        ratings.get_rating("CS2_106", "MAGE")
    assert (blank.value.card_id, blank.value.hero_class) == ("CS2_106", "MAGE")


def test_malformed_nonblank_score_cells_fail_strict_source_parsing():
    payload = [
        {
            "id": "BROKEN_SCORE",
            "name": "Broken score",
            "value": ["not-a-score", "", "", "", "", "", "", "", ""],
        }
    ]
    with pytest.raises(ratings.HistoricalRatingsError, match="invalid historical Arena score"):
        ratings._parse_payload(payload)


def test_historical_manifest_and_legal_pool_are_pinned_and_keep_hof_cards():
    profile = formats.historical_profile()
    config = formats.get_format(formats.WILD_2016_09_02_FORMAT_ID)
    assert config.id == formats.WILD_2016_09_02_FORMAT_ID
    assert config.fixed_sets == (
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
    assert config.max_wins == 12
    assert config.max_losses == 3
    assert profile["fixed_sets"] == list(config.fixed_sets)
    assert profile["candidate_count"] == 918
    assert profile["legal_pool_count"] == 899
    assert profile["ratings_sha256"] == "9a832ddff0bbdcb46612ced24948542d29f01feb6148f20d5d0c3feca7b1b447"
    assert profile["pool_sha256"] == "2c318c6288d45c2b0487156907ce5e997a28cc22b9ea6e8e8183a7a04f6b47a6"
    assert profile["policy_sha256"] == "25d5b8a532b276d07382b4e3ab7f3ab6f56b38eb3da1753ae6a2553e38dc59fa"
    assert set(config.profile_hashes) == {
        "manifest_sha256",
        "ratings_sha256",
        "carddefs_sha256",
        "pool_sha256",
        "policy_sha256",
        "score_fingerprint",
    }
    assert all(config.profile_hashes[key] == profile[key] for key in config.profile_hashes)

    # Current card data classifies Azure Drake and Sylvanas as Hall of Fame.
    # The pinned historical bundle retains their 2016 EXPERT1 set identity.
    cards.db.initialize()
    assert cards.db["EX1_284"].card_set.name == "HOF"
    assert cards.db["EX1_016"].card_set.name == "HOF"
    mage_pool = {card.id: card for card in arena_pool.historical_eligible_cards("HERO_08")}
    assert mage_pool["EX1_284"].card_set == "EXPERT1"
    warrior_pool = {card.id: card for card in arena_pool.historical_eligible_cards("HERO_01")}
    assert warrior_pool["EX1_016"].card_set == "EXPERT1"


def test_historical_exclusion_boundary_is_explicit_not_inferred_from_blank_rows():
    profile = formats.historical_profile()
    payload = json.loads(formats.POOL_PATH.read_text(encoding="utf-8"))
    legal_ids = {card["id"] for card in payload["cards"]}
    exclusion_ids = tuple(item["id"] for item in payload["exclusions"])

    assert len(formats.EXCLUDED_IDS) == 19
    assert formats.EXCLUDED_IDS == EXPECTED_EXCLUSIONS
    assert exclusion_ids == EXPECTED_EXCLUSIONS
    assert not set(EXPECTED_EXCLUSIONS) & legal_ids
    assert "OG_280" not in legal_ids  # C'Thun
    assert "KAR_013" not in legal_ids  # Purify

    unrated = ("EX1_062", "EX1_112", "NEW1_016", "PRO_001")
    assert formats.UNRATED_SOURCE_ROWS == unrated
    raw_ids = set(ratings.load_ratings())
    assert set(unrated).isdisjoint(EXPECTED_EXCLUSIONS)
    assert len(raw_ids - set(unrated)) == profile["candidate_count"]
    assert len((raw_ids - set(unrated)) - set(EXPECTED_EXCLUSIONS)) == profile["legal_pool_count"]


@pytest.mark.parametrize("source_name", ("RATINGS_PATH", "POOL_PATH", "OFFER_POLICY_PATH"))
def test_corrupt_pinned_data_fails_preflight_without_fallback(
    source_name: str, tmp_path, monkeypatch
):
    source_path = getattr(formats, source_name)
    corrupted_path = tmp_path / source_path.name
    if source_name == "OFFER_POLICY_PATH":
        policy = json.loads(source_path.read_text(encoding="utf-8"))
        policy["class_weight"] += 1
        corrupted_path.write_text(json.dumps(policy), encoding="utf-8")
    else:
        corrupted_path.write_bytes(source_path.read_bytes() + b"\n")
    monkeypatch.setattr(formats, source_name, corrupted_path)

    if source_name == "RATINGS_PATH":
        monkeypatch.setattr(ratings, "RATINGS_PATH", corrupted_path)
        ratings._load_cached.cache_clear()
        expected_error = ratings.HistoricalRatingsError
    else:
        expected_error = formats.HistoricalFormatError

    try:
        with pytest.raises(expected_error, match="checksum|checksum metadata|fingerprint|policy"):
            formats.historical_profile()
    finally:
        ratings._load_cached.cache_clear()


def test_co_tampered_manifest_pool_and_policy_fail_the_frozen_profile_guard(
    tmp_path, monkeypatch
):
    manifest = json.loads(formats.PROVENANCE_PATH.read_text(encoding="utf-8"))
    pool = json.loads(formats.POOL_PATH.read_text(encoding="utf-8"))
    policy = json.loads(formats.OFFER_POLICY_PATH.read_text(encoding="utf-8"))

    pool["cards"][0]["name"] += " changed"
    policy["class_weight"] += 1

    def canonical_bytes(value):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    pool_bytes = canonical_bytes(pool)
    policy_bytes = canonical_bytes(policy)
    manifest["pool_sha256"] = hashlib.sha256(pool_bytes).hexdigest()
    manifest["policy_sha256"] = hashlib.sha256(policy_bytes).hexdigest()
    manifest_bytes = canonical_bytes(manifest)

    paths = {
        "PROVENANCE_PATH": tmp_path / "provenance.json",
        "POOL_PATH": tmp_path / "pool.json",
        "OFFER_POLICY_PATH": tmp_path / "offer_policy.json",
    }
    paths["PROVENANCE_PATH"].write_bytes(manifest_bytes)
    paths["POOL_PATH"].write_bytes(pool_bytes)
    paths["OFFER_POLICY_PATH"].write_bytes(policy_bytes)
    for attribute, path in paths.items():
        monkeypatch.setattr(formats, attribute, path)

    with pytest.raises(formats.HistoricalFormatError, match="checksum|fingerprint|profile|policy"):
        formats.historical_profile()


def test_real_historical_pool_has_legal_cards_for_each_classic_hero():
    for hero_id, hero_class in formats.HERO_CLASSES.items():
        pool = arena_pool.historical_eligible_cards(hero_id)
        ids = [card.id for card in pool]
        assert pool
        assert ids == sorted(ids)
        assert len(ids) == len(set(ids))
        assert all(card.card_class in ("NEUTRAL", hero_class) for card in pool)
        assert all(card.dbf_id > 0 for card in pool)


def test_synthetic_offer_policy_guarantees_rare_plus_picks_and_ordinary_common_group():
    pool = tuple(
        {
            "id": f"{card_set}_{rarity}_{index}",
            "rarity": rarity,
            "card_class": "MAGE" if index % 2 == 0 else "NEUTRAL",
            "card_set": card_set,
        }
        for rarity, card_set in (
            ("COMMON", "BASIC"),
            ("COMMON", "EXPERT1"),
            ("COMMON", "BASIC"),
            ("RARE", "TGT"),
            ("EPIC", "OG"),
            ("LEGENDARY", "KARA"),
        )
        for index in range(3)
    )
    class LowestRng(random.Random):
        def random(self):
            return 0.0

    for pick_number in range(1, 31):
        offer = arena_draft.historical_card_offer(
            LowestRng(1000 + pick_number), pool, pick_number
        )
        assert len(offer) == 3
        assert len(set(offer)) == 3
        by_id = {card["id"]: card for card in pool}
        offered = [by_id[card_id] for card_id in offer]
        if pick_number in {1, 10, 20, 30}:
            assert all(card["rarity"] == "RARE" for card in offered)
        else:
            assert all(card["rarity"] in {"COMMON", "FREE"} for card in offered)
            assert all(card["card_set"] in {"BASIC", "EXPERT1"} for card in offered)


def test_custom_v1_run_still_works_when_historical_data_is_unavailable(monkeypatch):
    def unavailable():
        raise formats.HistoricalFormatError("historical bundle unavailable")

    monkeypatch.setattr(formats, "historical_profile", unavailable)
    sets = ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"]
    run = ArenaRun.create(sets, "Tester", "zhCN", seed=17)
    run.choose_hero(run.hero_choices[0])

    assert run.format_id == formats.CUSTOM_FORMAT_ID
    assert run.stage == "draft"
    assert len(run.choices) == 3
    assert run.to_dict()["version"] == 1


def test_real_ai_drafts_smoke_every_class_with_complete_class_scored_traces(monkeypatch):
    actual_rng = formats.historical_draft_rng
    observed_heroes = set()

    class FixedHeroRng:
        def __init__(self, hero_id):
            self.hero_id = hero_id

        def choice(self, candidates):
            assert self.hero_id in candidates
            return self.hero_id

    for ai_hero_id in formats.HERO_CLASSES:
        human_hero_id = "HERO_02" if ai_hero_id == "HERO_01" else "HERO_01"

        def controlled_rng(seed, pick_number, *, purpose="human"):
            if purpose == "ai-hero":
                return FixedHeroRng(ai_hero_id)
            return actual_rng(seed, pick_number, purpose=purpose)

        with monkeypatch.context() as hero_monkeypatch:
            hero_monkeypatch.setattr(ai_draft, "historical_draft_rng", controlled_rng)
            draft = ai_draft.draft_ai(1729, human_hero_id)

        assert draft.hero_id in formats.HERO_CLASSES
        assert draft.hero_id == ai_hero_id
        assert draft.hero_id != human_hero_id
        observed_heroes.add(draft.hero_id)
        assert len(draft.deck) == ai_draft.PICK_COUNT == 30
        assert len(draft.trace) == ai_draft.PICK_COUNT
        assert len(json.dumps(draft.to_dict())) > 0

        hero_class = formats.HERO_CLASSES[draft.hero_id]
        for index, entry in enumerate(draft.trace, start=1):
            assert entry["pick_number"] == index
            assert len(entry["offer_ids"]) == ai_draft.OFFER_SIZE == 3
            assert len(set(entry["offer_ids"])) == 3
            assert {score["id"] for score in entry["offer"]} == set(entry["offer_ids"])
            for score in entry["offer"]:
                expected = ratings.get_rating(score["id"], hero_class)
                assert score["raw"] == expected.raw
                assert score["numeric"] == expected.numeric
                assert score["starred"] is expected.starred
                assert score["over_100"] is expected.over_100
            expected_winner = min(
                entry["offer"], key=lambda score: (-score["numeric"], score["id"])
            )
            assert entry["selected"] == expected_winner["id"]
            assert entry["selected_id"] == expected_winner["id"]
            assert draft.deck[index - 1] == expected_winner["id"]
            assert entry["header"]["hero_id"] == draft.hero_id
            assert entry["header"]["seed"] == 1729
            assert entry["header"]["format_id"] == formats.WILD_2016_09_02_FORMAT_ID
            for key, fingerprint in entry["header"]["fingerprints"].items():
                assert fingerprint == str(draft.data_profile[key])

    assert observed_heroes == set(formats.HERO_CLASSES)


def test_ai_draft_seed_repeats_the_complete_trace(seeded_real_ai_draft):
    repeated = ai_draft.draft_ai(1729, "HERO_01")
    assert repeated.to_dict() == seeded_real_ai_draft.to_dict()


def test_ai_draft_ties_choose_lexical_id_without_random_selection(monkeypatch):
    profile = {
        "manifest_sha256": "manifest",
        "ratings_sha256": "ratings",
        "carddefs_sha256": "carddefs",
        "policy_sha256": "policy",
        "score_fingerprint": "scores",
    }

    class ChoiceOnlyRng:
        def __init__(self):
            self.choice_calls = 0

        def choice(self, values):
            self.choice_calls += 1
            assert "HERO_02" in values
            return "HERO_02"

        def random(self):
            raise AssertionError("AI selection must not use RNG to break score ties")

    rng = ChoiceOnlyRng()
    calls = {"offers": 0, "classes": []}
    monkeypatch.setattr(ai_draft, "historical_profile", lambda: profile)
    monkeypatch.setattr(ai_draft, "historical_draft_rng", lambda *_args, **_kwargs: rng)

    def fixed_offer(_rng, _pool, _pick_number):
        calls["offers"] += 1
        return ("Z_CARD", "A_CARD", "N_CARD")

    def tied_rating(card_id, hero_class):
        calls["classes"].append(hero_class)
        score = {"A_CARD": 120, "N_CARD": 10, "Z_CARD": 120}[card_id]
        return ratings.ScoreCell(str(score), score, over_100=score > 100)

    monkeypatch.setattr(ai_draft, "historical_card_offer", fixed_offer)
    monkeypatch.setattr(ai_draft, "get_rating", tied_rating)

    draft = ai_draft.draft_ai(11, "HERO_01")
    assert draft.hero_id == "HERO_02"
    assert calls["offers"] == 30
    assert calls["classes"] == ["SHAMAN"] * 90
    assert draft.deck == ["A_CARD"] * 30
    assert rng.choice_calls == 1


def test_missing_rating_propagates_without_rerolling_the_offer(monkeypatch):
    from fireplace.arena.ratings import MissingHistoricalScore

    calls: list[int] = []
    profile = formats.historical_profile()

    class HeroOnlyRng:
        def choice(self, _values):
            return "HERO_08"

    monkeypatch.setattr(ai_draft, "historical_profile", lambda: profile)
    monkeypatch.setattr(ai_draft, "historical_draft_rng", lambda *_args, **_kwargs: HeroOnlyRng())

    def first_offer_then_missing(_rng, _pool, pick_number):
        calls.append(pick_number)
        return ("MISSING_RATING_CARD", "CS2_029", "KAR_076")

    monkeypatch.setattr(ai_draft, "historical_card_offer", first_offer_then_missing)

    with pytest.raises(MissingHistoricalScore, match="MISSING_RATING_CARD/MAGE"):
        ai_draft.draft_ai(7, "HERO_01")
    assert calls == [1]


def test_saved_ai_draft_validates_without_loading_historical_scores(
    seeded_real_ai_draft, monkeypatch
):
    payload = seeded_real_ai_draft.to_dict()

    def unavailable(*_args, **_kwargs):
        raise AssertionError("saved draft validation must not load historical data")

    monkeypatch.setattr(ai_draft, "historical_profile", unavailable)
    monkeypatch.setattr(ai_draft, "historical_eligible_cards", unavailable)
    monkeypatch.setattr(ai_draft, "get_rating", unavailable)
    monkeypatch.setattr(ratings, "load_ratings", unavailable)
    monkeypatch.setattr(ratings, "_raw_bytes", unavailable)

    restored = ai_draft.AIDraft.from_dict(payload)
    assert restored.to_dict() == payload


@pytest.mark.parametrize(
    "tamper",
    ("deck", "selection", "numeric", "raw", "hero", "seed", "fingerprint"),
)
def test_saved_ai_draft_rejects_tampered_trace_and_header(
    seeded_real_ai_draft, tamper
):
    payload = copy.deepcopy(seeded_real_ai_draft.to_dict())
    first = payload["trace"][0]

    if tamper == "deck":
        payload["deck"][0] = "NOT_THE_TRACE_SELECTION"
    elif tamper == "selection":
        replacement = next(card_id for card_id in first["offer_ids"] if card_id != first["selected"])
        first["selected"] = replacement
        first["selected_id"] = replacement
        payload["deck"][0] = replacement
    elif tamper == "numeric":
        first["offer"][0]["numeric"] += 1
    elif tamper == "raw":
        first["offer"][0]["raw"] = "not-a-score"
    elif tamper == "hero":
        first["header"]["hero_id"] = "HERO_09" if payload["hero_id"] != "HERO_09" else "HERO_08"
    elif tamper == "seed":
        first["header"]["seed"] += 1
    else:
        first["header"]["fingerprints"]["ratings_sha256"] = "tampered"

    with pytest.raises(ValueError):
        ai_draft.AIDraft.from_dict(payload)
