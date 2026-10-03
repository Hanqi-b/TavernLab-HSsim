"""Behavior checks against the real rules engine, not an imitation of search."""

import pytest
from hearthstone.enums import Zone

from fireplace.agent_factory import create_agent
from fireplace.agent_api import Action
from fireplace.exceptions import GameOver
from fireplace.heuristic_agent import HeuristicAgent
from fireplace.mcts_agent import MCTSAgent
from fireplace.radical_agent import RadicalAgent
from fireplace.replay_state import normalized_game_state
from fireplace.search_simulation import EngineSearchPosition
from fireplace.search_scoring import score_observation
from tests.test_search_simulation import main_session


def test_radical_selects_the_knapsack_combination_in_a_real_hand():
    session, player = main_session()
    player.max_mana = 4
    expensive = player.card("CS2_182", zone=Zone.HAND)  # 4-mana Yeti.
    first = player.card("CS2_172", zone=Zone.HAND)  # 2-mana Raptor.
    second = player.card("CS2_120", zone=Zone.HAND)  # 2-mana Crocolisk.
    agent = create_agent("radical", seed=3)
    chosen = session.choose_action(player, agent=agent)
    assert chosen.type == "PLAY_CARD"
    assert chosen.source_entity_id in (first.entity_id, second.entity_id)
    assert chosen.source_entity_id != expensive.entity_id
    session.execute(player, chosen)
    following = session.choose_action(player, agent=agent)
    assert following.type == "PLAY_CARD"
    assert following.source_entity_id in (first.entity_id, second.entity_id)
    assert following.source_entity_id != chosen.source_entity_id


@pytest.mark.parametrize("kind", ["radical", "mcts"])
def test_both_agents_make_legal_main_phase_decisions_without_mutating_the_game(kind):
    session, player = main_session()
    player.card("CS2_029", zone=Zone.HAND)
    player.opponent.summon("CS2_182")
    before = normalized_game_state(session.game)
    rng = session.game.random.getstate()
    action = session.choose_action(player, agent=create_agent(kind, seed=1))
    assert action in session.legal_actions(player)
    assert normalized_game_state(session.game) == before
    assert session.game.random.getstate() == rng


def test_mcts_finds_two_attack_lethal_that_the_greedy_policy_trades_away():
    session, player = main_session()
    player.max_mana = 0
    player.temp_mana = 0
    player.used_mana = 0
    for _ in range(2):
        minion = player.summon("CS2_179")  # Two ready 3/5 Sen'jin Shieldmastas.
        minion.turns_in_play = 1
    decoy = player.opponent.summon("CS2_231")
    player.opponent.hero.damage = player.opponent.hero.max_health - 6
    legal = session.legal_actions(player)
    greedy = HeuristicAgent().choose_action(session.observation(player), legal)
    assert greedy.type == "ATTACK" and greedy.target_entity_id == decoy.entity_id
    agent = MCTSAgent(seed=12, time_budget=None, max_iterations=128, max_depth=6)
    action = session.choose_action(player, agent=agent)
    assert action.type == "ATTACK"
    assert action.target_entity_id == player.opponent.hero.entity_id
    session.execute(player, action)
    following = session.choose_action(player, agent=agent)
    assert following.type == "ATTACK"
    assert following.target_entity_id == player.opponent.hero.entity_id
    with pytest.raises(GameOver):
        session.execute(player, following)
    assert session.game.ended


def test_both_factory_policies_work_with_the_original_mulligan_boundary():
    from fireplace.controller import GameSession, decision_player
    from fireplace.game import Game
    from fireplace.player import Player
    from hearthstone.enums import CardClass

    game = Game([Player("One", ["CS2_182"] * 12, CardClass.MAGE.default_hero),
                 Player("Two", ["CS2_231"] * 12, CardClass.MAGE.default_hero)], seed=4)
    session = GameSession(game, {game.players[0]: create_agent("radical", seed=4),
                                 game.players[1]: create_agent("mcts", seed=5)})
    session.start()
    for _ in range(2):
        player = decision_player(game)
        action = session.choose_action(player)
        assert action.type == "MULLIGAN"
        assert action in session.legal_actions(player)
        session.execute(player, action)
    assert all(player.choice is None for player in game.players)


def test_radical_and_mcts_finish_a_seeded_game_through_the_controller(monkeypatch):
    from fireplace.controller import GameSession
    from fireplace.game import Game
    from fireplace.player import Player
    from hearthstone.enums import CardClass

    first = Player("Radical", ["CS2_231"] * 5, CardClass.DRUID.default_hero)
    second = Player("MCTS", ["CS2_231"] * 5, CardClass.DRUID.default_hero)
    game = Game((first, second), seed=41)
    session = GameSession(game, {
        first: RadicalAgent(seed=41, time_budget=None, max_iterations=16, max_depth=6),
        second: MCTSAgent(seed=42, time_budget=None, max_iterations=16, max_depth=6),
    })
    searched = {first: 0, second: 0}
    for player, agent in session.agents.items():
        original = agent.choose_action_with_search

        def counted(observation, actions, position, *, owner=player, policy=agent, choose=original):
            action = choose(observation, actions, position)
            searched[owner] += policy.last_search_stats["nodes"]
            return action

        monkeypatch.setattr(agent, "choose_action_with_search", counted)
    result = session.run()
    assert result.ended
    assert 0 < result.turn < 100
    assert searched[first] > 0
    assert searched[second] > 0


def test_radical_preserves_coin_when_full_board_blocks_the_extra_mana_play():
    session, player = main_session()
    player.max_mana = 0
    player.temp_mana = 0
    for _ in range(7):
        player.summon("CS2_231")
    player.card("GAME_005", zone=Zone.HAND)
    player.card("CS2_189", zone=Zone.HAND)
    action = session.choose_action(player, agent=create_agent("radical", seed=3))
    assert action.type == "END_TURN"


def test_simultaneous_hellfire_lethal_is_evaluated_as_a_draw():
    session, player = main_session()
    for participant in session.game.players:
        participant.hero.damage = participant.hero.max_health - 3
    spell = player.card("CS2_062", zone=Zone.HAND)
    position = EngineSearchPosition.from_game(session.game, player, seed=2)
    child = position.transition(Action(type="PLAY_CARD", source_entity_id=spell.entity_id))
    assert child.terminal
    assert child.observation()["self"]["hero"]["health"] == 0
    assert child.observation()["opponent"]["hero"]["health"] == 0
    assert score_observation(child.observation()) == 0
