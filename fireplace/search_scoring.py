"""Engine-independent scores used by the optional search agents.

The search boundary deliberately exposes mappings instead of Fireplace
objects.  Keeping the score here means that both the real branch adapter and
small deterministic test positions use exactly the same evaluation code.
Unknown cards are counted as unknown information; they are never assigned a
placeholder cost or a fabricated card value.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from math import isfinite
from typing import Any


# A lethal result should dominate every ordinary board advantage while still
# leaving room for a small health/board tiebreaker in diagnostics.
LETHAL_SCORE = 1_000_000.0


def field(value: object, name: str, default: Any = None) -> Any:
    """Read a JSON mapping or a small attribute based test double."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def integer(value: object, default: int | None = None) -> int | None:
    """Return a finite integer without turning booleans into numbers."""

    if isinstance(value, bool) or value is None:
        return default
    if not isinstance(value, (int, float)):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not isfinite(number):
        return default
    return int(number)


def number(value: object, default: float | None = None) -> float | None:
    """Return a finite float for test observations that expose ``power``."""

    if isinstance(value, bool) or value is None:
        return default
    if not isinstance(value, (int, float)):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if isfinite(result) else default


def action_type(action: object) -> str:
    value = field(action, "type", "")
    value = getattr(value, "value", value)
    return str(value).upper()


def items(value: object) -> tuple[object, ...]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return ()
    try:
        return tuple(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _entity_id(value: object) -> int | None:
    result = field(value, "entity_id")
    if isinstance(result, bool) or not isinstance(result, int) or result <= 0:
        return None
    return result


def _health_total(hero: object) -> int:
    value = _mapping(hero)
    return max(0, integer(value.get("health"), 0) or 0) + max(
        0, integer(value.get("armor"), 0) or 0
    )


def _raw_health(hero: object) -> int:
    value = _mapping(hero)
    return integer(value.get("health"), 0) or 0


def _search_outcome(observation: Mapping[str, Any] | object) -> str | None:
    """Read an engine-provided terminal result when one is available.

    ``search_outcome`` is emitted only for a detached branch whose engine
    state reached ``game.ended``.  Keeping this lookup out of the legacy score
    preserves its historical health-based behavior while tactical callers can
    recognize scripted wins such as Mecha'thun when both visible heroes still
    have positive health.
    """

    if not isinstance(observation, Mapping):
        return None
    value = observation.get("search_outcome")
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in {"win", "loss", "draw"} else None


def _tactical_terminal_score(observation: Mapping[str, Any] | object) -> float | None:
    outcome = _search_outcome(observation)
    if outcome is None:
        return None
    own = _mapping(observation.get("self")) if isinstance(observation, Mapping) else {}
    enemy = _mapping(observation.get("opponent")) if isinstance(observation, Mapping) else {}
    own_health = _health_total(_mapping(own.get("hero")))
    enemy_health = _health_total(_mapping(enemy.get("hero")))
    if outcome == "win":
        return LETHAL_SCORE + float(own_health)
    if outcome == "loss":
        return -LETHAL_SCORE - float(enemy_health)
    return 0.0


def _score_tactical_leaf(observation: Mapping[str, Any] | object) -> float:
    terminal_score = _tactical_terminal_score(observation)
    base = _score_observation(observation, face_weight=7.0)
    if terminal_score is not None:
        return terminal_score
    if not isinstance(observation, Mapping):
        return base
    # Terminal results and scalar test positions retain their authoritative
    # values. Resource corrections apply only to ordinary visible boards.
    if abs(base) >= LETHAL_SCORE or is_terminal_draw(observation):
        return base
    if number(observation.get("score")) is not None or number(observation.get("evaluation")) is not None:
        return base
    own = _mapping(observation.get("self"))
    enemy = _mapping(observation.get("opponent"))
    own_count = max(len(items(own.get("hand"))), integer(own.get("hand_count"), 0) or 0)
    enemy_count = max(len(items(enemy.get("hand"))), integer(enemy.get("hand_count"), 0) or 0)
    # A hidden draw still acquires a resource, without pretending to know its
    # identity, mana cost or effect. The engine handles burns and fatigue.
    resources = 2.5 * (own_count - enemy_count)
    capabilities = sum(_tactical_capability(card) for card in items(own.get("board")))
    capabilities -= sum(_tactical_capability(card) for card in items(enemy.get("board")))
    return base + resources + 3.0 * capabilities


def _tactical_capability(character: object) -> float:
    """Bounded adjustments for public abilities and immediate availability.

    Scripted effects are evaluated by the engine transition; these bonuses
    represent residual value on a surviving board, not predicted card text.
    """
    value = _mapping(character)
    attack = max(0, integer(value.get("atk"), 0) or 0)
    if value.get("dormant"):
        return -0.7 * _character_value(value)
    bonus = 0.0
    if not value.get("silenced"):
        card_id = value.get("card_id")
        if isinstance(card_id, str):
            bonus += _printed_ability_value(card_id)
        if value.get("has_deathrattle"):
            bonus += 2.0
        if value.get("reborn"):
            bonus += 2.0
        if value.get("divine_shield"):
            bonus += min(3.0, attack * 0.5)
        if value.get("poisonous"):
            bonus += 2.0
        if value.get("windfury"):
            bonus += min(3.0, attack * 0.5)
        # Only active, publicly projected aura attachments receive a bonus.
        bonus += min(2, sum(field(effect, "kind") == "aura" for effect in items(value.get("active_modifiers"))))
    if value.get("frozen"):
        bonus -= min(3.0, attack * 0.5)
    elif value.get("can_attack"):
        bonus += min(1.5, attack * 0.25)
    return max(-20.0, min(10.0, bonus))


@lru_cache(maxsize=512)
def _printed_ability_value(card_id: object) -> float:
    """Small residual value for scripts on an already visible card identity.

    This recognizes surviving triggered/aura abilities without a per-card
    exception table. Their actual effects and ordering still require engine
    simulation; script presence alone is deliberately a small heuristic.
    """
    if not isinstance(card_id, str) or not card_id:
        return 0.0
    try:
        from . import cards

        record = cards.db.get(card_id)
        scripts = getattr(record, "scripts", None)
        events = items(getattr(scripts, "events", ()))
        aura = bool(getattr(scripts, "update", None))
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return min(3.0, len(events) * 1.5 + (1.0 if aura else 0.0))


def _character_value(character: object) -> float:
    value = _mapping(character)
    attack = max(0, integer(value.get("atk"), 0) or 0)
    health = max(0, integer(value.get("health"), 0) or 0)
    armor = max(0, integer(value.get("armor"), 0) or 0)
    # Health and attack are intentionally kept on similar scales.  Keyword
    # fields add a small, visible bonus without pretending to model every
    # card script in a bounded search.
    bonus = 0.0
    for keyword in ("taunt", "divine_shield", "windfury", "lifesteal", "poisonous"):
        if value.get(keyword):
            bonus += 1.5
    return float(attack * 2 + health + armor + bonus)


def _weapon_value(weapon: object) -> float:
    value = _mapping(weapon)
    return float(
        max(0, integer(value.get("atk"), 0) or 0) * 2
        + max(0, integer(value.get("durability"), 0) or 0)
    )


def is_unknown_card(card: object) -> bool:
    """Whether a card intentionally carries no public identity/value."""

    value = _mapping(card)
    if value.get("unknown"):
        return True
    if str(value.get("type", "")).upper() == "UNKNOWN":
        return True
    # EngineSearchPosition represents hidden draws with ``card_id=None`` and
    # ``cost=None``.  Treat that pair as unknown even if an older projection
    # omitted the explicit marker.
    return value.get("card_id") is None and value.get("cost") is None


def card_power(card: object) -> float | None:
    """Estimate a known hand card's immediate value.

    Explicit ``power``/``value`` fields are useful for test positions and are
    respected first.  Otherwise the public stats provide a conservative
    estimate.  Unknown cards return ``None`` rather than receiving a fake
    high cost or power.
    """

    value = _mapping(card)
    if is_unknown_card(value):
        return None
    for key in ("power", "value", "score"):
        explicit = number(value.get(key))
        if explicit is not None:
            return explicit
    attack = integer(value.get("atk"))
    if attack is None:
        attack = integer(value.get("printed_atk"), 0)
    health = integer(value.get("health"))
    if health is None:
        health = integer(value.get("printed_health"), 0)
    cost = max(0, integer(value.get("cost"), 0) or 0)
    stats = max(0, attack or 0) + max(0, health or 0)
    if stats:
        return float(stats + max(1, cost))
    # A known spell with no public stat still has a useful immediate value.
    # Cost is the only safe proxy available at this boundary.
    return float(max(1, cost))


def card_cost(card: object) -> int | None:
    value = _mapping(card)
    if is_unknown_card(value):
        return None
    return integer(value.get("cost"))


def _score_observation(
    observation: Mapping[str, Any] | object,
    *,
    face_weight: float = 12.0,
) -> float:
    """Score a public observation from the observing player's perspective.

    Positive values favour the observing player.  A few fake search
    positions intentionally expose a scalar ``score``; honouring it keeps
    search tests independent of Fireplace while real observations continue
    through the board/hero calculation below.
    """

    if not isinstance(observation, Mapping):
        observation = {}
    explicit = number(observation.get("score"))
    if explicit is None:
        explicit = number(observation.get("evaluation"))

    own = _mapping(observation.get("self"))
    enemy = _mapping(observation.get("opponent"))
    own_hero = _mapping(own.get("hero"))
    enemy_hero = _mapping(enemy.get("hero"))

    own_health = _health_total(own_hero)
    enemy_health = _health_total(enemy_hero)
    own_dead = bool(own_hero) and _raw_health(own_hero) <= 0
    enemy_dead = bool(enemy_hero) and _raw_health(enemy_hero) <= 0
    if own_dead and enemy_dead:
        return 0.0
    if enemy_dead:
        return LETHAL_SCORE + float(own_health)
    if own_dead:
        return -LETHAL_SCORE - float(enemy_health)
    if explicit is not None:
        return explicit

    own_board = sum(_character_value(card) for card in items(own.get("board")))
    enemy_board = sum(_character_value(card) for card in items(enemy.get("board")))
    own_weapon = _weapon_value(own.get("weapon"))
    enemy_weapon = _weapon_value(enemy.get("weapon"))

    own_mana = max(0, integer(own.get("mana"), 0) or 0)
    enemy_mana = max(0, integer(enemy.get("mana"), 0) or 0)
    own_deck = max(0, integer(own.get("deck_count"), 0) or 0)
    enemy_deck = max(0, integer(enemy.get("deck_count"), 0) or 0)
    own_hand_cards = items(own.get("hand"))
    own_hand = 0.0
    unknown_hand_count = 0
    for card in own_hand_cards:
        power = card_power(card)
        if power is not None:
            own_hand += power * 0.15
        else:
            unknown_hand_count += 1
    # Unknown hand count is still public information, but it must not be
    # treated as a known card value.
    own_hand += unknown_hand_count * 0.05
    if not own_hand_cards:
        own_hand += max(0, integer(own.get("hand_count"), 0) or 0) * 0.05
    enemy_hand = max(0, integer(enemy.get("hand_count"), 0) or 0) * 0.05
    own_secrets = len(items(own.get("secrets")))
    if not own_secrets:
        own_secrets = max(0, integer(own.get("secrets_count"), 0) or 0)
    enemy_secrets = max(0, integer(enemy.get("secrets_count"), 0) or 0)

    return float(
        (own_health - enemy_health) * face_weight
        + (own_board - enemy_board) * 3
        + (own_weapon - enemy_weapon) * 2
        + (own_mana - enemy_mana) * 0.5
        + (own_deck - enemy_deck) * 0.1
        + (own_hand - enemy_hand)
        + (own_secrets - enemy_secrets) * 1.5
    )


def score_observation(observation: Mapping[str, Any] | object) -> float:
    """Score an observation with the original legacy policy weights.

    Keep this wrapper stable for ``legacy_v1`` and callers that use the
    engine-independent scorer directly.  Tactical v2 uses the separate
    :func:`score_tactical_observation` entry point below.
    """

    return _score_observation(observation, face_weight=12.0)


def is_terminal_win(observation: Mapping[str, Any] | object) -> bool:
    """Whether the visible observation is an own-alive enemy lethal."""

    outcome = _search_outcome(observation)
    if outcome is not None:
        return outcome == "win"
    if not isinstance(observation, Mapping):
        return False
    own = _mapping(observation.get("self"))
    enemy = _mapping(observation.get("opponent"))
    own_hero = _mapping(own.get("hero"))
    enemy_hero = _mapping(enemy.get("hero"))
    own_health = integer(own_hero.get("health"))
    enemy_health = integer(enemy_hero.get("health"))
    return (
        bool(own_hero)
        and bool(enemy_hero)
        and own_health is not None
        and enemy_health is not None
        and own_health > 0
        and enemy_health <= 0
    )


def is_terminal_loss(observation: Mapping[str, Any] | object) -> bool:
    """Whether the visible observation has an own-dead hero."""

    outcome = _search_outcome(observation)
    if outcome is not None:
        return outcome == "loss"
    if not isinstance(observation, Mapping):
        return False
    own = _mapping(observation.get("self"))
    own_hero = _mapping(own.get("hero"))
    health = integer(own_hero.get("health"))
    return bool(own_hero) and health is not None and health <= 0


def is_terminal_draw(observation: Mapping[str, Any] | object) -> bool:
    """Whether both visible heroes are dead."""

    outcome = _search_outcome(observation)
    if outcome is not None:
        return outcome == "draw"
    if not isinstance(observation, Mapping):
        return False
    own = _mapping(observation.get("self"))
    enemy = _mapping(observation.get("opponent"))
    own_hero = _mapping(own.get("hero"))
    enemy_hero = _mapping(enemy.get("hero"))
    own_health = integer(own_hero.get("health"))
    enemy_health = integer(enemy_hero.get("health"))
    return (
        bool(own_hero)
        and bool(enemy_hero)
        and own_health is not None
        and enemy_health is not None
        and own_health <= 0
        and enemy_health <= 0
    )


def score_tactical_observation(
    observation: Mapping[str, Any] | object,
    *,
    opponent_position: object | None = None,
    reply_position: object | None = None,
    max_reply_nodes: int = 32,
    max_reply_depth: int = 2,
    deadline: float | None = None,
    clock=None,
    diagnostics: dict[str, Any] | None = None,
) -> float:
    """Score a visible current-turn branch for tactical MCTS.

    Tactical v2 lowers the raw hero-face coefficient so board survival and
    actual turn-end outcomes matter more than speculative face pressure.  If
    an ``opponent_attack_position`` handle is supplied, a small attack-only
    reply search estimates the visible opponent's best sequence.  The reply is
    explicitly approximate: an unavailable or exhausted estimate leaves the
    current score unchanged, and no hidden hand or Secret is inspected.
    """

    # ``reply_position`` is the descriptive spelling used by new callers;
    # ``opponent_position`` keeps the helper convenient for older adapters.
    position = reply_position if reply_position is not None else opponent_position
    base = _score_tactical_leaf(observation)
    if diagnostics is not None:
        diagnostics.update({"status": "not_requested", "approximate": True,
                            "nodes": 0, "completed_leaves": 0, "truncated_lines": 0,
                            "failed_lines": 0, "uncertain": False})
    if position is None:
        return base

    # Import lazily to keep the scoring module usable by standalone fake
    # observations without importing the search traversal helpers at module
    # import time.
    from .search_tactics import evaluate_visible_opponent_reply

    try:
        reply = evaluate_visible_opponent_reply(
            position,
            score_fn=_score_tactical_leaf,
            max_nodes=max_reply_nodes,
            max_depth=max_reply_depth,
            deadline=deadline,
            clock=clock,
        )
    except Exception:
        reply = None
    if reply is None:
        if diagnostics is not None:
            diagnostics["status"] = "unavailable"
        return base
    if diagnostics is not None:
        diagnostics.update({"status": "partial" if reply.truncated_lines or reply.failed_lines else "evaluated",
                            "nodes": reply.nodes, "completed_leaves": reply.completed_leaves,
                            "truncated_lines": reply.truncated_lines, "failed_lines": reply.failed_lines,
                            "uncertain": reply.uncertain})
    if reply.self_lethal:
        # A visible opponent line that kills us must dominate ordinary board
        # value.  The reply score already includes the lethal sentinel, while
        # min() also preserves an even worse explicit current score.
        return min(base, float(reply.score))
    # Reply estimates are deliberately conservative and non-exhaustive.  A
    # reply cannot create bonus value for the current player; only a negative
    # change is blended into the current branch score.
    delta = min(0.0, float(reply.score) - base)
    return base + max(-250.0, delta * 0.8)


def improved(before: Mapping[str, Any] | object, after: Mapping[str, Any] | object) -> bool:
    """Return whether a child state improves the root-perspective score."""

    return score_observation(after) > score_observation(before)


__all__ = [
    "LETHAL_SCORE",
    "action_type",
    "card_cost",
    "card_power",
    "field",
    "improved",
    "integer",
    "is_terminal_draw",
    "is_terminal_loss",
    "is_terminal_win",
    "is_unknown_card",
    "score_observation",
    "score_tactical_observation",
]
