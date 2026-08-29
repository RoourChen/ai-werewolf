"""The human copilot.

Given a :class:`~ai_werewolf.domain.state.PlayerView`, the copilot estimates
how likely every other living player is to be a werewolf and recommends a
vote. The estimate is a transparent, explainable heuristic:

1. start from the prior ``unknown wolves / unknown players``;
2. pin 0 or 1 for anything *confirmed* (own role, packmates, seer results,
   revealed corpses);
3. nudge the rest with public voting behaviour;
4. renormalise so the probabilities sum to the wolves still at large.

It is deliberately model-free so it runs instantly and its reasons can be
shown to the human verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.roles import Faction, Role
from ai_werewolf.domain.state import PlayerView


@dataclass
class Suspicion:
    player_id: int
    name: str
    probability: float
    reasons: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int:
        return round(self.probability * 100)


@dataclass
class Advice:
    day: int
    suspicions: list[Suspicion]
    recommended_vote: int | None
    rationale: str


def advise(view: PlayerView) -> Advice:
    confirmed = _confirmed_factions(view)
    others = view.living_others()
    total_wolves = _total_wolves(view)
    dead_wolves = sum(
        1
        for pid, faction in confirmed.items()
        if faction is Faction.WEREWOLVES
        and pid in (s.id for s in view.seats if not s.alive)
    )
    known_living_wolves = [
        pid for pid in others if confirmed.get(pid) is Faction.WEREWOLVES
    ]
    unknown = [pid for pid in others if pid not in confirmed]
    unknown_wolves = max(0, total_wolves - dead_wolves - len(known_living_wolves))

    probabilities = _score_unknown(view, unknown, unknown_wolves)
    suspicions = _build(view, others, confirmed, probabilities, unknown_wolves)
    suspicions.sort(key=lambda s: s.probability, reverse=True)

    vote, rationale = _recommend(view, suspicions)
    return Advice(view.day, suspicions, vote, rationale)


def _score_unknown(
    view: PlayerView, unknown: list[int], unknown_wolves: int
) -> dict[int, float]:
    if not unknown or unknown_wolves <= 0:
        return dict.fromkeys(unknown, 0.0)
    weights = dict.fromkeys(unknown, 1.0)
    for day, target, role in _resolved_lynches(view):
        voters = _voters_for(view, day, target)
        wolf_lynched = role.faction is Faction.WEREWOLVES
        for pid in unknown:
            if pid in voters:
                weights[pid] *= 0.5 if wolf_lynched else 1.5
            else:
                weights[pid] *= 1.1 if wolf_lynched else 0.9
    total = sum(weights.values()) or 1.0
    return {pid: unknown_wolves * weights[pid] / total for pid in unknown}


def _build(
    view: PlayerView,
    others: list[int],
    confirmed: dict[int, Faction],
    probabilities: dict[int, float],
    unknown_wolves: int,
) -> list[Suspicion]:
    out: list[Suspicion] = []
    for pid in others:
        if confirmed.get(pid) is Faction.WEREWOLVES:
            out.append(Suspicion(pid, view.name(pid), 1.0, ["已确认是狼人"]))
        elif confirmed.get(pid) is Faction.VILLAGE:
            out.append(Suspicion(pid, view.name(pid), 0.0, ["已确认是好人"]))
        else:
            probability = min(0.97, max(0.03, probabilities.get(pid, 0.0)))
            out.append(Suspicion(pid, view.name(pid), probability, _reasons(view, pid)))
    if unknown_wolves == 0:
        for s in out:
            if "已确认是狼人" not in s.reasons:
                s.probability = 0.0
                s.reasons = ["狼人已全部定位"]
    return out


def _reasons(view: PlayerView, pid: int) -> list[str]:
    reasons: list[str] = []
    for day, target, role in _resolved_lynches(view):
        if pid in _voters_for(view, day, target):
            if role.faction is Faction.WEREWOLVES:
                reasons.append("投出过已确认狼人")
            else:
                reasons.append("投出过已确认好人")
    if not reasons:
        reasons.append("尚无明确信号，仅先验怀疑")
    return reasons


def _recommend(
    view: PlayerView, suspicions: list[Suspicion]
) -> tuple[int | None, str]:
    if not suspicions:
        return None, "没有可评估的存活玩家。"
    if view.my_role.faction is Faction.WEREWOLVES:
        mates = set(view.packmates)
        targets = [s for s in suspicions if s.player_id not in mates]
        targets.sort(key=lambda s: s.probability)
        if not targets:
            return None, "只剩狼队友存活，低调行事。"
        pick = targets[0]
        return pick.player_id, f"你是狼人：把票引向 {pick.name}（P{pick.player_id}）。"
    top = suspicions[0]
    if top.probability >= 0.999:
        return top.player_id, f"{top.name}（P{top.player_id}）已确认是狼人，果断投出。"
    if top.probability < 0.34:
        return top.player_id, f"暂无强信号，{top.name}（P{top.player_id}）以 {top.percent}% 暂居首位。"
    return top.player_id, f"{top.name}（P{top.player_id}）嫌疑最高（{top.percent}%），建议投出。"


def _confirmed_factions(view: PlayerView) -> dict[int, Faction]:
    confirmed: dict[int, Faction] = {view.me: view.my_role.faction}
    for mate in view.packmates:
        confirmed[mate] = Faction.WEREWOLVES
    for event in view.events:
        if event.kind is EventKind.SEER_RESULT and event.target is not None:
            confirmed[event.target] = (
                Faction.WEREWOLVES if event.data.get("is_wolf") else Faction.VILLAGE
            )
        elif event.kind in (EventKind.DEATH, EventKind.LYNCH, EventKind.HUNTER_SHOT):
            role = event.data.get("role")
            if role is not None and event.target is not None:
                confirmed[event.target] = Role(role).faction
    return confirmed


def _resolved_lynches(view: PlayerView) -> list[tuple[int, int, Role]]:
    out = []
    for event in view.events:
        if event.kind is EventKind.LYNCH and event.target is not None:
            role = event.data.get("role")
            if role is not None:
                out.append((event.day, event.target, Role(role)))
    return out


def _voters_for(view: PlayerView, day: int, target: int) -> set[int]:
    return {
        e.actor
        for e in view.events
        if e.kind is EventKind.VOTE
        and e.day == day
        and e.target == target
        and e.actor is not None
    }


def _total_wolves(view: PlayerView) -> int:
    for event in view.events:
        if event.kind is EventKind.GAME_STARTED:
            counts = event.data.get("role_counts", {})
            if counts:
                return int(counts.get(Role.WEREWOLF.value, 0))
    return max(1, len(view.seats) // 3)
