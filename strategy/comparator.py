"""
策略vs多基准对比模块
计算超额收益、信息比率、Alpha/Beta、跑赢胜率等对比指标
"""
import pandas as pd
import numpy as np
from typing import Dict
from strategy.performance import calc_metrics, calc_drawdown_series


def compare(
    strategy_nav: pd.DataFrame,
    benchmark_navs: Dict[str, pd.DataFrame],
    risk_free_rate: float = 0.02,
) -> Dict:
    """策略与多基准对比

    Args:
        strategy_nav: 策略净值 DataFrame[date, nav]
        benchmark_navs: {基准名称: 净值DataFrame}
        risk_free_rate: 年化无风险利率

    Returns:
        {
            'strategy_metrics': Dict,
            'benchmark_metrics': Dict[str, Dict],
            'comparison': Dict[str, Dict],
            'excess_nav_df': pd.DataFrame,
            'drawdown_df': pd.DataFrame,
        }
    """
    # 1. 计算策略绩效
    strategy_metrics = calc_metrics(strategy_nav, risk_free_rate)

    # 2. 计算每个基准绩效
    benchmark_metrics = {}
    for name, nav_df in benchmark_navs.items():
        if not nav_df.empty:
            benchmark_metrics[name] = calc_metrics(nav_df, risk_free_rate)

    # 3. 对齐策略和基准的交易日
    strategy_nav = strategy_nav.copy()
    strategy_nav['date'] = pd.to_datetime(strategy_nav['date'])
    strategy_nav = strategy_nav.reset_index(drop=True)

    # 过滤基准数据到策略日期范围内
    if not strategy_nav.empty:
        min_date = strategy_nav['date'].min()
        max_date = strategy_nav['date'].max()
        filtered_benchmark_navs = {}
        for name, bnav in benchmark_navs.items():
            if bnav.empty:
                continue
            bnav = bnav.copy()
            bnav['date'] = pd.to_datetime(bnav['date'])
            bnav = bnav[(bnav['date'] >= min_date) & (bnav['date'] <= max_date)]
            if not bnav.empty:
                first_nav = bnav.iloc[0]['nav']
                if first_nav > 0:
                    bnav['nav'] = bnav['nav'] / first_nav
                filtered_benchmark_navs[name] = bnav.reset_index(drop=True)
        benchmark_navs = filtered_benchmark_navs

    # 4. 计算对比指标
    comparison = {}
    excess_nav_data = {'date': strategy_nav['date'].values}
    drawdown_data = {'date': strategy_nav['date'].values}
    strategy_dd = calc_drawdown_series(strategy_nav)
    drawdown_data['strategy'] = strategy_dd['drawdown'].values

    strategy_returns = strategy_nav['nav'].pct_change().dropna()

    for name, nav_df in benchmark_navs.items():
        if nav_df.empty:
            continue

        nav_df = nav_df.copy()
        nav_df['date'] = pd.to_datetime(nav_df['date'])

        # 按日期outer join对齐
        merged = strategy_nav[['date', 'nav']].merge(
            nav_df[['date', 'nav']].rename(columns={'nav': 'benchmark_nav'}),
            on='date',
            how='outer',
        ).sort_values('date').reset_index(drop=True)
        merged[['nav', 'benchmark_nav']] = merged[['nav', 'benchmark_nav']].ffill()
        merged = merged.set_index('date')

        # 超额收益
        s_ret = strategy_metrics['total_return']
        b_ret = benchmark_metrics[name]['total_return']
        excess_return = s_ret - b_ret

        # 超额净值曲线（策略/基准，首日1.0）
        valid = merged.dropna(subset=['nav', 'benchmark_nav'])
        if len(valid) >= 2:
            first_nav = valid.iloc[0]['nav']
            first_bench = valid.iloc[0]['benchmark_nav']
            excess_nav = (valid['nav'] / first_nav) / (valid['benchmark_nav'] / first_bench)
            excess_nav_aligned = strategy_nav[['date']].merge(
                excess_nav.reset_index(), on='date', how='left'
            ).ffill()
            excess_nav_data[name] = excess_nav_aligned[0].values
        else:
            excess_nav_data[name] = [1.0] * len(strategy_nav)

        # 日收益率对齐
        s_daily = merged['nav'].pct_change().dropna()
        b_daily = merged['benchmark_nav'].pct_change().dropna()
        common = pd.DataFrame({'s': s_daily, 'b': b_daily}).dropna()

        # 信息比率
        if len(common) > 1 and common['s'].std() > 0:
            excess_daily = common['s'] - common['b']
            if excess_daily.std() > 0:
                information_ratio = (
                    excess_daily.mean() / excess_daily.std() * np.sqrt(252)
                )
            else:
                information_ratio = 0.0
        else:
            information_ratio = 0.0

        # Beta
        if len(common) > 1 and common['b'].var() > 0:
            beta = common['s'].cov(common['b']) / common['b'].var()
        else:
            beta = 0.0

        # Alpha (Jensen's Alpha, 年化, %)
        s_annual = strategy_metrics['annual_return'] / 100
        b_annual = benchmark_metrics[name]['annual_return'] / 100
        alpha = (s_annual - risk_free_rate - beta * (b_annual - risk_free_rate)) * 100

        # 月度/季度跑赢胜率
        win_rate_monthly = _calc_win_rate(common['s'], common['b'], 'ME')
        win_rate_quarterly = _calc_win_rate(common['s'], common['b'], 'QE')

        comparison[name] = {
            'excess_return': round(excess_return, 2),
            'information_ratio': round(information_ratio, 2),
            'beta': round(beta, 4),
            'alpha': round(alpha, 2),
            'win_rate_monthly': win_rate_monthly,
            'win_rate_quarterly': win_rate_quarterly,
        }

        # 基准回撤
        bench_dd = calc_drawdown_series(nav_df)
        bench_dd_aligned = strategy_nav[['date']].merge(
            bench_dd, on='date', how='left'
        )
        drawdown_data[name] = bench_dd_aligned['drawdown'].values

    excess_nav_df = pd.DataFrame(excess_nav_data)
    drawdown_df = pd.DataFrame(drawdown_data)

    cr_data = {'date': strategy_nav['date'].values}
    dr_data = {'date': strategy_nav['date'].values}

    cr_data['strategy'] = (strategy_nav['nav'] / strategy_nav.iloc[0]['nav'] - 1) * 100
    dr_data['strategy'] = strategy_nav['nav'].pct_change() * 100

    for name, nav_df in benchmark_navs.items():
        if nav_df.empty:
            continue
        nav_df = nav_df.copy()
        nav_df['date'] = pd.to_datetime(nav_df['date'])

        nav_aligned = strategy_nav[['date']].merge(
            nav_df[['date', 'nav']], on='date', how='left'
        ).ffill()

        if nav_aligned['nav'].iloc[0] > 0:
            cr_data[name] = (nav_aligned['nav'] / nav_aligned.iloc[0]['nav'] - 1) * 100
        else:
            cr_data[name] = [0.0] * len(strategy_nav)

        dr_data[name] = nav_aligned['nav'].pct_change() * 100

    cumulative_return_df = pd.DataFrame(cr_data)
    daily_return_df = pd.DataFrame(dr_data)

    return {
        'strategy_metrics': strategy_metrics,
        'benchmark_metrics': benchmark_metrics,
        'comparison': comparison,
        'excess_nav_df': excess_nav_df,
        'drawdown_df': drawdown_df,
        'cumulative_return_df': cumulative_return_df,
        'daily_return_df': daily_return_df,
    }


def _calc_win_rate(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    freq: str,
) -> float:
    """计算跑赢胜率

    Args:
        strategy_returns: 策略日收益率Series
        benchmark_returns: 基准日收益率Series
        freq: 重采样频率 'ME'=月度, 'QE'=季度

    Returns:
        胜率(%)，数据不足返回None
    """
    df = pd.DataFrame({
        's': strategy_returns,
        'b': benchmark_returns,
    })
    df['s_cum'] = (1 + df['s']).cumprod()
    df['b_cum'] = (1 + df['b']).cumprod()

    period_s = df['s_cum'].resample(freq).last().pct_change().dropna()
    period_b = df['b_cum'].resample(freq).last().pct_change().dropna()

    common = pd.DataFrame({'s': period_s, 'b': period_b}).dropna()

    if freq == 'QE' and len(common) < 4:
        return None
    if freq == 'ME' and len(common) < 2:
        return None

    wins = (common['s'] > common['b']).sum()
    return round(wins / len(common) * 100, 1)
