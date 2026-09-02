"""Decision-quality analysis for real-model calibration.

Aggregates the ratios the product review asked to track before tuning the
deception threshold: unmarked-but-over-threshold gaps, wrong deception marks,
retries and fallbacks. Threshold tuning is only allowed after at least 30
valid public decision nodes are collected, and only if the data shows
misjudgement or excessive retries.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_werewolf.domain.trace import DecisionRecord

MIN_PUBLIC_NODES = 30
_PUBLIC_KINDS = {"statement", "vote"}


@dataclass
class DecisionQualityReport:
    total: int = 0
    public: int = 0
    gap_without_mark: int = 0
    wrong_mark: int = 0
    retried: int = 0
    fallback: int = 0
    pending_review: int = 0

    @property
    def gap_without_mark_ratio(self) -> float:
        return self.gap_without_mark / self.public if self.public else 0.0

    @property
    def wrong_mark_ratio(self) -> float:
        return self.wrong_mark / self.public if self.public else 0.0

    @property
    def retry_ratio(self) -> float:
        return self.retried / self.total if self.total else 0.0

    @property
    def fallback_ratio(self) -> float:
        return self.fallback / self.total if self.total else 0.0

    @property
    def ready_for_tuning(self) -> bool:
        return self.public >= MIN_PUBLIC_NODES

    def render(self) -> str:
        return (
            f"决策质量 — 总 {self.total} 次决策，公开节点 {self.public} "
            f"（阈值为 {MIN_PUBLIC_NODES} 才允许调参）\n"
            f"  未标记但分差超阈值比例: {self.gap_without_mark_ratio:6.1%}\n"
            f"  错误标记欺骗比例:         {self.wrong_mark_ratio:6.1%}\n"
            f"  重试比例:                 {self.retry_ratio:6.1%}\n"
            f"  重试后兜底比例:           {self.fallback_ratio:6.1%}\n"
            f"  待复核欺骗:               {self.pending_review}"
        )


def analyze_decision_quality(traces: dict[int, list[DecisionRecord]]) -> DecisionQualityReport:
    report = DecisionQualityReport()
    for records in traces.values():
        for record in records:
            report.total += 1
            if record.kind in _PUBLIC_KINDS:
                report.public += 1
            if record.retried:
                report.retried += 1
            if record.fallback_reason is not None:
                report.fallback += 1
            if record.pending_review:
                report.pending_review += 1
            reason = record.fallback_reason or ""
            if "gap without" in reason:
                report.gap_without_mark += 1
            if any(tag in reason for tag in ("deception marked", "deception target", "fabrication")):
                report.wrong_mark += 1
    return report
