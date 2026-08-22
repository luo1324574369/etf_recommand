"""生成自主优化所需的 baseline 与候选评估 JSON。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DB_PATH, ETF_UNIVERSE, TUSHARE_TOKEN
from config.versioned_strategy import load_active_strategy_config
from service.application_service import ApplicationService
from service.autopilot_service import configuration_hash, write_autopilot_report
from service.factor_sandbox import FactorSandbox
from service.autopilot_diagnostics import build_autopilot_diagnostics, build_next_plan
from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES
from strategy import multi_factor
from strategy.walk_forward import _run_single_backtest, generate_walk_forward_presets


def _build_data_dict(service, codes, start_date, end_date=None):
    data_dict = {}
    start_text = pd.to_datetime(start_date).strftime("%Y-%m-%d")
    end_text = pd.to_datetime(end_date).strftime("%Y-%m-%d") if end_date else None
    for code in codes:
        local_rows = service.get_daily_price(code)
        source_rows = service.get_validated_source_records(code)
        merged = {
            row["trade_date"]: row
            for row in local_rows
            if row.get("trade_date", "") < start_text
        }
        merged.update({
            row["trade_date"]: row
            for row in (source_rows or [])
            if end_text is None or row.get("trade_date", "") <= end_text
        })
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


def _full_backtest_result(data_dict, params, start_date, end_date, valuation_repo, code_to_sector):
    return multi_factor.run_backtest(
        data_dict,
        initial_capital=1_000_000,
        start_date=start_date,
        end_date=end_date,
        valuation_repo=valuation_repo,
        code_to_sector=code_to_sector,
        enable_attribution=False,
        **params,
    )


def _plain_health(reports):
    return [asdict(report) if hasattr(report, "__dataclass_fields__") else report for report in reports]


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


def _future_safe(data_dict, end_date):
    end_timestamp = pd.to_datetime(end_date)
    return all(
        not frame.empty and pd.to_datetime(frame["trade_date"]).max() <= end_timestamp
        for frame in data_dict.values()
    )


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


def _autopilot_metrics(
    period_12,
    period_24,
    stress_results=None,
    final_holdout_passed=True,
    future_safe=True,
):
    stress_results = stress_results or {}
    period_returns = [
        period_12.get("excess_return", period_12.get("total_return", 0.0)),
        period_24.get("excess_return", period_24.get("total_return", 0.0)),
    ]
    available_stress = [value for value in stress_results.values() if value.get("available")]
    stress_passed = (
        len(available_stress) == 4
        and len({tuple(value["window"].values()) for value in available_stress}) == 4
        and all(
            value["sharpe"] is not None
            and value["max_drawdown"] is not None
            and np.isfinite(float(value["sharpe"]))
            and np.isfinite(float(value["max_drawdown"]))
            and abs(float(value["max_drawdown"])) <= 35.0
            for value in available_stress
        )
    )
    return {
        "data_quality_passed": True,
        "future_safe": bool(future_safe),
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
        "annual_cost_pct": float(max(
            period_12.get("annual_cost_pct", 0.0),
            period_24.get("annual_cost_pct", 0.0),
        )),
        "oos_stability": float(sum(value >= 0 for value in period_returns) / len(period_returns)),
        "annual_return": float(period_12.get("annual_return", 0.0)),
        "stress_passed": stress_passed,
        "stress_results": stress_results,
        "final_holdout_passed": bool(final_holdout_passed),
    }


def _config_params(config):
    if not isinstance(config, dict):
        raise ValueError("candidate config must be an object")
    params = dict(config.get("params", {}))
    if config.get("factor_weights"):
        params["factor_weights"] = dict(config["factor_weights"])
    params["constraints"] = dict(config.get("constraints", {}))
    return params


def build_search_profiles(param_ranges, search_rounds=3):
    """为一次自主优化生成互补的参数搜索轮次。"""
    if search_rounds <= 0:
        raise ValueError("search_rounds must be positive")

    base = {name: list(values) for name, values in param_ranges.items()}
    profiles = [("balanced", "均衡风险收益", base)]

    if search_rounds >= 2:
        risk_control = {name: list(values) for name, values in base.items()}
        for name in (
            "top_n",
            "rebalance_freq",
            "sector_penalty_factor",
            "lookback_volatility",
        ):
            if risk_control.get(name):
                risk_control[name] = [max(risk_control[name])]
        if risk_control.get("sector_exclude_threshold"):
            risk_control["sector_exclude_threshold"] = [max(risk_control["sector_exclude_threshold"])]
        if len(risk_control.get("drawdown_threshold", [])) > 1:
            risk_control["drawdown_threshold"] = [min(risk_control["drawdown_threshold"])]
        profiles.append(("risk_control", "回撤与换手控制", risk_control))

    if search_rounds >= 3:
        return_recovery = {name: list(values) for name, values in base.items()}
        for name in ("lookback_momentum", "top_n", "sector_penalty_factor"):
            if return_recovery.get(name):
                return_recovery[name] = [min(return_recovery[name]), max(return_recovery[name])]
        for name in ("rebalance_freq", "lookback_volatility"):
            if return_recovery.get(name):
                return_recovery[name] = [min(return_recovery[name])]
        profiles.append(("return_recovery", "收益修复与趋势响应", return_recovery))

    return profiles[:search_rounds]


def _archive_blocked_report(root, payload):
    run_id = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}/candidate-build-{uuid4().hex[:12]}"
    decision = {
        "status": "blocked",
        "reason": payload.get("reason", "candidate_generation_blocked"),
        "data_quality": payload.get("data_quality", {}),
        "repair_attempt": payload.get("repair_attempt"),
        "evaluations": [],
        "operation_log": payload.get("operation_log", []),
        "next_plan": payload.get("next_plan", {}),
    }
    return write_autopilot_report(
        root,
        decision,
        run_id,
        operation_log=decision["operation_log"],
        next_plan=decision["next_plan"],
    )


def _run_factor_sandbox(source_path, rows_path):
    source = Path(source_path).read_text(encoding="utf-8")
    rows = json.loads(Path(rows_path).read_text(encoding="utf-8"))
    result = FactorSandbox().run(source, rows)
    return {
        "passed": True,
        "source_hash": result.source_hash,
        "sample_count": len(result.values),
    }


def revalidate_candidate_payload(
    payload,
    start_date,
    end_date,
    db_path=DB_PATH,
    codes=None,
    version_root=None,
):
    """使用本地行情重新计算候选事实，禁止直接信任外部指标 JSON。"""
    selected_codes = codes or [item["code"] for item in ETF_UNIVERSE]
    operation_log = []
    service = ApplicationService(db_path, tushare_token=TUSHARE_TOKEN)
    try:
        quality = service.validate_backtest_data(selected_codes, start_date, end_date)
        operation_log.append({
            "operation": "数据质量门禁",
            "data_range": {"start": start_date, "end": end_date},
            "result": quality.to_dict(),
        })
        if quality.status != "passed":
            service.refresh_market_data(selected_codes, start_date, end_date)
            quality = service.validate_backtest_data(selected_codes, start_date, end_date)
        if quality.status != "passed":
            raise RuntimeError(f"数据质量阻断: {quality.to_dict()}")
        if service.data_call_count > 200:
            raise RuntimeError("数据调用次数超过200次预算")
        data_dict = _build_data_dict(service, selected_codes, start_date, end_date)
        if not data_dict:
            raise RuntimeError("没有可用于候选回测的行情数据")
        active = load_active_strategy_config(version_root or PROJECT_ROOT / "config" / "strategy_versions")
        code_to_sector = {item["code"]: item["sector"] for item in ETF_UNIVERSE}
        valuation_repo = service.get_valuation_repository()
        end_dt = pd.to_datetime(end_date)
        holdout_start = end_dt - pd.DateOffset(months=12)
        oos_24_start = end_dt - pd.DateOffset(months=36)
        if oos_24_start < pd.to_datetime(start_date):
            raise RuntimeError("至少需要36个月数据才能完成24个月OOS和12个月最终留出")
        oos_24_end = (holdout_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        stress_windows = _stress_windows(data_dict, start_date, end_date)
        future_safe = _future_safe(data_dict, end_date)

        def evaluate(config):
            params = _config_params(config)
            period_12 = _period_metrics(
                data_dict, params, holdout_start.strftime("%Y-%m-%d"), end_date,
                valuation_repo, code_to_sector,
            )
            period_24 = _period_metrics(
                data_dict, params, oos_24_start.strftime("%Y-%m-%d"), oos_24_end,
                valuation_repo, code_to_sector,
            )
            return _autopilot_metrics(
                period_12,
                period_24,
                _stress_metrics(data_dict, params, stress_windows, valuation_repo, code_to_sector),
                final_holdout_passed=True,
                future_safe=future_safe,
            )

        baseline_metrics = evaluate(active["config"])
        baseline_params = _config_params(active["config"])
        baseline_result = _full_backtest_result(
            data_dict, baseline_params, start_date, end_date, valuation_repo, code_to_sector
        )
        factor_health = _plain_health(baseline_result.get("factor_health", []))

        def diagnostic_backtest(params, period_start, period_end):
            return _full_backtest_result(
                data_dict, params, period_start, period_end, valuation_repo, code_to_sector
            )

        diagnostics = build_autopilot_diagnostics(
            config=active["config"],
            baseline_result=baseline_result,
            data_dict=data_dict,
            etf_to_sector=code_to_sector,
            start_date=start_date,
            end_date=end_date,
            factor_health=factor_health,
            backtest_runner=diagnostic_backtest,
            benchmark_etf_codes=["510300"],
        )
        diagnostics["next_plan"] = build_next_plan(
            diagnostics["decision"],
            current_metrics=baseline_metrics,
        )
        operation_log.extend([
            {
                "operation": "基线 12/24 个月 OOS 重新验证",
                "data_range": {"start": str(oos_24_start.date()), "end": end_date},
                "result": baseline_metrics,
            },
            {
                "operation": "基线归因、行业暴露、风格暴露和因子边际贡献诊断",
                "data_range": {"start": start_date, "end": end_date},
                "result": diagnostics["decision"],
            },
        ])
        verified_candidates = []
        for candidate in payload.get("candidates", []):
            config = candidate.get("config") if isinstance(candidate, dict) else None
            if not isinstance(config, dict):
                continue
            verified_candidate = {
                "config": config,
                "metrics": evaluate(config),
            }
            for key in ("optimization_stage", "search_round", "search_profile"):
                if isinstance(candidate, dict) and key in candidate:
                    verified_candidate[key] = candidate[key]
            verified_candidates.append(verified_candidate)
        return {
            "schema_version": 1,
            "generated_by": "revalidate_candidate_payload",
            "data_quality": quality.to_dict(),
            "baseline_metrics": baseline_metrics,
            "diagnostics": diagnostics,
            "next_plan": diagnostics["next_plan"],
            "operation_log": operation_log,
            "candidates": verified_candidates,
        }
    finally:
        service.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Codex 自主优化候选 JSON")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-combinations", type=int, default=20)
    parser.add_argument("--search-rounds", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--max-runtime-seconds", type=float, default=1800.0)
    parser.add_argument("--max-data-calls", type=int, default=200)
    parser.add_argument("--factor-source", type=Path)
    parser.add_argument("--factor-rows", type=Path)
    parser.add_argument("--codes", nargs="*", default=None)
    args = parser.parse_args()
    started_at = time.monotonic()
    operation_log = []
    if bool(args.factor_source) != bool(args.factor_rows):
        parser.error("--factor-source and --factor-rows must be provided together")

    codes = args.codes or [item["code"] for item in ETF_UNIVERSE]
    service = ApplicationService(args.db, tushare_token=TUSHARE_TOKEN)
    try:
        quality = service.validate_backtest_data(codes, args.start, args.end)
        operation_log.append({
            "operation": "数据质量门禁",
            "data_range": {"start": args.start, "end": args.end},
            "result": quality.to_dict(),
        })
        repair_attempt = None
        if quality.status != "passed":
            try:
                repair_attempt = service.refresh_market_data(codes, args.start, args.end)
                quality = service.validate_backtest_data(codes, args.start, args.end)
            except Exception as error:
                repair_attempt = {"error": str(error)}
            operation_log.append({
                "operation": "仅使用批准数据源重抓并重新校验",
                "data_range": {"start": args.start, "end": args.end},
                "result": repair_attempt,
            })
        if quality.status != "passed":
            blocked = {
                "status": "blocked",
                "reason": "data_quality",
                "data_quality": quality.to_dict(),
                "repair_attempt": repair_attempt,
                "operation_log": operation_log,
                "baseline_metrics": {},
                "candidates": [],
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            reports = _archive_blocked_report(args.output.parent, blocked)
            print(json.dumps({
                "status": "blocked",
                "output": str(args.output),
                "reports": {key: str(value) for key, value in reports.items()},
            }, ensure_ascii=False))
            return 2
        if service.data_call_count > args.max_data_calls:
            raise RuntimeError(f"数据调用次数超过{args.max_data_calls}次预算")
        data_dict = _build_data_dict(service, codes, args.start, args.end)
        if not data_dict:
            raise RuntimeError("没有可用于候选回测的行情数据")
        active = load_active_strategy_config()
        active_config = active["config"]
        code_to_sector = {item["code"]: item["sector"] for item in ETF_UNIVERSE}
        baseline_params = dict(active_config.get("params", {}))
        if active_config.get("factor_weights"):
            baseline_params["factor_weights"] = dict(active_config["factor_weights"])
        baseline_params["constraints"] = dict(active_config.get("constraints", {}))
        valuation_repo = service.get_valuation_repository()
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
        future_safe = _future_safe(data_dict, args.end)
        baseline_metrics = _autopilot_metrics(
            baseline_12,
            baseline_24,
            _stress_metrics(data_dict, baseline_params, stress_windows, valuation_repo, code_to_sector),
            final_holdout_passed=True,
            future_safe=future_safe,
        )
        operation_log.append({
            "operation": "验证当前正式版本基线（24个月 OOS + 12个月最终留出）",
            "data_range": {
                "full": {"start": args.start, "end": args.end},
                "oos_24": {"start": oos_24_start.strftime("%Y-%m-%d"), "end": oos_24_end},
                "final_holdout": {"start": oos_12_start.strftime("%Y-%m-%d"), "end": args.end},
            },
            "result": baseline_metrics,
        })
        baseline_result = _full_backtest_result(
            data_dict, baseline_params, args.start, args.end, valuation_repo, code_to_sector
        )
        factor_health_reports = service.build_factor_health_report(args.end)
        factor_health = _plain_health(factor_health_reports)
        if baseline_result.get("factor_health"):
            factor_health = _plain_health(baseline_result["factor_health"])
        csi300_source = None
        try:
            from data.sources.csi300_source import CSI300Source
            csi300_source = CSI300Source(db_path=str(service.db_path), tushare_token=TUSHARE_TOKEN)
        except Exception:
            csi300_source = None

        def diagnostic_backtest(params, period_start, period_end):
            return _full_backtest_result(
                data_dict, params, period_start, period_end, valuation_repo, code_to_sector
            )

        diagnostics = build_autopilot_diagnostics(
            config=active_config,
            baseline_result=baseline_result,
            data_dict=data_dict,
            etf_to_sector=code_to_sector,
            start_date=args.start,
            end_date=args.end,
            factor_health=factor_health,
            backtest_runner=diagnostic_backtest,
            csi300_source=csi300_source,
            benchmark_etf_codes=["510300"],
        )
        diagnostics["next_plan"] = build_next_plan(
            diagnostics["decision"],
            current_metrics=baseline_metrics,
        )
        operation_log.append({
            "operation": "执行基线自动归因、因子贡献、行业暴露和风格暴露诊断",
            "data_range": {"start": args.start, "end": args.end},
            "result": diagnostics["decision"],
        })
        factor_actions = [
            {"factor_name": report["factor_name"], "action": diagnostics["decision"]["action"], "status": report["status"]}
            for report in factor_health
            if report["status"] in {"failure_candidate", "warning"}
        ]
        factor_sandbox = (
            _run_factor_sandbox(args.factor_source, args.factor_rows)
            if args.factor_source else None
        )
        search_profiles = build_search_profiles(MULTI_FACTOR_PARAM_RANGES, args.search_rounds)
        profile_combination_budget = max(
            1, math.ceil(args.max_combinations / len(search_profiles))
        )
        walk_forward_profiles = []
        for search_round, (profile_key, profile_name, profile_ranges) in enumerate(search_profiles, 1):
            walk_forward = generate_walk_forward_presets(
                data_dict,
                args.start,
                args.end,
                profile_ranges,
                max_combinations=profile_combination_budget,
                strategy_module=multi_factor,
                extra_params={
                    "valuation_repo": valuation_repo,
                    "code_to_sector": code_to_sector,
                    "factor_weights": active_config.get("factor_weights") or None,
                    "constraints": dict(active_config.get("constraints", {})),
                },
            )
            walk_forward_profiles.append((search_round, profile_key, profile_name, walk_forward))
            operation_log.append({
                "operation": f"第{search_round}轮{profile_name}参数搜索",
                "data_range": {"start": args.start, "end": args.end},
                "result": {
                    "search_profile": profile_key,
                    "combination_budget": profile_combination_budget,
                    "tested_combinations": walk_forward.get("total_combinations", 0),
                    "preset_count": len(walk_forward.get("presets", [])),
                },
            })
            if time.monotonic() - started_at > args.max_runtime_seconds:
                raise RuntimeError("候选生成超过运行时间预算")
        candidates = []
        if diagnostics["decision"]["action"] == "replace_or_reweight_factor_first":
            factor_rows = diagnostics["factor_attribution"].get("factors", [])
            failed_factors = set(diagnostics["decision"].get("replacement_targets", []))
            weights = {
                row["factor"]: float(row["weight"])
                for row in factor_rows
                if row.get("factor") not in failed_factors
            }
            total_weight = sum(weights.values())
            if total_weight > 0 and len(weights) < len(factor_rows):
                weights = {name: value / total_weight for name, value in weights.items()}
                reweight_params = dict(active_config.get("params", {}))
                reweight_params["factor_weights"] = weights
                reweight_params["force_factor_weights"] = True
                period_12 = _period_metrics(
                    data_dict, reweight_params, oos_12_start.strftime("%Y-%m-%d"), args.end,
                    valuation_repo, code_to_sector,
                )
                period_24 = _period_metrics(
                    data_dict, reweight_params, oos_24_start.strftime("%Y-%m-%d"), oos_24_end,
                    valuation_repo, code_to_sector,
                )
                config = {
                    **active_config,
                    "params": reweight_params,
                    "factor_weights": weights,
                }
                candidates.append({
                    "config": config,
                    "optimization_stage": "factor_reweighting",
                    "metrics": _autopilot_metrics(
                        period_12,
                        period_24,
                        _stress_metrics(data_dict, reweight_params, stress_windows, valuation_repo, code_to_sector),
                        final_holdout_passed=True,
                        future_safe=future_safe,
                    ),
                })
                operation_log.append({
                    "operation": "生成失效因子降权候选并执行 OOS",
                    "data_range": {
                        "oos_24": {"start": oos_24_start.strftime("%Y-%m-%d"), "end": oos_24_end},
                        "final_holdout": {"start": oos_12_start.strftime("%Y-%m-%d"), "end": args.end},
                    },
                    "result": {"removed_factors": sorted(failed_factors), "metrics": candidates[-1]["metrics"]},
                })
        for search_round, profile_key, profile_name, walk_forward in walk_forward_profiles:
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
                    "optimization_stage": "parameter_search",
                    "search_round": search_round,
                    "search_profile": profile_key,
                    "metrics": _autopilot_metrics(
                        period_12,
                        period_24,
                        stress_results,
                        final_holdout_passed=holdout_available,
                        future_safe=future_safe,
                    ),
                })
                operation_log.append({
                    "operation": f"验证第{search_round}轮{profile_name}参数候选",
                    "data_range": {
                        "oos_24": {"start": oos_24_start.strftime("%Y-%m-%d"), "end": oos_24_end},
                        "final_holdout": {"start": oos_12_start.strftime("%Y-%m-%d"), "end": args.end},
                    },
                    "result": {
                        "search_profile": profile_key,
                        "metrics": candidates[-1]["metrics"],
                    },
                })

        unique_candidates = []
        seen_hashes = set()
        for candidate in candidates:
            candidate_hash = configuration_hash(candidate["config"])
            if candidate_hash in seen_hashes:
                continue
            seen_hashes.add(candidate_hash)
            unique_candidates.append(candidate)
        candidates = unique_candidates[:args.max_combinations]
        operation_log.append({
            "operation": "合并去重全部搜索轮次并交由评估器择优",
            "data_range": {"start": args.start, "end": args.end},
            "result": {
                "search_rounds": len(search_profiles),
                "candidate_count": len(candidates),
                "selection": "硬门槛通过后按风险调整综合评分降序选择最佳候选",
            },
        })
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({
                "schema_version": 1,
                "generated_by": "build_autopilot_candidates",
                "factor_health": factor_health,
                "factor_actions": factor_actions,
                "factor_sandbox": factor_sandbox,
                "diagnostics": diagnostics,
                "next_plan": diagnostics["next_plan"],
                "operation_log": operation_log,
                "baseline_metrics": baseline_metrics,
                "candidates": candidates,
            }, ensure_ascii=False, indent=2),
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
            "operation_log": operation_log,
            "next_plan": {
                "immediate_next_command": "$etf-autopilot",
                "current_action": "repair_data_quality_then_rerun",
                "rollback_triggers": [],
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        reports = _archive_blocked_report(args.output.parent, blocked)
        print(json.dumps({
            "status": "blocked",
            "output": str(args.output),
            "reason": str(error),
            "reports": {key: str(value) for key, value in reports.items()},
        }, ensure_ascii=False))
        return 2
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
