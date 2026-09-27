"""Browser-facing Arena draft state, separate from individual game sessions."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from fireplace.arena.rules import CLASSIC_SET, LARGE_SETS, SMALL_SETS
from fireplace.arena.run import ArenaRun
from fireplace.arena.store import ArenaStore, ArenaStoreConflict

from .catalog import CardCatalog
from .contracts import WebLifecycleError


class ArenaService:
    """Project and persist one local Arena run.

    Its caller owns request locking.  All returned values are JSON-safe and
    the game engine never receives a browser-supplied deck or card ID.
    """

    def __init__(
        self, *, catalog: CardCatalog | None = None, store: ArenaStore | None = None
    ) -> None:
        self.catalog = catalog if catalog is not None else CardCatalog()
        self.store = store if store is not None else ArenaStore()
        self.store.acquire_owner()
        try:
            self.run = self.store.load()
            if self.run is not None and self.run.stage == "match":
                # A process restart cannot restore a live GameSession yet.
                # After the prior process releases its owner lock, retry the
                # unfinished battle without counting a loss.
                previous = self.run
                recovered = copy.deepcopy(previous)
                recovered.recover_without_match()
                self.store.save(recovered, expected=previous)
                self.run = recovered
        except Exception:
            self.store.release_owner()
            raise

    def close(self) -> None:
        self.store.release_owner()

    def _commit(self, next_run: ArenaRun, previous: ArenaRun | None) -> None:
        try:
            self.store.save(next_run, expected=previous)
        except ArenaStoreConflict as exc:
            self.run = self.store.load()
            raise WebLifecycleError(str(exc), 409, self.state()) from exc
        self.run = next_run

    def _card(self, card_id: str, locale: str) -> dict[str, Any]:
        card = self.catalog.get_card(card_id, locale=locale)
        return card if card is not None else {"id": card_id, "name": card_id}

    def state(self, *, locale: str = "zhCN") -> dict[str, Any]:
        run = self.run
        if run is not None:
            locale = run.locale
        if locale not in {"zhCN", "enUS"}:
            raise ValueError("locale must be zhCN or enUS")
        # Catalog metadata is locale-aware but not the authority for Arena
        # eligibility.  The pool module independently validates card IDs.
        sets = {
            value["id"]: value
            for value in self.catalog.list_cards(locale=locale, page_size=1)["sets"]
        }

        def option(set_id: str) -> dict[str, Any]:
            entry = sets.get(set_id, {})
            return {
                "id": set_id,
                "label": entry.get("label", set_id),
                "count": entry.get("count", 0),
            }

        payload: dict[str, Any] = {
            "mode": run.stage if run is not None else "setup",
            "locale": locale,
            "pack_options": {
                "basic": option("BASIC"),
                "classic": option(CLASSIC_SET),
                "large": [option(set_id) for set_id in LARGE_SETS],
                "small": [option(set_id) for set_id in SMALL_SETS],
            },
        }
        if run is None:
            return payload
        payload.update(
            run_id=run.run_id,
            revision=run.revision,
            nickname=run.nickname,
            selected_sets=list(run.selected_sets),
            wins=run.wins,
            losses=run.losses,
            hero_offer=[self._card(card_id, locale) for card_id in run.hero_choices],
            card_offer=[self._card(card_id, locale) for card_id in run.choices],
            deck=[self._card(card_id, locale) for card_id in run.deck],
            hero=self._card(run.hero_id, locale) if run.hero_id else None,
        )
        return payload

    def _payload(self, body: object) -> Mapping[str, Any]:
        if not isinstance(body, Mapping):
            raise WebLifecycleError("request body must be a JSON object", 400, self.state())
        return body

    def _current(self, body: object, expected_stage: str) -> tuple[ArenaRun, Mapping[str, Any]]:
        data = self._payload(body)
        run = self.run
        if run is None:
            raise WebLifecycleError("no Arena run", 409, self.state())
        current = self.state()
        revision = data.get("revision")
        if (
            data.get("run_id") != run.run_id
            or type(revision) is not int
            or revision != run.revision
        ):
            raise WebLifecycleError("stale Arena state", 409, current)
        if run.stage != expected_stage:
            raise WebLifecycleError("Arena is not at this step", 409, current)
        return run, data

    def start(self, body: object, *, seed: int | None = None) -> dict[str, Any]:
        data = self._payload(body)
        if self.run is not None and self.run.stage != "complete":
            raise WebLifecycleError("finish the current Arena run first", 409, self.state())
        try:
            set_ids = data.get("set_ids")
            if not isinstance(set_ids, list):
                raise ValueError("set_ids must be a list")
            run = ArenaRun.create(
                set_ids,
                data.get("nickname"),
                data.get("locale"),
                seed=seed,
            )
        except (TypeError, ValueError) as exc:
            raise WebLifecycleError(str(exc), 400, self.state()) from exc
        self._commit(run, self.run)
        return self.state()

    def choose_hero(self, body: object) -> dict[str, Any]:
        run, data = self._current(body, "hero")
        next_run = copy.deepcopy(run)
        try:
            next_run.choose_hero(data.get("hero_id"))
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 400, self.state()) from exc
        self._commit(next_run, run)
        return self.state()

    def choose_card(self, body: object) -> dict[str, Any]:
        run, data = self._current(body, "draft")
        next_run = copy.deepcopy(run)
        try:
            next_run.choose_card(data.get("card_id"))
        except ValueError as exc:
            raise WebLifecycleError(str(exc), 400, self.state()) from exc
        self._commit(next_run, run)
        return self.state()

    def ready_for_battle(self, body: object) -> ArenaRun:
        run, _data = self._current(body, "ready")
        return run

    def mark_battle_started(self) -> dict[str, Any]:
        if self.run is None:
            raise ValueError("no Arena run")
        previous = self.run
        next_run = copy.deepcopy(previous)
        next_run.start_match()
        self._commit(next_run, previous)
        state = self.state()
        state["match_url"] = "/?arena=1"
        return state

    def settle(self, match_id: str, human_won: bool | None) -> dict[str, Any]:
        if self.run is None:
            raise ValueError("no Arena run")
        previous = self.run
        next_run = copy.deepcopy(previous)
        next_run.settle_match(match_id, human_won)
        self._commit(next_run, previous)
        return self.state()

    def reset(self, body: object) -> dict[str, Any]:
        run, _data = self._current(body, "complete")
        try:
            self.store.clear(expected=run)
        except ArenaStoreConflict as exc:
            self.run = self.store.load()
            raise WebLifecycleError(str(exc), 409, self.state()) from exc
        self.run = None
        return self.state()


__all__ = ["ArenaService"]
