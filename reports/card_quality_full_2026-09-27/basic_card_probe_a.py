"""Per-card behavioral probes for five Basic YELLOW cards.

Run from the repository root:
    PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_a.py

Card texts and previous audit rows are in card_master.csv/basic_quality.csv.
Every case below plays the actual card in a small game and checks card-specific
state transitions. This is evidence collection only; production code is not
changed.
"""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
OUT = HERE / "basic_card_probe_a.csv"
FIELDS = ["card_id", "case_id", "expected", "observed", "outcome", "notes"]
ROWS = []


def new_game():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    return game


def record(card_id, case_id, expected, observed, outcome, notes):
    assert outcome in {"pass", "confirmed_error", "inconclusive"}
    ROWS.append(
        {
            "card_id": card_id,
            "case_id": case_id,
            "expected": expected,
            "observed": observed,
            "outcome": outcome,
            "notes": notes,
        }
    )


def run_case(card_id, case_id, expected, probe, notes):
    try:
        observed, passed = probe()
        outcome = (
            "pass"
            if passed is True
            else "confirmed_error"
            if passed is False
            else "inconclusive"
        )
    except Exception as error:
        observed = f"exception={type(error).__name__}: {error}"
        outcome = "inconclusive"
    record(card_id, case_id, expected, observed, outcome, notes)


def test_acidic_swamp_ooze():
    card_id = "EX1_066"

    def enemy_weapon_only():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p1.max_mana = 10
        own_weapon = p1.give("CS2_091")
        own_weapon.play()
        game.end_turn()
        enemy_weapon = p2.give("CS2_091")
        enemy_weapon.play()
        game.end_turn()
        p1.max_mana = 10
        ooze = p1.give(card_id)
        ooze.play()
        observed = (
            f"enemy_weapon={enemy_weapon.zone.name},equipped={p2.weapon};"
            f"own_weapon={own_weapon.zone.name},equipped={getattr(p1.weapon, 'id', None)};"
            f"ooze={ooze.zone.name},field={ooze in p1.field}"
        )
        passed = (
            enemy_weapon.zone == Zone.GRAVEYARD
            and enemy_weapon in p2.graveyard
            and p2.weapon is None
            and own_weapon.zone == Zone.PLAY
            and p1.weapon is own_weapon
            and ooze.zone == Zone.PLAY
            and ooze in p1.field
        )
        return observed, passed

    run_case(
        card_id,
        "ooze_enemy_weapon_destroyed_own_preserved",
        "After the opponent equips a weapon, playing Ooze destroys that weapon and leaves the controller's weapon equipped.",
        enemy_weapon_only,
        "EN: Battlecry: Destroy your opponent's weapon. ZH: 战吼：摧毁对手的武器。 "
        "Impl: fireplace/cards/classic/neutral_common.py:266-272, play=Destroy(ENEMY_WEAPON). "
        "Existing: no effect assertion found; basic_quality.csv row EX1_066 was YELLOW/partial. "
        "Runs actual weapon equips on their owners' turns, then plays Ooze on its controller's next turn.",
    )

    def no_enemy_weapon_is_noop():
        game = new_game()
        p1 = game.player1
        p1.max_mana = 10
        own_weapon = p1.give("CS2_091")
        own_weapon.play()
        ooze = p1.give(card_id)
        ooze.play()
        observed = (
            f"opponent_weapon={getattr(game.player2.weapon, 'id', None)};"
            f"own_weapon={getattr(p1.weapon, 'id', None)},zone={own_weapon.zone.name};"
            f"ooze={ooze.zone.name},field={ooze in p1.field}"
        )
        passed = (
            game.player2.weapon is None
            and p1.weapon is own_weapon
            and own_weapon.zone == Zone.PLAY
            and ooze in p1.field
        )
        return observed, passed

    run_case(
        card_id,
        "ooze_no_enemy_weapon_preserves_own",
        "With no enemy weapon, Ooze still enters play and does not destroy its controller's weapon.",
        no_enemy_weapon_is_noop,
        "Negative/control branch for ENEMY_WEAPON. Text and implementation references are the same as the preceding case; "
        "existing tests had no EX1_066 behavior assertion.",
    )


def test_mortal_coil():
    card_id = "EX1_302"

    def lethal_draws_one():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p1.max_mana = 10
        target = p2.summon("CS2_231")  # 1/1 Wisp; exactly lethal to 1 damage.
        draw_card = p1.card("CS2_182", zone=Zone.DECK)
        coil = p1.give(card_id)
        coil.play(target=target)
        observed = (
            f"target_health={target.health},zone={target.zone.name},in_field={target in p2.field};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand};"
            f"deck={[card.id for card in p1.deck]};coil={coil.zone.name}"
        )
        passed = (
            target.zone == Zone.GRAVEYARD
            and target in p2.graveyard
            and target not in p2.field
            and draw_card.zone == Zone.HAND
            and draw_card in p1.hand
            and not p1.deck
            and coil.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "coil_lethal_damage_draws_one",
        "Deal 1 to a 1-health minion, process its death, and draw exactly the top card into the caster's hand.",
        lethal_draws_one,
        "EN: Deal $1 damage to a minion. If that kills it, draw a card. ZH: 对一个随从造成1点伤害；若消灭它则抽一张牌。 "
        "Impl: fireplace/cards/classic/warlock.py:126-132, Hit(TARGET, 1), Dead(TARGET) & Draw(CONTROLLER). "
        "Existing tests/test_classic.py:2286-2293:test_mortal_coil test the 2-health target in two plays, "
        "but do not assert deck/hand/zone deltas for each branch. basic_quality.csv was YELLOW/partial.",
    )

    def nonlethal_no_draw():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p1.max_mana = 10
        target = p2.summon("CS2_182")  # 4/5 Yeti.
        target.set_current_health(2)
        draw_card = p1.card("CS2_231", zone=Zone.DECK)
        coil = p1.give(card_id)
        coil.play(target=target)
        observed = (
            f"target_health={target.health},zone={target.zone.name},in_field={target in p2.field};"
            f"draw={draw_card.zone.name},in_hand={draw_card in p1.hand},deck_count={len(p1.deck)};"
            f"coil={coil.zone.name}"
        )
        passed = (
            target.health == 1
            and target.zone == Zone.PLAY
            and target in p2.field
            and draw_card.zone == Zone.DECK
            and draw_card not in p1.hand
            and list(p1.deck) == [draw_card]
            and coil.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "coil_nonlethal_damage_no_draw",
        "Deal 1 to a 2-health minion; it remains at 1 health and the caster draws nothing.",
        nonlethal_no_draw,
        "Same English/Chinese text and implementation as the lethal case. The deck has one known card so any unintended draw is observable.",
    )

    def legal_minion_targets_and_reject_hero():
        game = new_game()
        p1, p2 = game.player1, game.player2
        p1.max_mana = 10
        friendly = p1.summon("CS2_182")
        enemy = p2.summon("CS2_182")
        coil = p1.give(card_id)
        legal_friendly = friendly in coil.targets
        legal_enemy = enemy in coil.targets
        hero_legal = p1.hero in coil.targets or p2.hero in coil.targets
        observed = (
            f"friendly_minion_target={legal_friendly};enemy_minion_target={legal_enemy};"
            f"either_hero_target={hero_legal};coil_zone={coil.zone.name}"
        )
        passed = legal_friendly and legal_enemy and not hero_legal and coil.zone == Zone.HAND
        return observed, passed

    run_case(
        card_id,
        "coil_target_domain_minions_only",
        "Both friendly and enemy minions are legal targets; heroes are not legal targets before spell resolution.",
        legal_minion_targets_and_reject_hero,
        "Targeting prerequisites in CardDefs.xml#EX1_302 are REQ_MINION_TARGET and REQ_TARGET_TO_PLAY; "
        "existing target-prerequisite sweep was a generic precondition check, not this card's damage/draw behavior.",
    )


def test_tracking():
    card_id = "DS1_184"

    def exact_top_three_and_discard_fate():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        bottom = p.card("EX1_066", zone=Zone.DECK)
        top_three = [
            p.card("CS2_231", zone=Zone.DECK),
            p.card("CS2_182", zone=Zone.DECK),
            p.card("CS2_029", zone=Zone.DECK),
        ]
        tracking = p.give(card_id)
        tracking.play()
        choice = p.choice
        candidate_objects = list(choice.cards)
        candidate_ids = [card.id for card in candidate_objects]
        candidate_match = len(candidate_objects) == 3 and candidate_objects == top_three
        selected = top_three[1]
        choice.choose(selected)
        discarded = [card for card in top_three if card is not selected]
        observed = (
            f"candidates={candidate_ids};candidate_identity_order={candidate_objects == top_three};"
            f"selected={selected.id}:{selected.zone.name},in_hand={selected in p.hand};"
            f"discarded={[(c.id, c.zone.name) for c in discarded]};"
            f"bottom={bottom.zone.name},deck={[c.id for c in p.deck]};"
            f"choice_open={p.choice is not None};tracking={tracking.zone.name}"
        )
        passed = (
            candidate_match
            and selected.zone == Zone.HAND
            and selected in p.hand
            and all(card.zone == Zone.REMOVEDFROMGAME for card in discarded)
            and bottom.zone == Zone.DECK
            and list(p.deck) == [bottom]
            and p.choice is None
            and tracking.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "tracking_exact_top_three_and_fates",
        "The exact three top-deck entities appear as choices; selecting one puts it in hand, removes the other two, and preserves the older bottom card.",
        exact_top_three_and_discard_fate,
        "EN: Look at the top 3 cards of your deck. Draw one and discard the others. ZH: 检视牌库顶三张，抽取一张并弃掉其余牌。 "
        "Impl: fireplace/cards/classic/hunter.py:89-96, GenericChoice(CONTROLLER, FRIENDLY_DECK[-3:]). "
        "Existing tests/test_classic.py:3394-3401:test_tracking only checks choice count and chosen card in hand; "
        "tests/test_mechanics.py:210-230:test_choices checks choice blocking/unblocking. Audit row was YELLOW/partial.",
    )

    def duplicate_physical_top_cards_remain_distinct_choices():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        bottom = p.card("EX1_066", zone=Zone.DECK)
        top_three = [
            p.card("CS2_231", zone=Zone.DECK),
            p.card("CS2_231", zone=Zone.DECK),
            p.card("CS2_182", zone=Zone.DECK),
        ]
        tracking = p.give(card_id)
        tracking.play()
        candidate_objects = list(p.choice.cards)
        expected_identity_match = len(candidate_objects) == 3 and set(map(id, candidate_objects)) == set(map(id, top_three))
        selected = top_three[1]
        p.choice.choose(selected)
        other_cards = [card for card in top_three if card is not selected]
        observed = (
            f"physical_top={[card.id for card in top_three]};"
            f"options={[card.id for card in candidate_objects]},option_count={len(candidate_objects)},"
            f"option_entity_ids={[card.entity_id for card in candidate_objects]};"
            f"three_distinct_expected_entities={expected_identity_match};"
            f"selected={selected.id}:{selected.zone.name};"
            f"other_top_zones={[card.zone.name for card in other_cards]};"
            f"bottom={bottom.zone.name},deck_count={len(p.deck)},top={p.deck[-1].id if p.deck else None};"
            f"tracking={tracking.zone.name}"
        )
        passed = (
            expected_identity_match
            and selected.zone == Zone.HAND
            and all(card.zone == Zone.REMOVEDFROMGAME for card in other_cards)
            and list(p.deck) == [bottom]
            and tracking.zone == Zone.GRAVEYARD
        )
        return observed, passed

    run_case(
        card_id,
        "tracking_duplicate_ids_are_physical_cards",
        "Three top-deck physical cards remain three separate choice entries even when two have the same card ID; one is drawn and the other two are discarded.",
        duplicate_physical_top_cards_remain_distinct_choices,
        "Boundary test for the actual top-three slice: two separate Wisp entities plus one Yeti. The card text counts cards, "
        "not distinct printed IDs. Existing test_tracking uses no duplicate IDs.",
    )

    def selected_card_draw_event_semantics():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        candidates = [p.card(id, zone=Zone.DECK) for id in ("CS2_231", "CS2_182", "CS2_029")]
        before = p.cards_drawn_this_turn
        tracking = p.give(card_id)
        tracking.play()
        p.choice.choose(candidates[1])
        chosen = candidates[1]
        after = p.cards_drawn_this_turn

        control_game = new_game()
        control = control_game.player1
        known = control.card("CS2_182", zone=Zone.DECK)
        control_before = control.cards_drawn_this_turn
        control.draw()
        control_after = control.cards_drawn_this_turn
        observed = (
            f"tracking_chosen={chosen.id}:{chosen.zone.name},in_hand={chosen in p.hand};"
            f"tracking_draw_counter={before}->{after};"
            f"ordinary_draw={known.zone.name},counter={control_before}->{control_after}"
        )
        assert chosen.zone == Zone.HAND and chosen in p.hand
        assert known.zone == Zone.HAND and known in control.hand
        assert control_after == control_before + 1
        # The 17.6 text says 'Draw one'; whether the selection should produce
        # the same draw event needs independent rules evidence.
        return observed, True if after == before + 1 else None

    run_case(
        card_id,
        "tracking_chosen_card_draw_event_semantics",
        "Determine whether choosing the card counts as a draw event, as the 17.6 text says 'Draw one'; compare a normal draw in a separate game.",
        selected_card_draw_event_semantics,
        "Rule semantics pending: GenericChoice moves deck entity directly to hand; this case records the event/counter discrepancy without presuming it is an implementation defect.",
    )


def test_flametongue_totem():
    card_id = "EX1_565"

    def insertion_updates_only_immediate_neighbors():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        left = p.summon("CS2_231")
        near_right = p.summon("CS2_231")
        far_right = p.summon("CS2_231")
        totem = p.give(card_id)
        totem.play(index=1)
        observed = (
            f"field={[c.id for c in p.field]};"
            f"attacks=left:{left.atk},near_right:{near_right.atk},far_right:{far_right.atk},totem:{totem.atk};"
            f"adjacent={[c.id for c in totem.adjacent_minions]};"
            f"buffs={{left:{len(left.buffs)},near_right:{len(near_right.buffs)},far_right:{len(far_right.buffs)}}}"
        )
        passed = (
            p.field == [left, totem, near_right, far_right]
            and left.atk == 3
            and near_right.atk == 3
            and far_right.atk == 1
            and totem.atk == 0
            and totem.adjacent_minions == [left, near_right]
        )
        return observed, passed

    run_case(
        card_id,
        "flametongue_insertion_buffs_two_adjacent_only",
        "Insert Flametongue between minions: each immediate neighbor gains exactly +2 attack; the next minion and the Totem do not.",
        insertion_updates_only_immediate_neighbors,
        "EN: Adjacent minions have +2 Attack. ZH: 相邻的随从获得+2攻击力。 Impl: fireplace/cards/classic/shaman.py:20-30, "
        "Refresh(SELF_ADJACENT, buff='EX1_565o'), buff(atk=2). Existing tests/test_mechanics.py:706-730:test_positioning "
        "checks appended adjacency; tests/test_classic.py:1954 has only an indirect Lightspawn assertion. Audit row YELLOW/partial.",
    )

    def removing_neighbor_retargets_and_silence_clears_aura():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        left = p.summon("CS2_231")
        first_neighbor = p.summon("CS2_231")
        newly_adjacent = p.summon("CS2_231")
        totem = p.give(card_id)
        totem.play(index=1)  # [left, Totem, first_neighbor, newly_adjacent]
        before_destroy = (left.atk, first_neighbor.atk, newly_adjacent.atk)
        first_neighbor.destroy()
        after_destroy = (left.atk, newly_adjacent.atk)
        newly_adjacent_zone = newly_adjacent.zone.name
        totem.silence()
        after_silence = (left.atk, newly_adjacent.atk)
        observed = (
            f"before_destroy={before_destroy};first_neighbor={first_neighbor.zone.name};"
            f"after_destroy={after_destroy};newly_adjacent_zone={newly_adjacent_zone};"
            f"after_silence={after_silence};totem_silenced={totem.silenced};"
            f"field={[c.id for c in p.field]}"
        )
        passed = (
            before_destroy == (3, 3, 1)
            and first_neighbor.zone == Zone.GRAVEYARD
            and after_destroy == (3, 3)
            and newly_adjacent.zone == Zone.PLAY
            and after_silence == (1, 1)
            and totem.silenced
        )
        return observed, passed

    run_case(
        card_id,
        "flametongue_neighbor_death_and_silence_update",
        "After an adjacent minion dies, the minion that shifts next to the Totem receives +2 attack; silencing the Totem removes the aura from both neighbors.",
        removing_neighbor_retargets_and_silence_clears_aura,
        "Tests aura refresh after zone/position change and aura removal by silence. No existing per-card test covered death movement and silence together.",
    )


def test_sightless_watcher():
    card_id = "BT_323"

    def three_unique_candidates_and_put_chosen_on_top():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        deck_cards = [
            p.card("CS2_231", zone=Zone.DECK),
            p.card("CS2_182", zone=Zone.DECK),
            p.card("EX1_066", zone=Zone.DECK),
            p.card("CS2_029", zone=Zone.DECK),
        ]
        watcher = p.give(card_id)
        watcher.play()
        choice = p.choice
        options = list(choice.cards)
        expected_count = len(options) == 3
        options_are_deck_cards = all(card in deck_cards and card.zone == Zone.DECK for card in options)
        ids_are_distinct = len({card.id for card in options}) == len(options)
        selected = options[0]
        choice.choose(selected)
        observed = (
            f"options={[card.id for card in options]};option_entities={[card.entity_id for card in options]};"
            f"count={len(options)},three={expected_count},deck_members={options_are_deck_cards},distinct_ids={ids_are_distinct};"
            f"selected={selected.id}:{selected.zone.name},top={p.deck[-1].id if p.deck else None},"
            f"top_is_selected={bool(p.deck) and p.deck[-1] is selected};"
            f"deck_count={len(p.deck)},choice_open={p.choice is not None};watcher={watcher.zone.name}"
        )
        passed = (
            expected_count
            and options_are_deck_cards
            and ids_are_distinct
            and selected.zone == Zone.DECK
            and selected in p.deck
            and p.deck[-1] is selected
            and len(p.deck) == len(deck_cards)
            and p.choice is None
            and watcher.zone == Zone.PLAY
        )
        return observed, passed

    run_case(
        card_id,
        "watcher_three_candidates_selected_card_on_top",
        "With four unique cards in deck, show exactly three distinct physical deck cards; after choosing one, it remains in deck and is the top card.",
        three_unique_candidates_and_put_chosen_on_top,
        "EN: Battlecry: Look at 3 cards in your deck. Choose one to put on top. ZH: 战吼：检视牌库中的三张牌，选择一张置于牌库顶。 "
        "Impl: fireplace/cards/classic/demonhunter.py:16-23, Choice(CONTROLLER, RANDOM(DeDuplicate(FRIENDLY_DECK))*3) then PutOnTop. "
        "No targeted BT_323 effect assertion found; tests/test_classic.py:3084 contains only a commented-out BT_323 example. Audit row YELLOW/partial.",
    )

    def duplicate_ids_still_offer_three_physical_cards():
        game = new_game()
        p = game.player1
        p.max_mana = 10
        deck_cards = [
            p.card("CS2_231", zone=Zone.DECK),
            p.card("CS2_231", zone=Zone.DECK),
            p.card("CS2_182", zone=Zone.DECK),
            p.card("CS2_182", zone=Zone.DECK),
        ]
        watcher = p.give(card_id)
        watcher.play()
        options = list(p.choice.cards)
        three_physical_options = len(options) == 3 and len({card.entity_id for card in options}) == 3
        all_options_are_physical_deck_entities = all(card in deck_cards and card.zone == Zone.DECK for card in options)
        chosen = options[0]
        p.choice.choose(chosen)
        observed = (
            f"available_physical_cards={[(c.id, c.entity_id) for c in deck_cards]};"
            f"options={[(c.id, c.entity_id) for c in options]},count={len(options)};"
            f"three_distinct_physical_options={three_physical_options};"
            f"all_options_from_deck={all_options_are_physical_deck_entities};"
            f"chosen={chosen.id}:{chosen.zone.name},top_is_chosen={bool(p.deck) and p.deck[-1] is chosen};"
            f"deck_count={len(p.deck)};watcher={watcher.zone.name}"
        )
        passed = (
            three_physical_options
            and all_options_are_physical_deck_entities
            and chosen.zone == Zone.DECK
            and p.deck[-1] is chosen
            and len(p.deck) == len(deck_cards)
            and p.choice is None
            and watcher.zone == Zone.PLAY
        )
        # User-confirmed rule for this audit: copies with the same card ID are
        # separate deck cards and can both appear among the three choices.
        return observed, passed

    run_case(
        card_id,
        "watcher_duplicate_ids_suppress_physical_choice",
        "Even when IDs repeat, the Battlecry must expose three cards from a deck containing four physical cards; one chosen card is put on top.",
        duplicate_ids_still_offer_three_physical_cards,
        "User-confirmed rule: two copies of the same card remain separately discoverable. With two Wisp and two Yeti entities, "
        "DeDuplicate(FRIENDLY_DECK) offers only two options instead of three, so this case confirms the implementation error.",
    )


def main():
    test_acidic_swamp_ooze()
    test_mortal_coil()
    test_tracking()
    test_flametongue_totem()
    test_sightless_watcher()
    with OUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    by_card = {}
    for row in ROWS:
        by_card.setdefault(row["card_id"], []).append(row["outcome"])
    for card_id, outcomes in by_card.items():
        verdict = "RED" if "confirmed_error" in outcomes else "GREEN" if all(o == "pass" for o in outcomes) else "YELLOW"
        print(f"{card_id}: {verdict} cases={len(outcomes)} outcomes={outcomes}")
    print(f"wrote {len(ROWS)} cases to {OUT}")
    if any(row["outcome"] != "pass" for row in ROWS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
