import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.storage.db import init_db, get_db
from data.storage.etf_repo import ETFRepository


class TestETFRepository(unittest.TestCase):
    test_db_path = "data/test_etf.db"

    def setUp(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        init_db(self.test_db_path)
        self.db = get_db(self.test_db_path)
        self.repo = ETFRepository(self.db)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_batch_insert_and_list_etfs(self):
        etfs = [
            {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "股票型", "listed_date": "2012-05-28", "is_active": 1},
            {"code": "510500", "name": "中证500ETF", "sector": "宽基", "type": "股票型", "listed_date": "2013-02-06", "is_active": 1},
            {"code": "159915", "name": "创业板ETF", "sector": "宽基", "type": "股票型", "listed_date": "2011-12-09", "is_active": 0},
        ]
        self.repo.batch_insert(etfs)

        active_etfs = self.repo.list_etfs(active_only=True)
        self.assertEqual(len(active_etfs), 2)
        self.assertEqual(active_etfs[0]["code"], "510300")
        self.assertEqual(active_etfs[1]["code"], "510500")

        all_etfs = self.repo.list_etfs(active_only=False)
        self.assertEqual(len(all_etfs), 3)
        self.assertEqual(all_etfs[0]["code"], "159915")
        self.assertEqual(all_etfs[1]["code"], "510300")
        self.assertEqual(all_etfs[2]["code"], "510500")

    def test_get_etf(self):
        etfs = [
            {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "股票型", "listed_date": "2012-05-28", "is_active": 1},
        ]
        self.repo.batch_insert(etfs)

        etf = self.repo.get_etf("510300")
        self.assertIsNotNone(etf)
        self.assertEqual(etf["name"], "沪深300ETF")
        self.assertEqual(etf["sector"], "宽基")
        self.assertEqual(etf["type"], "股票型")
        self.assertEqual(etf["listed_date"], "2012-05-28")
        self.assertEqual(etf["is_active"], 1)

        etf_none = self.repo.get_etf("999999")
        self.assertIsNone(etf_none)

    def test_set_active(self):
        etfs = [
            {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "股票型", "listed_date": "2012-05-28", "is_active": 1},
        ]
        self.repo.batch_insert(etfs)

        etf = self.repo.get_etf("510300")
        self.assertEqual(etf["is_active"], 1)

        self.repo.set_active("510300", 0)
        etf = self.repo.get_etf("510300")
        self.assertEqual(etf["is_active"], 0)

        self.repo.set_active("510300", 1)
        etf = self.repo.get_etf("510300")
        self.assertEqual(etf["is_active"], 1)

    def test_insert_etf(self):
        self.repo.insert_etf(
            code="510300",
            name="沪深300ETF",
            sector="宽基",
            etf_type="股票型",
            listed_date="2012-05-28",
            is_active=1,
        )

        etf = self.repo.get_etf("510300")
        self.assertIsNotNone(etf)
        self.assertEqual(etf["name"], "沪深300ETF")
        self.assertEqual(etf["sector"], "宽基")
        self.assertEqual(etf["type"], "股票型")
        self.assertEqual(etf["listed_date"], "2012-05-28")
        self.assertEqual(etf["is_active"], 1)


if __name__ == "__main__":
    unittest.main()
