"""Tests for the game session (human multiplayer, chat, spectate)."""

from __future__ import annotations

import pytest

from ai_werewolf.domain.state import GamePhase
from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.server.room import AIConfig, HumanSeat, RoomConfig
from ai_werewolf.server.session import GameSession, SessionError
from ai_werewolf.transport.memory import InMemoryChannel
from conftest import AutoChannel


def _session(n_humans: int = 1) -> GameSession:
    config = RoomConfig(capacity=4, ai=AIConfig(count=4 - n_humans), seed=1)
    humans = {
        seat: HumanSeat(name=f"H{seat}", channel=AutoChannel())
        for seat in range(n_humans)
    }
    return GameSession(config, humans, lambda pid: RandomBot(pid))


def test_session_runs_human_and_bot_seats_to_completion():
    session = _session(n_humans=2)
    state = session.run()
    assert state.winner is not None
    assert len(session.players) == 4
    assert any(p.name == "human" for p in session.players.values())


def test_session_records_events():
    session = _session(n_humans=1)
    session.run()
    assert session.events
    # the full event log (including secrets) is kept for replay
    assert any(e.is_public() for e in session.events)


def test_chat_is_only_allowed_during_discussion():
    session = _session(n_humans=1)
    with pytest.raises(SessionError):
        session.post_chat(0, "text", "hello before game")
    session.run()
    assert session.referee is not None
    assert session.referee.state.phase is GamePhase.FINISHED
    with pytest.raises(SessionError):
        session.post_chat(0, "text", "hello after game")


def test_spectator_receives_public_broadcasts():
    spectator = InMemoryChannel()
    session = _session(n_humans=1)
    session.add_spectator(spectator)
    session.run()
    kinds = {env.kind for env in spectator.sent}
    assert "event" in kinds
    assert "result" in kinds
