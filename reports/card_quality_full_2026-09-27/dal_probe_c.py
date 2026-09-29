"""Targeted live game checks for frozen DALARAN YELLOW indices 90:134."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, MOONFIRE, THE_COIN, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "dal_probe_c.csv"
VERDICT_FILE = HERE / "dal_verdict_c.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


ROSTER_FULL = sorted((r for r in read(HERE / "remaining_yellow_baseline.csv")
                      if r["set"].endswith("(DALARAN)") and r["scope"] == "ordinary_collectible"),
                     key=lambda r: r["card_id"])
ROSTER = ROSTER_FULL[90:134]
assert len(ROSTER) == 44 and ROSTER[0]["card_id"] == "DAL_592" and ROSTER[-1]["card_id"] == "DAL_800"
assert len({r["card_id"] for r in ROSTER}) == 44 and [r["card_id"] for r in ROSTER] == sorted(r["card_id"] for r in ROSTER)
ROSTER_BY_ID = {r["card_id"]: r for r in ROSTER}
MASTER = {r["card_id"]: r for r in read(HERE / "card_master.csv")}
PROBES = read(PROBE_FILE)
VERDICTS = read(VERDICT_FILE)


def game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=181):
    random.seed(seed)
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    p = (next(player for player in g.players if player.hero.card_class == class1)
         if class1 != class2 else g.player1)
    e = next(player for player in g.players if player is not p)
    if g.current_player is not p:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
        player.temp_mana = 0
        player.overload_locked = 0
        player.discard_hand()
    assert p.hero.card_class == class1 and e.hero.card_class == class2
    return g, p, e


def play(player, cid, target=None, choose=None, index=None):
    card = player.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if choose is not None:
        kw["choose"] = choose
    if index is not None:
        kw["index"] = index
    card.play(**kw)
    return card


def summon(player, cid):
    card = player.summon(cid)
    assert card is not None, f"could not summon {cid}"
    return card


def put_deck(player, cid, count=1):
    cards = []
    for _ in range(count):
        card = player.give(cid)
        card.shuffle_into_deck()
        cards.append(card)
    return cards


def end_round(g):
    g.end_turn()
    g.end_turn()


def check(ok, observed):
    assert ok, observed
    return observed


def meta(cid):
    m = MASTER[cid]
    b = ROSTER_BY_ID[cid]
    return (f"EN={m['card_text_en']}; ZH={m['card_text_zh']}; "
            f"source={m['python_source'] or m.get('xml_source', '')}; "
            f"existing_tests={m['test_refs_candidate'] or 'none'}; "
            f"prior={b['status']}:{b['reason']}; prior_evidence={b['evidence']}")


def audit(cid, tests):
    global PROBES, VERDICTS
    assert cid in ROSTER_BY_ID
    PROBES = [r for r in PROBES if r["card_id"] != cid]
    VERDICTS = [r for r in VERDICTS if r["card_id"] != cid]
    write(PROBE_FILE, PF, PROBES)
    write(VERDICT_FILE, VF, VERDICTS)
    for case_id, expected, func, notes in tests:
        try:
            observed = func()
            outcome = "pass"
        except AssertionError as exc:
            observed = str(exc) or f"AssertionError at {traceback.extract_tb(exc.__traceback__)[-1].lineno}"
            outcome = "confirmed_error"
        except Exception as exc:
            observed = f"{type(exc).__name__}: {exc}"
            outcome = "inconclusive"
        PROBES.append(dict(card_id=cid, case_id=case_id, expected=expected,
                           observed=observed, outcome=outcome, notes=f"{notes}; {meta(cid)}"))
        write(PROBE_FILE, PF, PROBES)
        print(cid, case_id, outcome, observed, flush=True)
    own = [r for r in PROBES if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own)
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in errors)
    elif unresolved:
        status = "YELLOW"
        reason = "具体未决探测：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in unresolved)
    else:
        status = "GREEN"
        reason = "逐卡关键行为断言通过：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in own)
    VERDICTS.append(dict(card_id=cid, status=status, mechanic_scope=ROSTER_BY_ID[cid]["mechanic"],
                         reason=reason, probe_file=PROBE_FILE.name, notes=meta(cid)))
    write(VERDICT_FILE, VF, VERDICTS)
    print(cid, status, len(own), "cases", flush=True)
    return status


def batterhead_rush_kills_and_may_attack_again():
    cid = "DAL_592"

    def kills_two_minions():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=5921)
        first, second = summon(e, WISP), summon(e, WISP)
        batter = play(p, cid)
        first_error = second_error = None
        try:
            batter.attack(first)
        except Exception as exc:
            first_error = type(exc).__name__
        try:
            batter.attack(second)
        except Exception as exc:
            second_error = type(exc).__name__
        observed = (f"first_error={first_error};second_error={second_error};"
                    f"first={first.zone.name};second={second.zone.name};"
                    f"batter={batter.zone.name}/{batter.atk}/{batter.health};"
                    f"attacks_left={getattr(batter, 'attacks_left', None)}")
        return check(first_error is None and second_error is None
                     and first.zone == second.zone == Zone.GRAVEYARD
                     and batter.zone == Zone.PLAY, observed)

    def no_kill_does_not_grant_another_attack():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=5922)
        durable, second = summon(e, "CS2_182"), summon(e, WISP)
        batter = play(p, cid)
        first_error = second_error = None
        try:
            batter.attack(durable)
        except Exception as exc:
            first_error = type(exc).__name__
        try:
            batter.attack(second)
        except InvalidAction as exc:
            second_error = type(exc).__name__
        observed = (f"first_error={first_error};second_error={second_error};"
                    f"durable={durable.zone.name}/damage:{durable.damage};second={second.zone.name};"
                    f"batter={batter.zone.name}/{batter.health}")
        return check(first_error is None and second_error == "InvalidAction"
                     and durable.zone == second.zone == Zone.PLAY
                     and durable.damage == batter.atk, observed)

    audit(cid, [
        ("rush_kill_grants_second_attack", "Batterhead's Rush allows it to kill two 1/1 minions during one turn.", kills_two_minions, "打出突袭Batterhead后连续攻击两只敌方Wisp，只有首击击杀后才能进行第二次攻击。"),
        ("surviving_target_does_not_grant_second_attack", "After Batterhead fails to kill the first target, a second attack is rejected.", no_kill_does_not_grant_another_attack, "首击攻击5血Yeti后其仍存活，再尝试攻击Wisp，验证未击杀不奖励额外攻击。"),
    ])


def plot_twist_shuffles_hand_then_draws_same_number():
    cid = "DAL_602"

    def shuffle_and_redraw_other_hand_cards():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=6021)
        wisp, yeti = p.give(WISP), p.give("CS2_182")
        spell = play(p, cid)
        observed = (f"spell={spell.zone.name};hand={[(c.id,c.zone.name) for c in p.hand]};"
                    f"deck={[c.id for c in p.deck]};wisp={wisp.zone.name};yeti={yeti.zone.name};mana={p.mana}")
        return check(spell.zone == Zone.GRAVEYARD and len(p.hand) == 2
                     and sorted(c.id for c in p.hand) == sorted([WISP, "CS2_182"])
                     and wisp.zone == yeti.zone == Zone.HAND and not p.deck, observed)

    audit(cid, [
        ("shuffle_two_remaining_cards_and_draw_two", "Plot Twist shuffles the two other cards in hand into the deck and draws two cards back.", shuffle_and_redraw_other_hand_cards, "手牌中放Wisp、Yeti后施放Plot Twist，逐项核对施法牌不计入洗牌/抽牌数量且两张原牌回到手牌。"),
    ])


plot_twist_shuffles_hand_then_draws_same_number.card_id = "DAL_602"


def mana_cyclone_adds_one_mage_spell_per_spell_cast():
    cid = "DAL_603"

    def scenario(spell_count, seed):
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=seed)
        spells = []
        for _ in range(spell_count):
            spell = play(p, "CS2_024", target=e.hero)
            spells.append(spell)
        cyclone = play(p, cid)
        added = list(p.hand)
        valid = all(card.type == CardType.SPELL and card.card_class == CardClass.MAGE for card in added)
        observed = (f"cast_count={spell_count};played={[c.zone.name for c in spells]};"
                    f"added={[(c.id,str(c.type),str(c.card_class),c.zone.name) for c in added]};"
                    f"cyclone={cyclone.zone.name};enemy_hero={e.hero.health}")
        return check(cyclone.zone == Zone.PLAY and len(added) == spell_count and valid
                     and all(c.zone == Zone.GRAVEYARD for c in spells), observed)

    audit(cid, [
        ("two_prior_spells_add_two_mage_spells", "Two spells played before Mana Cyclone result in exactly two Mage spells added to hand.", lambda: scenario(2, 6031), "先實際施放兩次寒冰箭，再打出Mana Cyclone，檢查新增數量、類型與職業。"),
        ("no_prior_spells_add_nothing", "With no spell played earlier this turn, Mana Cyclone adds no card.", lambda: scenario(0, 6032), "本回合未施法直接打出，驗證手牌無額外生成法術。"),
    ])


mana_cyclone_adds_one_mage_spell_per_spell_cast.card_id = "DAL_603"


def ursatron_deathrattle_draws_mech_and_leaves_other_cards():
    cid = "DAL_604"

    def deathrattle_searches_deck_for_mech():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=6041)
        mech = put_deck(p, "EX1_556")[0]
        non_mech = put_deck(p, "CS2_182")[0]
        ursatron = summon(p, cid)
        g.end_turn()
        removal = e.give("CS2_029")
        removal.play(target=ursatron)
        observed = (f"ursatron={ursatron.zone.name};removal={removal.zone.name};"
                    f"mech={mech.zone.name};nonmech={non_mech.zone.name};"
                    f"hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]}")
        return check(ursatron.zone == Zone.GRAVEYARD and removal.zone == Zone.GRAVEYARD
                     and mech.zone == Zone.HAND and mech in p.hand
                     and non_mech.zone == Zone.DECK and non_mech in p.deck, observed)

    audit(cid, [
        ("deathrattle_draws_mech_only", "Ursatron's death draws the deck Mech and leaves a non-Mech in the deck.", deathrattle_searches_deck_for_mech, "將Harvest Golem與Yeti置入牌庫，讓對手火球術實際擊殺Ursatron，檢查機械被抽而非機械保留。"),
    ])


ursatron_deathrattle_draws_mech_and_leaves_other_cards.card_id = "DAL_604"


def impferno_buffs_demons_and_damages_enemy_board():
    cid = "DAL_605"

    def resolves_without_a_target():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=6051)
        demon = summon(p, "EX1_306")
        friendly_non_demon = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        before = (demon.atk, friendly_non_demon.atk, enemy.damage)
        spell = p.give(cid)
        err = None
        try:
            spell.play()
        except InvalidAction as exc:
            err = type(exc).__name__
        observed = (f"error={err};spell={spell.zone.name};demon={demon.zone.name}/{demon.atk}/{demon.health};"
                    f"friendly_non_demon={friendly_non_demon.atk}/{friendly_non_demon.health};"
                    f"enemy={enemy.zone.name}/{enemy.health}/damage:{enemy.damage};mana={p.mana}")
        return check(err is None and spell.zone == Zone.GRAVEYARD and demon.atk == before[0] + 1
                     and friendly_non_demon.atk == before[1] and enemy.damage == before[2] + 1
                     and enemy.zone == Zone.PLAY, observed)

    audit(cid, [
        ("no_target_cast_buffs_demons_and_hits_enemy_minions", "Impferno resolves without selecting a target, gives friendly Demons +1 Attack, and deals 1 to each enemy minion.", resolves_without_a_target, "己方場上準備惡魔與非惡魔、敵方準備Yeti，無目標施放後檢查惡魔+1攻、非惡魔不變、敵方受1傷。"),
    ])


impferno_buffs_demons_and_damages_enemy_board.card_id = "DAL_605"


def evil_genius_destroys_friendly_target_and_adds_two_lackeys():
    cid = "DAL_606"

    def battlecry_destroys_and_generates_two():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=6061)
        victim = summon(p, WISP)
        genius = p.give(cid)
        genius.play(target=victim)
        lackeys = [card for card in p.hand if card.id in {
            "DAL_613", "DAL_614", "DAL_615", "DAL_739", "DAL_741", "ULD_616", "DRG_052"
        }]
        observed = (f"victim={victim.zone.name};genius={genius.zone.name}/{genius.atk}/{genius.health};"
                    f"lackeys={[(c.id,c.zone.name,c.cost) for c in lackeys]};hand={[c.id for c in p.hand]}")
        return check(victim.zone == Zone.GRAVEYARD and genius.zone == Zone.PLAY
                     and len(lackeys) == 2 and all(c.zone == Zone.HAND for c in lackeys), observed)

    audit(cid, [
        ("friendly_death_adds_two_playable_lackeys", "Evil Genius destroys the selected friendly minion and adds two Lackeys to hand.", battlecry_destroys_and_generates_two, "指定己方Wisp作為戰吼犧牲目標，檢查Wisp死亡且手牌新增兩張已知Lackey ID。"),
    ])


evil_genius_destroys_friendly_target_and_adds_two_lackeys.card_id = "DAL_606"


def fel_lord_betrug_summons_rush_copy_that_dies_at_turn_end():
    cid = "DAL_607"

    def draw_minion_and_expire_copy():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=6071)
        deck_minion = put_deck(p, "CS2_182")[0]
        betrug = play(p, cid)
        drawn = p.draw()
        copies = [m for m in p.field if m.id == "CS2_182" and m is not deck_minion]
        copy = copies[0] if copies else None
        rush = copy.tags[GameTag.RUSH] if copy else False
        before_end = (drawn.id, drawn.zone.name, copy.zone.name if copy else None,
                      copy.atk if copy else None, copy.health if copy else None, rush)
        g.end_turn()
        observed = (f"deck_card={deck_minion.zone.name};drawn={drawn.zone.name};betrug={betrug.zone.name};"
                    f"copy_before_end={before_end};copy_after_end={copy.zone.name if copy else None};"
                    f"field={[(m.id,m.zone.name) for m in p.field]}")
        return check(drawn is deck_minion and drawn.zone == Zone.HAND and copy is not None
                     and copy.zone == Zone.GRAVEYARD and rush and betrug.zone == Zone.PLAY, observed)

    audit(cid, [
        ("drawn_minion_creates_ephemeral_rush_copy", "Drawing a minion while Betrug is active creates a Rush copy that is destroyed at end of turn; original stays in hand.", draw_minion_and_expire_copy, "先打出Betrug，再從只有Yeti的牌庫實際抽牌，核對原牌入手、突襲複製入場並於回合結束死亡。"),
    ])


fel_lord_betrug_summons_rush_copy_that_dies_at_turn_end.card_id = "DAL_607"


def magic_trick_discovers_spell_costing_three_or_less():
    cid = "DAL_608"

    def discover_low_cost_spell():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=6081)
        trick = p.give(cid)
        trick.play()
        choice = p.choice
        options = list(choice.cards) if choice else []
        valid = bool(options) and len(options) == 3 and all(
            card.type == CardType.SPELL and card.cost <= 3 for card in options
        )
        chosen = options[0] if options else None
        if chosen:
            choice.choose(chosen)
        observed = (f"options={[(c.id,c.cost,str(c.type)) for c in options]};valid={valid};"
                    f"chosen={chosen.id if chosen else None};choice_after={bool(p.choice)};"
                    f"hand={[(c.id,c.cost,c.zone.name) for c in p.hand]};spell={trick.zone.name}")
        return check(valid and chosen is not None and chosen in p.hand
                     and chosen.zone == Zone.HAND and p.choice is None
                     and trick.zone == Zone.GRAVEYARD, observed)

    audit(cid, [
        ("discover_three_spells_at_or_below_three_cost", "Magic Trick offers three spells each costing 3 or less and the selected spell enters hand.", discover_low_cost_spell, "實際施放Magic Trick，檢查三張發現選項都是法術且費用不超過3，再選一張入手。"),
    ])


magic_trick_discovers_spell_costing_three_or_less.card_id = "DAL_608"


def kalecgos_discovers_and_makes_only_first_spell_free():
    cid = "DAL_609"

    def first_spell_free_only():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=6091)
        spell_one, spell_two = p.give("CS2_029"), p.give("CS2_029")
        coins = [p.give(THE_COIN) for _ in range(4)]
        kalecgos = play(p, cid)
        choice = p.choice
        options = list(choice.cards) if choice else []
        discovered = options[0] if options else None
        if discovered:
            choice.choose(discovered)
        initial_costs = (spell_one.cost, spell_two.cost)
        for coin in coins:
            coin.play()
        costs_after_first_spell = (spell_one.cost, spell_two.cost)
        spell_one.play(target=e.hero)
        observed = (f"kalecgos={kalecgos.zone.name};discover_options={[(c.id,str(c.type)) for c in options]};"
                    f"discovered={discovered.id if discovered else None};initial_costs={initial_costs};"
                    f"after_coins={costs_after_first_spell};spell_one={spell_one.zone.name};"
                    f"spell_two={spell_two.zone.name}/{spell_two.cost};enemy_hero={e.hero.health};"
                    f"coins={[c.zone.name for c in coins]};mana={p.mana}")
        return check(kalecgos.zone == Zone.PLAY and len(options) == 3
                     and all(c.type == CardType.SPELL for c in options)
                     and discovered is not None and discovered.zone == Zone.HAND
                     and initial_costs == (0, 0) and costs_after_first_spell == (4, 4)
                     and spell_one.zone == Zone.GRAVEYARD and spell_two.zone == Zone.HAND
                     and spell_two.cost == 4 and e.hero.health == 24
                     and all(c.zone == Zone.GRAVEYARD for c in coins), observed)

    audit(cid, [
        ("battlecry_discovers_and_first_spell_is_free_once", "Kalecgos discovers a spell, makes the first spell cost 0, then restores the other spell's normal cost after the first spell is cast.", first_spell_free_only, "打出Kalecgos選擇一張發現法術；兩張火球暫為0費，先施放幸運幣觸發首法術優惠，四枚幸運幣提供後續4法力，再核對火球恢復4費並只免費施放一張。"),
    ])


kalecgos_discovers_and_makes_only_first_spell_free.card_id = "DAL_609"


def soul_of_murloc_grants_deathrattle_to_friendly_minions():
    cid = "DAL_710"

    def granted_deathrattle_summons_murloc():
        g, p, e = game(CardClass.SHAMAN, CardClass.MAGE, seed=7101)
        minion = summon(p, WISP)
        spell = play(p, cid)
        has_dr = minion.has_deathrattle
        g.end_turn()
        removal = e.give("CS2_029")
        removal.play(target=minion)
        tokens = [m for m in p.field if m.id == "EX1_506a"]
        observed = (f"spell={spell.zone.name};has_dr={has_dr};minion={minion.zone.name};"
                    f"removal={removal.zone.name};tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]};"
                    f"field={[(m.id,m.zone.name) for m in p.field]}")
        return check(has_dr and minion.zone == Zone.GRAVEYARD and removal.zone == Zone.GRAVEYARD
                     and len(tokens) == 1 and (tokens[0].atk,tokens[0].health,tokens[0].zone) == (1,1,Zone.PLAY), observed)

    audit(cid, [
        ("friendly_minion_deathrattle_summons_one_one_murloc", "Soul of the Murloc grants a friendly minion a Deathrattle and its death summons a 1/1 Murloc.", granted_deathrattle_summons_murloc, "己方Wisp施放Soul of the Murloc获得亡语，再被对手火球术击杀后核对指定Murloc token。"),
    ])


soul_of_murloc_grants_deathrattle_to_friendly_minions.card_id = "DAL_710"


def underbelly_fence_gets_stats_and_rush_with_foreign_class_card():
    cid = "DAL_714"

    def scenario(holding_foreign, seed):
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=seed)
        foreign = p.give("CS2_029") if holding_foreign else None
        class_pair = (p.hero.card_class, foreign.card_class if foreign else None)
        fence = play(p, cid)
        observed = (f"foreign={foreign.id if foreign else None}/{foreign.zone.name if foreign else None};"
                    f"classes={class_pair};"
                    f"fence={fence.zone.name}/{fence.atk}/{fence.health}/rush:{fence.rush};"
                    f"powered={fence.powered_up}")
        return check(class_pair[0] == CardClass.ROGUE
                     and (not holding_foreign or class_pair[1] == CardClass.MAGE)
                     and fence.zone == Zone.PLAY and fence.powered_up == holding_foreign
                     and (fence.atk,fence.health) == ((3,4) if holding_foreign else (2,3))
                     and fence.rush == holding_foreign, observed)

    audit(cid, [
        ("foreign_class_card_grants_plus_one_plus_one_and_rush", "Holding a non-Rogue card gives Underbelly Fence +1/+1 and Rush.", lambda: scenario(True, 7141), "盜賊手牌持有法師火球，打出Fence後檢查3/4和突襲。"),
        ("no_foreign_class_card_leaves_base_body", "Without another-class card in hand, Underbelly Fence stays 2/3 without Rush.", lambda: scenario(False, 7142), "手牌無外職牌打出Fence，檢查本體2/3且無突襲。"),
    ])


underbelly_fence_gets_stats_and_rush_with_foreign_class_card.card_id = "DAL_714"


def vendetta_costs_zero_only_with_foreign_class_card():
    cid = "DAL_716"

    def scenario(holding_foreign, seed):
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=seed)
        foreign = p.give("CS2_029") if holding_foreign else None
        class_pair = (p.hero.card_class, foreign.card_class if foreign else None)
        target = summon(e, "CS2_182")
        spell = p.give(cid)
        cost = spell.cost
        spell.play(target=target)
        observed = (f"foreign={foreign.id if foreign else None};cost={cost};spell={spell.zone.name};"
                    f"classes={class_pair};"
                    f"target={target.zone.name}/damage:{target.damage if target.zone == Zone.PLAY else '-'};mana={p.mana}")
        return check(class_pair[0] == CardClass.ROGUE
                     and (not holding_foreign or class_pair[1] == CardClass.MAGE)
                     and cost == (0 if holding_foreign else 4) and spell.zone == Zone.GRAVEYARD
                     and target.zone == Zone.PLAY and target.damage == 4, observed)

    audit(cid, [
        ("foreign_class_card_sets_vendetta_cost_to_zero", "Vendetta costs 0 while a non-Rogue card is held and deals 4 damage.", lambda: scenario(True, 7161), "手牌持有火球時讀取Vendetta動態0費並對Yeti實際造成4傷。"),
        ("no_foreign_class_card_keeps_base_cost_four", "With no other-class card, Vendetta costs its printed 4 and still deals 4 damage.", lambda: scenario(False, 7162), "手牌無外職牌時核對法術仍4費並造成4傷。"),
    ])


vendetta_costs_zero_only_with_foreign_class_card.card_id = "DAL_716"


def tak_nozwhisker_copies_friendly_shuffle_to_hand():
    cid = "DAL_719"

    def friendly_shuffle_gives_copy():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=7191)
        tak = summon(p, cid)
        original = p.give(WISP)
        original.shuffle_into_deck()
        copies = [card for card in p.hand if card.id == WISP]
        observed = (f"tak={tak.zone.name};original={original.zone.name};deck={[c.id for c in p.deck]};"
                    f"hand={[(c.id,c.zone.name) for c in p.hand]};copy_count={len(copies)}")
        return check(tak.zone == Zone.PLAY and original.zone == Zone.DECK
                     and original in p.deck and len(copies) == 1
                     and copies[0] is not original and copies[0].zone == Zone.HAND, observed)

    audit(cid, [
        ("shuffling_friendly_card_adds_exact_copy_to_hand", "When a friendly card is shuffled into its controller's deck, Tak adds an exact copy to hand.", friendly_shuffle_gives_copy, "Tak在場時將己方Wisp實際洗入牌庫，檢查原牌留在牌庫且一張複製進手牌。"),
    ])


tak_nozwhisker_copies_friendly_shuffle_to_hand.card_id = "DAL_719"


def waggle_pick_deathrattle_returns_minion_discounted_by_two():
    cid = "DAL_720"

    def weapon_break_returns_only_friendly_minion_discounted():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=7201)
        minion = summon(p, "CS2_182")
        pick = play(p, cid)
        initial = minion.cost
        p.hero.attack(e.hero)
        first_durability = pick.durability
        g.end_turn()
        g.end_turn()
        p.hero.attack(e.hero)
        observed = (f"initial_cost={initial};first_durability={first_durability};"
                    f"weapon={pick.zone.name}/{pick.durability};minion={minion.zone.name}/{minion.cost};"
                    f"hand={[(c.id,c.cost,c.zone.name) for c in p.hand]};enemy_hero={e.hero.health}")
        return check(first_durability == 1 and pick.zone == Zone.GRAVEYARD
                     and minion.zone == Zone.HAND and minion.cost == initial - 2
                     and minion in p.hand, observed)

    audit(cid, [
        ("last_weapon_attack_bounces_minion_and_reduces_cost_two", "Waggle Pick's last durability triggers its Deathrattle, returning the sole friendly minion at 2 less Cost.", weapon_break_returns_only_friendly_minion_discounted, "己方只控制一只Yeti时装备Waggle Pick，先攻一次、跨过对手回合后用最后耐久击破武器並核对Yeti回手降2费。"),
    ])


waggle_pick_deathrattle_returns_minion_discounted_by_two.card_id = "DAL_720"


def catrina_muerte_summons_friendly_minion_that_died_this_game():
    cid = "DAL_721"

    def death_archive_minion_returns_at_own_turn_end():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=7211)
        original = summon(p, WISP)
        g.end_turn()
        removal = e.give("CS2_029")
        removal.play(target=original)
        g.end_turn()
        catrina = play(p, cid)
        g.end_turn()
        copies = [m for m in p.field if m.id == WISP]
        observed = (f"original={original.zone.name};removal={removal.zone.name};"
                    f"catrina={catrina.zone.name}/{catrina.atk}/{catrina.health};"
                    f"copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};current_e={g.current_player is e}")
        return check(original.zone == Zone.GRAVEYARD and catrina.zone == Zone.PLAY
                     and len(copies) == 1 and copies[0].zone == Zone.PLAY and g.current_player is e, observed)

    audit(cid, [
        ("own_turn_end_summons_copy_of_friendly_dead_minion", "At its controller's turn end, Catrina summons a copy of the friendly Wisp that died earlier this game.", death_archive_minion_returns_at_own_turn_end, "實際由對手火球術擊殺己方Wisp，下一個己方回合打出Catrina並結束回合檢查亡者複製是否重返場上。"),
    ])


catrina_muerte_summons_friendly_minion_that_died_this_game.card_id = "DAL_721"


def forbidden_words_spends_all_mana_and_respects_attack_threshold():
    cid = "DAL_723"

    def destroys_with_available_mana():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=7231)
        target = summon(e, "CS2_182")
        before_mana = p.mana
        spell = p.give(cid)
        spell.play(target=target)
        observed = f"before_mana={before_mana};after_mana={p.mana};target={target.zone.name};spell={spell.zone.name}"
        return check(target.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD
                     and before_mana == 10 and p.mana == 0, observed)

    def rejects_target_above_remaining_mana():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=7232)
        burn = p.give("CS2_029")
        burn.play(target=e.hero)
        target = summon(e, "EX1_543")
        before_mana = p.mana
        attack = target.atk
        spell = p.give(cid)
        error = None
        try:
            spell.play(target=target)
        except InvalidAction as exc:
            error = type(exc).__name__
        observed = f"remaining_mana={before_mana};target_attack={attack};error={error};target={target.zone.name};spell={spell.zone.name};mana={p.mana}"
        return check(before_mana == 6 and attack > before_mana and error == "InvalidAction"
                     and target.zone == Zone.PLAY and spell.zone == Zone.HAND
                     and p.mana == before_mana, observed)

    audit(cid, [
        ("spell_spends_all_mana_and_destroys_under_threshold", "Forbidden Words spends all 10 available Mana and destroys a 4-Attack target.", destroys_with_available_mana, "己方有10點可用法力時指定4攻Yeti，核對消滅及法力歸零。"),
        ("higher_attack_than_remaining_mana_is_illegal", "After spending 4 Mana, an 8-Attack minion cannot be targeted with only 6 Mana remaining.", rejects_target_above_remaining_mana, "先施放火球消耗4費，再指定高攻King Krush，要求超出剩餘法力的目標在消費前拒絕。"),
    ])


forbidden_words_spends_all_mana_and_respects_attack_threshold.card_id = "DAL_723"


def mass_resurrection_summons_three_minions_from_friendly_death_pool():
    cid = "DAL_724"

    def three_friendly_deaths_return_three_minions():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=7241)
        originals = [summon(p, WISP) for _ in range(3)]
        g.end_turn()
        removals = []
        for minion in originals:
            removal = e.give(MOONFIRE)
            removal.play(target=minion)
            removals.append(removal)
        g.end_turn()
        spell = play(p, cid)
        revived = list(p.field)
        observed = (f"originals={[m.zone.name for m in originals]};removals={[c.zone.name for c in removals]};"
                    f"spell={spell.zone.name};revived={[(m.id,m.atk,m.health,m.zone.name) for m in revived]};mana={p.mana}")
        return check(all(m.zone == Zone.GRAVEYARD for m in originals)
                     and spell.zone == Zone.GRAVEYARD and len(revived) == 3
                     and all(m.id == WISP and m.zone == Zone.PLAY for m in revived), observed)

    audit(cid, [
        ("summons_three_friendly_minions_that_died_this_game", "Mass Resurrection summons three friendly minions from the three Wisps that died earlier in the game.", three_friendly_deaths_return_three_minions, "對手先以火球逐一擊殺三只己方Wisp；己方下一回合施放Mass Resurrection並核對正好三只Wisp複製。"),
    ])


mass_resurrection_summons_three_minions_from_friendly_death_pool.card_id = "DAL_724"


def scargil_sets_murloc_hand_costs_to_one_and_aura_expires_on_silence():
    cid = "DAL_726"

    def aura_changes_only_murlocs_and_clears_on_silence():
        g, p, e = game(CardClass.SHAMAN, CardClass.MAGE, seed=7261)
        murloc = p.give("EX1_507")
        other = p.give("CS2_182")
        before = (murloc.cost, other.cost)
        scargil = summon(p, cid)
        active_cost = murloc.cost
        silence = p.give("EX1_332")
        silence.play(target=scargil)
        observed = (f"before={before};active_cost={active_cost};murloc_after_silence={murloc.cost};"
                    f"other_cost={other.cost};scargil_silenced={scargil.silenced};silence={silence.zone.name}")
        return check(before == (3,4) and active_cost == 1 and murloc.cost == 3
                     and other.cost == 4 and scargil.silenced, observed)

    audit(cid, [
        ("murloc_hand_cost_one_only_while_scargil_aura_active", "Scargil sets the held Murloc's cost to 1 but leaves a non-Murloc unchanged; silencing Scargil restores printed costs.", aura_changes_only_murlocs_and_clears_on_silence, "手持3費Murloc Warleader和4費Yeti時召喚Scargil，比較費用；再實際沉默Scargil核對魚人費用回到3。"),
    ])


scargil_sets_murloc_hand_costs_to_one_and_aura_expires_on_silence.card_id = "DAL_726"


def call_to_adventure_draws_lowest_cost_minion_and_buffs_it():
    cid = "DAL_727"

    def lowest_cost_beats_lowest_attack():
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=7271)
        cheap_high_attack = put_deck(p, "EX1_045")[0]  # 2-Cost 4/5 Ancient Watcher.
        expensive_low_attack = put_deck(p, "EX1_396")[0]  # 4-Cost 1/7 Mogu'shan Warden.
        spell = play(p, cid)
        observed = (f"spell={spell.zone.name};cheap={cheap_high_attack.id}/{cheap_high_attack.cost}/{cheap_high_attack.atk}/{cheap_high_attack.health}/{cheap_high_attack.zone.name};"
                    f"expensive={expensive_low_attack.id}/{expensive_low_attack.cost}/{expensive_low_attack.atk}/{expensive_low_attack.health}/{expensive_low_attack.zone.name};"
                    f"hand={[(m.id,m.cost,m.atk,m.health,m.zone.name) for m in p.hand]};deck={[c.id for c in p.deck]}")
        return check(spell.zone == Zone.GRAVEYARD and cheap_high_attack.zone == Zone.HAND
                     and (cheap_high_attack.atk,cheap_high_attack.health) == (6,7)
                     and expensive_low_attack.zone == Zone.DECK, observed)

    audit(cid, [
        ("draws_two_cost_watcher_instead_of_lower_attack_four_cost_warden", "Call to Adventure draws the 2-Cost Ancient Watcher rather than a 4-Cost lower-Attack Warden, then gives it +2/+2.", lowest_cost_beats_lowest_attack, "牌庫同時放入2費4攻Ancient Watcher與4費1攻Mogu'shan Warden，區分最低費用與最低攻擊力，並核對抽到者+2/+2。"),
    ])


call_to_adventure_draws_lowest_cost_minion_and_buffs_it.card_id = "DAL_727"


def daring_escape_returns_all_friendly_minions_to_hand():
    cid = "DAL_728"

    def all_friendly_minions_return_but_enemy_stays():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=7281)
        friendly = [summon(p, WISP), summon(p, "CS2_182")]
        enemy = summon(e, WISP)
        spell = play(p, cid)
        observed = (f"spell={spell.zone.name};friendly={[m.zone.name for m in friendly]};"
                    f"hand={[(c.id,c.zone.name) for c in p.hand]};pfield={list(p.field)};"
                    f"enemy={enemy.zone.name}/{enemy.health}")
        return check(spell.zone == Zone.GRAVEYARD and not p.field
                     and all(m.zone == Zone.HAND and m in p.hand for m in friendly)
                     and enemy.zone == Zone.PLAY and enemy.health == 1, observed)

    audit(cid, [
        ("returns_every_friendly_minion_and_no_enemy_minion", "Daring Escape returns both friendly minions to hand and leaves the opponent's minion in play.", all_friendly_minions_return_but_enemy_stays, "己方场上Wisp与Yeti、敌方另有Wisp，施放后检查所有友方回手而敌方不动。"),
    ])


daring_escape_returns_all_friendly_minions_to_hand.card_id = "DAL_728"


def madame_lazul_discovers_a_copy_from_opponents_hand():
    cid = "DAL_729"

    def discover_copy_of_unique_opponent_hand_card():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=7291)
        originals = [e.give(WISP), e.give("CS2_029"), e.give("CS2_182")]
        lazul = play(p, cid)
        choice = p.choice
        options = list(choice.cards) if choice else []
        chosen = options[0] if options else None
        if chosen:
            choice.choose(chosen)
        copies = [card for card in p.hand if card.id == (chosen.id if chosen else None)]
        observed = (f"originals={[(c.id,c.zone.name) for c in originals]};"
                    f"options={[(c.id,c.zone.name) for c in options]};chosen={chosen.id if chosen else None};"
                    f"copies={[(c.id,c.zone.name) for c in copies]};lazul={lazul.zone.name};choice_after={bool(p.choice)}")
        return check(lazul.zone == Zone.PLAY and len(options) == 3
                     and {c.id for c in options} == {c.id for c in originals}
                     and all(c.zone == Zone.HAND for c in originals)
                     and chosen is not None and len(copies) == 1
                     and copies[0] is not next(c for c in originals if c.id == chosen.id)
                     and copies[0].zone == Zone.HAND and p.choice is None, observed)

    audit(cid, [
        ("battlecry_discovers_copy_of_opponents_hand_card", "Madame Lazul offers copies of the opponent's three unique hand cards and puts the selected copy in her controller's hand.", discover_copy_of_unique_opponent_hand_card, "對手手持Wisp、火球、Yeti三種不同卡；打出Lazul並核對選項來源、選中複製入手且原卡仍由對手持有。"),
    ])


madame_lazul_discovers_a_copy_from_opponents_hand.card_id = "DAL_729"


def duel_summons_minions_from_both_decks_and_they_fight():
    cid = "DAL_731"

    def deck_minions_are_summoned_and_fight():
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=7311)
        friendly_deck = put_deck(p, "CS2_182")  # Chillwind Yeti, 4/5
        enemy_deck = put_deck(e, WISP)
        duel = play(p, cid)
        ally = next((m for m in p.field if m.id == "CS2_182"), None)
        foe = next((m for m in e.field if m.id == WISP), None)
        observed = (f"duel={duel.zone.name};friendly_deck={[c.zone.name for c in friendly_deck]};"
                    f"enemy_deck={[c.zone.name for c in enemy_deck]};"
                    f"ally={None if ally is None else (ally.id,ally.atk,ally.health,ally.zone.name)};"
                    f"foe={None if foe is None else (foe.id,foe.zone.name)}")
        return check(duel.zone == Zone.GRAVEYARD and ally is not None and ally.zone == Zone.PLAY
                     and ally.health == 4 and foe is None and all(c.zone != Zone.DECK for c in friendly_deck+enemy_deck), observed)

    audit(cid, [
        ("summons_one_from_each_deck_and_they_fight", "Duel summons the 4/5 Yeti and 1/1 Wisp from their respective decks; they fight, killing the Wisp and leaving Yeti at 4 health.", deck_minions_are_summoned_and_fight, "Seed each deck with exactly one minion of asymmetric stats and verify both deck pulls plus actual combat outcome."),
    ])


duel_summons_minions_from_both_decks_and_they_fight.card_id = "DAL_731"


def keeper_stalladris_adds_both_choose_one_options():
    cid = "DAL_732"

    def casts_choose_one_and_gets_both_copies():
        g, p, e = game(CardClass.DRUID, CardClass.MAGE, seed=7321)
        keeper = play(p, cid)
        wild = p.give("EX1_160")
        wild.play(choose="EX1_160a")
        options = [c for c in p.hand if c.id in ("EX1_160a", "EX1_160b")]
        observed = (f"keeper={keeper.zone.name};wild={wild.zone.name};"
                    f"hand={[(c.id,c.zone.name,c.cost) for c in p.hand]};"
                    f"options={[c.id for c in options]};mana={p.mana}")
        return check(wild.zone == Zone.GRAVEYARD and len(options) == 2
                     and {c.id for c in options} == {"EX1_160a", "EX1_160b"}
                     and all(c.zone == Zone.HAND for c in options), observed)

    audit(cid, [
        ("choose_one_cast_adds_both_choice_cards", "After casting Power of the Wild's +1/+1 choice, Keeper adds one hand copy of each Choose One option.", casts_choose_one_and_gets_both_copies, "Play Keeper, cast Power of the Wild choosing the buff option, then inspect both distinct choice cards in hand."),
    ])


keeper_stalladris_adds_both_choose_one_options.card_id = "DAL_732"


def dreamway_guardians_summons_two_lifesteal_dryads():
    cid = "DAL_733"

    def creates_two_correct_tokens():
        g, p, e = game(CardClass.DRUID, CardClass.MAGE, seed=7331)
        spell = play(p, cid)
        tokens = [m for m in p.field if m.id == "DAL_733t"]
        observed = (f"spell={spell.zone.name};tokens={[(m.id,m.atk,m.health,m.max_health,m.tags[GameTag.LIFESTEAL]) for m in tokens]};"
                    f"board={len(p.field)}")
        return check(spell.zone == Zone.GRAVEYARD and len(tokens) == 2
                     and all(m.atk == 1 and m.health == 2 and m.tags[GameTag.LIFESTEAL] for m in tokens), observed)

    audit(cid, [
        ("summons_two_one_two_lifesteal_dryads", "Dreamway Guardians summons exactly two 1/2 Dryads and both have Lifesteal.", creates_two_correct_tokens, "Cast into an empty friendly board and assert exact token count, attack, health, and Lifesteal keyword."),
    ])


dreamway_guardians_summons_two_lifesteal_dryads.card_id = "DAL_733"


def dalaran_librarian_silences_only_adjacent_minions():
    cid = "DAL_735"

    def silence_neighbors_and_leave_distant_deathrattle():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7351)
        left = summon(p, "DAL_566")
        center = summon(p, "CS2_182")
        right = summon(p, "DAL_566")
        far = summon(p, "DAL_566")
        lib = play(p, cid, index=2)
        adjacent = (center, right)
        observed = (f"board={[(m.id,m.zone.name,getattr(m,'silenced',None),getattr(m,'has_deathrattle',None)) for m in p.field]};"
                    f"far={far.zone.name}/{getattr(far,'silenced',None)}/{getattr(far,'has_deathrattle',None)};"
                    f"librarian={lib.zone.name}")
        return check(all(m.zone == Zone.PLAY and m.silenced for m in adjacent)
                     and all(not m.has_deathrattle for m in adjacent)
                     and not left.silenced and left.has_deathrattle
                     and not far.silenced and far.has_deathrattle, observed)

    audit(cid, [
        ("battlecry_silences_two_adjacent_only", "Dalaran Librarian silences the minion immediately to its left and right, removing their Deathrattles, while a distant Deathrattle remains.", silence_neighbors_and_leave_distant_deathrattle, "Insert Librarian between a Deathrattle minion and Yeti, with another Deathrattle adjacent and a fourth minion distant; assert only neighbors are silenced."),
    ])


dalaran_librarian_silences_only_adjacent_minions.card_id = "DAL_735"


def archivist_elysiana_replaces_deck_with_two_copies_of_each_choice():
    cid = "DAL_736"

    def five_choices_make_ten_card_deck():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7361)
        old = put_deck(p, "CS2_182", 3)
        body = play(p, cid)
        selected = []
        for _ in range(5):
            choice = p.choice
            if not choice:
                break
            card = choice.cards[0]
            selected.append(card.id)
            choice.choose(card)
        counts = {cid: sum(c.id == cid for c in p.deck) for cid in set(selected)}
        observed = (f"body={body.zone.name};selected={selected};deck_len={len(p.deck)};"
                    f"deck={[(c.id,c.zone.name) for c in p.deck]};counts={counts};"
                    f"old={[c.zone.name for c in old]};choice={bool(p.choice)}")
        return check(len(selected) == 5 and len(p.deck) == 10 and p.choice is None
                     and all(counts[cid] == 2 for cid in set(selected))
                     and all(c.id not in {old_card.id for old_card in old} for c in p.deck), observed)

    audit(cid, [
        ("battlecry_replaces_deck_with_two_each_of_five_choices", "After five Discover selections, Elysiana replaces the old deck with exactly two copies of each of the five selected cards.", five_choices_make_ten_card_deck, "Seed an old deck, play Elysiana, make all five real choices, then verify the new ten-card deck has precisely two copies per selection and no old cards."),
    ])


archivist_elysiana_replaces_deck_with_two_copies_of_each_choice.card_id = "DAL_736"


def whirlwind_tempest_grants_mega_windfury_only_to_windfury_minions():
    cid = "DAL_742"

    def applies_aura_keyword_to_windfury_minions():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7421)
        tempest = summon(p, cid)
        fountain = summon(p, "DAL_047")
        plain = summon(p, WISP)
        observed = (f"tempest={tempest.zone.name};fountain={fountain.id}/{fountain.atk}/{fountain.health}/"
                    f"windfury={fountain.tags[GameTag.WINDFURY]}/mega={fountain.tags[GameTag.MEGA_WINDFURY]};"
                    f"plain={plain.id}/mega={plain.tags[GameTag.MEGA_WINDFURY]}")
        return check(fountain.tags[GameTag.WINDFURY] and fountain.tags[GameTag.MEGA_WINDFURY]
                     and not plain.tags[GameTag.MEGA_WINDFURY], observed)

    audit(cid, [
        ("windfury_minions_gain_mega_windfury_aura", "Whirlwind Tempest grants Mega-Windfury to Walking Fountain, which has Windfury, but not to a Wisp.", applies_aura_keyword_to_windfury_minions, "Control the aura source, a real printed Windfury minion, and a plain minion; inspect both live keyword tags."),
    ])


whirlwind_tempest_grants_mega_windfury_only_to_windfury_minions.card_id = "DAL_742"


def hench_clan_hogsteed_rush_and_deathrattle():
    cid = "DAL_743"

    def rush_attack_then_death_summons_murloc():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7431)
        enemy = summon(e, WISP)
        hog = play(p, cid)
        rush_error = None
        try:
            hog.attack(enemy)
        except Exception as exc:
            rush_error = type(exc).__name__
        before_death = (hog.zone.name, hog.health, enemy.zone.name)
        hog.destroy()
        tokens = [m for m in p.field if m.id == "DAL_743t"]
        observed = (f"rush_error={rush_error};after_attack={before_death};hog={hog.zone.name};"
                    f"tokens={[(m.id,m.atk,m.health,str(m.race),m.zone.name) for m in tokens]};"
                    f"board={[(m.id,m.zone.name) for m in p.field]}")
        return check(rush_error is None and enemy.zone == Zone.GRAVEYARD
                     and hog.zone == Zone.GRAVEYARD and len(tokens) == 1
                     and tokens[0].atk == 1 and tokens[0].health == 1, observed)

    audit(cid, [
        ("rush_can_attack_minion_and_death_summons_one_one_murloc", "Hench-Clan Hogsteed attacks an enemy minion immediately via Rush, then on death summons one 1/1 Murloc.", rush_attack_then_death_summons_murloc, "Play Hogsteed into an enemy Wisp, assert immediate minion attack legality and death, then destroy Hogsteed and inspect the Murloc token."),
    ])


hench_clan_hogsteed_rush_and_deathrattle.card_id = "DAL_743"


def faceless_rager_copies_friendly_target_health():
    cid = "DAL_744"

    def copies_buffed_friendly_health():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=7441)
        target = summon(p, WISP)
        shield = play(p, "CS2_004", target=target)
        rager = play(p, cid, target=target)
        observed = (f"target={target.id}/{target.atk}/{target.health}/{target.max_health};"
                    f"shield={shield.zone.name};rager={rager.id}/{rager.atk}/{rager.health}/{rager.max_health};"
                    f"board={[(m.id,m.health,m.max_health) for m in p.field]}")
        return check(target.max_health == 3 and target.health == 3
                     and rager.zone == Zone.PLAY and rager.health == 3 and rager.max_health == 3, observed)

    audit(cid, [
        ("battlecry_copies_friendly_target_health", "Faceless Rager copies the selected friendly Wisp's buffed 3 Health.", copies_buffed_friendly_health, "Buff a friendly Wisp with Power Word: Shield from 1 to 3 Health, target it with Rager, and compare current and maximum health."),
    ])


faceless_rager_copies_friendly_target_health.card_id = "DAL_744"


def flight_master_summons_gryphon_for_each_player():
    cid = "DAL_747"

    def creates_one_correct_gryphon_on_both_sides():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7471)
        flier = play(p, cid)
        own = [m for m in p.field if m.id == "DAL_747t"]
        opposing = [m for m in e.field if m.id == "DAL_747t"]
        observed = (f"flier={flier.zone.name};own={[(m.atk,m.health,m.zone.name) for m in own]};"
                    f"opposing={[(m.atk,m.health,m.zone.name) for m in opposing]};"
                    f"boards={len(p.field)}/{len(e.field)}")
        return check(flier.zone == Zone.PLAY and len(own) == len(opposing) == 1
                     and all(m.atk == 2 and m.health == 2 for m in own + opposing), observed)

    audit(cid, [
        ("battlecry_summons_one_two_two_gryphon_for_each_player", "Flight Master creates exactly one 2/2 Gryphon on its controller's board and one on the opponent's board.", creates_one_correct_gryphon_on_both_sides, "Play into empty boards and inspect each controller's token identity, count, attack, and health."),
    ])


flight_master_summons_gryphon_for_each_player.card_id = "DAL_747"


def mana_reservoir_spell_damage_adds_one_damage():
    cid = "DAL_748"

    def spell_damage_changes_six_damage_to_seven():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7481)
        reservoir = summon(p, cid)
        target = summon(e, "EX1_396")  # Mogu'shan Warden, 3/7
        spell = play(p, "CS2_029", target=target)
        observed = (f"reservoir={reservoir.id}/spellpower={reservoir.tags[GameTag.SPELLPOWER]};"
                    f"target={target.id}/{target.zone.name}/{target.health};spell={spell.zone.name}")
        return check(reservoir.tags[GameTag.SPELLPOWER] == 1 and spell.zone == Zone.GRAVEYARD
                     and target.zone == Zone.GRAVEYARD, observed)

    audit(cid, [
        ("spell_damage_plus_one_kills_seven_health_target", "Mana Reservoir's Spell Damage +1 raises Fireball's damage from 6 to 7 and kills a 3/7 Mogu'shan Warden.", spell_damage_changes_six_damage_to_seven, "Cast Fireball into an undamaged 7-health minion with only Mana Reservoir contributing spell damage; verify the target dies."),
    ])


mana_reservoir_spell_damage_adds_one_damage.card_id = "DAL_748"


def recurring_villain_resummons_only_at_four_attack():
    cid = "DAL_749"

    def base_attack_three_dies_without_resummon():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7491)
        villain = summon(p, cid)
        base_attack = villain.atk
        villain.destroy()
        copies = [m for m in p.field if m.id == cid]
        observed = f"base_attack={base_attack};dead={villain.zone.name};copies={[(m.atk,m.health,m.zone.name) for m in copies]}"
        return check(villain.zone == Zone.GRAVEYARD and len(copies) == (1 if base_attack >= 4 else 0), observed)

    def buffed_attack_four_or_more_resummons():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7492)
        villain = summon(p, cid)
        buff = play(p, "CS2_087", target=villain)  # Blessing of Might, +3 Attack this turn
        dying_attack = villain.atk
        villain.destroy()
        copies = [m for m in p.field if m.id == cid]
        observed = (f"buff={buff.zone.name};dying_attack={dying_attack};dead={villain.zone.name};"
                    f"copies={[(m.atk,m.health,m.zone.name) for m in copies]}")
        return check(dying_attack >= 4 and villain.zone == Zone.GRAVEYARD
                     and len(copies) == 1 and copies[0].zone == Zone.PLAY, observed)

    audit(cid, [
        ("below_four_attack_does_not_resummon", "Recurring Villain below 4 Attack dies without a replacement.", base_attack_three_dies_without_resummon, "Destroy an unbuffed base copy and verify the below-threshold death branch (or matching above-threshold branch if card stats differ)."),
        ("four_or_more_attack_resummons_villain", "Recurring Villain with at least 4 Attack is resummoned by its Deathrattle.", buffed_attack_four_or_more_resummons, "Give the Villain +3 temporary Attack, destroy it, and verify the threshold was met and a fresh copy is in play."),
    ])


recurring_villain_resummons_only_at_four_attack.card_id = "DAL_749"


def mad_summoner_fills_both_boards_without_overflow():
    cid = "DAL_751"

    def fills_each_remaining_board_slot_to_seven():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7511)
        own_seed = summon(p, WISP)
        enemy_seeds = [summon(e, WISP) for _ in range(6)]
        summoner = play(p, cid)
        own_imps = [m for m in p.field if m.id == "DAL_751t"]
        enemy_imps = [m for m in e.field if m.id == "DAL_751t"]
        observed = (f"summoner={summoner.zone.name};own_board={[(m.id,m.atk,m.health) for m in p.field]};"
                    f"enemy_board={[(m.id,m.atk,m.health) for m in e.field]};"
                    f"imps={len(own_imps)}/{len(enemy_imps)};seeds={own_seed.zone.name}/{[m.zone.name for m in enemy_seeds]}")
        return check(len(p.field) == 7 and len(e.field) == 7 and len(own_imps) == 5
                     and len(enemy_imps) == 1 and all(m.atk == 1 and m.health == 1 for m in own_imps + enemy_imps), observed)

    def empty_boards_both_fill_to_seven():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7512)
        summoner = play(p, cid)
        own_imps = [m for m in p.field if m.id == "DAL_751t"]
        enemy_imps = [m for m in e.field if m.id == "DAL_751t"]
        observed = (f"summoner={summoner.zone.name};own={[m.id for m in p.field]};"
                    f"enemy={[m.id for m in e.field]};imps={len(own_imps)}/{len(enemy_imps)}")
        return check(len(p.field) == 7 and len(e.field) == 7 and len(own_imps) == 6
                     and len(enemy_imps) == 7
                     and all(m.atk == 1 and m.health == 1 for m in own_imps + enemy_imps), observed)

    audit(cid, [
        ("battlecry_fills_each_board_to_seven_with_one_one_imps", "Mad Summoner fills each board to its seven-minion cap with 1/1 Imps without exceeding capacity.", fills_each_remaining_board_slot_to_seven, "Start with one friendly and six enemy minions; play Mad Summoner and assert both boards stop at seven with five own and one opposing 1/1 Imps."),
        ("empty_board_branch_fills_both_sides_to_seven", "From empty boards, Mad Summoner fills its own side with itself plus six Imps and the opponent side with seven Imps.", empty_boards_both_fill_to_seven, "Play into two empty boards so no capacity edge case or existing minion can explain missing opposing tokens."),
    ])


mad_summoner_fills_both_boards_without_overflow.card_id = "DAL_751"


def jepetto_joybuzz_draws_two_minions_and_sets_them_to_one():
    cid = "DAL_752"

    def two_drawn_minions_have_one_attack_health_and_cost():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7521)
        originals = put_deck(p, "EX1_543") + put_deck(p, "EX1_396")
        jepetto = play(p, cid)
        drawn = [c for c in p.hand if c.id in {"EX1_543", "EX1_396"}]
        observed = (f"jepetto={jepetto.zone.name};drawn={[(c.id,c.zone.name,c.atk,c.health,c.cost) for c in drawn]};"
                    f"deck={[(c.id,c.zone.name) for c in p.deck]};originals={[c.zone.name for c in originals]}")
        return check(len(drawn) == 2 and {c.id for c in drawn} == {"EX1_543", "EX1_396"}
                     and all(c.zone == Zone.HAND and c.atk == c.health == c.cost == 1 for c in drawn)
                     and not any(c.id in {"EX1_543", "EX1_396"} for c in p.deck), observed)

    audit(cid, [
        ("battlecry_draws_two_minions_and_sets_stats_and_cost_to_one", "Jepetto draws both deck minions and sets each to 1 Attack, 1 Health, and 1 Cost.", two_drawn_minions_have_one_attack_health_and_cost, "Seed exactly two distinct minions with very different printed costs/stats, play Jepetto, and inspect both drawn hand entities and remaining deck."),
    ])


jepetto_joybuzz_draws_two_minions_and_sets_them_to_one.card_id = "DAL_752"


def vicious_scraphound_gains_armor_equal_to_damage_dealt():
    cid = "DAL_759"

    def minion_combat_damage_becomes_armor():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=7591)
        scrap = summon(p, cid)
        victim = summon(e, WISP)
        end_round(g)
        armor_before = p.hero.armor
        attack_error = None
        try:
            scrap.attack(victim)
        except Exception as exc:
            attack_error = type(exc).__name__
        observed = (f"ready={getattr(scrap,'exhausted',None)};attack_error={attack_error};"
                    f"scrap={scrap.zone.name}/{scrap.health};victim={victim.zone.name};"
                    f"armor={armor_before}->{p.hero.armor};scrap_atk={scrap.atk}")
        return check(attack_error is None and victim.zone == Zone.GRAVEYARD
                     and scrap.zone == Zone.PLAY and p.hero.armor == armor_before + scrap.atk, observed)

    audit(cid, [
        ("deals_two_combat_damage_and_gains_two_armor", "When Scraphound deals 2 damage to a Wisp in combat, its controller gains exactly 2 Armor.", minion_combat_damage_becomes_armor, "Wait until Scraphound is attack-ready, have it kill a 1/1 enemy Wisp, and compare hero armor before and after its known 2 damage."),
    ])


vicious_scraphound_gains_armor_equal_to_damage_dealt.card_id = "DAL_759"


def burly_shovelfist_rush_attacks_minion_but_not_hero():
    cid = "DAL_760"

    def rush_rejects_hero_and_allows_minion():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7601)
        enemy = summon(e, WISP)
        shovelfist = play(p, cid)
        hero_error = None
        try:
            shovelfist.attack(e.hero)
        except Exception as exc:
            hero_error = type(exc).__name__
        minion_error = None
        try:
            shovelfist.attack(enemy)
        except Exception as exc:
            minion_error = type(exc).__name__
        observed = (f"hero_error={hero_error};minion_error={minion_error};"
                    f"shovelfist={shovelfist.zone.name}/{shovelfist.atk}/{shovelfist.health};"
                    f"enemy={enemy.zone.name};hero_hp={e.hero.health}")
        return check(hero_error == "InvalidAction" and minion_error is None
                     and enemy.zone == Zone.GRAVEYARD and e.hero.health == 30, observed)

    audit(cid, [
        ("rush_only_attacks_enemy_minion_on_play_turn", "Burly Shovelfist cannot attack the enemy hero the turn it is played, but Rush permits an immediate attack on an enemy minion.", rush_rejects_hero_and_allows_minion, "Attempt a hero attack first and require InvalidAction without consuming the attack; then attack an enemy Wisp and verify it dies while the enemy hero is untouched."),
    ])


burly_shovelfist_rush_attacks_minion_but_not_hero.card_id = "DAL_760"


def improve_morale_adds_lackey_only_if_target_survives():
    cid = "DAL_769"
    lackey_ids = {"DAL_613", "DAL_614", "DAL_615", "DAL_739", "DAL_741", "ULD_616", "DRG_052"}

    def surviving_minion_adds_one_lackey():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=7691)
        target = summon(e, "CS2_182")
        spell = play(p, cid, target=target)
        lackeys = [c for c in p.hand if c.id in lackey_ids]
        observed = (f"spell={spell.zone.name};target={target.id}/{target.zone.name}/{target.health};"
                    f"lackeys={[(c.id,c.zone.name) for c in lackeys]};hand={[c.id for c in p.hand]}")
        return check(spell.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY
                     and target.health == 4 and len(lackeys) == 1, observed)

    def lethal_damage_adds_no_lackey():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=7692)
        target = summon(e, WISP)
        spell = play(p, cid, target=target)
        lackeys = [c for c in p.hand if c.id in lackey_ids]
        observed = (f"spell={spell.zone.name};target={target.id}/{target.zone.name}/{target.health};"
                    f"lackeys={[(c.id,c.zone.name) for c in lackeys]};hand={[c.id for c in p.hand]}")
        return check(spell.zone == Zone.GRAVEYARD and target.zone == Zone.GRAVEYARD
                     and len(lackeys) == 0, observed)

    audit(cid, [
        ("survivor_takes_one_and_adds_exactly_one_lackey", "Improve Morale deals 1 damage to a surviving Yeti and adds exactly one Lackey.", surviving_minion_adds_one_lackey, "Target a 5-health Yeti, then assert the damage and exactly one Lackey from the seven-card Lackey ID set."),
        ("lethal_one_damage_adds_no_lackey", "When Improve Morale's 1 damage kills a Wisp, it adds no Lackey.", lethal_damage_adds_no_lackey, "Target a 1-health Wisp and inspect the graveyard transition plus absence of all Lackey IDs in hand."),
    ])


improve_morale_adds_lackey_only_if_target_survives.card_id = "DAL_769"


def omega_devastator_deals_ten_only_at_ten_crystals():
    cid = "DAL_770"

    def ten_crystals_kills_minion():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=7701)
        target = summon(e, "CS2_182")
        card = play(p, cid, target=target)
        observed = f"max_mana={p.max_mana};card={card.zone.name};target={target.zone.name}/{target.health}"
        return check(p.max_mana == 10 and card.zone == Zone.PLAY and target.zone == Zone.GRAVEYARD, observed)

    def nine_crystals_do_not_damage_minion():
        g, p, e = game(CardClass.WARRIOR, CardClass.MAGE, seed=7702)
        p.max_mana = 9
        target = summon(e, "CS2_182")
        card = play(p, cid, target=target)
        observed = f"max_mana={p.max_mana};card={card.zone.name};target={target.zone.name}/{target.health}"
        return check(p.max_mana == 9 and card.zone == Zone.PLAY
                     and target.zone == Zone.PLAY and target.health == 5, observed)

    audit(cid, [
        ("ten_crystal_battlecry_deals_ten_damage", "With 10 Mana Crystals, Omega Devastator's Battlecry deals 10 damage and kills a Yeti.", ten_crystals_kills_minion, "Play with exactly ten maximum Mana Crystals and inspect the selected minion's death."),
        ("nine_crystal_battlecry_does_not_damage", "With only 9 Mana Crystals, Omega Devastator leaves a Yeti undamaged.", nine_crystals_do_not_damage_minion, "Reduce maximum Mana Crystals to nine before the Battlecry and verify no damage is applied."),
    ])


omega_devastator_deals_ten_only_at_ten_crystals.card_id = "DAL_770"


def soldier_of_fortune_gives_opponent_coin_when_attacking():
    cid = "DAL_771"

    def attack_triggers_exactly_one_opponent_coin():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7711)
        soldier = summon(p, cid)
        end_round(g)
        before_coins = sum(c.id == THE_COIN for c in e.hand)
        attack_error = None
        try:
            soldier.attack(e.hero)
        except Exception as exc:
            attack_error = type(exc).__name__
        after_coins = sum(c.id == THE_COIN for c in e.hand)
        observed = (f"attack_error={attack_error};soldier={soldier.zone.name}/{soldier.atk};"
                    f"enemy_hp={e.hero.health};coins={before_coins}->{after_coins};"
                    f"enemy_hand={[c.id for c in e.hand]}")
        return check(attack_error is None and e.hero.health == 30 - soldier.atk
                     and after_coins == before_coins + 1, observed)

    audit(cid, [
        ("attack_gives_opponent_one_coin", "Whenever Soldier of Fortune attacks, the opponent receives exactly one Coin.", attack_triggers_exactly_one_opponent_coin, "Wait until this minion can attack, attack the opposing hero, and assert both actual combat damage and one new Coin in the opponent's hand."),
    ])


soldier_of_fortune_gives_opponent_coin_when_attacking.card_id = "DAL_771"


def magic_carpet_buffs_only_played_one_cost_minions():
    cid = "DAL_773"

    def one_cost_minion_gains_attack_and_rush_not_zero_cost():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7731)
        carpet = play(p, cid)
        free = play(p, WISP)
        one_cost_card = p.give("GIL_558")  # Swamp Leech
        base_attack = one_cost_card.atk
        leech = one_cost_card.play()
        observed = (f"carpet={carpet.zone.name};free={free.id}/{free.cost}/{free.atk}/rush={free.tags[GameTag.RUSH]};"
                    f"one_cost={leech.id}/{leech.cost}/{base_attack}->{leech.atk}/rush={leech.tags[GameTag.RUSH]};"
                    f"board={[m.id for m in p.field]}")
        return check(free.atk == 1 and not free.tags[GameTag.RUSH]
                     and leech.zone == Zone.PLAY and leech.cost == 1
                     and leech.atk == base_attack + 1 and leech.tags[GameTag.RUSH], observed)

    audit(cid, [
        ("only_one_cost_minion_gains_one_attack_and_rush", "Magic Carpet leaves a 0-Cost Wisp unchanged and gives a played 1-Cost Swamp Leech +1 Attack and Rush.", one_cost_minion_gains_attack_and_rush_not_zero_cost, "Play the aura, then a zero-cost Wisp and one-cost minion in the same turn; compare their attack and Rush tags."),
    ])


magic_carpet_buffs_only_played_one_cost_minions.card_id = "DAL_773"


def exotic_mountseller_summons_three_cost_beast_after_spell():
    cid = "DAL_774"

    def one_cast_spell_summons_one_three_cost_beast():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7741)
        mountseller = play(p, cid)
        before = set(id(m) for m in p.field)
        spell = play(p, MOONFIRE, target=e.hero)
        summoned = [m for m in p.field if id(m) not in before and m is not mountseller]
        observed = (f"mountseller={mountseller.zone.name};spell={spell.zone.name};new={[(m.id,m.cost,m.type,str(m.races),m.zone.name) for m in summoned]};"
                    f"field={[m.id for m in p.field]}")
        return check(spell.zone == Zone.GRAVEYARD and len(summoned) == 1
                     and summoned[0].type == CardType.MINION and summoned[0].cost == 3
                     and Race.BEAST in summoned[0].races, observed)

    audit(cid, [
        ("casting_a_spell_summons_one_random_three_cost_beast", "After one friendly spell is cast, Exotic Mountseller summons exactly one 3-Cost Beast.", one_cast_spell_summons_one_three_cost_beast, "Snapshot the friendly board, cast Moonfire, then inspect only newly summoned entities for minion type, Beast race, and Cost 3."),
    ])


exotic_mountseller_summons_three_cost_beast_after_spell.card_id = "DAL_774"


def tunnel_blaster_taunt_deathrattle_damages_all_minions():
    cid = "DAL_775"

    def death_deals_three_to_both_boards_only():
        g, p, e = game(CardClass.MAGE, CardClass.MAGE, seed=7751)
        ally = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        blaster = play(p, cid)
        taunt_before = blaster.tags[GameTag.TAUNT]
        blaster.destroy()
        observed = (f"blaster={blaster.zone.name};taunt_before={taunt_before};"
                    f"ally={ally.zone.name}/{ally.health};enemy={enemy.zone.name}/{enemy.health};"
                    f"heroes={p.hero.health}/{e.hero.health}")
        return check(taunt_before and blaster.zone == Zone.GRAVEYARD
                     and ally.zone == Zone.PLAY and enemy.zone == Zone.PLAY
                     and ally.health == enemy.health == 2
                     and p.hero.health == e.hero.health == 30, observed)

    audit(cid, [
        ("taunt_deathrattle_deals_three_to_every_minion", "Tunnel Blaster has Taunt and its death deals 3 damage to all minions on both sides without damaging heroes.", death_deals_three_to_both_boards_only, "Put a 5-health Yeti on each side, play Tunnel Blaster, destroy it, and assert both Yetis lose exactly 3 health while heroes remain untouched."),
    ])


tunnel_blaster_taunt_deathrattle_damages_all_minions.card_id = "DAL_775"


def crystal_stag_threshold_summons_copy_after_five_restored():
    cid = "DAL_799"

    def six_restored_health_summons_second_rush_stag():
        g, p, e = game(CardClass.DRUID, CardClass.MAGE, seed=7991)
        p.hero.set_current_health(20)
        heals = [play(p, "TRL_128", target=p.hero) for _ in range(2)]
        restored_health = p.hero.health - 20
        stag = play(p, cid)
        stags = [m for m in p.field if m.id == cid]
        observed = (f"heals={[h.zone.name for h in heals]};hero={p.hero.health};"
                    f"restored={restored_health};played={stag.zone.name};"
                    f"stags={[(m.id,m.atk,m.health,m.tags[GameTag.RUSH],m.zone.name) for m in stags]}")
        return check(restored_health == 6 and len(stags) == 2
                     and all(m.tags[GameTag.RUSH] for m in stags), observed)

    def three_restored_health_does_not_summon_copy():
        g, p, e = game(CardClass.DRUID, CardClass.MAGE, seed=7992)
        p.hero.set_current_health(20)
        heal = play(p, "TRL_128", target=p.hero)
        restored_health = p.hero.health - 20
        stag = play(p, cid)
        stags = [m for m in p.field if m.id == cid]
        observed = (f"heal={heal.zone.name};hero={p.hero.health};restored={restored_health};"
                    f"played={stag.zone.name};stags={[(m.id,m.atk,m.health,m.tags[GameTag.RUSH],m.zone.name) for m in stags]}")
        return check(restored_health == 3 and len(stags) == 1
                     and stags[0].tags[GameTag.RUSH], observed)

    audit(cid, [
        ("five_or_more_restored_health_summons_rush_copy", "After restoring at least 5 Health this game, Crystal Stag's Battlecry summons one exact copy; both have Rush.", six_restored_health_summons_second_rush_stag, "Damage own hero to 20, restore 6 with two Regenerates, then play Stag and count both Rush bodies."),
        ("below_five_restored_health_does_not_copy", "Restoring only 3 Health does not trigger Crystal Stag's copy Battlecry, leaving only the played Rush Stag.", three_restored_health_does_not_summon_copy, "Damage own hero to 20, restore only 3, then assert no extra Stag is summoned."),
    ])


crystal_stag_threshold_summons_copy_after_five_restored.card_id = "DAL_799"


def zayle_replaces_starting_deck_with_thirty_cards():
    cid = "DAL_800"

    def starting_deck_is_replaced_for_both_players():
        p1 = Player("Audit P1", [cid], "DAL_800h")
        p2 = Player("Audit P2", [cid], "DAL_800h")
        g = BaseTestGame(players=(p1, p2))
        g.start()
        deck1 = list(p1.starting_deck)
        deck2 = list(p2.starting_deck)
        ids1 = [getattr(card, "id", card) for card in deck1]
        ids2 = [getattr(card, "id", card) for card in deck2]
        live_total1 = len(p1.deck) + sum(c.id != THE_COIN for c in p1.hand)
        live_total2 = len(p2.deck) + sum(c.id != THE_COIN for c in p2.hand)
        observed = (f"starting_decks={len(deck1)}/{len(deck2)};p1={ids1};p2={ids2};"
                    f"live_deck_plus_opening_hand={live_total1}/{live_total2};"
                    f"deck_hand={len(p1.deck)}+{[c.id for c in p1.hand]}/{len(p2.deck)}+{[c.id for c in p2.hand]};"
                    f"hero={p1.hero.id}/{p2.hero.id}")
        return check(len(deck1) == len(deck2) == 30
                     and cid not in ids1 and cid not in ids2
                     and live_total1 == live_total2 == 30, observed)

    audit(cid, [
        ("start_of_game_replaces_zayle_deck_with_thirty_cards", "Starting a game with Zayle in the deck replaces the one-card deck with a full 30-card EVIL deck for both players.", starting_deck_is_replaced_for_both_players, "Construct the actual game using Zayle as each player's only starting deck card; start the game and inspect both constructed decks and active decks."),
    ])


zayle_replaces_starting_deck_with_thirty_cards.card_id = "DAL_800"


batterhead_rush_kills_and_may_attack_again.card_id = "DAL_592"

AUDITS = [batterhead_rush_kills_and_may_attack_again,
          plot_twist_shuffles_hand_then_draws_same_number,
          mana_cyclone_adds_one_mage_spell_per_spell_cast,
          ursatron_deathrattle_draws_mech_and_leaves_other_cards,
          impferno_buffs_demons_and_damages_enemy_board,
          evil_genius_destroys_friendly_target_and_adds_two_lackeys,
          fel_lord_betrug_summons_rush_copy_that_dies_at_turn_end,
          magic_trick_discovers_spell_costing_three_or_less,
          kalecgos_discovers_and_makes_only_first_spell_free,
          soul_of_murloc_grants_deathrattle_to_friendly_minions,
          underbelly_fence_gets_stats_and_rush_with_foreign_class_card,
          vendetta_costs_zero_only_with_foreign_class_card,
          tak_nozwhisker_copies_friendly_shuffle_to_hand,
          waggle_pick_deathrattle_returns_minion_discounted_by_two,
          catrina_muerte_summons_friendly_minion_that_died_this_game,
          forbidden_words_spends_all_mana_and_respects_attack_threshold,
          mass_resurrection_summons_three_minions_from_friendly_death_pool,
          scargil_sets_murloc_hand_costs_to_one_and_aura_expires_on_silence,
          call_to_adventure_draws_lowest_cost_minion_and_buffs_it,
          daring_escape_returns_all_friendly_minions_to_hand,
          madame_lazul_discovers_a_copy_from_opponents_hand,
          duel_summons_minions_from_both_decks_and_they_fight,
          keeper_stalladris_adds_both_choose_one_options,
          dreamway_guardians_summons_two_lifesteal_dryads,
          dalaran_librarian_silences_only_adjacent_minions,
          archivist_elysiana_replaces_deck_with_two_copies_of_each_choice,
          whirlwind_tempest_grants_mega_windfury_only_to_windfury_minions,
          hench_clan_hogsteed_rush_and_deathrattle,
          faceless_rager_copies_friendly_target_health,
          flight_master_summons_gryphon_for_each_player,
          mana_reservoir_spell_damage_adds_one_damage,
          recurring_villain_resummons_only_at_four_attack,
          mad_summoner_fills_both_boards_without_overflow,
          jepetto_joybuzz_draws_two_minions_and_sets_them_to_one,
          vicious_scraphound_gains_armor_equal_to_damage_dealt,
          burly_shovelfist_rush_attacks_minion_but_not_hero,
          improve_morale_adds_lackey_only_if_target_survives,
          omega_devastator_deals_ten_only_at_ten_crystals,
          soldier_of_fortune_gives_opponent_coin_when_attacking,
          magic_carpet_buffs_only_played_one_cost_minions,
          exotic_mountseller_summons_three_cost_beast_after_spell,
          tunnel_blaster_taunt_deathrattle_damages_all_minions,
          crystal_stag_threshold_summons_copy_after_five_restored,
          zayle_replaces_starting_deck_with_thirty_cards]


def main():
    from collections import Counter
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="zero-based frozen-roster index")
    parser.add_argument("--limit", type=int, default=44)
    args = parser.parse_args()
    assert 0 <= args.start < 44 and 1 <= args.limit <= 44
    selected = AUDITS[args.start:args.start + args.limit]
    statuses = []
    for row, fn in zip(ROSTER[args.start:args.start + args.limit], selected):
        assert row["card_id"] == fn.card_id
        fn()
        statuses.append(next(r["status"] for r in VERDICTS if r["card_id"] == fn.card_id))
    print(f"audited={len(statuses)} statuses={dict(Counter(statuses))}; "
          f"roster={[r['card_id'] for r in ROSTER[args.start:args.start+len(statuses)]]}")


if __name__ == "__main__":
    main()
