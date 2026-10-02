"""Behavior tests for the Mage/Rogue/Warrior Scholomance group."""
import pytest
from hearthstone.enums import CardClass, CardType, Zone
from fireplace.actions import CastSpell
from utils import prepare_empty_game


def ready():
    g=prepare_empty_game(CardClass.MAGE,CardClass.MAGE)
    p,q=g.current_player,g.current_player.opponent
    p.discard_hand();q.discard_hand()
    g.random.seed(2020)
    return g,p,q


def refill(p):p.used_mana=0


def test_sch_234_sophomore_generates_combo_card():
    _,p,_=ready();m=p.give('SCH_234').play();p.give('GAME_005').play()
    assert m.stealthed and len(p.hand)==1 and p.hand[0].has_combo


def test_sch_235_three_devolving_missiles():
    _,p,q=ready();q.summon('CS2_182')
    p.give('SCH_235').play()
    assert len(q.field)==1 and q.field[0].cost==1


def test_sch_237_athletic_studies_discount_consumed_once():
    _,p,_=ready();p.give('SCH_237').play()
    assert p.choice and all(m.rush for m in p.choice.cards)
    selected=p.choice.cards[0];p.choice.choose(selected)
    rush=p.give('SCH_311');assert rush.cost==0
    rush.play();assert selected.cost==selected.data.cost


def test_sch_238_scythe_cleave_only_for_current_turn():
    g,p,q=ready();w=p.give('SCH_238').play();p.give('GAME_005').play()
    enemies=[q.summon('CS2_182') for _ in range(3)]
    p.hero.attack(enemies[1]);assert [m.health for m in enemies]==[1,1,1]
    g.end_turn();g.end_turn()
    assert not any(b.id=='SCH_238e' for b in w.buffs)


def test_sch_241_firebrand_deals_four_without_spellpower_scaling():
    _,p,q=ready();p.summon('CS2_142');p.give('SCH_241').play()
    m=q.summon('CS2_182');p.give('GAME_005').play();assert m.health==1


def test_sch_243_wyrm_weaver_summons_two_mana_wyrms():
    _,p,_=ready();p.give('SCH_243').play();p.give('GAME_005').play()
    assert len([m for m in p.field if m.id=='NEW1_012'])==2


def test_sch_270_primordial_studies_supports_more_than_one_spellpower():
    _,p,_=ready();p.give('SCH_270').play()
    assert p.choice and all(m.spellpower>0 for m in p.choice.cards)
    p.choice.choose(p.choice.cards[0]);m=p.give('EX1_563')
    assert m.cost==8
    m.play();other=p.give('CS2_142');assert other.cost==2


def test_sch_273_ras_damage_scales_to_all_enemies():
    g,p,q=ready();p.summon('CS2_142');p.give('SCH_273').play();m=q.summon('CS2_182')
    g.end_turn();assert q.hero.health==28 and m.health==3


def test_sch_305_secret_passage_restores_unplayed_cards_and_keeps_generated_cards():
    g,p,q=ready();original=p.give('CS2_029')
    loans=[p.card('CS2_231',zone=Zone.DECK) for _ in range(5)]
    p.give('SCH_305').play()
    assert original.zone==Zone.SETASIDE and len(p.hand)==5 and p.cards_drawn_this_turn==0
    used=p.hand[0].play();generated=p.give('CS2_182')
    g.end_turn()
    assert original in p.hand and generated in p.hand and len(p.deck) == 4
    g.end_turn()
    assert original in p.hand and generated in p.hand and used.zone==Zone.PLAY
    # Four unused cards were returned, then the regular turn draw drew one.
    assert len(p.deck)==3 and sum(c in p.hand for c in loans)==1


def test_sch_310_lab_partner_spell_damage():
    _,p,_=ready();p.give('SCH_310').play();assert p.spellpower==1


def test_sch_317_playmaker_copies_rush_with_one_remaining_health():
    _,p,_=ready();p.give('SCH_317').play();m=p.give('SCH_425').play()
    copies=[c for c in p.field if c.id=='SCH_425']
    assert len(copies)==2 and sorted(c.health for c in copies)==[1,4]


def test_sch_337_troublemaker_ruffians_attack():
    g,p,q=ready();p.give('SCH_337').play();g.end_turn()
    assert len([m for m in p.field if m.id=='SCH_337t'])==2 and q.hero.health==24


def test_sch_348_combustion_excess_includes_spellpower_once():
    _,p,q=ready();p.summon('CS2_142')
    left=q.summon('CS2_182');middle=q.summon('CS2_231');right=q.summon('CS2_182')
    p.give('SCH_348').play(target=middle)
    assert middle.zone==Zone.GRAVEYARD and left.health==right.health==1


def test_sch_350_wand_thief_combo_discovers_mage_spell():
    _,p,_=ready();p.give('GAME_005').play();p.give('SCH_350').play()
    assert p.choice and all(CardClass.MAGE in c.classes for c in p.choice.cards)
    chosen=p.choice.cards[0];p.choice.choose(chosen);assert chosen in p.hand


def test_sch_351_jandice_illusion_dies_only_on_real_damage():
    _,p,_=ready();j=p.give('SCH_351').play()
    assert len(p.field)==3 and p.choice
    chosen=p.choice.cards[0];real=p.choice.cards[1];p.choice.choose(chosen)
    assert chosen.cost==real.cost==5
    # Enchantment identities and public text must be indistinguishable.
    assert chosen.buffs[-1].id==real.buffs[-1].id=='SCH_351e'
    chosen.divine_shield=False;chosen.hit(1)
    assert chosen.zone==Zone.GRAVEYARD and real.zone==Zone.PLAY


def test_sch_352_potion_copies_current_board_as_one_one_one_cost():
    _,p,_=ready();m=p.summon('CS2_182');m.hit(1)
    p.give('SCH_352').play()
    assert len(p.hand)==1 and p.hand[0].id==m.id
    assert (p.hand[0].atk,p.hand[0].health,p.hand[0].cost)==(1,1,1)
    assert (m.atk,m.health)==(4,4)


def test_sch_353_cram_session_draws_spell_damage_plus_one():
    _,p,_=ready();p.summon('CS2_142')
    for _ in range(4):p.card('CS2_231',zone=Zone.DECK)
    p.give('SCH_353').play();assert len(p.hand)==2


def test_sch_400_mozaki_gains_spell_damage_after_spell():
    _,p,q=ready();m=p.give('SCH_400').play()
    p.give('CS2_008').play(target=q.hero)
    assert q.hero.health==29 and m.spellpower==1
    p.give('CS2_008').play(target=q.hero)
    assert q.hero.health==27 and m.spellpower==2


def test_sch_425_krastinov_buffs_weapon_on_attack():
    _,p,q=ready();w=p.give('CS2_091').play();m=p.give('SCH_425').play()
    victim=q.summon('CS2_182');m.attack(victim)
    assert (w.atk,w.durability)==(2,5)


def test_sch_426_lilian_deathrattle_attacks():
    _,p,q=ready();p.give('SCH_426').play().destroy()
    assert p.field[0].id=='SCH_426t' and q.hero.health==26


def test_sch_509_brain_freeze_damage_only_on_combo():
    _,p,q=ready();a=q.summon('CS2_182');b=q.summon('CS2_182')
    p.give('SCH_509').play(target=a);assert a.frozen and a.health==5
    p.give('SCH_509').play(target=b);assert b.frozen and b.health==2


def test_sch_519_toxinblade_weapon_aura():
    _,p,_=ready();w=p.give('CS2_091').play();m=p.give('SCH_519').play()
    assert w.atk==3;m.silence();assert w.atk==1


def test_sch_521_coerce_requires_damage_without_combo():
    _,p,q=ready();a=q.summon('CS2_182');b=q.summon('CS2_182');b.hit(1)
    spell=p.give('SCH_521');assert b in spell.targets and a not in spell.targets
    p.give('GAME_005').play();assert a in spell.targets
    spell.play(target=a);assert a.zone==Zone.GRAVEYARD


def test_sch_522_steeldancer_uses_weapon_attack_as_cost():
    _,p,_=ready();p.give('CS2_091').play();p.give('SCH_522').play()
    assert len(p.field)==2 and any(m.id!='SCH_522' and m.cost==1 for m in p.field)


def test_sch_523_maul_uses_modified_spell_cost():
    _,p,q=ready();p.give('SCH_523').play();spell=p.give('CS2_029');spell.cost=2
    spell.play(target=q.hero)
    assert len(p.field)==1 and (p.field[0].atk,p.field[0].health)==(2,2) and p.field[0].taunt


def test_sch_524_shield_honor_targets_only_damaged_minions():
    _,p,_=ready();m=p.summon('CS2_182');spell=p.give('SCH_524')
    assert m not in spell.targets;m.hit(1);spell.play(target=m)
    assert m.atk==7 and m.divine_shield


def test_sch_525_in_formation_adds_two_taunts():
    _,p,_=ready();p.give('SCH_525').play()
    assert len(p.hand)==2 and all(m.taunt for m in p.hand)


def test_sch_526_barov_sets_other_health_and_deathrattle_kills():
    _,p,q=ready();a=p.summon('CS2_182');b=q.summon('CS2_182')
    barov=p.give('SCH_526').play();assert a.health==b.health==1 and barov.health==2
    barov.destroy();assert not p.field and not q.field


def test_sch_533_commencement_recruits_without_battlecry():
    _,p,q=ready();m=p.card('EX1_189',zone=Zone.DECK)
    p.give('SCH_533').play();assert m.zone==Zone.PLAY and m.taunt and m.divine_shield
    assert not p.hand


def test_sch_537_trick_totem_casts_cheap_spell(monkeypatch):
    g,p,q=ready();seen=[]
    def record(self,source,spell,targets):seen.append(spell.cost)
    monkeypatch.setattr(CastSpell,'do',record)
    p.give('SCH_537').play();g.end_turn()
    assert len(seen)==1 and 0<=seen[0]<=3


def test_sch_621_rattlegore_repeated_deaths_shrink_to_nothing():
    _,p,_=ready();p.give('SCH_621').play()
    for stats in range(9,0,-1):
        assert len(p.field)==1 and (p.field[0].atk,p.field[0].health)==(stats,stats)
        p.field[0].destroy()
    assert not p.field


def test_sch_622_self_sharpening_sword_gains_attack():
    _,p,q=ready();w=p.give('SCH_622').play();p.hero.attack(q.hero)
    assert q.hero.health==29 and w.atk==2 and w.durability==3


def test_sch_623_cutting_class_discount_and_draw():
    _,p,_=ready();p.give('CS2_091').play()
    for _ in range(3):p.card('CS2_231',zone=Zone.DECK)
    spell=p.give('SCH_623');assert spell.cost==4;spell.play();assert len(p.hand)==2


def test_sch_706_plagiarize_copies_enemy_turn_cards():
    g,p,q=ready();secret=p.give('SCH_706').play();g.end_turn()
    q.give('GAME_005').play();q.give('CS2_231').play();g.end_turn()
    assert secret.zone==Zone.GRAVEYARD and sorted(c.id for c in p.hand)==['CS2_231','GAME_005']


def test_nested_secret_passages_unwind_newest_first():
    g, p, q = ready()
    original = p.give("CS2_029")
    loans = [p.card("CS2_231", zone=Zone.DECK) for _ in range(8)]
    p.give("SCH_305").play()
    first_hand = list(p.hand)
    p.give("SCH_305").play()
    assert all(card.zone == Zone.SETASIDE for card in first_hand)
    generated = p.give("CS2_182")
    g.end_turn()
    assert original in p.hand and generated in p.hand and len(p.deck) == 8
    g.end_turn()
    assert original in p.hand and generated in p.hand
    assert len(p.deck) == 7  # Eight loans returned, then the normal draw.
    assert sum(card in p.hand for card in loans) == 1
    assert not any(buff.id == "SCH_305e3" for buff in p.buffs)


def test_jandice_divine_shield_and_exact_copy_illusion():
    g, p, q = ready()
    p.give("SCH_351").play()
    illusion = p.choice.cards[0]
    p.choice.choose(illusion)
    illusion.divine_shield = True
    illusion.hit(1)
    assert illusion.zone == Zone.PLAY and not illusion.divine_shield
    p.give("SCH_352").play()
    copied = next(card for card in p.hand if card.id == illusion.id)
    refill(p)
    copied.play()
    copied.divine_shield = False
    copied.buff(copied, "SCH_609e")
    assert copied.health > 1
    copied.hit(1)
    assert copied.zone == Zone.GRAVEYARD


def test_rattlegore_progression_ignores_external_buffs_and_stat_setting():
    _, p, q = ready()
    original = p.summon("SCH_621")
    original.buff(original, "SCH_609e")
    assert original.atk == original.max_health == 13
    original.destroy()
    returned = p.field[0]
    assert returned.atk == returned.max_health == 8
    returned.buff(returned, "SCH_352e")
    assert returned.atk == returned.max_health == 1
    returned.destroy()
    assert p.field[0].atk == p.field[0].max_health == 7
    p.field[0].bounce()
    p.hand[0].play()
    assert p.field[0].atk == p.field[0].max_health == 9
    p.field[0].destroy()
    assert p.field[0].atk == p.field[0].max_health == 8


def test_plagiarize_does_not_duplicate_an_earlier_turns_bounced_card():
    g, p, q = ready()
    minion = p.give("CS2_231").play()
    minion.bounce()
    g.end_turn()
    g.end_turn()
    q.card("SCH_706", zone=Zone.SECRET)
    minion.play()
    g.end_turn()
    assert [card.id for card in q.hand] == ["CS2_231"]
