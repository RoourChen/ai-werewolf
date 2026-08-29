"""Post-game vote analysis — new functionality built on the stable transcript
interface.

This module lives in ``extensions/`` on purpose. It never imports anything from
the game core; it consumes the *public* JSON transcript format produced by
:mod:`ai_werewolf.transcript` (``schema == "ai-werewolf.transcript/v1"``). New
features like this can be added here without touching the rules engine, exactly
as the architecture requires: core modules stay pure, extensions read and
report.
"""

from __future__ import annotations

from dataclasses import dataclass

_WEREWOLF = "werewolf"
_LYNCH = "lynch"
_VOTE_CAST = "vote_cast"


@dataclass(frozen=True)
class ResolvedLynch:
    """A lynch whose victim's role is revealed, plus who voted for it."""

    day: int
    target: int
    role: str
    voters: tuple[int, ...]

    @property
    def wolf_lynched(self) -> bool:
        return self.role == _WEREWOLF


@dataclass
class VoterRecord:
    """How well one player's votes tracked the truth (from a village lens)."""

    player_id: int
    name: str
    votes_cast: int = 0
    wolf_lynches: int = 0  # votes on a confirmed werewolf (good for village)
    village_lynches: int = 0  # votes on a confirmed villager (bad for village)

    @property
    def decided_votes(self) -> int:
        return self.wolf_lynches + self.village_lynches

    @property
    def accuracy(self) -> float:
        """Fraction of revealed-role lynch votes that hit a werewolf."""
        if self.decided_votes == 0:
            return 0.0
        return self.wolf_lynches / self.decided_votes


@dataclass
class VoteAnalysis:
    """The outcome of :func:`analyze_votes`."""

    lynches: list[ResolvedLynch]
    records: list[VoterRecord]  # ranked by accuracy, then by votes cast

    def render(self) -> str:
        lines = [
            f"Vote analysis — {len(self.lynches)} resolved lynch(es)",
            "",
            "  Resolved lynches:",
        ]
        for lynch in self.lynches:
            lines.append(
                f"    day {lynch.day}: P{lynch.target} ({lynch.role}) "
                f"<- {', '.join(f'P{v}' for v in lynch.voters) or 'no recorded votes'}"
            )
        lines.append("")
        lines.append("  Voter accuracy (werewolf lynches / decided votes):")
        for r in self.records:
            lines.append(
                f"    P{r.player_id} {r.name:<10} {r.accuracy:6.1%} "
                f"({r.wolf_lynches}/{r.decided_votes} decided, {r.votes_cast} total)"
            )
        return "\n".join(lines)


def analyze_votes(transcript: dict) -> VoteAnalysis:
    """Compute per-player vote accuracy from a saved transcript.

    ``transcript`` is the dict returned by
    :func:`ai_werewolf.transcript.loads`/:func:`ai_werewolf.transcript.load`.
    The analysis counts, for every lynch whose victim's role is revealed,
    which voters helped remove a werewolf and which pushed a villager.
    """
    names = {p["id"]: p["name"] for p in transcript.get("players", [])}
    events = transcript.get("events", [])

    lynches: list[ResolvedLynch] = []
    for e in events:
        if e.get("type") != _LYNCH:
            continue
        target = e.get("target")
        role = (e.get("data") or {}).get("role")
        if target is None or role is None:
            continue  # no role reveal -> nothing certain to score against
        day = e.get("day", 0)
        voters = tuple(
            v.get("actor")
            for v in events
            if v.get("type") == _VOTE_CAST
            and v.get("day") == day
            and v.get("target") == target
            and v.get("actor") is not None
        )
        lynches.append(ResolvedLynch(day=day, target=int(target), role=role, voters=voters))

    records: dict[int, VoterRecord] = {
        pid: VoterRecord(player_id=pid, name=name) for pid, name in names.items()
    }
    for lynch in lynches:
        for voter in lynch.voters:
            rec = records.setdefault(
                voter, VoterRecord(player_id=voter, name=names.get(voter, f"P{voter}"))
            )
            rec.votes_cast += 1
            if lynch.wolf_lynched:
                rec.wolf_lynches += 1
            else:
                rec.village_lynches += 1

    ordered = sorted(
        records.values(),
        key=lambda r: (-r.accuracy, -r.decided_votes, r.player_id),
    )
    return VoteAnalysis(lynches=lynches, records=ordered)
