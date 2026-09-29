"""Card-specific retests for cards affected by the simultaneous-death fix.

Every parameterized node is tied to one collectible card ID so current audit
records can cite an independent pytest result for that card.
"""

import random

import pytest
from hearthstone.enums import CardClass, Zone

from fireplace.actions import Bounce
from fireplace.exceptions import InvalidAction
from utils import MOONFIRE, WISP, prepare_empty_game


def empty_game(class1=CardClass.MAGE, class2=CardClass.MAGE):
    game = prepare_empty_game(class1, class2)
    for player in game.players:
        player.discard_hand()
        player.max_mana = 10
        player.used_mana = 0
    if game.current_player is not game.player1:
        game.end_turn()
    return game, game.player1, game.player2


def make_buff_death_board(card_id):
    """A source and 1-health ally die together; a Yeti survives Whirlwind."""
    game, player, opponent = empty_game()
    source = player.summon(card_id)
    source.set_current_health(1)
    doomed_ally = player.summon(WISP)
    doomed_ally.set_current_health(1)
    survivor = player.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    return game, player, opponent, source, doomed_ally, survivor, enemy


@pytest.mark.parametrize(
    "card_id,effect",
    [
        ("OG_256", "all_plus_one"),
        ("LOE_061", "random_plus_three_both"),
        ("FP1_023", "random_three_health"),
        ("OG_158", "random_plus_one"),
        ("UNG_037", "random_plus_one"),
        ("GIL_608", "random_two_health"),
        ("DAL_563", "two_random_plus_two"),
        ("ULD_266", "random_plus_one_reborn"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_same_batch_deathrattle_affects_eligible_survivors_only(card_id, effect):
    game, player, opponent, source, doomed_ally, survivor, enemy = make_buff_death_board(
        card_id
    )

    if effect == "two_random_plus_two":
        second_survivor = player.summon("CS2_182")
        pre_attack = survivor.atk + second_survivor.atk
        pre_max_health = survivor.max_health + second_survivor.max_health
        pre_health = survivor.health + second_survivor.health
    else:
        second_survivor = None
        pre_attack = survivor.atk
        pre_max_health = survivor.max_health
        pre_health = survivor.health
    enemy_before = (enemy.atk, enemy.max_health, enemy.health)

    game.random.seed(701)
    player.give("EX1_400").play()

    assert source.zone == Zone.GRAVEYARD
    assert doomed_ally.zone == Zone.GRAVEYARD
    assert survivor.zone == Zone.PLAY
    assert (survivor.atk, survivor.max_health, survivor.health) != (
        0,
        0,
        0,
    )
    # Whirlwind itself removes one current Health from survivors before the
    # deathrattle buff resolves.
    if effect == "all_plus_one":
        assert (survivor.atk, survivor.max_health, survivor.health) == (
            pre_attack + 1,
            pre_max_health + 1,
            pre_health,
        )
    elif effect == "random_plus_three_both":
        assert survivor.atk == pre_attack + 3
        assert survivor.max_health == pre_max_health + 3
        assert survivor.health == pre_health + 2
    elif effect == "random_three_health":
        assert survivor.atk == pre_attack
        assert survivor.max_health == pre_max_health + 3
        assert survivor.health == pre_health + 2
    elif effect == "random_plus_one":
        assert (survivor.atk, survivor.max_health, survivor.health) == (
            pre_attack + 1,
            pre_max_health + 1,
            pre_health,
        )
    elif effect == "random_two_health":
        assert survivor.atk == pre_attack
        assert survivor.max_health == pre_max_health + 2
        assert survivor.health == pre_health + 1
    elif effect == "two_random_plus_two":
        assert second_survivor.zone == Zone.PLAY
        assert survivor.atk + second_survivor.atk == pre_attack + 4
        assert survivor.max_health + second_survivor.max_health == pre_max_health + 4
        assert survivor.health + second_survivor.health == pre_health + 2
    elif effect == "random_plus_one_reborn":
        assert (survivor.atk, survivor.max_health, survivor.health) == (
            pre_attack + 1,
            pre_max_health + 1,
            pre_health,
        )
        reborn_copies = [card for card in player.field if card.id == card_id]
        assert len(reborn_copies) == 1
        assert (reborn_copies[0].atk, reborn_copies[0].health) == (1, 1)
        assert not reborn_copies[0].reborn
    else:  # pragma: no cover - guards future matrix edits
        pytest.fail(f"unhandled expected effect {effect}")

    assert (enemy.atk, enemy.max_health, enemy.health) == (
        enemy_before[0],
        enemy_before[1],
        enemy_before[2] - 1,
    )


@pytest.mark.parametrize(
    "card_id,expected_delta",
    [
        ("LOE_061", (3, 3, 3)),
        ("FP1_023", (0, 3, 3)),
        ("OG_158", (1, 1, 1)),
        ("UNG_037", (1, 1, 1)),
        ("GIL_608", (0, 2, 2)),
        ("ULD_266", (1, 1, 1)),
    ],
    ids=["LOE_061", "FP1_023", "OG_158", "UNG_037", "GIL_608", "ULD_266"],
)
def test_random_deathrattle_selects_only_eligible_friendly_targets(
    card_id, expected_delta
):
    seen_targets = set()
    candidate_ids = (WISP, "CS2_182", "CS2_200")

    for seed in range(24):
        game, player, opponent = empty_game()
        source = player.summon(card_id)
        candidates = [player.summon(candidate_id) for candidate_id in candidate_ids]
        enemy = opponent.summon("CS2_182")
        before = {
            candidate.entity_id: (candidate.atk, candidate.max_health, candidate.health)
            for candidate in candidates
        }
        enemy_before = (enemy.atk, enemy.max_health, enemy.health)
        game.random.seed(seed)

        source.destroy()

        assert source.zone == Zone.GRAVEYARD
        changed = []
        for candidate in candidates:
            signature = (candidate.atk, candidate.max_health, candidate.health)
            delta = tuple(
                after - prior
                for after, prior in zip(signature, before[candidate.entity_id])
            )
            if delta == expected_delta:
                changed.append(candidate)
            else:
                assert delta == (0, 0, 0)
            assert candidate.zone == Zone.PLAY
        assert len(changed) == 1
        assert (enemy.atk, enemy.max_health, enemy.health) == enemy_before
        seen_targets.add(changed[0].id)

        if card_id == "ULD_266":
            reborn_copies = [card for card in player.field if card.id == card_id]
            assert len(reborn_copies) == 1
            assert (reborn_copies[0].atk, reborn_copies[0].health) == (1, 1)
            assert not reborn_copies[0].reborn

    assert seen_targets == set(candidate_ids)


def test_dal_563_picks_two_distinct_legal_minions():
    seen_pairs = set()
    candidate_ids = (WISP, "CS2_182", "CS2_200")

    for seed in range(24):
        game, player, opponent = empty_game()
        source = player.summon("DAL_563")
        candidates = [player.summon(candidate_id) for candidate_id in candidate_ids]
        enemy = opponent.summon("CS2_182")
        before = {
            candidate.entity_id: (candidate.atk, candidate.max_health, candidate.health)
            for candidate in candidates
        }
        enemy_before = (enemy.atk, enemy.max_health, enemy.health)
        game.random.seed(seed)

        source.destroy()

        assert source.zone == Zone.GRAVEYARD
        chosen = set()
        for candidate in candidates:
            signature = (candidate.atk, candidate.max_health, candidate.health)
            delta = tuple(
                after - prior
                for after, prior in zip(signature, before[candidate.entity_id])
            )
            if delta == (2, 2, 2):
                chosen.add(candidate.id)
            else:
                assert delta == (0, 0, 0)
            assert candidate.zone == Zone.PLAY
        assert len(chosen) == 2
        assert (enemy.atk, enemy.max_health, enemy.health) == enemy_before
        seen_pairs.add(frozenset(chosen))

    assert seen_pairs == {
        frozenset((WISP, "CS2_182")),
        frozenset((WISP, "CS2_200")),
        frozenset(("CS2_182", "CS2_200")),
    }


def test_ung_037_taunt_blocks_hero_attack():
    game, player, opponent = empty_game()
    shellraiser = player.summon("UNG_037")
    attacker = opponent.summon("CS2_171")
    hero_health = player.hero.health
    shellraiser_health = shellraiser.health

    game.end_turn()

    assert shellraiser.taunt
    assert attacker.can_attack(shellraiser)
    assert not attacker.can_attack(player.hero)
    attacker.attack(shellraiser)
    assert player.hero.health == hero_health
    assert shellraiser.health == shellraiser_health - attacker.atk
    assert shellraiser.taunt


def test_gil_608_stealth_hides_it_from_enemy_attack_and_targeted_spell():
    game, player, opponent = empty_game()
    imp = player.summon("GIL_608")
    attacker = opponent.summon("CS2_171")
    hero_health = player.hero.health

    game.end_turn()

    assert imp.stealthed
    assert attacker.can_attack(player.hero)
    assert not attacker.can_attack(imp)
    with pytest.raises(InvalidAction):
        opponent.give(MOONFIRE).play(target=imp)

    attacker.attack(player.hero)
    assert imp.zone == Zone.PLAY
    assert imp.stealthed
    assert player.hero.health == hero_health - attacker.atk

    game.end_turn()
    assert game.current_player is player
    assert imp.can_attack(opponent.hero)
    imp.attack(opponent.hero)
    assert not imp.stealthed


def test_uld_266_reborn_tag_is_consumed_after_one_return():
    _, player, _ = empty_game()
    original = player.summon("ULD_266")
    original.destroy()

    assert original.zone == Zone.GRAVEYARD
    copies = [card for card in player.field if card.id == "ULD_266"]
    assert len(copies) == 1
    reborn_copy = copies[0]
    assert (reborn_copy.atk, reborn_copy.health) == (1, 1)
    assert not reborn_copy.reborn

    reborn_copy.destroy()

    assert reborn_copy.zone == Zone.GRAVEYARD
    assert not [card for card in player.field if card.id == "ULD_266"]


def test_fp1_026_random_return_and_no_target_boundary():
    returned_ids = set()
    for seed in range(16):
        game, player, opponent = empty_game()
        source = player.summon("FP1_026")
        candidates = [player.summon(WISP), player.summon("CS2_182")]
        enemy = opponent.summon(WISP)
        game.random.seed(seed)

        source.destroy()

        assert source.zone == Zone.GRAVEYARD
        returned = [card for card in candidates if card.zone == Zone.HAND]
        assert len(returned) == 1
        assert all(card.zone in {Zone.HAND, Zone.PLAY} for card in candidates)
        assert enemy.zone == Zone.PLAY
        returned_ids.add(returned[0].id)
    assert returned_ids == {WISP, "CS2_182"}

    _, player, _ = empty_game()
    only_source = player.summon("FP1_026")
    only_source.destroy()
    assert only_source.zone == Zone.GRAVEYARD
    assert len(player.hand) == 0
    assert len(player.field) == 0


def test_fp1_026_does_not_bounce_ally_dying_in_same_batch(monkeypatch):
    game, player, opponent = empty_game()
    source = player.summon("FP1_026")
    source.set_current_health(1)
    ally = player.summon(WISP)
    ally.set_current_health(1)
    enemy = opponent.summon("CS2_182")

    bounces = []
    original_targeted_action = game.manager.targeted_action

    def record_bounce(action, action_source, target, *args):
        if isinstance(action, Bounce):
            bounces.append(target)
        return original_targeted_action(action, action_source, target, *args)

    monkeypatch.setattr(game.manager, "targeted_action", record_bounce)
    player.give("EX1_400").play()

    assert source.zone == Zone.GRAVEYARD
    assert ally.zone == Zone.GRAVEYARD
    assert ally not in player.hand
    assert ally not in bounces
    assert enemy.zone == Zone.PLAY


def test_ex1_407_brawl_keeps_exactly_one_random_minion():
    survivors_seen = set()
    for seed in range(32):
        game, player, opponent = empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
        candidates = [
            player.summon("CS2_182"),
            player.summon("EX1_105"),
            opponent.summon("CS2_200"),
        ]
        game.random.seed(seed)

        player.give("EX1_407").play()

        survivors = [card for card in candidates if card.zone == Zone.PLAY]
        assert len(survivors) == 1
        assert all(
            card.zone in {Zone.PLAY, Zone.GRAVEYARD} for card in candidates
        )
        survivors_seen.add(survivors[0].id)
    assert survivors_seen == {"CS2_182", "EX1_105", "CS2_200"}


def test_ex1_407_brawl_does_not_rescue_ally_destroyed_in_same_resolution():
    found_enemy_survivor = False
    for seed in range(64):
        game, player, opponent = empty_game(CardClass.WARRIOR, CardClass.WARRIOR)
        ambusher = player.summon("FP1_026")
        ally = player.summon(WISP)
        enemy = opponent.summon("CS2_200")
        game.random.seed(seed)

        player.give("EX1_407").play()

        if enemy.zone == Zone.PLAY:
            found_enemy_survivor = True
            assert ambusher.zone == Zone.GRAVEYARD
            assert ally.zone == Zone.GRAVEYARD
            assert ally not in player.hand
            break
    assert found_enemy_survivor


def test_icc_047_growth_branch_and_same_batch_deaths():
    game, player, opponent = empty_game(CardClass.DRUID, CardClass.WARRIOR)
    player.give("ICC_047").play(choose="ICC_047a")
    source = next(card for card in player.field if card.id == "ICC_047t")
    own = player.summon("CS2_182")
    enemy = opponent.summon("CS2_182")
    source.destroy()

    assert source.zone == Zone.GRAVEYARD
    assert (own.atk, own.health) == (6, 7)
    assert (enemy.atk, enemy.health) == (6, 7)

    game, player, _ = empty_game(CardClass.DRUID, CardClass.WARRIOR)
    player.give("ICC_047").play(choose="ICC_047a")
    source = next(card for card in player.field if card.id == "ICC_047t")
    source.set_current_health(1)
    wisp = player.summon(WISP)
    wisp.set_current_health(1)

    player.give("ICC_064").play()

    assert source.zone == Zone.GRAVEYARD
    assert wisp.zone == Zone.GRAVEYARD
    assert wisp not in player.field


def test_icc_047_decay_branch_damages_both_sides():
    _, player, opponent = empty_game(CardClass.DRUID, CardClass.WARRIOR)
    player.give("ICC_047").play(choose="ICC_047b")
    source = next(card for card in player.field if card.id == "ICC_047t")
    own = player.summon("CS2_182")
    enemy = opponent.summon("CS2_182")

    source.destroy()

    assert source.zone == Zone.GRAVEYARD
    assert own.zone == enemy.zone == Zone.PLAY
    assert own.health == enemy.health == 2
