"""Rank agents against each other in the arena.

A leaderboard answers *"which agent plays werewolf best?"* in a way that is
actually fair. Each competitor is measured under identical, seeded conditions:

* it plays the **werewolves** against a fixed reference village, and
* it plays the **village** against fixed reference werewolves.

Its score is the average of the two win rates. Because both arenas reuse the
same seeds for every competitor, the ranking is reproducible and the only thing
that varies between competitors is the agent itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ai_werewolf.agents.base import Agent
from ai_werewolf.arena.runner import Arena, ProgressHook
from ai_werewolf.game.roles import Role

#: A competitor is a per-player agent builder — faction-agnostic, so the same
#: agent can be slotted into either side of a match-up.
AgentBuilder = Callable[[int], Agent]


@dataclass
class LeaderboardEntry:
    """One competitor's results across both sides of the table."""

    name: str
    games_per_side: int
    werewolf_wins: int  # wins while playing the werewolves
    village_wins: int   # wins while playing the village

    @property
    def werewolf_win_rate(self) -> float:
        return self.werewolf_wins / self.games_per_side if self.games_per_side else 0.0

    @property
    def village_win_rate(self) -> float:
        return self.village_wins / self.games_per_side if self.games_per_side else 0.0

    @property
    def score(self) -> float:
        """Overall skill: the mean of both win rates."""
        return (self.werewolf_win_rate + self.village_win_rate) / 2


@dataclass
class LeaderboardReport:
    """A ranked comparison of every competitor."""

    entries: list[LeaderboardEntry]  # best first
    n_players: int
    games_per_side: int
    reference: str

    def render(self) -> str:
        lines = [
            f"Leaderboard — {self.n_players} players, "
            f"{self.games_per_side} games/side vs reference '{self.reference}'",
        ]
        for rank, e in enumerate(self.entries, 1):
            lines.append(
                f"  {rank}. {e.name:<14} score {e.score:6.1%}  "
                f"(as werewolf {e.werewolf_win_rate:6.1%}, "
                f"as village {e.village_win_rate:6.1%})"
            )
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """A Markdown table, ready to paste into a README or an issue."""
        rows = [
            "| Rank | Agent | Score | Win rate as werewolf | Win rate as village |",
            "|-----:|-------|------:|---------------------:|--------------------:|",
        ]
        for rank, e in enumerate(self.entries, 1):
            rows.append(
                f"| {rank} | {e.name} | {e.score:.1%} | "
                f"{e.werewolf_win_rate:.1%} | {e.village_win_rate:.1%} |"
            )
        return "\n".join(rows)


class Leaderboard:
    """Runs every competitor through both sides of a fixed reference match-up."""

    def __init__(
        self,
        n_players: int,
        competitors: dict[str, AgentBuilder],
        reference: AgentBuilder,
        *,
        reference_name: str = "random",
        n_games: int = 30,
        base_seed: int = 0,
        discussion_rounds: int = 1,
    ) -> None:
        if not competitors:
            raise ValueError("a leaderboard needs at least one competitor")
        self.n_players = n_players
        self.competitors = competitors
        self.reference = reference
        self.reference_name = reference_name
        self.n_games = n_games
        self.base_seed = base_seed
        self.discussion_rounds = discussion_rounds

    def run(
        self,
        progress: ProgressHook | None = None,
        *,
        max_workers: int = 1,
    ) -> LeaderboardReport:
        entries: list[LeaderboardEntry] = []
        for done, (name, builder) in enumerate(self.competitors.items(), 1):
            as_wolf = self._arena(builder, self.reference).run(max_workers=max_workers)
            as_village = self._arena(self.reference, builder).run(max_workers=max_workers)
            entries.append(LeaderboardEntry(
                name=name,
                games_per_side=self.n_games,
                werewolf_wins=as_wolf.werewolf_wins,
                village_wins=as_village.village_wins,
            ))
            if progress is not None:
                progress(done, len(self.competitors))
        entries.sort(key=lambda e: e.score, reverse=True)
        return LeaderboardReport(
            entries=entries,
            n_players=self.n_players,
            games_per_side=self.n_games,
            reference=self.reference_name,
        )

    def _arena(self, wolves: AgentBuilder, village: AgentBuilder) -> Arena:
        def factory(player_id: int, role: Role) -> Agent:
            builder = wolves if role is Role.WEREWOLF else village
            return builder(player_id)

        return Arena(
            self.n_players,
            factory,
            n_games=self.n_games,
            base_seed=self.base_seed,
            discussion_rounds=self.discussion_rounds,
        )
