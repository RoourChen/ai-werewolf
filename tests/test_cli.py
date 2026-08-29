"""Smoke tests for the command-line interface."""

from __future__ import annotations

import pytest

from ai_werewolf.cli import build_parser, main


def test_simulate_command_runs():
    assert main(["simulate", "--players", "6", "--seed", "2"]) == 0


def test_arena_command_runs():
    assert main(["arena", "--games", "3", "--players", "7", "--villagers", "random"]) == 0


def test_leaderboard_command_runs():
    assert main(["leaderboard", "--games", "3", "--players", "7"]) == 0


def test_unknown_provider_is_reported(capsys):
    rc = main(["simulate", "--provider", "bogus"])
    assert rc == 1
    assert "error" in capsys.readouterr().err


def test_parser_requires_a_subcommand():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
