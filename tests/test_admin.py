"""Tests for the admin backend."""

from __future__ import annotations

import pytest

from ai_werewolf.server.admin import AdminBackend, AdminError
from ai_werewolf.server.room import AIConfig, Room, RoomConfig, RoomStatus
from conftest import AutoChannel


def _room() -> Room:
    return Room(RoomConfig(capacity=7, ai=AIConfig(count=6)))


def test_admin_lists_registered_rooms():
    admin = AdminBackend()
    admin.register(_room())
    rooms = admin.list_rooms()
    assert len(rooms) == 1
    assert rooms[0]["status"] == "open"


def test_admin_can_kick_a_human_from_an_open_room():
    admin = AdminBackend()
    room = _room()
    seat = room.add_human("Alice", AutoChannel())
    admin.register(room)
    admin.kick_human(room.id, seat)
    assert room.human_count == 0


def test_admin_cannot_kick_during_play():
    admin = AdminBackend()
    room = _room()
    room.add_human("Alice", AutoChannel())
    admin.register(room)
    room.status = RoomStatus.PLAYING
    with pytest.raises(AdminError):
        admin.kick_human(room.id, 0)


def test_admin_cancels_room():
    admin = AdminBackend()
    room = _room()
    admin.register(room)
    admin.cancel_room(room.id)
    assert room.status is RoomStatus.CANCELLED


def test_admin_bot_pool_and_stats():
    admin = AdminBackend()
    admin.register(_room())
    admin.set_bot_pool("llm", 5)
    stats = admin.stats()
    assert stats.rooms == 1
    assert stats.bot_pool == 5


def test_admin_rejects_unknown_bot_policy():
    admin = AdminBackend()
    with pytest.raises(AdminError):
        admin.set_bot_pool("alien", 1)
