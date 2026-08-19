"""应用编排服务，隔离 presentation 与数据存储实现。"""

from pathlib import Path

import pandas as pd

from config.settings import DB_PATH, ETF_UNIVERSE
from data.sources.hybrid_source import HybridDataSource
from data.storage.db import get_db, init_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo
from service.data_service import ensure_data_ready
from strategy.benchmark import PRIMARY_BENCHMARK
from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS
from strategy.scoring import FACTOR_DIRECTIONS, FACTOR_LABELS
from strategy.diagnostics import FactorSnapshot
from service.dto import BacktestResult


class ApplicationService:
    def __init__(self, db_path=DB_PATH, tushare_token=""):
        self.db_path = Path(db_path)
        init_db(self.db_path)
        self._db = get_db(self.db_path)
        self._etf_repo = ETFRepository(self._db)
        self._price_repo = PriceRepository(self._db)
        self._valuation_repo = ValuationRepo(self.db_path)
        self._data_source = HybridDataSource(tushare_token=tushare_token)

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

    def run_backtest(self, selected_codes, start_date, end_date, params, constraints,
                     enable_attribution=False, attribution_benchmark_type='csi300'):
        data_dict = {}
        for code in selected_codes:
            prices = self.get_daily_price(code)
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
