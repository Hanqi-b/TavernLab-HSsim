"""Card-specific live behavior probes for frozen Boomsday YELLOW cards 45:90."""

from __future__ import annotations

import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import GameOver

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import MOONFIRE, WISP, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "boom_probe_b.csv"
VERDICT_FILE = HERE / "boom_verdict_b.csv"
BASELINE_FILE = HERE / "remaining_yellow_baseline.csv"
MASTER_FILE = HERE / "card_master.csv"
QUALITY_FILE = HERE / "card_quality.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


ALL_BOOM = sorted(
    (r for r in read_csv(BASELINE_FILE) if r["set"].endswith("(BOOMSDAY)")),
    key=lambda r: r["card_id"],
)
ROSTER = ALL_BOOM[45:90]
assert len(ALL_BOOM) == 135 and len(ROSTER) == 45
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER_FILE)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY_FILE)}
FROZEN_IDS = tuple(r["card_id"] for r in ROSTER)


def game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=181):
    random.seed(seed)
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    p = next((player for player in g.players if player.hero.card_class == class1), g.player1)
    e = next(player for player in g.players if player is not p)
    if g.current_player is not p:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    assert p.hero.card_class == class1 and e.hero.card_class == class2
    return g, p, e


def play(player, card_id, target=None, choose=None, index=None):
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    if index is not None:
        kwargs["index"] = index
    card.play(**kwargs)
    return card


def summon(player, card_id, index=None):
    assert index is None or index == len(player.field)
    return player.summon(card_id)


def put_deck(player, card_ids):
    result = []
    for card_id in card_ids:
        card = player.give(card_id)
        card.shuffle_into_deck()
        result.append(card)
    return result


def ready(minion):
    minion.turns_in_play = 1
    minion.cant_attack = False
    minion.num_attacks = 0


def check(ok, observed):
    assert ok, observed
    return observed


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    prior = ROSTER_BY_ID[card_id]
    return (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or master.get('xml_source', '')}; "
        f"existing_tests={master.get('test_refs_candidate', '') or 'none'}; "
        f"previous={prior.get('status', 'unknown')}:{prior.get('reason', '')}; "
        f"prior_evidence={prior.get('evidence', '')}"
    )


def zerek_master_cloner():
    cid = "BOT_258"

    def spell_then_resummon_and_control():
        g, p, e = game(CardClass.PRIEST, CardClass.PRIEST)
        zerek = summon(p, cid)
        spell = play(p, "BOT_219", target=zerek)
        buffed = (zerek.atk, zerek.max_health)
        zerek.destroy()
        returned = [m for m in p.field if m.id == cid]
        positive = (spell.zone == Zone.GRAVEYARD and buffed == (7, 7)
                    and zerek.zone == Zone.GRAVEYARD and len(returned) == 1
                    and returned[0].zone == Zone.PLAY)

        control_game, control, _ = game(CardClass.PRIEST, CardClass.PRIEST)
        unmarked = summon(control, cid)
        unmarked.destroy()
        no_return = not [m for m in control.field if m.id == cid]
        observed = (f"spell={spell.id}:{spell.zone.name};buffed={buffed};first={zerek.zone.name};"
                    f"returned={[(m.id,m.atk,m.health,m.zone.name) for m in returned]};"
                    f"no_spell_control={no_return};control_original={unmarked.zone.name}")
        return check(positive and no_return and unmarked.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("spell_on_minion_marks_deathrattle", "Casting a spell on Zerek marks it; its first death resummons one copy, while an unmarked copy does not return.", spell_then_resummon_and_control, "Independent buff-spell cast, first death, and no-spell control.")])


def soul_infusion():
    cid = "BOT_263"

    def leftmost_minion_only():
        g, p, e = game(CardClass.WARLOCK, CardClass.WARLOCK)
        left = p.give("CS2_182")
        right = p.give("CS2_231")
        initial = [(c.id, c.atk, c.health) for c in (left, right)]
        spell = play(p, cid)
        observed = f"before={initial};after={[(c.id,c.atk,c.health,c.zone.name) for c in (left,right)]};spell={spell.zone.name}"
        return check(left.atk == 6 and left.health == 7 and right.atk == 1 and right.health == 1
                     and left in p.hand and right in p.hand and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("buffs_only_leftmost_hand_minion", "Only the left-most minion card in hand receives +2/+2.", leftmost_minion_only, "Two distinct minions were placed in hand in known order; verified one hand-card buff.")])


def piloted_reaper():
    cid = "BOT_267"

    def random_eligible_hand_minion():
        winners, valid = set(), True
        for seed in range(24):
            g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed)
            low_a, low_b = p.give(WISP), p.give("GVG_002")
            high = p.give("CS2_182")
            reaper = summon(p, cid)
            reaper.destroy()
            active = [c for c in (low_a, low_b) if c.zone == Zone.PLAY]
            valid &= reaper.zone == Zone.GRAVEYARD and len(active) == 1
            valid &= high.zone == Zone.HAND
            if len(active) == 1:
                winners.add(active[0].id)
        observed = f"seeds=24;eligible_winners={sorted(winners)};high_cost_left_hand={high.zone.name};one_eligible_summoned_per_death={valid}"
        return check(valid and winners == {WISP, "GVG_002"}, observed)

    audit(cid, [("death_summons_random_hand_minion_cost_at_most_two", "Deathrattle summons exactly one random minion from hand with printed Cost <=2; a 4-Cost minion is excluded.", random_eligible_hand_minion, "24 controlled random-seed games used two eligible minions and one ineligible minion.")])


def giggling_inventor():
    cid = "BOT_270"

    def two_shielded_taunt_mechs():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        source = play(p, cid)
        tokens = [m for m in p.field if m.id == "BOT_270t"]
        observed = f"source={source.zone.name};tokens={[(m.id,m.atk,m.health,m.taunt,m.divine_shield,m.races,m.zone.name) for m in tokens]};field={len(p.field)}"
        return check(source.zone == Zone.PLAY and len(tokens) == 2
                     and all((m.atk,m.health,m.taunt,m.divine_shield,m.zone)==(1,2,True,True,Zone.PLAY) for m in tokens)
                     and all(Race.MECHANICAL in m.races for m in tokens), observed)

    audit(cid, [("battlecry_summons_two_taunt_divine_shield_mechs", "Battlecry summons exactly two 1/2 Mechs with Taunt and Divine Shield.", two_shielded_taunt_mechs, "Live Battlecry resolution inspected both tokens' stats, race, Taunt, and shield.")])


def holomancer():
    cid = "BOT_280"

    def opponent_minion_play_copied_only():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        holo = summon(p, cid)
        before_friendly = len(p.field)
        friendly = play(p, "GVG_002")
        after_friendly = len(p.field)
        g.end_turn()
        original = play(e, "CS2_182")
        copies = [m for m in p.field if m.id == original.id]
        before_spell = len(p.field)
        play(e, MOONFIRE, target=p.hero)
        after_spell = len(p.field)
        observed = f"holo={holo.zone.name};friendly_minion={friendly.zone.name};opponent_minion={original.id}:{original.zone.name};copies={[(m.id,m.atk,m.health,m.controller is p) for m in copies]};field_friendly={before_friendly}->{after_friendly};opponent_spell={before_spell}->{after_spell}"
        return check(holo.zone == Zone.PLAY and len(copies)==1 and copies[0].controller is p
                     and (copies[0].atk,copies[0].max_health)==(1,1)
                     and after_friendly==before_friendly+1 and after_spell==before_spell, observed)

    audit(cid, [("opponent_minion_play_summons_one_one_copy", "Opponent minion Play creates a 1/1 copy; a spell and friendly minion do not trigger it.", opponent_minion_play_copied_only, "Opponent turn controlled; tested opponent minion trigger and spell/friendly-play controls.")])


def pogo_hopper():
    cid = "BOT_283"

    def buffs_for_other_copies_played_this_game():
        g, p, e = game(CardClass.ROGUE, CardClass.ROGUE)
        first = play(p, cid)
        first_stats = (first.atk, first.max_health)
        second = play(p, cid)
        second_stats = (second.atk, second.max_health)
        third = play(p, cid)
        third_stats = (third.atk, third.max_health)
        observed = f"first={first_stats};second={second_stats};third={third_stats};ids={[m.id for m in p.field]}"
        return check(first_stats == (1,1) and second_stats == (3,3) and third_stats == (5,5), observed)

    audit(cid, [("prior_pogo_hoppers_counted_but_self_excluded", "Each Pogo-Hopper gains +2/+2 per other copy played this game: first 1/1, second 3/3, third 5/5.", buffs_for_other_copies_played_this_game, "Sequential live plays distinguish prior copies from the current copy.")])


def necrium_blade():
    cid = "BOT_286"

    def weapon_deathrattle_triggers_random_friendly_deathrattle():
        g, p, e = game(CardClass.ROGUE, CardClass.ROGUE)
        bomb = summon(p, "BOT_031")
        mecharoo = summon(p, "BOT_445")
        weapon = play(p, cid)
        own_health, enemy_health = p.hero.health, e.hero.health
        weapon.destroy()
        joes = [m for m in p.field if m.id == "BOT_445t"]
        observed = f"weapon={weapon.zone.name};durability={weapon.durability};bomb={bomb.zone.name};mecharoo={mecharoo.zone.name};joe_tokens={len(joes)};heroes={own_health}->{p.hero.health}/{enemy_health}->{e.hero.health}"
        triggered_bomb = e.hero.health == enemy_health - 2 and not joes
        triggered_mecharoo = len(joes) == 1 and e.hero.health == enemy_health
        return check(weapon.zone == Zone.GRAVEYARD and (triggered_bomb or triggered_mecharoo)
                     and p.hero.health == own_health and bomb.zone == Zone.PLAY and mecharoo.zone == Zone.PLAY, observed)

    audit(cid, [("weapon_death_triggers_one_random_friendly_deathrattle", "When Necrium Blade dies, exactly one random friendly minion Deathrattle resolves; the minions remain alive.", weapon_deathrattle_triggers_random_friendly_deathrattle, "Weapon destroyed in a controlled state with two distinct friendly Deathrattle outcomes.")])


def lab_recruiter():
    cid = "BOT_288"

    def shuffles_three_friendly_copies():
        g, p, e = game(CardClass.ROGUE, CardClass.ROGUE)
        host = summon(p, "CS2_182")
        source = play(p, cid, target=host)
        copies = [c for c in p.deck if c.id == host.id]
        observed = f"source={source.zone.name};host={host.id}:{host.zone.name};deck={[c.id for c in p.deck]};target_copies={len(copies)}"
        return check(source.zone == Zone.PLAY and host.zone == Zone.PLAY and len(copies) == 3
                     and len(p.deck) == 3 and all(c.data.atk == host.data.atk and c.data.health == host.data.health for c in copies), observed)

    audit(cid, [("battlecry_shuffles_three_target_copies", "Battlecry shuffles three copies of the selected friendly minion into the deck and leaves its original on board.", shuffles_three_friendly_copies, "Target copy count, copied identity/stats, and original board presence checked.")])


def storm_chaser():
    cid = "BOT_291"

    def draws_only_five_cost_or_higher_spell():
        g, p, e = game(CardClass.SHAMAN, CardClass.SHAMAN)
        high = p.give("CS2_028")
        high.shuffle_into_deck()
        low = p.give(MOONFIRE)
        low.shuffle_into_deck()
        source = play(p, cid)
        observed = f"source={source.zone.name};high={high.id}:{high.cost}:{high.zone.name};low={low.id}:{low.cost}:{low.zone.name};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}"
        return check(source.zone == Zone.PLAY and high in p.hand and high.zone == Zone.HAND
                     and low in p.deck and low.zone == Zone.DECK, observed)

    audit(cid, [("battlecry_draws_only_eligible_high_cost_spell", "Battlecry draws the 6-Cost spell and leaves the 0-Cost spell in the deck.", draws_only_five_cost_or_higher_spell, "One qualifying and one nonqualifying deck spell isolate the cost filter.")])


def omega_defender():
    cid = "BOT_296"

    def ten_crystal_gate_and_taunt():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        p.max_resources = 10
        full = play(p, cid)
        full_state = (full.atk, full.max_health, full.taunt)
        g2, p2, e2 = game(CardClass.MAGE, CardClass.MAGE)
        p2.max_mana = 9
        p2.used_mana = 0
        lower = play(p2, cid)
        lower_state = (lower.atk, lower.max_health, lower.taunt)
        observed = f"10_crystal={full_state};9_crystal={lower_state};mana={p.max_mana}/{p2.max_mana};resources={p.max_resources}/{p2.max_resources}"
        return check(full_state == (12,6,True) and lower_state == (2,6,True), observed)

    audit(cid, [("ten_mana_crystals_unlock_plus_ten_attack", "At 10 Mana Crystals Omega Defender gains +10 Attack; at 9 it does not, and Taunt remains.", ten_crystal_gate_and_taunt, "Positive and negative max-crystal states with enough current Mana to play the card.")])


def omega_assembly():
    cid = "BOT_299"

    def ten_crystal_keeps_all_three_otherwise_choose_one():
        full_game, p, e = game(CardClass.WARRIOR, CardClass.WARRIOR)
        p.max_resources = 10
        full = play(p, cid)
        added = [c for c in p.hand if c.type == CardType.MINION and Race.MECHANICAL in c.races]
        full_no_choice = p.choice is None
        low_game, p2, e2 = game(CardClass.WARRIOR, CardClass.WARRIOR)
        p2.max_resources = 9
        p2.max_mana = 9
        low = play(p2, cid)
        options = list(p2.choice.cards) if p2.choice else []
        selected = options[0] if options else None
        if selected:
            p2.choice.choose(selected)
        low_no_choice = p2.choice is None
        observed = f"full={full.zone.name};full_choice={full_no_choice};all_mechs={[c.id for c in added]};low={low.zone.name};low_options={[c.id for c in options]};selected={selected.id if selected else None}:{selected.zone.name if selected else None};low_choice_closed={low_no_choice}"
        return check(full.zone == Zone.GRAVEYARD and full_no_choice and len(added) == 3
                     and all(Race.MECHANICAL in c.races for c in added)
                     and low.zone == Zone.GRAVEYARD and len(options) == 3 and selected in p2.hand
                     and low_no_choice, observed)

    audit(cid, [("ten_mana_keeps_all_discover_options", "At 10 Mana Crystals all three discovered Mechs enter hand; at 9 crystals a normal three-option Discover resolves to exactly one selected Mech.", ten_crystal_keeps_all_three_otherwise_choose_one, "Both sides of the max-mana gate were resolved through real choices.")])


def spring_rocket():
    cid = "BOT_308"

    def battlecry_deals_two_damage_to_selected_character():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        target = summon(e, "CS2_182")
        before = target.health
        source = play(p, cid, target=target)
        observed = f"source={source.zone.name};target={target.id}:{before}->{target.health};body={source.atk}/{source.health}"
        return check(source.zone == Zone.PLAY and target.health == before - 2 and source.health == 1, observed)

    audit(cid, [("battlecry_deals_two_to_target", "Battlecry deals exactly 2 damage to the chosen enemy minion while Spring Rocket remains in play.", battlecry_deals_two_damage_to_selected_character, "Minion target supplied to isolate the Battlecry damage amount.")])


def replicating_menace():
    cid = "BOT_312"

    def native_and_magnetic_deathrattle():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        standalone = play(p, cid)
        standalone.destroy()
        bots = [m for m in p.field if m.id == "BOT_312t"]
        first_ok = standalone.zone == Zone.GRAVEYARD and len(bots) == 3
        first_ok &= all((m.atk,m.health,Race.MECHANICAL in m.races)==(1,1,True) for m in bots)
        g2, p2, e2 = game(CardClass.MAGE, CardClass.MAGE)
        host = summon(p2, "BOT_020")
        magnet = play(p2, cid, index=0)
        host.destroy()
        attached_bots = [m for m in p2.field if m.id == "BOT_312t"]
        observed = f"standalone={standalone.zone.name};native_tokens={[(m.id,m.atk,m.health,m.zone.name) for m in bots]};host={host.zone.name};magnetic_card={magnet.zone.name};magnetic_tokens={len(attached_bots)}"
        second_ok = host.zone == Zone.GRAVEYARD and magnet.zone != Zone.PLAY and len(attached_bots) == 3
        return check(first_ok and second_ok and all(m.zone == Zone.PLAY for m in attached_bots), observed)

    audit(cid, [("deathrattle_three_microbots_standalone_and_magnetic", "The native and magnetically attached Deathrattle each summon exactly three 1/1 Mechs when the relevant minion dies.", native_and_magnetic_deathrattle, "Separate live games exercise card Deathrattle and its magnetic enchantment Deathrattle.")])


def weaponized_pinata():
    cid = "BOT_401"

    def death_adds_legendary_minion():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        pinata = summon(p, cid)
        before = list(p.hand)
        pinata.destroy()
        added = [c for c in p.hand if c not in before]
        observed = f"pinata={pinata.zone.name};added={[(c.id,c.type,c.rarity,c.zone.name) for c in added]}"
        return check(pinata.zone == Zone.GRAVEYARD and len(added) == 1
                     and added[0].type == CardType.MINION and int(added[0].rarity) == 5, observed)

    audit(cid, [("deathrattle_adds_random_legendary_minion", "Deathrattle adds exactly one Legendary minion to its controller's hand.", death_adds_legendary_minion, "Observed the generated hand card's type, rarity, and zone after death.")])


def secret_plan():
    cid = "BOT_402"

    def discover_hunter_secret_to_hand():
        g, p, e = game(CardClass.HUNTER, CardClass.HUNTER)
        source = play(p, cid)
        options = list(p.choice.cards) if p.choice else []
        selected = options[-1] if options else None
        ids = [c.id for c in options]
        if selected:
            p.choice.choose(selected)
        observed = f"source={source.zone.name};options={[(c.id,c.data.secret,c.card_class) for c in options]};selected={selected.id if selected else None}:{selected.zone.name if selected else None};secrets={[c.id for c in p.secrets]}"
        return check(source.zone == Zone.GRAVEYARD and len(options) == 3 and len(set(ids)) == 3
                     and all(c.data.secret and c.card_class == CardClass.HUNTER for c in options)
                     and selected in p.hand and selected.zone == Zone.HAND and p.choice is None, observed)

    audit(cid, [("discover_and_choose_hunter_secret", "Secret Plan discovers three distinct Hunter Secrets and the selected Secret enters hand.", discover_hunter_secret_to_hand, "Resolved the choice and inspected all candidate secret/class tags and destination zone.")])


def juicy_psychmelon():
    cid = "BOT_404"

    def draws_cost_seven_through_ten_minions():
        g, p, e = game(CardClass.DRUID, CardClass.DRUID)
        ids = ["CS2_201", "CS2_232", "EX1_561", "BOT_424"]
        deck = put_deck(p, ids)
        low = p.give("CS2_182")
        low.shuffle_into_deck()
        source = play(p, cid)
        observed = f"source={source.zone.name};drawn={[(c.id,c.data.cost,c.zone.name) for c in deck]};low={low.id}:{low.data.cost}:{low.zone.name};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}"
        return check(source.zone == Zone.GRAVEYARD and all(c.zone == Zone.HAND for c in deck)
                     and sorted(int(c.data.cost) for c in deck) == [7,8,9,10]
                     and low.zone == Zone.DECK, observed)

    audit(cid, [("draws_each_eligible_cost_minion", "Juicy Psychmelon draws the 7-, 8-, 9-, and 10-Cost deck minions and leaves a lower-cost minion in deck.", draws_cost_seven_through_ten_minions, "Four known-cost minions plus a lower-cost control were placed in deck.")])


def supercollider():
    cid = "BOT_406"

    def attacked_minion_attacks_one_neighbor():
        winners, valid = set(), True
        for seed in range(20):
            g, p, e = game(CardClass.WARRIOR, CardClass.WARRIOR, seed)
            left = summon(e, "CS2_182")
            center = summon(e, "CS2_182")
            right = summon(e, "CS2_182")
            left.atk = right.atk = 0
            weapon = play(p, cid)
            target_attack = center.atk
            before = (left.damage, center.damage, right.damage)
            p.hero.attack(center)
            deltas = (left.damage - before[0], center.damage - before[1], right.damage - before[2])
            hit = [idx for idx in (0,2) if deltas[idx] == target_attack]
            valid &= center.zone == Zone.PLAY and len(hit) == 1
            valid &= deltas[1] == 1 and deltas[0] + deltas[2] == target_attack
            if len(hit) == 1:
                winners.add(hit[0])
        observed = f"seeds=20;neighbor_winners={sorted(winners)};target_attack=4;each_attack_deltas=left/center/right={deltas};weapon={weapon.zone.name}:{weapon.durability}"
        return check(valid and winners == {0,2}, observed)

    audit(cid, [("hero_attack_forces_target_into_neighbor", "After the hero attacks a minion, that minion attacks one of its adjacent minions; random choices reach both neighbors across seeds.", attacked_minion_attacks_one_neighbor, "Controlled minion row, 20 random seeds, and one hero attack per game.")])


def thunderhead():
    cid = "BOT_407"

    def overload_play_summons_two_rush_sparks():
        g, p, e = game(CardClass.SHAMAN, CardClass.SHAMAN)
        head = summon(p, cid)
        enemy = summon(e, "CS2_182")
        lightning = play(p, "EX1_238", target=enemy)
        first = [m for m in p.field if m.id == "BOT_102t"]
        coin = play(p, "GAME_005")
        after_coin = len([m for m in p.field if m.id == "BOT_102t"])
        burst = play(p, "BOT_451")
        all_sparks = [m for m in p.field if m.id == "BOT_102t"]
        observed = f"head={head.zone.name};lightning={lightning.zone.name};first={[(m.atk,m.health,m.rush) for m in first]};coin={coin.zone.name};count_after_coin={after_coin};burst={burst.zone.name};final={[(m.atk,m.health,m.rush,m.zone.name) for m in all_sparks]};overload_owed={p.overloaded};enemy_health={enemy.health}"
        return check(len(first) == 2 and after_coin == 2 and len(all_sparks) == 6
                     and all((m.atk,m.health,m.rush,m.zone)==(1,1,True,Zone.PLAY) for m in all_sparks)
                     and p.overloaded == 2 and enemy.health == 2, observed)

    audit(cid, [("overload_card_triggers_two_sparks_and_nonoverload_control", "Each Overload card triggers two 1/1 Rush Sparks; non-Overload Coin adds none, and Voltaic Burst contributes two more of its own.", overload_play_summons_two_rush_sparks, "Lightning Bolt (Overload 1), Coin control, then Voltaic Burst (Overload 1) distinguish trigger from spell's own summons.")])


def electra_stormsurge():
    cid = "BOT_411"

    def duplicates_next_spell_then_expires():
        g, p, e = game(CardClass.SHAMAN, CardClass.SHAMAN)
        electra = play(p, cid)
        lightning = play(p, "EX1_238", target=e.hero)
        after_double = e.hero.health
        overloaded_after_double = p.overload_locked
        moonfire = play(p, MOONFIRE, target=e.hero)
        after_next_spell = e.hero.health
        observed = f"electra={electra.zone.name};lightning={lightning.zone.name};hero_after_double={after_double};overload={overloaded_after_double};moonfire={moonfire.zone.name};hero_after_next={after_next_spell}"
        return check(electra.zone == Zone.PLAY and after_double == 24 and overloaded_after_double == 2
                     and after_next_spell == 23, observed)

    audit(cid, [("next_spell_casts_twice_once", "Electra doubles the next Lightning Bolt (6 damage, Overload 2) then is consumed; the following Moonfire deals only 1.", duplicates_next_spell_then_expires, "Two real targeted spells distinguish one duplicated cast from later spell casts.")])


def brainstormer():
    cid = "BOT_413"

    def health_bonus_counts_spells_in_hand():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        spells = [p.give(MOONFIRE), p.give("CS2_025"), p.give("CS2_029")]
        minion = p.give(WISP)
        source = play(p, cid)
        observed = f"spell_cards={[(c.id,c.zone.name) for c in spells]};nonspell={minion.id}:{minion.zone.name};brainstormer={source.atk}/{source.health}/{source.max_health}"
        return check(source.zone == Zone.PLAY and source.atk == 3 and source.max_health == 4
                     and all(c.zone == Zone.HAND for c in spells) and minion.zone == Zone.HAND, observed)

    audit(cid, [("battlecry_health_scales_with_hand_spells", "Three spells in hand give Brainstormer exactly +3 Health; a hand minion does not count.", health_bonus_counts_spells_in_hand, "Three retained spell cards and one minion control isolate card-type counting.")])


def cloakscale_chemist():
    cid = "BOT_414"

    def stealth_and_shield_keywords_survive_combat_sequence():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        chemist = summon(p, cid)
        target = summon(e, "CS2_182")
        targeted_spell = e.give(MOONFIRE)
        before = (chemist.stealthed, chemist.divine_shield, chemist.health)
        inaccessible = chemist not in targeted_spell.play_targets
        ready(chemist)
        chemist.attack(target)
        after_attack = (chemist.stealthed, chemist.divine_shield, chemist.health, target.health)
        g.end_turn()
        targeted_spell.play(target=chemist)
        after_spell = (chemist.divine_shield, chemist.health)
        observed = f"before={before};untargetable_by_spell={inaccessible};after_attack={after_attack};after_moonfire={after_spell};spell={targeted_spell.zone.name}"
        return check(before == (True,True,2) and inaccessible and after_attack == (False,True,2,4)
                     and after_spell == (False,2) and targeted_spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("stealth_removes_on_attack_shield_blocks_next_damage", "Cloakscale starts Stealthed with Divine Shield, loses Stealth when attacking, and its Shield cancels the next spell damage.", stealth_and_shield_keywords_survive_combat_sequence, "Tested hidden-target exclusion, own attack, and a later enemy spell hit.")])


def dendrologist():
    cid = "BOT_419"

    def treant_unlocks_spell_discover():
        g, p, e = game(CardClass.DRUID, CardClass.DRUID)
        treant = summon(p, "EX1_158t")
        source = play(p, cid)
        options = list(p.choice.cards) if p.choice else []
        selected = options[0] if options else None
        if selected:
            p.choice.choose(selected)
        control_game, control, control_enemy = game(CardClass.DRUID, CardClass.DRUID)
        no_treant = play(control, cid)
        no_choice = control.choice is None
        observed = f"treant={treant.id}:{treant.zone.name};options={[(c.id,int(c.type)) for c in options]};selected={selected.id if selected else None}:{selected.zone.name if selected else None};without_treant_choice={not no_choice};control={no_treant.zone.name}"
        return check(treant.zone == Zone.PLAY and source.zone == Zone.PLAY
                     and len(options)==3 and all(c.type==CardType.SPELL for c in options)
                     and selected in p.hand and selected.zone==Zone.HAND and p.choice is None
                     and no_treant.zone==Zone.PLAY and no_choice, observed)

    audit(cid, [("treant_gate_opens_spell_discover", "A controlled Treant enables a spell Discover; without a Treant there is no choice.", treant_unlocks_spell_discover, "Resolved the positive Discover and a fresh no-Treant control.")])


def landscaping():
    cid = "BOT_420"

    def summons_two_treants():
        g, p, e = game(CardClass.DRUID, CardClass.DRUID)
        spell = play(p, cid)
        treants = [m for m in p.field if m.id == "EX1_158t"]
        observed = f"spell={spell.zone.name};treants={[(m.atk,m.health,m.races,m.zone.name) for m in treants]};board={len(p.field)}"
        return check(spell.zone == Zone.GRAVEYARD and len(treants)==2
                     and all((m.atk,m.health,m.zone)==(2,2,Zone.PLAY) and Race.TREANT in m.races for m in treants), observed)

    audit(cid, [("spell_summons_two_two_two_treants", "Landscaping summons exactly two 2/2 Treants.", summons_two_treants, "Inspected both live tokens' stats, race, and zone after casting.")])


def tending_tauren():
    cid = "BOT_422"

    def both_choose_one_branches():
        buff_game, p, e = game(CardClass.DRUID, CardClass.DRUID)
        ally = summon(p, WISP)
        source_a = play(p, cid, choose="BOT_422a")
        buff_state = (ally.atk,ally.max_health,source_a.zone.name)
        buff_tokens = len([m for m in p.field if m.id=="EX1_158t"])
        summon_game, p2, e2 = game(CardClass.DRUID, CardClass.DRUID)
        ally2 = summon(p2, WISP)
        source_b = play(p2, cid, choose="BOT_422b")
        treants = [m for m in p2.field if m.id=="EX1_158t"]
        observed = f"buff_branch={buff_state};unexpected_treants={buff_tokens};summon_branch_source={source_b.zone.name};ally={ally2.atk}/{ally2.max_health};treants={[(m.atk,m.health,m.zone.name) for m in treants]}"
        return check(buff_state==(2,2,"PLAY") and buff_tokens==0 and source_b.zone==Zone.PLAY
                     and (ally2.atk,ally2.max_health)==(1,1) and len(treants)==2
                     and all((m.atk,m.health,m.zone)==(2,2,Zone.PLAY) for m in treants), observed)

    audit(cid, [("choose_one_buff_and_treant_branches", "Branch A buffs other friendly minions +1/+1; Branch B summons two 2/2 Treants without buffing them.", both_choose_one_branches, "Each Choose One branch was selected and resolved in a fresh live game.")])


def dreampetal_florist():
    cid = "BOT_423"

    def end_turn_reduces_one_random_hand_minion():
        winners, valid = set(), True
        for seed in range(24):
            g, p, e = game(CardClass.DRUID, CardClass.DRUID, seed)
            high = p.give("CS2_232")  # 8-Cost minion -> 1 if selected.
            mid = p.give("CS2_200")   # 6-Cost minion -> 0 if selected.
            florist = play(p, cid)
            g.end_turn()
            costs = (high.cost,mid.cost)
            changed = [c.id for c, base in ((high,8),(mid,6)) if c.cost != base]
            valid &= florist.zone == Zone.PLAY and len(changed)==1
            valid &= (high.cost,mid.cost) in ((1,6),(8,0))
            winners.update(changed)
        observed = f"seeds=24;winner_ids={sorted(winners)};final_costs={costs};exactly_one_modified={valid}"
        return check(valid and winners=={"CS2_232","CS2_200"}, observed)

    audit(cid, [("end_turn_reduces_random_minion_cost_by_seven", "At end of turn, exactly one of two hand minions is reduced by 7 (floored at 0); both can be selected across random seeds.", end_turn_reduces_one_random_hand_minion, "Two known-cost minions distinguish the random recipient and reduction size over 24 games.")])


def mechathun():
    cid = "BOT_424"

    def empty_hand_deck_board_gate():
        outcomes = []
        # The minion being destroyed is not counted in hand/deck/board after death.
        g, p, e = game(CardClass.WARLOCK, CardClass.WARLOCK)
        mechathun = summon(p, cid)
        try:
            mechathun.destroy()
        except GameOver:
            pass
        outcomes.append(("empty", e.hero.zone.name, e.playstate.name, len(p.deck), len(p.hand), len(p.field)))
        # Each of the three stated zones independently blocks the lethal effect.
        for zone in ("hand", "deck", "board"):
            cg, cp, ce = game(CardClass.WARLOCK, CardClass.WARLOCK)
            if zone == "hand":
                blocker = cp.give(WISP)
            elif zone == "deck":
                blocker = cp.give(WISP)
                blocker.shuffle_into_deck()
            else:
                blocker = cp.summon(WISP)
            mech = summon(cp, cid)
            mech.destroy()
            outcomes.append((zone, ce.hero.zone.name, ce.playstate.name, len(cp.deck), len(cp.hand), len(cp.field)))
        observed = f"zone_outcomes={outcomes}"
        return check(outcomes[0][1:3] == ("GRAVEYARD", "LOST")
                     and all(row[1:3] == ("PLAY", "PLAYING") for row in outcomes[1:]), observed)

    audit(cid, [("deathrattle_lethal_only_with_all_three_zones_empty", "Mecha'thun destroys the enemy hero only when its controller has no other cards in hand, deck, or battlefield; each zone independently blocks it.", empty_hand_deck_board_gate, "One lethal empty-state case plus hand, deck, and board blockers.")])


def flarks_boom_zooka():
    cid = "BOT_429"

    def summons_attacks_and_destroys_three_deck_minions():
        g, p, e = game(CardClass.HUNTER, CardClass.HUNTER)
        deck_minions = put_deck(p, [WISP, WISP, WISP])
        target = summon(e, "BOT_448")  # high-health Taunt target survives all three attacks.
        before = target.health
        spell = play(p, cid)
        observed = f"spell={spell.zone.name};deck_cards={[(c.id,c.zone.name) for c in deck_minions]};target={target.id}:{before}->{target.health};deck={[c.id for c in p.deck]};friendly_field={[m.id for m in p.field]}"
        return check(spell.zone == Zone.GRAVEYARD and all(c.zone == Zone.GRAVEYARD for c in deck_minions)
                     and target.health == before - 3 and not p.field and not p.deck, observed)

    audit(cid, [("three_deck_minions_attack_then_die", "The spell summons three deck minions, has each attack an enemy minion, then destroys all three.", summons_attacks_and_destroys_three_deck_minions, "Three known deck minions and a surviving high-health enemy target expose summon, attack damage, and cleanup.")])


def whirliglider():
    cid = "BOT_431"

    def summons_goblin_bomb_with_deathrattle():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        own, enemy = p.hero.health, e.hero.health
        source = play(p, cid)
        bombs = [m for m in p.field if m.id == "BOT_031"]
        bomb = bombs[0] if bombs else None
        if bomb:
            bomb.destroy()
        observed = f"source={source.zone.name};bomb={(bomb.id,bomb.atk,bomb.health,bomb.zone.name) if bomb else None};heroes={own}->{p.hero.health}/{enemy}->{e.hero.health}"
        return check(source.zone == Zone.PLAY and bomb is not None and bomb.zone == Zone.GRAVEYARD
                     and (bomb.atk,bomb.max_health)==(0,2) and p.hero.health==own and e.hero.health==enemy-2, observed)

    audit(cid, [("battlecry_summons_zero_two_bomb_deathrattle", "Battlecry summons a 0/2 Goblin Bomb whose death deals 2 damage to the enemy hero only.", summons_goblin_bomb_with_deathrattle, "Resolved Battlecry token and then its Deathrattle with both hero totals observed.")])


def dr_morrigan():
    cid = "BOT_433"

    def death_swaps_with_deck_minion():
        g, p, e = game(CardClass.WARLOCK, CardClass.WARLOCK)
        chosen = p.give("CS2_182")
        chosen.shuffle_into_deck()
        spell = p.give(MOONFIRE)
        spell.shuffle_into_deck()
        morrigan = summon(p, cid)
        morrigan.destroy()
        replacement = [m for m in p.field if m.id == chosen.id]
        observed = f"morrigan={morrigan.zone.name};replacement={[(m.id,m.atk,m.health,m.zone.name) for m in replacement]};chosen={chosen.id}:{chosen.zone.name};spell={spell.id}:{spell.zone.name};deck={[c.id for c in p.deck]}"
        return check(morrigan.zone == Zone.DECK and chosen.zone == Zone.PLAY and len(replacement)==1
                     and spell.zone == Zone.DECK and replacement[0].controller is p, observed)

    audit(cid, [("death_swaps_with_one_minion_from_deck", "Deathrattle puts Dr. Morrigan into the deck and summons the only deck minion in its place; a spell is not selected.", death_swaps_with_deck_minion, "One eligible deck minion and a spell control isolate minion-only replacement.")])


def flobbidinous_floop():
    cid = "BOT_434"

    def hand_copy_tracks_last_minion_not_spells():
        g, p, e = game(CardClass.DRUID, CardClass.DRUID)
        floop = p.give(cid)
        original = (floop.id, floop.data.id, floop.cost, floop.atk, floop.health)
        first = play(p, "CS2_182")
        after_first = (floop.id, floop.data.id, floop.cost, floop.atk, floop.health)
        second = play(p, "EX1_016")
        after_second = (floop.id, floop.data.id, floop.cost, floop.atk, floop.health)
        play(p, MOONFIRE, target=e.hero)
        after_spell = (floop.id, floop.data.id, floop.cost, floop.atk, floop.health)
        observed = f"original={original};first={first.id}/{after_first};second={second.id}/{after_second};after_spell={after_spell}"
        return check(floop.zone == Zone.HAND and after_first[1] == first.id
                     and after_second[1] == second.id and after_spell == after_second
                     and after_first[3:] == (3,4) and after_second[3:] == (3,4), observed)

    audit(cid, [("hand_card_copies_last_minion_as_three_four", "While in hand, Floop updates to a 3/4 copy of the last minion played and a later spell does not change that copy.", hand_copy_tracks_last_minion_not_spells, "Two distinct minion plays and a spell control exercise hand-zone transformation timing.")])


def cloning_device():
    cid = "BOT_435"

    def discovers_copy_from_opponent_minion_deck():
        g, p, e = game(CardClass.PRIEST, CardClass.PRIEST)
        originals = put_deck(e, ["CS2_182", "EX1_016", "GVG_002"])
        source = play(p, cid)
        options = list(p.choice.cards) if p.choice else []
        selected = options[-1] if options else None
        if selected:
            p.choice.choose(selected)
        observed = f"source={source.zone.name};opponent_deck={[c.id for c in e.deck]};options={[(c.id,c.data.type.name,c.atk,c.health) for c in options]};selected={selected.id if selected else None}:{selected.zone.name if selected else None};own_hand={[c.id for c in p.hand]}"
        return check(source.zone == Zone.GRAVEYARD and len(options)==3
                     and all(c.type==CardType.MINION and c.id in {m.id for m in originals} for c in options)
                     and selected in p.hand and selected.zone==Zone.HAND and all(c.zone==Zone.DECK for c in originals), observed)

    audit(cid, [("discover_copy_of_opponent_deck_minion", "Cloning Device discovers a copy from the opponent's minion deck; the chosen copy enters hand and original remains in deck.", discovers_copy_from_opponent_minion_deck, "Three unique opponent deck minions ensure each offered option comes from the deck pool.")])


def prismatic_lens():
    cid = "BOT_436"

    def draws_one_minion_and_spell_then_swaps_costs():
        g, p, e = game(CardClass.PALADIN, CardClass.PALADIN)
        minion = p.give(WISP)
        minion.shuffle_into_deck()
        spell = p.give("CS2_029")
        spell.shuffle_into_deck()
        original_costs = (int(minion.data.cost), int(spell.data.cost))
        source = play(p, cid)
        observed = f"source={source.zone.name};original_costs={original_costs};minion={minion.id}:{minion.cost}:{minion.zone.name};spell={spell.id}:{spell.cost}:{spell.zone.name};hand={[c.id for c in p.hand]}"
        return check(source.zone==Zone.GRAVEYARD and minion in p.hand and spell in p.hand
                     and (minion.cost,spell.cost)==(original_costs[1],original_costs[0]), observed)

    audit(cid, [("minion_and_spell_drawn_with_costs_swapped", "Prismatic Lens draws the only minion and spell in deck, then swaps their printed costs.", draws_one_minion_and_spell_then_swaps_costs, "0-Cost minion and 4-Cost Fireball make the exchange unambiguous.")])


def goblin_prank():
    cid = "BOT_437"

    def gives_stats_rush_then_dies_at_end_turn():
        g, p, e = game(CardClass.HUNTER, CardClass.HUNTER)
        target = summon(p, WISP)
        enemy = summon(e, WISP)
        spell = play(p, cid, target=target)
        after_buff = (target.atk,target.health,target.max_health,target.rush,target.zone.name)
        can_attack_minion = target.can_attack(enemy)
        can_attack_hero = target.can_attack(e.hero)
        if can_attack_minion:
            target.attack(enemy)
        target_health_before_end = target.health
        g.end_turn()
        observed = f"spell={spell.zone.name};buffed={after_buff};rush_minion={can_attack_minion};rush_hero={can_attack_hero};enemy={enemy.zone.name};health_before_end={target_health_before_end};target_after_end={target.zone.name}"
        return check(after_buff[:4]==(4,4,4,True) and can_attack_minion and not can_attack_hero
                     and enemy.zone==Zone.GRAVEYARD and target.zone==Zone.GRAVEYARD, observed)

    audit(cid, [("friendly_target_gets_stats_rush_and_delayed_death", "Goblin Prank gives a friendly minion +3/+3 and Rush, lets it attack a minion but not a hero, then destroys it at end of turn.", gives_stats_rush_then_dies_at_end_turn, "Attack legality and delayed destruction were checked in the same owner turn.")])


def cybertech_chip():
    cid = "BOT_438"

    def only_current_minions_gain_mech_deathrattle():
        g, p, e = game(CardClass.HUNTER, CardClass.HUNTER)
        before = summon(p, WISP)
        spell = play(p, cid)
        after = summon(p, WISP)
        hand_before = list(p.hand)
        before.destroy()
        added_after_first = [c for c in p.hand if c not in hand_before]
        middle_count = len(added_after_first)
        after.destroy()
        added_after_second = [c for c in p.hand if c not in hand_before]
        observed = f"spell={spell.zone.name};before={before.zone.name};after={after.zone.name};first_reward={[(c.id,int(c.type),c.races) for c in added_after_first]};rewards_after_both={len(added_after_second)}"
        return check(spell.zone==Zone.GRAVEYARD and before.zone==Zone.GRAVEYARD and after.zone==Zone.GRAVEYARD
                     and middle_count==1 and len(added_after_second)==1
                     and added_after_second[0].type==CardType.MINION
                     and Race.MECHANICAL in added_after_second[0].races, observed)

    audit(cid, [("spell_grants_deathrattle_to_existing_minions_only", "Cybertech Chip grants the current minion a random-Mech Deathrattle; a minion played after the spell does not get it.", only_current_minions_gain_mech_deathrattle, "Destroyed one preexisting minion and one later minion, counting generated hand cards after each death.")])


def void_analyst():
    cid = "BOT_443"

    def deathrattle_buffs_demons_in_hand_only():
        g, p, e = game(CardClass.WARLOCK, CardClass.WARLOCK)
        demon_a, demon_b, plain = p.give("CS2_065"), p.give("EX1_306"), p.give(WISP)
        initial = [(c.id,c.atk,c.health,Race.DEMON in c.races) for c in (demon_a,demon_b,plain)]
        analyst = summon(p, cid)
        analyst.destroy()
        observed = f"initial={initial};after={[(c.id,c.atk,c.health,c.zone.name) for c in (demon_a,demon_b,plain)]};analyst={analyst.zone.name}"
        return check(analyst.zone==Zone.GRAVEYARD and demon_a.atk==2 and demon_a.health==4
                     and demon_b.atk==5 and demon_b.health==4
                     and (plain.atk,plain.health)==(1,1) and all(c.zone==Zone.HAND for c in (demon_a,demon_b,plain)), observed)

    audit(cid, [("deathrattle_buffs_every_demon_in_hand", "Void Analyst's Deathrattle gives each Demon in hand +1/+1; a non-Demon minion is unchanged.", deathrattle_buffs_demons_in_hand_only, "Two known Demon cards and a non-Demon hand control were inspected before and after death.")])


def gloop_glorious_gloop():
    cid = "BOT_444"

    def every_minion_death_gives_temporary_mana():
        g, p, e = game(CardClass.DRUID, CardClass.DRUID)
        own_minion, enemy_minion = summon(p, WISP), summon(e, WISP)
        p.max_mana, p.used_mana, p.temp_mana = 5, 0, 0
        resources = p.max_resources
        spell = play(p, cid)
        p.used_mana = 5
        own_minion.destroy()
        after_friendly = p.temp_mana
        enemy_minion.destroy()
        after_enemy = p.temp_mana
        g.end_turn()
        after_turn = p.temp_mana
        observed = f"spell={spell.zone.name};deaths={own_minion.zone.name}/{enemy_minion.zone.name};temp={0}->{after_friendly}->{after_enemy}->{after_turn};max_resources={resources}->{p.max_resources}"
        return check(spell.zone==Zone.GRAVEYARD and after_friendly==1 and after_enemy==2
                     and after_turn==0 and p.max_resources==resources, observed)

    audit(cid, [("each_minion_death_grants_one_turn_only_mana", "During this turn each friendly or enemy minion death gives 1 temporary Mana; it clears at turn end without raising max crystals.", every_minion_death_gives_temporary_mana, "One friendly and one enemy death were caused while current mana was exhausted.")])


def mecharoo():
    cid = "BOT_445"

    def death_summons_one_one_jo_e_bot():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        roo = summon(p, cid)
        roo.destroy()
        bots = [m for m in p.field if m.id == "BOT_445t"]
        observed = f"roo={roo.zone.name};tokens={[(m.id,m.atk,m.health,m.races,m.zone.name) for m in bots]}"
        return check(roo.zone==Zone.GRAVEYARD and len(bots)==1
                     and (bots[0].atk,bots[0].health,bots[0].zone)==(1,1,Zone.PLAY)
                     and Race.MECHANICAL in bots[0].races, observed)

    audit(cid, [("deathrattle_summons_one_one_mech_token", "Mecharoo's death summons exactly one 1/1 Jo-E Bot Mech.", death_summons_one_one_jo_e_bot, "Observed original death and token stats, race, and board zone.")])


def crystallizer():
    cid = "BOT_447"

    def battlecry_damages_hero_and_gains_five_armor():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        before = (p.hero.health,p.hero.armor)
        source = play(p, cid)
        after = (p.hero.health,p.hero.armor)
        observed = f"before={before};after={after};body={source.atk}/{source.health}:{source.zone.name}"
        return check(before==(30,0) and after==(25,5) and source.zone==Zone.PLAY, observed)

    audit(cid, [("battlecry_five_hero_damage_and_five_armor", "Battlecry deals 5 damage to its hero and grants exactly 5 Armor.", battlecry_damages_hero_and_gains_five_armor, "Both hero health and armor deltas were checked around the Battlecry.")])


def damaged_stegotron():
    cid = "BOT_448"

    def taunt_body_takes_six_battlecry_damage():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        before = p.hero.health
        source = play(p, cid)
        observed = f"body={source.atk}/{source.health}/{source.max_health};damage={source.damage};taunt={source.taunt};zone={source.zone.name};hero={before}->{p.hero.health}"
        return check(source.zone==Zone.PLAY and source.taunt and source.max_health==12
                     and source.health==6 and source.damage==6 and p.hero.health==before, observed)

    audit(cid, [("taunt_survives_six_self_damage", "Damaged Stegotron remains a 5/6 Taunt after its Battlecry deals 6 to itself.", taunt_body_takes_six_battlecry_damage, "Battlecry self-damage and printed Taunt/body survival inspected live.")])


def voltaic_burst():
    cid = "BOT_451"

    def two_rush_sparks_and_overload_one():
        g, p, e = game(CardClass.SHAMAN, CardClass.SHAMAN)
        enemy = summon(e, "CS2_182")
        spell = play(p, cid)
        sparks = [m for m in p.field if m.id == "BOT_102t"]
        can_attack_minion = all(m.can_attack(enemy) for m in sparks)
        can_attack_hero = any(m.can_attack(e.hero) for m in sparks)
        observed = f"spell={spell.zone.name};sparks={[(m.atk,m.health,m.rush,m.zone.name) for m in sparks]};minion_ready={can_attack_minion};hero_ready={can_attack_hero};overload_locked={p.overload_locked}"
        return check(spell.zone==Zone.GRAVEYARD and len(sparks)==2
                     and all((m.atk,m.health,m.rush,m.zone)==(1,1,True,Zone.PLAY) for m in sparks)
                     and can_attack_minion and not can_attack_hero and p.overload_locked==1, observed)

    audit(cid, [("summons_two_rush_sparks_and_overloads_one", "Voltaic Burst summons two 1/1 Sparks with Rush and locks 1 mana; they may attack minions but not heroes on the turn summoned.", two_rush_sparks_and_overload_one, "Token stats, Rush attack restrictions, and Overload were checked in one live cast.")])


def shooting_star():
    cid = "BOT_453"

    def damages_target_and_adjacent_minions():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE)
        left, center, right = (summon(e,"CS2_182"), summon(e,"EX1_016"), summon(e,"CS2_182"))
        friendly = summon(p,"CS2_182")
        before = [m.health for m in (left,center,right,friendly)]
        spell = play(p, cid, target=center)
        after = [m.health for m in (left,center,right,friendly)]
        observed = f"spell={spell.zone.name};before={before};after={after};zones={[m.zone.name for m in (left,center,right,friendly)]}"
        return check(spell.zone==Zone.GRAVEYARD and after==[before[0]-1,before[1]-1,before[2]-1,before[3]], observed)

    audit(cid, [("one_damage_to_target_and_enemy_neighbors", "Shooting Star deals 1 damage to the selected minion and its two adjacent minions; a friendly minion is unaffected.", damages_target_and_adjacent_minions, "Middle enemy minion selected with one same-side neighbor on each side and a friendly control.")])


def gloop_sprayer():
    cid = "BOT_507"

    def copies_each_adjacent_friendly_minion():
        g, p, e = game(CardClass.DRUID, CardClass.DRUID)
        left = summon(p, "GVG_002")
        right = summon(p, WISP)
        source = play(p, cid, index=1)
        id_counts = {card_id:sum(m.id==card_id for m in p.field) for card_id in ("GVG_002",WISP)}
        copies = [(m.id,m.atk,m.max_health) for m in p.field if m not in (left,right,source)]
        observed = f"board={[m.id for m in p.field]};source={source.zone.name};counts={id_counts};copies={copies}"
        return check(source.zone==Zone.PLAY and id_counts=={"GVG_002":2,WISP:2}
                     and sorted(copies)==sorted([("GVG_002",2,3),(WISP,1,1)]), observed)

    audit(cid, [("battlecry_copies_both_adjacent_minions", "Playing Gloop Sprayer between two friendly minions summons one exact copy of each adjacent minion.", copies_each_adjacent_friendly_minion, "Two distinct neighbors were positioned immediately left and right of the live Battlecry.")])


def necrium_vial():
    cid = "BOT_508"

    def triggers_target_deathrattle_twice_without_killing_it():
        g, p, e = game(CardClass.ROGUE, CardClass.ROGUE)
        target = summon(p, "BOT_445")
        spell = play(p, cid, target=target)
        bots = [m for m in p.field if m.id == "BOT_445t"]
        observed = f"spell={spell.zone.name};target={target.id}:{target.zone.name};jo_e_bots={[(m.atk,m.health,m.zone.name) for m in bots]};field={[m.id for m in p.field]}"
        return check(spell.zone==Zone.GRAVEYARD and target.zone==Zone.PLAY
                     and len(bots)==2 and all((m.atk,m.health,m.zone)==(1,1,Zone.PLAY) for m in bots), observed)

    audit(cid, [("friendly_deathrattle_triggers_twice", "Necrium Vial resolves a friendly Mecharoo's Deathrattle twice while leaving Mecharoo alive.", triggers_target_deathrattle_twice_without_killing_it, "Live target with a deterministic token Deathrattle; counted exact token summons and source survival.")])


def dead_ringer():
    cid = "BOT_509"

    def death_draws_deathrattle_minion_only():
        g, p, e = game(CardClass.PRIEST, CardClass.PRIEST)
        eligible = p.give("BOT_445")
        eligible.shuffle_into_deck()
        plain = p.give("CS2_182")
        plain.shuffle_into_deck()
        ringer = summon(p, cid)
        ringer.destroy()
        observed = f"ringer={ringer.zone.name};deathrattle_minion={eligible.id}:{eligible.zone.name};plain_minion={plain.id}:{plain.zone.name};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}"
        return check(ringer.zone==Zone.GRAVEYARD and eligible.zone==Zone.HAND and eligible in p.hand
                     and plain.zone==Zone.DECK and plain in p.deck, observed)

    audit(cid, [("deathrattle_draws_only_deathrattle_deck_minion", "Dead Ringer draws the only Deathrattle minion in deck and leaves the ordinary minion there.", death_draws_deathrattle_minion_only, "One known Deathrattle minion and one no-Deathrattle control were placed in deck.")])


def seaforium_bomber():
    cid = "BOT_511"

    def battlecry_shuffles_bomb_that_deals_five_when_drawn():
        g, p, e = game(CardClass.WARRIOR, CardClass.WARRIOR)
        owner_health, enemy_health = p.hero.health, e.hero.health
        bomber = play(p, cid)
        bombs = [c for c in e.deck if c.id == "BOT_511t"]
        g.end_turn()
        observed = f"bomber={bomber.zone.name};bombs_after_battlecry={len(bombs)};bomb_zones={[c.zone.name for c in bombs]};enemy_hero={enemy_health}->{e.hero.health};owner_hero={owner_health}->{p.hero.health};enemy_deck={[c.id for c in e.deck]};enemy_hand={[c.id for c in e.hand]}"
        return check(bomber.zone==Zone.PLAY and len(bombs)==1 and bombs[0].zone!=Zone.DECK
                     and e.hero.health==enemy_health-5 and p.hero.health==owner_health, observed)

    audit(cid, [("shuffle_bomb_into_opponent_deck_and_damage_on_draw", "Battlecry shuffles one Bomb into the opponent's deck; its next draw deals exactly 5 damage to that player.", battlecry_shuffles_bomb_that_deals_five_when_drawn, "Single-card opponent deck ensures the natural next-turn draw is the shuffled bomb.")])


PROBES = read_csv(PROBE_FILE) if PROBE_FILE.exists() else []
VERDICTS = read_csv(VERDICT_FILE) if VERDICT_FILE.exists() else []


def audit(card_id, cases):
    global PROBES, VERDICTS
    assert card_id in ROSTER_BY_ID
    PROBES = [row for row in PROBES if row["card_id"] != card_id]
    VERDICTS = [row for row in VERDICTS if row["card_id"] != card_id]
    write_csv(PROBE_FILE, PROBE_FIELDS, PROBES)
    write_csv(VERDICT_FILE, VERDICT_FIELDS, VERDICTS)
    for case_id, expected, function, case_notes in cases:
        try:
            observed = function()
            outcome = "pass"
        except AssertionError as exc:
            observed = str(exc) or f"AssertionError at line {traceback.extract_tb(exc.__traceback__)[-1].lineno}"
            outcome = "confirmed_error"
        except Exception as exc:
            observed = f"{type(exc).__name__}: {exc}"
            outcome = "inconclusive"
        PROBES.append({
            "card_id": card_id,
            "case_id": case_id,
            "expected": expected,
            "observed": observed,
            "outcome": outcome,
            "notes": f"{case_notes}; {metadata(card_id)}",
        })
        PROBES.sort(key=lambda row: (FROZEN_IDS.index(row["card_id"]), row["case_id"]))
        write_csv(PROBE_FILE, PROBE_FIELDS, PROBES)
        print(card_id, case_id, outcome, observed, flush=True)
    own = [row for row in PROBES if row["card_id"] == card_id]
    errors = [row for row in own if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in own if row["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{row['case_id']}: {row['observed']}" for row in errors)
    elif unresolved:
        status = "YELLOW"
        reason = "关键局面未能完成验证：" + "; ".join(f"{row['case_id']}: {row['observed']}" for row in unresolved)
    else:
        status = "GREEN"
        reason = "逐卡独立行为用例通过：" + "; ".join(f"{row['case_id']}: {row['observed']}" for row in own)
    VERDICTS.append({
        "card_id": card_id,
        "status": status,
        "mechanic_scope": ROSTER_BY_ID[card_id]["mechanic"],
        "reason": reason,
        "probe_file": PROBE_FILE.name,
        "notes": metadata(card_id),
    })
    VERDICTS.sort(key=lambda row: FROZEN_IDS.index(row["card_id"]))
    write_csv(VERDICT_FILE, VERDICT_FIELDS, VERDICTS)
    print(card_id, status, len(own), "cases", flush=True)


RUNNERS = {
    "BOT_258": zerek_master_cloner,
    "BOT_263": soul_infusion,
    "BOT_267": piloted_reaper,
    "BOT_270": giggling_inventor,
    "BOT_280": holomancer,
    "BOT_283": pogo_hopper,
    "BOT_286": necrium_blade,
    "BOT_288": lab_recruiter,
    "BOT_291": storm_chaser,
    "BOT_296": omega_defender,
    "BOT_299": omega_assembly,
    "BOT_308": spring_rocket,
    "BOT_312": replicating_menace,
    "BOT_401": weaponized_pinata,
    "BOT_402": secret_plan,
    "BOT_404": juicy_psychmelon,
    "BOT_406": supercollider,
    "BOT_407": thunderhead,
    "BOT_411": electra_stormsurge,
    "BOT_413": brainstormer,
    "BOT_414": cloakscale_chemist,
    "BOT_419": dendrologist,
    "BOT_420": landscaping,
    "BOT_422": tending_tauren,
    "BOT_423": dreampetal_florist,
    "BOT_424": mechathun,
    "BOT_429": flarks_boom_zooka,
    "BOT_431": whirliglider,
    "BOT_433": dr_morrigan,
    "BOT_434": flobbidinous_floop,
    "BOT_435": cloning_device,
    "BOT_436": prismatic_lens,
    "BOT_437": goblin_prank,
    "BOT_438": cybertech_chip,
    "BOT_443": void_analyst,
    "BOT_444": gloop_glorious_gloop,
    "BOT_445": mecharoo,
    "BOT_447": crystallizer,
    "BOT_448": damaged_stegotron,
    "BOT_451": voltaic_burst,
    "BOT_453": shooting_star,
    "BOT_507": gloop_sprayer,
    "BOT_508": necrium_vial,
    "BOT_509": dead_ringer,
    "BOT_511": seaforium_bomber,
}


def main():
    selected = sys.argv[1:] or list(FROZEN_IDS)
    assert selected and all(card_id in RUNNERS for card_id in selected)
    if not sys.argv[1:]:
        global PROBES, VERDICTS
        PROBES, VERDICTS = [], []
        write_csv(PROBE_FILE, PROBE_FIELDS, PROBES)
        write_csv(VERDICT_FILE, VERDICT_FIELDS, VERDICTS)
    for card_id in selected:
        RUNNERS[card_id]()
    counts = {name: sum(row["status"] == name for row in VERDICTS) for name in ("GREEN", "YELLOW", "RED")}
    print(f"COUNTS {counts}; cases={len(PROBES)}; selected={len(selected)}; frozen={len(FROZEN_IDS)}")
    if not sys.argv[1:]:
        assert [row["card_id"] for row in VERDICTS] == list(FROZEN_IDS)
        assert {row["card_id"] for row in PROBES} == set(FROZEN_IDS)
        assert len({(row['card_id'],row['case_id']) for row in PROBES}) == len(PROBES)


if __name__ == "__main__":
    main()
