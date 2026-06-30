import akshare as ak

from data.sources.base import DataSourceBase


def _format_date(date_str: str) -> str:
    return date_str.replace("-", "")


class AkshareDataSource(DataSourceBase):
    def get_etf_list(self) -> list[dict]:
        df = ak.fund_etf_spot_em()
        result = []
        for _, row in df.iterrows():
            result.append({"code": row["代码"], "name": row["名称"]})
        return result

    def get_daily_price(self, code: str, start_date: str, end_date: str) -> list[dict]:
        formatted_start = _format_date(start_date)
        formatted_end = _format_date(end_date)
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=formatted_start,
            end_date=formatted_end,
            adjust="qfq",
        )
        df = df.sort_values("日期", ascending=True)
        result = []
        for _, row in df.iterrows():
            result.append(
                {
                    "trade_date": row["日期"],
                    "open": row["开盘"],
                    "high": row["最高"],
                    "low": row["最低"],
                    "close": row["收盘"],
                    "volume": row["成交量"],
                    "amount": row["成交额"],
                }
            )
        return result
