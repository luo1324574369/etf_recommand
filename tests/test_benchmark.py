import unittest
import pandas as pd
import numpy as np
from strategy.benchmark import build_equal_weight_benchmark, build_single_etf_benchmark, build_benchmarks


class TestEqualWeightBenchmark(unittest.TestCase):

    def _make_price_data(self, codes, days=10, start_price=10.0):
        """生成测试用价格数据"""
        dates = pd.date_range('2024-01-01', periods=days, freq='B')
        data_dict = {}
        for code in codes:
            prices = [start_price * (1 + i * 0.01) for i in range(days)]
            data_dict[code] = pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'close': prices,
            })
        return data_dict

    def test_equal_weight_basic(self):
        """等权基准：两只ETF，首日净值为1.0"""
        data = self._make_price_data(['510300', '510500'])
        result = build_equal_weight_benchmark(data)
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 10)
        self.assertAlmostEqual(result.iloc[0]['nav'], 1.0)
        self.assertGreater(result.iloc[-1]['nav'], 1.0)

    def test_equal_weight_first_day_nav_is_one(self):
        """首日净值必须为1.0"""
        data = self._make_price_data(['510300'], days=5)
        result = build_equal_weight_benchmark(data)
        self.assertAlmostEqual(result.iloc[0]['nav'], 1.0)

    def test_equal_weight_with_date_filter(self):
        """日期过滤"""
        data = self._make_price_data(['510300'], days=30)
        result = build_equal_weight_benchmark(
            data, start_date='2024-01-08', end_date='2024-01-19'
        )
        self.assertGreaterEqual(str(result.iloc[0]['date'].date()), '2024-01-08')
        self.assertLessEqual(str(result.iloc[-1]['date'].date()), '2024-01-19')

    def test_equal_weight_empty_data(self):
        """空数据返回空DataFrame"""
        result = build_equal_weight_benchmark({})
        self.assertTrue(result.empty)

    def test_equal_weight_missing_etf_later(self):
        """ETF上市晚：前期不参与计算"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        df1 = pd.DataFrame({
            'trade_date': dates.strftime('%Y-%m-%d'),
            'close': [10 + i * 0.1 for i in range(10)],
        })
        df2 = pd.DataFrame({
            'trade_date': dates[5:].strftime('%Y-%m-%d'),
            'close': [20 + i * 0.1 for i in range(5)],
        })
        data = {'510300': df1, '510500': df2}
        result = build_equal_weight_benchmark(data)
        self.assertEqual(len(result), 10)
        self.assertAlmostEqual(result.iloc[0]['nav'], 1.0)


class TestSingleEtfBenchmark(unittest.TestCase):

    def test_single_etf_basic(self):
        """单ETF基准：首日归一化为1.0"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        data = {
            '510300': pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'close': [10 + i * 0.1 for i in range(10)],
            }),
        }
        result = build_single_etf_benchmark(data, '510300')
        self.assertEqual(len(result), 10)
        self.assertAlmostEqual(result.iloc[0]['nav'], 1.0)
        self.assertGreater(result.iloc[-1]['nav'], 1.0)

    def test_single_etf_not_in_data(self):
        """ETF不在数据池中：返回空DataFrame"""
        result = build_single_etf_benchmark({}, '999999')
        self.assertTrue(result.empty)


class TestBuildBenchmarks(unittest.TestCase):

    def test_build_multiple_benchmarks(self):
        """一次性构建多个基准"""
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        data = {
            '510300': pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'close': [10 + i * 0.1 for i in range(10)],
            }),
            '510500': pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'close': [20 + i * 0.2 for i in range(10)],
            }),
            '159915': pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'close': [15 + i * 0.15 for i in range(10)],
            }),
        }
        configs = [
            {'name': '等权持有', 'type': 'equal_weight'},
            {'name': '沪深300', 'type': 'single_etf', 'code': '510300'},
            {'name': '中证500', 'type': 'single_etf', 'code': '510500'},
        ]
        result = build_benchmarks(data, configs)
        self.assertEqual(len(result), 3)
        self.assertIn('等权持有', result)
        self.assertIn('沪深300', result)
        self.assertIn('中证500', result)
        for name, nav_df in result.items():
            self.assertAlmostEqual(nav_df.iloc[0]['nav'], 1.0)


if __name__ == '__main__':
    unittest.main()
