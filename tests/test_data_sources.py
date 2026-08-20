import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _FakeTushare:
    def fund_daily(self, **kwargs):
        assert kwargs["ts_code"] == "510300.SH"
        return pd.DataFrame([{
            "trade_date": "20250102", "open": 3.9, "high": 4.1,
            "low": 3.8, "close": 4.0, "vol": 100, "amount": 400,
        }])


def test_tushare_is_primary_and_akshare_is_cross_checked(monkeypatch):
    from data.sources.hybrid_source import HybridDataSource

    monkeypatch.setattr(
        "data.sources.hybrid_source.ak.fund_etf_hist_sina",
        lambda symbol: pd.DataFrame([{
            "date": "2025-01-02", "open": 3.9, "high": 4.1,
            "low": 3.8, "close": 4.0, "volume": 100, "amount": 400,
        }]),
    )
    source = HybridDataSource()
    source._tushare = _FakeTushare()

    rows = source.get_daily_price("510300", "2025-01-01", "2025-01-03")

    assert rows[0]["close"] == 4.0
