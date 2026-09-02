"""Structured decision traces.

A :class:`DecisionRecord` is an immutable, append-only record of one AI
decision. It captures the three suspicion channels (private true suspicion,
public suspicion, strategic threat), the delta against the previous private
suspicion, the key object of that change, an authorized evidence reference,
the candidate actions, the final decision with confidence and rationale, and
an optional deception plan.

All dict fields are stored as read-only ``MappingProxyType`` snapshots taken
at construction time, so a record can never be mutated after it is created —
neither through the field nor through ``to_dict()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

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
    private_suspicion: Mapping[int, float]
    public_suspicion: Mapping[int, float]
    strategic_threat: Mapping[int, float]
    delta: Mapping[int, float]
    key_player: int | None
    evidence: str
    candidates: tuple[int, ...]
    decision: str
    confidence: float
    rationale: str
    deception: bool
    deception_plan: Mapping[str, object] = field(default_factory=dict)
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "private_suspicion", MappingProxyType(dict(self.private_suspicion)))
        object.__setattr__(self, "public_suspicion", MappingProxyType(dict(self.public_suspicion)))
        object.__setattr__(self, "strategic_threat", MappingProxyType(dict(self.strategic_threat)))
        object.__setattr__(self, "delta", MappingProxyType(dict(self.delta)))
        object.__setattr__(self, "deception_plan", MappingProxyType(dict(self.deception_plan)))

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "actor": self.actor,
            "persona": self.persona,
            "role": self.role,
            "kind": self.kind,
            "private_suspicion": dict(self.private_suspicion),
            "public_suspicion": dict(self.public_suspicion),
            "strategic_threat": dict(self.strategic_threat),
            "delta": dict(self.delta),
            "key_player": self.key_player,
            "evidence": self.evidence,
            "candidates": list(self.candidates),
            "decision": self.decision,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "deception": self.deception,
            "deception_plan": dict(self.deception_plan),
            "fallback_reason": self.fallback_reason,
        }


def parse_scores(raw: object, others: list[int]) -> dict[int, float] | None:
    """Strictly parse a suspicion map.

    Returns a dict keyed by exactly ``others`` with numeric values in [0,1],
    or ``None`` if any key is missing/extra/duplicated or any value is
    missing, non-numeric or out of range. JSON string keys are accepted.
    """
    if not isinstance(raw, dict):
        return None
    expected = set(others)
    seen: set[int] = set()
    out: dict[int, float] = {}
    for key, value in raw.items():
        try:
            pid = int(key)
        except (TypeError, ValueError):
            return None
        if pid not in expected or pid in seen:
            return None
        seen.add(pid)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not 0.0 <= number <= 1.0:
            return None
        out[pid] = number
    if seen != expected:
        return None
    return out


def parse_number(value: object) -> float | None:
    """Parse a 0..1 numeric field (e.g. confidence); ``None`` if invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if 0.0 <= number <= 1.0 else None


def clamp_score(value: object) -> float:
    """Clamp any value to a 0..1 suspicion score; non-numeric → default."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_SUSPICION
    return min(1.0, max(0.0, number))


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
