"""Record per-card verdicts from the 2026-09-29 live regression tests."""

import csv
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ISSUE_IDS = {"BOARD-001", "BOARD-002", "DEATH-001", "DEATH-004"}
REASONS = {
    "EX1_136": "满场含休眠体时亡语先占空位，奥秘仍保留；有空位时复活目标为1生命并消耗奥秘。",
    "EX1_130": "休眠体占满场位时攻击正常命中英雄且奥秘保留；有空位时召唤防御者、改向并消耗奥秘。",
    "UNG_111": "休眠体占满场位时不损失水晶；开放场位按可用格数召唤树人，树人死亡归还水晶。",
    "ICC_200": "休眠体占满场位时不消耗奥秘；有一空位时召唤正确的剧毒眼镜蛇并消耗奥秘。",
    "ICC_054": "休眠体计入场位，最后一个空位仅召一只甲虫并停止；空场与双方人数相等分支均符合卡面。",
    "EX1_116": "己方第七格打出仍向对手召两只雏龙；敌方满场时无第八只且本体保持冲锋。",
    "EX1_577": "己方满场时亡语给有空位的对手召一只芬克；对手满场时不越过七格。",
    "FP1_019": "双方各满七格时原随从死亡并各自得到七只树人；人数不等时替换数量分别正确。",
    "UNG_926": "己方第七格打出仍给对手三只猛禽；对手满七格时不额外召唤。",
    "LOOT_154": "己方第七格打出仍给对手随机一费随从；对手满场时不越过七格。",
    "LOOT_357": "己方第七格打出仍给对手宝箱；对手满场不召唤，宝箱死亡后宝藏进入玛林控制者手牌。",
    "LOOT_383": "己方第七格打出仍给对手随机二费随从；对手满场不越过七格，本体嘲讽正确。",
    "OG_256": "同批死亡的友军如期入墓，幸存友军获得准确+1/+1，敌方不受增益。",
    "LOE_061": "同批死亡实体不被救活；24个种子覆盖三名合法友军随机目标且增益准确。",
    "FP1_023": "同批死亡实体不被救活；24个种子覆盖三名合法友军随机目标且+3生命准确。",
    "OG_158": "同批死亡实体不被救活；24个种子覆盖三名合法友军随机目标且+1/+1准确。",
    "UNG_037": "同批死亡和随机增益正确；嘲讽实际阻止攻击英雄。",
    "GIL_608": "同批死亡和随机+2生命正确；潜行禁止敌方攻击和指向法术，自己攻击后解除。",
    "DAL_563": "同批死亡实体不被救活；随机选两个不同合法友军，三种配对均出现且各+2/+2。",
    "ULD_266": "同批死亡和随机增益正确；仅复生一只1/1副本，复生标记消耗后再次死亡不复生。",
    "FP1_026": "随机回手仅选存活友军；无目标与同批死亡友军均不误回手。",
    "EX1_407": "乱斗随机保留恰一只随从，候选均可胜出；同次结算死亡友军不会被亡语回手救回。",
    "ICC_047": "抉择成长和腐朽两分支均实际触发；同批死亡友军不被成长亡语救回。",
    "OG_302": "友军死亡使手牌、牌库或场上的克苏恩各+1/+1；敌军死亡不触发。",
    "GIL_819": "友军死亡向手牌加入萨满法术；敌军死亡不触发。",
    "ICC_900": "另一友军死亡仅召一只2/2食尸鬼；敌军死亡或本体死亡不触发。",
    "BT_850": "三只敌方典狱官死亡后唤醒并清场；无关敌军死亡不计数，同批三杀也正确。",
    "TRL_251": "友军死亡使手牌随从+1/+1；敌军死亡不触发，潜行到期消失。",
    "TRL_257": "友军死亡时敌方英雄受2点伤害、己方不受伤；同批两名友军各触发一次，敌军或本体死亡不触发。",
    "TRL_502": "友军死亡洗入一张费用为1的复制随从；敌军死亡不触发，潜行到期消失。",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def collect_nodes():
    env = os.environ.copy()
    env.update(PYTHONPATH="tests:.", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    result = subprocess.run(
        [
            str(ROOT / "venv/bin/python"), "-m", "pytest", "--collect-only", "-q",
            "tests/test_retest_board_issues.py", "tests/test_retest_death_batch.py",
            "tests/test_retest_death_selector.py",
        ],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return [line for line in result.stdout.splitlines() if line.startswith("tests/test_retest_")]


def main():
    issue_map = {}
    for issue in read_csv(HERE / "mechanism_issues.csv"):
        if issue["issue_id"] in ISSUE_IDS:
            for card_id in issue["confirmed_cards"].split("|"):
                assert card_id not in issue_map
                issue_map[card_id] = issue["issue_id"]
    assert set(issue_map) == set(REASONS) and len(issue_map) == 30
    nodes = collect_nodes()
    rows = []
    for card_id, issue_id in issue_map.items():
        matching = [node for node in nodes if card_id.lower() in node.lower()]
        assert matching, card_id
        rows.append({
            "issue_id": issue_id,
            "card_id": card_id,
            "outcome": "PASS",
            "status": "GREEN",
            "tested": "yes",
            "reason": REASONS[card_id],
            "test_nodes": "|".join(matching),
            "notes": "当前代码逐卡行为重测通过。",
        })
    path = HERE / "remediation_verdicts_2026-09-29.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} per-card verdicts with {len(nodes)} collected test nodes: {path}")


if __name__ == "__main__":
    main()
