import backtrader as bt
import pandas as pd

from strategy.backtest_utils import _prepare_data


def test_prepare_data_limits_warmup_and_end_date():
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    prices = pd.DataFrame({
        "trade_date": dates,
        "open": range(10),
        "high": range(10),
        "low": range(10),
        "close": range(1, 11),
        "volume": [100] * 10,
    })
    cerebro = bt.Cerebro()

    _prepare_data(
        cerebro,
        {"ETF": prices},
        start_date="2025-01-06",
        end_date="2025-01-09",
        lookback_long=2,
    )

    prepared = cerebro.datas[0].p.dataname
    assert list(prepared.index.strftime("%Y-%m-%d")) == [
        "2025-01-04",
        "2025-01-05",
        "2025-01-06",
        "2025-01-07",
        "2025-01-08",
        "2025-01-09",
    ]
