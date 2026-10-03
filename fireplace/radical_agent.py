"""A bounded, visibility-limited forward-search agent.

``RadicalAgent`` is intentionally built on the value-object boundary.  It
uses a small 0/1 knapsack to arrange known hand cards, then searches attack
sequences when no known card is currently selected.  The search is a
conservative approximation: hidden cards and unresolved choices remain the
controller's responsibility.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .agent_api import ATTACK, END_TURN, PLAY_CARD, Action
from .heuristic_agent import HeuristicAgent
from .search_api import SearchPosition
from .search_scoring import (
    action_type,
    card_cost,
    field,
    integer,
    items,
    number,
    score_observation,
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _entity_id(value: object) -> int | None:
    result = field(value, "entity_id")
    if isinstance(result, bool) or not isinstance(result, int) or result <= 0:
        return None
    return result


def _source_id(action: object) -> int | None:
    result = field(action, "source_entity_id")
    if isinstance(result, bool) or not isinstance(result, int) or result <= 0:
        return None
    return result


def _same_action(left: object, right: object) -> bool:
    try:
        return bool(left == right)
    except Exception:
        return left is right


def _first_matching(actions: Sequence[Action], candidate: object) -> Action | None:
    for action in actions:
        if action is candidate or _same_action(action, candidate):
            return action
    return None


def _safe_actions(position: SearchPosition) -> tuple[Action, ...]:
    try:
        return tuple(position.legal_actions())
    except Exception:
        return ()


def _safe_observation(position: SearchPosition) -> Mapping[str, Any]:
    try:
        value = position.observation()
    except Exception:
        return {}
    return value if isinstance(value, Mapping) else {}


def _safe_terminal(position: SearchPosition) -> bool:
    try:
        return bool(position.terminal)
    except Exception:
        return False


@dataclass(frozen=True)
class _CardChoice:
    card: Mapping[str, Any]
    source_id: int
    cost: int
    card_weight: float
    power_weight: float

    @property
    def objective(self) -> float:
        """The xjw plan value: printed cost plus the configured card weight."""

        return float(self.cost) + self.card_weight


class RadicalAgent:
    """Arrange known plays and search visible attacks with bounded depth."""

    def __init__(
        self,
        seed: int | None = 0,
        *,
        time_budget: float | None = 0.2,
        max_iterations: int = 128,
        max_depth: int = 12,
        enemy_reply: bool = True,
        enemy_reply_depth: int = 2,
        consider_enemy_reply: bool | None = None,
        action_limit: int = 64,
        card_weights: Mapping[str, float] | None = None,
        power_weights: Mapping[str, float] | None = None,
    ):
        if time_budget is not None:
            if isinstance(time_budget, bool) or not isinstance(time_budget, (int, float)):
                raise ValueError("time_budget must be a nonnegative finite number or None")
            if not math.isfinite(float(time_budget)) or float(time_budget) < 0:
                raise ValueError("time_budget must be a nonnegative finite number or None")
        for name, value in (
            ("max_iterations", max_iterations),
            ("max_depth", max_depth),
            ("enemy_reply_depth", enemy_reply_depth),
            ("action_limit", action_limit),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("%s must be a nonnegative integer" % name)
        if action_limit == 0:
            raise ValueError("action_limit must be positive")
        if consider_enemy_reply is not None:
            if not isinstance(consider_enemy_reply, bool):
                raise ValueError("consider_enemy_reply must be a boolean")
            enemy_reply = consider_enemy_reply
        if not isinstance(enemy_reply, bool):
            raise ValueError("enemy_reply must be a boolean")
        if not isinstance(seed, (int, type(None))) or isinstance(seed, bool):
            raise ValueError("seed must be an integer or None")
        self.card_weights = self._validate_weights(card_weights, "card_weights")
        self.power_weights = self._validate_weights(power_weights, "power_weights")

        self.seed = 0 if seed is None else seed
        self.time_budget = None if time_budget is None else float(time_budget)
        self.max_iterations = max_iterations
        self.max_depth = max_depth
        self.enemy_reply = enemy_reply
        self.enemy_reply_depth = enemy_reply_depth
        self.action_limit = action_limit
        self.heuristic = HeuristicAgent()
        self._turn_key: tuple[int | None, int | None] | None = None
        self._turn_actions = 0
        self.last_search_stats: dict[str, Any] = {
            "mode": "initial",
            "iterations": 0,
            "nodes": 0,
            "completed_leaves": 0,
            "selected_cards": [],
            "elapsed": 0.0,
            "time_budget": self.time_budget,
        }

    @staticmethod
    def _validate_weights(
        values: Mapping[str, float] | None,
        name: str,
    ) -> dict[str, float]:
        if values is None:
            return {}
        if not isinstance(values, Mapping):
            raise ValueError("%s must be a mapping" % name)
        result: dict[str, float] = {}
        for key, value in values.items():
            if not isinstance(key, str):
                raise ValueError("%s keys must be strings" % name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("%s values must be finite numbers" % name)
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("%s values must be finite numbers" % name)
            result[key] = number
        return result

    # ------------------------------------------------------------------
    # Public policy boundary
    def choose_action(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
    ) -> Action:
        """Choose from the supplied legal values without an engine handle."""

        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("RadicalAgent received no legal actions")
        forced = self._prepare_action(observation, actions)
        if forced is not None:
            return forced
        if str(field(observation, "phase", "MAIN")).upper() != "MAIN":
            return self._record(self._heuristic_without_unhelpful_coin(observation, actions))
        normal, boosted, coin_action = self._card_plans(observation, actions)
        if coin_action is not None and not self._coin_is_plausibly_usable(observation, boosted):
            coin_action = None
        selected = boosted if coin_action is not None else normal
        choice = coin_action or self._card_action(observation, actions, selected)
        if choice is None:
            choice = self._heuristic_without_unhelpful_coin(observation, actions)
        self.last_search_stats = self._stats(
            mode="knapsack" if selected else "fallback",
            elapsed=0.0,
            selected_cards=[card.source_id for card in selected],
        )
        self.last_search_stats.update({
            "normal_objective": self._plan_objective(normal),
            "boosted_objective": self._plan_objective(boosted),
            "coin_boosted": coin_action is not None,
        })
        return self._record(choice)

    def choose_action_with_search(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
    ) -> Action:
        """Use card planning first, then bounded attack DFS when appropriate."""

        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("RadicalAgent received no legal actions")
        forced = self._prepare_action(observation, actions)
        if forced is not None:
            return forced
        phase = str(field(observation, "phase", "MAIN")).upper()
        if phase != "MAIN":
            return self._record(self._heuristic_without_unhelpful_coin(observation, actions))

        started = time.monotonic()
        normal, boosted, coin_action = self._card_plans(observation, actions)
        if coin_action is not None:
            coin_action = self._validated_coin_plan(
                observation, actions, position, normal, coin_action
            )
        selected = boosted if coin_action is not None else normal
        selected_ids = [choice.source_id for choice in selected]
        self.last_search_stats = self._stats(
            mode="knapsack" if selected else "attack_dfs",
            elapsed=time.monotonic() - started,
            selected_cards=selected_ids,
        )
        self.last_search_stats["normal_objective"] = self._plan_objective(normal)
        self.last_search_stats["boosted_objective"] = self._plan_objective(boosted)
        self.last_search_stats["coin_boosted"] = coin_action is not None
        card_action = coin_action or self._card_action(observation, actions, selected)
        if card_action is not None:
            self.last_search_stats["elapsed"] = time.monotonic() - started
            return self._record(card_action)

        # The bounded search is intentionally disabled by either zero budget.
        # This keeps deterministic tests and emergency callers from paying for
        # speculative transitions when they explicitly request no search.
        if not self._search_enabled():
            self.last_search_stats.update({"mode": "fallback", "elapsed": time.monotonic() - started})
            return self._record(self._heuristic_without_unhelpful_coin(observation, actions))

        attack_action = self._attack_search(observation, actions, position)
        if attack_action is None:
            self.last_search_stats["mode"] = "fallback"
            attack_action = self._heuristic_without_unhelpful_coin(observation, actions)
        self.last_search_stats["elapsed"] = time.monotonic() - started
        return self._record(attack_action)

    def _validated_coin_plan(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
        normal: Sequence[_CardChoice],
        coin_action: Action,
    ) -> Action | None:
        """Check that a speculative Coin actually exposes a useful legal play."""

        del legal_actions
        child = self._transition(position, coin_action)
        if child is None:
            return None
        child_observation = _safe_observation(child)
        child_actions = _safe_actions(child)
        if not child_actions:
            return None
        future_normal, _future_boosted, _future_coin = self._card_plans(
            child_observation, child_actions
        )
        # The boosted hand projection may contain a card whose printed cost
        # fits after the Coin but whose actual effect cannot resolve (for
        # example a full board).  Only the post-Coin *legal* plan counts.
        if not future_normal:
            return None
        if self._plan_objective(future_normal) <= self._plan_objective(normal):
            return None
        return coin_action

    def _coin_is_plausibly_usable(
        self,
        observation: Mapping[str, Any],
        boosted: Sequence[_CardChoice],
    ) -> bool:
        """Reject a known full board where Coin only enables minions."""

        self_view = _mapping(field(observation, "self", {}))
        board = items(self_view.get("board"))
        if len(board) < 7:
            return True
        return any(not self._looks_like_minion(card.card) for card in boosted)

    @staticmethod
    def _looks_like_minion(card: Mapping[str, Any]) -> bool:
        card_type = str(card.get("type") or "").upper()
        if card_type:
            return card_type == "MINION"
        # The public hand projection exposes these stat fields for minions;
        # spells and weapons do not expose max_health/printed_health.
        return "max_health" in card or "printed_health" in card

    def _heuristic_without_unhelpful_coin(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
    ) -> Action:
        self_view = _mapping(field(observation, "self", {}))
        hand = items(self_view.get("hand"))
        by_id = {_entity_id(card): _mapping(card) for card in hand}
        filtered = tuple(
            action
            for action in legal_actions
            if not (
                action_type(action) == PLAY_CARD
                and self._is_coin(by_id.get(_source_id(action), _mapping(action)))
            )
        )
        if filtered:
            return self._heuristic_choice(observation, filtered)
        return self._heuristic_choice(observation, legal_actions)

    # ------------------------------------------------------------------
    # Knapsack and fallback policy
    def select_cards(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
    ) -> tuple[_CardChoice, ...]:
        """Return the currently playable normal plan.

        The Coin-aware boosted comparison is kept in ``_card_plans`` so a
        caller asking only for selected cards never receives an action that is
        not present in its legal action list.
        """

        normal, _boosted, _coin = self._card_plans(observation, legal_actions)
        return normal

    def _card_plans(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
    ) -> tuple[tuple[_CardChoice, ...], tuple[_CardChoice, ...], Action | None]:
        """Build normal/one-extra-mana plans and the optional Coin action."""

        self_view = _mapping(field(observation, "self", {}))
        hand = items(self_view.get("hand"))
        by_id = {_entity_id(card): _mapping(card) for card in hand}
        legal_cards: dict[int, list[Action]] = {}
        coin_actions: list[Action] = []
        for action in legal_actions:
            if action_type(action) != PLAY_CARD:
                continue
            source_id = _source_id(action)
            if source_id is None:
                continue
            card = by_id.get(source_id, _mapping(action))
            if self._is_coin(card):
                coin_actions.append(action)
            else:
                legal_cards.setdefault(source_id, []).append(action)

        # Lightweight fake positions sometimes put card metadata on actions
        # rather than in a hand projection.  Include those action-only cards
        # while retaining the same public-cost rules.
        for source_id, action_list in legal_cards.items():
            if source_id not in by_id:
                by_id[source_id] = _mapping(action_list[0])

        candidates: list[_CardChoice] = []
        for card in hand:
            source_id = _entity_id(card)
            if source_id is None or self._is_coin(_mapping(card)):
                continue
            candidates.append(self._candidate(_mapping(card), source_id))
        for source_id, card in by_id.items():
            if source_id is None or source_id in {_entity_id(card) for card in hand}:
                continue
            if self._is_coin(card):
                continue
            candidates.append(self._candidate(card, source_id))
        candidates = [candidate for candidate in candidates if candidate is not None]

        mana = integer(self_view.get("mana"))
        if mana is None:
            mana = integer(self_view.get("max_mana"))
        mana = max(0, mana or 0)
        normal_candidates = [candidate for candidate in candidates if candidate.source_id in legal_cards]
        normal = self._knapsack(normal_candidates, mana)
        boosted = self._knapsack(candidates, mana + 1)
        normal_objective = self._plan_objective(normal)
        boosted_objective = self._plan_objective(boosted)
        coin = None
        if coin_actions and boosted_objective > normal_objective:
            coin = coin_actions[0]
        return normal, boosted, coin

    def _candidate(self, card: Mapping[str, Any], source_id: int) -> _CardChoice | None:
        cost = card_cost(card)
        if cost is None:
            cost = integer(card.get("cost"))
        if cost is None or cost < 0:
            return None
        card_id = str(card.get("card_id") or card.get("id") or "")
        configured_card_weight = self.card_weights.get(card_id, 1.0)
        observed_card_weight = number(card.get("card_weight"))
        if observed_card_weight is None:
            observed_card_weight = number(card.get("weight"))
        if observed_card_weight is not None:
            configured_card_weight = observed_card_weight
        observed_power_weight = number(card.get("power_weight"))
        power_weight = (
            observed_power_weight
            if observed_power_weight is not None
            else self.power_weights.get(card_id, 1.0)
        )
        return _CardChoice(
            card=card,
            source_id=source_id,
            cost=cost,
            card_weight=float(configured_card_weight),
            power_weight=float(power_weight),
        )

    @staticmethod
    def _plan_objective(plan: Sequence[_CardChoice]) -> float:
        return sum(card.objective for card in plan)

    def _knapsack(self, candidates: Sequence[_CardChoice], budget: int) -> tuple[_CardChoice, ...]:
        if budget < 0 or not candidates:
            return ()
        # Each card's weight is its actual mana cost.  The value being
        # optimized is cost + configured card weight, independent of printed
        # attack/health proxies.
        plans: list[tuple[float, int, tuple[_CardChoice, ...]] | None] = [None] * (budget + 1)
        plans[0] = (0.0, 0, ())
        for candidate in candidates:
            if candidate.cost > budget:
                continue
            for capacity in range(budget, candidate.cost - 1, -1):
                previous = plans[capacity - candidate.cost]
                if previous is None:
                    continue
                objective, weight, chosen = previous
                proposal = (
                    objective + candidate.objective,
                    weight + candidate.cost,
                    chosen + (candidate,),
                )
                current = plans[capacity]
                if current is None or self._plan_key(proposal) > self._plan_key(current):
                    plans[capacity] = proposal
        best = max(
            (plan for plan in plans if plan is not None),
            key=self._plan_key,
            default=(0.0, 0, ()),
        )
        selected = list(best[2])
        # Stable ties preserve the original hand order; the only ordering
        # criterion is the configured power_weight.
        selected.sort(key=lambda card: -card.power_weight)
        return tuple(selected)

    @staticmethod
    def _plan_key(plan: tuple[float, int, tuple[_CardChoice, ...]]) -> tuple[float, int, int]:
        objective, weight, chosen = plan
        return objective, -weight, len(chosen)

    @staticmethod
    def _is_coin(card: Mapping[str, Any]) -> bool:
        card_id = str(card.get("card_id") or card.get("id") or "").upper()
        name = str(card.get("name") or "").lower()
        return card_id in {"GAME_005", "GAME_005T"} or "coin" in name or "硬币" in name

    def _card_action(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        selected: Sequence[_CardChoice],
    ) -> Action | None:
        for card in selected:
            candidates = tuple(
                action
                for action in legal_actions
                if action_type(action) == PLAY_CARD and _source_id(action) == card.source_id
            )
            if not candidates:
                continue
            return self._heuristic_choice(observation, candidates)
        return None

    def _heuristic_choice(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
    ) -> Action:
        actions = tuple(legal_actions)
        try:
            choice = self.heuristic.choose_action(observation, actions)
        except Exception:
            choice = actions[0]
        return _first_matching(actions, choice) or actions[0]

    # ------------------------------------------------------------------
    # Attack DFS
    def _attack_search(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
    ) -> Action | None:
        attacks = tuple(action for action in legal_actions if action_type(action) == ATTACK)
        if not attacks or self.max_depth <= 0:
            return None
        roots = attacks + tuple(
            action for action in legal_actions if action_type(action) == END_TURN
        )
        root_score = score_observation(observation)
        context = {
            "deadline": None if self.time_budget is None else time.monotonic() + self.time_budget,
            "nodes": 0,
            "completed_leaves": 0,
            "root_score": root_score,
        }
        best_action: Action | None = None
        best_value: float | None = None
        for action in roots:
            if self._budget_exhausted(context):
                break
            child = self._transition(position, action)
            if child is None:
                continue
            value, _path = self._dfs_max(child, 1, context)
            if best_value is None or value > best_value:
                best_value = value
                best_action = action
        self.last_search_stats.update(
            {
                "iterations": context["nodes"],
                "nodes": context["nodes"],
                "completed_leaves": context["completed_leaves"],
                "root_actions": len(roots),
                "best_value": best_value,
            }
        )
        return _first_matching(legal_actions, best_action) if best_action is not None else None

    def _dfs_max(self, position: SearchPosition, depth: int, context: dict[str, Any]):
        if self._budget_exhausted(context):
            return score_observation(_safe_observation(position)), ()
        context["nodes"] += 1
        current = score_observation(_safe_observation(position))
        if _safe_terminal(position) or depth >= self.max_depth:
            context["completed_leaves"] += 1
            return self._leaf_value(position, current, depth, context), ()
        actions = tuple(
            action
            for action in _safe_actions(position)
            if action_type(action) in (ATTACK, END_TURN)
        )
        if not actions:
            context["completed_leaves"] += 1
            return self._leaf_value(position, current, depth, context), ()
        best_value: float | None = None
        best_path: tuple[Action, ...] = ()
        for action in actions:
            if self._budget_exhausted(context):
                break
            child = self._transition(position, action)
            if child is None:
                continue
            value, path = self._dfs_max(child, depth + 1, context)
            if best_value is None or value > best_value:
                best_value = value
                best_path = (action,) + path
        if best_value is None:
            context["completed_leaves"] += 1
            return self._leaf_value(position, current, depth, context), ()
        return best_value, best_path

    def _leaf_value(
        self,
        position: SearchPosition,
        current: float,
        depth: int,
        context: dict[str, Any],
    ) -> float:
        del depth
        if not self.enemy_reply:
            return current
        try:
            reply = position.opponent_attack_position()
        except Exception:
            return current
        reply_value, _ = self._dfs_min(reply, 0, context)
        # SearchPosition keeps the original viewer in its observation even
        # while the opponent acts.  The reply therefore minimizes our score;
        # it must be added with the xjw 0.6/0.4 blend, not subtracted twice.
        return 0.6 * current + 0.4 * reply_value

    def _dfs_min(self, position: SearchPosition, depth: int, context: dict[str, Any]):
        if self._budget_exhausted(context):
            return score_observation(_safe_observation(position)), ()
        context["nodes"] += 1
        current = score_observation(_safe_observation(position))
        if _safe_terminal(position) or depth >= self.enemy_reply_depth:
            return current, ()
        actions = tuple(
            action
            for action in _safe_actions(position)
            if action_type(action) in (ATTACK, END_TURN)
        )
        if not actions:
            return current, ()
        best_value: float | None = None
        best_path: tuple[Action, ...] = ()
        for action in actions:
            if self._budget_exhausted(context):
                break
            child = self._transition(position, action)
            if child is None:
                continue
            value, path = self._dfs_min(child, depth + 1, context)
            if best_value is None or value < best_value:
                best_value = value
                best_path = (action,) + path
        return (best_value, best_path) if best_value is not None else (current, ())

    @staticmethod
    def _transition(position: SearchPosition, action: Action) -> SearchPosition | None:
        try:
            return position.transition(action, seed=None)
        except TypeError:
            try:
                return position.transition(action)
            except Exception:
                return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Budget/action guards and diagnostics
    def _search_enabled(self) -> bool:
        return self.max_iterations > 0 and self.max_depth > 0 and (
            self.time_budget is None or self.time_budget > 0
        )

    def _budget_exhausted(self, context: Mapping[str, Any]) -> bool:
        if context.get("nodes", 0) >= self.max_iterations:
            return True
        deadline = context.get("deadline")
        return deadline is not None and time.monotonic() >= deadline

    def _stats(self, *, mode: str, elapsed: float, selected_cards: list[int]):
        # Keep the latest completed search evidence visible when the next
        # live action is a direct knapsack/fallback decision.
        previous_nodes = self.last_search_stats.get("nodes", 0)
        return {
            "mode": mode,
            "iterations": 0,
            "nodes": previous_nodes,
            "completed_leaves": 0,
            "root_actions": 0,
            "selected_cards": selected_cards,
            "elapsed": elapsed,
            "time_budget": self.time_budget,
            "max_iterations": self.max_iterations,
            "max_depth": self.max_depth,
        }

    def _prepare_action(
        self,
        observation: Mapping[str, Any],
        actions: Sequence[Action],
    ) -> Action | None:
        key = self._observation_turn_key(observation)
        if key != self._turn_key:
            self._turn_key = key
            self._turn_actions = 0
        if self._turn_actions < self.action_limit:
            return None
        end = next((action for action in actions if action_type(action) == END_TURN), None)
        if end is None:
            end = self._heuristic_choice(observation, actions)
        return self._record(end)

    @staticmethod
    def _observation_turn_key(observation: Mapping[str, Any]) -> tuple[int | None, int | None]:
        own = _mapping(field(observation, "self", {}))
        hero = _mapping(own.get("hero"))
        return integer(field(observation, "turn")), _entity_id(hero)

    def _record(self, action: Action) -> Action:
        self._turn_actions += 1
        return action


__all__ = ["RadicalAgent"]
