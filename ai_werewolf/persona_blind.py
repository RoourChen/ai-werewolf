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
    names = ["老好人", "质疑者", "激进派", "分析家", "和事佬", "话痨"]
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
    top_suspicion: int | None = None
    my_last: str | None = None

    scripted = scenario["scripted_statements"]
    votes = scenario["scripted_votes"]
    qb = scenario["questioned_by"]

    # turn 1：初步发言
    recent1 = list(scripted[:1])
    d1 = _call(provider, _hint(scenario, persona_id, "statement", recent1, votes, top_suspicion, my_last, qb))
    turns.append(_turn(d1, "statement"))
    my_statements.append({"actor": ME, "day": scenario["day"], "text": d1.get("statement", "")})
    my_last = d1.get("statement")
    top_suspicion = _top(d1.get("private_suspicion", {})) or top_suspicion

    # turn 2：回应局势（加入其它玩家后续发言 + 我上一句）
    recent2 = list(scripted) + list(my_statements)
    d2 = _call(provider, _hint(scenario, persona_id, "statement", recent2, votes, top_suspicion, my_last, qb))
    turns.append(_turn(d2, "statement"))
    my_statements.append({"actor": ME, "day": scenario["day"], "text": d2.get("statement", "")})
    my_last = d2.get("statement")
    top_suspicion = _top(d2.get("private_suspicion", {})) or top_suspicion

    # turn 3：投票
    d3 = _call(provider, _hint(scenario, persona_id, "vote", recent2, votes, top_suspicion, my_last, qb))
    turns.append(_turn(d3, "vote"))
    return turns


def _call(provider: MockProvider, hint: dict) -> dict:
    raw = provider.complete(Prompt(system="", user="", hint=hint))
    data = json.loads(raw)
    if not isinstance(data, dict):
        data = {}
    return data


def _turn(d: dict, kind: str) -> dict:
    priv = d.get("private_suspicion", {}) or {}
    top = _top(priv)
    intended = d.get("intended_vote")
    vote = intended if intended is not None else top
    if kind == "vote":
        vote = d.get("choice") if d.get("choice") is not None else vote
    return {
        "kind": kind,
        "statement": d.get("statement") if kind == "statement" else None,
        "speech_act": d.get("speech_act", ""),
        "intended_vote": intended,
        "stance_changed": bool(d.get("stance_changed")),
        "change_reason": d.get("change_reason"),
        "top_suspicion": top,
        "vote": vote,
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
    "S1_第一日信息不足": "场景一：第一日信息不足（初步发言）",
    "S2_被质疑": "场景二：被其他玩家质疑（需要回应）",
    "S3_票型矛盾": "场景三：发现发言与票型矛盾（需要归票）",
    "S4_狼人欺骗": "场景四：狼人欺骗（拿到狼人后如何误导）",
}


def _render_turns(turns: list[dict]) -> str:
    lines: list[str] = []
    for i, t in enumerate(turns, 1):
        if t["statement"]:
            lines.append(f"  第{i}轮发言：{t['statement']}")
            if t["stance_changed"] and t["change_reason"]:
                lines.append(f"      （较之前改口，理由：{t['change_reason']}）")
            if t["top_suspicion"] is not None:
                lines.append(f"      当前怀疑：P{t['top_suspicion']}")
        else:
            lines.append(f"  第{i}轮投票：P{t['vote']}；当前怀疑 P{t['top_suspicion']}")
    return "\n".join(lines)


def render_header(run: BlindRun) -> str:
    return (
        f"> 可复现信息：commit {run.commit} ｜ AI 模式 {run.ai_mode} ｜ seed {run.seed} ｜ 生成时间 {run.generated_at}"
    )


def render_questions(run: BlindRun, shuffle_seed: int) -> str:
    labels = shuffle_labels(shuffle_seed)
    label_names = {pid: chr(ord('A') + i) for i, pid in enumerate(labels)}
    parts = [
        "# 人格盲测题（版本 " + str(shuffle_seed) + "，无答案）",
        "",
        render_header(run),
        "",
        "下面有六名 AI（标为 A–F），它们面对**完全相同**的局势。请根据它们的发言、怀疑变化、投票与改口理由，判断每个人格是谁。",
        "",
    ]
    for sid, personas in run.scenarios.items():
        parts.append("## " + _SCENARIO_TITLE[sid])
        parts.append("")
        for pid in labels:
            label = label_names[pid]
            parts.append(f"### {label}")
            parts.append(_render_turns(personas[pid]))
            parts.append("")
    parts.append("请填写：A=____ B=____ C=____ D=____ E=____ F=____（可选项：质疑者 / 老好人 / 分析家 / 激进派 / 和事佬 / 话痨）")
    return "\n".join(parts)


def render_answers(run: BlindRun, shuffle_seed: int) -> str:
    labels = shuffle_labels(shuffle_seed)
    label_names = {pid: chr(ord('A') + i) for i, pid in enumerate(labels)}
    parts = [
        "# 人格盲测答案与评分规则（版本 " + str(shuffle_seed) + "）",
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
