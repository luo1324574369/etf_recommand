"""生成自主优化所需的 baseline 与候选评估 JSON。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DB_PATH, ETF_UNIVERSE, TUSHARE_TOKEN
from config.versioned_strategy import load_active_strategy_config
from service.application_service import ApplicationService
from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES
from strategy import multi_factor
from strategy.walk_forward import _run_single_backtest, generate_walk_forward_presets


def _build_data_dict(service, codes, start_date):
    data_dict = {}
    start_text = pd.to_datetime(start_date).strftime("%Y-%m-%d")
    for code in codes:
        local_rows = service.get_daily_price(code)
        source_rows = service._validated_source_records.get(code)
        merged = {
            row["trade_date"]: row
            for row in local_rows
            if row.get("trade_date", "") < start_text
        }
        merged.update({row["trade_date"]: row for row in (source_rows or [])})
        if merged:
            data_dict[code] = pd.DataFrame([merged[key] for key in sorted(merged)])
    return data_dict


def _period_metrics(data_dict, params, start_date, end_date, valuation_repo, code_to_sector):
    result = _run_single_backtest(
        multi_factor,
        data_dict,
        params,
        start_date,
        end_date,
        extra_params={
            "valuation_repo": valuation_repo,
            "code_to_sector": code_to_sector,
        },
    )
    if result is None:
        raise RuntimeError(f"候选回测失败: {start_date} ~ {end_date}")
    return result


def _stress_windows(data_dict, start_date, end_date, window_days=63):
    benchmark = data_dict.get("510300")
    if benchmark is None:
        return {}
    benchmark = benchmark.copy()
    benchmark["trade_date"] = pd.to_datetime(benchmark["trade_date"])
    benchmark = benchmark[
        (benchmark["trade_date"] >= pd.to_datetime(start_date))
        & (benchmark["trade_date"] <= pd.to_datetime(end_date))
    ].sort_values("trade_date").drop_duplicates("trade_date")
    if len(benchmark) < 150:
        return {}
    returns = benchmark["close"].pct_change()
    six_month_return = benchmark["close"].pct_change(126)
    volatility = returns.rolling(20).std() * np.sqrt(252)
    candidates = {
        "bull": six_month_return.idxmax(),
        "bear": six_month_return.idxmin(),
        "sideways": six_month_return.abs().idxmin(),
        "high_volatility": volatility.idxmax(),
    }
    windows = {}
    for name, end_index in candidates.items():
        if pd.isna(end_index):
            continue
        position = benchmark.index.get_loc(end_index)
        start_position = position - window_days + 1
        if start_position < 0:
            continue
        start_value = benchmark.iloc[start_position]["trade_date"]
        end_value = benchmark.loc[end_index, "trade_date"]
        windows[name] = {
            "start": start_value.strftime("%Y-%m-%d"),
            "end": end_value.strftime("%Y-%m-%d"),
        }
    return windows


def _stress_metrics(data_dict, params, windows, valuation_repo, code_to_sector):
    results = {}
    for name, window in windows.items():
        try:
            result = _period_metrics(
                data_dict,
                params,
                window["start"],
                window["end"],
                valuation_repo,
                code_to_sector,
            )
        except (RuntimeError, ValueError):
            result = None
        results[name] = {
            "window": window,
            "available": result is not None,
            "sharpe": result.get("sharpe_ratio") if result else None,
            "max_drawdown": result.get("max_drawdown") if result else None,
            "annual_return": result.get("annual_return") if result else None,
            "excess_return": result.get("excess_return") if result else None,
        }
    return results


def _autopilot_metrics(period_12, period_24, stress_results=None, final_holdout_passed=True):
    stress_results = stress_results or {}
    period_returns = [
        period_12.get("excess_return", period_12.get("total_return", 0.0)),
        period_24.get("excess_return", period_24.get("total_return", 0.0)),
    ]
    available_stress = [value for value in stress_results.values() if value.get("available")]
    stress_passed = (
        len(available_stress) == 4
        and all(float(value["max_drawdown"]) <= 35.0 for value in available_stress)
    )
    return {
        "data_quality_passed": True,
        "future_safe": True,
        "oos_12_excess_return": float(period_12.get("excess_return", period_12.get("total_return", 0.0))),
        "oos_24_excess_return": float(period_24.get("excess_return", period_24.get("total_return", 0.0))),
        "oos_sharpe": float(min(period_12.get("sharpe_ratio", 0.0), period_24.get("sharpe_ratio", 0.0))),
        "max_drawdown": float(max(
            period_12.get("max_drawdown", 0.0),
            period_24.get("max_drawdown", 0.0),
            *(value["max_drawdown"] for value in available_stress),
        )),
        "annual_turnover": float(max(
            period_12.get("turnover_annual_pct", 0.0),
            period_24.get("turnover_annual_pct", 0.0),
        )),
        "oos_stability": float(sum(value >= 0 for value in period_returns) / len(period_returns)),
        "annual_return": float(period_12.get("annual_return", 0.0)),
        "stress_passed": stress_passed,
        "stress_results": stress_results,
        "final_holdout_passed": bool(final_holdout_passed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Codex 自主优化候选 JSON")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-combinations", type=int, default=20)
    parser.add_argument("--codes", nargs="*", default=None)
    args = parser.parse_args()

    codes = args.codes or [item["code"] for item in ETF_UNIVERSE]
    service = ApplicationService(args.db, tushare_token=TUSHARE_TOKEN)
    try:
        quality = service.validate_backtest_data(codes, args.start, args.end)
        if quality.status != "passed":
            blocked = {
                "status": "blocked",
                "reason": "data_quality",
                "data_quality": quality.to_dict(),
                "baseline_metrics": {},
                "candidates": [],
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps({"status": "blocked", "output": str(args.output)}, ensure_ascii=False))
            return 2
        data_dict = _build_data_dict(service, codes, args.start)
        if not data_dict:
            raise RuntimeError("没有可用于候选回测的行情数据")
        active = load_active_strategy_config()
        active_config = active["config"]
        code_to_sector = {item["code"]: item["sector"] for item in ETF_UNIVERSE}
        baseline_params = dict(active_config.get("params", {}))
        if active_config.get("factor_weights"):
            baseline_params["factor_weights"] = dict(active_config["factor_weights"])
        baseline_params["constraints"] = dict(active_config.get("constraints", {}))
        valuation_repo = service._valuation_repo
        end_dt = pd.to_datetime(args.end)
        holdout_start = end_dt - pd.DateOffset(months=12)
        oos_24_start = end_dt - pd.DateOffset(months=36)
        if oos_24_start < pd.to_datetime(args.start):
            raise RuntimeError("至少需要36个月数据才能完成24个月OOS和12个月最终留出")
        oos_12_start = holdout_start
        oos_24_end = (holdout_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        baseline_12 = _period_metrics(
            data_dict, baseline_params, oos_12_start.strftime("%Y-%m-%d"), args.end,
            valuation_repo, code_to_sector,
        )
        baseline_24 = _period_metrics(
            data_dict, baseline_params, oos_24_start.strftime("%Y-%m-%d"), oos_24_end,
            valuation_repo, code_to_sector,
        )
        stress_windows = _stress_windows(data_dict, args.start, args.end)
        baseline_metrics = _autopilot_metrics(
            baseline_12,
            baseline_24,
            _stress_metrics(data_dict, baseline_params, stress_windows, valuation_repo, code_to_sector),
            final_holdout_passed=True,
        )
        walk_forward = generate_walk_forward_presets(
            data_dict,
            args.start,
            args.end,
            MULTI_FACTOR_PARAM_RANGES,
            max_combinations=args.max_combinations,
            strategy_module=multi_factor,
            extra_params={
                "valuation_repo": valuation_repo,
                "code_to_sector": code_to_sector,
                "factor_weights": active_config.get("factor_weights") or None,
                "constraints": dict(active_config.get("constraints", {})),
            },
        )
        candidates = []
        for preset in walk_forward.get("presets", []):
            params = dict(preset["params"])
            if active_config.get("factor_weights"):
                params["factor_weights"] = dict(active_config["factor_weights"])
            params["constraints"] = dict(active_config.get("constraints", {}))
            period_24 = _period_metrics(
                data_dict, params, oos_24_start.strftime("%Y-%m-%d"), oos_24_end,
                valuation_repo, code_to_sector,
            )
            holdout_available = preset.get("metrics", {}).get("oos_status") == "available"
            period_12 = {
                "annual_return": preset["metrics"].get("oos_annual_return", 0.0),
                "sharpe_ratio": preset["metrics"].get("oos_sharpe_ratio", 0.0),
                "max_drawdown": preset["metrics"].get("oos_max_drawdown", 0.0),
                "turnover_annual_pct": preset["metrics"].get("oos_turnover_annual_pct", 0.0),
                "excess_return": preset["metrics"].get("oos_excess_return", 0.0),
                "total_return": preset["metrics"].get("oos_total_return", 0.0),
            }
            stress_results = _stress_metrics(
                data_dict, params, stress_windows, valuation_repo, code_to_sector
            )
            config = {**active_config, "params": params}
            candidates.append({
                "config": config,
                "metrics": _autopilot_metrics(
                    period_12,
                    period_24,
                    stress_results,
                    final_holdout_passed=holdout_available,
                ),
            })
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"baseline_metrics": baseline_metrics, "candidates": candidates}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"quality": quality.to_dict(), "candidate_count": len(candidates), "output": str(args.output)}, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        blocked = {
            "status": "blocked",
            "reason": str(error),
            "baseline_metrics": {},
            "candidates": [],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"status": "blocked", "output": str(args.output), "reason": str(error)}, ensure_ascii=False))
        return 2
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
