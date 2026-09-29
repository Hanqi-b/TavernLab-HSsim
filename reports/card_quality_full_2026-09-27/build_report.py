"""Build the 17.6 card quality inventory from bundled data and audit evidence.

This is an audit report generator. It does not change card behavior. Generic play
smoke is deliberately never promoted to GREEN without effect assertions.
"""

import ast
import csv
import inspect
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from hearthstone import cardxml
from hearthstone.enums import CardSet, CardType, GameTag

from fireplace.cards import db, get_script_definition
from fireplace.targeting import TARGETING_PREREQUISITES
from report_snapshot import source_snapshot


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
VERSION = "17.6.0.53261"
XML = ROOT / "fireplace/cards/CardDefs.xml"
PRIOR = ROOT / "reports/card_quality_2026-09-27"
SMOKE = OUT / "collectible_play_smoke.json"
PLAY_TYPES = {"MINION", "SPELL", "WEAPON", "HERO", "HERO_POWER"}
STARTING_HERO_IDS = {f"HERO_{number:02d}" for number in range(1, 11)}
STRUCTURED = {
    "BATTLECRY": "Battlecry", "DEATHRATTLE": "Deathrattle",
    "DISCOVER": "Discover / Choice", "CHOOSE_ONE": "Choose One",
    "SECRET": "Secret", "COMBO": "Combo", "OVERLOAD": "Overload",
    "AURA": "Aura", "REBORN": "Reborn", "MAGNETIC": "Magnetic",
    "LIFESTEAL": "Lifesteal", "RUSH": "Rush", "TAUNT": "Taunt",
    "DIVINE_SHIELD": "Divine Shield", "CHARGE": "Charge",
    "POISONOUS": "Poisonous", "WINDFURY": "Windfury",
    "STEALTH": "Stealth", "ECHO": "Echo", "TWINSPELL": "Twinspell",
    "OUTCAST": "Outcast", "QUEST": "Quest",
    "HEROPOWER_DAMAGE": "Hero Power modification",
    "SPELLPOWER": "Spell Damage",
    "CANT_BE_TARGETED_BY_SPELLS": "Untargetable",
    "CANT_BE_TARGETED_BY_HERO_POWERS": "Untargetable",
}
TEXT_PATTERNS = {
    "Battlecry": r"\bBattlecry\b",
    "Discover / Choice": r"\bDiscover\b", "Choose One": r"\bChoose One\b",
    "Transform": r"\btransform\b|\bturn\s+(?:it|them|that|this)\s+into\b", "Silence": r"\bsilence\b",
    "Summon": r"\bsummon\b", "Random effects": r"\brandom\b",
    "Cost modification": r"\bcosts?\s*\([0-9]+\)\s*(?:less|more)|\breduce[s]?\s+the\s+cost|\bcosts?\s+less\b|\bcosts?\s+more\b|\bset (?:its|their) cost\b",
    "Draw / Discard": r"\b(?:draw|discard)\b", "Targeting": r"\b(?:target|choose a|choose an)\b",
    "Trigger": r"\b(?:after|whenever|when|at the (?:start|end) of)\b",
    "Deck construction": r"\bstart the game\b",
    "Spell Damage": r"\bSpell Damage\b",
    "Conditional stats": r"\bHas\s+\+\d+(?:/\+\d+|\s+(?:Attack|Health))\s+for each\b",
    "Spell repeat": r"\bYour spells cast an additional time\b",
    "Untargetable": r"\bCan't be targeted by spells or Hero Powers\b",
}
SCRIPT_PATTERNS = {
    "Discover / Choice": r"\bDiscover\(", "Transform": r"\bTransform\(",
    "Silence": r"\bSilence\(", "Summon": r"\bSummon\(",
    "Cost modification": r"\bcost_mod\b|\bRefresh\([^\n]*GameTag\.COST|\bBuff\([^\n]*GameTag\.COST",
    "Draw / Discard": r"\b(?:Draw|Discard)\(",
    "Random effects": r"\bRandom[A-Za-z_]*\b|\bRANDOM_[A-Z_]+\b",
}
PHASE = {
    "Targeting": 1, "Deathrattle": 1, "Death processing": 1,
    "Zone movement": 1, "Reborn": 1, "Random effects": 1,
    "Battlecry": 2, "Spell resolution": 2, "Summon": 2, "Draw / Discard": 2,
    "Transform": 2, "Silence": 2,
    "Discover / Choice": 3, "Choose One": 3, "Trigger": 3, "Aura": 3,
    "Secret": 3, "Quest": 3, "Cost modification": 3,
    "Continuous effect / Update": 3, "Conditional stats": 3, "Spell repeat": 3,
    "Weapon": 4, "Hero Power": 4, "Hero Power modification": 4,
    "Combo": 4, "Overload": 4, "Deck construction": 4, "Spell Damage": 5,
    "Untargetable": 5, "All tribes": 5,
}
CONFIRMED_ERRORS = {
    "BT_427": ("play 抛 KeyError，正常牌局中本回合已有友方随从死亡仍复现", "fireplace/cards/initiate/demonhunter.py:125; reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_427"),
    "BT_753": ("play 抛 AttributeError: Destroy 对象没有 at 属性", "fireplace/cards/initiate/demonhunter.py:166; reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_753"),
    "BT_801": ("目标法术没有目标需求，正常 play 以空 TARGET 抛 AttributeError", "fireplace/cards/initiate/demonhunter.py:177; reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_801"),
    "BT_731": ("攻击敌方英雄造成伤害后，错误地将英雄变形为传染孢子：原英雄移至 SETASIDE，敌方场上出现 BT_731", "fireplace/cards/outlands/neutral_rare.py:30; reports/card_quality_full_2026-09-27/infectious_sporeling_probe.csv#SPORE-02"),
    "EX1_194": ("文案要求给予目标随从 +2/+6；实际只得到 +2/+2，3/5 目标变成 5/7 而非 5/11", "fireplace/cards/classic/priest.py:322-330; reports/card_quality_full_2026-09-27/basic_power_infusion_probe.csv#BASIC-INFUSION-01"),
    "NAX15_04": ("英雄技能文案要求随机夺取敌方随从；无目标时以空 TARGET 抛 AttributeError", "fireplace/cards/naxxramas/adventure.py:203; reports/card_quality_full_2026-09-27/foundation_probes.csv#TARGET-02"),
    "VAN_CS2_203": ("旧版猫头鹰可无目标出牌，随从已入场后沉默空 TARGET 抛 AttributeError", "fireplace/cards/custom/patch_wog.py:73; reports/card_quality_full_2026-09-27/foundation_probes.csv#TARGET-03"),
    "EX1_050": ("战吼双方各抽 2 张，但 cards_drawn_this_turn 全计在出牌者名下（+4/+0），造成错误玩家状态", "fireplace/actions.py:1240; reports/card_quality_full_2026-09-27/cross_player_draw_probe.csv#DRAW-01"),
    "EX1_136": ("含休眠随从的满场状态下，Redemption 被错误揭示消耗，却无法召唤复活随从", "fireplace/cards/utils.py:48; fireplace/dsl/selector.py:532; reports/card_quality_full_2026-09-27/dormant_full_board_probe.csv#SECRET-BOARD-01"),
    "GIL_819": ("友方随从死亡后未获得随机萨满法术；死亡事件匹配用的 FRIENDLY_MINIONS 要求死者仍在场", "reports/card_quality_full_2026-09-27/og_death_selector_probe.csv#death_zone_GIL_819"),
    "ICC_900": ("其他友方随从死亡后未召唤食尸鬼；死亡事件匹配用的 FRIENDLY_MINIONS 要求死者仍在场", "reports/card_quality_full_2026-09-27/og_death_selector_probe.csv#death_zone_ICC_900"),
    "CS2_142": ("沉默后仍保留原生法术伤害+1；玛里苟斯复现中的狗头人地卜师对照显示 spellpower 为 1→1", "fireplace/card.py:1118,1122-1145; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_563_spell_damage_and_silence"),
    "EX1_332": ("沉默法术没有移除目标原生法术伤害；沉默玛里苟斯后仍为 +5，沉默狗头人地卜师后仍为 +1", "fireplace/actions.py:1643-1652; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_563_spell_damage_and_silence"),
    "UNG_999t2": ("Living Spores 施加附魔后宿主死亡未召唤两株植物；附魔亡语未注册", "reports/card_quality_full_2026-09-27/foundation_probes.csv#DEATH-05"),
    "TB_PickYourFate_7_2nd": ("Dire Fate: Manaburst 施加附魔后宿主死亡未使手牌费用归零；附魔亡语未注册", "reports/card_quality_full_2026-09-27/foundation_probes.csv#DEATH-06"),
    "DRG_058": ("攻击力只按入场时手牌龙数结算一次，手牌龙数改变后仍保持原值", "fireplace/cards/dragons/neutral_common.py:50; reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-01"),
    "DRG_088": ("只有自身时已经额外 +3 攻击；拥有 2 个其他 Dread Raven 时仍仅额外 +3", "fireplace/cards/dragons/neutral_epic.py:58; reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-02"),
    "TB_KTRAF_5": ("攻击力固定等于自身 5 点生命值，未随对手手牌数 0→1→0 改变", "fireplace/cards/brawl/ktraf.py:59; reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-03"),
    "TB_BaconUps_036": ("场上增加和移除其他鱼人时，攻击力仍固定 4；未实现文案的每个鱼人 +2", "reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-04"),
    "ULDA_501": ("场上增加和移除其他随从时，攻击力仍固定 3；未实现文案的每个其他随从 +2", "reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-05"),
    "ICC_841": ("弃掉 2 张牌后攻击力仍为 1；弃牌历史没有转成文案要求的持续攻击力", "fireplace/cards/icecrown/warlock.py:26; reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-07"),
    "DALA_503": ("两只 Kirin Tor Guard 同场时攻击力仍各为 1，未按其他同名随从数增加", "reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-08"),
    "GILA_403": ("友方野兽死亡后 Butch 仍为 1/1，未获得文案要求的 +1/+1", "reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-09"),
    "GILA_907": ("施放两张法术后 Clockwork Assistant 仍为 1/1，未获得文案要求的累计 +1/+1", "reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-10"),
    "DALA_504": ("附加施放效果未执行；Fireball 对英雄只造成 6 点而非 12 点", "reports/card_quality_full_2026-09-27/mode_ongoing_probe.csv#MODE-01"),
    "TB_BaconUps_008": ("鱼人光环未生效；受益鱼人攻击力仍为 2 而非 6", "reports/card_quality_full_2026-09-27/mode_ongoing_probe.csv#MODE-02"),
    "TB_BaconUps_038": ("嘲讽光环未生效；受益随从攻击力仍为 1 而非 5", "reports/card_quality_full_2026-09-27/mode_ongoing_probe.csv#MODE-03"),
}
ERROR_LABELS = {
    "BT_427": {"Draw / Discard", "Spell resolution"},
    "BT_753": {"Trigger", "Spell resolution"},
    "BT_801": {"Targeting", "Spell resolution"},
    "BT_731": {"Targeting", "Trigger", "Transform"},
    "EX1_194": {"Spell resolution"},
    "NAX15_04": {"Targeting", "Random effects", "Hero Power"},
    "VAN_CS2_203": {"Targeting", "Silence"},
    "EX1_050": {"Battlecry", "Draw / Discard"},
    "EX1_136": {"Secret", "Trigger"},
    "GIL_819": {"Random effects", "Trigger"},
    "ICC_900": {"Summon", "Trigger"},
    "CS2_142": {"Spell Damage"},
    "EX1_332": {"Silence", "Spell resolution"},
    "UNG_999t2": {"Spell resolution", "Summon"},
    "TB_PickYourFate_7_2nd": {"Spell resolution", "Random effects"},
    "DRG_058": {"Conditional stats"},
    "DRG_088": {"Conditional stats", "Continuous effect / Update"},
    "TB_KTRAF_5": {"Conditional stats", "Continuous effect / Update"},
    "TB_BaconUps_036": {"Conditional stats"},
    "ULDA_501": {"Conditional stats"},
    "ICC_841": {"Conditional stats", "Continuous effect / Update"},
    "DALA_503": {"Conditional stats"},
    "GILA_403": {"Conditional stats"},
    "GILA_907": {"Conditional stats"},
    "DALA_504": {"Spell repeat"},
    "TB_BaconUps_008": {"Aura"},
    "TB_BaconUps_038": {"Aura"},
}
MISSING_DEATH_TAG = {
    "YOD_016": "DEATH-03", "VAN_EX1_029": "DEATH-04",
    "UNG_999t2e": "DEATH-05", "TB_PickYourFate_7_EnchMiniom2nd": "DEATH-06",
}
DRAW_COUNTER_CANDIDATES = {"EX1_161", "GVG_032", "FP1_029", "OG_338", "DRG_077", "DRG_084"}
FULL_BOARD_CANDIDATES = {"EX1_130", "EX1_554", "tt_010", "ICC_200", "GIL_577", "AT_060",
                         "AT_002", "TRL_400", "BT_203", "BT_003", "BT_707", "UNG_111"}
CAST_OBSERVER_CANDIDATES = {
    "EX1_055", "EX1_095", "NEW1_020", "NEW1_026", "EX1_187", "EX1_145o",
    "KAR_021", "KAR_035", "KAR_036", "KAR_097t", "ULD_329", "DAL_182",
    "TB_PickYourFate_8_Ench", "LOE_086", "YOD_042", "DRG_322e", "VAN_EX1_145o",
    "OG_121e", "OG_303", "OG_085", "AT_061e", "UNG_832e", "BRM_002", "CFM_060", "CFM_807",
}
PROBE_GREEN = {
    "CS2_188": {"Battlecry": "BATTLE-01", "Targeting": "BATTLE-01"},
    "CS2_029": {"Spell resolution": "SPELL-01", "Targeting": "SPELL-01"},
    "BT_173": {"Spell resolution": "SUMMON-01|SUMMON-02", "Summon": "SUMMON-01|SUMMON-02"},
    "CS2_023": {"Draw / Discard": "DRAW-01", "Spell resolution": "DRAW-01"},
    "EX1_308": {"Draw / Discard": "DISCARD-01", "Spell resolution": "DISCARD-01", "Targeting": "DISCARD-01"},
    "EX1_332": {"Silence": "SILENCE-01", "Spell resolution": "SILENCE-01", "Targeting": "SILENCE-01"},
    "EX1_160": {"Choose One": "CHOICE-01|CHOICE-02", "Spell resolution": "CHOICE-01|CHOICE-02",
                  "Summon": "CHOICE-01|CHOICE-02"},
    "NEW1_012": {"Trigger": "TRIGGER-01"},
    "EX1_162": {"Aura": "AURA-01", "Continuous effect / Update": "AURA-01"},
    "AT_073": {"Secret": "SECRET-01", "Spell resolution": "SECRET-01", "Trigger": "SECRET-01"},
    "EX1_287": {"Secret": "SECRET-02", "Spell resolution": "SECRET-02", "Trigger": "SECRET-02"},
    "BRM_028": {"Cost modification": "COST-01", "Trigger": "COST-01"},
    "CS2_091": {"Weapon": "WEAPON-01"},
    "HERO_08bp": {"Hero Power": "HPOWER-01", "Targeting": "HPOWER-01"},
    "EX1_134": {"Combo": "COMBO-01", "Targeting": "COMBO-01"},
    "GIL_113": {"Rush": "KEYWORD-01"},
    "GIL_143": {"Lifesteal": "KEYWORD-02", "Rush": "KEYWORD-02"},
    "EX1_170": {"Poisonous": "KEYWORD-03"},
    "ULD_205": {"Reborn": "KEYWORD-04"},
    "BT_491": {"Draw / Discard": "OUTCAST-01", "Outcast": "OUTCAST-01", "Spell resolution": "OUTCAST-01"},
    "BT_921": {"Lifesteal": "WEAPON-02", "Weapon": "WEAPON-02"},
    "DRG_211": {"Spell Damage": "SPELLPOWER-01"},
    "EX1_062": {"Conditional stats": "STATS-06", "Continuous effect / Update": "STATS-06"},
}
BASIC_RUNTIME_GREEN = {
    "CS2_042": ("battlecry_CS2_042", {"Battlecry", "Targeting"}),
    "CS2_147": ("battlecry_CS2_147", {"Battlecry", "Draw / Discard"}),
    "CS2_226": ("battlecry_CS2_226", {"Battlecry"}),
    "CS2_026": ("spell_CS2_026", {"Spell resolution"}),
    "CS2_012": ("spell_CS2_012", {"Spell resolution", "Targeting"}),
    "CS2_009": ("spell_CS2_009", {"Spell resolution", "Targeting"}),
    "CS2_025": ("spell_CS2_025", {"Spell resolution"}),
    "CS2_039": ("spell_CS2_039", {"Spell resolution", "Targeting"}),
    "CS2_097": ("weapon_CS2_097", {"Weapon", "Trigger"}),
    "CS2_080": ("weapon_CS2_080", {"Weapon"}),
    "CS2_106": ("weapon_CS2_106", {"Weapon"}),
    "CS2_112": ("weapon_CS2_112", {"Weapon"}),
}
NATIVE_TAG_FOR_LABEL = {
    "Taunt": "TAUNT", "Rush": "RUSH", "Reborn": "REBORN", "Lifesteal": "LIFESTEAL",
    "Poisonous": "POISONOUS", "Stealth": "STEALTH", "Charge": "CHARGE",
    "Windfury": "WINDFURY", "Divine Shield": "DIVINE_SHIELD", "Magnetic": "MAGNETIC",
    "Echo": "ECHO", "Twinspell": "TWINSPELL", "Spell Damage": "SPELLPOWER",
    "Overload": "OVERLOAD",
}


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clean_text(card, locale="enUS"):
    value = card.strings.get(GameTag.CARDTEXT, {})
    if isinstance(value, dict):
        value = value.get(locale, "")
    return re.sub(r"<[^>]+>", "", value or "").replace("\n", " ").replace("_", " ").strip()


def localized_name(card, locale):
    value = card.strings.get(GameTag.CARDNAME, {})
    return value.get(locale, "") if isinstance(value, dict) else ""


def source_of(cls):
    if cls is None:
        return "", ""
    try:
        source = inspect.getsource(cls)
        file = Path(inspect.getsourcefile(cls)).resolve().relative_to(ROOT)
        return source, f"{file}:{inspect.getsourcelines(cls)[1]}"
    except (OSError, TypeError, ValueError):
        return "", ""


def direct_play_target_without_requirement(source, card):
    if not source or any(key in TARGETING_PREREQUISITES for key in card.requirements):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for statement in class_node.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(isinstance(target, ast.Name) and target.id in {"play", "activate", "combo"} for target in targets):
                if any(isinstance(node, ast.Name) and node.id == "TARGET" for node in ast.walk(statement.value)):
                    return True
    return False


def test_mentions(valid_ids):
    refs = defaultdict(list)
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError):
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)) or not func.name.startswith("test_"):
                continue
            for node in ast.walk(func):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in valid_ids:
                    ref = f"{path.relative_to(ROOT)}:{node.lineno}:{func.name}"
                    if ref not in refs[node.value]:
                        refs[node.value].append(ref)
    return refs


def scope_of(card, is_xml):
    setname = getattr(card.card_set, "name", str(card.card_set))
    ctype = getattr(card.type, "name", str(card.type))
    if not is_xml:
        return "runtime_custom"
    if setname == "CREDITS":
        return "metadata"
    if setname == "HERO_SKINS":
        return "cosmetic"
    if card.id in STARTING_HERO_IDS and card.type == CardType.HERO:
        # XML marks these collectible, but they are starting identities rather
        # than cards that can be put into a deck (see arena/pool.py).
        return "hero_identity"
    if card.collectible:
        return "ordinary_collectible"
    if ctype in PLAY_TYPES:
        return "mode_playable" if setname in {"TB", "BATTLEGROUNDS", "MISSIONS", "TAVERNS_OF_TIME", "WILD_EVENT"} else "generated_playable"
    return "supporting_entity"


def labels_for(card, raw_card, source, text):
    labels = defaultdict(set)
    for tag, label in STRUCTURED.items():
        enum = getattr(GameTag, tag, None)
        if enum is not None and card.tags.get(enum):
            labels[label].add("xml_tag" if raw_card is not None and raw_card.tags.get(enum) else "runtime_tag")
    for label, pattern in TEXT_PATTERNS.items():
        if re.search(pattern, text, re.I):
            labels[label].add("card_text")
    # Source matches are candidates, not proof: a class may contain comments or
    # conditional actions, and action nesting does not imply the whole effect.
    for label, pattern in SCRIPT_PATTERNS.items():
        if re.search(pattern, source):
            labels[label].add("python_source")
    if re.search(r"^\s*deathrattle\s*=", source, re.M):
        labels["Deathrattle"].add("python_script_slot")
    if "events =" in source or "class Hand:" in source or "class Deck:" in source:
        labels["Trigger"].add("python_source")
    if re.search(r"^\s*update\s*=", source, re.M):
        labels["Continuous effect / Update"].add("python_script_slot")
    if any(key in TARGETING_PREREQUISITES for key in card.requirements):
        labels["Targeting"].add("target_requirement")
    if re.search(r"\bTARGET\b", source):
        labels["Targeting"].add("python_source_target_candidate")
    if card.type == CardType.WEAPON:
        labels["Weapon"].add("card_type")
    if card.type == CardType.HERO_POWER:
        labels["Hero Power"].add("card_type")
    if card.type == CardType.SPELL:
        labels["Spell resolution"].add("card_type")
    if getattr(card.race, "name", "") == "ALL":
        labels["All tribes"].add("race_tag")
    if not labels:
        fallback = "Vanilla" if card.type == CardType.MINION and not text and not source else "Unclassified effect"
        labels[fallback].add("fallback")
    return labels


def implementation_for(card, cls, source, text):
    if cls is not None:
        # A class can still be broken or only partially implement the text.
        return "implemented"
    if card.id in {"BOT_914", "DAL_800"}:
        # Their deck replacement is handled during Player.prepare_for_game.
        return "implemented"
    if card.type in {CardType.WEAPON, CardType.HERO}:
        # Basic equipment and hero identity are handled by card.py from XML
        # stats/keyword tags. A missing per-card Python class is expected.
        return "implemented"
    if card.tags.get(GameTag.HEROPOWER_DAMAGE):
        return "implemented"  # Native engine tag; compare amount with card text separately.
    if card.type == CardType.MINION:
        if not text:
            return "implemented"
        if ("Can't be targeted by spells or Hero Powers" in text
                and card.tags.get(GameTag.CANT_BE_TARGETED_BY_SPELLS)
                and card.tags.get(GameTag.CANT_BE_TARGETED_BY_HERO_POWERS)):
            return "implemented"
        if getattr(card.race, "name", "") == "ALL" and "This is an Elemental" in text:
            return "implemented"
        native_only = re.sub(r"\b(?:Taunt|Rush|Reborn|Lifesteal|Poisonous|Stealth|Charge|Windfury|Divine Shield|Magnetic|Echo|Twinspell|Immune|Can't attack|Cannot attack)\b", "", text, flags=re.I)
        native_only = re.sub(r"\bSpell Damage\s*\+\d+\b|\bOverload:\s*\(\d+\)", "", native_only, flags=re.I)
        if not re.sub(r"[\s.,;:()\d+/-]+", "", native_only):
            return "implemented"  # Only native keyword/stat tags remain.
        native_tags = ("TAUNT", "RUSH", "REBORN", "LIFESTEAL", "POISONOUS", "STEALTH",
                       "CHARGE", "WINDFURY", "DIVINE_SHIELD", "MAGNETIC", "ECHO",
                       "TWINSPELL", "SPELLPOWER", "OVERLOAD")
        if any(card.tags.get(getattr(GameTag, tag)) for tag in native_tags if hasattr(GameTag, tag)):
            return "partial"  # Native keyword exists, other printed behavior has no known script.
        return "none"
    return "none"


def main():
    OUT.mkdir(exist_ok=True)
    digest, source_count, source_latest_mtime_ns = source_snapshot()
    raw, _ = cardxml.load(path=str(XML), locale="enUS")
    db.initialize()
    prior = {r["card_id"]: r for r in csv.DictReader((PRIOR / "deathrattle_quality_map.csv").open(encoding="utf-8-sig", newline=""))}
    smoke = {r["card_id"]: r for r in json.loads(SMOKE.read_text())} if SMOKE.exists() else {}
    overload_file = OUT / "overload_reproductions.csv"
    overload = {r["card_id"]: r for r in csv.DictReader(overload_file.open(encoding="utf-8-sig", newline=""))} if overload_file.exists() else {}
    target_file = OUT / "targeting_prereq_sweep.csv"
    target_sweep = {r["card_id"]: r for r in csv.DictReader(target_file.open(encoding="utf-8-sig", newline=""))} if target_file.exists() else {}
    probe_file = OUT / "later_stage_probes.csv"
    effect_probes = {r["case_id"]: r for r in csv.DictReader(probe_file.open(encoding="utf-8-sig", newline=""))} if probe_file.exists() else {}
    basic_corruption_file = OUT / "basic_corruption_probe.csv"
    basic_corruption = {r["case_id"]: r for r in csv.DictReader(basic_corruption_file.open(encoding="utf-8-sig", newline=""))} if basic_corruption_file.exists() else {}
    basic_runtime_file = OUT / "basic_runtime_probe.csv"
    basic_runtime = {r["case_id"]: r for r in csv.DictReader(basic_runtime_file.open(encoding="utf-8-sig", newline=""))} if basic_runtime_file.exists() else {}
    vanilla_runtime_file = OUT / "vanilla_runtime_probe.csv"
    vanilla_runtime = {r["case_id"]: r for r in csv.DictReader(vanilla_runtime_file.open(encoding="utf-8-sig", newline=""))} if vanilla_runtime_file.exists() else {}
    basic_tests_file = OUT / "basic_existing_tests.csv"
    basic_tests = {r["card_id"]: r for r in csv.DictReader(basic_tests_file.open(encoding="utf-8-sig", newline=""))} if basic_tests_file.exists() else {}
    card_verdicts = {}
    verdict_names = ("basic_card_verdicts.csv", "classic_verdict_first.csv",
                         "classic_verdict_middle_a.csv", "classic_verdict_second.csv",
                         "classic_verdict_middle_b.csv", "classic_verdict_final10.csv",
                         "classic_verdict_tail.csv",
                         "hof_verdict.csv", "naxx_verdict.csv",
                         "gvg_verdict.csv", "brm_verdict.csv", "tgt_verdict.csv", "loe_verdict.csv",
                         "og_verdict.csv", "three_set_verdict.csv", "icc_verdict.csv")
    for verdict_path in ([OUT / name for name in verdict_names]
                         + sorted(OUT.glob("set_verdict_*.csv"))):
        if verdict_path.exists():
            for row in csv.DictReader(verdict_path.open(encoding="utf-8-sig", newline="")):
                assert row["card_id"] not in card_verdicts, row["card_id"]
                card_verdicts[row["card_id"]] = row
    residual_verdict_path = OUT / "residual_verdict.csv"
    residual_ids = set()
    residual_previous_evidence = {}
    if residual_verdict_path.exists():
        residual_rows = list(csv.DictReader(residual_verdict_path.open(encoding="utf-8-sig", newline="")))
        if len(residual_rows) == 25:
            residual_baseline = [
                row for row in csv.DictReader(
                    (OUT / "remaining_yellow_baseline.csv").open(encoding="utf-8-sig", newline=""))
                if row["set"].endswith(("(BASIC)", "(EXPERT1)", "(GVG)",
                                        "(LOE)", "(GANGS)", "(OG)"))
            ]
            expected_residual_ids = {row["card_id"] for row in residual_baseline}
            assert {row["card_id"] for row in residual_rows} == expected_residual_ids
            residual_ids = expected_residual_ids
            residual_previous_evidence = {row["card_id"]: row["evidence"] for row in residual_baseline}
            for row in residual_rows:
                assert row["card_id"] in card_verdicts, row["card_id"]
                card_verdicts[row["card_id"]] = row
    card_probe_rows = {}
    probe_paths = list(OUT.glob("basic_card_probe_*.csv"))
    probe_paths += [OUT / name for name in ("classic_probe_first.csv", "classic_probe_middle_a.csv",
                                           "classic_probe_second.csv", "classic_probe_middle_b.csv",
                                           "classic_probe_final10.csv",
                                           "classic_probe_tail.csv",
                                           "hof_probe.csv", "naxx_probe.csv",
                                           "gvg_probe.csv", "brm_probe.csv", "tgt_probe.csv", "loe_probe.csv",
                                           "og_probe.csv", "three_set_probe.csv", "icc_probe.csv")
                    if (OUT / name).exists()]
    probe_paths += sorted(OUT.glob("set_probe_*.csv"))
    if residual_verdict_path.exists() and len(residual_rows) == 25:
        residual_probe_path = OUT / "residual_probe.csv"
        assert residual_probe_path.exists()
        probe_paths.append(residual_probe_path)
    for probe_path in probe_paths:
        card_probe_rows[probe_path.name] = list(csv.DictReader(probe_path.open(encoding="utf-8-sig", newline="")))
    refs = test_mentions(set(raw))
    inv = list(csv.DictReader((PRIOR / "set_inventory.csv").open(encoding="utf-8-sig", newline="")))
    setnames = {r["set"].split(" (")[1][:-1]: r["set"] for r in inv if " (" in r["set"]}
    master, quality, mechanisms, issues, smoke_rows, target_rows = [], [], [], [], [], []
    count_by_set = defaultdict(Counter)
    for cid, card in sorted(db.items(), key=lambda x: (getattr(x[1].card_set, "name", ""), x[0])):
        is_xml = cid in raw
        scope = scope_of(card, is_xml)
        setcode = getattr(card.card_set, "name", str(card.card_set))
        setname = setnames.get(setcode, f"{setcode} (runtime)")
        cls = get_script_definition(cid, card) if is_xml else card.scripts.__bases__[0]
        source, srcpath = source_of(cls)
        en = localized_name(card, "enUS")
        zh = localized_name(card, "zhCN")
        desc = clean_text(card)
        labels = labels_for(card, raw.get(cid), source, desc)
        impl = implementation_for(card, cls, source, desc)
        if scope == "ordinary_collectible" and direct_play_target_without_requirement(source, card):
            if cid in {"BT_801", "NAX15_04", "VAN_CS2_203"}:
                verdict = "confirmed_error"
                candidate_evidence = ("reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_801" if cid == "BT_801" else
                                      "reports/card_quality_full_2026-09-27/foundation_probes.csv#" + ("TARGET-02" if cid == "NAX15_04" else "TARGET-03"))
            elif cid in {"HERO_05bp", "HERO_05bp2"}:
                verdict = "special_steady_shot_rule"
                candidate_evidence = "REQ_STEADY_SHOT and STEADY_SHOT_CAN_TARGET gate manual targeting"
            else:
                verdict = "internal_target_candidate"
                candidate_evidence = "TARGET refers to a generated/internal entity; no manual target prerequisite proven"
            target_rows.append(dict(card_id=cid, name_en=localized_name(card, "enUS"),
                                    set=setname, source=srcpath,
                                    verdict=verdict, evidence=candidate_evidence))
        base = dict(version=VERSION if is_xml else VERSION + "+runtime_custom", set=setname,
                    card_id=cid, name_en=en, name_zh=zh, card_type=getattr(card.type, "name", ""),
                    scope=scope, collectible="yes" if card.collectible else "no",
                    implementation=impl, python_source=srcpath, card_text_en=desc)
        def tag_json(tags):
            return json.dumps({getattr(key, "name", str(key)): str(value) for key, value in tags.items()}, ensure_ascii=False, sort_keys=True)
        master.append({**base, "mechanics": "|".join(sorted(labels)), "dbf_id": card.dbf_id,
                       "origin": "xml" if is_xml else "custom_script",
                       "card_text_zh": clean_text(card, "zhCN"),
                       "raw_xml_tags": tag_json(raw[cid].tags) if is_xml else "{}",
                       "runtime_tags": tag_json(card.tags),
                       "requirements": json.dumps({getattr(key, "name", str(key)): str(value) for key, value in card.requirements.items()}, ensure_ascii=False, sort_keys=True),
                       "test_refs_candidate": " | ".join(refs.get(cid, [])[:8]),
                       "xml_source": f"fireplace/cards/CardDefs.xml#{cid}" if is_xml else "runtime custom_card"})
        count_by_set[setname]["runtime_total"] += 1
        count_by_set[setname][scope] += 1
        if scope in {"metadata", "cosmetic", "hero_identity"}:
            continue
        testref = " | ".join(refs.get(cid, [])[:8])
        smoke_event = smoke.get(cid)
        smoke_label = smoke_event["outcome"] if smoke_event else "not_run"
        if smoke_event:
            # Keep the inventory's display set name; the raw smoke JSON uses
            # enum codes such as BASIC, which would break per-set joins.
            smoke_rows.append({**smoke_event, **base})
        itemrows = []
        for label in sorted(labels):
            provenance = "+".join(sorted(labels[label]))
            status = "YELLOW"
            tested = "partial" if smoke_event or testref else "no"
            reason = ("未找到逐卡脚本或已识别的原生实现路径；尚未运行足以确认未实现的效果复现。"
                      if impl == "none" else
                      "存在定义或元数据候选；当前没有可复查的该机制核心效果断言。")
            evidence = "; ".join(x for x in [f"fireplace/cards/CardDefs.xml#{cid}", srcpath, testref,
                                            f"generic-play-smoke:{smoke_label}" if smoke_event else ""] if x)
            notes = "机制标签为候选，来源=" + provenance
            if cid in DRAW_COUNTER_CANDIDATES and label == "Draw / Discard":
                notes += "; DRAW-001 共享抽牌计数路径风险，尚未逐卡复现"
                evidence += "; mechanism_issues.csv#DRAW-001"
            if cid in FULL_BOARD_CANDIDATES and label in {"Secret", "Summon"} and cid not in card_verdicts:
                notes += "; BOARD-001 休眠占场位路径风险，尚未逐卡复现"
                evidence += "; mechanism_issues.csv#BOARD-001"
            if cid in CAST_OBSERVER_CANDIDATES and label == "Trigger":
                notes += "; CAST-001 效果代施放与玩家出牌事件不同；规则语义待核实"
                evidence += "; mechanism_issues.csv#CAST-001"
            mech_impl = impl
            native_tag = NATIVE_TAG_FOR_LABEL.get(label)
            if cls is None and native_tag and hasattr(GameTag, native_tag) and card.tags.get(getattr(GameTag, native_tag)):
                mech_impl = "implemented"
            if label == "Deathrattle" and cid in prior:
                p = prior[cid]
                status, tested, mech_impl = p["status"], p["tested"], p["implementation"]
                reason, evidence = p["reason"], p["evidence"]
                notes = p["notes"] + "; 继承已完成的亡语专项审计"
            if label == "Deathrattle" and cid in MISSING_DEATH_TAG:
                status, tested, mech_impl = "RED", "yes", "partial"
                reason = "有 deathrattle 脚本但无 DEATHRATTLE 标签；实际死亡时核心效果未触发。"
                evidence = "reports/card_quality_full_2026-09-27/foundation_probes.csv#" + MISSING_DEATH_TAG[cid]
                notes = "专项静态筛选出 4 个脚本槽与运行时标签不一致的实体，逐一复现。"
            if label == "Overload" and cid in overload:
                result = overload[cid]
                if result["outcome"] == "pass":
                    status, tested, reason = "GREEN", "yes", "出牌后欠费、下一己方回合锁费与可用法力均与卡牌 Overload 标签一致。"
                elif result["outcome"] in {"wrong_state", "exception"}:
                    status, tested, reason = "RED", "yes", "过载状态运行复现不符合期望：" + result["outcome"]
                evidence = f"reports/card_quality_full_2026-09-27/overload_reproductions.csv#{cid}"
            if label == "Targeting" and cid in target_sweep and target_sweep[cid]["outcome"] == "rejected_no_target":
                tested = "partial"
                reason = "缺目标与非法自身目标均在付费/移区前被拒绝；合法目标效果仍需逐卡验证。"
                evidence += f"; reports/card_quality_full_2026-09-27/targeting_prereq_sweep.csv#{cid}"
            if cid == "CS2_022" and label in {"Targeting", "Transform", "Spell resolution"}:
                status, tested, reason = "GREEN", "yes", "实际指定随从并变形为绵羊；原实体移至 SETASIDE，法术进入墓地，非法英雄目标被拒绝。"
                evidence = "reports/card_quality_full_2026-09-27/foundation_probes.csv#ZONE-02|TARGET-01"
            if cid == "EX1_049" and label in {"Battlecry", "Targeting"}:
                status, tested, reason = "GREEN", "yes", "战吼可指定友方随从并将其从战场返回手牌，战吼随从留在战场。"
                evidence = "reports/card_quality_full_2026-09-27/foundation_probes.csv#ZONE-03"
            if cid == "LOE_006" and label in {"Battlecry", "Discover / Choice"}:
                status, tested, reason = "GREEN", "yes", "战吼产生 3 个不同亡语随从选项；非法选择拒绝、选择时其他行动被阻止，选中卡进入手牌。"
                evidence = "reports/card_quality_full_2026-09-27/foundation_probes.csv#CHOICE-01"
            probe_case_ids = PROBE_GREEN.get(cid, {}).get(label, "").split("|")
            if probe_case_ids != [""] and all(effect_probes.get(case_id, {}).get("outcome") == "pass" for case_id in probe_case_ids):
                status, tested = "GREEN", "yes"
                reason = "实际运行的核心效果及对应目标、区域、回合或持续状态断言通过；范围限所列复现场景。"
                evidence = "; ".join("reports/card_quality_full_2026-09-27/later_stage_probes.csv#" + case_id
                                     for case_id in probe_case_ids)
            if (cid == "CS2_063" and label in {"Spell resolution", "Targeting", "Trigger"}
                    and basic_corruption.get("BASIC-CORRUPTION-01", {}).get("outcome") == "pass"):
                status, tested = "GREEN", "yes"
                reason = "仅能指定敌方随从；施法与附魔落区正确，跨过对手回合后在己方回合开始销毁目标。"
                evidence = "reports/card_quality_full_2026-09-27/basic_corruption_probe.csv#BASIC-CORRUPTION-01"
            test_case = basic_tests.get(cid)
            if (test_case and test_case["outcome"] == "pass"
                    and test_case["coverage_level"] == "full_candidate"
                    and test_case["source_sha256"] == digest
                    and label in test_case["mechanic"].split("|")):
                status, tested = "GREEN", "yes"
                reason = "已逐项核对测试中的核心效果和相关状态断言；本次在当前源码上重新运行通过。"
                evidence = (f"{test_case['test_node']}; "
                            f"reports/card_quality_full_2026-09-27/basic_existing_tests.csv#{cid}")
            runtime_cases = []
            if scope == "ordinary_collectible" and setcode == "BASIC" and cls is None and card.type == CardType.MINION:
                if label == "Vanilla":
                    runtime_cases = [f"entry_{cid}"]
                elif label in {"Taunt", "Charge", "Spell Damage"}:
                    case_prefix = {"Taunt": "taunt", "Charge": "charge", "Spell Damage": "spell_damage"}[label]
                    runtime_cases = [f"entry_{cid}", f"{case_prefix}_{cid}"]
            if cid in BASIC_RUNTIME_GREEN and label in BASIC_RUNTIME_GREEN[cid][1]:
                runtime_cases = [BASIC_RUNTIME_GREEN[cid][0]]
            if runtime_cases and all(basic_runtime.get(case_id, {}).get("outcome") == "PASS" for case_id in runtime_cases):
                status, tested = "GREEN", "yes"
                reason = "当前源码的真实游戏运行中，核心效果及关键目标、属性、区域或回合状态断言通过。"
                evidence = "; ".join("reports/card_quality_full_2026-09-27/basic_runtime_probe.csv#" + case_id
                                     for case_id in runtime_cases)
            vanilla_case = f"entry_{cid}"
            if (scope == "ordinary_collectible" and setcode != "BASIC" and cls is None
                    and card.type == CardType.MINION and not desc and label == "Vanilla"
                    and vanilla_runtime.get(vanilla_case, {}).get("outcome") == "PASS"):
                status, tested = "GREEN", "yes"
                reason = "无描述效果及逐卡脚本；实际运行核对了手牌和入场后的费用、属性、种族、种族选择器与区域。"
                evidence = f"reports/card_quality_full_2026-09-27/vanilla_runtime_probe.csv#{vanilla_case}"
            card_verdict = card_verdicts.get(cid)
            if card_verdict and label in card_verdict["mechanic_scope"].split("|"):
                probe_name = card_verdict["probe_file"]
                assert probe_name in card_probe_rows, (cid, probe_name)
                cases = [row for row in card_probe_rows[probe_name] if row["card_id"] == cid]
                assert cases and len({row["case_id"] for row in cases}) == len(cases), cid
                verdict = card_verdict["status"]
                assert verdict in {"GREEN", "RED", "YELLOW"}, (cid, verdict)
                if verdict == "GREEN":
                    assert all(row["outcome"] == "pass" for row in cases), cid
                if verdict == "RED":
                    assert any(row["outcome"] == "confirmed_error" for row in cases), cid
                status, tested = verdict, "yes" if verdict != "YELLOW" else "partial"
                if verdict == "RED":
                    mech_impl = "partial" if cls is not None else "none"
                reason = card_verdict["reason"]
                evidence = "; ".join(f"reports/card_quality_full_2026-09-27/{probe_name}#{row['case_id']}"
                                     for row in cases)
                notes += "; 逐卡定向行为测试：" + card_verdict["notes"]
            if cid in CONFIRMED_ERRORS and label in ERROR_LABELS[cid]:
                reason, evidence = CONFIRMED_ERRORS[cid]
                status, tested = "RED", "yes"
                mech_impl = "partial" if cid == "CS2_142" or cls is not None else "none"
            if label == "Hero Power modification" and cid in {"AT_003", "YOD_008"}:
                tested = "yes"
                evidence = ("reports/card_quality_full_2026-09-27/hero_power_reproductions.csv#" + cid +
                            "; fireplace/cards/CardDefs.xml#" + cid)
                if cid == "AT_003":
                    status, reason = "GREEN", "正常牌局中火焰冲击由 1 点变为 2 点，符合额外 +1。"
                else:
                    status, mech_impl = "RED", "partial"
                    reason = "文案要求额外 +2，XML HEROPOWER_DAMAGE=1；实测火焰冲击只造成 2 点，预期 3 点。"
            itemrows.append({**base, "mechanic": label, "status": status, "implementation": mech_impl,
                             "tested": tested, "reason": reason, "evidence": evidence,
                             "notes": notes, "label_basis": provenance})
        # Deathrattle audit includes dynamically conferred tags missing from raw text.
        if cid in prior and not any(r["mechanic"] == "Deathrattle" for r in itemrows):
            p = prior[cid]
            itemrows.append({**base, "mechanic": "Deathrattle", "status": p["status"],
                             "implementation": p["implementation"], "tested": p["tested"],
                             "reason": p["reason"], "evidence": p["evidence"],
                             "notes": p["notes"] + "; runtime tag from prior audit", "label_basis": "runtime_tag"})
        mechanisms.extend(itemrows)
        order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
        worst = max(itemrows, key=lambda x: order[x["status"]])["status"]
        if cid in CONFIRMED_ERRORS:
            worst = "RED"
        tested = "yes" if all(x["tested"] == "yes" for x in itemrows) else "partial" if any(x["tested"] != "no" for x in itemrows) else "no"
        missing = sum(x["status"] == "YELLOW" for x in itemrows)
        red = sum(x["status"] == "RED" for x in itemrows)
        if red:
            reason = f"{red} 个机制确认有错误或缺失；逐机制依据见 card_mechanism.csv。"
        elif missing:
            reason = f"{missing} 个机制缺少充分的核心效果验证；逐机制依据见 card_mechanism.csv。"
        else:
            reason = "当前列出的机制均有对应场景的效果断言；结论限于已识别标签与复现范围。"
        implementations = {x["implementation"] for x in itemrows}
        whole_impl = ("none" if implementations == {"none"} else
                      "partial" if "partial" in implementations or "none" in implementations else "implemented")
        direct_evidence = list(dict.fromkeys(row["evidence"] for row in itemrows
                                             if row["status"] in {"GREEN", "RED"}))
        whole_evidence = f"card_mechanism.csv#{cid}; " + (f"generic-play-smoke:{smoke_label}" if smoke_event else "smoke:not_run")
        if direct_evidence:
            whole_evidence += "; effect-evidence: " + " | ".join(direct_evidence)
        if cid in CONFIRMED_ERRORS:
            reason = CONFIRMED_ERRORS[cid][0]
        whole_notes = "聚合状态取该卡最差机制；普通烟测只证明可执行，不能单独构成 GREEN。"
        if cid in card_verdicts:
            card_verdict = card_verdicts[cid]
            assert worst == card_verdict["status"], cid
            reason = card_verdict["reason"]
            probe_name = card_verdict["probe_file"]
            cases = [row for row in card_probe_rows[probe_name] if row["card_id"] == cid]
            whole_evidence += "; per-card: " + "; ".join(
                f"reports/card_quality_full_2026-09-27/{probe_name}#{row['case_id']}"
                for row in cases)
            whole_notes += " " + card_verdict["notes"]
        if cid in residual_ids:
            whole_evidence += "; previous per-card audit: " + residual_previous_evidence[cid]
        quality.append({**base, "mechanic": "|".join(x["mechanic"] for x in itemrows),
                        "status": worst, "implementation": whole_impl, "tested": tested, "reason": reason,
                        "evidence": whole_evidence,
                        "notes": whole_notes})
        count_by_set[setname][worst] += 1
    # The issue ledger records confirmed shared failures plus scope of further checks.
    issues = [
        dict(issue_id="DEATH-001", mechanism="Death processing", severity="confirmed",
             summary="同一死亡批次逐个触发亡语并重新检查 dead；增益亡语能救回本应同批死亡的随从。",
             evidence="fireplace/actions.py:356-374; reports/card_quality_full_2026-09-27/foundation_probes.csv#DEATH-01; reports/card_quality_full_2026-09-27/naxx_probe.csv#same_batch_dead_ally; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_407_random_survivor_and_batch_deathrattle; reports/card_quality_full_2026-09-27/icc_probe.csv#ICC_047::growth_same_batch_death",
             confirmed_cards="OG_256|LOE_061|FP1_023|OG_158|UNG_037|GIL_608|DAL_563|ULD_266|FP1_026|EX1_407|ICC_047",
             candidate_cards="GIL_513|TRL_074|ICC_047t2", next_test="批量锁定死亡集合，再测友方/敌方增益及 Reborn"),
        dict(issue_id="DEATH-002", mechanism="Reborn / Death processing", severity="confirmed",
             summary="ULD_266 在同批死亡的复现中产生两份 Reborn；应核对死亡处理与转生调用边界。",
             evidence="reports/card_quality_full_2026-09-27/foundation_probes.csv#DEATH-02",
             confirmed_cards="ULD_266", candidate_cards="其他 Reborn + Deathrattle 实体", next_test="最小化双重转生复现并记录实体 ID/zone"),
        dict(issue_id="DEATH-003", mechanism="Deathrattle registration", severity="confirmed",
             summary="4 个实体定义 deathrattle 脚本却缺 DEATHRATTLE 运行时标签；死亡后效果完全不触发。",
             evidence="reports/card_quality_full_2026-09-27/foundation_probes.csv#DEATH-03|DEATH-04|DEATH-05|DEATH-06; fireplace/card.py:790-813",
             confirmed_cards="YOD_016|VAN_EX1_029|UNG_999t2e|TB_PickYourFate_7_EnchMiniom2nd|UNG_999t2|TB_PickYourFate_7_2nd",
             candidate_cards="后续新增 deathrattle 脚本实体", next_test="为脚本注册路径建立标签/效果一致性检查"),
        dict(issue_id="DEATH-004", mechanism="Death event / selector zone", severity="confirmed",
             summary="Death 广播前先把死亡随从移入墓地，而 FRIENDLY_MINIONS/ENEMY_MINIONS 选择器要求目标仍在场；已逐卡证实 OG_302、GIL_819、ICC_900、BT_850 和三张 TROLL 卡漏触发。对照 EX1_595 用无区域限制的选择器正常触发。",
             evidence="fireplace/actions.py:345-374; fireplace/dsl/selector.py:532,549; reports/card_quality_full_2026-09-27/og_probe.csv#friendly_death_only_buffs_cthun_wherever; reports/card_quality_full_2026-09-27/og_death_selector_probe.csv#death_zone_GIL_819|death_zone_ICC_900|death_zone_control_EX1_595; reports/card_quality_full_2026-09-27/bt_probe_c.csv#BT_850::three_enemy_warders_die_then_awaken_and_clear_board; reports/card_quality_full_2026-09-27/set_probe_TROLL.csv#TRL_251|TRL_257|TRL_502",
             confirmed_cards="OG_302|GIL_819|ICC_900|BT_850|TRL_251|TRL_257|TRL_502", candidate_cards="其他 Death(FRIENDLY_MINIONS/ENEMY_MINIONS) 监听器",
             next_test="逐卡检查死亡事件在移区后的选择器匹配；对候选卡分别做友方/敌方死亡实测"),
        dict(issue_id="SPELL-001", mechanism="Draw / Discard", severity="confirmed",
             summary="BT_427 Feast of Souls 在正常牌局中本回合已有友方随从死亡时抛 KeyError。",
             evidence="fireplace/cards/initiate/demonhunter.py:125; reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_427",
             confirmed_cards="BT_427", candidate_cards="使用 NUM_MINIONS_KILLED_THIS_TURN 的其他法术", next_test="检查 Attr tag 初始化与聚合动作"),
        dict(issue_id="DRAW-001", mechanism="Draw / Discard / player state", severity="confirmed",
             summary="跨玩家 Draw 成功后把 cards_drawn_this_turn 记到 source.controller，实际抽牌的 target 玩家计数不变；OG_338 的额外抽牌发生在回合重置前，错误计数随即被清空。",
             evidence="fireplace/actions.py:1240; reports/card_quality_full_2026-09-27/cross_player_draw_probe.csv#DRAW-01; reports/card_quality_full_2026-09-27/hof_probe.csv#destroy_target_and_opponent_draws_two; reports/card_quality_full_2026-09-27/naxx_probe.csv#opponent_draw_and_counter; reports/card_quality_full_2026-09-27/og_probe.csv#opponent_turn_start_fifty_percent_extra_draw",
             confirmed_cards="EX1_050|EX1_161|FP1_029|OG_338", candidate_cards="GVG_032|DRG_077|DRG_084|其他 Draw(OPPONENT/ALL_PLAYERS) 实体",
             next_test="逐卡复现跨玩家抽牌场景并验证各玩家计数与触发器依赖"),
        dict(issue_id="DISCARD-001", mechanism="Discard / Quest trigger", severity="confirmed",
             summary="弃牌动作仅广播 ON 事件，而拉卡利献祭监听 Discard(...).after；实战连续弃掉六张手牌后任务进度仍为0。",
             evidence="fireplace/actions.py:1135-1151; fireplace/cards/ungoro/warlock.py:58-64; reports/card_quality_full_2026-09-27/three_set_probe.csv#UNG_829::quest_progresses_on_six_discards_and_reward_creates_portal",
             confirmed_cards="UNG_829", candidate_cards="其他监听 Discard(...).after 的任务或触发器",
             next_test="让 Discard 在完成移区及 discarded 标记后广播 AFTER，并验证任务进度、重复弃牌与奖励生成"),
        dict(issue_id="DISCARD-002", mechanism="Discard / card history selector", severity="confirmed",
             summary="弃牌被移至 REMOVEDFROMGAME，但该区域没有缓存到 game 实体迭代器；以 DISCARDED 选择器寻找历史弃牌会得到空集，残酷的恐龙术士亡语无法召回实测已弃掉的小精灵。",
             evidence="fireplace/actions.py:1135-1151; fireplace/card.py:209-232; fireplace/game.py:63-68; fireplace/cards/ungoro/warlock.py:25-29; reports/card_quality_full_2026-09-27/three_set_probe.csv#UNG_830::deathrattle_summons_only_discarded_minion_from_current_game; reports/card_quality_full_2026-09-27/troll_probe_a.csv#TRL_247",
             confirmed_cards="UNG_830|TRL_247", candidate_cards="ICC_841",
             next_test="为弃牌历史保留可枚举实体或专用记录，再逐卡验证弃牌召回和已弃牌数量效果"),
        dict(issue_id="TRIGGER-001", mechanism="Trigger / Spell resolution", severity="confirmed",
             summary="BT_753e 的 events 元组把 Destroy(SELF) 当作独立事件监听器；直接施放法力燃烧或经尤格-萨隆随机代施放后，后续广播抛 AttributeError: Destroy 无 at 属性。",
             evidence="fireplace/cards/initiate/demonhunter.py:166-171; fireplace/actions.py:148-150; reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_753; reports/card_quality_full_2026-09-27/og_probe.csv#two_prior_spells",
             confirmed_cards="BT_753|OG_134", candidate_cards="ULD_216|LOOT_106|其他可代施放法力燃烧的随机法术来源",
             next_test="核对事件动作组合与延迟销毁，并测试其他随机法术来源抽中法力燃烧后的传播范围"),
        dict(issue_id="TRIGGER-002", mechanism="Trigger / controller scope", severity="confirmed",
             summary="两个 Classic 触发器把事件的玩家范围写反：奥秘守护者遗漏对手奥秘，鱼人招潮者错误响应对手召唤的鱼人。",
             evidence="fireplace/cards/classic/neutral_rare.py:103,160; reports/card_quality_full_2026-09-27/classic_probe_first.csv#secretkeeper_gains_stats_when_either_player_plays_secret; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_509_friendly_murloc_summons_only",
             confirmed_cards="EX1_080|EX1_509", candidate_cards="其他依赖 OWN_/ALL_PLAYERS 事件范围的牌面触发器",
             next_test="逐张对照文案主语与事件监听的施法者/召唤者范围"),
        dict(issue_id="TARGET-001", mechanism="Targeting", severity="confirmed",
             summary="BT_801 Eye Beam 文本要求指定随从，但脚本无 target requirements；正常出牌空 TARGET 抛错。",
             evidence="fireplace/cards/initiate/demonhunter.py:177; reports/card_quality_full_2026-09-27/targeted_reproductions.csv#BT_801; AST direct-play TARGET/no-target-prereq=3 collectible candidates",
             confirmed_cards="BT_801", candidate_cards="BOT_243|TRL_409（两者 TARGET 为效果执行后的内部实体，应单独核对）", next_test="缺目标/合法目标分别测试；检查衍生与模式卡"),
        dict(issue_id="TARGET-002", mechanism="Targeting / Random effects / Hero Power", severity="confirmed",
             summary="NAX15_04 Chains 文案要求随机夺取敌方随从，脚本却使用 TARGET；无目标激活抛 AttributeError。",
             evidence="fireplace/cards/naxxramas/adventure.py:203; reports/card_quality_full_2026-09-27/foundation_probes.csv#TARGET-02",
             confirmed_cards="NAX15_04", candidate_cards="其他随机效果误用 TARGET 的模式英雄技能", next_test="检查其他模式英雄技能的随机目标与选择需求"),
        dict(issue_id="TARGET-003", mechanism="Targeting / Silence", severity="confirmed",
             summary="VAN_CS2_203 旧版猫头鹰自定义卡没有目标需求；无目标出牌使随从入场后抛 AttributeError，留下错误状态。",
             evidence="fireplace/cards/custom/patch_wog.py:73; reports/card_quality_full_2026-09-27/foundation_probes.csv#TARGET-03",
             confirmed_cards="VAN_CS2_203", candidate_cards="其他 runtime custom 目标卡", next_test="检查自定义卡与衍生卡的目标需求"),
        dict(issue_id="TARGET-004", mechanism="Targeting / Trigger / Transform", severity="confirmed",
             summary="BT_731 监听自身造成的所有伤害，没有把目标限制为随从；攻击英雄后把英雄变形为传染孢子。",
             evidence="fireplace/cards/outlands/neutral_rare.py:30; reports/card_quality_full_2026-09-27/infectious_sporeling_probe.csv#SPORE-01|SPORE-02",
             confirmed_cards="BT_731", candidate_cards="其他按 Damage(source=SELF) 监听但只应作用于特定目标类型的脚本",
             next_test="核查事件目标类型过滤，并分别验证攻击随从与英雄的正常回合流程"),
        dict(issue_id="TARGET-HERO-001", mechanism="Targeting / Hero protection", severity="confirmed",
             summary="is_valid_target 仅在目标为随从时检查 cant_be_targeted_by_abilities 和 cant_be_targeted_by_hero_powers；带有相同保护标记的英雄仍能出现在法术及英雄技能的合法目标中。",
             evidence="fireplace/targeting.py:42-55; fireplace/cards/kobolds/neutral_rare.py:71-81; reports/card_quality_full_2026-09-27/set_probe_LOOTAPALOOZA.csv#LOOT_382::protects_hero_from_spell_and_hero_power_targets; reports/card_quality_full_2026-09-27/dal_probe_a.csv#DAL_081",
             confirmed_cards="LOOT_382|DAL_081", candidate_cards="其他给英雄施加不能被法术或英雄技能指定标记的卡",
             next_test="逐卡实测英雄防指定效果生效期间的法术和英雄技能目标列表、实际施放及到期撤销"),
        dict(issue_id="ARMOR-ATTACK-001", mechanism="Attack restriction / Armor", severity="confirmed",
             summary="Ironwood Golem 与 Gemstudded Golem 的限制脚本均从 FRIENDLY_HAND 查询护甲；实战达到卡面护甲门槛且同场普通随从已可攻击时，两张本体仍被禁止攻击。",
             evidence="fireplace/cards/kobolds/druid.py:8-12; fireplace/cards/kobolds/warrior.py:16-21; reports/card_quality_full_2026-09-27/set_probe_LOOTAPALOOZA.csv#LOOT_048::armor_attack_threshold|LOOT_365::armor_threshold_and_regular_minion_control",
             confirmed_cards="LOOT_048|LOOT_365", candidate_cards="其他使用 ARMOR(FRIENDLY_HAND) 判定英雄护甲的卡",
             next_test="分别验证低于阈值、达到阈值及正常可攻击对照，检查护甲选择器的对象域"),
        dict(issue_id="SECRET-REVEAL-001", mechanism="Secret / reveal lifecycle", severity="confirmed",
             summary="LOOT_214 Evasion 受伤后给予本回合免疫，但脚本没有 Reveal；奥秘一直留在 SECRET 区，之后的对手回合再次受伤又重复触发。",
             evidence="fireplace/cards/kobolds/rogue.py:100-107; reports/card_quality_full_2026-09-27/set_probe_LOOTAPALOOZA.csv#LOOT_214::hero_damage_triggers_immunity_until_turn_end; reports/card_quality_full_2026-09-27/uld_probe_b.csv#ULD_239",
             confirmed_cards="LOOT_214|ULD_239", candidate_cards="其他 secret 监听器只执行效果而未 Reveal(SELF) 的卡",
             next_test="逐张检查奥秘首次触发后是否进入墓地，并验证后续回合不再触发"),
        dict(issue_id="DISCOVER-CAST-001", mechanism="Discover / effect-cast", severity="confirmed",
             summary="LOOT_506 符文之矛在英雄攻击后能打开三选一，但所选有目标法术 LOOT_064 与无目标法术 BT_101 均留在 SETASIDE，未实际施放；对应手动打出对照均能结算。",
             evidence="fireplace/cards/kobolds/shaman.py:156-162; fireplace/actions.py:1152-1204,1876-1931; reports/card_quality_full_2026-09-27/set_probe_LOOTAPALOOZA.csv#LOOT_506::hero_attack_casts_target_spell_with_available_target|LOOT_506::hero_attack_casts_nontarget_spell",
             confirmed_cards="LOOT_506", candidate_cards="UNG_088|其他 Discover(...).then(CastSpell(Discover.CARD)) 的实现",
             next_test="追踪 Discover.choose 回调传参和 CastSpell 目标解析，分别复测有目标和无目标法术及真正离开 SETASIDE 的区域变化"),
        dict(issue_id="CAST-TARGET-001", mechanism="Spell recast / targeting", severity="confirmed",
             summary="TRL_085 Zentimo 在 Play.ON 阶段对原法术实体 CastSpell 到相邻目标，覆盖其 target。月火术原选第二名5血随从，实测第一名受1伤、第二名未受伤、第三名受2伤；原目标被最后一次相邻施法替换。单目标无邻居时则正常受1伤。",
             evidence="fireplace/cards/troll/shaman.py:36-43; fireplace/actions.py:1876-1931; reports/card_quality_full_2026-09-27/set_probe_TROLL.csv#TRL_085::middle_target_and_two_neighbors|TRL_085::single_minion_only_once",
             confirmed_cards="TRL_085", candidate_cards="其他在 Play.ON 阶段对 Play.CARD 原实体再次调用 CastSpell 的卡",
             next_test="让相邻目标施法使用独立目标上下文，并在额外施法后恢复原始 Play.CARD.target；复测左右邻居与原目标各受一次"),
        dict(issue_id="MINION-EXTRA-001", mechanism="Battlecry / Combo multiplier", severity="confirmed",
             summary="TRL_092 Spirit of the Shark 的 Refresh 使用 MINION_EXTRA_BATTLECRIES 与 MINION_EXTRA_COMBOS；managers.py 将两标签拼写映射到 minio_extra_*，而 Battlecry 实际读取 player.minion_extra_*。实战机械增益战吼只触发一次，军情七处特工连击也只造成一次2伤。",
             evidence="fireplace/cards/troll/rogue.py:36-45; fireplace/managers.py:272-273; fireplace/actions.py:1044-1069; reports/card_quality_full_2026-09-27/set_probe_TROLL.csv#TRL_092::battlecry_and_combo_both_double",
             confirmed_cards="TRL_092", candidate_cards="其他使用 MINION_EXTRA_BATTLECRIES 或 MINION_EXTRA_COMBOS 标签的卡",
             next_test="修正标签到玩家属性的映射后，用普通战吼、连击、非随从施法与多重倍率组合分别复测"),
        dict(issue_id="GAMESTART-001", mechanism="GameStart / Hand and Deck trigger", severity="confirmed",
             summary="SCH_199 在 Hand 和 Deck 中把 GameStart.on(effect) 当作类方法调用，事件监听器的 trigger 错绑成 Switch；开局手牌和牌库中的转校生都不随面板变形。",
             evidence="fireplace/cards/scholomance/transfer_student.py:41-49; fireplace/actions.py:136-143,151-159; reports/card_quality_full_2026-09-27/set_probe_SCHOLOMANCE.csv#SCH_199::board_orgrimmar_opening_hand_and_deck|SCH_199::board_naxxramas_opening_hand_and_deck",
             confirmed_cards="SCH_199", candidate_cards="后续使用 GameStart 事件的手牌或牌库脚本",
             next_test="将事件监听器绑定为 GameStart 实例后，分别验证开局手牌与牌库在不同面板的形态及其效果"),
        dict(issue_id="HEALING-DOUBLE-001", mechanism="Healing multiplier / Lifesteal", severity="confirmed",
             summary="BOT_236 在场时 Holy Light 的 6 点治疗正确翻倍为 12 点，但本体造成 1 点伤害后的吸血仅恢复 1 点而非 2 点。通用 Heal 从随从来源调用 BaseEntity.get_heal，不读取玩家 healing_double；只有 Spell.get_heal 对其应用倍率。",
             evidence="fireplace/actions.py:964-970,1439-1455; fireplace/entity.py:103-104; fireplace/card.py:1321-1324; fireplace/player.py:325-333; reports/card_quality_full_2026-09-27/set_probe_BOOMSDAY.csv#BOT_236::spell_healing_doubles|BOT_236::lifesteal_healing_doubles",
             confirmed_cards="BOT_236", candidate_cards="治愈加倍效果在场期间通过随从吸血、随从治疗或武器治疗恢复生命的卡",
             next_test="对所有治疗来源统一应用 healing_double，分别复测法术、英雄技能、随从吸血和其他非技能来源"),
        dict(issue_id="SELF-COUNT-001", mechanism="Battlecry / self exclusion", severity="confirmed",
             summary="TRL_071 文本要求每有一个其他友方海盗获得 +1/+1，但战吼结算时 Count(FRIENDLY_MINIONS + PIRATE) 把已入场的本体也算入：零其他海盗时仍得 +1/+1，两名其他海盗时得 +3/+3。",
             evidence="fireplace/cards/troll/rogue.py:8-15; reports/card_quality_full_2026-09-27/set_probe_TROLL.csv#TRL_071::two_other_pirates_each_plus_one|TRL_071::no_other_pirates_no_buff",
             confirmed_cards="TRL_071", candidate_cards="其他战吼文本写有 other/其他、脚本使用 FRIENDLY_MINIONS 计数而未排除 SELF 的卡",
             next_test="抽查其他“其他友方随从”计数战吼，分别用零个和多个符合种族的随从验证本体是否被排除"),
        dict(issue_id="BOARD-001", mechanism="Secret / Summon / Dormant", severity="confirmed",
             summary="FULL_BOARD 与 Count(FRIENDLY_MINIONS) 忽略休眠随从占用的场位。ICC_200 在六个活动随从加一个休眠随从满场时消耗奥秘却未召出眼镜蛇；ICC_054 在五个活动随从加一个休眠随从、召出首只甲虫填满场后继续递归并抛 RecursionError。UNG_111 在休眠体占满第七格时扣光8颗水晶却没有召出树人。普通满场对照均未出现相同错误。",
             evidence="fireplace/cards/utils.py:48; fireplace/dsl/selector.py:532; reports/card_quality_full_2026-09-27/dormant_full_board_probe.csv#SECRET-BOARD-01; reports/card_quality_full_2026-09-27/classic_probe_first.csv#noble_sacrifice_full_board_with_dormant_minion_stays_set; reports/card_quality_full_2026-09-27/three_set_probe.csv#UNG_111::spell_on_dormant_full_board_matches_full_board_behavior; reports/card_quality_full_2026-09-27/icc_probe.csv#ICC_200::dormant_full_board_secret_stays; reports/card_quality_full_2026-09-27/icc_probe.csv#ICC_054::dormant_slot_recursion",
             confirmed_cards="EX1_136|EX1_130|UNG_111|ICC_200|ICC_054", candidate_cards="EX1_554|tt_010|GIL_577|AT_060|AT_002|TRL_400|BT_203|BT_003|BT_707",
             next_test="逐类检查 FULL_BOARD 与休眠实体同场时的保密状态、召唤槽位和区域移动"),
        dict(issue_id="DAMAGE-SURVIVE-001", mechanism="Damage trigger / death processing", severity="confirmed",
             summary="Rotface 与 Val'kyr Soulclaimer 都使用未带存活条件的 SELF_DAMAGE 监听；致死伤害后本体已进入墓地，仍分别召唤随机传说随从或食尸鬼。两个效果都要求本体受到伤害后存活。",
             evidence="fireplace/cards/icecrown/warrior.py:20-29; reports/card_quality_full_2026-09-27/icc_probe.csv#ICC_405::lethal_damage_no_legendary; reports/card_quality_full_2026-09-27/icc_probe.csv#ICC_408::lethal_damage_no_ghoul",
             confirmed_cards="ICC_405|ICC_408", candidate_cards="其他用 SELF_DAMAGE 监听且文本要求受伤后存活的卡",
             next_test="区分受伤事件与死亡处理后的存活条件，复测普通伤害、致死伤害和伤害触发治疗"),
        dict(issue_id="ADAPT-001", mechanism="Adapt / Choice / multi-target", severity="confirmed",
             summary="多目标 Adapt 应只进行一次选择，并将同一进化效果施加给所有符合条件的随从；当前逐目标覆盖 player.choice，选择完成后只有最后一个目标获得效果。温顺的巨壳龙、进化孢子和光耀之剑龙均复现。",
             evidence="fireplace/actions.py:2102-2143; fireplace/cards/ungoro/neutral_epic.py:29; fireplace/cards/ungoro/druid.py:54; fireplace/cards/ungoro/paladin.py; reports/card_quality_full_2026-09-27/three_set_probe.csv#UNG_089::one_adapt_choice_applies_to_all_friendly_murlocs_only|UNG_103::one_adapt_choice_applies_to_all_friendly_minions_only|UNG_962::one_adapt_choice_applies_to_all_recruits",
             confirmed_cards="UNG_089|UNG_103|UNG_962", candidate_cards="其他使用 Adapt(多目标选择器) 的卡",
             next_test="让一次 Adapt 选择的同一结果作用于全部合法目标，并复核满场、目标中途死亡与不同进化选项"),
        dict(issue_id="BOARD-002", mechanism="Summon / board capacity", severity="confirmed",
             summary="Summon 在将生成实体的 controller 改为目标玩家之前检查可召唤性；向对手召唤时可能越过其7格上限，或因己方满场阻止本应给对手的召唤。UNG_926 对手满7格时仍召出3只猛禽，敌场增至10只；LOOT_154、LOOT_357 与 LOOT_383 均在对手满场时召出第8只随从，己方满场时则未给对手召唤。",
             evidence="fireplace/actions.py:1676-1684; reports/card_quality_full_2026-09-27/hof_probe.csv#battlecry_on_full_enemy_board; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_577_normal_and_full_opponent_board; reports/card_quality_full_2026-09-27/naxx_probe.csv#replace_seven_on_full_boards; reports/card_quality_full_2026-09-27/three_set_probe.csv#UNG_926::opponent_full_board_does_not_overflow; reports/card_quality_full_2026-09-27/set_probe_LOOTAPALOOZA.csv#LOOT_154::friendly_full_board_opponent_room|LOOT_154::opponent_full_board_caps_summon|LOOT_357::friendly_full_board_opponent_has_room|LOOT_357::opponent_full_board_caps_chest|LOOT_383::opponent_full_board_respects_seven_minion_cap|LOOT_383::friendly_full_board_does_not_block_opponent_summon; control: reports/card_quality_full_2026-09-27/naxx_probe.csv#full_enemy_board_no_eighth_from_deck",
             confirmed_cards="EX1_116|EX1_577|FP1_019|UNG_926|LOOT_154|LOOT_357|LOOT_383", candidate_cards="其他使用 Summon(OPPONENT, 新建衍生实体) 且接近满场的效果",
             next_test="在控制者分配后检查目标玩家场位，再复测对手满场与双方满场分支"),
        dict(issue_id="BOARD-003", mechanism="Steal / board capacity", severity="confirmed",
             summary="Steal 没有检查目标控制者战场上限；精神控制技师作为第7个友方随从入场后仍夺取敌方随从，友方场上出现8个随从。",
             evidence="fireplace/actions.py:1813-1840; reports/card_quality_full_2026-09-27/hof_probe.csv#steal_when_battlecry_fills_own_board",
             confirmed_cards="EX1_085", candidate_cards="其他使用 Steal 的效果，尤其满场时夺取敌方随从",
             next_test="对所有夺取控制权效果检查己方满场、敌方满场与暂置区的区域变化"),
        dict(issue_id="BOUNCE-001", mechanism="Bounce / ownership", severity="confirmed",
             summary="Bounce 以当前 controller 手牌为回手目的地；当随从被偷取后，消失与劫持者将其交给当前控制者，违反卡面‘拥有者的手牌’。",
             evidence="fireplace/actions.py:769-782; reports/card_quality_full_2026-09-27/hof_probe.csv#stolen_minion_returns_original_owner; reports/card_quality_full_2026-09-27/classic_probe_final10.csv#combo_stolen_minion_returns_original_owner",
             confirmed_cards="NEW1_004|NEW1_005", candidate_cards="其他写明回到拥有者手牌且作用于控制权已变化随从的效果",
             next_test="追踪原始拥有者并复测偷取、回手与手牌满额的交叉分支"),
        dict(issue_id="CONTROL-001", mechanism="Destroy / Summon / controller", severity="confirmed",
             summary="复生将敌方目标消灭后用施法者的 CONTROLLER 召唤副本；对敌方随从施法会把复生体错误地放到己方战场。",
             evidence="fireplace/cards/naxxramas/collectible.py:176; reports/card_quality_full_2026-09-27/naxx_probe.csv#enemy_target_returns_to_original_owner",
             confirmed_cards="FP1_025", candidate_cards="其他对任意目标使用 Summon(CONTROLLER, Copy(TARGET)) 的效果",
             next_test="核查复活类法术的目标控制者，并覆盖友方与敌方目标、目标满场分支"),
        dict(issue_id="RANDOM-001", mechanism="Random card pool / class filter", severity="confirmed",
             summary="ANOTHER_CLASS 遍历 CardClass 时只排除当前职业，没有排除 NEUTRAL；窃取随机得到中立卡，违反‘其他职业’。",
             evidence="fireplace/dsl/selector.py:659-663; fireplace/cards/classic/rogue.py:236-240; reports/card_quality_full_2026-09-27/classic_probe_first.csv#pilfer_adds_only_collectible_cards_from_other_hero_classes",
             confirmed_cards="EX1_182", candidate_cards="其他使用 ANOTHER_CLASS 随机卡池的效果（需逐卡验证实际结果）",
             next_test="按职业候选池核对 NEUTRAL 与非法职业值，并复测所有 ANOTHER_CLASS 调用点"),
        dict(issue_id="TIME-001", mechanism="Player state / Continuous effect", severity="confirmed",
             summary="Nozdormu 对双方玩家声明 TIMEOUT=15 的 Refresh，但实际 Player.timeout 和序列化 timeout 均维持75，限时效果未进入可观察玩家状态。",
             evidence="fireplace/cards/classic/neutral_legendary.py:135-138; fireplace/player.py:84,127,152; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_560_timeout_state_for_both_players",
             confirmed_cards="EX1_560", candidate_cards="其他通过 Refresh 修改 Player 上独立属性而非卡牌 tag 的持续效果",
             next_test="核查 Player 属性与 aura slot 映射，并在支持计时的运行层验证15秒超时"),
        dict(issue_id="SPELLPOWER-001", mechanism="Spell Damage enchantment", severity="confirmed",
             summary="上古法师相邻随从获得 EX1_584e 附魔实体，但该附魔只有文字、没有 SPELLPOWER 数值或脚本；法术伤害未增加。",
             evidence="fireplace/cards/classic/neutral_rare.py:166-169; fireplace/cards/CardDefs.xml#EX1_584e; reports/card_quality_full_2026-09-27/classic_probe_middle_b.csv#battlecry_only_buffs_adjacent_minions_spell_damage",
             confirmed_cards="EX1_584", candidate_cards="其他只有法术伤害文字、缺 SPELLPOWER tag 或脚本的附魔",
             next_test="按附魔实体逐一比对法术伤害文字、数值 tag、运行时属性和实战伤害"),
        dict(issue_id="SILENCE-001", mechanism="Silence / Spell Damage", severity="confirmed",
             summary="Silence 清除随从的可沉默属性时未包括 spellpower；已沉默的玛里苟斯仍保留 +5 法术伤害，月火术继续造成6点伤害。",
             evidence="fireplace/actions.py:1643-1652; fireplace/card.py:1118,1122-1145; fireplace/player.py:196-201; reports/card_quality_full_2026-09-27/classic_probe_second.csv#EX1_563_spell_damage_and_silence",
             confirmed_cards="EX1_563|CS2_142|EX1_332", candidate_cards="其他拥有原生 SPELLPOWER 属性且可被沉默的随从；其他使用 Silence 的卡",
             next_test="核查沉默时 spellpower 与附魔法术伤害的清除方式，并复测原生和附魔两类来源"),
        dict(issue_id="CAST-001", mechanism="CastSpell / Trigger", severity="semantics_pending",
             summary="效果代施放法术会结算，但不广播玩家 Play ON/AFTER；与手牌施放触发不同，规则语义待核实，暂不判定为错误。",
             evidence="fireplace/actions.py:1876-1929; fireplace/events.py:8; reports/card_quality_full_2026-09-27/castspell_trigger_probe.csv#CAST-TRIGGER-01",
             confirmed_cards="", candidate_cards="EX1_559|NEW1_012|EX1_287|LOOT_414|" + "|".join(sorted(CAST_OBSERVER_CANDIDATES)),
             next_test="先以权威规则核对随从代施放与玩家施放的区别，再检查监听触发次数"),
        dict(issue_id="DISCOVER-001", mechanism="Discover / Choice", severity="confirmed",
             summary="无放回选卡辅助函数在候选池仅 1 张、请求 3 张时抛 IndexError；默认具体卡牌池尚未证实可达。",
             evidence="fireplace/utils.py:125-159; reports/card_quality_full_2026-09-27/discover_pool_probe.csv#DISCOVER-POOL-01",
             confirmed_cards="", candidate_cards="所有使用 weighted_card_choice 且过滤后候选池可能小于请求数的 Discover/随机选项效果",
             next_test="构造具体卡牌的小候选池场景；核查 0、1、2 张池与权重为 0 的分支"),
        dict(issue_id="STATS-001", mechanism="Conditional stats / Continuous effect", severity="confirmed",
             summary="9 张条件属性卡在计数变化后不符合文案；包括入场快照、错误目标计数、错误属性绑定及无实现。",
             evidence="reports/card_quality_full_2026-09-27/conditional_stats_probe.csv#STATS-01|STATS-02|STATS-03|STATS-04|STATS-05|STATS-07|STATS-08|STATS-09|STATS-10",
             confirmed_cards="DRG_058|DRG_088|TB_KTRAF_5|TB_BaconUps_036|ULDA_501|ICC_841|DALA_503|GILA_403|GILA_907",
             candidate_cards="其他 Conditional stats / Continuous effect 候选；EX1_062 已通过单独对照",
             next_test="逐张检查 Has +N 文案与手牌/场上/弃牌历史变化，并区分 Battlecry 快照效果"),
        dict(issue_id="MODE-001", mechanism="Mode ongoing effects", severity="confirmed",
             summary="3 张模式卡的法术重复或攻击光环缺少有效实现，实际游戏中完全不生效。",
             evidence="reports/card_quality_full_2026-09-27/mode_ongoing_probe.csv#MODE-01|MODE-02|MODE-03",
             confirmed_cards="DALA_504|TB_BaconUps_008|TB_BaconUps_038",
             candidate_cards="其他无脚本但有持续效果文案的模式卡",
             next_test="按模式 set 对无脚本持续效果卡做代表性运行筛查"),
        dict(issue_id="DATA-001", mechanism="Deathrattle metadata", severity="confirmed",
             summary="TB_TempleOutrun_Lazul_HP 带亡语 tag，但实体是 Hero Power；机制标签与实际效果不符。",
             evidence="reports/card_quality_2026-09-27/deathrattle_quality_map.csv#TB_TempleOutrun_Lazul_HP",
             confirmed_cards="TB_TempleOutrun_Lazul_HP", candidate_cards="其他非随从/武器上的亡语 tag", next_test="核对 XML tag 与实体类型"),
        dict(issue_id="DATA-002", mechanism="Hero Power modification", severity="confirmed",
             summary="YOD_008 文案要求英雄技能伤害 +2，但原始 HEROPOWER_DAMAGE=1；运行时实际只有 +1。",
             evidence="fireplace/cards/CardDefs.xml#YOD_008; reports/card_quality_full_2026-09-27/hero_power_reproductions.csv#YOD_008",
             confirmed_cards="YOD_008", candidate_cards="AT_003（同标签，已实测正确）", next_test="核对卡牌数据源和该标签作用域"),
        dict(issue_id="CLEAVE-001", mechanism="Attack / adjacent damage", severity="confirmed",
             summary="共用 CLEAVE 动作通过 TARGET_ADJACENT 读 source.target，而攻击实际设置 source.attack_target；相邻随从在实战中没有受到溅射伤害。",
             evidence="fireplace/cards/utils.py:44; fireplace/dsl/selector.py:311,346; fireplace/actions.py:244; reports/card_quality_full_2026-09-27/tgt_probe.csv#tgt_at_067_core_behavior; reports/card_quality_full_2026-09-27/gvg_probe.csv#GVG_113_attack_cleave_adjacent; reports/card_quality_full_2026-09-27/set_probe_LOOTAPALOOZA.csv#LOOT_078::cleave_adjacent_minions",
             confirmed_cards="AT_067|GVG_113|LOOT_078", candidate_cards="BRMC_88",
             next_test="逐张使用主目标及左右高生命随从复现，修正目标上下文后验证攻击重定向和相邻站位"),
        dict(issue_id="RANDOM-002", mechanism="Random effects / trigger", severity="confirmed",
             summary="火妖把每次应随机命中单个敌方角色的伤害写成 Hit(ENEMY_CHARACTERS,1)*2；两个敌方目标时触发总伤害由 2 错增到 4。",
             evidence="fireplace/cards/blackrock/collectible.py:11; reports/card_quality_full_2026-09-27/brm_probe.csv#random_split_enemy_only",
             confirmed_cards="BRM_002", candidate_cards="其他用全体选择器模拟随机分配伤害的脚本",
             next_test="检查每次伤害的随机抽样目标与多敌方目标时总伤害守恒"),
        dict(issue_id="READY-001", mechanism="Battlecry / targeting readiness", severity="confirmed",
             summary="雷德·黑手的 powered_up 只搜索敌方传说随从，但卡文与 target requirements 允许选择友方传说；仅有友方合法目标时错误显示未就绪。",
             evidence="fireplace/cards/blackrock/collectible.py:171-174; reports/card_quality_full_2026-09-27/brm_probe.csv#friendly_legend_only_readiness",
             confirmed_cards="BRM_029", candidate_cards="其他 powered_up 候选域与合法目标域不一致的条件战吼",
             next_test="对照每张条件战吼的 powered_up、requires_target、targets 和实际出牌结算"),
        dict(issue_id="ATTACK-001", mechanism="Inspire / attack permission", severity="confirmed",
             summary="银色警卫的 Inspire 附魔已施加但不能清除卡牌原生 cant_attack，下一次实际攻击仍被 InvalidAction 拒绝。",
             evidence="fireplace/cards/tgt/neutral_rare.py:48-54; reports/card_quality_full_2026-09-27/tgt_probe.csv#inspire_attack_permission",
             confirmed_cards="AT_109", candidate_cards="其他用 buff(cant_attack=False) 清除原生不能攻击的效果",
             next_test="修正权限合成后同时验证 Inspire 当回合可攻击和下回合效果失效"),
        dict(issue_id="FORGETFUL-001", mechanism="Attack / wrong-target event", severity="confirmed",
             summary="食人魔战槌把 FORGETFUL 事件挂在武器自身；共用事件监听 Attack(SELF)，但实际攻击者是英雄。128 次有其他合法敌方目标的武器攻击均未改打目标。",
             evidence="fireplace/cards/gvg/warrior.py:85-88; fireplace/cards/utils.py:132-134; reports/card_quality_full_2026-09-27/gvg_probe.csv#GVG_054_weapon_forgetful_combat",
             confirmed_cards="GVG_054", candidate_cards="其他将 Attack(SELF) 随机转向事件直接挂在武器上的卡",
             next_test="改为监听装备武器的英雄攻击，并验证目标域、50% 概率及耐久结算"),
        dict(issue_id="TARGET-RANDOM-001", mechanism="Targeting / random attack target", severity="confirmed",
             summary="随机目标标记在打牌及英雄技能目标选择中生效，Mayor Noggenfogger 的额外攻击事件只监听随从；英雄装备武器攻击时仍固定命中玩家指定目标。32 个独立种子均未改打场上另一个合法敌方目标。",
             evidence="fireplace/card.py:568-578,977-980,1682-1693; fireplace/cards/gangs/neutral_legendary.py:125-134; reports/card_quality_full_2026-09-27/three_set_probe.csv#CFM_670::hero_attack_can_redirect; https://hearthstone.blizzard.com/en-us/blog/21098848/",
             confirmed_cards="CFM_670", candidate_cards="其他使用 ALL_TARGETS_RANDOM 的角色或效果；当前卡牌脚本只发现 CFM_670",
             next_test="在英雄攻击入口应用同一随机目标逻辑，并复核有嘲讽、武器及奥秘打断时的目标合法性"),
        dict(issue_id="HEROPOWER-002", mechanism="Hero Power targeting modifier", severity="confirmed",
             summary="蒸汽朋克狙击手把 STEADY_SHOT_CAN_TARGET 刷新到玩家，但稳固射击的目标能力从英雄技能自身读取该标签；狙击手在场时仍不能选择随从。",
             evidence="fireplace/cards/gvg/hunter.py:36-39; fireplace/cards/skins/hunter.py:8-14; fireplace/cards/dragons/hunter.py:36-40; reports/card_quality_full_2026-09-27/gvg_probe.csv#GVG_087_hero_power_target_gate",
             confirmed_cards="GVG_087", candidate_cards="其他把英雄技能修饰标签施加到玩家而不是英雄技能实体的卡；DRG_253 为正确作用域对照",
             next_test="将目标能力施加到 FRIENDLY_HERO_POWER，验证法术目标集合、实际施放和离场恢复"),
        dict(issue_id="MANA-REMAINING-001", mechanism="Remaining Mana / selector", severity="confirmed",
             summary="奥丹姆的法力条件把 MANA 选择器用于未使用法力判断；实测花过法力仍推进发掘潜力任务并触发水晶商人抽牌。",
             evidence="fireplace/dsl/selector.py:135; reports/card_quality_full_2026-09-27/uld_probe_a.csv#ULD_131|ULD_133",
             confirmed_cards="ULD_131|ULD_133", candidate_cards="其他以 MANA 判断本回合未使用法力的脚本",
             next_test="区分总法力水晶与当前剩余法力，并复测花费后与未花费两种分支"),
        dict(issue_id="DRAW-AFTER-001", mechanism="Draw / AFTER trigger", severity="confirmed",
             summary="抽牌动作未广播 AFTER，奥丹姆任务在实际抽牌二十次后进度仍为零。",
             evidence="fireplace/actions.py:1208-1250; reports/card_quality_full_2026-09-27/uld_probe_a.csv#ULD_140",
             confirmed_cards="ULD_140", candidate_cards="其他监听 Draw(...).after 的任务和随从",
             next_test="抽牌移区后广播 AFTER 并核查疲劳、抽到即施放和跨玩家抽牌边界"),
        dict(issue_id="RANDOM-ENEMY-MINION-001", mechanism="Random targeting / enemy minion", severity="confirmed",
             summary="两张写明随机敌方随从的牌使用敌方角色池：雷诺在空敌场打英雄，巨魔蝙蝠骑士有敌随从时仍打英雄。",
             evidence="fireplace/cards/dragons/neutral_common.py:81-85; reports/card_quality_full_2026-09-27/uld_probe_b.csv#ULD_238; reports/card_quality_full_2026-09-27/drg_probe_a.csv#DRG_067",
             confirmed_cards="ULD_238|DRG_067", candidate_cards="其他文案是 enemy minion 但脚本使用 RANDOM_ENEMY_CHARACTER 的卡",
             next_test="静态对照卡文目标类型并以敌方英雄加一名随从的局面逐卡复测"),
        dict(issue_id="SUMMON-CONTEXT-001", mechanism="Summon / Battlecry context", severity="confirmed",
             summary="废墟之子在两次真实祈求后执行额外召唤路径抛 AttributeError，卡牌无法完成强化战吼。",
             evidence="fireplace/cards/dragons/warrior.py#DRG_019; reports/card_quality_full_2026-09-27/drg_probe_a.csv#DRG_019::two_real_invokes_summon_two_copies",
             confirmed_cards="DRG_019", candidate_cards="其他把 SELF 传给 SummonBothSides 的脚本",
             next_test="用真实祈求牌达到阈值，验证三个本体的阵营、数量、Rush 和出牌流程"),
        dict(issue_id="TEMP-BUFF-001", mechanism="Temporary buff / turn expiry", severity="confirmed",
             summary="灰舌杀手给予潜行随从的 +3 攻击与免疫在本回合结束后都未撤销，造成持续错误状态。",
             evidence="fireplace/cards/outlands/rogue.py:18-30; reports/card_quality_full_2026-09-27/bt_probe_c.csv#BT_702::stealthed_target_gains_three_attack_and_temporary_immune",
             confirmed_cards="BT_702", candidate_cards="其他以普通 Buff 实现文案含 this turn 的卡",
             next_test="核查临时附魔生命周期，并实测施放回合与下回合属性"),
        dict(issue_id="ENCHANT-ID-001", mechanism="Trigger / missing enchantment", severity="confirmed",
             summary="噬骨先锋受伤事件指向未定义的 BT_716e，两次受伤均不加攻击；树木援军的 DRG_311e 与精神分裂的 BT_253e 只有描述而无属性实现，目标未获得文本所写强化。",
             evidence="fireplace/cards/outlands/neutral_common.py:72-81; fireplace/cards/dragons/druid.py:68-85; fireplace/cards/outlands/priest.py:99-104; reports/card_quality_full_2026-09-27/bt_probe_c.csv#BT_716::two_damage_events_each_add_two_attack; reports/card_quality_full_2026-09-27/set_probe_DRAGONS.csv#DRG_311::choose_target_buff; reports/card_quality_full_2026-09-27/bt_probe_b.csv#BT_253::buffs_target_one_two_and_summons_buffed_copy",
             confirmed_cards="BT_716|DRG_311|BT_253", candidate_cards="其他事件引用不存在、拼错或仅有文字无属性的附魔 ID",
             next_test="建立脚本引用附魔 ID 的存在性校验，并复测连续受伤叠加"),
        dict(issue_id="BOMB-OWNER-001", mechanism="Deck owner / Battlecry", severity="confirmed",
             summary="爆破大师布姆按己方牌库而非敌方牌库的炸弹数召唤炸弹机器人；敌库有两枚炸弹仍召不出机器人。",
             evidence="fireplace/cards/dalaran/warrior.py#DAL_064; reports/card_quality_full_2026-09-27/dal_probe_a.csv#DAL_064::two_enemy_bombs_summon_four_bots",
             confirmed_cards="DAL_064", candidate_cards="其他从 ENEMY_DECK 文案误取 FRIENDLY_DECK 的脚本",
             next_test="两枚敌库炸弹及两枚己库炸弹交叉测试，核对机器人数量与阵营"),
        dict(issue_id="HEAL-AFTER-001", mechanism="Heal / AFTER trigger", severity="confirmed",
             summary="Heal 动作只广播 ON 而未广播 AFTER；激活方尖碑任务在三次治疗共恢复 15 点生命后进度仍是零。",
             evidence="fireplace/actions.py:1439-1455; fireplace/cards/uldum/priest.py:99-105; reports/card_quality_full_2026-09-27/uld_probe_d.csv#ULD_724::restore_fifteen_actual_health_unlocks_obelisk_eye",
             confirmed_cards="ULD_724", candidate_cards="其他监听 Heal(...).after 的任务与触发器",
             next_test="治疗量结算后广播 AFTER，复测治疗过量、治疗转伤害与任务奖励"),
        dict(issue_id="CLASS-FILTER-001", mechanism="Card-class selector / entity filter", severity="confirmed",
             summary="ANOTHER_CLASS 返回职业枚举，却被直接用于筛选手牌卡牌实体或 Give 事件中的卡牌；实战中盗贼手持法师牌时栅栏随从与宿怨条件均不触发，加入四张外职业卡后集市抢劫任务进度仍为零。",
             evidence="fireplace/dsl/selector.py:659-664; fireplace/cards/dalaran/rogue.py:32-41,126-139; fireplace/cards/uldum/rogue.py:69-76; reports/card_quality_full_2026-09-27/set_probe_DALARAN.csv#DAL_714::foreign_class_card_grants_plus_one_plus_one_and_rush|DAL_716::foreign_class_card_sets_vendetta_cost_to_zero; reports/card_quality_full_2026-09-27/set_probe_ULDUM.csv#ULD_326::four_other_class_cards_complete_quest_and_equip_blade",
             confirmed_cards="DAL_714|DAL_716|ULD_326", candidate_cards="其他把卡牌实体直接与 CardClass 枚举比较的事件或手牌筛选器",
             next_test="按实体 card_class 筛选，并分别验证外职业、本职业及中立牌条件"),
        dict(issue_id="BATTLECRY-EXTRA-001", mechanism="Battlecry / repeat modifier", severity="confirmed",
             summary="腐化水源在六次真实战吼后发放英雄技能；实际使用英雄技能后，下一个 +2 生命值战吼仍只结算一次。奖励附魔与玩家 extra_battlecries 的传递需要核查。",
             evidence="fireplace/cards/uldum/shaman.py:74-91; fireplace/actions.py:1021-1080; reports/card_quality_full_2026-09-27/set_probe_ULDUM.csv#ULD_291::six_battlecries_reward_doubles_next_battlecry",
             confirmed_cards="ULD_291", candidate_cards="其他施加 EXTRA_BATTLECRIES 标记的英雄技能或附魔",
             next_test="观察英雄技能使用前后 player.extra_battlecries，并以两个不同战吼核查本回合双次触发与回合结束失效"),
        dict(issue_id="QUEST-REENTRY-001", mechanism="Quest reward / reentrant progress", severity="confirmed",
             summary="净化道路在第三次有效突袭召唤后奖励的突袭狮鹫再次满足任务条件，任务进度从 2 递归增至 6，实测出现三只 4/4 狮鹫而非一只。AddProgress 在执行奖励后才将任务移至墓地。",
             evidence="fireplace/actions.py:2151-2169; fireplace/cards/dragons/hunter.py:70-77; reports/card_quality_full_2026-09-27/drg_probe_c.csv#DRG_251::three_rush_summons_reward_gryphon",
             confirmed_cards="DRG_251", candidate_cards="奖励动作自身会满足进度事件的其他任务；目前明显候选仅 DRG_251",
             next_test="先移出已完成任务再执行奖励，并验证第三次进度、奖励数、场位已满及多次任务同时存在"),
        dict(issue_id="LOWEST-COST-001", mechanism="Card selector / cost", severity="confirmed",
             summary="显眼的诱饵与冒险的召唤都写明按最低费用选牌，脚本却调用 LOWEST_ATK；手牌召唤和牌库抽取各用费用/攻击排序相反的牌实测选错。",
             evidence="fireplace/cards/uldum/neutral_epic.py:94-101; fireplace/cards/dalaran/paladin.py:83-92; reports/card_quality_full_2026-09-27/set_probe_ULDUM.csv#ULD_706::death_summons_lowest_cost_not_lowest_attack_from_each_hand; reports/card_quality_full_2026-09-27/set_probe_DALARAN.csv#DAL_727::draws_two_cost_watcher_instead_of_lower_attack_four_cost_warden",
             confirmed_cards="ULD_706|DAL_727", candidate_cards="其他文案写最低费用却调用 LOWEST_ATK 的脚本",
             next_test="以费用与攻击排序相反的候选牌复测双方手牌、己方牌库及费用并列分支"),
        dict(issue_id="SUMMON-CONTROLLER-001", mechanism="Summon / target controller", severity="confirmed",
             summary="疯狂召唤师先填满己方场面再尝试给对手召唤小鬼；Summon 在改写待召实体控制者之前检查其可召唤性，敌方空场和仅有六名随从两种局面均没有得到小鬼。",
             evidence="fireplace/actions.py:1673-1683; fireplace/cards/dalaran/neutral_rare.py:76-83; reports/card_quality_full_2026-09-27/set_probe_DALARAN.csv#DAL_751::battlecry_fills_each_board_to_seven_with_one_one_imps|DAL_751::empty_board_branch_fills_both_sides_to_seven",
             confirmed_cards="DAL_751", candidate_cards="其他在己方场满时调用 Summon(OPPONENT, ...) 的脚本",
             next_test="在目标控制者就位后再判断场位，验证双方各 0、6、7 个随从及复制召唤源"),
        dict(issue_id="WEAPON-DRAW-001", mechanism="Deck weapon draw / durability enchantment", severity="confirmed",
             summary="海盗藏品文本要求从牌库抽武器并加一耐久；脚本却从 FRIENDLY_HAND 选武器，附魔增加 Health。唯一武器在牌库的实测中，施放后仍留在牌库且耐久不变。",
             evidence="fireplace/cards/outlands/warrior.py:97-106; reports/card_quality_full_2026-09-27/bt_probe_a.csv#BT_124::draws_weapon_with_one_extra_durability",
             confirmed_cards="BT_124", candidate_cards="其他从牌库抽装备却筛选 FRIENDLY_HAND 的脚本；以 health 实现武器耐久的附魔",
             next_test="改用牌库武器筛选及耐久附魔，核对抽取区域、当前与最大耐久及无武器牌库分支"),
        dict(issue_id="SUMMON-COUNT-001", mechanism="Battlecry / summon count", severity="confirmed",
             summary="女猎手召唤战吼文本要求给对手召唤三只 1/1，脚本只有一次 Summon；实测敌方只得到一只。",
             evidence="fireplace/cards/outlands/neutral_common.py:33-37; reports/card_quality_full_2026-09-27/bt_probe_b.csv#BT_159::battlecry_summons_three_one_one_tokens_for_opponent",
             confirmed_cards="BT_159", candidate_cards="其他文本写明召唤多份而脚本仅调用一次 Summon 的战吼",
             next_test="逐卡核查数量常量与召唤动作重复次数，并覆盖空场与场位不足分支"),
        dict(issue_id="DRAWN-THIS-TURN-001", mechanism="Drawn-this-turn / battlecry branch", severity="confirmed",
             summary="凯尔丹的实体从牌库抽入手牌后 drawn_this_turn 与 powered_up 均为真，但打出时没有消灭场上其他随从；普通定向消灭分支可用。",
             evidence="fireplace/cards/outlands/warlock.py:8-17; reports/card_quality_full_2026-09-27/bt_probe_b.csv#BT_196::drawn_this_turn_battlecry_destroys_all_other_minions",
             confirmed_cards="BT_196", candidate_cards="其他依赖 DRAWN_THIS_TURN 动态条件且在 Play 中用布尔组合的牌",
             next_test="核查 powered_up 与 play 条件计算时机，分别验证手持、当回合抽入与复制生成的分支"),
        dict(issue_id="SPELLPOWER-TIMING-001", mechanism="Spell Damage / Play trigger timing", severity="confirmed",
             summary="星界使者给下一张法术的 +2 法伤附魔在该法术 Play.ON 时即销毁，月火术实际只造成 1 点而非 3 点，之后法伤才归零。",
             evidence="fireplace/cards/boomsday/mage.py:22-31; reports/card_quality_full_2026-09-27/set_probe_BOOMSDAY.csv#BOT_531::spell_damage_two_applies_only_to_next_spell",
             confirmed_cards="BOT_531", candidate_cards="其他在 Play.ON 移除下一张法术临时增益的附魔",
             next_test="在首个法术完成伤害结算后再移除附魔，复测伤害、第二法术与回合结束"),
        dict(issue_id="RANDOM-SELF-001", mechanism="Random target / self exclusion", severity="confirmed",
             summary="松散标本使用 RANDOM_FRIENDLY_MINION，没有排除自身；单个其他友军在场时 6 点伤害分配为标本自身 4 点、友军 2 点。",
             evidence="fireplace/cards/boomsday/neutral_epic.py:71-75; reports/card_quality_full_2026-09-27/set_probe_BOOMSDAY.csv#BOT_544::six_damage_randomly_split_among_other_friendly_minions",
             confirmed_cards="BOT_544", candidate_cards="其他文案含 other friendly minions 却使用 RANDOM_FRIENDLY_MINION 的脚本",
             next_test="候选池排除 SELF，并以唯一其他友军及复数友军局面验证总伤害守恒"),
        dict(issue_id="RANDOM-ENEMY-CHARACTER-001", mechanism="Random target / enemy characters", severity="confirmed",
             summary="腐蚀吐息要求随机敌方角色，脚本却固定 Hit(ENEMY_HERO,5)；带一名敌方随从时 24 个独立种子仍只打英雄。",
             evidence="fireplace/cards/dragons/hunter.py:49-53; reports/card_quality_full_2026-09-27/set_probe_DRAGONS.csv#DRG_256::trigger_random_enemy_after_hero_power",
             confirmed_cards="DRG_256", candidate_cards="其他文案为随机敌方角色却写固定 ENEMY_HERO 的卡",
             next_test="敌方英雄加随从时跨种子验证候选池与伤害总量"),
        dict(issue_id="COST-SET-001", mechanism="Cost modification / set versus add", severity="confirmed",
             summary="盗贼迦拉克隆写明抽到的牌费用变为 1；脚本附魔用 COST:1，被费用合成当作加 1。实测 4 费冰风雪人变为 5 费，未升级、两次祈求、四次祈求三个阶段均复现。",
             evidence="fireplace/cards/dragons/rogue.py:112-149; reports/card_quality_full_2026-09-27/set_probe_DRAGONS.csv#DRG_610::uninvoked_hero_draws_one_card_set_to_one_cost|DRG_610::two_real_invokes_draw_two_at_one_cost|DRG_610::four_real_invokes_draw_four_at_one_cost_and_claw",
             confirmed_cards="DRG_610", candidate_cards="其他用 GameTag.COST 数值表示费用置为固定值的附魔",
             next_test="将固定费用语义改为 SET(1)，复测原价 0、4、10 及两级升级战吼"),
        dict(issue_id="GIVE-COUNT-001", mechanism="Give / card quantity", severity="confirmed",
             summary="聪明的伪装文案给两张外职业法术，实际仅给一张；光铸远征军文案给五张圣骑士牌，空中立牌库时实测仅给一张。两者脚本都只调用一次 Give。",
             evidence="fireplace/cards/uldum/rogue.py:90-94; fireplace/cards/dragons/paladin.py:34-42; reports/card_quality_full_2026-09-27/set_probe_ULDUM.csv#ULD_328::adds_two_random_spells_from_other_class; reports/card_quality_full_2026-09-27/set_probe_DRAGONS.csv#DRG_231::neutral_free_deck_generates_five_paladin_cards",
             confirmed_cards="ULD_328|DRG_231", candidate_cards="其他文案要求多个生成卡但脚本只有一次 Give 的实现",
             next_test="按数量重复生成并验证手牌上限、各卡来源职业和条件反支"),
        dict(issue_id="TARGET-REQ-DRAGON-001", mechanism="Targeting / conditional requirement", severity="confirmed",
             summary="闪电吐息把选随从目标的要求限定在持龙条件，导致无龙分支打出后 TARGET 为空，基础 4 点伤害未发生；持龙分支的伤害已实测正常。",
             evidence="fireplace/cards/dragons/shaman.py:97-106; reports/card_quality_full_2026-09-27/set_probe_DRAGONS.csv#DRG_219::without_dragon_only_target_takes_damage|DRG_219::holding_dragon_damages_target_and_adjacent_minions",
             confirmed_cards="DRG_219", candidate_cards="其他把无条件目标要求写成条件目标要求的卡",
             next_test="分别在有龙和无龙时检查可选目标集合、实际目标传递及基础伤害"),
    ]
    # Publish only playable collectible cards. Noncollectible entities remain
    # available to the internal audit and mechanism-issue evidence, but do not
    # appear in the user-facing card lists or set-level quality counts.
    collectible_master = [row for row in master if row["scope"] == "ordinary_collectible"]
    collectible_quality = [row for row in quality if row["scope"] == "ordinary_collectible"]
    collectible_mechanisms = [row for row in mechanisms if row["scope"] == "ordinary_collectible"]
    common = ["version", "set", "card_id", "name_en", "name_zh", "mechanic", "status", "implementation", "tested", "reason", "evidence", "notes"]
    write_csv(OUT / "card_master.csv", collectible_master, ["version", "set", "card_id", "dbf_id", "name_en", "name_zh", "card_type", "scope", "origin", "collectible", "implementation", "python_source", "card_text_en", "card_text_zh", "mechanics", "raw_xml_tags", "runtime_tags", "requirements", "test_refs_candidate", "xml_source"])
    write_csv(OUT / "card_quality.csv", collectible_quality, common + ["scope", "card_type", "collectible", "python_source", "card_text_en"])
    write_csv(OUT / "basic_quality.csv", [row for row in collectible_quality if row["set"].endswith("(BASIC)")],
              common + ["scope", "card_type", "collectible", "python_source", "card_text_en"])
    write_csv(OUT / "red_cards.csv", [row for row in collectible_quality if row["status"] == "RED"],
              common + ["scope", "card_type", "collectible", "python_source", "card_text_en"])
    write_csv(OUT / "card_mechanism.csv", collectible_mechanisms, common + ["scope", "card_type", "collectible", "python_source", "card_text_en", "label_basis"])
    write_csv(OUT / "mechanism_issues.csv", issues, ["issue_id", "mechanism", "severity", "summary", "evidence", "confirmed_cards", "candidate_cards", "next_test"])
    write_csv(OUT / "runtime_smoke.csv", smoke_rows, ["version", "set", "card_id", "name_en", "name_zh", "card_type", "scope", "collectible", "outcome", "stage", "exception", "playable", "target_count", "choose_count", "choice_resolved", "card_zone_after", "friendly_field_after", "enemy_field_after", "friendly_hand_after"])
    write_csv(OUT / "targeting_static_audit.csv", target_rows, ["card_id", "name_en", "set", "source", "verdict", "evidence"])
    by_mechanism = defaultdict(list)
    for row in collectible_mechanisms:
        by_mechanism[row["mechanic"]].append(row)
    queue = []
    for label, entries in by_mechanism.items():
        statuses = Counter(row["status"] for row in entries)
        collectible = [row for row in entries if row["scope"] == "ordinary_collectible"]
        state = ("ordinary_collectible_verified" if label in {"Overload", "Hero Power modification"} else
                 "specialty_audit_partial" if label == "Deathrattle" else
                 "foundation_audit_partial" if label in {"Targeting", "Reborn", "Random effects"} else
                 "sampled_runtime_audit_partial" if any(row["tested"] == "yes" for row in entries) else
                 "inventory_only_or_partial")
        queue.append(dict(phase=PHASE.get(label, 5), mechanism=label,
                          candidate_entities=len(entries), ordinary_collectible=len(collectible),
                          green=statuses["GREEN"], yellow=statuses["YELLOW"], red=statuses["RED"],
                          review_state=state,
                          next_action=("验证同一张卡的其他机制" if state == "ordinary_collectible_verified" else
                                       "扩展已确认问题到跨版本边界场景" if state in {"specialty_audit_partial", "foundation_audit_partial"} else
                                       "逐 set 读取现有断言并运行机制专属正例/边界复现")))
    for label in ("Death processing", "Zone movement"):
        queue.append(dict(phase=1, mechanism=label, candidate_entities=0, ordinary_collectible=0,
                          green=0, yellow=0, red=0, review_state="foundation_audit_partial",
                          next_action="跨卡/跨机制底层路径；详见 foundation_probes.csv 与 mechanism_issues.csv"))
    queue.sort(key=lambda row: (row["phase"], -row["ordinary_collectible"], row["mechanism"]))
    write_csv(OUT / "mechanism_queue.csv", queue, ["phase", "mechanism", "candidate_entities", "ordinary_collectible", "green", "yellow", "red", "review_state", "next_action"])
    enriched = []
    by_set_quality = defaultdict(list)
    for row in collectible_quality:
        by_set_quality[row["set"]].append(row)
    set_fields = ["version", "set", "ordinary_collectible", "python_definition_ordinary_collectible",
                  "battlecry_collectible", "discover_collectible", "choose_one_collectible",
                  "secret_collectible", "combo_collectible", "overload_collectible", "weapon_collectible",
                  "quality_green", "quality_yellow", "quality_red"]
    for r in inv:
        cards = by_set_quality[r["set"]]
        if not cards:
            continue
        states = Counter(row["status"] for row in cards)
        enriched.append({**r, "ordinary_collectible": len(cards),
                         "quality_green": states["GREEN"], "quality_yellow": states["YELLOW"],
                         "quality_red": states["RED"]})
    write_csv(OUT / "set_inventory.csv", enriched, set_fields)
    write_csv(OUT / "code_snapshot.csv", [{"version": VERSION, "source_sha256": digest,
                                           "source_files": source_count,
                                           "source_latest_mtime_ns": source_latest_mtime_ns,
                                           "built_at_utc": datetime.now(timezone.utc).isoformat()}],
              ["version", "source_sha256", "source_files", "source_latest_mtime_ns", "built_at_utc"])
    print("collectible master", len(collectible_master), "quality", len(collectible_quality),
          "mechanisms", len(collectible_mechanisms), "smoke", len(smoke_rows))
    print("quality statuses", dict(Counter(r["status"] for r in collectible_quality)))
    print("mechanism counts", Counter(r["mechanic"] for r in collectible_mechanisms).most_common())


if __name__ == "__main__":
    main()
