"""In-memory channel and hub for tests, the CLI and local multiplayer.

:class:`InMemoryChannel` is a scriptable pipe: pre-load replies with
``script=``, then inspect what was sent through ``sent``. :class:`Hub` routes
broadcasts to a set of channels keyed by player id.
"""

from __future__ import annotations

from ai_werewolf.transport.channel import Channel, Envelope


class InMemoryChannel:
    """A synchronous pipe with a scripted inbox."""

    def __init__(self, script: list[Envelope] | None = None) -> None:
        self.sent: list[Envelope] = []
        self._script = list(script or [])

    def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    def recv(self, timeout: float | None = None) -> Envelope:
        if self._script:
            return self._script.pop(0)
        raise TimeoutError("no scripted response")


class Hub:
    """Broadcasts envelopes to every connected channel."""

    def __init__(self) -> None:
        self.channels: dict[int, Channel] = {}

    def connect(self, player_id: int, channel: Channel) -> None:
        self.channels[player_id] = channel

    def disconnect(self, player_id: int) -> None:
        self.channels.pop(player_id, None)

    def send(self, player_id: int, envelope: Envelope) -> None:
        channel = self.channels.get(player_id)
        if channel is not None:
            channel.send(envelope)

    def broadcast(self, envelope: Envelope) -> None:
        for channel in self.channels.values():
            channel.send(envelope)
