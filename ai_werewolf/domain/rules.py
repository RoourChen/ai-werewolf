"""Pure rule functions.

These helpers encode the win condition, night-death resolution and vote
tallying. They are side-effect free and depend only on :class:`GameState`, so
they are trivially unit-testable.
"""

from __future__ import annotations

from ai_werewolf.domain.roles import Faction
from ai_werewolf.domain.state import GameState


def determine_winner(state: GameState) -> Faction | None:
    """Return the winning faction, or ``None`` if the game continues."""
    wolves = state.alive_in_faction(Faction.WEREWOLVES)
    village = state.alive_in_faction(Faction.VILLAGE)
    if wolves == 0:
        return Faction.VILLAGE
    if wolves >= village:
        return Faction.WEREWOLVES
    return None


def resolve_night_deaths(
    state: GameState,
    kill: int | None,
    guarded: int | None,
    healed: bool,
    poisoned: int | None,
) -> list[tuple[int, str]]:
    """Compute the night's deaths as ``(player_id, cause)`` pairs."""
    deaths: list[tuple[int, str]] = []
    if kill is not None and kill != guarded and not healed:
        deaths.append((kill, "killed"))
    if poisoned is not None and poisoned not in {d[0] for d in deaths}:
        deaths.append((poisoned, "poisoned"))
    return deaths


def tally_lynch(votes: dict[int, int]) -> int | None:
    """Return the strictly-most-voted player, or ``None`` on a tie/empty."""
    if not votes:
        return None
    counts: dict[int, int] = {}
    for target in votes.values():
        counts[target] = counts.get(target, 0) + 1
    best = max(counts.values())
    top = [target for target, n in counts.items() if n == best]
    return top[0] if len(top) == 1 else None
