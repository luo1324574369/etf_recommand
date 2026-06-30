import unittest
from datetime import datetime, timedelta

from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor


def _make_price_data(closes, volumes=None):
    data = []
    base_date = datetime(2025, 1, 1)
    for i, close in enumerate(closes):
        trade_date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        volume = volumes[i] if volumes else 100000
        data.append({
            "trade_date": trade_date,
            "close": close,
            "volume": volume,
        })
    return data


class TestMomentumFactor(unittest.TestCase):

    def test_10day_momentum(self):
        closes = [10.0] * 10 + [11.0]
        price_data = _make_price_data(closes)
        factor = MomentumFactor(period=10)
        result = factor.calculate("test", price_data, "2025-01-11")
        self.assertAlmostEqual(result, 0.1)

    def test_momentum_negative(self):
        closes = [10.0] * 10 + [9.0]
        price_data = _make_price_data(closes)
        factor = MomentumFactor(period=10)
        result = factor.calculate("test", price_data, "2025-01-11")
        self.assertAlmostEqual(result, -0.1)

    def test_momentum_insufficient_data(self):
        closes = [10.0, 11.0]
        price_data = _make_price_data(closes)
        factor = MomentumFactor(period=10)
        result = factor.calculate("test", price_data, "2025-01-02")
        self.assertIsNone(result)


class TestTrendFactor(unittest.TestCase):

    def test_above_ma20(self):
        closes = [10.0] * 20 + [11.0]
        price_data = _make_price_data(closes)
        factor = TrendFactor(period=20)
        result = factor.calculate("test", price_data, "2025-01-21")
        self.assertEqual(result["ma_value"], 10.0)
        self.assertEqual(result["price"], 11.0)
        self.assertTrue(result["above_ma"])

    def test_below_ma20(self):
        closes = [10.0] * 20 + [9.0]
        price_data = _make_price_data(closes)
        factor = TrendFactor(period=20)
        result = factor.calculate("test", price_data, "2025-01-21")
        self.assertEqual(result["ma_value"], 10.0)
        self.assertEqual(result["price"], 9.0)
        self.assertFalse(result["above_ma"])

    def test_ma_insufficient_data(self):
        closes = [10.0] * 5
        price_data = _make_price_data(closes)
        factor = TrendFactor(period=20)
        result = factor.calculate("test", price_data, "2025-01-05")
        self.assertIsNone(result)


class TestVolumeFactor(unittest.TestCase):

    def test_volume_expanding(self):
        closes = [10.0] * 25
        volumes = [100000] * 20 + [150000] * 5
        price_data = _make_price_data(closes, volumes)
        factor = VolumeFactor(short_period=5, long_period=20)
        result = factor.calculate("test", price_data, "2025-01-25")
        self.assertAlmostEqual(result, 1.5)

    def test_volume_shrinking(self):
        closes = [10.0] * 25
        volumes = [100000] * 20 + [80000] * 5
        price_data = _make_price_data(closes, volumes)
        factor = VolumeFactor(short_period=5, long_period=20)
        result = factor.calculate("test", price_data, "2025-01-25")
        self.assertAlmostEqual(result, 0.8)

    def test_volume_insufficient_data(self):
        closes = [10.0] * 5
        volumes = [100000] * 5
        price_data = _make_price_data(closes, volumes)
        factor = VolumeFactor(short_period=5, long_period=20)
        result = factor.calculate("test", price_data, "2025-01-05")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
