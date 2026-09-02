"""Decision-quality analysis for real-model calibration.

Aggregates the ratios the product review asked to track: unmarked-but-over-
threshold gaps, wrong deception marks, retries and fallbacks, plus a per-cause
breakdown of the *first* validation failure so the highest-frequency structured
output problem can be fixed first. Threshold tuning is gated on >= 30 public
decision nodes; format/stability fixes are not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_werewolf.domain.trace import DecisionRecord

MIN_PUBLIC_NODES = 30
_PUBLIC_KINDS = {"statement", "vote"}


def classify_failure(reason: str | None) -> str:
    if not reason:
        return "none"
    if "unparseable" in reason:
        return "json_parse"
    if any(tag in reason for tag in ("private_suspicion", "strategic_threat", "public_suspicion")):
        return "suspicion_scores"
    if "evidence" in reason:
        return "evidence"
    if any(tag in reason for tag in ("illegal", "wolf pretended")):
        return "illegal_action"
    if any(tag in reason for tag in ("deception", "fabrication", "gap without")):
        return "deception_protocol"
    if "confidence" in reason:
        return "confidence"
    return "other"


@dataclass
class DecisionQualityReport:
    total: int = 0
    public: int = 0
    gap_without_mark: int = 0
    wrong_mark: int = 0
    retried: int = 0
    fallback: int = 0
    pending_review: int = 0
    failure_distribution: dict[str, int] = field(default_factory=dict)

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
        lines = [
            f"决策质量 — 总 {self.total} 次决策，公开节点 {self.public} "
            f"（阈值 {MIN_PUBLIC_NODES} 才允许调参）",
            f"  重试比例:         {self.retry_ratio:6.1%}",
            f"  重试后兜底比例:   {self.fallback_ratio:6.1%}",
            f"  未标记超阈值比例: {self.gap_without_mark_ratio:6.1%}",
            f"  错误标记欺骗比例: {self.wrong_mark_ratio:6.1%}",
            f"  待复核欺骗:       {self.pending_review}",
            "  首次校验失败原因分布:",
        ]
        for cause, count in sorted(self.failure_distribution.items(), key=lambda kv: -kv[1]):
            ratio = count / self.total if self.total else 0.0
            lines.append(f"    {cause:<18} {count} 次 ({ratio:5.1%})")
        return "\n".join(lines)


def _fold(records, report: DecisionQualityReport) -> None:
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
        reason = record.first_failure or record.fallback_reason or ""
        if "gap without" in reason:
            report.gap_without_mark += 1
        if any(tag in reason for tag in ("deception", "fabrication")):
            report.wrong_mark += 1
        cause = classify_failure(record.first_failure)
        if cause != "none":
            report.failure_distribution[cause] = report.failure_distribution.get(cause, 0) + 1


def analyze_decision_quality(traces: dict[int, list[DecisionRecord]]) -> DecisionQualityReport:
    report = DecisionQualityReport()
    for records in traces.values():
        _fold(records, report)
    return report


def analyze_transcript(replay: dict) -> DecisionQualityReport:
    """Rebuild a quality report from a saved transcript's raw trace dicts."""
    report = DecisionQualityReport()
    traces = replay.get("traces", {})
    for records in traces.values():
        for raw in records:
            report.total += 1
            if raw.get("kind") in _PUBLIC_KINDS:
                report.public += 1
            if raw.get("retried"):
                report.retried += 1
            if raw.get("fallback_reason") is not None:
                report.fallback += 1
            if raw.get("pending_review"):
                report.pending_review += 1
            reason = raw.get("first_failure") or raw.get("fallback_reason") or ""
            if "gap without" in reason:
                report.gap_without_mark += 1
            if any(tag in reason for tag in ("deception", "fabrication")):
                report.wrong_mark += 1
            cause = classify_failure(raw.get("first_failure"))
            if cause != "none":
                report.failure_distribution[cause] = report.failure_distribution.get(cause, 0) + 1
    return report
