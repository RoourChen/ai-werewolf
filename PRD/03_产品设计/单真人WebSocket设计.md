# 单真人 WebSocket 设计 v2（最终审核稿）

> 状态：设计已定稿，已实现（实现以第 10 节最终产品决策为准）。
> 范围：严格限定 **1 名真人 + 6 名 AI**。不扩展到多真人、语音、SQLite、Admin 后台、正式前端。
> 前置：K1 真实模型技术验收已通过。

## 0. 已确认决策（9 项）

1. WebSocket 框架：**FastAPI + uvicorn**。
2. 线程模型：**每房一个后台线程 + 线程安全队列 + loop.call_soon_threadsafe**；增加**活跃房间上限、结束回收、异常回收**。
3. 操作超时：发言 30s、投票 20s、夜间 20s、遗言 30s、竞价 10s，**全部可配置**。
4. 断线宽限：**60s**；宽限期内可恢复操作；超期进入**永久自动兜底模式**，只能观战 + 查看终局回放。
5. 接口形态：**全 WebSocket**，仅保留 REST `/health`；本阶段不增加 REST 建房。
6. 删除语义：**仅终局后允许删除**；删除立即、不可恢复地清除内存房间 + 事件日志 + 本局 transcript；未主动删除则 **30 天自动过期**。
7. 编号粒度：`domain_event_id` **按房间递增**，不需要全局递增。
8. 回放权限：AI 心理活动与决策轨迹**仅终局后开放**；对局中只能查看已接收的公开历史 + 本人私密历史。
9. Token：`create_room` 返回**一次性 `join_secret`**（服务端只保存摘要，`join` 必须提交，验证成功后立即作废）；随后签发**密码学安全随机会话 Token**，绑定 `room_id` + `seat_id`，仅本局有效，用于 `reconnect` 鉴权；**禁止放 WebSocket URL 查询参数**；服务端**只保存摘要**，不写日志。

## 1. 推荐架构（含容量与回收）

```
浏览器/客户端(WebSocket, 校验 Origin)
        │  wss://…/ws  (token 不放在 URL)
        ▼
┌──────────────────────────────────────────────┐
│  WebSocket 层（新增，不碰规则）              │
│  - 鉴权(join/reconnect 消息提交 token)       │
│  - 消息编解码/大小/频率限制、超时、断线重连   │
│  - 每房 append-only 下行日志(stream_seq 递增) │
│  - 每房一个顺序对局线程；房间上限与回收        │
└──────────────┬───────────────────────────────┘
               │ 线程安全队列 + loop.call_soon_threadsafe
               ▼
┌──────────────────────────────────────────────┐
│  现有同步 GameSession（后台线程，每房一个）  │
│  Room + Referee + HumanPlayer(QueueChannel)  │
│  + 6 个 LLMBot + make_traced_decider         │
└──────────────────────────────────────────────┘
```

**容量与回收（MVP）**：
- `MAX_ACTIVE_ROOMS`（默认 10，可配置）；达到上限后 `create_room` 返回 `room_capacity_reached`。容量只统计 `created/joined/running`；`finished` 立即释放线程与队列容量；未开局房间空闲 **10 分钟**自动过期。
- 每房**只能有一个**对局线程；`finished` 后回收线程引用、消息队列、连接集合。
- 异常（线程抛错/断线异常）不强杀线程：**自动兜底让对局自然结束**，再回收资源（Python 线程不可安全强杀）。
- 房间生命周期：`created → joined → running → finished → deleted/expired`。

## 2. 完整消息类型表

统一信封：`{"type": "...", "stream_seq": 123, "ts": "...", "data": {...}}`

- `stream_seq`：**只分配给需要断线恢复的持久下行消息**，按房间严格递增（用于断线补发），与游戏无关；含 token 的 `room_created`/`joined`、`ping`/`pong`、`ai_processing`、普通 `error`、`reconnected` 不进入 append-only 日志，不分配 `stream_seq`。
- `domain_event_id`：**仅 GameEvent** 使用（在 `public_event`/`private_event` 的 `data` 内），用于规则事件与心理回放证据反查。
- 两者独立；私密消息被过滤导致 `stream_seq` 跳号是正常现象。

### 2.1 客户端 → 服务端（命令）

| type | 说明 | 关键字段 |
|---|---|---|
| `create_room` | 创建房间（返回一次性 join_secret） | → `room_id`,`join_secret` |
| `join` | 首次入座并鉴权 | `room_id`,`join_secret` → `seat_id`,`session_token` |
| `reconnect` | 断线重连并鉴权 | `room_id`,`seat_id`,`session_token`,`last_stream_seq` |
| `start` | 开局（仅房主） | `room_id` |
| `action` | 提交一个操作 | `request_id`,`client_action_id`,`kind`,`target`/`text`/`heal`/`poison`/`priority` |
| `replay` | 查看 AI 心理回放（仅终局+房主） | `room_id` |
| `delete` | 删除本局（仅终局+房主） | `room_id` |
| `ping` | 保活 | — |

### 2.2 服务端 → 客户端（事件/响应）

| type | 说明 | 关键字段 |
|---|---|---|
| `room_created` | 建房成功 | `room_id` |
| `joined` | 入座成功（含 session_token） | `room_id`,`seat_id`,`session_token` |
| `game_started` | 公开：开局 | `seats`,`role_counts` |
| `public_event` | 公开规则事件 | `domain_event_id`,`kind`,`day`,`text`,`actor`,`target` |
| `private_event` | 私密规则事件（本座可见） | `domain_event_id`,`kind`,`day`,`text`,`data` |
| `decision_request` | 等待真人操作 | `request_id`,`kind`,`legal_targets`,`can_heal`,`can_poison`,`suggestions`,`deadline_ms`,`prompt`,`copilot` |
| `action_ack` | 操作确认 | `request_id`,`client_action_id`,`accepted` |
| `ai_processing` | AI 处理中 | `phase`,`status` |
| `timeout` | 真人超时，已兜底 | `request_id`,`fallback` |
| `error` | 明确错误 | `code`,`message`,`request_id?`,`client_action_id?` |
| `game_over` | 终局结算 | `winner`,`days`,`seats` |
| `replay` | 终局回放（事件 ID 可反查） | `replay` |
| `deleted` | 已删除本局 | `room_id` |
| `reconnected` | 重连成功并补发 | `latest_stream_seq`,`replayed_count` |

### 2.3 `error` 错误码

| code | 含义 |
|---|---|
| `unauthorized` | token 无效/过期 |
| `forbidden` | 越权（读私密/替他人操作） |
| `not_owner` | 非房主执行 start/replay/delete |
| `not_finished` | 未终局执行 replay/delete |
| `seat_taken` | 单真人座位已被占，其他 join 拒绝 |
| `stale_request` | request_id 不匹配/已过期 |
| `idempotency_conflict` | 相同 `client_action_id` + 不同内容（同 ID 同内容直接返回首次缓存结果，不报错） |
| `illegal_target` | 目标非法 |
| `wrong_phase` | 状态机不接受该操作 |
| `room_capacity_reached` | 活跃房间数达上限 |
| `room_not_found` / `room_already_started` | 房间状态错误 |
| `message_too_large` / `rate_limited` | 消息大小/频率超限 |
| `server_error` | 内部错误（不泄露 Key/身份/token） |

## 3. 一局对战时序流程

```
C                       WS/服务端                    对局线程(Referee)
│ create_room ─────────▶│ room_created ◀─────────────┘
│ join(join_secret) ───▶│ joined(seat=0, session_token) │
│ start ───────────────▶│ 开对局线程 ────────────────▶│ run()
│        ◀──────────────│ game_started(公开)          │ S0→S1
│        ◀──────────────│ private_event(你的身份)      │ role_dealt
│        ◀──────────────│ private_event(狼队友,若狼)   │ pack_mates
│ S1 夜：              │                             │
│  (若真人狼) ◀─────────│ decision_request(deadline)   │ 等待真人
│  action(P3) ─────────▶│ action_ack ───────────────▶│ 入队→确认
│        ◀──────────────│ private_event(狼队刀 P3)    │ wolf_kill
│  (AI 行动)           │ ai_processing ─────────────▶│ LLMBot 决策
│ S2 晨： ◀─────────────│ public_event(死亡/平安夜)   │ dawn
│ S3 讨论： (AI/真人发言)│ public_event / decision_request │
│ S4 投票： ◀───────────│ decision_request(deadline)  │
│  (平票) ◀─────────────│ public_event(重投)          │ 限选重投
│  (被放逐) ◀───────────│ decision_request(遗言)      │
│ S5/S6： ◀─────────────│ public_event(放逐/遗言/终局) │ game_over
│ replay ──────────────▶│ (校验 finished+房主) replay │ record_session
│ delete ──────────────▶│ deleted(清内存/日志/transcript) │
```

## 4. 断线重连方案（基于 stream_seq）

1. 服务端为每房维护 **append-only 下行日志**，每条带 `stream_seq`（严格递增）与可见性。
2. 客户端断线后重连：发 `reconnect {room_id, seat_id, session_token, last_stream_seq}`。
3. 服务端校验 token 摘要与 seat 归属，在**锁内**取当前 high-watermark，把 `(last_stream_seq, high-watermark]` 且**该座位可见**的消息逐条补发（可见性过滤仍然逐条执行）；补发期间新消息先缓冲。
4. 补发完成后再切回实时流（不丢/不重/不乱序），回 `reconnected {latest_stream_seq, replayed_count}`。
5. 断线宽限 60s **不暂停 deadline**：操作先到期就立即确定性兜底；宽限期内可恢复参与后续操作；超期进入**永久自动兜底模式**（可继续观战/终局回放，不可再提交操作）。
6. `stream_seq` 因私密过滤出现跳号是正常现象；`domain_event_id` 独立，仅用于规则事件。

## 5. 超时与幂等规则

### 5.1 超时（编排层统一配置，可配置）

| 操作 | 默认超时 | 兜底 |
|---|---|---|
| 发言 | 30s | 放弃发言 |
| 投票/重投 | 20s | 合法候选确定性选择 |
| 狼人确认刀人 | 20s | AI 建议兜底 |
| 预言家查验/女巫用药 | 20s | 不查验/不用药 |
| 遗言 | 30s | 放弃遗言 |
| 竞价 | 10s | priority=5 |

**超时执行链（修正原假设）**：
1. 编排层按动作类型生成 `decision_request`，携带 `deadline_ms`。
2. `QueueChannel` 保存当前 `request` 与 `deadline`；`HumanPlayer.decide` 用 `recv(timeout=deadline)` 阻塞。
3. 超时触发时：先经 `loop.call_soon_threadsafe` 向客户端发 `timeout {request_id, fallback}`，随后抛**受控超时**。
4. `Referee._decide` 捕获异常 → 执行合法兜底（现有 `_fallback`）。
5. 测试必须验证**每类操作各自时长**真正生效（不能用同一超时）。

### 5.2 幂等与关联

- `request_id`（服务端生成）唯一标识一次操作请求；`action` 必须回带当前 `request_id`，否则 `stale_request`。
- `client_action_id`（客户端生成）保证重复提交幂等：相同 ID + 相同规范化请求 → 返回第一次的缓存结果，不重复执行；相同 ID + 不同内容 → `idempotency_conflict`。
- `action_ack` 仅表示已完成鉴权/合法性检查/入队；规则动作是否最终生效以对应公开/私密事件为准。
- 非法/过期/重复请求只回 `error`，不改变状态机。

## 6. 权限矩阵

| 能力 | 房主(seat 0，即真人) | 其他座位(AI) | 服务端 |
|---|---|---|---|
| 读自己私密事件 | ✅ | ✗ | — |
| 读公开事件 | ✅ | ✅(不下发客户端) | — |
| 提交自己座位操作 | ✅ | ✗ | 复验合法性 |
| 提交他人座位操作 | ✗ | ✗ | 拒绝 `forbidden` |
| start / replay / delete | ✅（房主 token） | ✗ | 复验 `not_owner` |
| replay | ✅（仅 finished） | ✗ | 复验 finished+房主 |
| 读取 API Key | ✗ | ✗ | 仅服务端，永不下发 |
| 对局中查看公开历史/本人私密历史 | ✅ | ✗ | — |
| AI 决策轨迹（心理回放） | ✅（仅终局后） | ✗ | — |

服务端对每个 `action` **重新验证**：`request.actor == seat_id`、目标在 `legal_targets`、phase 匹配、药水可用性、狼人只能刀存活非狼等（复用 `Referee._sanitize`）。

## 7. 安全边界

- 校验 WebSocket `Origin`（白名单）。
- 单条入站消息大小上限 **16KiB**、每连接令牌桶 **5 条/秒、突发 10 条**，超限回 `message_too_large` / `rate_limited`。
- Token 只保存**摘要**（如 HMAC/SHA-256），不写日志；API Key、完整私密身份不得进入错误日志。
- `replay` 返回前再次校验**房主身份 + finished 状态**。
- 断线补发**逐条执行可见性过滤**。
- Token 禁止放 URL 查询参数；仅经 `join`/`reconnect` 消息提交。

## 8. 测试清单

自动化（离线 Mock + 脚本人类）：
1. 正常完成一局（create→join→start→…→game_over→replay→delete）。
2. 真人狼：AI 建议→真人确认；确认覆盖建议、超时走确定性兜底。
3. 真人预言家查验：请求/响应/私密结果只回本座。
4. 真人女巫用药：合法单药、非法双药/自毒/毒死者拒绝。
5. 投票平票→限选重投→二次平票无人放逐。
6. 重复提交：同 `client_action_id` 只生效一次。
7. 非法目标：回 `illegal_target`，状态机不变。
8. 超时兜底：**逐类验证各自时长生效**，超时后收到 `timeout` 且走确定性兜底。
9. 断线重连：按 `last_stream_seq` 补发，`stream_seq` 连续/跳号正确，可见性过滤生效。
10. 私密事件越权：AI 座位/未授权 token 读不到私密事件。
11. 终局回放与原始事件一致（`replay` 与事件日志逐条比对）。
12. 非法/过期/重复请求返回明确错误且不破坏状态机。
13. 房间生命周期：seat 被占后其他 join 拒绝；非房主 start/replay/delete 拒绝；未终局 replay/delete 拒绝。
14. 容量：活跃房间达上限返回 `room_capacity_reached`；finished 后回收线程/队列/连接。
15. 安全：Origin 校验、消息大小/频率限制、token 不落日志、API Key 不出现。
16. 异常回收：对局线程异常时自动兜底自然结束，再回收资源。

真实模型人工验收（待本机 Key）：断线重连补发正确、回放可读、超时兜底不中断。

## 9. 明确不做的范围

- 多真人混房、“谁是 AI”模式。
- 语音（ASR/TTS）。
- SQLite 战绩持久化、Admin 后台。
- 正式前端页面（仅协议 + 最小测试客户端）。
- 不复制第二套狼人杀规则（复用 `Referee`）。
- 不做真人账号体系/登录（单机 token 绑定座位）。
- 不实现“强杀进行中的对局线程”。

## 10. 最终产品决策（已定稿，实现以本节为准）

1. **建房抢座**：`create_room` 返回一次性 `join_secret`；`join` 必须提交它。服务端只保存摘要，验证成功后立即作废并签发正式 `session_token`；不能仅凭 `room_id` 抢真人座位。
2. **stream_seq 范围**：只分配给需要断线恢复的持久下行消息；含 token 的 `room_created`/`joined`、`ping/pong`、`ai_processing`、普通 `error`、`reconnected` 不进入 append-only 日志；任何 token 不落盘、不回放。
3. **幂等语义**：相同 `client_action_id` + 相同规范化请求 → 返回第一次的缓存结果，不重复执行；相同 ID + 不同内容 → `idempotency_conflict`。
4. **重连竞态**：在锁内取 high-watermark，补发 `(last_stream_seq, high-watermark]`，期间新消息先缓冲；补发完成后切到实时流，不丢/不重/不乱序。
5. **断线宽限不暂停 deadline**：操作先到期就立即确定性兜底；60s 只决定是否还能参与后续操作；超宽限后本局永久自动兜底，只能观战+终局回放。
6. **action_ack 语义**：仅表示已完成鉴权/合法性检查/入队；规则动作是否最终生效以对应公开/私密事件为准。
7. **活跃房间统计**：只统计 created/joined/running；finished 立即释放线程与队列容量；未开局房间空闲 10 分钟自动过期。
8. **运行资源 vs 保留数据**：终局释放运行资源；事件/回放/transcript 用服务端管理的 JSON 文件最多保留 30 天，客户端不能指定路径；不落盘则不得宣称重启后仍保留。
9. **默认参数**：`MAX_ACTIVE_ROOMS=10`；客户端单条入站消息 ≤16KiB；每连接令牌桶 5 条/秒、突发 10 条；断线宽限与各动作超时进服务端配置、客户端不得覆盖；配置启动时校验、建房间时固化、进行中不变。
10. **对应测试**：抢座、secret 一次性消费、token 不落日志、真正幂等、幂等冲突、重连期间并发消息、断线不暂停 deadline、空房过期、finished 释放容量、30 天数据清理。
