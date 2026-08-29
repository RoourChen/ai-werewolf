"""Game state, configuration and per-player views.

``GameState`` is the mutable referee-side picture of a game. A
:class:`PlayerView` is the *filtered* picture handed to an agent: it contains
only what that player is allowed to know.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from ai_werewolf.game.events import Event, EventType
from ai_werewolf.game.roles import Faction, Role, standard_setup
from ai_werewolf.i18n import LANGUAGES, Translator


class Phase(str, Enum):
    SETUP = "setup"
    NIGHT = "night"
    DAY_DISCUSSION = "day_discussion"
    DAY_VOTE = "day_vote"
    GAME_OVER = "game_over"


@dataclass
class GameConfig:
    """Everything needed to start a reproducible game."""

    roles: list[Role]
    player_names: list[str] | None = None
    seed: int | None = None
    discussion_rounds: int = 1
    discussion_mode: str = "ordered"  # "ordered" (seating) or "bidding"
    max_days: int = 30
    reveal_role_on_death: bool = True
    lang: str = "en"

    @classmethod
    def standard(cls, n_players: int, **kwargs: object) -> GameConfig:
        """A balanced setup for ``n_players``. Extra kwargs pass through."""
        return cls(roles=standard_setup(n_players), **kwargs)  # type: ignore[arg-type]

    def __post_init__(self) -> None:
        if len(self.roles) < 4:
            raise ValueError("a game needs at least 4 roles")
        if self.player_names is not None and len(self.player_names) != len(self.roles):
            raise ValueError("player_names must match the number of roles")
        if self.lang not in LANGUAGES:
            raise ValueError(f"unknown language {self.lang!r}")
        if self.discussion_mode not in ("ordered", "bidding"):
            raise ValueError(f"unknown discussion_mode {self.discussion_mode!r}")


@dataclass
class Player:
    id: int
    name: str
    role: Role
    alive: bool = True
    death_day: int | None = None
    death_cause: str | None = None

    @property
    def faction(self) -> Faction:
        return self.role.faction

    def __str__(self) -> str:  # e.g. "Alice (P0)"
        return f"{self.name} (P{self.id})"


@dataclass
class GameState:
    """The referee's full, mutable view of a game."""

    players: list[Player]
    config: GameConfig
    rng: random.Random
    events: list[Event] = field(default_factory=list)
    day: int = 0
    phase: Phase = Phase.SETUP
    winner: Faction | None = None
    witch_heal_used: bool = False
    witch_poison_used: bool = False

    # ---- construction -----------------------------------------------------
    @classmethod
    def new(cls, config: GameConfig) -> GameState:
        """Deal roles and build a fresh game state."""
        rng = random.Random(config.seed)
        names = config.player_names or [_default_name(i) for i in range(len(config.roles))]
        roles = list(config.roles)
        rng.shuffle(roles)
        players = [Player(id=i, name=names[i], role=roles[i]) for i in range(len(roles))]
        return cls(players=players, config=config, rng=rng)

    # ---- queries ----------------------------------------------------------
    def player(self, player_id: int) -> Player:
        return self.players[player_id]

    def name(self, player_id: int) -> str:
        return self.players[player_id].name

    def living(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def living_ids(self) -> list[int]:
        return [p.id for p in self.players if p.alive]

    def living_with_role(self, role: Role) -> list[Player]:
        return [p for p in self.players if p.alive and p.role is role]

    def living_in_faction(self, faction: Faction) -> list[Player]:
        return [p for p in self.players if p.alive and p.faction is faction]

    @property
    def is_over(self) -> bool:
        return self.phase is Phase.GAME_OVER

    def emit(self, event: Event) -> Event:
        self.events.append(event)
        return event


@dataclass(frozen=True)
class PlayerInfo:
    """The public facts about one player, as seen by anyone."""

    id: int
    name: str
    alive: bool


@dataclass(frozen=True)
class PlayerView:
    """The slice of a game a single player is allowed to act on."""

    day: int
    phase: Phase
    me_id: int
    me_name: str
    me_role: Role
    players: tuple[PlayerInfo, ...]
    living_ids: tuple[int, ...]
    events: tuple[Event, ...]        # only events visible to this player
    private_notes: tuple[str, ...]   # human-readable secret knowledge
    lang: str                        # language for prompts and rendering
    rng: random.Random

    def name(self, player_id: int) -> str:
        return self.players[player_id].name

    def others_alive(self) -> list[int]:
        """Living players other than me — the usual set of legal targets."""
        return [pid for pid in self.living_ids if pid != self.me_id]

    @property
    def teammates(self) -> tuple[int, ...]:
        """Known werewolf packmates (only populated for werewolves)."""
        for event in self.events:
            if event.type is EventType.PACK_REVEAL:
                return tuple(event.data.get("pack", ()))
        return ()


@dataclass
class GameResult:
    """The outcome of a finished game."""

    winner: Faction
    days: int
    players: list[Player]
    events: list[Event]

    def survivors(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def won(self, player: Player) -> bool:
        return player.faction is self.winner


def build_view(state: GameState, player_id: int, phase: Phase | None = None) -> PlayerView:
    """Project ``state`` down to what ``player_id`` may legally see."""
    me = state.player(player_id)
    visible = tuple(e for e in state.events if e.visible(player_id))
    notes = _private_notes(state, visible, state.config.lang)
    return PlayerView(
        day=state.day,
        phase=phase or state.phase,
        me_id=me.id,
        me_name=me.name,
        me_role=me.role,
        players=tuple(PlayerInfo(p.id, p.name, p.alive) for p in state.players),
        living_ids=tuple(state.living_ids()),
        events=visible,
        private_notes=notes,
        lang=state.config.lang,
        rng=state.rng,
    )


def _private_notes(
    state: GameState, visible: tuple[Event, ...], lang: str
) -> tuple[str, ...]:
    """Turn a player's private events into readable, localised reminders."""
    tr = Translator(lang)
    notes: list[str] = []
    for event in visible:
        if event.type is EventType.ROLE_ASSIGNED:
            notes.append(tr.t("note_role", role=tr.role_name(event.data["role"])))
        elif event.type is EventType.PACK_REVEAL:
            pack = event.data.get("pack", [])
            mates = [f"{state.name(p)} (P{p})" for p in pack]
            joined = ", ".join(mates) if mates else tr.t("note_pack_alone")
            notes.append(tr.t("note_pack", mates=joined))
        elif event.type is EventType.SEER_RESULT and event.target is not None:
            verdict = tr.t(
                "note_verdict_wolf" if event.data["is_wolf"] else "note_verdict_clear"
            )
            who = f"{state.name(event.target)} (P{event.target})"
            notes.append(tr.t("note_seer", day=event.day, who=who, verdict=verdict))
    return tuple(notes)


def _default_name(index: int) -> str:
    pool = [
        "Alice", "Bob", "Carol", "Dave", "Erin", "Frank", "Grace", "Heidi",
        "Ivan", "Judy", "Mallory", "Niaj", "Olivia", "Peggy", "Rupert", "Sybil",
    ]
    return pool[index] if index < len(pool) else f"Player{index}"
