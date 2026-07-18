"""因子有效性检验工具

提供RankIC、ICIR、分层回测等因子检验指标，支持命令行独立运行。
"""
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def compute_forward_returns(prices: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算每只ETF每个日期的period日前瞻收益

    Args:
        prices: columns=['trade_date', 'code', 'close']
        period: 前瞻周期（交易日）

    Returns:
        DataFrame, columns=['trade_date', 'code', 'forward_return']
    """
    df = prices.sort_values(['code', 'trade_date']).copy()
    df['future_close'] = df.groupby('code')['close'].shift(-period)
    df['forward_return'] = (df['future_close'] - df['close']) / df['close']
    return df[['trade_date', 'code', 'forward_return']].dropna()


def compute_rank_ic(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_names: List[str],
    method: str = 'spearman',
) -> pd.DataFrame:
    """计算月度截面RankIC序列

    Args:
        factor_values: columns=['date', 'code', factor1, factor2, ...]
        forward_returns: columns=['date', 'code', 'forward_return']
        factor_names: 需计算的因子名列表
        method: 'spearman' (RankIC) or 'pearson' (IC)

    Returns:
        DataFrame, columns=['date', 'factor_name', 'ic']
    """
    merged = pd.merge(factor_values, forward_returns, on=['date', 'code'])

    rows = []
    for date in sorted(merged['date'].unique()):
        day_data = merged[merged['date'] == date]
        if len(day_data) < 5:
            continue
        for factor in factor_names:
            if factor not in day_data.columns:
                continue
            valid = day_data[[factor, 'forward_return']].dropna()
            if len(valid) < 5:
                continue
            if method == 'spearman':
                corr, _ = spearmanr(valid[factor], valid['forward_return'])
            else:
                corr = valid[factor].corr(valid['forward_return'])
            if not np.isnan(corr):
                rows.append({'date': date, 'factor_name': factor, 'ic': corr})

    return pd.DataFrame(rows)


def compute_icir(ic_series: pd.Series) -> Dict:
    """计算单因子的ICIR

    Returns:
        {'ic_mean', 'ic_std', 'icir', 'ic_positive_ratio', 'ic_t_stat'}
    """
    if len(ic_series) == 0:
        return {'ic_mean': 0, 'ic_std': 0, 'icir': 0, 'ic_positive_ratio': 0, 'ic_t_stat': 0}

    ic_mean = float(ic_series.mean())
    ic_std = float(ic_series.std(ddof=1))
    icir = ic_mean / ic_std if ic_std > 0 else 0
    ic_positive_ratio = float((ic_series > 0).sum() / len(ic_series))
    ic_t_stat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0

    return {
        'ic_mean': ic_mean,
        'ic_std': ic_std,
        'icir': icir,
        'ic_positive_ratio': ic_positive_ratio,
        'ic_t_stat': float(ic_t_stat),
    }


def stratified_backtest(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_name: str,
    n_groups: int = 5,
) -> pd.DataFrame:
    """分层回测：按因子值分组，计算各组未来收益

    Args:
        factor_values: columns=['date', 'code', factor_name]
        forward_returns: columns=['date', 'code', 'forward_return']
        factor_name: 因子名
        n_groups: 分组数

    Returns:
        DataFrame, columns=['date', 'group', 'avg_return']
        group=1是因子值最低组，group=n_groups是最高组
    """
    merged = pd.merge(factor_values, forward_returns, on=['date', 'code'])

    rows = []
    for date in sorted(merged['date'].unique()):
        day_data = merged[merged['date'] == date].copy()
        if len(day_data) < n_groups:
            continue
        valid = day_data[[factor_name, 'forward_return']].dropna()
        if len(valid) < n_groups:
            continue
        valid['group'] = pd.qcut(valid[factor_name], n_groups, labels=False, duplicates='drop') + 1
        for g in sorted(valid['group'].unique()):
            group_data = valid[valid['group'] == g]
            rows.append({
                'date': date,
                'group': int(g),
                'avg_return': float(group_data['forward_return'].mean()),
            })

    return pd.DataFrame(rows)


def _judge_verdict(ic_mean: float, icir: float, ic_positive_ratio: float,
                   monotonic: bool) -> str:
    """判定因子有效性

    判定逻辑：4个指标中≥2个达到"有效"判为有效，
    ≥2个达到"弱有效+"判为弱有效，否则无效。
    """
    abs_ic = abs(ic_mean)
    effective_count = 0
    weak_count = 0

    if abs_ic >= 0.05:
        effective_count += 1
    elif abs_ic >= 0.03:
        weak_count += 1

    if abs(icir) >= 0.3:
        effective_count += 1
    elif abs(icir) >= 0.1:
        weak_count += 1

    if ic_positive_ratio >= 0.6:
        effective_count += 1
    elif ic_positive_ratio >= 0.5:
        weak_count += 1

    if monotonic:
        effective_count += 1

    if effective_count >= 2:
        return '有效'
    elif weak_count + effective_count >= 2:
        return '弱有效'
    return '无效'


def _check_monotonicity(strat_df: pd.DataFrame, n_groups: int = 5) -> bool:
    """检查分层收益是否单调"""
    if strat_df.empty:
        return False
    avg_by_group = strat_df.groupby('group')['avg_return'].mean()
    if len(avg_by_group) < n_groups:
        return False
    # 检查是否单调递增或递减
    values = avg_by_group.values
    increasing = all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    decreasing = all(values[i] >= values[i + 1] for i in range(len(values) - 1))
    return increasing or decreasing


def analyze_factor(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_name: str,
    n_groups: int = 5,
) -> Dict:
    """单因子全量检验

    Returns:
        {ic_series, icir, stratified, monotonicity, verdict, ic_mean, ic_positive_ratio}
    """
    ic_df = compute_rank_ic(factor_values, forward_returns, [factor_name])
    ic_series = ic_df[ic_df['factor_name'] == factor_name]['ic']
    icir_result = compute_icir(ic_series)
    strat_df = stratified_backtest(factor_values, forward_returns, factor_name, n_groups)
    monotonic = _check_monotonicity(strat_df, n_groups)

    verdict = _judge_verdict(
        icir_result['ic_mean'], icir_result['icir'],
        icir_result['ic_positive_ratio'], monotonic
    )

    return {
        'ic_series': ic_df.to_dict('records'),
        'icir': icir_result,
        'stratified': strat_df.to_dict('records'),
        'monotonicity': '单调' if monotonic else '非单调',
        'verdict': verdict,
        'ic_mean': icir_result['ic_mean'],
        'ic_positive_ratio': icir_result['ic_positive_ratio'],
    }


def analyze_all_etfs(
    etf_codes: List[str],
    price_repo,
    valuation_repo,
    start_date: str,
    end_date: str,
    factor_names: List[str] = None,
    forward_period: int = 20,
) -> Dict:
    """全ETF池因子检验汇总

    Args:
        etf_codes: ETF代码列表
        price_repo: PriceRepository实例
        valuation_repo: ValuationRepo实例
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        factor_names: 因子名列表，None=默认['momentum_60d', 'pe_percentile', 'volatility_60d']
        forward_period: 前瞻周期

    Returns:
        {factor_name: {ic_mean, icir, ic_positive_ratio, monotonicity, verdict, ic_series, stratified}}
    """
    from strategy.scoring import compute_all_factors

    if factor_names is None:
        factor_names = ['momentum_60d', 'pe_percentile', 'volatility_60d']

    # 收集所有ETF的历史数据
    all_factor_rows = []
    all_return_rows = []
    all_prices = []

    for code in etf_codes:
        prices = price_repo.get_daily_price(code)
        if not prices or len(prices) < 120:
            continue

        # 转为DataFrame
        df = pd.DataFrame(prices)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date')
        df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]

        if len(df) < 120:
            continue

        # 获取PE历史
        pe_history = valuation_repo.get_pe_history(code) if hasattr(valuation_repo, 'get_pe_history') else None
        pe_pct_series = {}
        if pe_history:
            sorted_pe = sorted(pe_history, key=lambda x: x.get('trade_date', ''))
            pe_values = []
            for item in sorted_pe:
                pe_val = item.get('pe')
                trade_date = item.get('trade_date')
                if pe_val and pe_val > 0 and trade_date:
                    pe_values.append(pe_val)
                    if pe_values:
                        rank = sum(1 for v in pe_values if v <= pe_val)
                        pe_pct_series[trade_date] = (rank / len(pe_values)) * 100

        # 逐日计算因子值
        prices_list = df.to_dict('records')
        for i in range(60, len(prices_list)):  # 从第60天开始（确保有足够历史）
            sub_prices = prices_list[:i + 1]
            current_date = prices_list[i]['trade_date']
            date_str = current_date.strftime('%Y-%m-%d')

            pe_pct = pe_pct_series.get(date_str)
            factors = compute_all_factors(code, sub_prices, pe_percentile=pe_pct)

            row = {'date': current_date, 'code': code}
            for f in factor_names:
                row[f] = factors.get(f)
            all_factor_rows.append(row)

        # 前瞻收益
        price_df = df[['trade_date', 'close']].copy()
        price_df['code'] = code
        all_prices.append(price_df)

    if not all_factor_rows or not all_prices:
        return {}

    factor_df = pd.DataFrame(all_factor_rows)
    prices_df = pd.concat(all_prices, ignore_index=True)

    # 计算前瞻收益
    forward_df = compute_forward_returns(prices_df, period=forward_period)

    # 按月度采样（取每月最后一个交易日）
    factor_df['month'] = factor_df['date'].dt.to_period('M')
    monthly_factor = factor_df.groupby(['month', 'code']).last().reset_index()
    monthly_factor['date'] = monthly_factor['month'].dt.to_timestamp(how='end')

    forward_df['month'] = forward_df['trade_date'].dt.to_period('M')
    monthly_forward = forward_df.groupby(['month', 'code']).last().reset_index()
    monthly_forward['date'] = monthly_forward['month'].dt.to_timestamp(how='end')

    # 对每个因子做检验
    result = {}
    for factor in factor_names:
        if factor not in monthly_factor.columns:
            continue
        result[factor] = analyze_factor(
            monthly_factor[['date', 'code', factor]],
            monthly_forward[['date', 'code', 'forward_return']],
            factor,
        )

    return result


def main():
    """命令行入口"""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description='因子有效性检验')
    parser.add_argument('--factor', type=str, default=None, help='单个因子名')
    parser.add_argument('--all', action='store_true', help='检验所有因子')
    parser.add_argument('--start', type=str, default='2019-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2024-12-31', help='结束日期')
    parser.add_argument('--output', type=str, default=None, help='输出JSON文件路径')
    args = parser.parse_args()

    sys.path.insert(0, '.')

    from data.storage.db import init_db, get_db
    from data.storage.price_repo import PriceRepository
    from data.storage.valuation_repo import ValuationRepo
    from config.settings import ETF_UNIVERSE, DB_PATH

    init_db(DB_PATH)
    price_repo = PriceRepository(get_db(DB_PATH))
    valuation_repo = ValuationRepo(str(DB_PATH))

    etf_codes = [e['code'] for e in ETF_UNIVERSE]
    report = analyze_all_etfs(etf_codes, price_repo, valuation_repo, args.start, args.end)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"报告已保存到 {args.output}")
    else:
        print(f"\n{'='*60}")
        print(f"因子有效性分析报告 ({args.start} ~ {args.end})")
        print(f"ETF数: {len(etf_codes)}")
        print(f"{'='*60}\n")
        print(f"{'因子':<20} {'RankIC均值':<12} {'ICIR':<10} {'IC正比例':<10} {'单调性':<8} {'判定':<8}")
        print('-' * 70)
        for factor, metrics in report.items():
            icir_val = metrics.get('icir', {}).get('icir', 0)
            print(f"{factor:<20} {metrics['ic_mean']:<12.4f} {icir_val:<10.3f} "
                  f"{metrics['ic_positive_ratio']:<10.1%} {metrics['monotonicity']:<8} {metrics['verdict']:<8}")


if __name__ == '__main__':
    main()
