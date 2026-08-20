import json


def test_monthly_monitor_creates_replacement_candidates_for_failed_factors(tmp_path):
    from service.factor_monitoring_service import MonthlyFactorMonitor

    observations = {
        "value": [{
            "date": f"2025-{month:02d}-01",
            "ic": -0.03,
            "quantile_spread": -0.01,
            "cost_adjusted_return": -0.02,
            "contribution": -0.01,
        } for month in range(1, 13)],
        "momentum": [{
            "date": f"2025-{month:02d}-01",
            "ic": 0.04,
            "quantile_spread": 0.03,
            "cost_adjusted_return": 0.02,
            "contribution": 0.02,
        } for month in range(1, 13)],
    }

    report = MonthlyFactorMonitor().evaluate(observations, "2026-01-31")
    output = report.write(tmp_path)

    assert report.replacement_candidates == ("value",)
    assert json.loads(output["json"].read_text(encoding="utf-8"))["as_of_date"] == "2026-01-31"
    assert "替换候选" in output["markdown"].read_text(encoding="utf-8")
