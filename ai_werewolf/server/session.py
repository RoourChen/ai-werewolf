"""The game session: wires a room's humans and bots into a referee run.

The session is the bridge between the pure :class:`~ai_werewolf.domain.referee.
Referee` and the outside world. It builds the players, drives the referee,
broadcasts public events to human channels and spectators, and accepts
real-time text/voice chat during the discussion phase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ai_werewolf.domain.actions import Action
from ai_werewolf.domain.events import GameEvent, to_dict
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import build_roster
from ai_werewolf.domain.state import (
    DecisionRequest,
    GameConfig,
    GamePhase,
    GameState,
    PlayerView,
)
from ai_werewolf.players.base import Player
from ai_werewolf.players.human import HumanPlayer
from ai_werewolf.server.room import HumanSeat, RoomConfig
from ai_werewolf.transport.channel import Channel, Envelope

BotFactory = Callable[[int], Player]


@dataclass
class ChatMessage:
    """One real-time message posted during discussion."""

    player: int | None
    kind: str  # "text" | "voice"
    body: str
    day: int


@dataclass
class GameSession:
    """Runs one room to completion and exposes its live stream."""

    config: RoomConfig
    humans: dict[int, HumanSeat]
    bot_factory: BotFactory

    players: dict[int, Player] = field(default_factory=dict)
    events: list[GameEvent] = field(default_factory=list)
    chat: list[ChatMessage] = field(default_factory=list)
    spectators: list[Channel] = field(default_factory=list)
    referee: Referee | None = None
    result: GameState | None = None

    def run(self) -> GameState:
        capacity = self.config.capacity
        names: list[str | None] = [None] * capacity
        players: dict[int, Player] = {}
        for seat, human in self.humans.items():
            names[seat] = human.name
            players[seat] = HumanPlayer(seat, human.channel)
        for seat in range(capacity):
            if seat not in players:
                players[seat] = self.bot_factory(seat)
                names[seat] = f"Bot{seat}"

        game_config = GameConfig(
            roster=build_roster(capacity),
            seed=self.config.seed,
            language=self.config.language,
            discussion_mode=self.config.discussion_mode,
            player_names=names,  # type: ignore[arg-type]
        )
        self.players = players
        self.referee = Referee(game_config, self._decide, observer=self._observe)
        self.result = self.referee.run()
        self._broadcast(Envelope("result", payload={"result": _result_dict(self.result)}))
        return self.result

    def post_chat(self, player_id: int | None, kind: str, body: str) -> ChatMessage:
        """Accept a real-time text or voice message during discussion."""
        if self.referee is None or self.referee.state.phase is not GamePhase.DISCUSSION:
            raise SessionError("chat is only allowed during the discussion phase")
        message = ChatMessage(player=player_id, kind=kind, body=body, day=self.referee.state.day)
        self.chat.append(message)
        self._broadcast(Envelope(
            "chat",
            payload={"player": player_id, "kind": kind, "body": body, "day": message.day},
        ))
        return message

    def add_spectator(self, channel: Channel) -> None:
        self.spectators.append(channel)

    def _decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        return self.players[request.actor].decide(view, request)

    def _observe(self, event: GameEvent) -> None:
        self.events.append(event)
        if event.is_public():
            self._broadcast(Envelope("event", payload={"event": to_dict(event)}))

    def _broadcast(self, envelope: Envelope) -> None:
        for human in self.humans.values():
            human.channel.send(envelope)
        for spectator in self.spectators:
            spectator.send(envelope)


class SessionError(RuntimeError):
    """Raised for invalid session operations."""


def _result_dict(state: GameState) -> dict:
    return {
        "winner": state.winner.value if state.winner else None,
        "days": state.day,
        "seats": [
            {
                "id": seat.id,
                "name": seat.name,
                "role": seat.role.value,
                "alive": seat.alive,
                "is_human": seat.is_human,
            }
            for seat in state.seats
        ],
    }
