"""Tests for the copilot calibration evaluator."""

from __future__ import annotations

import json

import pytest

from ai_werewolf.copilot.calibration import (
    CalibrationBin,
    CalibrationReport,
    evaluate_copilot,
)


def test_evaluate_copilot_produces_a_well_formed_report():
    report = evaluate_copilot(n_players=7, n_games=8, base_seed=0)
    assert report.n_games == 8
    assert report.n_players == 7
    assert report.n_predictions > 0
    assert 0.0 < report.base_rate < 0.6  # 2-of-7 wolves, judged by villagers


def test_brier_score_is_in_the_unit_interval():
    report = evaluate_copilot(n_players=7, n_games=10, base_seed=1)
    assert 0.0 <= report.brier_score <= 1.0


def test_baseline_brier_equals_uncertainty():
    report = evaluate_copilot(n_players=7, n_games=10, base_seed=2)
    assert report.baseline_brier == report.uncertainty
    expected = report.base_rate * (1.0 - report.base_rate)
    assert abs(report.uncertainty - expected) < 1e-9


def test_skill_score_matches_its_definition():
    report = evaluate_copilot(n_players=7, n_games=10, base_seed=3)
    expected = 1.0 - report.brier_score / report.baseline_brier
    assert abs(report.skill_score - expected) < 1e-9


def test_murphy_decomposition_reconstructs_the_brier_score():
    """``reliability - resolution + uncertainty`` should approximate brier.

    The identity is exact only for discrete forecasts; with forecasts binned
    into 0.1-wide ranges there is a small binning residual (either sign), so the
    decomposition reconstructs the Brier score to within a tight tolerance.
    """
    report = evaluate_copilot(n_players=7, n_games=14, base_seed=4)
    recomposed = report.reliability - report.resolution + report.uncertainty
    assert abs(report.brier_score - recomposed) < 0.05


def test_reliability_diagram_bins_are_consistent():
    report = evaluate_copilot(n_players=7, n_games=12, base_seed=5)
    assert report.bins
    assert sum(b.count for b in report.bins) == report.n_predictions
    for b in report.bins:
        assert b.low < b.high
        assert b.count > 0
        assert 0.0 <= b.mean_predicted <= 1.0
        assert 0.0 <= b.observed_rate <= 1.0
        assert b.low <= b.mean_predicted <= b.high or abs(b.mean_predicted - b.high) < 1e-9


def test_evaluation_is_reproducible_for_a_base_seed():
    a = evaluate_copilot(n_players=7, n_games=6, base_seed=9)
    b = evaluate_copilot(n_players=7, n_games=6, base_seed=9)
    assert a.brier_score == b.brier_score
    assert a.n_predictions == b.n_predictions
    assert [bin.count for bin in a.bins] == [bin.count for bin in b.bins]


def test_evaluate_copilot_rejects_zero_games():
    with pytest.raises(ValueError):
        evaluate_copilot(n_players=7, n_games=0)


def test_progress_hook_fires_once_per_game():
    seen: list[tuple[int, int]] = []
    evaluate_copilot(n_players=6, n_games=4, progress=lambda d, t: seen.append((d, t)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_report_render_and_markdown_are_usable():
    report = evaluate_copilot(n_players=7, n_games=6, base_seed=7)
    text = report.render()
    assert "Brier score" in text and "reliability diagram" in text.lower()
    md = report.to_markdown()
    assert md.startswith("**Copilot calibration**")
    assert "| Predicted bin |" in md


def test_empty_report_is_safe():
    """A report with no predictions must still render without error."""
    empty = CalibrationReport()
    assert empty.skill_score == 0.0
    assert empty.baseline_brier == 0.0
    assert isinstance(empty.render(), str)


def test_calibration_bin_gap():
    b = CalibrationBin(low=0.6, high=0.7, mean_predicted=0.65, observed_rate=0.5, count=8)
    assert abs(b.gap - 0.15) < 1e-9


def test_reliability_diagram_surfaces_the_calibration_gap():
    report = evaluate_copilot(n_players=7, n_games=6, base_seed=8)
    assert "gap" in report.render().lower()
    assert "Gap" in report.to_markdown()


def test_cli_calibrate_command_runs():
    from ai_werewolf.cli import main

    assert main(["calibrate", "--games", "3", "--players", "7"]) == 0


def test_calibration_report_is_json_serialisable_via_markdown(tmp_path):
    """The Markdown export is plain text — a smoke check it writes cleanly."""
    report = evaluate_copilot(n_players=7, n_games=4, base_seed=11)
    path = tmp_path / "calibration.md"
    path.write_text(report.to_markdown(), encoding="utf-8")
    assert path.read_text(encoding="utf-8").count("\n") >= 5
    # the numeric fields are finite, plain floats
    json.dumps({"brier": report.brier_score, "skill": report.skill_score})
