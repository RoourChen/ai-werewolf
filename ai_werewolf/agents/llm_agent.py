"""An LLM-driven werewolf player.

The agent is a thin, robust shell around a provider: build a prompt, call the
model, parse the JSON decision, and *validate it hard*. Anything malformed —
empty reply, prose instead of JSON, an illegal target — degrades gracefully to
a random legal choice. A model can play badly here, but it can never break a
game.
"""

from __future__ import annotations

import json

from ai_werewolf.agents.base import Agent
from ai_werewolf.game.roles import Role
from ai_werewolf.game.state import PlayerView
from ai_werewolf.llm.provider import LLMProvider
from ai_werewolf.prompts import templates as T

_NIGHT_KIND = {
    Role.WEREWOLF: T.KIND_KILL,
    Role.SEER: T.KIND_INSPECT,
    Role.DOCTOR: T.KIND_PROTECT,
}


class LLMAgent(Agent):
    """A player whose every decision comes from a language model."""

    name = "llm"

    def __init__(self, player_id: int, provider: LLMProvider) -> None:
        super().__init__(player_id)
        self.provider = provider
        #: (day, kind, choice, reasoning) — useful for transcripts and review
        self.reasoning_log: list[tuple[int, str, int, str]] = []

    def last_reasoning(self) -> str | None:
        if not self.reasoning_log:
            return None
        reasoning = self.reasoning_log[-1][3].strip()
        return reasoning or None

    def night_action(self, view: PlayerView) -> int:
        kind = _NIGHT_KIND[view.me_role]
        candidates = (
            list(view.living_ids)  # the doctor may guard themselves
            if kind == T.KIND_PROTECT
            else view.others_alive()
        )
        return self._decide(view, kind, candidates or list(view.living_ids))

    def vote(self, view: PlayerView) -> int:
        candidates = view.others_alive() or list(view.living_ids)
        return self._decide(view, T.KIND_VOTE, candidates)

    def speak(self, view: PlayerView) -> str:
        candidates = view.others_alive() or list(view.living_ids)
        messages = self._messages(view, T.KIND_SPEAK, candidates)
        data = _parse_json(self._call(messages))
        if data and isinstance(data.get("statement"), str):
            return data["statement"].strip() or "I'll stay quiet this round."
        return "I'll stay quiet this round."

    def dying_shot(self, view: PlayerView) -> int:
        candidates = view.others_alive() or list(view.living_ids)
        return self._decide(view, T.KIND_SHOOT, candidates)

    def bid(self, view: PlayerView) -> tuple[int, str]:
        messages = [
            {"role": "system", "content": T.system_message(view)},
            {"role": "user", "content": T.bid_request(view)},
        ]
        data = _parse_json(self._call(messages))
        if not data:
            return (5, "")
        priority = data.get("priority")
        reason = str(data.get("reason", "")) if data.get("reason") else ""
        return (priority if isinstance(priority, int) else 5, reason)

    def witch_turn(
        self, view: PlayerView, victim: int | None, can_heal: bool, can_poison: bool
    ) -> tuple[bool, int | None]:
        messages = [
            {"role": "system", "content": T.system_message(view)},
            {"role": "user", "content": T.witch_request(view, victim, can_heal, can_poison)},
        ]
        data = _parse_json(self._call(messages))
        if not data:
            return (False, None)
        heal = bool(data.get("heal")) and can_heal
        poison = data.get("poison")
        poison_target = poison if (isinstance(poison, int) and can_poison) else None
        return (heal, poison_target)

    # ------------------------------------------------------------- internals
    def _decide(self, view: PlayerView, kind: str, candidates: list[int]) -> int:
        messages = self._messages(view, kind, candidates)
        data = _parse_json(self._call(messages))
        choice = data.get("choice") if data else None
        reasoning = str(data.get("reasoning", "")) if data else ""
        if not isinstance(choice, int) or choice not in candidates:
            choice = view.rng.choice(candidates)
            reasoning = "(fallback: model reply was missing or illegal)"
        self.reasoning_log.append((view.day, kind, choice, reasoning))
        return choice

    def _messages(
        self, view: PlayerView, kind: str, candidates: list[int]
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": T.system_message(view)},
            {"role": "user", "content": T.decision_request(view, kind, candidates)},
        ]

    def _call(self, messages: list[dict[str, str]]) -> str:
        try:
            return self.provider.complete(messages)
        except Exception:  # noqa: BLE001 - a provider error must not crash a game
            return ""


def _parse_json(raw: str) -> dict | None:
    """Extract the first balanced JSON object from a model reply."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    result = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return result if isinstance(result, dict) else None
    return None
