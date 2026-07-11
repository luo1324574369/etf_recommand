"""
混合数据源适配器
- ETF行情: AkShare fund_etf_hist_sina
- ETF列表: AkShare fund_etf_spot_em
- 指数PE历史: AkShare stock_index_pe_lg (乐咕乐股, 5000+条)
- 指数PE/股息率: AkShare stock_zh_index_value_csindex (中证指数公司)
- 个股估值: Tushare daily_basic (PE/PB/PS/股息率)

ETF → 跟踪指数映射，用于获取指数估值作为ETF估值代理
"""

import time
import akshare as ak
import pandas as pd
import tushare as ts
from typing import Optional

MAX_RETRIES = 3
RETRY_DELAY = 2


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


# ETF代码 → 跟踪指数名称（用于 stock_index_pe_lg）
ETF_INDEX_MAP = {
    # 宽基
    "510050": "上证50",
    "510300": "沪深300",
    "510310": "沪深300",
    "510350": "沪深300",
    "510500": "中证500",
    "510510": "中证500",
    "512500": "中证500",
    "512100": "中证1000",
    "560010": "中证1000",
    "159915": "创业板指",
    "159952": "创业板指",
    "588000": "科创50",
    "588050": "科创50",
    "588090": "科创50",
    "159901": "深证100",
    "159902": "深证100",
    "510160": "中证800",
    # 行业主题
    "512480": "半导体",
    "512760": "半导体",
    "512660": "军工",
    "512690": "军工",
    "512010": "医药",
    "512010": "中证医药",
    "512170": "医疗",
    "512120": "医疗",
    "512800": "银行",
    "512070": "证券",
    "512000": "券商",
    "515030": "新能源",
    "516160": "新能源",
    "515050": "中证5G",
    "515790": "光伏",
    "515080": "中证煤炭",
    "512200": "房地产",
    "512980": "传媒",
    "512720": "计算机",
    "515880": "通信",
    "159995": "芯片",
    "515060": "中证军工",
    # 海外
    "513050": "中概互联",
    "513100": "纳斯达克100",
    "513500": "标普500",
    "159920": "恒生",
    "510900": "H股",
    "513060": "恒生医疗",
    # 红利
    "510880": "红利",
    "512890": "红利",
    "159905": "红利",
}

# ETF代码 → 中证指数代码（用于 stock_zh_index_value_csindex）
ETF_CSINDEX_MAP = {
    "510300": "000300",
    "510310": "000300",
    "510350": "000300",
    "510050": "000016",
    "510500": "000905",
    "510510": "000905",
    "512500": "000905",
    "512100": "000852",
    "159915": "399006",
    "159952": "399006",
    "588000": "000688",
    "588050": "000688",
}


class HybridDataSource:
    def __init__(self, tushare_token: str = None):
        self._tushare = None
        if tushare_token:
            self._tushare = ts.pro_api(tushare_token)

    def get_etf_list(self) -> list[dict]:
        def _fetch():
            df = ak.fund_etf_spot_em()
            result = []
            for _, row in df.iterrows():
                code = str(row["代码"])
                result.append({
                    "code": code,
                    "name": str(row["名称"]),
                    "index_name": ETF_INDEX_MAP.get(code, ""),
                })
            return result
        return _retry(_fetch)

    def get_daily_price(self, code: str, start_date: str, end_date: str) -> list[dict]:
        def _to_sina_symbol(code: str) -> str:
            if code.startswith("5") or code.startswith("6") or code.startswith("9"):
                return f"sh{code}"
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
                result.append({
                    "trade_date": str(row["date"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                    "amount": float(row["amount"]),
                })
            return result
        return _retry(_fetch)

    def get_index_pe_history(self, etf_code: str) -> list[dict]:
        """通过ETF跟踪指数获取PE历史数据（来源：乐咕乐股）"""
        index_name = ETF_INDEX_MAP.get(etf_code)
        if not index_name:
            return []

        def _fetch():
            df = ak.stock_index_pe_lg(symbol=index_name)
            if df is None or df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                pe_ttm = row.get("滚动市盈率")
                pe_static = row.get("静态市盈率")
                pe = pe_ttm if pd.notna(pe_ttm) and pe_ttm > 0 else (pe_static if pd.notna(pe_static) and pe_static > 0 else None)
                if pe is None:
                    continue
                result.append({
                    "trade_date": str(row["日期"]),
                    "pe": float(pe),
                    "pe_ttm": float(pe_ttm) if pd.notna(pe_ttm) else None,
                    "pe_static": float(pe_static) if pd.notna(pe_static) else None,
                    "pe_equal": float(row["等权滚动市盈率"]) if pd.notna(row.get("等权滚动市盈率")) else None,
                    "pe_median": float(row["滚动市盈率中位数"]) if pd.notna(row.get("滚动市盈率中位数")) else None,
                })
            return result
        try:
            return _retry(_fetch)
        except Exception:
            return []

    def get_index_valuation_csindex(self, etf_code: str) -> list[dict]:
        """从中证指数公司获取估值数据（含股息率）"""
        csindex_code = ETF_CSINDEX_MAP.get(etf_code)
        if not csindex_code:
            return []

        def _fetch():
            df = ak.stock_zh_index_value_csindex(symbol=csindex_code)
            if df is None or df.empty:
                return []
            result = []
            for _, row in df.iterrows():
                result.append({
                    "trade_date": str(row["日期"]),
                    "pe": float(row["市盈率1"]) if pd.notna(row.get("市盈率1")) else None,
                    "pe2": float(row["市盈率2"]) if pd.notna(row.get("市盈率2")) else None,
                    "dividend_yield": float(row["股息率1"]) if pd.notna(row.get("股息率1")) else None,
                    "dividend_yield2": float(row["股息率2"]) if pd.notna(row.get("股息率2")) else None,
                })
            return result
        try:
            return _retry(_fetch)
        except Exception:
            return []

    def get_etf_valuation(self, etf_code: str) -> dict:
        """获取ETF估值综合数据"""
        result = {"code": etf_code}

        # 1. 从乐咕乐股获取最新PE
        pe_history = self.get_index_pe_history(etf_code)
        if pe_history:
            latest = pe_history[-1]
            result["pe"] = latest.get("pe")
            result["pe_ttm"] = latest.get("pe_ttm")
            result["trade_date"] = latest.get("trade_date")
            result["pe_history_count"] = len(pe_history)

        # 2. 从中证指数公司获取股息率
        csindex_val = self.get_index_valuation_csindex(etf_code)
        if csindex_val:
            latest_cs = csindex_val[0]
            result["dividend_yield"] = latest_cs.get("dividend_yield")
            result["pe_csindex"] = latest_cs.get("pe")

        return result

    def get_stock_valuation(self, ts_code: str, trade_date: str = None) -> dict:
        """用Tushare获取个股估值（PE/PB/PS/股息率）"""
        if not self._tushare:
            return {}

        try:
            kwargs = {"ts_code": ts_code}
            if trade_date:
                kwargs["trade_date"] = trade_date
            df = self._tushare.daily_basic(**kwargs)
            if df is None or df.empty:
                return {}
            row = df.iloc[0]
            return {
                "code": ts_code,
                "pe": float(row["pe"]) if pd.notna(row.get("pe")) else None,
                "pe_ttm": float(row["pe_ttm"]) if pd.notna(row.get("pe_ttm")) else None,
                "pb": float(row["pb"]) if pd.notna(row.get("pb")) else None,
                "ps": float(row["ps"]) if pd.notna(row.get("ps")) else None,
                "dividend_yield": float(row["dv_ratio"]) if pd.notna(row.get("dv_ratio")) else None,
                "total_mv": float(row["total_mv"]) if pd.notna(row.get("total_mv")) else None,
            }
        except Exception:
            return {}
