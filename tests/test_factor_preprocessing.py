import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import pytest
from strategy.scoring import (
    winsorize_mad_3sigma,
    group_zscore,
    preprocess_factor_cross_section,
    reversal_20d,
)
from strategy.factors.volatility import VolatilityFactor


def test_winsorize_mad_3sigma_basic():
    """MAD缩尾：中位数±3*1.4826*MAD之外被夹逼"""
    vals = pd.Series([10, 11, 12, 13, 14, 15, 100])  # 100是极端值
    result = winsorize_mad_3sigma(vals)
    # 不允许100保留
    assert result.max() < 100
    # 原始非极端值保持不变（未超边界的）
    assert sorted(result.values.tolist()[:-1]) == sorted([10, 11, 12, 13, 14, 15])


def test_winsorize_mad_edge_cases():
    """边界：n<2、全NaN、全相同"""
    assert winsorize_mad_3sigma(pd.Series([5.0])).item() == 5.0
    s_nan = pd.Series([np.nan, np.nan])
    assert winsorize_mad_3sigma(s_nan).isna().all()
    s_same = pd.Series([7.0, 7.0, 7.0])
    assert (winsorize_mad_3sigma(s_same).values == s_same.values).all()


def test_group_zscore_separate_distribution():
    """宽基组(均值20)和消费组(均值35)各自zscore，不互相影响"""
    codes = ['A1','A2','A3','A4','A5', 'B1','B2','B3','B4','B5']
    values = {'A1':17.0,'A2':20.0,'A3':23.0,'A4':20.0,'A5':20.0,
              'B1':30.0,'B2':35.0,'B3':40.0,'B4':35.0,'B5':35.0}
    groups = {c: '宽基' if c.startswith('A') else '消费' for c in codes}
    out = group_zscore(codes, values, groups)
    # A组均值20: A1=(17-20)/σ_A < 0
    assert out['A1'] < 0
    # B组均值35: B1=(30-35)/σ_B < 0
    assert out['B1'] < 0
    # B1不应被A组均值20拉上去（若全局zscore B1≈+2.7，组内≈-σ_B<0）
    assert out['B1'] < 1.0


def test_group_zscore_fallback_when_group_too_small():
    """某组只有1只 → 降级全局zscore"""
    codes = ['X1', 'Y1', 'Y2']
    values = {'X1': 10.0, 'Y1': 20.0, 'Y2': 20.0}
    groups = {'X1': '稀有', 'Y1': '普通', 'Y2': '普通'}
    out = group_zscore(codes, values, groups)
    # X1=10, Y均值20, X1组只有1只→fallback: 按全局
    mean_all = sum(values.values()) / 3
    std_all = pd.Series(list(values.values())).std()
    expected_x1 = (10.0 - mean_all) / std_all if std_all else 0.0
    np.testing.assert_almost_equal(out['X1'], expected_x1, decimal=5)


def test_preprocess_factor_cross_section_applies_direction_and_groups():
    """统一预处理应同时应用分组标准化和因子方向。"""
    factors = {
        "A": {"pe_percentile": 10.0},
        "B": {"pe_percentile": 20.0},
        "C": {"pe_percentile": 30.0},
        "D": {"pe_percentile": 40.0},
    }
    result = preprocess_factor_cross_section(
        factors,
        ["pe_percentile"],
        {"A": "group1", "B": "group1", "C": "group2", "D": "group2"},
    )

    assert result["A"]["pe_percentile"] > result["B"]["pe_percentile"]
    assert result["C"]["pe_percentile"] > result["D"]["pe_percentile"]


def test_preprocess_factor_cross_section_preserves_missing_values():
    """缺失因子不应被标准化成中性伪值。"""
    factors = {
        "A": {"pe_percentile": 10.0},
        "B": {"pe_percentile": None},
        "C": {"pe_percentile": 30.0},
    }

    result = preprocess_factor_cross_section(factors, ["pe_percentile"])

    assert result["B"]["pe_percentile"] is None


def test_reversal_20d_direction():
    """跌10% → reversal值为正（direction=+1下得分越高越好）"""
    # 21个K线，第0天100 → 第20天90（跌10%）
    prices = [{'close': 100.0 - i*0.5} for i in range(21)]
    r = reversal_20d(prices)
    assert r is not None
    assert r > 0  # 跌越多反转因子越大
    np.testing.assert_almost_equal(r, -(90.0/100.0 - 1))


def test_volatility_respects_end_date():
    """波动率只能使用 end_date 当日及之前的价格。"""
    prices = []
    for i in range(70):
        prices.append({
            "trade_date": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
            "close": 100.0 if i < 60 else 100.0 + (i - 59) * 10.0,
        })

    factor = VolatilityFactor(period=60)
    before_future = factor.calculate("ETF", prices, "2025-03-01")
    with_future = factor.calculate("ETF", prices, "2025-03-10")

    assert before_future["volatility"] == 0
    assert with_future["volatility"] > before_future["volatility"]
