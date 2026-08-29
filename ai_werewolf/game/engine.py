"""The werewolf referee.

The engine is intentionally a *pure rules machine*: it deals roles, runs the
night/day cycle, validates every agent decision and decides the winner. It
never reasons about the game — that is the agents' job. Any decision an agent
returns that is illegal is quietly replaced with a random legal one, so a
buggy or hallucinating agent can never corrupt a game.

All player-facing event text is produced through a
:class:`~ai_werewolf.i18n.Translator`, so a game can be run in any supported
language.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ai_werewolf.game.events import Event, EventType
from ai_werewolf.game.roles import Faction, Role
from ai_werewolf.game.state import (
    GameConfig,
    GameResult,
    GameState,
    Phase,
    Player,
    PlayerView,
    build_view,
)
from ai_werewolf.i18n import Translator

if TYPE_CHECKING:
    from ai_werewolf.agents.base import Agent

AgentFactory = Callable[[int, Role], "Agent"]
Observer = Callable[[Event], None]


class GameEngine:
    """Runs a single game of werewolf from deal to winner."""

    def __init__(
        self,
        config: GameConfig,
        agent_factory: AgentFactory,
        observer: Observer | None = None,
    ) -> None:
        self.config = config
        self.agent_factory = agent_factory
        self.observer = observer
        self.state = GameState.new(config)
        self.tr = Translator(config.lang)
        self.agents: dict[int, Agent] = {}

    # ------------------------------------------------------------------ run
    def run(self) -> GameResult:
        """Play the whole game and return its result."""
        self._setup()
        while not self.state.is_over:
            self.state.day += 1
            if self.state.day > self.config.max_days:
                self._declare_by_headcount()
                break
            self._night_phase()
            if self._check_winner():
                break
            self._day_phase()
            if self._check_winner():
                break
        return GameResult(
            winner=self.state.winner or Faction.VILLAGE,
            days=self.state.day,
            players=self.state.players,
            events=self.state.events,
        )

    # --------------------------------------------------------------- setup
    def _setup(self) -> None:
        s = self.state
        roster = ", ".join(str(p) for p in s.players)
        role_counts = _role_count_map(s.players)
        summary = ", ".join(
            f"{n}x {self.tr.role_name(role)}"
            for role, n in sorted(role_counts.items())
        )
        self._emit(Event(
            EventType.GAME_START, 0, "setup",
            self.tr.t("game_start", roster=roster, roles=summary),
            data={"role_counts": role_counts, "n_players": len(s.players)},
        ))
        for p in s.players:
            self._emit(Event(
                EventType.ROLE_ASSIGNED, 0, "setup",
                self.tr.t("role_assigned", role=self.tr.role_name(p.role)),
                public=False, visible_to=frozenset({p.id}),
                data={"role": p.role.value},
            ))
        pack = [p.id for p in s.players if p.role is Role.WEREWOLF]
        for wolf_id in pack:
            self._emit(Event(
                EventType.PACK_REVEAL, 0, "setup",
                self.tr.t("pack_reveal"),
                public=False, visible_to=frozenset({wolf_id}),
                data={"pack": pack},
            ))
        self.agents = {p.id: self.agent_factory(p.id, p.role) for p in s.players}

    # --------------------------------------------------------------- night
    def _night_phase(self) -> None:
        s = self.state
        s.phase = Phase.NIGHT
        self._emit(Event(
            EventType.NIGHT_FALLS, s.day, "night",
            self.tr.t("night_falls", day=s.day),
        ))

        victim = self._werewolf_target()
        self._seer_inspection()
        protected = self._doctor_protection()
        healed, poisoned = self._witch_action(victim)

        # Collect the night's deaths, then announce them together.
        deaths: list[tuple[int, str]] = []
        if victim is not None and victim != protected and not healed:
            deaths.append((victim, "killed by werewolves"))
        if poisoned is not None and poisoned not in {d[0] for d in deaths}:
            deaths.append((poisoned, "poisoned by the Witch"))

        if not deaths:
            saved = victim is not None and (victim == protected or healed)
            self._emit(Event(
                EventType.QUIET_NIGHT, s.day, "night",
                self.tr.t("quiet_night_saved" if saved else "quiet_night"),
            ))
            return
        self._announce_deaths(deaths)

    def _announce_deaths(self, deaths: list[tuple[int, str]]) -> None:
        """Mark each night death, announce it, and fire any Hunter shots."""
        s = self.state
        for pid, cause in deaths:
            if not s.player(pid).alive:
                continue  # already taken by an earlier death this night
            self._kill(pid, cause)
            role_name, data = self._reveal(pid)
            if role_name is not None:
                text = self.tr.t(
                    "death_announced_revealed", who=self._who(pid), role=role_name
                )
            else:
                text = self.tr.t("death_announced", who=self._who(pid))
            self._emit(Event(
                EventType.DEATH_ANNOUNCED, s.day, "night", text,
                target=pid, data=data,
            ))
            self._process_hunter(pid)

    def _werewolf_target(self) -> int | None:
        s = self.state
        wolves = s.living_with_role(Role.WEREWOLF)
        if not wolves:
            return None
        legal = s.living_ids()
        tally: dict[int, int] = {}
        for wolf in wolves:
            choice = self._ask_target(wolf, "kill", legal)
            tally[choice] = tally.get(choice, 0) + 1
        victim = _argmax_random(tally, s.rng)
        pack_ids = frozenset(w.id for w in wolves)
        self._emit(Event(
            EventType.WEREWOLF_TARGET, s.day, "night",
            self.tr.t("werewolf_target", who=self._who(victim)),
            target=victim, public=False, visible_to=pack_ids,
        ))
        return victim

    def _seer_inspection(self) -> None:
        s = self.state
        seers = s.living_with_role(Role.SEER)
        if not seers:
            return
        seer = seers[0]
        legal = [pid for pid in s.living_ids() if pid != seer.id]
        target = self._ask_target(seer, "inspect", legal)
        is_wolf = s.player(target).role is Role.WEREWOLF
        verdict = self.tr.t("verdict_wolf" if is_wolf else "verdict_clear")
        self._emit(Event(
            EventType.SEER_RESULT, s.day, "night",
            self.tr.t("seer_result", who=self._who(target), verdict=verdict),
            target=target, public=False, visible_to=frozenset({seer.id}),
            data={"is_wolf": is_wolf},
        ))

    def _doctor_protection(self) -> int | None:
        s = self.state
        doctors = s.living_with_role(Role.DOCTOR)
        if not doctors:
            return None
        doctor = doctors[0]
        target = self._ask_target(doctor, "protect", s.living_ids())
        self._emit(Event(
            EventType.DOCTOR_PROTECT, s.day, "night",
            self.tr.t("doctor_protect", who=self._who(target)),
            target=target, public=False, visible_to=frozenset({doctor.id}),
        ))
        return target

    def _witch_action(self, victim: int | None) -> tuple[bool, int | None]:
        """Run the Witch's night, returning (victim healed?, poison target)."""
        s = self.state
        witches = s.living_with_role(Role.WITCH)
        if not witches:
            return False, None
        witch = witches[0]
        can_heal = not s.witch_heal_used and victim is not None
        can_poison = not s.witch_poison_used
        if not (can_heal or can_poison):
            return False, None

        if victim is not None:
            self._emit(Event(
                EventType.WITCH_NIGHT_INFO, s.day, "night",
                self.tr.t("witch_night_info", who=self._who(victim)),
                target=victim, public=False, visible_to=frozenset({witch.id}),
            ))
        view = build_view(s, witch.id, Phase.NIGHT)
        try:
            heal, poison = self.agents[witch.id].witch_turn(
                view, victim, can_heal, can_poison
            )
        except Exception:  # noqa: BLE001 - an agent error must not crash a game
            heal, poison = False, None

        healed = False
        if heal and can_heal and victim is not None:
            s.witch_heal_used = True
            healed = True
            self._emit(Event(
                EventType.WITCH_POTION, s.day, "night",
                self.tr.t("witch_heal", who=self._who(victim)),
                target=victim, public=False, visible_to=frozenset({witch.id}),
                data={"potion": "heal"},
            ))
        poison_target: int | None = None
        if (
            can_poison
            and isinstance(poison, int)
            and poison in s.living_ids()
            and poison != witch.id
        ):
            s.witch_poison_used = True
            poison_target = poison
            self._emit(Event(
                EventType.WITCH_POTION, s.day, "night",
                self.tr.t("witch_poison", who=self._who(poison)),
                target=poison, public=False, visible_to=frozenset({witch.id}),
                data={"potion": "poison"},
            ))
        return healed, poison_target

    # ----------------------------------------------------------------- day
    def _day_phase(self) -> None:
        s = self.state
        s.phase = Phase.DAY_DISCUSSION
        self._emit(Event(
            EventType.DAY_BREAKS, s.day, "day",
            self.tr.t("day_breaks", day=s.day),
        ))
        for _ in range(self.config.discussion_rounds):
            for pid in self._speaking_order():
                self._collect_statement(pid)

        s.phase = Phase.DAY_VOTE
        tally: dict[int, int] = {}
        for pid in s.living_ids():
            choice = self._collect_vote(pid)
            tally[choice] = tally.get(choice, 0) + 1

        lynched = _plurality_or_none(tally)
        if lynched is None:
            self._emit(Event(
                EventType.NO_LYNCH, s.day, "day", self.tr.t("no_lynch"),
            ))
        else:
            self._kill(lynched, "lynched by the village")
            role_name, data = self._reveal(lynched)
            if role_name is not None:
                text = self.tr.t(
                    "lynch_revealed", who=self._who(lynched), role=role_name
                )
            else:
                text = self.tr.t("lynch", who=self._who(lynched))
            self._emit(Event(
                EventType.LYNCH, s.day, "day", text, target=lynched, data=data,
            ))
            self._process_hunter(lynched)

    def _speaking_order(self) -> list[int]:
        """Living players in the order they speak this round.

        In ``ordered`` mode this is seating order. In ``bidding`` mode every
        agent bids for the floor; the bids (priority + a public reason) are
        emitted as events, and speakers are seated highest-bid-first. Surfacing
        the bids keeps the round explainable — an eager bid with a thin reason
        is itself a signal the copilot and other agents can read.
        """
        s = self.state
        living = s.living_ids()
        if self.config.discussion_mode != "bidding":
            return living

        bids: dict[int, int] = {}
        for pid in living:
            view = build_view(s, pid, Phase.DAY_DISCUSSION)
            try:
                priority, reason = self.agents[pid].bid(view)
            except Exception:  # noqa: BLE001 - an agent error must not crash a game
                priority, reason = 5, ""
            priority = max(0, min(10, priority if isinstance(priority, int) else 5))
            reason = str(reason).strip()[:200]
            bids[pid] = priority
            if reason:
                text = self.tr.t(
                    "speak_bid_reasoned", who=self._who(pid),
                    priority=priority, reason=reason,
                )
            else:
                text = self.tr.t("speak_bid", who=self._who(pid), priority=priority)
            self._emit(Event(
                EventType.SPEAK_BID, s.day, "day", text,
                actor=pid, data={"priority": priority, "reason": reason},
            ))
        return sorted(living, key=lambda p: (-bids[p], p))

    def _collect_statement(self, player_id: int) -> None:
        s = self.state
        view = build_view(s, player_id, Phase.DAY_DISCUSSION)
        try:
            text = self.agents[player_id].speak(view).strip()
        except Exception as exc:  # noqa: BLE001 - agents must never crash a game
            text = f"(stays quiet — {type(exc).__name__})"
        text = text or "(says nothing)"
        if len(text) > 800:
            text = text[:797] + "..."
        self._emit(Event(
            EventType.STATEMENT, s.day, "day",
            f"{self._who(player_id)}: {text}",
            actor=player_id, data={"statement": text},
        ))

    def _collect_vote(self, player_id: int) -> int:
        s = self.state
        legal = [pid for pid in s.living_ids() if pid != player_id]
        view = build_view(s, player_id, Phase.DAY_VOTE)
        choice = self._validate(self.agents[player_id].vote, view, legal)
        self._emit_reasoning(player_id, "vote")
        self._emit(Event(
            EventType.VOTE_CAST, s.day, "day",
            self.tr.t("vote_cast", voter=self._who(player_id), target=self._who(choice)),
            actor=player_id, target=choice,
        ))
        return choice

    # ------------------------------------------------------------- helpers
    def _who(self, player_id: int) -> str:
        """A player's display name — ``Name (P0)`` — the same in every language."""
        return f"{self.state.name(player_id)} (P{player_id})"

    def _ask_target(self, actor: Player, action: str, legal: list[int]) -> int:
        view = build_view(self.state, actor.id, Phase.NIGHT)
        choice = self._validate(self.agents[actor.id].night_action, view, legal)
        self._emit_reasoning(actor.id, action)
        return choice

    def _emit_reasoning(self, player_id: int, decision: str) -> None:
        """Surface an agent's stated reasoning for its latest decision.

        Private to the actor (visible_to = {player_id}), so other agents'
        views are unchanged. The point is the post-game transcript: a saved
        game now records *why* each LLM-driven decision was made, not just
        *what* was decided. Agents that don't keep a reasoning trace return
        ``None`` from :meth:`Agent.last_reasoning` and nothing is emitted.
        """
        raw = self.agents[player_id].last_reasoning()
        reasoning = (raw or "").strip()
        if not reasoning:
            return
        self._emit(Event(
            EventType.AGENT_REASONING,
            self.state.day,
            self.state.phase.value,
            self.tr.t(
                "agent_reasoning",
                who=self._who(player_id),
                decision=decision,
                reasoning=reasoning,
            ),
            actor=player_id,
            public=False,
            visible_to=frozenset({player_id}),
            data={"decision": decision, "reasoning": reasoning},
        ))

    def _validate(
        self,
        decide: Callable[[PlayerView], int],
        view: PlayerView,
        legal: list[int],
    ) -> int:
        """Run an agent decision, falling back to a random legal target."""
        try:
            choice = decide(view)
        except Exception:  # noqa: BLE001 - never let an agent crash the game
            choice = -1
        if choice not in legal:
            choice = view.rng.choice(legal)
        return choice

    def _kill(self, player_id: int, cause: str) -> None:
        player = self.state.player(player_id)
        player.alive = False
        player.death_day = self.state.day
        player.death_cause = cause

    def _reveal(self, player_id: int) -> tuple[str | None, dict]:
        """Role reveal for a death event: (localised role name, event data).

        Returns ``(None, {})`` when role reveal on death is disabled.
        """
        if not self.config.reveal_role_on_death:
            return None, {}
        role = self.state.player(player_id).role
        return self.tr.role_name(role), {"role": role.value}

    def _process_hunter(self, player_id: int) -> None:
        """If the player who just died is the Hunter, fire their revenge shot.

        The shot is resolved immediately and may itself kill another Hunter, so
        the method recurses. Win conditions are re-checked by the phase loop
        once the whole chain has resolved.
        """
        s = self.state
        if s.player(player_id).role is not Role.HUNTER:
            return
        targets = s.living_ids()
        if not targets:
            return
        view = build_view(s, player_id, s.phase)
        try:
            choice = self.agents[player_id].dying_shot(view)
        except Exception:  # noqa: BLE001 - an agent error must not crash a game
            choice = -1
        if choice not in targets:
            choice = s.rng.choice(targets)
        self._emit_reasoning(player_id, "shoot")
        self._kill(choice, "shot by the dying Hunter")
        role_name, data = self._reveal(choice)
        if role_name is not None:
            text = self.tr.t(
                "hunter_shot_revealed",
                who=self._who(player_id), target=self._who(choice), role=role_name,
            )
        else:
            text = self.tr.t(
                "hunter_shot", who=self._who(player_id), target=self._who(choice)
            )
        self._emit(Event(
            EventType.HUNTER_SHOT, s.day, s.phase.value, text,
            actor=player_id, target=choice, data=data,
        ))
        self._process_hunter(choice)  # a shot Hunter shoots back

    def _check_winner(self) -> bool:
        winner = _winner(self.state)
        if winner is None:
            return False
        self.state.winner = winner
        self.state.phase = Phase.GAME_OVER
        self._emit(Event(
            EventType.GAME_OVER, self.state.day, "end",
            self.tr.t(
                "game_over",
                day=self.state.day, faction=self.tr.faction_label(winner),
            ),
            data={"winner": winner.value},
        ))
        return True

    def _declare_by_headcount(self) -> None:
        s = self.state
        wolves = len(s.living_in_faction(Faction.WEREWOLVES))
        village = len(s.living_in_faction(Faction.VILLAGE))
        s.winner = Faction.WEREWOLVES if wolves > village else Faction.VILLAGE
        s.phase = Phase.GAME_OVER
        self._emit(Event(
            EventType.GAME_OVER, s.day, "end",
            self.tr.t("game_over_headcount", faction=self.tr.faction_label(s.winner)),
            data={"winner": s.winner.value},
        ))

    def _emit(self, event: Event) -> None:
        self.state.emit(event)
        if self.observer is not None:
            self.observer(event)


# ---------------------------------------------------------------- functions
def _winner(state: GameState) -> Faction | None:
    """Return the winning faction, or ``None`` if the game continues."""
    wolves = len(state.living_in_faction(Faction.WEREWOLVES))
    village = len(state.living_in_faction(Faction.VILLAGE))
    if wolves == 0:
        return Faction.VILLAGE
    if wolves >= village:
        return Faction.WEREWOLVES
    return None


def _argmax_random(tally: dict[int, int], rng: object) -> int:
    """Key with the highest count; ties broken with ``rng``."""
    best = max(tally.values())
    top = sorted(k for k, v in tally.items() if v == best)
    return top[0] if len(top) == 1 else rng.choice(top)  # type: ignore[attr-defined]


def _plurality_or_none(tally: dict[int, int]) -> int | None:
    """Key with a strict plurality, or ``None`` on a tie or empty tally."""
    if not tally:
        return None
    best = max(tally.values())
    top = [k for k, v in tally.items() if v == best]
    return top[0] if len(top) == 1 else None


def _role_count_map(players: list[Player]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in players:
        counts[p.role.value] = counts.get(p.role.value, 0) + 1
    return counts
