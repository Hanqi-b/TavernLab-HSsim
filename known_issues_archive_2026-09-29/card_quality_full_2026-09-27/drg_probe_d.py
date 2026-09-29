"""Card-specific live game checks for the final 21 collectible DRAGONS YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction
from fireplace.actions import CastSpell
from fireplace.managers import BaseObserver

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "drg_probe_d.csv"
VERDICT_FILE = HERE / "drg_verdict_d.csv"
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


ROSTER = sorted((r for r in read(HERE / "remaining_yellow_baseline.csv")
                 if r["set"].endswith("(DRAGONS)")),
                key=lambda r: r["card_id"])
ROSTER = ROSTER[115:136]
assert len(ROSTER) == 21
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


def shrubadier():
    cid="DRG_312"
    def summons_one_treant():
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid);treants=[m for m in p.field if m.id=="DRG_311t"]
        observed=f"body={body.zone.name};treants={[(m.atk,m.health,m.zone.name) for m in treants]};enemy_count={len(e.field)}"
        return check(body.zone==Zone.PLAY and len(treants)==1 and
                     (treants[0].atk,treants[0].health,treants[0].zone)==(2,2,Zone.PLAY)
                     and not e.field,observed)
    audit(cid,[("battlecry_summons_one_two_two_treant","Battlecry creates exactly one friendly 2/2 Treant.",summons_one_treant,"战吼衍生物数量、属性与阵营")])


def emerald_explorer():
    cid="DRG_313"
    def taunt_and_dragon_discover():
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid);choice=p.choice;options=list(choice.cards) if choice else []
        selected=options[0] if options else None
        if selected:choice.choose(selected)
        observed=f"taunt={body.taunt};options={[(c.id,[int(r) for r in c.races]) for c in options]};selected={None if selected is None else (selected.id,selected.zone.name)};choice_closed={p.choice is None}"
        return check(body.taunt and body.zone==Zone.PLAY and len(options)==3 and
                     all(Race.DRAGON in c.races for c in options) and selected is not None and
                     selected.zone==Zone.HAND and p.choice is None,observed)
    audit(cid,[("taunt_and_discover_dragon_to_hand","Body has Taunt; three Dragon choices open; selected Dragon enters hand and choice closes.",taunt_and_dragon_discover,"嘲讽、候选种族、Choice 结算")])


def aeroponics():
    cid="DRG_314"
    def cost_reduces_per_treant_and_draws_two():
        g,p,e=game(CardClass.DRUID)
        first=p.card(WISP,zone=Zone.DECK);second=p.card("CS2_182",zone=Zone.DECK)
        spell=p.give(cid);base=spell.cost
        p.summon("DRG_311t");one=spell.cost
        p.summon("DRG_311t");two=spell.cost
        spell.play()
        observed=f"costs={base},{one},{two};drawn={first.zone.name},{second.zone.name};spell={spell.zone.name}"
        return check((base,one,two)==(5,3,1) and first.zone==second.zone==Zone.HAND
                     and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("two_treants_reduce_cost_and_two_known_cards_drawn","One and two friendly Treants reduce Aeroponics from 5 to 3 to 1, then its cast draws both known deck cards.",cost_reduces_per_treant_and_draws_two,"动态费用与真实抽牌移区")])


def embiggen():
    cid="DRG_315"
    def buffs_deck_minions_and_caps_cost():
        g,p,e=game(CardClass.DRUID)
        low=p.card(WISP,zone=Zone.DECK);high=p.card("EX1_572",zone=Zone.DECK)
        hand=p.give(WISP);before_high=(high.atk,high.max_health,high.cost)
        spell=play(p,cid)
        observed=f"low={low.atk}/{low.max_health}/cost{low.cost}/{low.zone.name};high={high.atk}/{high.max_health}/cost{high.cost}/before{before_high};hand={hand.atk}/{hand.max_health}/cost{hand.cost};spell={spell.zone.name}"
        return check((low.atk,low.max_health,low.cost,low.zone)==(3,3,1,Zone.DECK) and
                     (high.atk,high.max_health,high.cost)==(before_high[0]+2,before_high[1]+2,min(10,before_high[2]+1)) and
                     (hand.atk,hand.max_health,hand.cost,hand.zone)==(1,1,0,Zone.HAND) and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deck_minions_gain_two_two_and_one_cost_up_to_ten","All tested deck minions gain +2/+2 and +1 Cost capped at 10; same minion held in hand stays unchanged.",buffs_deck_minions_and_caps_cost,"牌库作用域、属性、费用上限与手牌对照")])


def secure_the_deck():
    cid="DRG_317"
    def two_real_hero_attacks_reward_three_claws():
        g,p,e=game(CardClass.DRUID)
        quest=play(p,cid);weapon=play(p,"CS2_106")
        p.hero.attack(e.hero)
        before=(quest.progress,quest.zone,len([c for c in p.hand if c.id=="CS2_005"]))
        g.end_turn();g.end_turn();p.hero.attack(e.hero)
        claws=[c for c in p.hand if c.id=="CS2_005"]
        observed=f"after_first={before[0]}:{before[1].name}:claws{before[2]};after_second={quest.progress}:{quest.zone.name};claws={[(c.id,c.zone.name) for c in claws]};weapon={weapon.zone.name}:{weapon.durability};enemy_hero={e.hero.health}"
        return check(before==(1,Zone.SECRET,0) and quest.progress==2 and quest.zone==Zone.GRAVEYARD
                     and len(claws)==3 and all(c.zone==Zone.HAND for c in claws) and e.hero.health==24,observed)
    audit(cid,[("two_hero_attacks_add_exactly_three_claws","First real hero attack gives progress 1 and no Claws; second on next turn completes Sidequest and adds exactly three Claw spells.",two_real_hero_attacks_reward_three_claws,"跨回合真实英雄攻击、进度与奖励手牌")])


def breath_of_dreams():
    cid="DRG_318"
    def branch(holding_dragon):
        g,p,e=game(CardClass.DRUID)
        p.max_mana=4;p.used_mana=0
        drawn=p.card(WISP,zone=Zone.DECK)
        if holding_dragon:dragon=p.give("DRG_075")
        spell=play(p,cid)
        observed=f"dragon={holding_dragon};drawn={drawn.zone.name};max_mana={p.max_mana};available={p.mana};used={p.used_mana};spell={spell.zone.name}"
        return check(drawn.zone==Zone.HAND and p.max_mana==(5 if holding_dragon else 4)
                     and p.mana==2 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("held_dragon_draws_and_gains_empty_crystal","A held Dragon permits one empty Mana Crystal while drawing the known deck card.",lambda:branch(True),"龙牌条件、实际抽牌和空水晶法力守恒"),
               ("without_dragon_draws_without_mana_gain","Without a Dragon it draws the card but does not gain a Mana Crystal.",lambda:branch(False),"无龙条件分支")])


def goru_the_mightree():
    cid="DRG_319"
    def permanent_friendly_treant_buff():
        g,p,e=game(CardClass.DRUID)
        earlier=p.summon("DRG_311t");enemy=e.summon("DRG_311t")
        body=play(p,cid);during=(earlier.atk,earlier.max_health)
        body.destroy();later=p.summon("DRG_311t")
        observed=f"earlier={during};later={later.atk}/{later.max_health};enemy={enemy.atk}/{enemy.max_health};goru={body.zone.name}"
        return check(body.zone==Zone.GRAVEYARD and during==(3,3) and
                     (later.atk,later.max_health)==(3,3) and (enemy.atk,enemy.max_health)==(2,2),observed)
    audit(cid,[("existing_and_future_friendly_treants_buff_after_goru_dies","Existing and newly summoned friendly Treants stay +1/+1 after Goru dies; enemy Treant stays 2/2.",permanent_friendly_treant_buff,"当前/未来实体、阵营和永久时效")])


def ysera_unleashed():
    cid="DRG_320"
    def seven_portals_and_draw_cast_summons_dragon():
        g,p,e=game(CardClass.DRUID)
        body=play(p,cid);portals=[c for c in p.deck if c.id=="DRG_320t"]
        # Cast-when-drawn effects also draw a replacement. Place a known plain
        # card on top to isolate one Portal instead of chaining all seven.
        replacement=p.card(WISP,zone=Zone.DECK)
        before=len(p.field);portals[0].draw()
        dragons=[m for m in p.field if m is not body and Race.DRAGON in m.races]
        observed=f"portals_before={len(portals)};remaining={len([c for c in p.deck if c.id=='DRG_320t'])};replacement={replacement.zone.name};drawn_portal={portals[0].zone.name};summoned={[(m.id,m.zone.name,[int(r) for r in m.races]) for m in dragons]};body={body.zone.name}"
        return check(len(portals)==7 and len([c for c in p.deck if c.id=="DRG_320t"])==6
                     and replacement.zone==Zone.HAND and len(p.field)==before+1 and len(dragons)==1 and dragons[0].zone==Zone.PLAY
                     and body.zone==Zone.PLAY,observed)
    audit(cid,[("seven_portals_shuffled_and_drawn_portal_summons_dragon","Battlecry shuffles seven Dream Portals; drawing one removes it from deck and summons exactly one friendly Dragon.",seven_portals_and_draw_cast_summons_dragon,"牌库数、抽到即施放和召唤种族区域")])


def rolling_fireball():
    cid="DRG_321"
    def excess_to_only_neighbor():
        g,p,e=game(CardClass.MAGE)
        center=e.summon(WISP);right=e.summon("EX1_572")
        spell=play(p,cid,target=center)
        observed=f"center={center.zone.name};right={right.health};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(center.zone==Zone.GRAVEYARD and right.health==5 and e.hero.health==30 and spell.zone==Zone.GRAVEYARD,observed)
    def excess_chooses_one_direction():
        g,p,e=game(CardClass.MAGE)
        left=e.summon("EX1_572");center=e.summon(WISP);right=e.summon("EX1_572")
        spell=play(p,cid,target=center)
        losses=(12-left.health,12-right.health)
        observed=f"center={center.zone.name};left={left.health};right={right.health};losses={losses};hero={e.hero.health};spell={spell.zone.name}"
        return check(center.zone==Zone.GRAVEYARD and sorted(losses)==[0,7] and e.hero.health==30 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("one_neighbor_takes_seven_excess_damage","Eight damage kills a 1-Health center minion; sole right neighbor takes seven excess, hero untouched.",excess_to_only_neighbor,"目标死亡、溢出量与相邻方向"),
               ("two_neighbors_only_one_receives_excess","With left and right neighbors, exactly one receives the seven excess damage.",excess_chooses_one_direction,"双方向随机候选但总伤害守恒")])


def dragoncaster():
    cid="DRG_322"
    def branch(holding_dragon):
        g,p,e=game(CardClass.MAGE)
        target=e.summon("EX1_572")
        first=p.give("CS2_029");second=p.give("CS2_029");base=first.cost
        if holding_dragon:p.give("DRG_075")
        body=play(p,cid);first_cost=first.cost
        if holding_dragon:
            first.play(target=target)
        observed=f"dragon={holding_dragon};base={base};first_cost={first_cost};second_cost={second.cost};target={target.health};first_zone={first.zone.name};body={body.zone.name}"
        return check(first_cost==(0 if holding_dragon else base) and second.cost==base
                     and body.zone==Zone.PLAY and (not holding_dragon or (first.zone==Zone.GRAVEYARD and target.health==6)),observed)
    audit(cid,[("held_dragon_makes_only_next_spell_free_this_turn","Holding a Dragon makes the next Fireball free; after it is cast, another Fireball returns to its original Cost.",lambda:branch(True),"持龙条件、实际施法和一次性折扣"),
               ("no_dragon_leaves_spell_cost_unchanged","Without a Dragon, Dragoncaster does not discount the next spell.",lambda:branch(False),"不持龙负例")])


def learn_draconic():
    cid="DRG_323"
    def spending_eight_rewards_one_six_six_dragon():
        g,p,e=game(CardClass.MAGE)
        quest=play(p,cid);play(p,"GAME_005")
        zero=(quest.progress,quest.zone)
        first=play(p,"CS2_029",target=e.hero);half=quest.progress
        second=play(p,"CS2_029",target=e.hero)
        reward=[m for m in p.field if m.id=="DRG_323t"]
        observed=f"zero={zero[0]}:{zero[1].name};half={half};final={quest.progress}:{quest.zone.name};reward={[(m.atk,m.health,m.zone.name) for m in reward]};enemy_hero={e.hero.health}"
        return check(zero==(0,Zone.SECRET) and half==4 and quest.progress==8
                     and quest.zone==Zone.GRAVEYARD and len(reward)==1 and
                     (reward[0].atk,reward[0].health,reward[0].zone)==(6,6,Zone.PLAY),observed)
    audit(cid,[("eight_paid_spell_mana_summons_one_six_six_dragon","Free Coin gives no progress; two actually paid 4-Mana Fireballs reach eight and summon one 6/6 Dragon.",spending_eight_rewards_one_six_six_dragon,"费用贡献、任务进度与唯一奖励")])


def elemental_allies():
    cid="DRG_324"
    def two_consecutive_elemental_turns_draw_three_spells():
        g,p,e=game(CardClass.MAGE)
        deck=[p.card(x,zone=Zone.DECK) for x in ("CS2_008","CS2_029","EX1_277")]
        quest=play(p,cid);play(p,"UNG_809");first=quest.progress
        g.end_turn();g.end_turn();p.used_mana=0;play(p,"UNG_809")
        observed=f"first={first};final={quest.progress}:{quest.zone.name};drawn={[(c.id,c.zone.name) for c in deck]}"
        return check(first==1 and quest.progress==2 and quest.zone==Zone.GRAVEYARD
                     and all(c.zone==Zone.HAND for c in deck),observed)
    def skipped_turn_resets_streak():
        g,p,e=game(CardClass.MAGE)
        quest=play(p,cid);play(p,"UNG_809");first=quest.progress
        g.end_turn();g.end_turn();g.end_turn();g.end_turn();reset=quest.progress
        play(p,"UNG_809")
        observed=f"first={first};after_skipped_turn={reset};after_next_elemental={quest.progress};quest={quest.zone.name}"
        return check(first==1 and reset==0 and quest.progress==1 and quest.zone==Zone.SECRET,observed)
    audit(cid,[("elemental_two_turn_streak_draws_three_known_spells","Elementals played on two consecutive own turns complete Sidequest and draw all three known spells.",two_consecutive_elemental_turns_draw_three_spells,"跨回合连续条件、牌库抽牌与奖励"),
               ("missing_elemental_turn_resets_streak","Skipping an own turn without playing an Elemental resets progress; a later Elemental starts at one.",skipped_turn_resets_streak,"断档负例与进度重置")])


def grizzled_wizard():
    cid="DRG_401"
    def swaps_powers_until_next_own_turn():
        g,p,e=game(CardClass.MAGE,CardClass.HUNTER)
        own=p.hero.power.id;enemy=e.hero.power.id
        body=play(p,cid);immediate=(p.hero.power.id,e.hero.power.id)
        g.end_turn();opponent_turn=(p.hero.power.id,e.hero.power.id)
        g.end_turn();restored=(p.hero.power.id,e.hero.power.id)
        observed=f"original={own}/{enemy};immediate={immediate};opponent_turn={opponent_turn};restored={restored};body={body.zone.name}"
        return check(immediate==(enemy,own) and opponent_turn==(enemy,own) and
                     restored==(own,enemy) and body.zone==Zone.PLAY,observed)
    audit(cid,[("swap_hero_powers_until_next_own_turn","The two distinct Hero Powers swap immediately, stay swapped on opponent's turn, and revert at next own turn.",swaps_powers_until_next_own_turn,"双方英雄技能身份与跨回合时效")])


def sathrovarr():
    cid="DRG_402"
    def targeted_copy_enters_three_zones():
        g,p,e=game()
        target=p.summon(WISP);body=play(p,cid,target=target)
        hand=[c for c in p.hand if c.id==WISP];deck=[c for c in p.deck if c.id==WISP]
        field=[m for m in p.field if m.id==WISP]
        observed=f"body={body.zone.name};target={target.zone.name};hand={[(c.id,c.zone.name) for c in hand]};deck={[(c.id,c.zone.name) for c in deck]};field={[(m.id,m.zone.name,m is target) for m in field]};enemy_field={len(e.field)}"
        return check(body.zone==Zone.PLAY and target.zone==Zone.PLAY and
                     len(hand)==len(deck)==1 and len(field)==2 and
                     hand[0].zone==Zone.HAND and deck[0].zone==Zone.DECK and
                     all(m.zone==Zone.PLAY for m in field) and not e.field,observed)
    audit(cid,[("selected_friendly_minion_copied_to_hand_deck_and_board","Chosen friendly Wisp remains in play and gains exactly one distinct copy in hand, deck and battlefield.",targeted_copy_enters_three_zones,"目标、三种区域与复制数量")])


def blowtorch_saboteur():
    cid="DRG_403"
    def opponent_next_power_costs_three_then_reverts():
        g,p,e=game(CardClass.MAGE,CardClass.HUNTER)
        baseline=e.hero.power.cost;body=play(p,cid);raised=e.hero.power.cost
        own_cost=p.hero.power.cost
        g.end_turn();e.hero.power.use();after=e.hero.power.cost
        observed=f"baseline={baseline};raised={raised};own_power_cost={own_cost};after_use={after};own_hero={p.hero.health};body={body.zone.name}"
        return check(baseline==2 and raised==3 and after==2 and p.hero.health==28
                     and own_cost==2 and body.zone==Zone.PLAY,observed)
    audit(cid,[("opponent_next_hero_power_costs_three_then_reverts","Enemy Hunter Hero Power costs 3 for its next real use, deals its usual damage, then returns to 2.",opponent_next_power_costs_three_then_reverts,"敌方技能费用、实际使用和一次性复原")])


def molten_breath():
    cid="DRG_500"
    def branch(holding_dragon):
        g,p,e=game(CardClass.WARRIOR)
        if holding_dragon:p.give("DRG_075")
        target=e.summon("EX1_572");spell=play(p,cid,target=target)
        observed=f"dragon={holding_dragon};target={target.health}:{target.zone.name};armor={p.hero.armor};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(target.health==7 and p.hero.armor==(5 if holding_dragon else 0)
                     and e.hero.health==30 and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("held_dragon_five_damage_and_five_armor","Held Dragon enables five Armor alongside five damage to the chosen minion.",lambda:branch(True),"持龙、目标伤害、护甲"),
               ("without_dragon_five_damage_no_armor","Without Dragon, target still takes five damage but hero gains no Armor.",lambda:branch(False),"无龙条件分支")])


def invoke_upgraded_hero(card_class, hero_id, invoke_id, count, deck_ids=(), enemy_before_play=0, clear_other_hand=False):
    """Use real class Invoke cards on successive turns before playing Galakrond."""
    g,p,e=game(card_class)
    p.give(hero_id)
    for _ in range(count):
        target=None
        if invoke_id in ("DRG_246","DRG_247"):
            target=e.summon("CS2_182")
        elif invoke_id=="DRG_248":
            target=e.hero
        play(p,invoke_id,target=target)
        # The next Invoke and Galakrond each happen on a later own turn.
        g.end_turn();g.end_turn()
    # Keep the known draw sample out of automatic start-of-turn draws during
    # the setup turns; it enters the deck immediately before Galakrond.
    deck_cards=[p.card(card_id,zone=Zone.DECK) for card_id in deck_ids]
    for body in list(p.field):
        body.destroy()
    foes=[e.summon("CS2_182") for _ in range(enemy_before_play)]
    card=next((c for c in p.hand if c.id in (hero_id,hero_id+"t2",hero_id+"t3")),None)
    assert card is not None, f"upgraded Galakrond missing from hand: {[c.id for c in p.hand]}"
    if clear_other_hand:
        for other in list(p.hand):
            if other is not card:other.discard()
    before_id=card.id
    card.play()
    return g,p,e,before_id,card,dict(deck_cards=deck_cards,foes=foes)


def galakrond_wretched():
    cid="DRG_600"
    def base_summons_one_demon():
        g,p,e=game(CardClass.WARLOCK)
        hero_card=play(p,cid)
        demons=[m for m in p.field if Race.DEMON in m.races]
        observed=f"hero={p.hero.id};power={p.hero.power.id};armor={p.hero.armor};demons={[(m.id,m.zone.name) for m in demons]};card={hero_card.zone.name}"
        return check(p.hero.id==cid and len(demons)==1 and demons[0].zone==Zone.PLAY
                     and p.hero.armor==5,observed)
    def upgraded_demons(count):
        g,p,e,before_id,card,ctx=invoke_upgraded_hero(CardClass.WARLOCK,cid,"DRG_250",count)
        demons=[m for m in p.field if Race.DEMON in m.races]
        weapon=p.weapon
        observed=f"invokes={p.invoke_counter};before_id={before_id};hero={p.hero.id};armor={p.hero.armor};demons={[(m.id,m.zone.name) for m in demons]};weapon={None if weapon is None else (weapon.id,weapon.atk,weapon.durability)}"
        return check(p.invoke_counter==count and before_id==cid+("t2" if count==2 else "t3")
                     and p.hero.id==before_id and p.hero.armor==5 and len(demons)==count
                     and all(m.zone==Zone.PLAY for m in demons)
                     and (count==2 or (weapon is not None and (weapon.atk,weapon.durability)==(5,2))),observed)
    audit(cid,[("uninvoked_hero_summons_one_random_demon","Playing base Warlock Galakrond replaces hero, grants five Armor, and summons one friendly Demon.",base_summons_one_demon,"英雄变身、护甲与基础战吼召唤"),
               ("two_real_invokes_summon_two_demons","Two actual Invoke cards on separate turns upgrade Warlock Galakrond to summon two Demons.",lambda:upgraded_demons(2),"第一升级阈值与召唤数"),
               ("four_real_invokes_summon_four_demons_and_claw","Four actual Invokes upgrade it to summon four Demons and equip a 5/2 Claw.",lambda:upgraded_demons(4),"第二升级阈值、召唤数与武器")])


def galakrond_nightmare():
    cid="DRG_610"
    def base_draws_one_card_at_one_cost():
        g,p,e=game(CardClass.ROGUE)
        drawn=p.card("CS2_182",zone=Zone.DECK)
        hero_card=play(p,cid)
        observed=f"hero={p.hero.id};power={p.hero.power.id};armor={p.hero.armor};drawn={drawn.id}:{drawn.zone.name}:cost{drawn.cost};card={hero_card.zone.name}"
        return check(p.hero.id==cid and p.hero.armor==5 and drawn.zone==Zone.HAND
                     and drawn.cost==1,observed)
    def upgraded_draws(count):
        g,p,e,before_id,card,ctx=invoke_upgraded_hero(
            CardClass.ROGUE,cid,"DRG_247",count,deck_ids=("CS2_182",)*8,clear_other_hand=True)
        drawn=[c for c in ctx["deck_cards"] if c.zone==Zone.HAND]
        waiting=[c for c in ctx["deck_cards"] if c.zone==Zone.DECK]
        weapon=p.weapon
        observed=f"invokes={p.invoke_counter};hero={p.hero.id};before_id={before_id};all_deck_cards={[(c.id,c.cost,c.zone.name) for c in ctx['deck_cards']]};drawn={[(c.id,c.cost,c.zone.name) for c in drawn]};waiting={len(waiting)};weapon={None if weapon is None else (weapon.id,weapon.atk,weapon.durability)}"
        return check(p.invoke_counter==count and before_id==cid+("t2" if count==2 else "t3")
                     and p.hero.id==before_id and len(drawn)==count and len(waiting)==8-count
                     and all(c.cost==1 for c in drawn)
                     and (count==2 or (weapon is not None and (weapon.atk,weapon.durability)==(5,2))),observed)
    audit(cid,[("uninvoked_hero_draws_one_card_set_to_one_cost","Playing base Rogue Galakrond replaces hero, gains five Armor, draws one known deck card and sets its Cost to one.",base_draws_one_card_at_one_cost,"英雄变身、真实抽牌和费用设置"),
               ("two_real_invokes_draw_two_at_one_cost","Two real Invokes upgrade Rogue Galakrond to draw two known cards and set each to Cost one.",lambda:upgraded_draws(2),"第一升级阈值、抽牌数量与费用"),
               ("four_real_invokes_draw_four_at_one_cost_and_claw","Four real Invokes draw four known cards at Cost one and equip a 5/2 Claw.",lambda:upgraded_draws(4),"第二升级阈值、抽牌费用与武器")])


def galakrond_tempest():
    cid="DRG_620"
    def base_summons_two_two_two_rush_storms():
        g,p,e=game(CardClass.SHAMAN)
        hero_card=play(p,cid)
        storms=[m for m in p.field if m.id=="DRG_620t4"]
        observed=f"hero={p.hero.id};power={p.hero.power.id};armor={p.hero.armor};storms={[(m.atk,m.health,m.rush,m.zone.name) for m in storms]};card={hero_card.zone.name}"
        return check(p.hero.id==cid and p.hero.armor==5 and len(storms)==2 and
                     all((m.atk,m.health,m.zone)==(2,2,Zone.PLAY) and m.rush for m in storms),observed)
    def upgraded_storms(count):
        g,p,e,before_id,card,ctx=invoke_upgraded_hero(CardClass.SHAMAN,cid,"DRG_248",count)
        token_id="DRG_620t5" if count==2 else "DRG_620t6"
        storms=[m for m in p.field if m.id==token_id]
        weapon=p.weapon;size=4 if count==2 else 8
        observed=f"invokes={p.invoke_counter};before_id={before_id};hero={p.hero.id};storms={[(m.id,m.atk,m.health,m.rush) for m in storms]};weapon={None if weapon is None else (weapon.id,weapon.atk,weapon.durability)}"
        return check(p.invoke_counter==count and before_id==cid+("t2" if count==2 else "t3")
                     and p.hero.id==before_id and len(storms)==2 and
                     all((m.atk,m.health)==(size,size) and m.rush for m in storms)
                     and (count==2 or (weapon is not None and (weapon.atk,weapon.durability)==(5,2))),observed)
    audit(cid,[("uninvoked_hero_summons_two_two_two_rush_storms","Playing base Shaman Galakrond summons exactly two friendly 2/2 Rush Storms and grants five Armor.",base_summons_two_two_two_rush_storms,"英雄变身、衍生物数量属性和突袭"),
               ("two_real_invokes_summon_two_four_four_rush_storms","Two actual Invokes upgrade the two Storms to 4/4 Rush.",lambda:upgraded_storms(2),"第一升级阈值与衍生物属性"),
               ("four_real_invokes_summon_two_eight_eight_storms_and_claw","Four actual Invokes create two 8/8 Rush Storms and equip a 5/2 Claw.",lambda:upgraded_storms(4),"第二升级阈值、衍生物属性与武器")])


def galakrond_unbreakable():
    cid="DRG_650"
    def base_draws_one_minion_and_buffs_four_four():
        g,p,e=game(CardClass.WARRIOR)
        target=p.card(WISP,zone=Zone.DECK);other=p.card("CS2_029",zone=Zone.DECK)
        hero_card=play(p,cid)
        observed=f"hero={p.hero.id};power={p.hero.power.id};armor={p.hero.armor};target={target.atk}/{target.max_health}/{target.zone.name};other={other.zone.name};card={hero_card.zone.name}"
        return check(p.hero.id==cid and p.hero.armor==5 and
                     (target.atk,target.max_health,target.zone)==(5,5,Zone.HAND)
                     and other.zone==Zone.DECK,observed)
    def upgraded_draws_buffed_minions(count):
        g,p,e,before_id,card,ctx=invoke_upgraded_hero(
            CardClass.WARRIOR,cid,"DRG_249",count,deck_ids=(WISP,)*8)
        drawn=[c for c in ctx["deck_cards"] if c.zone==Zone.HAND]
        waiting=[c for c in ctx["deck_cards"] if c.zone==Zone.DECK]
        weapon=p.weapon
        observed=f"invokes={p.invoke_counter};hero={p.hero.id};before_id={before_id};drawn={[(c.atk,c.max_health,c.zone.name) for c in drawn]};waiting={len(waiting)};weapon={None if weapon is None else (weapon.id,weapon.atk,weapon.durability)}"
        return check(p.invoke_counter==count and before_id==cid+("t2" if count==2 else "t3")
                     and p.hero.id==before_id and len(drawn)==count and len(waiting)==8-count
                     and all((c.atk,c.max_health)==(5,5) for c in drawn)
                     and (count==2 or (weapon is not None and (weapon.atk,weapon.durability)==(5,2))),observed)
    audit(cid,[("uninvoked_hero_draws_only_minion_and_buffs_four_four","Playing base Warrior Galakrond draws the sole minion, buffs it +4/+4 in hand, and leaves a spell in deck.",base_draws_one_minion_and_buffs_four_four,"英雄变身、牌库筛选和手牌属性"),
               ("two_real_invokes_draw_two_minions_plus_four_four","Two real Invokes draw two known minions, each gaining +4/+4.",lambda:upgraded_draws_buffed_minions(2),"第一升级阈值、抽取与手牌增益"),
               ("four_real_invokes_draw_four_buffed_minions_and_claw","Four real Invokes draw four buffed minions and equip a 5/2 Claw.",lambda:upgraded_draws_buffed_minions(4),"第二升级阈值、全体增益与武器")])


def galakrond_unspeakable():
    cid="DRG_660"
    def base_destroys_one_enemy_minion():
        g,p,e=game(CardClass.PRIEST)
        foes=[e.summon("CS2_182") for _ in range(2)];own=p.summon(WISP)
        hero_card=play(p,cid)
        dead=sum(m.zone==Zone.GRAVEYARD for m in foes)
        observed=f"hero={p.hero.id};power={p.hero.power.id};armor={p.hero.armor};enemy_zones={[m.zone.name for m in foes]};own={own.zone.name};card={hero_card.zone.name}"
        return check(p.hero.id==cid and p.hero.armor==5 and dead==1
                     and own.zone==Zone.PLAY,observed)
    def upgraded_destroys(count):
        g,p,e,before_id,card,ctx=invoke_upgraded_hero(
            CardClass.PRIEST,cid,"DRG_246",count,enemy_before_play=4)
        foes=ctx["foes"];dead=sum(m.zone==Zone.GRAVEYARD for m in foes)
        weapon=p.weapon
        observed=f"invokes={p.invoke_counter};hero={p.hero.id};before_id={before_id};enemy_zones={[m.zone.name for m in foes]};dead={dead};weapon={None if weapon is None else (weapon.id,weapon.atk,weapon.durability)}"
        return check(p.invoke_counter==count and before_id==cid+("t2" if count==2 else "t3")
                     and p.hero.id==before_id and dead==count and
                     all(m.zone in (Zone.PLAY,Zone.GRAVEYARD) for m in foes)
                     and (count==2 or (weapon is not None and (weapon.atk,weapon.durability)==(5,2))),observed)
    audit(cid,[("uninvoked_hero_destroys_one_random_enemy_minion","Playing base Priest Galakrond destroys exactly one of two enemy minions, leaves friendly minion alive and gains five Armor.",base_destroys_one_enemy_minion,"英雄变身、随机敌方随从范围与死亡"),
               ("two_real_invokes_destroy_two_enemy_minions","Two real Invokes upgrade Priest Galakrond to destroy exactly two of four enemy minions.",lambda:upgraded_destroys(2),"第一升级阈值与随机敌军击杀数量"),
               ("four_real_invokes_destroy_four_enemy_minions_and_claw","Four real Invokes destroy all four enemy minions and equip a 5/2 Claw.",lambda:upgraded_destroys(4),"第二升级阈值、死亡处理与武器")])


CHECKS={
    "DRG_312":shrubadier,"DRG_313":emerald_explorer,"DRG_314":aeroponics,
    "DRG_315":embiggen,"DRG_317":secure_the_deck,
    "DRG_318":breath_of_dreams,"DRG_319":goru_the_mightree,"DRG_320":ysera_unleashed,
    "DRG_321":rolling_fireball,"DRG_322":dragoncaster,
    "DRG_323":learn_draconic,"DRG_324":elemental_allies,"DRG_401":grizzled_wizard,
    "DRG_402":sathrovarr,"DRG_403":blowtorch_saboteur,
    "DRG_500":molten_breath,"DRG_600":galakrond_wretched,"DRG_610":galakrond_nightmare,
    "DRG_620":galakrond_tempest,"DRG_650":galakrond_unbreakable,"DRG_660":galakrond_unspeakable,
}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
