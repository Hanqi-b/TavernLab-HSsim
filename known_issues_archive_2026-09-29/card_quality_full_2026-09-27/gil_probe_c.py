"""Card-by-card live behavior probes for GILNEAS frozen indices 84:125."""
import argparse
import csv
import json
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Rarity, Zone

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, MOONFIRE, FIREBALL, prepare_empty_game  # noqa: E402
from fireplace.exceptions import InvalidAction  # noqa: E402

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
MECHANISMS = HERE / "card_mechanism.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE_OUT = HERE / "gil_probe_c.csv"
VERDICT_OUT = HERE / "gil_verdict_c.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_ROWS = sorted(
    (row for row in read_csv(BASELINE) if row["set"] == "The Witchwood (GILNEAS)"),
    key=lambda row: row["card_id"],
)
OWN_ROWS = BASE_ROWS[84:125]
OWN_IDS = [row["card_id"] for row in OWN_ROWS]
assert len(OWN_IDS) == 41 and OWN_IDS[0] == "GIL_655" and OWN_IDS[-1] == "GIL_905"
MASTER_BY_ID = {row["card_id"]: row for row in read_csv(MASTER)}
QUALITY_BY_ID = {row["card_id"]: row for row in read_csv(QUALITY)}
MECHANISMS_BY_ID = {}
for _row in read_csv(MECHANISMS):
    MECHANISMS_BY_ID.setdefault(_row["card_id"], []).append(_row)
ISSUES_FOR_CARD = {}
for _row in read_csv(ISSUES):
    for _field in ("confirmed_cards", "candidate_cards"):
        for _card_id in _row[_field].split("|"):
            if _card_id:
                ISSUES_FOR_CARD.setdefault(_card_id, []).append(_row)


class ProbeInconclusive(Exception):
    """A tested branch could not be isolated because a prerequisite failed."""


def class_for(card_id):
    tags = json.loads(MASTER_BY_ID[card_id]["raw_xml_tags"] or "{}")
    card_class = CardClass(int(tags.get("CLASS") or 12))
    return CardClass.MAGE if card_class == CardClass.NEUTRAL else card_class


def new_game(card_id, seed=4051, opponent_class=None):
    random.seed(seed)
    card_class = class_for(card_id)
    if opponent_class is None or opponent_class == card_class:
        opponent_class = CardClass.ROGUE if card_class != CardClass.ROGUE else CardClass.MAGE
    game = prepare_empty_game(card_class, opponent_class)
    game.random.seed(seed)
    actor = next(player for player in game.players if player.hero.card_class == card_class)
    if game.current_player is not actor:
        game.end_turn()
    assert game.current_player is actor
    for player in game.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    return game


def give(player, card_id):
    card = player.give(card_id)
    assert card is not None, f"could not give {card_id}"
    return card


def summon(player, card_id):
    card = player.summon(card_id)
    assert card is not None, f"could not summon {card_id}"
    return card


def play(player, card_id, target=None, choose=None, index=None):
    card = give(player, card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    if index is not None:
        kwargs["index"] = index
    card.play(**kwargs)
    return card


def deck_top(player, card_id):
    return player.card(card_id, zone=Zone.DECK)


def ids(cards):
    return [card.id for card in cards]


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    prior = QUALITY_BY_ID.get(card_id, {})
    previous_mechanics = MECHANISMS_BY_ID.get(card_id, [])
    mechanism_text = " | ".join(
        f"{row['mechanic']}={row['status']}:{row['reason']}" for row in previous_mechanics
    ) or "none"
    related_issues = ISSUES_FOR_CARD.get(card_id, [])
    issue_text = " | ".join(
        f"{row['issue_id']}({row['severity']}):{row['summary']}" for row in related_issues
    ) or "none"
    return (
        f"EN={master['card_text_en']}; ZH={master['card_text_zh']}; "
        f"source={master['python_source'] or master['xml_source']}; "
        f"existing_tests={master['test_refs_candidate'] or 'none'}; "
        f"prior_card={prior.get('status', 'unknown')}:{prior.get('reason', 'no prior reason')}; "
        f"prior_mechanisms={mechanism_text}; related_mechanism_issues={issue_text}"
    )


def checked(observed, condition):
    assert condition, observed
    return observed


PROBE_ROWS = []
VERDICT_ROWS = []


def record(card_id, case_id, expected, func):
    try:
        observed = func()
        outcome = "pass"
    except AssertionError as exc:
        observed = str(exc)
        if not observed:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error"
    except ProbeInconclusive as exc:
        observed = str(exc)
        outcome = "inconclusive"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    PROBE_ROWS.append({
        "card_id": card_id, "case_id": case_id, "expected": expected,
        "observed": observed, "outcome": outcome, "notes": metadata(card_id),
    })
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    print(f"{card_id} {case_id}: {outcome} | {observed}", flush=True)
    return outcome


def finish_card(card_id):
    rows = [row for row in PROBE_ROWS if row["card_id"] == card_id]
    assert rows and len({row["case_id"] for row in rows}) == len(rows)
    errors = [row for row in rows if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in rows if row["outcome"] == "inconclusive"]
    scope = QUALITY_BY_ID[card_id]["mechanic"]
    if errors:
        status = "RED"
        reason = "Confirmed live mismatch: " + "; ".join(
            f"{row['case_id']} expected=[{row['expected']}] observed=[{row['observed']}]"
            for row in errors
        )
    elif unresolved:
        status = "YELLOW"
        reason = "Concrete live-probe blocker: " + "; ".join(
            f"{row['case_id']}={row['observed']}" for row in unresolved
        )
    else:
        status = "GREEN"
        reason = "All live cases passed: " + "; ".join(
            f"{row['case_id']} observed {row['observed']}" for row in rows
        )
    VERDICT_ROWS.append({
        "card_id": card_id, "status": status, "mechanic_scope": scope,
        "reason": reason, "probe_file": PROBE_OUT.name,
        "notes": f"Cases={len(rows)}; probe rows contain EN/ZH text, source, existing tests, and prior audit details.",
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"updated {card_id}: {status} ({len(PROBE_ROWS)} total cases)", flush=True)
    return status


def c655_friendly_minion_attack_gains_attack():
    g = new_game("GIL_655", seed=6551)
    p, e = g.current_player, g.current_player.opponent
    hulk = summon(p, "GIL_655")
    attacker = summon(p, "CS2_182")
    target = summon(e, "CS2_231")
    before = hulk.atk
    g.end_turn()
    g.end_turn()
    attack_error = None
    try:
        attacker.attack(target)
    except InvalidAction as exc:
        attack_error = type(exc).__name__
    observed = (f"attack_error={attack_error};hulk={hulk.zone.name}/{before}->{hulk.atk};"
                f"attacker={attacker.zone.name}/{attacker.damage};target={target.zone.name}")
    return checked(observed, attack_error is None and hulk.zone == Zone.PLAY
                   and hulk.atk == before + 1 and attacker.zone == Zone.PLAY
                   and target.zone == Zone.GRAVEYARD)


def c655_hero_attack_does_not_trigger():
    g = new_game("GIL_655", seed=6552)
    p, e = g.current_player, g.current_player.opponent
    hulk = summon(p, "GIL_655")
    before = hulk.atk
    weapon = play(p, "CS2_105")
    p.hero.attack(e.hero)
    observed = f"weapon={weapon.id};hero_attacks={p.hero.num_attacks};hulk={before}->{hulk.atk}"
    return checked(observed, p.hero.num_attacks == 1 and hulk.atk == before)


def c658_copy_target_to_hand():
    g = new_game("GIL_658", seed=6581)
    p = g.current_player
    target = summon(p, "CS2_182")
    before = (target.id, target.atk, target.health, target.max_health)
    card = play(p, "GIL_658", target=target)
    copies = [c for c in p.hand if c.id == target.id]
    observed = (f"source={target.id}/{target.atk}/{target.health}/{target.max_health};"
                f"generated={[(c.id,c.atk,c.health,c.max_health,c.cost,c.zone.name) for c in copies]};"
                f"battlecry={card.zone.name}")
    return checked(observed, card.zone == Zone.PLAY and len(copies) == 1
                   and (target.id, target.atk, target.health, target.max_health) == before
                   and (copies[0].atk, copies[0].health, copies[0].max_health, copies[0].cost)
                   == (10, 10, 10, 10) and copies[0] is not target)


def c658_no_friendly_target():
    g = new_game("GIL_658", seed=6582)
    p = g.current_player
    card = play(p, "GIL_658")
    observed = f"card={card.zone.name};field={ids(p.field)};hand={ids(p.hand)}"
    return checked(observed, card.zone == Zone.PLAY and list(p.field) == [card] and not p.hand)


def c661_heals_only_friendly_characters_up_to_maximum():
    g = new_game("GIL_661", seed=6611)
    p, e = g.current_player, g.current_player.opponent
    p.hero.damage = 8
    damaged = summon(p, "CS2_182")
    damaged.damage = 3
    full = summon(p, "CS2_231")
    e.hero.damage = 4
    enemy = summon(e, "CS2_182")
    enemy.damage = 2
    spell = play(p, "GIL_661")
    observed = (f"spell={spell.zone.name};friendly_hero={p.hero.health};"
                f"friendly_minions={(damaged.health,full.health)};"
                f"enemy={(e.hero.health,enemy.health,enemy.damage)}")
    return checked(observed, p.hero.health == 28 and damaged.health == damaged.max_health
                   and full.health == full.max_health and e.hero.health == 26
                   and enemy.damage == 2)


def c663_adds_three_treants_to_hand():
    g = new_game("GIL_663", seed=6631)
    p = g.current_player
    spell = play(p, "GIL_663")
    treants = [c for c in p.hand if c.id == "GIL_663t"]
    observed = f"spell={spell.zone.name};treants={[(c.id,c.atk,c.health,c.zone.name) for c in treants]}"
    return checked(observed, spell.zone == Zone.GRAVEYARD and len(treants) == 3
                   and all((c.atk,c.health,c.zone) == (2,2,Zone.HAND) for c in treants))


def c664_spell_cast_summons_random_two_cost_minion():
    g = new_game("GIL_664", seed=6641)
    p, e = g.current_player, g.current_player.opponent
    crow = summon(p, "GIL_664")
    spell = play(p, "CS2_029", target=e.hero)
    spawned = [m for m in p.field if m is not crow]
    observed = f"spell={spell.zone.name};spawned={[(m.id,m.cost,m.atk,m.health,m.zone.name) for m in spawned]}"
    return checked(observed, spell.zone == Zone.GRAVEYARD and len(spawned) == 1
                   and spawned[0].zone == Zone.PLAY and spawned[0].cost == 2)


def c665_echo_debuffs_enemies_until_next_own_turn():
    g = new_game("GIL_665", seed=6651)
    p, e = g.current_player, g.current_player.opponent
    enemies = [summon(e, "CS2_182"), summon(e, "CS2_231")]
    own = summon(p, "CS2_182")
    base = [m.atk for m in enemies]
    own_base = own.atk
    first = play(p, "GIL_665")
    echo = next((c for c in p.hand if c.id == "GIL_665"), None)
    after_first = [m.atk for m in enemies]
    assert echo is not None and after_first == [max(0,a-2) for a in base], (base, after_first, ids(p.hand))
    echo.play()
    after_echo = [m.atk for m in enemies]
    assert after_echo == [max(0,a-4) for a in base], (base, after_echo)
    g.end_turn()
    g.end_turn()
    observed = (f"spells={(first.zone.name,echo.zone.name)};enemy={base}->{after_first}->{after_echo}"
                f"-> {[m.atk for m in enemies]};own={own_base}->{own.atk};hand={ids(p.hand)}")
    return checked(observed, first.zone == Zone.GRAVEYARD and echo.zone == Zone.GRAVEYARD
                   and [m.atk for m in enemies] == base and own.atk == own_base
                   and not p.hand)


def c667_taunt_deathrattle_heals_hero_four():
    g = new_game("GIL_667", seed=6671)
    p = g.current_player
    p.hero.damage = 5
    apple = summon(p, "GIL_667")
    taunt_before = apple.taunt
    apple.destroy()
    observed = f"taunt={taunt_before};apple={apple.zone.name};hero={p.hero.health};armor={p.hero.armor}"
    return checked(observed, taunt_before and apple.zone == Zone.GRAVEYARD and p.hero.health == 29)


def c672_offclass_card_gains_durability_and_lifesteal_heals():
    g = new_game("GIL_672", seed=6721, opponent_class=CardClass.MAGE)
    p, e = g.current_player, g.current_player.opponent
    p.hero.damage = 5
    weapon = play(p, "GIL_672")
    durability_before = weapon.max_durability
    p.hero.attack(e.hero)
    after_attack_health = p.hero.health
    fireball = play(p, "CS2_029", target=e.hero)
    observed = (f"weapon={weapon.id}/{weapon.atk}/{weapon.durability}/{durability_before}->{weapon.max_durability};"
                f"lifesteal_health={after_attack_health};fireball={fireball.zone.name};enemy={e.hero.health}")
    return checked(observed, after_attack_health == 27 and weapon.max_durability == durability_before + 1
                   and fireball.zone == Zone.GRAVEYARD and e.hero.health == 22)


def c672_own_class_card_does_not_gain_durability():
    g = new_game("GIL_672", seed=6722)
    p = g.current_player
    weapon = play(p, "GIL_672")
    durability_before = weapon.max_durability
    poison = play(p, "CS2_074", target=weapon)
    observed = f"weapon={weapon.atk}/{weapon.max_durability};base_max_durability={durability_before};poison={poison.zone.name}"
    return checked(observed, weapon.atk == 4 and weapon.max_durability == durability_before + 0
                   and poison.zone == Zone.GRAVEYARD)


def c677_echo_adds_two_legendary_minions_and_expires():
    g = new_game("GIL_677", seed=6771)
    p = g.current_player
    first = play(p, "GIL_677")
    echo = next((c for c in p.hand if c.id == "GIL_677"), None)
    first_legends = [c for c in p.hand if c.id != "GIL_677" and CardType(c.type) == CardType.MINION and Rarity(c.rarity) == Rarity.LEGENDARY]
    assert echo is not None and len(first_legends) == 1, (ids(p.hand), [(c.id,c.rarity) for c in first_legends])
    echo.play()
    all_legends = [c for c in p.hand if c.id != "GIL_677" and CardType(c.type) == CardType.MINION and Rarity(c.rarity) == Rarity.LEGENDARY]
    assert len(all_legends) == 2, [(c.id,c.rarity,c.zone.name) for c in p.hand]
    after_replay = [c.id for c in all_legends]
    g.end_turn()
    observed = f"first={first.zone.name};legendaries={after_replay};echo_zone={echo.zone.name};hand={ids(p.hand)}"
    return checked(observed, first.zone == Zone.PLAY and echo.zone == Zone.PLAY
                   and not any(c.id == "GIL_677" for c in p.hand))


def c678_echo_summons_second_anglers_and_expires():
    return _echo_minion_two_plays_and_expiry("GIL_678", 6781, 2, 2)


def _echo_minion_two_plays_and_expiry(card_id, seed, atk, health):
    g = new_game(card_id, seed=seed)
    p = g.current_player
    first = play(p, card_id)
    echo = next((c for c in p.hand if c.id == card_id), None)
    assert echo is not None and first.zone == Zone.PLAY and (first.atk,first.health)==(atk,health), (
        first.zone.name,first.atk,first.health,ids(p.hand)
    )
    echo.play()
    second = [m for m in p.field if m.id == card_id]
    assert len(second) == 2, [(m.id,m.zone.name) for m in p.field]
    after_repeat = [(m.id,m.atk,m.health,m.zone.name) for m in second]
    g.end_turn()
    observed = f"plays={(first.zone.name,echo.zone.name)};minions={after_repeat};hand={ids(p.hand)}"
    return checked(observed, len(second)==2 and all((m.atk,m.health)==(atk,health) for m in second)
                   and not any(c.id==card_id for c in p.hand))


def c680_echo_summons_second_sprites_and_expires():
    return _echo_minion_two_plays_and_expiry("GIL_680", 6801, 3, 3)


def c681_amalgam_has_all_eight_tribes():
    g = new_game("GIL_681", seed=6811)
    p = g.current_player
    amalgam = summon(p, "GIL_681")
    races = (Race.ELEMENTAL, Race.MECHANICAL, Race.DEMON, Race.MURLOC,
             Race.DRAGON, Race.BEAST, Race.PIRATE, Race.TOTEM)
    names = [race.name for race in races]
    found = [bool(amalgam.race & race) for race in races]
    observed = f"atk_health={(amalgam.atk,amalgam.health)};race={amalgam.race};all_races={dict(zip(names,found))}"
    return checked(observed, all(found) and (amalgam.atk,amalgam.health)==(3,4))


def c682_battlecry_summons_two_enemy_mucklings_and_rush_works():
    g = new_game("GIL_682", seed=6821)
    p, e = g.current_player, g.current_player.opponent
    target = summon(e, "CS2_182")
    hunter = play(p, "GIL_682")
    tokens = [m for m in e.field if m.id == "GIL_682t"]
    before = [(m.id,m.atk,m.health,m.race.name if hasattr(m.race,'name') else int(m.race)) for m in tokens]
    attack_error = None
    try:
        hunter.attack(target)
    except InvalidAction as exc:
        attack_error = type(exc).__name__
    observed = f"tokens={before};attack_error={attack_error};hunter={hunter.zone.name}/{hunter.damage};target={target.zone.name};enemy_board={len(e.field)}"
    return checked(observed, len(tokens)==2 and all((m.atk,m.health,m.zone)==(2,1,Zone.PLAY) for m in tokens)
                   and attack_error is None and hunter.damage==4 and target.zone==Zone.GRAVEYARD)


def c682_full_enemy_board_blocks_muckling_overflow():
    g = new_game("GIL_682", seed=6822)
    p, e = g.current_player, g.current_player.opponent
    for _ in range(7):
        summon(e, "CS2_231")
    hunter = play(p, "GIL_682")
    observed = f"enemy_count={len(e.field)};enemy_ids={ids(e.field)};hunter={hunter.zone.name}"
    return checked(observed, len(e.field)==7 and not any(m.id=="GIL_682t" for m in e.field)
                   and hunter.zone==Zone.PLAY)


def c683_battlecry_summons_enemy_poisonous_drakeslayer():
    g = new_game("GIL_683", seed=6831)
    p, e = g.current_player, g.current_player.opponent
    target = summon(p, "CS2_182")
    drake = play(p, "GIL_683")
    tokens = [m for m in e.field if m.id=="GIL_683t"]
    token_state = [(m.atk,m.health,m.poisonous,m.zone.name) for m in tokens]
    g.end_turn()
    attack_error = None
    try:
        tokens[0].attack(target)
    except InvalidAction as exc:
        attack_error=type(exc).__name__
    observed = f"drake={drake.zone.name};tokens={token_state};attack_error={attack_error};target={target.zone.name};token_zone={tokens[0].zone.name}"
    return checked(observed, len(tokens)==1 and token_state[0][:3]==(2,1,True)
                   and attack_error is None and target.zone==Zone.GRAVEYARD)


def c683_full_enemy_board_blocks_drakeslayer_overflow():
    g = new_game("GIL_683", seed=6832)
    p, e = g.current_player, g.current_player.opponent
    for _ in range(7):
        summon(e, "CS2_231")
    drake = play(p, "GIL_683")
    observed = f"enemy_count={len(e.field)};enemy_ids={ids(e.field)};drake={drake.zone.name}"
    return checked(observed, len(e.field)==7 and not any(m.id=="GIL_683t" for m in e.field)
                   and drake.zone==Zone.PLAY)


def c685_paragon_gains_taunt_lifesteal_at_three_attack():
    g = new_game("GIL_685", seed=6851)
    p = g.current_player
    paragon = summon(p, "GIL_685")
    before = (paragon.atk,paragon.taunt,paragon.lifesteal)
    buff = play(p, "GIL_145", target=paragon)
    observed = f"before={before};after={(paragon.atk,paragon.taunt,paragon.lifesteal)};buff={buff.zone.name}"
    return checked(observed, before==(2,False,False) and paragon.atk==3
                   and paragon.taunt and paragon.lifesteal and buff.zone==Zone.GRAVEYARD)


def c685_paragon_without_attack_threshold_has_no_keywords():
    g = new_game("GIL_685", seed=6852)
    p = g.current_player
    paragon = summon(p, "GIL_685")
    observed = f"stats={(paragon.atk,paragon.health)};taunt={paragon.taunt};lifesteal={paragon.lifesteal}"
    return checked(observed, paragon.atk==2 and not paragon.taunt and not paragon.lifesteal)


def c687_wanted_coin_only_when_target_dies():
    g = new_game("GIL_687", seed=6871)
    p, e = g.current_player, g.current_player.opponent
    lethal = summon(e, "CS2_231")
    survivor = summon(e, "CS2_182")
    spell = play(p, "GIL_687", target=lethal)
    coin = [c for c in p.hand if c.id=="GAME_005"]
    after_lethal = (lethal.zone.name,survivor.health,survivor.damage,len(coin))
    p.used_mana=0
    second_spell = play(p, "GIL_687", target=survivor)
    coins_after = [c for c in p.hand if c.id=="GAME_005"]
    observed = f"first={spell.zone.name};after_lethal={after_lethal};second={second_spell.zone.name};survivor={(survivor.zone.name,survivor.health,survivor.damage)};coins={len(coins_after)}"
    return checked(observed, lethal.zone==Zone.GRAVEYARD and len(coin)==1 and survivor.zone==Zone.PLAY
                   and survivor.damage==3 and len(coins_after)==1 and second_spell.zone==Zone.GRAVEYARD)


def c691_drawn_minion_copied_but_spell_not():
    g = new_game("GIL_691", seed=6911)
    p = g.current_player
    arugal = summon(p, "GIL_691")
    minion = deck_top(p, "CS2_182")
    drawn = p.draw()
    copies = [c for c in p.hand if c.id==minion.id]
    spell = deck_top(p, "CS2_029")
    spell_drawn = p.draw()
    observed = f"arugal={arugal.zone.name};minion_draw={drawn.zone.name if drawn else None};minion_copies={len(copies)};hand={[(c.id,c.zone.name) for c in p.hand]};spell_draw={spell_drawn.id if spell_drawn else None};deck={ids(p.deck)}"
    return checked(observed, drawn is minion and len(copies)==2 and copies[0] is not copies[1]
                   and arugal.zone==Zone.PLAY and minion.zone==Zone.HAND
                   and spell_drawn is spell and spell.zone==Zone.HAND
                   and len([c for c in p.hand if c.id==minion.id])==2
                   and not any(c.id==spell.id for c in p.hand if c is not spell))


def c691_turn_draw_minion_also_adds_copy():
    g=new_game("GIL_691",seed=6912)
    p=g.current_player
    arugal=summon(p,"GIL_691")
    minion=deck_top(p,"CS2_182")
    g.end_turn()
    g.end_turn()
    copies=[c for c in p.hand if c.id==minion.id]
    observed=f"arugal={arugal.zone.name};turn_draw={minion.zone.name};minion_copies={len(copies)};hand={ids(p.hand)};turn={g.turn};current_is_owner={g.current_player is p}"
    return checked(observed, g.current_player is p and minion.zone==Zone.HAND and len(copies)==2)


def c693_blood_witch_damages_hero_at_own_turn_start():
    g = new_game("GIL_693", seed=6931)
    p = g.current_player
    p.hero.damage=3
    witch = play(p, "GIL_693")
    before=p.hero.health
    g.end_turn()
    g.end_turn()
    observed=f"witch={witch.zone.name};hero={before}->{p.hero.health};damage={p.hero.damage};current_is_owner={g.current_player is p}"
    return checked(observed, witch.zone==Zone.PLAY and p.hero.health==before-1
                   and g.current_player is p)


def c694_prince_liam_transforms_one_cost_cards_only():
    g = new_game("GIL_694", seed=6941)
    p = g.current_player
    one_minion=deck_top(p,"CS2_189")
    one_spell=deck_top(p,"EX1_277")
    other=deck_top(p,"CS2_182")
    before=(one_minion.id,one_minion.cost,one_spell.id,one_spell.cost,other.id,other.cost)
    prince=play(p,"GIL_694")
    transformed=[c for c in p.deck if c is not other]
    after=[(c.id,CardType(c.type).name,Rarity(c.rarity).name,c.cost,c.zone.name) for c in p.deck]
    observed=f"before={before};old_targets={(one_minion.zone.name,one_spell.zone.name)};deck={after}"
    return checked(observed, prince.zone==Zone.PLAY and len(transformed)==2
                   and all(CardType(c.type)==CardType.MINION and Rarity(c.rarity)==Rarity.LEGENDARY for c in transformed)
                   and other in p.deck and other.id==before[4] and other.cost==before[5]
                   and CardType(other.type)==CardType.MINION)


def c696_echo_adds_opponent_class_cards_and_expires():
    g = new_game("GIL_696", seed=6961, opponent_class=CardClass.WARRIOR)
    p = g.current_player
    first=play(p,"GIL_696")
    echo=next((c for c in p.hand if c.id=="GIL_696"),None)
    first_gen=[c for c in p.hand if c.id!="GIL_696"]
    assert echo is not None and len(first_gen)==1 and first_gen[0].card_class==CardClass.WARRIOR, (
        [(c.id,c.card_class.name,c.zone.name) for c in p.hand]
    )
    echo.play()
    generated=[c for c in p.hand if c.id!="GIL_696"]
    assert len(generated)==2 and all(c.card_class==CardClass.WARRIOR for c in generated), (
        [(c.id,c.card_class.name,c.zone.name) for c in p.hand]
    )
    ids_after=[c.id for c in generated]
    g.end_turn()
    observed=f"first={first.zone.name};generated={ids_after};echo={echo.zone.name};hand={ids(p.hand)}"
    return checked(observed, first.zone==Zone.GRAVEYARD and echo.zone==Zone.GRAVEYARD
                   and not any(c.id=="GIL_696" for c in p.hand))


def c800_first_card_each_players_turn_costs_zero_once():
    g = new_game("GIL_800", seed=8001, opponent_class=CardClass.MAGE)
    p, e = g.current_player, g.current_player.opponent
    aviana=play(p,"GIL_800")
    p_first=give(p,"CS2_029")
    p_second=give(p,"CS2_029")
    e_first=give(e,"CS2_182")
    e_second=give(e,"CS2_029")
    g.end_turn()
    e_costs=(e_first.cost,e_second.cost)
    e_before=e.used_mana
    e_first.play()
    e_after_first=e.used_mana
    e_second_cost_after_first=e_second.cost
    e_second.play(target=p.hero)
    e_after_second=e.used_mana
    aviana_after_e=aviana.zone.name
    g.end_turn()
    p_costs=(p_first.cost,p_second.cost)
    p_before=p.used_mana
    p_first.play(target=e.hero)
    p_after_first=p.used_mana
    p_second_cost_after_first=p_second.cost
    p_second.play(target=e.hero)
    p_after_second=p.used_mana
    observed=(f"e_costs={e_costs};e_second_cost_after_first={e_second_cost_after_first};e_mana={e_before}->{e_after_first}->{e_after_second};"
              f"aviana_after_e={aviana_after_e};p_costs={p_costs};p_second_cost_after_first={p_second_cost_after_first};p_mana={p_before}->{p_after_first}->{p_after_second};"
              f"aviana={aviana.zone.name}")
    return checked(observed, e_costs[0]==0 and e_second_cost_after_first==4 and e_after_first==e_before and e_after_second==e_before+4
                   and p_costs[0]==0 and p_second_cost_after_first==4 and p_after_first==p_before and p_after_second==p_before+4
                   and aviana.zone==Zone.PLAY)


def c801_snap_freeze_freezes_then_destroys_already_frozen_minion():
    g = new_game("GIL_801", seed=8011)
    p, e = g.current_player, g.current_player.opponent
    target=summon(e,"CS2_182")
    first=play(p,"GIL_801",target=target)
    after_first=(target.zone.name,target.frozen,target.damage)
    p.used_mana=0
    second=play(p,"GIL_801",target=target)
    observed=f"first={first.zone.name};after_first={after_first};second={second.zone.name};target={target.zone.name};enemy_field={ids(e.field)}"
    return checked(observed, first.zone==Zone.GRAVEYARD and after_first[0]=="PLAY" and after_first[1]
                   and second.zone==Zone.GRAVEYARD and target.zone==Zone.GRAVEYARD)


def c803_militia_commander_rushes_and_attack_bonus_expires():
    g = new_game("GIL_803", seed=8031)
    p,e=g.current_player,g.current_player.opponent
    target=summon(e,"CS2_231")
    commander=play(p,"GIL_803")
    after_play=(commander.atk,commander.health,commander.rush)
    attack_error=None
    try: commander.attack(target)
    except InvalidAction as exc: attack_error=type(exc).__name__
    after_attack=(commander.atk,commander.health,commander.damage,target.zone.name)
    g.end_turn()
    observed=f"after_play={after_play};attack_error={attack_error};after_attack={after_attack};after_eot={(commander.atk,commander.health,commander.damage)}"
    return checked(observed, after_play==(5,5,True) and attack_error is None
                   and target.zone==Zone.GRAVEYARD and commander.zone==Zone.PLAY
                   and commander.atk==2 and commander.health==4)


def c805_deathrattle_summons_deathrattle_minion_from_hand():
    g=new_game("GIL_805",seed=8051)
    p=g.current_player
    egg=give(p,"GIL_816")
    plain=give(p,"CS2_231")
    crasher=summon(p,"GIL_805")
    before=(egg.has_deathrattle,plain.has_deathrattle)
    crasher.destroy()
    observed=f"before={before};crasher={crasher.zone.name};egg={egg.zone.name};plain={plain.zone.name};field={ids(p.field)};hand={ids(p.hand)}"
    return checked(observed, before==(True,False) and crasher.zone==Zone.GRAVEYARD
                   and egg.zone==Zone.PLAY and plain.zone==Zone.HAND)


def c805_no_deathrattle_in_hand_summons_nothing():
    g=new_game("GIL_805",seed=8052)
    p=g.current_player
    plain=give(p,"CS2_231")
    crasher=summon(p,"GIL_805")
    crasher.destroy()
    observed=f"crasher={crasher.zone.name};field={ids(p.field)};plain={plain.zone.name};hand={ids(p.hand)}"
    return checked(observed, crasher.zone==Zone.GRAVEYARD and not p.field and plain.zone==Zone.HAND)


def c807_spell_cast_draws_minion_not_spell():
    g=new_game("GIL_807",seed=8071)
    p,e=g.current_player,g.current_player.opponent
    bog=summon(p,"GIL_807")
    minion=deck_top(p,"CS2_182")
    spell_in_deck=deck_top(p,"CS2_029")
    spell=play(p,"CS2_008",target=e.hero)
    after_spell=(minion.zone.name,spell_in_deck.zone.name,ids(p.hand))
    played_minion=play(p,"CS2_231")
    observed=f"bog={bog.zone.name};spell={spell.zone.name};after_spell={after_spell};played_minion={played_minion.zone.name};deck={ids(p.deck)}"
    return checked(observed, minion.zone==Zone.HAND and spell_in_deck.zone==Zone.DECK
                   and played_minion.zone==Zone.PLAY and bog.zone==Zone.PLAY)


def c809_taunt_redirects_enemy_attack_from_hero():
    g=new_game("GIL_809",seed=8091)
    p,e=g.current_player,g.current_player.opponent
    taunt=summon(p,"GIL_809")
    attacker=summon(e,"CS2_182")
    g.end_turn()
    hero_error=None
    try: attacker.attack(p.hero)
    except InvalidAction as exc: hero_error=type(exc).__name__
    attack_error=None
    try: attacker.attack(taunt)
    except InvalidAction as exc: attack_error=type(exc).__name__
    observed=f"taunt={(taunt.atk,taunt.health,taunt.taunt)};hero_error={hero_error};attack_error={attack_error};target_damage={taunt.damage};attacker={attacker.zone.name}"
    return checked(observed, taunt.taunt and hero_error=="InvalidAction" and attack_error is None
                   and taunt.damage==4 and attacker.zone==Zone.PLAY)


def c813_vivid_nightmare_summons_one_health_copy():
    g=new_game("GIL_813",seed=8131)
    p=g.current_player
    target=summon(p,"CS2_182")
    before=(target.id,target.atk,target.health,target.max_health)
    spell=play(p,"GIL_813",target=target)
    copies=[m for m in p.field if m.id==target.id and m is not target]
    observed=f"before={before};spell={spell.zone.name};source={(target.atk,target.health,target.max_health,target.zone.name)};copies={[(m.atk,m.health,m.max_health,m.zone.name) for m in copies]}"
    return checked(observed, spell.zone==Zone.GRAVEYARD and target.zone==Zone.PLAY
                   and (target.atk,target.health,target.max_health)==before[1:]
                   and len(copies)==1 and copies[0].health==1 and copies[0].max_health==before[3])


def c813_no_friendly_target_rejected_without_payment():
    g=new_game("GIL_813",seed=8132)
    p=g.current_player
    spell=give(p,"GIL_813")
    mana=p.used_mana
    error=None
    try: spell.play()
    except InvalidAction as exc: error=type(exc).__name__
    observed=f"error={error};spell={spell.zone.name};mana={mana}->{p.used_mana};field={ids(p.field)}"
    return checked(observed, error=="InvalidAction" and spell.zone==Zone.HAND
                   and p.used_mana==mana and not p.field)


def c815_battlecry_shuffles_copy_and_keeps_target():
    g=new_game("GIL_815",seed=8151)
    p=g.current_player
    target=summon(p,"CS2_182")
    before=(target.id,target.atk,target.health)
    banker=play(p,"GIL_815",target=target)
    copies=[c for c in p.deck if c.id==target.id]
    observed=f"banker={banker.zone.name};target={(target.id,target.atk,target.health,target.zone.name)};copies={[(c.id,c.atk,c.health,c.zone.name) for c in copies]}"
    return checked(observed, banker.zone==Zone.PLAY and (target.id,target.atk,target.health)==before
                   and len(copies)==1 and copies[0] is not target and (copies[0].atk,copies[0].health)==before[1:])


def c815_no_target_still_resolves_without_shuffling_copy():
    g=new_game("GIL_815",seed=8152)
    p=g.current_player
    banker=play(p,"GIL_815")
    observed=f"banker={banker.zone.name};field={ids(p.field)};deck={ids(p.deck)}"
    return checked(observed, banker.zone==Zone.PLAY and list(p.field)==[banker] and not p.deck)


def c816_deathrattle_adds_dragon_card_to_hand():
    g=new_game("GIL_816",seed=8161)
    p=g.current_player
    egg=summon(p,"GIL_816")
    egg.destroy()
    added=[c for c in p.hand if CardType(c.type)==CardType.MINION and c.race & Race.DRAGON]
    observed=f"egg={egg.zone.name};added={[(c.id,CardClass(c.card_class).name,int(c.race),c.zone.name) for c in p.hand]}"
    return checked(observed, egg.zone==Zone.GRAVEYARD and len(added)==1 and added[0].zone==Zone.HAND)


def c817_healing_after_shield_break_restores_divine_shield():
    g=new_game("GIL_817",seed=8171,opponent_class=CardClass.MAGE)
    p,e=g.current_player,g.current_player.opponent
    glass=summon(p,"GIL_817")
    attacker=summon(e,"CS2_182")
    g.end_turn()
    attacker.attack(glass)
    after_combat=(glass.divine_shield,glass.damage,glass.health)
    chip=play(e,"CS2_008",target=glass)
    after_spell=(glass.divine_shield,glass.damage,glass.health)
    g.end_turn()
    hymn=play(p,"GIL_661")
    observed=f"after_combat={after_combat};chip={chip.zone.name};after_chip={after_spell};hymn={hymn.zone.name};glass={(glass.divine_shield,glass.damage,glass.health)}"
    return checked(observed, after_combat==(False,0,3) and after_spell==(False,1,2)
                   and glass.divine_shield and glass.damage==0 and glass.health==3 and hymn.zone==Zone.GRAVEYARD)


def c820_shudderwock_repeats_multiple_prior_battlecries():
    g=new_game("GIL_820",seed=8201,opponent_class=CardClass.ROGUE)
    p=g.current_player
    target=summon(p,"CS2_182")
    splinter=play(p,"GIL_658",target=target)
    g.end_turn();g.end_turn()
    fox=play(p,"GIL_827")
    g.end_turn();g.end_turn()
    before=(len([c for c in p.hand if CardType(c.type)==CardType.MINION and c.atk==10 and c.max_health==10]),
            len([c for c in p.hand if c.card_class==CardClass.ROGUE and c.id!="GIL_827"]))
    shudder=play(p,"GIL_820")
    copies=[c for c in p.hand if CardType(c.type)==CardType.MINION and c.atk==10 and c.max_health==10]
    rogue_cards=[c for c in p.hand if c.card_class==CardClass.ROGUE and c.id!="GIL_827"]
    observed=f"source_cards={(splinter.zone.name,fox.zone.name)};before={before};shudder={(shudder.zone.name,shudder.atk,shudder.health)};copies={[(c.id,c.atk,c.max_health,c.zone.name) for c in copies]};opponent_class_cards_excluding_copied_fox={[(c.id,c.zone.name) for c in rogue_cards]}"
    return checked(observed, shudder.zone==Zone.PLAY and (shudder.atk,shudder.health)==(6,6)
                   and len(copies)==2 and before[1]==1 and len(rogue_cards)==before[1]+1)


def c825_godfrey_repeats_after_any_minion_dies():
    g=new_game("GIL_825",seed=8251)
    p,e=g.current_player,g.current_player.opponent
    own_small=summon(p,"CS2_231")
    own_large=summon(p,"CS2_182")
    enemy_small=summon(e,"CS2_231")
    enemy_large=summon(e,"CS2_182")
    godfrey=play(p,"GIL_825")
    observed=f"godfrey={(godfrey.atk,godfrey.health,godfrey.damage,godfrey.zone.name)};own_small={own_small.zone.name};enemy_small={enemy_small.zone.name};large_damage={(own_large.damage,enemy_large.damage)}"
    return checked(observed, godfrey.zone==Zone.PLAY and own_small.zone==Zone.GRAVEYARD
                   and enemy_small.zone==Zone.GRAVEYARD and own_large.zone==Zone.PLAY
                   and enemy_large.zone==Zone.PLAY and own_large.damage==4 and enemy_large.damage==4)


def c825_no_death_means_no_repeat():
    g=new_game("GIL_825",seed=8252)
    p,e=g.current_player,g.current_player.opponent
    survivor=summon(e,"CS2_182")
    godfrey=play(p,"GIL_825")
    observed=f"godfrey={godfrey.zone.name};survivor={(survivor.zone.name,survivor.damage,survivor.health)}"
    return checked(observed, godfrey.zone==Zone.PLAY and survivor.zone==Zone.PLAY
                   and survivor.damage==2 and survivor.health==3)


def c827_battlecry_adds_one_opponent_class_card():
    g=new_game("GIL_827",seed=8271,opponent_class=CardClass.WARRIOR)
    p=g.current_player
    fox=play(p,"GIL_827")
    added=[c for c in p.hand if c.card_class==CardClass.WARRIOR]
    observed=f"fox={(fox.zone.name,fox.atk,fox.health)};added={[(c.id,CardClass(c.card_class).name,CardType(c.type).name,c.zone.name) for c in p.hand]}"
    return checked(observed, fox.zone==Zone.PLAY and (fox.atk,fox.health)==(3,3)
                   and len(added)==1 and added[0].zone==Zone.HAND)


def c828_dire_frenzy_buffs_beast_and_shuffles_three_copies():
    g=new_game("GIL_828",seed=8281)
    p=g.current_player
    beast=summon(p,"CS2_237")
    before=(beast.atk,beast.health,beast.race)
    spell=play(p,"GIL_828",target=beast)
    copies=[c for c in p.deck if c.id==beast.id]
    observed=f"before={(before[0],before[1],int(before[2]))};spell={spell.zone.name};beast={(beast.atk,beast.health,beast.zone.name)};copies={[(c.id,c.atk,c.health,int(c.race),c.zone.name) for c in copies]}"
    return checked(observed, before[2] & Race.BEAST and spell.zone==Zone.GRAVEYARD
                   and (beast.atk,beast.health)==(before[0]+3,before[1]+3)
                   and len(copies)==3 and all((c.atk,c.health,c.zone)==(before[0]+3,before[1]+3,Zone.DECK) for c in copies))


def c828_non_beast_target_is_rejected():
    g=new_game("GIL_828",seed=8282)
    p=g.current_player
    nonbeast=summon(p,"CS2_182")
    spell=give(p,"GIL_828")
    mana=p.used_mana
    error=None
    try: spell.play(target=nonbeast)
    except InvalidAction as exc: error=type(exc).__name__
    observed=f"error={error};target={(nonbeast.id,int(nonbeast.race),nonbeast.atk,nonbeast.health)};spell={spell.zone.name};mana={mana}->{p.used_mana};deck={ids(p.deck)}"
    return checked(observed, error=="InvalidAction" and spell.zone==Zone.HAND
                   and p.used_mana==mana and not p.deck and nonbeast.atk==4)


def c833_own_turn_end_draws_one_for_each_player():
    g=new_game("GIL_833",seed=8331)
    p,e=g.current_player,g.current_player.opponent
    own_card=deck_top(p,"CS2_182")
    enemy_card=deck_top(e,"CS2_231")
    guide=summon(p,"GIL_833")
    p_hand_before=len(p.hand);e_hand_before=len(e.hand)
    g.end_turn()
    after_own_end=(own_card.zone.name,enemy_card.zone.name,len(p.hand)-p_hand_before,len(e.hand)-e_hand_before)
    g.end_turn()
    after_enemy_end=(len(p.hand)-p_hand_before,len(e.hand)-e_hand_before)
    observed=f"guide={guide.zone.name};own_end={after_own_end};after_enemy_end={after_enemy_end};deck={(ids(p.deck),ids(e.deck))}"
    return checked(observed, own_card.zone==Zone.HAND and enemy_card.zone==Zone.HAND
                   and after_own_end==("HAND","HAND",1,1) and after_enemy_end==(1,1))


def c835_echo_squashling_repeats_heal_then_expires():
    g=new_game("GIL_835",seed=8351)
    p=g.current_player
    p.hero.damage=5
    first=play(p,"GIL_835",target=p.hero)
    after_first=p.hero.health
    echo=next((c for c in p.hand if c.id=="GIL_835"),None)
    assert echo is not None,(p.hero.health,ids(p.hand))
    echo.play(target=p.hero)
    after_second=p.hero.health
    g.end_turn()
    observed=f"plays={(first.zone.name,echo.zone.name)};health={30-p.hero.damage}->{after_first}->{after_second};field={ids(p.field)};hand={ids(p.hand)}"
    return checked(observed, first.zone==Zone.PLAY and echo.zone==Zone.PLAY
                   and after_first==27 and after_second==29
                   and not any(c.id=="GIL_835" for c in p.hand))


def c836_discover_offers_battlecry_minions():
    g=new_game("GIL_836",seed=8361)
    p=g.current_player
    spell=play(p,"GIL_836")
    choice=p.choice
    assert choice is not None,"Discover choice did not open"
    offered=list(choice.cards)
    offer_state=[(c.id,CardType(c.type).name,bool(c.has_battlecry),c.zone.name) for c in offered]
    assert len(offered)==3 and all(CardType(c.type)==CardType.MINION and c.has_battlecry for c in offered),offer_state
    selected=offered[0]
    choice.choose(selected)
    observed=f"spell={spell.zone.name};offered={offer_state};selected={selected.id}/{selected.zone.name};hand={ids(p.hand)}"
    return checked(observed, spell.zone==Zone.GRAVEYARD and p.choice is None
                   and selected in p.hand and selected.zone==Zone.HAND)


def c840_inner_fire_sets_attack_of_deck_minions_to_health():
    g=new_game("GIL_840",seed=8401)
    p=g.current_player
    minion=deck_top(p,"CS2_182")
    spell_card=deck_top(p,"CS2_029")
    before=(minion.atk,minion.max_health,spell_card.id,spell_card.cost)
    lady=play(p,"GIL_840")
    observed=f"lady={(lady.zone.name,lady.atk,lady.health)};minion={minion.id}/{minion.atk}/{minion.max_health}/{minion.zone.name};spell={spell_card.id}/{spell_card.cost}/{spell_card.zone.name};deck={ids(p.deck)}"
    return checked(observed, lady.zone==Zone.PLAY and minion.zone==Zone.DECK
                   and minion.atk==before[1] and spell_card.zone==Zone.DECK
                   and (spell_card.id,spell_card.cost)==before[2:])


def c902_combo_gives_weapon_plus_one_attack():
    g=new_game("GIL_902",seed=9021)
    p=g.current_player
    weapon=play(p,"CS2_080")
    g.end_turn();g.end_turn()
    coin=play(p,"GAME_005")
    before=(weapon.atk,weapon.durability)
    buccaneer=play(p,"GIL_902")
    observed=f"coin={coin.zone.name};weapon={before}->{(weapon.atk,weapon.durability)};buccaneer={buccaneer.zone.name};played_this_turn={p.cards_played_this_turn}"
    return checked(observed, buccaneer.zone==Zone.PLAY and weapon.atk==before[0]+1
                   and weapon.durability==before[1])


def c902_without_combo_does_not_buff_weapon():
    g=new_game("GIL_902",seed=9022)
    p=g.current_player
    weapon=play(p,"CS2_080")
    g.end_turn();g.end_turn()
    before=(weapon.atk,weapon.durability)
    buccaneer=play(p,"GIL_902")
    observed=f"weapon={before}->{(weapon.atk,weapon.durability)};buccaneer={buccaneer.zone.name};played_this_turn={p.cards_played_this_turn}"
    return checked(observed, buccaneer.zone==Zone.PLAY and (weapon.atk,weapon.durability)==before)


def c903_secret_draws_two_only_after_third_opponent_card():
    g=new_game("GIL_903",seed=9031,opponent_class=CardClass.MAGE)
    p,e=g.current_player,g.current_player.opponent
    first=deck_top(p,"CS2_182");second=deck_top(p,"CS2_231")
    secret=play(p,"GIL_903")
    g.end_turn()
    card1=give(e,"CS2_008");card1.play(target=p.hero)
    card2=give(e,"CS2_008");card2.play(target=p.hero)
    after_two=(secret.zone.name,ids(p.hand),e.cards_played_this_turn)
    card3=give(e,"CS2_231");card3.play()
    after_three=e.cards_played_this_turn
    observed=f"after_two={after_two};third={card3.zone.name};after_three_count={after_three};secret={secret.zone.name};drawn={[(c.id,c.zone.name) for c in p.hand]};deck={ids(p.deck)}"
    return checked(observed, after_two[0]=="SECRET" and not after_two[1]
                   and after_three==3 and secret.zone==Zone.GRAVEYARD and card3.zone==Zone.PLAY
                   and first.zone==Zone.HAND and second.zone==Zone.HAND and len(p.hand)==2 and not p.deck)


def c905_carrion_drake_gains_poisonous_only_after_death():
    g=new_game("GIL_905",seed=9051)
    p,e=g.current_player,g.current_player.opponent
    victim=summon(e,"CS2_231")
    victim.destroy()
    drake=play(p,"GIL_905")
    observed=f"victim={victim.zone.name};drake={(drake.zone.name,drake.poisonous,drake.atk,drake.health)}"
    return checked(observed, victim.zone==Zone.GRAVEYARD and drake.zone==Zone.PLAY and drake.poisonous)


def c905_no_death_this_turn_no_poisonous():
    g=new_game("GIL_905",seed=9052)
    p=g.current_player
    drake=play(p,"GIL_905")
    observed=f"drake={(drake.zone.name,drake.poisonous,drake.atk,drake.health)}"
    return checked(observed, drake.zone==Zone.PLAY and not drake.poisonous)


AUDITS = {
    "GIL_655": [
        ("friendly_minion_attack_gains_one_attack", "After a friendly minion attacks, Festeroot Hulk gains exactly +1 Attack.", c655_friendly_minion_attack_gains_attack),
        ("hero_attack_does_not_trigger", "A hero attack does not trigger Festeroot Hulk's minion-attack effect.", c655_hero_attack_does_not_trigger),
    ],
    "GIL_658": [
        ("battlecry_creates_ten_ten_cost_ten_copy", "Splintergraft adds a separate 10/10 copy of the chosen friendly minion to hand at Cost 10.", c658_copy_target_to_hand),
        ("target_optional_when_no_friendly_minions", "Splintergraft can resolve without a target when no friendly minions exist and creates no copy.", c658_no_friendly_target),
    ],
    "GIL_661": [("heals_all_friendly_characters_up_to_six", "Divine Hymn restores up to 6 Health to every friendly character and does not heal the enemy side.", c661_heals_only_friendly_characters_up_to_maximum)],
    "GIL_663": [("adds_three_two_two_treants_to_hand", "Witchwood Apple adds exactly three 2/2 Treants to hand.", c663_adds_three_treants_to_hand)],
    "GIL_664": [("spell_cast_summons_random_two_cost_minion", "After Vex Crow's controller casts a spell, it summons one random minion with Cost 2.", c664_spell_cast_summons_random_two_cost_minion)],
    "GIL_665": [("echo_repeats_attack_debuff_and_expires", "Curse of Weakness's Echo repeat applies another -2 Attack to enemies; both debuffs expire at the next own turn.", c665_echo_debuffs_enemies_until_next_own_turn)],
    "GIL_667": [("taunt_deathrattle_restores_four_hero_health", "Rotten Applebaum has Taunt and restores 4 Health to its hero when it dies.", c667_taunt_deathrattle_heals_hero_four)],
    "GIL_672": [
        ("offclass_card_increases_durability_and_lifesteal_heals", "Spectral Cutlass heals for damage dealt and gains +1 maximum Durability when its controller plays an off-class card.", c672_offclass_card_gains_durability_and_lifesteal_heals),
        ("own_class_card_does_not_increase_durability", "Playing a Rogue card does not trigger Spectral Cutlass's off-class durability gain.", c672_own_class_card_does_not_gain_durability),
    ],
    "GIL_677": [("echo_adds_two_legendary_minions_then_expires", "Face Collector adds a Legendary minion for each played Echo copy; the unused Echo copy does not persist past turn end.", c677_echo_adds_two_legendary_minions_and_expires)],
    "GIL_678": [("echo_can_be_replayed_and_unused_copy_expires", "Ghost Light Angler's Echo copy can be played again this turn and does not remain after turn end.", c678_echo_summons_second_anglers_and_expires)],
    "GIL_680": [("echo_can_be_replayed_and_unused_copy_expires", "Walnut Sprite's Echo copy can be played again this turn and does not remain after turn end.", c680_echo_summons_second_sprites_and_expires)],
    "GIL_681": [("amalgam_has_all_eight_minion_tribes", "Nightmare Amalgam is an Elemental, Mech, Demon, Murloc, Dragon, Beast, Pirate, and Totem.", c681_amalgam_has_all_eight_tribes)],
    "GIL_682": [
        ("battlecry_summons_two_enemy_mucklings_and_rush_works", "Muck Hunter summons two 2/1 Mucklings for the opponent and can immediately Rush into a minion.", c682_battlecry_summons_two_enemy_mucklings_and_rush_works),
        ("full_enemy_board_blocks_token_overflow", "The two opponent summons respect the seven-minion board limit.", c682_full_enemy_board_blocks_muckling_overflow),
    ],
    "GIL_683": [
        ("battlecry_summons_enemy_poisonous_drakeslayer", "Marsh Drake gives the opponent a 2/1 Poisonous Drakeslayer that kills its combat target.", c683_battlecry_summons_enemy_poisonous_drakeslayer),
        ("full_enemy_board_blocks_token_overflow", "The opponent's board limit prevents an eighth Drakeslayer from being summoned.", c683_full_enemy_board_blocks_drakeslayer_overflow),
    ],
    "GIL_685": [
        ("attack_three_grants_taunt_and_lifesteal", "Paragon of Light has Taunt and Lifesteal at 3 or more Attack.", c685_paragon_gains_taunt_lifesteal_at_three_attack),
        ("below_three_attack_has_no_conditional_keywords", "Paragon of Light has neither conditional keyword below 3 Attack.", c685_paragon_without_attack_threshold_has_no_keywords),
    ],
    "GIL_687": [("damage_coin_only_on_lethal_target", "WANTED! deals 3 damage and grants one Coin only for a target it kills.", c687_wanted_coin_only_when_target_dies)],
    "GIL_691": [
        ("drawn_minion_gets_hand_copy_but_spell_does_not", "Archmage Arugal adds a copy only after a minion draw; a spell draw is not copied.", c691_drawn_minion_copied_but_spell_not),
        ("normal_turn_draw_adds_minion_copy", "A minion drawn at the start of the owner's turn is copied into hand by Archmage Arugal.", c691_turn_draw_minion_also_adds_copy),
    ],
    "GIL_693": [("own_turn_begin_damages_hero_one", "Blood Witch deals 1 damage to its controller's hero at the start of that controller's turn.", c693_blood_witch_damages_hero_at_own_turn_start)],
    "GIL_694": [("transforms_one_cost_deck_cards_to_legendary_minions", "Prince Liam transforms 1-Cost cards in deck, including a spell, into Legendary minions while leaving a non-1-Cost minion unchanged.", c694_prince_liam_transforms_one_cost_cards_only)],
    "GIL_696": [("echo_adds_two_cards_from_opponents_class", "Pick Pocket's Echo copies add cards from the opponent's class; the Echo copy expires at turn end.", c696_echo_adds_opponent_class_cards_and_expires)],
    "GIL_800": [("first_card_on_each_players_turn_costs_zero_once", "Duskfallen Aviana makes each player's first card cost zero, then the next card costs its normal amount, and remains in play.", c800_first_card_each_players_turn_costs_zero_once)],
    "GIL_801": [("first_cast_freezes_second_destroys_frozen_target", "Snap Freeze freezes a minion; casting it again on that already-Frozen minion destroys it.", c801_snap_freeze_freezes_then_destroys_already_frozen_minion)],
    "GIL_803": [("rush_battlecry_attack_bonus_expires_at_turn_end", "Militia Commander gets +3 Attack this turn, can use Rush immediately, and loses the bonus at turn end.", c803_militia_commander_rushes_and_attack_bonus_expires)],
    "GIL_805": [
        ("deathrattle_summons_deathrattle_hand_minion", "Coffin Crasher summons a Deathrattle minion from hand when it dies, leaving a non-Deathrattle minion in hand.", c805_deathrattle_summons_deathrattle_minion_from_hand),
        ("no_deathrattle_hand_minion_summons_nothing", "With no Deathrattle minion in hand, Coffin Crasher summons no minion.", c805_no_deathrattle_in_hand_summons_nothing),
    ],
    "GIL_807": [("spell_cast_draws_minion_only", "Bogshaper draws a minion from the deck when its controller casts a spell and does not draw a spell instead.", c807_spell_cast_draws_minion_not_spell)],
    "GIL_809": [("taunt_prevents_hero_attack_and_takes_combat", "Unpowered Steambot's Taunt prevents an enemy minion from attacking the hero and redirects the attack to it.", c809_taunt_redirects_enemy_attack_from_hero)],
    "GIL_813": [
        ("summons_one_health_friendly_copy", "Vivid Nightmare summons a copy of the chosen friendly minion with 1 Health while leaving the original unchanged.", c813_vivid_nightmare_summons_one_health_copy),
        ("no_target_rejected_without_payment", "Vivid Nightmare cannot be cast without a friendly minion target and does not spend mana.", c813_no_friendly_target_rejected_without_payment),
    ],
    "GIL_815": [
        ("battlecry_shuffles_copy_and_keeps_target", "Baleful Banker shuffles a separate copy of the chosen friendly minion into the deck.", c815_battlecry_shuffles_copy_and_keeps_target),
        ("target_optional_when_no_friendly_minion", "Baleful Banker resolves without a target if there are no friendly minions and adds no copy.", c815_no_target_still_resolves_without_shuffling_copy),
    ],
    "GIL_816": [("deathrattle_adds_dragon_minion_to_hand", "Swamp Dragon Egg adds a Dragon minion to its controller's hand when it dies.", c816_deathrattle_adds_dragon_card_to_hand)],
    "GIL_817": [("healing_after_shield_break_restores_divine_shield", "After The Glass Knight loses Divine Shield, restoring its Health grants Divine Shield again.", c817_healing_after_shield_break_restores_divine_shield)],
    "GIL_820": [("repeats_two_different_prior_battlecries", "Shudderwock repeats both a prior targeted copy Battlecry and a prior opponent-class generation Battlecry.", c820_shudderwock_repeats_multiple_prior_battlecries)],
    "GIL_825": [
        ("repeats_aoe_after_any_minion_dies", "Lord Godfrey repeats its 2-damage Battlecry after the first batch kills minions, damaging surviving minions again.", c825_godfrey_repeats_after_any_minion_dies),
        ("does_not_repeat_when_no_minion_dies", "Lord Godfrey stops after one 2-damage batch if no minion dies.", c825_no_death_means_no_repeat),
    ],
    "GIL_827": [("battlecry_adds_opponent_class_card", "Blink Fox adds exactly one card belonging to the opponent's class.", c827_battlecry_adds_one_opponent_class_card)],
    "GIL_828": [
        ("buffs_beast_and_shuffles_three_buffed_copies", "Dire Frenzy gives a Beast +3/+3 and shuffles three matching +3/+3 copies into the deck.", c828_dire_frenzy_buffs_beast_and_shuffles_three_copies),
        ("non_beast_target_rejected_without_payment", "Dire Frenzy rejects a non-Beast target without spending mana or changing the target.", c828_non_beast_target_is_rejected),
    ],
    "GIL_833": [("own_turn_end_both_players_draw_one", "At its controller's turn end, Forest Guide makes both players draw exactly one card.", c833_own_turn_end_draws_one_for_each_player)],
    "GIL_835": [("echo_battlecry_repeats_two_health_restore", "Squashling restores 2 Health on each Echo play and the unused Echo copy expires at turn end.", c835_echo_squashling_repeats_heal_then_expires)],
    "GIL_836": [("discover_offers_battlecry_minions", "Blazing Invocation offers three Battlecry minions and the chosen one enters hand.", c836_discover_offers_battlecry_minions)],
    "GIL_840": [("inner_fire_sets_all_deck_minions_attack_to_health", "Lady in White sets every deck minion's Attack to its Health and leaves deck spells unchanged.", c840_inner_fire_sets_attack_of_deck_minions_to_health)],
    "GIL_902": [
        ("combo_gives_weapon_one_attack", "Cutthroat Buccaneer gives the equipped weapon +1 Attack when a card was played earlier this turn.", c902_combo_gives_weapon_plus_one_attack),
        ("no_prior_card_means_no_combo_buff", "When Cutthroat Buccaneer is the first card played that turn, the weapon does not gain Attack.", c902_without_combo_does_not_buff_weapon),
    ],
    "GIL_903": [("secret_triggers_on_third_opponent_card_and_draws_two", "Hidden Wisdom stays armed through two opponent card plays, then triggers after the third and draws two cards.", c903_secret_draws_two_only_after_third_opponent_card)],
    "GIL_905": [
        ("recent_minion_death_grants_poisonous", "Carrion Drake gains Poisonous if a minion died earlier in the turn.", c905_carrion_drake_gains_poisonous_only_after_death),
        ("no_minion_death_does_not_grant_poisonous", "Carrion Drake does not gain Poisonous without a minion death that turn.", c905_no_death_this_turn_no_poisonous),
    ],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("limit", nargs="?", type=int, default=41)
    args = parser.parse_args()
    assert 1 <= args.limit <= 41
    active_ids = OWN_IDS[:args.limit]
    statuses = []
    for card_id in active_ids:
        assert card_id in AUDITS, f"missing card audit for {card_id}"
        seen = set()
        for case_id, expected, func in AUDITS[card_id]:
            assert case_id not in seen, f"duplicate case {card_id}/{case_id}"
            seen.add(case_id)
            record(card_id, case_id, expected, func)
        statuses.append(finish_card(card_id))
    from collections import Counter
    print(f"SUMMARY cards={len(statuses)} cases={len(PROBE_ROWS)} {dict(Counter(statuses))}")


if __name__ == "__main__":
    main()
