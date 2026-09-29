"""Check that Wing Commander's hand-dependent Attack changes continuously."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)
HERE = Path(__file__).resolve().parent


def scaling_case(case_id, card_id, partner_id, expected, *, opponent_hand=False):
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    if opponent_hand:
        player.opponent.discard_hand()
    subject = player.summon(card_id)
    start = subject.atk
    if opponent_hand:
        partner = player.opponent.give(partner_id)
    else:
        partner = player.summon(partner_id)
    with_one = subject.atk
    if opponent_hand:
        partner.discard()
    else:
        partner.destroy()
    after = subject.atk
    got = (start, with_one, after)
    return dict(case_id=case_id, mechanism="Conditional stats / Continuous effect",
                card_ids=f"{card_id}|{partner_id}",
                expected=f"Attack before/with/after relevant entity: {expected}",
                observed=f"attack_sequence={got};subject_zone={subject.zone.name};partner_zone={partner.zone.name}",
                outcome="pass" if got == expected and subject.zone == Zone.PLAY else "confirmed_error")


def main():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    dragon1 = player.give("EX1_284")
    commander = player.give("DRG_058")
    commander.play()
    one_dragon = commander.atk
    dragon2 = player.give("EX1_284")
    two_dragons = commander.atk
    dragon1.discard()
    after_one_discard = commander.atk
    dragon2.discard()
    after_both_discard = commander.atk
    expected_stats = (4, 6, 4, 2)
    observed_stats = (one_dragon, two_dragons, after_one_discard, after_both_discard)
    row = dict(case_id="STATS-01", mechanism="Conditional stats / Continuous effect",
               card_ids="DRG_058|EX1_284",
               expected=f"Attack follows 1,2,1,0 Dragons in hand: {expected_stats}",
               observed=f"attack_sequence={observed_stats};commander_zone={commander.zone.name};dragon_zones={dragon1.zone.name},{dragon2.zone.name}",
               outcome="pass" if observed_stats == expected_stats and commander.zone == Zone.PLAY else "confirmed_error")
    rows = [row]
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    ravens = [player.summon("DRG_088")]
    first = tuple(card.atk for card in ravens)
    ravens.append(player.summon("DRG_088"))
    second = tuple(card.atk for card in ravens)
    ravens.append(player.summon("DRG_088"))
    third = tuple(card.atk for card in ravens)
    raven_expected = ((3,), (6, 6), (9, 9, 9))
    raven_got = (first, second, third)
    rows.append(dict(case_id="STATS-02", mechanism="Conditional stats / Continuous effect",
                     card_ids="DRG_088", expected=f"0,1,2 other Ravens -> {raven_expected}",
                     observed=f"attack_sequence={raven_got};field={len(player.field)}",
                     outcome="pass" if raven_got == raven_expected else "confirmed_error"))
    rows.append(scaling_case("STATS-03", "TB_KTRAF_5", "CS2_231", (0, 1, 0), opponent_hand=True))
    rows.append(scaling_case("STATS-04", "TB_BaconUps_036", "CS2_168", (4, 6, 4)))
    rows.append(scaling_case("STATS-05", "ULDA_501", "CS2_231", (3, 5, 3)))
    rows.append(scaling_case("STATS-06", "EX1_062", "CS2_168", (2, 3, 2)))
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    queen = player.summon("ICC_841")
    queen_attack = [queen.atk]
    for _ in range(2):
        player.give("CS2_231").discard()
        queen_attack.append(queen.atk)
    queen_expected = [1, 2, 3]
    rows.append(dict(case_id="STATS-07", mechanism="Conditional stats / Continuous effect",
                     card_ids="ICC_841|CS2_231", expected=f"0,1,2 discarded cards -> {queen_expected}",
                     observed=f"attack_sequence={queen_attack};queen_zone={queen.zone.name}",
                     outcome="pass" if queen_attack == queen_expected and queen.zone == Zone.PLAY else "confirmed_error"))
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    guard1 = player.summon("DALA_503")
    alone = guard1.atk
    guard2 = player.summon("DALA_503")
    pair = (guard1.atk, guard2.atk)
    rows.append(dict(case_id="STATS-08", mechanism="Conditional stats / Continuous effect",
                     card_ids="DALA_503", expected="one Guard 1 Attack; two Guards each 2 Attack",
                     observed=f"alone={alone};pair={pair};field={len(player.field)}",
                     outcome="pass" if alone == 1 and pair == (2, 2) else "confirmed_error"))
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    butch = player.summon("GILA_403")
    butch_before = (butch.atk, butch.health)
    beast = player.summon("CS2_172")
    beast.destroy()
    butch_after = (butch.atk, butch.health)
    rows.append(dict(case_id="STATS-09", mechanism="Conditional stats / Continuous effect",
                     card_ids="GILA_403|CS2_172", expected="friendly Beast death grows Butch from 1/1 to 2/2",
                     observed=f"butch={butch_before}->{butch_after};beast_zone={beast.zone.name};butch_zone={butch.zone.name}",
                     outcome="pass" if butch_before == (1, 1) and butch_after == (2, 2)
                     and beast.zone == Zone.GRAVEYARD else "confirmed_error"))
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    assistant = player.summon("GILA_907")
    stats = [(assistant.atk, assistant.health)]
    for _ in range(2):
        player.give("GAME_005").play()
        stats.append((assistant.atk, assistant.health))
    rows.append(dict(case_id="STATS-10", mechanism="Conditional stats / Continuous effect",
                     card_ids="GILA_907|GAME_005", expected="0,1,2 spells cast -> stats 1/1,2/2,3/3",
                     observed=f"stats_sequence={stats};assistant_zone={assistant.zone.name}",
                     outcome="pass" if stats == [(1, 1), (2, 2), (3, 3)]
                     and assistant.zone == Zone.PLAY else "confirmed_error"))
    with (HERE / "conditional_stats_probe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerows(rows)
    for item in rows:
        print(item)


if __name__ == "__main__":
    main()
