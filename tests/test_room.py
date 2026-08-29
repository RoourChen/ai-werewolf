"""Tests for rooms."""

from __future__ import annotations

import pytest

from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.server.room import AIConfig, Room, RoomConfig, RoomError, RoomStatus
from conftest import AutoChannel


def test_room_fills_and_reaches_ready():
    room = Room(RoomConfig(capacity=4, ai=AIConfig(count=2)))
    assert room.status is RoomStatus.OPEN
    assert room.add_human("Alice", AutoChannel()) == 0
    assert room.add_human("Bob", AutoChannel()) == 1
    assert room.is_full
    assert room.status is RoomStatus.READY


def test_room_rejects_overflow():
    room = Room(RoomConfig(capacity=4, ai=AIConfig(count=2)))
    room.add_human("Alice", AutoChannel())
    room.add_human("Bob", AutoChannel())
    with pytest.raises(RoomError):
        room.add_human("Carol", AutoChannel())


def test_room_rejects_join_when_not_open():
    room = Room(RoomConfig(capacity=4, ai=AIConfig(count=2)))
    room.add_human("Alice", AutoChannel())
    room.add_human("Bob", AutoChannel())
    room.status = RoomStatus.PLAYING
    with pytest.raises(RoomError):
        room.add_human("Carol", AutoChannel())


def test_remove_human_reopens_the_room():
    room = Room(RoomConfig(capacity=4, ai=AIConfig(count=2)))
    seat = room.add_human("Alice", AutoChannel())
    room.add_human("Bob", AutoChannel())
    room.remove_human(seat)
    assert not room.is_full
    assert room.status is RoomStatus.OPEN


def test_start_requires_ready():
    room = Room(RoomConfig(capacity=4, ai=AIConfig(count=2)))
    with pytest.raises(RoomError):
        room.start(lambda pid: RandomBot(pid))


def test_start_runs_a_session_to_completion():
    room = Room(RoomConfig(capacity=4, ai=AIConfig(count=3), seed=1))
    room.add_human("Alice", AutoChannel())
    session = room.start(lambda pid: RandomBot(pid))
    assert room.status is RoomStatus.FINISHED
    assert session.result is not None  # type: ignore[attr-defined]
    assert session.result.winner is not None  # type: ignore[attr-defined]
