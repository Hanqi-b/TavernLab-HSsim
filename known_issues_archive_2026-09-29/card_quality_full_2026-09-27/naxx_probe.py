"""Per-card behavior probes for collectible Curse of Naxxramas cards."""
import argparse
import csv
import random
import traceback
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Zone
from fireplace.exceptions import InvalidAction
from utils import MOONFIRE, WISP, prepare_empty_game

ROOT = Path(__file__).parent
PROBE_OUT = ROOT / "naxx_probe.csv"
VERDICT_OUT = ROOT / "naxx_verdict.csv"
PROBE_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VERDICT_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


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


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def finish_card(card_id, scope, blocker=None, notes=""):
    card_cases = [r for r in PROBE_ROWS if r["card_id"] == card_id]
    failures = [r for r in card_cases if r["outcome"] == "confirmed_error"]
    unresolved = [r for r in card_cases if r["outcome"] == "inconclusive"]
    if failures:
        status = "RED"
        reason = "确认错误：" + "；".join(f"{r['case_id']}预期[{r['expected']}]，实际[{r['observed']}]" for r in failures)
    elif unresolved:
        status = "YELLOW"
        reason = "行为未决：" + "；".join(f"{r['case_id']}={r['observed']}" for r in unresolved)
    elif blocker:
        status, reason = "YELLOW", blocker
    else:
        status = "GREEN"
        reason = "通过：" + "；".join(f"{r['case_id']}={r['observed']}" for r in card_cases)
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS.append({"card_id": card_id, "status": status, "mechanic_scope": scope,
                         "reason": reason, "probe_file": PROBE_OUT.name, "notes": notes})
    write_csv(VERDICT_OUT, VERDICT_FIELDS, VERDICT_ROWS)
    return status


def clear_card(card_id):
    PROBE_ROWS[:] = [r for r in PROBE_ROWS if r["card_id"] != card_id]
    VERDICT_ROWS[:] = [r for r in VERDICT_ROWS if r["card_id"] != card_id]


def new_game(*args):
    game = prepare_empty_game(*args)
    if game.current_player is not game.player1:
        game.end_turn()
    return game


def haunted_creeper_deathrattle():
    game = new_game()
    player = game.player1
    creeper = player.give("FP1_002")
    creeper.play()
    assert creeper in player.field and creeper.has_deathrattle
    creeper.destroy()
    spiders = list(player.field.filter(id="FP1_002t"))
    assert creeper.zone == Zone.GRAVEYARD
    assert len(spiders) == 2, [m.id for m in player.field]
    assert all((m.atk, m.health) == (1, 1) for m in spiders)
    return f"source={creeper.zone.name};spiders={len(spiders)}x{spiders[0].atk}/{spiders[0].health}"


def haunted_creeper_one_open_slot():
    game = new_game()
    player = game.player1
    creeper = player.summon("FP1_002")
    for _ in range(6):
        player.summon(WISP)
    assert len(player.field) == 7
    creeper.destroy()
    spiders = list(player.field.filter(id="FP1_002t"))
    assert len(player.field) == 7 and len(spiders) == 1, [m.id for m in player.field]
    return f"field={len(player.field)};spiders={len(spiders)}"


def probe_haunted_creeper():
    record("FP1_002", "deathrattle_two_spiders", "Destroying the minion puts it in the graveyard and summons exactly two 1/1 Spectral Spiders.", haunted_creeper_deathrattle, "逐卡验证亡语数量、衍生物属性与来源落区。")
    record("FP1_002", "deathrattle_one_open_slot", "When only one board slot remains, exactly one spider is summoned and the field stays at seven.", haunted_creeper_one_open_slot, "验证亡语召唤受七格上限约束。")
    return finish_card("FP1_002", "Deathrattle|Summon", notes="28 张 YELLOW 中第 1 张完成；未由普通出牌烟测代替效果断言。")


def echoing_ooze_exact_copy():
    game = new_game()
    owner = game.player1
    ooze = owner.give("FP1_003")
    ooze.play()
    ooze.buff(ooze, "FP1_005e")
    assert (ooze.atk, ooze.health) == (2, 3)
    game.end_turn()
    copies = list(owner.field.filter(id="FP1_003"))
    assert len(copies) == 2, [m.id for m in owner.field]
    twin = next(m for m in copies if m is not ooze)
    assert (twin.atk, twin.health) == (ooze.atk, ooze.health), (twin.atk, twin.health, ooze.atk, ooze.health)
    return f"source={ooze.atk}/{ooze.health};copy={twin.atk}/{twin.health};field={len(owner.field)}"


def echoing_ooze_removed_before_turn_end():
    game = new_game()
    owner = game.player1
    ooze = owner.give("FP1_003")
    ooze.play()
    ooze.destroy()
    game.end_turn()
    assert not owner.field.filter(id="FP1_003"), [m.id for m in owner.field]
    return f"source={ooze.zone.name};copies=0"


def probe_echoing_ooze():
    record("FP1_003", "end_turn_exact_copy", "At the end of the owner's turn, summon an exact copy with the source's current 2/3 stats.", echoing_ooze_exact_copy, "打出后对原体加成，检查本回合结束时衍生副本属性同步。")
    record("FP1_003", "source_dies_before_end", "If the source leaves play before turn end, it must not create a copy.", echoing_ooze_removed_before_turn_end, "验证延迟触发依赖来源仍在场。")
    return finish_card("FP1_003", "Battlecry|Summon|Trigger")


def mad_scientist_deathrattle_secret_only():
    game = new_game()
    owner = game.player1
    secret = owner.give("EX1_287")
    secret.shuffle_into_deck()
    nonsecret = owner.give(WISP)
    nonsecret.shuffle_into_deck()
    scientist = owner.give("FP1_004")
    scientist.play()
    scientist.destroy()
    assert secret in owner.secrets, [c.id for c in owner.secrets]
    assert nonsecret in owner.deck and not owner.hand.filter(id="CS2_231")
    assert scientist.zone == Zone.GRAVEYARD
    return f"secret_in_play={secret in owner.secrets};nonsecret_in_deck={nonsecret in owner.deck};deck={len(owner.deck)}"


def mad_scientist_no_secret_left():
    game = new_game()
    owner = game.player1
    nonsecret = owner.give(WISP)
    nonsecret.shuffle_into_deck()
    scientist = owner.give("FP1_004")
    scientist.play()
    scientist.destroy()
    assert not owner.secrets and nonsecret in owner.deck
    return f"secrets={len(owner.secrets)};nonsecret_in_deck={nonsecret in owner.deck}"


def mad_scientist_random_secret_from_multiple_candidates():
    selected_ids = []
    candidate_ids = ("EX1_287", "EX1_594")
    for seed in range(1, 17):
        game = new_game(CardClass.MAGE, CardClass.MAGE)
        owner = game.player1
        secrets = []
        for card_id in candidate_ids:
            secret = owner.give(card_id)
            secret.shuffle_into_deck()
            secrets.append(secret)
        nonsecret = owner.give(WISP)
        nonsecret.shuffle_into_deck()
        scientist = owner.give("FP1_004")
        scientist.play()
        # Seed the engine RNG after setup/shuffling, so this controls the actual choice.
        game.random.seed(seed)
        scientist.destroy()
        selected = [card for card in secrets if card in owner.secrets]
        assert len(selected) == 1, (seed, [c.id for c in owner.secrets], [c.id for c in owner.deck])
        assert selected[0].id in candidate_ids, (seed, selected[0].id)
        remaining = next(card for card in secrets if card is not selected[0])
        assert remaining in owner.deck and nonsecret in owner.deck, (
            seed, remaining.zone, nonsecret.zone, [c.id for c in owner.deck]
        )
        assert scientist.zone == Zone.GRAVEYARD, (seed, scientist.zone)
        selected_ids.append(selected[0].id)
    unique = sorted(set(selected_ids))
    assert unique == sorted(candidate_ids), (selected_ids, unique)
    return f"seeds=16;eligible_secrets={','.join(candidate_ids)};selected={','.join(unique)};nonsecret_always_in_deck=True"


def probe_mad_scientist():
    record("FP1_004", "deathrattle_extracts_secret", "Death puts the deck's Secret into play without drawing its nonsecret card.", mad_scientist_deathrattle_secret_only, "验证从牌库查找 Secret 的落区与非 Secret 保留。")
    record("FP1_004", "no_secret_in_deck", "With no Secret in the deck, death summons nothing and leaves the minion card in the deck.", mad_scientist_no_secret_left, "验证过滤后空池分支。")
    record("FP1_004", "random_choice_between_two_deck_secrets", "Across fixed engine seeds, Mad Scientist selects either of two eligible Secrets; the other Secret and a non-Secret stay in the deck.", mad_scientist_random_secret_from_multiple_candidates, "固定 game.random 种子覆盖两个候选 Secret，并验证非 Secret 不进入候选池。")
    return finish_card("FP1_004", "Deathrattle|Summon")


def shade_turn_start_growth():
    game = new_game()
    owner, opponent = game.player1, game.player2
    shade = owner.give("FP1_005")
    shade.play()
    assert (shade.atk, shade.health, shade.stealthed) == (2, 2, True)
    game.end_turn()
    assert (shade.atk, shade.health) == (2, 2), (shade.atk, shade.health)
    spell = opponent.give(MOONFIRE)
    assert shade not in spell.targets
    old_mana = opponent.mana
    try:
        spell.play(target=shade)
    except InvalidAction:
        pass
    else:
        raise AssertionError("stealthed Shade accepted a targeted spell")
    assert spell in opponent.hand and opponent.mana == old_mana and shade.health == 2
    game.end_turn()
    assert (shade.atk, shade.health, shade.stealthed) == (3, 3, True), (shade.atk, shade.health, shade.stealthed)
    shade.attack(opponent.hero)
    assert not shade.stealthed
    game.end_turn()
    assert shade in spell.targets
    spell.play(target=shade)
    assert shade.health == 2
    return f"enemy_target_rejected=True;owner_start={shade.atk}/{shade.health};stealth_after_attack={shade.stealthed};targetable_after_attack=True;post_spell_health={shade.health}"


def probe_shade():
    record("FP1_005", "own_turn_start_growth", "Shade starts 2/2 Stealth, does not grow at the opponent's start, and becomes 3/3 at its owner's next start.", shade_turn_start_growth, "核对隐身关键字、回合归属及时机与属性增量。")
    return finish_card("FP1_005", "Stealth|Trigger")


def nerubian_egg_deathrattle():
    game = new_game()
    owner = game.player1
    egg = owner.give("FP1_007")
    egg.play()
    assert (egg.atk, egg.health) == (0, 2)
    egg.destroy()
    nerubians = list(owner.field.filter(id="FP1_007t"))
    assert egg.zone == Zone.GRAVEYARD and len(nerubians) == 1
    assert (nerubians[0].atk, nerubians[0].health) == (4, 4), (nerubians[0].atk, nerubians[0].health)
    return f"egg={egg.zone.name};nerubian={nerubians[0].atk}/{nerubians[0].health}"


def probe_nerubian_egg():
    record("FP1_007", "deathrattle_nerubian", "The 0/2 Egg's death summons exactly one 4/4 Nerubian and moves the Egg to the graveyard.", nerubian_egg_deathrattle, "逐卡验证亡语登记、召唤身份、数量和属性。")
    return finish_card("FP1_007", "Deathrattle|Summon")


def spectral_knight_untargetable():
    game = new_game(CardClass.MAGE, CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    knight = opponent.summon("FP1_008")
    spell = owner.give(MOONFIRE)
    power = owner.hero.power
    assert knight not in spell.targets
    assert knight not in power.targets
    old_mana, old_health = owner.mana, knight.health
    for action in (lambda: spell.play(target=knight), lambda: power.use(target=knight)):
        try:
            action()
        except InvalidAction:
            continue
        raise AssertionError("targeting a Spectral Knight unexpectedly succeeded")
    assert spell in owner.hand and owner.mana == old_mana and knight.health == old_health
    return f"spell_target=no;hero_power_target=no;spell_in_hand={spell in owner.hand};knight_health={knight.health}"


def probe_spectral_knight():
    record("FP1_008", "spell_and_hero_power_targeting", "Neither a spell nor a Hero Power may select the Knight; rejected attempts preserve hand, mana, and health.", spectral_knight_untargetable, "对 Spell 与 Mage Hero Power 分别检查合法目标池和拒绝副作用。")
    return finish_card("FP1_008", "Untargetable")


def deathlord_taunt_and_summon():
    game = new_game()
    owner, opponent = game.player1, game.player2
    deathlord = owner.give("FP1_009")
    deathlord.play()
    attacker = opponent.summon(WISP)
    game.end_turn()
    assert deathlord.taunt and attacker.can_attack(deathlord) and not attacker.can_attack(owner.hero), (deathlord.taunt, attacker.can_attack(deathlord), attacker.can_attack(owner.hero))
    try:
        attacker.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("opponent Wisp attacked through Deathlord's Taunt")
    minion = opponent.give(WISP)
    minion.shuffle_into_deck()
    spell = opponent.give(MOONFIRE)
    spell.shuffle_into_deck()
    deathlord.destroy()
    assert minion in opponent.field and spell in opponent.deck, (minion.zone, spell.zone, [m.id for m in opponent.field], [c.id for c in opponent.deck])
    assert deathlord.zone == Zone.GRAVEYARD, deathlord.zone
    return f"taunt={deathlord.taunt};summoned={minion.id};spell_stays={spell in opponent.deck};source={deathlord.zone.name}"


def deathlord_no_minion_in_deck():
    game = new_game()
    owner, opponent = game.player1, game.player2
    deathlord = owner.summon("FP1_009")
    spell = opponent.give(MOONFIRE)
    spell.shuffle_into_deck()
    deathlord.destroy()
    assert not opponent.field and spell in opponent.deck
    return f"opponent_field={len(opponent.field)};spell_stays={spell in opponent.deck}"


def deathlord_random_minion_from_multiple_enemy_deck_candidates():
    selected_ids = []
    candidate_ids = ("CS2_231", "CS2_182")
    for seed in range(1, 17):
        game = new_game(CardClass.MAGE, CardClass.MAGE)
        owner, opponent = game.player1, game.player2
        deathlord = owner.give("FP1_009")
        deathlord.play()
        candidates = []
        for card_id in candidate_ids:
            minion = opponent.give(card_id)
            minion.shuffle_into_deck()
            candidates.append(minion)
        spell = opponent.give(MOONFIRE)
        spell.shuffle_into_deck()
        # Seed after deck construction to control the deathrattle's actual RNG.
        game.random.seed(seed)
        deathlord.destroy()
        selected = [card for card in candidates if card in opponent.field]
        assert len(selected) == 1, (
            seed, [c.id for c in opponent.field], [(c.id, c.zone.name) for c in candidates]
        )
        assert selected[0].controller is opponent, (seed, selected[0].id, selected[0].controller)
        remaining = next(card for card in candidates if card is not selected[0])
        assert remaining in opponent.deck and spell in opponent.deck, (
            seed, remaining.zone, spell.zone, [c.id for c in opponent.deck]
        )
        assert deathlord.zone == Zone.GRAVEYARD, (seed, deathlord.zone)
        selected_ids.append(selected[0].id)
    unique = sorted(set(selected_ids))
    assert unique == sorted(candidate_ids), (selected_ids, unique)
    return f"seeds=16;eligible_enemy_minions={','.join(candidate_ids)};summoned={','.join(unique)};spell_always_in_deck=True;controller=opponent"


def deathlord_full_enemy_board_no_eighth_from_deck():
    game = new_game(CardClass.MAGE, CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    for _ in range(7):
        opponent.summon(WISP)
    known = opponent.give("CS2_182")
    known.shuffle_into_deck()
    deathlord = owner.give("FP1_009")
    deathlord.play()
    deathlord.destroy()
    assert len(opponent.field) == 7 and known.zone == Zone.DECK and len(opponent.deck) == 1, (
        len(opponent.field), known.zone, len(opponent.deck), [m.id for m in opponent.field]
    )
    assert deathlord.zone == Zone.GRAVEYARD, deathlord.zone
    return f"enemy_field_count={len(opponent.field)};known_card_zone={known.zone.name};enemy_deck_count={len(opponent.deck)};deathlord_zone={deathlord.zone.name}"


def probe_deathlord():
    record("FP1_009", "taunt_and_pull_enemy_minion", "Taunt blocks attacks on the hero; death summons an enemy deck minion to the opponent's board without drawing its spell.", deathlord_taunt_and_summon, "检查 Taunt 攻击约束、对手牌库候选过滤、控制权及区域。")
    record("FP1_009", "no_enemy_deck_minion", "If the opponent deck has only spells, death summons no minion and leaves the spell in deck.", deathlord_no_minion_in_deck, "验证无可用随从的亡语候选池分支。")
    record("FP1_009", "random_enemy_minion_between_two_candidates", "Across fixed engine seeds, Deathlord puts either of two enemy deck minions onto the opponent's field; the other minion and a spell stay in that deck.", deathlord_random_minion_from_multiple_enemy_deck_candidates, "固定 game.random 种子覆盖两个敌方牌库随从身份，并验证召唤控制权及法术过滤。")
    record("FP1_009", "full_enemy_board_no_eighth_from_deck", "When the opponent's field is full, Deathlord's deathrattle leaves the eligible minion in the opponent's deck.", deathlord_full_enemy_board_no_eighth_from_deck, "重跑原七格满场边界，确保单卡重跑不丢既有证据。")
    return finish_card("FP1_009", "Deathrattle|Summon|Taunt")


def maexxna_poisonous_combat():
    game = new_game()
    owner, opponent = game.player1, game.player2
    maexxna = owner.give("FP1_010")
    maexxna.play()
    target = opponent.summon("FP1_007t")
    assert target.health >= 4, (target.id, target.health)
    game.end_turn()
    game.end_turn()
    assert maexxna.can_attack(target)
    maexxna.attack(target)
    assert target.dead and target.zone == Zone.GRAVEYARD, (target.health, target.zone, target.dead, maexxna.poisonous)
    assert maexxna in owner.field, (maexxna.zone, maexxna.health, maexxna.poisonous)
    return f"target={target.zone.name};maexxna_health={maexxna.health};poisonous={maexxna.poisonous}"


def probe_maexxna():
    record("FP1_010", "poisonous_actual_combat", "Maexxna's combat damage destroys a high-health target while Maexxna survives.", maexxna_poisonous_combat, "通过真实攻击验证剧毒的致死效果，不以属性标签存在作为证据。")
    return finish_card("FP1_010", "Poisonous")


def webspinner_random_beast_to_hand():
    generated = []
    for seed in range(1, 17):
        random.seed(seed)
        game = new_game()
        owner = game.player1
        webspinner = owner.give("FP1_011")
        webspinner.play()
        webspinner.destroy()
        assert webspinner.zone == Zone.GRAVEYARD, (seed, webspinner.zone)
        assert len(owner.hand) == 1, (seed, [c.id for c in owner.hand])
        card = owner.hand[0]
        assert card.type == CardType.MINION and Race.BEAST in card.races, (seed, card.id, card.type, card.races)
        assert card.zone == Zone.HAND, (seed, card.zone)
        generated.append(card.id)
    unique = sorted(set(generated))
    assert len(unique) > 1, generated
    return f"seeds=16;unique_beasts={','.join(unique)};all_cards_in_hand=True"


def probe_webspinner():
    record("FP1_011", "deathrattle_random_beast", "Death adds exactly one random Beast minion to hand and moves Webspinner to the graveyard.", webspinner_random_beast_to_hand, "固定随机种子并断言候选类型、手牌数量和来源区域。")
    return finish_card("FP1_011", "Deathrattle|Random effects")


def sludge_belcher_deathrattle_and_taunt():
    game = new_game()
    owner, opponent = game.player1, game.player2
    belcher = owner.give("FP1_012")
    belcher.play()
    enemy = opponent.summon(WISP)
    game.end_turn()
    assert belcher.taunt and not enemy.can_attack(owner.hero) and enemy.can_attack(belcher), (belcher.taunt, enemy.can_attack(owner.hero), enemy.can_attack(belcher))
    try:
        enemy.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("opponent Wisp attacked through Sludge Belcher's Taunt")
    belcher.destroy()
    slimes = list(owner.field.filter(id="FP1_012t"))
    assert belcher.zone == Zone.GRAVEYARD and len(slimes) == 1, (belcher.zone, [m.id for m in owner.field])
    assert (slimes[0].atk, slimes[0].health, slimes[0].taunt) == (1, 2, True), (slimes[0].atk, slimes[0].health, slimes[0].taunt)
    assert not enemy.can_attack(owner.hero) and enemy.can_attack(slimes[0]), (enemy.can_attack(owner.hero), enemy.can_attack(slimes[0]))
    try:
        enemy.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("opponent Wisp attacked through Sludge Belcher's Slime")
    enemy.attack(slimes[0])
    assert slimes[0].health == 1 and slimes[0] in owner.field, (slimes[0].health, slimes[0].zone)
    return f"belcher={belcher.zone.name};slime={slimes[0].atk}/{slimes[0].health};taunt_blocks_hero=True;attack_on_slime=True"


def probe_sludge_belcher():
    record("FP1_012", "taunt_and_slime_deathrattle", "Belcher's Taunt constrains enemy attacks; its death summons one 1/2 Slime with Taunt.", sludge_belcher_deathrattle_and_taunt, "同一局内实测本体 Taunt、亡语召唤、衍生物属性与关键词。")
    return finish_card("FP1_012", "Deathrattle|Summon|Taunt")


def kel_thuzad_returns_only_friendly_dead_minions():
    game = new_game()
    owner, opponent = game.player1, game.player2
    kel = owner.summon("FP1_013")
    friendly = owner.summon(WISP)
    enemy = opponent.summon(WISP)
    friendly.destroy()
    enemy.destroy()
    game.end_turn()
    returned = list(owner.field.filter(id=WISP))
    assert len(returned) == 1, [m.id for m in owner.field]
    assert friendly.zone == Zone.GRAVEYARD and enemy.zone == Zone.GRAVEYARD
    assert kel in owner.field and returned[0] is not friendly
    return f"friendly_dead={friendly.zone.name};enemy_dead={enemy.zone.name};friendly_returned={len(returned)};kel_alive={kel in owner.field}"


def kel_thuzad_death_stops_resurrection():
    game = new_game()
    owner = game.player1
    kel = owner.summon("FP1_013")
    friendly = owner.summon(WISP)
    friendly.destroy()
    kel.destroy()
    game.end_turn()
    assert not owner.field.filter(id=WISP), [m.id for m in owner.field]
    return f"kel={kel.zone.name};dead_wisp_returned=0"


def probe_kel_thuzad():
    record("FP1_013", "turn_end_friendly_deaths_only", "At turn end Kel'Thuzad returns a friendly minion that died this turn but not an enemy minion.", kel_thuzad_returns_only_friendly_dead_minions, "真实结束回合，分别杀死敌我随从，检查复生归属与数量。")
    record("FP1_013", "source_dead_before_turn_end", "If Kel'Thuzad leaves play first, it does not return the friendly minion that died that turn.", kel_thuzad_death_stops_resurrection, "验证回合结束触发器的来源离场边界。")
    return finish_card("FP1_013", "Summon|Trigger")


def stalagg_partner_condition():
    game = new_game()
    owner = game.player1
    stalagg = owner.summon("FP1_014")
    stalagg.destroy()
    assert not owner.field.filter(id="FP1_014t"), [m.id for m in owner.field]
    feugen = owner.summon("FP1_015")
    feugen.destroy()
    thaddiuses = list(owner.field.filter(id="FP1_014t"))
    assert len(thaddiuses) == 1 and (thaddiuses[0].atk, thaddiuses[0].health) == (11, 11), [(m.id, m.atk, m.health) for m in owner.field]
    return f"stalagg_without_feugen=0;feugen_then_stalagg=thaddius_{thaddiuses[0].atk}/{thaddiuses[0].health}"


def stalagg_both_die_in_combat():
    game = new_game()
    stalagg = game.player1.summon("FP1_014")
    game.end_turn()
    feugen = game.player2.summon("FP1_015")
    game.end_turn()
    stalagg.attack(feugen)
    left_p1 = list(game.player1.field.filter(id="FP1_014t"))
    left_p2 = list(game.player2.field.filter(id="FP1_014t"))
    assert stalagg.dead and feugen.dead, (stalagg.health, feugen.health)
    assert len(left_p1) + len(left_p2) == 1, (len(left_p1), len(left_p2))
    return f"both_dead=True;thaddius_count={len(left_p1)+len(left_p2)};controller={'player1' if left_p1 else 'player2'}"


def probe_stalagg():
    record("FP1_014", "partner_death_condition", "Stalagg does not summon Thaddius without Feugen's death; after Feugen dies, Stalagg's death summons one 11/11 Thaddius.", stalagg_partner_condition, "对照配对亡语的未满足与满足条件，并检查召唤数值。")
    record("FP1_014", "stalagg_and_feugen_die_together", "If Stalagg and Feugen die in the same combat, exactly one Thaddius is produced.", stalagg_both_die_in_combat, "检查同一战斗死亡批次，避免双亡语重复或漏召唤。")
    return finish_card("FP1_014", "Deathrattle|Summon")


def feugen_partner_condition():
    game = new_game()
    owner = game.player1
    feugen = owner.summon("FP1_015")
    feugen.destroy()
    assert not owner.field.filter(id="FP1_014t"), [m.id for m in owner.field]
    stalagg = owner.summon("FP1_014")
    stalagg.destroy()
    thaddiuses = list(owner.field.filter(id="FP1_014t"))
    assert len(thaddiuses) == 1 and (thaddiuses[0].atk, thaddiuses[0].health) == (11, 11), [(m.id, m.atk, m.health) for m in owner.field]
    return f"feugen_without_stalagg=0;stalagg_then_feugen=thaddius_{thaddiuses[0].atk}/{thaddiuses[0].health}"


def probe_feugen():
    record("FP1_015", "partner_death_condition", "Feugen does not summon Thaddius without Stalagg's death; after Stalagg dies, Feugen's death summons one 11/11 Thaddius.", feugen_partner_condition, "反向验证配对亡语条件，分别断言未满足与满足分支。")
    record("FP1_015", "stalagg_and_feugen_die_together", "If Stalagg and Feugen die in the same combat, exactly one Thaddius is produced.", stalagg_both_die_in_combat, "单独挂到 Feugen 判定上复核同战斗死亡批次。")
    return finish_card("FP1_015", "Deathrattle|Summon")


def wailing_soul_silences_friendly_others():
    game = new_game()
    owner, opponent = game.player1, game.player2
    egg = owner.give("FP1_007")
    egg.play()
    taunt = owner.give("CS1_042")
    taunt.play()
    enemy = opponent.summon("CS1_042")
    soul = owner.give("FP1_016")
    soul.play()
    assert egg.silenced and taunt.silenced and not enemy.silenced and not soul.silenced, (egg.silenced, taunt.silenced, enemy.silenced, soul.silenced)
    assert not taunt.taunt
    egg.destroy()
    assert not owner.field.filter(id="FP1_007t"), [m.id for m in owner.field]
    return f"friendly_egg_silenced={egg.silenced};friendly_taunt_removed={not taunt.taunt};enemy_untouched={not enemy.silenced};soul_untouched={not soul.silenced};egg_death_tokens=0"


def probe_wailing_soul():
    record("FP1_016", "silence_friendly_minions_only", "Wailing Soul silences its other friendly minions, removes their Taunt/Deathrattle, and leaves enemy minions and itself unsilenced.", wailing_soul_silences_friendly_others, "实测作用域及被沉默后的 Taunt、亡语移除。")
    return finish_card("FP1_016", "Battlecry|Silence")


def weblord_battlecry_cost_aura():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly_battlecry = owner.give("CS2_189")
    enemy_battlecry = opponent.give("CS2_189")
    friendly_plain = owner.give("CS1_042")
    assert (friendly_battlecry.cost, enemy_battlecry.cost, friendly_plain.cost) == (1, 1, 1)
    weblord = owner.give("FP1_017")
    weblord.play()
    active = (friendly_battlecry.cost, enemy_battlecry.cost, friendly_plain.cost)
    assert active == (3, 3, 1), active
    weblord.destroy()
    restored = (friendly_battlecry.cost, enemy_battlecry.cost, friendly_plain.cost)
    assert restored == (1, 1, 1), restored
    return f"costs_before=1/1/1;while_active={active};after_source_leaves={restored}"


def probe_weblord():
    record("FP1_017", "battlecry_minion_cost_aura", "Weblord raises friendly and enemy Battlecry minion costs by 2, leaves a non-Battlecry minion unchanged, and removes the increase when it dies.", weblord_battlecry_cost_aura, "验证费用变化目标域、非战吼排除及来源离场更新。")
    return finish_card("FP1_017", "Aura|Battlecry|Continuous effect / Update|Cost modification")


def duplicate_secret_copies_friendly_death():
    game = new_game()
    owner = game.player1
    secret = owner.give("FP1_018")
    secret.play()
    dead = owner.give(WISP)
    dead.play()
    game.end_turn()
    game.player2.give(MOONFIRE).play(target=dead)
    copies = list(owner.hand.filter(id=WISP))
    assert len(copies) == 2, [c.id for c in owner.hand]
    assert secret not in owner.secrets and dead.zone == Zone.GRAVEYARD
    assert copies[0] is not copies[1] and all(c.zone == Zone.HAND for c in copies)
    return f"friendly_minion_copies={len(copies)};unique_entities={copies[0] is not copies[1]};secret_consumed={secret not in owner.secrets};source={dead.zone.name}"


def duplicate_ignores_enemy_death():
    game = new_game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("FP1_018")
    secret.play()
    enemy = opponent.summon(WISP)
    game.end_turn()
    opponent.give(MOONFIRE).play(target=enemy)
    assert secret in owner.secrets and not owner.hand.filter(id=WISP)
    return f"enemy_dead={enemy.zone.name};secret_stays={secret in owner.secrets};copies=0"


def duplicate_full_hand_waits_for_space():
    game = new_game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("FP1_018")
    secret.play()
    dying1 = owner.give(WISP)
    dying1.play()
    dying2 = owner.give(WISP)
    dying2.play()
    for _ in range(10):
        owner.give("GVG_093")
    assert len(owner.hand) == 10
    game.end_turn()
    opponent.give(MOONFIRE).play(target=dying1)
    assert secret in owner.secrets and not owner.hand.filter(id=WISP)
    owner.hand[0].discard()
    opponent.give(MOONFIRE).play(target=dying2)
    copies = list(owner.hand.filter(id=WISP))
    assert secret not in owner.secrets and len(owner.hand) == 10 and len(copies) == 1, (secret in owner.secrets, len(owner.hand), len(copies))
    return f"full_hand_first_death_keeps_secret=True;one_slot_second_death_copies={len(copies)};hand={len(owner.hand)};secret_consumed={secret not in owner.secrets}"


def probe_duplicate():
    record("FP1_018", "friendly_death_adds_two_copies", "A friendly minion death consumes Duplicate and creates two distinct copies of that minion in hand.", duplicate_secret_copies_friendly_death, "验证秘密触发、实体副本数、原体落区和 secret 消耗。")
    record("FP1_018", "enemy_death_does_not_trigger", "An enemy minion death leaves Duplicate set and adds no cards.", duplicate_ignores_enemy_death, "验证亡语/奥秘事件只观察己方随从死亡。")
    record("FP1_018", "full_hand_delays_duplicate", "At a full hand, the first friendly death leaves Duplicate set; after one slot opens, the next death adds one copy and consumes it.", duplicate_full_hand_waits_for_space, "复核满手牌下暂不消耗奥秘及仅可容纳一张副本的边界。")
    return finish_card("FP1_018", "Secret|Spell resolution|Trigger")


def poison_seeds_replaces_both_sides():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly = [owner.summon(WISP) for _ in range(2)]
    enemy = opponent.summon("CS1_042")
    spell = owner.give("FP1_019")
    spell.play()
    friendly_treants = list(owner.field.filter(id="FP1_019t"))
    enemy_treants = list(opponent.field.filter(id="FP1_019t"))
    assert all(m.dead and m.zone == Zone.GRAVEYARD for m in friendly + [enemy])
    assert len(friendly_treants) == 2 and len(enemy_treants) == 1, (len(friendly_treants), len(enemy_treants))
    assert all((m.atk, m.health) == (2, 2) for m in friendly_treants + enemy_treants)
    assert spell.zone == Zone.GRAVEYARD
    return f"destroyed=2+1;treants=2+1;stats=2/2;spell={spell.zone.name}"


def poison_seeds_full_board_replacement():
    game = new_game()
    owner, opponent = game.player1, game.player2
    for _ in range(7):
        owner.summon(WISP)
        opponent.summon(WISP)
    spell = owner.give("FP1_019")
    before = (len(owner.field), len(opponent.field))
    assert before == (7, 7), before
    spell.play()
    friendly_treants = list(owner.field.filter(id="FP1_019t"))
    enemy_treants = list(opponent.field.filter(id="FP1_019t"))
    assert len(owner.field) == len(opponent.field) == 7, (len(owner.field), len(opponent.field), [m.id for m in owner.field], [m.id for m in opponent.field])
    assert len(friendly_treants) == len(enemy_treants) == 7, (len(friendly_treants), len(enemy_treants))
    return f"fields={len(owner.field)}/{len(opponent.field)};treants={len(friendly_treants)}/{len(enemy_treants)}"


def probe_poison_seeds():
    record("FP1_019", "destroy_and_replace_both_sides", "Poison Seeds destroys two friendly and one enemy minion, then replaces them with the same side counts of 2/2 Treants.", poison_seeds_replaces_both_sides, "检查双方死亡、替换数量、属性和法术区域。")
    record("FP1_019", "replace_seven_on_full_boards", "With seven minions on each side, the spell replaces all fourteen with seven Treants per side without exceeding board limits.", poison_seeds_full_board_replacement, "逐侧验证满场清除后的召唤容量与数量。")
    return finish_card("FP1_019", "Spell resolution|Summon")


def avenge_random_buff():
    chosen_positions = []
    for seed in range(1, 13):
        random.seed(seed)
        game = new_game()
        owner = game.player1
        secret = owner.give("FP1_020")
        secret.play()
        dying, survivor_a, survivor_b = [owner.summon(WISP) for _ in range(3)]
        game.end_turn()
        kill = game.player2.give(MOONFIRE)
        kill.play(target=dying)
        survivors = (survivor_a, survivor_b)
        buffed = [index for index, m in enumerate(survivors) if (m.atk, m.health) == (4, 3)]
        assert len(buffed) == 1, (seed, [(m.atk, m.health) for m in survivors], secret in owner.secrets)
        assert tuple((m.atk, m.health) for m in survivors if (m.atk, m.health) != (4, 3)) == ((1, 1),)
        assert secret not in owner.secrets and dying.zone == Zone.GRAVEYARD
        chosen_positions.append(buffed[0])
    assert set(chosen_positions) == {0, 1}, chosen_positions
    return f"seeds=12;random_choices_seen={sorted(set(chosen_positions))};each_death_buffed_one_3/2=True"


def avenge_no_survivor_or_enemy_death():
    game = new_game()
    owner, opponent = game.player1, game.player2
    secret = owner.give("FP1_020")
    secret.play()
    friendly = owner.summon(WISP)
    enemy = opponent.summon(WISP)
    game.end_turn()
    kill_enemy = opponent.give(MOONFIRE)
    kill_enemy.play(target=enemy)
    assert secret in owner.secrets and list(owner.field.filter(id=WISP)) == [friendly], (secret in owner.secrets, [m.id for m in owner.field])
    kill_friendly = opponent.give(MOONFIRE)
    kill_friendly.play(target=friendly)
    assert secret in owner.secrets and not owner.field
    return f"enemy_death_secret_stays=True;last_friendly_death_secret_stays={secret in owner.secrets};field={len(owner.field)}"


def probe_avenge():
    record("FP1_020", "random_buff_after_friendly_death", "When a friendly minion dies with survivors, Avenge consumes itself and grants exactly one random survivor +3/+2 across 12 fixed seeds.", avenge_random_buff, "核验触发域、增益数值及随机候选变化。")
    record("FP1_020", "enemy_or_last_minion_death", "Enemy minion death and a friendly last-minion death leave Avenge set and grant no buff.", avenge_no_survivor_or_enemy_death, "覆盖不触发敌方死亡和无剩余友方目标分支。")
    return finish_card("FP1_020", "Random effects|Secret|Spell resolution|Trigger")


def deaths_bite_breaks_on_second_attack():
    game = new_game()
    owner, opponent = game.player1, game.player2
    weapon = owner.give("FP1_021")
    weapon.play()
    friendly_wisp = owner.summon(WISP)
    friendly_survivor = owner.summon("CS2_182")
    enemy_wisp = opponent.summon(WISP)
    enemy_survivor = opponent.summon("CS2_182")
    owner.hero.attack(opponent.hero)
    assert owner.weapon is weapon and weapon.durability == 1 and opponent.hero.health == 26, (owner.weapon, weapon.durability, opponent.hero.health)
    game.end_turn()
    game.end_turn()
    owner.hero.attack(opponent.hero)
    assert weapon.zone == Zone.GRAVEYARD
    assert friendly_wisp.dead and enemy_wisp.dead
    assert friendly_survivor.health == enemy_survivor.health == 4, (friendly_survivor.health, enemy_survivor.health)
    assert owner.hero.health == 30 and opponent.hero.health == 22, (owner.hero.health, opponent.hero.health)
    return f"weapon={weapon.zone.name};wisps_dead={friendly_wisp.dead}/{enemy_wisp.dead};survivors_health={friendly_survivor.health}/{enemy_survivor.health};heroes=30/22"


def probe_deaths_bite():
    record("FP1_021", "weapon_deathrattle_on_second_attack", "After Death's Bite's second attack, its deathrattle deals 1 to every minion on both sides, kills Wisps, leaves Yetis at 4 health, and does not damage heroes.", deaths_bite_breaks_on_second_attack, "真实装备并攻击两回合，检查武器破坏时点、全场范围、伤害和区域。")
    return finish_card("FP1_021", "Deathrattle|Weapon")


def voidcaller_summons_demon_without_battlecry():
    game = new_game()
    owner = game.player1
    voidcaller = owner.give("FP1_022")
    voidcaller.play()
    demon = owner.give("EX1_310")
    non_demon = owner.give(WISP)
    voidcaller.destroy()
    assert demon in owner.field and demon.zone == Zone.PLAY
    assert non_demon in owner.hand and non_demon.zone == Zone.HAND
    assert voidcaller.zone == Zone.GRAVEYARD
    assert demon.can_attack(), "summoned Doomguard should retain Charge"
    return f"demon={demon.id}:{demon.zone.name};non_demon={non_demon.zone.name};charge_attack={demon.can_attack()};source={voidcaller.zone.name}"


def voidcaller_no_demon_in_hand():
    game = new_game()
    owner = game.player1
    voidcaller = owner.summon("FP1_022")
    non_demon = owner.give(WISP)
    voidcaller.destroy()
    assert non_demon in owner.hand and not owner.field
    return f"no_demon_summoned=True;wisp_stays={non_demon.zone.name}"


def voidcaller_random_demon_from_multiple_candidates_without_battlecry():
    selected_ids = []
    candidate_ids = ("EX1_310", "EX1_313")
    for seed in range(1, 25):
        game = new_game(CardClass.WARLOCK, CardClass.WARLOCK)
        owner = game.player1
        voidcaller = owner.give("FP1_022")
        voidcaller.play()
        demons = [owner.give(card_id) for card_id in candidate_ids]
        non_demons = [owner.give(WISP), owner.give(WISP)]
        assert all(demon.type == CardType.MINION and Race.DEMON in demon.races for demon in demons), (
            [(d.id, d.type, d.races) for d in demons]
        )
        hero_health = owner.hero.health
        game.random.seed(seed)
        voidcaller.destroy()
        selected = [card for card in demons if card in owner.field]
        assert len(selected) == 1, (seed, [c.id for c in owner.field], [(c.id, c.zone.name) for c in demons])
        summoned = selected[0]
        remaining = next(card for card in demons if card is not summoned)
        assert summoned.controller is owner and summoned.zone == Zone.PLAY, (seed, summoned.id, summoned.zone, summoned.controller)
        assert remaining in owner.hand and all(card in owner.hand for card in non_demons), (
            seed, remaining.zone, [(c.id, c.zone.name) for c in non_demons]
        )
        assert owner.hero.health == hero_health, (seed, summoned.id, hero_health, owner.hero.health)
        if summoned.id == "EX1_310":
            assert summoned.can_attack(), (seed, summoned.id, summoned.can_attack())
        selected_ids.append(summoned.id)
    unique = sorted(set(selected_ids))
    assert unique == sorted(candidate_ids), (selected_ids, unique)
    return f"seeds=24;eligible_demons={','.join(candidate_ids)};summoned={','.join(unique)};other_demon_and_two_wisps_stay_in_hand=True;battlecry_damage_or_discard=False"


def probe_voidcaller():
    record("FP1_022", "deathrattle_puts_demon_from_hand", "Death summons the only Demon from hand, leaves a non-Demon in hand, and does not execute the Demon Battlecry.", voidcaller_summons_demon_without_battlecry, "检查手牌类型筛选、直接召唤落区、Charge 和战吼边界。")
    record("FP1_022", "no_demon_in_hand", "With no Demon in hand, Voidcaller's death adds no minion and leaves the non-Demon card untouched.", voidcaller_no_demon_in_hand, "验证无候选 Demon 时的亡语边界。")
    record("FP1_022", "random_demon_between_two_candidates_without_battlecry", "Across fixed engine seeds, Voidcaller puts either eligible Demon into play, leaves the other Demon and non-Demons in hand, and skips their Battlecries.", voidcaller_random_demon_from_multiple_candidates_without_battlecry, "固定 game.random 种子覆盖两个不同恶魔；末日守卫弃牌与深渊领主打脸战吼均作为反证哨兵。")
    return finish_card("FP1_022", "Deathrattle|Random effects|Summon")


def unstable_ghoul_deathrattle_all_minions():
    game = new_game()
    owner, opponent = game.player1, game.player2
    ghoul = owner.give("FP1_024")
    ghoul.play()
    friendly_wisp = owner.summon(WISP)
    friendly_survivor = owner.summon("CS2_182")
    enemy_wisp = opponent.summon(WISP)
    enemy_survivor = opponent.summon("CS2_182")
    ghoul.destroy()
    assert ghoul.zone == Zone.GRAVEYARD and friendly_wisp.dead and enemy_wisp.dead
    assert friendly_survivor.health == enemy_survivor.health == 4, (friendly_survivor.health, enemy_survivor.health)
    assert owner.hero.health == opponent.hero.health == 30
    return f"ghoul={ghoul.zone.name};wisps_dead=True/True;survivors=4/4;heroes=30/30"


def unstable_ghoul_taunt_blocks_hero():
    game = new_game()
    owner, opponent = game.player1, game.player2
    ghoul = owner.give("FP1_024")
    ghoul.play()
    attacker = opponent.summon(WISP)
    game.end_turn()
    assert ghoul.taunt and not attacker.can_attack(owner.hero) and attacker.can_attack(ghoul), (ghoul.taunt, attacker.can_attack(owner.hero), attacker.can_attack(ghoul))
    try:
        attacker.attack(owner.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("opponent Wisp attacked through Unstable Ghoul's Taunt")
    attacker.attack(ghoul)
    assert ghoul.health == 2 and attacker.dead and attacker.zone == Zone.GRAVEYARD, (ghoul.health, attacker.zone, attacker.dead)
    return f"taunt_blocks_hero=True;attacker_hits_ghoul=True;ghoul_health_after_hit={ghoul.health};attacker={attacker.zone.name}"


def probe_unstable_ghoul():
    record("FP1_024", "deathrattle_one_damage_all_minions", "On death, Unstable Ghoul deals 1 to all minions on both sides, kills Wisps, leaves Yetis at 4 health, and leaves both heroes untouched.", unstable_ghoul_deathrattle_all_minions, "逐卡验证全场伤害范围、伤害值、死亡区域與英雄排除。")
    record("FP1_024", "taunt_blocks_hero_attack", "Enemy Wisp cannot attack the hero through Ghoul and can attack Ghoul instead.", unstable_ghoul_taunt_blocks_hero, "实际尝试攻击英雄和嘲讽随从。")
    return finish_card("FP1_024", "Deathrattle|Taunt")


def reincarnate_full_health_and_target_limits():
    game = new_game()
    owner, opponent = game.player1, game.player2
    wounded = owner.give("CS1_042")
    wounded.play()
    opponent_minion = opponent.summon(WISP)
    owner.give(MOONFIRE).play(target=wounded)
    spell = owner.give("FP1_025")
    assert wounded in spell.targets and opponent_minion in spell.targets
    assert owner.hero not in spell.targets and opponent.hero not in spell.targets
    old_mana = owner.mana
    try:
        spell.play(target=opponent.hero)
    except InvalidAction:
        pass
    else:
        raise AssertionError("Reincarnate accepted a hero target")
    assert spell in owner.hand and owner.mana == old_mana
    spell.play(target=wounded)
    copies = list(owner.field.filter(id="CS1_042"))
    assert wounded.zone == Zone.GRAVEYARD and len(copies) == 1
    assert (copies[0].atk, copies[0].health, copies[0].taunt) == (1, 2, True), (copies[0].atk, copies[0].health, copies[0].taunt)
    return f"enemy_minion_targetable=True;hero_target_rejected=True;original={wounded.zone.name};returned={copies[0].atk}/{copies[0].health};taunt={copies[0].taunt}"


def reincarnate_enemy_minion_returns_to_its_owner():
    game = new_game(CardClass.MAGE, CardClass.MAGE)
    owner, opponent = game.player1, game.player2
    enemy_minion = opponent.summon("CS1_042")
    owner.give(MOONFIRE).play(target=enemy_minion)
    assert enemy_minion.health < enemy_minion.max_health
    spell = owner.give("FP1_025")
    assert enemy_minion in spell.targets, "enemy minion must be a legal Reincarnate target"
    spell.play(target=enemy_minion)
    returned = list(opponent.field.filter(id="CS1_042"))
    owner_copies = list(owner.field.filter(id="CS1_042"))
    assert enemy_minion.zone == Zone.GRAVEYARD, (enemy_minion.zone, [c.id for c in owner.field], [c.id for c in opponent.field])
    assert len(returned) == 1 and not owner_copies, (
        f"expected revived minion on original owner Player2; original={enemy_minion.zone.name}; "
        f"player1_copies={[(c.id, c.zone.name) for c in owner_copies]}; "
        f"player2_copies={[(c.id, c.zone.name) for c in returned]}"
    )
    assert returned[0].controller is opponent and returned[0].health == returned[0].max_health, (
        returned[0].controller, returned[0].health, returned[0].max_health
    )
    return f"original_owner=Player2;original={enemy_minion.zone.name};returned_controller=Player2;returned_health={returned[0].health}/{returned[0].max_health};player1_same_id_copies=0"


def probe_reincarnate():
    record("FP1_025", "targeting_destroy_and_full_health_return", "Reincarnate accepts friendly and enemy minions but rejects heroes; the injured friendly minion dies and returns as a full-health Taunt minion.", reincarnate_full_health_and_target_limits, "实测目标范围、非法目标不扣费、原体落区及复生属性。")
    record("FP1_025", "enemy_target_returns_to_original_owner", "When Player 1 Reincarnates an enemy minion, the destroyed minion returns at full health under its original owner, Player 2.", reincarnate_enemy_minion_returns_to_its_owner, "对敌方合法目标实际施放，检查亡语复制体的控制方是否仍为原控制方。")
    return finish_card("FP1_025", "Spell resolution|Summon|Targeting")


def anubar_random_friendly_bounce():
    returned_positions = []
    for seed in range(1, 13):
        random.seed(seed)
        game = new_game()
        owner, opponent = game.player1, game.player2
        ambusher = owner.summon("FP1_026")
        friendly_a = owner.summon(WISP)
        friendly_b = owner.summon("CS1_042")
        enemy = opponent.summon(WISP)
        ambusher.destroy()
        returned = [m for m in (friendly_a, friendly_b) if m.zone == Zone.HAND]
        assert len(returned) == 1, (seed, friendly_a.zone, friendly_b.zone)
        assert ambusher.zone == Zone.GRAVEYARD and enemy in opponent.field
        assert returned[0] in owner.hand
        returned_positions.append(0 if returned[0] is friendly_a else 1)
    assert set(returned_positions) == {0, 1}, returned_positions
    return f"seeds=12;random_choices_seen={sorted(set(returned_positions))};enemy_untouched=True;source_in_graveyard=True"


def anubar_batch_death_does_not_bounce_dead_ally():
    game = new_game()
    owner, opponent = game.player1, game.player2
    ambusher = owner.summon("FP1_026")
    ally = owner.summon(WISP)
    ambusher.set_current_health(1)
    ally.set_current_health(1)
    game.end_turn()
    opponent.give("EX1_400").play()
    assert ambusher.zone == Zone.GRAVEYARD and ally.zone == Zone.GRAVEYARD, (ambusher.zone, ally.zone)
    assert ally not in owner.hand and not owner.field, (ally in owner.hand, [m.id for m in owner.field])
    return f"simultaneous_deaths=ambusher:{ambusher.zone.name},ally:{ally.zone.name};dead_ally_bounced=False"


def anubar_no_friendly_candidate():
    game = new_game()
    owner = game.player1
    ambusher = owner.summon("FP1_026")
    ambusher.destroy()
    assert ambusher.zone == Zone.GRAVEYARD and not owner.hand and not owner.field
    return f"source={ambusher.zone.name};hand=0;field=0"


def probe_anubar():
    record("FP1_026", "random_friendly_minion_return", "Across 12 seeds, death returns exactly one of two friendly minions to hand, leaves the enemy minion untouched, and varies the choice.", anubar_random_friendly_bounce, "逐种子验证随机候选域、手牌落区和随机性。")
    record("FP1_026", "same_batch_dead_ally", "When Ambusher and an ally die to the same Whirlwind, both remain dead; the ally is not rescued to hand by Ambusher's deathrattle.", anubar_batch_death_does_not_bounce_dead_ally, "针对同批死亡与亡语区域移动交叉场景。")
    record("FP1_026", "no_other_friendly_minion", "If Ambusher is the only friendly minion, its death returns nothing and raises no error.", anubar_no_friendly_candidate, "验证随机回手候选池为空的边界。")
    return finish_card("FP1_026", "Deathrattle|Random effects")


def gargoyle_heals_at_owner_start_only():
    game = new_game()
    owner = game.player1
    gargoyle = owner.give("FP1_027")
    gargoyle.play()
    owner.give(MOONFIRE).play(target=gargoyle)
    assert gargoyle.health == 3
    game.end_turn()
    assert gargoyle.health == 3, gargoyle.health
    game.end_turn()
    assert gargoyle.health == gargoyle.max_health, (gargoyle.health, gargoyle.max_health)
    owner.give(MOONFIRE).play(target=gargoyle)
    assert gargoyle.health == 3
    game.end_turn()
    assert gargoyle.health == 3
    game.end_turn()
    assert gargoyle.health == gargoyle.max_health
    return f"enemy_start_no_heal=True;owner_start_heals_full_twice=True;second_damage=1;final={gargoyle.health}/{gargoyle.max_health}"


def probe_gargoyle():
    record("FP1_027", "heal_to_full_at_own_turn_start", "Damage remains through the enemy turn; at each owner-turn start the Gargoyle heals fully, including after a later 4-damage hit.", gargoyle_heals_at_owner_start_only, "跨两个回合周期验证归属时机、满血恢复和重复触发。")
    return finish_card("FP1_027", "Trigger")


def undertaker_only_counts_friendly_deathrattle_summons():
    game = new_game()
    owner, opponent = game.player1, game.player2
    undertaker = owner.give("FP1_028")
    undertaker.play()
    owner.summon(WISP)
    assert undertaker.atk == 1
    opponent.summon("FP1_007")
    assert undertaker.atk == 1
    owner.summon("FP1_007")
    assert undertaker.atk == 2
    owner.summon("FP1_002")
    assert undertaker.atk == 3
    owner.summon(WISP)
    assert undertaker.atk == 3 and undertaker.health == 2
    return f"after_friendly_non_dr=1;after_enemy_dr=1;after_two_friendly_dr=3;health=2"


def probe_undertaker():
    record("FP1_028", "friendly_deathrattle_summon_trigger", "Undertaker gains +1 Attack per friendly Deathrattle minion summoned, ignores enemy Deathrattle and friendly non-Deathrattle summons, and gains no Health.", undertaker_only_counts_friendly_deathrattle_summons, "触发来源分敌我和亡语/非亡语，并断言属性仅加攻击。")
    return finish_card("FP1_028", "Summon|Trigger")


def dancing_swords_opponent_draw_counter():
    game = new_game()
    owner, opponent = game.player1, game.player2
    opponent.discard_hand()
    seeded = opponent.give(WISP)
    seeded.shuffle_into_deck()
    swords = owner.give("FP1_029")
    swords.play()
    before = (owner.cards_drawn_this_turn, opponent.cards_drawn_this_turn)
    swords.destroy()
    after = (owner.cards_drawn_this_turn, opponent.cards_drawn_this_turn)
    assert seeded in opponent.hand and seeded.zone == Zone.HAND and not opponent.deck
    assert swords.zone == Zone.GRAVEYARD
    assert after == (before[0], before[1] + 1), (before, after, seeded.zone, swords.zone)
    return f"opponent_drawn_card={seeded.id};draw_counters_before={before};after={after};swords={swords.zone.name}"


def probe_dancing_swords():
    record("FP1_029", "opponent_draw_and_counter", "Death draws the known top card for the opponent and increments only the opponent's cards-drawn-this-turn counter by 1.", dancing_swords_opponent_draw_counter, "逐卡复现跨玩家抽牌候选，检查目标手牌、牌库和双方抽牌计数。")
    return finish_card("FP1_029", "Deathrattle|Draw / Discard")


def loatheb_enemy_spell_costs_next_turn():
    game = new_game()
    owner, opponent = game.player1, game.player2
    friendly_spell = owner.give(MOONFIRE)
    moonfire = opponent.give(MOONFIRE)
    fireball = opponent.give("CS2_029")
    minion = opponent.give(WISP)
    assert (friendly_spell.cost, moonfire.cost, fireball.cost, minion.cost) == (0, 0, 4, 0)
    loatheb = owner.give("FP1_030")
    loatheb.play()
    assert (moonfire.cost, fireball.cost, friendly_spell.cost, minion.cost) == (0, 4, 0, 0)
    game.end_turn()
    assert (moonfire.cost, fireball.cost, friendly_spell.cost, minion.cost) == (5, 9, 0, 0), (moonfire.cost, fireball.cost, friendly_spell.cost, minion.cost)
    moonfire.play(target=owner.hero)
    assert owner.hero.health == 29
    game.end_turn()
    assert (moonfire.cost, fireball.cost, friendly_spell.cost, minion.cost) == (0, 4, 0, 0), (moonfire.cost, fireball.cost, friendly_spell.cost, minion.cost)
    return f"immediate=0/4;enemy_next_turn=5/9;moonfire_played=True;after_next_turn=0/4;friendly_spell=0;minion=0"


def probe_loatheb():
    record("FP1_030", "enemy_spells_cost_five_more_next_turn", "Loatheb leaves costs unchanged immediately, raises only enemy spell costs by 5 next turn, permits the 5-cost Moonfire, then restores costs at the following owner turn.", loatheb_enemy_spell_costs_next_turn, "实测延迟生效、敌方限定、法术排除随从及回合后恢复。")
    return finish_card("FP1_030", "Battlecry|Cost modification")


def baron_doubles_only_friendly_deathrattles():
    game = new_game()
    owner, opponent = game.player1, game.player2
    baron = owner.give("FP1_031")
    baron.play()
    friendly_gnome = owner.give("EX1_029")
    friendly_gnome.play()
    enemy_gnome = opponent.summon("EX1_029")
    friendly_gnome.destroy()
    assert opponent.hero.health == 26, opponent.hero.health
    enemy_gnome.destroy()
    assert owner.hero.health == 28, owner.hero.health
    baron.destroy()
    second_friendly_gnome = owner.give("EX1_029")
    second_friendly_gnome.play()
    second_friendly_gnome.destroy()
    assert opponent.hero.health == 24, opponent.hero.health
    return f"friendly_with_baron=4;enemy_with_opposing_baron=2;friendly_after_baron_death=2;heroes={owner.hero.health}/{opponent.hero.health}"


def probe_baron():
    record("FP1_031", "double_only_controller_deathrattles", "Baron doubles its controller's Leper Gnome deathrattle from 2 to 4, leaves the enemy Gnome at 2, and stops doubling after Baron dies.", baron_doubles_only_friendly_deathrattles, "真实触发亡语并核对己方/敌方归属及光环移除。")
    return finish_card("FP1_031", "Aura|Continuous effect / Update")


PROBES = {
    "FP1_002": probe_haunted_creeper,
    "FP1_003": probe_echoing_ooze,
    "FP1_004": probe_mad_scientist,
    "FP1_005": probe_shade,
    "FP1_007": probe_nerubian_egg,
    "FP1_008": probe_spectral_knight,
    "FP1_009": probe_deathlord,
    "FP1_010": probe_maexxna,
    "FP1_011": probe_webspinner,
    "FP1_012": probe_sludge_belcher,
    "FP1_013": probe_kel_thuzad,
    "FP1_014": probe_stalagg,
    "FP1_015": probe_feugen,
    "FP1_016": probe_wailing_soul,
    "FP1_017": probe_weblord,
    "FP1_018": probe_duplicate,
    "FP1_019": probe_poison_seeds,
    "FP1_020": probe_avenge,
    "FP1_021": probe_deaths_bite,
    "FP1_022": probe_voidcaller,
    "FP1_024": probe_unstable_ghoul,
    "FP1_025": probe_reincarnate,
    "FP1_026": probe_anubar,
    "FP1_027": probe_gargoyle,
    "FP1_028": probe_undertaker,
    "FP1_029": probe_dancing_swords,
    "FP1_030": probe_loatheb,
    "FP1_031": probe_baron,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("card_id", nargs="*", help="Run selected cards; defaults to all configured cards.")
    args = parser.parse_args()
    selected = args.card_id or list(PROBES)
    for card_id in selected:
        if card_id not in PROBES:
            raise SystemExit(f"No probe configured for {card_id}")
        clear_card(card_id)
        print(f"{card_id}: {PROBES[card_id]()}")


if __name__ == "__main__":
    main()
