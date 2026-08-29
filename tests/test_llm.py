"""Tests for the LLM provider layer and the offline mock."""

from __future__ import annotations

import json

import pytest

from ai_werewolf.llm.mock import MockProvider
from ai_werewolf.llm.provider import PRESETS, LLMConfig, LLMError


def _action(kind: str, candidates: str, lang: str = "en") -> list[dict[str, str]]:
    return [{
        "role": "user",
        "content": f"do something [[ACTION kind={kind} "
                   f"candidates={candidates} lang={lang}]]",
    }]


def test_mock_answers_choice_actions_with_legal_json():
    mock = MockProvider(seed=0)
    reply = mock.complete(_action("vote", "1,2,3"))
    data = json.loads(reply)
    assert data["choice"] in (1, 2, 3)


def test_mock_answers_speak_with_a_statement():
    mock = MockProvider(seed=0)
    data = json.loads(mock.complete(_action("speak", "1,2")))
    assert isinstance(data["statement"], str) and data["statement"]


def test_mock_speaks_chinese_when_the_game_is_in_chinese():
    mock = MockProvider(seed=0)
    data = json.loads(mock.complete(_action("speak", "1,2", lang="zh")))
    # at least one CJK character in the statement
    assert any("一" <= ch <= "鿿" for ch in data["statement"])


def test_mock_is_deterministic_for_a_seed():
    a = MockProvider(seed=5).complete(_action("vote", "0,1,2,3"))
    b = MockProvider(seed=5).complete(_action("vote", "0,1,2,3"))
    assert a == b


def test_mock_handles_a_request_without_an_action_trailer():
    data = json.loads(MockProvider().complete([{"role": "user", "content": "hi"}]))
    assert "statement" in data


def test_llm_config_from_env_with_preset(monkeypatch):
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "deepseek")
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "secret")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "deepseek-chat")
    monkeypatch.delenv("AIWEREWOLF_BASE_URL", raising=False)
    config = LLMConfig.from_env(env_file=None)
    assert config.base_url == PRESETS["deepseek"]
    assert config.model == "deepseek-chat"


def test_llm_config_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "not-a-real-provider")
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "k")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "m")
    monkeypatch.delenv("AIWEREWOLF_BASE_URL", raising=False)
    with pytest.raises(LLMError):
        LLMConfig.from_env(env_file=None)


def test_llm_config_requires_all_fields(monkeypatch):
    for var in (
        "AIWEREWOLF_PROVIDER",
        "AIWEREWOLF_BASE_URL",
        "AIWEREWOLF_API_KEY",
        "AIWEREWOLF_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(LLMError):
        LLMConfig.from_env(env_file=None)


def test_api_key_is_read_from_environment_not_arguments(monkeypatch):
    """The API key must come only from the environment."""
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "openai")
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "env-secret")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "gpt-4o-mini")
    monkeypatch.delenv("AIWEREWOLF_BASE_URL", raising=False)
    config = LLMConfig.from_env(env_file=None)
    assert config.api_key == "env-secret"
