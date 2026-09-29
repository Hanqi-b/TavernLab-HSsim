"""Additional per-card random-domain and low-hand branches for two HOF cards."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE = HERE / "hof_probe.csv"
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def game_for(cls=CardClass.MAGE):
    game = prepare_empty_game(cls, cls)
    if game.current_player is not game.player1:
        game.end_turn()
    return game


def read():
    with PROBE.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(data):
    with PROBE.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("card_id", "case_id", "expected", "observed", "outcome", "notes"))
        writer.writeheader()
        writer.writerows(data)


def ragnaros_random_enemy_domain():
    reached = set()
    for seed in range(24):
        game = game_for()
        game.random.seed(seed)
        owner, opponent = game.player1, game.player2
        first = opponent.summon("CS2_182")
        second = opponent.summon("CS2_182")
        rag = owner.give("EX1_298")
        rag.play()
        game.end_turn()
        if opponent.hero.health == 22:
            hit = 0
            assert first.zone == second.zone == Zone.PLAY
        elif first.zone == Zone.GRAVEYARD:
            hit = 1
            assert opponent.hero.health == 30 and second.zone == Zone.PLAY
        elif second.zone == Zone.GRAVEYARD:
            hit = 2
            assert opponent.hero.health == 30 and first.zone == Zone.PLAY
        else:
            raise AssertionError(f"seed={seed};hero={opponent.hero.health};minions={first.zone},{second.zone}")
        assert owner.hero.health == 30 and rag.zone == Zone.PLAY
        reached.add(hit)
    assert reached == {0, 1, 2}, reached
    return f"24 fixed seeds; reached enemy hero and both minions={sorted(reached)}; exactly one 8-damage hit each"


def doomguard_random_discard_domain():
    ids = (WISP, "CS2_024", "CS2_029")
    survivors = set()
    for seed in range(24):
        game = game_for(CardClass.WARLOCK)
        owner = game.player1
        owner.discard_hand()
        candidates = [owner.give(cid) for cid in ids]
        game.random.seed(seed)
        doomguard = owner.give("EX1_310")
        doomguard.play()
        kept = [c for c in candidates if c.zone == Zone.HAND]
        gone = [c for c in candidates if c.zone == Zone.REMOVEDFROMGAME]
        assert len(kept) == 1 and len(gone) == 2 and doomguard.zone == Zone.PLAY, (seed, [(c.id,c.zone.name) for c in candidates])
        survivors.add(kept[0].id)
    assert survivors == set(ids), survivors
    return f"24 fixed seeds; every one of three cards can survive, exactly two discarded per game={sorted(survivors)}"


def doomguard_short_hand():
    outcomes = []
    for count in (0, 1):
        game = game_for(CardClass.WARLOCK)
        owner = game.player1
        owner.discard_hand()
        other = owner.give(WISP) if count else None
        doomguard = owner.give("EX1_310")
        doomguard.play()
        assert doomguard.zone == Zone.PLAY and len(owner.hand) == 0
        if other is not None:
            assert other.zone == Zone.REMOVEDFROMGAME
        outcomes.append((count, len(owner.hand), other.zone.name if other else None))
    return f"available_hand_0_and_1={outcomes};no exception;all available cards discarded"


def main():
    cases = [
        ("EX1_298", "seeded_random_enemy_character_domain", "Ragnaros hits exactly one random enemy character for 8; enemy hero and both minions each reachable across seeds.", ragnaros_random_enemy_domain),
        ("EX1_310", "seeded_two_of_three_discard_domain", "Doomguard discards exactly two distinct hand cards, and each of three candidates can survive across seeds.", doomguard_random_discard_domain),
        ("EX1_310", "zero_and_one_other_hand_cards", "Doomguard with zero or one other hand card discards only cards available, then enters play.", doomguard_short_hand),
    ]
    data = {(r["card_id"], r["case_id"]): r for r in read()}
    for cid, case_id, expected, probe in cases:
        try:
            observed, outcome = probe(), "pass"
        except Exception as error:
            observed, outcome = f"{type(error).__name__}: {error}", "inconclusive"
        data[(cid, case_id)] = dict(card_id=cid, case_id=case_id, expected=expected,
                                    observed=observed, outcome=outcome,
                                    notes="Additional live branch probe; see hof_random_detail.py")
        print(cid, case_id, outcome, observed, flush=True)
    write(list(data.values()))


if __name__ == "__main__":
    main()
