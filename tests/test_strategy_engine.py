import unittest
from datetime import datetime, timedelta

from strategy.engine import StrategyEngine
from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor
from strategy.filters.trend_filter import TrendFilter


class MockPriceRepo:

    def __init__(self, price_data: dict):
        self.price_data = price_data

    def get_daily_price(
        self, code: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        data = self.price_data.get(code, [])
        if start_date:
            data = [item for item in data if item["trade_date"] >= start_date]
        if end_date:
            data = [item for item in data if item["trade_date"] <= end_date]
        return data


def _make_etf_data(base_price, momentum_pct, vol_ratio, n_days=30):
    data = []
    base_date = datetime(2025, 1, 1)
    end_price = base_price * (1 + momentum_pct)
    price_step = (end_price - base_price) / (n_days - 1)
    base_volume = 100000

    for i in range(n_days):
        trade_date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
        close = base_price + price_step * i
        if i >= n_days - 5:
            volume = base_volume * vol_ratio
        else:
            volume = base_volume
        data.append({
            "trade_date": trade_date,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        })
    return data


class TestStrategyEngine(unittest.TestCase):

    def _make_engine_and_repo(self):
        price_data = {
            "etf1": _make_etf_data(base_price=10.0, momentum_pct=0.20, vol_ratio=1.5),
            "etf2": _make_etf_data(base_price=10.0, momentum_pct=0.15, vol_ratio=1.3),
            "etf3": _make_etf_data(base_price=10.0, momentum_pct=0.10, vol_ratio=1.1),
            "etf4": _make_etf_data(base_price=10.0, momentum_pct=-0.10, vol_ratio=0.9),
            "etf5": _make_etf_data(base_price=10.0, momentum_pct=0.05, vol_ratio=1.2),
        }
        repo = MockPriceRepo(price_data)

        factors = [
            MomentumFactor(period=10),
            TrendFactor(period=20),
            VolumeFactor(short_period=5, long_period=20),
        ]
        filters = [TrendFilter(ma_period=20)]
        score_weights = {
            "momentum": 0.6,
            "volume": 0.4,
        }
        engine = StrategyEngine(
            factors=factors,
            filters=filters,
            top_n=3,
            score_weights=score_weights,
        )
        return engine, repo

    def test_run_returns_top_n(self):
        engine, repo = self._make_engine_and_repo()
        results = engine.run(
            etf_codes=["etf1", "etf2", "etf3", "etf4", "etf5"],
            end_date="2025-01-30",
            price_repo=repo,
        )
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)

    def test_results_have_required_fields(self):
        engine, repo = self._make_engine_and_repo()
        results = engine.run(
            etf_codes=["etf1", "etf2", "etf3"],
            end_date="2025-01-30",
            price_repo=repo,
        )
        for result in results:
            self.assertIn("code", result)
            self.assertIn("score", result)
            self.assertIn("rank", result)
            self.assertIn("factor_values", result)

    def test_results_sorted_by_score(self):
        engine, repo = self._make_engine_and_repo()
        results = engine.run(
            etf_codes=["etf1", "etf2", "etf3", "etf5"],
            end_date="2025-01-30",
            price_repo=repo,
        )
        scores = [r["score"] for r in results]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_down_etf_filtered_out(self):
        engine, repo = self._make_engine_and_repo()
        results = engine.run(
            etf_codes=["etf1", "etf2", "etf3", "etf4", "etf5"],
            end_date="2025-01-30",
            price_repo=repo,
        )
        codes = [r["code"] for r in results]
        self.assertNotIn("etf4", codes)

    def test_rank_starts_at_one(self):
        engine, repo = self._make_engine_and_repo()
        results = engine.run(
            etf_codes=["etf1", "etf2", "etf3"],
            end_date="2025-01-30",
            price_repo=repo,
        )
        if results:
            self.assertEqual(results[0]["rank"], 1)

    def test_check_exit_below_ma(self):
        price_data = {
            "etf1": _make_etf_data(base_price=10.0, momentum_pct=-0.15, vol_ratio=0.8),
        }
        repo = MockPriceRepo(price_data)
        holdings = {
            "etf1": {"cost_basis": 10.0},
        }
        engine = StrategyEngine(factors=[], filters=[])
        signals = engine.check_exit(holdings, "2025-01-30", repo)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["code"], "etf1")
        self.assertEqual(signals[0]["action"], "sell")
        self.assertIn("below_ma20", signals[0]["reasons"])

    def test_check_exit_stop_loss(self):
        base_price = 10.0
        price_data = {
            "etf1": _make_etf_data(base_price=base_price, momentum_pct=-0.10, vol_ratio=1.0),
        }
        repo = MockPriceRepo(price_data)
        holdings = {
            "etf1": {"cost_basis": base_price},
        }
        engine = StrategyEngine(factors=[], filters=[])
        signals = engine.check_exit(holdings, "2025-01-30", repo)
        self.assertGreaterEqual(len(signals), 1)
        self.assertEqual(signals[0]["code"], "etf1")
        self.assertIn("stop_loss_8pct", signals[0]["reasons"])

    def test_check_exit_no_signal(self):
        price_data = {
            "etf1": _make_etf_data(base_price=10.0, momentum_pct=0.20, vol_ratio=1.5),
        }
        repo = MockPriceRepo(price_data)
        holdings = {
            "etf1": {"cost_basis": 9.0},
        }
        engine = StrategyEngine(factors=[], filters=[])
        signals = engine.check_exit(holdings, "2025-01-30", repo)
        self.assertEqual(len(signals), 0)


if __name__ == "__main__":
    unittest.main()
