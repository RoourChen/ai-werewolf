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


def test_statement_suspicion_vote_consistent() -> None:
    """每人最终投票应与当前怀疑一致（除非有明确改口理由）。"""
    run = generate(seed=20260906)
    for personas in run.scenarios.values():
        for turns in personas.values():
            vote = turns[2]["vote"]
            suspicion = turns[2]["top_suspicion"]
            assert vote == suspicion, f"vote {vote} != suspicion {suspicion}"


def test_semantic_core_differs() -> None:
    """去掉开头口头禅后，核心内容不能雷同（不能只换语气词）。"""
    run = generate(seed=20260906)
    for scenario, personas in run.scenarios.items():
        cores: set[str] = set()
        for turns in personas.values():
            for turn in turns:
                if turn["statement"]:
                    core = turn["statement"].split("，", 1)[1] if "，" in turn["statement"] else turn["statement"]
                    cores.add(core)
        assert len(cores) >= 3, f"{scenario} 核心内容太雷同: {cores}"


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


def test_no_fabricated_attribution() -> None:
    """场景四只有 P4 的发言与 P4→P3 的投票，狼人不得归因 P3 有“分析/立场/带节奏”。"""
    run = generate(seed=20260906)
    for turns in run.scenarios["S4_狼人欺骗"].values():
        for turn in turns:
            if turn["statement"]:
                assert "分析有漏洞" not in turn["statement"]
                assert "立场" not in turn["statement"]
                assert "带节奏" not in turn["statement"]
