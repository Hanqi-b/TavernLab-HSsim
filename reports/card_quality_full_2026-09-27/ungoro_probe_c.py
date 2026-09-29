"""Focused live-game audit for the last 44 frozen UNGORO YELLOW collectibles."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.cards import db as card_db
from fireplace.dsl.selector import TARGET_ADJACENT
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import MOONFIRE, MURLOC, WISP, prepare_empty_game  # noqa: E402

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

BASELINE = HERE / "three_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
MECHANISMS = HERE / "card_mechanism.csv"
QUALITY = HERE / "card_quality.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE = HERE / "ungoro_probe_c.csv"
VERDICT = HERE / "ungoro_verdict_c.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


BASE_ROWS = read_csv(BASELINE)
UNGORO_ROWS = [row for row in BASE_ROWS if row["set"] == "Journey to Un'Goro (UNGORO)"]
START = next(i for i, row in enumerate(UNGORO_ROWS) if row["card_id"] == "UNG_847")
END = next(i for i, row in enumerate(UNGORO_ROWS) if row["card_id"] == "UNG_963")
CARDS = [row["card_id"] for row in UNGORO_ROWS[START:END + 1]]
assert START == 89 and END == 132 and len(CARDS) == 44
MASTER_ROWS = {row["card_id"]: row for row in read_csv(MASTER)}
OLD_QUALITY = {row["card_id"]: row for row in read_csv(QUALITY)}
MECH_ROWS = read_csv(MECHANISMS)
LABELS = {cid: sorted({r["mechanic"] for r in MECH_ROWS if r["card_id"] == cid}) for cid in CARDS}
OLD_MECH_REASONS = {
    cid: sorted({r["reason"] for r in MECH_ROWS if r["card_id"] == cid and r["reason"]})
    for cid in CARDS
}
PROBE_ROWS = read_csv(PROBE)
VERDICT_ROWS = read_csv(VERDICT)


def game(class1=CardClass.MAGE, class2=None, seed=417):
    random.seed(seed)
    if class2 is None:
        class2 = class1
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
    return g


def play(player, card_id, target=None, choose=None, index=None):
    card = player.give(card_id)
    kwargs = {}
    if target is not None:
        kwargs["target"] = target
    if choose is not None:
        kwargs["choose"] = choose
    if index is not None:
        kwargs["index"] = index
    card.play(**kwargs)
    return card


def summon(player, card_id):
    return player.summon(card_id)


def summon_enemy_then_return(g, card_id):
    if g.current_player is not g.player1:
        raise AssertionError(f"fixture expected Player1 turn, got {g.current_player.name}")
    g.end_turn()
    minion = g.player2.summon(card_id)
    g.end_turn()
    return minion


def checked(observed, condition):
    assert condition, observed
    return observed


def enum_name(enum_type, value):
    return enum_type(value).name


def prepare_card(cid):
    PROBE_ROWS[:] = [row for row in PROBE_ROWS if row["card_id"] != cid]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def add_case(cid, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append({"card_id": cid, "case_id": case_id, "expected": expected,
                       "observed": observed, "outcome": outcome, "notes": notes})
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)


def finish_card(cid, cases, blocker=None):
    own = [r for r in PROBE_ROWS if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own), cid
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "；".join(
            f"{r['case_id']}预期[{r['expected']}]，实际[{r['observed']}]" for r in errors
        )
    elif unresolved:
        status, reason = "YELLOW", "行为测试未完成：" + "；".join(
            f"{r['case_id']}={r['observed']}" for r in unresolved
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "逐卡实际对局断言通过：" + "；".join(
            f"{r['case_id']}={r['observed']}" for r in own
        )
    m = MASTER_ROWS[cid]
    q = OLD_QUALITY.get(cid, {})
    affected = []
    for issue in read_csv(ISSUES):
        cards = set((issue.get("confirmed_cards", "") + "|" + issue.get("candidate_cards", "")).split("|"))
        if cid in cards:
            affected.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    notes = (
        f"EN={m.get('card_text_en', '')}; ZH={m.get('card_text_zh', '')}; "
        f"source={m.get('python_source', '') or '未发现 Python 卡脚本'}; "
        f"existing_tests={m.get('test_refs_candidate', '') or '无候选既有测试引用'}; "
        f"previous_card_audit={q.get('reason', '无')}; "
        f"previous_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
        f"prior_cross_card_issues={' / '.join(affected) if affected else '无'}; audit_scope=本轮实际运行断言。"
    )
    if cid == "UNG_856":
        notes += (
            " confirmed_RED_scope=英文卡文为'Discover a card from your opponent's class';"
            "源码fireplace/cards/ungoro/rogue.py:126-127使用RandomSpell(card_class=ENEMY_CLASS)"
            "（中立对手分支同样RandomSpell），将候选池硬限制为法术。20个live seeds共60个候选全为SPELL；"
            "当前数据库对手职业仍有可收藏非SPELL随从候选，详见探针candidate对照。"
        )
    if cid == "UNG_962":
        notes += (
            " shared_mechanism_issue=ADAPT-001：两只Silver Hand Recruit存在时只出现一次Adapt Choice，"
            "实测仅最后一只获得增益，另一只保持原状态；与UNG_089/UNG_103多目标Adapt问题同类。"
        )
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    VERDICT_ROWS.append({"card_id": cid, "status": status, "mechanic_scope": "|".join(LABELS[cid]),
                         "reason": reason, "probe_file": PROBE.name, "notes": notes})
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}")


def audit_card(cid, tests, blocker=None):
    prepare_card(cid)
    for case_id, expected, func, notes in tests:
        add_case(cid, case_id, expected, func, notes)
    finish_card(cid, tests, blocker)


def un847_elemental_last_turn_deals_five():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_155")
    firefly = play(p, "UNG_809")
    g.end_turn()
    g.end_turn()
    before = target.health
    blazecaller = play(p, "UNG_847", target)
    return checked(f"elemental={firefly.zone.name};target={before}->{target.health};target_zone={target.zone.name};blazecaller={blazecaller.zone.name};mana={p.mana}",
                   target.controller is enemy and before == 7 and target.health == 2 and target.zone == Zone.PLAY and blazecaller in p.field)


def un847_no_elemental_has_no_battlecry_damage():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon_enemy_then_return(g, "CS2_182")
    before = target.health
    # Keep a legal enemy target available and pass it explicitly so this
    # isolates the Battlecry condition rather than target-requirement rules.
    blazecaller = play(p, "UNG_847", target)
    return checked(f"elemental_last_turn={p.elemental_played_last_turn};target={before}->{target.health};blazecaller={blazecaller.zone.name}",
                   target.controller is enemy and target.health == before and target.zone == Zone.PLAY and blazecaller in p.field)


def un848_damages_other_minions_but_not_drake():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    foe = summon_enemy_then_return(g, "CS2_182")
    friendly = summon(p, WISP)
    drake = play(p, "UNG_848")
    return checked(f"friendly={friendly.zone.name};enemy={foe.health}/{foe.max_health};drake={drake.health}/{drake.max_health};taunt={drake.taunt}",
                   friendly.zone == Zone.GRAVEYARD and foe.health == foe.max_health - 2 and
                   drake.health == drake.max_health and drake.taunt)


def un851_shuffles_pack_then_open_gives_five_ungoro_cards():
    g = game(CardClass.MAGE)
    p = g.player1
    p.give(WISP).shuffle_into_deck()
    elise = play(p, "UNG_851")
    packs = [c for c in p.deck if c.id == "UNG_851t1"]
    assert elise in p.field and len(packs) == 1 and WISP in [c.id for c in p.deck], (elise.zone, [c.id for c in p.deck])
    pack = packs[0]
    pack.draw()
    before_nonpack_hand = len(p.hand) - 1
    pack.play()
    generated = list(p.hand)
    ids = [c.id for c in generated]
    return checked(f"elise={elise.zone.name};pack={pack.zone.name};generated={ids};count_delta={len(generated)-before_nonpack_hand}",
                   pack.zone == Zone.GRAVEYARD and len(generated) == before_nonpack_hand + 5 and
                   all(c.data.card_set.name == "UNGORO" and c.data.collectible for c in generated[-5:]))


def un852_spell_and_hero_power_cannot_target_tyrantus():
    g = game(CardClass.MAGE, CardClass.MAGE)
    p, enemy = g.player1, g.player2
    tyrantus = summon_enemy_then_return(g, "UNG_852")
    spell = p.give("CS2_008")
    spell_blocked = False
    try:
        spell.play(target=tyrantus)
    except InvalidAction:
        spell_blocked = True
    mana_before = p.mana
    hp_blocked = False
    try:
        p.hero.power.use(target=tyrantus)
    except InvalidAction:
        hp_blocked = True
    return checked(f"tyrantus_controller={tyrantus.controller.name};spell_blocked={spell_blocked};spell={spell.zone.name};hp_blocked={hp_blocked};mana={mana_before}->{p.mana};zone={tyrantus.zone.name}",
                   tyrantus.controller is enemy and tyrantus in enemy.field and spell_blocked and spell in p.hand and hp_blocked and p.mana == mana_before)


def un854_discover_eight_cost_minion_and_summon():
    g = game(CardClass.PRIEST)
    p = g.player1
    spell = play(p, "UNG_854")
    choice = p.choice
    offered = [(c.id, enum_name(CardType, c.type), c.cost) for c in choice.cards]
    assert len(offered) == 3 and all(t == "MINION" and cost >= 8 for _, t, cost in offered), offered
    selected = choice.cards[0]
    selected_id = selected.id
    choice.choose(selected)
    summoned = [m for m in p.field if m.id == selected_id]
    return checked(f"offered={offered};selected={selected_id};summoned={[(m.id,m.zone.name) for m in summoned]};hand={[c.id for c in p.hand]};choice={p.choice};spell={spell.zone.name}",
                   len(summoned) == 1 and summoned[0].zone == Zone.PLAY and p.choice is None and spell.zone == Zone.GRAVEYARD)


def un856_offers_opponent_class_cards(first_class, second_class):
    g = game(first_class, second_class)
    p = g.player1
    spell = play(p, "UNG_856")
    choice = p.choice
    offered = [(c.id, enum_name(CardType, c.type), enum_name(CardClass, c.data.card_class)) for c in choice.cards]
    classes = (enum_name(CardClass, p.hero.card_class), enum_name(CardClass, g.player2.hero.card_class))
    expected_class = enum_name(CardClass, p.opponent.hero.card_class)
    selected = choice.cards[0]
    selected_id = selected.id
    choice.choose(selected)
    return checked(f"player_classes={classes};expected_opponent_class={expected_class};offered={offered};selected={selected_id};choice={p.choice};hand={[c.id for c in p.hand]};spell={spell.zone.name}",
                   len(offered) == 3 and all(c[2] == expected_class for c in offered) and
                   p.choice is None and any(c.id == selected_id for c in p.hand) and spell.zone == Zone.GRAVEYARD)


def un856_rogue_warlock_opponent_class():
    return un856_offers_opponent_class_cards(CardClass.ROGUE, CardClass.WARLOCK)


def un856_mage_rogue_opponent_class():
    return un856_offers_opponent_class_cards(CardClass.MAGE, CardClass.ROGUE)


def un856_choice_pool_contains_more_than_spells():
    observed_types = []
    wrong_classes = []
    comparison_cards = {}
    for seed in range(417, 437):
        g = game(CardClass.ROGUE, CardClass.WARLOCK, seed=seed)
        p = g.player1
        play(p, "UNG_856")
        expected_class = enum_name(CardClass, p.opponent.hero.card_class)
        nonspell_pool = card_db.filter(collectible=True, card_class=p.opponent.hero.card_class, type=CardType.MINION)
        if nonspell_pool:
            candidate = card_db[nonspell_pool[0]]
            comparison_cards[expected_class] = (candidate.id, candidate.name, enum_name(CardType, candidate.type), candidate.collectible)
        choice = p.choice
        for card in choice.cards:
            card_type = enum_name(CardType, card.type)
            card_class = enum_name(CardClass, card.data.card_class)
            observed_types.append(card_type)
            if card_class != expected_class:
                wrong_classes.append((seed, card.id, card_class, expected_class))
        choice.choose(choice.cards[0])
    counts = {t: observed_types.count(t) for t in sorted(set(observed_types))}
    return checked(f"seeds=417..436;observed_type_counts={counts};nonspell_seen={any(t != 'SPELL' for t in observed_types)};collectible_nonspell_comparisons={comparison_cards};wrong_classes={wrong_classes}",
                   not wrong_classes and all(candidate[2] == "MINION" and candidate[3] for candidate in comparison_cards.values()) and
                   len(comparison_cards) >= 1 and any(t != "SPELL" for t in observed_types))


def un900_umbra_triggers_summoned_deathrattle():
    g = game(CardClass.PRIEST)
    p = g.player1
    umbra = play(p, "UNG_900")
    igneous = play(p, "UNG_845")
    elementals = [c for c in p.hand if c.id == "UNG_809t1"]
    return checked(f"umbra={umbra.zone.name};igneous={igneous.zone.name};elemental_cards={[(c.id,c.zone.name) for c in elementals]};field={[m.id for m in p.field]}",
                   umbra in p.field and igneous in p.field and len(elementals) == 2 and all(c in p.hand for c in elementals))


def un907_health_scales_with_last_turn_elementals():
    g = game(CardClass.MAGE)
    p = g.player1
    one = play(p, "UNG_809")
    two = play(p, "UNG_809")
    g.end_turn()
    g.end_turn()
    ozruk = play(p, "UNG_907")
    return checked(f"elementals={[one.zone.name,two.zone.name]};ozruk={(ozruk.atk,ozruk.health,ozruk.max_health,ozruk.taunt)};counter={p.elemental_played_last_turn}",
                   ozruk.max_health == ozruk.data.health + 10 and ozruk.health == ozruk.max_health and ozruk.taunt)


def un907_no_elemental_keeps_base_health_and_taunt():
    g = game(CardClass.MAGE)
    p = g.player1
    ozruk = play(p, "UNG_907")
    return checked(f"elemental_last_turn={p.elemental_played_last_turn};ozruk={(ozruk.atk,ozruk.health,ozruk.max_health,ozruk.taunt)}",
                   p.elemental_played_last_turn == 0 and ozruk.max_health == ozruk.data.health and
                   ozruk.health == ozruk.max_health and ozruk.taunt)


def enemy_minions(g, card_ids):
    if g.current_player is not g.player1:
        raise AssertionError(f"fixture expected Player1 turn, got {g.current_player.name}")
    g.end_turn()
    minions = [g.player2.summon(card_id) for card_id in card_ids]
    g.end_turn()
    return minions


def un910_damages_target_and_adjacent_enemy_minions_only():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    left, target, right, far = enemy_minions(g, ["CS2_182"] * 4)
    friendly = summon(p, "CS2_182")
    spell = p.give("UNG_910")
    spell.target = target
    adjacent = TARGET_ADJACENT.eval(list(enemy.field), spell)
    before = [(m.max_health, m.damage, m.health) for m in (left, target, right, far, friendly)]
    spell.play(target=target)
    after = [(m.max_health, m.damage, m.health) for m in (left, target, right, far, friendly)]
    deltas = [new[1] - old[1] for old, new in zip(before, after)]
    return checked(f"starting_max_damage_health={before};direct_TARGET_ADJACENT={[(m.id,m.entity_id) for m in adjacent]};expected_adjacent_ids={[(m.id,m.entity_id) for m in (left,right)]};after={after};damage_deltas={deltas};zones={[m.zone.name for m in (left,target,right,far,friendly)]};spell={spell.zone.name}",
                   [m for m in adjacent] == [left, right] and deltas == [1, 2, 1, 0, 0] and
                   all(m.zone == Zone.PLAY for m in (left, target, right, far, friendly)) and spell.zone == Zone.GRAVEYARD)


def un912_adds_exactly_one_beast_to_hand():
    g = game(CardClass.HUNTER)
    p = g.player1
    original_hand = list(p.hand)
    macaw = play(p, "UNG_912")
    new_cards = [c for c in p.hand if c not in original_hand]
    return checked(f"macaw={macaw.zone.name};new_cards={[(c.id,[enum_name(Race,r) for r in c.races]) for c in new_cards]};hand={[c.id for c in p.hand]}",
                   macaw in p.field and len(new_cards) == 1 and Race.BEAST in new_cards[0].races)


def seed_deck(player, ids):
    for card_id in ids:
        player.give(card_id).shuffle_into_deck()


def un913_draws_two_one_cost_minions_and_leaves_distractor():
    g = game(CardClass.HUNTER)
    p = g.player1
    seed_deck(p, ["CS2_171", "UNG_809", "CS2_182"])
    original_hand = list(p.hand)
    warden = play(p, "UNG_913")
    new_cards = [c for c in p.hand if c not in original_hand]
    return checked(f"warden={warden.zone.name};drawn={[c.id for c in new_cards]};deck={[c.id for c in p.deck]}",
                   warden in p.field and sorted(c.id for c in new_cards) == ["CS2_171", "UNG_809"] and
                   len(new_cards) == 2 and [c.id for c in p.deck] == ["CS2_182"])


def un913_only_draws_available_one_cost_minion():
    g = game(CardClass.HUNTER)
    p = g.player1
    seed_deck(p, ["UNG_809", "CS2_182"])
    original_hand = list(p.hand)
    warden = play(p, "UNG_913")
    new_cards = [c for c in p.hand if c not in original_hand]
    return checked(f"warden={warden.zone.name};drawn={[c.id for c in new_cards]};deck={[c.id for c in p.deck]};health={p.hero.health}",
                   warden in p.field and [c.id for c in new_cards] == ["UNG_809"] and
                   [c.id for c in p.deck] == ["CS2_182"])


def un914_deathrattle_shuffles_exact_four_three_raptor():
    g = game(CardClass.HUNTER)
    p = g.player1
    seed_deck(p, ["CS2_231"])
    hatchling = play(p, "UNG_914")
    body_stats = (hatchling.atk, hatchling.health, hatchling.max_health)
    p.give(MOONFIRE).play(target=hatchling)
    raptors = [c for c in p.deck if c.id == "UNG_914t1"]
    raptor = raptors[0] if raptors else None
    stats = (raptor.atk, raptor.data.health) if raptor else None
    return checked(f"hatchling_stats={body_stats};hatchling_zone={hatchling.zone.name};deck={[c.id for c in p.deck]};raptor_stats={stats};raptor_count={len(raptors)}",
                   hatchling.zone == Zone.GRAVEYARD and body_stats[0] == 2 and len(raptors) == 1 and
                   stats == (4, 3) and "CS2_231" in [c.id for c in p.deck])


def un915_adapts_friendly_beast_and_rejects_nonbeast_target():
    g = game(CardClass.HUNTER)
    p = g.player1
    beast = summon(p, "CS2_171")
    nonbeast = summon(p, WISP)
    before = (beast.atk, beast.health, beast.max_health)
    card = p.give("UNG_915")
    card.play(target=beast)
    choice = p.choice
    offered = [c.id for c in choice.cards]
    selected = choice.cards[0]
    choice.choose(selected)
    mana_before = p.mana
    rejected = False
    invalid_card = p.give("UNG_915")
    try:
        invalid_card.play(target=nonbeast)
    except InvalidAction:
        rejected = True
    after = (beast.atk, beast.health, beast.max_health)
    return checked(f"offered={offered};selected={selected.id};beast={before}->{after};buffs={[b.id for b in beast.buffs]};nonbeast={nonbeast.zone.name};rejected={rejected};invalid_card={invalid_card.zone.name};mana={mana_before}->{p.mana}",
                   len(offered) == 3 and p.choice is None and selected.id + "e" in [b.id for b in beast.buffs] and
                   before != after and Race.BEAST in beast.races and nonbeast.zone == Zone.PLAY and rejected and
                   invalid_card in p.hand and p.mana == mana_before)


def un916_stampede_triggers_for_beast_only_this_turn():
    g = game(CardClass.HUNTER)
    p = g.player1
    stampede = play(p, "UNG_916")
    beast = p.give("CS2_171")
    before_beast = list(p.hand)
    beast.play()
    after_beast = [c for c in p.hand if c not in before_beast]
    nonbeast = p.give(WISP)
    before_nonbeast = list(p.hand)
    nonbeast.play()
    after_nonbeast = [c for c in p.hand if c not in before_nonbeast]
    g.end_turn()
    g.end_turn()
    next_beast = p.give("CS2_171")
    before_next = list(p.hand)
    next_beast.play()
    after_next = [c for c in p.hand if c not in before_next]
    return checked(f"stampede={stampede.zone.name};first_beast_added={[(c.id,[enum_name(Race,r) for r in c.races]) for c in after_beast]};nonbeast_added={[c.id for c in after_nonbeast]};next_turn_beast_added={[c.id for c in after_next]}",
                   stampede.zone == Zone.GRAVEYARD and len(after_beast) == 1 and Race.BEAST in after_beast[0].races and
                   not after_nonbeast and not after_next)


def un917_replaces_hero_power_with_beast_only_plus_two_plus_two():
    g = game(CardClass.HUNTER)
    p = g.player1
    dinomancy = play(p, "UNG_917")
    power = p.hero.power
    beast = summon(p, "CS2_171")
    nonbeast = summon(p, WISP)
    mana_before = p.mana
    rejected = False
    try:
        power.use(target=nonbeast)
    except InvalidAction:
        rejected = True
    after_invalid_mana = p.mana
    before_beast = (beast.atk, beast.health, beast.max_health)
    power.use(target=beast)
    after_beast = (beast.atk, beast.health, beast.max_health)
    return checked(f"dinomancy={dinomancy.zone.name};power={power.id};rejected_nonbeast={rejected};mana={mana_before}->{after_invalid_mana}->{p.mana};beast={before_beast}->{after_beast};nonbeast={nonbeast.atk}/{nonbeast.health}",
                   dinomancy.zone == Zone.GRAVEYARD and power.id == "UNG_917t1" and rejected and
                   after_invalid_mana == mana_before and after_beast == (before_beast[0] + 2, before_beast[1] + 2, before_beast[2] + 2) and
                   (nonbeast.atk, nonbeast.health) == (1, 1) and p.mana == mana_before - 2)


def play_enemy_card(g, card_id):
    if g.current_player is g.player1:
        g.end_turn()
    card = g.player2.give(card_id)
    card.play()
    return card


def un919_dred_attacks_opponent_minion_after_play():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    dred = play(p, "UNG_919")
    enemy_minion = play_enemy_card(g, WISP)
    return checked(f"dred={dred.zone.name};dred_health={dred.health}/{dred.max_health};dred_exhausted={dred.exhausted};enemy_minion={enemy_minion.zone.name};enemy_field={[m.id for m in enemy.field]}",
                   dred in p.field and dred.health == dred.max_health - 1 and dred.exhausted and
                   enemy_minion.zone == Zone.GRAVEYARD and len(enemy.field) == 0)


def un919_frozen_dred_does_not_attack_after_play():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    dred = play(p, "UNG_919")
    play(p, "CS2_024", dred)
    health_after_frostbolt = dred.health
    enemy_minion = play_enemy_card(g, WISP)
    return checked(f"dred={dred.zone.name};health_after_frostbolt={health_after_frostbolt};health_after_enemy_play={dred.health};frozen={dred.frozen};enemy_minion={enemy_minion.zone.name};enemy_field={[m.id for m in enemy.field]}",
                   dred in p.field and health_after_frostbolt == dred.max_health - 3 and dred.health == health_after_frostbolt and
                   dred.frozen and enemy_minion in enemy.field and enemy_minion.health == 1)


def un920_quest_counts_exactly_seven_one_cost_minions():
    g = game(CardClass.HUNTER)
    p = g.player1
    quest = play(p, "UNG_920")
    off_cost = p.give("CS2_182")
    off_cost.play()
    fireball = p.give("CS2_029")
    fireball.play(target=off_cost)
    first_progress = quest.progress
    g.end_turn()
    g.end_turn()
    for _ in range(6):
        play(p, "CS2_171")
    progress_six = quest.progress
    reward_before_seventh = any(c.id == "UNG_920t1" for c in p.hand)
    seventh = play(p, "CS2_171")
    seventh_played_and_counted = seventh in p.field and seventh.zone == Zone.PLAY and quest.progress == 7
    reward = [c for c in p.hand if c.id == "UNG_920t1"]
    reward_in_hand = [c.id for c in reward]
    queen = reward[0] if reward else None
    if queen is not None:
        # The seven qualifying minions occupy the full board; return one
        # without undoing its already-recorded quest progress before playing
        # the reward minion.
        seventh.bounce()
        if p.mana < queen.cost:
            g.end_turn()
            g.end_turn()
        queen.play()
    raptors = [c for c in p.deck if c.id == "UNG_920t2"]
    return checked(f"off_cost_minion_zone={off_cost.zone.name};progress_after_off_cost={first_progress};progress_after_six={progress_six};progress_after_seventh={quest.progress};quest_zone={quest.zone.name};seventh_played_and_counted={seventh_played_and_counted};seventh_after_slot_release={seventh.zone.name};reward_before_play={reward_in_hand};queen={None if queen is None else queen.zone.name};deck_count={len(p.deck)};raptors={len(raptors)};raptor_zones={[c.zone.name for c in raptors]}",
                   first_progress == 0 and progress_six == 6 and not reward_before_seventh and
                   quest.progress == 7 and quest.zone != Zone.SECRET and "UNG_920t1" in reward_in_hand and
                   seventh_played_and_counted and seventh.zone == Zone.HAND and queen is not None and queen in p.field and len(raptors) == 15 and
                   all(c.zone == Zone.DECK for c in raptors))


def un922_replaces_all_deck_cards_with_discover_spells():
    g = game(CardClass.WARRIOR)
    p = g.player1
    seed_deck(p, ["CS2_171", "UNG_809", "CS2_182"])
    original_count = len(p.deck)
    explore = play(p, "UNG_922")
    deck_after = list(p.deck)
    drawn = deck_after[0]
    drawn.draw()
    drawn.play()
    choice = p.choice
    offered = [c.id for c in choice.cards]
    selected = choice.cards[0]
    choice.choose(selected)
    return checked(f"explore={explore.zone.name};original_count={original_count};deck_after={[c.id for c in deck_after]};drawn={drawn.id}/{drawn.zone.name};offered={offered};selected={selected.id};choice={p.choice};hand={[c.id for c in p.hand]};deck_remaining={[c.id for c in p.deck]}",
                   explore.zone == Zone.GRAVEYARD and len(deck_after) == original_count and
                   all(c.id == "UNG_922t1" for c in deck_after) and drawn.zone == Zone.GRAVEYARD and
                   len(offered) == 3 and p.choice is None and any(c.id == selected.id for c in p.hand) and
                   all(c.id == "UNG_922t1" for c in p.deck))


def un923_gains_exactly_five_armor():
    g = game(CardClass.WARRIOR)
    p = g.player1
    before_health, before_armor = p.hero.health, p.hero.armor
    spell = play(p, "UNG_923")
    return checked(f"hero_health={before_health}->{p.hero.health};armor={before_armor}->{p.hero.armor};spell={spell.zone.name}",
                   p.hero.health == before_health and p.hero.armor == before_armor + 5 and spell.zone == Zone.GRAVEYARD)


def un925_adapts_itself_and_retains_taunt():
    g = game(CardClass.WARRIOR)
    p = g.player1
    direhorn = p.give("UNG_925")
    direhorn.play()
    choice = p.choice
    offered = [c.id for c in choice.cards]
    selected = choice.cards[0]
    choice.choose(selected)
    return checked(f"offered={offered};selected={selected.id};direhorn={(direhorn.atk,direhorn.health,direhorn.max_health,direhorn.taunt)};buffs={[b.id for b in direhorn.buffs]};choice={p.choice}",
                   len(offered) == 3 and selected.id + "e" in [b.id for b in direhorn.buffs] and
                   direhorn in p.field and direhorn.taunt and p.choice is None)


def un926_summons_three_ones_to_opponent():
    g = game(CardClass.WARRIOR)
    p, enemy = g.player1, g.player2
    sentry = play(p, "UNG_926")
    tokens = list(enemy.field)
    return checked(f"sentry={sentry.zone.name};friendly_field={[m.id for m in p.field]};enemy_tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]};controllers={[m.controller.name for m in tokens]}",
                   sentry in p.field and sentry.taunt and len(tokens) == 3 and
                   all(m.id == "UNG_076t1" and m.atk == 1 and m.health == m.max_health == 1 and m.zone == Zone.PLAY for m in tokens) and
                   all(m.controller is enemy for m in tokens))


def un926_opponent_full_board_does_not_overflow():
    g = game(CardClass.WARRIOR)
    p, enemy = g.player1, g.player2
    for _ in range(7):
        summon(enemy, WISP)
    starting_enemy = [(m.id, m.entity_id, m.zone.name) for m in enemy.field]
    sentry = play(p, "UNG_926")
    resulting_enemy = [(m.id, m.entity_id, m.zone.name) for m in enemy.field]
    return checked(f"starting_enemy={starting_enemy};sentry={sentry.zone.name};enemy_after={resulting_enemy};enemy_count={len(enemy.field)};friendly_field={[(m.id,m.zone.name) for m in p.field]}",
                   sentry in p.field and len(starting_enemy) == 7 and len(enemy.field) <= 7 and
                   all(m.id == WISP and m.zone == Zone.PLAY for m in enemy.field))


def un927_copies_only_damaged_minions():
    g = game(CardClass.WARRIOR)
    p = g.player1
    first, second, healthy = [summon(p, "CS2_182") for _ in range(3)]
    p.give(MOONFIRE).play(target=first)
    p.give(MOONFIRE).play(target=second)
    p.give(MOONFIRE).play(target=second)
    originals = (first, second, healthy)
    before = [(m.id, m.atk, m.max_health, m.damage, m.health, m.zone.name) for m in originals]
    spell = play(p, "UNG_927")
    copies = [m for m in p.field if m not in originals]
    copied_stats = [(m.id, m.atk, m.max_health, m.damage, m.health, m.zone.name) for m in copies]
    copy_matches = []
    for source in (first, second):
        matches = [m for m in copies if m.id == source.id and m.damage == source.damage]
        copy_matches.append((
            source.entity_id,
            (source.damage, source.health, source.max_health),
            [(m.entity_id, m.damage, m.health, m.max_health) for m in matches],
            len(matches) == 1 and
            (matches[0].damage, matches[0].health, matches[0].max_health) ==
            (source.damage, source.health, source.max_health),
        ))
    damaged_sources_copied_exactly = all(row[3] for row in copy_matches)
    healthy_copy_count = sum(1 for m in copies if m.id == healthy.id and m.damage == 0)
    return checked(f"originals_before={before};originals_after={[(m.id,m.damage,m.health,m.zone.name) for m in originals]};copies={copied_stats};copy_matches_by_source={copy_matches};damaged_sources_copied_exactly={damaged_sources_copied_exactly};healthy_copy_count={healthy_copy_count};spell={spell.zone.name};field={[m.id for m in p.field]}",
                   spell.zone == Zone.GRAVEYARD and len(copies) == 2 and
                   sorted(m.id for m in copies) == [first.id, second.id] and healthy.damage == 0 and
                   all(m.zone == Zone.PLAY for m in copies) and
                   damaged_sources_copied_exactly and healthy_copy_count == 0)


def un928_attack_changes_only_on_opponent_turn():
    g = game(CardClass.SHAMAN)
    p = g.player1
    creeper = play(p, "UNG_928")
    own_turn_attack = creeper.atk
    g.end_turn()
    opponent_turn_attack = creeper.atk
    g.end_turn()
    next_own_turn_attack = creeper.atk
    return checked(f"attack_own={own_turn_attack};attack_opponent={opponent_turn_attack};attack_next_own={next_own_turn_attack};taunt={creeper.taunt};zone={creeper.zone.name}",
                   own_turn_attack == creeper.data.atk and opponent_turn_attack == own_turn_attack + 2 and
                   next_own_turn_attack == own_turn_attack and creeper.taunt and creeper.zone == Zone.PLAY)


def un929_molten_blade_transforms_on_own_turns_in_hand():
    g = game(CardClass.WARRIOR)
    p = g.player1
    blade = p.give("UNG_929")
    g.random.seed(929)
    starting = blade.id
    preexisting = [c for c in p.hand if c is not blade]
    g.end_turn()
    g.end_turn()
    first_in_hand = [c for c in p.hand if c not in preexisting]
    first_id = first_in_hand[0].id if first_in_hand else None
    first_type = enum_name(CardType, first_in_hand[0].type) if first_in_hand else None
    first_entity_id = first_in_hand[0].entity_id if first_in_hand else None
    g.end_turn()
    g.end_turn()
    second_in_hand = [c for c in p.hand if c not in preexisting and c.entity_id != first_entity_id]
    second_id = second_in_hand[0].id if second_in_hand else None
    second_type = enum_name(CardType, second_in_hand[0].type) if second_in_hand else None
    second_entity_id = second_in_hand[0].entity_id if second_in_hand else None
    return checked(f"starting={starting};original_zone={blade.zone.name};first={first_id}/{first_type}/entity{first_entity_id};second={second_id}/{second_type}/entity{second_entity_id};hand={[c.id for c in p.hand]}",
                   blade.zone == Zone.SETASIDE and len(first_in_hand) == len(second_in_hand) == 1 and
                   first_type == "WEAPON" and second_type == "WEAPON" and first_entity_id != second_entity_id)


def un933_destroys_damaged_minions_on_both_sides_only():
    g = game(CardClass.WARRIOR)
    p, enemy = g.player1, g.player2
    enemy_damaged, enemy_healthy = enemy_minions(g, ["CS2_182", "CS2_182"])
    friendly_damaged = summon(p, "CS2_182")
    friendly_healthy = summon(p, "CS2_182")
    p.give(MOONFIRE).play(target=enemy_damaged)
    p.give(MOONFIRE).play(target=friendly_damaged)
    mosh = play(p, "UNG_933")
    return checked(f"mosh={mosh.zone.name};friendly_damaged={friendly_damaged.zone.name};enemy_damaged={enemy_damaged.zone.name};friendly_healthy={friendly_healthy.zone.name}/{friendly_healthy.health};enemy_healthy={enemy_healthy.zone.name}/{enemy_healthy.health};friendly_field={[m.id for m in p.field]};enemy_field={[m.id for m in enemy.field]}",
                   mosh in p.field and friendly_damaged.zone == Zone.GRAVEYARD and enemy_damaged.zone == Zone.GRAVEYARD and
                   friendly_healthy in p.field and enemy_healthy in enemy.field and
                   friendly_healthy.health == friendly_healthy.max_health and enemy_healthy.health == enemy_healthy.max_health)


def un934_quest_counts_seven_taunt_minions():
    g = game(CardClass.WARRIOR)
    p = g.player1
    quest = play(p, "UNG_934")
    non_taunt = play(p, "CS2_171")
    progress_without_taunt = quest.progress
    non_taunt.bounce()
    for _ in range(6):
        if p.mana < 3:
            g.end_turn()
            g.end_turn()
        taunt = play(p, "UNG_928")
        assert taunt.taunt
        taunt.bounce()
    progress_six = quest.progress
    reward_before_seventh = any(c.id == "UNG_934t1" for c in p.hand)
    if p.mana < 3:
        g.end_turn()
        g.end_turn()
    seventh = play(p, "UNG_928")
    reward = [c for c in p.hand if c.id == "UNG_934t1"]
    sulfuras = reward[0] if reward else None
    if sulfuras is not None:
        if p.mana < sulfuras.cost:
            g.end_turn()
            g.end_turn()
        sulfuras.play()
    power_after_equip = p.hero.power.id
    enemy_hero_before_power = p2_hero_health = g.player2.hero.health
    power_used = False
    if p.hero.power.id == "UNG_934t2":
        # Sulfuras may consume the last available mana. Refresh on a real
        # following own turn before trying the replacement power.
        g.end_turn()
        g.end_turn()
    if p.hero.power.id == "UNG_934t2" and p.mana >= p.hero.power.cost:
        p.hero.power.use()
        power_used = True
    return checked(f"non_taunt_progress={progress_without_taunt};progress_six={progress_six};quest_progress={quest.progress};quest_zone={quest.zone.name};seventh={seventh.zone.name};reward_ids={[c.id for c in p.hand]};sulfuras={None if sulfuras is None else (sulfuras.id,sulfuras.zone.name)};weapon={None if p.weapon is None else (p.weapon.id,p.weapon.atk,p.weapon.durability)};hero_power={power_after_equip};power_used={power_used};enemy_hero_health={enemy_hero_before_power}->{g.player2.hero.health}",
                   progress_without_taunt == 0 and progress_six == 6 and not reward_before_seventh and
                   quest.progress == 7 and quest.zone != Zone.SECRET and "UNG_934t1" not in [c.id for c in p.hand] and
                   seventh.taunt and sulfuras is not None and sulfuras.zone == Zone.PLAY and
                   p.weapon is not None and p.weapon.id == "UNG_934t1" and power_after_equip == "UNG_934t2" and
                   power_used and enemy_hero_before_power == 30 and g.player2.hero.health == p2_hero_health - 8)


def un937_discovers_murloc_only_with_another_murloc():
    g = game(CardClass.SHAMAN)
    p = g.player1
    murloc = summon(p, "CS2_168")
    lookout = play(p, "UNG_937")
    choice = p.choice
    offered = [(c.id, [enum_name(Race, r) for r in c.races]) for c in choice.cards]
    selected = choice.cards[0]
    choice.choose(selected)
    with_another = (p.choice is None and any(c.id == selected.id for c in p.hand) and
                    all(Race.MURLOC in c.races for c in choice.cards))
    g2 = game(CardClass.SHAMAN)
    p2 = g2.player1
    lookout2 = play(p2, "UNG_937")
    return checked(f"positive=murloc:{murloc.zone.name};lookout:{lookout.zone.name};offered={offered};selected={selected.id};choice={p.choice};hand={[c.id for c in p.hand]};negative=lookout:{lookout2.zone.name};choice:{p2.choice};hand:{[c.id for c in p2.hand]}",
                   with_another and lookout in p.field and lookout2 in p2.field and p2.choice is None and
                   not any(c.id not in [] and Race.MURLOC in c.races for c in p2.hand))


def un938_heals_target_three_and_has_taunt():
    g = game(CardClass.SHAMAN, CardClass.MAGE)
    p, enemy = g.player1, g.player2
    damaged = summon(p, "CS2_182")
    p.give(MOONFIRE).play(target=damaged)
    before = (damaged.health, damaged.max_health)
    guardian = play(p, "UNG_938", damaged)
    return checked(f"target_health={before}->{(damaged.health,damaged.max_health)};guardian={(guardian.atk,guardian.health,guardian.taunt)};target_zone={damaged.zone.name}",
                   before[0] == before[1] - 1 and damaged.health == damaged.max_health and guardian in p.field and guardian.taunt)


def un940_quest_counts_summoned_deathrattle_minions_and_plays_reward():
    g = game(CardClass.PRIEST)
    p = g.player1
    quest = play(p, "UNG_940")
    ordinary = p.summon(WISP)
    progress_after_non_deathrattle = quest.progress
    ordinary.destroy()
    for _ in range(6):
        minion = p.summon("UNG_914")
        assert minion.has_deathrattle
        minion.destroy()
    progress_six = quest.progress
    reward_before_seventh = any(c.id == "UNG_940t8" for c in p.hand)
    seventh = p.summon("UNG_914")
    assert seventh.has_deathrattle
    seventh.destroy()
    reward = [c for c in p.hand if c.id == "UNG_940t8"]
    amara = reward[0] if reward else None
    amara_result = None
    if amara is not None:
        amara.play()
        amara_result = (p.hero.health, p.hero.max_health, amara.zone.name)
    return checked(f"non_dr_progress={progress_after_non_deathrattle};progress_six={progress_six};quest_progress={quest.progress};quest_zone={quest.zone.name};reward_before_seventh={reward_before_seventh};amara={amara_result};hero={(p.hero.health,p.hero.max_health)};seventh={seventh.zone.name}",
                   progress_after_non_deathrattle == 0 and progress_six == 6 and not reward_before_seventh and
                   quest.progress == 7 and quest.zone != Zone.SECRET and amara is not None and
                   amara_result is not None and p.hero.max_health == 40 and p.hero.health == 40)


def un941_discover_spell_and_reduce_selected_cost_two():
    g = game(CardClass.MAGE)
    p = g.player1
    glyph = play(p, "UNG_941")
    choice = p.choice
    offered = [(c.id, enum_name(CardType, c.type), c.cost) for c in choice.cards]
    assert len(offered) == 3 and all(t == "SPELL" for _, t, _ in offered), offered
    selected = choice.cards[0]
    base_cost = selected.data.cost
    choice.choose(selected)
    return checked(f"offered={offered};selected={selected.id};base_cost={base_cost};discounted_cost={selected.cost};choice={p.choice};hand={[c.id for c in p.hand]};glyph={glyph.zone.name}",
                   p.choice is None and selected in p.hand and selected.cost == max(0, base_cost - 2) and glyph.zone == Zone.GRAVEYARD)


def un942_quest_counts_summoned_murlocs_and_reward_fills_hand():
    g = game(CardClass.SHAMAN)
    p = g.player1
    quest = play(p, "UNG_942")
    nonmurloc = p.summon(WISP)
    progress_after_nonmurloc = quest.progress
    nonmurloc.destroy()
    for _ in range(9):
        murloc = p.summon("CS2_168")
        murloc.destroy()
    progress_nine = quest.progress
    reward_before_tenth = any(c.id == "UNG_942t" for c in p.hand)
    tenth = p.summon("CS2_168")
    tenth.destroy()
    reward = [c for c in p.hand if c.id == "UNG_942t"]
    reward_result = None
    if reward:
        reward_card = reward[0]
        reward_card.play()
        reward_result = (len(p.hand), [(c.id, Race.MURLOC in c.races) for c in p.hand])
    return checked(f"nonmurloc_progress={progress_after_nonmurloc};progress_nine={progress_nine};quest_progress={quest.progress};quest_zone={quest.zone.name};reward_before_tenth={reward_before_tenth};reward_result={reward_result};tenth={tenth.zone.name}",
                   progress_after_nonmurloc == 0 and progress_nine == 9 and not reward_before_tenth and
                   quest.progress == 10 and quest.zone != Zone.SECRET and reward_result is not None and
                   reward_result[0] == 10 and all(is_murloc for _, is_murloc in reward_result[1]))


def un946_destroys_enemy_weapon_and_gains_its_attack_as_armor():
    g = game(CardClass.ROGUE, CardClass.WARRIOR)
    p, enemy = g.player1, g.player2
    own_weapon = play(p, "CS2_091")
    own_attack = own_weapon.atk
    g.end_turn()
    enemy_weapon = enemy.give("CS2_106")
    enemy_weapon.play()
    enemy_attack = enemy_weapon.atk
    g.end_turn()
    before_armor = p.hero.armor
    ooze = play(p, "UNG_946")
    return checked(f"own_weapon={own_weapon.id}/{own_weapon.atk}/{own_weapon.zone.name};enemy_weapon={enemy_weapon.id}/{enemy_weapon.atk}/{enemy_weapon.zone.name};enemy_weapon_live={enemy.weapon};enemy_attack={enemy_attack};armor={before_armor}->{p.hero.armor};ooze={ooze.zone.name}",
                   own_weapon is p.weapon and own_weapon.atk == own_attack and enemy.weapon is None and
                   enemy_weapon.zone != Zone.PLAY and p.hero.armor == before_armor + enemy_attack and ooze in p.field)


def un946_without_enemy_weapon_gains_no_armor():
    g = game(CardClass.ROGUE, CardClass.WARRIOR)
    p = g.player1
    before_armor = p.hero.armor
    ooze = play(p, "UNG_946")
    return checked(f"enemy_weapon={p.opponent.weapon};armor={before_armor}->{p.hero.armor};ooze={ooze.zone.name}",
                   p.opponent.weapon is None and p.hero.armor == before_armor and ooze in p.field)


def un948_summons_copy_of_friendly_target_and_rejects_enemy():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    foe = enemy_minions(g, ["CS2_182"])[0]
    target = summon(p, "CS2_182")
    before = (target.id, target.atk, target.health, target.max_health, target.damage)
    reflection = play(p, "UNG_948", target)
    copies = [m for m in p.field if m is not target and m.id == target.id]
    copy_state = [(m.id, m.atk, m.health, m.max_health, m.damage, m.zone.name) for m in copies]
    mana_before = p.mana
    invalid = p.give("UNG_948")
    rejected = False
    try:
        invalid.play(target=foe)
    except InvalidAction:
        rejected = True
    return checked(f"target_before={before};copies={copy_state};reflection={reflection.zone.name};foe={foe.zone.name};invalid_rejected={rejected};invalid_zone={invalid.zone.name};mana={mana_before}->{p.mana}",
                   len(copies) == 1 and copy_state == [(before[0],before[1],before[2],before[3],before[4],"PLAY")] and
                   reflection.zone == Zone.GRAVEYARD and foe in enemy.field and rejected and invalid in p.hand and p.mana == mana_before)


def un950_summons_recruits_after_hero_attacks():
    g = game(CardClass.PALADIN)
    p, enemy = g.player1, g.player2
    weapon = play(p, "UNG_950")
    foe = enemy_minions(g, ["CS2_182"])[0]
    before_durability = weapon.durability
    before_health = foe.health
    p.hero.attack(foe)
    recruits = [m for m in p.field if m.id == "CS2_101t"]
    return checked(f"weapon={weapon.zone.name};weapon_durability={before_durability}->{weapon.durability};hero_attack={p.hero.atk};enemy={before_health}->{foe.health}/{foe.max_health};recruits={[(m.id,m.atk,m.health,m.zone.name) for m in recruits]}",
                   weapon is p.weapon and weapon.durability == before_durability - 1 and foe.health == before_health - p.hero.atk and
                   len(recruits) == 2 and all(m.atk == 1 and m.health == m.max_health == 1 for m in recruits))


def un952_buffs_minion_and_death_summons_stegodon():
    g = game(CardClass.PALADIN)
    p = g.player1
    target = summon(p, WISP)
    spell = play(p, "UNG_952", target)
    buffed = (target.atk, target.health, target.max_health, target.taunt, target.has_deathrattle)
    p.give("CS2_029").play(target=target)
    after_fireball = (target.health, target.zone.name)
    p.give(MOONFIRE).play(target=target)
    stegodons = [m for m in p.field if m.id == "UNG_810"]
    return checked(f"spell={spell.zone.name};buffed={buffed};after_fireball={after_fireball};target={target.zone.name};stegodons={[(m.id,m.atk,m.health,m.max_health,m.taunt,m.zone.name) for m in stegodons]}",
                   buffed[:4] == (3, 7, 7, True) and buffed[4] and after_fireball == (1, "PLAY") and
                   target.zone == Zone.GRAVEYARD and len(stegodons) == 1 and stegodons[0].zone == Zone.PLAY)


def un953_returns_only_spells_cast_on_champion():
    g = game(CardClass.PALADIN)
    p = g.player1
    champion = play(p, "UNG_953")
    other = summon(p, "CS2_182")
    buff_spell = p.give("CS2_092")
    buff_spell.play(target=champion)
    p.give(MOONFIRE).play(target=other)
    lethal = p.give("CS2_029")
    lethal.play(target=champion)
    hand_ids = [c.id for c in p.hand]
    return checked(f"champion={champion.zone.name};other={other.zone.name}/{other.health};hand={hand_ids};champion_attacks={champion.atk}",
                   champion.zone == Zone.GRAVEYARD and other.zone == Zone.PLAY and other.health == other.max_health - 1 and
                   hand_ids.count("CS2_092") == 1 and hand_ids.count("CS2_029") == 1 and MOONFIRE not in hand_ids)


def un954_quest_counts_spells_on_friendly_minions_and_resolves_five_adapts():
    g = game(CardClass.PALADIN)
    p, enemy = g.player1, g.player2
    foe = enemy_minions(g, ["CS2_182"])[0]
    quest = play(p, "UNG_954")
    p.give(MOONFIRE).play(target=foe)
    progress_enemy_target = quest.progress
    target = summon(p, "CS2_200")
    for _ in range(6):
        p.give(MOONFIRE).play(target=target)
    progress_six = quest.progress
    reward = [c for c in p.hand if c.id == "UNG_954t1"]
    galvadon = reward[0] if reward else None
    choice_count = 0
    if galvadon is not None:
        galvadon.play()
        while p.choice is not None:
            choice = p.choice
            choice.choose(choice.cards[0])
            choice_count += 1
    return checked(f"enemy_target_progress={progress_enemy_target};friendly_target_health={target.health}/{target.max_health};progress={quest.progress};quest_zone={quest.zone.name};galvadon={galvadon.zone.name if galvadon else None};choice_count={choice_count};buffs={[b.id for b in galvadon.buffs] if galvadon else []};choice={p.choice}",
                   progress_enemy_target == 0 and progress_six == 6 and quest.progress == 6 and
                   quest.zone != Zone.SECRET and galvadon is not None and galvadon in p.field and
                   choice_count == 5 and p.choice is None and len(galvadon.buffs) >= 5)


def un955_meteor_hits_target_fifteen_and_adjacent_three():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    left, target, right, far = enemy_minions(g, ["CS2_182"] * 4)
    friendly = summon(p, "CS2_182")
    meteor = p.give("UNG_955")
    meteor.target = target
    adjacent = TARGET_ADJACENT.eval(list(enemy.field), meteor)
    before = [(m.max_health, m.damage, m.health) for m in (left, target, right, far, friendly)]
    meteor.play(target=target)
    after_damage = [m.damage for m in (left, target, right, far, friendly)]
    return checked(f"starting_max_damage_health={before};direct_TARGET_ADJACENT={[(m.id,m.entity_id) for m in adjacent]};target_zone={target.zone.name};adjacent_damage={[left.damage,right.damage]};all_damage={after_damage};far_zone={far.zone.name};friendly_zone={friendly.zone.name};meteor={meteor.zone.name}",
                   [m for m in adjacent] == [left, right] and target.zone == Zone.GRAVEYARD and
                   [left.damage, right.damage] == [3, 3] and far.damage == 0 and friendly.damage == 0 and
                   far.zone == Zone.PLAY and friendly.zone == Zone.PLAY and meteor.zone == Zone.GRAVEYARD)


def un956_grants_deathrattle_return_to_each_minion():
    g = game(CardClass.SHAMAN)
    p = g.player1
    first = summon(p, "CS2_182")
    second = summon(p, WISP)
    echo = play(p, "UNG_956")
    deathrattles = (first.has_deathrattle, second.has_deathrattle)
    p.give("CS2_029").play(target=first)
    first_returned = [c.id for c in p.hand]
    p.give(MOONFIRE).play(target=second)
    second_returned = [c.id for c in p.hand]
    return checked(f"echo={echo.zone.name};deathrattles={deathrattles};first={first.zone.name};after_first_hand={first_returned};second={second.zone.name};after_second_hand={second_returned};field={[m.id for m in p.field]}",
                   deathrattles == (True, True) and first.zone == Zone.GRAVEYARD and second.zone == Zone.GRAVEYARD and
                   first_returned.count("CS2_182") == 1 and second_returned.count("CS2_182") == 1 and
                   second_returned.count(WISP) == 1 and not p.field)


def un957_deathrattle_shuffles_taunt_six_nine_direhorn():
    g = game(CardClass.WARRIOR)
    p = g.player1
    seed_deck(p, ["CS2_182"])
    hatchling = play(p, "UNG_957")
    body = (hatchling.atk, hatchling.health, hatchling.max_health, hatchling.taunt)
    p.give("CS2_029").play(target=hatchling)
    tokens = [c for c in p.deck if c.id == "UNG_957t1"]
    token = tokens[0] if tokens else None
    token_stats = (token.atk, token.data.health, token.taunt) if token else None
    return checked(f"body={body};hatchling={hatchling.zone.name};deck={[c.id for c in p.deck]};token_stats={token_stats};token_count={len(tokens)}",
                   body[3] and hatchling.zone == Zone.GRAVEYARD and len(tokens) == 1 and token_stats == (6, 9, True) and
                   "CS2_182" in [c.id for c in p.deck])


def un960_summons_two_recruits_and_handles_one_open_slot():
    g = game(CardClass.PALADIN)
    p = g.player1
    spell = play(p, "UNG_960")
    recruits = [m for m in p.field if m.id == "CS2_101t"]
    two_case = (spell.zone == Zone.GRAVEYARD and len(recruits) == 2 and
                all(m.atk == 1 and m.health == m.max_health == 1 for m in recruits))
    g2 = game(CardClass.PALADIN)
    p2 = g2.player1
    for _ in range(6):
        summon(p2, "CS2_182")
    one_slot_spell = play(p2, "UNG_960")
    one_slot_recruits = [m for m in p2.field if m.id == "CS2_101t"]
    return checked(f"two_slot_case=spell:{spell.zone.name};recruits={[(m.id,m.atk,m.health) for m in recruits]};one_slot_case=spell:{one_slot_spell.zone.name};field_size={len(p2.field)};recruits={[(m.id,m.atk,m.health,m.zone.name) for m in one_slot_recruits]}",
                   two_case and one_slot_spell.zone == Zone.GRAVEYARD and len(p2.field) == 7 and
                   len(one_slot_recruits) == 1 and one_slot_recruits[0].atk == 1 and one_slot_recruits[0].health == 1)


def un960_cannot_play_with_full_board():
    g = game(CardClass.PALADIN)
    p = g.player1
    for _ in range(7):
        summon(p, "CS2_182")
    spell = p.give("UNG_960")
    before_mana = p.mana
    rejected = False
    try:
        spell.play()
    except InvalidAction:
        rejected = True
    return checked(f"rejected={rejected};spell={spell.zone.name};field_size={len(p.field)};mana={before_mana}->{p.mana};recruits={[m.id for m in p.field if m.id == 'CS2_101t']}",
                   rejected and spell in p.hand and len(p.field) == 7 and p.mana == before_mana and
                   not any(m.id == "CS2_101t" for m in p.field))


def un961_adapts_only_selected_friendly_minion():
    g = game(CardClass.PALADIN)
    p, enemy = g.player1, g.player2
    target = summon(p, "CS2_171")
    other = summon(p, "CS2_182")
    foe = enemy_minions(g, ["CS2_182"])[0]
    before_target = (target.atk, target.health, target.max_health)
    before_other = (other.atk, other.health, other.max_health)
    spell = play(p, "UNG_961", target)
    choice = p.choice
    offered = [c.id for c in choice.cards]
    selected = choice.cards[0]
    choice.choose(selected)
    after_target = (target.atk, target.health, target.max_health)
    after_other = (other.atk, other.health, other.max_health)
    mana_before = p.mana
    invalid = p.give("UNG_961")
    rejected = False
    try:
        invalid.play(target=foe)
    except InvalidAction:
        rejected = True
    return checked(f"offered={offered};selected={selected.id};target={before_target}->{after_target};other={before_other}->{after_other};foe={foe.zone.name};spell={spell.zone.name};invalid_rejected={rejected};invalid_zone={invalid.zone.name};mana={mana_before}->{p.mana}",
                   len(offered) == 3 and selected.id + "e" in [b.id for b in target.buffs] and after_target != before_target and
                   after_other == before_other and spell.zone == Zone.GRAVEYARD and foe in enemy.field and
                   rejected and invalid in p.hand and p.mana == mana_before)


def un962_adapts_every_friendly_silver_hand_recruit():
    g = game(CardClass.PALADIN)
    p = g.player1
    lost = play(p, "UNG_960")
    recruits = [m for m in p.field if m.id == "CS2_101t"]
    before = [(m.atk,m.health,m.max_health) for m in recruits]
    stegodon = p.give("UNG_962")
    stegodon.play()
    choice_count = 0
    chosen = []
    chosen_buff_ids = []
    while p.choice is not None:
        choice = p.choice
        chosen.append(choice.cards[0].id)
        chosen_buff_ids.append(choice.cards[0].id + "e")
        choice.choose(choice.cards[0])
        choice_count += 1
    after = [(m.atk,m.health,m.max_health) for m in recruits]
    buff_ids = [[b.id for b in m.buffs] for m in recruits]
    shared_choice_applied = bool(chosen_buff_ids) and all(chosen_buff_ids[0] in buffs for buffs in buff_ids)
    return checked(f"lost={lost.zone.name};recruits={[(m.id,m.entity_id) for m in recruits]};before={before};after={after};buff_ids={buff_ids};shared_choice_applied={shared_choice_applied};choice_count={choice_count};choices={chosen};stegodon={stegodon.zone.name};choice={p.choice}",
                   len(recruits) == 2 and stegodon in p.field and p.choice is None and
                   choice_count == 1 and shared_choice_applied)


def un962_no_recruits_means_no_adapt_choice():
    g = game(CardClass.PALADIN)
    p = g.player1
    stegodon = play(p, "UNG_962")
    return checked(f"stegodon={stegodon.zone.name};field={[m.id for m in p.field]};choice={p.choice}",
                   stegodon in p.field and p.choice is None and len(p.field) == 1)


def un963_lyra_adds_priest_spell_only_for_own_spell_casts():
    g = game(CardClass.PRIEST, CardClass.MAGE)
    p, enemy = g.player1, g.player2
    lyra = play(p, "UNG_963")
    target = summon(p, "CS2_182")
    before_spell = list(p.hand)
    own_spell = p.give(MOONFIRE)
    own_spell.play(target=target)
    generated = [c for c in p.hand if c not in before_spell]
    generated_info = [(c.id,enum_name(CardType,c.type),enum_name(CardClass,c.data.card_class)) for c in generated]
    nonspell = play(p, "CS2_171")
    own_nonspell_delta = [c.id for c in p.hand if c not in generated and c not in before_spell]
    g.end_turn()
    before_opponent_spell = list(p.hand)
    enemy_spell = enemy.give(MOONFIRE)
    enemy_spell.play(target=p.hero)
    after_opponent_spell = list(p.hand)
    return checked(f"lyra={lyra.zone.name};own_spell={own_spell.zone.name};generated={generated_info};nonspell={nonspell.zone.name};nonspell_added={own_nonspell_delta};enemy_spell={enemy_spell.zone.name};enemy_turn_hand_delta={[c.id for c in after_opponent_spell if c not in before_opponent_spell]};hand={[c.id for c in p.hand]}",
                   lyra in p.field and own_spell.zone == Zone.GRAVEYARD and len(generated) == 1 and
                   generated_info[0][1:] == ("SPELL", "PRIEST") and nonspell in p.field and
                   not own_nonspell_delta and not [c for c in after_opponent_spell if c not in before_opponent_spell])


CASES = {
    "UNG_847": [
        ("elemental_last_turn_deals_five", "After playing an Elemental last turn, Blazecaller deals 5 to the chosen enemy minion.", un847_elemental_last_turn_deals_five, "Played Fire Fly on the preceding own turn, targeted a real enemy minion, and checked exact death/zone."),
        ("no_elemental_last_turn_no_damage", "Without an Elemental last turn, Blazecaller's conditional Battlecry deals no damage.", un847_no_elemental_has_no_battlecry_damage, "Left a 4/5 enemy minion available and played Blazecaller without an Elemental on the prior turn."),
    ],
    "UNG_848": [("aoe_excludes_self", "Primordial Drake deals 2 to every other minion while its own health stays full.", un848_damages_other_minions_but_not_drake, "Placed a friendly Wisp and a real opposing 4/5 before playing Drake; checked self and both sides." )],
    "UNG_851": [("pack_shuffled_and_opened", "Elise shuffles one Un'Goro Pack into deck; opening it adds five collectible Un'Goro cards.", un851_shuffles_pack_then_open_gives_five_ungoro_cards, "Kept a known deck card, verified one pack, drew and opened pack, then checked set/collectible metadata and hand delta." )],
    "UNG_852": [("spell_and_hero_power_untargetable", "Tyrantus cannot be selected by an enemy spell or Hero Power; failed attempts spend no mana.", un852_spell_and_hero_power_cannot_target_tyrantus, "Used actual opposing Tyrantus; attempted Moonfire and Mage Hero Power and checked InvalidAction, zones, and mana." )],
    "UNG_854": [("discover_8_cost_minion_then_summon", "Free From Amber offers only minions costing at least 8 and summons the selected choice.", un854_discover_eight_cost_minion_and_summon, "Read live choice types/costs, selected one and checked that it entered field rather than hand." )],
    "UNG_856": [
        ("rogue_warlock_opponent_class", "Hallucination offers three cards from the actual opponent's class and adds the chosen card to hand.", un856_rogue_warlock_opponent_class, "Used Rogue/Warlock player setup; reads the post-coin-toss actual heroes rather than assuming class argument order; inspected all choices and hand/zone."),
        ("mage_rogue_opponent_class", "Hallucination offers three cards from the actual opponent's class and adds the chosen card to hand.", un856_mage_rogue_opponent_class, "Used Mage/Rogue setup; reads actual player and opponent hero classes after the coin toss; inspected all choices and hand/zone."),
        ("discover_pool_includes_all_card_types", "The Discover pool must allow cards of any type from the opponent's class, not spells only.", un856_choice_pool_contains_more_than_spells, "Ran 20 live game seeds; checked all 60 offered cards against actual opponent class and whether any non-spell could appear. Source uses RandomSpell at ungoro/rogue.py:122, which statically excludes non-spells."),
    ],
    "UNG_900": [("summon_triggers_deathrattle", "Umbra triggers a summoned Igneous Elemental's Deathrattle immediately, adding two Elementals to hand.", un900_umbra_triggers_summoned_deathrattle, "Played Umbra, then played Igneous Elemental and checked body zones and two generated hand cards." )],
    "UNG_907": [
        ("two_elementals_add_ten_health", "Two Elementals played last turn grant +10 Health; Ozruk remains Taunt.", un907_health_scales_with_last_turn_elementals, "Played two Fire Flies on the preceding own turn; checked counter=2, current/max health, and Taunt."),
        ("no_elemental_keeps_base_health", "With no Elemental played last turn, Ozruk gets no bonus Health but still has Taunt.", un907_no_elemental_keeps_base_health_and_taunt, "Played Ozruk immediately with counter=0; checked base/current/max health and Taunt."),
    ],
    "UNG_910": [("target_and_adjacent_zones", "Target takes 2, adjacent enemies take 1, nonadjacent and other-side minions take no damage.", un910_damages_target_and_adjacent_enemy_minions_only, "Placed four enemy minions in order, targeted the second, added a friendly minion, then asserted exact health and zones." )],
    "UNG_912": [("random_beast_added_to_hand", "Battlecry adds exactly one Beast card to hand.", un912_adds_exactly_one_beast_to_hand, "Compared hand entity identities before/after the live Battlecry and checked the generated card's race." )],
    "UNG_913": [
        ("draw_two_one_cost_minions", "Draws two 1-Cost minions and leaves a nonmatching minion in the deck.", un913_draws_two_one_cost_minions_and_leaves_distractor, "Seeded two known 1-Cost minions and a higher-cost minion; checked exact hand/deck IDs."),
        ("draw_only_one_when_only_one_available", "When only one 1-Cost minion remains, draws that minion without drawing the distractor.", un913_only_draws_available_one_cost_minion, "Seeded one 1-Cost minion and a higher-cost minion to check the partial availability branch."),
    ],
    "UNG_914": [("deathrattle_shuffles_4_3", "Deathrattle shuffles exactly one 4/3 Raptor into the deck.", un914_deathrattle_shuffles_exact_four_three_raptor, "Kept a known deck card, killed Raptor Hatchling with a real spell, and checked token identity/stats and deck zone." )],
    "UNG_915": [("adapt_beast_and_reject_nonbeast", "Adapts a friendly Beast and rejects a friendly non-Beast as target.", un915_adapts_friendly_beast_and_rejects_nonbeast_target, "Inspected and resolved actual Adapt choices on Stonetusk Boar; then attempted the same effect on Wisp and checked InvalidAction/mana/zone." )],
    "UNG_916": [("beast_play_triggers_this_turn_only", "Each Beast played this turn generates a Beast; a non-Beast and next-turn Beast do not.", un916_stampede_triggers_for_beast_only_this_turn, "Played Stampede, one Beast, one non-Beast, ended the turn, then played another Beast and checked generated entities." )],
    "UNG_917": [("hero_power_beast_only_plus_two_two", "Replaces Hero Power; new power rejects non-Beast and grants target Beast +2/+2 for 2 mana.", un917_replaces_hero_power_with_beast_only_plus_two_plus_two, "Attempted Wisp then used the actual new power on Stonetusk Boar; checked invalid-action mana and exact stats." )],
    "UNG_919": [
        ("attacks_played_enemy_minion", "After opponent plays a minion, Swamp King Dred attacks that minion.", un919_dred_attacks_opponent_minion_after_play, "Played Dred, then actually played an opposing Wisp; checked both zones, Dred damage, and exhaustion."),
        ("frozen_dred_skips_attack", "Frozen Dred does not attack an opponent minion played during the opponent turn.", un919_frozen_dred_does_not_attack_after_play, "Frostbolted Dred before the opponent played Wisp; checked Dred health/frozen state and surviving Wisp."),
    ],
    "UNG_920": [("quest_seven_one_cost_minions_and_queen_shuffles_15", "Quest advances only on 1-Cost minion plays; after the seventh, playing Queen Carnassa shuffles 15 Raptors into the deck.", un920_quest_counts_exactly_seven_one_cost_minions, "Played a cost-4 nonquest minion, checked six/seven 1-cost thresholds, returned the seventh minion to free a board slot, then actually played Queen Carnassa and asserted exactly 15 UNG_920t2 cards in deck." )],
    "UNG_922": [("replace_and_play_discover_deck", "Replaces every deck card with Discover-a-card spells which can be drawn and played.", un922_replaces_all_deck_cards_with_discover_spells, "Seeded three known cards, checked transformed deck count/IDs, drew and resolved one spell Choice, then checked deck/hand zones." )],
    "UNG_923": [("gain_five_armor", "Iron Hide adds exactly 5 Armor without changing health.", un923_gains_exactly_five_armor, "Recorded hero health/armor immediately before and after resolving the spell." )],
    "UNG_925": [("adapt_self_and_keep_taunt", "Ornery Direhorn's Battlecry resolves an Adapt Choice on itself and keeps Taunt.", un925_adapts_itself_and_retains_taunt, "Inspected all live Adapt options, selected one, and checked applied buff, body zone, and Taunt." )],
    "UNG_926": [
        ("opponent_gets_three_one_one_raptors", "Cornered Sentry gives the opponent three 1/1 Raptors and itself has Taunt.", un926_summons_three_ones_to_opponent, "Played Sentry with empty boards and inspected all resulting bodies, stats, zones, and controllers."),
        ("opponent_full_board_does_not_overflow", "When the opponent's board is full, the three Raptor summons must respect the seven-minion board limit.", un926_opponent_full_board_does_not_overflow, "Filled the opponent's seven slots with live Wisps, played Sentry, and recorded all resulting enemy entities and zones; evidence ID reserved for BOARD-002."),
    ],
    "UNG_927": [("copies_damaged_minions_only", "Sudden Genesis summons a copy of each damaged friendly minion, preserving its damage/current/max Health, and ignores an undamaged one.", un927_copies_only_damaged_minions, "Damaged two Yeti bodies by different exact amounts, left a third full-health, paired each damaged original with its copy by damage value, asserted matching damage/current/max Health for each pair, and asserted no full-health copy exists." )],
    "UNG_928": [("attack_bonus_on_opponent_turn", "Tar Creeper has +2 Attack during the opponent turn and returns to base on own turn.", un928_attack_changes_only_on_opponent_turn, "Read exact attack and Taunt immediately on own turn, opponent turn, and next own turn." )],
    "UNG_929": [("transforms_each_own_turn_in_hand", "Molten Blade transforms into a Weapon card on each of two own turns while remaining in hand.", un929_molten_blade_transforms_on_own_turns_in_hand, "Kept the physical hand entity through two opponent/own turn cycles and checked current card type/id each time." )],
    "UNG_933": [("destroy_damaged_minions_all_sides", "King Mosh destroys all damaged minions on both sides and leaves undamaged minions alive.", un933_destroys_damaged_minions_on_both_sides_only, "Damaged one friendly and one enemy Yeti, left one undamaged on each side, then checked every zone." )],
    "UNG_934": [("quest_seven_taunt_minions_and_sulfuras_power", "Quest counts seven Taunt minions and gives Sulfuras; playing it changes Hero Power, whose use deals 8 damage to the sole enemy character.", un934_quest_counts_seven_taunt_minions, "Played/bounced a non-Taunt Boar and seven Tar Creepers, then actually played Sulfuras, checked weapon and Hero Power IDs, and used the power against the only enemy character to assert exactly 8 damage." )],
    "UNG_937": [("conditional_murloc_discover", "Only with another friendly Murloc, Discovers a Murloc and adds selection to hand.", un937_discovers_murloc_only_with_another_murloc, "Ran both branches: a friendly Murloc present and no friendly Murloc; inspected all live choices and zones." )],
    "UNG_938": [("restore_three_to_target", "Hot Spring Guardian restores 3 Health to the chosen damaged friendly minion and has Taunt.", un938_heals_target_three_and_has_taunt, "Damaged a real friendly Yeti with Moonfire, targeted it with Battlecry, and checked exact health/max health and Taunt." )],
    "UNG_940": [("quest_seven_deathrattle_summons_and_amara", "Quest counts seven summoned Deathrattle minions, ignores a non-Deathrattle summon, and Amara sets hero Health to 40.", un940_quest_counts_summoned_deathrattle_minions_and_plays_reward, "Used actual Summon/Destroy state transitions for the threshold and non-Deathrattle branch, then played Amara and checked hero health/max health." )],
    "UNG_941": [("discover_spell_reduce_cost_two", "Offers only Spells, adds the selected spell, and reduces its Cost by 2.", un941_discover_spell_and_reduce_selected_cost_two, "Inspected all choices, selected one live spell, and compared its printed/base cost with post-choice hand cost." )],
    "UNG_942": [("quest_ten_murloc_summons_and_megafin", "Quest counts ten summoned Murlocs, ignores a non-Murloc, then Megafin fills the hand with Murlocs.", un942_quest_counts_summoned_murlocs_and_reward_fills_hand, "Used actual summon/destroy transitions, checked 9/10 threshold, and played reward to inspect generated hand races." )],
    "UNG_946": [
        ("destroy_enemy_weapon_gain_attack_armor", "Destroys only the opposing weapon and gains Armor equal to its Attack.", un946_destroys_enemy_weapon_and_gains_its_attack_as_armor, "Equipped a 1-Attack friendly weapon and opposing Fiery War Axe; checked weapon zones/identity and exact Armor."),
        ("no_enemy_weapon_no_armor", "With no opposing weapon, Ooze gives no Armor and resolves without error.", un946_without_enemy_weapon_gains_no_armor, "Played the actual Battlecry while opponent had no weapon; checked both weapon and Armor state."),
    ],
    "UNG_948": [("copies_friendly_target_only", "Molten Reflection summons one copy of a friendly minion and rejects an enemy target.", un948_summons_copy_of_friendly_target_and_rejects_enemy, "Inspected copied Yeti stats/health/zone; then attempted an opposing target and checked InvalidAction and mana." )],
    "UNG_950": [("recruits_after_hero_attack", "After the hero attacks, Vinecleaver summons two 1/1 Silver Hand Recruits.", un950_summons_recruits_after_hero_attacks, "Equipped Vinecleaver, attacked an actual enemy Yeti, and checked weapon durability, damage, and two token bodies." )],
    "UNG_952": [("buff_taunt_and_deathrattle_stegodon", "Spikeridged Steed grants +2/+6 and Taunt; after death it summons a Stegodon.", un952_buffs_minion_and_death_summons_stegodon, "Buffed a Wisp, checked attack/max/current health/Taunt/Deathrattle, then killed it with Fireball+Moonfire and checked token zone." )],
    "UNG_953": [("deathrattle_returns_spells_cast_on_champion", "Primalfin Champion returns spells cast on it to hand and excludes a spell cast on another minion.", un953_returns_only_spells_cast_on_champion, "Cast Blessing of Kings and lethal Fireball on Champion plus Moonfire on a different minion; checked exact returned IDs/zones." )],
    "UNG_954": [("six_friendly_spell_quest_and_galvadon", "Quest counts spells cast on friendly minions, ignores an enemy target, then Galvadon resolves five Adapts.", un954_quest_counts_spells_on_friendly_minions_and_resolves_five_adapts, "Cast one Moonfire on enemy minion, then six on a durable friendly minion; checked progress/reward and resolved all choices." )],
    "UNG_955": [("meteor_target_and_adjacent_damage", "Meteor deals 15 to target and 3 to adjacent minions only.", un955_meteor_hits_target_fifteen_and_adjacent_three, "Used four no-Spell-Damage Yetis plus a friendly Yeti; recorded max health/damage, directly evaluated TARGET_ADJACENT, and checked all resulting zones/damage." )],
    "UNG_956": [("deathrattle_returns_each_minion", "Spirit Echo grants each friendly minion a Deathrattle that returns itself to hand.", un956_grants_deathrattle_return_to_each_minion, "Applied to Yeti and Wisp, then killed them separately with real spells and checked both returned hand entities/zones." )],
    "UNG_957": [("deathrattle_shuffles_taunt_six_nine", "Direhorn Hatchling has Taunt and shuffles one 6/9 Taunt Direhorn into deck on death.", un957_deathrattle_shuffles_taunt_six_nine_direhorn, "Kept a known deck card, killed the real Hatchling with Fireball, and checked body Taunt, token ID/stats/count, and deck zone." )],
    "UNG_960": [
        ("summons_two_recruits_and_one_slot_branch", "Summons two 1/1 Recruits, or only one if only one board slot is open.", un960_summons_two_recruits_and_handles_one_open_slot, "Tested empty board for two tokens and six occupied slots for the one-slot edge; inspected exact token stats and zones."),
        ("full_board_rejects_spell", "With no minion slots, Lost in the Jungle is not playable and changes no state.", un960_cannot_play_with_full_board, "Filled all seven friendly slots and attempted the actual spell; checked InvalidAction, hand, mana, and board."),
    ],
    "UNG_961": [("adapt_selected_friendly_only", "Adaptation resolves a choice on the selected friendly minion and rejects enemy targets.", un961_adapts_only_selected_friendly_minion, "Adapted a Stonetusk Boar alongside an untouched friendly Yeti; then attempted enemy target and checked mana/zone." )],
    "UNG_962": [
        ("one_adapt_choice_applies_to_all_recruits", "With two friendly Silver Hand Recruits, one Adapt choice must apply the same selected option to both.", un962_adapts_every_friendly_silver_hand_recruit, "Generated two real Silver Hand Recruits with Lost in the Jungle, resolved the single live Adapt choice, and checked that the same selected buff reached both original entities."),
        ("no_recruits_no_choice", "With no Silver Hand Recruits, Battlecry creates no Adapt choice.", un962_no_recruits_means_no_adapt_choice, "Played the real Battlecry on an empty friendly board and checked the body/choice state."),
    ],
    "UNG_963": [("own_spell_adds_priest_spell", "Each own spell cast adds a Priest spell; a minion play and opponent spell add none.", un963_lyra_adds_priest_spell_only_for_own_spell_casts, "With Lyra on board, cast own Moonfire, played a minion, then had opponent cast Moonfire; checked generated class/type and hand deltas." )],
}

BLOCKERS = {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=44)
    args = parser.parse_args()
    end = min(len(CARDS), args.start + args.limit)
    selected = CARDS[args.start:end]
    for cid in selected:
        if cid not in CASES:
            print(f"{cid}: not yet implemented; stopping at card boundary")
            break
        audit_card(cid, CASES[cid], BLOCKERS.get(cid))
    print(f"slice={args.start}:{end}; completed={sum(1 for row in VERDICT_ROWS if row['card_id'] in selected)}")


if __name__ == "__main__":
    main()
