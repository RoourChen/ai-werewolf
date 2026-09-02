"""Tests for the game session (1 human + 6 AI, chat, spectate, traces)."""

from __future__ import annotations

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.domain.state import GamePhase
from ai_werewolf.server.room import AIConfig, HumanSeat, RoomConfig
from ai_werewolf.server.session import GameSession, SessionError
from ai_werewolf.transport.memory import InMemoryChannel
from conftest import AutoChannel


def _session() -> GameSession:
    config = RoomConfig(
        capacity=7,
        ai=AIConfig(count=6, policy="llm", provider=MockProvider(seed=0)),
        seed=1,
    )
    humans = {0: HumanSeat(name="Alice", channel=AutoChannel())}
    return GameSession(config, humans)


def test_session_runs_human_and_six_bots_to_completion():
    session = _session()
    state = session.run()
    assert state.winner is not None
    assert len(session.players) == 7
    assert any(p.name == "human" for p in session.players.values())
    assert sum(1 for p in session.players.values() if p.name == "llm") == 6


def test_session_collects_traces_for_every_ai():
    session = _session()
    session.run()
    assert session.traces  # every AI decision was captured
    for records in session.traces.values():
        assert records
        for record in records:
            assert record.kind


def test_session_records_events():
    session = _session()
    session.run()
    assert session.events
    assert any(e.is_public() for e in session.events)


def test_chat_is_only_allowed_during_discussion():
    session = _session()
    with pytest.raises(SessionError):
        session.post_chat(0, "text", "hello before game")
    session.run()
    assert session.referee is not None
    assert session.referee.state.phase is GamePhase.FINISHED
    with pytest.raises(SessionError):
        session.post_chat(0, "text", "hello after game")


def test_spectator_receives_public_broadcasts():
    spectator = InMemoryChannel()
    session = _session()
    session.add_spectator(spectator)
    session.run()
    kinds = {env.kind for env in spectator.sent}
    assert "event" in kinds
    assert "result" in kinds
