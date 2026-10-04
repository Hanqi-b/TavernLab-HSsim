"""RNG purity regressions for menagerie card preview predicates."""

import pytest
from hearthstone.enums import CardClass

from fireplace import cards
from fireplace.action_log import ActionLog
from fireplace.agent_api import Action
from fireplace.controller import GameSession
from fireplace.dsl import BEAST, DRAGON, FRIENDLY_MINIONS, Find, MURLOC, RANDOM
from fireplace.game import Game
from fireplace.mcts_agent import MCTSAgent
from fireplace.player import Player
from fireplace.replay import restore_action_log
from fireplace.replay_state import normalized_game_state

from tests.utils import prepare_empty_game


cards.db.initialize()

MURLOC_CARD = "PRO_001at"
MENAGERIE_CARDS = ("KAR_095", "KAR_702")


def _menagerie_game(card_id):
    game = prepare_empty_game()
    player = game.current_player
    card = player.give(card_id)
    player.give(MURLOC_CARD).play()
    return game, player, card


def _legacy_menagerie_predicate():
    return Find(
        RANDOM(FRIENDLY_MINIONS + MURLOC)
        | RANDOM(FRIENDLY_MINIONS + DRAGON)
        | RANDOM(FRIENDLY_MINIONS + BEAST)
    )


def _action_for(session, player, action_type, *, source=None, target=None):
    for action in session.legal_actions(player):
        if action.type != action_type:
            continue
        if source is not None and action.source_entity_id != source.entity_id:
            continue
        if target is not None and action.target_entity_id != target.entity_id:
            continue
        return action
    raise AssertionError(
        "missing %s action for %s" % (action_type, getattr(source, "id", None))
    )


@pytest.mark.parametrize("card_id", MENAGERIE_CARDS)
def test_menagerie_powered_up_is_rng_free(card_id):
    game, _player, card = _menagerie_game(card_id)
    before_state = normalized_game_state(game)
    before_rng = game.random.getstate()

    assert card.powered_up

    assert game.random.getstate() == before_rng
    assert normalized_game_state(game) == before_state


def test_legacy_menagerie_preview_predicate_consumes_rng(monkeypatch):
    game, _player, card = _menagerie_game("KAR_095")
    monkeypatch.setattr(
        card.data.scripts,
        "powered_up",
        (_legacy_menagerie_predicate(),),
    )
    before_rng = game.random.getstate()

    assert card.powered_up

    assert game.random.getstate() != before_rng


def test_repeated_public_observation_preserves_rng_and_state():
    game, player, card = _menagerie_game("KAR_095")
    session = GameSession(game, {})
    try:
        before_state = normalized_game_state(game)
        before_rng = game.random.getstate()

        views = [session.observation(player) for _ in range(3)]

        assert all(
            next(item for item in view["self"]["hand"] if item["card_id"] == card.id)[
                "powered_up"
            ]
            for view in views
        )
        assert game.random.getstate() == before_rng
        assert normalized_game_state(game) == before_state
    finally:
        session.close()


def test_mcts_choose_action_preserves_live_rng_and_state():
    game, player, _card = _menagerie_game("KAR_095")
    session = GameSession(game, {})
    try:
        before_state = normalized_game_state(game)
        before_rng = game.random.getstate()
        agent = MCTSAgent(
            seed=7,
            time_budget=None,
            max_iterations=1,
            max_depth=1,
            action_limit=64,
        )

        selected = session.choose_action(player, agent=agent)

        assert selected in session.legal_actions(player)
        assert game.random.getstate() == before_rng
        assert normalized_game_state(game) == before_state
    finally:
        session.close()


def _logged_webspinner_game():
    players = (
        Player(
            "One",
            ["KAR_095"] * 15 + ["GVG_092t"] * 15,
            CardClass.MAGE.default_hero,
        ),
        Player("Two", ["FP1_011"] * 30, CardClass.MAGE.default_hero),
    )
    game = Game(players, seed=1)
    log = ActionLog(game, source_revision="powered-up-rng-test")
    session = GameSession(game, {}, action_log=log)
    session.start()
    for player in game.players:
        session.execute(player, Action(type="MULLIGAN"))

    first = game.player1
    chicken = next(card for card in first.hand if card.id == "GVG_092t")
    zoobot = next(card for card in first.hand if card.id == "KAR_095")
    session.execute(first, _action_for(session, first, "PLAY_CARD", source=chicken))

    # This is the public read that used to consume the RNG before the
    # Webspinner deathrattle below.  Keep it between logged boundaries so
    # restore must reproduce the same subsequent random generation.
    view = session.observation(first)
    assert next(
        card for card in view["self"]["hand"] if card["card_id"] == zoobot.id
    )["powered_up"]

    session.execute(first, Action(type="END_TURN"))
    second = game.current_player
    webspinner = next(card for card in second.hand if card.id == "FP1_011")
    session.execute(
        second,
        _action_for(session, second, "PLAY_CARD", source=webspinner),
    )
    session.execute(second, Action(type="END_TURN"))
    hand_before_death = len(second.hand)

    attacker = game.current_player
    chicken = next(card for card in attacker.field if card.id == "GVG_092t")
    webspinner = next(
        card for card in attacker.opponent.field if card.id == "FP1_011"
    )
    session.execute(
        attacker,
        _action_for(session, attacker, "ATTACK", source=chicken, target=webspinner),
    )
    assert len(second.hand) == hand_before_death + 1
    return game, session, log


def test_logged_game_restore_replays_observation_and_webspinner_rng():
    game, session, log = _logged_webspinner_game()
    restored = None
    try:
        expected_state = normalized_game_state(game)
        expected_rng = game.random.getstate()
        restored = restore_action_log(log.to_dict())

        assert normalized_game_state(restored.game) == expected_state
        assert restored.game.random.getstate() == expected_rng
    finally:
        if restored is not None:
            restored.close()
        session.close()
