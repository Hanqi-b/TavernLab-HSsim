"""Regression coverage for live stats on Discover choices and their hand cards."""

from __future__ import annotations

import json

from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.agent_api import Action
from fireplace.controller import GameSession, decision_player
from fireplace.game import Game
from fireplace.player import Player


cards.db.initialize()


def _start_session(seed: int = 711):
    human = Player("Alice", ["CS2_231"] * 30, CardClass.PALADIN.default_hero, is_standard=False)
    opponent = Player("Bob", ["CS2_231"] * 30, CardClass.PALADIN.default_hero, is_standard=False)
    current = GameSession(Game((human, opponent), seed=seed), {})
    current.start()
    for _ in range(2):
        current.execute(decision_player(current.game), Action(type="MULLIGAN"))
    return current, current.game.current_player


def _force_historian_options(monkeypatch):
    """Keep the real Discover action while fixing its random pool result."""
    import fireplace.utils

    option_ids = ("LOOT_137", "AT_123", "BRM_030")

    def choose_options(source, _weights, card_sets, count):
        assert source.id == "KAR_062"
        pool = {card_id for card_set in card_sets for card_id in card_set}
        assert set(option_ids).issubset(pool)
        return [source.controller.card(card_id, source=source)
                for card_id in option_ids[:count]]

    monkeypatch.setattr(fireplace.utils, "weighted_card_choice", choose_options)


def _play(current, player, card):
    action = next(
        action for action in current.legal_actions(player)
        if action.type == "PLAY_CARD" and action.source_entity_id == card.entity_id
    )
    current.execute(player, action)


def test_discover_exposes_sleepy_dragon_live_and_printed_stats_privately(monkeypatch):
    _force_historian_options(monkeypatch)
    current, human = _start_session()
    human.max_mana = 10
    sleepy_in_hand = human.give("LOOT_137")
    historian = human.give("KAR_062")

    _play(current, human, historian)

    own_view = current.observation(human)
    assert own_view["phase"] == "CHOICE"
    assert own_view["pending_choice"] is not None
    sleepy_option = next(
        option for option in own_view["pending_choice"]["options"]
        if option["card_id"] == "LOOT_137"
    )
    assert {
        name: sleepy_option[name]
        for name in ("cost", "printed_cost", "atk", "printed_atk", "max_health", "printed_health")
    } == {
        "cost": 9,
        "printed_cost": 9,
        "atk": 4,
        "printed_atk": 4,
        "max_health": 12,
        "printed_health": 12,
    }

    opponent_view = current.observation(human.opponent)
    assert opponent_view["pending_choice"] is None
    assert "LOOT_137" not in json.dumps(opponent_view)
    assert str(sleepy_in_hand.entity_id) not in json.dumps(opponent_view)

    chosen = Action(type="CHOOSE", choice_entity_id=sleepy_option["entity_id"])
    current.execute(human, chosen)
    sleepy = next(card for card in human.hand if card.id == "LOOT_137" and card is not sleepy_in_hand)
    # This is the actual +1/+2 enchantment used by Sand Breath. Applying the
    # engine enchantment directly keeps this test about projection, not a new
    # Discover rule or a second targeted-board interaction.
    sleepy.buff(sleepy, "DRG_233e")

    hand_view = current.observation(human)
    public_sleepy = next(card for card in hand_view["self"]["hand"]
                         if card["entity_id"] == sleepy.entity_id)
    assert (public_sleepy["atk"], public_sleepy["max_health"]) == (5, 14)
    assert (public_sleepy["printed_atk"], public_sleepy["printed_health"]) == (4, 12)
    assert public_sleepy["active_modifiers"] == [{
        "kind": "enchantment",
        "effect": {"card_id": "DRG_233e", "name": "Sand Breath"},
        "source": {"card_id": "LOOT_137", "name": "Sleepy Dragon"},
        "grants": [],
    }]


def test_a_light_in_the_darkness_keeps_its_real_discover_plus_one_plus_one(monkeypatch):
    import fireplace.utils

    option_ids = ("LOOT_137", "AT_123", "BRM_030")

    def choose_options(source, _weights, _card_sets, count):
        assert source.id == "OG_311"
        return [source.controller.card(card_id, source=source)
                for card_id in option_ids[:count]]

    monkeypatch.setattr(fireplace.utils, "weighted_card_choice", choose_options)
    current, human = _start_session(seed=712)
    human.max_mana = 10
    light = human.give("OG_311")

    _play(current, human, light)

    before = current.observation(human)
    sleepy_option = before["pending_choice"]["options"][0]
    assert (sleepy_option["atk"], sleepy_option["max_health"]) == (4, 12)
    current.execute(human, Action(type="CHOOSE", choice_entity_id=sleepy_option["entity_id"]))

    sleepy = next(card for card in human.hand if card.id == "LOOT_137")
    after = current.observation(human)["self"]["hand"]
    public_sleepy = next(card for card in after if card["entity_id"] == sleepy.entity_id)
    assert (sleepy.atk, sleepy.max_health) == (5, 13)
    assert (public_sleepy["atk"], public_sleepy["max_health"]) == (5, 13)
    assert (public_sleepy["printed_atk"], public_sleepy["printed_health"]) == (4, 12)
    assert public_sleepy["active_modifiers"] == [{
        "kind": "enchantment",
        "effect": {"card_id": "OG_311e", "name": "Beacon of Hope"},
        "source": {"card_id": "OG_311", "name": "A Light in the Darkness"},
        "grants": [],
    }]
