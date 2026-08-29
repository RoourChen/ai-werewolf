# 单真人 × 6 AI 垂直闭环 — 设计 v2 与验收清单

> 状态：待审核。本文档只更新设计与验收，不含代码实现。
> 范围：1 名真人 + 6 名不同人格 AI 的 7 人局。暂不做多人、WebSocket、Admin、ASR、SQLite、部署。

## 0. 已确认硬约束

- **仅 7 人局**；任何非 7 人配置直接拒绝。
- 角色固定：**2 狼人 / 1 预言家 / 1 女巫 / 3 村民**，不加入守卫、猎人。
- **死亡不公开身份，终局统一揭晓。**
- 1 名真人 + 6 名 AI；AI 角色与人**独立随机分配**。

## 1. 人格规范（6 人格 × 6 维度，角色无关）

每个人格固化 6 个维度：**发言风格、信任倾向、风险偏好、拉票强度、改票阈值、欺骗倾向**。
数值为 0–1 归一化，方向见列名；具体值可调，但必须两两不同（避免同质化）。

| 人格 | 发言风格（固化描述） | 信任倾向<br>(0=多疑) | 风险偏好<br>(0=保守) | 拉票强度<br>(0=不强) | 改票阈值<br>(0=易改) | 欺骗倾向<br>(0=少) |
|---|---|---|---|---|---|---|
| 质疑者 | 主动找矛盾、频繁追问，不轻信身份声明 | 0.20 | 0.50 | 0.70 | 0.55 | 0.45 |
| 老好人 | 偏信任、语气友善，不轻易强推别人 | 0.80 | 0.30 | 0.25 | 0.30 | 0.20 |
| 分析家 | 重票型和前后逻辑，发言结构化、情绪较弱 | 0.45 | 0.35 | 0.45 | 0.80 | 0.35 |
| 激进派 | 结论明确、强势拉票、容忍较高决策风险 | 0.35 | 0.90 | 0.95 | 0.85 | 0.80 |
| 和事佬 | 关注阵营共识、缓和冲突，但关键时刻会归票 | 0.70 | 0.40 | 0.50 | 0.30 | 0.25 |
| 话痨 | 表达丰富、情绪化、容易制造噪声和戏剧效果 | 0.50 | 0.55 | 0.50 | 0.40 | 0.60 |

**关键约束（狼人撒谎能力）**：
- 人格与角色**独立随机分配**，不能固定绑定；映射关系按 seed 可复现并被记录。
- 所有人格拿到狼人时**都必须具备撒谎能力**，仅欺骗方式/强度不同。
- **“老好人”不得实现为永不撒谎**：其欺骗倾向为 0.20（低但 > 0）；狼人系统提示对所有人格强制追加“你必须伪装身份，必要时撒谎误导村民”，并按人格给出欺骗风格（例如老好人=用友善与信任感掩盖，而非直接攻击）。

## 2. 怀疑模型（私下真实 vs 公开立场）

每个 AI 在**每次发言、技能、投票**时，对**除自己外的每名存活玩家**输出 0–1 怀疑分：

- **private_suspicion（私下真实怀疑）**：AI 当时实际如何判断。所有决策都输出。
- **public_stance（公开立场）**：AI 准备在发言/拉票中**表现**出多怀疑对方。仅公开行为（发言、投票）输出；夜间技能无私下/公开之分，只记录 private_suspicion。
- **死亡玩家**：不进入新的评分；**历史评分保留**。
- **欺骗判定**：对每名玩家比较 `|public_stance - private_suspicion|`，超过阈值（建议 0.20）即标记为**故意欺骗**，并记录具体对象。终局可展示：“它实际只怀疑你 0.18，但公开表现为 0.82，因为它想替狼队友转移火力。”

## 3. 决策轨迹（结构化、紧凑、append-only）

### 3.1 每次只保存 7 个字段（控制延迟与成本）

1. **完整分数**：private_suspicion 全量；公开行为另存 public_stance 全量。
2. **相比上次的变化（delta）**：按 private_suspicion 相对上一次的差值。
3. **变化最大的关键对象**：delta 绝对值最大的玩家 id。
4. **证据来源**：短标签，如 `seer_result / vote_pattern / statement:P2 / pack / role_claim / none`。
5. **最终决策**：Action（目标/文本/用药）。
6. **简短依据**：一句话，不要求逐人长篇理由。
7. **欺骗标记**：是否欺骗 + 哪些玩家被欺骗性夸大/压低。

### 3.2 模型输出与编排层职责分离

- **模型只输出必要原始字段**（完整分数、简短依据、证据来源、最终决策），避免逐人生成长文理由。
- **编排层确定性计算**：delta、关键对象、欺骗标记，均由编排层根据连续记录推导，不由模型生成。

### 3.3 保存时机与不可变

- 轨迹在**决策发生时由编排层（GameSession）append-only 保存**。
- **禁止终局根据结果重新生成或修改**；实现上用 frozen 记录 + 只追加列表，并在验收中比较“运行中快照 == 终局快照”。

## 4. 差距清单（更新，精确到文件）

### G1 · 角色固定 + 移除守卫/猎人 + 仅 7 人

| 文件 | 目标 |
|---|---|
| `domain/roles.py` | `Role` 仅 `VILLAGER/WEREWOLF/SEER/WITCH`；`build_roster` 仅接受 7，固定 `2狼/1预言家/1女巫/3村民`，非 7 抛错 |
| `domain/actions.py` | 删 `NIGHT_PROTECT`、`HUNTER_SHOT` |
| `domain/referee.py` | 删守卫/猎人路径；`_night` 只跑狼/预言家/女巫 |
| `domain/rules.py` | `resolve_night_deaths` 去 `guarded` |
| `domain/events.py` | 删 `GUARD_PROTECT`、`HUNTER_SHOT` |
| `i18n.py` / `ai/persona.py` / `copilot/advisor.py` / `stats/ledger.py` | 删守卫/猎人相关文案、动作、事件、神职集合 |

### G2 · 死亡不公开身份

| 文件 | 目标 |
|---|---|
| `domain/state.py` | `reveal_role_on_death` 默认 `False` |
| `domain/referee.py` | 关闭时死亡/放逐文案不含角色名；终局仍揭晓 |

### G3 · AI 配置真正驱动机器人构建

| 文件 | 目标 |
|---|---|
| `server/room.py` | `AIConfig` 增 `provider`；`Room.start()` 无参，内部构建 6 个真实 `LLMBot` |
| `server/session.py` | 按 `RoomConfig.ai` 构建；机器人名用人格名 |
| `cli.py` | `cmd_play` 改走 `Room.add_human → Room.start()` |

### G4 · 6 人格 × 6 维度 + 独立随机分配

| 文件 | 目标 |
|---|---|
| `ai/persona.py` | 新增 `Persona`（6 维度字段）+ 6 人格注册表；`build_prompt` 注入人格 |
| `players/llm_bot.py` | `LLMBot(player_id, provider, persona)` |
| `server/session.py` | 按 seed 独立随机分配 6 人格到 6 AI 座位（与角色无关），记录映射 |
| 狼人提示 | 对所有人格追加“必须伪装/可撒谎”，老好人也不得永不撒谎 |

### G5 · 结构化决策轨迹（私下/公开双重 + 紧凑 + append-only）

| 文件 | 目标 |
|---|---|
| `players/llm_bot.py` | 产出 `DecisionRecord`（7 字段），暴露 `latest_record`；不再用覆盖式 `last_reasoning` |
| `ai/persona.py` | 扩展 JSON：`private_suspicion`、公开行为加 `public_stance`、`reasoning`(短)、`evidence`(短) |
| `ai/mock.py` | mock 按 hint 产出带怀疑分的结构化输出（离线可验收） |
| `server/session.py` | `_decide` 决策时 append 到 `traces[player]`（编排层保存，frozen 只追加） |

### G6 · 回放含轨迹、能回答“为什么怀疑我”

| 文件 | 目标 |
|---|---|
| `replay/recorder.py` | `record_session` 加入 `traces`；`replay_text` 渲染“真实 vs 公开 + 欺骗 + 理由/证据” |
| `server/session.py` | 汇总 `traces` 供 recorder 使用 |

### G7 · CLI / 内存通道跑通整局闭环

| 文件 | 目标 |
|---|---|
| `cli.py` | `cmd_play`：7 人房 → 1 真人 + `AIConfig(6 llm)` → `start()` → 终局身份揭晓 → 轨迹回放 |
| `transport/memory.py` / `conftest` | 复用 `InMemoryChannel` / `AutoChannel` |

### G8 · 端到端验收（见第 5 节）

### （仅记录，不实现）单真人 WebSocket 后续约束

- `Room.start` / `GameSession.run` 同步阻塞；WebSocket 不能简单替换 Channel。
- 后续需：后台对局任务、异步消息队列、请求-响应关联、断线/超时处理。

## 5. 验收清单

- **A1** 非 7 人配置被拒绝（`GameConfig`/`build_roster` 抛错）。
- **A2** 角色固定 2狼/1预言家/1女巫/3村民；无守卫/猎人（Role/Action/事件/文案全无）。
- **A3** 死亡与放逐事件不含角色名；终局统一揭晓全员身份。
- **A4** `Room.start()` 无参；`AIConfig(policy/model/provider)` 驱动自动构建 **6 个真实 LLMBot**（session 内 6 AI 均为 LLMBot，非 RandomBot）。
- **A5** 6 人格 × 6 维度两两不同；人格↔角色**独立随机分配**（同 seed 可复现，映射被记录）。
- **A6** 所有人格当狼都能撒谎：狼人提示对所有人格强制“必须伪装/可撒谎”；老好人欺骗倾向 > 0。
- **A7** 每次发言/技能/投票对每名存活其他玩家输出 private_suspicion(0–1)；公开行为输出 public_stance；死亡玩家不进入新评分，历史保留。
- **A8** `|public - private|` 超阈值标记故意欺骗，并记录具体玩家。
- **A9** 轨迹 7 字段齐全（完整分数/变化/关键对象/证据来源/最终决策/简短依据/欺骗标记），无逐人长文。
- **A10** 轨迹 append-only、决策时由编排层保存；终局不重算不修改（运行中快照 == 终局快照）。
- **A11** 回放能回答“为什么怀疑我”：展示某 AI 对真人玩家的 private vs public 怀疑 + 欺骗 + 理由/证据。
- **A12** 端到端：AutoChannel 真人 + 6 Mock LLMBot 完整一局，断言 A1–A11；pytest / ruff / mypy / CI 全绿。

## 6. 实施顺序（每步后跑 pytest / ruff / mypy）

1. 规则收敛（G1 + G2）。
2. 人格系统（G4：6 维度 + 独立分配 + 狼人撒谎约束）。
3. 结构化决策轨迹（G5：私下/公开双重 + 紧凑字段 + mock）。
4. AI 配置驱动构建（G3）。
5. 回放含轨迹（G6）。
6. CLI 闭环（G7）。
7. 端到端验收（G8 / A1–A12）。
8. 提交审核；通过后再设计单真人 WebSocket。

**明确不做**：多人混房、Admin、ASR、SQLite 战绩、部署。
