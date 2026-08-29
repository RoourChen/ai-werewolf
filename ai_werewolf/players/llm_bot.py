"""An LLM-driven player.

A thin, robust shell around a :class:`~ai_werewolf.ai.provider.Provider`:
build a prompt, call the model, parse the JSON decision. Malformed replies
degrade to a legal fallback so a model can play badly but never break a game.
"""

from __future__ import annotations

import json

from ai_werewolf.ai.persona import build_prompt
from ai_werewolf.ai.provider import Prompt, Provider
from ai_werewolf.domain.actions import TARGET_ACTIONS, Action, ActionKind
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.players.base import Player


class LLMBot(Player):
    """A player whose decisions come from a language model."""

    name = "llm"

    def __init__(self, player_id: int, provider: Provider) -> None:
        super().__init__(player_id)
        self.provider = provider
        self.last_reasoning: str = ""

    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        prompt = build_prompt(view, request)
        data = _parse_json(self._call(prompt))
        if data and isinstance(data.get("reasoning"), str):
            self.last_reasoning = data["reasoning"]
        return _to_action(request, data, view)

    def _call(self, prompt: Prompt) -> str:
        try:
            return self.provider.complete(prompt)
        except Exception:  # noqa: BLE001 - a provider error must not crash a game
            return ""


def _to_action(
    request: DecisionRequest, data: dict | None, view: PlayerView
) -> Action:
    if not data:
        return _fallback(request, view)
    if request.kind in TARGET_ACTIONS:
        choice = data.get("choice")
        if isinstance(choice, int) and choice in request.legal_targets:
            return Action(request.kind, request.actor, target=choice)
        return _fallback(request, view)
    if request.kind is ActionKind.WITCH_POTIONS:
        heal = bool(data.get("heal")) and request.can_heal
        poison = data.get("poison")
        poison_target = (
            poison
            if isinstance(poison, int) and request.can_poison and poison in request.legal_targets
            else None
        )
        return Action(ActionKind.WITCH_POTIONS, request.actor, heal=heal, poison=poison_target)
    if request.kind is ActionKind.STATEMENT:
        statement = data.get("statement")
        return Action(
            ActionKind.STATEMENT, request.actor, text=str(statement) if statement else "..."
        )
    if request.kind is ActionKind.BID:
        priority = data.get("priority")
        reason = data.get("reason")
        return Action(
            ActionKind.BID,
            request.actor,
            text=str(reason) if reason else "",
            priority=priority if isinstance(priority, int) else 5,
        )
    return Action(request.kind, request.actor)


def _fallback(request: DecisionRequest, view: PlayerView) -> Action:
    if request.kind in TARGET_ACTIONS and request.legal_targets:
        return Action(
            request.kind,
            request.actor,
            target=view.rng.choice(list(request.legal_targets)),
        )
    if request.kind is ActionKind.STATEMENT:
        return Action(ActionKind.STATEMENT, request.actor, text="...")
    if request.kind is ActionKind.BID:
        return Action(ActionKind.BID, request.actor, priority=5)
    return Action(request.kind, request.actor)


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
