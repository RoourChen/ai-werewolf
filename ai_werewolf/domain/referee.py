"""The referee state machine.

The referee is a *pure* state machine: it deals roles, drives the phase
transitions, asks players for decisions through an injected ``decider``
callback and enforces the rules. It performs no I/O and imports nothing from
the server or player layers, so it can be driven by bots, humans or tests
identically.

Every decision is validated. An illegal action — wrong phase, wrong actor,
dead or hallucinated target — is repaired to a random legal choice, so a
misbehaving client can play badly but can never break the game.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ai_werewolf.domain.actions import TARGET_ACTIONS, Action, ActionKind
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.roles import Faction, Role
from ai_werewolf.domain.rules import (
    determine_winner,
    resolve_night_deaths,
    tally_lynch,
)
from ai_werewolf.domain.state import (
    DecisionRequest,
    GameConfig,
    GamePhase,
    GameState,
    PlayerView,
    build_view,
)
from ai_werewolf.i18n import L10n

Decider = Callable[[PlayerView, DecisionRequest], Action]
Observer = Callable[[GameEvent], None]

TRANSITIONS: dict[GamePhase, frozenset[GamePhase]] = {
    GamePhase.SETUP: frozenset({GamePhase.NIGHT}),
    GamePhase.NIGHT: frozenset({GamePhase.DAWN}),
    GamePhase.DAWN: frozenset({GamePhase.DISCUSSION, GamePhase.FINISHED}),
    GamePhase.DISCUSSION: frozenset({GamePhase.VOTING}),
    GamePhase.VOTING: frozenset({GamePhase.RESOLUTION}),
    GamePhase.RESOLUTION: frozenset({GamePhase.NIGHT, GamePhase.FINISHED}),
    GamePhase.FINISHED: frozenset(),
}


class RefereeError(Exception):
    """Base error for invalid referee operations."""


class InvalidTransition(RefereeError):
    """A phase transition violated the state machine."""


@dataclass
class _NightMemo:
    kill: int | None = None
    guarded: int | None = None
    healed: bool = False
    poisoned: int | None = None


class Referee:
    """Runs a single game of werewolf from deal to winner."""

    def __init__(
        self,
        config: GameConfig,
        decider: Decider,
        observer: Observer | None = None,
    ) -> None:
        self.config = config
        self.decider = decider
        self.observer = observer
        self.state = GameState.new(config)
        self.l10n = L10n(config.language)
        self._night_memo: _NightMemo = _NightMemo()

    # ------------------------------------------------------------------ run
    def run(self) -> GameState:
        self._setup()
        while self.state.phase is not GamePhase.FINISHED:
            self.state.day += 1
            self._night()
            self._dawn()
            if self.state.phase is GamePhase.FINISHED:
                break
            self._discussion()
            self._voting()
            self._resolution()
        return self.state

    # --------------------------------------------------------------- setup
    def _setup(self) -> None:
        roster = ", ".join(s.label() for s in self.state.seats)
        role_counts: dict[str, int] = {}
        for s in self.state.seats:
            role_counts[s.role.value] = role_counts.get(s.role.value, 0) + 1
        summary = ", ".join(
            f"{n}x {self.l10n.role_name(role)}" for role, n in sorted(role_counts.items())
        )
        self._emit(
            EventKind.GAME_STARTED,
            self.l10n.msg("game.started", roster=roster, roles=summary),
            data={"role_counts": role_counts, "seats": len(self.state.seats)},
        )
        for s in self.state.seats:
            self._emit(
                EventKind.ROLE_DEALT,
                self.l10n.msg("role.dealt", role=self.l10n.role_name(s.role)),
                data={"role": s.role.value},
                audience=frozenset({s.id}),
            )
        pack = [s.id for s in self.state.seats if s.role is Role.WEREWOLF]
        for wolf_id in pack:
            self._emit(
                EventKind.PACK_MATES,
                self.l10n.msg("pack.mates", mates=", ".join(self._who(p) for p in pack)),
                data={"pack": pack},
                audience=frozenset({wolf_id}),
            )
        self._transition(GamePhase.NIGHT)

    # --------------------------------------------------------------- night
    def _night(self) -> None:
        self._emit(
            EventKind.NIGHT_BEGINS,
            self.l10n.msg("night.begins", day=self.state.day),
        )
        kill = self._werewolf_kill()
        self._seer_inspect()
        guarded = self._guard_protect()
        healed, poisoned = self._witch_potions(kill)
        self._night_memo = _NightMemo(kill=kill, guarded=guarded, healed=healed, poisoned=poisoned)
        self._transition(GamePhase.DAWN)

    def _werewolf_kill(self) -> int | None:
        wolves = self.state.living_with_role(Role.WEREWOLF)
        if not wolves:
            return None
        legal = tuple(self.state.living_ids())
        tally: dict[int, int] = {}
        for wolf in wolves:
            action = self._ask(DecisionRequest(ActionKind.NIGHT_KILL, wolf.id, legal))
            assert action.target is not None
            tally[action.target] = tally.get(action.target, 0) + 1
        victim = _majority(tally, self.state.rng)
        self._emit(
            EventKind.WOLF_KILL,
            self.l10n.msg("wolf.kill", who=self._who(victim)),
            target=victim,
            audience=frozenset(w.id for w in wolves),
        )
        return victim

    def _seer_inspect(self) -> None:
        seers = self.state.living_with_role(Role.SEER)
        if not seers:
            return
        seer = seers[0]
        legal = tuple(self.state.living_others(seer.id))
        action = self._ask(DecisionRequest(ActionKind.NIGHT_INSPECT, seer.id, legal))
        assert action.target is not None
        is_wolf = self.state.seat(action.target).role is Role.WEREWOLF
        key = "seer.result.wolf" if is_wolf else "seer.result.clear"
        self._emit(
            EventKind.SEER_RESULT,
            self.l10n.msg(key, who=self._who(action.target)),
            target=action.target,
            data={"is_wolf": is_wolf},
            audience=frozenset({seer.id}),
        )

    def _guard_protect(self) -> int | None:
        guards = self.state.living_with_role(Role.GUARD)
        if not guards:
            return None
        guard = guards[0]
        legal = tuple(self.state.living_ids())
        action = self._ask(DecisionRequest(ActionKind.NIGHT_PROTECT, guard.id, legal))
        assert action.target is not None
        self._emit(
            EventKind.GUARD_PROTECT,
            self.l10n.msg("guard.protect", who=self._who(action.target)),
            target=action.target,
            audience=frozenset({guard.id}),
        )
        return action.target

    def _witch_potions(self, kill: int | None) -> tuple[bool, int | None]:
        witches = self.state.living_with_role(Role.WITCH)
        if not witches:
            return False, None
        witch = witches[0]
        can_heal = not self.state.witch_heal_used and kill is not None
        can_poison = not self.state.witch_poison_used
        if not (can_heal or can_poison):
            return False, None

        if kill is not None:
            self._emit(
                EventKind.WITCH_ATTACK,
                self.l10n.msg("witch.attack", who=self._who(kill)),
                target=kill,
                audience=frozenset({witch.id}),
            )
        request = DecisionRequest(
            ActionKind.WITCH_POTIONS,
            witch.id,
            legal_targets=tuple(self.state.living_others(witch.id)),
            can_heal=can_heal,
            can_poison=can_poison,
        )
        action = self._ask(request)

        healed = False
        if action.heal and can_heal and kill is not None:
            self.state.witch_heal_used = True
            healed = True
            self._emit(
                EventKind.WITCH_POTIONS,
                self.l10n.msg("witch.heal", who=self._who(kill)),
                target=kill,
                data={"potion": "heal"},
                audience=frozenset({witch.id}),
            )
        poisoned: int | None = None
        if action.poison is not None and can_poison:
            self.state.witch_poison_used = True
            poisoned = action.poison
            self._emit(
                EventKind.WITCH_POTIONS,
                self.l10n.msg("witch.poison", who=self._who(action.poison)),
                target=action.poison,
                data={"potion": "poison"},
                audience=frozenset({witch.id}),
            )
        return healed, poisoned

    # ---------------------------------------------------------------- dawn
    def _dawn(self) -> None:
        memo = self._night_memo
        deaths = resolve_night_deaths(
            self.state, memo.kill, memo.guarded, memo.healed, memo.poisoned
        )
        if not deaths:
            self._emit(EventKind.PEACEFUL_NIGHT, self.l10n.msg("peaceful.night"))
        else:
            self._emit(
                EventKind.DAWN,
                self.l10n.msg("dawn", day=self.state.day),
            )
            for pid, cause in deaths:
                self._kill_and_announce(pid, cause, "death")
        if self._check_winner():
            return
        self._transition(GamePhase.DISCUSSION)

    # ----------------------------------------------------------- discussion
    def _discussion(self) -> None:
        self._emit(
            EventKind.DISCUSSION_BEGINS,
            self.l10n.msg("discussion.begins", day=self.state.day),
        )
        for _ in range(self.config.discussion_rounds):
            for pid in self._speaking_order():
                action = self._ask(DecisionRequest(ActionKind.STATEMENT, pid))
                text = (action.text or "").strip()[:800] or "..."
                self._emit(
                    EventKind.STATEMENT,
                    f"{self._who(pid)}: {text}",
                    actor=pid,
                    data={"text": text},
                )
        self._transition(GamePhase.VOTING)

    def _speaking_order(self) -> list[int]:
        living = self.state.living_ids()
        if self.config.discussion_mode != "bidding":
            return living
        bids: dict[int, int] = {}
        for pid in living:
            action = self._ask(DecisionRequest(ActionKind.BID, pid))
            priority = max(0, min(10, action.priority))
            reason = (action.text or "").strip()[:200]
            bids[pid] = priority
            self._emit(
                EventKind.BID,
                self.l10n.msg("bid", who=self._who(pid), priority=priority),
                actor=pid,
                data={"priority": priority, "reason": reason},
            )
        return sorted(living, key=lambda p: (-bids[p], p))

    # --------------------------------------------------------------- voting
    def _voting(self) -> None:
        votes: dict[int, int] = {}
        for pid in self.state.living_ids():
            legal = tuple(self.state.living_others(pid))
            action = self._ask(DecisionRequest(ActionKind.VOTE, pid, legal))
            assert action.target is not None
            votes[pid] = action.target
            self._emit(
                EventKind.VOTE,
                self.l10n.msg("vote", who=self._who(pid), target=self._who(action.target)),
                actor=pid,
                target=action.target,
            )
        lynched = tally_lynch(votes)
        if lynched is None:
            self._emit(EventKind.NO_LYNCH, self.l10n.msg("no.lynch"))
        else:
            self._kill_and_announce(lynched, "lynched", "lynch")
        self._transition(GamePhase.RESOLUTION)

    def _resolution(self) -> None:
        if self._check_winner():
            return
        if self.state.day >= self.config.max_days:
            self._declare_stalemate()
            return
        self._transition(GamePhase.NIGHT)

    # ------------------------------------------------------------- helpers
    def _who(self, player_id: int) -> str:
        return self.state.seat(player_id).label()

    def _transition(self, target: GamePhase) -> None:
        if target not in TRANSITIONS[self.state.phase]:
            raise InvalidTransition(
                f"illegal transition {self.state.phase.value} -> {target.value}"
            )
        self.state.phase = target

    def _ask(self, request: DecisionRequest) -> Action:
        view = build_view(self.state, request.actor)
        return self._decide(view, request)

    def _decide(self, view: PlayerView, request: DecisionRequest) -> Action:
        try:
            action = self.decider(view, request)
        except Exception:  # noqa: BLE001 - a player error must never crash a game
            action = None
        return self._sanitize(action, request, view)

    def _sanitize(
        self, action: Action | None, request: DecisionRequest, view: PlayerView
    ) -> Action:
        if action is None or not isinstance(action, Action):
            return self._fallback(request, view)
        if action.kind is not request.kind or action.actor != request.actor:
            return self._fallback(request, view)
        if request.kind in TARGET_ACTIONS:
            if action.target not in request.legal_targets:
                return self._fallback(request, view)
            return action
        if request.kind is ActionKind.WITCH_POTIONS:
            heal = bool(action.heal) and request.can_heal
            poison = (
                action.poison
                if (
                    isinstance(action.poison, int)
                    and request.can_poison
                    and action.poison in request.legal_targets
                )
                else None
            )
            return Action(ActionKind.WITCH_POTIONS, request.actor, heal=heal, poison=poison)
        if request.kind is ActionKind.STATEMENT:
            return Action(ActionKind.STATEMENT, request.actor, text=action.text or "")
        if request.kind is ActionKind.BID:
            priority = action.priority if isinstance(action.priority, int) else 5
            return Action(
                ActionKind.BID,
                request.actor,
                text=(action.text or "")[:200],
                priority=max(0, min(10, priority)),
            )
        return action

    def _fallback(self, request: DecisionRequest, view: PlayerView) -> Action:
        if request.kind in TARGET_ACTIONS and request.legal_targets:
            return Action(
                request.kind,
                request.actor,
                target=view.rng.choice(list(request.legal_targets)),
            )
        if request.kind is ActionKind.WITCH_POTIONS:
            return Action(ActionKind.WITCH_POTIONS, request.actor)
        if request.kind is ActionKind.STATEMENT:
            return Action(ActionKind.STATEMENT, request.actor, text="...")
        if request.kind is ActionKind.BID:
            return Action(ActionKind.BID, request.actor, priority=5)
        return Action(request.kind, request.actor)

    def _kill_and_announce(self, player_id: int, cause: str, key: str) -> None:
        seat = self.state.seat(player_id)
        if not seat.alive:
            return
        self._kill(player_id, cause)
        text, data = self._death_text(player_id, key)
        kind = {
            "death": EventKind.DEATH,
            "lynch": EventKind.LYNCH,
            "hunter": EventKind.HUNTER_SHOT,
        }[key]
        self._emit(kind, text, target=player_id, data=data)
        self._hunter_chain(player_id)

    def _death_text(self, player_id: int, key: str) -> tuple[str, dict]:
        role = self.state.seat(player_id).role
        if self.config.reveal_role_on_death:
            return (
                self.l10n.msg(f"{key}.revealed", who=self._who(player_id), role=self.l10n.role_name(role)),
                {"role": role.value},
            )
        return self.l10n.msg(key, who=self._who(player_id)), {}

    def _hunter_chain(self, player_id: int) -> None:
        if self.state.seat(player_id).role is not Role.HUNTER:
            return
        targets = self.state.living_others(player_id)
        if not targets:
            return
        request = DecisionRequest(ActionKind.HUNTER_SHOT, player_id, tuple(targets))
        action = self._ask(request)
        assert action.target is not None
        self._kill(action.target, "shot by hunter")
        text, data = self._hunter_shot_text(player_id, action.target)
        self._emit(
            EventKind.HUNTER_SHOT,
            text,
            actor=player_id,
            target=action.target,
            data=data,
        )
        self._hunter_chain(action.target)

    def _hunter_shot_text(self, shooter: int, victim: int) -> tuple[str, dict]:
        role = self.state.seat(victim).role
        if self.config.reveal_role_on_death:
            return (
                self.l10n.msg(
                    "hunter.shot.revealed",
                    who=self._who(shooter),
                    target=self._who(victim),
                    role=self.l10n.role_name(role),
                ),
                {"role": role.value},
            )
        return (
            self.l10n.msg("hunter.shot", who=self._who(shooter), target=self._who(victim)),
            {},
        )

    def _kill(self, player_id: int, cause: str) -> None:
        seat = self.state.seat(player_id)
        seat.alive = False
        seat.death_day = self.state.day
        seat.death_cause = cause

    def _check_winner(self) -> bool:
        winner = determine_winner(self.state)
        if winner is None:
            return False
        self.state.winner = winner
        self._transition(GamePhase.FINISHED)
        self._emit(
            EventKind.GAME_OVER,
            self.l10n.msg("game.over", faction=self.l10n.faction_name(winner)),
            data={"winner": winner.value},
        )
        return True

    def _declare_stalemate(self) -> None:
        wolves = self.state.alive_in_faction(Faction.WEREWOLVES)
        village = self.state.alive_in_faction(Faction.VILLAGE)
        winner = Faction.WEREWOLVES if wolves > village else Faction.VILLAGE
        self.state.winner = winner
        self._transition(GamePhase.FINISHED)
        self._emit(
            EventKind.GAME_OVER,
            self.l10n.msg("game.over", faction=self.l10n.faction_name(winner)),
            data={"winner": winner.value, "stalemate": True},
        )

    def _emit(
        self,
        kind: EventKind,
        text: str = "",
        *,
        actor: int | None = None,
        target: int | None = None,
        data: dict | None = None,
        audience: frozenset[int] | None = None,
    ) -> GameEvent:
        event = GameEvent(
            kind=kind,
            day=self.state.day,
            phase=self.state.phase.value,
            text=text,
            actor=actor,
            target=target,
            data=data or {},
            audience=audience,
        )
        self.state.emit(event)
        if self.observer is not None:
            self.observer(event)
        return event


def _majority(tally: dict[int, int], rng: object) -> int:
    best = max(tally.values())
    top = sorted(k for k, v in tally.items() if v == best)
    return top[0] if len(top) == 1 else rng.choice(top)  # type: ignore[attr-defined]
