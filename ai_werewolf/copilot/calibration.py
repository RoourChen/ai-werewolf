"""Calibration analysis for the human copilot.

The copilot reports a probability — P(werewolf) — for every living player. A
probability is only trustworthy if it is *calibrated*: when the copilot says
"70%", a werewolf should actually turn up about 70% of the time. This module
measures exactly that, so a human using the copilot knows how much weight its
percentages deserve.

It runs many seeded games and, at every daybreak, asks the copilot — from each
surviving villager's seat — for its suspicions. Each suspicion is paired with
the ground truth (was that player really a werewolf), and the pairs are scored
with standard forecast-verification metrics, following the WOLF benchmark
(arXiv:2512.09187) which uses the Brier score for werewolf-suspicion calibration:

* **Brier score** — mean squared error of the probabilities. 0 is perfect;
  lower is better.
* **Brier skill score** — how much the copilot beats a naive forecaster that
  always predicts the base rate. 1 is perfect, 0 is no better than the base
  rate, negative is worse.
* **Murphy decomposition** — splits the (binned) Brier score into *reliability*
  (calibration error — lower is better), *resolution* (how sharply the copilot
  separates wolves from villagers — higher is better) and *uncertainty* (the
  base-rate variance, intrinsic to the games and beyond any forecaster's
  control). Binned, ``brier ≈ reliability - resolution + uncertainty``.
* a **reliability table** — predicted probability vs observed werewolf rate per
  10% bin: the data behind a reliability diagram.

AI狼人杀 is, as far as the surveyed literature goes, one of the only werewolf
projects with an explainable probabilistic copilot — so it is one of the only
ones that can report *its own advisor's* calibration to the human who relies
on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ai_werewolf.agents.base import Agent
from ai_werewolf.agents.random_agent import RandomAgent
from ai_werewolf.copilot.advisor import advise
from ai_werewolf.game.engine import GameEngine
from ai_werewolf.game.events import Event, EventType
from ai_werewolf.game.roles import Faction, Role
from ai_werewolf.game.state import GameConfig, build_view

#: A (predicted P(werewolf), actual outcome 0/1) pair.
Prediction = tuple[float, float]

ProgressHook = Callable[[int, int], None]  # (completed games, total)


@dataclass(frozen=True)
class CalibrationBin:
    """One row of a reliability diagram."""

    low: float           # bin lower edge, e.g. 0.7
    high: float          # bin upper edge, e.g. 0.8
    mean_predicted: float  # average copilot probability in this bin
    observed_rate: float   # fraction that really were werewolves
    count: int             # how many predictions fell in this bin

    @property
    def gap(self) -> float:
        """Calibration gap — how far predicted sits from observed."""
        return self.mean_predicted - self.observed_rate


@dataclass
class CalibrationReport:
    """Aggregated calibration of the copilot over many games."""

    n_games: int = 0
    n_players: int = 0
    n_predictions: int = 0
    base_rate: float = 0.0       # fraction of judged players that were wolves
    brier_score: float = 0.0     # exact, from the raw pairs; lower is better
    reliability: float = 0.0     # binned calibration error; lower is better
    resolution: float = 0.0      # binned discrimination; higher is better
    uncertainty: float = 0.0     # base_rate * (1 - base_rate)
    bins: list[CalibrationBin] = field(default_factory=list)

    @property
    def baseline_brier(self) -> float:
        """Brier score of always forecasting the base rate (equals uncertainty)."""
        return self.uncertainty

    @property
    def skill_score(self) -> float:
        """Brier skill score: 1 perfect, 0 no better than the base rate."""
        if self.baseline_brier <= 0.0:
            return 0.0
        return 1.0 - self.brier_score / self.baseline_brier

    def render(self) -> str:
        """A plain-text report, suitable for logs or a terminal without rich."""
        lines = [
            f"Copilot calibration — {self.n_games} games, {self.n_players} players, "
            f"{self.n_predictions} predictions",
            f"  Base rate (werewolves)  : {self.base_rate:6.1%}",
            f"  Brier score             : {self.brier_score:7.4f}  (0 = perfect)",
            f"  Baseline (base-rate)    : {self.baseline_brier:7.4f}",
            f"  Brier skill score       : {self.skill_score:7.4f}  (1 = perfect, "
            f"0 = no skill)",
            f"  Reliability (cal. error): {self.reliability:7.4f}  (lower better)",
            f"  Resolution (discrim.)   : {self.resolution:7.4f}  (higher better)",
            f"  Uncertainty             : {self.uncertainty:7.4f}",
            "  Reliability diagram (predicted -> observed werewolf rate):",
        ]
        for b in self.bins:
            bar = "#" * round(b.observed_rate * 20)
            lines.append(
                f"    [{b.low:4.0%}-{b.high:4.0%}) predicted {b.mean_predicted:6.1%} "
                f"-> observed {b.observed_rate:6.1%}  gap {b.gap:+6.1%}  "
                f"n={b.count:<5d} |{bar}"
            )
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """A Markdown summary, ready to paste into a README or an issue."""
        rows = [
            f"**Copilot calibration** — {self.n_games} games, "
            f"{self.n_predictions} predictions",
            "",
            f"- Brier score: **{self.brier_score:.4f}** "
            f"(baseline {self.baseline_brier:.4f})",
            f"- Brier skill score: **{self.skill_score:.4f}**",
            f"- Reliability {self.reliability:.4f} · "
            f"Resolution {self.resolution:.4f} · "
            f"Uncertainty {self.uncertainty:.4f}",
            "",
            "| Predicted bin | Mean predicted | Observed werewolf rate | "
            "Gap | Count |",
            "|---------------|---------------:|-----------------------:|"
            "----:|------:|",
        ]
        for b in self.bins:
            rows.append(
                f"| {b.low:.0%}-{b.high:.0%} | {b.mean_predicted:.1%} | "
                f"{b.observed_rate:.1%} | {b.gap:+.1%} | {b.count} |"
            )
        return "\n".join(rows)


def evaluate_copilot(
    n_players: int = 7,
    n_games: int = 40,
    *,
    base_seed: int = 0,
    n_bins: int = 10,
    agent_factory: Callable[[int, Role], Agent] | None = None,
    progress: ProgressHook | None = None,
) -> CalibrationReport:
    """Measure how well-calibrated the copilot's probabilities are.

    Plays ``n_games`` seeded games (with ``agent_factory`` agents, random by
    default), collecting the copilot's suspicions from every surviving
    villager's viewpoint at each daybreak, and scores them.

    Note: calibration is measured against games *played by* ``agent_factory``.
    The copilot itself is always the heuristic advisor, but the games it reads
    are only as realistic as the agents playing them — a copilot's calibration
    against random agents may differ from its calibration against strong ones.
    """
    if n_games < 1:
        raise ValueError("n_games must be at least 1")
    factory = agent_factory or (lambda pid, _role: RandomAgent(pid))

    pairs: list[Prediction] = []
    for i in range(n_games):
        config = GameConfig.standard(n_players, seed=base_seed + i)
        pairs.extend(_collect_game(config, factory))
        if progress is not None:
            progress(i + 1, n_games)

    return _score(pairs, n_bins, n_games=n_games, n_players=n_players)


def _collect_game(
    config: GameConfig, factory: Callable[[int, Role], Agent]
) -> list[Prediction]:
    """Run one game, harvesting copilot predictions vs ground truth."""
    engine = GameEngine(config, factory)
    pairs: list[Prediction] = []

    def observer(event: Event) -> None:
        # A daybreak is a natural mid-game checkpoint: night info is in, the
        # day's votes are not — exactly when a human would consult the copilot.
        if event.type is not EventType.DAY_BREAKS:
            return
        state = engine.state
        for viewer_id in state.living_ids():
            if state.player(viewer_id).faction is not Faction.VILLAGE:
                continue  # the copilot's deductive job is a villager's job
            advice = advise(build_view(state, viewer_id))
            for suspicion in advice.suspicions:
                actual = (
                    1.0
                    if state.player(suspicion.player_id).faction is Faction.WEREWOLVES
                    else 0.0
                )
                pairs.append((suspicion.score, actual))

    engine.observer = observer
    engine.run()
    return pairs


def _score(
    pairs: list[Prediction], n_bins: int, *, n_games: int, n_players: int
) -> CalibrationReport:
    """Turn raw (prediction, outcome) pairs into a full calibration report."""
    n = len(pairs)
    if n == 0:
        return CalibrationReport(n_games=n_games, n_players=n_players)

    base_rate = sum(outcome for _, outcome in pairs) / n
    brier = sum((pred - outcome) ** 2 for pred, outcome in pairs) / n
    uncertainty = base_rate * (1.0 - base_rate)

    # Bin by predicted probability for the Murphy decomposition.
    sum_pred = [0.0] * n_bins
    sum_outcome = [0.0] * n_bins
    counts = [0] * n_bins
    for pred, outcome in pairs:
        k = min(n_bins - 1, int(pred * n_bins))
        sum_pred[k] += pred
        sum_outcome[k] += outcome
        counts[k] += 1

    reliability = 0.0
    resolution = 0.0
    bins: list[CalibrationBin] = []
    for k in range(n_bins):
        count = counts[k]
        if count == 0:
            continue
        mean_pred = sum_pred[k] / count
        observed = sum_outcome[k] / count
        reliability += count * (mean_pred - observed) ** 2
        resolution += count * (observed - base_rate) ** 2
        bins.append(CalibrationBin(
            low=k / n_bins,
            high=(k + 1) / n_bins,
            mean_predicted=mean_pred,
            observed_rate=observed,
            count=count,
        ))

    return CalibrationReport(
        n_games=n_games,
        n_players=n_players,
        n_predictions=n,
        base_rate=base_rate,
        brier_score=brier,
        reliability=reliability / n,
        resolution=resolution / n,
        uncertainty=uncertainty,
        bins=bins,
    )
