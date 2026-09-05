"""Offline faction win-rate baseline and rule-deviation audit.

Runs many deterministic games — one scripted human seat plus six Mock AI — and
aggregates win rates stratified by faction, role, seat, speaking order (先后手)
and seed, plus any rule deviations. It uses the mock provider exclusively, so
it needs no API key and is fully reproducible for a given seed.

The scripted human is a fixed, legal policy: it is only a positional control.
It must not be read as evidence of real-human win rate, persona quality or
playability (see PRD/00_卡点清单与子问题.md §二-b).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ai_werewolf.ai.mock import MockProvider
from ai_werewolf.domain.events import EventKind
from ai_werewolf.domain.roles import Faction
from ai_werewolf.server.room import AIConfig, HumanSeat, RoomConfig
from ai_werewolf.server.session import GameSession
from ai_werewolf.transport.channel import Envelope

_TARGET_KINDS = {"night_kill", "pack_confirm", "night_inspect", "vote"}


class _AutoChannel:
    """A scripted human that always takes the first legal option.

    It mirrors the test double used in the vertical-loop acceptance suite so
    the baseline uses the exact same human behaviour.
    """

    def __init__(self, seed: int = 0) -> None:
        self.sent: list[Envelope] = []
        self.rng = random.Random(seed)

    def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    def recv(self, timeout: float | None = None) -> Envelope:
        for envelope in reversed(self.sent):
            if envelope.kind != "decision":
                continue
            request = envelope.payload["request"]
            kind = request["kind"]
            targets = request.get("legal_targets", [])
            action: dict = {"kind": kind, "actor": request["actor"]}
            if kind == "statement":
                action["text"] = "auto statement"
            elif kind == "last_words":
                action["text"] = "auto last words"
            elif kind == "bid":
                action["priority"] = 5
                action["reason"] = ""
            elif kind == "witch_potions":
                action["heal"] = False
                action["poison"] = targets[0] if targets and self.rng.random() < 0.5 else None
            else:
                action["target"] = targets[0] if targets else None
            return Envelope("action", payload={"action": action})
        raise TimeoutError("no pending decision")


@dataclass
class BalanceReport:
    """Stratified outcomes of a batch of offline games."""

    n_games: int = 0
    village_wins: int = 0
    werewolf_wins: int = 0
    total_days: int = 0
    role_stats: dict[str, list[int]] = field(default_factory=dict)  # role -> [games, wins, survivals]
    seat_stats: dict[int, list[int]] = field(default_factory=dict)  # seat -> [games, wins]
    order_stats: dict[int, list[int]] = field(default_factory=dict)  # day-1 speak rank -> [games, wins]
    human_seat_stats: dict[int, list[int]] = field(default_factory=dict)  # human seat -> [games, human wins]
    per_seed: list[dict] = field(default_factory=list)
    rule_deviations: list[str] = field(default_factory=list)

    @property
    def village_win_rate(self) -> float:
        return self.village_wins / self.n_games if self.n_games else 0.0

    @property
    def werewolf_win_rate(self) -> float:
        return self.werewolf_wins / self.n_games if self.n_games else 0.0

    @property
    def avg_days(self) -> float:
        return self.total_days / self.n_games if self.n_games else 0.0

    def role_win_rate(self, role: str) -> float:
        games, wins, _ = self.role_stats.get(role, (0, 0, 0))
        return wins / games if games else 0.0

    def role_survival(self, role: str) -> float:
        games, _, survivals = self.role_stats.get(role, (0, 0, 0))
        return survivals / games if games else 0.0

    def render(self) -> str:
        lines = [f"平衡基线：{self.n_games} 局（离线 Mock，1 脚本真人 + 6 AI）"]
        lines.append(f"  村民阵营胜率 : {self.village_win_rate:6.1%}")
        lines.append(f"  狼人阵营胜率 : {self.werewolf_win_rate:6.1%}")
        lines.append(f"  平均天数     : {self.avg_days:6.1f}")
        lines.append("")
        lines.append("  角色（胜率 / 存活率）：")
        for role in sorted(self.role_stats):
            games, wins, survivals = self.role_stats[role]
            lines.append(
                f"    {role:<10}: 胜 {wins / games:6.1%}  存活 {survivals / games:6.1%}  (n={games})"
            )
        lines.append("")
        lines.append("  座位（该座位玩家的阵营胜率）：")
        for seat in sorted(self.seat_stats):
            games, wins = self.seat_stats[seat]
            lines.append(f"    P{seat}: {wins / games:6.1%}  (n={games})")
        lines.append("")
        lines.append("  先后手（第一天发言位次的阵营胜率）：")
        for rank in sorted(self.order_stats):
            games, wins = self.order_stats[rank]
            lines.append(f"    第 {rank} 位: {wins / games:6.1%}  (n={games})")
        lines.append("")
        lines.append("  真人座位（真人阵营胜率）：")
        for seat in sorted(self.human_seat_stats):
            games, wins = self.human_seat_stats[seat]
            lines.append(f"    真人坐 P{seat}: {wins / games:6.1%}  (n={games})")
        lines.append("")
        if self.rule_deviations:
            lines.append(f"  规则偏差（{len(self.rule_deviations)} 项，取前 10）：")
            for deviation in self.rule_deviations[:10]:
                lines.append(f"    - {deviation}")
        else:
            lines.append("  规则偏差：无")
        return "\n".join(lines)


def run_balance(
    n_games_per_seat: int = 50,
    *,
    human_seats: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6),
    base_seed: int = 0,
) -> BalanceReport:
    """Run the offline balance sweep and return a :class:`BalanceReport`."""
    report = BalanceReport()
    game_index = 0
    for human_seat in human_seats:
        for _ in range(n_games_per_seat):
            seed = base_seed + game_index
            game_index += 1
            state = _run_game(seed, human_seat)
            _record(report, state, seed, human_seat)
    return report


def _run_game(seed: int, human_seat: int):
    ai = AIConfig(count=6, policy="llm", provider=MockProvider(seed=seed))
    config = RoomConfig(capacity=7, ai=ai, seed=seed)
    session = GameSession(
        config,
        {human_seat: HumanSeat(name="你", channel=_AutoChannel(seed))},
    )
    return session.run()


def _record(report: BalanceReport, state, seed: int, human_seat: int) -> None:
    report.n_games += 1
    report.total_days += state.day
    winner = state.winner
    report.per_seed.append({
        "seed": seed,
        "winner": winner.value if winner is not None else None,
        "days": state.day,
        "human_seat": human_seat,
    })
    report.rule_deviations.extend(_check_rules(state, seed))

    if winner is Faction.VILLAGE:
        report.village_wins += 1
    elif winner is Faction.WEREWOLVES:
        report.werewolf_wins += 1

    order_rank = _speaking_order_ranks(state)

    for seat in state.seats:
        won = seat.faction is winner
        role = report.role_stats.setdefault(seat.role.value, [0, 0, 0])
        role[0] += 1
        if won:
            role[1] += 1
        if seat.alive:
            role[2] += 1

        seat_row = report.seat_stats.setdefault(seat.id, [0, 0])
        seat_row[0] += 1
        if won:
            seat_row[1] += 1

        rank = order_rank.get(seat.id)
        if rank is not None:
            order_row = report.order_stats.setdefault(rank, [0, 0])
            order_row[0] += 1
            if won:
                order_row[1] += 1

    human_row = report.human_seat_stats.setdefault(human_seat, [0, 0])
    human_row[0] += 1
    if state.seat(human_seat).faction is winner:
        human_row[1] += 1


def _speaking_order_ranks(state) -> dict[int, int]:
    """Map each seat to its position in the day-1 discussion speaking order."""
    ranks: dict[int, int] = {}
    for event in state.events:
        if (
            event.kind is EventKind.STATEMENT
            and event.day == 1
            and event.actor is not None
            and event.actor not in ranks
        ):
            ranks[event.actor] = len(ranks)
    return ranks


def _check_rules(state, seed: int) -> list[str]:
    deviations: list[str] = []
    if state.winner is None:
        deviations.append(f"seed {seed}: 对局未产生胜方")
    if state.day > state.config.max_days:
        deviations.append(f"seed {seed}: 超过最大天数（{state.day}）")
    for event in state.events:
        if event.kind in (EventKind.DEATH, EventKind.LYNCH) and event.data.get("role") is not None:
            deviations.append(f"seed {seed}: 死亡公开了身份")
            break
    counts: dict[str, int] = {}
    for seat in state.seats:
        counts[seat.role.value] = counts.get(seat.role.value, 0) + 1
    expected = {"werewolf": 2, "seer": 1, "witch": 1, "villager": 3}
    if counts != expected:
        deviations.append(f"seed {seed}: 角色分布错误 {counts}")
    return deviations
