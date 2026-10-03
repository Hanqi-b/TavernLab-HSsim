"""Privacy aware effect records for browser presentation frames.

The engine exposes effect callbacks through :class:`GameManager`, but those
callbacks carry Fireplace entities and can run while a simultaneous death
batch is being resolved.  ``EffectTimeline`` is the small adapter between the
engine observer API and the web presentation contract.  It is deliberately
owned by ``WebGame`` rather than ``GameSession`` so command line and replay
sessions keep their existing observer graph.

Only a filtered observation is copied at callback time.  Entity labels are
looked up from that observation, from earlier public battlefield snapshots,
or from a public non-secret played-card event explicitly seeded by the web
coordinator.  The Fireplace objects themselves never leave this module.
"""

from __future__ import annotations

import copy
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import Any

from hearthstone.enums import CardType, Zone

from ..managers import BaseObserver
from .public_events import visible_entity_details


_MAX_EFFECTS_PER_EXECUTION = 512
_MISSING = object()


def _field(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _class_name(value: object) -> str:
    return type(value).__name__.upper() if value is not None else ""


def _entity_id(value: object) -> int | None:
    entity_id = _field(value, "entity_id")
    return entity_id if type(entity_id) is int else None


def _enum_name(value: object) -> str | None:
    name = _field(value, "name")
    if name:
        return str(name).upper()
    if isinstance(value, str):
        return value.upper()
    if type(value) is int:
        try:
            return CardType(value).name
        except (TypeError, ValueError):
            return None
    return None


def _card_type(card: object) -> str | None:
    data = _field(card, "data")
    return _enum_name(_field(card, "type", _field(data, "type")))


def _json_copy(value: object) -> object:
    """Copy a filtered observation without retaining arbitrary engine values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, child in value.items():
            if isinstance(key, str):
                result[key] = _json_copy(child)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_copy(child) for child in value]
    # ``build_observation`` already returns JSON-safe values.  Dropping an
    # unexpected fake-session value is safer than serializing an engine handle.
    return None


class EffectTimeline(BaseObserver):
    """Collect one execution's public effect records.

    The observer stays registered for the lifetime of one ``WebGame`` but is
    active only between :meth:`begin` and :meth:`end`.  Every callback is
    defensive: presentation telemetry must never interrupt engine resolution.
    """

    def __init__(self, session: object, human: object) -> None:
        self.session = session
        self.human = human
        self._manager: object | None = None
        self._registered = False
        self._active = False
        self._active_actor = "self"
        self._records: list[dict[str, Any]] = []
        self._known: dict[int, dict[str, str]] = {}
        self._pending_damage: defaultdict[object, deque[dict[str, Any]]] = defaultdict(deque)
        self._deck_destroy_key: tuple[object, ...] | None = None
        self._deck_destroy_record: dict[str, Any] | None = None
        self._deck_destroy_action: object | None = None
        self._block_stack: list[int] = []
        self._next_block_id = 0
        # Keep the actual Hit action alive for the duration of one execution;
        # keying only on id(action) would allow a dynamically-created action
        # to reuse an address after an earlier action is collected.  The
        # action block also distinguishes a reusable listener invoked by two
        # separate triggers after its trigger_index has reset to zero.
        self._hit_batches: dict[tuple[int, int, int], tuple[object, int]] = {}
        self._next_batch_id = 0
        self._death_actions: list[object] = []
        self._effects_truncated = False
        self.last_truncated = False

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def active(self) -> bool:
        return self._active

    def register(self) -> None:
        """Attach to a session game manager when one is available."""

        if self._registered:
            return
        try:
            game = _field(self.session, "game")
            manager = _field(game, "manager")
            register = _field(manager, "register")
            if not callable(register):
                return
            register(self)
            self._manager = manager
            self._registered = True
        except Exception:
            # Lightweight HTTP tests use sessions without an engine manager.
            self._manager = None
            self._registered = False

    def unregister(self) -> None:
        """Detach from the manager without requiring a manager API extension."""

        manager = self._manager
        self._active = False
        self._records.clear()
        self._pending_damage.clear()
        self._deck_destroy_key = None
        self._deck_destroy_record = None
        self._deck_destroy_action = None
        self._hit_batches.clear()
        self._death_actions.clear()
        self._block_stack.clear()
        self._next_block_id = 0
        self._manager = None
        self._registered = False
        if manager is None:
            return
        try:
            unregister = _field(manager, "unregister")
            if callable(unregister):
                unregister(self)
                return
            observers = _field(manager, "observers")
            if observers is not None:
                while self in observers:
                    observers.remove(self)
        except Exception:
            # Detaching is best effort for fake managers.  A closing web match
            # must not turn an already completed game into an HTTP error.
            return

    close = unregister

    def begin(
        self,
        player: object | None = None,
        *,
        observation: object | None = None,
        public_event: Mapping[str, Any] | None = None,
    ) -> None:
        """Start recording one accepted decision and seed public identities."""

        self._records.clear()
        self._pending_damage.clear()
        self._deck_destroy_key = None
        self._deck_destroy_record = None
        self._deck_destroy_action = None
        self._hit_batches.clear()
        self._block_stack.clear()
        self._next_block_id = 0
        self._next_batch_id = 0
        self._death_actions.clear()
        self._effects_truncated = False
        self.last_truncated = False
        self._active_actor = self._actor_for(player) or "self"
        self._active = True
        if observation is None:
            observation = self._observation()
        self._remember_observation(observation)
        self._seed_public_event(public_event)

    def end(self) -> list[dict[str, Any]]:
        """Stop recording and return an isolated copy for one presentation frame."""

        self._active = False
        self.last_truncated = self._effects_truncated
        records = copy.deepcopy(self._records)
        self._records.clear()
        self._pending_damage.clear()
        self._deck_destroy_key = None
        self._deck_destroy_record = None
        self._deck_destroy_action = None
        self._hit_batches.clear()
        self._death_actions.clear()
        self._block_stack.clear()
        self._next_block_id = 0
        return records

    def drain(self) -> list[dict[str, Any]]:
        """Alias used by callers that think of the records as a queue."""

        return self.end()

    def _observation(self) -> object:
        try:
            observation = self.session.observation(self.human)
        except Exception:
            return {}
        copied = _json_copy(observation)
        return copied if isinstance(copied, Mapping) else {}

    def _actor_for(self, entity: object | None) -> str | None:
        if entity is None:
            return None
        try:
            if entity is self.human:
                return "self"
            opponent = _field(self.human, "opponent")
            if opponent is not None and entity is opponent:
                return "opponent"
            controller = _field(entity, "controller")
            if controller is self.human:
                return "self"
            if opponent is not None and controller is opponent:
                return "opponent"
        except Exception:
            return None
        return None

    def _entity_key(self, entity: object) -> object:
        entity_id = _entity_id(entity)
        return entity_id if entity_id is not None else id(entity)

    def _remember_observation(self, observation: object) -> None:
        if not isinstance(observation, Mapping):
            return
        try:
            details = visible_entity_details(observation)
        except Exception:
            details = {}
        owners: dict[int, str] = {}

        def visit(value: object, actor: str | None = None) -> None:
            if isinstance(value, Mapping):
                for key in ("self", "opponent"):
                    child = value.get(key)
                    if isinstance(child, (Mapping, list, tuple)):
                        visit(child, key)
                entity_id = value.get("entity_id")
                if type(entity_id) is int and actor in ("self", "opponent"):
                    owners[entity_id] = actor
                for key, child in value.items():
                    if key not in ("self", "opponent"):
                        visit(child, actor)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    visit(child, actor)

        visit(observation)
        for entity_id, detail in details.items():
            if type(entity_id) is not int or not isinstance(detail, Mapping):
                continue
            name = detail.get("name")
            if not isinstance(name, str) or not name:
                continue
            known = self._known.setdefault(entity_id, {})
            known["name"] = name
            card_id = detail.get("card_id")
            if isinstance(card_id, str) and card_id:
                known["card_id"] = card_id
            actor = owners.get(entity_id)
            if actor:
                known["actor"] = actor

    def _seed_public_event(self, event: Mapping[str, Any] | None) -> None:
        if not isinstance(event, Mapping):
            return
        source_id = event.get("source_entity_id")
        source_name = event.get("source_name")
        if type(source_id) is not int or not isinstance(source_name, str) or not source_name:
            return
        known = self._known.setdefault(source_id, {})
        known["name"] = source_name
        card_id = event.get("_source_card_id")
        if isinstance(card_id, str) and card_id:
            known["card_id"] = card_id
        actor = event.get("actor")
        if actor in ("self", "opponent"):
            known["actor"] = actor

    def _reference(self, entity: object | None) -> dict[str, str] | None:
        entity_id = _entity_id(entity)
        if entity_id is None:
            return None
        detail = self._known.get(entity_id)
        if not detail or not isinstance(detail.get("name"), str):
            return None
        return detail

    def _put_reference(
        self,
        event: dict[str, Any],
        prefix: str,
        entity: object | None,
    ) -> None:
        entity_id = _entity_id(entity)
        detail = self._reference(entity)
        if entity_id is None or detail is None:
            return
        event[f"{prefix}_entity_id"] = entity_id
        event[f"{prefix}_name"] = detail["name"]
        card_id = detail.get("card_id")
        if card_id:
            event[f"_{prefix}_card_id"] = card_id

    def _record(
        self,
        effect_type: str,
        *,
        source: object | None = None,
        target: object | None = None,
        actor_target: object | None = None,
        amount: object = _MISSING,
        batch_id: object = _MISSING,
        shield_broken: object = _MISSING,
        combat_damage: object = _MISSING,
        coalesce_key: object = _MISSING,
        suppress_source: bool = False,
        require_target: bool = False,
    ) -> None:
        if not self._active:
            return
        if len(self._records) >= _MAX_EFFECTS_PER_EXECUTION:
            self._effects_truncated = True
            return
        try:
            observation = self._observation()
            self._remember_observation(observation)
            actor = self._actor_for(source)
            if actor is None:
                actor = self._actor_for(actor_target)
            if actor is None:
                target_id = _entity_id(target)
                known = self._known.get(target_id) if target_id is not None else None
                actor = known.get("actor") if known else None
            actor = actor or self._active_actor or "self"
            event: dict[str, Any] = {"type": effect_type, "actor": actor}
            if not suppress_source:
                self._put_reference(event, "source", source)
            self._put_reference(event, "target", target)
            if require_target and "target_entity_id" not in event:
                return
            if amount is not _MISSING:
                if isinstance(amount, bool):
                    amount = int(amount)
                elif not isinstance(amount, (int, float)):
                    amount = int(amount)
                event["amount"] = amount
            if batch_id is not _MISSING:
                event["batch_id"] = batch_id
            if shield_broken is True:
                event["shield_broken"] = True
            if combat_damage is True:
                event["combat_damage"] = True
            record = {"event": event, "observation": observation}
            if (
                coalesce_key is not _MISSING
                and self._deck_destroy_key == coalesce_key
                and self._deck_destroy_record is not None
                and self._records
                and self._records[-1] is self._deck_destroy_record
            ):
                previous_event = self._deck_destroy_record["event"]
                previous_amount = previous_event.get("amount")
                current_amount = event.get("amount")
                if isinstance(previous_amount, (int, float)) and isinstance(
                    current_amount, (int, float)
                ):
                    previous_event["amount"] = previous_amount + current_amount
                self._deck_destroy_record["observation"] = observation
            else:
                self._records.append(record)
                if coalesce_key is not _MISSING:
                    self._deck_destroy_key = coalesce_key
                    self._deck_destroy_record = record
        except Exception:
            # Effects are presentation-only and must never affect gameplay.
            return

    def action_start(
        self, type: object, source: object, index: object, target: object
    ) -> None:
        """Track nested engine blocks so reusable actions get fresh batches."""

        del type, source, index, target
        if not self._active:
            return
        try:
            self._next_block_id += 1
            self._block_stack.append(self._next_block_id)
        except Exception:
            return

    def action_end(self, type: object, source: object) -> None:
        """Leave the current block without allowing observer failures out."""

        del type, source
        if not self._active:
            return
        try:
            if self._block_stack:
                self._block_stack.pop()
        except Exception:
            return

    def _batch_for_hit(self, action: object) -> int:
        trigger_index = _field(action, "trigger_index", 0)
        if type(trigger_index) is not int:
            try:
                trigger_index = int(trigger_index)
            except (TypeError, ValueError):
                trigger_index = 0
        block_id = self._block_stack[-1] if self._block_stack else 0
        key = (block_id, id(action), trigger_index)
        previous = self._hit_batches.get(key)
        if previous is not None and previous[0] is action:
            return previous[1]
        if previous is None or previous[0] is not action:
            self._next_batch_id += 1
            batch_id = self._next_batch_id
            self._hit_batches[key] = (action, batch_id)
        return batch_id

    def _pending_key(self, source: object, target: object) -> tuple[int, object]:
        return id(source), self._entity_key(target)

    def _remember_hit(self, action: object, source: object, target: object) -> None:
        key = self._pending_key(source, target)
        self._pending_damage[key].append({
            "source": source,
            "batch_id": self._batch_for_hit(action),
            "shield_before": bool(_field(target, "divine_shield", False)),
            "combat_damage": bool(_field(action, "combat_damage", False)),
        })

    def _consume_hit(self, source: object, target: object) -> dict[str, Any] | None:
        key = self._pending_key(source, target)
        pending = self._pending_damage.get(key)
        if pending:
            record = pending.popleft()
            if not pending:
                self._pending_damage.pop(key, None)
            return record
        # A few lightweight action doubles replace the source while retaining
        # the target.  Recover by target identity only; never by source name.
        target_key = self._entity_key(target)
        for candidate_key, candidate in tuple(self._pending_damage.items()):
            if candidate_key[1] != target_key or not candidate:
                continue
            record = candidate.popleft()
            if not candidate:
                self._pending_damage.pop(candidate_key, None)
            return record
        return None

    def targeted_action(self, action: object, source: object, target: object, *args: object) -> None:
        if not self._active:
            return
        try:
            name = _class_name(action)
            if name == "DESTROY":
                old_zone = args[0] if args else None
                if old_zone == Zone.DECK:
                    owner = _field(target, "controller")
                    trigger_index = _field(action, "trigger_index", 0)
                    if type(trigger_index) is not int:
                        try:
                            trigger_index = int(trigger_index)
                        except (TypeError, ValueError):
                            trigger_index = 0
                    block_id = self._block_stack[-1] if self._block_stack else 0
                    key = (
                        id(action), id(source), id(owner), block_id, trigger_index
                    )
                    self._deck_destroy_action = action
                    self._record(
                        "DECK_DESTROY",
                        actor_target=owner,
                        amount=1,
                        suppress_source=True,
                        coalesce_key=key,
                    )
                    return
                self._deck_destroy_key = None
                self._deck_destroy_record = None
                self._deck_destroy_action = None
            else:
                self._deck_destroy_key = None
                self._deck_destroy_record = None
                self._deck_destroy_action = None
            if name == "FATIGUE":
                # Fatigue targets a Player, while the public battlefield only
                # exposes that player's hero.  The callback runs after the
                # counter increments and before the queued Hit, so this
                # snapshot intentionally captures the hero before damage.
                hero = _field(target, "hero")
                self._record(
                    "FATIGUE", target=hero, actor_target=target,
                    amount=_field(target, "fatigue_counter", 0),
                    suppress_source=True, require_target=True,
                )
                return
            if name == "HIT":
                self._remember_hit(action, source, target)
                return
            if name == "DAMAGE":
                amount = args[0] if args else 0
                hit = self._consume_hit(source, target)
                self._record(
                    "DAMAGE", source=source, target=target,
                    amount=amount,
                    batch_id=hit.get("batch_id") if hit is not None else _MISSING,
                    shield_broken=(
                        True
                        if hit is not None
                        and hit.get("shield_before")
                        and not bool(_field(target, "divine_shield", False))
                        else _MISSING
                    ),
                    combat_damage=(
                        True
                        if hit is not None and hit.get("combat_damage")
                        else _MISSING
                    ),
                )
                return
            if name == "HEAL":
                self._record("HEAL", source=source, target=target,
                             amount=args[0] if args else 0)
                return
            if name == "GAINARMOR":
                self._record("ARMOR", source=source, target=target,
                             amount=args[0] if args else 0)
                return
            if name.endswith("BATTLECRY"):
                card = target
                if _card_type(card) != "MINION" or not bool(_field(card, "has_battlecry", False)):
                    return
                battlecry_target = args[0] if args else None
                self._record("BATTLECRY", source=card, target=battlecry_target,
                             actor_target=card)
                return
            if name == "DEATHRATTLE":
                if _card_type(target) != "MINION" or not bool(_field(target, "has_deathrattle", False)):
                    return
                self._record("DEATHRATTLE", source=target, target=target,
                             actor_target=target, require_target=True)
                return
            if name.startswith("SUMMON"):
                summoned = args[0] if args else None
                self._record("SUMMON", source=source, target=summoned,
                             actor_target=target)
                return
            if name == "DESTROY":
                self._record("DESTROY", source=source, target=target,
                             actor_target=target)
        except Exception:
            return

    def game_action(self, action: object, source: object, *args: object) -> None:
        if not self._active:
            return
        try:
            self._deck_destroy_key = None
            self._deck_destroy_record = None
            self._deck_destroy_action = None
            if _class_name(action) != "DEATH":
                return
            # Death's source is the Game object.  It is a batch coordinator,
            # never a public killer/source card.
            if any(action is previous for previous in self._death_actions):
                return
            self._death_actions.append(action)
            self._next_batch_id += 1
            death_batch_id = self._next_batch_id
            targets = []
            death_match_targets = _field(action, "_death_match_targets")
            if isinstance(death_match_targets, Mapping):
                for view in death_match_targets.values():
                    target = _field(view, "_match_original") or view
                    if target is not None:
                        targets.append(target)
            if not targets and args:
                targets.append(args[0])
            for target in targets:
                self._record(
                    "DEATH", target=target, actor_target=target,
                    batch_id=death_batch_id, suppress_source=True,
                    require_target=True,
                )
        except Exception:
            return


__all__ = ["EffectTimeline"]
