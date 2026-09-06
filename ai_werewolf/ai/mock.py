"""An offline, deterministic provider for tests and CI.

:class:`MockProvider` never touches the network. For statement decisions it
delegates to :func:`~ai_werewolf.ai.dialogue.compose_statement` so each persona
produces a distinct, situation-grounded line (no ``someone`` placeholder, no
shared fixed templates). For other decisions it keeps producing valid,
persona-aware suspicion maps and legal actions.
"""

from __future__ import annotations

import json
import random

from ai_werewolf.ai.dialogue import build_context, compose_statement
from ai_werewolf.ai.provider import ModelRunStats, Prompt, Provider


class MockProvider(Provider):
    """A deterministic, network-free stand-in for a real model."""

    name = "mock"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.stats = ModelRunStats(provider="mock", model="mock")
        self.last_diagnostic: dict = {}

    def complete(self, prompt: Prompt) -> str:
        hint = prompt.hint
        kind = hint.get("kind", "")
        me_role = hint.get("me_role", "villager")
        pack = set(hint.get("pack", []))
        candidates = [int(c) for c in hint.get("candidates", [])]
        others = [int(p) for p in hint.get("others", [])]
        public = bool(hint.get("public", False))
        trust = float(hint.get("trust_baseline", 0.5))
        suggestions = [int(s) for s in hint.get("suggestions", [])]

        if kind == "bid":
            return json.dumps({"priority": self.rng.randint(0, 10), "reason": ""})

        private: dict[int, float] = {}
        threat: dict[int, float] = {}
        for pid in others:
            if me_role == "werewolf":
                private[pid] = 1.0 if pid in pack else 0.0
            else:
                base = 1.0 - trust  # low trust -> high suspicion
                private[pid] = round(min(1.0, max(0.0, base + self.rng.uniform(-0.15, 0.15))), 4)
            threat[pid] = round(self.rng.random(), 4)

        payload: dict = {
            "reasoning": "offline heuristic decision.",
            "confidence": 0.7,
            "evidence": None,
            "private_suspicion": private,
            "strategic_threat": threat,
            "deception": {
                "active": False,
                "target": None,
                "public_statement": "",
                "purpose": "",
                "true_basis": "",
                "fabricated_event": None,
            },
        }
        if public:
            public_map = dict(private)
            if me_role == "werewolf":
                public_map = dict.fromkeys(others, 0.0)
                non_pack = [pid for pid in others if pid not in pack]
                if non_pack:
                    target = non_pack[0]
                    public_map[target] = 0.8
                    payload["deception"] = {
                        "active": True,
                        "target": target,
                        "public_statement": f"我强烈怀疑 P{target} 是狼",
                        "purpose": "转移火力，掩护狼队",
                        "true_basis": f"我知道 P{target} 不是狼，但认为他对狼队威胁很高",
                        "fabricated_event": None,
                    }
            payload["public_suspicion"] = public_map

        if kind == "statement":
            dialogue = compose_statement(build_context(hint), self.rng)
            payload.update(dialogue)
        elif kind == "last_words":
            payload["statement"] = self._last_words(hint)
        elif kind == "witch":
            payload["heal"] = False
            payload["poison"] = None
        elif kind == "pack_confirm":
            payload["choice"] = suggestions[0] if suggestions else (candidates[0] if candidates else 0)
        else:
            payload["choice"] = self.rng.choice(candidates) if candidates else 0

        reply = json.dumps(payload, ensure_ascii=False)
        self.last_diagnostic = {
            "finish_reason": "stop",
            "completion_tokens": 0,
            "max_tokens": 0,
            "content_len": len(reply),
        }
        return reply

    def _last_words(self, hint: dict) -> str:
        persona = hint.get("persona", "mediator")
        me_role = hint.get("me_role", "villager")
        if me_role == "werewolf":
            return "我的遗言：不管怎样，请继续找出狼人。"
        if persona == "aggressor":
            return "我的遗言：别犹豫，跟着票型投。"
        if persona == "chatterbox":
            return "我的遗言：有点不甘心，但就说到这吧，大家擦亮眼睛。"
        return "我的遗言：请根据票型继续找狼。"
