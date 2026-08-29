"""Tests for the agent reasoning trace surfaced into the event log."""

from __future__ import annotations

import json

from ai_werewolf.agents.base import Agent
from ai_werewolf.agents.llm_agent import LLMAgent
from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.events import EventType
from ai_werewolf.game.state import GameConfig
from ai_werewolf.llm.mock import MockProvider
from ai_werewolf.transcript import to_json


def _llm_game(seed: int = 1):
    """A finished game played entirely by LLMAgents over the mock provider."""
    provider = MockProvider(seed=0)
    config = GameConfig.standard(7, seed=seed)
    return GameEngine(config, lambda pid, _role: LLMAgent(pid, provider)).run()


def test_base_agent_last_reasoning_is_none():
    class _Bare(Agent):
        def night_action(self, view): return view.living_ids[0]
        def vote(self, view): return view.others_alive()[0]
        def speak(self, view): return "..."

    assert _Bare(0).last_reasoning() is None


def test_random_agent_emits_no_reasoning_events():
    config = GameConfig.standard(7, seed=2)
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()
    assert not any(e.type is EventType.AGENT_REASONING for e in result.events)


def test_llm_agent_emits_reasoning_events():
    result = _llm_game(seed=3)
    reasoning = [e for e in result.events if e.type is EventType.AGENT_REASONING]
    # the mock provider yields a reasoning string for every choice action, so
    # the game must produce many reasoning events
    assert len(reasoning) >= 10


def test_reasoning_events_are_private_to_the_actor():
    result = _llm_game(seed=4)
    for e in (e for e in result.events if e.type is EventType.AGENT_REASONING):
        assert e.actor is not None
        assert e.public is False
        assert e.visible_to == frozenset({e.actor})


def test_reasoning_event_data_carries_decision_and_reasoning():
    result = _llm_game(seed=5)
    reasoning = [e for e in result.events if e.type is EventType.AGENT_REASONING]
    expected = {"kill", "inspect", "protect", "vote", "shoot"}
    seen = {e.data["decision"] for e in reasoning}
    # at minimum vote always happens; kill/inspect/protect typically too
    assert seen <= expected
    assert "vote" in seen
    for e in reasoning:
        assert isinstance(e.data["reasoning"], str) and e.data["reasoning"]


def test_reasoning_survives_the_transcript_round_trip():
    result = _llm_game(seed=6)
    transcript = to_json(result)
    kinds = {ev["type"] for ev in transcript["events"]}
    assert "agent_reasoning" in kinds
    sample = next(ev for ev in transcript["events"] if ev["type"] == "agent_reasoning")
    assert sample["data"]["decision"] in {"kill", "inspect", "protect", "vote", "shoot"}
    assert sample["data"]["reasoning"]
    # JSON-serialisable end-to-end
    json.dumps(transcript)


def test_empty_reasoning_string_is_not_emitted():
    """If the agent's reasoning is blank, no event is generated."""

    class _Mute(LLMAgent):
        def last_reasoning(self):
            return "   "  # whitespace only — should be treated as no reasoning

    provider = MockProvider(seed=0)
    config = GameConfig.standard(7, seed=7)
    result = GameEngine(config, lambda pid, _: _Mute(pid, provider)).run()
    assert not any(e.type is EventType.AGENT_REASONING for e in result.events)
