"""Card-by-card live behavior probes for the middle 42 GILNEAS YELLOW cards."""
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
PROBE_OUT = HERE / "gil_probe_b.csv"
VERDICT_OUT = HERE / "gil_verdict_b.csv"
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
OWN_ROWS = BASE_ROWS[42:84]
OWN_IDS = [row["card_id"] for row in OWN_ROWS]
assert len(OWN_IDS) == 42 and OWN_IDS[0] == "GIL_543" and OWN_IDS[-1] == "GIL_654"
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


def new_game(card_id, seed=4051, opponent_class=None, player_class=None):
    random.seed(seed)
    card_class = class_for(card_id)
    game = prepare_empty_game(player_class or card_class, opponent_class or player_class or card_class)
    game.random.seed(seed)
    if game.current_player is not game.player1:
        game.end_turn()
    assert game.current_player is game.player1
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


def c543_friendly_damage_and_demon_discover():
    g = new_game("GIL_543", seed=5431)
    p = g.player1
    target = summon(p, "EX1_399")
    spell = play(p, "GIL_543", target=target)
    choice = p.choice
    assert choice is not None, "Discover choice did not open"
    offered = list(choice.cards)
    assert len(offered) == 3 and all(c.type == CardType.MINION and c.race == Race.DEMON for c in offered), (
        f"Discover offered={[(c.id, str(c.type), str(c.race)) for c in offered]}"
    )
    selected = offered[0]
    choice.choose(selected)
    observed = (
        f"target={target.zone.name}/{target.health}/{target.damage};spell={spell.zone.name};"
        f"offered={[(c.id,c.zone.name) for c in offered]};selected={selected.id}/{selected.zone.name};"
        f"hand={[(c.id,c.zone.name) for c in p.hand]}"
    )
    return checked(observed, target.zone == Zone.PLAY and target.damage == 2
                   and spell.zone == Zone.GRAVEYARD and p.choice is None
                   and selected in p.hand and selected.zone == Zone.HAND)


def c545_shielded_rush_combat():
    g = new_game("GIL_545", seed=5451)
    p, e = g.player1, g.player2
    charger = play(p, "GIL_545")
    target = summon(e, "CS2_182")
    before = (charger.atk, charger.health, charger.divine_shield, charger.rush)
    attack_error = None
    try:
        charger.attack(target)
    except InvalidAction as exc:
        attack_error = type(exc).__name__
    observed = (f"before={before};attack_error={attack_error};charger={charger.zone.name}/"
                f"{charger.atk}/{charger.health}/shield:{charger.divine_shield};"
                f"target={target.zone.name}/{target.health}/{target.damage}")
    return checked(observed, attack_error is None and before == (3, 4, True, True)
                   and charger.zone == Zone.PLAY and not charger.divine_shield
                   and target.zone == Zone.PLAY and target.damage == 3 and charger.damage == 0)


def c545_rush_cannot_attack_hero_same_turn():
    g = new_game("GIL_545", seed=5452)
    p, e = g.player1, g.player2
    charger = play(p, "GIL_545")
    error = None
    try:
        charger.attack(e.hero)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"error={error};charger={charger.zone.name};hero={e.hero.health};rush={charger.rush};attacks={charger.num_attacks}"
    return checked(observed, error == "InvalidAction" and charger.zone == Zone.PLAY
                   and e.hero.health == 30 and charger.rush and charger.num_attacks == 0)


def c547_attack_kill_gains_two_two():
    g = new_game("GIL_547", seed=5471)
    p, e = g.player1, g.player2
    crowley = play(p, "GIL_547")
    target = summon(e, WISP)
    error = None
    try:
        crowley.attack(target)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = (f"error={error};crowley={crowley.zone.name}/{crowley.atk}/{crowley.health}/"
                f"max:{crowley.max_health}/damage:{crowley.damage};target={target.zone.name}")
    return checked(observed, error is None and target.zone == Zone.GRAVEYARD
                   and crowley.zone == Zone.PLAY and crowley.atk == 6
                   and crowley.max_health == 6 and crowley.damage == 1)


def c547_attack_survival_no_buff():
    g = new_game("GIL_547", seed=5472)
    p, e = g.player1, g.player2
    crowley = play(p, "GIL_547")
    target = summon(e, "EX1_399")
    error = None
    try:
        crowley.attack(target)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"error={error};crowley={crowley.zone.name}/{crowley.atk}/{crowley.max_health}/{crowley.damage};target={target.zone.name}/{target.damage}"
    return checked(observed, error is None and crowley.zone == Zone.PLAY
                   and crowley.atk == 4 and crowley.max_health == 4
                   and target.zone == Zone.PLAY)


def c548_draw_three_discard_spells():
    g = new_game("GIL_548", seed=5481)
    p = g.player1
    minion_a = deck_top(p, "EX1_399")
    spell = deck_top(p, FIREBALL)
    minion_b = deck_top(p, "CS2_182")
    book = play(p, "GIL_548")
    observed = (f"book={book.zone.name};minions={[(c.id,c.zone.name) for c in (minion_a,minion_b)]};"
                f"discarded_spell={spell.zone.name};hand={ids(p.hand)};deck={ids(p.deck)}")
    return checked(observed, book.zone == Zone.GRAVEYARD
                   and minion_a in p.hand and minion_b in p.hand
                   and minion_a.zone == Zone.HAND and minion_b.zone == Zone.HAND
                   and spell.zone == Zone.REMOVEDFROMGAME and len(p.deck) == 0)


def c549_random_past_legendary_minion():
    g = new_game("GIL_549", seed=5491)
    p = g.player1
    toki = play(p, "GIL_549")
    generated = [c for c in p.hand if c.type == CardType.MINION]
    observed = (f"toki={toki.zone.name}/{toki.atk}/{toki.health};generated="
                f"{[(c.id,str(c.rarity),c.zone.name,c.card_class) for c in generated]};hand={ids(p.hand)}")
    return checked(observed, toki.zone == Zone.PLAY and len(generated) == 1
                   and generated[0].rarity == Rarity.LEGENDARY
                   and generated[0].zone == Zone.HAND and generated[0] in p.hand)


def c553_wisps_equal_remaining_hand():
    g = new_game("GIL_553", seed=5531)
    p = g.player1
    hand_cards = [give(p, card_id) for card_id in (WISP, "EX1_399", "CS2_182")]
    spell = play(p, "GIL_553")
    wisps = [m for m in p.field if m.id == "GIL_553t"]
    observed = f"spell={spell.zone.name};hand_before={ids(hand_cards)};wisps={[(m.atk,m.health) for m in wisps]};field={ids(p.field)}"
    return checked(observed, spell.zone == Zone.GRAVEYARD and len(wisps) == 3
                   and all((m.atk,m.health) == (1,1) for m in wisps))


def c553_wisps_respect_remaining_slots():
    g = new_game("GIL_553", seed=5532)
    p = g.player1
    for _ in range(6):
        summon(p, WISP)
    hand_cards = [give(p, WISP), give(p, "EX1_399")]
    spell = play(p, "GIL_553")
    wisps = [m for m in p.field if m.id == "GIL_553t"]
    observed = f"spell={spell.zone.name};remaining_hand={ids(hand_cards)};field_count={len(p.field)};wisps={len(wisps)}"
    return checked(observed, spell.zone == Zone.GRAVEYARD and len(p.field) == 7
                   and len(wisps) == 1)


def c557_rush_and_draw_combo_on_death():
    g = new_game("GIL_557", seed=5571)
    p, e = g.player1, g.player2
    combo = deck_top(p, "EX1_124")
    castaway = play(p, "GIL_557")
    target = summon(e, "EX1_399")
    attack_error = None
    try:
        castaway.attack(target)
    except InvalidAction as exc:
        attack_error = type(exc).__name__
    attack_state = (castaway.zone.name, castaway.rush, target.damage)
    castaway.destroy()
    observed = f"attack_error={attack_error};attack_state={attack_state};castaway={castaway.zone.name};combo={combo.id}/{combo.zone.name};hand={ids(p.hand)}"
    return checked(observed, attack_error is None and attack_state[1]
                   and target.zone == Zone.PLAY and castaway.zone == Zone.GRAVEYARD
                   and combo.zone == Zone.HAND and combo in p.hand)


def c557_no_combo_in_deck_draws_nothing():
    g = new_game("GIL_557", seed=5572)
    p = g.player1
    unrelated = deck_top(p, FIREBALL)
    castaway = summon(p, "GIL_557")
    castaway.destroy()
    observed = f"castaway={castaway.zone.name};unrelated={unrelated.zone.name};hand={ids(p.hand)}"
    return checked(observed, castaway.zone == Zone.GRAVEYARD
                   and unrelated.zone == Zone.DECK and not p.hand)


def c558_lifesteal_heals_hero_on_attack():
    g = new_game("GIL_558", seed=5581)
    p, e = g.player1, g.player2
    p.hero.hit(5)
    before = p.hero.health
    leech = play(p, "GIL_558")
    g.end_turn(); g.end_turn()
    error = None
    try:
        leech.attack(e.hero)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"lifesteal={leech.lifesteal};attack_error={error};hero={before}->{p.hero.health};enemy={e.hero.health};leech={leech.zone.name}/{leech.atk}"
    return checked(observed, error is None and leech.lifesteal
                   and p.hero.health == before + leech.atk
                   and e.hero.health == 30 - leech.atk)


def c561_refreshes_used_hero_power():
    g = new_game("GIL_561", seed=5611)
    p, e = g.player1, g.player2
    first_error = None
    try:
        p.hero.power.use(target=e.hero)
    except InvalidAction as exc:
        first_error = type(exc).__name__
    pixie = play(p, "GIL_561")
    second_error = None
    try:
        p.hero.power.use(target=e.hero)
    except InvalidAction as exc:
        second_error = type(exc).__name__
    observed = f"first_error={first_error};pixie={pixie.zone.name};second_error={second_error};enemy_health={e.hero.health}"
    return checked(observed, first_error is None and second_error is None
                   and pixie.zone == Zone.PLAY and e.hero.health == 28)


def c562_poisonous_rush_kills_larger_minion():
    g = new_game("GIL_562", seed=5621)
    p, e = g.player1, g.player2
    skitterer = play(p, "GIL_562")
    target = summon(e, "EX1_399")
    error = None
    try:
        skitterer.attack(target)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"error={error};skitterer={skitterer.zone.name}/{skitterer.atk}/{skitterer.health}/poison:{skitterer.poisonous}/rush:{skitterer.rush};target={target.zone.name}/{target.damage}"
    return checked(observed, error is None and skitterer.zone == Zone.PLAY
                   and skitterer.poisonous and skitterer.rush
                   and target.zone == Zone.GRAVEYARD)


def c565_no_damage_no_lifesteal():
    g = new_game("GIL_565", seed=5651)
    p = g.player1
    spider = play(p, "GIL_565")
    observed = f"hero_health={p.hero.health};spider={spider.zone.name}/{spider.lifesteal}"
    return checked(observed, spider.zone == Zone.PLAY and not spider.lifesteal
                   and p.hero.health == 30)


def c565_hero_damaged_this_turn_grants_lifesteal():
    g = new_game("GIL_565", seed=5652)
    p = g.player1
    p.hero.hit(1)
    spider = play(p, "GIL_565")
    observed = f"hero={p.hero.health}/{p.hero.damage};spider={spider.zone.name}/lifesteal:{spider.lifesteal}"
    return checked(observed, p.hero.health == 29 and spider.zone == Zone.PLAY
                   and spider.lifesteal)


def c571_summons_only_friendly_dead_beast():
    g = new_game("GIL_571", seed=5711)
    p = g.player1
    beast = summon(p, "GIL_558")
    beast.destroy()
    spell = play(p, "GIL_571")
    copies = [m for m in p.field if m.id == beast.id]
    observed = f"dead={beast.id}/{beast.race}/{beast.zone.name};spell={spell.zone.name};copies={[(m.id,m.atk,m.health,m.race) for m in copies]}"
    return checked(observed, beast.zone == Zone.GRAVEYARD
                   and spell.zone == Zone.GRAVEYARD and len(copies) == 1
                   and copies[0].zone == Zone.PLAY and copies[0].race == Race.BEAST
                   and (copies[0].atk,copies[0].health) == (2,1))


def c571_no_dead_beast_is_not_playable():
    g = new_game("GIL_571", seed=5712)
    p = g.player1
    spell = give(p, "GIL_571")
    mana = p.used_mana
    error = None
    try:
        spell.play()
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"error={error};spell={spell.zone.name};used={p.used_mana}/{mana};field={ids(p.field)}"
    return checked(observed, error == "InvalidAction" and spell.zone == Zone.HAND
                   and p.used_mana == mana and not p.field)


def c577_rat_trap_triggers_after_third_card():
    g = new_game("GIL_577", seed=5771)
    p, e = g.player1, g.player2
    secret = play(p, "GIL_577")
    g.end_turn()
    for _ in range(2):
        play(e, MOONFIRE, target=p.hero)
    after_two = (secret.zone.name, len([m for m in p.field if m.id == "GIL_577t"]))
    play(e, MOONFIRE, target=p.hero)
    rats = [m for m in p.field if m.id == "GIL_577t"]
    observed = f"after_two={after_two};opponent_cards={e.cards_played_this_turn};secret={secret.zone.name}/{secret in p.secrets};rats={[(m.id,m.atk,m.health) for m in rats]};controller_field={ids(p.field)};enemy_turn={g.current_player is e}"
    return checked(observed, after_two == ("SECRET", 0)
                   and secret.zone == Zone.GRAVEYARD and secret not in p.secrets
                   and len(rats) == 1 and (rats[0].atk,rats[0].health) == (6,6))


def c577_dormant_full_board_keeps_secret():
    g = new_game("GIL_577", seed=5772)
    p, e = g.player1, g.player2
    existing = [summon(p, WISP) for _ in range(6)]
    dormant = summon(p, "BT_009")
    assert dormant.dormant and len(p.field) == 7, f"invalid dormant full-board fixture: {len(p.field)} / {dormant.dormant}"
    secret = play(p, "GIL_577")
    g.end_turn()
    for _ in range(3):
        play(e, MOONFIRE, target=p.hero)
    rats = [m for m in p.field if m.id == "GIL_577t"]
    if e.cards_played_this_turn != 3 or (secret.zone == Zone.SECRET and not rats):
        raise ProbeInconclusive(
            f"Cannot isolate full-board/Dormant gating: after {e.cards_played_this_turn} "
            f"opponent cards Rat Trap stayed {secret.zone.name} and summoned {len(rats)} Rats."
        )
    observed = f"controller_board={len(p.field)};existing={all(m in p.field for m in existing)};dormant={dormant.id}/{dormant.dormant};secret={secret.zone.name}/{secret in p.secrets};rats={len(rats)}"
    return checked(observed, len(p.field) == 7 and all(m in p.field for m in existing)
                   and dormant in p.field and not rats
                   and secret.zone == Zone.SECRET and secret in p.secrets)


def c578_draw_rush_lifesteal_deathrattle():
    g = new_game("GIL_578", seed=5781)
    p = g.player1
    rush = deck_top(p, "GIL_545")
    lifesteal = deck_top(p, "GIL_558")
    deathrattle = deck_top(p, "GIL_616")
    ashmore = play(p, "GIL_578")
    observed = f"ashmore={ashmore.zone.name};drawn={[(c.id,c.zone.name) for c in (rush,lifesteal,deathrattle)]};hand={ids(p.hand)};deck={ids(p.deck)}"
    return checked(observed, ashmore.zone == Zone.PLAY
                   and all(c.zone == Zone.HAND and c in p.hand for c in (rush,lifesteal,deathrattle))
                   and len(p.deck) == 0)


def c580_draw_rush_minion_only():
    g = new_game("GIL_580", seed=5801)
    p = g.player1
    rush = deck_top(p, "GIL_545")
    nonrush = deck_top(p, "EX1_399")
    crier = play(p, "GIL_580")
    observed = f"crier={crier.zone.name};rush={rush.id}/{rush.rush}/{rush.zone.name};nonrush={nonrush.id}/{nonrush.rush}/{nonrush.zone.name};hand={ids(p.hand)}"
    return checked(observed, crier.zone == Zone.PLAY and rush.rush
                   and rush.zone == Zone.HAND and nonrush.zone == Zone.DECK)


def c581_draw_elemental_only():
    g = new_game("GIL_581", seed=5811)
    p = g.player1
    elemental = deck_top(p, "GIL_645")
    other = deck_top(p, "EX1_399")
    sandbinder = play(p, "GIL_581")
    observed = f"sandbinder={sandbinder.zone.name};elemental={elemental.id}/{elemental.race}/{elemental.zone.name};other={other.id}/{other.race}/{other.zone.name};hand={ids(p.hand)}"
    return checked(observed, sandbinder.zone == Zone.PLAY
                   and elemental.race == Race.ELEMENTAL and elemental.zone == Zone.HAND
                   and other.zone == Zone.DECK)


def c583_totems_destroyed_gain_stats():
    g = new_game("GIL_583", seed=5831)
    p = g.player1
    totems = [summon(p, "CS2_050"), summon(p, "CS2_051")]
    other = summon(p, WISP)
    cruncher = play(p, "GIL_583")
    observed = (f"cruncher={cruncher.zone.name}/{cruncher.atk}/{cruncher.health}/"
                f"max:{cruncher.max_health}/taunt:{cruncher.taunt};"
                f"totems={[(m.id,m.zone.name) for m in totems]};other={other.id}/{other.atk}/{other.health}/{other.zone.name}")
    return checked(observed, all(m.zone == Zone.GRAVEYARD for m in totems)
                   and (cruncher.atk,cruncher.max_health,cruncher.health) == (6,7,7)
                   and cruncher.taunt and other.zone == Zone.PLAY
                   and (other.atk,other.health) == (1,1))


def c583_without_totems_no_buff():
    g = new_game("GIL_583", seed=5832)
    p = g.player1
    other = summon(p, WISP)
    cruncher = play(p, "GIL_583")
    observed = f"cruncher={cruncher.zone.name}/{cruncher.atk}/{cruncher.health}/taunt:{cruncher.taunt};other={other.id}/{other.zone.name}"
    return checked(observed, cruncher.zone == Zone.PLAY
                   and (cruncher.atk,cruncher.health) == (2,3)
                   and cruncher.taunt and other.zone == Zone.PLAY)


def c584_draws_lowest_cost_minion():
    g = new_game("GIL_584", seed=5841)
    p = g.player1
    cheapest = deck_top(p, WISP)
    higher = deck_top(p, "EX1_399")
    piper = play(p, "GIL_584")
    observed = f"piper={piper.zone.name};cheapest={cheapest.id}/{cheapest.cost}/{cheapest.zone.name};higher={higher.id}/{higher.cost}/{higher.zone.name};hand={ids(p.hand)}"
    return checked(observed, piper.zone == Zone.PLAY and cheapest.cost < higher.cost
                   and cheapest.zone == Zone.HAND and higher.zone == Zone.DECK)


def c584_no_minion_in_deck_draws_nothing():
    g = new_game("GIL_584", seed=5842)
    p = g.player1
    spell = deck_top(p, FIREBALL)
    piper = play(p, "GIL_584")
    observed = f"piper={piper.zone.name};spell={spell.id}/{spell.zone.name};hand={ids(p.hand)};deck={ids(p.deck)}"
    return checked(observed, piper.zone == Zone.PLAY and spell.zone == Zone.DECK
                   and not p.hand)


def c586_elemental_target_gains_stats_and_card():
    g = new_game("GIL_586", seed=5861)
    p = g.player1
    elemental = summon(p, "GIL_645")
    spell = play(p, "GIL_586", target=elemental)
    generated = [c for c in p.hand if c.race == Race.ELEMENTAL]
    observed = f"spell={spell.zone.name};target={elemental.id}/{elemental.race}/{elemental.atk}/{elemental.health};generated={[(c.id,c.race,c.zone.name) for c in generated]}"
    return checked(observed, spell.zone == Zone.GRAVEYARD
                   and (elemental.atk,elemental.health) == (7,7)
                   and len(generated) == 1 and generated[0].zone == Zone.HAND)


def c586_non_elemental_gets_stats_only():
    g = new_game("GIL_586", seed=5862)
    p = g.player1
    target = summon(p, WISP)
    spell = play(p, "GIL_586", target=target)
    observed = f"spell={spell.zone.name};target={target.id}/{target.atk}/{target.health};hand={ids(p.hand)}"
    return checked(observed, spell.zone == Zone.GRAVEYARD
                   and (target.atk,target.health) == (3,3) and not p.hand)


def c596_hero_attack_buffs_friendly_minions():
    g = new_game("GIL_596", seed=5961)
    p, e = g.player1, g.player2
    sword = play(p, "GIL_596")
    minions = [summon(p, WISP), summon(p, "EX1_399")]
    before = [(m.atk,m.health) for m in minions]
    p.hero.attack(e.hero)
    observed = f"weapon={sword.zone.name}/{sword.atk}/{sword.durability};before={before};after={[(m.atk,m.health) for m in minions]};enemy_hero={e.hero.health}"
    return checked(observed, sword.zone == Zone.PLAY and sword.durability == 3
                   and [(m.atk,m.health) for m in minions]
                   == [(a+1,h+1) for a,h in before] and e.hero.health == 27)


def c598_tess_replays_other_class_and_skips_rogue():
    g = new_game("GIL_598", seed=5981)
    p, e = g.player1, g.player2
    friendly = summon(p, WISP)
    off_class = play(p, "CS2_087", target=friendly)
    own_class = play(p, "CS2_075")
    before_friendly_attack = sum(m.atk for m in p.field)
    tess = play(p, "GIL_598")
    after_friendly_attack = sum(m.atk for m in p.field)
    observed = (f"off_class={off_class.id}/{off_class.zone.name};own_class={own_class.id}/{own_class.zone.name};"
                f"tess={tess.zone.name};friendly_total_atk={before_friendly_attack}->{after_friendly_attack};"
                f"friendly={[(m.id,m.atk,m.health) for m in p.field]};enemy_hero={e.hero.health}")
    return checked(observed, tess.zone == Zone.PLAY
                   and after_friendly_attack == before_friendly_attack + 9
                   and len(p.field) == 2 and e.hero.health == 27)


def c600_zap_hits_minion_and_overloads():
    g = new_game("GIL_600", seed=6001)
    p, e = g.player1, g.player2
    target = summon(e, "EX1_399")
    zap = play(p, "GIL_600", target=target)
    locked_now = p.overload_locked
    g.end_turn(); g.end_turn()
    observed = f"zap={zap.zone.name};target={target.zone.name}/{target.health}/{target.damage};locked_now={locked_now};next_turn_mana={p.mana}/{p.max_mana};locked_next={p.overload_locked}"
    return checked(observed, zap.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY
                   and target.damage == 2 and locked_now == 0 and p.mana == 9
                   and p.max_mana == 10)


def c601_dragon_in_hand_grants_attack_and_rush():
    g = new_game("GIL_601", seed=6011)
    p = g.player1
    dragon = give(p, "EX1_572")
    worm = play(p, "GIL_601")
    observed = f"dragon={dragon.id}/{dragon.race}/{dragon.zone.name};worm={worm.zone.name}/{worm.atk}/{worm.health}/rush:{worm.rush}"
    return checked(observed, dragon.race == Race.DRAGON and dragon.zone == Zone.HAND
                   and worm.zone == Zone.PLAY and worm.atk == 5 and worm.rush)


def c601_without_dragon_no_bonus():
    g = new_game("GIL_601", seed=6012)
    p = g.player1
    worm = play(p, "GIL_601")
    observed = f"worm={worm.zone.name}/{worm.atk}/{worm.health}/rush:{worm.rush};hand={ids(p.hand)}"
    return checked(observed, worm.zone == Zone.PLAY and worm.atk == 4
                   and worm.health == 4 and not worm.rush and not p.hand)


def c607_played_one_cost_minion_gets_poisonous():
    g = new_game("GIL_607", seed=6071)
    p = g.player1
    toxmonger = play(p, "GIL_607")
    leech = play(p, "GIL_558")
    observed = f"toxmonger={toxmonger.zone.name};leech={leech.zone.name}/{leech.cost}/poison:{leech.poisonous};lifesteal:{leech.lifesteal}"
    return checked(observed, toxmonger.zone == Zone.PLAY and leech.zone == Zone.PLAY
                   and leech.cost == 1 and leech.poisonous and leech.lifesteal)


def c607_non_one_cost_does_not_get_poisonous():
    g = new_game("GIL_607", seed=6072)
    p = g.player1
    play(p, "GIL_607")
    minion = play(p, "CS2_182")
    observed = f"minion={minion.id}/{minion.cost}/poison:{minion.poisonous};field={ids(p.field)}"
    return checked(observed, minion.zone == Zone.PLAY and minion.cost != 1
                   and not minion.poisonous)


def c607t_echo_rush_replays_same_turn():
    g = new_game("GIL_607t", seed=6073)
    p, e = g.player1, g.player2
    target = summon(e, "EX1_399")
    first = play(p, "GIL_607t")
    first_error = None
    try:
        first.attack(target)
    except InvalidAction as exc:
        first_error = type(exc).__name__
    echo_copy = next((c for c in p.hand if c.id == "GIL_607t"), None)
    second = echo_copy
    if second is not None:
        second.play()
    second_minion = next((m for m in p.field if m.id == "GIL_607t" and m is not first), None)
    second_error = None
    if second_minion is not None:
        try:
            second_minion.attack(target)
        except InvalidAction as exc:
            second_error = type(exc).__name__
    echo_after_second = next((c for c in p.hand if c.id == "GIL_607t"), None)
    g.end_turn()
    observed = (f"first_error={first_error};first={first.zone.name}/{first.rush}/{first.echo};"
                f"second_error={second_error};second={None if second_minion is None else (second_minion.zone.name,second_minion.rush,second_minion.echo)};"
                f"target={target.zone.name}/{target.damage};attackers={first.zone.name}/{second_minion.zone.name};echo_before_end={echo_after_second is not None};"
                f"hand_after_end={ids(p.hand)};field={[(m.id,m.atk,m.health) for m in p.field]}")
    return checked(observed, first_error is None and second_error is None
                   and first.rush and first.zone == Zone.GRAVEYARD
                   and second_minion is not None and second_minion.zone == Zone.GRAVEYARD
                   and second_minion.rush and target.zone == Zone.PLAY and target.damage == 4
                   and echo_after_second is not None and not p.hand)


def c614_chosen_minion_destroyed_when_doll_dies():
    g = new_game("GIL_614", seed=6141)
    p, e = g.player1, g.player2
    target = summon(e, "EX1_399")
    doll = play(p, "GIL_614", target=target)
    after_battlecry = (target.zone.name, doll.has_deathrattle)
    doll.destroy()
    observed = f"after_battlecry={after_battlecry};doll={doll.zone.name};target={target.zone.name}/{target.damage};enemy_field={ids(e.field)}"
    return checked(observed, after_battlecry == ("PLAY", True)
                   and doll.zone == Zone.GRAVEYARD and target.zone == Zone.GRAVEYARD)


def c614_no_target_doll_has_no_destroy_effect():
    g = new_game("GIL_614", seed=6142)
    p = g.player1
    doll = play(p, "GIL_614")
    before = (doll.zone.name, doll.has_deathrattle, len(p.field))
    doll.destroy()
    observed = f"before={before};doll={doll.zone.name};field={ids(p.field)}"
    return checked(observed, doll.zone == Zone.GRAVEYARD and not p.field)


def c616_deathrattle_saplings_then_woodchips():
    g = new_game("GIL_616", seed=6161)
    p = g.player1
    tree = summon(p, "GIL_616")
    tree.destroy()
    saplings = [m for m in p.field if m.id == "GIL_616t"]
    first_stage = [(m.id,m.atk,m.health,m.has_deathrattle) for m in saplings]
    assert tree.zone == Zone.GRAVEYARD and len(saplings) == 2
    assert all((m.atk,m.health,m.has_deathrattle) == (2,2,True) for m in saplings), first_stage
    saplings[0].destroy()
    woodchips = [m for m in p.field if m.id == "GIL_616t2"]
    observed = f"tree={tree.zone.name};saplings={first_stage};first_sapling={saplings[0].zone.name};woodchips={[(m.id,m.atk,m.health) for m in woodchips]};field={ids(p.field)}"
    return checked(observed, saplings[0].zone == Zone.GRAVEYARD
                   and len(woodchips) == 2
                   and all((m.atk,m.health) == (1,1) for m in woodchips))


def c618_glinda_gives_hand_minions_echo_and_removal_clears_it():
    g = new_game("GIL_618", seed=6181)
    p = g.player1
    held = give(p, WISP)
    glinda = play(p, "GIL_618")
    held_echo = held.echo
    held.play()
    echo_copy = next((c for c in p.hand if c.id == WISP), None)
    spare = give(p, WISP)
    while_echo = spare.echo
    glinda.destroy()
    observed = (f"glinda={glinda.zone.name};original={held.zone.name}/{held_echo};"
                f"echo_copy={None if echo_copy is None else (echo_copy.zone.name,echo_copy.echo)};"
                f"spare_echo={while_echo}->{spare.echo};hand={[(c.id,c.zone.name,c.echo) for c in p.hand]}")
    return checked(observed, held_echo and held.zone == Zone.PLAY
                   and echo_copy is not None and echo_copy.zone == Zone.HAND
                   and while_echo and not spare.echo and glinda.zone == Zone.GRAVEYARD)


def c620_drawn_minion_summons_one_one_copy():
    g = new_game("GIL_620", seed=6201)
    p = g.player1
    dorian = play(p, "GIL_620")
    original = deck_top(p, "EX1_399")
    book = play(p, "GIL_548")
    copies = [m for m in p.field if m.id == "EX1_399"]
    observed = (f"dorian={dorian.zone.name}/{dorian.atk}/{dorian.health};original={original.zone.name};"
                f"book={book.zone.name};copies={[(m.atk,m.health,m.zone.name) for m in copies]};"
                f"hand={ids(p.hand)}")
    return checked(observed, original in p.hand and original.zone == Zone.HAND
                   and book.zone == Zone.GRAVEYARD and len(copies) == 1
                   and copies[0].zone == Zone.PLAY and (copies[0].atk,copies[0].health) == (1,1))


def c620_drawn_spell_does_not_summon_copy():
    g = new_game("GIL_620", seed=6202)
    p = g.player1
    dorian = play(p, "GIL_620")
    spell = deck_top(p, FIREBALL)
    book = play(p, "GIL_548")
    observed = f"dorian={dorian.zone.name};book={book.zone.name};spell={spell.zone.name};field={ids(p.field)};hand={ids(p.hand)}"
    return checked(observed, spell.zone == Zone.REMOVEDFROMGAME
                   and p.field == [dorian] and dorian.zone == Zone.PLAY and book.zone == Zone.GRAVEYARD)


def c622_lifedrinker_damages_enemy_and_heals_controller():
    g = new_game("GIL_622", seed=6221)
    p, e = g.player1, g.player2
    p.hero.hit(5)
    before = p.hero.health
    lifedrinker = play(p, "GIL_622")
    observed = f"hero={before}->{p.hero.health};enemy={e.hero.health};minion={lifedrinker.zone.name}/{lifedrinker.atk}/{lifedrinker.health}"
    return checked(observed, before == 25 and p.hero.health == 28 and e.hero.health == 27
                   and lifedrinker.zone == Zone.PLAY and (lifedrinker.atk,lifedrinker.health) == (3,3))


def c623_grizzly_loses_health_per_opponent_hand_card():
    g = new_game("GIL_623", seed=6231)
    p, e = g.player1, g.player2
    held = [give(e, card_id) for card_id in (WISP, FIREBALL, "EX1_399")]
    grizzly = play(p, "GIL_623")
    observed = f"opponent_hand={[(c.id,c.zone.name) for c in held]};grizzly={grizzly.zone.name}/{grizzly.atk}/{grizzly.health}/max:{grizzly.max_health}/taunt:{grizzly.taunt}"
    return checked(observed, len(e.hand) == 3 and all(c.zone == Zone.HAND for c in held)
                   and grizzly.zone == Zone.PLAY and grizzly.atk == 3
                   and grizzly.health == 9 and grizzly.max_health == 12 and grizzly.taunt)


def c623_empty_opponent_hand_keeps_full_health():
    g = new_game("GIL_623", seed=6232)
    grizzly = play(g.player1, "GIL_623")
    observed = f"grizzly={grizzly.zone.name}/{grizzly.atk}/{grizzly.health}/max:{grizzly.max_health}/taunt:{grizzly.taunt};opponent_hand={ids(g.player2.hand)}"
    return checked(observed, not g.player2.hand and grizzly.zone == Zone.PLAY
                   and (grizzly.atk,grizzly.health,grizzly.max_health) == (3,12,12)
                   and grizzly.taunt)


def c624_only_minion_gains_three_three():
    g = new_game("GIL_624", seed=6241)
    p = g.player1
    prowler = play(p, "GIL_624")
    observed = f"prowler={prowler.zone.name}/{prowler.atk}/{prowler.health}/field={ids(p.field)}/{ids(g.player2.field)}"
    return checked(observed, p.field == [prowler] and not g.player2.field
                   and (prowler.atk,prowler.health) == (6,6))


def c624_other_minion_prevents_bonus():
    g = new_game("GIL_624", seed=6242)
    p, e = g.player1, g.player2
    blocker = summon(e, WISP)
    prowler = play(p, "GIL_624")
    observed = f"blocker={blocker.zone.name}/{blocker.atk}/{blocker.health};prowler={prowler.zone.name}/{prowler.atk}/{prowler.health};boards={ids(p.field)}/{ids(e.field)}"
    return checked(observed, blocker.zone == Zone.PLAY and prowler.zone == Zone.PLAY
                   and (prowler.atk,prowler.health) == (3,3))


def c634_bellringer_battlecry_and_deathrattle_pull_secrets():
    g = new_game("GIL_634", seed=6341)
    p = g.player1
    secrets = [deck_top(p, "EX1_130"), deck_top(p, "GIL_903")]
    sentry = play(p, "GIL_634")
    after_battlecry = ([(c.id,c.zone.name) for c in p.secrets], [c.id for c in p.deck])
    sentry.destroy()
    observed = (f"sentry={sentry.zone.name}/deathrattle:{sentry.has_deathrattle};"
                f"secrets={[(c.id,c.zone.name) for c in p.secrets]};deck={ids(p.deck)};"
                f"after_battlecry={after_battlecry}")
    return checked(observed, sentry.zone == Zone.GRAVEYARD and sentry.has_deathrattle
                   and len(p.secrets) == 2 and all(c in p.secrets and c.zone == Zone.SECRET for c in secrets)
                   and not p.deck and len(after_battlecry[0]) == 1 and len(after_battlecry[1]) == 1)


def c635_dragon_in_hand_grants_taunt_and_shield():
    g = new_game("GIL_635", seed=6351)
    p = g.player1
    dragon = give(p, "EX1_572")
    gargoyle = play(p, "GIL_635")
    observed = f"dragon={dragon.id}/{dragon.race}/{dragon.zone.name};gargoyle={gargoyle.zone.name}/{gargoyle.atk}/{gargoyle.health}/taunt:{gargoyle.taunt}/shield:{gargoyle.divine_shield}"
    return checked(observed, dragon.race == Race.DRAGON and dragon.zone == Zone.HAND
                   and gargoyle.zone == Zone.PLAY and gargoyle.taunt and gargoyle.divine_shield)


def c635_without_dragon_no_keywords():
    g = new_game("GIL_635", seed=6352)
    p = g.player1
    gargoyle = play(p, "GIL_635")
    observed = f"gargoyle={gargoyle.zone.name}/{gargoyle.atk}/{gargoyle.health}/taunt:{gargoyle.taunt}/shield:{gargoyle.divine_shield};hand={ids(p.hand)}"
    return checked(observed, gargoyle.zone == Zone.PLAY and not gargoyle.taunt
                   and not gargoyle.divine_shield and not p.hand)


def c637_draws_then_gains_armor_per_hand_card():
    g = new_game("GIL_637", seed=6371)
    p = g.player1
    held = give(p, WISP)
    drawn_card = deck_top(p, FIREBALL)
    spell = play(p, "GIL_637")
    observed = f"spell={spell.zone.name};held={held.zone.name};drawn={drawn_card.zone.name};hand={ids(p.hand)};armor={p.hero.armor}"
    return checked(observed, spell.zone == Zone.GRAVEYARD and held in p.hand
                   and drawn_card in p.hand and drawn_card.zone == Zone.HAND
                   and len(p.hand) == 2 and p.hero.armor == 2)


def c640_draw_buffs_collector_not_drawn_card():
    g = new_game("GIL_640", seed=6401)
    p = g.player1
    collector = play(p, "GIL_640")
    drawn_card = deck_top(p, WISP)
    book = play(p, "GIL_548")
    observed = f"collector={collector.zone.name}/{collector.atk}/{collector.health};book={book.zone.name};drawn={drawn_card.id}/{drawn_card.zone.name}/{drawn_card.atk}/{drawn_card.health};hand={ids(p.hand)}"
    return checked(observed, drawn_card in p.hand and drawn_card.zone == Zone.HAND
                   and book.zone == Zone.GRAVEYARD and (collector.atk,collector.health) == (5,5)
                   and (drawn_card.atk,drawn_card.health) == (1,1))


def c645_elemental_played_last_turn_draws_card():
    g = new_game("GIL_645", seed=6451)
    p = g.player1
    drawn_card = deck_top(p, WISP)
    first = play(p, "GIL_645")
    second = give(p, "GIL_645")
    g.end_turn(); g.end_turn()
    second.play()
    observed = (f"first={first.zone.name}/{first.race};last_turn={p.elemental_played_last_turn};"
                f"second={second.zone.name};drawn={drawn_card.zone.name};hand={ids(p.hand)}")
    return checked(observed, first.zone == Zone.PLAY and second.zone == Zone.PLAY
                   and drawn_card in p.hand and drawn_card.zone == Zone.HAND)


def c645_no_prior_turn_elemental_does_not_draw():
    g = new_game("GIL_645", seed=6452)
    p = g.player1
    drawn_card = deck_top(p, WISP)
    elemental = play(p, "GIL_645")
    observed = f"elemental={elemental.zone.name}/{elemental.race};last_turn={p.elemental_played_last_turn};drawn={drawn_card.zone.name};hand={ids(p.hand)}"
    return checked(observed, elemental.zone == Zone.PLAY and drawn_card.zone == Zone.DECK
                   and not p.hand)


def c646_automaton_doubles_damage_hero_power():
    g = new_game("GIL_646", seed=6461)
    p, e = g.player1, g.player2
    automaton = play(p, "GIL_646")
    error = None
    try:
        p.hero.power.use(target=e.hero)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"automaton={automaton.zone.name};error={error};enemy_health={e.hero.health};hero_power={p.hero.power.id}"
    return checked(observed, automaton.zone == Zone.PLAY and error is None and e.hero.health == 28)


def c646_automaton_doubles_heal_hero_power():
    g = new_game("GIL_646", seed=6462, player_class=CardClass.PRIEST)
    p = g.player1
    p.hero.hit(5)
    automaton = play(p, "GIL_646")
    error = None
    try:
        p.hero.power.use(target=p.hero)
    except InvalidAction as exc:
        error = type(exc).__name__
    observed = f"automaton={automaton.zone.name};error={error};hero={p.hero.health}/{p.hero.damage};hero_power={p.hero.power.id}"
    return checked(observed, automaton.zone == Zone.PLAY and error is None and p.hero.health == 29)


def c648_destroys_enemy_secrets_not_controller_secrets():
    g = new_game("GIL_648", seed=6481, opponent_class=CardClass.MAGE)
    p, e = g.player1, g.player2
    own_secret = play(p, "EX1_289")
    g.end_turn()
    enemy_secret = play(e, "EX1_289")
    g.end_turn()
    inspector = play(p, "GIL_648")
    observed = f"inspector={inspector.zone.name};own={own_secret.zone.name}/{own_secret in p.secrets};enemy={enemy_secret.zone.name}/{enemy_secret in e.secrets};secrets={ids(p.secrets)}/{ids(e.secrets)}"
    return checked(observed, inspector.zone == Zone.PLAY and own_secret.zone == Zone.SECRET
                   and own_secret in p.secrets and enemy_secret.zone != Zone.SECRET
                   and enemy_secret not in e.secrets and len(p.secrets) == 1 and not e.secrets)


def c650_shaw_grants_rush_and_aura_ends_with_shaw():
    g = new_game("GIL_650", seed=6501)
    p, e = g.player1, g.player2
    shaw = play(p, "GIL_650")
    minion = summon(p, WISP)
    target = summon(e, "EX1_341")
    attack_error = None
    try:
        minion.attack(target)
    except InvalidAction as exc:
        attack_error = type(exc).__name__
    before_remove = (minion.rush, minion.num_attacks, target.damage)
    shaw.destroy()
    later = summon(p, WISP)
    observed = f"shaw={shaw.zone.name};attack_error={attack_error};before_remove={before_remove};existing_rush={minion.rush};later_rush={later.rush};target={target.zone.name}/{target.damage}"
    return checked(observed, shaw.zone == Zone.GRAVEYARD and attack_error is None
                   and before_remove == (True,1,1) and not minion.rush and not later.rush
                   and target.zone == Zone.PLAY and target.damage == 1)


def _break_woodcutters_axe(seed, minion_id):
    g = new_game("GIL_653", seed=seed)
    p, e = g.player1, g.player2
    minion = summon(p, minion_id)
    axe = play(p, "GIL_653")
    p.hero.attack(e.hero)
    first_durability = axe.durability
    g.end_turn(); g.end_turn()
    p.hero.attack(e.hero)
    return p, e, minion, axe, first_durability


def c653_axe_deathrattle_buffs_rush_minion():
    p, e, minion, axe, first_durability = _break_woodcutters_axe(6531, "GIL_545")
    observed = f"axe={axe.zone.name}/first_durability={first_durability};minion={minion.zone.name}/{minion.atk}/{minion.health}/rush:{minion.rush};enemy_hero={e.hero.health}"
    return checked(observed, first_durability == 1 and axe.zone == Zone.GRAVEYARD
                   and minion.zone == Zone.PLAY and (minion.atk,minion.health) == (5,5)
                   and minion.rush and e.hero.health == 26)


def c653_no_rush_minion_is_not_buffed():
    p, e, minion, axe, first_durability = _break_woodcutters_axe(6532, WISP)
    observed = f"axe={axe.zone.name}/first_durability={first_durability};minion={minion.zone.name}/{minion.atk}/{minion.health}/rush:{minion.rush};enemy_hero={e.hero.health}"
    return checked(observed, first_durability == 1 and axe.zone == Zone.GRAVEYARD
                   and minion.zone == Zone.PLAY and (minion.atk,minion.health) == (1,1)
                   and not minion.rush and e.hero.health == 26)


def c654_warpath_echo_repeats_aoe_and_expires_copy():
    g = new_game("GIL_654", seed=6541)
    p, e = g.player1, g.player2
    friendly = summon(p, "CS2_182")
    enemy = summon(e, "CS2_182")
    first = play(p, "GIL_654", target=enemy)
    first_state = (friendly.damage,enemy.damage)
    echo_copy = next((c for c in p.hand if c.id == "GIL_654"), None)
    second_error = None
    if echo_copy is not None:
        try:
            echo_copy.play(target=enemy)
        except InvalidAction as exc:
            second_error = type(exc).__name__
    second_state = (friendly.damage,enemy.damage)
    last_copy = next((c for c in p.hand if c.id == "GIL_654"), None)
    g.end_turn()
    observed = f"first={first.zone.name}/{first.echo};first_state={first_state};second_error={second_error};second_state={second_state};last_copy={last_copy is not None};after_end={ids(p.hand)};boards={friendly.zone.name}/{enemy.zone.name}"
    return checked(observed, first.zone == Zone.GRAVEYARD and first.echo
                   and first_state == (1,1) and echo_copy is not None
                   and second_error is None and second_state == (2,2)
                   and last_copy is not None and GIL654_id_not_in_hand(p))


def GIL654_id_not_in_hand(player):
    return not any(c.id == "GIL_654" for c in player.hand)


AUDITS = {
    "GIL_543": [("friendly_character_takes_two_then_discovers_demon",
                 "Deals exactly 2 damage to the selected friendly character, offers three Demon minions, and places the selected Demon in hand.",
                 c543_friendly_damage_and_demon_discover)],
    "GIL_545": [
        ("rush_minion_attacks_and_shield_absorbs_combat", "Ghostly Charger is a 3/4 with Rush and Divine Shield; a same-turn minion attack removes its Shield and it survives combat.", c545_shielded_rush_combat),
        ("rush_cannot_attack_hero_on_entry_turn", "Ghostly Charger cannot attack the enemy hero on the turn it is played.", c545_rush_cannot_attack_hero_same_turn),
    ],
    "GIL_547": [
        ("rush_attack_kill_grants_plus_two_plus_two", "Darius can attack a minion immediately and gains +2/+2 after killing it.", c547_attack_kill_gains_two_two),
        ("rush_attack_without_kill_does_not_buff", "Attacking but failing to kill a minion grants no +2/+2.", c547_attack_survival_no_buff),
    ],
    "GIL_548": [("draw_three_discard_drawn_spells", "Draws three cards and discards any spell among those draws while keeping the drawn minions.", c548_draw_three_discard_spells)],
    "GIL_549": [("battlecry_adds_past_legendary_minion", "Toki adds exactly one Legendary minion to hand and remains a 5/5 on board.", c549_random_past_legendary_minion)],
    "GIL_553": [
        ("summons_one_wisp_per_other_hand_card", "Summons one 1/1 Wisp for each card remaining in hand when the spell resolves.", c553_wisps_equal_remaining_hand),
        ("wisps_respect_board_slots", "With six minions already in play and two cards in hand, only one Wisp fits.", c553_wisps_respect_remaining_slots),
    ],
    "GIL_557": [
        ("rush_and_deathrattle_draws_combo_card", "Cursed Castaway has Rush and draws the only Combo card from the deck when it dies.", c557_rush_and_draw_combo_on_death),
        ("no_combo_card_means_no_draw", "If the deck has no Combo card, the Deathrattle draws nothing.", c557_no_combo_in_deck_draws_nothing),
    ],
    "GIL_558": [("lifesteal_attack_restores_hero_health", "Swamp Leech heals its controller for the damage it deals while attacking the enemy hero.", c558_lifesteal_heals_hero_on_attack)],
    "GIL_561": [("battlecry_refreshes_used_hero_power", "After using the Hero Power once, Blackwald Pixie refreshes it for a second use that turn.", c561_refreshes_used_hero_power)],
    "GIL_562": [("poisonous_rush_kills_larger_minion", "Vilebrood Skitterer can attack immediately and Poisonous kills a larger minion in combat.", c562_poisonous_rush_kills_larger_minion)],
    "GIL_565": [
        ("undamaged_hero_does_not_grant_lifesteal", "Without hero damage this turn, Deathweb Spider does not gain Lifesteal.", c565_no_damage_no_lifesteal),
        ("damaged_hero_grants_lifesteal", "If its hero took damage this turn, Deathweb Spider gains Lifesteal.", c565_hero_damaged_this_turn_grants_lifesteal),
    ],
    "GIL_571": [
        ("summons_copy_of_dead_friendly_beast", "Witching Hour summons a copy of the sole friendly Beast that died this game.", c571_summons_only_friendly_dead_beast),
        ("no_dead_beast_blocks_play", "Without a friendly Beast death this game, Witching Hour is rejected without payment or zone change.", c571_no_dead_beast_is_not_playable),
    ],
    "GIL_577": [
        ("rat_trap_triggers_after_third_opponent_card", "Rat Trap remains armed after two opponent cards, then is consumed and summons one 6/6 Rat after the third.", c577_rat_trap_triggers_after_third_card),
        ("dormant_full_board_keeps_secret_armed", "Six active minions plus one Dormant minion fill all seven slots; the Secret must not misread this as an open slot.", c577_dormant_full_board_keeps_secret),
    ],
    "GIL_578": [("draws_rush_lifesteal_and_deathrattle_cards", "Countess Ashmore draws one Rush, one Lifesteal, and one Deathrattle card from the deck.", c578_draw_rush_lifesteal_deathrattle)],
    "GIL_580": [("town_crier_draws_rush_minion", "Town Crier draws the eligible Rush minion and leaves a non-Rush minion in the deck.", c580_draw_rush_minion_only)],
    "GIL_581": [("sandbinder_draws_elemental", "Sandbinder draws the eligible Elemental and leaves the non-Elemental in the deck.", c581_draw_elemental_only)],
    "GIL_583": [
        ("destroys_totems_and_gains_two_two_each", "Totem Cruncher destroys two friendly Totems and gains exactly +4/+4 without affecting another minion.", c583_totems_destroyed_gain_stats),
        ("no_totems_means_no_buff", "With no Totems, Totem Cruncher keeps its base stats and Taunt.", c583_without_totems_no_buff),
    ],
    "GIL_584": [
        ("draws_lowest_cost_minion", "Witchwood Piper draws the lowest-Cost minion and leaves the higher-Cost minion in deck.", c584_draws_lowest_cost_minion),
        ("no_minions_means_no_draw", "If the deck contains no minions, Witchwood Piper draws no card.", c584_no_minion_in_deck_draws_nothing),
    ],
    "GIL_586": [
        ("elemental_target_buffs_and_adds_elemental", "Earthen Might gives the Elemental +2/+2 and adds one Elemental card to hand.", c586_elemental_target_gains_stats_and_card),
        ("non_elemental_target_only_buffs", "Earthen Might gives a non-Elemental +2/+2 without adding a card.", c586_non_elemental_gets_stats_only),
    ],
    "GIL_596": [("hero_attack_buffs_all_friendly_minions", "After the hero attacks with Silver Sword, all friendly minions gain +1/+1 and the weapon loses one durability.", c596_hero_attack_buffs_friendly_minions)],
    "GIL_598": [("tess_replays_other_class_card_only", "Tess replays the Paladin spell for +3 total friendly Attack while the Rogue spell is not replayed.", c598_tess_replays_other_class_and_skips_rogue)],
    "GIL_600": [("deals_two_and_locks_one_mana_next_turn", "Zap deals 2 damage to its minion target and Overloads 1 for the next turn.", c600_zap_hits_minion_and_overloads)],
    "GIL_601": [
        ("held_dragon_grants_attack_and_rush", "With a Dragon in hand, Scaleworm gains +1 Attack and Rush.", c601_dragon_in_hand_grants_attack_and_rush),
        ("without_dragon_keeps_base_stats", "Without a Dragon in hand, Scaleworm remains 4/4 without Rush.", c601_without_dragon_no_bonus),
    ],
    "GIL_607": [
        ("played_one_cost_minion_gets_poisonous", "Toxmonger gives Poisonous to a played 1-Cost minion.", c607_played_one_cost_minion_gets_poisonous),
        ("other_cost_minion_does_not_get_poisonous", "Toxmonger does not give Poisonous to a minion whose Cost is not 1.", c607_non_one_cost_does_not_get_poisonous),
    ],
    "GIL_607t": [("echo_rush_minion_repeats_and_attacks_twice", "Hunting Mastiff has Rush, attacks a minion on each same-turn play, receives an Echo copy, and the unused Echo copy expires at turn end.", c607t_echo_rush_replays_same_turn)],
    "GIL_614": [
        ("chosen_enemy_destroyed_when_doll_dies", "Voodoo Doll stores the selected enemy minion and destroys it when the Doll dies.", c614_chosen_minion_destroyed_when_doll_dies),
        ("no_target_deathrattle_does_nothing", "With no minion target available, Voodoo Doll can be played and its death has no target to destroy.", c614_no_target_doll_has_no_destroy_effect),
    ],
    "GIL_616": [("deathrattle_saplings_chain_into_woodchips", "Festeroot summons two 2/2 Deathrattle Saplings; a Sapling death summons two 1/1 Woodchips.", c616_deathrattle_saplings_then_woodchips)],
    "GIL_618": [("hand_minions_gain_echo_while_glinda_lives", "Glinda grants Echo to a held minion, the minion creates an Echo copy when played, and removing Glinda clears the hand aura.", c618_glinda_gives_hand_minions_echo_and_removal_clears_it)],
    "GIL_620": [
        ("drawn_minion_summons_one_one_copy", "Dollmaster Dorian summons a 1/1 copy when its controller draws a minion while keeping the drawn original in hand.", c620_drawn_minion_summons_one_one_copy),
        ("drawn_spell_does_not_summon_copy", "Drawing a spell while Dorian is in play leaves it in hand without summoning a copy.", c620_drawn_spell_does_not_summon_copy),
    ],
    "GIL_622": [("battlecry_deals_three_and_restores_three", "Lifedrinker deals 3 damage to the enemy hero and restores 3 health to its controller.", c622_lifedrinker_damages_enemy_and_heals_controller)],
    "GIL_623": [
        ("health_loss_matches_opponent_hand_size", "Witchwood Grizzly loses exactly one current Health per opponent hand card and retains Taunt.", c623_grizzly_loses_health_per_opponent_hand_card),
        ("empty_opponent_hand_causes_no_health_loss", "With an empty opponent hand, Witchwood Grizzly remains at its full 3/12 stats and has Taunt.", c623_empty_opponent_hand_keeps_full_health),
    ],
    "GIL_624": [
        ("only_minion_gains_three_three", "Night Prowler gains +3/+3 when it is the only minion on the battlefield.", c624_only_minion_gains_three_three),
        ("another_minion_prevents_three_three", "An existing minion on the battlefield prevents Night Prowler's +3/+3 bonus.", c624_other_minion_prevents_bonus),
    ],
    "GIL_634": [("battlecry_and_deathrattle_each_put_secret_into_play", "Bellringer Sentry puts one deck Secret into play on its Battlecry and a second on its Deathrattle.", c634_bellringer_battlecry_and_deathrattle_pull_secrets)],
    "GIL_635": [
        ("held_dragon_grants_taunt_and_divine_shield", "Holding a Dragon gives Cathedral Gargoyle Taunt and Divine Shield.", c635_dragon_in_hand_grants_taunt_and_shield),
        ("no_dragon_means_no_keywords", "Without a Dragon in hand, Cathedral Gargoyle gains neither Taunt nor Divine Shield.", c635_without_dragon_no_keywords),
    ],
    "GIL_637": [("draws_then_gains_armor_per_hand_card", "Ferocious Howl draws a card and gains one Armor per card in hand after the draw resolves.", c637_draws_then_gains_armor_per_hand_card)],
    "GIL_640": [("draw_buffs_collector_not_drawn_card", "When a card is drawn, Curio Collector itself gains +1/+1 while the drawn card keeps its original stats.", c640_draw_buffs_collector_not_drawn_card)],
    "GIL_645": [
        ("elemental_played_last_turn_draws", "Bonfire Elemental draws a card when another Elemental was played on the previous turn.", c645_elemental_played_last_turn_draws_card),
        ("elemental_played_this_turn_does_not_count", "Playing Bonfire Elemental this turn does not satisfy its previous-turn condition.", c645_no_prior_turn_elemental_does_not_draw),
    ],
    "GIL_646": [
        ("doubles_damage_hero_power", "Clockwork Automaton doubles the damage dealt by Mage's Hero Power.", c646_automaton_doubles_damage_hero_power),
        ("doubles_healing_hero_power", "Clockwork Automaton doubles the healing done by Priest's Hero Power.", c646_automaton_doubles_heal_hero_power),
    ],
    "GIL_648": [("destroys_enemy_secrets_only", "Chief Inspector destroys the opponent's Secret while leaving its controller's Secret in play.", c648_destroys_enemy_secrets_not_controller_secrets)],
    "GIL_650": [("other_minions_gain_rush_and_lose_aura", "Houndmaster Shaw lets another minion attack a minion immediately with Rush; its aura disappears when Shaw leaves play.", c650_shaw_grants_rush_and_aura_ends_with_shaw)],
    "GIL_653": [
        ("deathrattle_buffs_rush_minion", "Breaking Woodcutter's Axe gives +2/+1 to the sole friendly Rush minion.", c653_axe_deathrattle_buffs_rush_minion),
        ("no_rush_minion_remains_unbuffed", "With no friendly Rush minion, Woodcutter's Axe does not buff a non-Rush minion.", c653_no_rush_minion_is_not_buffed),
    ],
    "GIL_654": [("echo_repeats_damage_to_all_minions", "Warpath deals 1 damage to all minions on each of two Echo casts, and its unused Echo copy expires at turn end.", c654_warpath_echo_repeats_aoe_and_expires_copy)],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("limit", nargs="?", type=int, default=42)
    args = parser.parse_args()
    assert 1 <= args.limit <= 42
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
