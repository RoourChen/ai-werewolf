"""Tests for bidding-based discussion turn-taking."""

from __future__ import annotations

import pytest

from ai_werewolf.agents.llm_agent import LLMAgent
from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.events import EventType
from ai_werewolf.game.roles import Faction, standard_setup
from ai_werewolf.game.state import GameConfig
from ai_werewolf.llm.mock import MockProvider


def test_discussion_mode_defaults_to_ordered():
    assert GameConfig.standard(7).discussion_mode == "ordered"


def test_unknown_discussion_mode_is_rejected():
    with pytest.raises(ValueError):
        GameConfig(roles=standard_setup(7), discussion_mode="freeforall")


def test_ordered_mode_emits_no_bids():
    config = GameConfig.standard(7, seed=1)  # ordered is the default
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()
    assert not any(e.type is EventType.SPEAK_BID for e in result.events)


def test_bidding_mode_emits_one_bid_per_speaker():
    config = GameConfig.standard(7, seed=2, discussion_mode="bidding")
    result = GameEngine(config, lambda pid, _: RandomAgent(pid)).run()

    day1_bids = [e for e in result.events if e.type is EventType.SPEAK_BID and e.day == 1]
    day1_talk = [e for e in result.events if e.type is EventType.STATEMENT and e.day == 1]
    assert day1_bids and len(day1_bids) == len(day1_talk)
    for bid in day1_bids:
        assert 0 <= bid.data["priority"] <= 10


class _BidScript(RandomAgent):
    """Bids its own player id as priority — higher seat speaks earlier."""

    def bid(self, view):
        return (view.me_id, f"P{view.me_id}")


def test_bidding_seats_the_highest_bidder_first():
    config = GameConfig.standard(7, seed=1, discussion_mode="bidding")
    result = GameEngine(config, lambda pid, _: _BidScript(pid)).run()
    speakers = [
        e.actor for e in result.events
        if e.type is EventType.STATEMENT and e.day == 1
    ]
    # priority == player id, so statements run in descending id order
    assert speakers == sorted(speakers, reverse=True)


def test_bidding_game_with_llm_agents_reaches_a_winner():
    config = GameConfig.standard(7, seed=3, discussion_mode="bidding")
    provider = MockProvider(seed=0)
    result = GameEngine(config, lambda pid, _: LLMAgent(pid, provider)).run()
    assert result.winner in (Faction.VILLAGE, Faction.WEREWOLVES)
    assert any(e.type is EventType.SPEAK_BID for e in result.events)


def test_illegal_bids_are_clamped():
    class _RogueBidder(RandomAgent):
        def bid(self, view):
            return (999, "x" * 999)  # out-of-range priority, over-long reason

    config = GameConfig.standard(6, seed=1, discussion_mode="bidding")
    result = GameEngine(config, lambda pid, _: _RogueBidder(pid)).run()
    for bid in (e for e in result.events if e.type is EventType.SPEAK_BID):
        assert 0 <= bid.data["priority"] <= 10
        assert len(bid.data["reason"]) <= 200
