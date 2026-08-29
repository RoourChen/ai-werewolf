"""Tests for the human-controlled agent and its scriptable UI."""

from __future__ import annotations

import random

from ai_werewolf.agents.human_agent import HumanAgent, render_advice
from ai_werewolf.copilot.advisor import Advice, Suspicion
from ai_werewolf.game.roles import Role
from ai_werewolf.game.state import Phase, PlayerInfo, PlayerView


class _ScriptedUI:
    """A test double for the terminal: answers from a queue of strings."""

    def __init__(self, inputs: list[str]) -> None:
        self.inputs = list(inputs)
        self.records: list[tuple[str, str]] = []

    def rule(self, title: str = "") -> None:
        self.records.append(("rule", title))

    def print(self, text: str = "") -> None:
        self.records.append(("print", text))

    def input(self, prompt: str = "") -> str:
        self.records.append(("input", prompt))
        return self.inputs.pop(0) if self.inputs else ""


def _view(role: Role = Role.WEREWOLF) -> PlayerView:
    players = tuple(PlayerInfo(i, f"P{i}", True) for i in range(5))
    return PlayerView(
        day=1,
        phase=Phase.DAY_VOTE,
        me_id=0,
        me_name="P0",
        me_role=role,
        players=players,
        living_ids=(0, 1, 2, 3, 4),
        events=(),
        private_notes=(),
        lang="en",
        rng=random.Random(0),
    )


def test_night_action_accepts_a_valid_target():
    ui = _ScriptedUI(["P2"])
    agent = HumanAgent(0, ui)
    assert agent.night_action(_view(Role.WEREWOLF)) == 2


def test_night_action_reprompts_on_invalid_input():
    ui = _ScriptedUI(["99", "P3"])
    agent = HumanAgent(0, ui)
    assert agent.night_action(_view(Role.WEREWOLF)) == 3
    # it must have shown the "invalid" hint between the two attempts
    printed = " ".join(t for k, t in ui.records if k == "print")
    assert "invalid" in printed


def test_vote_accepts_a_valid_target():
    ui = _ScriptedUI(["P4"])
    agent = HumanAgent(0, ui)
    assert agent.vote(_view()) == 4


def test_speak_returns_the_typed_statement():
    ui = _ScriptedUI(["P1 looks suspicious to me."])
    agent = HumanAgent(0, ui)
    assert agent.speak(_view()) == "P1 looks suspicious to me."


def test_speak_falls_back_to_an_empty_statement():
    ui = _ScriptedUI([""])
    agent = HumanAgent(0, ui)
    assert agent.speak(_view())


def test_witch_turn_uses_heal_and_poison_from_input():
    ui = _ScriptedUI(["y", "P3"])
    agent = HumanAgent(0, ui)
    heal, poison = agent.witch_turn(_view(Role.WITCH), victim=2, can_heal=True, can_poison=True)
    assert heal is True
    assert poison == 3


def test_witch_turn_skips_poison_on_blank():
    ui = _ScriptedUI(["n", ""])
    agent = HumanAgent(0, ui)
    heal, poison = agent.witch_turn(_view(Role.WITCH), victim=2, can_heal=True, can_poison=True)
    assert heal is False
    assert poison is None


def test_bid_clamps_priority_to_ten():
    ui = _ScriptedUI(["99", "I have critical information"])
    agent = HumanAgent(0, ui)
    priority, reason = agent.bid(_view())
    assert priority == 10
    assert reason == "I have critical information"


def test_render_advice_is_plain_text():
    advice = Advice(
        day=2,
        suspicions=[
            Suspicion(1, "P1", 0.85, ["voted to lynch a confirmed villager"]),
            Suspicion(2, "P2", 0.2, ["no confirming signal yet"]),
        ],
        recommended_vote=1,
        rationale="P1 is your best werewolf candidate.",
    )
    text = render_advice(advice)
    assert "P1" in text and "85%" in text
    assert "recommendation" in text
    # no rich markup should leak into the plain-text render
    assert "[" not in text
