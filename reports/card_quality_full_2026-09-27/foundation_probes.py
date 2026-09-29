"""Phase 2: reproducible death/zone/target/choice/random primitive probes."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone

from fireplace.dsl import ALL_MINIONS, FRIENDLY_MINIONS, RANDOM
from fireplace.exceptions import InvalidAction
from utils import prepare_empty_game, prepare_game


logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


ROWS = []


def record(case_id, mechanism, card_ids, expected, observed, outcome):
    ROWS.append(dict(case_id=case_id, mechanism=mechanism, card_ids=card_ids,
                     expected=expected, observed=observed, outcome=outcome))


def probe_zones():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    wisp = player.give("CS2_231")
    hand = wisp.zone == Zone.HAND and wisp in player.hand
    wisp.play()
    field = wisp.zone == Zone.PLAY and wisp in player.field and wisp not in player.hand
    wisp.destroy()
    graveyard = wisp.zone == Zone.GRAVEYARD and wisp in player.graveyard and wisp not in player.field
    record("ZONE-01", "Zone movement", "CS2_231", "hand->field->graveyard with matching collections",
           f"hand={hand};field={field};graveyard={graveyard}", "pass" if hand and field and graveyard else "wrong_state")

    enemy = game.player2.summon("CS2_231")
    polymorph = player.give("CS2_022")
    targets = enemy in polymorph.targets
    polymorph.play(target=enemy)
    transformed = (enemy.zone == Zone.SETASIDE and
                   len(game.player2.field) == 1 and game.player2.field[0].id == "CS2_tk1" and
                   polymorph.zone == Zone.GRAVEYARD)
    record("ZONE-02", "Transform / Zone movement", "CS2_022|CS2_231",
           "old minion set aside; Sheep in field; spell in graveyard",
           f"target_available={targets};old_zone={enemy.zone.name};field={[c.id for c in game.player2.field]};spell_zone={polymorph.zone.name}",
           "pass" if targets and transformed else "wrong_state")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    wisp = player.summon("CS2_231")
    brewmaster = player.give("EX1_049")
    legal_target = wisp in brewmaster.targets
    brewmaster.play(target=wisp)
    returned = wisp.zone == Zone.HAND and wisp in player.hand and wisp not in player.field
    record("ZONE-03", "Bounce / Zone movement", "EX1_049|CS2_231",
           "Battlecry returns chosen friendly minion to hand",
           f"legal_target={legal_target};wisp_zone={wisp.zone.name};brewmaster_zone={brewmaster.zone.name}",
           "pass" if legal_target and returned and brewmaster.zone == Zone.PLAY else "wrong_state")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    first = player.give("CS2_091")
    first.play()
    second = player.give("CS2_106")
    second.play()
    weapon_replaced = (first.zone == Zone.GRAVEYARD and first in player.graveyard and
                       second.zone == Zone.PLAY and player.weapon is second)
    record("ZONE-04", "Weapon / Zone movement", "CS2_091|CS2_106",
           "replaced weapon enters graveyard; new weapon occupies weapon slot",
           f"old_zone={first.zone.name};new_zone={second.zone.name};equipped={player.weapon.id}",
           "pass" if weapon_replaced else "wrong_state")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    secret = player.give("EX1_287")
    secret.play()
    secret_placed = secret.zone == Zone.SECRET and secret in player.secrets and secret not in player.hand
    record("ZONE-05", "Secret / Zone movement", "EX1_287",
           "played Secret leaves hand and enters secret zone",
           f"zone={secret.zone.name};in_secret_slot={secret in player.secrets}",
           "pass" if secret_placed else "wrong_state")


def probe_death_batch():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    spawn = player.summon("OG_256")
    yeti = player.summon("CS2_182")
    sheep = player.summon("GVG_076")
    yeti.set_current_health(2)
    sheep.destroy()
    observed = (f"spawn={spawn.zone.name};sheep={sheep.zone.name};"
                f"yeti={yeti.zone.name},health={yeti.health};"
                f"field={[card.id for card in player.field]}")
    record("DEATH-01", "Death processing", "GVG_076|OG_256|CS2_182",
           "all minions lethally damaged in the same batch leave play",
           observed, "confirmed_error" if yeti.zone == Zone.PLAY else "pass")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    grandmother = player.summon("ULD_266")
    yeti = player.summon("CS2_182")
    sheep = player.summon("GVG_076")
    yeti.set_current_health(2)
    sheep.destroy()
    reborn_copies = [card for card in player.field if card.id == "ULD_266"]
    record("DEATH-02", "Death processing / Reborn", "GVG_076|ULD_266|CS2_182",
           "one 1-health Reborn copy after one death; same-batch Yeti dies",
           f"source={grandmother.zone.name};reborn_copies={len(reborn_copies)};yeti={yeti.zone.name},health={yeti.health}",
           "confirmed_error" if len(reborn_copies) != 1 or yeti.zone == Zone.PLAY else "pass")


def probe_unwired_deathrattles():
    game = prepare_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    skyvateer = player.summon("YOD_016")
    hand_before, deck_before = len(player.hand), len(player.deck)
    skyvateer.destroy()
    drew = len(player.hand) == hand_before + 1 and len(player.deck) == deck_before - 1
    record("DEATH-03", "Deathrattle tag / Draw", "YOD_016", "death draws one card",
           f"has_deathrattle={skyvateer.has_deathrattle};hand={hand_before}->{len(player.hand)};deck={deck_before}->{len(player.deck)}",
           "pass" if drew else "confirmed_error")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    old_leper = game.player1.summon("VAN_EX1_029")
    before = game.player2.hero.health
    old_leper.destroy()
    record("DEATH-04", "Deathrattle tag / Damage", "VAN_EX1_029", "death deals 2 to enemy hero",
           f"has_deathrattle={old_leper.has_deathrattle};enemy_health={before}->{game.player2.hero.health}",
           "pass" if game.player2.hero.health == before - 2 else "confirmed_error")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    wisp = player.summon("CS2_231")
    player.give("UNG_999t2").play(target=wisp)
    buff = next((card for card in wisp.buffs if card.id == "UNG_999t2e"), None)
    wisp.destroy()
    plants = [card for card in player.field if card.id == "UNG_999t2t1"]
    record("DEATH-05", "Deathrattle tag / Enchantment", "UNG_999t2|UNG_999t2e",
           "Living Spores buff summons two Plants when host dies",
           f"buff_attached={buff is not None};buff_has_deathrattle={buff.has_deathrattle if buff else None};plants={len(plants)}",
           "pass" if len(plants) == 2 else "confirmed_error")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    wisp = player.summon("CS2_231")
    fireball = player.give("CS2_029")
    fate = player.give("TB_PickYourFate_7_2nd")
    fate.play()
    buff = next((card for card in wisp.buffs if card.id == "TB_PickYourFate_7_EnchMiniom2nd"), None)
    cost_before = fireball.cost
    wisp.destroy()
    record("DEATH-06", "Deathrattle tag / Enchantment", "TB_PickYourFate_7_EnchMiniom2nd",
           "death reduces a positive-cost card in hand to zero",
           f"buff_attached={buff is not None};buff_has_deathrattle={buff.has_deathrattle if buff else None};fireball_cost={cost_before}->{fireball.cost}",
           "pass" if fireball.cost == 0 else "confirmed_error")


def probe_targeting():
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    enemy = game.player2.summon("CS2_231")
    polymorph = player.give("CS2_022")
    try:
        polymorph.play(target=player.hero)
        rejected = False
    except InvalidAction:
        rejected = True
    record("TARGET-01", "Targeting", "CS2_022", "invalid hero target rejected; card stays in hand",
           f"rejected={rejected};zone={polymorph.zone.name};enemy_in_targets={enemy in polymorph.targets}",
           "pass" if rejected and polymorph.zone == Zone.HAND and enemy in polymorph.targets else "wrong_state")

    boss_power = player.card("NAX15_04")
    boss_power.zone = Zone.PLAY
    try:
        boss_power.use()
        result = "used_without_exception"
    except Exception as error:
        result = type(error).__name__ + ": " + str(error)
    record("TARGET-02", "Targeting / Random effects", "NAX15_04",
           "random enemy minion stolen without a manual target",
           f"requires_target={boss_power.requires_target()};targets={len(boss_power.play_targets)};result={result};enemy_controller={enemy.controller.name}",
           "pass" if enemy.controller is player and result == "used_without_exception" else "confirmed_error")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    player = game.player1
    enemy = game.player2.summon("CS2_231")
    old_owl = player.give("VAN_CS2_203")
    target_count_before = len(old_owl.targets)
    try:
        old_owl.play()
        result = "played_without_exception"
    except Exception as error:
        result = type(error).__name__ + ": " + str(error)
    record("TARGET-03", "Targeting / Silence", "VAN_CS2_203",
           "requires a minion target before play",
           f"targets_before={target_count_before};result={result};card_zone={old_owl.zone.name};enemy_silenced={enemy.silenced}",
           "pass" if target_count_before and result == "played_without_exception" and enemy.silenced else "confirmed_error")


def probe_choice_and_random():
    game = prepare_empty_game(CardClass.PRIEST, CardClass.PRIEST)
    player = game.player1
    curator = player.give("LOE_006")
    waiting_wisp = player.give("CS2_231")
    curator.play()
    choice = player.choice
    options = list(choice.cards)
    options_valid = len(options) == 3 and len({card.id for card in options}) == 3 and all(card.data.deathrattle for card in options)
    invalid = player.card("CS2_231")
    try:
        choice.choose(invalid)
        invalid_rejected = False
    except InvalidAction:
        invalid_rejected = True
    blocked = not waiting_wisp.is_playable()
    still_open = player.choice is choice
    chosen = options[0]
    choice.choose(chosen)
    resolved = player.choice is None and len(player.hand) == 2 and chosen in player.hand
    record("CHOICE-01", "Discover / Choice", "LOE_006",
           "3 unique Deathrattle options; invalid choice rejected; actions blocked; selected card enters hand",
           f"options={len(options)};valid={options_valid};invalid_rejected={invalid_rejected};blocked={blocked};still_open={still_open};resolved={resolved}",
           "pass" if all((options_valid, invalid_rejected, blocked, still_open, resolved)) else "wrong_state")

    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    empty = RANDOM(FRIENDLY_MINIONS).eval(game, game.player1)
    left = game.player1.summon("CS2_231")
    right = game.player2.summon("CS2_231")
    selector = RANDOM(ALL_MINIONS)
    game.random.seed(731)
    first = selector.eval(game, game.player1)
    game.random.seed(731)
    replayed = selector.eval(game, game.player1)
    sampled = (selector * 3).eval(game, game.player1)
    valid = not empty and len(first) == len(replayed) == 1 and first[0] is replayed[0] and set(sampled) == {left, right}
    record("RANDOM-01", "Random effects", "CS2_231",
           "empty pool returns none; same seed repeats choice; sample without replacement caps at pool size",
           f"empty={len(empty)};first={[c.id for c in first]};replayed={[c.id for c in replayed]};sample_size={len(sampled)};unique={len(set(sampled))}",
           "pass" if valid else "wrong_state")


def main():
    probe_zones()
    probe_death_batch()
    probe_unwired_deathrattles()
    probe_targeting()
    probe_choice_and_random()
    path = Path(__file__).with_name("foundation_probes.csv")
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(ROWS[0]))
        writer.writeheader()
        writer.writerows(ROWS)
    for row in ROWS:
        print(row["case_id"], row["outcome"], row["observed"])


if __name__ == "__main__":
    main()
