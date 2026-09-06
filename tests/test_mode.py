"""Tests for AI mode selection and the no-silent-fallback contract."""

from __future__ import annotations

import pytest

from ai_werewolf.ai.provider import ProviderError, real_model_available
from ai_werewolf.server.room import AIConfig
from ai_werewolf.server.ws import MemoryConnection, WsServer


def test_health_reports_mode_without_key() -> None:
    # real_model_available() 只返回 bool，configured_model() 只返回模型名
    assert isinstance(real_model_available(), bool)


def test_aiconfig_real_mode_raises_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "")
    monkeypatch.setenv("AIWEREWOLF_BASE_URL", "")
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "")
    with pytest.raises(ProviderError):
        AIConfig(count=6, policy="llm", ai_mode="real").resolve_provider(seed=0)


def test_create_room_real_unconfigured_is_provider_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "")
    monkeypatch.setenv("AIWEREWOLF_BASE_URL", "")
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "")
    server = WsServer()
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {"ai_mode": "real"}})
    error = conn.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "provider_unavailable"


def test_create_room_offline_returns_effective_mode() -> None:
    server = WsServer()
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {"ai_mode": "offline"}})
    created = conn.next()
    assert created["type"] == "room_created"
    assert created["data"]["effective_ai_mode"] == "offline"


def test_create_room_rejects_unknown_mode() -> None:
    server = WsServer()
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {"ai_mode": "hybrid"}})
    error = conn.next()
    assert error["type"] == "error"
    assert error["data"]["code"] == "server_error"


def test_create_room_data_never_contains_key_or_provider() -> None:
    # 客户端只提交 ai_mode；错误消息/回包也不得包含 Key 值或 Provider 地址
    server = WsServer()
    conn = MemoryConnection()
    server.handle_inbound(conn, {"type": "create_room", "data": {"ai_mode": "offline"}})
    created = conn.next()
    blob = str(created)
    assert "AIWEREWOLF_API_KEY" not in blob
    assert "api.deepseek.com" not in blob
    assert "Authorization" not in blob
