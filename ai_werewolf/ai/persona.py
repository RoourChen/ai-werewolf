"""Prompt building for LLM players.

These helpers turn a :class:`~ai_werewolf.domain.state.PlayerView` and a
:class:`~ai_werewolf.domain.state.DecisionRequest` into a structured
:class:`~ai_werewolf.ai.provider.Prompt`. The prose is written for this
project and is localised; the JSON reply schema is stable so the offline
:class:`~ai_werewolf.ai.mock.MockProvider` can answer without a model.
"""

from __future__ import annotations

from ai_werewolf.ai.provider import Prompt
from ai_werewolf.domain.actions import ActionKind
from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.i18n import L10n

_ASK: dict[str, tuple[str, str]] = {
    "night_kill": (
        "现在是夜晚。作为狼人，选择一名存活玩家猎杀。",
        "It is night. As a werewolf, choose one living player to kill.",
    ),
    "night_inspect": (
        "现在是夜晚。作为预言家，选择一名存活玩家查验阵营。",
        "It is night. As the seer, choose one living player to inspect.",
    ),
    "night_protect": (
        "现在是夜晚。作为守卫，选择一名存活玩家守护。",
        "It is night. As the guard, choose one living player to protect.",
    ),
    "vote": (
        "现在是投票环节。选择一名存活玩家放逐。",
        "It is the daytime vote. Choose one living player to lynch.",
    ),
    "hunter_shot": (
        "你是猎人且刚刚死亡。选择一名存活玩家开枪带走。",
        "You are the hunter and just died. Choose one living player to shoot.",
    ),
    "statement": (
        "现在是讨论环节。发表一段简短发言（2-4 句）。",
        "It is the discussion phase. Make a short statement (2-4 sentences).",
    ),
    "bid": (
        "为发言权竞价，0-10 表示你有多想发言。",
        "Bid for the floor: 0-10, how much do you need to speak?",
    ),
}

_LANG = {"zh": "请使用简体中文。", "en": "Please answer in English."}


def build_prompt(view: PlayerView, request: DecisionRequest) -> Prompt:
    l10n = L10n(view.language)
    return Prompt(
        system=_system(view, l10n),
        user=_user(view, request, l10n),
        hint=_hint(view, request),
    )


def _system(view: PlayerView, l10n: L10n) -> str:
    role = l10n.role_name(view.my_role)
    brief = l10n.role_brief(view.my_role)
    return (
        f"你在玩一局狼人杀。你是 {view.name(view.me)}（P{view.me}），"
        f"身份是{role}。{brief}\n"
        "目标：村民阵营在狼人全灭时获胜；狼人阵营在狼人数达到或超过其余存活玩家时获胜。\n"
        "只依据你可见的信息行动，不要透露你本不该知道的信息。\n"
        + _LANG[view.language]
    )


def _user(view: PlayerView, request: DecisionRequest, l10n: L10n) -> str:
    parts = [
        f"=== 第 {view.day} 天 ===" if view.language == "zh" else f"=== Day {view.day} ===",
        _seats_block(view, l10n),
        _secrets_block(view, l10n),
        _log_block(view, l10n),
        _ASK[request.kind.value][0 if view.language == "zh" else 1],
    ]
    if request.legal_targets:
        named = ", ".join(f"{view.name(c)} (P{c})" for c in request.legal_targets)
        parts.append(
            f"合法目标：{named}。" if view.language == "zh" else f"Legal targets: {named}."
        )
    parts.append(_reply_format(request, view.language))
    return "\n\n".join(p for p in parts if p)


def _reply_format(request: DecisionRequest, language: str) -> str:
    if request.kind is ActionKind.STATEMENT:
        return (
            '只回复一个 JSON：{"statement": "<你的发言>"}。'
            if language == "zh"
            else 'Reply with ONLY JSON: {"statement": "<your words>"}.'
        )
    if request.kind is ActionKind.WITCH_POTIONS:
        return (
            '只回复一个 JSON：{"heal": true|false, "poison": <玩家编号|null>}。'
            if language == "zh"
            else 'Reply with ONLY JSON: {"heal": true|false, "poison": <player id|null>}.'
        )
    if request.kind is ActionKind.BID:
        return (
            '只回复一个 JSON：{"priority": <0-10 整数>, "reason": "<简短理由>"}。'
            if language == "zh"
            else 'Reply with ONLY JSON: {"priority": <int 0-10>, "reason": "<short>"}.'
        )
    return (
        '只回复一个 JSON：{"choice": <玩家编号整数>, "reasoning": "<一句话理由>"}。'
        if language == "zh"
        else 'Reply with ONLY JSON: {"choice": <player id int>, "reasoning": "<one sentence>"}.'
    )


def _hint(view: PlayerView, request: DecisionRequest) -> dict:
    return {
        "kind": request.kind.value,
        "candidates": list(request.legal_targets),
        "lang": view.language,
        "can_heal": request.can_heal,
        "can_poison": request.can_poison,
    }


def _seats_block(view: PlayerView, l10n: L10n) -> str:
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


def _secrets_block(view: PlayerView, l10n: L10n) -> str:
    if not view.secrets:
        return ""
    label = "只有你知道的信息：" if view.language == "zh" else "What only you know:"
    return label + "\n" + "\n".join(f"  - {s}" for s in view.secrets)


def _log_block(view: PlayerView, l10n: L10n) -> str:
    secret = "  [私密] " if view.language == "zh" else "  [secret] "
    lines = []
    for e in view.events:
        if e.kind in (EventKind.ROLE_DEALT, EventKind.PACK_MATES):
            continue
        lines.append(("  " if e.is_public() else secret) + e.text)
    label = "对局日志：" if view.language == "zh" else "Game log:"
    if not lines:
        return label + ("（暂无事件）" if view.language == "zh" else " (no events yet)")
    return label + "\n" + "\n".join(lines)
