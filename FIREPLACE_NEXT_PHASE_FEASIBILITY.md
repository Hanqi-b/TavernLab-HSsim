# Fireplace 下一阶段架构调查与可执行性评估

调查基线：仓库 `master`，commit `47a2572a000db66645bb74a425a090d51f1004fa`；Python 3.10.12；`fireplace==0.1.0`、`hearthstone==9.21.1`、`hearthstone-data==251952.1`。本报告仅调查和规划，没有修改生产代码。

## 1. Executive Summary

当前 checkout 是 Fireplace 的 Python 炉石规则模拟器，不是已带 TUI 和 AI Agent 的对战应用。批量随机模拟位于 `fireplace/utils.py`，通过 `tests/full_game.py` 启动；仓库没有交互式 TUI、Agent 类、统一玩家动作 API 或通用 game controller。`kettle/kettle.py` 是 TCP/JSON 协议适配器，不是终端界面。

总体方向可执行，且大部分动作已有可用的 Fireplace 方法，不需要重写引擎。最大工作量在新建一个薄的、按阶段工作的决策边界：动作列举与执行、mulligan 和异步 choice/discover、玩家视角信息过滤。最大技术风险是误把 `is_playable()` 当成完整合法动作列表、把原始游戏对象或隐藏牌信息交给 Agent，以及把“记录输入”误当成“确定性 replay”。

验证结果：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 venv/bin/python -m pytest tests` 得到 **828 passed**；另直接运行 `venv/bin/python tests/full_game.py`，一局随机对战正常结束。pytest 需禁用环境中 ROS 提供的第三方插件自动加载，否则其缺失的 `yaml` 依赖会使 pytest 在收集测试前退出。这是当前运行环境问题，不是 Fireplace 测试失败。

## 2. Current Architecture

| 部分 | 当前实现 | 结论 |
| --- | --- | --- |
| 包 / 启动入口 | `setup.cfg` 只定义 Python 包和依赖，没有 `console_scripts`；README 介绍模拟器和安装方式。批量运行脚本是 `tests/full_game.py:20-34`。 | 没有产品级交互入口；测试脚本承担了运行示例的角色。 |
| 初始化 | `fireplace/utils.py:199-213` 的 `setup_game()` 随机选两个职业、随机生成两套牌，创建 `Player` 和 `Game`，然后 `game.start()`。 | `setup_game()` 不收 seed，也不接入 Agent。 |
| 玩家 / 初始牌 | `fireplace/player.py:51-104` 初始化玩家；`prepare_for_game()` 在 `player.py:267-311` 创建英雄和卡牌、洗牌并抽起手牌。 | Fireplace 负责游戏内实体和牌区。 |
| mulligan | `Game` 继承 `MulliganRules`；`game.start()` 建立每位玩家的 `MulliganChoice`，两边都提交后才进入首回合，见 `fireplace/game.py:435-461`。`play_full_game()` 自动随机换牌，见 `fireplace/utils.py:279-290`。 | 是独立的开局阶段，不能只把 `current_player` 当作输入路由依据。 |
| 回合 / 胜负 | `play_turn()` 位于 `fireplace/utils.py:216-276`；`Game.end_turn()` 在 `game.py:332-335`。`check_for_end_game()` 写入完整/胜负状态，`action_end()` 在终局抛出 `GameOver`，见 `game.py:127-143,207-232`。 | 游戏流和随机策略目前集中在工具循环里；循环靠 `GameOver` 结束。 |
| TUI | 在当前源码中未发现终端交互输入、curses 或 TUI 框架。 | 用户描述的 TUI 不属于当前 checkout；需新建。 |
| 协议适配 | `kettle/kettle.py:281-338` 实现 TCP 请求处理；`KettleManager` 生成协议状态和选项，并把选项翻译成 Fireplace 调用，见 `kettle/kettle.py:104-226`。 | 可参考其适配思路，但它有协议状态、网络 I/O 和 Fireplace 对象耦合，不应直接充当 TUI/Agent 层。 |

`play_turn()` 当前做法：先随机处理 `player.choice`；可用英雄技能时按 10% 概率使用；遍历手牌，对可打出的牌按 50% 概率尝试出牌；Choose One 和目标随机选；再对可攻击角色随机选目标；最后直接结束回合（`fireplace/utils.py:219-275`）。这属于“随机的局部动作尝试”，并不构造所有合法 Action 后从中抽样。

质量注意：`play_turn()` 直接遍历 `player.hand`，而打出的牌会在 `card.py:201-229` 的换区逻辑中从手牌列表删除；边遍历边删可能跳过后续牌。若把旧策略搬入 `RandomAgent`，应先用动作列表抽样，或遍历快照并在每一步重新计算可行动作。`fireplace/utils.py` 同时放着 CardList、随机套牌、XML 序列化和整局模拟；`fireplace/actions.py` 有 2252 行、`fireplace/card.py` 有 1705 行，属于大型引擎模块，但本轮目标不要求拆它们。

## 3. Current Action Coverage

| Action | 当前支持 | Fireplace API / 源码位置 | 需要修改 |
| --- | --- | --- | --- |
| 出牌 `PLAY_CARD` | 部分。随机遍历手牌，检查 `is_playable()`；只尝试一部分可打牌。 | `PlayableCard.is_playable()`、`.play(target,index,choose)`：`fireplace/card.py:425-579` | 做成显式动作；生成可选分支、目标、随从落点；按引擎结果刷新动作。 |
| Choose One 分支 | 部分。随机取 `choose_cards` 中一项；不是统一 Action。 | `card.must_choose_one` / `choose_cards`：`card.py:350-356,406-411`；`.play(choose=...)`：`539-579` | 动作需记录父手牌实体和所选分支实体；只暴露实际可用的分支。分支自身可能改变目标要求。 |
| 目标选择 | 部分。由随机策略在 `card.targets` 中取目标；目标是出牌/技能/攻击调用的参数。 | `play_targets` 和 `requires_target()`：`card.py:619-735`；校验在 `.play()` / `.use()` | 不单独建立必须提交的 `SELECT_TARGET` 游戏动作；目标与其所属命令一起提交。TUI 可在内部先显示目标提示，再构造最终 Action。 |
| 随从攻击 | 部分。遍历 `player.characters` 并随机攻击目标。 | `.can_attack()`、`.attack_targets`、`.attack(target)`：`card.py:885-975` | 为每个可攻击者与其合法目标生成 Action；不重做 Taunt、Rush、冻结、攻击次数等规则。 |
| 英雄攻击 / 武器 | 部分。英雄在 `player.characters` 中，策略走相同攻击路径。 | 英雄继承 `Character`；武器攻击加到 Hero，武器风怒和耐久由规则处理：`card.py:971-1025`、`rules.py:11-12` | 复用 `ATTACK`，由 source 类型显示“英雄攻击”；武器不是独立攻击动作。 |
| Hero Power | 部分。可用时 10% 概率；选择和目标随机。 | `.is_usable()`、`.use(target,choose)`：`card.py:1652-1705` | 单列 `USE_HERO_POWER`，生成可用的 choose 分支和目标。 |
| Choice / Discover | 部分。`play_turn()` 在多个位置自动随机选择 `player.choice.cards`。 | `player.choice`；`Choice` / `Discover` 设置待选项，`choose(card)` 消费：`actions.py:784-845,1152-1205` | Action API 中必须是独立的待办决定；处理完后重新查询，因为可能立即出现下一项 choice。 |
| Mulligan | 部分。整局函数为双方随机挑换牌集合。 | `MulliganChoice.choose(*cards)`：`actions.py:417-452`；流程：`game.py:441-458` | 建立 `MULLIGAN` 阶段；每位玩家单独提交选择，等待两边都完成。 |
| 结束回合 | 支持，但不是策略作出的单一候选动作；`play_turn()` 最后无条件调用。 | `game.end_turn()`：`game.py:332-335` | 变成 `END_TURN` Action，与其余可行动作并列。 |
| 投降 | 当前随机循环不支持；引擎有 `Player.concede()`。 | `fireplace/player.py:397-399` | 可作为可选的 `CONCEDE` 输入，用于完整交互体验；不是正常回合合法动作的核心。 |

`KettleManager.get_options()` 证明基础的出牌、攻击和技能选项可从当前局面枚举；但 `process_send_option()` 没有把 Choose One 分支传给 `.play()` / `.use()`，且 Kettle 使用 `BaseGame` 并跳过 mulligan（`kettle/kettle.py:195-226,340-362`），不等于已有完整人类玩家控制层。

**已复现的 Choose One 随机策略缺陷：** `play_turn()` 把 `card` 变量替换成 `card.choose_cards` 的分支对象，再调用 `card.play()`（`utils.py:246-254`）；分支对象不是手牌中的父牌。使用脚本诊断播放 `Nourish` 的第一个分支后，分支进入墓地，但父牌 `EX1_164` 仍在手牌。正确调用应以父牌为 source，使用 `parent.play(choose=branch, ...)`。这不是 Fireplace 引擎规则错误，而是当前随机 runner 的动作翻译问题；新 Action 层应加测试防止重现。

## 4. Proposed Minimal Architecture

```text
                   ┌─────────────────────────────────┐
                   │ Agent                            │
                   │ HumanTUI / Random / later Rule   │
                   │ choose_action(observation, acts) │
                   └────────────────┬────────────────┘
                                    │ Action (IDs + values only)
                                    ▼
┌─────────────┐   ┌──────────────────────────┐   ┌───────────────────┐
│ Fireplace   │──▶│ thin game session / loop │──▶│ ActionExecutor    │
│ Game/Player │   │ phase + active player    │   │ resolve IDs,      │
└─────────────┘   └────────────┬─────────────┘   │ revalidate, call  │
                               │                 │ Fireplace methods│
                               ├── ObservationBuilder              └─────────┘
                               └── LegalActionProvider ──▶ Action[]
```

最小做法是新建少量模块与函数边界，不需要先建设一套框架：

- 需要一个 session/runner 负责 mulligan、pending choice、普通回合、Agent 调度和 `GameOver` 收尾。
- Provider 只查询当前状态和 Fireplace 已有的合法性方法，不模拟出牌来预测下一步。
- Executor 是有副作用的唯一动作入口。Provider 与 Executor 概念上分离，但 MVP 用同一模块中的函数即可，不必创建两个服务类。
- 暂时不需要独立 `GameController` 类；一个 `run_game(game, agents)` 函数或轻量 session 对象足够。只有在需要保存跨回合记录/状态后，再把状态提升为类。
- Agent 可以用 `typing.Protocol` 或简单的共同方法约定，不用复杂继承树。Presentation 与决策输入要分开：TUI 把屏幕选择翻译成 Action，不直接执行引擎对象方法。

## 5. Action Model

建议 Action 仅代表“玩家选择”，不把内部 Battlecry、Deathrattle、抽牌、随机伤害等引擎效果误当成玩家动作。可 JSON 化的最小记录：

```json
{
  "type": "PLAY_CARD",
  "source_entity_id": 42,
  "target_entity_id": 17,
  "choose_option_entity_id": 43,
  "position": 2
}
```

字段按 `type` 取用：

| 字段 | 含义 |
| --- | --- |
| `type` | `PLAY_CARD`、`ATTACK`、`USE_HERO_POWER`、`END_TURN`、`CHOOSE`、`MULLIGAN`；可选 `CONCEDE`。 |
| `source_entity_id` | 出牌实体、攻击者或英雄技能实体的本局 `entity_id`。 |
| `target_entity_id` | 出牌/攻击/英雄技能的目标；可为空。 |
| `choose_option_entity_id` | Choose One / Choose One 技能分支；传给父牌的 `choose` 参数。 |
| `position` | 随从的 0 起始插入位置；非随从不使用。引擎 `index` 与卡牌对外 `zone_position` 的 1 起始不能混淆。 |
| `choice_entity_id` | `CHOOSE` 阶段当前 choice 提供的选项实体。执行前须确认仍在当前 `player.choice.cards` 中。 |
| `mulligan_entity_ids` | `MULLIGAN` 要换回牌库的手牌实体集合；空集合表示全部保留。 |

不要保存 Fireplace 对象引用：它无法直接 JSON 序列化，也会泄露对象内部。`entity_id` 由 `GameManager` 在**单局内**单调分配，适合立即执行和本局输入日志，但不是跨局稳定 ID；重放记录应同时带 `game_id`，永久卡牌身份另记可见时的卡牌定义 ID。`GameManager` 自身没有按 ID 找实体的 API；Kettle 也维护了一份 `entity_id -> entity` 映射并注明这一点（`kettle/kettle.py:64-74,190-193`）。runner 应有局内实体索引，或者在执行时从当前实体区安全解析。

无需区分 `HERO_ATTACK` 与 `ATTACK`：两者都可调用 `Character.attack(target)`，展示名称由 source 实体类型决定；weapon 也不是玩家动作。无需独立 `SELECT_TARGET`：`.play()` / `.use()` / `.attack()` 都把 target 当参数。`DISCOVER` 与一般 `CHOOSE` 可共用“从当前选项中选一个”的 Action；choice 来源/种类可以放在 observation 或日志中。`MULLIGAN` 必须独立，因为它是开局阶段且可以一次选择多张牌。

这个 schema 可用 Python dataclass 表示，再由 `asdict()` 序列化；不要将 Python `Enum`/实体对象/回调放入记录。Action log 可以 JSON；这只代表数据可序列化，**不代表能确定性 replay**，见第 11 节。

## 6. LegalActionProvider Feasibility

**可行，但不能把“枚举完整性”简化为对 `is_playable()` 的扫描。** Fireplace 有足够的只读入口供常见命令枚举：

- 手牌：先对父卡调用 `is_playable()`；对 Choose One 的每个分支单独检验可用性，并根据被选分支计算 target。只要 `requires_target()` 为真，就对 `play_targets` 各生成一个组合；没有目标且卡牌可选目标时，生成不带 target 的动作。需要目标且无目标的牌一般会由 `is_playable()` 拦住。随从落点为现有板位 `0..len(field)`。
- 攻击：遍历 `player.characters`，对 `can_attack()` 为真的来源枚举 `.attack_targets`。目标属性已按 Taunt、Rush、隐身、Dormant、不可攻击目标等规则过滤；windfury / attack count 由 `can_attack()` / `exhausted` 判定。
- 技能：`hero.power.is_usable()` 后列出普通与 Choose One 分支及分支所需目标。
- 普通行动：追加 `END_TURN`。
- pending `player.choice`：只返回当前列出的 choice 选项，不返回普通回合动作。`MultipleChoice` 每次选择后会改变选项并要求再选，需回到 Provider 重新查询。
- Mulligan：两个玩家在开局都可能各有一个 `MulliganChoice`，所以按指定 player/阶段提供可换集合；正常开局只有 3/4 张起手牌，列举子集成本很低。不能只看 `game.current_player`。

Provider 不应为了知道 Discover 选项先执行卡牌。Fireplace 只在产生 Discover 的卡牌效果解析后，才把 `player.choice` 和随机生成的 `choice.cards` 放进局面；此时它成为下一条 `CHOOSE` 决策。正确模型是“执行动作 → 重新读取局面 → 列出新阶段动作”，而不是一次性提前预测完整决策树。

API 限制 / 适配陷阱：

1. `card.targets` 有上下文含义：手牌 PlayableCard 使用 `play_targets`，场上的 Character 则使用 `attack_targets`（`card.py:729-735,981-984`）。Provider 应按动作类型使用明确属性，避免含糊的 `.targets`。
2. 对 Choose One 必须枚举父牌与分支组合；父牌的 `is_playable()` 只表明至少存在一个可行分支。单一分支还要检验它自身。调用 API 最稳妥的是父牌 `.play(choose=branch, ...)`。
3. `requires_target()` 依条件变化；某些卡是“有合法目标才要求选”，有些卡只对 Battlecry 有条件目标。每次查询都以当前状态为准。
4. 不能承诺一次性完整支持 Fireplace 的每一种卡牌机制。`targeting.py` 有已支持要求的明确列表，且对部分 newer requirement 留有注释掉的代码（`targeting.py:30-135`）；卡牌脚本也可有特殊选择。首版应限定支持“当前引擎 API 能表达的玩家输入”，对新发现的分支加针对性用例，不重写规则。
5. `min_count` / `max_count` 不是所有 Choice 的统一验证器。`MulliganChoice` 提供 `min_count=0`、`max_count=len(hand)`，但 `.choose(*cards)` 只断言每张牌属于选项，不强制数量或去重；其 `cards` 会排除 Coin，而 `max_count` 仍基于整手牌。普通 `Choice` / `Discover` 每次只接受一个参数；`MultipleChoice` 每次接受一个选项并可能刷新下一步选项。因此 Provider 和 Executor 必须按 Choice 类型与当前选项集检查数量、去重和阶段，不能仅照搬这些字段。

结论：通常无需在“不执行动作”的前提下模拟游戏。常见 legal candidates 可通过 `is_playable`、`requires_target`、`play_targets`、`can_attack`、`attack_targets`、`is_usable` 和当前 `player.choice` 列出；动态的后续选择等动作发生后再列。

## 7. ActionExecutor Feasibility

**可行，并建议成为唯一的外部动作入口。**执行器把 ID 解析成当前实体后，调用受检 API：

- `PLAY_CARD` → `card.play(target=..., index=..., choose=...)`
- `ATTACK` → `character.attack(target)`
- `USE_HERO_POWER` → `hero.power.use(target=..., choose=...)`
- `CHOOSE` → 当前 `player.choice.choose(card)`
- `MULLIGAN` → 当前 `MulliganChoice.choose(*cards)`
- `END_TURN` → `game.end_turn()`

执行前重新生成/验证当前玩家的合法动作，确认 source 仍属于当前玩家和正确区域、target 仍合法、choice 仍待处理、落点仍有效。Fireplace 的 `.play()`、`.attack()` 和 `.use()` 自身会校验部分状态并抛出 `InvalidAction`；不要绕过这些方法直接调用较底层的 `game.play_card()` 或 `game.attack()`。

人类输入等待期间、外部 Agent 或未来多客户端都可能造成 Action 过期。过期/非法 Action 应返回一个可解释的错误（错误类型加简短原因），保留当前局面并重新显示 observation/actions；不应吞掉异常后自动随机选一个动作。底层引擎异常仍可记录 traceback。MVP 不需要复杂 stale-action 锁或分布式一致性机制。

因为 Fireplace ID 查找 API 不存在，runner 在 `game.start()` 前注册 `BaseObserver.new_entity` 以维护索引，或在启动后扫描所有当前区域建立索引、再接 observer 增量更新。现有 `setup_game()` 会先 `game.start()` 再返回，不能直接在调用后注册 observer 并指望收齐初始化实体。最简单的改造是让 TUI/session 自己创建 Game、在 start 之前挂索引，再走原 mulligan 流程。

## 8. Agent Interface Feasibility

可以采用用户提出的方法：

```python
choose_action(observation, legal_actions) -> Action
```

但这两个参数都应是 Agent 视角安全的值对象/字典，而不是 `Game`、`Player`、Card 实例。方法返回后由 session 验证并交给唯一 Executor。

- `RandomAgent`：对当前合法候选随机取样；Mulligan 对牌集合随机取舍；Choice 从现有选项抽取。旧 `play_turn()` 随机算法应改为此类策略或适配器，不再直接操作 game。
- `HumanTUIAgent`：展示 observation 和动作，读入序号/参数，返回 Action，不执行它。
- `RuleAgent` / `HeuristicAgent`：待最小动作和观测接口稳定后添加；与 `RandomAgent` 共用一个方法约定即可。
- `LLMAgent` / Search / RL：技术上未来可接，但不应现在加 API、prompt、训练接口或依赖。

不建议这轮就引入复杂的多 Agent 生命周期、异步消息、并行决策或策略注册框架。一个 Protocol / 简单类约定足以替换控制者。

## 9. Human TUI Feasibility

**现在距离“真人通过 TUI 完整打一局”仍差一套薄的应用层；引擎 API 本身不是主要阻碍。**当前不存在 TUI，也没有任何真实的人类输入路径。至少还需要：

1. 一个接收固定卡组/职业、可选 seed、两名 Agent 的 Game factory；能够在 `start()` 前安装局内 entity 索引。
2. 显式阶段路由：双方 Mulligan、普通回合、pending choice/discover、多步 MultipleChoice、终局。开局不能等待 `current_player` 提示来决定谁先 mulligan。
3. `LegalActionProvider` 为出牌、分支、目标、随从站位、英雄/随从攻击、技能和结束回合列动作；choice 阶段只列当时的选项。
4. 易读的 TUI 视图：双方英雄血量/护甲/法力、棋盘与卡牌、自己完整手牌、对手手牌数量、行动序号；对不合法输入说明原因后重试。
5. 每条行动后刷新状态和动作列表；不能保留上一条状态的 target / discover 引用。
6. Human 与 Random Agent 的路由及双方 mulligan 提交；捕获 `GameOver` 并报告胜者。
7. 隐私投影和观测测试，避免 TUI 之后 Agent API 直接得到对手手牌。

相对于 GUI，这是一个范围可控的垂直切片；不需要 Web 框架。初期命令行支持 `1..N` 选择、目标、Choose One 分支、随从位置、mulligan 子集和退出即可。

## 10. Observation / Hidden Information

Fireplace 对象默认是完整模拟状态，不应把它们直接传给 Agent。`Player.dump()` 会序列化完整手牌和 choice；`Player.dump_hidden()` 试图隐藏牌面，但手牌/choice 仍有 entity_id，且 secret/zone 序列化也需按观察者处理（`player.py:106-153`）。`BaseObserver` 的 `new_entity` / `targeted_action` 回调提供完整实体对象，没有视角过滤（`managers.py:97-120`）。因此，直接传 `game`、`player.dump()` 或原生 observer 事件都可能泄漏信息。

建议显式按 viewer 构造最小投影，不把 `dump_hidden()` 原样视为安全边界：

```json
{
  "turn": 5,
  "phase": "MAIN | MULLIGAN | CHOICE | GAME_OVER",
  "active_seat": 0,
  "self": {
    "hero": {"entity_id": 5, "card_id": "...", "health": 27, "armor": 0},
    "mana": 5, "max_mana": 5,
    "hand": [{"entity_id": 23, "card_id": "...", "cost": 2}],
    "board": [], "weapon": null, "hero_power": {},
    "deck_count": 18, "secrets": []
  },
  "opponent": {
    "hero": {"entity_id": 8, "card_id": "...", "health": 30, "armor": 0},
    "board": [], "weapon": null, "hero_power": {},
    "hand_count": 4, "deck_count": 20, "secrets_count": 1
  },
  "pending_choice": null
}
```

自己能见到的手牌和当前选择要有可执行用的本局 entity handle；对手暗手牌和牌库不列实体 ID、卡牌 ID 或卡牌对象，只列数量。公开棋盘、英雄/武器/技能状态可按游戏规则公开。`pending_choice` 只给对应的行动 Agent 看。隐藏牌离开隐区后才在新的 observation 里出现。

`entity_id` 是单局单调分配值，不是密码学随机数；若把暗牌实体 ID 发给对手，创建顺序可能形成无必要的信息侧信道。局内 Action 使用 entity ID 没问题，但 observation 只应向有权引用该实体的一方发 ID；对手手牌直接只给 count。记录、训练样本和 observer 日志也应分别做可见性过滤。

## 11. Replay / RNG

### Action log

可先记录通过 Agent 边界的**决策输入**，而不是把每个 Fireplace 内部 DSL 动作当作玩家命令：

```json
{"seq": 17, "turn": 5, "player": 0, "phase": "MAIN",
 "action": {"type": "ATTACK", "source_entity_id": 23, "target_entity_id": 8}}
```

再配套记 game id、仓库 commit、模式、双方职业/初始卡组、赢家和时间。它适合回看人类/Agent 做了什么、排错、做粗粒度统计；如果要展示“具体对战事件”，可额外消费 observer 回调或比较执行前后状态。现有 `BaseObserver` 回调是内存事件且携带对象引用，不是已持久化、带隐私策略的输入日志。`tests/test_misc.py:203-265` 里的 `test_observer` 在 `setup_game()` 已启动后才注册 observer；构造的 action/dump 数据没有断言，不能证明完整 recorder 已有。

### Deterministic replay

从初局完整重放并得到等价结果，比记录 Action 多出前置条件：

- 精确保存版本、两边职业/英雄、初始卡组及顺序、先手、所有 mulligan、玩家 Action/choice。`Game(seed)` 有局内 RNG (`game.py:40-41`)，但当前 `setup_game()` 不接受 seed；随机职业/卡组用模块级 `random`（`utils.py:89-131,199-211`）。
- 游戏内随机数大部分走 `game.random`，但全局 RNG 路径仍存在。例如 `Discover` 对某些中立牌随机职业调用 `random_class()` 且不传 game（`actions.py:1161-1177`），随机套牌/职业 helper 和 Brawl helper 也有模块级 `random`（`utils.py:89-131`、`brawls/__init__.py:87-91,310-320`）。需审计并集中 RNG，或至少把所有相关 RNG state 纳入测试记录。
- 记录人类/AI 对可选目标、Choose One、Discover、Mulligan 的实际输入。随机效果本身由相同 seed 和确定执行顺序重算；seed 不能替代用户命令记录。
- `uuid.uuid4()`（`entity.py:14-19`）和回合墙钟 `turn_start`（`game.py:380`）不是玩法 RNG，仍会让全对象快照的字节比较不同；replay 验证应比较归一化的游戏状态，不比较 UUID/时间戳。

建议顺序：先 Action log 和固定卡组 smoke test；然后统一 RNG 入口、增加 seed 参数和重复运行等价断言；不要现在实现任意时点存档/恢复、分支 replay 或二进制快照。初版的 deterministic replay 应定义为“相同代码版本、初始配置和命令日志从头再跑，得到归一化状态一致”，不要承诺跨版本兼容。

## 12. Recommended Phases

以下是对原 Phase 的逐项判断，并按依赖重新排序：

| Phase | 内容 | 可执行性 | 主要改动 | 依赖 | 风险 |
| --- | --- | --- | --- | --- | --- |
| 1 — Action abstraction | 定义玩家输入 Action | **FEASIBLE WITH CHANGES** | 只覆盖玩家决策命令；加 `CHOOSE` 和 `MULLIGAN`；Action 用本局 ID，不做实体引用。 | 无 | 漏掉变体字段会迫使未来破坏 JSON schema；先写例子和 schema version。 |
| 2 — Provider + Executor | 枚举/执行命令 | **FEASIBLE WITH CHANGES**；与 Phase 1 合并做一个垂直切片 | 初期在同一 controller 模块实现独立函数；支持普通回合和 pending choice/mulligan 状态。 | Phase 1、可控 game factory / ID 索引 | Choose One、条件 target、状态过期、隐藏阶段路由。 |
| 3 — Agent abstraction | RandomAgent / HumanTUIAgent | **FEASIBLE WITH CHANGES**；需在 Observation 后 | 使用简单方法约定；Agent 只接收 observation 和 Action 列表，不碰 Fireplace 实体。 | Phase 1/2/5 | 若先给 raw `game/player`，之后要大改接口。 |
| 4 — Human TUI | Human vs Random 完整对局 | **FEASIBLE WITH CHANGES**；这是新建，不是扩展现有 TUI | 在动作/状态基础上加菜单、提示、异常重试、完整开局与终局。 | Phase 1/2/5/3 | 忽略 Mulligan、choice/discover 或 minion 站位会导致“只能玩部分牌”。 |
| 5 — Observation | viewer 专属状态 | **SHOULD BE DONE EARLIER**；移到 Agent API 前 | 加最小 observation builder 和 hidden-hand/choice/privacy 测试。 | 明确动作需要的实体 handles | 原对象和 observer 数据泄漏暗牌；旧 dump 字段不能直接信任。 |
| 6 — Logging / replay | 输入日志、seed、回放 | **FEASIBLE WITH CHANGES**；必须拆成两步 | 先记 action log；后统一 RNG，再做确定性从头 replay。 | Action schema；determinism 部分依赖 Phase 1/2 | 当前初始化无 seed，存在模块级 random；事件日志并非命令日志。 |
| 7 — Rule / Heuristic AI | 规则或评分策略 | **FEASIBLE**；后置 | 只实现策略，不重复发动/攻击/targeting 的引擎规则。 | 稳定 Agent、Observation、Action | 规则质量不是本次架构工作的 blocker。 |
| 8 — GUI / API | Web、REST/WebSocket | **UNNECESSARY** 目前 | 本轮不新增框架；等 TUI 和 Agent boundary 验证后另立需求。 | 底层决策边界稳定 | 提前做会增加状态生命周期、并发和隐私面。 |
| 9 — LLM / Search / RL | 外部推理、搜索、训练 | **UNNECESSARY** 目前 | 仅保留接口可接入的空间，不加 SDK、Prompt、MCTS/RL 管线。 | Agent boundary 已验证 | 成本、数据质量和评测方法都还未定义。 |

建议实际推进顺序：`(1+2) Action + phase-aware controller` → `5 Observation/privacy` → `(3+4) Agent + Random/Human TUI 垂直切片` → `6a Action log` → `6b seed/RNG/deterministic replay` → `7 Rule/Heuristic`；GUI 和 LLM/Search/RL 暂缓。

## 13. File-Level Change Plan

以下是之后实现时建议的最小触及范围，本轮没有创建这些文件。

| 文件 | 操作 | 责任 |
| --- | --- | --- |
| `fireplace/agent_api.py` | 新增 | `Action` 数据类 / JSON 字段校验、轻量 `Agent` 协议；不导入 TUI 或网络框架。 |
| `fireplace/controller.py` | 新增 | session loop、按 phase 调用 provider、合法动作函数、ID 解析、executor、GameOver 收尾。Provider/Executor 先作为函数；达到维护痛点再拆类。 |
| `fireplace/observation.py` | 新增 | 以 viewer 为参数返回白名单字段；不得把 `dump()` 或 `dump_hidden()` 原样交给 agent。 |
| `examples/human_vs_random.py` | 新增 | 纯标准库输入输出，显示状态和合法命令、选择目标/分支/站位、启动 Human vs Random。无需先增加 `setup.cfg` console script。 |
| `fireplace/utils.py` | 小幅修改 | 保留 `setup_game()` 可复用；将 `play_turn()` 里的随机策略抽到 RandomAgent/兼容适配器，旧 `play_full_game()` 可保留为批量模拟入口。修复边遍历 hand 边移除导致的跳项。 |
| `tests/test_controller.py` | 新增 | Provider、Action→Fireplace 翻译、阶段路由和 Agent/controller 集成测试。 |
| `tests/test_observation.py` | 新增 | 自己与对手视角的 hidden hand/secret/choice 隔离。 |
| `tests/test_replay.py` | 后续新增 | 固定配置重跑和归一化状态比较；等 RNG 路径梳理后再写。 |

不建议先修改 `fireplace/game.py`、`fireplace/card.py`、`fireplace/actions.py` 来建立另一套规则系统。若实现过程中发现引擎 API 的具体缺口，先用一条用例证明缺口，再作最小修改。`setup.cfg` 只有在需要安装后命令入口时才改；本机首版可直接运行 `venv/bin/python examples/human_vs_random.py`。

## 14. Testing Plan

目标测试应用边界，不复制 Fireplace 已覆盖的规则实现。现有 pytest/tox 目标是引擎与卡牌测试；已验证现有测试 **828 passed**。新增最少用例：

| 覆盖 | 应断言什么 |
| --- | --- |
| 非目标出牌 | Provider 返回手牌实体 Action；Executor 调用后牌区/法力变化符合引擎结果。 |
| 目标出牌 | 同一张牌为每个当前合法目标生成组合；能成功执行；无效 target 被拒绝且局面不变。 |
| Choose One | 仅提供可玩的分支；目标按该分支计算；Action 通过父牌 `.play(choose=...)` 执行。 |
| 随从站位 | 可枚举合法插入位置；位置字段为 0 起始；结果顺序正确。 |
| 随从/英雄攻击 | 为当前可攻击角色生成 source-target 对；英雄使用武器攻击仍走 `ATTACK`。 |
| Taunt | Provider 的目标集合反映引擎 `attack_targets`；这里验证翻译/集合，不复刻 Taunt 算法。 |
| Hero Power | 不能用时没有动作；需目标/Choose One 时生成并执行对应字段。 |
| Choice / Discover | pending 阶段禁止普通 Action；只允许当下 choice.cards；选择后清空 choice 或重新列出下一步 choice。 |
| Mulligan | 可提交空集合与替换集合；双边都完成后引擎进入首回合；不允许传未展示的手牌 ID。 |
| End turn / game over | `END_TURN` 推进 active player；英雄死亡/投降抛 `GameOver` 后 runner 停止并返回胜者。 |
| 非法 / stale Action | 错 owner、错 zone、旧 target、重复 choice、无效位置、未知 ID 都返回错误；不发生静默随机 fallback。 |
| Observation 隐私 | 对手 hand/choice/deck 中无 card ID 和 entity ID；自己手牌可供自己执行；对手牌数仍可见。 |
| Agent 集成 | fake Human 和 RandomAgent 共用同一入口打一段完整局面；两者都只收到值对象，不收到 Game/Card 实例。 |
| replay（后续） | 相同固定卡组、seed 和 Action log 运行两次；比较归一化状态，不比较 UUID、时间戳。 |

先用固定卡组的小局面测试每种翻译，再加一条由 HumanTUIAgent/RandomAgent 跑到 `GameOver` 的 smoke test。不要把引擎中所有卡牌行为复制到 Provider 测试。

## 15. Risks / Blockers

- **HIGH — 当前假设与仓库不符：** checkout 没有 TUI/Agent；先前关于“已有 TUI”的描述不可作为实现依据。实际需要新建应用层，但不构成引擎 blocker。
- **HIGH — Choice / Mulligan 是不同阶段：** `player.choice` 既能代表双方并存的 mulligan，也能代表单步或连续 choice。若只按普通回合的 `current_player` 取动作，会卡在开局或跳过选择。
- **HIGH — Provider / 旧 Random 策略误报完整性：** `is_playable()` 不是一份规范 Action 列表，Choose One 子项和分支 target 必须分别展开；目标要求可能受状态和卡牌脚本条件影响。现有 Random 路径直接 `.play()` 分支对象，诊断表明会让父牌留在手里；迁移时要用父牌的 `choose` 参数并覆盖回归测试。
- **HIGH — 隐藏信息泄漏：** 原始 Player/Card/observer 数据包含完整状态；`dump_hidden()` 也保留隐藏实体 ID。观察必须按 view 明确白名单。
- **HIGH（仅 replay 目标）— RNG 未统一：** 默认游戏创建没有 seed，初始职业/套牌用模块级 random，部分卡牌/Discover/Brawl helper 也会落到模块 RNG。
- **MEDIUM — Action ID 解析：** entity_id 仅单局有效，Fireplace 无直接 ID 查找；需要 session 索引和执行前状态校验。
- **MEDIUM — RandomAgent 复用有行为差异：** 旧 `play_turn` 在循环出牌时改变被遍历 hand；照搬会保留跳项风险。新策略从重新计算的 legal list 选择更稳妥。
- **MEDIUM — observer 不是现成 recorder：** observer 回调给原始引用；现有 observer 测试不验证数据并且注册太晚；需单独定义输入日志和隐私。
- **LOW — 当前质量基线：** 828 个现有测试通过，基础引擎验证较丰富；但测试命名让 `tests/full_game.py` 不被默认 pytest 文件模式收集，因此它已另行手动执行验证。项目声明支持到 Patch 17.6.0，未来卡牌数据完整性应按独立目标评估。

没有外部框架或引擎能力造成的不可克服 BLOCKER。最需要先做的是把决策协议做小、把阶段处理正确，并用实际完整对局测试。

## 16. Final Recommendation

引擎已有出牌、攻击、英雄技能、结束回合、选择和 mulligan 所需的受检方法；不应重写它们。现有项目缺的是连接这些方法的通用决策循环、合法输入/执行边界、按玩家过滤的信息，以及人类输入界面。

### NEXT IMPLEMENTATION STEP

下一轮限定为一个可审查的垂直切片：**新增轻量 Action 值类型与 phase-aware controller（普通出牌/攻击/技能/结束回合 + Choice/Discover + Mulligan），实现 ID→引擎对象解析和执行前校验；加一个最小 observation 隐私投影；将现有随机策略适配为 RandomAgent，并新增纯标准库 Human TUI，让 Human vs Random 从 mulligan 打到终局。** Provider 和 Executor 先保持函数边界，不拆成多个类；不碰 GUI、REST、LLM、规则引擎重构或确定性 replay。同步新增只测动作翻译、阶段路由、隐私和一局集成的测试。完成这条切片后，再独立决定 Action log 和 RNG/replay 的范围。
