"""批量补充缺失ETF的PE数据

优化策略：
1. 快速路径：乐咕乐股 / Tushare index_dailybasic / csindex 20条 → 直接存
2. 慢速批量路径：收集所有需成分股PE的ETF → 每个交易日只调1次daily_basic → 同时为所有ETF计算加权PE
"""
import sys
import time
import datetime
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import akshare as ak
import tushare as ts
import numpy as np

from config.settings import ETF_UNIVERSE, DB_PATH, TUSHARE_TOKEN
from data.storage.db import init_db
from data.storage.valuation_repo import ValuationRepo
from data.sources.hybrid_source import (
    ETF_INDEX_MAP, ETF_CSINDEX_MAP, ETF_TUSHARE_INDEX_MAP, ETF_INDUSTRY_MAP
)

# 无PE概念的ETF（商品+海外QDII）
NO_PE_ETFS = {"159985", "518880", "159920", "513100"}  # 豆粕, 黄金, 恒生(QDII), 纳指(QDII)

# PE数据不足的阈值（24个月回测需要至少100条日频数据）
MIN_PE_RECORDS = 100


def _to_tushare_code(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    return f"{code}.SZ"


def _calc_weighted_pe(pe_ttm_values, market_values, cap=0.15):
    pe = np.array(pe_ttm_values, dtype=float)
    mv = np.array(market_values, dtype=float)
    raw_weights = mv / mv.sum()
    excess = np.where(raw_weights > cap, raw_weights - cap, 0)
    weights = np.minimum(raw_weights, cap)
    total_excess = excess.sum()
    if total_excess > 0:
        uncapped = weights < cap
        if uncapped.sum() > 0 and total_excess > 0:
            weights[uncapped] += total_excess * (weights[uncapped] / weights[uncapped].sum())
    profits = mv / pe
    total_mv = (weights * mv).sum()
    total_profit = (weights * profits).sum()
    if total_profit > 0:
        return round(float(total_mv / total_profit), 2)
    return round(float(np.average(pe, weights=mv)), 2)


def main():
    init_db(str(DB_PATH))
    repo = ValuationRepo(str(DB_PATH))

    # 1. 找出PE数据不足的ETF（排除无PE概念的ETF）
    missing = []
    for e in ETF_UNIVERSE:
        code = e['code']
        if code in NO_PE_ETFS:
            continue
        cnt = repo.get_pe_history_count(code)
        if cnt < MIN_PE_RECORDS:
            missing.append((code, e['name'], cnt))
    print(f"PE数据不足(<{MIN_PE_RECORDS}条)的ETF: {len(missing)}只")
    for code, name, cnt in missing:
        print(f"  {code} {name}: 现有{cnt}条")

    if not missing:
        print("所有ETF PE数据充足，无需补充")
        return

    # 2. 快速路径：乐咕乐股 + Tushare index_dailybasic + csindex 20条
    fast_done = []
    slow_needed = []

    ts_api = ts.pro_api(TUSHARE_TOKEN) if TUSHARE_TOKEN else None

    for code, name, cnt in missing:
        pe_data = []

        # 快速路径A: 乐咕乐股
        index_name = ETF_INDEX_MAP.get(code)
        if index_name and not pe_data:
            try:
                df = ak.stock_index_pe_lg(symbol=index_name)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        pe_ttm = row.get("滚动市盈率")
                        pe_static = row.get("静态市盈率")
                        pe_val = pe_ttm if pe_ttm and pe_ttm > 0 else (pe_static if pe_static and pe_static > 0 else None)
                        if pe_val:
                            pe_data.append({
                                "trade_date": str(row["日期"]),
                                "pe": float(pe_val),
                                "pe_ttm": float(pe_ttm) if pe_ttm else None,
                                "pe_static": float(pe_static) if pe_static else None,
                                "pe_equal": float(row["等权滚动市盈率"]) if row.get("等权滚动市盈率") else None,
                                "pe_median": float(row["滚动市盈率中位数"]) if row.get("滚动市盈率中位数") else None,
                            })
            except Exception:
                pass

        # 快速路径B: Tushare index_dailybasic
        if not pe_data and ts_api:
            ts_code = ETF_TUSHARE_INDEX_MAP.get(code)
            if ts_code:
                try:
                    df = ts_api.index_dailybasic(ts_code=ts_code)
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            pe_ttm = row.get("pe_ttm")
                            pe_val = row.get("pe")
                            v = pe_ttm if pe_ttm and pe_ttm > 0 else (pe_val if pe_val and pe_val > 0 else None)
                            if v:
                                td = str(row["trade_date"])
                                td = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                                pe_data.append({
                                    "trade_date": td,
                                    "pe": float(v),
                                    "pe_ttm": float(pe_ttm) if pe_ttm else None,
                                    "pe_static": float(pe_val) if pe_val else None,
                                    "pe_equal": None,
                                    "pe_median": None,
                                })
                except Exception:
                    pass

        # 快速路径C: 中证指数公司（~20条）
        if not pe_data:
            csindex_code = ETF_CSINDEX_MAP.get(code)
            if csindex_code:
                try:
                    df = ak.stock_zh_index_value_csindex(symbol=csindex_code)
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            pe_val = row.get("市盈率1")
                            if pe_val and pe_val > 0:
                                pe_data.append({
                                    "trade_date": str(row["日期"]),
                                    "pe": float(pe_val),
                                    "pe_ttm": float(pe_val),
                                    "pe_static": float(row.get("市盈率2")) if row.get("市盈率2") else None,
                                    "pe_equal": None,
                                    "pe_median": None,
                                })
                except Exception:
                    pass

        if pe_data:
            repo.batch_insert_pe_history(code, pe_data)
            new_cnt = repo.get_pe_history_count(code)
            if new_cnt >= MIN_PE_RECORDS:
                print(f"✅ {code} {name}: 快速路径获得{len(pe_data)}条, 现有{new_cnt}条")
                fast_done.append(code)
            else:
                print(f"⏳ {code} {name}: 快速路径仅{len(pe_data)}条(<{MIN_PE_RECORDS}), 需走批量路径")
                slow_needed.append((code, name))
        else:
            slow_needed.append((code, name))
            print(f"⏳ {code} {name}: 需走批量成分股路径")

    # 3. 批量慢速路径：每天1次API调用，同时为所有ETF计算PE
    if not slow_needed:
        print(f"\n所有ETF PE数据已补充完成")
        return

    print(f"\n=== 批量成分股PE计算: {len(slow_needed)}只ETF ===")

    # 3a. 收集所有ETF的成分股
    etf_constituents = {}  # {code: set(stock_codes)}
    all_stocks = set()

    for code, name in slow_needed:
        stocks = []

        # 尝试csindex成分股
        csindex_code = ETF_CSINDEX_MAP.get(code)
        if csindex_code:
            try:
                cons_df = ak.index_stock_cons_csindex(symbol=csindex_code)
                if cons_df is not None and not cons_df.empty:
                    stocks = [_to_tushare_code(c) for c in cons_df['成分券代码'].tolist()]
                    print(f"  {code} {name}: csindex成分股{len(stocks)}只")
            except Exception as e:
                print(f"  {code} {name}: csindex成分股获取失败({type(e).__name__}), 尝试行业fallback")

        # fallback: 用行业
        if not stocks:
            industry = ETF_INDUSTRY_MAP.get(code)
            if industry and ts_api:
                try:
                    basic = ts_api.stock_basic(exchange='', list_status='L', fields='ts_code,industry')
                    stocks = basic[basic['industry'] == industry]['ts_code'].tolist()
                    print(f"  {code} {name}: 行业'{industry}'成分股{len(stocks)}只")
                except Exception as e:
                    print(f"  {code} {name}: 行业获取也失败 {e}")

        if stocks:
            etf_constituents[code] = set(stocks)
            all_stocks.update(stocks)
        else:
            print(f"  ❌ {code} {name}: 无法获取成分股，跳过")

    if not etf_constituents or not ts_api:
        print("无法获取成分股或Tushare未配置，退出")
        return

    print(f"  合计覆盖{len(all_stocks)}只个股")

    # 3b. 获取近3年交易日历，每5天采样
    end_dt = datetime.date.today()
    start_dt = end_dt - datetime.timedelta(days=365 * 3)
    cal = ts_api.trade_cal(
        exchange='SSE',
        start_date=start_dt.strftime('%Y%m%d'),
        end_date=end_dt.strftime('%Y%m%d')
    )
    cal = cal[cal['is_open'] == 1]
    trade_dates = cal['cal_date'].tolist()[::5]  # 每5天采样
    print(f"  采样{len(trade_dates)}个交易日")

    # 3c. 逐日获取daily_basic，同时为所有ETF计算PE
    etf_pe_data = {code: [] for code in etf_constituents}

    for i, td in enumerate(trade_dates):
        try:
            df = ts_api.daily_basic(trade_date=td, fields='ts_code,pe_ttm,total_mv')
            if df is None or df.empty:
                continue

            td_fmt = f"{td[:4]}-{td[4:6]}-{td[6:8]}"

            for code, stock_set in etf_constituents.items():
                cons_df = df[df['ts_code'].isin(stock_set)]
                cons_df = cons_df.dropna(subset=['pe_ttm'])
                cons_df = cons_df[cons_df['pe_ttm'] > 0]
                if cons_df.empty:
                    continue
                valid = cons_df[cons_df['pe_ttm'] <= 500]
                if valid.empty:
                    continue

                weighted_pe = _calc_weighted_pe(
                    valid['pe_ttm'].values, valid['total_mv'].values, cap=0.15
                )
                etf_pe_data[code].append({
                    "trade_date": td_fmt,
                    "pe": weighted_pe,
                    "pe_ttm": weighted_pe,
                    "pe_static": None,
                    "pe_equal": round(float(valid['pe_ttm'].mean()), 2),
                    "pe_median": round(float(valid['pe_ttm'].median()), 2),
                })
        except Exception:
            continue

        if (i + 1) % 10 == 0:
            print(f"  进度: {i+1}/{len(trade_dates)}")

    # 3d. 存入DB
    for code, name in slow_needed:
        pe_data = etf_pe_data.get(code, [])
        if pe_data:
            repo.batch_insert_pe_history(code, pe_data)
            new_cnt = repo.get_pe_history_count(code)
            print(f"✅ {code} {name}: 批量路径获得{len(pe_data)}条, 现有{new_cnt}条")
        else:
            print(f"❌ {code} {name}: 未能获取PE数据")

    # 4. 最终检查
    print("\n=== 最终PE数据统计 ===")
    total_ok = 0
    total_skip = 0
    for e in ETF_UNIVERSE:
        code = e['code']
        if code in NO_PE_ETFS:
            total_skip += 1
            continue
        cnt = repo.get_pe_history_count(code)
        status = "✅" if cnt >= MIN_PE_RECORDS else "❌"
        if cnt >= MIN_PE_RECORDS:
            total_ok += 1
        print(f"  {status} {code} {e['name']}: {cnt}条")
    print(f"\n{total_ok}只ETF PE数据充足, {total_skip}只无PE概念(跳过)")


if __name__ == "__main__":
    main()
