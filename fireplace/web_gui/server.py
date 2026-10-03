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
from .public_events import (
    decorate_visible_cards,
    localize_events,
    project_action,
    visible_card_ids,
)


_ASSET_KINDS = frozenset({"render", "art", "tile"})
_LOCALES = frozenset({"zhCN", "enUS"})
_OPPONENTS = frozenset({"radical", "mcts"})
_OPPONENT_NAMES = {
    "radical": "Radical",
    "mcts": "MCTS",
}
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
        raise ValueError("opponent must be one of 'radical' or 'mcts'")
    return value


def _create_opponent_agent(
    kind: str,
    seed: int | None,
    *,
    policy_version: str | None = None,
    search_config: Mapping[str, Any] | None = None,
) -> object:
    """Create one validated browser opponent through the shared factory."""

    from ..agent_factory import create_agent

    options: dict[str, Any] = {}
    if policy_version is not None:
        options["policy_version"] = policy_version
    if search_config is not None:
        options["search_config"] = copy.deepcopy(dict(search_config))
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

        try:
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
        return {
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

    def _advance_ai_locked(
        self, presentation_steps: list[dict[str, Any]] | None = None
    ) -> None:
        """Run the supplied agent until human input or terminal state."""

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
            event = self._public_event_locked(
                player, action, self.session.observation(self.human)
            )
            # Stage diagnostics before execute: ActionLog saves the accepted
            # action inside that call. The private metadata checkpoint then
            # contains the decision and action atomically, including lethal.
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
                raise RuntimeError(
                    "Opponent action was rejected: %s" % action_error
                ) from action_error
            self._append_event_locked(event)
            self._ai_decisions_dropped += trim_decisions(self._ai_decisions)
            self._revision += 1
            if presentation_steps is not None:
                presentation_steps.append(
                    self._presentation_step_locked(
                        event, effects, effects_truncated
                    )
                )
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
            presentation_steps = [
                self._presentation_step_locked(event, effects, effects_truncated)
            ]
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
        return {
            "mode": "lobby",
            "opponent": self._opponent_default,
        }

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
        run: object | None = None,
        match_id: str | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "mode": mode,
            "locale": locale,
            "opponent": opponent,
            "seed": seed,
            "human_seat": 0,
        }
        if opponent == "mcts":
            if not isinstance(agent_state, Mapping):
                raise ValueError("MCTS archive is missing opponent state")
            policy_version = agent_state.get("policy_version")
            search_config = agent_state.get("search_config")
            if not isinstance(policy_version, str) or not policy_version:
                raise ValueError("MCTS archive has an invalid policy version")
            if not isinstance(search_config, Mapping):
                raise ValueError("MCTS archive has an invalid search configuration")
            metadata["mcts_policy_version"] = policy_version
            metadata["mcts_search_config"] = copy.deepcopy(dict(search_config))
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
        run: object | None = None,
        match_id: str | None = None,
        initial_events: list[Mapping[str, Any]] | None = None,
        initial_revision: int = 0,
        restored_session: GameSession | None = None,
        existing_envelope: Mapping[str, Any] | None = None,
    ) -> WebGame:
        """Create a WebGame with its archive checkpoint wired before setup."""

        if self._archive_store is None:
            session = restored_session or GameSession(game, {})
            return WebGame(
                session,
                human,
                opponent_agent,
                asset_service=self._asset_service_locked(),
                locale=locale,
                initial_events=initial_events,
                initial_revision=initial_revision,
            )

        from ..action_log import ActionLog

        session_ref: dict[str, GameSession] = {}
        initial_agent_state = capture_agent_state(opponent_agent)
        metadata = self._archive_metadata_locked(
            mode=mode,
            locale=locale,
            opponent=opponent_kind,
            seed=seed,
            agent_state=initial_agent_state if isinstance(initial_agent_state, Mapping) else None,
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

        def on_save(saved_log: object | None = None) -> None:
            current_log = saved_log if saved_log is not None else session_ref["session"].action_log
            active = context.get("active")
            try:
                public = None
                if active is not None and active._started:
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
                    agent_state=capture_agent_state(opponent_agent),
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
            active = WebGame(
                session,
                human,
                opponent_agent,
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
            restored: GameSession | None = None
            building_active = False
            try:
                opponent_kind = _validate_opponent(opponent_kind)
                locale = _validate_locale(metadata.get("locale", "zhCN"))
                policy_version = None
                search_config = None
                if opponent_kind == "mcts":
                    policy_version, search_config = _resolve_mcts_archive_options(
                        metadata, envelope.get("agent_state")
                    )
                # Constructing the policy is deliberately before replay.  The
                # constructor validates the archived version and every closed
                # search-config key/value while the archive is still untouched.
                opponent_agent = _create_opponent_agent(
                    opponent_kind,
                    seed=metadata.get("seed"),
                    **(
                        {
                            "policy_version": policy_version,
                            "search_config": search_config,
                        }
                        if opponent_kind == "mcts"
                        else {}
                    ),
                )
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
                opponent_kind = _validate_opponent(
                    payload.get("opponent", self._opponent_default)
                )
                locale = _validate_locale(payload.get("locale"))
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc

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
            opponent_agent = _create_opponent_agent(opponent_kind, seed=match_seed)
            try:
                active = self._build_archived_active_locked(
                    game=game,
                    human=human,
                    opponent_agent=opponent_agent,
                    mode="normal",
                    locale=locale,
                    seed=match_seed,
                    opponent_kind=opponent_kind,
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
