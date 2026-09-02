# deepwolf 对比分析

> 归属：07_竞品分析

## 1. 定位对比

| 维度 | deepwolf | AI狼人杀（ai-werewolf） |
|---|---|---|
| 定位 | LLM 狼人杀引擎：自博弈竞技场 + 可解释人类 Copilot | 面向**真人与 AI 多智能体对战**的狼人杀平台 |
| 对局形态 | Agent 自博弈（自玩）为主 | 1 真人 + 6 人格化 AI 的房间制对局 |
| 辅助 | 概率 Copilot | Copilot + 三通道怀疑 + 决策轨迹回放 |

## 2. 架构与实现差异

| 维度 | deepwolf | ai-werewolf |
|---|---|---|
| 目录结构 | `game/agents/llm/prompts/copilot/arena/transcript` | `domain/players/ai/server/transport/replay/stats/copilot` |
| 裁判 | `GameEngine` 循环 | 显式状态机 `Referee`（带迁移表，非法迁移拒绝） |
| 真人 | CLI 内 `HumanAgent` | `HumanPlayer` + `Channel` 传输抽象 |
| 房间/匹配 | 无 | `Room` + `Matchmaker` |
| 轨迹 | 仅 `last_reasoning` 覆盖式 | `DecisionRecord` 三通道 + 欺骗计划，append-only 不可变 |
| 角色 | 含守卫、猎人 | MVP 仅 2狼/1预言家/1女巫/3村民 |

## 3. 独立性声明

- 本项目**受 deepwolf 启发**，但**未复用其源码、测试、Prompt 或目录结构**。
- 具体声明见仓库根目录 `THIRD_PARTY_NOTICES.md`（保留 deepwolf MIT 声明备查）。

## 4. 待补充

- 其他 LLM 狼人杀/社交推理项目（如 WOLF benchmark 等）的横向对比。
- 真实模型下的胜率、延迟、成本对标。
