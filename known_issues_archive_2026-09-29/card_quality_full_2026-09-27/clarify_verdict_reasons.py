"""Keep confirmed-error verdict reasons concise and specific to observed state."""

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent
REASONS = {
    "classic_verdict_middle_b.csv": {
        "EX1_584": "左右相邻随从确实获得 EX1_584e 附魔，但法术伤害都仍为0；月火术只造成1点，而非应有的3点。",
    },
    "classic_verdict_tail.csv": {
        "NEW1_036": "随从最低1血分支通过；命令怒吼未执行文本的‘抽一张牌’，已知牌仍在牌库中。",
    },
    "hof_verdict.csv": {
        "EX1_161": "自然平衡摧毁目标且对手实际抽了两张牌，但本回合抽牌计数错误记为施法者+2、对手+0。",
    },
    "naxx_verdict.csv": {
        "FP1_016": "哀嚎的灵魂战吼把自身也沉默；文案要求只沉默其他友方随从。",
        "FP1_019": "双方原有7个随从时，剧毒之种摧毁所有随从后只在己方生成7株树人，对手0株。",
        "FP1_025": "转生指定敌方随从后，原体死亡，但满血复生体出现在施法者场上而非原控制者场上。",
        "FP1_026": "阿努巴尔伏击者与友方随从同批死亡时，亡语将本应已死的友方随从送回手牌。",
        "FP1_029": "舞动之剑死亡使对手实际抽牌，但本回合抽牌计数错误记到亡语拥有者名下。",
    },
}


def main():
    for name, mapping in REASONS.items():
        path = HERE / name
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            rows = list(reader)
        assert {row["card_id"] for row in rows} >= set(mapping)
        for row in rows:
            if row["card_id"] in mapping:
                assert row["status"] == "RED", row["card_id"]
                row["reason"] = mapping[row["card_id"]]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(name, "clarified", len(mapping))


if __name__ == "__main__":
    main()
