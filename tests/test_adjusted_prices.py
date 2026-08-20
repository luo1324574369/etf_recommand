import pandas as pd
import pytest


def test_price_repository_persists_adjusted_signal_prices_without_changing_trade_prices(tmp_path):
    from data.storage.db import get_db, init_db
    from data.storage.price_repo import PriceRepository

    db_path = tmp_path / "prices.db"
    init_db(db_path)
    db = get_db(db_path)
    try:
        repository = PriceRepository(db)
        repository.insert_daily_price("510300", [{
            "trade_date": "2025-01-02",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "adj_factor": 1.2,
            "volume": 100,
            "amount": 102000,
        }])

        row = repository.get_daily_price("510300")[0]

        assert row["close"] == 10.2
        assert row["signal_close"] == pytest.approx(12.24)
        assert row["signal_open"] == pytest.approx(12.0)
        assert row["adj_factor"] == pytest.approx(1.2)
    finally:
        db.close()


def test_prepare_data_exposes_adjusted_signal_line_but_keeps_raw_ohlc():
    import backtrader as bt

    from strategy.backtest_utils import _prepare_data

    cerebro = bt.Cerebro()
    _prepare_data(cerebro, {"ETF": pd.DataFrame([{
        "trade_date": "2025-01-02",
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "adj_factor": 1.2,
        "volume": 100,
    }])})

    prepared = cerebro.datas[0].p.dataname
    assert prepared.iloc[0]["close"] == 10.2
    assert prepared.iloc[0]["signal_close"] == pytest.approx(12.24)
