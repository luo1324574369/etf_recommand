"""应用编排服务，隔离 presentation 与数据存储实现。"""

from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess
from uuid import uuid4

import pandas as pd

from config.settings import DB_PATH, ETF_UNIVERSE
from data.sources.hybrid_source import HybridDataSource
from data.storage.db import get_db, init_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo
from data.storage.market_data_repo import MarketDataRepository
from service.data_service import ensure_data_ready
from strategy.benchmark import PRIMARY_BENCHMARK
from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS
from strategy.scoring import FACTOR_DIRECTIONS, FACTOR_LABELS
from strategy.diagnostics import FactorSnapshot
from service.dto import BacktestResult
from data.contracts import MarketDataSnapshot, DataQualityReport, ValidationIssue
from data.quality import validate_price_records
from service.reporting import ReportArtifact, RunManifest


class DataQualityBlockedError(RuntimeError):
    def __init__(self, report_paths, report):
        self.report_paths = report_paths
        self.report = report
        path_text = ", ".join(str(path) for path in report_paths.values())
        super().__init__(f"数据质量阻断，报告已归档: {path_text}")


def _compare_run_facts(left, right):
    if left is None or right is None:
        return None
    left_result = left.get("result", {})
    right_result = right.get("result", {})
    metrics = (
        "final_value", "total_return", "annual_return", "drawdown", "max_drawdown",
        "sharpe", "sharpe_ratio",
    )
    comparison = {}
    for metric in metrics:
        left_value = left_result.get(metric)
        right_value = right_result.get(metric)
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            comparison[metric] = {
                "current": left_value,
                "reference": right_value,
                "difference": left_value - right_value,
            }
    return comparison


class ApplicationService:
    def __init__(self, db_path=DB_PATH, tushare_token="", report_root=None):
        self.db_path = Path(db_path)
        init_db(self.db_path)
        self._db = get_db(self.db_path)
        self._etf_repo = ETFRepository(self._db)
        self._price_repo = PriceRepository(self._db)
        self._valuation_repo = ValuationRepo(self.db_path)
        self._market_data_repo = MarketDataRepository(self._db)
        self._data_source = HybridDataSource(tushare_token=tushare_token)
        self._report_root = Path(report_root) if report_root else Path(__file__).resolve().parent.parent / "reports"
        self._validated_source_records = {}
        self._last_report_context = {}
        self._data_call_count = 0

    @property
    def data_call_count(self):
        return self._data_call_count

    def get_daily_price(self, code, start_date=None, end_date=None):
        return self._price_repo.get_daily_price(code, start_date, end_date)

    def get_validated_source_records(self, code):
        return list(self._validated_source_records.get(code, []))

    def get_valuation_repository(self):
        return self._valuation_repo

    def refresh_market_data(self, selected_codes, start_date, end_date):
        """仅通过批准数据源重抓行情，不插值、不填充、不猜测。"""
        fetch_start = (pd.to_datetime(start_date) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
        fetch_end = (pd.to_datetime(end_date) + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        refreshed = {}
        for code in selected_codes:
            self._data_call_count += 1
            records = self._data_source.get_daily_price(code, fetch_start, fetch_end)
            refreshed[code] = self._price_repo.insert_daily_price(code, records)
        return refreshed

    def get_etf(self, code):
        return self._etf_repo.get_etf(code)

    def get_pe_percentile(self, code, end_date=None):
        return self._valuation_repo.get_pe_percentile(code, end_date=end_date)

    def get_pe_history(self, code, end_date=None):
        return self._valuation_repo.get_pe_history(code, end_date=end_date)

    def get_active_strategy_config(self):
        from config.versioned_strategy import load_active_strategy_config

        return load_active_strategy_config()

    def run_active_backtest(self, selected_codes, start_date, end_date, constraints=None,
                            enable_attribution=False, attribution_benchmark_type='csi300'):
        active = self.get_active_strategy_config()
        config = active.get("config", {})
        params = dict(config.get("params", {}))
        if config.get("factor_weights"):
            params["factor_weights"] = dict(config["factor_weights"])
        active_constraints = dict(config.get("constraints", {}))
        if constraints:
            active_constraints.update(constraints)
        return self.run_backtest(
            selected_codes,
            start_date,
            end_date,
            params,
            active_constraints,
            enable_attribution=enable_attribution,
            attribution_benchmark_type=attribution_benchmark_type,
        )

    def get_pb_history(self, code, end_date=None):
        getter = getattr(self._valuation_repo, "get_pb_history", None)
        return getter(code, end_date=end_date) if getter else None

    def list_validation_results(self, factor_name=None):
        return self._valuation_repo.list_validation_results(factor_name=factor_name)

    def compute_factor_snapshot(self, selected_codes):
        from strategy.scoring import compute_all_factors, preprocess_factor_cross_section

        etf_factors = {}
        etf_names = {}
        active_factors = []
        for code in selected_codes:
            prices = self._price_repo.get_signal_price(code)
            if len(prices) < 60:
                continue
            factors = compute_all_factors(
                code,
                prices,
                pe_percentile=self.get_pe_percentile(code),
            )
            if not factors:
                continue
            etf_factors[code] = factors
            etf_info = self.get_etf(code)
            etf_names[code] = etf_info.get('name', '') if etf_info else ''
            for factor_name in factors:
                if factor_name not in active_factors:
                    active_factors.append(factor_name)

        if not etf_factors:
            return FactorSnapshot(None, {}, {}, {}, {})

        code_to_group = {
            item['code']: item.get('sector', '其他') for item in ETF_UNIVERSE
        }
        zscores = preprocess_factor_cross_section(
            etf_factors,
            active_factors,
            code_to_group=code_to_group,
        )
        missing_factors = {
            code: [factor for factor in active_factors if factors.get(factor) is None]
            for code, factors in etf_factors.items()
        }
        return FactorSnapshot(
            date=None,
            raw_values=etf_factors,
            normalized_values=zscores,
            missing_factors=missing_factors,
            etf_names=etf_names,
        )

    def compute_factor_history(self, code, factor_names, pe_history=None, pb_history=None):
        from strategy.scoring import compute_factor_history

        prices = self._price_repo.get_signal_price(code)
        return compute_factor_history(
            code,
            prices,
            factor_names,
            pe_history=pe_history,
            pb_history=pb_history,
        )

    def ensure_data_ready(self, selected_codes, start_date, end_date, on_progress=None):
        return ensure_data_ready(
            selected_codes,
            start_date,
            end_date,
            self._data_source,
            self._etf_repo,
            self._price_repo,
            self._valuation_repo,
            on_progress=on_progress,
        )

    def validate_backtest_data(self, selected_codes, start_date, end_date):
        self._validated_source_records = {}
        requested_start = pd.to_datetime(start_date).strftime("%Y-%m-%d")
        requested_end = pd.to_datetime(end_date).strftime("%Y-%m-%d")
        fetch_start = (pd.to_datetime(start_date) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
        fetch_end = (pd.to_datetime(end_date) + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        if self._data_source._tushare:
            records_by_code = {}
            source_issues = []
            for code in selected_codes:
                try:
                    self._data_call_count += 1
                    records_by_code[code] = self._data_source.get_daily_price(code, fetch_start, fetch_end)
                except Exception as error:
                    records_by_code[code] = []
                    source_issues.append(ValidationIssue(
                        rule="source_fetch",
                        code=code,
                        message=f"主数据源获取失败: {error}",
                    ))
            source_name = "tushare_primary_akshare_cross_checked"
        else:
            records_by_code = {
                code: self._counted_daily_price(code, requested_start, fetch_end)
                for code in selected_codes
            }
            source_issues = []
            source_name = "local_db"
        expected_dates = self._expected_trade_dates(
            selected_codes,
            requested_start,
            requested_end,
            records_by_code=records_by_code,
        )
        snapshot = MarketDataSnapshot.from_records(
            records_by_code,
            source=source_name,
            as_of_date=requested_end,
            start_date=requested_start,
            end_date=requested_end,
            expected_dates=expected_dates,
            data_version="local-db-v2" if source_name == "local_db" else "tushare-akshare-v2",
        )
        report = validate_price_records(
            records_by_code,
            expected_dates=expected_dates,
            source_name=source_name,
            as_of_date=requested_end,
            start_date=requested_start,
            end_date=requested_end,
            data_version="local-db-v2" if source_name == "local_db" else "tushare-akshare-v2",
            require_adjustment=True,
            require_next_open=True,
        )
        if source_issues:
            report = DataQualityReport.blocked(
                snapshot.snapshot_id,
                list(report.issues) + source_issues,
                snapshot,
            )
        if report.status == "passed" and self._data_source._tushare:
            self._validated_source_records = records_by_code
        self._market_data_repo.save_snapshot(snapshot, report)
        return report

    def _counted_daily_price(self, code, start_date, end_date):
        self._data_call_count += 1
        return self.get_daily_price(code, start_date, end_date)

    def _expected_trade_dates(self, selected_codes, start_date, end_date, records_by_code=None):
        observed = set()
        if records_by_code:
            observed.update(
                str(row["trade_date"])
                for rows in records_by_code.values()
                for row in rows
                if row.get("trade_date") and start_date <= str(row["trade_date"]) <= end_date
            )
        if selected_codes:
            rows = self._db.execute(
                "SELECT DISTINCT trade_date FROM etf_daily_price "
                "WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
                [start_date, end_date],
            ).fetchall()
            observed.update(str(row[0]) for row in rows)
        if not observed:
            return [date.strftime("%Y-%m-%d") for date in pd.bdate_range(start_date, end_date)]
        return sorted(observed)

    def get_market_snapshot(self, snapshot_id):
        return self._market_data_repo.get_snapshot(snapshot_id)

    def build_factor_health_report(self, as_of_date):
        """从截止日期前最新的正式运行报告生成因子健康状态。"""
        from strategy.factor_lifecycle import health_reports_from_factor_stats

        cutoff = pd.to_datetime(as_of_date).date()
        latest_payload = None
        latest_created_at = None
        for path in self._report_root.rglob("report-data.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                created_at = payload.get("manifest", {}).get("created_at", "")
                created_date = pd.to_datetime(created_at).date()
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if created_date > cutoff or payload.get("status") != "passed":
                continue
            if latest_created_at is None or created_at > latest_created_at:
                latest_created_at = created_at
                latest_payload = payload
        if not latest_payload:
            return []
        diagnostics = latest_payload.get("result", {}).get("factor_diagnostics") or {}
        factor_stats = diagnostics.get("factor_stats")
        if not factor_stats:
            return []
        return health_reports_from_factor_stats(pd.DataFrame(factor_stats))

    def list_factor_candidates(self):
        from service.factor_governance_service import FactorGovernanceService
        from strategy.factor_registry import FactorRegistry

        governance_root = self._report_root / "factor-governance"
        service = FactorGovernanceService(
            governance_root / "candidates.json",
            FactorRegistry(governance_root / "registry.json"),
        )
        return service.list_candidates()

    def rollback_factor(self, factor_name, target_version, operator, reason):
        from service.factor_governance_service import FactorGovernanceService
        from strategy.factor_registry import FactorRegistry

        governance_root = self._report_root / "factor-governance"
        service = FactorGovernanceService(
            governance_root / "candidates.json",
            FactorRegistry(governance_root / "registry.json"),
        )
        return service.rollback_factor(factor_name, target_version, operator, reason)

    def compare_runs(self, current_run_id, previous_run_id=None, shadow_run_id=None):
        """读取归档运行事实，供面板或报告层展示历史对比。"""
        def load_run(run_id, allow_blocked=False):
            if not run_id:
                return None
            matches = list(self._report_root.rglob(f"{run_id}/report-data.json"))
            if not matches:
                raise KeyError(f"run not found: {run_id}")
            payload = json.loads(matches[0].read_text(encoding="utf-8"))
            if not allow_blocked and payload.get("status") != "passed":
                return None
            return payload

        current = load_run(current_run_id, allow_blocked=True)
        previous = load_run(previous_run_id)
        shadow = load_run(shadow_run_id)
        return {
            "current": current,
            "previous": previous,
            "shadow": shadow,
            "current_vs_previous": _compare_run_facts(current, previous),
            "current_vs_shadow": _compare_run_facts(current, shadow),
        }

    def archive_backtest_report(self, result, params, data_report):
        run_date = datetime.now(timezone.utc).date().isoformat()
        run_id = f"{run_date}-{uuid4().hex[:10]}"
        try:
            git_revision = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parent.parent,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            git_revision = "unknown"
        manifest = RunManifest.from_result(
            run_id=run_id,
            status=data_report.status,
            params={
                **params,
                "price_policy": "signal_adjusted_execution_raw",
                "report_mode": "static_ai_ready_external_analysis",
            },
            data_quality=data_report.to_dict(),
            git_revision=git_revision,
            evaluation_stage=params.get("evaluation_stage", "backtest"),
            data_range={
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date"),
            },
            parameter_selection=bool(params.get("parameter_selection", False)),
        )
        report_result = dict(result)
        report_context = self._build_report_context(report_result)
        report_result["historical_comparison"] = report_context
        report_result["factor_candidates"] = [
            candidate.to_dict() for candidate in self.list_factor_candidates()
        ]
        self._last_report_context = {
            "historical_comparison": report_context,
            "factor_candidates": report_result["factor_candidates"],
        }
        return ReportArtifact.write(self._report_root / run_date, manifest, report_result)

    def _build_report_context(self, current_result):
        previous = None
        previous_created_at = ""
        for path in self._report_root.rglob("report-data.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                created_at = payload.get("manifest", {}).get("created_at", "")
            except (OSError, TypeError, json.JSONDecodeError):
                continue
            if payload.get("status") != "passed":
                continue
            if created_at > previous_created_at:
                previous_created_at = created_at
                previous = payload
        current = {"result": current_result}
        shadow_candidates = [
            candidate.to_dict()
            for candidate in self.list_factor_candidates()
            if candidate.stage in {"shadow", "publishable"}
        ]
        current_metrics = {
            key: current_result.get(key)
            for key in ("total_return", "annual_return", "max_drawdown", "sharpe_ratio")
            if isinstance(current_result.get(key), (int, float))
        }
        shadow_comparisons = []
        for candidate in shadow_candidates:
            shadow_metrics = candidate.get("shadow_metrics") or {}
            actual_shadow = (
                shadow_metrics.get("source") == "formal_backtest"
                and bool(shadow_metrics.get("run_id"))
                and shadow_metrics.get("status", "passed") == "passed"
            )
            differences = {
                key: {
                    "current": current_metrics[key],
                    "shadow": shadow_metrics[key],
                    "difference": current_metrics[key] - shadow_metrics[key],
                }
                for key in current_metrics
                if actual_shadow and isinstance(shadow_metrics.get(key), (int, float))
            }
            shadow_comparisons.append({
                "candidate_id": candidate["candidate_id"],
                "metrics": shadow_metrics if actual_shadow else {},
                "comparison_available": actual_shadow,
                "unavailable_reason": None if actual_shadow else "候选指标不是正式影子净值运行证据",
                "comparison": differences,
            })
        return {
            "previous_run_id": previous.get("run_id") if previous else None,
            "current_vs_previous": _compare_run_facts(current, previous),
            "previous_summary": self._run_summary(previous),
            "shadow_candidates": shadow_candidates,
            "current_vs_shadow": shadow_comparisons,
        }

    @staticmethod
    def _run_summary(payload):
        if not payload:
            return None
        result = payload.get("result", {})
        return {
            "run_id": payload.get("run_id"),
            "status": payload.get("status"),
            "final_value": result.get("final_value"),
            "total_return": result.get("total_return"),
            "annual_return": result.get("annual_return"),
            "max_drawdown": result.get("max_drawdown"),
            "sharpe_ratio": result.get("sharpe_ratio"),
        }

    def run_backtest(self, selected_codes, start_date, end_date, params, constraints,
                     enable_attribution=False, attribution_benchmark_type='csi300'):
        data_report = self.validate_backtest_data(
            selected_codes,
            pd.to_datetime(start_date).strftime("%Y-%m-%d"),
            pd.to_datetime(end_date).strftime("%Y-%m-%d"),
        )
        if data_report.status == "blocked":
            report_paths = self.archive_backtest_report({}, params, data_report)
            raise DataQualityBlockedError(report_paths, data_report)
        data_dict = {}
        for code in selected_codes:
            prices = self.get_daily_price(code)
            source_prices = self._validated_source_records.get(code)
            if source_prices:
                merged_prices = {
                    row["trade_date"]: row
                    for row in prices
                    if row.get("trade_date") < pd.to_datetime(start_date).strftime("%Y-%m-%d")
                }
                end_text = pd.to_datetime(end_date).strftime("%Y-%m-%d")
                merged_prices.update({
                    row["trade_date"]: row
                    for row in source_prices
                    if row.get("trade_date", "") <= end_text
                })
                prices = [merged_prices[key] for key in sorted(merged_prices)]
            if prices:
                data_dict[code] = pd.DataFrame(prices)

        full_params = {
            **params,
            "constraints": constraints,
            "valuation_repo": self._valuation_repo,
            "enable_attribution": enable_attribution,
            "attribution_benchmark_type": attribution_benchmark_type,
            "code_to_sector": {item["code"]: item["sector"] for item in ETF_UNIVERSE},
        }
        from strategy import multi_factor
        result = multi_factor.run_backtest(
            data_dict,
            initial_capital=1_000_000,
            start_date=pd.to_datetime(start_date).strftime("%Y-%m-%d"),
            end_date=pd.to_datetime(end_date).strftime("%Y-%m-%d"),
            **full_params,
        )
        report_paths = self.archive_backtest_report(
            result,
            {
                **params,
                "constraints": constraints,
                "start_date": pd.to_datetime(start_date).strftime("%Y-%m-%d"),
                "end_date": pd.to_datetime(end_date).strftime("%Y-%m-%d"),
                "evaluation_stage": params.get("evaluation_stage", "backtest"),
            },
            data_report,
        )
        result["data_quality"] = data_report.to_dict()
        result["report_status"] = data_report.status
        result["report_paths"] = {key: str(path) for key, path in report_paths.items()}
        result.update(self._last_report_context)
        return BacktestResult(result)

    def run_strategy(self, strategy_name, signal_date):
        """运行兼容信号策略并持久化结果。"""
        from service.strategy_service import StrategyService

        return StrategyService(self._db).run_strategy(
            strategy_name,
            signal_date=signal_date,
        )

    def close(self):
        self._db.close()
