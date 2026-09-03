"""Tests for the single-human WebSocket runtime.

These drive the transport-agnostic :class:`WsServer` through
:class:`MemoryConnection` with a deterministic MockProvider, so they run
offline and fast while still exercising the full protocol, idempotency,
reconnect, timeouts and lifecycle rules.
"""

from __future__ import annotations

import time

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.server.ws import MemoryConnection, WsConfig, WsServer, create_ws_app
from ai_werewolf.transport.queue import QueueChannel

TARGET_KINDS = {"night_kill", "pack_confirm", "night_inspect", "vote"}


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def make_server(clock: FakeClock | None = None, **overrides) -> WsServer:
    config = WsConfig(provider_factory=lambda seed: MockProvider(seed=seed), **overrides)
    return WsServer(config=config, now=clock or FakeClock(0.0))


def auto_action(data: dict) -> dict:
    kind = data["kind"]
    out: dict = {"kind": kind}
    if kind in TARGET_KINDS:
        targets = data.get("suggestions") or data.get("legal_targets") or []
        out["target"] = targets[0] if targets else None
    elif kind == "witch_potions":
        legal = data.get("legal_targets") or []
        out["heal"] = False
        out["poison"] = legal[0] if data.get("can_poison") and legal else None
    elif kind in ("statement", "last_words"):
        out["text"] = "auto statement"
    elif kind == "bid":
        out["priority"] = 5
    return out


def create_and_join(server: WsServer, conn: MemoryConnection) -> tuple[str, str]:
    server.handle_inbound(conn, {"type": "create_room", "data": {}})
    created = conn.next()
    assert created["type"] == "room_created"
    room_id = created["data"]["room_id"]
    join_secret = created["data"]["join_secret"]

    server.handle_inbound(conn, {
        "type": "join",
        "data": {"room_id": room_id, "join_secret": join_secret},
    })
    joined = conn.next()
    assert joined["type"] == "joined"
    assert joined["data"]["seat_id"] == 0
    return room_id, joined["data"]["session_token"]


def play_to_end(server: WsServer, conn: MemoryConnection) -> list[dict]:
    """Respond to every decision request until ``game_over``."""
    server.handle_inbound(conn, {"type": "start", "data": {}})
    seen: list[dict] = []
    counter = 0
    while True:
        message = conn.next(timeout=10.0)
        seen.append(message)
        if message["type"] == "decision_request":
            counter += 1
            data = message["data"]
            action = auto_action(data)
            action["request_id"] = data["request_id"]
            action["client_action_id"] = f"client-{counter}"
            server.handle_inbound(conn, {"type": "action", "data": action})
        elif message["type"] == "game_over":
            return seen


def next_of_type(messages: list[dict], message_type: str) -> dict:
    for message in messages:
        if message["type"] == message_type:
            return message
    raise AssertionError(f"no {message_type!r} in {[m['type'] for m in messages]}")


# ------------------------------------------------------------------ lifecycle
def test_full_game_lifecycle() -> None:
    server = make_server()
    conn = MemoryConnection()
    room_id, _token = create_and_join(server, conn)
    seen = play_to_end(server, conn)

    assert next_of_type(seen, "game_started")
    assert next_of_type(seen, "private_event")
    assert next_of_type(seen, "public_event")
    game_over = next_of_type(seen, "game_over")
    assert game_over["data"]["winner"] in ("village", "werewolves")

    server.handle_inbound(conn, {"type": "replay", "data": {"room_id": room_id}})
    replay = conn.next()
    assert replay["type"] == "replay"
    assert 0 < len(replay["data"]["replay"]["traces"]) <= 6

    server.handle_inbound(conn, {"type": "delete", "data": {"room_id": room_id}})
    deleted = conn.next()
    assert deleted["type"] == "deleted"
    assert deleted["data"]["room_id"] == room_id


def test_second_join_is_rejected() -> None:
    server = make_server()
    conn = MemoryConnection()
    room_id, _ = create_and_join(server, conn)

    other = MemoryConnection()
    server.handle_inbound(other, {
        "type": "join",
        "data": {"room_id": room_id, "join_secret": "whatever"},
    })
    error = other.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "seat_taken"


def test_join_with_wrong_secret_is_unauthorized() -> None:
    server = make_server()
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {}})
    room_id = conn.next()["data"]["room_id"]

    other = MemoryConnection()
    server.handle_inbound(other, {
        "type": "join",
        "data": {"room_id": room_id, "join_secret": "wrong-secret"},
    })
    error = other.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "unauthorized"


def test_capacity_limit() -> None:
    server = make_server(max_active_rooms=2)
    for _ in range(2):
        conn = MemoryConnection()
        server.handle_inbound(conn, {"type": "create_room", "data": {}})
        assert conn.next()["type"] == "room_created"

    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {}})
    error = conn.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "room_capacity_reached"


# ------------------------------------------------------------- idempotency
def test_duplicate_action_is_idempotent() -> None:
    server = make_server()
    conn = MemoryConnection()
    create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})

    # read until the first decision request
    while True:
        message = conn.next(timeout=10.0)
        if message["type"] == "decision_request":
            break

    data = message["data"]
    action = auto_action(data)
    action["request_id"] = data["request_id"]
    action["client_action_id"] = "dup-1"
    server.handle_inbound(conn, {"type": "action", "data": action})
    server.handle_inbound(conn, {"type": "action", "data": dict(action)})

    acks: list[dict] = []
    deadline = time.monotonic() + 5.0
    while len(acks) < 2 and time.monotonic() < deadline:
        reply = conn.next(timeout=5.0)
        if reply["type"] == "action_ack":
            acks.append(reply)
        if reply["type"] == "error" and reply["data"]["code"] == "idempotency_conflict":
            pytest.fail("duplicate action was not treated as idempotent")
    assert len(acks) == 2
    assert acks[0]["data"]["client_action_id"] == "dup-1"
    assert acks[1]["data"]["client_action_id"] == "dup-1"


def test_same_id_different_content_is_conflict() -> None:
    server = make_server()
    conn = MemoryConnection()
    create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})

    while True:
        message = conn.next(timeout=10.0)
        if message["type"] == "decision_request":
            break

    data = message["data"]
    action = auto_action(data)
    action["request_id"] = data["request_id"]
    action["client_action_id"] = "dup-2"
    server.handle_inbound(conn, {"type": "action", "data": action})

    different = dict(action)
    different["kind"] = "statement"
    different["text"] = "different content"
    server.handle_inbound(conn, {"type": "action", "data": different})

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        reply = conn.next(timeout=5.0)
        if reply["type"] == "error":
            assert reply["data"]["code"] == "idempotency_conflict"
            return
    pytest.fail("expected idempotency_conflict error")


# ------------------------------------------------------------- validation
def test_stale_request_and_illegal_target() -> None:
    server = make_server()
    conn = MemoryConnection()
    create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})

    while True:
        message = conn.next(timeout=10.0)
        if message["type"] == "decision_request":
            break

    data = message["data"]
    legal = data.get("legal_targets") or []

    server.handle_inbound(conn, {"type": "action", "data": {
        "kind": data["kind"],
        "request_id": "wrong-request",
        "client_action_id": "stale-1",
        "target": legal[0] if legal else None,
    }})
    stale = conn.next()
    assert stale["type"] == "error"
    assert stale["data"]["code"] == "stale_request"

    if data["kind"] in TARGET_KINDS:
        illegal = {
            "kind": data["kind"],
            "request_id": data["request_id"],
            "client_action_id": "illegal-1",
            "target": 999,
        }
    elif data["kind"] == "witch_potions":
        illegal = {
            "kind": "witch_potions",
            "request_id": data["request_id"],
            "client_action_id": "illegal-1",
            "heal": True,
            "poison": 999,
        }
    else:
        return  # statement/bid/last_words have no target to reject here

    server.handle_inbound(conn, {"type": "action", "data": illegal})
    illegal_reply = conn.next()
    assert illegal_reply["type"] == "error"
    assert illegal_reply["data"]["code"] == "illegal_target"


# ------------------------------------------------------------- reconnect
def test_reconnect_replays_missed_messages() -> None:
    server = make_server()
    conn = MemoryConnection()
    room_id, token = create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})

    # let some messages accumulate, then drop
    while True:
        message = conn.next(timeout=10.0)
        if message["type"] == "game_started":
            break

    server.handle_disconnect(conn)

    other = MemoryConnection()
    server.handle_inbound(other, {
        "type": "reconnect",
        "data": {
            "room_id": room_id,
            "seat_id": 0,
            "session_token": token,
            "last_stream_seq": 0,
        },
    })
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        reply = other.next(timeout=10.0)
        if reply["type"] == "reconnected":
            assert reply["data"]["latest_stream_seq"] >= 1
            assert reply["data"]["replayed_count"] >= 1
            return
    pytest.fail("expected reconnected message")


def test_reconnect_with_bad_token_is_unauthorized() -> None:
    server = make_server()
    conn = MemoryConnection()
    room_id, _token = create_and_join(server, conn)

    other = MemoryConnection()
    server.handle_inbound(other, {
        "type": "reconnect",
        "data": {
            "room_id": room_id,
            "seat_id": 0,
            "session_token": "bad-token",
            "last_stream_seq": 0,
        },
    })
    error = other.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "unauthorized"


# ------------------------------------------------------------- timeout
def test_decision_times_out_and_falls_back() -> None:
    server = make_server(timeouts={"vote": 0.1, "statement": 0.1, "last_words": 0.1,
                                   "bid": 0.1, "night_kill": 0.1, "pack_confirm": 0.1,
                                   "night_inspect": 0.1, "witch_potions": 0.1})
    conn = MemoryConnection()
    create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})

    # never answer; the game must still finish via deterministic fallbacks
    deadline = time.monotonic() + 30.0
    saw_timeout = False
    while time.monotonic() < deadline:
        message = conn.next(timeout=30.0)
        if message["type"] == "timeout":
            saw_timeout = True
        if message["type"] == "game_over":
            assert saw_timeout
            return
    pytest.fail("game did not finish after timeouts")


def test_auto_fallback_after_disconnect_grace() -> None:
    clock = FakeClock()
    server = make_server(clock=clock, disconnect_grace=0.5)
    conn = MemoryConnection()
    room_id, _ = create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})

    while True:
        message = conn.next(timeout=10.0)
        if message["type"] == "decision_request":
            break

    server.handle_disconnect(conn)
    clock.advance(0.6)
    time.sleep(0.4)  # let the pump observe the expired grace
    room = server._rooms[room_id]
    assert room.channel.auto_fallback is True


# ------------------------------------------------------------- lifecycle rules
def test_replay_and_delete_before_finish_are_rejected() -> None:
    server = make_server()
    conn = MemoryConnection()
    create_and_join(server, conn)

    server.handle_inbound(conn, {"type": "replay", "data": {}})
    assert conn.next()["data"]["code"] == "not_finished"

    server.handle_inbound(conn, {"type": "delete", "data": {}})
    assert conn.next()["data"]["code"] == "not_finished"


def test_start_twice_is_rejected() -> None:
    server = make_server()
    conn = MemoryConnection()
    create_and_join(server, conn)
    server.handle_inbound(conn, {"type": "start", "data": {}})
    server.handle_inbound(conn, {"type": "start", "data": {}})
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        reply = conn.next(timeout=5.0)
        if reply["type"] == "error" and reply["data"]["code"] == "room_already_started":
            return
    pytest.fail("expected room_already_started error")


def test_unbound_connection_is_unauthorized() -> None:
    server = make_server()
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "start", "data": {}})
    error = conn.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "unauthorized"


# ------------------------------------------------------------- sweep/expiry
def test_idle_room_expires() -> None:
    clock = FakeClock()
    server = make_server(clock=clock, idle_timeout=600)
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {}})
    room_id = conn.next()["data"]["room_id"]

    clock.advance(601)
    server.sweep()

    other = MemoryConnection()
    server.handle_inbound(other, {
        "type": "join",
        "data": {"room_id": room_id, "join_secret": "anything"},
    })
    error = other.next()
    assert error["data"]["code"] == "room_not_found"


def test_finished_room_retained_then_expired() -> None:
    clock = FakeClock()
    server = make_server(clock=clock)
    conn = MemoryConnection()
    room_id, _ = create_and_join(server, conn)
    play_to_end(server, conn)

    # retained: replay still works
    server.handle_inbound(conn, {"type": "replay", "data": {"room_id": room_id}})
    assert conn.next()["type"] == "replay"

    clock.advance(31 * 86400)
    server.sweep()
    assert room_id not in server._rooms


# ------------------------------------------------------------- security
def test_tokens_never_leak_into_persistent_messages() -> None:
    server = make_server()
    conn = MemoryConnection()
    room_id, token = create_and_join(server, conn)
    seen = play_to_end(server, conn)

    import json

    for message in seen:
        if "stream_seq" not in message:  # non-persistent messages are exempt
            continue
        blob = json.dumps(message, ensure_ascii=False)
        assert token not in blob
        assert "AIWEREWOLF" not in blob
        assert "api_key" not in blob.lower()


# ------------------------------------------------------------- queue channel
def test_queue_channel_timeout_and_auto_fallback() -> None:
    from ai_werewolf.transport.channel import Envelope

    channel = QueueChannel(timeouts={"vote": 0.05})
    channel.send(Envelope("decision", payload={"request": {"kind": "vote"}}))
    with pytest.raises(TimeoutError):
        channel.recv()

    channel.auto_fallback = True
    channel.send(Envelope("decision", payload={"request": {"kind": "vote"}}))
    with pytest.raises(TimeoutError):
        channel.recv()


# ------------------------------------------------------------- fastapi adapter
@pytest.mark.filterwarnings("ignore::UserWarning")
def test_fastapi_adapter_runs_full_game() -> None:
    from fastapi.testclient import TestClient

    server = make_server()
    app = create_ws_app(server)
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "create_room", "data": {}})
        created = ws.receive_json()
        room_id = created["data"]["room_id"]
        join_secret = created["data"]["join_secret"]

        ws.send_json({"type": "join", "data": {
            "room_id": room_id, "join_secret": join_secret,
        }})
        joined = ws.receive_json()
        assert joined["type"] == "joined"

        ws.send_json({"type": "start", "data": {"room_id": room_id}})
        counter = 0
        while True:
            message = ws.receive_json()
            if message["type"] == "decision_request":
                counter += 1
                action = auto_action(message["data"])
                action["request_id"] = message["data"]["request_id"]
                action["client_action_id"] = f"ws-{counter}"
                ws.send_json({"type": "action", "data": action})
            elif message["type"] == "game_over":
                assert message["data"]["winner"] in ("village", "werewolves")
                break
    assert counter >= 0
