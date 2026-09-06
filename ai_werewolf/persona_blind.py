"""Generate persona blind-test materials from the real Mock engine.

Six personas face the *same* scripted situation in each scenario — only the
persona differs, so observed differences are persona behaviour, not situation.
Each persona produces three turns (statement, statement, vote) with suspicion,
intended vote and stance-change reason, using the actual
:class:`~ai_werewolf.ai.mock.MockProvider` dialogue path (never hand-written).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.personas import PERSONAS
from ai_werewolf.ai.provider import Prompt

PERSONA_IDS = ["skeptic", "nice", "analyst", "aggressor", "mediator", "chatterbox"]
PERSONA_NAMES = {pid: PERSONAS[pid].name for pid in PERSONA_IDS}

ME = 1  # the seat the persona under test occupies

# ---------------------------------------------------------------- scenarios
# 固定“其它玩家”的发言/票型，六个人格看到的局势完全相同。
SCENARIOS: dict[str, dict] = {
    "S1_第一日信息不足": {
        "day": 1,
        "role": "villager",
        "pack": [],
        "scripted_statements": [
            {"actor": 2, "day": 1, "text": "第一天信息太少，我先不急着表态。"},
            {"actor": 3, "day": 1, "text": "没别的，先随便怀疑一个，我暂投 P4。"},
            {"actor": 5, "day": 1, "text": "我也觉得信息不足，先听一轮。"},
        ],
        "scripted_votes": [],
        "questioned_by": [],
    },
    "S2_被质疑": {
        "day": 2,
        "role": "villager",
        "pack": [],
        "scripted_statements": [
            {"actor": 3, "day": 2, "text": "P1 昨天的发言很含糊，我想问他为什么不敢表态。"},
            {"actor": 5, "day": 2, "text": "我也觉得 P1 有点躲，先让他解释一下。"},
        ],
        "scripted_votes": [],
        "questioned_by": [3, 5],
    },
    "S3_票型矛盾": {
        "day": 2,
        "role": "villager",
        "pack": [],
        "scripted_statements": [
            {"actor": 4, "day": 2, "text": "P3 昨天说信 P2，却投了 P2，这票很矛盾。"},
        ],
        "scripted_votes": [
            {"day": 1, "actor": 3, "target": 2, "round": 1},
            {"day": 1, "actor": 4, "target": 3, "round": 1},
        ],
        "questioned_by": [],
    },
    "S4_狼人欺骗": {
        "day": 2,
        "role": "werewolf",
        "pack": [1, 2],
        "scripted_statements": [
            {"actor": 4, "day": 2, "text": "从票型看，P3 和 P5 里大概率有一狼。"},
        ],
        "scripted_votes": [
            {"day": 1, "actor": 4, "target": 3, "round": 1},
        ],
        "questioned_by": [],
    },
}


def _hint(scenario: dict, persona_id: str, kind: str, recent_statements, votes, top_suspicion, my_last, questioned_by) -> dict:
    p = PERSONAS[persona_id]
    living = [{"id": 0, "name": "你", "alive": True, "is_human": True}]
    names = ["Alice", "Bob", "Carol", "Dave", "Erin"]  # 普通名字，不泄露人格
    for i, pid in enumerate([2, 3, 4, 5, 6]):
        living.append({"id": pid, "name": names[i], "alive": True, "is_human": False})
    others = [pid for pid in [0, 2, 3, 4, 5, 6] if pid != ME]
    return {
        "kind": kind,
        "day": scenario["day"],
        "phase": "discussion" if kind == "statement" else "voting",
        "me": ME,
        "me_role": scenario["role"],
        "pack": scenario["pack"],
        "candidates": others,
        "others": others,
        "public": True,
        "persona": persona_id,
        "trust_baseline": p.trust_baseline,
        "evidence_sensitivity": p.evidence_sensitivity,
        "risk_preference": p.risk_preference,
        "lobby_strength": p.lobby_strength,
        "vote_resistance": p.vote_resistance,
        "deception_tendency": p.deception_tendency,
        "living": living,
        "recent_statements": recent_statements,
        "votes": votes,
        "top_suspicion": top_suspicion,
        "my_last_statement": my_last,
        "questioned_by": questioned_by,
        "memory": {},
        "suggestions": [],
    }


def _top(priv: dict) -> int | None:
    if not priv:
        return None
    return int(max(priv, key=lambda k: float(priv[k])))


def generate_persona(scenario: dict, persona_id: str, seed: int) -> list[dict]:
    """Generate 3 turns (statement, statement, vote) for one persona."""
    provider = MockProvider(seed=seed)
    turns: list[dict] = []
    my_statements: list[dict] = []
    suspicion: int | None = None
    my_last: str | None = None

    scripted = scenario["scripted_statements"]
    votes = scenario["scripted_votes"]
    qb = scenario["questioned_by"]

    # turn 1：初步发言
    recent1 = list(scripted[:1])
    d1 = _call(provider, _hint(scenario, persona_id, "statement", recent1, votes, suspicion, my_last, qb))
    suspicion = _suspicion_from(d1)
    turns.append(_turn(d1, "statement", suspicion))
    my_statements.append({"actor": ME, "day": scenario["day"], "text": d1.get("statement", "")})
    my_last = d1.get("statement")

    # turn 2：回应局势
    recent2 = list(scripted) + list(my_statements)
    d2 = _call(provider, _hint(scenario, persona_id, "statement", recent2, votes, suspicion, my_last, qb))
    suspicion = _suspicion_from(d2) if _suspicion_from(d2) is not None else suspicion
    turns.append(_turn(d2, "statement", suspicion))
    my_statements.append({"actor": ME, "day": scenario["day"], "text": d2.get("statement", "")})
    my_last = d2.get("statement")

    # turn 3：投票（= 当前怀疑；若之前“先观察/不强推”却现在投票，需说明）
    d3 = _call(provider, _hint(scenario, persona_id, "vote", recent2, votes, suspicion, my_last, qb))
    if suspicion is None:
        suspicion = 0
        d3["change_reason"] = "信息不足，但必须投票，低置信度选择 P0"
    turns.append(_turn(d3, "vote", suspicion))
    return turns


def _call(provider: MockProvider, hint: dict) -> dict:
    raw = provider.complete(Prompt(system="", user="", hint=hint))
    data = json.loads(raw)
    if not isinstance(data, dict):
        data = {}
    return data


_SUSPICIOUS_ACTS = {"accuse", "lobby", "mediate", "analyze", "question"}


def _suspicion_from(d: dict) -> int | None:
    """只有“怀疑型”行为才产生公开怀疑对象；信息不足/支持/辩护不设怀疑。"""
    if d.get("speech_act") in _SUSPICIOUS_ACTS:
        return d.get("target")
    return None


def _turn(d: dict, kind: str, suspicion: int | None) -> dict:
    intended = d.get("intended_vote")
    if kind == "vote":
        vote = suspicion  # 最终投票 = 当前怀疑（不一致时需理由）
        return {
            "kind": kind,
            "statement": None,
            "speech_act": "",
            "intended_vote": intended,
            "stance_changed": bool(d.get("stance_changed")),
            "change_reason": d.get("change_reason"),
            "top_suspicion": suspicion,
            "vote": vote,
        }
    return {
        "kind": kind,
        "statement": d.get("statement"),
        "speech_act": d.get("speech_act", ""),
        "intended_vote": intended,
        "stance_changed": bool(d.get("stance_changed")),
        "change_reason": d.get("change_reason"),
        "top_suspicion": suspicion,
        "vote": intended if intended is not None else suspicion,
    }


@dataclass
class BlindRun:
    commit: str
    ai_mode: str
    seed: int
    generated_at: str
    scenarios: dict = field(default_factory=dict)  # scenario -> persona -> turns


def generate(seed: int = 20260906, commit: str = "") -> BlindRun:
    scenarios: dict[str, dict[str, list[dict]]] = {}
    for sid, scenario in SCENARIOS.items():
        scenarios[sid] = {}
        for pid in PERSONA_IDS:
            scenarios[sid][pid] = generate_persona(scenario, pid, seed)
    return BlindRun(
        commit=commit,
        ai_mode="offline (Mock)",
        seed=seed,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        scenarios=scenarios,
    )


def shuffle_labels(seed: int) -> list[str]:
    """Return a shuffled persona list; labels are A..F by position."""
    ids = list(PERSONA_IDS)
    random.Random(seed).shuffle(ids)
    return ids


# ---------------------------------------------------------------- render
_SCENARIO_TITLE = {
    "S1_第一日信息不足": "场景一",
    "S2_被质疑": "场景二",
    "S3_票型矛盾": "场景三",
    "S4_狼人欺骗": "场景四",
}


def _scenario_preamble(sid: str) -> str:
    """场景的共享事实（所有 A–F 面对完全相同的这些事实）。"""
    sc = SCENARIOS[sid]
    role_name = {"villager": "村民", "werewolf": "狼人"}[sc["role"]]
    lines = [f"第 {sc['day']} 天；本场景你的身份：{role_name}。"]
    if sc["scripted_statements"]:
        lines.append("此前其他玩家已发言：")
        for s in sc["scripted_statements"]:
            lines.append(f"- P{s['actor']}：{s['text']}")
    if sc["scripted_votes"]:
        lines.append("此前的投票：")
        for v in sc["scripted_votes"]:
            lines.append(f"- 第 {v['day']} 天 P{v['actor']} 投了 P{v['target']}")
    else:
        lines.append("此前投票：无。")
    return "\n".join(lines)


def _render_turns(turns: list[dict]) -> str:
    lines: list[str] = []
    for i, t in enumerate(turns, 1):
        if t["statement"]:
            lines.append(f"  第{i}轮发言：{t['statement']}")
            if t["stance_changed"] and t["change_reason"]:
                lines.append(f"      （较之前改口，理由：{t['change_reason']}）")
            if t["top_suspicion"] is not None:
                lines.append(f"      公开怀疑：P{t['top_suspicion']}")
        else:
            lines.append(f"  第{i}轮投票：P{t['vote']}；公开怀疑 P{t['top_suspicion']}")
    return "\n".join(lines)


def render_header(run: BlindRun) -> str:
    return (
        f"> 可复现信息：commit {run.commit} ｜ AI 模式 {run.ai_mode} ｜ seed {run.seed} ｜ 生成时间 {run.generated_at}"
    )


def render_questions(run: BlindRun, shuffle_seed: int, material_version: int) -> str:
    labels = shuffle_labels(shuffle_seed)
    label_names = {pid: chr(ord('A') + i) for i, pid in enumerate(labels)}
    parts = [
        f"# 人格盲测题（材料版本 {material_version}，乱序组 {shuffle_seed}，无答案）",
        "",
        render_header(run),
        "",
        "下面有六名 AI（标为 A–F），它们面对**完全相同**的局势。请根据它们的发言、怀疑变化、投票与改口理由，判断每个人格是谁。",
        "",
    ]
    for sid, personas in run.scenarios.items():
        parts.append("## " + _SCENARIO_TITLE[sid])
        parts.append("")
        parts.append(_scenario_preamble(sid))
        parts.append("")
        for pid in labels:
            label = label_names[pid]
            parts.append(f"### {label}")
            parts.append(_render_turns(personas[pid]))
            parts.append("")
    parts.append("请填写：A=____ B=____ C=____ D=____ E=____ F=____（可选项：质疑者 / 老好人 / 分析家 / 激进派 / 和事佬 / 话痨）")
    return "\n".join(parts)


def render_answers(run: BlindRun, shuffle_seed: int, material_version: int) -> str:
    labels = shuffle_labels(shuffle_seed)
    label_names = {pid: chr(ord('A') + i) for i, pid in enumerate(labels)}
    parts = [
        f"# 人格盲测答案与评分规则（材料版本 {material_version}，乱序组 {shuffle_seed}）",
        "",
        render_header(run),
        "",
        "## 答案",
        "",
    ]
    for pid in labels:
        parts.append(f"- {label_names[pid]} = {PERSONA_NAMES[pid]}")
    parts.append("")
    parts.append("## 评分规则")
    parts.append("")
    parts.append("- 通过门槛：至少 4/5 名测试者，每人正确匹配不少于 4/6 人格。")
    parts.append("- 若测试者主要靠「角色名称提示词」（如看到「拉票」就猜激进派）而非跨场景的稳定行为辨认，则不算通过。")
    parts.append("- 本材料只证明离线 Mock 的人格可辨；真实 LLM 人格验收需在服务端配置 Key 后单独进行。")
    return "\n".join(parts)
