"""Real-engine coverage across spell effects, without a per-card rule list."""

import json

import pytest
from hearthstone.enums import Zone

from fireplace.replay_state import normalized_game_state
from fireplace.mcts_agent import MCTSAgent
from fireplace.search_candidates import evaluate_root_candidates
from fireplace.search_simulation import EngineSearchPosition
from tests.test_search_simulation import main_session
from tests.test_spell_targeting_integration import reported_mage_board


def evaluate(session, player):
    before = normalized_game_state(session.game)
    rng = session.game.random.getstate()
    result = evaluate_root_candidates(session.observation(player), session.legal_actions(player),
                                     EngineSearchPosition.from_game(session.game, player), budget=None)
    assert normalized_game_state(session.game) == before
    assert session.game.random.getstate() == rng
    json.dumps(result.as_stats(), allow_nan=False)
    return result


def candidate(result, spell, target=None):
    return next(row for row in result.candidates if row.action.source_entity_id == spell.entity_id
                and (target is None or row.action.target_entity_id == target.entity_id))


@pytest.mark.parametrize("card_id", ["CS2_032", "CS2_027", "CS2_026", "CS2_023", "CS2_028"])
def test_untargeted_spells_are_compared_and_do_not_mutate_live_game(card_id):
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        for _ in range(3):
            player.opponent.summon("CS2_182")
        spell = player.card(card_id, zone=Zone.HAND)
        result = evaluate(session, player)
        row = candidate(result, spell)
        assert row.action.target_entity_id is None
        assert row.score is not None
        assert row.reason not in {"transition_failed", "score_failed", "root_cap", "cutoff"}
        assert result.complete
        if card_id in {"CS2_032", "CS2_027", "CS2_028"}:
            assert row.score > result.baseline_score
    finally:
        session.close()


def test_draw_spell_receives_resources_but_not_hidden_card_identities():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        spell = player.card("CS2_023", zone=Zone.HAND)
        result = evaluate(session, player)
        row = candidate(result, spell)
        assert row.score > result.baseline_score
        assert row.uncertainty
        assert len(row.samples) == 3
        assert row.mean_score is not None
    finally:
        session.close()


def test_draw_into_fatigue_is_not_treated_as_free_resources():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        player.hero.damage = player.hero.max_health - 2
        for card in tuple(player.deck):
            card.zone = Zone.GRAVEYARD
        spell = player.card("CS2_023", zone=Zone.HAND)
        result = evaluate(session, player)
        assert candidate(result, spell).score <= -1_000_000
        assert result.selected_action.type == "END_TURN"
    finally:
        session.close()


def test_silencing_own_ancient_watcher_is_allowed_when_it_gains_an_attack():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        watcher = player.summon("EX1_045")
        watcher.turns_in_play = 1
        spell = player.card("EX1_332", zone=Zone.HAND)
        player.opponent.hero.damage = player.opponent.hero.max_health - 4
        before = normalized_game_state(session.game)
        agent = MCTSAgent(policy_version="tactical_v2", time_budget=None, seed=3)
        selected = session.choose_action(player, agent=agent)
        assert selected.source_entity_id == spell.entity_id
        assert selected.target_entity_id == watcher.entity_id
        assert agent.last_search_stats["deterministic_lethal"]
        assert normalized_game_state(session.game) == before
    finally:
        session.close()


def test_choose_one_branches_are_separate_candidates():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        player.summon("CS2_231")
        spell = player.card("EX1_160", zone=Zone.HAND)
        result = evaluate(session, player)
        rows = [row for row in result.candidates if row.action.source_entity_id == spell.entity_id]
        assert len({row.action.choose_option_entity_id for row in rows}) == 2
        assert all(row.score is not None for row in rows)
        assert result.complete
    finally:
        session.close()


def test_random_missiles_are_sampled_and_never_cached_as_deterministic():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        player.opponent.hero.damage = player.opponent.hero.max_health - 3
        player.opponent.summon("CS2_231")
        spell = player.card("EX1_277", zone=Zone.HAND)
        result = evaluate(session, player)
        row = candidate(result, spell)
        assert row.uncertainty
        assert len(row.samples) == 3
        assert row.score == min(row.samples)
        assert row.child is None
        assert all(key[1] != spell.entity_id for key in result.child_cache)
    finally:
        session.close()


def test_silence_recognizes_visible_trigger_ability_without_a_card_override():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        trigger = player.opponent.summon("BRM_002")
        spell = player.card("EX1_332", zone=Zone.HAND)
        result = evaluate(session, player)
        assert candidate(result, spell, trigger).score > result.baseline_score
    finally:
        session.close()


def test_discover_reports_choice_boundary_instead_of_inventing_future_options():
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        spell = player.card("LOE_115", zone=Zone.HAND)
        result = evaluate(session, player)
        rows = [row for row in result.candidates if row.action.source_entity_id == spell.entity_id]
        assert len(rows) == 2
        assert all(row.uncertainty for row in rows)
        assert all(row.reason == "choice_boundary" for row in rows)
        assert all(not row.completed for row in rows)
    finally:
        session.close()


def test_reported_board_all_polymorph_targets_have_basic_scores():
    session, player, flamewaker, polymorph, _ = reported_mage_board()
    try:
        result = evaluate(session, player)
        rows = [row for row in result.candidates if row.action.source_entity_id == polymorph.entity_id]
        expected = [action for action in session.legal_actions(player)
                    if action.source_entity_id == polymorph.entity_id]
        assert len(rows) == len(expected)
        assert all(row.immediate_score is not None for row in rows)
        own = next(row for row in rows if row.action.target_entity_id == flamewaker.entity_id)
        enemies = [row for row in rows if row is not own]
        assert own.immediate_score < max(row.immediate_score for row in enemies)
        assert result.as_stats()["basic_evaluated_count"] > 0
    finally:
        session.close()
