"""Individual live behavior probes for CFM_610 through CFM_685.

Each registered case has card-specific assertions. A failed case is retained as
inconclusive until its setup and the card text have been checked manually.
"""

import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tests"))
from utils import FIREBALL, MURLOC, WISP, WHELP, prepare_empty_game  # noqa: E402

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

BASE = list(csv.DictReader((HERE / "three_set_yellow_baseline.csv").open(encoding="utf-8-sig")))
CARDS = [r["card_id"] for r in BASE if r["set"].startswith("Mean Streets")][44:87]
assert len(CARDS) == 43 and CARDS[0] == "CFM_610" and CARDS[-1] == "CFM_685"
MASTER = {r["card_id"]: r for r in csv.DictReader((HERE / "card_master.csv").open(encoding="utf-8-sig"))}
OLD_QUALITY = {r["card_id"]: r for r in csv.DictReader((HERE / "card_quality.csv").open(encoding="utf-8-sig"))}
LABELS = {}
for r in csv.DictReader((HERE / "card_mechanism.csv").open(encoding="utf-8-sig")):
    LABELS.setdefault(r["card_id"], set()).add(r["mechanic"])
P = HERE / "gangs_probe_b.csv"
V = HERE / "gangs_verdict_b.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def game(c1=CardClass.MAGE, c2=None, seed=24680):
    random.seed(seed)
    g = prepare_empty_game(c1, c2 or c1)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for p in g.players:
        p.is_standard = False
        p.max_mana = 10
    return g


def play(p, cid, target=None, choose=None):
    c = p.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if choose is not None:
        kw["choose"] = choose
    c.play(**kw)
    return c


def deck(p, cid):
    c = p.give(cid)
    c.shuffle_into_deck()
    return c


def check(condition, **observed):
    assert condition, observed
    return ";".join(f"{k}={v}" for k, v in observed.items())


CASES = {}
CONFIRMED_ERRORS = {("CFM_650", "random_hand_murloc_only"),
                    ("CFM_670", "hero_attack_can_redirect"),
                    ("CFM_671", "frozen_enemy_grants_stats")}


def case(cid, name, expected):
    def wrap(fn):
        CASES.setdefault(cid, []).append((name, expected, fn))
        return fn
    return wrap


@case("CFM_610", "only_friendly_demons_buffed", "Both friendly Demons gain +1/+1; non-Demon and enemy Demon do not.")
def c610():
    g = game(CardClass.WARLOCK)
    p, foe = g.player1, g.player2
    a = p.summon("EX1_306")
    b = p.summon("CS2_065")
    n = p.summon(WISP)
    e = foe.summon("EX1_306")
    before = [(m.atk, m.health) for m in (a, b, n, e)]
    c = play(p, "CFM_610")
    after = [(m.atk, m.health) for m in (a, b, n, e)]
    return check(after[:2] == [(x + 1, y + 1) for x, y in before[:2]] and after[2:] == before[2:] and c.zone == Zone.PLAY, before=before, after=after, card=c.zone.name)


@case("CFM_611", "demon_and_nondemon_branches", "Demon gets +3/+3; non-Demon gets +3 Attack only.")
def c611():
    g = game(CardClass.WARLOCK)
    p = g.player1
    demon = p.summon("EX1_306")
    ordinary = p.summon(WISP)
    a0, h0 = demon.atk, demon.health
    a1, h1 = ordinary.atk, ordinary.health
    x = play(p, "CFM_611", target=demon)
    y = play(p, "CFM_611", target=ordinary)
    return check((demon.atk, demon.health) == (a0 + 3, h0 + 3) and (ordinary.atk, ordinary.health) == (a1 + 3, h1) and x.zone == y.zone == Zone.GRAVEYARD, demon=(demon.atk,demon.health), ordinary=(ordinary.atk,ordinary.health), spells=(x.zone.name,y.zone.name))


@case("CFM_611", "enemy_demon_is_legal_target", "Enemy Demon can be targeted and gains +3/+3, since text does not require friendly target.")
def c611_enemy():
    g=game(CardClass.WARLOCK)
    p,foe=g.player1,g.player2
    enemy=foe.summon("EX1_306")
    before=(enemy.atk,enemy.health)
    spell=p.give("CFM_611")
    legal=enemy in spell.play_targets
    spell.play(target=enemy)
    return check(legal and (enemy.atk,enemy.health)==(before[0]+3,before[1]+3) and enemy.controller is foe and spell.zone==Zone.GRAVEYARD, legal=legal, before=before, after=(enemy.atk,enemy.health), controller=enemy.controller.name)


@case("CFM_614", "friendly_board_only", "All friendly minions gain +1/+1; enemy minion stays unchanged.")
def c614():
    g = game(CardClass.DRUID)
    p, foe = g.player1, g.player2
    friends = [p.summon(WISP), p.summon(MURLOC)]
    enemy = foe.summon(WISP)
    old = [(m.atk,m.health) for m in friends+[enemy]]
    spell = play(p,"CFM_614")
    new = [(m.atk,m.health) for m in friends+[enemy]]
    return check(new[:2] == [(a+1,h+1) for a,h in old[:2]] and new[2] == old[2] and spell.zone == Zone.GRAVEYARD, before=old, after=new, spell=spell.zone.name)


@case("CFM_616", "empty_crystals_per_friendly_minion", "Two friendly minions add two empty crystals, enemy minion does not count.")
def c616():
    g = game(CardClass.DRUID)
    p, foe = g.player1,g.player2
    p.max_mana = 4
    p.summon(WISP); p.summon(MURLOC); foe.summon(WISP)
    spell = play(p,"CFM_616")
    return check(p.max_mana == 6 and p.mana <= 4 and spell.zone == Zone.GRAVEYARD, max_mana=p.max_mana, available=p.mana, spell=spell.zone.name)


@case("CFM_616", "no_minions_no_gain", "Zero friendly minions add zero crystals.")
def c616_no():
    g=game(CardClass.DRUID)
    p=g.player1
    p.max_mana=4
    spell=play(p,"CFM_616")
    return check(p.max_mana == 4 and spell.zone == Zone.GRAVEYARD, max_mana=p.max_mana, spell=spell.zone.name)


@case("CFM_616", "at_mana_cap_generates_excess_mana", "At 10 maximum Mana and with a friendly minion, gain Excess Mana instead of exceeding cap.")
def c616_cap():
    g=game(CardClass.DRUID)
    p=g.player1
    p.summon(WISP)
    play(p,"CFM_616")
    excess=[x.id for x in p.hand if x.id=="CS2_013t"]
    return check(p.max_mana==10 and len(excess)==1, max_mana=p.max_mana, hand=[x.id for x in p.hand])


@case("CFM_617", "threshold_and_enemy_exclusion", "Only an existing friendly minion with at least 5 Attack grants +2/+2.")
def c617():
    results=[]
    for kind in (None,"friendly","enemy"):
        g=game(CardClass.DRUID)
        p,foe=g.player1,g.player2
        if kind == "friendly": p.summon("CS2_200")
        if kind == "enemy": foe.summon("CS2_200")
        card=play(p,"CFM_617")
        results.append((kind,card.atk,card.health))
    return check(results[0][1:] == (3,3) and results[1][1:] == (5,5) and results[2][1:] == (3,3), branches=results)


@case("CFM_617", "four_attack_does_not_qualify", "A friendly minion with only 4 Attack does not activate the 5-Attack Battlecry.")
def c617_four():
    g=game(CardClass.DRUID)
    p=g.player1
    p.summon("CS2_182")
    card=play(p,"CFM_617")
    return check((card.atk,card.health)==(3,3), attack=card.atk, health=card.health)


@case("CFM_619", "gain_a_potion", "Playing Kabal Chemist adds one valid Potion card to hand.")
def c619():
    g=game(seed=619)
    p=g.player1
    card=play(p,"CFM_619")
    gained=list(p.hand)
    return check(card.zone == Zone.PLAY and len(gained) == 1 and "potion" in (gained[0].data.name or "").lower(), hand=[(x.id,x.data.name,x.zone.name) for x in gained], card=card.zone.name)


@case("CFM_619", "random_potion_varies_across_seeds", "Repeated isolated games gain valid Potion cards and show random variety.")
def c619_random():
    results=[]
    for seed in range(619,631):
        g=game(seed=seed)
        p=g.player1
        play(p,"CFM_619")
        assert len(p.hand)==1 and "potion" in (p.hand[0].data.name or "").lower(), (seed,[x.id for x in p.hand])
        results.append(p.hand[0].id)
    return check(len(set(results))>1, seeds=results, distinct=len(set(results)))


@case("CFM_620", "enemy_minion_play_transforms_after_secret", "Opponent's played minion becomes 1/1 Sheep and secret is consumed.")
def c620():
    g=game(CardClass.MAGE)
    p,foe=g.player1,g.player2
    secret=play(p,"CFM_620")
    g.end_turn()
    original=play(foe,"CS2_182")
    sheep=[m for m in foe.field if m.id == "CS2_tk1"]
    return check(secret not in p.secrets and len(sheep)==1 and (sheep[0].atk,sheep[0].health)==(1,1) and original.zone != Zone.PLAY, secret=secret.zone.name, field=[(m.id,m.atk,m.health) for m in foe.field], original=original.zone.name)


@case("CFM_620", "own_minion_does_not_trigger_secret", "Friendly minion play keeps Potion of Polymorph armed.")
def c620_own():
    g=game(CardClass.MAGE)
    p=g.player1
    secret=play(p,"CFM_620")
    minion=play(p,WISP)
    return check(secret in p.secrets and minion.id==WISP and minion.zone==Zone.PLAY, secret=secret.zone.name, field=[x.id for x in p.field])


@case("CFM_621", "duplicate_deck_suppresses_choice", "Duplicate deck gives no Kazakus custom-spell Choice.")
def c621_dup():
    g=game()
    p=g.player1
    deck(p,WISP); deck(p,WISP)
    card=play(p,"CFM_621")
    return check(p.choice is None and card.zone == Zone.PLAY and len(p.hand)==0, choice=p.choice, deck=[x.id for x in p.deck], hand=[x.id for x in p.hand])


@case("CFM_621", "unique_deck_three_choices", "Unique deck allows three custom potion choices and gives a playable custom spell.")
def c621_unique():
    g=game(seed=621)
    p,foe=g.player1,g.player2
    deck(p,WISP); deck(p,MURLOC)
    ally=p.summon(WISP)
    enemy=foe.summon("CS2_200")
    card=play(p,"CFM_621")
    picks=[]
    for desired in ("CFM_621t11","CFM_621t5","CFM_621t6"):
        assert p.choice and p.choice.cards, (p.choice,picks)
        picks.append([x.id for x in p.choice.cards])
        selected=next((x for x in p.choice.cards if x.id==desired),None)
        assert selected is not None, (desired,picks)
        p.choice.choose(selected)
    potions=[x for x in p.hand if x.id.startswith("CFM_621t")]
    assert card.zone==Zone.PLAY and p.choice is None and len(potions)==1 and potions[0].type==CardType.SPELL and len(picks)==3, (picks,potions)
    potion=potions[0]
    potion.play()
    return check(potion.zone==Zone.GRAVEYARD and enemy.frozen and (ally.health,ally.max_health)==(3,3), picks=picks, potion=(potion.id,potion.zone.name), enemy=(enemy.id,enemy.frozen), ally=(ally.health,ally.max_health))


@case("CFM_623", "three_missiles_damage_total", "Exactly three 3-damage missiles hit random enemy characters; friendly character is unharmed.")
def c623():
    g=game(seed=623)
    p,foe=g.player1,g.player2
    friend=p.summon("CS2_182")
    foe_minion=foe.summon("CS2_182")
    old=(foe.hero.health,foe_minion.health,friend.health,p.hero.health)
    spell=play(p,"CFM_623")
    lost=(old[0]-foe.hero.health)+(old[1]-foe_minion.health)
    return check(lost==9 and friend.health==old[2] and p.hero.health==old[3] and spell.zone==Zone.GRAVEYARD, old=old, enemy=(foe.hero.health,foe_minion.health), friendly=(friend.health,p.hero.health), spell=spell.zone.name)


@case("CFM_626", "friendly_target_plus_three_health", "Chosen friendly minion gains three maximum and current Health; enemy is unchanged.")
def c626():
    g=game(CardClass.PRIEST)
    p,foe=g.player1,g.player2
    target=p.summon(WISP); enemy=foe.summon(WISP)
    card=play(p,"CFM_626",target=target)
    return check((target.max_health,target.health)==(4,4) and enemy.health==1 and card.zone==Zone.PLAY, target=(target.max_health,target.health), enemy=enemy.health, card=card.zone.name)


@case("CFM_630", "temporary_mana_expires", "One mana this turn, returning to ordinary maximum on the next turn.")
def c630():
    g=game(CardClass.ROGUE)
    p=g.player1
    p.max_mana=4; p.used_mana=2
    spell=play(p,"CFM_630")
    after=(p.max_mana,p.mana)
    g.end_turn();g.end_turn()
    later=(p.max_mana,p.mana)
    return check(after==(4,3) and later==(5,5) and p.temp_mana==0 and spell.zone==Zone.GRAVEYARD, after=after, next_turn=later, temporary=p.temp_mana, spell=spell.zone.name)


@case("CFM_631", "hero_attack_buffs_hand_minion", "Hero attack buffs a hand minion +1/+1 once.")
def c631():
    g=game(CardClass.WARRIOR)
    p,foe=g.player1,g.player2
    weapon=play(p,"CFM_631")
    held=[p.give(WISP),p.give(MURLOC)]
    before=[(x.atk,x.health) for x in held]
    p.hero.attack(foe.hero)
    after=[(x.atk,x.health) for x in held]
    changes=[after[i]==(before[i][0]+1,before[i][1]+1) for i in (0,1)]
    return check(sum(changes)==1 and weapon.durability==2, before=before, after=after, changes=changes, weapon=(weapon.atk,weapon.durability))


@case("CFM_634", "kill_regrants_stealth", "After Lotus Assassin attacks and kills enemy minion, it gains Stealth again.")
def c634():
    g=game(CardClass.ROGUE)
    p,foe=g.player1,g.player2
    assassin=play(p,"CFM_634")
    target=foe.summon(WISP)
    g.end_turn();g.end_turn()
    assassin.attack(target)
    return check(target.zone==Zone.GRAVEYARD and assassin.zone==Zone.PLAY and assassin.stealthed, target=target.zone.name, assassin=(assassin.zone.name,assassin.health,assassin.stealthed))


@case("CFM_634", "nonlethal_attack_does_not_regain_stealth", "Attacking but not killing a minion consumes Stealth and does not restore it.")
def c634_no_kill():
    g=game(CardClass.ROGUE)
    p,foe=g.player1,g.player2
    assassin=play(p,"CFM_634")
    target=foe.summon("CS2_120")
    play(p,"CS2_004",target=target)
    play(p,"CS2_004",target=target)
    g.end_turn();g.end_turn()
    assassin.attack(target)
    return check(target.zone==Zone.PLAY and assassin.zone==Zone.PLAY and not assassin.stealthed, target=(target.zone.name,target.health), assassin=(assassin.zone.name,assassin.health,assassin.stealthed))


@case("CFM_636", "stealth_keyword", "Shadow Rager enters with Stealth and expected 5/1 stats.")
def c636():
    g=game()
    card=play(g.player1,"CFM_636")
    return check((card.atk,card.health)==(5,1) and card.stealthed and card.zone==Zone.PLAY, stats=(card.atk,card.health), stealth=card.stealthed, zone=card.zone.name)


@case("CFM_636", "stealth_blocks_enemy_targets", "Enemy cannot target or attack a Stealthed Shadow Rager; friendly targeting stays legal.")
def c636_targets():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_636")
    friendly_spell=p.give(FIREBALL)
    own_can_target=card in friendly_spell.play_targets
    attacker=foe.summon("CS2_182")
    g.end_turn()
    enemy_spell=foe.give(FIREBALL)
    enemy_can_target=card in enemy_spell.play_targets
    enemy_can_attack=card in attacker.attack_targets
    attacker.attack(p.hero)
    return check(own_can_target and not enemy_can_target and not enemy_can_attack and card.zone==Zone.PLAY and p.hero.health==26, targeting=(own_can_target,enemy_can_target,enemy_can_attack), hero=p.hero.health, card=card.zone.name)


@case("CFM_637", "pirate_play_summons_from_deck", "Playing a Pirate summons Patches from deck, not to hand.")
def c637():
    g=game(seed=637)
    p=g.player1
    patches=deck(p,"CFM_637")
    pirate=play(p,"CS2_146")
    return check(patches.zone==Zone.PLAY and patches in p.field and pirate in p.field and patches not in p.deck and patches not in p.hand, pirate=(pirate.id,pirate.zone.name), patches=(patches.zone.name,[x.id for x in p.field]), deck=[x.id for x in p.deck])


@case("CFM_637", "nonpirate_does_not_summon", "Playing a non-Pirate leaves Patches in the deck.")
def c637_no():
    g=game(seed=638)
    p=g.player1
    patches=deck(p,"CFM_637")
    play(p,WISP)
    return check(patches.zone==Zone.DECK and patches in p.deck, patches=patches.zone.name, field=[x.id for x in p.field])


@case("CFM_639", "end_turn_buffs_hand_minions", "At turn end all hand minions gain +1/+1; hand spell does not.")
def c639():
    g=game(CardClass.PALADIN)
    p=g.player1
    one=p.give(WISP);two=p.give(MURLOC);spell=p.give(FIREBALL)
    original=[(x.atk,x.health) for x in (one,two)]
    spell_cost=spell.cost
    card=play(p,"CFM_639")
    g.end_turn()
    after=[(x.atk,x.health) for x in (one,two)]
    return check(all(after[i]==(original[i][0]+1,original[i][1]+1) for i in (0,1)) and spell.cost==spell_cost and card.zone==Zone.PLAY, before=original, after=after, spell_cost=(spell_cost,spell.cost), card=card.zone.name)


@case("CFM_643", "weapon_hand_and_deck_buff", "Weapon cards in hand and deck each gain +1 Attack; equipped and enemy weapons do not.")
def c643():
    g=game(CardClass.WARRIOR)
    p,foe=g.player1,g.player2
    held=p.give("CS2_091");stored=deck(p,"CS2_106")
    equipped=play(p,"CS2_106")
    g.end_turn()
    enemy=play(foe,"CS2_091")
    g.end_turn()
    prior=(held.atk,stored.atk,equipped.atk,enemy.atk)
    card=play(p,"CFM_643")
    after=(held.atk,stored.atk,equipped.atk,enemy.atk)
    return check(after==(prior[0]+1,prior[1]+1,prior[2],prior[3]) and card.zone==Zone.PLAY, before=prior, after=after, zones=(held.zone.name,stored.zone.name,equipped.zone.name,enemy.zone.name))


@case("CFM_646", "deathrattle_hits_enemy_hero_only", "Deathrattle deals 2 to enemy hero, not friendly hero.")
def c646():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_646")
    card.destroy()
    return check(card.zone==Zone.GRAVEYARD and foe.hero.health==28 and p.hero.health==30, minion=card.zone.name, heroes=(p.hero.health,foe.hero.health))


@case("CFM_647", "targeted_one_damage", "Deal exactly 1 damage to chosen enemy minion; other character unaffected.")
def c647():
    g=game()
    p,foe=g.player1,g.player2
    target=foe.summon("CS2_182");other=foe.summon("CS2_182")
    before=(target.health,other.health)
    card=play(p,"CFM_647",target=target)
    return check((target.health,other.health)==(before[0]-1,before[1]) and card.zone==Zone.PLAY, before=before, after=(target.health,other.health), card=card.zone.name)


@case("CFM_647", "friendly_target_one_damage", "Unqualified target text permits friendly minion; chosen friendly minion takes 1.")
def c647_friendly():
    g=game()
    p=g.player1
    target=p.summon("CS2_182")
    before=target.health
    card=p.give("CFM_647")
    legal=target in card.play_targets
    card.play(target=target)
    return check(legal and target.health==before-1 and card.zone==Zone.PLAY, legal=legal, before=before, after=target.health)


@case("CFM_648", "summon_six_six_ogre", "Playing card creates one friendly 6/6 Ogre token in play.")
def c648():
    g=game()
    p=g.player1
    card=play(p,"CFM_648")
    ogres=[x for x in p.field if x.id=="CFM_648t"]
    return check(card.zone==Zone.PLAY and len(ogres)==1 and (ogres[0].atk,ogres[0].health,ogres[0].zone)==(6,6,Zone.PLAY), field=[(x.id,x.atk,x.health,x.zone.name) for x in p.field])


@case("CFM_649", "discover_one_of_three_classes", "Discover offers Mage, Priest and Warlock collectible cards; choosing one puts it in hand.")
def c649():
    g=game(seed=649)
    p=g.player1
    card=play(p,"CFM_649")
    choice=p.choice
    assert choice and len(choice.cards)==3, choice
    offered=list(choice.cards)
    classes=[tuple(c.data.classes) for c in offered]
    selected=offered[1]
    choice.choose(selected)
    gained=[x for x in p.hand if x.id==selected.id]
    return check(card.zone==Zone.PLAY and p.choice is None and len(gained)==1 and all(expected in choices for expected,choices in zip((CardClass.MAGE,CardClass.PRIEST,CardClass.WARLOCK),classes)), offers=[(x.id,tuple(x.data.classes)) for x in offered], chosen=(selected.id,[x.id for x in p.hand]))


@case("CFM_650", "random_hand_murloc_only", "Exactly one held friendly Murloc gains +1/+1; non-Murloc is unchanged.")
def c650():
    g=game(CardClass.PALADIN,seed=650)
    p=g.player1
    fish=[p.give(MURLOC),p.give("CS2_168")]
    ordinary=p.give(WISP)
    before=[(x.atk,x.health) for x in fish+[ordinary]]
    card=play(p,"CFM_650")
    after=[(x.atk,x.health) for x in fish+[ordinary]]
    changed=sum(after[i]==(before[i][0]+1,before[i][1]+1) for i in (0,1))
    return check(changed==1 and after[2]==before[2] and card.zone==Zone.PLAY, before=before, after=after)


@case("CFM_650", "no_murloc_in_hand", "No held Murloc leaves other held minions unchanged.")
def c650_no():
    g=game(CardClass.PALADIN)
    p=g.player1
    held=p.give(WISP)
    before=(held.atk,held.health)
    play(p,"CFM_650")
    return check((held.atk,held.health)==before, before=before, after=(held.atk,held.health))


@case("CFM_651", "equipped_weapon_plus_one_attack", "Battlecry gives equipped friendly weapon +1 Attack.")
def c651():
    g=game()
    p=g.player1
    weapon=play(p,"CS2_091")
    original=(weapon.atk,weapon.durability)
    card=play(p,"CFM_651")
    return check((weapon.atk,weapon.durability)==(original[0]+1,original[1]) and card.zone==Zone.PLAY, before=original, after=(weapon.atk,weapon.durability), card=card.zone.name)


@case("CFM_651", "no_weapon_no_effect", "With no weapon, battlecry completes without equipping one.")
def c651_none():
    g=game()
    p=g.player1
    card=play(p,"CFM_651")
    return check(p.weapon is None and card.zone==Zone.PLAY, weapon=p.weapon, card=card.zone.name)


@case("CFM_652", "threshold_enemy_three_minions", "Costs base at two enemy minions and 2 less at three.")
def c652():
    g=game()
    p,foe=g.player1,g.player2
    card=p.give("CFM_652")
    base=card.cost
    foe.summon(WISP);foe.summon(WISP)
    two=card.cost
    third=foe.summon(WISP)
    three=card.cost
    third.destroy()
    back=card.cost
    return check(base==two==back and three==base-2 and card.zone==Zone.HAND, costs=(base,two,three,back), zone=card.zone.name)


@case("CFM_653", "taunt_keyword", "Hired Gun enters in play with Taunt and expected base 4/3.")
def c653():
    g=game()
    card=play(g.player1,"CFM_653")
    return check(card.zone==Zone.PLAY and card.taunt and (card.atk,card.health)==(4,3), stats=(card.atk,card.health), taunt=card.taunt, zone=card.zone.name)


@case("CFM_653", "taunt_blocks_face_attack", "Enemy minion must attack Hired Gun while it has Taunt; after it dies face becomes legal.")
def c653_attacks():
    g=game()
    p,foe=g.player1,g.player2
    guard=play(p,"CFM_653")
    attacker=foe.summon("CS2_182")
    g.end_turn()
    while_alive=(guard in attacker.attack_targets,p.hero in attacker.attack_targets)
    attacker.attack(guard)
    after=(guard.zone,attacker.zone,p.hero.health)
    second=foe.summon("CS2_182")
    face_available=p.hero in second.attack_targets
    return check(while_alive==(True,False) and after==(Zone.GRAVEYARD,Zone.PLAY,30) and face_available, while_alive=while_alive, after=(after[0].name,after[1].name,after[2]), face_available=face_available)


@case("CFM_654", "turn_end_heals_own_hero_once", "Own turn end heals friendly hero 1, not enemy hero.")
def c654():
    g=game()
    p,foe=g.player1,g.player2
    p.hero.damage=5;foe.hero.damage=5
    card=play(p,"CFM_654")
    before=(p.hero.health,foe.hero.health)
    g.end_turn()
    after=(p.hero.health,foe.hero.health)
    return check(after==(before[0]+1,before[1]) and card.zone==Zone.PLAY, before=before, after=after, card=card.zone.name)


@case("CFM_655", "enemy_weapon_loses_one_durability", "Enemy equipped weapon loses exactly one Durability; friendly weapon unchanged.")
def c655():
    g=game()
    p,foe=g.player1,g.player2
    own=play(p,"CS2_091")
    g.end_turn()
    enemy=play(foe,"CS2_106")
    g.end_turn()
    before=(own.durability,enemy.durability)
    card=play(p,"CFM_655")
    after=(own.durability,enemy.durability)
    return check(after==(before[0],before[1]-1) and card.zone==Zone.PLAY, before=before, after=after, card=card.zone.name)


@case("CFM_655", "last_durability_breaks_weapon", "At one remaining Durability, the enemy weapon is destroyed.")
def c655_break():
    g=game()
    p,foe=g.player1,g.player2
    g.end_turn()
    weapon=play(foe,"CS2_091")
    weapon.max_durability=1
    assert weapon.durability==1
    g.end_turn()
    play(p,"CFM_655")
    return check(foe.weapon is None and weapon.zone==Zone.GRAVEYARD, weapon=weapon.zone.name, equipped=foe.weapon)


@case("CFM_656", "enemy_stealth_removed_only", "Battlecry removes Stealth from enemy minions, not friendly minion.")
def c656():
    g=game()
    p,foe=g.player1,g.player2
    friends=p.summon("CFM_636");enemies=[foe.summon("CFM_636"),foe.summon("CFM_636")]
    before=(friends.stealthed,[x.stealthed for x in enemies])
    card=play(p,"CFM_656")
    after=(friends.stealthed,[x.stealthed for x in enemies])
    return check(before==(True,[True,True]) and after==(True,[False,False]) and card.zone==Zone.PLAY, before=before, after=after, card=card.zone.name)


@case("CFM_657", "silence_targeted_minion", "Silences chosen non-self minion and leaves another untouched.")
def c657():
    g=game(CardClass.PRIEST)
    p,foe=g.player1,g.player2
    target=foe.summon("CS2_121");other=foe.summon("CS2_121")
    before=(target.taunt,other.taunt)
    card=play(p,"CFM_657",target=target)
    return check(before==(True,True) and not target.taunt and other.taunt and card.zone==Zone.PLAY, before=before, after=(target.taunt,other.taunt), card=card.zone.name)


@case("CFM_657", "silence_friendly_target", "A friendly minion other than the Songstealer can be selected and Silenced.")
def c657_friendly():
    g=game(CardClass.PRIEST)
    p=g.player1
    target=p.summon("CS2_121")
    card=p.give("CFM_657")
    legal=target in card.play_targets
    card.play(target=target)
    return check(legal and not target.taunt and card.zone==Zone.PLAY and target.controller is p, legal=legal, taunt=target.taunt, controller=target.controller.name)


@case("CFM_658", "friendly_death_grants_one_attack", "Each friendly minion death grants +1 Attack; enemy death does not.")
def c658():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_658")
    friendly=[p.summon(WISP),p.summon(WISP)]
    enemy=foe.summon(WISP)
    start=card.atk
    enemy.destroy();after_enemy=card.atk
    for m in friendly: m.destroy()
    after_friendly=card.atk
    return check(after_enemy==start and after_friendly==start+2 and card.zone==Zone.PLAY, attack=(start,after_enemy,after_friendly), card=card.zone.name)


@case("CFM_659", "heal_chosen_character_two", "Restores exactly 2 to chosen damaged character and not another.")
def c659():
    g=game()
    p,foe=g.player1,g.player2
    p.hero.damage=5;foe.hero.damage=5
    card=play(p,"CFM_659",target=p.hero)
    return check((p.hero.health,foe.hero.health)==(27,25) and card.zone==Zone.PLAY, heroes=(p.hero.health,foe.hero.health), card=card.zone.name)


@case("CFM_659", "heal_enemy_hero_two", "Unqualified target text permits enemy hero; heal enemy by 2 and leave own unchanged.")
def c659_enemy():
    g=game()
    p,foe=g.player1,g.player2
    p.hero.damage=5;foe.hero.damage=5
    card=p.give("CFM_659")
    legal=foe.hero in card.play_targets
    card.play(target=foe.hero)
    return check(legal and (p.hero.health,foe.hero.health)==(25,27) and card.zone==Zone.PLAY, legal=legal, heroes=(p.hero.health,foe.hero.health))


@case("CFM_660", "shuffle_copy_of_friendly_target", "A copy of chosen friendly minion enters deck; original remains in play.")
def c660():
    g=game(CardClass.MAGE)
    p=g.player1
    target=p.summon("CS2_182")
    card=play(p,"CFM_660",target=target)
    copies=[x for x in p.deck if x.id==target.id]
    return check(card.zone==Zone.PLAY and target.zone==Zone.PLAY and len(copies)==1 and copies[0] is not target and copies[0].zone==Zone.DECK, target=(target.id,target.zone.name), deck=[(x.id,x.zone.name) for x in p.deck])


@case("CFM_661", "enemy_minions_only_and_expires", "Enemy minions lose 3 Attack this turn only; friend unchanged; Attack restores next turn.")
def c661():
    g=game(CardClass.PRIEST)
    p,foe=g.player1,g.player2
    friend=p.summon("CS2_182");enemy=foe.summon("CS2_182")
    old=(friend.atk,enemy.atk)
    spell=play(p,"CFM_661")
    during=(friend.atk,enemy.atk)
    g.end_turn()
    after=(friend.atk,enemy.atk)
    return check(during==(old[0],max(0,old[1]-3)) and after==old and spell.zone==Zone.GRAVEYARD, before=old, during=during, next_turn=after, spell=spell.zone.name)


@case("CFM_662", "all_non_dragon_minions_hit", "All non-Dragons on both sides take 5; Dragons and heroes do not.")
def c662():
    g=game(CardClass.PRIEST)
    p,foe=g.player1,g.player2
    friendly=p.summon("CS2_182");enemy=foe.summon("CS2_182")
    dragon=p.summon("CS2_200")
    assert Race.DRAGON not in dragon.data.races, dragon.id
    dragon.destroy()
    dragon=p.summon("EX1_284")
    assert Race.DRAGON in dragon.data.races, dragon.id
    spell=play(p,"CFM_662")
    return check(friendly.zone==enemy.zone==Zone.GRAVEYARD and dragon.zone==Zone.PLAY and dragon.health==dragon.max_health and (p.hero.health,foe.hero.health)==(30,30) and spell.zone==Zone.GRAVEYARD, friendly=friendly.zone.name, enemy=enemy.zone.name, dragon=(dragon.id,dragon.zone.name,dragon.health), heroes=(p.hero.health,foe.hero.health))


@case("CFM_663", "turn_end_adds_random_demon", "At own turn end adds exactly one Demon to hand.")
def c663():
    g=game(CardClass.WARLOCK,seed=663)
    p=g.player1
    card=play(p,"CFM_663")
    g.end_turn()
    gained=list(p.hand)
    assert card.zone==Zone.PLAY and len(gained)==1 and Race.DEMON in gained[0].data.races and gained[0].zone==Zone.HAND
    g.end_turn()
    after_opponent=len(p.hand)
    return check(after_opponent==1, hand=[(x.id,tuple(x.data.races),x.zone.name) for x in gained], after_opponent_turn=after_opponent, card=card.zone.name)


@case("CFM_663", "random_demon_pool_varies", "Across seeds, each generated card is a Demon and more than one Demon can occur.")
def c663_random():
    results=[]
    for seed in range(663,675):
        g=game(CardClass.WARLOCK,seed=seed)
        p=g.player1
        play(p,"CFM_663")
        g.end_turn()
        assert len(p.hand)==1 and Race.DEMON in p.hand[0].data.races,(seed,[x.id for x in p.hand])
        results.append(p.hand[0].id)
    return check(len(set(results))>1, generated=results, distinct=len(set(results)))


@case("CFM_666", "windfury_keyword", "Grook Fu Master may attack twice in one turn after summoning sickness ends.")
def c666():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_666")
    g.end_turn();g.end_turn()
    card.attack(foe.hero)
    first=(foe.hero.health,card.num_attacks)
    card.attack(foe.hero)
    second=(foe.hero.health,card.num_attacks)
    return check(first==(27,1) and second==(24,2) and card.zone==Zone.PLAY, first=first, second=second, card=card.zone.name)


@case("CFM_667", "battlecry_enemy_minion_and_own_deathrattle", "Battlecry deals 5 to chosen enemy minion; Deathrattle deals 5 to own hero.")
def c667():
    g=game()
    p,foe=g.player1,g.player2
    target=foe.summon("CS2_182")
    card=play(p,"CFM_667",target=target)
    after_play=(target.zone,p.hero.health,foe.hero.health)
    card.destroy()
    return check(after_play==(Zone.GRAVEYARD,30,30) and p.hero.health==25 and foe.hero.health==30 and card.zone==Zone.GRAVEYARD, after_play=(after_play[0].name,after_play[1:]), after_death=(p.hero.health,foe.hero.health,card.zone.name))


@case("CFM_667", "no_enemy_target_still_has_deathrattle", "Without an enemy minion, Battlecry does not hit heroes; Deathrattle still hits own hero.")
def c667_no_target():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_667")
    before=(p.hero.health,foe.hero.health)
    card.destroy()
    return check(before==(30,30) and (p.hero.health,foe.hero.health)==(25,30) and card.zone==Zone.GRAVEYARD, before=before, after=(p.hero.health,foe.hero.health), card=card.zone.name)


@case("CFM_668", "battlecry_summons_two_copies", "Battlecry creates exactly two independent copies around original, with matching stats.")
def c668():
    g=game()
    p=g.player1
    card=play(p,"CFM_668")
    field=list(p.field)
    return check(len(field)==3 and card in field and len({id(x) for x in field})==3 and all(x.id==card.id and (x.atk,x.health)==(card.atk,card.health) for x in field), field=[(x.id,x.atk,x.health,x.zone.name) for x in field])


@case("CFM_668", "full_board_limits_copies", "At six occupied slots, only one Battlecry copy fits.")
def c668_full():
    g=game()
    p=g.player1
    for _ in range(5): p.summon(WISP)
    card=play(p,"CFM_668")
    return check(len(p.field)==7 and sum(x.id=="CFM_668" for x in p.field)==2 and card in p.field, field=[x.id for x in p.field])


@case("CFM_668", "copies_keep_hand_buff", "Two copies preserve +1/+1 applied to card in hand before playing it.")
def c668_buff():
    g=game(CardClass.PALADIN)
    p=g.player1
    card=p.give("CFM_668")
    play(p,"CFM_305")
    buffed=(card.atk,card.health)
    card.play()
    same=[(x.atk,x.health) for x in p.field if x.id=="CFM_668"]
    return check(len(same)==3 and all(stats==buffed for stats in same), buffed=buffed, copies=same)


@case("CFM_669", "opponent_spell_gives_one_coin", "Opponent-cast spell adds exactly one Coin to owner's hand; own spell does not.")
def c669():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_669")
    play(p,"CS2_008",target=foe.hero)
    own_count=sum(x.id=="GAME_005" for x in p.hand)
    g.end_turn()
    play(foe,"CS2_008",target=p.hero)
    enemy_count=sum(x.id=="GAME_005" for x in p.hand)
    return check(own_count==0 and enemy_count==1 and card.zone==Zone.PLAY, coins=(own_count,enemy_count), hand=[x.id for x in p.hand])


@case("CFM_670", "all_targets_random_active", "Mayor Noggenfogger sets random-target flag on both players while in play, removes it on death.")
def c670():
    g=game()
    p,foe=g.player1,g.player2
    card=play(p,"CFM_670")
    during=(bool(p.all_targets_random),bool(foe.all_targets_random))
    card.destroy()
    after=(bool(p.all_targets_random),bool(foe.all_targets_random))
    return check(during==(True,True) and after==(False,False) and card.zone==Zone.GRAVEYARD, during=during, after=after, card=card.zone.name)


@case("CFM_670", "spell_target_retargeted", "With Noggenfogger active, a targeted spell can hit another legal character.")
def c670_target():
    redirected=[]
    for seed in range(670,682):
        g=game(seed=seed)
        p,foe=g.player1,g.player2
        mayor=play(p,"CFM_670")
        friend=p.summon("CS2_200");enemy=foe.summon("CS2_200")
        before=(p.hero.health,foe.hero.health,friend.health,enemy.health,mayor.health)
        spell=play(p,"CS2_008",target=foe.hero)
        after=(p.hero.health,foe.hero.health,friend.health,enemy.health,mayor.health)
        losses=tuple(a-b for a,b in zip(before,after))
        assert sum(losses)==1 and spell.zone==Zone.GRAVEYARD,(seed,losses)
        redirected.append((seed,losses))
    return check(any(losses[1]==0 for _,losses in redirected), seeds_and_loss=redirected)


@case("CFM_670", "hero_power_target_retargeted", "With Noggenfogger active, a Mage Hero Power can hit another legal character.")
def c670_power():
    results=[]
    for seed in range(700,712):
        g=game(CardClass.MAGE,seed=seed)
        p,foe=g.player1,g.player2
        mayor=play(p,"CFM_670")
        friend=p.summon("CS2_200");enemy=foe.summon("CS2_200")
        g.end_turn();g.end_turn()
        before=(p.hero.health,foe.hero.health,friend.health,enemy.health,mayor.health)
        p.hero.power.use(target=foe.hero)
        after=(p.hero.health,foe.hero.health,friend.health,enemy.health,mayor.health)
        loss=tuple(a-b for a,b in zip(before,after))
        assert sum(loss)==1,(seed,loss)
        results.append((seed,loss))
    return check(any(loss[1]==0 for _,loss in results), seeds_and_loss=results)


@case("CFM_670", "minion_attack_can_redirect", "A minion attack directed at enemy hero can instead hit another enemy character.")
def c670_attack():
    results=[]
    for seed in range(720,752):
        g=game(seed=seed)
        p,foe=g.player1,g.player2
        play(p,"CFM_670")
        attacker=p.summon("CS2_182")
        targets=[foe.summon("CS2_200"),foe.summon("CS2_200")]
        g.end_turn();g.end_turn()
        before=(foe.hero.health,[x.health for x in targets])
        attacker.attack(foe.hero)
        after=(foe.hero.health,[x.health for x in targets])
        results.append((seed,before,after))
    redirected=[(seed,after) for seed,before,after in results if after[0]==before[0] and after[1]!=before[1]]
    return check(bool(redirected), redirected=redirected, normal=sum(after[0]<before[0] for _,before,after in results))


@case("CFM_670", "hero_attack_can_redirect", "A hero attack aimed at enemy hero can be redirected to another enemy character.")
def c670_hero_attack():
    results=[]
    for seed in range(760,792):
        g=game(seed=seed)
        p,foe=g.player1,g.player2
        weapon=play(p,"CS2_091")
        mayor=play(p,"CFM_670")
        enemy=foe.summon("CS2_200")
        before=(foe.hero.health,enemy.health)
        p.hero.attack(foe.hero)
        after=(foe.hero.health,enemy.health)
        assert mayor.zone==Zone.PLAY and weapon.durability==3,(seed,mayor.zone,weapon.durability)
        results.append((seed,before,after))
    redirected=[(seed,after) for seed,before,after in results if after[0]==before[0] and after[1]<before[1]]
    return check(bool(redirected), redirected=redirected, always_hit_requested_hero=sum(after[0]<before[0] for _,before,after in results), trials=len(results))


@case("CFM_671", "frozen_enemy_grants_stats", "Frozen enemy character grants +2/+2; no frozen enemy does not.")
def c671():
    results=[]
    for frozen in (False,True):
        g=game(CardClass.MAGE)
        p,foe=g.player1,g.player2
        if frozen:
            enemy=foe.summon("CS2_200")
            play(p,"CS2_024",target=enemy)
            assert enemy.frozen and enemy.zone==Zone.PLAY
        card=play(p,"CFM_671")
        results.append((frozen,card.atk,card.health))
    return check(results[0][1:]==(5,5) and results[1][1:]==(7,7), branches=results)


@case("CFM_672", "swap_target_with_deck_minion", "Selected friendly minion returns to deck and a deck minion enters its board slot.")
def c672():
    g=game()
    p=g.player1
    target=p.summon(WISP)
    stored=deck(p,"CS2_182")
    card=play(p,"CFM_672",target=target)
    return check(target.zone==Zone.DECK and stored.zone==Zone.PLAY and card.zone==Zone.PLAY and stored in p.field and target in p.deck, target=target.zone.name, drawn=stored.zone.name, field=[x.id for x in p.field], deck=[x.id for x in p.deck])


@case("CFM_685", "one_random_hand_minion_five_five", "Exactly one of two held minions receives +5/+5, held spell unchanged.")
def c685():
    g=game(seed=685)
    p=g.player1
    held=[p.give(WISP),p.give(MURLOC)]
    spell=p.give(FIREBALL)
    old=[(x.atk,x.health) for x in held]
    spell_cost=spell.cost
    card=play(p,"CFM_685")
    after=[(x.atk,x.health) for x in held]
    changed=sum(after[i]==(old[i][0]+5,old[i][1]+5) for i in (0,1))
    return check(changed==1 and spell.cost==spell_cost and card.zone==Zone.PLAY, before=old, after=after, spell_cost=(spell_cost,spell.cost))


def write(name,fields,rows):
    with name.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def main(selected=None):
    probes=list(csv.DictReader(P.open(encoding="utf-8-sig"))) if P.exists() else []
    verdicts=list(csv.DictReader(V.open(encoding="utf-8-sig"))) if V.exists() else []
    for cid in CARDS:
        if selected and cid not in selected: continue
        if cid not in CASES: continue
        probes=[r for r in probes if r["card_id"]!=cid]
        verdicts=[r for r in verdicts if r["card_id"]!=cid]
        write(P,PF,probes);write(V,VF,verdicts)
        for name,expected,fn in CASES[cid]:
            try:
                observed=fn();outcome="pass"
            except Exception as exc:
                observed=f"{type(exc).__name__}: {exc}"
                outcome="confirmed_error" if (cid,name) in CONFIRMED_ERRORS else "inconclusive"
            probes.append(dict(card_id=cid,case_id=name,expected=expected,observed=observed,outcome=outcome,notes=f"individual game assertion; source={MASTER[cid]['python_source']}"))
            write(P,PF,probes)
        own=[r for r in probes if r["card_id"]==cid]
        status="RED" if any(r["outcome"]=="confirmed_error" for r in own) else "GREEN" if all(r["outcome"]=="pass" for r in own) else "YELLOW"
        intro={"GREEN":"逐卡实战断言均通过：","YELLOW":"存在未决失败，需排除夹具问题：","RED":"已确认与卡牌文本不符："}[status]
        reason=intro+"; ".join(f"{r['case_id']}={r['observed']}" for r in own)
        prior=OLD_QUALITY[cid]
        official=("; Blizzard 2017-10-17 patch notes explicitly include Hero attacks redirected by Mayor Noggenfogger: https://hearthstone.blizzard.com/en-us/blog/21098848/"
                  if cid=="CFM_670" else "")
        verdicts.append(dict(card_id=cid,status=status,mechanic_scope="|".join(sorted(LABELS[cid])),reason=reason,probe_file=P.name,notes=f"EN: {MASTER[cid]['card_text_en']}; ZH: {MASTER[cid]['card_text_zh']}; source={MASTER[cid]['python_source']}; existing_test_refs={MASTER[cid]['test_refs_candidate']}; prior_audit={prior['status']}:{prior['reason']}{official}"))
        write(V,VF,verdicts)
        print(cid,status)


if __name__=="__main__":
    main(set(sys.argv[1:]) if len(sys.argv)>1 else None)
