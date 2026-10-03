"""Small, engine-backed sanity checks for a selected targeted spell.

The tactical policy normally trusts the root action chosen by its bounded
search.  A targeted spell is a useful exception: the engine can cheaply
show the result of each target in the same action group, while the ordinary
search may have compared only one of them.  This module deliberately keeps
that check local and conservative.  It sees only :class:`SearchPosition`
observations, uses a fixed transition seed, and returns a value from the
current legal action list.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from .agent_api import END_TURN, PLAY_CARD, Action
from .search_scoring import action_type, field, score_tactical_observation


# These limits are intentionally local to this corrective pass.  They keep a
# crowded board from turning one decision into a second search over every card
# in hand, while allowing the six-target Polymorph case to finish in the
# normal complex-decision budget.
MAX_TARGET_ACTIONS = 32
SIMPLE_TARGET_CHECK_BUDGET = 0.25
COMPLEX_TARGET_CHECK_BUDGET = 0.35
TARGET_CHECK_SEED = 104729


@dataclass(frozen=True)
class TargetCheckResult:
    """The selected legal action and bounded target-check diagnostics."""

    action: Action | None
    mode: str = "skipped"
    evaluated_count: int = 0
    changed: bool = False
    reason: str = "not_run"
    complete: bool = False
    uncertain_count: int = 0
    baseline_score: float | None = None
    selected_score: float | None = None
    best_score: float | None = None

    def as_stats(self) -> dict[str, Any]:
        """Return JSON-safe, finite diagnostics for ``last_search_stats``."""

        return {
            "mode": self.mode,
            "evaluated_count": int(self.evaluated_count),
            "changed": bool(self.changed),
            "reason": self.reason,
            "complete": bool(self.complete),
            "uncertain": bool(self.uncertain_count),
            "uncertain_count": int(self.uncertain_count),
            "baseline_score": _finite_or_none(self.baseline_score),
            "selected_score": _finite_or_none(self.selected_score),
            "best_score": _finite_or_none(self.best_score),
        }


def _finite_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


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


def _safe_items(value: object) -> tuple[object, ...]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return ()
    try:
        return tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()


def _source_card(observation: Mapping[str, Any], source_id: int | None) -> Mapping[str, Any]:
    own = observation.get("self")
    if not isinstance(own, Mapping) or source_id is None:
        return {}
    for card in _safe_items(own.get("hand")):
        if _entity_id(card) == source_id:
            return card if isinstance(card, Mapping) else {}
    return {}


def _source_type(card: Mapping[str, Any]) -> str:
    """Read the public source type, using the local card catalog if omitted.

    The normal observation projection exposes the owner's card identity and
    cost but deliberately omits a redundant ``type`` field.  Looking up that
    already-public identity in the bundled catalog keeps the guard usable on
    real engine observations without reading an engine card object or any
    opponent/private zone.  Small test observations can provide ``type``
    directly.
    """

    raw = card.get("type", card.get("card_type"))
    if raw is None:
        card_id = card.get("card_id")
        if isinstance(card_id, str) and card_id:
            try:
                from . import cards

                record = cards.db.get(card_id)
                raw = getattr(record, "type", None)
            except Exception:
                raw = None
    raw = getattr(raw, "name", getattr(raw, "value", raw))
    return str(raw or "").upper()


def _semantic_group(action: object) -> tuple[object, ...]:
    """Keep source, choose branch, and placement semantics together."""

    return (
        action_type(action),
        field(action, "source_entity_id"),
        field(action, "choose_option_entity_id"),
        field(action, "position"),
    )


def _own_target_ids(observation: Mapping[str, Any]) -> frozenset[int]:
    own = observation.get("self")
    if not isinstance(own, Mapping):
        return frozenset()
    values: list[object] = [own.get("hero"), own.get("weapon")]
    values.extend(_safe_items(own.get("board")))
    values.extend(_safe_items(own.get("secrets")))
    return frozenset(entity_id for value in values if (entity_id := _entity_id(value)) is not None)


def _observation_uncertain(observation: object, position: object) -> bool:
    if isinstance(observation, Mapping) and bool(observation.get("search_uncertain", False)):
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
        return float((clock or time.monotonic)())
    except Exception:
        return float("inf")


def _deadline_reached(deadline: float | None, clock: Callable[[], float] | None) -> bool:
    return deadline is not None and _clock_now(clock) >= deadline


def _is_complex(observation: Mapping[str, Any], candidate_count: int) -> bool:
    """Use the extra local slice for the small crowded-board target groups."""

    if candidate_count > 3:
        return True
    own = observation.get("self")
    opponent = observation.get("opponent")
    own = own if isinstance(own, Mapping) else {}
    opponent = opponent if isinstance(opponent, Mapping) else {}
    return any(
        len(_safe_items(own.get(key))) > limit
        for key, limit in (("hand", 3), ("board", 3))
    ) or len(_safe_items(opponent.get("board"))) > 1


def _safe_transition(position: object, action: Action, seed: int):
    """Transition with the fixed guard seed; unsupported adapters fail closed."""

    try:
        return position.transition(action, seed=seed)
    except Exception:
        return None


def _safe_child_observation(child: object) -> Mapping[str, Any] | None:
    try:
        observation = child.observation()
    except Exception:
        return None
    return observation if isinstance(observation, Mapping) else None


def _unresolved_choice(observation: Mapping[str, Any]) -> bool:
    """A one-step score cannot choose a future branch for an unresolved choice."""

    return bool(observation.get("search_terminal")) and not isinstance(
        observation.get("search_outcome"), str
    )


def _safe_score(observation: Mapping[str, Any]) -> float | None:
    try:
        return _finite_or_none(score_tactical_observation(observation))
    except Exception:
        return None


def _skip(selected: Action | None, reason: str) -> TargetCheckResult:
    return TargetCheckResult(action=selected, reason=reason)


def check_selected_spell_target(
    observation: Mapping[str, Any],
    legal_actions: Sequence[Action],
    position: object,
    selected: Action,
    *,
    deadline: float | None = None,
    max_actions: int = MAX_TARGET_ACTIONS,
    seed: int = TARGET_CHECK_SEED,
    clock: Callable[[], float] | None = None,
) -> TargetCheckResult:
    """Check target alternatives for one selected, targeted hand spell.

    The result is conservative.  Every target in the selected action's
    source/choose/position group must be evaluated by an isolated seeded
    transition before an alternative can replace the selected action.  A
    partial or uncertain group preserves the selected action, except that a
    fully observed harmful self-target may safely fall back to a legal
    ``END_TURN``.

    ``deadline`` is an absolute clock value.  When omitted, a local 0.25s or
    0.35s slice is created from ``clock``/``time.monotonic``.  The helper does
    not inspect engine objects or consume an agent RNG.
    """

    actions = tuple(legal_actions)
    legal_selected = _first_matching(actions, selected)
    selected = legal_selected or selected
    if not actions:
        return _skip(selected, "no_legal_actions")
    if action_type(selected) != PLAY_CARD:
        return _skip(selected, "selected_not_play_card")
    if field(selected, "target_entity_id") is None:
        return _skip(selected, "selected_not_targeted")

    source_id = field(selected, "source_entity_id")
    if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id <= 0:
        return _skip(selected, "selected_source_missing")
    source_card = _source_card(observation, source_id)
    if _source_type(source_card) != "SPELL":
        return _skip(selected, "source_not_known_spell")
    if max_actions <= 0:
        return _skip(selected, "target_limit_zero")

    group = _semantic_group(selected)
    candidates = [
        action
        for action in actions
        if _semantic_group(action) == group
        and field(action, "target_entity_id") is not None
    ]
    if not candidates:
        return _skip(selected, "no_target_group")
    # Always put the selected action first so a short deadline can still tell
    # whether the current self-target is known harmful.
    candidates = [selected] + [action for action in candidates if not _same_action(action, selected)]
    complete_group = len(candidates) <= max_actions
    candidates = candidates[:max_actions]

    if deadline is None:
        deadline = _clock_now(clock) + (
            COMPLEX_TARGET_CHECK_BUDGET
            if _is_complex(observation, len(candidates))
            else SIMPLE_TARGET_CHECK_BUDGET
        )
    if _deadline_reached(deadline, clock):
        return _skip(selected, "deadline_before_check")

    baseline = _safe_score(observation)
    if baseline is None:
        return _skip(selected, "nonfinite_baseline")

    end_turn = next((action for action in actions if action_type(action) == END_TURN), None)
    scores: dict[int, float] = {}
    evaluated_count = 0
    uncertain_count = int(_observation_uncertain(observation, position))
    partial_reason: str | None = None
    for index, action in enumerate(candidates):
        if _deadline_reached(deadline, clock):
            partial_reason = "deadline_during_check"
            break
        child = _safe_transition(position, action, seed)
        if child is None:
            partial_reason = "transition_failed"
            continue
        child_observation = _safe_child_observation(child)
        if child_observation is None:
            partial_reason = "observation_failed"
            continue
        if _observation_uncertain(child_observation, child):
            # The engine marks seeded random/hidden-dependent effects as
            # uncertain for lethal certification.  This guard is a greedy
            # visible one-step comparison, so a finite seeded outcome remains
            # useful; diagnostics make that approximation explicit.  A child
            # that stops at an unresolved CHOOSE boundary is still unsupported
            # because there is no single visible result to compare.
            uncertain_count += 1
        if _unresolved_choice(child_observation):
            partial_reason = "unresolved_choice"
            continue
        score = _safe_score(child_observation)
        if score is None:
            partial_reason = "nonfinite_target_score"
            continue
        scores[index] = score
        evaluated_count += 1
        if index == 0 and score >= baseline:
            # A non-harmful selected target is already protected by the
            # ordinary search's deeper line.  Do not spend the local budget
            # cloning every sibling just to choose a greedier immediate one.
            return TargetCheckResult(
                action=selected,
                mode="checked",
                evaluated_count=evaluated_count,
                reason="selected_not_worse_than_no_action",
                complete=False,
                uncertain_count=uncertain_count,
                baseline_score=baseline,
                selected_score=score,
                best_score=score,
            )

    selected_index = 0
    selected_score = scores.get(selected_index)
    complete = complete_group and partial_reason is None and len(scores) == len(candidates)
    if not complete:
        if partial_reason is None:
            partial_reason = "target_group_truncated"
        if (
            selected_score is not None
            and selected_score < baseline
            and field(selected, "target_entity_id") in _own_target_ids(observation)
            and end_turn is not None
        ):
            return TargetCheckResult(
                action=end_turn,
                mode="changed",
                evaluated_count=evaluated_count,
                changed=not _same_action(end_turn, selected),
                reason="partial_known_harmful_self_target",
                complete=False,
                uncertain_count=uncertain_count,
                baseline_score=baseline,
                selected_score=selected_score,
                best_score=selected_score,
            )
        return TargetCheckResult(
            action=selected,
            mode="partial",
            evaluated_count=evaluated_count,
            reason=partial_reason,
            complete=False,
            uncertain_count=uncertain_count,
            baseline_score=baseline,
            selected_score=selected_score,
            best_score=max(scores.values(), default=None),
        )

    if selected_score is None:
        # This should be covered by ``complete`` above, but retaining the
        # explicit guard keeps a future adapter change fail closed.
        return TargetCheckResult(
            action=selected,
            mode="partial",
            evaluated_count=evaluated_count,
            reason="selected_score_missing",
            complete=False,
            uncertain_count=uncertain_count,
            baseline_score=baseline,
            best_score=max(scores.values(), default=None),
        )

    best_index = selected_index
    best_score = selected_score
    for index in range(1, len(candidates)):
        score = scores[index]
        # Strict comparison deliberately preserves legal-list stability when
        # alternatives tie.  The selected target is known harmful here, so an
        # improving alternative must also beat the no-action baseline before
        # it can replace the deeper MCTS choice.
        if score > best_score:
            best_index = index
            best_score = score

    if best_score > baseline and best_index != selected_index:
        return TargetCheckResult(
            action=candidates[best_index],
            mode="changed",
            evaluated_count=evaluated_count,
            changed=True,
            reason="better_target",
            complete=True,
            uncertain_count=uncertain_count,
            baseline_score=baseline,
            selected_score=selected_score,
            best_score=best_score,
        )
    if end_turn is not None:
        reason = (
            "all_targets_below_no_action"
            if best_score < baseline
            else "all_targets_at_or_below_no_action"
        )
        return TargetCheckResult(
            action=end_turn,
            mode="changed",
            evaluated_count=evaluated_count,
            changed=not _same_action(end_turn, selected),
            reason=reason,
            complete=True,
            uncertain_count=uncertain_count,
            baseline_score=baseline,
            selected_score=selected_score,
            best_score=best_score,
        )
    return TargetCheckResult(
        action=selected,
        mode="checked",
        evaluated_count=evaluated_count,
        reason="selected_best_or_tie",
        complete=True,
        uncertain_count=uncertain_count,
        baseline_score=baseline,
        selected_score=selected_score,
        best_score=best_score,
    )


# Descriptive aliases make the small helper easy to discover without adding a
# second implementation or widening the agent API.
sanity_check_target = check_selected_spell_target
check_target_sanity = check_selected_spell_target


__all__ = [
    "COMPLEX_TARGET_CHECK_BUDGET",
    "MAX_TARGET_ACTIONS",
    "SIMPLE_TARGET_CHECK_BUDGET",
    "TARGET_CHECK_SEED",
    "TargetCheckResult",
    "check_selected_spell_target",
    "check_target_sanity",
    "sanity_check_target",
]
