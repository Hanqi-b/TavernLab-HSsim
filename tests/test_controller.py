import json
import io
import re
from types import SimpleNamespace

import pytest
from hearthstone.enums import CardClass, MultiClassGroup, Zone

from fireplace import cards
from fireplace.agent_api import Action
from fireplace.controller import ActionError, GameSession, decision_player
from fireplace.exceptions import GameOver
from fireplace.game import Game
from fireplace.player import Player


cards.db.initialize()


def session(deck=None, seed=3, hero=None):
    hero = hero or CardClass.DRUID.default_hero
    deck = deck if deck is not None else ["CS2_231"] * 10
    p1 = Player("One", deck[:], hero)
    p2 = Player("Two", deck[:], hero)
    game = Game((p1, p2), seed=seed)
    return GameSession(game, {})


def finish_mulligan(current):
    current.start()
    assert decision_player(current.game) in current.game.players
    for _ in range(2):
        player = decision_player(current.game)
        assert current.observation(player)["phase"] == "MULLIGAN"
        current.execute(player, Action(type="MULLIGAN"))
    assert current.game.current_player is not None


def test_mulligan_and_stale_rejection():
    current = session()
    current.start()
    p = decision_player(current.game)
    actions = current.legal_actions(p)
    assert Action(type="MULLIGAN") in actions
    assert any(a.mulligan_entity_ids for a in actions)
    hand = tuple(card.entity_id for card in p.hand)
    with pytest.raises(ActionError):
        current.execute(p, Action(type="MULLIGAN", mulligan_entity_ids=(999999,)))
    assert tuple(card.entity_id for card in p.hand) == hand
    finish_mulligan(current)
    with pytest.raises(ActionError):
        current.execute(p, Action(type="MULLIGAN"))


def test_concede_is_explicit_but_not_an_ai_legal_action():
    current = session()
    current.start()
    player = decision_player(current.game)
    other = next(candidate for candidate in current.game.players if candidate is not player)
    concede = Action(type="CONCEDE")

    assert concede not in current.legal_actions(player)
    with pytest.raises(ActionError, match="current decision"):
        current.execute(other, concede)
    assert not current.game.ended

    with pytest.raises(GameOver):
        current.execute(player, concede)
    assert current.game.ended
    assert current.action_log.to_dict()["actions"][-1]["action"] == concede.to_dict()
    assert current.action_log.to_dict()["status"] == "complete"


def test_agent_cannot_invent_concede_outside_legal_actions():
    class MaliciousAgent:
        def choose_action(self, _observation, _legal_actions):
            return Action(type="CONCEDE")

    current = session()
    current.start()
    player = decision_player(current.game)
    current.agents[player] = MaliciousAgent()

    with pytest.raises(ActionError, match="unavailable"):
        current._run_agent_action(player)
    assert not current.game.ended


def test_minion_positions_and_end_turn():
    current = session()
    finish_mulligan(current)
    player = current.game.current_player
    player.discard_hand()
    first = player.give("CS2_231")
    second = player.give("CS2_231")
    plays = [a for a in current.legal_actions(player)
             if a.type == "PLAY_CARD" and a.source_entity_id == first.entity_id]
    assert {a.position for a in plays} == {0}
    current.execute(player, plays[0])
    assert first.zone == Zone.PLAY
    plays = [a for a in current.legal_actions(player)
             if a.type == "PLAY_CARD" and a.source_entity_id == second.entity_id]
    assert {a.position for a in plays} == {0, 1}
    current.execute(player, next(a for a in plays if a.position == 0))
    assert list(player.field)[:2] == [second, first]
    with pytest.raises(ActionError):
        current.execute(player, plays[0])
    current.execute(player, Action(type="END_TURN"))
    assert current.game.current_player is player.opponent


def test_choose_one_uses_parent_card():
    current = session(hero=CardClass.DRUID.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    nourish = player.give("EX1_164")
    visible = next(card for card in current.observation(player)["self"]["hand"]
                   if card["entity_id"] == nourish.entity_id)
    assert len(visible["choose_options"]) == 2
    actions = [a for a in current.legal_actions(player)
               if a.type == "PLAY_CARD" and a.source_entity_id == nourish.entity_id]
    assert len({a.choose_option_entity_id for a in actions}) == 2
    current.execute(player, actions[0])
    assert nourish not in player.hand
    assert nourish.zone != Zone.HAND


def test_targeted_spell_and_choice_phase():
    current = session(hero=CardClass.MAGE.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    fireball = player.give("CS2_029")
    actions = [a for a in current.legal_actions(player)
               if a.type == "PLAY_CARD" and a.source_entity_id == fireball.entity_id]
    assert {a.target_entity_id for a in actions} >= {
        player.hero.entity_id, player.opponent.hero.entity_id
    }
    with pytest.raises(ActionError):
        current.execute(player, Action(type="PLAY_CARD", source_entity_id=fireball.entity_id,
                                       target_entity_id=999999))
    assert fireball in player.hand
    target = player.opponent.hero
    current.execute(player, next(a for a in actions if a.target_entity_id == target.entity_id))
    assert target.health == 24
    assert fireball not in player.hand



def test_discover_blocks_main_actions_until_chosen():
    current = session(hero=CardClass.PRIEST.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    curator = player.give("LOE_006")
    play = next(a for a in current.legal_actions(player)
                if a.type == "PLAY_CARD" and a.source_entity_id == curator.entity_id)
    current.execute(player, play)
    assert current.observation(player)["phase"] == "CHOICE"
    actions = current.legal_actions(player)
    assert actions and {a.type for a in actions} == {"CHOOSE"}
    with pytest.raises(ActionError):
        current.execute(player, Action(type="END_TURN"))
    current.execute(player, actions[0])
    assert player.choice is None
    assert current.observation(player)["phase"] == "MAIN"


def test_multiple_choice_refreshes_options_between_steps():
    current = session()
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    siamat = player.give("ULD_178")
    current.execute(player, next(a for a in current.legal_actions(player)
                                 if a.type == "PLAY_CARD" and a.source_entity_id == siamat.entity_id))
    first = current.legal_actions(player)
    assert len(first) == 4 and {a.type for a in first} == {"CHOOSE"}
    current.execute(player, first[0])
    second = current.legal_actions(player)
    assert len(second) == 3 and first[0] not in second
    current.execute(player, second[0])
    assert player.choice is None
    assert current.observation(player)["phase"] == "MAIN"


def test_hero_power_and_minion_attack():
    current = session(hero=CardClass.MAGE.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    wisp = player.give("CS2_231")
    current.execute(player, next(a for a in current.legal_actions(player)
                                 if a.type == "PLAY_CARD" and a.source_entity_id == wisp.entity_id))
    power_actions = [a for a in current.legal_actions(player)
                     if a.type == "USE_HERO_POWER"]
    assert {a.target_entity_id for a in power_actions} >= {
        player.hero.entity_id, player.opponent.hero.entity_id
    }
    enemy = player.opponent.hero
    current.execute(player, next(a for a in power_actions
                                 if a.target_entity_id == enemy.entity_id))
    assert enemy.health == 29
    assert not any(a.type == "USE_HERO_POWER" for a in current.legal_actions(player))
    current.execute(player, Action(type="END_TURN"))
    current.execute(player.opponent, Action(type="END_TURN"))
    attack = next(a for a in current.legal_actions(player)
                  if a.type == "ATTACK" and a.source_entity_id == wisp.entity_id
                  and a.target_entity_id == enemy.entity_id)
    current.execute(player, attack)
    assert enemy.health == 28


def test_taunt_filters_attack_targets():
    current = session()
    finish_mulligan(current)
    player = current.game.current_player
    wisp = player.give("CS2_231")
    current.execute(player, next(a for a in current.legal_actions(player)
                                 if a.type == "PLAY_CARD" and a.source_entity_id == wisp.entity_id))
    current.execute(player, Action(type="END_TURN"))
    taunt = player.opponent.summon("CS1_042")
    current.execute(player.opponent, Action(type="END_TURN"))
    attacks = [a for a in current.legal_actions(player)
               if a.type == "ATTACK" and a.source_entity_id == wisp.entity_id]
    assert {a.target_entity_id for a in attacks} == {taunt.entity_id}


def test_observation_exposes_public_minion_statuses_on_both_boards():
    current = session()
    finish_mulligan(current)
    player = current.game.current_player

    minions = {
        "dormant": player.summon("BT_156"),       # Dormant, Rush
        "lifesteal": player.summon("BT_197"),     # Lifesteal
        "poisonous": player.summon("EX1_170"),    # Poisonous
        "reborn": player.summon("ULD_208"),       # Taunt, Reborn
        "windfury": player.summon("CS2_169"),    # Windfury
        "charge": player.summon("CS2_171"),       # Charge
        "silenced": player.summon("EX1_021"),     # Silence removes Windfury
    }
    minions["silenced"].silence()
    opponent_minion = player.opponent.summon("EX1_170")
    deathrattle_minion = player.opponent.summon("EX1_556")

    view = current.observation(player)
    own_board = {card["card_id"]: card for card in view["self"]["board"]}
    opponent_board = {card["card_id"]: card for card in view["opponent"]["board"]}

    assert own_board["BT_156"]["dormant"] is True
    assert own_board["BT_156"]["dormant_turns"] == 2
    assert "dormant_turns" not in own_board["BT_197"]
    assert own_board["BT_197"]["lifesteal"] is True
    assert own_board["EX1_170"]["poisonous"] is True
    assert own_board["ULD_208"]["taunt"] is True
    assert own_board["ULD_208"]["reborn"] is True
    assert own_board["CS2_169"]["windfury"] is True
    assert own_board["CS2_171"]["charge"] is True
    assert own_board["BT_156"]["rush"] is True
    assert own_board["EX1_021"]["silenced"] is True
    assert own_board["EX1_021"]["windfury"] is False
    for field in ("taunt", "divine_shield", "frozen", "stealthed", "can_attack"):
        assert field in own_board["BT_156"]

    assert opponent_board["EX1_170"]["entity_id"] == opponent_minion.entity_id
    assert opponent_board["EX1_170"]["poisonous"] is True
    assert opponent_board["EX1_556"]["entity_id"] == deathrattle_minion.entity_id
    assert opponent_board["EX1_556"]["has_deathrattle"] is True
    assert "hand" not in view["opponent"]
    assert "hand_count" in view["opponent"]

    deathrattle_minion.silence()
    silenced_view = current.observation(player)
    silenced_minion = next(card for card in silenced_view["opponent"]["board"]
                            if card["entity_id"] == deathrattle_minion.entity_id)
    assert silenced_minion["has_deathrattle"] is False


def test_observation_records_active_buff_and_deathrattle_source_without_hidden_cards():
    current = session(hero=CardClass.PALADIN.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    minion = player.summon("CS2_231")
    spell = player.give("UNG_952")
    play = next(action for action in current.legal_actions(player)
                if action.type == "PLAY_CARD" and action.source_entity_id == spell.entity_id
                and action.target_entity_id == minion.entity_id)
    current.execute(player, play)

    public = current.observation(player)["self"]["board"][0]
    assert (public["printed_atk"], public["atk"]) == (1, 3)
    assert (public["printed_health"], public["max_health"]) == (1, 7)
    assert public["has_deathrattle"] is True
    assert public["active_modifiers"] == [{
        "kind": "enchantment",
        "effect": {"card_id": "UNG_952e", "name": "On a Stegodon"},
        "source": {"card_id": "UNG_952", "name": "Spikeridged Steed"},
        "grants": ["deathrattle"],
    }]

    # A card still in the opponent's hand may cause an effect, but its
    # identity must not enter the public projection or asset allowlist.
    hidden_source = player.opponent.give("CS2_092")
    hidden_source.buff(minion, "CS2_092e")
    opposite_view = current.observation(player)
    hidden_modifier = opposite_view["self"]["board"][0]["active_modifiers"][-1]
    assert hidden_modifier["effect"] is None
    assert hidden_modifier["source"] is None
    assert hidden_source.id not in json.dumps(opposite_view)

    minion.silence()
    after = current.observation(player)["self"]["board"][0]
    assert after["has_deathrattle"] is False
    assert after["active_modifiers"] == []


def test_weapon_hero_attack_uses_attack_action():
    current = session(hero=CardClass.PALADIN.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    weapon = player.give("CS2_091")
    current.execute(player, next(a for a in current.legal_actions(player)
                                 if a.type == "PLAY_CARD" and a.source_entity_id == weapon.entity_id))
    attacks = [a for a in current.legal_actions(player)
               if a.type == "ATTACK" and a.source_entity_id == player.hero.entity_id]
    assert any(a.target_entity_id == player.opponent.hero.entity_id for a in attacks)
    current.execute(player, next(a for a in attacks
                                 if a.target_entity_id == player.opponent.hero.entity_id))
    assert player.opponent.hero.health == 29


def test_random_agents_finish_a_game():
    from fireplace.agents import RandomAgent

    current = session(deck=["CS2_231"] * 5)
    current.agents = {
        current.game.players[0]: RandomAgent(seed=1),
        current.game.players[1]: RandomAgent(seed=2),
    }
    result = current.run()
    assert result.ended
    assert result.turn > 0


def test_run_turn_keeps_random_session_explicit():
    from fireplace.agents import RandomAgent
    from fireplace.utils import play_turn, setup_game

    game = setup_game(seed=17)
    agent = RandomAgent(seed=17)
    current = GameSession(game, {player: agent for player in game.players})

    play_turn(game, session=current)

    assert current.game is game
    assert not hasattr(game, "_random_session")


def test_legacy_play_turn_preserves_policy_stream_without_game_state():
    from fireplace.replay_state import normalized_game_state
    from fireplace.utils import play_turn, setup_game

    first = setup_game(seed=23)
    second = setup_game(seed=23)
    first_observers = len(first.manager.observers)
    for _ in range(2):
        play_turn(first)
        play_turn(second)

    assert normalized_game_state(first) == normalized_game_state(second)
    assert not hasattr(first, "_random_session")
    assert len(first.manager.observers) == first_observers


def test_random_match_factories_preserve_seeded_setup():
    import hashlib

    from fireplace.match_factory import build_random_game
    from fireplace.utils import setup_game

    shared = build_random_game(
        73, player_names=("Player1", "Player2")
    )
    batch = setup_game(seed=73, start=False)

    assert [
        (player.starting_hero, player.starting_deck)
        for player in shared[0].players
    ] == [
        (player.starting_hero, player.starting_deck)
        for player in batch.players
    ]
    assert shared[0].random.getstate() == batch.random.getstate()

    payload = "|".join(
        [
            *(player.starting_hero for player in shared[0].players),
            *(card for player in shared[0].players for card in player.starting_deck),
        ]
    )
    assert [player.starting_hero for player in shared[0].players] == [
        "HERO_09",
        "HERO_05",
    ]
    # This snapshot includes the corrected dual-class eligibility pool.
    for player in shared[0].players:
        hero_class = cards.db[player.starting_hero].card_class
        for card_id in player.starting_deck:
            classes = set(cards.db[card_id].classes)
            if len(classes) > 1:
                classes.discard(CardClass.NEUTRAL)
            assert hero_class in classes or classes == {CardClass.NEUTRAL}
    assert hashlib.sha256(payload.encode()).hexdigest() == (
        "30b03bc2eaab700a96c6f89a748493d9df27861caf382f8df5bc7be22fbcbb8e"
    )


def test_random_match_factory_initializes_card_db_once(monkeypatch):
    from fireplace import cards
    from fireplace.match_factory import build_random_game

    original_initialize = cards.db.initialize
    initial_state = cards.db.initialized
    calls = []

    def initialize(*args, **kwargs):
        calls.append((args, kwargs))
        return original_initialize(*args, **kwargs)

    monkeypatch.setattr(cards.db, "initialize", initialize)
    cards.db.initialized = False
    try:
        first = build_random_game(seed=101)
        second = build_random_game(seed=101)
    finally:
        cards.db.initialized = initial_state

    assert len(calls) == 1
    assert [
        (player.starting_hero, player.starting_deck)
        for player in first[0].players
    ] == [
        (player.starting_hero, player.starting_deck)
        for player in second[0].players
    ]
    assert first[0].random.getstate() == second[0].random.getstate()


def test_human_tui_and_random_share_session_to_game_over():
    from fireplace.agents import HumanTUIAgent, RandomAgent

    current = session(deck=["CS2_231"] * 5)
    output = io.StringIO()

    def select_last(prompt):
        return re.search(r"1-(\d+)", prompt).group(1)

    current.agents = {
        current.game.players[0]: HumanTUIAgent(input_fn=select_last, output=output),
        current.game.players[1]: RandomAgent(seed=7),
    }
    assert current.run().ended
    assert "MULLIGAN" in output.getvalue()
    assert "MAIN" in output.getvalue()


def test_observation_hides_opponent_hand_and_secret_identity():
    current = session()
    current.start()
    viewer = current.game.players[0]
    opponent = viewer.opponent
    data = current.observation(viewer)
    assert "hand_count" in data["opponent"]
    assert "hand" not in data["opponent"]
    assert "pending_choice" not in data["opponent"]
    assert data["self"]["hand"]
    assert json.loads(json.dumps(data)) == data
    opponent_hand_id = opponent.hand[0].entity_id
    assert str(opponent_hand_id) not in json.dumps(data["opponent"])


def test_active_quests_are_public_but_opponent_secrets_stay_concealed():
    current = session(hero=CardClass.DRUID.default_hero)
    finish_mulligan(current)
    player = current.game.current_player
    player.max_mana = 10
    quest = player.give("UNG_116")
    sidequest = player.give("DRG_051")
    secret = player.give("EX1_287")
    multi_class_secret = player.give("EX1_611")
    multi_class_secret.multi_class_group = MultiClassGroup.MAGE_ROGUE
    for card in (quest, sidequest, secret, multi_class_secret):
        play = next(action for action in current.legal_actions(player)
                    if action.type == "PLAY_CARD" and action.source_entity_id == card.entity_id)
        current.execute(player, play)
    quest.progress = 2
    sidequest.progress = 4

    own = current.observation(player)["self"]
    seen_by_opponent = current.observation(player.opponent)["opponent"]
    assert [card["card_id"] for card in own["secrets"]] == ["EX1_287", "EX1_611"]
    assert own["quests"] == seen_by_opponent["quests"]
    assert [(card["card_id"], card["kind"], card["progress"], card["progress_total"])
            for card in own["quests"]] == [
                ("UNG_116", "quest", 2, 5),
                ("DRG_051", "sidequest", 4, 10),
            ]
    assert seen_by_opponent["secrets_count"] == 2
    assert seen_by_opponent["secret_classes"] == [["MAGE"], ["MAGE", "ROGUE"]]
    assert "secrets" not in seen_by_opponent
    assert "EX1_287" not in json.dumps(seen_by_opponent)
    assert "EX1_611" not in json.dumps(seen_by_opponent)
    assert str(secret.entity_id) not in json.dumps(seen_by_opponent)
    assert str(multi_class_secret.entity_id) not in json.dumps(seen_by_opponent)


@pytest.mark.parametrize("unknown", [None, "NOT_A_CARD_CLASS", 999999, object()])
def test_unknown_secret_class_falls_back_to_an_empty_public_class_list(unknown):
    from fireplace.observation import _secret_class_names

    card = SimpleNamespace(classes=[unknown], card_class=unknown)
    assert _secret_class_names(card) == []


def test_opponent_cannot_see_secret_or_pending_discover_options():
    mage = session(hero=CardClass.MAGE.default_hero)
    finish_mulligan(mage)
    player = mage.game.current_player
    player.max_mana = 10
    secret = player.give("EX1_287")
    mage.execute(player, next(a for a in mage.legal_actions(player)
                              if a.type == "PLAY_CARD" and a.source_entity_id == secret.entity_id))
    hidden = mage.observation(player.opponent)
    assert hidden["opponent"]["secrets_count"] == 1
    assert "secrets" not in hidden["opponent"]
    assert hidden["pending_choice"] is None

    priest = session(hero=CardClass.PRIEST.default_hero)
    finish_mulligan(priest)
    player = priest.game.current_player
    player.max_mana = 10
    curator = player.give("LOE_006")
    priest.execute(player, next(a for a in priest.legal_actions(player)
                                if a.type == "PLAY_CARD" and a.source_entity_id == curator.entity_id))
    assert priest.observation(player)["pending_choice"]["options"]
    assert priest.observation(player.opponent)["pending_choice"] is None
    priest.execute(player, priest.legal_actions(player)[0])


def test_action_json_round_trip():
    action = Action(type="PLAY_CARD", source_entity_id=5, target_entity_id=6,
                    choose_option_entity_id=7, position=0)
    assert Action.from_dict(json.loads(json.dumps(action.to_dict()))) == action
    concede = Action(type="CONCEDE")
    assert Action.from_dict(json.loads(json.dumps(concede.to_dict()))) == concede
    with pytest.raises(ValueError):
        Action.from_dict({"type": "END_TURN", "extra": 1})


def test_interactive_agent_retries_after_stale_action():
    from fireplace.agents import HumanTUIAgent, RandomAgent

    class StaleOnce(HumanTUIAgent):
        def __init__(self):
            super().__init__(input_fn=lambda prompt: re.search(r"1-(\d+)", prompt).group(1),
                             output=io.StringIO())
            self.sent_stale = False

        def choose_action(self, observation, legal_actions):
            if not self.sent_stale:
                self.sent_stale = True
                return Action(type="CHOOSE", choice_entity_id=999999)
            return super().choose_action(observation, legal_actions)

    human = StaleOnce()
    current = session(deck=["CS2_231"] * 5)
    current.agents = {
        current.game.players[0]: human,
        current.game.players[1]: RandomAgent(seed=7),
    }
    assert current.run().ended
    assert "Action unavailable" in human.output.getvalue()
