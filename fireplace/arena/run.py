"""A single Arena run, independent of HTTP and the battle engine.

The draft and record are persisted between requests.  Match actions remain in
``GameSession``; this state machine only owns choices made before a match and
the result reported after it ends.
"""

from __future__ import annotations

import copy
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from .draft import card_offer, hero_offer
from .formats import CUSTOM_FORMAT_ID, get_format
from .pool import eligible_cards
from .rules import CLASSIC_SET, LARGE_SETS, SMALL_SETS, validate_pool_sets, validate_sets


def _ids(cards: object) -> tuple[str, ...]:
    return tuple(
        card if isinstance(card, str) else card.id if hasattr(card, "id") else card["id"]
        for card in cards
    )


@dataclass
class ArenaRun:
    """Validated thirty-pick run with format-specific record limits."""

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
    retired: bool = False
    format_id: str = CUSTOM_FORMAT_ID
    data_profile: dict[str, Any] = field(default_factory=dict)
    ai_drafts: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def create(
        cls, set_ids: list[str], nickname: str, locale: str, *,
        seed: int | None = None, format_id: str = CUSTOM_FORMAT_ID,
    ) -> "ArenaRun":
        config = get_format(format_id)
        data_profile: dict[str, Any] = {}
        if format_id == CUSTOM_FORMAT_ID:
            selected_sets = validate_sets(set_ids)
        else:
            from .formats import historical_profile
            if set_ids and tuple(set_ids) != config.fixed_sets:
                raise ValueError("historical Arena has a fixed card pool")
            selected_sets = config.fixed_sets
            data_profile = historical_profile()
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
            format_id=format_id,
            data_profile=data_profile,
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
        if self.format_id == CUSTOM_FORMAT_ID:
            pool = eligible_cards(self.selected_sets, self.hero_id)
            return _ids(card_offer(self._draft_rng(len(self.deck)), pool))
        from .draft import historical_card_offer
        from .pool import historical_eligible_cards
        from .formats import historical_profile, historical_draft_rng
        if historical_profile() != self.data_profile:
            raise ValueError("historical Arena data profile changed; cannot continue drafting")
        pick_number = len(self.deck) + 1
        pool = historical_eligible_cards(self.hero_id)
        return _ids(historical_card_offer(
            historical_draft_rng(self.seed, pick_number, purpose="human"), pool, pick_number
        ))

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
        config = get_format(self.format_id)
        self.stage = (
            "complete" if self.wins >= config.max_wins or self.losses >= config.max_losses
            else "ready"
        )
        self.revision += 1

    def retire(self) -> None:
        """End a ready run without changing its deck or record."""

        if self.stage != "ready":
            raise ValueError("the Arena run is not ready to retire")
        self.pending_match_id = None
        self.retired = True
        self.stage = "complete"
        self.revision += 1

    def recover_without_match(self) -> None:
        """Keep the draft after a process restart; an unplayed game is retried."""

        if self.stage == "match":
            self.stage = "ready"
            self.pending_match_id = None
            self.revision += 1

    def to_dict(self) -> dict[str, Any]:
        value = {
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
            "retired": self.retired,
        }
        if self.format_id != CUSTOM_FORMAT_ID:
            value.update(
                version=2, format_id=self.format_id,
                data_profile=copy.deepcopy(self.data_profile),
                ai_drafts=copy.deepcopy(self.ai_drafts),
            )
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArenaRun":
        if not isinstance(value, dict) or value.get("version") not in (1, 2):
            raise ValueError("unsupported Arena save version")
        format_id = CUSTOM_FORMAT_ID if value["version"] == 1 else value.get("format_id")
        config = get_format(format_id)
        if value["version"] == 2 and format_id == CUSTOM_FORMAT_ID:
            raise ValueError("custom Arena saves use version 1")
        saved_sets = tuple(value["selected_sets"])
        if format_id != CUSTOM_FORMAT_ID:
            if saved_sets != config.fixed_sets:
                raise ValueError("invalid historical Arena saved card pool")
            selected_sets = saved_sets
        elif CLASSIC_SET in saved_sets:
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
        retired = value.get("retired", False)
        if type(retired) is not bool:
            raise ValueError("invalid Arena saved retired marker")
        if retired and stage != "complete":
            raise ValueError("invalid Arena saved retired stage")
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
            retired=retired,
            format_id=format_id,
        )
        if run.wins < 0 or run.losses < 0 or run.revision < 0:
            raise ValueError("invalid Arena saved record")
        if format_id != CUSTOM_FORMAT_ID:
            profile = value.get("data_profile")
            drafts = value.get("ai_drafts")
            if not isinstance(profile, dict) or not profile or not isinstance(drafts, dict):
                raise ValueError("invalid historical Arena saved draft profile")
            from .ai_draft import AIDraft
            for index, draft in drafts.items():
                if not isinstance(index, str) or not index.isdecimal():
                    raise ValueError("invalid historical Arena draft match index")
                checked = AIDraft.from_dict(draft)
                if checked.data_profile != profile:
                    raise ValueError("historical Arena AI draft profile does not match the run")
                if (checked.trace[0]["header"]["seed"] != run.seed + 100_000 + int(index)
                        or checked.hero_id == run.hero_id):
                    raise ValueError("historical Arena AI draft does not match the run seed or hero")
            if stage == "match" and str(run.match_index) not in drafts:
                raise ValueError("historical Arena pending match has no saved AI draft")
            if any(int(index) > run.match_index for index in drafts):
                raise ValueError("historical Arena saved draft has a future match index")
            run.data_profile = copy.deepcopy(profile)
            run.ai_drafts = copy.deepcopy(drafts)
        return run


__all__ = ["ArenaRun"]
