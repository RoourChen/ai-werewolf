"""Thread-safe queue channel for the WebSocket runtime.

The game thread and the WebSocket transport run on different threads. The game
thread writes envelopes into :attr:`QueueChannel.outbox` and blocks on
:meth:`QueueChannel.recv`; the transport drains ``outbox`` and pushes the
human's action into ``inbox``. The channel enforces the per-action deadline
itself, so a disconnected or silent client can never stall a game forever.
"""

from __future__ import annotations

import queue
import time
from queue import Empty

from ai_werewolf.transport.channel import Envelope

# Default per-action timeouts in seconds (see the WebSocket design §5.1).
DEFAULT_TIMEOUTS: dict[str, float] = {
    "night_kill": 20.0,
    "pack_confirm": 20.0,
    "night_inspect": 20.0,
    "witch_potions": 20.0,
    "statement": 30.0,
    "last_words": 30.0,
    "bid": 10.0,
    "vote": 20.0,
}


def timeout_for_kind(kind: str, table: dict[str, float] | None = None) -> float:
    """Return the deadline (seconds) for one action kind."""
    return float((table or DEFAULT_TIMEOUTS).get(kind, 20.0))


class QueueChannel:
    """A :class:`Channel` whose two directions are thread-safe queues."""

    def __init__(self, timeouts: dict[str, float] | None = None) -> None:
        self.outbox: queue.Queue[Envelope] = queue.Queue()
        self.inbox: queue.Queue[Envelope] = queue.Queue()
        self.timeouts = timeouts or DEFAULT_TIMEOUTS
        self.auto_fallback = False
        self._deadline: float | None = None
        self._pending_kind: str | None = None

    def send(self, envelope: Envelope) -> None:
        if envelope.kind == "decision":
            request = envelope.payload.get("request", {})
            self._pending_kind = str(request.get("kind", ""))
            self._deadline = time.monotonic() + timeout_for_kind(
                self._pending_kind, self.timeouts
            )
        self.outbox.put(envelope)

    def recv(self, timeout: float | None = None) -> Envelope:
        if self.auto_fallback:
            raise TimeoutError("auto-fallback mode: no human input accepted")

        wait: float | None = None
        if self._deadline is not None:
            wait = self._deadline - time.monotonic()
        if timeout is not None:
            wait = min(wait, timeout) if wait is not None else timeout

        try:
            envelope = self.inbox.get(timeout=max(0.0, wait) if wait is not None else None)
        except Empty:
            self.outbox.put(Envelope("timeout", payload={"kind": self._pending_kind}))
            self._deadline = None
            raise TimeoutError(f"no action for {self._pending_kind!r} in time") from None
        self._deadline = None
        return envelope

    def deliver_action(self, action: dict) -> None:
        """Hand a validated action back to the blocked game thread."""
        self.inbox.put(Envelope("action", payload={"action": action}))
