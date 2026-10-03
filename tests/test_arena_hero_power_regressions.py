"""Focused Arena coverage for no-target hero power availability and turn reset."""

from fireplace import cards
from fireplace.agent_api import Action
from fireplace.controller import GameSession, decision_player
from fireplace.search_simulation import EngineSearchPosition
from fireplace.web_gui.arena_factory import build_arena_game


cards.db.initialize()


def _arena_druid_main(seed=90421):
    game, human, opponent = build_arena_game(
        seed=seed,
        nickname="Arena Druid",
        hero_id="HERO_06",
        deck=["CS2_231"] * 30,
        selected_sets=("GVG", "TGT", "OG", "GANGS", "UNGORO", "NAXX"),
    )
    session = GameSession(game, {})
    session.start()
    for _ in range(2):
        session.execute(decision_player(game), Action(type="MULLIGAN"))
    while game.current_player is not human:
        session.execute(game.current_player, Action(type="END_TURN"))
    human.max_mana = 10
    human.used_mana = 1
    return session, human, opponent


def test_arena_druid_hero_power_is_legal_at_nine_remaining_mana_and_refreshes():
    session, human, opponent = _arena_druid_main()
    try:
        power = human.hero.power
        assert power.id == "HERO_06bp"
        assert (human.mana, human.max_mana, power.cost) == (9, 10, 2)
        assert power.is_usable()

        action = next(
            action for action in session.legal_actions(human)
            if action.type == "USE_HERO_POWER"
        )
        assert action.target_entity_id is None

        branch = EngineSearchPosition.from_game(session.game, human, seed=41)
        simulated = branch.transition(action)
        assert simulated.observation()["self"]["mana"] == 7
        assert not simulated.observation()["self"]["hero_power"]["is_usable"]
        # Search transitions must not spend mana or activate the live power.
        assert human.mana == 9
        assert power.activations_this_turn == 0
        assert power.is_usable()

        mana_before = human.mana
        attack_before = human.hero.atk
        armor_before = human.hero.armor
        session.execute(human, action)
        assert human.mana == mana_before - 2
        assert human.hero.atk == attack_before + 1
        assert human.hero.armor == armor_before + 1
        assert power.activations_this_turn == 1
        assert power.exhausted and not power.is_usable()
        assert not any(
            action.type == "USE_HERO_POWER"
            for action in session.legal_actions(human)
        )

        session.execute(human, Action(type="END_TURN"))
        session.execute(opponent, Action(type="END_TURN"))
        assert session.game.current_player is human
        assert power.activations_this_turn == 0
        assert not power.exhausted and power.is_usable()
        assert any(
            action.type == "USE_HERO_POWER"
            for action in session.legal_actions(human)
        )
    finally:
        session.close()


def test_search_copy_removing_mindbreaker_does_not_change_live_hero_power_aura():
    session, human, opponent = _arena_druid_main(seed=90422)
    try:
        mindbreaker = opponent.summon("ICC_902")
        fireball = human.give("CS2_029")
        power = human.hero.power
        assert power.heropower_disabled
        assert power.exhausted and not power.is_usable()

        position = EngineSearchPosition.from_game(session.game, human, seed=42)
        action = next(
            action for action in position.legal_actions()
            if action.type == "PLAY_CARD"
            and action.source_entity_id == fireball.entity_id
            and action.target_entity_id == mindbreaker.entity_id
        )
        simulated = position.transition(action)
        assert simulated.observation()["self"]["hero_power"]["is_usable"]
        assert any(
            action.type == "USE_HERO_POWER"
            for action in simulated.legal_actions()
        )

        # Destroying the aura in a speculative branch leaves the live game intact.
        assert mindbreaker in opponent.field
        assert human.mana == 9
        assert power.heropower_disabled
        assert power.exhausted and not power.is_usable()
        assert not any(
            action.type == "USE_HERO_POWER"
            for action in session.legal_actions(human)
        )
    finally:
        session.close()
