"""Walk-Forward优化引擎测试

验证窗口分割、鲁棒性得分计算、预设生成功能。
"""
import os
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

# 将项目根目录加入sys.path，确保可以导入strategy模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.walk_forward import (
    generate_walk_forward_presets,
    split_windows,
    calculate_robustness_score,
    _cagr_from_returns,
)


def test_split_windows():
    """测试窗口分割

    验证 2020-01-01 ~ 2024-12-31 按6个月分割：
    - 返回窗口数 >= 3
    - 每个窗口包含 train_end, val_start, val_end 字段
    """
    windows = split_windows('2020-01-01', '2024-12-31', val_months=6)
    # 5年按6个月分割应有10个窗口，至少3个
    assert len(windows) >= 3, f"窗口数应>=3，实际{len(windows)}"
    # 验证每个窗口的字段
    for w in windows:
        assert 'train_start' in w
        assert 'train_end' in w
        assert 'val_start' in w
        assert 'val_end' in w
        # train_start为None，运行时由数据决定
        assert w['train_start'] is None
        # val_end 应晚于 val_start
        assert w['val_end'] > w['val_start']


def test_calculate_robustness_score():
    """测试鲁棒性得分计算

    鲁棒性得分 = 0.7 * 平均夏普 + 0.3 * 最差夏普
    [0.8, 0.6, 0.9, 0.3] 的平均=0.65, 最差=0.3
    得分 = 0.7*0.65 + 0.3*0.3 = 0.545
    """
    sharpes = [0.8, 0.6, 0.9, 0.3]
    score = calculate_robustness_score(sharpes)
    avg = sum(sharpes) / len(sharpes)
    worst = min(sharpes)
    expected = 0.7 * avg + 0.3 * worst
    assert abs(score - expected) < 0.001, f"期望{expected}, 实际{score}"


def test_cagr_from_returns():
    """测试复合年化收益率(CAGR)计算

    两段收益率: +10%, +20%
    累计收益 = 1.1 * 1.2 - 1 = 0.32 = 32%
    """
    returns = [10.0, 20.0]
    cagr = _cagr_from_returns(returns)
    expected = 32.0
    assert abs(cagr - expected) < 0.01, f"期望{expected}%, 实际{cagr}%"

    # 空列表返回0
    assert _cagr_from_returns([]) == 0.0

    # 负收益
    returns_neg = [-10.0, 5.0]
    cagr_neg = _cagr_from_returns(returns_neg)
    expected_neg = (0.9 * 1.05 - 1) * 100
    assert abs(cagr_neg - expected_neg) < 0.01


def test_generate_presets_returns_5():
    """测试生成5个差异化预设

    使用模拟数据生成Walk-Forward预设，验证：
    - 返回5个预设
    - 参数组合不重复
    - 每个预设有 name/params/metrics 字段
    """
    # 生成模拟ETF行情数据
    dates = pd.date_range('2018-01-01', '2024-12-31', freq='D')
    np.random.seed(42)
    prices = np.cumprod(1 + np.random.normal(0.0005, 0.015, len(dates))) * 100
    data_dict = {
        'test_etf': pd.DataFrame({
            'trade_date': dates,
            'open': prices, 'high': prices * 1.01,
            'low': prices * 0.99, 'close': prices,
            'volume': np.random.randint(100000, 1000000, len(dates)),
        })
    }
    param_ranges = {
        'lookback_short': [20, 60],
        'lookback_long': [120, 250],
        'top_n': [1, 3],
        'rebalance_freq': [10, 20],
    }
    result = generate_walk_forward_presets(
        data_dict, '2020-01-01', '2024-12-31', param_ranges,
        max_combinations=16,
    )
    # 验证返回结构
    assert 'presets' in result
    # 验证返回5个预设
    assert len(result['presets']) == 5, f"期望5个预设，实际{len(result['presets'])}"
    # 验证预设参数不重复
    param_strs = set()
    for p in result['presets']:
        ps = str(p['params'])
        assert ps not in param_strs, f"重复参数: {ps}"
        param_strs.add(ps)
    # 验证每个预设有必需字段
    for p in result['presets']:
        assert 'name' in p, "预設缺少name字段"
        assert 'params' in p, "预設缺少params字段"
        assert 'metrics' in p, "预設缺少metrics字段"
        # 验证metrics包含所有必需指标
        m = p['metrics']
        assert 'cagr' in m
        assert 'avg_sharpe_ratio' in m
        assert 'avg_max_drawdown' in m
        assert 'avg_num_trades' in m
        assert 'robustness_score' in m
        assert 'worst_sharpe' in m
        assert 'validation_windows' in m
        assert 'full_annual_return' in m
        assert 'full_sharpe_ratio' in m
        assert 'full_max_drawdown' in m
        assert 'full_num_trades' in m


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
