"""Reproduce BT_731's minion-only transform condition in normal combat."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
OUT = Path(__file__).with_suffix(".csv")


def setup(target_kind):
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    opponent = player.opponent
    sporeling = player.summon("BT_731")
    target = opponent.summon("CS2_179") if target_kind == "minion" else opponent.hero
    before_health = target.health
    game.end_turn()
    game.end_turn()
    assert game.current_player is player and sporeling.can_attack()
    assert target in sporeling.attack_targets
    sporeling.attack(target)
    return opponent, target, before_health


def main():
    rows = []
    for case_id, kind in (("SPORE-01", "minion"), ("SPORE-02", "hero")):
        try:
            opponent, target, before_health = setup(kind)
            transformed = target.morphed
            observed = (f"target_health={before_health}->{target.health};"
                        f"target_zone={target.zone.name};morphed_into="
                        f"{getattr(transformed, 'id', None)};opponent_hero_zone="
                        f"{opponent.hero.zone.name};opponent_field="
                        f"{'|'.join(card.id for card in opponent.field)}")
            if kind == "minion":
                passed = (target.zone == Zone.SETASIDE and transformed is not None
                          and transformed.id == "BT_731" and opponent.hero.zone == Zone.PLAY)
                expected = "Damaged minion becomes BT_731; opposing hero stays in PLAY"
            else:
                passed = (target.health == before_health - 1 and target.zone == Zone.PLAY
                          and transformed is None
                          and not any(card.id == "BT_731" for card in opponent.field))
                expected = "Damaged hero loses 1 Health and remains HERO in PLAY; no transform"
            outcome = "pass" if passed else "confirmed_error"
        except Exception as error:
            expected = ("Damaged minion becomes BT_731" if kind == "minion" else
                        "Damaged hero remains HERO in PLAY; no transform")
            observed = f"exception={type(error).__name__}: {error}"
            outcome = "confirmed_error"
        rows.append(dict(case_id=case_id, mechanism="Targeting / Trigger / Transform",
                         card_ids="BT_731", expected=expected, observed=observed,
                         outcome=outcome))
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print({row["case_id"]: row["outcome"] for row in rows})


if __name__ == "__main__":
    main()
