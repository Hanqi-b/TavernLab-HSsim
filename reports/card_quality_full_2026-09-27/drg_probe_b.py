"""Card-specific live game checks for the middle 45 collectible DRAGONS YELLOW cards (frozen indices 45:90)."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Rarity, Zone
from fireplace.exceptions import InvalidAction
from fireplace.actions import CastSpell
from fireplace.managers import BaseObserver

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "drg_probe_b.csv"
VERDICT_FILE = HERE / "drg_verdict_b.csv"
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


ALL_DRAGONS = sorted((r for r in read(HERE / "remaining_yellow_baseline.csv")
                      if r["set"].endswith("(DRAGONS)")),
                     key=lambda r: r["card_id"])
ROSTER = ALL_DRAGONS[45:90]
assert len(ALL_DRAGONS) == 136 and len(ROSTER) == 45
assert ROSTER[0]["card_id"] == "DRG_076" and ROSTER[-1]["card_id"] == "DRG_242"
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
PROBES = read(PROBE_FILE)
VERDICTS = read(VERDICT_FILE)


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


def summon(player, cid):
    return player.summon(cid)


def play(player, cid, target=None, index=None):
    card = player.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if index is not None:
        kw["index"] = index
    card.play(**kw)
    return card


def check(ok, observed):
    assert ok, observed
    return observed


def meta(cid):
    m = MASTER[cid]
    b = ROSTER_BY_ID[cid]
    return (f"EN={m['card_text_en']}; ZH={m['card_text_zh']}; "
            f"source={m['python_source']}; existing_tests={m['test_refs_candidate'] or 'none'}; "
            f"prior={b['status']}:{b['reason']}; prior_evidence={b['evidence']}")


def audit(cid, tests, blocker=None):
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
        print(cid, case_id, outcome, observed)
    own = [r for r in PROBES if r["card_id"] == cid]
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in errors)
    elif unresolved or blocker:
        status = "YELLOW"
        reason = blocker or "运行未决：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in unresolved)
    else:
        status = "GREEN"
        reason = "逐卡关键行为断言通过：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in own)
    VERDICTS.append(dict(card_id=cid, status=status,
                         mechanic_scope=ROSTER_BY_ID[cid]["mechanic"], reason=reason,
                         probe_file=PROBE_FILE.name, notes=meta(cid)))
    write(VERDICT_FILE, VF, VERDICTS)
    print(cid, status, len(own), "cases")



def faceless_corruptor():
    cid="DRG_076"
    def transforms_friendly_minion_into_copy_with_rush():
        g,p,e=game(CardClass.MAGE,CardClass.MAGE)
        original=summon(p,"CS2_182")
        source=play(p,cid,target=original)
        live=[m for m in p.field if m.id==cid]
        observed=f"old_target={original.zone.name};source={(source.atk,source.health,source.rush,source.zone.name)};live={[(m.id,m.atk,m.health,m.rush,m.zone.name) for m in live]}"
        return check(original.zone==Zone.SETASIDE and source.zone==Zone.PLAY and len(live)==2
                     and all((m.atk,m.max_health,m.rush)==(4,4,True) and m.zone==Zone.PLAY for m in live),observed)
    audit(cid,[("battlecry_transforms_friendly_minion_into_faceless_copy","Faceless Corruptor's Battlecry transforms a friendly minion into a 4/4 copy of Faceless Corruptor with Rush.",transforms_friendly_minion_into_copy_with_rush,"Played it targeting a friendly Yeti and inspected the new live field entities rather than the stale pre-Morph target.")])


def utgarde_grapplesniper():
    cid="DRG_077"
    def both_dragons_summoned():
        g,p,e=game()
        own=p.card("DRG_079",zone=Zone.DECK); enemy=e.card("NEW1_023",zone=Zone.DECK)
        body=play(p,cid)
        live_p=[m for m in p.field if m.id==own.id]; live_e=[m for m in e.field if m.id==enemy.id]
        observed=f"own={own.zone.name};enemy={enemy.zone.name};own_field={[m.id for m in live_p]};enemy_field={[m.id for m in live_e]};body={body.zone.name}"
        return check(body.zone==Zone.PLAY and own.zone==Zone.PLAY and enemy.zone==Zone.PLAY and len(live_p)==len(live_e)==1,observed)
    def non_dragons_stay_in_hand():
        g,p,e=game()
        own=p.card(WISP,zone=Zone.DECK); enemy=e.card("CS2_182",zone=Zone.DECK)
        play(p,cid)
        observed=f"own={own.zone.name};enemy={enemy.zone.name};hand={[c.id for c in p.hand]}/{[c.id for c in e.hand]}"
        return check(own.zone==Zone.HAND and enemy.zone==Zone.HAND,observed)
    audit(cid,[("both_players_draw_and_summon_dragons","Both players draw their top Dragon and summon it to their own board.",both_dragons_summoned,"One Dragon is placed atop each deck; inspect both field owners and zones."),
               ("both_players_keep_non_dragons_in_hand","Both players draw non-Dragons without summoning them.",non_dragons_stay_in_hand,"Non-Dragon control verifies draw remains in hand.")])


def depth_charge():
    cid="DRG_078"
    def start_turn_hits_every_minion_only():
        g,p,e=game()
        own=p.summon("CS2_182"); enemy=e.summon("CS2_182"); body=play(p,cid)
        h1,h2=p.hero.health,e.hero.health
        g.end_turn(); g.end_turn()
        observed=f"own={own.health}/{own.zone.name};enemy={enemy.health}/{enemy.zone.name};depth={body.health}/{body.zone.name};heroes={p.hero.health},{e.hero.health}"
        return check(own.zone==Zone.GRAVEYARD and enemy.zone==Zone.GRAVEYARD and body.zone==Zone.GRAVEYARD and p.hero.health==h1 and e.hero.health==h2,observed)
    audit(cid,[("next_own_turn_deals_five_to_all_minions","At the start of its controller's next turn, Depth Charge deals 5 damage to every minion, including itself, but no hero.",start_turn_hits_every_minion_only,"End both turns to trigger the delayed OWN_TURN_BEGIN effect; board bodies have 5 or less health.")])


def evasive_wyrm():
    cid="DRG_079"
    def rush_divine_shield_and_spell_protection():
        g,p,e=game()
        wyrm=e.summon(cid); victim=e.summon("CS2_182")
        before=(wyrm.health,wyrm.divine_shield,p.used_mana)
        fireball=p.give("CS2_029")
        try:
            fireball.play(target=wyrm)
            rejected=False
        except InvalidAction:
            rejected=True
        legal=p.give("CS2_029"); legal.play(target=victim)
        try:
            p.hero.power.use(target=wyrm)
            power_rejected=False
        except InvalidAction:
            power_rejected=True
        observed=f"atk={wyrm.atk};rush={wyrm.rush};shield_before={before[1]};shield_after={wyrm.divine_shield};spell_rejected={rejected};power_rejected={power_rejected};wyrm_health={wyrm.health};victim={victim.health}/{victim.zone.name};mana={p.used_mana}"
        return check(wyrm.atk==5 and wyrm.rush and before[1] and rejected and power_rejected and wyrm.health==before[0] and wyrm.divine_shield==before[1] and victim.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("rush_divine_shield_and_target_protection","Evasive Wyrm has Rush and Divine Shield; targeted Fireball and Mage Hero Power are rejected on it while a separate Fireball resolves against a legal Yeti.",rush_divine_shield_and_spell_protection,"Use Mage Fireballs/Hero Power as valid targeted effects and a separate Yeti control; inspect Rush, Shield, health, and target rejection.")])


def scalerider():
    cid="DRG_081"
    def dragon_held_enables_targeted_two_damage():
        g,p,e=game(); target=e.summon("CS2_182"); dragon=p.give("DRG_079")
        body=play(p,cid,target=target)
        observed=f"held={dragon.zone.name};target={target.health}/{target.zone.name};body={body.atk}/{body.health}/{body.zone.name}"
        return check(dragon.zone==Zone.HAND and target.health==3 and body.zone==Zone.PLAY,observed)
    def absent_dragon_leaves_target_untouched():
        g,p,e=game(); target=e.summon("CS2_182"); body=play(p,cid)
        observed=f"hand={[c.id for c in p.hand]};target={target.health};body={body.zone.name}"
        return check(target.health==5 and body.zone==Zone.PLAY,observed)
    audit(cid,[("holding_dragon_deals_two_to_target","With a Dragon in hand, Battlecry deals 2 to a selected enemy minion.",dragon_held_enables_targeted_two_damage,"Dragon held in actual hand; target health and body zone asserted."),
               ("without_dragon_battlecry_does_not_damage","Without a Dragon, the Battlecry's damage condition is inactive.",absent_dragon_leaves_target_untouched,"No Dragon in hand; enemy Yeti is available as the control target.")])


def kobold_stickyfinger():
    cid="DRG_082"
    def opponent_weapon_moves_to_controller():
        g,p,e=game(); g.end_turn()
        weapon=play(e,"CS2_091"); g.end_turn()
        stolen=play(p,cid)
        observed=f"original={weapon.id}/{weapon.zone.name}/controller={weapon.controller==p};p_weapon={p.weapon.id if p.weapon else None};e_weapon={e.weapon};body={stolen.zone.name}"
        return check(p.weapon is weapon and weapon.controller is p and e.weapon is None and stolen.zone==Zone.PLAY,observed)
    def no_opponent_weapon_is_safe():
        g,p,e=game(); body=play(p,cid)
        observed=f"p_weapon={p.weapon};e_weapon={e.weapon};body={body.zone.name}"
        return check(p.weapon is None and e.weapon is None and body.zone==Zone.PLAY,observed)
    audit(cid,[("steals_equipped_opponent_weapon","Battlecry transfers the opponent's equipped Fiery War Axe to the player and leaves the opponent unarmed.",opponent_weapon_moves_to_controller,"Equip via opponent's real weapon play, return turn, then assert ownership and both weapon slots."),
               ("no_weapon_battlecry_does_not_create_weapon","With no enemy weapon, Stickyfinger only enters play.",no_opponent_weapon_is_safe,"Empty weapon-slot control.")])


def tentacled_menace():
    cid="DRG_084"
    def both_draw_and_costs_swap():
        g,p,e=game(); own=p.card("CS2_182",zone=Zone.DECK); enemy=e.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        observed=f"own={own.id}:{own.zone.name}:cost{own.cost};enemy={enemy.id}:{enemy.zone.name}:cost{enemy.cost};body={body.zone.name}"
        return check(own.zone==Zone.HAND and enemy.zone==Zone.HAND and own.cost==0 and enemy.cost==4 and body.zone==Zone.PLAY,observed)
    audit(cid,[("each_player_draws_and_swaps_drawn_cost","Each player draws one card; the Yeti's cost 4 and Wisp's cost 0 are swapped between the drawn cards.",both_draw_and_costs_swap,"Top deck cards have known costs; assert ownership, hand zones, and swapped costs after Battlecry.")])


def chromatic_egg():
    cid="DRG_086"
    def choice_is_stored_and_hatches_on_death():
        g,p,e=game(); egg=play(p,cid); choice=p.choice
        opts=list(choice.cards); chosen=opts[0]; chosen_id=chosen.id
        choice.choose(chosen)
        no_reveal=not any(c.id==chosen_id for c in p.hand)
        egg.destroy()
        hatched=[m for m in p.field if m.id==chosen_id]
        observed=f"options={[c.id for c in opts]};chosen={chosen_id};no_reveal={no_reveal};egg={egg.zone.name};hatched={[(m.id,m.atk,m.health,m.zone.name) for m in hatched]}"
        return check(len(opts)==3 and no_reveal and egg.zone==Zone.GRAVEYARD and len(hatched)==1 and hatched[0].zone==Zone.PLAY,observed)
    audit(cid,[("discover_secret_dragon_then_hatch_on_death","Chromatic Egg offers a secret Dragon choice, does not put it in hand, and summons the chosen Dragon when the Egg dies.",choice_is_stored_and_hatches_on_death,"Resolve real Discover choice, verify no reveal/hand add, kill Egg, and inspect summoned chosen identity.")])


def dragonqueen_alexstrasza():
    cid="DRG_089"
    def no_duplicates_adds_two_other_one_cost_dragons():
        g,p,e=game(); body=play(p,cid)
        dragons=[c for c in p.hand if c.race==Race.DRAGON]
        observed=f"body={body.zone.name};hand={[(c.id,c.cost,c.race,c.zone.name) for c in p.hand]}"
        return check(body.zone==Zone.PLAY and len(dragons)==2 and all(c.id!=cid and c.cost==1 and c.zone==Zone.HAND for c in dragons),observed)
    def duplicate_deck_disables_battlecry():
        g,p,e=game(); p.card(WISP,zone=Zone.DECK);p.card(WISP,zone=Zone.DECK)
        body=play(p,cid)
        observed=f"body={body.zone.name};deck={[c.id for c in p.deck]};hand={[c.id for c in p.hand]}"
        return check(body.zone==Zone.PLAY and len(p.hand)==0,observed)
    audit(cid,[("singleton_deck_adds_two_other_dragons_at_one_cost","With no duplicates in deck, add exactly two Dragon cards other than Dragonqueen, each costing 1.",no_duplicates_adds_two_other_one_cost_dragons,"Empty-deck singleton branch; verify class race, cost, count, and exclusion of self."),
               ("duplicate_deck_prevents_added_dragons","A duplicate pair in deck disables the Battlecry and adds no Dragons.",duplicate_deck_disables_battlecry,"Two identical Wisp cards make the deck non-singleton; check no generated hand cards.")])


def murozond_the_infinite():
    cid="DRG_090"
    def replays_previous_turn_cards():
        g,p,e=game()
        p.give(WISP).play(); p.give("DS1_233").play(); p.give("ICC_481").play()
        g.end_turn(); body=play(e,cid)
        observed=f"enemy_field={[m.id for m in e.field]};p_damaged={p.hero.damaged_this_turn};e_hero={e.hero.id};body={body.zone.name}"
        return check(any(m.id==WISP for m in e.field) and p.hero.damaged_this_turn==5 and e.hero.id=="ICC_481" and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_replays_opponent_previous_turn_cards","Battlecry replays an opponent minion, damage spell, and hero card played on the immediately preceding turn.",replays_previous_turn_cards,"Replicate existing test_dragons.py scenario and assert summoned minion, 5 hero damage, transformed hero, and Murozond zone.")])


def shuma():
    cid="DRG_091"
    def end_turn_fills_open_slots_with_tentacles():
        g,p,e=game(); body=play(p,cid); p.summon(WISP); p.summon("CS2_182")
        g.end_turn()
        tentacles=[m for m in p.field if m.id=="DRG_091t"]
        observed=f"field={[(m.id,m.atk,m.health,m.zone.name) for m in p.field]};tentacles={len(tentacles)}"
        return check(len(p.field)==7 and len(tentacles)==4 and all((m.atk,m.health)==(1,1) for m in tentacles) and body.zone==Zone.PLAY,observed)
    audit(cid,[("end_of_turn_summons_tentacles_to_board_limit","At end of turn, Shu'ma fills the four open board slots with 1/1 Tentacles, reaching seven friendly minions.",end_turn_fills_open_slots_with_tentacles,"Start with Shu'ma plus two other friendly minions; trigger actual turn-end event and count tokens/stats.")])


def transmogrifier():
    cid="DRG_092"
    def drawn_card_becomes_legendary_minion():
        g,p,e=game(); source=p.card(WISP,zone=Zone.DECK); body=play(p,cid); drawn=p.draw()
        transformed=p.hand[0] if p.hand else None
        observed=f"source={source.id}/{source.zone.name};draw_return={drawn.id}/{drawn.zone.name};hand={[(c.id,CardType(c.type).name,Rarity(c.rarity).name,c.atk,c.health,c.zone.name) for c in p.hand]};body={body.zone.name}"
        return check(source.zone==Zone.SETASIDE and transformed is not None and transformed.id!=WISP and CardType(transformed.type)==CardType.MINION and Rarity(transformed.rarity)==Rarity.LEGENDARY and transformed.zone==Zone.HAND and body.zone==Zone.PLAY,observed)
    audit(cid,[("draw_transforms_card_into_random_legendary_minion","A card drawn while Transmogrifier is alive becomes a Legendary minion in hand instead of the deck's Wisp.",drawn_card_becomes_legendary_minion,"Draw from a known Wisp and assert the transformed object's identity, type, rarity, and hand zone.")])


def veranus():
    cid="DRG_095"
    def sets_all_enemy_minion_health_to_one():
        g,p,e=game(); friendly=p.summon("CS2_182"); a=e.summon("CS2_182"); b=e.summon("CFM_900"); body=play(p,cid)
        observed=f"friendly={friendly.health}/{friendly.max_health};enemy={[(m.id,m.health,m.max_health,m.zone.name) for m in (a,b)]};body={body.zone.name}"
        return check(friendly.health==5 and friendly.max_health==5 and all(m.health==1 and m.max_health==1 for m in (a,b)) and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_sets_enemy_minion_health_to_one","Battlecry sets both enemy minions' maximum and current Health to 1 while leaving a friendly Yeti unchanged.",sets_all_enemy_minion_health_to_one,"Use injured/high-health enemy bodies and a friendly control; inspect both current and maximum Health.")])


def bandersmosh():
    cid="DRG_096"
    def hand_card_transforms_on_own_turn_start():
        g,p,e=game(); old=p.give(cid); g.end_turn();g.end_turn()
        live=[c for c in p.hand if c is old or c.zone==Zone.HAND]
        observed=f"old={old.id}/{old.zone.name};hand={[(c.id,c.atk,c.health,Rarity(c.rarity).name,c.zone.name) for c in p.hand]}"
        return check(len(p.hand)==1 and live and p.hand[0].id!=cid and p.hand[0].atk==5 and p.hand[0].health==5 and Rarity(p.hand[0].rarity)==Rarity.LEGENDARY,observed)
    audit(cid,[("in_hand_bandersmosh_morphs_into_5_5_legendary","At the start of its controller's turn, Bandersmosh in hand becomes a random Legendary minion with 5/5 stats.",hand_card_transforms_on_own_turn_start,"Keep it in hand through an opponent turn, trigger next own turn, then inspect transformed Legendary identity and stats. Source uses Buff(Morph.CARD, DRG_096e), while the 5/5 override is declared on DRG_096e2; observed Legendary BT_255 remains 4/7.")])


def kronx_dragonhoof():
    cid="DRG_099"
    def draws_galakrond_from_deck():
        g,p,e=game(); gal=p.card("DRG_650",zone=Zone.DECK);body=play(p,cid)
        observed=f"galakrond={gal.zone.name};body={body.zone.name};hand={[c.id for c in p.hand]}"
        return check(gal.zone==Zone.HAND and body.zone==Zone.PLAY,observed)
    def galakrond_hero_offers_and_resolves_devastation():
        g,p,e=game(); gal=p.summon("DRG_650"); wisp=p.summon(WISP); body=play(p,cid); choice=p.choice
        if choice: choice.choose(choice.cards[2])
        observed=f"hero={p.hero.id};choice_open={p.choice is not None};wisp={wisp.atk}/{wisp.health}/{wisp.zone.name};kronx={body.atk}/{body.health}/{body.zone.name}"
        return check(choice is not None and p.choice is None and wisp.atk==3 and wisp.health==3 and body.atk==6 and body.health==6,observed)
    audit(cid,[("finds_galakrond_in_deck","If Galakrond remains in deck, Kronx draws that exact card.",draws_galakrond_from_deck,"Known Galakrond is sole card in deck; check it reaches hand."),
               ("galakrond_mode_selects_devastation","If Galakrond is already active, choose Domination and give other minions +2/+2.",galakrond_hero_offers_and_resolves_devastation,"Use the actual choice object and verify selected devastation's board effect.")])


def azure_explorer():
    cid="DRG_102"
    def battlecry_discovers_dragon_and_spell_damage_is_two():
        g,p,e=game(); body=play(p,cid); choice=p.choice; options=list(choice.cards)
        choice.choose(options[0])
        observed=f"options={[(c.id,c.race,c.type) for c in options]};selected={p.hand[-1].id if p.hand else None};spell_damage_1={p.get_spell_damage(1)};body={body.zone.name}"
        return check(len(options)==3 and all(c.race==Race.DRAGON for c in options) and p.get_spell_damage(1)==3 and body.zone==Zone.PLAY,observed)
    audit(cid,[("discover_dragon_and_spell_damage_two","Azure Explorer's Battlecry discovers a Dragon, and its live Spell Damage +2 increases a 1-damage spell to 3.",battlecry_discovers_dragon_and_spell_damage_is_two,"Resolve one real Discover choice, inspect all option races, and query computed spell damage while Explorer is on board.")])


def chenvaala():
    cid="DRG_104"
    def reward_triggers_after_third_spell_only():
        g,p,e=game(); body=play(p,cid); spells=[]
        for _ in range(2): spells.append(play(p,"EX1_277"))
        after_two=[m for m in p.field if m.id=="DRG_104t2"]
        spells.append(play(p,"EX1_277"))
        elementals=[m for m in p.field if m.id=="DRG_104t2"]
        observed=f"after_two={len(after_two)};after_three={[(m.atk,m.health,m.zone.name) for m in elementals]};enemy_hero={e.hero.health};body={body.zone.name};spells={[s.zone.name for s in spells]};mana={p.used_mana}"
        return check(not after_two and len(elementals)==1 and (elementals[0].atk,elementals[0].health)==(5,5) and all(s.zone==Zone.GRAVEYARD for s in spells),observed)
    audit(cid,[("after_three_spells_summons_five_five_elemental","The first two spells do not reward; the third spell cast in the same turn summons one 5/5 Elemental.",reward_triggers_after_third_spell_only,"Cast three actual Fireballs in one turn with a valid enemy hero target; inspect threshold and damage resolution.")])


def arcane_breath():
    cid="DRG_106"
    def dragon_branch_discovers_spells_and_deals_two():
        g,p,e=game(); target=e.summon("CS2_182"); dragon=p.give("DRG_079"); spell=play(p,cid,target=target); choice=p.choice
        options=list(choice.cards) if choice else []
        if choice: choice.choose(options[0])
        observed=f"dragon={dragon.zone.name};target={target.health}/{target.zone.name};options={[(c.id,CardType(c.type).name,c.race) for c in options]};spell={spell.zone.name};choice={p.choice is not None}"
        return check(target.health==3 and len(options)==3 and all(CardType(c.type)==CardType.SPELL for c in options) and p.choice is None,observed)
    def no_dragon_still_deals_two_without_discover():
        g,p,e=game(); target=e.summon("CS2_182"); spell=play(p,cid,target=target)
        observed=f"target={target.health};choice={p.choice};spell={spell.zone.name};hand={[c.id for c in p.hand]}"
        return check(target.health==3 and p.choice is None and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("holding_dragon_adds_spell_discover_after_two_damage","With Dragon in hand, Arcane Breath deals 2 to the selected minion and offers three Spell cards to Discover.",dragon_branch_discovers_spells_and_deals_two,"Confirm all actual Discover options are Spells, not merely any cards, and target loses exactly 2. Source line uses DISCOVER(RandomDragon()); observed all three options are Dragon MINIONs and no choice resolves."),
               ("without_dragon_only_two_damage","Without a Dragon, Arcane Breath still deals 2 but opens no Discover choice.",no_dragon_still_deals_two_without_discover,"No Dragon control; inspect target health, choice state, and consumed spell zone.")])


def violet_spellwing():
    cid="DRG_107"
    def deathrattle_adds_arcane_missiles():
        g,p,e=game(); body=p.summon(cid); body.destroy()
        missiles=[c for c in p.hand if c.id=="EX1_277"]
        observed=f"body={body.zone.name};hand={[(c.id,CardType(c.type).name,c.zone.name) for c in p.hand]};missiles={len(missiles)}"
        return check(body.zone==Zone.GRAVEYARD and len(missiles)==1 and CardType(missiles[0].type)==CardType.SPELL and missiles[0].zone==Zone.HAND,observed)
    audit(cid,[("deathrattle_adds_arcane_missiles_to_hand","When Violet Spellwing dies, its Deathrattle adds one Arcane Missiles spell to hand.",deathrattle_adds_arcane_missiles,"Summon then destroy the actual minion and assert exact generated card id/type/zone.")])


def mana_giant():
    cid="DRG_109"
    def outside_deck_play_reduces_cost():
        g,p,e=game(); giant=p.give(cid); base=giant.cost
        played=play(p,WISP); after=giant.cost
        observed=f"base={base};played={played.id}/{played.zone.name};cost_after_one_outside_card={after};giant_zone={giant.zone.name}"
        return check(base==8 and played.zone==Zone.PLAY and after==7 and giant.zone==Zone.HAND,observed)
    audit(cid,[("each_played_outside_deck_card_reduces_cost","After one card created outside the deck is actually played, Mana Giant's cost falls from its base 8 to 7.",outside_deck_play_reduces_cost,"Card definition base cost is 8; give Mana Giant and a Wisp from outside the deck, play Wisp, and inspect live Giant cost.")])


def crazed_netherwing():
    cid="DRG_201"
    def dragon_branch_hits_every_other_character():
        g,p,e=game(); friendly=p.summon("CS2_182"); hostile=e.summon("CS2_182"); dragon=p.give("DRG_079"); body=play(p,cid)
        observed=f"dragon={dragon.zone.name};heroes={p.hero.health},{e.hero.health};friendly={friendly.health};hostile={hostile.health};body={body.health}/{body.zone.name}"
        return check(p.hero.health==27 and e.hero.health==27 and friendly.health==2 and hostile.health==2 and body.health==5 and body.zone==Zone.PLAY,observed)
    def no_dragon_leaves_characters_unchanged():
        g,p,e=game(); friendly=p.summon("CS2_182"); hostile=e.summon("CS2_182"); body=play(p,cid)
        observed=f"heroes={p.hero.health},{e.hero.health};friendly={friendly.health};hostile={hostile.health};body={body.health}"
        return check(p.hero.health==30 and e.hero.health==30 and friendly.health==5 and hostile.health==5 and body.zone==Zone.PLAY,observed)
    audit(cid,[("holding_dragon_deals_three_to_all_other_characters","With a Dragon in hand, Crazed Netherwing deals 3 to both heroes and every other minion, not itself.",dragon_branch_hits_every_other_character,"Set up a Dragon in hand, both heroes and two minions; inspect all damage and self-exclusion."),
               ("without_dragon_no_splash_damage","Without a Dragon in hand, the conditional area damage does not resolve.",no_dragon_leaves_characters_unchanged,"No Dragon control; verify both heroes, both Yeti bodies, and Netherwing health.")])


def dragonblight_cultist():
    cid="DRG_202"
    def invokes_and_scales_attack_by_other_friends():
        g,p,e=game(CardClass.WARLOCK); p.card("DRG_600",zone=Zone.DECK); one=p.summon(WISP); two=p.summon("CS2_182"); body_card=p.give(cid); base=body_card.atk; body_card.play()
        others=[m for m in p.field if m is not body_card]
        observed=f"invoke={p.invoke_counter};base={base};atk_after={body_card.atk};other_friends={[(m.id,m.atk,m.health) for m in others]};body={body_card.zone.name}"
        return check(p.invoke_counter==1 and body_card.atk==base+len(others) and len(others)>=2 and body_card.zone==Zone.PLAY,observed)
    audit(cid,[("invoke_once_and_gain_attack_per_other_friendly_minion","Battlecry invokes Galakrond once and gains exactly +1 Attack for every other friendly minion present when the scaling effect resolves.",invokes_and_scales_attack_by_other_friends,"Count all other friendly minions after the Invoke action (including Invoke-generated minions), compare attack against base+count, and assert Invoke counter.")])


def veiled_worshipper():
    cid="DRG_203"
    def two_real_invokes_draw_three_cards():
        g,p,e=game(CardClass.WARLOCK); p.card("DRG_600",zone=Zone.DECK); cards=[p.card(x,zone=Zone.DECK) for x in (WISP,"CS2_182","DRG_079")]
        play(p,"DRG_303");play(p,"DRG_303"); count=p.invoke_counter; body=play(p,cid)
        observed=f"invoke={count};drawn={[(c.id,c.zone.name) for c in cards]};hand={[c.id for c in p.hand]};body={body.zone.name}"
        return check(count>=2 and all(c.zone==Zone.HAND for c in cards) and body.zone==Zone.PLAY,observed)
    def fewer_than_two_invokes_draw_nothing():
        g,p,e=game(CardClass.WARLOCK); p.card("DRG_600",zone=Zone.DECK); card=p.card(WISP,zone=Zone.DECK); play(p,"DRG_303"); body=play(p,cid)
        observed=f"invoke={p.invoke_counter};card={card.zone.name};hand={[c.id for c in p.hand]};body={body.zone.name}"
        return check(p.invoke_counter==1 and card.zone==Zone.DECK and body.zone==Zone.PLAY,observed)
    audit(cid,[("twice_invoked_battlecry_draws_three","After two actual Invoke cards, Veiled Worshipper draws three known deck cards.",two_real_invokes_draw_three_cards,"Use two actual Invoke Battlecries and three known deck cards; inspect exact drawn zones."),
               ("single_invoke_does_not_draw","After only one actual Invoke, Worshipper leaves the known top card in deck.",fewer_than_two_invokes_draw_nothing,"Single-Invoke branch control.")])


def dark_skies():
    cid="DRG_204"
    def base_hit_occurs_with_empty_remaining_hand():
        g,p,e=game(); minion=e.summon("CFM_900"); before=minion.health; spell=play(p,cid); damage=before-minion.health
        observed=f"before={before};after={minion.health};damage={damage};target_zone={minion.zone.name};hand={len(p.hand)};spell={spell.zone.name}"
        return check(damage==1 and minion.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,observed)
    def repeats_once_per_other_hand_card():
        g,p,e=game(); minion=e.summon("CFM_900"); before=minion.health; p.give(WISP);p.give("CS2_182");spell=play(p,cid); damage=before-minion.health
        observed=f"before={before};after={minion.health};damage={damage};target_zone={minion.zone.name};remaining_hand={[c.id for c in p.hand]};spell={spell.zone.name}"
        return check(damage==3 and minion.zone==Zone.PLAY and len(p.hand)==2 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("one_base_random_minion_damage_without_other_hand_cards","With no other cards in hand after casting, Dark Skies should deal only its base 1 random minion damage.",base_hit_occurs_with_empty_remaining_hand,"Sole enemy minion guarantees the random target; this branch checks the base hit with an empty remaining hand."),
               ("extra_hand_cards_repeat_damage","With two other cards remaining after casting, Dark Skies should deal 3 total damage: the base hit plus one repeat per remaining card.",repeats_once_per_other_hand_card,"Two known cards remain in hand; sole minion means repeated random hits must land there.")])


def nether_breath():
    cid="DRG_205"
    def dragon_upgrades_damage_and_lifesteal():
        g,p,e=game(); play(p,"CS2_029",target=p.hero); dragon=p.give("DRG_079"); spell=play(p,cid,target=e.hero)
        observed=f"dragon={dragon.zone.name};heroes={p.hero.health},{e.hero.health};lifesteal={spell.lifesteal};spell={spell.zone.name}"
        return check(p.hero.health==28 and e.hero.health==26 and spell.zone==Zone.GRAVEYARD,observed)
    def no_dragon_deals_two_without_lifesteal():
        g,p,e=game(); play(p,"CS2_029",target=p.hero); spell=play(p,cid,target=e.hero)
        observed=f"heroes={p.hero.health},{e.hero.health};lifesteal={spell.lifesteal};spell={spell.zone.name}"
        return check(p.hero.health==24 and e.hero.health==28 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("holding_dragon_deals_four_with_lifesteal","With a Dragon held, Nether Breath deals 4 and Lifesteal restores 4 to a damaged hero.",dragon_upgrades_damage_and_lifesteal,"Target enemy hero, measure 4 damage and 4 heal, and inspect Lifesteal on resolving spell."),
               ("without_dragon_deals_two_without_heal","Without a Dragon, Nether Breath deals 2 and grants no Lifesteal healing.",no_dragon_deals_two_without_lifesteal,"Damaged hero plus enemy hero target isolate damage and healing branch.")])


def rain_of_fire():
    cid="DRG_206"
    def damages_both_heroes_and_all_minions():
        g,p,e=game(); own=p.summon(WISP); hostile=e.summon(WISP); spell=play(p,cid)
        observed=f"heroes={p.hero.health},{e.hero.health};own={own.zone.name};hostile={hostile.zone.name};spell={spell.zone.name}"
        return check(p.hero.health==29 and e.hero.health==29 and own.zone==Zone.GRAVEYARD and hostile.zone==Zone.GRAVEYARD and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("one_damage_to_all_characters","Rain of Fire deals exactly 1 to both heroes and all minions, killing both 1-health Wisps.",damages_both_heroes_and_all_minions,"Use both heroes and one Wisp per side to exercise the all-characters scope.")])


def abyssal_summoner():
    cid="DRG_207"
    def demon_stats_equal_remaining_hand_size():
        g,p,e=game(); fillers=[p.give(x) for x in (WISP,"CS2_182","DRG_079")]; body=play(p,cid)
        demons=[m for m in p.field if m.id=="DRG_207t"]
        observed=f"remaining_hand={len(p.hand)}:{[c.id for c in p.hand]};demons={[(m.atk,m.health,m.taunt,m.race,m.zone.name) for m in demons]};body={body.zone.name}"
        return check(len(p.hand)==3 and len(demons)==1 and (demons[0].atk,demons[0].health)==(3,3) and demons[0].taunt and demons[0].race==Race.DEMON and demons[0].zone==Zone.PLAY and body.zone==Zone.PLAY,observed)
    audit(cid,[("summons_taunt_demon_with_stats_equal_to_hand","With three other cards remaining in hand, Battlecry summons a 3/3 Demon with Taunt.",demon_stats_equal_remaining_hand_size,"Cards are in hand before the minion Battlecry; assert remaining hand count, Demon race, stats, Taunt, and zone.")])


def valdris_felgorge():
    cid="DRG_208"
    def raises_hand_limit_and_draws_four():
        g,p,e=game(); cards=[p.card(x,zone=Zone.DECK) for x in (WISP,"CS2_182","DRG_079","NEW1_023")];body=play(p,cid)
        observed=f"max_hand={p.max_hand_size};drawn={[(c.id,c.zone.name) for c in cards]};hand={len(p.hand)};body={body.zone.name}"
        return check(p.max_hand_size==12 and all(c.zone==Zone.HAND for c in cards) and len(p.hand)==4 and body.zone==Zone.PLAY,observed)
    audit(cid,[("increase_hand_limit_to_twelve_and_draw_four","Valdris changes the maximum hand size to 12 and draws all four known deck cards.",raises_hand_limit_and_draws_four,"Four known deck cards isolate draw count; inspect max-hand-size and exact hand zones.")])


def zzeraku_the_warped():
    cid="DRG_209"
    def opponent_spell_damage_summons_one_six_six():
        g,p,e=game(); body=play(p,cid);g.end_turn();spell=play(e,"CS2_029",target=p.hero)
        drakes=[m for m in p.field if m.id=="DRG_209t"]
        observed=f"own_hero={p.hero.health};drakes={[(m.atk,m.health,m.zone.name) for m in drakes]};body={body.zone.name};spell={spell.zone.name}"
        return check(p.hero.health==24 and len(drakes)==1 and (drakes[0].atk,drakes[0].health)==(6,6) and body.zone==Zone.PLAY,observed)
    audit(cid,[("whenever_hero_takes_damage_summon_six_six_drake","A single enemy Fireball damaging the controller's hero triggers one 6/6 Nether Drake.",opponent_spell_damage_summons_one_six_six,"Play Zzeraku, pass turn, and resolve enemy Fireball at its controller's hero; inspect damage event and token stats.")])


def twin_tyrant():
    cid="DRG_213"
    def two_four_damage_hits_land_on_enemy_minions():
        g,p,e=game(); targets=[e.summon("EX1_561") for _ in range(3)];before=[m.health for m in targets];body=play(p,cid)
        losses=[old-m.health for old,m in zip(before,targets)]
        observed=f"before={before};after={[(m.health,m.zone.name) for m in targets]};losses={losses};body={body.zone.name}"
        return check(sum(losses)==8 and all(m.zone==Zone.PLAY for m in targets) and all(loss in (0,4,8) for loss in losses) and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_deals_two_four_damage_enemy_minion_hits","Battlecry deals two independently random 4-damage hits among enemy minions; three 12-health Malygos targets survive and take 8 total damage.",two_four_damage_hits_land_on_enemy_minions,"Use three high-health enemy minions so repeated selection of one target cannot be mistaken for missing hits; sum health deltas.")])


def storms_wrath():
    cid="DRG_215"
    def buffs_friendly_minions_and_overloads_one():
        g,p,e=game(CardClass.SHAMAN); own1=p.summon(WISP);own2=p.summon("CS2_182");hostile=e.summon(WISP)
        before=[(m.atk,m.health) for m in (own1,own2,hostile)];spell=play(p,cid)
        g.end_turn();g.end_turn()
        observed=f"before={before};after={[(m.atk,m.health) for m in (own1,own2,hostile)]};overload_locked={p.overload_locked};overloaded_owed={p.overloaded};spell={spell.zone.name}"
        return check((own1.atk,own1.health)==(2,2) and (own2.atk,own2.health)==(5,6) and (hostile.atk,hostile.health)==before[2] and p.overload_locked==1 and p.overloaded==0 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("friendly_minions_gain_one_one_and_overload_locks_next_turn","Storm's Wrath gives each friendly minion +1/+1, leaves enemy minion unchanged, and its Overload (1) locks one crystal on the controller's next turn.",buffs_friendly_minions_and_overloads_one,"Use two friendly minions and one enemy control; assert stats and spell zone, then end both turns and assert actual next-turn overload lock.")])


def surging_tempest():
    cid="DRG_216"
    def attack_aura_tracks_overloaded_crystals():
        g0,p0,e0=game(CardClass.SHAMAN);plain=p0.summon(cid);plain_atk=plain.atk;plain_base=plain.data.atk
        g,p,e=game(CardClass.SHAMAN);spell=play(p,"DRG_215");g.end_turn();g.end_turn();body=p.summon(cid);overloaded_atk=body.atk;base=body.data.atk
        observed=f"plain_attack={plain_atk}/{plain_base};source_spell={spell.zone.name};locked={p.overload_locked};owed={p.overloaded};overloaded_attack={overloaded_atk}/{base};body={body.zone.name}"
        return check(plain_atk==plain_base and p.overload_locked==1 and overloaded_atk==base+1 and body.zone==Zone.PLAY,observed)
    audit(cid,[("plus_one_attack_with_real_locked_crystal","Surging Tempest has base Attack without overload, then +1 Attack after a real Overload (1) is carried into its controller's next turn.",attack_aura_tracks_overloaded_crystals,"Compare a no-overload fixture with a second match where Storm's Wrath creates a real pending overload, pass both turns, and summon during the actual locked-mana turn.")])


def dragons_pack():
    cid="DRG_217"
    def no_invoke_summons_two_base_taunt_wolves():
        g,p,e=game(CardClass.SHAMAN);spell=play(p,cid);wolves=[m for m in p.field if m.id=="DRG_217t"]
        observed=f"wolves={[(m.atk,m.health,m.taunt,m.zone.name) for m in wolves]};spell={spell.zone.name}"
        return check(len(wolves)==2 and all((m.atk,m.health)==(2,3) and m.taunt and m.zone==Zone.PLAY for m in wolves),observed)
    def two_actual_invokes_upgrade_both_wolves():
        g,p,e=game(CardClass.SHAMAN);p.card("DRG_620",zone=Zone.DECK)
        play(p,"DRG_248",target=e.hero);play(p,"DRG_248",target=e.hero);counter=p.invoke_counter;spell=play(p,cid)
        wolves=[m for m in p.field if m.id=="DRG_217t"]
        observed=f"invoke={counter};wolves={[(m.atk,m.health,m.taunt,m.zone.name) for m in wolves]};spell={spell.zone.name}"
        return check(counter==2 and len(wolves)==2 and all((m.atk,m.health)==(4,5) and m.taunt and m.zone==Zone.PLAY for m in wolves),observed)
    audit(cid,[("base_pack_summons_two_two_three_taunts","Without Invoke, Dragon's Pack summons exactly two 2/3 Taunt Spirit Wolves.",no_invoke_summons_two_base_taunt_wolves,"No Invoke branch; count tokens and assert their stats, Taunt, and zone."),
               ("twice_invoked_pack_gives_two_two","After two actual Shaman Invoke spells, both summoned Spirit Wolves are 4/5 Taunts.",two_actual_invokes_upgrade_both_wolves,"Invoke using real targeted spells with Shaman Galakrond in deck, then inspect count and both upgraded token stats.")])


def corrupt_elementalist():
    cid="DRG_218"
    def battlecry_invokes_twice():
        g,p,e=game(CardClass.SHAMAN);gal=p.card("DRG_620",zone=Zone.DECK);body=play(p,cid)
        evolved=[c for c in p.deck if c.id=="DRG_620t2"]
        observed=f"invoke_counter={p.invoke_counter};original_galakrond={gal.zone.name};evolved_in_deck={[c.id for c in evolved]};field={[(m.id,m.atk,m.health) for m in p.field]};body={body.zone.name}"
        return check(p.invoke_counter==2 and len(evolved)==1 and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_invokes_galakrond_twice","Corrupt Elementalist performs two real Invokes, increments its controller's counter by two, and upgrades deck Galakrond to its second stage.",battlecry_invokes_twice,"Use Shaman Galakrond in deck; assert invocation counter, evolved live deck entity (the original object is stale after Morph), and played body.")])


def lightning_breath():
    cid="DRG_219"
    def dragon_branch_hits_target_and_both_neighbors():
        g,p,e=game(CardClass.SHAMAN);left=e.summon("CFM_900");center=e.summon("CFM_900");right=e.summon("CFM_900");dragon=p.give("DRG_079");spell=play(p,cid,target=center)
        observed=f"dragon={dragon.zone.name};health={[m.health for m in (left,center,right)]};zones={[m.zone.name for m in (left,center,right)]};spell={spell.zone.name}"
        return check(all(m.health==1 and m.zone==Zone.PLAY for m in (left,center,right)) and spell.zone==Zone.GRAVEYARD,observed)
    def no_dragon_only_hits_selected_minion():
        g,p,e=game(CardClass.SHAMAN);left=e.summon("CFM_900");center=e.summon("CFM_900");right=e.summon("CFM_900");spell=play(p,cid,target=center)
        observed=f"health={[m.health for m in (left,center,right)]};zones={[m.zone.name for m in (left,center,right)]};spell={spell.zone.name}"
        return check(left.health==5 and center.health==1 and right.health==5 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("holding_dragon_damages_target_and_adjacent_minions","With a Dragon held, Lightning Breath deals 4 to its chosen minion and both adjacent enemy minions.",dragon_branch_hits_target_and_both_neighbors,"Use exactly three adjacent 5-health enemy minions, so all survive with 1 health after the 4-damage spread."),
               ("without_dragon_only_target_takes_damage","Without a Dragon, only the chosen minion takes 4 damage; its neighbors are unchanged.",no_dragon_only_hits_selected_minion,"Same three-minion line without a Dragon isolates neighbor splash condition. Source requirements make targeting conditional on holding a Dragon, and the base Hit(TARGET, 4) resolves with no target; all three minions remain at 5 health.")])


def cumulo_maximus():
    cid="DRG_223"
    def overload_enables_targeted_five_damage():
        g,p,e=game(CardClass.SHAMAN);p.overload_locked=1;body=play(p,cid,target=e.hero)
        observed=f"overload={p.overload_locked};enemy_hero={e.hero.health};body={body.zone.name}"
        return check(e.hero.health==25 and body.zone==Zone.PLAY,observed)
    def no_overload_does_not_damage():
        g,p,e=game(CardClass.SHAMAN);body=play(p,cid,target=e.hero)
        observed=f"overload={p.overload_locked};enemy_hero={e.hero.health};body={body.zone.name}"
        return check(e.hero.health==30 and body.zone==Zone.PLAY,observed)
    audit(cid,[("overloaded_mana_deals_five_to_selected_target","With Overloaded Mana, Battlecry deals 5 to the selected enemy hero.",overload_enables_targeted_five_damage,"Set one real locked crystal, choose the enemy hero, and assert exact damage."),
               ("without_overload_no_damage","Without Overloaded Mana, the optional Battlecry target receives no damage.",no_overload_does_not_damage,"No overload control with the same valid target.")])


def nithogg():
    cid="DRG_224"
    def eggs_hatch_into_rush_drakes_next_own_turn():
        g,p,e=game(CardClass.SHAMAN);body=play(p,cid);eggs=[m for m in p.field if m.id=="DRG_224t"]
        before=[(m.atk,m.health,m.zone.name) for m in eggs];g.end_turn();g.end_turn()
        drakes=[m for m in p.field if m.id=="DRG_224t2"]
        observed=f"body={body.zone.name};eggs_before={before};live={[ (m.id,m.atk,m.health,m.rush,m.zone.name) for m in p.field]};drakes={len(drakes)}"
        return check(len(eggs)==2 and all(x[:2]==(0,3) for x in before) and len(drakes)==2 and all((m.atk,m.health,m.rush,m.zone)==(4,4,True,Zone.PLAY) for m in drakes),observed)
    audit(cid,[("summons_two_eggs_that_hatch_next_turn","Battlecry summons two 0/3 Eggs; at the start of the controller's next turn they become 4/4 Drakes with Rush.",eggs_hatch_into_rush_drakes_next_own_turn,"Inspect initial egg stats, end both turns to reach own next turn, then inspect new live Morph entities and Rush.")])


def sky_claw():
    cid="DRG_225"
    def buffs_other_mechs_and_summons_two_microcopters():
        g,p,e=game(CardClass.PALADIN);mech=p.summon("GVG_006");nonmech=p.summon("CS2_182");before=(mech.atk,mech.health,nonmech.atk);body=play(p,cid)
        tokens=[m for m in p.field if m.id=="DRG_225t"]
        observed=f"before={before};mech={(mech.atk,mech.health)};nonmech={nonmech.atk};tokens={[(m.atk,m.health,m.race,m.zone.name) for m in tokens]};body={body.zone.name}"
        return check(mech.atk==before[0]+1 and mech.health==before[1] and nonmech.atk==before[2] and len(tokens)==2 and all((m.atk,m.health)==(2,1) and m.zone==Zone.PLAY for m in tokens) and body.zone==Zone.PLAY,observed)
    audit(cid,[("other_mechs_gain_attack_and_two_microcopters_spawn","Sky Claw grants +1 Attack to another Mech and its two 1/1 Microcopters also receive that aura, while a non-Mech is unchanged.",buffs_other_mechs_and_summons_two_microcopters,"Use Annoy-o-Tron as a known Mech and Yeti as a non-Mech control; assert both spawned Microcopters are 2/1 under the live +1 Attack aura.")])


def amber_watcher():
    cid="DRG_226"
    def battlecry_restores_eight_health_to_selected_hero():
        g,p,e=game(CardClass.PALADIN);g.end_turn();play(e,"CS2_029",target=p.hero);play(e,"CS2_029",target=p.hero);before=p.hero.health;g.end_turn();body=play(p,cid,target=p.hero)
        observed=f"before={before};after={p.hero.health};body={body.zone.name};mana={p.used_mana}"
        return check(before==18 and p.hero.health==26 and body.zone==Zone.PLAY,observed)
    audit(cid,[("battlecry_restores_eight_to_chosen_friendly_hero","Amber Watcher's Battlecry restores 8 Health to its chosen friendly hero, from 18 to 26.",battlecry_restores_eight_health_to_selected_hero,"Opponent resolves two real Fireballs on the player's hero, then the targetable heal is played on the damaged friendly hero.")])


def bronze_explorer():
    cid="DRG_229"
    def discovers_dragon_and_lifesteal_heals_on_combat():
        g,p,e=game(CardClass.PALADIN);p.max_mana=10;damage_spell=play(p,"CS2_029",target=p.hero);body=play(p,cid);choice=p.choice;options=list(choice.cards);choice.choose(options[0]);g.end_turn();g.end_turn();target=e.summon(WISP);health_before=p.hero.health;ready=body.can_attack(target)
        if ready:body.attack(target)
        observed=f"damage_spell={damage_spell.zone.name};options={[(c.id,c.race) for c in options]};dragon_in_hand={p.hand[-1].id if p.hand else None};lifesteal={body.lifesteal};ready={ready};hero={health_before}->{p.hero.health};body={body.health}/{body.zone.name};target={target.health}/{target.zone.name}"
        return check(len(options)==3 and all(c.race==Race.DRAGON for c in options) and body.lifesteal and ready and p.hero.health==health_before+body.atk and body.zone==Zone.PLAY,observed)
    audit(cid,[("discover_dragon_and_lifesteal_combat_heals","Bronze Explorer discovers a Dragon into hand, and Lifesteal heals its controller for its 3 damage in a later Yeti attack.",discovers_dragon_and_lifesteal_heals_on_combat,"Damage hero with own Fireball, resolve choice and verify Dragon options, pass round for attack readiness, then inspect actual Lifesteal combat heal.")])


def lightforged_crusader():
    cid="DRG_231"
    def no_neutral_deck_adds_five_paladin_cards():
        g,p,e=game(CardClass.PALADIN);body=play(p,cid);created=list(p.hand)
        observed=f"hand={[(c.id,c.card_class,c.zone.name) for c in created]};body={body.zone.name}"
        return check(len(created)==5 and all(c.card_class==CardClass.PALADIN and c.zone==Zone.HAND for c in created) and body.zone==Zone.PLAY,observed)
    def neutral_in_deck_disables_battlecry():
        g,p,e=game(CardClass.PALADIN);neutral=p.card(WISP,zone=Zone.DECK);body=play(p,cid)
        observed=f"neutral={neutral.id}/{neutral.zone.name};hand={[c.id for c in p.hand]};body={body.zone.name}"
        return check(neutral.zone==Zone.DECK and len(p.hand)==0 and body.zone==Zone.PLAY,observed)
    audit(cid,[("neutral_free_deck_generates_five_paladin_cards","With no Neutral cards in deck, the Battlecry adds five Paladin class cards to hand.",no_neutral_deck_adds_five_paladin_cards,"Empty-deck condition; assert exactly five generated cards and class/zone for every card. Source calls Give(CONTROLLER, RandomCollectible(...)) once without a repeat multiplier; observed hand contains exactly one Paladin card."),
               ("neutral_deck_prevents_generated_cards","A Neutral Wisp in deck disables the Battlecry and remains in deck.",neutral_in_deck_disables_battlecry,"One known Neutral card exercises the false condition.")])


def lightforged_zealot():
    cid="DRG_232"
    def neutral_free_deck_equips_four_two_truesilver():
        g,p,e=game(CardClass.PALADIN);body=play(p,cid);weapon=p.weapon
        observed=f"weapon={(weapon.id,weapon.atk,weapon.durability,weapon.zone.name) if weapon else None};body={body.zone.name}"
        return check(weapon is not None and weapon.id=="DRG_232t" and weapon.atk==4 and weapon.durability==2 and weapon.zone==Zone.PLAY and body.zone==Zone.PLAY,observed)
    def neutral_deck_prevents_weapon_equip():
        g,p,e=game(CardClass.PALADIN);neutral=p.card(WISP,zone=Zone.DECK);body=play(p,cid)
        observed=f"neutral={neutral.zone.name};weapon={p.weapon};body={body.zone.name}"
        return check(neutral.zone==Zone.DECK and p.weapon is None and body.zone==Zone.PLAY,observed)
    audit(cid,[("neutral_free_deck_equips_four_attack_two_durability_weapon","With no Neutral cards in deck, Lightforged Zealot equips a 4/2 Truesilver Champion.",neutral_free_deck_equips_four_two_truesilver,"Check exact weapon id, Attack, Durability, ownership slot, and body zone."),
               ("neutral_deck_prevents_weapon_equip","A Neutral Wisp in deck prevents equipping the weapon.",neutral_deck_prevents_weapon_equip,"Neutral-card false branch control.")])


def sand_breath():
    cid="DRG_233"
    def dragon_in_hand_grants_stats_and_shield():
        g,p,e=game(CardClass.PALADIN);target=p.summon(WISP);dragon=p.give("DRG_079");spell=play(p,cid,target=target)
        observed=f"dragon={dragon.zone.name};target={target.atk}/{target.health}/{target.divine_shield};spell={spell.zone.name}"
        return check((target.atk,target.health,target.divine_shield)==(2,3,True) and spell.zone==Zone.GRAVEYARD,observed)
    def no_dragon_grants_stats_without_shield():
        g,p,e=game(CardClass.PALADIN);target=p.summon(WISP);spell=play(p,cid,target=target)
        observed=f"target={target.atk}/{target.health}/{target.divine_shield};spell={spell.zone.name}"
        return check((target.atk,target.health,target.divine_shield)==(2,3,False) and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("holding_dragon_adds_divine_shield_to_buffed_minion","Sand Breath gives a minion +1/+2 and Divine Shield while a Dragon is held.",dragon_in_hand_grants_stats_and_shield,"Target friendly Wisp, hold Dragon, and inspect all modified stats and keyword."),
               ("without_dragon_only_stats_buff","Without a Dragon, Sand Breath gives +1/+2 but no Divine Shield.",no_dragon_grants_stats_without_shield,"Same target setup without the conditional Dragon.")])


def dragonrider_talritha():
    cid="DRG_235"
    def deathrattle_buffs_one_hand_dragon_and_passes_deathrattle():
        g,p,e=game(CardClass.PALADIN);d1=p.give("DRG_079");d2=p.give("NEW1_023");base={d1.id:(d1.atk,d1.health),d2.id:(d2.atk,d2.health)};body=p.summon(cid);body.destroy()
        buffed=[d for d in (d1,d2) if (d.atk,d.health)!=(base[d.id][0],base[d.id][1])];
        if len(buffed)==1:
            p.used_mana=0;first=buffed[0];first.play();first.destroy()
        other=[d for d in (d1,d2) if buffed and d is not buffed[0]]
        observed=f"talritha={body.zone.name};base={base};hand={[(d.id,d.atk,d.health,d.zone.name) for d in (d1,d2)]};buffed={[d.id for d in buffed]};played={[d.id for d in buffed if d.zone==Zone.GRAVEYARD]};other={[(d.id,d.atk,d.health) for d in other]}"
        return check(body.zone==Zone.GRAVEYARD and len(buffed)==1 and (buffed[0].atk,buffed[0].health)==(base[buffed[0].id][0]+3,base[buffed[0].id][1]+3) and buffed[0].zone==Zone.GRAVEYARD and len(other)==1 and (other[0].atk,other[0].health)==(base[other[0].id][0]+3,base[other[0].id][1]+3),observed)
    audit(cid,[("deathrattle_buffs_hand_dragon_and_grants_inherited_deathrattle","Talritha's death buffs one hand Dragon +3/+3; after playing and killing that Dragon, its copied Deathrattle buffs the other hand Dragon +3/+3.",deathrattle_buffs_one_hand_dragon_and_passes_deathrattle,"Two known hand Dragons make the random first target observable; actually play and kill it to verify inherited Deathrattle on the remaining Dragon.")])


def shield_of_galakrond():
    cid="DRG_242"
    def taunt_body_invokes_once():
        g,p,e=game(CardClass.WARLOCK);gal=p.card("DRG_600",zone=Zone.DECK);body=play(p,cid)
        observed=f"invoke={p.invoke_counter};body={body.atk}/{body.health}/{body.taunt}/{body.zone.name};gal={gal.zone.name};field={[(m.id,m.atk,m.health) for m in p.field]}"
        return check(p.invoke_counter==1 and body.taunt and body.zone==Zone.PLAY and gal.zone==Zone.DECK,observed)
    audit(cid,[("taunt_battlecry_invokes_galakrond_once","Shield of Galakrond enters as a Taunt minion and its Battlecry performs one actual Invoke with Warlock Galakrond in deck.",taunt_body_invokes_once,"Assert printed keyword, exact live zone, invocation counter, and untouched Galakrond deck card.")])


RUNNERS = [
    ("DRG_076", faceless_corruptor), ("DRG_077", utgarde_grapplesniper),
    ("DRG_078", depth_charge), ("DRG_079", evasive_wyrm),
    ("DRG_081", scalerider), ("DRG_082", kobold_stickyfinger),
    ("DRG_084", tentacled_menace), ("DRG_086", chromatic_egg),
    ("DRG_089", dragonqueen_alexstrasza), ("DRG_090", murozond_the_infinite),
    ("DRG_091", shuma), ("DRG_092", transmogrifier),
    ("DRG_095", veranus), ("DRG_096", bandersmosh),
    ("DRG_099", kronx_dragonhoof), ("DRG_102", azure_explorer),
    ("DRG_104", chenvaala), ("DRG_106", arcane_breath),
    ("DRG_107", violet_spellwing), ("DRG_109", mana_giant),
    ("DRG_201", crazed_netherwing), ("DRG_202", dragonblight_cultist),
    ("DRG_203", veiled_worshipper), ("DRG_204", dark_skies),
    ("DRG_205", nether_breath), ("DRG_206", rain_of_fire),
    ("DRG_207", abyssal_summoner), ("DRG_208", valdris_felgorge),
    ("DRG_209", zzeraku_the_warped), ("DRG_213", twin_tyrant),
    ("DRG_215", storms_wrath), ("DRG_216", surging_tempest),
    ("DRG_217", dragons_pack), ("DRG_218", corrupt_elementalist),
    ("DRG_219", lightning_breath), ("DRG_223", cumulo_maximus),
    ("DRG_224", nithogg), ("DRG_225", sky_claw),
    ("DRG_226", amber_watcher), ("DRG_229", bronze_explorer),
    ("DRG_231", lightforged_crusader), ("DRG_232", lightforged_zealot),
    ("DRG_233", sand_breath), ("DRG_235", dragonrider_talritha),
    ("DRG_242", shield_of_galakrond),
]


def run_all():
    runner_ids=[cid for cid,_ in RUNNERS]
    frozen_ids=[r["card_id"] for r in ROSTER]
    assert len(runner_ids)==45 and len(set(runner_ids))==45 and runner_ids==frozen_ids
    for cid,runner in RUNNERS:
        runner()
    probe_ids=[r["card_id"] for r in PROBES]
    verdict_ids=[r["card_id"] for r in VERDICTS]
    pairs=[(r["card_id"],r["case_id"]) for r in PROBES]
    assert set(probe_ids)==set(frozen_ids) and len(set(probe_ids))==45
    assert set(verdict_ids)==set(frozen_ids) and len(set(verdict_ids))==45
    assert len(pairs)==len(set(pairs))
    assert all(r["outcome"] in {"pass","confirmed_error"} for r in PROBES)
    assert all(r["status"] in {"GREEN","RED","YELLOW"} for r in VERDICTS)
    counts={status:sum(r["status"]==status for r in VERDICTS) for status in ("GREEN","YELLOW","RED")}
    print(f"COUNTS {counts}; cases={len(PROBES)}; selected={len(runner_ids)}; frozen={len(frozen_ids)}")
    return counts


if __name__=="__main__":
    run_all()
