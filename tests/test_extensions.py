"""Tests for the extension layer's vote analysis."""

from __future__ import annotations

from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.extensions.vote_analysis import analyze_votes
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.state import GameConfig
from ai_werewolf.transcript import to_json


def test_analyze_votes_on_a_finished_game_is_well_formed():
    config = GameConfig.standard(7, seed=4)
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()
    analysis = analyze_votes(to_json(result))

    # every player gets exactly one record, ranked by accuracy
    assert len(analysis.records) == 7
    for rec in analysis.records:
        assert 0.0 <= rec.accuracy <= 1.0
    accuracies = [r.accuracy for r in analysis.records]
    assert accuracies == sorted(accuracies, reverse=True)


def test_analyze_votes_scores_a_confirmed_wolf_lynch():
    """A transcript where P1 votes a confirmed werewolf must credit P1."""
    transcript = {
        "schema": "ai-werewolf.transcript/v1",
        "winner": "village",
        "days": 1,
        "players": [
            {"id": 0, "name": "P0", "role": "villager", "faction": "village", "alive": True},
            {"id": 1, "name": "P1", "role": "villager", "faction": "village", "alive": True},
            {"id": 2, "name": "P2", "role": "werewolf", "faction": "werewolves", "alive": False},
        ],
        "events": [
            {"type": "vote_cast", "day": 1, "phase": "day", "actor": 1, "target": 2,
             "public": True, "text": "P1 votes for P2.", "data": {}},
            {"type": "lynch", "day": 1, "phase": "day", "actor": None, "target": 2,
             "public": True, "text": "P2 was lynched.", "data": {"role": "werewolf"}},
        ],
    }
    analysis = analyze_votes(transcript)
    by_id = {r.player_id: r for r in analysis.records}
    assert by_id[1].wolf_lynches == 1
    assert by_id[1].accuracy == 1.0


def test_analyze_votes_renders_text():
    config = GameConfig.standard(6, seed=2)
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()
    text = analyze_votes(to_json(result)).render()
    assert "Vote analysis" in text
    assert "Voter accuracy" in text
