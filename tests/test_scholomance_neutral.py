"""Behavioral contracts for every Scholomance neutral collectible."""
import pytest
from hearthstone.enums import CardClass, CardType, GameTag, Zone
from fireplace import cards
from fireplace.actions import CastSpell
from utils import prepare_empty_game


def ready():
    g = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    p, q = g.current_player, g.current_player.opponent
    for player in (p, q):
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    g.random.seed(521)
    return g, p, q


def test_sch_142_reader_draws_to_three():
    g,p,q = ready()
    for _ in range(5): p.card('CS2_231', zone=Zone.DECK)
    p.give('SCH_142').play()
    g.end_turn()
    assert len(p.hand) == 3 and len(p.deck) == 2


@pytest.mark.parametrize('cid,attack,health,keyword', [('SCH_143',5,1,'divine_shield'),('SCH_145',1,1,None)])
def test_neutral_printed_bodies(cid,attack,health,keyword):
    _,p,_ = ready()
    m=p.give(cid).play()
    assert (m.atk,m.health)==(attack,health)
    if keyword: assert getattr(m,keyword)


def test_sch_146_robes_aura_is_removed_when_silenced():
    _,p,q = ready()
    m=p.summon('CS2_231')
    robes=p.give('SCH_146').play()
    assert m.cant_be_targeted_by_abilities and m.cant_be_targeted_by_hero_powers
    assert not q.hero.cant_be_targeted_by_abilities
    robes.silence()
    assert not m.cant_be_targeted_by_abilities


def test_sch_157_cauldron_casts_spell_with_paid_cost(monkeypatch):
    g,p,q = ready()
    m=p.give('SCH_157').play()
    observed=[]
    original=CastSpell.do
    def record(self,source,spell,targets):
        observed.append(spell.data.cost)
        return original(self,source,spell,targets)
    monkeypatch.setattr(CastSpell,'do',record)
    p.give('GAME_005').play()
    assert observed == [0] and m.spellburst_used


def test_sch_160_wandmaker_gives_one_cost_class_spell():
    _,p,_ = ready()
    p.give('SCH_160').play()
    assert len(p.hand)==1
    assert p.hand[0].cost==1 and CardClass.MAGE in p.hand[0].classes


def test_sch_162_vectus_whelps_inherit_deathrattle():
    _,p,q = ready()
    p.summon('EX1_029').destroy()
    p.give('SCH_162').play()
    whelps=[c for c in p.field if c.id=='SCH_162t']
    assert len(whelps)==2 and all(c.has_deathrattle for c in whelps)
    whelps[0].destroy()
    assert q.hero.health==26


def test_sch_224_kelthuzad_revives_spell_victims_only():
    _,p,q=ready()
    p.summon('CS2_231').destroy()
    kt=p.give('SCH_224').play()
    victim=q.summon('CS2_231')
    p.give('CS2_008').play(target=victim)
    assert victim.zone==Zone.GRAVEYARD
    assert [m.id for m in p.field]==['SCH_224','CS2_231'] and kt.spellburst_used


def test_sch_230_magescribe_adds_two_class_spells_once():
    _,p,_=ready()
    p.give('SCH_230').play()
    p.give('GAME_005').play()
    assert len(p.hand)==2 and all(c.type==CardType.SPELL and CardClass.MAGE in c.classes for c in p.hand)
    p.give('GAME_005').play()
    assert len(p.hand)==2


@pytest.mark.parametrize('cid,delta,taunt',[('SCH_231',2,False),('SCH_232',1,True)])
def test_spellburst_attack_buffs(cid,delta,taunt):
    _,p,_=ready()
    m=p.give(cid).play(); base=m.atk
    p.give('GAME_005').play()
    assert m.atk==base+delta and m.taunt==taunt


def test_sch_245_steward_discovers_spell():
    _,p,_=ready()
    m=p.give('SCH_245').play()
    assert m.spellpower==1 and p.choice
    options=list(p.choice.cards)
    assert all(c.type==CardType.SPELL for c in options)
    p.choice.choose(options[0])
    assert options[0] in p.hand


def test_sch_248_pen_flinger_hits_hero_and_returns_repeatedly():
    _,p,q=ready()
    m=p.give('SCH_248').play(target=q.hero)
    assert q.hero.health==29
    p.give('GAME_005').play()
    assert m.zone==Zone.HAND
    m.play(target=q.hero)
    p.give('GAME_005').play()
    assert q.hero.health==28 and m.zone==Zone.HAND


@pytest.mark.parametrize('replace',[False,True])
def test_sch_259_sphere_choice_precedes_normal_draw(replace):
    g,p,q=ready()
    bottom=p.card('CS2_182',zone=Zone.DECK)
    top=p.card('CS2_231',zone=Zone.DECK)
    w=p.give('SCH_259').play()
    g.end_turn(); g.end_turn()
    assert p.choice and not p.hand and len(p.deck)==2
    p.choice.choose(p.choice.cards[1 if replace else 0])
    assert p.hand[0] is (bottom if replace else top)
    assert w.durability==(3 if replace else 4)
    assert p.deck[0] is (top if replace else bottom)


def test_sch_283_panthara_requires_power_this_turn():
    _,p,q=ready()
    card=p.card('CS2_231',zone=Zone.DECK)
    p.give('SCH_283').play()
    assert card.zone==Zone.DECK
    p.hero.power.use(target=q.hero)
    p.give('SCH_283').play()
    assert card.zone==Zone.HAND


def test_sch_311_broom_gives_existing_minions_rush():
    _,p,_=ready()
    m=p.summon('CS2_182'); broom=p.give('SCH_311').play()
    later=p.summon('CS2_231')
    assert m.rush and broom.rush and not later.rush


def test_sch_312_tour_guide_next_power_only():
    g,p,q=ready()
    p.give('SCH_312').play()
    assert p.hero.power.cost==0
    p.hero.power.use(target=q.hero)
    assert p.hero.power.cost==2
    g.end_turn();g.end_turn()
    assert p.hero.power.cost==2


def test_sch_313_tutor_hits_both_boards_except_self():
    _,p,q=ready()
    a=p.summon('CS2_182');b=q.summon('CS2_182')
    m=p.give('SCH_313').play();hp=m.health
    p.give('GAME_005').play()
    assert a.health==b.health==3 and m.health==hp


def test_sch_428_polkelt_orders_draws_highest_first():
    _,p,_=ready()
    for cid in ['CS2_231','CS2_182','CS2_029']:p.card(cid,zone=Zone.DECK)
    p.give('SCH_428').play()
    assert [c.cost for c in reversed(p.deck)]==[4,4,0]


def test_sch_530_substitute_requires_spell_damage():
    _,p,_=ready()
    p.give('SCH_530').play()
    assert len(p.field)==1
    p.summon('CS2_142');p.used_mana=0
    m=p.give('SCH_530').play()
    assert len([c for c in p.field if c.id=='SCH_530'])==3


def test_sch_605_thresher_damages_adjacent_minions():
    _,p,q=ready()
    enemies=[q.summon('CS2_182') for _ in range(3)]
    m=p.summon('SCH_605');m.turns_in_play=1
    m.attack(enemies[1])
    assert [e.health for e in enemies]==[1,1,1]


@pytest.mark.parametrize('cid,token,keyword',[('SCH_707','SCH_707t','rush'),('SCH_708','SCH_708t','stealthed'),('SCH_709','SCH_709t','taunt')])
def test_spectral_deathrattles(cid,token,keyword):
    _,p,_=ready()
    p.give(cid).play().destroy()
    assert len(p.hand)==1 and p.hand[0].id==token and getattr(p.hand[0],keyword)


def test_sch_710_ogremancer_only_opponent_spells():
    g,p,q=ready()
    p.give('SCH_710').play()
    p.give('GAME_005').play()
    assert len(p.field)==1
    g.end_turn();q.give('GAME_005').play()
    assert len(p.field)==2 and p.field[-1].id=='SCH_710t' and p.field[-1].taunt


def test_sch_711_protodrake_summons_seven_cost_minion():
    _,p,_=ready()
    p.give('SCH_711').play().destroy()
    assert len(p.field)==1 and p.field[0].data.cost==7


def test_sch_713_neophyte_tax_expires_after_enemy_turn():
    g,p,q=ready()
    spell=q.give('CS2_029')
    p.give('SCH_713').play()
    g.end_turn()
    assert spell.cost==5
    g.end_turn()
    assert spell.cost==4


def test_sch_714_elekk_remembers_both_players_spells():
    g,p,q=ready()
    m=p.give('SCH_714').play()
    p.give('GAME_005').play()
    g.end_turn(); q.give('CS2_008').play(target=p.hero)
    m.destroy()
    assert sorted(c.id for c in p.deck)==['CS2_008','GAME_005']


def test_sch_717_alabaster_copies_draw_for_one_mana():
    _,p,q=ready()
    p.give('SCH_717').play()
    original=q.card('CS2_029',zone=Zone.DECK)
    q.draw()
    assert original.zone==Zone.HAND
    assert len(p.hand)==1 and p.hand[0].id==original.id and p.hand[0].cost==1


def test_vectus_remembers_deathrattle_that_shuffled_its_owner():
    g, p, q = ready()
    malorne = p.summon("GVG_035")
    malorne.destroy()
    assert malorne.zone == Zone.DECK
    p.give("SCH_162").play()
    whelps = [m for m in p.field if m.id == "SCH_162t"]
    assert len(whelps) == 2 and all(m.has_deathrattle for m in whelps)
    whelps[0].destroy()
    assert whelps[0].zone == Zone.DECK


def test_kelthuzad_remembers_killed_minion_after_its_shuffle_deathrattle():
    g, p, q = ready()
    malorne = q.summon("GVG_035")
    malorne.damage = 2
    kel = p.summon("SCH_224")
    p.give("CS2_029").play(target=malorne)
    assert malorne.zone == Zone.DECK and kel.spellburst_used
    assert any(m.id == "GVG_035" for m in p.field)
