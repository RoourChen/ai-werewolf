"""Tests for the human copilot."""

from __future__ import annotations

import random

from ai_werewolf.copilot.advisor import advise
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import Role, build_roster
from ai_werewolf.domain.state import (
    GameConfig,
    GamePhase,
    PlayerView,
    PublicSeat,
    build_view,
)
from conftest import random_decider


def _seer_view() -> PlayerView:
    seats = tuple(PublicSeat(i, f"P{i}", True) for i in range(4))
    events = (
        GameEvent(
            EventKind.GAME_STARTED, 0, "setup", "start",
            data={"role_counts": {"werewolf": 1, "seer": 1, "villager": 2}},
        ),
        GameEvent(
            EventKind.SEER_RESULT, 1, "night", "P1 是狼人。",
            target=1, data={"is_wolf": True}, audience=frozenset({0}),
        ),
    )
    return PlayerView(
        me=0, day=2, phase=GamePhase.VOTING, language="zh", my_role=Role.SEER,
        seats=seats, living=(0, 1, 2, 3), events=events, secrets=(),
        rng=random.Random(0),
    )


def test_confirmed_werewolf_scores_certain():
    advice = advise(_seer_view())
    by_id = {s.player_id: s for s in advice.suspicions}
    assert by_id[1].probability == 1.0
    assert "已确认是狼人" in by_id[1].reasons
    assert by_id[2].probability == 0.0
    assert by_id[3].probability == 0.0


def test_recommendation_targets_the_known_wolf():
    advice = advise(_seer_view())
    assert advice.recommended_vote == 1
    assert "确认是狼人" in advice.rationale


def test_advice_on_a_real_game_is_well_formed():
    config = GameConfig(roster=build_roster(7), seed=11)
    state = Referee(config, random_decider).run()
    view = build_view(state, 0)
    advice = advise(view)
    others = view.living_others()
    assert len(advice.suspicions) == len(others)
    for s in advice.suspicions:
        assert 0.0 <= s.probability <= 1.0
        assert s.reasons
    if advice.recommended_vote is not None:
        assert advice.recommended_vote in others


def test_suspicions_are_sorted_most_suspicious_first():
    advice = advise(_seer_view())
    scores = [s.probability for s in advice.suspicions]
    assert scores == sorted(scores, reverse=True)
