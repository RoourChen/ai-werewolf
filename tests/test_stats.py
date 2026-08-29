"""Tests for the statistics ledger and achievements."""

from __future__ import annotations

from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import Faction, Role, build_roster
from ai_werewolf.domain.state import GameConfig
from ai_werewolf.stats.ledger import StatsLedger
from conftest import random_decider


def test_ledger_records_wins_and_survivals():
    ledger = StatsLedger()
    ledger.record("Alice", Role.WEREWOLF, Faction.WEREWOLVES, Faction.WEREWOLVES, True)
    ledger.record("Alice", Role.VILLAGER, Faction.VILLAGE, Faction.WEREWOLVES, False)
    assert ledger.win_rate("Alice") == 0.5
    rec = ledger.records["Alice"]
    assert rec.survivals == 1


def test_ledger_leaderboard_sorts_by_win_rate():
    ledger = StatsLedger()
    for _ in range(4):
        ledger.record("Winner", Role.WEREWOLF, Faction.WEREWOLVES, Faction.WEREWOLVES, True)
    for _ in range(4):
        ledger.record("Loser", Role.VILLAGER, Faction.VILLAGE, Faction.WEREWOLVES, False)
    board = ledger.leaderboard()
    assert board[0][0] == "Winner"
    assert board[1][0] == "Loser"


def test_achievements_are_derived_from_records():
    ledger = StatsLedger()
    ledger.record("WolfKing", Role.WEREWOLF, Faction.WEREWOLVES, Faction.WEREWOLVES, True)
    badges = ledger.achievements("WolfKing")
    assert "首胜" in badges
    assert "狼王" in badges


def test_record_game_populates_the_ledger():
    config = GameConfig(roster=build_roster(7), seed=4)
    state = Referee(config, random_decider).run()
    ledger = StatsLedger()
    ledger.record_game(state)
    assert len(ledger.records) == 7
    assert all(rec.games == 1 for rec in ledger.records.values())


def test_unknown_player_has_no_achievements():
    assert StatsLedger().achievements("nobody") == []
