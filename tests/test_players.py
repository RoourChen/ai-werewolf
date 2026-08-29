"""Tests for player policies."""

from __future__ import annotations

import random

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.provider import Prompt, Provider
from ai_werewolf.domain.actions import ActionKind
from ai_werewolf.domain.roles import Role
from ai_werewolf.domain.state import DecisionRequest, GamePhase, PlayerView, PublicSeat
from ai_werewolf.players.llm_bot import LLMBot, _parse_json
from ai_werewolf.players.random_bot import RandomBot


def _view(role: Role = Role.VILLAGER) -> PlayerView:
    seats = tuple(PublicSeat(i, f"P{i}", True) for i in range(5))
    return PlayerView(
        me=0,
        day=1,
        phase=GamePhase.VOTING,
        language="zh",
        my_role=role,
        seats=seats,
        living=(0, 1, 2, 3, 4),
        events=(),
        secrets=(),
        rng=random.Random(0),
    )


def test_random_bot_picks_legal_targets():
    bot = RandomBot(0)
    view = _view()
    request = DecisionRequest(ActionKind.VOTE, 0, legal_targets=(1, 2, 3, 4))
    for _ in range(20):
        assert bot.decide(view, request).target in (1, 2, 3, 4)


def test_llm_bot_with_mock_returns_legal_choices():
    bot = LLMBot(0, MockProvider(seed=1))
    view = _view(Role.SEER)
    request = DecisionRequest(ActionKind.NIGHT_INSPECT, 0, legal_targets=(1, 2, 3, 4))
    assert bot.decide(view, request).target in (1, 2, 3, 4)
    statement = bot.decide(view, DecisionRequest(ActionKind.STATEMENT, 0))
    assert statement.text


class _GarbageProvider(Provider):
    def complete(self, prompt: Prompt) -> str:
        return "sorry, no JSON here!"


def test_llm_bot_falls_back_on_garbage():
    bot = LLMBot(0, _GarbageProvider())
    view = _view(Role.WEREWOLF)
    request = DecisionRequest(ActionKind.VOTE, 0, legal_targets=(1, 2, 3, 4))
    assert bot.decide(view, request).target in (1, 2, 3, 4)


class _ExplodingProvider(Provider):
    def complete(self, prompt: Prompt) -> str:
        raise RuntimeError("network down")


def test_llm_bot_survives_provider_exception():
    bot = LLMBot(0, _ExplodingProvider())
    view = _view(Role.GUARD)
    request = DecisionRequest(ActionKind.NIGHT_PROTECT, 0, legal_targets=(0, 1, 2, 3, 4))
    assert bot.decide(view, request).target in (0, 1, 2, 3, 4)


def test_parse_json_handles_fences_and_prose():
    assert _parse_json('```json\n{"choice": 2}\n```') == {"choice": 2}
    assert _parse_json('Sure! {"choice": 3, "reasoning": "x"} done') == {
        "choice": 3,
        "reasoning": "x",
    }
    assert _parse_json("no json") is None
    assert _parse_json("") is None
