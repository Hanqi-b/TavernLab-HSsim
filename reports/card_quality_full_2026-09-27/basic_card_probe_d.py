#!/usr/bin/env python3
"""Focused, card-specific behavior probes for twelve Basic YELLOW cards.

Run from the repository root with:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_d.py

Each case plays the named card in a minimal deterministic game and asserts the
card-specific state changes. The CSV is evidence output, not a generic smoke
test.
"""

import csv
import json
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from fireplace.exceptions import InvalidAction
from tests.utils import prepare_empty_game


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "basic_card_probe_d.csv"
CARDS_XML = ROOT / "fireplace/cards/CardDefs.xml"
AUDIT_CSV = HERE / "basic_quality.csv"

SOURCE = {
    "CS2_045": "fireplace/cards/classic/shaman.py:90-97",
    "CS2_046": "fireplace/cards/classic/shaman.py:100-106",
    "CS2_057": "fireplace/cards/classic/warlock.py:123-127",
    "CS2_061": "fireplace/cards/classic/warlock.py:95-99",
    "CS2_062": "fireplace/cards/classic/warlock.py:102-105",
    "CS2_072": "fireplace/cards/classic/rogue.py:60-68",
    "CS2_075": "fireplace/cards/classic/rogue.py:93-96",
    "CS2_076": "fireplace/cards/classic/rogue.py:99-107",
    "CS2_077": "fireplace/cards/classic/rogue.py:110-113",
    "CS2_088": "fireplace/cards/classic/paladin.py:8-11",
    "CS2_089": "fireplace/cards/classic/paladin.py:61-64",
    "CS2_092": "fireplace/cards/classic/paladin.py:68-75",
}

EXISTING_TESTS = {
    "CS2_045": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_046": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_057": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_061": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_062": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_072": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_075": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_076": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_077": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_088": "No direct behavior assertion found in tests/; the earlier audit had generic-play-smoke only.",
    "CS2_089": "tests/test_mechanics.py::test_spell_power (lines 792-795) asserts Holy Light heals the enemy hero by 6, but does not cover target classes or overheal cap.",
    "CS2_092": "tests/test_ungoro.py::test_the_voraxx (lines 172-180) asserts +4/+4-derived stats; test_misc/test_ungoro/test_boomsday references otherwise test interactions, not the full card contract.",
}


class ProbeMismatch(AssertionError):
    def __init__(self, label, expected, observed):
        super().__init__(f"{label}: expected {expected!r}, observed {observed!r}")
        self.observed = observed


def same(label, observed, expected):
    if observed != expected:
        raise ProbeMismatch(label, expected, observed)


def card_texts():
    root = ET.parse(CARDS_XML).getroot()
    result = {}
    for card_id in SOURCE:
        entity = root.find(f".//Entity[@CardID='{card_id}']")
        if entity is None:
            raise RuntimeError(f"CardDefs.xml has no entity {card_id}")
        name = entity.find("./Tag[@name='CARDNAME']")
        text = entity.find("./Tag[@name='CARDTEXT']")

        def localized(node, language):
            item = node.find(language) if node is not None else None
            if item is None:
                return ""
            return " ".join("".join(item.itertext()).split())

        result[card_id] = {
            "name_en": localized(name, "enUS"),
            "name_zh": localized(name, "zhCN"),
            "text_en": localized(text, "enUS"),
            "text_zh": localized(text, "zhCN"),
        }
    return result


def audit_rows():
    with AUDIT_CSV.open(encoding="utf-8-sig", newline="") as handle:
        return {row["card_id"]: row for row in csv.DictReader(handle)}


TEXT = card_texts()
AUDIT = audit_rows()
ROWS = []


def notes(card_id, detail):
    old = AUDIT.get(card_id, {})
    return (
        f"name={TEXT[card_id]['name_en']} / {TEXT[card_id]['name_zh']}; "
        f"EN={TEXT[card_id]['text_en']}; ZH={TEXT[card_id]['text_zh']}; "
        f"source={SOURCE[card_id]}; prior={old.get('status')} ({old.get('reason')}); "
        f"prior-tests={EXISTING_TESTS[card_id]}; case={detail}"
    )


def new_game(card_class):
    game = prepare_empty_game(card_class, card_class)
    return game, game.player1, game.player2


def summon(player, card_id):
    return player.summon(card_id)


def set_health(character, health):
    character.damage = character.max_health - health


def play_card(player, card_id, target=None, has_target=False):
    card = player.give(card_id)
    if card is None:
        raise RuntimeError(f"could not put {card_id} into hand")
    try:
        if has_target:
            card.play(target=target)
        else:
            card.play()
    except Exception as exc:
        raise ProbeMismatch(
            f"{card_id} valid play", "resolve successfully", f"{type(exc).__name__}: {exc}"
        ) from exc
    return card


def expect_invalid_target(player, card, target, label):
    mana_before = player.mana
    try:
        card.play(target=target)
    except InvalidAction:
        pass
    except Exception as exc:
        raise ProbeMismatch(
            label, "InvalidAction before resolution", f"{type(exc).__name__}: {exc}"
        ) from exc
    else:
        raise ProbeMismatch(label, "InvalidAction", "target was accepted")
    same(f"{label}: card remains in hand", card.zone, Zone.HAND)
    same(f"{label}: card is still present", card in player.hand, True)
    same(f"{label}: mana not spent", player.mana, mana_before)


def emit(card_id, case_id, expected, fn, case_notes):
    try:
        observed = fn()
    except ProbeMismatch as exc:
        outcome = "confirmed_error"
        observed = f"{exc.observed!r}; assertion={exc}"
    except Exception as exc:
        outcome = "inconclusive"
        observed = f"{type(exc).__name__}: {exc}; {traceback.format_exc(limit=2).strip()}"
    else:
        outcome = "pass"
        if not isinstance(observed, str):
            observed = json.dumps(observed, ensure_ascii=False, sort_keys=True)
    ROWS.append(
        {
            "card_id": card_id,
            "case_id": case_id,
            "expected": expected,
            "observed": observed,
            "outcome": outcome,
            "notes": notes(card_id, case_notes),
        }
    )


def rockbiter_minion_temp():
    game, own, opponent = new_game(CardClass.SHAMAN)
    ally = summon(own, "CS2_186")
    other_ally = summon(own, "CS2_231")
    enemy = summon(opponent, "CS2_182")
    before = (ally.atk, other_ally.atk, enemy.atk)
    card = own.give("CS2_045")
    expect_invalid_target(own, card, opponent.hero, "enemy character is not a friendly target")
    card.play(target=ally)
    during = (ally.atk, other_ally.atk, enemy.atk)
    same("only selected friendly minion gains +3 attack this turn", during, (before[0] + 3, before[1], before[2]))
    same("health is unchanged by attack buff", ally.health, ally.max_health)
    game.end_turn()
    after = (ally.atk, other_ally.atk, enemy.atk)
    same("temporary attack expires at end of caster turn", after, before)
    return {"before": before, "during": during, "after_end_turn": after, "card_zone": card.zone.name}


def rockbiter_hero_temp():
    game, own, _ = new_game(CardClass.SHAMAN)
    before = own.hero.atk
    play_card(own, "CS2_045", own.hero, has_target=True)
    during = own.hero.atk
    same("friendly hero is a valid character target and gains +3 attack", during, before + 3)
    game.end_turn()
    after = own.hero.atk
    same("hero attack bonus expires at end of caster turn", after, before)
    return {"before": before, "during": during, "after_end_turn": after}


def bloodlust_existing_scope_expiry():
    game, own, opponent = new_game(CardClass.SHAMAN)
    ally_a = summon(own, "CS2_186")
    ally_b = summon(own, "CS2_182")
    enemy = summon(opponent, "CS2_186")
    own_hero_attack = own.hero.atk
    before = (ally_a.atk, ally_b.atk, enemy.atk, own.hero.atk)
    play_card(own, "CS2_046")
    during = (ally_a.atk, ally_b.atk, enemy.atk, own.hero.atk)
    same("all and only current friendly minions gain +3 attack", during, (before[0] + 3, before[1] + 3, before[2], own_hero_attack))
    late_ally = summon(own, "CS2_231")
    same("minion summoned after spell resolution is not retroactively buffed", late_ally.atk, 1)
    game.end_turn()
    after = (ally_a.atk, ally_b.atk, enemy.atk, late_ally.atk)
    same("Bloodlust attack buffs expire at end of caster turn", after, before[:3] + (1,))
    return {"before": before, "during": during, "late_minion_attack": late_ally.atk, "after_end_turn": after}


def shadow_bolt_friendly_target():
    _, own, opponent = new_game(CardClass.WARLOCK)
    friend = summon(own, "CS2_186")
    enemy_hero = opponent.hero
    card = own.give("CS2_057")
    expect_invalid_target(own, card, enemy_hero, "Shadow Bolt requires a minion, not a hero")
    before = (friend.health, own.hero.health, opponent.hero.health)
    card.play(target=friend)
    after = (friend.damage, friend.health, friend.zone.name, own.hero.health, opponent.hero.health)
    same("4 damage applies to a friendly minion; heroes are unchanged", after, (4, before[0] - 4, "PLAY", before[1], before[2]))
    return {"before": before, "after": after}


def shadow_bolt_enemy_death():
    _, own, opponent = new_game(CardClass.WARLOCK)
    target = summon(opponent, "CS2_231")
    other = summon(opponent, "CS2_186")
    before_other = other.health
    play_card(own, "CS2_057", target, has_target=True)
    same("4 damage kills the 1-health enemy minion", target.zone, Zone.GRAVEYARD)
    same("killed target leaves enemy field", target in opponent.field, False)
    same("unselected enemy minion is unaffected", other.health, before_other)
    return {"target_zone": target.zone.name, "enemy_field_ids": [m.id for m in opponent.field], "other_health": other.health}


def drain_life_minion_and_heal():
    _, own, opponent = new_game(CardClass.WARLOCK)
    target = summon(opponent, "CS2_179")
    set_health(own.hero, 24)
    set_health(target, 4)
    play_card(own, "CS2_061", target, has_target=True)
    same("selected minion takes exactly 2 damage", (target.damage, target.health), (target.max_health - 2, 2))
    same("own hero restores exactly 2 health", own.hero.health, 26)
    same("enemy hero is unchanged", opponent.hero.health, 30)
    return {"target": {"damage": target.damage, "health": target.health, "zone": target.zone.name}, "own_hero": own.hero.health, "enemy_hero": opponent.hero.health}


def drain_life_friendly_minion_and_heal():
    _, own, opponent = new_game(CardClass.WARLOCK)
    target = summon(own, "CS2_186")
    set_health(own.hero, 24)
    card = play_card(own, "CS2_061", target, has_target=True)
    same("friendly minion target takes exactly 2 damage", (target.damage, target.health, target.zone), (2, 5, Zone.PLAY))
    same("own hero restores exactly 2 after friendly-target damage", own.hero.health, 26)
    same("opponent hero is unchanged", opponent.hero.health, 30)
    same("Drain Life spell is in graveyard after resolution", card.zone, Zone.GRAVEYARD)
    return {"friendly_target": {"damage": target.damage, "health": target.health, "zone": target.zone.name}, "own_hero": own.hero.health, "opponent_hero": opponent.hero.health, "spell_zone": card.zone.name}


def drain_life_enemy_hero_and_cap():
    _, own, opponent = new_game(CardClass.WARLOCK)
    set_health(opponent.hero, 20)
    set_health(own.hero, 27)
    play_card(own, "CS2_061", opponent.hero, has_target=True)
    same("enemy hero target loses exactly 2 health", opponent.hero.health, 18)
    same("own hero heals 2 independently of target side", own.hero.health, 29)
    play_card(own, "CS2_061", opponent.hero, has_target=True)
    same("healing cannot exceed own hero maximum health", own.hero.health, 30)
    same("second target hit also deals 2", opponent.hero.health, 16)
    return {"enemy_hero": opponent.hero.health, "own_hero": own.hero.health}


def drain_life_lethal_minion():
    _, own, opponent = new_game(CardClass.WARLOCK)
    target = summon(opponent, "CS2_231")
    set_health(own.hero, 25)
    play_card(own, "CS2_061", target, has_target=True)
    same("2 damage kills a 1-health minion", target.zone, Zone.GRAVEYARD)
    same("lethal target is removed from enemy field", target in opponent.field, False)
    same("Drain Life still heals its hero after lethal damage", own.hero.health, 27)
    return {"target_zone": target.zone.name, "enemy_field_ids": [m.id for m in opponent.field], "own_hero": own.hero.health}


def hellfire_all_characters():
    _, own, opponent = new_game(CardClass.WARLOCK)
    own_survivor = summon(own, "CS2_182")
    own_victim = summon(own, "CS2_231")
    enemy_victim = summon(opponent, "CS2_231")
    enemy_croc = summon(opponent, "CS2_120")
    play_card(own, "CS2_062")
    same("both heroes take 3 damage", (own.hero.health, opponent.hero.health), (27, 27))
    same("friendly surviving minion takes 3", (own_survivor.damage, own_survivor.health), (3, 2))
    same("friendly 1-health minion dies", own_victim.zone, Zone.GRAVEYARD)
    same("enemy 1-health minion dies", enemy_victim.zone, Zone.GRAVEYARD)
    same("enemy minion at 3 health dies to exactly 3 damage", enemy_croc.zone, Zone.GRAVEYARD)
    return {"heroes": [own.hero.health, opponent.hero.health], "survivor": {"damage": own_survivor.damage, "health": own_survivor.health}, "dead_minions": [own_victim.zone.name, enemy_victim.zone.name, enemy_croc.zone.name]}


def backstab_undamaged_only():
    _, own, opponent = new_game(CardClass.ROGUE)
    wounded = summon(opponent, "CS2_179")
    fresh = summon(opponent, "CS2_179")
    wounded.damage = 1
    card = own.give("CS2_072")
    mana_before = own.mana
    expect_invalid_target(own, card, wounded, "damaged minion is not a valid Backstab target")
    same("rejected target does not spend mana", own.mana, mana_before)
    same("invalid target remains undamaged", wounded.damage, 1)
    card.play(target=fresh)
    same("undamaged enemy minion takes exactly 2 damage", (fresh.damage, fresh.health), (2, fresh.max_health - 2))
    return {"wounded_target": {"damage": wounded.damage, "zone": wounded.zone.name}, "fresh_target": {"damage": fresh.damage, "health": fresh.health}}


def sinister_strike_enemy_hero_only():
    _, own, opponent = new_game(CardClass.ROGUE)
    ally = summon(own, "CS2_182")
    enemy = summon(opponent, "CS2_182")
    before = (own.hero.health, opponent.hero.health, ally.health, enemy.health)
    play_card(own, "CS2_075")
    after = (own.hero.health, opponent.hero.health, ally.health, enemy.health)
    same("Sinister Strike deals 3 to the enemy hero only", after, (before[0], before[1] - 3, before[2], before[3]))
    return {"before": before, "after": after}


def backstab_friendly_minion_allowed():
    _, own, _ = new_game(CardClass.ROGUE)
    target = summon(own, "CS2_179")
    play_card(own, "CS2_072", target, has_target=True)
    same("undamaged friendly minion is also a valid target", (target.damage, target.health), (2, target.max_health - 2))
    return {"friendly_target": {"damage": target.damage, "health": target.health, "zone": target.zone.name}}


def assassinate_destroy_and_target_rules():
    _, own, opponent = new_game(CardClass.ROGUE)
    friendly = summon(own, "CS2_186")
    enemy = summon(opponent, "CS2_186")
    enemy.divine_shield = True
    card = own.give("CS2_076")
    expect_invalid_target(own, card, friendly, "Assassinate cannot target friendly minions")
    expect_invalid_target(own, card, opponent.hero, "Assassinate cannot target a hero")
    before_enemy_hero = opponent.hero.health
    card.play(target=enemy)
    same("enemy minion is destroyed even with Divine Shield", enemy.zone, Zone.GRAVEYARD)
    same("destroyed minion leaves field", enemy in opponent.field, False)
    same("friendly minion is unaffected", friendly.zone, Zone.PLAY)
    same("enemy hero is unaffected", opponent.hero.health, before_enemy_hero)
    return {"enemy_zone": enemy.zone.name, "enemy_field_ids": [m.id for m in opponent.field], "friendly_zone": friendly.zone.name, "enemy_hero": opponent.hero.health}


def load_deck_top_first(player, ids_top_first):
    cards = {}
    for card_id in reversed(ids_top_first):
        cards[card_id] = player.card(card_id, zone=Zone.DECK)
    return cards


def sprint_four_known_cards():
    _, own, _ = new_game(CardClass.ROGUE)
    ordered = ["CS2_231", "CS2_142", "CS2_182", "CS2_186", "CS2_179", "CS2_119"]
    load_deck_top_first(own, ordered)
    before_hand = len(own.hand)
    play_card(own, "CS2_077")
    expected_drawn = ordered[:4]
    observed_drawn = [card.id for card in own.hand]
    same("Sprint draws exactly four top cards in deck order", observed_drawn, expected_drawn)
    same("two lower deck cards stay in deck with next card still on top", [card.id for card in own.deck], list(reversed(ordered[4:])))
    same("next card to draw remains the fourth card after Sprint", own.deck[-1].id, ordered[4])
    same("hand increases by four net after Sprint itself leaves", len(own.hand), before_hand + 4)
    return {"drawn": observed_drawn, "remaining_deck": [card.id for card in own.deck], "hand_count": len(own.hand)}


def sprint_short_deck_fatigue():
    _, own, _ = new_game(CardClass.ROGUE)
    # prepare_empty_game suppresses fatigue by default; enable normal draw behavior.
    own.cant_fatigue = False
    ordered = ["CS2_231", "CS2_142"]
    load_deck_top_first(own, ordered)
    set_health(own.hero, 20)
    play_card(own, "CS2_077")
    same("all available cards are drawn", [card.id for card in own.hand], ordered)
    same("empty deck remains empty", len(own.deck), 0)
    same("two failed draws cause fatigue 1 then 2", (own.fatigue_counter, own.hero.health), (2, 17))
    return {"hand": [card.id for card in own.hand], "fatigue_counter": own.fatigue_counter, "hero_health": own.hero.health}


def sprint_overdraw_full_hand():
    _, own, _ = new_game(CardClass.ROGUE)
    for _ in range(9):
        own.give("CS2_231")
    ordered = ["CS2_231", "CS2_142", "CS2_182", "CS2_186"]
    deck_cards = load_deck_top_first(own, ordered)
    play_card(own, "CS2_077")
    same("draw leaves hand at maximum size", len(own.hand), own.max_hand_size)
    same("first available top card enters the last hand slot", own.hand[-1].id, ordered[0])
    same("remaining overdrawn cards leave hand and enter removed-from-game zone", [deck_cards[card_id].zone for card_id in ordered[1:]], [Zone.REMOVEDFROMGAME] * 3)
    same("all four deck cards are consumed", len(own.deck), 0)
    return {"hand_count": len(own.hand), "last_hand_card": own.hand[-1].id, "overdrawn_removed": {card_id: deck_cards[card_id].zone.name for card_id in ordered[1:]}, "deck_count": len(own.deck)}


def guardian_injured_hero():
    _, own, _ = new_game(CardClass.PALADIN)
    set_health(own.hero, 22)
    guardian = play_card(own, "CS2_088")
    same("Battlecry restores 6 to damaged hero", own.hero.health, 28)
    same("hero maximum health is unchanged", own.hero.max_health, 30)
    same("Guardian enters play with printed 5/6 body", (guardian.zone, guardian.atk, guardian.max_health, guardian.health), (Zone.PLAY, 5, 6, 6))
    return {"hero_health": own.hero.health, "hero_max_health": own.hero.max_health, "guardian": {"zone": guardian.zone.name, "atk": guardian.atk, "health": guardian.health}}


def guardian_full_health_cap():
    _, own, _ = new_game(CardClass.PALADIN)
    guardian = play_card(own, "CS2_088")
    same("Battlecry does not overheal a full-health hero", own.hero.health, 30)
    same("minion still enters play at full hero health", guardian.zone, Zone.PLAY)
    return {"hero_health": own.hero.health, "guardian_zone": guardian.zone.name}


def holy_light_friendly_hero():
    _, own, opponent = new_game(CardClass.PALADIN)
    set_health(own.hero, 24)
    play_card(own, "CS2_089", own.hero, has_target=True)
    same("Holy Light heals friendly hero by 6", own.hero.health, 30)
    same("opponent hero is unchanged", opponent.hero.health, 30)
    return {"own_hero": own.hero.health, "opponent_hero": opponent.hero.health}


def holy_light_enemy_minion_cap():
    _, own, opponent = new_game(CardClass.PALADIN)
    minion = summon(opponent, "CS2_179")
    minion.damage = 2
    own_before = own.hero.health
    play_card(own, "CS2_089", minion, has_target=True)
    same("enemy minion is a valid target and restores up to its maximum", (minion.health, minion.damage), (minion.max_health, 0))
    same("heal does not damage or heal the caster hero", own.hero.health, own_before)
    return {"enemy_minion": {"health": minion.health, "max_health": minion.max_health, "damage": minion.damage}, "own_hero": own.hero.health}


def blessing_kings_damaged_friendly_and_persistent():
    game, own, _ = new_game(CardClass.PALADIN)
    target = summon(own, "CS2_186")
    target.damage = 2
    before = {"atk": target.atk, "max_health": target.max_health, "health": target.health, "damage": target.damage}
    play_card(own, "CS2_092", target, has_target=True)
    during = {"atk": target.atk, "max_health": target.max_health, "health": target.health, "damage": target.damage}
    same("Blessing gives +4/+4 while preserving existing damage", during, {"atk": before["atk"] + 4, "max_health": before["max_health"] + 4, "health": before["health"] + 4, "damage": before["damage"]})
    game.end_turn()
    after = {"atk": target.atk, "max_health": target.max_health, "health": target.health, "damage": target.damage}
    same("+4/+4 buff persists after caster turn", after, during)
    return {"before": before, "during": during, "after_end_turn": after}


def blessing_kings_enemy_minion_and_type_restriction():
    _, own, opponent = new_game(CardClass.PALADIN)
    enemy = summon(opponent, "CS2_182")
    card = own.give("CS2_092")
    expect_invalid_target(own, card, opponent.hero, "Blessing of Kings requires a minion")
    before = (enemy.atk, enemy.max_health, enemy.health)
    card.play(target=enemy)
    same("unqualified 'a minion' permits enemy minion and grants +4/+4", (enemy.atk, enemy.max_health, enemy.health), (before[0] + 4, before[1] + 4, before[2] + 4))
    return {"before": before, "after": (enemy.atk, enemy.max_health, enemy.health), "zone": enemy.zone.name}


def build_cases():
    cases = [
        ("CS2_045", "rockbiter_friendly_minion_temp_expiry", "Reject enemy character without cost; selected friendly minion +3 Attack, other characters unchanged; bonus expires after caster turn.", rockbiter_minion_temp, "friendly-character scope; exact attack delta; invalid enemy target; one-turn expiry"),
        ("CS2_045", "rockbiter_friendly_hero_temp_expiry", "Friendly hero is a legal character target, gains +3 Attack this turn, then returns to original Attack.", rockbiter_hero_temp, "hero target and one-turn expiry"),
        ("CS2_046", "bloodlust_friendly_scope_expiry", "All current friendly minions gain +3 Attack; enemy minion and hero do not; later minion is not retroactively buffed; effects expire at turn end.", bloodlust_existing_scope_expiry, "friendly/enemy scope; current-board resolution; temporary duration"),
        ("CS2_057", "shadow_bolt_friendly_target_exact_damage", "Enemy hero target is rejected without consuming spell; a friendly minion takes exactly 4 and both heroes remain unchanged.", shadow_bolt_friendly_target, "minion-only target; both-side targeting; exact damage"),
        ("CS2_057", "shadow_bolt_enemy_lethal_zone", "An enemy 1-health minion takes lethal 4 damage and moves from field to graveyard; another enemy minion is unchanged.", shadow_bolt_enemy_death, "lethal damage and zone/death processing"),
        ("CS2_061", "drain_life_minion_damage_and_hero_heal", "Target minion takes exactly 2; caster hero heals exactly 2; enemy hero is unchanged.", drain_life_minion_and_heal, "target damage, surviving health, own-hero heal"),
        ("CS2_061", "drain_life_friendly_minion_target", "Friendly minion takes 2 damage; caster hero heals 2; opponent hero is unchanged; spell moves to graveyard.", drain_life_friendly_minion_and_heal, "friendly-target legality, damage/healing and spell zone"),
        ("CS2_061", "drain_life_enemy_hero_and_heal_cap", "Enemy hero target loses 2 each cast; own hero heals 2 and is capped at 30.", drain_life_enemy_hero_and_cap, "hero target; target-side independence; overheal cap"),
        ("CS2_061", "drain_life_lethal_minion_and_heal", "A 1-health minion dies to 2 damage and moves to graveyard; caster hero still heals 2.", drain_life_lethal_minion, "lethal damage, zone/death processing, and post-hit hero heal"),
        ("CS2_062", "hellfire_all_characters_and_deaths", "Both heroes and every friendly/enemy minion take 3; damaged survivors remain, lethal minions move to graveyard.", hellfire_all_characters, "ALL characters, both sides, exact damage, death processing"),
        ("CS2_072", "backstab_undamaged_gate_and_exact_damage", "Damaged minion is rejected without cost/state change; undamaged enemy minion takes exactly 2.", backstab_undamaged_only, "undamaged-only eligibility; target rejection; damage result"),
        ("CS2_072", "backstab_friendly_minion_allowed", "Undamaged friendly minion is also targetable and takes exactly 2 damage.", backstab_friendly_minion_allowed, "minion-only restriction without side restriction"),
        ("CS2_075", "sinister_strike_enemy_hero_only", "Without a target choice, enemy hero takes exactly 3; friendly hero and both minions are unchanged.", sinister_strike_enemy_hero_only, "fixed enemy-hero target and unaffected board"),
        ("CS2_076", "assassinate_enemy_destroy_and_target_rules", "Friendly minion and hero targets are rejected; enemy minion is destroyed despite Divine Shield; other characters remain unchanged.", assassinate_destroy_and_target_rules, "enemy/minion restrictions; destroy versus shield; graveyard zone"),
        ("CS2_077", "sprint_exact_four_known_top_cards", "Exactly the four known top cards enter hand in order; lower two remain in deck.", sprint_four_known_cards, "draw count, identity/order, remaining deck"),
        ("CS2_077", "sprint_short_deck_fatigue", "Two available cards are drawn; two failed draws cause fatigue 1+2 damage and deck remains empty.", sprint_short_deck_fatigue, "short-deck branch and fatigue state"),
        ("CS2_077", "sprint_full_hand_overdraw", "After one free slot is available when Sprint leaves hand, one card draws and three overdrawn cards go to graveyard; hand caps at 10.", sprint_overdraw_full_hand, "hand cap, drawn/overdrawn zones, deck depletion"),
        ("CS2_088", "guardian_battlecry_damaged_hero", "Guardian enters as 5/6; Battlecry restores 6 to an injured hero without changing max health.", guardian_injured_hero, "body, battlecry amount, hero/max-health state"),
        ("CS2_088", "guardian_battlecry_full_health_cap", "At full health, Battlecry leaves hero at 30 while Guardian still enters play.", guardian_full_health_cap, "full-health healing cap"),
        ("CS2_089", "holy_light_friendly_hero", "Friendly hero at 24 returns to 30; opponent hero is unchanged.", holy_light_friendly_hero, "friendly hero target and exact heal"),
        ("CS2_089", "holy_light_enemy_minion_cap", "Injured enemy minion is a valid target and heals only to max health; caster hero is unchanged.", holy_light_enemy_minion_cap, "enemy target; minion heal; overheal cap"),
        ("CS2_092", "blessing_damaged_friendly_persistent", "Friendly minion receives +4 Attack/+4 max health/current health while preserving damage; buff remains after caster turn.", blessing_kings_damaged_friendly_and_persistent, "damaged-target health semantics and permanent buff"),
        ("CS2_092", "blessing_enemy_minion_and_minion_gate", "Hero target is rejected without cost; enemy minion is valid and gets +4/+4.", blessing_kings_enemy_minion_and_type_restriction, "minion-only targeting and no friendly-only restriction"),
    ]
    return cases


def main():
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["card_id", "case_id", "expected", "observed", "outcome", "notes"],
        )
        writer.writeheader()
        for card_id, case_id, expected, fn, case_notes in build_cases():
            emit(card_id, case_id, expected, fn, case_notes)
            writer.writerow(ROWS[-1])
            handle.flush()
            row = ROWS[-1]
            print(f"{row['card_id']} {row['case_id']}: {row['outcome']} — {row['observed']}")

    counts = {}
    for row in ROWS:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    print(f"Wrote {OUTPUT}; cases={len(ROWS)}; outcomes={counts}")
    if counts.get("confirmed_error"):
        raise SystemExit(1)
    if counts.get("inconclusive"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
