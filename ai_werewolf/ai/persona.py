"""Prompt building for LLM players.

Turns a :class:`~ai_werewolf.domain.state.PlayerView`, a persona and a
:class:`~ai_werewolf.domain.state.DecisionRequest` into a structured
:class:`~ai_werewolf.ai.provider.Prompt`. The JSON reply schema asks for the
three suspicion channels (private / public / strategic threat), a short
rationale, an *event-id* evidence reference and an explicit deception plan, so
every decision can be traced and audited.
"""

from __future__ import annotations

from ai_werewolf.ai.personas import Persona
from ai_werewolf.ai.provider import Prompt
from ai_werewolf.domain.actions import ActionKind
from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.roles import Faction
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.i18n import L10n

_ASK: dict[str, tuple[str, str]] = {
    "night_kill": (
        "现在是夜晚。作为狼人，提出一个猎杀建议（不能是狼人）。",
        "It is night. As a werewolf, suggest a victim (not a werewolf).",
    ),
    "pack_confirm": (
        "你的 AI 狼队友已给出建议，请最终确认猎杀目标。",
        "Your AI packmates suggested targets; confirm the final kill.",
    ),
    "night_inspect": (
        "现在是夜晚。作为预言家，选择一名存活玩家查验阵营。",
        "It is night. As the seer, choose one living player to inspect.",
    ),
    "vote": (
        "现在是投票环节。选择一名存活玩家放逐。",
        "It is the daytime vote. Choose one living player to lynch.",
    ),
    "statement": (
        "现在是讨论环节。发表一段简短发言（2-4 句）。",
        "It is the discussion phase. Make a short statement (2-4 sentences).",
    ),
    "last_words": (
        "你被放逐。请说一句遗言。",
        "You are lynched. Say your last words.",
    ),
    "bid": (
        "为发言权竞价，0-10 表示你有多想发言。",
        "Bid for the floor: 0-10, how much do you need to speak?",
    ),
}

_WOLF_RULES = {
    "zh": (
        "你是狼人，必须伪装成村民、必要时撒谎误导。所有狼人都可以撒谎，"
        "只是欺骗方式与强度不同：按你的人格选择欺骗风格。绝不要泄露狼队名单。"
        "你的 private_suspicion 反映你已知的事实：对已知狼人填 1，对已知非狼人填 0；"
        "用 strategic_threat 衡量对方对你狼队的威胁；用 public_suspicion 表演你"
        "想公开表现的怀疑。"
    ),
    "en": (
        "You are a werewolf: disguise yourself and lie when useful. Every wolf may "
        "lie, differing only in style and intensity — follow your persona. Never "
        "reveal the pack. private_suspicion reflects known facts: 1 for known "
        "wolves, 0 for known non-wolves; use strategic_threat for danger to your "
        "pack; use public_suspicion for the doubt you choose to perform."
    ),
}

_LANG = {"zh": "请使用简体中文。", "en": "Please answer in English."}

_PUBLIC_KINDS = {ActionKind.STATEMENT, ActionKind.VOTE}


def build_prompt(view: PlayerView, request: DecisionRequest, persona: Persona) -> Prompt:
    l10n = L10n(view.language)
    return Prompt(
        system=_system(view, persona, l10n),
        user=_user(view, request, persona, l10n),
        hint=_hint(view, request, persona),
    )


def _system(view: PlayerView, persona: Persona, l10n: L10n) -> str:
    role = l10n.role_name(view.my_role)
    brief = l10n.role_brief(view.my_role)
    text = (
        f"你在玩一局 7 人狼人杀。你是 {view.name(view.me)}（P{view.me}），身份是{role}。{brief}\n"
        f"你的人格：{persona.name}——{persona.speech_style}。\n"
        f"行为倾向（0-1，仅为倾向而非固定概率）：信任基线 {persona.trust_baseline}、"
        f"证据敏感度 {persona.evidence_sensitivity}、风险偏好 {persona.risk_preference}、"
        f"拉票强度 {persona.lobby_strength}、改票阻力 {persona.vote_resistance}、"
        f"欺骗倾向 {persona.deception_tendency}。\n"
        "决策优先级：游戏合法性 > 阵营获胜目标 > 人格倾向。\n"
        "只依据你可见的信息行动，不要使用你无权知道的信息；evidence 只能引用对局日志里"
        "你可见的事件编号（E 开头），没有依据就填 null。\n"
        "阵营目标：村民阵营在狼人全灭时获胜；狼人阵营在狼人数达到或超过其余存活玩家时获胜。\n"
        + _LANG[view.language]
    )
    if view.my_role.faction is Faction.WEREWOLVES:
        text += "\n" + _WOLF_RULES[view.language]
    return text


def _user(
    view: PlayerView, request: DecisionRequest, persona: Persona, l10n: L10n
) -> str:
    parts = [
        f"=== 第 {view.day} 天 ===" if view.language == "zh" else f"=== Day {view.day} ===",
        _seats_block(view),
        _secrets_block(view),
        _log_block(view),
        _ASK[request.kind.value][0 if view.language == "zh" else 1],
    ]
    if request.legal_targets:
        named = ", ".join(f"{view.name(c)} (P{c})" for c in request.legal_targets)
        parts.append(
            f"合法目标：{named}。" if view.language == "zh" else f"Legal targets: {named}."
        )
    if request.suggestions:
        named = ", ".join(f"P{c}" for c in request.suggestions)
        parts.append(
            f"狼队友建议：{named}。" if view.language == "zh" else f"Pack suggestions: {named}."
        )
    parts.append(_reply_format(view, request))
    return "\n\n".join(p for p in parts if p)


def _reply_format(view: PlayerView, request: DecisionRequest) -> str:
    lang = view.language
    if request.kind is ActionKind.BID:
        return (
            '只回复一个 JSON：{"priority": <0-10 整数>, "reason": "<简短理由>"}。'
            if lang == "zh"
            else 'Reply with ONLY JSON: {"priority": <int 0-10>, "reason": "<short>"}.'
        )
    if request.kind is ActionKind.LAST_WORDS:
        return (
            '只回复一个 JSON：{"statement": "<你的遗言，建议60-100字，最多120字>"}。'
            if lang == "zh"
            else 'Reply with ONLY JSON: {"statement": "<last words, 60-100 chars suggested, max 120>"}.'
        )
    if request.kind is ActionKind.WITCH_POTIONS:
        action_key = (
            '{"heal": true|false, "poison": <玩家编号|null>}'
            if lang == "zh"
            else '{"heal": true|false, "poison": <player id|null>}'
        )
    elif request.kind is ActionKind.STATEMENT:
        action_key = (
            '{"statement": "<你的发言>"}'
            if lang == "zh"
            else '{"statement": "<your words>"}'
        )
    else:
        action_key = (
            '{"choice": <玩家编号整数>}'
            if lang == "zh"
            else '{"choice": <player id int>}'
        )

    others = "、".join(str(pid) for pid in view.living_others()) or "无"
    public_part = ""
    if request.kind in _PUBLIC_KINDS:
        public_part = (
            ', "public_suspicion": {<每个存活其他玩家编号>: <0-1>}'
            if lang == "zh"
            else ', "public_suspicion": {<each living other id>: <0-1>}'
        )
    return (
        f"只回复一个 JSON 对象：{action_key}, "
        f'"reasoning": "<一句话>", "confidence": <0-1>, "evidence": <可见事件编号整数/数组|null>, '
        f'"private_suspicion": {{<每个存活其他玩家编号>: <0-1>}}{public_part}, '
        f'"strategic_threat": {{<每个存活其他玩家编号>: <0-1>}}, '
        f'"deception": {{"active": false|true, "target": <整数编号|null>, '
        f'"public_statement": "<公开说法>", "purpose": "<欺骗目的>", '
        f'"true_basis": "<真实依据>", "fabricated_event": <被编造事件的可见编号|null>}}。'
        f"默认 public_suspicion 与 private_suspicion 应完全相同；只有当你要故意公开表现出与真实判断不同的怀疑时才让二者不同，此时必须 active=true 且 target=该玩家的整数编号。"
        f"任何 public 与 private 差值≥0.20 都必须 active=true，且 target 就是产生该差值的那个玩家（例：P3 的 private=0.1 而 public=0.9，则 target=3）。"
        f"三个怀疑分映射（private_suspicion、strategic_threat 及 public_suspicion）必须恰好包含以下每个编号且值为 0-1 数字，不得遗漏、多余或越界：{others}。"
        if lang == "zh"
        else f"Reply with ONLY a JSON object: {action_key}, "
        f'"reasoning": "<one sentence>", "confidence": <0-1>, "evidence": <visible event id int/array|null>, '
        f'"private_suspicion": {{<each living other id>: <0-1>}}{public_part}, '
        f'"strategic_threat": {{<each living other id>: <0-1>}}, '
        f'"deception": {{"active": false|true, "target": <int id|null>, '
        f'"public_statement": "<public claim>", "purpose": "<purpose>", '
        f'"true_basis": "<true basis>", "fabricated_event": <fabricated visible event id|null>}}.'
        f" By default public_suspicion must equal private_suspicion; only when you deliberately show a different suspicion than your true belief may they differ, and then you must set active=true with target = that player's int id."
        f" Any public-vs-private gap >= 0.20 must set active=true, and target must be the player with that gap (e.g. P3 private=0.1 public=0.9 -> target=3)."
        f" The three suspicion maps (private_suspicion, strategic_threat, public_suspicion) must cover exactly these ids with 0-1 numbers, no missing/extra/out-of-range: {others}."
    )


def _hint(view: PlayerView, request: DecisionRequest, persona: Persona) -> dict:
    return {
        "kind": request.kind.value,
        "candidates": list(request.legal_targets),
        "lang": view.language,
        "can_heal": request.can_heal,
        "can_poison": request.can_poison,
        "suggestions": list(request.suggestions),
        "me_role": view.my_role.value,
        "pack": list(view.packmates),
        "others": [pid for pid in view.living if pid != view.me],
        "public": request.kind in _PUBLIC_KINDS,
        "day": view.day,
        "event_ids": [e.id for e in view.events],
        "persona": persona.id,
        "trust_baseline": persona.trust_baseline,
        "evidence_sensitivity": persona.evidence_sensitivity,
        "risk_preference": persona.risk_preference,
        "lobby_strength": persona.lobby_strength,
        "vote_resistance": persona.vote_resistance,
        "deception_tendency": persona.deception_tendency,
    }


def _seats_block(view: PlayerView) -> str:
    alive = "存活" if view.language == "zh" else "alive"
    dead = "已死亡" if view.language == "zh" else "DEAD"
    you = "  ← 你" if view.language == "zh" else "  <- you"
    rows = []
    for s in view.seats:
        tag = alive if s.alive else dead
        mark = you if s.id == view.me else ""
        rows.append(f"  P{s.id} {s.name}: {tag}{mark}")
    label = "玩家：" if view.language == "zh" else "Players:"
    return label + "\n" + "\n".join(rows)


def _secrets_block(view: PlayerView) -> str:
    if not view.secrets:
        return ""
    label = "只有你知道的信息：" if view.language == "zh" else "What only you know:"
    return label + "\n" + "\n".join(f"  - {s}" for s in view.secrets)


def _log_block(view: PlayerView) -> str:
    secret = "  [私密] " if view.language == "zh" else "  [secret] "
    lines = []
    for e in view.events:
        if e.kind in (EventKind.ROLE_DEALT, EventKind.PACK_MATES):
            continue
        prefix = f"E{e.id} "
        lines.append(("  " if e.is_public() else secret) + prefix + e.text)
    label = "对局日志（E 为事件编号）：" if view.language == "zh" else "Game log (E = event id):"
    if not lines:
        return label + ("（暂无事件）" if view.language == "zh" else " (no events yet)")
    return label + "\n" + "\n".join(lines)
