"""Player policies.

A :class:`Player` controls one seat. It is handed a
:class:`~ai_werewolf.domain.state.PlayerView` and a
:class:`~ai_werewolf.domain.state.DecisionRequest`, and returns an
:class:`~ai_werewolf.domain.actions.Action`. Implementations here cover
random bots, LLM bots and humans connected through a transport channel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ai_werewolf.domain.actions import Action
from ai_werewolf.domain.state import DecisionRequest, PlayerView


class Player(ABC):
    """A single seat's decision-making policy."""

    #: short identifier used in stats and reports
    name: str = "player"

    def __init__(self, player_id: int) -> None:
        self.player_id = player_id

    @abstractmethod
    def decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        """Return the action this player takes for ``request``."""
