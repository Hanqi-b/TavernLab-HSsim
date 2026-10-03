"""Spell-target decisions against Fireplace, including the reported Mage board."""

import pytest
from hearthstone.enums import Zone

from fireplace.agent_api import Action
from fireplace.exceptions import GameOver
from fireplace.mcts_agent import MCTSAgent
from fireplace.replay_state import normalized_game_state
from fireplace.search_tactics import TacticalSearchResult
from fireplace.search_candidates import evaluate_root_candidates
from tests.test_search_simulation import main_session


def reported_mage_board():
    """Public board/AI hand from the reported turn, without private archive data."""
    session, player = main_session()
    player.max_mana = 6
    player.temp_mana = 0
    flamewaker = player.summon("BRM_002")
    flamewaker.turns_in_play = 2
    enemy_ids = set()
    for card_id, health in (("EX1_131", 2), ("EX1_131t", 1), ("NEW1_014", 4),
                            ("AT_028", 4), ("NEW1_026", 2)):
        minion = player.opponent.summon(card_id)
        minion.damage = minion.max_health - health
        minion.turns_in_play = 1
        minion.stealthed = card_id == "NEW1_026"
        enemy_ids.add(minion.entity_id)
    for card_id in ("EX1_046", "CS2_028", "CS2_022", "OG_147", "EX1_590", "LOE_092"):
        player.card(card_id, zone=Zone.HAND)
    polymorph = next(card for card in player.hand if card.id == "CS2_022")
    return session, player, flamewaker, polymorph, enemy_ids


def choose_without_mutating(session, player, agent):
    before = normalized_game_state(session.game)
    rng = session.game.random.getstate()
    action = session.choose_action(player, agent=agent)
    assert action in session.legal_actions(player)
    assert normalized_game_state(session.game) == before
    assert session.game.random.getstate() == rng
    return action


def force_uncertified_candidate(monkeypatch, agent, action):
    # Reproduce an exhausted search's bad candidate independently of timing.
    monkeypatch.setattr(agent, "_tactical_probe", lambda *args: (TacticalSearchResult(), {}))

    def select(*args, **kwargs):
        agent.last_search_stats = {"mode": "mcts_partial", "best_reward": 0.5}
        return action

    monkeypatch.setattr(agent, "_run_mcts", select)
    # These forced-search tests verify selection semantics; timed coverage is
    # covered separately by the full-policy seed tests and cutoff unit tests.
    monkeypatch.setattr(agent, "_run_candidate_pass", lambda view, actions, position:
                        evaluate_root_candidates(view, actions, position, budget=None))


def test_reported_own_flamewaker_polymorph_is_retargeted(monkeypatch):
    session, player, flamewaker, polymorph, enemy_ids = reported_mage_board()
    try:
        wrong = Action(type="PLAY_CARD", source_entity_id=polymorph.entity_id,
                       target_entity_id=flamewaker.entity_id)
        assert wrong in session.legal_actions(player)
        agent = MCTSAgent(policy_version="tactical_v2", seed=0)
        force_uncertified_candidate(monkeypatch, agent, wrong)
        chosen = choose_without_mutating(session, player, agent)
        # The unified evaluator may choose Blizzard or a summon instead of
        # retargeting the same spell. It must avoid the reported harmful play.
        assert chosen != wrong
        if chosen.source_entity_id == polymorph.entity_id:
            assert chosen.target_entity_id in enemy_ids
        rows = agent.last_search_stats["decision_trace"]["candidates"]
        assert any(row["action"] == wrong.to_dict() for row in rows)
    finally:
        session.close()


@pytest.mark.parametrize("seed", [0, 1, 3, 7])
def test_full_policy_avoids_own_polymorph_on_reported_board(seed):
    session, player, flamewaker, polymorph, _ = reported_mage_board()
    try:
        chosen = choose_without_mutating(session, player,
            MCTSAgent(policy_version="tactical_v2", seed=seed))
        assert not (chosen.source_entity_id == polymorph.entity_id
                    and chosen.target_entity_id == flamewaker.entity_id)
    finally:
        session.close()


def test_polymorph_is_preserved_when_only_good_own_minion_is_available(monkeypatch):
    session, player = main_session()
    try:
        own = player.summon("CS2_182")
        player.hero.power.activations_this_turn = 1
        polymorph = player.card("CS2_022", zone=Zone.HAND)
        wrong = Action(type="PLAY_CARD", source_entity_id=polymorph.entity_id,
                       target_entity_id=own.entity_id)
        agent = MCTSAgent(policy_version="tactical_v2")
        force_uncertified_candidate(monkeypatch, agent, wrong)
        assert choose_without_mutating(session, player, agent).type == "END_TURN"
        assert polymorph.zone == Zone.HAND and own.zone == Zone.PLAY
    finally:
        session.close()


@pytest.mark.parametrize("effect", ["buff", "heal", "deathrattle"])
def test_beneficial_own_target_is_allowed(monkeypatch, effect):
    session, player = main_session()
    try:
        player.hero.power.activations_this_turn = 1
        if effect == "buff":
            own = player.summon("CS2_231")
            spell = player.card("CS2_004", zone=Zone.HAND)
            target = own
            player.opponent.summon("CS2_182")
        elif effect == "heal":
            player.hero.damage = 10
            spell = player.card("CS2_007", zone=Zone.HAND)
            target = player.hero
        else:
            own = player.summon("EX1_016")  # Sylvanas.
            own.damage = own.max_health - 1
            player.opponent.summon("NEW1_030")  # Deathwing (summon skips battlecry).
            spell = player.card("CS2_029", zone=Zone.HAND)
            target = own
        action = Action(type="PLAY_CARD", source_entity_id=spell.entity_id,
                        target_entity_id=target.entity_id)
        assert action in session.legal_actions(player)
        agent = MCTSAgent(policy_version="tactical_v2")
        force_uncertified_candidate(monkeypatch, agent, action)
        chosen = choose_without_mutating(session, player, agent)
        assert chosen == action
        session.execute(player, chosen)
        if effect == "buff":
            assert target.max_health >= 3
        elif effect == "heal":
            assert target.health == target.max_health - 2
        else:
            assert any(card.id == "NEW1_030" for card in player.field)
            assert not player.opponent.field
    finally:
        session.close()


def test_certified_spell_lethal_is_preserved():
    session, player = main_session()
    try:
        spell = player.card("CS2_029", zone=Zone.HAND)
        player.opponent.summon("CS2_182")
        player.opponent.hero.damage = player.opponent.hero.max_health - 6
        agent = MCTSAgent(policy_version="tactical_v2", seed=3)
        action = choose_without_mutating(session, player, agent)
        assert action.source_entity_id == spell.entity_id
        assert action.target_entity_id == player.opponent.hero.entity_id
        with pytest.raises(GameOver):
            session.execute(player, action)
    finally:
        session.close()


def test_target_check_does_not_replace_survival_with_face_damage(monkeypatch):
    session, player = main_session()
    try:
        player.hero.damage = player.hero.max_health - 6
        player.max_mana = 4
        for _ in range(2):
            player.opponent.summon("CS2_182")
        spell = player.card("CS2_029", zone=Zone.HAND)
        defended = Action(type="PLAY_CARD", source_entity_id=spell.entity_id,
                          target_entity_id=player.opponent.field[0].entity_id)
        agent = MCTSAgent(policy_version="tactical_v2")
        force_uncertified_candidate(monkeypatch, agent, defended)
        assert choose_without_mutating(session, player, agent) == defended
    finally:
        session.close()


def test_certain_mcts_win_can_use_a_negative_setup_spell(monkeypatch):
    session, player = main_session()
    try:
        # Isolate this visible combo from unknown-zone queries and from an
        # alternative attack + empty-deck fatigue win at END_TURN.
        for participant in session.game.players:
            for card in tuple(participant.deck):
                card.zone = Zone.GRAVEYARD
        for card in tuple(player.opponent.hand):
            card.zone = Zone.GRAVEYARD
        player.opponent.cant_draw = True
        player.max_mana = 4
        player.temp_mana = 0
        player.hero.power.activations_this_turn = 1
        questing = player.summon("EX1_044")
        questing.turns_in_play = 1
        yeti = player.summon("CS2_182")
        polymorph = player.card("CS2_022", zone=Zone.HAND)
        player.opponent.hero.damage = player.opponent.hero.max_health - 3
        agent = MCTSAgent(policy_version="tactical_v2", seed=3,
                          time_budget=None, max_iterations=128, max_depth=4)
        # Exercise the completed ordinary MCTS line, not the independent probe.
        monkeypatch.setattr(agent, "_tactical_probe", lambda *args: (TacticalSearchResult(), {}))
        action = choose_without_mutating(session, player, agent)
        assert action.source_entity_id == polymorph.entity_id
        assert action.target_entity_id == yeti.entity_id
        assert agent.last_search_stats["best_reward"] == 1.0
        assert agent.last_search_stats["target_check"]["reason"] == "certain_mcts_win"
        session.execute(player, action)
        assert questing.atk == 3
        following = choose_without_mutating(session, player, agent)
        assert following.type == "ATTACK"
        assert following.target_entity_id == player.opponent.hero.entity_id
        with pytest.raises(GameOver):
            session.execute(player, following)
    finally:
        session.close()
