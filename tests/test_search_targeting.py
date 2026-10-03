"""Focused contracts for the bounded tactical spell-target sanity pass."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fireplace.agent_api import Action
from fireplace.mcts_agent import MCTSAgent
from fireplace.search_targeting import check_selected_spell_target


def _observation(*, score: float = 0.0, uncertain: bool = False):
    return {
        "phase": "MAIN",
        "score": score,
        "search_uncertain": uncertain,
        "self": {
            "hero": {"entity_id": 1, "health": 30, "armor": 0},
            "board": [{"entity_id": 11, "atk": 4, "health": 4}],
            "hand": [{"entity_id": 10, "type": "SPELL", "card_id": "TEST", "cost": 4}],
        },
        "opponent": {
            "hero": {"entity_id": 2, "health": 30, "armor": 0},
            "board": [
                {"entity_id": 20, "atk": 5, "health": 5},
                {"entity_id": 21, "atk": 3, "health": 3},
            ],
        },
    }


def _actions(*targets: int, choose: int | None = None):
    return [
        Action(
            type="PLAY_CARD",
            source_entity_id=10,
            target_entity_id=target,
            choose_option_entity_id=choose,
        )
        for target in targets
    ] + [Action(type="END_TURN")]


@dataclass
class FakePosition:
    outcomes: dict[int, object]
    root: dict

    def __post_init__(self):
        self.seeds: list[int] = []

    @property
    def terminal(self):
        return False

    def observation(self):
        return self.root

    def transition(self, action, *, seed=None):
        self.seeds.append(seed)
        outcome = self.outcomes[action.target_entity_id]
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome == "uncertain":
            view = dict(self.root)
            view["score"] = -20
            view["search_uncertain"] = True
        else:
            view = dict(self.root)
            view["score"] = outcome
        return FakeChild(view)


@dataclass
class FakeChild:
    view: dict

    def observation(self):
        return self.view


def _check(outcomes, selected, *, root_score=0, **kwargs):
    observation = _observation(score=root_score)
    actions = _actions(11, 20, 21)
    position = FakePosition(outcomes, observation)
    result = check_selected_spell_target(observation, actions, position, selected, **kwargs)
    return result, actions, position


def test_enemy_target_with_better_engine_score_replaces_selected_target():
    actions = _actions(11, 20, 21)
    result, _actions_value, position = _check(
        {11: -5, 20: 12, 21: 5}, actions[0]
    )

    assert result.action == actions[1]
    assert result.changed and result.complete
    assert result.reason == "better_target"
    assert result.evaluated_count == 3
    assert position.seeds and set(position.seeds) == {104729}


def test_all_harmful_targets_choose_legal_end_turn():
    actions = _actions(11, 20, 21)
    result, _actions_value, _position = _check(
        {11: -5, 20: -2, 21: -1}, actions[0]
    )

    assert result.action == actions[-1]
    assert result.reason == "all_targets_below_no_action"
    assert result.complete


@pytest.mark.parametrize("reward,completed", [(0.94, 1), (1.0, 0), (1.0, None)])
def test_uncertain_or_uncompleted_win_cannot_bypass_target_check(reward, completed):
    observation = _observation()
    actions = _actions(11, 20, 21)
    position = FakePosition({11: -5, 20: 12, 21: 5}, observation)
    agent = MCTSAgent(policy_version="tactical_v2")
    agent.last_search_stats = {
        "best_reward": reward, "best_score": 1_000_030,
        "best_path": (actions[0],), "search_uncertain": False,
    }
    if completed is not None:
        agent.last_search_stats["completed_leaves"] = completed
    assert agent._target_sanity_action(observation, actions, position, actions[0]) == actions[1]


@pytest.mark.parametrize("limit", [1, 2])
def test_truncated_target_group_avoids_known_harmful_self_cast(limit):
    actions = _actions(11, 20, 21)
    result, _, position = _check({11: -5, 20: 12, 21: 5}, actions[0], max_actions=limit)
    assert result.action.type == "END_TURN"
    assert not result.complete and len(position.seeds) <= limit


def test_failed_sibling_avoids_known_harmful_self_cast():
    actions = _actions(11, 20, 21)
    result, _, _ = _check({11: -5, 20: RuntimeError("unsupported"), 21: 12}, actions[0])
    assert result.action.type == "END_TURN" and not result.complete


def test_deadline_during_target_group_avoids_known_harmful_self_cast():
    actions = _actions(11, 20, 21)
    ticks = iter((0.0, 0.0, 2.0))
    result, _, position = _check({11: -5, 20: 12, 21: 5}, actions[0],
                                deadline=1.0, clock=lambda: next(ticks))
    assert result.action.type == "END_TURN" and len(position.seeds) == 1


def test_friendly_positive_target_remains_allowed():
    actions = _actions(11, 20, 21)
    result, _actions_value, _position = _check(
        {11: 9, 20: 3, 21: 4}, actions[0]
    )

    assert result.action == actions[0]
    assert not result.changed


def test_exact_tie_preserves_current_legal_action():
    actions = _actions(11, 20, 21)
    result, _actions_value, _position = _check(
        {11: 7, 20: 7, 21: 7}, actions[1]
    )

    assert result.action == actions[1]
    assert result.reason == "selected_not_worse_than_no_action"


def test_partial_model_failure_does_not_pick_an_unevaluated_target():
    actions = _actions(11, 20, 21)
    result, _actions_value, _position = _check(
        {11: RuntimeError("unsupported"), 20: 50, 21: 50}, actions[0]
    )

    assert result.action == actions[0]
    assert result.mode == "partial"
    assert result.reason == "transition_failed"


def test_seeded_uncertain_child_is_scored_but_expired_deadline_fails_closed():
    actions = _actions(11, 20, 21)
    uncertain, _actions_value, position = _check(
        {11: "uncertain", 20: 50, 21: 50}, actions[0]
    )
    expired, _actions_value, expired_position = _check(
        {11: -5, 20: 50, 21: 50}, actions[0], deadline=0
    )

    assert uncertain.action == actions[1]
    assert uncertain.reason == "better_target"
    assert uncertain.uncertain_count == 1
    assert uncertain.complete
    assert expired.action == actions[0]
    assert expired.reason == "deadline_before_check"
    assert not expired_position.seeds
    assert position.seeds and set(position.seeds) == {104729}


def test_uncertain_root_is_scored_and_non_spell_is_skipped_without_blacklist():
    observation = _observation(uncertain=True)
    actions = _actions(11, 20, 21)
    position = FakePosition({11: -5, 20: 50, 21: 50}, observation)
    uncertain = check_selected_spell_target(observation, actions, position, actions[0])
    observation = _observation(uncertain=False)
    observation["self"]["hand"][0]["type"] = "MINION"
    non_spell = check_selected_spell_target(observation, actions, position, actions[0])

    assert uncertain.action == actions[1]
    assert uncertain.reason == "better_target"
    assert uncertain.uncertain_count >= 1
    assert non_spell.reason == "source_not_known_spell"
    assert position.seeds and set(position.seeds) == {104729}


def test_same_source_choose_branch_stays_with_selected_branch():
    observation = _observation()
    selected = Action(
        type="PLAY_CARD", source_entity_id=10, target_entity_id=11, choose_option_entity_id=100
    )
    same_branch = Action(
        type="PLAY_CARD", source_entity_id=10, target_entity_id=20, choose_option_entity_id=100
    )
    other_branch = Action(
        type="PLAY_CARD", source_entity_id=10, target_entity_id=21, choose_option_entity_id=101
    )
    end = Action(type="END_TURN")
    actions = [selected, same_branch, other_branch, end]
    position = FakePosition({11: -5, 20: 10, 21: 100}, observation)
    result = check_selected_spell_target(observation, actions, position, selected)

    assert result.action == same_branch
    assert result.evaluated_count == 2
