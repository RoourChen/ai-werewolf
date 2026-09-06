"""Deterministic persona-aware dialogue generation for the offline Mock.

Every statement references a real player id in the context, or explicitly admits
"信息不足". Speech acts are filtered by situation, ranked by
``score = situation_relevance + persona_weight + strategic_need - repetition``,
then composed from persona voice + situation-specific content (not one fixed
sentence per act, and not just synonym-swapped openers).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from ai_werewolf.ai.personas import SPEECH_WEIGHTS


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
    trust_baseline: float = 0.5
    evidence_sensitivity: float = 0.5
    risk_preference: float = 0.5
    lobby_strength: float = 0.5
    vote_resistance: float = 0.5
    deception_tendency: float = 0.5


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
            StatementRecord(s["actor"], s["day"], s["text"]) for s in hint.get("recent_statements", [])
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
def _living_ids(ctx: DialogueContext) -> list[int]:
    return [s.id for s in ctx.living]


def _situation(ctx: DialogueContext) -> dict:
    others = [s.id for s in ctx.living if s.id != ctx.me]
    recent_speakers = [s.actor for s in ctx.recent_statements if s.actor in others]
    mentioned = _mentioned_ids(ctx)
    contradiction = _contradiction_target(ctx)
    return {
        "low_info": not ctx.votes and not ctx.questioned_by and ctx.top_suspicion is None,
        "questioned": bool(ctx.questioned_by),
        "has_votes": bool(ctx.votes),
        "has_speaker": bool(recent_speakers),
        "has_contradiction": contradiction is not None,
        "contradiction": contradiction,
        "mentioned": mentioned,
        "recent_speakers": recent_speakers,
        "can_mislead": ctx.role == "werewolf" and bool(ctx.pack),
    }


def _mentioned_ids(ctx: DialogueContext) -> set[int]:
    out: set[int] = set()
    for s in ctx.recent_statements:
        for m in re.findall(r"P(\d+)", s.text):
            out.add(int(m))
    return out


def _contradiction_target(ctx: DialogueContext) -> int | None:
    """A voter who is also called out in recent statements (speech-vote clash)."""
    mentioned = _mentioned_ids(ctx)
    for v in ctx.votes:
        if v.actor in mentioned and v.actor in _living_ids(ctx) and v.actor != ctx.me:
            return v.actor
    return None


def _most_voted(ctx: DialogueContext) -> int | None:
    targets = [v.target for v in ctx.votes if v.target in _living_ids(ctx) and v.target != ctx.me]
    if not targets:
        return None
    return max(set(targets), key=targets.count)


def _relevance(act: str, ctx: DialogueContext, sit: dict) -> float:
    if act == "defend" and not sit["questioned"]:
        return 0.0
    if act == "mediate" and not (sit["has_votes"] or sit["has_contradiction"] or sit["mentioned"] or sit["has_speaker"]):
        return 0.0
    if act == "inform" and not sit["low_info"]:
        return 0.0
    if act == "question" and not sit["has_speaker"]:
        return 0.0
    if act == "analyze" and not (sit["has_votes"] or sit["has_contradiction"]):
        return 0.0
    if act == "support" and (not sit["has_speaker"] or ctx.role == "werewolf"):
        return 0.0  # 狼人不“支持”非狼，改为误导
    if act == "accuse" and ctx.top_suspicion is None and not sit["has_contradiction"]:
        return 0.0
    if act == "lobby":
        return 0.7 + 0.5 * ctx.lobby_strength
    return 1.0


def _strategic_need(act: str, ctx: DialogueContext) -> float:
    # 狼人不额外强行 accuse/lobby；误导由“目标指向非狼”实现，行为仍由人格决定
    return 0.2 if act in ("question", "analyze") else 0.0


def _situation_boost(act: str, ctx: DialogueContext, sit: dict) -> float:
    """被质疑时，不同人格用不同方式回应（不是所有人都 defend 或都反击）。"""
    if not sit["questioned"]:
        return 0.0
    persona = ctx.persona_id
    if persona == "skeptic":
        return 0.8 if act == "question" else 0.0
    if persona == "aggressor":
        return 0.8 if act in ("accuse", "lobby") else 0.0
    if persona == "analyst":
        return 0.8 if act == "analyze" else 0.0
    if persona == "mediator":
        return 0.8 if act == "mediate" else 0.0
    # nice / chatterbox：解释辩护
    return 0.8 if act == "defend" else 0.0


# ---------------------------------------------------------------- target
def _pick_target(ctx: DialogueContext, act: str) -> int | None:
    others = _living_ids(ctx)
    if not others:
        return None
    others_ex_me = [p for p in others if p != ctx.me]
    sit = _situation(ctx)

    if ctx.role == "werewolf":
        non_pack = [p for p in others_ex_me if p not in ctx.pack]
        if non_pack:
            return _most_threat(ctx, non_pack)
    if act == "defend" and ctx.questioned_by:
        return ctx.questioned_by[0]
    if act == "analyze" and sit["has_contradiction"]:
        return sit["contradiction"]
    if act == "analyze" and sit["has_votes"]:
        return _most_voted(ctx)
    if act == "support":
        for s in reversed(ctx.recent_statements):
            if s.actor in others_ex_me:
                return s.actor
        return others_ex_me[0]
    if act == "accuse":
        if ctx.top_suspicion in others_ex_me:
            return ctx.top_suspicion
        if sit["has_contradiction"]:
            return sit["contradiction"]
        if sit["recent_speakers"]:
            return sit["recent_speakers"][-1]
        return others_ex_me[0]
    if act == "question":
        if sit["has_contradiction"] and sit["contradiction"] in others_ex_me:
            return sit["contradiction"]  # 追问矛盾核心，而非套模板追问最近发言者
        for s in reversed(ctx.recent_statements):
            if s.actor in others_ex_me:
                return s.actor
        return ctx.top_suspicion if ctx.top_suspicion in others_ex_me else others_ex_me[0]
    if act == "inform":
        return None  # 信息不足，无明确怀疑对象
    if act == "mediate":
        return ctx.top_suspicion if ctx.top_suspicion in others_ex_me else (_most_voted(ctx) or others_ex_me[0])
    return ctx.top_suspicion if ctx.top_suspicion in others_ex_me else others_ex_me[0]


def _most_threat(ctx: DialogueContext, candidates: list[int]) -> int:
    # 优先选非人类 AI 作为误导目标（避免六人都指向真人）
    human_ids = {s.id for s in ctx.living if s.is_human}
    ai = [p for p in candidates if p not in human_ids]
    pool = ai or candidates
    threat = ctx.memory_summary.get("strategic_threat", {}) if isinstance(ctx.memory_summary, dict) else {}
    best = None
    best_score = -1.0
    for pid in pool:
        score = float(threat.get(str(pid), threat.get(pid, 0.5)))
        if score > best_score:
            best_score, best = score, pid
    return best if best is not None else pool[0]


# ---------------------------------------------------------------- compose
_LOW_INFO_ACT = {
    "skeptic": "question",
    "nice": "inform",
    "analyst": "analyze",
    "aggressor": "accuse",
    "mediator": "mediate",
    "chatterbox": "inform",
}


def _low_info_line(ctx: DialogueContext, act: str, rng: random.Random) -> str:
    voice = _VOICE.get(ctx.persona_id, _VOICE["mediator"])
    opener = rng.choice(voice["openers"])
    others = [s.id for s in ctx.living if s.id != ctx.me]
    name = _pname(ctx, others[0]) if others else "那位玩家"
    if act == "question":
        return f"{opener}，信息太少，我先问一句：谁有更具体的怀疑？"
    if act == "analyze":
        return f"{opener}，信息不足，我先把已知列一下：目前还没有实质线索。"
    if act == "accuse":
        return f"{opener}，信息不足，但总得先怀疑一个，我暂定 {name}。"
    if act == "mediate":
        return f"{opener}，信息少，先别内讧，我们听一轮。"
    if act == "support":
        return f"{opener}，信息少，我先听大家的，别急着定。"
    return f"{opener}，目前信息不足，我先听一轮再表态。"


# 带“目标/投票意图”的行为：目标即 public_suspicion 最高对象与 intended_vote
_VOTE_ACTS = {"accuse", "lobby", "mediate", "analyze", "question"}


def compose_statement(ctx: DialogueContext, rng: random.Random) -> dict:
    sit = _situation(ctx)
    weights = SPEECH_WEIGHTS.get(ctx.persona_id, SPEECH_WEIGHTS["mediator"])

    if sit["low_info"]:
        act = _LOW_INFO_ACT.get(ctx.persona_id, "inform")
    else:
        scored = []
        for act, weight in weights.items():
            rel = _relevance(act, ctx, sit)
            if rel <= 0.0:
                continue
            scored.append((rel + weight + _strategic_need(act, ctx) + _situation_boost(act, ctx, sit), act))
        if not scored:
            scored = [(1.0, "inform")]
        scored.sort(key=lambda pair: -pair[0])
        top_score = scored[0][0]
        top = [a for s, a in scored if s >= top_score - 0.05]
        act = rng.choice(top)

    target = _pick_target(ctx, act)
    statement = _compose_line(ctx, act, target, rng)
    claim = _claim_for(ctx, act, target)
    changed = _stance_changed(ctx, target)
    return {
        "speech_act": act,
        "target": target,
        "claim": claim,
        "evidence": None,
        "intended_vote": target if act in _VOTE_ACTS else None,
        "stance_changed": changed,
        "change_reason": _change_reason(ctx, act, target) if changed else None,
        "statement": statement,
    }


def _compose_line(ctx: DialogueContext, act: str, target: int | None, rng: random.Random) -> str:
    voice = _VOICE.get(ctx.persona_id, _VOICE["mediator"])
    opener = rng.choice(voice["openers"])
    name = _pname(ctx, target)

    if ctx.role == "werewolf" and target is not None:
        return _wolf_mislead(ctx, act, target, rng)

    if _situation(ctx)["low_info"]:
        return _low_info_line(ctx, act, rng)

    if act == "inform":
        return f"{opener}，目前信息不足，我先听一轮再表态。"

    if act == "defend":
        q = ctx.questioned_by[0] if ctx.questioned_by else None
        if q is not None:
            return f"{opener}，{_pname(ctx, q)} 质疑我，我说明一下：我的判断都来自公开信息，没有隐瞒。"
        return f"{opener}，有人质疑我，我的判断都来自公开信息。"

    if act == "support":
        return f"{opener}，我倾向支持 {name} 的方向。"

    if act == "mediate":
        return f"{opener}，大家的分歧先放一放，我建议统一投 {name}，避免分散票。"

    if act == "lobby":
        return f"{opener}，跟我投 {name}，别分散。"

    if act == "analyze":
        sit = _situation(ctx)
        if sit["has_contradiction"] and sit["contradiction"] is not None:
            c = sit["contradiction"]
            voted_for = [v.target for v in ctx.votes if v.actor == c]
            vtarget = _pname(ctx, voted_for[0]) if voted_for else "别人"
            return _style_analyze(ctx, c, vtarget, rng)
        mv = _most_voted(ctx)
        n = sum(1 for v in ctx.votes if v.target == mv)
        if mv is not None:
            return f"{opener}，先看票型：{_pname(ctx, mv)} 目前被 {n} 票，值得重点核一遍。"
        return f"{opener}，从现有信息看，{name} 值得再观察。"

    if act == "question":
        last = next((s for s in reversed(ctx.recent_statements) if s.actor == target), None)
        if last is not None:
            return f"{opener}，{name}，你刚才说「{last.text[:18]}…」，能再解释一下吗？"
        return f"{opener}，{name}，我想听听你的判断。"

    # accuse
    if ctx.role == "werewolf":
        return f"{opener}，{name} 很可疑，我怀疑是狼。"
    if ctx.risk_preference >= 0.8:
        return f"{opener}，{name} 就是狼，跟我投。"
    return f"{opener}，{name} 的票和发言对不上，我怀疑是狼。"


def _style_analyze(ctx: DialogueContext, c: int, vtarget: str, rng: random.Random) -> str:
    """同是“分析票型矛盾”，不同人格的推理深度与表达不同。"""
    voice = _VOICE.get(ctx.persona_id, _VOICE["mediator"])
    opener = rng.choice(voice["openers"])
    cname = _pname(ctx, c)
    style = voice["style"]
    if style == "analytical":
        return f"{opener}，第一，{cname} 的票和发言对不上；第二，他说过信 {vtarget}，票却投了 {vtarget}。"
    if style == "chatty":
        return f"{opener}，{cname} 这票和发言对不上啊，他说过信 {vtarget} 却投了 {vtarget}，而且也没解释，我先多观察两轮。"
    if style == "friendly":
        return f"{opener}，{cname} 可以理解，但他说信 {vtarget} 却投 {vtarget}，这里有点怪。"
    if style == "aggressive":
        return f"{opener}，{cname} 的票和发言对不上，别洗了。"
    if style == "mediating":
        return f"{opener}，{cname} 的票和发言有矛盾，我们先把这点弄清楚再投。"
    return f"{opener}，{cname} 的票和发言对不上。"


def _wolf_mislead(ctx: DialogueContext, act: str, target: int, rng: random.Random) -> str:
    voice = _VOICE.get(ctx.persona_id, _VOICE["mediator"])
    opener = rng.choice(voice["openers"])
    name = _pname(ctx, target)
    voted_by = [v.actor for v in ctx.votes if v.target == target]  # 真实事实：谁投了 target
    has_stmt = any(s.actor == target for s in ctx.recent_statements)
    if act == "lobby":
        return f"{opener}，跟我投 {name}，别分散。"
    if act == "mediate":
        return f"{opener}，我建议统一投 {name}，别让狼人混过去。"
    if act == "analyze":
        style = voice["style"]
        if voted_by:
            voters = "、".join(f"P{a}" for a in voted_by)
            if style == "analytical":
                return f"{opener}，第一，{voters} 投了 {name}；第二，这个票值得怀疑。"
            if style == "chatty":
                return f"{opener}，{voters} 投了 {name}，这个票我越看越觉得可疑，大家多留意。"
            if style == "friendly":
                return f"{opener}，{voters} 投了 {name}，可能有点问题，但我也说不好。"
            if style == "mediating":
                return f"{opener}，{voters} 投了 {name}，我们先把这一点弄清楚。"
            return f"{opener}，从票型看，{voters} 投了 {name}，这个票值得怀疑。"
        return f"{opener}，我怀疑 {name} 是狼，虽然目前证据不足。"
    if act == "accuse":
        if voted_by:
            voters = "、".join(f"P{a}" for a in voted_by)
            return f"{opener}，{name} 被 {voters} 投过，很可疑。"
        return f"{opener}，{name} 很可疑，我怀疑是狼。"
    if act == "question":
        if has_stmt:
            return f"{opener}，{name} 你刚才的话有点问题，能再解释吗？"
        return f"{opener}，{name} 我很怀疑，你怎么看？"
    return f"{opener}，{name} 值得大家多注意。"


def _claim_for(ctx: DialogueContext, act: str, target: int | None) -> str:
    if target is None:
        return "目前信息不足"
    labels = {
        "inform": "信息不足，先观察",
        "question": f"向 P{target} 追问依据",
        "analyze": f"整理与 P{target} 有关的票型",
        "accuse": f"公开怀疑 P{target}",
        "defend": "回应质疑",
        "support": f"支持 P{target}",
        "lobby": f"拉票投 P{target}",
        "mediate": f"协调并归票 P{target}",
    }
    return labels.get(act, f"关注 P{target}")


def _stance_changed(ctx: DialogueContext, target: int | None) -> bool:
    return target is not None and ctx.my_last_statement is not None and f"P{target}" not in ctx.my_last_statement


def _change_reason(ctx: DialogueContext, act: str, target: int | None) -> str | None:
    if target is None:
        return None
    sit = _situation(ctx)
    if act == "analyze":
        if sit["has_contradiction"]:
            return f"发现 P{target} 的票和发言对不上"
        return f"重新评估 P{target} 的发言"
    if act == "accuse":
        return f"P{target} 的发言可疑"
    if act == "question":
        return f"想追问 P{target} 的依据"
    if act == "lobby":
        return f"想推动放逐 P{target}"
    if act == "mediate":
        return f"为统一票型，建议归票 P{target}"
    if act == "defend":
        return "回应质疑，澄清自己的判断来源"
    if act == "support":
        return f"认可 P{target} 的判断"
    return f"重新评估 P{target}"


def _pname(ctx: DialogueContext, pid: int | None) -> str:
    if pid is None:
        return "那位玩家"
    for s in ctx.living:
        if s.id == pid:
            return f"{s.name}（P{pid}）"
    return f"P{pid}"
