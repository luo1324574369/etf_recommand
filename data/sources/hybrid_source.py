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
    "159915": "创业板指",
    "159952": "创业板指",
    "588000": "科创50",
    "588050": "科创50",
    "588090": "科创50",
    "159901": "深证100",
    "159902": "深证100",
    "510160": "中证800",
    "510500": "中证500",
    "510510": "中证500",
    "512500": "中证500",
    "512100": "中证1000",
    "560010": "中证1000",
    "159919": "沪深300",  # 沪深300ETF
    # 行业主题
    "512480": "半导体",
    "512760": "半导体",
    "512660": "军工",
    "512690": "军工",
    "512010": "医药",
    "512170": "医疗",
    "512800": "银行",
    "512070": "证券",
    "512000": "券商",
    "512880": "证券",  # 证券ETF
    "515030": "新能源",
    "516160": "新能源",
    "515050": "中证5G",
    "515790": "光伏",
    "515080": "中证煤炭",
    "515220": "中证煤炭",  # 煤炭ETF
    "512200": "房地产",
    "512980": "传媒",
    "159805": "传媒",  # 传媒ETF
    "512720": "计算机",
    "515880": "通信",
    "159995": "芯片",
    "515060": "中证军工",
    "159928": "中证消费",  # 消费ETF
    "159996": "中证家电",  # 家电ETF
    "159992": "创新药",  # 创新药ETF
    "515000": "中证科技",  # 科技ETF
    "159825": "中证农业",  # 农业ETF
    "515210": "中证钢铁",  # 钢铁ETF
    "512400": "有色金属",  # 有色金属ETF
    # 海外
    "513050": "中概互联",
    "513100": "纳斯达克100",
    "513500": "标普500",
    "159920": "恒生",
    "510900": "H股",
    "513060": "恒生医疗",
    # 红利
    "510880": "上证红利",  # 乐咕乐股支持的名称
    "512890": "深证红利",  # 乐咕乐股支持的名称
    "159905": "红利",
}

# ETF代码 → 中证指数代码（用于成分股获取 + stock_zh_index_value_csindex）
# 用于乐咕乐股不支持的行业/主题指数的数据源
ETF_CSINDEX_MAP = {
    # 宽基
    "510300": "000300",
    "510310": "000300",
    "510350": "000300",
    "159919": "000300",  # 沪深300ETF
    "510050": "000016",
    "510500": "000905",
    "510510": "000905",
    "512500": "000905",
    "512100": "000852",
    "159915": "399006",
    "159952": "399006",
    "588000": "000688",
    "588050": "000688",
    # 行业主题
    "512480": "990001",  # 中华半导体芯片
    "512760": "990001",  # 中华半导体芯片
    "159995": "990001",  # 芯片 → 中华半导体芯片
    "512660": "399967",  # 中证军工
    "512690": "399967",  # 中证军工
    "515060": "399967",  # 中证军工
    "512010": "000933",  # 中证医药
    "512170": "399989",  # 中证医疗
    "512800": "399986",  # 中证银行
    "512070": "399975",  # 中证全指证券
    "512000": "399975",  # 券商 → 中证全指证券
    "512880": "399975",  # 证券ETF → 中证全指证券
    "515030": "399808",  # 中证新能源
    "516160": "399808",  # 中证新能源
    "515790": "399812",  # 中证光伏
    "515080": "399998",  # 中证煤炭
    "515220": "399998",  # 煤炭ETF → 中证煤炭
    "512200": "399393",  # 中证房地产
    "512980": "399971",  # 中证传媒
    "159805": "399971",  # 传媒ETF → 中证传媒
    "512720": "399820",  # 中证计算机
    "515880": "399935",  # 中证通信
    "515050": "931079",  # 中证5G通信
    "159928": "000932",  # 消费ETF → 中证主要消费
    "159996": "930697",  # 家电ETF → 中证家电
    "159992": "931142",  # 创新药ETF → 中证创新药产业
    "515000": "931186",  # 科技ETF → 中证科技
    "159825": "930689",  # 农业ETF → 中证农业
    "515210": "930608",  # 钢铁ETF → 中证钢铁
    "512400": "930708",  # 有色金属ETF → 中证有色金属
    "512890": "930955",  # 红利低波ETF → 中证红利低波动
    "510880": "000015",  # 红利ETF → 上证红利
}

# ETF代码 → Tushare 指数代码（用于 index_dailybasic，仅覆盖大盘指数）
# Tushare index_dailybasic 只支持 12 个大盘宽基指数，不支持行业指数
ETF_TUSHARE_INDEX_MAP = {
    "510050": "000016.SH",  # 上证50
    "510300": "000300.SH",  # 沪深300
    "510310": "000300.SH",
    "510350": "000300.SH",
    "159919": "000300.SH",  # 沪深300ETF
    "510500": "000905.SH",  # 中证500
    "510510": "000905.SH",
    "512500": "000905.SH",
    "512100": "000852.SH",  # 中证1000
    "560010": "000852.SH",
    "510160": "000906.SH",  # 中证800
    "159915": "399006.SZ",  # 创业板指
    "159952": "399006.SZ",
    "588000": "000688.SH",  # 科创50
    "588050": "000688.SH",
    "588090": "000688.SH",
    "159901": "399330.SZ",  # 深证100
    "159902": "399330.SZ",
}

# ETF代码 → Tushare 行业名称（用于 daily_basic 加权计算行业PE）
# 用于宽基和csindex都不支持的行业ETF
ETF_INDUSTRY_MAP = {
    "512480": "半导体",
    "512760": "半导体",
    "159995": "半导体",      # 芯片
    "512660": "航空",         # 军工
    "512690": "航空",
    "515060": "航空",
    "512010": "中成药",       # 医药
    "512170": "医疗保健",     # 医疗
    "512800": "银行",
    "512070": "证券",
    "512000": "证券",         # 券商
    "515030": "电气设备",     # 新能源
    "516160": "电气设备",
    "515050": "通信设备",     # 5G
    "515880": "通信设备",
    "515790": "电气设备",     # 光伏
    "515080": "煤炭开采",
    "512200": "全国地产",     # 房地产
    "512980": "影视音像",     # 传媒
    "512720": "软件服务",     # 计算机
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
        """通过ETF跟踪指数获取PE历史数据
        数据源优先级：
        1. 乐咕乐股 stock_index_pe_lg（宽基指数，5000+条历史，口径更接近中证官方）
        2. Tushare index_dailybasic（宽基指数，2014年至今，3000+条）
        3. 中证指数成分股 + Tushare daily_basic（行业ETF，日频）
        4. 中证指数公司 stock_zh_index_value_csindex（行业指数，近20条）
        """
        # 数据源1: 乐咕乐股（宽基指数，口径与中证官方更接近）
        index_name = ETF_INDEX_MAP.get(etf_code)
        if index_name:
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
                result = _retry(_fetch)
                if result:
                    return result
            except Exception:
                pass

        # 数据源2: Tushare index_dailybasic（宽基指数，fallback）
        if self._tushare:
            ts_code = ETF_TUSHARE_INDEX_MAP.get(etf_code)
            if ts_code:
                try:
                    df = self._tushare.index_dailybasic(ts_code=ts_code)
                    if df is not None and not df.empty:
                        result = []
                        for _, row in df.iterrows():
                            pe_ttm = row.get("pe_ttm")
                            pe = row.get("pe")
                            pe_val = pe_ttm if pd.notna(pe_ttm) and pe_ttm > 0 else (pe if pd.notna(pe) and pe > 0 else None)
                            if pe_val is None:
                                continue
                            td = str(row["trade_date"])
                            td = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                            result.append({
                                "trade_date": td,
                                "pe": float(pe_val),
                                "pe_ttm": float(pe_ttm) if pd.notna(pe_ttm) else None,
                                "pe_static": float(pe) if pd.notna(pe) else None,
                                "pe_equal": None,
                                "pe_median": None,
                            })
                        if result:
                            return result
                except Exception:
                    pass

        # 数据源3: 中证指数成分股 + Tushare daily_basic pe_ttm 加权计算（行业ETF，日频）
        csindex_code = ETF_CSINDEX_MAP.get(etf_code)
        if csindex_code and self._tushare:
            result = self._get_constituent_pe_history(csindex_code)
            if result:
                return result

        # 数据源3b: Tushare daily_basic 行业加权计算（fallback，日频）
        industry = ETF_INDUSTRY_MAP.get(etf_code)
        if industry and self._tushare:
            result = self._get_industry_pe_history(industry)
            if result:
                return result

        # 数据源4: 中证指数公司（行业指数，近20天数据）
        csindex_code = ETF_CSINDEX_MAP.get(etf_code)
        if csindex_code:
            try:
                df = ak.stock_zh_index_value_csindex(symbol=csindex_code)
                if df is None or df.empty:
                    return []
                result = []
                for _, row in df.iterrows():
                    pe_val = row.get("市盈率1")
                    if pd.notna(pe_val) and pe_val > 0:
                        result.append({
                            "trade_date": str(row["日期"]),
                            "pe": float(pe_val),
                            "pe_ttm": float(pe_val),
                            "pe_static": float(row.get("市盈率2")) if pd.notna(row.get("市盈率2")) else None,
                            "pe_equal": None,
                            "pe_median": None,
                        })
                return result
            except Exception:
                return []

        return []

    def _to_tushare_code(self, code: str) -> str:
        """将6位股票代码转为Tushare格式（带交易所后缀）"""
        code = str(code).zfill(6)
        if code.startswith(('6', '9')):
            return f"{code}.SH"
        return f"{code}.SZ"

    def _calc_weighted_pe(self, pe_ttm_values, market_values, cap=0.15):
        """按中证指数官方公式计算加权PE

        中证指数公式: PE = Σ(市值) / Σ(利润), 其中 利润 = 市值 / PE
        等价于 PE = Σ(mv) / Σ(mv / pe_ttm)

        不是 Σ(pe_ttm * weight) 这种算术加权，而是调和加权。
        同时施加15%单只权重上限。
        """
        import numpy as np
        pe = np.array(pe_ttm_values, dtype=float)
        mv = np.array(market_values, dtype=float)

        # 施加权重上限
        weights = self._apply_weight_cap(mv, cap=cap)

        # 中证指数公式: 加权PE = Σ(mv) / Σ(mv / pe)
        # 用权重计算: Σ(weight * mv_total) / Σ(weight * mv_total / pe)
        # 简化为: Σ(weight) / Σ(weight / pe)  （因为 mv_total 约掉）
        earnings = weights / pe  # 模拟利润占比
        total_earnings = earnings.sum()
        if total_earnings <= 0:
            return 0.0
        weighted_pe = 1.0 / total_earnings  # = Σ(weight) / Σ(weight/pe)
        return round(float(weighted_pe), 2)

    def _apply_weight_cap(self, market_values, cap=0.15):
        """对市值权重施加单只上限（中证指数规则：单只≤15%），迭代重分配"""
        import numpy as np
        mv = np.array(market_values, dtype=float)
        total = mv.sum()
        if total <= 0:
            return mv / 1.0
        weights = mv / total
        for _ in range(10):
            capped = weights > cap
            if not capped.any():
                break
            excess = (weights[capped] - cap).sum()
            weights[capped] = cap
            uncapped = ~capped
            if uncapped.sum() > 0 and excess > 0:
                weights[uncapped] += excess * (weights[uncapped] / weights[uncapped].sum())
        return weights

    def _get_constituent_pe_history(self, csindex_code: str) -> list[dict]:
        """用中证指数官方成分股 + Tushare daily_basic pe_ttm 加权计算PE历史（日频）

        三项对齐：
        1. PE口径：使用 pe_ttm（滚动市盈率），与中证指数官方一致
        2. 成分股：从中证指数公司获取官方成分股列表，替代申万行业分类
        3. 加权方式：市值加权 + 单只15%权重上限（中证指数规则）
        """
        if not self._tushare:
            return []
        try:
            # 1. 从AkShare获取中证指数官方成分股
            cons_df = ak.index_stock_cons_csindex(symbol=csindex_code)
            if cons_df is None or cons_df.empty:
                return []
            stock_codes = [self._to_tushare_code(c) for c in cons_df['成分券代码'].tolist()]
            if not stock_codes:
                return []

            # 2. 获取交易日历
            cal = self._tushare.trade_cal(exchange='SSE', start_date='20150101', end_date='20261231')
            cal = cal[cal['is_open'] == 1]
            trade_dates = cal['cal_date'].tolist()

            # 3. 逐日获取daily_basic，筛选成分股，用pe_ttm加权
            result = []
            for td in trade_dates:
                try:
                    df = self._tushare.daily_basic(trade_date=td, fields='ts_code,pe_ttm,total_mv')
                    if df is None or df.empty:
                        continue
                    # 筛选官方成分股
                    cons_df_filtered = df[df['ts_code'].isin(stock_codes)]
                    cons_df_filtered = cons_df_filtered.dropna(subset=['pe_ttm'])
                    cons_df_filtered = cons_df_filtered[cons_df_filtered['pe_ttm'] > 0]
                    if cons_df_filtered.empty:
                        continue

                    # 排除PE>500的异常亏损股
                    valid = cons_df_filtered[cons_df_filtered['pe_ttm'] <= 500]
                    if valid.empty:
                        continue

                    # 中证指数公式加权PE（调和加权 + 15%上限）
                    weighted_pe = self._calc_weighted_pe(
                        valid['pe_ttm'].values, valid['total_mv'].values, cap=0.15
                    )

                    td_fmt = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                    result.append({
                        "trade_date": td_fmt,
                        "pe": weighted_pe,
                        "pe_ttm": weighted_pe,
                        "pe_static": None,
                        "pe_equal": round(float(valid['pe_ttm'].mean()), 2),
                        "pe_median": round(float(valid['pe_ttm'].median()), 2),
                    })
                except Exception:
                    continue

            return result
        except Exception:
            return []

    def _get_industry_pe_history(self, industry: str) -> list[dict]:
        """用 Tushare daily_basic 加权计算行业PE历史（日频，fallback）

        使用 pe_ttm + 中证指数公式加权 + 15%权重上限
        """
        if not self._tushare:
            return []
        try:
            # 1. 获取行业成分股列表
            basic = self._tushare.stock_basic(exchange='', list_status='L', fields='ts_code,industry')
            stock_codes = basic[basic['industry'] == industry]['ts_code'].tolist()
            if not stock_codes:
                return []

            # 2. 获取交易日历
            cal = self._tushare.trade_cal(exchange='SSE', start_date='20150101', end_date='20261231')
            cal = cal[cal['is_open'] == 1]
            trade_dates = cal['cal_date'].tolist()

            # 3. 逐日获取全市场pe_ttm，筛选行业成分股，加权计算
            result = []
            for td in trade_dates:
                try:
                    df = self._tushare.daily_basic(trade_date=td, fields='ts_code,pe_ttm,total_mv')
                    if df is None or df.empty:
                        continue
                    industry_df = df[df['ts_code'].isin(stock_codes)]
                    industry_df = industry_df.dropna(subset=['pe_ttm'])
                    industry_df = industry_df[industry_df['pe_ttm'] > 0]
                    if industry_df.empty:
                        continue

                    # 排除PE>500的异常亏损股
                    valid = industry_df[industry_df['pe_ttm'] <= 500]
                    if valid.empty:
                        continue

                    # 中证指数公式加权PE（调和加权 + 15%上限）
                    weighted_pe = self._calc_weighted_pe(
                        valid['pe_ttm'].values, valid['total_mv'].values, cap=0.15
                    )

                    td_fmt = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                    result.append({
                        "trade_date": td_fmt,
                        "pe": weighted_pe,
                        "pe_ttm": weighted_pe,
                        "pe_static": None,
                        "pe_equal": round(float(valid['pe_ttm'].mean()), 2),
                        "pe_median": round(float(valid['pe_ttm'].median()), 2),
                    })
                except Exception:
                    continue

            return result
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

    def batch_get_pe_history(self, etf_codes: list[str], on_progress=None) -> dict[str, list[dict]]:
        """批量获取多只ETF的PE历史数据（优化版）

        优化点：
        1. 正确分类：ETF_TUSHARE_INDEX_MAP(宽基) → ETF_CSINDEX_MAP(行业) → ETF_INDEX_MAP(乐咕乐股)
        2. 行业ETF按ts_code查询（~500次API），而非按trade_date查询（2700次API），速度提升5倍+
        3. 一次API调用获取一只股票的全部历史daily_basic，共享数据为所有ETF计算PE

        返回: {etf_code: [pe_record, ...]}
        """
        if not self._tushare:
            return {}

        # 1. 分类ETF（优先级：Tushare宽基 > 中证行业 > 乐咕乐股宽基）
        broad_codes = []  # 宽基：用Tushare index_dailybasic或乐咕乐股（快速）
        industry_codes = []  # 行业：用成分股批量法
        for code in etf_codes:
            if code in ETF_TUSHARE_INDEX_MAP:
                broad_codes.append(code)
            elif code in ETF_CSINDEX_MAP:
                industry_codes.append(code)
            elif code in ETF_INDEX_MAP:
                broad_codes.append(code)

        result = {}

        # 2. 宽基ETF：逐个获取（快速，每只1次API调用）
        for i, code in enumerate(broad_codes):
            if on_progress:
                on_progress(f"获取宽基ETF PE: {code} ({i+1}/{len(broad_codes)})")
            pe_data = self.get_index_pe_history(code)
            if pe_data:
                result[code] = pe_data

        # 3. 行业ETF：按成分股批量获取（ts_code优化）
        if industry_codes and self._tushare:
            if on_progress:
                on_progress("获取行业ETF成分股列表...")

            # 3a. 获取每只ETF的成分股列表，收集所有唯一股票
            etf_constituents = {}  # {etf_code: set(tushare_codes)}
            all_stocks = set()
            for code in industry_codes:
                csindex_code = ETF_CSINDEX_MAP.get(code)
                if not csindex_code:
                    continue
                try:
                    cons_df = ak.index_stock_cons_csindex(symbol=csindex_code)
                    if cons_df is not None and not cons_df.empty:
                        stock_codes = {self._to_tushare_code(c) for c in cons_df['成分券代码'].tolist()}
                        etf_constituents[code] = stock_codes
                        all_stocks.update(stock_codes)
                except Exception:
                    continue

            if etf_constituents and all_stocks:
                # 3b. 逐只股票获取全部历史daily_basic（一次API调用获取全部日期）
                stock_list = sorted(all_stocks)
                total_stocks = len(stock_list)
                stock_frames = []
                for i, ts_code in enumerate(stock_list):
                    if on_progress and (i % 50 == 0 or i == total_stocks - 1):
                        on_progress(f"获取个股估值数据: {i+1}/{total_stocks} 只股票")
                    try:
                        df = self._tushare.daily_basic(
                            ts_code=ts_code,
                            start_date='20150101',
                            end_date='20261231',
                            fields='ts_code,trade_date,pe_ttm,total_mv'
                        )
                        if df is not None and not df.empty:
                            stock_frames.append(df)
                    except Exception:
                        continue

                # 3c. 合并所有股票数据，筛选有效PE
                if stock_frames:
                    if on_progress:
                        on_progress("计算行业ETF加权PE...")
                    all_df = pd.concat(stock_frames, ignore_index=True)
                    all_df = all_df.dropna(subset=['pe_ttm'])
                    all_df = all_df[all_df['pe_ttm'] > 0]
                    all_df = all_df[all_df['pe_ttm'] <= 500]

                    # 3d. 为每只ETF计算每日加权PE
                    for code, stock_set in etf_constituents.items():
                        cons_df = all_df[all_df['ts_code'].isin(stock_set)]
                        if cons_df.empty:
                            continue

                        pe_records = []
                        for td, group in cons_df.groupby('trade_date'):
                            weighted_pe = self._calc_weighted_pe(
                                group['pe_ttm'].values,
                                group['total_mv'].values,
                                cap=0.15,
                            )
                            if weighted_pe > 0:
                                td_str = str(td)
                                td_fmt = f"{td_str[:4]}-{td_str[4:6]}-{td_str[6:8]}"
                                pe_records.append({
                                    "trade_date": td_fmt,
                                    "pe": weighted_pe,
                                    "pe_ttm": weighted_pe,
                                    "pe_static": None,
                                    "pe_equal": round(float(group['pe_ttm'].mean()), 2),
                                    "pe_median": round(float(group['pe_ttm'].median()), 2),
                                })

                        if pe_records:
                            pe_records.sort(key=lambda x: x['trade_date'])
                            result[code] = pe_records

        return result
