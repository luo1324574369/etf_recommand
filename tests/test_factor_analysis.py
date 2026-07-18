"""因子有效性检验测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
import pytest

from strategy.factor_analysis import (
    compute_forward_returns,
    compute_rank_ic,
    compute_icir,
    stratified_backtest,
    analyze_factor,
)


def test_compute_forward_returns():
    """测试前瞻收益计算
    10个交易日，period=3
    第7日（index=6, close=10）的forward_return = (close[9]-close[6])/close[6] = (13-10)/10 = 0.3
    """
    dates = pd.date_range('2023-01-01', periods=10, freq='D')
    df = pd.DataFrame({
        'trade_date': dates,
        'code': '510300',
        'close': [10, 11, 12, 11, 10, 9, 10, 11, 12, 13],
    })
    result = compute_forward_returns(df, period=3)
    # 第7日（index=6, close=10）的forward_return = (close[9]-close[6])/close[6] = (13-10)/10 = 0.3
    row = result[result['trade_date'] == dates[6]].iloc[0]
    assert abs(row['forward_return'] - 0.3) < 0.001
    # 最后3天无前瞻收益
    assert len(result) == 7


def test_compute_rank_ic():
    """测试RankIC计算
    完全正相关 → IC=1.0
    """
    dates = pd.date_range('2023-01-01', periods=3, freq='MS')
    # 完全正相关
    factor_df = pd.DataFrame({
        'date': dates.tolist() * 3,
        'code': ['A', 'B', 'C'] * 3,
        'momentum_60d': [1, 2, 3, 1, 2, 3, 1, 2, 3],
    })
    return_df = pd.DataFrame({
        'date': dates.tolist() * 3,
        'code': ['A', 'B', 'C'] * 3,
        'forward_return': [0.01, 0.02, 0.03, 0.01, 0.02, 0.03, 0.01, 0.02, 0.03],
    })
    ic_df = compute_rank_ic(factor_df, return_df, ['momentum_60d'])
    # 每个日期的IC应为1.0
    for _, row in ic_df.iterrows():
        assert abs(row['ic'] - 1.0) < 0.001, f"期望IC=1.0，实际{row['ic']}"


def test_compute_icir():
    """测试ICIR计算
    IC序列 [0.1, 0.2, 0.15, 0.05, 0.1]
    IC均值=0.12, ICIR=0.12/std
    """
    ic_series = pd.Series([0.1, 0.2, 0.15, 0.05, 0.1])
    result = compute_icir(ic_series)
    expected_mean = 0.12
    assert abs(result['ic_mean'] - expected_mean) < 0.001
    assert result['ic_positive_ratio'] == 1.0  # 全部为正
    assert result['icir'] > 0


def test_stratified_backtest():
    """测试分层回测
    构造单调递增的因子-收益关系，验证5组收益单调
    """
    np.random.seed(42)
    dates = pd.date_range('2023-01-01', periods=5, freq='MS')
    rows_factor = []
    rows_return = []
    for d in dates:
        # 50只ETF，因子值1-50，收益与因子值正相关
        for i in range(50):
            rows_factor.append({'date': d, 'code': f'ETF{i}', 'momentum_60d': i})
            rows_return.append({'date': d, 'code': f'ETF{i}',
                               'forward_return': i * 0.001 + np.random.normal(0, 0.001)})
    factor_df = pd.DataFrame(rows_factor)
    return_df = pd.DataFrame(rows_return)
    result = stratified_backtest(factor_df, return_df, 'momentum_60d', n_groups=5)
    # 每个日期应有5组
    for d in dates:
        day_result = result[result['date'] == d]
        assert len(day_result) == 5
        # 组5（高因子值）收益应 > 组1（低因子值）
        g5 = day_result[day_result['group'] == 5]['avg_return'].iloc[0]
        g1 = day_result[day_result['group'] == 1]['avg_return'].iloc[0]
        assert g5 > g1, f"组5收益{g5}应大于组1收益{g1}"


def test_analyze_factor_verdict():
    """测试有效性判定
    构造强因子数据，验证判定结果
    """
    dates = pd.date_range('2023-01-01', periods=24, freq='MS')
    rows_f, rows_r = [], []
    np.random.seed(42)
    for d in dates:
        for i in range(20):
            factor_val = i
            return_val = i * 0.001 + np.random.normal(0, 0.002)
            rows_f.append({'date': d, 'code': f'ETF{i}', 'momentum_60d': factor_val})
            rows_r.append({'date': d, 'code': f'ETF{i}', 'forward_return': return_val})
    factor_df = pd.DataFrame(rows_f)
    return_df = pd.DataFrame(rows_r)

    result = analyze_factor(factor_df, return_df, 'momentum_60d')
    # 验证指标存在
    assert 'ic_mean' in result
    assert 'icir' in result
    assert 'ic_positive_ratio' in result
    assert 'verdict' in result
    assert result['verdict'] in ['有效', '弱有效', '无效']
