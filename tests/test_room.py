"""Tests for rooms."""

from __future__ import annotations

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.server.room import AIConfig, Room, RoomConfig, RoomError, RoomStatus
from conftest import AutoChannel


def _room() -> Room:
    return Room(RoomConfig(capacity=7, ai=AIConfig(count=6)))


def test_room_fills_and_reaches_ready():
    room = _room()
    assert room.status is RoomStatus.OPEN
    assert room.add_human("Alice", AutoChannel()) == 0
    assert room.is_full
    assert room.status is RoomStatus.READY


def test_room_rejects_overflow():
    room = _room()
    room.add_human("Alice", AutoChannel())
    with pytest.raises(RoomError):
        room.add_human("Bob", AutoChannel())


def test_room_rejects_join_when_not_open():
    room = _room()
    room.add_human("Alice", AutoChannel())
    room.status = RoomStatus.PLAYING
    with pytest.raises(RoomError):
        room.add_human("Bob", AutoChannel())


def test_remove_human_reopens_the_room():
    room = _room()
    seat = room.add_human("Alice", AutoChannel())
    room.remove_human(seat)
    assert not room.is_full
    assert room.status is RoomStatus.OPEN


def test_start_requires_ready():
    room = _room()  # no human yet
    with pytest.raises(RoomError):
        room.start()


def test_start_builds_six_real_llm_bots_from_aiconfig():
    room = Room(RoomConfig(
        capacity=7,
        ai=AIConfig(count=6, policy="llm", provider=MockProvider(seed=0)),
        seed=1,
    ))
    room.add_human("Alice", AutoChannel())
    session = room.start()
    assert room.status is RoomStatus.FINISHED
    assert session.result is not None
    assert session.result.winner is not None
    assert sum(1 for p in session.players.values() if p.name == "llm") == 6
