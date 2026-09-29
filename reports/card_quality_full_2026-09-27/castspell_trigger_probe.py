"""Compare effect-cast and hand-played spell events for Antonidas."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from utils import prepare_empty_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
HERE = Path(__file__).resolve().parent


def fireballs(player):
    return sum(card.id == "CS2_029" for card in player.hand)


def main():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.current_player
    player.summon("EX1_559")
    player.summon("LOOT_414")
    spell = player.give("CS2_023")
    spell.shuffle_into_deck()
    for _ in range(2):
        player.give("CS2_231").shuffle_into_deck()
    before = fireballs(player)
    before_hand, before_deck = len(player.hand), len(player.deck)
    game.end_turn()
    effect_cast_fireballs = fireballs(player) - before
    effect_cast_zone = spell.zone.name
    effect_cast_draws = len(player.hand) - before_hand
    effect_cast_deck_change = before_deck - len(player.deck)

    control = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    owner = control.current_player
    owner.summon("EX1_559")
    played_coin = owner.give("GAME_005")
    before_control = fireballs(owner)
    played_coin.play()
    hand_play_fireballs = fireballs(owner) - before_control
    observed = (f"effect_cast_spell_zone={effect_cast_zone};effect_cast_draws={effect_cast_draws};"
                f"effect_cast_deck_change={effect_cast_deck_change};effect_cast_fireballs={effect_cast_fireballs};"
                f"hand_play_coin_zone={played_coin.zone.name};hand_play_fireballs={hand_play_fireballs}")
    row = dict(case_id="CAST-TRIGGER-01", mechanism="CastSpell / Trigger",
               card_ids="LOOT_414|EX1_559|CS2_023|GAME_005",
               expected="observe minion-cast versus player-cast event behavior; caster identity semantics need confirmation",
               observed=observed, outcome="inconclusive")
    wyrm_game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    wyrm_owner = wyrm_game.current_player
    wyrm_owner.summon("LOOT_414")
    wyrm = wyrm_owner.summon("NEW1_012")
    arcane = wyrm_owner.give("CS2_023")
    arcane.shuffle_into_deck()
    for _ in range(2):
        wyrm_owner.give("CS2_231").shuffle_into_deck()
    before_wyrm = wyrm.atk
    before_wyrm_hand = len(wyrm_owner.hand)
    wyrm_game.end_turn()
    wyrm_draws = len(wyrm_owner.hand) - before_wyrm_hand
    row2 = dict(case_id="CAST-TRIGGER-02", mechanism="CastSpell / Trigger",
                card_ids="LOOT_414|NEW1_012|CS2_023",
                expected="observe whether minion-cast spell counts as player casting for Mana Wyrm",
                observed=f"spell_zone={arcane.zone.name};draws={wyrm_draws};wyrm_attack={before_wyrm}->{wyrm.atk};wyrm_zone={wyrm.zone.name}",
                outcome="inconclusive")
    secret_game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    secret_owner = secret_game.current_player
    caster = secret_owner.opponent
    counterspell = secret_owner.give("EX1_287")
    counterspell.play()
    caster.summon("LOOT_414")
    secret_game.end_turn()
    enemy_arcane = caster.give("CS2_023")
    enemy_arcane.shuffle_into_deck()
    for _ in range(2):
        caster.give("CS2_231").shuffle_into_deck()
    before_enemy_hand = len(caster.hand)
    secret_game.end_turn()
    enemy_draws = len(caster.hand) - before_enemy_hand
    row3 = dict(case_id="CAST-SECRET-01", mechanism="CastSpell / Secret",
                card_ids="LOOT_414|EX1_287|CS2_023",
                expected="observe whether Counterspell reacts to a minion-cast opponent spell",
                observed=f"spell_zone={enemy_arcane.zone.name};opponent_draws={enemy_draws};"
                         f"counterspell_zone={counterspell.zone.name};secret_still_set={counterspell in secret_owner.secrets}",
                outcome="inconclusive")
    with (HERE / "castspell_trigger_probe.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerows([row, row2, row3])
    print(row)
    print(row2)
    print(row3)


if __name__ == "__main__":
    main()
