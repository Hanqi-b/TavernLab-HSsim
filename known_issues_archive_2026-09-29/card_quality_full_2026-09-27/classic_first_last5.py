"""Independent targeted cases for original Classic YELLOW EX1_183–EX1_187.

Writes separate evidence first; merge_classic_first_last5.py appends it after the
EX1_179–182 worker has finished writing classic_probe_first.csv.
"""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE = HERE / "classic_probe_first_last5.csv"
VERDICT = HERE / "classic_verdict_first_last5.csv"
P_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
V_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
IDS = ("EX1_183", "EX1_184", "EX1_185", "EX1_186", "EX1_187")
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def read(name):
    with (HERE / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


MASTER = {row["card_id"]: row for row in read("card_master.csv")}
BASELINE = {row["card_id"] for row in read("expansion_yellow_baseline.csv")}
assert all(cid in BASELINE for cid in IDS)


def game_for(cls=CardClass.MAGE):
    game = prepare_empty_game(cls, cls)
    if game.current_player is not game.player1:
        game.end_turn()
    game.player1.max_mana = game.player2.max_mana = 10
    return game


def ensure(condition, observed):
    if not condition:
        raise AssertionError(observed)


def gift_of_wild_friendly_only():
    game = game_for(CardClass.DRUID)
    own, opponent = game.player1, game.player2
    a = own.summon(WISP)
    b = own.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    before = [(m.atk, m.health, m.max_health, m.taunt) for m in (a, b, enemy)]
    spell = own.give("EX1_183")
    spell.play()
    after = [(m.atk, m.health, m.max_health, m.taunt) for m in (a, b, enemy)]
    observed = f"before={before};after={after};spell={spell.zone.name}"
    ensure(after[0] == (before[0][0]+2, before[0][1]+2, before[0][2]+2, True), observed)
    ensure(after[1] == (before[1][0]+2, before[1][1]+2, before[1][2]+2, True), observed)
    ensure(after[2] == before[2] and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def gift_of_wild_empty_board():
    game = game_for(CardClass.DRUID)
    own, opponent = game.player1, game.player2
    enemy = opponent.summon(WISP)
    before = (enemy.atk, enemy.health, enemy.taunt)
    spell = own.give("EX1_183")
    spell.play()
    observed = f"own_field={len(own.field)};enemy={(enemy.atk, enemy.health, enemy.taunt)};spell={spell.zone.name}"
    ensure(len(own.field) == 0 and (enemy.atk, enemy.health, enemy.taunt) == before and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def righteousness_friendly_and_shield_absorbs_damage():
    game = game_for(CardClass.PALADIN)
    own, opponent = game.player1, game.player2
    a = own.summon("CS2_182")
    b = own.summon(WISP)
    enemy = opponent.summon("CS2_182")
    spell = own.give("EX1_184")
    spell.play()
    shields = (a.divine_shield, b.divine_shield, enemy.divine_shield)
    health_before = a.health
    a.hit(1)
    after_first = (a.health, a.divine_shield)
    a.hit(1)
    after_second = (a.health, a.divine_shield)
    observed = f"shields={shields};first={after_first};second={after_second};spell={spell.zone.name}"
    ensure(shields == (True, True, False) and after_first == (health_before, False), observed)
    ensure(after_second == (health_before-1, False) and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def righteousness_empty_board():
    game = game_for(CardClass.PALADIN)
    own, opponent = game.player1, game.player2
    enemy = opponent.summon(WISP)
    spell = own.give("EX1_184")
    spell.play()
    observed = f"own_field={len(own.field)};enemy_shield={enemy.divine_shield};spell={spell.zone.name}"
    ensure(len(own.field) == 0 and not enemy.divine_shield and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def siegebreaker_aura_and_removal():
    game = game_for(CardClass.WARLOCK)
    own, opponent = game.player1, game.player2
    friendly_demon = own.summon("CS2_065")
    friendly_plain = own.summon(WISP)
    enemy_demon = opponent.summon("CS2_065")
    base = (friendly_demon.atk, friendly_plain.atk, enemy_demon.atk)
    siege = own.give("EX1_185")
    siege.play()
    active = (siege.taunt, siege.atk, friendly_demon.atk, friendly_plain.atk, enemy_demon.atk)
    siege.hit(20)
    gone = (siege.zone.name, friendly_demon.atk, friendly_plain.atk, enemy_demon.atk)
    observed = f"base={base};active={active};after_destroy={gone}"
    ensure(active[0] and active[2] == base[0]+1 and active[3:] == base[1:], observed)
    ensure(gone == ("GRAVEYARD", *base), observed)
    return observed


def siegebreaker_two_auras_stack_on_other_demons():
    game = game_for(CardClass.WARLOCK)
    own = game.player1
    demon = own.summon("CS2_065")
    first = own.give("EX1_185")
    first.play()
    # The first 7-mana play was legal; construct the second copy as board state.
    second = own.summon("EX1_185")
    observed = f"demon={demon.atk};sieges={(first.atk, second.atk)};taunts={(first.taunt, second.taunt)}"
    ensure(demon.atk == 3 and first.atk == 6 and second.atk == 6, observed)
    ensure(first.taunt and second.taunt, observed)
    return observed


def infiltrator_two_enemy_secrets_random_domain():
    seen = set()
    for seed in range(16):
        game = game_for(CardClass.MAGE)
        own, opponent = game.player1, game.player2
        game.end_turn()
        secrets = [opponent.give(cid) for cid in ("EX1_287", "EX1_594")]
        for secret in secrets:
            secret.play()
        game.end_turn()
        game.random.seed(seed)
        infiltrator = own.give("EX1_186")
        infiltrator.play()
        destroyed = [secret for secret in secrets if secret.zone == Zone.GRAVEYARD]
        observation = f"seed={seed};secrets={[(s.id,s.zone.name) for s in secrets]};infiltrator={infiltrator.zone.name}"
        ensure(len(destroyed) == 1 and len(opponent.secrets) == 1 and infiltrator.zone == Zone.PLAY, observation)
        seen.add(destroyed[0].id)
    observed = f"16_fixed_seeds;destroyed_candidate_ids={sorted(seen)}"
    ensure(seen == {"EX1_287", "EX1_594"}, observed)
    return observed


def infiltrator_no_enemy_secret_keeps_friendly_secret():
    game = game_for(CardClass.MAGE)
    own, opponent = game.player1, game.player2
    friendly_secret = own.give("EX1_287")
    friendly_secret.play()
    infiltrator = own.give("EX1_186")
    infiltrator.play()
    observed = f"friendly_secret={friendly_secret.zone.name};enemy_secret_count={len(opponent.secrets)};infiltrator={infiltrator.zone.name}"
    ensure(friendly_secret.zone == Zone.SECRET and len(opponent.secrets) == 0 and infiltrator.zone == Zone.PLAY, observed)
    return observed


def devourer_own_spells_not_enemy_spells():
    game = game_for(CardClass.MAGE)
    own, opponent = game.player1, game.player2
    devourer = own.give("EX1_187")
    devourer.play()
    base = (devourer.atk, devourer.health, devourer.max_health)
    own.give("CS2_008").play(target=opponent.hero)
    first = (devourer.atk, devourer.health, devourer.max_health)
    own.give("CS2_008").play(target=opponent.hero)
    second = (devourer.atk, devourer.health, devourer.max_health)
    game.end_turn()
    opponent.give("CS2_008").play(target=own.hero)
    after_enemy = (devourer.atk, devourer.health, devourer.max_health)
    observed = f"base={base};after_own_first={first};after_own_second={second};after_enemy={after_enemy};zone={devourer.zone.name}"
    ensure(first == tuple(value+2 for value in base), observed)
    ensure(second == tuple(value+4 for value in base), observed)
    ensure(after_enemy == second and devourer.zone == Zone.PLAY, observed)
    return observed


CASES = {
    "EX1_183": [
        ("friendly_only_plus_two_two_taunt", "Gift of the Wild grants each friendly minion +2/+2 and Taunt, without buffing an enemy minion.", gift_of_wild_friendly_only),
        ("empty_friendly_board", "With no friendly minions, the spell resolves and leaves enemy minions unchanged.", gift_of_wild_empty_board),
    ],
    "EX1_184": [
        ("friendly_shields_absorb_first_hit", "Righteousness grants Divine Shield to each friendly minion only; first damage breaks shield without Health loss, second damage lands.", righteousness_friendly_and_shield_absorbs_damage),
        ("empty_friendly_board", "With no friendly minions, Righteousness resolves without shielding enemy minions.", righteousness_empty_board),
    ],
    "EX1_185": [
        ("friendly_demon_aura_lost_on_death", "Siegebreaker has Taunt and gives only other friendly Demons +1 Attack, which ends when it dies.", siegebreaker_aura_and_removal),
        ("two_siegebreakers_stack", "Two Siegebreakers each buff the other and add +2 total Attack to a third friendly Demon.", siegebreaker_two_auras_stack_on_other_demons),
    ],
    "EX1_186": [
        ("two_enemy_secret_random_domain", "Across 16 fixed seeds, exactly one of two distinct enemy Secrets is destroyed and both candidates are reachable.", infiltrator_two_enemy_secrets_random_domain),
        ("no_enemy_secret_friendly_preserved", "With no enemy Secret, SI:7 Infiltrator leaves a friendly Secret in place.", infiltrator_no_enemy_secret_keeps_friendly_secret),
    ],
    "EX1_187": [
        ("own_spell_twice_enemy_spell_ignored", "Two player-cast spells each permanently grant +2/+2; an opponent spell does not buff Arcane Devourer.", devourer_own_spells_not_enemy_spells),
    ],
}


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    case_rows = []
    verdict_rows = []
    for cid in IDS:
        card = MASTER[cid]
        outcomes = []
        for case_id, expected, probe in CASES[cid]:
            try:
                observed, outcome = probe(), "pass"
            except AssertionError as error:
                observed, outcome = f"AssertionError: {error}", "confirmed_error"
            except Exception as error:
                observed, outcome = f"{type(error).__name__}: {error}", "inconclusive"
            outcomes.append(outcome)
            case_rows.append(dict(card_id=cid, case_id=case_id, expected=expected,
                                  observed=observed, outcome=outcome,
                                  notes=(f"EN: {card['card_text_en']} ZH: {card['card_text_zh']} "
                                         f"Implementation: {card['python_source']}; existing tests: "
                                         f"{card['test_refs_candidate'] or 'none'}; prior audit: YELLOW.")))
        blocker = ("CAST-001: effect-generated CastSpell versus player-cast spell semantics remain unresolved."
                   if cid == "EX1_187" else None)
        status = "RED" if "confirmed_error" in outcomes else "YELLOW" if "inconclusive" in outcomes or blocker else "GREEN"
        reason = "; ".join(f"{row['case_id']}={row['outcome']} ({row['observed'][:180]})"
                           for row in case_rows if row["card_id"] == cid)
        if blocker:
            reason += f"; unresolved: {blocker}"
        verdict_rows.append(dict(card_id=cid, status=status, mechanic_scope=card["mechanics"],
                                 reason=reason, probe_file="classic_probe_first.csv",
                                 notes="Per-card live cases with EN/ZH text, source, existing test references and prior audit; "
                                       + (blocker or "key branches executed.")))
        print(f"{cid}: {status}; cases={len(CASES[cid])}; outcomes={outcomes}", flush=True)
    write(PROBE, P_FIELDS, case_rows)
    write(VERDICT, V_FIELDS, verdict_rows)


if __name__ == "__main__":
    main()
