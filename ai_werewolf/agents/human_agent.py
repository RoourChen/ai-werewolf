"""A seat driven by a human at the keyboard, backed by the copilot.

The human agent never touches the terminal directly: it talks to a minimal
:class:`HumanUI` interface (``rule``/``print``/``input``), so the game layer
stays free of any console I/O and the same agent can be driven by a TUI, a web
socket or a scripted test harness. The :class:`~ai_werewolf.cli` module passes
its console in as the UI.
"""

from __future__ import annotations

from typing import Protocol

from ai_werewolf.agents.base import Agent
from ai_werewolf.copilot.advisor import Advice, advise
from ai_werewolf.game.roles import Role
from ai_werewolf.game.state import PlayerView
from ai_werewolf.i18n import pick
from ai_werewolf.llm.provider import LLMProvider


class HumanUI(Protocol):
    """The narrow UI surface a :class:`HumanAgent` needs.

    ``rich.Console`` and the CLI's plain fallback both satisfy it, as does any
    scripted test double.
    """

    def rule(self, title: str = "") -> None: ...
    def print(self, text: str = "") -> None: ...
    def input(self, prompt: str = "") -> str: ...


def render_advice(advice: Advice) -> str:
    """Render a copilot :class:`Advice` as plain, markup-free text."""
    lines = ["copilot — werewolf suspicion:"]
    for s in advice.suspicions:
        lines.append(
            f"  P{s.player_id} {s.name}: {s.percent:3d}% — {'; '.join(s.reasons)}"
        )
    lines.append(f"  recommendation: {advice.rationale}")
    if advice.llm_note:
        lines.append(f"  llm note: {advice.llm_note}")
    return "\n".join(lines)


class HumanAgent(Agent):
    """A person at one seat, with the copilot offering live advice."""

    name = "human"

    def __init__(
        self, player_id: int, ui: HumanUI, copilot: LLMProvider | None = None
    ) -> None:
        super().__init__(player_id)
        self.ui = ui
        self.copilot = copilot

    def night_action(self, view: PlayerView) -> int:
        prompt, candidates = _night_prompt(view)
        self._banner(view, "NIGHT")
        return self._ask(view, candidates, prompt)

    def speak(self, view: PlayerView) -> str:
        self._banner(view, "DISCUSSION")
        self.ui.print(render_advice(advise(view, self.copilot)))
        text = self.ui.input(
            pick(view.lang, "Your statement> ", "你的发言> ")
        ).strip()
        return text or pick(view.lang, "(I have nothing to say.)", "（我没有什么要说的。）")

    def vote(self, view: PlayerView) -> int:
        self._banner(view, "VOTE")
        self.ui.print(render_advice(advise(view, self.copilot)))
        return self._ask(
            view,
            view.others_alive(),
            pick(view.lang, "Who do you vote to lynch?", "你要投票放逐谁？"),
        )

    def dying_shot(self, view: PlayerView) -> int:
        self._banner(view, "DYING SHOT")
        self.ui.print(render_advice(advise(view, self.copilot)))
        pool = view.others_alive() or list(view.living_ids)
        return self._ask(
            view,
            pool,
            pick(view.lang, "You are the dying Hunter — who do you shoot?", "你是将死的猎人——你要开枪带走谁？"),
        )

    def witch_turn(
        self, view: PlayerView, victim: int | None, can_heal: bool, can_poison: bool
    ) -> tuple[bool, int | None]:
        self._banner(view, "WITCH")
        if victim is not None:
            self.ui.print(
                pick(
                    view.lang,
                    f"  The werewolves attacked {view.name(victim)} (P{victim}).",
                    f"  狼人袭击了 {view.name(victim)}（P{victim}）。",
                )
            )
        else:
            self.ui.print(
                pick(
                    view.lang,
                    "  You sense no werewolf attack you could counter.",
                    "  你没有察觉可应对的狼人袭击。",
                )
            )
        heal = False
        if can_heal and victim is not None:
            answer = self.ui.input(
                pick(
                    view.lang,
                    f"  Use your HEALING potion on P{victim}? [y/N] ",
                    f"  对 P{victim} 使用解药？[y/N] ",
                )
            )
            heal = answer.strip().lower().startswith("y")
        poison: int | None = None
        if can_poison:
            answer = self.ui.input(
                pick(
                    view.lang,
                    "  POISON potion — enter a player id to kill, or blank to skip: ",
                    "  毒药——输入要毒杀的玩家编号，留空跳过：",
                )
            )
            raw = answer.strip().lstrip("Pp")
            if raw.isdigit() and int(raw) in view.others_alive():
                poison = int(raw)
        return (heal, poison)

    def bid(self, view: PlayerView) -> tuple[int, str]:
        self._banner(view, "BID")
        raw = self.ui.input(
            pick(view.lang, "  Bid for the floor [0-10]: ", "  为发言权竞价 [0-10]：")
        ).strip()
        priority = int(raw) if raw.isdigit() else 5
        reason = self.ui.input(
            pick(view.lang, "  reason (optional)> ", "  理由（可选）> ")
        ).strip()
        return (max(0, min(10, priority)), reason)

    def _banner(self, view: PlayerView, phase: str) -> None:
        self.ui.rule(f"You are {view.me_name} (P{view.me_id}) — {view.me_role.value} — {phase}")
        for note in view.private_notes:
            self.ui.print(f"  • {note}")

    def _ask(self, view: PlayerView, candidates: list[int], prompt: str) -> int:
        options = ", ".join(f"P{c}={view.name(c)}" for c in candidates)
        self.ui.print(prompt)
        self.ui.print(f"  choices: {options}")
        while True:
            raw = self.ui.input("> ").strip().lstrip("Pp")
            if raw.isdigit() and int(raw) in candidates:
                return int(raw)
            self.ui.print(
                pick(
                    view.lang,
                    "  invalid — enter one of the listed player ids.",
                    "  无效——请输入上述玩家编号之一。",
                )
            )


def _night_prompt(view: PlayerView) -> tuple[str, list[int]]:
    if view.me_role is Role.WEREWOLF:
        return (
            pick(view.lang, "Choose a player for the pack to eliminate.", "选择一名玩家供狼队猎杀。"),
            view.others_alive(),
        )
    if view.me_role is Role.SEER:
        return (
            pick(view.lang, "Choose a player to inspect.", "选择一名玩家查验。"),
            view.others_alive(),
        )
    if view.me_role is Role.DOCTOR:
        return (
            pick(view.lang, "Choose a player to protect (you may pick yourself).", "选择一名玩家守护（可以选自己）。"),
            list(view.living_ids),
        )
    return (
        pick(view.lang, "You have no night action.", "你没有夜间行动。"),
        list(view.living_ids),
    )
