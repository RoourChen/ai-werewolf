"""Regression tests for the product-review fixes."""

from __future__ import annotations

import pytest

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.ai.provider import OpenAICompatProvider
from ai_werewolf.domain.actions import Action, ActionKind
from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import Role, build_roster
from ai_werewolf.domain.state import GameConfig, GamePhase, GameState
from ai_werewolf.server.room import AIConfig, Room, RoomConfig
from conftest import AutoChannel, random_decider


# --------------------------------------------------------------- referee rules
def test_wolves_cannot_target_wolves():
    config = GameConfig(roster=build_roster(7), seed=2)
    wolves = [s.id for s in GameState.new(config).seats if s.role is Role.WEREWOLF]
    wolf_teammate = wolves[1]

    def decider(view, request):
        if request.kind is ActionKind.NIGHT_KILL:
            return Action(ActionKind.NIGHT_KILL, request.actor, target=wolf_teammate)
        return random_decider(view, request)

    state = Referee(config, decider).run()
    for event in state.events:
        if event.kind is EventKind.WOLF_KILL:
            assert event.target not in wolves


def test_witch_uses_at_most_one_potion_per_night():
    config = GameConfig(roster=build_roster(7), seed=3)
    referee = Referee(config, random_decider)
    villagers = [s.id for s in referee.state.seats if s.role is Role.VILLAGER]
    victim, poison_target = villagers[0], villagers[1]

    class Script:
        def __call__(self, view, request):
            if request.kind is ActionKind.WITCH_POTIONS:
                return Action(
                    ActionKind.WITCH_POTIONS, request.actor, heal=True, poison=poison_target
                )
            return random_decider(view, request)

    referee.decider = Script()
    healed, poisoned = referee._witch_potions(kill=victim)
    assert healed is True
    assert poisoned is None  # heal consumed the only allowed potion this night


def test_witch_cannot_self_heal_after_night_one():
    config = GameConfig(roster=build_roster(7), seed=3)
    referee = Referee(config, random_decider)
    witch = next(s for s in referee.state.seats if s.role is Role.WITCH)
    referee.state.day = 2
    referee.state.witch_heal_used = False
    referee.state.witch_poison_used = False

    class Script:
        def __call__(self, view, request):
            if request.kind is ActionKind.WITCH_POTIONS:
                return Action(ActionKind.WITCH_POTIONS, request.actor, heal=True)
            return random_decider(view, request)

    referee.decider = Script()
    healed, _ = referee._witch_potions(kill=witch.id)
    assert healed is False


def test_first_tie_revotes_and_second_tie_no_lynch():
    config = GameConfig(roster=build_roster(7), seed=5)
    referee = Referee(config, random_decider)
    referee.state.seat(6).alive = False  # 6 living voters: 0..5
    referee.state.phase = GamePhase.VOTING
    referee.state.day = 1

    plan = {
        1: {0: 2, 1: 2, 2: 4, 3: 4, 4: 0, 5: 0},
        2: {0: 2, 1: 2, 3: 2, 2: 4, 4: 4, 5: 4},
    }

    class Script:
        def __init__(self) -> None:
            self.vote_count = 0

        def __call__(self, view, request):
            if request.kind is ActionKind.VOTE:
                round_num = self.vote_count // 6 + 1  # 6 living voters per round
                self.vote_count += 1
                target = plan[round_num].get(request.actor, request.legal_targets[0])
                if target not in request.legal_targets:
                    target = request.legal_targets[0]
                return Action(ActionKind.VOTE, request.actor, target=target)
            return random_decider(view, request)

    referee.decider = Script()
    referee._voting()
    rounds = {e.data.get("round") for e in referee.state.events if e.kind is EventKind.VOTE}
    assert rounds == {1, 2}
    assert any(e.kind is EventKind.NO_LYNCH for e in referee.state.events)
    assert not any(e.kind is EventKind.LYNCH for e in referee.state.events)


def test_lynched_player_gets_last_words():
    config = GameConfig(roster=build_roster(7), seed=5)
    referee = Referee(config, random_decider)
    referee.state.seat(6).alive = False
    referee.state.phase = GamePhase.VOTING
    referee.state.day = 1

    class Script:
        def __call__(self, view, request):
            if request.kind is ActionKind.VOTE:
                target = 0 if 0 in request.legal_targets else request.legal_targets[0]
                return Action(ActionKind.VOTE, request.actor, target=target)
            if request.kind is ActionKind.LAST_WORDS:
                return Action(ActionKind.LAST_WORDS, request.actor, text="我的遗言")
            return random_decider(view, request)

    referee.decider = Script()
    referee._voting()
    lynch = [e for e in referee.state.events if e.kind is EventKind.LYNCH]
    assert lynch and lynch[0].target == 0
    last_words = [e for e in referee.state.events if e.kind is EventKind.LAST_WORDS]
    assert last_words and last_words[0].actor == 0


def test_human_wolf_confirmation_overrides_suggestion():
    config = GameConfig(roster=build_roster(7), seed=4)
    referee = Referee(config, random_decider)
    wolves = [s for s in referee.state.seats if s.role is Role.WEREWOLF]
    referee.state.seat(wolves[0].id).is_human = True
    referee.state.seat(wolves[1].id).is_human = False
    suggestion = next(s.id for s in referee.state.seats if s.role is Role.VILLAGER)
    chosen = next(s.id for s in referee.state.seats if s.role is Role.VILLAGER and s.id != suggestion)

    class Script:
        def __call__(self, view, request):
            if request.kind is ActionKind.NIGHT_KILL:
                return Action(ActionKind.NIGHT_KILL, request.actor, target=suggestion)
            if request.kind is ActionKind.PACK_CONFIRM:
                return Action(ActionKind.PACK_CONFIRM, request.actor, target=chosen)
            return random_decider(view, request)

    referee.decider = Script()
    victim = referee._werewolf_kill()
    assert victim == chosen  # the human's confirmation wins


def test_human_wolf_timeout_falls_back_to_suggestion():
    config = GameConfig(roster=build_roster(7), seed=4)
    referee = Referee(config, random_decider)
    wolves = [s for s in referee.state.seats if s.role is Role.WEREWOLF]
    referee.state.seat(wolves[0].id).is_human = True
    referee.state.seat(wolves[1].id).is_human = False
    suggestion = next(s.id for s in referee.state.seats if s.role is Role.VILLAGER)

    class Script:
        def __call__(self, view, request):
            if request.kind is ActionKind.NIGHT_KILL:
                return Action(ActionKind.NIGHT_KILL, request.actor, target=suggestion)
            if request.kind is ActionKind.PACK_CONFIRM:
                raise TimeoutError("human timeout")
            return random_decider(view, request)

    referee.decider = Script()
    victim = referee._werewolf_kill()
    assert victim == suggestion  # deterministic fallback to the AI suggestion


# ------------------------------------------------------------- hard constraints
def test_room_config_enforces_one_human_six_ai():
    with pytest.raises(ValueError):
        RoomConfig(capacity=7, ai=AIConfig(count=5))  # would allow 2 humans
    with pytest.raises(ValueError):
        RoomConfig(capacity=8, ai=AIConfig(count=6))


def test_unknown_ai_policy_is_rejected():
    with pytest.raises(ValueError):
        AIConfig(count=6, policy="typo")


def test_model_participates_in_provider_build(monkeypatch):
    monkeypatch.setenv("AIWEREWOLF_PROVIDER", "deepseek")
    monkeypatch.setenv("AIWEREWOLF_API_KEY", "k")
    monkeypatch.setenv("AIWEREWOLF_MODEL", "base-model")
    ai = AIConfig(count=6, policy="llm", model="my-model")
    provider = ai.resolve_provider(seed=0)
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.config.model == "my-model"


def test_resolve_provider_falls_back_to_mock():
    ai = AIConfig(count=6, policy="llm")
    assert isinstance(ai.resolve_provider(seed=0), MockProvider)


def test_human_seat_is_marked():
    room = Room(RoomConfig(
        capacity=7,
        ai=AIConfig(count=6, policy="llm", provider=MockProvider(seed=0)),
        seed=1,
    ))
    room.add_human("你", AutoChannel())
    session = room.start()
    assert session.result is not None
    assert session.result.seat(0).is_human is True
    assert all(not session.result.seat(i).is_human for i in range(1, 7))


def test_mock_produces_real_deception_record():
    room = Room(RoomConfig(
        capacity=7,
        ai=AIConfig(count=6, policy="llm", provider=MockProvider(seed=0)),
        seed=11,
    ))
    room.add_human("你", AutoChannel())
    session = room.start()
    deceptive = [rec for recs in session.traces.values() for rec in recs if rec.deception]
    assert deceptive
    rec = deceptive[0]
    target = rec.deception_plan["target"]
    assert isinstance(target, int)
    assert abs(rec.public_suspicion[target] - rec.private_suspicion[target]) >= 0.20
