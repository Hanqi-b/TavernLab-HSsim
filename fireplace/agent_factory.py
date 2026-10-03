"""Construct the selectable opponent policies used by the web game."""

from __future__ import annotations

from collections.abc import Mapping

from .heuristic_agent import HeuristicAgent
from .mcts_agent import MCTSAgent
from .radical_agent import RadicalAgent


SUPPORTED_AGENT_IDS = ("heuristic", "radical", "mcts")


def create_agent(
    kind: str,
    seed: int | None = None,
    *,
    policy_version: str | None = None,
    search_config: Mapping[str, object] | None = None,
):
    """Create a policy by stable public identifier.

    ``seed=None`` intentionally follows each constructor's deterministic
    default.  The heuristic has no random state, while the two search agents
    normalize ``None`` to seed zero.
    """

    if not isinstance(kind, str) or kind not in SUPPORTED_AGENT_IDS:
        raise ValueError(
            "kind must be one of %s" % ", ".join(repr(value) for value in SUPPORTED_AGENT_IDS)
        )
    if kind == "heuristic":
        if policy_version is not None or search_config is not None:
            raise ValueError("policy_version and search_config are only valid for mcts")
        return HeuristicAgent()
    if kind == "radical":
        if policy_version is not None or search_config is not None:
            raise ValueError("policy_version and search_config are only valid for mcts")
        return RadicalAgent(seed=seed)
    if search_config is not None and not isinstance(search_config, Mapping):
        raise ValueError("search_config must be a mapping")

    # New matches use the tactical policy.  Resume callers pass the archived
    # version explicitly; leaving the factory's public default independent of
    # MCTSAgent's constructor default keeps old direct constructor callers
    # legacy-compatible while making fresh web matches opt into the new policy.
    resolved_policy_version = (
        "tactical_v2" if policy_version is None else policy_version
    )
    config = dict(search_config) if search_config is not None else {}
    allowed_keys = frozenset(MCTSAgent.CONFIG_KEYS)
    invalid_keys = [
        key for key in config
        if not isinstance(key, str) or key not in allowed_keys
    ]
    if invalid_keys:
        raise ValueError("search_config contains unsupported keys")
    return MCTSAgent(
        seed=seed,
        policy_version=resolved_policy_version,
        **config,
    )


__all__ = ["SUPPORTED_AGENT_IDS", "create_agent"]
