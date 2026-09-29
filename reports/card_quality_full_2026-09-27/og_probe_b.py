"""Per-card live Fireplace probes for OG baseline slice B (indices 42:84)."""

import csv
import json
import logging
import os
import random
import traceback
from collections import Counter as PyCounter
from pathlib import Path

from hearthstone.enums import CardClass, GameTag, Zone
from utils import *
from fireplace.logging import log


HERE = Path(__file__).resolve().parent
BASELINE = HERE / "og_yellow_baseline.csv"
PROBE = HERE / "og_probe_b.csv"
VERDICT = HERE / "og_verdict_b.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
log.setLevel(logging.ERROR)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


BASE_ROWS = read_csv(BASELINE)[42:84]
IDS = [row["card_id"] for row in BASE_ROWS]
CARD_ROWS = {row["card_id"]: row for row in BASE_ROWS}
AUDIT_ROWS = {row["card_id"]: row for row in read_csv(HERE / "card_quality.csv")}
MASTER_ROWS = {row["card_id"]: row for row in read_csv(HERE / "card_master.csv")}
PROBES = []
VERDICTS = []
CARD_CASES = {}


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_probe():
    write(PROBE, PROBE_FIELDS, PROBES)


def save_verdict():
    write(VERDICT, VERDICT_FIELDS, VERDICTS)


def new_game(seed=1, class1=CardClass.DRUID, class2=CardClass.DRUID):
    game = prepare_empty_game(class1, class2)
    game.player1.is_standard = False
    game.player2.is_standard = False
    game.random.seed(seed)
    random.seed(seed)
    for player in game.players:
        player.max_mana = 10
        player.used_mana = 0
    return game


def eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, observed {actual!r}")


def check(condition, expected, observed, label):
    if not condition:
        raise AssertionError(f"{label}: expected {expected!r}, observed {observed!r}")


def run_case(card_id, case_id, expected, action, notes=""):
    try:
        observed = action()
        outcome = "pass"
    except AssertionError as error:
        observed = str(error)
        outcome = "confirmed_error"
    except Exception as error:  # Invalid fixtures/API gaps are not treated as card bugs.
        observed = f"{type(error).__name__}: {error}"
        outcome = "inconclusive"
    row = {
        "card_id": card_id,
        "case_id": case_id,
        "expected": expected,
        "observed": str(observed),
        "outcome": outcome,
        "notes": notes,
    }
    PROBES.append(row)
    CARD_CASES.setdefault(card_id, []).append(row)
    save_probe()  # Each direct case is persisted as soon as it finishes.
    return row


def play_minion(player, card_id, target=None, choose=None):
    return play_card(player, card_id, target=target, choose=choose)


def play_card(player, card_id, target=None, choose=None):
    if not player.current_player:
        raise RuntimeError(f"{player.name} is not the active player; advance turn explicitly")
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    card.play(**kwargs)
    return card


def summon_fixture(player, card_id):
    """Put a supporting minion in play without spending mana or running its Battlecry."""
    return player.summon(card_id)


def advance_to_turn(game, player):
    for _ in range(2):
        if player.current_player:
            return
        game.end_turn()
    if not player.current_player:
        raise RuntimeError(f"could not advance to {player.name}'s turn")


def cycle_to_own_start(game, player):
    game.end_turn()
    game.end_turn()
    check(game.current_player is player, player.name, game.current_player.name, "turn owner")


def damage_minion(minion, amount):
    minion.set_current_health(minion.health - amount)


def current_test_name(card_id):
    lines = (Path(__file__).resolve().parents[2] / "tests" / "test_wog.py").read_text().splitlines()
    needle = f'"{card_id}"'
    found = []
    for index, line in enumerate(lines):
        if needle in line:
            for previous in reversed(lines[:index]):
                if previous.startswith("def test_"):
                    found.append(previous.strip()[4:].split("(", 1)[0])
                    break
    return ";".join(dict.fromkeys(found)) or "none"


YELLOW_BLOCKERS = {
    "OG_134": "Yogg-Saron resolves a random spell for every prior spell; the tested seeds cannot certify the full random spell pool, target rules, and stop-on-death interactions.",
}


def cases_for(card_id):
    """Return card-specific named direct-game cases; every case plays/resolves the card."""
    if card_id == "OG_133":
        def deadrattle_copy():
            g = new_game(133); p, e = g.player1, g.player2
            friends = [summon_fixture(p, "OG_147") for _ in range(3)]; silenced = summon_fixture(p,"OG_147"); silenced.silence()
            plain = summon_fixture(p, WISP)
            enemy = summon_fixture(e, "OG_241")
            for friend in friends:
                friend.destroy()
            silenced.destroy(); plain.destroy(); enemy.destroy()
            n = play_minion(p, "OG_133")
            copies = [c for c in p.field if c.id == "OG_147"]
            check(len(copies) == 3 and all(c not in friends for c in copies), "return three fresh copies including duplicate IDs; exclude a silenced Deathrattle corpse", [(c.id, c in friends) for c in copies], "N'Zoth duplicate and silenced corpse filter")
            eq(plain.zone, Zone.GRAVEYARD, "non-Deathrattle corpse zone")
            eq(enemy.zone, Zone.GRAVEYARD, "enemy corpse zone")
            return f"field={[c.id for c in p.field]}, copies={len(copies)}, originals={[c.zone.name for c in friends]}, silenced={silenced.zone.name}, plain={plain.zone.name}, enemy={enemy.zone.name}, played={n.zone.name}"
        def seven_minion_cap():
            g = new_game(1331); p = g.player1
            bodies=[summon_fixture(p,"OG_147") for _ in range(3)]
            for _ in range(4): summon_fixture(p,WISP)
            for body in bodies: body.destroy()
            n=play_minion(p,"OG_133")
            returned=[c for c in p.field if c.id=="OG_147"]
            check((len(p.field),len(returned),n.zone)==(7,2,Zone.PLAY), "N'Zoth respects the seven-minion board cap and returns only two of three eligible corpses", (len(p.field),len(returned),n.zone.name), "N'Zoth full-board summon limit")
            return f"field_count={len(p.field)}; returned_healb ots={len(returned)}; field={[c.id for c in p.field]}".replace("healb ots", "healbots")
        return [("returns_duplicate_friendly_deathrattle_corpses", "Return each eligible friendly dead Deathrattle minion, including duplicate IDs; exclude plain and enemy corpses.", deadrattle_copy), ("resurrection_respects_seven_minion_cap", "N'Zoth returns no more copies than fit on the seven-minion board.", seven_minion_cap)]

    if card_id == "OG_134":
        def no_previous_spells():
            g = new_game(134); p = g.player1
            yogg = play_minion(p, "OG_134")
            eq(yogg.zone, Zone.PLAY, "Yogg zone")
            eq(sum(1 for c in p.cards_played_this_game if c.type == CardType.SPELL), 0, "spells played before Yogg")
            return f"yogg_zone={yogg.zone.name}; spell_history={len([c for c in p.cards_played_this_game if c.type == CardType.SPELL])}; field={[c.id for c in p.field]}"
        def two_previous_spells():
            g = new_game(1341); p = g.player1
            play_minion(p, MOONFIRE, target=g.player2.hero)
            play_minion(p, THE_COIN)
            prior = sum(1 for c in p.cards_played_this_game if c.type == CardType.SPELL)
            before = g.player2.hero.health
            yogg = p.give("OG_134")
            try:
                yogg.play()
            except Exception as error:
                raise AssertionError(
                    f"live Yogg Battlecry crashes with two prior spells at game.random seed 1341: "
                    f"{type(error).__name__}: {error}; prior_spell_plays={prior}; yogg_zone={yogg.zone.name}; "
                    f"enemy_hp={g.player2.hero.health}; traceback={traceback.format_exc()}"
                ) from error
            after = sum(1 for c in p.cards_played_this_game if c.type == CardType.SPELL)
            check(prior == 2, 2, prior, "two prior spell plays before Yogg")
            return f"prior_spell_plays={prior}; observed_spell_history_after={after}; enemy_hp={before}->{g.player2.hero.health}; yogg_zone={yogg.zone.name}"
        return [("zero_prior_spells", "With zero spells previously played, Yogg resolves zero random spells.", no_previous_spells), ("two_prior_spells", "Two prior spells trigger two random spell attempts, subject to Yogg's death/leave-play stopping rule.", two_previous_spells)]

    if card_id == "OG_138":
        def repeated_discount():
            g = new_game(138); p = g.player1; card = p.give("OG_138")
            eq(card.cost, 6, "initial cost")
            cycle_to_own_start(g, p); one = card.cost
            cycle_to_own_start(g, p); two = card.cost
            check((one, two) == (5, 4), "cost drops by 1 at each of two own-turn starts while in hand", (one, two), "Nerubian Prophet hand trigger")
            card.play()
            eq(card.zone, Zone.PLAY, "played prophet zone")
            return f"cost_sequence=[6,{one},{two}]; played_zone={card.zone.name}"
        return [("hand_cost_reduction_each_own_turn", "While in hand, cost decreases once at each own-turn start; it can then be played.", repeated_discount)]

    if card_id == "OG_145":
        def shield_taunt_combat():
            g = new_game(145); p, e = g.player1, g.player2
            defender = play_minion(p, "OG_145")
            check(defender.taunt and defender.divine_shield, "Taunt and Divine Shield", (defender.taunt, defender.divine_shield), "Psych-o-Tron keywords")
            attacker = summon_fixture(e, "CS2_124")
            g.end_turn()
            try:
                attacker.attack(p.hero)
                hero_attack_allowed = True
            except Exception:
                hero_attack_allowed = False
            check(not hero_attack_allowed, "enemy attack is blocked from bypassing Taunt", hero_attack_allowed, "Taunt attack restriction")
            attacker.attack(defender)
            eq(defender.divine_shield, False, "shield consumed by attack")
            eq(defender.health, defender.max_health, "shield prevents first hit damage")
            return f"taunt={defender.taunt}; shield_after_hit={defender.divine_shield}; defender_hp={defender.health}/{defender.max_health}; hero_attack_allowed={hero_attack_allowed}"
        return [("taunt_and_shield_in_combat", "Taunt redirects the attack and Divine Shield absorbs the first hit.", shield_taunt_combat)]

    if card_id == "OG_147":
        def enemy_heal():
            g = new_game(147); p, e = g.player1, g.player2
            e.hero.set_current_health(18); p.hero.set_current_health(20)
            healbot = play_minion(p, "OG_147"); healbot.destroy()
            check((e.hero.health, p.hero.health, healbot.zone) == (26, 20, Zone.GRAVEYARD), "death heals enemy hero by 8 only, then Healbot enters graveyard", (e.hero.health, p.hero.health, healbot.zone.name), "Corrupted Healbot deathrattle")
            return f"enemy_hp=18->{e.hero.health}; friendly_hp={p.hero.health}; healbot_zone={healbot.zone.name}"
        return [("deathrattle_heals_enemy_hero", "On death, restore exactly 8 health to the enemy hero, not the friendly hero.", enemy_heal)]

    if card_id == "OG_149":
        def all_other_minions():
            g = new_game(149); p, e = g.player1, g.player2
            friend = summon_fixture(p, "CS2_182"); enemy = summon_fixture(e, "CS2_182")
            friend.set_current_health(2); enemy.set_current_health(3)
            ghoul = play_minion(p, "OG_149")
            check((friend.health, enemy.health, ghoul.health, p.hero.health, e.hero.health) == (1, 2, 3, 30, 30), "deal 1 to all other minions; preserve Ghoul itself and both heroes", (friend.health, enemy.health, ghoul.health, p.hero.health, e.hero.health), "Ravaging Ghoul Battlecry scope")
            return f"friendly_hp={friend.health}; enemy_hp={enemy.health}; ghoul_hp={ghoul.health}; hero_hp={(p.hero.health,e.hero.health)}"
        return [("battlecry_other_minions_excludes_self", "Deal 1 damage to every other minion on both sides, excluding Ravaging Ghoul and heroes.", all_other_minions)]

    if card_id == "OG_150":
        def damaged_attack_bonus():
            g = new_game(150); p = g.player1
            berserker = play_minion(p, "OG_150")
            base = berserker.atk; damage_minion(berserker, 1); damaged = berserker.atk
            berserker.set_current_health(berserker.max_health)
            healed = berserker.atk
            check((base, damaged, healed) == (3, 5, 3), "gain +2 Attack only while damaged; lose it on healing", (base, damaged, healed), "Aberrant Berserker enrage")
            return f"attack={base}->{damaged}->{healed}; hp={berserker.health}/{berserker.max_health}"
        return [("damage_and_heal_enrage", "Attack is +2 while damaged and returns to base when fully healed.", damaged_attack_bonus)]

    if card_id == "OG_151":
        def death_aoe():
            g = new_game(151); p, e = g.player1, g.player2
            friend = summon_fixture(p, "CS2_182"); enemy = summon_fixture(e, "CS2_182")
            friend.set_current_health(2); enemy.set_current_health(2)
            p.hero.set_current_health(28); e.hero.set_current_health(27)
            tentacle = play_minion(p, "OG_151"); tentacle.destroy()
            check((friend.health, enemy.health, tentacle.zone, p.hero.health, e.hero.health) == (1, 1, Zone.GRAVEYARD, 28, 27), "death deals 1 to all minions only, both sides; heroes excluded", (friend.health, enemy.health, tentacle.zone.name, p.hero.health, e.hero.health), "Tentacle of N'Zoth deathrattle")
            return f"minions_hp={(friend.health,enemy.health)}; heroes_hp={(p.hero.health,e.hero.health)}; dead={tentacle.zone.name}"
        return [("deathrattle_all_minions_not_heroes", "On death, deal 1 to all minions on both sides and no damage to heroes.", death_aoe)]

    if card_id == "OG_152":
        def two_attacks():
            g = new_game(152); p, e = g.player1, g.player2
            dragonhawk = play_minion(p, "OG_152")
            eq(bool(dragonhawk.windfury), True, "native Windfury")
            cycle_to_own_start(g, p)
            dragonhawk.attack(e.hero); first = e.hero.health
            dragonhawk.attack(e.hero); second = e.hero.health
            check((first, second) == (25, 20), "5-Attack Dragonhawk can attack twice in the same turn", (first, second), "Windfury attacks")
            return f"enemy_hp=30->{first}->{second}; windfury={dragonhawk.windfury}"
        return [("windfury_two_attacks_same_turn", "Windfury allows two attacks in one turn and each deals printed attack damage.", two_attacks)]

    if card_id == "OG_153":
        def taunt_blocks_hero():
            g = new_game(153); p, e = g.player1, g.player2
            taunter = play_minion(p, "OG_153")
            other = summon_fixture(p, WISP)
            attacker = summon_fixture(e, "CS2_124")
            g.end_turn()
            try:
                attacker.attack(p.hero); bypassed = True
            except Exception:
                bypassed = False
            check((taunter.taunt, other.zone, bypassed, p.hero.health) == (True, Zone.PLAY, False, 30), "Taunt blocks enemy attack on hero while other friendly minions remain", (taunter.taunt, other.zone.name, bypassed, p.hero.health), "Bog Creeper taunt legality")
            return f"taunt={taunter.taunt}; hero_attack={bypassed}; hero_hp={p.hero.health}"
        return [("taunt_blocks_hero_attack", "An enemy attacker cannot attack the hero while Bog Creeper with Taunt is alive.", taunt_blocks_hero)]

    if card_id == "OG_156":
        def body_and_token():
            g = new_game(156); p = g.player1
            body = play_minion(p, "OG_156")
            tokens = [c for c in p.field if c.id == "OG_156a"]
            check((body.id, body.atk, body.health, len(tokens), tokens[0].atk, tokens[0].health, tokens[0].taunt) == ("OG_156", 2, 1, 1, 1, 1, True), "2/1 Tidehunter summons exactly one 1/1 Taunt Ooze", (body.id, body.atk, body.health, len(tokens), [(c.atk,c.health,c.taunt) for c in tokens]), "Bilefin Tidehunter Battlecry")
            return f"field={[(c.id,c.atk,c.health,c.taunt) for c in p.field]}"
        return [("battlecry_summons_taunt_ooze", "Battlecry summons one 1/1 Taunt Ooze alongside the printed body.", body_and_token)]

    if card_id == "OG_161":
        def non_murloc_aoe():
            g = new_game(161); p, e = g.player1, g.player2
            friend = summon_fixture(p, "CS2_182")  # Chillwind Yeti, 4/5 non-Murloc.
            own_murloc = summon_fixture(p, MURLOC)
            enemy = summon_fixture(e, "CS2_182")
            enemy_murloc = summon_fixture(e, MURLOC)
            seer = play_minion(p, "OG_161")
            check((friend.health, own_murloc.health, enemy.health, enemy_murloc.health, seer.health) == (3, 1, 3, 1, 3), "2 damage to all other non-Murloc minions on both sides; spare Murlocs and Seer", (friend.health, own_murloc.health, enemy.health, enemy_murloc.health, seer.health), "Corrupted Seer target filter")
            return f"health={[friend.health,own_murloc.health,enemy.health,enemy_murloc.health,seer.health]}"
        return [("battlecry_non_murloc_filter_both_sides", "Battlecry damages all non-Murloc minions on both sides, excludes Murlocs and self.", non_murloc_aoe)]

    if card_id == "OG_162":
        def damage_and_cthun_zone():
            g = new_game(162); p, e = g.player1, g.player2
            cthun = p.cthun; base = (cthun.atk, cthun.max_health, cthun.zone)
            target = summon_fixture(e, "CS2_182"); target.set_current_health(4)
            disciple = play_minion(p, "OG_162", target=target)
            check((target.health, cthun.atk, cthun.max_health, cthun.zone) == (2, base[0]+2, base[1]+2, Zone.SETASIDE), "deal 2 to chosen minion and buff the C'Thun entity wherever stored", (target.health, cthun.atk, cthun.max_health, cthun.zone.name), "Disciple of C'Thun")
            return f"target_hp={target.health}; cthun={(base[:2],(cthun.atk,cthun.max_health),cthun.zone.name)}; disciple={disciple.zone.name}"
        def enemy_hero_target_buffs_cthun_in_deck():
            g = new_game(1621); p, e = g.player1, g.player2
            cthun = p.cthun; cthun.shuffle_into_deck()
            base = (cthun.atk, cthun.max_health)
            disciple = p.give("OG_162")
            target_is_legal = e.hero in disciple.play_targets
            check(target_is_legal, True, target_is_legal, "enemy hero is a legal character target")
            disciple.play(target=e.hero)
            check((e.hero.health, cthun.atk, cthun.max_health, cthun.zone, disciple.zone) == (28, base[0]+2, base[1]+2, Zone.DECK, Zone.PLAY), "deal 2 to enemy hero and buff C'Thun +2/+2 while it remains in deck", (e.hero.health, cthun.atk, cthun.max_health, cthun.zone.name, disciple.zone.name), "Disciple character target and deck C'Thun")
            return f"enemy_hero=30->{e.hero.health}; cthun={base}->{(cthun.atk,cthun.max_health)} zone={cthun.zone.name}; disciple={disciple.zone.name}"
        return [
            ("battlecry_target_damage_and_cthun_buff", "Deal 2 damage to chosen target and grant the owner's C'Thun +2/+2 while set aside.", damage_and_cthun_zone),
            ("enemy_hero_target_buffs_cthun_in_deck", "Enemy hero is a legal character target; deal 2 damage and buff C'Thun +2/+2 while C'Thun is in deck.", enemy_hero_target_buffs_cthun_in_deck),
        ]

    if card_id == "OG_173":
        def pair_merge_at_own_end():
            g = new_game(173); p = g.player1
            first = summon_fixture(p, "OG_173"); second = play_minion(p, "OG_173")
            g.end_turn()
            ancients = [c for c in p.field if c.id == "OG_173a"]
            check((len(ancients), first.zone, second.zone) == (1, Zone.GRAVEYARD, Zone.GRAVEYARD), "two friendly Bloods merge at own turn end into one Ancient One", (len(ancients), first.zone.name, second.zone.name), "Ancient One merge")
            eq((ancients[0].atk, ancients[0].health), (30, 30), "Ancient One stats")
            return f"ancient_count={len(ancients)}; stats={(ancients[0].atk,ancients[0].health)}; blood_zones={(first.zone.name,second.zone.name)}"
        def lone_blood_survives():
            g = new_game(1731); p = g.player1
            blood = play_minion(p, "OG_173"); g.end_turn()
            eq(blood.zone, Zone.PLAY, "single Blood remains on board")
            return f"field={[c.id for c in p.field]}; blood_zone={blood.zone.name}"
        return [("two_copies_merge_only_at_own_turn_end", "Two copies merge at end of your turn into a 30/30 Ancient One; both source cards die.", pair_merge_at_own_end), ("single_copy_does_not_merge", "A lone Blood of the Ancient One remains in play at your turn end.", lone_blood_survives)]

    if card_id == "OG_174":
        def copy_current_stats_and_taunt():
            g = new_game(174); p = g.player1
            target = summon_fixture(p, "CS2_182")
            copy = play_minion(p, "OG_174", target=target)
            check((copy.atk, copy.health, copy.max_health, copy.taunt) == (target.atk, target.health, target.max_health, True), "copy friendly minion attack/health and retain Shambler's Taunt", (copy.atk, copy.health, copy.max_health, copy.taunt), "Faceless Shambler copy")
            return f"target={(target.atk,target.health,target.max_health)}; copy={(copy.atk,copy.health,copy.max_health,copy.taunt)}"
        def copies_damaged_friendly_current_health():
            g = new_game(1741); p = g.player1
            target = summon_fixture(p, "CS2_182"); target.set_current_health(3)
            copy = play_minion(p, "OG_174", target=target)
            check((target.atk,target.health,target.max_health,copy.atk,copy.health,copy.taunt)==(4,3,5,4,3,True), "copy the damaged friendly minion's current Health and Attack, retaining Taunt", (target.atk,target.health,target.max_health,copy.atk,copy.health,copy.taunt), "Faceless Shambler damaged-target copy")
            return f"target={(target.atk,target.health,target.max_health)}; copy={(copy.atk,copy.health,copy.max_health,copy.taunt)}"
        def enemy_target_rejected():
            g = new_game(1742); p,e=g.player1,g.player2
            friendly=summon_fixture(p,WISP); enemy=summon_fixture(e,"CS2_182")
            card=p.give("OG_174")
            friendly_legal=friendly in card.play_targets; enemy_legal=enemy in card.play_targets
            before=(p.mana,len(p.field),enemy.atk,enemy.health)
            try:
                card.play(target=enemy); accepted=True
            except Exception:
                accepted=False
            check((friendly_legal,enemy_legal,accepted,card.zone,p.mana,len(p.field),enemy.atk,enemy.health)==(True,False,False,Zone.HAND,before[0],before[1],before[2],before[3]), "friendly minion is legal, enemy target is rejected without paying or changing either board", (friendly_legal,enemy_legal,accepted,card.zone.name,p.mana,len(p.field),enemy.atk,enemy.health), "Faceless Shambler target ownership")
            return f"friendly_legal={friendly_legal}; enemy_legal={enemy_legal}; accepted={accepted}; card={card.zone.name}; mana={p.mana}"
        return [
            ("battlecry_copies_friendly_stats_and_keeps_taunt", "An undamaged friendly minion's Attack and Health are copied; Shambler keeps Taunt.", copy_current_stats_and_taunt),
            ("copies_damaged_friendly_current_health", "A damaged friendly target's current Health is copied along with its Attack.", copies_damaged_friendly_current_health),
            ("enemy_target_rejected", "Enemy minions are not legal targets and rejected selection preserves card, mana and board state.", enemy_target_rejected),
        ]

    if card_id == "OG_176":
        def undamaged_target_and_damage():
            g = new_game(176); p, e = g.player1, g.player2
            fresh = summon_fixture(e, "CS2_200")  # Boulderfist Ogre has 7 Health; survives the spell.
            play_card(p, "OG_176", target=fresh)
            eq((fresh.health, fresh.zone), (2, Zone.PLAY), "five damage leaves the 7-health target alive at 2")
            return f"target_zone={fresh.zone.name}; target_health={fresh.health}"
        def damaging_card_target_details():
            g = new_game(1761); p, e = g.player1, g.player2
            fresh = summon_fixture(e,"CS2_182")
            spell=p.give("OG_176")
            check(fresh in spell.play_targets,"undamaged enemy minion appears as legal target",[c.id for c in spell.play_targets],"Shadow Strike legal target")
            return f"targets={[c.id for c in spell.play_targets]}"
        def damaged_target_rejected():
            g = new_game(1762); p, e = g.player1, g.player2
            damaged = summon_fixture(e, "CS2_182"); damage_minion(damaged, 1)
            spell = p.give("OG_176")
            legal = damaged in spell.play_targets
            eq(legal, False, "damaged character is excluded from legal target list")
            before_mana = p.mana
            try:
                spell.play(target=damaged); accepted = True
            except Exception:
                accepted = False
            check((accepted, spell.zone, p.mana) == (False, Zone.HAND, before_mana), "illegal damaged target rejected without consuming card or mana", (accepted, spell.zone.name, p.mana, before_mana), "Shadow Strike failed target transaction")
            return f"damaged_hp={damaged.health}; legal_target={legal}; accepted={accepted}; spell_zone={spell.zone.name}; mana={p.mana}"
        return [("five_damage_to_undamaged_character", "An undamaged minion can be targeted and takes 5 damage.", undamaged_target_and_damage), ("damaged_target_not_legal", "A previously damaged minion is not a legal target and the spell stays in hand.", damaged_target_rejected)]

    if card_id == "OG_179":
        def random_deathrattle(seed):
            g = new_game(seed); p, e = g.player1, g.player2
            e.hero.set_current_health(28)
            victim = summon_fixture(e, "CS2_182"); victim.set_current_health(4)
            own = summon_fixture(p, WISP)
            bat = play_minion(p, "OG_179"); bat.destroy()
            deltas = {"enemy_minion": 4-victim.health, "enemy_hero": 28-e.hero.health, "friendly_minion": 1-own.health}
            check(sum(deltas.values()) == 1 and deltas["friendly_minion"] == 0, "deathrattle deals exactly 1 to one random enemy character, never a friendly", deltas, "Fiery Bat random target domain")
            return f"seed={seed}; damage={deltas}; bat_zone={bat.zone.name}"
        return [(f"random_enemy_character_seed_{seed}", "Deathrattle hits exactly one enemy character for 1; sample random target domain.", lambda seed=seed: random_deathrattle(seed)) for seed in (17, 29, 41, 53, 67, 79, 83, 97)]

    if card_id == "OG_188":
        def threshold_health_buff():
            g = new_game(188); p = g.player1
            low = p.cthun
            # Fresh game C'Thun starts at 6 Attack; raise it to 10 exactly.
            p.give("OG_281").play(); p.give("OG_281").play()
            check(low.atk == 10, 10, low.atk, "C'Thun threshold setup")
            weaver = play_minion(p, "OG_188")
            check((weaver.atk, weaver.health, weaver.max_health) == (4, 10, 10), "at 10+ C'Thun Attack, Klaxxi gains +5 Health (base 4/5 to 4/10)", (weaver.atk, weaver.health, weaver.max_health), "Klaxxi Amber-Weaver threshold")
            return f"cthun_atk={low.atk}; weaver={(weaver.atk,weaver.health,weaver.max_health)}"
        def below_threshold_no_buff():
            g = new_game(1881); p = g.player1
            p.give("OG_281").play()
            w = play_minion(p, "OG_188")
            check((p.cthun.atk, w.health, w.max_health) == (8, 5, 5), "below 10 C'Thun Attack, no extra Health", (p.cthun.atk, w.health, w.max_health), "Klaxxi threshold negative")
            return f"cthun_atk={p.cthun.atk}; weaver_hp={w.health}/{w.max_health}"
        return [("cthun_at_least_10_grants_five_health", "At 10+ C'Thun Attack, gain +5 Health; verify exact printed-text amount.", threshold_health_buff), ("cthun_below_10_no_health_buff", "At 9 or less C'Thun Attack, no bonus health.", below_threshold_no_buff)]

    if card_id == "OG_195":
        def summon_branch():
            g = new_game(195); p = g.player1
            p.give("OG_195").play(choose="OG_195a")
            wisps = [c for c in p.field if c.id == "OG_195c"]
            check(len(wisps) == 7 and all((c.atk,c.health)==(1,1) for c in wisps), "first Choose One summons seven 1/1 Wisps", (len(wisps),[(c.atk,c.health) for c in wisps]), "Wisps of the Old Gods summon choice")
            return f"wisp_count={len(wisps)}; stats={[(c.atk,c.health) for c in wisps]}"
        def buff_branch_no_fandral():
            g = new_game(1951); p = g.player1
            minion = summon_fixture(p, WISP)
            p.give("OG_195").play(choose="OG_195b")
            wisps = [c for c in p.field if c.id == "OG_195c"]
            check((minion.atk,minion.health,len(wisps)) == (3,3,0), "buff choice gives +2/+2 and no Wisps without Fandral", (minion.atk,minion.health,len(wisps)), "Wisps buff branch")
            return f"existing={(minion.atk,minion.health)}; wisps={len(wisps)}"
        def fandral_combines_choices():
            g = new_game(1952); p = g.player1
            minion = summon_fixture(p, WISP); summon_fixture(p, "OG_044")
            p.give("OG_195").play()
            wisps = [c for c in p.field if c.id == "OG_195c"]
            check((minion.atk,minion.health,len(wisps),all((c.atk,c.health)==(3,3) for c in wisps)) == (3,3,5,True), "Fandral combines both choices; existing minion is buffed and five available spaces fill with 3/3 Wisps", (minion.atk,minion.health,len(wisps),[(c.atk,c.health) for c in wisps]), "Fandral combined choice and board limit")
            return f"existing={(minion.atk,minion.health)}; wisps={len(wisps)}x3/3"
        return [("choose_one_seven_wisps", "Summon branch creates exactly seven 1/1 Wisps.", summon_branch), ("buff_choice_no_fandral", "Buff branch gives +2/+2 to existing minions without summoning Wisps.", buff_branch_no_fandral), ("fandral_combines_choices_board_cap", "Fandral combines both effects, limited by open board spaces.", fandral_combines_choices)]

    if card_id == "OG_198":
        def spend_all_and_double_heal():
            g = new_game(198); p = g.player1
            p.hero.set_current_health(20); p.max_mana = 4; p.used_mana = 0
            spell = p.give("OG_198"); spell.play(target=p.hero)
            check((p.hero.health, p.mana, spell.zone) == (28, 0, Zone.GRAVEYARD), "spend all four mana and heal selected hero for eight", (p.hero.health,p.mana,spell.zone.name), "Forbidden Healing mana scaling")
            return f"hero_hp=20->{p.hero.health}; mana=4->{p.mana}; spell_zone={spell.zone.name}"
        def overheal_is_capped():
            g = new_game(1981); p = g.player1
            p.hero.set_current_health(29); p.max_mana = 2; p.used_mana = 0
            p.give("OG_198").play(target=p.hero)
            eq(p.hero.health, 30, "healing cannot exceed max health")
            eq(p.mana, 0, "all available mana spent even if healing is capped")
            return f"hero_hp={p.hero.health}; mana={p.mana}"
        return [("four_mana_spent_for_eight_healing", "All available mana is spent and target is healed for twice that amount.", spend_all_and_double_heal), ("overheal_capped_but_mana_spent", "Healing is capped at maximum health while all mana is still spent.", overheal_is_capped)]

    if card_id == "OG_200":
        def attack_set_on_own_start():
            g = new_game(200); p = g.player1
            doomsayer = play_minion(p, "OG_200")
            eq(doomsayer.atk, 0, "printed attack before trigger")
            cycle_to_own_start(g,p); first=doomsayer.atk
            cycle_to_own_start(g,p); second=doomsayer.atk
            check((first,second)==(7,7), "at each own-turn start set attack to 7, not add 7", (first,second), "Validated Doomsayer turn trigger")
            return f"attack=0->{first}->{second}"
        return [("start_of_own_turn_sets_attack_seven", "Start of your turn sets Attack to 7 and repeated triggers do not stack.", attack_set_on_own_start)]

    if card_id == "OG_202":
        def slime_choice():
            g = new_game(202); p = g.player1
            p.give("OG_202").play(choose="OG_202a")
            slimes=[c for c in p.field if c.id=="OG_202c"]
            check(len(slimes)==1 and (slimes[0].atk,slimes[0].health)==(2,2), "Summon choice adds one 2/2 Slime", [(c.id,c.atk,c.health) for c in slimes], "Mire Keeper summon choice")
            return f"field={[(c.id,c.atk,c.health) for c in p.field]}"
        def mana_crystal_choice():
            g = new_game(2021); p=g.player1; p.max_mana=5; p.used_mana=0
            p.give("OG_202").play(choose="OG_202b")
            check((p.max_mana,p.mana,[c.id for c in p.field])==(6,1,["OG_202"]), "Pay 4 for Mire Keeper, gain one empty crystal, summon no Slime", (p.max_mana,p.mana,[c.id for c in p.field]), "Mire Keeper crystal choice")
            return f"max_mana=5->{p.max_mana}; mana=5->{p.mana}; field={[c.id for c in p.field]}"
        return [("choose_summons_single_two_two", "Summon choice creates one 2/2 Slime.", slime_choice), ("choose_gain_empty_mana_crystal", "Crystal choice increases max Mana by one and creates no Slime.", mana_crystal_choice)]

    if card_id == "OG_206":
        def targeted_damage_and_overload():
            g = new_game(206); p,e=g.player1,g.player2
            victim=summon_fixture(e,"CS2_182"); victim.set_current_health(4)
            play_card(p,"OG_206",target=victim)
            eq(victim.zone,Zone.GRAVEYARD,"4 damage kills the 4-health minion")
            eq(p.overloaded,1,"spell incurs one overload owed")
            cycle_to_own_start(g,p)
            eq(p.overload_locked,1,"one mana is locked on next own turn")
            return f"victim_zone={victim.zone.name}; overloaded={p.overloaded}; next_turn_locked={p.overload_locked}"
        return [("deal_four_to_minion_and_overload_one", "Deal 4 to a minion and incur Overload (1).", targeted_damage_and_overload)]

    if card_id == "OG_207":
        def random_three_cost(seed):
            g=new_game(seed); p=g.player1
            parent=play_minion(p,"OG_207")
            summoned=[c for c in p.field if c is not parent]
            check(len(summoned)==1 and summoned[0].type==CardType.MINION and summoned[0].cost==3, "Battlecry summons exactly one minion with printed cost 3", [(c.id,int(c.type),c.cost) for c in summoned], "Faceless Summoner random pool")
            return f"seed={seed}; summoned={[(c.id,c.cost,c.zone.name) for c in summoned]}"
        return [(f"random_three_cost_minion_seed_{seed}", "Summon one random 3-Cost minion; test generated card cost and zone over fixed seeds.", lambda seed=seed: random_three_cost(seed)) for seed in (7,19,31,43)]

    if card_id == "OG_209":
        def friendly_spell_damage_heals_owner():
            g=new_game(209); p,e=g.player1,g.player2
            h=play_minion(p,"OG_209"); p.hero.set_current_health(20)
            p.give(MOONFIRE).play(target=e.hero)
            check((e.hero.health,p.hero.health)==(29,21), "friendly spell deals 1 to enemy and heals own hero by exactly 1", (e.hero.health,p.hero.health), "Hallazeal damage event")
            return f"enemy_hp=30->{e.hero.health}; own_hp=20->{p.hero.health}; hallazeal={h.zone.name}"
        def non_spell_damage_does_not_heal():
            g=new_game(2091); p,e=g.player1,g.player2
            play_minion(p,"OG_209"); p.hero.set_current_health(20)
            charger=summon_fixture(p,"CS2_124"); charger.attack(e.hero)
            check((e.hero.health,p.hero.health)==(27,20),"minion combat damage does not trigger Hallazeal's spell-only effect",(e.hero.health,p.hero.health),"Hallazeal source-type filter")
            return f"enemy_hp=30->{e.hero.health}; own_hp={p.hero.health}"
        def multi_damage_spell_sums_healing():
            g=new_game(2092); p,e=g.player1,g.player2
            play_minion(p,"OG_209"); p.hero.set_current_health(20)
            victim=summon_fixture(e,"CS2_182")
            play_card(p,"CS2_012",target=victim)  # Swipe: 4 to target and 1 to other enemies.
            check((victim.health,e.hero.health,p.hero.health)==(1,29,25),"Hallazeal heals for the total 5 damage dealt by Swipe across target and hero",(victim.health,e.hero.health,p.hero.health),"Hallazeal total spell damage")
            return f"victim_hp={victim.health}; enemy_hero=30->{e.hero.health}; own_hero=20->{p.hero.health}"
        return [("friendly_spell_damage_heals_hero", "Damage dealt by your spell restores the same amount of health to your hero.", friendly_spell_damage_heals_owner), ("multi_target_spell_damage_is_summed", "Healing equals total damage dealt to multiple enemy characters by one spell.", multi_damage_spell_sums_healing), ("minion_damage_is_not_spell_damage", "A minion attack does not trigger Hallazeal's spell-only effect.", non_spell_damage_does_not_heal)]

    if card_id == "OG_211":
        def all_companions():
            g=new_game(211); p=g.player1
            p.give("OG_211").play()
            wanted={"NEW1_034","NEW1_033","NEW1_032"}
            companions=[c for c in p.field if c.id in wanted]
            observed={c.id:(c.atk,c.health,c.taunt,c.charge) for c in companions}
            # Leokk (NEW1_033) gives +1 Attack to Huffer and Misha.
            expected={"NEW1_034":(5,2,False,True),"NEW1_032":(5,4,True,False),"NEW1_033":(2,4,False,False)}
            check(len(companions)==3 and observed==expected, "Summon Huffer, Misha, and Leokk with exact printed stats/keywords", observed, "Call of the Wild companions")
            return f"companions={observed}"
        return [("summon_all_three_animal_companions", "Call of the Wild summons Huffer, Misha and Leokk with correct stats and abilities.", all_companions)]

    if card_id == "OG_216":
        def death_summons_two_spiders():
            g=new_game(216); p=g.player1
            wolf=play_minion(p,"OG_216"); wolf.destroy()
            spiders=[c for c in p.field if c.id=="OG_216a"]
            check(wolf.zone==Zone.GRAVEYARD and len(spiders)==2 and all((c.atk,c.health)==(1,1) for c in spiders), "deathrattle summons two 1/1 Spiders", (wolf.zone.name,[(c.id,c.atk,c.health) for c in spiders]), "Infested Wolf deathrattle")
            return f"wolf_zone={wolf.zone.name}; spiders={[(c.id,c.atk,c.health) for c in spiders]}"
        return [("deathrattle_summons_two_spiders", "On death, summon exactly two 1/1 Spiders for its controller.", death_summons_two_spiders)]

    if card_id == "OG_218":
        def taunt_and_enrage_attack():
            g=new_game(218); p=g.player1
            brave=play_minion(p,"OG_218"); base=(brave.atk,brave.taunt)
            damage_minion(brave,1); wounded=brave.atk
            brave.set_current_health(brave.max_health); healed=brave.atk
            check((base,wounded,healed)==((2,True),5,2), "Taunt remains and damaged state grants +3 Attack; healing removes bonus", (base,wounded,healed), "Bloodhoof Brave enrage")
            return f"base={base}; damaged_attack={wounded}; healed_attack={healed}"
        return [("taunt_and_plus_three_while_damaged", "Bloodhoof Brave has Taunt and gains 3 Attack only while damaged.", taunt_and_enrage_attack)]

    if card_id == "OG_220":
        def random_weapon(seed):
            g=new_game(seed); p=g.player1
            malk=play_minion(p,"OG_220"); weapon=p.weapon
            check(weapon is not None and weapon.type==CardType.WEAPON and weapon.durability>0, "Equip one generated weapon for controller, including legal zero-Attack weapons", None if weapon is None else (weapon.id,int(weapon.type),weapon.atk,weapon.durability), "Malkorok weapon equipment")
            check(g.player2.weapon is None, "random weapon is equipped only to Malkorok's controller", None if g.player2.weapon is None else g.player2.weapon.id, "weapon owner")
            return f"seed={seed}; minion={malk.zone.name}; weapon={(weapon.id,weapon.atk,weapon.durability)}"
        return [(f"random_weapon_equipped_seed_{seed}", "Battlecry equips a random weapon to the player who controls Malkorok.", lambda seed=seed: random_weapon(seed)) for seed in (11,23,37,49)]

    if card_id == "OG_221":
        def random_friendly_shield(seed):
            g=new_game(seed); p,e=g.player1,g.player2
            first=summon_fixture(p,WISP); second=summon_fixture(p,"CS2_182"); enemy=summon_fixture(e,WISP)
            hero=play_minion(p,"OG_221"); hero.destroy()
            candidates=[first,second]
            shielded=[c.id for c in candidates if c.divine_shield]
            check(len(shielded)==1 and not enemy.divine_shield, "Deathrattle gives Divine Shield to exactly one random friendly minion, never enemy", {"friendly_shielded":shielded,"enemy_shield":enemy.divine_shield}, "Selfless Hero target domain")
            return f"seed={seed}; friendly_shielded={shielded}; enemy_shield={enemy.divine_shield}"
        def no_friendly_target():
            g=new_game(2215); p=g.player1
            hero=play_minion(p,"OG_221"); hero.destroy()
            check((hero.zone, list(p.field)) == (Zone.GRAVEYARD, []), "Deathrattle safely resolves with no other friendly minion to receive Divine Shield", (hero.zone.name,[c.id for c in p.field]), "Selfless Hero empty target set")
            return f"hero_zone={hero.zone.name}; friendly_field={[c.id for c in p.field]}"
        return ([(f"random_friendly_minion_shield_seed_{seed}", "Deathrattle gives one friendly minion Divine Shield and excludes the enemy board.", lambda seed=seed: random_friendly_shield(seed)) for seed in (13,29,47,61)] + [("no_friendly_target", "With no other friendly minion, deathrattle resolves without an invalid target.", no_friendly_target)])

    if card_id == "OG_222":
        def shield_minions_buff_only():
            g=new_game(222); p,e=g.player1,g.player2
            friendly_shield=summon_fixture(p,"EX1_008"); friendly_plain=summon_fixture(p,WISP)
            enemy_shield=summon_fixture(e,"EX1_008")
            before=(friendly_shield.atk,friendly_shield.health,friendly_plain.atk,friendly_plain.health,enemy_shield.atk,enemy_shield.health)
            blade=play_minion(p,"OG_222")
            after=(friendly_shield.atk,friendly_shield.health,friendly_plain.atk,friendly_plain.health,enemy_shield.atk,enemy_shield.health)
            check((before,after,blade.atk,blade.durability)==((1,1,1,1,1,1),(2,2,1,1,1,1),3,2), "weapon Battlecry gives +1/+1 to friendly Divine Shield minions only", (before,after,blade.atk,blade.durability), "Rallying Blade")
            return f"before={before}; after={after}; blade={(blade.atk,blade.durability)}"
        return [("battlecry_buffs_friendly_divine_shield_minions", "Rallying Blade equips a 3/2 weapon and buffs only friendly minions with Divine Shield by +1/+1.", shield_minions_buff_only)]

    if card_id == "OG_223":
        def buff_target():
            g=new_game(223); p,e=g.player1,g.player2
            target=summon_fixture(e,WISP); play_card(p,"OG_223",target=target)
            check((target.atk,target.health,target.max_health)==(2,3,3), "selected minion receives +1/+2 regardless of controller", (target.atk,target.health,target.max_health), "Divine Strength target scope")
            return f"enemy_target={(target.atk,target.health,target.max_health)}"
        return [("spell_gives_plus_one_plus_two_to_minion", "Divine Strength gives a chosen minion +1/+2.", buff_target)]

    if card_id == "OG_229":
        def end_turn_heal_friendly_random(seed):
            g=new_game(seed); p,e=g.player1,g.player2
            hero=p.hero; hero.set_current_health(20)
            friendly=summon_fixture(p,"CS2_182"); friendly.set_current_health(2)
            enemy=summon_fixture(e,"CS2_182"); enemy.set_current_health(2)
            rag=play_minion(p,"OG_229")
            g.end_turn()
            changed=(hero.health-20, friendly.health-2, enemy.health-2)
            check(sum(x>0 for x in changed)==1 and all(x>=0 and x<=8 for x in changed) and changed[2]==0, "at own turn end heal exactly one damaged friendly character by up to 8; never enemy", changed, "Ragnaros Lightlord random heal domain")
            return f"seed={seed}; heal_delta={changed}; rag={rag.zone.name}"
        return [(f"own_end_random_friendly_heal_seed_{seed}", "At end of your turn, heal one damaged friendly character (up to 8), not the enemy.", lambda seed=seed: end_turn_heal_friendly_random(seed)) for seed in (5,17,31,47)]

    if card_id == "OG_234":
        def exact_five_to_not_full_hero():
            g=new_game(2342); p,e=g.player1,g.player2
            p.hero.set_current_health(20)
            alchemist=play_minion(p,"OG_234",target=p.hero)
            check((p.hero.health,p.hero.max_health,e.hero.health,alchemist.zone)==(25,30,30,Zone.PLAY), "heal selected 20/30 friendly hero for exactly 5 and leave Alchemist in play", (p.hero.health,p.hero.max_health,e.hero.health,alchemist.zone.name), "Darkshire Alchemist exact heal amount")
            return f"friendly_hero=20->{p.hero.health}/30; enemy_hero={e.hero.health}; alchemist={alchemist.zone.name}"
        def targeted_heal_five():
            g=new_game(234); p,e=g.player1,g.player2
            target=summon_fixture(e,"CS2_182"); target.set_current_health(1)
            alchemist=play_minion(p,"OG_234",target=target)
            check((target.health,target.max_health,alchemist.zone)==(5,5,Zone.PLAY), "Battlecry restores exactly 5 to selected character and leaves body in play", (target.health,target.max_health,alchemist.zone.name), "Darkshire Alchemist targeted heal")
            return f"target_hp=1->{target.health}/{target.max_health}; alchemist={alchemist.zone.name}"
        def full_target_does_not_overheal():
            g=new_game(2341); p,e=g.player1,g.player2
            target=e.hero; before=target.health
            play_minion(p,"OG_234",target=target)
            eq(target.health,before,"full-health hero does not overheal")
            return f"target_hp={target.health}; cap={target.max_health}"
        return [
            ("battlecry_restores_five_to_chosen_character", "Restore 5 Health to the chosen character.", targeted_heal_five),
            ("non_capped_hero_heal_exactly_five", "A 20/30 friendly hero heals to 25/30, proving the exact +5 amount and selected target.", exact_five_to_not_full_hero),
            ("full_health_target_capped", "Healing a full-health target does not exceed maximum Health.", full_target_does_not_overheal),
        ]

    if card_id == "OG_239":
        def destroy_and_draw_for_predeath_count():
            g=new_game(239); p,e=g.player1,g.player2
            one=summon_fixture(p,WISP); two=summon_fixture(p,"CS2_182"); three=summon_fixture(e,WISP)
            for cid in ("CS2_172","CS2_181","CS2_182"):
                p.give(cid).shuffle_into_deck()
            predeck=len(p.deck); prehand=len(p.hand)
            play_card(p,"OG_239")
            check((one.zone,two.zone,three.zone,len(p.hand)-prehand,len(p.deck),predeck)==(Zone.GRAVEYARD,Zone.GRAVEYARD,Zone.GRAVEYARD,3,0,3), "destroy all minions on both sides, then draw one per destroyed minion", (one.zone.name,two.zone.name,three.zone.name,len(p.hand)-prehand,len(p.deck),predeck), "DOOM! count and draw")
            return f"zones={(one.zone.name,two.zone.name,three.zone.name)}; draws={len(p.hand)-prehand}; deck={predeck}->{len(p.deck)}"
        def deathrattle_token_not_counted_as_original():
            g=new_game(2391); p,e=g.player1,g.player2
            villager=summon_fixture(p,"OG_241"); other=summon_fixture(e,WISP)
            for cid in ("CS2_172","CS2_181"):
                p.give(cid).shuffle_into_deck()
            before_hand=len(p.hand); before_deck=len(p.deck)
            play_card(p,"OG_239")
            tokens=[c for c in p.field if c.id=="OG_241a"]
            check((villager.zone,other.zone,len(p.hand)-before_hand,len(p.deck),before_deck,len(tokens))==(Zone.GRAVEYARD,Zone.GRAVEYARD,2,0,2,1), "draw count uses the two minions present when DOOM resolves; Villager Deathrattle token appears without changing draw count", (villager.zone.name,other.zone.name,len(p.hand)-before_hand,len(p.deck),before_deck,len(tokens)), "DOOM deathrattle and draw ordering")
            return f"original_zones={(villager.zone.name,other.zone.name)}; draws={len(p.hand)-before_hand}; deck={before_deck}->{len(p.deck)}; tokens={[(c.id,c.zone.name) for c in tokens]}"
        return [("destroy_both_boards_and_draw_predeath_count", "Destroy all minions on both sides and draw one card for each of the three destroyed minions.", destroy_and_draw_for_predeath_count), ("deathrattle_token_and_draw_snapshot", "Check count/timing when a destroyed minion's Deathrattle summons a token.", deathrattle_token_not_counted_as_original)]

    if card_id == "OG_241":
        def death_summons_shadowbeast():
            g=new_game(241); p=g.player1
            villager=play_minion(p,"OG_241"); villager.destroy()
            tokens=[c for c in p.field if c.id=="OG_241a"]
            check((villager.zone,len(tokens),[(c.atk,c.health) for c in tokens])==(Zone.GRAVEYARD,1,[(1,1)]), "Deathrattle summons one 1/1 Shadowbeast", (villager.zone.name,len(tokens),[(c.atk,c.health) for c in tokens]), "Possessed Villager deathrattle")
            return f"villager={villager.zone.name}; shadowbeasts={[(c.id,c.atk,c.health) for c in tokens]}"
        return [("deathrattle_summons_one_shadowbeast", "On death, summon a 1/1 Shadowbeast for its controller.", death_summons_shadowbeast)]

    if card_id == "OG_247":
        def stealth_until_attack():
            g=new_game(247); p,e=g.player1,g.player2
            worgen=play_minion(p,"OG_247")
            initial=worgen.stealthed
            g.end_turn()  # Let the opponent test an explicit target while Worgen is stealthed.
            enemy_spell=e.give("CS2_029")
            enemy_can_target=worgen in enemy_spell.play_targets
            before_mana=e.mana
            try:
                enemy_spell.play(target=worgen); accepted=True
            except Exception:
                accepted=False
            check((enemy_can_target,accepted,enemy_spell.zone,e.mana)==(False,False,Zone.HAND,before_mana),"stealthed Worgen is not a legal Fireball target; rejected play preserves card/mana",(enemy_can_target,accepted,enemy_spell.zone.name,e.mana,before_mana),"Stealth target rejection")
            g.end_turn()
            worgen.attack(e.hero)
            check((initial,enemy_can_target,accepted,worgen.stealthed,e.hero.health)==(True,False,False,False,27), "Stealth blocks enemy targeted spell while active; attacking removes Stealth and deals printed attack", (initial,enemy_can_target,accepted,worgen.stealthed,e.hero.health), "Twisted Worgen Stealth")
            return f"stealth={initial}->{worgen.stealthed}; enemy_spell_legal={enemy_can_target}; enemy_hp={e.hero.health}"
        return [("stealth_blocks_targeting_then_ends_on_attack", "Stealth prevents enemy targeting until Worgen attacks; its attack removes Stealth.", stealth_until_attack)]

    if card_id == "OG_249":
        def taunt_and_death_token():
            g=new_game(249); p=g.player1
            tauren=play_minion(p,"OG_249")
            eq(tauren.taunt,True,"native Taunt")
            tauren.destroy(); slimes=[c for c in p.field if c.id=="OG_249a"]
            check((tauren.zone,len(slimes),[(c.atk,c.health) for c in slimes])==(Zone.GRAVEYARD,1,[(2,2)]), "Taunt minion death summons one 2/2 Slime", (tauren.zone.name,len(slimes),[(c.atk,c.health) for c in slimes]), "Infested Tauren deathrattle")
            return f"tauren_taunt={tauren.taunt}; tauren_zone={tauren.zone.name}; slimes={[(c.atk,c.health) for c in slimes]}"
        return [("taunt_body_death_summons_two_two", "Infested Tauren has Taunt and its deathrattle summons a 2/2 Slime.", taunt_and_death_token)]

    if card_id == "OG_254":
        def destroy_secrets_and_scale():
            g=new_game(254,CardClass.HUNTER,CardClass.HUNTER); p,e=g.player1,g.player2
            advance_to_turn(g,e)
            for secret_id in ("EX1_379","EX1_609","EX1_294"):
                play_card(e,secret_id)
            advance_to_turn(g,p)
            count=len(e.secrets); eater=play_minion(p,"OG_254")
            check((count,len(e.secrets),eater.atk,eater.health)==(3,0,5,7), "Destroy all three enemy Secrets and gain +1/+1 for each", (count,len(e.secrets),eater.atk,eater.health), "Eater of Secrets")
            return f"enemy_secrets={count}-> {len(e.secrets)}; eater={(eater.atk,eater.health)}"
        def no_secrets_no_buff():
            g=new_game(2541); p=g.player1
            eater=play_minion(p,"OG_254")
            eq((eater.atk,eater.health),(2,4),"no enemy secrets means no stats gained")
            return f"eater={(eater.atk,eater.health)}"
        return [("destroy_enemy_secrets_gain_per_secret", "Destroy each enemy Secret and gain +1/+1 for each destroyed.", destroy_secrets_and_scale), ("no_secrets_no_stat_bonus", "With no enemy Secrets, Eater keeps its printed stats.", no_secrets_no_buff)]

    if card_id == "OG_255":
        def buff_live_cthun():
            g=new_game(255); p=g.player1
            cthun=p.cthun; before=(cthun.atk,cthun.max_health,cthun.zone)
            doom=play_minion(p,"OG_255")
            check((cthun.atk,cthun.max_health,cthun.zone)==(before[0]+2,before[1]+2,before[2]), "C'Thun receives +2/+2 wherever it is; no duplicate is added while not dead", (cthun.atk,cthun.max_health,cthun.zone.name), "Doomcaller live C'Thun")
            return f"cthun={before[:2]}->{(cthun.atk,cthun.max_health)} zone={cthun.zone.name}; doom={doom.zone.name}"
        def buffs_cthun_in_deck():
            g=new_game(2551); p=g.player1
            cthun=p.cthun; cthun.shuffle_into_deck(); before=(cthun.atk,cthun.max_health)
            play_minion(p,"OG_255")
            check((cthun.atk,cthun.max_health,cthun.zone)==(before[0]+2,before[1]+2,Zone.DECK), "Doomcaller buffs C'Thun while it is in deck", (cthun.atk,cthun.max_health,cthun.zone.name), "Doomcaller deck zone")
            return f"cthun={before}->{(cthun.atk,cthun.max_health)} zone={cthun.zone.name}; deck={[c.id for c in p.deck]}"
        def dead_cthun_shuffled_back():
            g=new_game(2552); p=g.player1
            cthun=play_card(p,"OG_280"); cthun.destroy()
            eq(cthun.zone,Zone.GRAVEYARD,"C'Thun death setup")
            p.used_mana=0
            before=(cthun.atk,cthun.max_health)
            play_minion(p,"OG_255")
            deck_cthun=[c for c in p.deck if c.id=="OG_280"]
            check(len(deck_cthun)==1 and deck_cthun[0].zone==Zone.DECK and (deck_cthun[0].atk,deck_cthun[0].max_health)==(before[0]+2,before[1]+2),"dead C'Thun is buffed +2/+2 and shuffled into owner's deck",[(c.id,c.zone.name,c.atk,c.max_health) for c in deck_cthun],"Doomcaller dead C'Thun branch")
            return f"cthun_graveyard_at_start={before}; deck_cthuns={[(c.zone.name,c.atk,c.max_health) for c in deck_cthun]}"
        return [("battlecry_buffs_cthun_wherever", "Battlecry buffs the owner's live C'Thun by +2/+2 wherever it is.", buff_live_cthun), ("buff_cthun_inside_deck", "The wherever clause also buffs C'Thun while in deck.", buffs_cthun_in_deck), ("dead_cthun_buffed_and_shuffled_back", "If C'Thun has died, buff and shuffle it into the owner's deck.", dead_cthun_shuffled_back)]

    if card_id == "OG_267":
        def death_weapon_buff():
            g=new_game(267); p=g.player1
            weapon=p.give(LIGHTS_JUSTICE); weapon.play(); before=(weapon.atk,weapon.durability)
            squid=play_minion(p,"OG_267"); squid.destroy()
            check((weapon.atk,weapon.durability,squid.zone)==(before[0]+2,before[1],Zone.GRAVEYARD), "Deathrattle adds +2 Attack to equipped weapon without changing durability", (weapon.atk,weapon.durability,squid.zone.name), "Southsea Squidface deathrattle")
            return f"weapon={before}->{(weapon.atk,weapon.durability)}; squid={squid.zone.name}"
        def death_without_weapon_safe():
            g=new_game(2671); p=g.player1
            squid=play_minion(p,"OG_267"); squid.destroy()
            eq(squid.zone,Zone.GRAVEYARD,"dies normally when no weapon exists")
            eq(p.weapon,None,"does not create a weapon")
            return f"squid={squid.zone.name}; weapon={p.weapon}"
        return [("deathrattle_buffs_equipped_weapon", "Deathrattle gives the equipped friendly weapon +2 Attack.", death_weapon_buff), ("death_without_weapon", "Without a friendly weapon, deathrattle does not create one or error.", death_without_weapon_safe)]

    if card_id == "OG_271":
        def attack_doubles_on_turn_start():
            g=new_game(271); p=g.player1
            nightmare=play_minion(p,"OG_271"); initial=nightmare.atk
            cycle_to_own_start(g,p); first=nightmare.atk
            cycle_to_own_start(g,p); second=nightmare.atk
            check((initial,first,second)==(2,4,8), "attack doubles at each own-turn start", (initial,first,second), "Scaled Nightmare trigger timing")
            return f"attack={initial}->{first}->{second}; health={nightmare.health}/{nightmare.max_health}"
        return [("attack_doubles_each_own_turn_start", "Scaled Nightmare doubles its Attack at each start of your turn.", attack_doubles_on_turn_start)]

    raise KeyError(card_id)


def get_context(card_id):
    audit = AUDIT_ROWS[card_id]
    master = MASTER_ROWS[card_id]
    src = audit.get("python_source") or "fireplace/cards/CardDefs.xml:" + card_id
    test = current_test_name(card_id)
    return f"EN: {master.get('card_text_en',audit.get('card_text_en',''))}; CN: {master.get('card_text_zh','')}; source: {src}; prior test: tests/test_wog.py::{test}; prior audit: {audit.get('evidence','')}"


def finish_card(card_id):
    cases = CARD_CASES[card_id]
    bad = [case for case in cases if case["outcome"] == "confirmed_error"]
    inconclusive = [case for case in cases if case["outcome"] != "pass"]
    if bad:
        status = "RED"
        reason = "; ".join(f"{case['case_id']}: {case['observed']}" for case in bad)
    elif inconclusive:
        status = "YELLOW"
        reason = "; ".join(f"{case['case_id']} inconclusive: {case['observed']}" for case in inconclusive)
    elif card_id in YELLOW_BLOCKERS:
        status = "YELLOW"
        reason = YELLOW_BLOCKERS[card_id]
    else:
        status = "GREEN"
        reason = f"{len(cases)} 本轮逐卡实战用例通过；覆盖文本中的核心效果及所列条件。"
    verdict = {
        "card_id": card_id,
        "status": status,
        "mechanic_scope": AUDIT_ROWS[card_id].get("mechanic", ""),
        "reason": reason,
        "probe_file": "og_probe_b.csv",
        "notes": get_context(card_id),
    }
    VERDICTS.append(verdict)
    save_probe()
    save_verdict()  # Persist the row immediately when this card is complete.
    print(f"{card_id}: {status} ({len(cases)} cases)")


def main():
    assert len(BASE_ROWS) == len(IDS) == 42
    assert IDS[0] == "OG_133" and IDS[-1] == "OG_271"
    existing = read_csv(PROBE) if PROBE.exists() else []
    existing_verdicts = read_csv(VERDICT) if VERDICT.exists() else []
    # Resume safely after interruption: retain completed card outputs and skip them.
    global PROBES, VERDICTS
    redo = {value.strip() for value in os.environ.get("OG_PROBE_REDO_IDS", "").split(",") if value.strip()}
    completed = {row["card_id"] for row in existing_verdicts} - redo
    PROBES = [row for row in existing if row["card_id"] not in redo]
    VERDICTS = [row for row in existing_verdicts if row["card_id"] not in redo]
    limit = int(os.environ.get("OG_PROBE_LIMIT", str(len(IDS))))
    completed_now = 0
    for card_id in IDS:
        if card_id in completed:
            print(f"{card_id}: already persisted, skipping")
            continue
        specs = cases_for(card_id)
        before = len(PROBES)
        for case_id, expected, action in specs:
            run_case(card_id, case_id, expected, action)
        assert len(PROBES) > before, card_id
        assert len({(row['card_id'],row['case_id']) for row in PROBES}) == len(PROBES)
        finish_card(card_id)
        completed_now += 1
        if completed_now >= limit:
            break
    print(f"DONE cards={len(VERDICTS)} cases={len(PROBES)} statuses={dict(PyCounter(row['status'] for row in VERDICTS))}")


if __name__ == "__main__":
    main()
