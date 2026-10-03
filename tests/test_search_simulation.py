import threading

import pytest
from hearthstone.enums import CardClass, Zone

from fireplace import cards
from fireplace.agent_api import Action
from fireplace.controller import GameSession, decision_player
from fireplace.game import Game
from fireplace.managers import BaseObserver
from fireplace.player import Player
from fireplace.replay_state import normalized_game_state
from fireplace.search_api import SearchUnavailable
from fireplace.search_simulation import EngineSearchPosition


cards.db.initialize()


def main_session():
    game = Game([Player("One", ["CS2_182"] * 12, CardClass.MAGE.default_hero),
                 Player("Two", ["CS2_231"] * 12, CardClass.MAGE.default_hero)], seed=17)
    session = GameSession(game, {})
    session.start()
    while any(p.choice for p in game.players):
        session.execute(decision_player(game), Action(type="MULLIGAN"))
    player = game.current_player
    player.max_mana = 10
    player.used_mana = 0
    for card in tuple(player.hand):
        card.zone = Zone.GRAVEYARD
    return session, player


def test_search_does_not_copy_observer_locks_or_mutate_live_game(caplog):
    session, player = main_session()

    class LockedObserver(BaseObserver):
        def __init__(self):
            self.lock = threading.Lock()
            self.calls = 0

        def action_start(self, *args):
            self.calls += 1

    observer = LockedObserver()
    session.game.manager.register(observer)
    spell = player.card("CS2_029", zone=Zone.HAND)
    action = Action(type="PLAY_CARD", source_entity_id=spell.entity_id,
                    target_entity_id=player.opponent.hero.entity_id)
    before = normalized_game_state(session.game)
    rng = session.game.random.getstate()
    log = session.action_log.to_dict()
    position = EngineSearchPosition.from_game(session.game, player, seed=31)
    caplog.clear()
    child = position.transition(action, seed=32)
    assert not caplog.records
    assert child.observation()["opponent"]["hero"]["health"] == 24
    assert position.observation()["opponent"]["hero"]["health"] == 30
    assert normalized_game_state(session.game) == before
    assert session.game.random.getstate() == rng
    assert session.action_log.to_dict() == log
    assert observer.calls == 0
    assert len(child._game.manager.observers) == 1
    session.execute(player, action)
    assert caplog.records  # The search context must restore real engine logs.


def test_unknown_draws_are_counted_but_unplayable():
    session, player = main_session()
    spell = player.card("CS2_023", zone=Zone.HAND)
    action = Action(type="PLAY_CARD", source_entity_id=spell.entity_id)
    original_deck = tuple(card.id for card in player.deck)
    position = EngineSearchPosition.from_game(session.game, player, seed=7)
    child = position.transition(action)
    hand = child.observation()["self"]["hand"]
    assert len(hand) == 2
    assert all(card["unknown"] and card["card_id"] is None for card in hand)
    assert not any(a.type == "PLAY_CARD" for a in child.legal_actions())
    assert tuple(card.id for card in player.deck) == original_deck
    assert not child.terminal


def test_hidden_secrets_are_inert_and_private_cards_are_replaced():
    session, player = main_session()
    player.opponent.card("EX1_287", zone=Zone.SECRET)
    spell = player.card("CS2_029", zone=Zone.HAND)
    action = Action(type="PLAY_CARD", source_entity_id=spell.entity_id,
                    target_entity_id=player.opponent.hero.entity_id)
    position = EngineSearchPosition.from_game(session.game, player, seed=11)
    opponent = position._game.players[1 - position._viewer_seat]
    assert all(card.id == "UNKNOWN" for card in opponent.hand)
    assert all(card.id == "UNKNOWN" for p in position._game.players for card in p.deck)
    view = position.observation()["opponent"]
    assert "hand" not in view and "secrets" not in view
    assert view["secrets_count"] == 1
    assert view["secret_classes"] == [["MAGE"]]
    assert position.transition(action).observation()["opponent"]["hero"]["health"] == 24
    assert len(player.opponent.secrets) == 1


def test_discover_stops_before_copying_or_executing_deferred_callbacks():
    session, player = main_session()
    card = player.card("LOE_006", zone=Zone.HAND)
    action = next(a for a in session.legal_actions(player)
                  if a.source_entity_id == card.entity_id)
    before = normalized_game_state(session.game)
    child = EngineSearchPosition.from_game(session.game, player).transition(action)
    assert child.terminal
    assert child.observation()["phase"] == "CHOICE"
    assert child.legal_actions() == []
    assert player.choice is None
    assert normalized_game_state(session.game) == before
    with pytest.raises(SearchUnavailable):
        child.transition(Action(type="END_TURN"))


def test_secret_classes_follow_survivors_when_a_random_secret_is_stolen():
    session, player = main_session()
    mage_secret = player.opponent.card("EX1_287", zone=Zone.SECRET)
    hunter_secret = player.opponent.card("EX1_609", zone=Zone.SECRET)
    thief = player.card("GVG_074", zone=Zone.HAND)  # Kezan Mystic.
    action = next(a for a in session.legal_actions(player)
                  if a.source_entity_id == thief.entity_id)
    position = EngineSearchPosition.from_game(session.game, player)
    classes = {mage_secret.entity_id: ["MAGE"], hunter_secret.entity_id: ["HUNTER"]}
    for seed in (0, 1, 2):
        child = position.transition(action, seed=seed)
        rival = child._game.players[1 - child._viewer_seat]
        assert len(rival.secrets) == 1
        assert child.observation()["opponent"]["secret_classes"] == [classes[rival.secrets[0].entity_id]]
        assert child.observation()["self"]["secrets"][0]["unknown"]
    assert len(player.opponent.secrets) == 2


def test_turn_end_is_a_boundary_and_applies_visible_turn_end_effects():
    session, player = main_session()
    player.summon("EX1_597")  # Imp Master loses health and summons at turn end.
    position = EngineSearchPosition.from_game(session.game, player)
    child = position.transition(Action(type="END_TURN"))
    assert child.terminal
    assert child.legal_actions() == []
    assert len(child.observation()["self"]["board"]) == 2
    assert len(player.field) == 1


def test_opponent_reply_allows_only_visible_attacks_and_keeps_viewer():
    session, player = main_session()
    minion = player.opponent.summon("CS2_182")
    position = EngineSearchPosition.from_game(session.game, player)
    reply = position.opponent_attack_position()
    actions = reply.legal_actions()
    assert {a.type for a in actions} == {"ATTACK", "END_TURN"}
    action = next(a for a in actions if a.target_entity_id == player.hero.entity_id)
    assert action.source_entity_id == minion.entity_id
    child = reply.transition(action)
    assert child.observation()["self"]["hero"]["health"] == 26
    assert player.hero.health == 30


def test_live_pending_choices_cannot_be_cloned_for_search():
    session, player = main_session()
    card = player.card("LOE_006", zone=Zone.HAND)
    session.execute(player, next(a for a in session.legal_actions(player)
                                 if a.source_entity_id == card.entity_id))
    with pytest.raises(SearchUnavailable, match="main-action"):
        EngineSearchPosition.from_game(session.game, player)


def test_main_state_with_a_live_entity_callback_falls_back_safely():
    session, player = main_session()
    session.game.deferred_callback = lambda: player.draw()
    with pytest.raises(SearchUnavailable, match="live game"):
        EngineSearchPosition.from_game(session.game, player)


def test_controller_supplies_only_the_optional_search_boundary():
    session, player = main_session()

    class ProbeAgent:
        seed = 4

        def choose_action_with_search(self, observation, actions, position):
            assert observation["phase"] == "MAIN"
            assert isinstance(position, EngineSearchPosition)
            return next(a for a in actions if a.type == "END_TURN")

        def choose_action(self, observation, actions):
            raise AssertionError("Search should be available")

    before = normalized_game_state(session.game)
    assert session.choose_action(player, agent=ProbeAgent()) == Action(type="END_TURN")
    assert normalized_game_state(session.game) == before
