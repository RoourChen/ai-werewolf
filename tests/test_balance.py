"""Tests for the offline faction win-rate baseline."""

from __future__ import annotations

import pytest

from ai_werewolf.balance import BalanceReport, run_balance


def test_balance_report_is_stratified_and_rule_clean() -> None:
    report = run_balance(n_games_per_seat=3, base_seed=0)

    assert report.n_games == 21  # 7 human seats x 3 games
    assert report.village_wins + report.werewolf_wins == 21
    assert report.rule_deviations == []

    # each game deals exactly 2 wolves / 1 seer / 1 witch / 3 villagers
    assert report.role_stats["werewolf"][0] == 42
    assert report.role_stats["seer"][0] == 21
    assert report.role_stats["witch"][0] == 21
    assert report.role_stats["villager"][0] == 63

    # every physical seat plays every game
    assert set(report.seat_stats) == {0, 1, 2, 3, 4, 5, 6}
    assert all(games == 21 for games, _ in report.seat_stats.values())

    # seat × role cross-tab: 7 seats, each with all 4 roles
    assert set(report.seat_role_stats) == {0, 1, 2, 3, 4, 5, 6}
    for by_role in report.seat_role_stats.values():
        assert set(by_role) == {"werewolf", "seer", "witch", "villager"}

    # Wilson confidence intervals are well-formed
    low, high = report.village_ci
    assert 0.0 <= low <= high <= 1.0

    # every human seat was swept equally
    assert set(report.human_seat_stats) == {0, 1, 2, 3, 4, 5, 6}
    assert all(games == 3 for games, _ in report.human_seat_stats.values())

    # speaking-order ranks are contiguous from 0 and never exceed 6 players
    assert set(report.order_stats) == set(range(len(report.order_stats)))


def test_balance_is_reproducible_for_same_seed() -> None:
    first = run_balance(n_games_per_seat=2, base_seed=0)
    second = run_balance(n_games_per_seat=2, base_seed=0)
    assert [game["winner"] for game in first.per_seed] == [
        game["winner"] for game in second.per_seed
    ]
    assert first.village_wins == second.village_wins
    assert first.werewolf_wins == second.werewolf_wins


def test_single_human_seat_sweep() -> None:
    report = run_balance(n_games_per_seat=5, human_seats=(0,), base_seed=10)
    assert report.n_games == 5
    assert set(report.human_seat_stats) == {0}
    assert report.human_seat_stats[0][0] == 5


def test_random_strategy_control_runs() -> None:
    report = run_balance(n_games_per_seat=2, base_seed=0, strategy="random")
    assert report.strategy == "random"
    assert report.n_games == 14
    assert report.rule_deviations == []


def test_unknown_strategy_is_rejected() -> None:
    with pytest.raises(ValueError):
        run_balance(n_games_per_seat=1, strategy="nope")


def test_balance_report_renders() -> None:
    report = run_balance(n_games_per_seat=1, base_seed=0)
    text = report.render()
    assert "村民阵营胜率" in text
    assert "狼人阵营胜率" in text
    assert "先后手" in text
    assert "规则不变量" in text
    assert isinstance(report, BalanceReport)
