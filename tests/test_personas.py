"""Tests for personas and their assignment."""

from __future__ import annotations

import random

from ai_werewolf.ai.personas import (
    JITTER,
    PERSONAS,
    assign_personas,
    perturb,
)
from ai_werewolf.domain.roles import Role

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


def test_personas_produce_distinct_prompts():
    import random

    from ai_werewolf.ai.persona import build_prompt
    from ai_werewolf.domain.actions import ActionKind
    from ai_werewolf.domain.state import (
        DecisionRequest,
        GamePhase,
        PlayerView,
        PublicSeat,
    )

    seats = tuple(PublicSeat(i, f"P{i}", True) for i in range(5))
    view = PlayerView(
        me=0, day=1, phase=GamePhase.VOTING, language="zh", my_role=Role.VILLAGER,
        seats=seats, living=(0, 1, 2, 3, 4), events=(), secrets=(),
        rng=random.Random(0),
    )
    request = DecisionRequest(ActionKind.VOTE, 0, legal_targets=(1, 2, 3, 4))
    systems = {p.id: build_prompt(view, request, p).system for p in PERSONAS.values()}
    assert len(set(systems.values())) == 6


def test_mock_suspicion_reflects_trust_baseline():
    import random

    from ai_werewolf.ai.mock import MockProvider
    from ai_werewolf.ai.persona import build_prompt
    from ai_werewolf.domain.actions import ActionKind
    from ai_werewolf.domain.state import (
        DecisionRequest,
        GamePhase,
        PlayerView,
        PublicSeat,
    )

    seats = tuple(PublicSeat(i, f"P{i}", True) for i in range(5))
    view = PlayerView(
        me=0, day=1, phase=GamePhase.VOTING, language="zh", my_role=Role.VILLAGER,
        seats=seats, living=(0, 1, 2, 3, 4), events=(), secrets=(),
        rng=random.Random(0),
    )
    request = DecisionRequest(ActionKind.VOTE, 0, legal_targets=(1, 2, 3, 4))

    def mean_suspicion(persona_id: str) -> float:
        import json

        prompt = build_prompt(view, request, PERSONAS[persona_id])
        data = json.loads(MockProvider(seed=0).complete(prompt))
        scores = data["private_suspicion"]
        return sum(scores.values()) / len(scores)

    skeptic = mean_suspicion("skeptic")   # trust 0.25 -> high suspicion
    nice = mean_suspicion("nice")         # trust 0.80 -> low suspicion
    assert skeptic > nice
