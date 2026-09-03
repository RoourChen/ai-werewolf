"""An offline, deterministic provider for tests and CI.

:class:`MockProvider` never touches the network. It reads the structured
``Prompt.hint`` (role, pack, living others, whether the act is public, persona
dimensions) and answers with valid, consistent JSON. It is persona-aware:
suspicion is biased by the persona's trust baseline, and werewolf actors frame
a non-pack player on public acts — producing *real* deception records with a
≥0.20 public/private gap and a full deception plan.
"""

from __future__ import annotations

import json
import random

from ai_werewolf.ai.provider import ModelRunStats, Prompt, Provider

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
        self.stats = ModelRunStats(provider="mock", model="mock")
        self.last_diagnostic: dict = {}

    def complete(self, prompt: Prompt) -> str:
        hint = prompt.hint
        kind = hint.get("kind", "")
        lang = hint.get("lang", "zh")
        candidates = [int(c) for c in hint.get("candidates", [])]
        me_role = hint.get("me_role", "villager")
        pack = set(hint.get("pack", []))
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
            public_map = dict(private)  # non-wolves show their true belief
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
            payload["statement"] = self._statement(candidates, lang)
        elif kind == "last_words":
            payload["statement"] = "我的遗言。"
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

    def _statement(self, candidates: list[int], lang: str) -> str:
        pool = _STATEMENTS.get(lang, _STATEMENTS["zh"])
        if not candidates:
            return pool[0].replace("P{x}", "someone")
        return self.rng.choice(pool).format(x=self.rng.choice(candidates))
