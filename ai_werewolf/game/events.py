"""The event log.

Every observable thing that happens in a game is an :class:`Event`. The log is
the single source of truth: player views, transcripts and the copilot's belief
model are all derived from it. Events carry their own visibility so a player
view is just a filter over the log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    GAME_START = "game_start"          # public: roster + role list announced
    ROLE_ASSIGNED = "role_assigned"    # private: a player learns their role
    PACK_REVEAL = "pack_reveal"        # private: werewolves learn each other
    NIGHT_FALLS = "night_falls"        # public
    WEREWOLF_TARGET = "werewolf_target"  # private: a wolf names a victim
    SEER_RESULT = "seer_result"        # private: the seer's inspection
    DOCTOR_PROTECT = "doctor_protect"  # private: the doctor's choice
    WITCH_NIGHT_INFO = "witch_night_info"  # private: who the wolves attacked
    WITCH_POTION = "witch_potion"      # private: a potion the witch used
    DAY_BREAKS = "day_breaks"          # public
    DEATH_ANNOUNCED = "death_announced"  # public
    QUIET_NIGHT = "quiet_night"        # public: nobody died
    SPEAK_BID = "speak_bid"            # public: a bid for the discussion floor
    STATEMENT = "statement"            # public: a daytime statement
    VOTE_CAST = "vote_cast"            # public
    LYNCH = "lynch"                    # public
    NO_LYNCH = "no_lynch"              # public
    HUNTER_SHOT = "hunter_shot"        # public: a dying Hunter's revenge
    AGENT_REASONING = "agent_reasoning"  # private: an agent's stated reason for its decision
    GAME_OVER = "game_over"            # public


@dataclass(frozen=True)
class Event:
    """A single thing that happened, with built-in visibility.

    ``public`` events are seen by everyone. Otherwise only players listed in
    ``visible_to`` (typically the actor and any teammates) can see it.
    """

    type: EventType
    day: int
    phase: str
    text: str
    actor: int | None = None
    target: int | None = None
    public: bool = True
    visible_to: frozenset[int] = field(default_factory=frozenset)
    data: dict = field(default_factory=dict)

    def visible(self, player_id: int) -> bool:
        return self.public or player_id in self.visible_to
