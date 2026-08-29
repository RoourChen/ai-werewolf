"""The self-play arena.

The arena runs many games under identical rules and aggregates the outcomes
into an :class:`ArenaReport`. It is how AI狼人杀 answers questions like *"do
LLM werewolves beat random villagers?"* or *"which model survives longest as
the seer?"* — every game is seeded, so a benchmark is reproducible.

Games are independent — each has its own seeded ``GameState`` — so the runner
can play them in parallel. Real-LLM benchmarks are IO-bound (waiting on the
provider) and scale almost linearly with worker count; the default stays
sequential for predictable behaviour and to keep shared-resource agents like
the deterministic :class:`~ai_werewolf.llm.mock.MockProvider` safe.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ai_werewolf.agents.base import Agent
from ai_werewolf.game.engine import AgentFactory, GameEngine
from ai_werewolf.game.roles import Faction, Role
from ai_werewolf.game.state import GameConfig, GameResult

ProgressHook = Callable[[int, int], None]  # (completed, total)


@dataclass
class ArenaReport:
    """Aggregated results of an arena run."""

    n_games: int = 0
    n_players: int = 0
    village_wins: int = 0
    werewolf_wins: int = 0
    total_days: int = 0
    # role -> [appearances, survivals]
    role_stats: dict[str, list[int]] = field(default_factory=dict)
    # agent name -> [games played, games won]
    agent_stats: dict[str, list[int]] = field(default_factory=dict)

    @property
    def village_win_rate(self) -> float:
        return self.village_wins / self.n_games if self.n_games else 0.0

    @property
    def werewolf_win_rate(self) -> float:
        return self.werewolf_wins / self.n_games if self.n_games else 0.0

    @property
    def avg_days(self) -> float:
        return self.total_days / self.n_games if self.n_games else 0.0

    def role_survival(self) -> dict[str, float]:
        return {
            role: (s / a if a else 0.0)
            for role, (a, s) in sorted(self.role_stats.items())
        }

    def agent_win_rate(self) -> dict[str, float]:
        return {
            name: (w / g if g else 0.0)
            for name, (g, w) in sorted(self.agent_stats.items())
        }

    def render(self) -> str:
        """A plain-text summary, suitable for logs or a terminal without rich."""
        lines = [
            f"Arena: {self.n_games} games, {self.n_players} players each",
            f"  Village win rate   : {self.village_win_rate:6.1%}",
            f"  Werewolf win rate  : {self.werewolf_win_rate:6.1%}",
            f"  Average game length: {self.avg_days:6.1f} days",
            "  Role survival:",
        ]
        for role, rate in self.role_survival().items():
            lines.append(f"    {role:<10}: {rate:6.1%}")
        if self.agent_stats:
            lines.append("  Agent win rate:")
            for name, rate in self.agent_win_rate().items():
                lines.append(f"    {name:<10}: {rate:6.1%}")
        return "\n".join(lines)


class Arena:
    """Runs a batch of seeded games with one agent configuration."""

    def __init__(
        self,
        n_players: int,
        agent_factory: AgentFactory,
        *,
        n_games: int = 50,
        base_seed: int = 0,
        discussion_rounds: int = 1,
    ) -> None:
        self.n_players = n_players
        self.agent_factory = agent_factory
        self.n_games = n_games
        self.base_seed = base_seed
        self.discussion_rounds = discussion_rounds

    def run(
        self,
        progress: ProgressHook | None = None,
        *,
        max_workers: int = 1,
    ) -> ArenaReport:
        """Play every seeded game and return the aggregated report.

        With ``max_workers == 1`` (the default) games run sequentially, exactly
        as before. With a higher value, independent games are dispatched onto a
        thread pool — ideal for real-LLM benchmarks where almost all of each
        game's wall-clock is spent waiting on the provider. Aggregation is
        commutative, so the report is bit-identical to the sequential run.

        When running in parallel, the ``agent_factory`` must be safe to call
        from multiple threads. Factories that return fresh agents on every call
        (the usual pattern) are safe automatically. Agents that share mutable
        state — notably :class:`~ai_werewolf.llm.mock.MockProvider`, whose RNG
        is not thread-safe — should be instantiated *per game* by the factory
        in parallel mode.
        """
        if max_workers <= 1:
            return self._run_sequential(progress)
        return self._run_parallel(progress, max_workers)

    # ------------------------------------------------------------- internals
    def _run_sequential(self, progress: ProgressHook | None) -> ArenaReport:
        report = ArenaReport(n_games=self.n_games, n_players=self.n_players)
        for i in range(self.n_games):
            result, seats = self._play(i)
            self._record(report, result, seats)
            if progress is not None:
                progress(i + 1, self.n_games)
        return report

    def _run_parallel(self, progress: ProgressHook | None, max_workers: int) -> ArenaReport:
        report = ArenaReport(n_games=self.n_games, n_players=self.n_players)
        lock = threading.Lock()
        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(self._play, i) for i in range(self.n_games)]
            for future in as_completed(futures):
                result, seats = future.result()
                with lock:
                    self._record(report, result, seats)
                    completed += 1
                    done = completed
                if progress is not None:
                    progress(done, self.n_games)
        return report

    def _play(self, index: int) -> tuple[GameResult, dict[int, Agent]]:
        """Play one seeded game and return (result, seats)."""
        config = GameConfig.standard(
            self.n_players,
            seed=self.base_seed + index,
            discussion_rounds=self.discussion_rounds,
        )
        seats: dict[int, Agent] = {}

        def recording_factory(pid: int, role: Role, _seats=seats) -> Agent:
            agent = self.agent_factory(pid, role)
            _seats[pid] = agent
            return agent

        result = GameEngine(config, recording_factory).run()
        return result, seats

    @staticmethod
    def _record(report: ArenaReport, result: GameResult, seats: dict[int, Agent]) -> None:
        report.total_days += result.days
        if result.winner is Faction.VILLAGE:
            report.village_wins += 1
        else:
            report.werewolf_wins += 1
        for player in result.players:
            stats = report.role_stats.setdefault(player.role.value, [0, 0])
            stats[0] += 1
            if player.alive:
                stats[1] += 1
            agent = seats.get(player.id)
            if agent is not None:
                a_stats = report.agent_stats.setdefault(agent.name, [0, 0])
                a_stats[0] += 1
                if player.faction is result.winner:
                    a_stats[1] += 1
