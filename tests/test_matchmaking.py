"""Tests for matchmaking."""

from __future__ import annotations

import pytest

from ai_werewolf.server.matchmaking import Matchmaker, MatchmakingError
from ai_werewolf.server.room import AIConfig, RoomConfig
from conftest import AutoChannel


def _maker() -> Matchmaker:
    return Matchmaker(RoomConfig(capacity=7, ai=AIConfig(count=6)))


def test_matchmaker_forms_rooms_from_the_queue():
    maker = _maker()
    for i in range(3):
        maker.enqueue(i, f"P{i}", AutoChannel())
    assert maker.queue_size() == 3
    rooms = maker.form_rooms()
    assert len(rooms) == 3  # 1 human per 7-seat room
    assert maker.queue_size() == 0
    assert all(room.status.value == "ready" for room in rooms)


def test_matchmaker_forms_nothing_from_an_empty_queue():
    maker = _maker()
    assert maker.form_rooms() == []


def test_matchmaker_rejects_duplicate_player():
    maker = _maker()
    maker.enqueue(0, "P0", AutoChannel())
    with pytest.raises(MatchmakingError):
        maker.enqueue(0, "P0", AutoChannel())


def test_matchmaker_cancels_a_room():
    maker = _maker()
    maker.enqueue(0, "P0", AutoChannel())
    room = maker.form_rooms()[0]
    maker.cancel(room.id)
    assert room.status.value == "cancelled"
