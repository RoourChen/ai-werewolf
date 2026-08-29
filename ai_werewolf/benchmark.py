"""Batch evaluation of bot policies.

Runs many seeded games with one bot policy and aggregates faction win rates,
role survival, agent win rates and a per-player ledger. This is the "模型评测"
surface: the same primitives a human room uses, replayed in bulk.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ai_werewolf.ai.provider import Provider
from ai_werewolf.domain.actions import Action
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import Faction, build_roster
from ai_werewolf.domain.state import DecisionRequest, GameConfig, PlayerView
from ai_werewolf.players.llm_bot import LLMBot
from ai_werewolf.players.random_bot import RandomBot
from ai_werewolf.stats.ledger import StatsLedger


@dataclass
class ArenaReport:
    n_games: int = 0
    n_players: int = 0
    village_wins: int = 0
    werewolf_wins: int = 0
    total_days: int = 0
    role_stats: dict[str, list[int]] = field(default_factory=dict)  # role -> [games, survivals]
    agent_stats: dict[str, list[int]] = field(default_factory=dict)  # policy -> [games, wins]
    ledger: StatsLedger = field(default_factory=StatsLedger)

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
            role: (s / g if g else 0.0)
            for role, (g, s) in sorted(self.role_stats.items())
        }

    def agent_win_rate(self) -> dict[str, float]:
        return {
            policy: (w / g if g else 0.0)
            for policy, (g, w) in sorted(self.agent_stats.items())
        }

    def render(self) -> str:
        lines = [
            f"竞技场：{self.n_games} 局，每局 {self.n_players} 人",
            f"  村民阵营胜率 : {self.village_win_rate:6.1%}",
            f"  狼人阵营胜率 : {self.werewolf_win_rate:6.1%}",
            f"  平均局数     : {self.avg_days:6.1f} 天",
            "  角色存活率：",
        ]
        for role, rate in self.role_survival().items():
            lines.append(f"    {role:<10}: {rate:6.1%}")
        lines.append("  Agent 胜率：")
        for policy, rate in self.agent_win_rate().items():
            lines.append(f"    {policy:<10}: {rate:6.1%}")
        return "\n".join(lines)


def run_arena(
    n_players: int = 7,
    n_games: int = 50,
    *,
    policy: str = "random",
    base_seed: int = 0,
    provider: Provider | None = None,
) -> ArenaReport:
    """Run ``n_games`` seeded games and aggregate the outcomes."""
    report = ArenaReport(n_games=n_games, n_players=n_players)
    for i in range(n_games):
        config = GameConfig(roster=build_roster(n_players), seed=base_seed + i)
        referee = Referee(config, _make_decider(policy, provider))
        state = referee.run()
        _record(report, state, policy)
    return report


def _make_decider(
    policy: str, provider: Provider | None
) -> Callable[[PlayerView, DecisionRequest], Action]:
    def decider(view: PlayerView, request: DecisionRequest) -> Action:
        if policy == "llm" and provider is not None:
            return LLMBot(request.actor, provider).decide(view, request)
        return RandomBot(request.actor).decide(view, request)

    return decider


def _record(report: ArenaReport, state: object, policy: str) -> None:
    from ai_werewolf.domain.state import GameState

    game: GameState = state  # type: ignore[assignment]
    report.total_days += game.day
    if game.winner is Faction.VILLAGE:
        report.village_wins += 1
    else:
        report.werewolf_wins += 1
    for seat in game.seats:
        stats = report.role_stats.setdefault(seat.role.value, [0, 0])
        stats[0] += 1
        if seat.alive:
            stats[1] += 1
        agent_stats = report.agent_stats.setdefault(policy, [0, 0])
        agent_stats[0] += 1
        if seat.faction is game.winner:
            agent_stats[1] += 1
    report.ledger.record_game(game)
