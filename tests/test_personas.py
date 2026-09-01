"""Tests for personas and their assignment."""

from __future__ import annotations

import random

from ai_werewolf.ai.personas import (
    JITTER,
    PERSONAS,
    assign_personas,
    perturb,
)

_DIMENSIONS = (
    "trust_baseline",
    "evidence_sensitivity",
    "risk_preference",
    "lobby_strength",
    "vote_resistance",
    "deception_tendency",
)


def test_six_personas_are_distinct_on_every_dimension():
    assert len(PERSONAS) == 6
    for dim in _DIMENSIONS:
        values = [getattr(p, dim) for p in PERSONAS.values()]
        assert len(set(values)) == 6, f"{dim} is not distinctive"


def test_no_persona_is_incapable_of_lying():
    for persona in PERSONAS.values():
        assert persona.deception_tendency > 0


def test_perturb_is_reproducible_and_within_jitter():
    persona = PERSONAS["nice"]
    a = perturb(persona, random.Random(7))
    b = perturb(persona, random.Random(7))
    assert a == b
    assert abs(a.trust_baseline - persona.trust_baseline) <= JITTER + 1e-9
    assert 0.0 <= a.trust_baseline <= 1.0


def test_assign_personas_is_reproducible_and_covers_all_six():
    a = assign_personas([1, 2, 3, 4, 5, 6], seed=3)
    b = assign_personas([1, 2, 3, 4, 5, 6], seed=3)
    assert a == b
    assert len(set(a.values())) == 6  # every AI gets a different persona
