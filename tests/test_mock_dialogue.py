"""Tests for the offline persona dialogue generator."""

from __future__ import annotations

import json
import random

from ai_werewolf.ai.dialogue import (
    DialogueContext,
    SeatInfo,
    StatementRecord,
    VoteRecord,
    compose_statement,
)
from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.provider import Prompt

PERSONAS = ["skeptic", "nice", "analyst", "aggressor", "mediator", "chatterbox"]


def _ctx(persona: str = "skeptic", **overrides) -> DialogueContext:
    base = DialogueContext(
        persona_id=persona,
        day=2,
        phase="discussion",
        me=0,
        role="villager",
        pack=[],
        living=[SeatInfo(1, "老好人", False), SeatInfo(2, "分析家", False),
                SeatInfo(3, "激进派", False), SeatInfo(4, "和事佬", False)],
        recent_statements=[
            StatementRecord(1, 1, "P3 上一轮的票很奇怪"),
            StatementRecord(3, 1, "我先不表态"),
        ],
        votes=[VoteRecord(day=1, actor=1, target=3, round=1),
               VoteRecord(day=1, actor=0, target=3, round=1)],
        top_suspicion=3,
        my_last_statement="我昨天怀疑 P3",
        questioned_by=[1],
        memory_summary={},
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_no_placeholder_and_grounded() -> None:
    for persona in PERSONAS:
        for seed in range(20):
            out = compose_statement(_ctx(persona), random.Random(seed))
            text = out["statement"]
            assert "someone" not in text and "有人" not in text
            # 要么引用真实编号，要么明确信息不足
            assert ("P" in text) or ("信息不足" in text)


def test_personas_produce_distinct_voices() -> None:
    # 同一局势，六人格的 speech_act 分布或语句应可区分
    acts = {
        persona: {compose_statement(_ctx(persona), random.Random(s))["speech_act"]
                  for s in range(12)}
        for persona in PERSONAS
    }
    distinct = len({frozenset(v) for v in acts.values()})
    assert distinct >= 4


def test_compose_is_deterministic() -> None:
    a = compose_statement(_ctx("analyst"), random.Random(7))
    b = compose_statement(_ctx("analyst"), random.Random(7))
    assert a == b


def test_mock_provider_statement_has_no_placeholder() -> None:
    hint = {
        "kind": "statement", "day": 2, "phase": "discussion", "me": 0,
        "me_role": "villager", "pack": [], "others": [1, 2, 3],
        "persona": "skeptic", "top_suspicion": 2,
        "living": [{"id": 1, "name": "老好人", "alive": True, "is_human": False},
                   {"id": 2, "name": "分析家", "alive": True, "is_human": False}],
        "recent_statements": [{"actor": 1, "day": 1, "text": "P2 的票可疑"}],
        "votes": [{"day": 1, "actor": 1, "target": 2, "round": 1}],
        "questioned_by": [], "my_last_statement": None, "memory": {},
        "trust_baseline": 0.3, "evidence_sensitivity": 0.8, "risk_preference": 0.5,
        "lobby_strength": 0.6, "vote_resistance": 0.6, "deception_tendency": 0.4,
    }
    raw = MockProvider(seed=0).complete(Prompt(system="", user="", hint=hint))
    payload = json.loads(raw)
    assert "someone" not in payload["statement"]
    assert payload["speech_act"]
