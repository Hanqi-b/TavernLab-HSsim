"""All launch-era Transfer Student boards and their observable effects."""
import pytest
from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.enums import BoardEnum
from fireplace.cards.utils import BASIC_HERO_POWERS, LACKEY_CARDS, LICH_KING_CARDS
from test_scholomance_transfer_student_red_fix import fixed_board_game
from utils import prepare_empty_game


BOARD_VARIANTS = [
    (BoardEnum.STORMWIND,'SCH_199t'),(BoardEnum.ORGRIMMAR,'SCH_199t2'),
    (BoardEnum.PANDARIA,'SCH_199t3'),(BoardEnum.STRANGLETHORN,'SCH_199t4'),
    (BoardEnum.NAXXRAMAS,'SCH_199t5'),(BoardEnum.GOBLINS_VS_GNOMES,'SCH_199t6'),
    (BoardEnum.BLACKROCK_MOUNTAIN,'SCH_199t7'),(BoardEnum.THE_GRAND_TOURNAMENT,'SCH_199t8'),
    (BoardEnum.EXCAVATION_SITE,'SCH_199t24'),(BoardEnum.THE_MUSEUM,'SCH_199t9'),
    (BoardEnum.WHISPERS_OF_THE_OLD_GODS,'SCH_199t10'),(BoardEnum.KARAZHAN,'SCH_199t11'),
    (BoardEnum.GADGETZAN,'SCH_199t12'),(BoardEnum.UNGORO,'SCH_199t13'),
    (BoardEnum.ICECROWN_CITADEL,'SCH_199t14'),(BoardEnum.THE_CATACOMBS,'SCH_199t15'),
    (BoardEnum.THE_WITCHWOOD,'SCH_199t16'),(BoardEnum.THE_BOOMSDAY_PROJECT,'SCH_199t17'),
    (BoardEnum.GURUBASHI_ARENA,'SCH_199t18'),(BoardEnum.DALARAN,'SCH_199t19'),
    (BoardEnum.ULDUM_TOMB,'SCH_199t20'),(BoardEnum.ULDUM_CITY,'SCH_199t25'),
    (BoardEnum.DRAGONBLIGHT,'SCH_199t21'),(BoardEnum.OUTLAND,'SCH_199t22'),
    (BoardEnum.SCHOLOMANCE,'SCH_199t23'),(999,'SCH_199t'),
]


@pytest.mark.parametrize('board,expected',BOARD_VARIANTS)
def test_sch_199_initial_and_generated_board_variants(board,expected):
    g,p,q=fixed_board_game(board)
    copies=[c for c in p.hand+p.deck if c.id.startswith('SCH_199')]
    assert len(copies)==6 and {c.id for c in copies}=={expected}
    generated=p.give('SCH_199')
    assert generated.id==expected


def ready():
    g=prepare_empty_game(CardClass.MAGE,CardClass.MAGE)
    p,q=g.current_player,g.current_player.opponent
    p.discard_hand();q.discard_hand();p.max_mana=10;p.used_mana=0
    g.random.seed(937)
    return g,p,q


@pytest.mark.parametrize('cid,attributes',[
    ('SCH_199t',['divine_shield']),('SCH_199t4',['stealthed','poisonous']),
    ('SCH_199t16',['echo','rush']),('SCH_199t20',['reborn']),
])
def test_sch_199_keyword_forms(cid,attributes):
    _,p,_=ready();m=p.give(cid).play()
    assert all(getattr(m,a) for a in attributes)
    if cid=='SCH_199t16':assert any(c.id==cid for c in p.hand)
    if cid=='SCH_199t20':
        m.destroy(); assert len(p.field)==1 and p.field[0].health==1 and not p.field[0].reborn


def test_sch_199_targeted_battlecries():
    _,p,q=ready();m=p.summon('CS2_231')
    p.give('SCH_199t2').play(target=q.hero)
    assert q.hero.health==28
    p.give('SCH_199t3').play(target=m)
    assert (m.atk,m.health)==(2,3)


def test_sch_199_deathrattle_minion_and_spare_parts():
    _,p,_=ready();p.give('SCH_199t5').play().destroy()
    assert len(p.hand)==1 and p.hand[0].has_deathrattle
    p.discard_hand();m=p.give('SCH_199t6').play()
    assert len(p.hand)==1 and p.hand[0].data.spare_part
    m.destroy();assert len(p.hand)==2 and all(c.data.spare_part for c in p.hand)


def test_sch_199_end_turn_discount():
    g,p,_=ready();spell=p.give('CS2_029');p.give('SCH_199t7').play();g.end_turn()
    assert spell.cost==2


def test_sch_199_inspire_and_new_hero_power():
    _,p,q=ready();card=p.card('CS2_231',zone=Zone.DECK)
    p.give('SCH_199t8').play();p.hero.power.use(target=q.hero)
    assert card.zone==Zone.HAND
    p.give('SCH_199t9').play()
    old=p.hero.power;options=list(p.choice.cards)
    assert len(options)==3 and all(c.id in BASIC_HERO_POWERS and c.id!=old.id for c in options)
    p.choice.choose(options[0]);assert p.hero.power is options[0]


def test_sch_199_spends_all_remaining_mana():
    _,p,_=ready();p.give('SCH_199t10').play()
    assert p.mana==0 and len(p.field)==2 and p.field[-1].data.cost==8


@pytest.mark.parametrize('cid,pool',[
    ('SCH_199t11',{'KAR_073','KAR_077','KAR_091','KAR_075','KAR_076'}),
    ('SCH_199t19',set(LACKEY_CARDS)),
    ('SCH_199t25',{'ULD_718','ULD_717','ULD_715','ULD_172','ULD_707'}),
])
def test_sch_199_battlecry_generation(cid,pool):
    _,p,_=ready();p.give(cid).play();assert len(p.hand)==1 and p.hand[0].id in pool


def test_sch_199_hand_buff_and_adapt():
    _,p,_=ready();m=p.give('CS2_231');p.give('SCH_199t12').play()
    assert (m.atk,m.health)==(3,3)
    student=p.give('SCH_199t13').play();assert p.choice
    p.choice.choose(p.choice.cards[0]);assert student.buffs


def test_sch_199_death_knight_and_recruit():
    _,p,_=ready();p.give('SCH_199t14').play().destroy()
    assert len(p.hand)==1 and p.hand[0].id in LICH_KING_CARDS
    recruit=p.card('CS2_231',zone=Zone.DECK)
    p.give('SCH_199t15').play();assert recruit.zone==Zone.PLAY


@pytest.mark.parametrize('mana,expected',[(9,(2,2)),(10,(7,7))])
def test_sch_199_ten_mana_buff(mana,expected):
    _,p,_=ready();p.max_mana=mana;m=p.give('SCH_199t17').play()
    assert (m.atk,m.health)==expected and m.taunt


def test_sch_199_overkill_draws():
    _,p,q=ready();draw=p.card('CS2_231',zone=Zone.DECK)
    m=p.give('SCH_199t18').play();victim=q.summon('CS2_231');m.attack(victim)
    assert draw.zone==Zone.HAND


def test_sch_199_discovers_dragon():
    _,p,_=ready();p.give('SCH_199t21').play()
    options=list(p.choice.cards);assert options and all(Race.DRAGON in c.races for c in options)
    p.choice.choose(options[0]);assert options[0] in p.hand


def test_sch_199_dormant_awakening_hits_two_distinct_minions():
    g,p,q=ready();enemies=[q.summon('CS2_182') for _ in range(3)]
    m=p.give('SCH_199t22').play();assert m.dormant
    g.end_turn();g.end_turn();assert m.dormant
    g.end_turn();g.end_turn();assert not m.dormant
    assert sorted(e.health for e in enemies)==[2,2,5]


def test_sch_199_dual_class_and_weapon_generation():
    _,p,_=ready();p.give('SCH_199t23').play()
    assert len(p.hand)==1 and len(p.hand[0].classes)==2
    p.discard_hand();p.give('SCH_199t24').play()
    assert len(p.hand)==1 and p.hand[0].type==CardType.WEAPON
