"""
因子验证脚本 v2
- 验证行情因子（动量、波动率、流动性）
- 验证PE历史数据获取与百分位计算
- 验证Z-score标准化与等权加权

使用方法:
    .venv/bin/python scripts/verify_factors.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from data.sources.hybrid_source import HybridDataSource, ETF_INDEX_MAP
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo
from strategy.scoring import compute_all_factors, zscore_normalize, equal_weight_score
from config.settings import TUSHARE_TOKEN

DB_PATH = "data/etf.db"
TEST_CODES = ["510300", "510500", "510050"]
TOLERANCE = 0.01


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(name, expected, actual, tolerance=TOLERANCE):
    if expected is None or actual is None:
        status = "⚠️  SKIP" if expected is None and actual is None else "❌ FAIL"
        print(f"  {status}  {name}: expected={expected}, actual={actual}")
        return status == "⚠️  SKIP"
    diff = abs(expected - actual)
    if diff < tolerance:
        print(f"  ✅ PASS  {name}: expected={expected:.4f}, actual={actual:.4f}, diff={diff:.6f}")
        return True
    else:
        print(f"  ❌ FAIL  {name}: expected={expected:.4f}, actual={actual:.4f}, diff={diff:.6f}")
        return False


def main():
    init_db(DB_PATH)
    source = HybridDataSource(tushare_token=TUSHARE_TOKEN)
    price_repo = PriceRepository(get_db(DB_PATH))
    val_repo = ValuationRepo(DB_PATH)

    all_pass = True

    # ── 1. ETF→指数映射验证 ────────────────────────────
    section("步骤1: ETF→指数映射")
    for code in TEST_CODES:
        index_name = ETF_INDEX_MAP.get(code)
        if index_name:
            print(f"  ✅ {code} → {index_name}")
        else:
            print(f"  ❌ {code} → 未映射")
            all_pass = False

    # ── 2. 拉取行情数据 ────────────────────────────────
    section("步骤2: 拉取行情数据")
    etf_prices = {}
    for code in TEST_CODES:
        print(f"  拉取 {code} 行情...")
        prices = source.get_daily_price(code, "2020-01-01", "2024-12-31")
        print(f"    获取 {len(prices)} 条记录")
        if len(prices) < 120:
            print(f"  ❌ 数据不足")
            all_pass = False
            continue
        price_repo.batch_insert({code: prices})
        etf_prices[code] = prices

    # ── 3. 拉取PE历史数据 ──────────────────────────────
    section("步骤3: 拉取指数PE历史数据")
    for code in TEST_CODES:
        print(f"  拉取 {code} 的PE历史...")
        pe_history = source.get_index_pe_history(code)
        if pe_history:
            print(f"    获取 {len(pe_history)} 条PE记录")
            print(f"    最早: {pe_history[0]['trade_date']}, PE={pe_history[0]['pe']:.2f}")
            print(f"    最新: {pe_history[-1]['trade_date']}, PE={pe_history[-1]['pe']:.2f}")
            val_repo.batch_insert_pe_history(code, pe_history)
        else:
            print(f"  ⚠️  {code} 无PE历史数据（ETF_INDEX_MAP未映射）")

    # ── 4. 行情因子验证 ────────────────────────────────
    section("步骤4: 行情因子验证（510300）")
    code = "510300"
    prices = etf_prices.get(code, [])
    if prices:
        df = pd.DataFrame(prices)
        df["close"] = df["close"].astype(float)
        df["amount"] = df["amount"].astype(float)
        df = df.sort_values("trade_date").reset_index(drop=True)

        module_factors = compute_all_factors(code, prices, pe_percentile=50.0)
        print(f"  模块输出: {{k: round(v,2) for k,v in module_factors.items()}}")

        # 动量
        print("\n  ── 动量因子 ──")
        for period in [20, 60, 120]:
            if len(df) > period:
                past = df["close"].iloc[-period - 1]
                curr = df["close"].iloc[-1]
                expected = (curr - past) / past * 100
                key = f"momentum_{period}d"
                ok = check(key, expected, module_factors.get(key))
                all_pass = all_pass and ok

        # 波动率
        print("\n  ── 波动率因子 ──")
        recent = df["close"].iloc[-60:]
        daily_returns = recent.pct_change().dropna()
        expected_vol = daily_returns.std(ddof=1) * np.sqrt(252) * 100
        ok = check("volatility_60d", expected_vol, module_factors.get("volatility_60d"))
        all_pass = all_pass and ok

        # 流动性
        print("\n  ── 流动性因子 ──")
        expected_amt = df["amount"].iloc[-20:].mean()
        ok = check("avg_amount_20d", expected_amt, module_factors.get("avg_amount_20d"))
        all_pass = all_pass and ok

    # ── 5. PE百分位验证 ────────────────────────────────
    section("步骤5: PE百分位验证")
    for code in TEST_CODES:
        pe_count = val_repo.get_pe_history_count(code)
        pe_latest = val_repo.get_latest_pe(code)
        pe_pct = val_repo.get_pe_percentile(code)

        if pe_count > 0:
            print(f"\n  {code}:")
            print(f"    PE历史记录数: {pe_count}")
            print(f"    最新PE: {pe_latest:.2f}" if pe_latest else "    最新PE: None")
            print(f"    PE百分位: {pe_pct:.1f}%")

            # 独立验证百分位
            pe_history = val_repo.get_pe_history(code)
            pe_values = sorted([r["pe"] for r in pe_history if r["pe"] is not None])
            if pe_values and pe_latest:
                cnt = sum(1 for v in pe_values if v <= pe_latest)
                expected_pct = cnt / len(pe_values) * 100
                ok = check(f"{code} PE百分位", expected_pct, pe_pct, tolerance=0.5)
                all_pass = all_pass and ok

            # 验证百分位在合理范围
            if pe_pct < 0 or pe_pct > 100:
                print(f"  ❌ FAIL  百分位超出[0,100]范围")
                all_pass = False
            elif pe_pct < 10:
                print(f"  ℹ️  PE处于历史低位（<10%分位），可能被低估")
            elif pe_pct > 90:
                print(f"  ℹ️  PE处于历史高位（>90%分位），可能被高估")
            else:
                print(f"  ✅ PE百分位在合理范围内")
        else:
            print(f"\n  ⚠️  {code}: 无PE历史数据，跳过")

    # ── 6. Z-score标准化验证 ──────────────────────────
    section("步骤6: Z-score标准化验证")
    test_factors = {
        "A": {"momentum_60d": 10.0, "pe_percentile": 30.0},
        "B": {"momentum_60d": 5.0, "pe_percentile": 50.0},
        "C": {"momentum_60d": 15.0, "pe_percentile": 70.0},
    }
    factor_list = ["momentum_60d", "pe_percentile"]
    zscores = zscore_normalize(test_factors, factor_list)
    scores = equal_weight_score(zscores, factor_list)

    vals = [10.0, 5.0, 15.0]
    mean = np.mean(vals)
    std = np.std(vals, ddof=0)
    z_A = (10.0 - mean) / std * 1
    z_B = (5.0 - mean) / std * 1
    z_C = (15.0 - mean) / std * 1

    print(f"  momentum_60d: mean={mean:.4f}, std={std:.4f}")
    for label, expected_z, code in [("A", z_A, "A"), ("B", z_B, "B"), ("C", z_C, "C")]:
        ok = check(f"z-score {label} (momentum)", expected_z, zscores[code]["momentum_60d"])
        all_pass = all_pass and ok

    pe_vals = [30.0, 50.0, 70.0]
    pe_mean = np.mean(pe_vals)
    pe_std = np.std(pe_vals, ddof=0)
    z_A_pe = (30.0 - pe_mean) / pe_std * (-1)
    z_B_pe = (50.0 - pe_mean) / pe_std * (-1)
    z_C_pe = (70.0 - pe_mean) / pe_std * (-1)

    print(f"\n  pe_percentile (反向, direction=-1): mean={pe_mean:.4f}, std={pe_std:.4f}")
    for label, expected_z, code in [("A", z_A_pe, "A"), ("B", z_B_pe, "B"), ("C", z_C_pe, "C")]:
        ok = check(f"z-score {label} (pe_percentile)", expected_z, zscores[code]["pe_percentile"])
        all_pass = all_pass and ok

    print(f"\n  综合评分 (等权平均):")
    for code in ["A", "B", "C"]:
        expected_score = np.mean([zscores[code]["momentum_60d"], zscores[code]["pe_percentile"]])
        ok = check(f"score {code}", expected_score, scores[code])
        all_pass = all_pass and ok

    # ── 7. 总结 ────────────────────────────────────────
    section("总结")
    if all_pass:
        print("  ✅ 所有因子验证通过！")
    else:
        print("  ❌ 部分因子验证失败，请检查上方输出")

    print(f"\n  数据源架构:")
    print(f"    行情数据: AkShare fund_etf_hist_sina")
    print(f"    ETF列表: AkShare fund_etf_spot_em")
    print(f"    PE历史: AkShare stock_index_pe_lg (5000+条)")
    print(f"    中证估值: AkShare stock_zh_index_value_csindex")
    print(f"    个股估值: Tushare daily_basic (PE/PB/PS)")
    print(f"    ETF→指数映射: ETF_INDEX_MAP ({len(ETF_INDEX_MAP)}只ETF)")
    print(f"    存储: SQLite index_pe_history 表")
    print(f"    计算: valuation_repo.get_pe_percentile()")


if __name__ == "__main__":
    main()
