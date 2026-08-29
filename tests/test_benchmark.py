"""Tests for the batch benchmark."""

from __future__ import annotations

from ai_werewolf.benchmark import run_arena


def test_arena_totals_add_up():
    report = run_arena(7, n_games=8, policy="random", base_seed=0)
    assert report.n_games == 8
    assert report.village_wins + report.werewolf_wins == 8
    assert abs(report.village_win_rate + report.werewolf_win_rate - 1.0) < 1e-9
    assert report.avg_days >= 1.0


def test_arena_reports_role_survival_and_agent_win_rate():
    report = run_arena(7, n_games=6, policy="random", base_seed=100)
    survival = report.role_survival()
    assert "werewolf" in survival
    assert "seer" in survival
    assert all(0.0 <= rate <= 1.0 for rate in survival.values())
    assert 0.0 <= report.agent_win_rate()["random"] <= 1.0


def test_arena_is_reproducible():
    a = run_arena(7, n_games=5, policy="random", base_seed=5)
    b = run_arena(7, n_games=5, policy="random", base_seed=5)
    assert (a.village_wins, a.werewolf_wins, a.total_days) == (
        b.village_wins,
        b.werewolf_wins,
        b.total_days,
    )


def test_arena_populates_ledger():
    report = run_arena(7, n_games=4, policy="random", base_seed=1)
    assert report.ledger.records
