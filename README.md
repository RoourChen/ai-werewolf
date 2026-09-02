# AI狼人杀 (ai-werewolf)

> 一款 LLM 驱动的狼人杀引擎：支持 Agent 自博弈（self-play）与真人多智能体对战，
> 并为真人玩家提供**可解释的**狼人辅助（Copilot）。

> An LLM-driven Werewolf (Mafia) engine for human-vs-AI multi-agent play, with an
> explainable copilot for human players.

**本项目受 deepwolf 启发，是面向真人与 AI 多智能体对战场景的独立实现。**
（This project is inspired by [deepwolf](https://github.com/JuneQQQ/deepwolf) and is
an independent implementation for human-vs-AI multi-agent play.）

deepwolf 仅用于理解产品能力与玩法；本项目未复用其源码、测试、Prompt 或目录结构。
对本项目实际复用的任何第三方 MIT 代码，版权与许可证统一记录于
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## 与参考项目的区别 / Product differentiation

AI狼人杀不是 deepwolf 的移植，而是一个**面向多人在线对战**的独立产品，核心差异：

| 能力 | 说明 |
| --- | --- |
| 🏠 房间与匹配系统 | `Room` 房间生命周期（开放→就绪→对局→结束），`Matchmaker` 匹配队列自动成房。 |
| 👥 真人多人对局 | 多个真人席位通过 `Channel` 传输接入，其余席位由 AI 补齐。 |
| 🤖 AI 玩家配置 | `AIConfig` 按房间配置 AI 数量、策略（random/llm）与模型。 |
| 💬 实时语音/文字讨论 | 讨论阶段支持实时文字与语音帧消息，广播到全员与观战者。 |
| ⚖️ 裁判状态机 | `Referee` 是显式状态机：准备→夜晚→清晨→讨论→投票→结算→结束，非法迁移被拒绝。 |
| 👀 观战回放 | 对局事件流 + 实时聊天，可保存为 JSON（`ai-werewolf.replay/v1`）并回放。 |
| 🏆 战绩体系 | `StatsLedger` 记录胜率、角色数据、排行榜与成就徽章。 |
| 🛠️ 管理后台 | `AdminBackend` 提供房间列表、踢人、关房、服务器统计与 Bot 池管理。 |

## 快速开始 / Quickstart

```bash
# Python 3.10+
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

默认离线运行（无需 API Key）：

```bash
# 观看一局 AI 自博弈
ai-werewolf simulate --players 7 --seed 1

# 真人入座（你是座位 3，其余为 AI，Copilot 实时辅助）
ai-werewolf play --players 7 --seat 3

# 批量评测机器人策略
ai-werewolf arena --games 20 --bots random

# Copilot 概率校准（Brier Score）
ai-werewolf calibrate --games 40

# 回放保存的对局
ai-werewolf simulate --transcript game.json --seed 1
ai-werewolf replay game.json
```

Python API：

```python
from ai_werewolf import GameConfig, Referee, RandomBot, build_roster

def decider(view, request):
    return RandomBot(request.actor).decide(view, request)

state = Referee(GameConfig(roster=build_roster(7), seed=1), decider).run()
print(state.winner, "在", state.day, "天后获胜")
```

## 架构 / Architecture

```
ai_werewolf/
├── domain/        # 纯领域：角色、动作、事件、规则、裁判状态机（无 I/O）
├── players/       # 玩家策略：RandomBot、LLMBot、HumanPlayer（经 Channel）
├── ai/            # 模型适配：Provider、OpenAI 兼容、Mock、角色 Prompt
├── copilot/       # 真人辅助：狼人概率/理由/投票建议 + Brier 校准
├── server/        # 房间、匹配、对局会话、管理后台
├── transport/     # 传输抽象：Channel 协议 + 内存实现（可替换为 WebSocket）
├── replay/        # 观战回放：记录、保存、加载、回放
├── stats/         # 战绩体系：胜率、排行榜、成就
├── benchmark.py   # 批量评测
├── app.py         # 可选 FastAPI 适配器（pip install 'ai-werewolf[server]'）
└── cli.py         # simulate、play、arena、calibrate、replay
```

关键原则：`Referee` 是唯一裁判且为纯状态机；玩家只能看到 `PlayerView`；公开事件
全员可见、私密事件仅对授权玩家可见；非法动作回退到合法候选；相同 seed + 确定性
策略产生相同结果；新功能放在 server/transport 等应用层，不污染 domain 核心。

详见 [PRD/03_产品设计/架构设计.md](PRD/03_产品设计/架构设计.md)。

## 接入真实模型 / Real models

模型层支持 OpenAI-compatible Provider（OpenAI、DeepSeek、MiMo、Groq、OpenRouter
或自定义地址）。API Key **只能从环境变量读取**：

```bash
cp .env.example .env   # 填入 AIWEREWOLF_PROVIDER / AIWEREWOLF_API_KEY / AIWEREWOLF_MODEL
ai-werewolf simulate --provider env
```

## 开发 / Development

```bash
pytest              # 单元测试
ruff check .        # 代码规范
mypy ai_werewolf    # 类型检查
```

## License

MIT，见 [LICENSE](LICENSE)。第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
