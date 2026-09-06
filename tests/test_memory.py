"""Tests for the per-seat cross-turn memory."""

from __future__ import annotations

from ai_werewolf.ai.memory import AgentMemory


def test_agent_memory_records_and_caps() -> None:
    memory = AgentMemory()
    for i in range(20):
        memory.record_statement(f"第 {i} 句")
    assert len(memory.statements) <= 8
    assert memory.last_statement == "第 19 句"
    assert memory.has_recent_phrase("第 19 句")
    assert not memory.has_recent_phrase("不存在的话")

    for i in range(10):
        memory.record_vote(day=1, target=i % 7)
    assert len(memory.votes) <= 12


def test_agent_memory_summarize_is_json_safe() -> None:
    memory = AgentMemory()
    memory.record_statement("我先听一轮")
    memory.record_vote(1, 3)
    memory.record_questioned_by(2)
    summary = memory.summarize()
    assert "statements" in summary
    assert summary["statements"][-1] == "我先听一轮"
    assert summary["votes"][-1] == {"day": 1, "target": 3}


def test_agent_memory_no_duplicate_questioner() -> None:
    memory = AgentMemory()
    memory.record_questioned_by(2)
    memory.record_questioned_by(2)
    assert memory.questioned_by == [2]
