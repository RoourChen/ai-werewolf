"""Replay: record, save, load and replay a finished game.

A replay is a self-contained JSON document (``ai-werewolf.replay/v1``) holding
the seats, the full event stream and the live chat. It is the basis for the
spectate/replay feature and for offline analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_werewolf.domain.events import to_dict
from ai_werewolf.domain.state import GameState

SCHEMA = "ai-werewolf.replay/v1"


def record_game(state: GameState) -> dict:
    """Build a replay dict from a finished :class:`GameState`."""
    return {
        "schema": SCHEMA,
        "winner": state.winner.value if state.winner else None,
        "days": state.day,
        "seats": [
            {
                "id": seat.id,
                "name": seat.name,
                "role": seat.role.value,
                "faction": seat.faction.value,
                "alive": seat.alive,
                "death_day": seat.death_day,
                "death_cause": seat.death_cause,
            }
            for seat in state.seats
        ],
        "events": [to_dict(e) for e in state.events],
    }


def record_session(session: object) -> dict:
    """Build a replay dict from a finished game session (includes chat)."""
    state = session.result  # type: ignore[attr-defined]
    replay = record_game(state)
    replay["chat"] = [
        {"player": m.player, "kind": m.kind, "body": m.body, "day": m.day}
        for m in session.chat  # type: ignore[attr-defined]
    ]
    return replay


def save(replay: dict, path: str | Path) -> Path:
    out = Path(path)
    out.write_text(json.dumps(replay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def replay_text(replay: dict) -> str:
    """Render a replay dict as a readable timeline."""
    winner = replay.get("winner", "?")
    days = replay.get("days", "?")
    lines = [f"=== 回放 — 胜方：{winner}，共 {days} 天 ==="]
    for seat in replay.get("seats", []):
        status = "存活" if seat.get("alive") else f"第 {seat.get('death_day')} 天死亡"
        lines.append(
            f"  P{seat['id']} {seat.get('name', ''):<8} {seat.get('role', ''):<8} — {status}"
        )
    lines.append("")
    for event in replay.get("events", []):
        tag = "" if event.get("audience") is None else "[私密] "
        lines.append(f"  第{event.get('day', '?'):<3}天 [{event.get('phase', ''):<12}] {tag}{event.get('text', '')}")
    for message in replay.get("chat", []):
        lines.append(f"  [聊天] P{message.get('player')}: {message.get('body', '')}")
    return "\n".join(lines)
