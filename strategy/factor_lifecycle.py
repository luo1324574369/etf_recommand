"""因子健康分级与候选因子多目标评分。"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class FactorHealthReport:
    factor_name: str
    status: str
    window_months: int
    metrics: dict[str, float]
    failed_metrics: tuple[str, ...]
    window_metrics: dict[int, dict[str, float]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.window_metrics:
            object.__setattr__(self, "window_metrics", {self.window_months: dict(self.metrics)})


@dataclass(frozen=True)
class CandidateScore:
    score: float
    accepted: bool
    reasons: tuple[str, ...]
    metrics: dict[str, float]


def _classify_health(failed_metrics: list[str]) -> str:
    if len(failed_metrics) >= 3:
        return "failure_candidate"
    if len(failed_metrics) >= 2:
        return "warning"
    if failed_metrics:
        return "attention"
    return "healthy"


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

        metric_names = (
            "ic", "icir", "quantile_spread", "cost_adjusted_return", "contribution",
            "decay", "market_phase_stability", "style_exposure",
        )
        window_metrics = {}
        for requested_window in sorted(set(window_months)):
            if requested_window > len(observations):
                continue
            selected = observations[-requested_window:]
            metrics = {
                name: float(mean(float(row.get(name, 0.0)) for row in selected))
                for name in metric_names
                if any(name in row for row in selected)
            }
            if len(selected) >= 4:
                midpoint = len(selected) // 2
                metrics["decay"] = float(
                    mean(float(row.get("ic", 0.0)) for row in selected[midpoint:])
                    - mean(float(row.get("ic", 0.0)) for row in selected[:midpoint])
                )
            phases = {
                str(row.get("market_phase")): float(row.get("ic", 0.0))
                for row in selected
                if row.get("market_phase") is not None
            }
            if phases:
                metrics["market_phase_stability"] = float(
                    sum(value > 0 for value in phases.values()) / len(phases)
                )
            style_values = [
                abs(float(row["style_exposure"]))
                for row in selected
                if row.get("style_exposure") is not None
            ]
            if style_values:
                metrics["style_exposure"] = float(mean(style_values))
            metrics["ic_positive_ratio"] = float(
                sum(float(row.get("ic", 0.0)) > 0 for row in selected) / len(selected)
            )
            window_metrics[requested_window] = metrics

        if not window_metrics:
            return FactorHealthReport(
                factor_name=factor_name,
                status="insufficient_data",
                window_months=len(observations),
                metrics={},
                failed_metrics=("window_size",),
            )

        selected_window = max(window_metrics)
        metrics = window_metrics[selected_window]
        failed_metrics = []
        if metrics["ic"] < 0.02:
            failed_metrics.append("ic")
        if metrics["ic_positive_ratio"] < 0.55:
            failed_metrics.append("ic_positive_ratio")
        if metrics.get("icir", 1.0) < 0.30:
            failed_metrics.append("icir")
        if metrics.get("decay", 0.0) < -0.05:
            failed_metrics.append("decay")
        if metrics.get("market_phase_stability", 1.0) < 0.50:
            failed_metrics.append("market_phase_stability")
        if metrics.get("style_exposure", 0.0) > 0.80:
            failed_metrics.append("style_exposure")
        if metrics["quantile_spread"] <= 0:
            failed_metrics.append("quantile_spread")
        if metrics["cost_adjusted_return"] <= 0:
            failed_metrics.append("cost_adjusted_return")
        if metrics["contribution"] <= 0:
            failed_metrics.append("contribution")

        status = _classify_health(failed_metrics)
        return FactorHealthReport(
            factor_name=factor_name,
            status=status,
            window_months=selected_window,
            metrics=metrics,
            failed_metrics=tuple(failed_metrics),
            window_metrics=window_metrics,
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
        window_metrics = {}
        for window in (12, 24):
            suffix = f"_{window}m"
            ic = row.get(f"rank_ic_mean{suffix}", row.get("rank_ic_mean", 0.0))
            icir = row.get(f"icir{suffix}", row.get("icir", 0.0))
            hit_rate = row.get(f"hit_rate{suffix}", row.get("hit_rate_12m", 0.0))
            window_metrics[window] = {
                "ic": float(ic or 0.0),
                "icir": float(icir or 0.0),
                "hit_rate": float(hit_rate or 0.0),
            }
        metrics = window_metrics[12]
        failed_metrics = []
        if metrics["ic"] < 0.02:
            failed_metrics.append("ic")
        if metrics["icir"] < 0.30:
            failed_metrics.append("icir")
        if metrics["hit_rate"] < 0.55:
            failed_metrics.append("hit_rate")
        if row.get("status") == "excluded":
            failed_metrics.extend(metric for metric in ("excluded", "contribution") if metric not in failed_metrics)
        health_status = _classify_health(failed_metrics)
        reports.append(FactorHealthReport(
            factor_name=str(row.get("factor", "unknown")),
            status=health_status,
            window_months=12,
            metrics=metrics,
            failed_metrics=tuple(failed_metrics),
            window_metrics=window_metrics,
        ))
    return reports
