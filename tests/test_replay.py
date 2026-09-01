"""Tests for replay recording and rendering."""

from __future__ import annotations

import json

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import build_roster
from ai_werewolf.domain.state import GameConfig
from ai_werewolf.replay.recorder import (
    SCHEMA,
    load,
    record_game,
    record_session,
    replay_text,
    save,
)
from ai_werewolf.server.room import AIConfig, HumanSeat, RoomConfig
from ai_werewolf.server.session import GameSession
from conftest import AutoChannel, random_decider


def _finished_state():
    config = GameConfig(roster=build_roster(7), seed=3)
    return Referee(config, random_decider).run()


def test_record_game_has_the_expected_shape():
    replay = record_game(_finished_state())
    assert replay["schema"] == SCHEMA
    assert replay["winner"] in ("village", "werewolves")
    assert len(replay["seats"]) == 7
    assert replay["events"]


def test_replay_round_trips_through_json():
    replay = record_game(_finished_state())
    assert json.loads(json.dumps(replay)) == replay


def test_save_and_load(tmp_path):
    path = save(record_game(_finished_state()), tmp_path / "game.json")
    assert path.exists()
    data = load(path)
    assert data["schema"] == SCHEMA


def test_replay_text_is_readable():
    text = replay_text(record_game(_finished_state()))
    assert "回放" in text
    assert len(text.splitlines()) > 5


def test_record_session_includes_chat_and_traces():
    config = RoomConfig(
        capacity=7,
        ai=AIConfig(count=6, policy="llm", provider=MockProvider(seed=0)),
        seed=1,
    )
    humans = {0: HumanSeat(name="Alice", channel=AutoChannel())}
    session = GameSession(config, humans)
    session.run()
    replay = record_session(session)
    assert "chat" in replay
    assert isinstance(replay["chat"], list)
    assert "traces" in replay
    assert replay["human_seats"] == [0]
    assert replay["persona_map"]
