"""Save, load and replay game transcripts.

A transcript is a self-contained, machine-readable record of one game: the
players with their roles revealed, the full event log, and the winner. It is
useful for replay, offline analysis, attaching to a bug report, or feeding past
games into an arena leaderboard.

The format is versioned via the ``schema`` field so consumers can evolve
safely. The current schema is ``ai-werewolf.transcript/v1``.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_werewolf.game.events import Event
from ai_werewolf.game.state import GameResult

SCHEMA = "ai-werewolf.transcript/v1"


def event_to_json(event: Event) -> dict:
    """Serialise one :class:`Event` to a JSON-safe dict."""
    return {
        "type": event.type.value,
        "day": event.day,
        "phase": event.phase,
        "text": event.text,
        "actor": event.actor,
        "target": event.target,
        "public": event.public,
        "visible_to": sorted(event.visible_to),
        "data": event.data,
    }


def to_json(result: GameResult) -> dict:
    """Build a JSON-safe transcript dict from a finished game."""
    return {
        "schema": SCHEMA,
        "winner": result.winner.value,
        "days": result.days,
        "players": [
            {
                "id": p.id,
                "name": p.name,
                "role": p.role.value,
                "faction": p.faction.value,
                "alive": p.alive,
                "death_day": p.death_day,
                "death_cause": p.death_cause,
            }
            for p in result.players
        ],
        "events": [event_to_json(e) for e in result.events],
    }


def dumps(result: GameResult, *, indent: int | None = 2) -> str:
    """Return the transcript of ``result`` as a JSON string."""
    return json.dumps(to_json(result), indent=indent, ensure_ascii=False)


def save(result: GameResult, path: str | Path) -> Path:
    """Write the transcript of ``result`` to ``path`` and return that path."""
    out = Path(path)
    out.write_text(dumps(result) + "\n", encoding="utf-8")
    return out


def loads(text: str) -> dict:
    """Parse a JSON transcript string back into a dict (for replay/analysis)."""
    return json.loads(text)


def load(path: str | Path) -> dict:
    """Read a saved transcript from ``path`` and parse it."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def replay_text(transcript: dict) -> str:
    """Render a loaded transcript as a readable event timeline."""
    winner = transcript.get("winner", "?")
    days = transcript.get("days", "?")
    lines = [
        f"=== ai-werewolf replay — winner: {winner} after {days} day(s) ===",
    ]
    for p in transcript.get("players", []):
        status = (
            "survived"
            if p.get("alive")
            else f"died day {p.get('death_day')} ({p.get('death_cause')})"
        )
        lines.append(
            f"  P{p['id']} {p.get('name', ''):<10} {p.get('role', ''):<10} "
            f"{p.get('faction', ''):<12} — {status}"
        )
    lines.append("")
    for e in transcript.get("events", []):
        tag = "" if e.get("public") else "[secret] "
        lines.append(
            f"  day {e.get('day', '?'):<3} [{e.get('phase', ''):<14}] "
            f"{tag}{e.get('text', '')}"
        )
    return "\n".join(lines)
