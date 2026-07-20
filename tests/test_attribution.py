import unittest
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd

from config.settings import ETF_SECTOR_TO_SW, ETF_UNIVERSE


class TestSectorMapping(unittest.TestCase):
    """ETF sector → 申万行业映射"""

    def test_mapping_exists(self):
        self.assertIsInstance(ETF_SECTOR_TO_SW, dict)

    def test_all_etf_sectors_covered(self):
        """ETF_UNIVERSE 中所有 sector 都在映射里"""
        sectors_in_universe = {etf['sector'] for etf in ETF_UNIVERSE}
        for sector in sectors_in_universe:
            self.assertIn(sector, ETF_SECTOR_TO_SW,
                          f"sector '{sector}' 未在 ETF_SECTOR_TO_SW 中")

    def test_empty_sectors_are_explicit_empty_list(self):
        """宽基/红利/海外 应显式为空列表"""
        self.assertEqual(ETF_SECTOR_TO_SW['宽基'], [])
        self.assertEqual(ETF_SECTOR_TO_SW['红利'], [])
        self.assertEqual(ETF_SECTOR_TO_SW['海外'], [])

    def test_mapped_sectors_nonempty(self):
        """消费/医药/科技 等映射应有内容"""
        self.assertGreater(len(ETF_SECTOR_TO_SW['消费']), 0)
        self.assertGreater(len(ETF_SECTOR_TO_SW['医药']), 0)


class TestCSI300Source(unittest.TestCase):
    """沪深300成分股数据源"""

    def test_class_exists(self):
        from data.sources.csi300_source import CSI300Source
        self.assertTrue(callable(CSI300Source))

    def test_init_with_db_path(self):
        """可指定 db_path 初始化"""
        from data.sources.csi300_source import CSI300Source
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            source = CSI300Source(db_path=db_path, tushare_token='dummy')
            self.assertIsInstance(source, CSI300Source)
        finally:
            os.unlink(db_path)

    def test_cache_table_created(self):
        """初始化时自动创建缓存表"""
        from data.sources.csi300_source import CSI300Source
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            CSI300Source(db_path=db_path, tushare_token='dummy')
            conn = sqlite3.connect(db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='csi300_constituents'"
            ).fetchall()
            conn.close()
            self.assertEqual(len(tables), 1)
        finally:
            os.unlink(db_path)

    def test_fetch_constituents_raises_on_empty_tushare_response(self):
        """严格模式：Tushare 返回空 → 抛 RuntimeError"""
        from data.sources.csi300_source import CSI300Source
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            source = CSI300Source(db_path=db_path, tushare_token='dummy')
            source._tushare = MagicMock()
            source._tushare.index_weight.return_value = pd.DataFrame()
            with self.assertRaises(RuntimeError) as ctx:
                source.fetch_constituents('20240101')
            self.assertIn('沪深300成分股', str(ctx.exception))
        finally:
            os.unlink(db_path)

    def test_fetch_constituents_raises_when_tushare_uninitialized(self):
        """严格模式：Tushare 未初始化 → 抛 RuntimeError"""
        from data.sources.csi300_source import CSI300Source
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            source = CSI300Source(db_path=db_path, tushare_token=None)
            with self.assertRaises(RuntimeError) as ctx:
                source.fetch_constituents('20240101')
            self.assertIn('沪深300成分股', str(ctx.exception))
        finally:
            os.unlink(db_path)

    def test_fetch_constituents_from_cache(self):
        """缓存命中时不调用 Tushare"""
        from data.sources.csi300_source import CSI300Source
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            source = CSI300Source(db_path=db_path, tushare_token='dummy')
            source._tushare = MagicMock()  # 防止真实调用
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO csi300_constituents (trade_date, code, weight, sw_industry) "
                "VALUES (?, ?, ?, ?)",
                ('20240101', '600000.SH', 0.05, '银行')
            )
            conn.commit()
            conn.close()

            df = source.fetch_constituents('20240101')
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]['code'], '600000.SH')
            self.assertAlmostEqual(df.iloc[0]['weight'], 0.05)
            source._tushare.index_weight.assert_not_called()
        finally:
            os.unlink(db_path)

    def test_get_industry_weights_aggregates_by_industry(self):
        """行业权重按申万一级行业聚合"""
        from data.sources.csi300_source import CSI300Source
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            source = CSI300Source(db_path=db_path, tushare_token='dummy')
            conn = sqlite3.connect(db_path)
            conn.executemany(
                "INSERT INTO csi300_constituents (trade_date, code, weight, sw_industry) "
                "VALUES (?, ?, ?, ?)",
                [
                    ('20240101', '600000.SH', 0.10, '银行'),
                    ('20240101', '601318.SH', 0.05, '银行'),
                    ('20240101', '000001.SZ', 0.08, '电子'),
                ]
            )
            conn.commit()
            conn.close()

            weights = source.get_industry_weights('20240101')
            self.assertAlmostEqual(weights['银行'], 0.15)
            self.assertAlmostEqual(weights['电子'], 0.08)
        finally:
            os.unlink(db_path)


class TestBrinsonResult(unittest.TestCase):
    """BrinsonResult 数据结构"""

    def test_dataclass_exists(self):
        from strategy.attribution import BrinsonResult
        result = BrinsonResult(
            allocation_effect=1.0,
            selection_effect=2.0,
            interaction_effect=0.5,
            total_excess=3.5,
            sector_breakdown=pd.DataFrame(),
            period_breakdown=pd.DataFrame(),
        )
        self.assertEqual(result.allocation_effect, 1.0)
        self.assertEqual(result.selection_effect, 2.0)
        self.assertEqual(result.interaction_effect, 0.5)
        self.assertEqual(result.total_excess, 3.5)


class TestBrinsonMath(unittest.TestCase):
    """Brinson 数学正确性测试"""

    def _build_simple_scenario(self):
        """构造简化场景：2 行业，2 ETF

        策略：超配银行(60% vs 基准 50%)，欠配科技(40% vs 50%)
        策略银行收益率 10%，基准银行收益率 8%
        策略科技收益率 5%，基准科技收益率 6%
        基准整体收益率 = 0.5*0.08 + 0.5*0.06 = 7%

        期望:
        BA_银行 = (0.6 - 0.5) * (0.08 - 0.07) = 0.001 = 0.1%
        BA_科技 = (0.4 - 0.5) * (0.06 - 0.07) = 0.001 = 0.1%
        BA_total = 0.2%

        BS_银行 = 0.5 * (0.10 - 0.08) = 0.01 = 1%
        BS_科技 = 0.5 * (0.05 - 0.06) = -0.005 = -0.5%
        BS_total = 0.5%

        BI_银行 = (0.6 - 0.5) * (0.10 - 0.08) = 0.002 = 0.2%
        BI_科技 = (0.4 - 0.5) * (0.05 - 0.06) = 0.001 = 0.1%
        BI_total = 0.3%

        总效应 = 0.2 + 0.5 + 0.3 = 1.0%
        """
        return {
            'strategy_weights': {'银行': 0.6, '科技': 0.4},
            'benchmark_weights': {'银行': 0.5, '科技': 0.5},
            'strategy_returns': {'银行': 0.10, '科技': 0.05},
            'benchmark_returns': {'银行': 0.08, '科技': 0.06},
            'benchmark_total_return': 0.07,
        }

    def test_brinson_calculation(self):
        """验证 Brinson 公式计算正确"""
        from strategy.attribution import _calc_single_period
        scenario = self._build_simple_scenario()
        result = _calc_single_period(
            strategy_weights=scenario['strategy_weights'],
            benchmark_weights=scenario['benchmark_weights'],
            strategy_returns=scenario['strategy_returns'],
            benchmark_returns=scenario['benchmark_returns'],
            benchmark_total_return=scenario['benchmark_total_return'],
        )
        self.assertAlmostEqual(result['allocation_effect'], 0.002, places=4)
        self.assertAlmostEqual(result['selection_effect'], 0.005, places=4)
        self.assertAlmostEqual(result['interaction_effect'], 0.003, places=4)
        self.assertAlmostEqual(result['total_excess'], 0.010, places=4)


class TestBrinsonEmptyAndStrict(unittest.TestCase):
    """Brinson 边界与严格模式测试"""

    def test_empty_trade_log_returns_zero_result(self):
        """无交易记录返回零结果"""
        from strategy.attribution import run_brinson_attribution
        nav_df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=5, freq='B'),
            'nav': [1.0, 1.01, 1.02, 1.01, 1.03],
        })
        bench_df = nav_df.copy()
        source = MagicMock()
        result = run_brinson_attribution(
            trade_log=[],
            strategy_nav=nav_df,
            benchmark_nav=bench_df,
            csi300_source=source,
            etf_sector_map={'510300': '未归类'},
            start_date='2024-01-01',
            end_date='2024-01-05',
        )
        self.assertEqual(result.allocation_effect, 0.0)
        self.assertEqual(result.selection_effect, 0.0)
        self.assertEqual(result.interaction_effect, 0.0)
        self.assertEqual(result.total_excess, 0.0)

    def test_strict_mode_raises_on_data_failure(self):
        """严格模式：CSI300Source 抛 RuntimeError → 归因也抛 RuntimeError"""
        from strategy.attribution import run_brinson_attribution
        nav_df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=5, freq='B'),
            'nav': [1.0, 1.01, 1.02, 1.01, 1.03],
        })
        bench_df = nav_df.copy()
        source = MagicMock()
        source.get_industry_weights.side_effect = RuntimeError('Tushare 积分不足')

        trade_log = [
            {'date': '2024-01-02', 'code': '512800', 'direction': '买入',
             'amount': 100000, 'price': 10, 'quantity': 10000},
        ]
        with self.assertRaises(RuntimeError) as ctx:
            run_brinson_attribution(
                trade_log=trade_log,
                strategy_nav=nav_df,
                benchmark_nav=bench_df,
                csi300_source=source,
                etf_sector_map={'512800': '银行'},
                start_date='2024-01-01',
                end_date='2024-01-05',
                rebalance_dates=['2024-01-02'],
            )
        self.assertIn('Brinson 归因数据不完整', str(ctx.exception))


class TestBacktestAttributionIntegration(unittest.TestCase):
    """回测集成归因（默认关闭）"""

    def test_attribution_disabled_by_default(self):
        """不启用归因时，result['attribution'] 应为 None"""
        from strategy.backtest_utils import run_backtest
        from strategy.multi_factor import MultiFactorStrategy

        dates = pd.date_range('2024-01-01', periods=260, freq='B')
        data = {}
        for code in ['510300', '510500']:
            data[code] = pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'open': 10, 'high': 10.5, 'low': 9.5,
                'close': [10 + i * 0.01 for i in range(260)],
                'volume': 1000000,
            })
        result = run_backtest(
            MultiFactorStrategy,
            data,
            start_date='2024-06-01',
            end_date='2024-12-31',
            lookback_momentum=60,
            lookback_volatility=60,
            top_n=2,
            rebalance_freq=20,
        )
        self.assertIsNone(result.get('attribution'))


if __name__ == '__main__':
    unittest.main()
