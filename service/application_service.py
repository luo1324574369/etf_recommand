"""应用编排服务，隔离 presentation 与数据存储实现。"""

from pathlib import Path
from datetime import datetime, timezone
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

    def get_daily_price(self, code, start_date=None, end_date=None):
        return self._price_repo.get_daily_price(code, start_date, end_date)

    def get_etf(self, code):
        return self._etf_repo.get_etf(code)

    def get_pe_percentile(self, code, end_date=None):
        return self._valuation_repo.get_pe_percentile(code, end_date=end_date)

    def get_pe_history(self, code, end_date=None):
        return self._valuation_repo.get_pe_history(code, end_date=end_date)

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
            prices = self.get_daily_price(code)
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

        prices = self.get_daily_price(code)
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
        if self._data_source._tushare:
            records_by_code = {}
            source_issues = []
            for code in selected_codes:
                try:
                    records_by_code[code] = self._data_source.get_daily_price(code, start_date, end_date)
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
                code: self.get_daily_price(code, start_date, end_date)
                for code in selected_codes
            }
            source_issues = []
            source_name = "local_db"
        snapshot = MarketDataSnapshot.from_records(
            records_by_code,
            source=source_name,
            as_of_date=end_date,
        )
        report = validate_price_records(
            records_by_code,
            expected_dates=None,
            source_name=source_name,
            as_of_date=end_date,
        )
        if source_issues:
            report = DataQualityReport.blocked(
                snapshot.snapshot_id,
                list(report.issues) + source_issues,
            )
        if report.status == "passed" and self._data_source._tushare:
            self._validated_source_records = records_by_code
        self._market_data_repo.save_snapshot(snapshot, report)
        return report

    def get_market_snapshot(self, snapshot_id):
        return self._market_data_repo.get_snapshot(snapshot_id)

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
            params=params,
            data_quality=data_report.to_dict(),
            git_revision=git_revision,
        )
        return ReportArtifact.write(self._report_root / run_date, manifest, result)

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
                merged_prices.update({row["trade_date"]: row for row in source_prices})
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
            {**params, "constraints": constraints},
            data_report,
        )
        result["data_quality"] = data_report.to_dict()
        result["report_status"] = data_report.status
        result["report_paths"] = {key: str(path) for key, path in report_paths.items()}
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
