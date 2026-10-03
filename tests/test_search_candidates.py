"""Contracts for the bounded tactical root-candidate pass."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from fireplace.agent_api import END_TURN, PLAY_CARD, Action
from fireplace.mcts_agent import MCTSAgent
from fireplace.search_candidates import (
    CANDIDATE_SAMPLE_SEEDS,
    action_key,
    evaluate_root_candidates,
)


def _observation(score: float = 0.0, *, uncertain: bool = False):
    return {
        "phase": "MAIN",
        "score": score,
        "search_uncertain": uncertain,
        "self": {
            "hero": {"entity_id": 1, "health": 30},
            "hand": [
                {"entity_id": 10, "card_id": "SPELL_TARGET", "type": "SPELL"},
                {"entity_id": 11, "card_id": "SPELL_AOE", "type": "SPELL"},
                {"entity_id": 12, "card_id": "SPELL_CHOOSE", "type": "SPELL"},
            ],
        },
        "opponent": {"hero": {"entity_id": 2, "health": 30}, "board": []},
    }


def _actions():
    return (
        Action(type=PLAY_CARD, source_entity_id=10, target_entity_id=2),
        Action(type=PLAY_CARD, source_entity_id=11),
        Action(type=PLAY_CARD, source_entity_id=12, choose_option_entity_id=99),
        Action(type=END_TURN),
    )


@dataclass
class Child:
    view: dict
    uncertain: bool = False

    @property
    def terminal(self):
        return False

    def observation(self):
        return self.view

    def opponent_attack_position(self):
        return None


class FakePosition:
    def __init__(self, outcomes, *, root=None):
        self.outcomes = outcomes
        self.root = root or _observation()
        self.calls = []

    @property
    def terminal(self):
        return False

    def observation(self):
        return self.root

    def legal_actions(self):
        return list(_actions())

    def transition(self, action, *, seed=None):
        self.calls.append((action_key(action), seed))
        outcome = self.outcomes[action_key(action)]
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            outcome = outcome(seed)
        uncertain = False
        if isinstance(outcome, tuple):
            outcome, uncertain = outcome
        view = dict(self.root)
        view["score"] = outcome
        view["search_uncertain"] = uncertain
        return Child(view, uncertain=uncertain)

    def opponent_attack_position(self):
        return None


def _outcomes(values):
    actions = _actions()
    return {
        action_key(actions[0]): values[0],
        action_key(actions[1]): values[1],
        action_key(actions[2]): values[2],
        action_key(actions[3]): values[3],
    }


def test_all_root_spell_categories_and_end_are_covered_in_stable_order():
    actions = _actions()
    position = FakePosition(_outcomes((4, 4, 4, 0)))
    result = evaluate_root_candidates(position.observation(), actions, position)

    assert result.complete
    assert result.considered_roots == len(actions)
    assert [row.action for row in result.candidates] == list(actions)
    assert [row.source_card_id for row in result.candidates[:3]] == [
        "SPELL_TARGET",
        "SPELL_AOE",
        "SPELL_CHOOSE",
    ]
    assert all(row.completed for row in result.candidates)
    # END is evaluated first to establish the baseline, but legal order is
    # preserved for ties and in the public trace.
    assert position.calls[0][0] == action_key(actions[-1])
    assert result.selected_action == actions[0]
    json.dumps(result.as_stats())


def test_all_immediate_spell_harm_falls_back_to_end():
    actions = _actions()
    result = evaluate_root_candidates(
        _observation(), actions, FakePosition(_outcomes((-4, -3, -2, 0)))
    )

    assert result.selected_action == actions[-1]
    assert result.reason == "end_baseline"
    assert result.baseline_score == 0


def test_equal_candidate_scores_keep_the_first_legal_action():
    actions = _actions()
    result = evaluate_root_candidates(
        _observation(), actions, FakePosition(_outcomes((5, 5, 5, 0)))
    )

    assert result.selected_action == actions[0]
    assert result.candidates[0].selected
    assert not result.candidates[1].selected


def test_zero_score_remains_better_than_later_negative_candidates():
    actions = _actions()
    result = evaluate_root_candidates(
        _observation(), actions, FakePosition(_outcomes((0, -5, -6, -10)))
    )

    assert result.selected_action == actions[0]
    assert result.candidates[0].score == 0
    assert not result.candidates[1].selected


def test_uncertain_branch_samples_three_seeds_and_uses_conservative_score():
    actions = _actions()

    def random_outcome(seed):
        return ({CANDIDATE_SAMPLE_SEEDS[0]: 10,
                 CANDIDATE_SAMPLE_SEEDS[1]: 3,
                 CANDIDATE_SAMPLE_SEEDS[2]: 7}[seed], True)

    result = evaluate_root_candidates(
        _observation(),
        actions,
        FakePosition(_outcomes((random_outcome, -1, -1, 0))),
    )
    candidate = result.candidates[0]
    assert candidate.uncertainty
    assert candidate.completed
    assert candidate.samples == (10.0, 3.0, 7.0)
    assert candidate.mean_score == 20.0 / 3.0
    assert candidate.score == 3.0
    assert result.selected_action == actions[0]
    assert result.reason == "candidate_beats_end"


def test_failures_and_cutoffs_are_explicit_rows():
    actions = _actions()
    failed_position = FakePosition(
        _outcomes((RuntimeError("unsupported"), -1, -1, 0))
    )
    failed = evaluate_root_candidates(_observation(), actions, failed_position)
    assert failed.candidates[0].reason == "transition_failed"
    assert failed.failed_count == 1
    assert failed.selected_action == actions[-1]

    now = iter((0.0, 2.0, 2.0, 2.0))
    cutoff = evaluate_root_candidates(
        _observation(),
        actions,
        FakePosition(_outcomes((5, 5, 5, 0))),
        deadline=1.0,
        clock=lambda: next(now),
    )
    assert cutoff.cutoff
    assert all(row.reason == "cutoff" for row in cutoff.candidates)
    assert not cutoff.complete


def test_cutoff_after_last_transition_is_not_reported_as_completed():
    actions = _actions()
    now = iter((0.0, 0.0, 2.0, 2.0, 2.0, 2.0))
    result = evaluate_root_candidates(
        _observation(),
        actions,
        FakePosition(_outcomes((5, 5, 5, 0))),
        deadline=1.0,
        clock=lambda: next(now),
    )

    end = result.candidates[-1]
    assert result.cutoff
    assert end.reason == "cutoff"
    assert not end.completed
    assert not result.complete


def test_final_basic_transition_crossing_deadline_keeps_cutoff_explicit():
    action = _actions()[0]
    now = [0.0]

    class LateTransition(FakePosition):
        def transition(self, action, *, seed=None):
            child = super().transition(action, seed=seed)
            now[0] = 2.0
            return child

    result = evaluate_root_candidates(
        _observation(),
        (action,),
        LateTransition(_outcomes((5, 0, 0, 0))),
        deadline=1.0,
        clock=lambda: now[0],
    )

    row = result.candidates[0]
    assert result.cutoff
    assert row.reason == "cutoff"
    assert row.immediate_score == 5.0
    assert not row.completed


def test_skipped_projection_preserves_direct_uncertainty_once():
    action = _actions()[0]
    now = [0.0]

    class LateUncertainTransition(FakePosition):
        def transition(self, action, *, seed=None):
            child = super().transition(action, seed=seed)
            now[0] = 2.0
            return child

    result = evaluate_root_candidates(
        _observation(),
        (action,),
        LateUncertainTransition(_outcomes(((5, True), 0, 0, 0))),
        deadline=1.0,
        clock=lambda: now[0],
    )

    row = result.candidates[0]
    assert result.cutoff
    assert row.uncertainty
    assert result.uncertain_count == 1
    assert len(result.child_cache) == 0


def test_failed_child_legal_actions_is_incomplete_and_cannot_win_end():
    play, end = _actions()[0], _actions()[-1]

    class BrokenChild(Child):
        def legal_actions(self):
            raise RuntimeError("engine enumeration failed")

    class BrokenPosition(FakePosition):
        def transition(self, action, *, seed=None):
            child = super().transition(action, seed=seed)
            if action == play:
                return BrokenChild(child.view)
            return child

    result = evaluate_root_candidates(
        _observation(),
        (play, end),
        BrokenPosition(
            {
                action_key(play): 5,
                action_key(end): 0,
            }
        ),
    )

    row = result.candidates[0]
    assert row.reason == "legal_actions_failed"
    assert row.immediate_score == 5.0
    assert not row.completed
    assert result.failed_count >= 1
    assert result.selected_action == end


def test_basic_cutoff_projects_prepared_spell_roots_with_remaining_budget():
    """Coverage cutoff must not discard the already prepared spell prefix."""

    actions = _actions() + (Action(type=PLAY_CARD, source_entity_id=90),)
    outcomes = {
        action_key(action): value
        for action, value in zip(actions, (5, 4, 3, 0, -5))
    }
    position = FakePosition(outcomes)

    # END and all three spell variants are prepared before the 60% slice
    # expires.  A minion root remains basic-uncovered, while the shared clock
    # leaves enough time for the prepared rows' projection pass.
    ticks = iter([0.0] * 15 + [0.7])

    def clock():
        try:
            return next(ticks)
        except StopIteration:
            return 0.7

    result = evaluate_root_candidates(
        _observation(),
        actions,
        position,
        deadline=1.0,
        clock=clock,
    )

    assert result.cutoff
    assert not result.basic_complete
    assert result.basic_evaluated_count == 4
    assert result.projected_completed_count == 4
    assert all(result.candidates[index].completed for index in range(4))
    assert result.candidates[-1].reason == "cutoff"
    assert not result.complete


def test_deterministic_child_cache_reuses_root_transition_without_agent_rng():
    actions = _actions()
    position = FakePosition(_outcomes((5, 4, 3, 0)))
    agent = MCTSAgent(policy_version="tactical_v2", seed=77, time_budget=None, max_iterations=1)
    before = agent.random.getstate()
    result = evaluate_root_candidates(position.observation(), actions, position)
    assert agent.random.getstate() == before
    assert len(result.child_cache) == len(actions)

    # MCTS consumes the cache directly for its first expansion.  No second
    # transition is needed for a root action already proved deterministic.
    calls_before = len(position.calls)
    agent._run_mcts(
        position.observation(),
        actions,
        position,
        time.monotonic(),
        root_child_cache=result.child_cache,
    )
    assert len(position.calls) == calls_before


def test_completed_mcts_combo_can_keep_a_negative_immediate_root():
    actions = _actions()
    agent = MCTSAgent(policy_version="tactical_v2", seed=3, time_budget=None)
    candidate_pass = evaluate_root_candidates(
        _observation(), actions, FakePosition(_outcomes((-5, -2, -3, 0)))
    )
    assert candidate_pass.selected_action == actions[-1]
    agent.last_search_stats = {
        "best_reward": 0.8,
        "completed_leaves": 1,
        "best_score": 20,
        "best_path": (actions[0],),
        "search_uncertain": False,
    }
    assert agent._select_unified_candidate(
        _observation(), actions, actions[0], candidate_pass
    ) == actions[0]


def test_incomplete_end_projection_cannot_replace_completed_mcts_line():
    actions = _actions()
    now = iter((0.0, 0.0, 2.0, 2.0, 2.0, 2.0))
    candidate_pass = evaluate_root_candidates(
        _observation(),
        actions,
        FakePosition(_outcomes((5, 5, 5, 0))),
        deadline=1.0,
        clock=lambda: next(now),
    )
    agent = MCTSAgent(policy_version="tactical_v2", seed=3, time_budget=None)
    agent.last_search_stats = {
        "best_reward": 0.8,
        "completed_leaves": 1,
        "best_score": 20,
        "best_path": (actions[0],),
        "search_uncertain": False,
    }

    assert candidate_pass.candidates[-1].reason == "cutoff"
    assert agent._select_unified_candidate(
        _observation(), actions, actions[0], candidate_pass
    ) == actions[0]
