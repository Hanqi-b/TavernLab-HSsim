"""Targeted live-game probes for frozen ordinary TROLL YELLOW indices 90:134."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, GameTag, Race, Zone
from fireplace.exceptions import InvalidAction

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import WISP, MOONFIRE, FIREBALL, prepare_empty_game  # noqa: E402

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
MECHANISMS = HERE / "card_mechanism.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE_OUT = HERE / "troll_probe_c.csv"
VERDICT_OUT = HERE / "troll_verdict_c.csv"
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
    (r for r in read_csv(BASELINE)
     if r["set"].startswith("Rastakhan's Rumble") and r["scope"] == "ordinary_collectible"),
    key=lambda r: r["card_id"],
)
OWN_ROWS = BASE_ROWS[90:134]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
assert len(OWN_IDS) == 44 and OWN_IDS[0] == "TRL_500" and OWN_IDS[-1] == "TRL_901"
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY)}
MECHANISMS_BY_ID = {}
for _row in read_csv(MECHANISMS):
    MECHANISMS_BY_ID.setdefault(_row["card_id"], []).append(_row)
ISSUES_FOR_CARD = {}
for _row in read_csv(ISSUES):
    for _field in ("confirmed_cards", "candidate_cards"):
        for _card_id in _row[_field].split("|"):
            if _card_id:
                ISSUES_FOR_CARD.setdefault(_card_id, []).append(_row)
PROBE_ROWS = read_csv(PROBE_OUT) if PROBE_OUT.exists() else []
VERDICT_ROWS = read_csv(VERDICT_OUT) if VERDICT_OUT.exists() else []


def new_game(class1=CardClass.MAGE, class2=CardClass.MAGE, seed=8901):
    random.seed(seed)
    game = prepare_empty_game(class1, class2)
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
    card = player.summon(card_id)
    assert card is not None, f"could not summon {card_id}"
    return card


def put_deck(player, card_id, count=1):
    cards = []
    for _ in range(count):
        card = player.give(card_id)
        card.shuffle_into_deck()
        cards.append(card)
    return cards


def ids(cards):
    return [card.id for card in cards]


def card_state(card):
    if card is None:
        return None
    stats = (card.atk, card.health) if card.type == CardType.MINION else None
    return (card.id, int(card.type), card.zone.name, card.cost, stats)


def end_round(game):
    game.end_turn()
    game.end_turn()


def checked(observed, condition):
    assert condition, observed
    return observed


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    prior = QUALITY_BY_ID.get(card_id, {})
    previous_mechanics = MECHANISMS_BY_ID.get(card_id, [])
    mechanism_text = " | ".join(
        f"{row['mechanic']}={row['status']}:{row['reason']}" for row in previous_mechanics
    ) or "none"
    related = ISSUES_FOR_CARD.get(card_id, [])
    issue_text = " | ".join(
        f"{row['issue_id']}({row['severity']}):{row['summary']}" for row in related
    ) or "none"
    return (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or master.get('xml_source', '')}; "
        f"existing_tests={master.get('test_refs_candidate', '') or 'none'}; "
        f"prior_card={prior.get('status', 'unknown')}:{prior.get('reason', 'no prior reason')}; "
        f"prior_mechanics={mechanism_text}; related_issues={issue_text}"
    )


def record(card_id, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except AssertionError as exc:
        observed = str(exc)
        if not observed:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    PROBE_ROWS.append({
        "card_id": card_id, "case_id": case_id, "expected": expected,
        "observed": observed, "outcome": outcome,
        "notes": f"{notes}; {metadata(card_id)}",
    })
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    print(f"{card_id} {case_id}: {outcome} | {observed}", flush=True)
    return outcome


def finish_card(card_id):
    rows = [row for row in PROBE_ROWS if row["card_id"] == card_id]
    assert rows and len({row["case_id"] for row in rows}) == len(rows)
    errors = [row for row in rows if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in rows if row["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "Confirmed live mismatch: " + "; ".join(
            f"{row['case_id']} expected=[{row['expected']}] observed=[{row['observed']}]"
            for row in errors
        )
    elif unresolved:
        status = "YELLOW"
        reason = "Concrete unresolved probe blocker: " + "; ".join(
            f"{row['case_id']}={row['observed']}" for row in unresolved
        )
    else:
        status = "GREEN"
        reason = "All live cases passed: " + "; ".join(
            f"{row['case_id']} observed {row['observed']}" for row in rows
        )
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != card_id]
    VERDICT_ROWS.append({
        "card_id": card_id, "status": status,
        "mechanic_scope": QUALITY_BY_ID[card_id]["mechanic"],
        "reason": reason, "probe_file": PROBE_OUT.name,
        "notes": f"Cases={len(rows)}; probe rows include EN/ZH, source, test, and prior audit evidence.",
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"updated {card_id}: {status} ({len(rows)} cases)", flush=True)
    return status


def audit(card_id, tests):
    PROBE_ROWS[:] = [row for row in PROBE_ROWS if row["card_id"] != card_id]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != card_id]
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    for case_id, expected, func, notes in tests:
        record(card_id, case_id, expected, func, notes)
    return finish_card(card_id)


def c500_crystal_loss_and_deck_buff():
    cid = "TRL_500"

    def applies_to_deck_minions_only():
        g = new_game(CardClass.PRIEST, seed=5001)
        p = g.player1
        yeti = put_deck(p, "CS2_182")[0]
        wisp = put_deck(p, WISP)[0]
        spell = put_deck(p, FIREBALL)[0]
        before_mana = p.max_mana
        card = play(p, cid)
        observed = (f"mana={before_mana}->{p.max_mana};spell={card.zone.name};"
                    f"yeti={card_state(yeti)};wisp={card_state(wisp)};fireball={card_state(spell)};"
                    f"deck={ids(p.deck)};current_mana={p.mana}")
        return checked(observed, card.zone == Zone.GRAVEYARD and p.max_mana == 7
                       and (yeti.atk, yeti.health, yeti.zone) == (6, 7, Zone.DECK)
                       and (wisp.atk, wisp.health, wisp.zone) == (3, 3, Zone.DECK)
                       and spell.zone == Zone.DECK and spell.cost == 4)

    return audit(cid, [(
        "destroys_three_crystals_and_buffs_deck_minions",
        "Destroys 3 of 10 Mana Crystals, gives each deck minion +2/+2, and leaves a deck spell unchanged.",
        applies_to_deck_minions_only,
        "把Yeti、Wisp及火球术分别洗入牌库；施放后核对最大法力水晶、两种随从身材、法术费用和牌库区域。",
    )])


def c501_healing_turns_to_damage_then_expires():
    cid = "TRL_501"

    def healing_is_damage_only_this_turn():
        g = new_game(CardClass.PRIEST, seed=5011)
        p = g.player1
        p.hero.hit(5)
        phantasm = play(p, cid)
        first_spell = play(p, "TRL_128", target=p.hero)
        during = p.hero.health
        end_round(g)
        second_spell = play(p, "TRL_128", target=p.hero)
        observed = (f"phantasm={phantasm.zone.name};during={during};after_next_turn_heal={p.hero.health};"
                    f"spells={first_spell.zone.name}/{second_spell.zone.name};damage={p.hero.damage};armor={p.hero.armor}")
        return checked(observed, phantasm.zone == Zone.PLAY and during == 22
                       and p.hero.health == 25 and first_spell.zone == Zone.GRAVEYARD
                       and second_spell.zone == Zone.GRAVEYARD)

    return audit(cid, [(
        "healing_becomes_damage_until_turn_end",
        "Regenerate deals 3 damage to the Priest hero during Auchenai's turn; after that turn, Regenerate heals 3.",
        healing_is_damage_only_this_turn,
        "先让己方英雄缺5血，再由Phantasm本回合和下回合分别施放3点恢复，核对先掉血、过回合后恢复。",
    )])


def c502_spirit_of_dead_shuffles_cost_one_copy():
    cid = "TRL_502"

    def friendly_death_shuffles_copy_and_stealth_expires():
        g = new_game(CardClass.PRIEST, seed=5021)
        p, e = g.player1, g.player2
        spirit = play(p, cid)
        victim = summon(p, WISP)
        stealth_at_play = spirit.stealthed
        g.end_turn()
        moonfire = play(e, MOONFIRE, target=victim)
        g.end_turn()
        copies = [card for card in p.deck if card.id == WISP]
        observed = (f"spirit={spirit.zone.name}/stealth:{stealth_at_play}->{spirit.stealthed};"
                    f"victim={victim.zone.name};copy={[card_state(card) for card in copies]};"
                    f"moonfire={moonfire.zone.name};deck={ids(p.deck)}")
        return checked(observed, stealth_at_play and not spirit.stealthed
                       and victim.zone == Zone.GRAVEYARD and len(copies) == 1
                       and copies[0].zone == Zone.DECK and copies[0].cost == 1)

    return audit(cid, [(
        "friendly_death_shuffles_one_cost_copy_and_stealth_expires",
        "Spirit is Stealthed at entry, shuffles a 1-Cost Wisp copy after a friendly Wisp dies, and loses Stealth on its next turn.",
        friendly_death_shuffles_copy_and_stealth_expires,
        "用对手实际施放月火术击杀友方Wisp，检查牌库复制费用/区域，并跨到下一己方回合验证潜行结束。",
    )])


def c503_scarab_egg_summons_three_tokens():
    cid = "TRL_503"

    def death_summons_three_one_one_scarabs():
        g = new_game(seed=5031)
        p, e = g.player1, g.player2
        egg = summon(p, cid)
        g.end_turn()
        fireball = play(e, FIREBALL, target=egg)
        scarabs = [minion for minion in p.field if minion.id == "TRL_503t"]
        observed = f"egg={egg.zone.name};fireball={fireball.zone.name};scarabs={[(m.atk,m.health,m.zone.name) for m in scarabs]};field={ids(p.field)}"
        return checked(observed, egg.zone == Zone.GRAVEYARD and fireball.zone == Zone.GRAVEYARD
                       and len(scarabs) == 3 and all((m.atk,m.health,m.zone)==(1,1,Zone.PLAY) for m in scarabs))

    return audit(cid, [(
        "deathrattle_summons_three_scarabs",
        "When Scarab Egg dies, three 1/1 Scarabs are summoned to its controller's board.",
        death_summons_three_one_one_scarabs,
        "先召唤蛋，再让对手火球术真实击杀；逐一检查三只衍生随从的ID、身材和场上区域。",
    )])


def c504_bookie_gives_opponent_coin():
    cid = "TRL_504"

    def coin_enters_opponent_hand():
        g = new_game(seed=5041)
        p, e = g.player1, g.player2
        bookie = play(p, cid)
        observed = f"bookie={bookie.zone.name}/{bookie.atk}/{bookie.health};opponent_hand={[card_state(c) for c in e.hand]};own_hand={ids(p.hand)}"
        return checked(observed, bookie.zone == Zone.PLAY and len(e.hand) == 1
                       and e.hand[0].type == CardType.SPELL and e.hand[0].cost == 0
                       and not p.hand)

    return audit(cid, [(
        "battlecry_gives_opponent_coin",
        "Booty Bay Bookie's Battlecry adds one playable 0-Cost Coin to the opponent's hand.",
        coin_enters_opponent_hand,
        "实战打出随从后检查金币确实进入对手而非己方手牌，且费用为0并属于法术。",
    )])


def c505_hatchling_reduces_beast_cost_on_death():
    cid = "TRL_505"

    def deathrattle_discounts_beast_only():
        g = new_game(seed=5051)
        p, e = g.player1, g.player2
        beast = p.give("GIL_558")
        other = p.give("CS2_182")
        before_costs = (beast.cost, other.cost)
        hatchling = summon(p, cid)
        g.end_turn()
        fireball = play(e, FIREBALL, target=hatchling)
        observed = (f"hatchling={hatchling.zone.name};fireball={fireball.zone.name};"
                    f"beast={beast.id}/{beast.race}/{beast.zone.name}/{before_costs[0]}->{beast.cost};"
                    f"other={other.id}/{other.zone.name}/{before_costs[1]}->{other.cost}")
        return checked(observed, hatchling.zone == Zone.GRAVEYARD and fireball.zone == Zone.GRAVEYARD
                       and beast in p.hand and beast.cost == max(0, before_costs[0]-1)
                       and other in p.hand and other.cost == before_costs[1])

    return audit(cid, [(
        "deathrattle_reduces_beast_cost_one",
        "Helpless Hatchling's death reduces the held Beast's cost by exactly 1 without changing a held non-Beast.",
        deathrattle_discounts_beast_only,
        "手中准备Swamp Leech野兽和Yeti非野兽，对手火球术击杀Hatchling后检查二者费用及手牌区域。",
    )])


def c506_chicken_gains_attack_only_on_overkill():
    cid = "TRL_506"

    def scenario(overkill, seed):
        g = new_game(seed=seed)
        p, e = g.player1, g.player2
        chicken = play(p, cid)
        blessing = None
        shield = None
        if overkill:
            blessing = play(p, "CS2_087", target=chicken)
            shield = play(p, "CS2_004", target=chicken)
        target = summon(e, WISP)
        end_round(g)
        attack_error = None
        try:
            chicken.attack(target)
        except InvalidAction as exc:
            attack_error = type(exc).__name__
        observed = (f"overkill={overkill};blessing={None if blessing is None else blessing.zone.name};"
                    f"shield={None if shield is None else shield.zone.name};before={chicken.atk}/{chicken.health};"
                    f"attack_error={attack_error};chicken={chicken.zone.name}/{chicken.atk}/{chicken.health};"
                    f"target={target.zone.name}/{target.health}/{target.damage}")
        return checked(observed, attack_error is None and target.zone == Zone.GRAVEYARD
                       and chicken.zone == (Zone.PLAY if overkill else Zone.GRAVEYARD)
                       and chicken.atk == (9 if overkill else 1))

    return audit(cid, [
        ("overkill_adds_five_attack", "A 4-Attack Chicken overkills a 1-Health minion and gains +5 Attack while surviving its 1-Attack retaliation.", lambda: scenario(True, 5061), "用祝福之力+3攻和真言术：盾+2生命，把鸡变为4/3；跨回合击杀1血Wisp并核对超杀加攻。"),
        ("exact_lethal_does_not_add_attack", "A 1-Attack Chicken exactly kills a 1-Health minion, dies in combat, and gains no Overkill bonus.", lambda: scenario(False, 5062), "未加攻击时精确击杀1血Wisp，作为超杀边界对照。"),
    ])


def c507_hero_attack_summons_pirate():
    cid = "TRL_507"

    def hero_attack_not_minion_attack_triggers():
        g = new_game(seed=5071)
        p, e = g.player1, g.player2
        fan = play(p, cid)
        attacker = summon(p, WISP)
        enemy = summon(e, WISP)
        weapon = play(p, "CS2_091")
        end_round(g)
        attacker.attack(enemy)
        after_minion_attack = [m for m in p.field if m.id == "TRL_507t"]
        p.hero.attack(e.hero)
        pirates = [m for m in p.field if m.id == "TRL_507t"]
        observed = (f"fan={fan.zone.name};weapon={weapon.zone.name}/{weapon.durability};"
                    f"minion_attack={attacker.num_attacks}/{enemy.zone.name};after_minion={len(after_minion_attack)};"
                    f"hero_attack={p.hero.num_attacks};enemy_hero={e.hero.health};pirates={[(m.atk,m.health,m.zone.name) for m in pirates]}")
        return checked(observed, fan.zone == Zone.PLAY and enemy.zone == Zone.GRAVEYARD
                       and not after_minion_attack and p.hero.num_attacks == 1
                       and e.hero.health == 29 and len(pirates) == 1
                       and (pirates[0].atk,pirates[0].health,pirates[0].zone)==(1,1,Zone.PLAY))

    return audit(cid, [(
        "only_hero_attack_summons_pirate",
        "A friendly minion attack does not trigger Sharkfin Fan; the hero's weapon attack summons one 1/1 Pirate.",
        hero_attack_not_minion_attack_triggers,
        "同回合先用己方随从攻击Wisp，再用Light's Justice攻击对方英雄，分别检查海盗数量和1/1身材。",
    )])


def c508_thug_heals_at_owner_turn_start():
    cid = "TRL_508"

    def restores_two_after_enemy_turn_damage():
        g = new_game(seed=5081)
        p, e = g.player1, g.player2
        thug = summon(p, cid)
        g.end_turn()
        first = play(e, MOONFIRE, target=thug)
        second = play(e, MOONFIRE, target=thug)
        before_start = (thug.health, thug.damage)
        g.end_turn()
        observed = f"spells={first.zone.name}/{second.zone.name};before={before_start};after={thug.health}/{thug.damage};turn={g.current_player is p};zone={thug.zone.name}"
        return checked(observed, first.zone == Zone.GRAVEYARD and second.zone == Zone.GRAVEYARD
                       and before_start == (3,2) and thug.zone == Zone.PLAY
                       and thug.health == 5 and thug.damage == 0 and g.current_player is p)

    return audit(cid, [(
        "heals_two_at_start_of_owner_turn",
        "Regeneratin' Thug restores 2 Health at its controller's turn start after being damaged during the opponent's turn.",
        restores_two_after_enemy_turn_damage,
        "敌方回合连续对随从施放两次月火术，切回己方回合后核对当前生命与伤害值。",
    )])


def c509_banana_buffoon_adds_playable_bananas():
    cid = "TRL_509"

    def two_bananas_buff_same_minion():
        g = new_game(seed=5091)
        p = g.player1
        target = summon(p, WISP)
        buffoon = play(p, cid)
        bananas = [card for card in p.hand if card.id == "TRL_509t"]
        before = (target.atk, target.health)
        for banana in list(bananas):
            banana.play(target=target)
        observed = f"buffoon={buffoon.zone.name};before={before};after={target.atk}/{target.health};bananas={[c.zone.name for c in bananas]};hand={ids(p.hand)}"
        return checked(observed, buffoon.zone == Zone.PLAY and len(bananas) == 2
                       and all(c.zone == Zone.GRAVEYARD for c in bananas)
                       and (target.atk,target.health) == (3,3) and target.zone == Zone.PLAY)

    return audit(cid, [(
        "adds_two_bananas_that_each_give_plus_one_plus_one",
        "Battlecry adds two Bananas; playing both on a Wisp gives it +2/+2 total.",
        two_bananas_buff_same_minion,
        "场上准备Wisp，逐张打出Buffoon生成的两张香蕉并检查目标身材及香蕉离手区域。",
    )])


def c512_anklebiter_lifesteal_battlecry():
    cid = "TRL_512"

    def one_damage_to_enemy_hero_heals_controller():
        g = new_game(seed=5121)
        p, e = g.player1, g.player2
        p.hero.hit(5)
        before = p.hero.health
        minion = play(p, cid, target=e.hero)
        observed = f"hero={before}->{p.hero.health};enemy={e.hero.health};minion={minion.zone.name}/{minion.atk}/{minion.health}/lifesteal:{minion.lifesteal};spell_target={e.hero.id}"
        return checked(observed, before == 25 and p.hero.health == 26 and e.hero.health == 29
                       and minion.zone == Zone.PLAY and minion.lifesteal)

    return audit(cid, [(
        "battlecry_damage_heals_through_lifesteal",
        "Cheaty Anklebiter deals 1 to the enemy hero and Lifesteal restores 1 Health to its controller.",
        one_damage_to_enemy_hero_heals_controller,
        "让己方英雄缺5血，以英雄作为战吼目标造成1点并逐项核对敌我英雄生命、吸血关键词和随从区域。",
    )])


def c513_enforcer_taunt_and_shield_combat():
    cid = "TRL_513"

    def shield_absorbs_wisp_attack_and_taunt_remains():
        g = new_game(seed=5131)
        p, e = g.player1, g.player2
        enforcer = play(p, cid)
        attacker = summon(e, WISP)
        g.end_turn()
        before = (enforcer.atk, enforcer.health, enforcer.taunt, enforcer.divine_shield)
        error = None
        try:
            attacker.attack(enforcer)
        except InvalidAction as exc:
            error = type(exc).__name__
        observed = f"before={before};error={error};enforcer={enforcer.zone.name}/{enforcer.atk}/{enforcer.health}/damage:{enforcer.damage}/taunt:{enforcer.taunt}/shield:{enforcer.divine_shield};attacker={attacker.zone.name}/{attacker.damage}"
        return checked(observed, before == (2,14,True,True) and error is None
                       and enforcer.zone == Zone.PLAY and enforcer.damage == 0
                       and enforcer.taunt and not enforcer.divine_shield
                       and attacker.zone == Zone.GRAVEYARD)

    return audit(cid, [(
        "taunt_divine_shield_survive_combat",
        "Mosh'Ogg Enforcer has Taunt and Divine Shield; a 1-Attack Wisp removes the Shield without damaging the 2/14.",
        shield_absorbs_wisp_attack_and_taunt_remains,
        "实际召唤XML定义的2/14随从及敌方1/1 Wisp，跨回合战斗后检查嘲讽仍在、圣盾消失且本体无伤。",
    )])


def c514_belligerent_gnome_threshold():
    cid = "TRL_514"

    def scenario(enemy_count, seed):
        g = new_game(seed=seed)
        p, e = g.player1, g.player2
        enemies = [summon(e, WISP) for _ in range(enemy_count)]
        gnome = play(p, cid)
        observed = f"enemy_count={len(e.field)};enemies={[m.zone.name for m in enemies]};gnome={gnome.zone.name}/{gnome.atk}/{gnome.health}/taunt:{gnome.taunt}"
        return checked(observed, len(e.field) == enemy_count and gnome.zone == Zone.PLAY
                       and gnome.taunt and gnome.atk == (2 if enemy_count >= 2 else 1)
                       and gnome.health == 4)

    return audit(cid, [
        ("two_enemy_minions_grant_one_attack", "With two opposing minions, Belligerent Gnome is 2/4 with Taunt.", lambda: scenario(2, 5141), "对手场上恰有两个Wisp，检查战吼加攻及Taunt。"),
        ("one_enemy_minion_does_not_grant_attack", "With one opposing minion, Belligerent Gnome remains 1/4 with Taunt.", lambda: scenario(1, 5142), "对手只控制一个Wisp，检查条件阈值以下不加攻。"),
    ])


def c515_rabble_bouncer_cost_tracks_enemy_board():
    cid = "TRL_515"

    def scenario(enemy_count, seed):
        g = new_game(seed=seed)
        p, e = g.player1, g.player2
        enemies = [summon(e, WISP) for _ in range(enemy_count)]
        card = p.give(cid)
        expected_cost = max(0, 7-enemy_count)
        cost_before_play = card.cost
        observed = f"enemy_count={len(e.field)};enemy_ids={ids(enemies)};cost={cost_before_play};taunt:{card.taunt};mana={p.mana}"
        if enemy_count:
            card.play()
        return checked(observed, cost_before_play == expected_cost and card.taunt
                       and (card.zone == Zone.PLAY if enemy_count else card.zone == Zone.HAND))

    return audit(cid, [
        ("three_enemy_minions_reduce_cost_by_three", "Three enemy minions reduce Rabble Bouncer from 7 to 4 mana; it can be played with Taunt.", lambda: scenario(3, 5151), "对手三只Wisp，读手牌动态费用并实际打出后检查嘲讽。"),
        ("empty_enemy_board_keeps_base_cost", "With no enemy minions, Rabble Bouncer remains at its base 7-Cost and is not auto-played.", lambda: scenario(0, 5152), "空敌方场面核对未减费牌仍在手牌且保持7费。"),
    ])


def c516_offering_dies_and_grants_armor_at_own_turn_start():
    cid = "TRL_516"
    def scenario():
        game = new_game(seed=5161)
        p, e = game.player1, game.player2
        offering = summon(p, cid)
        before = p.hero.armor
        game.end_turn()
        game.end_turn()
        observed = f"offering={offering.zone.name};armor={before}->{p.hero.armor};current={game.current_player is p}"
        return checked(observed, offering.zone == Zone.GRAVEYARD and p.hero.armor == before + 8 and game.current_player is p)
    return audit(cid, [
        ("own_turn_start_destroys_offering_and_gains_eight_armor", "At the next start of its owner's turn, Gurubashi Offering is destroyed and grants exactly 8 Armor.", scenario, "召唤后实际经过双方回合切换，核对随从进入墓地且英雄获得8护甲。"),
    ])


def c517_fanatic_buffs_minions_not_spells_in_hand():
    cid = "TRL_517"
    def scenario():
        game = new_game(seed=5171)
        p = game.player1
        minion = p.give(WISP)
        other = p.give("CS2_182")
        spell = p.give(FIREBALL)
        before = (minion.atk, minion.health, other.atk, other.health, spell.cost)
        fanatic = play(p, cid)
        observed = f"before={before};wisp={minion.atk}/{minion.health}/{minion.zone.name};yeti={other.atk}/{other.health}/{other.zone.name};spell={spell.cost}/{spell.zone.name};fanatic={fanatic.zone.name}"
        return checked(observed, (minion.atk, minion.health) == (before[0] + 1, before[1] + 1)
                       and (other.atk, other.health) == (before[2] + 1, before[3] + 1)
                       and spell.cost == before[4] and spell.zone == Zone.HAND
                       and minion.zone == other.zone == Zone.HAND and fanatic.zone == Zone.PLAY)
    return audit(cid, [
        ("battlecry_buffs_every_hand_minion_only", "Arena Fanatic gives each minion in hand +1/+1 and leaves a spell unchanged.", scenario, "手牌放入Wisp、Yeti和火球术，打出战吼随从后逐张核对身材、费用和区域。"),
    ])


def c520_deathrattle_draws_two_murlocs_only():
    cid = "TRL_520"
    def scenario():
        game = new_game(seed=5201)
        p, e = game.player1, game.player2
        murlocs = [put_deck(p, "CS2_168")[0], put_deck(p, "EX1_506")[0]]
        non_murloc = put_deck(p, WISP)[0]
        tastyfin = summon(p, cid)
        game.end_turn()
        spell = e.give(FIREBALL)
        spell.play(target=tastyfin)
        drawn = [card for card in p.hand if card.id in {"CS2_168", "EX1_506"}]
        observed = f"tastyfin={tastyfin.zone.name};fireball={spell.zone.name};drawn={[(c.id, c.zone.name) for c in drawn]};nonmurloc={non_murloc.zone.name};deck={[c.id for c in p.deck]}"
        return checked(observed, tastyfin.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD
                       and sorted(ids(drawn)) == sorted(ids(murlocs))
                       and all(c.zone == Zone.HAND for c in drawn)
                       and non_murloc.zone == Zone.DECK and non_murloc in p.deck)
    return audit(cid, [
        ("deathrattle_draws_both_deck_murlocs_and_skips_nonmurloc", "When killed, Murloc Tastyfin draws both Murlocs from the deck while a non-Murloc remains in the deck.", scenario, "牌库放入两种鱼人和Wisp，让对手火球术实际击杀后检查抽到的ID与非鱼人仍在牌库。"),
    ])


def c521_patron_overkill_summons_copy_only_when_excess_damage():
    cid = "TRL_521"
    def scenario(overkill, seed):
        game = new_game(seed=seed)
        p, e = game.player1, game.player2
        patron = summon(p, cid)
        target = summon(e, WISP)
        if not overkill:
            # Make a 1/1 target have exactly three Health using an actual spell.
            game.end_turn()
            shield = e.give("CS2_004")
            shield.play(target=target)
            game.end_turn()
        else:
            game.end_turn()
            game.end_turn()
        err = None
        try:
            patron.attack(target)
        except Exception as exc:
            err = type(exc).__name__
        patrons = [m for m in p.field if m.id == cid]
        observed = f"overkill={overkill};error={err};target={target.zone.name}/damage:{target.damage if target.zone == Zone.PLAY else '-'};patron={patron.zone.name}/{patron.atk}/{patron.health};patrons={[(m.zone.name,m.atk,m.health) for m in patrons]}"
        expected_count = 2 if overkill else 1
        return checked(observed, err is None and target.zone == Zone.GRAVEYARD
                       and len(patrons) == expected_count
                       and (len(patrons) == 1 or any(m is not patron and (m.atk, m.health) == (3, 3) for m in patrons)))
    return audit(cid, [
        ("one_damage_overkill_summons_another_patron", "A 3/3 Arena Patron that kills a 1-Health Wisp summons one additional 3/3 Patron.", lambda: scenario(True, 5211), "己方奴隶主攻击敌方1血Wisp，超过其剩余生命并核对多出的一只3/3。"),
        ("exact_lethal_does_not_summon_patron", "An Arena Patron exactly kills a 3-Health Wisp and does not trigger Overkill.", lambda: scenario(False, 5212), "对手用真言术：盾把Wisp实际提高到3血；奴隶主恰好造成3伤，验证超杀边界。"),
    ])


def c522_wartbringer_requires_two_spells_for_damage():
    cid = "TRL_522"
    def scenario(powered, seed):
        game = new_game(CardClass.SHAMAN, seed=seed)
        p, e = game.player1, game.player2
        target = summon(e, "CS2_182")
        if powered:
            for _ in range(2):
                play(p, MOONFIRE, target=e.hero)
        card = p.give(cid)
        before = target.health
        if powered:
            card.play(target=target)
        else:
            card.play()
        observed = f"powered={powered};target={target.zone.name}/{target.health}/damage:{target.damage};wart={card.zone.name};played_spells={p.cards_played_this_turn}"
        return checked(observed, card.zone == Zone.PLAY and target.zone == Zone.PLAY
                       and target.health == (before - 2 if powered else before)
                       and target.damage == (2 if powered else 0))
    return audit(cid, [
        ("two_prior_spells_enable_targeted_two_damage", "After two spells in the turn, Wartbringer deals exactly 2 damage to the selected enemy minion.", lambda: scenario(True, 5221), "先实际施放两次月火术，再以敌方Yeti为目标打出战吼并检查其伤害。"),
        ("no_prior_spells_allows_no_target_and_deals_none", "With no spells played, Wartbringer can be played without a target and deals no damage.", lambda: scenario(False, 5222), "本回合未施法但敌方有随从，验证战吼不要求目标且不造成伤害。"),
    ])


def c523_witchdoctor_discovers_spell_only_with_dragon():
    cid = "TRL_523"
    def scenario(holding_dragon, seed):
        game = new_game(seed=seed)
        p = game.player1
        dragon = p.give("EX1_572") if holding_dragon else None
        witchdoctor = p.give(cid)
        witchdoctor.play()
        choice = p.choice
        if holding_dragon:
            options = list(choice.cards) if choice else []
            all_spells = bool(options) and all(card.type == CardType.SPELL for card in options)
            chosen = options[0] if options else None
            if chosen:
                choice.choose(chosen)
            observed = f"dragon={dragon.zone.name};options={[(c.id,str(c.type)) for c in options]};all_spells={all_spells};chosen={chosen.id if chosen else None};choice_after={bool(p.choice)};hand={[(c.id,c.zone.name) for c in p.hand]}"
            return checked(observed, len(options) == 3 and all_spells and chosen is not None
                           and not p.choice and chosen in p.hand and chosen.zone == Zone.HAND)
        observed = f"dragon=None;choice={choice};witchdoctor={witchdoctor.zone.name};hand={[c.id for c in p.hand]}"
        return checked(observed, choice is None and witchdoctor.zone == Zone.PLAY)
    return audit(cid, [
        ("holding_dragon_opens_three_spell_discover", "Holding a Dragon opens Discover with three spell options and the chosen spell enters hand.", lambda: scenario(True, 5231), "持有暮光幼龙，打出女巫博士，逐项检查三张选择都是法术并将选中牌加入手牌。"),
        ("no_dragon_skips_discover", "Without a Dragon in hand, the Battlecry creates no Discover choice.", lambda: scenario(False, 5232), "不持龙牌直接打出，验证没有发现界面/待选项。"),
    ])


def c524_shieldbreaker_requires_enemy_taunt_and_silences_it():
    cid = "TRL_524"
    def valid_target():
        game = new_game(seed=5241)
        p, e = game.player1, game.player2
        target = summon(e, "TRL_513")
        assert target.taunt and target.divine_shield
        card = p.give(cid)
        card.play(target=target)
        observed = f"target={target.zone.name};taunt={target.taunt};shield={target.divine_shield};silenced={target.silenced};card={card.zone.name}"
        return checked(observed, target.zone == Zone.PLAY and not target.taunt
                       and not target.divine_shield and target.silenced and card.zone == Zone.PLAY)
    def rejects_non_taunt():
        game = new_game(seed=5242)
        p, e = game.player1, game.player2
        target = summon(e, "CS2_182")
        card = p.give(cid)
        mana_before = p.mana
        error = None
        try:
            card.play(target=target)
        except InvalidAction as exc:
            error = type(exc).__name__
        observed = f"error={error};target={target.zone.name}/silenced:{target.silenced};card={card.zone.name};mana={mana_before}->{p.mana}"
        return checked(observed, error == "InvalidAction" and not target.silenced
                       and card.zone == Zone.HAND and p.mana == mana_before)
    return audit(cid, [
        ("valid_enemy_taunt_target_is_silenced", "Shieldbreaker removes Taunt and Divine Shield from a valid enemy Taunt minion.", valid_target, "以敌方具有嘲讽和圣盾的Mosh'Ogg Enforcer为目标，检查沉默及关键词移除。"),
        ("non_taunt_enemy_target_is_rejected_without_cost", "An enemy minion without Taunt is rejected before Shieldbreaker leaves hand or spends mana.", rejects_non_taunt, "尝试指定敌方无嘲讽Yeti，要求非法目标被拒且手牌、法力、目标状态不变。"),
    ])


def c525_treasure_chest_deathrattle_draws_two_cards():
    cid = "TRL_525"
    def scenario():
        game = new_game(seed=5251)
        p, e = game.player1, game.player2
        expected = [put_deck(p, WISP)[0], put_deck(p, "CS2_182")[0], put_deck(p, FIREBALL)[0]]
        chest = summon(p, cid)
        game.end_turn()
        removal = e.give(FIREBALL)
        removal.play(target=chest)
        drawn = [card for card in expected if card in p.hand]
        remaining = [card for card in expected if card in p.deck]
        observed = f"chest={chest.zone.name};removal={removal.zone.name};drawn={[(c.id,c.zone.name) for c in drawn]};remaining={[c.id for c in remaining]};deck={[c.id for c in p.deck]}"
        return checked(observed, chest.zone == Zone.GRAVEYARD and removal.zone == Zone.GRAVEYARD
                       and len(drawn) == 2 and len(remaining) == 1
                       and all(c.zone == Zone.HAND for c in drawn) and remaining[0].zone == Zone.DECK)
    return audit(cid, [
        ("deathrattle_draws_exactly_two_cards", "Arena Treasure Chest draws exactly two cards when killed; one of three deck cards remains.", scenario, "三张不同卡牌洗入牌库，让对手火球术实际击杀宝箱，核对两张进手牌、一张仍在牌库。"),
    ])


def c526_scorcher_damages_all_other_minions_not_itself():
    cid = "TRL_526"
    def scenario():
        game = new_game(seed=5261)
        p, e = game.player1, game.player2
        friendly = summon(p, "CS2_182")
        enemy = summon(e, "CS2_182")
        before = (friendly.health, enemy.health)
        scorcher = play(p, cid)
        observed = f"before={before};friendly={friendly.zone.name}/{friendly.health}/damage:{friendly.damage};enemy={enemy.zone.name}/{enemy.health}/damage:{enemy.damage};scorcher={scorcher.zone.name}/{scorcher.health}/damage:{scorcher.damage}"
        return checked(observed, friendly.zone == enemy.zone == scorcher.zone == Zone.PLAY
                       and friendly.damage == 1 and enemy.damage == 1
                       and friendly.health == before[0] - 1 and enemy.health == before[1] - 1
                       and scorcher.damage == 0)
    return audit(cid, [
        ("battlecry_hits_friendly_and_enemy_other_minions_only", "Dragonmaw Scorcher deals 1 damage to both players' other minions while remaining undamaged.", scenario, "双方各准备Yeti后打出Scorcher，检查友敌双方受到1伤、本体未受伤且仍在场。"),
    ])


def c527_trickster_gives_each_player_from_opponents_deck():
    cid = "TRL_527"
    def scenario():
        game = new_game(seed=5271)
        p, e = game.player1, game.player2
        own_deck = put_deck(p, FIREBALL)[0]
        enemy_deck = put_deck(e, WISP)[0]
        trickster = play(p, cid)
        own_copy = next((card for card in p.hand if card.id == WISP), None)
        enemy_copy = next((card for card in e.hand if card.id == FIREBALL), None)
        observed = f"own_deck={own_deck.zone.name};enemy_deck={enemy_deck.zone.name};own_hand={[(c.id,c.zone.name) for c in p.hand]};enemy_hand={[(c.id,c.zone.name) for c in e.hand]};trickster={trickster.zone.name}"
        return checked(observed, own_copy is not None and own_copy.zone == Zone.HAND
                       and enemy_copy is not None and enemy_copy.zone == Zone.HAND
                       and own_deck.zone == enemy_deck.zone == Zone.DECK
                       and trickster.zone == Zone.PLAY)
    return audit(cid, [
        ("both_players_receive_copy_from_opponents_deck", "Each player receives the distinct card from the opponent's deck, not from their own deck.", scenario, "己方牌库只放火球、对手牌库只放Wisp，打出后分别检查双方新获得的对方牌库卡牌副本。"),
    ])


def c528_linecracker_doubles_attack_only_on_overkill():
    cid = "TRL_528"
    def scenario(overkill, seed):
        game = new_game(seed=seed)
        p, e = game.player1, game.player2
        linecracker = summon(p, cid)
        target = summon(e, WISP if overkill else "CS2_182")
        game.end_turn()
        game.end_turn()
        before_atk = linecracker.atk
        error = None
        try:
            linecracker.attack(target)
        except Exception as exc:
            error = type(exc).__name__
        observed = f"overkill={overkill};error={error};before_atk={before_atk};linecracker={linecracker.zone.name}/{linecracker.atk}/{linecracker.health};target={target.zone.name}"
        return checked(observed, error is None and linecracker.zone == Zone.PLAY
                       and target.zone == Zone.GRAVEYARD
                       and linecracker.atk == (before_atk * 2 if overkill else before_atk))
    return audit(cid, [
        ("overkill_doubles_current_attack", "Linecracker overkills a 1-Health Wisp and doubles its Attack from 5 to 10.", lambda: scenario(True, 5281), "5攻Linecracker攻击1血Wisp，检查超杀后攻击变10且本体存活。"),
        ("exact_lethal_keeps_attack_unchanged", "Linecracker exactly kills a 5-Health Yeti and stays at 5 Attack.", lambda: scenario(False, 5282), "Linecracker恰好对5血Yeti造成5伤，检查未触发超杀、攻击仍为5。"),
    ])


def c530_contender_plays_secret_from_deck_if_secret_controlled():
    cid = "TRL_530"
    def scenario(control_secret, seed):
        game = new_game(CardClass.MAGE, seed=seed)
        p = game.player1
        active = play(p, "EX1_289") if control_secret else None
        deck_secret = put_deck(p, "EX1_294")[0]
        contender = play(p, cid)
        observed = f"active={active.zone.name if active else None};secrets={[(c.id,c.zone.name) for c in p.secrets]};deck_secret={deck_secret.zone.name};contender={contender.zone.name};mana={p.mana}"
        if control_secret:
            return checked(observed, active in p.secrets and deck_secret in p.secrets
                           and deck_secret.zone == Zone.SECRET and deck_secret not in p.deck
                           and contender.zone == Zone.PLAY)
        return checked(observed, deck_secret.zone == Zone.DECK and deck_secret in p.deck
                       and not p.secrets and contender.zone == Zone.PLAY)
    return audit(cid, [
        ("controlled_secret_plays_one_deck_secret", "With a Secret already controlled, Masked Contender plays a Secret from the deck.", lambda: scenario(True, 5301), "先实际施放奥秘，再打出Contender，核对另一张奥秘由牌库进入奥秘区。"),
        ("no_controlled_secret_keeps_deck_secret", "Without a controlled Secret, Masked Contender leaves the deck Secret untouched.", lambda: scenario(False, 5302), "不控制奥秘时打出Contender，核对牌库奥秘仍在牌库且未进入奥秘区。"),
    ])


def c531_shaker_deathrattle_summons_three_two_breaker():
    cid = "TRL_531"
    def scenario():
        game = new_game(seed=5311)
        p, e = game.player1, game.player2
        shaker = summon(p, cid)
        game.end_turn()
        removal = e.give(FIREBALL)
        removal.play(target=shaker)
        tokens = [m for m in p.field if m.id == "TRL_531t"]
        observed = f"shaker={shaker.zone.name};removal={removal.zone.name};tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]};field={ids(p.field)}"
        return checked(observed, shaker.zone == Zone.GRAVEYARD and removal.zone == Zone.GRAVEYARD
                       and len(tokens) == 1 and (tokens[0].atk, tokens[0].health, tokens[0].zone) == (3, 2, Zone.PLAY))
    return audit(cid, [
        ("deathrattle_summons_one_three_two_breaker", "Rumbletusk Shaker's actual death summons one 3/2 Rumbletusk Breaker for its controller.", scenario, "对手火球术实际击杀Shaker，核对己方场上出现一只3/2指定token。"),
    ])


def c532_announcer_randomly_redirects_about_half_of_attacks():
    cid = "TRL_532"
    def scenario():
        outcomes = []
        for seed in range(5320, 5340):
            game = new_game(seed=seed)
            p, e = game.player1, game.player2
            announcer = summon(p, cid)
            alternate = summon(p, WISP)
            attacker = summon(e, "CS2_182")
            end_round(game)
            game.end_turn()
            assert game.current_player is e
            before_hero = p.hero.health
            before_alternate = (alternate.zone, alternate.health)
            error = None
            try:
                attacker.attack(announcer)
            except Exception as exc:
                error = type(exc).__name__
            redirected = announcer.damage == 0
            if redirected:
                assert error is None and (p.hero.health < before_hero or alternate.zone != before_alternate[0] or alternate.health < before_alternate[1])
            else:
                assert error is None and announcer.damage == attacker.atk and p.hero.health == before_hero
            outcomes.append((seed, "redirect" if redirected else "announcer", error,
                             p.hero.health - before_hero, alternate.zone.name,
                             announcer.damage))
        redirected_count = sum(item[1] == "redirect" for item in outcomes)
        normal_count = len(outcomes) - redirected_count
        observed = f"games={outcomes};redirected={redirected_count};announcer_hit={normal_count}"
        return checked(observed, redirected_count > 0 and normal_count > 0)
    return audit(cid, [
        ("seeded_attacks_include_redirect_and_normal_outcomes", "Across fixed actual combat seeds, some attacks are redirected to another friendly character and some hit the Announcer.", scenario, "固定20个种子各创建真实对战并让对手Yeti攻击Announcer；核对两类随机结果及每次实际受击者。"),
    ])


def c533_peddler_gains_armor_only_with_frozen_friendly_minion():
    cid = "TRL_533"
    def scenario(freeze_first, seed):
        game = new_game(CardClass.MAGE, seed=seed)
        p, e = game.player1, game.player2
        target = summon(p, "CS2_182")
        if freeze_first:
            game.end_turn()
            frostbolt = e.give("CS2_024")
            frostbolt.play(target=target)
            game.end_turn()
        before = p.hero.armor
        peddler = play(p, cid)
        observed = f"frozen_case={freeze_first};target={target.zone.name}/frozen:{target.frozen};armor={before}->{p.hero.armor};peddler={peddler.zone.name}"
        return checked(observed, peddler.zone == Zone.PLAY
                       and target.frozen == freeze_first
                       and p.hero.armor == (before + 8 if freeze_first else before))
    return audit(cid, [
        ("frozen_friendly_minion_grants_eight_armor", "When a friendly minion is frozen by the opponent, Ice Cream Peddler gains 8 Armor.", lambda: scenario(True, 5331), "对手真实施放寒冰箭冻结己方Yeti后，打出Peddler并检查护甲增加8。"),
        ("no_frozen_friendly_minion_grants_no_armor", "Without a frozen friendly minion, Ice Cream Peddler grants no Armor.", lambda: scenario(False, 5332), "己方有未冻结Yeti时打出Peddler，检查护甲不变。"),
    ])


def c535_shellfighter_redirects_damage_from_adjacent_minions():
    cid = "TRL_535"
    def scenario():
        game = new_game(seed=5351)
        p, e = game.player1, game.player2
        left = summon(p, WISP)
        shell = summon(p, cid)
        right = summon(p, WISP)
        far = summon(p, "CS2_182")
        game.end_turn()
        spells = []
        for target in (left, right, far):
            spell = e.give(MOONFIRE)
            spell.play(target=target)
            spells.append(spell)
        observed = f"left={left.zone.name}/damage:{left.damage};shell={shell.zone.name}/damage:{shell.damage}/health:{shell.health};right={right.zone.name}/damage:{right.damage};far={far.zone.name}/damage:{far.damage};spells={[s.zone.name for s in spells]}"
        return checked(observed, left.zone == right.zone == shell.zone == far.zone == Zone.PLAY
                       and left.damage == right.damage == 0 and shell.damage == 2
                       and far.damage == 1 and all(spell.zone == Zone.GRAVEYARD for spell in spells))
    return audit(cid, [
        ("adjacent_damage_is_redirected_but_far_damage_is_not", "Damage aimed at both adjacent friendly minions is redirected to Shellfighter; a far minion takes damage normally.", scenario, "将左邻Wisp、Shellfighter、右邻Wisp及远侧Yeti排成一列；对手逐个施放月火术并检查伤害转移边界。"),
    ])


def c537_undatakah_copies_three_friendly_dead_deathrattles():
    cid = "TRL_537"
    def scenario():
        game = new_game(seed=5371)
        p, e = game.player1, game.player2
        beast = p.give("EX1_543")
        hatchlings = [summon(p, "TRL_505") for _ in range(3)]
        game.end_turn()
        removals = []
        for hatchling in hatchlings:
            removal = e.give(MOONFIRE)
            removal.play(target=hatchling)
            removals.append(removal)
        cost_after_original_deathrattles = beast.cost
        game.end_turn()
        undatakah = play(p, cid)
        has_dr = undatakah.has_deathrattle
        game.end_turn()
        kill = e.give(FIREBALL)
        kill.play(target=undatakah)
        observed = f"hatchlings={[m.zone.name for m in hatchlings]};removals={[m.zone.name for m in removals]};beast_cost=9->{cost_after_original_deathrattles}->{beast.cost};undatakah={undatakah.zone.name};has_deathrattle={has_dr};kill={kill.zone.name}"
        return checked(observed, all(m.zone == Zone.GRAVEYARD for m in hatchlings)
                       and beast.zone == Zone.HAND and cost_after_original_deathrattles == 6
                       and undatakah.zone == Zone.GRAVEYARD and has_dr
                       and beast.cost == 3 and kill.zone == Zone.GRAVEYARD)
    return audit(cid, [
        ("battlecry_copies_three_deathrattles_and_all_trigger_on_death", "After three friendly Hatchlings die, Da Undatakah gains three copied Deathrattles; its death reduces a held Beast by three more.", scenario, "让三只Helpless Hatchling被对手月火术真实击杀，King Krush从9费降至6费；打出Da后被火球术击杀，复制亡语再降至3费。"),
    ])


def c542_ondasta_rush_overkill_summons_hand_beast():
    cid = "TRL_542"
    def scenario(overkill, seed):
        game = new_game(CardClass.HUNTER, seed=seed)
        p, e = game.player1, game.player2
        beast = p.give("GIL_558")
        target = summon(e, WISP)
        ondasta = play(p, cid)
        if not overkill:
            # Raise the target to exactly 7 Health with real opposing spells while keeping it at 1 Attack.
            game.end_turn()
            shields = []
            for _ in range(3):
                shield = e.give("CS2_004")
                shield.play(target=target)
                shields.append(shield)
            game.end_turn()
        before_target_health = target.health
        error = None
        try:
            ondasta.attack(target)
        except Exception as exc:
            error = type(exc).__name__
        observed = f"overkill={overkill};target_before={before_target_health};error={error};target={target.zone.name};ondasta={ondasta.zone.name}/{ondasta.atk}/{ondasta.health};beast={beast.zone.name}/{beast.atk}/{beast.health};field={[(m.id,m.zone.name,m.atk,m.health) for m in p.field]}"
        expected_beast_zone = Zone.PLAY if overkill else Zone.HAND
        return checked(observed, error is None and target.zone == Zone.GRAVEYARD
                       and ondasta.zone == Zone.PLAY and beast.zone == expected_beast_zone
                       and (not overkill or beast in p.field))
    return audit(cid, [
        ("rush_overkill_summons_only_beast_from_hand", "Oondasta uses Rush to overkill a Wisp and summons the only Beast from hand.", lambda: scenario(True, 5421), "打出Oondasta后立即攻击敌方Wisp，核对超杀召唤手牌中唯一的野兽。"),
        ("exact_lethal_does_not_summon_beast", "Oondasta exactly kills a 7-Health minion, so the hand Beast remains in hand.", lambda: scenario(False, 5422), "以Yeti/7血Gurubashi作边界目标，恰好造成7伤，核对野兽没有被召唤。"),
    ])


def c543_bloodclaw_equips_weapon_and_deals_five_to_hero():
    cid = "TRL_543"
    def scenario():
        game = new_game(CardClass.PALADIN, seed=5431)
        p = game.player1
        before = p.hero.health
        bloodclaw = play(p, cid)
        weapon = p.hero.weapon
        observed = f"hero={before}->{p.hero.health}/damage:{p.hero.damage};card={bloodclaw.zone.name};weapon={weapon.id if weapon else None}/{weapon.atk if weapon else None}/{weapon.durability if weapon else None}/{weapon.zone.name if weapon else None};mana={p.mana}"
        return checked(observed, p.hero.health == before - 5 and bloodclaw.zone == Zone.PLAY
                       and weapon is bloodclaw and weapon.atk == 2 and weapon.durability == 2)
    return audit(cid, [
        ("battlecry_damages_hero_and_equips_two_two_weapon", "Bloodclaw deals exactly 5 damage to its controller's hero and equips a 2/2 weapon.", scenario, "实战打出Bloodclaw后核对己方英雄掉5血、卡牌成为2攻2耐久武器。"),
    ])


def c545_templar_threshold_requires_ten_health_restored():
    cid = "TRL_545"
    def scenario(restores, seed):
        game = new_game(CardClass.PALADIN, seed=seed)
        p = game.player1
        p.hero.hit(10)
        spells = []
        for _ in range(restores):
            spell = p.give("TRL_128")
            spell.play(target=p.hero)
            spells.append(spell)
        templar = play(p, cid)
        observed = f"restore_casts={restores};hero_health={p.hero.health};hero_damage={p.hero.damage};spells={[s.zone.name for s in spells]};templar={templar.zone.name}/{templar.atk}/{templar.health}/taunt:{templar.taunt};powered={templar.powered_up}"
        expected = (8, 8, True) if restores == 4 else (4, 4, False)
        # powered_up tracks the 10-Health threshold, which gates the +4/+4 and Taunt gain.
        return checked(observed, (templar.atk, templar.health, templar.powered_up) == expected
                       and all(spell.zone == Zone.GRAVEYARD for spell in spells)
                       and p.hero.health == min(30, 20 + 3 * restores)
                       and templar.taunt == (restores == 4))
    return audit(cid, [
        ("restoring_ten_health_grants_four_four_and_taunt", "After actually restoring 10 Health this game, Templar becomes 8/8 and its threshold is powered.", lambda: scenario(4, 5451), "英雄先实际受10伤，再以四次Regenerate最多恢复10点，检查模板达到阈值后的身材与powered_up。"),
        ("restoring_nine_health_stays_base_body", "Restoring only 9 Health does not activate the Battlecry; Templar remains 4/4.", lambda: scenario(3, 5452), "英雄受10伤后只施放三次Regenerate，累计恢复9点，检查未达阈值。"),
    ])


def c546_tortoise_battlecry_damages_hero_five():
    cid = "TRL_546"
    def scenario():
        game = new_game(seed=5461)
        p = game.player1
        before = p.hero.health
        tortoise = play(p, cid)
        observed = f"hero={before}->{p.hero.health}/damage:{p.hero.damage};tortoise={tortoise.zone.name}/{tortoise.atk}/{tortoise.health};taunt={tortoise.taunt}"
        return checked(observed, p.hero.health == before - 5 and tortoise.zone == Zone.PLAY
                       and (tortoise.atk, tortoise.health) == (3, 5))
    return audit(cid, [
        ("battlecry_damages_hero_five_and_leaves_three_five", "Ornery Tortoise deals 5 to its controller's hero and remains a 3/5 minion.", scenario, "实际打出海龟，检查己方英雄受5伤且随从仍为3/5并在场。"),
    ])


def c550_war_bear_has_rush_taunt_and_cannot_attack_hero_immediately():
    cid = "TRL_550"
    def attacks_minion():
        game = new_game(CardClass.HUNTER, seed=5501)
        p, e = game.player1, game.player2
        target = summon(e, WISP)
        bear = play(p, cid)
        error = None
        try:
            bear.attack(target)
        except Exception as exc:
            error = type(exc).__name__
        observed = f"error={error};target={target.zone.name};bear={bear.zone.name}/{bear.atk}/{bear.health}/taunt:{bear.taunt}/rush:{bear.rush};enemy_hero={e.hero.health}"
        return checked(observed, error is None and target.zone == Zone.GRAVEYARD
                       and bear.zone == Zone.PLAY and bear.taunt and bear.atk == 5
                       and e.hero.health == 30)
    def rejects_hero_attack():
        game = new_game(CardClass.HUNTER, seed=5502)
        p, e = game.player1, game.player2
        bear = play(p, cid)
        before = e.hero.health
        error = None
        try:
            bear.attack(e.hero)
        except InvalidAction as exc:
            error = type(exc).__name__
        observed = f"error={error};bear={bear.zone.name}/{bear.atk}/{bear.health}/rush:{bear.rush};enemy_hero={before}->{e.hero.health}"
        return checked(observed, error == "InvalidAction" and bear.zone == Zone.PLAY
                       and e.hero.health == before)
    return audit(cid, [
        ("rush_allows_immediate_minion_attack_with_taunt", "Amani War Bear can immediately attack an enemy minion and retains Taunt.", attacks_minion, "同回合攻击敌方Wisp，验证Rush能打随从，之后本体存活并保留Taunt。"),
        ("rush_cannot_attack_enemy_hero_on_entry_turn", "Rush does not allow Amani War Bear to attack the enemy hero on the turn it is played.", rejects_hero_attack, "打出当回合直接尝试攻击敌方英雄，要求动作被拒且英雄不掉血。"),
    ])


def c551_diretroll_discards_lowest_cost_hand_card():
    cid = "TRL_551"
    def scenario():
        game = new_game(CardClass.WARLOCK, seed=5511)
        p = game.player1
        lowest = p.give(WISP)
        higher_minion = p.give("CS2_182")
        higher_spell = p.give(FIREBALL)
        troll = play(p, cid)
        observed = f"discarded={lowest.zone.name};hand={[(c.id,c.cost,c.zone.name) for c in p.hand]};troll={troll.zone.name}/{troll.taunt}/{troll.atk}/{troll.health}"
        return checked(observed, lowest not in p.hand and lowest.zone == Zone.REMOVEDFROMGAME
                       and higher_minion in p.hand and higher_spell in p.hand
                       and troll.zone == Zone.PLAY and troll.taunt)
    return audit(cid, [
        ("battlecry_discards_only_the_lowest_cost_card", "Reckless Diretroll discards the 0-Cost Wisp while retaining the higher-Cost minion and spell.", scenario, "手牌放入0费Wisp、4费Yeti和4费火球，实战打出后检查被弃牌与保留卡。"),
    ])


def c555_demonbolt_cost_falls_per_friendly_minion_and_destroys_target():
    cid = "TRL_555"
    def scenario(friend_count, seed):
        game = new_game(CardClass.WARLOCK, seed=seed)
        p, e = game.player1, game.player2
        friends = [summon(p, WISP) for _ in range(friend_count)]
        target = summon(e, "CS2_182")
        spell = p.give(cid)
        cost = spell.cost
        spell.play(target=target)
        observed = f"friend_count={friend_count};friends={[m.zone.name for m in friends]};cost={cost};target={target.zone.name};spell={spell.zone.name};mana={p.mana}"
        return checked(observed, cost == 8 - friend_count and target.zone == Zone.GRAVEYARD
                       and spell.zone == Zone.GRAVEYARD and all(m.zone == Zone.PLAY for m in friends))
    return audit(cid, [
        ("two_friendly_minions_reduce_cost_to_six_and_destroy", "With two friendly minions, Demonbolt costs 6 and destroys the selected enemy minion.", lambda: scenario(2, 5551), "控制两只Wisp后检查动态费用从8降到6，并指定敌方Yeti实际消灭。"),
        ("empty_board_keeps_eight_cost_and_destroys", "With no friendly minions, Demonbolt remains 8-Cost and still destroys its target.", lambda: scenario(0, 5552), "己方空场作为费用对照，验证法术仍可用8费消灭敌方Yeti。"),
    ])


def c564_zihi_sets_both_max_mana_to_five():
    cid = "TRL_564"
    def scenario():
        game = new_game(seed=5641)
        p, e = game.player1, game.player2
        before = (p.max_mana, e.max_mana)
        zihi = play(p, cid)
        observed = f"before={before};after=({p.max_mana},{e.max_mana});p_mana={p.mana};e_mana={e.mana};zihi={zihi.zone.name}/{zihi.cost}"
        return checked(observed, before == (10, 10) and (p.max_mana, e.max_mana) == (5, 5)
                       and p.mana == 10 - zihi.cost and e.mana == 5 and zihi.zone == Zone.PLAY)
    return audit(cid, [
        ("battlecry_sets_each_player_to_five_crystals", "Mojomaster Zihi sets both players' maximum Mana Crystals and current available Mana to 5, subject to the caster's spent cost.", scenario, "双方原有10个水晶时打出Zihi，核对双方最大水晶变5及各自可用法力。"),
    ])


def c566_revenge_summons_friendly_beast_that_died_this_turn():
    cid = "TRL_566"
    def positive():
        game = new_game(CardClass.HUNTER, seed=5661)
        p = game.player1
        beast = summon(p, "GIL_558")
        murder = play(p, MOONFIRE, target=beast)
        spell = p.give(cid)
        spell.play()
        copies = [m for m in p.field if m.id == "GIL_558"]
        observed = f"original={beast.zone.name};moonfire={murder.zone.name};revenge={spell.zone.name};copies={[(m.id,m.atk,m.health,m.zone.name) for m in copies]};hand={[m.id for m in p.hand]}"
        return checked(observed, beast.zone == Zone.GRAVEYARD and murder.zone == Zone.GRAVEYARD
                       and spell.zone == Zone.GRAVEYARD and len(copies) == 1
                       and copies[0] is not beast and copies[0].zone == Zone.PLAY)
    def no_dead_beast():
        game = new_game(CardClass.HUNTER, seed=5662)
        p = game.player1
        spell = p.give(cid)
        mana_before = p.mana
        error = None
        try:
            spell.play()
        except InvalidAction as exc:
            error = type(exc).__name__
        observed = f"error={error};spell={spell.zone.name};field={ids(p.field)};mana={mana_before}->{p.mana}"
        return checked(observed, error == "InvalidAction" and spell.zone == Zone.HAND
                       and not p.field and p.mana == mana_before)
    return audit(cid, [
        ("summons_beast_killed_during_current_turn", "After a friendly Beast dies during this turn, Revenge of the Wild summons its copy.", positive, "本回合先用月火术实际杀死己方野兽，再施放复仇之野性并检查新召唤物。"),
        ("no_beast_death_rejects_spell_without_cost", "With no friendly Beast death this turn, the spell is rejected without spending mana.", no_dead_beast, "本回合无野兽死亡时尝试施放，要求规则拒绝且法力、手牌不变。"),
    ])


def c569_crowd_roaster_requires_dragon_to_deal_seven():
    cid = "TRL_569"
    def scenario(holding_dragon, seed):
        game = new_game(seed=seed)
        p, e = game.player1, game.player2
        dragon = p.give("EX1_572") if holding_dragon else None
        target = summon(e, "CS2_182")
        roaster = p.give(cid)
        roaster.play(target=target)
        observed = f"dragon={dragon.zone.name if dragon else None};target={target.zone.name}/damage:{target.damage if target.zone == Zone.PLAY else '-'};roaster={roaster.zone.name};hand={[c.id for c in p.hand]}"
        return checked(observed, roaster.zone == Zone.PLAY
                       and target.zone == (Zone.GRAVEYARD if holding_dragon else Zone.PLAY)
                       and (holding_dragon or target.damage == 0))
    return audit(cid, [
        ("dragon_in_hand_enables_seven_damage", "Holding a Dragon makes Crowd Roaster deal 7 damage to and kill the enemy Yeti.", lambda: scenario(True, 5691), "持有暮光幼龙时指定敌方Yeti，核对7伤足以消灭目标。"),
        ("no_dragon_means_no_battlecry_damage", "Without a Dragon in hand, Crowd Roaster's Battlecry deals no damage to the selected enemy minion.", lambda: scenario(False, 5692), "没有龙牌时仍有敌方目标，核对战吼不造成伤害。"),
    ])


def c570_soup_vendor_draws_only_for_three_plus_hero_heal():
    cid = "TRL_570"
    def scenario(heal_amount, seed):
        game = new_game(CardClass.PRIEST, seed=seed)
        p = game.player1
        p.hero.hit(5)
        vendor = summon(p, cid)
        deck_card = put_deck(p, WISP)[0]
        if heal_amount == 3:
            heal = p.give("TRL_128")
            heal.play(target=p.hero)
        else:
            heal = p.hero.power
            heal.use(target=p.hero)
        observed = f"heal={heal_amount};hero={p.hero.health}/damage:{p.hero.damage};vendor={vendor.zone.name};hand={[c.id for c in p.hand]};deck={[c.id for c in p.deck]};heal_card={getattr(heal,'id','HERO_POWER')}/{getattr(heal,'zone',None)}"
        if heal_amount == 3:
            return checked(observed, deck_card in p.hand and deck_card.zone == Zone.HAND
                           and deck_card not in p.deck and deck_card.zone != Zone.DECK)
        return checked(observed, deck_card in p.deck and deck_card.zone == Zone.DECK
                       and deck_card not in p.hand and vendor.zone == Zone.PLAY)
    return audit(cid, [
        ("healing_hero_three_draws_one_card", "Restoring 3 Health to the hero causes Soup Vendor to draw one card.", lambda: scenario(3, 5701), "英雄受5伤后用Regenerate实际恢复3点，检查牌库顶卡进入手牌。"),
        ("healing_hero_two_does_not_draw", "Restoring only 2 Health to the hero causes no draw.", lambda: scenario(2, 5702), "牧师英雄技能实际恢复2点，检查牌库卡仍留在牌库。"),
    ])


def c900_halazzi_fills_hand_with_one_one_rush_lynxes():
    cid = "TRL_900"
    def scenario(initial_minions, seed):
        game = new_game(CardClass.HUNTER, seed=seed)
        p = game.player1
        starting = [p.give(WISP) for _ in range(initial_minions)]
        halazzi = play(p, cid)
        tokens = [card for card in p.hand if card.id == "TRL_348t"]
        observed = f"initial_hand={initial_minions+1};starting={[c.zone.name for c in starting]};halazzi={halazzi.zone.name};hand_count={len(p.hand)};tokens={[(c.id,c.atk,c.health,c.rush,c.zone.name) for c in tokens]}"
        expected_tokens = min(4, 10 - initial_minions)
        return checked(observed, len(p.hand) == 10 and len(tokens) == expected_tokens
                       and all((c.atk,c.health,c.rush,c.zone) == (1,1,True,Zone.HAND) for c in tokens))
    return audit(cid, [
        ("fills_hand_to_ten_with_one_one_rush_lynxes", "Halazzi fills a partially empty hand to 10 with 1/1 Rush Lynxes.", lambda: scenario(6, 9001), "打出前手牌有Halazzi和六张Wisp，战吼应补入四只Lynx至10张。"),
        ("near_full_hand_adds_only_available_slots", "With nine cards before playing Halazzi, exactly two Lynxes fill the hand to 10.", lambda: scenario(8, 9002), "打出前手牌有Halazzi和八张Wisp，只剩两个空位，检查不溢出且补两只。"),
    ])


def c901_spirit_of_lynx_stealth_and_beast_summon_buff():
    cid = "TRL_901"
    def scenario():
        game = new_game(CardClass.HUNTER, seed=9011)
        p = game.player1
        spirit = play(p, cid)
        beast = p.give("GIL_558")
        base_stats = (beast.atk, beast.health)
        beast.play()
        non_beast = play(p, WISP)
        stealth_on_entry = spirit.tags[GameTag.STEALTH]
        end_round(game)
        stealth_after_turn = spirit.tags[GameTag.STEALTH]
        observed = f"spirit={spirit.zone.name};stealth={stealth_on_entry}->{stealth_after_turn};beast={beast.id}/{base_stats}->{beast.atk}/{beast.health}/{beast.zone.name};nonbeast={non_beast.id}/{non_beast.atk}/{non_beast.health}/{non_beast.zone.name}"
        return checked(observed, spirit.zone == Zone.PLAY and stealth_on_entry and not stealth_after_turn
                       and (base_stats, (beast.atk, beast.health)) == ((2, 1), (3, 2))
                       and (non_beast.atk, non_beast.health) == (1, 1))
    return audit(cid, [
        ("stealth_expires_after_own_turn_and_summoned_beast_gets_plus_one_plus_one", "Spirit of the Lynx starts Stealthed, grants +1/+1 to a subsequently summoned Beast, leaves a non-Beast unchanged, and loses Stealth next turn.", scenario, "打出Spirit后实际打出野兽与Wisp，检查野兽+1/+1、非野兽不变，并跨回合核对潜行消失。"),
    ])


AUDITS = [
    c500_crystal_loss_and_deck_buff,
    c501_healing_turns_to_damage_then_expires,
    c502_spirit_of_dead_shuffles_cost_one_copy,
    c503_scarab_egg_summons_three_tokens,
    c504_bookie_gives_opponent_coin,
    c505_hatchling_reduces_beast_cost_on_death,
    c506_chicken_gains_attack_only_on_overkill,
    c507_hero_attack_summons_pirate,
    c508_thug_heals_at_owner_turn_start,
    c509_banana_buffoon_adds_playable_bananas,
    c512_anklebiter_lifesteal_battlecry,
    c513_enforcer_taunt_and_shield_combat,
    c514_belligerent_gnome_threshold,
    c515_rabble_bouncer_cost_tracks_enemy_board,
    c516_offering_dies_and_grants_armor_at_own_turn_start,
    c517_fanatic_buffs_minions_not_spells_in_hand,
    c520_deathrattle_draws_two_murlocs_only,
    c521_patron_overkill_summons_copy_only_when_excess_damage,
    c522_wartbringer_requires_two_spells_for_damage,
    c523_witchdoctor_discovers_spell_only_with_dragon,
    c524_shieldbreaker_requires_enemy_taunt_and_silences_it,
    c525_treasure_chest_deathrattle_draws_two_cards,
    c526_scorcher_damages_all_other_minions_not_itself,
    c527_trickster_gives_each_player_from_opponents_deck,
    c528_linecracker_doubles_attack_only_on_overkill,
    c530_contender_plays_secret_from_deck_if_secret_controlled,
    c531_shaker_deathrattle_summons_three_two_breaker,
    c532_announcer_randomly_redirects_about_half_of_attacks,
    c533_peddler_gains_armor_only_with_frozen_friendly_minion,
    c535_shellfighter_redirects_damage_from_adjacent_minions,
    c537_undatakah_copies_three_friendly_dead_deathrattles,
    c542_ondasta_rush_overkill_summons_hand_beast,
    c543_bloodclaw_equips_weapon_and_deals_five_to_hero,
    c545_templar_threshold_requires_ten_health_restored,
    c546_tortoise_battlecry_damages_hero_five,
    c550_war_bear_has_rush_taunt_and_cannot_attack_hero_immediately,
    c551_diretroll_discards_lowest_cost_hand_card,
    c555_demonbolt_cost_falls_per_friendly_minion_and_destroys_target,
    c564_zihi_sets_both_max_mana_to_five,
    c566_revenge_summons_friendly_beast_that_died_this_turn,
    c569_crowd_roaster_requires_dragon_to_deal_seven,
    c570_soup_vendor_draws_only_for_three_plus_hero_heal,
    c900_halazzi_fills_hand_with_one_one_rush_lynxes,
    c901_spirit_of_lynx_stealth_and_beast_summon_buff,
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="zero-based frozen-roster index")
    parser.add_argument("--limit", type=int, default=44, help="number of cards to run")
    args = parser.parse_args()
    assert 0 <= args.start < 44 and 1 <= args.limit <= 44
    selected = AUDITS[args.start:args.start + args.limit]
    statuses = []
    for expected_id, audit_fn in zip(OWN_IDS[args.start:args.start + args.limit], selected):
        assert expected_id == audit_fn.card_id
        statuses.append(audit_fn())
    from collections import Counter
    print(f"audited={len(statuses)} statuses={dict(Counter(statuses))}; roster={OWN_IDS[args.start:args.start + len(statuses)]}")


c500_crystal_loss_and_deck_buff.card_id = "TRL_500"
c501_healing_turns_to_damage_then_expires.card_id = "TRL_501"
c502_spirit_of_dead_shuffles_cost_one_copy.card_id = "TRL_502"
c503_scarab_egg_summons_three_tokens.card_id = "TRL_503"
c504_bookie_gives_opponent_coin.card_id = "TRL_504"
c505_hatchling_reduces_beast_cost_on_death.card_id = "TRL_505"
c506_chicken_gains_attack_only_on_overkill.card_id = "TRL_506"
c507_hero_attack_summons_pirate.card_id = "TRL_507"
c508_thug_heals_at_owner_turn_start.card_id = "TRL_508"
c509_banana_buffoon_adds_playable_bananas.card_id = "TRL_509"
c512_anklebiter_lifesteal_battlecry.card_id = "TRL_512"
c513_enforcer_taunt_and_shield_combat.card_id = "TRL_513"
c514_belligerent_gnome_threshold.card_id = "TRL_514"
c515_rabble_bouncer_cost_tracks_enemy_board.card_id = "TRL_515"
c516_offering_dies_and_grants_armor_at_own_turn_start.card_id = "TRL_516"
c517_fanatic_buffs_minions_not_spells_in_hand.card_id = "TRL_517"
c520_deathrattle_draws_two_murlocs_only.card_id = "TRL_520"
c521_patron_overkill_summons_copy_only_when_excess_damage.card_id = "TRL_521"
c522_wartbringer_requires_two_spells_for_damage.card_id = "TRL_522"
c523_witchdoctor_discovers_spell_only_with_dragon.card_id = "TRL_523"
c524_shieldbreaker_requires_enemy_taunt_and_silences_it.card_id = "TRL_524"
c525_treasure_chest_deathrattle_draws_two_cards.card_id = "TRL_525"
c526_scorcher_damages_all_other_minions_not_itself.card_id = "TRL_526"
c527_trickster_gives_each_player_from_opponents_deck.card_id = "TRL_527"
c528_linecracker_doubles_attack_only_on_overkill.card_id = "TRL_528"
c530_contender_plays_secret_from_deck_if_secret_controlled.card_id = "TRL_530"
c531_shaker_deathrattle_summons_three_two_breaker.card_id = "TRL_531"
c532_announcer_randomly_redirects_about_half_of_attacks.card_id = "TRL_532"
c533_peddler_gains_armor_only_with_frozen_friendly_minion.card_id = "TRL_533"
c535_shellfighter_redirects_damage_from_adjacent_minions.card_id = "TRL_535"
c537_undatakah_copies_three_friendly_dead_deathrattles.card_id = "TRL_537"
c542_ondasta_rush_overkill_summons_hand_beast.card_id = "TRL_542"
c543_bloodclaw_equips_weapon_and_deals_five_to_hero.card_id = "TRL_543"
c545_templar_threshold_requires_ten_health_restored.card_id = "TRL_545"
c546_tortoise_battlecry_damages_hero_five.card_id = "TRL_546"
c550_war_bear_has_rush_taunt_and_cannot_attack_hero_immediately.card_id = "TRL_550"
c551_diretroll_discards_lowest_cost_hand_card.card_id = "TRL_551"
c555_demonbolt_cost_falls_per_friendly_minion_and_destroys_target.card_id = "TRL_555"
c564_zihi_sets_both_max_mana_to_five.card_id = "TRL_564"
c566_revenge_summons_friendly_beast_that_died_this_turn.card_id = "TRL_566"
c569_crowd_roaster_requires_dragon_to_deal_seven.card_id = "TRL_569"
c570_soup_vendor_draws_only_for_three_plus_hero_heal.card_id = "TRL_570"
c900_halazzi_fills_hand_with_one_one_rush_lynxes.card_id = "TRL_900"
c901_spirit_of_lynx_stealth_and_beast_summon_buff.card_id = "TRL_901"

if __name__ == "__main__":
    main()
