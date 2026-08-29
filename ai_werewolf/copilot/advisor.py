"""The human copilot.

Given the view of the game a *human* player can see, the advisor estimates how
likely every other living player is to be a werewolf and recommends a vote.

The estimate is a transparent, explainable heuristic — not a black box:

* it starts from the prior ``unknown werewolves / unknown players``;
* it hardens to 0 or 1 for anything the human has *confirmed* (a seer result, a
  revealed corpse, a known packmate);
* it nudges the rest using public voting behaviour — players who helped lynch a
  confirmed werewolf look cleaner, players who pushed a confirmed villager look
  worse;
* it renormalises so the suspicions sum to the number of werewolves still at
  large.

An optional LLM pass adds a natural-language second opinion that can read the
*statements* the heuristic ignores.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.game.events import EventType
from ai_werewolf.game.roles import Faction, Role
from ai_werewolf.game.state import PlayerView
from ai_werewolf.llm.provider import LLMProvider


@dataclass
class Suspicion:
    """The copilot's read on one living player."""

    player_id: int
    name: str
    score: float  # estimated probability of being a werewolf, 0..1
    reasons: list[str] = field(default_factory=list)

    @property
    def percent(self) -> int:
        return round(self.score * 100)


@dataclass
class Advice:
    """The copilot's full recommendation for the current turn."""

    day: int
    suspicions: list[Suspicion]  # living players, most suspicious first
    recommended_vote: int | None
    rationale: str
    llm_note: str | None = None


def advise(view: PlayerView, provider: LLMProvider | None = None) -> Advice:
    """Analyse ``view`` and return advice for the player who owns it."""
    confirmed = _confirmed_roles(view)
    others = [pid for pid in view.living_ids if pid != view.me_id]

    total_wolves = _total_wolves(view)
    dead_wolves = sum(
        1
        for pid, fac in confirmed.items()
        if fac is Faction.WEREWOLVES and not view.players[pid].alive
    )
    known_living_wolves = [
        pid for pid in others if confirmed.get(pid) is Faction.WEREWOLVES
    ]
    unknown = [pid for pid in others if pid not in confirmed]
    unknown_wolves = max(0, total_wolves - dead_wolves - len(known_living_wolves))

    scores = _score_unknowns(view, unknown, unknown_wolves)
    suspicions = _build_suspicions(view, others, confirmed, scores, unknown_wolves)
    suspicions.sort(key=lambda s: s.score, reverse=True)

    vote, rationale = _recommend(view, suspicions, confirmed)
    advice = Advice(view.day, suspicions, vote, rationale)
    if provider is not None:
        advice.llm_note = _llm_second_opinion(view, suspicions, provider)
    return advice


# --------------------------------------------------------------- heuristics
def _score_unknowns(
    view: PlayerView, unknown: list[int], unknown_wolves: int
) -> dict[int, float]:
    """Probability each unknown player is a werewolf, from voting behaviour."""
    if not unknown or unknown_wolves <= 0:
        return dict.fromkeys(unknown, 0.0)

    weight = dict.fromkeys(unknown, 1.0)
    for lynch_day, target, role in _confirmed_lynches(view):
        voters = _voters_for(view, lynch_day, target)
        wolf_lynched = role.faction is Faction.WEREWOLVES
        for pid in unknown:
            if pid in voters:
                weight[pid] *= 0.55 if wolf_lynched else 1.45
            else:
                weight[pid] *= 1.12 if wolf_lynched else 0.92

    total = sum(weight.values()) or 1.0
    return {pid: unknown_wolves * weight[pid] / total for pid in unknown}


def _build_suspicions(
    view: PlayerView,
    others: list[int],
    confirmed: dict[int, Faction],
    scores: dict[int, float],
    unknown_wolves: int,
) -> list[Suspicion]:
    out: list[Suspicion] = []
    for pid in others:
        name = view.name(pid)
        if confirmed.get(pid) is Faction.WEREWOLVES:
            out.append(Suspicion(pid, name, 1.0, ["confirmed werewolf"]))
        elif confirmed.get(pid) is Faction.VILLAGE:
            out.append(Suspicion(pid, name, 0.0, ["confirmed innocent"]))
        else:
            score = min(0.97, max(0.02, scores.get(pid, 0.0)))
            out.append(Suspicion(pid, name, score, _reasons(view, pid, score)))
    if unknown_wolves == 0:
        for s in out:
            if "confirmed werewolf" not in s.reasons:
                s.score, s.reasons = 0.0, ["all werewolves are accounted for"]
    return out


def _reasons(view: PlayerView, pid: int, score: float) -> list[str]:
    reasons: list[str] = []
    helped, pushed = 0, 0
    for lynch_day, target, role in _confirmed_lynches(view):
        if pid in _voters_for(view, lynch_day, target):
            if role.faction is Faction.WEREWOLVES:
                helped += 1
            else:
                pushed += 1
    if helped:
        reasons.append(f"voted to lynch a confirmed werewolf ({helped}x)")
    if pushed:
        reasons.append(f"voted to lynch a confirmed villager ({pushed}x)")
    if not reasons:
        reasons.append("no confirming signal yet — prior suspicion only")
    if score >= 0.6:
        reasons.append("above the table average — watch closely")
    return reasons


# ----------------------------------------------------------------- recommend
def _recommend(
    view: PlayerView,
    suspicions: list[Suspicion],
    confirmed: dict[int, Faction],
) -> tuple[int | None, str]:
    living_suspicions = [s for s in suspicions if s.score is not None]
    if not living_suspicions:
        return None, "No living players left to evaluate."

    if view.me_role.faction is Faction.WEREWOLVES:
        # A werewolf wants the village to burn its own. Aim at the most
        # village-trusted seat that is not a packmate.
        mates = set(view.teammates)
        targets = [s for s in living_suspicions if s.player_id not in mates]
        targets.sort(key=lambda s: s.score)
        if not targets:
            return None, "Only packmates remain alive — lie low."
        pick = targets[0]
        return pick.player_id, (
            f"As a werewolf, push the vote onto {pick.name} (P{pick.player_id}) "
            f"— the village trusts them, so removing them quietly helps the pack."
        )

    top = living_suspicions[0]
    if top.score >= 0.999:
        return top.player_id, (
            f"{top.name} (P{top.player_id}) is a confirmed werewolf. "
            f"Vote them without hesitation."
        )
    if top.score < 0.34:
        return top.player_id, (
            f"No strong read yet. {top.name} (P{top.player_id}) is the marginal lead at "
            f"{top.percent}% — consider stalling for more information."
        )
    return top.player_id, (
        f"{top.name} (P{top.player_id}) is your best werewolf candidate at "
        f"{top.percent}%. Lead the vote there unless discussion changes it."
    )


def _llm_second_opinion(
    view: PlayerView, suspicions: list[Suspicion], provider: LLMProvider
) -> str:
    """Ask a model to weigh the *statements* the heuristic cannot parse."""
    from ai_werewolf.prompts import templates as T

    ranking = "; ".join(
        f"{s.name} (P{s.player_id}) {s.percent}%" for s in suspicions
    )
    user = (
        f"{T.decision_request(view, T.KIND_VOTE, [s.player_id for s in suspicions])}\n\n"
        f"A statistical model ranks werewolf suspicion as: {ranking}.\n"
        "In 2-3 sentences, say whether the daytime statements support or "
        "contradict that ranking, and who you would watch. Plain text only."
    )
    messages = [
        {"role": "system", "content": T.system_message(view)},
        {"role": "user", "content": user},
    ]
    try:
        reply = provider.complete(messages).strip()
    except Exception as exc:  # noqa: BLE001
        return f"(LLM second opinion unavailable: {type(exc).__name__})"
    return reply or "(LLM returned nothing)"


# ------------------------------------------------------------------- helpers
def _confirmed_roles(view: PlayerView) -> dict[int, Faction]:
    """Every player whose faction the human can be *certain* of."""
    confirmed: dict[int, Faction] = {view.me_id: view.me_role.faction}
    for mate in view.teammates:
        confirmed[mate] = Faction.WEREWOLVES
    for e in view.events:
        if e.type is EventType.SEER_RESULT and e.target is not None:
            confirmed[e.target] = (
                Faction.WEREWOLVES if e.data.get("is_wolf") else Faction.VILLAGE
            )
        elif e.type in (
            EventType.DEATH_ANNOUNCED,
            EventType.LYNCH,
            EventType.HUNTER_SHOT,
        ):
            role = e.data.get("role")
            if role is not None and e.target is not None:
                confirmed[e.target] = Role(role).faction
    return confirmed


def _confirmed_lynches(view: PlayerView) -> list[tuple[int, int, Role]]:
    """(day, player, role) for every lynch whose victim's role is known."""
    out = []
    for e in view.events:
        if e.type is EventType.LYNCH and e.target is not None:
            role = e.data.get("role")
            if role is not None:
                out.append((e.day, e.target, Role(role)))
    return out


def _voters_for(view: PlayerView, day: int, target: int) -> set[int]:
    return {
        e.actor
        for e in view.events
        if e.type is EventType.VOTE_CAST
        and e.day == day
        and e.target == target
        and e.actor is not None
    }


def _total_wolves(view: PlayerView) -> int:
    for e in view.events:
        if e.type is EventType.GAME_START:
            counts = e.data.get("role_counts", {})
            if counts:
                return int(counts.get(Role.WEREWOLF.value, 0))
    # Fallback: the standard ~1-in-4 ratio.
    return max(1, round(len(view.players) / 4))
