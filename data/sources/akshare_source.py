import time
import akshare as ak
import pandas as pd

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

    def get_etf_valuation(self, code: str) -> dict:
        def _fetch():
            df = ak.fund_etf_fundamental_em(symbol=code)
            if df is None or df.empty:
                return {}
            row = df.iloc[0]
            return {
                "code": code,
                "pe": float(row.get("市盈率", 0)) if pd.notna(row.get("市盈率")) else None,
                "pb": float(row.get("市净率", 0)) if pd.notna(row.get("市净率")) else None,
                "ps": float(row.get("市销率", 0)) if pd.notna(row.get("市销率")) else None,
                "dividend_yield": float(row.get("股息率", 0)) if pd.notna(row.get("股息率")) else None,
                "nav": float(row.get("最新净值", 0)) if pd.notna(row.get("最新净值")) else None,
                "premium_rate": float(row.get("溢价率", 0)) if pd.notna(row.get("溢价率")) else None,
            }
        try:
            return _retry(_fetch)
        except Exception:
            return {}

    def get_etf_valuation_batch(self, codes: list[str]) -> dict[str, dict]:
        result = {}
        for code in codes:
            try:
                result[code] = self.get_etf_valuation(code)
            except Exception:
                result[code] = {}
        return result

    def get_index_valuation(self, index_code: str, start_date: str, end_date: str) -> list[dict]:
        def _fetch():
            df = ak.index_value_hist_em(symbol=index_code)
            if df is None or df.empty:
                return []
            df = df.sort_values("日期", ascending=True)
            df["日期"] = df["日期"].astype(str)
            mask = (df["日期"] >= start_date) & (df["日期"] <= end_date)
            df = df[mask]
            result = []
            for _, row in df.iterrows():
                result.append({
                    "trade_date": str(row["日期"]),
                    "pe": float(row.get("市盈率", 0)) if pd.notna(row.get("市盈率")) else None,
                    "pb": float(row.get("市净率", 0)) if pd.notna(row.get("市净率")) else None,
                    "ps": float(row.get("市销率", 0)) if pd.notna(row.get("市销率")) else None,
                    "dividend_yield": float(row.get("股息率", 0)) if pd.notna(row.get("股息率")) else None,
                })
            return result
        try:
            return _retry(_fetch)
        except Exception:
            return []
