"""Brier-score calibration of the copilot's probabilities.

The copilot reports P(werewolf) for each player. A probability is only useful
if it is *calibrated*: when it says 70%, a werewolf should turn up about 70%
of the time. This module measures that with the Brier score (mean squared
error, 0 = perfect) and a reliability table over probability bins.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.copilot.advisor import advise
from ai_werewolf.domain.actions import Action
from ai_werewolf.domain.events import EventKind, GameEvent
from ai_werewolf.domain.referee import Referee
from ai_werewolf.domain.roles import Faction, build_roster
from ai_werewolf.domain.state import DecisionRequest, GameConfig, PlayerView, build_view
from ai_werewolf.players.random_bot import RandomBot

Prediction = tuple[float, float]  # (predicted P(werewolf), actual 0/1)


@dataclass(frozen=True)
class ReliabilityBin:
    low: float
    high: float
    mean_predicted: float
    observed_rate: float
    count: int


@dataclass
class CalibrationReport:
    n_games: int = 0
    n_predictions: int = 0
    base_rate: float = 0.0
    brier_score: float = 0.0
    bins: list[ReliabilityBin] = field(default_factory=list)

    @property
    def skill_score(self) -> float:
        """Brier skill vs always forecasting the base rate."""
        baseline = self.base_rate * (1.0 - self.base_rate)
        if baseline <= 0.0:
            return 0.0
        return 1.0 - self.brier_score / baseline

    def render(self) -> str:
        lines = [
            f"Copilot 校准 — {self.n_games} 局，{self.n_predictions} 次预测",
            f"  狼人基础比例 : {self.base_rate:6.1%}",
            f"  Brier 分数   : {self.brier_score:7.4f}（0 = 完美）",
            f"  技能分数     : {self.skill_score:7.4f}（1 = 完美）",
            "  可靠性表（预测 → 实际狼人率）：",
        ]
        for b in self.bins:
            lines.append(
                f"    [{b.low:4.0%}-{b.high:4.0%}) 预测 {b.mean_predicted:6.1%} "
                f"→ 实际 {b.observed_rate:6.1%}（n={b.count}）"
            )
        return "\n".join(lines)


def evaluate_copilot(
    n_players: int = 7,
    n_games: int = 40,
    *,
    base_seed: int = 0,
    n_bins: int = 10,
) -> CalibrationReport:
    """Measure the copilot's calibration over many seeded bot games."""
    if n_games < 1:
        raise ValueError("n_games must be at least 1")

    pairs: list[Prediction] = []
    for i in range(n_games):
        config = GameConfig(roster=build_roster(n_players), seed=base_seed + i)
        pairs.extend(_collect(config))
    return _score(pairs, n_bins, n_games)


def _collect(config: GameConfig) -> list[Prediction]:
    referee = Referee(config, _decider)
    pairs: list[Prediction] = []

    def observer(event: GameEvent) -> None:
        if event.kind is not EventKind.DISCUSSION_BEGINS:
            return
        state = referee.state
        for viewer in state.living_ids():
            if state.seat(viewer).faction is not Faction.VILLAGE:
                continue
            advice = advise(build_view(state, viewer))
            for suspicion in advice.suspicions:
                actual = (
                    1.0
                    if state.seat(suspicion.player_id).faction is Faction.WEREWOLVES
                    else 0.0
                )
                pairs.append((suspicion.probability, actual))

    referee.observer = observer
    referee.run()
    return pairs


def _decider(view: PlayerView, request: DecisionRequest) -> Action:
    return RandomBot(request.actor).decide(view, request)


def _score(pairs: list[Prediction], n_bins: int, n_games: int) -> CalibrationReport:
    n = len(pairs)
    if n == 0:
        return CalibrationReport(n_games=n_games)
    base_rate = sum(actual for _, actual in pairs) / n
    brier = sum((pred - actual) ** 2 for pred, actual in pairs) / n

    sum_pred = [0.0] * n_bins
    sum_actual = [0.0] * n_bins
    counts = [0] * n_bins
    for pred, actual in pairs:
        k = min(n_bins - 1, int(pred * n_bins))
        sum_pred[k] += pred
        sum_actual[k] += actual
        counts[k] += 1

    bins: list[ReliabilityBin] = []
    for k in range(n_bins):
        if counts[k] == 0:
            continue
        bins.append(ReliabilityBin(
            low=k / n_bins,
            high=(k + 1) / n_bins,
            mean_predicted=sum_pred[k] / counts[k],
            observed_rate=sum_actual[k] / counts[k],
            count=counts[k],
        ))
    return CalibrationReport(
        n_games=n_games,
        n_predictions=n,
        base_rate=base_rate,
        brier_score=brier,
        bins=bins,
    )
