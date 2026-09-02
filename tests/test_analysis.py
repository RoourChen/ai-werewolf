"""Tests for decision-quality analysis."""

from __future__ import annotations

from ai_werewolf.analysis import MIN_PUBLIC_NODES, analyze_decision_quality
from ai_werewolf.domain.trace import DecisionRecord


def _record(**overrides) -> DecisionRecord:
    base = {
        "day": 1, "phase": "voting", "actor": 0, "persona": "analyst",
        "role": "villager", "kind": "vote", "private_suspicion": {1: 0.3},
        "public_suspicion": {1: 0.3}, "strategic_threat": {1: 0.4},
        "delta": {1: 0.0}, "key_player": None, "evidence": "none",
        "candidates": (1,), "decision": "vote P1", "confidence": 0.5,
        "rationale": "r", "deception": False,
    }
    base.update(overrides)
    return DecisionRecord(**base)


def test_analyze_decision_quality_counts_ratios():
    traces = {
        0: [
            _record(),
            _record(retried=True, fallback_reason="retry failed: public/private gap without deception mark"),
            _record(fallback_reason="unparseable output"),
            _record(pending_review=True),
        ]
    }
    report = analyze_decision_quality(traces)
    assert report.total == 4
    assert report.public == 4
    assert report.gap_without_mark == 1
    assert report.retried == 1
    assert report.fallback == 2
    assert report.pending_review == 1
    assert not report.ready_for_tuning  # 4 < MIN_PUBLIC_NODES
    assert report.render()


def test_ready_for_tuning_requires_enough_public_nodes():
    traces = {0: [_record() for _ in range(MIN_PUBLIC_NODES)]}
    report = analyze_decision_quality(traces)
    assert report.ready_for_tuning
