import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _observations(weak=False):
    rows = []
    for month in range(24):
        rows.append({
            "date": f"2024-{month % 12 + 1:02d}-01",
            "ic": -0.03 if weak else 0.04,
            "quantile_spread": -0.01 if weak else 0.03,
            "cost_adjusted_return": -0.02 if weak else 0.02,
            "contribution": -0.01 if weak else 0.02,
        })
    return rows


def test_multi_metric_deterioration_becomes_failure_candidate():
    from strategy.factor_lifecycle import FactorHealthMonitor

    report = FactorHealthMonitor().evaluate("value", _observations(weak=True))

    assert report.status == "failure_candidate"
    assert report.window_months == 24
    assert "ic" in report.failed_metrics


def test_single_metric_deterioration_only_warns():
    from strategy.factor_lifecycle import FactorHealthMonitor

    observations = _observations()
    for observation in observations[-12:]:
        observation["ic"] = -0.01
    report = FactorHealthMonitor().evaluate("momentum", observations)

    assert report.status in {"attention", "warning"}


def test_candidate_with_no_incremental_contribution_is_rejected():
    from strategy.factor_lifecycle import FactorCandidateEvaluator

    score = FactorCandidateEvaluator().score(
        {"icir": 0.6, "quantile_spread": 0.04, "cost_adjusted_return": 0.03,
         "stability": 0.8, "correlation": 0.95, "marginal_contribution": 0.0},
        [],
    )

    assert score.accepted is False
    assert "incremental" in score.reasons[0]


def test_existing_factor_diagnostics_produce_health_reports():
    import pandas as pd
    from strategy.factor_lifecycle import health_reports_from_factor_stats

    reports = health_reports_from_factor_stats(pd.DataFrame([
        {"factor": "value", "rank_ic_mean": -0.03, "icir": -0.4,
         "hit_rate_12m": 0.4, "status": "excluded"},
    ]))

    assert reports[0].factor_name == "value"
    assert reports[0].status == "failure_candidate"


def test_health_monitor_keeps_12_and_24_month_windows():
    from strategy.factor_lifecycle import FactorHealthMonitor

    report = FactorHealthMonitor().evaluate("momentum", _observations())

    assert set(report.window_metrics) == {12, 24}
    assert report.window_metrics[12]["ic"] == pytest.approx(0.04)
