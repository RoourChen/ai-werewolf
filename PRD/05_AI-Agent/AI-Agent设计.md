# AI-Agent 设计

> 归属：05_AI-Agent

## 1. 人格（6 人格 × 6 维度，角色无关）

| 人格 | 信任基线 | 证据敏感度 | 风险偏好 | 拉票强度 | 改票阻力 | 欺骗倾向 |
|---|---:|---:|---:|---:|---:|---:|
| 质疑者 | 0.25 | 0.75 | 0.55 | 0.65 | 0.60 | 0.45 |
| 老好人 | 0.80 | 0.45 | 0.25 | 0.25 | 0.30 | 0.20 |
| 分析家 | 0.45 | 0.90 | 0.30 | 0.45 | 0.75 | 0.30 |
| 激进派 | 0.30 | 0.55 | 0.90 | 0.90 | 0.70 | 0.55 |
| 和事佬 | 0.70 | 0.60 | 0.20 | 0.20 | 0.35 | 0.25 |
| 话痨 | 0.50 | 0.40 | 0.65 | 0.60 | 0.40 | 0.65 |

- 每局按 seed 对各维度加 ±0.03 确定性扰动；人格与身份**独立随机分配**。
- 参数是行为倾向，不是硬编码概率；决策优先级：游戏合法性 > 阵营目标 > 人格倾向。
- 所有人格拿到狼人都允许撒谎，仅方式与强度不同（老好人欺骗倾向 0.20，绝不设为 0）。

## 2. 怀疑模型（三通道）

- `private_suspicion`：AI 实际认为对方是狼人的概率；狼人此通道恒为 0/1（知识而非信念）。
- `public_suspicion`：AI 在发言/拉票/投票中公开表现出的怀疑（仅公开行为）。
- `strategic_threat`：对方对自身阵营的威胁程度（尤其供狼人使用）。

## 3. 欺骗判定

- 阈值 0.20，且必须**主动标记**并给出完整计划（对象/公开说法/目的/真实依据）。
- 分差 < 0.20 时需引用可验证的 `fabricated_event`（可见事件 ID）。
- 不一致（分差无标记、标记无分差、目标无效、计划不完整）→ 重试一次 → 合法兜底。

## 4. 决策协议与轨迹

- 输入：`Prompt(system, user, hint)`；`hint` 携带 role/pack/others/persona/event_ids 等。
- 输出：严格 JSON（choice/statement/heal/poison + 三通道分数 + evidence + confidence + deception）。
- 校验：怀疑分键集合精确完整且为 0-1 数值；evidence 必须是真实可见事件 ID。
- 轨迹：`DecisionRecord` 不可变快照，编排层决策时 append-only 保存。

## 5. Provider

- `MockProvider`（离线确定性，persona-aware，狼人产生真实欺骗记录）。
- `OpenAICompatProvider`（openai/deepseek/mimo/groq/openrouter/自定义）。
- `AIConfig.resolve_provider`：显式 provider > model（env 构建）> mock。
