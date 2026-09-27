"""Privacy-aware projections for the browser's public action timeline.

The engine action log contains the acting player's private choices and card
objects.  This module turns one accepted :class:`~fireplace.agent_api.Action`
into the small event shape understood by the browser.  It deliberately keeps
the privacy policy here instead of spreading card-type checks through the
match coordinator.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hearthstone.enums import CardType

from ..agent_api import Action


def _field(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _description_value(description: object, name: str) -> Any:
    value = _field(description, name)
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def decorate_visible_cards(value: object, descriptions: Mapping[str, object]) -> None:
    """Enrich already filtered observation cards with optional card text."""

    if isinstance(value, dict):
        card_id = value.get("card_id")
        if isinstance(card_id, str) and card_id:
            description = descriptions.get(card_id)
            if description is not None:
                name = _description_value(description, "name")
                text = _description_value(description, "text")
                locale = _description_value(description, "locale")
                if name:
                    value["name"] = str(name)
                if text is not None:
                    value["text"] = str(text)
                if locale:
                    value["locale"] = str(locale)
        for child in value.values():
            decorate_visible_cards(child, descriptions)
    elif isinstance(value, list):
        for child in value:
            decorate_visible_cards(child, descriptions)


def visible_card_ids(value: object) -> set[str]:
    """Collect card ids from a filtered observation."""

    result: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            card_id = item.get("card_id")
            if isinstance(card_id, str) and card_id:
                result.add(card_id)
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return result


def visible_entity_details(
    observation: Mapping[str, Any],
) -> dict[int, dict[str, str]]:
    """Index names and ids that this viewer is allowed to see."""

    result: dict[int, dict[str, str]] = {}

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            entity_id = item.get("entity_id")
            name = item.get("name")
            if type(entity_id) is int and isinstance(name, str) and name:
                detail = {"name": name}
                card_id = item.get("card_id")
                if isinstance(card_id, str) and card_id:
                    detail["card_id"] = card_id
                result[entity_id] = detail
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(observation)
    return result


def _enum_name(value: object) -> str | None:
    name = _field(value, "name")
    if name:
        return str(name).upper()
    if isinstance(value, str):
        return value.upper()
    if type(value) is int:
        try:
            return CardType(value).name
        except ValueError:
            pass
    return None


def _card_data(card: object) -> object:
    return _field(card, "data")


def _card_id(card: object) -> str | None:
    value = _field(card, "id")
    if value is None:
        value = _field(_card_data(card), "id")
    return str(value) if isinstance(value, (str, int)) and value else None


def _card_name(card: object) -> str | None:
    value = _field(_card_data(card), "name")
    if value is None:
        value = _field(card, "name")
    if value is None:
        try:
            value = str(card)
        except Exception:
            value = None
    return str(value) if isinstance(value, (str, int, float)) and value else None


def _is_secret(card: object) -> bool:
    data = _card_data(card)
    if bool(_field(data, "secret", False)):
        return True
    if _enum_name(_field(card, "spelltype")) == "SECRET":
        return True
    return type(card).__name__.upper() == "SECRET"


def _is_public_play(card: object) -> bool:
    """Return whether a played card's identity is public to its opponent.

    Ordinary spells are public when cast even though Fireplace moves them
    straight to the graveyard.  Quests and sidequests are public in the
    ``SECRET`` engine zone; only true Secrets remain concealed.
    """

    if card is None or _is_secret(card):
        return False
    data = _card_data(card)
    card_type = _field(card, "type", _field(data, "type"))
    type_name = _enum_name(card_type)
    # PLAY_CARD currently accepts minions, spells and weapons.  Keep the
    # privacy rule future-proof for any other real card type: once a non-secret
    # card has been accepted as played, its identity is public even if its
    # immediate zone is not visible in the next observation.
    return type_name not in {None, "INVALID", "SECRET", "GAME", "PLAYER"}


def _card_detail(card: object) -> dict[str, str] | None:
    card_id = _card_id(card)
    name = _card_name(card)
    if card_id is None and name is None:
        return None
    result: dict[str, str] = {}
    if name is not None:
        result["name"] = name
    if card_id is not None:
        result["card_id"] = card_id
    return result


def _put_detail(
    event: dict[str, Any], prefix: str, entity_id: int | None,
    detail: Mapping[str, str] | None,
) -> None:
    if type(entity_id) is not int or not detail:
        return
    name = detail.get("name")
    if not name:
        return
    event[f"{prefix}_name"] = name
    event[f"{prefix}_entity_id"] = entity_id
    card_id = detail.get("card_id")
    if card_id:
        event[f"_{prefix}_card_id"] = card_id


def project_action(
    player: object,
    human: object,
    action: Action,
    observation: Mapping[str, Any],
    *,
    seq: int,
    source: object | None = None,
) -> dict[str, Any]:
    """Project one accepted action under the explicit browser privacy policy."""

    actor = "self" if player is human else "opponent"
    details = visible_entity_details(observation)
    event: dict[str, Any] = {
        "seq": seq,
        "turn": observation.get("turn"),
        "actor": actor,
        "type": action.type,
    }

    if action.type == "CHOOSE":
        if actor == "self":
            _put_detail(event, "source", action.choice_entity_id,
                        details.get(action.choice_entity_id))
    elif action.type in {"ATTACK", "USE_HERO_POWER"}:
        _put_detail(event, "source", action.source_entity_id,
                    details.get(action.source_entity_id))
    elif action.type == "PLAY_CARD":
        if actor == "self":
            _put_detail(event, "source", action.source_entity_id,
                        details.get(action.source_entity_id))
        elif _is_public_play(source):
            # Capture the source before execution.  Spells and minions that
            # die immediately are no longer in the next observation.
            _put_detail(event, "source", action.source_entity_id,
                        _card_detail(source))

    if action.type in {"PLAY_CARD", "ATTACK", "USE_HERO_POWER"}:
        _put_detail(event, "target", action.target_entity_id,
                    details.get(action.target_entity_id))
    if actor == "self" and action.type == "PLAY_CARD" and action.position is not None:
        event["position"] = action.position
    return event


def localize_events(
    events: list[dict[str, Any]], descriptions: Mapping[str, object]
) -> list[dict[str, Any]]:
    """Strip internal card ids while refreshing names from the asset cache."""

    for event in events:
        source_card_id = event.pop("_source_card_id", None)
        target_card_id = event.pop("_target_card_id", None)
        if source_card_id in descriptions:
            name = _description_value(descriptions[source_card_id], "name")
            if name:
                event["source_name"] = str(name)
        if target_card_id in descriptions:
            name = _description_value(descriptions[target_card_id], "name")
            if name:
                event["target_name"] = str(name)
    return events


__all__ = [
    "decorate_visible_cards",
    "localize_events",
    "project_action",
    "visible_card_ids",
    "visible_entity_details",
]
