"""An offline, deterministic provider for tests and CI.

:class:`MockProvider` never touches the network. It reads the structured
``Prompt.hint`` field and answers with valid JSON for every decision kind, in
the game's language. With a fixed seed it is fully deterministic.
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
        candidates = [int(c) for c in hint.get("candidates", [])]
        lang = hint.get("lang", "zh")

        if kind == "statement":
            return json.dumps(
                {"statement": self._statement(candidates, lang)}, ensure_ascii=False
            )
        if kind == "witch":
            return json.dumps({"heal": False, "poison": None})
        if kind == "bid":
            return json.dumps({"priority": self.rng.randint(0, 10), "reason": ""})

        if candidates:
            choice = self.rng.choice(candidates)
            return json.dumps(
                {"choice": choice, "reasoning": "offline heuristic choice."}
            )
        return json.dumps({"statement": "..."})

    def _statement(self, candidates: list[int], lang: str) -> str:
        pool = _STATEMENTS.get(lang, _STATEMENTS["zh"])
        if not candidates:
            return pool[0].replace("P{x}", "someone")
        return self.rng.choice(pool).format(x=self.rng.choice(candidates))
