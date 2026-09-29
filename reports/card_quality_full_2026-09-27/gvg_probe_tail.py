"""Independent GVG card-specific live probes for 17 legacy-test-referenced cards."""

import csv
import logging
import random
import sys
from pathlib import Path

from hearthstone.enums import CardClass, CardType, Race, Rarity, Zone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from utils import FIREBALL, MOONFIRE, WISP, prepare_empty_game  # noqa: E402

logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)

PROBE = HERE / "gvg_probe_tail.csv"
VERDICT = HERE / "gvg_verdict_tail.csv"
BASE = HERE / "four_set_yellow_baseline.csv"
MASTER = HERE / "card_master.csv"
QUALITY = HERE / "card_quality.csv"
PF = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
VF = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        out = csv.DictWriter(stream, fieldnames=fields)
        out.writeheader()
        out.writerows(rows)


def game(cls=CardClass.MAGE, seed=417):
    random.seed(seed)
    g = prepare_empty_game(cls, cls)
    g.random.seed(seed)
    if g.current_player is not g.player1:
        g.end_turn()
    for player in g.players:
        player.max_mana = 10
        player.is_standard = False
    return g


def play(player, cid, target=None):
    c = player.give(cid)
    if target is None:
        c.play()
    else:
        c.play(target=target)
    return c


def shuffle(player, cid):
    c = player.give(cid)
    c.shuffle_into_deck()
    return c


def p092_minion():
    g = game()
    top = shuffle(g.player1, WISP)
    experimenter = play(g.player1, "GVG_092")
    chicken = [c for c in g.player1.hand if c.id == "GVG_092t"]
    return f"drawn_original={top.zone.name};hand={[c.id for c in g.player1.hand]};chicken={len(chicken)};source={experimenter.zone.name}", experimenter.zone == Zone.PLAY and len(chicken) == 1 and top.zone != Zone.DECK


def p092_spell():
    g = game()
    top = shuffle(g.player1, FIREBALL)
    play(g.player1, "GVG_092")
    return f"drawn={top.id}/{top.zone.name};hand={[c.id for c in g.player1.hand]}", top.zone == Zone.HAND and top in g.player1.hand and not any(c.id == "GVG_092t" for c in g.player1.hand)


def p094():
    g = game()
    for player in g.players:
        player.discard_hand()
        for _ in range(3): shuffle(player, WISP)
    c = play(g.player1, "GVG_094")
    g.end_turn()
    first = (len(g.player1.hand), len(g.player2.hand))
    g.end_turn()
    second = (len(g.player1.hand), len(g.player2.hand))
    return f"after_owner_turn={first};after_opponent_turn={second};jeeves={c.zone.name}", first == (3, 1) and second == (3, 3) and c.zone == Zone.PLAY


def p097():
    g = game()
    enemy = [g.player2.summon("EX1_029") for _ in range(2)]
    friendly = g.player1.summon("EX1_029")
    c = play(g.player1, "GVG_097")
    return f"enemy_deathrattle={len(enemy)};own_deathrattle={friendly.id};stats={c.atk}/{c.health};base={c.data.atk}/{c.data.health};taunt={c.taunt}", bool(c.atk == c.data.atk + 2 and c.health == c.data.health + 2 and c.taunt)


def p099_one():
    g = game()
    target = g.player2.summon("CS2_182")
    c = play(g.player1, "GVG_099")
    return f"target_damage={target.damage};zone={target.zone.name};lobber={c.zone.name};hero_health={g.player2.hero.health}", target.damage == 4 and target.zone == Zone.PLAY and g.player2.hero.health == 30 and c.zone == Zone.PLAY


def p099_domain():
    seen = set()
    for seed in range(40, 56):
        g = game(seed=seed)
        a, b = g.player2.summon("CS2_182"), g.player2.summon("CS2_182")
        play(g.player1, "GVG_099")
        deltas = (a.damage, b.damage)
        if sorted(deltas) != [0, 4] or g.player2.hero.health != 30:
            return f"seed={seed};minion_damages={deltas};hero={g.player2.hero.health}", False
        seen.add(deltas.index(4))
    return f"16_seeded_winners={sorted(seen)}", seen == {0, 1}


def p100_own():
    g = game(CardClass.WARLOCK)
    watcher = play(g.player1, "GVG_100")
    before = (watcher.atk, watcher.health)
    g.player1.hero.hit(2)
    return f"own_turn_hero_damage=2;before={before};after={watcher.atk}/{watcher.health}", watcher.atk == before[0] + 2 and watcher.health == before[1] + 2


def p100_other():
    g = game(CardClass.WARLOCK)
    watcher = play(g.player1, "GVG_100")
    before = (watcher.atk, watcher.health)
    g.end_turn()
    g.player1.hero.hit(2)
    return f"opponent_turn_hero_damage=2;before={before};after={watcher.atk}/{watcher.health}", (watcher.atk, watcher.health) == before


def p102_mech():
    g = game()
    g.player1.summon("GVG_006")
    before = len(g.player1.hand)
    c = play(g.player1, "GVG_102")
    added = list(g.player1.hand)
    return f"stats={c.atk}/{c.health};base={c.data.atk}/{c.data.health};added={[(x.id,x.data.spare_part,x.zone.name) for x in added]}", c.atk == c.data.atk + 1 and c.health == c.data.health + 1 and len(added) == before + 1 and added[0].data.spare_part and added[0].zone == Zone.HAND


def p102_no_mech():
    g = game()
    c = play(g.player1, "GVG_102")
    return f"stats={c.atk}/{c.health};base={c.data.atk}/{c.data.health};hand={[x.id for x in g.player1.hand]}", c.atk == c.data.atk and c.health == c.data.health and not g.player1.hand


def p103():
    g = game()
    c = play(g.player1, "GVG_103")
    base = c.atk
    g.end_turn()
    after_enemy_start = c.atk
    g.end_turn()
    after_owner_start = c.atk
    return f"attack={base}->{after_enemy_start}->{after_owner_start};health={c.health}", after_enemy_start == base + 1 and after_owner_start == base + 2


def p104():
    g = game()
    hob = play(g.player1, "GVG_104")
    one = play(g.player1, WISP)
    two = play(g.player1, "CS2_182")
    return f"wisp={one.atk}/{one.health},base={one.data.atk}/{one.data.health};yeti={two.atk}/{two.health},base={two.data.atk}/{two.data.health};hob={hob.zone.name}", one.atk == one.data.atk + 2 and one.health == one.data.health + 2 and two.atk == two.data.atk and two.health == two.data.health


def p108_target():
    samples = []
    for seed in range(40, 56):
        g = game(seed=seed)
        original = g.player1.summon("CS2_182")
        enemy = g.player2.summon("CS2_182")
        slot = g.player1.field.index(original)
        c = g.player1.give("GVG_108")
        legal = set(c.targets)
        c.play(target=original)
        transformed = g.player1.field[slot]
        if original not in legal or enemy in legal or transformed is original or transformed.cost != original.data.cost or transformed.zone != Zone.PLAY or c.zone != Zone.PLAY:
            return f"seed={seed};target_domain={[m.id for m in legal]};old={original.id}/{original.zone.name};new={transformed.id}/{transformed.cost}/{transformed.zone.name};source={c.zone.name}", False
        samples.append(transformed.id)
    return f"16_seeded_same_cost_replacements={samples};distinct={len(set(samples))};enemy_target_excluded=True", len(set(samples)) > 1


def p108_no_target():
    g = game()
    c = play(g.player1, "GVG_108")
    return f"source={c.zone.name};board={[x.id for x in g.player1.field]}", c.zone == Zone.PLAY and len(g.player1.field) == 1


def p110():
    g = game()
    c = play(g.player1, "GVG_110")
    bots = [m for m in g.player1.field if m.id == "GVG_110t"]
    return f"board={[(m.id,m.atk,m.health,m.zone.name) for m in g.player1.field]}", c.zone == Zone.PLAY and len(bots) == 2 and all((m.atk, m.health, m.zone) == (1, 1, Zone.PLAY) for m in bots)


def p110_bot_death():
    g = game()
    play(g.player1, "GVG_110")
    bot = next(m for m in g.player1.field if m.id == "GVG_110t")
    bot.destroy()
    damage = 30 - g.player2.hero.health
    return f"bot_zone={bot.zone.name};enemy_hero_damage={damage};enemy_board={[m.id for m in g.player2.field]}", bot.zone == Zone.GRAVEYARD and 1 <= damage <= 4


def p111():
    g = game()
    head = play(g.player1, "GVG_111")
    others = [g.player1.summon("GVG_006") for _ in range(2)]
    g.end_turn(); g.end_turn()
    formed = [m for m in g.player1.field if m.id == "GVG_111t"]
    return f"head={head.zone.name};other_mechs={[m.zone.name for m in others]};formed={[(m.id,m.zone.name,m.mega_windfury) for m in formed]}", head.zone == Zone.GRAVEYARD and all(m.zone == Zone.GRAVEYARD for m in others) and len(formed) == 1 and formed[0].zone == Zone.PLAY


def p111_below_threshold():
    g = game()
    head = play(g.player1, "GVG_111")
    other = g.player1.summon("GVG_006")
    g.end_turn(); g.end_turn()
    formed = [m for m in g.player1.field if m.id == "GVG_111t"]
    return f"mech_count=2;head={head.zone.name};other={other.zone.name};formed={len(formed)}", head.zone == other.zone == Zone.PLAY and not formed


def p112():
    seen = set()
    for seed in range(40, 72):
        g = game(seed=seed)
        mogor = g.player1.summon("GVG_112")
        attacker = g.player1.summon("CS2_182")
        enemy = g.player2.summon("CS2_182")
        g.end_turn(); g.end_turn()
        try:
            attacker.attack(g.player2.hero)
        except Exception as exc:
            return f"seed={seed};attack_exception={type(exc).__name__}:{exc}", None
        actual = "minion" if enemy.damage else "hero" if g.player2.hero.health < 30 else "none"
        seen.add(actual)
    return f"32_seeded_attack_destinations={sorted(seen)};mogor={mogor.zone.name}", seen == {"hero", "minion"}


def p112_enemy_attacker():
    seen = set()
    for seed in range(40, 72):
        g = game(seed=seed)
        mogor = g.player1.summon("GVG_112")
        other = g.player1.summon("CS2_182")
        attacker = g.player2.summon("CS2_182")
        g.end_turn()
        try:
            attacker.attack(g.player1.hero)
        except Exception as exc:
            return f"seed={seed};attack_exception={type(exc).__name__}:{exc}", None
        actual = "minion" if mogor.damage or other.damage else "hero" if g.player1.hero.health < 30 else "none"
        seen.add(actual)
    return f"32_seeded_opponent_attack_destinations={sorted(seen)}", seen == {"hero", "minion"}


def p114():
    ids = set()
    for seed in range(40, 56):
        g = game(seed=seed)
        c = play(g.player1, "GVG_114")
        c.destroy()
        summoned = list(g.player1.field)
        if len(summoned) != 1 or summoned[0].zone != Zone.PLAY or summoned[0].rarity != Rarity.LEGENDARY:
            return f"seed={seed};summoned={[(m.id,str(m.rarity),m.zone.name) for m in summoned]}", False
        ids.add(summoned[0].id)
    return f"16_seeded_legendary_ids={sorted(ids)}", len(ids) > 1


def p116_enemy():
    g = game()
    engineer = play(g.player1, "GVG_116")
    enemy = g.player2.summon(WISP)
    enemy.destroy()
    lepers = [m for m in g.player1.field if m.id == "EX1_029"]
    return f"enemy={enemy.zone.name};lepers={[(m.id,m.zone.name) for m in lepers]};engineer={engineer.zone.name}", enemy.zone == Zone.GRAVEYARD and len(lepers) == 1 and lepers[0].zone == Zone.PLAY


def p116_friendly():
    g = game()
    play(g.player1, "GVG_116")
    ally = g.player1.summon(WISP)
    ally.destroy()
    return f"friendly_dead={ally.zone.name};lepers={[m.id for m in g.player1.field if m.id == 'EX1_029']}", ally.zone == Zone.GRAVEYARD and not any(m.id == "EX1_029" for m in g.player1.field)


def p117():
    gained_ids = set()
    for seed in range(40, 56):
        g = game(CardClass.PRIEST, seed)
        gaz = play(g.player1, "GVG_117")
        spell = g.player1.give("CS1_130")
        if spell.cost != 1:
            return f"fixture_spell_cost={spell.cost}", None
        spell.play(target=gaz)
        gained = [c for c in g.player1.hand if c.type == CardType.MINION and Race.MECHANICAL in c.races]
        if len(gained) != 1 or gaz.zone != Zone.PLAY:
            return f"seed={seed};hand={[(c.id,c.type,c.races) for c in g.player1.hand]};source={gaz.zone.name}", False
        gained_ids.add(gained[0].id)
    return f"16_seeded_mechs={sorted(gained_ids)}", len(gained_ids) > 1


def p117_zero_cost():
    g = game(CardClass.PRIEST)
    gaz = play(g.player1, "GVG_117")
    before = len(g.player1.hand)
    spell = play(g.player1, MOONFIRE, g.player2.hero)
    return f"spell_cost={spell.data.cost};hand_before={before};hand_after={[c.id for c in g.player1.hand]};source={gaz.zone.name}", spell.data.cost == 0 and len(g.player1.hand) == before and gaz.zone == Zone.PLAY


def p117_opponent():
    g = game(CardClass.PRIEST)
    gaz = play(g.player1, "GVG_117")
    g.end_turn()
    before = len(g.player1.hand)
    spell = play(g.player2, "CS1_130", gaz)
    return f"opponent_spell_cost={spell.data.cost};owner_hand_before={before};owner_hand_after={[c.id for c in g.player1.hand]};gazlowe={gaz.zone.name}", spell.data.cost == 1 and len(g.player1.hand) == before and gaz.zone == Zone.PLAY


def p119():
    samples = []
    for seed in range(40, 56):
        g = game(seed=seed)
        c = play(g.player1, "GVG_119")
        weapons = [(p.weapon.id if p.weapon else None, p.weapon.zone.name if p.weapon else None) for p in g.players]
        if c.zone != Zone.PLAY or not all(p.weapon and p.weapon.zone == Zone.PLAY and p.weapon.type == CardType.WEAPON for p in g.players):
            return f"seed={seed};weapons={weapons};source={c.zone.name}", False
        samples.append(tuple(w[0] for w in weapons))
    return f"16_seeded_weapon_pairs={samples};distinct_pairs={len(set(samples))}", len(set(samples)) > 1


def p122():
    g = game()
    left = g.player1.summon("CS2_182")
    stop = play(g.player1, "GVG_122")
    right = g.player1.summon("CS2_182")
    farther = g.player1.summon("CS2_182")
    spell = g.player1.give(MOONFIRE)
    blocked = (left not in spell.targets, right not in spell.targets)
    far_legal = farther in spell.targets
    power = g.player1.hero.power
    power_blocked = (left not in power.targets, right not in power.targets)
    power_far_legal = farther in power.targets
    stop.destroy()
    restored = (left in spell.targets, right in spell.targets)
    power_restored = (left in power.targets, right in power.targets)
    return f"spell_blocked={blocked};spell_far_legal={far_legal};power_blocked={power_blocked};power_far_legal={power_far_legal};spell_restored={restored};power_restored={power_restored};stop_zone={stop.zone.name}", blocked == power_blocked == (True, True) and far_legal and power_far_legal and restored == power_restored == (True, True)


CASES = {
    "GVG_092": [("minion_draw_chicken", "Drawn minion becomes a Chicken in hand.", p092_minion), ("spell_draw_unchanged", "Drawn spell remains itself in hand.", p092_spell)],
    "GVG_094": [("both_turn_ends_draw_to_three", "At each player's turn end that player draws until hand size three.", p094)],
    "GVG_097": [("enemy_deathrattles_only", "Two enemy Deathrattle minions grant +2/+2; own Deathrattle is excluded; Taunt is active.", p097)],
    "GVG_099": [("single_enemy_four_damage", "Only enemy minion takes 4, hero unaffected.", p099_one), ("random_enemy_minion_domain", "Across 16 seeds exactly one of two enemy minions takes 4, both candidates reached.", p099_domain)],
    "GVG_100": [("own_turn_hero_damage_buffs", "Own hero damage on own turn grants +2/+2.", p100_own), ("opponent_turn_hero_damage_no_buff", "Own hero damage on opponent turn grants no buff.", p100_other)],
    "GVG_102": [("with_mech_stats_and_part", "With friendly Mech gains +1/+1 and adds one Spare Part.", p102_mech), ("without_mech_no_bonus", "Without friendly Mech gains neither stats nor a card.", p102_no_mech)],
    "GVG_103": [("both_turn_starts_gain_attack", "Each turn start grants +1 Attack, including enemy and own turns.", p103)],
    "GVG_104": [("one_attack_only", "Played 1-Attack minion receives +2/+2, 2-Attack minion unchanged.", p104)],
    "GVG_108": [("friendly_same_cost_transform", "Across 16 seeds legal friendly target transforms into varied same-Cost minions; enemy target is excluded.", p108_target), ("no_target_enters_normally", "Without a friendly target Recombobulator enters normally.", p108_no_target)],
    "GVG_110": [("two_one_one_boom_bots", "Battlecry summons exactly two 1/1 Boom Bots.", p110), ("boom_bot_deathrattle_damage", "Boom Bot death deals 1–4 to only enemy character.", p110_bot_death)],
    "GVG_111": [("two_mechs_no_formation", "At own turn start with only two Mechs including Head, no transformation occurs.", p111_below_threshold), ("three_mechs_form_v07tron", "At next own turn with three Mechs including Head, destroy them and summon V-07-TR-0N.", p111)],
    "GVG_112": [("friendly_attack_wrong_enemy_randomness", "Across 32 seeded friendly attacks with Mogor, attacks reach intended enemy hero and wrong enemy minion.", p112), ("enemy_attack_wrong_enemy_randomness", "Across 32 seeded enemy attacks with Mogor, attacks reach intended friendly hero and wrong friendly minion.", p112_enemy_attacker)],
    "GVG_114": [("legendary_deathrattle_pool", "Across 16 seeded deaths, summons one random Legendary minion each time with varied identities.", p114)],
    "GVG_116": [("enemy_death_summons_leper", "One enemy minion death summons one Leper Gnome for controller.", p116_enemy), ("friendly_death_no_leper", "Friendly minion death does not summon Leper Gnome.", p116_friendly)],
    "GVG_117": [("one_cost_spell_adds_random_mech", "Across 16 seeds, a 1-Cost spell adds a random Mech card to own hand.", p117), ("zero_cost_spell_no_mech", "Own 0-Cost spell does not add a Mech.", p117_zero_cost), ("opponent_one_cost_spell_no_mech", "Opponent 1-Cost spell does not add a Mech to owner hand.", p117_opponent)],
    "GVG_119": [("weapon_each_player", "Across 16 seeds Battlecry equips a random Weapon for each player, with varied legal weapon pairs.", p119)],
    "GVG_122": [("adjacent_untargetable_aura", "Both adjacent minions cannot be targeted by spells or Hero Powers, nonadjacent can, and removal restores both targeting paths.", p122)],
}


def main():
    baseline = {r["card_id"] for r in read(BASE) if r["set"] == "Goblins vs Gnomes (GVG)"}
    assert len(CASES) == 17 and set(CASES) <= baseline
    master = {r["card_id"]: r for r in read(MASTER)}
    prior = {r["card_id"]: r for r in read(QUALITY)}
    rows, verdicts = [], []
    for cid in sorted(CASES):
        card = master[cid]
        for case_id, expected, fn in CASES[cid]:
            try:
                observed, passed = fn()
                outcome = "pass" if passed is True else "confirmed_error" if passed is False else "inconclusive"
            except Exception as exc:
                observed = f"{type(exc).__name__}: {exc}"
                outcome = "inconclusive"
            rows.append({"card_id": cid, "case_id": case_id, "expected": expected,
                         "observed": observed, "outcome": outcome,
                         "notes": f"EN: {card['card_text_en']} ZH: {card['card_text_zh']} Source: {card['python_source'] or 'native tags'}. Existing refs: {card['test_refs_candidate'] or 'none'}. Previous YELLOW: {prior[cid]['reason']}"})
            write(PROBE, PF, rows)
            print(cid, case_id, outcome, observed, flush=True)
        own = [r for r in rows if r["card_id"] == cid]
        errors = [r for r in own if r["outcome"] == "confirmed_error"]
        open_cases = [r for r in own if r["outcome"] == "inconclusive"]
        status = "RED" if errors else "YELLOW" if open_cases else "GREEN"
        if errors:
            reason = "确认行为与文本不符：" + "; ".join(f"{r['case_id']} expected[{r['expected']}] observed[{r['observed']}]" for r in errors)
        elif open_cases:
            reason = "关键行为待进一步核实：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in open_cases)
        else:
            reason = "本轮逐卡行为断言通过：" + "; ".join(f"{r['case_id']}={r['observed']}" for r in own)
        verdicts.append({"card_id": cid, "status": status, "mechanic_scope": card["mechanics"],
                         "reason": reason, "probe_file": PROBE.name,
                         "notes": f"{len(own)} new live cases; EN/ZH text, source, prior audit and existing refs preserved in probe notes."})
        write(VERDICT, VF, verdicts)


if __name__ == "__main__":
    main()
