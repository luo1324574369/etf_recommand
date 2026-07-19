import unittest
import pandas as pd
import numpy as np
from strategy.benchmark import (
    build_single_etf_benchmark,
    build_benchmarks,
    DEFAULT_BENCHMARKS,
    PRIMARY_BENCHMARK,
)


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


class TestPrimaryBenchmarkConstant(unittest.TestCase):
    """验证主基准常量与默认基准列表"""

    def test_primary_benchmark_value(self):
        """PRIMARY_BENCHMARK 必须是沪深300"""
        self.assertEqual(PRIMARY_BENCHMARK, '沪深300')

    def test_default_benchmarks_only_csi300(self):
        """DEFAULT_BENCHMARKS 只剩沪深300"""
        self.assertEqual(len(DEFAULT_BENCHMARKS), 1)
        self.assertEqual(DEFAULT_BENCHMARKS[0]['name'], '沪深300')
        self.assertEqual(DEFAULT_BENCHMARKS[0]['type'], 'single_etf')
        self.assertEqual(DEFAULT_BENCHMARKS[0]['code'], '510300')

    def test_no_equal_weight_in_defaults(self):
        """DEFAULT_BENCHMARKS 不应包含 equal_weight 类型"""
        for cfg in DEFAULT_BENCHMARKS:
            self.assertNotEqual(cfg['type'], 'equal_weight')


class TestBuildBenchmarksSingle(unittest.TestCase):
    """build_benchmarks 默认调用只返回沪深300"""

    def test_default_returns_only_csi300(self):
        dates = pd.date_range('2024-01-01', periods=10, freq='B')
        data = {
            '510300': pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'close': [10 + i * 0.1 for i in range(10)],
            }),
        }
        result = build_benchmarks(data)
        self.assertEqual(len(result), 1)
        self.assertIn('沪深300', result)


if __name__ == '__main__':
    unittest.main()
