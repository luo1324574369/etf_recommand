import json

import pandas as pd


def _base_result():
    dates = pd.date_range("2023-01-01", periods=180, freq="B")
    trade_date = dates[0].strftime("%Y-%m-%d")
    return {
        "total_return": 10.0,
        "excess_return": 2.0,
        "sharpe_ratio": 0.6,
        "max_drawdown": 10.0,
        "annual_cost_pct": 1.0,
        "trade_list": [
            {"date": trade_date, "code": "510300", "direction": "买入", "amount": 600000},
            {"date": trade_date, "code": "510500", "direction": "买入", "amount": 400000},
        ],
        "nav_df": pd.DataFrame({"date": dates, "nav": [1 + index / 1000 for index in range(180)]}),
        "factor_diagnostics": {
            "factor_stats": pd.DataFrame([
                {"factor": "momentum_120d", "rank_ic_mean": 0.04, "icir": 0.5, "used_weight_mean": 0.6},
                {"factor": "reversal_20d", "rank_ic_mean": -0.03, "icir": -0.2, "used_weight_mean": 0.4},
            ]),
            "grouped_returns": {},
            "weight_history": pd.DataFrame([
                {"date": "2023-01-01", "momentum_120d": 0.6, "reversal_20d": 0.4},
            ]),
        },
    }


def _data():
    dates = pd.date_range("2023-01-01", periods=180, freq="B")
    return {
        code: pd.DataFrame({
            "trade_date": dates,
            "close": [1 + scale * index / 180 for index in range(180)],
            "volume": [100000] * 180,
        })
        for code, scale in (("510300", 0.2), ("510500", 0.3))
    }


def test_diagnostics_runs_attribution_with_local_proxy_and_builds_exposures():
    from service.autopilot_diagnostics import build_autopilot_diagnostics

    def runner(params, start_date, end_date):
        return {"total_return": 8.0}

    result = build_autopilot_diagnostics(
        config={"params": {}},
        baseline_result=_base_result(),
        data_dict=_data(),
        etf_to_sector={"510300": "宽基", "510500": "宽基"},
        start_date="2023-01-01",
        end_date="2023-09-01",
        factor_health=[],
        backtest_runner=runner,
    )

    assert result["attribution"]["benchmark_type"] == "510300_proxy"
    assert result["industry_exposure"]["summary"][0]["sector"] == "宽基"
    assert result["style_exposure"]["momentum"]["available"] is True
    assert result["next_plan"]["immediate_next_command"] == "$etf-autopilot"
    assert result["next_plan"]["expected_optimization_goal"]["focus"]

    from service.autopilot_diagnostics import build_next_plan
    goal = build_next_plan(
        {
            "action": "adjust_parameters",
            "performance_problems": ["12_month_oos_excess_return"],
        },
        current_metrics={"oos_12_excess_return": -3.71},
    )["expected_optimization_goal"]
    assert goal["current"] == -3.71


def test_diagnostics_decides_factor_replacement_when_health_and_marginal_fail():
    from service.autopilot_diagnostics import build_autopilot_diagnostics

    def runner(params, start_date, end_date):
        if params["factor_weights"].get("reversal_20d", 0) == 0:
            return {"total_return": 12.0}
        return {"total_return": 10.0}

    result = build_autopilot_diagnostics(
        config={"params": {}},
        baseline_result=_base_result(),
        data_dict=_data(),
        etf_to_sector={"510300": "宽基", "510500": "宽基"},
        start_date="2023-01-01",
        end_date="2023-09-01",
        factor_health=[{"factor_name": "reversal_20d", "status": "failure_candidate"}],
        backtest_runner=runner,
    )

    assert result["decision"]["action"] == "replace_or_reweight_factor_first"
    assert "reversal_20d" in result["decision"]["negative_marginal_factors"]
    assert result["decision"]["replacement_targets"] == ["reversal_20d"]


def test_autopilot_report_writes_operation_log_and_next_plan(tmp_path):
    from service.autopilot_service import write_autopilot_report

    paths = write_autopilot_report(
        tmp_path,
        {"status": "kept_current", "evaluations": []},
        "2026-08-22/autopilot-test",
        operation_log=[{"operation": "基线回测", "data_range": {"start": "2023-01-01"}, "result": {"passed": True}}],
        next_plan={"immediate_next_command": "$etf-autopilot"},
    )

    assert paths["operation_log"].exists()
    assert paths["next_plan"].exists()
    assert json.loads(paths["next_plan"].read_text(encoding="utf-8"))["immediate_next_command"] == "$etf-autopilot"
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "本轮尝试" in markdown
    assert "本轮预期优化目标" in markdown
    assert "决策事实" not in markdown


def test_autopilot_report_describes_budget_stop_without_claiming_auto_continuation(tmp_path):
    from service.autopilot_service import write_autopilot_report

    paths = write_autopilot_report(
        tmp_path,
        {
            "status": "kept_current",
            "reason": "no_candidate_passed_hard_gates",
            "evaluations": [],
            "budget": {"stop_reason": "stagnation"},
        },
        "2026-08-22/autopilot-stop",
        next_plan={"current_action": "adjust_parameters"},
    )

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "本轮搜索停滞，已自动结束" in markdown
    assert "下一轮将自动继续" not in markdown
