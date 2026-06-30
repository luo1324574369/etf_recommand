import unittest

from strategy.filters.trend_filter import TrendFilter
from strategy.filters.momentum_filter import MomentumFilter
from strategy.filters.volume_filter import VolumeFilter


class TestTrendFilter(unittest.TestCase):

    def test_above_ma_passes(self):
        f = TrendFilter()
        factor_values = {"trend": {"above_ma": True, "ma_value": 10.0, "price": 11.0}}
        passed, score = f.apply("test", factor_values)
        self.assertTrue(passed)
        self.assertEqual(score, 1.0)

    def test_below_ma_fails(self):
        f = TrendFilter()
        factor_values = {"trend": {"above_ma": False, "ma_value": 10.0, "price": 9.0}}
        passed, score = f.apply("test", factor_values)
        self.assertFalse(passed)
        self.assertEqual(score, 0.0)

    def test_missing_trend_factor(self):
        f = TrendFilter()
        factor_values = {"momentum": 0.1}
        passed, score = f.apply("test", factor_values)
        self.assertFalse(passed)
        self.assertEqual(score, 0.0)


class TestMomentumFilter(unittest.TestCase):

    def test_rank_filtering(self):
        f = MomentumFilter(top_pct=0.5)
        all_factor_values = {
            "etf1": {"momentum": 0.1},
            "etf2": {"momentum": 0.3},
            "etf3": {"momentum": 0.2},
            "etf4": {"momentum": 0.4},
        }
        f.set_universe(all_factor_values)

        passed1, score1 = f.apply("etf1", all_factor_values["etf1"])
        passed2, score2 = f.apply("etf2", all_factor_values["etf2"])
        passed3, score3 = f.apply("etf3", all_factor_values["etf3"])
        passed4, score4 = f.apply("etf4", all_factor_values["etf4"])

        self.assertFalse(passed1)
        self.assertEqual(score1, 0.1)
        self.assertTrue(passed2)
        self.assertEqual(score2, 0.3)
        self.assertFalse(passed3)
        self.assertEqual(score3, 0.2)
        self.assertTrue(passed4)
        self.assertEqual(score4, 0.4)

    def test_top_pct_30(self):
        f = MomentumFilter(top_pct=0.3)
        all_factor_values = {}
        for i in range(10):
            all_factor_values[f"etf{i}"] = {"momentum": float(i) * 0.1}
        f.set_universe(all_factor_values)

        passed_count = 0
        for code, factors in all_factor_values.items():
            passed, _ = f.apply(code, factors)
            if passed:
                passed_count += 1

        self.assertEqual(passed_count, 3)


class TestVolumeFilter(unittest.TestCase):

    def test_above_threshold_passes(self):
        f = VolumeFilter(min_ratio=1.2)
        factor_values = {"volume": 1.5}
        passed, score = f.apply("test", factor_values)
        self.assertTrue(passed)
        self.assertEqual(score, 1.5)

    def test_below_threshold_fails(self):
        f = VolumeFilter(min_ratio=1.2)
        factor_values = {"volume": 1.0}
        passed, score = f.apply("test", factor_values)
        self.assertFalse(passed)
        self.assertEqual(score, 1.0)

    def test_at_threshold_passes(self):
        f = VolumeFilter(min_ratio=1.2)
        factor_values = {"volume": 1.2}
        passed, score = f.apply("test", factor_values)
        self.assertTrue(passed)
        self.assertEqual(score, 1.2)

    def test_missing_volume_factor(self):
        f = VolumeFilter()
        factor_values = {"momentum": 0.1}
        passed, score = f.apply("test", factor_values)
        self.assertFalse(passed)
        self.assertEqual(score, 0.0)


if __name__ == "__main__":
    unittest.main()
