"""Optional forward-search boundary; ordinary Agents still receive values only."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .agent_api import Action


class SearchUnavailable(RuntimeError):
    """A speculative state cannot safely model this continuation."""


class SearchPosition(Protocol):
    @property
    def terminal(self) -> bool:
        """Game over, own turn over, or an unresolved choice boundary."""

    def observation(self) -> Mapping[str, Any]: ...

    def legal_actions(self) -> Sequence[Action]: ...

    def transition(self, action: Action, *, seed: int | None = None) -> SearchPosition: ...

    def opponent_attack_position(self) -> SearchPosition:
        """Approximate the visible opponent's attacks, without hidden card plays."""


class SearchAgent(Protocol):
    def choose_action_with_search(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[Action],
        position: SearchPosition,
    ) -> Action: ...
