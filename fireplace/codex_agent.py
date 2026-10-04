"""Human-vs-Codex card decision agent.

Only the JSON-safe observation and the controller's already validated legal
action values cross this boundary.  The Codex process receives a bounded text
prompt and must return one indexed action; Fireplace still owns validation and
execution of the returned ``Action`` object.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .codex_transport import CodexTransport, CodexTransportError


class CodexAgentError(RuntimeError):
    """A safe, actionable error raised when Codex cannot choose a move."""


CARD_AGENT_INSTRUCTIONS = (
    "You are the decision service for a local card-game bot. "
    "Use only the visible observation and the supplied legal action menu. "
    "Choose exactly one legal action. Return exactly one JSON object with "
    'the shape {"action_id": <integer>} and no other keys or prose. '
    "You have no tools and must not request tools, files, shell commands, "
    "web search, plugins, MCP servers, or hidden game state. Do not provide "
    "chain of thought or an explanation."
)

_TOP_KEYS = frozenset({"turn", "phase", "active_seat", "self", "opponent", "pending_choice"})
_PLAYER_PUBLIC_KEYS = frozenset(
    {
        "hero",
        "board",
        "weapon",
        "hero_power",
        "mana",
        "max_mana",
        "deck_count",
        "quests",
    }
)
_PLAYER_PRIVATE_KEYS = frozenset({"hand", "secrets"})
_PLAYER_HIDDEN_KEYS = frozenset({"hand_count", "secrets_count", "secret_classes"})
_CARD_KEYS = frozenset(
    {
        "entity_id",
        "card_id",
        "name",
        "cost",
        "printed_cost",
        "powered_up",
        "active_modifiers",
        "atk",
        "printed_atk",
        "max_health",
        "printed_health",
        "has_deathrattle",
        "durability",
        "printed_durability",
        "choose_options",
        "zone_position",
        "health",
        "damage",
        "armor",
        "taunt",
        "divine_shield",
        "frozen",
        "stealthed",
        "poisonous",
        "dormant",
        "dormant_turns",
        "lifesteal",
        "reborn",
        "windfury",
        "rush",
        "charge",
        "silenced",
        "can_attack",
        "is_usable",
        "exhausted",
    }
)
_MODIFIER_KEYS = frozenset({"kind", "effect", "source", "grants"})
_ACTION_VALUE_KEYS = frozenset(
    {
        "schema_version",
        "type",
        "source_entity_id",
        "target_entity_id",
        "choose_option_entity_id",
        "position",
        "choice_entity_id",
        "mulligan_entity_ids",
    }
)
_MAX_PROMPT_BYTES = 256 * 1024
_MAX_VALUE_DEPTH = 16
_MAX_COLLECTION_ITEMS = 512
_MODEL_UNSET = object()


def _safe_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _safe_copy(value: object, depth: int = 0) -> object:
    """Copy only JSON primitives, with hard bounds for malformed callers."""

    if depth > _MAX_VALUE_DEPTH:
        return None
    scalar = _safe_scalar(value)
    if scalar is not None or value is None:
        return scalar
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_COLLECTION_ITEMS or not isinstance(key, str):
                break
            result[key] = _safe_copy(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_copy(item, depth + 1) for item in value[:_MAX_COLLECTION_ITEMS]]
    return None


def _filter_card(value: object, *, include_private: bool = True) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for key in _CARD_KEYS:
        if key not in value:
            continue
        if key in {"hand", "secrets"} and not include_private:
            continue
        if key == "active_modifiers":
            modifiers = value.get(key)
            if isinstance(modifiers, (list, tuple)):
                safe_modifiers = []
                for modifier in modifiers[:_MAX_COLLECTION_ITEMS]:
                    if not isinstance(modifier, Mapping):
                        continue
                    safe_modifier: dict[str, object] = {}
                    for modifier_key in _MODIFIER_KEYS:
                        if modifier_key not in modifier:
                            continue
                        nested = modifier[modifier_key]
                        if modifier_key in {"effect", "source"} and nested is not None:
                            safe_modifier[modifier_key] = _filter_card(nested)
                        else:
                            safe_modifier[modifier_key] = _safe_copy(nested)
                    safe_modifiers.append(safe_modifier)
                result[key] = safe_modifiers
            continue
        if key in {"choose_options"}:
            options = value.get(key)
            if isinstance(options, (list, tuple)):
                result[key] = [_filter_card(option) for option in options[:_MAX_COLLECTION_ITEMS]]
            continue
        result[key] = _safe_copy(value[key])
    return result


def _filter_player(value: object, *, private: bool) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for key in _PLAYER_PUBLIC_KEYS:
        if key not in value:
            continue
        if key in {"hero", "weapon", "hero_power"}:
            result[key] = (
                _filter_card(value[key]) if value[key] is not None else None
            )
        elif key in {"board", "quests"}:
            items = value[key]
            if isinstance(items, (list, tuple)):
                result[key] = [_filter_card(item) for item in items[:_MAX_COLLECTION_ITEMS]]
        else:
            result[key] = _safe_copy(value[key])
    if private:
        for key in _PLAYER_PRIVATE_KEYS:
            if key not in value:
                continue
            items = value[key]
            if isinstance(items, (list, tuple)):
                result[key] = [_filter_card(item) for item in items[:_MAX_COLLECTION_ITEMS]]
    else:
        for key in _PLAYER_HIDDEN_KEYS:
            if key not in value:
                continue
            if key == "secret_classes":
                classes = value[key]
                if isinstance(classes, (list, tuple)):
                    result[key] = [
                        [item for item in group if isinstance(item, str)]
                        if isinstance(group, (list, tuple))
                        else []
                        for group in classes[:_MAX_COLLECTION_ITEMS]
                    ]
                else:
                    result[key] = []
            else:
                result[key] = _safe_copy(value[key])
    return result


def _filter_observation(observation: Mapping[str, Any]) -> dict[str, object]:
    """Keep the explicit public observation shape and discard hidden extras."""

    if not isinstance(observation, Mapping):
        raise CodexAgentError("Codex needs a JSON-safe game observation")
    result: dict[str, object] = {}
    for key in _TOP_KEYS:
        if key not in observation:
            continue
        value = observation[key]
        if key == "self":
            result[key] = _filter_player(value, private=True)
        elif key == "opponent":
            result[key] = _filter_player(value, private=False)
        elif key == "pending_choice":
            if value is None:
                result[key] = None
            elif isinstance(value, Mapping):
                pending: dict[str, object] = {}
                options = value.get("options")
                if isinstance(options, (list, tuple)):
                    pending["options"] = [
                        _filter_card(option) for option in options[:_MAX_COLLECTION_ITEMS]
                    ]
                for pending_key in ("min_count", "max_count"):
                    if pending_key in value:
                        pending[pending_key] = _safe_copy(value[pending_key])
                result[key] = pending
        else:
            result[key] = _safe_copy(value)
    return result


def _visible_card_ids(value: object) -> tuple[str, ...]:
    result: list[str] = []

    def visit(current: object) -> None:
        if isinstance(current, Mapping):
            for key, item in current.items():
                if key == "card_id" and isinstance(item, str) and item and item not in result:
                    result.append(item)
                visit(item)
        elif isinstance(current, (list, tuple)):
            for item in current:
                visit(item)

    visit(value)
    return tuple(result)


def _field(card: object, name: str) -> object:
    try:
        value = getattr(card, name)
    except Exception:
        value = None
    if value is None:
        try:
            data = getattr(card, "data")
        except Exception:
            data = None
        try:
            value = getattr(data, name) if data is not None else None
        except Exception:
            value = None
    return value


def _catalog_value(value: object) -> object:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        values = []
        for item in value:
            converted = _catalog_value(item)
            if converted is not None and converted not in values:
                values.append(converted)
        return values
    return None


def _visible_catalog(
    card_ids: Sequence[str],
    cache: dict[str, dict[str, object] | None] | None = None,
) -> list[dict[str, object]]:
    """Load only metadata for IDs present in the already filtered view."""

    if not card_ids:
        return []
    requested_ids = tuple(card_ids)
    if cache is not None:
        missing = [card_id for card_id in card_ids if card_id not in cache]
        if not missing:
            return [
                dict(cache[card_id])
                for card_id in requested_ids
                if cache[card_id] is not None
            ]
        card_ids = tuple(missing)
    try:
        from . import card_data

        cards, _provenance = card_data.load_card_data()
    except Exception:
        if cache is not None:
            for card_id in card_ids:
                cache[card_id] = None
        return []
    result: list[dict[str, object]] = []
    for card_id in card_ids:
        card = cards.get(card_id)
        if card is None:
            continue
        entry: dict[str, object] = {"card_id": card_id}
        for key in ("name", "text", "type"):
            value = _catalog_value(_field(card, key))
            if value is not None:
                entry[key] = value
        race = _catalog_value(_field(card, "races"))
        if race is None:
            race = _catalog_value(_field(card, "race"))
        if race is not None:
            entry["race"] = race
        keywords = _catalog_value(_field(card, "keywords"))
        if keywords is None:
            keywords = _catalog_value(_field(card, "mechanics"))
        if keywords is not None:
            entry["keywords"] = keywords
        result.append(entry)
        if cache is not None:
            cache[card_id] = entry
    if cache is not None:
        for card_id in card_ids:
            cache.setdefault(card_id, None)
        return [
            dict(cache[card_id])
            for card_id in requested_ids
            if cache[card_id] is not None
        ]
    return result


def _action_dict(action: object) -> dict[str, object]:
    if isinstance(action, Mapping):
        value = {
            key: action[key]
            for key in _ACTION_VALUE_KEYS
            if key in action
        }
    else:
        converter = getattr(action, "to_dict", None)
        if not callable(converter):
            raise CodexAgentError("Codex received a legal action without a JSON form")
        try:
            value = converter()
        except Exception as exc:
            raise CodexAgentError("Codex received an invalid legal action") from exc
    if not isinstance(value, dict):
        raise CodexAgentError("Codex received an invalid legal action")
    copied = _safe_copy(value)
    if not isinstance(copied, dict):
        raise CodexAgentError("Codex received an invalid legal action")
    return copied


def _unwrap_result(value: object) -> object:
    # CodexTransport returns result payloads.  Accepting a complete JSON-RPC
    # response makes small injected fakes easier to write and keeps this seam
    # backwards-compatible with test transports.
    if isinstance(value, Mapping) and "result" in value and "id" in value:
        return value["result"]
    return value


def _thread_id(value: object) -> str | None:
    value = _unwrap_result(value)
    if not isinstance(value, Mapping):
        return None
    thread = value.get("thread")
    if isinstance(thread, Mapping) and isinstance(thread.get("id"), str):
        return thread["id"]
    if isinstance(value.get("id"), str):
        return value["id"]
    return None


def _turn_id(value: object) -> str | None:
    value = _unwrap_result(value)
    if not isinstance(value, Mapping):
        return None
    turn = value.get("turn")
    if isinstance(turn, Mapping) and isinstance(turn.get("id"), str):
        return turn["id"]
    if isinstance(value.get("id"), str):
        return value["id"]
    return None


def _message_text(item: object) -> str | None:
    if not isinstance(item, Mapping) or item.get("type") != "agentMessage":
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


class CodexAgent:
    """Ask a persistent local Codex app-server to select one legal action."""

    async_decisions = True

    def __init__(
        self,
        model: str | None | object = _MODEL_UNSET,
        timeout: float | None = None,
        transport: object | None = None,
    ) -> None:
        if model is _MODEL_UNSET:
            model = os.environ.get("TAVERNLAB_CODEX_MODEL") or None
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ValueError("model must be a non-empty string or None")
        if timeout is None:
            env_timeout = os.environ.get("TAVERNLAB_CODEX_TIMEOUT")
            if env_timeout:
                try:
                    timeout = float(env_timeout)
                except (TypeError, ValueError) as exc:
                    raise ValueError("TAVERNLAB_CODEX_TIMEOUT must be a positive number") from exc
            else:
                timeout = 90
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a positive finite number")
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self.model = model.strip() if isinstance(model, str) else None
        self.timeout = timeout
        self.transport = transport if transport is not None else CodexTransport()
        self._thread_id: str | None = None
        self._catalog_cache: dict[str, dict[str, object] | None] = {}
        self._closed = False
        self._decision_lock = threading.RLock()

    def export_config(self) -> dict[str, object]:
        return {"model": self.model, "timeout": self.timeout}

    def choose_action(
        self,
        observation: Mapping[str, Any],
        legal_actions: Sequence[object],
    ) -> object:
        """Return the original legal action object selected by Codex."""

        if self._closed:
            raise CodexAgentError("Codex agent is closed; create a new agent to continue")
        try:
            actions = tuple(legal_actions)
        except (TypeError, ValueError) as exc:
            raise CodexAgentError("Codex cannot choose an action from an invalid legal-action list") from exc
        if not actions:
            raise CodexAgentError("Codex cannot choose an action because no legal actions are available")
        if len(actions) == 1:
            return actions[0]
        with self._decision_lock:
            if self._closed:
                raise CodexAgentError("Codex agent is closed; create a new agent to continue")
            started = time.monotonic()
            try:
                return self._choose_action(actions, observation)
            except TimeoutError as exc:
                self._reset_transport_sync()
                self._thread_id = None
                raise CodexAgentError(
                    "Codex took too long to choose an action; retry the decision or check local Codex login"
                ) from exc
            except CodexAgentError:
                self._reset_transport_sync()
                self._thread_id = None
                raise
            except CodexTransportError as exc:
                self._reset_transport_sync()
                self._thread_id = None
                if time.monotonic() - started >= self.timeout:
                    raise CodexAgentError(
                        "Codex took too long to choose an action; retry the decision or check local Codex login"
                    ) from exc
                raise CodexAgentError(
                    "Codex app-server is unavailable; check local Codex login and retry"
                ) from exc
            except Exception as exc:
                self._reset_transport_sync()
                self._thread_id = None
                raise CodexAgentError(
                    "Codex could not choose an action; retry the decision"
                ) from exc

    def _choose_action(self, actions: tuple[object, ...], observation: Mapping[str, Any]) -> object:
        filtered = _filter_observation(observation)
        visible_ids = _visible_card_ids(filtered)
        action_values = [_action_dict(action) for action in actions]
        prompt_payload: dict[str, object] = {
            "observation": filtered,
            "visible_card_catalog": _visible_catalog(visible_ids, self._catalog_cache),
            "legal_actions": [
                {"action_id": index, "action": action}
                for index, action in enumerate(action_values)
            ],
        }
        prompt = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(prompt.encode("utf-8")) > _MAX_PROMPT_BYTES:
            raise CodexAgentError("The visible game state is too large for a Codex decision; retry the turn")
        deadline = time.monotonic() + self.timeout
        self._ensure_session(deadline)
        turn_result = self._request(
            "turn/start",
            self._turn_params(prompt, len(actions)),
            deadline,
        )
        turn_id = _turn_id(turn_result)
        if turn_id is None:
            # The protocol normally returns the turn in the request response;
            # accepting only a matching turn/started notification keeps fake
            # and older app-server implementations interoperable.
            turn_id = self._wait_for_started_turn(deadline)
        return self._wait_for_completed_action(turn_id, len(actions), deadline, actions)

    def _ensure_session(self, deadline: float) -> None:
        if self._thread_id is not None:
            return
        self._call("start")
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "tavernlab-card-agent",
                    "title": "TavernLab Card Agent",
                    "version": "1",
                }
            },
            deadline,
        )
        self._notify("initialized")
        thread_result = self._request(
            "thread/start",
            {
                "model": self.model,
                "cwd": getattr(self.transport, "cwd", None),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
                "baseInstructions": CARD_AGENT_INSTRUCTIONS,
                "config": {
                    "features": {
                        "shell_tool": False,
                        "apps": False,
                        "browser_use": False,
                        "computer_use": False,
                        "plugins": False,
                        "multi_agent": False,
                        "multi_agent_v2": False,
                        "memories": False,
                        "skill_search": False,
                        "skill_mcp_dependency_install": False,
                        "hooks": False,
                        "image_generation": False,
                        "view_image": False,
                        "sleep_tool": False,
                        "tool_suggest": False,
                        "code_mode_host": False,
                    },
                    "web_search": "disabled",
                    "tools": {"view_image": False},
                    "mcp_servers": {},
                },
            },
            deadline,
        )
        thread_id = _thread_id(thread_result)
        if thread_id is None:
            raise CodexAgentError("Codex app-server did not return a usable card-agent thread")
        self._thread_id = thread_id

    def _turn_params(self, prompt: str, action_count: int) -> dict[str, object]:
        params: dict[str, object] = {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": prompt}],
            "outputSchema": {
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "integer",
                        "enum": list(range(action_count)),
                    }
                },
                "required": ["action_id"],
                "additionalProperties": False,
            },
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
            "disabledPluginIds": [],
            "cwd": getattr(self.transport, "cwd", None),
        }
        if self.model is not None:
            params["model"] = self.model
        return params

    def _wait_for_started_turn(self, deadline: float) -> str:
        while True:
            event = self._wait_notification(deadline)
            if event.get("method") != "turn/started":
                if event.get("method") == "error":
                    params = event.get("params")
                    if isinstance(params, Mapping) and params.get("threadId") not in (
                        None,
                        self._thread_id,
                    ):
                        continue
                self._handle_non_turn_event(event, None)
                continue
            params = event.get("params")
            if not isinstance(params, Mapping) or params.get("threadId") != self._thread_id:
                continue
            turn = params.get("turn")
            turn_id = turn.get("id") if isinstance(turn, Mapping) else None
            if isinstance(turn_id, str):
                return turn_id

    def _wait_for_completed_action(
        self,
        turn_id: str,
        action_count: int,
        deadline: float,
        actions: tuple[object, ...],
    ) -> object:
        completed_text: str | None = None
        while True:
            event = self._wait_notification(deadline)
            method = event.get("method")
            params = event.get("params")
            if method == "item/completed":
                if not isinstance(params, Mapping):
                    continue
                if params.get("threadId") != self._thread_id or params.get("turnId") != turn_id:
                    continue
                text = _message_text(params.get("item"))
                if text is not None:
                    completed_text = text
                continue
            if method == "error":
                if isinstance(params, Mapping):
                    if params.get("threadId") not in (None, self._thread_id):
                        continue
                    if params.get("turnId") not in (None, turn_id):
                        continue
                self._handle_non_turn_event(event, turn_id)
                continue
            if method != "turn/completed":
                self._handle_non_turn_event(event, turn_id)
                continue
            if not isinstance(params, Mapping) or params.get("threadId") != self._thread_id:
                continue
            turn = params.get("turn")
            if not isinstance(turn, Mapping) or turn.get("id") != turn_id:
                continue
            status = turn.get("status")
            if status != "completed":
                raise CodexAgentError("Codex did not complete the card decision; retry the turn")
            items = turn.get("items")
            if isinstance(items, (list, tuple)):
                for item in items:
                    text = _message_text(item)
                    if text is not None:
                        completed_text = text
            if completed_text is None:
                raise CodexAgentError("Codex completed without a final card action; retry the turn")
            return self._parse_action(completed_text, action_count, actions)

    @staticmethod
    def _handle_non_turn_event(event: Mapping[str, Any], turn_id: str | None) -> None:
        method = event.get("method")
        if method == "error":
            raise CodexAgentError("Codex reported an error while choosing a card action; retry the turn")
        # Server requests are denied by CodexTransport before reaching this
        # point.  An injected transport may expose them as events; fail fast
        # rather than leaving the app-server waiting for an approval response.
        if "id" in event and isinstance(method, str):
            raise CodexAgentError("Codex requested a tool or permission that is disabled for card decisions")

    def _wait_notification(self, deadline: float) -> Mapping[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexTransportError("Codex notification timeout")
        method = getattr(self.transport, "wait_for_notification", None)
        if not callable(method):
            raise CodexTransportError("Codex transport has no notification wait method")
        event = self._call(method, timeout=remaining)
        if not isinstance(event, Mapping):
            raise CodexTransportError("Codex transport returned an invalid notification")
        return event

    def _request(self, method: str, params: Mapping[str, Any], deadline: float) -> object:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexTransportError("Codex request timeout")
        return self._call("request", method, params, timeout=remaining)

    def _notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        if callable(getattr(self.transport, "notify", None)):
            if params is None:
                self._call("notify", method)
            else:
                self._call("notify", method, params)
        elif callable(getattr(self.transport, "send_notification", None)):
            if params is None:
                self._call("send_notification", method)
            else:
                self._call("send_notification", method, params)
        else:
            raise CodexTransportError("Codex transport cannot send notifications")

    def _call(self, method_or_name: object, *args: object, **kwargs: object) -> object:
        method = method_or_name if callable(method_or_name) else getattr(self.transport, method_or_name)
        return _unwrap_result(method(*args, **kwargs))

    def _parse_action(
        self,
        text: str,
        action_count: int,
        actions: tuple[object, ...],
    ) -> object:
        try:
            value = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CodexAgentError("Codex returned malformed action JSON; retry the decision") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"action_id"}
            or type(value.get("action_id")) is not int
            or not 0 <= value["action_id"] < action_count
        ):
            raise CodexAgentError("Codex returned an invalid legal action index; retry the decision")
        return actions[value["action_id"]]

    def _reset_transport_sync(self) -> None:
        reset = getattr(self.transport, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass

    async def aclose(self) -> None:
        self.close()

    def cancel(self) -> None:
        """Abort the in-flight decision while keeping the agent reusable."""

        self._thread_id = None
        self._reset_transport_sync()

    def close(self, *, wait: bool = False) -> None:
        """Cancel future decisions and terminate the app-server child."""

        self._closed = True
        self._thread_id = None
        close = getattr(self.transport, "close", None)
        if not callable(close):
            return
        try:
            close()
        except Exception:
            pass

    def __enter__(self) -> "CodexAgent":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["CARD_AGENT_INSTRUCTIONS", "CodexAgent", "CodexAgentError"]
