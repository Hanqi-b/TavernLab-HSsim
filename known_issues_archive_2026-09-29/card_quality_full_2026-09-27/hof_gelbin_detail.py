"""Four invention branches of collectible Gelbin Mekkatorque, in live games."""

import csv
import logging
from pathlib import Path

from hearthstone.enums import CardClass, Zone
from utils import WISP, prepare_empty_game


HERE = Path(__file__).resolve().parent
PROBE = HERE / "hof_probe.csv"
VERDICT = HERE / "hof_verdict.csv"
P_FIELDS = ("card_id", "case_id", "expected", "observed", "outcome", "notes")
V_FIELDS = ("card_id", "status", "mechanic_scope", "reason", "probe_file", "notes")
logging.getLogger("fireplace").setLevel(logging.CRITICAL)
for handler in logging.getLogger("fireplace").handlers:
    handler.setLevel(logging.CRITICAL)


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, fields, data):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


def game_with_invention(seed, expected):
    game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
    if game.current_player is not game.player1:
        game.end_turn()
    game.random.seed(seed)
    owner = game.player1
    gelbin = owner.give("EX1_112")
    gelbin.play()
    inventions = [m for m in owner.field if m.id in {"Mekka1", "Mekka2", "Mekka3", "Mekka4"}]
    assert len(inventions) == 1 and inventions[0].id == expected, [m.id for m in owner.field]
    return game, gelbin, inventions[0]


def candidate_pool():
    seen = set()
    for seed in range(40):
        game = prepare_empty_game(CardClass.MAGE, CardClass.MAGE)
        if game.current_player is not game.player1:
            game.end_turn()
        game.random.seed(seed)
        gelbin = game.player1.give("EX1_112")
        gelbin.play()
        invention = [m for m in game.player1.field if m is not gelbin]
        assert len(invention) == 1, [m.id for m in game.player1.field]
        seen.add(invention[0].id)
    assert seen == {"Mekka1", "Mekka2", "Mekka3", "Mekka4"}, seen
    return f"40 fixed seeds; all four inventions reached={sorted(seen)}"


def homing_chicken_delayed_draw():
    game, _, chicken = game_with_invention(1, "Mekka1")
    owner = game.player1
    for _ in range(3):
        owner.give(WISP).shuffle_into_deck()
    before = len(owner.hand)
    game.end_turn()
    assert chicken.zone == Zone.PLAY, f"chicken_died_on_enemy_turn={chicken.zone.name}"
    game.end_turn()
    observed = f"chicken={chicken.zone.name};hand={before}->{len(owner.hand)};deck={len(owner.deck)}"
    assert chicken.zone == Zone.GRAVEYARD and len(owner.hand) == before + 3 and len(owner.deck) == 0, observed
    return observed


def repair_bot_heals_damaged_character():
    game, _, bot = game_with_invention(3, "Mekka2")
    owner = game.player1
    owner.hero.hit(10)
    assert owner.hero.health == 20
    game.end_turn()
    observed = f"owner_hero={owner.hero.health};bot={bot.zone.name}"
    assert owner.hero.health == 26 and bot.zone == Zone.PLAY, observed
    return observed


def emboldener_buffs_one_minion():
    reached = set()
    seeds = (5, 9, 12, 17, 23, 27, 29, 30)
    for seed in seeds:
        game, gelbin, device = game_with_invention(seed, "Mekka3")
        enemy = game.player2.summon("CS2_182")
        members = (gelbin, device, enemy)
        before = tuple((m.atk, m.health) for m in members)
        game.end_turn()
        after = tuple((m.atk, m.health) for m in members)
        changed = [i for i, (b, a) in enumerate(zip(before, after)) if a == (b[0]+1, b[1]+1)]
        assert len(changed) == 1 and all(a == b or i in changed for i, (b, a) in enumerate(zip(before, after))), (seed, before, after)
        reached.add(changed[0])
    assert reached == {0, 1, 2}, reached
    return f"seeds={seeds};random_targets_reached={sorted(reached)}"


def poultryizer_morphs_one_minion():
    reached = set()
    seeds = (0, 8, 10, 11, 16, 18, 21, 38, 39)
    for seed in seeds:
        game, gelbin, device = game_with_invention(seed, "Mekka4")
        enemy = game.player2.summon("CS2_182")
        members = (gelbin, device, enemy)
        game.end_turn()
        assert all(m.zone == Zone.PLAY for m in members), (seed, [m.zone.name for m in members])
        game.end_turn()
        dead = [i for i, m in enumerate(members) if m.zone != Zone.PLAY]
        chickens = [m for m in game.player1.field + game.player2.field if m.id == "Mekka4t"]
        assert len(dead) == 1 and len(chickens) == 1, (seed, dead, [(m.id,m.zone.name) for m in game.player1.field + game.player2.field])
        assert chickens[0].controller is members[dead[0]].controller, (seed, dead, chickens[0].controller)
        reached.add(dead[0])
    assert reached == {0, 1, 2}, reached
    return f"seeds={seeds};morphed_indices_reached={sorted(reached)}"


def main():
    cases = [
        ("four_inventions_reachable", "All four inventions occur over fixed battlecry seeds.", candidate_pool),
        ("homing_chicken_delayed_draw_three", "Homing Chicken survives enemy turn, then dies at owner's turn start and draws exactly three known cards.", homing_chicken_delayed_draw),
        ("repair_bot_heals_six", "Repair Bot heals the sole damaged character for six at its owner's turn end.", repair_bot_heals_damaged_character),
        ("emboldener_random_plus_one_plus_one", "Emboldener buffs exactly one minion +1/+1 at its owner's turn end across fixed seeds.", emboldener_buffs_one_minion),
        ("poultryizer_delayed_morph", "Poultryizer transforms exactly one random minion at its owner's next turn start, preserving controller.", poultryizer_morphs_one_minion),
    ]
    current = {(r["card_id"], r["case_id"]): r for r in rows(PROBE)}
    results = []
    for case_id, expected, probe in cases:
        try:
            observed = probe()
            outcome = "pass"
        except Exception as exc:
            observed = f"{type(exc).__name__}: {exc}"
            outcome = "inconclusive"
        current[("EX1_112", case_id)] = dict(card_id="EX1_112", case_id=case_id,
                                                expected=expected, observed=observed,
                                                outcome=outcome,
                                                notes="Additional live branch probe for Gelbin's four invention effects; see hof_gelbin_detail.py")
        results.append((case_id, outcome, observed))
    write(PROBE, P_FIELDS, list(current.values()))
    print(*results, sep="\n")
    if all(outcome == "pass" for _, outcome, _ in results):
        verdicts = rows(VERDICT)
        for verdict in verdicts:
            if verdict["card_id"] == "EX1_112":
                verdict["status"] = "GREEN"
                verdict["reason"] = "40个固定种子覆盖全部四种发明；分别实测小鸡下回合开始亡语抽3、修理机器人回合末治疗6、壮胆器回合末随机+1/+1、变鸡器下回合开始随机变形及控制者。"
                verdict["notes"] = "hof_probe.py 原战吼断言 + hof_gelbin_detail.py 四分支实战断言。"
        write(VERDICT, V_FIELDS, verdicts)


if __name__ == "__main__":
    main()
