"use strict";

// AI狼人杀 — 最小 Web 客户端（纯静态，无构建链）。
// 复用服务端 `/ws` 协议：建房 → 入座 → 开局 → 夜晚/讨论/投票 → 终局 → 回放。

const TARGET_KINDS = ["night_kill", "pack_confirm", "night_inspect", "vote"];

const KIND_LABELS = {
  night_kill: "选择猎杀目标",
  pack_confirm: "确认猎杀目标",
  night_inspect: "选择查验目标",
  witch_potions: "决定是否用药",
  statement: "发言",
  last_words: "遗言",
  vote: "投票放逐",
  bid: "竞价发言",
};

const PHASE_LABELS = {
  setup: "准备", night: "夜晚", dawn: "清晨", discussion: "讨论",
  voting: "投票", resolution: "结算", finished: "结束",
};

const ROLE_NAMES = { villager: "村民", werewolf: "狼人", seer: "预言家", witch: "女巫" };

const S = {
  ws: null,
  roomId: null,
  token: null,
  seat: null,
  myRole: null,
  phase: "setup",
  seats: [],
  currentRequest: null,
  clientActionSeq: 0,
  countdownTimer: null,
  wantCreate: false,
};

function el(id) { return document.getElementById(id); }
function setStatus(text) { el("status").textContent = text; }

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
  };
  ws.onmessage = (ev) => {
    try { handle(JSON.parse(ev.data)); } catch (e) { console.error(e); }
  };
  ws.onclose = () => setStatus("连接已断开（刷新页面可重连）");
}

// ---------------------------------------------------------------- handlers
function handle(msg) {
  const d = msg.data || {};
  switch (msg.type) {
    case "room_created": return onRoomCreated(d);
    case "joined": return onJoined(d);
    case "game_started": return onGameStarted(d);
    case "public_event": return onPublicEvent(d);
    case "private_event": return onPrivateEvent(d);
    case "decision_request": return onDecision(d);
    case "action_ack": return onAck();
    case "timeout": return onTimeout(d);
    case "error": return onError(d);
    case "game_over": return onGameOver(d);
    case "replay": return onReplay(d);
    case "deleted": return onDeleted();
    case "reconnected": addLog({ text: "已重连，补发 " + d.replayed_count + " 条" }, "private");
    default: return undefined;
  }
}

function onRoomCreated(d) {
  S.roomId = d.room_id;
  el("room-info").textContent = "房间 " + d.room_id;
  send("join", { room_id: d.room_id, join_secret: d.join_secret });
  el("lobby-note").textContent = "已创建房间，正在入座…";
}

function onJoined(d) {
  S.token = d.session_token;
  S.seat = d.seat_id;
  el("start-btn").disabled = false;
  el("lobby-note").textContent = "已入座（P" + d.seat_id + "）。点击「开始游戏」。";
}

function onGameStarted(d) {
  S.phase = "night";
  el("lobby").hidden = true;
  el("game").hidden = false;
  renderSeats(d.seats || []);
  renderPhase();
  const counts = d.role_counts || {};
  addLog({ text: "游戏开始。狼人 " + (counts.werewolf || 2) + "，预言家 1，女巫 1，村民 " + (counts.villager || 3) });
}

function onPublicEvent(d) {
  if (d.phase) { S.phase = d.phase; renderPhase(); }
  const cls = (d.kind === "death" || d.kind === "lynch") ? "death" : "";
  addLog(d, cls);
  if ((d.kind === "death" || d.kind === "lynch") && d.target != null) {
    const seat = S.seats.find((s) => s.id === d.target);
    if (seat) { seat.alive = false; renderSeats(S.seats); }
  }
}

function onPrivateEvent(d) {
  if (d.phase) { S.phase = d.phase; renderPhase(); }
  const k = d.kind;
  if (k === "role_dealt") {
    S.myRole = d.data && d.data.role;
    renderRole();
    addLog({ text: "你的身份：" + roleName(S.myRole) }, "private");
  } else if (k === "pack_mates") {
    const pack = (d.data && d.data.pack) || [];
    addLog({ text: "狼队友：" + pack.map((p) => "P" + p).join("、") }, "private");
  } else if (k === "seer_result") {
    const verdict = d.data && d.data.is_wolf ? "是狼人" : "是好人";
    addLog({ text: "查验 P" + d.target + "：" + verdict }, "private");
  } else if (k === "witch_attack") {
    addLog({ text: "今夜 P" + d.target + " 被狼人袭击" }, "private");
  } else if (k === "witch_potions") {
    const potion = d.data && d.data.potion;
    addLog({ text: "你使用了" + (potion === "heal" ? "解药" : "毒药") + "（P" + d.target + "）" }, "private");
  } else {
    addLog(d, "private");
  }
}

function onDecision(d) {
  S.currentRequest = d;
  renderPhase();
  renderDecision(d);
  renderCopilot(d);
  startCountdown(d.deadline_ms);
}

function onAck() {
  clearDecision("已提交，等待其他玩家…");
  stopCountdown();
}

function onTimeout(d) {
  clearDecision("已超时，系统已自动兜底。");
  stopCountdown();
}

function onError(d) {
  addLog({ text: "错误 [" + d.code + "] " + d.message }, "private");
}

function onGameOver(d) {
  stopCountdown();
  clearDecision("");
  el("game").hidden = true;
  el("result").hidden = false;
  const box = el("result-body");
  box.innerHTML = "";
  const h = document.createElement("p");
  h.textContent = "胜方：" + (d.winner === "werewolves" ? "狼人阵营" : "村民阵营");
  box.appendChild(h);
  (d.seats || []).forEach((s) => {
    const row = document.createElement("div");
    row.className = "seat-row";
    row.textContent = "P" + s.id + " " + s.name + " — " + roleName(s.role) +
      (s.is_human ? "（你）" : "") + " — " + (s.alive ? "存活" : "死亡");
    box.appendChild(row);
  });
  el("replay-btn").hidden = false;
}

function onReplay(d) {
  const box = el("replay");
  box.hidden = false;
  box.innerHTML = "";
  const replay = d.replay || {};
  (replay.events || []).forEach((ev) => addLogTo(box, ev));
  const traces = replay.traces || {};
  const h = document.createElement("div");
  h.className = "log-line muted";
  h.textContent = "—— 决策轨迹（" + Object.keys(traces).length + " 名 AI）——";
  box.appendChild(h);
}

function onDeleted() {
  el("result").hidden = true;
  el("lobby").hidden = false;
  el("start-btn").disabled = true;
  el("lobby-note").textContent = "本局已删除。";
}

// ---------------------------------------------------------------- rendering
function renderPhase() {
  el("phase").textContent = "阶段：" + (PHASE_LABELS[S.phase] || S.phase);
}

function renderRole() {
  el("role").textContent = "你的身份：" + roleName(S.myRole);
}

function renderSeats(seats) {
  S.seats = seats || S.seats || [];
  const box = el("seats");
  box.innerHTML = "";
  S.seats.forEach((s) => {
    const row = document.createElement("div");
    row.className = "seat" + (s.id === S.seat ? " me" : "") + (s.alive ? "" : " dead");
    row.textContent = "P" + s.id + " " + (s.name || "") + (s.alive ? "" : "（死亡）");
    box.appendChild(row);
  });
}

function renderDecision(d) {
  const box = el("decision");
  box.innerHTML = "";
  const h = document.createElement("h3");
  h.textContent = "轮到你：" + (KIND_LABELS[d.kind] || d.kind);
  box.appendChild(h);

  if (TARGET_KINDS.indexOf(d.kind) >= 0) renderTargets(box, d);
  else if (d.kind === "statement" || d.kind === "last_words") renderStatement(box, d);
  else if (d.kind === "witch_potions") renderWitch(box, d);
  else if (d.kind === "bid") renderBid(box, d);
}

function renderTargets(box, d) {
  const wrap = document.createElement("div");
  wrap.className = "targets";
  const targets = (d.suggestions && d.suggestions.length) ? d.suggestions : d.legal_targets;
  (targets || []).forEach((t) => {
    const b = document.createElement("button");
    b.textContent = "P" + t;
    b.onclick = () => submitAction({ kind: d.kind, target: t });
    wrap.appendChild(b);
  });
  if (d.kind === "pack_confirm" && d.suggestions && d.suggestions.length) {
    wrap.appendChild(note("（狼队友建议的目标）"));
  }
  box.appendChild(wrap);
}

function renderStatement(box, d) {
  const ta = document.createElement("textarea");
  ta.className = "textarea";
  ta.placeholder = d.kind === "last_words" ? "说一句遗言…" : "输入你的发言…";
  box.appendChild(ta);
  const b = document.createElement("button");
  b.textContent = d.kind === "last_words" ? "提交遗言" : "提交发言";
  b.onclick = () => submitAction({ kind: d.kind, text: ta.value });
  box.appendChild(b);
}

function renderWitch(box, d) {
  if (d.can_heal) {
    const b = document.createElement("button");
    b.textContent = "使用解药";
    b.onclick = () => submitAction({ kind: "witch_potions", heal: true });
    box.appendChild(b);
  }
  if (d.can_poison) {
    box.appendChild(note("使用毒药（选择目标）："));
    const wrap = document.createElement("div");
    wrap.className = "targets";
    (d.legal_targets || []).forEach((t) => {
      const b = document.createElement("button");
      b.className = "danger";
      b.textContent = "P" + t;
      b.onclick = () => submitAction({ kind: "witch_potions", poison: t });
      wrap.appendChild(b);
    });
    box.appendChild(wrap);
  }
  const skip = document.createElement("button");
  skip.className = "ghost";
  skip.textContent = "不用药";
  skip.onclick = () => submitAction({ kind: "witch_potions" });
  box.appendChild(skip);
}

function renderBid(box, d) {
  box.appendChild(note("竞价 0–10（数字越大越先发言）："));
  const wrap = document.createElement("div");
  wrap.className = "targets";
  for (let i = 10; i >= 0; i--) {
    const b = document.createElement("button");
    b.textContent = String(i);
    b.onclick = () => submitAction({ kind: "bid", priority: i });
    wrap.appendChild(b);
  }
  box.appendChild(wrap);
}

function renderCopilot(d) {
  const box = el("copilot");
  box.innerHTML = "";
  const cd = d.copilot_data || {};
  const susp = (cd.suspicions || []).slice().sort((a, b) => b.probability - a.probability);
  const h = document.createElement("h3");
  h.textContent = "🐺 Copilot 狼人嫌疑";
  box.appendChild(h);
  if (!susp.length) {
    box.appendChild(note("暂无嫌疑数据"));
    box.appendChild(disclaimer());
    return;
  }
  susp.forEach((s) => {
    const pct = Math.round(s.probability * 100);
    const row = document.createElement("div");
    row.className = "suspect" + (s.player_id === cd.recommended_vote ? " recommended" : "");
    const head = document.createElement("div");
    head.className = "suspect-head";
    head.innerHTML = "<span>P" + s.player_id + " " + escapeHtml(s.name) + "</span>" +
      "<span class='pct'>" + pct + "%</span>";
    row.appendChild(head);
    const bar = document.createElement("div");
    bar.className = "bar";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.width = pct + "%";
    bar.appendChild(fill);
    row.appendChild(bar);
    const reasons = document.createElement("div");
    reasons.className = "reasons";
    reasons.textContent = (s.reasons || []).join("；");
    row.appendChild(reasons);
    box.appendChild(row);
  });
  const rationale = document.createElement("div");
  rationale.className = "rationale";
  rationale.textContent = "建议：" + (cd.rationale || "—");
  box.appendChild(rationale);
  box.appendChild(disclaimer());
}

function disclaimer() {
  const d = document.createElement("div");
  d.className = "disclaimer";
  d.textContent = "仅供参考，最终决定由你做出。";
  return d;
}

function startCountdown(deadlineMs) {
  stopCountdown();
  const noteEl = note("");
  noteEl.className = "countdown";
  const box = el("decision");
  if (box) box.appendChild(noteEl);
  const end = Date.now() + deadlineMs;
  S.countdownTimer = setInterval(() => {
    const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
    noteEl.textContent = "剩余 " + left + " 秒";
    if (left <= 0) stopCountdown();
  }, 500);
}

function stopCountdown() {
  if (S.countdownTimer) { clearInterval(S.countdownTimer); S.countdownTimer = null; }
}

function clearDecision(text) {
  const box = el("decision");
  if (!box) return;
  box.innerHTML = "";
  if (text) box.appendChild(note(text));
}

function submitAction(action) {
  if (!S.currentRequest) return;
  S.clientActionSeq += 1;
  send("action", {
    request_id: S.currentRequest.request_id,
    client_action_id: "web-" + S.clientActionSeq,
    kind: action.kind,
    target: action.target,
    text: action.text,
    heal: action.heal,
    poison: action.poison,
    priority: action.priority,
  });
}

// ---------------------------------------------------------------- log
function addLog(d, cls) {
  addLogTo(el("log"), d, cls);
}

function addLogTo(container, d, cls) {
  if (!container) return;
  const line = document.createElement("div");
  line.className = "log-line" + (cls ? " " + cls : "");
  const day = (d.day !== undefined) ? "第" + d.day + "天" : "";
  const text = d.text || (d.kind ? (KIND_LABELS[d.kind] || d.kind) : "");
  line.innerHTML = (day ? "<span class='day'>" + day + "</span>" : "") + escapeHtml(text);
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function note(text) {
  const d = document.createElement("div");
  d.className = "muted";
  d.textContent = text;
  return d;
}

function roleName(r) { return ROLE_NAMES[r] || r || "未知"; }

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------- bootstrap
el("create-btn").onclick = () => {
  el("create-btn").disabled = true;
  if (S.ws && S.ws.readyState === WebSocket.OPEN) {
    send("create_room", {});
  } else {
    S.wantCreate = true;
  }
};
el("start-btn").onclick = () => send("start", { room_id: S.roomId });
el("replay-btn").onclick = () => send("replay", { room_id: S.roomId });

connect();
