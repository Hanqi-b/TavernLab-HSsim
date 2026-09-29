# 卡牌质量地图：现行重测与历史摸排

## 2026-09-29 当前代码重测

修复前 CSV 已存入 `known_issues_archive_2026-09-29/`，并通过其中的 `SHA256SUMS` 校验；归档中的卡牌颜色和原始失败证据未改。本次仅更新项目现行质量表。四项已知公共问题覆盖的 **30 张可构筑可收藏卡**均按卡面效果重新执行逐卡行为测试；随后单独修正 `TRL_257` 的伤害目标。结论为 **30 GREEN / 0 YELLOW / 0 RED**。另经用户确认，`DS1_184` 追踪术选择牌置入手牌不触发普通抽牌；正常抽牌与追踪术的克洛玛古斯对照测试通过，故从 YELLOW 改为 GREEN。随后修复 Basic 的四张 RED 卡 `BT_142`、`BT_323`、`CS2_142`、`EX1_194`，并因共用的沉默逻辑修复而逐卡复测 Classic 的 `EX1_332` 与 `EX1_563`。这六张现行评级均为 GREEN。当前完整质量表共 **2,497 张：GREEN 2,311 / YELLOW 8 / RED 178**。

逐卡结论与 pytest nodeid 见 `remediation_verdicts_2026-09-29.csv`、`tracking_rule_verdict_2026-09-29.csv` 和 `basic_red_fix_verdicts_2026-09-29.csv`，当前整卡评级见 `card_quality.csv`，当前 RED 清单见 `red_cards.csv`，当前机制问题见 `mechanism_issues.csv`。`BT_323` 的复测还发现 `PutOnTop` 原先会覆盖另一张牌库实体；修正后逐实体核对牌库并实际抽出所选牌。`CS2_142` 的沉默修正还需保证精确复制不重复计算法强增益，已补相应用例。完整测试集 **1,129 passed**。`SILENCE-001` 连同 `DEATH-001`、`DEATH-002`、`DEATH-004`、`BOARD-001`、`BOARD-002` 标为已逐卡重测解决。旧 probe、verdict、baseline 和 `code_snapshot.csv` 保持修复前历史含义；旧 `verify_report.py` 含修复前源码哈希和固定 RED 断言，不用它校验当前表。现行重测可运行 `write_remediation_verdicts.py`、`apply_remediation_results.py`、`apply_tracking_rule_verdict.py`、`apply_basic_red_fix_verdicts.py` 和 `verify_remediation_results.py`；更新脚本会先重跑列出的逐卡用例并核验归档。

以下内容记录先前摸排阶段的状态和过程。涉及当时的数量、颜色或旧测试输出时，以本节及现行 CSV 为准。

## 历史摸排记录（2026-09-28）

## 口径与本轮完成范围

数据锁定在项目自带的 `CardDefs.xml`，build **17.6.0.53261**。`version` 记录这个项目快照；`set` 记录卡牌所属扩展包。交付用的卡牌表仅包含 **可构筑的可收藏卡**：要求 `collectible=yes` 且 `scope=ordinary_collectible`，排除 Hero Skins、衍生卡、模式卡、英雄技能、辅助实体，以及虽然 XML 标成可收藏、但项目组牌规则明确禁止入卡组的 `HERO_01..10` 初始英雄身份。不能把这个快照当作当前炉石全量卡池，尤其 Scholomance Academy 在此 XML 中只有 1 张普通可收集实体。

- 数据源内部含 XML 实体 **9,344** 和运行时实体 **36**；这些非可收藏实体不进入交付用卡牌表。
- 卡牌主表、质量表和通用烟测均为 **2,497** 张可构筑可收藏卡，分属 **24** 个有可收藏卡的 set。
- 机制明细 **5,024** 行；一个可收藏卡可以有多个机制标签，候选标签不能等同于效果存在或正确。
- 整卡评级：**GREEN 736 / YELLOW 1,703 / RED 58**。评级取该卡所有已识别机制中的最差级别；本轮新增 GVG、BRM、TGT、LOE 的原始 YELLOW 逐卡行为证据。
- 可收藏卡的亡语机制行 **234** 条：GREEN 41 / YELLOW 184 / RED 9。先前覆盖 412 个各类实体的亡语专项原始证据仍保留在上一轮报告，但非可收藏实体不进入本表。

当前的 YELLOW 主要表示仍欠逐卡核心效果断言，**不是已确认错误**。`implementation` 只反映脚本或引擎原生标签的实现线索；存在 Python 类绝不产生 GREEN。`tested=partial` 可以是普通出牌烟测或测试文件中的卡号引用，也绝不单独产生 GREEN。

白板与描述效果未归类的卡已分开：`Vanilla` 仅含 32 张无描述效果、无逐卡脚本的可构筑随从，均经专项运行验证为 GREEN；`Unclassified effect` 含 26 张有描述效果但尚未归入现有机制的卡，仍需效果验证。Basic 的 9 张白板包含在这 32 张中；本次补验后其他 23 张从 YELLOW 升为 GREEN。

## 文件

| 文件 | 用途 |
|---|---|
| `card_master.csv` | 2,497 张可构筑可收藏卡的 XML/运行时标签、源码位置和测试引用候选。 |
| `set_inventory.csv` | 24 个有普通可收藏卡的 set 的数量和评级数。 |
| `set_sweep.csv`、`set_mechanism_matrix.csv` | 24 个 set 的逐包对账、烟测汇总及扩展包×机制分布。 |
| `card_quality.csv` | 2,497 张可构筑可收藏卡的整卡评级；包含用户要求的 12 个基本列。 |
| `basic_quality.csv` | 首个逐包复查结果：Basic 的 143 张可构筑卡及逐卡评级证据。 |
| `card_mechanism.csv` | 可收藏卡逐机制评级、标签来源与证据，共 5,024 行。 |
| `red_cards.csv` | 58 张确认 RED 的可构筑可收藏卡。 |
| `mechanism_issues.csv` | 31 条已确认机制/共性问题、1 条待核实规则语义，均列证据与受影响候选。 |
| `expansion_yellow_baseline.csv` | 本轮固定的 291 张原始 YELLOW 可收藏卡，避免在报告重建后改变待测范围。 |
| `expansion_yellow_quality.csv`、`classic_yellow_quality.csv`、`hof_yellow_quality.csv`、`naxx_yellow_quality.csv` | 291 张原黄卡及三包分表的最终逐卡评级、理由和 testcase 证据。 |
| `four_set_yellow_baseline.csv`、`four_set_yellow_quality.csv` | 固定并导出 GVG、BRM、TGT、LOE 的 315 张原始 YELLOW 可收藏卡。 |
| `gvg_yellow_quality.csv`、`brm_yellow_quality.csv`、`tgt_yellow_quality.csv`、`loe_yellow_quality.csv` | 四包分表；含中英文文案、整卡评级、具体理由及逐 case 证据。 |
| `gvg_probe.csv`、`brm_probe.csv`、`tgt_probe.csv`、`loe_probe.csv` 与对应脚本和 `*verdict.csv` | 四包 395 条本轮定向行为 case 和 59 条辅助既有测试记录。 |
| `classic_probe_*.csv`、`hof_probe.csv`、`naxx_probe.csv` 与对应 `*verdict*.csv` | 逐卡实际对局断言和判定，共 422 条行为 case。 |
| `mechanism_queue.csv` | 每种机制的候选数、评级分布、排查阶段与下一动作。 |
| `runtime_smoke.csv` | 2,497 张可构筑可收藏卡的通用真实游戏出牌烟测，不能用于直接判 GREEN。 |
| `collectible_play_smoke.json` | 原始烟测快照共 2,507 个 XML `collectible` 实体；报告生成时排除其中 10 个初始英雄身份。 |
| `targeted_reproductions.csv`、`hero_power_reproductions.csv` | 正常牌局中的定点复现和对照。 |
| `overload_reproductions.csv` | 35 张普通可收集过载卡的出牌后与下一回合状态断言。 |
| `targeting_static_audit.csv` | `play/activate/combo` 直接使用 `TARGET`、但没有通用目标前置条件的 3 张可收藏卡静态候选。 |
| `foundation_probes.csv` | 第二步底层状态最小复现：死亡批次、区域移动、目标、选择和随机选取。 |
| `targeting_prereq_sweep.csv` | 425 张有目标前置条件的普通可收集卡的缺目标与非法自身目标横向检查。 |
| `later_stage_probes.csv` | 主动效果、交互效果、装备和关键词的 24 条代表性效果断言。 |
| `cross_player_draw_probe.csv`、`dormant_full_board_probe.csv`、`discover_pool_probe.csv` | 跨玩家抽牌计数、休眠占场位、Discover 小池的机制级最小复现。 |
| `conditional_stats_probe.csv` | 10 张条件属性卡的逐卡状态变化复现，9 张失败、1 张通过。 |
| `mode_ongoing_probe.csv` | 3 张模式持续效果卡的实际对局复现，均确认效果不生效。 |
| `infectious_sporeling_probe.csv` | `BT_731` 传染孢子正常回合攻击随从与英雄的对照：随从变形通过，英雄被错误变形。 |
| `basic_runtime_probe.csv` | Basic 包 61 条逐卡运行断言，涵盖入场属性/费用/种族选择器、原生关键词、武器、战吼、光环和法术。 |
| `vanilla_runtime_probe.csv` | 全部 32 张可构筑无效果白板随从的入场、费用、属性、种族与种族选择器验证。 |
| `basic_existing_tests.csv` | Basic 包 18 张卡的既有测试断言复核与重跑；14 张达到独立升绿候选标准，4 张只算部分验证。 |
| `basic_card_verdicts.csv`、`basic_card_probe_a.csv` 至 `basic_card_probe_k.csv` | 原始 83 张 Basic YELLOW 的逐卡判定与独立行为 testcase；每条 verdict 汇总该卡全部相关机制标签和 probe case。 |
| `basic_corruption_probe.csv`、`basic_power_infusion_probe.csv` | Basic 包延迟触发正例与能量灌注数值错误复现。 |
| `castspell_trigger_probe.csv` | 随从代施放与玩家打出法术的 3 条差异观察；规则语义未证实，均为 inconclusive。 |
| `code_snapshot.csv` | 本次生成时卡牌 XML 与规则源码的 SHA-256；验证脚本校验源文件与证据时序。 |

`test_refs_candidate` 只是 AST 中的卡号引用，可能仅是测试布置、元数据或输出；必须读断言才能认作效果验证。`label_basis` 分开记录 `xml_tag`、`runtime_tag`、`target_requirement`、`python_source` 和 `card_text`。`raw_xml_tags` 与 `runtime_tags` 分列，避免把脚本合并后产生的标签误当成原始 XML。

## 已完成验证与发现

测试命令：

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=tests:. venv/bin/python -m pytest -q tests --disable-warnings
```

本轮完整测试重跑 **1,049 passed**。先前一次全套运行曾有随机测试 `tests/test_tgt.py::test_effigy` 失败，单独重跑通过；它抽到休眠随从时会暴露 `FULL_BOARD` 不计休眠占槽的已复现问题。完整测试通过不能代替逐卡效果证据。测试引用候选涉及 912 个 XML ID，只有实际断言核心效果的用例才可作为卡牌评级证据。

可构筑可收藏卡通用烟测：**2,456 played / 36 在统一场景不可出牌 / 5 异常**。正常牌库对照后，`UNG_035` 与 `DAL_059` 的异常只发生在空牌库烟测布置中；`BT_427`、`BT_753`、`BT_801` 在正常牌局继续抛错。`BT_801` 文案要求指定随从，而运行时 `targets=0`。直接 `TARGET` 且缺目标 prerequisite 的可收藏卡静态候选仅 3 张；另外两张 `BOT_243`、`TRL_409` 的 `TARGET` 用于效果内部所选实体，尚不能判错。

英雄技能伤害标签专项：仅 `AT_003` 与 `YOD_008` 两张普通可收集卡带 `HEROPOWER_DAMAGE`。同一套 Mage Fireblast 复现中，前者造成 2 点伤害，符合额外 +1；后者也只造成 2 点，但文案要求额外 +2、应造成 3 点。XML 中 `YOD_008` 的标签值为 1，已记 RED。

过载专项：35 张普通可收集 Overload 卡全部在独立正常牌局中通过：实际出牌后的 `overloaded`、下一己方回合的 `overload_locked`、`overloaded` 清零和可用法力均与卡牌标签数值一致，因此这 **35 条 Overload 机制行**为 GREEN；这些卡的其他机制不随过载通过而升级。

亡语机制级错误仍是首要底层风险：同一批死亡实体逐个进入 `Death.do()` 时先触发前者亡语，再重新判断后者的 `dead`，增益亡语可救回本已致死的随从。`ULD_266` 在相关场景还出现两份 Reborn。具体复现与可能受影响卡见 `mechanism_issues.csv` 和上一轮亡语专项 CSV。

第二步底层状态检查：针对现有死亡、目标、选择、随机测试运行了 **27 项，全部通过**；另有 16 条最小复现，其中 8 条是区域移动、目标拒绝、Discover 选择和随机选择的通过对照，8 条复现了错误。区域对照覆盖出牌、死亡、变形、回手、武器替换与奥秘入场；这些对照不能替代所有卡的 zone 验证。425 张有目标前置条件的普通可收集卡中，342 张在缺目标及非法自身目标下被正确拒绝且未付费/移区；11 张首先要求 Choose One 选项，72 张在统一场景中条件不成立，仍需后续场景验证。

第二步新增确认：`NAX15_04` 的随机夺取英雄技能在无目标时抛错；运行时自定义 `VAN_CS2_203` 无目标出牌后抛错，随从已经进入战场。另有 **4 个**实体有 `deathrattle` 脚本却没有有效亡语标签，死亡时效果不触发：`YOD_016`、`VAN_EX1_029`、`UNG_999t2e`、`TB_PickYourFate_7_EnchMiniom2nd`。后两种附魔的来源法术 `UNG_999t2` 和 `TB_PickYourFate_7_2nd` 也因承诺效果未发生而列为 RED。基础随机选择器的空池、固定种子与无放回抽样对照通过；额外检查发现请求 3 张但合格池仅 1 张时抛 `IndexError`，尚未找到默认卡必然遇到这个边界，故只列机制级风险。

后续阶段新增 **24 条代表性效果探针均通过**，覆盖战吼、法术结算、召唤格位、抽弃牌、沉默、Choose One 双分支、触发、光环、奥秘、减费、武器耐久、英雄技能、连击、Rush、吸血、剧毒、转生、流放及 Spell Damage。它们只支持对应卡和场景的 GREEN；其他同机制卡继续 YELLOW。

新确认的共享问题：`EX1_050` 让双方各抽 2 张，但 `cards_drawn_this_turn` 错把 4 张全记到卡主；`EX1_136` 在休眠随从占满第七格时被错误揭示消耗；`FULL_BOARD` 还有 12 张其他静态使用卡待验证。`conditional_stats_probe.csv` 的 10 张条件属性卡中 **9 张 RED / 1 张通过**；另外 3 张模式持续效果卡在实际游戏中完全不生效。详见 `mechanism_issues.csv` 与逐卡证据。XML 原生的“不可被法术或英雄技能指定”以及全种族标签已按引擎实现记录，但缺少效果断言的卡仍为 YELLOW。

用户指出的可收藏卡 `BT_731` 传染孢子经正常回合攻击复现：攻击敌方随从能正确把随从变形；攻击敌方英雄也触发 `Morph`，把英雄移到 `SETASIDE` 并在敌方场上生成传染孢子。脚本的 `Damage(source=SELF)` 监听没有限定目标必须为随从，已将此卡从 YELLOW 改为 RED，并在 `TARGET-004` 记录目标类型过滤问题。

`CastSpell` 代施放与玩家手牌出牌走不同事件路径，3 条探针记录了差异。由于“由随从施放”是否应算“玩家施放”涉及炉石规则语义，`CAST-001` 标为 `semantics_pending`，没有仅凭这一差异升级 RED。

## 逐扩展包复查：Basic

Basic 中排除 `HERO_01..10` 初始英雄身份后有 **143 张**可构筑卡。此前逐张对照卡牌描述与脚本，检查既有测试中的实际断言，并执行 **61 条 Basic 专项运行探针（全部通过）**；另将 18 条既有测试重新运行通过。针对当时 83 张 YELLOW 的逐卡行为补验及规则确认，得到 80 GREEN、2 RED、1 YELLOW。本轮 Classic 沉默复测又确认此前 GREEN 的 `CS2_142` 狗头人地卜师在沉默后仍保留法术伤害，故当前整包为 **GREEN 138 / YELLOW 1 / RED 4**。没有依据 Python 类存在或普通出牌烟测升绿。

新确认的 RED 是 `EX1_194` 能量灌注：文案 `+2/+6`，源码 `buff(+2,+2)`；实际把 3/5 随从变成 5/7，预期应为 5/11。`CS2_063` 腐蚀术已验证目标限制、跨对手回合保留、施法者下回合开始销毁及区域变化，因此升 GREEN。28 张无逐卡 Python 脚本的 Basic 随从均核对了手牌与入场的属性、费用、种族和区域；11 张有种族的随从另核对了实际种族选择器能选中该随从而排除无种族随从。嘲讽、冲锋、法术伤害另经真实攻击或法术伤害场景验证。基础武器验证了装备、伤害和耐久，`CS2_097` 还验证了攻击时治疗。

本轮针对原始 **83 张 YELLOW** 逐卡执行独立行为测试：**80 张转 GREEN、2 张转 RED、1 张仍为 YELLOW**。`BT_142` 影蹄杀手的战吼把 +1 攻击附魔加在玩家对象，英雄攻击力实际保持 0。人工确认重复卡副本也可被分别检索后，`BT_323` 盲眼监视者在 4 张实体仅 2 种卡号时只给 2 个选项，违反应展示 3 张物理候选的规则，因此确认为另一张新 RED。人工确认单敌随从只应受一次伤害后，`BT_740` 灵魂裂劈的单目标 2 点伤害和 2 点吸血与双目标、零目标分支均通过，升为 GREEN。`DS1_184` 追踪术的牌库候选、入手与移出游戏通过，但“抽取一张”是否应触发抽牌事件尚未证实：当前实现直接移牌，本回合抽牌计数保持 0，故仍为唯一 YELLOW。除这两张卡的具体脚本错误外，本次未确认新的共享底层机制故障；相似代码的其他卡牌不自动改级。

## 本轮逐卡补验：Classic、Hall of Fame、Naxxramas

固定范围是三个扩展包在本轮开始时的 **291 张原始 YELLOW 可收藏卡**。每张均核对中英文文案、实现、已有测试与原 audit 结论，再运行与自身效果对应的最小对局断言；多分支牌补测目标、候选池、回合、区域或满场边界。合计 **422 条独立 case，268 张转 GREEN、20 张转 RED、3 张保留 YELLOW**。仅有代码、能出牌或已有测试卡号引用均不计作 GREEN。

| 原黄卡所属 set | 检查数 | GREEN | YELLOW | RED |
|---|---:|---:|---:|---:|
| Classic (EXPERT1) | 229 | 215 | 3 | 11 |
| Hall of Fame (HOF) | 34 | 30 | 0 | 4 |
| Curse of Naxxramas (NAXX) | 28 | 23 | 0 | 5 |
| **合计** | **291** | **268** | **3** | **20** |

仍为 YELLOW 的具体阻碍：`EX1_095` 加基森拍卖师已通过己方手牌施法抽牌及对手施法不触发；`EX1_187` 奥术吞噬者已通过己方手牌施法连续 +2/+2 与对手施法不触发；`EX1_559` 大法师安东尼达斯已通过己方连续施法各得一张火球术。三张均尚未证明**效果代施放法术**是否应触发“你施放一个法术”，`CAST-001` 保留为规则语义待核实，因此没有升绿。

本轮新增或细化的 RED 共 20 张：Classic 的 `EX1_080`、`EX1_130`、`EX1_182`、`EX1_407`、`EX1_509`、`EX1_560`、`EX1_563`、`EX1_577`、`EX1_584`、`NEW1_005`、`NEW1_036`；Hall of Fame 的 `EX1_085`、`EX1_116`、`EX1_161`、`NEW1_004`；Naxxramas 的 `FP1_016`、`FP1_019`、`FP1_025`、`FP1_026`、`FP1_029`。每张失败条件、期望值和实际状态均在分包 CSV 与对应 probe 行中。

公共底层问题优先保留为机制级记录：死亡批次处理错误影响绝命乱斗与阿努巴尔伏击者；向对手召唤和夺取控制权可能越过七格上限；回手动作不区分原拥有者与当前控制者；跨玩家抽牌计数记错玩家；沉默未清除原生法术伤害；`ANOTHER_CLASS` 随机池包含中立卡；复生错误使用施法者控制权。详见 `mechanism_issues.csv` 的 `DEATH-001`、`BOARD-002/003`、`BOUNCE-001`、`DRAW-001`、`SILENCE-001`、`RANDOM-001` 和 `CONTROL-001`。沉默问题还使此前已标 GREEN 的 `EX1_332`《沉默》与 Basic 的 `CS2_142` 改为 RED；这两张不计入 291 张原黄卡的转换统计。

验证门禁通过：`verify_expansion_audit.py` 核对原始 291 ID、逐卡 case 与判定、证据引用及分包导出；`verify_report.py` 核对全 2,497 张可收藏卡与 24 个扩展包对账。本轮未修改游戏卡牌实现。

## 本轮逐卡补验：GVG、BRM、TGT、LOE

固定范围是四包在开始时的 **315 张原始 YELLOW 可收藏卡**。每张都有本轮独立的实际对局用例，按自身文本检查数值、目标、区域、回合、触发、选择或随机候选；既有测试仅作辅助证据。共有 **395 条本轮定向行为 case** 和 **59 条辅助既有测试记录**，共 454 条。结果为 **282 GREEN、19 YELLOW、14 RED**。

| set | 原黄卡 | GREEN | YELLOW | RED | probe case |
|---|---:|---:|---:|---:|---:|
| GVG | 118 | 94 | 18 | 6 | 198 |
| BRM | 30 | 28 | 0 | 2 | 43 |
| TGT | 125 | 119 | 0 | 6 | 149 |
| LOE | 42 | 41 | 1 | 0 | 64 |
| **合计** | **315** | **282** | **19** | **14** | **454** |

GVG 的 18 张 YELLOW 都在 `gvg_yellow_quality.csv` 写明具体缺口，主要是随机结果池只出现一个候选、尚未覆盖另一合法目标，或条件分支未测；例如 `GVG_052` 尚缺无受伤友方随从时的原费用检查，`GVG_090` 尚缺伤害分配到随从的局面，`GVG_107` 尚缺随机嘲讽分支。LOE 的唯一 YELLOW 是 `LOE_086`：玩家直接施法时已验证召唤，但灯神代施放副本是否也应计入“你每施放一个法术”的规则语义未定，因此没有强行判 GREEN 或 RED。

14 张 RED 的逐卡实际偏差如下：GVG 的 `GVG_022` 随机加攻可能落到英雄、`GVG_046` 计入自身野兽、`GVG_048` 只强化一只其他机械、`GVG_054` 武器攻击未随机改打目标、`GVG_087` 狙击手未扩展稳固射击目标、`GVG_113` 未伤害相邻随从；BRM 的 `BRM_002` 火妖每次伤害了所有敌方角色、`BRM_029` 只有友方传说目标时错误显示战吼未就绪；TGT 的 `AT_008` 英雄技能不能无限使用、`AT_049` 图腾只得 +1 攻击、`AT_067` 未伤害相邻随从、`AT_069` 自身缺嘲讽、`AT_090` 错误强化自身、`AT_109` 激励后仍无法攻击。共用 CLEAVE 目标上下文错误同时由 `GVG_113` 与 `AT_067` 实测确认；武器的错误目标事件和猎人英雄技能目标修饰作用域也另列 `FORGETFUL-001`、`HEROPOWER-002`。全部机制级问题见 `mechanism_issues.csv`。

`verify_four_set_audit.py` 已核对 315 个固定 ID、每卡独立 case、case 唯一性、评级与实际 outcome、标签覆盖、证据文件时序和四包 CSV 导出；`verify_report.py` 与 `verify_expansion_audit.py` 同时通过。没有修改游戏卡牌实现。

## 阶段执行状态与未验证范围

每一阶段均先列出该机制在**每个 set** 的候选实体，再核对源码、现有测试，运行正例和边界最小复现，最后更新 `card_mechanism.csv`；`card_quality.csv` 按最差机制自动聚合。随机效果固定随机种子，并检查候选集合、抽样次数和落区；选择与目标效果同时检查取消/非法目标；死亡和触发效果同时检查 zone、顺序、重复触发。

1. **基础状态原语**：已完成死亡、区域、目标、选择、随机及 Reborn 的代表性横向检查；保留未测交叉场景。
2. **高覆盖主动效果**：已核对现有测试并运行代表性战吼、法术、召唤、抽弃牌、变形、沉默；跨玩家抽牌计数错误已入问题表。未逐张验证数百张同机制卡。
3. **交互与持续效果**：已调查 Discover、Choose One、Trigger、Aura、Secret、Quest、费用修改；执行代表性场景与 10 张条件属性卡专项。Quest/SideQuest 大多仍缺逐卡效果断言。
4. **资源与装备**：武器、英雄技能、连击做了实际攻击/目标/费用探针；35 张普通可收集 Overload 全部逐卡通过，其他机制仍只是抽样。
5. **关键词与特殊路径**：Rush、Reborn、Lifesteal、Poisonous、Outcast、Spell Damage 已有正例；Magnetic、Echo、Twinspell 主要依赖现有窄样本测试。模式卡的 3 个无效持续效果留在机制证据中，不进入可收藏卡评级表。
6. **逐扩展包回扫**：24 个有可收藏卡的 set 的主表、质量表、机制行和烟测逐包对账全部通过；Basic、Classic、Hall of Fame、Naxxramas、GVG、BRM、TGT、LOE 的指定原黄卡分别完成逐卡行为测试。其他 set 目前仍以覆盖核算和抽样为主。
7. **独立复核与证据门禁**：复核纠正了漏标机制、错误 set 关联、来源法术漏标 RED、候选池和控制权边界漏测；`verify_report.py`、`verify_expansion_audit.py`、`verify_four_set_audit.py` 校验源码快照、逐卡证据、原始范围及逐包总数。

具体升降级规则：**GREEN** 必须有当前代码上可复查的效果断言和关键状态验证；**YELLOW** 用于只有代码/标签/普通烟测、部分正确或条件复杂未证实；**RED** 用于经静态与运行时证实的未实现、错误状态、异常或无法正常交互。机制标签为候选时，先确认机制归属，再写断言。问题属于共享层时优先在 `mechanism_issues.csv` 记录和列出受影响卡，不因一次普通场景通过而把风险卡升级 GREEN。

复现清单（逐卡组 `a`、`b` 有预期的 inconclusive/confirmed_error，脚本会保留 CSV 并返回非零；请读取逐 case 结果）：

```sh
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/reproduce_play_failures.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/reproduce_overload.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/foundation_probes.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/targeting_prereq_sweep.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/later_stage_probes.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/cross_player_draw_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/dormant_full_board_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/discover_pool_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/conditional_stats_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/mode_ongoing_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/infectious_sporeling_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_runtime_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/vanilla_runtime_probe.py
venv/bin/python reports/card_quality_full_2026-09-27/basic_existing_tests.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_corruption_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_power_infusion_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/castspell_trigger_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/basic_card_probe_e.py  # 其他逐卡组同名 a-k
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_first.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_first_last5.py
venv/bin/python reports/card_quality_full_2026-09-27/merge_classic_first_last5.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_middle_a.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_second.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_middle_b.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_final10.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/classic_probe_tail.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/hof_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/hof_gelbin_detail.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/hof_leeroy_full_board.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/hof_random_detail.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/hof_owner_bounce_detail.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/hof_repair_bot_domain.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/naxx_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/gvg_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/gvg_probe_tail.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/brm_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/tgt_probe.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/tgt_probe_tail.py
PYTHONPATH=tests:. venv/bin/python reports/card_quality_full_2026-09-27/loe_probe.py
venv/bin/python reports/card_quality_full_2026-09-27/merge_split_set_probes.py
venv/bin/python reports/card_quality_full_2026-09-27/finalize_verdict_metadata.py
venv/bin/python reports/card_quality_full_2026-09-27/clarify_verdict_reasons.py
venv/bin/python reports/card_quality_full_2026-09-27/build_report.py
venv/bin/python reports/card_quality_full_2026-09-27/set_sweep.py
venv/bin/python reports/card_quality_full_2026-09-27/export_expansion_audit.py
venv/bin/python reports/card_quality_full_2026-09-27/export_four_set_audit.py
venv/bin/python reports/card_quality_full_2026-09-27/verify_report.py
venv/bin/python reports/card_quality_full_2026-09-27/verify_expansion_audit.py
venv/bin/python reports/card_quality_full_2026-09-27/verify_four_set_audit.py
```

本轮没有修改任何卡牌实现；CSV 是当前代码快照的保守质量地图，后续专项验证应追加可复查的运行证据并重新生成聚合表。
