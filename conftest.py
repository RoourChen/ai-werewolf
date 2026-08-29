"""Pytest configuration and shared helpers for ai-werewolf tests."""

from __future__ import annotations

import random

from ai_werewolf.domain.actions import Action
from ai_werewolf.domain.state import DecisionRequest, PlayerView
from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.transport.channel import Envelope


def random_decider(view: PlayerView, request: DecisionRequest) -> Action:
    """A decider that plays every seat as a fresh RandomBot."""
    return RandomBot(request.actor).decide(view, request)


class AutoChannel:
    """An in-memory channel that auto-answers decision requests legally.

    It replies to the most recent ``decision`` envelope with a valid action,
    which lets room/session tests run games that contain human seats without
    pre-scripting every turn.
    """

    def __init__(self, seed: int = 0) -> None:
        self.sent: list[Envelope] = []
        self.rng = random.Random(seed)

    def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    def recv(self, timeout: float | None = None) -> Envelope:
        for envelope in reversed(self.sent):
            if envelope.kind != "decision":
                continue
            request = envelope.payload["request"]
            kind = request["kind"]
            targets = request.get("legal_targets", [])
            action: dict = {"kind": kind, "actor": request["actor"]}
            if kind == "statement":
                action["text"] = "auto statement"
            elif kind == "bid":
                action["priority"] = 5
                action["reason"] = ""
            elif kind == "witch_potions":
                action["heal"] = False
                action["poison"] = targets[0] if targets and self.rng.random() < 0.5 else None
            else:
                action["target"] = targets[0] if targets else None
            return Envelope("action", payload={"action": action})
        raise TimeoutError("no pending decision to answer")
