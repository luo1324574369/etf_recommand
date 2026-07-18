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
