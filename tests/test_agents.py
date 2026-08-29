"""Tests for agents and their robustness to bad model output."""

from __future__ import annotations

import random

from ai_werewolf.agents.llm_agent import LLMAgent, _parse_json
from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.game.roles import Role
from ai_werewolf.game.state import Phase, PlayerInfo, PlayerView
from ai_werewolf.llm.mock import MockProvider
from ai_werewolf.llm.provider import LLMProvider


def _view(role: Role = Role.VILLAGER) -> PlayerView:
    players = tuple(PlayerInfo(i, f"P{i}", True) for i in range(5))
    return PlayerView(
        day=1,
        phase=Phase.DAY_VOTE,
        me_id=0,
        me_name="P0",
        me_role=role,
        players=players,
        living_ids=(0, 1, 2, 3, 4),
        events=(),
        private_notes=(),
        lang="en",
        rng=random.Random(0),
    )


def test_random_agent_always_picks_a_living_other():
    agent = RandomAgent(0)
    view = _view()
    for _ in range(20):
        assert agent.vote(view) in view.others_alive()
        assert agent.night_action(view) in view.others_alive()


def test_llm_agent_with_mock_returns_legal_choices():
    agent = LLMAgent(0, MockProvider(seed=1))
    view = _view(Role.SEER)
    assert agent.night_action(view) in view.others_alive()
    assert agent.vote(view) in view.others_alive()
    assert isinstance(agent.speak(view), str)
    assert agent.speak(view)


class _GarbageProvider(LLMProvider):
    """A provider that always returns unparseable junk."""

    def complete(self, messages):
        return "I refuse to answer in JSON, sorry!"


def test_llm_agent_falls_back_when_model_misbehaves():
    agent = LLMAgent(0, _GarbageProvider())
    view = _view(Role.WEREWOLF)
    choice = agent.vote(view)
    assert choice in view.others_alive()
    # the fallback path should be recorded
    assert agent.reasoning_log
    assert "fallback" in agent.reasoning_log[-1][3]


class _ExplodingProvider(LLMProvider):
    def complete(self, messages):
        raise RuntimeError("network down")


def test_llm_agent_survives_a_provider_exception():
    agent = LLMAgent(0, _ExplodingProvider())
    view = _view(Role.DOCTOR)
    assert agent.night_action(view) in view.living_ids
    assert agent.speak(view)  # non-empty default


def test_parse_json_handles_code_fences_and_prose():
    assert _parse_json('```json\n{"choice": 2}\n```') == {"choice": 2}
    assert _parse_json('Sure! {"choice": 3, "reasoning": "x"} done') == {
        "choice": 3,
        "reasoning": "x",
    }
    assert _parse_json("no json here") is None
    assert _parse_json("") is None
