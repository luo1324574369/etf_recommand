import time
import akshare as ak

from data.sources.base import DataSourceBase

MAX_RETRIES = 3
RETRY_DELAY = 2


def _format_date(date_str: str) -> str:
    return date_str.replace("-", "")


def _retry(func, *args, **kwargs):
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                raise last_err


class AkshareDataSource(DataSourceBase):
    def get_etf_list(self) -> list[dict]:
        def _fetch():
            df = ak.fund_etf_spot_em()
            result = []
            for _, row in df.iterrows():
                result.append({"code": str(row["代码"]), "name": str(row["名称"])})
            return result
        return _retry(_fetch)

    def get_daily_price(self, code: str, start_date: str, end_date: str) -> list[dict]:
        def _to_sina_symbol(code: str) -> str:
            if code.startswith("5") or code.startswith("6") or code.startswith("9"):
                return f"sh{code}"
            else:
                return f"sz{code}"

        def _fetch():
            symbol = _to_sina_symbol(code)
            df = ak.fund_etf_hist_sina(symbol=symbol)
            if df is None or df.empty:
                return []
            df = df.sort_values("date", ascending=True)
            df["date"] = df["date"].astype(str)
            mask = (df["date"] >= start_date) & (df["date"] <= end_date)
            df = df[mask]
            result = []
            for _, row in df.iterrows():
                result.append(
                    {
                        "trade_date": str(row["date"]),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": int(row["volume"]),
                        "amount": float(row["amount"]),
                    }
                )
            return result
        return _retry(_fetch)
