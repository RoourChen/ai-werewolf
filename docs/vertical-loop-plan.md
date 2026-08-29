# 单真人 × 6 AI 垂直闭环 — 差距清单与实施顺序

> 状态：待审核。本文档只列差距与顺序，不含代码实现。
> 范围：1 名真人 + 6 名不同人格 AI 的一整局闭环（暂不做多人、WebSocket、Admin、ASR、SQLite、部署）。

## 目标（本次闭环验收标准）

1. 固定 7 人角色：**2 狼人 / 1 预言家 / 1 女巫 / 3 村民**，移除守卫与猎人；**死亡不公开身份**。
2. `AIConfig` 的 `policy / model / provider` 真正决定机器人构建：1 真人入座后**自动生成 6 个真实 LLMBot**，不再依赖外部 `bot_factory`。
3. 6 个**可辨识、且互不绑定身份**的人格；每个人格影响**发言风格、怀疑变化、撒谎倾向、投票策略**。
4. 每次 AI **发言/技能/投票**都保存**结构化决策轨迹**（非覆盖式 `last_reasoning`）；终局回放能回答“这个 AI 当时为什么怀疑我”。
5. 用**内存通道 / CLI** 跑通“真人加入 → 完整对局 → 身份揭晓 → 决策轨迹回放”一整局，并补**端到端验收**。

## 现状差距清单（精确到文件）

### G1 · 角色固定 + 移除守卫/猎人

| 文件 | 现状 | 目标 |
|---|---|---|
| `domain/roles.py` | `Role` 含 `GUARD`、`HUNTER`；`build_roster(7)` 产出 2狼+预言家+守卫+女巫+猎人+1村民 | `Role` 仅剩 `VILLAGER/WEREWOLF/SEER/WITCH`；`build_roster(7)` 固定为 `2狼/1预言家/1女巫/3村民`（MVP 只允许 7 人） |
| `domain/actions.py` | `ActionKind` 含 `NIGHT_PROTECT`、`HUNTER_SHOT` | 删除这两个动作（`TARGET_ACTIONS` 同步） |
| `domain/referee.py` | `_guard_protect()`、`_hunter_chain()`、`_hunter_shot_text()`；`_night` 调用守卫；`_kill_and_announce` 的 `key` 映射含 `"hunter"` | 删除守卫/猎人路径；`_night` 只跑狼/预言家/女巫 |
| `domain/rules.py` | `resolve_night_deaths(…, guarded, …)` | 去掉 `guarded` 参数 |
| `domain/events.py` | `EventKind.GUARD_PROTECT`、`HUNTER_SHOT` | 删除 |
| `i18n.py` | 守卫/猎人角色名、`guard.protect`、`hunter.shot*` 文案 | 删除 |
| `ai/persona.py` | `_ASK` 含 `night_protect`、`hunter_shot` | 删除 |
| `copilot/advisor.py` | `_confirmed_factions` 读 `HUNTER_SHOT` | 去掉 HUNTER_SHOT |
| `stats/ledger.py` | `_GOD_ROLES` 含 `GUARD/HUNTER` | 改为 `{SEER, WITCH}` |
| 相关测试 | `test_roles` 断言守卫/猎人；`test_referee` 用守卫角色写女巫用例 | 同步改写 |

### G2 · 死亡不公开身份

| 文件 | 现状 | 目标 |
|---|---|---|
| `domain/state.py` | `GameConfig.reveal_role_on_death: bool = True` | 默认 `False`（终局仍揭晓身份） |
| `domain/referee.py` | `_death_text` 已按开关分支 | 保持开关逻辑，验证关闭时死亡/放逐文案不含角色名 |

### G3 · AI 配置真正驱动机器人构建

| 文件 | 现状 | 目标 |
|---|---|---|
| `server/room.py` | `AIConfig{count, policy, model}` 缺 `provider`；`Room.start(bot_factory)` 强制外部传入工厂 | `AIConfig` 增加 `provider: Provider`；`Room.start()` 无参，内部按 `policy/model/provider` 构建 6 个 `LLMBot` |
| `server/session.py` | `GameSession` 强制 `bot_factory`，机器人名固定 `Bot{seat}` | 改为按 `RoomConfig.ai` 构建；机器人名用人格名 |
| `cli.py` | `cmd_play` 绕过 Room/Session，自建 decider | 改走 `Room.add_human → Room.start()`，由 AIConfig 自动生成 6 个真实 LLMBot |

### G4 · 6 个可辨识、互不绑定身份的人格

| 文件 | 现状 | 目标 |
|---|---|---|
| `ai/persona.py` | 只有角色 Prompt，无人格 | 新增 `Persona` 模型 + 6 个人格注册表 |
| `players/llm_bot.py` | 无 persona 字段 | `LLMBot(player_id, provider, persona)`，人格注入 system prompt |
| `server/session.py` | 无人格分配 | 按 seed 确定性地把 6 个人格分到 6 个 AI 座位（与角色无关） |

**建议 6 人格原型（均不绑定身份，狼/民通用）**：

| 人格 | 发言风格 | 怀疑倾向 | 撒谎倾向(狼) | 投票策略 |
|---|---|---|---|---|
| 质疑者 | 反问、逼问 | 高 | 中 | 独立、带头投 |
| 老好人 | 温和、相信他人 | 低 | 低 | 跟多数 |
| 分析家 | 引用票型/数据 | 中(理性) | 低 | 数据驱动 |
| 激进派 | 短句、命令式 | 中高 | 高 | 强推一人 |
| 和事佬 | 圆场、折中 | 低 | 低 | 跟风避免冲突 |
| 话痨 | 长、发散 | 波动大 | 中 | 摇摆不定 |

> 人格必须角色无关：同一人格当狼/当民都保留其风格；撒谎倾向只在“狼人且需要伪装”时生效，投票/怀疑始终体现。

### G5 · 结构化决策轨迹（非覆盖式）

| 文件 | 现状 | 目标 |
|---|---|---|
| `players/llm_bot.py` | 仅 `self.last_reasoning`（每次覆盖） | 增加 `trace: list[DecisionRecord]`，每次决策 append：`{day, phase, kind, persona, role, choice, reasoning, suspicion(对每名存活玩家的打分), fallback标志}` |
| `ai/persona.py` | 回复只要求 `choice/reasoning` | 扩展 JSON：发言含 `statement + suspicion`；技能/投票含 `choice + reasoning + suspicion` |
| `ai/mock.py` | 只回 `choice/reasoning` | mock 也按 hint 产出带 `suspicion` 的结构化输出（保证离线可验收） |

### G6 · 回放含轨迹、能回答“为什么怀疑我”

| 文件 | 现状 | 目标 |
|---|---|---|
| `replay/recorder.py` | `record_session` 只有 seats/events/chat | 加入 `traces`；`replay_text` 渲染“P3 第1天投票前 怀疑你 60%：理由…” |
| `server/session.py` | 不收集 trace | 运行后把 `players[].trace` 汇总进 session，供 recorder 使用 |

### G7 · CLI / 内存通道跑通整局闭环

| 文件 | 现状 | 目标 |
|---|---|---|
| `cli.py` | `cmd_play` 不走 Room/Session | `cmd_play`：建 7 人房 → 1 真人（终端通道）+ `AIConfig(6 llm)` → `start()` → 终局打印全员身份揭晓 → 打印决策轨迹回放 |
| `transport/memory.py` | 已有 `InMemoryChannel` | 复用；`conftest.AutoChannel` 供端到端脚本化真人 |

### G8 · 端到端验收（新增）

- 1 真人（AutoChannel）+ 6 个 `LLMBot`（MockProvider）跑完整局。
- 断言：角色=2狼/1预言家/1女巫/3村民；死亡事件无角色名；6 个 AI 由 AIConfig 构建且人格互不相同；每人每次发言/技能/投票都有结构化 trace 且含 suspicion；回放文本能回答“为什么怀疑我”。

### （仅记录，不实现）单真人 WebSocket 后续约束

- `Room.start` / `GameSession.run` 目前同步阻塞；WebSocket 不能简单替换 `Channel`。
- 后续需：后台对局任务、异步消息队列、请求-响应关联、断线/超时处理。本次不写 WebSocket。

## 实施顺序（每步完成后跑 pytest / ruff / mypy）

1. **规则收敛**：G1 + G2 → 同步改 `roles/actions/referee/rules/events/i18n/persona/advisor/ledger` 与相关测试。
2. **人格系统**：G4 → 单测“人格互异且不绑身份”。
3. **结构化决策轨迹**：G5 → 单测“trace 追加不覆盖”。
4. **AI 配置驱动构建**：G3 → 单测“自动生成真实 LLMBot”。
5. **回放含轨迹**：G6 → 单测“能回答为什么怀疑我”。
6. **CLI 闭环**：G7。
7. **端到端验收**：G8。
8. **提交审核**：全检查 + CI 绿，审核通过后再设计单真人 WebSocket。

**明确不做**：多人混房、Admin、ASR、SQLite 战绩、部署。
