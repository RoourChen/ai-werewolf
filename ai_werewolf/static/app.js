"use strict";

// AI狼人杀 — 前端。双模式：引导模式（默认，逐条播放 + 阶段/身份卡）+ 快速模式（立即渲染）。
// 模式偏好存 localStorage；会话敏感信息（token 等）只存 sessionStorage。

const TARGET_KINDS = ["night_kill", "pack_confirm", "night_inspect", "vote"];

const KIND_LABELS = {
  night_kill: "选择猎杀目标", pack_confirm: "确认猎杀目标", night_inspect: "选择查验目标",
  witch_potions: "决定是否用药", statement: "发言", last_words: "遗言",
  vote: "投票放逐", bid: "竞价发言",
};

const PHASE_LABELS = {
  setup: "准备", night: "夜晚", dawn: "清晨", discussion: "讨论",
  voting: "投票", resolution: "结算", finished: "结束",
};

const ROLE_NAMES = { villager: "村民", werewolf: "狼人", seer: "预言家", witch: "女巫" };

const PHASES = {
  setup: { name: "准备", what: "发放身份、确认队友", todo: "看清你的身份和阵营目标", term: "" },
  night: { name: "夜晚", what: "狼人刀人、预言家查验、女巫用药", todo: "夜里能行动的角色行动，其余人等待", term: "「查验」= 预言家看一名玩家是不是狼人" },
  dawn: { name: "清晨", what: "公布昨夜结果", todo: "看清谁出局了", term: "" },
  discussion: { name: "讨论", what: "每个人依次发言、找狼人", todo: "说出你的怀疑，听别人发言", term: "「归票」= 号召大家集中投同一个人" },
  voting: { name: "投票", what: "每人一票放逐最怀疑的人", todo: "选一个你想放逐的目标", term: "「平票」= 得票最高的人并列" },
  resolution: { name: "结算", what: "结算放逐结果，进入下一夜或结束", todo: "等待结果", term: "" },
  finished: { name: "结束", what: "揭晓全部身份", todo: "查看结果与复盘", term: "" },
};

const ROLE_INFO = {
  villager: { faction: "好人阵营", goal: "投出所有狼人", ability: "没有特殊技能，靠发言和投票" },
  werewolf: { faction: "狼人阵营", goal: "夜晚刀人，存活到好人被消灭", ability: "每晚和队友一起刀一名非狼玩家" },
  seer: { faction: "好人阵营", goal: "投出所有狼人", ability: "每晚查验一名玩家是否为狼" },
  witch: { faction: "好人阵营", goal: "投出所有狼人", ability: "有一瓶解药和一瓶毒药，各只能用一次" },
};

const KEY_KINDS = {
  death: true, lynch: true, seer_result: true, witch_attack: true, witch_potions: true,
  no_lynch: true, peaceful_night: true, game_over: true,
};

// sessionStorage keys — 会话敏感信息（不进 URL / 日志 / 回放）
const SS = { room: "aiww_room_id", seat: "aiww_seat_id", token: "aiww_token", seq: "aiww_last_stream_seq" };
const LS_MODE = "aiww_mode";

const S = {
  ws: null, roomId: null, token: null, seat: null, myRole: null, phase: "setup",
  seats: [], currentRequest: null, clientActionSeq: 0, countdownTimer: null,
  wantCreate: false, wantReconnect: false, lastStreamSeq: 0,
  mode: localStorage.getItem(LS_MODE) || "guided",
  queue: [], playing: false, queueTimer: null,
  identityConfirmed: false, pendingMate: null,
  collectedEvents: [],
};

function el(id) { return document.getElementById(id); }
function setStatus(text) { el("status").textContent = text; }
function isGuided() { return S.mode === "guided"; }

function saveSession(roomId, seatId, token) {
  sessionStorage.setItem(SS.room, roomId);
  sessionStorage.setItem(SS.seat, String(seatId));
  sessionStorage.setItem(SS.token, token);
}
function clearSession() { Object.values(SS).forEach((k) => sessionStorage.removeItem(k)); }
function loadSession() {
  return {
    roomId: sessionStorage.getItem(SS.room),
    seat: parseInt(sessionStorage.getItem(SS.seat) || "", 10),
    token: sessionStorage.getItem(SS.token),
    seq: parseInt(sessionStorage.getItem(SS.seq) || "0", 10),
  };
}

function send(type, data) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return;
  S.ws.send(JSON.stringify({ type, data: data || {} }));
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(proto + "://" + location.host + "/ws");
  S.ws = ws;
  ws.onopen = () => {
    setStatus("已连接");
    if (S.wantCreate) { S.wantCreate = false; send("create_room", {}); }
    else if (S.wantReconnect) {
      S.wantReconnect = false;
      send("reconnect", {
        room_id: S.roomId, seat_id: S.seat,
        session_token: S.token, last_stream_seq: S.lastStreamSeq,
      });
    }
  };
  ws.onmessage = (ev) => { try { handle(JSON.parse(ev.data)); } catch (e) { console.error(e); } };
  ws.onclose = () => setStatus("连接已断开");
}

// ---------------------------------------------------------------- handle / queue
function handle(msg) {
  if (msg.stream_seq != null) {
    S.lastStreamSeq = Math.max(S.lastStreamSeq, msg.stream_seq);
    sessionStorage.setItem(SS.seq, String(S.lastStreamSeq));
  }
  const d = msg.data || {};
  const type = msg.type;

  if (type === "decision_request") { flushForDecision(); return onDecision(d, msg.ts); }
  if (type === "game_over") { flushForDecision(); return onGameOver(d); }
  if (type === "replay") { return onReplay(d); }
  if (type === "reconnected") { return addFeed({ text: "已恢复对局，补发 " + d.replayed_count + " 条" }, "phase", true); }
  if (type === "error") { return onError(d); }
  if (type === "deleted") { clearSession(); location.reload(); }
  if (type === "room_created") { return onRoomCreated(d); }
  if (type === "joined") { return onJoined(d); }
  if (type === "action_ack") { return onAck(); }
  if (type === "timeout") { return onTimeout(d); }

  // 事件类消息
  const item = { type, data: d, ts: msg.ts };
  if (type === "game_started") { onGameStartedState(d); }
  if (type === "private_event" && d.kind === "role_dealt") {
    S.myRole = d.data && d.data.role;
    maybeShowIdentity();
  }
  if (type === "private_event" && d.kind === "pack_mates") {
    S.pendingMate = (d.data && d.data.pack) || [];
    maybeShowIdentity();
  }
  S.collectedEvents.push(item);

  if (isGuided()) enqueue(item);
  else renderEvent(item, false);
}

function enqueue(item) {
  S.queue.push(item);
  if (!S.playing) { S.playing = true; playNext(); }
}
function playNext() {
  if (S.queue.length === 0) { S.playing = false; return; }
  const item = S.queue.shift();
  renderEvent(item, true);
  maybePhaseCard(item);
  maybeSummary(item);
  S.queueTimer = setTimeout(playNext, delayFor(item));
}
function flushForDecision() {
  if (S.queue.length) {
    addFeed({ text: "…已略过 " + S.queue.length + " 条事件，现在轮到你" }, "skip", true);
    S.queue = [];
  }
  if (S.queueTimer) { clearTimeout(S.queueTimer); S.queueTimer = null; }
  S.playing = false;
  if (!S.identityConfirmed && S.myRole) dismissIdentity();
}

function delayFor(item) {
  const d = item.data || {};
  if (item.type === "game_started") return 1400;
  if (d.kind === "statement" || d.kind === "last_words") {
    const n = String(d.text || "").length;
    return Math.min(4500, Math.max(900, 900 + n * 32));
  }
  if (d.kind === "death" || d.kind === "lynch") return 2600;
  if (d.kind === "seer_result" || d.kind === "witch_attack" || d.kind === "witch_potions") return 2200;
  if (d.kind === "vote" || d.kind === "bid") return 850;
  if (d.kind === "no_lynch" || d.kind === "peaceful_night") return 1600;
  return 1000;
}

// ---------------------------------------------------------------- identity card
function maybeShowIdentity() {
  if (!isGuided() || S.identityConfirmed || !S.myRole) return;
  const info = ROLE_INFO[S.myRole] || { faction: "", goal: "", ability: "" };
  el("identity-role").textContent = "你的身份：" + roleName(S.myRole);
  el("identity-faction").innerHTML = "<b>阵营</b>：" + info.faction;
  el("identity-goal").innerHTML = "<b>目标</b>：" + info.goal;
  el("identity-ability").innerHTML = "<b>能力</b>：" + info.ability;
  const mates = el("identity-mates");
  if (S.pendingMate && S.pendingMate.length) {
    mates.hidden = false;
    mates.innerHTML = "<b>狼队友</b>：" + S.pendingMate.map((p) => "P" + p).join("、");
  } else {
    mates.hidden = true;
  }
  el("identity-modal").hidden = false;
}
function dismissIdentity() {
  S.identityConfirmed = true;
  el("identity-modal").hidden = true;
}

// ---------------------------------------------------------------- phase card / summary
function maybePhaseCard(item) {
  const d = item.data || {};
  if (!d.phase || d.phase === S.phase) return;
  S.phase = d.phase;
  renderPhase();
  if (!isGuided()) return;
  const p = PHASES[S.phase] || { name: PHASE_LABELS[S.phase] || S.phase, what: "", todo: "", term: "" };
  const box = el("phase-card");
  box.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = "阶段：" + p.name;
  box.appendChild(h);
  if (p.what) { const x = document.createElement("p"); x.textContent = "会发生：" + p.what; box.appendChild(x); }
  if (p.todo) { const x = document.createElement("p"); x.textContent = "你要做：" + p.todo; box.appendChild(x); }
  if (p.term) { const x = document.createElement("p"); x.className = "term"; x.textContent = p.term; box.appendChild(x); }
}

function maybeSummary(item) {
  const d = item.data || {};
  if (!isGuided()) return;
  if (d.kind === "death" || d.kind === "lynch") {
    addFeed({ text: "第 " + d.day + " 天 P" + d.target + " 出局，身份暂未公开。" }, "key", true);
  } else if (d.kind === "vote" && d.data && d.data.round === 2) {
    addFeed({ text: "投票平票，进入限选重投。" }, "key", true);
  } else if (d.kind === "peaceful_night") {
    addFeed({ text: "昨夜平安夜，无人出局。" }, "phase", true);
  } else if (d.kind === "no_lynch") {
    addFeed({ text: "无人被放逐。" }, "phase", true);
  }
}

// ---------------------------------------------------------------- event rendering
function renderEvent(item, rich) {
  const d = item.data || {};
  const t = item.type;
  if (t === "game_started") { renderSeats(d.seats || []); return; }

  let cls = "";
  let who = "";
  let text = "";
  if (t === "public_event") {
    if (d.kind === "statement") { cls = "speech"; who = "P" + d.actor; text = d.text || ""; }
    else if (KEY_KINDS[d.kind]) { cls = "key"; who = ""; text = d.text || KIND_LABELS[d.kind] || d.kind; }
    else { cls = "phase"; text = d.text || KIND_LABELS[d.kind] || d.kind; }
  } else if (t === "private_event") {
    cls = "private";
    text = privateText(d);
  }

  if (d.phase) { S.phase = d.phase; renderPhase(); }
  if ((d.kind === "death" || d.kind === "lynch") && d.target != null) {
    const s = S.seats.find((x) => x.id === d.target);
    if (s) { s.alive = false; renderSeats(S.seats); }
  }

  addFeed({ who, text, day: d.day, cls }, cls, rich);
}

function privateText(d) {
  switch (d.kind) {
    case "role_dealt": return "你的身份：" + roleName(d.data && d.data.role);
    case "pack_mates": return "狼队友：" + ((d.data && d.data.pack) || []).map((p) => "P" + p).join("、");
    case "seer_result": return "查验 P" + d.target + "：" + (d.data && d.data.is_wolf ? "是狼人" : "是好人");
    case "witch_attack": return "今夜 P" + d.target + " 被狼人袭击";
    case "witch_potions": return "你使用了" + (d.data && d.data.potion === "heal" ? "解药" : "毒药") + "（P" + d.target + "）";
    default: return d.text || d.kind;
  }
}

function addFeed(d, cls, rich) {
  const box = el("feed");
  if (!box) return;
  const line = document.createElement("div");
  line.className = "feed-line" + (cls ? " " + cls : "");
  let html = "";
  if (d.day != null) html += "<span class='day'>第" + d.day + "天</span>";
  if (d.who) html += "<span class='who'>" + escapeHtml(d.who) + "：</span>";
  html += escapeHtml(d.text || "");
  line.innerHTML = html;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

// ---------------------------------------------------------------- room / start
function onRoomCreated(d) {
  S.roomId = d.room_id;
  el("room-info").textContent = "房间 " + d.room_id;
  send("join", { room_id: d.room_id, join_secret: d.join_secret });
}
function onJoined(d) {
  S.token = d.session_token; S.seat = d.seat_id;
  saveSession(S.roomId, S.seat, S.token);
  el("start-btn").disabled = false;
  el("lobby-note").textContent = "已入座（P" + d.seat_id + "）。点击「开始游戏」。";
}
function onGameStartedState(d) {
  el("lobby").hidden = true; el("game").hidden = false; el("result").hidden = true;
  S.phase = d.phase || "night";
  renderSeats(d.seats || []);
  renderPhase();
}

// ---------------------------------------------------------------- decision
function onDecision(d, ts) {
  S.currentRequest = d;
  el("game").hidden = false;
  el("result").hidden = true;
  el("turn-banner").hidden = false;
  renderPhase();
  renderDecision(d);
  renderCopilot(d);
  const box = el("decision");
  box.classList.add("highlight");
  box.scrollIntoView({ behavior: "smooth", block: "center" });
  startCountdown(d.deadline_ms, ts);
}

function onAck() {
  el("turn-banner").hidden = true;
  clearDecision("已提交，等待其他玩家…");
  stopCountdown();
}
function onTimeout(d) {
  el("turn-banner").hidden = true;
  clearDecision("已超时，系统已自动兜底。");
  stopCountdown();
}
function onError(d) {
  addFeed({ text: "错误 [" + d.code + "] " + d.message }, "private", true);
  if (d.code === "unauthorized" || d.code === "room_not_found") { clearSession(); location.reload(); }
}

function renderPhase() { el("phase").textContent = "阶段：" + (PHASE_LABELS[S.phase] || S.phase); }
function renderRole() { el("role").textContent = "你的身份：" + roleName(S.myRole); }

function renderSeats(seats) {
  S.seats = seats || S.seats || [];
  const box = el("seats"); box.innerHTML = "";
  S.seats.forEach((s) => {
    const row = document.createElement("div");
    row.className = "seat" + (s.id === S.seat ? " me" : "") + (s.alive ? "" : " dead");
    row.textContent = "P" + s.id + " " + (s.name || "") + (s.alive ? "" : "（死亡）");
    box.appendChild(row);
  });
  if (S.myRole) renderRole();
  maybeShowIdentity();
}

function renderDecision(d) {
  const box = el("decision"); box.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = "轮到你：" + (KIND_LABELS[d.kind] || d.kind);
  box.appendChild(h);
  if (TARGET_KINDS.indexOf(d.kind) >= 0) renderTargets(box, d);
  else if (d.kind === "statement" || d.kind === "last_words") renderStatement(box, d);
  else if (d.kind === "witch_potions") renderWitch(box, d);
  else if (d.kind === "bid") renderBid(box, d);
}

function renderTargets(box, d) {
  const wrap = document.createElement("div"); wrap.className = "targets";
  const targets = (d.suggestions && d.suggestions.length) ? d.suggestions : d.legal_targets;
  (targets || []).forEach((t) => {
    const b = document.createElement("button");
    b.textContent = "P" + t;
    b.onclick = () => submitAction({ kind: d.kind, target: t });
    wrap.appendChild(b);
  });
  if (d.kind === "pack_confirm" && d.suggestions && d.suggestions.length) wrap.appendChild(note("（狼队友建议的目标）"));
  box.appendChild(wrap);
}
function renderStatement(box, d) {
  const ta = document.createElement("textarea"); ta.className = "textarea";
  ta.placeholder = d.kind === "last_words" ? "说一句遗言…" : "输入你的发言…";
  box.appendChild(ta);
  const b = document.createElement("button");
  b.textContent = d.kind === "last_words" ? "提交遗言" : "提交发言";
  b.onclick = () => submitAction({ kind: d.kind, text: ta.value });
  box.appendChild(b);
}
function renderWitch(box, d) {
  if (d.can_heal) {
    const b = document.createElement("button"); b.className = "gold"; b.textContent = "使用解药";
    b.onclick = () => submitAction({ kind: "witch_potions", heal: true }); box.appendChild(b);
  }
  if (d.can_poison) {
    box.appendChild(note("使用毒药（选择目标）："));
    const wrap = document.createElement("div"); wrap.className = "targets";
    (d.legal_targets || []).forEach((t) => {
      const b = document.createElement("button"); b.className = "danger"; b.textContent = "P" + t;
      b.onclick = () => submitAction({ kind: "witch_potions", poison: t }); wrap.appendChild(b);
    });
    box.appendChild(wrap);
  }
  const skip = document.createElement("button"); skip.className = "ghost"; skip.textContent = "不用药";
  skip.onclick = () => submitAction({ kind: "witch_potions" }); box.appendChild(skip);
}
function renderBid(box, d) {
  box.appendChild(note("竞价 0–10（数字越大越先发言）："));
  const wrap = document.createElement("div"); wrap.className = "targets";
  for (let i = 10; i >= 0; i--) {
    const b = document.createElement("button"); b.textContent = String(i);
    b.onclick = () => submitAction({ kind: "bid", priority: i }); wrap.appendChild(b);
  }
  box.appendChild(wrap);
}

function submitAction(action) {
  if (!S.currentRequest) return;
  const request = S.currentRequest;
  S.currentRequest = null;
  S.clientActionSeq += 1;
  send("action", {
    request_id: request.request_id, client_action_id: "web-" + S.clientActionSeq,
    kind: action.kind, target: action.target, text: action.text,
    heal: action.heal, poison: action.poison, priority: action.priority,
  });
}

// ---------------------------------------------------------------- copilot
function renderCopilot(d) {
  const box = el("copilot"); box.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = "🐺 Copilot 狼人嫌疑";
  box.appendChild(h);
  const body = document.createElement("div"); body.id = "copilot-body";
  const cd = d.copilot_data || {};
  const susp = (cd.suspicions || []).slice().sort((a, b) => b.probability - a.probability);
  if (!susp.length) { body.appendChild(note("暂无嫌疑数据")); }
  susp.forEach((s) => {
    const pct = Math.round(s.probability * 100);
    const row = document.createElement("div");
    row.className = "suspect" + (s.player_id === cd.recommended_vote ? " recommended" : "");
    const head = document.createElement("div"); head.className = "suspect-head";
    head.innerHTML = "<span>P" + s.player_id + " " + escapeHtml(s.name) + "</span><span class='pct'>" + pct + "%</span>";
    row.appendChild(head);
    const bar = document.createElement("div"); bar.className = "bar";
    const fill = document.createElement("div"); fill.className = "bar-fill"; fill.style.width = pct + "%";
    bar.appendChild(fill); row.appendChild(bar);
    const reasons = document.createElement("div"); reasons.className = "reasons";
    reasons.textContent = (s.reasons || []).join("；"); row.appendChild(reasons);
    body.appendChild(row);
  });
  const rationale = document.createElement("div"); rationale.className = "rationale";
  rationale.textContent = "建议：" + (cd.rationale || "—"); body.appendChild(rationale);
  box.appendChild(body);

  const disc = document.createElement("div"); disc.className = "disclaimer";
  disc.textContent = "AI 辅助建议，仅供参考，最终决定由你做出。";
  box.appendChild(disc);

  if (!isGuided()) {
    const toggle = document.createElement("button"); toggle.className = "ghost"; toggle.textContent = "收起 / 展开";
    toggle.onclick = () => box.classList.toggle("copilot-collapsed");
    box.appendChild(toggle);
  }
}

// ---------------------------------------------------------------- game over / recap
function onGameOver(d) {
  stopCountdown();
  el("turn-banner").hidden = true;
  clearDecision("");
  el("game").hidden = true; el("result").hidden = false;
  const winner = d.winner;
  const box = el("result-body"); box.innerHTML = "";
  const h = document.createElement("p");
  h.textContent = "胜方：" + (winner === "werewolves" ? "狼人阵营" : "村民阵营");
  box.appendChild(h);
  (d.seats || []).forEach((s) => {
    const row = document.createElement("div"); row.className = "seat-row";
    row.textContent = "P" + s.id + " " + s.name + " — " + roleName(s.role) +
      (s.is_human ? "（你）" : "") + " — " + (s.alive ? "存活" : "死亡");
    box.appendChild(row);
  });
  renderRecap(d, winner);
  el("replay-btn").hidden = false;
}

function renderRecap(d, winner) {
  const box = el("recap"); box.innerHTML = "";
  const mySeat = (d.seats || []).find((s) => s.is_human) || {};
  const won = mySeat.role === "werewolf" ? winner === "werewolves" : winner === "village";
  const h = document.createElement("h3"); h.textContent = "本局复盘（你）"; box.appendChild(h);
  const line = document.createElement("p");
  line.innerHTML = "<span class='" + (won ? "win" : "lose") + "'>" + (won ? "你赢了" : "你输了") + "</span>" +
    "（你是" + roleName(mySeat.role) + "，" + (mySeat.alive ? "存活到终局" : "中途死亡") + "）";
  box.appendChild(line);
  const ul = document.createElement("ul");
  const myVotes = S.collectedEvents.filter((e) => e.type === "public_event" && e.data.kind === "vote" && e.data.actor === S.seat);
  if (myVotes.length) ul.appendChild(li("你投票：" + myVotes.map((e) => "第" + e.data.day + "天投 P" + e.data.target).join("；")));
  const myStatements = S.collectedEvents.filter((e) => e.type === "public_event" && e.data.kind === "statement" && e.data.actor === S.seat);
  if (myStatements.length) ul.appendChild(li("你发言 " + myStatements.length + " 次"));
  const myDeath = S.collectedEvents.find((e) => (e.data.kind === "death" || e.data.kind === "lynch") && e.data.target === S.seat);
  if (myDeath) ul.appendChild(li("你在第 " + myDeath.data.day + " 天出局（" + (myDeath.data.kind === "lynch" ? "被放逐" : "被狼人刀") + "）"));
  const myInspect = S.collectedEvents.filter((e) => e.type === "private_event" && e.data.kind === "seer_result");
  if (myInspect.length) ul.appendChild(li("你查验了 " + myInspect.length + " 次"));
  const myPotion = S.collectedEvents.find((e) => e.type === "private_event" && e.data.kind === "witch_potions");
  if (myPotion) ul.appendChild(li("你使用了" + (myPotion.data.data && myPotion.data.data.potion === "heal" ? "解药" : "毒药")));
  if (!ul.children.length) ul.appendChild(li("这一局你没有留下特殊操作记录"));
  box.appendChild(ul);
  const note2 = document.createElement("p"); note2.className = "muted";
  note2.textContent = "下一局你可能会抽到不同身份。";
  box.appendChild(note2);
}

function li(text) { const x = document.createElement("li"); x.textContent = text; return x; }

function onReplay(d) {
  const box = el("replay"); box.hidden = false; box.innerHTML = "";
  const replay = d.replay || {};
  (replay.events || []).forEach((ev) => {
    const line = document.createElement("div"); line.className = "log-line";
    line.textContent = "第" + (ev.day ?? "?") + "天 [" + (ev.phase || "") + "] " + (ev.text || "");
    box.appendChild(line);
  });
  const h = document.createElement("div"); h.className = "log-line muted";
  h.textContent = "—— 决策轨迹（" + Object.keys(replay.traces || {}).length + " 名 AI）——";
  box.appendChild(h);
}

// ---------------------------------------------------------------- helpers
function startCountdown(deadlineMs, ts) {
  stopCountdown();
  const noteEl = note(""); noteEl.className = "countdown";
  const box = el("decision"); if (box) box.appendChild(noteEl);
  const start = ts ? Date.parse(ts) : Date.now();
  const end = start + (deadlineMs || 0);
  S.countdownTimer = setInterval(() => {
    const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
    noteEl.textContent = "剩余 " + left + " 秒";
    if (left <= 0) stopCountdown();
  }, 500);
}
function stopCountdown() { if (S.countdownTimer) { clearInterval(S.countdownTimer); S.countdownTimer = null; } }
function clearDecision(text) {
  const box = el("decision"); if (!box) return;
  box.innerHTML = ""; box.classList.remove("highlight");
  if (text) box.appendChild(note(text));
}
function note(text) { const d = document.createElement("div"); d.className = "muted"; d.textContent = text; return d; }
function roleName(r) { return ROLE_NAMES[r] || r || "未知"; }
function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function exitGame() { clearSession(); location.reload(); }
function setMode(mode) {
  S.mode = mode;
  localStorage.setItem(LS_MODE, mode);
  el("mode-guided").classList.toggle("active", mode === "guided");
  el("mode-fast").classList.toggle("active", mode === "fast");
  if (mode === "fast") flushForDecision();
}

// ---------------------------------------------------------------- bootstrap
el("create-btn").onclick = () => {
  el("create-btn").disabled = true;
  if (S.ws && S.ws.readyState === WebSocket.OPEN) send("create_room", {});
  else S.wantCreate = true;
};
el("start-btn").onclick = () => send("start", { room_id: S.roomId });
el("replay-btn").onclick = () => send("replay", { room_id: S.roomId });
el("again-btn").onclick = exitGame;
el("home-btn").onclick = exitGame;
el("exit-btn").onclick = exitGame;
el("identity-confirm").onclick = dismissIdentity;
el("mode-guided").onclick = () => setMode("guided");
el("mode-fast").onclick = () => setMode("fast");
setMode(S.mode);

const saved = loadSession();
if (saved.roomId && saved.token && !Number.isNaN(saved.seat)) {
  S.roomId = saved.roomId; S.seat = saved.seat; S.token = saved.token; S.lastStreamSeq = saved.seq || 0;
  S.wantReconnect = true;
  el("lobby").hidden = true; el("game").hidden = false;
  el("phase").textContent = "阶段：正在恢复对局…";
}

connect();
