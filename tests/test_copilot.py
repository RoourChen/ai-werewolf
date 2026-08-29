"""Tests for the human copilot's belief model."""

from __future__ import annotations

import random

from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.copilot.advisor import advise
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.events import Event, EventType
from ai_werewolf.game.roles import Role
from ai_werewolf.game.state import GameConfig, Phase, PlayerInfo, PlayerView, build_view


def _seer_view() -> PlayerView:
    """A 4-player view where the seer (P0) has caught P1 as a werewolf."""
    players = tuple(PlayerInfo(i, f"P{i}", True) for i in range(4))
    events = (
        Event(
            EventType.GAME_START, 0, "setup", "game start",
            data={"role_counts": {"werewolf": 1, "seer": 1, "villager": 2}},
        ),
        Event(
            EventType.SEER_RESULT, 1, "night", "P1 is a werewolf",
            target=1, public=False, visible_to=frozenset({0}),
            data={"is_wolf": True},
        ),
    )
    return PlayerView(
        day=2, phase=Phase.DAY_VOTE, me_id=0, me_name="P0", me_role=Role.SEER,
        players=players, living_ids=(0, 1, 2, 3), events=events,
        private_notes=(), lang="en", rng=random.Random(0),
    )


def test_confirmed_werewolf_scores_certain():
    advice = advise(_seer_view())
    by_id = {s.player_id: s for s in advice.suspicions}
    assert by_id[1].score == 1.0
    assert "confirmed werewolf" in by_id[1].reasons
    # with the only wolf located, everyone else is cleared
    assert by_id[2].score == 0.0
    assert by_id[3].score == 0.0


def test_recommended_vote_targets_the_known_wolf():
    advice = advise(_seer_view())
    assert advice.recommended_vote == 1
    assert "confirmed werewolf" in advice.rationale


def test_advice_on_a_real_game_is_well_formed():
    config = GameConfig.standard(7, seed=11)
    engine = GameEngine(config, lambda pid, _: RandomAgent(pid))
    engine.run()
    view = build_view(engine.state, player_id=0)
    advice = advise(view)
    living_others = [pid for pid in view.living_ids if pid != 0]
    assert len(advice.suspicions) == len(living_others)
    for s in advice.suspicions:
        assert 0.0 <= s.score <= 1.0
        assert s.reasons
    if advice.recommended_vote is not None:
        assert advice.recommended_vote in living_others


def test_suspicions_are_ranked_most_suspicious_first():
    advice = advise(_seer_view())
    scores = [s.score for s in advice.suspicions]
    assert scores == sorted(scores, reverse=True)
