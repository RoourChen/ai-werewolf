"""End-to-end acceptance for the 1-human + 6-AI vertical loop."""

from __future__ import annotations

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.roles import build_roster
from ai_werewolf.domain.state import GameConfig
from ai_werewolf.replay.recorder import record_session, replay_text
from ai_werewolf.server.room import AIConfig, Room, RoomConfig
from conftest import AutoChannel


def _run_game(seed: int = 11):
    room = Room(RoomConfig(
        capacity=7,
        ai=AIConfig(count=6, policy="llm", provider=MockProvider(seed=0)),
        seed=seed,
    ))
    seat = room.add_human("你", AutoChannel())
    session = room.start()
    return room, session, seat


def test_vertical_loop_full_game():
    room, session, seat = _run_game()
    result = session.result
    assert result is not None
    assert result.winner is not None

    # 7 seats, strictly correct roles
    roles = sorted(s.role.value for s in result.seats)
    assert roles == ["seer", "villager", "villager", "villager", "werewolf", "werewolf", "witch"]

    # AIConfig built 6 real LLMBots (not random bots)
    assert sum(1 for p in session.players.values() if p.name == "llm") == 6
    assert any(p.name == "human" for p in session.players.values())

    # six distinct personas, recorded
    assert len(session.persona_map) == 6
    assert len(set(session.persona_map.values())) == 6

    # every AI produced traces with the three channels
    assert len(session.traces) == 6
    for records in session.traces.values():
        assert records
        for record in records:
            assert set(record.private_suspicion)
            assert set(record.strategic_threat)
            if record.kind in ("statement", "vote"):
                assert set(record.public_suspicion)

    # death never reveals role
    deaths = [e for e in result.events if e.kind in (EventKind.DEATH, EventKind.LYNCH)]
    assert deaths
    assert all("身份" not in e.text for e in deaths)

    # replay answers "why suspect the human"
    replay = record_session(session)
    text = replay_text(replay)
    assert "决策轨迹" in text
    assert "私下" in text


def test_non_seven_configs_are_rejected():
    with pytest.raises(ValueError):
        build_roster(8)
    with pytest.raises(ValueError):
        GameConfig(roster=[build_roster(7)[0]] * 8)


def test_persona_and_role_assignment_is_reproducible():
    _, a, _ = _run_game(seed=42)
    _, b, _ = _run_game(seed=42)
    assert a.persona_map == b.persona_map
    roles_a = {s.id: s.role.value for s in a.result.seats}
    roles_b = {s.id: s.role.value for s in b.result.seats}
    assert roles_a == roles_b


def test_replay_renders_deception_narrative():
    replay = {
        "schema": "ai-werewolf.replay/v1",
        "winner": "werewolves",
        "days": 1,
        "human_seats": [0],
        "persona_map": {},
        "seats": [
            {"id": i, "name": f"P{i}", "role": "villager", "faction": "village",
             "alive": True, "death_day": None, "death_cause": None}
            for i in range(7)
        ],
        "events": [],
        "chat": [],
        "traces": {
            "3": [{
                "day": 1, "phase": "voting", "actor": 3, "persona": "aggressor",
                "role": "werewolf", "kind": "vote",
                "private_suspicion": {0: 0.0}, "public_suspicion": {0: 0.82},
                "strategic_threat": {0: 0.9}, "delta": {0: 0.82}, "key_player": 0,
                "evidence": "pack", "candidates": [0, 1, 2, 4, 5, 6],
                "decision": "vote P0", "confidence": 0.8, "rationale": "转移火力",
                "deception": True,
                "deception_plan": {
                    "target": 0,
                    "public_statement": "我强烈怀疑 P0 是狼",
                    "purpose": "转移火力保住狼队",
                    "true_basis": "我知道 P0 不是狼，但认为他对狼队威胁很高",
                },
                "fallback_reason": None,
            }],
        },
    }
    text = replay_text(replay)
    assert "故意欺骗" in text
    assert "公开说法" in text
    assert "真实依据" in text
    assert "0.82" in text
