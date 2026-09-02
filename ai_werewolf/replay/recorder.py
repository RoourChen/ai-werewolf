"""Replay: record, save, load and replay a finished game.

A replay is a self-contained JSON document (``ai-werewolf.replay/v1``) holding
the seats, the full event stream, the live chat and every AI's decision trace.
The trace section is what lets a post-game replay answer "why did that AI
suspect or attack me at that moment".
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_werewolf.domain.events import to_dict
from ai_werewolf.domain.state import GameState
from ai_werewolf.domain.trace import to_dicts

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
    """Build a replay dict from a finished session (includes chat + traces)."""
    return record_game_with_traces(
        session.result,  # type: ignore[attr-defined]
        session.traces,  # type: ignore[attr-defined]
        human_seats=session.humans,  # type: ignore[attr-defined]
        persona_map=session.persona_map,  # type: ignore[attr-defined]
        chat=session.chat,  # type: ignore[attr-defined]
    )


def record_game_with_traces(
    state: GameState,
    traces: dict,
    *,
    human_seats=( ),
    persona_map=None,
    chat=None,
) -> dict:
    """Build a replay dict from a state plus its decision traces."""
    replay = record_game(state)
    replay["human_seats"] = sorted(human_seats)
    replay["persona_map"] = dict(persona_map or {})
    replay["chat"] = [
        message if isinstance(message, dict)
        else {"player": message.player, "kind": message.kind, "body": message.body, "day": message.day}
        for message in (chat or [])
    ]
    replay["traces"] = {
        str(player_id): to_dicts(records)
        for player_id, records in (traces or {}).items()
    }
    return replay


def save(replay: dict, path: str | Path) -> Path:
    out = Path(path)
    out.write_text(json.dumps(replay, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def replay_text(replay: dict) -> str:
    """Render a replay dict as a readable timeline plus decision traces."""
    winner = replay.get("winner", "?")
    days = replay.get("days", "?")
    lines = [f"=== 回放 — 胜方：{winner}，共 {days} 天 ==="]
    for seat in replay.get("seats", []):
        status = "存活" if seat.get("alive") else f"第 {seat.get('death_day')} 天死亡"
        lines.append(
            f"  P{seat['id']} {seat.get('name', ''):<8} {seat.get('role', ''):<8} — {status}"
        )
    lines.append("")
    lines.append("=== 事件时间线 ===")
    for event in replay.get("events", []):
        tag = "" if event.get("audience") is None else "[私密] "
        lines.append(
            f"  第{event.get('day', '?'):<3}天 [{event.get('phase', ''):<12}] "
            f"{tag}{event.get('text', '')}"
        )
    for message in replay.get("chat", []):
        lines.append(f"  [聊天] P{message.get('player')}: {message.get('body', '')}")
    lines.extend(_trace_lines(replay))
    return "\n".join(lines)


def traces_text(replay: dict) -> str:
    """Render only the decision-trace section of a replay."""
    return "\n".join(_trace_lines(replay))


def _trace_lines(replay: dict) -> list[str]:
    human_seats = set(replay.get("human_seats", []))
    traces = replay.get("traces", {})
    if not traces:
        return []

    lines = ["", "=== 决策轨迹（AI 当时为什么怀疑/攻击你）==="]
    for _player_id, records in traces.items():
        for record in records:
            private = record.get("private_suspicion", {})
            public = record.get("public_suspicion", {})
            threat = record.get("strategic_threat", {})
            deception = record.get("deception", False)
            plan = record.get("deception_plan", {})
            focus = ", ".join(
                f"P{h}: 私下 {_fmt(private, h)} / 公开 {_fmt(public, h)}"
                f" / 威胁 {_fmt(threat, h)}"
                for h in sorted(human_seats)
            ) or "—"
            lines.append(
                f"  [P{record.get('actor')} {record.get('persona')}/{record.get('role')}"
                f" 第{record.get('day')}天 {record.get('kind')}] {record.get('decision')}"
                f"（置信 {record.get('confidence')}）对真人：{focus}"
            )
            if record.get("evidence") and record["evidence"] != "none":
                lines.append(f"      证据 {record['evidence']}")
            threat_delta = record.get("threat_delta", {})
            threat_key = record.get("threat_key_player")
            if threat_key is not None:
                lines.append(
                    f"      威胁变化 P{threat_key}: {_fmt(threat_delta, threat_key)}"
                )
            if record.get("rationale"):
                lines.append(f"      依据 {record['rationale']}")
            if deception:
                lines.append(
                    f"      ⚠ 故意欺骗 → 对象 P{plan.get('target')}："
                    f"公开说法“{plan.get('public_statement')}”，"
                    f"目的“{plan.get('purpose')}”，真实依据“{plan.get('true_basis')}”"
                )
            if record.get("fallback_reason"):
                lines.append(f"      兜底 {record['fallback_reason']}")
    return lines


def _fmt(scores: dict, pid: int) -> object:
    return scores.get(pid, scores.get(str(pid), "—"))
