"""Focused contracts for the tactical MCTS policy version."""

from __future__ import annotations

from itertools import count
from types import SimpleNamespace

import pytest

from fireplace.agent_api import Action
from fireplace.mcts_agent import MCTSAgent
from fireplace.search_scoring import (
    LETHAL_SCORE,
    is_terminal_draw,
    is_terminal_loss,
    is_terminal_win,
    score_observation,
    score_tactical_observation,
)
from fireplace.search_tactics import TacticalSearchResult, find_deterministic_lethal


def _observation(
    *, score=0, enemy_health=10, own_health=30, uncertain=False, search_outcome=None
):
    result = {
        "phase": "MAIN",
        "turn": 1,
        "score": score,
        "search_uncertain": uncertain,
        "self": {"hero": {"entity_id": 1, "health": own_health}, "hand": []},
        "opponent": {"hero": {"entity_id": 2, "health": enemy_health}, "board": []},
    }
    if search_outcome is not None:
        result["search_outcome"] = search_outcome
    return result


class TacticalPosition:
    """Tiny immutable position supporting both lethal and scalar fake lines."""

    def __init__(self, *, enemy_health=10, own_health=30, score=0, uncertain=False, done=False):
        self.enemy_health = enemy_health
        self.own_health = own_health
        self.score = score
        self.uncertain = uncertain
        self.done = done

    @property
    def terminal(self):
        return self.done or self.enemy_health <= 0 or self.own_health <= 0

    def observation(self):
        return _observation(
            score=self.score,
            enemy_health=self.enemy_health,
            own_health=self.own_health,
            uncertain=self.uncertain,
        )

    def legal_actions(self):
        if self.terminal:
            return []
        return [
            Action(type="END_TURN"),
            Action(type="ATTACK", source_entity_id=1, target_entity_id=2),
        ]

    def transition(self, action, *, seed=None):
        del seed
        if action.type == "ATTACK":
            return type(self)(
                enemy_health=0,
                own_health=self.own_health,
                score=self.score + 10,
                uncertain=self.uncertain,
                done=True,
            )
        return type(self)(
            enemy_health=self.enemy_health,
            own_health=self.own_health,
            score=self.score,
            uncertain=self.uncertain,
            done=True,
        )

    def opponent_attack_position(self):
        return self


class ScalarPosition(TacticalPosition):
    """No hero fields: tactical MCTS must still support scalar test doubles."""

    def observation(self):
        return {"phase": "MAIN", "turn": 1, "score": self.score}


def test_tactical_probe_keeps_a_real_lethal_when_final_transition_crosses_deadline():
    ticks = count()
    clock = lambda: next(ticks) * 0.001
    result = find_deterministic_lethal(
        _observation(enemy_health=3),
        TacticalPosition(enemy_health=3).legal_actions(),
        TacticalPosition(enemy_health=3),
        deadline=0.001,
        max_nodes=4,
        max_depth=2,
        clock=clock,
    )
    assert result.deterministic_lethal
    assert result.action.type == "ATTACK"


def test_terminal_outcome_overrides_equal_visible_hero_health():
    win = _observation(enemy_health=30, own_health=30, search_outcome="win")
    loss = _observation(enemy_health=30, own_health=30, search_outcome="loss")
    draw = _observation(enemy_health=30, own_health=30, search_outcome="draw")
    assert is_terminal_win(win)
    assert not is_terminal_loss(win)
    assert score_tactical_observation(win) >= LETHAL_SCORE
    assert is_terminal_loss(loss)
    assert is_terminal_draw(draw)


class EqualHealthOutcomePosition(TacticalPosition):
    def observation(self):
        result = super().observation()
        if self.done:
            result["self"]["hero"]["health"] = 30
            result["opponent"]["hero"]["health"] = 30
            result["search_outcome"] = "win"
        return result


def test_tactical_dfs_accepts_engine_terminal_win_when_health_is_positive():
    position = EqualHealthOutcomePosition(enemy_health=30)
    agent = MCTSAgent(policy_version="tactical_v2", time_budget=None, max_iterations=2)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen.type == "ATTACK"
    assert agent.last_search_stats["deterministic_lethal"] is True


def test_mcts_keeps_terminal_win_when_last_transition_crosses_deadline(monkeypatch):
    values = iter((0.0, 0.0002, 0.0003, 0.002, 0.002, 0.002))

    def monotonic():
        try:
            return next(values)
        except StopIteration:
            return 0.002

    monkeypatch.setattr("fireplace.mcts_agent.time", SimpleNamespace(monotonic=monotonic))

    class TerminalAfterDeadline(EqualHealthOutcomePosition):
        def transition(self, action, *, seed=None):
            del action, seed
            monotonic()  # The final engine step crosses the cooperative deadline.
            return type(self)(enemy_health=30, done=True)

        def legal_actions(self):
            if self.terminal:
                return []
            return [Action(type="ATTACK", source_entity_id=1, target_entity_id=2)]

    position = TerminalAfterDeadline(enemy_health=30)
    agent = MCTSAgent(policy_version="tactical_v2", time_budget=0.001, max_iterations=1)
    # Isolate the shared MCTS flow so this regression exercises its terminal
    # classification after a deadline crossing rather than the pre-probe.
    agent._tactical_probe = lambda *args: (TacticalSearchResult(), {})
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen.type == "ATTACK"
    assert agent.last_search_stats["mode"] == "mcts"
    assert agent.last_search_stats["best_score"] >= LETHAL_SCORE


def test_tactical_agent_finds_single_winning_action_with_a_small_budget():
    position = TacticalPosition(enemy_health=3)
    agent = MCTSAgent(policy_version="tactical_v2", time_budget=0.01, max_iterations=2)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen.type == "ATTACK"
    assert agent.last_search_stats["mode"] == "tactical_lethal"
    assert agent.last_search_stats["deterministic_lethal"] is True


def test_tactical_mcts_supports_scalar_fake_positions_with_bounded_rewards():
    position = ScalarPosition(score=0, enemy_health=100)
    actions = position.legal_actions()
    agent = MCTSAgent(policy_version="tactical_v2", time_budget=None, max_iterations=8)
    chosen = agent.choose_action_with_search(position.observation(), actions, position)
    assert chosen in actions
    assert agent.last_search_stats["mode"] in {"mcts", "mcts_partial"}
    assert all(0.0 <= row["mean"] <= 1.0 for row in agent.last_search_stats["root_stats"])


def test_legacy_constructor_and_scorer_remain_stable():
    agent = MCTSAgent(seed=7, time_budget=None, max_iterations=3)
    assert agent.policy_version == "legacy_v1"
    assert tuple(agent.export_config()) == MCTSAgent.CONFIG_KEYS
    assert "seed" not in agent.export_config()
    observation = _observation(score=17)
    assert score_observation(observation) == 17
    assert agent.choose_action(observation, [Action(type="END_TURN")]).type == "END_TURN"


def test_zero_budget_disables_tactical_search_and_resets_diagnostics():
    position = TacticalPosition(enemy_health=3)
    agent = MCTSAgent(policy_version="tactical_v2", time_budget=0, max_iterations=20)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen in position.legal_actions()
    assert agent.last_search_stats["mode"] == "fallback"
    assert agent.last_search_stats["nodes"] == 0
    assert agent.last_search_stats["iterations"] == 0


def test_uncertain_branch_is_never_reported_as_deterministic_lethal():
    position = TacticalPosition(enemy_health=3, uncertain=True)
    agent = MCTSAgent(policy_version="tactical_v2", time_budget=None, max_iterations=4)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen in position.legal_actions()
    assert agent.last_search_stats["deterministic_lethal"] is False
    assert agent.last_search_stats["mode"] != "tactical_lethal"


class ReplyPosition:
    @property
    def terminal(self):
        return False

    def observation(self):
        return _observation(enemy_health=20, own_health=6)

    def legal_actions(self):
        return [Action(type="ATTACK", source_entity_id=5, target_entity_id=1)]

    def transition(self, action, *, seed=None):
        del action, seed
        return _DeadReplyPosition()


class _DeadReplyPosition(ReplyPosition):
    @property
    def terminal(self):
        return True

    def observation(self):
        return _observation(enemy_health=20, own_health=0)

    def legal_actions(self):
        return []


def test_tactical_score_penalizes_a_visible_self_lethal_reply():
    observation = _observation(enemy_health=20, own_health=6)
    baseline = score_tactical_observation(observation)
    defended = score_tactical_observation(observation, reply_position=ReplyPosition())
    assert defended < baseline


@pytest.mark.parametrize("policy_version", ["legacy_v1", "tactical_v2"])
def test_policy_version_validation_is_explicit(policy_version):
    assert MCTSAgent(policy_version=policy_version).policy_version == policy_version
    with pytest.raises(ValueError):
        MCTSAgent(policy_version="unsupported")
