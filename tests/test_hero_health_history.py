from hearthstone.enums import CardClass
from fireplace.actions import Heal, Hit, SetCurrentHealth
from utils import prepare_empty_game


def test_health_counts_logical_changes_not_armor_or_noops():
    g=prepare_empty_game(CardClass.MAGE,CardClass.MAGE)
    p=g.current_player
    p.hero.armor=3
    g.cheat_action(p,[Hit(p.hero,2)])
    assert p.hero_health_changes_on_own_turn==0
    g.cheat_action(p,[Hit(p.hero,2)])
    assert p.hero.health==29 and p.hero_health_changes_on_own_turn==1
    g.cheat_action(p,[Heal(p.hero,10),Heal(p.hero,10)])
    assert p.hero_health_changes_on_own_turn==2
    g.cheat_action(p,[SetCurrentHealth(p.hero,20),SetCurrentHealth(p.hero,20)])
    assert p.hero_health_changes_on_own_turn==3
    assert p.hero_health_changed_turn==g.turn
    g.end_turn()
    assert p.hero_health_changed_turn!=g.turn
    g.cheat_action(p,[Hit(p.hero,1)])
    assert p.hero_health_changed_turn==g.turn and p.hero_health_changes_on_own_turn==3
