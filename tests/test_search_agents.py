"""Deterministic value-boundary checks for the selectable search agents."""

from __future__ import annotations

import math
from itertools import count
from types import SimpleNamespace

import pytest

from fireplace.agent_api import Action
from fireplace.agent_factory import create_agent
from fireplace.mcts_agent import MCTSAgent, MCTSNode
from fireplace.radical_agent import RadicalAgent
from fireplace.search_scoring import LETHAL_SCORE, score_observation


def _observation(*, phase="MAIN", mana=4, hand=(), score=0, turn=1):
    return {
        "phase": phase,
        "turn": turn,
        "self": {
            "hero": {"entity_id": 1, "health": 30, "armor": 0},
            "mana": mana,
            "hand": list(hand),
            "board": [],
        },
        "opponent": {
            "hero": {"entity_id": 2, "health": 30, "armor": 0},
            "board": [],
        },
        "score": score,
    }


class FakePosition:
    """A tiny immutable tree with explicit scalar scores."""

    def __init__(self, score=0, depth=0, *, terminal=False, damage=0):
        self.score = score
        self.depth = depth
        self._terminal = terminal
        self.damage = damage

    @property
    def terminal(self):
        return self._terminal or self.damage >= 6

    def observation(self):
        return _observation(score=self.score, turn=self.depth + 1)

    def legal_actions(self):
        if self.terminal:
            return []
        return [
            Action(type="ATTACK", source_entity_id=1, target_entity_id=2),
            Action(type="ATTACK", source_entity_id=2, target_entity_id=2),
            Action(type="END_TURN"),
        ]

    def transition(self, action, *, seed=None):
        del seed
        if action.type == "ATTACK":
            return type(self)(self.score + 1, self.depth + 1, damage=self.damage + 3)
        return type(self)(self.score, self.depth + 1, terminal=True, damage=self.damage)

    def opponent_attack_position(self):
        return self


def test_radical_knapsack_uses_cost_plus_weight_and_stable_power_order():
    hand = [
        {"entity_id": 10, "card_id": "CHEAP_A", "cost": 2, "power_weight": 2},
        {"entity_id": 11, "card_id": "CHEAP_B", "cost": 2, "power_weight": 1},
        {"entity_id": 12, "card_id": "EXPENSIVE", "cost": 4, "power_weight": 0},
    ]
    actions = [
        Action(type="PLAY_CARD", source_entity_id=10),
        Action(type="PLAY_CARD", source_entity_id=11),
        Action(type="PLAY_CARD", source_entity_id=12),
        Action(type="END_TURN"),
    ]
    agent = RadicalAgent(time_budget=None)
    selected = agent.select_cards(_observation(hand=hand), actions)
    assert [card.source_id for card in selected] == [10, 11]
    assert agent.choose_action(_observation(hand=hand), actions) == actions[0]


def test_radical_uses_a_legal_coin_for_the_one_extra_mana_plan():
    hand = [
        {"entity_id": 10, "card_id": "GAME_005", "cost": 0},
        {"entity_id": 11, "card_id": "ONE_OVER", "cost": 5},
    ]
    actions = [Action(type="PLAY_CARD", source_entity_id=10), Action(type="END_TURN")]
    chosen = RadicalAgent(time_budget=None).choose_action(
        _observation(mana=4, hand=hand), actions
    )
    assert chosen == actions[0]


def test_radical_coin_is_skipped_when_extra_mana_does_not_improve_plan():
    hand = [
        {"entity_id": 10, "card_id": "GAME_005", "cost": 0},
        {"entity_id": 11, "card_id": "ONE", "cost": 1},
    ]
    coin = Action(type="PLAY_CARD", source_entity_id=10)
    card = Action(type="PLAY_CARD", source_entity_id=11)
    chosen = RadicalAgent(time_budget=None).choose_action(
        _observation(mana=1, hand=hand), [coin, card, Action(type="END_TURN")]
    )
    assert chosen == card


def test_radical_card_and_power_weights_control_different_dimensions():
    hand = [
        {"entity_id": 10, "card_id": "A", "cost": 2, "power_weight": 0},
        {"entity_id": 11, "card_id": "B", "cost": 2, "power_weight": 2},
    ]
    actions = [
        Action(type="PLAY_CARD", source_entity_id=10),
        Action(type="PLAY_CARD", source_entity_id=11),
    ]
    observation = _observation(mana=2, hand=hand)
    weighted = RadicalAgent(time_budget=None, card_weights={"A": 4, "B": 0})
    assert weighted.select_cards(observation, actions)[0].source_id == 10
    ordered = RadicalAgent(time_budget=None, power_weights={"A": 0, "B": 2})
    # Both cards fit only one at a time; the configured power weight is
    # visible when the card set is expanded to two one-cost plays.
    expanded_hand = [
        {"entity_id": 20, "card_id": "A", "cost": 1},
        {"entity_id": 21, "card_id": "B", "cost": 1},
    ]
    expanded_actions = [
        Action(type="PLAY_CARD", source_entity_id=20),
        Action(type="PLAY_CARD", source_entity_id=21),
    ]
    selected = ordered.select_cards(_observation(mana=2, hand=expanded_hand), expanded_actions)
    assert [card.source_id for card in selected] == [21, 20]


def test_radical_attack_search_can_pass_when_attack_is_worse():
    attack = Action(type="ATTACK", source_entity_id=1, target_entity_id=2)
    end = Action(type="END_TURN")

    class PassingPosition(FakePosition):
        def transition(self, action, *, seed=None):
            del seed
            return type(self)(-1 if action.type == "ATTACK" else 0, terminal=True)

        def legal_actions(self):
            return [] if self.terminal else [attack, end]

    observation = _observation(hand=(), score=0)
    chosen = RadicalAgent(time_budget=None, max_iterations=20).choose_action_with_search(
        observation, [attack, end], PassingPosition()
    )
    assert chosen == end


def test_radical_falls_back_to_hero_power_when_no_attack_exists():
    power = Action(type="USE_HERO_POWER", source_entity_id=20)
    end = Action(type="END_TURN")
    observation = _observation(hand=())
    observation["self"]["hero_power"] = {
        "entity_id": 20,
        "card_id": "HERO_08bp",
        "cost": 2,
        "is_usable": True,
    }
    agent = RadicalAgent(time_budget=None)
    assert agent.choose_action(observation, [power, end]) == power
    assert agent.choose_action_with_search(observation, [power, end], FakePosition()) == power


def test_mcts_returns_a_root_attack_for_a_two_action_lethal_line():
    position = FakePosition()
    actions = position.legal_actions()
    agent = MCTSAgent(seed=12, time_budget=None, max_iterations=128, max_depth=6)
    chosen = agent.choose_action_with_search(position.observation(), actions, position)
    assert chosen in actions
    assert chosen.type == "ATTACK"
    assert agent.last_search_stats["iterations"] <= 128
    assert agent.last_search_stats["completed_leaves"] > 0


def test_mcts_uct_uses_float_wins_and_visits():
    parent = MCTSNode(FakePosition(), visits=4)
    child = MCTSNode(FakePosition(), parent=parent, visits=2, wins=1.5)
    assert isinstance(child.wins, float)
    assert math.isclose(child.uct(0), 0.75)


def test_mcts_depth_cutoffs_are_reported_as_partial_lines():
    class UnboundedPosition(FakePosition):
        @property
        def terminal(self):
            return False

        def legal_actions(self):
            return [Action(type="ATTACK", source_entity_id=1, target_entity_id=2)]

        def transition(self, action, *, seed=None):
            del action, seed
            return type(self)(self.score + 1, self.depth + 1)

    position = UnboundedPosition()
    agent = MCTSAgent(seed=4, time_budget=None, max_iterations=4, max_depth=2)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen in position.legal_actions()
    assert agent.last_search_stats["completed_leaves"] == 0
    assert agent.last_search_stats["mode"] == "mcts_partial"
    assert agent.last_search_stats["truncated_lines"] > 0


def test_mcts_failed_transitions_are_not_completed_leaves():
    class BrokenPosition(FakePosition):
        def transition(self, action, *, seed=None):
            del action, seed
            raise RuntimeError("unsupported")

    position = BrokenPosition()
    agent = MCTSAgent(seed=1, time_budget=None, max_iterations=5, max_depth=3)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen in position.legal_actions()
    assert agent.last_search_stats["completed_leaves"] == 0
    assert agent.last_search_stats["failed_lines"] > 0


def test_search_score_handles_raw_lethal_health_and_double_ko():
    enemy_dead = _observation(score=0)
    enemy_dead["opponent"]["hero"].update(health=0, armor=10)
    assert score_observation(enemy_dead) >= LETHAL_SCORE
    both_dead = _observation(score=0)
    both_dead["self"]["hero"]["health"] = 0
    both_dead["opponent"]["hero"]["health"] = 0
    assert score_observation(both_dead) == 0


def test_zero_budget_and_iteration_caps_do_not_search():
    position = FakePosition()
    actions = position.legal_actions()
    zero = MCTSAgent(time_budget=0, max_iterations=20)
    chosen = zero.choose_action_with_search(position.observation(), actions, position)
    assert chosen in actions
    assert zero.last_search_stats["iterations"] == 0

    capped = RadicalAgent(time_budget=None, max_iterations=2, max_depth=6)
    capped.choose_action_with_search(position.observation(), actions, position)
    assert capped.last_search_stats["nodes"] <= 2


def test_deadline_stops_mcts_even_when_every_transition_fails(monkeypatch):
    ticks = count()
    monkeypatch.setattr(
        "fireplace.mcts_agent.time",
        SimpleNamespace(monotonic=lambda: next(ticks) * 0.001),
    )

    class BrokenPosition(FakePosition):
        def transition(self, action, *, seed=None):
            raise RuntimeError("unsupported")

    position = BrokenPosition()
    agent = MCTSAgent(seed=1, time_budget=0.004, max_iterations=100)
    chosen = agent.choose_action_with_search(
        position.observation(), position.legal_actions(), position
    )
    assert chosen in position.legal_actions()
    assert 0 < agent.last_search_stats["iterations"] < 100
    assert agent.last_search_stats["completed_leaves"] == 0


@pytest.mark.parametrize("agent", [RadicalAgent(time_budget=None), MCTSAgent(time_budget=None)])
def test_non_main_phase_and_current_legal_set_use_fallback(agent):
    mulligan = Action(type="MULLIGAN", mulligan_entity_ids=())
    chosen = agent.choose_action_with_search(
        _observation(phase="MULLIGAN", hand=()), [mulligan], FakePosition()
    )
    assert chosen == mulligan

    end = Action(type="END_TURN")
    observation = _observation(hand=[{"entity_id": 50, "card_id": "CARD", "cost": 1}])
    assert agent.choose_action(observation, [end]) == end


def test_factory_accepts_only_public_policy_ids():
    assert isinstance(create_agent("heuristic"), object)
    assert isinstance(create_agent("radical", seed=3), RadicalAgent)
    assert isinstance(create_agent("mcts", seed=3), MCTSAgent)
    with pytest.raises(ValueError):
        create_agent("random")
