"""Tests for the AI provider layer and the offline mock."""

from __future__ import annotations

import json

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.provider import (
    PRESETS,
    ModelConfig,
    OpenAICompatProvider,
    Prompt,
    ProviderError,
)


def _prompt(kind: str, candidates: list[int], lang: str = "zh") -> Prompt:
    return Prompt(
        system="sys",
        user="u",
        hint={"kind": kind, "candidates": candidates, "lang": lang},
    )


def test_mock_choice_is_legal_and_deterministic():
    a = MockProvider(seed=5).complete(_prompt("vote", [1, 2, 3]))
    b = MockProvider(seed=5).complete(_prompt("vote", [1, 2, 3]))
    assert a == b
    assert json.loads(a)["choice"] in (1, 2, 3)


def test_mock_statement_and_witch_and_bid():
    statement = json.loads(MockProvider(seed=0).complete(_prompt("statement", [1, 2])))
    assert statement["statement"]
    assert "private_suspicion" in statement
    witch = json.loads(MockProvider(seed=0).complete(_prompt("witch", [1, 2, 3])))
    assert witch["heal"] is False
    assert witch["poison"] is None
    bid = json.loads(MockProvider(seed=0).complete(_prompt("bid", [])))
    assert 0 <= bid["priority"] <= 10


def test_mock_without_candidates_is_safe():
    data = json.loads(MockProvider().complete(Prompt("sys", "hi")))
    assert isinstance(data, dict)


def test_model_config_from_env_preset(monkeypatch):
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "deepseek")
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "secret")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "deepseek-chat")
    monkeypatch.delenv("AIWEREWOLF_BASE_URL", raising=False)
    config = ModelConfig.from_env(env_file=None)
    assert config.base_url == PRESETS["deepseek"]


def test_model_config_rejects_unknown_preset(monkeypatch):
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "not-real")
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "k")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "m")
    monkeypatch.delenv("AIWEREWOLF_BASE_URL", raising=False)
    with pytest.raises(ProviderError):
        ModelConfig.from_env(env_file=None)


def test_model_config_requires_all_fields(monkeypatch):
    for var in (
        "AIWEREWOLF_PROVIDER",
        "AIWEREWOLF_BASE_URL",
        "AIWEREWOLF_API_KEY",
        "AIWEREWOLF_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ProviderError):
        ModelConfig.from_env(env_file=None)


def test_openai_provider_sends_thinking_off_explicitly(monkeypatch):
    import httpx

    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    config = ModelConfig(
        base_url="https://api.deepseek.com",
        api_key="secret-key",
        model="deepseek-v4-flash",
        thinking=False,
        response_format={"type": "json_object"},
    )
    provider = OpenAICompatProvider(config)
    assert provider.complete(Prompt("sys", "user")) == "ok"
    assert captured["payload"]["thinking"] is False
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert "api_key" not in captured["payload"]
    assert captured["headers"]["Authorization"] == "Bearer secret-key"


def test_openai_provider_can_enable_thinking(monkeypatch):
    import httpx

    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    config = ModelConfig(
        base_url="https://api.deepseek.com", api_key="k", model="deepseek-v4-flash", thinking=True
    )
    OpenAICompatProvider(config).complete(Prompt("sys", "user"))
    assert captured["payload"]["thinking"] is True
