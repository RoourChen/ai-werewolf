"""Tests for the referee state machine and rules."""

from __future__ import annotations

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.domain.actions import Action, ActionKind
from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.referee import TRANSITIONS, InvalidTransition, Referee
from ai_werewolf.domain.roles import Faction, Role, build_roster
from ai_werewolf.domain.state import (
    DecisionRequest,
    GameConfig,
    GamePhase,
    GameState,
    PlayerView,
    build_view,
)
from ai_werewolf.players.llm_bot import LLMBot
from conftest import random_decider


def _run(seed: int = 42):
    config = GameConfig(roster=build_roster(7), seed=seed)
    return Referee(config, random_decider).run()


def test_game_reaches_a_winner():
    state = _run()
    assert state.winner in (Faction.VILLAGE, Faction.WEREWOLVES)
    assert state.phase is GamePhase.FINISHED
    wolves = state.alive_in_faction(Faction.WEREWOLVES)
    village = state.alive_in_faction(Faction.VILLAGE)
    if state.winner is Faction.VILLAGE:
        assert wolves == 0
    else:
        assert wolves >= village


def test_games_are_reproducible_for_a_seed():
    a, b = _run(7), _run(7)
    assert a.winner is b.winner
    assert a.day == b.day
    assert [e.text for e in a.events] == [e.text for e in b.events]


def test_llm_game_is_reproducible():
    def play():
        provider = MockProvider(seed=0)
        config = GameConfig(roster=build_roster(7), seed=7)

        def decider(view, request):
            return LLMBot(request.actor, provider).decide(view, request)

        return Referee(config, decider).run()

    a, b = play(), play()
    assert a.winner is b.winner
    assert [e.text for e in a.events] == [e.text for e in b.events]


def test_illegal_targets_fall_back_to_legal_choices():
    def rogue(view, request):
        if request.legal_targets:
            return Action(request.kind, request.actor, target=999)
        return Action(request.kind, request.actor)

    config = GameConfig(roster=build_roster(7), seed=1)
    state = Referee(config, rogue).run()
    assert state.winner in (Faction.VILLAGE, Faction.WEREWOLVES)


def test_transition_table_is_a_valid_state_machine():
    assert GamePhase.NIGHT in TRANSITIONS[GamePhase.SETUP]
    assert GamePhase.FINISHED in TRANSITIONS[GamePhase.DAWN]
    assert GamePhase.FINISHED in TRANSITIONS[GamePhase.RESOLUTION]
    assert TRANSITIONS[GamePhase.FINISHED] == frozenset()


def test_invalid_transition_is_rejected():
    config = GameConfig(roster=build_roster(7), seed=1)
    referee = Referee(config, random_decider)
    with pytest.raises(InvalidTransition):
        referee._transition(GamePhase.DISCUSSION)  # not allowed from SETUP


def test_players_cannot_see_unauthorised_secrets():
    state = _run(seed=9)
    for pid in range(len(state.seats)):
        view = build_view(state, pid)
        for event in view.events:
            assert event.is_public() or pid in (event.audience or frozenset())


def test_seer_result_is_private_to_the_seer():
    state = _run(seed=5)
    seer_events = [e for e in state.events if e.kind is EventKind.SEER_RESULT]
    assert seer_events
    for event in seer_events:
        assert not event.is_public()
        assert event.audience is not None and len(event.audience) == 1


class _WitchScript:
    def __init__(self) -> None:
        self.heal = False
        self.poison = -1
        self.wolf_target = -1

    def decider(self, view: PlayerView, request: DecisionRequest) -> Action:
        if request.kind is ActionKind.NIGHT_KILL:
            target = self.wolf_target if self.wolf_target in view.living_ids() else view.living_others()[0]
            return Action(ActionKind.NIGHT_KILL, request.actor, target=target)
        if request.kind is ActionKind.WITCH_POTIONS:
            poison = self.poison if self.poison in request.legal_targets else None
            return Action(
                ActionKind.WITCH_POTIONS,
                request.actor,
                heal=self.heal,
                poison=poison,
            )
        return random_decider(view, request)


def test_witch_heal_cancels_the_night_kill():
    config = GameConfig(roster=build_roster(7), seed=2)
    victim = next(
        s.id for s in GameState.new(config).seats if s.role is Role.VILLAGER
    )
    script = _WitchScript()
    script.heal = True
    script.wolf_target = victim
    state = Referee(config, script.decider).run()
    assert any(
        e.kind is EventKind.PEACEFUL_NIGHT and e.day == 1 for e in state.events
    )
