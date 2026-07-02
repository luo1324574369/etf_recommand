import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import backtrader as bt
from data.storage.db import init_db, get_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from backtest.data_feed import SQLiteDataFeed


def _make_price_data(n_days=30, start_date="2025-01-01"):
    data = []
    start = datetime.strptime(start_date, "%Y-%m-%d")
    base_price = 10.0
    for i in range(n_days):
        trade_date = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        close = base_price + i * 0.1
        data.append({
            "trade_date": trade_date,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 100000,
            "amount": close * 100000,
        })
    return data


def test_data_feed_loads_prices():
    db_path = "data/test_datafeed.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    init_db(db_path)
    db = get_db(db_path)
    try:
        etf_repo = ETFRepository(db)
        price_repo = PriceRepository(db)
        etf_repo.batch_insert([{"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "指数"}])
        price_repo.insert_daily_price("510300", _make_price_data(10))

        feed = SQLiteDataFeed(
            code="510300",
            price_repo=price_repo,
            fromdate=datetime(2025, 1, 1),
            todate=datetime(2025, 1, 10),
        )

        cerebro = bt.Cerebro()
        cerebro.adddata(feed)
        cerebro.run()

        # 验证数据加载（通过检查 data 是否有数据）
        assert len(feed) > 0, "DataFeed 应该加载到价格数据"
        print(f"✓ SQLiteDataFeed 加载了 {len(feed)} 条数据")
    finally:
        db.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_data_feed_empty_when_no_data():
    db_path = "data/test_datafeed_empty.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    init_db(db_path)
    db = get_db(db_path)
    try:
        price_repo = PriceRepository(db)
        feed = SQLiteDataFeed(
            code="999999",
            price_repo=price_repo,
            fromdate=datetime(2025, 1, 1),
            todate=datetime(2025, 1, 10),
        )
        cerebro = bt.Cerebro()
        cerebro.adddata(feed)
        cerebro.run()
        # 不存在的 code 应该没有数据，不报错
        print("✓ SQLiteDataFeed 无数据时不报错")
    finally:
        db.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def main():
    print("=== 测试 SQLiteDataFeed ===")
    test_data_feed_loads_prices()
    test_data_feed_empty_when_no_data()
    print("\n🎉 所有测试通过！")


if __name__ == "__main__":
    main()
