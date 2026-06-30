import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository


class TestPriceRepository(unittest.TestCase):

    TEST_DB = "data/test_etf.db"

    def setUp(self):
        if os.path.exists(self.TEST_DB):
            os.remove(self.TEST_DB)
        init_db(self.TEST_DB)
        self.db = get_db(self.TEST_DB)
        self.repo = PriceRepository(self.db)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.TEST_DB):
            os.remove(self.TEST_DB)

    def test_insert_and_get_latest_date(self):
        data = [
            {"trade_date": "2026-06-23", "open": 3.5, "high": 3.6, "low": 3.4, "close": 3.55, "volume": 1000000, "amount": 3550000},
            {"trade_date": "2026-06-24", "open": 3.55, "high": 3.65, "low": 3.5, "close": 3.6, "volume": 1200000, "amount": 4320000},
            {"trade_date": "2026-06-25", "open": 3.6, "high": 3.7, "low": 3.55, "close": 3.65, "volume": 1100000, "amount": 4015000},
            {"trade_date": "2026-06-26", "open": 3.65, "high": 3.75, "low": 3.6, "close": 3.7, "volume": 1300000, "amount": 4810000},
            {"trade_date": "2026-06-29", "open": 3.7, "high": 3.8, "low": 3.65, "close": 3.75, "volume": 1500000, "amount": 5625000},
        ]
        count = self.repo.insert_daily_price("510300", data)
        self.assertEqual(count, 5)

        latest_date = self.repo.get_latest_date("510300")
        self.assertEqual(latest_date, "2026-06-29")

    def test_get_daily_price_date_range(self):
        data = [
            {"trade_date": "2026-06-23", "open": 3.5, "high": 3.6, "low": 3.4, "close": 3.55, "volume": 1000000, "amount": 3550000},
            {"trade_date": "2026-06-24", "open": 3.55, "high": 3.65, "low": 3.5, "close": 3.6, "volume": 1200000, "amount": 4320000},
            {"trade_date": "2026-06-25", "open": 3.6, "high": 3.7, "low": 3.55, "close": 3.65, "volume": 1100000, "amount": 4015000},
            {"trade_date": "2026-06-26", "open": 3.65, "high": 3.75, "low": 3.6, "close": 3.7, "volume": 1300000, "amount": 4810000},
            {"trade_date": "2026-06-29", "open": 3.7, "high": 3.8, "low": 3.65, "close": 3.75, "volume": 1500000, "amount": 5625000},
        ]
        self.repo.insert_daily_price("510300", data)

        all_prices = self.repo.get_daily_price("510300")
        self.assertEqual(len(all_prices), 5)

        range_prices = self.repo.get_daily_price("510300", start_date="2026-06-24", end_date="2026-06-26")
        self.assertEqual(len(range_prices), 3)
        self.assertEqual(range_prices[0]["trade_date"], "2026-06-24")
        self.assertEqual(range_prices[-1]["trade_date"], "2026-06-26")

        start_only = self.repo.get_daily_price("510300", start_date="2026-06-25")
        self.assertEqual(len(start_only), 3)

        end_only = self.repo.get_daily_price("510300", end_date="2026-06-25")
        self.assertEqual(len(end_only), 3)

    def test_insert_or_ignore(self):
        data = [
            {"trade_date": "2026-06-23", "open": 3.5, "high": 3.6, "low": 3.4, "close": 3.55, "volume": 1000000, "amount": 3550000},
            {"trade_date": "2026-06-24", "open": 3.55, "high": 3.65, "low": 3.5, "close": 3.6, "volume": 1200000, "amount": 4320000},
        ]
        count = self.repo.insert_daily_price("510300", data)
        self.assertEqual(count, 2)

        count2 = self.repo.insert_daily_price("510300", data)
        self.assertEqual(count2, 0)

    def test_get_latest_price(self):
        data = [
            {"trade_date": "2026-06-23", "open": 3.5, "high": 3.6, "low": 3.4, "close": 3.55, "volume": 1000000, "amount": 3550000},
            {"trade_date": "2026-06-24", "open": 3.55, "high": 3.65, "low": 3.5, "close": 3.6, "volume": 1200000, "amount": 4320000},
            {"trade_date": "2026-06-25", "open": 3.6, "high": 3.7, "low": 3.55, "close": 3.65, "volume": 1100000, "amount": 4015000},
            {"trade_date": "2026-06-26", "open": 3.65, "high": 3.75, "low": 3.6, "close": 3.7, "volume": 1300000, "amount": 4810000},
            {"trade_date": "2026-06-29", "open": 3.7, "high": 3.8, "low": 3.65, "close": 3.75, "volume": 1500000, "amount": 5625000},
        ]
        self.repo.insert_daily_price("510300", data)

        latest = self.repo.get_latest_price("510300")
        self.assertIsNotNone(latest)
        self.assertEqual(latest["trade_date"], "2026-06-29")
        self.assertEqual(latest["close"], 3.75)
        self.assertEqual(latest["open"], 3.7)
        self.assertEqual(latest["high"], 3.8)
        self.assertEqual(latest["low"], 3.65)

    def test_get_latest_date_empty(self):
        result = self.repo.get_latest_date("999999")
        self.assertIsNone(result)

    def test_get_latest_price_empty(self):
        result = self.repo.get_latest_price("999999")
        self.assertIsNone(result)

    def test_batch_insert(self):
        prices_by_code = {
            "510300": [
                {"trade_date": "2026-06-23", "open": 3.5, "high": 3.6, "low": 3.4, "close": 3.55, "volume": 1000000, "amount": 3550000},
                {"trade_date": "2026-06-24", "open": 3.55, "high": 3.65, "low": 3.5, "close": 3.6, "volume": 1200000, "amount": 4320000},
            ],
            "510500": [
                {"trade_date": "2026-06-23", "open": 6.0, "high": 6.1, "low": 5.9, "close": 6.05, "volume": 800000, "amount": 4840000},
                {"trade_date": "2026-06-24", "open": 6.05, "high": 6.15, "low": 6.0, "close": 6.1, "volume": 900000, "amount": 5490000},
                {"trade_date": "2026-06-25", "open": 6.1, "high": 6.2, "low": 6.05, "close": 6.15, "volume": 850000, "amount": 5227500},
            ],
        }
        total = self.repo.batch_insert(prices_by_code)
        self.assertEqual(total, 5)

        self.assertEqual(self.repo.get_latest_date("510300"), "2026-06-24")
        self.assertEqual(self.repo.get_latest_date("510500"), "2026-06-25")


if __name__ == "__main__":
    unittest.main()
