"""Matchmaking.

A :class:`Matchmaker` holds a queue of players waiting for a seat and forms
rooms once enough humans are queued. It is deliberately simple and in-memory:
a real deployment would replace it with a networked matcher, but the room
lifecycle it produces is identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.server.room import Room, RoomConfig
from ai_werewolf.transport.channel import Channel


@dataclass
class QueuedPlayer:
    player_id: int
    name: str
    channel: Channel


@dataclass
class Matchmaker:
    """Forms rooms from a first-come, first-served queue."""

    room_config: RoomConfig
    queue: list[QueuedPlayer] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)

    def enqueue(self, player_id: int, name: str, channel: Channel) -> None:
        if any(p.player_id == player_id for p in self.queue):
            raise MatchmakingError("player already queued")
        self.queue.append(QueuedPlayer(player_id, name, channel))

    def queue_size(self) -> int:
        return len(self.queue)

    def form_rooms(self) -> list[Room]:
        """Greedily pull ready players out of the queue into new rooms."""
        formed: list[Room] = []
        human_slots = self.room_config.human_slots
        while len(self.queue) >= human_slots:
            room = Room(self.room_config)
            for _ in range(human_slots):
                player = self.queue.pop(0)
                room.add_human(player.name, player.channel)
            self.rooms.append(room)
            formed.append(room)
        return formed

    def cancel(self, room_id: str) -> None:
        from ai_werewolf.server.room import RoomStatus

        for room in self.rooms:
            if room.id == room_id:
                room.status = RoomStatus.CANCELLED
                return
        raise MatchmakingError("room not found")


class MatchmakingError(RuntimeError):
    """Raised for invalid matchmaking operations."""
