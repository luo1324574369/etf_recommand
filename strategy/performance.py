"""
绩效指标计算模块
所有指标从净值序列统一计算，策略和基准用同一套函数保证口径一致
"""
import pandas as pd
import numpy as np
from typing import Dict


def calc_metrics(nav_df: pd.DataFrame, risk_free_rate: float = 0.02) -> Dict[str, float]:
    """计算完整绩效指标

    Args:
        nav_df: DataFrame[date, nav]
        risk_free_rate: 年化无风险利率，默认2%

    Returns:
        指标字典：total_return, annual_return, volatility, sharpe_ratio,
        sortino_ratio, max_drawdown, calmar_ratio
    """
    if nav_df.empty or len(nav_df) < 2:
        return {
            'total_return': 0.0,
            'annual_return': 0.0,
            'volatility': 0.0,
            'sharpe_ratio': 0.0,
            'sortino_ratio': 0.0,
            'max_drawdown': 0.0,
            'calmar_ratio': 0.0,
        }

    nav = nav_df['nav'].values
    daily_returns = nav_df['nav'].pct_change().dropna().values

    # 总收益率
    total_return = (nav[-1] / nav[0] - 1) * 100

    # 年化收益率
    days = len(nav_df)
    if days > 1 and nav[-1] > 0 and nav[0] > 0:
        annual_return = ((nav[-1] / nav[0]) ** (252 / days) - 1) * 100
    else:
        annual_return = 0.0

    # 年化波动率
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        volatility = daily_returns.std() * np.sqrt(252) * 100
    else:
        volatility = 0.0

    # 夏普比率
    if volatility > 0:
        sharpe_ratio = (annual_return / 100 - risk_free_rate) / (volatility / 100)
    else:
        sharpe_ratio = 0.0

    # 索提诺比率
    downside_returns = daily_returns[daily_returns < 0]
    if len(downside_returns) > 1 and downside_returns.std() > 0:
        downside_volatility = downside_returns.std() * np.sqrt(252)
        sortino_ratio = (annual_return / 100 - risk_free_rate) / downside_volatility
    else:
        sortino_ratio = float('inf')

    # 最大回撤
    cummax = np.maximum.accumulate(nav)
    drawdowns = (nav - cummax) / cummax
    max_drawdown = abs(drawdowns.min()) * 100 if drawdowns.min() < 0 else 0.0

    # 卡玛比率
    if max_drawdown > 0:
        calmar_ratio = annual_return / max_drawdown
    else:
        calmar_ratio = float('inf') if annual_return > 0 else 0.0

    return {
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'volatility': round(volatility, 2),
        'sharpe_ratio': round(sharpe_ratio, 2),
        'sortino_ratio': round(sortino_ratio, 2) if sortino_ratio != float('inf') else float('inf'),
        'max_drawdown': round(max_drawdown, 2),
        'calmar_ratio': round(calmar_ratio, 2) if calmar_ratio != float('inf') else float('inf'),
    }


def calc_drawdown_series(nav_df: pd.DataFrame) -> pd.DataFrame:
    """计算回撤时序数据

    Args:
        nav_df: DataFrame[date, nav]

    Returns:
        DataFrame[date, drawdown]，drawdown <= 0
    """
    if nav_df.empty:
        return pd.DataFrame(columns=['date', 'drawdown'])

    df = nav_df.copy()
    df['cummax'] = df['nav'].cummax()
    df['drawdown'] = (df['nav'] - df['cummax']) / df['cummax'] * 100
    return df[['date', 'drawdown']]
