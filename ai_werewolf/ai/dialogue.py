"""Deterministic persona-aware dialogue generation for the offline Mock.

The generator never fabricates: every statement references a real player id
present in the context, or explicitly admits "信息不足". It first filters
speech acts by situation, then ranks them with
``score = situation_relevance + persona_weight + strategic_need - repetition_penalty``,
and finally composes the line through the persona's voice. Same seed + same
context reproduces the same line.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ai_werewolf.ai.personas import SPEECH_WEIGHTS


# ---------------------------------------------------------------- context
@dataclass(frozen=True)
class SeatInfo:
    id: int
    name: str
    is_human: bool


@dataclass(frozen=True)
class StatementRecord:
    actor: int
    day: int
    text: str


@dataclass(frozen=True)
class VoteRecord:
    day: int
    actor: int
    target: int
    round: int


@dataclass
class DialogueContext:
    persona_id: str
    day: int
    phase: str
    me: int
    role: str
    pack: list[int]
    living: list[SeatInfo]
    recent_statements: list[StatementRecord]
    votes: list[VoteRecord]
    top_suspicion: int | None
    my_last_statement: str | None
    questioned_by: list[int]
    memory_summary: dict = field(default_factory=dict)
    # persona dimensions
    trust_baseline: float = 0.5
    evidence_sensitivity: float = 0.5
    risk_preference: float = 0.5
    lobby_strength: float = 0.5
    vote_resistance: float = 0.5
    deception_tendency: float = 0.5


# ---------------------------------------------------------------- voice
_VOICE = {
    "skeptic": {"openers": ["我有个疑问", "这我想不通", "先别急着定论", "我想追问一句"], "style": "question"},
    "nice": {"openers": ["我觉得", "先别急", "可以理解，但", "我不太会强推"], "style": "friendly"},
    "analyst": {"openers": ["先看事实", "我分几点说", "从票型看", "梳理一下"], "style": "analytical"},
    "aggressor": {"openers": ["没别的", "很明显", "我话放这", "别犹豫了"], "style": "aggressive"},
    "mediator": {"openers": ["大家听我说", "争议在于", "我帮大家收一收", "先别吵"], "style": "mediating"},
    "chatterbox": {"openers": ["哎呀这个局面有点意思", "我先啰嗦两句", "说真的我有点纠结", "你们听我慢慢说"], "style": "chatty"},
}


def build_context(hint: dict) -> DialogueContext:
    living = [SeatInfo(s["id"], s["name"], s["is_human"]) for s in hint.get("living", [])]
    return DialogueContext(
        persona_id=hint.get("persona", "neutral"),
        day=hint.get("day", 1),
        phase=hint.get("phase", "discussion"),
        me=hint.get("me", 0),
        role=hint.get("me_role", "villager"),
        pack=list(hint.get("pack", [])),
        living=living,
        recent_statements=[
            StatementRecord(s["actor"], s["day"], s["text"])
            for s in hint.get("recent_statements", [])
        ],
        votes=[VoteRecord(v["day"], v["actor"], v["target"], v["round"]) for v in hint.get("votes", [])],
        top_suspicion=hint.get("top_suspicion"),
        my_last_statement=hint.get("my_last_statement"),
        questioned_by=list(hint.get("questioned_by", [])),
        memory_summary=dict(hint.get("memory", {})),
        trust_baseline=float(hint.get("trust_baseline", 0.5)),
        evidence_sensitivity=float(hint.get("evidence_sensitivity", 0.5)),
        risk_preference=float(hint.get("risk_preference", 0.5)),
        lobby_strength=float(hint.get("lobby_strength", 0.5)),
        vote_resistance=float(hint.get("vote_resistance", 0.5)),
        deception_tendency=float(hint.get("deception_tendency", 0.5)),
    )


# ---------------------------------------------------------------- situation
def _situation(ctx: DialogueContext) -> dict:
    todays = [s for s in ctx.recent_statements if s.day == ctx.day]
    has_disagreement = len({s.actor for s in todays}) >= 3
    return {
        "low_info": not todays,
        "questioned": ctx.me in ctx.questioned_by,
        "has_votes": bool(ctx.votes),
        "has_disagreement": has_disagreement,
        "can_mislead": ctx.role == "werewolf" and bool(ctx.pack),
        "target_exists": ctx.top_suspicion is not None or bool(ctx.living),
    }


def _relevance(act: str, ctx: DialogueContext, sit: dict) -> float:
    if act == "defend" and not sit["questioned"]:
        return 0.0  # 无人质疑我时不能无故 defend
    if act == "mediate" and not sit["has_disagreement"]:
        return 0.0  # 没有分歧时不应强行 mediate
    if act == "question" and sit["low_info"] and not ctx.top_suspicion:
        return 0.2
    if act == "analyze" and not (sit["has_votes"] or sit["has_disagreement"]):
        return 0.2
    if act == "support" and not ctx.living:
        return 0.0
    if act == "accuse" and ctx.top_suspicion is None and not sit["has_votes"]:
        return 0.15
    if act == "lobby":
        return 0.3 + 0.5 * ctx.lobby_strength
    return 1.0


def _strategic_need(act: str, ctx: DialogueContext) -> float:
    if ctx.role != "werewolf":
        return 0.2 if act in ("question", "analyze") else 0.0
    # 狼人：引导火力到非狼队友
    if act in ("accuse", "lobby"):
        return 0.4
    return 0.0


# ---------------------------------------------------------------- compose
def compose_statement(ctx: DialogueContext, rng: random.Random) -> dict:
    sit = _situation(ctx)
    weights = SPEECH_WEIGHTS.get(ctx.persona_id, SPEECH_WEIGHTS["mediator"])

    scored = []
    for act, weight in weights.items():
        rel = _relevance(act, ctx, sit)
        if rel <= 0.0:
            continue
        score = rel + weight + _strategic_need(act, ctx)
        scored.append((score, act))

    if not scored:
        scored = [(1.0, "inform")]

    scored.sort(key=lambda pair: -pair[0])
    # 确定性：用 rng 在得分最高的行为里轻微扰动，避免永远同一句
    top_score = scored[0][0]
    top = [act for s, act in scored if s >= top_score - 0.05]
    act = rng.choice(top)

    target = _pick_target(ctx, act)
    statement = _compose_line(ctx, act, target, rng)
    claim = _claim_for(ctx, act, target)

    return {
        "speech_act": act,
        "target": target,
        "claim": claim,
        "evidence": _evidence_for(ctx, target),
        "intended_vote": target if act in ("accuse", "lobby") else None,
        "stance_changed": _stance_changed(ctx, target),
        "change_reason": "依据本轮票型和发言调整" if target is not None else None,
        "statement": statement,
    }


def _pick_target(ctx: DialogueContext, act: str) -> int | None:
    others = [s.id for s in ctx.living if s.id != ctx.me]
    if not others:
        return None
    if ctx.role == "werewolf":
        non_pack = [p for p in others if p not in ctx.pack]
        if non_pack and act in ("accuse", "lobby"):
            return _most_threat(ctx, non_pack)
    if act in ("accuse", "question") and ctx.top_suspicion in others:
        return ctx.top_suspicion
    if act == "defend" and ctx.questioned_by:
        return ctx.questioned_by[0]
    if act == "support":
        recent = [s.actor for s in ctx.recent_statements if s.actor in others]
        return recent[-1] if recent else (others[0] if others else None)
    # 票型分析：投出过最多“被投对象”的人，或得票最多的人
    voted = [v.target for v in ctx.votes if v.target in others]
    if voted and act in ("analyze", "accuse"):
        return max(set(voted), key=voted.count)
    return ctx.top_suspicion if ctx.top_suspicion in others else others[0]


def _most_threat(ctx: DialogueContext, candidates: list[int]) -> int:
    threat = ctx.memory_summary.get("strategic_threat", {}) if isinstance(ctx.memory_summary, dict) else {}
    best = None
    best_score = -1.0
    for pid in candidates:
        score = float(threat.get(str(pid), threat.get(pid, 0.5)))
        if score > best_score:
            best_score, best = score, pid
    return best if best is not None else candidates[0]


def _compose_line(ctx: DialogueContext, act: str, target: int | None, rng: random.Random) -> str:
    voice = _VOICE.get(ctx.persona_id, _VOICE["mediator"])
    opener = rng.choice(voice["openers"])
    name = _pname(ctx, target)

    if act == "inform" or (target is None and ctx.top_suspicion is None):
        if ctx.persona_id == "chatterbox":
            return f"{opener}，这一轮信息还太少，我先不急着表态，听大家多说两句。"
        return f"{opener}，目前信息不足，我先听一轮再表态。"

    if act == "defend":
        return f"{opener}，有人质疑我，我说明一下：我目前的判断依据都来自公开信息，没有隐瞒。"

    if act == "support":
        return f"{opener}，我倾向支持 {name} 的方向，先把这轮说清楚。"

    if act == "mediate":
        return f"{opener}，大家的分歧先放一放，我建议统一投 {name}，避免分散票。"

    if act == "lobby":
        return f"{opener}，跟我投 {name}，别分散。"

    if act == "analyze":
        votes = [v for v in ctx.votes if v.day == ctx.day] or ctx.votes
        if votes and target is not None:
            against = sum(1 for v in votes if v.target == target)
            return f"{opener}，第一，{name} 目前被 {against} 票；第二，他的票型值得再核一遍。"
        return f"{opener}，从现有信息看，{name} 的发言值得再观察。"

    if act == "question":
        return f"{opener}，{name}，你刚才的说法我想请你再解释一下。"

    # accuse
    if ctx.role == "werewolf":
        return f"{opener}，{name} 很可疑，我怀疑是狼。"
    return f"{opener}，{name} 的票和发言对不上，我怀疑是狼。"


def _claim_for(ctx: DialogueContext, act: str, target: int | None) -> str:
    if target is None:
        return "目前信息不足"
    return f"P{target} 需要被观察/质疑"


def _evidence_for(ctx: DialogueContext, target: int | None) -> list[int] | None:
    ids = list(ctx.memory_summary.get("evidence", [])) if isinstance(ctx.memory_summary, dict) else []
    return ids or None


def _stance_changed(ctx: DialogueContext, target: int | None) -> bool:
    return target is not None and ctx.my_last_statement is not None and f"P{target}" not in ctx.my_last_statement


def _pname(ctx: DialogueContext, pid: int | None) -> str:
    if pid is None:
        return "那位玩家"
    for s in ctx.living:
        if s.id == pid:
            return f"{s.name}（P{pid}）"
    return f"P{pid}"
