"""Two-controller automation for the Codex-vs-MCTS web match.

The normal :class:`~fireplace.web_gui.server.WebGame` exposes one human seat
and one opponent.  Automation keeps the same engine/event/archive boundary
while making both seats controller-owned and treating seat zero as a private
viewer.  Slow Codex calls and MCTS search run in one daemon worker outside the
match lock; a generation token makes pause, retry, and stale completions safe.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Callable

from ..agent_api import Action
from ..search_api import SearchUnavailable
from ..search_simulation import EngineSearchPosition
from ..controller import decision_player
from .contracts import WebActionError
from .archive_runtime import ArchivePersistenceError
from .server import WebGame, _game_ended
from .async_opponent import (
    DetachedDecisionWorker,
    codex_config_from_agent,
    validate_codex_state,
)


AUTOMATION_BATTLE_MODE = "codex_mcts"
CODEX_DUEL_BATTLE_MODE = "codex_codex"
AUTOMATION_BATTLE_MODES = frozenset(
    {AUTOMATION_BATTLE_MODE, CODEX_DUEL_BATTLE_MODE}
)
AUTOMATION_MIN_ACTION_GAP = 0.1


@dataclass(frozen=True)
class AutomatedDecision:
    """A detached controller input captured under the match lock."""

    session_id: str
    revision: int
    seat: int
    player: object
    observation: Mapping[str, Any]
    actions: tuple[object, ...]
    search_position: object | None
    controller: object
    generation: int


class AutomatedDecisionScheduler:
    """Run exactly one persistent Codex/MCTS decision worker.

    Controller replacement invalidates the current item but keeps the worker
    alive.  Each decision captures its controller, so cancel/close from an
    old Codex transport cannot affect the replacement used by a later turn.
    """

    def __init__(
        self,
        controllers: Sequence[object],
        *,
        on_result: Callable[[AutomatedDecision, object], None],
        on_error: Callable[[AutomatedDecision, BaseException], None],
    ) -> None:
        self._controllers = list(controllers)
        if len(self._controllers) != 2:
            raise ValueError("automation requires exactly two controllers")
        self._lock = threading.RLock()
        self._on_result = on_result
        self._on_error = on_error
        self._worker = DetachedDecisionWorker(
            self._choose,
            on_result=on_result,
            on_error=on_error,
            cancel_for=lambda decision: decision.controller,
            closeables=lambda: self.controllers,
        )

    @property
    def pending(self) -> AutomatedDecision | None:
        value = self._worker.pending
        return value if isinstance(value, AutomatedDecision) else None

    @property
    def controllers(self) -> tuple[object, object]:
        with self._lock:
            return tuple(self._controllers)  # type: ignore[return-value]

    @property
    def closed(self) -> bool:
        return self._worker.closed

    def is_current(self, decision: AutomatedDecision) -> bool:
        return self._worker.is_generation_current(decision.generation)

    def schedule(
        self,
        *,
        session_id: str,
        revision: int,
        seat: int,
        player: object,
        observation: Mapping[str, Any],
        actions: Sequence[object],
        search_position: object | None,
    ) -> AutomatedDecision | None:
        with self._lock:
            if self._worker.closed or self._worker.pending is not None:
                return None
            seat = int(seat)
            controller = self._controllers[seat]
            decision = AutomatedDecision(
                session_id=str(session_id),
                revision=int(revision),
                seat=seat,
                player=player,
                observation=copy.deepcopy(dict(observation)),
                actions=tuple(copy.deepcopy(list(actions))),
                search_position=search_position,
                controller=controller,
                generation=self._worker.generation,
            )
            return decision if self._worker.submit(decision) else None

    def invalidate(self) -> None:
        """Invalidate a result and dispatch cancellation without waiting."""

        self._worker.invalidate()

    def close(self, *, wait: bool = False) -> None:
        self._worker.close(wait=wait)

    def replace_controller(self, seat: int, controller: object) -> object:
        """Replace one controller while retaining this scheduler's worker."""

        seat = int(seat)
        if seat not in (0, 1):
            raise ValueError("invalid automation controller seat")
        with self._lock:
            old = self._controllers[seat]
            self._worker.invalidate()
            self._controllers[seat] = controller
        self._worker.retire(old)
        return old

    def _choose(self, decision: AutomatedDecision) -> object:
        controller = decision.controller
        observation = copy.deepcopy(dict(decision.observation))
        actions = copy.deepcopy(list(decision.actions))
        if decision.seat == 1 and decision.search_position is not None:
            try:
                return controller.choose_action_with_search(
                    observation,
                    actions,
                    decision.search_position,
                )
            except SearchUnavailable:
                # MCTS owns this fallback.  It preserves MCTS policy state
                # instead of silently switching to a heuristic controller.
                return controller.choose_action(observation, actions)
        return controller.choose_action(observation, actions)


def _controller_kind_for_mode(battle_mode: str, seat: int) -> str:
    if battle_mode not in AUTOMATION_BATTLE_MODES:
        raise ValueError("invalid automated battle mode")
    if int(seat) == 0 or battle_mode == CODEX_DUEL_BATTLE_MODE:
        return "codex"
    return "mcts"


def capture_automated_agent_state(
    controllers: Sequence[object], battle_mode: str = AUTOMATION_BATTLE_MODE
) -> dict[str, Any]:
    """Capture both validated controller states without conversation data."""

    from .archive_runtime import capture_agent_state

    values = list(controllers)
    if len(values) != 2:
        raise ValueError("automation requires exactly two controllers")
    if battle_mode not in AUTOMATION_BATTLE_MODES:
        raise ValueError("invalid automated battle mode")
    states = [capture_agent_state(value) for value in values]
    if not all(isinstance(value, Mapping) for value in states):
        raise ValueError("automation controller state is unavailable")
    expected = [_controller_kind_for_mode(battle_mode, seat) for seat in (0, 1)]
    if [states[0].get("kind"), states[1].get("kind")] != expected:
        raise ValueError("automation controller kinds are invalid")
    return {
        "kind": "automated",
        "battle_mode": battle_mode,
        "controllers": copy.deepcopy(states),
    }


def validate_automated_agent_state(
    value: object, expected_battle_mode: str | None = None
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "kind", "battle_mode", "controllers"
    }:
        raise ValueError("invalid automated controller state")
    battle_mode = value.get("battle_mode")
    if value.get("kind") != "automated" or battle_mode not in AUTOMATION_BATTLE_MODES:
        raise ValueError("invalid automated battle mode")
    if expected_battle_mode is not None and battle_mode != expected_battle_mode:
        raise ValueError("archived automated battle mode does not match the match")
    controllers = value.get("controllers")
    if not isinstance(controllers, list) or len(controllers) != 2:
        raise ValueError("invalid automated controller list")
    states: list[dict[str, Any]] = []
    expected = [_controller_kind_for_mode(str(battle_mode), seat) for seat in (0, 1)]
    states.append(validate_codex_state(controllers[0]))
    if expected[1] == "codex":
        states.append(validate_codex_state(controllers[1]))
    elif not isinstance(controllers[1], Mapping) or controllers[1].get("kind") != "mcts":
        raise ValueError("invalid automated MCTS state")
    else:
        states.append(copy.deepcopy(dict(controllers[1])))
    return {
        "kind": "automated",
        "battle_mode": str(battle_mode),
        "controllers": states,
    }


def restore_automated_agent_state(
    controllers: Sequence[object],
    value: object,
    expected_battle_mode: str | None = None,
) -> dict[str, Any]:
    from .archive_runtime import restore_agent_state

    state = validate_automated_agent_state(value, expected_battle_mode)
    values = list(controllers)
    if len(values) != 2:
        raise ValueError("automation requires exactly two controllers")
    restore_agent_state(values[0], state["controllers"][0])
    restore_agent_state(values[1], state["controllers"][1])
    return state



class AutomatedGame(WebGame):
    def __init__(
        self,
        session,
        viewer,
        controllers: Sequence[object],
        *,
        battle_mode: str = AUTOMATION_BATTLE_MODE,
        automation_paused: bool = True,
        **kwargs,
    ):
        values = list(controllers)
        if len(values) != 2:
            raise ValueError("automation requires exactly two controllers")
        if battle_mode not in AUTOMATION_BATTLE_MODES:
            raise ValueError("invalid automated battle mode")
        self._controllers = values
        self._battle_mode = battle_mode
        self._codex_config = codex_config_from_agent(values[0])
        self._automation_paused = bool(automation_paused)
        self._automation_error: str | None = None
        self._automation_error_seat: int | None = None
        self._automation_epoch = 0
        self._automation_scheduler: AutomatedDecisionScheduler | None = None
        self._automation_timer: threading.Timer | None = None
        self._automation_step_requested = False
        self._automation_recreate_seat: int | None = None
        self._automation_last_action = 0.0
        self._automation_retrying = False
        self._automation_retry_token = 0
        # WebGame's opponent slot remains seat one for event/search
        # compatibility.  Both controllers are owned by this subclass.
        super().__init__(
            session,
            viewer,
            values[1],
            **kwargs,
        )
        self._async_opponent = False
        # WebGame initializes this slot for human-vs-agent matches and thus
        # overwrites the value set before construction.  Restore the pinned
        # Codex config after the base constructor has finished.
        self._codex_config = codex_config_from_agent(values[0])

    @property
    def controllers(self) -> tuple[object, object]:
        return (self._controllers[0], self._controllers[1])

    @property
    def battle_mode(self) -> str:
        return self._battle_mode

    def _controller_kind(self, seat: int) -> str:
        return _controller_kind_for_mode(self._battle_mode, seat)

    def _seat_locked(self, player: object | None) -> int | None:
        if player is None:
            return None
        for seat, candidate in enumerate(self.session.game.players):
            if candidate is player:
                return seat
        return None

    def _decision_actions_locked(self):
        # Seat zero is a viewer, never an input controller.  Automated
        # snapshots intentionally expose no normal legal action menu.
        return decision_player(self.session.game), []

    def _record_presentation_step_locked(self, step: Mapping[str, Any]) -> None:
        self._presentation_steps.append(copy.deepcopy(dict(step)))
        self._automation_last_action = time.monotonic()

    def _automation_public_locked(self, payload: dict[str, Any]) -> None:
        current = decision_player(self.session.game)
        current_seat = self._seat_locked(current)
        config = self._codex_config or {}
        payload["battle_mode"] = self._battle_mode
        pending = (
            self._automation_scheduler is not None
            and self._automation_scheduler.pending is not None
        )
        controller_public = []
        for seat, controller in enumerate(self._controllers):
            kind = self._controller_kind(seat)
            model = None
            if kind == "codex":
                try:
                    model = codex_config_from_agent(controller).get("model")
                except (TypeError, ValueError):
                    model = None
            controller_public.append({"kind": kind, "model": model})
        payload["automation"] = {
            "enabled": True,
            "paused": bool(self._automation_paused),
            "pending": bool(pending),
            "current_seat": current_seat,
            "controllers": controller_public,
        }
        if self._automation_error is not None:
            payload["automation"]["error"] = self._automation_error
            payload["automation"]["error_seat"] = self._automation_error_seat
        llm_seat = (
            self._automation_error_seat
            if self._automation_error_seat is not None
            else current_seat
        )
        llm_model = config.get("model")
        if llm_seat in (0, 1) and self._controller_kind(llm_seat) == "codex":
            try:
                llm_model = codex_config_from_agent(self._controllers[llm_seat]).get(
                    "model"
                )
            except (TypeError, ValueError):
                llm_model = None
        payload["llm"] = {
            "state": (
                "error"
                if self._automation_error is not None
                else "thinking"
                if pending and current_seat == llm_seat
                else "idle"
            ),
            "model": llm_model,
            "seat": llm_seat,
            "error": self._automation_error,
        }
        payload["presentation_steps"] = copy.deepcopy(
            list(self._presentation_steps)
        )

    def _snapshot_locked(self):
        payload = super()._snapshot_locked()
        self._automation_public_locked(payload)
        return payload

    def _ensure_automation_scheduler_locked(self):
        scheduler = self._automation_scheduler
        if scheduler is None:
            scheduler_ref: dict[str, AutomatedDecisionScheduler] = {}
            scheduler = AutomatedDecisionScheduler(
                self._controllers,
                on_result=lambda decision, result: self._on_automation_result(
                    scheduler_ref["scheduler"], decision, result
                ),
                on_error=lambda decision, error: self._on_automation_error(
                    scheduler_ref["scheduler"], decision, error
                ),
            )
            scheduler_ref["scheduler"] = scheduler
            self._automation_scheduler = scheduler
        return scheduler

    def _cancel_timer_locked(self) -> None:
        timer = self._automation_timer
        self._automation_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_after_gap(self, epoch: int) -> None:
        with self._lock:
            if epoch != self._automation_epoch:
                return
            self._automation_timer = None
            self._schedule_automation_locked()

    def _schedule_automation_locked(self) -> None:
        if (
            self._closed
            or self._automation_paused
            or self._automation_error is not None
            or _game_ended(self.session.game)
            or self._archive_failed is not None
        ):
            return
        player = decision_player(self.session.game)
        seat = self._seat_locked(player)
        if player is None or seat is None:
            return
        scheduler = self._ensure_automation_scheduler_locked()
        if scheduler.pending is not None:
            return
        elapsed = time.monotonic() - self._automation_last_action
        if elapsed < AUTOMATION_MIN_ACTION_GAP:
            if self._automation_timer is None:
                epoch = self._automation_epoch
                self._automation_timer = threading.Timer(
                    AUTOMATION_MIN_ACTION_GAP - elapsed,
                    self._schedule_after_gap,
                    args=(epoch,),
                )
                self._automation_timer.daemon = True
                self._automation_timer.start()
            return
        actions = list(self.session.legal_actions(player))
        if not actions:
            self._set_automation_error_locked(seat, RuntimeError("no legal action"))
            return
        observation = self.session.observation(player)
        search_position = None
        if self._controller_kind(seat) == "mcts":
            try:
                search_position = EngineSearchPosition.from_game(
                    self.session.game,
                    player,
                    seed=int(getattr(self._controllers[1], "seed", 0)),
                )
            except SearchUnavailable:
                search_position = None
            except Exception as exc:
                self._set_automation_error_locked(seat, exc)
                return
        decision = scheduler.schedule(
            session_id=self._session_id,
            revision=self._revision,
            seat=seat,
            player=player,
            observation=observation,
            actions=actions,
            search_position=search_position,
        )
        if decision is None:
            return

    # WebGame calls this dynamic hook after every accepted AI action.
    def _schedule_async_ai_locked(self) -> None:
        self._schedule_automation_locked()

    def _advance_ai_locked(self, presentation_steps=None) -> None:
        del presentation_steps
        self._schedule_automation_locked()

    def _sanitize_automation_error(self, seat: int, error: BaseException) -> str:
        if self._controller_kind(seat) == "codex":
            return WebGame._sanitize_codex_error(error)
        if isinstance(error, SearchUnavailable):
            return "MCTS search was unavailable"
        return "MCTS opponent failed to choose an action"

    def _set_automation_error_locked(self, seat: int, error: BaseException) -> None:
        self._automation_error_seat = int(seat)
        self._automation_error = self._sanitize_automation_error(seat, error)
        self._automation_paused = True
        self._automation_step_requested = False
        self._cancel_timer_locked()
        scheduler = self._automation_scheduler
        if scheduler is not None:
            scheduler.invalidate()

    def _on_automation_error(
        self,
        scheduler: AutomatedDecisionScheduler,
        decision: AutomatedDecision,
        error: BaseException,
    ) -> None:
        with self._lock:
            if scheduler is not self._automation_scheduler or self._closed:
                return
            if (
                not scheduler.is_current(decision)
                or decision.session_id != self._session_id
                or decision.revision != self._revision
                or decision.player is not decision_player(self.session.game)
                or self._automation_paused
            ):
                return
            self._set_automation_error_locked(decision.seat, error)

    def _on_automation_result(
        self,
        scheduler: AutomatedDecisionScheduler,
        decision: AutomatedDecision,
        raw_action: object,
    ) -> None:
        with self._lock:
            if scheduler is not self._automation_scheduler or self._closed:
                return
            if (
                not scheduler.is_current(decision)
                or decision.session_id != self._session_id
                or decision.revision != self._revision
                or self._automation_paused
                or decision.player is not decision_player(self.session.game)
            ):
                return
            actions = list(self.session.legal_actions(decision.player))
            action = raw_action
            if isinstance(action, Mapping):
                try:
                    action = Action.from_dict(action)
                except (TypeError, ValueError):
                    self._set_automation_error_locked(
                        decision.seat,
                        ValueError("invalid action"),
                    )
                    return
            if not isinstance(action, Action) or action not in actions:
                self._set_automation_error_locked(
                    decision.seat,
                    ValueError("invalid action"),
                )
                return
            step_requested = self._automation_step_requested
            if step_requested:
                # _accept_ai_action_locked schedules the next controller
                # turn before returning.  Mark the match paused first so
                # a step can accept exactly one engine action.
                self._automation_paused = True
                self._automation_step_requested = False
            try:
                self._accept_ai_action_locked(decision.player, action, None)
            except ArchivePersistenceError as exc:
                self.mark_archive_failed(exc)
                self._set_automation_error_locked(decision.seat, exc)
                return
            except Exception as exc:
                self._set_automation_error_locked(decision.seat, exc)
                return

    def _invalidate_automation_locked(self, *, retire: bool = False) -> None:
        self._automation_epoch += 1
        self._cancel_timer_locked()
        scheduler = self._automation_scheduler
        if scheduler is not None:
            pending = scheduler.pending
            pending_seat = pending.seat if pending is not None else None
            scheduler.invalidate()
            if retire and pending_seat is not None and self._controller_kind(pending_seat) == "codex":
                self._automation_recreate_seat = pending_seat

    def _new_controller(self, seat: int, state: Mapping[str, Any] | None = None):
        from . import server as web_server

        current = self._controllers[seat]
        if self._controller_kind(seat) == "codex":
            config = codex_config_from_agent(current)
            return web_server._create_opponent_agent(
                "codex",
                seed=None,
                model=config["model"],
                timeout=config["timeout"],
            )
        from .archive_runtime import capture_agent_state, restore_agent_state

        state = state if state is not None else capture_agent_state(current)
        if not isinstance(state, Mapping):
            raise ValueError("MCTS controller state is unavailable")
        replacement = web_server._create_opponent_agent(
            "mcts",
            seed=state.get("seed"),
            policy_version=state.get("policy_version"),
            search_config=state.get("search_config"),
        )
        restore_agent_state(replacement, state)
        return replacement

    def _recreate_controller_locked(self, seat: int) -> None:
        replacement = self._new_controller(seat)
        scheduler = self._automation_scheduler
        if scheduler is not None:
            scheduler.replace_controller(seat, replacement)
        self._controllers[seat] = replacement
        if self._controller_kind(seat) == "codex":
            self._codex_config = codex_config_from_agent(replacement)

    def _close_scheduler_locked(self) -> None:
        scheduler = self._automation_scheduler
        self._automation_scheduler = None
        if scheduler is not None:
            scheduler.invalidate()
            scheduler.close(wait=False)

    def close(self, *, wait: bool = True) -> None:
        scheduler = None
        controllers = ()
        with self._lock:
            if self._closed:
                return
            self._automation_epoch += 1
            self._cancel_timer_locked()
            scheduler = self._automation_scheduler
            self._automation_scheduler = None
            if scheduler is not None:
                scheduler.invalidate()
            else:
                controllers = tuple(self._controllers)
        if scheduler is not None:
            scheduler.close(wait=wait)
        else:
            for controller in controllers:
                close = getattr(controller, "close", None)
                if not callable(close):
                    continue
                if wait:
                    try:
                        close(wait=True)
                    except TypeError:
                        close()
                else:
                    threading.Thread(
                        target=close,
                        kwargs={"wait": False},
                        daemon=True,
                    ).start()
        super().close(wait=wait)

    def automation(self, payload: object) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise WebActionError("request body must be a JSON object", 400, self.snapshot())
        command = payload.get("command")
        with self._lock:
            current = self._snapshot_locked()
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
            if command == "pause":
                self._automation_paused = True
                self._automation_step_requested = False
                self._invalidate_automation_locked(retire=True)
                return self._snapshot_locked()
            if command == "resume":
                if not self._automation_paused:
                    return current
                try:
                    self._ensure_archive_healthy_locked()
                except ArchivePersistenceError as exc:
                    current["error"] = str(exc)
                    raise WebActionError(str(exc), 503, current) from exc
                if self._automation_error is not None:
                    current["error"] = "automation is paused on a controller error"
                    raise WebActionError(current["error"], 409, current)
                if self._automation_recreate_seat is not None:
                    seat = self._automation_recreate_seat
                    self._automation_recreate_seat = None
                    try:
                        self._recreate_controller_locked(seat)
                    except Exception as exc:
                        self._set_automation_error_locked(seat, exc)
                        failed = self._snapshot_locked()
                        failed["error"] = self._automation_error
                        raise WebActionError(self._automation_error, 503, failed) from exc
                self._cancel_timer_locked()
                self._automation_epoch += 1
                self._automation_paused = False
                self._automation_step_requested = False
                self._schedule_automation_locked()
                return self._snapshot_locked()
            if command == "step":
                if not self._automation_paused:
                    current["error"] = "automation must be paused before stepping"
                    raise WebActionError(current["error"], 409, current)
                try:
                    self._ensure_archive_healthy_locked()
                except ArchivePersistenceError as exc:
                    current["error"] = str(exc)
                    raise WebActionError(str(exc), 503, current) from exc
                if self._automation_error is not None:
                    current["error"] = "automation is paused on a controller error"
                    raise WebActionError(current["error"], 409, current)
                if self._automation_recreate_seat is not None:
                    seat = self._automation_recreate_seat
                    self._automation_recreate_seat = None
                    try:
                        self._recreate_controller_locked(seat)
                    except Exception as exc:
                        self._set_automation_error_locked(seat, exc)
                        failed = self._snapshot_locked()
                        failed["error"] = self._automation_error
                        raise WebActionError(self._automation_error, 503, failed) from exc
                self._cancel_timer_locked()
                self._automation_epoch += 1
                self._automation_paused = False
                self._automation_step_requested = True
                self._schedule_automation_locked()
                return self._snapshot_locked()
            current["error"] = "unknown automation command"
            raise WebActionError(current["error"], 400, current)

    def retry_opponent(self, payload: object) -> dict[str, Any]:
        # Retry the controller that failed, retaining its archived config.
        if not isinstance(payload, Mapping):
            raise WebActionError("request body must be a JSON object", 400, self.snapshot())
        retry_token = None
        seat = None
        mcts_state = None
        with self._lock:
            current = self._snapshot_locked()
            try:
                self._ensure_archive_healthy_locked()
            except ArchivePersistenceError as exc:
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
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
            if self._automation_retrying:
                current["error"] = "opponent retry is already in progress"
                raise WebActionError(current["error"], 409, current)
            seat = self._automation_error_seat
            if self._automation_error is None or seat not in (0, 1):
                current["error"] = "opponent retry is unavailable"
                raise WebActionError(current["error"], 409, current)
            if _game_ended(self.session.game):
                current["error"] = "match is over"
                raise WebActionError(current["error"], 409, current)
            if seat == 1:
                from .archive_runtime import capture_agent_state

                mcts_state = capture_agent_state(self._controllers[1])
            self._automation_retrying = True
            self._automation_retry_token += 1
            retry_token = self._automation_retry_token
            self._automation_epoch += 1
            self._automation_paused = True
            self._automation_step_requested = False
            scheduler = self._automation_scheduler
            if scheduler is not None:
                scheduler.invalidate()

        try:
            replacement = self._new_controller(int(seat), mcts_state)
        except Exception as exc:
            with self._lock:
                if retry_token != self._automation_retry_token or self._closed:
                    raise WebActionError("match is closed", 409, self._snapshot_locked()) from exc
                self._automation_retrying = False
                failed = self._snapshot_locked()
                failed["error"] = self._automation_error
                raise WebActionError(
                    self._automation_error or "opponent retry failed", 503, failed
                ) from exc

        with self._lock:
            if (
                self._closed
                or retry_token != self._automation_retry_token
                or not self._automation_retrying
                or self._session_id != payload.get("session_id")
                or self._revision != revision
            ):
                close = getattr(replacement, "close", None)
                if callable(close):
                    threading.Thread(target=close, daemon=True).start()
                current = self._snapshot_locked()
                current["error"] = "stale session"
                raise WebActionError(current["error"], 409, current)
            try:
                self._ensure_archive_healthy_locked()
            except ArchivePersistenceError as exc:
                self._automation_retrying = False
                close = getattr(replacement, "close", None)
                if callable(close):
                    threading.Thread(target=close, daemon=True).start()
                current = self._snapshot_locked()
                current["error"] = str(exc)
                raise WebActionError(str(exc), 503, current) from exc
            scheduler = self._automation_scheduler
            if scheduler is None:
                scheduler = self._ensure_automation_scheduler_locked()
            scheduler.replace_controller(int(seat), replacement)
            self._controllers[int(seat)] = replacement
            if self._controller_kind(int(seat)) == "codex":
                self._codex_config = codex_config_from_agent(replacement)
            self._automation_retrying = False
            self._automation_error = None
            self._automation_error_seat = None
            self._automation_paused = False
            self._automation_epoch += 1
            self._schedule_automation_locked()
            return self._snapshot_locked()

    def concede(self, payload: object) -> dict[str, Any]:
        """Keep the private viewer from being recorded as a human surrender."""

        del payload
        current = self.snapshot()
        current["error"] = "use automation stop to leave an automated match"
        raise WebActionError(current["error"], 409, current)

    def archive_agent_state(self):
        return capture_automated_agent_state(self._controllers, self._battle_mode)




__all__ = [
    "AUTOMATION_BATTLE_MODE",
    "AUTOMATION_BATTLE_MODES",
    "CODEX_DUEL_BATTLE_MODE",
    "AUTOMATION_MIN_ACTION_GAP",
    "AutomatedDecision",
    "AutomatedDecisionScheduler",
    "AutomatedGame",
    "capture_automated_agent_state",
    "restore_automated_agent_state",
    "validate_automated_agent_state",
]
