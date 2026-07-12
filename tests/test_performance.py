import unittest
import pandas as pd
import numpy as np
from strategy.performance import calc_metrics, calc_drawdown_series


class TestCalcMetrics(unittest.TestCase):

    def _make_nav_df(self, returns, start_date='2024-01-01'):
        """从日收益率列表生成净值DataFrame

        净值序列以1.0为起点，再依次应用日收益率，共 len(returns)+1 个点。
        """
        dates = pd.date_range(start_date, periods=len(returns) + 1, freq='B')
        nav = 1.0
        nav_list = [nav]
        for r in returns:
            nav *= (1 + r)
            nav_list.append(nav)
        return pd.DataFrame({'date': dates, 'nav': nav_list})

    def test_basic_metrics(self):
        """基本指标计算"""
        nav_df = self._make_nav_df([0.01] * 10)
        m = calc_metrics(nav_df)
        self.assertIn('total_return', m)
        self.assertIn('annual_return', m)
        self.assertIn('volatility', m)
        self.assertIn('sharpe_ratio', m)
        self.assertIn('sortino_ratio', m)
        self.assertIn('max_drawdown', m)
        self.assertIn('calmar_ratio', m)
        self.assertAlmostEqual(m['total_return'], 10.46, places=1)
        self.assertAlmostEqual(m['max_drawdown'], 0.0, places=2)

    def test_negative_returns(self):
        """下跌行情"""
        nav_df = self._make_nav_df([-0.01] * 10)
        m = calc_metrics(nav_df)
        self.assertLess(m['total_return'], 0)
        self.assertGreater(m['max_drawdown'], 0)

    def test_sharpe_ratio_positive(self):
        """正收益正夏普"""
        nav_df = self._make_nav_df([0.01, -0.005, 0.01, -0.005, 0.01])
        m = calc_metrics(nav_df)
        self.assertGreater(m['sharpe_ratio'], 0)

    def test_volatility_zero(self):
        """净值不变（空仓）：波动率为0"""
        nav_df = self._make_nav_df([0.0] * 10)
        m = calc_metrics(nav_df)
        self.assertAlmostEqual(m['volatility'], 0.0, places=4)
        self.assertAlmostEqual(m['sharpe_ratio'], 0.0, places=4)

    def test_calmar_ratio(self):
        """卡玛比率 = 年化收益 / 最大回撤"""
        nav_df = self._make_nav_df([0.02, -0.05, 0.02, 0.02, 0.02])
        m = calc_metrics(nav_df)
        if m['max_drawdown'] > 0:
            self.assertGreater(m['calmar_ratio'], 0)

    def test_sortino_no_downside(self):
        """无下跌日：sortino为inf"""
        nav_df = self._make_nav_df([0.01] * 10)
        m = calc_metrics(nav_df)
        self.assertEqual(m['sortino_ratio'], float('inf'))


class TestCalcDrawdownSeries(unittest.TestCase):

    def test_drawdown_basic(self):
        """回撤序列计算"""
        nav_df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=5, freq='B'),
            'nav': [1.0, 1.1, 1.0, 0.9, 1.05],
        })
        dd = calc_drawdown_series(nav_df)
        self.assertEqual(len(dd), 5)
        self.assertAlmostEqual(dd.iloc[0]['drawdown'], 0.0, places=4)
        self.assertAlmostEqual(dd.iloc[2]['drawdown'], (1.0 - 1.1) / 1.1 * 100, places=2)
        self.assertAlmostEqual(dd.iloc[3]['drawdown'], (0.9 - 1.1) / 1.1 * 100, places=2)
        self.assertTrue((dd['drawdown'] <= 0).all())

    def test_drawdown_monotonic_increase(self):
        """净值持续上涨：回撤全为0"""
        nav_df = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=5, freq='B'),
            'nav': [1.0, 1.1, 1.2, 1.3, 1.4],
        })
        dd = calc_drawdown_series(nav_df)
        self.assertTrue((dd['drawdown'] == 0.0).all())


if __name__ == '__main__':
    unittest.main()
