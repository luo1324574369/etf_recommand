import unittest
import pandas as pd
import numpy as np
from strategy.comparator import compare


class TestComparator(unittest.TestCase):

    def _make_nav_df(self, returns, start_date='2024-01-01'):
        """从日收益率列表生成净值DataFrame，首日为1.0"""
        dates = pd.date_range(start_date, periods=len(returns) + 1, freq='B')
        nav = 1.0
        nav_list = [1.0]
        for r in returns:
            nav *= (1 + r)
            nav_list.append(nav)
        return pd.DataFrame({'date': dates, 'nav': nav_list})

    def test_compare_basic_structure(self):
        """基本结构验证"""
        strategy_nav = self._make_nav_df([0.01, 0.02, -0.01, 0.005, 0.015])
        benchmark_navs = {
            '沪深300': self._make_nav_df([0.005, 0.01, -0.005, 0.002, 0.008]),
        }
        result = compare(strategy_nav, benchmark_navs)

        self.assertIn('strategy_metrics', result)
        self.assertIn('benchmark_metrics', result)
        self.assertIn('comparison', result)
        self.assertIn('excess_nav_df', result)
        self.assertIn('drawdown_df', result)

    def test_strategy_metrics_has_all_fields(self):
        """策略指标包含所有字段"""
        strategy_nav = self._make_nav_df([0.01, 0.02, -0.01, 0.005, 0.015])
        benchmark_navs = {'沪深300': self._make_nav_df([0.005] * 5)}
        result = compare(strategy_nav, benchmark_navs)

        sm = result['strategy_metrics']
        for key in ['total_return', 'annual_return', 'volatility', 'sharpe_ratio',
                     'sortino_ratio', 'max_drawdown', 'calmar_ratio']:
            self.assertIn(key, sm)

    def test_comparison_has_all_fields(self):
        """对比指标包含所有字段"""
        strategy_nav = self._make_nav_df([0.01, 0.02, -0.01, 0.005, 0.015])
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, 0.01, -0.005, 0.002, 0.008])}
        result = compare(strategy_nav, benchmark_navs)

        comp = result['comparison']['沪深300']
        for key in ['excess_return', 'information_ratio', 'beta', 'alpha',
                     'win_rate_monthly', 'win_rate_quarterly']:
            self.assertIn(key, comp)

    def test_excess_return_calculation(self):
        """超额收益 = 策略总收益 - 基准总收益"""
        strategy_nav = self._make_nav_df([0.01, 0.01, 0.01, 0.01, 0.01])
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, 0.005, 0.005, 0.005, 0.005])}
        result = compare(strategy_nav, benchmark_navs)

        s_ret = result['strategy_metrics']['total_return']
        b_ret = result['benchmark_metrics']['沪深300']['total_return']
        expected_excess = s_ret - b_ret
        self.assertAlmostEqual(
            result['comparison']['沪深300']['excess_return'],
            expected_excess,
            places=1,
        )

    def test_excess_nav_df_columns(self):
        """超额净值DataFrame包含所有基准列"""
        strategy_nav = self._make_nav_df([0.01] * 10)
        benchmark_navs = {
            '沪深300': self._make_nav_df([0.005] * 10),
            '沪深300': self._make_nav_df([0.008] * 10),
        }
        result = compare(strategy_nav, benchmark_navs)

        excess_df = result['excess_nav_df']
        self.assertIn('date', excess_df.columns)
        self.assertIn('沪深300', excess_df.columns)
        self.assertIn('沪深300', excess_df.columns)
        self.assertAlmostEqual(excess_df.iloc[0]['沪深300'], 1.0, places=4)

    def test_drawdown_df_columns(self):
        """回撤DataFrame包含策略和所有基准列"""
        strategy_nav = self._make_nav_df([0.01, -0.02, 0.01] * 5)
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, -0.01, 0.005] * 5)}
        result = compare(strategy_nav, benchmark_navs)

        dd_df = result['drawdown_df']
        self.assertIn('date', dd_df.columns)
        self.assertIn('strategy', dd_df.columns)
        self.assertIn('沪深300', dd_df.columns)

    def test_win_rate_monthly(self):
        """月度跑赢胜率"""
        strategy_nav = self._make_nav_df(
            [0.01, -0.005, 0.008, 0.002, -0.003, 0.01] * 10
        )
        benchmark_navs = {'沪深300': self._make_nav_df([0.005] * 60)}
        result = compare(strategy_nav, benchmark_navs)

        wr = result['comparison']['沪深300']['win_rate_monthly']
        self.assertIsNotNone(wr)
        self.assertGreaterEqual(wr, 0)
        self.assertLessEqual(wr, 100)

    def test_beta_alpha(self):
        """Beta和Alpha计算"""
        strategy_nav = self._make_nav_df([0.01, -0.005, 0.008, 0.002, -0.003, 0.01] * 5)
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, -0.002, 0.004, 0.001, -0.001, 0.005] * 5)}
        result = compare(strategy_nav, benchmark_navs)

        comp = result['comparison']['沪深300']
        self.assertIsNotNone(comp['beta'])
        self.assertIsNotNone(comp['alpha'])

    def test_information_ratio(self):
        """信息比率计算"""
        strategy_nav = self._make_nav_df([0.01, 0.005, 0.008, 0.002, 0.003, 0.01] * 5)
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, 0.002, 0.004, 0.001, 0.001, 0.005] * 5)}
        result = compare(strategy_nav, benchmark_navs)

        ir = result['comparison']['沪深300']['information_ratio']
        self.assertIsNotNone(ir)

    def test_empty_benchmark_navs(self):
        """空基准字典"""
        strategy_nav = self._make_nav_df([0.01] * 5)
        result = compare(strategy_nav, {})
        self.assertIn('strategy_metrics', result)
        self.assertEqual(len(result['benchmark_metrics']), 0)

    def test_cumulative_return_df(self):
        """累计收益率DataFrame"""
        strategy_nav = self._make_nav_df([0.01, 0.02, -0.01, 0.005, 0.015])
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, 0.01, -0.005, 0.002, 0.008])}
        result = compare(strategy_nav, benchmark_navs)

        cr_df = result['cumulative_return_df']
        self.assertIsInstance(cr_df, pd.DataFrame)
        self.assertIn('date', cr_df.columns)
        self.assertIn('strategy', cr_df.columns)
        self.assertIn('沪深300', cr_df.columns)
        self.assertAlmostEqual(cr_df.iloc[0]['strategy'], 0.0, places=2)
        self.assertAlmostEqual(cr_df.iloc[0]['沪深300'], 0.0, places=2)

    def test_daily_return_df(self):
        """日收益率DataFrame"""
        strategy_nav = self._make_nav_df([0.01, 0.02, -0.01, 0.005, 0.015])
        benchmark_navs = {'沪深300': self._make_nav_df([0.005, 0.01, -0.005, 0.002, 0.008])}
        result = compare(strategy_nav, benchmark_navs)

        dr_df = result['daily_return_df']
        self.assertIsInstance(dr_df, pd.DataFrame)
        self.assertIn('date', dr_df.columns)
        self.assertIn('strategy', dr_df.columns)
        self.assertIn('沪深300', dr_df.columns)
        self.assertTrue(pd.isna(dr_df.iloc[0]['strategy']))

    def test_cumulative_return_values(self):
        """累计收益率计算正确"""
        strategy_nav = self._make_nav_df([0.10])  # nav: [1.0, 1.10]
        benchmark_navs = {'沪深300': self._make_nav_df([0.05])}  # nav: [1.0, 1.05]
        result = compare(strategy_nav, benchmark_navs)

        cr_df = result['cumulative_return_df']
        self.assertEqual(len(cr_df), 2)
        self.assertAlmostEqual(cr_df.iloc[0]['strategy'], 0.0, places=2)
        self.assertAlmostEqual(cr_df.iloc[1]['strategy'], 10.0, places=2)
        self.assertAlmostEqual(cr_df.iloc[1]['沪深300'], 5.0, places=2)


if __name__ == '__main__':
    unittest.main()
