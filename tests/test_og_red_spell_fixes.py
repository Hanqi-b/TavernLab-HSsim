"""Focused fixes for OG cards that cast or change the cost of spells."""

from hearthstone.enums import CardClass, CardType, Zone
from fireplace.actions import CastSpell
from fireplace.cards.wog import neutral_legendary
from fireplace.dsl.random_picker import RandomID
from fireplace.managers import BaseObserver

from utils import MOONFIRE, THE_COIN, prepare_empty_game


class CastCapture(BaseObserver):
    def __init__(self):
        self.spells = []

    def targeted_action(self, action, source, target, *args):
        if isinstance(action, CastSpell):
            self.spells.append((source, target))


def test_chogall_unused_health_payment_expires_at_turn_end():
    game = prepare_empty_game(CardClass.WARLOCK, CardClass.WARLOCK)
    chogall = game.player1.give("OG_121")
    chogall.play()
    assert chogall.zone == Zone.PLAY
    assert game.player1.spells_cost_health

    game.end_turn()
    assert not game.player1.spells_cost_health
    game.end_turn()
    game.player1.used_mana = 0
    game.player1.hero.set_current_health(20)
    health_before = game.player1.hero.health
    mana_before = game.player1.mana
    frostbolt = game.player1.give("CS2_024")
    frostbolt.play(target=game.player2.hero)

    assert frostbolt.zone == Zone.GRAVEYARD
    assert game.player1.hero.health == health_before
    assert game.player1.mana == mana_before - frostbolt.cost
    assert game.player2.hero.health == 27


def test_servant_of_yogg_saron_casts_varied_spells_costing_at_most_five():
    seen = set()
    for seed in range(870, 882):
        game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
        game.player1.is_standard = game.player2.is_standard = False
        game.random.seed(seed)
        for card_id in ("CS2_231", "CS2_182", "EX1_016"):
            game.player1.give(card_id).shuffle_into_deck()
        capture = CastCapture()
        game.manager.register(capture)

        servant = game.player1.give("OG_087")
        servant.play()

        assert len(capture.spells) == 1
        source, spell = capture.spells[0]
        assert source is servant
        assert spell.type == CardType.SPELL and spell.data.collectible
        assert 0 <= spell.data.cost <= 5
        seen.add(spell.id)
    assert len(seen) > 1


def test_mana_burn_direct_cast_reduces_next_turn_mana_without_crashing():
    game = prepare_empty_game(CardClass.DEMONHUNTER, CardClass.WARRIOR)
    mana_burn = game.player1.give("BT_753")
    mana_burn.play()
    assert mana_burn.zone == Zone.GRAVEYARD

    game.end_turn()
    assert game.player2.mana == 8
    assert not any(buff.id == "BT_753e" for buff in game.player2.buffs)
    game.end_turn()
    game.end_turn()
    assert game.player2.mana == 10


def test_yogg_saron_handles_seeded_mana_burn_from_two_prior_spells():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    game.player1.is_standard = game.player2.is_standard = False
    game.random.seed(1341)
    game.player1.give(MOONFIRE).play(target=game.player2.hero)
    game.player1.give(THE_COIN).play()
    assert sum(card.type == CardType.SPELL for card in game.player1.cards_played_this_game) == 2
    capture = CastCapture()
    game.manager.register(capture)

    yogg = game.player1.give("OG_134")
    yogg.play()

    assert yogg.zone == Zone.PLAY
    assert len(capture.spells) == 2
    assert all(source is yogg and spell.type == CardType.SPELL for source, spell in capture.spells)
    assert any(spell.id == "BT_753" for _, spell in capture.spells)


def test_yogg_saron_with_no_prior_spells_casts_nothing():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    capture = CastCapture()
    game.manager.register(capture)
    yogg = game.player1.give("OG_134")

    yogg.play()

    assert yogg.zone == Zone.PLAY
    assert capture.spells == []


def test_yogg_saron_stops_casting_after_it_dies(monkeypatch):
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    for card_id in (MOONFIRE, THE_COIN, THE_COIN):
        spell = game.player1.give(card_id)
        if card_id == MOONFIRE:
            spell.play(target=game.player2.hero)
        else:
            spell.play()
    assert sum(card.type == CardType.SPELL for card in game.player1.cards_played_this_game) == 3
    monkeypatch.setattr(neutral_legendary, "RandomSpell", lambda: RandomID("EX1_279"))
    monkeypatch.setattr(CastSpell, "choose_target", lambda self, source, card: source)
    capture = CastCapture()
    game.manager.register(capture)

    yogg = game.player1.give("OG_134")
    yogg.play()

    assert yogg.zone == Zone.GRAVEYARD
    assert len(capture.spells) == 1
    assert capture.spells[0][1].id == "EX1_279"
