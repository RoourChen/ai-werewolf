# AI狼人杀 (ai-werewolf)

一款 LLM 驱动的狼人杀引擎：支持 Agent 自博弈（self-play），并为真人玩家提供**可解释的**狼人辅助（Copilot）。

An LLM-driven Werewolf (Mafia) engine: an agent self-play arena for benchmarking
models, plus an explainable copilot that helps a human player reason under
hidden information.

> **独立性声明 / Independence notice** — 本项目是基于
> [deepwolf](https://github.com/JuneQQQ/deepwolf)（参考提交
> `cc7e8f4c363f7d66d20f66d4d7479d25c842e048`）架构衍生而来的**独立项目**。
> 它使用自己的包名 `ai_werewolf`、环境变量前缀 `AIWEREWOLF_*` 与版本记录，
> 不修改也不会覆盖 deepwolf 原仓库。原作者的 MIT License 声明保留于
> [LICENSE](LICENSE)。This is an independent derivative of
> [deepwolf](https://github.com/JuneQQQ/deepwolf); it does not modify the
> upstream repository, and retains the original MIT attribution.

---

## 功能概览 / Features

| 能力 | 说明 |
| --- | --- |
| **AI 自博弈 / Self-play** | `RandomAgent` 与 `LLMAgent` 可完成完整狼人杀对局，支持中英文、固定随机种子与可复现对局。 |
| **真人游戏 / Human play** | 真人控制一个席位，其余席位由 AI 控制；Copilot 实时给出狼人概率、判断理由与投票建议。 |
| **模型评测 / Evaluation** | 批量对局，输出阵营胜率、角色存活率、Agent 胜率与排行榜；用 **Brier Score** 评估 Copilot 概率可信度。 |
| **对局记录 / Transcript** | 保存玩家、身份、事件、投票、AI 决策理由与最终结果，支持 JSON 回放与分析。 |

## 快速开始 / Quickstart

```bash
# 需要 Python 3.10+
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

默认**离线**运行（无需 API Key）：

```bash
# 观看一局 AI 自博弈
ai-werewolf simulate --players 7 --seed 1

# 中文对局
ai-werewolf simulate --players 7 --seed 1 --lang zh

# 批量评测
ai-werewolf arena --games 20 --players 7

# 排行榜
ai-werewolf leaderboard --games 20

# Copilot 概率可信度（Brier Score）
ai-werewolf calibrate --games 40

# 真人入座（你是座位 3）
ai-werewolf play --players 7 --seat 3
```

Python API 同样可用：

```python
from ai_werewolf import GameConfig, GameEngine, LLMAgent, MockProvider

provider = MockProvider(seed=0)
config = GameConfig.standard(n_players=7, seed=1)
result = GameEngine(config, lambda pid, _: LLMAgent(pid, provider)).run()
print(f"{result.winner.label} win after {result.days} day(s).")
```

## 接入真实模型 / Real models

模型层支持 OpenAI-compatible Provider：OpenAI、DeepSeek、MiMo、Groq、
OpenRouter 或任意自定义地址。API Key **只能从环境变量读取**，不会写入日志
或仓库：

```bash
cp .env.example .env
# 编辑 .env，填入 AIWEREWOLF_PROVIDER / AIWEREWOLF_API_KEY / AIWEREWOLF_MODEL

ai-werewolf simulate --provider env
```

## 架构 / Architecture

```
ai_werewolf/
├── game/          # 角色、事件、状态、规则引擎（唯一裁判，纯规则）
├── agents/        # Agent 接口、RandomAgent、LLMAgent、HumanAgent
├── llm/           # Mock 模型和 OpenAI-compatible Provider
├── prompts/       # 中英文角色与决策 Prompt
├── copilot/       # 狼人概率、理由和投票建议 + Brier 校准
├── arena/         # 批量对局、统计和排行榜
├── transcript/    # 对局保存与回放（JSON）
├── extensions/    # 新增功能（只依赖稳定接口，不污染核心规则层）
└── cli.py         # simulate、play、arena、leaderboard、calibrate
```

关键规则：`GameEngine` 是唯一裁判；Agent 只能看到 `PlayerView`；公开事件全员
可见、私密事件仅对指定玩家可见；Agent 异常/模型错误/非法目标不会中断对局，
非法决策回退到合法候选；相同 seed + 确定性 Agent 产生相同结果。

详见 [docs/architecture.md](docs/architecture.md)。

## 开发 / Development

```bash
pytest      # 单元测试
ruff check .       # 代码规范
mypy ai_werewolf   # 类型检查
```

## License

MIT，见 [LICENSE](LICENSE)。保留 deepwolf 原作者声明。
