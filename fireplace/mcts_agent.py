"""A small Monte Carlo tree search policy over :mod:`fireplace.search_api`."""

from __future__ import annotations

import math
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from .agent_api import ATTACK, END_TURN, PLAY_CARD, USE_HERO_POWER, Action
from .radical_agent import (
    RadicalAgent,
    _first_matching,
    _safe_actions,
    _safe_observation,
    _safe_terminal,
)
from .search_api import SearchPosition
from .search_candidates import (
    COMPLEX_CANDIDATE_BUDGET,
    MAX_ROOT_ACTIONS,
    SIMPLE_CANDIDATE_BUDGET,
    CandidatePassResult,
    _action_dict,
    action_key as candidate_action_key,
    evaluate_root_candidates,
)
from .search_scoring import (
    action_type,
    is_terminal_draw,
    is_terminal_loss,
    is_terminal_win,
    score_observation,
    score_tactical_observation,
)
from .search_tactics import (
    REPLY_MAX_DEPTH,
    REPLY_MAX_NODES,
    TACTICAL_MAX_DEPTH,
    TACTICAL_MAX_NODES,
    TacticalSearchResult,
    find_deterministic_lethal,
)
from .search_targeting import TargetCheckResult, check_selected_spell_target


@dataclass
class MCTSNode:
    """One value-object search node.

    ``wins`` is a float because rollouts use a binary reward but callers may
    also inspect or aggregate fractional diagnostics.  Keeping visits as an
    integer and wins as a float avoids accidental floor division in UCT.
    """

    position: SearchPosition
    parent: "MCTSNode | None" = None
    action: Action | None = None
    untried_actions: list[Action] = dataclass_field(default_factory=list)
    children: list["MCTSNode"] = dataclass_field(default_factory=list)
    visits: int = 0
    wins: float = 0.0
    depth: int = 0

    @property
    def untried(self) -> list[Action]:
        return self.untried_actions

    @property
    def root_action(self) -> Action | None:
        node: MCTSNode = self
        while node.parent is not None and node.parent.parent is not None:
            node = node.parent
        return node.action

    def uct(self, exploration: float = math.sqrt(2.0)) -> float:
        """Return the child score used by UCT selection."""

        if self.visits <= 0:
            return float("inf")
        if self.parent is None or self.parent.visits <= 0:
            return self.wins / float(self.visits)
        return self.wins / float(self.visits) + exploration * math.sqrt(
            math.log(float(self.parent.visits)) / float(self.visits)
        )


class MCTSAgent(RadicalAgent):
    """Run bounded UCT rollouts and replan from the live state every action."""

    POLICY_VERSIONS = frozenset({"legacy_v1", "tactical_v2"})
    CONFIG_KEYS = (
        "time_budget",
        "max_iterations",
        "max_depth",
        "exploration",
        "action_limit",
        "complex_time_budget",
    )

    def __init__(
        self,
        seed: int | None = 0,
        *,
        policy_version: str = "legacy_v1",
        time_budget: float | None = 0.2,
        max_iterations: int = 128,
        max_depth: int = 12,
        exploration: float = math.sqrt(2.0),
        action_limit: int = 64,
        complex_time_budget: float | None = 1.0,
    ):
        if not isinstance(policy_version, str) or policy_version not in self.POLICY_VERSIONS:
            values = ", ".join(sorted(self.POLICY_VERSIONS))
            raise ValueError(f"policy_version must be one of {values}")
        if complex_time_budget is not None:
            if (
                isinstance(complex_time_budget, bool)
                or not isinstance(complex_time_budget, (int, float))
                or not math.isfinite(float(complex_time_budget))
                or float(complex_time_budget) < 0
            ):
                raise ValueError(
                    "complex_time_budget must be a nonnegative finite number or None"
                )
        super().__init__(
            seed=seed,
            time_budget=time_budget,
            max_iterations=max_iterations,
            max_depth=max_depth,
            enemy_reply=False,
            action_limit=action_limit,
        )
        if isinstance(exploration, bool) or not isinstance(exploration, (int, float)):
            raise ValueError("exploration must be a nonnegative finite number")
        if not math.isfinite(float(exploration)) or float(exploration) < 0:
            raise ValueError("exploration must be a nonnegative finite number")
        self.exploration = float(exploration)
        self.policy_version = policy_version
        self.complex_time_budget = (
            None if complex_time_budget is None else float(complex_time_budget)
        )
        self.random = random.Random(self.seed)
        self._tactical_score_cache: dict[tuple[str, bool], float] = {}
        self._last_unified_selection_reason = "fallback"

    def export_config(self) -> dict[str, Any]:
        """Return validated constructor kwargs, excluding identity fields.

        Archive metadata stores ``policy_version`` and ``seed`` separately so
        this mapping remains a small, stable set of policy configuration
        fields.  Keep the order aligned with :attr:`CONFIG_KEYS` for readable
        serialized metadata and deterministic tests.
        """

        return {
            key: getattr(self, key)
            for key in self.CONFIG_KEYS
        }

    def _stats(self, *, mode: str, elapsed: float, selected_cards: list[int]):
        """Reset tactical diagnostics on zero-budget/fallback decisions."""

        result = super()._stats(
            mode=mode,
            elapsed=elapsed,
            selected_cards=selected_cards,
        )
        result["policy_version"] = self.policy_version
        if self.policy_version == "tactical_v2":
            result.update(
                {
                    "nodes": 0,
                    "iterations": 0,
                    "completed_leaves": 0,
                    "truncated_lines": 0,
                    "failed_lines": 0,
                    "uncertain_lines": 0,
                    "deterministic_lethal": False,
                    "effective_time_budget": self.time_budget,
                    "target_check": self._target_check_stats("not_run"),
                    "decision_trace": [],
                }
            )
        return result

    @staticmethod
    def _target_check_stats(reason: str) -> dict[str, Any]:
        """Return a stable empty target-check diagnostic block."""

        result = {
            "mode": "skipped",
            "evaluated_count": 0,
            "changed": False,
            "reason": reason,
            "complete": False,
            "uncertain": False,
            "uncertain_count": 0,
            "baseline_score": None,
            "selected_score": None,
            "best_score": None,
        }
        return result

    @classmethod
    def _record_target_check_stats(
        cls,
        stats: dict[str, Any],
        result: TargetCheckResult | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        target_stats = (
            result.as_stats()
            if result is not None
            else cls._target_check_stats(reason or "not_run")
        )
        stats["target_check"] = target_stats

    @staticmethod
    def _preserve_certain_mcts_win(stats: Mapping[str, Any]) -> bool:
        """Do not second-guess a completed, certain terminal winning line."""

        try:
            reward = float(stats.get("best_reward", float("-inf")))
            completed = int(stats.get("completed_leaves", 0))
            best_score = float(stats.get("best_score", float("nan")))
        except (TypeError, ValueError, OverflowError):
            return False
        path = stats.get("best_path")
        if not (completed > 0 and path and math.isfinite(best_score)):
            return False
        if bool(stats.get("search_uncertain", False)):
            return False
        return reward == 1.0

    def _target_sanity_action(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
        selected: Action,
    ) -> Action:
        """Apply one bounded target check after ordinary tactical selection."""

        if self._preserve_certain_mcts_win(self.last_search_stats):
            self._record_target_check_stats(
                self.last_search_stats,
                reason="certain_mcts_win",
            )
            return selected
        result = check_selected_spell_target(
            observation,
            legal_actions,
            position,
            selected,
        )
        self._record_target_check_stats(self.last_search_stats, result)
        chosen = _first_matching(legal_actions, result.action)
        return chosen if chosen is not None else selected

    def choose_action(self, observation, legal_actions):
        """Standalone fallback: use the established heuristic policy."""

        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("MCTSAgent received no legal actions")
        forced = self._prepare_action(observation, actions)
        if forced is not None:
            if self.policy_version == "tactical_v2":
                self.last_search_stats = self._stats(
                    mode="forced",
                    elapsed=0.0,
                    selected_cards=[],
                )
                self.last_search_stats["decision_trace"] = self._single_decision_trace(
                    observation, forced, reason="action_limit_forced"
                )
            return forced
        if self.policy_version == "tactical_v2":
            self.last_search_stats = self._stats(
                mode="fallback",
                elapsed=0.0,
                selected_cards=[],
            )
            selected = self._heuristic_choice(observation, actions)
            self.last_search_stats["decision_trace"] = self._single_decision_trace(
                observation, selected, reason="standalone_fallback"
            )
            return self._record(selected)
        return self._record(self._heuristic_choice(observation, actions))

    def choose_action_with_search(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
    ) -> Action:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("MCTSAgent received no legal actions")
        forced = self._prepare_action(observation, actions)
        if forced is not None:
            if self.policy_version == "tactical_v2":
                self.last_search_stats = self._stats(
                    mode="forced",
                    elapsed=0.0,
                    selected_cards=[],
                )
                self.last_search_stats["decision_trace"] = self._single_decision_trace(
                    observation, forced, reason="action_limit_forced"
                )
            return forced
        phase = str(self._observation_phase(observation)).upper()
        if phase != "MAIN":
            self.last_search_stats = self._stats(
                mode="fallback",
                elapsed=0.0,
                selected_cards=[],
            )
            selected = self._heuristic_choice(observation, actions)
            self.last_search_stats["decision_trace"] = self._single_decision_trace(
                observation, selected, reason="non_main_phase"
            )
            return self._record(selected)
        if not self._search_enabled():
            if self.policy_version != "tactical_v2":
                self.last_search_stats = self._stats(
                    mode="fallback",
                    elapsed=0.0,
                    selected_cards=[],
                )
                return self._record(self._heuristic_choice(observation, actions))
            started = time.monotonic()
            self.last_search_stats = self._stats(
                mode="fallback",
                elapsed=0.0,
                selected_cards=[],
            )
            selected = self._heuristic_choice(observation, actions)
            self.last_search_stats["decision_trace"] = self._single_decision_trace(
                observation, selected, reason="search_disabled"
            )
            self.last_search_stats["elapsed"] = time.monotonic() - started
            return self._record(selected)

        started = time.monotonic()
        tactical_stats: dict[str, Any] | None = None
        if self.policy_version == "tactical_v2":
            tactical_result, tactical_stats = self._tactical_probe(
                observation,
                actions,
                position,
                started,
            )
            if tactical_result.action is not None:
                self.last_search_stats = {
                    "mode": "tactical_lethal",
                    "policy_version": self.policy_version,
                    "iterations": 0,
                    "nodes": tactical_result.nodes,
                    "completed_leaves": tactical_result.completed_leaves,
                    "truncated_lines": tactical_result.truncated_lines,
                    "failed_lines": tactical_result.failed_lines,
                    "root_actions": len(actions),
                    "best_reward": 1.0,
                    "best_score": tactical_result.score,
                    "best_path_length": len(tactical_result.path),
                    "best_path": tactical_result.path,
                    "best_partial_score": tactical_result.best_partial_score,
                    "tactical_nodes": tactical_result.nodes,
                    "tactical_completed_leaves": tactical_result.completed_leaves,
                    "tactical_truncated_lines": tactical_result.truncated_lines,
                    "tactical_failed_lines": tactical_result.failed_lines,
                    "uncertain_branches": tactical_result.uncertain_branches,
                    "deterministic_lethal": tactical_result.deterministic_lethal,
                    "search_uncertain": bool(observation.get("search_uncertain", False)),
                    "elapsed": time.monotonic() - started,
                    "time_budget": self._effective_time_budget(observation, actions),
                    "effective_time_budget": self._effective_time_budget(observation, actions),
                    "max_iterations": self.max_iterations,
                    "max_depth": self.max_depth,
                }
                lethal_row = {
                        "action": tactical_result.action.to_dict(),
                        "source_card_id": None,
                        "target": getattr(tactical_result.action, "target_entity_id", None),
                        "target_entity_id": getattr(tactical_result.action, "target_entity_id", None),
                        "score": self._finite_stat(tactical_result.score),
                        "mean_score": self._finite_stat(tactical_result.score),
                        "samples": [self._finite_stat(tactical_result.score)],
                        "uncertainty": bool(tactical_result.uncertain_branches),
                        "completed": True,
                        "reason": "certified_lethal",
                        "coverage": {
                            "total": len(actions),
                            "considered": 0,
                            "complete": False,
                        },
                        "selected": True,
                    }
                self.last_search_stats["decision_trace"] = {
                    "selected_action": tactical_result.action.to_dict(),
                    "candidates": [lethal_row],
                    "reason": "certified_lethal",
                    "selected_reason": "certified_lethal",
                    "coverage": lethal_row["coverage"],
                    "complete": False,
                    "cutoff": False,
                    "search": self._search_trace(self.last_search_stats),
                }
                self._record_target_check_stats(
                    self.last_search_stats,
                    reason="certified_lethal",
                )
                return self._record(tactical_result.action)

        candidate_pass: CandidatePassResult | None = None
        mcts_started = started
        root_child_cache: Mapping[tuple[Any, ...], object] | None = None
        root_action_order: Sequence[Action] | None = None
        if self.policy_version == "tactical_v2":
            candidate_pass = self._run_candidate_pass(observation, actions, position)
            # The deterministic candidate pass is an explicitly extra slice;
            # MCTS retains its own configured budget and starts its clock after
            # that slice.  legacy_v1 keeps its original start/deadline/RNG.
            mcts_started = time.monotonic()
            root_child_cache = candidate_pass.child_cache
            root_action_order = candidate_pass.root_order
        selected = self._run_mcts(
            observation,
            actions,
            position,
            mcts_started,
            tactical_stats=tactical_stats,
            root_child_cache=root_child_cache,
            root_action_order=root_action_order,
        )
        if selected is None:
            selected = self._heuristic_choice(observation, actions)
            self.last_search_stats["mode"] = "fallback"
        if self.policy_version == "tactical_v2":
            assert candidate_pass is not None
            selected = self._select_unified_candidate(
                observation,
                actions,
                selected,
                candidate_pass,
            )
            self.last_search_stats["candidate_pass"] = candidate_pass.as_stats()
            self.last_search_stats["decision_trace"] = self._decision_trace_for_selection(
                candidate_pass,
                selected,
                selected_reason=self._last_unified_selection_reason,
            )
            self._record_target_check_stats(
                self.last_search_stats,
                reason=self._last_unified_selection_reason,
            )
        self.last_search_stats["elapsed"] = time.monotonic() - started
        return self._record(selected)

    @staticmethod
    def _finite_stat(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    @classmethod
    def _search_trace(cls, stats: Mapping[str, Any]) -> dict[str, Any]:
        """Return the small JSON-safe MCTS summary kept with a decision."""

        raw_path = stats.get("best_path", ())
        try:
            path = tuple(raw_path)[:32]
        except (TypeError, ValueError):
            path = ()
        return {
            "mode": str(stats.get("mode", "unknown")),
            "iterations": int(stats.get("iterations", 0) or 0),
            "completed_leaves": int(stats.get("completed_leaves", 0) or 0),
            "truncated_lines": int(stats.get("truncated_lines", 0) or 0),
            "failed_lines": int(stats.get("failed_lines", 0) or 0),
            "best_score": cls._finite_stat(stats.get("best_score")),
            "best_reward": cls._finite_stat(stats.get("best_reward")),
            "elapsed": cls._finite_stat(stats.get("elapsed")) or 0.0,
            "time_budget": cls._finite_stat(stats.get("time_budget")),
            "best_path": [_action_dict(action) for action in path],
        }

    @staticmethod
    def _single_decision_trace(
        observation: Mapping[str, Any], action: Action, *, reason: str
    ) -> dict[str, Any]:
        """Build a JSON-safe trace for decisions that skip root search."""

        source_id = getattr(action, "source_entity_id", None)
        source_card_id = None
        own = observation.get("self", {}) if isinstance(observation, Mapping) else {}
        own = own if isinstance(own, Mapping) else {}
        hand = own.get("hand", ())
        try:
            cards = tuple(hand)
        except (TypeError, ValueError):
            cards = ()
        for card in cards:
            if getattr(card, "get", lambda *_args: None)("entity_id") == source_id:
                value = card.get("card_id", card.get("id"))
                if isinstance(value, str) and value:
                    source_card_id = value
                break
        action_dict = _action_dict(action)
        target = getattr(action, "target_entity_id", None)
        row = {
            "action": action_dict,
            "source_card_id": source_card_id,
            "target": target,
            "target_entity_id": target,
            "score": None,
            "immediate_score": None,
            "mean_score": None,
            "samples": [],
            "uncertainty": False,
            "completed": False,
            "reason": reason,
            "coverage": {"total": 1, "considered": 1, "complete": False},
            "selected": True,
        }
        return {
            "selected_action": action_dict,
            "candidates": [row],
            "reason": reason,
            "selected_reason": reason,
            "coverage": row["coverage"],
            "complete": False,
            "cutoff": False,
        }

    def _run_candidate_pass(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
    ) -> CandidatePassResult:
        """Run the extra tactical coverage slice with its own deadline."""

        budget = (
            COMPLEX_CANDIDATE_BUDGET
            if self._is_complex_observation(observation, legal_actions)
            else SIMPLE_CANDIDATE_BUDGET
        )
        started = time.monotonic()
        deadline = started + budget
        try:
            return evaluate_root_candidates(
                observation,
                legal_actions,
                position,
                deadline=deadline,
                budget=budget,
                max_roots=MAX_ROOT_ACTIONS,
                clock=time.monotonic,
            )
        except Exception as exc:
            # A candidate pass is additive.  If an adapter cannot provide a
            # detached root, MCTS still receives its ordinary budget and the
            # failure remains visible in diagnostics.
            elapsed = max(0.0, time.monotonic() - started)
            return CandidatePassResult(
                selected_action=None,
                baseline_score=None,
                elapsed=elapsed,
                budget=budget,
                cutoff=False,
                reason="pass_failed:%s" % type(exc).__name__,
                total_roots=len(tuple(legal_actions)),
                considered_roots=0,
            )

    @staticmethod
    def _candidate_entry(
        candidate_pass: CandidatePassResult, action: Action
    ):
        for candidate in candidate_pass.candidates:
            if candidate.action is action or candidate.action == action:
                return candidate
        return None

    def _select_unified_candidate(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        selected: Action,
        candidate_pass: CandidatePassResult,
    ) -> Action:
        """Merge one-step coverage with MCTS without masking deeper combos."""

        del observation, legal_actions
        self._last_unified_selection_reason = "fallback"
        if self._preserve_certain_mcts_win(self.last_search_stats):
            self._last_unified_selection_reason = "certain_mcts_win"
            return selected
        candidate_action = candidate_pass.selected_action
        candidate = (
            self._candidate_entry(candidate_pass, candidate_action)
            if candidate_action is not None
            else None
        )
        if candidate is None or candidate.score is None:
            if int(self.last_search_stats.get("completed_leaves", 0) or 0) > 0:
                self._last_unified_selection_reason = "completed_mcts_line"
            return selected
        baseline = candidate_pass.baseline_score
        mcts_score = self._finite_stat(self.last_search_stats.get("best_score"))
        completed = int(self.last_search_stats.get("completed_leaves", 0) or 0)
        if not candidate.completed and candidate.reason != "choice_boundary":
            # A cutoff, failed endpoint, or unavailable turn-end projection
            # cannot fairly outrank a completed MCTS defense.  The selected
            # action remains the MCTS result (or its explicit heuristic
            # fallback when no completed line exists).
            if completed > 0:
                self._last_unified_selection_reason = "completed_mcts_line"
            return selected
        if action_type(candidate_action) == END_TURN:
            # END is a real projected turn-end score.  It can beat a
            # completed but harmful MCTS line; a better completed/partial
            # combo remains eligible when its score is higher.
            if mcts_score is None or mcts_score <= candidate.score:
                self._last_unified_selection_reason = "end_baseline"
                return candidate_action
            if completed > 0:
                self._last_unified_selection_reason = "completed_mcts_line"
            return selected
        if baseline is None or candidate.score <= baseline:
            if completed > 0:
                self._last_unified_selection_reason = "completed_mcts_line"
            return selected

        # A completed MCTS turn-end score is the fairer comparison for a
        # multi-action combo.  Keep it whenever it reaches at least the
        # one-step candidate's risk-adjusted score.
        if completed > 0 and mcts_score is not None and mcts_score >= candidate.score:
            self._last_unified_selection_reason = "completed_mcts_line"
            return selected
        self._last_unified_selection_reason = "candidate_beats_end"
        return candidate_action

    def _decision_trace_for_selection(
        self,
        candidate_pass: CandidatePassResult,
        selected: Action,
        *,
        selected_reason: str,
    ) -> dict[str, Any]:
        trace = []
        selected_seen = False
        for candidate in candidate_pass.candidates:
            row = candidate.as_trace()
            is_selected = candidate.action is selected or candidate.action == selected
            row["selected"] = bool(is_selected)
            selected_seen = selected_seen or is_selected
            trace.append(row)
        if not selected_seen:
            # MCTS can select a root omitted by a 64-action coverage cap.  Add
            # a JSON-only row so every final decision remains auditable.
            extra = self._single_decision_trace({}, selected, reason="mcts_selected")
            extra["candidates"][0]["coverage"] = {
                "total": candidate_pass.total_roots,
                "considered": candidate_pass.considered_roots,
                "planned": candidate_pass.planned_roots,
                "basic_evaluated": candidate_pass.basic_evaluated_count,
                "projected_completed": candidate_pass.projected_completed_count,
                "complete": False,
            }
            trace.append(extra["candidates"][0])
        return {
            "selected_action": _action_dict(selected),
            "candidates": trace,
            "reason": selected_reason,
            "selected_reason": selected_reason,
            "candidate_pass_reason": candidate_pass.reason,
            "coverage": {
                "total": candidate_pass.total_roots,
                "considered": candidate_pass.considered_roots,
                "planned": candidate_pass.planned_roots,
                "basic_evaluated": candidate_pass.basic_evaluated_count,
                "projected_completed": candidate_pass.projected_completed_count,
                "omitted": max(
                    0, candidate_pass.total_roots - candidate_pass.considered_roots
                ),
                "complete": candidate_pass.complete,
            },
            "complete": candidate_pass.complete,
            "cutoff": bool(candidate_pass.cutoff),
            "search": self._search_trace(self.last_search_stats),
        }

    def _tactical_probe(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
        started: float,
    ) -> tuple[TacticalSearchResult, dict[str, Any]]:
        """Run the independent bounded lethal probe before tactical MCTS."""

        budget = self._effective_time_budget(observation, legal_actions)
        deadline = None if budget is None else started + budget
        result = find_deterministic_lethal(
            observation,
            legal_actions,
            position,
            deadline=deadline,
            max_nodes=TACTICAL_MAX_NODES,
            max_depth=min(self.max_depth, TACTICAL_MAX_DEPTH),
            # Use the same clock object as MCTS.  Tests can replace the
            # module-level monotonic source with a deterministic clock.
            clock=time.monotonic,
        )
        stats = {
            "tactical_nodes": result.nodes,
            "tactical_completed_leaves": result.completed_leaves,
            "tactical_truncated_lines": result.truncated_lines,
            "tactical_failed_lines": result.failed_lines,
            "tactical_best_partial_score": result.best_partial_score,
            "tactical_path": result.path,
            "tactical_deterministic_lethal": result.deterministic_lethal,
            "uncertain_branches": result.uncertain_branches,
            "search_uncertain": bool(observation.get("search_uncertain", False)),
            "tactical_elapsed": time.monotonic() - started,
            "tactical_time_budget": budget,
            "effective_time_budget": budget,
        }
        return result, stats

    @staticmethod
    def _observation_phase(observation: object) -> object:
        if isinstance(observation, Mapping):
            return observation.get("phase", "MAIN")
        return getattr(observation, "phase", "MAIN")

    def _run_mcts(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
        started: float,
        *,
        tactical_stats: Mapping[str, Any] | None = None,
        root_child_cache: Mapping[tuple[Any, ...], object] | None = None,
        root_action_order: Sequence[Action] | None = None,
    ) -> Action | None:
        root_actions = list(legal_actions)
        if not root_actions:
            return None
        tactical = self.policy_version == "tactical_v2"
        if tactical and root_action_order:
            ordered = list(root_action_order)
            ordered.extend(
                action
                for action in root_actions
                if not any(action is item or action == item for item in ordered)
            )
            root_actions = ordered
        if tactical:
            # A seeded rollout often reaches the same visible turn-end board
            # through sibling paths.  Reusing only the scalar score keeps the
            # bounded reply search from cloning that identical state dozens of
            # times while still replanning from the live root every decision.
            self._tactical_score_cache = {}
        budget = (
            self._effective_time_budget(observation, root_actions)
            if tactical
            else self.time_budget
        )
        deadline = None if budget is None else started + budget
        root = MCTSNode(
            position=position,
            untried_actions=list(root_actions),
            depth=0,
        )
        baseline = (
            self._score_position(
                observation,
                position,
                deadline=deadline,
                estimate_reply=False,
            )
            if tactical
            else score_observation(observation)
        )
        uncertain_root = bool(observation.get("search_uncertain", False))
        iterations = 0
        nodes = 0
        transitions = 0
        completed = 0
        truncated = 0
        failed = 0
        uncertain_lines = 0
        best_reward = -1.0
        best_score = float("-inf")
        best_path: tuple[Action, ...] = ()
        best_partial_reward = -1.0
        best_partial_score = float("-inf")
        best_partial_path: tuple[Action, ...] = ()

        while iterations < self.max_iterations and not self._deadline_reached(deadline):
            iterations += 1
            node = root
            path: list[Action] = []

            # Selection: once a node has no pending actions, follow UCT until
            # a leaf or a depth boundary.  Random tie-breaking keeps this a
            # genuine seeded search while preserving deterministic tests.
            while (
                not node.untried_actions
                and node.children
                and node.depth < self.max_depth
                and not self._deadline_reached(deadline)
            ):
                node = self._select_child(node)
                if node.action is not None:
                    path.append(node.action)

            # Expansion: sample one untried action and isolate its child.
            if node.untried_actions and node.depth < self.max_depth and not self._deadline_reached(deadline):
                child = self._expand(node, root_child_cache=root_child_cache)
                if child is not None:
                    node = child
                    nodes += 1
                    transitions += 1
                    if node.action is not None:
                        path.append(node.action)
                else:
                    failed += 1

            # Rollout: random legal continuation, with END_TURN retained as a
            # valid choice.  A line is complete only at a terminal/choice
            # boundary, an explicit END_TURN, or a state with no legal action.
            # A depth/time cutoff is recorded separately as truncated.
            rollout_position = node.position
            rollout_depth = node.depth
            line_complete = _safe_terminal(rollout_position) or action_type(node.action) == "END_TURN"
            line_truncated = False
            while (
                rollout_depth < self.max_depth
                and not _safe_terminal(rollout_position)
                and not self._deadline_reached(deadline)
            ):
                actions = list(_safe_actions(rollout_position))
                if not actions:
                    line_complete = True
                    break
                action = self._random_rollout_action(actions)
                child_position = self._random_transition(rollout_position, action)
                if child_position is None:
                    line_truncated = True
                    break
                if tactical:
                    transitions += 1
                rollout_position = child_position
                rollout_depth += 1
                path.append(action)
                if action_type(action) == "END_TURN":
                    line_complete = True
                    break
                # A terminal result is authoritative even when the transition
                # itself consumed the remaining cooperative time slice.  This
                # is particularly important for an actual lethal on the last
                # engine step.
                if tactical and _safe_terminal(rollout_position):
                    line_complete = True
                    break

            if self._deadline_reached(deadline) and not line_complete:
                line_truncated = True
            if _safe_terminal(rollout_position) and (tactical or not line_truncated):
                line_complete = True
            if rollout_depth >= self.max_depth and not line_complete and not line_truncated:
                line_truncated = True

            final_observation = _safe_observation(rollout_position)
            line_uncertain = uncertain_root or bool(final_observation.get("search_uncertain", False))
            if line_uncertain:
                uncertain_lines += 1
            final_score = (
                self._score_position(
                    final_observation,
                    rollout_position,
                    deadline=deadline,
                    estimate_reply=(line_complete or _safe_terminal(rollout_position)),
                )
                if tactical
                else score_observation(final_observation)
            )
            reward = (
                self._tactical_reward(
                    final_observation,
                    final_score,
                    baseline,
                    uncertain=line_uncertain,
                )
                if tactical
                else (1.0 if final_score > baseline else 0.0)
            )
            candidate_path = tuple(path)
            if (
                reward > best_partial_reward
                or (reward == best_partial_reward and final_score > best_partial_score)
            ):
                best_partial_reward = reward
                best_partial_score = final_score
                best_partial_path = candidate_path
            if line_truncated:
                truncated += 1
                continue
            if not line_complete:
                failed += 1
                continue
            completed += 1
            self._backpropagate(node, reward)
            # Binary reward drives wins; score breaks ties between completed
            # improving lines so an immediate lethal line wins predictably.
            if (
                reward > best_reward
                or (reward == best_reward and final_score > best_score)
            ):
                best_reward = reward
                best_score = final_score
                best_path = candidate_path

        if completed == 0 and not best_partial_path:
            self.last_search_stats = self._stats(
                mode="fallback",
                elapsed=time.monotonic() - started,
                selected_cards=[],
            )
            self.last_search_stats.update({
                "iterations": iterations,
                "nodes": nodes,
                "completed_leaves": 0,
                "truncated_lines": truncated,
                "failed_lines": failed,
            })
            if tactical:
                self.last_search_stats.update(
                    {
                        "policy_version": self.policy_version,
                        "time_budget": budget,
                        "transitions": transitions,
                        "uncertain_lines": uncertain_lines,
                        "search_uncertain": uncertain_root,
                        "deterministic_lethal": False,
                        "effective_time_budget": budget,
                        "best_partial_score": best_partial_score,
                        "best_partial_path": best_partial_path,
                    }
                )
                if tactical_stats:
                    self.last_search_stats.update(dict(tactical_stats))
            return None

        partial_only = completed == 0
        if partial_only:
            best_path = best_partial_path
            best_reward = best_partial_reward
            best_score = best_partial_score

        # A completed rollout's path is authoritative.  If a transition
        # failed before recording a root action, use UCT visits as the stable
        # fallback rather than inventing an action.
        best_root = best_path[0] if best_path else None
        if best_root is None:
            best_child = self._best_root_child(root)
            best_root = best_child.action if best_child is not None else None
        best_root = _first_matching(legal_actions, best_root) if best_root is not None else None

        root_stats = []
        for child in root.children:
            root_stats.append(
                {
                    "action": child.action,
                    "visits": child.visits,
                    "wins": float(child.wins),
                    "mean": child.wins / float(child.visits) if child.visits else 0.0,
                }
            )
        self.last_search_stats = {
            "mode": "mcts_partial" if partial_only else "mcts",
            "iterations": iterations,
            "nodes": nodes,
            "completed_leaves": completed,
            "truncated_lines": truncated,
            "failed_lines": failed,
            "root_actions": len(root_actions),
            "best_reward": best_reward,
            "best_score": best_score,
            "best_path_length": len(best_path),
            "best_path": best_path,
            "root_stats": root_stats,
            "baseline_score": baseline,
            "elapsed": time.monotonic() - started,
            "time_budget": self.time_budget,
            "max_iterations": self.max_iterations,
            "max_depth": self.max_depth,
        }
        if tactical:
            self.last_search_stats.update(
                {
                    "policy_version": self.policy_version,
                    "time_budget": budget,
                    "transitions": transitions,
                    "uncertain_lines": uncertain_lines,
                    "search_uncertain": uncertain_root,
                    "deterministic_lethal": False,
                    "effective_time_budget": budget,
                    "best_partial_score": best_partial_score,
                    "best_partial_path": best_partial_path,
                }
            )
            if tactical_stats:
                self.last_search_stats.update(dict(tactical_stats))
        return best_root

    def _effective_time_budget(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action] | None = None,
    ) -> float | None:
        """Adapt simple/complex tactical budgets without unbounding callers."""

        if self.time_budget is None:
            return None
        if self.time_budget <= 0:
            return 0.0
        if self.complex_time_budget is None or not self._is_complex_observation(
            observation, legal_actions
        ):
            return self.time_budget
        return self.complex_time_budget

    @staticmethod
    def _is_complex_observation(
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action] | None = None,
    ) -> bool:
        own = observation.get("self", {})
        opponent = observation.get("opponent", {})
        if not isinstance(own, Mapping):
            own = {}
        if not isinstance(opponent, Mapping):
            opponent = {}
        hand = own.get("hand", ())
        board = own.get("board", ())
        enemy_board = opponent.get("board", ())
        try:
            hand_count = len(hand) if hand is not None else 0
        except TypeError:
            hand_count = 0
        try:
            board_count = len(board) if board is not None else 0
        except TypeError:
            board_count = 0
        try:
            enemy_board_count = len(enemy_board) if enemy_board is not None else 0
        except TypeError:
            enemy_board_count = 0
        return bool(
            (legal_actions is not None and len(legal_actions) > 12)
            or hand_count > 3
            or board_count > 3
            or enemy_board_count > 1
            or int(opponent.get("secrets_count", 0) or 0) > 0
        )

    def _score_position(
        self,
        observation: Mapping[str, Any],
        position: SearchPosition,
        *,
        deadline: float | None,
        estimate_reply: bool,
    ) -> float:
        """Score a leaf and estimate a reply only at a turn-end boundary."""

        if not estimate_reply:
            return score_tactical_observation(observation)
        cache_key = (repr(observation), True)
        cached = self._tactical_score_cache.get(cache_key)
        if cached is not None:
            return cached
        reply_position = None
        try:
            reply_position = position.opponent_attack_position()
        except Exception:
            reply_position = None
        # A completed turn-end branch deserves its bounded visible threat
        # estimate even when the final transition crossed the main deadline.
        # The reply cap remains finite and does not inspect hidden cards.
        reply_deadline = deadline
        if self._deadline_reached(deadline):
            reply_deadline = None
        result = score_tactical_observation(
            observation,
            reply_position=reply_position,
            max_reply_nodes=REPLY_MAX_NODES,
            max_reply_depth=REPLY_MAX_DEPTH,
            deadline=reply_deadline,
            clock=time.monotonic,
        )
        if len(self._tactical_score_cache) < 256:
            self._tactical_score_cache[cache_key] = result
        return result

    @staticmethod
    def _tactical_reward(
        observation: Mapping[str, Any],
        score: float,
        baseline: float,
        *,
        uncertain: bool,
    ) -> float:
        """Map a tactical leaf to a bounded continuous rollout reward."""

        # A certain actual win is the only path allowed to receive the exact
        # top reward.  Uncertain branches may still guide exploration, but
        # they are never reported as deterministic lethal wins.
        if is_terminal_win(observation):
            return 0.94 if uncertain else 1.0
        if is_terminal_draw(observation):
            return 0.5
        if is_terminal_loss(observation):
            return 0.0
        delta = float(score) - float(baseline)
        # Keep ordinary score differences useful without letting large board
        # values crowd out a real terminal result.  The output is guaranteed
        # to remain inside [0, 1].
        normalized = max(-0.5, min(0.5, delta / 200.0))
        # Keep non-terminal lines strictly below a real certain win, even
        # when a large board delta saturates the shaping term.
        return max(0.05, min(0.95, 0.5 + normalized * 0.9))

    def _select_child(self, node: MCTSNode) -> MCTSNode:
        values = [child.uct(self.exploration) for child in node.children]
        best_value = max(values)
        choices = [child for child, value in zip(node.children, values) if value == best_value]
        return self.random.choice(choices)

    def _expand(
        self,
        node: MCTSNode,
        *,
        root_child_cache: Mapping[tuple[Any, ...], object] | None = None,
    ) -> MCTSNode | None:
        if not node.untried_actions:
            return None
        if node.parent is None and self.policy_version == "tactical_v2":
            # Candidate basic scores establish a stable root priority.  Keep
            # every legal action in the ordered list so negative roots remain
            # available for deeper combinations; ties follow legal order.
            index = 0
        else:
            index = self.random.randrange(len(node.untried_actions))
        action = node.untried_actions.pop(index)
        child_position = None
        if node.parent is None and root_child_cache:
            child_position = root_child_cache.get(candidate_action_key(action))
        if child_position is None:
            child_position = self._random_transition(node.position, action)
        if child_position is None:
            return None
        child = MCTSNode(
            position=child_position,
            parent=node,
            action=action,
            untried_actions=list(_safe_actions(child_position)),
            depth=node.depth + 1,
        )
        node.children.append(child)
        return child

    def _random_rollout_action(self, actions: Sequence[Action]) -> Action:
        if self.policy_version == "legacy_v1":
            return self.random.choice(list(actions))
        choices = list(actions)
        if not choices:
            raise ValueError("cannot roll out without legal actions")
        weights = [self._rollout_weight(action) for action in choices]
        total = sum(weights)
        if total <= 0:
            return self.random.choice(choices)
        draw = self.random.random() * total
        for action, weight in zip(choices, weights):
            draw -= weight
            if draw <= 0:
                return action
        return choices[-1]

    @staticmethod
    def _rollout_weight(action: Action) -> float:
        kind = action_type(action)
        if kind == ATTACK:
            return 3.0
        if kind == PLAY_CARD:
            return 2.2
        if kind == USE_HERO_POWER:
            return 1.8
        if kind == END_TURN:
            # Keep ending the turn possible for exploration, but avoid using
            # it as the overwhelming first random rollout step.
            return 0.25
        return 1.0

    def _random_transition(self, position: SearchPosition, action: Action):
        try:
            return position.transition(action, seed=self.random.randrange(2**31))
        except TypeError:
            try:
                return position.transition(action)
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def _backpropagate(node: MCTSNode, reward: float) -> None:
        current: MCTSNode | None = node
        while current is not None:
            current.visits += 1
            current.wins += float(reward)
            current = current.parent

    @staticmethod
    def _best_root_child(root: MCTSNode) -> MCTSNode | None:
        if not root.children:
            return None
        return max(
            root.children,
            key=lambda child: (
                child.wins / float(child.visits) if child.visits else 0.0,
                child.visits,
            ),
        )

    @staticmethod
    def _deadline_reached(deadline: float | None) -> bool:
        return deadline is not None and time.monotonic() >= deadline


__all__ = ["MCTSAgent", "MCTSNode"]
