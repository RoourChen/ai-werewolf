"""Tests for structured decision traces, deception rules and retry."""

from __future__ import annotations

import json
import random

import pytest

from ai_werewolf.ai.personas import PERSONAS
from ai_werewolf.ai.provider import Prompt, Provider
from ai_werewolf.domain.actions import ActionKind
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.roles import Role
from ai_werewolf.domain.state import DecisionRequest, GamePhase, PlayerView, PublicSeat
from ai_werewolf.domain.trace import DecisionRecord, compute_delta, key_player
from ai_werewolf.players.llm_bot import LLMBot


def _view(role: Role, pack: tuple[int, ...] = ()) -> PlayerView:
    seats = tuple(PublicSeat(i, f"P{i}", True) for i in range(5))
    events = (GameEvent(EventKind.GAME_STARTED, 0, "setup", "start", id=0),)
    if role is Role.WEREWOLF and pack:
        events += (
            GameEvent(EventKind.PACK_MATES, 0, "setup", "pack",
                      data={"pack": list(pack)}, id=1),
        )
    return PlayerView(
        me=0, day=1, phase=GamePhase.VOTING, language="zh", my_role=role,
        seats=seats, living=(0, 1, 2, 3, 4), events=events, secrets=(),
        rng=random.Random(0),
    )


_OTHERS = [1, 2, 3, 4]


def _json(choice: int = 1, *, private=None, public=None, evidence=None,
          deception=None, confidence: float = 0.6) -> str:
    deception = deception or {
        "active": False, "target": None, "public_statement": "",
        "purpose": "", "true_basis": "", "fabricated_event": None,
    }
    return json.dumps({
        "choice": choice,
        "reasoning": "r",
        "confidence": confidence,
        "evidence": evidence,
        "private_suspicion": private or dict.fromkeys(_OTHERS, 0.3),
        "public_suspicion": public or dict.fromkeys(_OTHERS, 0.3),
        "strategic_threat": dict.fromkeys(_OTHERS, 0.4),
        "deception": deception,
    })


class _FixedProvider(Provider):
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def complete(self, prompt: Prompt) -> str:
        self.calls += 1
        return self.text


def _vote_request() -> DecisionRequest:
    return DecisionRequest(ActionKind.VOTE, 0, legal_targets=(1, 2, 3, 4))


def test_decision_record_carries_three_channels_and_delta():
    bot = LLMBot(0, _FixedProvider(_json()), PERSONAS["skeptic"])
    bot.decide(_view(Role.VILLAGER), _vote_request())
    record = bot.latest_record
    assert record is not None
    assert set(record.private_suspicion) == set(_OTHERS)
    assert set(record.public_suspicion) == set(_OTHERS)
    assert set(record.strategic_threat) == set(_OTHERS)
    assert record.persona == "skeptic"
    assert record.fallback_reason is None


def test_delta_and_key_player_helpers():
    delta = compute_delta({1: 0.5, 2: 0.5}, {1: 0.9, 2: 0.2}, [1, 2])
    assert abs(delta[1] - 0.4) < 1e-9
    assert abs(delta[2] - (-0.3)) < 1e-9
    assert key_player(delta) == 1


def test_gap_without_mark_is_retried_then_falls_back():
    text = _json(private=dict.fromkeys(_OTHERS, 0.1), public=dict.fromkeys(_OTHERS, 0.9))
    provider = _FixedProvider(text)
    bot = LLMBot(0, provider, PERSONAS["aggressor"])
    action = bot.decide(_view(Role.VILLAGER), _vote_request())
    record = bot.latest_record
    assert record is not None
    assert provider.calls == 2  # one retry
    assert record.fallback_reason is not None
    assert "gap" in record.fallback_reason
    assert action.target in (1, 2, 3, 4)


def test_marked_deception_with_full_plan_is_accepted():
    text = _json(
        private=dict.fromkeys(_OTHERS, 0.1),
        public={1: 0.9, 2: 0.1, 3: 0.1, 4: 0.1},
        deception={
            "active": True, "target": 1, "public_statement": "P1 很可疑",
            "purpose": "转移火力", "true_basis": "我知道他不是狼",
            "fabricated_event": None,
        },
    )
    bot = LLMBot(0, _FixedProvider(text), PERSONAS["mediator"])
    bot.decide(_view(Role.VILLAGER), _vote_request())
    record = bot.latest_record
    assert record is not None
    assert record.deception is True
    assert record.deception_plan["target"] == 1
    assert record.fallback_reason is None


def test_marked_deception_without_gap_is_rejected():
    # private == public, no 0.20 gap, no fabrication -> rejected
    text = _json(
        private=dict.fromkeys(_OTHERS, 0.3),
        public=dict.fromkeys(_OTHERS, 0.3),
        deception={
            "active": True, "target": 1, "public_statement": "x",
            "purpose": "y", "true_basis": "z", "fabricated_event": None,
        },
    )
    bot = LLMBot(0, _FixedProvider(text), PERSONAS["nice"])
    bot.decide(_view(Role.VILLAGER), _vote_request())
    assert bot.latest_record is not None
    assert bot.latest_record.fallback_reason is not None
    assert "deception" in bot.latest_record.fallback_reason


def test_deception_target_must_be_a_valid_player():
    text = _json(
        private=dict.fromkeys(_OTHERS, 0.1),
        public={1: 0.9, 2: 0.1, 3: 0.1, 4: 0.1},
        deception={
            "active": True, "target": 999, "public_statement": "x",
            "purpose": "y", "true_basis": "z", "fabricated_event": None,
        },
    )
    bot = LLMBot(0, _FixedProvider(text), PERSONAS["skeptic"])
    bot.decide(_view(Role.VILLAGER), _vote_request())
    assert bot.latest_record is not None
    assert "target" in bot.latest_record.fallback_reason


def test_evidence_must_reference_a_visible_event_id():
    bad = LLMBot(0, _FixedProvider(_json(evidence=999)), PERSONAS["analyst"])
    bad.decide(_view(Role.VILLAGER), _vote_request())
    assert "unknown event" in bad.latest_record.fallback_reason

    good = LLMBot(0, _FixedProvider(_json(evidence=0)), PERSONAS["analyst"])
    good.decide(_view(Role.VILLAGER), _vote_request())
    assert good.latest_record.fallback_reason is None
    assert good.latest_record.evidence == "E0"


def test_missing_suspicion_keys_are_rejected():
    text = _json(private={1: 0.2, 2: 0.3})  # missing 3 and 4
    bot = LLMBot(0, _FixedProvider(text), PERSONAS["chatterbox"])
    bot.decide(_view(Role.VILLAGER), _vote_request())
    assert bot.latest_record is not None
    assert "private_suspicion" in bot.latest_record.fallback_reason


def test_out_of_range_scores_are_rejected():
    text = _json(private={1: 0.2, 2: 0.3, 3: 1.5, 4: 0.5})
    bot = LLMBot(0, _FixedProvider(text), PERSONAS["chatterbox"])
    bot.decide(_view(Role.VILLAGER), _vote_request())
    assert bot.latest_record is not None
    assert "private_suspicion" in bot.latest_record.fallback_reason


def test_wolf_cannot_pretend_unknown_judgment():
    text = _json(private=dict.fromkeys(_OTHERS, 0.5))
    bot = LLMBot(0, _FixedProvider(text), PERSONAS["chatterbox"])
    bot.decide(_view(Role.WEREWOLF, pack=(2,)), _vote_request())
    record = bot.latest_record
    assert record is not None
    assert record.fallback_reason is not None
    assert "wolf pretended" in record.fallback_reason


def test_record_is_immutable_and_to_dict_copies():
    record = DecisionRecord(
        day=1, phase="voting", actor=3, persona="aggressor", role="werewolf",
        kind="vote", private_suspicion={0: 0.0}, public_suspicion={0: 0.8},
        strategic_threat={0: 0.9}, delta={0: 0.8}, key_player=0,
        evidence="E1", candidates=(0, 1), decision="vote P0",
        confidence=0.8, rationale="转移火力", deception=True,
        deception_plan={"target": 0, "public_statement": "x", "purpose": "y",
                        "true_basis": "z"},
    )
    with pytest.raises(TypeError):
        record.private_suspicion[0] = 0.99  # type: ignore[index]

    snapshot = record.to_dict()
    snapshot["private_suspicion"][0] = 0.99
    assert record.private_suspicion[0] == 0.0
    assert json.loads(json.dumps(record.to_dict()))["deception"] is True
