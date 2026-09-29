"""Targeted live-game checks for frozen BLACK_TEMPLE YELLOW indices 45:90."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, MOONFIRE, THE_COIN, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "bt_probe_b.csv"
VERDICT_FILE = HERE / "bt_verdict_b.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


ROSTER_FULL = sorted((r for r in read(HERE / "remaining_yellow_baseline.csv")
                      if r["set"].endswith("(BLACK_TEMPLE)") and r["scope"] == "ordinary_collectible"),
                     key=lambda r: r["card_id"])
ROSTER = ROSTER_FULL[45:90]
assert len(ROSTER) == 45 and ROSTER[0]["card_id"] == "BT_138" and ROSTER[-1]["card_id"] == "BT_321"
assert len({r["card_id"] for r in ROSTER}) == 45
assert [r["card_id"] for r in ROSTER] == sorted(r["card_id"] for r in ROSTER)
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
PROBES = [r for r in read(PROBE_FILE) if r["card_id"] in ROSTER_BY_ID]
VERDICTS = [r for r in read(VERDICT_FILE) if r["card_id"] in ROSTER_BY_ID]


def game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=181):
    random.seed(seed)
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    p = (next(player for player in g.players if player.hero.card_class == class1)
         if class1 != class2 else g.player1)
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


def play(player, cid, target=None, index=None):
    card = player.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if index is not None:
        kw["index"] = index
    card.play(**kw)
    return card


def summon(player, cid):
    card = player.summon(cid)
    assert card is not None, f"could not summon {cid}"
    return card


def put_deck(player, cid, count=1):
    cards = []
    for _ in range(count):
        card = player.give(cid)
        card.shuffle_into_deck()
        cards.append(card)
    return cards


def end_round(g):
    g.end_turn()
    g.end_turn()


def check(ok, observed):
    assert ok, observed
    return observed


def meta(cid):
    m = MASTER[cid]
    b = ROSTER_BY_ID[cid]
    return (f"EN={m['card_text_en']}; ZH={m['card_text_zh']}; "
            f"source={m['python_source'] or m.get('xml_source', '')}; "
            f"existing_tests={m['test_refs_candidate'] or 'none'}; "
            f"prior={b['status']}:{b['reason']}; prior_evidence={b['evidence']}")


def audit(cid, tests):
    global PROBES, VERDICTS
    assert cid in ROSTER_BY_ID
    PROBES = [r for r in PROBES if r["card_id"] != cid]
    VERDICTS = [r for r in VERDICTS if r["card_id"] != cid]
    write(PROBE_FILE, PF, PROBES)
    write(VERDICT_FILE, VF, VERDICTS)
    for case_id, expected, func, notes in tests:
        try:
            observed = func()
            outcome = "pass"
        except AssertionError as exc:
            observed = str(exc) or f"AssertionError at {traceback.extract_tb(exc.__traceback__)[-1].lineno}"
            outcome = "confirmed_error"
        except Exception as exc:
            observed = f"{type(exc).__name__}: {exc}"
            outcome = "inconclusive"
        PROBES.append(dict(card_id=cid, case_id=case_id, expected=expected,
                           observed=observed, outcome=outcome, notes=f"{notes}; {meta(cid)}"))
        write(PROBE_FILE, PF, PROBES)
        print(cid, case_id, outcome, observed, flush=True)
    own = [r for r in PROBES if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own)
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in errors)
    elif unresolved:
        status = "YELLOW"
        reason = "具体未决探测：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in unresolved)
    else:
        status = "GREEN"
        reason = "逐卡关键行为断言通过：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in own)
    VERDICTS.append(dict(card_id=cid, status=status, mechanic_scope=ROSTER_BY_ID[cid]["mechanic"],
                         reason=reason, probe_file=PROBE_FILE.name, notes=meta(cid)))
    write(VERDICT_FILE, VF, VERDICTS)
    print(cid, status, len(own), "cases", flush=True)
    return status


def bloodboil_brute_discount_and_rush():
    cid = "BT_138"

    def each_damaged_minion_reduces_cost_and_brute_rushes():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=1381)
        brute = p.give(cid)
        printed_cost = brute.cost
        friend = summon(p, "CS2_182")
        foe = summon(e, "CS2_182")
        play(p, MOONFIRE, target=friend)
        play(p, MOONFIRE, target=foe)
        damaged_cost = brute.cost
        target = summon(e, WISP)
        body = brute.play()
        attack_error = None
        try:
            body.attack(target)
        except Exception as exc:
            attack_error = type(exc).__name__
        observed = (f"printed={printed_cost};damaged={friend.health}/{foe.health};cost={damaged_cost};"
                    f"body={body.zone.name}/{body.atk}/{body.health}/rush={body.tags[GameTag.RUSH]};"
                    f"attack_error={attack_error};target={target.zone.name};mana={p.mana}")
        return check(damaged_cost == max(0, printed_cost - 2) and body.zone == Zone.PLAY
                     and body.tags[GameTag.RUSH] and attack_error is None
                     and target.zone == Zone.GRAVEYARD, observed)

    def no_damaged_minions_preserves_printed_cost():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=1382)
        brute = p.give(cid)
        printed_cost = brute.cost
        observed = f"printed={printed_cost};current={brute.cost};friendly={list(p.field)};enemy={list(e.field)}"
        return check(brute.cost == printed_cost, observed)

    audit(cid, [
        ("two_damaged_minions_discount_two_and_rush_attacks", "Each of two damaged minions discounts Bloodboil Brute by 1; the played Brute retains Rush and immediately kills a Wisp.", each_damaged_minion_reduces_cost_and_brute_rushes, "Damage one friendly and one enemy Yeti, verify the exact two-point cost reduction, then play Brute and test its Rush attack."),
        ("zero_damaged_minions_no_discount", "With no damaged minions, Bloodboil Brute stays at its printed Cost.", no_damaged_minions_preserves_printed_cost, "Hold Brute on an empty board and compare live cost to the same entity's initial printed cost."),
    ])


bloodboil_brute_discount_and_rush.card_id = "BT_138"


def bonechewer_raider_conditionally_gains_stats_and_rush():
    cid = "BT_140"

    def damaged_minion_grants_one_one_and_rush():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1401)
        target = summon(e, "CS2_182")
        play(p, MOONFIRE, target=target)
        raider = p.give(cid)
        base = (raider.atk, raider.health)
        raider.play()
        after_battlecry = (raider.atk, raider.health, raider.max_health)
        enemy = summon(e, WISP)
        attack_error = None
        try:
            raider.attack(enemy)
        except Exception as exc:
            attack_error = type(exc).__name__
        observed = (f"damaged_enemy={target.health};base={base};after_battlecry={after_battlecry};"
                    f"raider={raider.zone.name}/{raider.atk}/{raider.health}/{raider.max_health}/"
                    f"rush={raider.tags[GameTag.RUSH]};attack_error={attack_error};enemy={enemy.zone.name}")
        return check(target.health == 4 and after_battlecry == (base[0]+1,base[1]+1,base[1]+1)
                     and raider.health == after_battlecry[1]-1
                     and raider.tags[GameTag.RUSH] and attack_error is None
                     and enemy.zone == Zone.GRAVEYARD, observed)

    def no_damaged_minion_leaves_base_body():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1402)
        raider = p.give(cid)
        base = (raider.atk, raider.health)
        raider.play()
        observed = f"base={base};body={raider.zone.name}/{raider.atk}/{raider.health};rush={raider.tags[GameTag.RUSH]}"
        return check((raider.atk,raider.health) == base and not raider.tags[GameTag.RUSH], observed)

    audit(cid, [
        ("damaged_minion_grants_plus_one_plus_one_and_rush", "With a damaged minion present, Bonechewer Raider gains +1/+1 and Rush and can attack a minion immediately.", damaged_minion_grants_one_one_and_rush, "Damage an enemy Yeti, then play Raider and verify its stat gain, Rush tag, and immediate minion attack."),
        ("no_damaged_minion_keeps_base_stats_and_no_rush", "Without a damaged minion, Bonechewer Raider receives neither the stat buff nor Rush.", no_damaged_minion_leaves_base_body, "Play Raider onto an undamaged empty board and compare the resulting stats and Rush tag with its held base stats."),
    ])


bonechewer_raider_conditionally_gains_stats_and_rush.card_id = "BT_140"


def scrapyard_colossus_taunt_deathrattle_summons_seven_seven():
    cid = "BT_155"

    def death_summons_taunt_felcracked_colossus():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1551)
        body = play(p, cid)
        taunt_before = body.tags[GameTag.TAUNT]
        body.destroy()
        tokens = [m for m in p.field if m.id == "BT_155t"]
        observed = (f"colossus={body.zone.name};taunt={taunt_before};"
                    f"tokens={[(m.id,m.atk,m.health,m.tags[GameTag.TAUNT],m.zone.name) for m in tokens]};"
                    f"board={[m.id for m in p.field]}")
        return check(taunt_before and body.zone == Zone.GRAVEYARD and len(tokens) == 1
                     and (tokens[0].atk,tokens[0].health) == (7,7)
                     and tokens[0].tags[GameTag.TAUNT], observed)

    audit(cid, [
        ("taunt_deathrattle_summons_one_seven_seven_taunt", "Scrapyard Colossus has Taunt and its Deathrattle summons exactly one 7/7 Taunt Felcracked Colossus.", death_summons_taunt_felcracked_colossus, "Verify printed Taunt, destroy the minion, and inspect its sole replacement token's ID, stats, and Taunt tag."),
    ])


scrapyard_colossus_taunt_deathrattle_summons_seven_seven.card_id = "BT_155"


def imprisoned_vilefiend_wakes_after_two_turns_with_rush():
    cid = "BT_156"

    def dormancy_counts_down_and_wake_allows_minion_attack():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1561)
        target = summon(e, WISP)
        body = play(p, cid)
        initial = (body.dormant, body.dormant_turns)
        end_round(g)
        after_first_owner_start = (body.dormant, body.dormant_turns)
        end_round(g)
        awake = (body.dormant, body.dormant_turns, body.zone.name)
        attack_error = None
        try:
            body.attack(target)
        except Exception as exc:
            attack_error = type(exc).__name__
        observed = (f"initial={initial};after_first={after_first_owner_start};awake={awake};"
                    f"rush={body.tags[GameTag.RUSH]};attack_error={attack_error};target={target.zone.name};"
                    f"body={body.zone.name}/{body.atk}/{body.health}")
        return check(initial == (True,2) and after_first_owner_start[0]
                     and not awake[0] and awake[2] == Zone.PLAY.name
                     and body.tags[GameTag.RUSH] and attack_error is None
                     and target.zone == Zone.GRAVEYARD, observed)

    audit(cid, [
        ("dormant_two_turns_then_rush_kills_enemy_minion", "Imprisoned Vilefiend remains Dormant through two of its owner's turn starts, wakes, and uses Rush to attack an enemy Wisp.", dormancy_counts_down_and_wake_allows_minion_attack, "Track both owner-turn boundaries explicitly, then test whether the awakened Rush minion can attack a minion on its waking turn."),
    ])


imprisoned_vilefiend_wakes_after_two_turns_with_rush.card_id = "BT_156"


def terrorguard_escapee_summons_three_huntresses_for_opponent():
    cid = "BT_159"

    def battlecry_gives_opponent_three_one_one_huntresses():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1591)
        body = play(p, cid)
        tokens = [m for m in e.field if m.id == "BT_159t"]
        observed = (f"body={body.zone.name};own={[m.id for m in p.field]};"
                    f"enemy={[(m.id,m.atk,m.health,m.zone.name) for m in e.field]};tokens={len(tokens)}")
        return check(body.zone == Zone.PLAY and len(tokens) == 3 and len(p.field) == 1
                     and all(m.atk == 1 and m.health == 1 and m.controller is e for m in tokens), observed)

    audit(cid, [
        ("battlecry_summons_three_one_one_tokens_for_opponent", "Terrorguard Escapee summons exactly three 1/1 Huntresses under the opponent's control.", battlecry_gives_opponent_three_one_one_huntresses, "Play Escapee onto an empty board and inspect the opposing token controller, count, and stats."),
    ])


terrorguard_escapee_summons_three_huntresses_for_opponent.card_id = "BT_159"


def rustsworn_cultist_gives_other_minions_demon_deathrattles():
    cid = "BT_160"

    def all_other_minions_receive_deathrattle_and_summon_demons():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1601)
        first, second = summon(p, WISP), summon(p, "CS2_182")
        cultist = play(p, cid, index=1)
        granted = (first.has_deathrattle, second.has_deathrattle, cultist.has_deathrattle)
        first.destroy()
        after_first = [m for m in p.field if m.id == "BT_160t"]
        second.destroy()
        tokens = [m for m in p.field if m.id == "BT_160t"]
        observed = (f"granted={granted};deaths={first.zone.name}/{second.zone.name};"
                    f"cultist={cultist.zone.name};after_first={[(m.id,m.atk,m.health,str(m.races)) for m in after_first]};"
                    f"tokens={[(m.id,m.atk,m.health,m.zone.name,str(m.races)) for m in tokens]}")
        return check(granted == (True,True,False) and len(after_first) == 1
                     and len(tokens) == 2 and all(m.atk == 1 and m.health == 1
                                                   and Race.DEMON in m.races and m.zone == Zone.PLAY for m in tokens), observed)

    audit(cid, [
        ("gives_each_other_minion_deathrattle_summoning_one_one_demon", "Rustsworn Cultist grants its two other friendly minions Deathrattles; each death summons a 1/1 Demon, while Cultist itself gets none.", all_other_minions_receive_deathrattle_and_summon_demons, "With two existing friendly minions, play Cultist between them; verify both but not Cultist gain Deathrattle, then kill each and count Demon tokens."),
    ])


rustsworn_cultist_gives_other_minions_demon_deathrattles.card_id = "BT_160"


def nagrand_slam_summons_four_clefthoofs_that_attack():
    cid = "BT_163"

    def all_four_tokens_attack_only_opposing_hero_when_no_minions():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=1631)
        spell = play(p, cid)
        tokens = [m for m in p.field if m.id == "BT_163t"]
        observed = (f"spell={spell.zone.name};enemy_hero={e.hero.health};"
                    f"tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]};"
                    f"own={[m.id for m in p.field]};enemy={[m.id for m in e.field]}")
        return check(spell.zone == Zone.GRAVEYARD and len(tokens) == 4
                     and all((m.atk,m.health)==(3,5) and m.zone == Zone.PLAY for m in tokens)
                     and e.hero.health == 18 and not e.field, observed)

    def tokens_can_attack_a_minion_before_remaining_attacks_hit_hero():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=1633)
        target = summon(e, WISP)
        spell = play(p, cid)
        tokens = [m for m in p.field if m.id == "BT_163t"]
        observed = (f"spell={spell.zone.name};hero={e.hero.health};target={target.zone.name};"
                    f"tokens={[(m.atk,m.health,m.zone.name) for m in tokens]};"
                    f"enemy_field={[m.id for m in e.field]}")
        return check(spell.zone==Zone.GRAVEYARD and target.zone==Zone.GRAVEYARD
                     and e.hero.health==21 and len(tokens)==4
                     and sum(m.health==4 for m in tokens)==1
                     and sum(m.health==5 for m in tokens)==3, observed)

    audit(cid, [
        ("summons_four_three_five_clefthoofs_and_deals_twelve_to_lone_hero", "Nagrand Slam summons four 3/5 Clefthoofs; with no enemy minions, each attacks the enemy hero for a total of 12 damage.", all_four_tokens_attack_only_opposing_hero_when_no_minions, "Cast with only the opposing hero as a legal enemy; count all four token bodies and verify their scripted attacks total 12 hero damage."),
        ("random_attacks_can_kill_minion_then_continue_to_hero", "With an enemy Wisp and hero available, Nagrand Slam's random attacks can kill the Wisp and send the remaining three attacks to face.", tokens_can_attack_a_minion_before_remaining_attacks_hit_hero, "Use deterministic seed1633 with a live enemy Wisp; verify one 3/5 token loses 1 health in the Wisp trade, the Wisp dies, and the remaining attacks total9 to the hero."),
    ])


nagrand_slam_summons_four_clefthoofs_that_attack.card_id = "BT_163"


def kayn_sunfury_charge_and_friendly_attacks_ignore_taunt():
    cid = "BT_187"

    def aura_lets_ready_friend_attack_hero_past_taunt():
        g, p, e = game(CardClass.DEMONHUNTER, CardClass.MAGE, seed=1871)
        friend = summon(p, WISP)
        taunt = summon(e, "CS2_121")
        end_round(g)
        kayn = play(p, cid)
        before = e.hero.health
        attack_error = None
        try:
            friend.attack(e.hero)
        except Exception as exc:
            attack_error = type(exc).__name__
        observed = (f"kayn={kayn.zone.name}/charge={kayn.tags[GameTag.CHARGE]};"
                    f"friend_ignore_taunt={friend.tags[GameTag.IGNORE_TAUNT]};"
                    f"taunt={taunt.zone.name}/{taunt.tags[GameTag.TAUNT]};"
                    f"attack_error={attack_error};enemy_hero={before}->{e.hero.health}")
        return check(kayn.tags[GameTag.CHARGE] and friend.tags[GameTag.IGNORE_TAUNT]
                     and taunt.zone == Zone.PLAY and taunt.tags[GameTag.TAUNT]
                     and attack_error is None and e.hero.health == before - friend.atk, observed)

    audit(cid, [
        ("charge_kayn_grants_friendly_attacks_ignore_taunt", "Kayn has Charge and lets a ready friendly Wisp attack the enemy hero despite an enemy Taunt minion.", aura_lets_ready_friend_attack_hero_past_taunt, "Set an enemy Taunt, ready a friendly Wisp, play Kayn, and assert both the live Ignore-Taunt tag and successful hero attack."),
    ])


kayn_sunfury_charge_and_friendly_attacks_ignore_taunt.card_id = "BT_187"


def shadowjeweler_hanar_discovers_off_class_secret_after_secret():
    cid = "BT_188"

    def playing_rogue_secret_offers_other_class_secrets():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=1881)
        hanar = play(p, cid)
        rogue_secret = play(p, "BT_707")  # Ambush
        choice = p.choice
        options = list(choice.cards) if choice else []
        option_info = [(c.id,c.card_class,c.type,c.tags[GameTag.SECRET]) for c in options]
        chosen = options[0] if options else None
        if chosen:
            choice.choose(chosen)
        in_hand = [c for c in p.hand if chosen is not None and c.id == chosen.id]
        observed = (f"hanar={hanar.zone.name};rogue_secret={rogue_secret.zone.name}/"
                    f"controller_class={p.hero.card_class};options={option_info};"
                    f"chosen={chosen.id if chosen else None};hand={[(c.id,c.zone.name) for c in in_hand]};"
                    f"choice_after={bool(p.choice)};secrets={[c.id for c in p.secrets]}")
        return check(hanar.zone == Zone.PLAY and rogue_secret.zone == Zone.SECRET
                     and len(options) == 3 and all(c.type == CardType.SPELL and c.tags[GameTag.SECRET]
                                                    and c.card_class != CardClass.ROGUE for c in options)
                     and chosen is not None and len(in_hand) == 1 and p.choice is None, observed)

    audit(cid, [
        ("playing_secret_discovers_three_secrets_from_other_classes", "After a Rogue plays Ambush, Hanar offers three Secret spells from non-Rogue classes and the selected Secret enters hand.", playing_rogue_secret_offers_other_class_secrets, "Play Rogue Hanar then the Rogue Ambush secret; inspect Discover options' spell type, Secret tag, class identities, and selected hand result."),
    ])


shadowjeweler_hanar_discovers_off_class_secret_after_secret.card_id = "BT_188"


def replicat_o_tron_transforms_sole_adjacent_neighbor_at_turn_end():
    cid = "BT_190"

    def neighbor_becomes_exact_copy_but_far_minion_stays():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=1901)
        left = summon(p, WISP)
        replicator = summon(p, cid)
        right = summon(p, WISP)
        distant = summon(p, "CS2_182")
        end_round(g)
        copies = [m for m in p.field if m.id == cid]
        observed = (f"field={[(m.id,m.atk,m.health,m.zone.name) for m in p.field]};"
                    f"old_neighbors={left.id}/{left.zone.name},{right.id}/{right.zone.name};replicator={replicator.zone.name};"
                    f"distant={distant.id}/{distant.atk}/{distant.health}/{distant.zone.name};"
                    f"copies={len(copies)};turn_owner={g.current_player is e}")
        return check(len(copies) == 2 and all((m.atk,m.health)==(3,3) for m in copies)
                     and distant.id == "CS2_182" and distant.zone == Zone.PLAY
                     and (distant.atk,distant.health)==(4,5), observed)

    audit(cid, [
        ("end_of_turn_transforms_neighbor_and_leaves_distant_minion", "At its controller's end of turn, Replicat-o-tron transforms one adjacent Wisp into an exact 3/3 copy, leaving a distant Yeti unchanged.", neighbor_becomes_exact_copy_but_far_minion_stays, "Place two adjacent Wisps around Replicat-o-tron and a Yeti beyond one adjacent Wisp; end the turn and inspect current board entities rather than stale pre-Morph references."),
    ])


replicat_o_tron_transforms_sole_adjacent_neighbor_at_turn_end.card_id = "BT_190"


def kelidan_breaker_drawn_turn_destroys_all_other_minions():
    cid = "BT_196"

    def ordinary_hand_play_destroys_only_selected_target():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=1961)
        ally = summon(p, WISP)
        target = summon(e, "CS2_182")
        other = summon(e, WISP)
        kelidan = play(p, cid, target=target)
        observed = (f"kelidan={kelidan.zone.name};ally={ally.zone.name};target={target.zone.name};"
                    f"other={other.zone.name};fields={[m.id for m in p.field]}/{[m.id for m in e.field]}")
        return check(kelidan.zone == Zone.PLAY and ally.zone == Zone.PLAY
                     and target.zone == Zone.GRAVEYARD and other.zone == Zone.PLAY, observed)

    def drawn_this_turn_kelidan_clears_both_boards():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=1962)
        ally = summon(p, "CS2_182")
        enemy_minions = [summon(e, WISP), summon(e, "CS2_182")]
        original = put_deck(p, cid)[0]
        drawn = p.draw()
        drawn_zone = drawn.zone
        drawn_flag = bool(drawn.drawn_this_turn)
        powered_up = bool(drawn.powered_up)
        kelidan = drawn.play()
        observed = (f"drawn={drawn.id}/{drawn_zone.name}/same_deck_entity={drawn is original};"
                    f"drawn_this_turn={drawn_flag}/powered_up={powered_up};kelidan={kelidan.zone.name};"
                    f"ally={ally.zone.name};enemies={[m.zone.name for m in enemy_minions]};"
                    f"pfield={[m.id for m in p.field]};efield={[m.id for m in e.field]};deck={original.zone.name}")
        return check(drawn is original and drawn_zone == Zone.HAND and drawn_flag and powered_up
                     and drawn.zone == Zone.PLAY and kelidan.zone == Zone.PLAY
                     and ally.zone == Zone.GRAVEYARD and all(m.zone == Zone.GRAVEYARD for m in enemy_minions)
                     and p.field == [kelidan] and not e.field, observed)

    audit(cid, [
        ("not_drawn_this_turn_destroys_selected_minion_only", "A normally held Keli'dan destroys the selected enemy minion and leaves other minions alive.", ordinary_hand_play_destroys_only_selected_target, "Play Keli'dan already in hand with a chosen enemy Yeti and an unrelated enemy Wisp; check target-specific destruction."),
        ("drawn_this_turn_battlecry_destroys_all_other_minions", "When Keli'dan is drawn this turn, its Battlecry destroys every other minion on both boards without requiring a target.", drawn_this_turn_kelidan_clears_both_boards, "Shuffle the exact Keli'dan entity into deck, draw it during this turn, verify its drawn-this-turn tag, then play without a target amid friendly/enemy minions."),
    ])


kelidan_breaker_drawn_turn_destroys_all_other_minions.card_id = "BT_196"


def reliquary_of_souls_lifesteal_and_deathrattle_prime_shuffle():
    cid = "BT_197"

    def lifesteal_heals_hero_and_death_shuffles_prime():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=1971)
        p.hero.set_current_health(25)
        body = summon(p, cid)
        lifesteal = body.tags[GameTag.LIFESTEAL]
        end_round(g)
        ready = body.can_attack()
        attack_error = None
        try:
            body.attack(e.hero)
        except Exception as exc:
            attack_error = type(exc).__name__
        health_after_hit = p.hero.health
        body.destroy()
        primes = [c for c in p.deck if c.id == "BT_197t"]
        observed = (f"lifesteal={lifesteal};ready_after_own_turn={ready};attack_error={attack_error};"
                    f"enemy_hero={e.hero.health};"
                    f"own_hero={25}->{health_after_hit};body={body.zone.name};"
                    f"prime={[c.zone.name for c in primes]};deck={[c.id for c in p.deck]}")
        return check(lifesteal and ready and attack_error is None and e.hero.health == 29
                     and health_after_hit == 26 and body.zone == Zone.GRAVEYARD
                     and len(primes) == 1 and primes[0].zone == Zone.DECK, observed)

    audit(cid, [
        ("lifesteal_attack_heals_and_deathrattle_shuffles_prime", "After Reliquary is ready on its owner's next turn, its 1-damage Lifesteal attack heals its hero by 1, and its death shuffles one Reliquary Prime into the deck.", lifesteal_heals_hero_and_death_shuffles_prime, "Start own hero at25, summon Reliquary, complete both turns until its own next turn, assert can_attack before attacking, then destroy it and check exact Prime deck insertion."),
    ])


reliquary_of_souls_lifesteal_and_deathrattle_prime_shuffle.card_id = "BT_197"


def soul_mirror_summons_enemy_copy_and_they_fight():
    cid = "BT_198"

    def enemy_and_summoned_copy_exchange_combat_damage():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=1981)
        original = summon(e, "EX1_045")  # Ancient Watcher 4/5
        spell = play(p, cid)
        copies = [m for m in p.field if m.id == "EX1_045"]
        observed = (f"spell={spell.zone.name};original={original.id}/{original.zone.name}/{original.health};"
                    f"copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};"
                    f"boards={[m.id for m in p.field]}/{[m.id for m in e.field]}")
        return check(spell.zone == Zone.GRAVEYARD and original.zone == Zone.PLAY
                     and original.health == 1 and len(copies) == 1
                     and copies[0].zone == Zone.PLAY and (copies[0].atk,copies[0].health)==(4,1), observed)

    def copies_and_fights_every_enemy_minion():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=1982)
        original_watcher = summon(e, "EX1_045")
        original_yeti = summon(e, "CS2_182")
        spell = play(p, cid)
        copies = list(p.field)
        observed = (f"spell={spell.zone.name};originals={[(m.id,m.zone.name,m.atk,m.health) for m in (original_watcher,original_yeti)]};"
                    f"copies={[(m.id,m.zone.name,m.atk,m.health) for m in copies]};"
                    f"boards={[m.id for m in p.field]}/{[m.id for m in e.field]}")
        return check(spell.zone==Zone.GRAVEYARD
                     and all(m.zone==Zone.PLAY and (m.atk,m.health)==(4,1)
                             for m in (original_watcher,original_yeti))
                     and len(copies)==2 and {m.id for m in copies}=={"EX1_045","CS2_182"}
                     and all(m.zone==Zone.PLAY and (m.atk,m.health)==(4,1) for m in copies)
                     and len(e.field)==2, observed)

    audit(cid, [
        ("summons_copy_of_enemy_minion_and_makes_them_fight", "Soul Mirror summons a 4/5 copy of the enemy Ancient Watcher and both exchange 4 damage, leaving each at 1 Health.", enemy_and_summoned_copy_exchange_combat_damage, "Use the actual EX1_045 4/5 Ancient Watcher with only 4 attack to ensure the original and its summoned copy survive the reciprocal attack with observable damage."),
        ("copies_and_fights_all_enemy_minions", "Soul Mirror creates a copy of each enemy minion and each copy attacks its matching original.", copies_and_fights_every_enemy_minion, "Set up two distinct enemy 4/5 minions (Ancient Watcher and Yeti); verify both original entities and both friendly copies survive at 4/1, proving the all-enemies loop handles multiple targets."),
    ])


soul_mirror_summons_enemy_copy_and_they_fight.card_id = "BT_198"


def unstable_felbolt_hits_enemy_target_and_one_random_friendly_minion():
    cid = "BT_199"

    def damages_enemy_target_and_exactly_one_friendly_minion():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=1991)
        friendlies = [summon(p, "CS2_182"), summon(p, "CS2_182")]
        enemy = summon(e, "CS2_182")
        spell = play(p, cid, target=enemy)
        friendly_damage = [m.damage for m in friendlies]
        observed = (f"spell={spell.zone.name};enemy={enemy.zone.name}/{enemy.health}/damage={enemy.damage};"
                    f"friendlies={[(m.id,m.zone.name,m.health,m.damage) for m in friendlies]};"
                    f"friendly_damage={friendly_damage};heroes={p.hero.health}/{e.hero.health}")
        return check(spell.zone == Zone.GRAVEYARD and enemy.zone == Zone.PLAY and enemy.damage == 3
                     and sorted(friendly_damage) == [0,3]
                     and all(m.zone == Zone.PLAY for m in friendlies), observed)

    audit(cid, [
        ("deals_three_to_enemy_target_and_one_random_friendly_minion", "Unstable Felbolt deals 3 to the chosen enemy Yeti and 3 to exactly one of two friendly Yetis, selected randomly.", damages_enemy_target_and_exactly_one_friendly_minion, "Use multiple surviving friendly minions so only one random recipient is damaged, and separately verify the chosen enemy target receives exactly 3."),
    ])


unstable_felbolt_hits_enemy_target_and_one_random_friendly_minion.card_id = "BT_199"


def augmented_porcupine_deathrattle_splits_attack_damage_among_enemies():
    cid = "BT_201"

    def total_enemy_damage_equals_porcupines_attack():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2011)
        enemies = [summon(e, "CS2_182"), summon(e, "CS2_182")]
        before_hero = e.hero.health
        before_damage = [m.damage for m in enemies]
        porcupine = summon(p, cid)
        atk = porcupine.atk
        porcupine.destroy()
        dealt = before_hero - e.hero.health + sum(m.damage-b for m,b in zip(enemies,before_damage))
        observed = (f"atk={atk};porcupine={porcupine.zone.name};enemy_hero={before_hero}->{e.hero.health};"
                    f"minions={[(m.id,m.zone.name,m.health,m.damage) for m in enemies]};total_damage={dealt}")
        return check(porcupine.zone == Zone.GRAVEYARD and all(m.zone == Zone.PLAY for m in enemies)
                     and dealt == atk, observed)

    audit(cid, [
        ("deathrattle_deals_exact_attack_damage_split_among_enemy_characters", "On death, Augmented Porcupine deals a total of its Attack value as randomly distributed 1-damage hits among enemy characters.", total_enemy_damage_equals_porcupines_attack, "Keep two high-health enemy minions alive alongside the enemy hero; destroy Porcupine and sum actual damage across all enemy characters."),
    ])


augmented_porcupine_deathrattle_splits_attack_damage_among_enemies.card_id = "BT_201"


def helboar_deathrattle_buffs_random_beast_in_hand_only():
    cid = "BT_202"

    def one_of_two_beasts_gets_plus_one_plus_one():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2021)
        beasts = [p.give("CS2_172"), p.give("EX1_543")]
        nonbeast = p.give("CS2_182")
        before = [(c.atk,c.health) for c in beasts]
        other_before = (nonbeast.atk,nonbeast.health)
        body = summon(p, cid)
        body.destroy()
        changes = [(c.atk-before[i][0],c.health-before[i][1]) for i,c in enumerate(beasts)]
        observed = (f"body={body.zone.name};beasts={[(c.id,c.zone.name,c.atk,c.health) for c in beasts]};"
                    f"before={before};changes={changes};nonbeast={nonbeast.id}/{nonbeast.atk}/{nonbeast.health}/"
                    f"before={other_before};races={[str(c.races) for c in beasts]}")
        return check(all(Race.BEAST in c.races for c in beasts) and Race.BEAST not in nonbeast.races
                     and changes.count((1,1)) == 1 and changes.count((0,0)) == 1
                     and (nonbeast.atk,nonbeast.health) == other_before, observed)

    def no_beast_in_hand_has_no_buff_target():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2022)
        held = [p.give("CS2_182"), p.give("CS2_231")]
        before = [(c.atk,c.health) for c in held]
        body = summon(p, cid)
        body.destroy()
        after = [(c.atk,c.health) for c in held]
        observed = f"body={body.zone.name};held={[(c.id,c.atk,c.health) for c in held]};before={before};after={after}"
        return check(after == before, observed)

    audit(cid, [
        ("deathrattle_buffs_one_random_beast_and_no_other_card", "Helboar gives +1/+1 to exactly one of two Beast cards in hand and does not buff a non-Beast.", one_of_two_beasts_gets_plus_one_plus_one, "Hold two known Beast minions and a Yeti; after the Deathrattle compare before/after stats and require exactly one Beast to change."),
        ("no_beast_in_hand_has_no_effect", "With no Beast in hand, Helboar's Deathrattle changes no held minion stats.", no_beast_in_hand_has_no_buff_target, "Repeat its death with only non-Beast cards in hand and verify no card gains stats."),
    ])


helboar_deathrattle_buffs_random_beast_in_hand_only.card_id = "BT_202"


def pack_tactics_summons_three_three_copy_when_friend_is_attacked():
    cid = "BT_203"

    def secret_reveals_and_summons_three_three_copy():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2031)
        defender = summon(p, "CS2_182")
        attacker = summon(e, WISP)
        secret = play(p, cid)
        g.end_turn()
        attack_error = None
        try:
            attacker.attack(defender)
        except Exception as exc:
            attack_error = type(exc).__name__
        copies = [m for m in p.field if m.id == "CS2_182" and m is not defender]
        observed = (f"secret={secret.zone.name};attack_error={attack_error};attacker={attacker.zone.name};"
                    f"defender={defender.zone.name}/{defender.health}/{defender.max_health};"
                    f"copies={[(m.id,m.atk,m.health,m.max_health,m.zone.name) for m in copies]};"
                    f"boards={[m.id for m in p.field]}/{[m.id for m in e.field]}")
        return check(attack_error is None and secret.zone == Zone.GRAVEYARD
                     and attacker.zone == Zone.GRAVEYARD and defender.zone == Zone.PLAY
                     and defender.health == 4 and len(copies) == 1
                     and (copies[0].atk,copies[0].health,copies[0].max_health)==(3,3,3), observed)

    audit(cid, [
        ("friendly_minion_attack_reveals_secret_and_summons_three_three_copy", "When the enemy Wisp attacks a friendly Yeti, Pack Tactics reveals and summons a 3/3 copy of the attacked Yeti.", secret_reveals_and_summons_three_three_copy, "Trigger the secret with an actual enemy minion attack; verify reveal, attacker combat, surviving original, and the 3/3 token stats."),
    ])


pack_tactics_summons_three_three_copy_when_friend_is_attacked.card_id = "BT_203"


def scrap_shot_damages_target_and_buffs_random_beast_in_hand():
    cid = "BT_205"

    def damages_target_and_only_one_beast_gets_three_three():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2051)
        beasts = [p.give("CS2_172"), p.give("EX1_543")]
        nonbeast = p.give("CS2_182")
        before = [(c.atk,c.health) for c in beasts]
        other_before = (nonbeast.atk,nonbeast.health)
        target = summon(e, "CS2_182")
        spell = play(p, cid, target=target)
        changes = [(c.atk-before[i][0],c.health-before[i][1]) for i,c in enumerate(beasts)]
        observed = (f"spell={spell.zone.name};target={target.zone.name}/{target.health}/damage={target.damage};"
                    f"beasts={[(c.id,c.atk,c.health,c.zone.name) for c in beasts]};before={before};"
                    f"changes={changes};nonbeast={nonbeast.id}/{nonbeast.atk}/{nonbeast.health};before={other_before}")
        return check(target.zone == Zone.PLAY and target.damage == 3
                     and changes.count((3,3)) == 1 and changes.count((0,0)) == 1
                     and all(Race.BEAST in c.races for c in beasts) and Race.BEAST not in nonbeast.races
                     and (nonbeast.atk,nonbeast.health)==other_before, observed)

    audit(cid, [
        ("deals_three_and_randomly_buffs_one_beast_by_three_three", "Scrap Shot deals 3 to the chosen Yeti and gives +3/+3 to exactly one of two Beast cards in hand, leaving the non-Beast unchanged.", damages_target_and_only_one_beast_gets_three_three, "Hold two verified Beast minions and a non-Beast, target a surviving enemy Yeti, then compare spell damage and hand-card stats."),
    ])


scrap_shot_damages_target_and_buffs_random_beast_in_hand.card_id = "BT_205"


def zixor_rushes_and_deathrattle_shuffles_prime_into_deck():
    cid = "BT_210"

    def rush_kill_then_death_shuffles_one_prime():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2101)
        target = summon(e, WISP)
        zixor = play(p, cid)
        attack_error = None
        try:
            zixor.attack(target)
        except Exception as exc:
            attack_error = type(exc).__name__
        after_attack = (zixor.zone.name,zixor.health,target.zone.name)
        zixor.destroy()
        primes = [c for c in p.deck if c.id == "BT_210t"]
        observed = (f"rush={zixor.tags[GameTag.RUSH]};attack_error={attack_error};"
                    f"after_attack={after_attack};zixor={zixor.zone.name};"
                    f"primes={[(c.id,c.zone.name) for c in primes]};deck={[c.id for c in p.deck]}")
        return check(zixor.tags[GameTag.RUSH] and attack_error is None
                     and target.zone == Zone.GRAVEYARD and zixor.zone == Zone.GRAVEYARD
                     and len(primes) == 1 and primes[0].zone == Zone.DECK, observed)

    audit(cid, [
        ("rush_minion_kills_wisp_and_deathrattle_shuffles_zixor_prime", "Zixor can use Rush to kill an enemy Wisp and its Deathrattle shuffles one Zixor Prime into its controller's deck.", rush_kill_then_death_shuffles_one_prime, "Play into an enemy Wisp, confirm immediate Rush combat, kill Zixor, and count exactly one prime card in deck."),
    ])


zixor_rushes_and_deathrattle_shuffles_prime_into_deck.card_id = "BT_210"


def imprisoned_felmaw_awaken_attacks_the_only_enemy_character():
    cid = "BT_211"

    def dormancy_expires_then_attacks_enemy_hero():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2111)
        felmaw = play(p, cid)
        initial = (felmaw.dormant,felmaw.dormant_turns)
        end_round(g)
        after_first = (felmaw.dormant,felmaw.dormant_turns)
        end_round(g)
        after_wake = (felmaw.dormant,felmaw.dormant_turns,felmaw.zone.name)
        observed = (f"initial={initial};after_first={after_first};wake={after_wake};"
                    f"atk={felmaw.atk};enemy_hero={e.hero.health};enemy_minions={list(e.field)};"
                    f"body={felmaw.zone.name}/{felmaw.health}")
        return check(initial == (True,2) and after_first == (True,1)
                     and after_wake == (False,0,Zone.PLAY.name)
                     and e.hero.health == 30-felmaw.atk and not e.field
                     and felmaw.zone == Zone.PLAY, observed)

    def random_attack_after_awakening_can_hit_enemy_minion():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2115)
        target = summon(e, WISP)
        felmaw = play(p, cid)
        end_round(g)
        end_round(g)
        observed = (f"felmaw={felmaw.zone.name}/{felmaw.atk}/{felmaw.health}/"
                    f"dormant={felmaw.dormant}/{felmaw.dormant_turns};"
                    f"target={target.zone.name};hero={e.hero.health};enemy_field={[m.id for m in e.field]}")
        return check(felmaw.zone==Zone.PLAY and not felmaw.dormant and felmaw.dormant_turns==0
                     and target.zone==Zone.GRAVEYARD and e.hero.health==30
                     and felmaw.health==3, observed)

    audit(cid, [
        ("after_two_turns_awakens_and_random_attacks_only_enemy_hero", "Imprisoned Felmaw stays Dormant for two owner-turn starts, then awakens and attacks the sole enemy character, the hero.", dormancy_expires_then_attacks_enemy_hero, "With no enemy minions, its random attack target is deterministic; verify dormancy countdown, awakening, and exact hero damage."),
        ("after_two_turns_random_attack_can_hit_enemy_minion", "When a Wisp is present alongside the enemy hero, awakened Felmaw can attack the random minion and take its 1 damage.", random_attack_after_awakening_can_hit_enemy_minion, "Use deterministic seed2115 with an enemy Wisp plus hero; check the Wisp dies, hero remains30, and awakened Felmaw is at3 health after combat."),
    ])


imprisoned_felmaw_awaken_attacks_the_only_enemy_character.card_id = "BT_211"


def moknathal_lion_rush_copies_friendly_deathrattle():
    cid = "BT_212"

    def copied_deathrattle_triggers_on_lion_and_source():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2121)
        source = summon(p, "BT_155")
        lion = play(p, cid, target=source)
        enemy = summon(e, WISP)
        attack_error = None
        try:
            lion.attack(enemy)
        except Exception as exc:
            attack_error = type(exc).__name__
        lion_has_dr = lion.has_deathrattle
        lion.destroy()
        after_lion = [m for m in p.field if m.id == "BT_155t"]
        source.destroy()
        tokens = [m for m in p.field if m.id == "BT_155t"]
        observed = (f"lion={lion.zone.name}/{lion.atk}/{lion.health};rush={lion.tags[GameTag.RUSH]};"
                    f"attack_error={attack_error};enemy={enemy.zone.name};lion_dr={lion_has_dr};"
                    f"source={source.zone.name};after_lion={len(after_lion)};"
                    f"tokens={[(m.id,m.atk,m.health,m.tags[GameTag.TAUNT],m.zone.name) for m in tokens]}")
        return check(lion.tags[GameTag.RUSH] and attack_error is None and enemy.zone == Zone.GRAVEYARD
                     and lion_has_dr and lion.zone == Zone.GRAVEYARD and source.zone == Zone.GRAVEYARD
                     and len(after_lion) == 1 and len(tokens) == 2
                     and all((m.atk,m.health)==(7,7) and m.tags[GameTag.TAUNT] for m in tokens), observed)

    audit(cid, [
        ("rush_lion_copies_and_triggers_friendly_colossus_deathrattle", "Mok'Nathal Lion uses Rush and copies the friendly Scrapyard Colossus Deathrattle; both deaths summon a 7/7 Taunt.", copied_deathrattle_triggers_on_lion_and_source, "Target an actual friendly Deathrattle minion, test Lion's immediate Rush attack, then kill both bodies and count the copied outcomes."),
    ])


moknathal_lion_rush_copies_friendly_deathrattle.card_id = "BT_212"


def scavengers_ingenuity_draws_and_buffs_beast():
    cid = "BT_213"

    def draws_beast_from_nonbeast_mixed_deck_and_buffs_it():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2131)
        beast = put_deck(p, "CS2_172")[0]
        nonbeast = put_deck(p, "CS2_182")[0]
        base = (beast.atk,beast.health)
        spell = play(p, cid)
        observed = (f"spell={spell.zone.name};beast={beast.id}/{beast.zone.name}/{beast.atk}/{beast.health};"
                    f"base={base};nonbeast={nonbeast.id}/{nonbeast.zone.name}/{nonbeast.atk}/{nonbeast.health};"
                    f"hand={[(c.id,c.atk,c.health,c.zone.name) for c in p.hand]};deck={[c.id for c in p.deck]}")
        return check(Race.BEAST in beast.races and beast.zone == Zone.HAND
                     and (beast.atk,beast.health)==(base[0]+2,base[1]+2)
                     and nonbeast.zone == Zone.DECK, observed)

    audit(cid, [
        ("draws_beast_and_gives_two_two_while_nonbeast_remains_deck", "Scavenger's Ingenuity draws the deck's Beast and gives it +2/+2, leaving a non-Beast in the deck.", draws_beast_from_nonbeast_mixed_deck_and_buffs_it, "Mix one known Beast and a non-Beast in deck; cast and inspect exact draw, stat buff, and untouched non-Beast zone."),
    ])


scavengers_ingenuity_draws_and_buffs_beast.card_id = "BT_213"


def beastmaster_leoroxx_summons_three_beasts_from_hand():
    cid = "BT_214"

    def summons_all_three_beasts_and_leaves_nonbeast_in_hand():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2141)
        beasts = [p.give("CS2_172"), p.give("CS2_119"), p.give("EX1_543")]
        nonbeast = p.give("CS2_182")
        body = play(p, cid)
        observed = (f"body={body.zone.name};beasts={[(c.id,c.zone.name,c.atk,c.health,str(c.races)) for c in beasts]};"
                    f"nonbeast={nonbeast.id}/{nonbeast.zone.name};field={[(m.id,m.atk,m.health) for m in p.field]};"
                    f"hand={[c.id for c in p.hand]}")
        return check(body.zone == Zone.PLAY and all(Race.BEAST in c.races for c in beasts)
                     and all(c.zone == Zone.PLAY and c.controller is p for c in beasts)
                     and nonbeast.zone == Zone.HAND and len([m for m in p.field if m is not body]) == 3, observed)

    def chooses_three_of_four_beasts_and_leaves_one_in_hand():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=2142)
        beasts = [p.give("CS2_172"), p.give("CS2_119"), p.give("EX1_543"), p.give("CS2_125")]
        nonbeast = p.give("CS2_182")
        body = play(p, cid)
        summoned = [c for c in beasts if c.zone==Zone.PLAY]
        remaining = [c for c in beasts if c.zone==Zone.HAND]
        observed = (f"body={body.zone.name};beasts={[(c.id,c.zone.name,c.atk,c.health,str(c.races)) for c in beasts]};"
                    f"summoned={[c.id for c in summoned]};remaining={[c.id for c in remaining]};"
                    f"nonbeast={nonbeast.id}/{nonbeast.zone.name};field={[m.id for m in p.field]}")
        return check(body.zone==Zone.PLAY and len(summoned)==3
                     and all(Race.BEAST in c.races and c.controller is p for c in summoned)
                     and len(remaining)==1 and Race.BEAST in remaining[0].races
                     and nonbeast.zone==Zone.HAND, observed)

    audit(cid, [
        ("battlecry_summons_three_beasts_and_not_nonbeast", "Beastmaster Leoroxx summons all three held Beast minions onto the board and leaves the held Yeti in hand.", summons_all_three_beasts_and_leaves_nonbeast_in_hand, "Hold exactly three verified Beast minions plus a non-Beast; play Leoroxx and verify the three selected hand entities move to play."),
        ("more_than_three_beasts_summons_exactly_three", "With four Beast candidates, Leoroxx summons three of them and leaves the fourth Beast plus the non-Beast in hand.", chooses_three_of_four_beasts_and_leaves_one_in_hand, "Hold four verified Beast minions plus a Yeti; inspect all original entity zones after the Battlecry to test the three-minion cap and selection from excess eligible cards."),
    ])


beastmaster_leoroxx_summons_three_beasts_from_hand.card_id = "BT_214"


def the_lurker_below_chain_hits_one_neighbor_after_kill():
    cid = "BT_230"

    def killing_target_repeats_three_damage_on_one_neighbor():
        g, p, e = game(CardClass.SHAMAN, CardClass.MAGE, seed=2301)
        left = summon(e, "CS2_182")
        target = summon(e, WISP)
        right = summon(e, "CS2_182")
        far = summon(e, WISP)
        lurker = play(p, cid, target=target)
        neighbor_damages = [left.damage,right.damage]
        observed = (f"lurker={lurker.zone.name};target={target.zone.name};"
                    f"neighbors={[(m.id,m.zone.name,m.health,m.damage) for m in (left,right)]};"
                    f"neighbor_damages={neighbor_damages};far={far.zone.name}/{far.damage};")
        return check(target.zone == Zone.GRAVEYARD and neighbor_damages.count(3) == 1
                     and neighbor_damages.count(0) == 1 and left.zone == right.zone == Zone.PLAY
                     and far.zone == Zone.PLAY and far.damage == 0, observed)

    audit(cid, [
        ("enemy_target_death_repeats_once_on_one_neighbor", "The Lurker Below deals 3 to the selected Wisp, kills it, then deals 3 to one adjacent Yeti only; a farther Wisp is untouched.", killing_target_repeats_three_damage_on_one_neighbor, "Arrange enemy board left-Yeti / target-Wisp / right-Yeti / far-Wisp; check the initial kill, one neighbor repeat, and chain stopping on the surviving Yeti."),
    ])


the_lurker_below_chain_hits_one_neighbor_after_kill.card_id = "BT_230"


def sword_and_board_deals_two_and_gains_two_armor():
    cid = "BT_233"

    def selected_minion_takes_two_and_hero_gains_two_armor():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=2331)
        target = summon(e, "CS2_182")
        armor_before = p.hero.armor
        spell = play(p, cid, target=target)
        observed = (f"spell={spell.zone.name};target={target.zone.name}/{target.health}/damage={target.damage};"
                    f"armor={armor_before}->{p.hero.armor};heroes={p.hero.health}/{e.hero.health}")
        return check(spell.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY
                     and target.health == 3 and target.damage == 2
                     and p.hero.armor == armor_before+2 and e.hero.health == 30, observed)

    audit(cid, [
        ("deals_two_to_target_and_gains_two_armor", "Sword and Board deals 2 damage to the chosen Yeti and grants its Warrior 2 Armor.", selected_minion_takes_two_and_hero_gains_two_armor, "Record armor before casting at a 5-health Yeti; assert exactly two damage and exactly two Armor."),
    ])


sword_and_board_deals_two_and_gains_two_armor.card_id = "BT_233"


def scrap_golem_deathrattle_gains_armor_equal_to_attack():
    cid = "BT_249"

    def taunt_death_gains_attack_value_armor():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=2491)
        golem = summon(p, cid)
        attack = golem.atk
        taunt = golem.tags[GameTag.TAUNT]
        golem.destroy()
        observed = f"attack={attack};taunt={taunt};dead={golem.zone.name};armor={p.hero.armor};field={[m.id for m in p.field]}"
        return check(taunt and golem.zone == Zone.GRAVEYARD and p.hero.armor == attack, observed)

    audit(cid, [
        ("taunt_deathrattle_gains_armor_equal_to_golem_attack", "Scrap Golem has Taunt and its Deathrattle grants Armor equal to its Attack.", taunt_death_gains_attack_value_armor, "Snapshot its actual Attack and Taunt tag, destroy it, and compare hero Armor to that exact Attack value."),
    ])


scrap_golem_deathrattle_gains_armor_equal_to_attack.card_id = "BT_249"


def renew_restores_three_and_discovers_spell():
    cid = "BT_252"

    def heals_hero_and_adds_chosen_discovered_spell():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2521)
        p.hero.set_current_health(25)
        spell = play(p, cid, target=p.hero)
        healed = p.hero.health
        choice = p.choice
        options = list(choice.cards) if choice else []
        chosen = options[0] if options else None
        if chosen:
            choice.choose(chosen)
        in_hand = [c for c in p.hand if chosen is not None and c.id == chosen.id]
        observed = (f"renew={spell.zone.name};hero=25->{healed};options={[(c.id,c.type,c.cost) for c in options]};"
                    f"chosen={chosen.id if chosen else None};hand={[(c.id,c.zone.name) for c in in_hand]};choice={bool(p.choice)}")
        return check(healed == 28 and spell.zone == Zone.GRAVEYARD and len(options) == 3
                     and all(c.type == CardType.SPELL for c in options)
                     and chosen is not None and len(in_hand) == 1 and p.choice is None, observed)

    audit(cid, [
        ("restores_three_health_and_discovered_spell_enters_hand", "Renew restores 3 Health to the damaged hero, discovers three spells, and the chosen spell enters hand.", heals_hero_and_adds_chosen_discovered_spell, "Damage own hero to25, cast Renew on it, inspect actual healing and all Discover choices, then choose one and verify the hand result."),
    ])


renew_restores_three_and_discovers_spell.card_id = "BT_252"


def psyche_split_buffs_friendly_minion_and_summons_copy():
    cid = "BT_253"

    def target_and_copy_both_have_plus_one_plus_two_stats():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2531)
        target = summon(p, WISP)
        before = (target.atk, target.health, target.max_health)
        spell = play(p, cid, target=target)
        copies = [m for m in p.field if m.id == WISP]
        observed = (f"spell={spell.zone.name};before={before};target={target.zone.name}/{target.atk}/{target.health}/"
                    f"{target.max_health}/damage={target.damage};"
                    f"wisps={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};"
                    f"field={[m.id for m in p.field]}")
        return check(spell.zone == Zone.GRAVEYARD and len(copies) == 2
                     and all((m.atk,m.health)==(2,3) and m.zone == Zone.PLAY for m in copies), observed)

    audit(cid, [
        ("buffs_target_one_two_and_summons_buffed_copy", "Psyche Split buffs a friendly 1/1 Wisp to 2/3 and summons a second 2/3 copy.", target_and_copy_both_have_plus_one_plus_two_stats, "Target a live friendly Wisp, verify spell resolution and both entities' attack/current/max health. CardDefs.xml BT_253e contains only CARDNAME/CARDTEXT/CARD_SET/CLASS/CARDTYPE, with no ATK or HEALTH enchant values; check that the Python Buff action still applies the promised +1/+2."),
    ])


psyche_split_buffs_friendly_minion_and_summons_copy.card_id = "BT_253"


def sethekk_veilweaver_generates_priest_spell_only_on_minion_spell():
    cid = "BT_254"

    def spell_targeting_minion_adds_one_priest_spell():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2541)
        veilweaver = summon(p, cid)
        target = summon(p, WISP)
        cast = p.give("BT_257")
        before = list(p.hand)
        cast.play(target=target)
        generated = [c for c in p.hand if c not in before]
        observed = (f"veilweaver={veilweaver.zone.name};cast={cast.zone.name};target={target.atk}/{target.health};"
                    f"generated={[(c.id,c.type,c.card_class,c.zone.name) for c in generated]};hand={[c.id for c in p.hand]}")
        return check(cast.zone == Zone.GRAVEYARD and (target.atk,target.health)==(3,4)
                     and len(generated) == 1 and generated[0].type == CardType.SPELL
                     and generated[0].card_class == CardClass.PRIEST and generated[0].zone == Zone.HAND, observed)

    def spell_targeting_hero_does_not_generate_priest_spell():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2542)
        veilweaver = summon(p, cid)
        cast = p.give("EX1_624")  # Holy Fire; can target a hero
        enemy_health_before = e.hero.health
        before = list(p.hand)
        cast.play(target=e.hero)
        generated = [c for c in p.hand if c not in before]
        observed = (f"veilweaver={veilweaver.zone.name};cast={cast.zone.name};"
                    f"enemy_hero={enemy_health_before}->{e.hero.health};"
                    f"generated={[(c.id,c.type,c.card_class) for c in generated]};hand={[c.id for c in p.hand]}")
        return check(cast.zone == Zone.GRAVEYARD and e.hero.health == enemy_health_before - 5
                     and not generated, observed)

    audit(cid, [
        ("priest_spell_on_minion_adds_priest_spell", "After a Priest spell targets a minion, Sethekk adds exactly one Priest spell to hand.", spell_targeting_minion_adds_one_priest_spell, "Cast Apotheosis on a minion with Sethekk active; filter new hand entities by object identity and verify one is a Priest spell."),
        ("priest_spell_on_hero_adds_no_spell", "Casting a Priest spell on a hero does not trigger Sethekk's minion-targeted effect.", spell_targeting_hero_does_not_generate_priest_spell, "Cast the Priest Holy Fire EX1_624 at the enemy hero while Sethekk is active; verify its five damage resolves but no newly added hand card appears. CS2_012 is a Druid spell in this card set and is not a valid identity fixture."),
    ])


sethekk_veilweaver_generates_priest_spell_only_on_minion_spell.card_id = "BT_254"


def kaelthas_makes_every_third_spell_each_turn_free():
    cid = "BT_255"

    def third_spell_is_free_and_counter_resets_on_next_turn():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=2551)
        kael = summon(p, cid)
        costs = []
        for _ in range(3):
            spell = p.give("CS2_029")
            costs.append(spell.cost)
            spell.play(target=e.hero)
        enemy_after_three = e.hero.health
        end_round(g)
        next_spell = p.give("CS2_029")
        observed = (f"kael={kael.zone.name}/{kael.atk}/{kael.health};costs={costs};"
                    f"enemy_after_three={enemy_after_three};next_turn_used_mana={p.used_mana};"
                    f"fourth_cost={next_spell.cost};")
        return check(costs == [4, 4, 0] and enemy_after_three == 12
                     and p.used_mana == 0 and next_spell.cost == 4, observed)

    audit(cid, [
        ("third_spell_free_and_turn_counter_resets", "The first two Fireballs cost 4, the third costs 0, and the first spell next turn costs 4 again.", third_spell_is_free_and_counter_resets_on_next_turn, "Put Kael'thas in play with an otherwise fresh spell count, cast three real Fireballs at the enemy hero while recording each live hand cost, then pass a full round and check the count reset."),
    ])


kaelthas_makes_every_third_spell_each_turn_free.card_id = "BT_255"


def dragonmaw_overseer_buffs_one_other_friendly_at_end_turn():
    cid = "BT_256"

    def exactly_one_of_two_other_minions_gets_plus_two_plus_two():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2561)
        overseer = summon(p, cid)
        candidates = [summon(p, WISP), summon(p, "CS2_182")]
        before = [(m.atk, m.health) for m in candidates]
        overseer_before = (overseer.atk, overseer.health)
        end_round(g)
        after = [(m.atk, m.health) for m in candidates]
        buffed = [i for i, (old, new) in enumerate(zip(before, after))
                  if new == (old[0] + 2, old[1] + 2)]
        observed = (f"before={before};after={after};buffed_indexes={buffed};"
                    f"overseer={overseer_before}->{(overseer.atk,overseer.health)}")
        return check(len(buffed) == 1 and all(
            after[i] == (before[i][0] + 2, before[i][1] + 2) if i in buffed else after[i] == before[i]
            for i in range(2)) and (overseer.atk,overseer.health) == overseer_before, observed)

    def no_other_friendly_minion_does_not_buff_self():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2562)
        overseer = summon(p, cid)
        before = (overseer.atk, overseer.health)
        end_round(g)
        observed = f"before={before};after={(overseer.atk,overseer.health)};field={[m.id for m in p.field]}"
        return check((overseer.atk, overseer.health) == before, observed)

    audit(cid, [
        ("end_turn_buffs_exactly_one_other_minion", "At the owner's end of turn exactly one of two other friendly minions gets +2/+2; the Overseer does not buff itself.", exactly_one_of_two_other_minions_gets_plus_two_plus_two, "Put Overseer beside a Wisp and Yeti, end its turn, and compare each live minion's attack and health before and after the trigger."),
        ("no_other_minion_means_no_self_buff", "With no other friendly minion, Dragonmaw Overseer remains at base stats.", no_other_friendly_minion_does_not_buff_self, "End a turn with only the Overseer in play and assert no self-buff occurs."),
    ])


dragonmaw_overseer_buffs_one_other_friendly_at_end_turn.card_id = "BT_256"


def apotheosis_buffs_minion_and_lifesteal_heals_on_attack():
    cid = "BT_257"

    def plus_two_plus_three_lifesteal_heals_actual_attack_damage():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2571)
        p.hero.set_current_health(25)
        body = summon(p, WISP)
        spell = play(p, cid, target=body)
        stats_after_spell = (body.atk, body.health, body.max_health)
        lifesteal = body.tags[GameTag.LIFESTEAL]
        end_round(g)
        ready = body.can_attack()
        error = None
        try:
            body.attack(e.hero)
        except Exception as exc:
            error = type(exc).__name__
        observed = (f"spell={spell.zone.name};stats={stats_after_spell};lifesteal={lifesteal};"
                    f"ready={ready};attack_error={error};own_hero={p.hero.health};enemy_hero={e.hero.health}")
        return check(stats_after_spell == (3, 4, 4) and lifesteal and ready and error is None
                     and p.hero.health == 28 and e.hero.health == 27, observed)

    audit(cid, [
        ("buffs_two_three_and_lifesteal_heals_attack_damage", "Apotheosis gives a friendly Wisp +2/+3 and Lifesteal; its ready 3-Attack minion heals the hero by 3 when it attacks face.", plus_two_plus_three_lifesteal_heals_actual_attack_damage, "Start the Priest hero at25, cast Apotheosis on a real Wisp, check its attack/health/Lifesteal, wait until it is attack-ready, then attack the opposing hero and verify exact healing."),
    ])


apotheosis_buffs_minion_and_lifesteal_heals_on_attack.card_id = "BT_257"


def imprisoned_homunculus_wakes_with_taunt_after_two_turns():
    cid = "BT_258"

    def dormant_counts_down_and_taunt_blocks_enemy_hero_attack():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2581)
        attacker = summon(e, WISP)
        body = play(p, cid)
        initial = (body.tags[GameTag.DORMANT], body.dormant, body.dormant_turns,
                   body.tags[GameTag.TAUNT])
        end_round(g)
        after_one = (body.dormant, body.dormant_turns, body.zone.name)
        end_round(g)
        after_two = (body.dormant, body.dormant_turns, body.zone.name, body.tags[GameTag.TAUNT])
        g.end_turn()
        hero_attack_error = None
        try:
            attacker.attack(p.hero)
        except Exception as exc:
            hero_attack_error = type(exc).__name__
        minion_attack_error = None
        try:
            attacker.attack(body)
        except Exception as exc:
            minion_attack_error = type(exc).__name__
        observed = (f"initial={initial};after_one={after_one};after_two={after_two};"
                    f"hero_attack_error={hero_attack_error};minion_attack_error={minion_attack_error};"
                    f"attacker={attacker.zone.name};body={body.zone.name}/{body.health};"
                    f"hero_health={p.hero.health}")
        return check(initial[0] and initial[2] == 2 and initial[3] and after_one[0]
                     and after_one[1] == 1 and after_two[0] is False and after_two[1] == 0
                     and after_two[2] == Zone.PLAY.name and after_two[3]
                     and hero_attack_error == "InvalidAction" and minion_attack_error is None
                     and body.zone == Zone.PLAY and body.health == 4 and p.hero.health == 30, observed)

    audit(cid, [
        ("dormant_two_turns_then_taunt_blocks_hero", "Imprisoned Homunculus stays Dormant through one owner turn, awakens after two, and its Taunt forces the enemy Wisp to attack it instead of face.", dormant_counts_down_and_taunt_blocks_enemy_hero_attack, "Play Homunculus while an enemy Wisp is present, advance two complete rounds, check the live Dormant counter and Taunt after awakening, then assert a hero attack is rejected and the legal attack damages the 2/5 body."),
    ])


imprisoned_homunculus_wakes_with_taunt_after_two_turns.card_id = "BT_258"


def dragonmaw_sentinel_powered_up_by_dragon_in_hand():
    cid = "BT_262"

    def held_dragon_grants_attack_and_lifesteal():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2621)
        p.hero.set_current_health(25)
        dragon = p.give("EX1_561")
        sentinel = play(p, cid)
        stats = (sentinel.atk, sentinel.health)
        lifesteal = sentinel.tags[GameTag.LIFESTEAL]
        end_round(g)
        ready = sentinel.can_attack()
        error = None
        try:
            sentinel.attack(e.hero)
        except Exception as exc:
            error = type(exc).__name__
        observed = (f"held={dragon.id}/{dragon.type}/{dragon.race};"
                    f"sentinel={sentinel.zone.name}/{stats};lifesteal={lifesteal};ready={ready};"
                    f"attack_error={error};own_hero={p.hero.health};enemy_hero={e.hero.health}")
        return check(dragon.race == Race.DRAGON and stats == (2, 4)
                     and lifesteal and ready and error is None and p.hero.health == 27
                     and e.hero.health == 28, observed)

    def no_dragon_in_hand_leaves_base_body_without_lifesteal():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=2622)
        other = p.give("CS2_182")
        sentinel = play(p, cid)
        observed = (f"held={other.id}/{other.race};"
                    f"sentinel={sentinel.zone.name}/{sentinel.atk}/{sentinel.health};"
                    f"lifesteal={sentinel.tags[GameTag.LIFESTEAL]}")
        return check(other.race != Race.DRAGON and (sentinel.atk, sentinel.health) == (1, 4)
                     and not sentinel.tags[GameTag.LIFESTEAL], observed)

    audit(cid, [
        ("held_dragon_grants_plus_one_attack_and_lifesteal", "Holding a Dragon makes Dragonmaw Sentinel a 2/4 with Lifesteal; its ready attack heals its owner by 2.", held_dragon_grants_attack_and_lifesteal, "Hold an actual Race.DRAGON minion in hand, play Sentinel, inspect its body and Lifesteal tag, wait for attack readiness, and verify both hero health changes."),
        ("no_dragon_leaves_one_four_without_lifesteal", "Without a Dragon in hand, Dragonmaw Sentinel remains a 1/4 and has no Lifesteal.", no_dragon_in_hand_leaves_base_body_without_lifesteal, "Hold a non-Dragon Yeti, play Sentinel, and compare its body and Lifesteal tag to its unpowered form."),
    ])


dragonmaw_sentinel_powered_up_by_dragon_in_hand.card_id = "BT_262"


def apexis_blast_summons_five_cost_minion_only_if_deck_has_no_minions():
    cid = "BT_291"

    def empty_of_minions_deck_summons_five_cost_minion_after_damage():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=2911)
        spell_only = put_deck(p, "CS2_029")[0]
        target = summon(e, "CS2_182")
        cast = play(p, cid, target=target)
        summoned = list(p.field)
        observed = (f"spell={cast.zone.name};target={target.zone.name}/{target.health};"
                    f"deck={[c.id for c in p.deck]};spell_only={spell_only.id}/{spell_only.zone.name};"
                    f"summoned={[(m.id,m.cost,m.atk,m.health,m.zone.name) for m in summoned]}")
        return check(target.zone == Zone.GRAVEYARD and not any(c.type == CardType.MINION for c in p.deck)
                     and len(summoned) == 1 and summoned[0].zone == Zone.PLAY
                     and summoned[0].cost == 5, observed)

    def minion_in_deck_prevents_summon():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=2912)
        minion = put_deck(p, "CS2_182")[0]
        target = summon(e, "CS2_182")
        cast = play(p, cid, target=target)
        observed = (f"spell={cast.zone.name};target={target.zone.name}/{target.health};"
                    f"deck={[c.id for c in p.deck]};minion={minion.zone.name};pfield={[m.id for m in p.field]}")
        return check(target.zone == Zone.GRAVEYARD and minion in p.deck and p.field == [], observed)

    audit(cid, [
        ("no_minion_deck_summons_random_five_cost_minion", "Apexis Blast deals 5 to its target and, with no minion in deck, summons one 5-Cost minion.", empty_of_minions_deck_summons_five_cost_minion_after_damage, "Leave only a spell in Mage's deck, target a five-health Yeti so the 5 damage is observable, then check the resolved summon is exactly one 5-Cost minion."),
        ("minion_in_deck_suppresses_summon", "If Mage's deck still contains a minion, Apexis Blast deals 5 but summons no minion.", minion_in_deck_prevents_summon, "Put a known Yeti in deck, target a separate enemy Yeti, and verify the deck minion remains while no friendly body appears."),
    ])


apexis_blast_summons_five_cost_minion_only_if_deck_has_no_minions.card_id = "BT_291"


def hand_of_adal_buffs_friendly_minion_and_draws():
    cid = "BT_292"

    def target_gets_two_two_and_top_card_enters_hand():
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=2921)
        target = summon(p, WISP)
        deck_cards = [put_deck(p, card_id)[0] for card_id in ("CS2_182", "CS2_029")]
        before = list(p.hand)
        spell = play(p, cid, target=target)
        new_cards = [c for c in p.hand if c not in before]
        remaining = [c for c in deck_cards if any(c is top for top in p.deck)]
        observed = (f"spell={spell.zone.name};target={target.atk}/{target.health};"
                    f"deck_entities={[(c.id,c.zone.name) for c in deck_cards]};"
                    f"new={[(c.id,c.zone.name) for c in new_cards]};"
                    f"deck={[c.id for c in p.deck]};hero={p.hero.health}")
        return check(target.zone == Zone.PLAY and (target.atk,target.health)==(3,3)
                     and len(new_cards)==1 and new_cards[0] in deck_cards
                     and new_cards[0].zone==Zone.HAND and len(remaining)==1
                     and spell.zone==Zone.GRAVEYARD and p.hero.health==30, observed)

    audit(cid, [
        ("buffs_friendly_minion_and_draws_exactly_one", "Hand of A'dal gives its friendly Wisp +2/+2 and draws exactly one card into hand, leaving a second sentinel in deck.", target_gets_two_two_and_top_card_enters_hand, "Target a live friendly Wisp with a Yeti and Fireball in deck; verify exact target stats, exactly one of those entities in hand, the other still in deck, and no fatigue."),
    ])


hand_of_adal_buffs_friendly_minion_and_draws.card_id = "BT_292"


def hand_of_guldan_draws_three_when_played_or_discarded():
    cid = "BT_300"

    def playing_card_draws_three_cards():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3001)
        deck_ids = ["CS2_029", "CS2_182", WISP, "CS2_179"]
        deck_cards = [put_deck(p, card_id)[0] for card_id in deck_ids]
        before = list(p.hand)
        spell = play(p, cid)
        new_cards = [c for c in p.hand if c not in before]
        observed = (f"spell={spell.zone.name};drawn={[(c.id,c.zone.name) for c in new_cards]};"
                    f"deck={[c.id for c in p.deck]};original_deck={[c.id for c in deck_cards]}")
        remaining = [c for c in deck_cards if any(c is top for top in p.deck)]
        return check(spell.zone == Zone.GRAVEYARD and len(new_cards)==3
                     and all(c in p.hand for c in deck_cards if c not in remaining)
                     and len(remaining)==1 and p.hero.health==30, observed)

    def discarding_card_draws_three_cards():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3002)
        deck_ids = ["CS2_029", "CS2_182", WISP, "CS2_179"]
        deck_cards = [put_deck(p, card_id)[0] for card_id in deck_ids]
        spell = p.give(cid)
        before = list(p.hand)
        spell.discard()
        new_cards = [c for c in p.hand if c not in before]
        observed = (f"discarded={spell.zone.name};drawn={[(c.id,c.zone.name) for c in new_cards]};"
                    f"deck={[c.id for c in p.deck]};original_deck={[c.id for c in deck_cards]}")
        remaining = [c for c in deck_cards if any(c is top for top in p.deck)]
        return check(spell.zone == Zone.REMOVEDFROMGAME and len(new_cards)==3
                     and all(c in p.hand for c in deck_cards if c not in remaining)
                     and len(remaining)==1 and p.hero.health==30, observed)

    audit(cid, [
        ("playing_hand_of_guldan_draws_three", "Playing Hand of Gul'dan draws exactly 3 cards and leaves the fourth sentinel card in deck.", playing_card_draws_three_cards, "Play Hand of Gul'dan with four known cards in deck; verify exactly three original entities enter hand, one sentinel remains in deck, and no fatigue damage occurs."),
        ("discarding_hand_of_guldan_draws_three", "Discarding Hand of Gul'dan also draws exactly 3 cards and leaves the fourth sentinel card in deck.", discarding_card_draws_three_cards, "Discard Hand of Gul'dan with four known cards in deck; inspect the exact three-card hand delta, one remaining sentinel, and unchanged hero health."),
    ])


hand_of_guldan_draws_three_when_played_or_discarded.card_id = "BT_300"


def nightshade_matron_rushes_and_discards_highest_cost_card():
    cid = "BT_301"

    def discards_highest_cost_hand_of_guldan_triggers_draws_and_rushes():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3011)
        matron = p.give(cid)
        guldan = p.give("BT_300")
        lower_cost = p.give("CS2_182")
        deck_ids = ["CS2_029", WISP, "CS2_179", "CS2_182"]
        deck_cards = [put_deck(p, card_id)[0] for card_id in deck_ids]
        target = summon(e, WISP)
        body = matron.play()
        drawn = [c for c in p.hand if c not in (lower_cost,)]
        rush = body.tags[GameTag.RUSH]
        attack_error = None
        try:
            body.attack(target)
        except Exception as exc:
            attack_error = type(exc).__name__
        observed = (f"matron={body.zone.name}/{body.atk}/{body.health}/rush={rush};"
                    f"guldan={guldan.zone.name};lower={lower_cost.zone.name};"
                    f"drawn={[c.id for c in drawn]};deck={[c.id for c in p.deck]};"
                    f"attack_error={attack_error};target={target.zone.name}")
        remaining = [c for c in deck_cards if any(c is top for top in p.deck)]
        drawn_cards = [c for c in deck_cards if c not in remaining]
        return check(rush and guldan.zone == Zone.REMOVEDFROMGAME and lower_cost.zone == Zone.HAND
                     and len(drawn_cards)==3 and all(c in p.hand for c in drawn_cards)
                     and len(remaining)==1 and len(p.hand)==4 and p.hero.health==30
                     and attack_error is None and target.zone==Zone.GRAVEYARD, observed)

    audit(cid, [
        ("rush_discards_highest_cost_and_can_attack_minion", "Nightshade Matron has Rush, discards the highest-Cost card (Hand of Gul'dan), triggers its 3-card draw while leaving a fourth sentinel in deck, and can attack an enemy minion immediately.", discards_highest_cost_hand_of_guldan_triggers_draws_and_rushes, "Hold Hand of Gul'dan (6) and a Yeti (4), with four known deck cards and an enemy Wisp; play Matron, verify discard selection, exactly three draws plus one remaining sentinel, and immediate Rush combat."),
    ])


nightshade_matron_rushes_and_discards_highest_cost_card.card_id = "BT_301"


def dark_portal_reduces_drawn_minion_if_hand_has_eight_cards():
    cid = "BT_302"

    def eight_cards_including_portal_reduces_drawn_king_krush_by_five():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3021)
        fillers = [p.give("CS2_029") for _ in range(7)]
        deck_cards = put_deck(p, "EX1_543", count=2)
        portal = p.give(cid)
        hand_before = len(p.hand)
        spell = portal.play()
        entity = next((c for c in p.hand if any(c is prior for prior in deck_cards)), None)
        remaining = [c for c in deck_cards if any(c is top for top in p.deck)]
        observed = (f"before={hand_before};spell={spell.zone.name};drawn={entity.id if entity else None}/"
                    f"{entity.zone.name if entity else None}/cost={entity.cost if entity else None};"
                    f"remaining={[(c.id,c.cost,c.zone.name) for c in remaining]};"
                    f"hand={[c.id for c in p.hand]};fillers={[c.id for c in fillers]};hero={p.hero.health}")
        return check(hand_before == 8 and entity is not None and entity.zone==Zone.HAND
                     and entity.cost == 4 and len(remaining)==1 and remaining[0].cost==9
                     and spell.zone==Zone.GRAVEYARD and p.hero.health==30, observed)

    def seven_cards_including_portal_leaves_drawn_minion_cost_unchanged():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3022)
        fillers = [p.give("CS2_029") for _ in range(6)]
        deck_cards = put_deck(p, "EX1_543", count=2)
        portal = p.give(cid)
        hand_before = len(p.hand)
        spell = portal.play()
        entity = next((c for c in p.hand if any(c is prior for prior in deck_cards)), None)
        remaining = [c for c in deck_cards if any(c is top for top in p.deck)]
        observed = (f"before={hand_before};spell={spell.zone.name};drawn={entity.id if entity else None}/"
                    f"{entity.zone.name if entity else None}/cost={entity.cost if entity else None};"
                    f"remaining={[(c.id,c.cost,c.zone.name) for c in remaining]};"
                    f"hand={[c.id for c in p.hand]};fillers={[c.id for c in fillers]};hero={p.hero.health}")
        return check(hand_before == 7 and entity is not None and entity.zone==Zone.HAND
                     and entity.cost == 9 and len(remaining)==1 and remaining[0].cost==9
                     and spell.zone==Zone.GRAVEYARD and p.hero.health==30, observed)

    audit(cid, [
        ("eight_hand_cards_reduce_drawn_minion_cost_five", "With 8 cards in hand including The Dark Portal, the drawn King Krush costs 5 less (9 to 4) and the second eligible minion remains in deck.", eight_cards_including_portal_reduces_drawn_king_krush_by_five, "Hold seven known filler cards plus Portal and two King Krush entities in deck; check the drawn entity's cost is4, its twin remains at9 in deck, and the hero takes no fatigue damage."),
        ("seven_hand_cards_do_not_reduce_drawn_minion_cost", "With only 7 cards in hand including The Dark Portal, the drawn King Krush keeps its 9-Cost value; the second minion remains in deck.", seven_cards_including_portal_leaves_drawn_minion_cost_unchanged, "Hold six known filler cards plus Portal and two King Krush entities in deck; compare drawn and remaining costs against the exact 8-card threshold."),
    ])


dark_portal_reduces_drawn_minion_if_hand_has_eight_cards.card_id = "BT_302"


def enhanced_dreadlord_taunt_deathrattle_summons_lifesteal_five_five():
    cid = "BT_304"

    def taunt_body_death_summons_exact_lifesteal_dreadlord():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3041)
        p.hero.set_current_health(25)
        body = play(p, cid)
        taunt = body.tags[GameTag.TAUNT]
        body.destroy()
        token = next((m for m in p.field if m.id == "BT_304t"), None)
        lifesteal = token.tags[GameTag.LIFESTEAL] if token else False
        observed = (f"body={body.zone.name}/{body.atk}/{body.health}/taunt={taunt};"
                    f"token={token.id if token else None}/{token.zone.name if token else None}/"
                    f"{(token.atk,token.health) if token else None}/lifesteal={lifesteal};"
                    f"field={[(m.id,m.atk,m.health) for m in p.field]}")
        return check(taunt and body.zone==Zone.GRAVEYARD and token is not None
                     and token.zone==Zone.PLAY and (token.atk,token.health)==(5,5)
                     and lifesteal and len(p.field)==1, observed)

    audit(cid, [
        ("taunt_death_summons_one_five_five_lifesteal_dreadlord", "Enhanced Dreadlord has Taunt; its death summons exactly one 5/5 Dreadlord with Lifesteal.", taunt_body_death_summons_exact_lifesteal_dreadlord, "Play Enhanced Dreadlord, assert its Taunt, destroy it, and inspect the exact summoned token's ID, zone, stats and Lifesteal tag."),
    ])


enhanced_dreadlord_taunt_deathrattle_summons_lifesteal_five_five.card_id = "BT_304"


def imprisoned_scrap_imp_buffs_minions_in_hand_when_awakened():
    cid = "BT_305"

    def awakens_after_two_turns_and_buffs_hand_minions_only():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3051)
        body = play(p, cid)
        yeti = p.give("CS2_182")
        wisp = p.give(WISP)
        fireball = p.give("CS2_029")
        before = [(yeti.atk,yeti.health),(wisp.atk,wisp.health)]
        end_round(g)
        after_one = (body.dormant, body.dormant_turns,
                     (yeti.atk,yeti.health),(wisp.atk,wisp.health),fireball.cost)
        end_round(g)
        after_two = (body.dormant, body.dormant_turns,
                     (yeti.atk,yeti.health),(wisp.atk,wisp.health),fireball.cost)
        observed = (f"before={before};after_one={after_one};after_two={after_two};"
                    f"hand={[c.id for c in p.hand]};body={body.zone.name}")
        return check(after_one[0] and after_one[1]==1 and after_one[2:4]==tuple(before)
                     and after_two[0] is False and after_two[1]==0
                     and after_two[2]==(6,6) and after_two[3]==(3,2)
                     and after_two[4]==fireball.cost==4 and body.zone==Zone.PLAY, observed)

    audit(cid, [
        ("awakening_after_two_turns_buffs_all_minions_in_hand", "After two Dormant turns, Scrap Imp awakens and grants +2/+1 to each minion in hand while leaving the Fireball spell unchanged.", awakens_after_two_turns_and_buffs_hand_minions_only, "Keep a known Yeti, Wisp and Fireball in hand while the Imp is Dormant; compare minion stats after each owner turn and verify the non-minion card's cost is untouched."),
    ])


imprisoned_scrap_imp_buffs_minions_in_hand_when_awakened.card_id = "BT_305"


def shadow_council_replaces_whole_hand_with_buffed_demons():
    cid = "BT_306"

    def all_held_cards_become_buffed_demons():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3061)
        old = [p.give(WISP), p.give("CS2_182"), p.give("CS2_029")]
        old_ids = [c.id for c in old]
        spell = play(p, cid)
        replacements = list(p.hand)
        details = []
        for card in replacements:
            details.append((card.id, card.type, card.race, card.atk, card.health,
                            card.max_health, card.data.atk, card.data.health, card.zone.name))
        observed = (f"spell={spell.zone.name};old={[ (c.id,c.zone.name) for c in old]};"
                    f"old_ids={old_ids};replacements={details};hand={[c.id for c in p.hand]}")
        valid_stats = all(card.atk == card.data.atk + 2
                          and card.health == card.data.health + 2
                          and card.max_health == card.data.health + 2
                          for card in replacements)
        return check(spell.zone==Zone.GRAVEYARD and len(replacements)==len(old)
                     and all(all(card is not prior for prior in old) for card in replacements)
                     and all(card.type==CardType.MINION and card.race==Race.DEMON
                             and card.zone==Zone.HAND for card in replacements)
                     and valid_stats and all(c.id not in [WISP,"CS2_182","CS2_029"] for c in replacements), observed)

    audit(cid, [
        ("replaces_every_hand_card_with_plus_two_plus_two_demon", "Shadow Council replaces all three other hand cards, including the spell, with Demons that each have +2/+2.", all_held_cards_become_buffed_demons, "Hold a Wisp, Yeti and Fireball, play Shadow Council, then retrieve current hand entities rather than stale pre-Morph references; assert each replacement is a Demon minion and its attack/current/max health are its base values plus two."),
    ])


shadow_council_replaces_whole_hand_with_buffed_demons.card_id = "BT_306"


def darkglare_refreshes_two_mana_only_after_friendly_hero_damage():
    cid = "BT_307"

    def damage_to_friendly_hero_refreshes_two_spent_mana():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3071)
        glare = summon(p, cid)
        spend = play(p, "BT_304")
        mana_before = p.mana
        g.end_turn()
        spell = e.give("CS2_029")
        spell.play(target=p.hero)
        observed = (f"glare={glare.zone.name};spend={spend.zone.name}/{spend.health};"
                    f"mana_before={mana_before};mana_after={p.mana};used={p.used_mana};"
                    f"hero={p.hero.health};enemy_spell={spell.zone.name}")
        return check(mana_before==2 and p.mana==4 and p.hero.health==24
                     and spell.zone==Zone.GRAVEYARD and glare.zone==Zone.PLAY, observed)

    def damage_to_minion_does_not_refresh_mana():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3072)
        glare = summon(p, cid)
        spend = play(p, "BT_304")
        mana_before = p.mana
        g.end_turn()
        spell = e.give("CS2_029")
        spell.play(target=spend)
        observed = (f"glare={glare.zone.name};spend={spend.zone.name}/{spend.health};"
                    f"mana_before={mana_before};mana_after={p.mana};used={p.used_mana};"
                    f"hero={p.hero.health};enemy_spell={spell.zone.name}")
        return check(mana_before==2 and p.mana==2 and spend.health==1
                     and p.hero.health==30 and spell.zone==Zone.GRAVEYARD, observed)

    audit(cid, [
        ("friendly_hero_damage_refreshes_two_mana", "After Darkglare is in play and 8 mana is spent, damage to its controller's hero refreshes exactly 2 crystals (2 to 4 remaining).", damage_to_friendly_hero_refreshes_two_spent_mana, "Spend 8 real mana on an Enhanced Dreadlord while Darkglare is active; during the opponent's turn cast Fireball at the Warlock hero and compare the exact remaining mana before and after."),
        ("minion_damage_does_not_refresh_hero_damage_trigger", "Damage to a friendly minion without damaging the hero does not refresh mana through Darkglare.", damage_to_minion_does_not_refresh_mana, "Repeat with the opposing Fireball targeting the 5/7 Dreadlord; verify it survives at 1 health, the hero stays at30, and remaining mana stays2."),
    ])


darkglare_refreshes_two_mana_only_after_friendly_hero_damage.card_id = "BT_307"


def kanrethad_ebonlocke_aura_reduces_demon_cost_and_deathrattle_shuffles_prime():
    cid = "BT_309"

    def aura_applies_only_to_demons_and_death_shuffles_prime():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=3091)
        demon = p.give("BT_304")
        non_demon = p.give("CS2_182")
        before = (demon.cost, non_demon.cost)
        body = play(p, cid)
        during = (demon.cost, non_demon.cost)
        body.destroy()
        after = (demon.cost, non_demon.cost)
        primes = [c for c in p.deck if c.id=="BT_309t"]
        observed = (f"before={before};during={during};after={after};body={body.zone.name};"
                    f"primes={[(c.id,c.zone.name) for c in primes]};deck={[c.id for c in p.deck]}")
        return check(before==(8,4) and during==(7,4) and after==(8,4)
                     and body.zone==Zone.GRAVEYARD and len(primes)==1
                     and primes[0].zone==Zone.DECK, observed)

    audit(cid, [
        ("demon_cost_reduced_one_aura_ends_and_death_shuffles_prime", "Kanrethad makes the held Demon cost 1 less but leaves the Yeti unchanged; when Kanrethad dies the aura ends and one Kanrethad Prime is shuffled into the deck.", aura_applies_only_to_demons_and_death_shuffles_prime, "Record a held Demon and non-Demon cost, play Kanrethad to compare aura effects, destroy it, verify costs revert and inspect the exact Prime card in deck."),
    ])


kanrethad_ebonlocke_aura_reduces_demon_cost_and_deathrattle_shuffles_prime.card_id = "BT_309"


def netherwalker_discovers_a_demon_into_hand():
    cid = "BT_321"

    def three_demon_choices_and_selected_card_enters_hand():
        g, p, e = game(CardClass.DEMONHUNTER, CardClass.MAGE, seed=3211)
        body = play(p, cid)
        choice = p.choice
        options = list(choice.cards) if choice else []
        chosen = options[0] if options else None
        if chosen:
            choice.choose(chosen)
        in_hand = [c for c in p.hand if chosen is not None and c.id==chosen.id]
        observed = (f"body={body.zone.name}/{body.atk}/{body.health};"
                    f"options={[(c.id,c.type,c.race,c.zone.name) for c in options]};"
                    f"chosen={chosen.id if chosen else None};in_hand={[(c.id,c.zone.name) for c in in_hand]};"
                    f"choice_pending={bool(p.choice)}")
        return check(body.zone==Zone.PLAY and len(options)==3
                     and all(c.type==CardType.MINION and c.race==Race.DEMON for c in options)
                     and chosen is not None and len(in_hand)==1 and in_hand[0].zone==Zone.HAND
                     and p.choice is None, observed)

    audit(cid, [
        ("discovers_three_demons_and_selected_demon_enters_hand", "Netherwalker presents three Demon minions, and the selected Demon enters hand.", three_demon_choices_and_selected_card_enters_hand, "Play Netherwalker, inspect all three live Discover options' card type and race, select one, and verify it enters hand and the choice closes."),
    ])


netherwalker_discovers_a_demon_into_hand.card_id = "BT_321"


AUDITS = [bloodboil_brute_discount_and_rush,
          bonechewer_raider_conditionally_gains_stats_and_rush,
          scrapyard_colossus_taunt_deathrattle_summons_seven_seven,
          imprisoned_vilefiend_wakes_after_two_turns_with_rush,
          terrorguard_escapee_summons_three_huntresses_for_opponent,
          rustsworn_cultist_gives_other_minions_demon_deathrattles,
          nagrand_slam_summons_four_clefthoofs_that_attack,
          kayn_sunfury_charge_and_friendly_attacks_ignore_taunt,
          shadowjeweler_hanar_discovers_off_class_secret_after_secret,
          replicat_o_tron_transforms_sole_adjacent_neighbor_at_turn_end,
          kelidan_breaker_drawn_turn_destroys_all_other_minions,
          reliquary_of_souls_lifesteal_and_deathrattle_prime_shuffle,
          soul_mirror_summons_enemy_copy_and_they_fight,
          unstable_felbolt_hits_enemy_target_and_one_random_friendly_minion,
          augmented_porcupine_deathrattle_splits_attack_damage_among_enemies,
          helboar_deathrattle_buffs_random_beast_in_hand_only,
          pack_tactics_summons_three_three_copy_when_friend_is_attacked,
          scrap_shot_damages_target_and_buffs_random_beast_in_hand,
          zixor_rushes_and_deathrattle_shuffles_prime_into_deck,
          imprisoned_felmaw_awaken_attacks_the_only_enemy_character,
          moknathal_lion_rush_copies_friendly_deathrattle,
          scavengers_ingenuity_draws_and_buffs_beast,
          beastmaster_leoroxx_summons_three_beasts_from_hand,
          the_lurker_below_chain_hits_one_neighbor_after_kill,
          sword_and_board_deals_two_and_gains_two_armor,
          scrap_golem_deathrattle_gains_armor_equal_to_attack,
          renew_restores_three_and_discovers_spell,
          psyche_split_buffs_friendly_minion_and_summons_copy,
          sethekk_veilweaver_generates_priest_spell_only_on_minion_spell,
          kaelthas_makes_every_third_spell_each_turn_free,
          dragonmaw_overseer_buffs_one_other_friendly_at_end_turn,
          apotheosis_buffs_minion_and_lifesteal_heals_on_attack,
          imprisoned_homunculus_wakes_with_taunt_after_two_turns,
          dragonmaw_sentinel_powered_up_by_dragon_in_hand,
          apexis_blast_summons_five_cost_minion_only_if_deck_has_no_minions,
          hand_of_adal_buffs_friendly_minion_and_draws,
          hand_of_guldan_draws_three_when_played_or_discarded,
          nightshade_matron_rushes_and_discards_highest_cost_card,
          dark_portal_reduces_drawn_minion_if_hand_has_eight_cards,
          enhanced_dreadlord_taunt_deathrattle_summons_lifesteal_five_five,
          imprisoned_scrap_imp_buffs_minions_in_hand_when_awakened,
          shadow_council_replaces_whole_hand_with_buffed_demons,
          darkglare_refreshes_two_mana_only_after_friendly_hero_damage,
          kanrethad_ebonlocke_aura_reduces_demon_cost_and_deathrattle_shuffles_prime,
          netherwalker_discovers_a_demon_into_hand]


def main():
    from collections import Counter
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=45)
    args = parser.parse_args()
    assert 0 <= args.start < 45 and 1 <= args.limit <= 45
    assert len(AUDITS) == len(ROSTER) == 45, (len(AUDITS), len(ROSTER))
    selected = AUDITS[args.start:args.start + args.limit]
    target_rows = ROSTER[args.start:args.start + args.limit]
    assert len(selected) == len(target_rows)
    statuses = []
    for row, fn in zip(target_rows, selected):
        assert row["card_id"] == fn.card_id
        fn()
        statuses.append(next(r["status"] for r in VERDICTS if r["card_id"] == fn.card_id))
    print(f"audited={len(statuses)} statuses={dict(Counter(statuses))}; "
          f"roster={[r['card_id'] for r in ROSTER[args.start:args.start+len(statuses)]]}")


if __name__ == "__main__":
    main()
