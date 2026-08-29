"""Tests for the self-play arena."""

from __future__ import annotations

from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.arena.runner import Arena


def test_arena_runs_every_game_and_totals_add_up():
    arena = Arena(7, lambda pid, _: RandomAgent(pid), n_games=12, base_seed=0)
    report = arena.run()
    assert report.n_games == 12
    assert report.village_wins + report.werewolf_wins == 12
    assert abs(report.village_win_rate + report.werewolf_win_rate - 1.0) < 1e-9
    assert report.avg_days >= 1.0


def test_arena_reports_role_and_agent_breakdowns():
    arena = Arena(7, lambda pid, _: RandomAgent(pid), n_games=8, base_seed=100)
    report = arena.run()
    survival = report.role_survival()
    assert {"werewolf", "seer", "doctor", "villager"} <= set(survival)
    assert all(0.0 <= rate <= 1.0 for rate in survival.values())
    assert report.agent_win_rate()["random"] >= 0.0


def test_arena_is_reproducible_for_a_base_seed():
    def run():
        return Arena(7, lambda pid, _: RandomAgent(pid), n_games=6, base_seed=5).run()

    a, b = run(), run()
    assert (a.village_wins, a.werewolf_wins, a.total_days) == (
        b.village_wins, b.werewolf_wins, b.total_days,
    )


def test_arena_progress_hook_is_called():
    seen: list[tuple[int, int]] = []
    Arena(6, lambda pid, _: RandomAgent(pid), n_games=4).run(progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_report_render_is_a_string():
    report = Arena(7, lambda pid, _: RandomAgent(pid), n_games=3).run()
    text = report.render()
    assert "Village win rate" in text and "Role survival" in text


def test_parallel_arena_matches_sequential_bit_for_bit():
    """Determinism: every game is seeded, aggregation is commutative."""
    arena = Arena(7, lambda pid, _: RandomAgent(pid), n_games=20, base_seed=42)
    sequential = arena.run()
    parallel = arena.run(max_workers=4)
    assert (parallel.village_wins, parallel.werewolf_wins) == (
        sequential.village_wins, sequential.werewolf_wins,
    )
    assert parallel.total_days == sequential.total_days
    assert parallel.role_stats == sequential.role_stats
    assert parallel.agent_stats == sequential.agent_stats


def test_parallel_progress_hook_reports_every_game():
    counts: list[tuple[int, int]] = []
    Arena(6, lambda pid, _: RandomAgent(pid), n_games=12, base_seed=1).run(
        progress=lambda d, t: counts.append((d, t)), max_workers=4,
    )
    # one progress call per game, total monotonically reaches n_games
    assert len(counts) == 12
    assert max(d for d, _ in counts) == 12
    assert all(t == 12 for _, t in counts)


def test_max_workers_one_uses_the_sequential_path():
    """The explicit default is sequential."""
    arena = Arena(7, lambda pid, _: RandomAgent(pid), n_games=4, base_seed=3)
    default = arena.run()
    explicit = arena.run(max_workers=1)
    assert (default.village_wins, default.werewolf_wins, default.total_days) == (
        explicit.village_wins, explicit.werewolf_wins, explicit.total_days,
    )
