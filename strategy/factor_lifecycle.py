"""因子健康分级与候选因子多目标评分。"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class FactorHealthReport:
    factor_name: str
    status: str
    window_months: int
    metrics: dict[str, float]
    failed_metrics: tuple[str, ...]


@dataclass(frozen=True)
class CandidateScore:
    score: float
    accepted: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float]


class FactorHealthMonitor:
    def __init__(self, min_observations: int = 12):
        self.min_observations = min_observations

    def evaluate(
        self,
        factor_name: str,
        observations: list[dict[str, Any]],
        window_months: tuple[int, ...] = (12, 24),
    ) -> FactorHealthReport:
        if len(observations) < self.min_observations:
            return FactorHealthReport(
                factor_name=factor_name,
                status="insufficient_data",
                window_months=len(observations),
                metrics={},
                failed_metrics=("sample_size",),
            )

        selected_window = min(max(window_months), len(observations))
        selected = observations[-selected_window:]
        metric_names = ("ic", "quantile_spread", "cost_adjusted_return", "contribution")
        metrics = {
            name: float(mean(float(row.get(name, 0.0)) for row in selected))
            for name in metric_names
        }
        ic_positive_ratio = sum(float(row.get("ic", 0.0)) > 0 for row in selected) / len(selected)
        metrics["ic_positive_ratio"] = float(ic_positive_ratio)
        failed_metrics = []
        if metrics["ic"] < 0.02:
            failed_metrics.append("ic")
        if metrics["ic_positive_ratio"] < 0.55:
            failed_metrics.append("ic_positive_ratio")
        if metrics["quantile_spread"] <= 0:
            failed_metrics.append("quantile_spread")
        if metrics["cost_adjusted_return"] <= 0:
            failed_metrics.append("cost_adjusted_return")
        if metrics["contribution"] <= 0:
            failed_metrics.append("contribution")

        if len(failed_metrics) >= 3:
            status = "failure_candidate"
        elif len(failed_metrics) >= 2:
            status = "warning"
        elif failed_metrics:
            status = "attention"
        else:
            status = "healthy"
        return FactorHealthReport(
            factor_name=factor_name,
            status=status,
            window_months=selected_window,
            metrics=metrics,
            failed_metrics=tuple(failed_metrics),
        )


class FactorCandidateEvaluator:
    def score(self, candidate: dict[str, Any], active_reports: list[FactorHealthReport]) -> CandidateScore:
        metrics = {
            key: float(candidate.get(key, 0.0))
            for key in ("icir", "quantile_spread", "cost_adjusted_return", "stability", "correlation", "marginal_contribution")
        }
        reasons = []
        if metrics["correlation"] >= 0.90:
            reasons.append("no incremental contribution: factor correlation is too high")
        if metrics["marginal_contribution"] <= 0:
            reasons.append("no incremental contribution: portfolio marginal contribution is non-positive")
        score = (
            metrics["icir"]
            + metrics["quantile_spread"]
            + metrics["cost_adjusted_return"]
            + metrics["stability"]
            + metrics["marginal_contribution"]
            - metrics["correlation"] * 0.2
        )
        return CandidateScore(
            score=float(score),
            accepted=not reasons,
            reasons=tuple(reasons),
            metrics=metrics,
        )


def health_reports_from_factor_stats(factor_stats) -> list[FactorHealthReport]:
    """把正式策略已经生成的因子摘要转换为生命周期健康报告。"""
    if factor_stats is None or getattr(factor_stats, "empty", True):
        return []
    reports = []
    for row in factor_stats.to_dict(orient="records"):
        failed_metrics = []
        if float(row.get("rank_ic_mean", 0.0) or 0.0) < 0.02:
            failed_metrics.append("ic")
        if float(row.get("icir", 0.0) or 0.0) < 0.30:
            failed_metrics.append("icir")
        if float(row.get("hit_rate_12m", 0.0) or 0.0) < 0.55:
            failed_metrics.append("hit_rate")
        if row.get("status") == "excluded":
            failed_metrics.extend(metric for metric in ("excluded", "contribution") if metric not in failed_metrics)
        if len(failed_metrics) >= 3:
            health_status = "failure_candidate"
        elif len(failed_metrics) >= 2:
            health_status = "warning"
        elif failed_metrics:
            health_status = "attention"
        else:
            health_status = "healthy"
        reports.append(FactorHealthReport(
            factor_name=str(row.get("factor", "unknown")),
            status=health_status,
            window_months=12,
            metrics={
                "ic": float(row.get("rank_ic_mean", 0.0) or 0.0),
                "icir": float(row.get("icir", 0.0) or 0.0),
                "hit_rate": float(row.get("hit_rate_12m", 0.0) or 0.0),
            },
            failed_metrics=tuple(failed_metrics),
        ))
    return reports
