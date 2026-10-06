"""Thread-safe local HTTP boundary for the browser game UI.

Only JSON-safe values cross this module's HTTP boundary.  A browser receives
the observation already filtered by :mod:`fireplace.observation` and the
canonical dictionaries returned by :class:`fireplace.agent_api.Action`.
Fireplace entities are kept inside ``GameSession`` and are never serialized or
looked up by the request handler.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections import deque
from collections.abc import Mapping
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from ..agent_api import Action, CONCEDE
from ..controller import ActionError, GameSession, decision_player
from ..exceptions import GameOver
from .assets import AssetService
from .archive_runtime import (
    ArchivePersistenceError,
    action_log_dict,
    archive_summary,
    as_envelope,
    attach_on_save,
    capture_agent_state,
    canonical_game_id,
    checkpoint_is_terminal,
    envelope_log,
    envelope_metadata,
    envelope_public,
    envelope_revision,
    envelope_status,
    public_payload,
    restore_action_log,
    restore_agent_state,
    store_create,
    store_find_arena,
    store_get,
    store_list,
    store_mark_abandoned,
    store_save,
)
from .contracts import ASSET_PENDING, WebActionError, WebLifecycleError
from .effect_timeline import EffectTimeline
from .ai_decisions import capture_decision, restore_decisions, trim_decisions
from .async_opponent import (
    AsyncDecision,
    AsyncOpponentScheduler,
    codex_config_from_agent,
    codex_defaults,
    validate_codex_model,
    validate_codex_state,
)
from .public_events import (
    decorate_visible_cards,
    localize_events,
    project_action,
    visible_card_ids,
)


_ASSET_KINDS = frozenset({"render", "art", "tile"})
_LOCALES = frozenset({"zhCN", "enUS"})
_OPPONENTS = frozenset({"radical", "mcts", "codex"})
_OPPONENT_NAMES = {
    "radical": "Radical",
    "mcts": "MCTS",
    "codex": "Codex",
}
_BATTLE_MODES = frozenset({"human", "codex_mcts", "codex_codex"})
_AUTOMATION_BATTLE_MODE = "codex_mcts"
_CODEX_DUEL_BATTLE_MODE = "codex_codex"
_ASSET_PENDING = ASSET_PENDING
_MCTS_LEGACY_POLICY = "legacy_v1"
_MCTS_TACTICAL_POLICY = "tactical_v2"


def _game_ended(game: object) -> bool:
    value = getattr(game, "ended", False)
    if callable(value):
        try:
            value = value()
        except Exception:
            return False
    return bool(value)


def _player_name(player: object) -> str | None:
    value = getattr(player, "name", None)
    if value is None:
        return None
    return str(value)


def _outcome(game: object, human: object) -> dict[str, str | bool | None] | None:
    """Return the deliberately small terminal result projection."""

    if not _game_ended(game):
        return None

    winner = None
    human_won = False
    for player in getattr(game, "players", ()):
        state = getattr(player, "playstate", None)
        state_name = getattr(state, "name", state)
        if str(state_name).upper() == "WON":
            winner = _player_name(player)
            human_won = player is human
            break
    return {"winner": winner, "human_won": human_won if winner else None}


def _validate_locale(value: object) -> str:
    if value not in _LOCALES:
        raise ValueError("locale must be 'zhCN' or 'enUS'")
    return str(value)


def _validate_opponent(value: object) -> str:
    if not isinstance(value, str) or value not in _OPPONENTS:
        raise ValueError("opponent must be one of 'radical', 'mcts', or 'codex'")
    return value


def _validate_battle_mode(value: object) -> str:
    if value is None:
        return "human"
    if not isinstance(value, str) or value not in _BATTLE_MODES:
        raise ValueError(
            "battle_mode must be 'human', 'codex_mcts', or 'codex_codex'"
        )
    return value


def _create_opponent_agent(
    kind: str,
    seed: int | None,
    *,
    policy_version: str | None = None,
    search_config: Mapping[str, Any] | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> object:
    """Create one validated browser opponent through the shared factory."""

    from ..agent_factory import create_agent

    options: dict[str, Any] = {}
    if policy_version is not None:
        options["policy_version"] = policy_version
    if search_config is not None:
        options["search_config"] = copy.deepcopy(dict(search_config))
    if model is not None or kind == "codex":
        options["model"] = model
    if timeout is not None or kind == "codex":
        options["timeout"] = timeout
    if kind == "codex":
        # Constructing the transport is lazy. Only this explicitly selected
        # controller uses the user's Codex connection settings.
        from .codex_connection import get_codex_connection

        options["transport"] = get_codex_connection().create_transport()
    return create_agent(kind, seed=seed, **options)


def _resolve_mcts_archive_options(
    metadata: Mapping[str, Any], agent_state: object
) -> tuple[str, dict[str, Any] | None]:
    """Resolve one archived MCTS policy before replay construction.

    Archive version one permits these fields to be absent.  That is the
    legacy policy shape; a configuration without an accompanying version is
    rejected because its intended constructor defaults are ambiguous.
    """

    state = agent_state if isinstance(agent_state, Mapping) else {}
    state_has_version = "policy_version" in state
    metadata_has_version = "mcts_policy_version" in metadata
    state_version = state.get("policy_version")
    metadata_version = metadata.get("mcts_policy_version")
    for name, value in (
        ("archived MCTS policy version", state_version),
        ("archived MCTS metadata policy version", metadata_version),
    ):
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError("%s is invalid" % name)
    if (state_has_version and state_version is None) or (
        metadata_has_version and metadata_version is None
    ):
        raise ValueError("archived MCTS policy version is invalid")
    if state_has_version and metadata_has_version and state_version != metadata_version:
        raise ValueError("archived MCTS policy versions conflict")
    if (
        not state_has_version
        and metadata_has_version
        and metadata_version != _MCTS_LEGACY_POLICY
    ):
        raise ValueError("archived MCTS state is missing its policy version")
    if state_has_version or metadata_has_version:
        policy_version = state_version if state_has_version else metadata_version
    else:
        policy_version = _MCTS_LEGACY_POLICY

    state_has_config = "search_config" in state
    metadata_has_config = "mcts_search_config" in metadata
    state_config = state.get("search_config")
    metadata_config = metadata.get("mcts_search_config")
    for name, value in (
        ("archived MCTS search configuration", state_config),
        ("archived MCTS metadata search configuration", metadata_config),
    ):
        if value is not None and not isinstance(value, Mapping):
            raise ValueError("%s is invalid" % name)
    if state_has_config and metadata_has_config:
        if not isinstance(state_config, Mapping) or not isinstance(metadata_config, Mapping):
            raise ValueError("archived MCTS search configuration is invalid")
        if dict(state_config) != dict(metadata_config):
            raise ValueError("archived MCTS search configurations conflict")
    if state_has_config or metadata_has_config:
        search_config = state_config if state_has_config else metadata_config
        if not isinstance(search_config, Mapping):
            raise ValueError("archived MCTS search configuration is invalid")
        search_config = copy.deepcopy(dict(search_config))
    else:
        search_config = None

    if not state_has_version and not metadata_has_version and search_config is not None:
        raise ValueError("archived MCTS search configuration has no policy version")
    if policy_version == _MCTS_TACTICAL_POLICY:
        from ..mcts_agent import MCTSAgent

        required_keys = frozenset(MCTSAgent.CONFIG_KEYS)
        if search_config is None:
            raise ValueError("archived tactical MCTS match is missing search configuration")
        if frozenset(search_config) != required_keys:
            raise ValueError("archived tactical MCTS search configuration is incomplete")
        if not state_has_config:
            raise ValueError("archived tactical MCTS state is missing search configuration")
    return policy_version, search_config


def _resolve_codex_archive_options(
    metadata: Mapping[str, Any],
    agent_state: object,
    *,
    model_keys: tuple[str, ...] = ("codex_model", "codex_self_model"),
    timeout_keys: tuple[str, ...] = ("codex_timeout",),
) -> tuple[str | None, float]:
    """Resolve one seat's pinned Codex configuration from an archive.

    Human-vs-Codex archives historically used ``codex_model`` while the
    automated seat zero contract uses ``codex_self_model``.  Duel archives
    contain both keys with different values, so aliases are supplied by the
    caller per seat instead of treating the two fields as one identity.
    """

    state = validate_codex_state(agent_state)
    metadata_models = [metadata[key] for key in model_keys if key in metadata]
    if metadata_models:
        model_values = [validate_codex_model(value) for value in metadata_models]
        if any(value != model_values[0] for value in model_values[1:]):
            raise ValueError("archived Codex models conflict")
        model = model_values[0]
    else:
        model = state["model"]
    # Metadata is public match identity, while agent_state is the authoritative
    # private constructor contract.  If both are present they must agree.
    if model != state["model"]:
        raise ValueError("archived Codex models conflict")

    metadata_timeouts = [metadata[key] for key in timeout_keys if key in metadata]
    if metadata_timeouts:
        if any(value is None for value in metadata_timeouts):
            raise ValueError("archived Codex timeout is invalid")
        try:
            timeout_values = [codex_defaults(None, value)[1] for value in metadata_timeouts]
        except ValueError as exc:
            raise ValueError("archived Codex timeout is invalid") from exc
        if any(value != timeout_values[0] for value in timeout_values[1:]):
            raise ValueError("archived Codex timeouts conflict")
        timeout = timeout_values[0]
    else:
        timeout = state["timeout"]
    if timeout != state["timeout"]:
        raise ValueError("archived Codex timeouts conflict")
    return state["model"], state["timeout"]


def _validate_nickname(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("nickname must be a string")
    nickname = value.strip()
    if not nickname:
        raise ValueError("nickname must not be empty")
    if len(nickname) > 32:
        raise ValueError("nickname must be at most 32 characters")
    return nickname


class WebGame:
    """Own one local human-vs-agent ``GameSession``.

    Construction starts the session and lets the opponent make decisions until
    the supplied ``human`` is the next decision player or the game ends.  The
    public methods are safe to call from multiple HTTP worker threads.
    """

    def __init__(
        self,
        session: GameSession,
        human: object,
        opponent_agent: object,
        *,
        asset_resolver: object | None = None,
        asset_service: AssetService | None = None,
        locale: str = "zhCN",
        initial_events: list[Mapping[str, Any]] | None = None,
        initial_revision: int = 0,
        initial_ai_decisions: list[Mapping[str, Any]] | None = None,
        initial_ai_decisions_dropped: int = 0,
        start_immediately: bool = True,
    ) -> None:
        if asset_resolver is not None and asset_service is not None:
            raise ValueError("asset_resolver and asset_service are mutually exclusive")
        self.locale = _validate_locale(locale)
        self.session = session
        self.human = human
        self.opponent_agent = opponent_agent
        self._async_opponent = bool(
            getattr(opponent_agent, "async_decisions", False)
        )
        self._async_scheduler: AsyncOpponentScheduler | None = None
        self._llm_state = "idle"
        self._llm_error: str | None = None
        self._closed = False
        self._retrying = False
        self._retry_token = 0
        self._archive_ready = False
        self._presentation_steps: deque[dict[str, Any]] = deque(maxlen=32)
        self._codex_config: dict[str, Any] | None = None
        if self._async_opponent:
            self._codex_config = codex_config_from_agent(opponent_agent)
        self._lock = threading.RLock()
        self._revision = int(initial_revision)
        self._session_id = str(uuid.uuid4())
        self._started = False
        self._events: list[dict[str, Any]] = [
            copy.deepcopy(dict(event))
            for event in (initial_events or ())
            if isinstance(event, Mapping)
        ]
        # ActionLog invokes its save callback from inside GameSession.execute,
        # before this boundary has appended the corresponding public event.
        # Keep that event in a short lived pending slot so a durable callback
        # still receives an exact visible prefix.  It is cleared as soon as
        # the event is appended (or the checked action is rejected).
        self._pending_event: dict[str, Any] | None = None
        self._ai_decisions = copy.deepcopy(initial_ai_decisions or [])
        self._ai_decisions_dropped = initial_ai_decisions_dropped
        self._event_seq = max(
            [
                int(event.get("seq"))
                for event in self._events
                if type(event.get("seq")) is int
            ]
            or [len(self._events)]
        )
        self._archive_failed: str | None = None
        self._archive_game_id: str | None = None
        self._archive_revision: int | None = None
        self.asset_resolver = asset_resolver
        self._owns_assets = asset_service is None
        # AssetService owns optional resolver construction and keeps it lazy.
        # Passing a custom resolver remains useful for deterministic tests and
        # embedded callers; omitting one uses the package's default factory.
        self.assets = asset_service or (
            AssetService() if asset_resolver is None
            else AssetService(resolver=asset_resolver)
        )
        # Presentation observers belong to the web match boundary.  The
        # underlying GameSession remains unchanged for CLI/replay callers.
        self._effect_timeline = EffectTimeline(self.session, self.human)
        self._effect_timeline.register()
        if start_immediately:
            self.start()

    @property
    def lock(self) -> threading.RLock:
        """Expose the lock to the HTTP adapter without exposing game state."""

        return self._lock

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    @property
    def archive_game_id(self) -> str | None:
        with self._lock:
            return self._archive_game_id

    @property
    def archive_revision(self) -> int | None:
        with self._lock:
            return self._archive_revision

    @property
    def archive_failed(self) -> str | None:
        with self._lock:
            return self._archive_failed

    def bind_archive(self, game_id: str, revision: int) -> None:
        """Attach the durable identity after the initial envelope is created."""

        with self._lock:
            self._archive_game_id = canonical_game_id(game_id)
            self._archive_revision = int(revision)
            self._archive_ready = True

    def mark_archive_failed(self, error: object) -> None:
        with self._lock:
            self._archive_failed = str(error)

    def _ensure_archive_healthy_locked(self) -> None:
        if self._archive_failed is not None:
            raise ArchivePersistenceError(
                "match archive is unavailable; resume from the latest durable checkpoint"
            )

    def close(self, *, wait: bool = True) -> None:
        """Release optional asset workers when the local server closes."""

        scheduler = None
        with self._lock:
            if self._closed:
                return
            self._closed = True
            scheduler = self._async_scheduler
            self._async_scheduler = None
            if scheduler is not None:
                scheduler.invalidate()
        try:
            if scheduler is not None:
                scheduler.close(wait=wait)
            self._effect_timeline.unregister()
            if self._owns_assets:
                self.assets.close(wait=wait)
        finally:
            # The session registers an engine observer for entity-id lookup.
            # Detach it when a lobby match is discarded so repeated matches do
            # not retain the old game through the observer graph.
            self.session.close()

    def start(self) -> dict[str, Any]:
        """Start the session once and advance the AI to the human decision."""

        with self._lock:
            try:
                self._ensure_archive_healthy_locked()
            except ArchivePersistenceError as exc:
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            if not self._started:
                self.session.start()
                self._started = True
                # Direct WebGame callers have no archive envelope.  Archived
                # construction calls bind_archive before start(), so an
                # asynchronous decision can never race initial persistence.
                if self._archive_game_id is None:
                    self._archive_ready = True
                self._advance_ai_locked()
            return self._snapshot_locked()

    def _decision_actions_locked(self) -> tuple[object | None, list[Action]]:
        game = self.session.game
        if _game_ended(game):
            return None, []
        player = decision_player(game)
        if player is not self.human:
            return player, []
        return player, list(self.session.legal_actions(self.human))

    def _localized_observation_locked(self, observation: object) -> object:
        """Decorate one already filtered observation in the match locale."""

        localized = copy.deepcopy(observation)
        visible_ids = visible_card_ids(localized)
        descriptions = self.assets.describe_visible(visible_ids, locale=self.locale)
        if descriptions:
            decorate_visible_cards(localized, descriptions)
        return localized

    def _public_events_locked(self) -> list[dict[str, Any]]:
        """Return event rows without internal localization metadata.

        The private card IDs are captured only from filtered observations at
        the moment an entity is visible.  They let a later snapshot replace a
        temporary fallback name after an asynchronous asset description has
        completed, while the browser never receives those internal fields.
        """

        events = copy.deepcopy(self._events)
        if self._pending_event is not None:
            pending = copy.deepcopy(self._pending_event)
            pending_seq = pending.get("seq")
            if not any(
                pending_seq is not None and event.get("seq") == pending_seq
                for event in events
            ):
                events.append(pending)
        return self._localize_public_events_locked(events)

    def _localize_public_events_locked(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Localize event copies while keeping internal card ids private."""

        card_ids = {
            card_id
            for event in events
            for key in ("_source_card_id", "_target_card_id")
            if isinstance(card_id := event.get(key), str) and card_id
        }
        if card_ids:
            descriptions = self.assets.describe_visible(card_ids, locale=self.locale)
        else:
            descriptions = {}
        return localize_events(events, descriptions)

    def _presentation_step_locked(
        self, event: Mapping[str, Any],
        effects: list[Mapping[str, Any]] | None = None,
        effects_truncated: bool = False,
    ) -> dict[str, Any]:
        """Capture one accepted action after its engine effects have settled.

        The stored event may contain private card ids used for asynchronous
        localization.  Presentation frames go directly to the browser, so
        they use the same public projection as the event timeline and keep
        those implementation details out of the response.
        """

        public_event = self._localize_public_events_locked([
            copy.deepcopy(dict(event))
        ])[0]
        frame = {
            "revision": self._revision,
            "observation": self._localized_observation_locked(
                self.session.observation(self.human)
            ),
            "event": public_event,
            "outcome": _outcome(self.session.game, self.human),
        }
        if effects or effects_truncated:
            frame["effects"] = self._localized_effects_locked(effects or [])
        if effects_truncated:
            frame["effects_truncated"] = True
        return frame

    def _localized_effects_locked(
        self, effects: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Localize copied effect records without exposing card ids."""

        localized: list[dict[str, Any]] = []
        for effect in effects:
            if not isinstance(effect, Mapping):
                continue
            raw_event = effect.get("event")
            if not isinstance(raw_event, Mapping):
                continue
            event = self._localize_public_events_locked([
                copy.deepcopy(dict(raw_event))
            ])[0]
            observation = self._localized_observation_locked(
                copy.deepcopy(effect.get("observation", {}))
            )
            localized.append({"event": event, "observation": observation})
        return localized

    def _snapshot_locked(self) -> dict[str, Any]:
        observation = self._localized_observation_locked(
            self.session.observation(self.human)
        )

        _decision, actions = self._decision_actions_locked()
        payload = {
            "mode": "match",
            "session_id": self._session_id,
            "revision": self._revision,
            "locale": self.locale,
            "nickname": _player_name(self.human),
            "observation": observation,
            "legal_actions": [action.to_dict() for action in actions],
            "outcome": _outcome(self.session.game, self.human),
            "events": self._public_events_locked(),
        }
        if self._async_opponent:
            payload["llm"] = {
                "state": self._llm_state,
                "model": (self._codex_config or {}).get("model"),
                "error": self._llm_error,
            }
            payload["presentation_steps"] = copy.deepcopy(
                list(self._presentation_steps)
            )
        return payload

    def _public_event_locked(
        self, player: object, action: Action, observation: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Project an accepted action under the centralized privacy policy."""

        source = None
        if action.type == "PLAY_CARD" and action.source_entity_id is not None:
            try:
                source = self.session.index.get(action.source_entity_id)
            except ActionError:
                # The action was already checked against legal actions.  This
                # defensive fallback keeps projection harmless for lightweight
                # test sessions whose index does not retain hand cards.
                source = None
        return project_action(
            player,
            self.human,
            action,
            self._localized_observation_locked(observation),
            seq=self._event_seq + 1,
            source=source,
        )

    def _append_event_locked(self, event: dict[str, Any]) -> None:
        self._event_seq += 1
        self._events.append(event)
        self._pending_event = None

    def _execute_with_effects_locked(
        self,
        player: object,
        action: Action,
        event: Mapping[str, Any],
        observation: object,
    ) -> tuple[bool, ActionError | None, list[dict[str, Any]], bool]:
        """Execute one checked action while the effect observer is active."""

        self._effect_timeline.begin(
            player,
            observation=observation,
            public_event=event,
        )
        terminal = False
        action_error: ActionError | None = None
        try:
            try:
                self.session.execute(player, action)
            except GameOver:
                terminal = True
            except ActionError as exc:
                action_error = exc
        finally:
            # The terminal signal is raised from the engine's action_end after
            # all observer callbacks have run, so draining here retains fatal
            # damage/death effects as well.
            effects = self._effect_timeline.end()
        return terminal, action_error, effects, self._effect_timeline.last_truncated

    def snapshot(self) -> dict[str, Any]:
        """Return the current browser payload as ordinary JSON-safe values."""

        with self._lock:
            return self._snapshot_locked()

    def error_payload(self, message: str) -> dict[str, Any]:
        """Return an error plus the latest snapshot for an HTTP response."""

        with self._lock:
            payload = self._snapshot_locked()
            payload["error"] = str(message)
            return payload

    def start_match(self, payload: object) -> dict[str, Any]:
        """Satisfy the shared backend contract for single-match servers."""

        del payload
        raise WebLifecycleError(
            "match lifecycle is unavailable for this server", 409, self.snapshot()
        )

    def return_to_lobby(self, payload: object) -> dict[str, Any]:
        """Satisfy the shared backend contract for single-match servers."""

        del payload
        raise WebLifecycleError(
            "match lifecycle is unavailable for this server", 409, self.snapshot()
        )

    def _ensure_async_scheduler_locked(self) -> AsyncOpponentScheduler:
        if not self._async_opponent:
            raise RuntimeError("opponent is not asynchronous")
        if not self._archive_ready:
            raise RuntimeError("opponent scheduler is not ready")
        scheduler = self._async_scheduler
        if scheduler is None:
            scheduler_ref: dict[str, AsyncOpponentScheduler] = {}
            scheduler = AsyncOpponentScheduler(
                self.opponent_agent,
                on_result=lambda decision, result: self._on_async_result(
                    scheduler_ref["scheduler"], decision, result
                ),
                on_error=lambda decision, error: self._on_async_error(
                    scheduler_ref["scheduler"], decision, error
                ),
            )
            scheduler_ref["scheduler"] = scheduler
            self._async_scheduler = scheduler
        return scheduler

    @staticmethod
    def _sanitize_codex_error(error: BaseException) -> str:
        """Map adapter failures to stable browser-safe diagnostics."""

        from ..codex_agent import CodexAgentError

        if isinstance(error, CodexAgentError):
            messages = {
                "timeout": "Codex connection timed out; check login and proxy in Codex connection settings, then retry",
                "unavailable": "Codex is unavailable; check the installed program and login in Codex connection settings",
                "invalid_action": "Codex opponent returned an invalid action",
            }
            return messages.get(
                error.reason,
                "Codex request failed; use the connection test to check login, network and model access",
            )
        name = type(error).__name__.lower()
        if isinstance(error, TimeoutError) or "timeout" in name:
            return "Codex opponent timed out"
        if "invalid" in name or "action" in name:
            return "Codex opponent returned an invalid action"
        if "api" in name or "codex" in name or "request" in name:
            return "Codex opponent request failed"
        return "Codex opponent failed to choose an action"

    def _set_llm_error_locked(self, error: BaseException | str) -> None:
        if isinstance(error, BaseException):
            message = self._sanitize_codex_error(error)
        else:
            # Internal archive/lifecycle errors are already deliberately
            # phrased for clients; never pass an arbitrary external stderr
            # string through this path.
            message = str(error)
        self._llm_state = "error"
        self._llm_error = message

    def _record_presentation_step_locked(self, step: Mapping[str, Any]) -> None:
        if self._async_opponent:
            self._presentation_steps.append(copy.deepcopy(dict(step)))

    def _invalidate_async_locked(self) -> None:
        if not self._async_opponent:
            return
        scheduler = self._async_scheduler
        if scheduler is not None:
            scheduler.invalidate()
        if self._llm_state == "thinking":
            self._llm_state = "idle"
            self._llm_error = None

    def _schedule_async_ai_locked(self) -> None:
        if not self._async_opponent or self._closed or _game_ended(self.session.game):
            return
        if self._llm_state == "error":
            return
        player = decision_player(self.session.game)
        if player is None or player is self.human:
            self._llm_state = "idle"
            self._llm_error = None
            return
        actions = list(self.session.legal_actions(player))
        if not actions:
            self._set_llm_error_locked("Codex opponent has no legal action")
            return
        scheduler = self._ensure_async_scheduler_locked()
        if scheduler.pending is not None:
            return
        observation = self.session.observation(player)
        decision = scheduler.schedule(
            session_id=self._session_id,
            revision=self._revision,
            player=player,
            observation=observation,
            actions=actions,
        )
        if decision is not None:
            self._llm_state = "thinking"
            self._llm_error = None

    def _on_async_error(
        self,
        scheduler: AsyncOpponentScheduler,
        decision: AsyncDecision,
        error: BaseException,
    ) -> None:
        with self._lock:
            if self._closed or scheduler is not self._async_scheduler:
                return
            if not scheduler.is_current(decision):
                return
            if decision.session_id != self._session_id:
                return
            if decision.revision != self._revision:
                return
            if decision.player is not decision_player(self.session.game):
                return
            self._set_llm_error_locked(error)

    def _on_async_result(
        self,
        scheduler: AsyncOpponentScheduler,
        decision: AsyncDecision,
        raw_action: object,
    ) -> None:
        with self._lock:
            if self._closed or scheduler is not self._async_scheduler:
                return
            if not scheduler.is_current(decision):
                return
            if decision.session_id != self._session_id:
                return
            if decision.revision != self._revision:
                return
            player = decision_player(self.session.game)
            if player is not decision.player or player is self.human:
                return
            actions = list(self.session.legal_actions(player))
            if isinstance(raw_action, Mapping):
                try:
                    action = Action.from_dict(raw_action)
                except (TypeError, ValueError):
                    self._set_llm_error_locked("Codex opponent returned an invalid action")
                    return
            else:
                action = raw_action
            if not isinstance(action, Action) or action not in actions:
                self._set_llm_error_locked("Codex opponent returned an invalid action")
                return
            try:
                self._accept_ai_action_locked(player, action, None)
            except ArchivePersistenceError as exc:
                self._set_llm_error_locked("match archive is unavailable")
                self.mark_archive_failed(exc)
            except Exception as exc:
                # Keep foreign process details out of browser payloads while
                # leaving local engine failures visible as a stable diagnostic.
                self._set_llm_error_locked(exc)

    def _accept_ai_action_locked(
        self,
        player: object,
        action: Action,
        presentation_steps: list[dict[str, Any]] | None,
    ) -> bool:
        """Validate/project/execute one already selected opponent action."""

        # A failed checkpoint quarantines the match.  Check before building
        # the public event or touching engine state so retry/late callbacks
        # cannot advance an archive past its last durable revision.
        self._ensure_archive_healthy_locked()

        event = self._public_event_locked(
            player, action, self.session.observation(self.human)
        )
        decision_count = len(self._ai_decisions)
        action_count = None
        if getattr(self.opponent_agent, "policy_version", None) == "tactical_v2":
            action_count = len(action_log_dict(self.session.action_log).get("actions", []))
            self._ai_decisions.append(capture_decision(
                self.opponent_agent, action, action_seq=action_count + 1,
                turn=int(self.session.game.turn),
                seat=list(self.session.game.players).index(player),
            ))
        self._pending_event = copy.deepcopy(event)
        try:
            terminal, action_error, effects, effects_truncated = self._execute_with_effects_locked(
                player, action, event, self.session.observation(self.human)
            )
        except Exception:
            self._pending_event = None
            if action_count is not None and len(action_log_dict(self.session.action_log).get("actions", [])) == action_count:
                del self._ai_decisions[decision_count:]
            raise
        if action_error is not None:
            self._pending_event = None
            del self._ai_decisions[decision_count:]
            raise RuntimeError("Opponent action was rejected") from action_error
        self._append_event_locked(event)
        self._ai_decisions_dropped += trim_decisions(self._ai_decisions)
        self._revision += 1
        step = self._presentation_step_locked(event, effects, effects_truncated)
        self._record_presentation_step_locked(step)
        if presentation_steps is not None:
            presentation_steps.append(step)
        if terminal:
            self._llm_state = "idle"
            self._llm_error = None
            return True
        self._llm_state = "idle"
        self._llm_error = None
        self._schedule_async_ai_locked()
        return False

    def _advance_ai_locked(
        self, presentation_steps: list[dict[str, Any]] | None = None
    ) -> None:
        """Run the supplied agent until human input or terminal state."""

        if self._async_opponent:
            self._schedule_async_ai_locked()
            return

        while not _game_ended(self.session.game):
            player = decision_player(self.session.game)
            if player is None or player is self.human:
                return
            actions = list(self.session.legal_actions(player))
            if not actions:
                raise RuntimeError("No legal decision for the opponent")
            choose_action = getattr(self.session, "choose_action", None)
            if callable(choose_action):
                action = choose_action(player, agent=self.opponent_agent)
            else:
                observation = self.session.observation(player)
                action = self.opponent_agent.choose_action(observation, actions)
            if isinstance(action, Mapping):
                try:
                    action = Action.from_dict(action)
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("Opponent returned an invalid action") from exc
            if not isinstance(action, Action) or action not in actions:
                raise RuntimeError("Opponent returned an unavailable action")
            try:
                terminal = self._accept_ai_action_locked(
                    player, action, presentation_steps
                )
            except RuntimeError as exc:
                raise RuntimeError(str(exc)) from exc
            if terminal:
                return

    def handle_action(self, payload: object) -> dict[str, Any]:
        """Validate and execute one browser action, returning a new snapshot.

        ``WebActionError`` carries status 400 for malformed JSON values and
        status 409 for an old revision or an action that is no longer legal.
        """

        with self._lock:
            try:
                self._ensure_archive_healthy_locked()
            except ArchivePersistenceError as exc:
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            current = self._snapshot_locked()
            if not isinstance(payload, Mapping):
                raise WebActionError("request body must be a JSON object", 400, current)

            if payload.get("session_id") != self._session_id:
                current["error"] = "stale session"
                raise WebActionError(current["error"], 409, current)

            revision = payload.get("revision")
            if type(revision) is not int:
                current["error"] = "revision must be an integer"
                raise WebActionError(current["error"], 400, current)
            if revision != self._revision:
                current["error"] = "stale revision"
                raise WebActionError(current["error"], 409, current)

            raw_action = payload.get("action")
            try:
                action = Action.from_dict(raw_action)
            except (TypeError, ValueError) as exc:
                current["error"] = str(exc)
                raise WebActionError(str(exc), 400, current) from exc

            player, actions = self._decision_actions_locked()
            if player is not self.human:
                current["error"] = "it is not the human player's turn"
                raise WebActionError(current["error"], 409, current)
            if action not in actions:
                current["error"] = "action is unavailable or stale"
                raise WebActionError(current["error"], 409, current)

            event = self._public_event_locked(
                self.human, action, current["observation"]
            )
            self._pending_event = copy.deepcopy(event)
            try:
                terminal, action_error, effects, effects_truncated = self._execute_with_effects_locked(
                    self.human, action, event, self.session.observation(self.human)
                )
            except ArchivePersistenceError as exc:
                self._pending_event = None
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            except Exception:
                self._pending_event = None
                raise
            if action_error is not None:
                self._pending_event = None
                current = self._snapshot_locked()
                current["error"] = str(action_error)
                raise WebActionError(str(action_error), 409, current) from action_error

            self._append_event_locked(event)
            self._revision += 1
            human_step = self._presentation_step_locked(
                event, effects, effects_truncated
            )
            self._record_presentation_step_locked(human_step)
            presentation_steps = [human_step]
            if terminal:
                response = self._snapshot_locked()
                response["presentation_steps"] = presentation_steps
                return response
            try:
                self._advance_ai_locked(presentation_steps)
            except ArchivePersistenceError as exc:
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            response = self._snapshot_locked()
            response["presentation_steps"] = presentation_steps
            return response

    def retry_opponent(self, payload: object) -> dict[str, Any]:
        """Start a fresh Codex request after a paused adapter failure."""

        retry_token = None
        old_scheduler = None
        with self._lock:
            current = self._snapshot_locked()
            try:
                self._ensure_archive_healthy_locked()
            except ArchivePersistenceError as exc:
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            if not self._async_opponent:
                current["error"] = "opponent retry is available only for Codex matches"
                raise WebActionError(current["error"], 409, current)
            if not isinstance(payload, Mapping):
                raise WebActionError("request body must be a JSON object", 400, current)
            if payload.get("session_id") != self._session_id:
                current["error"] = "stale session"
                raise WebActionError(current["error"], 409, current)
            revision = payload.get("revision")
            if type(revision) is not int:
                current["error"] = "revision must be an integer"
                raise WebActionError(current["error"], 400, current)
            if revision != self._revision:
                current["error"] = "stale revision"
                raise WebActionError(current["error"], 409, current)
            if self._retrying:
                current["error"] = "opponent retry is already in progress"
                raise WebActionError(current["error"], 409, current)
            if self._llm_state != "error":
                current["error"] = "opponent retry is unavailable"
                raise WebActionError(current["error"], 409, current)
            if _game_ended(self.session.game):
                current["error"] = "match is over"
                raise WebActionError(current["error"], 409, current)
            config = copy.deepcopy(self._codex_config or {})
            self._retrying = True
            self._retry_token += 1
            retry_token = self._retry_token
            # Reserve this retry while the replacement is constructed outside
            # the match lock.  A second same-revision request must not create
            # another adapter and later overwrite the first scheduler.
            self._llm_state = "thinking"
            self._llm_error = None
            old_scheduler = self._async_scheduler
            self._async_scheduler = None
            if old_scheduler is not None:
                old_scheduler.invalidate()

        if old_scheduler is not None:
            old_scheduler.close(wait=False)
        try:
            agent = _create_opponent_agent(
                "codex",
                seed=None,
                model=config.get("model"),
                timeout=config.get("timeout"),
            )
            agent_config = codex_config_from_agent(agent)
        except Exception as exc:
            with self._lock:
                if self._closed or retry_token != self._retry_token:
                    raise WebActionError("match is closed", 409, self._snapshot_locked()) from exc
                self._retrying = False
                self._set_llm_error_locked(exc)
                failed = self._snapshot_locked()
                failed["error"] = self._llm_error
                raise WebActionError(self._llm_error or "Codex retry failed", 503, failed) from exc

        with self._lock:
            if (
                self._closed
                or retry_token != self._retry_token
                or not self._retrying
                or self._session_id != payload.get("session_id")
                or self._revision != revision
            ):
                # The fresh adapter has not been exposed to a game state; let
                # its asynchronous cleanup happen without blocking this lock.
                if retry_token == self._retry_token:
                    self._retrying = False
                close = getattr(agent, "close", None)
                if callable(close):
                    threading.Thread(target=close, daemon=True).start()
                current = self._snapshot_locked()
                current["error"] = "stale session"
                raise WebActionError(current["error"], 409, current)
            self.opponent_agent = agent
            self._codex_config = agent_config
            self._retrying = False
            self._llm_state = "idle"
            self._llm_error = None
            self._schedule_async_ai_locked()
            return self._snapshot_locked()

    def concede(self, payload: object) -> dict[str, Any]:
        """Concede the active match through the human player's engine API.

        Surrender is deliberately kept outside ``legal_actions``.  It is a
        browser control, and exposing it as a normal agent action would also
        make it available to the opponent agent.  The session still executes
        the explicit action so the terminal result remains replayable.
        """

        with self._lock:
            try:
                self._ensure_archive_healthy_locked()
            except ArchivePersistenceError as exc:
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            current = self._snapshot_locked()
            if not isinstance(payload, Mapping):
                raise WebActionError("request body must be a JSON object", 400, current)

            if payload.get("session_id") != self._session_id:
                current["error"] = "stale session"
                raise WebActionError(current["error"], 409, current)

            revision = payload.get("revision")
            if type(revision) is not int:
                current["error"] = "revision must be an integer"
                raise WebActionError(current["error"], 400, current)
            if revision != self._revision:
                current["error"] = "stale revision"
                raise WebActionError(current["error"], 409, current)
            if current.get("outcome") is not None:
                current["error"] = "match is over"
                raise WebActionError(current["error"], 409, current)

            # A human may surrender while the asynchronous opponent is still
            # thinking.  Invalidate the captured revision before touching the
            # engine so a late response cannot execute after this terminal
            # action has been accepted.
            self._invalidate_async_locked()
            concede_action = Action(type=CONCEDE)
            event = self._public_event_locked(
                self.human, concede_action, current["observation"]
            )
            self._pending_event = copy.deepcopy(event)
            # Concession normally has no presentation effects, but it still
            # runs through the same observer lifecycle as every session
            # execution so a lightweight/future engine cannot leak records
            # into the next decision.
            self._effect_timeline.begin(
                self.human,
                observation=self.session.observation(self.human),
                public_event=event,
            )
            action_error: ActionError | None = None
            try:
                self.session.execute(self.human, concede_action)
            except GameOver:
                # GameSession records the explicit action and finalizes the
                # action log before propagating the engine's terminal signal.
                pass
            except ActionError as exc:
                action_error = exc
            except ArchivePersistenceError as exc:
                self._pending_event = None
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            except Exception:
                self._pending_event = None
                raise
            finally:
                self._effect_timeline.end()
            if action_error is not None:
                self._pending_event = None
                current = self._snapshot_locked()
                current["error"] = str(action_error)
                raise WebActionError(str(action_error), 409, current) from action_error

            if not _game_ended(self.session.game):
                self._pending_event = None
                current = self._snapshot_locked()
                current["error"] = "could not concede the match"
                raise WebActionError(current["error"], 409, current)

            self._append_event_locked(event)
            self._revision += 1
            self._llm_state = "idle"
            self._llm_error = None
            return self._snapshot_locked()

    def asset(self, kind: str, card_id: str) -> tuple[bytes, str, bool] | object | None:
        """Resolve one visible card asset to bytes and a content type.

        Unknown card ids, unsupported kinds, unavailable resolvers and resolver
        errors all return ``None``.  This is deliberately a local allowlist
        derived from the current observation, so hidden opponent cards cannot
        be probed through this route.
        """

        if kind not in _ASSET_KINDS or not isinstance(card_id, str):
            return None
        with self._lock:
            if card_id not in visible_card_ids(self.session.observation(self.human)):
                return None
        # A cache miss may download an image for up to two locale timeouts.
        # Respond immediately so image requests cannot monopolize the
        # browser's per-origin connections and delay player actions.
        future = self.assets.request_asset(card_id, kind, locale=self.locale)
        try:
            asset = future.result(timeout=0.05)
        except FutureTimeout:
            return _ASSET_PENDING
        except Exception:
            return None
        if asset is None:
            return None
        return asset.data, asset.media_type, asset.is_placeholder


class WebGameManager:
    """Own the lobby and at most one active :class:`WebGame`.

    ``WebGame`` remains the single-match decision boundary.  This manager only
    constructs a fresh match from lobby input and discards it after a terminal
    result has been returned to the lobby.  Keeping that lifecycle here avoids
    adding lobby branches to action validation and execution.
    """

    def __init__(
        self,
        *,
        seed: int | None = None,
        opponent: str = "radical",
        codex_model: str | None = None,
        codex_timeout: float | None = None,
        asset_resolver: object | None = None,
        arena_store: object | None = None,
        deck_store: object | None = None,
        archive_store: object | None = None,
        catalog: object | None = None,
    ) -> None:
        if seed is not None and type(seed) is not int:
            raise ValueError("seed must be an integer or None")
        self._base_seed = seed
        self._opponent_default = _validate_opponent(opponent)
        if codex_model is not None:
            codex_model = validate_codex_model(codex_model)
        if codex_timeout is not None:
            codex_timeout = codex_defaults(None, codex_timeout)[1]
        self._codex_model_default = codex_model
        self._codex_timeout_default = codex_timeout
        self._asset_resolver = asset_resolver
        self._arena_store = arena_store
        self._deck_store = deck_store
        self._archive_store = archive_store
        self._archive_owner = False
        self._catalog = catalog
        self._deck_service = None
        self._asset_service: AssetService | None = None
        self._match_count = 0
        self._active: WebGame | None = None
        self._active_arena_match_id: str | None = None
        self._arena_result_recorded = False
        self._arena_service = None
        self._lock = threading.RLock()
        if self._archive_store is not None:
            self._archive_store.acquire_owner()
            self._archive_owner = True

    @property
    def active(self) -> WebGame | None:
        """Return the current match for internal server adapters."""

        with self._lock:
            return self._active

    @property
    def opponent_default(self) -> str:
        return self._opponent_default

    def _lobby_snapshot_locked(self) -> dict[str, Any]:
        payload = {
            "mode": "lobby",
            "opponent": self._opponent_default,
        }
        if self._opponent_default == "codex":
            payload["codex_model"] = self._codex_model_default
        return payload

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = self._active
            if active is None:
                return self._lobby_snapshot_locked()
            return active.snapshot()

    def error_payload(self, message: str) -> dict[str, Any]:
        with self._lock:
            active = self._active
            payload = (
                active.error_payload(message)
                if active is not None
                else self._lobby_snapshot_locked()
            )
            if active is None:
                payload["error"] = str(message)
            return payload

    def _next_seed_locked(self) -> int | None:
        if self._base_seed is None:
            return None
        return self._base_seed + self._match_count

    def _asset_service_locked(self) -> AssetService:
        """Return the one asset service shared by all manager matches."""

        if self._asset_service is None:
            self._asset_service = (
                AssetService()
                if self._asset_resolver is None
                else AssetService(resolver=self._asset_resolver)
            )
        return self._asset_service

    def _arena_locked(self):
        if self._arena_service is None:
            from fireplace.arena.store import ArenaStoreConflict, ArenaStoreCorrupt
            from .arena_service import ArenaService

            try:
                self._arena_service = ArenaService(
                    store=self._arena_store,
                    catalog=self._catalog,
                    preserve_pending=(
                        self._preserve_arena_pending_locked
                        if self._archive_store is not None
                        else None
                    ),
                )
            except (ArenaStoreConflict, ArenaStoreCorrupt) as exc:
                raise WebLifecycleError(str(exc), 409, self._lobby_snapshot_locked()) from exc
            except OSError as exc:
                raise WebLifecycleError("Arena or match archive is unavailable", 503, self._lobby_snapshot_locked()) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, self._lobby_snapshot_locked()) from exc
        return self._arena_service

    def _preserve_arena_pending_locked(self, run: object) -> bool:
        """Keep a pending Arena run only when its match archive exists."""

        match_id = getattr(run, "pending_match_id", None)
        if not isinstance(match_id, str) or self._archive_store is None:
            return False
        try:
            return store_find_arena(self._archive_store, match_id) is not None
        except (OSError, ValueError):
            # Store corruption or an I/O failure must stay visible to the
            # caller; ArenaService will surface its construction exception.
            raise

    @staticmethod
    def _arena_format_matches(run: object, metadata: Mapping[str, Any]) -> bool:
        """Compare saved identities without loading historical data on resume."""
        format_id = getattr(run, "format_id", "custom_v1")
        if metadata.get("format_id", "custom_v1") != format_id:
            return False
        if format_id == "custom_v1":
            return True
        return (metadata.get("data_profile") == run.data_profile
                and metadata.get("ai_draft") == run.ai_drafts.get(str(run.match_index)))

    def _archive_metadata_locked(
        self,
        *,
        mode: str,
        locale: str,
        opponent: str,
        seed: object,
        agent_state: Mapping[str, Any] | None = None,
        battle_mode: str = "human",
        run: object | None = None,
        match_id: str | None = None,
    ) -> dict[str, Any]:
        battle_mode = _validate_battle_mode(battle_mode)
        metadata: dict[str, Any] = {
            "mode": mode,
            "locale": locale,
            "opponent": opponent,
            "seed": seed,
            "human_seat": 0,
        }
        if battle_mode != "human":
            metadata["battle_mode"] = battle_mode
        if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
            from .automated_game import validate_automated_agent_state

            automated = validate_automated_agent_state(
                agent_state, expected_battle_mode=battle_mode
            )
            self_state = automated["controllers"][0]
            metadata["codex_self_model"] = self_state["model"]
            metadata["codex_self_timeout"] = self_state["timeout"]
            if battle_mode == _AUTOMATION_BATTLE_MODE:
                state_for_mcts = automated["controllers"][1]
                opponent = "mcts"
                metadata["codex_timeout"] = self_state["timeout"]
            else:
                opponent_state = automated["controllers"][1]
                metadata["codex_model"] = opponent_state["model"]
                metadata["codex_timeout"] = opponent_state["timeout"]
                opponent = "codex"
            if opponent == "mcts":
                if not isinstance(state_for_mcts, Mapping):
                    raise ValueError("MCTS archive is missing opponent state")
                policy_version = state_for_mcts.get("policy_version")
                search_config = state_for_mcts.get("search_config")
                if not isinstance(policy_version, str) or not policy_version:
                    raise ValueError("MCTS archive has an invalid policy version")
                if not isinstance(search_config, Mapping):
                    raise ValueError("MCTS archive has an invalid search configuration")
                metadata["mcts_policy_version"] = policy_version
                metadata["mcts_search_config"] = copy.deepcopy(dict(search_config))
        elif opponent == "mcts":
            state_for_mcts = agent_state
            if not isinstance(state_for_mcts, Mapping):
                raise ValueError("MCTS archive is missing opponent state")
            policy_version = state_for_mcts.get("policy_version")
            search_config = state_for_mcts.get("search_config")
            if not isinstance(policy_version, str) or not policy_version:
                raise ValueError("MCTS archive has an invalid policy version")
            if not isinstance(search_config, Mapping):
                raise ValueError("MCTS archive has an invalid search configuration")
            metadata["mcts_policy_version"] = policy_version
            metadata["mcts_search_config"] = copy.deepcopy(dict(search_config))
        elif opponent == "codex":
            if not isinstance(agent_state, Mapping):
                raise ValueError("Codex archive is missing opponent state")
            codex_state = validate_codex_state(agent_state)
            metadata["codex_model"] = codex_state["model"]
            metadata["codex_timeout"] = codex_state["timeout"]
        if run is not None:
            metadata["arena"] = {
                "run_id": getattr(run, "run_id", None),
                "match_id": match_id or getattr(run, "pending_match_id", None),
                "match_index": getattr(run, "match_index", None),
            }
            if getattr(run, "format_id", "custom_v1") != "custom_v1":
                metadata["arena"].update(
                    format_id=run.format_id,
                    data_profile=copy.deepcopy(run.data_profile),
                    ai_draft=copy.deepcopy(run.ai_drafts.get(str(run.match_index))),
                    combat_implementation="current_fireplace",
                    offer_policy_accuracy="reconstructed",
                )
        return metadata

    def _build_archived_active_locked(
        self,
        *,
        game: object,
        human: object,
        opponent_agent: object,
        mode: str,
        locale: str,
        seed: object,
        opponent_kind: str,
        battle_mode: str = "human",
        run: object | None = None,
        match_id: str | None = None,
        initial_events: list[Mapping[str, Any]] | None = None,
        initial_revision: int = 0,
        restored_session: GameSession | None = None,
        existing_envelope: Mapping[str, Any] | None = None,
    ) -> WebGame:
        """Create a WebGame with its archive checkpoint wired before setup."""

        battle_mode = _validate_battle_mode(battle_mode)
        automated = battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}
        if automated:
            from .automated_game import (
                AutomatedGame,
                capture_automated_agent_state,
            )

            if not isinstance(opponent_agent, (tuple, list)):
                raise ValueError("automated match requires two controllers")
            active_class = AutomatedGame
        else:
            active_class = WebGame

        if self._archive_store is None:
            session = restored_session or GameSession(game, {})
            return active_class(
                session,
                human,
                opponent_agent,
                **({"battle_mode": battle_mode} if automated else {}),
                asset_service=self._asset_service_locked(),
                locale=locale,
                initial_events=initial_events,
                initial_revision=initial_revision,
            )

        from ..action_log import ActionLog

        session_ref: dict[str, GameSession] = {}
        initial_agent_state = (
            capture_automated_agent_state(opponent_agent, battle_mode)
            if automated
            else capture_agent_state(opponent_agent)
        )
        metadata = self._archive_metadata_locked(
            mode=mode,
            locale=locale,
            opponent=opponent_kind,
            seed=seed,
            agent_state=initial_agent_state if isinstance(initial_agent_state, Mapping) else None,
            battle_mode=battle_mode,
            run=run,
            match_id=match_id,
        )
        if restored_session is not None:
            session = restored_session
            log = session.action_log
            if existing_envelope is None:
                raise ValueError("restored match is missing its archive envelope")
            envelope_id = canonical_game_id(existing_envelope.get("game_id"))
            log_id = canonical_game_id(log.to_dict().get("game_id"))
            if log_id != envelope_id:
                raise ValueError("restored match archive identity does not match its log")
            archive_id = envelope_id
            archive_revision = envelope_revision(existing_envelope)
            context: dict[str, Any] = {
                "revision": archive_revision,
                "active": None,
                "failed": None,
            }
        else:
            log = ActionLog(game, mode=mode, seed=seed)
            # The first archive must contain the pre-setup RNG position and
            # replay signature.  GameSession.start() calls this hook later,
            # but a crash between archive creation and that call would
            # otherwise leave an unrecoverable header.
            log.before_start(game)
            archive = store_create(
                self._archive_store,
                log,
                metadata,
                agent_state=initial_agent_state,
                public=None,
            )
            archive_envelope = as_envelope(archive)
            archive_id = canonical_game_id(
                archive_envelope.get("game_id") or log.to_dict().get("game_id")
            )
            archive_revision = envelope_revision(archive_envelope)
            session = GameSession(game, {}, action_log=log)
            context = {
                "revision": archive_revision,
                "active": None,
                "failed": None,
            }

        session_ref["session"] = session
        active = None

        def on_save(saved_log: object | None = None) -> None:
            current_log = saved_log if saved_log is not None else session_ref["session"].action_log
            active = context.get("active")
            try:
                public = None
                if active is not None and (active._started or restored_session is not None):
                    with active.lock:
                        active._ensure_archive_healthy_locked()
                        public = public_payload(active._snapshot_locked())
                        if active._ai_decisions:
                            active._ai_decisions_dropped += trim_decisions(active._ai_decisions)
                            metadata["ai_decisions"] = copy.deepcopy(active._ai_decisions)
                            metadata["ai_decisions_dropped"] = active._ai_decisions_dropped
                envelope = store_save(
                    self._archive_store,
                    archive_id,
                    log=current_log,
                    metadata=metadata,
                    agent_state=(
                        capture_automated_agent_state(
                            active.controllers if active is not None else opponent_agent,
                            battle_mode,
                        )
                        if automated
                        else capture_agent_state(
                            active.opponent_agent if active is not None else opponent_agent
                        )
                    ),
                    public=public,
                    expected_revision=context["revision"],
                )
                context["revision"] = envelope_revision(envelope)
                if active is not None:
                    active.bind_archive(archive_id, context["revision"])
            except Exception as exc:
                context["failed"] = str(exc)
                if active is not None:
                    active.mark_archive_failed(exc)
                raise ArchivePersistenceError(
                    "match archive could not be saved: %s" % exc
                ) from exc

        try:
            # The callback is attached before GameSession/WebGame setup can
            # emit before_start/started saves.  Agent creation happens before
            # this callback, so its state is always captured by the first
            # checkpoint.
            attach_on_save(log, on_save)
            active = active_class(
                session,
                human,
                opponent_agent,
                **({"battle_mode": battle_mode} if automated else {}),
                asset_service=self._asset_service_locked(),
                locale=locale,
                initial_events=initial_events,
                initial_revision=initial_revision,
                initial_ai_decisions=restore_decisions(envelope_metadata(existing_envelope)) if existing_envelope is not None else None,
                initial_ai_decisions_dropped=int(envelope_metadata(existing_envelope).get("ai_decisions_dropped", 0)) if existing_envelope is not None else 0,
                start_immediately=False,
            )
        except Exception:
            session.close()
            raise
        context["active"] = active
        active.bind_archive(archive_id, context["revision"])
        try:
            if restored_session is not None:
                # Recovery may repair an old signature or a pre-start/terminal
                # checkpoint. Persist that validated prefix before a controller
                # can continue, retaining the restored seat's public view.
                on_save(log)
            # Start only after the callback can see the live WebGame.  This
            # makes setup and the initial AI prefix durable with its public
            # event projection, while the callback skips the INVALID setup
            # snapshot until the engine has actually started.
            active.start()
            # Publish the final post-construction observation/events after
            # setup even when no accepted decision occurred.
            on_save(log)
        except Exception:
            active.close(wait=False)
            raise
        return active

    def _decks_locked(self):
        if self._deck_service is None:
            from .decks import DeckService

            self._deck_service = DeckService(store=self._deck_store, catalog=self._catalog)
        return self._deck_service

    def _verify_terminal_archive_locked(
        self, active: WebGame, state: Mapping[str, Any]
    ) -> None:
        """Verify the durable terminal row before releasing a live match.

        ActionLog's terminal callback is the authoritative write.  A failed
        directory fsync can still leave a complete replacement on disk, so a
        terminal session marked archive-failed may be released only after the
        durable raw log exactly matches the live accepted prefix/result.
        """

        if self._archive_store is None or active.archive_game_id is None:
            return
        try:
            envelope = store_get(self._archive_store, active.archive_game_id)
        except OSError as exc:
            raise WebLifecycleError(
                "match archive is unavailable", 503, dict(state)
            ) from exc
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 409, dict(state)) from exc
        if envelope is None:
            raise WebLifecycleError(
                "terminal match archive is missing", 503, dict(state)
            )
        try:
            status = envelope_status(envelope)
            durable_log = envelope_log(envelope)
            live_log = action_log_dict(active.session.action_log)
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 409, dict(state)) from exc
        if status != "complete":
            raise WebLifecycleError(
                "terminal match archive is not durable; resume from history", 503, dict(state)
            )
        if durable_log != live_log:
            raise WebLifecycleError(
                "terminal match archive does not match the live result", 503, dict(state)
            )
        outcome = state.get("outcome")
        summary = archive_summary(envelope)
        if isinstance(outcome, Mapping) and summary.get("human_won") != outcome.get("human_won"):
            raise WebLifecycleError(
                "terminal match archive result does not match the live result", 503, dict(state)
            )
        if self._active_arena_match_id is not None:
            metadata = envelope_metadata(envelope)
            arena_metadata = metadata.get("arena")
            service = self._arena_locked()
            run = service.run
            identity_matches = (
                isinstance(arena_metadata, Mapping)
                and arena_metadata.get("match_id") == self._active_arena_match_id
            )
            pending_matches = (
                run is not None
                and run.stage == "match"
                and arena_metadata.get("run_id") == run.run_id
                and arena_metadata.get("match_index") == run.match_index
                and run.pending_match_id == self._active_arena_match_id
                and self._arena_format_matches(run, arena_metadata)
            ) if isinstance(arena_metadata, Mapping) else False
            if not identity_matches or (
                not self._arena_result_recorded and not pending_matches
            ):
                raise WebLifecycleError(
                    "terminal Arena archive does not match the pending run", 503, dict(state)
                )

    def matches_list(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Return newest-first summaries owned by this account."""

        with self._lock:
            if type(offset) is not int or offset < 0 or offset > 1_000_000:
                raise WebLifecycleError("offset must be between 0 and 1000000", 400, self.snapshot())
            if type(limit) is not int or limit < 1 or limit > 100:
                raise WebLifecycleError("limit must be between 1 and 100", 400, self.snapshot())
            if self._archive_store is None:
                return {"matches": [], "offset": offset, "limit": limit, "total": 0}
            try:
                self._reconcile_arena_archive_locked()
                rows = store_list(self._archive_store)
                total = len(rows)
                selected = rows[offset : offset + limit]
                return {
                    "matches": [archive_summary(row) for row in selected],
                    "offset": offset,
                    "limit": limit,
                    "total": total,
                }
            except OSError as exc:
                raise WebLifecycleError("match archive is unavailable", 503, self.snapshot()) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, self.snapshot()) from exc

    def match_detail(self, game_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                game_id = canonical_game_id(game_id)
                envelope = store_get(self._archive_store, game_id) if self._archive_store is not None else None
            except (OSError, ValueError) as exc:
                status = 503 if isinstance(exc, OSError) else 400 if "canonical UUID" in str(exc) else 409
                raise WebLifecycleError(str(exc), status, self.snapshot()) from exc
            if envelope is None:
                raise WebLifecycleError("match archive was not found", 404, self.snapshot())
            try:
                public = envelope_public(envelope)
                return {
                    "match": archive_summary(envelope),
                    "events": public.get("events", []),
                    "snapshot": public.get("snapshot"),
                }
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, self.snapshot()) from exc

    def match_download(self, game_id: str) -> tuple[str, dict[str, Any]]:
        with self._lock:
            try:
                game_id = canonical_game_id(game_id)
                envelope = store_get(self._archive_store, game_id) if self._archive_store is not None else None
            except (OSError, ValueError) as exc:
                status = 503 if isinstance(exc, OSError) else 400 if "canonical UUID" in str(exc) else 409
                raise WebLifecycleError(str(exc), status, self.snapshot()) from exc
            if envelope is None:
                raise WebLifecycleError("match archive was not found", 404, self.snapshot())
            try:
                log = envelope_log(envelope)
                status = envelope_status(envelope)
                if status not in {"complete", "abandoned"}:
                    raise WebLifecycleError("unfinished matches cannot be downloaded", 409, self.snapshot())
                if status == "abandoned":
                    log = copy.deepcopy(log)
                    log["status"] = "abandoned"
                    metadata = envelope_metadata(envelope)
                    if metadata.get("finished_at") is not None:
                        log["finished_at"] = metadata.get("finished_at")
                arena = envelope_metadata(envelope).get("arena")
                if isinstance(arena, Mapping) and arena.get("format_id") == "wild_2016_09_02":
                    log = copy.deepcopy(log)
                    log["arena_draft"] = copy.deepcopy(dict(arena))
                return game_id, log
            except WebLifecycleError:
                raise
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, self.snapshot()) from exc

    def resume_match(self, payload: object) -> dict[str, Any]:
        with self._lock:
            current = self.snapshot()
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, current)
            try:
                game_id = canonical_game_id(payload.get("game_id"))
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc
            revision = payload.get("revision")
            if type(revision) is not int or revision < 0:
                raise WebLifecycleError("revision must be a nonnegative integer", 400, current)
            active = self._active
            if active is not None:
                if active.archive_game_id == game_id:
                    if active.archive_failed is None:
                        return {
                            "state": active.snapshot(),
                            "match_url": "/?arena=1" if self._active_arena_match_id is not None else "/",
                        }
                    # The live engine may have advanced after the last
                    # durable checkpoint.  Detach it before replaying the
                    # archive so a retry cannot expose unsaved state.
                    self._active = None
                    self._active_arena_match_id = None
                    self._arena_result_recorded = False
                    active.close(wait=False)
                    active = None
                else:
                    raise WebLifecycleError("finish the active match first", 409, current)
            if self._archive_store is None:
                raise WebLifecycleError("match archive is unavailable", 503, current)
            try:
                envelope = store_get(self._archive_store, game_id)
            except OSError as exc:
                raise WebLifecycleError("match archive is unavailable", 503, current) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, current) from exc
            if envelope is None:
                raise WebLifecycleError("match archive was not found", 404, current)
            try:
                actual_revision = envelope_revision(envelope)
                if revision != actual_revision:
                    raise WebLifecycleError("stale match archive revision", 409, current)
                log = envelope_log(envelope)
                if envelope_status(envelope) != "in_progress":
                    raise WebLifecycleError("only unfinished matches can be resumed", 409, current)
            except WebLifecycleError:
                raise
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, current) from exc
            metadata = envelope_metadata(envelope)
            mode = metadata.get("mode", log.get("mode"))
            if mode not in {"normal", "arena"}:
                raise WebLifecycleError("unsupported archived match mode", 409, current)
            opponent_kind = metadata.get("opponent", "radical" if mode == "normal" else "mcts")
            battle_mode = metadata.get("battle_mode", "human")
            restored: GameSession | None = None
            building_active = False
            try:
                battle_mode = _validate_battle_mode(battle_mode)
                opponent_kind = _validate_opponent(opponent_kind)
                if battle_mode == _AUTOMATION_BATTLE_MODE and opponent_kind != "mcts":
                    raise ValueError("archived automated match must use MCTS seat one")
                if battle_mode == _CODEX_DUEL_BATTLE_MODE and opponent_kind != "codex":
                    raise ValueError("archived Codex duel must use Codex seat one")
                locale = _validate_locale(metadata.get("locale", "zhCN"))
                policy_version = None
                search_config = None
                codex_model = None
                codex_timeout = None
                codex_self_model = None
                codex_self_timeout = None
                automated_state = None
                if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                    from .automated_game import validate_automated_agent_state

                    automated_state = validate_automated_agent_state(
                        envelope.get("agent_state"), expected_battle_mode=battle_mode
                    )
                    codex_self_state = automated_state["controllers"][0]
                    if battle_mode == _AUTOMATION_BATTLE_MODE:
                        mcts_state = automated_state["controllers"][1]
                        policy_version, search_config = _resolve_mcts_archive_options(
                            metadata, mcts_state
                        )
                        codex_self_model, codex_self_timeout = _resolve_codex_archive_options(
                            metadata,
                            codex_self_state,
                            model_keys=("codex_self_model", "codex_model"),
                            timeout_keys=("codex_self_timeout", "codex_timeout"),
                        )
                        codex_model, codex_timeout = codex_self_model, codex_self_timeout
                    else:
                        codex_self_model, codex_self_timeout = _resolve_codex_archive_options(
                            metadata,
                            codex_self_state,
                            model_keys=("codex_self_model",),
                            timeout_keys=("codex_self_timeout",),
                        )
                        codex_model, codex_timeout = _resolve_codex_archive_options(
                            metadata,
                            automated_state["controllers"][1],
                            model_keys=("codex_model",),
                            timeout_keys=("codex_timeout",),
                        )
                elif opponent_kind == "mcts":
                    policy_version, search_config = _resolve_mcts_archive_options(
                        metadata, envelope.get("agent_state")
                    )
                elif opponent_kind == "codex":
                    codex_model, codex_timeout = _resolve_codex_archive_options(
                        metadata, envelope.get("agent_state")
                    )
                # Constructing the policy is deliberately before replay.  The
                # constructor validates the archived version and every closed
                # search-config key/value while the archive is still untouched.
                try:
                    if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                        codex_agent = _create_opponent_agent(
                            "codex",
                            seed=metadata.get("seed"),
                            model=codex_self_model,
                            timeout=codex_self_timeout,
                        )
                        try:
                            if battle_mode == _AUTOMATION_BATTLE_MODE:
                                seat1_agent = _create_opponent_agent(
                                    "mcts",
                                    seed=metadata.get("seed"),
                                    policy_version=policy_version,
                                    search_config=search_config,
                                )
                            else:
                                seat1_agent = _create_opponent_agent(
                                    "codex",
                                    seed=metadata.get("seed"),
                                    model=codex_model,
                                    timeout=codex_timeout,
                                )
                        except Exception:
                            close = getattr(codex_agent, "close", None)
                            if callable(close):
                                close()
                            raise
                        opponent_agent = (codex_agent, seat1_agent)
                    else:
                        opponent_agent = _create_opponent_agent(
                            opponent_kind,
                            seed=metadata.get("seed"),
                            **(
                                {
                                    "policy_version": policy_version,
                                    "search_config": search_config,
                                }
                                if opponent_kind == "mcts"
                                else {
                                    "model": codex_model,
                                    "timeout": codex_timeout,
                                }
                                if opponent_kind == "codex"
                                else {}
                            ),
                        )
                except ValueError as exc:
                    raise WebLifecycleError(str(exc), 409, current) from exc
                except Exception as exc:
                    if opponent_kind == "codex" or battle_mode in {
                        _AUTOMATION_BATTLE_MODE,
                        _CODEX_DUEL_BATTLE_MODE,
                    }:
                        raise WebLifecycleError(
                            "archived Codex opponent cannot be resumed"
                            if battle_mode == "human"
                            else "archived automated opponent cannot be resumed",
                            409,
                            current,
                        ) from exc
                    raise
                arena_metadata = metadata.get("arena")
                if mode == "arena":
                    if not isinstance(arena_metadata, Mapping):
                        raise ValueError("archived Arena match has no correlation metadata")
                    service = self._arena_locked()
                    run = service.run
                    if (
                        run is None
                        or run.stage != "match"
                        or run.run_id != arena_metadata.get("run_id")
                        or run.pending_match_id != arena_metadata.get("match_id")
                        or run.match_index != arena_metadata.get("match_index")
                        or not self._arena_format_matches(run, arena_metadata)
                    ):
                        raise ValueError("archived Arena match does not match the pending run")
                restored = restore_action_log(log)
                if not isinstance(restored, GameSession):
                    raise ValueError("archive restore did not return a live game session")
                game = restored.game
                players = list(getattr(game, "players", ()))
                human_seat = metadata.get("human_seat", 0)
                if human_seat != 0:
                    raise ValueError("archived human seat is unsupported")
                if len(players) < 2:
                    raise ValueError("archived game has no two players")
                human = players[0]
                if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                    from .automated_game import restore_automated_agent_state

                    restore_automated_agent_state(
                        opponent_agent,
                        envelope.get("agent_state"),
                        expected_battle_mode=battle_mode,
                    )
                else:
                    restore_agent_state(opponent_agent, envelope.get("agent_state"))
                public = envelope_public(envelope)
                old_snapshot = public.get("snapshot")
                events = public.get("events", [])
                initial_revision = len(log.get("actions", []))
                building_active = True
                active = self._build_archived_active_locked(
                    game=game,
                    human=human,
                    opponent_agent=opponent_agent,
                    mode=mode,
                    locale=locale,
                    seed=metadata.get("seed"),
                    opponent_kind=opponent_kind,
                    battle_mode=battle_mode,
                    run=None,
                    match_id=(metadata.get("arena") or {}).get("match_id")
                    if isinstance(metadata.get("arena"), Mapping)
                    else None,
                    initial_events=events if isinstance(events, list) else [],
                    initial_revision=initial_revision,
                    restored_session=restored,
                    existing_envelope=envelope,
                )
            except ArchivePersistenceError as exc:
                raise WebLifecycleError(str(exc), 503, current) from exc
            except (OSError, ValueError, TypeError) as exc:
                raise WebLifecycleError("archived match cannot be resumed: %s" % exc, 409, current) from exc
            except Exception as exc:
                message = (
                    "archived Codex opponent cannot be resumed"
                    if opponent_kind == "codex"
                    else "archived match cannot be resumed"
                )
                raise WebLifecycleError(message, 409, current) from exc
            finally:
                # _build_archived_active_locked owns cleanup once construction
                # begins.  Before that point restore_agent_state, Arena
                # correlation validation, or player-shape checks can fail and
                # must detach the replay session here.
                if restored is not None and not building_active:
                    restored.close()
            self._active = active
            arena_metadata = metadata.get("arena")
            self._active_arena_match_id = (
                str(arena_metadata.get("match_id"))
                if mode == "arena"
                and isinstance(arena_metadata, Mapping)
                and arena_metadata.get("match_id")
                else None
            )
            self._arena_result_recorded = False
            if self._active_arena_match_id and active.snapshot().get("outcome") is not None:
                self._settle_arena_result_locked(active.snapshot())
            return {
                "state": active.snapshot(),
                "match_url": "/?arena=1" if mode == "arena" else "/",
            }

    def abandon_match(self, payload: object) -> dict[str, Any]:
        with self._lock:
            current = self.snapshot()
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, current)
            try:
                game_id = canonical_game_id(payload.get("game_id"))
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc
            revision = payload.get("revision")
            if type(revision) is not int or revision < 0:
                raise WebLifecycleError("revision must be a nonnegative integer", 400, current)
            if self._archive_store is None:
                raise WebLifecycleError("match archive is unavailable", 503, current)
            active = self._active
            if active is not None and active.archive_game_id != game_id:
                raise WebLifecycleError("finish the active match first", 409, current)
            abandoning = False
            try:
                envelope = store_get(self._archive_store, game_id)
                if envelope is None:
                    raise WebLifecycleError("match archive was not found", 404, current)
                actual_revision = envelope_revision(envelope)
                if revision != actual_revision:
                    raise WebLifecycleError("stale match archive revision", 409, current)
                status = envelope_status(envelope)
                if status == "complete":
                    raise WebLifecycleError("completed matches cannot be abandoned", 409, current)
                if status == "in_progress" and checkpoint_is_terminal(envelope_log(envelope)):
                    raise WebLifecycleError(
                        "terminal checkpoint must be resumed to finalize its result",
                        409,
                        current,
                    )
                metadata = envelope_metadata(envelope)
                arena_metadata = metadata.get("arena")
                if metadata.get("mode") == "arena":
                    if not isinstance(arena_metadata, Mapping):
                        raise WebLifecycleError("Arena archive metadata is invalid", 409, current)
                    service = self._arena_locked()
                    run = service.run
                    if status == "in_progress":
                        if (
                            run is None
                            or run.stage != "match"
                            or run.run_id != arena_metadata.get("run_id")
                            or run.match_index != arena_metadata.get("match_index")
                            or run.pending_match_id != arena_metadata.get("match_id")
                            or not self._arena_format_matches(run, arena_metadata)
                        ):
                            raise WebLifecycleError(
                                "Arena archive does not match the pending run", 409, current
                            )
                    elif (
                        run is not None
                        and run.stage == "match"
                        and run.pending_match_id == arena_metadata.get("match_id")
                        and (
                            run.run_id != arena_metadata.get("run_id")
                            or run.match_index != arena_metadata.get("match_index")
                            or not self._arena_format_matches(run, arena_metadata)
                        )
                    ):
                        raise WebLifecycleError(
                            "Arena archive does not match the pending run", 409, current
                        )
                if status == "in_progress":
                    store_mark_abandoned(self._archive_store, game_id, expected_revision=revision)
                    abandoning = True
                elif status == "abandoned":
                    abandoning = True
                envelope = store_get(self._archive_store, game_id) or envelope
            except WebLifecycleError:
                raise
            except OSError as exc:
                raise WebLifecycleError("match archive is unavailable", 503, current) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, current) from exc
            if abandoning and metadata.get("mode") == "arena" and isinstance(arena_metadata, Mapping) and arena_metadata.get("match_id"):
                try:
                    self._settle_archive_arena_locked(
                        arena_metadata.get("match_id"),
                        False,
                        arena_metadata=arena_metadata,
                    )
                except Exception as exc:
                    if active is not None:
                        active.mark_archive_failed(exc)
                    raise WebLifecycleError(
                        "Arena result could not be settled; retry abandonment", 503, current
                    ) from exc
            if active is not None:
                self._active = None
                self._active_arena_match_id = None
                self._arena_result_recorded = False
                active.close(wait=False)
            return {"match": archive_summary(envelope)}

    def _settle_archive_arena_locked(
        self,
        match_id: object,
        human_won: bool | None,
        *,
        arena_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(match_id, str):
            return
        service = self._arena_locked()
        run = service.run
        if run is None or run.stage != "match" or run.pending_match_id != match_id:
            return
        if arena_metadata is not None and (
            arena_metadata.get("run_id") != run.run_id
            or arena_metadata.get("match_index") != run.match_index
            or arena_metadata.get("match_id") != match_id
            or not self._arena_format_matches(run, arena_metadata)
        ):
            raise WebLifecycleError(
                "Arena archive does not match the pending run", 409, self._lobby_snapshot_locked()
            )
        service.settle(match_id, human_won)

    def decks_state(self, *, locale: str = "zhCN") -> dict[str, Any]:
        with self._lock:
            try:
                return self._decks_locked().list(locale=locale)
            except OSError as exc:
                raise WebLifecycleError("deck storage is unavailable", 503, self._lobby_snapshot_locked()) from exc

    def decks_save(self, payload: object) -> dict[str, Any]:
        with self._lock:
            from .decks import DeckConflict

            current = self._lobby_snapshot_locked()
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, current)
            try:
                return self._decks_locked().save(payload, locale=payload.get("locale", "zhCN"))
            except DeckConflict as exc:
                raise WebLifecycleError(str(exc), 409, current) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc
            except OSError as exc:
                raise WebLifecycleError("deck storage is unavailable", 503, current) from exc

    def decks_delete(self, payload: object) -> dict[str, Any]:
        with self._lock:
            from .decks import DeckConflict

            current = self._lobby_snapshot_locked()
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, current)
            try:
                return self._decks_locked().delete(payload, locale=payload.get("locale", "zhCN"))
            except DeckConflict as exc:
                raise WebLifecycleError(str(exc), 409, current) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc
            except OSError as exc:
                raise WebLifecycleError("deck storage is unavailable", 503, current) from exc

    def arena_state(self, *, locale: str = "zhCN") -> dict[str, Any]:
        with self._lock:
            service = self._arena_locked()
            self._reconcile_arena_archive_locked(service)
            state = service.state(locale=locale)
            if (
                service.run is not None
                and service.run.stage == "match"
                and self._active is None
                and self._archive_store is not None
                and service.run.pending_match_id
            ):
                archive = store_find_arena(
                    self._archive_store, service.run.pending_match_id
                )
                if archive is not None:
                    state["mode"] = "resume"
                    state["resume_game_id"] = as_envelope(archive).get("game_id")
            return state

    def _reconcile_arena_archive_locked(self, service: object | None = None) -> None:
        """Settle one durable terminal Arena archive after a crash window."""

        if self._archive_store is None:
            return
        service = service or self._arena_locked()
        run = getattr(service, "run", None)
        if run is None or getattr(run, "stage", None) != "match":
            return
        match_id = getattr(run, "pending_match_id", None)
        if not isinstance(match_id, str):
            return
        try:
            archive = store_find_arena(self._archive_store, match_id)
        except OSError as exc:
            raise WebLifecycleError("match archive is unavailable", 503, self._lobby_snapshot_locked()) from exc
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 409, self._lobby_snapshot_locked()) from exc
        if archive is None:
            return
        metadata = envelope_metadata(archive)
        arena_metadata = metadata.get("arena")
        if not isinstance(arena_metadata, Mapping):
            raise WebLifecycleError("Arena archive metadata is invalid", 409, self._lobby_snapshot_locked())
        if (
            arena_metadata.get("run_id") != run.run_id
            or arena_metadata.get("match_index") != run.match_index
            or arena_metadata.get("match_id") != match_id
            or not self._arena_format_matches(run, arena_metadata)
        ):
            raise WebLifecycleError("Arena archive does not match the pending run", 409, self._lobby_snapshot_locked())
        status = envelope_status(archive)
        if status not in {"complete", "abandoned"}:
            return
        outcome = archive_summary(archive).get("human_won")
        if status == "abandoned":
            outcome = False
        service.settle(match_id, outcome)
        if self._active_arena_match_id == match_id:
            self._arena_result_recorded = True

    def arena_start(self, payload: object) -> dict[str, Any]:
        with self._lock:
            if self._active is not None:
                raise WebLifecycleError("finish the active match first", 409, self.snapshot())
            seed = self._base_seed
            return self._arena_locked().start(payload, seed=seed)

    def arena_choose_hero(self, payload: object) -> dict[str, Any]:
        with self._lock:
            return self._arena_locked().choose_hero(payload)

    def arena_choose_card(self, payload: object) -> dict[str, Any]:
        with self._lock:
            return self._arena_locked().choose_card(payload)

    def arena_start_battle(self, payload: object) -> dict[str, Any]:
        with self._lock:
            service = self._arena_locked()
            # Arena policy is server-owned, independent of lobby preferences
            # and any opponent field sent by an older client.
            opponent_kind = "mcts"
            run = service.ready_for_battle(payload)
            if self._active is not None:
                raise WebLifecycleError("finish the active match first", 409, service.state())

            from .arena_factory import build_arena_game

            match_seed = run.seed + 100_000 + run.match_index
            prepared_draft = None
            if run.format_id != "custom_v1":
                from fireplace.arena.ai_draft import draft_ai, AIDraft
                from fireplace.arena.formats import historical_profile
                try:
                    saved_draft = run.ai_drafts.get(str(run.match_index))
                    if saved_draft is not None:
                        prepared_draft = AIDraft.from_dict(saved_draft).to_dict()
                    else:
                        if historical_profile() != run.data_profile:
                            raise ValueError("historical Arena data profile changed; cannot draft opponent")
                        prepared_draft = draft_ai(match_seed, run.hero_id).to_dict()
                except (TypeError, ValueError, OSError) as exc:
                    raise WebLifecycleError(str(exc), 409, service.state()) from exc
            if self._archive_store is not None:
                # Publish the pending identity before constructing/starting
                # the engine.  A process crash in the window below therefore
                # leaves a resumable Arena run when its archive exists.
                state = (service.mark_battle_started(ai_draft=prepared_draft)
                         if prepared_draft is not None else service.mark_battle_started())
                pending_match_id = service.run.pending_match_id
                try:
                    game, human, _opponent = build_arena_game(
                        seed=match_seed,
                        nickname=run.nickname,
                        hero_id=run.hero_id,
                        deck=run.deck,
                        selected_sets=run.selected_sets,
                        **({"ai_draft": prepared_draft} if prepared_draft is not None else {}),
                    )
                    opponent_agent = _create_opponent_agent(opponent_kind, seed=match_seed)
                    active = self._build_archived_active_locked(
                        game=game,
                        human=human,
                        opponent_agent=opponent_agent,
                        mode="arena",
                        locale=run.locale,
                        seed=match_seed,
                        opponent_kind=opponent_kind,
                        run=service.run,
                        match_id=pending_match_id,
                    )
                except Exception as exc:
                    # If no checkpoint reached the store, this was only the
                    # pre-archive pending window and can be retried.  Once a
                    # checkpoint exists, leave the run in MATCH for explicit
                    # history resume/reconciliation after restart.
                    archive_exists: bool | None = None
                    try:
                        archive_exists = (
                            pending_match_id is not None
                            and store_find_arena(self._archive_store, pending_match_id) is not None
                        )
                    except OSError as lookup_exc:
                        raise WebLifecycleError(
                            "match archive is unavailable", 503, state
                        ) from lookup_exc
                    except ValueError as lookup_exc:
                        raise WebLifecycleError(str(lookup_exc), 409, state) from lookup_exc
                    if not archive_exists:
                        recover = getattr(service, "recover_pending_without_match", None)
                        if callable(recover):
                            try:
                                recover()
                            except (OSError, ValueError) as recovery_exc:
                                raise WebLifecycleError(
                                    "Arena pending state could not be recovered", 503, state
                                ) from recovery_exc
                    if isinstance(exc, WebLifecycleError):
                        raise
                    if isinstance(exc, (ArchivePersistenceError, OSError)):
                        raise WebLifecycleError(
                            "match archive is unavailable" if isinstance(exc, OSError)
                            else str(exc),
                            503,
                            state,
                        ) from exc
                    if isinstance(exc, ValueError):
                        raise WebLifecycleError(str(exc), 409, state) from exc
                    raise WebLifecycleError(
                        "Arena match construction failed", 503, state
                    ) from exc
            else:
                if prepared_draft is not None:
                    state = service.mark_battle_started(ai_draft=prepared_draft)
                try:
                    game, human, _opponent = build_arena_game(
                        seed=match_seed,
                        nickname=run.nickname,
                        hero_id=run.hero_id,
                        deck=run.deck,
                        selected_sets=run.selected_sets,
                        **({"ai_draft": prepared_draft} if prepared_draft is not None else {}),
                    )
                    active = WebGame(
                        GameSession(game, {}),
                        human,
                        _create_opponent_agent(opponent_kind, seed=match_seed),
                        asset_service=self._asset_service_locked(),
                        locale=run.locale,
                    )
                except Exception as exc:
                    if prepared_draft is None:
                        raise
                    try:
                        service.recover_pending_without_match()
                    except (OSError, ValueError) as recovery_exc:
                        raise WebLifecycleError(
                            "Arena pending state could not be recovered", 503, state
                        ) from recovery_exc
                    raise WebLifecycleError(
                        str(exc), 409 if isinstance(exc, ValueError) else 503, service.state()
                    ) from exc
                if prepared_draft is None:
                    state = service.mark_battle_started()
            self._active = active
            self._active_arena_match_id = service.run.pending_match_id
            self._arena_result_recorded = False
            return state

    def arena_retire(self, payload: object) -> dict[str, Any]:
        with self._lock:
            service = self._arena_locked()
            if self._active is not None or self._active_arena_match_id is not None:
                raise WebLifecycleError("finish the active match first", 409, service.state())
            return service.retire(payload)

    def arena_reset(self, payload: object) -> dict[str, Any]:
        with self._lock:
            if self._active_arena_match_id is not None:
                raise WebLifecycleError("finish the active match first", 409, self._arena_locked().state())
            return self._arena_locked().reset(payload)

    def start_match(self, payload: object) -> dict[str, Any]:
        """Create a fresh random-class/random-deck match from lobby input."""

        with self._lock:
            current = (
                self._active.snapshot()
                if self._active is not None
                else self._lobby_snapshot_locked()
            )
            if self._active is not None:
                raise WebLifecycleError(
                    "return to the lobby before starting another match", 409, current
                )
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, current)
            try:
                nickname = _validate_nickname(payload.get("nickname"))
                battle_mode = _validate_battle_mode(payload.get("battle_mode", "human"))
                opponent_kind = _validate_opponent(
                    payload.get("opponent", self._opponent_default)
                )
                locale = _validate_locale(payload.get("locale"))
                if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                    codex_self_model = validate_codex_model(
                        payload.get("codex_self_model", self._codex_model_default)
                    )
                    codex_model = (
                        validate_codex_model(
                            payload.get("codex_model", self._codex_model_default)
                        )
                        if battle_mode == _CODEX_DUEL_BATTLE_MODE
                        else None
                    )
                else:
                    codex_self_model = None
                    codex_model = validate_codex_model(
                        payload.get("codex_model", self._codex_model_default)
                    )
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc
            if battle_mode == _AUTOMATION_BATTLE_MODE:
                if "opponent" in payload and payload.get("opponent") not in (None, "mcts"):
                    raise WebLifecycleError(
                        "codex_mcts battle mode requires the MCTS opponent", 400, current
                    )
                opponent_kind = "mcts"
            elif battle_mode == _CODEX_DUEL_BATTLE_MODE:
                if "opponent" in payload and payload.get("opponent") not in (None, "codex"):
                    raise WebLifecycleError(
                        "codex_codex battle mode requires the Codex opponent", 400, current
                    )
                opponent_kind = "codex"
            if "codex_model" in payload and opponent_kind != "codex":
                if battle_mode not in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                    raise WebLifecycleError(
                        "codex_model is only valid for a Codex opponent", 400, current
                    )
                if battle_mode == _AUTOMATION_BATTLE_MODE:
                    raise WebLifecycleError(
                        "codex_model is reserved for a Codex opponent seat", 400, current
                    )
            if "codex_self_model" in payload and battle_mode not in {
                _AUTOMATION_BATTLE_MODE,
                _CODEX_DUEL_BATTLE_MODE,
            }:
                raise WebLifecycleError(
                    "codex_self_model is only valid for an automated Codex match",
                    400,
                    current,
                )

            # Imports stay local so direct single-match users do not pay for
            # the lobby factory until they actually request a new match.
            from fireplace.controller import GameSession
            from .factory import build_game, build_saved_deck_game

            match_seed = self._next_seed_locked()
            opponent_name = _OPPONENT_NAMES[opponent_kind]
            deck_id = payload.get("deck_id")
            if deck_id is None or deck_id == "":
                game, human, _opponent = build_game(
                    match_seed, opponent_name, nickname=nickname
                )
            else:
                if not isinstance(deck_id, str):
                    raise WebLifecycleError("deck_id must be a string", 400, current)
                try:
                    saved = self._decks_locked().get_complete(deck_id)
                except ValueError as exc:
                    raise WebLifecycleError(str(exc), 400, current) from exc
                except OSError as exc:
                    raise WebLifecycleError("deck storage is unavailable", 503, current) from exc
                game, human, _opponent = build_saved_deck_game(
                    seed=match_seed,
                    nickname=nickname,
                    opponent_name=opponent_name,
                    hero_id=saved["hero_id"],
                    card_ids=saved["card_ids"],
                )
            codex_timeout = None
            codex_self_timeout = None
            if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                try:
                    codex_self_model, codex_self_timeout = codex_defaults(
                        codex_self_model, self._codex_timeout_default
                    )
                    if battle_mode == _AUTOMATION_BATTLE_MODE:
                        codex_model, codex_timeout = codex_self_model, codex_self_timeout
                    else:
                        codex_model, codex_timeout = codex_defaults(
                            codex_model, self._codex_timeout_default
                        )
                except ValueError as exc:
                    raise WebLifecycleError(str(exc), 400, current) from exc
            elif opponent_kind == "codex":
                try:
                    codex_model, codex_timeout = codex_defaults(
                        codex_model, self._codex_timeout_default
                    )
                except ValueError as exc:
                    raise WebLifecycleError(str(exc), 400, current) from exc
            try:
                if battle_mode in {_AUTOMATION_BATTLE_MODE, _CODEX_DUEL_BATTLE_MODE}:
                    codex_agent = _create_opponent_agent(
                        "codex",
                        seed=match_seed,
                        model=codex_self_model,
                        timeout=codex_self_timeout,
                    )
                    try:
                        if battle_mode == _AUTOMATION_BATTLE_MODE:
                            seat1_agent = _create_opponent_agent("mcts", seed=match_seed)
                        else:
                            seat1_agent = _create_opponent_agent(
                                "codex",
                                seed=match_seed,
                                model=codex_model,
                                timeout=codex_timeout,
                            )
                    except Exception:
                        close = getattr(codex_agent, "close", None)
                        if callable(close):
                            close()
                        raise
                    opponent_agent = (codex_agent, seat1_agent)
                else:
                    opponent_agent = _create_opponent_agent(
                        opponent_kind,
                        seed=match_seed,
                        model=codex_model if opponent_kind == "codex" else None,
                        timeout=codex_timeout if opponent_kind == "codex" else None,
                    )
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc
            except Exception as exc:
                if opponent_kind == "codex" or battle_mode in {
                    _AUTOMATION_BATTLE_MODE,
                    _CODEX_DUEL_BATTLE_MODE,
                }:
                    raise WebLifecycleError(
                        "Codex opponent could not be started"
                        if battle_mode not in {
                            _AUTOMATION_BATTLE_MODE,
                            _CODEX_DUEL_BATTLE_MODE,
                        }
                        else "automated Codex opponent could not be started",
                        503,
                        current,
                    ) from exc
                raise
            try:
                active = self._build_archived_active_locked(
                    game=game,
                    human=human,
                    opponent_agent=opponent_agent,
                    mode="normal",
                    locale=locale,
                    seed=match_seed,
                    opponent_kind=opponent_kind,
                    battle_mode=battle_mode,
                )
            except ArchivePersistenceError as exc:
                raise WebLifecycleError(str(exc), 503, current) from exc
            except OSError as exc:
                raise WebLifecycleError("match archive is unavailable", 503, current) from exc
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 409, current) from exc
            self._active = active
            self._match_count += 1
            return active.snapshot()

    def return_to_lobby(self, payload: object) -> dict[str, Any]:
        """Close a terminal match after validating its current revision."""

        with self._lock:
            active = self._active
            if active is None:
                current = self._lobby_snapshot_locked()
                raise WebLifecycleError("no active match", 409, current)
            current = active.snapshot()
            if not isinstance(payload, Mapping):
                raise WebLifecycleError("request body must be a JSON object", 400, current)
            if payload.get("session_id") != current["session_id"]:
                raise WebLifecycleError("stale session", 409, current)
            revision = payload.get("revision")
            if type(revision) is not int:
                raise WebLifecycleError("revision must be an integer", 400, current)
            if revision != current["revision"]:
                raise WebLifecycleError("stale revision", 409, current)
            if current.get("outcome") is None:
                raise WebLifecycleError("match is not over", 409, current)

            arena_match_id = self._active_arena_match_id
            self._verify_terminal_archive_locked(active, current)
            self._settle_arena_result_locked(current)
            self._active = None
            self._active_arena_match_id = None
            self._arena_result_recorded = False
            lobby = self._lobby_snapshot_locked()
            if arena_match_id is not None:
                lobby["arena_redirect"] = True

        # A resolver may still be downloading an uncached image.  Detach the
        # match first so state and a new start remain responsive.  The manager
        # keeps its shared asset service alive for the next match; this also
        # keeps resolver catalog initialization serialized across lifetimes.
        active.close(wait=False)
        return lobby

    def _settle_arena_result_locked(self, state: Mapping[str, Any]) -> None:
        """Persist one terminal Arena result while the manager lock is held."""

        match_id = self._active_arena_match_id
        if match_id is None or self._arena_result_recorded:
            return
        outcome = state.get("outcome")
        if not isinstance(outcome, Mapping):
            return
        human_won = outcome.get("human_won")
        if human_won is not True and human_won is not False and human_won is not None:
            return
        self._arena_locked().settle(match_id, human_won)
        self._arena_result_recorded = True

    def handle_action(self, payload: object) -> dict[str, Any]:
        with self._lock:
            active = self._active
            if active is None:
                raise WebActionError("no active match", 409, self._lobby_snapshot_locked())
            state = active.handle_action(payload)
            self._settle_arena_result_locked(state)
            return state

    def concede(self, payload: object) -> dict[str, Any]:
        """Concede the active match and settle an Arena loss exactly once."""

        with self._lock:
            active = self._active
            if active is None:
                raise WebActionError("no active match", 409, self._lobby_snapshot_locked())
            state = active.concede(payload)
            self._settle_arena_result_locked(state)
            return state

    def retry_opponent(self, payload: object) -> dict[str, Any]:
        with self._lock:
            active = self._active
            if active is None:
                raise WebActionError("no active match", 409, self._lobby_snapshot_locked())
            return active.retry_opponent(payload)

    def automation(self, payload: object) -> dict[str, Any]:
        """Control a Codex-vs-MCTS match or detach it as abandoned."""

        with self._lock:
            active = self._active
            if active is None:
                raise WebActionError("no active match", 409, self._lobby_snapshot_locked())
            if not isinstance(payload, Mapping):
                current = active.snapshot()
                raise WebActionError("request body must be a JSON object", 400, current)
            if getattr(active, "battle_mode", "human") not in {
                _AUTOMATION_BATTLE_MODE,
                _CODEX_DUEL_BATTLE_MODE,
            }:
                current = active.snapshot()
                current["error"] = "automation is available only for Codex-vs-MCTS matches"
                raise WebActionError(current["error"], 409, current)
            if payload.get("command") != "stop":
                return active.automation(payload)

            # Validate the request and invalidate a pending worker while the
            # match lock is held.  The archive CAS happens under that same
            # lock, so a worker callback cannot save a newer prefix between
            # the snapshot and abandonment.
            with active.lock:
                current = active._snapshot_locked()
                if payload.get("session_id") != current.get("session_id"):
                    current["error"] = "stale session"
                    raise WebActionError(current["error"], 409, current)
                revision = payload.get("revision")
                if type(revision) is not int:
                    current["error"] = "revision must be an integer"
                    raise WebActionError(current["error"], 400, current)
                if revision != current.get("revision"):
                    current["error"] = "stale revision"
                    raise WebActionError(current["error"], 409, current)
                try:
                    active._ensure_archive_healthy_locked()
                except ArchivePersistenceError as exc:
                    current["error"] = str(exc)
                    raise WebActionError(current["error"], 503, current) from exc
                invalidate = getattr(active, "_invalidate_automation_locked", None)
                if callable(invalidate):
                    active._automation_paused = True
                    invalidate(retire=False)
                archive_id = active._archive_game_id
                archive_revision = active._archive_revision
                if self._archive_store is not None and archive_id is not None:
                    try:
                        envelope = store_get(self._archive_store, archive_id)
                        if envelope is None:
                            raise WebActionError(
                                "match archive was not found", 503, current
                            )
                        status = envelope_status(envelope)
                        if status == "complete":
                            raise WebActionError("match archive is already complete", 409, current)
                        if status == "in_progress" and checkpoint_is_terminal(
                            envelope_log(envelope)
                        ):
                            raise WebActionError(
                                "terminal checkpoint must be resumed before stopping",
                                409,
                                current,
                            )
                        store_mark_abandoned(
                            self._archive_store,
                            archive_id,
                            expected_revision=archive_revision,
                        )
                    except WebActionError:
                        raise
                    except OSError as exc:
                        raise WebActionError(
                            "match archive is unavailable", 503, current
                        ) from exc
                    except ValueError as exc:
                        raise WebActionError(str(exc), 409, current) from exc
                self._active = None
                self._active_arena_match_id = None
                self._arena_result_recorded = False
                lobby = self._lobby_snapshot_locked()
            active.close(wait=False)
            return lobby

    def asset(self, kind: str, card_id: str) -> tuple[bytes, str, bool] | object | None:
        with self._lock:
            active = self._active
        if active is None:
            return None
        # ``WebGame.asset`` waits briefly for a completed cache lookup.  Do not
        # hold the lobby lock during that wait: state/action requests and a
        # terminal return must remain independent of artwork resolution.
        return active.asset(kind, card_id)

    def close(self) -> None:
        with self._lock:
            active = self._active
            self._active = None
            self._active_arena_match_id = None
            self._arena_result_recorded = False
            assets = self._asset_service
            self._asset_service = None
            arena = self._arena_service
            self._arena_service = None
        try:
            if active is not None:
                active.close(wait=False)
        finally:
            try:
                if assets is not None:
                    assets.close(wait=True)
            finally:
                if arena is not None:
                    arena.close()
                if self._archive_store is not None and self._archive_owner:
                    self._archive_store.release_owner()
                    self._archive_owner = False


# Keep the historical import surface while keeping the HTTP adapter separate
# from match and lobby orchestration.
from .http_server import WebGameHTTPServer, create_server, make_server, serve


__all__ = [
    "WebActionError",
    "WebLifecycleError",
    "WebGame",
    "WebGameManager",
    "WebGameHTTPServer",
    "create_server",
    "make_server",
    "serve",
]
