"""A human at a seat, connected through a :class:`Channel`.

The human player never touches the terminal directly: it renders a readable
prompt, sends it down the channel, and awaits an action envelope. A terminal
client, a web client or a scripted test double can all drive it identically.
"""

from __future__ import annotations

from ai_werewolf.copilot.advisor import advise
from ai_werewolf.domain.actions import Action, ActionKind
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.players.base import Player
from ai_werewolf.transport.channel import Channel, Envelope


class HumanPlayer(Player):
    """A seat controlled by a person over a channel."""

    name = "human"

    def __init__(self, player_id: int, channel: Channel) -> None:
        super().__init__(player_id)
        self.channel = channel

    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        self.channel.send(Envelope(
            kind="decision",
            sender=self.player_id,
            payload={
                "prompt": render_human_prompt(view, request),
                "advice": advise(view).render(),
                "request": _request_payload(request),
            },
        ))
        reply = self.channel.recv(
            timeout=30.0 if request.kind is ActionKind.LAST_WORDS else None
        )
        return _action_from_payload(reply.payload, request)


def render_human_prompt(view: PlayerView, request: DecisionRequest) -> str:
    lines = [
        f"你是 {view.name(view.me)}（P{view.me}）——身份 {view.my_role.value}——阶段 {view.phase.value}",
    ]
    lines.extend(f"  • {s}" for s in view.secrets)
    lines.append("")
    lines.append("座位：")
    for s in view.seats:
        state = "存活" if s.alive else "已死亡"
        mark = "  ← 你" if s.id == view.me else ""
        lines.append(f"  P{s.id} {s.name}: {state}{mark}")
    if request.legal_targets:
        named = ", ".join(f"P{c}={view.name(c)}" for c in request.legal_targets)
        lines.append(f"合法目标：{named}")
    if request.suggestions:
        named = ", ".join(f"P{c}" for c in request.suggestions)
        lines.append(f"狼队友建议：{named}")
    if request.kind is ActionKind.WITCH_POTIONS:
        lines.append("可用药水：")
        if request.can_heal:
            lines.append("  - 解药")
        if request.can_poison:
            lines.append("  - 毒药")
    lines.append("")
    lines.append(_ACTION_HINT.get(request.kind.value, "请做出选择。"))
    return "\n".join(lines)


_ACTION_HINT = {
    "night_kill": "选择猎杀目标。",
    "pack_confirm": "确认猎杀目标。",
    "night_inspect": "选择查验目标。",
    "witch_potions": "决定是否使用解药/毒药。",
    "vote": "选择放逐目标。",
    "statement": "输入你的发言。",
    "last_words": "说一句遗言。",
    "bid": "输入竞价（0-10）。",
}


def _request_payload(request: DecisionRequest) -> dict:
    return {
        "kind": request.kind.value,
        "actor": request.actor,
        "legal_targets": list(request.legal_targets),
        "can_heal": request.can_heal,
        "can_poison": request.can_poison,
        "suggestions": list(request.suggestions),
    }


def _action_from_payload(payload: dict, request: DecisionRequest) -> Action:
    action = payload.get("action", {}) if isinstance(payload, dict) else {}
    target = action.get("target")
    poison = action.get("poison")
    priority = action.get("priority", 5)
    return Action(
        request.kind,
        request.actor,
        target=target if isinstance(target, int) else None,
        text=str(action.get("text", "")),
        heal=bool(action.get("heal")),
        poison=poison if isinstance(poison, int) else None,
        priority=priority if isinstance(priority, int) else 5,
    )
