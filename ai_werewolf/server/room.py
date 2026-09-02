"""Rooms and their configuration.

A :class:`Room` is where humans and bots are gathered before a game. It holds
the seats, the AI configuration and the game rules; once full it is started,
which creates and runs a :class:`~ai_werewolf.server.session.GameSession`.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.provider import ModelConfig, OpenAICompatProvider, Provider
from ai_werewolf.transport.channel import Channel

if TYPE_CHECKING:
    from ai_werewolf.server.session import GameSession


class RoomStatus(str, Enum):
    OPEN = "open"        # still accepting humans
    READY = "ready"      # full, waiting to start
    PLAYING = "playing"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass
class AIConfig:
    """How the room's bot seats are filled."""

    count: int = 6
    policy: str = "llm"  # "llm" | "random"
    model: str | None = None
    provider: Provider | None = None

    def __post_init__(self) -> None:
        if self.policy not in ("llm", "random"):
            raise ValueError(f"unknown AI policy {self.policy!r} (use 'llm' or 'random')")

    def resolve_provider(self, seed: int | None) -> Provider:
        """Build the provider: explicit provider > model (CLI/AIConfig) > env > mock.

        Model priority is fixed: explicit ``model`` field (set by the CLI when
        given) wins, then the ``AIWEREWOLF_MODEL`` environment variable.
        """
        if self.provider is not None:
            return self.provider
        model = self.model or os.environ.get("AIWEREWOLF_MODEL", "") or None
        if model:
            config = ModelConfig.from_env()  # loads .env if present
            config.model = model
            return OpenAICompatProvider(config)
        return MockProvider(seed=seed or 0)


@dataclass
class RoomConfig:
    """Rules and composition of a room."""

    capacity: int = 7
    language: str = "zh"
    discussion_mode: str = "seating"  # "seating" | "bidding"
    ai: AIConfig = field(default_factory=AIConfig)
    seed: int | None = None

    @property
    def human_slots(self) -> int:
        return self.capacity - self.ai.count

    def __post_init__(self) -> None:
        if self.capacity != 7 or self.ai.count != 6:
            raise ValueError("MVP rooms must be exactly 7 seats: 1 human + 6 AI")


@dataclass
class HumanSeat:
    name: str
    channel: Channel


@dataclass
class Room:
    """A table of humans and configured bots."""

    config: RoomConfig
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: RoomStatus = RoomStatus.OPEN
    humans: dict[int, HumanSeat] = field(default_factory=dict)
    result: object | None = None

    @property
    def human_count(self) -> int:
        return len(self.humans)

    @property
    def is_full(self) -> bool:
        return self.human_count >= self.config.human_slots

    def add_human(self, name: str, channel: Channel) -> int:
        if self.status is not RoomStatus.OPEN:
            raise RoomError("room is not open")
        if self.is_full:
            raise RoomError("room is full")
        seat = self._next_seat()
        self.humans[seat] = HumanSeat(name=name, channel=channel)
        if self.is_full:
            self.status = RoomStatus.READY
        return seat

    def remove_human(self, seat: int) -> None:
        if seat not in self.humans:
            raise RoomError("seat is empty")
        if self.status is RoomStatus.PLAYING:
            raise RoomError("cannot leave a game in progress")
        del self.humans[seat]
        self.status = RoomStatus.OPEN

    def _next_seat(self) -> int:
        taken = set(self.humans)
        for seat in range(self.config.capacity):
            if seat not in taken:
                return seat
        raise RoomError("no free seat")

    def start(self) -> GameSession:
        """Start the game; returns the finished :class:`GameSession`."""
        from ai_werewolf.server.session import GameSession as _GameSession

        if self.status is not RoomStatus.READY:
            raise RoomError("room is not ready to start")
        self.status = RoomStatus.PLAYING
        session = _GameSession(self.config, self.humans)
        session.run()
        self.result = session
        self.status = RoomStatus.FINISHED
        return session


class RoomError(RuntimeError):
    """Raised for invalid room operations."""
