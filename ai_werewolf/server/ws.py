"""Single-human WebSocket runtime (FastAPI + uvicorn).

Implements the protocol in ``PRD/03_产品设计/单真人WebSocket设计.md``.

The core :class:`WsServer` is transport-agnostic and synchronous so tests can
drive a full game without a live socket; :func:`create_ws_app` adapts it to a
FastAPI app with a single ``/ws`` endpoint and a ``/health`` probe.

Threading model (one room = one game thread + one pump thread):

* the game thread runs the existing synchronous :class:`GameSession`;
* the human seat is bridged through a thread-safe :class:`QueueChannel`;
* the pump thread drains the channel's outbox and pushes messages to the
  connected client, assigning ``stream_seq`` to persistent messages;
* cross-thread delivery into the event loop uses ``call_soon_threadsafe``.

Tokens are never written to logs or replays: only their HMAC-SHA256 digests are
stored in memory.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import queue
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai_werewolf.ai.provider import Provider
from ai_werewolf.replay.recorder import record_session
from ai_werewolf.server.room import AIConfig, HumanSeat, RoomConfig
from ai_werewolf.server.session import GameSession
from ai_werewolf.transport.channel import Envelope
from ai_werewolf.transport.queue import DEFAULT_TIMEOUTS, QueueChannel, timeout_for_kind

try:  # fastapi is optional — only create_ws_app needs it; importing WebSocket at
    # module level keeps FastAPI's annotation resolution working under PEP 563.
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover - fastapi is only required by create_ws_app
    FastAPI = None  # type: ignore[assignment,misc]
    WebSocket = None  # type: ignore[assignment,misc]
    WebSocketDisconnect = None  # type: ignore[assignment,misc]

TARGET_KINDS = frozenset({"night_kill", "pack_confirm", "night_inspect", "vote"})


class WsError(Exception):
    """A protocol error with a machine-readable code (never carries secrets)."""

    def __init__(
        self,
        code: str,
        message: str,
        request_id: str | None = None,
        client_action_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.client_action_id = client_action_id


@dataclass
class WsConfig:
    """Server-side, startup-validated configuration (clients cannot override)."""

    max_active_rooms: int = 10
    disconnect_grace: float = 60.0
    idle_timeout: float = 600.0  # un-started rooms expire after 10 minutes
    retention_days: float = 30.0
    message_max_bytes: int = 16 * 1024
    rate_limit_per_sec: float = 5.0
    rate_limit_burst: int = 10
    timeouts: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TIMEOUTS))
    seed: int = 1
    allowed_origins: list[str] | None = None  # None = allow all (dev)
    provider_factory: Callable[[int], Provider | None] | None = None

    def __post_init__(self) -> None:
        if self.max_active_rooms <= 0:
            raise ValueError("max_active_rooms must be positive")
        if self.disconnect_grace < 0:
            raise ValueError("disconnect_grace must be non-negative")
        if self.message_max_bytes <= 0:
            raise ValueError("message_max_bytes must be positive")
        for kind, seconds in self.timeouts.items():
            if seconds <= 0:
                raise ValueError(f"timeout for {kind!r} must be positive")


class Connection:
    """A thread-safe outbound pipe to one connected client."""

    def __init__(self) -> None:
        self.bound_room_id: str | None = None
        self.bound_seat: int | None = None

    def send(self, message: dict) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class MemoryConnection(Connection):
    """A test double whose outbound messages can be drained with a timeout."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: queue.Queue[dict] = queue.Queue()

    def send(self, message: dict) -> None:
        self.messages.put(json.loads(json.dumps(message)))

    def next(self, timeout: float = 10.0) -> dict:
        return self.messages.get(timeout=timeout)


class StarletteConnection(Connection):
    """Bridges a starlette WebSocket into the running event loop."""

    def __init__(self, websocket: Any, loop: Any, outbox: asyncio.Queue[dict]) -> None:
        super().__init__()
        self._websocket = websocket
        self._loop = loop
        self._outbox = outbox

    def send(self, message: dict) -> None:
        self._loop.call_soon_threadsafe(self._outbox.put_nowait, message)


@dataclass
class _LogEntry:
    seq: int
    message: dict
    audience: frozenset[int] | None


class _Room:
    """State for one live room and its single human seat."""

    def __init__(self, server: WsServer, room_id: str, join_secret_digest: str) -> None:
        self.server = server
        self.room_id = room_id
        self.join_secret_digest = join_secret_digest
        self.created_at = server.now()
        self.last_activity = self.created_at
        self.finished_at: float | None = None

        self.status = "created"  # created -> joined -> running -> finished -> deleted
        self.seat = 0
        self.session_token_digest: str | None = None
        self.channel = QueueChannel(server.config.timeouts)
        self.connection: Connection | None = None
        self.connected = False
        self.disconnect_at: float | None = None

        self.log: list[_LogEntry] = []
        self.log_lock = threading.Lock()
        self.stream_seq = 0

        self.current_request_id: str | None = None
        self.pending_request: dict | None = None
        self.idempotency: dict[str, tuple[str, dict]] = {}

        self.game_thread: threading.Thread | None = None
        self.pump_thread: threading.Thread | None = None
        self._pump_stop = threading.Event()
        self.session: GameSession | None = None
        self.transcript: dict | None = None

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.status = "running"
        self.game_thread = threading.Thread(
            target=self._game_loop, name=f"game-{self.room_id}", daemon=True
        )
        self.game_thread.start()
        self.pump_thread = threading.Thread(
            target=self._pump_loop, name=f"pump-{self.room_id}", daemon=True
        )
        self.pump_thread.start()

    def _game_loop(self) -> None:
        session = self._build_session()
        self.session = session
        try:
            session.run()
        finally:
            self.status = "finished"
            self.finished_at = self.server.now()
            try:
                self.transcript = record_session(session)
            except Exception:  # noqa: BLE001 - a failed transcript must not break the room
                self.transcript = None

    def _build_session(self) -> GameSession:
        factory = self.server.config.provider_factory
        provider = factory(self.server.config.seed) if factory is not None else None
        ai = AIConfig(count=6, policy="llm", provider=provider)
        config = RoomConfig(
            capacity=7,
            language="zh",
            discussion_mode="seating",
            ai=ai,
            seed=self.server.config.seed,
        )
        return GameSession(config, {self.seat: HumanSeat(name="你", channel=self.channel)})

    def _pump_loop(self) -> None:
        while not self._pump_stop.is_set():
            try:
                envelope = self.channel.outbox.get(timeout=0.2)
            except queue.Empty:
                self._check_disconnect_grace()
                continue
            self._forward(envelope)
            self._check_disconnect_grace()

    def _check_disconnect_grace(self) -> None:
        if self.connected or self.disconnect_at is None:
            return
        if self.server.now() - self.disconnect_at >= self.server.config.disconnect_grace:
            self.channel.auto_fallback = True

    # -------------------------------------------------------------- forwarding
    def _forward(self, envelope: Envelope) -> None:
        if envelope.kind == "decision":
            self._forward_decision(envelope)
        elif envelope.kind == "event":
            self._forward_event(envelope, public=True)
        elif envelope.kind == "private_event":
            self._forward_event(envelope, public=False)
        elif envelope.kind == "chat":
            self._forward_chat(envelope)
        elif envelope.kind == "result":
            self._forward_result(envelope)
        elif envelope.kind == "timeout":
            self._forward_timeout(envelope)

    def _forward_decision(self, envelope: Envelope) -> None:
        payload = envelope.payload
        request = payload.get("request", {})
        kind = str(request.get("kind", ""))
        request_id = uuid.uuid4().hex[:8]
        self.current_request_id = request_id
        self.pending_request = request
        data = {
            "request_id": request_id,
            "kind": kind,
            "legal_targets": list(request.get("legal_targets", [])),
            "can_heal": bool(request.get("can_heal")),
            "can_poison": bool(request.get("can_poison")),
            "suggestions": list(request.get("suggestions", [])),
            "deadline_ms": int(timeout_for_kind(kind, self.server.config.timeouts) * 1000),
            "prompt": payload.get("prompt", ""),
            "copilot": payload.get("advice", ""),
        }
        self._send("decision_request", data, persistent=True, audience=frozenset({self.seat}))

    def _forward_event(self, envelope: Envelope, *, public: bool) -> None:
        event = envelope.payload.get("event", {})
        audience = None if public else frozenset({self.seat})
        if public and event.get("kind") == "game_started":
            self._send("game_started", {
                "seats": event.get("data", {}).get("seats"),
                "role_counts": event.get("data", {}).get("role_counts"),
            }, persistent=True, audience=None)
            return
        data = {
            "domain_event_id": event.get("id"),
            "kind": event.get("kind"),
            "day": event.get("day"),
            "text": event.get("text"),
            "actor": event.get("actor"),
            "target": event.get("target"),
            "data": event.get("data", {}),
        }
        self._send("public_event" if public else "private_event", data, persistent=True, audience=audience)

    def _forward_chat(self, envelope: Envelope) -> None:
        data = {
            "domain_event_id": None,
            "kind": "chat",
            "day": envelope.payload.get("day"),
            "text": envelope.payload.get("body"),
            "actor": envelope.payload.get("player"),
            "target": None,
        }
        self._send("public_event", data, persistent=True, audience=None)

    def _forward_result(self, envelope: Envelope) -> None:
        result = envelope.payload.get("result", {})
        self.status = "finished"
        self.finished_at = self.server.now()
        self._send("game_over", {
            "winner": result.get("winner"),
            "days": result.get("days"),
            "seats": result.get("seats"),
        }, persistent=True, audience=None)
        self._pump_stop.set()

    def _forward_timeout(self, envelope: Envelope) -> None:
        self._send("timeout", {
            "request_id": self.current_request_id,
            "fallback": _fallback_label(envelope.payload.get("kind")),
        }, persistent=True, audience=frozenset({self.seat}))

    # ------------------------------------------------------------- commands
    def handle_start(self, conn: Connection) -> None:
        if conn.bound_seat != self.seat:
            raise WsError("not_owner", "only the human seat may start the game")
        if self.status != "joined":
            raise WsError("room_already_started", f"room is {self.status}")
        self.start()

    def handle_action(self, conn: Connection, message: dict) -> None:
        if conn is not self.connection:
            raise WsError("forbidden", "this connection is not bound to the room")
        if self.channel.auto_fallback:
            raise WsError("forbidden", "auto-fallback mode: spectating only")
        data = message.get("data") or {}
        request_id: Any = data.get("request_id")
        client_action_id: Any = data.get("client_action_id")
        normalized = _normalize_action(data)

        cached = self.idempotency.get(client_action_id)
        if cached is not None:
            if cached[0] == normalized:
                self._send("action_ack", cached[1], persistent=False, audience=frozenset({self.seat}))
                return
            raise WsError(
                "idempotency_conflict",
                "same client_action_id with different content",
                request_id=request_id,
                client_action_id=client_action_id,
            )

        if request_id != self.current_request_id or self.pending_request is None:
            raise WsError("stale_request", "request_id does not match the pending decision",
                          request_id=request_id, client_action_id=client_action_id)
        issue = _validate_action(data, self.pending_request)
        if issue is not None:
            raise WsError(issue, f"invalid action: {issue}",
                          request_id=request_id, client_action_id=client_action_id)

        ack = {"request_id": request_id, "client_action_id": client_action_id, "accepted": True}
        self.idempotency[client_action_id] = (normalized, ack)
        self.channel.deliver_action(_to_channel_action(data))
        self._send("action_ack", ack, persistent=False, audience=frozenset({self.seat}))

    def handle_replay(self, conn: Connection) -> None:
        if conn.bound_seat != self.seat:
            raise WsError("not_owner", "only the human seat may read the replay")
        if self.status != "finished":
            raise WsError("not_finished", "replay is only available after the game ends")
        if self.transcript is None and self.session is not None and self.session.result is not None:
            self.transcript = record_session(self.session)
        self._send("replay", {"replay": self.transcript}, persistent=False, audience=frozenset({self.seat}))

    def handle_delete(self, conn: Connection) -> None:
        if conn.bound_seat != self.seat:
            raise WsError("not_owner", "only the human seat may delete the room")
        if self.status != "finished":
            raise WsError("not_finished", "delete is only available after the game ends")
        self.status = "deleted"
        self._pump_stop.set()
        self.server._rooms.pop(self.room_id, None)
        self._send("deleted", {"room_id": self.room_id}, persistent=False, audience=frozenset({self.seat}))

    def reconnect(self, conn: Connection, last_stream_seq: int) -> None:
        with self.log_lock:
            high = self.stream_seq
            replay = [
                entry for entry in self.log
                if entry.seq > last_stream_seq
                and (entry.audience is None or self.seat in entry.audience)
            ]
            self.connection = conn
            self.connected = True
            self.disconnect_at = None
            self.last_activity = self.server.now()
            for entry in replay:
                conn.send(json.loads(json.dumps(entry.message)))
        conn.send(_plain("reconnected", {
            "latest_stream_seq": high,
            "replayed_count": len(replay),
        }))

    # ------------------------------------------------------------- helpers
    def _send(self, message_type: str, data: dict, *, persistent: bool, audience: frozenset[int] | None) -> None:
        message: dict[str, Any] = {"type": message_type, "ts": _ts(), "data": data}
        with self.log_lock:
            if persistent:
                message["stream_seq"] = self.stream_seq
                self.stream_seq += 1
                self.log.append(_LogEntry(message["stream_seq"], message, audience))
            if self.connected and self.connection is not None:
                self.connection.send(json.loads(json.dumps(message)))


class WsServer:
    """Owns the room table and routes inbound messages to the right room."""

    def __init__(
        self,
        config: WsConfig | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or WsConfig()
        self.now = now
        self._rooms: dict[str, _Room] = {}
        self._secret = secrets.token_bytes(32)

    # ------------------------------------------------------------ routing
    def handle_inbound(self, conn: Connection, raw: str | dict) -> None:
        message = raw if isinstance(raw, dict) else json.loads(raw)
        message_type = message.get("type")
        data = message.get("data") or {}
        try:
            if message_type == "create_room":
                self._handle_create_room(conn)
            elif message_type == "join":
                self._handle_join(conn, data)
            elif message_type == "reconnect":
                self._handle_reconnect(conn, data)
            elif message_type == "ping":
                conn.send(_plain("pong", {}))
            else:
                room = self._bound_room(conn)
                if message_type == "start":
                    room.handle_start(conn)
                elif message_type == "action":
                    room.handle_action(conn, message)
                elif message_type == "replay":
                    room.handle_replay(conn)
                elif message_type == "delete":
                    room.handle_delete(conn)
                else:
                    raise WsError("server_error", f"unknown message type {message_type!r}")
        except WsError as exc:
            conn.send(self._error(exc))

    def _bound_room(self, conn: Connection) -> _Room:
        room_id = conn.bound_room_id
        room = self._rooms.get(room_id) if room_id is not None else None
        if room is None or conn is not room.connection:
            raise WsError("unauthorized", "connection is not bound to a room")
        return room

    def handle_disconnect(self, conn: Connection) -> None:
        room_id = conn.bound_room_id
        room = self._rooms.get(room_id) if room_id is not None else None
        if room is not None and room.connection is conn:
            room.connected = False
            room.disconnect_at = self.now()
            room.connection = None
        conn.bound_room_id = None
        conn.bound_seat = None

    # ------------------------------------------------------------ handlers
    def _handle_create_room(self, conn: Connection) -> None:
        self.sweep()
        if self._active_count() >= self.config.max_active_rooms:
            raise WsError("room_capacity_reached", "active room limit reached")
        room_id = uuid.uuid4().hex[:8]
        join_secret = secrets.token_urlsafe(24)
        room = _Room(self, room_id, self._digest(join_secret))
        self._rooms[room_id] = room
        conn.send(_plain("room_created", {"room_id": room_id, "join_secret": join_secret}))

    def _handle_join(self, conn: Connection, data: dict) -> None:
        room_id: Any = data.get("room_id")
        join_secret: Any = data.get("join_secret")
        room = self._rooms.get(room_id)
        if room is None:
            raise WsError("room_not_found", "unknown room")
        if room.status != "created":
            raise WsError("seat_taken", "the human seat is already taken")
        if not isinstance(join_secret, str) or self._digest(join_secret) != room.join_secret_digest:
            raise WsError("unauthorized", "invalid join_secret")

        room.join_secret_digest = ""  # one-time consumption
        token = secrets.token_urlsafe(32)
        room.session_token_digest = self._digest(token)
        room.status = "joined"
        room.connection = conn
        room.connected = True
        room.last_activity = self.now()
        conn.bound_room_id = room_id
        conn.bound_seat = room.seat
        conn.send(_plain("joined", {
            "room_id": room_id,
            "seat_id": room.seat,
            "session_token": token,
        }))

    def _handle_reconnect(self, conn: Connection, data: dict) -> None:
        room_id: Any = data.get("room_id")
        seat: Any = data.get("seat_id")
        token: Any = data.get("session_token")
        last_stream_seq = _as_int(data.get("last_stream_seq"))
        room = self._rooms.get(room_id)
        if room is None:
            raise WsError("room_not_found", "unknown room")
        if seat != room.seat:
            raise WsError("forbidden", "seat mismatch")
        if not isinstance(token, str) or self._digest(token) != room.session_token_digest:
            raise WsError("unauthorized", "invalid session_token")

        conn.bound_room_id = room_id
        conn.bound_seat = room.seat
        room.reconnect(conn, last_stream_seq)

    # ------------------------------------------------------------ helpers
    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _error(self, exc: WsError) -> dict:
        data = {"code": exc.code, "message": exc.message}
        if exc.request_id is not None:
            data["request_id"] = exc.request_id
        if exc.client_action_id is not None:
            data["client_action_id"] = exc.client_action_id
        return _plain("error", data)

    def _active_count(self) -> int:
        return sum(1 for room in self._rooms.values() if room.status in ("created", "joined", "running"))

    def sweep(self) -> None:
        """Expire idle un-started rooms and retained finished rooms."""
        now = self.now()
        for room_id in list(self._rooms):
            room = self._rooms[room_id]
            if room.status in ("created", "joined"):
                if now - room.last_activity >= self.config.idle_timeout:
                    self._drop(room_id)
            elif room.status == "finished":
                if room.finished_at is not None and now - room.finished_at >= self.config.retention_days * 86400:
                    self._drop(room_id)
            elif room.status == "deleted":
                self._drop(room_id)

    def _drop(self, room_id: str) -> None:
        room = self._rooms.pop(room_id, None)
        if room is not None:
            room._pump_stop.set()


# ------------------------------------------------------------- helpers
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain(message_type: str, data: dict) -> dict:
    return {"type": message_type, "ts": _ts(), "data": data}


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_action(data: dict) -> str:
    return json.dumps({
        "kind": data.get("kind"),
        "target": data.get("target"),
        "text": data.get("text"),
        "heal": bool(data.get("heal")),
        "poison": data.get("poison"),
        "priority": data.get("priority"),
    }, sort_keys=True, ensure_ascii=False)


def _validate_action(data: dict, pending: dict) -> str | None:
    kind = data.get("kind")
    if kind != pending.get("kind"):
        return "wrong_phase"
    if kind in TARGET_KINDS:
        target = data.get("target")
        if not isinstance(target, int) or target not in pending.get("legal_targets", []):
            return "illegal_target"
        return None
    if kind == "witch_potions":
        heal = bool(data.get("heal"))
        poison = data.get("poison")
        legal = pending.get("legal_targets", [])
        if heal and poison is not None:
            return "illegal_target"
        if heal and not pending.get("can_heal"):
            return "illegal_target"
        if poison is not None and (
            not pending.get("can_poison")
            or not isinstance(poison, int)
            or poison not in legal
        ):
            return "illegal_target"
        return None
    if kind in ("statement", "last_words"):
        return None
    if kind == "bid":
        priority = data.get("priority", 5)
        if not isinstance(priority, int) or not 0 <= priority <= 10:
            return "illegal_target"
        return None
    return "wrong_phase"


def _to_channel_action(data: dict) -> dict:
    target = data.get("target")
    poison = data.get("poison")
    priority = data.get("priority", 5)
    return {
        "target": target if isinstance(target, int) else None,
        "text": str(data.get("text") or ""),
        "heal": bool(data.get("heal")),
        "poison": poison if isinstance(poison, int) else None,
        "priority": priority if isinstance(priority, int) else 5,
    }


def _fallback_label(kind: object) -> str:
    labels = {
        "statement": "skip_statement",
        "last_words": "skip_last_words",
        "vote": "deterministic_vote",
        "night_kill": "ai_suggestion",
        "pack_confirm": "ai_suggestion",
        "night_inspect": "no_inspect",
        "witch_potions": "no_potion",
        "bid": "priority_5",
    }
    return labels.get(str(kind), "deterministic")


# ------------------------------------------------------------- FastAPI
def create_ws_app(server: WsServer | None = None) -> Any:
    """Build a FastAPI app with ``/health`` and ``/ws`` (no REST room API)."""
    if FastAPI is None:  # pragma: no cover - fastapi not installed
        raise RuntimeError(
            "the WebSocket server needs FastAPI; install with `pip install 'ai-werewolf[server]'`"
        )

    server = server or WsServer()
    app = FastAPI(title="AI狼人杀 WebSocket")
    app.state.ws_server = server

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if server.config.allowed_origins and origin not in server.config.allowed_origins:
            await websocket.close(code=1008)
            return
        await websocket.accept()

        loop = asyncio.get_running_loop()
        outbox: asyncio.Queue[dict] = asyncio.Queue()
        conn = StarletteConnection(websocket, loop, outbox)
        bucket = _TokenBucket(
            server.config.rate_limit_per_sec, server.config.rate_limit_burst, now=server.now
        )

        async def sender() -> None:
            while True:
                await websocket.send_json(await outbox.get())

        task = asyncio.create_task(sender())
        try:
            while True:
                raw = await websocket.receive_text()
                if len(raw.encode("utf-8")) > server.config.message_max_bytes:
                    conn.send(_plain("error", {"code": "message_too_large", "message": "message too large"}))
                    continue
                if not bucket.allow():
                    conn.send(_plain("error", {"code": "rate_limited", "message": "rate limit exceeded"}))
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    conn.send(_plain("error", {"code": "server_error", "message": "invalid JSON"}))
                    continue
                server.handle_inbound(conn, message)
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
            server.handle_disconnect(conn)

    return app


class _TokenBucket:
    """A tiny token bucket shared by all connections of one server instance."""

    def __init__(self, rate: float, burst: int, now: Callable[[], float] = time.monotonic) -> None:
        self.rate = rate
        self.burst = burst
        self.now = now
        self.tokens = float(burst)
        self.updated = now()

    def allow(self) -> bool:
        now = self.now()
        self.tokens = min(float(self.burst), self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True
