"""Golden values captured from the working tree before adding formats."""
import hashlib
import json

from fireplace.arena.run import ArenaRun
from fireplace.web_gui.arena_factory import build_arena_game

SETS = ["GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"]

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def test_custom_original_draft_and_opponent_random_stream():
    run = ArenaRun.create(SETS, "Tester", "zhCN", seed=17)
    heroes = list(run.hero_choices)
    run.choose_hero(heroes[0])
    offers = []
    for _ in range(30):
        offers.append(list(run.choices))
        run.choose_card(run.choices[0])
    assert digest({"hero_offers": heroes, "offers": offers, "deck": run.deck}) == "48c3c420fa77771b392805022d2cf46cacb73219f0ce6b42b1289c1f3f1d823b"
    game, _, opponent = build_arena_game(seed=100017, nickname=run.nickname, hero_id=run.hero_id, deck=run.deck, selected_sets=run.selected_sets)
    assert digest({"opponent_hero": opponent.starting_hero, "opponent_deck": opponent.starting_deck, "post_rng": [game.random.random() for _ in range(3)]}) == "30499c7d6cca2cf009e72c9a48d1fa5d117d048472ef838a555b1f6beb10f861"
    payload = run.to_dict()
    assert payload["version"] == 1
    assert "format_id" not in payload and "ai_drafts" not in payload
    assert ArenaRun.from_dict(payload).to_dict() == payload
