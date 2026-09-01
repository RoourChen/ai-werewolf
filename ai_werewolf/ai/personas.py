"""Personas for the six AI seats.

A :class:`Persona` fixes six behavioural dimensions plus a speech style. The
dimensions are *tendencies*, not hard-coded decision probabilities; they steer
the prompt and are recorded in decision traces. Personas are role-agnostic:
the same persona may be dealt a werewolf or a villager.

Each game applies a deterministic ±0.03 jitter per dimension (reproducible for
the same seed) so two games with the same persona still differ slightly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

JITTER = 0.03


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    speech_style: str
    trust_baseline: float       # 0 = suspicious, 1 = trusting
    evidence_sensitivity: float  # 0 = ignores evidence, 1 = weighs evidence
    risk_preference: float       # 0 = cautious, 1 = aggressive
    lobby_strength: float        # 0 = never lobbies, 1 = strong lobbying
    vote_resistance: float       # 0 = easily swayed, 1 = rarely changes vote
    deception_tendency: float    # 0 = rarely deceives, 1 = often deceives


PERSONAS: dict[str, Persona] = {
    "skeptic": Persona(
        "skeptic", "质疑者",
        "主动找矛盾、频繁追问，不轻信身份声明",
        0.25, 0.75, 0.55, 0.65, 0.60, 0.45,
    ),
    "nice": Persona(
        "nice", "老好人",
        "偏信任、语气友善，不轻易强推别人",
        0.80, 0.45, 0.25, 0.25, 0.30, 0.20,
    ),
    "analyst": Persona(
        "analyst", "分析家",
        "重票型和前后逻辑，发言结构化、情绪较弱",
        0.45, 0.90, 0.30, 0.45, 0.75, 0.30,
    ),
    "aggressor": Persona(
        "aggressor", "激进派",
        "结论明确、强势拉票、容忍较高决策风险",
        0.30, 0.55, 0.90, 0.90, 0.70, 0.55,
    ),
    "mediator": Persona(
        "mediator", "和事佬",
        "关注阵营共识、缓和冲突，但关键时刻会归票",
        0.70, 0.60, 0.20, 0.20, 0.35, 0.25,
    ),
    "chatterbox": Persona(
        "chatterbox", "话痨",
        "表达丰富、情绪化、容易制造噪声和戏剧效果",
        0.50, 0.40, 0.65, 0.60, 0.40, 0.65,
    ),
}

#: Fallback for non-MVP paths (e.g. all-bot simulation) where no persona is set.
NEUTRAL = Persona(
    "neutral", "中性",
    "平实、中立、随大流",
    0.50, 0.50, 0.50, 0.50, 0.50, 0.50,
)


def perturb(persona: Persona, rng: random.Random) -> Persona:
    """Apply a deterministic ±0.03 jitter to every dimension, clamped to [0,1]."""
    def jitter(value: float) -> float:
        return round(min(1.0, max(0.0, value + rng.uniform(-JITTER, JITTER))), 4)

    return replace(
        persona,
        trust_baseline=jitter(persona.trust_baseline),
        evidence_sensitivity=jitter(persona.evidence_sensitivity),
        risk_preference=jitter(persona.risk_preference),
        lobby_strength=jitter(persona.lobby_strength),
        vote_resistance=jitter(persona.vote_resistance),
        deception_tendency=jitter(persona.deception_tendency),
    )


def assign_personas(ai_seats: list[int], seed: int | None) -> dict[int, Persona]:
    """Independently shuffle and assign a persona to each AI seat.

    Uses its own ``random.Random(seed)`` instance, independent of the referee's
    role-shuffling RNG, so persona and role assignments are unrelated yet both
    reproducible for the same seed.
    """
    rng = random.Random(seed)
    pool = [perturb(p, rng) for p in PERSONAS.values()]
    rng.shuffle(pool)
    return {seat: pool[i % len(pool)] for i, seat in enumerate(sorted(ai_seats))}
