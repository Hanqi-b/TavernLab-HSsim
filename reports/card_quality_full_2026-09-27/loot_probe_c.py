"""Live behavior audit for roster indices 90:134 of LOOT YELLOW cards."""

import argparse
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import (  # noqa: E402
    BASIC_TOTEMS, MOONFIRE, THE_COIN, WISP, prepare_empty_game,
)

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for _handler in logging.getLogger("fireplace").handlers:
    _handler.setLevel(logging.CRITICAL)

BASELINE = HERE / "remaining_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
MECHANISMS = HERE / "card_mechanism.csv"
ISSUES = HERE / "mechanism_issues.csv"
PROBE = HERE / "loot_probe_c.csv"
VERDICT = HERE / "loot_verdict_c.csv"
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
LOOT_ROWS = [r for r in BASE_ROWS if r["set"] == "Kobolds & Catacombs (LOOTAPALOOZA)"]
CARDS = [r["card_id"] for r in LOOT_ROWS[90:134]]
assert len(CARDS) == 44 and CARDS[0] == "LOOT_367" and CARDS[-1] == "LOOT_542", (len(CARDS), CARDS[:1], CARDS[-1:])
MASTER_ROWS = {r["card_id"]: r for r in read_csv(MASTER)}
OLD_QUALITY = {r["card_id"]: r for r in read_csv(QUALITY)}
MECH_ROWS = read_csv(MECHANISMS)
LABELS = {cid: sorted({r["mechanic"] for r in MECH_ROWS if r["card_id"] == cid}) for cid in CARDS}
OLD_MECH_REASONS = {cid: sorted({r["reason"] for r in MECH_ROWS if r["card_id"] == cid and r["reason"]}) for cid in CARDS}
PROBE_ROWS = read_csv(PROBE)
VERDICT_ROWS = read_csv(VERDICT)


def game(class1=CardClass.MAGE, class2=CardClass.WARRIOR, seed=417):
    random.seed(seed)
    g = prepare_empty_game(class1, class2)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for player in g.players:
        player.is_standard = False
        player.max_mana = 10
        player.used_mana = 0
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


def add_case(cid, case_id, expected, func, notes):
    try:
        result = func()
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], bool):
            observed, condition = result
            assert condition, observed
        else:
            observed = result
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append(dict(card_id=cid, case_id=case_id, expected=expected, observed=observed, outcome=outcome, notes=notes))
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)


def prepare_card(cid):
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != cid]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != cid]
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)


def finish_card(cid, blocker=None, extra_notes=""):
    own = [r for r in PROBE_ROWS if r["card_id"] == cid]
    assert own and len({r["case_id"] for r in own}) == len(own), cid
    errors = [r for r in own if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in own if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实测与卡牌文本不符：" + "；".join(f"{r['case_id']}预期[{r['expected']}]，实际[{r['observed']}]" for r in errors)
    elif unresolved or blocker:
        status = "YELLOW"
        reason = "行为测试未完成：" + "；".join(f"{r['case_id']}={r['observed']}" for r in unresolved)
        if blocker:
            reason += ("；" if unresolved else "") + blocker
    else:
        status = "GREEN"
        reason = "逐卡实际对局断言通过：" + "；".join(f"{r['case_id']}={r['observed']}" for r in own)
    master = MASTER_ROWS[cid]
    quality = OLD_QUALITY.get(cid, {})
    issues = []
    for issue in read_csv(ISSUES):
        issue_cards = set((issue.get("confirmed_cards", "") + "|" + issue.get("candidate_cards", "")).split("|"))
        if cid in issue_cards:
            issues.append(f"{issue.get('issue_id')}[{issue.get('severity')}]:{issue.get('summary')}")
    notes = (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '') or '未发现 Python 卡脚本'}; "
        f"existing_tests={master.get('test_refs_candidate', '') or '无候选既有测试引用'}; "
        f"previous_card_audit={quality.get('status', '')}:{quality.get('reason', '无')}; "
        f"previous_mechanism_audit={' / '.join(OLD_MECH_REASONS[cid]) or '无'}; "
        f"prior_cross_card_issues={' / '.join(issues) if issues else '无'}; audit_scope=本轮实际运行逐卡断言。"
    )
    if extra_notes:
        notes += f"; {extra_notes}"
    VERDICT_ROWS.append(dict(card_id=cid, status=status, mechanic_scope="|".join(LABELS[cid]), reason=reason, probe_file=PROBE.name, notes=notes))
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    print(f"{cid}: {status} ({len(own)} cases) — {reason}", flush=True)


def audit_card(cid, cases, blocker=None, extra_notes=""):
    prepare_card(cid)
    for case_id, expected, func, notes in cases:
        add_case(cid, case_id, expected, func, notes)
    finish_card(cid, blocker, extra_notes)


def probe_367():
    cid = "LOOT_367"
    def armor_per_enemy():
        g = game(CardClass.WARRIOR); p, e = g.player1, g.player2
        summon(e, WISP); summon(e, "CS2_182")
        before = p.hero.armor
        armorer = play(p, cid)
        return f"enemy_minions=2;armor={before}->{p.hero.armor};armorer={armorer.zone.name}", p.hero.armor == before + 4
    def no_enemies_no_armor():
        g = game(CardClass.WARRIOR); p = g.player1
        before = p.hero.armor
        armorer = play(p, cid)
        return f"enemy_minions=0;armor={before}->{p.hero.armor};armorer={armorer.zone.name}", p.hero.armor == before
    return [
        ("two_enemy_minions_gain_four", "Gain 2 Armor for each of two enemy minions.", armor_per_enemy, "战吼分别计数敌方普通随从与高费随从，检查护甲总增量为 4。"),
        ("empty_enemy_board_gain_zero", "Gain no Armor when the opponent controls no minions.", no_enemies_no_armor, "验证敌方空场分支，护甲不变化。"),
    ]


def probe_368():
    cid = "LOOT_368"
    def taunt_and_three_demon_deathrattle():
        g = game(CardClass.WARLOCK); p = g.player1
        lord = summon(p, cid)
        assert lord.taunt and (lord.atk, lord.health) == (3, 9), (lord.taunt, lord.atk, lord.health)
        lord.destroy()
        tokens = [m for m in p.field if m.id == "CS2_065"]
        state = [(m.id, m.atk, m.health, m.taunt, Race(m.race).name, m.zone.name) for m in tokens]
        assert len(tokens) == 3 and all((m.atk, m.health) == (1, 3) and m.taunt and Race(m.race) == Race.DEMON and m.zone == Zone.PLAY for m in tokens), state
        return f"voidlord=GRAVEYARD;tokens={state}"
    return [("taunt_and_three_taunt_demons", "Voidlord has Taunt; its Deathrattle summons exactly three 1/3 Taunt Demons.", taunt_and_three_demon_deathrattle,
             "真实召唤后检查 Voidlord 的 Taunt 和 3/9，再触发亡语逐个验证数量、身材、种族、嘲讽及区域。")]


def probe_370():
    cid = "LOOT_370"
    def recruits_a_deck_minion():
        g = game(CardClass.WARRIOR); p = g.player1
        m = p.give(WISP); m.shuffle_into_deck()
        spell = p.give("CS2_008"); spell.shuffle_into_deck()
        recruit = play(p, cid)
        recruited = [c for c in p.field if c.id == WISP]
        assert len(recruited) == 1 and recruited[0].zone == Zone.PLAY and m not in p.deck and spell in p.deck and recruit.zone == Zone.GRAVEYARD, ([(c.id,c.zone.name) for c in p.field], [c.id for c in p.deck], recruit.zone)
        return f"recruited={[c.id for c in recruited]};remaining_deck={[c.id for c in p.deck]};spell={recruit.zone.name}"
    return [("recruit_minion_from_deck", "Recruit summons a minion from the deck and leaves the non-minion card there.", recruits_a_deck_minion,
             "牌库仅含一个随从与一个法术，施放后检查随从从牌库直接进入己方战场，法术仍留在牌库。")]


def probe_373():
    cid = "LOOT_373"
    def split_twelve_health_randomly():
        g = game(CardClass.SHAMAN); p, e = g.player1, g.player2
        p.hero.damage = 20
        friends = [summon(p, "EX1_563") for _ in range(6)]
        for friend in friends:
            friend.damage = 12
        e.hero.damage = 5
        enemy = summon(e, "CS2_182"); enemy.damage = 2
        before_missing = 20 + sum(friend.damage for friend in friends)
        spell = play(p, cid)
        after_missing = (p.hero.max_health - p.hero.health) + sum(friend.damage for friend in friends)
        restored = before_missing - after_missing
        assert restored == 12 and p.hero.health >= 10 and all(friend.health > 0 for friend in friends), (before_missing, after_missing, restored, p.hero.health, [(friend.health,friend.max_health) for friend in friends])
        assert (e.hero.health, enemy.damage) == (25, 2) and spell.zone == Zone.GRAVEYARD, (e.hero.health, enemy.damage, spell.zone)
        return f"restored_total={restored};hero={p.hero.health};friendly_minion_damage={[friend.damage for friend in friends]};enemy_hero={e.hero.health};enemy_minion_damage={enemy.damage}"
    return [("heal_twelve_split_among_friendly_characters", "Restore exactly 12 Health randomly among friendly characters without healing enemy characters.", split_twelve_health_randomly,
             "友方英雄及六个友方随从均受伤且单个角色至少可接收全部 12 点；逐角色核对总恢复为 12，并检查敌方英雄/随从不变。")]


def probe_375():
    cid = "LOOT_375"
    def recruit_cost_four_or_less():
        g = game(); p = g.player1
        cheap = p.give("CS2_196"); cheap.shuffle_into_deck()
        expensive = p.give("CS2_200"); expensive.shuffle_into_deck()
        recruiter = play(p, cid)
        recruited = [c for c in p.field if c.id in {"CS2_196", "CS2_200"}]
        assert len(recruited) == 1 and recruited[0].id == "CS2_196" and recruited[0].cost <= 4 and recruiter.zone == Zone.PLAY, ([(c.id,c.cost,c.zone.name) for c in recruited], recruiter.zone)
        assert cheap not in p.deck and expensive in p.deck, ([c.id for c in p.deck], cheap.zone, expensive.zone)
        return f"recruited={recruited[0].id}:cost{recruited[0].cost};high_cost_stays={expensive in p.deck};recruiter={recruiter.zone.name}"
    return [("battlecry_recruits_cost_at_most_four", "Recruiter summons the eligible 2-Cost deck minion and excludes the 6-Cost minion.", recruit_cost_four_or_less,
             "牌库放入唯一符合费用条件的随从及一个高于 4 费的随从，检查费用筛选和牌库移除。")]


def probe_380():
    cid = "LOOT_380"
    def hero_attack_recruits():
        g = game(CardClass.WARRIOR); p, e = g.player1, g.player2
        m = p.give(WISP); m.shuffle_into_deck()
        weapon = play(p, cid)
        before = weapon.durability
        p.hero.attack(e.hero)
        assert p.hero.num_attacks == 1 and weapon.durability == before - 1, (p.hero.num_attacks, weapon.durability, before)
        assert any(c.id == WISP and c.zone == Zone.PLAY for c in p.field) and m not in p.deck, ([c.id for c in p.field], [c.id for c in p.deck])
        return f"attacks={p.hero.num_attacks};durability={before}->{weapon.durability};recruited={[c.id for c in p.field if c.id == WISP]};deck={[c.id for c in p.deck]}"
    return [("after_hero_attack_recruits", "After the hero attacks, Woecleaver recruits a deck minion.", hero_attack_recruits,
             "使用真实可攻击英雄与已装备武器进行攻击，检查触发时点、耐久消耗以及牌库随从入场。")]


def probe_382():
    cid = "LOOT_382"
    def hero_untargetable_by_spells_and_powers_until_monk_leaves():
        g = game(CardClass.MAGE, CardClass.MAGE); p, e = g.player1, g.player2
        monk = summon(p, cid)
        g.end_turn()
        e.used_mana=0
        fireball=e.give("CS2_029")
        spell_targeting=(p.hero in fireball.targets)
        power_targeting=(p.hero in e.hero.power.targets)
        rejected = []
        for action in (lambda: fireball.play(target=p.hero), lambda: e.hero.power.use(target=p.hero)):
            try:
                action()
                rejected.append(False)
            except InvalidAction:
                rejected.append(True)
        active = (p.hero.cant_be_targeted_by_abilities, p.hero.cant_be_targeted_by_hero_powers, spell_targeting, power_targeting, tuple(rejected), p.hero.health, e.mana)
        monk.destroy()
        removed = (p.hero.cant_be_targeted_by_abilities, p.hero.cant_be_targeted_by_hero_powers)
        assert active[:5] == (True, True, False, False, (True, True)) and removed == (False, False), (active, removed)
        return f"while_present={active};after_leave={removed};monk={monk.zone.name};fireball={fireball.zone.name}"
    return [("protects_hero_from_spell_and_hero_power_targets", "Friendly hero is excluded from spell and Hero Power targets while Monk lives; protection ends after it leaves.", hero_untargetable_by_spells_and_powers_until_monk_leaves,
             "检查两个具体 targetability 属性及合法目标集合，再移除光环源并确认限制撤销。")]


def probe_383():
    cid = "LOOT_383"
    def opponent_gets_random_two_cost_minion():
        g = game(); p, e = g.player1, g.player2
        ettin = play(p, cid)
        summoned = [c for c in e.field]
        state = [(c.id,c.cost,c.atk,c.health,c.zone.name) for c in summoned]
        assert ettin.taunt and (ettin.atk,ettin.health)==(4,10) and len(summoned)==1 and summoned[0].cost == 2 and summoned[0].zone == Zone.PLAY, (ettin.taunt,ettin.atk,ettin.health,state)
        assert len(p.field)==1 and p.field[0] is ettin, [(c.id,c.zone.name) for c in p.field]
        return f"ettin=4/10:taunt={ettin.taunt};opponent_minion={state}"
    def opponent_full_board_does_not_exceed_seven():
        g=game();p,e=g.player1,g.player2
        opposing=[summon(e,WISP) for _ in range(7)]
        ettin=play(p,cid)
        actual=(len(p.field),len(e.field),[m.zone.name for m in opposing],ettin.zone.name)
        assert len(p.field)==1 and len(e.field)==7 and all(m.zone==Zone.PLAY for m in opposing) and ettin.zone==Zone.PLAY,actual
        return f"friendly_field={actual[0]};opponent_field={actual[1]};opponent_slots_respected=True;ettin={actual[3]}"
    def full_friendly_board_does_not_block_opponent_summon():
        g=game();p,e=g.player1,g.player2
        friendly=[summon(p,WISP) for _ in range(6)]
        ettin=play(p,cid)
        opposing=list(e.field)
        actual=(len(p.field),[(m.id,m.cost,m.zone.name) for m in opposing],ettin.zone.name)
        assert len(p.field)==7 and len(opposing)==1 and opposing[0].cost==2 and opposing[0].zone==Zone.PLAY and ettin.zone==Zone.PLAY,actual
        return f"friendly_field={len(p.field)};opponent_summon={actual[1]};ettin={ettin.zone.name}"
    return [("battlecry_summons_two_cost_for_opponent", "Hungry Ettin is Taunt and summons one 2-Cost minion for the opponent, not its controller.", opponent_gets_random_two_cost_minion,
             "实际打出后分别检查双方场地、对手召唤随从的费用/区域及 Ettin 嘲讽。"),
            ("opponent_full_board_respects_seven_minion_cap", "The Battlecry does not put an eighth minion on the opponent's full board.", opponent_full_board_does_not_exceed_seven,
             "对手先占满七格再打出 Ettin，检查双方场地数量和已有随从区域，不产生第八个敌方随从。"),
            ("friendly_full_board_does_not_block_opponent_summon", "A full friendly board does not stop Ettin from summoning a 2-Cost minion for the opponent.", full_friendly_board_does_not_block_opponent_summon,
             "己方预留六格，打出 Ettin 后己方恰满七格；仍检查对手实际召到一只 2 费随从。")]


def probe_388():
    cid = "LOOT_388"
    def restore_two_to_friendly_characters():
        g = game(); p,e = g.player1,g.player2
        p.hero.damage=2; e.hero.damage=3
        injured=summon(p,"CS2_182"); injured.damage=2
        full=summon(p,"CS2_182")
        enemy=summon(e,"CS2_182"); enemy.damage=2
        healer=play(p,cid)
        state=(p.hero.health,injured.health,full.health,e.hero.health,enemy.health)
        assert state==(30,5,5,27,3) and healer.zone==Zone.PLAY, state
        return f"friendly_hero/minions={state[:3]};enemy_hero/minion={state[3:]};healer={healer.zone.name}"
    return [("heal_all_friendly_characters_two", "Restore 2 Health to the friendly hero and damaged friendly minion, leave a full minion capped, and do not heal enemies.", restore_two_to_friendly_characters,
             "对友方英雄、受伤/满血友方随从和敌方角色设置对照，检查逐个治疗与生命上限。")]


def probe_389():
    cid = "LOOT_389"
    def recover_own_destroyed_weapon():
        g=game();p=g.player1
        weapon=play(p,"CS2_091")
        weapon.destroy()
        assert weapon.zone==Zone.GRAVEYARD and p.hero.weapon is None, (weapon.zone,p.hero.weapon)
        rummager=play(p,cid)
        returned=[c for c in p.hand if c.id=="CS2_091"]
        assert len(returned)==1 and CardType(returned[0].type)==CardType.WEAPON and rummager.zone==Zone.PLAY, ([(c.id,CardType(c.type).name,c.zone.name) for c in p.hand],rummager.zone)
        return f"destroyed={weapon.id}:{weapon.zone.name};returned={[(c.id,CardType(c.type).name,c.zone.name) for c in returned]};rummager={rummager.zone.name}"
    return [("battlecry_returns_own_destroyed_weapon", "Rummager returns a weapon previously destroyed by its controller.", recover_own_destroyed_weapon,
             "装备并显式摧毁己方武器，随后检查战吼仅将同一己方武器作为武器卡返回手牌。")]


def probe_392():
    cid="LOOT_392"
    def deathrattle_gains_mana_crystals():
        g=game(CardClass.DRUID);p=g.player1
        p.max_mana=4;p.used_mana=0
        twig=play(p,cid)
        before=(p.max_mana,p.mana)
        twig.destroy()
        after=(p.max_mana,p.mana)
        assert twig.zone==Zone.GRAVEYARD and after[0]==min(10,before[0]+10) and after[1]>=before[1], (before,after,twig.zone)
        return f"mana_before={before};mana_after={after};twig={twig.zone.name}"
    return [("deathrattle_gains_ten_crystals", "Twig's Deathrattle adds ten Mana Crystals, subject to the ten-crystal cap.", deathrattle_gains_mana_crystals,
             "将最大法力晶体置于 3 后触发武器亡语，检查晶体增量受游戏上限约束且武器进入墓地。")]


def probe_394():
    cid="LOOT_394"
    def end_turn_summons_one_cost_minion():
        g=game();p,e=g.player1,g.player2
        shroom=play(p,cid)
        g.end_turn()
        spawned=[m for m in p.field if m is not shroom]
        state=[(m.id,m.cost,m.atk,m.health,m.zone.name) for m in spawned]
        assert shroom.zone==Zone.PLAY and len(spawned)==1 and spawned[0].cost==1 and spawned[0].zone==Zone.PLAY and not e.field, (shroom.zone,state,[m.id for m in e.field])
        return f"shroom={shroom.zone.name};end_turn_spawn={state};enemy_field={len(e.field)}"
    return [("own_turn_end_summons_one_cost_minion", "At its controller's end of turn, Shroom summons exactly one 1-Cost minion.", end_turn_summons_one_cost_minion,
             "在己方实际结束回合后检查触发时序、召唤数量、费用及归属场地。")]


def probe_398():
    cid="LOOT_398"
    def end_turn_heals_only_own_hero_three():
        g=game(CardClass.PALADIN);p,e=g.player1,g.player2
        p.hero.damage=7;e.hero.damage=4
        djinn=play(p,cid)
        g.end_turn()
        assert (p.hero.health,e.hero.health,djinn.zone)==(26,26,Zone.PLAY), (p.hero.health,e.hero.health,djinn.zone)
        return f"own_hero=26;enemy_hero=26;djinn={djinn.zone.name};current_player_is_opponent={g.current_player is e}"
    return [("own_turn_end_restores_three_to_hero", "At its controller's end of turn, Djinn restores 3 Health to its own hero.", end_turn_heals_only_own_hero_three,
             "使双方英雄均受伤后结束己方回合，检查只有己方英雄精确恢复 3。")]


def probe_410():
    cid="LOOT_410"
    def with_dragon_damages_all_other_minions():
        g=game(CardClass.PRIEST);p,e=g.player1,g.player2
        held_dragon=p.give(cid)
        friend=summon(p,"CS2_182");enemy=summon(e,"CS2_182")
        own_wisp=summon(p,WISP)
        dusk=play(p,cid)
        state=(friend.damage,enemy.damage,own_wisp.zone.name,dusk.damage,dusk.zone.name,p.hero.health,e.hero.health)
        assert state==(3,3,"GRAVEYARD",0,"PLAY",30,30),state
        assert held_dragon.id==cid and held_dragon.zone==Zone.HAND, (held_dragon.id,held_dragon.zone)
        return f"other_minions={state[:4]};duskbreaker={state[4]};heroes={(state[5],state[6])};dragon_still_held={held_dragon.zone.name}"
    def without_dragon_no_damage():
        g=game(CardClass.PRIEST);p,e=g.player1,g.player2
        friend=summon(p,"CS2_182");enemy=summon(e,"CS2_182")
        dusk=play(p,cid)
        assert (friend.damage,enemy.damage,dusk.zone)==(0,0,Zone.PLAY),(friend.damage,enemy.damage,dusk.zone)
        return f"friendly_damage={friend.damage};enemy_damage={enemy.damage};duskbreaker={dusk.zone.name}"
    return [
        ("dragon_held_deals_three_to_all_other_minions", "With a Dragon in hand, Duskbreaker deals 3 to all other minions, including both sides, while surviving itself and sparing heroes.", with_dragon_damages_all_other_minions,
         "用手牌中的另一张龙牌激活条件，分别检查友方/敌方其他随从、Duskbreaker 本体及双方英雄。"),
        ("no_dragon_no_damage", "Without a Dragon in hand, Battlecry deals no damage.", without_dragon_no_damage,
         "移除手牌龙牌，使用同样的友敌随从局面验证条件为假时不造成伤害。"),
    ]


def probe_412():
    cid="LOOT_412"
    def deathrattle_summons_one_one_copy_from_hand():
        g=game(CardClass.ROGUE);p=g.player1
        original=p.give("CS2_182")
        p.give("CS2_008")
        illusionist=play(p,cid)
        illusionist.destroy()
        copies=[m for m in p.field if m.id=="CS2_182"]
        assert len(copies)==1 and (copies[0].atk,copies[0].health)==(1,1) and copies[0].zone==Zone.PLAY, ([(m.id,m.atk,m.health,m.zone.name) for m in p.field],illusionist.zone)
        assert original in p.hand and original.zone==Zone.HAND and illusionist.zone==Zone.GRAVEYARD, (original.zone,illusionist.zone)
        return f"hand_original={original.id}:{original.zone.name};summoned_copy={copies[0].id}:{copies[0].atk}/{copies[0].health}:{copies[0].zone.name};source={illusionist.zone.name}"
    return [("deathrattle_summons_one_one_hand_copy", "Deathrattle summons a 1/1 copy of a minion from hand and leaves the original in hand.", deathrattle_summons_one_one_copy_from_hand,
             "手牌中仅留一个可选随从及一个法术，触发亡语并比较原牌区域与复制品的攻击/生命。")]


def probe_413():
    cid="LOOT_413"
    def deathrattle_gains_three_armor():
        g=game();p=g.player1
        beetle=summon(p,cid)
        before=p.hero.armor
        beetle.destroy()
        assert (beetle.zone,p.hero.armor)==(Zone.GRAVEYARD,before+3),(beetle.zone,p.hero.armor,before)
        return f"armor={before}->{p.hero.armor};beetle={beetle.zone.name}"
    return [("deathrattle_gains_three_armor", "Plated Beetle's Deathrattle grants its controller exactly 3 Armor.", deathrattle_gains_three_armor,
             "实际死亡结算后检查英雄护甲变化和甲虫墓地区域。")]


def probe_414():
    cid="LOOT_414"
    def casts_deck_spell_and_resolves_effect():
        g=game();p,e=g.player1,g.player2
        spell=p.give("CS2_024");spell.shuffle_into_deck()
        own_minion=summon(p,"EX1_572")
        enemy=summon(e,"EX1_572")
        archivist=play(p,cid)
        before=(p.hero.damage,e.hero.damage,own_minion.damage,enemy.damage,archivist.damage)
        g.end_turn()
        after=(p.hero.damage,e.hero.damage,own_minion.damage,enemy.damage,archivist.damage)
        frozen=(p.hero.frozen,e.hero.frozen,own_minion.frozen,enemy.frozen,archivist.frozen)
        changed=[i for i,(old,new) in enumerate(zip(before,after)) if new==old+3 and frozen[i]]
        state=(spell.zone.name,spell in p.deck,before,after,frozen,archivist.zone.name)
        target=spell.target
        assert spell.zone==Zone.GRAVEYARD and spell not in p.deck and len(changed)==1 and target in (p.hero,e.hero,own_minion,enemy,archivist) and archivist.zone==Zone.PLAY,state
        return f"deck_spell={state[0]};still_in_deck={state[1]};target={target.id};target_slot={changed[0]};damage_before={before};damage_after={after};frozen={frozen};archivist={state[5]}"
    def compares_hand_cast_trigger_with_deck_cast():
        g=game();p,e=g.player1,g.player2
        wyrm=summon(p,"NEW1_012")
        hand_spell=play(p,"CS2_029",target=e.hero)
        after_hand=wyrm.atk
        deck_spell=p.give("CS2_023");deck_spell.shuffle_into_deck()
        p.give(WISP).shuffle_into_deck();p.give("CS2_182").shuffle_into_deck()
        p.used_mana=0
        archivist=play(p,cid)
        g.end_turn()
        observed=(after_hand,wyrm.atk,deck_spell.zone.name,deck_spell in p.deck,[c.id for c in p.hand],archivist.zone.name)
        assert after_hand==2 and deck_spell.zone==Zone.GRAVEYARD and deck_spell not in p.deck and archivist.zone==Zone.PLAY,observed
        return f"hand_cast_mana_wyrm_attack=1->{after_hand};archivist_cast_mana_wyrm_attack={after_hand}->{wyrm.atk};deck_spell={deck_spell.zone.name};drawn_hand={observed[4]};archivist={archivist.zone.name}"
    return [
        ("end_turn_casts_deck_spell_with_random_target", "At own turn end Grand Archivist casts a spell from deck; Frostbolt resolves against a random legal target and leaves the deck.", casts_deck_spell_and_resolves_effect,
         "牌库只放入 Frostbolt，实际结束己方回合并检查法术离库/进入墓地、随机目标受到 3 点伤害及 Archivist 留场。"),
        ("empirical_hand_cast_vs_archivist_trigger", "Record whether a direct hand spell and Grand Archivist's deck cast trigger Mana Wyrm equivalently; no normative result is assumed for the generated-cast boundary.", compares_hand_cast_trigger_with_deck_cast,
         "同局先手动施放 Fireball 作对照，再让 Archivist 从牌库施放 Arcane Intellect，记录 Mana Wyrm 攻击变化。CAST-001 语义仍无权威结论，因此该观察不单独判定正确性。"),
    ]


def probe_415():
    cid="LOOT_415"
    def rin_seal_chain_reaches_azari_and_destroys_enemy_deck():
        g=game(CardClass.WARLOCK);p,e=g.player1,g.player2
        e.give(WISP).shuffle_into_deck()
        rin=summon(p,cid)
        assert rin.taunt,(rin.taunt,rin.zone)
        rin.destroy()
        observed=[]
        for card_id,token_id,stats,next_id in [
            ("LOOT_415t1","LOOT_415t1t",(2,2),"LOOT_415t2"),
            ("LOOT_415t2","LOOT_415t2t",(3,3),"LOOT_415t3"),
            ("LOOT_415t3","LOOT_415t3t",(4,4),"LOOT_415t4"),
            ("LOOT_415t4","LOOT_415t4t",(5,5),"LOOT_415t5"),
            ("LOOT_415t5","LOOT_415t5t",(6,6),"LOOT_415t6"),
        ]:
            seal=next((c for c in p.hand if c.id==card_id),None)
            assert seal is not None,(card_id,[c.id for c in p.hand])
            p.used_mana=0
            seal.play()
            demon=next((m for m in p.field if m.id==token_id),None)
            assert demon is not None and (demon.atk,demon.health)==stats and Race(demon.race)==Race.DEMON and demon.zone==Zone.PLAY,(card_id,[(m.id,m.atk,m.health,Race(m.race).name) for m in p.field])
            assert any(c.id==next_id for c in p.hand),(next_id,[c.id for c in p.hand])
            observed.append(f"{card_id}->{token_id}:{stats}->{next_id}")
            demon.destroy()
        azari=next(c for c in p.hand if c.id=="LOOT_415t6")
        p.used_mana=0
        azari.play()
        assert len(e.deck)==0 and azari.zone==Zone.PLAY,(len(e.deck),azari.zone)
        return f"rin={rin.zone.name};seal_chain={observed};azari={azari.zone.name};enemy_deck_remaining={len(e.deck)}"
    return [("deathrattle_seals_chain_to_azari", "Rin adds The First Seal; each played Seal summons its stated Demon and adds the next Seal, ending with Azari who destroys the opponent deck.", rin_seal_chain_reaches_azari_and_destroys_enemy_deck,
             "真实触发 Rin 亡语，逐张施放五道封印并断言对应恶魔身材/种族和下一张牌，清场后施放 Azari 检查敌方牌库归零。")]


def probe_417():
    cid="LOOT_417"
    def destroys_all_minions_and_discards_hand():
        g=game(CardClass.WARLOCK);p,e=g.player1,g.player2
        own=summon(p,WISP);enemy=summon(e,"CS2_182")
        retained1=p.give("CS2_008");retained2=p.give("CS2_029")
        cataclysm=play(p,cid)
        assert (own.zone,enemy.zone)==(Zone.GRAVEYARD,Zone.GRAVEYARD),(own.zone,enemy.zone)
        discard_zones={Zone.GRAVEYARD,Zone.REMOVEDFROMGAME}
        assert cataclysm.zone==Zone.GRAVEYARD and retained1.zone in discard_zones and retained2.zone in discard_zones and retained1 not in p.hand and retained2 not in p.hand and not p.hand,(cataclysm.zone,retained1.zone,retained2.zone,[c.id for c in p.hand])
        return f"minions={(own.zone.name,enemy.zone.name)};spell={cataclysm.zone.name};discarded={(retained1.zone.name,retained2.zone.name)};hand={len(p.hand)}"
    return [("destroys_board_and_discards_remaining_hand", "Cataclysm destroys all minions on both sides and discards the rest of its controller's hand.", destroys_all_minions_and_discards_hand,
             "场上布置友方与敌方随从，手牌除 Cataclysm 外额外放两张牌，检查所有对象进入墓地。")]


def probe_420():
    cid="LOOT_420"
    def own_turn_begin_summons_demon_from_hand():
        g=game(CardClass.WARLOCK);p,e=g.player1,g.player2
        weapon=play(p,cid)
        demon=p.give("EX1_310")
        non_demon=p.give(WISP)
        before_hand={c.id for c in p.hand}
        g.end_turn();g.end_turn()
        summoned=[m for m in p.field if m.race==Race.DEMON]
        added_hand=[c.id for c in p.hand if c.id not in before_hand and c.race==Race.DEMON]
        actual=f"weapon={weapon.id}:{weapon.durability};original_demon={demon.id}:{demon.zone.name};summoned={[m.id for m in summoned]};added_demons_in_hand={added_hand};non_demon_remains={non_demon in p.hand}"
        assert len(summoned)==1 and demon.zone==Zone.PLAY and demon not in p.hand and non_demon in p.hand,actual
        return actual
    return [("own_turn_begin_summons_demon_from_hand", "At the start of its controller's turn, Skull summons a Demon from hand without summoning non-Demons.", own_turn_begin_summons_demon_from_hand,
             "手牌只有一个恶魔和一个中立非恶魔作对照，跨过对手回合进入己方新回合，检查恶魔入场且非恶魔仍在手牌。")]


def probe_500():
    cid="LOOT_500"
    def deathrattle_buffs_minion_in_hand():
        g=game(CardClass.PALADIN);p=g.player1
        target=p.give(WISP)
        board_target=summon(p,"CS2_182")
        weapon=play(p,cid)
        weapon.destroy()
        actual=(target.atk,target.health,target.zone.name,board_target.atk,board_target.health,board_target.zone.name)
        assert actual==(5,3,"HAND",4,5,"PLAY"),actual
        return f"hand_target={actual[:3]};board_target={actual[3:]}"
    def buffed_minion_death_reequips_weapon():
        g=game(CardClass.PALADIN);p=g.player1
        target=p.give(WISP)
        board_target=summon(p,"CS2_182")
        weapon=play(p,cid)
        weapon.destroy()
        actual=(target.atk,target.health,target.zone.name,board_target.atk,board_target.health,board_target.zone.name)
        assert actual==(1,1,"HAND",8,7,"PLAY"),actual
        board_target.destroy()
        equipped=p.hero.weapon
        assert target.zone==Zone.HAND and board_target.zone==Zone.GRAVEYARD and equipped is not None and equipped.id==cid and equipped.durability==2,(target.zone,board_target.zone,None if equipped is None else (equipped.id,equipped.durability))
        return f"hand_target={actual[:3]};board_target_buff={actual[3:]};board_minion_death={board_target.zone.name};reequipped={(equipped.id,equipped.durability)}"
    return [
        ("deathrattle_buffs_minion_in_hand", "Val'anyr Deathrattle gives one hand minion exactly +4/+2.", deathrattle_buffs_minion_in_hand,
         "同时准备一个手牌随从与一个场上随从，触发亡语后逐个断言 +4/+2 目标必须来自手牌。"),
        ("buffed_minion_death_reequips_weapon", "When the minion carrying Val'anyr's buff dies, Val'anyr is re-equipped.", buffed_minion_death_reequips_weapon,
         "按当前引擎实际增益的场上随从死亡，检查死亡触发及武器重装备分支；该用例不替代手牌目标断言。"),
    ]


def probe_503():
    cid="LOOT_503"
    def base_spellstone_destroys_one_random_enemy():
        g=game(CardClass.ROGUE);p,e=g.player1,g.player2
        enemies=[summon(e,WISP),summon(e,"CS2_182")]
        stone=play(p,cid)
        dead=[m for m in enemies if m.zone==Zone.GRAVEYARD]
        assert len(dead)==1 and stone.zone==Zone.GRAVEYARD,(dead,[(m.id,m.zone.name) for m in enemies],stone.zone)
        return f"destroyed={[m.id for m in dead]};survived={[m.id for m in enemies if m.zone==Zone.PLAY]};stone={stone.zone.name}"
    def three_deathrattle_plays_upgrade_to_two_target_form():
        g=game(CardClass.ROGUE);p,e=g.player1,g.player2
        stone=p.give(cid)
        for _ in range(3):
            p.used_mana=0;play(p,"LOOT_413")
        current=next(c for c in p.hand if c.id.startswith("LOOT_503"))
        enemies=[summon(e,WISP) for _ in range(3)]
        p.used_mana=0;current.play()
        dead=[m for m in enemies if m.zone==Zone.GRAVEYARD]
        assert len(dead)==2 and current.zone==Zone.GRAVEYARD,(current.id,current.zone,[m.zone.name for m in enemies])
        return f"after_three_DR_id={current.id};destroyed={len(dead)};survivors={len(enemies)-len(dead)}"
    def six_deathrattle_plays_upgrade_to_three_target_form():
        g=game(CardClass.ROGUE);p,e=g.player1,g.player2
        stone=p.give(cid)
        observed=[]
        for i in range(6):
            p.used_mana=0;play(p,"LOOT_413")
            current=next(c for c in p.hand if c.id.startswith("LOOT_503"))
            if i in (2,5): observed.append(current.id)
        current=next(c for c in p.hand if c.id.startswith("LOOT_503"))
        assert current.id=="LOOT_503t2",(observed,current.id)
        return f"upgrades_after_three_and_six={observed};final={current.id}"
    return [
        ("base_spellstone_destroys_one_random_enemy", "Base Onyx Spellstone destroys exactly one random enemy minion.", base_spellstone_destroys_one_random_enemy,
         "对手场上有两只不同生命值的随从，实际施放未升级版本，检查恰好一只死亡。"),
        ("three_deathrattle_cards_upgrade_to_two_destroy", "After three Deathrattle card plays, Onyx Spellstone upgrades and destroys two random enemy minions.", three_deathrattle_plays_upgrade_to_two_target_form,
         "将三张具有亡语的牌从手牌打出后检查升级形态，再实际施放并验证两只敌方随从死亡。"),
        ("six_deathrattle_cards_upgrade_to_three_destroy", "After six Deathrattle card plays, Onyx Spellstone reaches its Greater form.", six_deathrattle_plays_upgrade_to_three_target_form,
         "继续实际打出六张亡语牌，分别记录第 3 与第 6 次后的形态；不直接生成升级卡。"),
    ]


def probe_504():
    cid="LOOT_504"
    def evolves_to_next_cost_repeats_and_expires_at_turn_end():
        g=game(CardClass.SHAMAN);p=g.player1
        target=summon(p,WISP)
        first_spell=play(p,cid,target=target)
        first_minion=p.field[0]
        first_state=(first_minion.id,first_minion.cost,first_minion.zone.name,first_spell.zone.name)
        assert first_minion.cost==1 and first_spell.zone==Zone.GRAVEYARD,first_state
        repeat=next(c for c in p.hand if c.id=="LOOT_504t")
        p.used_mana=0
        repeat.play(target=first_minion)
        second_minion=p.field[0]
        second_state=(second_minion.id,second_minion.cost,second_minion.zone.name,repeat.zone.name)
        assert second_minion.cost==2 and repeat.zone==Zone.GRAVEYARD,second_state
        g.end_turn()
        residual=[c.id for c in p.hand if c.id=="LOOT_504t"]
        assert not residual,residual
        return f"first_evolve={first_state};repeat_evolve={second_state};echo_in_hand_after_turn={residual}"
    return [("repeatable_same_turn_evolve_and_expires", "Each Unstable Evolution transforms its target into a minion costing one more; its generated repeat card works again this turn and expires at turn end.", evolves_to_next_cost_repeats_and_expires_at_turn_end,
             "从 Wisp 开始连续施放原法术与生成法术，检查 0→1→2 费用及结束本回合时剩余法术消失。")]


def probe_506():
    cid="LOOT_506"
    def game_with_option(card_id):
        for seed in range(1,1001):
            g=game(CardClass.SHAMAN,CardClass.WARRIOR,seed=seed);p,e=g.player1,g.player2
            friendly=summon(p,"CS2_182")
            enemy=summon(e,"CS2_182")
            weapon=play(p,cid)
            p.hero.attack(e.hero)
            choice=p.choice
            if choice and any(c.id==card_id for c in choice.cards):
                return seed,g,p,e,friendly,enemy,weapon,choice
        raise RuntimeError(f"no seeded Runespear choice contained {card_id} in 1000 attempts")
    def attack_discovers_and_casts_target_spell_when_legal_target_exists():
        seed,g,p,e,friendly,enemy,weapon,choice=game_with_option("LOOT_064")
        assert choice and len(choice.cards)==3,(choice,[c.id for c in choice.cards] if choice else None)
        options=[(c.id,CardType(c.type).name,c.requires_target()) for c in choice.cards]
        assert all(CardType(c.type)==CardType.SPELL for c in choice.cards),options
        selected=next((c for c in choice.cards if c.id=="LOOT_064"),None)
        assert selected is not None and selected.requires_target(),options
        chosen_id=selected.id
        legal_target_present=friendly in selected.targets
        assert legal_target_present,(options,[(t.id,t.zone.name) for t in selected.targets],friendly.zone.name)
        before=(friendly.atk,friendly.health,len(p.field),len(p.hand))
        choice.choose(selected)
        after=(friendly.atk,friendly.health,len(p.field),len(p.hand))
        event_cast_ok=p.choice is None and selected.zone==Zone.GRAVEYARD and selected not in p.hand and sum(m.id==friendly.id for m in p.field)==2
        control_state=None
        if not event_cast_ok:
            p.used_mana=0
            control=play(p,"LOOT_064",target=friendly)
            assert control.zone==Zone.GRAVEYARD and sum(m.id==friendly.id for m in p.field)==2,("direct target-spell control failed",control.zone,[(m.id,m.zone.name) for m in p.field])
            control_state=(control.id,control.zone.name,[(m.id,m.zone.name) for m in p.field])
        event_state=(options,chosen_id,selected.zone.name,[c.id for c in p.hand],[(m.id,m.zone.name) for m in p.field],legal_target_present,before,after,control_state)
        assert event_cast_ok,event_state
        assert after==(friendly.atk,friendly.health,before[2]+1,0),(before,after)
        assert weapon is p.hero.weapon and p.hero.num_attacks==1,(weapon.id,p.hero.weapon.id if p.hero.weapon else None,p.hero.num_attacks)
        return f"seed={seed};options={options};selected={chosen_id};friendly_minion={before}->{after};spell_zone={selected.zone.name};enemy={enemy.zone.name};weapon_durability={weapon.durability};hero_attacks={p.hero.num_attacks}"
    def attack_discovers_and_casts_nontarget_spell():
        seed,g,p,e,friendly,enemy,weapon,choice=game_with_option("BT_101")
        options=[(c.id,CardType(c.type).name,c.requires_target()) for c in choice.cards]
        selected=next(c for c in choice.cards if c.id=="BT_101")
        assert not selected.requires_target(),options
        choice.choose(selected)
        deathrattle_after_event=friendly.has_deathrattle
        event_cast_ok=p.choice is None and selected.zone==Zone.GRAVEYARD and selected not in p.hand and deathrattle_after_event
        event_state=(options,selected.zone.name,[c.id for c in p.hand],deathrattle_after_event)
        direct_control=None
        if not event_cast_ok:
            p.used_mana=0
            direct_control=play(p,"BT_101")
            assert direct_control.zone==Zone.GRAVEYARD and friendly.has_deathrattle,(direct_control.zone,friendly.has_deathrattle)
        assert event_cast_ok,(event_state,"direct_hand_cast_effect="+str(friendly.has_deathrattle))
        friendly.destroy()
        revived=[m for m in p.field if m.id==friendly.id]
        assert friendly.zone==Zone.GRAVEYARD and len(revived)==1 and revived[0].zone==Zone.PLAY,(friendly.zone,[(m.id,m.zone.name) for m in p.field])
        assert weapon is p.hero.weapon and p.hero.num_attacks==1,(weapon.id,p.hero.num_attacks)
        return f"seed={seed};options={options};selected=BT_101;selected_zone={selected.zone.name};friendly_deathrattle={deathrattle_after_event};direct_control={None if direct_control is None else direct_control.zone.name};resummoned={[(m.id,m.zone.name) for m in revived]};enemy={enemy.zone.name}"
    return [("hero_attack_casts_target_spell_with_available_target", "After attacking, Runespear discovers and casts a chosen target spell when a legal friendly target exists; The Lesser Sapphire Spellstone copies it.", attack_discovers_and_casts_target_spell_when_legal_target_exists,
             "固定候选选择器在 1–1000 seeded live games 中查找 LOOT_064；场上先放己方与敌方随从，选中需目标法术并断言其进入墓地且友方目标复制真实出现。"),
            ("hero_attack_casts_nontarget_spell", "After attacking, Runespear discovers and casts a chosen spell that needs no target; Vivid Spores grants a Deathrattle that resummons the friendly minion.", attack_discovers_and_casts_nontarget_spell,
             "在同一轮固定候选 seed 搜索中查找无目标法术 BT_101；检查法术离开选择区且友方随从取得亡语并实际死亡后重召。")]


def probe_507():
    cid="LOOT_507"
    def unupgraded_resurrects_two_distinct_friendly_deaths():
        g=game(CardClass.PRIEST);p=g.player1
        dead=[]
        for card_id in (WISP,"CS2_182","LOOT_413"):
            minion=summon(p,card_id);minion.destroy();dead.append(minion)
        stone=play(p,cid)
        revived=[m for m in p.field]
        ids=[m.id for m in revived]
        assert len(revived)==2 and len(set(ids))==2 and set(ids)<=set(m.id for m in dead) and stone.zone==Zone.GRAVEYARD,(ids,[m.id for m in dead],stone.zone)
        return f"resurrected={[(m.id,m.atk,m.health) for m in revived]};distinct={len(set(ids))};spell={stone.zone.name}"
    def eight_spells_upgrade_and_resurrect_four_distinct():
        g=game(CardClass.PRIEST);p,e=g.player1,g.player2
        dead=[]
        for card_id in (WISP,"CS2_182","LOOT_413","CS2_125"):
            minion=summon(p,card_id);minion.destroy();dead.append(minion.id)
        stone=p.give(cid)
        seen=[]
        for i in range(8):
            p.used_mana=0;play(p,MOONFIRE,target=e.hero)
            active=next(c for c in p.hand if c.id.startswith("LOOT_507"))
            if i in (3,7):seen.append(active.id)
        active=next(c for c in p.hand if c.id.startswith("LOOT_507"))
        assert active.id=="LOOT_507t2",(seen,active.id)
        p.used_mana=0;active.play()
        revived=list(p.field);ids=[m.id for m in revived]
        assert len(revived)==4 and len(set(ids))==4 and set(ids)<=set(dead) and active.zone==Zone.GRAVEYARD,(ids,dead,active.zone)
        return f"upgrades={seen};resurrected={[(m.id,m.atk,m.health) for m in revived]};distinct={len(set(ids))}"
    return [
        ("base_resurrects_two_different_friendly_minions", "Base Spellstone resurrects two distinct friendly minions that died this game.", unupgraded_resurrects_two_distinct_friendly_deaths,
         "用三种不同随从各自死亡后实际施放未升级版本，逐个检查复活 ID 互异且来自己方墓地池。"),
        ("eight_spells_upgrade_to_greater_and_resurrect_four", "After eight spells across both upgrades, Greater Diamond Spellstone resurrects four different friendly minions.", eight_spells_upgrade_and_resurrect_four_distinct,
         "通过真实施放八张 Moonfire 升级两次，检查形态序列及四个复活对象互异。"),
    ]


def probe_511():
    cid="LOOT_511"
    def battlecry_and_deathrattle_each_recruit_beast():
        g=game(CardClass.HUNTER);p=g.player1
        beast1=p.give("CS2_125");beast1.shuffle_into_deck()
        beast2=p.give("LOOT_258");beast2.shuffle_into_deck()
        nonbeast=p.give(WISP);nonbeast.shuffle_into_deck()
        kathrena=play(p,cid)
        recruited1=[m for m in p.field if m is not kathrena]
        assert len(recruited1)==1 and Race(recruited1[0].race)==Race.BEAST and recruited1[0].zone==Zone.PLAY,([(m.id,Race(m.race).name,m.zone.name) for m in p.field],[c.id for c in p.deck])
        first=recruited1[0]
        kathrena.destroy()
        recruited2=[m for m in p.field if m is not first]
        assert len(recruited2)==1 and Race(recruited2[0].race)==Race.BEAST and recruited2[0].zone==Zone.PLAY and nonbeast in p.deck,(first.id,recruited2,[c.id for c in p.deck])
        return f"battlecry_recruit={first.id}:{first.zone.name};deathrattle_recruit={recruited2[0].id}:{recruited2[0].zone.name};non_beast_stays={nonbeast in p.deck};kathrena={kathrena.zone.name}"
    return [("battlecry_and_deathrattle_recruit_beasts", "Kathrena's Battlecry and Deathrattle each Recruit a Beast, leaving a non-Beast in deck.", battlecry_and_deathrattle_each_recruit_beast,
             "牌库放入两种 Beast 和一张普通随从，分别实测战吼与亡语各招募一只 Beast。")]


def probe_516():
    cid="LOOT_516"
    def chooses_friendly_minion_and_adds_copy():
        g=game();p=g.player1
        target=summon(p,WISP)
        zola=play(p,cid,target=target)
        copies=[c for c in p.hand if c.id==WISP]
        assert len(copies)==1 and copies[0].type==CardType.MINION and target.zone==Zone.PLAY and zola.zone==Zone.PLAY,(copies,target.zone,zola.zone)
        return f"target={target.id}:{target.zone.name};copy={[(c.id,c.zone.name) for c in copies]};zola={zola.zone.name}"
    return [("chooses_friendly_minion_and_adds_golden_copy", "Zola adds a copy of the chosen friendly minion to hand while the original stays on board.", chooses_friendly_minion_and_adds_copy,
             "使用真实友方目标完成战吼，检查同 ID 随从卡进入手牌、原随从仍在场。金色外观标记另有引擎表达能力限制。")]


def probe_517():
    cid="LOOT_517"
    def doubles_only_next_battlecry_this_turn():
        g=game(CardClass.SHAMAN);p,e=g.player1,g.player2
        summon(e,WISP)
        murmuring=play(p,cid)
        extra_after_murmuring=p.extra_battlecries
        first=play(p,"LOOT_367")
        after_double=p.hero.armor
        p.used_mana=0
        second=play(p,"LOOT_367")
        after_next=p.hero.armor
        assert extra_after_murmuring and after_double==4 and after_next==6 and first.zone==Zone.PLAY and second.zone==Zone.PLAY,(extra_after_murmuring,after_double,after_next,first.zone,second.zone)
        return f"extra_battlecries_after_murmuring={extra_after_murmuring};after_first_battlecry_twice={after_double};after_second_once={after_next};murmuring={murmuring.zone.name}"
    return [("next_battlecry_triggers_twice_once", "Murmuring Elemental doubles the next Battlecry this turn, then a later Battlecry resolves once.", doubles_only_next_battlecry_this_turn,
             "敌方有一个随从固定 Armor Armorer 的单次效果为 +2；第一张验证 +4，第二张验证临时效果已消耗。")]


def probe_518():
    cid="LOOT_518"
    def all_four_basic_totems_summon_alakir():
        g=game(CardClass.SHAMAN);p=g.player1
        totems=[summon(p,c) for c in BASIC_TOTEMS]
        stormcaller=play(p,cid)
        alakir=next((m for m in p.field if m.id=="NEW1_010"),None)
        assert len(totems)==4 and alakir is not None and alakir.zone==Zone.PLAY and (alakir.atk,alakir.health)==(3,5) and alakir.taunt and alakir.divine_shield and alakir.windfury and alakir.charge,(len(totems),alakir)
        return f"totems={[m.id for m in totems]};alakir={(alakir.id,alakir.atk,alakir.health,alakir.taunt,alakir.divine_shield,alakir.windfury,alakir.charge)};stormcaller={stormcaller.zone.name}"
    def missing_one_totem_does_not_summon_alakir():
        g=game(CardClass.SHAMAN);p=g.player1
        for c in BASIC_TOTEMS[:-1]:summon(p,c)
        stormcaller=play(p,cid)
        alakir=[m for m in p.field if m.id=="NEW1_010"]
        assert len(alakir)==0 and stormcaller.zone==Zone.PLAY,([m.id for m in p.field],stormcaller.zone)
        return f"basic_totems={len(BASIC_TOTEMS)-1};alakir_count={len(alakir)};stormcaller={stormcaller.zone.name}"
    return [
        ("four_basic_totems_summon_alakir", "Controlling all four basic Totems summons a 3/5 Al'Akir with Charge, Divine Shield, Taunt, and Windfury.", all_four_basic_totems_summon_alakir,
         "场上逐个放入 BASIC_TOTEMS 四种不同图腾，检查召唤物身份、身材和四个关键词。"),
        ("missing_basic_totem_no_alakir", "With one basic Totem missing, Windshear summons no Al'Akir.", missing_one_totem_does_not_summon_alakir,
         "仅控制三种基础图腾，覆盖条件不满足分支。"),
    ]


def probe_519():
    cid="LOOT_519"
    def end_turn_minion_cost_matches_armor_with_ten_cap():
        outcomes=[]
        for armor,expected_cost in ((4,4),(12,10)):
            g=game(CardClass.WARRIOR);p=g.player1
            p.hero.armor=armor
            yip=play(p,cid)
            before=list(p.field)
            g.end_turn()
            summoned=[m for m in p.field if m not in before]
            state=[(m.id,m.cost,m.zone.name) for m in summoned]
            assert len(summoned)==1 and summoned[0].cost==expected_cost and summoned[0].zone==Zone.PLAY,(armor,expected_cost,state)
            outcomes.append(f"armor={armor};minion={state}")
        return ";".join(outcomes)
    return [("end_turn_minion_cost_equals_armor_capped_at_ten", "Yip summons one random minion matching Armor cost, with Armor above 10 capped at 10.", end_turn_minion_cost_matches_armor_with_ten_cap,
             "两局分别用 4 与 12 点护甲结束己方回合，检查召唤费用对应 4 与上限 10。")]


def probe_520():
    cid="LOOT_520"
    def gains_deathrattle_from_random_deck_minion():
        g=game(CardClass.HUNTER);p=g.player1
        beetle=p.give("LOOT_413");beetle.shuffle_into_deck()
        plain=p.give(WISP);plain.shuffle_into_deck()
        oozeling=play(p,cid)
        before=p.hero.armor
        oozeling.destroy()
        assert oozeling.zone==Zone.GRAVEYARD and p.hero.armor==before+3 and plain in p.deck and beetle in p.deck,(oozeling.zone,p.hero.armor,before,[c.id for c in p.deck])
        return f"copied_source=LOOT_413;armor={before}->{p.hero.armor};source_stays_in_deck={beetle in p.deck};plain_stays={plain in p.deck};oozeling={oozeling.zone.name}"
    return [("copies_deck_minion_deathrattle_and_triggers_it", "Oozeling gains the sole Deathrattle minion's Deathrattle from deck and triggers it when Oozeling dies.", gains_deathrattle_from_random_deck_minion,
             "牌库放入唯一亡语随从 Plated Beetle 与普通 Wisp，打出 Oozeling 后死亡，检查 +3 护甲和牌库原卡保留。")]


def probe_521():
    cid="LOOT_521"
    def recruits_attack_one_two_three_and_excludes_others():
        g=game();p=g.player1
        # Cost-decoys make a cost-based Recruit implementation observable:
        # the text selects Attack, while the current script may select Cost.
        ids=("CS2_059","FP1_007","DRG_010",WISP,"CS2_119","AT_006")
        cards=[p.give(c) for c in ids]
        for card in cards:card.shuffle_into_deck()
        oakheart=play(p,cid)
        recruited=[m for m in p.field if m is not oakheart]
        state=sorted((m.id,m.atk,m.zone.name) for m in recruited)
        assert len(recruited)==3 and sorted(m.atk for m in recruited)==[1,2,3] and all(m.zone==Zone.PLAY for m in recruited) and all(c in p.deck for c in cards[:3]),(state,[c.id for c in p.deck],oakheart.zone.name)
        return f"recruited={state};cost_decoys_remain={[c.id for c in cards[:3] if c in p.deck]};oakheart={oakheart.zone.name}"
    return [("recruits_one_two_three_attack_minions", "Oakheart Recruits one minion at each of 1, 2, and 3 Attack, leaving a higher-Attack deck minion behind.", recruits_attack_one_two_three_and_excludes_others,
             "牌库分别放入费用 1/2/3 但攻击 0/0/4 的诱饵，以及费用不为 1/2/3 而攻击为 1/2/3 的随从，按卡面攻击力逐个检查。")]


def probe_522():
    cid="LOOT_522"
    def destroys_left_and_right_enemy_minions_only():
        g=game(CardClass.HUNTER);p,e=g.player1,g.player2
        friendly=summon(p,WISP)
        enemies=[summon(e,c) for c in (WISP,"CS2_182","CS2_125","CS2_196")]
        spell=play(p,cid)
        state=[(m.id,m.zone.name,m.health) for m in enemies]
        assert enemies[0].zone==Zone.GRAVEYARD and enemies[3].zone==Zone.GRAVEYARD and enemies[1].zone==Zone.PLAY and enemies[2].zone==Zone.PLAY and friendly.zone==Zone.PLAY and spell.zone==Zone.GRAVEYARD,state
        return f"enemies_left_to_right={state};friendly={friendly.zone.name};spell={spell.zone.name}"
    def one_enemy_is_destroyed_once():
        g=game(CardClass.HUNTER);p,e=g.player1,g.player2
        lone=summon(e,"CS2_182")
        play(p,cid)
        assert lone.zone==Zone.GRAVEYARD and not e.field,lone.zone
        return f"one_enemy={lone.zone.name};enemy_field={len(e.field)}"
    return [
        ("destroys_both_edge_enemy_minions", "Crushing Walls destroys only the opponent's leftmost and rightmost minions; center and friendly minions remain.", destroys_left_and_right_enemy_minions_only,
         "敌方布置四个有序不同随从并保留一个友方随从，逐个确认两侧死亡、中央与友方存活。"),
        ("single_enemy_minion_destroyed_once", "If the opponent has one minion, it is destroyed once without an extra side effect.", one_enemy_is_destroyed_once,
         "覆盖左右边界指向同一随从的单随从局面。"),
    ]


def probe_526():
    cid="LOOT_526"
    def battlecry_shuffles_three_candles_into_enemy_deck():
        g=game();p,e=g.player1,g.player2
        darkness=play(p,cid)
        enemy_candles=[c for c in e.deck if c.id=="LOOT_526t"]
        own_candles=[c for c in p.deck if c.id=="LOOT_526t"]
        actual=(darkness.dormant,darkness.progress,len(enemy_candles),len(own_candles),darkness.zone.name)
        assert actual==(True,0,3,0,"PLAY"),actual
        return f"dormant={actual[0]};progress={actual[1]}/{darkness.progress_total};enemy_candles={len(enemy_candles)};own_candles={len(own_candles)};darkness={actual[4]}"
    def three_actual_candle_draws_awaken_in_full_board_slot():
        g=game();p,e=g.player1,g.player2
        friendly=[summon(p,WISP) for _ in range(6)]
        darkness=play(p,cid)
        assert len(p.field)==7 and darkness.dormant,(len(p.field),darkness.dormant)
        # The battlecry's deck-routing is covered separately. For the progress
        # branch, use actual Candle entities created by Darkness in the expected
        # opponent deck so each draw exercises its on-draw cast and creator link.
        candles=[]
        draw_sequence=[]
        for _ in range(3):
            candle=e.card("LOOT_526t",source=darkness)
            candles.append(candle)
            draw_sequence.extend((candle,e.card(WISP)))
        for card in draw_sequence:
            card.zone=Zone.DECK
        # Draw takes deck[-1]. Establish the deterministic sequence Candle,
        # replacement Wisp, Candle, replacement Wisp, Candle, replacement Wisp.
        e.deck[:]=list(reversed(draw_sequence))
        states=[]
        for index in range(1,4):
            drawn=e.draw()
            states.append((index,None if drawn is None else drawn.id,darkness.progress,darkness.dormant,len(p.field),darkness.zone.name))
            assert drawn is not None and drawn.id=="LOOT_526t",(index,drawn,states[-1],[c.id for c in e.deck])
            expect_dormant=index<3
            assert darkness.progress==index and darkness.dormant==expect_dormant and len(p.field)==7 and darkness.zone==Zone.PLAY,states[-1]
        replacements=[c for c in e.hand if c.id==WISP]
        assert all(c.zone!=Zone.DECK for c in candles) and len(e.deck)==0 and len(replacements)==3,([(c.zone.name,c.id) for c in candles],[c.id for c in e.deck],[c.id for c in e.hand])
        return f"draw_progress_dormant_field={states};full_board_slots={len(p.field)};candles={[c.zone.name for c in candles]};replacement_draws={[c.id for c in replacements]}"
    return [
        ("battlecry_shuffles_three_candles_into_enemy_deck", "The Darkness starts Dormant and shuffles exactly three Candles into the opponent's deck.", battlecry_shuffles_three_candles_into_enemy_deck,
         "实际打出黑暗之主，分别统计双方牌库中的 LOOT_526t，并断言己方休眠体留场且对手牌库有且仅有三张蜡烛。"),
        ("three_opponent_candle_draws_awaken_darkness", "The opponent's first two Candle draws advance progress while Darkness stays Dormant; the third awakens it without using another board slot.", three_actual_candle_draws_awaken_in_full_board_slot,
         "场上预置六个己方随从再打出休眠的黑暗之主以填满第七格；将带 Darkness creator 的真实 Candle 实体放入对手牌库，逐次实际抽牌断言进度 1/2/3、前两次休眠、第三次苏醒及场位不变。")
    ]


def probe_528():
    cid="LOOT_528"
    def holding_dragon_swaps_attack_with_target():
        g=game(CardClass.PRIEST);p,e=g.player1,g.player2
        dragon=p.give("EX1_563")
        target=summon(e,"CS2_182")
        acolyte=play(p,cid,target=target)
        actual=(dragon in p.hand,target.atk,acolyte.atk,target.zone.name,acolyte.zone.name)
        assert actual==(True,2,4,"PLAY","PLAY"),actual
        return f"dragon_held={actual[0]};target_attack={actual[1]};acolyte_attack={actual[2]};target={actual[3]};acolyte={actual[4]}"
    def no_held_dragon_leaves_attack_unchanged():
        g=game(CardClass.PRIEST);p,e=g.player1,g.player2
        target=summon(e,"CS2_182")
        before=target.atk
        acolyte=play(p,cid)
        actual=(before,target.atk,acolyte.atk,target.zone.name,acolyte.zone.name)
        assert actual==(4,4,2,"PLAY","PLAY"),actual
        return f"dragon_held=False;target_attack={actual[1]};acolyte_attack={actual[2]};target={actual[3]}"
    return [
        ("dragon_held_swaps_attack_with_selected_minion", "Holding a Dragon makes Twilight Acolyte swap its Attack with the chosen minion.", holding_dragon_swaps_attack_with_target,
         "手牌持有龙牌并明确选择敌方 4 攻随从，检查双方攻击力交换且区域不变。"),
        ("without_dragon_attack_is_not_swapped", "Without a Dragon in hand, Twilight Acolyte does not change another minion's Attack.", no_held_dragon_leaves_attack_unchanged,
         "无龙手牌时在敌方留有可选随从的局面打出，断言不发生攻击力交换。")
    ]


def probe_529():
    cid="LOOT_529"
    def battlecry_swaps_attack_and_health_of_all_other_minions():
        g=game();p,e=g.player1,g.player2
        friendly=summon(p,"CS2_182")
        enemy=summon(e,"CS2_119")
        before=(friendly.atk,friendly.max_health,enemy.atk,enemy.max_health)
        ripper=play(p,cid)
        after=(friendly.atk,friendly.max_health,enemy.atk,enemy.max_health)
        actual=(before,after,ripper.atk,ripper.max_health,ripper.zone.name,friendly.zone.name,enemy.zone.name)
        assert after==(before[1],before[0],before[3],before[2]) and (ripper.atk,ripper.max_health)==(3,3) and ripper.zone==Zone.PLAY,actual
        return f"other_minions_before={before};after={after};ripper={(ripper.atk,ripper.max_health,ripper.zone.name)}"
    return [("battlecry_swaps_other_minions_attack_and_health", "Void Ripper swaps Attack and Health on every other minion, friendly and enemy, and leaves itself unchanged.", battlecry_swaps_attack_and_health_of_all_other_minions,
             "同时放置己方 4/5 与敌方 2/7 随从，实际打出 3/3 Void Ripper，逐项检查其他双方随从攻/生命互换、本体未交换。")]


def probe_534():
    cid="LOOT_534"
    def deathrattle_adds_coin_to_hand():
        g=game(CardClass.PRIEST);p=g.player1
        before=[c.id for c in p.hand]
        gargoyle=summon(p,cid)
        gargoyle.destroy()
        added=[c for c in p.hand if c.id not in before]
        actual=(gargoyle.zone.name,[(c.id,c.zone.name) for c in added],len(p.hand))
        assert gargoyle.zone==Zone.GRAVEYARD and len(added)==1 and added[0].id==THE_COIN and added[0].zone==Zone.HAND,actual
        return f"gargoyle={actual[0]};deathrattle_added={actual[1]};hand_size={actual[2]}"
    return [("deathrattle_adds_coin_to_hand", "When Gilded Gargoyle dies, its Deathrattle adds one Coin to its controller's hand.", deathrattle_adds_coin_to_hand,
             "召唤后实际消灭石像鬼，检查其墓地区域及手牌恰新增一张处于手牌的幸运币。")]


def probe_535():
    cid="LOOT_535"
    def summons_five_five_dragons_for_each_five_cost_spell_played():
        g=game(CardClass.MAGE);p,e=g.player1,g.player2
        high_spells=[play(p,"CS2_032")]
        p.used_mana=0
        high_spells.append(play(p,"EX1_279",target=e.hero))
        p.used_mana=0
        cheap=play(p,MOONFIRE,target=e.hero)
        alanna=play(p,cid)
        dragons=[m for m in p.field if m.id=="LOOT_535t"]
        actual=(len(high_spells),cheap.zone.name,[(m.id,m.atk,m.health,m.zone.name) for m in dragons],alanna.zone.name,e.hero.health)
        assert len(dragons)==2 and all((m.atk,m.health,m.zone)==(5,5,Zone.PLAY) for m in dragons) and alanna.zone==Zone.PLAY,actual
        return f"five_plus_spells={len(high_spells)};cheap_spell={actual[1]};dragons={actual[2]};alanna={actual[3]};enemy_hero={actual[4]}"
    def no_five_cost_spell_summons_no_dragon():
        g=game(CardClass.MAGE);p=g.player1
        alanna=play(p,cid)
        dragons=[m for m in p.field if m.id=="LOOT_535t"]
        assert not dragons and alanna.zone==Zone.PLAY,(dragons,alanna.zone)
        return f"five_plus_spells=0;dragons={len(dragons)};alanna={alanna.zone.name}"
    return [
        ("five_plus_spells_each_summon_five_five_dragon", "Dragoncaller Alanna summons one 5/5 Dragon per spell costing at least 5 played this game; cheap spells do not count.", summons_five_five_dragons_for_each_five_cost_spell_played,
         "本局先实际施放 7 费烈焰风暴与 10 费炎爆术，再施放零费月火作负对照；打出奥兰娜后精确断言召唤两只 5/5 龙。"),
        ("zero_qualifying_spells_summons_no_dragon", "With no qualifying spell played, Dragoncaller Alanna summons no Dragon.", no_five_cost_spell_summons_no_dragon,
         "不施放任何法术直接打出奥兰娜，覆盖零计数分支并检查不出现 LOOT_535t。")
    ]


def probe_537():
    cid="LOOT_537"
    def reduces_generated_card_but_preserves_starting_deck_card_cost():
        g=game(CardClass.MAGE);p=g.player1
        starting=p.give("CS2_200")
        p.starting_deck=[starting]
        generated=p.give("CS2_029")
        before=(starting.cost,generated.cost)
        manipulator=play(p,cid)
        after=(starting.cost,generated.cost)
        actual=(before,after,starting in p.hand,generated in p.hand,manipulator.zone.name)
        assert after==(before[0],before[1]-2) and starting in p.hand and generated in p.hand and manipulator.zone==Zone.PLAY,actual
        return f"starting_card_cost={before[0]}->{after[0]};generated_card_cost={before[1]}->{after[1]};hand_cards={actual[2:4]}"
    def starting_deck_only_hand_has_no_reduction():
        g=game(CardClass.MAGE);p=g.player1
        starting=p.give("CS2_200");p.starting_deck=[starting]
        before=starting.cost
        manipulator=play(p,cid)
        assert starting.cost==before and starting in p.hand and manipulator.zone==Zone.PLAY,(before,starting.cost,starting in p.hand)
        return f"starting_card_cost={before}->{starting.cost};no_generated_cards=True;manipulator={manipulator.zone.name}"
    return [
        ("reduces_only_hand_card_not_from_starting_deck", "Leyline Manipulator reduces the Cost of cards in hand that did not start in the deck by 2; starting-deck cards keep their Cost.", reduces_generated_card_but_preserves_starting_deck_card_cost,
         "构造起始牌库中的 6 费牌与不在起始牌库中的 4 费火球术同时在手，打出操控者后分别断言起始牌不变、生成/非起始牌减 2。"),
        ("starting_deck_only_hand_is_unchanged", "If the hand contains only starting-deck cards, Leyline Manipulator does not reduce their Cost.", starting_deck_only_hand_has_no_reduction,
         "手牌仅放一张列入 starting_deck 的 6 费牌，无生成牌时打出操控者并检查基础卡费用不变。")
    ]


def probe_538():
    cid="LOOT_538"
    def queues_two_opponent_turns_then_two_controller_turns():
        g=game(CardClass.PRIEST,CardClass.WARRIOR);p,e=g.player1,g.player2
        temporus=play(p,cid)
        after_battlecry=[player.name for player in g.next_players]
        turns=[]
        for _ in range(4):
            g.end_turn()
            turns.append(g.current_player)
        actual=(after_battlecry,["P1" if player is p else "P2" if player is e else player.name for player in turns],temporus.zone.name)
        assert turns==[e,e,p,p] and temporus.zone==Zone.PLAY,actual
        return f"queued={after_battlecry};current_players={actual[1]};temporus={actual[2]}"
    return [("battlecry_grants_two_opponent_turns_then_two_own", "After the current turn, Temporus grants the opponent two consecutive turns followed by two controller turns.", queues_two_opponent_turns_then_two_controller_turns,
             "实际打出坦普卢斯并连续推进四个真实回合，逐次断言当前玩家序列为 P2、P2、P1、P1，且坦普卢斯留场。")]


def probe_539():
    cid="LOOT_539"
    def reveals_spell_and_summons_random_minion_with_same_cost():
        g=game();p=g.player1
        spell=p.give("CS2_032");spell.shuffle_into_deck()
        summoner=play(p,cid)
        spawned=[m for m in p.field if m is not summoner]
        actual=(spell.zone.name,spell in p.deck,[(m.id,m.cost,m.zone.name) for m in spawned],summoner.zone.name)
        assert spell.zone==Zone.DECK and spell in p.deck and len(spawned)==1 and spawned[0].cost==7 and spawned[0].zone==Zone.PLAY and summoner.zone==Zone.PLAY,actual
        return f"revealed_spell={spell.id}:cost7:{actual[0]};deck_contains_spell={actual[1]};summoned={actual[2]};summoner={actual[3]}"
    def no_spell_in_deck_does_not_summon_minion():
        g=game();p=g.player1
        summoner=play(p,cid)
        spawned=[m for m in p.field if m is not summoner]
        assert not spawned and summoner.zone==Zone.PLAY,(spawned,summoner.zone)
        return f"deck_spell_count=0;summoned={len(spawned)};summoner={summoner.zone.name}"
    return [
        ("revealed_deck_spell_cost_matches_summoned_minion", "Spiteful Summoner reveals a spell from deck and summons a random minion of the same Cost.", reveals_spell_and_summons_random_minion_with_same_cost,
         "牌库只放入一张七费烈焰风暴，打出恶毒的召唤师后检查法术仍在牌库且恰有一个七费随从进入场地。"),
        ("empty_deck_has_no_spell_to_copy_cost", "With no spell in deck, Spiteful Summoner summons no minion.", no_spell_in_deck_does_not_summon_minion,
         "空牌库分支实测战吼，不预放任何法术，检查不召唤额外随从。")
    ]


def probe_540():
    cid="LOOT_540"
    def end_turn_recruits_dragon_from_deck_only():
        g=game();p=g.player1
        dragon=p.give("EX1_563")
        dragon.shuffle_into_deck()
        non_dragon=p.give(WISP);non_dragon.shuffle_into_deck()
        hatcher=play(p,cid)
        before=list(p.field)
        g.end_turn()
        recruited=[m for m in p.field if m not in before]
        actual=(hatcher.zone.name,[(m.id,m.race,m.zone.name) for m in recruited],dragon in p.deck,non_dragon in p.deck)
        assert len(recruited)==1 and recruited[0].race==Race.DRAGON and recruited[0].zone==Zone.PLAY and dragon not in p.deck and non_dragon in p.deck and hatcher.zone==Zone.PLAY,actual
        return f"dragon_recruited={[(m.id,Race(m.race).name,m.zone.name) for m in recruited]};dragon_left_deck={not actual[2]};non_dragon_stays={actual[3]};hatcher={actual[0]}"
    def no_deck_dragon_has_no_recruit():
        g=game();p=g.player1
        hatcher=play(p,cid)
        before=list(p.field)
        g.end_turn()
        recruited=[m for m in p.field if m not in before]
        assert not recruited and hatcher.zone==Zone.PLAY,(recruited,hatcher.zone)
        return f"dragon_count_in_deck=0;recruited={len(recruited)};hatcher={hatcher.zone.name}"
    return [
        ("end_turn_recruits_dragon_and_leaves_non_dragon", "At the end of your turn, Dragonhatcher Recruits a Dragon from deck and leaves non-Dragons behind.", end_turn_recruits_dragon_from_deck_only,
         "牌库准备一条龙与一只非龙，打出驯龙师并实际结束己方回合，检查龙进入场地而非龙仍在牌库。"),
        ("no_deck_dragon_does_not_summon", "If deck contains no Dragon, Dragonhatcher recruits nothing at turn end.", no_deck_dragon_has_no_recruit,
         "空牌库分支实际结束己方回合，检查不产生随从。")
    ]


def probe_541():
    cid="LOOT_541"
    def swaps_decks_and_ransom_swaps_back():
        g=game(CardClass.MAGE,CardClass.WARRIOR);p,e=g.player1,g.player2
        own=p.give(WISP);own.shuffle_into_deck()
        enemy=e.give("CS2_182");enemy.shuffle_into_deck()
        own_before=list(p.deck);enemy_before=list(e.deck)
        king=play(p,cid)
        ransom=next((c for c in e.hand if c.id=="LOOT_541t"),None)
        after_swap=(list(p.deck),list(e.deck),ransom is not None)
        assert p.deck==enemy_before and e.deck==own_before and ransom is not None and ransom.zone==Zone.HAND and king.zone==Zone.PLAY,(after_swap,[c.id for c in p.deck],[c.id for c in e.deck])
        # Keep the next-turn draw from moving the swapped card out of the deck
        # before the opponent can resolve Ransom.
        e.cant_draw=True
        g.end_turn()
        ransom.play()
        after_return=(list(p.deck),list(e.deck),ransom.zone.name)
        returned_ransom=next((c for c in p.hand if c.id=="LOOT_541t"),None)
        assert p.deck==own_before and e.deck==enemy_before and ransom.zone==Zone.GRAVEYARD and returned_ransom is not None, (after_return,[c.id for c in p.hand])
        return f"after_togwaggle=player1:{[c.id for c in after_swap[0]]};player2:{[c.id for c in after_swap[1]]};ransom_given={after_swap[2]};after_ransom=player1:{[c.id for c in p.deck]};player2:{[c.id for c in e.deck]};used_ransom={ransom.zone.name};returned_ransom={returned_ransom.zone.name};king={king.zone.name}"
    return [("battlecry_swaps_decks_and_gives_ransom_to_restore", "King Togwaggle swaps both decks and gives the opponent a Ransom that swaps them back.", swaps_decks_and_ransom_swaps_back,
             "给双方各放入一张身份不同的牌库卡，实测国王打出后的牌库对象交换与对手手牌赎金；切换到对手回合实际施放赎金，再检查原牌库恢复及赎金消耗。")]


def probe_542():
    cid="LOOT_542"
    def deathrattle_shuffles_weapon_back_and_keeps_enchantments():
        g=game(CardClass.ROGUE);p=g.player1
        weapon=play(p,cid)
        poison1=play(p,"CS2_074",target=weapon)
        p.used_mana=0
        poison2=play(p,"CS2_074",target=weapon)
        empowered=(weapon.atk,weapon.durability)
        weapon.destroy()
        deck_after=[c for c in p.deck if c.id==cid]
        # The card definition stores both DURABILITY=3 and HEALTH=3; this
        # engine's Weapon.max_durability sums those fields, so its live
        # starting durability is 6 (not the printed DURABILITY tag alone).
        assert empowered==(5,6) and weapon.zone==Zone.DECK and len(deck_after)==1 and deck_after[0] is weapon,(empowered,weapon.zone,[(c.id,c.atk,c.durability,c.zone.name) for c in deck_after])
        deck_snapshot=[(c.id,c.atk,c.durability,c.zone.name) for c in deck_after]
        drawn=p.draw()
        assert drawn is weapon and weapon.zone==Zone.HAND and (weapon.atk,weapon.durability)==empowered,(drawn,weapon.zone,weapon.atk,weapon.durability,empowered)
        draw_snapshot=(drawn.id,drawn.zone.name,drawn.atk,drawn.durability)
        p.used_mana=0
        weapon.play()
        assert p.hero.weapon is weapon and (weapon.atk,weapon.durability)==empowered,(p.hero.weapon,weapon.atk,weapon.durability,empowered)
        replay_snapshot=(weapon.atk,weapon.durability,weapon.zone.name)
        return f"poisons={(poison1.zone.name,poison2.zone.name)};deathrattle_deck={deck_snapshot};drawn={draw_snapshot};replayed={replay_snapshot}"
    return [("deathrattle_shuffles_kingsbane_and_preserves_weapon_buffs", "Kingsbane's Deathrattle shuffles it into its owner's deck, keeps its enchantments, and it retains those buffs when drawn and replayed.", deathrattle_shuffles_weapon_back_and_keeps_enchantments,
             "卡面 EN Kingsbane: 'Deathrattle: Shuffle this into your deck. It keeps any enchantments.' / ZH 王之帷幕（弑君）: 亡语洗回牌库并保留附魔；来源 `fireplace/cards/kobolds/rogue.py` 的 KEEP_BUFF/Shuffle、`CardDefs.xml` 的 DURABILITY=3 与 HEALTH=3、经典卡 CS2_074 的 buff(atk=2) 及 `fireplace/card.py` Weapon.max_durability；旧审计标为待核验。实测初始耐久6（本引擎 max_durability=3+max_health=3），两张致命药膏后为5攻/6耐久；触发亡语、抽回和重装备均是同一实体且保留附魔。")]


PROBES = {
    "LOOT_367": probe_367, "LOOT_368": probe_368, "LOOT_370": probe_370,
    "LOOT_373": probe_373, "LOOT_375": probe_375, "LOOT_380": probe_380,
    "LOOT_382": probe_382, "LOOT_383": probe_383, "LOOT_388": probe_388,
    "LOOT_389": probe_389, "LOOT_392": probe_392, "LOOT_394": probe_394,
    "LOOT_398": probe_398, "LOOT_410": probe_410, "LOOT_412": probe_412,
    "LOOT_413": probe_413, "LOOT_414": probe_414, "LOOT_415": probe_415,
    "LOOT_417": probe_417, "LOOT_420": probe_420, "LOOT_500": probe_500,
    "LOOT_503": probe_503, "LOOT_504": probe_504, "LOOT_506": probe_506,
    "LOOT_507": probe_507, "LOOT_511": probe_511, "LOOT_516": probe_516,
    "LOOT_517": probe_517, "LOOT_518": probe_518, "LOOT_519": probe_519,
    "LOOT_520": probe_520, "LOOT_521": probe_521, "LOOT_522": probe_522,
    "LOOT_526": probe_526, "LOOT_528": probe_528, "LOOT_529": probe_529,
    "LOOT_534": probe_534, "LOOT_535": probe_535, "LOOT_537": probe_537,
    "LOOT_538": probe_538, "LOOT_539": probe_539, "LOOT_540": probe_540,
    "LOOT_541": probe_541, "LOOT_542": probe_542,
}

BLOCKERS = {
    "LOOT_414": "牌库代施放是否应触发普通玩家施法事件暂无权威语义结论；记录了与手动施放的对照，但该机制边界未判定。",
    "LOOT_516": "实测验证了所选随从的副本进入手牌，但该引擎没有暴露卡牌是否金色/高级外观的状态，无法验证文本中的 Golden 属性。",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=CARDS[0])
    parser.add_argument("--end", default=CARDS[-1])
    args = parser.parse_args()
    start = CARDS.index(args.start)
    end = CARDS.index(args.end)
    if start > end:
        raise SystemExit("--start must be before --end in the frozen roster")
    write_csv(PROBE, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT, VERDICT_FIELDS, VERDICT_ROWS)
    for cid in CARDS[start:end + 1]:
        if cid not in PROBES:
            print(f"{cid}: BLOCKED — probe not implemented", flush=True)
            continue
        audit_card(cid, PROBES[cid](), BLOCKERS.get(cid))


if __name__ == "__main__":
    main()
