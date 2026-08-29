"""Transport abstractions.

The game core never talks to a network. Humans connect through a
:class:`Channel`, which is an abstract send/receive pipe. The referee and
session only ever see channels, so the same code drives a terminal, a
WebSocket or a scripted test double.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Envelope:
    """A message travelling through a channel."""

    kind: str
    payload: dict = field(default_factory=dict)
    sender: int | None = None


class Channel(Protocol):
    """A bidirectional pipe to one player."""

    def send(self, envelope: Envelope) -> None: ...

    def recv(self, timeout: float | None = None) -> Envelope: ...
