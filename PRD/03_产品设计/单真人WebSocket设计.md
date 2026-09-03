# 单真人 WebSocket 设计（仅设计方案，待审核）

> 状态：设计待审核，未实现。
> 范围：严格限定 **1 名真人 + 6 名 AI**。不扩展到多真人、语音、SQLite、Admin 后台、正式前端。
> 前置：K1 真实模型技术验收已通过（`990a237` / `5c8def8`）。

## 0. 现状状态机映射（复用，不重写规则）

现有裁判状态机为 **7 相**（非 S0–S9；以实际代码为准）：

| 编号 | 相 | 迁移 | 真人可操作 |
|---|---|---|---|
| S0 | `setup` | → night | 建房/入座/开局 |
| S1 | `night` | → dawn | 狼人刀人确认 / 预言家查验 / 女巫用药 |
| S2 | `dawn` | → discussion \| finished | （无，仅看死亡） |
| S3 | `discussion` | → voting | 发言（竞价发言时先 bid） |
| S4 | `voting` | → resolution | 投票（首轮平票则限选重投） |
| S5 | `resolution` | → finished \| night | （遗言，若被放逐） |
| S6 | `finished` | ∅ | 看回放 / 删除本局 |

复用：`Room`、`GameSession`、`Referee`（唯一裁判）、`GameEvent` 的可见性（`audience=None` 即公开）、`DecisionRecord` 决策轨迹、`record_session` 回放、AI 超时/重试/兜底（`LLMBot`/`Provider`）。

## 1. 推荐架构

```
浏览器/客户端(WebSocket)
        │  wss://…/ws?token=…
        ▼
┌─────────────────────────────────────────────┐
│  WebSocket 层（新增，不碰规则）              │
│  - 鉴权/绑定 (room_id, seat_id, token)      │
│  - 消息编解码、路由、超时、断线重连          │
│  - 每房事件日志（append-only, event_id 递增）│
│  - 每房一个顺序对局任务                      │
└──────────────┬──────────────────────────────┘
               │ 线程安全队列 + loop.call_soon_threadsafe
               ▼
┌─────────────────────────────────────────────┐
│  现有同步 GameSession（后台线程，每房一个）  │
│  Room + Referee + HumanPlayer(QueueChannel) │
│  + 6 个 LLMBot + make_traced_decider        │
└─────────────────────────────────────────────┘
```

**关键决策（推荐）**：保留现有**同步** `GameSession.run()` 不变，把它放进**每房一个后台线程**；
真人输入通过**线程安全队列**串行送入状态机；服务端事件通过 `loop.call_soon_threadsafe` 推回
asyncio 连接。这样不复制规则、不改裁判，WebSocket 只负责连接/鉴权/消息/超时/恢复。

- 单机单事件循环（asyncio + uvicorn/FastAPI，已在 `server` extra）。
- 每房一个对局线程 + 一个 `queue.Queue`（真人动作）+ 一个事件日志。

## 2. 完整消息类型表

统一信封：`{"type": "...", "seq": 123, "ts": "...", "data": {...}}`
（`seq` 为服务端每房严格递增的投递序号，用于补发）。

### 2.1 客户端 → 服务端（命令）

| type | 说明 | 关键字段 |
|---|---|---|
| `create_room` | 创建房间 | → `room_id` |
| `join` | 加入并绑定座位 | `room_id` → `seat_id`,`token` |
| `start` | 开局 | `room_id` |
| `action` | 提交一个操作 | `request_id`,`client_action_id`,`kind`,`target`/`text`/`heal`/`poison`/`priority` |
| `replay` | 查看 AI 心理回放 | `room_id` |
| `delete` | 删除本局记录 | `room_id` |
| `ping` | 保活 | — |

### 2.2 服务端 → 客户端（事件/响应）

| type | 说明 | 关键字段 |
|---|---|---|
| `room_created` | 建房成功 | `room_id` |
| `joined` | 入座成功 | `room_id`,`seat_id`,`token` |
| `game_started` | 公开：开局 | `seats`,`role_counts` |
| `public_event` | 公开事件（夜晚/清晨/发言/投票/放逐/遗言/终局） | `event_id`,`kind`,`day`,`text`,`actor`,`target` |
| `private_event` | 私密事件（身份/狼队友/查验/女巫） | `event_id`,`kind`,`day`,`text`,`data` |
| `decision_request` | 等待真人操作 | `request_id`,`kind`,`legal_targets`,`can_heal`,`can_poison`,`suggestions`,`deadline_ms`,`prompt`,`copilot` |
| `action_ack` | 操作确认 | `request_id`,`client_action_id`,`accepted` |
| `ai_processing` | AI 处理中（旋转状态） | `phase`,`status` |
| `error` | 明确错误 | `code`,`message`,`request_id?`,`client_action_id?` |
| `timeout` | 真人超时，已确定性兜底 | `request_id`,`fallback` |
| `game_over` | 终局结算 | `winner`,`days`,`seats` |
| `replay` | 心理回放（事件 ID 可反查） | `replay`（复用 `record_session`） |
| `deleted` | 已删除本局 | `room_id` |
| `reconnected` | 重连成功并补发 | `last_event_id`,`replayed_count` |

### 2.3 `error` 错误码

| code | 含义 |
|---|---|
| `unauthorized` | token 无效/过期 |
| `forbidden` | 越权（读私密/替他人操作） |
| `stale_request` | request_id 不匹配/已过期 |
| `duplicate_action` | client_action_id 重复提交 |
| `illegal_target` | 目标非法（非存活/非本座合法目标） |
| `wrong_phase` | 当前状态机不接受该操作 |
| `room_not_found` / `room_already_started` | 房间状态错误 |
| `server_error` | 内部错误（不泄露 Key） |

## 3. 一局对战时序流程（1 真人 + 6 AI）

```
C                       WS/服务端                    对局线程(Referee)
│ create_room ─────────▶│ room_created ◀─────────────┘
│ join ────────────────▶│ joined(seat=0, token)      │
│ start ───────────────▶│ 开对局线程 ────────────────▶│ run()
│        ◀──────────────│ game_started(公开)          │ S0→S1
│        ◀──────────────│ private_event(你的身份)      │ role_dealt
│        ◀──────────────│ private_event(狼队友,若狼)   │ pack_mates
│ S1 夜：              │                             │
│  (若真人狼) ◀─────────│ decision_request(确认刀人)   │ 等待真人
│  action(P3) ─────────▶│ action_ack ───────────────▶│ 入队→确认
│        ◀──────────────│ private_event(狼队刀 P3)    │ wolf_kill
│  (AI 预言家/女巫)     │ ai_processing ─────────────▶│ LLMBot 决策
│        ◀──────────────│ (若真人预言家/女巫)          │
│        ◀──────────────│ decision_request(查验/用药) │ 等待真人
│ S2 晨： ◀─────────────│ public_event(死亡/平安夜)   │ dawn
│ S3 讨论：             │                             │
│  (AI 发言) ◀──────────│ public_event(statement)     │ 依次
│  (真人发言) ◀─────────│ decision_request(发言)      │ 等待真人
│ S4 投票： ◀───────────│ decision_request(投票)      │ 等待真人
│  (若平票) ◀───────────│ public_event(重投说明)      │ 限选重投
│  (被放逐) ◀───────────│ decision_request(遗言)      │ 等待真人
│ S5/S6： ◀─────────────│ public_event(放逐/遗言/终局) │ game_over
│ replay ──────────────▶│ replay(轨迹)               │ record_session
│ delete ──────────────▶│ deleted                    │ 清理线程+日志
```

## 4. 断线重连方案

1. 每次连接建立后，服务端给该 `(room_id, seat_id)` 发一个**新的临时连接**，但座位仍归原 `seat_id`。
2. 服务端为该座位维护 **append-only 事件日志**（每房单调递增 `event_id`，含公开+该座位私密事件）。
3. 客户端重连时发送 `reconnect {room_id, seat_id, last_event_id}`：
   - 校验 `token`（每次 `join` 后由服务端签发，重连时需携带或重新 join）。
   - 服务端把 `event_id > last_event_id` 且该座位可见的事件按序补发。
   - 回 `reconnected {last_event_id, replayed_count}`。
4. 断线宽限期（建议 60s）：宽限期内对局继续，真人操作按**超时兜底**执行；超宽限期后座位判为“已离场”，后续该座全部走确定性兜底，仍可重连看回放，但不能继续操作。
5. 断线期间不丢 `event_id`：事件日志只追加，重连从 `last_event_id` 续上。

## 5. 超时与幂等规则

### 5.1 超时（每类真人操作，可配置）

| 操作 | 建议超时 | 兜底 |
|---|---|---|
| 白天发言 | 30s | “放弃发言” |
| 投票 / 重投 | 20s | 合法候选中的确定性选择（按 seed） |
| 狼人确认刀人 | 20s | AI 建议的确定性兜底（`PACK_CONFIRM` fallback） |
| 预言家查验 / 女巫用药 | 20s | 不查验 / 不用药 |
| 遗言 | 30s | “放弃遗言” |
| 竞价发言 bid | 10s | priority=5 |

兜底逻辑**已存在于 `Referee`**（decider 抛错→`_fallback`）；WebSocket 层只需把超时转换成“入队超时”，让 `HumanPlayer.decide` 抛 `TimeoutError`。

### 5.2 幂等与关联

- `request_id`（服务端生成）唯一标识一次操作请求；`action` 必须回带当前 `request_id`，否则 `stale_request`。
- `client_action_id`（客户端生成）保证重复提交幂等：同一 `client_action_id` 只处理一次，重复 → `duplicate_action`。
- 非法/过期/重复请求只回 `error`，**不改变状态机**；不会因网络重发导致“一票两投”或“重复用药”。

## 6. 权限矩阵

| 能力 | 真人座位(seat 0) | 其他座位(AI) | 服务端 |
|---|---|---|---|
| 读自己私密事件（身份/查验/女巫/狼队友） | ✅ | ✗ | — |
| 读公开事件 | ✅ | ✅(不发客户端) | — |
| 提交自己座位的操作 | ✅ | ✗ | 复验合法性 |
| 提交他人座位的操作 | ✗ | ✗ | 拒绝 `forbidden` |
| 读取 API Key | ✗ | ✗ | 仅服务端，永不下发 |
| 读取终局回放（决策轨迹） | ✅(仅终局后) | ✗ | — |
| 删除本局记录 | ✅(本局创建者) | ✗ | — |

服务端对每个 `action` **重新验证**：`request.actor == seat_id`、目标在 `legal_targets`、当前 phase 匹配、药水可用性、狼人只能刀存活非狼等（复用 `Referee._sanitize`）。

## 7. 测试清单

自动化（离线 Mock + 脚本人类）：
1. 正常完成一局（create→join→start→…→game_over→replay→delete）。
2. 真人狼：AI 建议 → 真人确认刀人；确认覆盖建议、超时走确定性兜底。
3. 真人预言家查验：请求/响应/私密结果只回本座。
4. 真人女巫用药：合法单药、非法双药拒绝、自毒/毒死者拒绝。
5. 投票平票 → 限选重投 → 二次平票无人放逐。
6. 重复提交：同 `client_action_id` 只生效一次。
7. 非法目标：回 `illegal_target`，状态机不变。
8. 超时兜底：每类操作超时后走确定性兜底，对局不中断。
9. 中途断线重连：从 `last_event_id` 补发遗漏事件，序号连续。
10. 私密事件越权：AI 座位/未授权 token 读不到私密事件。
11. 终局回放与原始事件一致（`replay` 与事件日志逐条比对）。
12. 非法/过期/重复请求返回明确错误且不破坏状态机。
13. API Key 绝不出现在任何下行消息或回放中。

真实模型人工验收（待本机 Key）：
14. 真实 DeepSeek 跑通一局；断线重连补发正确；回放可读。

## 8. 明确不做的范围

- 多真人混房、“谁是 AI”模式。
- 语音（ASR/TTS）。
- SQLite 战绩持久化、Admin 后台。
- 正式前端页面（仅设计协议；可用最小测试客户端验证）。
- 不复制第二套狼人杀规则（复用 `Referee`）。
- 不做真人账号体系/登录（单机 token 绑定座位即可）。

## 9. 需要你确认的决策点

1. **WebSocket 框架**：建议 `FastAPI + uvicorn`（已在 `server` extra）；是否接受？
2. **线程模型**：建议“每房一个后台线程跑同步 GameSession + 线程安全队列 + `loop.call_soon_threadsafe`”，避免把同步裁判改成全异步；是否接受？
3. **超时时长**：上表建议值（发言30s/投票20s/夜间20s/遗言30s/竞价10s）是否采纳？
4. **断线宽限期**：建议 60s，超期座位永久走兜底但仍可看回放；是否采纳？
5. **接口形态**：建议“全 WebSocket + 一个 REST `/health`”；是否需要 REST `create_room`？
6. **`delete` 语义**：删除内存房间+事件日志，并删除 `acceptance/` 下本局 transcript？30 天保留规则如何适用？
7. **`event_id` 粒度**：建议“每房间递增”（一房一局）；是否需要全局递增？
8. **回放权限**：仅终局后可读，还是讨论中也可看自己座位的历史？

设计完成后停在此处等待审核，不进入实现。
