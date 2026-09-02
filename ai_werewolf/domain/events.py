"""Game events.

Every observable thing that happens in a game is a :class:`GameEvent`. Each
event knows its own audience: a ``None`` audience means "public" (everyone),
while a ``frozenset`` audience restricts the event to those player ids. Player
views, spectators and replays are all derived from the event stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventKind(str, Enum):
    GAME_STARTED = "game_started"
    ROLE_DEALT = "role_dealt"
    PACK_MATES = "pack_mates"
    NIGHT_BEGINS = "night_begins"
    WOLF_KILL = "wolf_kill"
    SEER_RESULT = "seer_result"
    WITCH_ATTACK = "witch_attack"
    WITCH_POTIONS = "witch_potions"
    DAWN = "dawn"
    DEATH = "death"
    PEACEFUL_NIGHT = "peaceful_night"
    DISCUSSION_BEGINS = "discussion_begins"
    BID = "bid"
    STATEMENT = "statement"
    VOTE = "vote"
    LYNCH = "lynch"
    NO_LYNCH = "no_lynch"
    LAST_WORDS = "last_words"
    GAME_OVER = "game_over"


@dataclass(frozen=True)
class GameEvent:
    kind: EventKind
    day: int
    phase: str
    text: str
    actor: int | None = None
    target: int | None = None
    data: dict = field(default_factory=dict)
    #: ``None`` means public; otherwise only these player ids may see it.
    audience: frozenset[int] | None = None
    #: Stable unique id within a game, used as an evidence reference.
    id: int = 0

    def is_public(self) -> bool:
        return self.audience is None

    def visible_to(self, player_id: int) -> bool:
        return self.audience is None or player_id in self.audience


def to_dict(event: GameEvent) -> dict:
    """Serialise one event to a JSON-safe dict (for transport and replay)."""
    return {
        "kind": event.kind.value,
        "id": event.id,
        "day": event.day,
        "phase": event.phase,
        "text": event.text,
        "actor": event.actor,
        "target": event.target,
        "data": event.data,
        "audience": sorted(event.audience) if event.audience is not None else None,
    }
