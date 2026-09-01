"""Structured decision traces.

A :class:`DecisionRecord` is an immutable, append-only record of one AI
decision. It captures the three suspicion channels (private true suspicion,
public suspicion, strategic threat), the delta against the previous private
suspicion, the key object of that change, the authorized evidence, the
candidate actions, the final decision with confidence and rationale, and an
optional deception plan.

Records are produced at decision time by the player and appended by the
orchestration layer; they must never be regenerated or rewritten at game end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SUSPICION = 0.5
DECEPTION_THRESHOLD = 0.20


@dataclass(frozen=True)
class DecisionRecord:
    day: int
    phase: str
    actor: int
    persona: str
    role: str
    kind: str
    private_suspicion: dict[int, float]
    public_suspicion: dict[int, float]
    strategic_threat: dict[int, float]
    delta: dict[int, float]
    key_player: int | None
    evidence: str
    candidates: tuple[int, ...]
    decision: str
    confidence: float
    rationale: str
    deception: bool
    deception_plan: dict = field(default_factory=dict)
    fallback_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "actor": self.actor,
            "persona": self.persona,
            "role": self.role,
            "kind": self.kind,
            "private_suspicion": self.private_suspicion,
            "public_suspicion": self.public_suspicion,
            "strategic_threat": self.strategic_threat,
            "delta": self.delta,
            "key_player": self.key_player,
            "evidence": self.evidence,
            "candidates": list(self.candidates),
            "decision": self.decision,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "deception": self.deception,
            "deception_plan": self.deception_plan,
            "fallback_reason": self.fallback_reason,
        }


def clamp_score(value: object) -> float:
    """Clamp any value to a 0..1 suspicion score; non-numeric → default."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SUSPICION
    return min(1.0, max(0.0, number))


def normalize_scores(raw: object, others: list[int]) -> dict[int, float]:
    """Extract per-player scores for ``others``, defaulting missing ones.

    Accepts both int and string keys, since JSON round-trips coerce dict keys
    to strings.
    """
    source = raw if isinstance(raw, dict) else {}
    out: dict[int, float] = {}
    for pid in others:
        value = source.get(pid, source.get(str(pid), DEFAULT_SUSPICION))
        out[pid] = clamp_score(value)
    return out


def compute_delta(
    previous: dict[int, float], current: dict[int, float], others: list[int]
) -> dict[int, float]:
    return {
        pid: round(current.get(pid, DEFAULT_SUSPICION) - previous.get(pid, DEFAULT_SUSPICION), 4)
        for pid in others
    }


def key_player(delta: dict[int, float]) -> int | None:
    if not delta:
        return None
    return max(delta, key=lambda pid: abs(delta[pid]))


def to_dicts(records: list[DecisionRecord]) -> list[dict]:
    return [r.to_dict() for r in records]
