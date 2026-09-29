"""Per-card runtime probes for Classic YELLOW collectible cards, second half.

Run from the repository root with:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_second.py
"""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, GameTag, Race, Zone
from utils import WISP, prepare_empty_game


ROOT = Path(__file__).parent
QUALITY = ROOT / "card_quality.csv"
MASTER = ROOT / "card_master.csv"
BASELINE = ROOT / "expansion_yellow_baseline.csv"
PROBE_OUT = ROOT / "classic_probe_second.csv"
VERDICT_OUT = ROOT / "classic_verdict_second.csv"
PROBE_FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
VERDICT_FIELDS = ["card_id", "status", "mechanic_scope", "reason", "probe_file", "notes"]

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)


class ProbeMismatch(Exception):
    """A card behavior contradicted its printed effect."""


def ensure(condition, observed):
    if not condition:
        raise ProbeMismatch(observed)


def classic_yellow_second_half():
    with BASELINE.open(encoding="utf-8-sig", newline="") as stream:
        baseline = [row for row in csv.DictReader(stream)
                    if row["set"] == "Classic (EXPERT1)" and row["status"] == "YELLOW"]
    with MASTER.open(encoding="utf-8-sig", newline="") as stream:
        master = {row["card_id"]: row for row in csv.DictReader(stream)}
    if len(baseline) != 229:
        raise RuntimeError(f"Classic baseline YELLOW count changed: {len(baseline)}")
    selected = []
    for base in baseline:
        row = dict(master[base["card_id"]])
        row["mechanic"] = row["mechanics"]
        row["set"] = base["set"]
        row["status"] = base["status"]
        selected.append(row)
    selected.sort(key=lambda row: row["card_id"])
    # Other workers own original sorted indices 179–228.
    return selected[len(selected) // 2:179]


def localized_text(card_id):
    with MASTER.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["card_id"] == card_id:
                return row["card_text_en"], row["card_text_zh"]
    return "", ""


def new_game(card_class):
    game = prepare_empty_game(card_class, card_class)
    if game.current_player is not game.player1:
        game.end_turn()
    return game


def case(case_id, expected, probe):
    return {"case_id": case_id, "expected": expected, "probe": probe}


def pit_lord_hero_damage():
    game = new_game(CardClass.WARLOCK)
    player, opponent = game.player1, game.player2
    before = (player.hero.health, opponent.hero.health, player.mana)
    card = player.give("EX1_313")
    card.play()
    observed = (
        f"own_hero={before[0]}->{player.hero.health};"
        f"enemy_hero={before[1]}->{opponent.hero.health};"
        f"body={card.zone.name}:{card.atk}/{card.health};mana={before[2]}->{player.mana}"
    )
    ensure(player.hero.health == before[0] - 5 and opponent.hero.health == before[1], observed)
    ensure(card.zone == Zone.PLAY and card in player.field and (card.atk, card.health) == (5, 6), observed)
    ensure(player.mana == before[2] - 4, observed)
    return observed


def summoning_portal_cost_aura():
    game = new_game(CardClass.WARLOCK)
    player, opponent = game.player1, game.player2
    friendly_four = player.give("CS2_182")  # Chillwind Yeti, printed cost 4.
    friendly_two = player.give("CS2_142")  # Kobold Geomancer, printed cost 2.
    enemy_four = opponent.give("CS2_182")
    portal = player.give("EX1_315")
    portal.play()
    while_active = (friendly_four.cost, friendly_two.cost, enemy_four.cost)
    silence = player.give("EX1_332")
    silence.play(target=portal)
    after_silence = (friendly_four.cost, friendly_two.cost, enemy_four.cost)
    observed = f"costs_during_aura={while_active};after_silence={after_silence};portal_silenced={portal.silenced}"
    ensure(while_active == (2, 1, 4), observed)
    ensure(after_silence == (4, 2, 4), observed)
    return observed


def sense_demons_two_available():
    game = new_game(CardClass.WARLOCK)
    player = game.player1
    demon_a = player.give("EX1_304")
    demon_b = player.give("EX1_310")
    non_demon = player.give(WISP)
    for card in (demon_a, demon_b, non_demon):
        card.shuffle_into_deck()
    spell = player.give("EX1_317")
    before = len(player.deck)
    spell.play()
    ids = [card.id for card in player.hand]
    observed = f"full_pool_draws={ids};deck={before}->{len(player.deck)};spell={spell.zone.name}"
    ensure(demon_a in player.hand and demon_b in player.hand and non_demon not in player.hand, observed)
    ensure(len(player.deck) == before - 2 and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def sense_demons_one_available():
    game = new_game(CardClass.WARLOCK)
    player = game.player1
    sole_demon = player.give("EX1_304")
    sole_demon.shuffle_into_deck()
    spell = player.give("EX1_317")
    spell.play()
    fillers = [card for card in player.hand if card.id == "EX1_317t"]
    observed = f"one_demon_draw={sole_demon in player.hand};fillers={len(fillers)};deck={len(player.deck)}"
    ensure(sole_demon in player.hand and len(fillers) == 1 and len(player.deck) == 0, observed)
    return observed


def sense_demons_zero_available():
    game = new_game(CardClass.WARLOCK)
    player = game.player1
    non_demon = player.give(WISP)
    non_demon.shuffle_into_deck()
    spell = player.give("EX1_317")
    spell.play()
    fillers = [card for card in player.hand if card.id == "EX1_317t"]
    observed = f"zero_demons_fillers={len(fillers)};non_demon_stays_in_deck={non_demon.zone == Zone.DECK};deck={len(player.deck)}"
    ensure(len(fillers) == 2 and non_demon.zone == Zone.DECK and len(player.deck) == 1, observed)
    return observed


def flame_imp_hero_damage():
    game = new_game(CardClass.WARLOCK)
    player, opponent = game.player1, game.player2
    before = (player.hero.health, opponent.hero.health, player.mana)
    card = player.give("EX1_319")
    card.play()
    observed = f"own_hero={before[0]}->{player.hero.health};enemy_hero={opponent.hero.health};body={card.zone.name}:{card.atk}/{card.health};mana={before[2]}->{player.mana}"
    ensure(player.hero.health == before[0] - 3 and opponent.hero.health == before[1], observed)
    ensure(card.zone == Zone.PLAY and (card.atk, card.health) == (3, 2) and player.mana == before[2] - 1, observed)
    return observed


def bane_of_doom_lethal():
    game = new_game(CardClass.WARLOCK)
    player, opponent = game.player1, game.player2
    target = opponent.summon(WISP)
    spell = player.give("EX1_320")
    spell.play(target=target)
    summoned = list(player.field)
    observed = f"target={target.zone.name};friendly_summon={[(m.id, m.race, m.atk, m.health) for m in summoned]};spell={spell.zone.name}"
    ensure(target.zone == Zone.GRAVEYARD, observed)
    ensure(len(summoned) == 1 and summoned[0].race == Race.DEMON and summoned[0].zone == Zone.PLAY, observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def bane_of_doom_nonlethal():
    game = new_game(CardClass.WARLOCK)
    player, opponent = game.player1, game.player2
    survivor = opponent.summon("CS2_182")
    spell = player.give("EX1_320")
    spell.play(target=survivor)
    nonlethal = f"target={survivor.zone.name}:{survivor.damage}/{survivor.health};friendly_summons={len(player.field)}"
    ensure(survivor.zone == Zone.PLAY and survivor.damage == 2 and len(player.field) == 0, nonlethal)
    return nonlethal


def lord_jaraxxus_transforms_hero():
    game = new_game(CardClass.WARLOCK)
    player = game.player1
    before = player.hero
    minion = player.give("EX1_323")
    minion.play()
    hero = player.hero
    weapon = player.weapon
    observed = (
        f"hero={getattr(before, 'id', '?')}->{getattr(hero, 'id', '?')}:{hero.health}/{hero.max_health};"
        f"power={getattr(player.hero_power, 'id', '?')};"
        f"weapon={getattr(weapon, 'id', None)}:{getattr(weapon, 'atk', None)}/{getattr(weapon, 'durability', None)};"
        f"source_minion={minion.zone.name}"
    )
    ensure(hero.health == 15 and hero.max_health == 15, observed)
    ensure(getattr(hero, "id", None) == "EX1_323h", observed)
    ensure(weapon is not None and weapon.atk == 3 and weapon.durability == 8, observed)
    ensure(getattr(player.hero_power, "id", None) == "EX1_tk33", observed)
    return observed


def shadow_madness_temporary_control_and_charge():
    game = new_game(CardClass.PRIEST)
    player, opponent = game.player1, game.player2
    target = opponent.summon(WISP)
    spell = player.give("EX1_334")
    spell.play(target=target)
    controlled = (target.controller is player and target in player.field and target not in opponent.field)
    can_attack = target.can_attack(opponent.hero)
    before_hero = opponent.hero.health
    if can_attack:
        target.attack(opponent.hero)
    active = f"controlled={controlled};charge={target.charge};can_attack_hero={can_attack};enemy_health={before_hero}->{opponent.hero.health};zone={target.zone.name}"
    ensure(controlled and target.charge and can_attack and opponent.hero.health == before_hero - 1, active)
    game.end_turn()
    returned = f"owner={target.controller.name};player1_field={target in player.field};player2_field={target in opponent.field};zone={target.zone.name};charge={target.charge}"
    ensure(target.controller is opponent and target in opponent.field and target not in player.field, returned)
    ensure(not target.charge and target.zone == Zone.PLAY, returned)

    return f"during_turn={active};after_end_turn={returned}"


def shadow_madness_rejects_over_attack_limit():
    game = new_game(CardClass.PRIEST)
    player, opponent = game.player1, game.player2
    over_limit = opponent.summon("CS2_182")  # 4 Attack, above the printed maximum.
    spell = player.give("EX1_334")
    offered = over_limit in spell.targets
    mana_before = player.mana
    try:
        spell.play(target=over_limit)
    except Exception as error:
        rejected = type(error).__name__
    else:
        rejected = "accepted"
    invalid = f"4_attack_target_offered={offered};play={rejected};spell={spell.zone.name};mana={mana_before}->{player.mana};controller={over_limit.controller.name}"
    ensure(not offered and rejected != "accepted" and spell.zone == Zone.HAND and player.mana == mana_before and over_limit.controller is opponent, invalid)
    return invalid


def lightspawn_attack_tracks_health():
    game = new_game(CardClass.PRIEST)
    player, opponent = game.player1, game.player2
    spawn = player.summon("EX1_335")
    before = (spawn.atk, spawn.health)
    game.end_turn()
    moonfire = opponent.give("CS2_008")
    moonfire.play(target=spawn)
    after = (spawn.atk, spawn.health, spawn.damage)
    observed = f"before={before};after_moonfire={after};zone={spawn.zone.name}"
    ensure(after == (4, 4, 1) and spawn.zone == Zone.PLAY, observed)
    return observed


def thoughtsteal_copies_known_opponent_cards():
    game = new_game(CardClass.PRIEST)
    player, opponent = game.player1, game.player2
    known = [opponent.give("CS2_231"), opponent.give("CS2_008")]
    for card in known:
        card.shuffle_into_deck()
    before = len(opponent.deck)
    spell = player.give("EX1_339")
    spell.play()
    own_ids = [card.id for card in player.hand]
    observed = f"copied_ids={own_ids};opponent_deck={before}->{len(opponent.deck)};source_zones={[card.zone.name for card in known]}"
    ensure(all(any(card.id == original.id and card.controller is player for card in player.hand) for original in known), observed)
    ensure(len(opponent.deck) == before and all(card.zone == Zone.DECK for card in known), observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def lightwell_heals_single_damaged_friendly_at_start():
    game = new_game(CardClass.PRIEST)
    player = game.player1
    player.hero.damage = 6
    before = player.hero.health
    well = player.summon("EX1_341")
    game.end_turn()
    after_opponent_turn = player.hero.health
    game.end_turn()
    after_own_start = player.hero.health
    observed = f"hero_health={before}->{after_opponent_turn}->{after_own_start};well={well.zone.name}"
    ensure(after_opponent_turn == before and after_own_start == min(before + 3, player.hero.max_health), observed)
    ensure(well.zone == Zone.PLAY, observed)
    return observed


def lightwell_random_heal_selects_one_and_reaches_both():
    import random

    selections = set()
    samples = []
    for seed in range(32):
        game = new_game(CardClass.PRIEST)
        player = game.player1
        first = player.summon("CS2_182")
        second = player.summon("CS2_200")
        first.damage = 3
        second.damage = 3
        well = player.summon("EX1_341")
        before = (first.health, second.health)
        random.seed(seed)
        game.end_turn()
        game.end_turn()
        after = (first.health, second.health)
        deltas = (after[0] - before[0], after[1] - before[1])
        observed = f"seed={seed};healing_delta={deltas};well={well.zone.name}"
        ensure(deltas in ((3, 0), (0, 3)), observed)
        selections.add(0 if deltas == (3, 0) else 1)
        samples.append(observed)
        if selections == {0, 1}:
            break
    ensure(selections == {0, 1}, f"random selection did not reach both damaged minions in 32 seeds; samples={samples}")
    return f"distinct_damaged_candidates_reached={sorted(selections)};samples={samples}"


def mindgames_known_random_minion_and_empty_minion_pool():
    game = new_game(CardClass.PRIEST)
    player, opponent = game.player1, game.player2
    known = opponent.give("CS2_182")
    known.shuffle_into_deck()
    opponent.give("CS2_008").shuffle_into_deck()
    spell = player.give("EX1_345")
    spell.play()
    copies = list(player.field)
    observed = f"one_minion_pool={[ (m.id, m.atk, m.health, m.zone.name) for m in copies ]};spell={spell.zone.name}"
    ensure(len(copies) == 1 and copies[0].id == known.id and (copies[0].atk, copies[0].health) == (4, 5), observed)
    ensure(copies[0].controller is player and spell.zone == Zone.GRAVEYARD, observed)

    game = new_game(CardClass.PRIEST)
    player, opponent = game.player1, game.player2
    opponent.give("CS2_008").shuffle_into_deck()
    spell = player.give("EX1_345")
    spell.play()
    fallback = list(player.field)
    empty = f"no_minion_pool={[ (m.id, m.atk, m.health, m.zone.name) for m in fallback ]};spell={spell.zone.name}"
    ensure(len(fallback) == 1 and fallback[0].id == "EX1_345t", empty)
    ensure((fallback[0].atk, fallback[0].health) == (0, 1) and spell.zone == Zone.GRAVEYARD, empty)
    return f"known_pool={observed};empty_pool={empty}"


def lay_on_hands_heals_and_draws_three_known_cards():
    game = new_game(CardClass.PALADIN)
    player = game.player1
    player.hero.damage = 12
    for card_id in ("CS2_231", "CS2_008", "CS2_142"):
        player.give(card_id).shuffle_into_deck()
    before = player.hero.health
    spell = player.give("EX1_354")
    spell.play(target=player.hero)
    ids = [card.id for card in player.hand]
    observed = f"hero={before}->{player.hero.health};drawn={ids};deck={len(player.deck)};spell={spell.zone.name}"
    ensure(player.hero.health == min(before + 8, player.hero.max_health), observed)
    ensure(all(any(card.id == card_id for card in player.hand) for card_id in ("CS2_231", "CS2_008", "CS2_142")), observed)
    ensure(len(player.deck) == 0 and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def lay_on_hands_heals_friendly_minion_target():
    game = new_game(CardClass.PALADIN)
    player = game.player1
    target = player.summon("CS2_182")
    target.damage = 3
    before = target.health
    for card_id in ("CS2_231", "CS2_008", "CS2_142"):
        player.give(card_id).shuffle_into_deck()
    spell = player.give("EX1_354")
    offered = target in spell.targets
    spell.play(target=target)
    observed = f"friendly_target_offered={offered};target_health={before}->{target.health}/{target.max_health};draws={[card.id for card in player.hand]};spell={spell.zone.name}"
    ensure(offered and target.health == target.max_health, observed)
    ensure(all(any(card.id == card_id for card in player.hand) for card_id in ("CS2_231", "CS2_008", "CS2_142")), observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def lay_on_hands_heals_enemy_minion_target():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    target.damage = 3
    before = target.health
    for card_id in ("CS2_231", "CS2_008", "CS2_142"):
        player.give(card_id).shuffle_into_deck()
    spell = player.give("EX1_354")
    offered = target in spell.targets
    spell.play(target=target)
    observed = f"enemy_target_offered={offered};target_health={before}->{target.health}/{target.max_health};draws={[card.id for card in player.hand]};spell={spell.zone.name}"
    ensure(offered and target.health == target.max_health, observed)
    ensure(all(any(card.id == card_id for card in player.hand) for card_id in ("CS2_231", "CS2_008", "CS2_142")), observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def blessed_champion_doubles_attack():
    game = new_game(CardClass.PALADIN)
    player = game.player1
    target = player.summon("CS2_182")
    before = (target.atk, target.health)
    spell = player.give("EX1_355")
    spell.play(target=target)
    observed = f"target={before}->{(target.atk, target.health)};spell={spell.zone.name}"
    ensure((target.atk, target.health) == (before[0] * 2, before[1]), observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def blessed_champion_doubles_enemy_minion_attack():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    before = (target.atk, target.health)
    spell = player.give("EX1_355")
    offered = target in spell.targets
    spell.play(target=target)
    observed = f"enemy_target_offered={offered};target={before}->{(target.atk, target.health)};spell={spell.zone.name}"
    ensure(offered and (target.atk, target.health) == (before[0] * 2, before[1]), observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def argent_protector_shield_with_and_without_target():
    game = new_game(CardClass.PALADIN)
    player = game.player1
    target = player.summon(WISP)
    minion = player.give("EX1_362")
    offered = target in minion.targets
    minion.play(target=target)
    observed = f"target_offered={offered};target_shield={target.divine_shield};protector={minion.zone.name}:{minion.atk}/{minion.health}"
    ensure(offered and target.divine_shield and minion.zone == Zone.PLAY and minion in player.field, observed)

    game = new_game(CardClass.PALADIN)
    player = game.player1
    minion = player.give("EX1_362")
    no_target_playable = minion.is_playable()
    minion.play()
    no_target = f"playable_without_friendly_minion={no_target_playable};body={minion.zone.name}:{minion.atk}/{minion.health}"
    ensure(no_target_playable and minion.zone == Zone.PLAY, no_target)
    return f"target_branch={observed};no_target_branch={no_target}"


def argent_protector_shield_absorbs_attack():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    target = player.summon(WISP)
    player.give("EX1_362").play(target=target)
    boar = opponent.summon("CS2_171")
    game.end_turn()
    ready = boar.can_attack(target)
    boar.attack(target)
    observed = f"boar_ready={ready};target_shield={target.divine_shield};target_health={target.health};target_damage={target.damage};boar_zone={boar.zone.name}"
    ensure(ready and not target.divine_shield and target.health == 1 and target.damage == 0, observed)
    return observed


def blessing_of_wisdom_friendly_attacker_draws():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    known = player.give("CS2_231")
    known.shuffle_into_deck()
    attacker = player.give("CS2_171")
    attacker.play()
    blessing = player.give("EX1_363")
    offered = attacker in blessing.targets
    blessing.play(target=attacker)
    ready = attacker.can_attack(opponent.hero)
    attacker.attack(opponent.hero)
    observed = f"target_offered={offered};attacker_ready={ready};enemy_health={opponent.hero.health};draw={known.zone.name};deck={len(player.deck)}"
    ensure(offered and ready and opponent.hero.health == 29, observed)
    ensure(known.zone == Zone.HAND and len(player.deck) == 0, observed)
    return observed


def blessing_of_wisdom_enemy_attacker_draw_owner():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    own_known = player.give("CS2_231")
    own_known.shuffle_into_deck()
    enemy_known = [opponent.give("CS2_008"), opponent.give("CS2_231")]
    for card in enemy_known:
        card.shuffle_into_deck()
    attacker = opponent.summon("CS2_171")
    blessing = player.give("EX1_363")
    offered = attacker in blessing.targets
    blessing.play(target=attacker)
    game.end_turn()
    natural_draws = [card for card in enemy_known if card in opponent.hand]
    deck_after_turn_draw = len(opponent.deck)
    ready = attacker.can_attack(player.hero)
    attacker.attack(player.hero)
    observed = f"target_offered={offered};natural_enemy_draws={[card.id for card in natural_draws]};deck_after_turn_draw={deck_after_turn_draw};attacker_ready={ready};own_deck_card={own_known.zone.name};enemy_deck={[card.id for card in opponent.deck]};own_deck={len(player.deck)};enemy_deck_count={len(opponent.deck)};own_hero={player.hero.health}"
    ensure(offered and ready and player.hero.health == 29, observed)
    ensure(len(natural_draws) == 1 and deck_after_turn_draw == 1, observed)
    ensure(own_known.zone == Zone.HAND and len(opponent.deck) == 1, observed)
    ensure(len(player.deck) == 0 and len(opponent.deck) == 1, observed)
    return observed


def holy_wrath_drawn_card_cost_damage():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    drawn = player.give("CS2_182")  # Cost 4.
    drawn.shuffle_into_deck()
    target = opponent.summon("CS2_200")
    before = target.health
    spell = player.give("EX1_365")
    offered = target in spell.targets
    spell.play(target=target)
    observed = f"target_offered={offered};drawn={drawn.id}:{drawn.zone.name};target_health={before}->{target.health};damage={target.damage};spell={spell.zone.name}"
    ensure(offered and drawn in player.hand and len(player.deck) == 0, observed)
    ensure(target.zone == Zone.PLAY and target.damage == 4 and target.health == before - 4, observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def sword_of_justice_buffs_each_new_summon():
    game = new_game(CardClass.PALADIN)
    player = game.player1
    before_weapon = player.summon(WISP)
    weapon = player.give("EX1_366")
    weapon.play()
    first = player.summon(WISP)
    after_first = (first.atk, first.health, player.weapon.durability)
    second = player.summon(WISP)
    after_second = (second.atk, second.health, player.weapon.durability)
    observed = f"preexisting={before_weapon.atk}/{before_weapon.health};after_first={after_first};after_second={after_second};weapon={player.weapon.atk}/{player.weapon.durability}"
    ensure((before_weapon.atk, before_weapon.health) == (1, 1), observed)
    ensure(after_first == (2, 2, 4) and after_second == (2, 2, 3), observed)
    return observed


def repentance_reduces_played_enemy_minion_to_one_health():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    secret = player.give("EX1_379")
    secret.play()
    before_secrets = len(player.secrets)
    game.end_turn()
    minion = opponent.give("CS2_182")
    minion.play()
    observed = f"secrets={before_secrets}->{len(player.secrets)};enemy_minion={minion.zone.name}:{minion.health}/{minion.max_health};damage={minion.damage};secret={secret.zone.name}"
    ensure(minion.zone == Zone.PLAY and minion.health == 1, observed)
    ensure(len(player.secrets) == 0 and secret.zone == Zone.GRAVEYARD, observed)
    return observed


def aldor_sets_enemy_attack_to_one():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    before = (target.atk, target.health)
    peacekeeper = player.give("EX1_382")
    offered = target in peacekeeper.targets
    peacekeeper.play(target=target)
    observed = f"target_offered={offered};target={before}->{(target.atk, target.health)};controller={target.controller.name}"
    ensure(offered and (target.atk, target.health) == (1, before[1]), observed)
    ensure(target.controller is opponent and target.zone == Zone.PLAY, observed)
    return observed


def tirion_shield_taunt_and_deathrattle_weapon():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    tirion = player.give("EX1_383")
    tirion.play()
    opening = f"body={tirion.zone.name}:{tirion.atk}/{tirion.health};taunt={tirion.taunt};shield={tirion.divine_shield}"
    ensure(tirion.taunt and tirion.divine_shield and tirion.zone == Zone.PLAY, opening)
    game.end_turn()
    opponent.give("CS2_029").play(target=tirion)
    after_shield = f"shield={tirion.divine_shield};health={tirion.health};zone={tirion.zone.name}"
    ensure(not tirion.divine_shield and tirion.health == 6 and tirion.zone == Zone.PLAY, after_shield)
    opponent.give("CS2_029").play(target=tirion)
    weapon = player.weapon
    death = f"tirion={tirion.zone.name};weapon={getattr(weapon, 'id', None)}:{getattr(weapon, 'atk', None)}/{getattr(weapon, 'durability', None)}"
    ensure(tirion.zone == Zone.GRAVEYARD, death)
    ensure(weapon is not None and weapon.id == "EX1_383t" and (weapon.atk, weapon.durability) == (5, 3), death)
    return f"entry={opening};first_hit={after_shield};deathrattle={death}"


def avenging_wrath_hits_only_enemies_for_eight():
    game = new_game(CardClass.PALADIN)
    player, opponent = game.player1, game.player2
    first = opponent.summon("CS2_200")
    second = opponent.summon("CS2_200")
    own = player.summon("CS2_200")
    baseline = (opponent.hero.health, first.damage, second.damage, own.damage, player.hero.health)
    spell = player.give("EX1_384")
    spell.play()
    enemy_damage = (opponent.hero.health - baseline[0]) * -1 + (first.damage - baseline[1]) + (second.damage - baseline[2])
    observed = f"enemy_hero={baseline[0]}->{opponent.hero.health};enemy_minions={(first.damage, second.damage)};total_enemy_damage={enemy_damage};friendly_damage={own.damage};own_hero={player.hero.health};spell={spell.zone.name}"
    ensure(enemy_damage == 8, observed)
    ensure(own.damage == baseline[3] and player.hero.health == baseline[4], observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def tauren_warrior_taunt_and_enrage():
    game = new_game(CardClass.WARRIOR)
    player = game.player1
    warrior = player.give("EX1_390")
    warrior.play()
    base = (warrior.atk, warrior.health)
    taunt = warrior.taunt
    player.give("CS2_008").play(target=warrior)
    damaged = (warrior.atk, warrior.health, warrior.damage)
    player.give("CS2_089").play(target=warrior)
    healed = (warrior.atk, warrior.health, warrior.damage)
    observed = f"taunt={taunt};base={base};damaged={damaged};healed={healed}"
    ensure(taunt and damaged == (base[0] + 3, base[1] - 1, 1), observed)
    ensure(healed == (base[0], base[1], 0), observed)
    return observed


def slam_survivor_draws():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS2_182")
    known = player.give("CS2_231")
    known.shuffle_into_deck()
    spell = player.give("EX1_391")
    before = target.health
    spell.play(target=target)
    observed = f"target_health={before}->{target.health};damage={target.damage};known_draw={known.zone.name};deck={len(player.deck)};spell={spell.zone.name}"
    ensure(target.zone == Zone.PLAY and target.health == before - 2, observed)
    ensure(known.zone == Zone.HAND and len(player.deck) == 0, observed)
    return observed


def slam_kill_does_not_draw():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    target = opponent.summon(WISP)
    spell = player.give("EX1_391")
    spell.play(target=target)
    observed = f"target={target.zone.name};hand={len(player.hand)};deck={len(player.deck)};spell={spell.zone.name}"
    ensure(target.zone == Zone.GRAVEYARD and len(player.hand) == 0 and len(player.deck) == 0, observed)
    return observed


def battle_rage_counts_damaged_friendly_characters():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    player.hero.damage = 3
    injured = player.summon("CS2_182")
    injured.damage = 2
    full = player.summon("CS2_200")
    own_known = [player.give("CS2_231"), player.give("CS2_008")]
    for card in own_known:
        card.shuffle_into_deck()
    enemy_known = opponent.give("CS2_231")
    enemy_known.shuffle_into_deck()
    spell = player.give("EX1_392")
    before = (len(player.deck), len(opponent.deck))
    spell.play()
    own_ids = [card.id for card in player.hand]
    observed = f"damaged_friendly=hero,minion;full_minion={full.health}/{full.max_health};own_deck={before[0]}->{len(player.deck)};enemy_deck={before[1]}->{len(opponent.deck)};hand={own_ids}"
    ensure(all(card.zone == Zone.HAND for card in own_known) and len(player.deck) == 0, observed)
    ensure(enemy_known.zone == Zone.DECK and len(opponent.deck) == before[1], observed)
    ensure(full.damage == 0 and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def amani_enrage_gains_and_loses_attack():
    game = new_game(CardClass.WARRIOR)
    player = game.player1
    minion = player.give("EX1_393")
    minion.play()
    base = (minion.atk, minion.health)
    player.give("CS2_008").play(target=minion)
    damaged = (minion.atk, minion.health, minion.damage)
    player.give("CS2_089").play(target=minion)
    healed = (minion.atk, minion.health, minion.damage)
    observed = f"base={base};damaged={damaged};healed={healed}"
    ensure(damaged == (base[0] + 3, base[1] - 1, 1), observed)
    ensure(healed == (base[0], base[1], 0), observed)
    return observed


def mogu_shan_warden_taunt_blocks_hero():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    warden = player.give("EX1_396")
    warden.play()
    boar = opponent.summon("CS2_171")
    game.end_turn()
    hero_legal = boar.can_attack(player.hero)
    warden_legal = boar.can_attack(warden)
    before_health = player.hero.health
    if warden_legal:
        boar.attack(warden)
    observed = f"warden={warden.atk}/{warden.health};taunt={warden.taunt};hero_target_legal={hero_legal};warden_target_legal={warden_legal};boar={boar.zone.name};hero_health={before_health}->{player.hero.health}"
    ensure(warden.taunt and not hero_legal and warden_legal, observed)
    ensure(boar.zone == Zone.GRAVEYARD and player.hero.health == before_health, observed)
    return observed


def arathi_weaponsmith_equips_two_two():
    game = new_game(CardClass.WARRIOR)
    player = game.player1
    smith = player.give("EX1_398")
    smith.play()
    weapon = player.weapon
    observed = f"smith={smith.zone.name}:{smith.atk}/{smith.health};weapon={getattr(weapon, 'id', None)}:{getattr(weapon, 'atk', None)}/{getattr(weapon, 'durability', None)}"
    ensure(smith.zone == Zone.PLAY and weapon is not None and (weapon.atk, weapon.durability) == (2, 2), observed)
    return observed


def armorsmith_counts_friendly_damage_events():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    smith = player.give("EX1_402")
    smith.play()
    friendly = player.summon(WISP)
    armor_before = player.hero.armor
    game.end_turn()
    whirlwind = opponent.give("EX1_400")
    whirlwind.play()
    observed = f"armor={armor_before}->{player.hero.armor};smith={smith.zone.name}:{smith.damage};friendly={friendly.zone.name}:{friendly.damage};opponent_minions={len(opponent.field)}"
    ensure(smith.zone == Zone.PLAY and smith.damage == 1, observed)
    ensure(friendly.zone == Zone.GRAVEYARD, observed)
    ensure(player.hero.armor == armor_before + 2, observed)
    return observed


def shieldbearer_taunt_blocks_charge_attack():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    shieldbearer = player.give("EX1_405")
    shieldbearer.play()
    boar = opponent.summon("CS2_171")
    game.end_turn()
    hero_legal = boar.can_attack(player.hero)
    taunt_legal = boar.can_attack(shieldbearer)
    before = player.hero.health
    if taunt_legal:
        boar.attack(shieldbearer)
    observed = f"taunt={shieldbearer.taunt};hero_target_legal={hero_legal};taunt_target_legal={taunt_legal};shieldbearer_health={shieldbearer.health};boar={boar.zone.name};boar_ready_after_attack={boar.can_attack()};hero_health={before}->{player.hero.health}"
    ensure(shieldbearer.taunt and not hero_legal and taunt_legal, observed)
    ensure(player.hero.health == before and boar.zone == Zone.PLAY and shieldbearer.health == shieldbearer.max_health - 1, observed)
    ensure(not boar.can_attack(), observed)
    return observed


def brawl_random_survivor_and_same_batch_deathrattle():
    import random

    survivors_seen = set()
    traces = []
    for seed in range(32):
        game = new_game(CardClass.WARRIOR)
        player, opponent = game.player1, game.player2
        minions = [player.summon("CS2_182"), player.summon("EX1_105"), opponent.summon("CS2_200")]
        random.seed(seed)
        brawl = player.give("EX1_407")
        brawl.play()
        survivor = [minion for minion in minions if minion.zone == Zone.PLAY]
        trace = f"seed={seed};zones={[m.zone.name for m in minions]};survivor={[m.id for m in survivor]};board={[m.id for m in game.board]}"
        ensure(len(survivor) == 1, trace)
        survivors_seen.add(survivor[0].id)
        traces.append(trace)
        if survivors_seen == {"CS2_182", "EX1_105", "CS2_200"}:
            break
    ensure(survivors_seen == {"CS2_182", "EX1_105", "CS2_200"}, f"Brawl survivor randomization did not reach every candidate: {traces}")

    deathrattle_traces = []
    for seed in range(32):
        game = new_game(CardClass.WARRIOR)
        player, opponent = game.player1, game.player2
        ambusher = player.summon("FP1_026")
        ally = player.summon("CS2_182")
        enemy = opponent.summon("CS2_200")
        random.seed(seed)
        brawl = player.give("EX1_407")
        brawl.play()
        trace = f"seed={seed};ambusher={ambusher.zone.name};ally={ally.zone.name};enemy={enemy.zone.name};board={[m.id for m in game.board]}"
        deathrattle_traces.append(trace)
        if ambusher.zone == Zone.GRAVEYARD and ally.zone == Zone.HAND and enemy.zone == Zone.PLAY:
            raise ProbeMismatch(f"Brawl's enemy survivor remains, but Anub'ar Ambusher returns its same-batch-destroyed ally: {trace}")
    return f"random_survivors={sorted(survivors_seen)};brawl_traces={traces};deathrattle_traces={deathrattle_traces}"


def mortal_strike_damage_thresholds():
    results = []
    for health, expected_damage in ((30, 4), (12, 6)):
        game = new_game(CardClass.WARRIOR)
        player, opponent = game.player1, game.player2
        player.hero.damage = player.hero.max_health - health
        before = opponent.hero.health
        spell = player.give("EX1_408")
        spell.play(target=opponent.hero)
        observed = f"own_health={player.hero.health};damage_expected={expected_damage};enemy_hero={before}->{opponent.hero.health};spell={spell.zone.name}"
        ensure(opponent.hero.health == before - expected_damage and spell.zone == Zone.GRAVEYARD, observed)
        results.append(observed)
    return " | ".join(results)


def upgrade_weapon_and_no_weapon_branches():
    game = new_game(CardClass.WARRIOR)
    player = game.player1
    spell = player.give("EX1_409")
    spell.play()
    created = player.weapon
    no_weapon = f"weapon={created.id}:{created.atk}/{created.durability};spell={spell.zone.name}"
    ensure(created.id == "EX1_409t" and (created.atk, created.durability) == (1, 3), no_weapon)

    game = new_game(CardClass.WARRIOR)
    player = game.player1
    equipped = player.give("CS2_091")
    equipped.play()
    before = (player.weapon.atk, player.weapon.durability)
    spell = player.give("EX1_409")
    spell.play()
    buffed = (player.weapon.atk, player.weapon.durability)
    observed = f"no_weapon_branch={no_weapon};equipped_branch={before}->{buffed};spell={spell.zone.name}"
    ensure(before == (1, 4) and buffed == (2, 5) and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def shield_slam_damage_scales_with_armor():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    target = opponent.summon("CS2_200")
    shield_block = player.give("EX1_606")
    shield_block.play()
    before = (target.health, player.hero.armor)
    spell = player.give("EX1_410")
    spell.play(target=target)
    observed = f"armor={before[1]};target_health={before[0]}->{target.health};damage={target.damage};spell={spell.zone.name}"
    ensure(before[1] == 5 and target.zone == Zone.PLAY and target.damage == 5 and target.health == before[0] - 5, observed)
    ensure(spell.zone == Zone.GRAVEYARD, observed)
    return observed


def gorehowl_minion_attack_costs_attack_not_durability():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    target = opponent.summon("EX1_105")
    weapon_card = player.give("EX1_411")
    weapon_card.play()
    start = (player.weapon.atk, player.weapon.durability)
    player.hero.attack(target)
    after_minion = (player.weapon.atk, player.weapon.durability, target.damage, target.zone.name)
    can_attack_again_same_turn = player.hero.can_attack(opponent.hero)
    game.end_turn()
    game.end_turn()
    ready_next_turn = player.hero.can_attack(opponent.hero)
    opponent_health = opponent.hero.health
    player.hero.attack(opponent.hero)
    after_hero = (player.weapon.atk if player.weapon else 0, player.weapon.durability if player.weapon else 0, player.weapon.zone.name if player.weapon else "NONE", opponent_health - opponent.hero.health)
    observed = f"start={start};after_minion={after_minion};can_attack_again_same_turn={can_attack_again_same_turn};ready_next_turn={ready_next_turn};after_hero={after_hero}"
    ensure(start == (7, 1) and after_minion == (6, 1, 7, "PLAY"), observed)
    ensure(not can_attack_again_same_turn and ready_next_turn, observed)
    ensure(after_hero == (0, 0, "NONE", 6), observed)
    return observed


def raging_worgen_enrage_grants_windfury_attacks():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    worgen = player.give("EX1_412")
    worgen.play()
    base_attack = worgen.atk
    player.give("CS2_008").play(target=worgen)
    damaged = (worgen.atk, worgen.windfury, worgen.health)
    game.end_turn()
    game.end_turn()
    first_ready = worgen.can_attack(opponent.hero)
    worgen.attack(opponent.hero)
    second_ready = worgen.can_attack(opponent.hero)
    worgen.attack(opponent.hero)
    third_ready = worgen.can_attack(opponent.hero)
    observed = f"base_attack={base_attack};damaged={damaged};ready_before={first_ready};ready_after_one={second_ready};ready_after_two={third_ready};enemy_health={opponent.hero.health}"
    ensure(damaged == (base_attack + 1, True, 2), observed)
    ensure(first_ready and second_ready and not third_ready, observed)
    ensure(opponent.hero.health == 30 - base_attack * 2 - 2, observed)
    return observed


def grommash_charge_and_enrage_attack():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    grommash = player.give("EX1_414")
    grommash.play()
    base = grommash.atk
    player.give("CS2_008").play(target=grommash)
    attack = grommash.atk
    ready = grommash.can_attack(opponent.hero)
    grommash.attack(opponent.hero)
    damaged_state = f"base_attack={base};enraged_attack={attack};charge={grommash.charge};ready={ready};enemy_health={opponent.hero.health}"
    ensure(attack == base + 6 and ready and opponent.hero.health == 30 - attack, damaged_state)
    player.give("CS2_089").play(target=grommash)
    healed = f"attack_after_heal={grommash.atk};health={grommash.health}/{grommash.max_health}"
    ensure(grommash.atk == base and grommash.health == grommash.max_health, healed)
    return f"charge_and_attack={damaged_state};healed={healed}"


def murloc_warleader_buffs_only_other_friendly_murlocs():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    ally = player.summon("CS2_168")
    enemy = opponent.summon("CS2_168")
    ally_base, enemy_base = ally.atk, enemy.atk
    leader = player.give("EX1_507")
    own_base = leader.atk
    leader.play()
    during = (ally.atk, leader.atk, enemy.atk)
    player.give("EX1_332").play(target=leader)
    after_silence = (ally.atk, leader.atk, enemy.atk)
    observed = f"bases=(ally:{ally_base},leader:{own_base},enemy:{enemy_base});during={during};after_silence={after_silence}"
    ensure(during == (ally_base + 2, own_base, enemy_base), observed)
    ensure(after_silence == (ally_base, own_base, enemy_base), observed)
    return observed


def murloc_tidecaller_gains_from_own_summons_only():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    tidecaller = player.give("EX1_509")
    base = tidecaller.atk
    tidecaller.play()
    after_self = tidecaller.atk
    ally = player.give("CS2_168")
    ally.play()
    after_ally = tidecaller.atk
    game.end_turn()
    enemy = opponent.give("CS2_168")
    enemy.play()
    after_enemy = tidecaller.atk
    observed = f"base={base};after_self_summon={after_self};after_friendly_murloc={after_ally};after_enemy_murloc={after_enemy};ally={ally.zone.name}"
    ensure(after_self == base + 1 and after_ally == after_self + 1 and after_enemy == after_ally, observed)
    return observed


def patient_assassin_stealth_poisonous_attack():
    game = new_game(CardClass.ROGUE)
    player, opponent = game.player1, game.player2
    assassin = player.give("EX1_522")
    assassin.play()
    target = opponent.summon("CS2_182")
    before = (assassin.stealthed, assassin.poisonous, target.health)
    game.end_turn()
    game.end_turn()
    can_attack = assassin.can_attack(target)
    assassin.attack(target)
    observed = f"before={before};can_attack={can_attack};assassin={assassin.zone.name};target={target.zone.name};target_damage={target.damage}"
    ensure(before[0] and before[1] and can_attack, observed)
    ensure(assassin.zone == Zone.GRAVEYARD and target.zone == Zone.GRAVEYARD, observed)
    return observed


def scavenging_hyena_counts_friendly_beast_deaths_only():
    game = new_game(CardClass.HUNTER)
    player, opponent = game.player1, game.player2
    hyena = player.give("EX1_531")
    hyena.play()
    friendly_beast = player.give("CS2_171")
    friendly_beast.play()
    base = (hyena.atk, hyena.health)
    player.give("CS2_008").play(target=friendly_beast)
    after_friendly = (hyena.atk, hyena.health, friendly_beast.zone.name)
    enemy_beast = opponent.summon("CS2_171")
    player.give("CS2_008").play(target=enemy_beast)
    after_enemy = (hyena.atk, hyena.health, enemy_beast.zone.name)
    observed = f"base={base};after_friendly_beast_death={after_friendly};after_enemy_beast_death={after_enemy}"
    ensure(after_friendly == (base[0] + 2, base[1] + 1, "GRAVEYARD"), observed)
    ensure(after_enemy == after_friendly[:2] + ("GRAVEYARD",), observed)
    return observed


def misdirection_redirects_attack_to_other_character():
    game = new_game(CardClass.HUNTER)
    player, opponent = game.player1, game.player2
    secret = player.give("EX1_533")
    secret.play()
    game.end_turn()
    attacker = opponent.give("CS2_171")
    attacker.play()
    before = (player.hero.health, opponent.hero.health)
    legal = attacker.can_attack(player.hero)
    attacker.attack(player.hero)
    observed = f"original_target_legal={legal};player_hero={before[0]}->{player.hero.health};opponent_hero={before[1]}->{opponent.hero.health};attacker={attacker.zone.name};secret_active={secret in player.secrets}"
    ensure(legal and secret not in player.secrets, observed)
    ensure(player.hero.health == before[0] and opponent.hero.health == before[1] - 1, observed)
    return observed


def savannah_highmane_summons_two_hyenas_on_death():
    game = new_game(CardClass.MAGE)
    player = game.player1
    highmane = player.give("EX1_534")
    highmane.play()
    body = (highmane.atk, highmane.health)
    player.give("CS2_029").play(target=highmane)
    hyenas = [minion for minion in player.field if minion.id == "EX1_534t"]
    observed = f"body={body};highmane={highmane.zone.name};hyenas={[(m.id, m.atk, m.health, m.races) for m in hyenas]}"
    ensure(body == (6, 5) and highmane.zone == Zone.GRAVEYARD, observed)
    ensure(len(hyenas) == 2 and all((m.atk, m.health) == (2, 2) for m in hyenas), observed)
    return observed


def eaglehorn_bow_gains_durability_only_from_friendly_secret():
    friendly_game = new_game(CardClass.HUNTER)
    player, opponent = friendly_game.player1, friendly_game.player2
    bow_card = player.give("EX1_536")
    bow_card.play()
    bow = player.weapon
    player.give("EX1_289").play()
    before_friendly_reveal = bow.durability
    friendly_game.end_turn()
    attacker = opponent.give("CS2_171")
    attacker.play()
    attacker.attack(player.hero)
    after_friendly_reveal = bow.durability
    friendly_revealed = not player.secrets

    enemy_game = new_game(CardClass.HUNTER)
    player2, opponent2 = enemy_game.player1, enemy_game.player2
    bow2_card = player2.give("EX1_536")
    bow2_card.play()
    bow2 = player2.weapon
    player2.summon("CS2_171")
    enemy_game.end_turn()
    opponent2.give("EX1_289").play()
    enemy_game.end_turn()
    player2.field[0].attack(opponent2.hero)
    after_enemy_reveal = bow2.durability
    enemy_revealed = not opponent2.secrets
    observed = f"friendly_secret_durability={before_friendly_reveal}->{after_friendly_reveal};friendly_revealed={friendly_revealed};enemy_secret_durability={bow2.durability if not enemy_revealed else after_enemy_reveal};enemy_revealed={enemy_revealed};enemy_hero_armor={opponent2.hero.armor}"
    ensure(before_friendly_reveal == 2 and after_friendly_reveal == 3 and friendly_revealed, observed)
    ensure(enemy_revealed and after_enemy_reveal == 2, observed)
    return observed


def explosive_shot_hits_target_and_adjacent_minions():
    game = new_game(CardClass.HUNTER)
    player, opponent = game.player1, game.player2
    far_left = opponent.summon("CS2_182")
    left = opponent.summon("CS2_182")
    target = opponent.summon("EX1_105")
    right = opponent.summon("CS2_182")
    spell = player.give("EX1_537")
    offered = target in spell.targets
    spell.play(target=target)
    observed = f"target_offered={offered};far_left={far_left.health}/{far_left.damage};left={left.health}/{left.damage};target={target.health}/{target.damage}:{target.zone.name};right={right.health}/{right.damage}"
    ensure(offered and spell.zone == Zone.GRAVEYARD, observed)
    ensure(target.zone == Zone.PLAY and target.damage == 5 and target.health == 3, observed)
    ensure(left.damage == 2 and right.damage == 2 and far_left.damage == 0, observed)
    return observed


def unleash_the_hounds_counts_enemy_minions_and_charge_attacks():
    outcomes = []
    for enemy_count in (0, 2):
        game = new_game(CardClass.HUNTER)
        player, opponent = game.player1, game.player2
        enemies = [opponent.summon("CS2_182") for _ in range(enemy_count)]
        spell = player.give("EX1_538")
        playable = spell.is_playable()
        if enemy_count == 0:
            observed = f"enemy_count=0;playable={playable};spell={spell.zone.name};mana={player.mana}"
            ensure(not playable and spell.zone == Zone.HAND and player.mana == 10, observed)
            outcomes.append(observed)
            continue
        ensure(playable, f"two enemy minions should make Unleash playable: {spell.requirements}")
        spell.play()
        hounds = [minion for minion in player.field if minion.id == "EX1_538t"]
        readiness = [hound.can_attack(opponent.hero) for hound in hounds]
        for hound in hounds:
            hound.attack(opponent.hero)
        observed = f"enemy_count={len(enemies)};hounds={[(m.atk, m.health, m.charge, m.zone.name) for m in hounds]};ready={readiness};enemy_hero={30}->{opponent.hero.health}"
        ensure(len(hounds) == enemy_count and all((m.atk, m.health, m.charge) == (1, 1, True) for m in hounds), observed)
        ensure(all(readiness) and opponent.hero.health == 30 - enemy_count, observed)
        outcomes.append(observed)
    return " | ".join(outcomes)


def king_krush_charge_allows_immediate_attack():
    game = new_game(CardClass.HUNTER)
    player, opponent = game.player1, game.player2
    krush = player.give("EX1_543")
    krush.play()
    ready = krush.can_attack(opponent.hero)
    krush.attack(opponent.hero)
    observed = f"body={krush.zone.name}:{krush.atk}/{krush.health};charge={krush.charge};ready_on_play={ready};enemy_hero={30}->{opponent.hero.health};mana={player.mana}"
    ensure(krush.zone == Zone.PLAY and (krush.atk, krush.health, krush.charge) == (8, 8, True), observed)
    ensure(ready and opponent.hero.health == 22 and player.mana == 1, observed)
    return observed


def flare_removes_stealth_and_enemy_secrets_then_draws():
    game = new_game(CardClass.HUNTER)
    player, opponent = game.player1, game.player2
    friendly_secret = player.give("EX1_289")
    friendly_secret.play()
    friendly_stealth = player.summon("EX1_522")
    enemy_stealth = opponent.summon("EX1_028")
    for card_id in ("CS2_182", "CS2_231"):
        player.give(card_id).put_on_top()
    game.end_turn()
    enemy_secret_ids = []
    for card_id in ("EX1_289", "EX1_533"):
        secret = opponent.give(card_id)
        secret.play()
        enemy_secret_ids.append(secret.id)
    game.end_turn()
    natural_draws = [card.id for card in player.hand]
    flare = player.give("EX1_544")
    flare.play()
    observed = f"stealth=(friendly:{friendly_stealth.stealthed},enemy:{enemy_stealth.stealthed});enemy_secrets_before={enemy_secret_ids};enemy_secrets_after={[c.id for c in opponent.secrets]};friendly_secret_remains={friendly_secret in player.secrets};drawn={natural_draws + [c.id for c in player.hand if c.id not in natural_draws]};deck={len(player.deck)}"
    ensure(not friendly_stealth.stealthed and not enemy_stealth.stealthed, observed)
    ensure(not opponent.secrets and friendly_secret in player.secrets, observed)
    ensure(all(card_id in [card.id for card in player.hand] for card_id in ("CS2_182", "CS2_231")) and not player.deck, observed)
    ensure(flare.zone == Zone.GRAVEYARD, observed)
    return observed


def bestial_wrath_grants_attack_and_turn_immune():
    game = new_game(CardClass.HUNTER)
    player, opponent = game.player1, game.player2
    beast = player.give("CS2_171")
    beast.play()
    enemy = opponent.summon("CS2_182")
    base_attack = beast.atk
    spell = player.give("EX1_549")
    offered = beast in spell.targets
    spell.play(target=beast)
    during = (beast.atk, beast.immune, beast.health, enemy.health)
    beast.attack(enemy)
    after_attack = (beast.zone.name, beast.health, beast.damage, enemy.health, enemy.damage)
    game.end_turn()
    after_turn = (beast.atk, beast.immune)
    observed = f"target_offered={offered};during={during};after_attack={after_attack};after_turn={after_turn};base_attack={base_attack}"
    ensure(offered and during[:2] == (base_attack + 2, True), observed)
    ensure(after_attack == ("PLAY", beast.max_health, 0, enemy.max_health - (base_attack + 2), base_attack + 2), observed)
    ensure(after_turn == (base_attack, False) and spell.zone == Zone.GRAVEYARD, observed)
    return observed


def snake_trap_only_triggers_when_friendly_minion_is_attacked():
    attack_branch = new_game(CardClass.HUNTER)
    player, opponent = attack_branch.player1, attack_branch.player2
    trap = player.give("EX1_554")
    trap.play()
    wisp = player.give(WISP)
    wisp.play()
    attack_branch.end_turn()
    boar = opponent.give("CS2_171")
    boar.play()
    boar.attack(wisp)
    snakes = [minion for minion in player.field if minion.id == "EX1_554t"]
    attack_observed = f"minion_attack=secret_active:{trap in player.secrets};wisp={wisp.zone.name};snakes={[(m.atk, m.health) for m in snakes]}"
    ensure(trap not in player.secrets and wisp.zone == Zone.GRAVEYARD, attack_observed)
    ensure(len(snakes) == 3 and all((m.atk, m.health) == (1, 1) for m in snakes), attack_observed)

    hero_branch = new_game(CardClass.HUNTER)
    player2, opponent2 = hero_branch.player1, hero_branch.player2
    hero_trap = player2.give("EX1_554")
    hero_trap.play()
    hero_branch.end_turn()
    hero_boa = opponent2.give("CS2_171")
    hero_boa.play()
    hero_boa.attack(player2.hero)
    hero_observed = f"hero_attack=secret_active:{hero_trap in player2.secrets};snakes={len([m for m in player2.field if m.id == 'EX1_554t'])};hero_health={player2.hero.health}"
    ensure(hero_trap in player2.secrets and not player2.field, hero_observed)
    return f"{attack_observed} | {hero_observed}"


def harvest_golem_deathrattle_summons_damaged_golem():
    game = new_game(CardClass.MAGE)
    player = game.player1
    golem = player.give("EX1_556")
    golem.play()
    body = (golem.atk, golem.health)
    for _ in range(3):
        player.give("CS2_008").play(target=golem)
    tokens = [minion for minion in player.field if minion is not golem]
    observed = f"body={body};golem={golem.zone.name};tokens={[(m.id, m.atk, m.health, m.races) for m in tokens]}"
    ensure(body == (2, 3) and golem.zone == Zone.GRAVEYARD, observed)
    ensure(len(tokens) == 1 and (tokens[0].atk, tokens[0].health) == (2, 1), observed)
    return observed


def nat_pagle_has_both_seeded_start_turn_draw_outcomes():
    import random

    outcomes = {}
    traces = []
    for seed in range(64):
        game = new_game(CardClass.WARRIOR)
        player, opponent = game.player1, game.player2
        nat = player.summon("EX1_557")
        for card_id in ("CS2_182", "CS2_231"):
            player.give(card_id).put_on_top()
        game.end_turn()
        random.seed(seed)
        game.end_turn()
        count = len(player.hand)
        trace = f"seed={seed};nat={nat.zone.name};drawn={[card.id for card in player.hand]};deck={len(player.deck)}"
        ensure(count in (1, 2) and len(player.deck) == 2 - count, trace)
        outcomes.setdefault(count, trace)
        traces.append(trace)
        if set(outcomes) == {1, 2}:
            break
    ensure(set(outcomes) == {1, 2}, f"did not reach both 50% branches: {traces}")
    return f"no_extra={outcomes[1]};extra={outcomes[2]}"


def harrison_jones_draws_opponent_weapon_durability():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    for card_id in ("CS2_182", "CS2_231", "CS2_008", "CS2_142", "CS2_029"):
        player.give(card_id).put_on_top()
    game.end_turn()
    enemy_weapon = opponent.give("CS2_091")
    enemy_weapon.play()
    weapon_before = (opponent.weapon.atk, opponent.weapon.durability)
    game.end_turn()
    harrison = player.give("EX1_558")
    harrison.play()
    known_draws = [card.id for card in player.hand]
    weapon_after = opponent.weapon
    observed = f"enemy_weapon_before={weapon_before};enemy_weapon_after={getattr(weapon_after, 'id', None)};harrison={harrison.zone.name}:{harrison.atk}/{harrison.health};known_draws={known_draws};deck={len(player.deck)};draws_this_turn={player.cards_drawn_this_turn}"
    ensure(weapon_before == (1, 4) and weapon_after is None and enemy_weapon.zone == Zone.GRAVEYARD, observed)
    ensure(all(card_id in known_draws for card_id in ("CS2_182", "CS2_231", "CS2_008", "CS2_142", "CS2_029")), observed)
    ensure(not player.deck and player.cards_drawn_this_turn == 5, observed)

    no_weapon_game = new_game(CardClass.WARRIOR)
    player2 = no_weapon_game.player1
    known_card = player2.give("CS2_182")
    known_card.put_on_top()
    no_weapon_harrison = player2.give("EX1_558")
    no_weapon_harrison.play()
    no_weapon_observed = f"enemy_weapon={getattr(no_weapon_game.player2.weapon, 'id', None)};drawn_hand={[card.id for card in player2.hand]};known_card_zone={known_card.zone.name};deck={len(player2.deck)}"
    ensure(no_weapon_game.player2.weapon is None and not player2.hand, no_weapon_observed)
    ensure(known_card.zone == Zone.DECK and len(player2.deck) == 1, no_weapon_observed)
    return f"4-durability={observed} | no-weapon={no_weapon_observed}"


def antonidas_adds_fireball_for_each_hand_cast_spell():
    game = new_game(CardClass.MAGE)
    player, opponent = game.player1, game.player2
    antonidas = player.give("EX1_559")
    antonidas.play()
    fireballs = []
    damage = []
    for _ in range(2):
        spell = player.give("CS2_008")
        spell.play(target=opponent.hero)
        fireballs.append([card.id for card in player.hand if card.id == "CS2_029"])
        damage.append(opponent.hero.health)
    observed = f"antonidas={antonidas.zone.name};fireball_counts={[len(cards) for cards in fireballs]};fireballs={[cards for cards in fireballs]};enemy_health_after_casts={damage}"
    ensure([len(cards) for cards in fireballs] == [1, 2], observed)
    ensure(damage == [29, 28] and antonidas.zone == Zone.PLAY, observed)
    return observed


def nozdormu_timeout_refresh_is_not_visible_on_players():
    game = new_game(CardClass.DRUID)
    player, opponent = game.player1, game.player2
    before = (player.timeout, opponent.timeout)
    nozdormu = player.give("EX1_560")
    nozdormu.play()
    during = (player.dump()["timeout"], opponent.dump()["timeout"])
    aura_values = tuple(
        next((slot.tags.get(GameTag.TIMEOUT) for slot in target.slots if slot.source is nozdormu), None)
        for target in (player, opponent)
    )
    player.give("EX1_332").play(target=nozdormu)
    after_silence = (player.dump()["timeout"], opponent.dump()["timeout"])
    observed = f"before_serialized={before};aura_timeout_tags={aura_values};while_nozdormu_serialized={during};after_silence_serialized={after_silence};silenced={nozdormu.silenced}"
    ensure(before == (75, 75) and during == (15, 15) and after_silence == (75, 75), observed)
    return observed


def alexstrasza_sets_either_hero_to_15_from_above_or_below():
    outcomes = []
    for target_side, target_health in (("friendly", 8), ("enemy", 22)):
        game = new_game(CardClass.MAGE)
        player, opponent = game.player1, game.player2
        target = player.hero if target_side == "friendly" else opponent.hero
        other = opponent.hero if target is player.hero else player.hero
        target.damage = target.max_health - target_health
        before = (target.health, target.max_health, other.health)
        alex = player.give("EX1_561")
        offered = target in alex.targets
        alex.play(target=target)
        observed = f"side={target_side};target_offered={offered};before={before};after={(target.health, target.max_health, other.health)};body={alex.zone.name}:{alex.atk}/{alex.health}"
        ensure(offered and target.health == 15 and target.max_health == before[1], observed)
        ensure(other.health == before[2] and alex.zone == Zone.PLAY, observed)
        outcomes.append(observed)
    return " | ".join(outcomes)


def onyxia_fills_only_available_friendly_slots():
    outcomes = []
    for existing_count, expected_tokens in ((0, 6), (5, 1), (6, 0)):
        game = new_game(CardClass.HUNTER)
        player = game.player1
        existing = [player.summon("CS2_182") for _ in range(existing_count)]
        onyxia = player.give("EX1_562")
        onyxia.play()
        whelps = [minion for minion in player.field if minion.id == "ds1_whelptoken"]
        observed = f"existing={len(existing)};onyxia={onyxia.zone.name}:{onyxia.atk}/{onyxia.health};field={len(player.field)};whelps={[(m.atk, m.health) for m in whelps]}"
        ensure(len(player.field) == 7 and onyxia.zone == Zone.PLAY, observed)
        ensure(len(whelps) == expected_tokens and all((m.atk, m.health) == (1, 1) for m in whelps), observed)
        outcomes.append(observed)
    return " | ".join(outcomes)


def malygos_spell_damage_and_silence():
    game = new_game(CardClass.MAGE)
    player, opponent = game.player1, game.player2
    malygos = player.give("EX1_563")
    malygos.play()
    spellpower = player.spellpower
    first_before = opponent.hero.health
    player.give("CS2_008").play(target=opponent.hero)
    after_moonfire = opponent.hero.health
    player.give("EX1_332").play(target=malygos)
    silenced = malygos.silenced
    silenced_spellpower = player.spellpower
    second_before = opponent.hero.health
    player.give("CS2_008").play(target=opponent.hero)
    after_silenced_moonfire = opponent.hero.health

    comparison_game = new_game(CardClass.MAGE)
    comparison_player = comparison_game.player1
    kobold = comparison_player.give("CS2_142")
    kobold.play()
    kobold_before = comparison_player.spellpower
    comparison_player.give("EX1_332").play(target=kobold)
    kobold_after = comparison_player.spellpower
    kobold_silenced = kobold.silenced
    observed = f"malygos={malygos.zone.name}:{malygos.atk}/{malygos.health};silenced={silenced};spellpower={spellpower}->{silenced_spellpower};moonfire_damage={(first_before-after_moonfire, second_before-after_silenced_moonfire)};enemy_hero={30}->{opponent.hero.health};kobold_silenced={kobold_silenced};kobold_spellpower={kobold_before}->{kobold_after}"
    ensure(spellpower == 5 and after_moonfire == first_before - 6, observed)
    ensure(silenced and silenced_spellpower == 0 and after_silenced_moonfire == second_before - 1, observed)
    ensure(kobold_silenced and kobold_before == 1 and kobold_after == 0, observed)
    return observed


def faceless_manipulator_copies_friendly_and_enemy_minions():
    outcomes = []
    friendly_game = new_game(CardClass.MAGE)
    player, opponent = friendly_game.player1, friendly_game.player2
    friendly_target = player.give(WISP)
    friendly_target.play()
    player.give("CS2_009").play(target=friendly_target)
    player.give("CS2_008").play(target=friendly_target)
    target_before = (friendly_target.atk, friendly_target.health, friendly_target.max_health, friendly_target.taunt)
    faceless = player.give("EX1_564")
    friendly_offered = friendly_target in faceless.targets
    faceless.play(target=friendly_target)
    copied = next(minion for minion in player.field if minion is not friendly_target and minion.id == WISP)
    friendly_observed = f"friendly_target_offered={friendly_offered};target_before={target_before};copy={copied.id}:{copied.atk}/{copied.health}/{copied.max_health};taunt={copied.taunt};source={faceless.zone.name}"
    ensure(friendly_offered and copied.atk == target_before[0] and copied.health == target_before[1], friendly_observed)
    ensure(copied.max_health == target_before[2] and copied.taunt == target_before[3], friendly_observed)
    outcomes.append(friendly_observed)

    enemy_game = new_game(CardClass.MAGE)
    player2, opponent2 = enemy_game.player1, enemy_game.player2
    enemy_target = opponent2.summon("CS2_182")
    enemy_faceless = player2.give("EX1_564")
    enemy_offered = enemy_target in enemy_faceless.targets
    heroes_offered = player2.hero in enemy_faceless.targets or opponent2.hero in enemy_faceless.targets
    enemy_faceless.play(target=enemy_target)
    enemy_copy = next(minion for minion in player2.field if minion is not enemy_target)
    enemy_observed = f"enemy_target_offered={enemy_offered};hero_targets_offered={heroes_offered};enemy_target={enemy_target.id}:{enemy_target.atk}/{enemy_target.health};copy={enemy_copy.id}:{enemy_copy.atk}/{enemy_copy.health};copy_controller={enemy_copy.controller.name}"
    ensure(enemy_offered and not heroes_offered, enemy_observed)
    ensure(enemy_copy.id == "CS2_182" and (enemy_copy.atk, enemy_copy.health) == (4, 5) and enemy_copy.controller is player2, enemy_observed)
    outcomes.append(enemy_observed)
    return " | ".join(outcomes)


def doomhammer_windfury_attacks_and_overload_lock():
    game = new_game(CardClass.SHAMAN)
    player, opponent = game.player1, game.player2
    doomhammer = player.give("EX1_567")
    doomhammer.play()
    equipped = (player.weapon.id, player.weapon.atk, player.weapon.durability, player.hero.windfury)
    first_ready = player.hero.can_attack(opponent.hero)
    player.hero.attack(opponent.hero)
    second_ready = player.hero.can_attack(opponent.hero)
    player.hero.attack(opponent.hero)
    after_two_attacks = (opponent.hero.health, player.weapon.durability, player.hero.can_attack())
    overloaded = player.overloaded
    game.end_turn()
    game.end_turn()
    next_turn = (player.mana, player.overloaded, player.overload_locked)
    observed = f"equipped={equipped};ready={(first_ready, second_ready)};after_two_attacks={after_two_attacks};overloaded_after_play={overloaded};next_turn={next_turn}"
    ensure(equipped == ("EX1_567", 2, 8, True) and first_ready and second_ready, observed)
    ensure(after_two_attacks == (26, 6, False) and overloaded == 2, observed)
    ensure(next_turn == (8, 0, 2), observed)
    return observed


def bite_attack_and_armor_expiry():
    game = new_game(CardClass.DRUID)
    player, opponent = game.player1, game.player2
    before = (player.hero.atk, player.hero.armor, opponent.hero.health)
    bite = player.give("EX1_570")
    bite.play()
    during = (player.hero.atk, player.hero.armor, player.hero.can_attack(opponent.hero))
    player.hero.attack(opponent.hero)
    after_attack = (opponent.hero.health, player.hero.atk, player.hero.armor)
    game.end_turn()
    after_turn = (player.hero.atk, player.hero.armor)
    observed = f"before={before};during={during};after_attack={after_attack};after_turn={after_turn};spell={bite.zone.name}"
    ensure(before == (0, 0, 30) and during == (4, 4, True), observed)
    ensure(after_attack == (26, 4, 4) and after_turn == (0, 4), observed)
    return observed


def force_of_nature_summons_until_board_capacity():
    outcomes = []
    for existing_count, expected_tokens in ((0, 3), (5, 2)):
        game = new_game(CardClass.DRUID)
        player = game.player1
        for _ in range(existing_count):
            player.summon("CS2_182")
        spell = player.give("EX1_571")
        spell.play()
        treants = [minion for minion in player.field if minion.id == "EX1_tk9"]
        observed = f"existing={existing_count};field={len(player.field)};treants={[(m.atk, m.health, m.charge) for m in treants]};spell={spell.zone.name}"
        ensure(len(treants) == expected_tokens and len(player.field) == existing_count + expected_tokens, observed)
        ensure(all((m.atk, m.health) == (2, 2) for m in treants) and spell.zone == Zone.GRAVEYARD, observed)
        outcomes.append(observed)
    return " | ".join(outcomes)


def ysera_gives_dream_card_at_each_owners_end_turn():
    game = new_game(CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    ysera = player.summon("EX1_572")
    enemy_ysera = opponent.summon("EX1_572")
    game.end_turn()
    first_p1 = [card.id for card in player.hand]
    first_p2 = [card.id for card in opponent.hand]
    game.end_turn()
    second_p1 = [card.id for card in player.hand]
    second_p2 = [card.id for card in opponent.hand]
    dreams = {"DREAM_01", "DREAM_02", "DREAM_03", "DREAM_04", "DREAM_05"}
    first_p1_dreams = [card_id for card_id in first_p1 if card_id in dreams]
    first_p2_dreams = [card_id for card_id in first_p2 if card_id in dreams]
    second_p1_dreams = [card_id for card_id in second_p1 if card_id in dreams]
    second_p2_dreams = [card_id for card_id in second_p2 if card_id in dreams]
    observed = f"yseras={(ysera.zone.name, enemy_ysera.zone.name)};after_p1_end=(p1:{first_p1},p2:{first_p2});after_p2_end=(p1:{second_p1},p2:{second_p2});dreams=(p1:{second_p1_dreams},p2:{second_p2_dreams})"
    ensure(len(first_p1_dreams) == 1 and not first_p2_dreams, observed)
    ensure(len(second_p1_dreams) == 1 and len(second_p2_dreams) == 1, observed)
    return observed


def cenarius_both_choose_one_branches():
    buff_game = new_game(CardClass.DRUID)
    player = buff_game.player1
    allies = [player.summon(WISP), player.summon(WISP)]
    cenarius = player.give("EX1_573")
    cenarius.play(choose="EX1_573a")
    buff_state = [(minion.atk, minion.health) for minion in allies]
    buff_observed = f"buff_choice={buff_state};cenarius={cenarius.zone.name}:{cenarius.atk}/{cenarius.health}"
    ensure(buff_state == [(3, 3), (3, 3)] and cenarius.zone == Zone.PLAY, buff_observed)

    summon_game = new_game(CardClass.DRUID)
    player2 = summon_game.player1
    summoned_cenarius = player2.give("EX1_573")
    summoned_cenarius.play(choose="EX1_573b")
    treants = [minion for minion in player2.field if minion.id == "EX1_573t"]
    summon_observed = f"summon_choice={[(m.atk, m.health, m.taunt) for m in treants]};cenarius={summoned_cenarius.zone.name}:{summoned_cenarius.atk}/{summoned_cenarius.health}"
    ensure(len(treants) == 2 and all((m.atk, m.health, m.taunt) == (2, 2, True) for m in treants), summon_observed)
    ensure(summoned_cenarius.zone == Zone.PLAY, summon_observed)
    return f"{buff_observed} | {summon_observed}"


def mana_tide_totem_draws_for_its_controller_at_end_turn():
    game = new_game(CardClass.SHAMAN)
    player, opponent = game.player1, game.player2
    own_totem = player.summon("EX1_575")
    enemy_totem = opponent.summon("EX1_575")
    for card_id in ("CS2_182", "CS2_231"):
        player.give(card_id).put_on_top()
    for card_id in ("CS2_008", "CS2_029"):
        opponent.give(card_id).put_on_top()
    game.end_turn()
    after_p1_end = (len(player.hand), len(player.deck), len(opponent.hand), len(opponent.deck))
    p1_end_ids = [card.id for card in player.hand]
    p2_end_ids = [card.id for card in opponent.hand]
    game.end_turn()
    after_p2_end_and_p1_start = (len(player.hand), len(player.deck), len(opponent.hand), len(opponent.deck))
    p2_final_ids = [card.id for card in opponent.hand]
    p1_final_ids = [card.id for card in player.hand]
    observed = f"totems={(own_totem.zone.name, enemy_totem.zone.name)};after_p1_end={after_p1_end};p1_cards={p1_end_ids};p2_cards={p2_end_ids};after_p2_end_plus_p1_draw={after_p2_end_and_p1_start};p1_final={p1_final_ids};p2_final={p2_final_ids}"
    ensure(after_p1_end == (1, 1, 2, 1) and len(p1_end_ids) == 1, observed)
    ensure(after_p2_end_and_p1_start == (2, 0, 3, 0) and len(opponent.hand) == 3, observed)
    ensure(all(card_id in p1_final_ids for card_id in ("CS2_182", "CS2_231")), observed)
    ensure(all(card_id in p2_final_ids for card_id in ("CS2_008", "CS2_029")), observed)
    return observed


def the_beast_deathrattle_respects_opponent_board_cap():
    normal_game = new_game(CardClass.MAGE)
    player, opponent = normal_game.player1, normal_game.player2
    beast = player.give("EX1_577")
    beast.play()
    player.give("CS2_029").play(target=beast)
    player.give("CS2_008").play(target=beast)
    normal_tokens = [minion for minion in opponent.field if minion.id == "EX1_finkle"]
    normal_observed = f"empty_board=beast:{beast.zone.name};opponent_field={[(m.id,m.atk,m.health) for m in opponent.field]}"
    ensure(beast.zone == Zone.GRAVEYARD and len(normal_tokens) == 1, normal_observed)
    ensure((normal_tokens[0].atk, normal_tokens[0].health) == (3, 3), normal_observed)

    full_game = new_game(CardClass.MAGE)
    player2, opponent2 = full_game.player1, full_game.player2
    prior_minions = [opponent2.summon("CS2_182") for _ in range(7)]
    full_beast = player2.give("EX1_577")
    full_beast.play()
    player2.give("CS2_029").play(target=full_beast)
    player2.give("CS2_008").play(target=full_beast)
    full_tokens = [minion for minion in opponent2.field if minion.id == "EX1_finkle"]
    full_observed = f"full_board_before={len(prior_minions)};beast={full_beast.zone.name};opponent_field_after={len(opponent2.field)};finkles={[(m.id,m.atk,m.health) for m in full_tokens]}"
    ensure(full_beast.zone == Zone.GRAVEYARD and len(opponent2.field) == 7 and not full_tokens, f"normal={normal_observed};{full_observed}")
    return f"normal={normal_observed};{full_observed}"


PROBES = {
    "EX1_313": {"cases": [case("EX1_313_own_hero_battlecry", "Battlecry deals 5 to its controller's hero only; 5/6 body is played and 4 mana is spent.", pit_lord_hero_damage)], "complete": True,
                "reason": "己方英雄恰受5点战吼伤害，对手英雄不变；5/6本体正常入场并扣除4点法力。"},
    "EX1_315": {"cases": [case("EX1_315_minion_cost_aura_and_silence", "Friendly 4- and 2-cost minions cost 2 and 1 while Portal lives; enemy minion cost is unchanged; silence removes the aura.", summoning_portal_cost_aura)], "complete": True,
                "reason": "己方随从费用减少2且下限为1，对手费用不变；沉默 Portal 后两张手牌费用恢复。"},
    "EX1_317": {"cases": [case("EX1_317_two_demons", "Draws both Demon cards and leaves the sole non-Demon in deck.", sense_demons_two_available),
                          case("EX1_317_one_demon", "Draws the sole Demon and creates one missing-card placeholder.", sense_demons_one_available),
                          case("EX1_317_zero_demons", "With no Demon in deck, creates two placeholder cards and leaves the non-Demon in deck.", sense_demons_zero_available)], "complete": True,
                "reason": "两张、仅一张和没有恶魔的牌库分支均按数量结算；非恶魔不会被抽走。"},
    "EX1_319": {"cases": [case("EX1_319_own_hero_battlecry", "Battlecry deals 3 to its controller's hero only; 3/2 body is played and 1 mana is spent.", flame_imp_hero_damage)], "complete": True,
                "reason": "己方英雄恰受3点战吼伤害，对手英雄不变；3/2本体正常入场并扣除1点法力。"},
    "EX1_320": {"cases": [case("EX1_320_lethal_summon", "A lethal 2 damage hit destroys the minion and summons a random Demon.", bane_of_doom_lethal),
                          case("EX1_320_nonlethal_no_summon", "A nonlethal 2 damage hit leaves the minion in play and summons no Demon.", bane_of_doom_nonlethal)], "complete": True,
                "reason": "致死分支消灭目标并召唤恶魔；非致死分支只造成2点伤害。"},
    "EX1_323": {"cases": [case("EX1_323_hero_replacement_and_weapon", "Jaraxxus replaces the hero at 15 health, grants its hero power, and equips a 3/8 weapon.", lord_jaraxxus_transforms_hero)], "complete": True,
                "reason": "战吼将英雄替换为15生命的加拉克苏斯大王，并赋予对应技能和3/8武器。"},
    "EX1_334": {"cases": [case("EX1_334_control_charge_and_return", "A legal enemy minion gains temporary control and Charge, attacks, and returns to its owner at end of turn.", shadow_madness_temporary_control_and_charge),
                          case("EX1_334_reject_over_three_attack", "A 4-Attack enemy minion is not offered as a target and cannot be taken; no mana or zone changes.", shadow_madness_rejects_over_attack_limit)], "complete": True,
                "reason": "3攻合法随从获得临时控制与冲锋、攻击后回归；4攻目标不合法且不扣费、不移区。"},
    "EX1_335": {"cases": [case("EX1_335_attack_equals_current_health", "Lightspawn's Attack equals Health initially and after taking damage.", lightspawn_attack_tracks_health)], "complete": True,
                "reason": "光耀之子初始攻击力等于生命值；受到1点实际法术伤害后两者仍相等。"},
    "EX1_339": {"cases": [case("EX1_339_copy_two_opponent_deck_cards", "Copies both known opponent deck cards into the caster's hand while leaving the opponent's originals in deck.", thoughtsteal_copies_known_opponent_cards)], "complete": True,
                "reason": "将对手牌库中两张已知卡牌的副本加入己方手牌；原牌仍留在对手牌库。"},
    "EX1_341": {"cases": [case("EX1_341_heal_at_own_turn_start", "Lightwell heals the only damaged friendly character by 3 at its controller's turn start, not during the opponent's turn.", lightwell_heals_single_damaged_friendly_at_start),
                          case("EX1_341_random_heal_one_reachable_candidate", "With two damaged friendly minions, heals exactly one by 3; deterministic seeded runs can select either candidate.", lightwell_random_heal_selects_one_and_reaches_both)], "complete": True,
                "reason": "己方回合开始時治疗唯一受伤角色；两名受伤随从候选时仅治疗一名且不同随机种子可触达两者。"},
    "EX1_345": {"cases": [case("EX1_345_known_minion_copy_and_empty_pool_token", "Copies the only minion in the opponent's deck onto the friendly board; with no enemy minion card, summons Shadow of Nothing.", mindgames_known_random_minion_and_empty_minion_pool)], "complete": True,
                "reason": "复制对手牌库中唯一随从并置入己方场上；没有敌方随从牌时召唤“虚无之影”。"},
    "EX1_354": {"cases": [case("EX1_354_eight_healing_and_three_draws", "Restores 8 to the selected friendly hero and draws three known cards.", lay_on_hands_heals_and_draws_three_known_cards),
                          case("EX1_354_friendly_minion_target", "Offers and heals a friendly minion, while drawing three cards.", lay_on_hands_heals_friendly_minion_target),
                          case("EX1_354_enemy_minion_target", "Offers and heals an enemy minion, while drawing three cards.", lay_on_hands_heals_enemy_minion_target)], "complete": True,
                "reason": "友方英雄、友方随从及敌方随从目标均可恢复生命，同时抽三张牌。"},
    "EX1_355": {"cases": [case("EX1_355_doubles_friendly_minion_attack", "Doubles a friendly minion's Attack without changing its Health.", blessed_champion_doubles_attack),
                          case("EX1_355_doubles_enemy_minion_attack", "Doubles an enemy minion's Attack without changing its Health.", blessed_champion_doubles_enemy_minion_attack)], "complete": True,
                "reason": "友方与敌方随从均可成为目标；目标攻击力翻倍且生命值不变。"},
    "EX1_362": {"cases": [case("EX1_362_divine_shield_and_optional_target", "Gives a friendly minion Divine Shield; with no friendly minions, Protector remains playable without a target.", argent_protector_shield_with_and_without_target),
                          case("EX1_362_shield_blocks_attack", "An incoming minion attack removes the granted shield and deals no damage to its bearer.", argent_protector_shield_absorbs_attack)], "complete": True,
                "reason": "目标友方随从获得圣盾，圣盾实际抵挡攻击且不损失生命；场上无友军时无目标正常入场。"},
    "EX1_363": {"cases": [case("EX1_363_friendly_attacker_draws", "A friendly enchanted minion's attack draws one known card for the caster.", blessing_of_wisdom_friendly_attacker_draws),
                          case("EX1_363_enemy_attacker_draw_owner", "An enemy enchanted minion's attack still draws for the caster, without consuming the opponent's deck.", blessing_of_wisdom_enemy_attacker_draw_owner)], "complete": True,
                "reason": "友方随从攻击后抽牌；附魔敌方随从并由其攻击时，抽牌归施法者且不消耗对手牌库。"},
    "EX1_365": {"cases": [case("EX1_365_draw_cost_and_damage", "Draws the known 4-cost card and deals exactly 4 damage to the selected enemy minion.", holy_wrath_drawn_card_cost_damage)], "complete": True,
                "reason": "先抽取已知4费牌，再对目标造成等于该牌费用的4点伤害。"},
    "EX1_366": {"cases": [case("EX1_366_buffs_new_summons_and_loses_durability", "Each minion summoned after the weapon is equipped gains +1/+1 and costs one durability; an existing minion is unchanged.", sword_of_justice_buffs_each_new_summon)], "complete": True,
                "reason": "武器装备后每次召唤令新随从获得+1/+1并消耗1耐久；已在场随从不受影响。"},
    "EX1_379": {"cases": [case("EX1_379_reduces_enemy_minion_health_to_one", "After the opponent plays a minion, Repentance reveals and reduces its Health to 1.", repentance_reduces_played_enemy_minion_to_one_health)], "complete": True,
                "reason": "对手打出随从后奥秘揭示，使该随从当前生命值降为1。"},
    "EX1_382": {"cases": [case("EX1_382_sets_enemy_attack_to_one", "Aldor Peacekeeper changes an enemy minion's Attack to 1 and preserves its Health and controller.", aldor_sets_enemy_attack_to_one)], "complete": True,
                "reason": "敌方随从攻击力改为1，生命值、区域和控制者保持不变。"},
    "EX1_383": {"cases": [case("EX1_383_shield_taunt_and_ashbringer_deathrattle", "Tirion has Divine Shield and Taunt; the shield blocks one hit, a second kills it, and its Deathrattle equips 5/3 Ashbringer.", tirion_shield_taunt_and_deathrattle_weapon)], "complete": True,
                "reason": "弗丁拥有圣盾和嘲讽；圣盾挡住首次伤害，死亡后装备5/3灰烬使者。"},
    "EX1_384": {"cases": [case("EX1_384_eight_damage_enemy_only", "Eight random 1-damage hits total exactly 8 across enemy characters; friendly characters take none.", avenging_wrath_hits_only_enemies_for_eight)], "complete": True,
                "reason": "8次随机伤害合计正好8点，范围仅限敌方角色，友方随从与英雄不受伤。"},
    "EX1_390": {"cases": [case("EX1_390_taunt_and_enrage_lifecycle", "Tauren Warrior has Taunt, gains +3 Attack while damaged, and loses the Enrage bonus when fully healed.", tauren_warrior_taunt_and_enrage)], "complete": True,
                "reason": "牛头人战士具有嘲讽；受伤时攻击力+3，恢复满血后增益消失。"},
    "EX1_391": {"cases": [case("EX1_391_survivor_draws", "A minion that survives 2 damage remains in play and causes one known-card draw.", slam_survivor_draws),
                          case("EX1_391_kill_skips_draw", "A minion killed by 2 damage does not cause a draw.", slam_kill_does_not_draw)], "complete": True,
                "reason": "2点伤害的存活分支抽1张；致死分支不抽牌。"},
    "EX1_392": {"cases": [case("EX1_392_draw_per_damaged_friendly_character", "Draws exactly once for each damaged friendly character (hero and one minion), ignores an undamaged minion, and leaves the opponent's deck unchanged.", battle_rage_counts_damaged_friendly_characters)], "complete": True,
                "reason": "每名受伤友方角色各抽一张；未受伤随从不计入，抽牌来自己方牌库而对手牌库不变。"},
    "EX1_393": {"cases": [case("EX1_393_enrage_gains_and_loses_attack", "Amani Berserker gains +3 Attack while damaged and loses it when healed to full.", amani_enrage_gains_and_loses_attack)], "complete": True,
                "reason": "阿曼尼狂战士受伤时攻击力+3，恢复满血后回到原攻击力。"},
    "EX1_396": {"cases": [case("EX1_396_taunt_blocks_hero", "Mogu'shan Warden has Taunt; a Charge minion cannot attack the hero and is forced to attack it.", mogu_shan_warden_taunt_blocks_hero)], "complete": True,
                "reason": "魔古山守望者嘲讽迫使冲锋随从攻击它，阻止其攻击英雄。"},
    "EX1_398": {"cases": [case("EX1_398_battlecry_equips_two_two", "Arathi Weaponsmith enters play and equips a 2/2 weapon.", arathi_weaponsmith_equips_two_two)], "complete": True,
                "reason": "阿拉希武器匠战吼装备2/2武器，本体正常入场。"},
    "EX1_402": {"cases": [case("EX1_402_armor_per_friendly_damage_event", "Armorsmith grants one Armor for each friendly minion damaged by Whirlwind, including itself.", armorsmith_counts_friendly_damage_events)], "complete": True,
                "reason": "旋风斩使铸甲师与另一友方随从各受伤时，护甲增加2点；死亡随从的受伤事件也计入。"},
    "EX1_405": {"cases": [case("EX1_405_taunt_blocks_charge_attack", "Shieldbearer's Taunt prevents a Charge attacker from attacking the hero and redirects the attack to it.", shieldbearer_taunt_blocks_charge_attack)], "complete": True,
                "reason": "持盾卫士嘲讽阻止冲锋随从攻击英雄，并迫使其攻击嘲讽随从。"},
    "EX1_407": {"cases": [case("EX1_407_random_survivor_and_batch_deathrattle", "Brawl leaves exactly one of three candidates; a minion already destroyed in the same Brawl resolution is not returned by Anub'ar Ambusher's Deathrattle.", brawl_random_survivor_and_same_batch_deathrattle)], "complete": True,
                "reason": "绝命乱斗随机保留一个随从，其余随从死亡；同一处理中的亡语不得把已被消灭的友方随从救回手牌。",
                "failure_reason": "乱斗留在场上的敌方随从仍存活时，阿努巴拉克伏兵的亡语却把同批被乱斗摧毁的友方随从带回手牌。"},
    "EX1_408": {"cases": [case("EX1_408_four_or_six_damage_threshold", "Deals 4 damage at 30 friendly Health and 6 damage at the exact 12-Health threshold.", mortal_strike_damage_thresholds)], "complete": True,
                "reason": "己方生命值30时造成4点伤害，恰为12时造成6点伤害。"},
    "EX1_409": {"cases": [case("EX1_409_weapon_and_no_weapon_branches", "Without a weapon, equips 1/3; with a weapon, grants +1 Attack and +1 Durability.", upgrade_weapon_and_no_weapon_branches)], "complete": True,
                "reason": "无武器时装备1/3武器；已有武器时攻击力和耐久各增加1。"},
    "EX1_410": {"cases": [case("EX1_410_damage_equals_armor", "With 5 Armor, Shield Slam deals exactly 5 damage to the selected minion.", shield_slam_damage_scales_with_armor)], "complete": True,
                "reason": "以盾牌格挡获得5点护甲后，盾牌猛击对目标造成5点伤害。"},
    "EX1_411": {"cases": [case("EX1_411_minion_attack_reduces_attack_not_durability", "Attacking a minion reduces Gorehowl Attack by 1 while preserving Durability; attacking a hero then consumes its final Durability.", gorehowl_minion_attack_costs_attack_not_durability)], "complete": True,
                "reason": "攻随从后血吼攻击力减1但耐久不变；随后攻击英雄才消耗最后1点耐久。"},
    "EX1_412": {"cases": [case("EX1_412_damaged_worgen_gets_windfury", "Damage grants +1 Attack and Windfury; the minion attacks twice on its next turn and then cannot attack again that turn.", raging_worgen_enrage_grants_windfury_attacks)], "complete": True,
                "reason": "暴怒的狼人受伤后获得+1攻击和风怒；下一回合实际攻击两次后耗尽攻击次数。"},
    "EX1_414": {"cases": [case("EX1_414_charge_and_damaged_attack", "Grommash has Charge, gains +6 Attack while damaged, attacks immediately, and loses the bonus when healed.", grommash_charge_and_enrage_attack)], "complete": True,
                "reason": "格罗玛什具有冲锋；受伤后攻击力+6并立即攻击，恢复满血后攻击力增益消失。"},
    "EX1_507": {"cases": [case("EX1_507_other_friendly_murlocs_only", "Other friendly Murlocs gain +2 Attack; the Warleader itself and enemy Murlocs do not; silence removes the aura.", murloc_warleader_buffs_only_other_friendly_murlocs)], "complete": True,
                "reason": "仅其他友方鱼人获得+2攻击；领军自身和敌方鱼人不变，沉默后光环移除。"},
    "EX1_509": {"cases": [case("EX1_509_friendly_murloc_summons_only", "Tidecaller gains +1 Attack for its own summon and another friendly Murloc summon, but not for an enemy Murloc.", murloc_tidecaller_gains_from_own_summons_only)], "complete": True,
                "reason": "鱼人招潮者自身与后续友方鱼人召唤均使其+1攻击；敌方鱼人召唤不触发。",
                "failure_reason": "对手在自己的回合合法打出鱼人后，鱼人招潮者仍额外获得+1攻击，触发范围超出文本的‘你召唤’。"},
    "EX1_522": {"cases": [case("EX1_522_stealth_poisonous_trade", "Patient Assassin starts Stealthed and Poisonous; after becoming ready it trades into a 4/5 minion and destroys it despite dealing only 1 damage.", patient_assassin_stealth_poisonous_attack)], "complete": True,
                "reason": "耐心的刺客初始潜行且剧毒；准备就绪后仅造成1点战斗伤害也能消灭4/5随从。"},
    "EX1_531": {"cases": [case("EX1_531_friendly_beast_death_only", "A friendly Beast death grants +2/+1; an enemy Beast death grants no additional stats.", scavenging_hyena_counts_friendly_beast_deaths_only)], "complete": True,
                "reason": "友方野兽死亡使土狼获得+2/+1；敌方野兽死亡不触发。"},
    "EX1_533": {"cases": [case("EX1_533_attack_redirects_to_only_other_character", "When a minion attacks the hero with Misdirection active and the opponent hero is the only other legal character, the attack is redirected to that hero and the secret is consumed.", misdirection_redirects_attack_to_other_character)], "complete": True,
                "reason": "敌方冲锋随从攻击英雄时，唯一可重定向目标是攻击者自己的英雄；原英雄不受伤且 Misdirection 消耗。"},
    "EX1_534": {"cases": [case("EX1_534_death_summons_two_hyenas", "Playing and killing Savannah Highmane summons exactly two friendly 2/2 Hyenas.", savannah_highmane_summons_two_hyenas_on_death)], "complete": True,
                "reason": "6/5 Savannah Highmane 被火球术击杀后进入墓地，并召唤两只友方2/2土狼。"},
    "EX1_536": {"cases": [case("EX1_536_only_friendly_secret_reveal_adds_durability", "A friendly Ice Barrier reveal increases Eaglehorn Bow durability from 2 to 3; revealing the opponent's Ice Barrier leaves it at 2.", eaglehorn_bow_gains_durability_only_from_friendly_secret)], "complete": True,
                "reason": "友方冰箱奥秘揭示使鹰角弓耐久从2增至3；敌方奥秘揭示不增加耐久。"},
    "EX1_537": {"cases": [case("EX1_537_target_and_adjacent_damage", "Explosive Shot deals 5 to its chosen 8/8 target, 2 to the immediate neighbor on each side, and none to a farther minion.", explosive_shot_hits_target_and_adjacent_minions)], "complete": True,
                "reason": "目标大个随从受5伤，左右相邻各受2伤，更远的随从不受伤。"},
    "EX1_538": {"cases": [case("EX1_538_enemy_count_requirement_and_charge", "With no enemy minions Unleash is unplayable and spends no mana; with two enemy minions it summons two 1/1 Charge Hounds that can attack immediately.", unleash_the_hounds_counts_enemy_minions_and_charge_attacks)], "complete": True,
                "reason": "敌方无随从时卡牌因前置条件不可打出且不耗法力；敌方有两随从时召唤两只可立即攻击的1/1冲锋猎犬。"},
    "EX1_543": {"cases": [case("EX1_543_charge_immediate_attack", "King Krush enters as an 8/8 with Charge and immediately attacks the opposing hero for 8.", king_krush_charge_allows_immediate_attack)], "complete": True,
                "reason": "暴龙王以8/8冲锋入场并在当回合攻击敌方英雄造成8点伤害，消耗9点法力。"},
    "EX1_544": {"cases": [case("EX1_544_global_stealth_enemy_secrets_and_draw", "Flare removes Stealth from friendly and enemy minions, destroys two enemy Secrets but preserves a friendly Secret, and draws the second known card after the turn-start draw.", flare_removes_stealth_and_enemy_secrets_then_draws)], "complete": True,
                "reason": "照明弹同时移除双方随从潜行、摧毁两张敌方奥秘但保留己方奥秘，并在抽牌阶段后再抽一张已知牌。"},
    "EX1_549": {"cases": [case("EX1_549_beast_attack_immune_and_expiry", "Bestial Wrath gives a friendly Beast +2 Attack and Immune for the turn; its attack harms the enemy without retaliation damage, then both effects expire.", bestial_wrath_grants_attack_and_turn_immune)], "complete": True,
                "reason": "友方野兽获得+2攻击并以免疫状态攻击敵方隨從而不受反擊傷害；回合结束后攻击和免疫均消失。"},
    "EX1_554": {"cases": [case("EX1_554_attacked_minion_only", "Snake Trap summons three 1/1 Snakes when a friendly minion is attacked, while an attack on the friendly hero leaves it armed.", snake_trap_only_triggers_when_friendly_minion_is_attacked)], "complete": True,
                "reason": "友方随从被攻击时召唤三条1/1蛇；仅攻击英雄不会触发，奥秘继续待命。"},
    "EX1_556": {"cases": [case("EX1_556_death_summons_damaged_golem", "Killing the 2/3 Harvest Golem summons one 2/1 Damaged Golem.", harvest_golem_deathrattle_summons_damaged_golem)], "complete": True,
                "reason": "2/3收割傀儡受三次真实法术伤害死亡后召唤一个2/1受损傀儡。"},
    "EX1_557": {"cases": [case("EX1_557_seeded_extra_draw_branches", "Across deterministic seeds, Nat Pagle's controller draws the normal start-turn card and reaches both the no-extra-draw and one-extra-draw outcomes.", nat_pagle_has_both_seeded_start_turn_draw_outcomes)], "complete": True,
                "reason": "固定随机种子分别实测到纳特·帕格回合开始时正常抽1张和额外抽1张的两种分支。"},
    "EX1_558": {"cases": [case("EX1_558_weapon_durability_draw_and_no_weapon", "Harrison destroys an opponent's 1/4 weapon and draws four cards after the normal turn-start draw; with no enemy weapon it draws none.", harrison_jones_draws_opponent_weapon_durability)], "complete": True,
                "reason": "摧毁敌方1/4武器后按耐久抽4张（另计回合开始自然抽牌）；无敌方武器时不抽牌。"},
    "EX1_559": {"cases": [case("EX1_559_hand_cast_spell_adds_fireball", "Each of two spells cast from hand while Antonidas is on board adds one Fireball to hand.", antonidas_adds_fireball_for_each_hand_cast_spell)], "complete": False,
                "reason": "两次从手牌施放法术各生成一张火球术；直接由效果 CastSpell 而非从手牌施放的事件分支仍未验证（CAST-001）。"},
    "EX1_560": {"cases": [case("EX1_560_timeout_state_for_both_players", "Nozdormu's declared timeout refresh should set both serialized Player.timeout values from 75 to 15 and silence should restore 75.", nozdormu_timeout_refresh_is_not_visible_on_players)], "complete": False,
                "reason": "源码声明双方 timeout=15，但入场后序列化的 Player.timeout 仍为75；TIMEOUT aura 仅留在 slot 中，未影响玩家可见状态，限时效果未生效。",
                "failure_reason": "打出并保留诺兹多姆时双方序列化 timeout 都仍为75，源码声明的TIMEOUT aura没有生效。"},
    "EX1_561": {"cases": [case("EX1_561_friendly_and_enemy_hero_to_15", "Alexstrasza can target either hero: a friendly hero at 8 and an enemy hero at 22 are each set to 15 while both max-health values remain 30.", alexstrasza_sets_either_hero_to_15_from_above_or_below)], "complete": True,
                "reason": "阿莱克丝塔萨可指定任一英雄：友方8血与敌方22血均被设为15，双方最大生命值保持30。"},
    "EX1_562": {"cases": [case("EX1_562_fills_remaining_friendly_slots", "Onyxia leaves the controller's board at exactly seven minions and creates six, one, or zero Whelps with zero, five, or six preexisting minions.", onyxia_fills_only_available_friendly_slots)], "complete": True,
                "reason": "已有0/5/6个友方随从时，奥妮克希亚分别补6/1/0只1/1雏龙，己方场面恰好填至7个。"},
    "EX1_563": {"cases": [case("EX1_563_spell_damage_and_silence", "Malygos makes Moonfire deal 6 damage; after Malygos is silenced the same spell deals 1.", malygos_spell_damage_and_silence)], "complete": True,
                "reason": "玛里苟斯使月火术伤害由1变6；沉默后法术伤害回到1。",
                "failure_reason": "沉默标记已生效但玛里苟斯的法术伤害仍为+5，月火术继续造成6点；独立的科布尔地精也在沉默后保留+1法强。"},
    "EX1_564": {"cases": [case("EX1_564_copies_friendly_buffed_and_enemy_minion", "Faceless can target a friendly buffed/damaged minion and an enemy minion, copies current stats and Taunt, and does not offer heroes.", faceless_manipulator_copies_friendly_and_enemy_minions)], "complete": True,
                "reason": "无面操纵者可选择友方受伤且有嘲讽增益的随从或敌方随从，复制其当前攻防及嘲讽；英雄不在目标列表。"},
    "EX1_567": {"cases": [case("EX1_567_two_attacks_and_overload", "Doomhammer grants Windfury for two actual hero attacks, loses two Durability, and leaves two mana locked next turn.", doomhammer_windfury_attacks_and_overload_lock)], "complete": True,
                "reason": "毁灭之锤本回合实际攻击两次后耐久8→6，英雄不能再攻；过载2使下回合锁定2点法力。"},
    "EX1_570": {"cases": [case("EX1_570_attack_and_armor_expiry", "Bite gives the hero +4 Attack and 4 Armor, permits a 4-damage attack, and expires only the Attack at turn end.", bite_attack_and_armor_expiry)], "complete": True,
                "reason": "撕咬使英雄获得4攻击和4护甲并实际造成4点攻击伤害；回合结束攻击归零，护甲保留。"},
    "EX1_571": {"cases": [case("EX1_571_summon_to_board_capacity", "Force of Nature summons three 2/2 Treants on an empty board and two with five existing minions, filling the board without exceeding seven.", force_of_nature_summons_until_board_capacity)], "complete": True,
                "reason": "自然之力在空场召唤3个2/2树人；已有5个友方随从时只补2个至场面上限。"},
    "EX1_572": {"cases": [case("EX1_572_each_controller_gets_dream_on_own_end_turn", "Each Ysera grants its controller one Dream card at that controller's own end turn and does not grant one to the other player.", ysera_gives_dream_card_at_each_owners_end_turn)], "complete": True,
                "reason": "双方各自的伊瑟拉仅在其控制者回合结束时加入一张梦境牌，另一方回合结束不会触发。"},
    "EX1_573": {"cases": [case("EX1_573_both_choose_one_options", "The buff choice gives other friendly minions +2/+2 without buffing Cenarius; the other choice summons two 2/2 Taunt Treants.", cenarius_both_choose_one_branches)], "complete": True,
                "reason": "抉择两分支均实测：友方其他随从+2/+2（不增强塞纳留斯），或召唤两只2/2嘲讽树人。"},
    "EX1_575": {"cases": [case("EX1_575_controller_end_turn_draw", "Each player's Mana Tide Totem draws from its controller's deck at that controller's end turn; the other player's Totem does not cross-draw.", mana_tide_totem_draws_for_its_controller_at_end_turn)], "complete": True,
                "reason": "双方潮汐图腾在各自控制者回合结束时只从本方牌库抽牌；另一方图腾不会跨玩家抽牌。"},
    "EX1_577": {"cases": [case("EX1_577_normal_and_full_opponent_board", "The Beast's death summons one 3/3 Finkle Einhorn on an open enemy board, but must not create an eighth enemy minion when that board already has seven.", the_beast_deathrattle_respects_opponent_board_cap)], "complete": True,
                "reason": "空场时野兽亡语正常召唤敌方3/3芬克·恩霍尔；敌方已满7个随从时不得突破上限。",
                "failure_reason": "芬克·恩霍尔正常召唤分支通过，但敌方满7场死亡时仍被召唤，场面增至8个随从。"},
}


def read_existing(path, key_fields):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {tuple(row[key] for key in key_fields): row for row in csv.DictReader(stream)}


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    roster = classic_yellow_second_half()
    old_probes = read_existing(PROBE_OUT, ["card_id", "case_id"])
    old_verdicts = read_existing(VERDICT_OUT, ["card_id"])
    order = {row["card_id"]: i for i, row in enumerate(roster)}

    for row in roster:
        card_id = row["card_id"]
        plan = PROBES.get(card_id)
        if not plan:
            continue
        en, zh = localized_text(card_id)
        case_rows = []
        status = "GREEN" if plan["complete"] else "YELLOW"
        reason = plan["reason"]
        for spec in plan["cases"]:
            try:
                observed = spec["probe"]()
                outcome = "pass"
            except ProbeMismatch as error:
                observed = str(error)
                outcome = "confirmed_error"
                status = "RED"
                reason = f"{plan.get('failure_reason', '核心效果断言失败')} 实测：{observed}"
            except Exception as error:
                observed = f"{type(error).__name__}: {error}"
                outcome = "inconclusive"
                if status != "RED":
                    status = "YELLOW"
                    reason = f"运行时/夹具异常，无法裁定核心效果：{observed}"
            case_rows.append({
                "card_id": card_id,
                "case_id": spec["case_id"],
                "expected": spec["expected"],
                "observed": observed,
                "outcome": outcome,
                "notes": f"CardDefs.xml enUS={en}; zhCN={zh}",
            })
        for key in [key for key in old_probes if key[0] == card_id]:
            del old_probes[key]
        for result in case_rows:
            old_probes[(result["card_id"], result["case_id"])] = result
        old_verdicts[(card_id,)] = {
            "card_id": card_id,
            "status": status,
            "mechanic_scope": row["mechanic"],
            "reason": reason,
            "probe_file": PROBE_OUT.name,
            "notes": plan.get("notes", "逐卡实际出牌与状态断言；状态仅依据本卡已列核心分支。"),
        }
        probe_rows = sorted(old_probes.values(), key=lambda item: (order.get(item["card_id"], 9999), item["case_id"]))
        verdict_rows = sorted(old_verdicts.values(), key=lambda item: order.get(item["card_id"], 9999))
        write_csv(PROBE_OUT, PROBE_FIELDS, probe_rows)
        write_csv(VERDICT_OUT, VERDICT_FIELDS, verdict_rows)
        print(f"{card_id}: {status} {case_rows[-1]['observed']}", flush=True)


if __name__ == "__main__":
    main()
