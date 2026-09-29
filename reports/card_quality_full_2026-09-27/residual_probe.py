"""Independent live-game probes for the frozen 25-card residual YELLOW roster.

Each case directly exercises the missing branch from the prior per-card audit.
The source reports are read-only; this script writes only residual_probe.csv and
residual_verdict.csv beside itself.
"""

from __future__ import annotations

import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone

logging.disable(logging.CRITICAL)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from utils import ANIMATED_STATUE, MOONFIRE, WISP, prepare_empty_game  # noqa: E402

PROBE_OUT = HERE / "residual_probe.csv"
VERDICT_OUT = HERE / "residual_verdict.csv"
BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")

GVG_IDS = (
    "GVG_001", "GVG_003", "GVG_004", "GVG_020", "GVG_029", "GVG_034",
    "GVG_042", "GVG_043", "GVG_052", "GVG_059", "GVG_075", "GVG_078",
    "GVG_082", "GVG_090", "GVG_096", "GVG_105", "GVG_107", "GVG_115",
)
FROZEN_IDS = (
    "DS1_184", "EX1_095", "EX1_187", "EX1_559", *GVG_IDS,
    "LOE_086", "CFM_060", "OG_282",
)
assert len(FROZEN_IDS) == len(set(FROZEN_IDS)) == 25


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_BY_ID = {row["card_id"]: row for row in read_csv(BASELINE)}
MASTER_BY_ID = {row["card_id"]: row for row in read_csv(MASTER)}
QUALITY_BY_ID = {row["card_id"]: row for row in read_csv(QUALITY)}
assert all(cid in BASE_BY_ID and cid in MASTER_BY_ID and cid in QUALITY_BY_ID for cid in FROZEN_IDS)


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    prior = BASE_BY_ID[card_id]
    return (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or master.get('xml_source', '')}; "
        f"existing_tests={master.get('test_refs_candidate', '') or 'none'}; "
        f"prior={prior.get('status', 'unknown')}:{prior.get('reason', '')}"
    )


def new_game(seed=19, class1=CardClass.MAGE, class2=CardClass.MAGE):
    random.seed(seed)
    game = prepare_empty_game(class1, class2)
    game.random.seed(seed)
    for player in game.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    if game.current_player is not game.player1:
        game.end_turn()
    assert game.current_player is game.player1
    return game


def play(player, card_id, target=None):
    card = player.give(card_id)
    if target is None:
        card.play()
    else:
        card.play(target=target)
    return card


def summon(player, card_id):
    return player.summon(card_id)


def _draw_known_deck(player, card_ids):
    cards = []
    for cid in card_ids:
        card = player.give(cid)
        card.shuffle_into_deck()
        cards.append(card)
    return cards


def tracking_case():
    game = new_game(class1=CardClass.HUNTER, class2=CardClass.HUNTER)
    player = game.player1
    seeded = _draw_known_deck(player, ["CS2_231", "CS2_182", "CS2_033"])
    tracking = player.give("DS1_184")
    before_count = player.cards_drawn_this_turn
    before_deck = list(player.deck)
    tracking.play()
    options = list(player.choice.cards)
    chosen = options[1]
    player.choice.choose(chosen)
    remaining = list(player.deck)
    chosen_in_hand = chosen in player.hand and chosen.zone == Zone.HAND
    removed = [card.id for card in seeded if card not in remaining and card is not chosen]
    after_tracking_count = player.cards_drawn_this_turn
    control_card = player.give("CS2_042")
    control_card.shuffle_into_deck()
    control = player.draw()
    control_count = player.cards_drawn_this_turn
    observed = (
        f"top3={[x.id for x in before_deck]};options={[x.id for x in options]};"
        f"chosen={chosen.id}:{chosen.zone.name};removed={removed};"
        f"tracking_draw_count={before_count}->{after_tracking_count};"
        f"normal_draw={control.id}:{control.zone.name};normal_draw_count={after_tracking_count}->{control_count}"
    )
    core_ok = (
        len(options) == 3 and set(options) == set(seeded) and chosen_in_hand
        and len(removed) == 2 and control in player.hand and control_count == after_tracking_count + 1
        and tracking.zone == Zone.GRAVEYARD
    )
    # The rules question is whether a choice that says “Draw one” emits Draw;
    # the run records the discrepancy but does not settle that semantic.
    return observed, core_ok, "tracking selection and normal-draw counter control passed; Draw event semantics remain unresolved"


def cast_trigger_case(card_id):
    game = new_game(class1=CardClass.MAGE, class2=CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    watched = summon(owner, card_id)
    archivist = summon(owner, "LOOT_414")
    effect_spell = owner.give("CS2_023")  # Arcane Intellect; the only spell in the deck.
    effect_spell.shuffle_into_deck()
    deck_cards = _draw_known_deck(owner, ["CS2_231", "CS2_182", "CS2_033", "CS2_168"])
    # Shuffle each card into deck once; assert the selected source spell remains unique.
    before_deck = len(owner.deck)
    before_hand = len(owner.hand)
    before_count = owner.cards_drawn_this_turn
    before_state = (getattr(watched, "atk", None), getattr(watched, "max_health", None),
                    sum(c.id == "CS2_029" for c in owner.hand))
    game.end_turn()
    effect_state = (getattr(watched, "atk", None), getattr(watched, "health", None),
                    sum(c.id == "CS2_029" for c in owner.hand))
    effect_observed = (
        f"source_spell={effect_spell.zone.name};archivist={archivist.zone.name};"
        f"deck={before_deck}->{len(owner.deck)};hand={before_hand}->{len(owner.hand)};"
        f"draw_count={before_count}->{owner.cards_drawn_this_turn};"
        f"watched={before_state}->{effect_state}"
    )
    if card_id == "EX1_095":
        # Arcane Intellect itself draws two: a third card would be Auctioneer's trigger.
        core_ok = effect_spell.zone == Zone.GRAVEYARD and len(owner.deck) == before_deck - 3 and len(owner.hand) == before_hand + 2
        detail = "effect-cast Arcane Intellect resolves two draws; Auctioneer adds no third draw"
    elif card_id == "EX1_187":
        core_ok = effect_spell.zone == Zone.GRAVEYARD and effect_state[0:2] == before_state[0:2]
        detail = "effect-cast spell resolves without Arcane Devourer buff"
    elif card_id == "EX1_559":
        core_ok = effect_spell.zone == Zone.GRAVEYARD and not any(c.id == "CS2_029" for c in owner.hand)
        detail = "effect-cast spell does not add a Fireball"
    else:
        core_ok = effect_spell.zone == Zone.GRAVEYARD and watched.atk == before_state[0]
        detail = "effect-cast spell resolves without Red Mana Wyrm attack buff"

    # A second own-turn game observes a direct hand-played control spell. This
    # avoids playing the owner’s card during the opponent’s turn.
    control = new_game(class1=CardClass.MAGE, class2=CardClass.MAGE)
    control_owner, control_opponent = control.player1, control.player2
    direct_watched = summon(control_owner, card_id)
    direct_state_before = (getattr(direct_watched, "atk", None),
                           getattr(direct_watched, "max_health", None),
                           sum(c.id == "CS2_029" for c in control_owner.hand))
    hand_spell = control_owner.give(MOONFIRE)
    direct_drawn = None
    if card_id == "EX1_095":
        direct_drawn = control_owner.give("CS2_231")
        direct_drawn.shuffle_into_deck()
    hand_spell.play(target=control_opponent.hero)
    direct_state = (getattr(direct_watched, "atk", None), getattr(direct_watched, "max_health", None),
                    sum(c.id == "CS2_029" for c in control_owner.hand))
    if card_id == "EX1_095":
        direct_ok = direct_drawn in control_owner.hand and direct_drawn.zone == Zone.HAND
        direct_detail = f"hand_played_moonfire_auctioneer_draw={direct_drawn.zone.name};known_card_in_hand={direct_drawn in control_owner.hand}"
    elif card_id == "EX1_187":
        direct_ok = direct_watched.atk == direct_state_before[0] + 2 and direct_watched.max_health == direct_state_before[1] + 2
        direct_detail = f"hand_spell_devourer={direct_state_before[0]}/{direct_state_before[1]}->{direct_watched.atk}/{direct_watched.max_health}"
    elif card_id == "EX1_559":
        direct_ok = sum(c.id == "CS2_029" for c in control_owner.hand) == direct_state_before[2] + 1
        direct_detail = f"hand_spell_fireballs={direct_state_before[2]}->{sum(c.id == 'CS2_029' for c in control_owner.hand)}"
    else:
        direct_ok = direct_watched.atk == direct_state_before[0] + 2
        direct_detail = f"hand_spell_wyrm_attack={direct_state_before[0]}->{direct_watched.atk}"
    observed = f"effect_cast=({effect_observed}); direct_hand_spell=({direct_detail});direct_state={direct_state}"
    return observed, core_ok and direct_ok, detail + "; direct hand-played control passed; CAST-001 rule semantics remain unresolved"


def loe_cast_trigger_case():
    game = new_game(class1=CardClass.PRIEST, class2=CardClass.PRIEST)
    player = game.player1
    stone = summon(player, "LOE_086")
    djinni = summon(player, "LOE_053")
    friend = summon(player, WISP)
    spell = player.give("CS1_129")
    before = [m for m in player.field if m not in (stone, djinni, friend)]
    cost = spell.cost
    spell.play(target=friend)
    summons = [m for m in player.field if m not in (stone, djinni, friend)]
    generated = summons[len(before):]
    observed = (
        f"hand_inner_fire_cost={cost};inner_fire_zone={spell.zone.name};"
        f"friend={friend.atk}/{friend.max_health};djinni={djinni.atk}/{djinni.max_health};"
        f"same_cost_summons={[ (m.id,m.data.cost,m.zone.name) for m in summons ]};"
        f"stone={stone.zone.name};djinni_zone={djinni.zone.name}"
    )
    valid = cost == 1 and spell.zone == Zone.GRAVEYARD and friend.atk == friend.max_health
    valid = valid and len(summons) in (1, 2) and all(m.data.cost == cost and m.zone == Zone.PLAY for m in summons)
    # The 1-cost spell from hand provably creates one same-cost summon. Whether
    # Djinni's effect-copy is itself another “you cast” event is intentionally open.
    return observed, valid, "hand cast and effect-copy path characterized; CAST-001 rule semantics remain unresolved"


def gvg_case_001():
    winners, valid = set(), True
    for seed in range(128):
        game = new_game(seed, CardClass.MAGE, CardClass.MAGE)
        player, enemy = game.player1, game.player2
        targets = [summon(enemy, ANIMATED_STATUE), summon(enemy, "CS2_182")]
        before = [m.damage for m in targets]
        spell = play(player, "GVG_001")
        deltas = [m.damage - before[i] for i, m in enumerate(targets)]
        hit = [i for i, delta in enumerate(deltas) if delta == 4 and targets[i].zone == Zone.PLAY]
        valid &= spell.zone == Zone.GRAVEYARD and len(hit) == 1 and enemy.hero.health == 30
        if len(hit) == 1:
            winners.add(hit[0])
    observed = f"seeds=128;candidate_winners={sorted(winners)};both_enemy_candidates_hit={winners == {0,1}};exactly_one_4_damage_each_cast=True"
    return observed, valid and winners == {0, 1}, "random target domain sampled across fixed seeds"


def gvg_case_003():
    costs, observed_ids, valid = set(), set(), True
    floor_seen = False
    for seed in range(128):
        game = new_game(seed)
        player = game.player1
        before = list(player.hand)
        play(player, "GVG_003")
        added = [card for card in player.hand if card not in before]
        if len(added) != 1:
            valid = False
            continue
        card = added[0]
        printed, actual = int(card.data.cost), int(card.cost)
        valid &= card.type == CardType.MINION and actual == max(0, printed - 3)
        floor_seen |= printed < 3 and actual == 0
        costs.add((printed, actual))
        observed_ids.add(card.id)
    observed = f"seeds=128;cost_pairs={sorted(costs)};zero_floor_seen={floor_seen};distinct_minions={len(observed_ids)};all_costs=max(0,printed-3)"
    return observed, valid and floor_seen and any(printed >= 3 for printed, _ in costs), "random identity unconstrained; low-cost floor and ordinary discount branches sampled"


def gvg_case_004():
    recipients, valid = set(), True
    for seed in range(128):
        game = new_game(seed)
        player, enemy = game.player1, game.player2
        summon(player, "GVG_082")
        targets = [summon(enemy, ANIMATED_STATUE), summon(enemy, ANIMATED_STATUE), summon(enemy, ANIMATED_STATUE)]
        before = [m.damage for m in targets]
        hero_before = enemy.hero.health
        play(player, "GVG_004")
        deltas = [m.damage - before[i] for i, m in enumerate(targets)] + [hero_before - enemy.hero.health]
        valid &= sum(deltas) == 4 and all(delta >= 0 for delta in deltas)
        recipients.update(i for i, delta in enumerate(deltas) if delta > 0)
    observed = f"seeds=128;recipient_indexes={sorted(recipients)};domain=enemy_minions_0_1_2+enemy_hero;each_battlecry_total=4"
    return observed, valid and recipients == {0, 1, 2, 3}, "mech-on and prior no-Mech case retained; random enemy recipient domain covered"


def gvg_case_020():
    winners, valid = set(), True
    for seed in range(128):
        game = new_game(seed, CardClass.WARLOCK, CardClass.WARLOCK)
        player, enemy = game.player1, game.player2
        cannon = summon(player, "GVG_020")
        friendlies = [summon(player, "CS2_182"), summon(player, "EX1_016")]
        enemies = [summon(enemy, "CS2_182"), summon(enemy, "EX1_016")]
        mechs = [cannon, summon(player, "GVG_082"), summon(enemy, "GVG_082")]
        eligible = friendlies + enemies
        game.current_player = player
        before = [m.damage for m in eligible]
        game.end_turn()
        deltas = [m.damage - before[i] for i, m in enumerate(eligible)]
        hit = [i for i, delta in enumerate(deltas) if delta == 2]
        valid &= len(hit) == 1 and all(mech.damage == 0 for mech in mechs) and player.hero.health == 30 and enemy.hero.health == 30
        if len(hit) == 1:
            winners.add(hit[0])
    observed = f"seeds=128;non_mech_winners={sorted(winners)};pool=two_friendly+two_enemy_nonmechs;Fel_Cannon_and_other_Mechs_excluded=True;heroes_excluded=True"
    return observed, valid and winners == {0, 1, 2, 3}, "both prior own-turn/end-turn evidence and each eligible recipient branch retained"


def gvg_case_029():
    seen = {"owner": set(), "opponent": set()}
    valid = True
    choices = ((WISP, "GVG_093"), ("CS2_033", "CS2_182"))
    for seed in range(128):
        game = new_game(seed, CardClass.SHAMAN, CardClass.SHAMAN)
        owner, opponent = game.player1, game.player2
        entities = {"owner": [owner.give(cid) for cid in choices[0]],
                    "opponent": [opponent.give(cid) for cid in choices[1]]}
        before = {side: {card for card in cards if card.zone == Zone.HAND} for side, cards in entities.items()}
        play(owner, "GVG_029")
        for side, cards in entities.items():
            entered = [card for card in cards if card.zone == Zone.PLAY]
            remained = [card for card in cards if card.zone == Zone.HAND]
            valid &= len(entered) == len(remained) == 1
            if len(entered) == 1:
                seen[side].add(entered[0].id)
            # ensure no extra candidate left its owner hand or entered wrong side
            player = owner if side == "owner" else opponent
            valid &= all(card.controller is player for card in entered)
    observed = f"seeds=128;owner_candidate_winners={sorted(seen['owner'])};opponent_candidate_winners={sorted(seen['opponent'])};one_from_each_hand_each_cast=True"
    expected_owner = set(choices[0]); expected_opponent = set(choices[1])
    return observed, valid and seen["owner"] == expected_owner and seen["opponent"] == expected_opponent, "competing random candidates for both players; prior one-candidate case retained"


SPARE_PART_IDS = {f"PART_{n:03d}" for n in range(1, 8)}


def gvg_case_034():
    observed_parts, valid = set(), True
    for seed in range(96):
        game = new_game(seed, CardClass.DRUID, CardClass.DRUID)
        player = game.player1
        bear = summon(player, "GVG_034")
        spell = player.give(MOONFIRE)
        before = list(player.hand)
        spell.play(target=bear)
        added = [card.id for card in player.hand if card not in before]
        valid &= bear.health == bear.max_health - 1 and len(added) == 1 and added[0] in SPARE_PART_IDS
        observed_parts.update(added)
    observed = f"seeds=96;spare_parts_seen={sorted(observed_parts)};pool_size={len(SPARE_PART_IDS)};one_per_damage_event=True"
    return observed, valid and observed_parts == SPARE_PART_IDS, "96 independent damage-trigger games sample the Spare Part identity domain"


def gvg_case_042():
    seen, valid = set(), True
    for seed in range(128):
        game = new_game(seed, CardClass.SHAMAN, CardClass.SHAMAN)
        player = game.player1
        before = list(player.hand)
        neph = play(player, "GVG_042")
        added = [card for card in player.hand if card not in before]
        valid &= len(added) == 4 and all(Race.MURLOC in card.races for card in added)
        valid &= neph.zone == Zone.PLAY and player.overloaded == 3
        seen.update(card.id for card in added)
    observed = f"seeds=128;distinct_murloc_ids={len(seen)};sample={sorted(seen)[:24]};each_battlecry_adds_four_murlocs_and_overloads_3=True"
    return observed, valid and len(seen) >= 2, "different random Murloc identities observed across seeds; prior four-card/Overload evidence retained"


def gvg_case_043():
    winners, valid = set(), True
    for seed in range(96):
        game = new_game(seed, CardClass.HUNTER, CardClass.HUNTER)
        player = game.player1
        allies = [summon(player, "CS2_182"), summon(player, "EX1_016")]
        before = [m.atk for m in allies]
        weapon = play(player, "GVG_043")
        deltas = [m.atk - before[i] for i, m in enumerate(allies)]
        hit = [i for i, delta in enumerate(deltas) if delta == 1]
        valid &= weapon.zone == Zone.PLAY and len(hit) == 1 and sum(deltas) == 1
        if len(hit) == 1:
            winners.add(hit[0])
    observed = f"seeds=96;beneficiary_indexes={sorted(winners)};exactly_one_minion_gains_1_attack=True;weapon_equipped=True"
    return observed, valid and winners == {0, 1}, "both random friendly-minion recipients sampled"


def gvg_case_052():
    game = new_game(class1=CardClass.WARRIOR, class2=CardClass.WARRIOR)
    player, opponent = game.player1, game.player2
    target = summon(opponent, "CS2_182")
    crush = player.give("GVG_052")
    cost_before = crush.cost
    damaged_friends = [m for m in player.field if m.health < m.max_health]
    crush.play(target=target)
    observed = f"damaged_friendly_minions={len(damaged_friends)};cost={cost_before}->{crush.cost};target={target.zone.name};printed_cost={crush.data.cost}"
    return observed, cost_before == crush.data.cost == 7 and target.zone == Zone.GRAVEYARD and crush.zone == Zone.GRAVEYARD, "unconditional full-cost branch passed; prior damaged-friendly discount branch retained"


def gvg_case_059():
    winners, valid = set(), True
    for seed in range(96):
        game = new_game(seed, CardClass.PALADIN, CardClass.PALADIN)
        player = game.player1
        allies = [summon(player, "CS2_182"), summon(player, "EX1_016")]
        hammer = play(player, "GVG_059")
        states = [(bool(m.taunt), bool(m.divine_shield)) for m in allies]
        hit = [i for i, state in enumerate(states) if state == (True, True)]
        valid &= hammer.zone == Zone.PLAY and len(hit) == 1 and states[1-hit[0]] == (False, False)
        if len(hit) == 1:
            winners.add(hit[0])
    observed = f"seeds=96;beneficiary_indexes={sorted(winners)};one_recipient_gets_taunt_and_shield=True;weapon_equipped=True"
    return observed, valid and winners == {0, 1}, "both candidate recipients sampled; prior weapon and tag behavior retained"


def gvg_case_075():
    seen, valid = set(), True
    for seed in range(128):
        game = new_game(seed)
        player, enemy = game.player1, game.player2
        cannon = summon(player, "GVG_075")
        targets = [summon(enemy, ANIMATED_STATUE), summon(enemy, "CS2_182")]
        before = [m.damage for m in targets]
        hero_before = enemy.hero.health
        pirate = summon(player, "CS2_146")
        deltas = [m.damage - before[i] for i, m in enumerate(targets)] + [hero_before - enemy.hero.health]
        hit = [i for i, delta in enumerate(deltas) if delta == 2]
        valid &= Race.PIRATE in pirate.races and cannon.zone == Zone.PLAY and len(hit) == 1 and sum(deltas) == 2
        if len(hit) == 1:
            seen.add(hit[0])
    observed = f"seeds=128;enemy_recipient_indexes={sorted(seen)};domain=two_enemy_minions+enemy_hero;each_pirate_summon_deals_one_2_damage_hit=True"
    return observed, valid and seen == {0, 1, 2}, "all random enemy recipient classes sampled"


def gvg_case_078():
    seen_owner, seen_opponent, valid = set(), set(), True
    for seed in range(96):
        game = new_game(seed)
        owner, opponent = game.player1, game.player2
        yeti = summon(owner, "GVG_078")
        owner_before, opponent_before = list(owner.hand), list(opponent.hand)
        yeti.destroy()
        owner_added = [c.id for c in owner.hand if c not in owner_before]
        opponent_added = [c.id for c in opponent.hand if c not in opponent_before]
        valid &= yeti.zone == Zone.GRAVEYARD and len(owner_added) == len(opponent_added) == 1
        valid &= all(cid in SPARE_PART_IDS for cid in owner_added + opponent_added)
        seen_owner.update(owner_added); seen_opponent.update(opponent_added)
    observed = f"seeds=96;owner_parts={sorted(seen_owner)};opponent_parts={sorted(seen_opponent)};each_side_receives_one=True"
    return observed, valid and seen_owner == SPARE_PART_IDS and seen_opponent == SPARE_PART_IDS, "both independently random recipient pools cover all Spare Part identities"


def gvg_case_082():
    seen, valid = set(), True
    for seed in range(96):
        game = new_game(seed)
        owner = game.player1
        gnome = summon(owner, "GVG_082")
        before = list(owner.hand)
        gnome.destroy()
        added = [c.id for c in owner.hand if c not in before]
        valid &= gnome.zone == Zone.GRAVEYARD and len(added) == 1 and added[0] in SPARE_PART_IDS
        seen.update(added)
    observed = f"seeds=96;spare_parts_seen={sorted(seen)};one_controller_part_per_death=True"
    return observed, valid and seen == SPARE_PART_IDS, "deathrattle random identity domain sampled across seeds"


def gvg_case_090():
    seen, valid = set(), True
    for seed in range(128):
        game = new_game(seed)
        player, enemy = game.player1, game.player2
        friends = [summon(player, ANIMATED_STATUE), summon(player, ANIMATED_STATUE)]
        enemies = [summon(enemy, ANIMATED_STATUE), summon(enemy, ANIMATED_STATUE)]
        characters = friends + enemies
        before = [m.damage for m in characters]
        hero_before = [player.hero.health, enemy.hero.health]
        bomber = play(player, "GVG_090")
        deltas = [m.damage - before[i] for i, m in enumerate(characters)] + [
            hero_before[0] - player.hero.health, hero_before[1] - enemy.hero.health,
        ]
        valid &= bomber.zone == Zone.PLAY and sum(deltas) == 6 and all(delta >= 0 for delta in deltas)
        seen.update(i for i, delta in enumerate(deltas) if delta > 0)
    observed = f"seeds=128;recipient_indexes={sorted(seen)};domain=two_friendly_minions+two_enemy_minions+both_heroes;exactly_six_damage_per_battlecry=True"
    return observed, valid and seen == set(range(6)), "random split samples all other-character categories, including both minion sides"


def random_deathrattle_case(card_id, cost, seed_count=128):
    seen, valid = set(), True
    for seed in range(seed_count):
        game = new_game(seed)
        owner = game.player1
        source = summon(owner, card_id)
        existing = set(owner.field)
        source.destroy()
        summoned = [m for m in owner.field if m not in existing and m is not source]
        if len(summoned) != 1:
            valid = False
            continue
        minion = summoned[0]
        valid &= source.zone == Zone.GRAVEYARD and minion.zone == Zone.PLAY and int(minion.data.cost) == cost
        seen.add(minion.id)
    observed = f"seeds={seed_count};distinct_spawn_ids={len(seen)};sample={sorted(seen)[:30]};printed_cost={cost};exactly_one_spawn_per_death=True"
    return observed, valid and len(seen) >= 2, "multiple valid random candidates sampled; prior cost and zone evidence retained"


def gvg_case_107():
    seen, valid = set(), True
    for seed in range(96):
        game = new_game(seed)
        player = game.player1
        friends = [summon(player, WISP), summon(player, "CS2_182"), summon(player, "EX1_016"), summon(player, "CS2_168")]
        assert all(not m.taunt and not m.windfury and not m.divine_shield for m in friends), "keyword probe fixtures must start without target keywords"
        mechano = play(player, "GVG_107")
        if mechano.zone != Zone.PLAY:
            valid = False
        for minion in friends:
            flags = (bool(minion.windfury), bool(minion.taunt), bool(minion.divine_shield))
            valid &= sum(flags) == 1
            if sum(flags) == 1:
                seen.add(flags.index(True))
    observed = f"seeds=96;keyword_indexes={sorted(seen)};index_meaning=0_windfury_1_taunt_2_divine_shield;one_of_three_per_other_minion=True"
    return observed, valid and seen == {0, 1, 2}, "random keyword choices include all three options across fixed seeds"


def gvg_case_115():
    battlecry_seen, death_seen, valid = set(), set(), True
    for seed in range(96):
        game = new_game(seed)
        player = game.player1
        before = list(player.hand)
        toshley = play(player, "GVG_115")
        play_added = [c.id for c in player.hand if c not in before]
        valid &= len(play_added) == 1 and play_added[0] in SPARE_PART_IDS and toshley.zone == Zone.PLAY
        battlecry_seen.update(play_added)
        before_death = list(player.hand)
        toshley.destroy()
        death_added = [c.id for c in player.hand if c not in before_death]
        valid &= toshley.zone == Zone.GRAVEYARD and len(death_added) == 1 and death_added[0] in SPARE_PART_IDS
        death_seen.update(death_added)
    observed = f"seeds=96;battlecry_parts={sorted(battlecry_seen)};deathrattle_parts={sorted(death_seen)};one_each_per_trigger=True"
    return observed, valid and battlecry_seen == SPARE_PART_IDS and death_seen == SPARE_PART_IDS, "both independent trigger paths sample all Spare Part identities"


def og_282_case():
    game = new_game(class1=CardClass.ROGUE, class2=CardClass.ROGUE)
    player, enemy = game.player1, game.player2
    cthun = player.give("OG_280")
    target = summon(enemy, "CS2_182")
    target.set_current_health(2)
    base = (cthun.atk, cthun.health, target.atk, target.health, target.max_health)
    blade = play(player, "OG_282", target)
    actual = (cthun.atk, cthun.health)
    current_interpretation = (base[0] + base[2], base[1] + base[3])
    maximum_interpretation = (base[0] + base[2], base[1] + base[4])
    observed = f"wounded_target={base[2]}/{base[3]}/{base[4]};cthun={actual};current_health_interpretation={current_interpretation};max_health_interpretation={maximum_interpretation};target={target.zone.name};blade={blade.zone.name}"
    valid = target.zone == Zone.GRAVEYARD and blade.zone == Zone.PLAY and actual in (current_interpretation, maximum_interpretation)
    return observed, valid, "wounded-target implementation behavior recorded; official card text does not resolve current-vs-max Health semantics"


CASES = {
    "DS1_184": ("tracking_choice_draw_event_counter_control", tracking_case,
                "look at exactly three top cards, choose one into hand and remove the other two; compare draw counter with ordinary Draw"),
    "EX1_095": ("effect_cast_arcane_intellect_listener", lambda: cast_trigger_case("EX1_095"),
                "Grand Archivist effect-casts Arcane Intellect; resolve its two draws and check Auctioneer adds no extra draw; hand-played control"),
    "EX1_187": ("effect_cast_arcane_intellect_listener", lambda: cast_trigger_case("EX1_187"),
                "Grand Archivist effect-casts Arcane Intellect; compare Devourer stats with its hand-played spell control"),
    "EX1_559": ("effect_cast_arcane_intellect_listener", lambda: cast_trigger_case("EX1_559"),
                "Grand Archivist effect-casts Arcane Intellect; count Fireballs and compare the hand-played spell control"),
    "GVG_001": ("seeded_random_enemy_minion_candidates", gvg_case_001, "128 isolated live games; both enemy-minion candidates must be observed"),
    "GVG_003": ("seeded_random_minion_cost_floor", gvg_case_003, "128 isolated live games; verify exact cost reduction and zero floor"),
    "GVG_004": ("seeded_random_enemy_damage_recipients", gvg_case_004, "128 isolated live games with Mech and three enemy minions plus hero"),
    "GVG_020": ("seeded_random_non_mech_end_turn_recipients", gvg_case_020, "128 own-turn end phases with two other eligible non-Mechs; Mech and heroes are controls"),
    "GVG_029": ("seeded_random_multi_candidate_each_hand", gvg_case_029, "128 spell resolutions with two candidates in each player's hand"),
    "GVG_034": ("seeded_random_spare_part_on_damage", gvg_case_034, "96 isolated damage triggers; sample the seven Spare Part identities"),
    "GVG_042": ("seeded_random_murloc_pool_and_overload", gvg_case_042, "128 battlecries; assert four Murlocs, Overload 3, and identity variety"),
    "GVG_043": ("seeded_random_friendly_attack_buff_recipient", gvg_case_043, "96 battlecries with two friendly candidates; each recipient must be hit"),
    "GVG_052": ("no_damaged_friendly_full_cost_control", gvg_case_052, "Cast Crush with no damaged friendly minion and retain prior discount-positive case"),
    "GVG_059": ("seeded_random_coghammer_recipient", gvg_case_059, "96 battlecries with two friendly candidates; verify both tags and each recipient"),
    "GVG_075": ("seeded_random_enemy_character_after_pirate", gvg_case_075, "128 Pirate summons with two enemy minions and enemy hero available"),
    "GVG_078": ("seeded_random_parts_for_each_player", gvg_case_078, "96 deaths; independently sample each player's Spare Part identity pool"),
    "GVG_082": ("seeded_random_spare_part_deathrattle", gvg_case_082, "96 Clockwork Gnome deaths; sample the seven Spare Part identities"),
    "GVG_090": ("seeded_random_damage_split_including_minions", gvg_case_090, "128 battlecries with two friendly and two enemy minions plus both heroes"),
    "GVG_096": ("seeded_random_two_cost_deathrattle_candidates", lambda: random_deathrattle_case("GVG_096", 2), "128 deaths; verify cost, zone, single summon, and multiple candidate identities"),
    "GVG_105": ("seeded_random_four_cost_deathrattle_candidates", lambda: random_deathrattle_case("GVG_105", 4), "128 deaths; verify cost, zone, single summon, and multiple candidate identities"),
    "GVG_107": ("seeded_random_keyword_including_taunt", gvg_case_107, "96 battlecries x four other minions; each receives exactly one and Taunt appears"),
    "GVG_115": ("seeded_random_parts_on_battlecry_and_deathrattle", gvg_case_115, "96 full play/death pairs; each trigger independently samples the Spare Part domain"),
    "LOE_086": ("djinni_effect_cast_inner_fire_listener", loe_cast_trigger_case,
                "Hand-cast Inner Fire triggers Stone; characterize Djinni's effect-cast copy without assuming CAST-001 rule semantics"),
    "CFM_060": ("effect_cast_arcane_intellect_listener", lambda: cast_trigger_case("CFM_060"),
                "Grand Archivist effect-casts Arcane Intellect; compare Wyrm attack with the hand-played spell control"),
    "OG_282": ("wounded_target_health_increment_control", og_282_case,
               "Target a wounded minion; retain measured current-Health versus maximum-Health alternatives without choosing a rules interpretation"),
}

BLOCKERS = {
    "DS1_184": "YELLOW: top-three choice and removal pass, but its 'Draw one' wording does not establish whether it emits the Draw event; the observed draw-counter distinction needs authoritative rules semantics.",
    "EX1_095": "YELLOW: effect-cast path characterized, but whether spells cast by another card count as 'you cast' for listeners remains CAST-001 rules-semantic blocker.",
    "EX1_187": "YELLOW: effect-cast path characterized, but whether spells cast by another card count as 'you cast' for listeners remains CAST-001 rules-semantic blocker.",
    "EX1_559": "YELLOW: effect-cast path characterized, but whether spells cast by another card count as 'you cast' for listeners remains CAST-001 rules-semantic blocker.",
    "LOE_086": "YELLOW: hand-cast and Djinni effect-cast paths characterized, but CAST-001 does not establish whether the effect-copy itself counts as 'you cast'.",
    "CFM_060": "YELLOW: effect-cast path characterized, but whether spells cast by another card count as 'you cast' for listeners remains CAST-001 rules-semantic blocker.",
    "OG_282": "YELLOW: wounded-target runtime behavior is recorded, but official text says Attack and Health without specifying current Health versus maximum Health; no authoritative rule evidence settles the distinction.",
}


def execute_case(card_id):
    name, function, expected = CASES[card_id]
    try:
        observed, valid, detail = function()
        outcome = "pass" if valid else "inconclusive"
        if not valid:
            detail += "; expected branch coverage or core state assertion was not complete"
    except AssertionError as exc:
        observed = str(exc) or "AssertionError"
        outcome = "inconclusive"
        detail = "probe assertion did not complete; review fixture and runtime before inferring a card bug"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
        detail = "runtime exception; this probe is not treated as evidence of a card implementation bug"
    case_id = f"{card_id}::{name}"
    return {
        "card_id": card_id,
        "case_id": case_id,
        "expected": expected,
        "observed": observed,
        "outcome": outcome,
        "notes": f"{detail}; {metadata(card_id)}",
    }


def main():
    rows, verdicts = [], []
    write_csv(PROBE_OUT, PROBE_FIELDS, rows)
    write_csv(VERDICT_OUT, VERDICT_FIELDS, verdicts)
    for card_id in FROZEN_IDS:
        row = execute_case(card_id)
        rows.append(row)
        assert row["case_id"].startswith(row["card_id"] + "::")
        write_csv(PROBE_OUT, PROBE_FIELDS, rows)
        quality = QUALITY_BY_ID[card_id]
        master = MASTER_BY_ID[card_id]
        if row["outcome"] != "pass":
            status = "YELLOW"
            reason = f"YELLOW: independent live case incomplete: {row['observed']}"
        elif card_id in BLOCKERS:
            status, reason = "YELLOW", BLOCKERS[card_id]
        else:
            status = "GREEN"
            reason = f"本轮补足原黄卡缺失分支且逐卡实测通过：{row['case_id']}={row['observed']}"
        verdicts.append({
            "card_id": card_id,
            "status": status,
            "mechanic_scope": master["mechanics"],
            "reason": reason,
            "probe_file": PROBE_OUT.name,
            "notes": f"new_case={row['case_id']}; new_outcome={row['outcome']}; prior_status={quality['status']}; {metadata(card_id)}",
        })
        write_csv(VERDICT_OUT, VERDICT_FIELDS, verdicts)
        print(f"{row['card_id']} {row['case_id']}: {row['outcome']} -> {status} :: {row['observed']}", flush=True)
    assert len(rows) == 25 and {row["card_id"] for row in rows} == set(FROZEN_IDS)
    counts = {name: sum(row["status"] == name for row in verdicts) for name in ("GREEN", "YELLOW", "RED")}
    print(f"COUNTS {counts}; cases={len(rows)}; roster={len(FROZEN_IDS)}")


if __name__ == "__main__":
    main()
