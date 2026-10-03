"""Small, visibility-limited tactical searches shared by search agents.

The engine-backed search position is deliberately the only object this module
knows how to transition.  A tactical result is therefore a value object: the
caller receives a current :class:`~fireplace.agent_api.Action`, rather than a
cached engine object or a plan that can become stale after the controller acts.

Two helpers live here instead of in :mod:`fireplace.mcts_agent`:

* :func:`find_deterministic_lethal` is a bounded depth-first probe used before
  MCTS.  It certifies a line only when every observation in the line remains
  deterministic and the detached position reports an actual victory.
* :func:`evaluate_visible_opponent_reply` estimates the visible attack reply
  after a turn-ending line.  It is intentionally shallow and non-exhaustive;
  hidden cards, Secrets, and random draws are never guessed here.

Both searches use cooperative node/deadline checks.  A transition that reaches
an actual terminal state is inspected before a crossed deadline is applied so
that a real lethal is not discarded merely because the final engine step was
slow.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .agent_api import ATTACK, END_TURN, PLAY_CARD, USE_HERO_POWER, Action
from .radical_agent import _safe_actions, _safe_observation, _safe_terminal
from .search_scoring import (
    action_type, is_terminal_win, score_observation, score_tactical_observation,
)


# These are intentionally fixed tactical caps.  The public MCTS configuration
# remains small enough for archive compatibility; changing these constants is
# a code-level policy change rather than a per-match unbounded search knob.
TACTICAL_MAX_NODES = 64
TACTICAL_MAX_DEPTH = 8
# A reply estimate is intentionally smaller than the current-player search,
# while still reaching the third or fourth visible attacker.  The node cap is
# the primary guard; depth eight lets a board of ready attackers be evaluated
# when the action ordering follows the engine's legal taunt targets.
REPLY_MAX_NODES = 32
REPLY_MAX_DEPTH = 8


def _field(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> tuple[object, ...]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return ()
    try:
        return tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()


def _entity_id(value: object) -> int | None:
    result = _field(value, "entity_id")
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


def _hero(observation: Mapping[str, Any] | object, side: str) -> Mapping[str, Any]:
    value = _mapping(_field(observation, side, {}))
    return _mapping(value.get("hero"))


def _raw_health(hero: object) -> int | None:
    value = _field(hero, "health")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result


def _is_lethal_observation(observation: Mapping[str, Any] | object) -> bool:
    """Return true only for an enemy-dead/own-alive public observation."""

    return is_terminal_win(observation)


def _is_uncertain(observation: Mapping[str, Any] | object, position: object = None) -> bool:
    """Read uncertainty markers without requiring a concrete engine class."""

    if bool(_field(observation, "search_uncertain", False)):
        return True
    for name in ("search_uncertain", "uncertain", "_uncertain"):
        marker = getattr(position, name, False)
        if marker:
            return True
    return False


def _clock_now(clock: Callable[[], float] | None) -> float:
    return float((clock or time.monotonic)())


def _deadline_reached(deadline: float | None, clock: Callable[[], float] | None) -> bool:
    return deadline is not None and _clock_now(clock) >= deadline


def _source_card(observation: Mapping[str, Any], action: object) -> Mapping[str, Any]:
    own = _mapping(observation.get("self"))
    source = _field(action, "source_entity_id")
    for card in _items(own.get("hand")):
        if _entity_id(card) == source:
            return _mapping(card)
    return {}


def _hero_id(observation: Mapping[str, Any], side: str) -> int | None:
    return _entity_id(_hero(observation, side))


def _is_coin(observation: Mapping[str, Any], action: object) -> bool:
    card = _source_card(observation, action)
    card_id = str(card.get("card_id") or card.get("id") or "").upper()
    name = str(card.get("name") or "").lower()
    return card_id in {"GAME_005", "GAME_005T"} or "coin" in name or "硬币" in name


def _action_priority(observation: Mapping[str, Any], action: object) -> tuple[float, int]:
    """Order likely tactical actions while retaining legal-list stability.

    This is a search ordering hint only.  Rules such as taunt, Divine Shield,
    Freeze, and attack readiness remain the engine's responsibility because
    the action list and every transition come from ``SearchPosition``.
    """

    kind = action_type(action)
    enemy_hero_id = _hero_id(observation, "opponent")
    target_id = _field(action, "target_entity_id")
    face = target_id == enemy_hero_id and enemy_hero_id is not None
    if kind == ATTACK:
        # Face attacks expose lethal first; trades remain useful when taunt or
        # a board clear makes them necessary.
        return (100.0 if face else 85.0, 0)
    if kind == PLAY_CARD:
        if _is_coin(observation, action):
            # Coin is retained near the front because it can unlock the only
            # legal damage/taunt play, but direct plays still win ties.
            return (72.0, 0)
        if face:
            return (96.0, 0)
        return (78.0, 0)
    if kind == USE_HERO_POWER:
        return (76.0 if face else 70.0, 0)
    if kind == END_TURN:
        # Keep END_TURN available for a complete reply line, while avoiding
        # premature termination during the bounded lethal probe.
        return (1.0, 0)
    return (40.0, 0)


def _ordered_actions(
    observation: Mapping[str, Any], actions: Sequence[Action], *, limit: int | None = None
) -> tuple[Action, ...]:
    indexed = list(enumerate(actions))
    indexed.sort(key=lambda pair: (-_action_priority(observation, pair[1])[0], pair[0]))
    ordered = tuple(action for _index, action in indexed)
    return ordered if limit is None else ordered[: max(0, int(limit))]


def _ordered_reply_actions(
    observation: Mapping[str, Any], actions: Sequence[Action]
) -> tuple[Action, ...]:
    """Prioritize an opponent attack aimed at our visible hero.

    ``SearchPosition.opponent_attack_position`` keeps the original viewer in
    its observations, so the attacker's face target is ``self.hero`` rather
    than ``opponent.hero``.  Engine legal actions already enforce taunt,
    Freeze, Divine Shield, and other target rules; this only orders them.
    """

    own_hero_id = _hero_id(observation, "self")
    indexed = list(enumerate(actions))

    def key(pair):
        index, action = pair
        kind = action_type(action)
        target = _field(action, "target_entity_id")
        if kind == ATTACK and target == own_hero_id:
            priority = 100.0
        elif kind == ATTACK:
            priority = 85.0
        elif kind == END_TURN:
            priority = 1.0
        else:
            priority = 0.0
        return -priority, index

    indexed.sort(key=key)
    return tuple(action for _index, action in indexed)


def _transition(position: object, action: Action, *, seed: int | None = None):
    try:
        return position.transition(action, seed=seed)
    except TypeError:
        try:
            return position.transition(action)
        except Exception:
            return None
    except Exception:
        return None


@dataclass(frozen=True)
class TacticalSearchResult:
    """Diagnostics and the first action of a bounded tactical search."""

    action: Action | None = None
    path: tuple[Action, ...] = ()
    score: float = float("-inf")
    best_partial_score: float = float("-inf")
    nodes: int = 0
    completed_leaves: int = 0
    truncated_lines: int = 0
    failed_lines: int = 0
    deterministic_lethal: bool = False
    uncertain_branches: int = 0

    @property
    def found(self) -> bool:
        return self.action is not None


def find_deterministic_lethal(
    observation: Mapping[str, Any],
    legal_actions: Sequence[Action],
    position: object,
    *,
    deadline: float | None = None,
    max_nodes: int = TACTICAL_MAX_NODES,
    max_depth: int = TACTICAL_MAX_DEPTH,
    clock: Callable[[], float] | None = None,
) -> TacticalSearchResult:
    """Find a current legal action with a visible, deterministic lethal line.

    The helper performs no plan caching.  Callers invoke it for every fresh
    decision, then execute only the returned current root action.  A branch
    carrying ``search_uncertain`` is explored for diagnostics but cannot be
    certified as deterministic lethal.
    """

    roots = _ordered_actions(observation, tuple(legal_actions), limit=max_nodes)
    if not roots or max_nodes <= 0 or max_depth <= 0:
        return TacticalSearchResult()

    counters = {
        "nodes": 0,
        "completed": 0,
        "truncated": 0,
        "failed": 0,
        "uncertain": 0,
    }
    best_partial_score = score_tactical_observation(observation)
    best_partial_path: tuple[Action, ...] = ()
    lethal_path: tuple[Action, ...] = ()
    lethal_score = float("-inf")

    def dfs(
        current_position: object,
        current_observation: Mapping[str, Any],
        depth: int,
        path: tuple[Action, ...],
        uncertain: bool,
    ) -> bool:
        nonlocal best_partial_score, best_partial_path, lethal_path, lethal_score

        # ``max_nodes`` counts transitions, including the transition that may
        # finish the game.  The child terminal state is inspected immediately
        # after transition, before this cooperative deadline guard.
        if depth >= max_depth:
            counters["truncated"] += 1
            return False
        actions = _ordered_actions(
            current_observation,
            _safe_actions(current_position),
            limit=max_nodes - counters["nodes"],
        )
        if not actions:
            counters["completed"] += 1
            return False

        for action in actions:
            if counters["nodes"] >= max_nodes:
                counters["truncated"] += 1
                return False
            if _deadline_reached(deadline, clock):
                counters["truncated"] += 1
                return False
            child = _transition(current_position, action, seed=None)
            if child is None:
                counters["failed"] += 1
                continue
            counters["nodes"] += 1
            child_observation = _safe_observation(child)
            child_uncertain = uncertain or _is_uncertain(child_observation, child)
            if child_uncertain and not uncertain:
                counters["uncertain"] += 1

            child_score = score_tactical_observation(child_observation)
            if child_score > best_partial_score or not best_partial_path:
                best_partial_score = child_score
                best_partial_path = path + (action,)

            child_path = path + (action,)
            # A real lethal is recognized before checking whether the final
            # transition crossed the deadline.  Certainty is a separate gate.
            if _is_lethal_observation(child_observation):
                if not child_uncertain:
                    lethal_path = child_path
                    lethal_score = child_score
                    return True
                counters["uncertain"] += 1
            if _safe_terminal(child):
                counters["completed"] += 1
                continue
            if _deadline_reached(deadline, clock):
                counters["truncated"] += 1
                return False
            if dfs(child, child_observation, depth + 1, child_path, child_uncertain):
                return True
        return False

    initial_uncertain = _is_uncertain(observation, position)
    if initial_uncertain:
        counters["uncertain"] += 1
    found = dfs(position, observation, 0, (), initial_uncertain)
    if found and lethal_path:
        selected = _first_matching(legal_actions, lethal_path[0])
        return TacticalSearchResult(
            action=selected,
            path=lethal_path,
            score=lethal_score,
            best_partial_score=best_partial_score,
            nodes=counters["nodes"],
            completed_leaves=counters["completed"],
            truncated_lines=counters["truncated"],
            failed_lines=counters["failed"],
            deterministic_lethal=True,
            uncertain_branches=counters["uncertain"],
        )
    return TacticalSearchResult(
        action=None,
        path=best_partial_path,
        score=best_partial_score,
        best_partial_score=best_partial_score,
        nodes=counters["nodes"],
        completed_leaves=counters["completed"],
        truncated_lines=counters["truncated"],
        failed_lines=counters["failed"],
        deterministic_lethal=False,
        uncertain_branches=counters["uncertain"],
    )


@dataclass(frozen=True)
class ReplySearchResult:
    """Bounded visible-opponent reply diagnostics."""

    score: float
    nodes: int
    completed_leaves: int
    truncated_lines: int
    self_lethal: bool
    uncertain: bool = False
    failed_lines: int = 0


def evaluate_visible_opponent_reply(
    position: object,
    *,
    score_fn: Callable[[Mapping[str, Any]], float] = score_observation,
    max_nodes: int = REPLY_MAX_NODES,
    max_depth: int = REPLY_MAX_DEPTH,
    deadline: float | None = None,
    clock: Callable[[], float] | None = None,
) -> ReplySearchResult | None:
    """Minimize our score over a shallow, visible attack-only reply.

    ``position`` should be the result of ``SearchPosition.opponent_attack_position``
    when available.  The helper is intentionally conservative: failures or an
    unavailable reply estimate simply return ``None`` and never invent a hand
    play, Secret trigger, draw, or random outcome.
    """

    if max_nodes <= 0 or max_depth < 0:
        return None
    counters = {"nodes": 0, "completed": 0, "truncated": 0, "failed": 0}
    uncertain = bool(_safe_observation(position).get("search_uncertain", False))
    initial = _safe_observation(position)
    best_score = float(score_fn(initial))
    self_lethal = _raw_health(_hero(initial, "self")) is not None and _raw_health(
        _hero(initial, "self")
    ) <= 0

    def dfs(current_position: object, depth: int) -> float:
        nonlocal self_lethal, uncertain
        current_observation = _safe_observation(current_position)
        uncertain = uncertain or bool(current_observation.get("search_uncertain", False))
        current_score = float(score_fn(current_observation))
        own_health = _raw_health(_hero(current_observation, "self"))
        if own_health is not None and own_health <= 0:
            self_lethal = True
        if _safe_terminal(current_position):
            counters["completed"] += 1
            return current_score
        if depth >= max_depth:
            if any(action_type(action) == ATTACK for action in _safe_actions(current_position)):
                counters["truncated"] += 1
            else:
                counters["completed"] += 1
            return current_score
        if counters["nodes"] >= max_nodes or _deadline_reached(deadline, clock):
            counters["truncated"] += 1
            return current_score
        actions = tuple(
            action
            for action in _ordered_reply_actions(
                current_observation, _safe_actions(current_position)
            )
            if action_type(action) in (ATTACK, END_TURN)
        )
        if not actions:
            counters["completed"] += 1
            return current_score
        worst = current_score
        explored = False
        for action in actions:
            if counters["nodes"] >= max_nodes:
                counters["truncated"] += 1
                break
            if _deadline_reached(deadline, clock):
                counters["truncated"] += 1
                break
            child = _transition(current_position, action, seed=None)
            if child is None:
                counters["failed"] += 1
                continue
            counters["nodes"] += 1
            child_observation = _safe_observation(child)
            uncertain = uncertain or bool(child_observation.get("search_uncertain", False))
            child_health = _raw_health(_hero(child_observation, "self"))
            if child_health is not None and child_health <= 0:
                self_lethal = True
            # Inspect a terminal child before the deadline guard.  A slow final
            # attack still represents the actual visible reply outcome.
            if _safe_terminal(child):
                value = float(score_fn(child_observation))
                counters["completed"] += 1
            elif _deadline_reached(deadline, clock):
                counters["truncated"] += 1
                value = float(score_fn(child_observation))
            else:
                value = dfs(child, depth + 1)
            worst = min(worst, value)
            explored = True
        return worst if explored else current_score

    try:
        best_score = dfs(position, 0)
    except Exception:
        return None
    return ReplySearchResult(
        score=best_score,
        nodes=counters["nodes"],
        completed_leaves=counters["completed"],
        truncated_lines=counters["truncated"],
        self_lethal=self_lethal,
        uncertain=uncertain,
        failed_lines=counters["failed"],
    )


__all__ = [
    "REPLY_MAX_DEPTH",
    "REPLY_MAX_NODES",
    "TACTICAL_MAX_DEPTH",
    "TACTICAL_MAX_NODES",
    "ReplySearchResult",
    "TacticalSearchResult",
    "evaluate_visible_opponent_reply",
    "find_deterministic_lethal",
]
