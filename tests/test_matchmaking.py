"""Tests for matchmaking."""

from __future__ import annotations

import pytest

from ai_werewolf.server.matchmaking import Matchmaker, MatchmakingError
from ai_werewolf.server.room import AIConfig, RoomConfig
from conftest import AutoChannel


def _maker() -> Matchmaker:
    return Matchmaker(RoomConfig(capacity=4, ai=AIConfig(count=2)))


def test_matchmaker_forms_rooms_from_the_queue():
    maker = _maker()
    for i in range(4):
        maker.enqueue(i, f"P{i}", AutoChannel())
    assert maker.queue_size() == 4
    rooms = maker.form_rooms()
    assert len(rooms) == 2  # 4 humans, 2 per room
    assert maker.queue_size() == 0
    assert all(room.status.value == "ready" for room in rooms)


def test_matchmaker_waits_for_enough_players():
    maker = _maker()
    maker.enqueue(0, "P0", AutoChannel())
    assert maker.form_rooms() == []
    assert maker.queue_size() == 1


def test_matchmaker_rejects_duplicate_player():
    maker = _maker()
    maker.enqueue(0, "P0", AutoChannel())
    with pytest.raises(MatchmakingError):
        maker.enqueue(0, "P0", AutoChannel())


def test_matchmaker_cancels_a_room():
    maker = _maker()
    for i in range(2):
        maker.enqueue(i, f"P{i}", AutoChannel())
    room = maker.form_rooms()[0]
    maker.cancel(room.id)
    assert room.status.value == "cancelled"
