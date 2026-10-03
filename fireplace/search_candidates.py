"""Bounded deterministic root-candidate evaluation for tactical search.

The tactical policy has two different jobs at a main-action boundary.  It
must first see the legal root choices (including targeted, area-of-effect,
no-target, and choose branches), then it may spend its normal budget exploring
longer combinations.  This module owns the first, deliberately small pass.

Only value-object observations and :class:`~fireplace.agent_api.Action`
instances cross this boundary.  A fixed transition seed keeps the pass out of
the agent RNG and the live game's RNG.  A successful deterministic child can
be handed to MCTS for its first expansion; uncertain children are sampled for
diagnostics but are never cached or certified as wins.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable

from .agent_api import END_TURN, Action
from .search_scoring import (
    action_type,
    field,
    is_terminal_draw,
    is_terminal_loss,
    is_terminal_win,
    score_tactical_observation,
)
from .search_tactics import REPLY_MAX_DEPTH, REPLY_MAX_NODES


# These limits are policy constants.  They intentionally sit outside MCTS's
# existing configuration so adding tactical coverage does not alter archive
# compatibility or legacy_v1's random/action stream.
MAX_ROOT_ACTIONS = 64
MAX_UNCERTAIN_SAMPLES = 3
SIMPLE_CANDIDATE_BUDGET = 0.35
COMPLEX_CANDIDATE_BUDGET = 0.65

# Deliberately independent from the agent seed and the old target-check seed.
# The engine adapter uses this seed only on an isolated SearchPosition.
CANDIDATE_SEED = 1_000_003
CANDIDATE_SAMPLE_SEEDS = tuple(
    CANDIDATE_SEED + offset for offset in range(MAX_UNCERTAIN_SAMPLES)
)
CANDIDATE_END_SEED_OFFSET = 100_003

# ``None`` means that a very small scalar fake has no continuation API.  This
# sentinel distinguishes that compatibility case from an engine adapter that
# exposes ``legal_actions`` but fails while enumerating it.
_LEGAL_ACTIONS_FAILED = object()


def _finite(value: object) -> float | None:
    """Return a finite float suitable for diagnostics, or ``None``."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _safe_items(value: object) -> tuple[object, ...]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return ()
    try:
        return tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()


def _entity_id(value: object) -> int | None:
    result = field(value, "entity_id")
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


def action_key(action: object) -> tuple[Any, ...]:
    """Return a stable value key for an action, including every branch field."""

    return (
        str(action_type(action)),
        field(action, "source_entity_id"),
        field(action, "target_entity_id"),
        field(action, "choose_option_entity_id"),
        field(action, "position"),
        field(action, "choice_entity_id"),
        tuple(field(action, "mulligan_entity_ids", ()) or ()),
    )


def _action_dict(action: object) -> dict[str, Any]:
    """Serialize an Action without allowing a test double to leak objects."""

    try:
        value = action.to_dict()  # type: ignore[attr-defined]
    except Exception:
        value = {
            "schema_version": 1,
            "type": action_type(action),
        }
        for name in (
            "source_entity_id",
            "target_entity_id",
            "choose_option_entity_id",
            "position",
            "choice_entity_id",
        ):
            item = field(action, name)
            if item is not None:
                value[name] = item
    if not isinstance(value, Mapping):
        return {"schema_version": 1, "type": action_type(action)}
    # Action.to_dict() is already JSON-safe.  Rebuild the small mapping to
    # avoid retaining a custom dict subclass or an attribute-backed object.
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(key, str) and (
            item is None
            or isinstance(item, (str, int, float, bool))
            or isinstance(item, list)
        ):
            result[key] = item
    result.setdefault("schema_version", 1)
    result.setdefault("type", action_type(action))
    return result


def _source_card_id(observation: Mapping[str, Any], action: object) -> str | None:
    raw_source = field(action, "source_entity_id")
    source_id = (
        raw_source
        if isinstance(raw_source, int) and not isinstance(raw_source, bool) and raw_source > 0
        else None
    )
    own = observation.get("self") if isinstance(observation, Mapping) else None
    own = own if isinstance(own, Mapping) else {}
    for card in _safe_items(own.get("hand")):
        if _entity_id(card) != source_id:
            continue
        card_id = field(card, "card_id", field(card, "id"))
        if isinstance(card_id, str) and card_id:
            return card_id
        return None
    return None


def _uncertain(observation: object, position: object) -> bool:
    if isinstance(observation, Mapping) and bool(observation.get("search_uncertain")):
        return True
    for name in ("search_uncertain", "uncertain", "_uncertain"):
        try:
            if bool(getattr(position, name, False)):
                return True
        except Exception:
            return True
    return False


def _clock_now(clock: Callable[[], float] | None) -> float:
    try:
        value = float((clock or time.monotonic)())
    except Exception:
        return float("inf")
    return value if math.isfinite(value) else float("inf")


def _deadline_reached(deadline: float | None, clock: Callable[[], float] | None) -> bool:
    return deadline is not None and _clock_now(clock) >= deadline


def _safe_transition(position: object, action: Action, seed: int):
    try:
        return position.transition(action, seed=seed)
    except TypeError:
        # A tiny fake SearchPosition may predate the seeded protocol.  It is
        # still safe to use for a deterministic unit test; real positions
        # implement the seeded form above.
        try:
            return position.transition(action)
        except Exception:
            return None
    except Exception:
        return None


def _safe_reply_position(child: object):
    try:
        return child.opponent_attack_position()
    except Exception:
        return None


def _explicit_terminal(observation: object) -> bool:
    """Whether the adapter exposed an authoritative terminal outcome."""

    if not isinstance(observation, Mapping):
        return False
    return bool(
        isinstance(observation.get("search_outcome"), str)
        or is_terminal_win(observation)
        or is_terminal_loss(observation)
        or is_terminal_draw(observation)
    )


def _score_basic_observation(
    child: object,
    *,
    deadline: float | None,
    clock: Callable[[], float] | None,
) -> tuple[float | None, str, dict[str, Any], Mapping[str, Any] | None]:
    """Score one transitioned child without spending a reply search."""

    diagnostics: dict[str, Any] = {}
    try:
        observation = child.observation()
    except Exception:
        observation = None
    if not isinstance(observation, Mapping):
        return None, "observation_failed", diagnostics, None
    try:
        score = score_tactical_observation(
            observation,
            deadline=deadline,
            clock=clock,
            diagnostics=diagnostics,
        )
    except Exception:
        return None, "score_failed", diagnostics, observation
    value = _finite(score)
    return (
        (value, "scored", diagnostics, observation)
        if value is not None
        else (None, "nonfinite_score", diagnostics, observation)
    )


def _score_observation(
    child: object,
    action: Action,
    *,
    deadline: float | None,
    clock: Callable[[], float] | None,
) -> tuple[float | None, str, dict[str, Any]]:
    diagnostics: dict[str, Any] = {}
    try:
        observation = child.observation()
    except Exception:
        observation = None
    if not isinstance(observation, Mapping):
        return None, "observation_failed", diagnostics
    reply_position = None
    reply_requested = action_type(action) == END_TURN
    if reply_requested:
        reply_position = _safe_reply_position(child)
    try:
        score = score_tactical_observation(
            observation,
            reply_position=reply_position,
            max_reply_nodes=REPLY_MAX_NODES,
            max_reply_depth=REPLY_MAX_DEPTH,
            deadline=deadline,
            clock=clock,
            diagnostics=diagnostics,
        )
    except Exception:
        return None, "score_failed", diagnostics
    if reply_requested and reply_position is None:
        # A missing visible reply is an adapter limitation.  A real terminal
        # child needs no opponent turn, so distinguish that case explicitly.
        diagnostics["status"] = (
            "not_needed" if _explicit_terminal(observation) else "unavailable"
        )
        diagnostics["approximate"] = not _explicit_terminal(observation)
    value = _finite(score)
    return (
        (value, "scored", diagnostics)
        if value is not None
        else (None, "nonfinite_score", diagnostics)
    )


def _safe_legal_actions(position: object):
    try:
        legal_actions = getattr(position, "legal_actions")
    except AttributeError:
        return None
    except Exception:
        return _LEGAL_ACTIONS_FAILED
    if not callable(legal_actions):
        return _LEGAL_ACTIONS_FAILED
    try:
        actions = legal_actions()
    except Exception:
        return _LEGAL_ACTIONS_FAILED
    try:
        return tuple(actions)
    except (TypeError, ValueError):
        return _LEGAL_ACTIONS_FAILED


def _score_child(
    child: object,
    action: Action,
    *,
    seed: int,
    deadline: float | None,
    clock: Callable[[], float] | None,
    immediate_override: tuple[float | None, str, Mapping[str, Any] | None] | None = None,
) -> tuple[float | None, str, float | None, bool, bool, dict[str, Any], bool]:
    """Return projected score, reason, immediate score, completion, uncertainty.

    The uncertainty flag describes uncertainty discovered while projecting the
    root through its turn-end/reply endpoint.  It is deliberately separate
    from uncertainty on ``child``: a deterministic direct child is safe to
    reuse for MCTS even when its later endpoint requires conservative
    sampling.  The final flag marks an explicit engine terminal outcome.
    """

    if immediate_override is None:
        immediate, immediate_reason, immediate_diagnostics, child_observation = (
            _score_basic_observation(child, deadline=deadline, clock=clock)
        )
    else:
        immediate, immediate_reason, child_observation = immediate_override
        immediate_diagnostics = {}
    if immediate is None:
        return None, immediate_reason, None, False, False, immediate_diagnostics, False
    if not isinstance(child_observation, Mapping):
        try:
            child_observation = child.observation()
        except Exception:
            child_observation = {}
    direct_uncertain = _uncertain(child_observation, child)
    if action_type(action) == END_TURN:
        # Basic scoring above intentionally skipped the reply.  Projection
        # here is the second phase and is shared by every END sample.
        projected, projected_reason, projected_diagnostics = _score_observation(
            child, action, deadline=deadline, clock=clock
        )
        if projected is None:
            return (
                None,
                projected_reason,
                immediate,
                False,
                direct_uncertain
                or bool(projected_diagnostics.get("uncertain", False)),
                projected_diagnostics,
                _explicit_terminal(child_observation),
            )
        endpoint_uncertain = direct_uncertain or bool(
            projected_diagnostics.get("uncertain", False)
        )
        return (
            projected,
            projected_reason,
            immediate,
            True,
            endpoint_uncertain,
            projected_diagnostics,
            _explicit_terminal(child_observation),
        )
    if not isinstance(child_observation, Mapping):
        return (
            None,
            "observation_failed",
            immediate,
            False,
            direct_uncertain,
            immediate_diagnostics,
            False,
        )
    # Discover/choose effects intentionally stop at the engine's choice
    # boundary.  The adapter does not expose a future option here, so scoring
    # the one-step state must remain explicit and incomplete.
    if (
        str(child_observation.get("phase", "")).upper() == "CHOICE"
        or bool(child_observation.get("pending_choice"))
        or bool(child_observation.get("choice_pending"))
    ):
        return immediate, "choice_boundary", immediate, False, True, immediate_diagnostics, False
    if bool(child_observation.get("search_terminal")) and not isinstance(
        child_observation.get("search_outcome"), str
    ):
        return immediate, "choice_boundary", immediate, False, True, immediate_diagnostics, False
    child_actions = _safe_legal_actions(child)
    if child_actions is _LEGAL_ACTIONS_FAILED:
        return (
            None,
            "legal_actions_failed",
            immediate,
            False,
            direct_uncertain,
            immediate_diagnostics,
            _explicit_terminal(child_observation),
        )
    if child_actions is None:
        # Keep minimal test doubles usable, but label their one-step evidence
        # so it is never mistaken for a full turn-end projection.
        return (
            immediate,
            "immediate_only",
            immediate,
            True,
            direct_uncertain,
            immediate_diagnostics,
            _explicit_terminal(child_observation),
        )
    end_action = next(
        (candidate for candidate in child_actions if action_type(candidate) == END_TURN),
        None,
    )
    if end_action is None:
        return (
            immediate,
            "turn_end_unavailable",
            immediate,
            False,
            direct_uncertain,
            immediate_diagnostics,
            _explicit_terminal(child_observation),
        )
    end_child = _safe_transition(child, end_action, seed + CANDIDATE_END_SEED_OFFSET)
    if end_child is None:
        return (
            immediate,
            "turn_end_failed",
            immediate,
            False,
            direct_uncertain,
            immediate_diagnostics,
            False,
        )
    projected, projected_reason, projected_diagnostics = _score_observation(
        end_child, end_action, deadline=deadline, clock=clock
    )
    if projected is None:
        try:
            endpoint_observation = end_child.observation()
        except Exception:
            endpoint_observation = {}
        return (
            immediate,
            projected_reason,
            immediate,
            False,
            _uncertain(endpoint_observation, end_child)
            or bool(projected_diagnostics.get("uncertain", False)),
            projected_diagnostics,
            _explicit_terminal(endpoint_observation),
        )
    try:
        endpoint_observation = end_child.observation()
    except Exception:
        endpoint_observation = {}
    endpoint_uncertain = _uncertain(endpoint_observation, end_child) or bool(
        projected_diagnostics.get("uncertain", False)
    )
    return (
        projected,
        "scored",
        immediate,
        True,
        endpoint_uncertain,
        projected_diagnostics,
        _explicit_terminal(endpoint_observation),
    )


def _is_complex(observation: Mapping[str, Any], action_count: int) -> bool:
    own = observation.get("self", {})
    opponent = observation.get("opponent", {})
    own = own if isinstance(own, Mapping) else {}
    opponent = opponent if isinstance(opponent, Mapping) else {}
    return bool(
        action_count > 12
        or len(_safe_items(own.get("hand"))) > 3
        or len(_safe_items(own.get("board"))) > 3
        or len(_safe_items(opponent.get("board"))) > 1
        or int(opponent.get("secrets_count", 0) or 0) > 0
    )


def _root_priority(observation: Mapping[str, Any], action: Action, index: int) -> tuple[int, int]:
    """Cover END and spell variants before lower-value placement roots."""

    kind = action_type(action)
    if kind == END_TURN:
        return 0, index
    if kind == "PLAY_CARD":
        source_id = field(action, "source_entity_id")
        own = observation.get("self", {})
        own = own if isinstance(own, Mapping) else {}
        for card in _safe_items(own.get("hand")):
            if _entity_id(card) != source_id:
                continue
            card_type = str(field(card, "type", field(card, "card_type", ""))).upper()
            if not card_type:
                card_id = field(card, "card_id", field(card, "id"))
                if isinstance(card_id, str) and card_id:
                    try:
                        from . import cards

                        record = cards.db.get(card_id)
                        raw_type = getattr(record, "type", "")
                        card_type = str(
                            getattr(raw_type, "name", getattr(raw_type, "value", raw_type))
                        ).upper()
                    except Exception:
                        card_type = ""
            if card_type == "SPELL":
                return 1, index
            break
        return 2, index
    if kind == "USE_HERO_POWER":
        return 3, index
    if kind == "ATTACK":
        return 4, index
    return 5, index


@dataclass(frozen=True)
class CandidateEvaluation:
    """One legal root action and its bounded one-step evidence."""

    action: Action
    source_card_id: str | None = None
    target_entity_id: int | None = None
    score: float | None = None
    immediate_score: float | None = None
    mean_score: float | None = None
    samples: tuple[float, ...] = ()
    uncertainty: bool = False
    completed: bool = False
    reason: str = "not_evaluated"
    root_index: int = 0
    root_total: int = 0
    root_considered: int = 0
    selected: bool = False
    reply_diagnostics: Mapping[str, Any] | None = dataclass_field(
        default=None, repr=False, compare=False
    )
    child: object | None = dataclass_field(default=None, repr=False, compare=False)

    def as_trace(self) -> dict[str, Any]:
        score = _finite(self.score)
        immediate_score = _finite(self.immediate_score)
        mean_score = _finite(self.mean_score)
        samples = [value for value in (_finite(item) for item in self.samples) if value is not None]
        raw_reply = self.reply_diagnostics or {}
        reply = {
            "status": str(raw_reply.get("status", "not_requested")),
            "approximate": bool(raw_reply.get("approximate", True)),
            "nodes": int(raw_reply.get("nodes", 0) or 0),
            "completed_leaves": int(raw_reply.get("completed_leaves", 0) or 0),
            "truncated_lines": int(raw_reply.get("truncated_lines", 0) or 0),
            "failed_lines": int(raw_reply.get("failed_lines", 0) or 0),
            "uncertain": bool(raw_reply.get("uncertain", False)),
        }
        coverage = {
            "root_index": int(self.root_index),
            "root_total": int(self.root_total),
            "root_considered": int(self.root_considered),
            # ``root_index`` is legal-action order, while evaluation is
            # priority ordered (END and spells first).  An index comparison
            # therefore mislabels capped low-index actions as covered and a
            # covered END action as omitted.
            "covered": self.immediate_score is not None
            and self.reason not in {"root_cap", "basic_cutoff", "not_evaluated"},
        }
        # Keep the public shape deliberately flat and JSON-safe.
        return {
            "action": _action_dict(self.action),
            "source_card_id": self.source_card_id,
            "target": self.target_entity_id,
            "target_entity_id": self.target_entity_id,
            "score": score,
            "immediate_score": immediate_score,
            "mean_score": mean_score,
            "samples": samples,
            "uncertainty": bool(self.uncertainty),
            "reply": reply,
            "completed": bool(self.completed),
            "reason": str(self.reason),
            "coverage": coverage,
            "selected": bool(self.selected),
        }


@dataclass(frozen=True)
class CandidatePassResult:
    """Result of the bounded deterministic root pass.

    ``child_cache`` intentionally stays out of :meth:`as_stats`: it contains
    isolated engine positions and therefore must never enter JSON diagnostics.
    """

    selected_action: Action | None
    baseline_score: float | None
    candidates: tuple[CandidateEvaluation, ...] = ()
    elapsed: float = 0.0
    budget: float | None = None
    cutoff: bool = False
    reason: str = "not_run"
    total_roots: int = 0
    considered_roots: int = 0
    failed_count: int = 0
    uncertain_count: int = 0
    planned_roots: int = 0
    basic_evaluated_count: int = 0
    basic_complete: bool = False
    projected_completed_count: int = 0
    root_order: tuple[Action, ...] = dataclass_field(
        default_factory=tuple, repr=False, compare=False
    )
    child_cache: Mapping[tuple[Any, ...], object] = dataclass_field(
        default_factory=dict, repr=False, compare=False
    )

    @property
    def decision_trace(self) -> dict[str, Any]:
        return {
            "selected_action": (
                _action_dict(self.selected_action)
                if self.selected_action is not None
                else None
            ),
            "candidates": [candidate.as_trace() for candidate in self.candidates],
            "reason": str(self.reason),
            "coverage": {
                "total": int(self.total_roots),
                "considered": int(self.considered_roots),
                "planned": int(self.planned_roots),
                "basic_evaluated": int(self.basic_evaluated_count),
                "projected_completed": int(self.projected_completed_count),
                "omitted": max(0, int(self.total_roots) - int(self.considered_roots)),
                "complete": self.complete,
            },
            "complete": self.complete,
            "cutoff": bool(self.cutoff),
        }

    @property
    def complete(self) -> bool:
        return bool(
            self.total_roots > 0
            and self.considered_roots == self.total_roots
            and not self.cutoff
            and all(candidate.completed for candidate in self.candidates)
        )

    def as_stats(self) -> dict[str, Any]:
        baseline = _finite(self.baseline_score)
        return {
            "mode": "unified_candidates",
            "elapsed": _finite(self.elapsed) or 0.0,
            "budget": _finite(self.budget),
            "cutoff": bool(self.cutoff),
            "reason": str(self.reason),
            "complete": self.complete,
            "total_roots": int(self.total_roots),
            "considered_roots": int(self.considered_roots),
            "coverage": {
                "total": int(self.total_roots),
                "considered": int(self.considered_roots),
                "omitted": max(0, int(self.total_roots) - int(self.considered_roots)),
                "complete": self.complete,
            },
            "failed_count": int(self.failed_count),
            "uncertain_count": int(self.uncertain_count),
            "planned_roots": int(self.planned_roots),
            "basic_evaluated_count": int(self.basic_evaluated_count),
            "basic_complete": bool(self.basic_complete),
            "projected_completed_count": int(self.projected_completed_count),
            "baseline_score": baseline,
            "selected_action": (
                _action_dict(self.selected_action)
                if self.selected_action is not None
                else None
            ),
            "decision_trace": self.decision_trace,
        }


def _candidate_placeholder(
    action: Action,
    *,
    index: int,
    total: int,
    considered: int,
    reason: str,
    observation: Mapping[str, Any],
) -> CandidateEvaluation:
    return CandidateEvaluation(
        action=action,
        source_card_id=_source_card_id(observation, action),
        target_entity_id=field(action, "target_entity_id"),
        reason=reason,
        root_index=index,
        root_total=total,
        root_considered=considered,
    )


def evaluate_root_candidates(
    observation: Mapping[str, Any],
    legal_actions: Sequence[Action],
    position: object,
    *,
    deadline: float | None = None,
    budget: float | None = None,
    max_roots: int = MAX_ROOT_ACTIONS,
    max_uncertain_samples: int = MAX_UNCERTAIN_SAMPLES,
    seed: int = CANDIDATE_SEED,
    clock: Callable[[], float] | None = None,
) -> CandidatePassResult:
    """Evaluate roots in two bounded deterministic phases.

    Phase one transitions each cap-selected root once and records its direct
    tactical score.  Phase two spends the remaining slice on END/reply
    projection and conservative uncertainty samples.  Keeping those phases
    separate ensures a large spell-target action set still receives useful
    basic coverage before one random AoE branch consumes the pass.
    """

    started = _clock_now(clock)
    if deadline is None and budget is not None:
        deadline = started + max(0.0, float(budget))
    actions = tuple(legal_actions)
    total = len(actions)
    if max_roots <= 0 or not actions:
        root_score = _finite(score_tactical_observation(observation))
        return CandidatePassResult(
            selected_action=None,
            baseline_score=root_score,
            elapsed=max(0.0, _clock_now(clock) - started),
            budget=budget,
            reason="no_legal_actions" if not actions else "root_cap_zero",
            total_roots=total,
            planned_roots=0,
            root_order=actions,
        )

    cap = min(int(max_roots), total)
    indexed = list(enumerate(actions))
    ordered_indices = [
        index
        for index, _action in sorted(
            indexed, key=lambda pair: _root_priority(observation, pair[1], pair[0])
        )
    ]
    selected_indices = set(ordered_indices[:cap])
    end_index = next(
        (index for index, action in indexed if action_type(action) == END_TURN),
        None,
    )
    if end_index is not None and end_index not in selected_indices:
        selected_indices.remove(max(selected_indices))
        selected_indices.add(end_index)
    eval_indices = sorted(
        selected_indices,
        key=lambda index: _root_priority(observation, actions[index], index),
    )
    planned_roots = len(eval_indices)
    uncertain_limit = max(1, min(int(max_uncertain_samples), MAX_UNCERTAIN_SAMPLES))
    basic_deadline = None
    if deadline is not None:
        basic_deadline = started + max(0.0, deadline - started) * 0.60

    candidate_by_index: dict[int, CandidateEvaluation] = {}
    prepared: dict[int, dict[str, Any]] = {}
    transition_cache: dict[tuple[Any, ...], object] = {}
    failed_count = 0
    uncertain_count = 0
    uncertain_indices: set[int] = set()
    cutoff = False
    phase1_interrupted = False
    attempted_indices: set[int] = set()
    basic_evaluated_count = 0
    root_uncertain = _uncertain(observation, position)

    # Phase one: one deterministic transition and one no-reply score per
    # selected root.  Spells are before minions by ``_root_priority``.
    for index in eval_indices:
        action = actions[index]
        if _deadline_reached(deadline, clock) or _deadline_reached(
            basic_deadline, clock
        ):
            phase1_interrupted = True
            cutoff = True
            break
        attempted_indices.add(index)
        child = _safe_transition(position, action, int(seed))
        if child is None:
            failed_count += 1
            candidate_by_index[index] = _candidate_placeholder(
                action,
                index=index,
                total=total,
                considered=0,
                reason="transition_failed",
                observation=observation,
            )
            continue
        try:
            child_observation = child.observation()
        except Exception:
            child_observation = {}
        direct_uncertain = root_uncertain or _uncertain(child_observation, child)
        # A deterministic direct child is reusable even if later endpoint
        # scoring is uncertain or is cut off.  Uncertain children remain
        # available for this pass only.
        if not direct_uncertain:
            transition_cache[action_key(action)] = child
        basic_score, basic_reason, basic_diagnostics, basic_observation = (
            _score_basic_observation(child, deadline=basic_deadline, clock=clock)
        )
        if basic_score is not None:
            basic_evaluated_count += 1
        else:
            failed_count += 1
        prepared[index] = {
            "child": child,
            "observation": basic_observation
            if isinstance(basic_observation, Mapping)
            else child_observation,
            "direct_uncertain": direct_uncertain,
            "basic_score": basic_score,
            "basic_reason": basic_reason,
            "basic_diagnostics": basic_diagnostics,
        }
        # A full cooperative deadline reached by the final transition still
        # makes this ordinary row incomplete.  An authoritative terminal
        # child is the exception: its outcome is already final.  The basic
        # slice alone may expire after the final root without becoming a
        # global cutoff because all planned basic roots were attempted.
        terminal_child = _explicit_terminal(
            basic_observation if isinstance(basic_observation, Mapping) else child_observation
        )
        full_deadline_reached = _deadline_reached(deadline, clock)
        basic_deadline_reached = _deadline_reached(basic_deadline, clock)
        if full_deadline_reached and not terminal_child:
            phase1_interrupted = True
            cutoff = True
            break
        if index != eval_indices[-1] and (
            full_deadline_reached or basic_deadline_reached
        ):
            phase1_interrupted = True
            cutoff = True
            break

    basic_attempt_complete = len(attempted_indices) == planned_roots
    basic_complete = (
        basic_attempt_complete
        and not phase1_interrupted
        and basic_evaluated_count == planned_roots
    )
    # Count direct uncertainty once even when projection cannot start.  Later
    # endpoint/sample uncertainty is added to this set so skipped rows and
    # projected rows share one stable count.
    uncertain_indices.update(
        index
        for index, data in prepared.items()
        if bool(data.get("direct_uncertain"))
    )
    uncertain_count = len(uncertain_indices)

    # Any root not reached by phase one is explicit.  Its immediate score is
    # absent, so later diagnostics cannot imply that the cap was fully covered.
    for index in eval_indices:
        if index in candidate_by_index or index in prepared:
            continue
        candidate_by_index[index] = _candidate_placeholder(
            actions[index],
            index=index,
            total=total,
            considered=basic_evaluated_count,
            reason="cutoff" if phase1_interrupted else "not_evaluated",
            observation=observation,
        )

    # Phase two: project after the spell portion of basic coverage has had its
    # chance.  A basic-phase cutoff can still leave useful time in the shared
    # budget; project the roots already prepared in that case, but never let a
    # minion/hero prefix consume the projection slice while an unattempted
    # spell variant remains.  ``cutoff`` is global coverage metadata, so it
    # must not make an otherwise completed prepared row incomplete.
    projected_completed_count = 0
    basic_spell_complete = all(
        index in attempted_indices
        for index in eval_indices
        if _root_priority(observation, actions[index], index)[0] == 1
    )
    phase2_allowed = bool(prepared) and not _deadline_reached(deadline, clock) and (
        not phase1_interrupted or basic_spell_complete
    )
    if phase2_allowed:
        for index in eval_indices:
            data = prepared.get(index)
            if data is None:
                continue
            action = actions[index]
            basic_score = data["basic_score"]
            basic_reason = data["basic_reason"]
            child = data["child"]
            child_observation = data["observation"]
            direct_uncertain = bool(data["direct_uncertain"])
            if _deadline_reached(deadline, clock):
                cutoff = True
                candidate_by_index[index] = CandidateEvaluation(
                    action=action,
                    source_card_id=_source_card_id(observation, action),
                    target_entity_id=field(action, "target_entity_id"),
                    immediate_score=basic_score,
                    reason="cutoff",
                    root_index=index,
                    root_total=total,
                    root_considered=basic_evaluated_count,
                    uncertainty=direct_uncertain,
                    child=child if not direct_uncertain else None,
                )
                continue

            samples: list[float] = []
            immediate_samples: list[float] = []
            uncertain = direct_uncertain
            reason = "scored" if basic_score is not None else basic_reason
            reply_diagnostics: dict[str, Any] = {}
            row_cutoff = False
            first_child = child
            sample_count = uncertain_limit if uncertain else 1
            sample_index = 0
            while sample_index < sample_count:
                if _deadline_reached(deadline, clock):
                    cutoff = True
                    row_cutoff = True
                    reason = "cutoff"
                    break
                if sample_index == 0:
                    sample_child = first_child
                    sample_observation = child_observation
                    sample_basic = basic_score
                    sample_basic_reason = basic_reason
                else:
                    sample_seed = int(seed) + sample_index
                    sample_child = _safe_transition(position, action, sample_seed)
                    if sample_child is None:
                        failed_count += 1
                        reason = "sample_failed" if samples else "transition_failed"
                        break
                    try:
                        sample_observation = sample_child.observation()
                    except Exception:
                        sample_observation = {}
                    sample_direct_uncertain = _uncertain(
                        sample_observation, sample_child
                    )
                    direct_uncertain = direct_uncertain or sample_direct_uncertain
                    uncertain = uncertain or sample_direct_uncertain
                    (
                        sample_basic,
                        sample_basic_reason,
                        _sample_basic_diagnostics,
                        sample_observation,
                    ) = _score_basic_observation(
                        sample_child, deadline=deadline, clock=clock
                    )
                    if sample_basic is None:
                        failed_count += 1
                        reason = sample_basic_reason
                        break
                if sample_basic is None:
                    reason = sample_basic_reason
                    break
                (
                    score,
                    score_reason,
                    immediate_value,
                    score_completed,
                    projected_uncertain,
                    projected_diagnostics,
                    endpoint_terminal,
                ) = _score_child(
                    sample_child,
                    action,
                    seed=int(seed) + sample_index,
                    deadline=deadline,
                    clock=clock,
                    immediate_override=(
                        sample_basic,
                        sample_basic_reason,
                        sample_observation,
                    ),
                )
                uncertain = uncertain or projected_uncertain
                if projected_diagnostics:
                    reply_diagnostics = dict(projected_diagnostics)
                if score_reason == "legal_actions_failed":
                    failed_count += 1
                    reason = score_reason
                    break
                if _deadline_reached(deadline, clock) and not endpoint_terminal:
                    cutoff = True
                    row_cutoff = True
                    reason = "cutoff"
                if score is None:
                    reason = score_reason
                    failed_count += 1
                    break
                samples.append(score)
                immediate_samples.append(sample_basic)
                if not score_completed:
                    reason = score_reason
                if uncertain and sample_count == 1:
                    sample_count = uncertain_limit
                sample_index += 1
                if len(samples) >= sample_count:
                    break

            if uncertain and index not in uncertain_indices:
                uncertain_indices.add(index)
                uncertain_count += 1
            score = min(samples) if samples else None
            mean_score = sum(samples) / len(samples) if samples else None
            immediate_score = (
                min(immediate_samples)
                if immediate_samples
                else _finite(basic_score)
            )
            completed = bool(samples) and not row_cutoff and len(samples) >= sample_count
            if reason in {"choice_boundary", "turn_end_failed", "turn_end_unavailable"}:
                completed = False
            if uncertain and sample_count > 1 and len(samples) < sample_count:
                completed = False
                if reason == "scored":
                    reason = "sample_incomplete"
            if completed and reason == "scored" and uncertain:
                reason = "uncertain_sampled"
            if not completed and reason == "scored":
                reason = "incomplete"
            if completed:
                projected_completed_count += 1
            candidate_by_index[index] = CandidateEvaluation(
                action=action,
                source_card_id=_source_card_id(observation, action),
                target_entity_id=field(action, "target_entity_id"),
                score=score,
                immediate_score=immediate_score,
                mean_score=mean_score,
                samples=tuple(samples),
                uncertainty=uncertain,
                completed=completed,
                reason=reason,
                root_index=index,
                root_total=total,
                root_considered=basic_evaluated_count,
                reply_diagnostics=reply_diagnostics,
                child=first_child if not direct_uncertain else None,
            )

    # Rows omitted by the root cap remain explicit and do not inflate actual
    # basic coverage.  They are kept in legal order for stable trace output.
    for index, action in indexed:
        if index in candidate_by_index or index in prepared:
            continue
        candidate_by_index[index] = _candidate_placeholder(
            action,
            index=index,
            total=total,
            considered=basic_evaluated_count,
            reason="root_cap",
            observation=observation,
        )

    # If phase two was skipped after a successful basic transition, retain the
    # direct score in its row for diagnostics and root coverage.
    for index, data in prepared.items():
        if index in candidate_by_index:
            continue
        candidate_by_index[index] = CandidateEvaluation(
            action=actions[index],
            source_card_id=_source_card_id(observation, actions[index]),
            target_entity_id=field(actions[index], "target_entity_id"),
            immediate_score=data["basic_score"],
            reason="cutoff" if cutoff else data["basic_reason"],
            root_index=index,
            root_total=total,
            root_considered=basic_evaluated_count,
            uncertainty=bool(data["direct_uncertain"]),
            child=data["child"] if not data["direct_uncertain"] else None,
        )

    candidates = tuple(candidate_by_index[index] for index in range(total))
    end_candidate = (
        candidates[end_index] if end_index is not None else None
    )
    baseline = (
        end_candidate.score
        if end_candidate is not None and end_candidate.score is not None
        else (end_candidate.immediate_score if end_candidate is not None else None)
    )
    if baseline is None:
        baseline = _finite(score_tactical_observation(observation))
    baseline_complete = bool(end_candidate is not None and end_candidate.completed)
    selected: Action | None = None
    selection_reason = "no_completed_candidate"
    if baseline_complete and baseline is not None:
        best: CandidateEvaluation | None = None
        for candidate in candidates:
            if (
                end_candidate is not None
                and candidate.action is end_candidate.action
            ):
                continue
            if (
                candidate.score is None
                or candidate.score <= baseline
                or candidate.reason
                in {
                    "cutoff",
                    "basic_cutoff",
                    "root_cap",
                    "transition_failed",
                    "sample_failed",
                    "observation_failed",
                    "score_failed",
                    "nonfinite_score",
                    "legal_actions_failed",
                    "turn_end_unavailable",
                }
            ):
                continue
            if best is None or best.score is None or candidate.score > best.score:
                best = candidate
        if best is not None:
            selected = best.action
            selection_reason = (
                "candidate_beats_end"
                if best.completed
                else "candidate_beats_end_partial"
            )
        elif end_candidate is not None:
            selected = end_candidate.action
            selection_reason = "end_baseline"
    elif end_candidate is not None:
        selected = end_candidate.action
        selection_reason = "end_incomplete_baseline"
    elif candidates:
        selected = candidates[0].action

    actual_considered = basic_evaluated_count
    if selected is not None:
        candidates = tuple(
            CandidateEvaluation(
                **{
                    **candidate.__dict__,
                    "selected": _same_action(candidate.action, selected),
                    "root_considered": actual_considered,
                }
            )
            for candidate in candidates
        )
    elapsed = max(0.0, _clock_now(clock) - started)
    if cutoff and selection_reason == "no_completed_candidate":
        selection_reason = "cutoff"

    # MCTS uses this stable order for tactical root expansion.  Finite basic
    # scores lead; ties and unavailable scores retain original legal order.
    immediate_by_index = {
        index: _finite(candidate_by_index[index].immediate_score)
        for index in range(total)
    }
    root_order = tuple(
        actions[index]
        for index in sorted(
            range(total),
            key=lambda index: (
                0 if immediate_by_index[index] is not None else 1,
                -(immediate_by_index[index] or 0.0)
                if immediate_by_index[index] is not None
                else 0.0,
                index,
            ),
        )
    )
    return CandidatePassResult(
        selected_action=selected,
        baseline_score=baseline,
        candidates=candidates,
        elapsed=elapsed,
        budget=budget,
        cutoff=cutoff,
        reason=selection_reason,
        total_roots=total,
        considered_roots=actual_considered,
        failed_count=failed_count,
        uncertain_count=uncertain_count,
        planned_roots=planned_roots,
        basic_evaluated_count=basic_evaluated_count,
        basic_complete=basic_complete,
        projected_completed_count=projected_completed_count,
        root_order=root_order,
        child_cache=transition_cache,
    )


__all__ = [
    "CANDIDATE_SAMPLE_SEEDS",
    "CANDIDATE_SEED",
    "COMPLEX_CANDIDATE_BUDGET",
    "MAX_ROOT_ACTIONS",
    "MAX_UNCERTAIN_SAMPLES",
    "SIMPLE_CANDIDATE_BUDGET",
    "CandidateEvaluation",
    "CandidatePassResult",
    "action_key",
    "evaluate_root_candidates",
]
