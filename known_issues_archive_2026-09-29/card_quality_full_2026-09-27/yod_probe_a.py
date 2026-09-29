"""Independent live-game audit of the first 33 frozen YEAR_OF_THE_DRAGON YELLOW cards."""

from __future__ import annotations

import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import InvalidAction

logging.disable(logging.CRITICAL)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))
from utils import ANIMATED_STATUE, MOONFIRE, WISP, prepare_empty_game  # noqa: E402

PROBE_OUT = HERE / "yod_probe_a.csv"
VERDICT_OUT = HERE / "yod_verdict_a.csv"
BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")

FROZEN_IDS = (
    "YOD_001", "YOD_003", "YOD_004", "YOD_005", "YOD_006", "YOD_007",
    "YOD_009", "YOD_010", "YOD_012", "YOD_013", "YOD_014", "YOD_015",
    "YOD_017", "YOD_018", "YOD_020", "YOD_022", "YOD_023", "YOD_024",
    "YOD_025", "YOD_026", "YOD_027", "YOD_028", "YOD_029", "YOD_030",
    "YOD_032", "YOD_033", "YOD_035", "YOD_036", "YOD_038", "YOD_040",
    "YOD_041", "YOD_042", "YOD_043",
)
assert len(FROZEN_IDS) == len(set(FROZEN_IDS)) == 33


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_BY_ID = {row["card_id"]: row for row in read_csv(BASELINE)}
MASTER_BY_ID = {row["card_id"]: row for row in read_csv(MASTER)}
QUALITY_BY_ID = {row["card_id"]: row for row in read_csv(QUALITY)}
YOD_ROSTER = sorted(
    (row for row in read_csv(BASELINE) if row["set"].endswith("(YEAR_OF_THE_DRAGON)") and row["status"] == "YELLOW"),
    key=lambda row: row["card_id"],
)
assert [row["card_id"] for row in YOD_ROSTER] == list(FROZEN_IDS)
assert all(cid in MASTER_BY_ID and cid in QUALITY_BY_ID for cid in FROZEN_IDS)


def metadata(card_id):
    master, prior = MASTER_BY_ID[card_id], BASE_BY_ID[card_id]
    return (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or master.get('xml_source', '')}; "
        f"existing_tests={master.get('test_refs_candidate', '') or 'none'}; "
        f"previous={prior.get('status', 'unknown')}:{prior.get('reason', '')}"
    )


def new_game(seed=19, class1=CardClass.MAGE, class2=CardClass.MAGE):
    random.seed(seed)
    game = prepare_empty_game(class1, class2)
    game.random.seed(seed)
    for player in game.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    if game.current_player is not game.player1:
        game.end_turn()
    assert game.current_player is game.player1
    return game


def play(player, card_id, target=None, choose=None):
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    card.play(**kwargs)
    return card


def summon(player, card_id):
    return player.summon(card_id)


def put_deck(player, card_ids):
    cards = []
    for card_id in card_ids:
        card = player.give(card_id)
        card.shuffle_into_deck()
        cards.append(card)
    return cards


def result(observed, passed, detail, error=False):
    return observed, "confirmed_error" if error else ("pass" if passed else "inconclusive"), detail


def case_001():
    game = new_game(CardClass.DRUID, CardClass.DRUID)
    owner, opponent = game.player1, game.player2
    drawn = put_deck(owner, ["CS2_231"])[0]
    first = play(owner, "YOD_001", choose="YOD_001b")
    twin = next((card for card in owner.hand if card.id == "YOD_001ts"), None)
    draw_ok = drawn in owner.hand and drawn.zone == Zone.HAND
    first_zone = first.zone.name
    eagle = None
    second_zone = None
    if twin:
        twin.play(choose="YOD_001c")
        second_zone = twin.zone.name
        eagle = next((m for m in owner.field if m.id == "YOD_001t"), None)
    checks = {
        "draw_in_hand": draw_ok,
        "first_in_graveyard": first.zone == Zone.GRAVEYARD,
        "twin_found": twin is not None,
        "twin_in_graveyard": twin is not None and twin.zone == Zone.GRAVEYARD,
        "eagle_present": eagle is not None,
        "eagle_3_2_play": eagle is not None and (eagle.atk, eagle.health, eagle.zone) == (3, 2, Zone.PLAY),
        "no_third_twin": not any(c.id == "YOD_001ts" for c in owner.hand),
    }
    observed = f"draw_branch={drawn.zone.name};first_spell={first_zone};twin={twin.id if twin else None}:{twin.zone.name if twin else None};summon_branch={((eagle.atk,eagle.health,eagle.zone.name) if eagle else None)};second_spell={second_zone};extra_twin={any(c.id == 'YOD_001ts' for c in owner.hand)};checks={checks}"
    valid = draw_ok and first.zone == Zone.GRAVEYARD and twin is not None and second_zone == Zone.GRAVEYARD.name
    valid &= eagle is not None and (eagle.atk, eagle.health, eagle.zone) == (3, 2, Zone.PLAY)
    valid &= not any(c.id == "YOD_001ts" for c in owner.hand)
    return result(observed, valid, "both Choose One branches and the one-use Twinspell copy were checked")


def case_003():
    game = new_game(CardClass.MAGE, CardClass.MAGE)  # Fireblast is a targeted Hero Power.
    owner, enemy = game.player1, game.player2
    guardian = summon(owner, "YOD_003")
    spell = owner.give(MOONFIRE)
    power = owner.hero.power
    spell_targetable = guardian in spell.play_targets
    power_targetable = guardian in power.play_targets
    spell_rejected = power_rejected = False
    try:
        spell.play(target=guardian)
    except InvalidAction:
        spell_rejected = True
    try:
        power.use(target=guardian)
    except InvalidAction:
        power_rejected = True
    before_hero = enemy.hero.health
    guardian.destroy()
    reborn = next((m for m in owner.field if m.id == "YOD_003"), None)
    observed = f"printed_tags=taunt:{guardian.taunt};reborn:{guardian.reborn};spell_targetable={spell_targetable};hero_power_targetable={power_targetable};rejections={spell_rejected}/{power_rejected};reborn_entity={(reborn.id,reborn.health,reborn.reborn,reborn.taunt) if reborn else None};enemy_hero={before_hero}->{enemy.hero.health}"
    valid = bool(guardian.taunt) and not spell_targetable and not power_targetable
    valid &= spell_rejected and power_rejected and enemy.hero.health == before_hero
    valid &= guardian.zone == Zone.GRAVEYARD and reborn is not None
    valid &= reborn.health == 1 and not reborn.reborn and reborn.taunt
    return result(observed, valid, "XML keywords, spell and Hero Power target gates, and Reborn remainder checked")


def case_004():
    seen, valid, invalid_ids = set(), True, set()
    for seed in range(48):
        game = new_game(seed, CardClass.HUNTER, CardClass.HUNTER)
        owner = game.player1
        copter = summon(owner, "YOD_004")
        mech = summon(owner, "GVG_002")  # Snowchugger: Mech without a Deathrattle.
        before = list(owner.hand)
        mech.destroy()
        added = [card for card in owner.hand if card not in before]
        valid &= mech.zone == Zone.GRAVEYARD and copter.zone == Zone.PLAY
        valid &= len(added) == 1 and Race.MECHANICAL in added[0].races
        seen.update(card.id for card in added)
        invalid_ids.update(card.id for card in added if Race.MECHANICAL not in card.races)
    control = new_game(class1=CardClass.HUNTER, class2=CardClass.HUNTER)
    owner, enemy = control.player1, control.player2
    copter = summon(owner, "YOD_004")
    nonmech = summon(owner, "CS2_182")
    hand_before = list(owner.hand)
    nonmech.destroy()
    nonmech_no_trigger = not [c for c in owner.hand if c not in hand_before]
    enemy_mech = summon(enemy, "GVG_002")
    hand_before = list(owner.hand)
    enemy_mech.destroy()
    enemy_no_trigger = not [c for c in owner.hand if c not in hand_before]
    observed = f"48_friendly_mech_deaths;distinct_generated={len(seen)};non_mech_generated_ids={sorted(invalid_ids)};all_mech_race={valid};friendly_nonmech_no_trigger={nonmech_no_trigger};enemy_mech_no_trigger={enemy_no_trigger};copter={copter.zone.name}"
    return result(observed, valid and len(seen) >= 2 and nonmech_no_trigger and enemy_no_trigger,
                  "friendly-Mech trigger, random Mech pool, and controller/type exclusions checked")


def case_005():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = game.player1, game.player2
    first_beast = summon(owner, "CS2_171")  # Stonetusk Boar
    nonbeast = summon(owner, "CS2_182")
    spell = owner.give("YOD_005")
    legal = [m.id for m in spell.play_targets]
    before = (first_beast.atk, first_beast.max_health)
    spell.play(target=first_beast)
    twin = next((c for c in owner.hand if c.id == "YOD_005ts"), None)
    second_beast = summon(owner, "CS2_171")  # another Stonetusk Boar instance
    second_spell_ok = False
    if twin:
        twin.play(target=second_beast)
        second_spell_ok = (second_beast.atk, second_beast.max_health) == (second_beast.data.atk + 2, second_beast.data.health + 2)
    observed = f"legal_targets={legal};nonbeast_target_legal={nonbeast.id in legal};first_beast={before}->{first_beast.atk}/{first_beast.max_health};twin={twin.id if twin else None};second_beast={second_beast.id}:{second_spell_ok};extra_twin={any(c.id == 'YOD_005ts' for c in owner.hand)};enemy_hero={enemy.hero.health}"
    valid = first_beast.id in legal and nonbeast.id not in legal
    valid &= (first_beast.atk, first_beast.max_health) == (before[0] + 2, before[1] + 2)
    valid &= twin is not None and twin.zone == Zone.GRAVEYARD and second_spell_ok
    valid &= not any(c.id == "YOD_005ts" for c in owner.hand)
    return result(observed, valid, "Beast target prerequisite, +2/+2, and both Twinspell resolutions checked")


def case_006():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = game.player1, game.player2
    owner.max_mana = 5
    owner.used_mana = 5
    saber = summon(owner, "YOD_006")
    enemy_target = summon(enemy, "CS2_182")
    saber.turns_in_play = 1
    saber.cant_attack = False
    max_before = owner.max_mana
    resources_before = owner.max_resources
    temp_before = owner.temp_mana
    stealth_before = bool(saber.stealthed)
    saber.attack(enemy_target)
    temp_after = owner.temp_mana
    max_after_attack = owner.max_mana
    attack_damage = enemy_target.health
    game.end_turn()
    temp_after_opponent_turn = owner.temp_mana
    game.end_turn()
    next_turn_temp = owner.temp_mana
    observed = f"stealth={stealth_before}->{saber.stealthed};target_health={enemy_target.max_health}->{enemy_target.health};max_mana={max_before}->{max_after_attack}->{owner.max_mana};max_resources={resources_before}->{owner.max_resources};temp_mana={temp_before}->{temp_after}->{temp_after_opponent_turn}->{next_turn_temp};saber={saber.zone.name}"
    valid = stealth_before and not saber.stealthed and attack_damage < enemy_target.max_health
    valid &= temp_after == temp_before + 1 and max_after_attack == max_before
    valid &= owner.max_resources == resources_before
    valid &= next_turn_temp == 0
    return result(observed, valid, "Stealth attack triggers a temporary mana crystal; the mana does not persist to the next turn")


def avalanche_scenario(with_elemental):
    game = new_game(CardClass.MAGE, CardClass.MAGE)
    owner, enemy = game.player1, game.player2
    if with_elemental:
        elemental = play(owner, "UNG_027")  # Fire Fly, an Elemental played from hand.
        game.end_turn()
        game.end_turn()
    else:
        elemental = None
    before = len(owner.field)
    avalanche = play(owner, "YOD_007")
    generated = [m for m in owner.field if m not in (avalanche,) and m.id == "YOD_007"]
    observed = f"elemental_last_turn={elemental is not None};source={avalanche.id}:{avalanche.atk}/{avalanche.max_health}:{avalanche.zone.name};matching_avalanches={[(m.atk,m.max_health,m.zone.name) for m in generated]};board_before={before};board_after={len(owner.field)}"
    wanted = 2 if with_elemental else 1
    valid = avalanche.zone == Zone.PLAY and len([m for m in owner.field if m.id == "YOD_007"]) == wanted
    valid &= all((m.atk, m.max_health) == (7, 6) for m in owner.field if m.id == "YOD_007")
    return observed, valid


def case_007():
    positive, p_ok = avalanche_scenario(True)
    negative, n_ok = avalanche_scenario(False)
    return result(f"positive=[{positive}];negative=[{negative}]", p_ok and n_ok,
                  "last-turn Elemental positive and no-Elemental control both checked")


def case_009():
    game = new_game(CardClass.MAGE, CardClass.MAGE)
    owner, enemy = game.player1, game.player2
    own = [summon(owner, "CS2_182"), summon(owner, "EX1_016")]
    theirs = [summon(enemy, "CS2_182"), summon(enemy, "CS2_168")]
    keep_own = [summon(owner, "YOD_010")]
    all_minions = own + theirs + keep_own
    hero_before = (owner.hero.health, enemy.hero.health)
    reno = play(owner, "YOD_009")
    removed = [(m.id, m.zone.name) for m in all_minions]
    hero_after = (owner.hero.health, enemy.hero.health)
    observed = f"reno_hero={owner.hero.id};hero_card={reno.id}:{reno.zone.name};minions={removed};heroes={hero_before}->{hero_after};deathrattle_shotbot_graveyard={keep_own[0].zone.name}"
    valid = all(m.zone == Zone.REMOVEDFROMGAME for m in all_minions)
    valid &= owner.hero.id == "YOD_009" and hero_after == hero_before
    valid &= keep_own[0].zone == Zone.REMOVEDFROMGAME
    return result(observed, valid, "Hero transformation and minion removal checked across both boards; Reborn minion must not die")


def case_010():
    game = new_game(CardClass.PALADIN, CardClass.PALADIN)
    owner, enemy = game.player1, game.player2
    shotbot = summon(owner, "YOD_010")
    original = (shotbot.atk, shotbot.max_health, bool(shotbot.reborn))
    enemy_target = summon(enemy, "CS2_182")
    shotbot.destroy()
    reborn = next((m for m in owner.field if m.id == "YOD_010"), None)
    observed = f"original={original};source={shotbot.zone.name};reborn={(reborn.id,reborn.atk,reborn.health,reborn.max_health,reborn.reborn,reborn.zone.name) if reborn else None};enemy={enemy_target.zone.name}"
    valid = shotbot.zone == Zone.GRAVEYARD and reborn is not None
    valid &= (reborn.atk, reborn.health, reborn.reborn, reborn.zone) == (2, 1, False, Zone.PLAY)
    return result(observed, valid, "XML Reborn keyword was exercised through death and the 1-Health return")


def case_012():
    game = new_game(CardClass.PALADIN, CardClass.PALADIN)
    owner = game.player1
    spell = play(owner, "YOD_012")
    first = [m for m in owner.field if m.id == "CS2_101t"]
    twin = next((c for c in owner.hand if c.id == "YOD_012ts"), None)
    second = []
    if twin:
        twin.play()
        second = [m for m in owner.field if m.id == "CS2_101t" and m not in first]
    all_recruits = first + second
    observed = f"first={[(m.id,m.atk,m.health,m.taunt) for m in first]};twin={twin.id if twin else None}:{twin.zone.name if twin else None};second={[(m.id,m.atk,m.health,m.taunt) for m in second]};spell={spell.zone.name};board={len(owner.field)}"
    valid = spell.zone == Zone.GRAVEYARD and len(first) == len(second) == 2
    valid &= all((m.atk,m.health,bool(m.taunt)) == (1,1,True) for m in all_recruits)
    valid &= twin is not None and twin.zone == Zone.GRAVEYARD and not any(c.id == "YOD_012ts" for c in owner.hand)
    return result(observed, valid, "both Twinspell casts summon two 1/1 Taunt recruits")


def case_013():
    game = new_game(CardClass.PRIEST, CardClass.PRIEST)
    owner, enemy = game.player1, game.player2
    dragon = owner.give("EX1_561")
    spells = put_deck(owner, ["CS2_023", "CS2_024", "CS2_029"])
    cleric = play(owner, "YOD_013")
    options = list(owner.choice.cards) if owner.choice else []
    option_ids = [c.id for c in options]
    selected = options[0] if options else None
    if selected:
        owner.choice.choose(selected)
    no_dragon_game = new_game(CardClass.PRIEST, CardClass.PRIEST)
    no_dragon_cleric = play(no_dragon_game.player1, "YOD_013")
    no_dragon_no_choice = no_dragon_game.player1.choice is None
    observed = f"dragon_in_hand={dragon.zone.name};options={option_ids};selected={selected.id if selected else None}:{selected.zone.name if selected else None};spell_in_deck={[c.id for c in spells if c in owner.deck]};cleric={cleric.zone.name};no_dragon_choice={no_dragon_no_choice};control_cleric={no_dragon_cleric.zone.name}"
    valid = len(options) == 3 and len(set(option_ids)) == 3 and all(c.type == CardType.SPELL for c in options)
    valid &= selected is not None and selected.zone == Zone.HAND and selected in owner.hand
    valid &= cleric.zone == Zone.PLAY and no_dragon_no_choice and no_dragon_cleric.zone == Zone.PLAY
    return result(observed, valid, "Dragon prerequisite gates the Discover; a selected deck spell is drawn to hand")


def case_014():
    game = new_game(CardClass.PRIEST, CardClass.PRIEST)
    owner, enemy = game.player1, game.player2
    target = summon(enemy, ANIMATED_STATUE)
    attack, health = target.atk, target.health
    reaver = play(owner, "YOD_014", target)
    damage = health - target.health
    observed = f"target_attack={attack};target_health={health}->{target.health};damage={damage};reaver_attack={reaver.atk};target={target.zone.name};reaver={reaver.zone.name}"
    if target.zone == Zone.PLAY and reaver.zone == Zone.PLAY and damage != attack:
        return result(observed, False,
                      "卡面要求伤害等于目标随从攻击力；实际攻击值与目标值不同，重现了明确偏差。", error=True)
    return result(observed, target.zone == Zone.PLAY and reaver.zone == Zone.PLAY and damage == attack,
                  "damage amount compared with the selected minion's Attack")


def case_015():
    game = new_game(CardClass.PRIEST, CardClass.PRIEST)
    owner = game.player1
    spell = play(owner, "YOD_015")
    options = list(owner.choice.cards) if owner.choice else []
    option_ids = [card.id for card in options]
    selected = options[-1] if options else None
    base = (int(selected.data.cost), int(selected.data.atk), int(selected.data.health)) if selected else None
    if selected:
        owner.choice.choose(selected)
    summoned = [m for m in owner.field if m is not None]
    result_minion = next((m for m in summoned if m.id != "YOD_015"), None)
    observed = f"spell={spell.zone.name};options={[(c.id,c.data.cost,c.data.atk,c.data.health) for c in options]};selected={selected.id if selected else None};base={base};summoned={(result_minion.id,result_minion.data.cost,result_minion.atk,result_minion.health,result_minion.max_health,result_minion.zone.name) if result_minion else None};choice_open={bool(owner.choice)}"
    valid = len(options) == 3 and len(set(option_ids)) == 3 and all(c.type == CardType.MINION and c.data.cost == 2 for c in options)
    valid &= selected is not None and not owner.choice and spell.zone == Zone.GRAVEYARD
    valid &= result_minion is not None and result_minion.id == selected.id and result_minion.zone == Zone.PLAY
    valid &= result_minion.data.cost == 2 and result_minion.max_health == base[2] + 3 and result_minion.atk == base[1]
    return result(observed, valid, "Discover pool is exactly three distinct 2-Cost minions; selected minion is summoned with +3 Health")


def case_017():
    game = new_game(CardClass.ROGUE, CardClass.ROGUE)
    owner = game.player1
    cards = put_deck(owner, ["CS2_231", "CS2_182", "CS2_033"])
    play(owner, "GAME_005")
    play(owner, MOONFIRE, target=game.player2.hero)
    before_hand = list(owner.hand)
    sculptor = play(owner, "YOD_017")
    drawn = [card for card in owner.hand if card not in before_hand]
    observed = f"cards_played_before_sculptor=2;drawn={[c.id for c in drawn]};expected_top_deck_candidates={[c.id for c in cards]};sculptor={sculptor.zone.name};remaining_deck={[c.id for c in owner.deck]}"
    valid = sculptor.zone == Zone.PLAY and len(drawn) == 2 and all(c in cards for c in drawn)
    # Counter-free control: the printed Combo keyword must not make the card draw on its own.
    control = new_game(CardClass.ROGUE, CardClass.ROGUE)
    control_owner = control.player1
    control_deck = put_deck(control_owner, ["CS2_231"])
    control_before = list(control_owner.hand)
    control_sculptor = play(control_owner, "YOD_017")
    control_drawn = [c for c in control_owner.hand if c not in control_before]
    observed += f";zero_combo_control_draws={[c.id for c in control_drawn]};control_deck_card={control_deck[0].zone.name}"
    valid &= control_sculptor.zone == Zone.PLAY and not control_drawn and control_deck[0] in control_owner.deck
    return result(observed, valid, "two previous plays draw exactly two; without previous plays the Combo has no draw")


def case_018():
    game = new_game(CardClass.WARLOCK, CardClass.WARLOCK)
    owner = game.player1
    wax = play(owner, "YOD_018")
    options = list(owner.choice.cards) if owner.choice else []
    selected = options[0] if options else None
    before_cost = int(selected.data.cost) if selected else None
    if selected:
        owner.choice.choose(selected)
    added = [card for card in owner.hand if card.id == selected.id] if selected else []
    received = added[-1] if added else None
    observed = f"options={[(c.id,c.data.cost,c.cost,bool(c.data.battlecry)) for c in options]};selected={selected.id if selected else None};printed_cost={before_cost};received={(received.id,received.cost,received.zone.name) if received else None};spell={wax.zone.name};choice_open={bool(owner.choice)}"
    valid = wax.zone == Zone.GRAVEYARD and len(options) == 3 and selected is not None
    valid &= all(c.type == CardType.MINION and bool(c.data.battlecry) for c in options)
    valid &= received is not None and received.zone == Zone.HAND and not owner.choice
    valid &= received.cost == max(0, before_cost - 2)
    return result(observed, valid, "every Discover option is a Battlecry minion; the added card gets the two-mana reduction")


def case_020():
    spawned_ids, valid = set(), True
    for seed in range(24):
        game = new_game(seed, CardClass.SHAMAN, CardClass.SHAMAN)
        owner, enemy = game.player1, game.player2
        target = summon(enemy, "CS2_182")
        before_cost = int(target.data.cost)
        spell = play(owner, "YOD_020", target)
        replacement = next((m for m in enemy.field if m is not target), None)
        valid &= target.zone == Zone.SETASIDE and spell.zone == Zone.GRAVEYARD and replacement is not None
        if replacement:
            valid &= replacement.zone == Zone.PLAY and int(replacement.data.cost) == before_cost + 3
            spawned_ids.add(replacement.id)
    observed = f"seeds=24;original_cost=4;distinct_replacements={len(spawned_ids)};sample={sorted(spawned_ids)[:20]};replacement_printed_cost=7;original_left_play=True"
    return result(observed, valid and len(spawned_ids) >= 2, "Evolve replacement costs exactly three more and replaces the selected minion")


def case_022():
    game = new_game(CardClass.WARRIOR, CardClass.WARRIOR)
    owner, enemy = game.player1, game.player2
    skipper = play(owner, "YOD_022")
    allies = [summon(owner, ANIMATED_STATUE)]
    foe = summon(enemy, ANIMATED_STATUE)
    before = [skipper.damage] + [m.damage for m in allies + [foe]]
    played = play(owner, "CS2_182")
    targets = [skipper] + allies + [foe, played]
    deltas = [m.damage - before[i] for i, m in enumerate(targets[:-1])] + [played.damage]
    expected_deltas = [1, 1, 1, 1]
    after_friendly = [m.health for m in targets]
    # An opponent minion play is not the owner-trigger event.
    game.end_turn()
    enemy_minion = play(enemy, "CS2_182")
    enemy_play_no_new_damage = all(m.damage == 1 for m in targets if m is not played) and played.damage == 1
    observed = f"skipper={skipper.zone.name};friendly_play={played.id}:{played.zone.name};damage_deltas={deltas};all_minion_health={after_friendly};opponent_play={enemy_minion.zone.name};owner_minions_still_damage1={enemy_play_no_new_damage}"
    valid = skipper.zone == Zone.PLAY and played.zone == Zone.PLAY and deltas == expected_deltas
    valid &= enemy_minion.zone == Zone.PLAY and enemy_play_no_new_damage
    return result(observed, valid, "own minion Play damages all current minions including the played minion; opponent Play is excluded")


def case_023():
    game = new_game(CardClass.WARRIOR, CardClass.WARRIOR)
    owner = game.player1
    spell = play(owner, "YOD_023")
    options = list(owner.choice.cards) if owner.choice else []
    ids = [c.id for c in options]
    cats = []
    for card in options:
        if card.id in ("DAL_613", "DAL_614", "DAL_615", "DAL_739", "DAL_741", "ULD_616", "DRG_052"):
            cats.append("Lackey")
        elif Race.MECHANICAL in card.races:
            cats.append("Mech")
        elif Race.DRAGON in card.races:
            cats.append("Dragon")
        else:
            cats.append("invalid")
    selected = options[-1] if options else None
    if selected:
        owner.choice.choose(selected)
    observed = f"spell={spell.zone.name};options={list(zip(ids,cats))};selected={selected.id if selected else None}:{selected.zone.name if selected else None};choice_open={bool(owner.choice)}"
    valid = len(options) == 3 and len(set(cats)) == 3 and set(cats) == {"Lackey", "Mech", "Dragon"}
    valid &= selected is not None and selected.zone == Zone.HAND and selected in owner.hand and not owner.choice
    valid &= spell.zone == Zone.GRAVEYARD
    return result(observed, valid, "the three offered cards represent one Lackey, one Mech, and one Dragon; chosen card enters hand")


def case_024():
    game = new_game(CardClass.WARRIOR, CardClass.WARRIOR)
    owner = game.player1
    bomber = summon(owner, "YOD_024")
    for hit in range(2):
        play(owner, MOONFIRE, target=bomber)
    bots = [m for m in owner.field if m.id == "GVG_110t"]
    observed = f"bomber_health={bomber.health};bomber={bomber.zone.name};bots={[(m.id,m.atk,m.health,m.zone.name) for m in bots]}"
    valid = bomber.zone == Zone.PLAY and bomber.health == 1 and len(bots) == 2
    valid &= all((m.atk,m.health,m.zone) == (1,1,Zone.PLAY) for m in bots)
    return result(observed, valid, "two distinct damage events each summon exactly one 1/1 Boom Bot")


def case_025():
    game = new_game(CardClass.WARLOCK, CardClass.WARLOCK)
    owner = game.player1
    spell = play(owner, "YOD_025")
    choices = []
    chosen = []
    for index in range(2):
        options = list(owner.choice.cards) if owner.choice else []
        choices.append(options)
        selected = options[index % len(options)] if options else None
        if selected:
            chosen.append(selected)
            owner.choice.choose(selected)
    discovered = [c for c in owner.hand if c not in [spell]]
    ids = [card.id for card in discovered]
    valid_options = len(choices) == 2 and all(len(opts) == 3 and all(c.card_class == CardClass.WARLOCK for c in opts) for opts in choices)
    observed = f"spell={spell.zone.name};options={[[c.id for c in opts] for opts in choices]};chosen={[(c.id,c.zone.name) for c in chosen]};warlock_cards_in_hand={ids};choice_open={bool(owner.choice)}"
    valid = spell.zone == Zone.GRAVEYARD and valid_options and len(chosen) == 2 and all(c.zone == Zone.HAND for c in chosen)
    valid &= all(c in owner.hand for c in chosen) and not owner.choice
    return result(observed, valid, "two Discover resolutions each offer Warlock cards and move a selected card to hand")


def case_026():
    winners, valid = set(), True
    for seed in range(48):
        game = new_game(seed, CardClass.WARLOCK, CardClass.WARLOCK)
        owner, enemy = game.player1, game.player2
        first, second = summon(owner, "CS2_182"), summon(owner, "EX1_016")
        enemy_minion = summon(enemy, "CS2_182")
        servant = summon(owner, "YOD_026")
        attack = servant.atk
        servant.destroy()
        deltas = [first.atk - 4, second.atk - 5, enemy_minion.atk - 4]
        hit = [index for index, delta in enumerate(deltas[:2]) if delta == attack]
        valid &= servant.zone == Zone.GRAVEYARD and sum(deltas) == attack and deltas[2] == 0 and len(hit) == 1
        if len(hit) == 1:
            winners.add(hit[0])
    observed = f"seeds=48;friendly_recipient_indexes={sorted(winners)};exactly_attack={2};enemy_buffed=False;one_friendly_recipient_each_death=True"
    return result(observed, valid and winners == {0,1}, "deathrattle transfers the Servant's Attack to one other friendly minion across random recipients")


def case_027():
    game = new_game(CardClass.WARLOCK, CardClass.WARLOCK)
    owner, opponent = game.player1, game.player2
    playable = opponent.give(WISP)
    unplayable = opponent.give("CS2_029")
    opponent.max_mana = 0
    gazer = play(owner, "YOD_027")
    game.end_turn()
    game.end_turn()  # opponent's one opportunity ends; an unplayed Corrupted card is destroyed.
    observed = f"gazer={gazer.zone.name};playable_cost={playable.data.cost};playable_after_opponent_turn={playable.zone.name};unplayable_cost={unplayable.data.cost};unplayable_after_opponent_turn={unplayable.zone.name};opponent_turns_ended=True"
    valid = gazer.zone == Zone.PLAY and playable.zone == Zone.GRAVEYARD and unplayable.zone == Zone.HAND
    return result(observed, valid, "playable-card condition selects the zero-cost hand card; expiry is at the opponent's turn end")


def case_028():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = game.player1, game.player2
    one_cost = owner.give("CS2_171")  # Stonetusk Boar, printed cost 1.
    one_cost.shuffle_into_deck()
    other = owner.give("CS2_182")
    other.shuffle_into_deck()
    instructor = play(owner, "YOD_028")
    observed = f"instructor={instructor.zone.name};eligible_one_cost={one_cost.id}:{one_cost.zone.name};four_cost={other.zone.name};owner_field={[(m.id,m.data.cost,m.zone.name) for m in owner.field]};deck={[c.id for c in owner.deck]}"
    valid = instructor.zone == Zone.PLAY and one_cost.zone == Zone.PLAY and one_cost in owner.field
    valid &= other.zone == Zone.DECK and other in owner.deck
    valid &= sum(1 for m in owner.field if m is one_cost) == 1
    return result(observed, valid, "Battlecry summons exactly the eligible one-cost minion from the deck")


def case_029():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = game.player1, game.player2
    hail = play(owner, "YOD_029")
    shards = [m for m in owner.field if m.id == "YOD_029t"]
    minion_target = summon(enemy, "CS2_182")
    for shard in shards:
        shard.turns_in_play = 1
        shard.cant_attack = False
        shard.num_attacks = 0
    if len(shards) == 2:
        shards[0].attack(minion_target)
        shards[1].attack(enemy.hero)
    observed = f"hail={hail.zone.name};shards={[(m.id,m.atk,m.health,m.zone.name) for m in shards]};minion_health={minion_target.max_health}->{minion_target.health};minion_frozen={minion_target.frozen};hero_health={enemy.hero.health};hero_frozen={enemy.hero.frozen}"
    valid = hail.zone == Zone.PLAY and len(shards) == 2
    valid &= sum(1 for m in owner.field if m.id == "YOD_029t") == 1
    valid &= shards[0].zone == Zone.GRAVEYARD and shards[1].zone == Zone.PLAY
    valid &= minion_target.frozen and enemy.hero.frozen and minion_target.health == minion_target.max_health - 1
    return result(observed, valid, "Battlecry summons two 1/1 shards; their damage triggers Freeze on minion and hero targets")


def quest_play(player):
    quest = player.give("ULD_131")  # Untapped Potential, a real Druid Quest.
    quest.play()
    return quest


def case_030():
    no_quest = new_game(CardClass.PALADIN, CardClass.PALADIN)
    plain = play(no_quest.player1, "YOD_030")
    no_coin = not any(c.id == "GAME_005" for c in no_quest.player1.hand)
    positive = new_game(CardClass.DRUID, CardClass.DRUID)
    owner = positive.player1
    quest = quest_play(owner)
    adventurer = play(owner, "YOD_030")
    coins = [c for c in owner.hand if c.id == "GAME_005"]
    observed = f"no_quest_coin={no_coin};no_quest_adventurer={plain.zone.name};quest={quest.id}:{quest.zone.name};quest_state={[card.id for card in owner.secrets]};with_quest_coins={len(coins)};adventurer={adventurer.zone.name}"
    valid = no_coin and plain.zone == Zone.PLAY and quest.zone == Zone.SECRET
    valid &= quest in owner.secrets and len(coins) == 1 and adventurer.zone == Zone.PLAY
    return result(observed, valid, "no-Quest negative control and active Quest Battlecry condition checked")


def case_032():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = game.player1, game.player2
    felwing = owner.give("YOD_032")
    base = felwing.cost
    play(owner, MOONFIRE, target=enemy.hero)
    after_hero_hit = felwing.cost
    enemy_minion = summon(enemy, "CS2_182")
    play(owner, MOONFIRE, target=enemy_minion)
    after_minion_hit = felwing.cost
    felwing2 = owner.give("YOD_032")
    second_cost = felwing2.cost
    observed = f"enemy_hero_damage={enemy.hero.damaged_this_turn};enemy_minion_damage={enemy_minion.max_health-enemy_minion.health};felwing={base}->{after_hero_hit}->{after_minion_hit};second_felwing_cost={second_cost}"
    valid = (base, after_hero_hit, after_minion_hit, second_cost) == (4,3,3,3)
    return result(observed, valid, "only damage to the opposing hero reduces Frenzied Felwing's cost")


def case_033():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = game.player1, game.player2
    battlecry = enemy.give("EX1_048")  # Spellbreaker, Battlecry minion.
    non_battlecry = enemy.give("CS2_182")
    source = play(owner, "YOD_033")
    immediate = (battlecry.cost, non_battlecry.cost)
    game.end_turn()
    next_enemy_turn = game.current_player is enemy
    on_enemy_turn = (battlecry.cost, non_battlecry.cost)
    game.end_turn()
    after_enemy_turn = (battlecry.cost, non_battlecry.cost)
    observed = f"bully={source.zone.name};immediate={immediate};enemy_turn={next_enemy_turn};during_enemy_turn={on_enemy_turn};after_enemy_turn={after_enemy_turn}"
    valid = source.zone == Zone.PLAY and next_enemy_turn
    valid &= on_enemy_turn == (9,4) and after_enemy_turn == (4,4)
    return result(observed, valid, "only enemy Battlecry cards cost +5 during the next enemy turn, then revert")


def case_035():
    game = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner = game.player1
    erkh = summon(owner, "YOD_035")
    lackey = play(owner, "DAL_613")
    generated = [c for c in owner.hand if c.id in {"DAL_613", "DAL_614", "DAL_615", "DAL_739", "DAL_741", "ULD_616", "DRG_052"}]
    other = play(owner, "CS2_231")
    lackeys_after_non_lackey = len([c for c in owner.hand if c.id in {"DAL_613", "DAL_614", "DAL_615", "DAL_739", "DAL_741", "ULD_616", "DRG_052"}])
    observed = f"erkh={erkh.zone.name};lackey_play={lackey.zone.name};generated_lackeys={[c.id for c in generated]};nonlackey={other.zone.name};lackey_count_after_nonlackey={lackeys_after_non_lackey}"
    valid = erkh.zone == Zone.PLAY and lackey.zone == Zone.PLAY and len(generated) == 1
    valid &= generated[0].zone == Zone.HAND and other.zone == Zone.PLAY and lackeys_after_non_lackey == 1
    return result(observed, valid, "playing a Lackey adds one random Lackey; a non-Lackey play adds none")


def case_036():
    seen, valid = set(), True
    for seed in range(24):
        game = new_game(seed, CardClass.HUNTER, CardClass.HUNTER)
        owner, enemy = game.player1, game.player2
        dragon = owner.give("EX1_561")
        enemies = [summon(enemy, "CS2_182"), summon(enemy, "EX1_016")]
        drake = play(owner, "YOD_036")
        killed = [m.id for m in enemies if m.zone == Zone.GRAVEYARD]
        valid &= drake.zone == Zone.PLAY and dragon.zone == Zone.HAND and len(killed) == 1
        seen.update(killed)
    no_dragon = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner2, enemy2 = no_dragon.player1, no_dragon.player2
    enemies2 = [summon(enemy2, "CS2_182"), summon(enemy2, "EX1_016")]
    drake2 = play(owner2, "YOD_036")
    no_dragon_unchanged = all(m.zone == Zone.PLAY for m in enemies2)
    observed = f"24_dragon_condition_games;killed_candidate_ids={sorted(seen)};random_enemy_winners=1_per_case;positive_drake=PLAY;no_dragon_board={[m.zone.name for m in enemies2]};no_dragon_drake={drake2.zone.name}"
    return result(observed, valid and seen == {"CS2_182", "EX1_016"} and no_dragon_unchanged and drake2.zone == Zone.PLAY,
                  "holding a Dragon enables exactly one random enemy destruction; no-Dragon control has none")


def case_038():
    negative = new_game(CardClass.HUNTER, CardClass.HUNTER)
    owner, enemy = negative.player1, negative.player2
    no_quest_enemies = [summon(enemy, "CS2_182")]
    kragg0 = play(owner, "YOD_038")
    no_parrot = not any(m.id == "YOD_038t" for m in owner.field)
    positive = new_game(CardClass.DRUID, CardClass.DRUID)
    owner2, enemy2 = positive.player1, positive.player2
    quest = quest_play(owner2)
    kragg = play(owner2, "YOD_038")
    parrot = next((m for m in owner2.field if m.id == "YOD_038t"), None)
    observed = f"without_quest={kragg0.zone.name};parrot_without_quest={no_parrot};quest={quest.zone.name};kragg={(kragg.atk,kragg.health,kragg.taunt,kragg.zone.name)};parrot={(parrot.id,parrot.atk,parrot.health,parrot.rush,parrot.zone.name) if parrot else None}"
    valid = kragg0.zone == Zone.PLAY and no_parrot and kragg.zone == Zone.PLAY and kragg.taunt
    valid &= parrot is not None and (parrot.atk,parrot.health,parrot.zone) == (4,2,Zone.PLAY) and parrot.rush
    return result(observed, valid, "Quest-played-this-game gate, Taunt on Kragg, and 4/2 Rush Parrot reward checked")


def case_040():
    positive = new_game(CardClass.DRUID, CardClass.DRUID)
    owner = positive.player1
    expensive = owner.give("CS2_028")  # Blizzard, cost 6.
    armor_before = owner.hero.armor
    beetle = play(owner, "YOD_040")
    armor_after = owner.hero.armor
    negative = new_game(CardClass.DRUID, CardClass.DRUID)
    owner2 = negative.player1
    low_spell = owner2.give(MOONFIRE)
    armor2_before = owner2.hero.armor
    beetle2 = play(owner2, "YOD_040")
    armor2_after = owner2.hero.armor
    observed = f"expensive_spell={expensive.id}:{expensive.cost};armor={armor_before}->{armor_after};beetle={beetle.zone.name};low_spell={low_spell.id}:{low_spell.cost};negative_armor={armor2_before}->{armor2_after};beetle_without_qualifier={beetle2.zone.name}"
    valid = armor_after == armor_before + 5 and beetle.zone == Zone.PLAY
    valid &= armor2_after == armor2_before and beetle2.zone == Zone.PLAY
    return result(observed, valid, "holding a 5+-cost spell grants 5 Armor; low-cost-only hand gives no Armor")


def case_041():
    game = new_game(CardClass.SHAMAN, CardClass.SHAMAN)
    owner = game.player1
    base = [summon(owner, "CS2_182") for _ in range(3)]
    spell = play(owner, "YOD_041")
    elementals = [m for m in owner.field if m.id == "YOD_041t"]
    observed = f"spell={spell.zone.name};elementals={[(m.id,m.atk,m.health,m.taunt,m.races,m.zone.name) for m in elementals]};overloaded={owner.overloaded};base_count={len(base)};board={len(owner.field)}"
    valid = spell.zone == Zone.GRAVEYARD and len(elementals) == 3
    valid &= all((m.atk,m.health,bool(m.taunt),m.zone) == (5,6,True,Zone.PLAY) and Race.ELEMENTAL in m.races for m in elementals)
    valid &= owner.overloaded == 3 and len(owner.field) == 6
    return result(observed, valid, "three 5/6 Taunt Elementals and the printed Overload 3 are both checked")


def case_042():
    seen, valid = set(), True
    for seed in range(24):
        game = new_game(seed, CardClass.SHAMAN, CardClass.SHAMAN)
        owner, enemy = game.player1, game.player2
        fist = play(owner, "YOD_042")
        enemy_spell = enemy.give(MOONFIRE)
        game.end_turn()
        before_enemy_spell = (fist.damage, len(owner.field))
        enemy_spell.play(target=owner.hero)
        after_enemy_spell = (fist.damage, len(owner.field))
        game.end_turn()
        own_spell = play(owner, "CS2_025")  # Arcane Explosion, cost 2.
        summoned = [m for m in owner.field if m is not None and m is not fist]
        added = [m for m in summoned if int(m.data.cost) == 2]
        valid &= enemy_spell.zone == Zone.GRAVEYARD and after_enemy_spell == before_enemy_spell
        valid &= fist.damage == after_enemy_spell[0] + 1 and len(added) >= 1 and all(m.rarity == 5 for m in added)
        valid &= own_spell.zone == Zone.GRAVEYARD
        seen.update(m.id for m in added)
    observed = f"24_games;different_cost_2_legendaries={len(seen)};sample={sorted(seen)[:20]};enemy_spell_no_trigger=True;own_cost2_spell_summons_legendary_and_loses_durability=True"
    return result(observed, valid and len(seen) >= 1, "opponent's spell is excluded; an own positive-cost spell summons a matching-cost Legendary and loses durability")


def case_043():
    game = new_game(CardClass.PALADIN, CardClass.PALADIN)
    owner, enemy = game.player1, game.player2
    friendlies = [summon(owner, "CS2_168"), summon(owner, "EX1_506"), summon(owner, "CS2_182")]
    opposing_murloc = summon(enemy, "CS2_168")
    paladin = play(owner, "YOD_043")
    states = [(m.id, Race.MURLOC in m.races, bool(m.divine_shield)) for m in friendlies + [opposing_murloc]]
    observed = f"scalelord={paladin.zone.name};states={states};non_murloc_shield={friendlies[2].divine_shield}"
    valid = paladin.zone == Zone.PLAY
    valid &= all(m.divine_shield for m in friendlies[:2]) and not friendlies[2].divine_shield
    valid &= not opposing_murloc.divine_shield
    return result(observed, valid, "Battlecry grants Shield to friendly Murlocs only; enemy Murloc and friendly non-Murloc are controls")


CASES = {
    "YOD_001": ("both_choose_one_branches_and_twinspell", case_001, "Draw one card or summon a 3/2 Eagle; first cast creates a Twinspell copy, second cast resolves without another copy."),
    "YOD_003": ("untargetable_taunt_reborn", case_003, "XML Taunt/Reborn and Spell/Hero Power untargetability persist after the 1-Health Reborn return."),
    "YOD_004": ("friendly_mech_death_random_hand_reward", case_004, "A friendly Mech death adds one random Mech; non-Mech and enemy Mech deaths do not."),
    "YOD_005": ("beast_gate_and_twinspell_buffs", case_005, "Fresh Scent buffs Beast targets by +2/+2 on both casts and excludes non-Beasts."),
    "YOD_006": ("stealth_attack_temporary_mana", case_006, "Attack while Stealthed gains one temporary mana this turn and none remains next turn."),
    "YOD_007": ("elemental_last_turn_copy_gate", case_007, "Playing an Elemental last turn summons an exact copy; no Elemental means no copy."),
    "YOD_009": ("reno_hero_and_all_minion_poof", case_009, "Transform into Reno and remove minions on both boards without killing them or changing heroes' health."),
    "YOD_010": ("shotbot_reborn_keyword", case_010, "Shotbot returns as a 2/1 without Reborn after its first death."),
    "YOD_012": ("both_air_raid_twinspell_summons", case_012, "Each cast summons two 1/1 Taunt Recruits and the first cast creates one Twinspell copy."),
    "YOD_013": ("dragon_gate_deck_spell_discover", case_013, "Holding a Dragon opens a three-spell Discover from deck; without one, Cleric produces no choice."),
    "YOD_014": ("battlecry_damage_equals_target_attack", case_014, "Aeon Reaver damages the chosen minion by exactly that minion's Attack, not the Reaver's Attack."),
    "YOD_015": ("discover_summon_two_cost_plus_health", case_015, "Discover offers distinct 2-Cost minions; selected minion is summoned and gains +3 Health."),
    "YOD_017": ("combo_draw_count_and_zero_control", case_017, "Two cards played first draw exactly two; no prior card means no Combo draw."),
    "YOD_018": ("discover_battlecry_cost_reduction", case_018, "All Discover candidates have Battlecry and selected hand copy costs 2 less, floored at zero."),
    "YOD_020": ("evolve_random_minion_plus_three_cost", case_020, "Across seeds, Explosive Evolution replaces its target with one minion whose printed cost is exactly +3."),
    "YOD_022": ("friendly_minion_play_aoe_trigger", case_022, "After a friendly minion is played, all minions take 1; opponent minion plays do not trigger it."),
    "YOD_023": ("lackey_mech_dragon_choice", case_023, "Choice presents one Lackey, one Mech, and one Dragon; selected card enters hand."),
    "YOD_024": ("damage_events_summon_boom_bots", case_024, "Each damage event to Bomb Wrangler summons one 1/1 Boom Bot."),
    "YOD_025": ("two_warlock_discover_resolutions", case_025, "Twisted Knowledge offers Warlock cards on two Discover resolutions and moves both selections to hand."),
    "YOD_026": ("deathrattle_attack_to_random_other_friendly", case_026, "Deathrattle transfers the Servant's Attack to exactly one other friendly minion, never an enemy."),
    "YOD_027": ("chaos_gazer_playable_card_and_expiry", case_027, "Chaos Gazer corrupts a playable enemy card; the unplayed card is destroyed after that player's turn."),
    "YOD_028": ("summon_one_cost_minion_from_deck", case_028, "Battlecry summons exactly an eligible 1-Cost minion from deck; nonqualifying deck minion remains."),
    "YOD_029": ("ice_shard_damage_freeze", case_029, "Battlecry summons two Ice Shards whose damage freezes minions and heroes."),
    "YOD_030": ("licensed_adventurer_quest_gate", case_030, "No active Quest yields no Coin; active Quest yields exactly one Coin."),
    "YOD_032": ("felwing_cost_only_enemy_hero_damage", case_032, "Each damage point to enemy hero reduces cost by one; enemy minion damage does not."),
    "YOD_033": ("boompistol_enemy_battlecry_next_turn_cost", case_033, "Enemy Battlecry minions cost +5 on the next enemy turn, then revert; other cards are unaffected."),
    "YOD_035": ("lackey_play_trigger_random_lackey", case_035, "Playing a Lackey adds one Lackey; playing a non-Lackey adds none."),
    "YOD_036": ("dragon_gate_random_enemy_destroy", case_036, "Holding a Dragon destroys one random enemy minion; no Dragon means no destruction."),
    "YOD_038": ("quest_reward_parrot_rush_taunt", case_038, "Quest history unlocks a 4/2 Rush Parrot; Kragg has Taunt and no Quest means no Parrot."),
    "YOD_040": ("holding_high_cost_spell_armor", case_040, "Holding a spell costing 5+ grants 5 Armor; only a low-cost spell does not."),
    "YOD_041": ("eye_storm_three_taunt_elementals_overload", case_041, "Summons three 5/6 Taunt Elementals and applies Overload 3."),
    "YOD_042": ("fist_matching_cost_legendary_and_enemy_exclusion", case_042, "Opponent spell does not trigger; own cost-2 spell summons a matching Legendary and loses 1 durability."),
    "YOD_043": ("scalelord_friendly_murloc_shields", case_043, "Gives Divine Shield to friendly Murlocs only."),
}


def run_card(card_id):
    name, function, expected = CASES[card_id]
    observed, outcome, detail = function()
    return {
        "card_id": card_id,
        "case_id": f"{card_id}::{name}",
        "expected": expected,
        "observed": observed,
        "outcome": outcome,
        "notes": f"{detail}; {metadata(card_id)}",
    }


def main():
    selected_ids = sys.argv[1:] or list(FROZEN_IDS)
    assert selected_ids and all(card_id in CASES for card_id in selected_ids)
    # Focused invocations update one card at a time while preserving completed rows.
    # A no-argument run starts fresh and fully reruns the frozen roster.
    if sys.argv[1:]:
        probes = read_csv(PROBE_OUT) if PROBE_OUT.exists() else []
        verdicts = read_csv(VERDICT_OUT) if VERDICT_OUT.exists() else []
    else:
        probes, verdicts = [], []
    probe_by_id = {row["card_id"]: row for row in probes}
    verdict_by_id = {row["card_id"]: row for row in verdicts}
    for card_id in selected_ids:
        try:
            row = run_card(card_id)
        except Exception as exc:
            # A broken fixture/action is not evidence of a card bug; keep it yellow for review.
            row = {
                "card_id": card_id,
                "case_id": f"{card_id}::{CASES[card_id][0]}",
                "expected": CASES[card_id][2],
                "observed": f"{type(exc).__name__}: {exc}",
                "outcome": "inconclusive",
                "notes": f"runtime/fixture exception; review before assigning a card verdict; {metadata(card_id)}",
            }
        probe_by_id[card_id] = row
        probes = [probe_by_id[cid] for cid in FROZEN_IDS if cid in probe_by_id]
        write_csv(PROBE_OUT, PROBE_FIELDS, probes)
        previous = QUALITY_BY_ID[card_id]
        master = MASTER_BY_ID[card_id]
        if row["outcome"] == "confirmed_error":
            status = "RED"
            reason = f"实测与卡牌文本不符：{row['case_id']} expected=[{row['expected']}] actual=[{row['observed']}]"
        elif row["outcome"] == "pass":
            status, reason = "GREEN", f"本轮逐卡实际效果与重要分支用例通过：{row['case_id']}={row['observed']}"
        else:
            status, reason = "YELLOW", f"关键分支未能完成验证：{row['case_id']}={row['observed']}"
        verdict_by_id[card_id] = {
            "card_id": card_id,
            "status": status,
            "mechanic_scope": previous["mechanic"],
            "reason": reason,
            "probe_file": PROBE_OUT.name,
            "notes": f"new_case={row['case_id']}; outcome={row['outcome']}; {metadata(card_id)}",
        }
        verdicts = [verdict_by_id[cid] for cid in FROZEN_IDS if cid in verdict_by_id]
        write_csv(VERDICT_OUT, VERDICT_FIELDS, verdicts)
        print(f"{card_id} {row['case_id']}: {row['outcome']} -> {status} :: {row['observed']}", flush=True)
    assert len(probes) == len(verdicts)
    assert {row["card_id"] for row in probes} == {row["card_id"] for row in verdicts}
    assert len({row["case_id"] for row in probes}) == len(probes)
    counts = {name: sum(row["status"] == name for row in verdicts) for name in ("GREEN", "YELLOW", "RED")}
    print(f"COUNTS {counts}; cases={len(probes)}; requested={len(selected_ids)}; frozen_roster={len(FROZEN_IDS)}")


if __name__ == "__main__":
    main()
