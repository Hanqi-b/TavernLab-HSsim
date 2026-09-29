#!/usr/bin/env python3
"""Card-specific behavioral probes for yellow collectible Hall of Fame cards."""

import csv
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))

from utils import *  # noqa: E402,F401,F403
from fireplace.card import Card  # noqa: E402
from fireplace.logging import log  # noqa: E402


OUT = Path(__file__).resolve().parent
PROBE_PATH = OUT / "hof_probe.csv"
VERDICT_PATH = OUT / "hof_verdict.csv"
PROBE_FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
VERDICT_FIELDS = ["card_id", "status", "mechanic_scope", "reason", "probe_file", "notes"]
FAILED_CARDS = set()
UNRESOLVED_CARDS = {}


def card_scope(card_id):
    quality = OUT / "card_quality.csv"
    with quality.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["card_id"] == card_id:
                return row["mechanic"]
    return ""

for handler in log.handlers:
    handler.setLevel(logging.WARNING)
log.setLevel(logging.WARNING)


def _read_rows(path, fields):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def record_case(card_id, case_id, expected, observed, outcome, notes=""):
    rows = _read_rows(PROBE_PATH, PROBE_FIELDS)
    key = (card_id, case_id)
    row = dict(card_id=card_id, case_id=case_id, expected=expected,
               observed=str(observed), outcome=outcome, notes=notes)
    rows = [r for r in rows if (r["card_id"], r["case_id"]) != key]
    rows.append(row)
    _write_rows(PROBE_PATH, PROBE_FIELDS, rows)


def record_verdict(card_id, status, mechanic_scope, reason, notes=""):
    rows = _read_rows(VERDICT_PATH, VERDICT_FIELDS)
    row = dict(card_id=card_id, status=status,
               mechanic_scope=mechanic_scope or card_scope(card_id),
               reason=reason, probe_file="hof_probe.csv", notes=notes)
    rows = [r for r in rows if r["card_id"] != card_id]
    rows.append(row)
    _write_rows(VERDICT_PATH, VERDICT_FIELDS, rows)


def run_case(card_id, case_id, expected, probe, validate, notes=""):
    try:
        observed = probe()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
        UNRESOLVED_CARDS.setdefault(card_id, []).append(f"{case_id}: probe setup/execution raised {detail}")
        record_case(card_id, case_id, expected, detail, outcome, notes)
        print(f"INCONCLUSIVE {card_id} {case_id}: {detail}")
        return False
    try:
        assert validate(observed), f"expected={expected}; observed={observed}"
    except AssertionError as exc:
        detail = f"{observed}; assertion={exc}"
        outcome = "confirmed_error"
        FAILED_CARDS.add(card_id)
        record_case(card_id, case_id, expected, detail, outcome, notes)
        print(f"FAIL {card_id} {case_id}: expected={expected}; observed={detail}")
        record_verdict(card_id, "RED", card_scope(card_id), f"失败断言 {case_id}: {detail}",
                       "至少一条逐卡行为断言失败；保留完整探针行。")
        return False
    except Exception as exc:
        detail = f"{observed}; validator={type(exc).__name__}: {exc}"
        outcome = "inconclusive"
        UNRESOLVED_CARDS.setdefault(card_id, []).append(f"{case_id}: validator raised {type(exc).__name__}: {exc}")
        record_case(card_id, case_id, expected, detail, outcome, notes)
        print(f"INCONCLUSIVE {card_id} {case_id}: {detail}")
        return False
    record_case(card_id, case_id, expected, observed, "pass", notes)
    print(f"PASS {card_id} {case_id}: {observed}")
    return True


def finish_card(card_id, mechanic_scope, reason, notes="", unresolved=None):
    if card_id in FAILED_CARDS:
        status = "RED"
        reason = "至少一条逐卡行为断言失败；见对应 probe 行。"
    elif unresolved or card_id in UNRESOLVED_CARDS:
        status = "YELLOW"
        reason = unresolved or "；".join(UNRESOLVED_CARDS[card_id])
    else:
        status = "GREEN"
    record_verdict(card_id, status, mechanic_scope, reason, notes)


def fresh_game(class1=CardClass.MAGE, class2=CardClass.MAGE):
    return prepare_empty_game(class1, class2)


def starting_deck_game(deck1, deck2, hero1="HERO_01", hero2="HERO_01"):
    p1 = Player("Player1", list(deck1), hero1)
    p2 = Player("Player2", list(deck2), hero2)
    game = BaseTestGame(players=(p1, p2))
    game.start()
    for player in game.players:
        if player.choice:
            player.choice.choose()
    return game, p1, p2


def seed_deck(player, card_id, count=1):
    for _ in range(count):
        player.give(card_id).shuffle_into_deck()


def ice_lance_first_target():
    game = fresh_game()
    target = game.player2.hero
    spell = game.player1.give("CS2_031")
    before = target.health
    spell.play(target=target)
    return {"frozen": target.frozen, "health_before": before,
            "health_after": target.health, "spell_zone": spell.zone.name}


def ice_lance_repeat_frozen_target():
    game = fresh_game()
    target = game.player2.hero
    game.player1.give("CS2_031").play(target=target)
    spell = game.player1.give("CS2_031")
    before = target.health
    spell.play(target=target)
    return {"frozen": target.frozen, "health_before": before,
            "health_after": target.health, "spell_zone": spell.zone.name}


def probe_ice_lance():
    run_case("CS2_031", "initial_freeze_no_damage",
             "An unfrozen enemy character becomes Frozen and takes no damage; spell resolves to graveyard.",
             ice_lance_first_target,
             lambda x: x == {"frozen": True, "health_before": 30, "health_after": 30,
                             "spell_zone": "GRAVEYARD"},
             "Reproduces tests/test_classic.py::test_ice_lance first cast with a fresh game.")
    run_case("CS2_031", "repeat_on_frozen_character_deals_4",
             "A second Ice Lance on the Frozen enemy deals exactly 4 and leaves it Frozen.",
             ice_lance_repeat_frozen_target,
             lambda x: x == {"frozen": True, "health_before": 30, "health_after": 26,
                             "spell_zone": "GRAVEYARD"},
             "Checks the already-Frozen branch independently of the first case.")
    finish_card("CS2_031", "Spell resolution|Targeting",
                "两条分支均实测通过：首次施放只冻结；已冻结目标再次施放造成4点伤害。",
                "参考既有 tests/test_classic.py::test_ice_lance 与 targeting_static_audit.csv；本探针直接验证效果与法术落区。")


def probe_northshire_cleric():
    def heal_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        cleric = game.player1.give("CS2_235")
        cleric.play()
        damaged = game.player2.summon("CS1_042")
        full = game.player1.summon("CS1_042")
        damaged.damage = 1
        seed_deck(game.player1, WISP)
        seed_deck(game.player1, MOONFIRE)
        game.player1.give(CIRCLE_OF_HEALING).play()
        return {"damaged_health": damaged.health, "damaged_max": damaged.max_health,
                "full_health": full.health, "hand_ids": [c.id for c in game.player1.hand],
                "deck_size": len(game.player1.deck)}

    run_case("CS2_235", "draw_once_for_healed_minion_only",
             "Circle heals one damaged minion and a full minion; exactly one card is drawn.",
             heal_case,
             lambda x: x["damaged_health"] == 2 and x["damaged_max"] == 2
             and x["full_health"] == 2 and len(x["hand_ids"]) == 1
             and x["hand_ids"][0] in {WISP, MOONFIRE}
             and x["deck_size"] == 1,
             "Existing tests/test_classic.py::test_northshire_cleric exercises Circle of Healing; this isolates one actually healed minion versus one already full.")
    finish_card("CS2_235", "Draw / Discard|Trigger",
                "每个实际被治疗的随从触发一次抽牌；满血随从没有额外触发。",
                "观察手牌与牌库实体数，验证触发次数而非只看战吼/出牌成功。")


def probe_divine_spirit():
    def double_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        target = game.player2.summon("CS1_042")
        target.damage = 1
        before = (target.health, target.max_health)
        attack_before = target.atk
        game.player1.give("CS2_236").play(target=target)
        return {"before": before, "after": (target.health, target.max_health),
                "attack_before": attack_before, "attack_after": target.atk,
                "enemy_control_retained": target.controller is game.player2}

    run_case("CS2_236", "double_current_minion_health",
             "Casting on a 1/2-damaged minion doubles its current and maximum Health, not Attack.",
             double_case,
             lambda x: x["before"] == (1, 2) and x["after"] == (2, 3)
             and x["attack_before"] == x["attack_after"] == 1
             and x["enemy_control_retained"],
             "Existing tests/test_classic.py::test_divine_spirit checks repeated full-health doubling; this probes a damaged target and current/max-health accounting.")
    finish_card("CS2_236", "Spell resolution|Targeting",
             "合法敌方受伤随从的当前生命和最大生命按卡面效果增长；攻击力与控制者不变。",
                "目标是敌方受伤随从；覆盖敌方合法目标效果。")


def probe_mind_blast():
    def blast_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        friendly = game.player1.summon(WISP)
        enemy = game.player2.summon(WISP)
        spell = game.player1.give("DS1_233")
        spell.play()
        return {"enemy_hero": game.player2.hero.health,
                "friendly_hero": game.player1.hero.health,
                "friendly_minion": friendly.health, "enemy_minion": enemy.health,
                "spell_zone": spell.zone.name}

    run_case("DS1_233", "enemy_hero_only_five_damage",
             "Mind Blast deals 5 to the enemy hero, leaves both minions and the friendly hero untouched, and resolves to graveyard.",
             blast_case,
             lambda x: x == {"enemy_hero": 25, "friendly_hero": 30,
                             "friendly_minion": 1, "enemy_minion": 1,
                             "spell_zone": "GRAVEYARD"},
             "Direct effect check; prior mechanism audit had only generic-play smoke.")
    finish_card("DS1_233", "Spell resolution",
                "仅敌方英雄受到5点伤害，友方角色和双方随从均未改变。")


def probe_acolyte_of_pain():
    def multi_damage_case():
        game = fresh_game()
        acolyte = game.player1.give("EX1_007")
        acolyte.play()
        seed_deck(game.player1, WISP, 3)
        for _ in range(3):
            game.player1.give(MOONFIRE).play(target=acolyte)
        return {"acolyte_zone": acolyte.zone.name, "dead": acolyte.dead,
                "hand_ids": [c.id for c in game.player1.hand],
                "deck_size": len(game.player1.deck)}

    run_case("EX1_007", "draw_for_each_damage_instance_including_lethal",
             "Three separate damage events cause three draws; the third is lethal and Acolyte reaches graveyard.",
             multi_damage_case,
             lambda x: x["acolyte_zone"] == "GRAVEYARD" and x["dead"]
             and x["hand_ids"] == [WISP, WISP, WISP] and x["deck_size"] == 0,
             "Existing tests/test_classic.py::test_acolyte_of_pain checks two nonlethal hits; this includes the lethal damage event and physical draw entities.")
    finish_card("EX1_007", "Draw / Discard|Trigger",
                "每次受伤均抽一张，包括致死伤害；侍僧死亡入墓。")


def probe_sylvanas_windrunner():
    def steal_one_case():
        game = fresh_game()
        sylvanas = game.player1.give("EX1_016")
        sylvanas.play()
        targets = [game.player2.summon(WISP), game.player2.summon("CS1_042")]
        sylvanas.destroy()
        stolen = [m for m in targets if m.controller is game.player1]
        left = [m for m in targets if m.controller is game.player2]
        return {"sylvanas_zone": sylvanas.zone.name,
                "stolen_ids": [m.id for m in stolen],
                "stolen_zones": [m.zone.name for m in stolen],
                "enemy_remaining": [m.id for m in left],
                "friendly_field": [m.id for m in game.player1.field]}

    run_case("EX1_016", "deathrattle_steals_exactly_one_random_enemy",
             "After Sylvanas dies, exactly one of two enemy minions changes control; the other remains enemy-controlled.",
             steal_one_case,
             lambda x: x["sylvanas_zone"] == "GRAVEYARD" and len(x["stolen_ids"]) == 1
             and x["stolen_zones"] == ["PLAY"] and len(x["enemy_remaining"]) == 1
             and len(x["friendly_field"]) == 1,
             "Existing test_classic.py::test_sylvanas_windrunner covers deathrattle; this checks random pool cardinality and controller transfer in a live game.")
    def seeded_candidates_case():
        candidate_ids = (WISP, "CS1_042", "CS2_182")
        outcomes = {}
        for seed in range(10):
            game = fresh_game()
            game.random.seed(seed)
            sylvanas = game.player1.give("EX1_016")
            sylvanas.play()
            targets = [game.player2.summon(cid) for cid in candidate_ids]
            sylvanas.destroy()
            stolen = [m.id for m in targets if m.controller is game.player1]
            outcomes[str(seed)] = stolen
        return {"outcomes": outcomes,
                "candidates_reached": sorted({cid for ids in outcomes.values() for cid in ids})}

    run_case("EX1_016", "seeded_random_pool_reaches_each_candidate",
             "Across fixed RNG seeds 0-9, each of the three enemy minions is observed as the deathrattle's stolen target.",
             seeded_candidates_case,
             lambda x: x["candidates_reached"] == sorted((WISP, "CS1_042", "CS2_182"))
             and all(len(v) == 1 for v in x["outcomes"].values()),
             "Fixed game.random seeds verify all candidate identities are reachable; each sample still steals exactly one.")
    def simultaneous_clear_case():
        game = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
        sylvanas = game.player1.give("EX1_016")
        sylvanas.play()
        enemies = [game.player2.summon(WISP), game.player2.summon("CS1_042")]
        ally = game.player1.summon(WISP)
        game.player1.used_mana = 0
        game.player1.give("EX1_312").play()
        return {"sylvanas_zone": sylvanas.zone.name,
                "enemy_zones": [m.zone.name for m in enemies],
                "ally_zone": ally.zone.name,
                "friendly_field": [m.id for m in game.player1.field],
                "enemy_field": [m.id for m in game.player2.field]}

    run_case("EX1_016", "deathrattle_has_no_live_target_in_simultaneous_clear",
             "When Sylvanas and all enemy minions die in the same Twisting Nether resolution, all remain dead and no dead minion is stolen.",
             simultaneous_clear_case,
             lambda x: x == {"sylvanas_zone": "GRAVEYARD",
                             "enemy_zones": ["GRAVEYARD", "GRAVEYARD"],
                             "ally_zone": "GRAVEYARD", "friendly_field": [], "enemy_field": []},
             "Covers deathrattle ordering against a same-batch full-board destruction.")
    finish_card("EX1_016", "Deathrattle|Random effects",
                "死亡后从两个敌方随从中随机夺取恰好一个；另一个仍归对手控制。")


def probe_spellbreaker():
    def silence_deathrattle_case():
        game = fresh_game()
        cairne = game.player2.summon("EX1_110")
        breaker = game.player1.give("EX1_048")
        breaker.play(target=cairne)
        silenced = not cairne.has_deathrattle
        cairne.destroy()
        return {"silenced": silenced, "cairne_zone": cairne.zone.name,
                "baine_ids": [m.id for p in game.players for m in p.field if m.id == "EX1_110t"],
                "breaker_zone": breaker.zone.name}

    run_case("EX1_048", "battlecry_silences_enemy_deathrattle",
             "Spellbreaker can target an enemy minion; silence removes Cairne's Deathrattle, so killing it creates no Baine.",
             silence_deathrattle_case,
             lambda x: x["silenced"] and x["cairne_zone"] == "GRAVEYARD"
             and not x["baine_ids"] and x["breaker_zone"] == "PLAY",
             "Targeting sweep covered missing/illegal target prereqs; this validates the actual battlecry and later deathrattle suppression.")
    def friendly_target_case():
        game = fresh_game()
        cairne = game.player1.summon("EX1_110")
        breaker = game.player1.give("EX1_048")
        breaker.play(target=cairne)
        silenced = not cairne.has_deathrattle
        cairne.destroy()
        return {"silenced_friendly": silenced,
                "cairne_zone": cairne.zone.name,
                "baine_summoned": any(m.id == "EX1_110t" for p in game.players for m in p.field)}

    run_case("EX1_048", "battlecry_can_target_friendly_minion",
             "Spellbreaker can also target a friendly minion, silence its Deathrattle, and prevent its Baine token.",
             friendly_target_case,
             lambda x: x == {"silenced_friendly": True, "cairne_zone": "GRAVEYARD",
                             "baine_summoned": False},
             "Complements the enemy-target case; the card text does not restrict target controller.")
    finish_card("EX1_048", "Battlecry|Silence|Targeting",
                "战吼合法指定敌方随从并沉默；被沉默的亡语不再召唤贝恩。")


def probe_old_murk_eye():
    def count_charge_case():
        game = fresh_game()
        game.player1.summon(MURLOC)
        game.player2.summon(MURLOC)
        murkeye = game.player1.give("EX1_062")
        murkeye.play()
        initial = {"atk": murkeye.atk, "charge": murkeye.charge,
                   "can_attack": murkeye.can_attack()}
        murkeye.attack(game.player2.hero)
        after_attack = game.player2.hero.health
        added = game.player2.summon(MURLOC)
        after_add = murkeye.atk
        added.destroy()
        after_remove = murkeye.atk
        return {"initial": initial, "opponent_health": after_attack,
                "after_add": after_add, "after_remove": after_remove}

    run_case("EX1_062", "charge_and_live_murloc_count_updates",
             "Murk-Eye has Charge, gets +1 Attack for each other Murloc on both boards, can attack immediately, and loses the aura when one dies.",
             count_charge_case,
             lambda x: x["initial"] == {"atk": 4, "charge": True, "can_attack": True}
             and x["opponent_health"] == 26 and x["after_add"] == 5
             and x["after_remove"] == 4,
             "Existing tests/test_classic.py::test_old_murkeye covers stat changes and Charge; this additionally performs an immediate hero attack and tests opposing Murloc removal.")
    finish_card("EX1_062", "Charge|Conditional stats|Continuous effect / Update",
                "立即攻击合法；攻击力按双方场上其他鱼人动态增减。")


def probe_mind_control_tech():
    def below_threshold_case():
        game = fresh_game()
        targets = [game.player2.summon(WISP) for _ in range(3)]
        tech = game.player1.give("EX1_085")
        tech.play()
        return {"enemy_controls": sum(m.controller is game.player2 for m in targets),
                "friendly_controls": sum(m.controller is game.player1 for m in targets),
                "tech_zone": tech.zone.name}

    def threshold_case():
        game = fresh_game()
        targets = [game.player2.summon(WISP) for _ in range(4)]
        tech = game.player1.give("EX1_085")
        tech.play()
        return {"stolen": sum(m.controller is game.player1 for m in targets),
                "enemy_left": sum(m.controller is game.player2 for m in targets),
                "friendly_field": [m.id for m in game.player1.field],
                "enemy_field": [m.id for m in game.player2.field],
                "tech_zone": tech.zone.name}

    run_case("EX1_085", "no_steal_below_four_enemy_minions",
             "With exactly three opposing minions, no minion changes control.",
             below_threshold_case,
             lambda x: x == {"enemy_controls": 3, "friendly_controls": 0, "tech_zone": "PLAY"},
             "Existing test_classic.py::test_mind_control_tech provides prior mechanism coverage; this isolates the below-threshold branch.")
    run_case("EX1_085", "steal_exactly_one_at_four_enemy_minions",
             "With exactly four opposing minions, one random minion is stolen and three remain with its owner.",
             threshold_case,
             lambda x: x["stolen"] == 1 and x["enemy_left"] == 3
             and x["friendly_field"].count("EX1_085") == 1
             and len(x["friendly_field"]) == 2 and len(x["enemy_field"]) == 3
             and x["tech_zone"] == "PLAY",
             "Random outcome is checked by owner/count, not by a fixed target identity.")
    def seeded_candidates_case():
        candidate_ids = (WISP, "CS1_042", "CS2_182", "EX1_007")
        outcomes = {}
        for seed in range(10):
            game = fresh_game()
            game.random.seed(seed)
            targets = [game.player2.summon(cid) for cid in candidate_ids]
            tech = game.player1.give("EX1_085")
            tech.play()
            outcomes[str(seed)] = [m.id for m in targets if m.controller is game.player1]
        return {"outcomes": outcomes,
                "candidates_reached": sorted({cid for ids in outcomes.values() for cid in ids})}

    run_case("EX1_085", "seeded_random_pool_reaches_each_candidate",
             "Across fixed RNG seeds 0-9, each of the four enemy minions is observed as the stolen target.",
             seeded_candidates_case,
             lambda x: x["candidates_reached"] == sorted((WISP, "CS1_042", "CS2_182", "EX1_007"))
             and all(len(v) == 1 for v in x["outcomes"].values()),
             "Fixed game.random seeds cover every candidate while preserving the exact-one steal count.")
    finish_card("EX1_085", "Battlecry|Random effects",
                "三只敌方随从时不触发；四只时随机夺取恰好一只。")


def probe_mountain_giant():
    def cost_updates_case():
        game = fresh_game()
        giant = game.player1.give("EX1_105")
        base = giant.cost
        first = game.player1.give(WISP)
        second = game.player1.give(MOONFIRE)
        with_two = giant.cost
        first.discard()
        with_one = giant.cost
        second.discard()
        restored = giant.cost
        return {"base": base, "with_two_other_cards": with_two,
                "with_one_other_card": with_one, "restored": restored,
                "giant_zone": giant.zone.name}

    run_case("EX1_105", "cost_tracks_other_hand_cards",
             "Base cost 12 falls by one for each other card in hand and updates when cards leave hand.",
             cost_updates_case,
             lambda x: x == {"base": 12, "with_two_other_cards": 10,
                             "with_one_other_card": 11, "restored": 12,
                             "giant_zone": "HAND"},
             "Existing test_classic.py::test_mountain_giant checks cost against total hand count; this asserts exact add/remove deltas with the Giant excluded.")
    finish_card("EX1_105", "Cost modification",
                "巨人费用对手牌中其余卡牌逐张减1，并随卡牌离手恢复。")


def probe_gelbin_mekkatorque():
    def invention_case():
        game = fresh_game()
        gelbin = game.player1.give("EX1_112")
        gelbin.play()
        inventions = [m.id for m in game.player1.field
                      if m.id in {"Mekka1", "Mekka2", "Mekka3", "Mekka4"}]
        return {"gelbin_zone": gelbin.zone.name, "inventions": inventions,
                "friendly_field_count": len(game.player1.field),
                "enemy_field_count": len(game.player2.field)}

    run_case("EX1_112", "battlecry_summons_one_allowed_random_invention",
             "Battlecry leaves Gelbin plus exactly one owned invention chosen from the four supported gadgets.",
             invention_case,
             lambda x: x["gelbin_zone"] == "PLAY" and len(x["inventions"]) == 1
             and x["friendly_field_count"] == 2 and x["enemy_field_count"] == 0,
             "Prior audit listed only generic-play smoke; validates live random entourage selection and summon ownership.")
    finish_card("EX1_112", "Battlecry|Random effects|Summon",
                "战吼从四种发明中随机召唤恰好一个到己方场上。",
                unresolved="随机分支只观察到本次选中的发明；四种发明各自的延迟效果未在本探针中覆盖。")


def probe_leeroy_jenkins():
    def charge_and_whelps_case():
        game = fresh_game()
        leeroy = game.player1.give("EX1_116")
        leeroy.play()
        whelps = [m for m in game.player2.field if m.id == "EX1_116t"]
        ready = {"charge": leeroy.charge, "can_attack": leeroy.can_attack(),
                 "attack": leeroy.atk}
        leeroy.attack(game.player2.hero)
        return {"ready": ready, "enemy_hero_after_attack": game.player2.hero.health,
                "opponent_whelps": [(m.id, m.atk, m.health, m.controller is game.player2)
                                    for m in whelps],
                "leeroy_zone": leeroy.zone.name}

    run_case("EX1_116", "charge_attack_and_two_opponent_whelps",
             "Leeroy has Charge and can attack immediately; battlecry gives the opponent exactly two owned 1/1 Whelps.",
             charge_and_whelps_case,
             lambda x: x["ready"] == {"charge": True, "can_attack": True, "attack": 6}
             and x["enemy_hero_after_attack"] == 24
             and x["opponent_whelps"] == [("EX1_116t", 1, 1, True), ("EX1_116t", 1, 1, True)]
             and x["leeroy_zone"] == "PLAY",
             "Independent live-play check of Charge, attack damage, token count, stats, and controller.")
    finish_card("EX1_116", "Battlecry|Charge|Summon",
                "勒罗伊具有冲锋并可立即攻击；战吼给对手召唤两只1/1龙蛋。")


def probe_conceal():
    def stealth_lifetime_case():
        game = fresh_game()
        normal = game.player1.summon(WISP)
        natural_stealth = game.player1.summon("EX1_010")
        before = (normal.stealthed, natural_stealth.stealthed)
        game.player1.give("EX1_128").play()
        during = (normal.stealthed, natural_stealth.stealthed)
        game.end_turn()
        game.end_turn()
        after_owner_turn = (normal.stealthed, natural_stealth.stealthed)
        return {"before": before, "during": during, "after_owner_turn": after_owner_turn,
                "normal_zone": normal.zone.name, "natural_zone": natural_stealth.zone.name}

    run_case("EX1_128", "friendly_minions_stealth_expires_next_turn",
             "Conceal grants Stealth to friendly minions and removes that temporary Stealth at the owner's next turn; naturally Stealthed minion remains Stealthed.",
             stealth_lifetime_case,
             lambda x: x == {"before": (False, True), "during": (True, True),
                             "after_owner_turn": (False, True),
                             "normal_zone": "PLAY", "natural_zone": "PLAY"},
             "Existing tests/test_classic.py::test_conceal covers ordinary expiration; this separates temporary and native Stealth.")
    finish_card("EX1_128", "Spell resolution",
                "友方随从获得潜行直到己方下回合；其自身潜行不被该临时效果移除。")


def probe_naturalize():
    def destroy_and_draw_case():
        game = fresh_game(CardClass.DRUID, CardClass.DRUID)
        game.player2.discard_hand()
        seed_deck(game.player2, WISP, 2)
        target = game.player2.summon("CS2_182")
        drawn_before = (game.player1.cards_drawn_this_turn, game.player2.cards_drawn_this_turn)
        spell = game.player1.give("EX1_161")
        spell.play(target=target)
        drawn_after = (game.player1.cards_drawn_this_turn, game.player2.cards_drawn_this_turn)
        return {"target_zone": target.zone.name, "opponent_hand": [c.id for c in game.player2.hand],
                "opponent_deck": len(game.player2.deck), "draw_counters_before": drawn_before,
                "draw_counters_after": drawn_after, "spell_zone": spell.zone.name}

    run_case("EX1_161", "destroy_target_and_opponent_draws_two",
             "Naturalize destroys the selected minion and makes the opponent draw exactly two cards, with both draw counters assigned to that opponent.",
             destroy_and_draw_case,
             lambda x: x["target_zone"] == "GRAVEYARD"
             and x["opponent_hand"] == [WISP, WISP] and x["opponent_deck"] == 0
             and x["draw_counters_after"][0] == x["draw_counters_before"][0]
             and x["draw_counters_after"][1] == x["draw_counters_before"][1] + 2
             and x["spell_zone"] == "GRAVEYARD",
             "Checks cross-player draw ownership as well as target death and physical draw destinations; investigate counter mismatch as a confirmed runtime issue.")
    finish_card("EX1_161", "Draw / Discard|Spell resolution|Targeting",
                "目标随从被摧毁入墓；对手实际抽两张并由对手计入本回合抽牌。")


def probe_azure_drake():
    def spellpower_and_draw_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        seed_deck(game.player1, WISP)
        drake = game.player1.give("EX1_284")
        drake.play()
        after_battlecry = {"hand_ids": [c.id for c in game.player1.hand],
                           "deck_size": len(game.player1.deck),
                           "spellpower": game.player1.spellpower}
        game.player1.give(MOONFIRE).play(target=game.player2.hero)
        return {"after_battlecry": after_battlecry,
                "enemy_hero_health": game.player2.hero.health,
                "drake_zone": drake.zone.name}

    run_case("EX1_284", "battlecry_draw_and_spell_damage_aura",
             "Azure Drake draws one physical card and grants Spell Damage +1; Moonfire then deals 2 instead of 1.",
             spellpower_and_draw_case,
             lambda x: x["after_battlecry"] == {"hand_ids": [WISP], "deck_size": 0,
                                                 "spellpower": 1}
             and x["enemy_hero_health"] == 28 and x["drake_zone"] == "PLAY",
             "Existing generic card tests do not combine this exact Battlecry draw with its Spell Damage effect; this probe checks both in one board state.")
    finish_card("EX1_284", "Battlecry|Draw / Discard|Spell Damage",
                "战吼抽到一张实体牌；龙在场时法术伤害增加1。")


def probe_ice_block():
    def nonfatal_then_fatal_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        secret = game.player1.give("EX1_295")
        secret.play()
        game.player1.hero.damage = 28
        game.end_turn()
        game.player2.give(MOONFIRE).play(target=game.player1.hero)
        nonfatal = {"health": game.player1.hero.health,
                    "secret_zone": secret.zone.name,
                    "secret_active": secret in game.player1.secrets}
        game.player2.give("CS2_029").play(target=game.player1.hero)
        fatal_prevented = {"health": game.player1.hero.health,
                           "immune": game.player1.hero.immune,
                           "secret_zone": secret.zone.name,
                           "secret_active": secret in game.player1.secrets}
        return {"nonfatal": nonfatal, "fatal_prevented": fatal_prevented}

    run_case("EX1_295", "secret_waits_for_fatal_damage_then_prevents_it",
             "Nonfatal damage leaves Ice Block armed; later lethal Fireball leaves the hero at 1, grants Immune, and consumes the secret.",
             nonfatal_then_fatal_case,
             lambda x: x["nonfatal"] == {"health": 1, "secret_zone": "SECRET",
                                          "secret_active": True}
             and x["fatal_prevented"] == {"health": 1, "immune": True,
                                          "secret_zone": "GRAVEYARD", "secret_active": False},
             "Uses two distinct opposing spell events to distinguish the lethal predicate from ordinary damage.")
    finish_card("EX1_295", "Secret|Spell resolution|Trigger",
                "冰箱不响应非致命伤害；致命伤害被阻止，英雄剩1血并在本回合获得免疫。")


def probe_ragnaros():
    def end_turn_case():
        game = fresh_game()
        rag = game.player1.give("EX1_298")
        rag.play()
        before = game.player2.hero.health
        attack_allowed = rag.can_attack()
        game.end_turn()
        return {"can_attack": attack_allowed, "enemy_hero_before": before,
                "enemy_hero_after": game.player2.hero.health,
                "rag_zone": rag.zone.name}

    run_case("EX1_298", "cannot_attack_and_hits_only_enemy_at_end_turn",
             "Ragnaros cannot attack; with only the enemy hero as a legal enemy, its end-of-turn trigger deals 8 damage.",
             end_turn_case,
             lambda x: x == {"can_attack": False, "enemy_hero_before": 30,
                             "enemy_hero_after": 22, "rag_zone": "PLAY"},
             "Constrains the random enemy-character pool to one candidate so this is a deterministic trigger assertion.")
    finish_card("EX1_298", "Random effects|Trigger",
                "不能攻击；回合结束对唯一合法敌方角色造成8点伤害。")


def probe_doomguard():
    def discard_two_and_charge_case():
        game = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
        game.player1.discard_hand()
        hand_ids = (WISP, MOONFIRE, "CS2_029")
        candidates = [game.player1.give(cid) for cid in hand_ids]
        doomguard = game.player1.give("EX1_310")
        doomguard.play()
        discarded = [card.id for card in candidates if card.zone.name == "REMOVEDFROMGAME"]
        remaining = [card.id for card in game.player1.hand]
        charge = doomguard.charge
        can_attack = doomguard.can_attack()
        doomguard.attack(game.player2.hero)
        return {"discarded": discarded, "remaining": remaining,
                "charge": charge, "can_attack_before": can_attack,
                "enemy_hero_after_attack": game.player2.hero.health,
                "doomguard_zone": doomguard.zone.name}

    run_case("EX1_310", "battlecry_discards_two_random_and_charge_attacks",
             "Doomguard discards exactly two of three other hand cards, retains one, has Charge, and can attack immediately for 5.",
             discard_two_and_charge_case,
             lambda x: len(x["discarded"]) == 2 and set(x["discarded"]).issubset({WISP, MOONFIRE, "CS2_029"})
             and len(x["remaining"]) == 1 and x["remaining"][0] in {WISP, MOONFIRE, "CS2_029"}
             and x["charge"] and x["can_attack_before"]
             and x["enemy_hero_after_attack"] == 25 and x["doomguard_zone"] == "PLAY",
             "Random discard assertions are based on counts/set membership; no fixed discarded identity is assumed.")
    finish_card("EX1_310", "Battlecry|Charge|Draw / Discard|Random effects",
                "战吼随机弃掉两张其他手牌并保留第三张；具有冲锋且可立即造成5点攻击伤害。")


def probe_power_overwhelming():
    def buff_then_death_case():
        game = fresh_game(CardClass.WARLOCK, CardClass.WARLOCK)
        target = game.player1.summon(WISP)
        spell = game.player1.give("EX1_316")
        spell.play(target=target)
        buffed = {"attack": target.atk, "health": target.health,
                  "max_health": target.max_health, "zone": target.zone.name}
        game.end_turn()
        return {"buffed": buffed, "after_turn_end_zone": target.zone.name,
                "dead": target.dead, "spell_zone": spell.zone.name}

    run_case("EX1_316", "friendly_minion_gets_4_4_then_dies_at_turn_end",
             "Power Overwhelming gives a friendly minion +4/+4 through the turn, then destroys it at turn end.",
             buff_then_death_case,
             lambda x: x["buffed"] == {"attack": 5, "health": 5,
                                       "max_health": 5, "zone": "PLAY"}
             and x["after_turn_end_zone"] == "GRAVEYARD" and x["dead"]
             and x["spell_zone"] == "GRAVEYARD",
             "Checks immediate stats, delayed death trigger, and both card zones.")
    finish_card("EX1_316", "Spell resolution|Targeting",
                "友方随从本回合获得+4/+4；回合结束后被摧毁。")


def probe_divine_favor():
    def catch_up_case():
        game = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
        game.player1.discard_hand()
        game.player2.discard_hand()
        seed_deck(game.player1, WISP, 5)
        for _ in range(3):
            game.player2.give(WISP)
        favor = game.player1.give("EX1_349")
        favor.play()
        return {"friendly_hand": [c.id for c in game.player1.hand],
                "enemy_hand_count": len(game.player2.hand),
                "friendly_deck_count": len(game.player1.deck),
                "favor_zone": favor.zone.name}

    def already_ahead_case():
        game = fresh_game(CardClass.PALADIN, CardClass.PALADIN)
        game.player1.discard_hand()
        game.player2.discard_hand()
        seed_deck(game.player1, WISP, 2)
        for _ in range(3):
            game.player1.give(WISP)
        game.player2.give(WISP)
        favor = game.player1.give("EX1_349")
        favor.play()
        return {"friendly_hand_count": len(game.player1.hand),
                "enemy_hand_count": len(game.player2.hand),
                "friendly_deck_count": len(game.player1.deck),
                "favor_zone": favor.zone.name}

    run_case("EX1_349", "draw_until_matching_larger_opponent_hand",
             "When behind, Divine Favor draws exactly enough cards for hand sizes to match.",
             catch_up_case,
             lambda x: len(x["friendly_hand"]) == x["enemy_hand_count"] == 3
             and x["friendly_hand"] == [WISP] * 3
             and x["friendly_deck_count"] == 2 and x["favor_zone"] == "GRAVEYARD",
             "Uses five known deck cards and three known enemy hand cards; verifies stopping at the target count.")
    run_case("EX1_349", "no_draw_when_already_ahead",
             "When Divine Favor resolves with more cards in hand than the opponent, it draws none.",
             already_ahead_case,
             lambda x: x == {"friendly_hand_count": 3, "enemy_hand_count": 1,
                             "friendly_deck_count": 2, "favor_zone": "GRAVEYARD"},
             "Covers the opposite hand-size branch without relying on fatigue behavior.")
    finish_card("EX1_349", "Draw / Discard|Spell resolution",
                "手牌少于对手时抽至数量相等；手牌已多于对手时不抽。")


def probe_prophet_velen():
    def double_spell_and_power_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        game.player1.hero.damage = 15
        velen = game.player1.give("EX1_350")
        velen.play()
        game.player1.used_mana = 0
        spell = game.player1.give("EX1_624")
        spell.play(target=game.player2.hero)
        spell_effect = {"enemy_hero_health": game.player2.hero.health,
                        "friendly_hero_health": game.player1.hero.health,
                        "spellpower_double": game.player1.spellpower_double,
                        "healing_double": game.player1.healing_double}
        game.player1.hero.damage = 10
        game.player1.used_mana = 0
        game.player1.hero.power.use(target=game.player1.hero)
        return {"spell_effect": spell_effect,
                "after_doubled_hero_power_heal": game.player1.hero.health,
                "velen_zone": velen.zone.name}

    run_case("EX1_350", "double_spell_damage_spell_healing_and_hero_power_healing",
             "Prophet Velen doubles Holy Fire's 5 damage and 5 healing, and doubles Priest Hero Power healing from 2 to 4.",
             double_spell_and_power_case,
             lambda x: x["spell_effect"] == {"enemy_hero_health": 20,
                                            "friendly_hero_health": 25,
                                            "spellpower_double": 1,
                                            "healing_double": 1}
             and x["after_doubled_hero_power_heal"] == 24
             and x["velen_zone"] == "PLAY",
             "Covers both spell damage and healing, plus a Hero Power, in a real Priest game.")
    finish_card("EX1_350", "Continuous effect / Update",
                "在场时法术伤害/治疗与英雄技能治疗均翻倍。")


def probe_auchenai_soulpriest():
    def power_and_spell_become_damage_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        soulpriest = game.player1.give("EX1_591")
        soulpriest.play()
        target = game.player1.summon("CS1_042")
        game.player1.hero.power.use(target=target)
        power_result = {"minion_zone": target.zone.name, "minion_dead": target.dead}
        game.player1.used_mana = 0
        game.player1.give(HOLY_LIGHT).play(target=game.player1.hero)
        return {"power_result": power_result,
                "hero_health_after_holy_light": game.player1.hero.health,
                "soulpriest_zone": soulpriest.zone.name,
                "healing_as_damage": game.player1.healing_as_damage}

    run_case("EX1_591", "hero_power_and_healing_spell_deal_damage",
             "With Auchenai active, Lesser Heal deals 2 to a friendly 1/2 minion and kills it; Holy Light targeting own hero deals 6 damage instead of healing.",
             power_and_spell_become_damage_case,
             lambda x: x["power_result"] == {"minion_zone": "GRAVEYARD", "minion_dead": True}
             and x["hero_health_after_holy_light"] == 24
             and x["soulpriest_zone"] == "PLAY" and x["healing_as_damage"],
             "Exercises both a Hero Power and a healing card, with the original friendly targets retained as damage targets.")
    finish_card("EX1_591", "Continuous effect / Update",
                "己方英雄技能和治疗法术都改为对原目标造成对应伤害。")


def probe_molten_giant():
    def cost_tracks_real_damage_case():
        game = fresh_game()
        giant = game.player1.give("EX1_620")
        base = giant.cost
        game.end_turn()
        for _ in range(5):
            game.player2.give(MOONFIRE).play(target=game.player1.hero)
        at_five_damage = {"hero_health": game.player1.hero.health, "cost": giant.cost}
        for _ in range(3):
            game.player2.give(MOONFIRE).play(target=game.player1.hero)
        at_eight_damage = {"hero_health": game.player1.hero.health, "cost": giant.cost}
        return {"base_cost": base, "at_five_damage": at_five_damage,
                "at_eight_damage": at_eight_damage, "giant_zone": giant.zone.name}

    run_case("EX1_620", "cost_decreases_with_hero_damage",
             "Molten Giant's cost is 20 at full health, 15 after 5 actual damage, and 12 after 8 actual damage.",
             cost_tracks_real_damage_case,
             lambda x: x == {"base_cost": 20,
                             "at_five_damage": {"hero_health": 25, "cost": 15},
                             "at_eight_damage": {"hero_health": 22, "cost": 12},
                             "giant_zone": "HAND"},
             "Damage is produced by eight real opposing Moonfire plays; validates incremental cost updates in the same game.")
    finish_card("EX1_620", "Cost modification",
                "巨人的费用随英雄实际承受伤害逐点降低。")


def probe_holy_fire():
    def damage_and_heal_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        game.player1.hero.damage = 5
        spell = game.player1.give("EX1_624")
        spell.play(target=game.player2.hero)
        return {"enemy_health_before": 30, "enemy_health_after": game.player2.hero.health,
                "friendly_health_before": 25, "friendly_health_after": game.player1.hero.health,
                "spell_zone": spell.zone.name}

    run_case("EX1_624", "deal_five_to_target_and_restore_five_to_friendly_hero",
             "Holy Fire deals 5 to the selected enemy hero and restores exactly 5 to its controller's damaged hero.",
             damage_and_heal_case,
             lambda x: x == {"enemy_health_before": 30, "enemy_health_after": 25,
                             "friendly_health_before": 25, "friendly_health_after": 30,
                             "spell_zone": "GRAVEYARD"},
             "Direct card execution covers both the targeted damage leg and the fixed friendly-hero heal.")
    finish_card("EX1_624", "Spell resolution|Targeting",
                "指定敌方英雄受到5伤；己方受伤英雄恢复5血。")


def probe_shadowform():
    def first_and_second_form_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        original_power = game.player1.hero.power.id
        game.player1.give("EX1_625").play()
        first_power = game.player1.hero.power.id
        game.player1.hero.power.use(target=game.player2.hero)
        first_damage = 30 - game.player2.hero.health
        game.end_turn()
        game.end_turn()
        game.player1.used_mana = 0
        second = game.player1.give("EX1_625")
        second.play()
        second_power = game.player1.hero.power.id
        game.player1.hero.power.use(target=game.player2.hero)
        total_damage = 30 - game.player2.hero.health
        return {"original_power": original_power, "first_power": first_power,
                "first_damage": first_damage, "second_power": second_power,
                "cumulative_enemy_damage": total_damage,
                "shadowform_active": game.player1.shadowform}

    run_case("EX1_625", "hero_power_upgrades_from_two_to_three_damage",
             "First Shadowform changes Lesser Heal to Mind Spike for 2 damage; second changes it to Mind Shatter for 3 damage.",
             first_and_second_form_case,
             lambda x: x == {"original_power": "HERO_09bp", "first_power": "EX1_625t",
                             "first_damage": 2, "second_power": "EX1_625t2",
                             "cumulative_enemy_damage": 5,
                             "shadowform_active": True},
             "Tests the initial form and already-in-Shadowform upgrade on separate turns, including actual power activation.")
    finish_card("EX1_625", "Spell resolution|Summon",
                "第一次变为2伤害英雄技能；第二次升级到3伤害英雄技能。")


def probe_gloom_stag():
    def only_odd_case():
        game = fresh_game(CardClass.DRUID, CardClass.DRUID)
        seed_deck(game.player1, "EX1_507")
        stag = game.player1.give("GIL_130")
        before = (stag.atk, stag.health)
        stag.play()
        return {"before": before, "after": (stag.atk, stag.health),
                "taunt": stag.taunt, "deck_costs": [c.cost for c in game.player1.deck]}

    def mixed_deck_case():
        game = fresh_game(CardClass.DRUID, CardClass.DRUID)
        seed_deck(game.player1, "EX1_507")
        seed_deck(game.player1, WISP)
        stag = game.player1.give("GIL_130")
        before = (stag.atk, stag.health)
        stag.play()
        return {"before": before, "after": (stag.atk, stag.health),
                "taunt": stag.taunt, "deck_costs": sorted(c.cost for c in game.player1.deck)}

    run_case("GIL_130", "only_odd_deck_adds_two_two",
             "An all-odd deck activates Battlecry and adds +2/+2 while Taunt is present.",
             only_odd_case,
             lambda x: x["after"] == (x["before"][0] + 2, x["before"][1] + 2)
             and x["taunt"] and all(cost % 2 == 1 for cost in x["deck_costs"]),
             "Uses one 3-cost starting deck card; checks the powered-up branch and unconditional Taunt.")
    run_case("GIL_130", "mixed_deck_keeps_base_stats",
             "Adding one even-cost deck card disables the +2/+2 Battlecry; Taunt remains.",
             mixed_deck_case,
             lambda x: x["after"] == x["before"] and x["taunt"]
             and any(cost % 2 == 0 for cost in x["deck_costs"]),
             "Covers the condition-false branch with an otherwise identical board and one even-cost card.")
    finish_card("GIL_130", "Battlecry|Taunt",
                "纯奇数费用牌库时获得+2/+2；混入偶数费用牌后无增益；嘲讽始终存在。")


def probe_murkspark_eel():
    def even_deck_case():
        game = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
        seed_deck(game.player1, WISP)
        eel = game.player1.give("GIL_530")
        requires_target = eel.requires_target()
        eel.play(target=game.player2.hero)
        return {"requires_target": requires_target,
                "enemy_health": game.player2.hero.health,
                "deck_costs": [c.cost for c in game.player1.deck]}

    def mixed_deck_case():
        game = fresh_game(CardClass.SHAMAN, CardClass.SHAMAN)
        seed_deck(game.player1, WISP)
        seed_deck(game.player1, "EX1_507")
        eel = game.player1.give("GIL_530")
        requires_target = eel.requires_target()
        eel.play()
        return {"requires_target": requires_target,
                "enemy_health": game.player2.hero.health,
                "deck_costs": sorted(c.cost for c in game.player1.deck)}

    run_case("GIL_530", "all_even_deck_requires_target_and_deals_two",
             "An all-even deck powers up Murkspark Eel, requires a target, and deals 2 to it.",
             even_deck_case,
             lambda x: x["requires_target"] and x["enemy_health"] == 28
             and all(cost % 2 == 0 for cost in x["deck_costs"]),
             "Uses a real 0-cost card in the deck; tests target requirement together with the powered effect.")
    run_case("GIL_530", "mixed_deck_has_no_target_and_no_damage",
             "A mixed even/odd deck disables the Battlecry: no target is required and the enemy hero takes no damage.",
             mixed_deck_case,
             lambda x: not x["requires_target"] and x["enemy_health"] == 30
             and any(cost % 2 == 0 for cost in x["deck_costs"])
             and any(cost % 2 == 1 for cost in x["deck_costs"]),
             "Covers the conditional-false branch; matches the existing test_murkspark_eel empty/random-deck prerequisite observations.")
    finish_card("GIL_530", "Battlecry|Targeting",
                "纯偶数费用牌库时必须指定目标并造成2伤；混合牌库时无战吼效果且不需目标。")


def probe_genn_greymane():
    def starting_power_cost_case():
        even_deck = [WISP] * 29 + ["GIL_692"]
        mixed_deck = [WISP] * 28 + ["EX1_507", "GIL_692"]
        game, even_player, mixed_player = starting_deck_game(even_deck, mixed_deck)
        return {"even_costs": [Card(cid).cost for cid in even_deck],
                "mixed_costs": [Card(cid).cost for cid in mixed_deck],
                "even_power_cost": even_player.hero.power.cost,
                "mixed_power_cost": mixed_player.hero.power.cost,
                "even_genn_zone": next((c.zone.name for c in even_player.deck if c.id == "GIL_692"), "not_in_deck")}

    run_case("GIL_692", "start_of_game_reduces_only_even_deck_power_cost",
             "At game start, the hero power of an all-even deck costs 1; a deck containing a 3-cost card keeps base cost 2.",
             starting_power_cost_case,
             lambda x: all(c % 2 == 0 for c in x["even_costs"])
             and any(c % 2 == 1 for c in x["mixed_costs"])
             and x["even_power_cost"] == 1 and x["mixed_power_cost"] == 2,
             "Uses two live starting decks containing Genn and distinguishes an all-even list from one odd-card list.")
    finish_card("GIL_692", "Trigger",
                "开局仅在起始牌库全部为偶数费用时将英雄技能费用设为1。")


def probe_baku():
    def starting_upgrade_case():
        odd_deck = ["EX1_507"] * 29 + ["GIL_826"]
        mixed_deck = ["EX1_507"] * 28 + [WISP, "GIL_826"]
        game, odd_player, mixed_player = starting_deck_game(odd_deck, mixed_deck)
        return {"odd_deck_costs": [Card(cid).cost for cid in odd_deck],
                "mixed_deck_costs": [Card(cid).cost for cid in mixed_deck],
                "odd_power": odd_player.hero.power.id,
                "mixed_power": mixed_player.hero.power.id}

    run_case("GIL_826", "start_of_game_upgrades_only_odd_deck_power",
             "Baku upgrades the base Warrior Hero Power for an all-odd starting deck, but not when one 0-cost card is present.",
             starting_upgrade_case,
             lambda x: all(cost % 2 == 1 for cost in x["odd_deck_costs"])
             and any(cost % 2 == 0 for cost in x["mixed_deck_costs"])
             and x["odd_power"] == "HERO_01bp2"
             and x["mixed_power"] == "HERO_01bp",
             "Uses full starting-deck fixtures and checks the actual upgraded power ID at game start.")
    finish_card("GIL_826", "Trigger",
                "开局仅在起始牌库全部为奇数费用时升级英雄技能。")


def probe_glitter_moth():
    def odd_deck_double_health_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        seed_deck(game.player1, "EX1_507")
        minions = [game.player1.summon("CS1_042"), game.player1.summon(WISP)]
        before = [(m.atk, m.health, m.max_health) for m in minions]
        moth = game.player1.give("GIL_837")
        moth.play()
        after = [(m.atk, m.health, m.max_health) for m in minions]
        return {"before": before, "after": after,
                "moth_stats": (moth.atk, moth.health),
                "deck_costs": [c.cost for c in game.player1.deck]}

    def mixed_deck_no_buff_case():
        game = fresh_game(CardClass.PRIEST, CardClass.PRIEST)
        seed_deck(game.player1, "EX1_507")
        seed_deck(game.player1, WISP)
        minion = game.player1.summon("CS1_042")
        before = (minion.health, minion.max_health)
        game.player1.give("GIL_837").play()
        return {"before": before, "after": (minion.health, minion.max_health),
                "deck_costs": sorted(c.cost for c in game.player1.deck)}

    run_case("GIL_837", "odd_deck_doubles_other_minions_health",
             "With only odd-cost deck cards, Battlecry doubles current and maximum Health of every other friendly minion without changing Attack.",
             odd_deck_double_health_case,
             lambda x: x["after"] == [(atk, health * 2, max_health * 2)
                                      for atk, health, max_health in x["before"]]
             and all(c % 2 == 1 for c in x["deck_costs"]),
             "Checks two different minion health values and confirms Glitter Moth itself is excluded from its buff.")
    run_case("GIL_837", "mixed_deck_leaves_minion_health_unchanged",
             "Adding an even-cost card disables the Battlecry and leaves the other minion's Health unchanged.",
             mixed_deck_no_buff_case,
             lambda x: x["before"] == x["after"]
             and any(c % 2 == 0 for c in x["deck_costs"]),
             "Covers the condition-false case using an otherwise matching test state.")
    finish_card("GIL_837", "Battlecry",
                "纯奇数牌库时翻倍其他友方随从生命；混合牌库时不变。")


def probe_black_cat():
    def odd_deck_draw_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        seed_deck(game.player1, "EX1_507")
        cat = game.player1.give("GIL_838")
        cat.play()
        return {"hand_ids": [c.id for c in game.player1.hand],
                "deck_size": len(game.player1.deck), "spellpower": game.player1.spellpower,
                "cat_zone": cat.zone.name,
                "deck_costs": [c.cost for c in game.player1.deck]}

    def mixed_deck_no_draw_case():
        game = fresh_game(CardClass.MAGE, CardClass.MAGE)
        seed_deck(game.player1, "EX1_507")
        seed_deck(game.player1, WISP)
        cat = game.player1.give("GIL_838")
        cat.play()
        return {"hand_ids": [c.id for c in game.player1.hand],
                "deck_size": len(game.player1.deck), "spellpower": game.player1.spellpower,
                "cat_zone": cat.zone.name,
                "deck_costs": sorted(c.cost for c in game.player1.deck)}

    run_case("GIL_838", "odd_deck_draws_and_spell_damage_always_applies",
             "With an all-odd deck, Black Cat draws one card and grants Spell Damage +1.",
             odd_deck_draw_case,
             lambda x: x["hand_ids"] == ["EX1_507"] and x["deck_size"] == 0
             and x["spellpower"] == 1 and x["cat_zone"] == "PLAY"
             and all(c % 2 == 1 for c in x["deck_costs"]),
             "One known odd-cost Pirate card is drawn; tests its Battlecry and static Spell Damage.")
    run_case("GIL_838", "mixed_deck_skips_draw_but_keeps_spell_damage",
             "With a mixed deck, Battlecry draws nothing while Spell Damage +1 remains active.",
             mixed_deck_no_draw_case,
             lambda x: x["hand_ids"] == [] and x["deck_size"] == 2
             and x["spellpower"] == 1 and x["cat_zone"] == "PLAY"
             and any(c % 2 == 0 for c in x["deck_costs"])
             and any(c % 2 == 1 for c in x["deck_costs"]),
             "Separates conditional draw from unconditional Spell Damage using one mixed deck.")
    finish_card("GIL_838", "Battlecry|Draw / Discard|Spell Damage",
                "纯奇数牌库时战吼抽牌；混合牌库时不抽；法术伤害+1始终有效。")


def probe_vanish():
    def both_owners_return_case():
        game = fresh_game(CardClass.ROGUE, CardClass.ROGUE)
        friendly = game.player1.summon(WISP)
        enemy = game.player2.summon("CS1_042")
        spell = game.player1.give("NEW1_004")
        spell.play()
        return {"friendly_zone": friendly.zone.name,
                "enemy_zone": enemy.zone.name,
                "friendly_in_owner_hand": friendly in game.player1.hand,
                "enemy_in_owner_hand": enemy in game.player2.hand,
                "friendly_controls": friendly.controller is game.player1,
                "enemy_controls": enemy.controller is game.player2,
                "friendly_field": len(game.player1.field),
                "enemy_field": len(game.player2.field),
                "spell_zone": spell.zone.name}

    run_case("NEW1_004", "return_every_minion_to_its_owner_hand",
             "Vanish bounces both friendly and enemy minions to their respective owners' hands and clears both boards.",
             both_owners_return_case,
             lambda x: x == {"friendly_zone": "HAND", "enemy_zone": "HAND",
                             "friendly_in_owner_hand": True, "enemy_in_owner_hand": True,
                             "friendly_controls": True, "enemy_controls": True,
                             "friendly_field": 0, "enemy_field": 0,
                             "spell_zone": "GRAVEYARD"},
             "Checks both sides' physical hand zones and controller ownership after the global bounce.")
    finish_card("NEW1_004", "Spell resolution",
                "双方场上所有随从都回到各自拥有者的手牌；场面清空，法术入墓。")


def probe_captains_parrot():
    def seeded_pirate_pool_case():
        pirate_ids = ("NEW1_022", "CS2_146")
        outcomes = {}
        for seed in range(10):
            game = fresh_game()
            game.player1.discard_hand()
            candidates = [game.player1.give(cid) for cid in pirate_ids]
            non_pirate = game.player1.give(WISP)
            for card in candidates + [non_pirate]:
                card.shuffle_into_deck()
            game.random.seed(seed)
            parrot = game.player1.give("NEW1_016")
            parrot.play()
            outcomes[str(seed)] = [card.id for card in game.player1.hand]
            if len(game.player1.deck) != 2:
                outcomes[str(seed)].append(f"deck_size={len(game.player1.deck)}")
        return {"outcomes": outcomes,
                "pirates_reached": sorted({cid for values in outcomes.values()
                                            for cid in values if cid in pirate_ids}),
                "non_pirate_in_hand": any(WISP in values for values in outcomes.values())}

    def no_pirate_case():
        game = fresh_game()
        game.player1.discard_hand()
        seed_deck(game.player1, WISP)
        parrot = game.player1.give("NEW1_016")
        parrot.play()
        return {"hand_ids": [c.id for c in game.player1.hand],
                "deck_ids": [c.id for c in game.player1.deck],
                "parrot_zone": parrot.zone.name}

    run_case("NEW1_016", "seeded_draw_selects_only_pirates",
             "Across fixed seeds 0-9, each of two Pirates is selected from the deck; the non-Pirate Wisp is never drawn.",
             seeded_pirate_pool_case,
             lambda x: x["pirates_reached"] == sorted(("NEW1_022", "CS2_146"))
             and not x["non_pirate_in_hand"]
             and all(len(v) == 1 and not v[0].startswith("deck_size=")
                     for v in x["outcomes"].values()),
             "Uses fixed RNG seeds and two distinct Pirate candidates plus a non-Pirate decoy.")
    run_case("NEW1_016", "no_pirate_deck_draws_nothing",
             "With only a non-Pirate in the deck, Captain's Parrot draws nothing and leaves the deck card in place.",
             no_pirate_case,
             lambda x: x == {"hand_ids": [], "deck_ids": [WISP],
                             "parrot_zone": "PLAY"},
             "Covers the empty eligible-pool branch present in existing tests/test_classic.py::test_captains_parrot.")
    finish_card("NEW1_016", "Battlecry|Draw / Discard",
                "战吼从牌库随机抽取海盗；无海盗时不抽，非海盗牌留在牌库。")


def probe_elite_tauren_chieftain():
    chord_ids = {"PRO_001a", "PRO_001b", "PRO_001c"}

    def give_both_players_case():
        game = fresh_game()
        game.player1.discard_hand()
        game.player2.discard_hand()
        tauren = game.player1.give("PRO_001")
        tauren.play()
        return {"friendly_chords": [c.id for c in game.player1.hand],
                "enemy_chords": [c.id for c in game.player2.hand],
                "tauren_zone": tauren.zone.name,
                "friendly_chord_valid": len(game.player1.hand) == 1 and game.player1.hand[0].id in chord_ids,
                "enemy_chord_valid": len(game.player2.hand) == 1 and game.player2.hand[0].id in chord_ids}

    def seeded_all_chords_case():
        outcomes = {}
        for seed in range(12):
            game = fresh_game()
            game.player1.discard_hand()
            game.player2.discard_hand()
            game.random.seed(seed)
            tauren = game.player1.give("PRO_001")
            tauren.play()
            outcomes[str(seed)] = {"friendly": [c.id for c in game.player1.hand],
                                   "enemy": [c.id for c in game.player2.hand]}
        friendly_seen = {values["friendly"][0] for values in outcomes.values()
                         if len(values["friendly"]) == 1}
        enemy_seen = {values["enemy"][0] for values in outcomes.values()
                      if len(values["enemy"]) == 1}
        return {"outcomes": outcomes,
                "friendly_seen": sorted(friendly_seen),
                "enemy_seen": sorted(enemy_seen)}

    run_case("PRO_001", "battlecry_gives_both_players_one_power_chord",
             "ETC's Battlecry gives each player exactly one Power Chord from the three-card pool.",
             give_both_players_case,
             lambda x: x["friendly_chord_valid"] and x["enemy_chord_valid"]
             and x["tauren_zone"] == "PLAY",
             "Directly verifies recipient, count, and membership for both generated cards.")
    run_case("PRO_001", "seeded_random_pools_reach_all_three_chords_for_both_players",
             "Across fixed seeds 0-11, each player receives each of the three Power Chord options at least once.",
             seeded_all_chords_case,
             lambda x: x["friendly_seen"] == sorted(chord_ids)
             and x["enemy_seen"] == sorted(chord_ids)
             and all(len(v["friendly"]) == 1 and len(v["enemy"]) == 1
                     and v["friendly"][0] in chord_ids and v["enemy"][0] in chord_ids
                     for v in x["outcomes"].values()),
             "Fixed game RNG seeds cover all candidates separately for each player's random selection.")
    finish_card("PRO_001", "Battlecry|Random effects",
                "战吼让双方各获得一张力量和弦；固定种子覆盖三种可选牌。")


def main():
    if not PROBE_PATH.exists():
        _write_rows(PROBE_PATH, PROBE_FIELDS, [])
    if not VERDICT_PATH.exists():
        _write_rows(VERDICT_PATH, VERDICT_FIELDS, [])
    for probe in (probe_ice_lance, probe_northshire_cleric, probe_divine_spirit,
                  probe_mind_blast, probe_acolyte_of_pain,
                  probe_sylvanas_windrunner, probe_spellbreaker,
                  probe_old_murk_eye, probe_mind_control_tech,
                  probe_mountain_giant, probe_gelbin_mekkatorque,
                  probe_leeroy_jenkins, probe_conceal, probe_naturalize,
                  probe_azure_drake, probe_ice_block, probe_ragnaros,
                  probe_doomguard, probe_power_overwhelming,
                  probe_divine_favor, probe_prophet_velen,
                  probe_auchenai_soulpriest, probe_molten_giant,
                  probe_holy_fire, probe_shadowform, probe_gloom_stag,
                  probe_murkspark_eel, probe_genn_greymane, probe_baku,
                  probe_glitter_moth, probe_black_cat, probe_vanish,
                  probe_captains_parrot, probe_elite_tauren_chieftain):
        probe()
    baseline_rows = _read_rows(OUT / "expansion_yellow_baseline.csv", [])
    target_ids = {r["card_id"] for r in baseline_rows
                  if r["set"] == "Hall of Fame (HOF)" and r["status"] == "YELLOW"}
    verdict_rows = _read_rows(VERDICT_PATH, VERDICT_FIELDS)
    verdict_ids = {r["card_id"] for r in verdict_rows}
    probe_ids = {r["card_id"] for r in _read_rows(PROBE_PATH, PROBE_FIELDS)}
    missing = sorted(target_ids - verdict_ids)
    missing_probes = sorted(target_ids - probe_ids)
    unexpected = sorted(verdict_ids - target_ids)
    counts = {status: sum(r["status"] == status for r in verdict_rows)
              for status in ("GREEN", "RED", "YELLOW")}
    print(f"HOF yellow collectible inventory={len(target_ids)}; verdicts={len(verdict_ids)}; "
          f"probe-covered={len(probe_ids)}; statuses={counts}; "
          f"missing_verdicts={missing}; missing_probes={missing_probes}; unexpected={unexpected}")
    assert target_ids == verdict_ids and target_ids <= probe_ids, "HOF inventory coverage incomplete"


if __name__ == "__main__":
    main()
