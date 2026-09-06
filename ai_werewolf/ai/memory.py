"""Cross-turn memory for each AI seat.

Each :class:`AgentMemory` lives on the player object (server-side), so it
survives client refreshes, disconnects and message replay. It records what the
agent said, voted, suspected and who pushed back, so the next statement can
refer to real history instead of fabricating it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CAP_STATEMENTS = 8
CAP_VOTES = 12
CAP_QUESTIONED = 8
CAP_ALLIES = 8
CAP_CONFLICTS = 8
CAP_PROMISES = 4
CAP_PHRASES = 16


@dataclass
class AgentMemory:
    """Append-only, bounded per-seat dialogue memory."""

    statements: list[str] = field(default_factory=list)
    votes: list[dict] = field(default_factory=list)          # {"day": int, "target": int}
    suspicion_log: list[dict] = field(default_factory=list)  # {"day": int, "key_player": int|None}
    questioned_by: list[int] = field(default_factory=list)
    allies: list[int] = field(default_factory=list)
    conflicts: list[int] = field(default_factory=list)
    promises: list[str] = field(default_factory=list)
    recent_phrases: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- mutations
    def record_statement(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.statements.append(text)
            self._trim(self.statements, CAP_STATEMENTS)
            if text not in self.recent_phrases:
                self.recent_phrases.append(text)
                self._trim(self.recent_phrases, CAP_PHRASES)

    def record_vote(self, day: int, target: int | None) -> None:
        if target is None:
            return
        self.votes.append({"day": day, "target": target})
        self._trim(self.votes, CAP_VOTES)

    def record_suspicion(self, day: int, key_player: int | None) -> None:
        self.suspicion_log.append({"day": day, "key_player": key_player})
        self._trim(self.suspicion_log, CAP_STATEMENTS)

    def record_questioned_by(self, player_id: int) -> None:
        if player_id not in self.questioned_by:
            self.questioned_by.append(player_id)
            self._trim(self.questioned_by, CAP_QUESTIONED)

    def record_ally(self, player_id: int) -> None:
        if player_id not in self.allies:
            self.allies.append(player_id)
            self._trim(self.allies, CAP_ALLIES)

    def record_conflict(self, player_id: int) -> None:
        if player_id not in self.conflicts:
            self.conflicts.append(player_id)
            self._trim(self.conflicts, CAP_CONFLICTS)

    def record_promise(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.promises.append(text)
            self._trim(self.promises, CAP_PROMISES)

    @staticmethod
    def _trim(items: list, cap: int) -> None:
        if len(items) > cap:
            del items[: len(items) - cap]

    # ------------------------------------------------------------- views
    @property
    def last_statement(self) -> str | None:
        return self.statements[-1] if self.statements else None

    def has_recent_phrase(self, text: str) -> bool:
        return (text or "").strip() in self.recent_phrases

    def summarize(self) -> dict:
        """A compact JSON-safe view injected into the prompt / hint."""
        return {
            "statements": list(self.statements[-4:]),
            "votes": [dict(v) for v in self.votes[-4:]],
            "questioned_by": list(self.questioned_by[-4:]),
            "allies": list(self.allies[-4:]),
            "conflicts": list(self.conflicts[-4:]),
            "promises": list(self.promises[-2:]),
            "recent_phrases": list(self.recent_phrases[-6:]),
        }
