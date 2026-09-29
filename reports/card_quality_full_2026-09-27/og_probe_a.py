"""Per-card live-game tests for the first 42 frozen OG YELLOW collectibles."""

import csv
import logging
import random
import sys
import traceback
from collections import Counter
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
import fireplace.cards as carddb
from fireplace.managers import BaseObserver

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import MOONFIRE, WISP, prepare_empty_game  # noqa: E402

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

PROBE = HERE / "og_probe_a.csv"
VERDICT = HERE / "og_verdict_a.csv"
BASELINE = HERE / "og_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
MECHANISMS = HERE / "card_mechanism.csv"
QUALITY = HERE / "card_quality.csv"
ISSUES = HERE / "mechanism_issues.csv"
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
CARDS = [row["card_id"] for row in BASE_ROWS[:42]]
assert len(CARDS) == 42 and CARDS[0] == "OG_006" and CARDS[-1] == "OG_131"
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


def prepare_card(cid):
    """Replace only this card's old rows when its live tests actually start."""
    PROBE_ROWS[:] = [row for row in PROBE_ROWS if row["card_id"] != cid]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def game(class1=CardClass.MAGE, class2=None, seed=417):
    """Use an empty Wild game with deterministic Fireplace and Python RNGs."""
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


def checked(observed, condition):
    assert condition, observed
    return observed


def add_case(cid, case_id, expected, func, notes, covers):
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
                       "observed": observed, "outcome": outcome,
                       "notes": f"{notes}; scope_asserted={'|'.join(covers)}"})
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    return outcome


def finish_card(cid, cases, blocker=None, audit_note=""):
    own = [row for row in PROBE_ROWS if row["card_id"] == cid]
    assert own and len({row["case_id"] for row in own}) == len(own), cid
    errors = [row for row in own if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in own if row["outcome"] == "inconclusive"]
    covered = set().union(*(set(case[4]) for case in cases))
    expected_scope = set(LABELS[cid])
    if errors:
        status = "RED"
        reason = "实测偏差：" + "；".join(
            f"{r['case_id']} 预期[{r['expected']}]，实际[{r['observed']}]" for r in errors
        )
    elif unresolved:
        status = "YELLOW"
        reason = "行为仍未决：" + "；".join(f"{r['case_id']}={r['observed']}" for r in unresolved)
    elif blocker:
        status, reason = "YELLOW", blocker
    elif covered != expected_scope:
        status = "YELLOW"
        reason = f"本轮断言未覆盖全部机制标签；未覆盖={sorted(expected_scope - covered)}。"
    else:
        status = "GREEN"
        reason = "针对性对局断言通过：" + "；".join(
            f"{row['case_id']}={row['observed']}" for row in own
        )
    m = MASTER_ROWS[cid]
    q = OLD_QUALITY.get(cid, {})
    affected = []
    for issue in read_csv(ISSUES):
        cards = set((issue.get("confirmed_cards", "") + "|" + issue.get("candidate_cards", "")).split("|"))
        if cid in cards:
            affected.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    tests = m.get("test_refs_candidate", "") or "无候选既有测试引用"
    notes = (
        f"EN={m.get('card_text_en', '')}; ZH={m.get('card_text_zh', '')}; "
        f"source={m.get('python_source', '') or '未发现 Python 卡脚本'}; "
        f"existing_tests={tests}; previous_card_audit={q.get('reason', '无')}; "
        f"previous_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
        f"prior_cross_card_issues={' / '.join(affected) if affected else '无'}; "
        f"audit_scope=本轮所列实际运行断言。"
    )
    if audit_note:
        notes += f"; audit_note={audit_note}"
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != cid]
    VERDICT_ROWS.append({"card_id": cid, "status": status,
                         "mechanic_scope": "|".join(LABELS[cid]), "reason": reason,
                         "probe_file": PROBE.name, "notes": notes})
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}")
    return status


def audit_card(cid, tests, blocker=None, audit_note=""):
    """Run and persist each card immediately; each test is (id, expected, fn, notes, scope)."""
    for case_id, expected, fn, notes, covers in tests:
        add_case(cid, case_id, expected, fn, notes, covers)
    return finish_card(cid, tests, blocker=blocker, audit_note=audit_note)


def p006_power_and_token():
    g = game(CardClass.PALADIN)
    p = g.player1
    card = play(p, "OG_006")
    power_id = p.hero.power.id
    p.hero.power.use()
    card.destroy()
    g.end_turn()
    g.end_turn()
    p.hero.power.use()
    tokens = [m for m in p.field if m.id == "OG_006a"]
    return checked(f"card={card.zone.name};hero_power={power_id};murloc_tokens={[(m.atk,m.health,m.zone.name) for m in tokens]}",
                   card.zone == Zone.GRAVEYARD and power_id == "OG_006b" and len(tokens) == 2 and all(m.atk == m.health == 1 for m in tokens))


def p023_totem_count_buff():
    g = game(CardClass.SHAMAN)
    p, enemy = g.player1, g.player2
    target = summon(p, WISP)
    summon(p, "CS2_050")
    summon(p, "CS2_051")
    summon(enemy, "CS2_052")
    before = (target.atk, target.max_health)
    spell = play(p, "OG_023", target)
    after = (target.atk, target.max_health)
    return checked(f"friendly_totems=2;enemy_totem=1;target_before={before};after={after};spell={spell.zone.name}",
                   after == (before[0] + 2, before[1] + 2) and spell.zone == Zone.GRAVEYARD)


def p026_unlock_overload():
    g = game(CardClass.SHAMAN)
    p = g.player1
    p.overloaded = 2
    p.overload_locked = 1
    card = play(p, "OG_026")
    return checked(f"overloaded={p.overloaded};locked={p.overload_locked};card={card.zone.name};mana={p.mana}",
                   p.overloaded == 0 and p.overload_locked == 0 and card in p.field)


def p027_evolve_domain():
    observations = []
    replacement_ids = set()
    for seed in range(16):
        g = game(CardClass.SHAMAN, seed=seed + 110)
        p, enemy = g.player1, g.player2
        own0 = summon(p, WISP)
        own1 = summon(p, "CS2_182")
        foe = summon(enemy, "CS2_182")
        before = [(m.data.cost, m.id) for m in (own0, own1)]
        play(p, "OG_027")
        after = [(m.id, m.data.cost, m.zone.name) for m in p.field]
        foe_state = (foe.id, foe.atk, foe.max_health, foe.zone.name)
        assert len(p.field) == 2 and all(new_id != old[1] for (new_id, _, _), old in zip(after, before)), (seed, before, after)
        assert all(zone == Zone.PLAY.name for _, _, zone in after), (seed, after)
        assert [cost for _, cost, _ in after] == [cost + 1 for cost, _ in before], (seed, before, after)
        assert foe_state == ("CS2_182", foe.data.atk, foe.data.health, Zone.PLAY.name), (seed, foe_state)
        observations.append(f"{seed}:{before}->{after}")
        replacement_ids.update(card_id for card_id, _, _ in after)
    return checked(f"16_seeded_friendly_transformations={observations};replacement_ids={len(replacement_ids)};enemy_unchanged=true",
                   len(observations) == 16 and len(replacement_ids) > 2)


def p028_totem_lifetime_discount():
    g = game(CardClass.SHAMAN)
    p, enemy = g.player1, g.player2
    card = p.give("OG_028")
    initial = card.cost
    summon(enemy, "CS2_052")
    after_enemy_totem = card.cost
    summon(p, "CS2_050")
    after_one = card.cost
    first_totem = summon(p, "CS2_051")
    after_two = card.cost
    first_totem.destroy()
    second_totem = [m for m in p.field if m.race == Race.TOTEM][0]
    second_totem.destroy()
    after_totems_die = card.cost
    taunt = card.taunt
    card.play()
    return checked(f"costs={initial},{after_enemy_totem},{after_one},{after_two},{after_totems_die};taunt={taunt};played_zone={card.zone.name}",
                   (initial, after_enemy_totem, after_one, after_two, after_totems_die) == (6, 6, 5, 4, 4) and taunt and card in p.field)


def p031_hammer_deathrattle():
    g = game(CardClass.SHAMAN)
    p, enemy = g.player1, g.player2
    hammer = play(p, "OG_031")
    p.hero.attack(enemy.hero)
    g.end_turn()
    g.end_turn()
    p.hero.attack(enemy.hero)
    elementals = [m for m in p.field if m.id == "OG_031a"]
    return checked(f"weapon={hammer.zone.name};durability={hammer.durability};elementals={[(m.atk,m.health,m.zone.name) for m in elementals]};enemy_hero={enemy.hero.health}",
                   hammer.zone == Zone.GRAVEYARD and len(elementals) == 1 and (elementals[0].atk, elementals[0].health) == (4, 2))


def p033_tentacles_return():
    g = game(CardClass.WARRIOR)
    p, enemy = g.player1, g.player2
    tentacles = play(p, "OG_033")
    p.hero.attack(enemy.hero)
    g.end_turn()
    g.end_turn()
    p.hero.attack(enemy.hero)
    return checked(f"weapon_zone={tentacles.zone.name};in_hand={tentacles in p.hand};weapon={p.weapon};hand={[c.id for c in p.hand]}",
                   tentacles.zone == Zone.HAND and tentacles in p.hand and p.weapon is None)


def p034_attack_gate():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    swarmer = play(p, "OG_034")
    play(p, "CS2_091")
    target = summon(enemy, WISP)
    before = swarmer.can_attack()
    g.end_turn()
    g.end_turn()
    after_refresh = swarmer.can_attack()
    blocked = False
    try:
        swarmer.attack(target)
    except Exception:
        blocked = True
    p.hero.attack(enemy.hero)
    after_hero_attack = swarmer.can_attack()
    if after_hero_attack:
        swarmer.attack(target)
    return checked(f"initial={before};after_refresh_without_hero={after_refresh};blocked_attack={blocked};after_hero_attack={after_hero_attack};target_zone={target.zone.name};hero={p.hero.atk} atk", 
                   not before and not after_refresh and blocked and after_hero_attack and target.zone == Zone.GRAVEYARD)


def p042_deck_minion_only_own_endturn():
    g = game(CardClass.MAGE)
    p = g.player1
    minions = [p.give("CS2_182"), p.give(WISP)]
    for minion in minions:
        minion.shuffle_into_deck()
    spell = p.give(MOONFIRE)
    spell.shuffle_into_deck()
    yshaarj = play(p, "OG_042")
    before = [c.id for c in p.deck]
    g.end_turn()
    after = [c.id for c in p.deck]
    summoned = [m for m in minions if m in p.field]
    remaining = [m for m in minions if m in p.deck]
    g.end_turn()
    after_opponent = [m for m in minions if m in p.field]
    remaining_zone = remaining[0].zone if len(remaining) == 1 else None
    return checked(f"deck_before={before};deck_after_own_end={after};summoned_own_end={[m.id for m in summoned]};remaining_minions={[(m.id,m.zone.name) for m in remaining]};summoned_after_opponent_end={[m.id for m in after_opponent]};Yshaarj={yshaarj.zone.name};remaining_deck={[c.id for c in p.deck]}",
                   yshaarj in p.field and len(summoned) == 1 and len(remaining) == 1 and MOONFIRE in after and after_opponent == summoned and len(after_opponent) == 1 and remaining_zone in (Zone.DECK, Zone.HAND))


def p042_full_board_keeps_deck_minion():
    g = game(CardClass.MAGE)
    p = g.player1
    minion = p.give("CS2_182")
    minion.shuffle_into_deck()
    for _ in range(6):
        summon(p, WISP)
    yshaarj = play(p, "OG_042")
    g.end_turn()
    return checked(f"field_count={len(p.field)};Yshaarj={yshaarj.zone.name};deck={[c.id for c in p.deck]};minion_zone={minion.zone.name}",
                   len(p.field) == 7 and yshaarj in p.field and minion in p.deck and minion.zone == Zone.DECK)


def p044_fandral_combines():
    g = game(CardClass.DRUID)
    p = g.player1
    p.give("ICC_832").play(choose="ICC_832a")
    g.end_turn()
    g.end_turn()
    fandral = play(p, "OG_044")
    before_rage = (p.hero.atk, p.hero.armor)
    rage = p.give("OG_047")
    rage.play()
    rage_state = (p.hero.atk, p.hero.armor)
    power = p.hero.power
    before_power = (p.hero.atk, p.hero.armor)
    power.use()
    after_power = (p.hero.atk, p.hero.armor)
    return checked(f"fandral={fandral.zone.name};before_feral_rage={before_rage};after_feral_rage={rage_state};power={power.id};before_power={before_power};after_power={after_power};rage={rage.zone.name};choice={p.choice}",
                   fandral in p.field and rage_state == (before_rage[0] + 4, before_rage[1] + 8) and after_power == (before_power[0] + 3, before_power[1] + 3) and rage.zone == Zone.GRAVEYARD and p.choice is None)


def p044_normal_choice_after_departure():
    g = game(CardClass.DRUID)
    p = g.player1
    fandral = play(p, "OG_044")
    fandral.destroy()
    rage = p.give("OG_047")
    rage.play(choose="OG_047a")
    rage_state = (p.hero.atk, p.hero.armor)
    normal_power_results = []
    for branch, option in (("armor", "ICC_832pa"), ("attack", "ICC_832pb")):
        power_game = game(CardClass.DRUID, seed=440 + len(normal_power_results))
        power_player = power_game.player1
        power_player.give("ICC_832").play(choose="ICC_832a")
        before = (power_player.hero.atk, power_player.hero.armor)
        power = power_player.hero.power
        power.use(choose=option)
        after = (power_player.hero.atk, power_player.hero.armor)
        normal_power_results.append((branch, before, after, power_player.choice))
    return checked(f"fandral={fandral.zone.name};feral_rage_after_departure={rage_state};normal_hero_power_branches={normal_power_results}",
                   fandral.zone == Zone.GRAVEYARD and rage_state == (4, 0) and
                   normal_power_results[0][2] == (normal_power_results[0][1][0], normal_power_results[0][1][1] + 3) and
                   normal_power_results[1][2] == (normal_power_results[1][1][0] + 3, normal_power_results[1][1][1]) and
                   all(row[3] is None for row in normal_power_results))


def p045_infest_deathrattles():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    minions = [summon(p, WISP), summon(p, "CS2_231")]
    enemy_minion = summon(enemy, "CS2_182")
    assert not enemy_minion.has_deathrattle, enemy_minion.id
    infest = play(p, "OG_045")
    assert not enemy_minion.has_deathrattle, (enemy_minion.id, enemy_minion.has_deathrattle)
    gained = []
    for minion in minions:
        assert minion.has_deathrattle, (minion.id, minion.has_deathrattle)
        minion.destroy()
        fresh = [c for c in p.hand if c.type == CardType.MINION and c.race == Race.BEAST]
        assert len(fresh) == len(gained) + 1, (minion.id, [(c.id, c.race) for c in fresh])
        gained = fresh
    return checked(f"infest={infest.zone.name};dead_minions={[m.zone.name for m in minions]};enemy={(enemy_minion.id, enemy_minion.zone.name, enemy_minion.has_deathrattle)};random_beasts={[c.id for c in gained]}",
                   infest.zone == Zone.GRAVEYARD and all(m.zone == Zone.GRAVEYARD for m in minions) and not enemy_minion.has_deathrattle and enemy_minion.zone == Zone.PLAY and len(gained) == 2)


def p047_attack_branch():
    g = game(CardClass.DRUID)
    p, enemy = g.player1, g.player2
    spell = play(p, "OG_047", choose="OG_047a")
    attack = p.hero.atk
    armor = p.hero.armor
    p.hero.attack(enemy.hero)
    dealt = 30 - enemy.hero.health
    g.end_turn()
    g.end_turn()
    return checked(f"spell={spell.zone.name};attack_before={attack};armor={armor};hero_damage={dealt};attack_next_turn={p.hero.atk}",
                   spell.zone == Zone.GRAVEYARD and attack == 4 and armor == 0 and dealt == 4 and p.hero.atk == 0)


def p047_armor_branch():
    g = game(CardClass.DRUID)
    p = g.player1
    spell = play(p, "OG_047", choose="OG_047b")
    armor, attack = p.hero.armor, p.hero.atk
    g.end_turn()
    g.end_turn()
    return checked(f"spell={spell.zone.name};armor={armor};attack={attack};armor_next_turn={p.hero.armor}",
                   spell.zone == Zone.GRAVEYARD and armor == 8 and attack == 0 and p.hero.armor == 8)


def p048_beast_buff_and_draw():
    g = game(CardClass.DRUID)
    p = g.player1
    beast = summon(p, "OG_179")
    known = p.give(WISP)
    known.shuffle_into_deck()
    before = (beast.atk, beast.max_health)
    spell = play(p, "OG_048", beast)
    draws = [c.id for c in p.hand if c.id == WISP]
    return checked(f"beast={beast.id};before={before};after={(beast.atk, beast.max_health)};drawn={draws};spell={spell.zone.name}",
                   (beast.atk, beast.max_health) == (before[0] + 2, before[1] + 2) and draws == [WISP] and spell.zone == Zone.GRAVEYARD)


def p048_nonbeast_no_draw():
    g = game(CardClass.DRUID)
    p = g.player1
    minion = summon(p, WISP)
    known = p.give(MOONFIRE)
    known.shuffle_into_deck()
    spell = play(p, "OG_048", minion)
    return checked(f"target={minion.id};stats={(minion.atk,minion.max_health)};deck={[c.id for c in p.deck]};hand={[c.id for c in p.hand]};spell={spell.zone.name}",
                   (minion.atk, minion.max_health) == (3, 3) and known in p.deck and MOONFIRE not in [c.id for c in p.hand] and spell.zone == Zone.GRAVEYARD)


def p051_spend_remaining_mana():
    g = game(CardClass.DRUID)
    p = g.player1
    p.max_mana = 5
    card = p.give("OG_051")
    before = p.mana
    card.play()
    after = (card.atk, card.health, card.max_health, p.mana, card.zone.name)
    return checked(f"mana_before={before};after_stats_mana_zone={after}",
                   before == 5 and after == (5, 5, 5, 0, Zone.PLAY.name))


def p061_minion_target_and_dog():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    target = summon(enemy, "CS2_182")
    before = target.health
    spell = play(p, "OG_061", target)
    dogs = [m for m in p.field if m.id == "OG_061t"]
    return checked(f"target={target.id};damage={before-target.health};target_zone={target.zone.name};dogs={[(m.atk,m.health) for m in dogs]};spell={spell.zone.name}",
                   before - target.health == 1 and target.zone == Zone.PLAY and len(dogs) == 1 and (dogs[0].atk, dogs[0].health) == (1, 1) and spell.zone == Zone.GRAVEYARD)


def p061_hero_target():
    g = game(CardClass.HUNTER)
    p, enemy = g.player1, g.player2
    spell = play(p, "OG_061", enemy.hero)
    dogs = [m for m in p.field if m.id == "OG_061t"]
    return checked(f"enemy_hero_health={enemy.hero.health};dogs={len(dogs)};spell={spell.zone.name}",
                   enemy.hero.health == 29 and len(dogs) == 1 and spell.zone == Zone.GRAVEYARD)


def p070_no_combo():
    g = game(CardClass.ROGUE)
    p = g.player1
    combo_before = p.combo
    card = play(p, "OG_070")
    return checked(f"combo_before={combo_before};attack_health={(card.atk, card.health)};combo_after_play={p.combo}",
                   not combo_before and (card.atk, card.health) == (1, 2))


def p070_combo():
    g = game(CardClass.ROGUE)
    p = g.player1
    coin = play(p, "GAME_005")
    card = play(p, "OG_070")
    return checked(f"coin={coin.zone.name};attack_health={(card.atk, card.health)};combo={p.combo}",
                   (card.atk, card.health) == (2, 3) and p.combo)


def p072_discover_deathrattle_card():
    g = game(CardClass.ROGUE, seed=727)
    p = g.player1
    spell = play(p, "OG_072")
    options = list(p.choice.cards)
    assert len(options) == 3 and all(card.has_deathrattle for card in options), [(c.id, c.has_deathrattle) for c in options]
    selected = options[1]
    p.choice.choose(selected)
    return checked(f"spell={spell.zone.name};options={[c.id for c in options]};chosen={selected.id};hand={[c.id for c in p.hand]};choice={p.choice}",
                   spell.zone == Zone.GRAVEYARD and p.choice is None and selected in p.hand and sum(c in p.hand for c in options) == 1)


def p073_draw_and_copy():
    g = game(CardClass.ROGUE)
    p = g.player1
    known = p.give(WISP)
    known.shuffle_into_deck()
    spell = play(p, "OG_073")
    copies = [c for c in p.hand if c.id == WISP]
    return checked(f"known={known.zone.name};wisp_hand={[c.id for c in copies]};deck={[c.id for c in p.deck]};spell={spell.zone.name}",
                   len(copies) == 3 and known in copies and known not in p.deck and spell.zone == Zone.GRAVEYARD)


def p080_battlecry_and_deathrattle_toxins():
    expected = {"OG_080b", "OG_080c", "OG_080d", "OG_080e", "OG_080f"}
    samples = []
    for seed in range(16):
        g = game(CardClass.ROGUE, seed=seed + 880)
        p = g.player1
        xaril = play(p, "OG_080")
        first = [c.id for c in p.hand if c.id in expected]
        assert len(first) == 1, (seed, [c.id for c in p.hand])
        xaril.destroy()
        toxins = [c.id for c in p.hand if c.id in expected]
        assert len(toxins) == 2 and set(first) <= set(toxins) and xaril.zone == Zone.GRAVEYARD, (seed, toxins, xaril.zone)
        samples.extend(toxins)
    observed = sorted(Counter(samples).items())
    return checked(f"16 seeded Battlecries+Deathrattles;toxin_counts={observed}",
                   len(set(samples)) > 1 and set(samples) <= expected)


def p081_destroy_frozen_only():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    frozen = summon(enemy, "CS2_182")
    frozen.frozen = True
    spell = play(p, "OG_081", frozen)
    return checked(f"was_frozen=true;target_zone={frozen.zone.name};spell={spell.zone.name}",
                   frozen.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD)


def p081_reject_unfrozen_target():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon(enemy, "CS2_182")
    spell = p.give("OG_081")
    mana = p.mana
    rejected = False
    try:
        spell.play(target=target)
    except Exception:
        rejected = True
    return checked(f"unfrozen_target={target.id};rejected={rejected};spell_zone={spell.zone.name};mana_before_after={mana},{p.mana}",
                   rejected and spell.zone == Zone.HAND and p.mana == mana and target.zone == Zone.PLAY)


def p082_spell_damage_two():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    kobold = play(p, "OG_082")
    before = enemy.hero.health
    spell = play(p, MOONFIRE, enemy.hero)
    return checked(f"kobold={kobold.zone.name};spell_damage={before-enemy.hero.health};enemy_hero={enemy.hero.health};spell={spell.zone.name}",
                   kobold in p.field and before - enemy.hero.health == 3 and spell.zone == Zone.GRAVEYARD)


def p083_enemy_minions_only():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    friendly = summon(p, "CS2_182")
    enemy_small = summon(enemy, WISP)
    enemy_large = summon(enemy, "CS2_182")
    enemy_hero_health = enemy.hero.health
    flamecaller = play(p, "OG_083")
    return checked(f"flamecaller={flamecaller.zone.name};friendly_health={friendly.health};enemy_small={enemy_small.zone.name};enemy_large_health={enemy_large.health};enemy_hero={enemy.hero.health}",
                   flamecaller in p.field and friendly.health == 5 and enemy_small.zone == Zone.GRAVEYARD and enemy_large.health == 4 and enemy.hero.health == enemy_hero_health)


def p085_freeze_eligible_enemy_only():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    frostcaller = play(p, "OG_085")
    friendly = summon(p, WISP)
    enemy_minion = summon(enemy, "CS2_182")
    play(p, "GAME_005")
    after_one = (enemy_minion.frozen, enemy.hero.frozen)
    assert sum(after_one) == 1, after_one
    play(p, "GAME_005")
    after_two = (enemy_minion.frozen, enemy.hero.frozen)
    return checked(f"frostcaller={frostcaller.zone.name};after_first={after_one};after_second={after_two};friendly_frozen={friendly.frozen}",
                   all(after_two) and not friendly.frozen and frostcaller in p.field)


def p086_spend_all_mana_damage():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    p.max_mana = 4
    target = summon(enemy, "CS2_182")
    target_health = target.health
    spell = play(p, "OG_086", target)
    return checked(f"mana_after={p.mana};damage={target_health-target.health};target_health={target.health};target_zone={target.zone.name};spell={spell.zone.name}",
                   p.mana == 0 and target_health - target.health == 4 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def p086_zero_mana_target():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    p.max_mana = 0
    target = summon(enemy, "CS2_182")
    spell = play(p, "OG_086", target)
    return checked(f"mana={p.mana};damage={target.damage};target={target.zone.name};spell={spell.zone.name}",
                   p.mana == 0 and target.damage == 0 and target.zone == Zone.PLAY and spell.zone == Zone.GRAVEYARD)


def p086_reject_hero_target():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    spell = p.give("OG_086")
    mana = p.mana
    rejected = False
    try:
        spell.play(target=enemy.hero)
    except Exception:
        rejected = True
    return checked(f"rejected_hero={rejected};spell={spell.zone.name};mana_before_after={mana},{p.mana};enemy_health={enemy.hero.health}",
                   rejected and spell.zone == Zone.HAND and p.mana == mana and enemy.hero.health == 30)


def p087_only_tracking_across_seeds():
    deck_ids = ["CS2_231", "CS2_182", "EX1_016"]
    observations = []
    for seed in range(12):
        g = game(CardClass.MAGE, seed=seed + 870)
        p = g.player1
        for card_id in deck_ids:
            card = p.give(card_id)
            card.shuffle_into_deck()
        seeded_cards = list(p.deck)
        class CastCapture(BaseObserver):
            def __init__(self):
                self.cast_ids = []

            def targeted_action(self, action, source, target, *args):
                if type(action).__name__ == "CastSpell":
                    self.cast_ids.append(target.id)

        capture = CastCapture()
        g.manager.register(capture)
        servant = play(p, "OG_087")
        assert len(capture.cast_ids) == 1, (seed, capture.cast_ids, servant.zone.name)
        hand_cards = [card.id for card in seeded_cards if card in p.hand]
        removed = [card.id for card in seeded_cards if card.zone == Zone.REMOVEDFROMGAME]
        assert servant.zone == Zone.PLAY and len(hand_cards) == 1 and len(removed) == 2, (seed, capture.cast_ids, hand_cards, removed)
        observations.append({"seed": seed, "actual_cast_spell_id": capture.cast_ids[0],
                             "drawn_from_tracking": hand_cards[0], "discarded_by_tracking": removed})
    random_pool = carddb.filter(collectible=True, type=CardType.SPELL, cost=range(0, 6), is_standard=False)
    detail = (f"12 actual CastSpell observer IDs={[row['actual_cast_spell_id'] for row in observations]};"
              f"independent_Wild_eligible_spell_pool_size={len(random_pool)};Tracking_draw/discard={observations};"
              f"source=fireplace/cards/wog/mage.py:41")
    assert len(random_pool) > 1 and set(row["actual_cast_spell_id"] for row in observations) != {"DS1_184"}, detail
    return detail


def p090_three_mage_spells():
    observations = []
    for seed in range(12):
        g = game(CardClass.MAGE, seed=seed + 900)
        p = g.player1
        spell = play(p, "OG_090")
        gained = list(p.hand)
        assert len(gained) == 3, (seed, [c.id for c in gained])
        assert all(c.type == CardType.SPELL and CardClass.MAGE in c.classes for c in gained), (seed, [(c.id,c.type,c.classes) for c in gained])
        assert spell.zone == Zone.GRAVEYARD, (seed, spell.zone)
        observations.append([c.id for c in gained])
    return checked(f"12 seeded results={observations}", len(observations) == 12)


def p094_buff_target():
    g = game(CardClass.PRIEST)
    p = g.player1
    target = summon(p, WISP)
    spell = play(p, "OG_094", target)
    return checked(f"target={(target.atk,target.health,target.max_health)};spell={spell.zone.name}",
                   (target.atk, target.health, target.max_health) == (3, 7, 7) and spell.zone == Zone.GRAVEYARD)


def p096_below_cthun_threshold():
    g = game(CardClass.PRIEST)
    p = g.player1
    cthun = p.cthun
    cthun.atk = 9
    p.hero.set_current_health(10)
    card = play(p, "OG_096")
    return checked(f"cthun_zone={cthun.zone.name};cthun_attack={cthun.atk};hero_health={p.hero.health};card={card.zone.name}",
                   cthun.zone == Zone.SETASIDE and cthun.atk == 9 and p.hero.health == 10 and card in p.field)


def p096_at_cthun_threshold():
    g = game(CardClass.PRIEST)
    p = g.player1
    cthun = p.cthun
    cthun.atk = 10
    p.hero.set_current_health(10)
    card = play(p, "OG_096")
    return checked(f"cthun_zone={cthun.zone.name};cthun_attack={cthun.atk};hero_health={p.hero.health};card={card.zone.name}",
                   cthun.zone == Zone.SETASIDE and cthun.atk == 10 and p.hero.health == 20 and card in p.field)


def p100_attack_threshold_sweep():
    g = game(CardClass.PRIEST)
    p, enemy = g.player1, g.player2
    small_own = summon(p, WISP)
    small_own.atk = 2
    large_own = summon(p, "CS2_182")
    large_own.atk = 3
    small_enemy = summon(enemy, WISP)
    small_enemy.atk = 1
    large_enemy = summon(enemy, "CS2_182")
    large_enemy.atk = 3
    card = play(p, "OG_100")
    return checked(f"card={card.zone.name};own_1_2={[small_own.zone.name]};own_3={large_own.zone.name};enemy_1={small_enemy.zone.name};enemy_3={large_enemy.zone.name}",
                   card.zone == Zone.GRAVEYARD and small_own.zone == Zone.GRAVEYARD and small_enemy.zone == Zone.GRAVEYARD and large_own.zone == Zone.PLAY and large_enemy.zone == Zone.PLAY)


def p101_random_minion_matches_spent_mana():
    results = []
    for seed in range(16):
        g = game(CardClass.PRIEST, seed=seed + 1010)
        p = g.player1
        p.max_mana = 5
        card = play(p, "OG_101")
        summoned = [m for m in p.field if m is not card]
        assert card.zone == Zone.GRAVEYARD and p.mana == 0 and len(summoned) == 1, (seed, card.zone, p.mana, [m.id for m in p.field])
        assert summoned[0].data.cost == 5 and summoned[0].zone == Zone.PLAY, (seed, summoned[0].id, summoned[0].data.cost, summoned[0].zone)
        results.append(summoned[0].id)
    return checked(f"spent_mana=5;16_seeded_minions={results};distinct={len(set(results))}", len(set(results)) > 1)


def p102_swap_friendly_stats():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    target = summon(p, "CS2_182")
    target_before = (target.atk, target.max_health, target.health)
    card = p.give("OG_102")
    legal = set(card.targets)
    assert target in legal and not any(candidate.controller is enemy for candidate in legal), [c.id for c in legal]
    card.play(target=target)
    target_after = (target.atk, target.max_health, target.health)
    card_after = (card.atk, card.max_health, card.health)
    return checked(f"target_before={target_before};target_after={target_after};darkspeaker_after={card_after};legal_target_ids={[c.id for c in legal]};zone={card.zone.name}",
                   target_after == (3, 6, 6) and card_after == target_before and card in p.field)


def p102_play_without_available_friendly_target():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    enemy_minion = summon(enemy, "CS2_182")
    enemy_before = (enemy_minion.atk, enemy_minion.health, enemy_minion.max_health)
    card = p.give("OG_102")
    legal = list(card.targets)
    assert not legal, [target.id for target in legal]
    card.play()
    return checked(f"available_targets={legal};enemy_before={enemy_before};enemy_after={(enemy_minion.atk, enemy_minion.health, enemy_minion.max_health)};card={(card.atk, card.health, card.max_health)};zone={card.zone.name}",
                   enemy_minion.zone == Zone.PLAY and (enemy_minion.atk, enemy_minion.health, enemy_minion.max_health) == enemy_before and (card.atk, card.health, card.max_health) == (3, 6, 6) and card in p.field)


def p104_healing_reverses_then_expires():
    g = game(CardClass.PRIEST)
    p = g.player1
    p.hero.set_current_health(20)
    embrace = play(p, "OG_104")
    active_flag = p.healing_as_damage
    power = p.hero.power
    power.use(target=p.hero)
    during_turn = p.hero.health
    g.end_turn()
    g.end_turn()
    expired_flag = p.healing_as_damage
    power = p.hero.power
    power.use(target=p.hero)
    next_turn = p.hero.health
    return checked(f"embrace={embrace.zone.name};active_flag={active_flag};health_during={during_turn};expired_flag={expired_flag};health_next_turn={next_turn}",
                   active_flag and during_turn == 18 and not expired_flag and next_turn == 20)


def p109_discard_and_death_draw():
    observations = []
    for seed in range(24):
        g = game(CardClass.WARLOCK, seed=1090 + seed)
        p = g.player1
        p.discard_hand()
        discarded_options = [p.give(WISP), p.give(MOONFIRE)]
        deck_card = p.give("CS2_182")
        deck_card.shuffle_into_deck()
        librarian = play(p, "OG_109")
        discarded = [c for c in discarded_options if c.zone == Zone.REMOVEDFROMGAME]
        retained = [c for c in discarded_options if c.zone == Zone.HAND]
        assert len(discarded) == len(retained) == 1, (seed, [(c.id,c.zone.name) for c in discarded_options])
        librarian.destroy()
        assert deck_card in p.hand and deck_card.id == "CS2_182" and librarian.zone == Zone.GRAVEYARD and retained[0] in p.hand, (seed, [c.id for c in p.hand], deck_card.zone, librarian.zone)
        observations.append((seed, discarded[0].id, retained[0].id, deck_card.zone.name, librarian.zone.name))
    return checked(f"24_seeded_battlecries_and_deathrattles={observations};discarded_ids={sorted({row[1] for row in observations})}",
                   {row[1] for row in observations} == {WISP, MOONFIRE})


def p113_trigger_friendly_summons():
    g = game(CardClass.WARLOCK)
    p, enemy = g.player1, g.player2
    councilman = play(p, "OG_113")
    on_play = councilman.atk
    summon(p, WISP)
    after_friendly = councilman.atk
    summon(enemy, WISP)
    after_enemy = councilman.atk
    return checked(f"attack_after_play={on_play};after_friendly_summon={after_friendly};after_enemy_summon={after_enemy};zone={councilman.zone.name}",
                   on_play == 1 and after_friendly == 2 and after_enemy == 2 and councilman in p.field)


def p114_spend_mana_and_summon_tokens():
    g = game(CardClass.WARLOCK)
    p = g.player1
    p.max_mana = 4
    ritual = play(p, "OG_114")
    tokens = [m for m in p.field if m.id == "OG_114a"]
    return checked(f"mana={p.mana};ritual={ritual.zone.name};tokens={[(m.atk,m.health,m.zone.name) for m in tokens]}",
                   p.mana == 0 and ritual.zone == Zone.GRAVEYARD and len(tokens) == 4 and all((m.atk,m.health)==(1,1) for m in tokens))


def p114_board_capacity():
    g = game(CardClass.WARLOCK)
    p = g.player1
    p.max_mana = 4
    for _ in range(6):
        summon(p, WISP)
    ritual = play(p, "OG_114")
    tokens = [m for m in p.field if m.id == "OG_114a"]
    return checked(f"mana={p.mana};board_count={len(p.field)};ritual={ritual.zone.name};tentacles={len(tokens)}",
                   p.mana == 0 and len(p.field) == 7 and len(tokens) == 1 and ritual.zone == Zone.GRAVEYARD)


def p116_random_damage_all_characters():
    ids = []
    damaged = Counter()
    for seed in range(48):
        g = game(CardClass.WARLOCK, seed=seed + 1160)
        p, enemy = g.player1, g.player2
        friendly = summon(p, "OG_153")
        hostile = summon(enemy, "OG_153")
        for minion in (friendly, hostile):
            minion.max_health = 30
            minion.set_current_health(30)
        chars = {"friendly_hero": p.hero, "enemy_hero": enemy.hero,
                 "friendly_minion": friendly, "enemy_minion": hostile}
        before = {label: obj.health for label, obj in chars.items()}
        play(p, "OG_116")
        losses = {label: before[label] - obj.health for label, obj in chars.items()}
        assert sum(losses.values()) == 9 and all(obj.zone == Zone.PLAY for label,obj in chars.items() if "minion" in label), (seed, losses)
        for label, value in losses.items():
            if value:
                damaged[label] += 1
        ids.append(losses)
    return checked(f"48 seeds;each run exactly 9 total damage;seed_hit_counts={dict(damaged)}",
                   set(damaged) == {"friendly_hero", "enemy_hero", "friendly_minion", "enemy_minion"})


def p118_replace_warlock_cards_and_power():
    observations = []
    for seed in range(16):
        g = game(CardClass.WARLOCK, seed=seed + 1180)
        p = g.player1
        p.discard_hand()
        hand_card = p.give("EX1_302")
        neutral = p.give(WISP)
        deck_card = p.give("EX1_304")
        deck_card.shuffle_into_deck()
        neutral_deck = p.give("CS2_182")
        neutral_deck_before = (neutral_deck.id, neutral_deck.card_class, neutral_deck.data.cost)
        neutral_deck.shuffle_into_deck()
        spell = play(p, "OG_118")
        assert spell.zone == Zone.GRAVEYARD and p.hero.power.id != "CS2_056", (seed, spell.zone, p.hero.power.id)
        hand_replacements = [c for c in p.hand if c is not neutral and c.id != "GAME_005"]
        assert len(hand_replacements) == 1, (seed, [c.id for c in p.hand])
        new_hand_card = hand_replacements[0]
        assert hand_card.zone == Zone.SETASIDE and new_hand_card.card_class != CardClass.WARLOCK, (seed, hand_card.id, hand_card.zone, new_hand_card.id, new_hand_card.card_class)
        assert new_hand_card.cost == max(0, new_hand_card.data.cost - 1), (seed, new_hand_card.id, new_hand_card.cost, new_hand_card.data.cost)
        assert neutral.id == WISP and neutral.zone == Zone.HAND, (seed, neutral.id, neutral.zone)
        deck_replacements = [c for c in p.deck if c is not neutral_deck]
        assert len(deck_replacements) == 1, (seed, [c.id for c in deck_replacements])
        new_deck_card = deck_replacements[0]
        assert deck_card.zone == Zone.SETASIDE and new_deck_card.card_class != CardClass.WARLOCK, (seed, deck_card.id, deck_card.zone, new_deck_card.id, new_deck_card.card_class)
        assert new_deck_card.cost == max(0, new_deck_card.data.cost - 1), (seed, new_deck_card.id, new_deck_card.cost, new_deck_card.data.cost)
        assert new_hand_card.card_class == new_deck_card.card_class == p.hero.power.card_class, (seed, new_hand_card.card_class, new_deck_card.card_class, p.hero.power.card_class)
        assert neutral_deck in p.deck and neutral_deck.zone == Zone.DECK and (neutral_deck.id, neutral_deck.card_class, neutral_deck.data.cost) == neutral_deck_before, (seed, neutral_deck.id, neutral_deck.zone, neutral_deck.card_class, neutral_deck.cost, neutral_deck_before)
        observations.append((p.hero.power.id, new_hand_card.id, new_deck_card.id,
                             (neutral_deck.id, neutral_deck.zone.name, CardClass(neutral_deck.card_class).name, neutral_deck.cost)))
    return checked(f"16 seeds;new hero powers/cards={observations}", len({row[0] for row in observations}) > 1)


def p120_deathrattle_hits_all_minions_for_eight():
    g = game(CardClass.MAGE)
    p, enemy = g.player1, g.player2
    friendly = summon(p, "OG_153")
    hostile = summon(enemy, "OG_153")
    for minion in (friendly, hostile):
        minion.max_health = 12
        minion.set_current_health(12)
    anomalus = play(p, "OG_120")
    anomalus.destroy()
    return checked(f"Anomalus={anomalus.zone.name};friendly_health={friendly.health}/{friendly.max_health};enemy_health={hostile.health}/{hostile.max_health};both_zones={friendly.zone.name},{hostile.zone.name};heroes={p.hero.health},{enemy.hero.health}",
                   anomalus.zone == Zone.GRAVEYARD and friendly.zone == hostile.zone == Zone.PLAY and friendly.health == hostile.health == 4 and p.hero.health == enemy.hero.health == 30)


def p121_next_spell_costs_health():
    g = game(CardClass.WARLOCK)
    p, enemy = g.player1, g.player2
    chogall = play(p, "OG_121")
    mana_after_chogall = p.mana
    p.hero.set_current_health(20)
    frostbolt = play(p, "CS2_024", enemy.hero)
    return checked(f"chogall={chogall.zone.name};mana_after_chogall={mana_after_chogall};mana_after_spell={p.mana};own_hero={p.hero.health};enemy_hero={enemy.hero.health};health_cost_flag={p.spells_cost_health};spell={frostbolt.zone.name}",
                   chogall in p.field and mana_after_chogall == p.mana and p.hero.health == 18 and enemy.hero.health == 27 and not p.spells_cost_health and frostbolt.zone == Zone.GRAVEYARD)


def p121_zero_cost_next_spell():
    g = game(CardClass.WARLOCK)
    p, enemy = g.player1, g.player2
    play(p, "OG_121")
    p.hero.set_current_health(20)
    mana_before = p.mana
    spell = play(p, MOONFIRE, enemy.hero)
    return checked(f"own_hero={p.hero.health};mana_before_after={mana_before},{p.mana};enemy_hero={enemy.hero.health};flag={p.spells_cost_health};spell={spell.zone.name}",
                   p.hero.health == 20 and p.mana == mana_before and enemy.hero.health == 29 and not p.spells_cost_health and spell.zone == Zone.GRAVEYARD)


def p121_unused_effect_expires_this_turn():
    g = game(CardClass.WARLOCK)
    p, enemy = g.player1, g.player2
    play(p, "OG_121")
    p.hero.set_current_health(20)
    mana_after_chogall = p.mana
    g.end_turn()
    g.end_turn()
    active_at_next_turn = p.spells_cost_health
    mana_before_spell = p.mana
    frostbolt = play(p, "CS2_024", enemy.hero)
    return checked(f"flag_next_turn={active_at_next_turn};mana_after_chogall={mana_after_chogall};mana_before_spell={mana_before_spell};mana_after_spell={p.mana};own_hero={p.hero.health};enemy_hero={enemy.hero.health};spell={frostbolt.zone.name}",
                   not active_at_next_turn and p.mana == mana_before_spell - 2 and p.hero.health == 20 and enemy.hero.health == 27 and frostbolt.zone == Zone.GRAVEYARD)


def p122_two_bananas_and_effects():
    g = game(CardClass.MAGE)
    p = g.player1
    mukla = play(p, "OG_122")
    bananas = [c for c in p.hand if c.id == "EX1_014t"]
    first, second = summon(p, WISP), summon(p, WISP)
    first_before, second_before = (first.atk, first.max_health), (second.atk, second.max_health)
    bananas[0].play(target=first)
    bananas[1].play(target=second)
    return checked(f"mukla={mukla.zone.name};banana_count={len(bananas)};first={(first.atk,first.max_health)};second={(second.atk,second.max_health)};bananas={[b.zone.name for b in bananas]}",
                   len(bananas) == 2 and (first.atk,first.max_health) == (first_before[0]+1,first_before[1]+1) and (second.atk,second.max_health) == (second_before[0]+1,second_before[1]+1) and all(b.zone == Zone.GRAVEYARD for b in bananas))


def p123_hand_morphs_across_own_turns():
    results = []
    for seed in range(16):
        g = game(CardClass.MAGE, seed=seed + 1230)
        p = g.player1
        zerus = p.give("OG_123")
        original_hand = set(p.hand)
        g.end_turn()
        g.end_turn()
        first_candidates = [c for c in p.hand if c not in original_hand]
        assert len(first_candidates) == 1, (seed, [c.id for c in p.hand], zerus.zone.name)
        first = first_candidates[0]
        first_id = first.id
        first_zone = first.zone
        first_type = first.type
        before_second = set(p.hand)
        g.end_turn()
        g.end_turn()
        second_candidates = [c for c in p.hand if c not in before_second]
        assert len(second_candidates) == 1, (seed, [c.id for c in p.hand], first.zone.name)
        second = second_candidates[0]
        second_id = second.id
        second_zone = second.zone
        second_type = second.type
        # See the second own-turn Morph on the same hand card after both idle turns.
        assert first_zone == second_zone == Zone.HAND and first_type == second_type == CardType.MINION and zerus.zone == first.zone == Zone.SETASIDE, (seed, zerus.zone, first_id, first_type, first.zone, second_id, second_type, second.zone)
        results.append((first_id, CardType(first_type).name, second_id))
    distinct = {card_id for first_id, _, second_id in results for card_id in (first_id, second_id)}
    return checked(f"16 games x two own turns={results};distinct_ids={len(distinct)}",
                   len(distinct) > 2 and all(zone_type == CardType.MINION.name for _, zone_type, _ in results))


def p131_below_cthun_attack_threshold():
    g = game(CardClass.MAGE)
    p = g.player1
    cthun = summon(p, "OG_280")
    cthun.atk = 9
    emperor = play(p, "OG_131")
    extra = [m for m in p.field if m.id == "OG_319"]
    return checked(f"cthun_atk={cthun.atk};emperor={(emperor.atk,emperor.health,emperor.taunt)};extra={[m.id for m in extra]};field={[m.id for m in p.field]}",
                   cthun.atk == 9 and emperor in p.field and emperor.taunt and not extra)


def p131_at_cthun_attack_threshold():
    g = game(CardClass.MAGE)
    p = g.player1
    cthun = summon(p, "OG_280")
    cthun.atk = 10
    emperor = play(p, "OG_131")
    extras = [m for m in p.field if m.id == "OG_319"]
    return checked(f"cthun_atk={cthun.atk};emperor={(emperor.atk,emperor.health,emperor.taunt)};extra={[(m.atk,m.health,m.taunt,m.zone.name) for m in extras]}",
                   cthun.atk == 10 and len(extras) == 1 and extras[0].atk == emperor.atk == 4 and extras[0].health == emperor.health == 6 and emperor.taunt and extras[0].taunt)


CASES = {
    "OG_006": [("battlecry_replaces_and_persists_hero_power", "Replace Paladin Hero Power with Tidal Hand; after Vilefin dies, use it twice to summon two 1/1 Murlocs.", p006_power_and_token,
                "打出邪鳍审判者后检查技能 ID、使用技能，再杀死本体後重复使用，核对增援和区域。", ("Battlecry", "Summon"))],
    "OG_023": [("friendly_totem_count_buff", "Two friendly Totems grant exactly +2/+2; an enemy Totem does not count.", p023_totem_count_buff,
                "同时放置两个己方图腾和一个敌方图腾，对己方目标实测攻击、最大生命和法术区域。", ("Spell resolution", "Targeting"))],
    "OG_026": [("unlock_all_overloaded_crystals", "Battlecry clears both owed and locked Overload.", p026_unlock_overload,
                "直接置入 owed=2、locked=1 的过载状态后打出，核对两个状态槽。", ("Battlecry",))],
    "OG_027": [("evolve_only_friendly_plus_one_cost", "Across 16 seeded games, each friendly minion becomes a different minion costing exactly one more; enemy minion stays unchanged.", p027_evolve_domain,
                "双方各有不同费用随从；多 seed 检查变形范围、费用、数量、区域和敌方状态。", ("Cost modification", "Random effects", "Spell resolution", "Transform"))],
    "OG_028": [("totem_summon_game_total_discount_and_taunt", "Enemy Totem does not discount; two friendly Totems discount even after they die; card keeps Taunt and can be played.", p028_totem_lifetime_discount,
                "先召唤敌方图腾，再让两个己方图腾召唤后死亡，核对费用仍保持折扣并实际打出嘲讽随从。", ("Cost modification", "Taunt"))],
    "OG_031": [("weapon_break_summons_4_2_elemental", "Breaking the weapon through two hero attacks triggers one 4/2 Elemental Deathrattle.", p031_hammer_deathrattle,
                "装备暮光神锤后实际攻击两次使耐久归零，核对武器离场和元素身材。", ("Deathrattle", "Summon", "Weapon"))],
    "OG_033": [("weapon_break_returns_to_hand", "Breaking Tentacles for Arms returns the same weapon card to hand and leaves no weapon equipped.", p033_tentacles_return,
                "实际挥击两次耗尽耐久，检查原武器对象区域、手牌和装备槽。", ("Deathrattle", "Weapon"))],
    "OG_034": [("cannot_attack_until_hero_attacks", "Swarmer cannot attack after summoning or at a new turn until its hero attacks; then it attacks successfully once.", p034_attack_gate,
                "打出后和跨回合后都尝试攻击；再先由英雄攻击，确认随从此时可攻击且攻击实际结算。", ("Continuous effect / Update",))],
    "OG_042": [("own_turn_end_pulls_minion_not_spell", "At its controller's turn end, one of two deck minions enters board while a spell and the other minion remain; opponent's turn end causes no second summon.", p042_deck_minion_only_own_endturn,
                "牌库中预置两个可区分随从和一张法术，结束己方回合后保留一个随从，再结束对方回合；额外核对下一回合正常抽牌导致的区域变化没有变成召唤。", ("Summon", "Trigger")),
                ("full_board_does_not_remove_deck_minion", "If all seven spaces are occupied, Y'Shaarj leaves the deck minion in deck.", p042_full_board_keeps_deck_minion,
                "用六个随从加亚煞极填满己方战场后触发回合末效果，检查未成功召唤的随从仍留在牌库。", ("Summon", "Trigger"))],
    "OG_044": [("fandral_combines_both_choose_one_effects", "With Fandral active, Feral Rage and Malfurion's Choose One Hero Power resolve both effects without opening Choice.", p044_fandral_combines,
                "先变身为玛法里奥再跨回合打出范达尔；实测野性之怒和玛法里奥英雄技能均合并两分支，核对攻击、护甲及 Choice 状态。", ("Aura", "Choose One", "Continuous effect / Update")),
                 ("choose_one_returns_after_fandral_leaves", "After Fandral leaves, Feral Rage and both Hero Power options resolve as individual choices.", p044_normal_choice_after_departure,
                "移除范达尔后选择野性之怒攻击分支；另以无范达尔的玛法里奥对局分别选择护甲与攻击技能分支。", ("Aura", "Choose One", "Continuous effect / Update"))],
    "OG_045": [("infest_applies_random_beast_deathrattle_to_all", "Both friendly minions receive a Deathrattle and each death adds one Beast card to hand; an enemy minion receives none.", p045_infest_deathrattles,
                "己方两个随从施法后分别死亡并生成野兽；敌方无亡语白板作负向对照，确认仍在场且没有获得亡语。", ("Random effects", "Spell resolution"))],
    "OG_047": [("feral_rage_attack_branch_expires", "Attack branch grants 4 Attack for this turn, enables a 4-damage hero attack, and expires next turn.", p047_attack_branch,
                "实际选择攻击子卡，挥击后跨回合检查攻击增益消失。", ("Choose One", "Spell resolution")),
                ("feral_rage_armor_branch_persists", "Armor branch grants 8 Armor without Attack; Armor remains after turn change.", p047_armor_branch,
                "实际选择护甲子卡，比较英雄攻击与护甲并跨回合复核。", ("Choose One", "Spell resolution"))],
    "OG_048": [("beast_target_gains_two_and_draws", "Target gains exactly +2/+2 and the known deck card is drawn.", p048_beast_buff_and_draw,
                "以已知野兽为目标，检查增益、牌库对象离区和实际抽到的牌。", ("Draw / Discard", "Spell resolution", "Targeting")),
                ("nonbeast_target_gains_two_without_draw", "Non-Beast target gains +2/+2 without drawing the known deck card.", p048_nonbeast_no_draw,
                "以白板非野兽为目标，验证条件未满足时只加属性、不抽牌。", ("Draw / Discard", "Spell resolution", "Targeting"))],
    "OG_051": [("forbidden_ancient_spends_remaining_mana", "At five available Mana, 1-cost body is played then remaining 4 Mana yields a 5/5 Ancient and zero Mana.", p051_spend_remaining_mana,
                "将法力上限设为5，实测打出本体后消费余下法力并检查当前/最大生命、攻击、区域。", ("Battlecry",))],
    "OG_061": [("on_the_hunt_minion_damage_and_mastiff", "Deals exactly 1 to an enemy minion and summons one 1/1 Mastiff.", p061_minion_target_and_dog,
                "以敌方可存活随从为目标，分别断言伤害、目标仍在场、獒犬属性及法术区域。", ("Spell resolution", "Summon", "Targeting")),
                ("on_the_hunt_hero_target", "Can target the enemy hero for 1 damage and still summons one Mastiff.", p061_hero_target,
                "以敌方英雄为目标实际结算，核对英雄生命和召唤物数量。", ("Spell resolution", "Summon", "Targeting"))],
    "OG_070": [("no_combo_printed_stats", "Without prior card this turn, Bladed Cultist remains 1/2.", p070_no_combo,
                "空回合直接打出，检查本体基础身材和 Combo 状态。", ("Combo",)),
                ("combo_after_coin_gains_two_stats", "After playing The Coin, Bladed Cultist is 2/3.", p070_combo,
                "先实际施放零费硬币，再打出教徒检查连击增益和区域。", ("Combo",))],
    "OG_072": [("discover_three_deathrattle_cards_and_choose", "Offers three Deathrattle cards; selecting one adds only that card to hand and closes Choice.", p072_discover_deathrattle_card,
                "逐项检查三个候选均有亡语，真实选择其中之一後核对手牌和 Choice 关闭。", ("Discover / Choice", "Random effects", "Spell resolution"))],
    "OG_073": [("draw_one_and_add_two_exact_copies", "Known deck minion is drawn and two copies enter hand, for three same-ID cards total.", p073_draw_and_copy,
                "只放入一张已知牌库牌，施放后核对原牌转入手牌、复制数量和法术区域。", ("Draw / Discard", "Spell resolution"))],
    "OG_080": [("both_random_toxin_grants", "Across 16 seeds, Battlecry and Deathrattle each grant a card from the five printed Toxin options.", p080_battlecry_and_deathrattle_toxins,
                "16 个固定种子逐次实打夏克里尔并令其死亡，核对两个随机毒素的候选域和结果多样性。", ("Battlecry", "Deathrattle", "Random effects"))],
    "OG_081": [("shatter_destroys_frozen_minion", "Frozen target is destroyed and the spell resolves.", p081_destroy_frozen_only,
                "实际冻结敌方随从后作为目标施放，检查目标墓地和法术区域。", ("Spell resolution", "Targeting")),
                ("shatter_rejects_unfrozen_minion_without_payment", "Unfrozen target is rejected before spending Mana or moving either card.", p081_reject_unfrozen_target,
                "尝试以未冻结敌方随从为目标，检查拒绝结果、法力和双方区域。", ("Spell resolution", "Targeting"))],
    "OG_082": [("spell_damage_plus_two_applies_to_real_spell", "Evolved Kobold adds two Spell Damage, so Moonfire deals 3 instead of 1.", p082_spell_damage_two,
                "先实际召唤异变的狗头人，再以已知基础伤害法术命中敌方英雄，断言总伤害。", ("Spell Damage",))],
    "OG_083": [("battlecry_hits_enemy_minions_only", "Enemy 1-health minion dies; enemy 5-health minion takes 1; friendly minion and enemy hero remain unchanged.", p083_enemy_minions_only,
                "双方各放置不同生命值随从，打出战吼后逐一断言区域、剩余生命及英雄状态。", ("Battlecry",))],
    "OG_085": [("two_spells_freeze_each_unfrozen_enemy_once", "After two spells, both enemy characters are Frozen, the friendly minion is not, and first frozen target is excluded from the next random trigger.", p085_freeze_eligible_enemy_only,
                "以敌方英雄和随从作为随机候选连续施放两张硬币，核对随机目标集合排除已冻结对象且不波及友方。", ("Random effects", "Trigger"))],
    "OG_086": [("forbidden_flame_spends_all_four_mana", "With 4 Mana, spell deals exactly 4 to a minion and leaves 0 Mana.", p086_spend_all_mana_damage,
                "设置4点可用法力，以敌方随从为目标，检查实际伤害和剩余法力。", ("Spell resolution", "Targeting")),
                ("forbidden_flame_zero_mana_resolves_zero_damage", "With 0 Mana, spell resolves for 0 damage and leaves target alive.", p086_zero_mana_target,
                "零法力时仍以合法随从目标打出，核对无伤害、目标区域和法术完成。", ("Spell resolution", "Targeting")),
                ("forbidden_flame_rejects_hero_target", "Hero target is rejected with card and Mana unchanged.", p086_reject_hero_target,
                "尝试以英雄为目标，检查目标限制在付费及移区前生效。", ("Spell resolution", "Targeting"))],
    "OG_087": [("servant_repeatedly_casts_only_tracking", "Random <=5-cost spell should vary; 12 independent seeds must not all resolve into Tracking's exact known-deck choice.", p087_only_tracking_across_seeds,
                "每局放入三张已知牌库牌，实打仆从並完成弹出的选择；重复固定种子观察实际咒语效果。结合源码 fireplace/cards/wog/mage.py:41。", ("Battlecry", "Random effects"))],
    "OG_090": [("cabalists_tome_adds_three_mage_spells", "Across 12 seeds, each Tome adds exactly three Mage spells and resolves to graveyard.", p090_three_mage_spells,
                "12 个固定种子逐局施放宝典，逐张校验手牌数量、牌类和法术类别。", ("Random effects", "Spell resolution"))],
    "OG_094": [("power_word_tentacles_gives_two_six", "Friendly target gains exactly +2 Attack and +6 maximum/current Health.", p094_buff_target,
                "以己方1/1白板为目标，核对攻击、当前生命、最大生命和法术区域。", ("Spell resolution", "Targeting"))],
    "OG_096": [("darkmender_below_ten_cthun_does_not_heal", "Set-aside friendly C'Thun at 9 Attack leaves damaged hero unchanged.", p096_below_cthun_threshold,
                "将游戏内置且位于SETASIDE区的克苏恩设为9攻，英雄降至10生命，实际打出战吼检查未满足条件分支。", ("Battlecry",)),
                ("darkmender_at_ten_cthun_heals_ten", "Set-aside friendly C'Thun at 10 Attack restores exactly 10 Health.", p096_at_cthun_threshold,
                "将SETASIDE区内置克苏恩设为10攻，英雄降至10生命，打出后断言精确恢复值。", ("Battlecry",))],
    "OG_100": [("horror_destroys_both_sides_at_two_or_less", "All friendly and enemy minions with 2 or less Attack are destroyed; 3-Attack minions survive.", p100_attack_threshold_sweep,
                "雙方各放置1、2和3攻随从，施放后逐个核对阈值边界与区域。", ("Spell resolution",))],
    "OG_101": [("forbidden_shaping_spends_five_and_summons_cost_five", "Across 16 seeds, all Mana is spent and exactly one in-play minion costing exactly five is summoned.", p101_random_minion_matches_spent_mana,
                "16 个固定种子各设5点法力施放禁忌畸变，检查召唤数量、对象区域、卡牌费用和随机结果变化。", ("Random effects", "Spell resolution", "Summon"))],
    "OG_102": [("darkspeaker_swaps_stats_with_friendly_minion", "Darkspeaker and a legal friendly minion exchange Attack and maximum/current Health; enemy minions are not legal targets.", p102_swap_friendly_stats,
                "核对卡牌 targets 集合后，以己方4/5随从为目标，实测双方交换后的属性。", ("Battlecry", "Targeting")),
                ("darkspeaker_is_playable_without_friendly_target", "With no friendly minion and only an enemy minion, Darkspeaker can be played as a 3/6 without changing the enemy.", p102_play_without_available_friendly_target,
                "己方无随从、敌方有随从时先断言无合法目标，再不传 target 打出，核对3/6本体、敌方状态和区域。", ("Battlecry", "Targeting"))],
    "OG_104": [("embrace_shadow_turns_healing_into_damage_then_expires", "This turn, Priest self-heal deals damage; after the turn cycle, the same Hero Power heals normally.", p104_healing_reverses_then_expires,
                "打出暗影之握后对己方英雄实际使用治疗技能，再跨回合重复治疗，核对生命变化及效果标志。", ("Spell resolution",))],
    "OG_109": [("librarian_discards_random_hand_card_and_deathrattle_draws", "Battlecry removes exactly one known random hand card; on death, known deck minion is drawn while the other card remains.", p109_discard_and_death_draw,
                "清空初始手牌后放入两张候选和一张已知牌库牌，核对实际弃牌区域、保留牌与死亡抽牌。", ("Battlecry", "Deathrattle", "Draw / Discard", "Random effects"))],
    "OG_113": [("councilman_gains_attack_after_friendly_summon_only", "Councilman stays 3 Attack on play, gains 1 after friendly summon, and ignores an opponent summon.", p113_trigger_friendly_summons,
                "分辨本体入场、其后己方召唤和敌方召唤三个时点，实际检查攻击变化。", ("Summon", "Trigger"))],
    "OG_114": [("forbidden_ritual_spends_all_four_for_four_tentacles", "Four available Mana is spent and four 1/1 Tentacles are summoned.", p114_spend_mana_and_summon_tokens,
                "用4点法力施放零费仪式，逐只检查触须属性、数量、场上区域和当前法力。", ("Spell resolution", "Summon")),
                ("forbidden_ritual_respects_seven_minion_limit", "With six minions in play, Ritual can summon only one additional Tentacle while spending all Mana.", p114_board_capacity,
                "用六只己方随从占位后施放4费触须，检查法力消耗与场地容量限制。", ("Spell resolution", "Summon"))],
    "OG_116": [("spreading_madness_deals_nine_across_all_characters", "Across 48 seeds, each cast deals exactly nine total damage and every friendly/enemy hero/minion category is hit in some run.", p116_random_damage_all_characters,
                "双方英雄及大生命随从构成全部角色池，48 个固定种子逐局施放并累加每个实体受到的伤害。", ("Random effects", "Spell resolution"))],
    "OG_118": [("renounce_replaces_hero_power_and_warlock_cards_only", "Across 16 seeds, Hero Power and Warlock cards in hand/deck become cards of one other class at -1 cost; neutral card remains unchanged.", p118_replace_warlock_cards_and_power,
                "每局在手牌和牌库各放术士牌，并留中立白板作对照；记录职业、费用、英雄技能、牌库/手牌区域。", ("Cost modification", "Random effects", "Spell resolution", "Summon"))],
    "OG_120": [("anomalus_deathrattle_hits_every_minion_for_eight", "On death, Anomalus deals exactly 8 to all minions on both sides and does not damage heroes.", p120_deathrattle_hits_all_minions_for_eight,
                "双方各放一个12生命随从，实际杀死阿诺玛鲁后核对各自剩4生命及英雄不受伤。", ("Deathrattle",))],
    "OG_121": [("chogall_next_spell_costs_health_not_mana", "Next 2-cost spell costs exactly 2 Health and no Mana, deals its printed damage, and consumes the effect.", p121_next_spell_costs_health,
                "打出古加尔后把己方英雄设为20生命，施放寒冰箭，核对支付生命而非法力、目标伤害和标志清除。", ("Battlecry",)),
                ("chogall_zero_cost_next_spell_consumes_effect_without_health", "Next zero-cost spell consumes the effect without Health or Mana payment.", p121_zero_cost_next_spell,
                "打出古加尔后施放零费月火术，验证零费分支仍计作下一张法术并不扣生命。", ("Battlecry",)),
                ("chogall_unused_effect_expires_at_end_of_turn", "If no spell is cast this turn, next turn's spell uses Mana, not Health.", p121_unused_effect_expires_this_turn,
                "打出古加尔后空过至下个己方回合，再施放2费寒冰箭，比较标志、英雄生命和法力。", ("Battlecry",))],
    "OG_122": [("mukla_adds_and_uses_two_bananas", "Battlecry adds exactly two Banana spells; each buffs a different target by +1/+1.", p122_two_bananas_and_effects,
                "核对手牌中香蕉数量，再逐张实际施放到两个白板随从，检查属性和区域。", ("Battlecry",))],
    "OG_123": [("zerus_morphs_in_hand_each_own_turn", "Across 16 games and two own turns, the in-hand card remains a Minion in hand while repeatedly morphing among random Minions.", p123_hand_morphs_across_own_turns,
                "每局持有百变泽鲁斯跨两个己方回合，记录同一手牌对象的卡号、类型和区域变化。", ("Random effects", "Transform", "Trigger"))],
    "OG_131": [("twin_emperor_no_extra_copy_below_ten_cthun", "C'Thun at 9 Attack produces no second Emperor; printed Taunt body is present.", p131_below_cthun_attack_threshold,
                "場上克苏恩攻击力设为9，实际打出维克洛尔并核对无额外皇帝及本体嘲讽。", ("Battlecry", "Summon", "Taunt")),
                ("twin_emperor_summons_second_taunt_at_ten_cthun", "C'Thun at exactly 10 Attack summons one additional 4/6 Taunt Emperor.", p131_at_cthun_attack_threshold,
                "場上克苏恩攻击力设为10，实际打出维克洛尔并逐只核对两个皇帝的身材、嘲讽及区域。", ("Battlecry", "Summon", "Taunt"))],
}


def main():
    for cid in CARDS:
        if cid not in CASES:
            continue
        prepare_card(cid)
        audit_card(cid, CASES[cid])
    print("checkpoint", dict(Counter(row["status"] for row in VERDICT_ROWS)),
          "cases", len(PROBE_ROWS), "cards", len(VERDICT_ROWS))


if __name__ == "__main__":
    main()
