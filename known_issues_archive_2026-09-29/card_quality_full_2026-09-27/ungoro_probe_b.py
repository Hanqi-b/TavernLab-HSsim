"""Card-specific live probes for the second 44 original Un'Goro YELLOW collectibles."""
import csv
import logging
import random
import sys
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.enums import DISCARDED

logging.disable(logging.CRITICAL)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import FIREBALL, HOLY_LIGHT, MOONFIRE, WISP, prepare_empty_game, prepare_game  # noqa: E402

BASELINE = HERE / "three_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PROBE_OUT = HERE / "ungoro_probe_b.csv"
VERDICT_OUT = HERE / "ungoro_verdict_b.csv"
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


BASE_ROWS = [r for r in read_csv(BASELINE) if r["set"] == "Journey to Un'Goro (UNGORO)"]
BASE_ROWS.sort(key=lambda r: r["card_id"])
OWN_ROWS = BASE_ROWS[45:89]
OWN_IDS = [r["card_id"] for r in OWN_ROWS]
MASTER_BY_ID = {r["card_id"]: r for r in read_csv(MASTER)}
QUALITY_BY_ID = {r["card_id"]: r for r in read_csv(QUALITY)}
PROBE_ROWS = read_csv(PROBE_OUT)
VERDICT_ROWS = read_csv(VERDICT_OUT)


def new_game(card_class=CardClass.MAGE, seed=913):
    random.seed(seed)
    game = prepare_empty_game(card_class, card_class)
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
    return player.give(card_id)


def summon(player, card_id):
    return player.summon(card_id)


def play(player, card_id, target=None):
    card = give(player, card_id)
    if target is None:
        card.play()
    else:
        card.play(target=target)
    return card


def metadata(card_id):
    master = MASTER_BY_ID[card_id]
    old = QUALITY_BY_ID.get(card_id, {})
    return (
        f"EN={master['card_text_en']}; ZH={master['card_text_zh']}; "
        f"source={master['python_source'] or master['xml_source']}; "
        f"existing_tests={master['test_refs_candidate'] or 'none'}; "
        f"prior={old.get('status', 'unknown')}:{old.get('reason', 'no prior reason')}"
    )


def record(card_id, case_id, expected, func, notes):
    try:
        observed = func()
        outcome = "pass"
    except AssertionError as exc:
        observed = str(exc) or "AssertionError"
        if not str(exc):
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            observed = f"AssertionError at {Path(frame.filename).name}:{frame.lineno}"
        outcome = "confirmed_error"
    except Exception as exc:
        observed = f"{type(exc).__name__}: {exc}"
        outcome = "inconclusive"
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if not (r["card_id"] == card_id and r["case_id"] == case_id)]
    PROBE_ROWS.append({
        "card_id": card_id, "case_id": case_id, "expected": expected,
        "observed": observed, "outcome": outcome,
        "notes": f"{notes}; {metadata(card_id)}",
    })
    write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    return outcome, observed


def finish_card(card_id, blocker=None):
    rows = [r for r in PROBE_ROWS if r["card_id"] == card_id]
    errors = [r for r in rows if r["outcome"] == "confirmed_error"]
    inconclusive = [r for r in rows if r["outcome"] == "inconclusive"]
    if errors:
        status = "RED"
        reason = "实战断言确认偏差：" + "；".join(
            f"{r['case_id']} expected={r['expected']} actual={r['observed']}" for r in errors
        )
    elif inconclusive:
        status = "YELLOW"
        reason = "关键行为运行未决：" + "；".join(
            f"{r['case_id']}={r['observed']}" for r in inconclusive
        )
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "本轮逐卡行为用例全部通过：" + "; ".join(
            f"{r['case_id']}={r['observed']}" for r in rows
        )
    master = MASTER_BY_ID[card_id]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS.append({
        "card_id": card_id, "status": status,
        "mechanic_scope": master["mechanics"], "reason": reason,
        "probe_file": PROBE_OUT.name, "notes": metadata(card_id),
    })
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def adapt_choice(player, minion, expect_next=False):
    assert player.choice is not None, "Adapt choice was not offered"
    choices = list(player.choice.cards)
    assert len(choices) == 3, [(c.id, c.name) for c in choices]
    selected = choices[0]
    player.choice.choose(selected)
    assert (player.choice is not None) if expect_next else (player.choice is None)
    assert any(buff.id == f"{selected.id}e" for buff in minion.buffs), (selected.id, [b.id for b in minion.buffs])
    return selected.id


def resolve_all_adapt_choices(player):
    resolved = []
    while player.choice is not None:
        action = player.choice
        assert hasattr(action, "target") and hasattr(action, "cards"), type(action).__name__
        target = action.target
        selected = action.cards[0]
        action.choose(selected)
        assert any(buff.id == f"{selected.id}e" for buff in target.buffs), (target.id, selected.id, [b.id for b in target.buffs])
        resolved.append((target, selected.id))
    return resolved


def tortollan_primalist():
    cid = "UNG_088"
    def discovers_then_casts_selected_spell():
        g = new_game(CardClass.MAGE, 8801); p = g.player1
        scout = play(p, cid)
        choice = p.choice
        assert choice is not None and len(choice.cards) == 3
        selected = choice.cards[0]
        assert selected.type == CardType.SPELL and selected.zone != Zone.HAND
        selected_id = selected.id
        choice.choose(selected)
        assert p.choice is None and scout in p.field
        assert selected.zone in (Zone.GRAVEYARD, Zone.SETASIDE), (selected.id, selected.zone)
        assert all(c.id != selected_id for c in p.hand)
        return f"options={[c.id for c in choice.cards]};selected={selected_id};selected_zone={selected.zone.name};choice={p.choice};hero_health={p.hero.health}/{p.opponent.hero.health};field={[(m.id,m.health) for m in p.field]}"
    record(cid, "battlecry_discovers_spell_and_casts_chosen_card", "Discover presents three spells; after a real choice the selected spell is cast, is not added to hand, and the Primalist remains in play.", discovers_then_casts_selected_spell, "实选候选法术，断言 Choice 关闭、法术不进手牌而进入施放后的区域；记录结算状态。")
    def selected_target_spell_is_cast_at_one_legal_random_target():
        g=new_game(CardClass.MAGE,8807);p,e=g.player1,g.player2
        own=summon(p,"CS2_182");enemy=summon(e,"CS2_182")
        primalist=play(p,cid);choice=p.choice
        fireball=next((c for c in choice.cards if c.id=="CS2_029"),None)
        assert fireball is not None and fireball.type==CardType.SPELL and fireball.requires_target(), [(c.id,c.type,c.requires_target()) for c in choice.cards]
        legal_targets=list(fireball.targets);before_health={target:target.health for target in legal_targets}
        choice.choose(fireball)
        target=fireball.target
        assert target in legal_targets and fireball.zone==Zone.GRAVEYARD and p.choice is None
        if target.type==CardType.HERO:
            assert target.health==before_health[target]-6, (target.id,before_health[target],target.health,target.armor)
        else:
            assert target.zone==Zone.GRAVEYARD or target.health==before_health[target]-6, (target.id,before_health[target],target.health,target.zone.name)
        assert own.zone==Zone.PLAY and enemy.zone==Zone.PLAY
        return f"selected=CS2_029;legal_random_targets={[t.id for t in legal_targets]};actual_target={target.id}/{target.type};target_before={before_health[target]};target_after={target.health}/{target.zone.name};spell={fireball.zone.name};choice={p.choice}"
    record(cid,"random_target_spell_resolves_against_a_legal_target","When the real Discover includes Fireball, choosing it casts it at one of its legal random targets and resolves 6 damage; the selected spell is not kept in hand.",selected_target_spell_is_cast_at_one_legal_random_target,"固定种子提供火球术候选；记录其合法目标集，实选后断言随机选中的目标实际承受6点伤害或死亡。")
    def selected_non_target_spell_resolves_and_adds_its_effect_cards():
        g=new_game(CardClass.MAGE,8807);p,e=g.player1,g.player2
        summon(p,"CS2_182");summon(e,"CS2_182")
        primalist=play(p,cid);choice=p.choice
        rift=next((c for c in choice.cards if c.id=="BOT_101"),None)
        assert rift is not None and rift.type==CardType.SPELL and not rift.requires_target(), [(c.id,c.type,c.requires_target()) for c in choice.cards]
        choice.choose(rift)
        assert rift.zone==Zone.GRAVEYARD and p.choice is None and primalist in p.field
        assert len(p.hand)==2 and all(c.type==CardType.MINION and c.zone==Zone.HAND for c in p.hand), [(c.id,c.type,c.zone.name) for c in p.hand]
        return f"selected=BOT_101;rift={rift.zone.name};choice={p.choice};added_minions={[(c.id,c.zone.name) for c in p.hand]};primalist={primalist.zone.name}"
    record(cid,"selected_non_target_spell_resolves_its_hand_effect","Choosing no-target Astral Rift resolves normally, adds two minions to hand, and closes the Discover without requiring a target.",selected_non_target_spell_resolves_and_adds_its_effect_cards,"同一固定候选池实选无目标的星界裂隙，核对法术施放区域、Choice关闭及新增两张随从手牌。")
    def selected_secret_spell_enters_secret_zone_and_triggers():
        g=new_game(CardClass.MAGE,8806);p,e=g.player1,g.player2
        primalist=play(p,cid);choice=p.choice
        secret=next((c for c in choice.cards if c.id=="LOOT_101"),None)
        assert secret is not None and secret.type==CardType.SPELL and not secret.requires_target(), [(c.id,c.type,c.requires_target()) for c in choice.cards]
        choice.choose(secret)
        assert secret.zone==Zone.SECRET and secret in p.secrets and p.choice is None and primalist in p.field, (secret.zone.name,[c.id for c in p.secrets],p.choice)
        g.end_turn();assert g.current_player is e
        wisp=give(e,WISP);wisp.play()
        assert secret.zone==Zone.GRAVEYARD and secret not in p.secrets and wisp.zone==Zone.GRAVEYARD and e.hero.health==25, (secret.zone.name,[c.id for c in p.secrets],wisp.zone.name,e.hero.health)
        return f"secret_after_cast={Zone.SECRET.name};after_opponent_minion_play=secret:{secret.zone.name},wisp:{wisp.zone.name},enemy_hero={e.hero.health}"
    record(cid,"selected_secret_spell_enters_secret_zone_and_triggers","Choosing Explosive Runes leaves it as an armed Secret; the opponent's 1/1 minion triggers it, dies, and its hero takes the 5 excess damage.",selected_secret_spell_enters_secret_zone_and_triggers,"实选爆炸符文并核对其进入秘密区域；轮到对手打出1/1随从后，检查秘密消耗、随从死亡和溢出伤害。")
    return finish_card(cid)


def gentle_megasaur():
    cid = "UNG_089"
    def adapts_all_friendly_murlocs_not_other_minions():
        g = new_game(CardClass.SHAMAN, 8901); p, e = g.player1, g.player2
        m1 = summon(p, "CS2_168"); m2 = summon(p, "EX1_506")
        other = summon(p, WISP); enemy_murloc = summon(e, "CS2_168")
        play(p, cid)
        choice = p.choice
        assert choice is not None and len(choice.cards)==3, "Battlecry did not offer one shared Adapt choice"
        selected=choice.cards[0]; selected_id=selected.id; choice.choose(selected)
        assert p.choice is None and m1 in p.field and m2 in p.field and other in p.field and enemy_murloc in e.field
        assert any(b.id==f"{selected_id}e" for b in m1.buffs) and any(b.id==f"{selected_id}e" for b in m2.buffs), f"one shared Adapt choice {selected_id} should affect both friendly Murlocs; m1={[b.id for b in m1.buffs]};m2={[b.id for b in m2.buffs]}"
        assert not other.buffs and not enemy_murloc.buffs, ([b.id for b in other.buffs], [b.id for b in enemy_murloc.buffs])
        return f"single_choice={selected_id};friendly_murlocs={[(m.id,m.atk,m.health,[b.id for b in m.buffs]) for m in (m1,m2)]};friendly_non_murloc={other.atk}/{other.health}/{[b.id for b in other.buffs]};enemy_murloc={enemy_murloc.atk}/{enemy_murloc.health}/{[b.id for b in enemy_murloc.buffs]};choice={p.choice}"
    record(cid, "one_adapt_choice_applies_to_all_friendly_murlocs_only", "One shared Adapt choice is applied to both friendly Murlocs; friendly non-Murlocs and enemy Murlocs are unaffected.", adapts_all_friendly_murlocs_not_other_minions, "同局面加入两个己方鱼人、一个己方非鱼人和一个敌方鱼人，实际只选一次 Adapt，再检查共享效果和目标范围。")
    return finish_card(cid, "验证实际 Adapt 增益及目标范围；不同 Adapt 选项的完整效果不在本例穷举。")


def charged_devilsaur():
    cid = "UNG_099"
    def charge_can_attack_minion_but_not_enemy_hero():
        g = new_game(CardClass.HUNTER, 9901); p, e = g.player1, g.player2
        devil = play(p, cid); target = summon(e, "CS2_182")
        assert devil.can_attack() and devil.charge, (devil.can_attack(), devil.charge)
        hero_health = e.hero.health
        try:
            devil.attack(e.hero)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "Charged Devilsaur attacked an enemy hero this turn"
        assert e.hero.health == hero_health and devil.can_attack(), (e.hero.health, hero_health, devil.can_attack())
        devil.attack(target)
        assert target.zone == Zone.GRAVEYARD and devil in p.field and not devil.can_attack()
        return f"face_health={e.hero.health};minion_target={target.zone.name};devil={devil.atk}/{devil.health};remaining_attacks={devil.can_attack()}"
    record(cid, "charge_restricts_hero_attack_but_allows_minion_attack", "Charged Devilsaur cannot attack a hero this turn, but can attack and kill an enemy minion.", charge_can_attack_minion_but_not_enemy_hero, "先尝试攻击敌方英雄并核对失败不消耗攻击，再攻击敌方随从并检查战斗结果。")
    return finish_card(cid)


def verdant_longneck():
    cid = "UNG_100"
    def battlecry_offers_and_applies_exactly_one_adapt():
        g = new_game(CardClass.DRUID, 10001); p = g.player1
        longneck = play(p, cid)
        selected = adapt_choice(p, longneck)
        assert longneck.zone == Zone.PLAY and len(longneck.buffs) == 1 and p.choice is None
        return f"selected={selected};buffs={[b.id for b in longneck.buffs]};stats={longneck.atk}/{longneck.health};zone={longneck.zone.name}"
    record(cid, "battlecry_adapts_once_and_applies_choice", "Battlecry presents an Adapt choice, applies exactly one selected buff, and leaves no pending choice.", battlecry_offers_and_applies_exactly_one_adapt, "实际选择一个 Adapt 选项，断言只增加一项增益并关闭 Choice。")
    return finish_card(cid)


def shellshifter():
    cid = "UNG_101"
    def chooses_stealth_five_three_form():
        g = new_game(CardClass.DRUID, 10101); p = g.player1
        original = give(p, cid); original.play(choose="UNG_101a")
        form = next(m for m in p.field if m.id in ("UNG_101t", "UNG_101t2"))
        assert form.zone == Zone.PLAY and (form.atk, form.max_health) == (5, 3), (form.id, form.atk, form.max_health)
        assert form.stealthed and not form.taunt, (form.id, form.stealthed, form.taunt)
        return f"choice=UNG_101a;result={form.id}/{form.atk}/{form.max_health};stealth={form.stealthed};taunt={form.taunt};original={original.zone.name}"
    def chooses_taunt_three_five_form():
        g = new_game(CardClass.DRUID, 10102); p = g.player1
        original = give(p, cid); original.play(choose="UNG_101b")
        form = next(m for m in p.field if m.id in ("UNG_101t", "UNG_101t2"))
        assert form.zone == Zone.PLAY and (form.atk, form.max_health) == (3, 5), (form.id, form.atk, form.max_health)
        assert form.taunt and not form.stealthed, (form.id, form.taunt, form.stealthed)
        return f"choice=UNG_101b;result={form.id}/{form.atk}/{form.max_health};taunt={form.taunt};stealth={form.stealthed};original={original.zone.name}"
    record(cid, "choose_one_transforms_into_stealth_five_three", "Choosing the first option transforms Shellshifter into a 5/3 with Stealth.", chooses_stealth_five_three_form, "实际选择潜行分支，核对变形后的身材、关键词和场上区域。")
    record(cid, "choose_one_transforms_into_taunt_three_five", "Choosing the second option transforms Shellshifter into a 3/5 with Taunt.", chooses_taunt_three_five_form, "实际选择嘲讽分支，核对变形后的身材、关键词和场上区域。")
    return finish_card(cid)


def evolving_spores():
    cid = "UNG_103"
    def adapts_every_friendly_minion_and_not_enemy():
        g = new_game(CardClass.DRUID, 10301); p, e = g.player1, g.player2
        first = summon(p, WISP); second = summon(p, "CS2_182"); enemy = summon(e, WISP)
        play(p, cid)
        choice=p.choice
        assert choice is not None and len(choice.cards)==3, "Evolving Spores did not offer one shared Adapt choice"
        selected=choice.cards[0]; selected_id=selected.id; choice.choose(selected)
        assert any(b.id==f"{selected_id}e" for b in first.buffs) and any(b.id==f"{selected_id}e" for b in second.buffs), f"one shared Adapt choice {selected_id} should affect both friendly minions; first={[b.id for b in first.buffs]};second={[b.id for b in second.buffs]}"
        assert not enemy.buffs and enemy in e.field, ([b.id for b in enemy.buffs], enemy.zone)
        assert first in p.field and second in p.field and p.choice is None
        return f"single_choice={selected_id};friendly={[ (m.id,[b.id for b in m.buffs]) for m in (first,second)]};enemy={enemy.id}/{[b.id for b in enemy.buffs]};choice={p.choice}"
    record(cid, "one_adapt_choice_applies_to_all_friendly_minions_only", "One shared Adapt choice is applied to every friendly minion; enemy minions are unaffected and the spell resolves.", adapts_every_friendly_minion_and_not_enemy, "己方两只随从加一只敌方随从，实际选择一次 Adapt，检查同一效果施于己方二者、不施于敌方及法术区域。")
    return finish_card(cid, "覆盖多随从目标范围与实际增益；未穷尽 10 种 Adapt 效果。")


def earthen_scales():
    cid = "UNG_108"
    def buffs_friendly_minion_then_gains_its_new_attack_as_armor():
        g = new_game(CardClass.DRUID, 10801); p, e = g.player1, g.player2
        target = summon(p, WISP); enemy_target = summon(e, "CS2_182")
        before_armor = p.hero.armor
        spell = play(p, cid, target)
        assert (target.atk, target.health, target.max_health) == (2, 2, 2), (target.atk, target.health, target.max_health)
        assert p.hero.armor == before_armor + 2, (before_armor, p.hero.armor)
        assert (enemy_target.atk, enemy_target.health) == (4, 5)
        assert spell.zone == Zone.GRAVEYARD and target.zone == Zone.PLAY
        return f"friendly={target.atk}/{target.health}/{target.max_health};armor_delta={p.hero.armor-before_armor};enemy={enemy_target.atk}/{enemy_target.health};spell={spell.zone.name}"
    record(cid, "spell_buffs_friendly_minion_then_gains_new_attack_as_armor", "Friendly target gains +1/+1 first, then its new Attack value is gained as hero Armor.", buffs_friendly_minion_then_gains_its_new_attack_as_armor, "对1/1己方随从施法，明确断言变为2/2后获得2点护甲，并核对敌方随从未变。")
    return finish_card(cid)


def elder_longneck():
    cid = "UNG_109"
    def hand_five_attack_enables_adapt():
        g = new_game(CardClass.DRUID, 10901); p = g.player1
        high = give(p, "UNG_086"); high_attack = high.atk
        assert high_attack >= 5
        longneck = play(p, cid); choice = adapt_choice(p, longneck)
        assert len(longneck.buffs) == 1 and p.choice is None
        return f"high_hand={high.id}/{high_attack};adapt={choice};longneck={longneck.atk}/{longneck.health};buffs={[b.id for b in longneck.buffs]}"
    def low_attack_hand_does_not_enable_adapt():
        g = new_game(CardClass.DRUID, 10902); p = g.player1
        low = give(p, WISP); assert low.atk < 5
        longneck = play(p, cid)
        assert p.choice is None, f"no hand minion has 5 Attack (only {low.id}/{low.atk});unexpected_adapt_target={getattr(p.choice.target,'id',None)}"
        return f"low_hand={low.id}/{low.atk};choice={p.choice};longneck_buffs={[b.id for b in longneck.buffs]}"
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != cid]
    record(cid, "battlecry_adapts_with_hand_minion_at_five_attack", "A 5-Attack minion in hand meets the printed condition and Longneck adapts.", hand_five_attack_enables_adapt, "手牌放入5攻随从后实际选择 Adapt，核对核心正向分支。")
    record(cid, "battlecry_does_not_adapt_without_five_attack_in_hand", "With only a 1-Attack hand minion, Longneck should not offer Adapt.", low_attack_hand_does_not_enable_adapt, "仅将1攻随从留在手牌后打出，检查阈值负例；记录意外触发目标。")
    return finish_card(cid)


def living_mana():
    cid = "UNG_111"
    def converts_crystals_to_treants_and_restores_one_when_dies():
        g = new_game(CardClass.DRUID, 11101); p = g.player1
        p.max_mana = 8; p.used_mana = 0
        spell = play(p, cid)
        treants = [m for m in p.field if m.id == "UNG_111t1"]
        assert len(treants) == 7 and all((m.atk,m.health,m.max_health)==(2,2,2) for m in treants), [(m.id,m.atk,m.health,m.max_health) for m in treants]
        assert p.max_mana == 1 and p.mana == 1 and spell.zone == Zone.GRAVEYARD
        treants[0].destroy()
        assert treants[0].zone == Zone.GRAVEYARD and p.max_mana == 2 and p.mana == 1, (treants[0].zone,p.max_mana,p.mana)
        return f"played={spell.zone.name};treants_before=7;crystals_after={p.max_mana};available_mana={p.mana};dead_token={treants[0].zone.name};restored_crystals={p.max_mana}"
    def ordinary_full_board_preserves_crystals_and_summons_none():
        g = new_game(CardClass.DRUID, 11102); p = g.player1
        p.max_mana = 8; p.used_mana = 0
        existing = [summon(p, "CS2_182") for _ in range(7)]
        spell = play(p, cid)
        assert len(p.field) == 7 and all(m in p.field for m in existing)
        assert p.max_mana == 8 and p.mana == 3 and not [m for m in p.field if m.id == "UNG_111t1"], (p.max_mana,p.mana,[(m.id,m.zone.name) for m in p.field])
        return f"existing_minions={len(existing)};field={len(p.field)};spell={spell.zone.name};max_mana={p.max_mana};mana={p.mana};treants=0"
    def dormant_occupant_full_board_does_not_lose_unsummoned_crystals():
        g = new_game(CardClass.DRUID, 11103); p = g.player1
        p.max_mana = 8; p.used_mana = 0
        existing = [summon(p, "CS2_182") for _ in range(6)]
        dormant = summon(p, "UNG_065t")
        assert dormant.dormant and len(p.field) == 7
        spell = play(p, cid)
        treants = [m for m in p.field if m.id == "UNG_111t1"]
        assert len(p.field) == 7 and len(treants) == 0 and dormant in p.field and all(m in p.field for m in existing)
        actual = (p.mana, p.max_mana, len(treants), len(p.field))
        assert p.max_mana == 8 and p.mana == 3, f"ordinary_full_control=(mana=3,max_mana=8,treants=0,board=7); dormant_full_actual=(mana={p.mana},max_mana={p.max_mana},treants={len(treants)},board={len(p.field)})"
        return f"ordinary_minions={len(existing)};dormant={dormant.id}/{dormant.dormant};field={len(p.field)};treants={len(treants)};spell={spell.zone.name};max_mana={p.max_mana};mana={p.mana};actual={actual}"
    record(cid, "spell_converts_crystals_and_token_death_restores_one", "With 8 crystals and available board space, Living Mana creates 2/2 Treants by converting crystals; a Treant's death restores one crystal.", converts_crystals_to_treants_and_restores_one_when_dies, "8水晶下实际施法，检查令牌数/身材、余水晶，再杀死一只确认亡语恢复1水晶。")
    record(cid, "spell_on_ordinary_full_board_preserves_crystals", "When all seven spaces are occupied by ordinary minions, no Treant can be summoned and unconverted crystals remain.", ordinary_full_board_preserves_crystals_and_summons_none, "普通随从满场实际施法，对照满场保护分支下法力水晶状态。")
    record(cid, "spell_on_dormant_full_board_matches_full_board_behavior", "A Dormant minion occupies one of the seven spaces; an otherwise full board must not consume crystals without summoning Treants.", dormant_occupant_full_board_does_not_lose_unsummoned_crystals, "六个普通随从加一个休眠随从组成七格满场，检查是否仍扣除水晶却无法召唤。")
    return finish_card(cid)


def bright_eyed_scout():
    cid = "UNG_113"
    def draws_known_card_and_sets_its_cost_to_five():
        g = new_game(CardClass.MAGE, 11301); p = g.player1
        drawn = give(p, WISP); drawn.shuffle_into_deck()
        assert drawn.zone == Zone.DECK and drawn.cost == 0
        scout = play(p, cid)
        assert drawn in p.hand and drawn.zone == Zone.HAND and drawn.cost == 5, (drawn.zone, drawn.cost)
        assert len(p.deck) == 0 and scout in p.field
        return f"drawn={drawn.id};cost_before=0;cost_after={drawn.cost};zone={drawn.zone.name};deck={len(p.deck)};scout={scout.zone.name}"
    record(cid, "battlecry_draws_and_sets_drawn_card_cost_to_five", "Scout draws the known deck card and sets its hand cost to 5.", draws_known_card_and_sets_its_cost_to_five, "空手加单张已知牌库随从，实际战吼后核对抽牌身份、区域、费用及牌库数量。")
    return finish_card(cid)


def jungle_giants():
    cid = "UNG_116"
    def quest_counts_summoned_minions_at_five_attack_and_reward_sets_deck_minion_cost_zero():
        g = new_game(CardClass.DRUID, 11601); p = g.player1
        quest = play(p, cid)
        assert quest.zone == Zone.SECRET and quest.progress == 0
        below = summon(p, "CS2_182")
        assert below.atk == 4 and quest.progress == 0, (below.atk, quest.progress)
        for expected in range(1, 5):
            high = summon(p, "UNG_086")
            assert high.atk >= 5 and quest.progress == expected, (high.atk, quest.progress, expected)
        deck_minion = give(p, "CS2_182"); deck_minion.shuffle_into_deck()
        final = summon(p, "UNG_086")
        assert final.atk >= 5 and quest.zone == Zone.GRAVEYARD and quest.progress == 5
        reward = next((c for c in p.hand if c.id == "UNG_116t"), None)
        assert reward is not None and reward.zone == Zone.HAND
        reward.play()
        assert deck_minion.zone == Zone.DECK and deck_minion.cost == 0, (deck_minion.zone, deck_minion.cost)
        assert reward.zone == Zone.PLAY and below in p.field and final in p.field
        return f"progress={quest.progress};below_threshold={below.atk};reward={reward.zone.name};deck_minion_cost={deck_minion.cost};deck_size={len(p.deck)}"
    record(cid, "quest_requires_five_attack_summons_and_barnabus_sets_deck_minions_free", "Four eligible summons plus one 4-Attack nonqualifier do not finish; the fifth >=5 Attack summon completes the quest, and Barnabus makes a deck minion cost 0.", quest_counts_summoned_minions_at_five_attack_and_reward_sets_deck_minion_cost_zero, "用召唤而非仅打出测试阈值；4攻不计数，第5个5攻完成任务，再实际打出班纳布斯检查牌库随从费用。")
    return finish_card(cid)


def primalfin_totem():
    cid = "UNG_201"
    def summons_one_murloc_at_each_owner_turn_end_only():
        g = new_game(CardClass.SHAMAN, 20101); p = g.player1
        totem = play(p, cid)
        assert totem in p.field
        g.end_turn()
        tokens = [m for m in p.field if m.id == "UNG_201t"]
        assert len(tokens) == 1 and tokens[0].zone == Zone.PLAY and (tokens[0].atk,tokens[0].health,tokens[0].max_health)==(1,1,1) and Race.MURLOC in tokens[0].races
        assert g.current_player is p.opponent
        g.end_turn()
        assert len([m for m in p.field if m.id == "UNG_201t"]) == 1, [(m.id,m.zone.name) for m in p.field]
        g.end_turn()
        tokens = [m for m in p.field if m.id == "UNG_201t"]
        assert len(tokens) == 2 and all((m.atk,m.health,m.max_health)==(1,1,1) for m in tokens)
        return f"totem={totem.zone.name};after_first_owner_end=1;after_opponent_end=1;after_second_owner_end={len(tokens)};tokens={[(m.atk,m.health,m.zone.name) for m in tokens]}"
    record(cid, "end_of_owner_turn_summons_one_one_murloc_not_on_opponent_turn", "At each of its controller's turn ends, Primalfin Totem summons one 1/1 Murloc; no token is added at opponent turn end.", summons_one_murloc_at_each_owner_turn_end_only, "逐个结束双方回合，检查触发回合、确切令牌数/身材/鱼人种族和区域。")
    return finish_card(cid)


def fire_plume_harbinger():
    cid = "UNG_202"
    def reduces_only_elementals_in_hand_and_floors_at_zero():
        g = new_game(CardClass.SHAMAN, 20201); p = g.player1
        cheap_elemental = give(p, "UNG_809")
        expensive_elemental = give(p, "UNG_847")
        non_elemental = give(p, "CS2_231")
        assert Race.ELEMENTAL in cheap_elemental.races and Race.ELEMENTAL in expensive_elemental.races
        assert Race.ELEMENTAL not in non_elemental.races
        before = (cheap_elemental.cost, expensive_elemental.cost, non_elemental.cost)
        harbinger = play(p, cid)
        assert (cheap_elemental.cost, expensive_elemental.cost, non_elemental.cost) == (0, before[1]-1, before[2]), (before, cheap_elemental.cost, expensive_elemental.cost, non_elemental.cost)
        assert all(c.zone == Zone.HAND for c in (cheap_elemental, expensive_elemental, non_elemental)) and harbinger in p.field
        return f"before={before};after={(cheap_elemental.cost,expensive_elemental.cost,non_elemental.cost)};elemental_flags={(Race.ELEMENTAL in cheap_elemental.races,Race.ELEMENTAL in expensive_elemental.races,Race.ELEMENTAL in non_elemental.races)}"
    record(cid, "battlecry_reduces_elemental_hand_cards_by_one_only", "Each Elemental in hand costs 1 less with a zero-cost floor; a non-Elemental is unchanged.", reduces_only_elementals_in_hand_and_floors_at_zero, "手牌中放入1费/7费元素和非元素，实际战吼后逐张断言费用、手牌区域和分类。")
    return finish_card(cid)


def glacial_shard():
    cid = "UNG_205"
    def battlecry_freezes_enemy_minion_through_its_attack_turn():
        g = new_game(CardClass.MAGE, 20501); p, e = g.player1, g.player2
        target = summon(e, "CS2_182"); other = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        shard = play(p, cid, target)
        assert target.frozen and not other.frozen and target in e.field and shard in p.field
        g.end_turn()
        assert target.frozen and not target.can_attack() and other.can_attack()
        g.end_turn()
        assert not target.frozen
        g.end_turn()
        assert g.current_player is e and not target.frozen and target.can_attack(), (g.current_player.name,target.frozen,target.can_attack())
        return f"target={target.id};frozen_on_play=True;opponent_turn_blocked=True;other_attackable=True;thawed={not target.frozen};attackable_on_owner_turn={target.can_attack()};shard={shard.zone.name}"
    record(cid, "battlecry_freezes_only_selected_enemy_and_blocks_its_attack", "Glacial Shard freezes the chosen enemy minion, keeps an unrelated enemy unfrozen, blocks the target's next attack, then allows it to thaw.", battlecry_freezes_enemy_minion_through_its_attack_turn, "用两只已可攻击的敌方随从，冻住其一，跨过其回合验证不能攻击及随后解冻。")
    return finish_card(cid)


def stone_sentinel():
    cid = "UNG_208"
    def summons_two_taunt_elementals_only_after_previous_turn_elemental():
        g = new_game(CardClass.SHAMAN, 20801); p = g.player1
        elemental = play(p, "UNG_809"); g.end_turn(); g.end_turn()
        sentinel = play(p, cid)
        tokens = [m for m in p.field if m.id == "UNG_208t"]
        assert len(tokens) == 2 and all((m.atk,m.health,m.max_health)==(2,3,3) and m.taunt and Race.ELEMENTAL in m.races for m in tokens), [(m.id,m.atk,m.health,m.taunt,list(m.races)) for m in tokens]
        assert elemental in p.field and sentinel in p.field and len(p.field) == 4
        g2 = new_game(CardClass.SHAMAN, 20802); p2 = g2.player1
        same_turn_elemental = play(p2, "UNG_809"); sentinel2 = play(p2, cid)
        assert not [m for m in p2.field if m.id == "UNG_208t"] and same_turn_elemental in p2.field and sentinel2 in p2.field
        return f"previous_turn={elemental.id};tokens={[(m.atk,m.health,m.taunt,m.zone.name) for m in tokens]};same_turn_tokens=0;board={len(p.field)}"
    record(cid, "battlecry_summons_two_taunt_elementals_after_prior_turn_elemental_only", "An Elemental played last turn yields two 2/3 Taunt Elementals; an Elemental played only this turn yields none.", summons_two_taunt_elementals_only_after_previous_turn_elemental, "分别跨回合/同回合打出元素，检查两个令牌的数量、身材、嘲讽、种族及条件负例。")
    return finish_card(cid)


def kalimos_primal_lord():
    cid = "UNG_211"
    def prior_turn_elemental_enables_each_invocation_and_same_turn_does_not():
        traces = []
        for option in ("UNG_211a", "UNG_211b", "UNG_211c", "UNG_211d"):
            g = new_game(CardClass.SHAMAN, 21100 + ord(option[-1])); p, e = g.player1, g.player2
            for _ in range(12):
                play(p, MOONFIRE, p.hero)
            assert p.hero.health == 18, p.hero.health
            if option == "UNG_211d":
                enemy_targets = [summon(e, "CS2_182") for _ in range(2)]
            elemental = play(p, "UNG_809"); g.end_turn(); g.end_turn()
            kalimos = play(p, cid)
            assert p.choice is not None and {c.id for c in p.choice.cards} == {"UNG_211a", "UNG_211b", "UNG_211c", "UNG_211d"}, [c.id for c in getattr(p.choice,"cards",[])]
            p.choice.choose(next(c for c in p.choice.cards if c.id == option))
            assert p.choice is None and kalimos in p.field and elemental in p.field
            if option == "UNG_211a":
                summons = [m for m in p.field if m.id == "UNG_211aa"]
                assert len(summons) == 5 and all((m.atk,m.health,m.max_health)==(1,1,1) and Race.ELEMENTAL in m.races for m in summons), [(m.id,m.atk,m.health,list(m.races)) for m in summons]
                assert len(p.field) == 7
                effect = f"summons={len(summons)}"
            elif option == "UNG_211b":
                assert p.hero.health == 30, p.hero.health
                effect = f"friendly_hero={p.hero.health}"
            elif option == "UNG_211c":
                assert e.hero.health == 24, e.hero.health
                effect = f"enemy_hero={e.hero.health}"
            else:
                assert len(enemy_targets) == 2 and all(m.health == 2 for m in enemy_targets), [(m.id,m.health,m.max_health) for m in enemy_targets]
                effect = f"enemy_minions={[m.health for m in enemy_targets]}"
            traces.append(f"{option}:{effect}")
        g2 = new_game(CardClass.SHAMAN, 21199); p2 = g2.player1
        same_turn_elemental = play(p2, "UNG_809"); kalimos2 = play(p2, cid)
        assert p2.choice is None and same_turn_elemental in p2.field and kalimos2 in p2.field
        return ";".join(traces) + ";same_turn_choice=None"
    record(cid, "battlecry_offers_all_four_invocations_only_after_previous_turn_elemental", "After an Elemental last turn, Kalimos offers all four distinct Invocations and each selected branch performs its corresponding effect; a same-turn-only Elemental offers no choice.", prior_turn_elemental_enables_each_invocation_and_same_turn_does_not, "分别实选四种祈咒并断言召唤/治疗/打脸效果，再验证同回合元素不触发。")
    return finish_card(cid)


def terrorscale_stalker():
    cid = "UNG_800"
    def triggers_selected_friendly_deathrattle_without_killing_it():
        g = new_game(CardClass.HUNTER, 80001); p = g.player1
        egg = summon(p, "UNG_083")
        stalker = play(p, cid, egg)
        devils = [m for m in p.field if m.id == "UNG_083t1"]
        assert egg in p.field and egg.zone == Zone.PLAY and len(devils) == 1
        assert (devils[0].atk,devils[0].health,devils[0].max_health)==(5,5,5) and devils[0].zone == Zone.PLAY
        assert stalker in p.field and stalker.zone == Zone.PLAY
        g2 = new_game(CardClass.HUNTER, 80002); p2 = g2.player1
        no_target = play(p2, cid)
        assert no_target in p2.field and len(p2.field) == 1 and p2.choice is None
        return f"egg={egg.zone.name};triggered_devil={devils[0].id}/{devils[0].atk}/{devils[0].health};stalker={stalker.zone.name};optional_no_target={no_target.zone.name}"
    record(cid, "battlecry_triggers_friendly_deathrattle_without_destroying_source", "Stalker triggers a friendly Egg's Deathrattle to summon one 5/5 while Egg remains in play; no eligible target is optional.", triggers_selected_friendly_deathrattle_without_killing_it, "选择蛋触发亡语但不杀死目标，检查令牌；另测无亡语目标仍可正常打出。")
    return finish_card(cid)


def nesting_roc():
    cid = "UNG_801"
    def taunt_only_if_two_other_friendly_minions():
        g = new_game(CardClass.MAGE, 80101); p = g.player1
        one_other = summon(p, WISP)
        roc = play(p, cid)
        assert one_other in p.field and not roc.taunt, (len(p.field),roc.taunt)
        g2 = new_game(CardClass.MAGE, 80102); p2 = g2.player1
        first = summon(p2, WISP); second = summon(p2, "CS2_182")
        roc2 = play(p2, cid)
        assert first in p2.field and second in p2.field and roc2.taunt and roc2 in p2.field
        return f"one_other_taunt={roc.taunt};two_other_taunt={roc2.taunt};boards={len(p.field)}/{len(p2.field)}"
    record(cid, "battlecry_taunt_threshold_counts_other_minions", "Nesting Roc gains Taunt with at least two other friendly minions, but not with only one.", taunt_only_if_two_other_friendly_minions, "分別有1只和恰有2只其他己方随从，检查阈值与本体嘲讽关键词。")
    return finish_card(cid)


def emerald_reaver():
    cid = "UNG_803"
    def battlecry_damages_both_heroes_once():
        g = new_game(CardClass.MAGE, 80301); p, e = g.player1, g.player2
        before = (p.hero.health,e.hero.health)
        reaver = play(p, cid)
        assert (p.hero.health,e.hero.health) == (before[0]-1,before[1]-1), (before,p.hero.health,e.hero.health)
        assert reaver in p.field and reaver.zone == Zone.PLAY
        return f"heroes_before={before};after={(p.hero.health,e.hero.health)};reaver={reaver.zone.name}"
    record(cid, "battlecry_deals_one_damage_to_each_hero", "Both heroes take exactly 1 damage from Emerald Reaver's Battlecry.", battlecry_damages_both_heroes_once, "保留两边英雄施法前生命值，实际战吼后分别断言-1。")
    return finish_card(cid)


def golakka_crawler():
    cid = "UNG_807"
    def destroys_pirate_and_gets_printed_plus_one_plus_one():
        g = new_game(CardClass.MAGE, 80701); p, e = g.player1, g.player2
        pirate = summon(e, "CS2_146"); assert Race.PIRATE in pirate.races
        crawler = play(p, cid, pirate)
        expected = (crawler.data.atk+1,crawler.data.health+1)
        assert pirate.zone == Zone.GRAVEYARD and pirate not in e.field
        assert (crawler.atk,crawler.max_health,crawler.health) == (expected[0],expected[1],expected[1]), f"card_text=+1/+1;printed={crawler.data.atk}/{crawler.data.health};expected={expected};actual={(crawler.atk,crawler.health,crawler.max_health)}"
        assert crawler in p.field and crawler.zone == Zone.PLAY
        return f"pirate={pirate.zone.name};crawler={crawler.atk}/{crawler.health}/{crawler.max_health};expected={expected}"
    record(cid, "battlecry_destroys_pirate_and_gains_exactly_one_one", "Destroy the chosen Pirate and grant Crawler exactly +1/+1.", destroys_pirate_and_gets_printed_plus_one_plus_one, "选择敌方海盗后核对死亡区域、本体增益与卡牌文本+1/+1精确一致。")
    return finish_card(cid)


def stubborn_gastropod():
    cid = "UNG_808"
    def taunt_poisonous_combat_kills_attacking_minion():
        g = new_game(CardClass.MAGE, 80801); p, e = g.player1, g.player2
        snail = play(p, cid)
        assert snail.taunt and snail.poisonous and (snail.atk,snail.max_health)==(1,2)
        target = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        assert snail.can_attack()
        snail.attack(target)
        assert snail.zone == Zone.GRAVEYARD and target.zone == Zone.GRAVEYARD, (snail.zone,target.zone,target.health)
        return f"taunt={snail.taunt};poisonous={snail.poisonous};combat_target={target.zone.name};gastropod={snail.zone.name}"
    record(cid, "keywords_and_poisonous_combat_destroy_target", "Gastropod has Taunt and Poisonous; when it deals combat damage to a minion that minion is destroyed.", taunt_poisonous_combat_kills_attacking_minion, "实际攻击4/5敌方随从，验证剧毒触发且双方死亡状态正确。")
    return finish_card(cid)


def fire_fly():
    cid = "UNG_809"
    def battlecry_adds_one_one_two_elemental_to_hand():
        g = new_game(CardClass.MAGE, 80901); p = g.player1
        fly = play(p, cid)
        tokens = [c for c in p.hand if c.id == "UNG_809t1"]
        assert len(tokens) == 1 and tokens[0].zone == Zone.HAND and (tokens[0].data.atk,tokens[0].data.health)==(1,2) and Race.ELEMENTAL in tokens[0].races
        assert fly in p.field and Race.ELEMENTAL in fly.races
        return f"fly={fly.zone.name};token={tokens[0].id}/{tokens[0].data.atk}/{tokens[0].data.health}/{tokens[0].zone.name};elemental={Race.ELEMENTAL in tokens[0].races}"
    record(cid, "battlecry_adds_one_one_two_elemental_to_hand", "Fire Fly stays in play and adds exactly one 1/2 Elemental to hand.", battlecry_adds_one_one_two_elemental_to_hand, "实际打出火羽精灵，检查令牌数量、数据身材、种族、手牌区域及本体区域。")
    return finish_card(cid)


def stegodon():
    cid = "UNG_810"
    def taunt_blocks_enemy_charge_face_attack_and_can_be_attacked():
        g = new_game(CardClass.WARRIOR, 81001); p, e = g.player1, g.player2
        steg = play(p, cid)
        assert steg in p.field and steg.taunt and (steg.atk,steg.max_health)==(2,6)
        g.end_turn()
        attacker = play(e, "CS2_173")
        assert attacker.charge and attacker.can_attack(), (attacker.id,attacker.charge,attacker.can_attack())
        face_before = p.hero.health
        try:
            attacker.attack(p.hero)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "enemy Charge minion attacked through Stegodon Taunt"
        assert p.hero.health == face_before and attacker.can_attack()
        attacker.attack(steg)
        assert steg.health == 4 and attacker.zone == Zone.GRAVEYARD, (steg.health,attacker.zone)
        return f"taunt={steg.taunt};blocked_face={p.hero.health==face_before};attacker_attackable_after_block={attacker.can_attack()};combat_steg={steg.health};attacker={attacker.zone.name}"
    record(cid, "taunt_blocks_face_and_is_valid_combat_target", "Stegodon has Taunt, blocks a Charge minion from attacking the hero, and can be attacked instead.", taunt_blocks_enemy_charge_face_attack_and_can_be_attacked, "用确有冲锋的敌方随从先尝试打脸，再攻击剑龙，检查阻挡、存活攻击权与战斗伤害。")
    return finish_card(cid)


def sabretooth_stalker():
    cid = "UNG_812"
    def stealth_prevents_targeting_until_stalker_attacks():
        g = new_game(CardClass.HUNTER, 81201); p, e = g.player1, g.player2
        stalker = play(p, cid)
        assert stalker.stealthed and (stalker.atk,stalker.max_health)==(8,2)
        spell = give(e, MOONFIRE); mana_before = e.mana
        try:
            spell.play(target=stalker)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "enemy spell targeted Stealthed Stalker"
        assert spell.zone == Zone.HAND and e.mana == mana_before and stalker.health == 2
        g.end_turn(); g.end_turn()
        assert stalker.can_attack()
        hero_before = e.hero.health
        stalker.attack(e.hero)
        assert not stalker.stealthed and e.hero.health == hero_before-8, (stalker.stealthed,e.hero.health,hero_before)
        g.end_turn()
        assert spell.zone == Zone.HAND
        spell.play(target=stalker)
        assert stalker.health == 1 and spell.zone == Zone.GRAVEYARD and not stalker.stealthed
        return f"initial_stealth=True;rejected_spell_cost_unchanged={e.mana==mana_before};after_attack_stealth={stalker.stealthed};hero_damage={hero_before-e.hero.health};post_attack_spell_targeted={stalker.health};spell={spell.zone.name}"
    record(cid, "stealth_blocks_enemy_spell_until_after_attack", "Stealth blocks enemy targeting; attacking removes Stealth, after which an enemy spell can damage the Stalker.", stealth_prevents_targeting_until_stalker_attacks, "实测对潜行目标施法失败且不付费，再等其攻击破隐，之后对同一目标成功施法。")
    return finish_card(cid)


def stormwatcher():
    cid = "UNG_813"
    def windfury_allows_two_attacks_then_exhausts():
        g = new_game(CardClass.MAGE, 81301); p, e = g.player1, g.player2
        storm = play(p, cid)
        assert storm.windfury and (storm.atk,storm.max_health)==(4,8)
        g.end_turn(); g.end_turn()
        before = e.hero.health
        assert storm.can_attack()
        storm.attack(e.hero)
        assert e.hero.health == before-4 and storm.can_attack(), (e.hero.health,before,storm.can_attack())
        storm.attack(e.hero)
        assert e.hero.health == before-8 and not storm.can_attack(), (e.hero.health,before,storm.can_attack())
        return f"windfury={storm.windfury};first_attack_health={before-4};second_attack_health={e.hero.health};third_attack_available={storm.can_attack()}"
    record(cid, "windfury_grants_two_attacks_per_turn", "Stormwatcher has Windfury, attacks twice for 4 damage each, and cannot attack a third time that turn.", windfury_allows_two_attacks_then_exhausts, "等到随从可攻击后对英雄攻击两次，逐次断言伤害及剩余攻击次数。")
    return finish_card(cid)


def giant_wasp():
    cid = "UNG_814"
    def stealth_poisonous_wasp_cannot_be_targeted_and_trades_for_large_minion():
        g = new_game(CardClass.HUNTER, 81401); p, e = g.player1, g.player2
        wasp = play(p, cid)
        assert wasp.stealthed and wasp.poisonous
        enemy_spell = give(e, MOONFIRE); mana_before = e.mana
        try:
            enemy_spell.play(target=wasp)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc, InvalidAction), type(exc).__name__
        else:
            assert False, "enemy spell targeted Stealthed Giant Wasp"
        assert enemy_spell.zone == Zone.HAND and e.mana == mana_before and wasp.health == wasp.max_health
        target = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        wasp.attack(target)
        assert target.zone == Zone.GRAVEYARD and wasp.zone == Zone.GRAVEYARD, (target.zone,wasp.zone,target.health,wasp.health)
        return f"stealth={wasp.stealthed};poisonous={wasp.poisonous};invalid_target_no_cost={enemy_spell.zone.name}/{e.mana==mana_before};combat_target={target.zone.name};wasp={wasp.zone.name}"
    record(cid, "stealth_poisonous_blocks_targeting_and_kills_combat_target", "Giant Wasp starts Stealthed and Poisonous; enemy targeted spell is rejected, then its attack destroys a larger minion through Poisonous combat.", stealth_poisonous_wasp_cannot_be_targeted_and_trades_for_large_minion, "先检验潜行阻止敌方法术指向且不付费，再让黄蜂攻击4/5目标验证剧毒和死亡区域。")
    return finish_card(cid)


def servant_of_kalimos():
    cid = "UNG_816"
    def discovers_elemental_only_after_prior_turn_elemental():
        g = new_game(CardClass.SHAMAN, 81601); p = g.player1
        elemental = play(p, "UNG_809"); g.end_turn(); g.end_turn()
        servant = play(p, cid)
        choice = p.choice
        assert choice is not None and len(choice.cards) == 3 and all(Race.ELEMENTAL in c.races for c in choice.cards), [(c.id,list(c.races)) for c in getattr(choice,"cards",[])]
        chosen = choice.cards[0]; chosen_id = chosen.id; choice.choose(chosen)
        assert p.choice is None and chosen in p.hand and chosen.zone == Zone.HAND and servant in p.field and elemental in p.field
        g2 = new_game(CardClass.SHAMAN, 81602); p2 = g2.player1
        same_turn = play(p2, "UNG_809"); hand_before_servant = list(p2.hand); servant2 = play(p2, cid)
        assert p2.choice is None and list(p2.hand) == hand_before_servant, (p2.choice,[c.id for c in p2.hand],[c.id for c in hand_before_servant])
        return f"prior_elemental={elemental.id};options={[(c.id,list(c.races)) for c in choice.cards]};selected={chosen_id};same_turn_choice={p2.choice};same_turn_servant={servant2.zone.name}"
    record(cid, "battlecry_discovers_elemental_after_last_turn_elemental_only", "A previous-turn Elemental enables a 3-card Elemental Discover; a same-turn-only Elemental does not.", discovers_elemental_only_after_prior_turn_elemental, "跨回合与同回合分别测试，检查候选种族、真实选择进手牌和条件负例。")
    return finish_card(cid)


def tidal_surge():
    cid = "UNG_817"
    def spell_damages_target_for_four_and_heals_hero_four():
        g = new_game(CardClass.SHAMAN, 81701); p, e = g.player1, g.player2
        for _ in range(5): play(p, MOONFIRE, p.hero)
        assert p.hero.health == 25
        target = summon(e, "CS2_182"); before_hero = p.hero.health
        spell = play(p, cid, target)
        assert target.health == 1 and target.max_health == 5 and target in e.field, (target.health,target.max_health,target.zone)
        assert p.hero.health == before_hero + 4 and spell.zone == Zone.GRAVEYARD, (before_hero,p.hero.health,spell.zone)
        return f"target_after={target.health}/{target.max_health};hero_before={before_hero};hero_after={p.hero.health};spell={spell.zone.name}"
    record(cid, "spell_deals_four_to_minion_and_restores_four_health", "Tidal Surge deals exactly 4 to the selected minion and heals its controller's hero for 4.", spell_damages_target_for_four_and_heals_hero_four, "先将英雄降至25生命，对4/5敌方随从施法，分别断言目标剩1生命和英雄+4。")
    return finish_card(cid)


def volatile_elemental():
    cid = "UNG_818"
    def deathrattle_deals_three_to_one_random_enemy_minion_only():
        damaged_targets = set()
        for seed in range(81810, 81826):
            g = new_game(CardClass.MAGE, seed); p, e = g.player1, g.player2
            friendly = summon(p, "CS2_182")
            enemy = [summon(e, "CS2_182") for _ in range(2)]
            source = play(p, cid); source.destroy()
            damaged = [m for m in enemy if m.health == 2]
            unchanged = [m for m in enemy if m.health == 5]
            assert source.zone == Zone.GRAVEYARD and len(damaged) == 1 and len(unchanged) == 1, [(m.health,m.zone.name) for m in enemy]
            assert friendly.health == 5 and friendly.zone == Zone.PLAY
            damaged_targets.add(enemy.index(damaged[0]))
        assert len(damaged_targets) == 2, f"fixed seeds did not demonstrate both random targets: {damaged_targets}"
        return f"seeds=16;each_run_one_enemy_hit=3;different_random_targets={sorted(damaged_targets)};friendly_untouched=True"
    record(cid, "deathrattle_randomly_hits_one_enemy_minion_for_three", "On death exactly one enemy minion takes 3; friendly minions remain untouched, and fixed seeds reach both eligible enemy targets.", deathrattle_deals_three_to_one_random_enemy_minion_only, "16个固定种子、两只敌方4/5和一只己方4/5，逐局检查仅一个敌方失3且选择具备多样性。")
    return finish_card(cid)


def envenom_weapon():
    cid = "UNG_823"
    def weapon_gains_poisonous_and_kills_large_target_in_combat():
        g = new_game(CardClass.WARRIOR, 82301); p, e = g.player1, g.player2
        weapon = play(p, "CS2_106")
        assert p.weapon is weapon and (weapon.atk,weapon.durability)==(3,2)
        spell = play(p, cid)
        assert p.weapon is weapon and weapon.poisonous and spell.zone == Zone.GRAVEYARD
        target = summon(e, "CS2_182")
        g.end_turn(); g.end_turn()
        p.hero.attack(target)
        assert target.zone == Zone.GRAVEYARD and p.weapon is weapon and weapon.durability == 1, (target.zone,weapon.durability)
        return f"weapon={weapon.id};poisonous={weapon.poisonous};target={target.zone.name};durability={weapon.durability};spell={spell.zone.name}"
    record(cid, "spell_gives_equipped_weapon_poisonous_for_combat", "Envenom Weapon grants Poisonous to the equipped weapon; a weapon attack destroys its large target and consumes one durability.", weapon_gains_poisonous_and_kills_large_target_in_combat, "先装备3/2斧并施法确认关键词，再跨回合攻击4/5随从验证毒性、目标死亡和耐久。")
    return finish_card(cid)


def lakkari_sacrifice():
    cid = "UNG_829"
    def quest_counts_six_actual_discards_and_opens_portal_reward():
        g = new_game(CardClass.WARLOCK, 82901); p = g.player1
        quest = play(p, cid)
        assert quest.zone == Zone.SECRET and quest.progress == 0
        discarded = []
        progress_after_batch = []
        discard_evidence = []
        for batch in range(3):
            fillers = [give(p, WISP), give(p, FIREBALL)]
            felhound = play(p, "UNG_833")
            discard_evidence.append([(card.id,card.zone.name,bool(card.tags.get(DISCARDED, False))) for card in fillers])
            assert all(card.zone == Zone.REMOVEDFROMGAME and card.tags.get(DISCARDED, False) for card in fillers), discard_evidence[-1]
            discarded.extend(fillers)
            progress_after_batch.append(quest.progress)
            assert felhound in p.field and felhound.zone == Zone.PLAY
            if batch == 1:
                g.end_turn(); g.end_turn()
        assert progress_after_batch == [2,4,6], f"actual discard batches={discard_evidence}; quest.progress after each 2-card batch={progress_after_batch}; final={quest.progress}; quest_zone={quest.zone.name}"
        assert quest.zone == Zone.GRAVEYARD and quest.progress == 6
        reward = next((c for c in p.hand if c.id == "UNG_829t1"), None)
        assert reward is not None and reward.zone == Zone.HAND
        portal_card = reward; portal_card.play()
        portal = next((m for m in p.field if m.id == "UNG_829t2"), None)
        assert portal is not None and portal.dormant and portal.zone == Zone.PLAY
        g.end_turn()
        imps = [m for m in p.field if m.id == "UNG_829t3"]
        assert len(imps) == 2 and all(m.zone == Zone.PLAY for m in imps), [(m.id,m.zone.name) for m in p.field]
        return f"progress_after_each_batch={progress_after_batch};discard_evidence={discard_evidence};quest={quest.zone.name};portal={portal.zone.name}/{portal.dormant};end_turn_imps={[(m.id,m.atk,m.health) for m in imps]}"
    record(cid, "quest_progresses_on_six_discards_and_reward_creates_portal", "Three real two-card discard Battlecries progress the quest by 2 each; completion adds Nether Portal, which is Dormant and summons two Imps at owner turn end.", quest_counts_six_actual_discards_and_opens_portal_reward, "逐批真实打出拉卡利地狱犬并断言实际弃牌/进度，完成后打出奖励并验证休眠门户与回合末令牌。")
    return finish_card(cid)


def cruel_dinomancer():
    cid = "UNG_830"
    def deathrattle_summons_discarded_minion_from_this_game():
        g = new_game(CardClass.WARLOCK, 83001); p, e = g.player1, g.player2
        discarded = give(p, WISP)
        soul_fire = play(p, "EX1_308", e.hero)
        assert discarded.zone == Zone.REMOVEDFROMGAME and discarded.tags.get(DISCARDED, False) and soul_fire.zone == Zone.GRAVEYARD
        dinomancer = play(p, cid); dinomancer.destroy()
        summoned = [m for m in p.field if m.id == WISP]
        assert dinomancer.zone == Zone.GRAVEYARD and len(summoned) == 1 and summoned[0].zone == Zone.PLAY, f"dinomancer={dinomancer.zone.name};summoned={[(m.id,m.zone.name,m.tags.get(DISCARDED, False)) for m in summoned]};discarded_original={discarded.zone.name}/{discarded.tags.get(DISCARDED, False)};hand={[c.id for c in p.hand]};field={[(m.id,m.zone.name) for m in p.field]}"
        assert (summoned[0].atk,summoned[0].health,summoned[0].max_health)==(1,1,1)
        return f"discarded_original={discarded.zone.name}/{discarded.tags.get(DISCARDED, False)};dinomancer={dinomancer.zone.name};summoned={[(m.id,m.atk,m.health,m.zone.name) for m in summoned]};soulfire={soul_fire.zone.name}"
    record(cid, "deathrattle_summons_only_discarded_minion_from_current_game", "After a Wisp is truly discarded this game, Cruel Dinomancer's death summons one 1/1 Wisp.", deathrattle_summons_discarded_minion_from_this_game, "用灵魂之火在仅有一张其他手牌时确定弃掉小精灵，再实际杀死恐龙术士。")
    return finish_card(cid)


def corrupting_mist():
    cid = "UNG_831"
    def corrupts_existing_minions_then_destroys_them_at_next_owner_turn_begin():
        g = new_game(CardClass.WARLOCK, 83101); p, e = g.player1, g.player2
        own = summon(p, "CS2_182"); enemy = summon(e, "CS2_182")
        spell = play(p, cid)
        assert own in p.field and enemy in e.field and own.zone == Zone.PLAY and enemy.zone == Zone.PLAY
        assert any(b.id == "UNG_831e" for b in own.buffs) and any(b.id == "UNG_831e" for b in enemy.buffs), ([b.id for b in own.buffs],[b.id for b in enemy.buffs])
        late = summon(p, WISP)
        assert late in p.field and not any(b.id == "UNG_831e" for b in late.buffs)
        g.end_turn()
        assert own in p.field and enemy in e.field and late in p.field
        g.end_turn()
        assert own.zone == Zone.GRAVEYARD and enemy.zone == Zone.GRAVEYARD and late.zone == Zone.PLAY, (own.zone,enemy.zone,late.zone)
        return f"spell={spell.zone.name};during_opponent_turn={[own.zone.name,enemy.zone.name,late.zone.name]};next_owner_begin={[own.zone.name,enemy.zone.name,late.zone.name]};late_minion_survives={late.zone==Zone.PLAY}"
    record(cid, "spell_delays_destruction_until_next_own_turn_and_spares_later_minion", "Corrupting Mist leaves all existing minions in play until its controller's next turn begins, then destroys the corrupted set; a later minion survives.", corrupts_existing_minions_then_destroys_them_at_next_owner_turn_begin, "核对施法即时不灭、敌我随从均腐化、对方回合仍存活、下回合开始摧毁且新随从幸存。")
    return finish_card(cid)


def bloodbloom():
    cid = "UNG_832"
    def next_spell_pays_health_once_then_following_spell_pays_mana():
        g = new_game(CardClass.WARLOCK, 83201); p, e = g.player1, g.player2
        for _ in range(5): play(p, MOONFIRE, p.hero)
        assert p.hero.health == 25
        before_mana = p.mana
        bloom = play(p, cid)
        mana_after_bloom = p.mana
        assert mana_after_bloom == before_mana - bloom.cost
        first_spell = give(p, FIREBALL); fireball_cost = first_spell.cost; health_before_spell = p.hero.health; mana_before_spell = p.mana
        first_spell.play(target=e.hero)
        assert p.hero.health == health_before_spell - fireball_cost and p.mana == mana_before_spell and first_spell.zone == Zone.GRAVEYARD, (health_before_spell,p.hero.health,mana_before_spell,p.mana)
        second_spell = give(p, HOLY_LIGHT); health_before_heal = p.hero.health; mana_before_heal = p.mana
        second_spell.play(target=p.hero)
        assert p.hero.health == health_before_heal + 6 and p.mana == mana_before_heal - second_spell.cost and second_spell.zone == Zone.GRAVEYARD, (health_before_heal,p.hero.health,mana_before_heal,p.mana)
        return f"bloom={bloom.zone.name};first_spell_health_cost={fireball_cost};health_after_first={health_before_spell-fireball_cost};mana_unchanged_first={p.mana+second_spell.cost==mana_before_heal};second_spell_mana_cost={second_spell.cost};health_after_second={p.hero.health};mana_after={p.mana}"
    record(cid, "next_spell_pays_health_once_then_normal_mana_resumes", "Bloodbloom itself costs mana; the next spell costs its printed amount in Health without mana, and the following spell spends mana normally.", next_spell_pays_health_once_then_following_spell_pays_mana, "先伤害英雄，施放血色绽放，再施法火球和圣光术，分别验证生命/法力账目与一次性失效。")
    return finish_card(cid)


def lakkari_felhound():
    cid = "UNG_833"
    def battlecry_discards_two_random_hand_cards_and_keeps_taunt_body():
        survivors = set()
        evidence = []
        for seed in range(83301, 83325):
            g = new_game(CardClass.WARLOCK, seed); p = g.player1
            candidates = [give(p, WISP), give(p, FIREBALL), give(p, HOLY_LIGHT)]
            hound = play(p, cid)
            discarded = [c for c in candidates if c.zone == Zone.REMOVEDFROMGAME]
            still_in_hand = [c for c in candidates if c.zone == Zone.HAND]
            assert len(discarded) == 2 and len(still_in_hand) == 1, (seed,[(c.id,c.zone.name) for c in candidates])
            assert all(c.tags.get(DISCARDED, False) for c in discarded), (seed,[(c.id,c.zone.name,c.tags.get(DISCARDED,False)) for c in candidates])
            assert hound.zone == Zone.PLAY and hound.taunt and len(p.field) == 1, (hound.zone.name,hound.taunt,[(m.id,m.zone.name) for m in p.field])
            survivors.add(still_in_hand[0].id)
            evidence.append((seed, sorted(c.id for c in discarded), still_in_hand[0].id))
        assert len(survivors) >= 2, f"24 seeds always left same card; survivors={sorted(survivors)}"
        return f"seeds=24;sample={evidence[:5]};survivor_ids={sorted(survivors)};discarded_per_run=2;body=PLAY/Taunt"
    record(cid, "battlecry_discards_two_random_hand_cards_and_keeps_taunt_body", "Across fixed seeds exactly two of three known hand cards are truly discarded, the survivor remains in hand, choices vary, and Felhound is a Taunt minion in play.", battlecry_discards_two_random_hand_cards_and_keeps_taunt_body, "每个种子用三张已知手牌实际打出地狱犬，核对恰弃两张、弃牌标签/区域、剩余手牌、随机结果变化及嘲讽本体。")
    return finish_card(cid)


def feeding_time():
    cid = "UNG_834"
    def damages_target_and_summons_three_tokens_even_on_lethal():
        g = new_game(CardClass.WARLOCK, 83401); p,e = g.player1,g.player2
        survives = summon(e, "CS2_182")
        spell = play(p, cid, survives)
        tokens = [m for m in p.field if m.id == "UNG_834t1"]
        assert survives.zone == Zone.PLAY and (survives.health,survives.max_health)==(2,5), (survives.zone.name,survives.health,survives.max_health)
        assert len(tokens)==3 and all((m.atk,m.health,m.zone)==(1,1,Zone.PLAY) for m in tokens), [(m.id,m.atk,m.health,m.zone.name) for m in p.field]
        assert spell.zone == Zone.GRAVEYARD
        g2 = new_game(CardClass.WARLOCK, 83402); p2,e2 = g2.player1,g2.player2
        lethal = summon(e2, WISP)
        spell2 = play(p2, cid, lethal)
        tokens2 = [m for m in p2.field if m.id == "UNG_834t1"]
        assert lethal.zone == Zone.GRAVEYARD and len(tokens2)==3 and all(m.zone==Zone.PLAY for m in tokens2), (lethal.zone.name,[(m.id,m.zone.name) for m in p2.field])
        assert spell2.zone == Zone.GRAVEYARD
        return f"nonlethal_target=2/5/PLAY;nonlethal_tokens={[(m.id,m.atk,m.health) for m in tokens]};lethal_target={lethal.zone.name};lethal_tokens={[(m.id,m.atk,m.health,m.zone.name) for m in tokens2]}"
    record(cid, "spell_deals_three_to_minion_and_summons_three_one_ones", "A 4/5 target survives at 4/2 and three 1/1 Pterrordaxes appear; lethal damage still kills the target and summons all three tokens.", damages_target_and_summons_three_tokens_even_on_lethal, "分别测试目标存活与被击杀两支，断言法术区域、目标区域/生命及三只令牌身材/区域。")
    return finish_card(cid)


def chittering_tunneler():
    cid = "UNG_835"
    def discovers_spell_adds_choice_to_hand_and_damages_hero_by_its_cost():
        selected_evidence = None
        for seed in range(83501, 83541):
            g = new_game(CardClass.WARLOCK, seed); p = g.player1
            before = p.hero.health
            tunneler = play(p, cid)
            choice = p.choice
            if choice is None:
                continue
            assert len(choice.cards) == 3 and all(c.type == CardType.SPELL for c in choice.cards), [(c.id,c.type.name,c.cost) for c in choice.cards]
            selected = max(choice.cards, key=lambda c: c.cost)
            cost = selected.cost; selected_id = selected.id
            choice.choose(selected)
            assert p.choice is None and selected.zone == Zone.HAND and selected in p.hand, (selected.id,selected.zone.name,[c.id for c in p.hand])
            assert p.hero.health == before-cost and tunneler in p.field, (before,p.hero.health,cost,tunneler.zone.name)
            selected_evidence = (seed,selected_id,cost,p.hero.health,[c.id for c in p.hand])
            if cost >= 1:
                break
        assert selected_evidence is not None and selected_evidence[2] >= 1, f"no usable positive-cost spell choice found; last={selected_evidence}"
        return f"seed={selected_evidence[0]};selected={selected_evidence[1]};cost={selected_evidence[2]};hero_health={selected_evidence[3]};hand={selected_evidence[4]};choice=None"
    record(cid, "battlecry_discovers_spell_and_deals_selected_spell_cost_to_hero", "A real three-spell Discover is resolved; the chosen spell is added to hand, and the hero loses exactly that card's cost in Health.", discovers_spell_adds_choice_to_hand_and_damages_hero_by_its_cost, "以固定种子实选候选法术，检查三项均为法术、选择牌进手牌、Choice关闭及英雄生命按该牌费用变化。")
    return finish_card(cid)


def clutchmother_zavas():
    cid = "UNG_836"
    def each_real_discard_returns_zavas_to_hand_and_stacks_two_two():
        g = new_game(CardClass.WARLOCK, 83601); p = g.player1
        zavas = give(p, cid)
        snapshots = []
        for discard_n in (1,2):
            give(p, WISP)
            felhound = play(p, "UNG_833")
            assert zavas.zone == Zone.HAND and zavas in p.hand, (discard_n,zavas.zone.name,[c.id for c in p.hand])
            assert zavas.tags.get(DISCARDED, False), (discard_n,zavas.zone.name,zavas.tags)
            assert (zavas.atk,zavas.max_health)==(2+2*discard_n,2+2*discard_n), (discard_n,zavas.atk,zavas.max_health)
            assert felhound in p.field and felhound.zone==Zone.PLAY
            snapshots.append((discard_n,zavas.zone.name,zavas.atk,zavas.max_health,[b.id for b in zavas.buffs]))
        return f"after_each_discard={snapshots};final_hand={[c.id for c in p.hand]};zavas={zavas.zone.name}/{zavas.atk}/{zavas.max_health}"
    record(cid, "discard_trigger_returns_zavas_to_hand_and_stacks_plus_two_plus_two", "After each of two deterministic real discards, Zavas returns to hand and its Attack/Health increase cumulatively by +2/+2.", each_real_discard_returns_zavas_to_hand_and_stacks_two_two, "每轮仅留 Zavas 与一张小精灵在手后打出会弃两张的地狱犬，确保两次都弃到 Zavas，并检查回手区域和叠加身材。")
    return finish_card(cid)


def tar_lord():
    cid = "UNG_838"
    def attack_gains_four_only_during_opponents_turn():
        g = new_game(CardClass.WARRIOR, 83801); p = g.player1
        lord = play(p,cid)
        own_attack = lord.atk
        assert lord.taunt and lord.zone==Zone.PLAY
        g.end_turn()
        opponent_attack = lord.atk
        assert opponent_attack==own_attack+4 and lord.taunt and lord.zone==Zone.PLAY, (own_attack,opponent_attack,lord.taunt,lord.zone.name)
        g.end_turn()
        assert lord.atk==own_attack and lord.taunt and lord.zone==Zone.PLAY, (own_attack,lord.atk)
        return f"own_turn_attack={own_attack};opponent_turn_attack={opponent_attack};next_own_turn_attack={lord.atk};taunt={lord.taunt}"
    record(cid, "taunt_minion_gains_and_loses_four_attack_with_turn_owner", "Tar Lord has Taunt throughout, gains exactly +4 Attack when the opponent becomes active, and returns to base Attack on its controller's turn.", attack_gains_four_only_during_opponents_turn, "在我方回合、对方回合及下一我方回合读取同一随从攻击力和嘲讽状态。")
    return finish_card(cid)


def hemet_jungle_hunter():
    cid = "UNG_840"
    def battlecry_destroys_own_deck_cost_three_or_less_only():
        g = new_game(CardClass.HUNTER, 84001); p,e = g.player1,g.player2
        own_cards = [give(p, WISP), give(p, "CS2_024"), give(p, "CS2_026"), give(p, "CS2_029"), give(p, "CS2_182")]
        enemy_cards = [give(e, WISP), give(e, "CS2_029")]
        for c in own_cards + enemy_cards:
            c.shuffle_into_deck()
        costs = {c.id:c.cost for c in own_cards}
        assert costs[WISP] == 0 and costs["CS2_024"] == 2 and costs["CS2_026"] == 3 and costs["CS2_029"] == 4 and costs["CS2_182"] == 4, costs
        hemet = play(p,cid)
        own_deck_ids = [c.id for c in p.deck]
        enemy_deck_ids = [c.id for c in e.deck]
        assert set(own_deck_ids)=={"CS2_029","CS2_182"} and len(own_deck_ids)==2, (own_deck_ids,[(c.id,c.cost,c.zone.name) for c in own_cards])
        assert len(enemy_deck_ids)==2 and set(enemy_deck_ids)=={WISP,"CS2_029"}, enemy_deck_ids
        assert hemet.zone==Zone.PLAY and hemet in p.field
        return f"own_costs={costs};own_deck_after={own_deck_ids};enemy_deck_unchanged={enemy_deck_ids};hemet={hemet.zone.name}"
    record(cid, "battlecry_destroys_own_deck_cost_three_or_less_only", "Hemet removes own deck cards costing 0, 2, and exactly 3, retains both 4-cost cards, leaves the opponent's deck untouched, and remains in play.", battlecry_destroys_own_deck_cost_three_or_less_only, "牌库实际放入费用0、2、3、4各类卡，打出后检查己方牌库边界和对手牌库。")
    return finish_card(cid)


def the_voraxx():
    cid = "UNG_843"
    def only_spell_cast_on_voraxx_is_copied_onto_one_one_plant():
        g = new_game(CardClass.PALADIN, 84301); p = g.player1
        voraxx = play(p,cid)
        buff = play(p,"CS2_092",voraxx)
        plants = [m for m in p.field if m.id=="UNG_999t2t1"]
        assert (voraxx.atk,voraxx.max_health)==(7,7) and voraxx.zone==Zone.PLAY, (voraxx.atk,voraxx.max_health,voraxx.zone.name)
        assert len(plants)==1 and (plants[0].atk,plants[0].max_health,plants[0].zone)==(5,5,Zone.PLAY), [(m.id,m.atk,m.max_health,m.zone.name) for m in p.field]
        assert buff.zone==Zone.GRAVEYARD
        g2 = new_game(CardClass.PALADIN,84302); p2=g2.player1
        voraxx2=play(p2,cid); other=summon(p2,WISP)
        buff2=play(p2,"CS2_092",other)
        plants2=[m for m in p2.field if m.id=="UNG_999t2t1"]
        assert (other.atk,other.max_health)==(5,5) and (voraxx2.atk,voraxx2.max_health)==(3,3), (other.atk,other.max_health,voraxx2.atk,voraxx2.max_health)
        assert not plants2 and len(p2.field)==2 and buff2.zone==Zone.GRAVEYARD, ([(m.id,m.zone.name) for m in p2.field],buff2.zone.name)
        return f"targeted_voraxx={voraxx.atk}/{voraxx.max_health};copied_spell_plant={plants[0].id}/{plants[0].atk}/{plants[0].max_health};spell={buff.zone.name};target_other_control=other_{other.atk}/{other.max_health};voraxx_unchanged={voraxx2.atk}/{voraxx2.max_health};plants={len(plants2)}"
    record(cid, "trigger_copies_targeted_spell_once_onto_new_plant_only", "Casting Blessing of Kings on Voraxx buffs it, summons one 1/1 Plant, and applies the copied +4/+4; casting the same spell on another minion does not trigger Voraxx.", only_spell_cast_on_voraxx_is_copied_onto_one_one_plant, "一局把+4/+4法术指向沃拉斯，检查本体、令牌及复制效果；另局指向其他随从做触发目标负例。")
    return finish_card(cid)


def humongous_razorleaf():
    cid = "UNG_844"
    def cannot_attack_even_after_a_full_ready_turn():
        g = new_game(CardClass.DRUID, 84401); p,e=g.player1,g.player2
        razorleaf=play(p,cid); enemy=summon(e,WISP)
        assert razorleaf.zone==Zone.PLAY and not razorleaf.can_attack(), (razorleaf.zone.name,razorleaf.can_attack())
        g.end_turn(); g.end_turn()
        assert g.current_player is p and not razorleaf.can_attack(), (g.current_player,razorleaf.can_attack())
        health=e.hero.health
        try:
            razorleaf.attack(e.hero)
        except Exception as exc:
            from fireplace.exceptions import InvalidAction
            assert isinstance(exc,InvalidAction), type(exc).__name__
        else:
            assert False,"Humongous Razorleaf attacked enemy hero after becoming ready"
        assert e.hero.health==health and razorleaf in p.field and enemy in e.field, (e.hero.health,health,razorleaf.zone.name,enemy.zone.name)
        return f"after_summon_can_attack=False;controller_turn={g.current_player is p};after_ready_can_attack=False;attack_rejected=True;hero_health={e.hero.health};razorleaf={razorleaf.zone.name};enemy={enemy.zone.name}"
    record(cid, "cant_attack_persists_after_summoning_sickness_expires", "The 4/8 Razorleaf cannot attack on entry or after a complete opponent turn, and a rejected hero attack changes neither hero health nor minion zones.", cannot_attack_even_after_a_full_ready_turn, "等待召唤失调消失并实际尝试攻击，核对攻击合法性、英雄生命和双方区域。")
    return finish_card(cid)


def igneous_elemental():
    cid = "UNG_845"
    def deathrattle_adds_two_one_two_elementals_and_silence_suppresses_it():
        g = new_game(CardClass.SHAMAN,84501); p=g.player1
        elemental=play(p,cid); elemental.destroy()
        added=[c for c in p.hand if c.id=="UNG_809t1"]
        assert elemental.zone==Zone.GRAVEYARD and len(added)==2, (elemental.zone.name,[(c.id,c.zone.name) for c in p.hand])
        assert all(c.zone==Zone.HAND and c.type==CardType.MINION and Race.ELEMENTAL in c.races and (c.atk,c.max_health)==(1,2) for c in added), [(c.id,c.zone.name,c.type.name,list(c.races),c.atk,c.max_health) for c in added]
        g2=new_game(CardClass.SHAMAN,84502); p2=g2.player1
        silenced=play(p2,cid); silenced.silence(); silenced.destroy()
        assert silenced.zone==Zone.GRAVEYARD and not p2.hand, (silenced.zone.name,[(c.id,c.zone.name) for c in p2.hand])
        return f"deathrattle_minion={elemental.zone.name};added=[{[(c.id,c.atk,c.max_health,c.zone.name) for c in added]}];silenced_source={silenced.zone.name};cards_after_silenced_death={[c.id for c in p2.hand]}"
    record(cid, "deathrattle_adds_two_elementals_and_silence_removes_trigger", "A normal death adds exactly two 1/2 Elementals to hand; silencing an otherwise identical source before death prevents those cards from being added.", deathrattle_adds_two_one_two_elementals_and_silence_suppresses_it, "分别正常杀死与先沉默再杀死，核对手牌新增数量、种族、身材、区域和亡语抑制。")
    return finish_card(cid)


def shimmering_tempest():
    cid = "UNG_846"
    def deathrattle_adds_one_random_mage_spell_to_hand():
        sampled_ids=set(); evidence=[]
        for seed in range(84601,84625):
            g=new_game(CardClass.MAGE,seed); p=g.player1
            tempest=play(p,cid); before=list(p.hand); tempest.destroy()
            added=[c for c in p.hand if c not in before]
            assert tempest.zone==Zone.GRAVEYARD and len(added)==1, (seed,tempest.zone.name,[(c.id,c.zone.name) for c in p.hand])
            spell=added[0]
            assert spell.zone==Zone.HAND and spell.type==CardType.SPELL and spell.card_class==CardClass.MAGE, (seed,spell.id,spell.zone.name,spell.type.name,spell.card_class)
            sampled_ids.add(spell.id); evidence.append((seed,spell.id,spell.cost))
        assert len(sampled_ids)>=2, f"24 deterministic seeds sampled only one spell: {sorted(sampled_ids)}"
        return f"seeds=24;sample={evidence[:6]};distinct_mage_spells={sorted(sampled_ids)};each_death_added_one=True"
    record(cid, "deathrattle_adds_one_random_mage_spell_to_hand", "Across 24 fixed seeds each death adds exactly one Mage spell to hand, and multiple valid spell IDs are sampled.", deathrattle_adds_one_random_mage_spell_to_hand, "24个固定种子实际死亡，逐局检查只新增一张、卡牌类型/职业/区域，并验证随机结果不恒定。")
    return finish_card(cid)


PROBES = [tortollan_primalist, gentle_megasaur, charged_devilsaur,
          verdant_longneck, shellshifter, evolving_spores, earthen_scales,
          elder_longneck, living_mana, bright_eyed_scout, jungle_giants,
          primalfin_totem, fire_plume_harbinger, glacial_shard,
          stone_sentinel, kalimos_primal_lord, terrorscale_stalker,
          nesting_roc, emerald_reaver, golakka_crawler, stubborn_gastropod,
          fire_fly, stegodon, sabretooth_stalker, stormwatcher, giant_wasp,
          servant_of_kalimos, tidal_surge, volatile_elemental, envenom_weapon,
          lakkari_sacrifice, cruel_dinomancer, corrupting_mist, bloodbloom,
          lakkari_felhound, feeding_time, chittering_tunneler, clutchmother_zavas,
          tar_lord, hemet_jungle_hunter, the_voraxx, humongous_razorleaf,
          igneous_elemental, shimmering_tempest]


def main():
    assert len(OWN_IDS) == 44 and OWN_IDS[0] == "UNG_088" and OWN_IDS[-1] == "UNG_846", (len(OWN_IDS), OWN_IDS[:3], OWN_IDS[-3:])
    stale_case_ids = {
        ("UNG_089", "battlecry_adapts_each_friendly_murloc_only"),
        ("UNG_103", "spell_adapts_all_friendly_minions_only"),
    }
    if any((r["card_id"],r["case_id"]) in stale_case_ids for r in PROBE_ROWS):
        PROBE_ROWS[:] = [r for r in PROBE_ROWS if (r["card_id"],r["case_id"]) not in stale_case_ids]
        write_csv(PROBE_OUT, PROBE_FIELDS, PROBE_ROWS)
    for probe in PROBES:
        status = probe()
        print(f"{probe.__name__}: {status}", flush=True)
    current_ids = {"UNG_088", "UNG_089", "UNG_099", "UNG_100", "UNG_101", "UNG_103", "UNG_108", "UNG_109", "UNG_111", "UNG_113", "UNG_116", "UNG_201", "UNG_202", "UNG_205", "UNG_208", "UNG_211", "UNG_800", "UNG_801", "UNG_803", "UNG_807", "UNG_808", "UNG_809", "UNG_810", "UNG_812", "UNG_813", "UNG_814", "UNG_816", "UNG_817", "UNG_818", "UNG_823", "UNG_829", "UNG_830", "UNG_831", "UNG_832", "UNG_833", "UNG_834", "UNG_835", "UNG_836", "UNG_838", "UNG_840", "UNG_843", "UNG_844", "UNG_845", "UNG_846"}
    active = [r for r in VERDICT_ROWS if r["card_id"] in current_ids]
    active_cases = [r for r in PROBE_ROWS if r["card_id"] in current_ids]
    assert len(active) == len(current_ids) and {r["card_id"] for r in active} == current_ids
    assert len({(r["card_id"],r["case_id"]) for r in active_cases}) == len(active_cases)
    print(f"summary batch_cards={len(active)} probes={len(active_cases)} counts=" + str({s:sum(r["status"]==s for r in active) for s in ("GREEN","YELLOW","RED")}), flush=True)


if __name__ == "__main__":
    main()
