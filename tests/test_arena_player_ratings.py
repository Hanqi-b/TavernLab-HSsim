"""Player ratings use the AI's class-specific source without changing drafts."""
import copy

import pytest

from fireplace.arena import ratings
from fireplace.arena.formats import HERO_CLASSES
from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore
from fireplace.web_gui.arena_service import ArenaService

WILD = "wild_2016_09_02"


def service_for(tmp_path, run):
    store = ArenaStore(tmp_path / "arena.json")
    store.save(run)
    return ArenaService(store=store)


def request(state, **values):
    return {"run_id": state["run_id"], "revision": state["revision"], **values}


@pytest.mark.parametrize("hero_id", HERO_CLASSES)
def test_all_player_offers_use_current_class_scores(tmp_path, hero_id):
    run = ArenaRun.create([], "Tester", "zhCN", seed=17, format_id=WILD)
    # Exercise each legal class, irrespective of this seed's hero offer.
    run.hero_choices = [hero_id]
    run.choose_hero(hero_id)
    service = service_for(tmp_path, run)
    try:
        for pick in range(30):
            before = copy.deepcopy(service.run.to_dict())
            state = service.state()
            assert service.run.to_dict() == before
            assert service.store.load().to_dict() == before
            assert state["rating_source"] == {
                "name": "Lightforge", "as_of": "2016-09-02",
                "card_class": HERO_CLASSES[hero_id],
            }
            assert len(state["card_offer"]) == 3
            for card in state["card_offer"]:
                assert card["arena_rating"] == {
                    **ratings.get_rating(card["id"], hero_id).to_dict(),
                    "source": "Lightforge", "as_of": "2016-09-02",
                    "card_class": HERO_CLASSES[hero_id],
                }
                # Catalog cards and the deck are never annotated in place.
                assert "arena_rating" not in service.catalog.get_card(card["id"], locale="zhCN")
            assert all("arena_rating" not in card for card in state["deck"])
            assert "ai_drafts" not in state
            # Players can choose any offer, including the lowest score.
            chosen = min(state["card_offer"], key=lambda c: c["arena_rating"]["numeric"])
            service.choose_card(request(state, card_id=chosen["id"]))
        assert service.state()["mode"] == "ready"
        assert "rating_source" not in service.state()
    finally:
        service.close()


def test_custom_draft_never_queries_historical_ratings(tmp_path, monkeypatch):
    from fireplace.arena.rules import LARGE_SETS, SMALL_SETS
    run = ArenaRun.create(list(LARGE_SETS[:4]) + list(SMALL_SETS[:2]), "Tester", "enUS", seed=17)
    run.choose_hero(run.hero_choices[0])
    service = service_for(tmp_path, run)
    try:
        def forbidden(*args):
            raise AssertionError("custom mode must not query historical ratings")
        monkeypatch.setattr(ratings, "get_rating", forbidden)
        before = run.to_dict()
        state = service.state()
        assert "rating_source" not in state
        assert all("arena_rating" not in card for card in state["card_offer"])
        assert service.run.to_dict() == before
    finally:
        service.close()


def test_missing_player_rating_reports_id_class_without_mutation(tmp_path, monkeypatch):
    run = ArenaRun.create([], "Tester", "zhCN", seed=17, format_id=WILD)
    run.choose_hero(run.hero_choices[0])
    service = service_for(tmp_path, run)
    try:
        before = copy.deepcopy(run.to_dict())
        def missing(card_id, hero_class):
            raise ratings.MissingHistoricalScore(card_id, hero_class)
        monkeypatch.setattr(ratings, "get_rating", missing)
        with pytest.raises(ratings.MissingHistoricalScore) as exc:
            service.state()
        assert exc.value.card_id == run.choices[0]
        assert exc.value.hero_class == HERO_CLASSES[run.hero_id]
        assert service.run.to_dict() == before
        assert service.store.load().to_dict() == before
    finally:
        service.close()


def test_non_draft_state_does_not_require_ratings(tmp_path, monkeypatch):
    run = ArenaRun.create([], "Tester", "enUS", seed=17, format_id=WILD)
    service = service_for(tmp_path, run)
    try:
        def forbidden(*args):
            raise AssertionError("non-draft states must not query ratings")
        monkeypatch.setattr(ratings, "get_rating", forbidden)
        assert "rating_source" not in service.state()
        run.choose_hero(run.hero_choices[0])
        for _ in range(30):
            run.choose_card(run.choices[0])
        # Projection works for an already saved ready/match run offline.
        service.run = run
        assert "rating_source" not in service.state()
        run.start_match()
        assert "rating_source" not in service.state()
    finally:
        service.close()
