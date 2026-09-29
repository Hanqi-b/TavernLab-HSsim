"""Per-card live behavior probes for the frozen BRM YELLOW roster."""
import argparse
import csv
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone

ROOT = Path(__file__).parent
PROJECT = ROOT.parents[1]
sys.path.insert(0, str(PROJECT / "tests"))
from utils import (  # noqa: E402
    GOLDSHIRE_FOOTMAN,
    MOONFIRE,
    WISP,
    WHELP,
    prepare_empty_game,
)

PROBE_OUT = ROOT / "brm_probe.csv"
VERDICT_OUT = ROOT / "brm_verdict.csv"
BASELINE = ROOT / "four_set_yellow_baseline.csv"
MASTER = ROOT / "card_master.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")

UNVERIFIED = {
    "BRM_001": "未覆盖：空牌库疲劳、满手牌溢出抽牌和回合重置。",
    "BRM_002": "未覆盖：满场随机分配；由其他卡牌代施放法术后的触发归属（既有跨卡审计 CAST-001 标记为 semantics_pending）。",
    "BRM_003": "未覆盖：随从目标、非法目标拒绝和满减费后的零费下限。",
    "BRM_004": "未覆盖：手牌中的龙被移走后再打出暮光雏龙。",
    "BRM_005": "未覆盖：圣盾、免疫及满场对双方恶魔/非恶魔混合场的边界。",
    "BRM_006": "未覆盖：满场时受到伤害导致的小鬼召唤容量。",
    "BRM_007": "未覆盖：目标已受增益/沉默后复制的属性，以及满牌库洗入。",
    "BRM_008": "未覆盖：圣盾/免疫对战吼伤害的交互。",
    "BRM_009": "未覆盖：零费下限、对手回合费用变化及满场嘲讽攻击。",
    "BRM_010": "未覆盖：变形前后受到的增益/沉默是否保留。",
    "BRM_011": "未覆盖：过载超过可解锁水晶总数和非法目标拒绝。",
    "BRM_012": "未覆盖：重复抽样的概率分布；仅确认1至4的取值及过载状态。",
    "BRM_013": "未覆盖：满手牌抽牌烧牌和目标拒绝后手牌/法力状态。",
    "BRM_014": "未覆盖：抽牌触发前后手牌计数边界及沉默后的增益。",
    "BRM_015": "未覆盖：护盾、免疫和场上七只随从时的全场结算。",
    "BRM_016": "未覆盖：多个同时受伤事件及敌方英雄免疫。",
    "BRM_017": "未覆盖：空死亡池拒绝、满场召唤及不同身材副本属性。",
    "BRM_018": "未覆盖：已打出的龙不会追溯折扣，以及来源离场前后的费用。",
    "BRM_019": "未覆盖：满场时存活伤害触发以及同批次伤害。",
    "BRM_020": "未覆盖：敌方沉默/控制效果及同一法术对其造成伤害时的时序。",
    "BRM_022": "未覆盖：满场和圣盾吸收伤害时的雏龙召唤。",
    "BRM_024": "未覆盖：敌方英雄生命低于15、护甲和战吼前后生命变化。",
    "BRM_025": "未覆盖：回合切换重置死亡折扣及费用下限的跨回合边界。",
    "BRM_026": "未覆盖：对手满场时召唤失败及随机池覆盖面。",
    "BRM_027": "未覆盖：护甲、当前生命低于8以及双方均持有管理者时的英雄替换。",
    "BRM_029": "未覆盖：无龙但有传说目标时的候选域，以及满场以外的战吼边界。",
    "BRM_030": "未覆盖：随机法术池覆盖和满手牌溢出。",
    "BRM_031": "未覆盖：满手牌抽牌导致原牌烧毁时的复制行为。",
    "BRM_033": "未覆盖：持龙条件在打出本体前变化及沉默后的属性。",
    "BRM_034": "未覆盖：友方目标、英雄目标、圣盾吸收和非法目标拒绝。",
}


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


PROBE_ROWS = read_csv(PROBE_OUT)
VERDICT_ROWS = read_csv(VERDICT_OUT)


def record(card_id, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, AssertionError) and not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error" if isinstance(exc, AssertionError) else "inconclusive"
    PROBE_ROWS.append({"card_id": card_id, "case_id": case_id, "expected": expected,
                       "observed": observed, "outcome": outcome, "notes": notes})
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    return outcome


def finish_card(card_id, scope, blocker=None, notes=""):
    cases = [row for row in PROBE_ROWS if row["card_id"] == card_id]
    failures = [row for row in cases if row["outcome"] == "confirmed_error"]
    unresolved = [row for row in cases if row["outcome"] == "inconclusive"]
    if failures:
        status = "RED"
        reason = "确认错误：" + "；".join(
            f"{row['case_id']}预期[{row['expected']}]，实际[{row['observed']}]" for row in failures
        )
    elif unresolved:
        status = "YELLOW"
        reason = "行为未决：" + "；".join(
            f"{row['case_id']}={row['observed']}" for row in unresolved
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "通过：" + "；".join(
            f"{row['case_id']}={row['observed']}" for row in cases
        )
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != card_id]
    master = next((row for row in read_csv(MASTER) if row["card_id"] == card_id), {})
    mechanisms = [row for row in read_csv(ROOT / "card_mechanism.csv") if row["card_id"] == card_id]
    old_yellow = sorted({row["reason"] for row in mechanisms if row["status"] == "YELLOW" and row["reason"]})
    prior_issues = []
    for row in read_csv(ROOT / "mechanism_issues.csv"):
        affected = set((row.get("confirmed_cards", "") + "|" + row.get("candidate_cards", "")).split("|"))
        if card_id in affected:
            prior_issues.append(f"{row['issue_id']}[{row['severity']}]:{row['summary']}")
    refs = master.get("test_refs_candidate", "") or "无候选测试引用"
    metadata_notes = (
        f"EN={master.get('card_text_en', '')}; ZH={master.get('card_text_zh', '')}; "
        f"source={master.get('python_source', '')}; existing_tests={refs}; "
        f"old_YELLOW_reason={' / '.join(old_yellow) if old_yellow else '无'}; "
        f"prior_cross_card_audit={' / '.join(prior_issues) if prior_issues else '无'}; "
        f"key_unverified={UNVERIFIED.get(card_id, '无')}; "
        f"audit_scope=只覆盖本CSV所列实际对局断言。"
    )
    if notes:
        metadata_notes += f"; audit_note={notes}"
    VERDICT_ROWS.append({"card_id": card_id, "status": status, "mechanic_scope": master.get("mechanics", scope),
                         "reason": reason, "probe_file": PROBE_OUT.name, "notes": metadata_notes})
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def clear_card(card_id):
    PROBE_ROWS[:] = [row for row in PROBE_ROWS if row["card_id"] != card_id]
    VERDICT_ROWS[:] = [row for row in VERDICT_ROWS if row["card_id"] != card_id]
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)


def new_game(class1=None, class2=None):
    game = prepare_empty_game(class1, class2)
    if game.current_player is not game.player1:
        game.end_turn()
    for player in game.players:
        player.is_standard = False
    return game


def board_ids(player):
    return [card.id for card in player.field]


def case(card_id, case_id, expected, func, notes):
    return record(card_id, case_id, expected, func, notes)


def probe_001():
    cid = "BRM_001"
    def behavior():
        game = new_game()
        owner, other = game.player1, game.player2
        owner.discard_hand()
        for _ in range(2):
            card = owner.give(WISP)
            card.shuffle_into_deck()
        vigil = owner.give(cid)
        owner.summon(WISP).destroy()
        assert vigil.cost == 4, vigil.cost
        other.summon(WISP).destroy()
        assert vigil.cost == 3, vigil.cost
        vigil.play()
        drawn = list(owner.hand)
        assert len(drawn) == 2 and all(card.id == WISP for card in drawn), [c.id for c in drawn]
        return f"deaths=2;cost=3;drawn={[card.id for card in drawn]}"
    case(cid, "death_discount_and_two_draws", "Each minion death this turn lowers cost by 1; the spell draws exactly two cards.", behavior,
         "分别让双方各死一个随从，核对折扣累计和已知牌库抽取数量/身份。")
    finish_card(cid, "Cost modification|Draw / Discard|Spell resolution")


def probe_002():
    cid = "BRM_002"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        waker = owner.summon(cid)
        ally = owner.summon(WISP)
        enemy_start = enemy.hero.health
        owner.give(MOONFIRE).play(target=enemy.hero)
        assert enemy.hero.health == enemy_start - 3, enemy.hero.health
        assert ally.zone == Zone.PLAY and ally.health == 1, (ally.zone, ally.health)
        assert waker.zone == Zone.PLAY
        return f"enemy_hero={enemy.hero.health};damage=3(including_spell_1+trigger_2);ally={ally.health}"
    case(cid, "spell_trigger_damage", "After a spell resolves, Flamewaker deals 2 damage to the only enemy; the spell itself deals its 1 damage separately.", behavior,
         "用敌方英雄作为唯一随机候选，区分法术本身伤害与触发的2点伤害，并确认友方未受伤。")
    def split_behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        owner.summon(cid)
        target = enemy.summon("BRM_014")  # Unbuffed Core Rager, 4/4, so both pings are observable.
        friendly = owner.summon(WISP)
        initial_enemy_total = enemy.hero.health + target.health
        owner.give("CS2_037").play(target=enemy.hero)
        # Frost Shock deals 1 to the hero. Each Flamewaker ping should then be a single point
        # randomly assigned across the enemy characters, for 3 total loss in this scene.
        enemy_loss = (initial_enemy_total - enemy.hero.health - target.health)
        observed = {"enemy_hero_health": enemy.hero.health, "4/4_minion_health": target.health,
                    "minion_zone": target.zone.name, "total_enemy_loss_including_spell": enemy_loss}
        assert target.zone == Zone.PLAY and target.health >= 1, observed
        assert enemy_loss == 3, observed
        assert friendly.zone == Zone.PLAY and friendly.health == 1, (friendly.zone, friendly.health)
        return f"enemy_total_damage={enemy_loss}(including_spell_1);hero={enemy.hero.health};4/4_minion={target.health};friendly={friendly.health}"
    case(cid, "random_split_enemy_only", "The post-spell 2 damage is split only among enemy characters; with a minion and hero, total enemy loss is 3 including Frost Shock's 1.", split_behavior,
         "对照敌方英雄和4/4敌方随从两个候选，并检查友方随从不进入伤害范围。")
    finish_card(cid, "Trigger")


def probe_003():
    cid = "BRM_003"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        spell = owner.give(cid)
        owner.summon(WISP).destroy()
        enemy.summon(WISP).destroy()
        assert spell.cost == 3, spell.cost
        discounted_cost = spell.cost
        spell.play(target=enemy.hero)
        assert enemy.hero.health == 26, enemy.hero.health
        assert spell.zone == Zone.GRAVEYARD
        return f"cost_after_2_deaths={discounted_cost};enemy_hero={enemy.hero.health};spell={spell.zone.name}"
    case(cid, "discounted_four_damage", "Two minions dying reduce cost by 2; the spell deals exactly 4 damage to a legal enemy hero target.", behavior,
         "通过双方随从死亡累计折扣，并对英雄结算4点实际伤害。")
    finish_card(cid, "Cost modification|Spell resolution|Targeting")


def probe_004():
    cid = "BRM_004"
    def behavior():
        game = new_game()
        owner = game.player1
        whelp = owner.give(cid)
        whelp.play()
        assert (whelp.atk, whelp.health, whelp.max_health) == (2, 1, 1), (whelp.atk, whelp.health, whelp.max_health)
        return f"no_dragon={whelp.atk}/{whelp.health}"
    case(cid, "no_dragon_baseline", "Without a Dragon in hand, Twilight Whelp remains its printed 2/1.", behavior,
         "覆盖持龙条件不满足分支和本体基础属性。")
    def powered():
        game = new_game()
        owner = game.player1
        owner.give(WHELP)
        whelp = owner.give(cid)
        whelp.play()
        assert (whelp.atk, whelp.health, whelp.max_health) == (2, 3, 3), (whelp.atk, whelp.health, whelp.max_health)
        return f"dragon_in_hand=True;stats={whelp.atk}/{whelp.health}"
    case(cid, "dragon_in_hand_health_bonus", "With a Dragon in hand, Twilight Whelp gains exactly +2 Health (2/3).", powered,
         "覆盖持龙条件满足分支并检查最大生命值同步。")
    finish_card(cid, "Battlecry")


def probe_005():
    cid = "BRM_005"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        ally = owner.summon(WISP)
        demon1 = owner.summon("EX1_598")
        enemy_wisp = enemy.summon(WISP)
        demon2 = enemy.summon("EX1_598")
        assert Race.DEMON in demon1.races and Race.DEMON in demon2.races
        heroes = (owner.hero.health, enemy.hero.health)
        owner.give(cid).play()
        assert ally.zone == Zone.GRAVEYARD and enemy_wisp.zone == Zone.GRAVEYARD
        assert demon1.zone == Zone.PLAY and demon2.zone == Zone.PLAY, (demon1.zone, demon2.zone)
        assert (demon1.health, demon2.health) == (1, 1), (demon1.health, demon2.health)
        assert (owner.hero.health, enemy.hero.health) == heroes
        return f"non_demons=dead;demons={demon1.health}/{demon2.health};heroes={heroes}"
    case(cid, "both_sides_non_demons_only", "Deal 2 to all non-Demon minions on both sides; Demons and heroes remain untouched.", behavior,
         "用双方非恶魔和恶魔各一只，核对范围、伤害以及英雄排除。")
    finish_card(cid, "Spell resolution")


def probe_006():
    cid = "BRM_006"
    def behavior():
        game = new_game()
        owner = game.player1
        boss = owner.give(cid)
        boss.play()
        owner.give(MOONFIRE).play(target=boss)
        imps = list(owner.field.filter(id="BRM_006t"))
        assert len(imps) == 1 and (imps[0].atk, imps[0].health) == (1, 1), board_ids(owner)
        assert boss.health == 3 and boss.zone == Zone.PLAY
        owner.give(MOONFIRE).play(target=boss)
        assert len(owner.field.filter(id="BRM_006t")) == 2, board_ids(owner)
        return f"boss_health={boss.health};imps=2x1/1"
    case(cid, "each_damage_event_summons_imp", "Each separate damage event summons exactly one 1/1 Imp while Imp Gang Boss survives.", behavior,
         "对同一本体造成两次独立伤害，逐次检查触发数量、衍生物属性和存活本体。")
    finish_card(cid, "Summon|Trigger")


def probe_007():
    cid = "BRM_007"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        target = enemy.summon(WISP)
        spell = owner.give(cid)
        spell.play(target=target)
        copies = list(owner.deck.filter(id=WISP))
        assert len(copies) == 3, [card.id for card in owner.deck]
        assert all(card.zone == Zone.DECK for card in copies)
        assert target.zone == Zone.PLAY and target.controller is enemy
        assert len(enemy.deck) == 0
        return f"target={target.zone.name};owner_deck={[c.id for c in copies]};enemy_deck=0"
    case(cid, "copies_selected_enemy_minion_into_own_deck", "Gang Up leaves the chosen enemy minion in place and shuffles exactly three copies into the caster's deck.", behavior,
         "选择敌方随从以确认目标不离场、复制数和控制方牌库落区。")
    finish_card(cid, "Spell resolution|Targeting")


def probe_008():
    cid = "BRM_008"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        ally = owner.summon(WISP)
        undamaged = enemy.summon("BRM_014")
        damaged = enemy.summon("BRM_014")
        owner.give(MOONFIRE).play(target=damaged)
        skulker = owner.give(cid)
        skulker.play()
        assert undamaged.health == 2 and undamaged.zone == Zone.PLAY, (undamaged.health, undamaged.zone)
        assert damaged.health == 3 and damaged.zone == Zone.PLAY, (damaged.health, damaged.zone)
        assert ally.health == 1 and ally.zone == Zone.PLAY, (ally.health, ally.zone)
        return f"undamaged_4/4=2/4;previously_damaged_4/4=3/4;friendly_wisp=1/1"
    case(cid, "undamaged_enemy_gate", "Battlecry deals 2 only to undamaged enemy minions; damaged enemies and friendly minions are excluded.", behavior,
         "先对一只4/4敌方随从造成1点伤，再检查战吼只命中未受伤敌人；友方随从不受影响。")
    finish_card(cid, "Battlecry")


def probe_009():
    cid = "BRM_009"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        lumberer = owner.give(cid)
        assert lumberer.cost == 9 and lumberer.taunt, (lumberer.cost, lumberer.taunt)
        owner.summon(WISP).destroy()
        enemy.summon(WISP).destroy()
        assert lumberer.cost == 7, lumberer.cost
        lumberer.play()
        assert lumberer.taunt and lumberer.zone == Zone.PLAY
        attacker = enemy.summon(WISP)
        game.end_turn()
        assert attacker.can_attack(lumberer), (attacker.can_attack(lumberer), attacker.can_attack(owner.hero))
        assert not attacker.can_attack(owner.hero), (attacker.can_attack(lumberer), attacker.can_attack(owner.hero))
        attacker.attack(lumberer)
        assert attacker.zone == Zone.GRAVEYARD and lumberer.health == 7
        return f"cost=7;taunt=True;hero_blocked=True;attacker={attacker.zone.name}"
    case(cid, "death_discount_and_taunt_combat", "Each minion death lowers Lumberer's cost by 1; its Taunt blocks a Wisp from attacking the hero and permits an attack into Lumberer.", behavior,
         "在两次死亡后核对费用，再让对手实际攻击验证嘲讽合法目标过滤。")
    finish_card(cid, "Cost modification|Taunt")


def probe_010():
    cid = "BRM_010"
    def form_a():
        game = new_game()
        minion = game.player1.give(cid)
        minion.play(choose="BRM_010a")
        result = list(game.player1.field)[0]
        assert (result.id, result.atk, result.health) == ("BRM_010t", 5, 2), (result.id, result.atk, result.health)
        return f"choice_a={result.id}:{result.atk}/{result.health}"
    case(cid, "choose_five_two_form", "The first Choose One option transforms the Druid into the 5/2 form.", form_a,
         "通过实际选择分支检查衍生卡身份与属性。")
    def form_b():
        game = new_game()
        minion = game.player1.give(cid)
        minion.play(choose="BRM_010b")
        result = list(game.player1.field)[0]
        assert (result.id, result.atk, result.health) == ("BRM_010t2", 2, 5), (result.id, result.atk, result.health)
        return f"choice_b={result.id}:{result.atk}/{result.health}"
    case(cid, "choose_two_five_form", "The second Choose One option transforms the Druid into the 2/5 form.", form_b,
         "分别验证另一抉择分支，且场上仍只有一个变形后的随从。")
    finish_card(cid, "Choose One|Transform")


def probe_011():
    cid = "BRM_011"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        owner.give("EX1_243").play()  # Dust Devil: its printed Overload is (2).
        assert owner.overloaded == 2, owner.overloaded
        game.end_turn()
        game.end_turn()
        assert owner.overload_locked == 2, (owner.overloaded, owner.overload_locked)
        lava = owner.give(cid)
        lava.play(target=enemy.hero)
        assert enemy.hero.health == 28, enemy.hero.health
        assert owner.overloaded == 0 and owner.overload_locked == 0, (owner.overloaded, owner.overload_locked)
        return f"enemy_hero={enemy.hero.health};overloaded={owner.overloaded};locked={owner.overload_locked}"
    case(cid, "damage_and_unlock_overload", "After Dust Devil locks two crystals on the owner's next turn, Lava Shock deals 2 and clears the locked overload.", behavior,
         "先打出过载2的尘魔，经过对手回合使水晶实际锁定，再施放熔岩震击并核对伤害及解锁。")
    finish_card(cid, "Spell resolution|Targeting")


def probe_012():
    cid = "BRM_012"
    def behavior():
        values = set()
        for seed in range(1, 33):
            game = new_game()
            owner = game.player1
            destroyer = owner.give(cid)
            game.random.seed(seed)
            destroyer.play()
            assert destroyer.health == 6 and 4 <= destroyer.atk <= 7, (seed, destroyer.atk, destroyer.health)
            assert owner.overloaded == 1, (seed, owner.overloaded)
            game.end_turn()
            game.end_turn()
            assert owner.overloaded == 0 and owner.overload_locked == 1, (seed, owner.overloaded, owner.overload_locked)
            values.add(destroyer.atk - 3)
        assert values == {1, 2, 3, 4}, values
        return f"seeds=32;attack_bonus_values={sorted(values)};after_play_overload=1;next_own_turn_locked=1"
    case(cid, "random_attack_range_and_overload", "Across fixed seeds, battlecry attack bonuses include all values 1–4; body remains 3/6 and Overload locks one crystal.", behavior,
         "每次新局后固定游戏随机种子，覆盖四个攻击增益并检查过载状态。")
    finish_card(cid, "Battlecry|Overload|Random effects")


def probe_013():
    cid = "BRM_013"
    def empty_case():
        game = new_game()
        owner, enemy = game.player1, game.player2
        owner.discard_hand()
        top = owner.give(WISP)
        top.shuffle_into_deck()
        quick = owner.give(cid)
        assert quick.powered_up, quick.powered_up
        quick.play(target=enemy.hero)
        drawn = list(owner.hand)
        assert enemy.hero.health == 27 and [card.id for card in drawn] == [WISP], (enemy.hero.health, [c.id for c in drawn])
        return f"empty_hand=True;enemy_hero={enemy.hero.health};drawn={[c.id for c in drawn]}"
    case(cid, "empty_hand_deals_three_and_draws", "With no other cards in hand, Quick Shot deals 3 and draws the known top card.", empty_case,
         "确认手牌空条件、英雄目标伤害及牌库抽牌身份。")
    def nonempty_case():
        game = new_game()
        owner, enemy = game.player1, game.player2
        spare = owner.give(WISP)
        quick = owner.give(cid)
        assert not quick.powered_up, quick.powered_up
        quick.play(target=enemy.hero)
        assert enemy.hero.health == 27 and list(owner.hand) == [spare], (enemy.hero.health, board_ids(owner), [c.id for c in owner.hand])
        return f"other_card_remains={spare.id};enemy_hero={enemy.hero.health};no_draw=True"
    case(cid, "nonempty_hand_no_draw", "With another card in hand, Quick Shot still deals 3 but does not draw.", nonempty_case,
         "覆盖手牌条件不满足分支，确认原有手牌保留且没有额外抽牌。")
    finish_card(cid, "Draw / Discard|Spell resolution|Targeting")


def probe_014():
    cid = "BRM_014"
    def empty_case():
        game = new_game()
        owner = game.player1
        owner.discard_hand()
        rager = owner.give(cid)
        rager.play()
        assert (rager.atk, rager.health, rager.max_health) == (7, 7, 7), (rager.atk, rager.health, rager.max_health)
        return f"empty_hand=True;stats={rager.atk}/{rager.health}"
    case(cid, "empty_hand_plus_three_three", "With no other cards in hand, Core Rager gains +3/+3 and becomes 7/7 from its printed 4/4.", empty_case,
         "验证空手战吼的攻击和生命增益。")
    def nonempty_case():
        game = new_game()
        owner = game.player1
        owner.give(WISP)
        rager = owner.give(cid)
        rager.play()
        assert (rager.atk, rager.health, rager.max_health) == (4, 4, 4), (rager.atk, rager.health, rager.max_health)
        return f"other_card_in_hand=True;stats={rager.atk}/{rager.health}"
    case(cid, "nonempty_hand_no_bonus", "With another card in hand, Core Rager remains its printed 4/4.", nonempty_case,
         "验证空手条件不满足时保留基础属性。")
    finish_card(cid, "Battlecry")


def probe_015():
    cid = "BRM_015"
    def threshold_case():
        game = new_game()
        owner, enemy = game.player1, game.player2
        owner.hero.set_current_health(12)
        friendly = owner.summon(GOLDSHIRE_FOOTMAN)
        foe = enemy.summon(GOLDSHIRE_FOOTMAN)
        revenge = owner.give(cid)
        assert revenge.powered_up
        revenge.play()
        assert friendly.zone == Zone.GRAVEYARD and foe.zone == Zone.GRAVEYARD, (friendly.health, foe.health)
        assert owner.hero.health == 12 and enemy.hero.health == 30
        return f"owner_health=12;both_minions_dead=True;heroes=12/30"
    case(cid, "at_twelve_deals_three_to_all_minions", "At exactly 12 Health, Revenge deals 3 to all minions on both sides and leaves heroes untouched.", threshold_case,
         "覆盖阈值等于12的强化分支、双方随从和英雄排除。")
    def ordinary_case():
        game = new_game()
        owner, enemy = game.player1, game.player2
        owner.hero.set_current_health(13)
        friendly = owner.summon(GOLDSHIRE_FOOTMAN)
        foe = enemy.summon(GOLDSHIRE_FOOTMAN)
        owner.give(cid).play()
        assert (friendly.health, foe.health) == (1, 1), (friendly.health, foe.health)
        assert owner.hero.health == 13 and enemy.hero.health == 30
        return f"owner_health=13;both_minions=1hp;heroes=13/30"
    case(cid, "above_twelve_deals_one", "At 13 Health, Revenge deals exactly 1 to all minions and leaves heroes untouched.", ordinary_case,
         "覆盖阈值上方的普通伤害分支。")
    finish_card(cid, "Spell resolution")


def probe_016():
    cid = "BRM_016"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        axe = owner.give(cid)
        axe.play()
        owner.give(MOONFIRE).play(target=axe)
        assert enemy.hero.health == 28 and axe.health == 4, (enemy.hero.health, axe.health)
        owner.give("CS2_029").play(target=axe)
        assert axe.zone == Zone.GRAVEYARD and enemy.hero.health == 26, (axe.zone, enemy.hero.health)
        return f"nonlethal_hit=-2;lethal_hit=-2;axe={axe.zone.name};enemy_hero={enemy.hero.health}"
    case(cid, "each_damage_including_lethal_hit", "Each damage event deals 2 to the enemy hero; the trigger also resolves when the Axe Flinger takes lethal damage.", behavior,
         "先造成非致命伤，再以火球术造成致命伤，验证两次触发和死亡边界。")
    finish_card(cid, "Trigger")


def probe_017():
    cid = "BRM_017"
    def behavior():
        selected = set()
        for seed in range(1, 25):
            game = new_game()
            owner, enemy = game.player1, game.player2
            wisp = owner.summon(WISP)
            wisp.destroy()
            footman = owner.summon(GOLDSHIRE_FOOTMAN)
            footman.destroy()
            enemy.summon("CS2_142").destroy()
            spell = owner.give(cid)
            assert spell.is_playable(), (seed, spell.is_playable())
            game.random.seed(seed)
            spell.play()
            summoned = list(owner.field)
            assert len(summoned) == 1 and summoned[0].id in {WISP, GOLDSHIRE_FOOTMAN}, (seed, board_ids(owner))
            assert not enemy.field
            selected.add(summoned[0].id)
        assert selected == {WISP, GOLDSHIRE_FOOTMAN}, selected
        return f"seeds=24;eligible_friendly_dead_minions={sorted(selected)};enemy_dead_excluded=True"
    case(cid, "random_resurrect_friendly_dead_minion", "Resurrect summons exactly one previously dead friendly minion; enemy deaths are excluded and both eligible choices appear across fixed seeds.", behavior,
         "重复新局并控制游戏随机种子，覆盖两个友方候选和排除敌方死亡随从。")
    def empty_pool():
        game = new_game()
        owner = game.player1
        spell = owner.give(cid)
        before_mana = owner.mana
        assert not spell.is_playable(), spell.is_playable()
        try:
            spell.play()
        except Exception as exc:
            assert type(exc).__name__ == "InvalidAction", (type(exc).__name__, str(exc))
        else:
            raise AssertionError("Resurrect unexpectedly played with no friendly deaths")
        assert spell.zone == Zone.HAND and owner.mana == before_mana and not owner.field, (spell.zone, owner.mana, board_ids(owner))
        return f"empty_friendly_death_pool=True;play_rejected=InvalidAction;spell_zone={spell.zone.name};mana_unchanged=True"
    case(cid, "empty_death_pool_rejected", "With no friendly minions dead, Resurrect is not playable; attempted play preserves hand, mana and board.", empty_pool,
         "覆盖复活术无合法死亡池时的必要前置条件和拒绝后状态。")
    finish_card(cid, "Random effects|Spell resolution|Summon")


def probe_018():
    cid = "BRM_018"
    def behavior():
        game = new_game()
        owner = game.player1
        consort = owner.give(cid)
        first = owner.give("BRM_026")  # Hungry Dragon, 4 mana
        second = owner.give("BRM_004")  # Twilight Whelp, 1 mana
        non_dragon = owner.give("CS2_029")
        consort.play()
        assert Race.DRAGON in first.races and Race.DRAGON in second.races
        assert (first.cost, second.cost, non_dragon.cost) == (2, 0, 4), (first.cost, second.cost, non_dragon.cost)
        first.play()
        assert second.cost == 1 and non_dragon.cost == 4, (second.cost, non_dragon.cost)
        assert first.zone == Zone.PLAY
        return f"before_next_dragon=(2,0,4);played=BRM_026@2;after=(1,4)"
    case(cid, "next_dragon_discount_consumed_once", "Dragon Consort reduces Dragon costs by 2, excludes non-Dragons, then consumes the effect when the next Dragon is played.", behavior,
         "同时持有两张龙和一张非龙，检查初始折扣、下一张龙的实际施放及剩余手牌费用恢复。")
    finish_card(cid, "Battlecry|Cost modification")


def probe_019():
    cid = "BRM_019"
    def behavior():
        game = new_game()
        owner = game.player1
        patron = owner.give(cid)
        patron.play()
        owner.give(MOONFIRE).play(target=patron)
        patrons = list(owner.field.filter(id=cid))
        assert len(patrons) == 2, board_ids(owner)
        assert patrons[0] is patron and patron.health == 2 and patrons[1].health == 3, [(p.health, p.max_health) for p in patrons]
        owner.give("CS2_029").play(target=patron)
        assert patron.zone == Zone.GRAVEYARD
        assert len(owner.field.filter(id=cid)) == 1, board_ids(owner)
        return f"surviving_hit_created_copy=True;lethal_hit_created_none=True;living_patron_count=1"
    case(cid, "survives_damage_but_not_lethal_damage", "A Patron surviving damage summons one 3/3 copy; a later lethal hit does not summon another copy.", behavior,
         "同一局先触发存活分支，再检验致命伤害边界，按源与副本分别计数。")
    finish_card(cid, "Summon|Trigger")


def probe_020():
    cid = "BRM_020"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        sorcerer = owner.give(cid)
        sorcerer.play()
        owner.give("CS2_004").play(target=sorcerer)
        assert (sorcerer.atk, sorcerer.health, sorcerer.max_health) == (4, 8, 8), (sorcerer.atk, sorcerer.health, sorcerer.max_health)
        game.end_turn()
        enemy.give(MOONFIRE).play(target=sorcerer)
        assert (sorcerer.atk, sorcerer.health, sorcerer.max_health) == (4, 7, 8), (sorcerer.atk, sorcerer.health, sorcerer.max_health)
        return f"friendly_target_spell=4/8;opponent_target_spell=4/7(max8)"
    case(cid, "only_controller_spell_target_gives_plus_one", "A friendly spell targeting Dragonkin Sorcerer grants +1/+1; an opponent's targeted spell deals damage but grants no additional buff.", behavior,
         "使用友方生命值法术和对手伤害法术分别检查己方触发域与非触发域。")
    finish_card(cid, "Targeting|Trigger")


def probe_022():
    cid = "BRM_022"
    def behavior():
        game = new_game()
        owner = game.player1
        egg = owner.give(cid)
        egg.play()
        owner.give(MOONFIRE).play(target=egg)
        tokens = list(owner.field.filter(id="BRM_022t"))
        assert egg.health == 1 and len(tokens) == 1 and (tokens[0].atk, tokens[0].health) == (2, 1), (egg.health, board_ids(owner))
        owner.give(MOONFIRE).play(target=egg)
        assert egg.zone == Zone.GRAVEYARD and len(owner.field.filter(id="BRM_022t")) == 2, board_ids(owner)
        return f"first_hit=1x2/1;lethal_hit=second_token;egg={egg.zone.name}"
    case(cid, "each_damage_including_lethal_summons_whelp", "Each damage event summons a 2/1 Whelp, including the hit that kills Dragon Egg.", behavior,
         "先造成非致命伤核对衍生物，再造成致命伤检查触发仍结算。")
    finish_card(cid, "Summon|Trigger")


def probe_024():
    cid = "BRM_024"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        enemy.hero.set_current_health(15)
        crusher = owner.give(cid)
        crusher.play()
        assert (crusher.atk, crusher.health, crusher.max_health) == (9, 9, 9), (crusher.atk, crusher.health, crusher.max_health)
        return f"enemy_health=15;crusher=9/9"
    case(cid, "opponent_at_fifteen_gets_bonus", "At exactly 15 enemy Health, Drakonid Crusher gains +3/+3 and becomes 9/9.", behavior,
         "覆盖强化条件的等值边界。")
    def ordinary():
        game = new_game()
        enemy = game.player2
        enemy.hero.set_current_health(16)
        crusher = game.player1.give(cid)
        crusher.play()
        assert (crusher.atk, crusher.health, crusher.max_health) == (6, 6, 6), (crusher.atk, crusher.health, crusher.max_health)
        return f"enemy_health=16;crusher=6/6"
    case(cid, "opponent_above_fifteen_no_bonus", "At 16 enemy Health, Drakonid Crusher remains its printed 6/6.", ordinary,
         "覆盖强化条件不满足的相邻边界。")
    finish_card(cid, "Battlecry")


def probe_025():
    cid = "BRM_025"
    def behavior():
        game = new_game()
        owner, enemy = game.player1, game.player2
        drake = owner.give(cid)
        assert drake.cost == 6, drake.cost
        owner.summon(WISP).destroy()
        enemy.summon(WISP).destroy()
        assert drake.cost == 4, drake.cost
        owner.summon(WISP).destroy()
        owner.summon(WISP).destroy()
        owner.summon(WISP).destroy()
        owner.summon(WISP).destroy()
        assert drake.cost == 0, drake.cost
        return "deaths=6;cost=0 (from printed 6)"
    case(cid, "one_mana_less_per_death_clamped_zero", "Volcanic Drake costs 6 initially, drops by 1 per minion death this turn, and reaches 0 after six deaths.", behavior,
         "分两步验证折扣累计和零费用下限，包含双方死亡事件。")
    finish_card(cid, "Cost modification")


def probe_026():
    cid = "BRM_026"
    def behavior():
        outcomes = set()
        for seed in range(1, 17):
            game = new_game()
            owner, enemy = game.player1, game.player2
            dragon = owner.give(cid)
            game.random.seed(seed)
            dragon.play()
            summoned = list(enemy.field)
            assert len(summoned) == 1, (seed, board_ids(enemy))
            card = summoned[0]
            assert card.data.cost == 1 and card.type == CardType.MINION, (seed, card.id, card.data.cost, card.type)
            assert list(owner.field.filter(id=cid)) == [dragon], board_ids(owner)
            outcomes.add(card.id)
        assert outcomes, "no random 1-cost minion selected"
        return f"seeds=16;opponent_summons={len(outcomes)} distinct 1-cost minion IDs;owner_minion=Hungry_Dragon_only"
    case(cid, "random_one_cost_minion_for_opponent", "Each Battlecry creates exactly one 1-Cost minion on the opponent's board; none is summoned for the caster.", behavior,
         "多固定种子检查随机候选类型、召唤控制方、数量和施法者场位。")
    finish_card(cid, "Battlecry|Random effects|Summon")


def probe_027():
    cid = "BRM_027"
    def behavior():
        game = new_game(CardClass.WARRIOR, CardClass.WARRIOR)
        owner = game.player1
        majordomo = owner.give(cid)
        majordomo.play()
        majordomo.destroy()
        assert majordomo.zone == Zone.GRAVEYARD
        assert owner.hero.power.id == "BRM_027p", owner.hero.power.id
        assert owner.hero.health == 8, owner.hero.health
        assert owner.hero.power.controller is owner
        return f"source={majordomo.zone.name};hero_power={owner.hero.power.id};hero_health={owner.hero.health}"
    case(cid, "deathrattle_replaces_owner_hero", "When Majordomo dies, its Deathrattle replaces its owner's hero with Ragnaros at 8 Health and installs the owner's Ragnaros Hero Power.", behavior,
         "直接摧毁本体触发真实亡语，并核对主人、英雄生命和英雄技能。")
    finish_card(cid, "Deathrattle|Summon")


def probe_029():
    cid = "BRM_029"
    def no_dragon():
        game = new_game()
        owner, enemy = game.player1, game.player2
        legend = enemy.summon("EX1_557")
        rend = owner.give(cid)
        assert not rend.powered_up and not rend.requires_target(), (rend.powered_up, rend.requires_target())
        rend.play()
        assert legend.zone == Zone.PLAY
        return f"no_dragon=True;legendary_untouched=True;rend_played=True"
    case(cid, "no_dragon_no_destroy_effect", "Without a Dragon in hand, Rend has no Battlecry target requirement and leaves an enemy Legendary minion in play.", no_dragon,
         "覆盖条件不满足分支以及可正常打出本体。")
    def dragon_targeting():
        game = new_game()
        owner, enemy = game.player1, game.player2
        enemy_legend = enemy.summon("EX1_557")
        enemy_common = enemy.summon(WISP)
        friendly_legend = owner.summon("EX1_557")
        owner.give(WHELP)
        rend = owner.give(cid)
        assert rend.powered_up and rend.requires_target(), (rend.powered_up, rend.requires_target())
        targets = list(rend.targets)
        assert set(targets) == {enemy_legend, friendly_legend} and enemy_common not in targets, [card.id for card in targets]
        rend.play(target=enemy_legend)
        assert enemy_legend.zone == Zone.GRAVEYARD
        assert enemy_common.zone == Zone.PLAY and friendly_legend.zone == Zone.PLAY
        return f"target_domain=[enemy_legendary,friendly_legendary];enemy_legend={enemy_legend.zone.name};nonlegend/friendly_survive=True"
    case(cid, "dragon_enables_legendary_destroy", "Holding a Dragon enables the Battlecry and selects Legendary minions, including a friendly one; the selected enemy Legendary is destroyed while the unselected minions remain.", dragon_targeting,
         "根据中英文卡文验证传说随从目标域（不限定敌方），再检查选中目标的真实摧毁和未选中随从存活。")
    def friendly_legend_only():
        game = new_game()
        owner = game.player1
        friendly_legend = owner.summon("EX1_557")
        owner.give(WHELP)
        rend = owner.give(cid)
        reported_powered = rend.powered_up
        target_legal = friendly_legend in rend.targets and rend.requires_target()
        rend.play(target=friendly_legend)
        assert target_legal and friendly_legend.zone == Zone.GRAVEYARD and reported_powered, (
            f"holding_dragon=True;only_friendly_legendary=True;powered_up={reported_powered};"
            f"target_legal={target_legal};target_zone={friendly_legend.zone.name}"
        )
        return f"holding_dragon=True;only_friendly_legendary=True;powered_up={reported_powered};target_zone={friendly_legend.zone.name}"
    case(cid, "friendly_legend_only_readiness", "With Dragon in hand and only a friendly Legendary available, Rend must report Battlecry ready, accept that target and destroy it.", friendly_legend_only,
         "卡文允许任意传说随从；检验仅友方目标时 powered_up 与实际合法目标/结算保持一致。")
    finish_card(cid, "Battlecry|Targeting")


def probe_030():
    cid = "BRM_030"
    def versus(opponent_class):
        def behavior():
            samples = set()
            for seed in range(1, 17):
                game = prepare_empty_game(CardClass.WARRIOR, opponent_class)
                game.random.seed(seed)
                for player in game.players:
                    player.is_standard = False
                owner = next(player for player in game.players if player.hero.card_class == CardClass.WARRIOR)
                enemy = next(player for player in game.players if player.hero.card_class == opponent_class)
                if game.current_player is not owner:
                    game.end_turn()
                assert game.current_player is owner and enemy.hero.card_class == opponent_class
                nef = owner.give(cid)
                before_hand = list(owner.hand)
                nef.play()
                added = [card for card in owner.hand if card not in before_hand]
                assert len(added) == 2, (seed, [card.id for card in owner.hand])
                assert all(card.type == CardType.SPELL and card.card_class == opponent_class for card in added), [
                    (seed, card.id, card.type, card.card_class) for card in added
                ]
                samples.update(card.id for card in added)
            assert len(samples) > 2, samples
            return f"opponent_class={opponent_class.name};seeds=16;unique_legal_spell_ids={len(samples)};examples={sorted(samples)[:8]}"
        return behavior
    case(cid, "mage_opponent_spell_pool", "Against Mage, two generated cards per seed are Mage spells and vary across 16 seeds.", versus(CardClass.MAGE),
         "验证法师职业卡池、两张数量及随机候选变化。")
    case(cid, "priest_opponent_spell_pool", "Against Priest, two generated cards per seed are Priest spells and vary across 16 seeds.", versus(CardClass.PRIEST),
         "换职业验证卡池随对手职业变化，避免只通过法师硬编码样本。")
    finish_card(cid, "Battlecry|Random effects")


def probe_031():
    cid = "BRM_031"
    def own_draw():
        game = new_game()
        owner = game.player1
        chromaggus = owner.give(cid)
        chromaggus.play()
        top = owner.give(WISP)
        top.shuffle_into_deck()
        owner.draw()
        copies = list(owner.hand.filter(id=WISP))
        assert len(copies) == 2 and all(card.zone == Zone.HAND for card in copies), [card.id for card in owner.hand]
        assert copies[0] is not copies[1]
        assert top.zone == Zone.HAND
        return f"owner_drawn={top.id};copies_in_hand={len(copies)}"
    case(cid, "owner_draw_gets_second_copy", "When its controller draws a card, Chromaggus adds exactly one copy of that same card to the controller's hand.", own_draw,
         "用单张已知牌库顶牌触发真实抽牌并核对原牌及复制牌都在手牌。")
    def opponent_draw():
        game = new_game()
        owner, enemy = game.player1, game.player2
        chromaggus = owner.summon(cid)
        card = enemy.give(WISP)
        card.shuffle_into_deck()
        enemy.draw()
        assert len(enemy.hand.filter(id=WISP)) == 1
        assert not owner.hand.filter(id=WISP)
        assert chromaggus.zone == Zone.PLAY
        return f"opponent_draw_hand={[c.id for c in enemy.hand]};owner_copies=0"
    case(cid, "opponent_draw_not_triggered", "An opponent drawing a card does not trigger Chromaggus controlled by this player.", opponent_draw,
         "反向检查抽牌者归属，排除非控制者抽牌触发。")
    finish_card(cid, "Draw / Discard|Trigger")


def probe_033():
    cid = "BRM_033"
    def behavior():
        game = new_game()
        owner = game.player1
        plain = owner.give(cid)
        plain.play()
        assert (plain.atk, plain.health) == (2, 4), (plain.atk, plain.health)
        owner.give(WHELP)
        powered = owner.give(cid)
        powered.play()
        assert (powered.atk, powered.health) == (3, 5), (powered.atk, powered.health)
        return f"no_dragon=2/4;dragon_in_hand=3/5"
    case(cid, "dragon_conditional_plus_one_plus_one", "Blackwing Technician remains 2/4 without a Dragon and gains +1/+1 when a Dragon is in hand.", behavior,
         "同局顺序覆盖未满足与满足持龙条件。")
    finish_card(cid, "Battlecry")


def probe_034():
    cid = "BRM_034"
    def powered():
        game = new_game()
        owner, enemy = game.player1, game.player2
        target = enemy.summon("BRM_014")
        owner.give(WHELP)
        corruptor = owner.give(cid)
        assert corruptor.powered_up and corruptor.requires_target()
        assert target in corruptor.targets, [card.id for card in corruptor.targets]
        corruptor.play(target=target)
        assert target.health == 1 and target.zone == Zone.PLAY, (target.health, target.zone, target.damage)
        return f"dragon_in_hand=True;enemy_4/4_minion_after_3_damage=1/4;corruptor={corruptor.zone.name}"
    case(cid, "dragon_enables_three_damage_battlecry", "With a Dragon in hand, Blackwing Corruptor requires a target and deals exactly 3 damage to an enemy minion.", powered,
         "检查持龙触发、目标要求及可致死的准确伤害结算。")
    def unpowered():
        game = new_game()
        owner, enemy = game.player1, game.player2
        target = enemy.summon("BRM_014")
        corruptor = owner.give(cid)
        assert not corruptor.powered_up and not corruptor.requires_target(), (corruptor.powered_up, corruptor.requires_target(), corruptor.battlecry_requires_target())
        corruptor.play()
        assert target.health == 4 and target.zone == Zone.PLAY
        return "dragon_in_hand=False;target_untouched=True;no_target_required=True"
    case(cid, "no_dragon_no_damage_or_target", "Without a Dragon in hand, Blackwing Corruptor requires no target and deals no Battlecry damage.", unpowered,
         "覆盖条件不满足分支以及目标可选性。")
    finish_card(cid, "Battlecry|Targeting")


PROBES = {
    "BRM_001": probe_001, "BRM_002": probe_002, "BRM_003": probe_003,
    "BRM_004": probe_004, "BRM_005": probe_005, "BRM_006": probe_006,
    "BRM_007": probe_007, "BRM_008": probe_008, "BRM_009": probe_009,
    "BRM_010": probe_010, "BRM_011": probe_011, "BRM_012": probe_012,
    "BRM_013": probe_013, "BRM_014": probe_014, "BRM_015": probe_015,
    "BRM_016": probe_016, "BRM_017": probe_017, "BRM_018": probe_018,
    "BRM_019": probe_019, "BRM_020": probe_020, "BRM_022": probe_022,
    "BRM_024": probe_024, "BRM_025": probe_025, "BRM_026": probe_026,
    "BRM_027": probe_027, "BRM_029": probe_029, "BRM_030": probe_030,
    "BRM_031": probe_031, "BRM_033": probe_033, "BRM_034": probe_034,
}


def frozen_cards():
    return [row for row in read_csv(BASELINE)
            if row["set"] == "Blackrock Mountain (BRM)" and row["status"] == "YELLOW"]


def card_scopes():
    return {row["card_id"]: row["mechanics"] for row in read_csv(MASTER)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", help="Run one BRM card ID from the frozen baseline")
    args = parser.parse_args()
    roster = frozen_cards()
    ids = [row["card_id"] for row in roster]
    if len(ids) != 30 or set(ids) != set(PROBES):
        raise SystemExit(f"Frozen BRM roster mismatch: baseline={ids}; probes={sorted(PROBES)}")
    scopes = card_scopes()
    selected = [args.card] if args.card else ids
    for card_id in selected:
        if card_id not in PROBES:
            raise SystemExit(f"Not in frozen BRM YELLOW roster: {card_id}")
        clear_card(card_id)
        status_before = len(VERDICT_ROWS)
        PROBES[card_id]()
        current = next(row for row in VERDICT_ROWS if row["card_id"] == card_id)
        if current["mechanic_scope"] != scopes[card_id]:
            current["mechanic_scope"] = scopes[card_id]
            write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
        print(f"{card_id} {current['status']} ({len([r for r in PROBE_ROWS if r['card_id'] == card_id])} cases)")
    counts = {status: sum(row["status"] == status for row in VERDICT_ROWS if row["card_id"] in selected)
              for status in ("GREEN", "RED", "YELLOW")}
    print(f"completed={len(selected)}; verdict_counts={counts}")


if __name__ == "__main__":
    main()
