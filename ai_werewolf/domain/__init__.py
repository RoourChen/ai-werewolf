"""Domain layer: roles, actions, events, rules and the referee state machine.

This package holds the pure game logic. It performs no I/O and never talks to
a network, terminal or database — the server layer drives it.
"""

from ai_werewolf.domain.actions import Action, ActionKind
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.referee import GamePhase, Referee
from ai_werewolf.domain.roles import Faction, Role, build_roster
from ai_werewolf.domain.state import (
    DecisionRequest,
    GameConfig,
    GameState,
    PlayerView,
    Seat,
    build_view,
)

__all__ = [
    "Action",
    "ActionKind",
    "EventKind",
    "GameEvent",
    "GamePhase",
    "Referee",
    "Faction",
    "Role",
    "build_roster",
    "DecisionRequest",
    "GameConfig",
    "GameState",
    "PlayerView",
    "Seat",
    "build_view",
]
