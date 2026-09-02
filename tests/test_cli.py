"""Smoke tests for the command-line interface."""

from __future__ import annotations

import pytest

from ai_werewolf.cli import build_parser, main


def test_simulate_command_runs():
    assert main(["simulate", "--players", "7", "--seed", "2"]) == 0


def test_arena_command_runs():
    assert main(["arena", "--games", "3", "--players", "7", "--bots", "random"]) == 0


def test_calibrate_command_runs():
    assert main(["calibrate", "--games", "3", "--players", "7"]) == 0


def test_replay_command_runs(tmp_path):
    path = tmp_path / "g.json"
    assert main(["simulate", "--players", "7", "--seed", "1", "--transcript", str(path)]) == 0
    assert main(["replay", str(path)]) == 0


def test_simulate_saves_traces_in_transcript(tmp_path):
    import json

    path = tmp_path / "g.json"
    assert main(["simulate", "--players", "7", "--seed", "1", "--transcript", str(path)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "traces" in data
    assert data["traces"]  # non-empty decision traces


def test_play_transcript_saves_sanitized_record(tmp_path, monkeypatch):
    import json

    from ai_werewolf import cli
    from conftest import AutoChannel

    # Replace the interactive terminal channel with a scripted human channel.
    monkeypatch.setattr(cli, "TerminalChannel", lambda console: AutoChannel())
    path = tmp_path / "play.json"
    assert cli.main(["play", "--provider", "mock", "--seed", "1", "--transcript", str(path)]) == 0
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "api_key" not in text  # no API key anywhere in the file
    data = json.loads(text)
    assert data["events"]
    assert data["traces"]
    assert data["model_stats"] is not None
    # every trace record carries the first_failure field
    first = next(rec for recs in data["traces"].values() for rec in recs)
    assert "first_failure" in first

    # the saved file can be read back by the replay command
    assert cli.main(["replay", str(path)]) == 0


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
