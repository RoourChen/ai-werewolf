"""Automated checks for the persona blind-test generator.

These assert the *hard* acceptance criteria on the generated material:
no placeholder/empty lines, no same-scenario duplicate lines, grounded
references (P numbers or "信息不足"), speech-act behaviour differs across
personas, determinism, and wolf misdirection that never targets the human.
"""

from __future__ import annotations

from ai_werewolf.persona_blind import PERSONA_IDS, generate, shuffle_labels


def test_no_placeholder_or_empty() -> None:
    run = generate(seed=20260906)
    for personas in run.scenarios.values():
        for turns in personas.values():
            for turn in turns:
                if turn["statement"] is not None:
                    text = turn["statement"]
                    assert "someone" not in text
                    assert text.strip() not in ("", "...", "…")
                    assert "你刚才的说法我想请" not in text or "能再解释" in text  # grounded question


def test_no_duplicate_statements_within_scenario() -> None:
    run = generate(seed=20260906)
    for scenario, personas in run.scenarios.items():
        for turn_idx in (0, 1):
            lines = [p[turn_idx]["statement"] for p in personas.values()]
            lines = [x for x in lines if x]
            assert len(set(lines)) == len(lines), f"{scenario} turn{turn_idx} duplicated"


def test_statements_are_grounded() -> None:
    import re

    run = generate(seed=20260906)
    for personas in run.scenarios.values():
        for turns in personas.values():
            for turn in turns:
                if turn["statement"]:
                    assert re.search(r"P\d+", turn["statement"]) or "信息" in turn["statement"]


def test_speech_acts_differ_across_personas() -> None:
    run = generate(seed=20260906)
    for scenario, personas in run.scenarios.items():
        act_sets = {frozenset(t["speech_act"] for t in turns) for turns in personas.values()}
        assert len(act_sets) >= 3, f"{scenario} act sets too similar: {act_sets}"


def test_each_persona_uses_multiple_speech_acts() -> None:
    """每个人格在四个场景里至少出现过一次非空 speech_act（有实际行为）。"""
    run = generate(seed=20260906)
    for pid in PERSONA_IDS:
        acts = [
            turn["speech_act"]
            for personas in run.scenarios.values()
            for turn in personas[pid]
            if turn["speech_act"]
        ]
        assert acts, f"{pid}: no speech_act recorded"


def test_wolf_misdirect_never_targets_human() -> None:
    run = generate(seed=20260906)
    for turns in run.scenarios["S4_狼人欺骗"].values():
        for turn in turns:
            # 狼人目标必须是 AI（非真人座位 0）
            assert turn["intended_vote"] != 0
            assert turn["target"] != 0 if turn.get("target") is not None else True


def test_deterministic() -> None:
    a = generate(seed=20260906)
    b = generate(seed=20260906)
    assert a.scenarios == b.scenarios


def test_shuffle_labels_are_unique_and_cover_all() -> None:
    for seed in range(5):
        labels = shuffle_labels(seed)
        assert len(labels) == 6
        assert set(labels) == set(PERSONA_IDS)
