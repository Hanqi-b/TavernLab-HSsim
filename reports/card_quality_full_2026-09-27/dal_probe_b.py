"""Card-specific live game checks for frozen indices 45:90 of Rise of Shadows YELLOW cards."""

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
from utils import WISP, THE_COIN, BaseTestGame, Player, prepare_empty_game  # noqa: E402

logging.disable(logging.CRITICAL)
PROBE_FILE = HERE / "dal_probe_b.csv"
VERDICT_FILE = HERE / "dal_verdict_b.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
LACKEY_IDS = {"DAL_613", "DAL_614", "DAL_615", "DAL_739", "DAL_741", "ULD_616", "DRG_052"}


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
ROSTER = ROSTER_FULL[45:90]
assert len(ROSTER) == 45 and ROSTER[0]["card_id"] == "DAL_357" and ROSTER[-1]["card_id"] == "DAL_589"
assert len({r["card_id"] for r in ROSTER}) == 45 and [r["card_id"] for r in ROSTER] == sorted(r["card_id"] for r in ROSTER)
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


def play(player, cid, target=None, index=None):
    card = player.give(cid)
    kw = {}
    if target is not None:
        kw["target"] = target
    if index is not None:
        kw["index"] = index
    card.play(**kw)
    return card


def check(ok, observed):
    assert ok, observed
    return observed


def meta(cid):
    m = MASTER[cid]
    b = ROSTER_BY_ID[cid]
    return (f"EN={m['card_text_en']}; ZH={m['card_text_zh']}; "
            f"source={m['python_source']}; existing_tests={m['test_refs_candidate'] or 'none'}; "
            f"prior={b['status']}:{b['reason']}; prior_evidence={b['evidence']}")


def audit(cid, tests, blocker=None):
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
        print(cid, case_id, outcome, observed)
    own = [r for r in PROBES if r["card_id"] == cid]
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in errors)
    elif unresolved or blocker:
        status = "YELLOW"
        reason = blocker or "运行未决：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in unresolved)
    else:
        status = "GREEN"
        reason = "逐卡关键行为断言通过：" + "; ".join(f"{r['case_id']}: {r['observed']}" for r in own)
    VERDICTS.append(dict(card_id=cid, status=status,
                         mechanic_scope=ROSTER_BY_ID[cid]["mechanic"], reason=reason,
                         probe_file=PROBE_FILE.name, notes=meta(cid)))
    write(VERDICT_FILE, VF, VERDICTS)
    print(cid, status, len(own), "cases")



def lucentbark():
    cid = "DAL_357"

    def deathrattle_dormant_and_five_actual_healing_awakens():
        g, p, e = game(CardClass.DRUID, CardClass.MAGE, seed=3571)
        bark = play(p, cid)
        bark.destroy()
        dormant = next((m for m in p.field if m.id == "DAL_357t"), None)
        initial = (dormant.id, dormant.zone.name, dormant.dormant, dormant.progress) if dormant else None
        assert dormant is not None and dormant.zone == Zone.PLAY and dormant.dormant and dormant.progress == 0, initial

        # Spend first, then coins supply exactly enough turn mana for the three heals.
        p.hero.set_current_health(28)
        coins = []
        for _ in range(4):
            coin = p.give(THE_COIN)
            coin.play()
            coins.append(coin)
        p.give("CS2_089").play(target=p.hero)  # Heal 2 actual health to cap.
        after_first = (p.hero.health, dormant.progress, dormant.id, dormant.zone.name)
        ally = p.summon("CS2_182")
        ally.set_current_health(3)
        p.give("CS2_089").play(target=ally)  # Heal 2 actual health.
        after_second = (ally.health, dormant.progress, dormant.id, dormant.zone.name)
        p.hero.set_current_health(29)
        p.give("CS2_089").play(target=p.hero)  # Heal 1 actual health.
        awakened = next((m for m in p.field if m.id == cid), None)
        remaining_dormant = [m for m in p.field if m.id == "DAL_357t"]
        observed = (f"initial={initial};after_first={after_first};after_second={after_second};"
                    f"hero_health={p.hero.health};ally={(ally.health,ally.max_health)};"
                    f"awakened={(awakened.id,awakened.atk,awakened.health,awakened.taunt,awakened.zone.name) if awakened else None};"
                    f"dormant_remaining={len(remaining_dormant)};coin_zones={[c.zone.name for c in coins]};mana={p.mana}")
        return check(awakened is not None and awakened.zone == Zone.PLAY and awakened.taunt
                     and not remaining_dormant and p.hero.health == 30 and ally.health == ally.max_health == 5,
                     observed)

    audit(cid, [("deathrattle_dormant_and_cumulative_heal_wakes", "Deathrattle goes Dormant; cumulative actual healing of 5 across characters wakes Lucentbark.", deathrattle_dormant_and_five_actual_healing_awakens, "实战摧毁嘲讽树灵后核对休眠令牌，再将英雄实际恢复2点、友方Yeti实际恢复2点、英雄实际恢复1点；低于5期间继续休眠，达到5后检查本体返回场上。")])


lucentbark.card_id = "DAL_357"


def unidentified_contract():
    cid = "DAL_366"

    def drawing_contract_selects_one_of_four_real_variants():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=3661)
        p.give(cid).shuffle_into_deck()
        play(p, "CS2_023")  # Arcane Intellect draws the Contract from the deck.
        variants = ("DAL_366t1", "DAL_366t2", "DAL_366t3", "DAL_366t4")
        cards = [c for c in p.hand if c.id in variants]
        observed = f"hand={[c.id for c in p.hand]};variants={[c.id for c in cards]};deck={[c.id for c in p.deck]}"
        return check(len(cards) == 1 and cards[0].zone == Zone.HAND and len(p.deck) == 0, observed)

    def each_drawn_variant_resolves_its_bonus():
        variants = ("DAL_366t1", "DAL_366t2", "DAL_366t3", "DAL_366t4")
        rows = []
        for i, variant in enumerate(variants):
            g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=3662 + i)
            if variant == "DAL_366t4":
                left, target, right = e.summon("CS2_182"), e.summon("CS2_182"), e.summon("CS2_182")
            else:
                target = e.summon("CS2_182")
            play(p, variant, target=target)
            rows.append((variant, target.zone.name, [(m.id,m.health,m.damage,m.zone.name) for m in e.field], [c.id for c in p.hand], [c.id for c in p.field]))
            if variant == "DAL_366t1":
                assert target.zone == Zone.GRAVEYARD and any(c.id == "EX1_522" and c.zone == Zone.PLAY for c in p.field), rows[-1]
            elif variant == "DAL_366t2":
                assert target.zone == Zone.GRAVEYARD and sum(c.id == "CS2_182" for c in p.hand) == 1, rows[-1]
            elif variant == "DAL_366t3":
                assert target.zone == Zone.GRAVEYARD and sum(c.id == THE_COIN for c in p.hand) == 2, rows[-1]
            else:
                assert target.zone == Zone.GRAVEYARD and left.health == 1 and right.health == 1, rows[-1]
        return check(len(rows) == 4, f"variant_resolutions={rows}")

    audit(cid, [
        ("draw_morphs_into_bonus_contract", "Drawing Unidentified Contract changes it into one of its four hand bonuses.", drawing_contract_selects_one_of_four_real_variants, "从牌库实际抽到未鉴定契约，检查手牌里的实体变为四种合同之一。"),
        ("four_contract_bonus_resolutions", "All four generated contract versions destroy their chosen minion and resolve their distinct bonus.", each_drawn_variant_resolves_its_bonus, "逐个实际打出四种合同实体，分别核对1/1刺客、目标复制回手、两枚幸运币，以及目标攻击力对相邻随从造成伤害。"),
    ])


unidentified_contract.card_id = "DAL_366"


def marked_shot():
    cid = "DAL_371"

    def deals_four_then_discovers_spell():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=3711)
        target = e.summon("CS2_182")
        shot = play(p, cid, target=target)
        after_damage = (target.health, target.damage, target.zone.name)
        choice = p.choice
        offered = [(c.id, int(c.type)) for c in choice.cards]
        selected = choice.cards[0]
        choice.choose(selected)
        observed = f"target_before=5;after={after_damage};offered={offered};selected={selected.id};hand={[c.id for c in p.hand]};spell={shot.zone.name}"
        return check(after_damage == (1, 4, "PLAY") and len(offered) == 3 and all(t == int(CardType.SPELL) for _,t in offered) and selected in p.hand and not p.choice and shot.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("four_damage_and_spell_discover", "Deals 4 to a minion and Discovers a spell into hand.", deals_four_then_discovers_spell, "以敌方5血Yeti为目标核对4点伤害存活状态，再核对三张发现候选均为法术并选择一张入手。")])


marked_shot.card_id = "DAL_371"


def arcane_fletcher():
    cid = "DAL_372"

    def only_playing_a_one_cost_minion_draws_spell():
        def scenario(one_cost, seed):
            g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=seed)
            fletcher = play(p, cid)
            p.give("CS2_029").shuffle_into_deck()
            card_id = "EX1_011" if one_cost else WISP
            if one_cost:
                p.hero.damage = 1
            played = play(p, card_id, target=p.hero if one_cost else None)
            drawn = [c for c in p.hand if c.id == "CS2_029"]
            observed = f"one_cost={one_cost};played={(played.id,played.cost,played.zone.name)};fletcher={fletcher.zone.name};hero={p.hero.health};drawn={[c.id for c in drawn]};deck={[c.id for c in p.deck]}"
            return check((len(drawn) == 1 and drawn[0].zone == Zone.HAND and not p.deck and p.hero.health == 30) if one_cost else (not drawn and len(p.deck) == 1), observed)
        return scenario(True, 3721) + "; " + scenario(False, 3722)

    audit(cid, [("one_cost_minion_play_triggers_spell_draw", "Playing a 1-Cost minion draws a spell; a 0-Cost minion does not trigger it.", only_playing_a_one_cost_minion_draws_spell, "分别打出1费Voodoo Doctor（指定受伤己方英雄）和0费Wisp，牌库均只留法术，核对只前者抽法术。")])


arcane_fletcher.card_id = "DAL_372"


def rapid_fire():
    cid = "DAL_373"

    def first_cast_generates_single_twinspell_for_second_cast():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=3731)
        target = e.summon("CS2_182")
        original = play(p, cid, target=target)
        twins = [c for c in p.hand if c.id == "DAL_373ts"]
        first = (target.health, target.damage, len(twins), original.zone.name)
        twin = twins[0] if twins else None
        if twin:
            twin.play(target=target)
        second = (target.health, target.damage, len([c for c in p.hand if c.id in (cid,"DAL_373ts")]), twin.zone.name if twin else None)
        observed = f"first={first};second={second};hand={[c.id for c in p.hand]};target_zone={target.zone.name}"
        return check(first == (4,1,1,"GRAVEYARD") and second == (3,2,0,"GRAVEYARD") and target.zone == Zone.PLAY, observed)

    audit(cid, [("twinspell_first_and_copy_cast", "Rapid Fire deals 1 damage and creates one Twinspell copy; that copy deals 1 and does not reproduce itself.", first_cast_generates_single_twinspell_for_second_cast, "以5血Yeti连续承受原始Rapid Fire与手牌双生副本，各受1伤；核对只第一张产生副本。")])


rapid_fire.card_id = "DAL_373"


def oblivitron():
    cid = "DAL_376"

    def deathrattle_pulls_mech_and_triggers_its_deathrattle():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=3761)
        harvest = p.give("EX1_556")
        body = play(p, cid)
        body.destroy()
        other_minions = [m for m in p.field if m is not harvest]
        observed = f"oblivitron={body.zone.name};harvest={(harvest.id,harvest.atk,harvest.health,harvest.zone.name)};other_minions={[(m.id,m.atk,m.health,m.zone.name) for m in other_minions]};hand={[c.id for c in p.hand]}"
        return check(body.zone == Zone.GRAVEYARD and harvest not in p.hand and harvest in p.field and harvest.id == "EX1_556" and len(other_minions) == 1 and (other_minions[0].atk, other_minions[0].health) == (2, 1), observed)

    audit(cid, [("deathrattle_summons_hand_mech_and_triggers_deathrattle", "On death, pulls a Mech from hand, summons it, and triggers its Deathrattle.", deathrattle_pulls_mech_and_triggers_its_deathrattle, "把 Harvest Golem 留在手牌，实际摧毁 Oblivitron；检查机械从手牌离开、进场，且 Harvest Golem 的亡语额外召唤 2/1 Damaged Golem。")])


oblivitron.card_id = "DAL_376"


def nine_lives():
    cid = "DAL_377"

    def discovers_dead_friendly_deathrattle_and_triggers_it():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=3771)
        leper = p.give("EX1_029"); leper.play(); leper.destroy()
        before = e.hero.health
        spell = play(p, cid)
        offered = [c.id for c in p.choice.cards]
        chosen = p.choice.cards[0]
        p.choice.choose(chosen)
        cards = [c.id for c in p.hand]
        observed = f"dead={leper.zone.name};offered={offered};chosen={chosen.id};hand={cards};enemy_hero={e.hero.health};spell={spell.zone.name}"
        return check(offered and all(card_id == "EX1_029" for card_id in offered) and "EX1_029" in cards and e.hero.health == before - 2 and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("discover_dead_deathrattle_and_retrigger", "Discovers a friendly Deathrattle minion that died this game, returns a copy, and triggers its Deathrattle.", discovers_dead_friendly_deathrattle_and_triggers_it, "先让友方 Leper Gnome 实际死亡，再施放 Nine Lives；确认候选是该亡语随从、选择后复制入手，并再次对敌方英雄造成2伤。")])


nine_lives.card_id = "DAL_377"


def unleash_the_beast():
    cid = "DAL_378"

    def twinspell_summons_two_rush_wyverns():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=3781)
        enemy = e.summon(WISP)
        first = play(p, cid)
        copy = next((c for c in p.hand if c.id == "DAL_378ts"), None)
        first_body = next((m for m in p.field if m.id == "DAL_378t1"), None)
        first_ready = bool(first_body and first_body.rush and first_body.can_attack)
        if first_body:
            first_body.attack(enemy)
        after_attack = (enemy.zone.name, enemy.health, bool(first_body and first_body.can_attack))
        if copy:
            p.used_mana = 0  # The probe isolates the generated Twinspell branch after the first 6-cost cast.
            copy.play()
        bodies = [m for m in p.field if m.id == "DAL_378t1"]
        observed = f"first={first.zone.name};copy={copy.zone.name if copy else None};first_body_ready={first_ready};after_attack={after_attack};bodies={[(m.atk,m.health,m.rush,m.zone.name) for m in bodies]};hand={[c.id for c in p.hand]}"
        return check(copy is not None and copy.zone == Zone.GRAVEYARD and first.zone == Zone.GRAVEYARD and first_ready and after_attack[0] == "GRAVEYARD" and len(bodies) == 2 and [(m.atk,m.health,m.rush) for m in bodies] == [(5,4,1),(5,5,1)] and not any(c.id == "DAL_378ts" for c in p.hand), observed)

    audit(cid, [("twinspell_summons_rush_wyvern_twice", "Each Twinspell cast summons a 5/5 Rush Wyvern; first may attack a minion immediately and copy is consumed.", twinspell_summons_two_rush_wyverns, "施放本体后实际取用其生成的 Twinspell 副本（测试夹具重置已用法力以单局验证两次），检查各召唤5/5突袭飞龙、首只当回合攻击敌方 Wisp 并击杀，副本消耗后不再留牌。")])


unleash_the_beast.card_id = "DAL_378"


def vereesa_windrunner():
    cid = "DAL_379"

    def equips_weapon_and_attacking_grants_spell_damage():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=3791)
        vereesa = play(p, cid)
        weapon = p.weapon
        p.hero.attack(e.hero)
        weapon_after_attack = weapon.durability if weapon else None
        enemy_hero_after_attack = e.hero.health
        target = e.summon("CS2_182")
        spell = play(p, "DAL_373", target=target)
        observed = f"body={vereesa.zone.name};weapon={(weapon.id,weapon.atk,weapon.durability,weapon.zone.name) if weapon else None};weapon_after_attack={weapon_after_attack};enemy_hero_after_attack={enemy_hero_after_attack};hero_atk={p.hero.atk};target={(target.health,target.damage,target.zone.name)};spell={spell.zone.name};spellpower={p.spellpower}"
        return check(weapon is not None and weapon.id == "DAL_379t" and weapon.zone == Zone.PLAY and weapon_after_attack == 2 and enemy_hero_after_attack == 28 and target.damage == 3 and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("battlecry_equips_thoridal_and_attack_buffs_spell_damage", "Battlecry equips Thori'dal; a hero attack grants +2 Spell Damage for the turn.", equips_weapon_and_attacking_grants_spell_damage, "实战打出 Vereesa 并核对装备武器；英雄攻击后施放 Rapid Fire，以敌方5血Yeti承受3伤证实本回合获得+2法伤。")])


vereesa_windrunner.card_id = "DAL_379"


def evil_cable_rat():
    cid = "DAL_400"

    def battlecry_adds_one_real_lackey():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=4001)
        before = len(p.hand)
        body = play(p, cid)
        lackeys = [c for c in p.hand if c.id in LACKEY_IDS]
        observed = f"body={(body.id,body.atk,body.health,body.zone.name)};hand={[c.id for c in p.hand]};lackeys={[c.id for c in lackeys]};hand_delta={len(p.hand)-before}"
        return check(body.zone == Zone.PLAY and len(lackeys) == 1 and len(p.hand) == before + 1 and all(c.zone == Zone.HAND for c in lackeys), observed)

    audit(cid, [("battlecry_generates_a_lackey", "Battlecry adds one Lackey card to hand.", battlecry_adds_one_real_lackey, "打出 Cable Rat，核对手牌准确增加一张处于手牌区的实体 Lackey。")])


evil_cable_rat.card_id = "DAL_400"


def evil_concripter():
    cid = "DAL_413"

    def deathrattle_adds_a_lackey():
        g, p, e = game(CardClass.PRIEST, CardClass.MAGE, seed=4131)
        body = play(p, cid)
        before = len(p.hand)
        body.destroy()
        lackeys = [c for c in p.hand if c.id in LACKEY_IDS]
        observed = f"body={body.zone.name};hand={[c.id for c in p.hand]};lackeys={[c.id for c in lackeys]};hand_delta={len(p.hand)-before}"
        return check(body.zone == Zone.GRAVEYARD and len(lackeys) == 1 and len(p.hand) == before + 1, observed)

    audit(cid, [("deathrattle_adds_a_lackey", "Deathrattle adds one Lackey card to hand.", deathrattle_adds_a_lackey, "实际摧毁场上的 EVIL Conscripter，检查亡语只增加一张手牌 Lackey。")])


evil_concripter.card_id = "DAL_413"


def evil_miscreant():
    cid = "DAL_415"

    def combo_adds_two_random_lackeys_only_when_preceded_by_card():
        def scenario(combo, seed):
            g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=seed)
            if combo:
                p.give(THE_COIN).play()
            before = len(p.hand)
            body = play(p, cid)
            lackeys = [c for c in p.hand if c.id in LACKEY_IDS]
            observed = f"combo={combo};body={body.zone.name};hand={[c.id for c in p.hand]};lackeys={[c.id for c in lackeys]};delta={len(p.hand)-before}"
            return check(body.zone == Zone.PLAY and len(lackeys) == (2 if combo else 0) and len(p.hand)-before == (2 if combo else 0), observed)
        return scenario(False, 4151) + " | " + scenario(True, 4152)

    audit(cid, [("combo_adds_two_lackeys_and_noncombo_adds_none", "Combo adds two Lackeys after a prior card this turn; without Combo it adds none.", combo_adds_two_random_lackeys_only_when_preceded_by_card, "同一规则下对比本回合第一张打 Miscreant 与先使用 Coin 再打；确认只有连击分支增加两张 Lackey。")])


evil_miscreant.card_id = "DAL_415"


def hench_clan_burglar():
    cid = "DAL_416"

    def discovers_three_other_class_spells():
        g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=4161)
        body = play(p, cid)
        cards = list(p.choice.cards)
        offered = [(c.id, int(c.type), int(c.card_class)) for c in cards]
        chosen = cards[0]
        p.choice.choose(chosen)
        observed = f"body={body.zone.name};offered={offered};chosen={chosen.id};hand={[c.id for c in p.hand]}"
        return check(len(cards) == 3 and all(c.type == CardType.SPELL and c.card_class != CardClass.ROGUE for c in cards) and chosen in p.hand and not p.choice, observed)

    audit(cid, [("battlecry_discovers_another_class_spell", "Battlecry offers three spells from classes other than Rogue and places the chosen one in hand.", discovers_three_other_class_spells, "打出 Burglar 并检查三个真实候选都是法术且职业不是 Rogue，选择后确认实体牌进入手牌。")])


hench_clan_burglar.card_id = "DAL_416"


def heistbaron_togwaggle():
    cid = "DAL_417"

    def lackey_enables_treasure_choice_only():
        def scenario(with_lackey, seed):
            g, p, e = game(CardClass.ROGUE, CardClass.MAGE, seed=seed)
            lackey = p.give("DAL_613").play() if with_lackey else None
            before = len(p.hand)
            body = play(p, cid)
            if with_lackey:
                offered = [c.id for c in p.choice.cards]
                chosen = p.choice.cards[0]
                p.choice.choose(chosen)
                observed = f"lackey={(lackey.id,lackey.zone.name)};body={body.zone.name};offered={offered};chosen={chosen.id};hand={[c.id for c in p.hand]}"
                return check(len(offered) == 4 and chosen.id in ("LOOT_998h", "LOOT_998j", "LOOT_998l", "LOOT_998k") and chosen in p.hand and not p.choice, observed)
            observed = f"lackey=None;body={body.zone.name};choice={p.choice};hand={[c.id for c in p.hand]};delta={len(p.hand)-before}"
            return check(not p.choice and len(p.hand) == before, observed)
        return scenario(False, 4171) + " | " + scenario(True, 4172)

    audit(cid, [("lackey_gates_treasure_choice", "Without a controlled Lackey Battlecry gives no treasure choice; with one it offers four treasures.", lackey_enables_treasure_choice_only, "對照空場手牌狀態與控制實體 Lackey 的狀態打出 Togwaggle；只有後者出现四选一并将所选宝藏入手。")])


heistbaron_togwaggle.card_id = "DAL_417"


def arch_villain_rafaam():
    cid = "DAL_422"

    def replaces_hand_and_deck_with_legendary_minions():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=4221)
        p.give(WISP)
        p.give("CS2_029")
        p.give("EX1_015").shuffle_into_deck()
        p.give("CS2_182").shuffle_into_deck()
        before_deck = len(p.deck)
        body = play(p, cid)
        hand_types = [(c.id, c.type.name if hasattr(c.type, "name") else int(c.type), c.data.tags.get(GameTag.RARITY) == 5) for c in p.hand]
        deck_types = [(c.id, c.type.name if hasattr(c.type, "name") else int(c.type), c.data.tags.get(GameTag.RARITY) == 5) for c in p.deck]
        observed = f"body={body.zone.name};before_deck={before_deck};hand={hand_types};deck={deck_types};hand_n={len(p.hand)};deck_n={len(p.deck)}"
        return check(len(p.hand) == 2 and len(p.deck) == before_deck and all(c[1] == "MINION" and c[2] for c in hand_types + deck_types), observed)

    audit(cid, [("battlecry_replaces_hand_and_deck", "Battlecry replaces every other hand/deck card with Legendary minions.", replaces_hand_and_deck_with_legendary_minions, "预置两张非传说手牌和两张牌库牌，打出 Rafaam 后检查其余手牌及原牌库数量均保留但牌种替换为传说随从。")])


arch_villain_rafaam.card_id = "DAL_422"


def swampqueen_hagatha():
    cid = "DAL_431"

    def teaches_two_spells_to_real_horror():
        g, p, e = game(CardClass.SHAMAN, CardClass.MAGE, seed=4311)
        body = play(p, cid)
        first_offered = [(c.id, bool(c.requirements)) for c in p.choice.cards]
        first = next((c for c in p.choice.cards if not c.requirements), p.choice.cards[0])
        p.choice.choose(first)
        second_offered = [(c.id, bool(c.requirements)) for c in p.choice.cards]
        second = next((c for c in p.choice.cards if not c.requirements), p.choice.cards[0])
        p.choice.choose(second)
        horror = next((c for c in p.hand if c.id == "DAL_431t"), None)
        script_match = bool(horror and horror.data.scripts.play == first.data.scripts.play + second.data.scripts.play)
        overload_match = bool(horror and horror.overload == first.overload + second.overload)
        stats = (horror.atk, horror.health, horror.cost) if horror else None
        observed = f"body={body.zone.name};first={first.id};first_offered={first_offered};second={second.id};second_offered={second_offered};horror={stats};script_match={script_match};overload_match={overload_match}"
        return check(horror is not None and stats == (5,5,5) and script_match and overload_match and not p.choice, observed)

    audit(cid, [("battlecry_builds_5_5_horror_from_two_selected_spells", "Battlecry resolves two Shaman spell choices into a 5/5 Horror whose play script and Overload equal both selected spells.", teaches_two_spells_to_real_horror, "逐步实际选择两个萨满法术，检查5/5恐魔入手，逐个核对定制脚本、过载值由两张所选法术组合而成。")])


swampqueen_hagatha.card_id = "DAL_431"


def witchs_brew():
    cid = "DAL_432"

    def repeatable_spell_heals_twice_this_turn():
        g, p, e = game(CardClass.SHAMAN, CardClass.MAGE, seed=4321)
        p.hero.damage = 8
        brew = play(p, cid, target=p.hero)
        after_first = (p.hero.health, brew.zone.name, [c.id for c in p.hand])
        repeat = next((c for c in p.hand if c.id == cid), None)
        if repeat:
            repeat.play(target=p.hero)
        observed = f"after_first={after_first};after_second={p.hero.health};repeat={repeat.zone.name if repeat else None};hand={[c.id for c in p.hand]};graveyard={[c.id for c in p.graveyard if c.id==cid]}"
        return check(after_first[0] == 26 and repeat is not None and p.hero.health == 30 and repeat.zone == Zone.GRAVEYARD and len([c for c in p.graveyard if c.id == cid]) == 2 and any(c.id == cid for c in p.hand), observed)

    audit(cid, [("repeatable_restore_four_twice", "Restore 4 Health, then receive a repeatable copy that can restore 4 more Health during the same turn.", repeatable_spell_heals_twice_this_turn, "将己方英雄降至22血，施放两次 Witch's Brew；核对第一次+4、同回合复制第二次再+4并消耗两张法术。")])


witchs_brew.card_id = "DAL_432"


def sludge_slurper():
    cid = "DAL_433"

    def battlecry_adds_lackey_and_overloads_one_next_turn():
        g, p, e = game(CardClass.SHAMAN, CardClass.MAGE, seed=4331)
        before = len(p.hand)
        body = play(p, cid)
        lackeys = [c for c in p.hand if c.id in LACKEY_IDS]
        locked = p.overload_locked
        g.end_turn(); g.end_turn()
        observed = f"body={body.zone.name};lackeys={[c.id for c in lackeys]};hand_delta={len(p.hand)-before};overload_state_after_play={locked};max_mana_next_turn={p.max_mana};overload_locked_next_turn={p.overload_locked}"
        return check(body.zone == Zone.PLAY and len(lackeys) == 1 and len(p.hand) == before + 1 and locked == 0 and p.max_mana == 10 and p.overload_locked == 1, observed)

    audit(cid, [("battlecry_lackey_and_overload_one", "Battlecry adds one Lackey and Overload (1) locks one mana on the next turn.", battlecry_adds_lackey_and_overloads_one_next_turn, "打出 Slurper 检查一张 Lackey 入手；结束回合后再回到己方回合，检查过载状态显示锁定1颗水晶。")])


sludge_slurper.card_id = "DAL_433"


def arcane_watcher():
    cid = "DAL_434"

    def cannot_attack_until_spell_damage_is_controlled():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=4341)
        watcher = play(p, cid)
        target = e.summon("CS2_182")
        g.end_turn(); g.end_turn()
        blocked = False
        try:
            watcher.attack(target)
        except InvalidAction:
            blocked = True
        damage_before = (watcher.damage, target.damage)
        dragon = play(p, "EX1_284")
        spellpower = p.spellpower
        blocked_with_spellpower = False
        try:
            watcher.attack(target)
        except InvalidAction:
            blocked_with_spellpower = True
        observed = f"blocked_without_spellpower={blocked};before_damage={damage_before};dragon={(dragon.id,dragon.zone.name)};spellpower={spellpower};blocked_with_spellpower={blocked_with_spellpower};watcher={(watcher.atk,watcher.health,watcher.damage)};target={(target.health,target.damage,target.zone.name)}"
        return check(blocked and damage_before == (0,0) and spellpower > 0 and not blocked_with_spellpower and watcher.damage == 4 and target.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("attack_locked_until_spell_damage_then_can_attack", "Cannot attack with no friendly Spell Damage; after gaining Spell Damage it can attack a minion.", cannot_attack_until_spell_damage_is_controlled, "讓 Watcher 經過一個敵方回合成熟；無法術傷害時實際攻擊必被拒絕，打出 Azure Drake 後獲得1法傷，再以5攻擊力擊殺5血Yeti並承受4點反擊。")])


arcane_watcher.card_id = "DAL_434"


def unseen_saboteur():
    cid = "DAL_538"

    def casts_only_enemy_spell_from_hand_and_consumes_it():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5381)
        spell = e.give("DS1_233")
        before = p.hero.health
        body = play(p, cid)
        observed = f"body={body.zone.name};spell={(spell.id,spell.zone.name)};friendly_hero={p.hero.health};enemy_hero={e.hero.health};enemy_hand={[c.id for c in e.hand]}"
        return check(spell.zone == Zone.GRAVEYARD and p.hero.health < before and e.hero.health == 30 and not e.hand, observed)

    audit(cid, [("battlecry_casts_opponents_random_spell", "Battlecry makes the opponent cast the only spell in their hand; random target damages the only legal enemy character.", casts_only_enemy_spell_from_hand_and_consumes_it, "只在敌方手牌放一张 DS1_233，并保持双方场面为空；打出 Saboteur 后检查该法术真实进入墓地、造成敌方法术伤害且敌方英雄未受伤。")])


unseen_saboteur.card_id = "DAL_538"


def sunreaver_warmage():
    cid = "DAL_539"

    def scenario(qualifying, seed):
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=seed)
        held = p.give("CS2_028" if qualifying else "CS2_029")
        target = e.summon("CS2_182")
        before = target.damage
        warmage = play(p, cid, target=target if qualifying else None)
        observed = f"qualifying={qualifying};held={(held.id,held.cost,held.zone.name)};body={warmage.zone.name};target={(target.health,target.damage,target.zone.name)};hand={[c.id for c in p.hand]}"
        return check((target.damage == before + 4) if qualifying else (target.damage == before), observed)

    audit(cid, [
        ("holding_six_cost_spell_enables_four_damage", "Holding a 6-Cost spell enables the 4-damage Battlecry.", lambda: scenario(True, 5391), "手持6费 Blizzard 且指定敌方Yeti，检查 Warmage 战吼实际造成4伤。"),
        ("holding_four_cost_spell_does_not_enable_damage", "Holding a 4-Cost spell does not enable the damage Battlecry.", lambda: scenario(False, 5392), "对照只手持4费 Fireball，不给目标；检查战吼不造成伤害。"),
    ])


sunreaver_warmage.card_id = "DAL_539"


def potion_vendor():
    cid = "DAL_544"

    def battlecry_restores_all_friendly_characters_two():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5441)
        p.hero.damage = 4
        ally = p.summon("CS2_182"); ally.damage = 2
        enemy_hero_before = e.hero.health
        body = play(p, cid)
        observed = f"body={body.zone.name};hero={p.hero.health};ally={(ally.health,ally.damage)};enemy_hero={e.hero.health}"
        return check(p.hero.health == 28 and ally.health == 5 and ally.damage == 0 and e.hero.health == enemy_hero_before, observed)

    audit(cid, [("battlecry_restores_friendly_characters_two", "Battlecry restores 2 Health to every friendly character.", battlecry_restores_all_friendly_characters_two, "實際讓己方英雄受4傷、友方Yeti受2傷後打出 Potion Vendor；檢查英雄与随从各恢复2，敌方英雄不变。")])


potion_vendor.card_id = "DAL_544"


def barista_lynchen():
    cid = "DAL_546"

    def battlecry_copies_hand_battlecry_minions_but_not_other_cards():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5461)
        p.give("EX1_015"); p.give("EX1_015"); p.give(WISP)
        body = play(p, cid)
        engineer = [c for c in p.hand if c.id == "EX1_015"]
        wisps = [c for c in p.hand if c.id == WISP]
        observed = f"body={body.zone.name};hand={[c.id for c in p.hand]};engineers={len(engineer)};wisps={len(wisps)}"
        return check(body.zone == Zone.PLAY and len(engineer) == 4 and len(wisps) == 1 and all(c.zone == Zone.HAND for c in engineer), observed)

    audit(cid, [("copies_each_other_battlecry_minion_in_hand", "Battlecry adds a copy of each other Battlecry minion in hand and leaves non-Battlecry cards unchanged.", battlecry_copies_hand_battlecry_minions_but_not_other_cards, "手牌中放两张具有战吼的 Novice Engineer 和一张无战吼 Wisp，打出 Barista 后检查工程师变四张而 Wisp 仍一张。")])


barista_lynchen.card_id = "DAL_546"


def azerite_elemental():
    cid = "DAL_548"

    def gains_two_spell_damage_at_each_friendly_turn_start():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5481)
        body = play(p, cid)
        after_play = p.spellpower
        g.end_turn(); g.end_turn()
        after_first_start = p.spellpower
        g.end_turn(); g.end_turn()
        after_second_start = p.spellpower
        observed = f"body={body.zone.name};spellpower_after_play={after_play};after_first_start={after_first_start};after_second_start={after_second_start};stats={(body.atk,body.health)}"
        return check(after_play == 0 and after_first_start == 2 and after_second_start == 4 and body.zone == Zone.PLAY, observed)

    audit(cid, [("turn_start_grants_spell_damage_plus_two_each_time", "At each of your turn starts this minion gains Spell Damage +2.", gains_two_spell_damage_at_each_friendly_turn_start, "打出 Azerite Elemental 时法伤仍为0；完成两个己方回合开始事件，分别检查法伤变为2和4。")])


azerite_elemental.card_id = "DAL_548"


def underbelly_ooze():
    cid = "DAL_550"

    def survives_damage_then_summons_exact_copy_but_not_if_dead():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5501)
        ooze = play(p, cid)
        attacker = e.summon(WISP)
        g.end_turn()
        attacker.attack(ooze)
        copies = [m for m in p.field if m.id == cid]
        survived = (ooze.health, ooze.damage, len(copies), [(m.atk,m.health,m.zone.name) for m in copies])
        observed = f"attacker={attacker.zone.name};survived={survived};friendly_field={[m.id for m in p.field]}"
        return check(attacker.zone == Zone.GRAVEYARD and ooze.zone == Zone.PLAY and ooze.damage == 1 and len(copies) == 2 and all((m.atk,m.max_health,m.health,m.damage) == (ooze.atk,ooze.max_health,ooze.health,ooze.damage) for m in copies), observed)

    audit(cid, [("survives_damage_summons_exact_copy", "After surviving damage, summons an exact copy of this minion.", survives_damage_then_summons_exact_copy_but_not_if_dead, "敵方 Wisp 在敵方回合實際攻擊 Underbelly Ooze；確認來源存活受傷且場上出现一个同ID、3/3复本。")])


underbelly_ooze.card_id = "DAL_550"


def proud_defender():
    cid = "DAL_551"

    def taunt_attack_bonus_tracks_other_friendly_minions():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5511)
        body = play(p, cid)
        alone = (body.atk, body.health, body.taunt)
        ally = p.summon(WISP)
        with_ally = (body.atk, body.health, body.taunt)
        ally.destroy()
        alone_again = (body.atk, body.health, body.taunt)
        observed = f"alone={alone};with_ally={with_ally};alone_again={alone_again};ally={ally.zone.name}"
        return check(alone[0] == 4 and alone[2] and with_ally[0] == 2 and with_ally[2] and alone_again[0] == 4 and alone_again[2], observed)

    audit(cid, [("taunt_attack_bonus_updates_with_board_count", "Has Taunt and +2 Attack with no other friendly minions; loses bonus when another friendly appears and regains it when they leave.", taunt_attack_bonus_tracks_other_friendly_minions, "分別檢查 Proud Defender 單獨在場、加入一隻 Wisp、Wisp 死亡後的攻擊力4→2→4及全程嘲諷。")])


proud_defender.card_id = "DAL_551"


def big_bad_archmage():
    cid = "DAL_553"

    def end_turn_summons_one_random_six_cost_minion():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5531)
        body = play(p, cid)
        before = list(p.field)
        g.end_turn()
        summoned = [m for m in p.field if m not in before]
        observed = f"before={[m.id for m in before]};after={[(m.id,m.cost,int(m.type),m.zone.name) for m in p.field]};new={[(m.id,m.cost,int(m.type),m.zone.name) for m in summoned]}"
        return check(body in p.field and len(summoned) == 1 and summoned[0].type == CardType.MINION and summoned[0].cost == 6 and summoned[0].zone == Zone.PLAY, observed)

    audit(cid, [("own_turn_end_summons_six_cost_minion", "At the end of your turn, summons one random 6-Cost minion.", end_turn_summons_one_random_six_cost_minion, "打出 Archmage 后结束己方回合，逐项比较场面，确认本体保留且恰好新增一个6费随从。")])


big_bad_archmage.card_id = "DAL_553"


def chef_nomi():
    cid = "DAL_554"

    def scenario(empty_deck, seed):
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=seed)
        if not empty_deck:
            p.give(WISP).shuffle_into_deck()
        body = play(p, cid)
        tokens = [m for m in p.field if m.id == "DAL_554t"]
        observed = f"empty_deck={empty_deck};body={body.zone.name};deck={[c.id for c in p.deck]};tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens]};field={[m.id for m in p.field]}"
        return check(len(tokens) == (6 if empty_deck else 0) and all((m.atk,m.health) == (6,6) for m in tokens) and len(p.deck) == (0 if empty_deck else 1), observed)

    audit(cid, [
        ("empty_deck_summons_six_elementals", "If the deck is empty, summons six 6/6 Greasefire Elementals.", lambda: scenario(True, 5541), "空牌庫分支：打出 Chef Nomi 後检查额外召唤6个6/6 Greasefire Elemental。"),
        ("nonempty_deck_summons_none", "If any card remains in the deck, summons no Greasefire Elementals.", lambda: scenario(False, 5542), "对照牌库剩一张 Wisp，检查不会生成元素。"),
    ])


chef_nomi.card_id = "DAL_554"


def archmage_vargoth():
    cid = "DAL_558"

    def end_turn_recasts_only_spell_cast_this_turn():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5581)
        body = play(p, cid)
        spell = play(p, "DAL_373", target=e.hero)
        before = p.hero.health + e.hero.health + body.health
        g.end_turn()
        after = p.hero.health + e.hero.health + body.health
        observed = f"body={body.zone.name};original_spell={spell.zone.name};health_sum_before_end={before};health_sum_after_end={after};p_hero={p.hero.health};e_hero={e.hero.health};vargoth={(body.health,body.damage)};hand={[c.id for c in p.hand]}"
        return check(spell.zone == Zone.GRAVEYARD and before - after == 1 and body.zone == Zone.PLAY, observed)

    audit(cid, [("own_turn_end_recasts_spell_cast_this_turn", "At own turn end, casts a copy of a spell cast that turn, with target chosen randomly.", end_turn_recasts_only_spell_cast_this_turn, "只在本回合施放一张 Rapid Fire；结束回合后检查 Vargoth 额外施放一次，三名存活角色总生命再减少1（随机目标可不同）。")])


archmage_vargoth.card_id = "DAL_558"


def heroic_innkeeper():
    cid = "DAL_560"

    def battlecry_gains_two_two_per_other_friendly_minion():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5601)
        other = [p.summon(WISP), p.summon(WISP)]
        body = p.give(cid)
        base = (body.atk, body.health)
        body.play()
        observed = f"base={base};others={[(m.id,m.zone.name) for m in other]};after={(body.atk,body.health,body.zone.name)}"
        return check((body.atk,body.health) == (base[0] + 4,base[1] + 4) and body.zone == Zone.PLAY, observed)

    audit(cid, [("battlecry_plus_two_plus_two_per_other_minion", "Taunt Battlecry gains +2/+2 for each other friendly minion.", battlecry_gains_two_two_per_other_friendly_minion, "在打牌前控制两只友方 Wisp，记录 Innkeeper 手牌基础身材，打出后确认恰好+4/+4。")])


heroic_innkeeper.card_id = "DAL_560"


def jumbo_imp():
    cid = "DAL_561"

    def each_friendly_demon_death_reduces_hand_cost_once():
        g, p, e = game(CardClass.WARLOCK, CardClass.MAGE, seed=5611)
        imp = p.give(cid)
        base = imp.cost
        neutral = p.summon(WISP); neutral.destroy()
        after_non_demon = imp.cost
        demon1 = p.summon("CS2_065"); demon1.destroy()
        after_first = imp.cost
        demon2 = p.summon("CS2_065"); demon2.destroy()
        after_second = imp.cost
        observed = f"base={base};after_non_demon={after_non_demon};voidwalker1={demon1.zone.name};after_first={after_first};voidwalker2={demon2.zone.name};after_second={after_second};imp={imp.zone.name}"
        return check(base == 10 and after_non_demon == base and after_first == base - 1 and after_second == base - 2 and imp.zone == Zone.HAND, observed)

    audit(cid, [("friendly_demon_deaths_reduce_hand_cost", "While in hand, Jumbo Imp costs 1 less for each friendly Demon death; non-Demon deaths do not reduce it.", each_friendly_demon_death_reduces_hand_cost_once, "让 Jumbo Imp 留在手牌，先摧毁中立 Wisp 再先后摧毁两只 Voidwalker；核对费用保持10后逐次变为9、8。")])


jumbo_imp.card_id = "DAL_561"


def portal_overfiend():
    cid = "DAL_565"

    def shuffles_three_cast_when_drawn_portals():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5651)
        wisp = p.give(WISP); wisp.shuffle_into_deck()
        body = play(p, cid)
        portals = [c for c in p.deck if c.id == "DAL_582t"]
        # Keep the ordinary card at the bottom so the Portal replacement-draw chain is deterministic.
        p.deck.remove(wisp); p.deck.insert(0, wisp)
        drawn = p.draw()
        demons = [m for m in p.field if m.id == "DAL_582t2"]
        observed = f"body={body.zone.name};portals_before={len(portals)};deck_after={[(c.id,c.zone.name) for c in p.deck]};drawn={drawn.id if drawn else None}/{drawn.zone.name if drawn else None};wisp={wisp.zone.name};hand={[c.id for c in p.hand]};demons={[(m.id,m.atk,m.health,m.rush,m.race) for m in demons]}"
        return check(len(portals) == 3 and drawn is not None and drawn.id == "DAL_582t" and drawn.zone == Zone.GRAVEYARD and not p.deck and wisp.zone == Zone.HAND and len(demons) == 3 and all((m.atk,m.health,m.rush) == (2,2,1) for m in demons), observed)

    audit(cid, [("battlecry_shuffles_three_portals_and_draw_summons_rush_demon", "Battlecry shuffles three Portals; drawing one casts it and summons a 2/2 Rush Demon.", shuffles_three_cast_when_drawn_portals, "打出 Portal Overfiend 后核对牌库3张Portal，再实际抽到其中一张；检查Portal自动消耗并召唤2/2突袭恶魔，牌库余2张。")])


portal_overfiend.card_id = "DAL_565"


def eccentric_scribe():
    cid = "DAL_566"

    def deathrattle_summons_four_one_one_scrolls():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5661)
        body = play(p, cid)
        body.destroy()
        scrolls = [m for m in p.field if m.id == "DAL_566t"]
        observed = f"body={body.zone.name};scrolls={[(m.id,m.atk,m.health,m.zone.name) for m in scrolls]};field={[m.id for m in p.field]}"
        return check(body.zone == Zone.GRAVEYARD and len(scrolls) == 4 and all((m.atk,m.health,m.zone) == (1,1,Zone.PLAY) for m in scrolls), observed)

    audit(cid, [("deathrattle_summons_four_scrolls", "Deathrattle summons four 1/1 Vengeful Scrolls.", deathrattle_summons_four_one_one_scrolls, "實際摧毀 Scribe，核對亡語恰好召喚四個處於場上的1/1 Scroll。")])


eccentric_scribe.card_id = "DAL_566"


def lightforged_blessing():
    cid = "DAL_568"

    def twinspell_gives_lifesteal_and_both_minions_heal_hero():
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=5681)
        first = p.summon("EX1_015"); second = p.summon("EX1_015")
        p.hero.damage = 5
        g.end_turn(); g.end_turn()
        spell = play(p, cid, target=first)
        first.attack(e.hero)
        after_first = (p.hero.health,e.hero.health,first.zone.name)
        copy = next((c for c in p.hand if c.id == "DAL_568ts"), None)
        if copy:
            copy.play(target=second)
            second.attack(e.hero)
        observed = f"first={after_first};copy={copy.zone.name if copy else None};second={(p.hero.health,e.hero.health,second.zone.name)};first_minion={first.id};second_minion={second.id};hand={[c.id for c in p.hand]}"
        return check(after_first[:2] == (26,29) and copy is not None and copy.zone == Zone.GRAVEYARD and (p.hero.health,e.hero.health) == (27,28) and not any(c.id == "DAL_568ts" for c in p.hand), observed)

    audit(cid, [("twinspell_grants_lifesteal_and_restores_damage", "Twinspell gives a friendly minion Lifesteal; damage dealt by either cast's minion heals its hero.", twinspell_gives_lifesteal_and_both_minions_heal_hero, "讓兩個1攻友方 Novice Engineer 跨回合成熟並把英雄降至25；先後用本体及Twinspell赋予吸血并攻击敌方英雄，各造成1伤并实际治疗1。")])


lightforged_blessing.card_id = "DAL_568"


def never_surrender():
    cid = "DAL_570"

    def secret_ignores_owner_spell_and_triggers_on_opponent_spell():
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=5701)
        ally = p.summon(WISP)
        secret = play(p, cid)
        p.give(THE_COIN).play()
        after_own_spell = (ally.health,secret.zone.name,secret in p.secrets)
        g.end_turn()
        e.give(THE_COIN).play()
        observed = f"after_own_spell={after_own_spell};after_enemy_spell={(ally.health,ally.max_health,secret.zone.name,secret in p.secrets)};p_field={[m.id for m in p.field]}"
        return check(after_own_spell == (1,"SECRET",True) and (ally.health,ally.max_health) == (3,3) and secret.zone == Zone.GRAVEYARD and secret not in p.secrets, observed)

    audit(cid, [("secret_triggers_on_opponent_but_not_owner_spell", "When the opponent casts a spell, gives all friendly minions +2 Health; does not trigger for own spell.", secret_ignores_owner_spell_and_triggers_on_opponent_spell, "檢查己方 Coin 不觸發，秘密仍在场；结束回合后由敌方施放 Coin，Wisp生命上限与当前生命+2且秘密消耗。")])


never_surrender.card_id = "DAL_570"


def mysterious_blade():
    cid = "DAL_571"

    def scenario(with_secret, seed):
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=seed)
        secret = play(p, "DAL_570") if with_secret else None
        weapon_card = play(p, cid)
        weapon = p.weapon
        observed = f"with_secret={with_secret};secret={secret.zone.name if secret else None}/{secret in p.secrets if secret else False};weapon={(weapon.id,weapon.atk,weapon.durability,weapon.zone.name) if weapon else None}"
        return check(weapon is not None and weapon.id == cid and weapon.atk == (3 if with_secret else 2) and weapon.zone == Zone.PLAY, observed)

    audit(cid, [
        ("secret_control_gives_weapon_one_attack", "Controlling a Secret when Mysterious Blade's Battlecry resolves increases weapon Attack by 1.", lambda: scenario(True, 5711), "先控制 Never Surrender 奥秘再装备武器，检查2攻变3攻。"),
        ("no_secret_leaves_weapon_base_attack", "Without a Secret, Mysterious Blade keeps its base Attack.", lambda: scenario(False, 5712), "无奥秘时装备武器，检查保持2攻。"),
    ])


mysterious_blade.card_id = "DAL_571"


def commander_rhyssa():
    cid = "DAL_573"

    def scenario(with_rhyssa, seed):
        g, p, e = game(CardClass.PALADIN, CardClass.MAGE, seed=seed)
        ally = p.summon(WISP)
        rhyssa = play(p, cid) if with_rhyssa else None
        secret = play(p, "DAL_570")
        g.end_turn()
        e.give(THE_COIN).play()
        observed = f"with_rhyssa={with_rhyssa};rhyssa={rhyssa.zone.name if rhyssa else None};secret={secret.zone.name}/{secret in p.secrets};ally={(ally.health,ally.max_health)}"
        return check(secret.zone == Zone.GRAVEYARD and secret not in p.secrets and (ally.health,ally.max_health) == ((5,5) if with_rhyssa else (3,3)), observed)

    audit(cid, [
        ("secret_triggers_once_without_rhyssa", "Without Commander Rhyssa, Never Surrender triggers once for +2 Health.", lambda: scenario(False, 5731), "奥秘无 Rhyssa 时由敌方 Coin 触发一次，Wisp从1/1变1/3。"),
        ("secret_triggers_twice_with_rhyssa", "With Commander Rhyssa, Never Surrender triggers twice for +4 Health.", lambda: scenario(True, 5732), "控制 Rhyssa 后同样由敌方 Coin 触发，Wisp应从1/1变1/5。"),
    ])


commander_rhyssa.card_id = "DAL_573"


def khadgar():
    cid = "DAL_575"

    def doubles_one_minion_created_by_a_lackey():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5751)
        khadgar_body = play(p, cid)
        before = list(p.field)
        lackey = play(p, "DAL_613")
        added = [m for m in p.field if m not in before]
        summoned = [m for m in added if m is not lackey]
        observed = f"khadgar={khadgar_body.zone.name};lackey={lackey.zone.name};added={[(m.id,m.atk,m.health) for m in added]};summoned={[(m.id,m.atk,m.health) for m in summoned]}"
        return check(len(summoned) == 2 and summoned[0].id == summoned[1].id and lackey in p.field, observed)

    audit(cid, [("summon_effect_doubles_random_minion_created_by_lackey", "Cards that summon minions summon twice as many; Faceless Lackey's one random minion becomes two copies.", doubles_one_minion_created_by_a_lackey, "打出 Khadgar 后使用 Faceless Lackey，其战吼随机召唤一个2费随从；检查生成物恰有两只相同ID的实体。")])


khadgar.card_id = "DAL_575"


def kirin_tor_tricaster():
    cid = "DAL_576"

    def grants_three_spell_damage_increases_spell_cost_and_removal_reverts():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5761)
        fireball = p.give("CS2_029")
        base_cost = fireball.cost
        body = play(p, cid)
        increased_cost = fireball.cost
        target = e.summon("CS2_182")
        spell = play(p, "DAL_373", target=target)
        damage = target.damage
        body.destroy()
        reverted_cost = fireball.cost
        observed = f"body={body.zone.name};base_fireball_cost={base_cost};cost_with_tricaster={increased_cost};spellpower_damage={damage};fireball_cost_after_remove={reverted_cost};spellpower_after_remove={p.spellpower}"
        return check(base_cost == 4 and increased_cost == 5 and damage == 4 and reverted_cost == 4 and p.spellpower == 0 and body.zone == Zone.GRAVEYARD and spell.zone == Zone.GRAVEYARD, observed)

    audit(cid, [("spell_damage_three_and_spell_cost_plus_one_revert_on_death", "Has Spell Damage +3; friendly spells cost 1 more while present, and both effects leave when it dies.", grants_three_spell_damage_increases_spell_cost_and_removal_reverts, "手持 Fireball 观察4费→5费，Rapid Fire实际造成4伤验证+3法伤，再摧毁 Tricaster 检查法伤消失且 Fireball回到4费。")])


kirin_tor_tricaster.card_id = "DAL_576"


def ray_of_frost():
    cid = "DAL_577"

    def twinspell_freezes_then_damages_an_already_frozen_minion():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5771)
        target = e.summon("CS2_182")
        original = play(p, cid, target=target)
        after_first = (target.frozen,target.damage,target.zone.name)
        copy = next((c for c in p.hand if c.id == "DAL_577ts"), None)
        if copy:
            copy.play(target=target)
        observed = f"original={original.zone.name};after_first={after_first};copy={copy.zone.name if copy else None};after_second={(target.frozen,target.damage,target.health,target.zone.name)};hand={[c.id for c in p.hand]}"
        return check(after_first == (True,0,"PLAY") and copy is not None and copy.zone == Zone.GRAVEYARD and target.frozen and target.damage == 2 and target.zone == Zone.PLAY and not any(c.id == "DAL_577ts" for c in p.hand), observed)

    audit(cid, [("twinspell_freeze_then_two_damage_if_already_frozen", "First cast freezes a minion; Twinspell cast on the already Frozen minion deals 2 damage.", twinspell_freezes_then_damages_an_already_frozen_minion, "對5血Yeti先施放 Ray of Frost 检查冻结且0伤，再用生成副本对已冻结目标施放，检查造成2伤并消耗副本。")])


ray_of_frost.card_id = "DAL_577"


def power_of_creation():
    cid = "DAL_578"

    def discovers_six_cost_minion_and_summons_two_copies():
        g, p, e = game(CardClass.MAGE, CardClass.HUNTER, seed=5781)
        spell = play(p, cid)
        offered = [(c.id,c.cost,int(c.type)) for c in p.choice.cards]
        chosen = p.choice.cards[0]
        chosen_id = chosen.id
        chosen_stats = (chosen.atk,chosen.health)
        p.choice.choose(chosen)
        copies = [m for m in p.field if m.id == chosen_id]
        observed = f"spell={spell.zone.name};offered={offered};chosen={chosen_id}/{chosen_stats};copies={[(m.atk,m.health,m.zone.name) for m in copies]};field={[m.id for m in p.field]}"
        return check(len(offered) == 3 and all(cost == 6 and card_type == int(CardType.MINION) for _,cost,card_type in offered) and len(copies) == 2 and all((m.atk,m.health) == chosen_stats and m.zone == Zone.PLAY for m in copies), observed)

    audit(cid, [("discover_six_cost_minion_summons_two_copies", "Discovers a 6-Cost minion and summons two copies of the chosen card.", discovers_six_cost_minion_and_summons_two_copies, "核对三个发现候选均为6费随从，选择一个后检查本体消耗且场上生成两个同ID同身材随从。")])


power_of_creation.card_id = "DAL_578"


def nozari():
    cid = "DAL_581"

    def battlecry_restores_both_heroes_to_full_health():
        g, p, e = game(CardClass.PALADIN, CardClass.HUNTER, seed=5811)
        p.hero.damage = 10; e.hero.damage = 17
        body = play(p, cid)
        observed = f"body={body.zone.name};friendly={(p.hero.health,p.hero.armor)};enemy={(e.hero.health,e.hero.armor)}"
        return check(p.hero.health == 30 and e.hero.health == 30 and body.zone == Zone.PLAY, observed)

    audit(cid, [("battlecry_full_heals_both_heroes", "Battlecry restores both heroes to full Health.", battlecry_restores_both_heroes_to_full_health, "將雙方英雄分別降到20與13血，再打出 Nozari，检查双方均恢复至30血。")])


nozari.card_id = "DAL_581"


def portal_keeper():
    cid = "DAL_582"

    def shuffles_three_portals_that_chain_draw_into_rush_demons():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=5821)
        wisp = p.give(WISP); wisp.shuffle_into_deck()
        body = play(p, cid)
        portals = [c for c in p.deck if c.id == "DAL_582t"]
        p.deck.remove(wisp); p.deck.insert(0, wisp)
        drawn = p.draw()
        demons = [m for m in p.field if m.id == "DAL_582t2"]
        observed = f"body={body.zone.name};portals_before={len(portals)};drawn={drawn.id if drawn else None}/{drawn.zone.name if drawn else None};wisp={wisp.zone.name};deck={[c.id for c in p.deck]};demons={[(m.id,m.atk,m.health,m.rush,m.race) for m in demons]}"
        return check(len(portals) == 3 and drawn is not None and drawn.id == "DAL_582t" and drawn.zone == Zone.GRAVEYARD and wisp.zone == Zone.HAND and not p.deck and len(demons) == 3 and all((m.atk,m.health,m.rush) == (2,2,1) for m in demons), observed)

    audit(cid, [("battlecry_shuffles_three_portals_and_draws_summon_rush_demons", "Battlecry shuffles three Portals into deck; each drawn portal summons a 2/2 Rush Demon.", shuffles_three_portals_that_chain_draw_into_rush_demons, "手牌前置普通 Wisp 作牌库底牌，打出 Keeper 确认3张Portal；实际抽取引发替代抽牌链，消耗三张Portal并召唤三个2/2突袭恶魔，最后抽到Wisp。")])


portal_keeper.card_id = "DAL_582"


def shimmerfly():
    cid = "DAL_587"

    def deathrattle_adds_one_hunter_spell():
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=5871)
        body = play(p, cid)
        body.destroy()
        spells = [c for c in p.hand if c.type == CardType.SPELL and c.card_class == CardClass.HUNTER]
        observed = f"body={body.zone.name};hand={[(c.id,int(c.type),int(c.card_class),c.zone.name) for c in p.hand]};hunter_spells={[c.id for c in spells]}"
        return check(body.zone == Zone.GRAVEYARD and len(spells) == 1 and spells[0].zone == Zone.HAND and len(p.hand) == 1, observed)

    audit(cid, [("deathrattle_adds_random_hunter_spell", "Deathrattle adds one random Hunter spell to hand.", deathrattle_adds_one_hunter_spell, "實際摧毀 Shimmerfly，檢查手牌恰有一張處於手牌區且職業為 Hunter 的法術。")])


shimmerfly.card_id = "DAL_587"


def hunting_party():
    cid = "DAL_589"

    def scenario(with_beasts, seed):
        g, p, e = game(CardClass.HUNTER, CardClass.MAGE, seed=seed)
        if with_beasts:
            p.give("EX1_534"); p.give("EX1_534")
        p.give("CS2_029")
        before_beasts = sum(c.id == "EX1_534" for c in p.hand)
        before_fireball = sum(c.id == "CS2_029" for c in p.hand)
        spell = play(p, cid)
        after_beasts = sum(c.id == "EX1_534" for c in p.hand)
        after_fireball = sum(c.id == "CS2_029" for c in p.hand)
        observed = f"with_beasts={with_beasts};spell={spell.zone.name};before=({before_beasts},{before_fireball});after=({after_beasts},{after_fireball});hand={[c.id for c in p.hand]}"
        return check(after_beasts == before_beasts * 2 and after_fireball == before_fireball, observed)

    audit(cid, [
        ("copies_every_beast_in_hand", "Copies each Beast in hand and leaves non-Beast spells unchanged.", lambda: scenario(True, 5891), "手持两张 Savannah Highmane 野兽及一张 Fireball，施放后野兽牌增至4张，非野兽法术仍1张。"),
        ("no_beast_creates_no_copies", "With no Beast in hand, creates no copies.", lambda: scenario(False, 5892), "无野兽、仅有 Fireball 时施放，确认手牌不变。"),
    ])


hunting_party.card_id = "DAL_589"


AUDITS = [lucentbark, unidentified_contract, marked_shot, arcane_fletcher, rapid_fire,
          oblivitron, nine_lives, unleash_the_beast, vereesa_windrunner, evil_cable_rat,
          evil_concripter, evil_miscreant, hench_clan_burglar, heistbaron_togwaggle,
          arch_villain_rafaam, swampqueen_hagatha, witchs_brew, sludge_slurper,
          arcane_watcher, unseen_saboteur, sunreaver_warmage, potion_vendor,
          barista_lynchen, azerite_elemental, underbelly_ooze, proud_defender,
          big_bad_archmage, chef_nomi, archmage_vargoth, heroic_innkeeper, jumbo_imp,
          portal_overfiend, eccentric_scribe, lightforged_blessing, never_surrender,
          mysterious_blade, commander_rhyssa, khadgar, kirin_tor_tricaster, ray_of_frost,
          power_of_creation, nozari, portal_keeper, shimmerfly, hunting_party]


def main():
    import argparse
    from collections import Counter
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="zero-based index in frozen roster 45:90")
    parser.add_argument("--limit", type=int, default=45)
    args = parser.parse_args()
    assert 0 <= args.start < 45 and 1 <= args.limit <= 45
    selected = AUDITS[args.start:args.start + args.limit]
    statuses = []
    for row, fn in zip(ROSTER[args.start:args.start + args.limit], selected):
        assert row["card_id"] == fn.card_id
        fn()
        statuses.append(next(r["status"] for r in VERDICTS if r["card_id"] == fn.card_id))
    print(f"audited={len(statuses)} statuses={dict(Counter(statuses))}; roster={[r['card_id'] for r in ROSTER[args.start:args.start+len(statuses)]]}")


if __name__ == "__main__":
    main()
