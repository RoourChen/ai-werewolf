"""An offline provider for tests, CI and zero-setup demos.

:class:`MockProvider` never touches the network. It reads the machine-readable
``[[ACTION ...]]`` trailer that :mod:`ai_werewolf.prompts.templates` appends to
every request and answers with a valid, well-formed JSON decision — in the
game's language. With a fixed seed it is fully deterministic, so a whole
self-play game is reproducible.
"""

from __future__ import annotations

import json
import random
import re

from ai_werewolf.llm.provider import LLMProvider

_ACTION_RE = re.compile(
    r"\[\[ACTION kind=(\w+) candidates=([\d,]*) lang=(\w+)\]\]"
)

_STATEMENTS = {
    "en": [
        "P{x} has been dodging the hard questions — that reads wolfy to me.",
        "Something about P{x}'s vote yesterday doesn't add up.",
        "I'd rather hear P{x} explain themselves before I commit my vote.",
        "P{x} is steering us a little too eagerly. I'm watching them.",
        "I think P{x} is village, honestly. Let's not waste the day on them.",
    ],
    "zh": [
        "P{x} 一直在回避关键问题——这点让我觉得他很有狼味。",
        "P{x} 昨天那一票怎么想都说不通。",
        "在我决定投票之前，我想先听 P{x} 把话说清楚。",
        "P{x} 带节奏带得有点太急了，我盯着他。",
        "老实说我觉得 P{x} 是好人，别在他身上浪费白天。",
    ],
}


class MockProvider(LLMProvider):
    """A deterministic, network-free stand-in for a real LLM."""

    name = "mock"

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def complete(self, messages: list[dict[str, str]]) -> str:
        user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        match = _ACTION_RE.search(user)
        if match is None:
            return json.dumps({"statement": "..."})

        kind, raw_candidates, lang = match.groups()
        candidates = [int(x) for x in raw_candidates.split(",") if x]
        if kind == "speak":
            return json.dumps(
                {"statement": self._statement(candidates, lang)}, ensure_ascii=False
            )
        if kind == "witch":
            # The offline witch plays conservatively: it banks both potions.
            return json.dumps({"heal": False, "poison": None})
        if kind == "bid":
            return json.dumps({"priority": self.rng.randint(0, 10), "reason": ""})

        choice = self.rng.choice(candidates) if candidates else 0
        return json.dumps({"choice": choice, "reasoning": "mock heuristic pick."})

    def _statement(self, candidates: list[int], lang: str) -> str:
        pool = _STATEMENTS.get(lang, _STATEMENTS["en"])
        if not candidates:
            return pool[0].replace("P{x}", "someone")
        return self.rng.choice(pool).format(x=self.rng.choice(candidates))
