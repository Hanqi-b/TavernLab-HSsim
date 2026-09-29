"""Reconcile quality evidence for every set in the 17.6 card snapshot."""

import csv
from collections import Counter, defaultdict
from pathlib import Path


OUT = Path(__file__).resolve().parent


def read(name):
    with (OUT / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    inventory = read("set_inventory.csv")
    master = read("card_master.csv")
    quality = read("card_quality.csv")
    mechanism = read("card_mechanism.csv")
    smoke = read("runtime_smoke.csv")
    issues = read("mechanism_issues.csv")
    by_set = defaultdict(lambda: defaultdict(list))
    for kind, rows in (("master", master), ("quality", quality), ("mechanism", mechanism), ("smoke", smoke)):
        for row in rows:
            by_set[row["set"]][kind].append(row)
    issue_cards = defaultdict(list)
    for issue in issues:
        for card_id in issue["confirmed_cards"].split("|"):
            if card_id:
                issue_cards[card_id].append(issue["issue_id"])

    output = []
    matrix = []
    for setrow in inventory:
        name = setrow["set"]
        groups = by_set[name]
        cards = groups["quality"]
        master_ids = {r["card_id"] for r in groups["master"]}
        card_ids = {r["card_id"] for r in cards}
        mechanism_ids = {r["card_id"] for r in groups["mechanism"]}
        counts = Counter(r["status"] for r in cards)
        tests = Counter(r["tested"] for r in cards)
        implementations = Counter(r["implementation"] for r in cards)
        smoke_counts = Counter(r["outcome"] for r in groups["smoke"])
        red = sorted(r["card_id"] for r in cards if r["status"] == "RED")
        none = sorted(r["card_id"] for r in cards if r["implementation"] == "none")
        issues_in_set = sorted({issue_id for cid in red for issue_id in issue_cards[cid]})
        ordinary_count = sum(r["scope"] == "ordinary_collectible" for r in cards)
        # Every published card and mechanism row is ordinary collectible.
        reconciled = (len(groups["master"]) == int(setrow["ordinary_collectible"])
                      and len(cards) == counts.total()
                      and len(cards) == int(setrow["ordinary_collectible"])
                      and len(groups["mechanism"]) >= len(cards)
                      and card_ids == mechanism_ids
                      and card_ids <= master_ids
                      and counts["GREEN"] == int(setrow["quality_green"])
                      and counts["YELLOW"] == int(setrow["quality_yellow"])
                      and counts["RED"] == int(setrow["quality_red"])
                      and len(groups["smoke"]) == ordinary_count
                      and sum(smoke_counts.values()) == ordinary_count)
        output.append({
            "version": setrow["version"], "set": name,
            "collectible_cards": len(groups["master"]), "applicable_entities": len(cards),
            "ordinary_collectible": ordinary_count,
            "mechanism_rows": len(groups["mechanism"]),
            "green": counts["GREEN"], "yellow": counts["YELLOW"], "red": counts["RED"],
            "tested_yes": tests["yes"], "tested_partial": tests["partial"], "tested_no": tests["no"],
            "implementation_none": implementations["none"],
            "implementation_partial": implementations["partial"],
            "smoke_played": smoke_counts["played"],
            "smoke_not_playable": smoke_counts["unplayable_in_generic_setup"],
            "smoke_exception": smoke_counts["exception"],
            "red_card_ids": "|".join(red), "no_implementation_ids": "|".join(none),
            "confirmed_issue_ids": "|".join(issues_in_set),
            "coverage_reconciled": "yes" if reconciled else "no",
            "next_review": ("本轮原始 YELLOW 已逐卡运行；复核保留的 YELLOW 具体阻碍，并针对已确认的共享问题修复后回归。"
                            if name in {"Classic (EXPERT1)", "Hall of Fame (HOF)", "Curse of Naxxramas (NAXX)",
                                        "Goblins vs Gnomes (GVG)", "Blackrock Mountain (BRM)",
                                        "The Grand Tournament (TGT)", "League of Explorers (LOE)",
                                        "Whispers of the Old Gods (OG)"}
                            else "核对 RED 复现与无实现卡；其余 YELLOW 按该扩展包高频机制补核心效果断言。"),
        })
        by_mechanism = defaultdict(list)
        for item in groups["mechanism"]:
            by_mechanism[item["mechanic"]].append(item)
        for label, items in sorted(by_mechanism.items()):
            states = Counter(item["status"] for item in items)
            matrix.append({
                "version": setrow["version"], "set": name, "mechanism": label,
                "candidate_entities": len(items),
                "ordinary_collectible": sum(item["scope"] == "ordinary_collectible" for item in items),
                "green": states["GREEN"], "yellow": states["YELLOW"], "red": states["RED"],
                "red_card_ids": "|".join(sorted(item["card_id"] for item in items if item["status"] == "RED")),
                "evidence_note": "文案、标签及源码均可产生候选；GREEN 须看 card_mechanism.csv 中的实际效果断言。",
            })
    fieldnames = list(output[0])
    with (OUT / "set_sweep.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output)
    with (OUT / "set_mechanism_matrix.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)
    failures = [r["set"] for r in output if r["coverage_reconciled"] != "yes"]
    print(f"sets={len(output)}; set-mechanism rows={len(matrix)}; reconciled={len(output) - len(failures)}; failures={failures}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
