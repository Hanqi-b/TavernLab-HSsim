"""Individual Basic behavior probes for three damage battlecries and two other minions."""

import csv
from pathlib import Path

from hearthstone.enums import Race, Zone
from fireplace.exceptions import InvalidAction

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


def damage_battlecry_target(card_id, damage, target_kind):
    game = new_game()
    owner, opponent = game.player1, game.player2
    card = owner.give(card_id)
    if target_kind == "enemy_hero":
        target = opponent.hero
    elif target_kind == "friendly_minion":
        target = owner.summon("CS2_182")
    else:
        raise ValueError(target_kind)
    assert target in card.targets, f"{card_id}: {target_kind} target not offered"
    before = target.health
    card.play(target=target)
    observed = (before - target.health, card.zone, card in owner.field)
    assert observed == (damage, Zone.PLAY, True), observed
    return f"target={target_kind};health={before}->{target.health};minion={card.zone.name}"


def damage_battlecry_no_target(card_id):
    game = new_game()
    owner, opponent = game.player1, game.player2
    card = owner.give(card_id)
    assert card.is_playable() and card.targets
    mana_before = owner.mana
    try:
        card.play()
    except InvalidAction:
        pass
    else:
        raise AssertionError(f"{card_id}: a target was available but omitted")
    observed = (owner.hero.health, opponent.hero.health, card.zone, owner.mana)
    assert observed == (30, 30, Zone.HAND, mana_before), observed
    return f"heroes={owner.hero.health}/{opponent.hero.health};minion={card.zone.name};mana={owner.mana}"


def rifleman_enemy_hero():
    return damage_battlecry_target("CS2_141", 1, "enemy_hero")


def rifleman_friendly_minion():
    return damage_battlecry_target("CS2_141", 1, "friendly_minion")


def rifleman_no_target():
    return damage_battlecry_no_target("CS2_141")


def commando_enemy_hero():
    return damage_battlecry_target("CS2_150", 2, "enemy_hero")


def commando_friendly_minion():
    return damage_battlecry_target("CS2_150", 2, "friendly_minion")


def commando_no_target():
    return damage_battlecry_no_target("CS2_150")


def archer_enemy_hero():
    return damage_battlecry_target("CS2_189", 1, "enemy_hero")


def archer_friendly_minion():
    return damage_battlecry_target("CS2_189", 1, "friendly_minion")


def archer_no_target():
    return damage_battlecry_no_target("CS2_189")


def novice_draw_known_card():
    game = new_game()
    owner = game.player1
    owner.discard_hand()
    seeded = owner.give("CS2_231")
    seeded.shuffle_into_deck()
    novice = owner.give("EX1_015")
    novice.play()
    observed = (seeded.zone, seeded in owner.hand, len(owner.deck),
                novice.zone, novice in owner.field)
    assert observed == (Zone.HAND, True, 0, Zone.PLAY, True), observed
    return f"drawn={seeded.id}:{seeded.zone.name};deck={len(owner.deck)};novice={novice.zone.name}"


def novice_empty_deck():
    game = new_game()
    owner = game.player1
    owner.discard_hand()
    novice = owner.give("EX1_015")
    assert len(owner.deck) == 0
    novice.play()
    observed = (len(owner.hand), novice.zone, len(owner.deck))
    assert observed == (0, Zone.PLAY, 0), observed
    return f"hand={len(owner.hand)};deck={len(owner.deck)};novice={novice.zone.name}"


def dragonling_normal_summon():
    game = new_game()
    owner = game.player1
    mechanic = owner.give("EX1_025")
    mechanic.play()
    tokens = [minion for minion in owner.field if minion.id == "EX1_025t"]
    assert len(tokens) == 1, [minion.id for minion in owner.field]
    token = tokens[0]
    observed = (mechanic.zone, token.zone, token.atk, token.health,
                Race(token.race), len(owner.field))
    assert observed == (Zone.PLAY, Zone.PLAY, 2, 1, Race.MECHANICAL, 2), observed
    return f"mechanic={mechanic.zone.name};token={token.id}:{token.atk}/{token.health}:{Race(token.race).name};field={len(owner.field)}"


def dragonling_full_board():
    game = new_game()
    owner = game.player1
    for _ in range(6):
        owner.summon("CS2_231")
    mechanic = owner.give("EX1_025")
    mechanic.play()
    tokens = [minion for minion in owner.field if minion.id == "EX1_025t"]
    observed = (len(owner.field), mechanic.zone, len(tokens))
    assert observed == (7, Zone.PLAY, 0), observed
    return f"field={len(owner.field)};mechanic={mechanic.zone.name};tokens={len(tokens)}"


def main():
    cases = [
        ("CS2_141", "CS2_141_enemy", "Battlecry deals one to chosen enemy hero", rifleman_enemy_hero,
         "CardDefs.xml#CS2_141; fireplace/cards/classic/neutral_common.py:110; no prior effect assertion"),
        ("CS2_141", "CS2_141_friendly", "Battlecry can choose friendly minion and deal one", rifleman_friendly_minion,
         "CardDefs.xml#CS2_141; fireplace/cards/classic/neutral_common.py:110"),
        ("CS2_141", "CS2_141_no_target", "Available target requires selection; omission rejects before payment or entry", rifleman_no_target,
         "CardDefs.xml#CS2_141; fireplace/cards/classic/neutral_common.py:110"),
        ("CS2_150", "CS2_150_enemy", "Battlecry deals two to chosen enemy hero", commando_enemy_hero,
         "CardDefs.xml#CS2_150; fireplace/cards/classic/neutral_common.py:129; no prior effect assertion"),
        ("CS2_150", "CS2_150_friendly", "Battlecry can choose friendly minion and deal two", commando_friendly_minion,
         "CardDefs.xml#CS2_150; fireplace/cards/classic/neutral_common.py:129"),
        ("CS2_150", "CS2_150_no_target", "Available target requires selection; omission rejects before payment or entry", commando_no_target,
         "CardDefs.xml#CS2_150; fireplace/cards/classic/neutral_common.py:129"),
        ("CS2_189", "CS2_189_enemy", "Battlecry deals one to chosen enemy hero", archer_enemy_hero,
         "CardDefs.xml#CS2_189; fireplace/cards/classic/neutral_common.py:142; prior tests use card contextually"),
        ("CS2_189", "CS2_189_friendly", "Battlecry can choose friendly minion and deal one", archer_friendly_minion,
         "CardDefs.xml#CS2_189; fireplace/cards/classic/neutral_common.py:142"),
        ("CS2_189", "CS2_189_no_target", "Available target requires selection; omission rejects before payment or entry", archer_no_target,
         "CardDefs.xml#CS2_189; fireplace/cards/classic/neutral_common.py:142"),
        ("EX1_015", "EX1_015_known_deck", "Battlecry draws one known card from deck into hand", novice_draw_known_card,
         "CardDefs.xml#EX1_015; fireplace/cards/classic/neutral_common.py:42; tests/test_mechanics.py:111 partial"),
        ("EX1_015", "EX1_015_empty_deck", "Empty deck creates no card but minion enters board", novice_empty_deck,
         "CardDefs.xml#EX1_015; fireplace/cards/classic/neutral_common.py:42"),
        ("EX1_025", "EX1_025_token", "Battlecry summons exactly one 2/1 Mechanical Dragonling", dragonling_normal_summon,
         "CardDefs.xml#EX1_025; fireplace/cards/classic/neutral_common.py:213; no prior effect assertion"),
        ("EX1_025", "EX1_025_full_board", "When Mechanic fills seventh slot, no token is summoned", dragonling_full_board,
         "CardDefs.xml#EX1_025; fireplace/cards/classic/neutral_common.py:213"),
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
