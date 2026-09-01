"""The achievement / statistics ledger.

A :class:`StatsLedger` accumulates per-player records across games: games
played, wins, survivals and per-role breakdowns, then derives win rates, a
leaderboard and simple achievements (badges).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.domain.roles import Faction, Role
from ai_werewolf.domain.state import GameState

_GOD_ROLES = {Role.SEER.value, Role.WITCH.value}


@dataclass
class PlayerRecord:
    games: int = 0
    wins: int = 0
    survivals: int = 0
    # role value -> [games, wins, survivals]
    by_role: dict[str, list[int]] = field(default_factory=dict)

    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0


@dataclass
class StatsLedger:
    """Aggregated records across games."""

    records: dict[str, PlayerRecord] = field(default_factory=dict)

    def record(
        self,
        name: str,
        role: Role,
        faction: Faction,
        winner: Faction,
        survived: bool,
    ) -> None:
        rec = self.records.setdefault(name, PlayerRecord())
        rec.games += 1
        if survived:
            rec.survivals += 1
        won = faction is winner
        if won:
            rec.wins += 1
        stats = rec.by_role.setdefault(role.value, [0, 0, 0])
        stats[0] += 1
        if won:
            stats[1] += 1
        if survived:
            stats[2] += 1

    def record_game(self, state: GameState) -> None:
        if state.winner is None:
            return
        for seat in state.seats:
            self.record(seat.name, seat.role, seat.faction, state.winner, seat.alive)

    def win_rate(self, name: str) -> float:
        rec = self.records.get(name)
        return rec.win_rate() if rec else 0.0

    def leaderboard(self, min_games: int = 1) -> list[tuple[str, PlayerRecord]]:
        rows = [
            (name, rec)
            for name, rec in self.records.items()
            if rec.games >= min_games
        ]
        rows.sort(key=lambda pair: (-pair[1].win_rate(), -pair[1].games, pair[0]))
        return rows

    def achievements(self, name: str) -> list[str]:
        rec = self.records.get(name)
        if rec is None:
            return []
        badges: list[str] = []
        if rec.wins >= 1:
            badges.append("首胜")
        if rec.by_role.get(Role.WEREWOLF.value, [0, 0, 0])[1] >= 1:
            badges.append("狼王")
        if any(rec.by_role.get(r, [0, 0, 0])[1] >= 1 for r in _GOD_ROLES):
            badges.append("神职")
        if rec.survivals >= 1:
            badges.append("幸存者")
        if rec.games >= 5 and rec.win_rate() >= 0.6:
            badges.append("常胜将军")
        return badges

    def render_leaderboard(self) -> str:
        lines = ["排行榜（按胜率）："]
        for rank, (name, rec) in enumerate(self.leaderboard(), 1):
            badges = "/".join(self.achievements(name)) or "—"
            lines.append(
                f"  {rank}. {name:<12} {rec.win_rate():6.1%} "
                f"（{rec.wins}/{rec.games} 胜）徽章：{badges}"
            )
        return "\n".join(lines)
