import pytest
from hearthstone.enums import Zone

from fireplace.actions import Shuffle
from fireplace.agent_api import Action
from fireplace.search_simulation import EngineSearchPosition
from tests.test_search_simulation import main_session


def _attacks_from(actions, source_entity_id):
    return [
        action
        for action in actions
        if action.type == "ATTACK" and action.source_entity_id == source_entity_id
    ]


def test_bounce_resets_private_zone_combat_state_and_replay_is_asleep():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 3
    minion.num_attacks = 1
    minion.frozen = True
    minion.damage = 2

    minion.bounce()

    assert minion.zone == Zone.HAND
    assert minion.turns_in_play == 0
    assert minion.num_attacks == 0
    assert not minion.frozen
    assert minion.damage == 0

    minion.play()
    assert minion.turns_in_play == 0
    assert minion.num_attacks == 0
    assert not minion.can_attack()
    assert not _attacks_from(session.legal_actions(player), minion.entity_id)


def test_shadowstep_keeps_post_bounce_buff_and_game_session_hides_attack():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 1
    minion.num_attacks = 1
    minion.frozen = True
    shadowstep = player.give("EX1_144")

    shadowstep_action = next(
        action
        for action in session.legal_actions(player)
        if action.type == "PLAY_CARD"
        and action.source_entity_id == shadowstep.entity_id
        and action.target_entity_id == minion.entity_id
    )
    session.execute(player, shadowstep_action)

    assert minion.zone == Zone.HAND
    assert minion.turns_in_play == 0
    assert minion.num_attacks == 0
    assert not minion.frozen
    assert minion.cost == 2
    hand_minion = next(
        card
        for card in session.observation(player)["self"]["hand"]
        if card["entity_id"] == minion.entity_id
    )
    assert hand_minion["cost"] == 2

    replay_action = next(
        action
        for action in session.legal_actions(player)
        if action.type == "PLAY_CARD" and action.source_entity_id == minion.entity_id
    )
    session.execute(player, replay_action)

    assert minion.zone == Zone.PLAY
    assert minion.turns_in_play == 0
    assert minion.num_attacks == 0
    assert not minion.frozen
    assert not minion.can_attack()
    board_minion = next(
        card
        for card in session.observation(player)["self"]["board"]
        if card["entity_id"] == minion.entity_id
    )
    assert not board_minion["can_attack"]
    assert not _attacks_from(session.legal_actions(player), minion.entity_id)


@pytest.mark.parametrize("card_id", ["CS2_171", "CS2_173"])
@pytest.mark.parametrize("frozen", [False, True])
def test_spent_charge_minion_gets_a_fresh_attack_after_replay(card_id, frozen):
    session, player = main_session()
    minion = player.summon(card_id)
    hero = player.opponent.hero

    minion.attack(hero)
    assert minion.num_attacks == 1
    assert not minion.can_attack()
    minion.frozen = frozen

    minion.bounce()
    minion.play()

    assert minion.turns_in_play == 0
    assert minion.num_attacks == 0
    assert not minion.frozen
    assert minion.can_attack(hero)
    minion.attack(hero)
    assert minion.num_attacks == 1


def test_windfury_replay_resets_attack_count():
    session, player = main_session()
    minion = player.summon("NEW1_010")
    hero = player.opponent.hero

    minion.attack(hero)
    assert minion.num_attacks == 1
    assert minion.can_attack(hero)

    minion.bounce()
    minion.play()

    assert minion.num_attacks == 0
    assert minion.can_attack(hero)
    minion.attack(hero)
    assert minion.num_attacks == 1
    assert minion.can_attack(hero)


def test_rush_replay_can_attack_minions_but_not_heroes():
    session, player = main_session()
    minion = player.summon("GIL_515")
    minion.turns_in_play = 1
    sacrifice = player.summon("CS2_182")
    enemy = player.opponent.summon("CS2_182")

    minion.bounce()
    minion.play(target=sacrifice)

    assert minion.turns_in_play == 0
    assert not minion.can_attack(player.opponent.hero)
    assert minion.can_attack(enemy)
    attacks = _attacks_from(session.legal_actions(player), minion.entity_id)
    assert [action.target_entity_id for action in attacks] == [enemy.entity_id]


def test_replay_on_next_own_turn_starts_asleep():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 1
    minion.bounce()

    session.execute(player, Action(type="END_TURN"))
    session.execute(player.opponent, Action(type="END_TURN"))
    assert session.game.current_player is player

    minion.play()

    assert minion.turns_in_play == 0
    assert not minion.can_attack()
    assert not _attacks_from(session.legal_actions(player), minion.entity_id)


def test_setaside_round_trip_preserves_combat_state():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 4
    minion.num_attacks = 1
    minion.frozen = True

    minion.zone = Zone.SETASIDE
    minion.zone = Zone.PLAY

    assert minion.turns_in_play == 4
    assert minion.num_attacks == 1
    assert minion.frozen


def test_same_zone_move_preserves_combat_state():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 4
    minion.num_attacks = 1
    minion.frozen = True

    minion.zone = Zone.PLAY

    assert minion.turns_in_play == 4
    assert minion.num_attacks == 1
    assert minion.frozen


def test_steal_setaside_round_trip_preserves_attacks_and_freeze():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 4
    minion.num_attacks = 1
    minion.frozen = True

    player.opponent.steal(minion)

    assert minion.controller is player.opponent
    assert minion.zone == Zone.PLAY
    assert minion.turns_in_play == 0
    assert minion.num_attacks == 1
    assert minion.frozen


def test_cross_controller_shuffle_enters_deck_with_fresh_combat_state():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 4
    minion.num_attacks = 1
    minion.frozen = True

    session.game.cheat_action(
        player,
        [Shuffle(player.opponent, minion)],
    )

    assert minion.controller is player.opponent
    assert minion.zone == Zone.DECK
    assert minion.turns_in_play == 0
    assert minion.num_attacks == 0
    assert not minion.frozen

    minion.draw()
    session.execute(player, Action(type="END_TURN"))
    receiver = player.opponent
    receiver.max_mana = 10
    replay_action = next(
        action for action in session.legal_actions(receiver)
        if action.type == "PLAY_CARD" and action.source_entity_id == minion.entity_id
    )
    session.execute(receiver, replay_action)
    assert not minion.can_attack()
    assert not _attacks_from(session.legal_actions(receiver), minion.entity_id)


def test_search_clone_bounce_replay_excludes_stale_attack():
    session, player = main_session()
    minion = player.summon("CS2_182")
    minion.turns_in_play = 1
    shadowstep = player.give("EX1_144")

    position = EngineSearchPosition.from_game(session.game, player, seed=23)
    shadowstep_action = next(
        action
        for action in position.legal_actions()
        if action.type == "PLAY_CARD"
        and action.source_entity_id == shadowstep.entity_id
        and action.target_entity_id == minion.entity_id
    )
    bounced = position.transition(shadowstep_action)
    replay_action = next(
        action
        for action in bounced.legal_actions()
        if action.type == "PLAY_CARD" and action.source_entity_id == minion.entity_id
    )
    replayed = bounced.transition(replay_action)

    board_minion = next(
        card
        for card in replayed.observation()["self"]["board"]
        if card["entity_id"] == minion.entity_id
    )
    assert not board_minion["can_attack"]
    assert not _attacks_from(replayed.legal_actions(), minion.entity_id)
