"""Tactical decisions verified against the live Fireplace rules engine."""
import pytest
from hearthstone.enums import Zone

from fireplace.agent_api import Action
from fireplace.exceptions import GameOver
from fireplace.mcts_agent import MCTSAgent
from fireplace.replay_state import normalized_game_state
from fireplace.search_simulation import EngineSearchPosition
from fireplace.search_scoring import is_terminal_win, score_tactical_observation
from fireplace.search_tactics import find_deterministic_lethal
from tests.test_search_simulation import main_session


def test_hidden_spell_filter_cannot_certify_saboteur_lethal():
    session, player = main_session()
    enemy = player.opponent
    for card in tuple(enemy.hand):
        card.zone = Zone.GRAVEYARD
    enemy.card("EX1_312", zone=Zone.HAND)  # Hidden Twisting Nether.
    attacker = player.summon("EX1_044")  # Questing Adventurer.
    attacker.turns_in_play = 1
    player.hero.power.activations_this_turn = 1
    saboteur = player.card("DAL_538", zone=Zone.HAND)
    enemy.hero.damage = enemy.hero.max_health - 3
    before = normalized_game_state(session.game)
    rng = session.game.random.getstate()
    root = EngineSearchPosition.from_game(session.game, player)
    play = next(a for a in root.legal_actions()
                if a.type == "PLAY_CARD" and a.source_entity_id == saboteur.entity_id)
    child = root.transition(play)
    assert child.observation()["search_uncertain"]
    result = find_deterministic_lethal(root.observation(), root.legal_actions(), root,
                                       max_nodes=64, max_depth=8)
    assert not result.deterministic_lethal and result.action is None
    assert normalized_game_state(session.game) == before
    assert session.game.random.getstate() == rng
    session.execute(player, play)
    assert not player.field  # Real hidden Nether makes the simulated attack impossible.
    assert enemy.hero.health == 3


def test_destroyed_hero_victory_beats_face_damage():
    session, player = main_session()
    for card in tuple(player.deck):
        card.zone = Zone.GRAVEYARD
    attacker = player.summon("BOT_424")  # Mecha'thun wins by Destroy, not damage.
    attacker.turns_in_play = 1
    attacker.damage = attacker.max_health - 1
    wisp = player.opponent.summon("CS2_231")
    player.max_mana = 0
    player.temp_mana = 0
    attack = Action(type="ATTACK", source_entity_id=attacker.entity_id,
                    target_entity_id=wisp.entity_id)
    root = EngineSearchPosition.from_game(session.game, player)
    child = root.transition(attack)
    view = child.observation()
    assert child.terminal and view["opponent"]["hero"]["health"] == 30
    assert view["search_outcome"] == "win"
    assert is_terminal_win(view) and score_tactical_observation(view) >= 1_000_000
    assert not view["search_uncertain"]
    agent = MCTSAgent(policy_version="tactical_v2", seed=0, time_budget=None,
                      max_iterations=16)
    assert session.choose_action(player, agent=agent) == attack
    with pytest.raises(GameOver):
        session.execute(player, attack)
    assert session.game.ended


@pytest.mark.parametrize("on_buff", [False, True])
def test_inherited_hidden_deathrattle_is_also_uncertain(on_buff):
    session, player = main_session()
    attacker = player.summon("CS2_179")
    attacker.turns_in_play = 1
    recipient = attacker.buff(attacker, "EX1_044e") if on_buff else attacker
    hidden_effect = player.card("DAL_538", zone=Zone.GRAVEYARD).data.scripts.play
    recipient.additional_deathrattles.append(hidden_effect)
    recipient.has_deathrattle = True
    attacker.has_deathrattle = True
    root = EngineSearchPosition.from_game(session.game, player)
    face = Action(type="ATTACK", source_entity_id=attacker.entity_id,
                  target_entity_id=player.opponent.hero.entity_id)
    assert root.transition(face).observation()["search_uncertain"]


def tactical_scene(case):
    session, player = main_session()
    enemy = player.opponent
    player.temp_mana = 0
    player.used_mana = 0
    player.max_mana = 0
    if case in {"attack", "crowded", "taunt"}:
        for _ in range(2):
            minion = player.summon("CS2_179")
            minion.turns_in_play = 1
        enemy.hero.damage = enemy.hero.max_health - (3 if case == "taunt" else 6)
        if case == "taunt":
            enemy.summon("CS1_042")
        for _ in range({"attack": 1, "crowded": 7, "taunt": 4}[case]):
            enemy.summon("CS2_231")
    elif case == "spells":
        player.max_mana = 6
        player.card("CS2_029", zone=Zone.HAND)
        player.card("CS2_024", zone=Zone.HAND)
        enemy.hero.damage = enemy.hero.max_health - 9
        for _ in range(3):
            enemy.summon("CS2_231")
    elif case in {"defend", "defend_three"}:
        player.hero.damage = player.hero.max_health - (6 if case == "defend" else 10)
        player.max_mana = 4
        player.card("CS2_029", zone=Zone.HAND)
        for _ in range(2 if case == "defend" else 3):
            minion = enemy.summon("CS2_182")
            minion.turns_in_play = 1
    return session, player


def finish_ai_turn(session, player, agent):
    for _ in range(16):
        if session.game.ended or session.game.current_player is not player:
            return
        before = normalized_game_state(session.game)
        rng = session.game.random.getstate()
        action = session.choose_action(player, agent=agent)
        assert action in session.legal_actions(player)
        assert normalized_game_state(session.game) == before
        assert session.game.random.getstate() == rng
        try:
            session.execute(player, action)
        except GameOver:
            return
    pytest.fail("tactical turn did not finish within sixteen actions")


@pytest.mark.parametrize("case", ["attack", "crowded", "spells", "taunt"])
@pytest.mark.parametrize("seed", [0, 2, 4, 7])
def test_v2_completes_lethal_without_losing_live_state(case, seed):
    session, player = tactical_scene(case)
    try:
        agent = MCTSAgent(seed=seed, policy_version="tactical_v2", time_budget=None,
                          max_iterations=16)
        finish_ai_turn(session, player, agent)
        assert session.game.ended
        assert player.opponent.hero.health <= 0 and player.hero.health > 0
    finally:
        session.close()


@pytest.mark.parametrize("seed", [0, 2, 4, 7])
@pytest.mark.parametrize("case", ["defend", "defend_three"])
def test_v2_clears_a_yeti_to_survive_visible_counterattack(seed, case):
    session, player = tactical_scene(case)
    try:
        agent = MCTSAgent(seed=seed, policy_version="tactical_v2", time_budget=None,
                          max_iterations=16)
        finish_ai_turn(session, player, agent)
        assert not session.game.ended
        assert session.game.current_player is player.opponent
        assert sum(m.atk for m in player.opponent.field if m.can_attack()) < player.hero.health
    finally:
        session.close()


@pytest.mark.parametrize("card_id, uncertain", [
    ("CS2_029", False),  # Deterministic Fireball.
    ("EX1_277", True),   # Random Arcane Missiles.
    ("CS2_023", True),   # Drawing identity-hidden cards.
])
def test_search_marks_uncertain_continuations_without_mutating_live_rng(card_id, uncertain):
    session, player = main_session()
    try:
        card = player.card(card_id, zone=Zone.HAND)
        legal = session.legal_actions(player)
        action = next(a for a in legal if a.source_entity_id == card.entity_id
                      and (a.target_entity_id is None or a.target_entity_id == player.opponent.hero.entity_id))
        rng = session.game.random.getstate()
        root = EngineSearchPosition.from_game(session.game, player)
        assert root.observation()["search_uncertain"] is False
        child = root.transition(action, seed=19)
        assert child.observation()["search_uncertain"] is uncertain
        assert session.game.random.getstate() == rng
    finally:
        session.close()


def test_hidden_ice_block_cannot_certify_an_attack_lethal():
    session, player = tactical_scene("attack")
    try:
        player.opponent.card("EX1_295", zone=Zone.SECRET)
        root = EngineSearchPosition.from_game(session.game, player)
        assert root.observation()["search_uncertain"] is True
        for _ in range(2):
            action = next(a for a in root.legal_actions()
                          if a.type == "ATTACK" and a.target_entity_id == player.opponent.hero.entity_id)
            root = root.transition(action)
        assert root.observation()["opponent"]["hero"]["health"] <= 0
        assert root.observation()["search_uncertain"] is True
        assert player.opponent.hero.health == 6
    finally:
        session.close()


@pytest.mark.parametrize("protection", ["frozen", "taunt", "shielded_taunt"])
def test_visible_reply_respects_engine_attack_restrictions(protection):
    from fireplace.search_tactics import evaluate_visible_opponent_reply
    session, player = tactical_scene("defend")
    try:
        if protection == "frozen":
            player.opponent.field[0].frozen = True
        else:
            guard = player.summon("CS2_179")
            if protection == "shielded_taunt":
                guard.divine_shield = True
        before = normalized_game_state(session.game)
        reply = EngineSearchPosition.from_game(session.game, player).opponent_attack_position()
        result = evaluate_visible_opponent_reply(reply, max_depth=8)
        assert result is not None and not result.self_lethal
        assert normalized_game_state(session.game) == before
    finally:
        session.close()


@pytest.mark.parametrize("seed", [0, 2, 4, 7])
def test_coin_unlocks_a_verified_fireball_lethal(seed):
    session, player = main_session()
    try:
        player.max_mana, player.temp_mana, player.used_mana = 3, 0, 0
        player.card("GAME_005", zone=Zone.HAND)
        player.card("CS2_029", zone=Zone.HAND)
        player.opponent.hero.damage = player.opponent.hero.max_health - 6
        agent = MCTSAgent(seed=seed, policy_version="tactical_v2", time_budget=None,
                          max_iterations=16)
        finish_ai_turn(session, player, agent)
        assert session.game.ended and player.opponent.hero.health <= 0
    finally:
        session.close()


def test_shielded_taunt_prevents_false_attack_lethal():
    from fireplace.search_tactics import find_deterministic_lethal
    session, player = tactical_scene("attack")
    try:
        guard = player.opponent.summon("CS1_042")
        guard.divine_shield = True
        root = EngineSearchPosition.from_game(session.game, player)
        result = find_deterministic_lethal(root.observation(), root.legal_actions(), root)
        assert result.action is None and not result.deterministic_lethal
        assert player.opponent.hero.health == 6
    finally:
        session.close()
