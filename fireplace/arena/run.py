"""A single Arena run, independent of HTTP and the battle engine.

The draft and record are persisted between requests.  Match actions remain in
``GameSession``; this state machine only owns choices made before a match and
the result reported after it ends.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from .draft import card_offer, hero_offer
from .pool import eligible_cards
from .rules import CLASSIC_SET, LARGE_SETS, SMALL_SETS, validate_pool_sets, validate_sets


def _ids(cards: object) -> tuple[str, ...]:
    return tuple(
        card if isinstance(card, str) else card.id if hasattr(card, "id") else card["id"]
        for card in cards
    )


@dataclass
class ArenaRun:
    """Validated transition state for one 30-pick, seven-win/three-loss run."""

    run_id: str
    seed: int
    nickname: str
    locale: str
    selected_sets: tuple[str, ...]
    stage: str = "hero"
    revision: int = 0
    hero_choices: tuple[str, ...] = ()
    hero_id: str | None = None
    choices: tuple[str, ...] = ()
    deck: list[str] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    match_index: int = 0
    pending_match_id: str | None = None

    @classmethod
    def create(
        cls, set_ids: list[str], nickname: str, locale: str, *, seed: int | None = None
    ) -> "ArenaRun":
        selected_sets = validate_sets(set_ids)
        if not isinstance(nickname, str) or not nickname.strip() or len(nickname.strip()) > 32:
            raise ValueError("nickname must contain 1 to 32 characters")
        if locale not in {"zhCN", "enUS"}:
            raise ValueError("locale must be zhCN or enUS")
        if seed is None:
            seed = random.SystemRandom().randrange(1 << 63)
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        run = cls(
            run_id=str(uuid.uuid4()),
            seed=seed,
            nickname=nickname.strip(),
            locale=locale,
            selected_sets=selected_sets,
        )
        run.hero_choices = hero_offer(random.Random(seed))
        return run

    def _draft_rng(self, pick_number: int) -> random.Random:
        # An independent stream per pick makes saved offers stable after a
        # restart without serializing Python's internal RNG state.
        return random.Random(self.seed + 1_000_003 * (pick_number + 1))

    def _next_choices(self) -> tuple[str, ...]:
        if self.hero_id is None:
            raise ValueError("choose a hero before drafting cards")
        pool = eligible_cards(self.selected_sets, self.hero_id)
        return _ids(card_offer(self._draft_rng(len(self.deck)), pool))

    def choose_hero(self, hero_id: str) -> None:
        if self.stage != "hero" or hero_id not in self.hero_choices:
            raise ValueError("hero is not an available choice")
        self.hero_id = hero_id
        self.choices = self._next_choices()
        self.stage = "draft"
        self.revision += 1

    def choose_card(self, card_id: str) -> None:
        if self.stage != "draft" or card_id not in self.choices:
            raise ValueError("card is not an available choice")
        self.deck.append(card_id)
        if len(self.deck) == 30:
            self.choices = ()
            self.stage = "ready"
        else:
            self.choices = self._next_choices()
        self.revision += 1

    def start_match(self) -> str:
        if self.stage != "ready" or len(self.deck) != 30 or self.hero_id is None:
            raise ValueError("the Arena deck is not ready")
        self.pending_match_id = f"{self.run_id}:{self.match_index}"
        self.stage = "match"
        self.revision += 1
        return self.pending_match_id

    def settle_match(self, match_id: str, human_won: bool | None) -> None:
        if self.stage != "match" or match_id != self.pending_match_id:
            raise ValueError("match result is unavailable or already recorded")
        if human_won is True:
            self.wins += 1
        elif human_won is False:
            self.losses += 1
        elif human_won is not None:
            raise ValueError("human_won must be true, false, or null")
        self.match_index += 1
        self.pending_match_id = None
        self.stage = "complete" if self.wins >= 7 or self.losses >= 3 else "ready"
        self.revision += 1

    def recover_without_match(self) -> None:
        """Keep the draft after a process restart; an unplayed game is retried."""

        if self.stage == "match":
            self.stage = "ready"
            self.pending_match_id = None
            self.revision += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "run_id": self.run_id,
            "seed": self.seed,
            "nickname": self.nickname,
            "locale": self.locale,
            "selected_sets": list(self.selected_sets),
            "stage": self.stage,
            "revision": self.revision,
            "hero_choices": list(self.hero_choices),
            "hero_id": self.hero_id,
            "choices": list(self.choices),
            "deck": list(self.deck),
            "wins": self.wins,
            "losses": self.losses,
            "match_index": self.match_index,
            "pending_match_id": self.pending_match_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArenaRun":
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported Arena save version")
        saved_sets = tuple(value["selected_sets"])
        if CLASSIC_SET in saved_sets:
            # Runs created before Classic became fixed counted it as a large
            # expansion. Let those drafts finish with their original choices.
            expansions = tuple(set_id for set_id in saved_sets if set_id != CLASSIC_SET)
            validate_pool_sets(expansions)
            old_budget = 3 * (1 + sum(set_id in LARGE_SETS for set_id in expansions))
            old_budget += sum(set_id in SMALL_SETS for set_id in expansions)
            if saved_sets.count(CLASSIC_SET) != 1 or old_budget != 16:
                raise ValueError("invalid legacy Arena set selection")
            selected_sets = saved_sets
        else:
            selected_sets = validate_sets(saved_sets)
        stage = value["stage"]
        if stage not in {"hero", "draft", "ready", "match", "complete"}:
            raise ValueError("invalid Arena save stage")
        deck = value["deck"]
        if not isinstance(deck, list) or len(deck) > 30 or any(not isinstance(card, str) for card in deck):
            raise ValueError("invalid Arena saved deck")
        run = cls(
            run_id=str(value["run_id"]),
            seed=int(value["seed"]),
            nickname=str(value["nickname"]),
            locale=str(value["locale"]),
            selected_sets=selected_sets,
            stage=stage,
            revision=int(value["revision"]),
            hero_choices=tuple(value["hero_choices"]),
            hero_id=value["hero_id"],
            choices=tuple(value["choices"]),
            deck=list(deck),
            wins=int(value["wins"]),
            losses=int(value["losses"]),
            match_index=int(value["match_index"]),
            pending_match_id=value["pending_match_id"],
        )
        if run.wins < 0 or run.losses < 0 or run.revision < 0:
            raise ValueError("invalid Arena saved record")
        return run


__all__ = ["ArenaRun"]
