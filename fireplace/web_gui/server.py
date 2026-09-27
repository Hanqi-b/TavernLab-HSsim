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
from .contracts import ASSET_PENDING, WebActionError, WebLifecycleError
from .public_events import (
    decorate_visible_cards,
    localize_events,
    project_action,
    visible_card_ids,
)


_ASSET_KINDS = frozenset({"render", "art", "tile"})
_LOCALES = frozenset({"zhCN", "enUS"})
_OPPONENTS = frozenset({"heuristic"})
_ASSET_PENDING = ASSET_PENDING


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
    if value not in _OPPONENTS:
        raise ValueError("opponent must be 'heuristic'")
    return str(value)


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
    ) -> None:
        if asset_resolver is not None and asset_service is not None:
            raise ValueError("asset_resolver and asset_service are mutually exclusive")
        self.locale = _validate_locale(locale)
        self.session = session
        self.human = human
        self.opponent_agent = opponent_agent
        self._lock = threading.RLock()
        self._revision = 0
        self._session_id = str(uuid.uuid4())
        self._started = False
        self._events: list[dict[str, Any]] = []
        self._event_seq = 0
        self.asset_resolver = asset_resolver
        self._owns_assets = asset_service is None
        # AssetService owns optional resolver construction and keeps it lazy.
        # Passing a custom resolver remains useful for deterministic tests and
        # embedded callers; omitting one uses the package's default factory.
        self.assets = asset_service or (
            AssetService() if asset_resolver is None
            else AssetService(resolver=asset_resolver)
        )
        self.start()

    @property
    def lock(self) -> threading.RLock:
        """Expose the lock to the HTTP adapter without exposing game state."""

        return self._lock

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def close(self, *, wait: bool = True) -> None:
        """Release optional asset workers when the local server closes."""

        try:
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

    def _advance_ai_locked(self) -> None:
        """Run the supplied agent until human input or terminal state."""

        while not _game_ended(self.session.game):
            player = decision_player(self.session.game)
            if player is None or player is self.human:
                return
            actions = list(self.session.legal_actions(player))
            if not actions:
                raise RuntimeError("No legal decision for the opponent")
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
            try:
                self.session.execute(player, action)
            except GameOver:
                self._append_event_locked(event)
                self._revision += 1
                return
            except ActionError as exc:
                raise RuntimeError("Opponent action was rejected: %s" % exc) from exc
            self._append_event_locked(event)
            self._revision += 1

    def handle_action(self, payload: object) -> dict[str, Any]:
        """Validate and execute one browser action, returning a new snapshot.

        ``WebActionError`` carries status 400 for malformed JSON values and
        status 409 for an old revision or an action that is no longer legal.
        """

        with self._lock:
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
            try:
                self.session.execute(self.human, action)
            except GameOver:
                # GameSession has already applied and logged the accepted
                # action before raising its terminal signal.
                self._append_event_locked(event)
                self._revision += 1
                return self._snapshot_locked()
            except ActionError as exc:
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 409, current) from exc

            self._append_event_locked(event)
            self._revision += 1
            self._advance_ai_locked()
            return self._snapshot_locked()

    def concede(self, payload: object) -> dict[str, Any]:
        """Concede the active match through the human player's engine API.

        Surrender is deliberately kept outside ``legal_actions``.  It is a
        browser control, and exposing it as a normal agent action would also
        make it available to the opponent agent.  The session still executes
        the explicit action so the terminal result remains replayable.
        """

        with self._lock:
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

            try:
                self.session.execute(self.human, Action(type=CONCEDE))
            except GameOver:
                # GameSession records the explicit action and finalizes the
                # action log before propagating the engine's terminal signal.
                pass
            except ActionError as exc:
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 409, current) from exc

            if not _game_ended(self.session.game):
                current = self._snapshot_locked()
                current["error"] = "could not concede the match"
                raise WebActionError(current["error"], 409, current)

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
        opponent: str = "heuristic",
        asset_resolver: object | None = None,
        arena_store: object | None = None,
        deck_store: object | None = None,
        catalog: object | None = None,
    ) -> None:
        if seed is not None and type(seed) is not int:
            raise ValueError("seed must be an integer or None")
        self._base_seed = seed
        self._opponent_default = _validate_opponent(opponent)
        self._asset_resolver = asset_resolver
        self._arena_store = arena_store
        self._deck_store = deck_store
        self._catalog = catalog
        self._deck_service = None
        self._asset_service: AssetService | None = None
        self._match_count = 0
        self._active: WebGame | None = None
        self._active_arena_match_id: str | None = None
        self._arena_result_recorded = False
        self._arena_service = None
        self._lock = threading.RLock()

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
                self._arena_service = ArenaService(store=self._arena_store, catalog=self._catalog)
            except (ArenaStoreConflict, ArenaStoreCorrupt) as exc:
                raise WebLifecycleError(str(exc), 409, self._lobby_snapshot_locked()) from exc
        return self._arena_service

    def _decks_locked(self):
        if self._deck_service is None:
            from .decks import DeckService

            self._deck_service = DeckService(store=self._deck_store, catalog=self._catalog)
        return self._deck_service

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
            return self._arena_locked().state(locale=locale)

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
            run = service.ready_for_battle(payload)
            if self._active is not None:
                raise WebLifecycleError("finish the active match first", 409, service.state())

            from fireplace.agents import HeuristicAgent
            from .arena_factory import build_arena_game

            game, human, _opponent = build_arena_game(
                seed=run.seed + 100_000 + run.match_index,
                nickname=run.nickname,
                hero_id=run.hero_id,
                deck=run.deck,
                selected_sets=run.selected_sets,
            )
            active = WebGame(
                GameSession(game, {}),
                human,
                HeuristicAgent(),
                asset_service=self._asset_service_locked(),
                locale=run.locale,
            )
            try:
                state = service.mark_battle_started()
            except Exception:
                active.close(wait=False)
                raise
            self._active = active
            self._active_arena_match_id = service.run.pending_match_id
            self._arena_result_recorded = False
            return state

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
                _validate_opponent(payload.get("opponent", "heuristic"))
                locale = _validate_locale(payload.get("locale"))
            except ValueError as exc:
                raise WebLifecycleError(str(exc), 400, current) from exc

            # Imports stay local so direct single-match users do not pay for
            # the lobby factory until they actually request a new match.
            from fireplace.agents import HeuristicAgent
            from fireplace.controller import GameSession
            from .factory import build_game, build_saved_deck_game

            match_seed = self._next_seed_locked()
            deck_id = payload.get("deck_id")
            if deck_id is None or deck_id == "":
                game, human, _opponent = build_game(
                    match_seed, "Heuristic", nickname=nickname
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
                    opponent_name="Heuristic",
                    hero_id=saved["hero_id"],
                    card_ids=saved["card_ids"],
                )
            opponent_agent = HeuristicAgent()
            active = WebGame(
                GameSession(game, {}),
                human,
                opponent_agent,
                asset_service=self._asset_service_locked(),
                locale=locale,
            )
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
