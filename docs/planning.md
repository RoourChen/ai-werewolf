# AI狼人杀（ai-werewolf）— 独立实现架构文档（v0.2）

> 状态：已完成独立重写并推送（本地完成架构、测试与产品差异化后再提交，未强制覆盖历史）
> 灵感来源：https://github.com/JuneQQQ/deepwolf（仅用于理解产品能力与玩法，未复用其源码/测试/Prompt/目录结构）
> 仓库：https://github.com/RoourChen/ai-werewolf
> README 准确表述：**本项目受 deepwolf 启发，是面向真人与 AI 多智能体对战场景的独立实现。**

---

## 一、产品定位（一句话）

**AI狼人杀** 是一款面向**真人与 AI 多智能体对战**的狼人杀引擎：既支持 Agent 自博弈
（self-play）用于模型评测，也支持真人多人入座 + 实时文字/语音讨论，并为真人玩家
提供**可解释的**狼人辅助（Copilot）。

## 二、与参考项目（deepwolf）的关系

- deepwolf 只用于理解产品能力与玩法，**未复制其源码、测试、Prompt 或目录结构**。
- 本项目是全新设计：`domain/server/players/transport/replay/stats/copilot/ai` 分层，
  与 deepwolf 的 `game/agents/llm/prompts/copilot/arena/transcript` 目录结构完全不同。
- 实际复用的第三方 MIT 代码统一记录于 `THIRD_PARTY_NOTICES.md`（当前为“无源码级复用”，
  仅记录 deepwolf 为灵感来源及其 MIT 声明）。
- 保留原版权声明：deepwolf 的 MIT License 文本收录于 `THIRD_PARTY_NOTICES.md`。

## 三、八大产品差异点（重点区别于参考项目）

| # | 差异点 | 实现 |
|---|---|---|
| 1 | 房间与匹配系统 | `server/room.py` 房间生命周期（OPEN→READY→PLAYING→FINISHED）；`server/matchmaking.py` 匹配队列自动成房 |
| 2 | 真人多人对局 | `players/human.py` 真人席位经 `transport/Channel` 接入；`server/session.py` 支持多个真人席位 + AI 补位 |
| 3 | AI 玩家配置 | `server/room.py` 的 `AIConfig`（数量、策略 random/llm、模型）按房间配置 |
| 4 | 实时语音/文字讨论 | `server/session.py` 的 `post_chat`（text/voice 帧）+ 全员/观战者广播 |
| 5 | 裁判状态机 | `domain/referee.py` 显式状态机：SETUP→NIGHT→DAWN→DISCUSSION→VOTING→RESOLUTION→FINISHED，非法迁移抛 `InvalidTransition` |
| 6 | 观战回放 | `replay/recorder.py` 记录/保存/加载/回放（`ai-werewolf.replay/v1`）；`session.add_spectator` 观战流 |
| 7 | 战绩体系 | `stats/ledger.py` 胜率、角色数据、排行榜、成就徽章 |
| 8 | 管理后台 | `server/admin.py` 房间列表、踢人、关房、服务器统计、Bot 池管理 |

## 四、架构分层

```
cli / app       cli.py, app.py         唯一做 I/O 的层
 ├─ benchmark   benchmark.py           批量评测
 ├─ stats       stats/                 战绩/排行榜/成就
 ├─ replay      replay/                观战/记录/回放
 ├─ server      server/                房间/匹配/会话/后台
 │    ├─ players   players/            RandomBot/LLMBot/HumanPlayer
 │    ├─ transport transport/          Channel 抽象 + 内存实现（可换 WebSocket）
 │    └─ ai        ai/                 Provider/Mock/人设 Prompt
 ├─ copilot     copilot/              可解释辅助 + Brier 校准
 └─ domain      domain/               纯规则 + 裁判状态机（无 I/O）
```

## 五、核心数据流

```
用户/客户端 → Matchmaker/房间 → Room.start()
→ GameSession 构建玩家（真人经 Channel + AI）
→ Referee 状态机按阶段产生 DecisionRequest
→ build_view() 生成 PlayerView（只含可见信息）
→ 玩家 decide() 返回 Action
→ Referee 校验（非法回退到合法候选）
→ 写入事件流（公开/私密 audience）→ 广播
→ 输出 GameState / replay / 战绩
```

## 六、关键规则（均实现并有测试）

- `Referee` 是唯一裁判，且为显式状态机，非法阶段迁移被拒绝。
- 玩家只能看到 `PlayerView`；公开事件全员可见，私密事件仅授权玩家可见。
- Agent/模型错误、非法目标不中断对局，非法决策回退到合法候选。
- 相同 seed + 确定性策略产生相同结果（事件级复现）。
- 核心不处理 UI/网络/终端；这些都在 transport/cli/app 层。

## 七、验收结果

| # | 项 | 结果 |
|---|---|---|
| 1 | 本地完成架构、测试与产品差异化后再提交 | ✅ |
| 2 | 未强制覆盖 GitHub 历史（快进推送 `5296800..af5fd90`） | ✅ |
| 3 | 未启用 GitHub Actions，保留 `docs/ci.yml.example` | ✅ |
| 4 | README 使用准确表述（受启发 + 独立实现） | ✅ |
| 5 | THIRD_PARTY_NOTICES.md 记录 MIT 复用与 deepwolf 声明 | ✅ |
| 6 | 8 大产品差异点全部落地 | ✅ |
| 7 | pytest 80 通过 / ruff 0 问题 / mypy 0 问题 | ✅ |
| 8 | 离线可运行；中英文均可；CLI 与 Python API 均可用 | ✅ |
| 9 | 推送到新仓库，未修改 deepwolf 原仓库 | ✅ |

## 八、与 0.1 版（已废弃）的区别

0.1 版是 deepwolf 的换皮移植，已按新要求整体删除并重写为 0.2 独立实现；
历史通过新提交保留（未 force push）。
