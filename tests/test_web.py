"""Tests for the static web client and the data it consumes."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.server.ws import MemoryConnection, WsConfig, WsServer, create_ws_app

_STATIC_DIR = Path(__file__).resolve().parent.parent / "ai_werewolf" / "static"


def _server() -> WsServer:
    return WsServer(config=WsConfig(provider_factory=lambda s: MockProvider(seed=s)))


def _start_room(server: WsServer, conn: MemoryConnection) -> str:
    server.handle_inbound(conn, {"type": "create_room", "data": {}})
    created = conn.next()
    room_id = created["data"]["room_id"]
    server.handle_inbound(conn, {
        "type": "join",
        "data": {"room_id": room_id, "join_secret": created["data"]["join_secret"]},
    })
    assert conn.next()["type"] == "joined"
    server.handle_inbound(conn, {"type": "start", "data": {"room_id": room_id}})
    return room_id


def _next_of_type(conn: MemoryConnection, message_type: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = conn.next(timeout=timeout)
        if message["type"] == message_type:
            return message
    raise AssertionError(f"no {message_type!r} within {timeout}s")


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_static_files_served() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_ws_app(_server()))
    assert client.get("/health").json() == {"status": "ok"}

    index = client.get("/")
    assert index.status_code == 200
    assert "AI狼人杀" in index.text

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "create-btn" in js.text

    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert ".bar-fill" in css.text


def test_index_html_references_client_elements() -> None:
    index = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for element_id in (
        "status", "create-btn", "start-btn", "phase", "role", "seats",
        "decision", "log", "copilot", "result", "replay-btn", "replay",
    ):
        assert f'id="{element_id}"' in index, element_id


def test_game_started_includes_seat_list() -> None:
    server = _server()
    conn = MemoryConnection()
    _start_room(server, conn)
    message = _next_of_type(conn, "game_started")
    seats = message["data"]["seats"]
    assert len(seats) == 7
    assert all("id" in s and "name" in s and "alive" in s for s in seats)


def test_decision_request_includes_structured_copilot() -> None:
    server = _server()
    conn = MemoryConnection()
    _start_room(server, conn)
    message = _next_of_type(conn, "decision_request")
    data = message["data"]

    assert data.get("copilot")  # text explanation still present
    copilot = data.get("copilot_data", {})
    assert "recommended_vote" in copilot
    assert "rationale" in copilot

    suspicions = copilot.get("suspicions", [])
    assert suspicions
    probabilities = [s["probability"] for s in suspicions]
    assert probabilities == sorted(probabilities, reverse=True)
    assert all(
        {"player_id", "name", "probability", "reasons"} <= set(s)
        for s in suspicions
    )
