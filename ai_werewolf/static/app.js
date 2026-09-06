"use strict";

// AI狼人杀 — 圆桌界面。双模式（引导默认/快速）+ 离线演示/真实LLM 房间模式。
// 会话敏感信息只存 sessionStorage；模式偏好存 localStorage。

const TARGET_KINDS = ["night_kill", "pack_confirm", "night_inspect", "vote"];
const KIND_LABELS = {
  night_kill: "选择猎杀目标", pack_confirm: "确认猎杀目标", night_inspect: "选择查验目标",
  witch_potions: "决定是否用药", statement: "发言", last_words: "遗言", vote: "投票放逐", bid: "竞价发言",
};
const PHASE_LABELS = { setup: "准备", night: "夜晚", dawn: "清晨", discussion: "讨论", voting: "投票", resolution: "结算", finished: "结束" };
const ROLE_NAMES = { villager: "村民", werewolf: "狼人", seer: "预言家", witch: "女巫" };
const ROLE_INFO = {
  villager: { faction: "好人阵营", goal: "投出所有狼人", ability: "没有特殊技能，靠发言和投票" },
  werewolf: { faction: "狼人阵营", goal: "夜晚刀人，存活到好人被消灭", ability: "每晚和队友一起刀一名非狼玩家" },
  seer: { faction: "好人阵营", goal: "投出所有狼人", ability: "每晚查验一名玩家是否为狼" },
  witch: { faction: "好人阵营", goal: "投出所有狼人", ability: "有一瓶解药和一瓶毒药，各只能用一次" },
};
const PERSONAS_INTRO = [
  { name: "质疑者", style: "主动找矛盾、频繁追问，不轻信身份声明" },
  { name: "老好人", style: "偏信任、语气友善，不轻易强推别人" },
  { name: "分析家", style: "重票型和前后逻辑，发言结构化、情绪较弱" },
  { name: "激进派", style: "结论明确、强势拉票、容忍较高决策风险" },
  { name: "和事佬", style: "关注阵营共识、缓和冲突，关键时刻会归票" },
  { name: "话痨", style: "表达丰富、情绪化、容易制造噪声和戏剧效果" },
];

const SS = { room: "aiww_room_id", seat: "aiww_seat_id", token: "aiww_token", seq: "aiww_last_stream_seq" };
const LS_MODE = "aiww_mode";

const S = {
  ws: null, roomId: null, token: null, seat: null, myRole: null, phase: "setup",
  seats: [], currentRequest: null, clientActionSeq: 0, countdownTimer: null,
  wantCreate: false, wantReconnect: false, lastStreamSeq: 0,
  mode: localStorage.getItem(LS_MODE) || "guided",
  aiMode: "offline", realAvailable: false, model: null,
  queue: [], playing: false, queueTimer: null,
  identityConfirmed: false, pendingMate: null,
  private: { myRole: null, pack: [], seerResults: {} },
  finalRoles: {}, voted: {},
  seatEls: {}, bubbleEl: null,
  collectedEvents: [],
};

function el(id) { return document.getElementById(id); }
function setStatus(t) { el("status").textContent = t; }
function isGuided() { return S.mode === "guided"; }
function send(type, data) { if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify({ type, data: data || {} })); }

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

// ---------------------------------------------------------------- health / home
async function loadHealth() {
  try {
    const resp = await fetch("/health");
    const data = await resp.json();
    S.realAvailable = !!data.real_llm_available;
    S.model = data.model || null;
  } catch (e) { S.realAvailable = false; }
  renderAiModeChoice();
}
function renderAiModeChoice() {
  const realBtn = el("ai-real");
  realBtn.disabled = !S.realAvailable;
  el("ai-mode-note").textContent = S.realAvailable
    ? "真实 LLM 已配置（" + (S.model || "未知模型") + "）"
    : "真实 LLM 未配置（缺少 .env 配置），只能使用离线演示 AI";
}

function setAiMode(mode) {
  S.aiMode = mode;
  el("ai-offline").classList.toggle("active", mode === "offline");
  el("ai-real").classList.toggle("active", mode === "real");
}

// ---------------------------------------------------------------- connect
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(proto + "://" + location.host + "/ws");
  S.ws = ws;
  ws.onopen = () => {
    setStatus("已连接");
    if (S.wantCreate) { S.wantCreate = false; send("create_room", { ai_mode: S.aiMode }); }
    else if (S.wantReconnect) {
      S.wantReconnect = false;
      send("reconnect", { room_id: S.roomId, seat_id: S.seat, session_token: S.token, last_stream_seq: S.lastStreamSeq });
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
  if (type === "reconnected") { return addFeed({ text: "已恢复对局，补发 " + d.replayed_count + " 条" }, "phase"); }
  if (type === "error") { return onError(d); }
  if (type === "deleted") { clearSession(); location.reload(); }
  if (type === "room_created") { return onRoomCreated(d); }
  if (type === "joined") { return onJoined(d); }
  if (type === "action_ack") { return onAck(); }
  if (type === "timeout") { return onTimeout(d); }

  const item = { type, data: d, ts: msg.ts };
  if (type === "game_started") { onGameStartedState(d); }
  if (type === "private_event" && d.kind === "role_dealt") { S.private.myRole = d.data && d.data.role; maybeShowIdentity(); }
  if (type === "private_event" && d.kind === "pack_mates") { S.private.pack = (d.data && d.data.pack) || []; maybeShowIdentity(); }
  if (type === "private_event" && d.kind === "seer_result") { S.private.seerResults[d.target] = !!(d.data && d.data.is_wolf); }
  S.collectedEvents.push(item);

  if (isGuided()) enqueue(item);
  else renderEvent(item, false);
}

function enqueue(item) { S.queue.push(item); if (!S.playing) { S.playing = true; playNext(); } }
function playNext() {
  if (S.queue.length === 0) { S.playing = false; return; }
  const item = S.queue.shift();
  renderEvent(item, true);
  maybePhaseCard(item);
  maybeSummary(item);
  S.queueTimer = setTimeout(playNext, delayFor(item));
}
function flushForDecision() {
  if (S.queue.length) { addFeed({ text: "…已略过 " + S.queue.length + " 条事件，现在轮到你" }, "phase"); S.queue = []; }
  if (S.queueTimer) { clearTimeout(S.queueTimer); S.queueTimer = null; }
  S.playing = false;
  if (!S.identityConfirmed && S.private.myRole) dismissIdentity();
}
function delayFor(item) {
  const d = item.data || {};
  if (item.type === "game_started") return 1400;
  if (d.kind === "statement" || d.kind === "last_words") { const n = String(d.text || "").length; return Math.min(4500, Math.max(900, 900 + n * 32)); }
  if (d.kind === "death" || d.kind === "lynch") return 2600;
  if (d.kind === "seer_result" || d.kind === "witch_attack" || d.kind === "witch_potions") return 2200;
  if (d.kind === "vote" || d.kind === "bid") return 850;
  if (d.kind === "no_lynch" || d.kind === "peaceful_night") return 1600;
  return 1000;
}

// ---------------------------------------------------------------- identity
function maybeShowIdentity() {
  if (!isGuided() || S.identityConfirmed || !S.private.myRole) return;
  const info = ROLE_INFO[S.private.myRole] || { faction: "", goal: "", ability: "" };
  el("identity-role").textContent = "你的身份：" + roleName(S.private.myRole);
  el("identity-faction").innerHTML = "<b>阵营</b>：" + info.faction;
  el("identity-goal").innerHTML = "<b>目标</b>：" + info.goal;
  el("identity-ability").innerHTML = "<b>能力</b>：" + info.ability;
  const mates = el("identity-mates");
  if (S.private.pack.length) { mates.hidden = false; mates.innerHTML = "<b>狼队友</b>：" + S.private.pack.map((p) => "P" + p).join("、"); }
  else mates.hidden = true;
  el("identity-modal").hidden = false;
}
function dismissIdentity() { S.identityConfirmed = true; el("identity-modal").hidden = true; }

// ---------------------------------------------------------------- phase
function maybePhaseCard(item) {
  const d = item.data || {};
  if (!d.phase || d.phase === S.phase) return;
  S.phase = d.phase;
  renderTopBar();
  renderTable();
}
function maybeSummary(item) {
  const d = item.data || {};
  if (!isGuided()) return;
  if (d.kind === "death" || d.kind === "lynch") addFeed({ text: "第 " + d.day + " 天 P" + d.target + " 出局，身份暂未公开。" }, "key");
  else if (d.kind === "vote" && d.data && d.data.round === 2) addFeed({ text: "投票平票，进入限选重投。" }, "key");
  else if (d.kind === "peaceful_night") addFeed({ text: "昨夜平安夜，无人出局。" }, "phase");
  else if (d.kind === "no_lynch") addFeed({ text: "无人被放逐。" }, "phase");
}

// ---------------------------------------------------------------- events / round table
function renderEvent(item, rich) {
  const d = item.data || {};
  const t = item.type;
  if (t === "game_started") { renderSeats(d.seats || []); renderTopBar(); return; }

  if (d.phase) { S.phase = d.phase; renderTopBar(); }

  if (t === "public_event" && d.kind === "statement" && d.actor != null) {
    S.voted[d.actor] = S.voted[d.actor] || false;
    highlightSeat(d.actor, d.text, rich);
    addFeed({ who: "P" + d.actor, text: d.text, day: d.day }, "speech");
    return;
  }
  if (t === "public_event" && d.kind === "vote" && d.actor != null) {
    S.voted[d.actor] = true;
    renderTable();
    addFeed({ text: "P" + d.actor + " 投了 P" + d.target, day: d.day }, "");
    return;
  }
  if ((d.kind === "death" || d.kind === "lynch") && d.target != null) {
    const s = S.seats.find((x) => x.id === d.target);
    if (s) { s.alive = false; }
    renderTable();
  }
  if (t === "private_event") addFeed({ text: privateText(d), day: d.day }, "private");
  else if (d.kind === "death" || d.kind === "lynch") addFeed({ text: d.text || KIND_LABELS[d.kind] || d.kind, day: d.day }, "key");
  else if (d.kind === "game_started" || d.kind === "night_begins" || d.kind === "discussion_begins") addFeed({ text: d.text, day: d.day }, "phase");
  else addFeed({ text: d.text || KIND_LABELS[d.kind] || d.kind, day: d.day }, "");
  renderTable();
}

function highlightSeat(actor, text, rich) {
  Object.values(S.seatEls).forEach((e) => e.classList.remove("speaking"));
  const seatEl = S.seatEls[actor];
  if (seatEl) seatEl.classList.add("speaking");
  if (rich) showBubble(actor, text);
  setTimeout(() => { if (seatEl) seatEl.classList.remove("speaking"); }, 2000);
}
function showBubble(actor, text) {
  if (!S.bubbleEl) { S.bubbleEl = document.createElement("div"); S.bubbleEl.className = "bubble"; el("table").appendChild(S.bubbleEl); }
  const seatEl = S.seatEls[actor];
  S.bubbleEl.textContent = "P" + actor + "：" + text;
  if (seatEl) {
    S.bubbleEl.style.left = (seatEl.offsetLeft + 60) + "px";
    S.bubbleEl.style.top = seatEl.offsetTop + "px";
  }
  S.bubbleEl.hidden = false;
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

function addFeed(d, cls) {
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

// ---------------------------------------------------------------- seats / table
function renderSeats(seats) {
  S.seats = seats || S.seats || [];
  const table = el("table");
  table.innerHTML = "";
  S.seatEls = {};
  const cx = table.clientWidth / 2, cy = table.clientHeight / 2;
  const radius = Math.min(cx, cy) - 80;
  S.seats.forEach((s, i) => {
    const angle = -90 + i * (360 / S.seats.length);
    const x = cx + radius * Math.cos(angle * Math.PI / 180);
    const y = cy + radius * Math.sin(angle * Math.PI / 180);
    const div = document.createElement("div");
    div.className = "seat" + (s.id === S.seat ? " me" : "") + (s.alive ? "" : " dead");
    div.style.left = x + "px";
    div.style.top = y + "px";
    div.innerHTML = seatCardHtml(s);
    table.appendChild(div);
    S.seatEls[s.id] = div;
  });
  renderPrivateInfo();
}
function seatRole(s) {
  if (S.finalRoles[s.id]) return ROLE_NAMES[S.finalRoles[s.id]] || S.finalRoles[s.id];
  if (s.id === S.seat && S.private.myRole) return roleName(S.private.myRole);
  if (S.private.pack.includes(s.id)) return "狼队友";
  if (s.id in S.private.seerResults) return S.private.seerResults[s.id] ? "狼" : "好";
  return "?";
}
function seatCardHtml(s) {
  const persona = s.is_human ? "" : s.name;
  const role = seatRole(s);
  const tags = [];
  if (S.voted[s.id]) tags.push("已投票");
  if (!s.alive) tags.push("死亡");
  return "<div class='seat-card'>" +
    "<div class='num'>P" + s.id + "</div>" +
    (s.is_human ? "<div class='name'>你</div>" : "<div class='name'>" + escapeHtml(s.name) + "</div>") +
    "<div class='role'>" + role + "</div>" +
    "<div class='tags'>" + tags.join(" ") + "</div>" +
    "</div>";
}
function renderTable() {
  Object.entries(S.seatEls).forEach(([id, div]) => {
    const s = S.seats.find((x) => x.id === Number(id));
    if (s) div.innerHTML = seatCardHtml(s);
  });
  renderPrivateInfo();
}
function renderTopBar() {
  const bar = el("top-bar");
  if (!bar) return;
  bar.innerHTML = "<span>第 " + (S.seats.length ? "?" : "") + " 天</span>" +
    "<span class='phase'>阶段：" + (PHASE_LABELS[S.phase] || S.phase) + "</span>";
}
function renderPrivateInfo() {
  const box = el("private-info");
  if (!box) return;
  let html = "<h3>我的私密信息</h3>";
  html += "<div class='line'>身份：" + roleName(S.private.myRole) + "</div>";
  if (S.private.pack.length) html += "<div class='line'>狼队友：" + S.private.pack.map((p) => "P" + p).join("、") + "</div>";
  const seer = Object.entries(S.private.seerResults);
  if (seer.length) html += "<div class='line'>查验：" + seer.map(([p, w]) => "P" + p + (w ? "狼" : "好")).join("、") + "</div>";
  box.innerHTML = html;
}

// ---------------------------------------------------------------- room / start
function onRoomCreated(d) {
  S.roomId = d.room_id;
  el("room-info").textContent = "房间 " + d.room_id;
  el("ai-mode-badge").textContent = d.effective_ai_mode === "real" ? "真实 LLM" : "离线演示 AI";
  el("ai-mode-badge").className = "badge" + (d.effective_ai_mode === "real" ? " real" : "");
  send("join", { room_id: d.room_id, join_secret: d.join_secret });
}
function onJoined(d) {
  S.token = d.session_token; S.seat = d.seat_id;
  saveSession(S.roomId, S.seat, S.token);
  el("home").hidden = true;
  el("lobby").hidden = false;
  el("start-btn").disabled = false;
  el("lobby-note").textContent = "已入座（P" + d.seat_id + "）。点击「开始游戏」。";
}
function onGameStartedState(d) {
  el("lobby").hidden = true; el("game").hidden = false; el("result").hidden = true;
  S.phase = d.phase || "night";
  renderSeats(d.seats || []);
  renderTopBar();
}

// ---------------------------------------------------------------- decision
function onDecision(d, ts) {
  S.currentRequest = d;
  el("game").hidden = false;
  el("turn-banner").hidden = false;
  renderDecision(d);
  renderCopilot(d);
  const box = el("decision");
  box.classList.add("highlight");
  box.scrollIntoView({ behavior: "smooth", block: "center" });
  startCountdown(d.deadline_ms, ts);
}
function onAck() { el("turn-banner").hidden = true; clearDecision("已提交，等待其他玩家…"); stopCountdown(); }
function onTimeout(d) { el("turn-banner").hidden = true; clearDecision("已超时，系统已自动兜底。"); stopCountdown(); }
function onError(d) {
  addFeed({ text: "错误 [" + d.code + "] " + d.message }, "private");
  if (d.code === "unauthorized" || d.code === "room_not_found" || d.code === "provider_unavailable") { clearSession(); location.reload(); }
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
  if (d.can_heal) { const b = document.createElement("button"); b.className = "gold"; b.textContent = "使用解药"; b.onclick = () => submitAction({ kind: "witch_potions", heal: true }); box.appendChild(b); }
  if (d.can_poison) {
    box.appendChild(note("使用毒药（选择目标）："));
    const wrap = document.createElement("div"); wrap.className = "targets";
    (d.legal_targets || []).forEach((t) => { const b = document.createElement("button"); b.className = "danger"; b.textContent = "P" + t; b.onclick = () => submitAction({ kind: "witch_potions", poison: t }); wrap.appendChild(b); });
    box.appendChild(wrap);
  }
  const skip = document.createElement("button"); skip.className = "ghost"; skip.textContent = "不用药"; skip.onclick = () => submitAction({ kind: "witch_potions" }); box.appendChild(skip);
}
function renderBid(box, d) {
  box.appendChild(note("竞价 0–10："));
  const wrap = document.createElement("div"); wrap.className = "targets";
  for (let i = 10; i >= 0; i--) { const b = document.createElement("button"); b.textContent = String(i); b.onclick = () => submitAction({ kind: "bid", priority: i }); wrap.appendChild(b); }
  box.appendChild(wrap);
}
function submitAction(action) {
  if (!S.currentRequest) return;
  const request = S.currentRequest;
  S.currentRequest = null;
  S.clientActionSeq += 1;
  send("action", { request_id: request.request_id, client_action_id: "web-" + S.clientActionSeq, kind: action.kind, target: action.target, text: action.text, heal: action.heal, poison: action.poison, priority: action.priority });
}

// ---------------------------------------------------------------- copilot
function renderCopilot(d) {
  const box = el("copilot"); box.innerHTML = "";
  const h = document.createElement("h3"); h.textContent = "🐺 Copilot 狼人嫌疑"; box.appendChild(h);
  const body = document.createElement("div"); body.id = "copilot-body";
  const cd = d.copilot_data || {};
  const susp = (cd.suspicions || []).slice().sort((a, b) => b.probability - a.probability);
  if (!susp.length) body.appendChild(note("暂无嫌疑数据"));
  susp.forEach((s) => {
    const pct = Math.round(s.probability * 100);
    const row = document.createElement("div"); row.className = "suspect" + (s.player_id === cd.recommended_vote ? " recommended" : "");
    const head = document.createElement("div"); head.className = "suspect-head";
    head.innerHTML = "<span>P" + s.player_id + " " + escapeHtml(s.name) + "</span><span class='pct'>" + pct + "%</span>";
    row.appendChild(head);
    const bar = document.createElement("div"); bar.className = "bar";
    const fill = document.createElement("div"); fill.className = "bar-fill"; fill.style.width = pct + "%";
    bar.appendChild(fill); row.appendChild(bar);
    const reasons = document.createElement("div"); reasons.className = "reasons"; reasons.textContent = (s.reasons || []).join("；"); row.appendChild(reasons);
    body.appendChild(row);
  });
  const rationale = document.createElement("div"); rationale.className = "rationale"; rationale.textContent = "建议：" + (cd.rationale || "—"); body.appendChild(rationale);
  box.appendChild(body);
  const disc = document.createElement("div"); disc.className = "disclaimer"; disc.textContent = "AI 辅助建议，仅供参考，最终决定由你做出。"; box.appendChild(disc);
  if (!isGuided()) {
    const toggle = document.createElement("button"); toggle.className = "ghost"; toggle.textContent = "收起 / 展开";
    toggle.onclick = () => box.classList.toggle("copilot-collapsed"); box.appendChild(toggle);
  }
}

// ---------------------------------------------------------------- game over / recap
function onGameOver(d) {
  stopCountdown();
  el("turn-banner").hidden = true;
  clearDecision("");
  el("game").hidden = true; el("result").hidden = false;
  (d.seats || []).forEach((s) => { S.finalRoles[s.id] = s.role; });
  const winner = d.winner;
  const box = el("result-body"); box.innerHTML = "";
  const h = document.createElement("p");
  h.textContent = "胜方：" + (winner === "werewolves" ? "狼人阵营" : "村民阵营");
  box.appendChild(h);
  (d.seats || []).forEach((s) => {
    const row = document.createElement("div"); row.className = "seat-row";
    row.textContent = "P" + s.id + " " + s.name + " — " + roleName(s.role) + (s.is_human ? "（你）" : "") + " — " + (s.alive ? "存活" : "死亡");
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
  line.innerHTML = "<span class='" + (won ? "win" : "lose") + "'>" + (won ? "你赢了" : "你输了") + "</span>（你是" + roleName(mySeat.role) + "，" + (mySeat.alive ? "存活到终局" : "中途死亡") + "）";
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
  const note2 = document.createElement("p"); note2.className = "muted"; note2.textContent = "下一局你可能会抽到不同身份。"; box.appendChild(note2);
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
function clearDecision(text) { const box = el("decision"); if (!box) return; box.innerHTML = ""; box.classList.remove("highlight"); if (text) box.appendChild(note(text)); }
function note(text) { const d = document.createElement("div"); d.className = "muted"; d.textContent = text; return d; }
function roleName(r) { return ROLE_NAMES[r] || r || "未知"; }
function escapeHtml(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function exitGame() { clearSession(); location.reload(); }
function setMode(mode) {
  S.mode = mode;
  localStorage.setItem(LS_MODE, mode);
  el("mode-guided").classList.toggle("active", mode === "guided");
  el("mode-fast").classList.toggle("active", mode === "fast");
  el("exp-new").classList.toggle("active", mode === "guided");
  el("exp-vet").classList.toggle("active", mode === "fast");
  if (mode === "fast") flushForDecision();
}

// ---------------------------------------------------------------- bootstrap
function renderPersonaIntro() {
  const box = el("persona-intro");
  box.innerHTML = PERSONAS_INTRO.map((p) => "<div class='p'><b>" + p.name + "</b>：" + p.style + "</div>").join("");
}
el("exp-new").onclick = () => setMode("guided");
el("exp-vet").onclick = () => setMode("fast");
el("ai-offline").onclick = () => setAiMode("offline");
el("ai-real").onclick = () => setAiMode("real");
el("create-btn").onclick = () => {
  el("create-btn").disabled = true;
  if (S.ws && S.ws.readyState === WebSocket.OPEN) send("create_room", { ai_mode: S.aiMode });
  else S.wantCreate = true;
};
el("start-btn").onclick = () => send("start", { room_id: S.roomId });
el("replay-btn").onclick = () => send("replay", { room_id: S.roomId });
el("again-btn").onclick = exitGame;
el("home-btn").onclick = exitGame;
el("identity-confirm").onclick = dismissIdentity;
el("mode-guided").onclick = () => setMode("guided");
el("mode-fast").onclick = () => setMode("fast");
el("drawer-toggle").onclick = () => {
  const drawer = el("drawer");
  drawer.hidden = !drawer.hidden;
  el("drawer-toggle").textContent = drawer.hidden ? "完整日志（折叠）" : "收起日志";
};
setMode(S.mode);
setAiMode(S.aiMode);
renderPersonaIntro();
loadHealth();

const saved = loadSession();
if (saved.roomId && saved.token && !Number.isNaN(saved.seat)) {
  S.roomId = saved.roomId; S.seat = saved.seat; S.token = saved.token; S.lastStreamSeq = saved.seq || 0;
  S.wantReconnect = true;
  el("home").hidden = true; el("lobby").hidden = true; el("game").hidden = false;
  el("top-bar").textContent = "正在恢复对局…";
}

connect();
