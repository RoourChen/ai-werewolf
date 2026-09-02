"""Game configuration, seats, the full referee state and per-player views."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from ai_werewolf.domain.actions import ActionKind
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.roles import MVP_SEATS, Faction, Role
from ai_werewolf.i18n import LANGUAGES, L10n


class GamePhase(str, Enum):
    SETUP = "setup"
    NIGHT = "night"
    DAWN = "dawn"
    DISCUSSION = "discussion"
    VOTING = "voting"
    RESOLUTION = "resolution"
    FINISHED = "finished"


@dataclass
class GameConfig:
    """Everything needed to start a reproducible room."""

    roster: list[Role]
    seed: int | None = None
    language: str = "zh"
    discussion_rounds: int = 1
    discussion_mode: str = "seating"  # "seating" or "bidding"
    max_days: int = 20
    reveal_role_on_death: bool = False
    player_names: list[str] | None = None
    human_seats: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if len(self.roster) != MVP_SEATS:
            raise ValueError(f"the MVP only supports {MVP_SEATS}-player games")
        if self.player_names is not None and len(self.player_names) != len(self.roster):
            raise ValueError("player_names must match the number of roles")
        if self.language not in LANGUAGES:
            raise ValueError(f"unknown language {self.language!r}")
        if self.discussion_mode not in ("seating", "bidding"):
            raise ValueError(f"unknown discussion_mode {self.discussion_mode!r}")


@dataclass
class Seat:
    """One seat at the table — a human or a bot, with a dealt role."""

    id: int
    name: str
    role: Role
    is_human: bool = False
    alive: bool = True
    death_day: int | None = None
    death_cause: str | None = None

    @property
    def faction(self) -> Faction:
        return self.role.faction

    def label(self) -> str:
        return f"{self.name} (P{self.id})"


@dataclass
class GameState:
    """The referee's full, mutable picture of a game."""

    seats: list[Seat]
    config: GameConfig
    rng: random.Random
    day: int = 0
    phase: GamePhase = GamePhase.SETUP
    winner: Faction | None = None
    events: list[GameEvent] = field(default_factory=list)
    witch_heal_used: bool = False
    witch_poison_used: bool = False

    @classmethod
    def new(cls, config: GameConfig) -> GameState:
        """Deal roles onto seats and build a fresh, reproducible state."""
        rng = random.Random(config.seed)
        names = config.player_names or [_default_name(i) for i in range(len(config.roster))]
        roles = list(config.roster)
        rng.shuffle(roles)
        human = set(config.human_seats)
        seats = [
            Seat(id=i, name=names[i], role=roles[i], is_human=i in human)
            for i in range(len(roles))
        ]
        return cls(seats=seats, config=config, rng=rng)

    # ---- queries ----------------------------------------------------------
    def seat(self, player_id: int) -> Seat:
        return self.seats[player_id]

    def name(self, player_id: int) -> str:
        return self.seats[player_id].name

    def living_ids(self) -> list[int]:
        return [s.id for s in self.seats if s.alive]

    def living_others(self, player_id: int) -> list[int]:
        return [s.id for s in self.seats if s.alive and s.id != player_id]

    def living_with_role(self, role: Role) -> list[Seat]:
        return [s for s in self.seats if s.alive and s.role is role]

    def alive_in_faction(self, faction: Faction) -> int:
        return sum(1 for s in self.seats if s.alive and s.faction is faction)

    def emit(self, event: GameEvent) -> GameEvent:
        self.events.append(event)
        return event


@dataclass(frozen=True)
class PublicSeat:
    """The public facts about a seat, visible to everyone."""

    id: int
    name: str
    alive: bool


@dataclass(frozen=True)
class PlayerView:
    """The slice of a game one player is allowed to act on."""

    me: int
    day: int
    phase: GamePhase
    language: str
    my_role: Role
    seats: tuple[PublicSeat, ...]
    living: tuple[int, ...]
    events: tuple[GameEvent, ...]
    secrets: tuple[str, ...]
    rng: random.Random

    def name(self, player_id: int) -> str:
        return self.seats[player_id].name

    def living_others(self) -> list[int]:
        return [pid for pid in self.living if pid != self.me]

    @property
    def packmates(self) -> tuple[int, ...]:
        for event in self.events:
            if event.kind is EventKind.PACK_MATES:
                return tuple(event.data.get("pack", ()))
        return ()


@dataclass(frozen=True)
class DecisionRequest:
    """What the referee is asking one player to decide right now."""

    kind: ActionKind
    actor: int
    legal_targets: tuple[int, ...] = ()
    can_heal: bool = False
    can_poison: bool = False
    suggestions: tuple[int, ...] = ()


def build_view(state: GameState, player_id: int) -> PlayerView:
    """Project ``state`` down to what ``player_id`` may legally see."""
    me = state.seat(player_id)
    visible = tuple(e for e in state.events if e.visible_to(player_id))
    return PlayerView(
        me=me.id,
        day=state.day,
        phase=state.phase,
        language=state.config.language,
        my_role=me.role,
        seats=tuple(PublicSeat(s.id, s.name, s.alive) for s in state.seats),
        living=tuple(state.living_ids()),
        events=visible,
        secrets=_private_notes(state, visible),
        rng=state.rng,
    )


def _private_notes(state: GameState, visible: tuple[GameEvent, ...]) -> tuple[str, ...]:
    l10n = L10n(state.config.language)
    notes: list[str] = []
    for event in visible:
        if event.kind is EventKind.ROLE_DEALT:
            notes.append(l10n.msg("role.dealt", role=l10n.role_name(event.data["role"])))
        elif event.kind is EventKind.PACK_MATES:
            pack = event.data.get("pack", [])
            mates = ", ".join(state.seats[p].label() for p in pack)
            notes.append(l10n.msg("pack.mates", mates=mates))
        elif event.kind is EventKind.SEER_RESULT and event.target is not None:
            verdict = (
                "seer.result.wolf" if event.data["is_wolf"] else "seer.result.clear"
            )
            notes.append(l10n.msg(verdict, who=state.seats[event.target].label()))
    return tuple(notes)


def _default_name(index: int) -> str:
    pool = [
        "Alice", "Bob", "Carol", "Dave", "Erin", "Frank", "Grace", "Heidi",
        "Ivan", "Judy", "Mallory", "Niaj", "Olivia", "Peggy", "Rupert", "Sybil",
    ]
    return pool[index] if index < len(pool) else f"Player{index}"
