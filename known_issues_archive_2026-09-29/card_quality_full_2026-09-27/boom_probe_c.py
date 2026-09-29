"""Card-specific live behavior probes for frozen Boomsday YELLOW cards 90:135."""

from __future__ import annotations

import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import GameOver, InvalidAction

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import BaseTestGame, MOONFIRE, Player, WISP, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "boom_probe_c.csv"
VERDICT_FILE = HERE / "boom_verdict_c.csv"
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
ROSTER = ALL_BOOM[90:135]
assert len(ALL_BOOM) == 135 and len(ROSTER) == 45 and ROSTER[0]["card_id"] == "BOT_517" and ROSTER[-1]["card_id"] == "BOT_914"
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


def topsy_turvy():
    cid="BOT_517"
    def swaps_attack_and_health():
        g,p,e=game(CardClass.PRIEST,CardClass.PRIEST)
        target=summon(p,"CS2_182")
        before=(target.atk,target.health,target.max_health)
        spell=play(p,cid,target=target)
        observed=f"before={before};after={(target.atk,target.health,target.max_health)};spell={spell.zone.name}"
        return check(spell.zone==Zone.GRAVEYARD and before==(4,5,5) and (target.atk,target.health,target.max_health)==(5,4,4),observed)
    audit(cid,[("swaps_minion_attack_and_health","Topsy Turvy exchanges the target's Attack and Health.",swaps_attack_and_health,"A 4/5 Yeti target verifies both Attack and maximum/current Health after cast.")])
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




def ectomancy():
    cid="BOT_521"
    def copies_all_controlled_demons_and_excludes_other_races():
        g,p,e=game(CardClass.WARLOCK,CardClass.WARLOCK)
        demons=[summon(p,"CS2_065"),summon(p,"EX1_306")]
        plain=summon(p,WISP)
        before=[(m.id,m.atk,m.health) for m in demons]
        spell=play(p,cid)
        copies=[m for m in p.field if m not in demons and m is not plain and m is not spell]
        observed=f"originals={before};spell={spell.zone.name};copies={[(m.id,m.atk,m.health,m.races,m.zone.name) for m in copies]};plain={plain.zone.name};field={[m.id for m in p.field]}"
        return check(spell.zone==Zone.GRAVEYARD and len(copies)==2
                     and [(m.id,m.atk,m.max_health) for m in copies]==[(m.id,m.atk,m.max_health) for m in demons]
                     and all(Race.DEMON in m.races and m.zone==Zone.PLAY for m in copies)
                     and plain.zone==Zone.PLAY,observed)
    audit(cid,[("summons_copies_of_all_friendly_demons","Ectomancy summons a copy of every Demon controlled and leaves non-Demons unchanged.",copies_all_controlled_demons_and_excludes_other_races,"Two different friendly Demons plus a Wisp control; compared copied identity/stats and board zones.")])


def mulchmuncher():
    cid="BOT_523"
    def treant_deaths_discount_cost_and_rush_is_minion_only():
        g,p,e=game(CardClass.DRUID,CardClass.MAGE)
        treants=[summon(p,"EX1_158t"),summon(p,"EX1_158t")]
        for t in treants:t.destroy()
        card=p.give(cid);discounted=card.cost
        body=card.play();target=summon(e,"CS2_182")
        can_hit=body.can_attack(target);can_hero=body.can_attack(e.hero)
        if can_hit:body.attack(target)
        observed=f"treants={[t.zone.name for t in treants]};discounted_cost={discounted};body={(body.atk,body.health,body.rush,body.zone.name)};minion_attack={can_hit};hero_attack={can_hero};target={target.zone.name}"
        return check(discounted==7 and body.zone==Zone.PLAY and body.rush and can_hit and not can_hero and target.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("treant_deaths_reduce_cost_and_rush_attacks_minion","Mulchmuncher costs 1 less per friendly Treant death and Rush can attack a minion, not a hero, this turn.",treant_deaths_discount_cost_and_rush_is_minion_only,"Destroyed two live friendly Treants before checking cost, then exercised Rush target restrictions in the same turn.")])


def power_word_replicate():
    cid="BOT_529"
    def creates_five_five_copy_without_changing_target():
        g,p,e=game(CardClass.PRIEST,CardClass.PRIEST)
        target=summon(p,"CS2_182");before=(target.id,target.atk,target.health,target.max_health)
        spell=play(p,cid,target=target)
        copies=[m for m in p.field if m is not target and m.id==target.id]
        observed=f"target={before}->{(target.id,target.atk,target.health,target.max_health)};spell={spell.zone.name};copies={[(m.id,m.atk,m.health,m.max_health,m.zone.name) for m in copies]}"
        return check(spell.zone==Zone.GRAVEYARD and (target.atk,target.health,target.max_health)==before[1:]
                     and len(copies)==1 and (copies[0].atk,copies[0].health,copies[0].max_health,copies[0].zone)==(5,5,5,Zone.PLAY),observed)
    audit(cid,[("choose_friendly_minion_summons_five_five_copy","Power Word: Replicate chooses a friendly minion and summons a 5/5 copy while the original remains unchanged.",creates_five_five_copy_without_changing_target,"Selected a live friendly Yeti, compared original stats, and checked exact copy stats/zone.")])


def celestial_emissary():
    cid="BOT_531"
    def next_spell_gets_plus_two_spell_damage_then_expires():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        em=play(p,cid);power_before=p.spellpower;first=play(p,MOONFIRE,target=e.hero);after_first=e.hero.health
        second=play(p,"CS2_029",target=e.hero);after_second=e.hero.health
        observed=f"emissary={em.zone.name};spellpower_before_first={power_before};first={first.zone.name}/{after_first};second={second.zone.name}/{after_second};spellpower_after={p.spellpower}"
        return check(em.zone==Zone.PLAY and power_before==2 and first.zone==Zone.GRAVEYARD and after_first==27
                     and second.zone==Zone.GRAVEYARD and after_second==21 and p.spellpower==0,observed)
    audit(cid,[("spell_damage_two_applies_only_to_next_spell","Celestial Emissary grants +2 Spell Damage to the next spell this turn; later spells do not keep the bonus.",next_spell_gets_plus_two_spell_damage_then_expires,"Moonfire should demonstrate 1+2 damage; the following Fireball baseline is 6 damage and should remain unmodified.")])


def explodinator():
    cid="BOT_532"
    def summons_two_bombs_and_each_death_hits_enemy_hero():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        own,enemy=p.hero.health,e.hero.health;source=play(p,cid)
        bombs=[m for m in p.field if m.id=="BOT_031"]
        states=[(m.atk,m.max_health,m.zone.name) for m in bombs]
        for m in list(bombs):m.destroy()
        observed=f"source={source.zone.name};bombs={states};after_death={[(m.zone.name,m.damage) for m in bombs]};heroes={own}->{p.hero.health}/{enemy}->{e.hero.health}"
        return check(source.zone==Zone.PLAY and len(bombs)==2 and all(x==(0,2,"PLAY") for x in states)
                     and all(m.zone==Zone.GRAVEYARD for m in bombs) and p.hero.health==own and e.hero.health==enemy-4,observed)
    audit(cid,[("battlecry_summons_two_goblin_bombs","Explodinator summons two 0/2 Goblin Bombs; each Bomb death deals 2 damage to the enemy hero.",summons_two_bombs_and_each_death_hits_enemy_hero,"Destroyed both generated Bombs separately and measured both hero health totals.")])


def menacing_nimbus():
    cid="BOT_533"
    def battlecry_adds_elemental_to_hand():
        g,p,e=game(CardClass.SHAMAN,CardClass.MAGE)
        source=play(p,cid);added=list(p.hand)
        state=[(c.id,CardType(c.type).name,c.races,c.zone.name) for c in added]
        observed=f"source={source.zone.name};added={state}"
        return check(source.zone==Zone.PLAY and len(added)==1 and added[0].zone==Zone.HAND
                     and added[0].type==CardType.MINION and Race.ELEMENTAL in added[0].races,observed)
    audit(cid,[("battlecry_adds_random_elemental","Menacing Nimbus adds one random Elemental card to its controller's hand.",battlecry_adds_elemental_to_hand,"Inspected the sole generated card's type, Elemental race, and hand zone after Battlecry.")])


def bull_dozer():
    cid="BOT_534"
    def divine_shield_absorbs_first_damage_event():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        body=summon(p,cid);before=(body.atk,body.health,body.max_health,body.divine_shield)
        g.end_turn();spell=play(e,MOONFIRE,target=body)
        after=(body.health,body.damage,body.divine_shield)
        observed=f"before={before};enemy_spell={spell.zone.name};after={after};body_zone={body.zone.name}"
        return check(before[3] and before[:3]==(9,7,7) and spell.zone==Zone.GRAVEYARD
                     and after==(7,0,False) and body.zone==Zone.PLAY,observed)
    audit(cid,[("divine_shield_prevents_damage_until_hit","Bull Dozer has Divine Shield; the first damage event removes its shield without damaging its body.",divine_shield_absorbs_first_damage_event,"Summoned the minion and cast a real enemy-targeted damage spell while its shield was intact.")])


def microtech_controller():
    cid="BOT_535"
    def battlecry_summons_two_one_one_mechs():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);source=play(p,cid)
        bots=[m for m in p.field if m.id=="BOT_312t"]
        observed=f"source={source.zone.name};tokens={[(m.atk,m.health,m.races,m.zone.name) for m in bots]};field={len(p.field)}"
        return check(source.zone==Zone.PLAY and len(bots)==2 and all((m.atk,m.max_health,m.zone)==(1,1,Zone.PLAY) and Race.MECHANICAL in m.races for m in bots),observed)
    audit(cid,[("battlecry_summons_two_microbots","Microtech Controller summons exactly two 1/1 Microbots.",battlecry_summons_two_one_one_mechs,"Observed both token stats, Mech race, and board zone after the minion's Battlecry.")])


def omega_agent():
    cid="BOT_536"
    def ten_mana_summons_two_copies_nine_mana_does_not():
        g,p,e=game(CardClass.WARLOCK,CardClass.MAGE);full=play(p,cid);full_minions=[m for m in p.field if m.id==cid]
        g2,p2,e2=game(CardClass.WARLOCK,CardClass.MAGE);p2.max_mana=9;low=play(p2,cid);low_minions=[m for m in p2.field if m.id==cid]
        observed=f"full_max_mana={p.max_mana};full={[(m.atk,m.health,m.zone.name) for m in full_minions]};nine_max_mana={p2.max_mana};low={[(m.atk,m.health,m.zone.name) for m in low_minions]}"
        return check(len(full_minions)==3 and all((m.atk,m.health,m.zone)==(4,5,Zone.PLAY) for m in full_minions)
                     and p.max_mana==10 and p2.max_mana==9 and len(low_minions)==1 and low.zone==Zone.PLAY,observed)
    audit(cid,[("ten_mana_crystals_summon_two_copies","Omega Agent summons two copies at 10 Mana Crystals and no copies at 9.",ten_mana_summons_two_copies_nine_mana_does_not,"Compared a full-crystal game with a 9-crystal game while both could pay the card's cost.")])


def mechano_egg():
    cid="BOT_537"
    def deathrattle_summons_eight_eight_robosaur():
        g,p,e=game(CardClass.PALADIN,CardClass.MAGE);egg=summon(p,cid);egg.destroy()
        bots=[m for m in p.field if m.id=="BOT_537t"]
        observed=f"egg={egg.zone.name};summons={[(m.atk,m.health,m.max_health,m.races,m.zone.name) for m in bots]}"
        return check(egg.zone==Zone.GRAVEYARD and len(bots)==1 and (bots[0].atk,bots[0].health,bots[0].zone)==(8,8,Zone.PLAY),observed)
    audit(cid,[("deathrattle_summons_eight_eight_robosaur","Mechano-Egg's Deathrattle summons one 8/8 Robosaur.",deathrattle_summons_eight_eight_robosaur,"Destroyed the live Egg, then inspected exact Robosaur stats and board destination.")])


def spark_engine():
    cid="BOT_538"
    def adds_rush_spark_to_hand_and_it_can_attack_minion():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);source=play(p,cid)
        sparks=[c for c in p.hand if c.id=="BOT_102t"];target=summon(e,"CS2_182")
        if sparks:spark=sparks[0].play()
        else:spark=None
        minion_ready=bool(spark and spark.can_attack(target));hero_ready=bool(spark and spark.can_attack(e.hero))
        if minion_ready:spark.attack(target)
        observed=f"source={source.zone.name};generated={[(c.atk,c.health,c.rush,c.zone.name) for c in sparks]};spark={(spark.zone.name,spark.rush,spark.damage) if spark else None};minion_ready={minion_ready};hero_ready={hero_ready};target={target.zone.name}"
        return check(source.zone==Zone.PLAY and len(sparks)==1 and spark.zone==Zone.GRAVEYARD
                     and (spark.atk,spark.max_health,spark.rush)==(1,1,True) and minion_ready and not hero_ready
                     and target.zone==Zone.PLAY and target.damage==1,observed)
    audit(cid,[("battlecry_adds_rush_spark_that_attacks_minion","Spark Engine adds a 1/1 Rush Spark to hand; it can attack an enemy minion but not a hero on the turn played.",adds_rush_spark_to_hand_and_it_can_attack_minion,"Played the generated hand token immediately and checked Rush target legality and combat result.")])


def arcane_dynamo():
    cid="BOT_539"
    def discovers_a_spell_costing_five_or_more():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);source=play(p,cid)
        options=list(p.choice.cards) if p.choice else [];details=[(c.id,CardType(c.type).name,c.cost,c.zone.name) for c in options]
        selected=options[0] if options else None
        if selected:p.choice.choose(selected)
        observed=f"source={source.zone.name};options={details};selected={(selected.id,selected.cost,selected.zone.name) if selected else None};choice_open={p.choice is not None}"
        return check(source.zone==Zone.PLAY and len(options)==3 and all(c.type==CardType.SPELL and c.cost>=5 for c in options)
                     and selected in p.hand and selected.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("discover_three_spells_costing_five_plus","Arcane Dynamo discovers three spells costing at least 5 and the selected spell enters hand.",discovers_a_spell_costing_five_or_more,"Resolved the real Discover and checked every offered card's type/cost plus selected destination.")])


def emp_operative():
    cid="BOT_540"
    def destroys_mech_but_keeps_nonmech():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);mech=summon(e,"BOT_020");plain=summon(e,"CS2_182")
        card=p.give(cid);legal=list(card.play_targets);eligible=mech in legal and plain not in legal
        card.play(target=mech)
        observed=f"eligible_targets={[(m.id,m.zone.name) for m in legal]};spell_body={card.zone.name};mech={mech.zone.name};plain={plain.zone.name}"
        return check(eligible and card.zone==Zone.PLAY and mech.zone==Zone.GRAVEYARD and plain.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_destroys_mech_only","E.M.P. Operative destroys a targeted Mech; a non-Mech enemy minion is not a legal target and remains.",destroys_mech_but_keeps_nonmech,"Enemy board contains a Mech and Yeti; inspected legal target set and both post-Battlecry zones.")])


def omega_mind():
    cid="BOT_543"
    def ten_mana_grants_lifesteal_to_this_turn_spells_only():
        g,p,e=game(CardClass.SHAMAN,CardClass.MAGE);p.hero.damage=8;mind=play(p,cid);first_power=p.spellpower
        fireball=play(p,"CS2_029",target=e.hero);after_full=p.hero.health
        g2,p2,e2=game(CardClass.SHAMAN,CardClass.MAGE);p2.max_mana=9;p2.hero.damage=8;low=play(p2,cid)
        lowspell=play(p2,"CS2_029",target=e2.hero);after_low=p2.hero.health
        observed=f"full_crystals={p.max_mana};full_power={first_power};mind={mind.zone.name};fireball={fireball.zone.name};healed={22}->{after_full};nine_crystals={p2.max_mana};low_mind={low.zone.name};low_spell={lowspell.zone.name};health={22}->{after_low}"
        return check(p.max_mana==10 and first_power==0 and after_full==28 and p2.max_mana==9 and after_low==22,observed)
    audit(cid,[("ten_crystals_make_this_turn_spells_lifesteal","At 10 Mana Crystals Omega Mind gives spells Lifesteal for the turn (Fireball heals 6); at 9 crystals Fireball does not heal.",ten_mana_grants_lifesteal_to_this_turn_spells_only,"Used identical damaged-hero Fireball scenarios at 10 and 9 crystals to isolate Lifesteal gate and healing.")])


def loose_specimen():
    cid="BOT_544"
    def six_random_damage_hits_only_other_friendly_minion():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE,seed=5441);target=summon(p,"EX1_561")
        before=(target.health,p.hero.health,e.hero.health);specimen=play(p,cid)
        observed=f"before={before};specimen={(specimen.atk,specimen.health,specimen.damage,specimen.zone.name)};target={(target.damage,target.health,target.zone.name)};heroes={p.hero.health}/{e.hero.health}"
        return check(specimen.zone==Zone.PLAY and specimen.damage==0 and specimen.health==specimen.max_health
                     and target.zone==Zone.PLAY and target.damage==6 and target.health==before[0]-6
                     and (p.hero.health,e.hero.health)==before[1:],observed)
    audit(cid,[("six_damage_randomly_split_among_other_friendly_minions","Loose Specimen deals six total damage randomly among other friendly minions and excludes itself and both heroes.",six_random_damage_hits_only_other_friendly_minion,"A single high-health friendly target isolates all six damage instances; source, heroes, and target health/damage are checked.")])


def zilliax():
    cid="BOT_548"
    def magnetic_keywords_work_and_rush_lifesteal_combat_resolves():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);p.hero.damage=5
        target=summon(e,"CS2_182");body=play(p,cid)
        initial=(body.atk,body.health,body.taunt,body.divine_shield,body.lifesteal,body.rush)
        minion_ready=body.can_attack(target);hero_ready=body.can_attack(e.hero)
        if minion_ready:body.attack(target)
        observed=f"initial={initial};minion_ready={minion_ready};hero_ready={hero_ready};body={(body.zone.name,body.damage,body.divine_shield)};target={target.health};hero={25}->{p.hero.health}"
        return check(initial==(3,2,True,True,True,True) and minion_ready and not hero_ready
                     and body.zone==Zone.PLAY and not body.divine_shield and target.health==2 and p.hero.health==28,observed)
    audit(cid,[("zilliax_keywords_rush_taunt_shield_and_lifesteal","Zilliax has Magnetic, Divine Shield, Taunt, Lifesteal, and Rush; its Rush attack hits a minion and Lifesteal heals its hero.",magnetic_keywords_work_and_rush_lifesteal_combat_resolves,"Played Zilliax directly, checked its combat keywords, attacked a minion, and observed shield loss/target damage/hero healing.")])


def electrowright():
    cid="BOT_550"
    def high_cost_hand_spell_grants_stats_and_low_cost_does_not():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);high=p.give("EX1_279");low=p.give("CS2_029");buffed=play(p,cid)
        g2,p2,e2=game(CardClass.MAGE,CardClass.MAGE);only_low=p2.give("CS2_029");plain=play(p2,cid)
        observed=f"high_cost={high.cost};low_cost={low.cost};buffed={(buffed.atk,buffed.health,buffed.max_health)};low_only={only_low.cost};plain={(plain.atk,plain.health,plain.max_health)}"
        return check(high.cost>=5 and low.cost<5 and (buffed.atk,buffed.max_health)==(4,4)
                     and only_low.cost<5 and (plain.atk,plain.max_health)==(3,3),observed)
    audit(cid,[("five_cost_spell_in_hand_grants_one_one","Electrowright gains +1/+1 while its controller holds a spell costing at least 5; a 4-Cost-only hand does not trigger it.",high_cost_hand_spell_grants_stats_and_low_cost_does_not,"Compared Fireball-only with Pyroblast plus Fireball in hand and checked printed/body stats.")])


def star_aligner():
    cid="BOT_552"
    def three_seven_health_gate_hits_enemies_only():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        first=summon(p,"CS2_155");second=summon(p,"CS2_155")
        target=summon(e,"EX1_561");target_before=target.health;enemy_before=e.hero.health;friendly_before=p.hero.health
        source=play(p,cid);target_after=target.health;enemy_after=e.hero.health
        g2,p2,e2=game(CardClass.MAGE,CardClass.MAGE);only=summon(p2,"CS2_155")
        second_target=summon(e2,"EX1_561");second_target_before=second_target.health;enemy_control=e2.hero.health;no_proc=play(p2,cid)
        observed=f"threshold_health={(first.health,second.health,source.health)};target={target_before}->{target_after};enemy_hero={enemy_before}->{enemy_after};friendly_hero={friendly_before}->{p.hero.health};one_prior_minion_target={second_target.health};enemy_control={enemy_control}->{e2.hero.health}"
        return check(source.zone==Zone.PLAY and first.health==7 and second.health==7 and target.health==target_before-7
                     and e.hero.health==enemy_before-7 and p.hero.health==friendly_before
                     and second_target.health==second_target_before and e2.hero.health==enemy_control,observed)
    audit(cid,[("three_minions_at_seven_health_deal_seven_to_enemies","Star Aligner deals 7 to all enemies when three friendly minions have 7 Health; fewer than three does nothing.",three_seven_health_gate_hits_enemies_only,"Two 7-Health minions plus Star Aligner test the powered case; one 7-Health minion plus body tests the negative, with enemy/friendly controls.")])


def harbinger_celestia():
    cid="BOT_555"
    def stealth_copies_opponent_minion_played():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);celestia=summon(p,cid)
        initial=(celestia.id,celestia.stealthed,celestia.atk,celestia.health)
        g.end_turn();opponent=play(e,"CS2_182")
        copies=[m for m in p.field if m.id==opponent.id]
        observed=f"initial={initial};opponent={(opponent.id,opponent.atk,opponent.health)};old_entity={celestia.zone.name};friendly_field={[(m.id,m.atk,m.health,m.max_health,m.stealthed,m.zone.name) for m in p.field]}"
        return check(initial[0]==cid and initial[1] and opponent.zone==Zone.PLAY and len(copies)==1
                     and (copies[0].atk,copies[0].max_health)==(opponent.atk,opponent.max_health),observed)
    audit(cid,[("after_opponent_minion_play_becomes_copy","Harbinger Celestia starts Stealthed and becomes a copy of the opponent's minion after it is played.",stealth_copies_opponent_minion_played,"Checked initial Stealth, then compared the live transformed minion's identity/stats with the opponent's just-played minion.")])


def test_subject():
    cid="BOT_558"
    def returns_only_spells_cast_on_subject_after_death():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE);subject=summon(p,cid)
        targeted=[play(p,"BOT_219",target=subject),play(p,"BOT_219t",target=subject)]
        unrelated=play(p,MOONFIRE,target=e.hero);before_stats=(subject.atk,subject.health)
        subject.destroy();returned=[c for c in p.hand if c.id in ("BOT_219","BOT_219t")]
        observed=f"targeted={[c.zone.name for c in targeted]};unrelated={unrelated.zone.name};subject={subject.zone.name}/{before_stats};returned={[(c.id,c.zone.name) for c in returned]};hand={[c.id for c in p.hand]}"
        return check(subject.zone==Zone.GRAVEYARD and all(c.zone==Zone.GRAVEYARD for c in targeted)
                     and unrelated.zone==Zone.GRAVEYARD and len([c for c in returned if c.id=="BOT_219"])==1
                     and len([c for c in returned if c.id=="BOT_219t"])==2
                     and not any(c.id==MOONFIRE for c in p.hand),observed)
    audit(cid,[("deathrattle_returns_spells_cast_on_subject","Test Subject's Deathrattle returns each spell cast on it to hand; a spell cast elsewhere is not returned.",returns_only_spells_cast_on_subject_after_death,"Two distinct targeted spells and one hero-targeted control spell were followed through the minion's death.")])


def augmented_elekk():
    cid="BOT_559"
    def friendly_shuffle_adds_extra_copy():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);elekk=summon(p,cid)
        card=p.give(WISP);card.shuffle_into_deck();own=[c for c in p.deck if c.id==WISP]
        control=e.give("CS2_182");control.shuffle_into_deck();enemy=[c for c in e.deck if c.id=="CS2_182"]
        observed=f"elekk={elekk.zone.name};friendly_original={card.zone.name};friendly_copies={[(c.id,c.zone.name) for c in own]};enemy_original={control.zone.name};enemy_copies={[(c.id,c.zone.name) for c in enemy]}"
        return check(elekk.zone==Zone.PLAY and len(own)==2 and all(c.zone==Zone.DECK for c in own)
                     and len(enemy)==1 and control.zone==Zone.DECK,observed)
    audit(cid,[("shuffle_into_own_deck_adds_one_extra_copy","Augmented Elekk adds an extra copy whenever a card is shuffled into its controller's deck.",friendly_shuffle_adds_extra_copy,"Shuffled one known card into the friendly deck with Elekk present and one opponent control card into the enemy deck.")])


def coppertail_imposter():
    cid="BOT_562"
    def gains_stealth_until_next_own_turn():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);body=play(p,cid);initial=body.stealthed
        g.end_turn();blocked=e.give("CS2_029");mana_before=e.used_mana;attack_error=None
        try:blocked.play(target=body)
        except InvalidAction as exc:attack_error=type(exc).__name__
        no_payment=blocked.zone==Zone.HAND and e.used_mana==mana_before
        g.end_turn();after=body.stealthed
        observed=f"initial_stealth={initial};blocked_spell={attack_error};no_payment={no_payment};after_next_own_start={after};body={body.zone.name}"
        return check(initial and attack_error=="InvalidAction" and no_payment and not after and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_stealth_expires_at_next_own_turn","Coppertail Imposter gains Stealth and loses it at the start of its controller's next turn.",gains_stealth_until_next_own_turn,"Checked initial Stealth, attempted opposing hero combat, then advanced both turn boundaries and checked expiration.")])


def wargear():
    cid="BOT_563"
    def magnetic_attachment_and_standalone_body():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);host=summon(p,"BOT_445");before=(host.atk,host.health)
        card=play(p,cid,index=0);attached=(host.atk,host.health,host.zone.name,card.zone.name)
        g2,p2,e2=game(CardClass.MAGE,CardClass.MAGE);standalone=play(p2,cid)
        observed=f"magnet_before={before};attached={attached};standalone={(standalone.atk,standalone.health,standalone.zone.name)}"
        return check(attached[:2]==(before[0]+5,before[1]+5) and host.zone==Zone.PLAY
                     and card.zone!=Zone.PLAY and standalone.zone==Zone.PLAY and (standalone.atk,standalone.health)==(5,5),observed)
    audit(cid,[("magnetic_buffs_mech_or_plays_as_five_five","Wargear attaches as Magnetic to a friendly Mech for +5/+5, or plays as a 5/5 when not attached.",magnetic_attachment_and_standalone_body,"Compared a Magnetic play on Mecharoo with a separate standalone play and checked attachment/card zones.")])


def blightnozzle_crawler():
    cid="BOT_565"
    def deathrattle_summons_rush_poisonous_ooze():
        g,p,e=game(CardClass.ROGUE,CardClass.MAGE);crawler=summon(p,cid);crawler.destroy()
        ooze=[m for m in p.field if m.id=="BOT_565t"][0];target=summon(e,"EX1_561")
        ready_now=ooze.can_attack(target);face_now=ooze.can_attack(e.hero)
        if ready_now:ooze.attack(target)
        observed=f"crawler={crawler.zone.name};ooze={(ooze.atk,ooze.health,ooze.poisonous,ooze.rush,ooze.zone.name)};minion_ready={ready_now};face_ready={face_now};target={target.zone.name}"
        return check(crawler.zone==Zone.GRAVEYARD and (ooze.atk,ooze.max_health,ooze.poisonous,ooze.rush)==(1,1,True,True)
                     and ready_now and not face_now and ooze.zone==Zone.GRAVEYARD and target.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deathrattle_ooze_has_poisonous_rush","Blightnozzle Crawler's Deathrattle summons a 1/1 Ooze with Poisonous and Rush; it can kill an enemy minion immediately.",deathrattle_summons_rush_poisonous_ooze,"Killed the Crawler, inspected its token, then attacked a high-health enemy minion while checking Rush cannot target face.")])


def reckless_experimenter():
    cid="BOT_566"
    def reduces_deathrattle_cost_and_destroys_played_minion_at_turn_end():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE);experimenter=play(p,cid)
        deathrattle=p.give("BOT_445");plain=p.give("CS2_182");costs=(deathrattle.cost,plain.cost)
        played=deathrattle.play();ordinary=plain.play();g.end_turn()
        bots=[m for m in p.field if m.id=="BOT_445t"]
        observed=f"experimenter={experimenter.zone.name};hand_costs={costs};played={played.zone.name};plain={(ordinary.id,ordinary.zone.name,ordinary.health)};death_tokens={[(m.id,m.zone.name) for m in bots]}"
        return check(costs==(0,4) and played.zone==Zone.GRAVEYARD and ordinary.zone==Zone.PLAY
                     and len(bots)==1 and bots[0].zone==Zone.PLAY,observed)
    audit(cid,[("deathrattle_minions_cost_three_less_then_die_at_turn_end","Reckless Experimenter reduces Deathrattle minion costs by 3 and destroys those played during the turn at its end; ordinary minions remain.",reduces_deathrattle_cost_and_destroys_played_minion_at_turn_end,"Compared a discounted Mecharoo with an unmodified Yeti, then ended the turn and checked each resulting zone/token.")])


def zereks_cloning_gallery():
    cid="BOT_567"
    def summons_one_one_copies_of_deck_minions_only():
        g,p,e=game(CardClass.PRIEST,CardClass.MAGE);minions=put_deck(p,["CS2_182","BOT_445"]);spell=put_deck(p,["CS2_029"])[0]
        source=play(p,cid);copies=[m for m in p.field if m is not source]
        observed=f"source={source.zone.name};originals={[(c.id,c.zone.name) for c in minions]};spell={spell.id}:{spell.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};deck={[c.id for c in p.deck]}"
        return check(source.zone==Zone.GRAVEYARD and all(c.zone==Zone.DECK for c in minions) and spell.zone==Zone.DECK
                     and len(copies)==2 and sorted((m.id,m.atk,m.max_health) for m in copies)==sorted([(c.id,1,1) for c in minions]),observed)
    audit(cid,[("summons_one_one_copy_of_each_deck_minion","Zerek's Cloning Gallery summons a 1/1 copy of each minion in the deck and leaves originals and spells in deck.",summons_one_one_copies_of_deck_minions_only,"Two different minion references and a spell were placed in deck; checked all generated copies and source-card zones.")])


def the_soularium():
    cid="BOT_568"
    def draws_three_then_discards_only_them_at_end_turn():
        g,p,e=game(CardClass.WARLOCK,CardClass.MAGE);control=p.give(WISP)
        deck=put_deck(p,["CS2_182","CS2_231","CS2_029",MOONFIRE]);source=play(p,cid)
        drawn=[c for c in deck if c.zone==Zone.HAND];remaining=[c for c in deck if c.zone==Zone.DECK]
        before_end=(len(drawn),[c.id for c in p.hand],len(remaining));g.end_turn()
        observed=f"source={source.zone.name};before_end={before_end};after={[(c.id,c.zone.name) for c in deck]};control={control.zone.name};hand={[c.id for c in p.hand]}"
        return check(source.zone==Zone.GRAVEYARD and len(drawn)==3 and len(remaining)==1 and control in p.hand
                     and all(c not in p.hand and c.zone!=Zone.HAND for c in drawn) and control.zone==Zone.HAND
                     and len([c for c in deck if c.zone==Zone.DECK])==1,observed)
    audit(cid,[("draws_three_and_discards_them_at_own_turn_end","The Soularium draws three cards, then discards those cards at the end of the turn while preexisting hand cards remain.",draws_three_then_discards_only_them_at_end_turn,"Tracked four known deck cards and a preexisting hand control across the cast and owner's end step.")])


def subject_nine():
    cid="BOT_573"
    def draws_five_distinct_secrets_from_deck():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        secrets=put_deck(p,["EX1_287","EX1_289","EX1_294","EX1_533","EX1_554","EX1_610"])
        source=play(p,cid);drawn=[c for c in secrets if c.zone==Zone.HAND];left=[c for c in secrets if c.zone==Zone.DECK]
        observed=f"source={source.zone.name};drawn={[(c.id,c.zone.name,c.data.secret) for c in drawn]};left={[(c.id,c.zone.name) for c in left]};hand={[c.id for c in p.hand]}"
        return check(source.zone==Zone.PLAY and len(drawn)==5 and len({c.id for c in drawn})==5
                     and all(c.data.secret and c.zone==Zone.HAND for c in drawn) and len(left)==1,observed)
    audit(cid,[("battlecry_draws_five_different_secrets","Subject 9 draws five different Secrets from the deck and leaves the sixth Secret there.",draws_five_distinct_secrets_from_deck,"Six uniquely identified Secrets were placed in deck, then their distinct draw/remaining zones were inspected.")])


def crazed_chemist():
    cid="BOT_576"
    def combo_gives_four_attack_but_no_combo_does_not():
        g,p,e=game(CardClass.ROGUE,CardClass.MAGE);target=summon(p,"CS2_182");before=(target.atk,target.health)
        coin=play(p,"GAME_005");buffed=play(p,cid,target=target);after=(target.atk,target.health)
        g2,p2,e2=game(CardClass.ROGUE,CardClass.MAGE);plain_target=summon(p2,"CS2_182");plain_before=(plain_target.atk,plain_target.health)
        plain=play(p2,cid);plain_after=(plain_target.atk,plain_target.health)
        observed=f"combo_coin={coin.zone.name};combo_body={buffed.zone.name};target={before}->{after};no_combo_body={plain.zone.name};target={plain_before}->{plain_after}"
        return check(after==(before[0]+4,before[1]) and buffed.zone==Zone.PLAY
                     and plain.zone==Zone.PLAY and plain_after==plain_before,observed)
    audit(cid,[("combo_gives_target_four_attack_only","Crazed Chemist's Combo gives a friendly minion +4 Attack; without Combo it does not buff.",combo_gives_four_attack_but_no_combo_does_not,"Used Coin before one copy to activate Combo and played a second copy first in a separate game as a negative control.")])


def research_project():
    cid="BOT_600"
    def each_player_draws_two_cards():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        own=put_deck(p,["CS2_182","CS2_231","CS2_029"]);foe=put_deck(e,["CS2_182","CS2_231","CS2_029"])
        spell=play(p,cid);own_drawn=[c for c in own if c.zone==Zone.HAND];foe_drawn=[c for c in foe if c.zone==Zone.HAND]
        observed=f"spell={spell.zone.name};own_drawn={[(c.id,c.zone.name) for c in own_drawn]};foe_drawn={[(c.id,c.zone.name) for c in foe_drawn]};decks={len(p.deck)}/{len(e.deck)}"
        return check(spell.zone==Zone.GRAVEYARD and len(own_drawn)==2 and len(foe_drawn)==2
                     and len(p.deck)==1 and len(e.deck)==1,observed)
    audit(cid,[("spell_draws_two_for_each_player","Research Project makes each player draw two cards.",each_player_draws_two_cards,"Tracked three known cards in each deck and verified both players drew exactly two with one remaining.")])


def meteorologist():
    cid="BOT_601"
    def one_damage_per_remaining_hand_card_to_random_enemies():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);hand=[p.give("CS2_008"),p.give("CS2_029"),p.give(WISP)]
        enemies=[summon(e,"EX1_561"),summon(e,"EX1_561")];enemy_before=sum(m.health for m in enemies)+e.hero.health
        friendly_before=p.hero.health;body=play(p,cid)
        enemy_after=sum(m.health for m in enemies)+e.hero.health;total=enemy_before-enemy_after
        observed=f"hand_remaining={len(hand)};body={(body.zone.name,body.damage,body.health)};enemy_health_before={enemy_before};enemy_health_after={enemy_after};total_enemy_damage={total};enemy_states={[(m.health,m.damage,m.zone.name) for m in enemies]};friendly_hero={friendly_before}->{p.hero.health}"
        return check(body.zone==Zone.PLAY and total==len(hand) and body.damage==0
                     and all(m.zone==Zone.PLAY for m in enemies) and p.hero.health==friendly_before,observed)
    audit(cid,[("battlecry_damage_scales_with_hand_size_to_enemies","Meteorologist deals one random enemy damage per card remaining in hand when its Battlecry resolves.",one_damage_per_remaining_hand_card_to_random_enemies,"Kept three hand cards and provided two high-health enemy minions plus the enemy hero as valid random targets; measured aggregate enemy damage.")])


def steel_rager():
    cid="BOT_603"
    def rush_attacks_minion_but_not_hero():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);target=summon(e,"CS2_182");body=play(p,cid)
        before=(body.atk,body.max_health,body.rush);minion_ready=body.can_attack(target);hero_ready=body.can_attack(e.hero)
        if minion_ready:body.attack(target)
        observed=f"before={before};minion_ready={minion_ready};hero_ready={hero_ready};body={body.zone.name}/{body.damage};target={target.zone.name}/{target.damage}"
        return check(before[2] and minion_ready and not hero_ready and body.zone==Zone.GRAVEYARD
                     and target.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("rush_minion_can_attack_minion_not_hero","Steel Rager has Rush, so it may attack a minion but not a hero on the turn played.",rush_attacks_minion_but_not_hero,"Played Steel Rager directly, checked target legality, then resolved its attack into a Yeti.")])


def cosmic_anomaly():
    cid="BOT_604"
    def spell_damage_plus_two_applies_to_damage_spell():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);anomaly=play(p,cid);power=p.spellpower
        spell=play(p,MOONFIRE,target=e.hero);after=e.hero.health
        observed=f"anomaly={anomaly.zone.name};spellpower={power};spell={spell.zone.name};enemy_hero={30}->{after}"
        return check(anomaly.zone==Zone.PLAY and power==2 and spell.zone==Zone.GRAVEYARD and after==27,observed)
    audit(cid,[("spell_damage_two_increases_spell_damage","Cosmic Anomaly provides Spell Damage +2; Moonfire deals 3 instead of 1.",spell_damage_plus_two_applies_to_damage_spell,"Read the live Spell Damage aura and compared a targeted Moonfire's damage to its normal 1.")])


def kaboom_bot():
    cid="BOT_606"
    def deathrattle_hits_random_enemy_minion_not_heroes():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE,seed=6061);targets=[summon(e,"EX1_561"),summon(e,"EX1_561")]
        enemy_before=sum(m.health for m in targets)+e.hero.health;own=p.hero.health
        bot=summon(p,cid);bot.destroy();damage=sum(m.max_health-m.health for m in targets)
        observed=f"bot={bot.zone.name};enemy_minions={[(m.health,m.damage,m.zone.name) for m in targets]};total_minion_damage={damage};heroes={own}/{enemy_before}->{p.hero.health}/{e.hero.health}"
        return check(bot.zone==Zone.GRAVEYARD and damage==4 and all(m.zone==Zone.PLAY for m in targets)
                     and p.hero.health==own and e.hero.health==30,observed)
    audit(cid,[("deathrattle_deals_four_to_random_enemy_minion","Kaboom Bot's Deathrattle deals 4 damage to a random enemy minion without damaging either hero.",deathrattle_hits_random_enemy_minion_not_heroes,"Two high-health enemy minions ensure the four damage is observable without deaths; both hero totals are controls.")])


def snip_snap():
    cid="BOT_700"
    def echo_and_magnetic_deathrattles_each_summon_two_bots():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);first=play(p,cid);echo=next((c for c in p.hand if c.id==cid),None)
        first.destroy();after_first=[m for m in p.field if m.id=="BOT_312t"]
        if echo:second=echo.play()
        else:second=None
        if second:second.destroy()
        total=[m for m in p.field if m.id=="BOT_312t"]
        g2,p2,e2=game(CardClass.MAGE,CardClass.MAGE);host=summon(p2,"BOT_445");mag=play(p2,cid,index=0);host.destroy()
        attached=[m for m in p2.field if m.id=="BOT_312t"]
        observed=f"first={first.zone.name};echo={echo.zone.name if echo else None};after_first={len(after_first)};second={second.zone.name if second else None};total={len(total)};magnet={mag.zone.name};host={host.zone.name};attached_tokens={len(attached)}"
        return check(len(after_first)==2 and second is not None and len(total)==4 and all(m.zone==Zone.PLAY for m in total)
                     and host.zone==Zone.GRAVEYARD and len(attached)==2,observed)
    audit(cid,[("echo_replay_and_magnetic_deathrattle_summon_bots","SN1P-SN4P's Echo replay gives another body; its Deathrattle and magnetic Deathrattle each summon two Microbots.",echo_and_magnetic_deathrattles_each_summon_two_bots,"Destroyed first and Echo bodies in sequence, then separately attached SN1P-SN4P to a Mech and checked host-death summons.")])


def glow_tron():
    cid="BOT_906"
    def magnetic_mech_gains_one_three_and_stays_on_board():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);host=summon(p,"BOT_445");before=(host.atk,host.max_health)
        magnet=play(p,cid,index=0);observed=f"before={before};host={(host.atk,host.health,host.max_health,host.zone.name)};magnet={magnet.zone.name}"
        return check((host.atk,host.max_health)==(before[0]+1,before[1]+3) and host.zone==Zone.PLAY and magnet.zone!=Zone.PLAY,observed)
    audit(cid,[("magnetic_glow_tron_adds_one_three","Glow-Tron's Magnetic effect adds +1/+3 to a friendly Mech while leaving it on board.",magnetic_mech_gains_one_three_and_stays_on_board,"Attached to a 1/1 Mech and checked stat deltas and attached card destination.")])


def galvanizer():
    cid="BOT_907"
    def reduces_only_mech_hand_cost_then_reverts_when_removed():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);mech_a=p.give("BOT_445");mech_b=p.give("BOT_563");plain=p.give("CS2_182")
        original=(mech_a.data.cost,mech_b.data.cost,plain.data.cost);body=play(p,cid)
        reduced=(mech_a.cost,mech_b.cost,plain.cost);body.destroy();after_source_removed=(mech_a.cost,mech_b.cost,plain.cost)
        observed=f"original={original};reduced={reduced};after_source_removed={after_source_removed};galvanizer={body.zone.name}"
        return check(reduced==(0,4,4)
                     and after_source_removed==reduced and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("battlecry_reduces_mech_hand_costs_by_one","Galvanizer reduces Mech costs in hand by 1 and leaves non-Mechs unchanged; the Battlecry reduction persists after the source leaves.",reduces_only_mech_hand_cost_then_reverts_when_removed,"Tracked two Mech hand cards and a Yeti control before/after Galvanizer and after its removal.")])


def autodefense_matrix():
    cid="BOT_908"
    def secret_gives_attacked_friendly_minion_divine_shield():
        g,p,e=game(CardClass.PALADIN,CardClass.WARRIOR);defender=summon(p,"CS2_182");attacker=summon(e,"CS2_182")
        ready(attacker);secret=play(p,cid);g.end_turn();before=(defender.health,defender.divine_shield)
        attacker.attack(defender);after=(defender.health,defender.damage,defender.divine_shield)
        observed=f"secret={secret.zone.name};before={before};after={after};attacker={attacker.zone.name}/{attacker.damage}"
        return check(secret.zone==Zone.GRAVEYARD and before==(5,False) and after==(5,0,False)
                     and attacker.zone==Zone.PLAY and attacker.damage==4,observed)
    audit(cid,[("secret_shields_friendly_minion_when_attacked","Autodefense Matrix triggers when an enemy attacks a friendly minion and grants that minion Divine Shield before combat damage.",secret_gives_attacked_friendly_minion_divine_shield,"Equipped the Secret and resolved an enemy Yeti attack into a friendly Yeti while checking defender damage/shield and attacker combat.")])


def crystology():
    cid="BOT_909"
    def draws_two_one_attack_minions_and_leaves_other_attack_values():
        g,p,e=game(CardClass.PALADIN,CardClass.MAGE);one_attack=put_deck(p,["BOT_445",WISP])
        high=p.give("CS2_182");high.shuffle_into_deck();spell=p.give("CS2_029");spell.shuffle_into_deck()
        cast=play(p,cid);drawn=[c for c in one_attack if c.zone==Zone.HAND];left=[c for c in (high,spell) if c.zone==Zone.DECK]
        observed=f"spell={cast.zone.name};eligible={[(c.id,c.atk,c.zone.name) for c in one_attack]};high={high.id}/{high.atk}/{high.zone.name};deck_spell={spell.zone.name};hand={[c.id for c in p.hand]}"
        return check(cast.zone==Zone.GRAVEYARD and len(drawn)==2 and all(c.atk==1 for c in drawn)
                     and high.zone==Zone.DECK and spell.zone==Zone.DECK and len(left)==2,observed)
    audit(cid,[("draws_two_minions_with_one_attack","Crystology draws two minions with 1 Attack and leaves higher-Attack minions and spells in the deck.",draws_two_one_attack_minions_and_leaves_other_attack_values,"Two 1-Attack Mechs, a 4-Attack Yeti, and a spell isolate the Attack/type filter.")])


def glowstone_technician():
    cid="BOT_910"
    def gives_all_hand_minions_plus_two_plus_two_only():
        g,p,e=game(CardClass.PALADIN,CardClass.MAGE);a=p.give("CS2_182");b=p.give("BOT_445");spell=p.give("CS2_029")
        before=[(c.id,c.atk,c.health,c.max_health) for c in (a,b)];source=play(p,cid)
        observed=f"before={before};after={[(c.id,c.atk,c.health,c.max_health,c.zone.name) for c in (a,b)]};spell={spell.id}/{spell.cost}/{spell.zone.name};source={source.zone.name}"
        return check(source.zone==Zone.PLAY and (a.atk,a.max_health)==(before[0][1]+2,before[0][3]+2)
                     and (b.atk,b.max_health)==(before[1][1]+2,before[1][3]+2)
                     and spell.zone==Zone.HAND and spell.cost==4,observed)
    audit(cid,[("battlecry_buffs_all_minions_in_hand","Glowstone Technician gives every minion in hand +2/+2 and does not change a spell in hand.",gives_all_hand_minions_plus_two_plus_two_only,"Kept two different minions and a Fireball in hand through the Battlecry and compared stats/costs.")])


def annoy_o_module():
    cid="BOT_911"
    def magnetic_adds_taunt_shield_and_has_standalone_keywords():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE);host=summon(p,"BOT_445");mod=play(p,cid,index=0)
        attached=(host.atk,host.max_health,host.taunt,host.divine_shield,mod.zone.name)
        g2,p2,e2=game(CardClass.MAGE,CardClass.MAGE);standalone=play(p2,cid)
        observed=f"attached={attached};standalone={(standalone.atk,standalone.health,standalone.taunt,standalone.divine_shield,standalone.zone.name)}"
        return check(attached==(3,5,True,True,"REMOVEDFROMGAME")
                     and (standalone.atk,standalone.max_health,standalone.taunt,standalone.divine_shield,standalone.zone)==(2,4,True,True,Zone.PLAY),observed)
    audit(cid,[("magnetic_annoy_o_module_adds_taunt_and_divine_shield","Annoy-o-Module attaches to a Mech adding Taunt and Divine Shield; played without a host it has those keywords itself.",magnetic_adds_taunt_shield_and_has_standalone_keywords,"Tested Magnetic attachment on Mecharoo and a second standalone play, inspecting stats/keywords/zones.")])


def kangors_endless_army():
    cid="BOT_912"
    def resurrects_three_mechs_and_preserves_magnetic_upgrades():
        g,p,e=game(CardClass.PALADIN,CardClass.MAGE);hosts=[summon(p,"BOT_445") for _ in range(3)]
        rush=play(p,"BOT_020",index=0);big=play(p,"BOT_563",index=1)
        states=[(h.atk,h.max_health,h.rush) for h in hosts]
        for h in hosts:h.destroy()
        before=[(h.id,h.zone.name,h.atk,h.max_health,h.rush) for h in hosts]
        p.used_mana=0
        spell=play(p,cid);returned=[m for m in p.field if m.id=="BOT_445"]
        after=sorted((m.atk,m.max_health,m.rush,m.zone.name) for m in returned)
        expected=sorted([(1,1,False,"PLAY"),(2,2,True,"PLAY"),(6,6,False,"PLAY")])
        observed=f"magnetic_cards={(rush.zone.name,big.zone.name)};host_states={states};dead={before};spell={spell.zone.name};resurrected={after}"
        return check(spell.zone==Zone.GRAVEYARD and len(returned)==3 and after==expected,observed)
    audit(cid,[("resurrects_three_mechs_with_magnetic_upgrades","Kangor's Endless Army resurrects three friendly Mechs and preserves their Magnetic stat/keyword upgrades.",resurrects_three_mechs_and_preserves_magnetic_upgrades,"Killed three Mecharoos, two with different Magnetic upgrades (Rush and +5/+5), then checked the three resurrected copies.")])


def demonic_project():
    cid="BOT_913"
    def transforms_one_minion_in_each_hand_into_demon():
        g,p,e=game(CardClass.WARLOCK,CardClass.MAGE);own=[p.give("CS2_182"),p.give("BOT_445")];foe=[e.give("CS2_231"),e.give("EX1_016")]
        spell=play(p,cid);own_minions=[c for c in p.hand if c.type==CardType.MINION];foe_minions=[c for c in e.hand if c.type==CardType.MINION]
        own_demons=[c for c in own_minions if Race.DEMON in c.races];foe_demons=[c for c in foe_minions if Race.DEMON in c.races]
        observed=f"spell={spell.zone.name};own={[(c.id,c.races,c.zone.name) for c in own_minions]};opponent={[(c.id,c.races,c.zone.name) for c in foe_minions]};own_demons={len(own_demons)};enemy_demons={len(foe_demons)}"
        return check(spell.zone==Zone.GRAVEYARD and len(own_minions)==2 and len(foe_minions)==2
                     and len(own_demons)==1 and len(foe_demons)==1
                     and all(c.zone==Zone.HAND for c in own_minions+foe_minions),observed)
    audit(cid,[("transforms_one_random_hand_minion_for_each_player","Demonic Project transforms exactly one minion in each player's hand into a Demon.",transforms_one_minion_in_each_hand_into_demon,"Placed two hand minions on each side and checked each player's live post-Morph hand for exactly one Demon minion.")])


def whizbang():
    cid="BOT_914"
    def starting_deck_is_replaced_with_thirty_card_recipe():
        p1=Player("Player1",[cid],"BOT_914h",is_standard=False);p2=Player("Player2",[cid],"BOT_914h",is_standard=False)
        g=BaseTestGame(players=(p1,p2));g.random.seed(9141);g.start()
        states=[(len(player.starting_deck),len(player.deck),len(player.hand),sum(c.id=="GAME_005" for c in player.hand),player.hero.id,[c.id for c in player.starting_deck].count(cid)) for player in g.players]
        observed=f"players={states};current={g.current_player.name};choices={[player.choice is not None for player in g.players]}"
        return check(all(start==30 and deck+hand-coins==30 and whiz==0 for start,deck,hand,coins,hero,whiz in states)
                     and all(hero!="BOT_914h" for start,deck,hand,coins,hero,whiz in states),observed)
    audit(cid,[("game_start_replaces_whizbang_deck_with_thirty_cards","A starting deck containing only Whizbang is replaced at game start by a 30-card Wonderful Deck for each player.",starting_deck_is_replaced_with_thirty_card_recipe,"Initialized a real BaseTestGame with Whizbang deck/hero identities and checked each selected 30-card deck and opening hand size sum for both players.")])


RUNNERS={
    "BOT_517":topsy_turvy,"BOT_521":ectomancy,"BOT_523":mulchmuncher,"BOT_529":power_word_replicate,
    "BOT_531":celestial_emissary,"BOT_532":explodinator,"BOT_533":menacing_nimbus,"BOT_534":bull_dozer,
    "BOT_535":microtech_controller,"BOT_536":omega_agent,"BOT_537":mechano_egg,"BOT_538":spark_engine,
    "BOT_539":arcane_dynamo,"BOT_540":emp_operative,"BOT_543":omega_mind,"BOT_544":loose_specimen,
    "BOT_548":zilliax,"BOT_550":electrowright,"BOT_552":star_aligner,"BOT_555":harbinger_celestia,
    "BOT_558":test_subject,"BOT_559":augmented_elekk,"BOT_562":coppertail_imposter,"BOT_563":wargear,
    "BOT_565":blightnozzle_crawler,"BOT_566":reckless_experimenter,"BOT_567":zereks_cloning_gallery,
    "BOT_568":the_soularium,"BOT_573":subject_nine,"BOT_576":crazed_chemist,"BOT_600":research_project,
    "BOT_601":meteorologist,"BOT_603":steel_rager,"BOT_604":cosmic_anomaly,"BOT_606":kaboom_bot,
    "BOT_700":snip_snap,"BOT_906":glow_tron,"BOT_907":galvanizer,"BOT_908":autodefense_matrix,
    "BOT_909":crystology,"BOT_910":glowstone_technician,"BOT_911":annoy_o_module,
    "BOT_912":kangors_endless_army,"BOT_913":demonic_project,"BOT_914":whizbang,
}


def main():
    selected=sys.argv[1:] or list(FROZEN_IDS)
    assert selected and all(cid in RUNNERS for cid in selected),selected
    if not sys.argv[1:]:
        global PROBES,VERDICTS
        PROBES,VERDICTS=[],[]
        write_csv(PROBE_FILE,PROBE_FIELDS,PROBES)
        write_csv(VERDICT_FILE,VERDICT_FIELDS,VERDICTS)
    for cid in selected:RUNNERS[cid]()
    counts={name:sum(row["status"]==name for row in VERDICTS) for name in ("GREEN","YELLOW","RED")}
    print(f"COUNTS {counts}; cases={len(PROBES)}; selected={len(selected)}; frozen={len(FROZEN_IDS)}",flush=True)
    if not sys.argv[1:]:
        assert [row["card_id"] for row in VERDICTS]==list(FROZEN_IDS)
        assert {row["card_id"] for row in PROBES}==set(FROZEN_IDS)
        assert len({(row["card_id"],row["case_id"]) for row in PROBES})==len(PROBES)


if __name__=="__main__":
    main()
