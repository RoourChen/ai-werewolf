"""Tests for copilot Brier calibration."""

from __future__ import annotations

import pytest

from ai_werewolf.copilot.calibration import evaluate_copilot


def test_evaluation_produces_a_well_formed_report():
    report = evaluate_copilot(n_players=7, n_games=6, base_seed=0)
    assert report.n_games == 6
    assert report.n_predictions > 0
    assert 0.0 < report.base_rate < 0.6
    assert 0.0 <= report.brier_score <= 1.0


def test_skill_score_matches_its_definition():
    report = evaluate_copilot(n_players=7, n_games=8, base_seed=1)
    baseline = report.base_rate * (1.0 - report.base_rate)
    expected = 1.0 - report.brier_score / baseline
    assert abs(report.skill_score - expected) < 1e-9


def test_evaluation_is_reproducible():
    a = evaluate_copilot(n_players=7, n_games=5, base_seed=9)
    b = evaluate_copilot(n_players=7, n_games=5, base_seed=9)
    assert a.brier_score == b.brier_score
    assert a.n_predictions == b.n_predictions


def test_evaluation_rejects_zero_games():
    with pytest.raises(ValueError):
        evaluate_copilot(n_players=7, n_games=0)


def test_reliability_bins_sum_to_predictions():
    report = evaluate_copilot(n_players=7, n_games=6, base_seed=2)
    assert sum(b.count for b in report.bins) == report.n_predictions
