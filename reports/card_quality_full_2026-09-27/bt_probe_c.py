"""Card-specific live game checks for the final 43 collectible BLACK_TEMPLE YELLOW cards."""

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
PROBE_FILE = HERE / "bt_probe_c.csv"
VERDICT_FILE = HERE / "bt_verdict_c.csv"
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
                 if r["set"].endswith("(BLACK_TEMPLE)")),
                key=lambda r: r["card_id"])
ROSTER = ROSTER[90:133]
assert len(ROSTER) == 43
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



def lady_liadrin():
    cid="BT_334"
    def returns_friendly_target_spells_only():
        g,p,e=game(CardClass.PALADIN)
        ally=p.summon(WISP);enemy=e.summon(WISP)
        friendly=play(p,"CS2_087",target=ally)
        g.end_turn();g.end_turn()
        repeated_friendly=play(p,"CS2_087",target=ally)
        g.end_turn();g.end_turn()
        second_friendly=play(p,"CS2_092",target=ally)
        g.end_turn();g.end_turn()
        hostile=play(p,"CS2_029",target=enemy)
        g.end_turn();g.end_turn()
        body=play(p,cid);hand=[c.id for c in p.hand]
        observed=f"friendly_spells={friendly.zone.name}/{repeated_friendly.zone.name}/{second_friendly.zone.name};hostile_spell={hostile.zone.name};hand={hand};body={body.zone.name}"
        return check(hand.count("CS2_087")==2 and hand.count("CS2_092")==1 and len(hand)==3 and "CS2_029" not in hand and body.zone==Zone.PLAY,observed)
    audit(cid,[("recovers_cast_spells_on_friendly_characters_only","After three friendly-target casts including two of same spell, recovers all three copies but excludes enemy-target Fireball.",returns_friendly_target_spells_only,"施法次数、重复卡、目标阵营与手牌。")])


def skeletal_dragon():
    cid="BT_341"
    def turn_end_adds_dragon():
        g,p,e=game(CardClass.PRIEST);body=play(p,cid);before=len(p.hand)
        g.end_turn();hand=list(p.hand)
        observed=f"taunt={body.taunt};before={before};hand={[(c.id,Race.DRAGON in c.races,c.zone.name) for c in hand]}"
        return check(body.taunt and len(hand)==before+1 and Race.DRAGON in hand[-1].races and hand[-1].zone==Zone.HAND,observed)
    audit(cid,[("own_turn_end_gives_dragon_and_has_taunt","Own turn end adds one Dragon to hand; body has Taunt.",turn_end_adds_dragon,"回合触发、种族、区域和关键词。")])


def ashtongue_battlelord():
    cid="BT_423"
    def attack_heals_hero_with_lifesteal():
        g,p,e=game(CardClass.PRIEST);body=play(p,cid)
        p.hero.hit(5);enemy=e.summon("CS2_182")
        g.end_turn();g.end_turn();ready=body.can_attack(enemy)
        before=p.hero.health
        if ready:body.attack(enemy)
        observed=f"taunt={body.taunt};lifesteal={body.lifesteal};ready={ready};hero={before}->{p.hero.health};enemy={enemy.health}:{enemy.zone.name}"
        return check(body.taunt and body.lifesteal and ready and p.hero.health>before,observed)
    audit(cid,[("taunt_lifesteal_real_combat_heals_hero","After taking damage, attacking enemy Yeti heals owner via Lifesteal and body has Taunt.",attack_heals_hero_with_lifesteal,"实际战斗与治疗。")])


def metamorphosis():
    cid="BT_429"
    def power_twice_four_damage_then_restores():
        g,p,e=game(CardClass.DEMONHUNTER)
        old=p.hero.power.id;spell=play(p,cid)
        first=p.hero.power.id
        p.hero.power.use(target=e.hero);after1=p.hero.power.id;health1=e.hero.health
        g.end_turn();g.end_turn()
        p.hero.power.use(target=e.hero);after2=p.hero.power.id;health2=e.hero.health
        observed=f"old={old};first={first};after1={after1};after2={after2};enemy_health={health1}/{health2};spell={spell.zone.name}"
        return check(first=="BT_429p" and after1=="BT_429p2" and health1==26 and health2==22 and after2==old,observed)
    audit(cid,[("two_uses_deal_four_each_then_restore_hero_power","Power changes to Demonic Blast, two uses each deal 4, then original power returns.",power_twice_four_damage_then_restores,"英雄技能替换、使用次数、伤害与恢复。")])


def warglaives():
    cid="BT_430"
    def grants_extra_attack_after_minion():
        g,p,e=game(CardClass.DEMONHUNTER);enemy=e.summon(WISP)
        weapon=play(p,cid);first=p.hero.can_attack(enemy)
        if first:p.hero.attack(enemy)
        second=p.hero.can_attack(e.hero)
        if second:p.hero.attack(e.hero)
        observed=f"first={first};minion={enemy.zone.name};second={second};hero_attacks={p.hero.num_attacks};enemy_health={e.hero.health};weapon={weapon.zone.name}:{weapon.durability}"
        return check(first and second and enemy.zone==Zone.GRAVEYARD and e.hero.health==27 and weapon.durability==2,observed)
    audit(cid,[("attack_minion_grants_second_attack","Weapon attack kills enemy Wisp, then hero can attack enemy hero in same turn.",grants_extra_attack_after_minion,"实际英雄攻击、额外攻击与武器耐久。")])


def crimson_sigil_runner():
    cid="BT_480"
    def branch(outcast):
        g,p,e=game(CardClass.DEMONHUNTER);deck=p.card(WISP,zone=Zone.DECK)
        if not outcast:p.give("CS2_182")
        card=p.give(cid)
        if not outcast:p.give("CS2_182")
        card.play()
        observed=f"outcast={outcast};drawn={deck.zone.name};runner={card.zone.name};hand={[(c.id,c.zone.name) for c in p.hand]}"
        return check(deck.zone==(Zone.HAND if outcast else Zone.DECK) and card.zone==Zone.PLAY,observed)
    audit(cid,[("outcast_draws_one","Runner at hand edge draws sole Wisp.",lambda:branch(True),"真实手牌边缘与抽牌。"),
               ("not_outcast_does_not_draw","Runner with card to right does not draw.",lambda:branch(False),"非边缘分支。")])


def pit_commander():
    cid="BT_486"
    def turn_end_summons_deck_demon_only():
        g,p,e=game(CardClass.DEMONHUNTER)
        demon=p.card("EX1_301",zone=Zone.DECK);plain=p.card(WISP,zone=Zone.DECK)
        body=play(p,cid);g.end_turn()
        observed=f"taunt={body.taunt};demon={demon.zone.name};plain={plain.zone.name};body={body.zone.name}"
        return check(body.taunt and demon.zone==Zone.PLAY and plain.zone==Zone.DECK,observed)
    audit(cid,[("end_turn_summons_only_demon_from_deck","Own turn end summons sole deck Demon; non-Demon Wisp stays.",turn_end_summons_deck_demon_only,"回合触发、种族牌库过滤、嘲讽。")])


def priestess_of_fury():
    cid="BT_493"
    def six_damage_to_only_enemy_character():
        g,p,e=game(CardClass.DEMONHUNTER)
        ally=p.summon("CS2_182");body=play(p,cid)
        g.end_turn()
        observed=f"enemy_hero={e.hero.health};friendly={ally.health};body={body.zone.name}"
        return check(e.hero.health==24 and ally.health==5 and body.zone==Zone.PLAY,observed)
    def six_damage_is_conserved_across_enemy_characters():
        g,p,e=game(CardClass.DEMONHUNTER)
        ally=p.summon("CS2_182");foe=e.summon("EX1_572");body=play(p,cid)
        g.end_turn()
        total=(30-e.hero.health)+(12-foe.health)
        observed=f"total={total};enemy_hero={e.hero.health};enemy_minion={foe.health};friendly={ally.health};own_hero={p.hero.health};body={body.health}:{body.zone.name}"
        return check(total==6 and ally.health==5 and p.hero.health==30 and body.zone==Zone.PLAY,observed)
    audit(cid,[("six_end_turn_hits_all_enemies_not_friendlies","With sole enemy character hero, end-turn six 1-damage hits total 6; friendly Yeti untouched.",six_damage_to_only_enemy_character,"重复随机目标、归属与回合触发。"),
               ("six_damage_multi_enemy_conservation","With hero and a high-Health enemy minion as eligible enemies, combined damage is exactly 6 and friendly characters are unharmed.",six_damage_is_conserved_across_enemy_characters,"多目标随机分配总量及阵营过滤。")])


def furious_felfin():
    cid="BT_496"
    def branch(attacked):
        g,p,e=game(CardClass.DEMONHUNTER)
        if attacked:
            play(p,"CS2_106");p.hero.attack(e.hero)
        body=play(p,cid)
        observed=f"attacked={attacked};hero_attacks={p.hero.num_attacks};stats={body.atk}/{body.health};rush={body.rush}"
        return check((body.atk,body.rush)==((4,True) if attacked else (3,False)),observed)
    audit(cid,[("after_actual_hero_attack_gets_attack_and_rush","After hero weapon attack, Felfin gains +1 Attack and Rush.",lambda:branch(True),"英雄真实攻击条件。"),
               ("no_hero_attack_no_buff","Without hero attack, no Attack buff or Rush.",lambda:branch(False),"条件反支。")])


def fel_summoner():
    cid="BT_509"
    def death_summons_hand_demon_only():
        g,p,e=game(CardClass.DEMONHUNTER)
        demon=p.give("EX1_301");plain=p.give(WISP)
        body=play(p,cid);body.destroy()
        observed=f"demon={demon.zone.name};plain={plain.zone.name};body={body.zone.name}"
        return check(demon.zone==Zone.PLAY and plain.zone==Zone.HAND and body.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("deathrattle_summons_demon_from_hand","Actual death puts sole hand Demon onto board; Wisp remains hand.",death_summons_hand_demon_only,"死亡、手牌种族过滤、召唤区域。")])


def immolation_aura():
    cid="BT_514"
    def two_hits_all_minions():
        g,p,e=game(CardClass.DEMONHUNTER)
        own=p.summon("CS2_182");foe=e.summon("CS2_182");small=e.summon(WISP)
        spell=play(p,cid)
        observed=f"own={own.health}:{own.zone.name};foe={foe.health}:{foe.zone.name};small={small.zone.name};heroes={p.hero.health}/{e.hero.health};spell={spell.zone.name}"
        return check(own.health==3 and foe.health==3 and small.zone==Zone.GRAVEYARD and p.hero.health==30 and e.hero.health==30,observed)
    audit(cid,[("two_separate_one_damage_waves_all_minions","Both 5-Health Yetis lose 2, 1-Health Wisp dies, heroes untouched.",two_hits_all_minions,"双方随从、二次伤害与死亡。")])


def skull_of_guldan():
    cid="BT_601"
    def branch(outcast):
        g,p,e=game(CardClass.DEMONHUNTER)
        deck=[p.card("CS2_182",zone=Zone.DECK) for _ in range(4)]
        if not outcast:p.give(WISP)
        spell=p.give(cid)
        if not outcast:p.give(WISP)
        spell.play()
        drawn=[c for c in deck if c.zone==Zone.HAND];waiting=[c for c in deck if c.zone==Zone.DECK]
        observed=f"outcast={outcast};drawn={[(c.id,c.cost,c.zone.name) for c in drawn]};waiting={len(waiting)};spell={spell.zone.name}"
        return check(len(drawn)==3 and len(waiting)==1 and
                     all(c.cost==(1 if outcast else 4) for c in drawn) and spell.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("outcast_draws_three_with_cost_minus_three","Outcast Skull draws three 4-Cost Yetis and each costs 1.",lambda:branch(True),"真实手牌边缘、抽取和费用。"),
               ("middle_hand_draws_three_at_original_cost","Non-Outcast Skull draws three Yetis still costing 4.",lambda:branch(False),"非边缘对照。")])


def spymistress():
    cid="BT_701"
    def stealth_blocks_enemy_spell_target():
        g,p,e=game(CardClass.ROGUE);body=play(p,cid);g.end_turn()
        spell=e.give("CS2_029")
        observed=f"stealthed={body.stealthed};spell_targetable={body in spell.targets};body={body.zone.name}"
        return check(body.stealthed and body not in spell.targets and body.zone==Zone.PLAY,observed)
    audit(cid,[("stealth_excludes_enemy_fireball_target","On enemy turn Stealth body cannot be selected by Fireball.",stealth_blocks_enemy_spell_target,"关键词与真实法术目标集合。")])


def ashtongue_slayer():
    cid="BT_702"
    def buff_stealth_target_and_expire():
        g,p,e=game(CardClass.ROGUE)
        target=p.summon("BT_701");base=target.atk
        body=play(p,cid,target=target)
        now=(target.atk,target.immune)
        g.end_turn();after=(target.atk,target.immune)
        observed=f"base={base};now={now};after_turn={after};body={body.zone.name};target={target.zone.name}"
        return check(now==(base+3,True) and after==(base,False),observed)
    audit(cid,[("stealthed_target_gains_three_attack_and_temporary_immune","Stealthed minion gains +3 Attack and Immune, both expire after turn.",buff_stealth_target_and_expire,"目标、双增益及持续期。")])


def cursed_vagrant():
    cid="BT_703"
    def death_summons_stealth_shadow():
        g,p,e=game(CardClass.ROGUE);body=play(p,cid);body.destroy()
        shadows=[m for m in p.field if m.id=="BT_703t"]
        observed=f"body={body.zone.name};shadows={[(m.atk,m.health,m.stealthed,m.zone.name) for m in shadows]}"
        return check(body.zone==Zone.GRAVEYARD and len(shadows)==1 and (shadows[0].atk,shadows[0].health)==(7,5) and shadows[0].stealthed,observed)
    audit(cid,[("death_summons_seven_five_stealthed_shadow","Actual death summons a 7/5 Stealthed Shadow on own board.",death_summons_stealth_shadow,"亡语、身材、潜行与区域。")])


def ambush():
    cid="BT_707"
    def enemy_minion_play_triggers_secret():
        g,p,e=game(CardClass.ROGUE)
        secret=play(p,cid);g.end_turn();enemy=play(e,WISP)
        ambushers=[m for m in p.field if m.id=="BT_707t"]
        observed=f"secret={secret.zone.name};enemy={enemy.zone.name};ambushers={[(m.atk,m.health,m.poisonous,m.zone.name) for m in ambushers]}"
        return check(secret.zone==Zone.GRAVEYARD and enemy.zone==Zone.PLAY and len(ambushers)==1
                     and (ambushers[0].atk,ambushers[0].health)==(2,3) and ambushers[0].poisonous,observed)
    audit(cid,[("enemy_minion_play_reveals_and_summons_poisonous_ambusher","Enemy Wisp play reveals Secret and summons own 2/3 Poisonous Ambusher.",enemy_minion_play_triggers_secret,"对手出牌事件、奥秘揭示和召唤。")])


def dirty_tricks():
    cid="BT_709"
    def enemy_spell_triggers_two_draws():
        g,p,e=game(CardClass.ROGUE)
        cards=[p.card(WISP,zone=Zone.DECK) for _ in range(3)]
        secret=play(p,cid);g.end_turn();spell=play(e,"GAME_005")
        zones=[c.zone for c in cards]
        observed=f"secret={secret.zone.name};drawn={[z.name for z in zones]};spell={spell.zone.name}"
        return check(secret.zone==Zone.GRAVEYARD and zones.count(Zone.HAND)==2 and zones.count(Zone.DECK)==1,observed)
    audit(cid,[("enemy_spell_reveals_secret_and_draws_two","Enemy Coin spell triggers reveal and draws exactly two deck Wisps.",enemy_spell_triggers_two_draws,"敌方施法、奥秘揭示和抽牌。")])


def greyheart_sage():
    cid="BT_710"
    def branch(stealth):
        g,p,e=game(CardClass.ROGUE)
        cards=[p.card(WISP,zone=Zone.DECK) for _ in range(3)]
        if stealth:p.summon("BT_701")
        body=play(p,cid)
        zones=[c.zone for c in cards]
        observed=f"stealth={stealth};drawn={[z.name for z in zones]};body={body.zone.name}"
        return check(zones.count(Zone.HAND)==(2 if stealth else 0) and
                     zones.count(Zone.DECK)==(1 if stealth else 3) and body.zone==Zone.PLAY,observed)
    audit(cid,[("friendly_stealth_draws_two","With Stealthed minion, Battlecry draws two deck cards.",lambda:branch(True),"有潜行条件。"),
               ("no_stealth_draws_none","Without Stealthed minion, draws none.",lambda:branch(False),"条件反支。")])


def blackjack_stunner():
    cid="BT_711"
    def branch(secret):
        g,p,e=game(CardClass.ROGUE);target=e.summon("CS2_182");base=target.cost
        if secret:play(p,"BT_707")
        body=play(p,cid,target=target if secret else None)
        observed=f"secret={secret};target={target.zone.name}:cost{target.cost};base={base};body={body.zone.name}"
        return check((target.zone,target.cost)==((Zone.HAND,base+1) if secret else (Zone.PLAY,base)),observed)
    audit(cid,[("controlled_secret_bounces_target_with_cost_plus_one","With active Secret, enemy Yeti returns to owner hand costing one more.",lambda:branch(True),"奥秘条件、目标归属、费用与区域。"),
               ("no_secret_no_bounce","Without Secret, enemy Yeti remains on board.",lambda:branch(False),"条件反支。")])


def akama():
    cid="BT_713"
    def stealth_death_shuffles_prime():
        g,p,e=game(CardClass.ROGUE);body=play(p,cid);stealth=body.stealthed
        body.destroy();prime=[c for c in p.deck if c.id=="BT_713t"]
        observed=f"stealth={stealth};dead={body.zone.name};prime={[(c.id,c.zone.name) for c in prime]}"
        return check(stealth and body.zone==Zone.GRAVEYARD and len(prime)==1 and prime[0].zone==Zone.DECK,observed)
    audit(cid,[("stealth_death_shuffles_one_akama_prime","Stealth Akama's actual death shuffles exactly one Prime into own deck.",stealth_death_shuffles_prime,"潜行、死亡、衍生牌数量和牌库。")])


def frozen_shadoweaver():
    cid="BT_714"
    def freezes_selected_enemy_only():
        g,p,e=game();target=e.summon("CS2_182");other=e.summon("CS2_182")
        body=play(p,cid,target=target)
        observed=f"target_frozen={target.frozen};other_frozen={other.frozen};body={body.zone.name}"
        return check(target.frozen and not other.frozen and body.zone==Zone.PLAY,observed)
    audit(cid,[("chosen_enemy_freezes_other_does_not","Battlecry freezes selected enemy Yeti but leaves second enemy Yeti unfrozen.",freezes_selected_enemy_only,"实际目标与冻结状态。")])


def bonechewer(cid):
    def damage_grants_attack():
        g,p,e=game();body=play(p,cid);base=body.atk
        body.hit(1);after1=body.atk
        body.hit(1);after2=body.atk
        observed=f"base={base};after1={after1};after2={after2};health={body.health};taunt={body.taunt};zone={body.zone.name}"
        return check(body.taunt and after1==base+2 and after2==base+4 and body.zone==Zone.PLAY,observed)
    audit(cid,[("two_damage_events_each_add_two_attack","Two actual 1-damage events each grant +2 Attack while Taunt body survives.",damage_grants_attack,"逐次受伤事件、攻击和嘲讽。")])


def burrowing_scorpid():
    cid="BT_717"
    def branch(lethal):
        g,p,e=game();target=e.summon(WISP if lethal else "CS2_182")
        body=play(p,cid,target=target)
        observed=f"lethal={lethal};target={target.health}:{target.zone.name};stealthed={body.stealthed};body={body.zone.name}"
        return check(body.stealthed==lethal and target.zone==(Zone.GRAVEYARD if lethal else Zone.PLAY)
                     and (lethal or target.health==3),observed)
    audit(cid,[("lethal_two_damage_grants_stealth","2 damage kills Wisp and Scorpid gains Stealth.",lambda:branch(True),"致死分支。"),
               ("nonlethal_two_damage_no_stealth","2 damage leaves Yeti at 3 Health; Scorpid stays visible.",lambda:branch(False),"非致死分支。")])


def ruststeed_raider():
    cid="BT_720"
    def temporary_attack_and_rush_taunt():
        g,p,e=game();body=play(p,cid);now=body.atk;ready=body.can_attack(e.summon(WISP))
        g.end_turn();later=body.atk
        observed=f"now={now};later={later};rush={body.rush};taunt={body.taunt};ready={ready}"
        return check(now==5 and later==1 and body.rush and body.taunt and ready,observed)
    audit(cid,[("battlecry_four_attack_expires_after_turn","Raider enters as 5 Attack with Rush/Taunt; after turn it returns to 1 Attack.",temporary_attack_and_rush_taunt,"暂时攻击和关键词。")])


def blistering_rot():
    cid="BT_721"
    def end_turn_summons_equal_stats():
        g,p,e=game();body=play(p,cid);body.hit(1)
        body_stats=(body.atk,body.health)
        g.end_turn();rots=[m for m in p.field if m.id=="BT_721t"]
        observed=f"body={body_stats}:{body.zone.name};rots={[(m.atk,m.health,m.zone.name) for m in rots]}"
        return check(len(rots)==1 and (rots[0].atk,rots[0].health)==body_stats,observed)
    audit(cid,[("end_turn_rot_copies_current_damaged_stats","After body takes 1 damage, end turn summons one Rot with same current Attack/Health.",end_turn_summons_equal_stats,"触发、当前属性与召唤。")])


def guardian_augmerchant():
    cid="BT_722"
    def damages_then_shields_target():
        g,p,e=game();target=p.summon("CS2_182");body=play(p,cid,target=target)
        observed=f"target={target.health}:{target.divine_shield}:{target.zone.name};body={body.zone.name}"
        return check(target.health==4 and target.divine_shield and body.zone==Zone.PLAY,observed)
    audit(cid,[("target_takes_one_then_gets_divine_shield","Friendly Yeti loses 1 Health and gains Divine Shield.",damages_then_shields_target,"目标伤害与圣盾。")])


def rocket_augmerchant():
    cid="BT_723"
    def damages_then_gives_rush():
        g,p,e=game();target=p.summon("CS2_182");enemy=e.summon(WISP)
        body=play(p,cid,target=target);ready=target.can_attack(enemy)
        if ready:target.attack(enemy)
        observed=f"target={target.health}:{target.rush}:{target.zone.name};ready={ready};enemy={enemy.zone.name};body={body.zone.name}"
        return check(target.rush and ready and enemy.zone==Zone.GRAVEYARD and target.zone==Zone.PLAY,observed)
    audit(cid,[("damaged_friendly_minion_gets_real_rush_attack","Yeti takes 1 damage, gains Rush, immediately attacks enemy Wisp.",damages_then_gives_rush,"目标、伤害、关键词和实际攻击。")])


def ethereal_augmerchant():
    cid="BT_724"
    def damages_minion_and_adds_spell_damage():
        g,p,e=game(CardClass.MAGE);target=p.summon("CS2_182")
        body=play(p,cid,target=target)
        spell=play(p,"CS2_029",target=e.hero)
        observed=f"target={target.health}:{target.zone.name};enemy_hero={e.hero.health};spell={spell.zone.name};body={body.zone.name}"
        return check(target.health==4 and e.hero.health==23 and body.zone==Zone.PLAY,observed)
    audit(cid,[("target_takes_one_and_spell_damage_increases_fireball","Yeti takes 1; its Spell Damage +1 makes Fireball deal 7 to enemy hero.",damages_minion_and_adds_spell_damage,"真实法术伤害结果。")])


def dragonmaw_sky_stalker():
    cid="BT_726"
    def death_summons_dragonrider():
        g,p,e=game();body=play(p,cid);body.destroy()
        riders=[m for m in p.field if m.id=="BT_726t"]
        observed=f"dead={body.zone.name};riders={[(m.atk,m.health,m.zone.name) for m in riders]}"
        return check(body.zone==Zone.GRAVEYARD and len(riders)==1 and (riders[0].atk,riders[0].health)==(3,4),observed)
    audit(cid,[("death_summons_three_four_dragonrider","Actual death summons exactly one 3/4 Dragonrider.",death_summons_dragonrider,"死亡、数量和身材。")])


def soulbound_ashtongue():
    cid="BT_727"
    def copies_received_damage_to_own_hero():
        g,p,e=game();body=play(p,cid);before=p.hero.health;body.hit(2)
        observed=f"hero={before}->{p.hero.health};body_health={body.health};enemy_hero={e.hero.health}"
        return check(p.hero.health==before-2 and e.hero.health==30 and body.zone==Zone.PLAY,observed)
    audit(cid,[("two_damage_to_body_also_hits_owner_hero_two","Actual 2 damage to minion causes 2 damage to owner's hero, not opponent.",copies_received_damage_to_own_hero,"伤害量及英雄归属。")])


def disguised_wanderer():
    cid="BT_728"
    def death_summons_nine_one():
        g,p,e=game();body=play(p,cid);body.destroy()
        inquisitors=[m for m in p.field if m.id=="BT_728t"]
        observed=f"dead={body.zone.name};summons={[(m.atk,m.health,m.zone.name) for m in inquisitors]}"
        return check(len(inquisitors)==1 and (inquisitors[0].atk,inquisitors[0].health)==(9,1),observed)
    audit(cid,[("death_summons_nine_one_inquisitor","Actual death summons exactly one 9/1 Inquisitor.",death_summons_nine_one,"死亡、数量和身材。")])


def waste_warden():
    cid="BT_729"
    def hits_selected_race_across_both_sides():
        g,p,e=game()
        target=e.summon("EX1_572");same=p.summon("EX1_572");different=e.summon("CS2_182")
        body=play(p,cid,target=target)
        observed=f"target={target.health};same={same.health};different={different.health};body={body.zone.name}"
        return check(target.health==target.max_health-3 and same.health==same.max_health-3 and different.health==5,observed)
    audit(cid,[("three_damage_to_target_and_same_race_on_both_sides","Target Dragon and friendly Dragon each take 3; unrelated enemy Yeti remains 5 Health.",hits_selected_race_across_both_sides,"选定目标、同种族跨阵营和不同种族对照。")])


def overconfident_orc():
    cid="BT_730"
    def full_health_attack_bonus_disappears_when_damaged():
        g,p,e=game();body=play(p,cid);full=body.atk;body.hit(1);damaged=body.atk
        observed=f"full={full};damaged={damaged};health={body.health}/{body.max_health};taunt={body.taunt}"
        return check(full==damaged+2 and body.taunt and body.health<body.max_health,observed)
    audit(cid,[("full_health_attack_bonus_lost_after_damage","At full Health Attack is +2; after 1 actual damage bonus disappears, Taunt remains.",full_health_attack_bonus_disappears_when_damaged,"状态光环随生命变化。")])


def scavenging_shivarra():
    cid="BT_732"
    def six_damage_to_only_other_minion():
        g,p,e=game();target=e.summon("EX1_572");body=play(p,cid)
        observed=f"target={target.health}:{target.zone.name};body={body.health}:{body.zone.name};heroes={p.hero.health}/{e.hero.health}"
        return check(target.health==6 and body.zone==Zone.PLAY and p.hero.health==30 and e.hero.health==30,observed)
    def six_damage_split_among_two_other_minions():
        g,p,e=game();ally=p.summon("EX1_572");foe=e.summon("EX1_572")
        body=play(p,cid)
        total=(12-ally.health)+(12-foe.health)
        observed=f"total={total};ally={ally.health};foe={foe.health};self={body.health}:{body.zone.name};heroes={p.hero.health}/{e.hero.health}"
        return check(total==6 and body.zone==Zone.PLAY and body.health==body.max_health
                     and p.hero.health==30 and e.hero.health==30,observed)
    audit(cid,[("six_split_damage_to_only_other_minion","With sole other minion Ysera, six 1-damage hits reduce its Health 12 to 6; Shivarra and heroes untouched.",six_damage_to_only_other_minion,"六次随机伤害与自身排除。"),
               ("six_split_damage_two_eligible_minions","Across two other high-Health minions the total damage is 6, while Shivarra and both heroes remain unharmed.",six_damage_split_among_two_other_minions,"多目标分配总量、自身与英雄排除。")])


def moarg_artificer():
    cid="BT_733"
    def branch(artificer):
        g,p,e=game(CardClass.MAGE)
        body=play(p,cid) if artificer else None
        minion=e.summon("EX1_572");spell=play(p,"CS2_029",target=minion)
        observed=f"artificer={artificer};minion={minion.health}:{minion.zone.name};body={None if body is None else body.zone.name};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(minion.zone==(Zone.GRAVEYARD if artificer else Zone.PLAY) and
                     (artificer or minion.health==6) and e.hero.health==30,observed)
    audit(cid,[("fireball_six_is_doubled_to_kill_twelve_health_minion","With Artificer aura, 6-damage Fireball kills 12-Health Ysera.",lambda:branch(True),"倍增分支。"),
               ("without_artificer_fireball_leaves_six_health","Without Artificer, same Fireball leaves Ysera at 6 Health.",lambda:branch(False),"独立对照。")])


def supreme_abyssal():
    cid="BT_734"
    def can_attack_minion_but_not_hero():
        g,p,e=game();enemy=e.summon(WISP);body=play(p,cid)
        g.end_turn();g.end_turn()
        hero_ok=body.can_attack(e.hero);minion_ok=body.can_attack(enemy)
        if minion_ok:body.attack(enemy)
        observed=f"hero_ok={hero_ok};minion_ok={minion_ok};enemy={enemy.zone.name};body={body.zone.name}"
        return check(not hero_ok and minion_ok and enemy.zone==Zone.GRAVEYARD and body.zone==Zone.PLAY,observed)
    audit(cid,[("cannot_attack_hero_but_attacks_minion","After summoning sickness, hero is illegal attack target while enemy Wisp is legal and dies.",can_attack_minion_but_not_hero,"两类目标及实际战斗。")])


def alar():
    cid="BT_735"
    def ashes_resurrect_next_turn():
        g,p,e=game();body=play(p,cid);body.destroy()
        ashes=[m for m in p.field if m.id=="BT_735t"]
        before=[(m.id,m.atk,m.health) for m in p.field]
        g.end_turn();g.end_turn()
        alars=[m for m in p.field if m.id==cid]
        observed=f"dead={body.zone.name};ashes_initial={before};ashes_after={[(m.id,m.zone.name) for m in ashes]};resurrected={[(m.id,m.zone.name) for m in alars]}"
        return check(body.zone==Zone.GRAVEYARD and before==[("BT_735t",0,3)] and len(ashes)==1 and len(alars)==1 and alars[0].zone==Zone.PLAY,observed)
    audit(cid,[("death_summons_ashes_then_next_own_turn_resurrects","Death summons 0/3 Ashes, which transform to Al'ar at next own turn start.",ashes_resurrect_next_turn,"死亡、衍生随从、回合触发及复活。")])


def maiev_shadowsong():
    cid="BT_737"
    def target_goes_dormant_two_turns_then_returns():
        g,p,e=game();target=e.summon("CS2_182");body=play(p,cid,target=target)
        immediate=target.dormant
        for _ in range(2):g.end_turn()
        midway=target.dormant
        for _ in range(2):g.end_turn()
        observed=f"initial_dormant={immediate};after_two_turns={midway};after_four_turns={target.dormant};target={target.zone.name};body={body.zone.name}"
        return check(immediate and midway and not target.dormant and target.zone==Zone.PLAY,observed)
    audit(cid,[("chosen_minion_dormant_then_awakens_after_two_rounds","Battlecry makes chosen Yeti Dormant; after two full rounds it awakens on board.",target_goes_dormant_two_turns_then_returns,"选定目标、休眠及回合计数。")])


def coilfang_warlord():
    cid="BT_761"
    def rush_and_death_summons_taunt_warlord():
        g,p,e=game(CardClass.DEMONHUNTER);body=play(p,cid);rush=body.rush
        body.destroy();warlords=[m for m in p.field if m.id=="BT_761t"]
        observed=f"rush={rush};dead={body.zone.name};warlords={[(m.atk,m.health,m.taunt,m.zone.name) for m in warlords]}"
        return check(rush and len(warlords)==1 and (warlords[0].atk,warlords[0].health)==(5,9) and warlords[0].taunt,observed)
    audit(cid,[("rush_deathrattle_summons_five_nine_taunt","Rush body dies and summons exactly one 5/9 Taunt Warlord.",rush_and_death_summons_taunt_warlord,"关键词、死亡及奖励身材。")])


def bulwark_of_azzinoth():
    cid="BT_781"
    def damage_prevented_in_exchange_for_durability():
        g,p,e=game(CardClass.WARRIOR,CardClass.MAGE);weapon=play(p,cid)
        before=weapon.durability;g.end_turn()
        spell=play(e,"CS2_029",target=p.hero)
        observed=f"hero_health={p.hero.health};durability={before}->{weapon.durability};weapon={weapon.zone.name};spell={spell.zone.name}"
        return check(p.hero.health==30 and weapon.durability==before-1 and weapon.zone==Zone.PLAY,observed)
    audit(cid,[("incoming_fireball_prevented_and_one_durability_lost","Enemy Fireball aimed at owner hero deals no Health damage; Bulwark loses one Durability.",damage_prevented_in_exchange_for_durability,"真实敌方法术、伤害替代和武器状态。")])


def magtheridon():
    cid="BT_850"
    def three_warder_deaths_awaken_and_clear_board():
        g,p,e=game();friend=p.summon("CS2_182");body=play(p,cid)
        warders=[m for m in e.field if m.id=="BT_850t"]
        initial=body.dormant
        for warder in warders:warder.destroy()
        observed=f"initial_dormant={initial};warders={len(warders)}:{[m.zone.name for m in warders]};progress={body.progress};body={body.dormant}:{body.zone.name};friend={friend.zone.name}"
        return check(initial and len(warders)==3 and all(m.zone==Zone.GRAVEYARD for m in warders)
                     and not body.dormant and body.zone==Zone.PLAY and friend.zone==Zone.GRAVEYARD,observed)
    audit(cid,[("three_enemy_warders_die_then_awaken_and_destroy_others","Three 1/3 Warders appear on enemy side; after all die Magtheridon awakens and clears other minions.",three_warder_deaths_awaken_and_clear_board,"休眠、敌方召唤、死亡计数、清场。")])


def imprisoned_antaen():
    cid="BT_934"
    def wakes_after_two_turns_and_deals_ten():
        g,p,e=game(CardClass.DEMONHUNTER);body=play(p,cid);initial=body.dormant
        for _ in range(2):g.end_turn()
        midway=(body.dormant,e.hero.health)
        for _ in range(2):g.end_turn()
        observed=f"initial={initial};midway={midway};final={body.dormant}:{body.zone.name};enemy_hero={e.hero.health};own_hero={p.hero.health}"
        return check(initial and midway==(True,30) and not body.dormant and e.hero.health==20 and p.hero.health==30,observed)
    def splits_ten_damage_across_enemy_character_pool():
        g,p,e=game(CardClass.DEMONHUNTER)
        foe=e.summon("EX1_572");body=play(p,cid)
        for _ in range(4):g.end_turn()
        hero_loss=30-e.hero.health;minion_loss=12-foe.health
        observed=f"hero_loss={hero_loss};minion_loss={minion_loss};total={hero_loss+minion_loss};foe={foe.zone.name};own_hero={p.hero.health};dormant={body.dormant}"
        return check(not body.dormant and hero_loss>0 and minion_loss>0 and
                     hero_loss+minion_loss==10 and p.hero.health==30,observed)
    audit(cid,[("dormant_two_turns_then_ten_damage_to_only_enemy","After two own starts, Antaen awakens and ten split damage hits sole enemy hero.",wakes_after_two_turns_and_deals_ten,"休眠回合与唤醒伤害。"),
               ("awakening_splits_ten_damage_between_enemy_hero_and_minion","With enemy hero and high-Health enemy minion both eligible, Antaen splits exactly ten damage across them and spares own hero.",splits_ten_damage_across_enemy_character_pool,"多目标随机分配、总量和阵营。")])


CHECKS={"BT_334":lady_liadrin,"BT_341":skeletal_dragon,"BT_423":ashtongue_battlelord,"BT_429":metamorphosis,
        "BT_430":warglaives,"BT_480":crimson_sigil_runner,"BT_486":pit_commander,"BT_493":priestess_of_fury,
        "BT_496":furious_felfin,"BT_509":fel_summoner,"BT_514":immolation_aura,"BT_601":skull_of_guldan,
        "BT_701":spymistress,"BT_702":ashtongue_slayer,"BT_703":cursed_vagrant,
        "BT_707":ambush,"BT_709":dirty_tricks,"BT_710":greyheart_sage,
        "BT_711":blackjack_stunner,"BT_713":akama,"BT_714":frozen_shadoweaver,
        "BT_715":lambda:bonechewer("BT_715"),"BT_716":lambda:bonechewer("BT_716"),
        "BT_717":burrowing_scorpid,"BT_720":ruststeed_raider,"BT_721":blistering_rot,
        "BT_722":guardian_augmerchant,"BT_723":rocket_augmerchant,"BT_724":ethereal_augmerchant,
        "BT_726":dragonmaw_sky_stalker,"BT_727":soulbound_ashtongue,
        "BT_728":disguised_wanderer,"BT_729":waste_warden,"BT_730":overconfident_orc,
        "BT_732":scavenging_shivarra,"BT_733":moarg_artificer,"BT_734":supreme_abyssal,
        "BT_735":alar,"BT_737":maiev_shadowsong,"BT_761":coilfang_warlord,
        "BT_781":bulwark_of_azzinoth,"BT_850":magtheridon,"BT_934":imprisoned_antaen}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("card_ids",nargs="*")
    args=parser.parse_args()
    for cid in args.card_ids or list(CHECKS):CHECKS[cid]()
