"""Spellburst lifecycle independently of expansion card implementations."""
from hearthstone.enums import CardClass, Zone

from fireplace import cards
from fireplace.actions import Bounce, CastSpell, Give, Hit, Summon
from fireplace.dsl.copy import ExactCopy
from fireplace.dsl.selector import CONTROLLER, ENEMY_HERO, SELF
from utils import prepare_empty_game


def ready():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    p, q = game.current_player, game.current_player.opponent
    p.discard_hand()
    q.discard_hand()
    return game, p, q


def burst(monkeypatch, card_id="CS2_231", effect=None):
    monkeypatch.setattr(cards.db[card_id].scripts, "spellburst", effect or (Hit(ENEMY_HERO, 2),))


def test_once_after_spell_and_only_owner_hand_cast(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch)
    m = p.summon("CS2_231")
    g.cheat_action(m, [CastSpell(p.card("GAME_005"))])
    assert q.hero.health == 30 and not m.spellburst_used
    p.give("GAME_005").play()
    assert q.hero.health == 28 and m.spellburst_used
    p.give("GAME_005").play()
    assert q.hero.health == 28
    opponent_minion = q.summon("CS2_231")
    p.give("GAME_005").play()
    assert not opponent_minion.spellburst_used


def test_killed_or_silenced_listener_does_not_fire(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch)
    m = p.summon("CS2_231")
    p.give("CS2_008").play(target=m)
    assert m.zone == Zone.GRAVEYARD and q.hero.health == 30
    m = p.summon("CS2_231")
    m.silence()
    p.give("GAME_005").play()
    assert q.hero.health == 30


def test_spellburst_summons_do_not_trigger_from_same_spell(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch, effect=(Summon(CONTROLLER, "CS2_231"),))
    original = p.summon("CS2_231")
    p.give("GAME_005").play()
    assert len(p.field) == 2
    assert original.spellburst_used
    assert not p.field[1].spellburst_used
    p.give("GAME_005").play()
    assert len(p.field) == 3


def test_bounce_rearms_but_exact_copy_keeps_used_state(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch)
    m = p.summon("CS2_231")
    p.give("GAME_005").play()
    copied = ExactCopy(SELF).copy(m, m)
    p.summon(copied)
    assert copied.spellburst_used
    m.bounce()
    assert not m.spellburst_used
    m.play()
    p.give("GAME_005").play()
    assert q.hero.health == 26


def test_bouncing_spellburst_can_trigger_on_each_replay(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch, effect=(Bounce(SELF),))
    m = p.summon("CS2_231")
    for _ in range(2):
        p.give("GAME_005").play()
        assert m.zone == Zone.HAND and not m.spellburst_used
        m.play()


def test_weapon_spellburst(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch, "CS2_091")
    weapon = p.give("CS2_091").play()
    p.give("GAME_005").play()
    p.give("GAME_005").play()
    assert q.hero.health == 28 and weapon.spellburst_used


def test_countered_spell_does_not_consume_spellburst(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch)
    m = p.summon("CS2_231")
    q.card("EX1_287", zone=Zone.SECRET)
    p.give("GAME_005").play()
    assert not m.spellburst_used and q.hero.health == 30


def test_discover_spellbursts_resolve_sequentially_and_keep_context(monkeypatch):
    from fireplace.actions import Discover
    from fireplace.dsl.random_picker import RandomSpell
    g,p,q=ready()
    burst(monkeypatch,effect=(Discover(CONTROLLER,RandomSpell()),))
    a=p.summon('CS2_231');b=p.summon('CS2_231')
    spell=p.give('GAME_005').play()
    assert a.spellburst_used and not b.spellburst_used and p.choice
    assert a.spellburst_spell is spell
    first=p.choice
    first.choose(first.cards[0])
    assert b.spellburst_used and p.choice is not first
    assert a.spellburst_spell is None and b.spellburst_spell is spell
    p.choice.choose(p.choice.cards[0])
    assert p.choice is None and b.spellburst_spell is None


def test_spell_summoned_spellburst_waits_for_next_spell(monkeypatch):
    g,p,q=ready()
    burst(monkeypatch)
    monkeypatch.setattr(cards.db['GAME_005'].scripts,'play',(Summon(CONTROLLER,'CS2_231'),))
    p.give('GAME_005').play()
    assert len(p.field)==1 and not p.field[0].spellburst_used
    assert q.hero.health==30
    p.give('GAME_005').play()
    assert q.hero.health==28 and len(p.field)==2


def test_spellburst_actions_after_discover_are_not_lost(monkeypatch):
    from fireplace.actions import Discover
    from fireplace.dsl.random_picker import RandomSpell
    g,p,q=ready()
    burst(monkeypatch,effect=(Discover(CONTROLLER,RandomSpell()),Hit(ENEMY_HERO,2)))
    p.summon('CS2_231')
    p.give('GAME_005').play()
    assert p.choice and q.hero.health==30
    p.choice.choose(p.choice.cards[0])
    assert q.hero.health==28


def test_two_choices_keep_spellburst_context_and_hold_next_listener(monkeypatch):
    from fireplace.actions import Discover
    from fireplace.dsl.random_picker import RandomSpell
    g, p, q = ready()
    burst(monkeypatch, effect=(Discover(CONTROLLER, RandomSpell()),
                              Discover(CONTROLLER, RandomSpell()), Hit(ENEMY_HERO, 2)))
    a = p.summon("CS2_231")
    b = p.summon("CS2_231")
    spell = p.give("GAME_005").play()
    p.choice.choose(p.choice.cards[0])
    assert p.choice and a.spellburst_spell is spell and not b.spellburst_used
    assert q.hero.health == 30
    p.choice.choose(p.choice.cards[0])
    assert q.hero.health == 28 and b.spellburst_used and p.choice
    p.choice.choose(p.choice.cards[0])
    assert b.spellburst_spell is spell and q.hero.health == 28
    p.choice.choose(p.choice.cards[0])
    assert not p.choice and b.spellburst_spell is None and q.hero.health == 26


def test_exact_copy_to_hand_rearms_spellburst(monkeypatch):
    g, p, q = ready()
    burst(monkeypatch)
    original = p.summon("CS2_231")
    p.give("GAME_005").play()
    copied = ExactCopy(SELF).copy(original, original)
    g.cheat_action(original, [Give(p, copied)])
    assert not copied.spellburst_used
    copied.play()
    p.give("GAME_005").play()
    assert q.hero.health == 26
