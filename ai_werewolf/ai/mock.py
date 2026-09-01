"""An offline, deterministic provider for tests and CI.

:class:`MockProvider` never touches the network. It reads the structured
``Prompt.hint`` (actor role, pack, living others, whether the act is public)
and answers with valid, *consistent* JSON for every decision kind. Werewolf
actors report known-fact suspicion (1 for packmates, 0 for others); everyone
else reports a deterministic per-player belief. Public suspicion mirrors
private suspicion, so the offline path never trips the deception retry.
"""

from __future__ import annotations

import json
import random

from ai_werewolf.ai.provider import Prompt, Provider

_STATEMENTS: dict[str, list[str]] = {
    "zh": [
        "P{x} 一直在回避问题，我觉得他很有狼味。",
        "P{x} 上一轮的票怎么想都说不通。",
        "我想先听 P{x} 把话说明白，再决定投谁。",
        "P{x} 带节奏太急了，我会盯着他。",
        "我觉得 P{x} 更像好人，先不投他。",
    ],
    "en": [
        "P{x} has been dodging questions — that reads wolfy.",
        "P{x}'s last vote does not add up.",
        "I want to hear P{x} explain before I commit my vote.",
        "P{x} is steering too eagerly; I am watching them.",
        "P{x} feels like a villager; let's not vote them today.",
    ],
}


class MockProvider(Provider):
    """A deterministic, network-free stand-in for a real model."""

    name = "mock"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def complete(self, prompt: Prompt) -> str:
        hint = prompt.hint
        kind = hint.get("kind", "")
        lang = hint.get("lang", "zh")
        candidates = [int(c) for c in hint.get("candidates", [])]
        me_role = hint.get("me_role", "villager")
        pack = set(hint.get("pack", []))
        others = [int(p) for p in hint.get("others", [])]
        public = bool(hint.get("public", False))

        if kind == "bid":
            return json.dumps({"priority": self.rng.randint(0, 10), "reason": ""})

        private: dict[int, float] = {}
        threat: dict[int, float] = {}
        for pid in others:
            if me_role == "werewolf":
                private[pid] = 1.0 if pid in pack else 0.0
            else:
                private[pid] = round(self.rng.random(), 4)
            threat[pid] = round(self.rng.random(), 4)

        payload: dict = {
            "reasoning": "offline heuristic decision.",
            "confidence": 0.7,
            "evidence": "none",
            "private_suspicion": private,
            "strategic_threat": threat,
            "deception": {
                "active": False,
                "target": None,
                "public_statement": "",
                "purpose": "",
                "true_basis": "",
            },
        }
        if public:
            payload["public_suspicion"] = dict(private)

        if kind == "statement":
            payload["statement"] = self._statement(candidates, lang)
        elif kind == "witch":
            payload["heal"] = False
            payload["poison"] = None
        else:
            payload["choice"] = self.rng.choice(candidates) if candidates else 0
        return json.dumps(payload, ensure_ascii=False)

    def _statement(self, candidates: list[int], lang: str) -> str:
        pool = _STATEMENTS.get(lang, _STATEMENTS["zh"])
        if not candidates:
            return pool[0].replace("P{x}", "someone")
        return self.rng.choice(pool).format(x=self.rng.choice(candidates))
