#!/usr/bin/env python3
"""Focused behavior probes for seven remaining Basic YELLOW cards.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_k.py
"""

import csv
import json
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path

from hearthstone.enums import CardClass, Race, Zone

from fireplace.exceptions import InvalidAction
from tests.utils import prepare_empty_game


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "basic_card_probe_k.csv"
CARDS_XML = ROOT / "fireplace/cards/CardDefs.xml"
AUDIT_CSV = HERE / "basic_quality.csv"

SOURCE = {
    "EX1_506": "fireplace/cards/classic/neutral_common.py:316-319",
    "EX1_508": "fireplace/cards/classic/neutral_common.py:78-84",
    "EX1_539": "fireplace/cards/classic/hunter.py:123-128",
    "EX1_587": "fireplace/cards/classic/shaman.py:39-48",
    "EX1_622": "fireplace/cards/classic/priest.py:262-270",
    "NEW1_003": "fireplace/cards/classic/warlock.py:215-223",
    "NEW1_031": "fireplace/cards/classic/hunter.py:162-168",
}

EXISTING_TESTS = {
    "EX1_506": "tests/test_classic.py::test_murloc_tidecaller checks a Tidecaller attack increase after Tidehunter is played; tests/test_secrets.py::test_snipe checks the pre-battlecry death case. Neither directly asserts the Scout token stats/race/zone.",
    "EX1_508": "tests/test_classic.py::test_grimscale_oracle already asserts friendly Murloc +1, enemy Murloc/self unaffected, and buff removal after bounce; no later-summon or silence test.",
    "EX1_539": "tests/test_classic.py::test_kill_command already asserts 3 damage without a controlled Beast and 5 with a friendly Beast; tests/test_mechanics.py::test_powered_up checks the flag when a Beast is summoned.",
    "EX1_587": "No card-specific behavior assertion found in tests/; prior evidence was generic-play smoke only.",
    "EX1_622": "tests/test_ungoro.py::test_sherazin_corpse_flower uses Shadow Word: Death to destroy Sherazin but does not test the 5-Attack boundary.",
    "NEW1_003": "tests/test_naxxramas.py::test_voidcaller asserts the friendly Demon dies and its Deathrattle summons Doomguard; it does not assert the hero heal or target rules.",
    "NEW1_031": "tests/test_classic.py::test_animal_companion only asserts exactly one of the three companion IDs; it does not assert stats/keywords. test_starving_buzzard only uses its summon interaction.",
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


def expect_unplayable(player, card, label):
    mana_before = player.mana
    try:
        card.play()
    except InvalidAction:
        pass
    except Exception as exc:
        raise ProbeMismatch(
            label, "InvalidAction before resolution", f"{type(exc).__name__}: {exc}"
        ) from exc
    else:
        raise ProbeMismatch(label, "InvalidAction", "card was playable")
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


def tidehunter_battlecry_token():
    _, own, opponent = new_game(CardClass.SHAMAN)
    enemy = summon(opponent, "CS2_168")
    enemy_before = (enemy.atk, enemy.health)
    tidehunter = play_card(own, "EX1_506")
    same("Tidehunter itself enters as printed 2/1 Murloc", (tidehunter.zone, tidehunter.atk, tidehunter.health, tidehunter.race), (Zone.PLAY, 2, 1, Race.MURLOC))
    same("battlecry adds exactly one Scout to friendly field", len(own.field), 2)
    scout = next((m for m in own.field if m.id == "EX1_506a"), None)
    if scout is None:
        raise ProbeMismatch("Murloc Scout token exists", "one EX1_506a on friendly field", [m.id for m in own.field])
    same("Scout token enters as 1/1 Murloc", (scout.zone, scout.atk, scout.health, scout.race), (Zone.PLAY, 1, 1, Race.MURLOC))
    same("opponent board does not receive a token or stat change", ([m.id for m in opponent.field], (enemy.atk, enemy.health)), ([enemy.id], enemy_before))
    return {"friendly_field": [{"id": m.id, "atk": m.atk, "health": m.health, "race": Race(int(m.race)).name} for m in own.field], "enemy": {"id": enemy.id, "atk": enemy.atk, "health": enemy.health}}


def tidehunter_seventh_slot_no_token():
    _, own, opponent = new_game(CardClass.SHAMAN)
    existing = [summon(own, "CS2_231") for _ in range(6)]
    enemy = summon(opponent, "CS2_168")
    own_before = [m.id for m in own.field]
    enemy_before = [m.id for m in opponent.field]
    tidehunter = play_card(own, "EX1_506")
    same("Tidehunter itself occupies the seventh and final slot", (len(own.field), tidehunter in own.field, tidehunter.zone), (7, True, Zone.PLAY))
    same("no Scout is summoned when the board has no slot left", [m.id for m in own.field].count("EX1_506a"), 0)
    same("six earlier minions remain in play and in order", [m.id for m in own.field[:6]], own_before)
    same("enemy board is unchanged", [m.id for m in opponent.field], enemy_before)
    same("enemy Murloc remains in play", enemy.zone, Zone.PLAY)
    return {"friendly_field_count": len(own.field), "friendly_field_ids": [m.id for m in own.field], "tidehunter_zone": tidehunter.zone.name, "enemy_field_ids": [m.id for m in opponent.field], "existing_minions_in_play": all(m.zone == Zone.PLAY for m in existing)}


def grimscale_aura_scope_addition_and_silence():
    _, own, opponent = new_game(CardClass.SHAMAN)
    murloc_before = summon(own, "CS2_168")
    non_murloc = summon(own, "CS2_231")
    enemy_murloc = summon(opponent, "CS2_168")
    oracle = own.summon("EX1_508")
    same("Oracle buffs only other friendly Murlocs by +1", (murloc_before.atk, non_murloc.atk, enemy_murloc.atk, oracle.atk), (3, 1, 2, 1))
    murloc_after = summon(own, "EX1_506a")
    same("Murloc summoned after aura source receives +1 immediately", murloc_after.atk, 2)
    same("enemy Murloc remains outside friendly aura", enemy_murloc.atk, 2)
    own.give("EX1_332").play(target=oracle)
    same("silenced Oracle stays on board but loses its aura", (oracle.zone, oracle.silenced, murloc_before.atk, murloc_after.atk), (Zone.PLAY, True, 2, 1))
    same("enemy Murloc and non-Murloc stay unchanged", (enemy_murloc.atk, non_murloc.atk), (2, 1))
    return {"oracle": {"zone": oracle.zone.name, "silenced": oracle.silenced}, "friendly_murloc_attacks_after_silence": [murloc_before.atk, murloc_after.atk], "enemy_murloc_attack": enemy_murloc.atk, "friendly_non_murloc_attack": non_murloc.atk}


def kill_command_no_beast_enemy_beast():
    _, own, opponent = new_game(CardClass.HUNTER)
    enemy_beast = summon(opponent, "CS2_125")
    target = summon(opponent, "CS2_186")
    before = target.health
    card = own.give("EX1_539")
    same("opposing Beast does not power up Kill Command", card.powered_up, False)
    card.play(target=target)
    same("without friendly Beast the target takes exactly 3", (target.damage, target.health), (3, before - 3))
    same("opponent Beast remains undamaged", enemy_beast.damage, 0)
    return {"powered_up": card.powered_up, "target": {"damage": target.damage, "health": target.health}, "enemy_beast": {"id": enemy_beast.id, "damage": enemy_beast.damage}}


def kill_command_friendly_beast_and_loss():
    _, own, opponent = new_game(CardClass.HUNTER)
    beast = summon(own, "CS2_125")
    target = opponent.hero
    before = target.health
    powered = own.give("EX1_539")
    same("controlled Beast enables powered-up state", powered.powered_up, True)
    powered_status = powered.powered_up
    powered.play(target=target)
    same("controlled Beast changes damage from 3 to 5", target.health, before - 5)
    beast.destroy()
    same("destroyed Beast leaves friendly field", beast.zone, Zone.GRAVEYARD)
    next_card = own.give("EX1_539")
    same("no longer controlling a Beast disables powered-up state", next_card.powered_up, False)
    before_second = target.health
    next_card.play(target=target)
    same("after Beast leaves play next Kill Command deals 3", target.health, before_second - 3)
    return {"first_powered_up_before_play": powered_status, "enemy_hero_after_5": before - 5, "beast_zone": beast.zone.name, "second_powered_up_before_play": next_card.powered_up, "enemy_hero_final": target.health}


def kill_command_friendly_minion_target_three():
    _, own, opponent = new_game(CardClass.HUNTER)
    friendly = summon(own, "CS2_186")
    own_hero_before = own.hero.health
    enemy_hero_before = opponent.hero.health
    card = own.give("EX1_539")
    same("friendly target is legal when no friendly Beast is controlled", card.powered_up, False)
    card.play(target=friendly)
    same("friendly minion receives exactly 3 and survives", (friendly.damage, friendly.health, friendly.zone), (3, 4, Zone.PLAY))
    same("other characters remain unchanged and spell moves to graveyard", (own.hero.health, opponent.hero.health, card.zone), (own_hero_before, enemy_hero_before, Zone.GRAVEYARD))
    return {"friendly_target": {"damage": friendly.damage, "health": friendly.health, "zone": friendly.zone.name}, "own_hero": own.hero.health, "enemy_hero": opponent.hero.health, "spell_zone": card.zone.name}


def kill_command_friendly_hero_target_five():
    _, own, opponent = new_game(CardClass.HUNTER)
    beast = summon(own, "CS2_125")
    own_hero_before = own.hero.health
    enemy_hero_before = opponent.hero.health
    card = own.give("EX1_539")
    same("friendly Beast enables powered-up state for friendly hero target", card.powered_up, True)
    card.play(target=own.hero)
    same("friendly hero target takes exactly 5", (own.hero.damage, own.hero.health), (5, own_hero_before - 5))
    same("controlled Beast, opponent hero, and spell zone are correct", (beast.zone, beast.damage, opponent.hero.health, card.zone), (Zone.PLAY, 0, enemy_hero_before, Zone.GRAVEYARD))
    return {"own_hero": {"damage": own.hero.damage, "health": own.hero.health}, "beast": {"zone": beast.zone.name, "damage": beast.damage}, "enemy_hero": opponent.hero.health, "spell_zone": card.zone.name}


def windspeaker_windfury_two_attacks():
    _, own, opponent = new_game(CardClass.SHAMAN)
    boar = summon(own, "CS2_171")
    enemy_minion = summon(opponent, "CS2_186")
    before_enemy_hero = opponent.hero.health
    card = own.give("EX1_587")
    expect_invalid_target(own, card, enemy_minion, "Windspeaker can target friendly minion only")
    card.play(target=boar)
    same("Battlecry grants Windfury without changing minion attack", (boar.windfury, boar.atk, boar.max_attacks, card.zone), (True, 1, 2, Zone.PLAY))
    same("Windspeaker body enters as 3/3", (own.field.contains("EX1_587"), next(m for m in own.field if m.id == "EX1_587").atk, next(m for m in own.field if m.id == "EX1_587").health), (True, 3, 3))
    same("Charge minion can attack immediately", boar.can_attack(), True)
    boar.attack(opponent.hero)
    same("first attack deals 1 and records one attack", (opponent.hero.health, boar.num_attacks), (before_enemy_hero - 1, 1))
    boar.attack(opponent.hero)
    same("second Windfury attack also deals 1", (opponent.hero.health, boar.num_attacks, boar.exhausted), (before_enemy_hero - 2, 2, True))
    try:
        boar.attack(opponent.hero)
    except InvalidAction:
        pass
    else:
        raise ProbeMismatch("third attack is unavailable with Windfury", "InvalidAction after two attacks", "third attack accepted")
    same("third attack causes no additional damage", opponent.hero.health, before_enemy_hero - 2)
    return {"windfury": boar.windfury, "boar_atk": boar.atk, "num_attacks": boar.num_attacks, "enemy_hero": opponent.hero.health, "windspeaker": {"atk": next(m for m in own.field if m.id == "EX1_587").atk, "health": next(m for m in own.field if m.id == "EX1_587").health}}


def shadow_word_death_threshold_and_friend_target():
    _, own, opponent = new_game(CardClass.PRIEST)
    below = summon(opponent, "CS2_182")
    exactly = summon(own, "CS2_186")
    exactly.atk = 5
    higher = summon(opponent, "CS2_186")
    card = own.give("EX1_622")
    expect_invalid_target(own, card, below, "4-Attack minion is below the threshold")
    card.play(target=exactly)
    same("exactly 5 Attack is included and friendly minion is valid", exactly.zone, Zone.GRAVEYARD)
    same("below-threshold enemy minion remains", below.zone, Zone.PLAY)
    second = play_card(own, "EX1_622", higher, has_target=True)
    same("minion above 5 Attack is also destroyed", higher.zone, Zone.GRAVEYARD)
    same("both spells resolve from graveyard after use", (card.zone, second.zone), (Zone.GRAVEYARD, Zone.GRAVEYARD))
    return {"below_attack": below.atk, "below_zone": below.zone.name, "exactly_attack": exactly.atk, "exactly_zone": exactly.zone.name, "higher_attack": higher.atk, "higher_zone": higher.zone.name}


def sacrificial_pact_friendly_demon_rules_and_heal():
    _, own, opponent = new_game(CardClass.WARLOCK)
    demon = summon(own, "CS2_065")
    enemy_demon = summon(opponent, "EX1_319")
    friendly_non_demon = summon(own, "CS2_231")
    own.hero.damage = own.hero.max_health - 18
    card = own.give("NEW1_003")
    expect_invalid_target(own, card, enemy_demon, "enemy Demon is not a friendly Demon target")
    expect_invalid_target(own, card, friendly_non_demon, "friendly non-Demon is not a Demon target")
    card.play(target=demon)
    same("friendly Demon is destroyed and leaves play", (demon.zone, demon in own.field), (Zone.GRAVEYARD, False))
    same("hero restores exactly 5", own.hero.health, 23)
    same("enemy Demon and friendly non-Demon stay unchanged", (enemy_demon.zone, friendly_non_demon.zone), (Zone.PLAY, Zone.PLAY))
    return {"friendly_demon_zone": demon.zone.name, "hero_health": own.hero.health, "enemy_demon_zone": enemy_demon.zone.name, "friendly_non_demon_zone": friendly_non_demon.zone.name}


def sacrificial_pact_full_health_cap():
    _, own, _ = new_game(CardClass.WARLOCK)
    demon = summon(own, "CS2_065")
    play_card(own, "NEW1_003", demon, has_target=True)
    same("friendly Demon is still destroyed at full hero health", demon.zone, Zone.GRAVEYARD)
    same("5 healing cannot exceed maximum health", own.hero.health, 30)
    return {"demon_zone": demon.zone.name, "hero_health": own.hero.health}


def companion_game(seed):
    game, own, opponent = new_game(CardClass.HUNTER)
    game.random.seed(seed)
    return game, own, opponent


def animal_companion_leokk_aura():
    _, own, opponent = companion_game(0)
    friend = summon(own, "CS2_182")
    enemy = summon(opponent, "CS2_182")
    before = (friend.atk, enemy.atk)
    play_card(own, "NEW1_031")
    leokk = own.field[-1]
    same("seed 0 resolves one permitted companion, Leokk", (leokk.id, leokk.atk, leokk.health, leokk.race), ("NEW1_033", 2, 4, Race.BEAST))
    same("Leokk aura gives other friendly minion +1 Attack, not itself or enemy", (friend.atk, enemy.atk, leokk.atk), (before[0] + 1, before[1], 2))
    leokk.destroy()
    same("Leokk aura expires when companion leaves play", friend.atk, before[0])
    return {"companion": {"id": leokk.id, "atk": leokk.atk, "health": leokk.health, "race": Race(int(leokk.race)).name, "zone": leokk.zone.name}, "friend_attack_before_after": [before[0], friend.atk], "enemy_attack": enemy.atk}


def animal_companion_misha_taunt():
    _, own, _ = companion_game(1)
    before = len(own.field)
    play_card(own, "NEW1_031")
    misha = own.field[-1]
    same("seed 1 resolves Misha as 4/4 Beast with Taunt", (misha.id, misha.atk, misha.health, misha.race, misha.taunt, misha.zone), ("NEW1_032", 4, 4, Race.BEAST, True, Zone.PLAY))
    same("Animal Companion adds exactly one minion", len(own.field), before + 1)
    return {"companion": {"id": misha.id, "atk": misha.atk, "health": misha.health, "race": Race(int(misha.race)).name, "taunt": misha.taunt, "zone": misha.zone.name}}


def animal_companion_misha_blocks_and_takes_attack():
    game, own, opponent = companion_game(1)
    attacker = summon(opponent, "CS2_182")
    game.random.seed(1)
    play_card(own, "NEW1_031")
    misha = own.field[-1]
    same("taunt companion is the seeded Misha", (misha.id, misha.taunt, misha.health), ("NEW1_032", True, 4))
    game.end_turn()
    same("opponent's ready minion can attack now", attacker.can_attack(), True)
    same("Misha blocks attack to friendly hero and is a legal attack target", (attacker.can_attack(own.hero), attacker.can_attack(misha)), (False, True))
    hero_before = own.hero.health
    try:
        attacker.attack(own.hero)
    except InvalidAction:
        pass
    else:
        raise ProbeMismatch("Misha Taunt blocks enemy hero attack", "InvalidAction", "hero attack accepted")
    same("blocked hero attack does not consume attacker or damage hero", (attacker.num_attacks, own.hero.health), (0, hero_before))
    attacker.attack(misha)
    same("enemy minion can attack Misha; combat removes Misha and damages attacker", (misha.zone, attacker.damage, attacker.health, own.hero.health), (Zone.GRAVEYARD, 4, 1, hero_before))
    return {"misha_zone": misha.zone.name, "attacker": {"num_attacks": attacker.num_attacks, "damage": attacker.damage, "health": attacker.health}, "own_hero": own.hero.health}


def animal_companion_huffer_charge_attack():
    _, own, opponent = companion_game(3)
    before = opponent.hero.health
    play_card(own, "NEW1_031")
    huffer = own.field[-1]
    same("seed 3 resolves Huffer as 4/2 Beast with Charge", (huffer.id, huffer.atk, huffer.health, huffer.race, huffer.charge, huffer.zone), ("NEW1_034", 4, 2, Race.BEAST, True, Zone.PLAY))
    same("Huffer can attack immediately", huffer.can_attack(), True)
    huffer.attack(opponent.hero)
    same("Huffer's immediate attack deals 4", (opponent.hero.health, huffer.num_attacks), (before - 4, 1))
    return {"companion": {"id": huffer.id, "atk": huffer.atk, "health": huffer.health, "race": Race(int(huffer.race)).name, "charge": huffer.charge}, "enemy_hero": opponent.hero.health, "attacks": huffer.num_attacks}


def animal_companion_full_board_unplayable():
    _, own, _ = new_game(CardClass.HUNTER)
    existing = [summon(own, "CS2_231") for _ in range(7)]
    before_ids = [m.id for m in own.field]
    card = own.give("NEW1_031")
    expect_unplayable(own, card, "Animal Companion requires a free minion slot")
    same("full field remains exactly seven existing minions", (len(own.field), [m.id for m in own.field]), (7, before_ids))
    same("no companion token is summoned", [m for m in own.field if m.id in ("NEW1_032", "NEW1_033", "NEW1_034")], [])
    same("all original minions stay in play", all(m.zone == Zone.PLAY for m in existing), True)
    return {"field_count": len(own.field), "field_ids": [m.id for m in own.field], "spell_zone": card.zone.name, "mana": own.mana}


def build_cases():
    return [
        ("EX1_506", "tidehunter_token_body_race_zone", "Tidehunter enters as 2/1 Murloc; Battlecry summons exactly one friendly 1/1 Murloc Scout; enemy board unchanged.", tidehunter_battlecry_token, "Battlecry token identity/stats/race/zone plus Tidehunter body"),
        ("EX1_506", "tidehunter_seventh_slot_no_token", "With six friendly minions, Tidehunter occupies slot seven; the Scout Battlecry cannot exceed the seven-minion field cap.", tidehunter_seventh_slot_no_token, "board-slot edge after the source minion consumes the final slot"),
        ("EX1_508", "grimscale_friendly_other_murlocs_aura_and_silence", "Other friendly Murlocs gain +1 attack, including a later summon; self, non-Murloc, enemy Murloc do not; silence removes aura.", grimscale_aura_scope_addition_and_silence, "friendly tribe filter, self exclusion, dynamic addition, aura cleanup"),
        ("EX1_539", "kill_command_no_friendly_beast", "Enemy-controlled Beast alone does not power up; a legal target takes exactly 3.", kill_command_no_beast_enemy_beast, "condition checks controller ownership"),
        ("EX1_539", "kill_command_friendly_beast_and_departure", "Friendly Beast raises damage to 5; after it dies, next cast returns to 3.", kill_command_friendly_beast_and_loss, "both sides of conditional and state change when Beast leaves"),
        ("EX1_539", "kill_command_friendly_minion_target_three", "Without a friendly Beast, a friendly minion target takes 3; other characters are unchanged and the spell enters graveyard.", kill_command_friendly_minion_target_three, "friendly target domain with base damage and resulting card/character states"),
        ("EX1_539", "kill_command_friendly_hero_target_five", "With a friendly Beast, friendly hero target takes 5; Beast/opponent hero remain unchanged and the spell enters graveyard.", kill_command_friendly_hero_target_five, "friendly character target domain with powered-up damage"),
        ("EX1_587", "windspeaker_grants_two_attacks", "Enemy minion is rejected without resource loss; friendly Charge minion gets Windfury, can attack twice now, third attack is rejected; Windspeaker body is 3/3.", windspeaker_windfury_two_attacks, "friendly target, keyword, actual attack count, no stat change"),
        ("EX1_622", "shadow_word_death_five_attack_boundary", "4-Attack target is rejected without cost; friendly 5-Attack and enemy higher-Attack minions are destroyed.", shadow_word_death_threshold_and_friend_target, "exact attack threshold, above threshold, no side restriction, zone changes"),
        ("NEW1_003", "sacrificial_pact_friendly_demon_heal_and_target_rules", "Enemy Demon and friendly non-Demon are rejected; friendly Demon is destroyed; hero restores 5; other minions remain.", sacrificial_pact_friendly_demon_rules_and_heal, "friendly/race restrictions, destroy and heal"),
        ("NEW1_003", "sacrificial_pact_full_health_cap", "Friendly Demon is destroyed; full-health hero remains capped at 30.", sacrificial_pact_full_health_cap, "full-health healing cap"),
        ("NEW1_031", "animal_companion_leokk_variant", "Fixed RNG seed 0 summons only Leokk (2/4 Beast); its aura buffs other friendly minion +1, not self or enemy, and leaves when Leokk leaves.", animal_companion_leokk_aura, "random outcome membership/stats and Leokk aura behavior"),
        ("NEW1_031", "animal_companion_misha_variant", "Fixed RNG seed 1 summons exactly one Misha (4/4 Beast with Taunt).", animal_companion_misha_taunt, "random outcome membership/stats/keyword/zone"),
        ("NEW1_031", "animal_companion_misha_taunt_attack_legality", "On opponent turn, ready attacker cannot attack hero while Misha is present but can attack Misha; combat resolves against Misha.", animal_companion_misha_blocks_and_takes_attack, "Taunt behavior verified through target legality and actual combat"),
        ("NEW1_031", "animal_companion_huffer_variant", "Fixed RNG seed 3 summons Huffer (4/2 Beast with Charge), which can immediately attack for 4.", animal_companion_huffer_charge_attack, "random outcome membership/stats/keyword and in-game Charge result"),
        ("NEW1_031", "animal_companion_full_board_unplayable", "At seven minions, Animal Companion is unplayable; attempt is rejected with hand, mana, and board unchanged.", animal_companion_full_board_unplayable, "REQ_NUM_MINION_SLOTS prerequisite and no-side-effect rejection"),
    ]


def main():
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["card_id", "case_id", "expected", "observed", "outcome", "notes"],
        )
        writer.writeheader()
        for card_id, case_id, expected, fn, case_notes in build_cases():
            try:
                observed = fn()
            except ProbeMismatch as exc:
                row = {
                    "card_id": card_id,
                    "case_id": case_id,
                    "expected": expected,
                    "observed": f"{exc.observed!r}; assertion={exc}",
                    "outcome": "confirmed_error",
                    "notes": notes(card_id, case_notes),
                }
            except Exception as exc:
                row = {
                    "card_id": card_id,
                    "case_id": case_id,
                    "expected": expected,
                    "observed": f"{type(exc).__name__}: {exc}; {traceback.format_exc(limit=2).strip()}",
                    "outcome": "inconclusive",
                    "notes": notes(card_id, case_notes),
                }
            else:
                row = {
                    "card_id": card_id,
                    "case_id": case_id,
                    "expected": expected,
                    "observed": observed if isinstance(observed, str) else json.dumps(observed, ensure_ascii=False, sort_keys=True),
                    "outcome": "pass",
                    "notes": notes(card_id, case_notes),
                }
            ROWS.append(row)
            writer.writerow(row)
            handle.flush()
            print(f"{card_id} {case_id}: {row['outcome']} — {row['observed']}")

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
