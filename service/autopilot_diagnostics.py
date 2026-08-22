"""自主优化运行的确定性诊断：归因、暴露、因子边际贡献和行动决策。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from strategy.attribution import run_attribution


def _number(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _frame(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, list):
        return pd.DataFrame(value)
    if isinstance(value, dict):
        return pd.DataFrame(value)
    return pd.DataFrame()


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, pd.DataFrame):
        return [_plain(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _factor_names_and_weights(config: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, float]:
    configured = config.get("factor_weights") or {}
    if configured:
        weights = {str(name): max(0.0, _number(value)) for name, value in configured.items()}
    else:
        weight_history = _frame(diagnostics.get("weight_history"))
        weights = {}
        if not weight_history.empty:
            for name in weight_history.columns:
                if name == "date":
                    continue
                values = pd.to_numeric(weight_history[name], errors="coerce").dropna()
                if not values.empty:
                    weights[name] = max(0.0, float(values.mean()))
        if not weights:
            stats = _frame(diagnostics.get("factor_stats"))
            if "factor" in stats.columns:
                for row in stats.to_dict(orient="records"):
                    weights[str(row["factor"])] = max(0.0, _number(row.get("used_weight_mean")))
    weights = {name: value for name, value in weights.items() if value > 0}
    if not weights:
        stats = _frame(diagnostics.get("factor_stats"))
        names = [str(name) for name in stats.get("factor", [])] if "factor" in stats else []
        weights = {name: 1.0 for name in names}
    total = sum(weights.values())
    return {name: value / total for name, value in weights.items()} if total > 0 else {}


def _factor_stats(diagnostics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stats = _frame(diagnostics.get("factor_stats"))
    if "factor" not in stats.columns:
        return {}
    return {
        str(row["factor"]): row
        for row in stats.to_dict(orient="records")
        if row.get("factor") is not None
    }


def _grouped_returns(diagnostics: dict[str, Any], factor: str) -> list[dict[str, Any]]:
    grouped = diagnostics.get("grouped_returns") or {}
    frame = _frame(grouped.get(factor)) if isinstance(grouped, dict) else pd.DataFrame()
    if frame.empty:
        return []
    return [
        {
            "group": int(_number(row.get("group"))),
            "forward_return": _number(row.get("forward_return")),
            "observations": int(_number(row.get("observations"))),
        }
        for row in frame.to_dict(orient="records")
    ]


def _weights_at(trade_log: list[dict[str, Any]], date: str) -> dict[str, float]:
    values: dict[str, float] = {}
    total = 0.0
    for trade in trade_log or []:
        if str(trade.get("date", "")) > str(date):
            continue
        code = str(trade.get("code", ""))
        amount = max(0.0, _number(trade.get("amount")))
        signed = amount if trade.get("direction") == "买入" else -amount
        values[code] = values.get(code, 0.0) + signed
        total += signed
    if total <= 0:
        return {}
    return {code: max(value, 0.0) / total for code, value in values.items() if value > 0}


def compute_industry_exposure(
    trade_log: list[dict[str, Any]],
    etf_to_sector: dict[str, str],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    dates = sorted({str(item.get("date")) for item in trade_log or [] if item.get("date")})
    dates = [start_date, *[date for date in dates if start_date <= date <= end_date], end_date]
    snapshots = []
    for date in sorted(set(dates)):
        weights = _weights_at(trade_log, date)
        sectors: dict[str, float] = {}
        for code, weight in weights.items():
            sector = etf_to_sector.get(code, "未归类")
            sectors[sector] = sectors.get(sector, 0.0) + weight
        if sectors:
            snapshots.append({"date": date, "weights": sectors})
    all_sectors = sorted({sector for row in snapshots for sector in row["weights"]})
    summary = []
    for sector in all_sectors:
        values = [row["weights"].get(sector, 0.0) for row in snapshots]
        summary.append({
            "sector": sector,
            "average_exposure_pct": round(float(np.mean(values) * 100), 6),
            "max_exposure_pct": round(float(np.max(values) * 100), 6),
            "latest_exposure_pct": round(float(values[-1] * 100), 6),
        })
    return {"snapshots": snapshots, "summary": summary, "sample_count": len(snapshots)}


def _latest_style_values(frame: pd.DataFrame, end_date: str) -> dict[str, float | None]:
    if frame.empty or "close" not in frame.columns:
        return {}
    current = frame.copy()
    if "trade_date" in current.columns:
        current["trade_date"] = pd.to_datetime(current["trade_date"], errors="coerce")
        current = current[current["trade_date"] <= pd.to_datetime(end_date)]
    current = current.sort_values("trade_date" if "trade_date" in current.columns else current.index)
    close = pd.to_numeric(current["close"], errors="coerce").dropna()
    if close.empty:
        return {}
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    amount = None
    if "amount" in current.columns:
        amount = pd.to_numeric(current["amount"], errors="coerce").dropna()
    elif "volume" in current.columns:
        amount = (close * pd.to_numeric(current.loc[close.index, "volume"], errors="coerce") * 100).dropna()
    values: dict[str, float | None] = {
        "momentum": float(close.iloc[-1] / close.iloc[-121] - 1) if len(close) > 120 else None,
        "volatility": float(returns.tail(60).std(ddof=1) * np.sqrt(252)) if len(returns) >= 20 else None,
        "liquidity": float(amount.tail(20).mean()) if amount is not None and not amount.empty else None,
        "size": float(np.log(max(amount.tail(60).mean(), 1.0))) if amount is not None and not amount.empty else None,
    }
    for column in ("pe_percentile", "pb_percentile", "pe", "pb"):
        if column in current.columns:
            series = pd.to_numeric(current[column], errors="coerce").dropna()
            if not series.empty:
                raw = float(series.iloc[-1])
                values["value"] = -raw if "percentile" in column else (1.0 / raw if raw > 0 else None)
                break
    return values


def compute_style_exposure(
    data_dict: dict[str, pd.DataFrame],
    trade_log: list[dict[str, Any]],
    end_date: str,
) -> dict[str, Any]:
    weights = _weights_at(trade_log, end_date)
    raw = {code: _latest_style_values(frame, end_date) for code, frame in data_dict.items()}
    styles = {
        "momentum": "momentum",
        "value": "value",
        "volatility": "volatility",
        "liquidity": "liquidity",
        "size_proxy": "size",
    }
    result = {}
    for style, source_name in styles.items():
        available = {code: values[source_name] for code, values in raw.items() if values.get(source_name) is not None}
        if len(available) < 2:
            result[style] = {"available": False, "sample_count": len(available), "exposure": None}
            continue
        series = pd.Series(available, dtype=float)
        std = float(series.std(ddof=0))
        zscores = (series - float(series.mean())) / std if std > 0 else series * 0.0
        exposure = sum(weights.get(code, 0.0) * float(zscores.get(code, 0.0)) for code in available)
        result[style] = {
            "available": True,
            "sample_count": len(available),
            "exposure": round(float(exposure), 6),
            "proxy": "横截面标准化后的现有行情字段",
        }
    return result


def compute_factor_attribution(
    config: dict[str, Any],
    baseline_result: dict[str, Any],
    backtest_runner: Callable[[dict[str, Any], str, str], dict[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    diagnostics = baseline_result.get("factor_diagnostics") or {}
    weights = _factor_names_and_weights(config, diagnostics)
    stats = _factor_stats(diagnostics)
    baseline_return = _number(baseline_result.get("total_return"))
    rows = []
    for factor, weight in weights.items():
        leave_out = dict(weights)
        leave_out[factor] = 0.0
        leave_out = {name: value for name, value in leave_out.items() if value > 0}
        params = dict(config.get("params", {}))
        params["factor_weights"] = leave_out
        params["force_factor_weights"] = True
        try:
            without = backtest_runner(params, start_date, end_date)
            without_return = _number(without.get("total_return"))
            marginal = baseline_return - without_return
            status = "available"
            error = None
        except Exception as exc:
            without_return = None
            marginal = None
            status = "unavailable"
            error = str(exc)
        stat = stats.get(factor, {})
        rows.append({
            "factor": factor,
            "weight": round(weight, 8),
            "rank_ic": _number(stat.get("rank_ic_mean", stat.get("ic", 0.0))),
            "icir": _number(stat.get("icir")),
            "five_group_returns": _grouped_returns(diagnostics, factor),
            "without_factor_return_pct": without_return,
            "marginal_contribution_pct_points": marginal,
            "status": status,
            "error": error,
        })
    available_marginals = [row["marginal_contribution_pct_points"] for row in rows if row["marginal_contribution_pct_points"] is not None]
    denominator = sum(abs(value) for value in available_marginals)
    for row in rows:
        marginal = row["marginal_contribution_pct_points"]
        row["actual_return_contribution_pct_points"] = (
            baseline_return * marginal / denominator if marginal is not None and denominator > 0 else None
        )
    return {
        "method": "leave_one_factor_out_with_fixed_weights",
        "baseline_total_return_pct": baseline_return,
        "factors": rows,
    }


def decide_action(
    factor_health: Iterable[Any],
    factor_attribution: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    health_rows = [_plain(item) for item in factor_health or []]
    failed_factors = [
        str(row.get("factor_name"))
        for row in health_rows
        if row.get("status") in {"failure_candidate", "warning"}
    ]
    negative_marginal = [
        row.get("factor")
        for row in factor_attribution.get("factors", [])
        if row.get("marginal_contribution_pct_points") is not None
        and row["marginal_contribution_pct_points"] < 0
    ]
    replacement_targets = sorted(set(failed_factors) & set(negative_marginal))
    performance_problems = []
    if _number(metrics.get("oos_12_excess_return")) < 0:
        performance_problems.append("12_month_oos_excess_return")
    if _number(metrics.get("oos_24_excess_return")) < 0:
        performance_problems.append("24_month_oos_excess_return")
    if _number(metrics.get("oos_sharpe")) < 0.3:
        performance_problems.append("oos_sharpe")
    if abs(_number(metrics.get("max_drawdown"))) > 35:
        performance_problems.append("max_drawdown")
    if _number(metrics.get("annual_cost_pct")) > 5:
        performance_problems.append("annual_cost_pct")

    if replacement_targets:
        action = "replace_or_reweight_factor_first"
        reason = "因子健康失败且去因子边际贡献为负，先替换或降权因子，再进行参数优化。"
    elif performance_problems:
        action = "adjust_parameters"
        reason = "因子未同时满足替换条件，但绩效或成本存在问题，进入参数调整阶段。"
    else:
        action = "monitor_current_configuration"
        reason = "当前没有足够证据触发替换或参数调整，继续观察下一窗口。"
    return {
        "action": action,
        "reason": reason,
        "failed_factors": failed_factors,
        "negative_marginal_factors": negative_marginal,
        "replacement_targets": replacement_targets,
        "performance_problems": performance_problems,
        "stages": [
            "factor_replacement_or_reweighting" if action == "replace_or_reweight_factor_first" else "parameter_adjustment",
            "oos_revalidation",
            "final_holdout_and_stress_test",
            "publish_immediately_if_all_gates_pass",
        ],
    }


def _expected_optimization_goal(
    decision: dict[str, Any],
    current_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_metrics = current_metrics or {}
    performance_problems = decision.get("performance_problems", [])
    labels = {
        "12_month_oos_excess_return": ("12个月 OOS 超额收益", 0.0, "oos_12_excess_return"),
        "24_month_oos_excess_return": ("24个月 OOS 超额收益", 0.0, "oos_24_excess_return"),
        "oos_sharpe": ("OOS Sharpe", 0.3, "oos_sharpe"),
        "max_drawdown": ("最大回撤", 35.0, "max_drawdown"),
        "annual_cost_pct": ("年化成本", 5.0, "annual_cost_pct"),
    }
    if decision.get("action") == "replace_or_reweight_factor_first":
        targets = decision.get("replacement_targets", [])
        return {
            "focus": "替换或降权失效因子",
            "current": targets,
            "target": "因子通过沙箱、12/24个月 OOS 和压力测试，并且不恶化已通过指标",
            "success_criteria": ["只修改因子组合或权重", "保留数据质量、风险和交易约束"],
        }
    focus = next((problem for problem in labels if problem in performance_problems), None)
    if focus:
        label, threshold, metric_name = labels[focus]
        current = _number(current_metrics.get(metric_name))
        return {
            "focus": label,
            "current": round(current, 6),
            "target": f">= {threshold:g}",
            "success_criteria": [
                "本轮至少消除该硬门槛缺口",
                "不牺牲已通过的 OOS、回撤、成本和压力测试指标",
            ],
        }
    return {
        "focus": "保持当前版本的风险调整后收益质量",
        "current": "当前版本已通过现有门槛",
        "target": "综合评分继续提升至少5%，且风险不恶化",
        "success_criteria": ["不放宽硬门槛", "优先选择可解释、低换手的增量改进"],
    }


def build_next_plan(
    decision: dict[str, Any],
    report_root: str | None = None,
    current_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action = decision.get("action", "monitor_current_configuration")
    if action == "replace_or_reweight_factor_first":
        next_optimization = "优先对失效因子执行降权/替换候选，再与参数候选一起完成 12/24 个月 OOS 和压力测试。"
    elif action == "adjust_parameters":
        next_optimization = "围绕最大绩效缺口依次运行均衡参数、回撤/换手控制、收益修复三类候选，全部完成后按风险调整评分择优。"
    else:
        next_optimization = "保持当前版本，继续监测因子健康和风险指标；出现明确缺口后再生成互补候选。"
    return {
        "immediate_next_command": "$etf-autopilot",
        "current_action": action,
        "next_optimization": next_optimization,
        "expected_optimization_goal": _expected_optimization_goal(decision, current_metrics),
        "next_run": "重新读取本次静态报告，使用最新可用36个月数据，按24个月OOS+12个月最终留出重新验证。",
        "continue_observing": decision.get("failed_factors", []),
        "rollback_triggers": ["数据质量失败", "未来函数或代码异常", "最大回撤超过35%", "连续三个评估窗口风险调整评分恶化"],
        "report_root": report_root,
    }


def build_autopilot_diagnostics(
    config: dict[str, Any],
    baseline_result: dict[str, Any],
    data_dict: dict[str, pd.DataFrame],
    etf_to_sector: dict[str, str],
    start_date: str,
    end_date: str,
    factor_health: Iterable[Any] = (),
    backtest_runner: Callable[[dict[str, Any], str, str], dict[str, Any]] | None = None,
    csi300_source: Any = None,
    benchmark_etf_codes: list[str] | None = None,
) -> dict[str, Any]:
    attribution = None
    attribution_error = None
    if baseline_result.get("trade_list") and not _frame(baseline_result.get("nav_df")).empty:
        try:
            attribution = run_attribution(
                trade_log=baseline_result.get("trade_list", []),
                strategy_nav=_frame(baseline_result.get("nav_df")),
                etf_codes=list(data_dict),
                valuation_repo=type("DataDictRepo", (), {
                    "get_daily_price": lambda self, code: data_dict.get(code, pd.DataFrame()).to_dict("records")
                })(),
                etf_to_sector=etf_to_sector,
                start_date=start_date,
                end_date=end_date,
                benchmark_type="csi300",
                csi300_source=csi300_source,
                benchmark_etf_codes=benchmark_etf_codes or ["510300"],
            )
        except Exception as exc:
            attribution_error = str(exc)
            raise RuntimeError(f"自主优化归因阻断：沪深300和510300代理均不可用: {exc}") from exc

    factor_attribution = {"method": "not_run", "factors": []}
    if backtest_runner is not None:
        factor_attribution = compute_factor_attribution(
            config, baseline_result, backtest_runner, start_date, end_date
        )
    diagnostics = baseline_result.get("factor_diagnostics") or {}
    output = {
        "attribution": _plain(attribution) if attribution is not None else None,
        "attribution_error": attribution_error,
        "factor_attribution": factor_attribution,
        "industry_exposure": compute_industry_exposure(
            baseline_result.get("trade_list", []), etf_to_sector, start_date, end_date
        ),
        "style_exposure": compute_style_exposure(
            data_dict, baseline_result.get("trade_list", []), end_date
        ),
    }
    decision_metrics = {
        "oos_12_excess_return": baseline_result.get("excess_return"),
        "oos_24_excess_return": baseline_result.get("excess_return"),
        "oos_sharpe": baseline_result.get("sharpe_ratio"),
        "max_drawdown": baseline_result.get("max_drawdown"),
        "annual_cost_pct": baseline_result.get("annual_cost_pct"),
    }
    output["decision"] = decide_action(factor_health, factor_attribution, decision_metrics)
    output["next_plan"] = build_next_plan(output["decision"], current_metrics=decision_metrics)
    output["methodology"] = {
        "benchmark_priority": "沪深300，获取失败时使用本地510300；两者都不可用则阻断归因。",
        "factor_marginal_contribution": "固定权重逐因子移除后重跑，与基线总收益差值。",
        "style_fields": ["momentum", "value", "volatility", "liquidity", "size_proxy"],
        "data_range": {"start": start_date, "end": end_date},
    }
    return _plain(output)
