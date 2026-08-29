"""Tests for the arena leaderboard."""

from __future__ import annotations

import pytest

from ai_werewolf.agents.llm_agent import LLMAgent
from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.arena.leaderboard import Leaderboard, LeaderboardEntry
from ai_werewolf.llm.mock import MockProvider


def _random(player_id: int) -> RandomAgent:
    return RandomAgent(player_id)


def test_leaderboard_ranks_every_competitor():
    mock = MockProvider(seed=0)
    competitors = {"random": _random, "mock-llm": lambda pid: LLMAgent(pid, mock)}
    report = Leaderboard(7, competitors, _random, n_games=6, base_seed=0).run()

    assert len(report.entries) == 2
    scores = [e.score for e in report.entries]
    assert scores == sorted(scores, reverse=True)  # best first
    for e in report.entries:
        assert 0.0 <= e.werewolf_win_rate <= 1.0
        assert 0.0 <= e.village_win_rate <= 1.0
        assert 0.0 <= e.score <= 1.0


def test_leaderboard_markdown_is_a_table():
    report = Leaderboard(7, {"random": _random}, _random, n_games=4).run()
    md = report.to_markdown()
    assert md.startswith("| Rank |")
    assert "random" in md
    assert md.count("\n") >= 2  # header, separator, at least one row


def test_leaderboard_is_reproducible():
    def run():
        return Leaderboard(7, {"random": _random}, _random, n_games=5, base_seed=3).run()

    a, b = run(), run()
    assert a.entries[0].werewolf_wins == b.entries[0].werewolf_wins
    assert a.entries[0].village_wins == b.entries[0].village_wins


def test_leaderboard_rejects_an_empty_field():
    with pytest.raises(ValueError):
        Leaderboard(7, {}, _random)


def test_entry_score_is_the_mean_of_both_win_rates():
    e = LeaderboardEntry("x", games_per_side=10, werewolf_wins=6, village_wins=4)
    assert e.werewolf_win_rate == 0.6
    assert e.village_win_rate == 0.4
    assert e.score == 0.5


def test_progress_hook_fires_once_per_competitor():
    seen: list[tuple[int, int]] = []
    Leaderboard(6, {"a": _random, "b": _random}, _random, n_games=3).run(
        progress=lambda d, t: seen.append((d, t))
    )
    assert seen == [(1, 2), (2, 2)]
