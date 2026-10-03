"""Public resource and residual ability values for the tactical policy."""

from copy import deepcopy

import pytest

from fireplace.agent_api import Action
from fireplace.search_scoring import LETHAL_SCORE, score_observation, score_tactical_observation


def board():
    return {"self": {"hero": {"health": 30}, "hand": [], "hand_count": 0,
                     "board": [{"atk": 3, "health": 4}], "mana": 0},
            "opponent": {"hero": {"health": 30}, "board": [], "hand_count": 0}}


def test_legacy_numeric_score_remains_exact():
    view = board()
    assert score_observation(view) == 30.0
    view["self"]["board"][0]["has_deathrattle"] = True
    assert score_observation(view) == 30.0


@pytest.mark.parametrize("keyword", ["has_deathrattle", "reborn", "divine_shield", "poisonous", "windfury"])
def test_public_residual_abilities_increase_tactical_value(keyword):
    view = board()
    baseline = score_tactical_observation(view)
    view["self"]["board"][0][keyword] = True
    assert score_tactical_observation(view) > baseline


def test_silence_removes_residual_deathrattle_value():
    view = board()
    view["self"]["board"][0]["has_deathrattle"] = True
    before = score_tactical_observation(view)
    view["self"]["board"][0]["silenced"] = True
    assert score_tactical_observation(view) < before


def test_frozen_and_dormant_minions_have_less_immediate_value():
    view = board()
    baseline = score_tactical_observation(view)
    view["self"]["board"][0]["frozen"] = True
    assert score_tactical_observation(view) < baseline
    view["self"]["board"][0] = {"atk": 3, "health": 4, "dormant": True}
    assert score_tactical_observation(view) < baseline


def test_unknown_draw_has_resource_value_without_fabricated_card_power():
    before = board()
    after = deepcopy(before)
    after["self"]["hand"] = [{"unknown": True, "card_id": None, "cost": None}]
    after["self"]["hand_count"] = 1
    assert score_tactical_observation(after) - score_tactical_observation(before) == pytest.approx(2.55)
    after["self"]["hand"][0]["cost"] = 10
    assert score_tactical_observation(after) - score_tactical_observation(before) == pytest.approx(2.55)


def test_public_opponent_hand_count_has_matching_resource_value():
    view = board()
    baseline = score_tactical_observation(view)
    view["opponent"]["hand_count"] = 1
    assert score_tactical_observation(view) - baseline == pytest.approx(-2.55)


def test_scalar_and_terminal_scores_are_authoritative():
    view = board()
    view["score"] = 17
    assert score_tactical_observation(view) == 17
    view["search_outcome"] = "win"
    assert score_tactical_observation(view) >= LETHAL_SCORE
    view["search_outcome"] = "draw"
    assert score_tactical_observation(view) == 0
    view.pop("search_outcome")
    view["opponent"]["hero"]["health"] = 0
    assert score_tactical_observation(view) >= LETHAL_SCORE


class Reply:
    def __init__(self, *, terminal=False, uncertain=False, fail=False):
        self.terminal = terminal
        self.uncertain = uncertain
        self.fail = fail

    def observation(self):
        view = board()
        view["search_uncertain"] = self.uncertain
        return view

    def legal_actions(self):
        return [Action(type="ATTACK", source_entity_id=2, target_entity_id=1)]

    def transition(self, action, *, seed=None):
        if self.fail:
            raise RuntimeError("unsupported branch")
        return Reply(terminal=True, uncertain=True)


def test_reply_diagnostics_propagate_random_branch_uncertainty():
    diagnostics = {}
    score_tactical_observation(board(), reply_position=Reply(), diagnostics=diagnostics)
    assert diagnostics["uncertain"]
    assert diagnostics["completed_leaves"] > 0


def test_reply_diagnostics_make_failure_and_deadline_explicit():
    diagnostics = {}
    score_tactical_observation(board(), reply_position=Reply(fail=True), diagnostics=diagnostics)
    assert diagnostics["status"] == "partial"
    assert diagnostics["failed_lines"] == 1
    score_tactical_observation(board(), reply_position=Reply(), deadline=1,
                               clock=lambda: 2, diagnostics=diagnostics)
    assert diagnostics["status"] == "partial"
    assert diagnostics["truncated_lines"] == 1
    score_tactical_observation(board(), reply_position=Reply(), max_reply_depth=0,
                               diagnostics=diagnostics)
    assert diagnostics["status"] == "partial"
    assert diagnostics["truncated_lines"] == 1
