"""Card-specific Basic behavior probes: EX1_169, EX1_192, EX1_593, EX1_606, EX1_581."""

import csv
from pathlib import Path

from hearthstone.enums import Zone

from basic_runtime_probe import new_game


OUT = Path(__file__).with_suffix(".csv")
FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
ROWS = []


def run(card_id, case_id, expected, probe, notes):
    try:
        observed = probe()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "confirmed_error"
    ROWS.append(dict(card_id=card_id, case_id=case_id, expected=expected,
                     observed=observed, outcome=outcome, notes=notes))


def innervate_temporary_mana():
    game = new_game()
    owner = game.player1
    owner.max_mana = 5
    owner.used_mana = 2
    before = (owner.mana, owner.max_mana, owner.temp_mana)
    spell = owner.give("EX1_169")
    spell.play()
    during = (owner.mana, owner.max_mana, owner.temp_mana, spell.zone)
    game.end_turn()
    after = (owner.max_mana, owner.temp_mana)
    assert before == (3, 5, 0), before
    assert during == (4, 5, 1, Zone.GRAVEYARD), during
    assert after == (5, 0), after
    return f"before={before};during={during};after_end_turn={after}"


def innervate_full_mana_cap():
    game = new_game()
    owner = game.player1
    assert owner.mana == owner.max_resources == 10
    spell = owner.give("EX1_169")
    spell.play()
    observed = (owner.mana, owner.max_mana, owner.temp_mana, spell.zone)
    assert observed == (10, 10, 0, Zone.GRAVEYARD), observed
    return f"mana={owner.mana};max={owner.max_mana};temp={owner.temp_mana};zone={spell.zone.name}"


def radiance_heals_only_friendly_hero():
    game = new_game()
    owner, opponent = game.player1, game.player2
    owner.hero.damage = 8
    opponent.hero.damage = 7
    spell = owner.give("EX1_192")
    spell.play()
    observed = (owner.hero.health, opponent.hero.health, spell.zone)
    assert observed == (27, 23, Zone.GRAVEYARD), observed
    return f"friendly_hero={owner.hero.health};enemy_hero={opponent.hero.health};zone={spell.zone.name}"


def radiance_cannot_overheal():
    game = new_game()
    owner = game.player1
    spell = owner.give("EX1_192")
    spell.play()
    observed = (owner.hero.health, spell.zone)
    assert observed == (30, Zone.GRAVEYARD), observed
    return f"friendly_hero={owner.hero.health};zone={spell.zone.name}"


def nightblade_enemy_hero():
    game = new_game()
    owner, opponent = game.player1, game.player2
    minion = owner.give("EX1_593")
    minion.play()
    observed = (owner.hero.health, opponent.hero.health, minion.zone,
                minion in owner.field)
    assert observed == (30, 27, Zone.PLAY, True), observed
    return f"friendly_hero={owner.hero.health};enemy_hero={opponent.hero.health};minion={minion.zone.name}"


def nightblade_armor_absorbs_damage():
    game = new_game()
    opponent = game.player2
    opponent.hero.armor = 2
    game.player1.give("EX1_593").play()
    observed = (opponent.hero.armor, opponent.hero.health)
    assert observed == (0, 29), observed
    return f"enemy_armor={opponent.hero.armor};enemy_health={opponent.hero.health}"


def shield_block_armor_and_draw():
    game = new_game()
    owner = game.player1
    owner.discard_hand()
    owner.hero.armor = 2
    seeded = owner.give("CS2_231")
    seeded.shuffle_into_deck()
    spell = owner.give("EX1_606")
    spell.play()
    observed = (owner.hero.armor, seeded in owner.hand, seeded.zone,
                len(owner.deck), spell.zone)
    assert observed == (7, True, Zone.HAND, 0, Zone.GRAVEYARD), observed
    return f"armor={owner.hero.armor};drawn={seeded.id}:{seeded.zone.name};deck={len(owner.deck)};spell={spell.zone.name}"


def shield_block_empty_deck():
    game = new_game()
    owner = game.player1
    owner.discard_hand()
    assert len(owner.deck) == 0
    spell = owner.give("EX1_606")
    spell.play()
    observed = (owner.hero.armor, len(owner.hand), len(owner.deck), spell.zone)
    assert observed == (5, 0, 0, Zone.GRAVEYARD), observed
    return f"armor={owner.hero.armor};hand={len(owner.hand)};deck={len(owner.deck)};spell={spell.zone.name}"


def sap_enemy_only_bounce():
    game = new_game()
    owner, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    friendly = owner.summon("CS2_182")
    spell = owner.give("EX1_581")
    assert target in spell.targets and friendly not in spell.targets
    spell.play(target=target)
    observed = (target.zone, target.controller is opponent,
                target in opponent.hand, target in opponent.field,
                friendly.zone, spell.zone)
    assert observed == (Zone.HAND, True, True, False, Zone.PLAY, Zone.GRAVEYARD), observed
    return f"target={target.zone.name};owner_preserved={target.controller is opponent};friendly={friendly.zone.name};spell={spell.zone.name}"


def sap_full_enemy_hand():
    game = new_game()
    owner, opponent = game.player1, game.player2
    opponent.discard_hand()
    target = opponent.summon("CS2_182")
    for _ in range(opponent.max_hand_size):
        opponent.give("CS2_231")
    assert len(opponent.hand) == opponent.max_hand_size
    spell = owner.give("EX1_581")
    spell.play(target=target)
    observed = (target.zone, target in opponent.hand,
                target in opponent.field, len(opponent.hand), spell.zone)
    assert observed == (Zone.GRAVEYARD, False, False, 10, Zone.GRAVEYARD), observed
    return f"target={target.zone.name};enemy_hand={len(opponent.hand)};spell={spell.zone.name}"


def main():
    cases = [
        ("EX1_169", "EX1_169_temporary", "Gain exactly one usable mana this turn without permanent crystal; clear at end turn", innervate_temporary_mana,
         "CardDefs.xml#EX1_169; fireplace/cards/classic/druid.py:272; contextual test_witchwood.py:38"),
        ("EX1_169", "EX1_169_cap", "At ten mana, temporary mana cannot exceed resource cap", innervate_full_mana_cap,
         "CardDefs.xml#EX1_169; fireplace/actions.py:1463"),
        ("EX1_192", "EX1_192_heal", "Heal friendly hero for five and leave enemy hero unchanged", radiance_heals_only_friendly_hero,
         "CardDefs.xml#EX1_192; fireplace/cards/classic/priest.py:315; no prior effect assertion"),
        ("EX1_192", "EX1_192_full_health", "At full health hero remains at maximum", radiance_cannot_overheal,
         "CardDefs.xml#EX1_192; fireplace/cards/classic/priest.py:315"),
        ("EX1_593", "EX1_593_battlecry", "Battlecry deals three to enemy hero and minion enters play", nightblade_enemy_hero,
         "CardDefs.xml#EX1_593; fireplace/cards/classic/neutral_common.py:87; no prior effect assertion"),
        ("EX1_593", "EX1_593_armor", "Enemy hero armor absorbs first two and health loses one", nightblade_armor_absorbs_damage,
         "CardDefs.xml#EX1_593; fireplace/cards/classic/neutral_common.py:87"),
        ("EX1_606", "EX1_606_draw", "Gain five armor and draw the known deck card", shield_block_armor_and_draw,
         "CardDefs.xml#EX1_606; fireplace/cards/classic/warrior.py:177; prior test refs are contextual"),
        ("EX1_606", "EX1_606_empty_deck", "Armor still gained when deck is empty; no card appears", shield_block_empty_deck,
         "CardDefs.xml#EX1_606; fireplace/cards/classic/warrior.py:177"),
        ("EX1_581", "EX1_581_bounce", "Only enemy minion target returns to opponent hand with controller preserved", sap_enemy_only_bounce,
         "CardDefs.xml#EX1_581; fireplace/cards/classic/rogue.py:207; contextual test_naxxramas.py:485"),
        ("EX1_581", "EX1_581_full_hand", "Full enemy hand causes bounced minion to be destroyed rather than overfill hand", sap_full_enemy_hand,
         "CardDefs.xml#EX1_581; fireplace/actions.py:769"),
    ]
    for card_id, case_id, expected, probe, notes in cases:
        run(card_id, case_id, expected, probe, notes)
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    print(f"cases={len(ROWS)}; pass={sum(r['outcome'] == 'pass' for r in ROWS)}; failures={sum(r['outcome'] != 'pass' for r in ROWS)}")
    for row in ROWS:
        if row["outcome"] != "pass":
            print(row["case_id"], row["observed"])
    if any(row["outcome"] != "pass" for row in ROWS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
