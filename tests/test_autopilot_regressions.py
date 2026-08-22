import pandas as pd
import pytest


def test_score_candidate_rejects_missing_and_non_finite_metrics():
    from service.autopilot_service import score_candidate

    evaluation = score_candidate(
        {"params": {"top_n": 3}},
        {"data_quality_passed": True, "future_safe": True, "stress_passed": True,
         "oos_12_excess_return": float("nan")},
        {"data_quality_passed": True, "future_safe": True, "oos_12_excess_return": 1,
         "oos_24_excess_return": 1, "oos_sharpe": 0.5, "max_drawdown": 20,
         "annual_turnover": 100, "oos_stability": 0.5, "annual_return": 10,
         "stress_passed": True},
    )

    assert evaluation.accepted is False
    assert "missing_metrics" in evaluation.reasons
    assert "invalid_metrics" in evaluation.reasons


def test_backtest_reports_empty_trading_range_instead_of_returns_division_by_zero():
    from strategy import multi_factor

    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    prices = pd.DataFrame({
        "trade_date": dates,
        "open": range(1, 11),
        "high": range(1, 11),
        "low": range(1, 11),
        "close": range(1, 11),
        "volume": [100] * 10,
    })

    with pytest.raises(ValueError, match="没有交易日行情"):
        multi_factor.run_backtest(
            {"510300": prices},
            start_date="2025-01-01",
            end_date="2025-01-31",
        )
