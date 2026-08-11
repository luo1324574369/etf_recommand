"""样本外因子验证脚本（Out-of-Sample Factor Validation）

按时间 8:2 切分历史数据，对每个因子计算训练集与测试集的月度 RankIC 序列，
输出衰减率报告，判断因子是否在样本外仍然有效。

流程：
1. 加载 ETF_UNIVERSE 中所有 ETF 的行情数据
2. 找到每月最后一个交易日，构成月度截面序列
3. 对每个截面日，用 compute_all_factors 计算因子值，并计算到下一截面日的前向收益
4. 用 rank_ic_monthly 计算每月每个因子的 IC
5. 按时间切分 IC 序列（默认 2019-01~2023-06 训练，2023-07~至今 测试）
6. 对每个因子计算：训练集 IC 均值/ICIR、测试集 IC 均值/ICIR、衰减率
7. 验收：RankIC 衰减 ≤ 30% 且 ICIR 不打对折（测试 ICIR ≥ 训练 ICIR * 0.5）

使用方法:
    .venv/bin/python scripts/validate_factor_oos.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from tabulate import tabulate

from config.settings import ETF_UNIVERSE, DB_PATH
from data.storage.db import get_db
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo
from strategy.scoring import (
    compute_all_factors, winsorize_mad_3sigma, group_zscore,
    rank_ic_monthly, FACTOR_DIRECTIONS, FACTOR_LOGIC, DEFAULT_FACTORS,
)

START = '2019-01-01'
END = '2026-12-01'
SPLIT_DATE = '2023-07-01'  # 前80%训练，后20%测试
MIN_CROSS_SECTION = 3      # 至少3个ETF有数据才计算截面IC


def load_prices(price_repo):
    """加载 ETF_UNIVERSE 中所有 ETF 的行情数据，过滤到 [START, END]"""
    code_prices = {}
    for e in ETF_UNIVERSE:
        code = e['code']
        prices = price_repo.get_daily_price(code)
        if not prices:
            continue
        prices = [p for p in prices if START <= p['trade_date'] <= END]
        if len(prices) >= 60:
            code_prices[code] = prices
    return code_prices


def find_monthly_last_dates(code_prices):
    """收集所有交易日，找出每月最后一个交易日（按所有 ETF 日期并集）"""
    all_dates_set = set()
    for prices in code_prices.values():
        for p in prices:
            all_dates_set.add(p['trade_date'])
    all_dates_sorted = sorted(all_dates_set)

    monthly_last_dates = []
    last_ym = None
    last_date = None
    for d_str in all_dates_sorted:
        ym = d_str[:7]
        if last_ym is None:
            last_ym = ym
            last_date = d_str
        elif ym == last_ym:
            last_date = d_str
        else:
            monthly_last_dates.append(last_date)
            last_ym = ym
            last_date = d_str
    if last_date:
        monthly_last_dates.append(last_date)
    return monthly_last_dates


def compute_monthly_ic_series(code_prices, monthly_last_dates, valuation_repo, code_to_sector):
    """对每个截面日计算因子值与下月收益，返回 {factor: [(cut_date, ic), ...]}

    因子预处理与策略保持一致：先 winsorize_mad_3sigma，再 group_zscore（按赛道分组）。
    """
    # 构建 code -> {trade_date: idx} 映射加速查找
    code_date_idx = {}
    for code, prices in code_prices.items():
        code_date_idx[code] = {p['trade_date']: j for j, p in enumerate(prices)}

    factor_ic = {f: [] for f in DEFAULT_FACTORS}
    n_dates = len(monthly_last_dates)
    t0 = time.time()

    for i in range(n_dates - 1):
        cut_date_str = monthly_last_dates[i]
        next_date_str = monthly_last_dates[i + 1]

        etf_factor_values = {}  # {factor: {code: value}}
        etf_returns = {}        # {code: next_month_return}
        codes_with_data = []

        for code, prices in code_prices.items():
            dmap = code_date_idx[code]
            cut_idx = dmap.get(cut_date_str)
            next_idx = dmap.get(next_date_str)
            if cut_idx is None or cut_idx < 30:
                continue
            if next_idx is None or next_idx <= cut_idx:
                continue

            cut_prices = prices[:cut_idx + 1]
            try:
                cut_close = float(cut_prices[-1]['close'])
                next_close = float(prices[next_idx]['close'])
            except (TypeError, ValueError):
                continue
            if cut_close <= 0:
                continue
            etf_returns[code] = (next_close / cut_close - 1)

            # pe_percentile：与 multi_factor._warmup_ic_history 一致
            pe_pct = None
            try:
                pe_pct = valuation_repo.get_pe_percentile(code, end_date=cut_date_str)
            except Exception:
                pe_pct = None

            # dividend_yield：取截止日最近一条估值
            dy_val = None
            try:
                valuations = valuation_repo.get_valuation(code, end_date=cut_date_str)
                if valuations:
                    dy = valuations[0].get('dividend_yield')
                    dy_val = float(dy) if dy and dy > 0 else None
            except Exception:
                dy_val = None

            factors = compute_all_factors(
                code, cut_prices, end_date=cut_date_str,
                pe_percentile=pe_pct, dividend_yield=dy_val,
            )
            if not factors:
                continue

            for f, v in factors.items():
                etf_factor_values.setdefault(f, {})[code] = v
            codes_with_data.append(code)

        if len(codes_with_data) < MIN_CROSS_SECTION:
            continue

        codes = codes_with_data
        for factor in DEFAULT_FACTORS:
            if factor not in FACTOR_DIRECTIONS:
                continue
            vals = etf_factor_values.get(factor, {})
            valid_codes = [c for c in codes if c in vals and vals[c] is not None]
            if len(valid_codes) < MIN_CROSS_SECTION:
                continue

            s = pd.Series({c: vals[c] for c in valid_codes})
            s = winsorize_mad_3sigma(s)
            zscores = group_zscore(valid_codes, {c: s[c] for c in valid_codes}, code_to_sector)

            factor_series = pd.Series({c: zscores.get(c, 0.0) for c in valid_codes})
            return_series = pd.Series({c: etf_returns.get(c, np.nan) for c in valid_codes})
            ic = rank_ic_monthly(factor_series, return_series)
            factor_ic[factor].append((cut_date_str, ic))

        if (i + 1) % 12 == 0 or i == n_dates - 2:
            elapsed = time.time() - t0
            print(f'  进度: {i + 1}/{n_dates - 1} 截面日 ({cut_date_str})  耗时 {elapsed:.1f}s')

    return factor_ic


def _ic_stats(adj_values):
    """计算方向调整后IC的均值与ICIR（ddof=1）"""
    valid = [v for v in adj_values if v is not None]
    if len(valid) < 2:
        return None, None
    mean_ic = float(np.mean(valid))
    std_ic = float(np.std(valid, ddof=1))
    if std_ic == 0 or np.isnan(std_ic):
        return mean_ic, None
    return mean_ic, mean_ic / std_ic


def main():
    print('=' * 70)
    print('样本外因子验证（OOS Factor Validation）')
    print(f'数据区间: {START} ~ {END}  |  训练/测试切分日: {SPLIT_DATE}')
    print(f'验证因子: {", ".join(DEFAULT_FACTORS)}')
    print('=' * 70)

    price_repo = PriceRepository(get_db(str(DB_PATH)))
    valuation_repo = ValuationRepo(str(DB_PATH))
    code_to_sector = {e['code']: e.get('sector', '其他') for e in ETF_UNIVERSE}

    print('\n[1/3] 加载行情数据...')
    code_prices = load_prices(price_repo)
    print(f'  有效ETF数量: {len(code_prices)}')

    print('\n[2/3] 计算月度截面IC序列...')
    monthly_last_dates = find_monthly_last_dates(code_prices)
    if len(monthly_last_dates) < 4:
        print(f'  [ERROR] 月度截面数不足: {len(monthly_last_dates)}')
        return
    print(f'  月度截面数: {len(monthly_last_dates)} '
          f'({monthly_last_dates[0]} ~ {monthly_last_dates[-1]})')

    factor_ic = compute_monthly_ic_series(
        code_prices, monthly_last_dates, valuation_repo, code_to_sector,
    )

    print('\n[3/3] 计算训练/测试集IC统计与衰减率...')
    rows = []
    for factor in DEFAULT_FACTORS:
        ic_list = factor_ic.get(factor, [])
        train_raw = [v for d, v in ic_list if d < SPLIT_DATE]
        test_raw = [v for d, v in ic_list if d >= SPLIT_DATE]

        direction = FACTOR_DIRECTIONS.get(factor, 1)
        train_adj = [v * direction for v in train_raw if v is not None]
        test_adj = [v * direction for v in test_raw if v is not None]

        train_ic, train_icir = _ic_stats(train_adj)
        test_ic, test_icir = _ic_stats(test_adj)

        logic = FACTOR_LOGIC.get(factor, {}).get('logic', '-')

        # IC 衰减率 (train-test)/train*100
        if train_ic is not None and train_ic != 0:
            ic_decay = (train_ic - (test_ic if test_ic is not None else 0.0)) / train_ic * 100
        else:
            ic_decay = None

        # ICIR 比值 test/train
        if train_icir is not None and train_icir != 0 and test_icir is not None:
            icir_ratio = test_icir / train_icir
        else:
            icir_ratio = None

        # 验收：RankIC衰减≤30% 且 ICIR比值≥0.5
        pass_decay = ic_decay is not None and ic_decay <= 30
        pass_icir = icir_ratio is not None and icir_ratio >= 0.5
        result = 'PASS' if (pass_decay and pass_icir) else 'FAIL'

        rows.append({
            'Factor': factor,
            'Logic': logic,
            'Train_IC': f'{train_ic:+.4f}' if train_ic is not None else '-',
            'Train_ICIR': f'{train_icir:+.3f}' if train_icir is not None else '-',
            'Test_IC': f'{test_ic:+.4f}' if test_ic is not None else '-',
            'Test_ICIR': f'{test_icir:+.3f}' if test_icir is not None else '-',
            'IC_Decay%': f'{ic_decay:.1f}' if ic_decay is not None else '-',
            'ICIR_Ratio': f'{icir_ratio:.2f}' if icir_ratio is not None else '-',
            'Result': result,
            'n_train': len(train_adj),
            'n_test': len(test_adj),
        })

    headers = ['Factor', 'Logic', 'Train_IC', 'Train_ICIR',
               'Test_IC', 'Test_ICIR', 'IC_Decay%', 'ICIR_Ratio', 'Result']
    table_rows = [[r[k] for k in headers] for r in rows]
    print()
    print(tabulate(table_rows, headers=headers, tablefmt='grid'))

    # 样本量明细
    print('\n各因子训练/测试样本量（月度IC数）:')
    for r in rows:
        print(f'  {r["Factor"]:<16} train={r["n_train"]:>3}  test={r["n_test"]:>3}')

    # 总结
    passed = [r['Factor'] for r in rows if r['Result'] == 'PASS']
    failed = [r['Factor'] for r in rows if r['Result'] == 'FAIL']
    print('\n' + '=' * 70)
    print('验证总结')
    print('=' * 70)
    print(f'验收标准: RankIC衰减 ≤ 30% 且 ICIR比值 ≥ 0.5（测试集ICIR不打对折）')
    print(f'通过验证的因子 ({len(passed)}/{len(rows)}): '
          f'{", ".join(passed) if passed else "无"}')
    print(f'未通过验证的因子 ({len(failed)}/{len(rows)}): '
          f'{", ".join(failed) if failed else "无"}')
    if failed:
        print('\n未通过因子归因:')
        for r in rows:
            if r['Result'] != 'FAIL':
                continue
            reasons = []
            if r['IC_Decay%'] == '-':
                reasons.append('训练集IC缺失或为0')
            elif float(r['IC_Decay%']) > 30:
                reasons.append(f"IC衰减过大({r['IC_Decay%']}%)")
            if r['ICIR_Ratio'] == '-':
                reasons.append('ICIR无法计算(训练/测试数据不足)')
            elif float(r['ICIR_Ratio']) < 0.5:
                reasons.append(f"ICIR打对折(比值{r['ICIR_Ratio']})")
            print(f'  - {r["Factor"]}: {"; ".join(reasons)}')


if __name__ == '__main__':
    main()
