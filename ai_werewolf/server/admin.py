"""Admin backend.

A read-only control surface over live rooms, matchmaking and the bot pool. It
is intentionally independent of any web framework: a real deployment would
expose these methods over HTTP, while tests and the CLI call them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.server.room import Room, RoomStatus


@dataclass
class ServerStats:
    rooms: int = 0
    open_rooms: int = 0
    playing_rooms: int = 0
    finished_rooms: int = 0
    bot_pool: int = 0

    def render(self) -> str:
        return (
            f"房间 {self.rooms}（开放 {self.open_rooms}，对局中 {self.playing_rooms}，"
            f"已结束 {self.finished_rooms}），Bot 池 {self.bot_pool}"
        )


@dataclass
class AdminBackend:
    """Administrative operations over rooms and the bot pool."""

    rooms: dict[str, Room] = field(default_factory=dict)
    bot_pool: dict[str, int] = field(default_factory=lambda: {"random": 0, "llm": 0})

    def register(self, room: Room) -> None:
        self.rooms[room.id] = room

    def list_rooms(self) -> list[dict]:
        return [
            {
                "id": room.id,
                "status": room.status.value,
                "humans": room.human_count,
                "capacity": room.config.capacity,
                "ai": room.config.ai.count,
            }
            for room in self.rooms.values()
        ]

    def room_summary(self, room_id: str) -> dict:
        room = self._room(room_id)
        return {
            "id": room.id,
            "status": room.status.value,
            "humans": room.human_count,
            "capacity": room.config.capacity,
            "ai": room.config.ai.count,
        }

    def kick_human(self, room_id: str, seat: int) -> None:
        room = self._room(room_id)
        if room.status is RoomStatus.PLAYING:
            raise AdminError("cannot kick from a game in progress")
        room.remove_human(seat)

    def cancel_room(self, room_id: str) -> None:
        self._room(room_id).status = RoomStatus.CANCELLED

    def set_bot_pool(self, policy: str, count: int) -> None:
        if policy not in self.bot_pool:
            raise AdminError(f"unknown bot policy {policy!r}")
        if count < 0:
            raise AdminError("bot count cannot be negative")
        self.bot_pool[policy] = count

    def stats(self) -> ServerStats:
        rooms = list(self.rooms.values())
        return ServerStats(
            rooms=len(rooms),
            open_rooms=sum(1 for r in rooms if r.status in (RoomStatus.OPEN, RoomStatus.READY)),
            playing_rooms=sum(1 for r in rooms if r.status is RoomStatus.PLAYING),
            finished_rooms=sum(1 for r in rooms if r.status is RoomStatus.FINISHED),
            bot_pool=sum(self.bot_pool.values()),
        )

    def _room(self, room_id: str) -> Room:
        room = self.rooms.get(room_id)
        if room is None:
            raise AdminError("room not found")
        return room


class AdminError(RuntimeError):
    """Raised for invalid admin operations."""
