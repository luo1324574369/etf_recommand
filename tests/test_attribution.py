import unittest
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd

from config.settings import ETF_UNIVERSE


class TestAttributionResult(unittest.TestCase):
    """AttributionResult 数据结构"""

    def test_create_result(self):
        from strategy.attribution import AttributionResult
        result = AttributionResult(
            allocation_effect=5.0,
            selection_effect=2.0,
            total_excess=7.0,
            sector_breakdown=pd.DataFrame(),
            period_breakdown=pd.DataFrame(),
            hold_return=3.0,
            switch_return=2.5,
            switch_win_rate=0.6,
            rolling_ir=0.8,
            etf_switch_breakdown=pd.DataFrame(),
            switch_period_breakdown=pd.DataFrame(),
            benchmark_type='equal_weight',
            total_periods=10,
        )
        self.assertAlmostEqual(result.allocation_effect, 5.0)
        self.assertAlmostEqual(result.selection_effect, 2.0)
        self.assertAlmostEqual(result.total_excess, 7.0)
        self.assertAlmostEqual(result.hold_return, 3.0)
        self.assertAlmostEqual(result.switch_return, 2.5)
        self.assertAlmostEqual(result.switch_win_rate, 0.6)
        self.assertEqual(result.benchmark_type, 'equal_weight')
        self.assertEqual(result.total_periods, 10)


class TestComputeEqualWeightBenchmark(unittest.TestCase):
    """等权基准净值计算"""

    def test_equal_weight_two_etfs(self):
        """两只ETF等权组合，一只涨10%，一只跌5%，组合收益2.5%"""
        from strategy.attribution import compute_equal_weight_benchmark

        dates = ['2024-01-02', '2024-01-03', '2024-01-04']
        prices_a = pd.DataFrame({
            'trade_date': dates,
            'close': [1.0, 1.1, 1.1],
        })
        prices_b = pd.DataFrame({
            'trade_date': dates,
            'close': [1.0, 0.95, 0.95],
        })

        class MockRepo:
            def get_daily_price(self, code):
                if code == 'ETF1':
                    return prices_a.to_dict('records')
                elif code == 'ETF2':
                    return prices_b.to_dict('records')
                return []

        nav_df = compute_equal_weight_benchmark(
            ['ETF1', 'ETF2'], MockRepo(), '2024-01-02', '2024-01-04'
        )
        self.assertEqual(len(nav_df), 3)
        self.assertAlmostEqual(nav_df['nav'].iloc[0], 1.0)
        self.assertAlmostEqual(nav_df['nav'].iloc[1], 1.025, places=4)
        self.assertAlmostEqual(nav_df['nav'].iloc[2], 1.025, places=4)


class TestCalcSinglePeriodBF(unittest.TestCase):
    """BF双分项单期归因"""

    def test_bf_two_sectors(self):
        """验证BF双分项公式：配置收益+选品收益

        场景：
        - 2个赛道：消费、医药
        - 每个赛道1只ETF
        - 策略权重：消费60%、医药40%
        - 基准权重：消费50%、医药50%
        - 消费ETF收益10%，医药ETF收益5%
        - 消费赛道收益8%，医药赛道收益6%
        - 基准总收益 = 0.5*8% + 0.5*6% = 7%

        配置收益(赛道择时):
        消费: (0.6-0.5) * (8%-7%) = 0.1%
        医药: (0.4-0.5) * (6%-7%) = 0.1%
        合计: 0.2%

        选品收益(选品/跟踪误差):
        消费: 0.6 * (10%-8%) = 1.2%
        医药: 0.4 * (5%-6%) = -0.4%
        合计: 0.8%

        总超额 = 0.2% + 0.8% = 1.0%
        """
        from strategy.attribution import _calc_single_period_bf

        strategy_weights = {'消费ETF': 0.6, '医药ETF': 0.4}
        benchmark_weights = {'消费': 0.5, '医药': 0.5}
        etf_returns = {'消费ETF': 0.10, '医药ETF': 0.05}
        sector_returns = {'消费': 0.08, '医药': 0.06}
        etf_to_sector = {'消费ETF': '消费', '医药ETF': '医药'}
        benchmark_total_return = 0.07

        result = _calc_single_period_bf(
            strategy_weights=strategy_weights,
            benchmark_weights=benchmark_weights,
            etf_returns=etf_returns,
            sector_returns=sector_returns,
            etf_to_sector=etf_to_sector,
            benchmark_total_return=benchmark_total_return,
        )

        self.assertAlmostEqual(result['allocation_effect'], 0.002, places=4)
        self.assertAlmostEqual(result['selection_effect'], 0.008, places=4)
        self.assertAlmostEqual(result['total_excess'], 0.010, places=4)
        self.assertIn('sector_detail', result)
        self.assertIn('etf_detail', result)

    def test_bf_equal_weights_zero_allocation(self):
        """权重与基准完全相同时，配置收益为0"""
        from strategy.attribution import _calc_single_period_bf

        strategy_weights = {'ETF1': 0.5, 'ETF2': 0.5}
        benchmark_weights = {'赛道A': 0.5, '赛道B': 0.5}
        etf_returns = {'ETF1': 0.10, 'ETF2': 0.05}
        sector_returns = {'赛道A': 0.08, '赛道B': 0.06}
        etf_to_sector = {'ETF1': '赛道A', 'ETF2': '赛道B'}
        benchmark_total_return = 0.07

        result = _calc_single_period_bf(
            strategy_weights=strategy_weights,
            benchmark_weights=benchmark_weights,
            etf_returns=etf_returns,
            sector_returns=sector_returns,
            etf_to_sector=etf_to_sector,
            benchmark_total_return=benchmark_total_return,
        )

        self.assertAlmostEqual(result['allocation_effect'], 0.0, places=4)


class TestCalcSwitchHold(unittest.TestCase):
    """换仓/持有收益拆解"""

    def test_switch_hold_basic(self):
        """验证换仓/持有收益拆解公式

        场景：
        - 上期权重：ETF1=60%, ETF2=40%
        - 本期权重：ETF1=50%, ETF2=50%
        - 本期收益率：ETF1=10%, ETF2=5%

        持有收益（不调仓的固有收益）:
        ETF1: 0.6 * 10% = 6%
        ETF2: 0.4 * 5% = 2%
        合计: 8%

        换仓收益（调仓带来的增量）:
        ETF1: (0.5-0.6) * 10% = -1%
        ETF2: (0.5-0.4) * 5% = 0.5%
        合计: -0.5%

        总收益 = 8% + (-0.5%) = 7.5%
        验证：本期权重×本期收益率 = 0.5*10% + 0.5*5% = 7.5% ✓
        """
        from strategy.attribution import _calc_switch_hold

        prev_weights = {'ETF1': 0.6, 'ETF2': 0.4}
        curr_weights = {'ETF1': 0.5, 'ETF2': 0.5}
        etf_returns = {'ETF1': 0.10, 'ETF2': 0.05}

        result = _calc_switch_hold(
            prev_weights=prev_weights,
            curr_weights=curr_weights,
            etf_returns=etf_returns,
        )

        self.assertAlmostEqual(result['hold_return'], 0.08, places=4)
        self.assertAlmostEqual(result['switch_return'], -0.005, places=4)
        total = 0.5 * 0.10 + 0.5 * 0.05
        self.assertAlmostEqual(
            result['hold_return'] + result['switch_return'],
            total,
            places=4,
        )
        self.assertIn('etf_detail', result)

    def test_no_switch_zero_switch_return(self):
        """权重不变时，换仓收益为0"""
        from strategy.attribution import _calc_switch_hold

        prev_weights = {'ETF1': 0.5, 'ETF2': 0.5}
        curr_weights = {'ETF1': 0.5, 'ETF2': 0.5}
        etf_returns = {'ETF1': 0.10, 'ETF2': 0.05}

        result = _calc_switch_hold(
            prev_weights=prev_weights,
            curr_weights=curr_weights,
            etf_returns=etf_returns,
        )

        self.assertAlmostEqual(result['switch_return'], 0.0, places=4)


class TestRunAttribution(unittest.TestCase):
    """run_attribution 主函数"""

    def _build_simple_scenario(self):
        """构造简单场景：2只ETF，2个调仓期

        ETF1: 消费赛道，价格1.0→1.1→1.2（每期涨10%）
        ETF2: 医药赛道，价格1.0→0.95→0.9（每期跌5%）

        策略：
        第1期：ETF1 60%, ETF2 40%
        第2期：ETF1 50%, ETF2 50%

        等权基准：每期 50% ETF1 + 50% ETF2
        """
        dates = ['2024-01-02', '2024-01-31', '2024-02-29']
        prices_1 = pd.DataFrame({
            'trade_date': dates,
            'close': [1.0, 1.1, 1.2],
        })
        prices_2 = pd.DataFrame({
            'trade_date': dates,
            'close': [1.0, 0.95, 0.9],
        })

        class MockRepo:
            def get_daily_price(self, code):
                if code == 'ETF1':
                    return prices_1.to_dict('records')
                elif code == 'ETF2':
                    return prices_2.to_dict('records')
                return []

        trade_log = [
            {'date': '2024-01-02', 'code': 'ETF1', 'direction': '买入',
             'amount': 60000, 'price': 1.0, 'quantity': 60000},
            {'date': '2024-01-02', 'code': 'ETF2', 'direction': '买入',
             'amount': 40000, 'price': 1.0, 'quantity': 40000},
            {'date': '2024-01-31', 'code': 'ETF1', 'direction': '卖出',
             'amount': 10000, 'price': 1.1, 'quantity': 9091},
            {'date': '2024-01-31', 'code': 'ETF2', 'direction': '买入',
             'amount': 10000, 'price': 0.95, 'quantity': 10526},
        ]

        strategy_nav = pd.DataFrame({
            'date': dates,
            'nav': [1.0, 1.06, 1.095],
        })

        return {
            'repo': MockRepo(),
            'trade_log': trade_log,
            'strategy_nav': strategy_nav,
            'etf_codes': ['ETF1', 'ETF2'],
            'etf_to_sector': {'ETF1': '消费', 'ETF2': '医药'},
            'start_date': '2024-01-02',
            'end_date': '2024-02-29',
            'rebalance_dates': ['2024-01-31'],
        }

    def test_run_attribution_equal_weight(self):
        """等权基准归因测试"""
        from strategy.attribution import run_attribution

        scn = self._build_simple_scenario()
        result = run_attribution(
            trade_log=scn['trade_log'],
            strategy_nav=scn['strategy_nav'],
            etf_codes=scn['etf_codes'],
            valuation_repo=scn['repo'],
            etf_to_sector=scn['etf_to_sector'],
            start_date=scn['start_date'],
            end_date=scn['end_date'],
            rebalance_dates=scn['rebalance_dates'],
            benchmark_type='equal_weight',
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.benchmark_type, 'equal_weight')
        self.assertEqual(result.total_periods, 2)
        self.assertIsInstance(result.sector_breakdown, pd.DataFrame)
        self.assertIsInstance(result.period_breakdown, pd.DataFrame)
        self.assertIsInstance(result.etf_switch_breakdown, pd.DataFrame)
        self.assertIsInstance(result.switch_period_breakdown, pd.DataFrame)
        self.assertTrue(0 <= result.switch_win_rate <= 1)

    def test_empty_trade_log_returns_zero(self):
        """空交易日志返回零结果"""
        from strategy.attribution import run_attribution

        scn = self._build_simple_scenario()
        result = run_attribution(
            trade_log=[],
            strategy_nav=scn['strategy_nav'],
            etf_codes=scn['etf_codes'],
            valuation_repo=scn['repo'],
            etf_to_sector=scn['etf_to_sector'],
            start_date=scn['start_date'],
            end_date=scn['end_date'],
            benchmark_type='equal_weight',
        )

        self.assertEqual(result.total_periods, 0)
        self.assertEqual(result.allocation_effect, 0.0)
        self.assertEqual(result.selection_effect, 0.0)


if __name__ == '__main__':
    unittest.main()
