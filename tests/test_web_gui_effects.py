"""Focused checks for the web effect timeline and its privacy boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from hearthstone.enums import Zone

from fireplace import cards
from fireplace.controller import GameSession
from fireplace.game import Game
from fireplace.player import Player
from fireplace.web_gui.effect_timeline import EffectTimeline
from fireplace.web_gui.server import WebGame


cards.db.initialize()


class PassAgent:
    def choose_action(self, observation, actions):
        del observation
        return next((action for action in actions if action.type == "END_TURN"), actions[0])


@pytest.fixture
def effect_game():
    human = Player("Human", ["CS2_231"] * 30, "HERO_08")
    opponent = Player("Opponent", ["CS2_231"] * 30, "HERO_01")
    app = WebGame(
        GameSession(Game((human, opponent), seed=7), {}),
        human,
        PassAgent(),
    )
    yield app, human, opponent
    app.close()


def _start_main(app):
    state = app.snapshot()
    mulligan = next(
        action for action in state["legal_actions"]
        if action["type"] == "MULLIGAN" and not action["mulligan_entity_ids"]
    )
    return app.handle_action({
        "session_id": state["session_id"],
        "revision": state["revision"],
        "action": mulligan,
    })


def _prepare_hand(human):
    human.max_mana = 10
    human.used_mana = 0
    for card in list(human.hand):
        card.zone = Zone.SETASIDE


def _trim_deck(human, count):
    for card in list(human.deck)[count:]:
        card.zone = Zone.SETASIDE


def _prepare_fatigue_card(human, *, deck_size=0):
    _prepare_hand(human)
    _trim_deck(human, deck_size)
    return human.give("CS2_023")


def _play(app, state, source_id, target_id=None):
    candidates = [
        action for action in state["legal_actions"]
        if action["type"] == "PLAY_CARD"
        and action.get("source_entity_id") == source_id
        and (target_id is None or action.get("target_entity_id") == target_id)
    ]
    assert candidates
    return app.handle_action({
        "session_id": state["session_id"],
        "revision": state["revision"],
        "action": candidates[0],
    })


def _events(response):
    return [effect["event"] for frame in response["presentation_steps"]
            for effect in frame.get("effects", [])]


def _records(response):
    return [effect for frame in response["presentation_steps"]
            for effect in frame.get("effects", [])]


def test_battlecry_lethal_deathrattle_and_token_effects(effect_game):
    app, human, opponent = effect_game
    _start_main(app)
    _prepare_hand(human)
    archer = human.give("CS2_189")
    creeper = opponent.summon("FP1_002")
    creeper.damage = 1

    state = app.snapshot()
    response = _play(app, state, archer.entity_id, creeper.entity_id)
    records = _records(response)
    effects = [record["event"] for record in records]
    types = [event["type"] for event in effects]

    assert types[:4] == ["BATTLECRY", "DAMAGE", "DEATH", "DEATHRATTLE"]
    assert types.count("SUMMON") == 2
    assert effects[1]["amount"] == 1
    assert effects[1]["target_entity_id"] == creeper.entity_id
    damage_observation = records[1]["observation"]
    damage_card = next(
        card for card in damage_observation["opponent"]["board"]
        if card["entity_id"] == creeper.entity_id
    )
    assert damage_card["health"] <= 0
    assert all("_source_card_id" not in event for event in effects)
    assert all("_target_card_id" not in event for event in effects)
    assert response["observation"]["opponent"]["board"]


def test_aoe_batches_and_chained_deaths_keep_simultaneous_order(effect_game):
    app, human, opponent = effect_game
    _start_main(app)
    _prepare_hand(human)
    flamestrike = human.give("CS2_032")
    sheep = opponent.summon("GVG_076")
    wisp = opponent.summon("CS2_231")
    abomination = human.summon("EX1_097")
    abomination.damage = abomination.max_health - 2
    yeti = human.summon("CS2_182")
    yeti.damage = yeti.max_health - 3

    response = _play(app, app.snapshot(), flamestrike.entity_id)
    effects = _events(response)
    damage = [event for event in effects if event["type"] == "DAMAGE"]
    first_wave = [event for event in damage if event["target_entity_id"] in
                  {sheep.entity_id, wisp.entity_id}]
    assert len(first_wave) == 2
    assert len({event["batch_id"] for event in first_wave}) == 1
    assert first_wave[0]["batch_id"] != next(
        event["batch_id"] for event in damage
        if event["target_entity_id"] == abomination.entity_id
    )

    death_ids = [event["target_entity_id"] for event in effects
                 if event["type"] == "DEATH"]
    first_wave_deaths = [event for event in effects
                         if event["type"] == "DEATH"
                         and event["target_entity_id"] in
                         {sheep.entity_id, wisp.entity_id}]
    assert len({event["batch_id"] for event in first_wave_deaths}) == 1
    first_deathrattle = next(
        index for index, event in enumerate(effects)
        if event["type"] == "DEATHRATTLE"
    )
    assert death_ids[:2] == [sheep.entity_id, wisp.entity_id]
    death_positions = {
        event["target_entity_id"]: index
        for index, event in enumerate(effects)
        if event["type"] == "DEATH"
    }
    assert death_positions[sheep.entity_id] < first_deathrattle
    assert death_positions[wisp.entity_id] < first_deathrattle
    assert len(death_ids) == len(set(death_ids))
    assert effects[first_deathrattle]["source_entity_id"] == sheep.entity_id
    assert any(
        event["type"] == "DEATHRATTLE"
        and event["source_entity_id"] == abomination.entity_id
        for event in effects
    )


def test_shield_damage_and_direct_destroy_are_distinct_effects(effect_game):
    app, human, opponent = effect_game
    _start_main(app)
    _prepare_hand(human)
    shielded = opponent.summon("EX1_067")
    fireball = human.give("CS2_029")
    response = _play(app, app.snapshot(), fireball.entity_id, shielded.entity_id)
    damage = next(event for event in _events(response) if event["type"] == "DAMAGE")
    assert damage["amount"] == 0
    assert damage["shield_broken"] is True

    siphon = human.give("EX1_309")
    response = _play(app, app.snapshot(), siphon.entity_id, shielded.entity_id)
    effects = _events(response)
    assert any(
        event["type"] == "DESTROY"
        and event["target_entity_id"] == shielded.entity_id
        for event in effects
    )
    # Destroy marks a live minion and the normal death pass subsequently
    # emits its DEATH callback; both records are useful to the presentation
    # timeline and are intentionally distinct.
    assert any(
        event["type"] == "DEATH"
        and event["target_entity_id"] == shielded.entity_id
        for event in effects
    )


def test_elysiana_coalesces_private_deck_destroy_and_rebuilds_ten_cards(effect_game):
    app, human, _opponent = effect_game
    _start_main(app)
    _prepare_hand(human)
    _trim_deck(human, 11)
    elysiana = human.give("DAL_736")

    response = _play(app, app.snapshot(), elysiana.entity_id)
    effects = _records(response)
    deck_destroy = [record for record in effects
                    if record["event"]["type"] == "DECK_DESTROY"]
    assert len(deck_destroy) == 1
    event = deck_destroy[0]["event"]
    assert event["actor"] == "self"
    assert event["amount"] == 11
    assert not any(key.startswith("target") or key.startswith("_target")
                   for key in event)
    assert response["observation"]["self"]["deck_count"] == 0
    assert response["observation"]["self"]["deck_count"] == deck_destroy[0]["observation"]["self"]["deck_count"]
    assert not any(record["event"]["type"] == "DESTROY" for record in effects)

    for expected_count in (2, 4, 6, 8, 10):
        choice = next(action for action in response["legal_actions"]
                      if action["type"] == "CHOOSE")
        response = app.handle_action({
            "session_id": response["session_id"],
            "revision": response["revision"],
            "action": choice,
        })
        assert response["observation"]["self"]["deck_count"] == expected_count

    assert len(human.deck) == 10


def test_attack_marks_direct_combat_hits_but_not_attack_trigger_damage(effect_game):
    app, human, opponent = effect_game
    _start_main(app)
    _prepare_hand(human)
    attacker = human.summon("CS2_182")
    attacker.turns_in_play = 1
    defender = opponent.summon("CS2_182")
    adjacent = opponent.summon("CS2_182")
    sweeping_strikes = human.give("DAL_062")

    response = _play(app, app.snapshot(), sweeping_strikes.entity_id, attacker.entity_id)
    attack = next(action for action in response["legal_actions"]
                  if action["type"] == "ATTACK"
                  and action.get("source_entity_id") == attacker.entity_id
                  and action.get("target_entity_id") == defender.entity_id)
    response = app.handle_action({
        "session_id": response["session_id"],
        "revision": response["revision"],
        "action": attack,
    })
    damage = [event for event in _events(response) if event["type"] == "DAMAGE"]
    direct = next(event for event in damage
                  if event.get("source_entity_id") == attacker.entity_id
                  and event.get("target_entity_id") == defender.entity_id)
    reflected = next(event for event in damage
                     if event.get("source_entity_id") == defender.entity_id
                     and event.get("target_entity_id") == attacker.entity_id)
    extra = next(event for event in damage
                 if event.get("target_entity_id") == adjacent.entity_id)
    assert direct["combat_damage"] is True
    assert reflected["combat_damage"] is True
    assert "combat_damage" not in extra


def test_fatigue_uses_public_hero_and_pre_hit_observations(effect_game):
    app, human, _opponent = effect_game
    _start_main(app)
    intellect = _prepare_fatigue_card(human, deck_size=1)
    engineer_one = human.give("EX1_015")
    engineer_two = human.give("EX1_015")

    # Arcane Intellect draws the last card normally, then reaches an empty
    # deck and emits exactly one fatigue tick in the same accepted action.
    response = _play(app, app.snapshot(), intellect.entity_id)
    records = _records(response)
    effects = [record["event"] for record in records]
    fatigue = [event for event in effects if event["type"] == "FATIGUE"]
    damage = [event for event in effects if event["type"] == "DAMAGE"]
    assert len(fatigue) == len(damage) == 1
    assert fatigue[0]["actor"] == damage[0]["actor"] == "self"
    assert fatigue[0]["target_entity_id"] == human.hero.entity_id
    assert "source_entity_id" not in fatigue[0]
    assert fatigue[0]["amount"] == damage[0]["amount"] == 1
    assert fatigue[0]["target_entity_id"] != human.entity_id
    assert fatigue[0]["target_name"] == "Jaina Proudmoore"

    fatigue_record = next(record for record in records
                          if record["event"]["type"] == "FATIGUE")
    damage_record = next(record for record in records
                         if record["event"]["type"] == "DAMAGE")
    fatigue_observation = fatigue_record["observation"]
    damage_observation = damage_record["observation"]
    assert fatigue_observation["self"]["deck_count"] == 0
    assert fatigue_observation["self"]["hero"]["health"] == 30
    assert damage_observation["self"]["hero"]["health"] == 29
    assert any(card["card_id"] == "CS2_231"
               for card in response["observation"]["self"]["hand"])
    assert "hand" not in fatigue_observation["opponent"]
    assert "deck" not in fatigue_observation["opponent"]
    assert all(not key.startswith("_") for key in fatigue[0])

    # Later empty-deck draws advance the counter and damage in ascending
    # order, while preserving the same public hero target.
    expected = ((engineer_one, 2), (engineer_two, 3))
    for engineer, amount in expected:
        response = _play(app, response, engineer.entity_id)
        records = _records(response)
        fatigue = [event for event in _events(response)
                   if event["type"] == "FATIGUE"]
        damage = [event for event in _events(response)
                  if event["type"] == "DAMAGE"]
        assert len(fatigue) == len(damage) == 1
        assert fatigue[0]["amount"] == damage[0]["amount"] == amount
        assert fatigue[0]["target_entity_id"] == human.hero.entity_id
        assert all(not key.startswith("_") for key in fatigue[0])


def test_fatigue_damage_consumes_hero_armor_before_health(effect_game):
    app, human, _opponent = effect_game
    _start_main(app)
    intellect = _prepare_fatigue_card(human)
    human.hero.armor = 2

    response = _play(app, app.snapshot(), intellect.entity_id)
    effects = _events(response)
    fatigue = next(event for event in effects if event["type"] == "FATIGUE")
    damage = next(event for event in effects if event["type"] == "DAMAGE")
    assert fatigue["amount"] == 1
    assert damage["amount"] == 1
    armor_snapshot = next(record["observation"] for record in _records(response)
                           if record["event"]["type"] == "FATIGUE")
    assert armor_snapshot["self"]["hero"]["armor"] == 2
    first_damage_snapshot = next(
        record["observation"] for record in _records(response)
        if record["event"]["type"] == "DAMAGE"
        and record["event"]["amount"] == 1
    )
    assert first_damage_snapshot["self"]["hero"]["armor"] == 1
    assert first_damage_snapshot["self"]["hero"]["health"] == 30
    final_hero = response["observation"]["self"]["hero"]
    assert final_hero["armor"] == 0
    assert final_hero["health"] == 29


def test_fatigue_still_records_when_hero_is_immune(effect_game):
    app, human, _opponent = effect_game
    _start_main(app)
    intellect = _prepare_fatigue_card(human)
    human.hero.cant_be_damaged = True

    response = _play(app, app.snapshot(), intellect.entity_id)
    effects = _events(response)
    assert [event["type"] for event in effects].count("FATIGUE") == 2
    assert not any(event["type"] == "DAMAGE" for event in effects)
    fatigue = [event for event in effects if event["type"] == "FATIGUE"]
    assert [event["amount"] for event in fatigue] == [1, 2]
    assert all(event["target_entity_id"] == human.hero.entity_id for event in fatigue)


def test_cant_fatigue_suppresses_fatigue_and_damage_records(effect_game):
    app, human, _opponent = effect_game
    _start_main(app)
    intellect = _prepare_fatigue_card(human)
    human.cant_fatigue = True

    response = _play(app, app.snapshot(), intellect.entity_id)
    effects = _events(response)
    assert not any(event["type"] in {"FATIGUE", "DAMAGE"} for event in effects)


def test_repeated_missiles_get_distinct_hit_batches(effect_game):
    app, human, _opponent = effect_game
    _start_main(app)
    _prepare_hand(human)
    missiles = human.give("CFM_623")

    response = _play(app, app.snapshot(), missiles.entity_id)
    damage = [event for event in _events(response) if event["type"] == "DAMAGE"]

    assert len(damage) == 3
    assert all(isinstance(event.get("batch_id"), int) for event in damage)
    assert len({event["batch_id"] for event in damage}) == 3


def test_same_pair_extra_hit_keeps_combat_provenance():
    human = SimpleNamespace(name="Human")
    opponent = SimpleNamespace(name="Opponent")
    human.opponent = opponent
    source = SimpleNamespace(entity_id=10, controller=human)
    target = SimpleNamespace(entity_id=11, controller=opponent)

    class Session:
        def observation(self, player):
            del player
            return {
                "self": {"board": [{"entity_id": 10, "name": "Source", "card_id": "PUBLIC"}]},
                "opponent": {"board": [{"entity_id": 11, "name": "Target", "card_id": "PUBLIC"}]},
            }

    class Hit:
        trigger_index = 0

        def __init__(self, combat_damage=False):
            self.combat_damage = combat_damage

    class Damage:
        pass

    timeline = EffectTimeline(Session(), human)
    timeline.begin(human)
    timeline.action_start("ATTACK", source, 0, target)
    timeline.targeted_action(Hit(True), source, target, 1)
    timeline.targeted_action(Damage(), source, target, 1)
    timeline.targeted_action(Hit(False), source, target, 2)
    timeline.targeted_action(Damage(), source, target, 2)
    timeline.action_end("ATTACK", source)

    damage = [record["event"] for record in timeline.end()
              if record["event"]["type"] == "DAMAGE"]
    assert damage[0]["combat_damage"] is True
    assert "combat_damage" not in damage[1]


def test_reused_hit_listener_gets_new_batch_per_trigger_block():
    human = SimpleNamespace(name="Human")
    opponent = SimpleNamespace(name="Opponent")
    human.opponent = opponent
    source = SimpleNamespace(entity_id=10, controller=human)
    first = SimpleNamespace(entity_id=11, controller=opponent)
    second = SimpleNamespace(entity_id=12, controller=opponent)

    class Session:
        def observation(self, player):
            del player
            return {
                "self": {
                    "board": [{"entity_id": 10, "name": "Source", "card_id": "PUBLIC"}]
                },
                "opponent": {
                    "board": [
                        {"entity_id": 11, "name": "First", "card_id": "PUBLIC"},
                        {"entity_id": 12, "name": "Second", "card_id": "PUBLIC"},
                    ]
                },
            }

    class Hit:
        trigger_index = 0

    class Damage:
        pass

    timeline = EffectTimeline(Session(), human)
    timeline.begin(human)
    hit = Hit()
    timeline.action_start("TRIGGER", source, 0, None)
    timeline.targeted_action(hit, source, first, 1)
    timeline.targeted_action(Damage(), source, first, 1)
    timeline.targeted_action(hit, source, second, 1)
    timeline.targeted_action(Damage(), source, second, 1)
    timeline.action_end("TRIGGER", source)

    # The same Hit listener is invoked again after its trigger_index resets.
    # It must retain one batch for the first AOE and receive a fresh batch for
    # the second trigger block.
    timeline.action_start("TRIGGER", source, 0, None)
    timeline.targeted_action(hit, source, first, 1)
    timeline.targeted_action(Damage(), source, first, 1)
    timeline.action_end("TRIGGER", source)

    damage = [
        record["event"] for record in timeline.end()
        if record["event"]["type"] == "DAMAGE"
    ]
    assert damage[0]["batch_id"] == damage[1]["batch_id"]
    assert damage[2]["batch_id"] != damage[0]["batch_id"]


def test_death_batch_ids_follow_actual_death_actions():
    human = SimpleNamespace(name="Human")
    opponent = SimpleNamespace(name="Opponent")
    human.opponent = opponent
    first = SimpleNamespace(entity_id=11, controller=opponent)
    second = SimpleNamespace(entity_id=12, controller=opponent)

    class Session:
        def observation(self, player):
            del player
            return {
                "opponent": {
                    "board": [
                        {"entity_id": 11, "name": "First", "card_id": "PUBLIC"},
                        {"entity_id": 12, "name": "Second", "card_id": "PUBLIC"},
                    ]
                }
            }

    class Death:
        pass

    class DeathView:
        def __init__(self, original):
            self._match_original = original

    timeline = EffectTimeline(Session(), human)
    timeline.begin(human)
    first_action = Death()
    first_action._death_match_targets = {first.entity_id: DeathView(first)}
    second_action = Death()
    second_action._death_match_targets = {second.entity_id: DeathView(second)}
    timeline.game_action(first_action, None)
    timeline.game_action(first_action, None)
    timeline.game_action(second_action, None)

    deaths = [
        record["event"] for record in timeline.end()
        if record["event"]["type"] == "DEATH"
    ]
    assert len(deaths) == 2
    assert deaths[0]["batch_id"] != deaths[1]["batch_id"]


def test_private_sources_are_omitted_and_records_reset_and_detach():
    human = SimpleNamespace(name="Human")
    opponent = SimpleNamespace(name="Opponent")
    human.opponent = opponent
    target = SimpleNamespace(entity_id=2, controller=opponent)
    hidden_source = SimpleNamespace(entity_id=99, controller=opponent)

    class Session:
        def observation(self, player):
            del player
            return {
                "self": {"hero": {"entity_id": 1, "name": "Hero", "card_id": "PUBLIC"}},
                "opponent": {"board": [{"entity_id": 2, "name": "Target", "card_id": "PUBLIC"}]},
            }

    timeline = EffectTimeline(Session(), human)
    timeline.begin(opponent)

    class Damage:
        pass

    timeline.targeted_action(Damage(), hidden_source, target, 0)
    first = timeline.end()
    assert first[0]["event"]["actor"] == "opponent"
    assert "shield_broken" not in first[0]["event"]
    assert "source_entity_id" not in first[0]["event"]
    assert "source_name" not in first[0]["event"]
    assert first[0]["observation"]["opponent"]["board"][0]["name"] == "Target"

    timeline.begin(human)
    assert timeline.end() == []

    class Manager:
        def __init__(self):
            self.observers = []

        def register(self, observer):
            self.observers.append(observer)

    manager = Manager()
    session = SimpleNamespace(game=SimpleNamespace(manager=manager), observation=lambda player: {})
    registered = EffectTimeline(session, human)
    registered.register()
    assert registered in manager.observers
    registered.unregister()
    assert registered not in manager.observers


def test_webgame_close_detaches_effect_observer(effect_game):
    app, _human, _opponent = effect_game
    observer = app._effect_timeline
    assert observer in app.session.game.manager.observers
    app.close()
    assert observer not in app.session.game.manager.observers
