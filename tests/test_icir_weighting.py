import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from strategy.scoring import (
    compute_icir_weights,
    rank_ic_monthly,
)


def _make_ic(values_list):
    """values_list: list[float], 12个表示12个月IC"""
    return values_list


def test_icir_basic_distribution():
    """6因子：2高正 2低正 2负 → 仅正ICIR参与加权，权重和=1.0"""
    ic_hist = {
        'A': _make_ic([0.15]*6 + [0.10]*6),   # mean=0.125, std≈0.025 → icir≈5
        'B': _make_ic([0.10]*6 + [0.08]*6),   # mean=0.09, std≈0.01 → icir≈9
        'C': _make_ic([0.03]*6 + [0.02]*6),   # mean=0.025, std≈0.005 → icir≈5
        'D': _make_ic([0.02]*6 + [0.01]*6),   # mean=0.015, std≈0.005 → icir≈3
        'E': _make_ic([-0.01]*6 + [-0.02]*6), # 负ICIR → 权重0
        'F': _make_ic([0.00]*12),              # IC=0 → 权重0
    }
    w, excl = compute_icir_weights(ic_hist, rolling_months=12, min_icir_include=0.05)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w['A'] > 0 and w['B'] > 0 and w['C'] > 0 and w['D'] > 0
    assert w['E'] == 0 and 'E' in excl  # 连续6月≤0
    assert w['F'] == 0                   # ICIR≈0 < min_icir


def test_icir_consecutive_6m_exclusion():
    """构造：前6月正，后6月连续≤0 → 被剔除"""
    ic_hist = {
        'X': _make_ic([0.1, 0.05, 0.02, -0.01, -0.02, -0.03, -0.01, -0.02, -0.03, -0.01, -0.02, -0.03]),
    }
    w, excl = compute_icir_weights(ic_hist, 12)
    assert 'X' in excl
    assert excl['X'] == 'consecutive_6m_ic_le_0'
    assert w.get('X', 0) == 0


def test_icir_all_negative_fallback_equal():
    """全部负ICIR → 权重等权 + weight_mode=equal_weight_fallback"""
    ic_hist = {
        'A': _make_ic([-0.1]*12),
        'B': _make_ic([-0.2]*12),
    }
    w, excl, mode = compute_icir_weights(ic_hist, 12, return_mode=True)
    assert mode == 'equal_weight_fallback'
    np.testing.assert_almost_equal(w['A'], 0.5)
    np.testing.assert_almost_equal(w['B'], 0.5)


def test_icir_recovery_after_exclusion():
    """被剔除后 +3个月正IC > 0.02 → 恢复"""
    # 15个月：前12月含连续6月负 → 被exclude；再加3个月正IC均值>0.02
    vals_15 = [-0.1,-0.08,-0.05,-0.02,-0.01,-0.03,-0.02,-0.01,-0.03, 0.05,0.04,0.06,  0.03,0.03,0.04]
    ic_hist = {'R': vals_15}
    w, excl = compute_icir_weights(ic_hist, rolling_months=15)
    assert 'R' not in excl, f"应该恢复但excluded: {excl}"
    assert w.get('R', 0) > 0


def test_rank_ic_spearman_correctness():
    """完全线性 → RankIC≈1.0；完全反向 → ≈-1.0；全乱序 → ≈0"""
    # 截面：10个ETF，每个因子rank就是1~10；下月收益rank也是1~10一一对应
    f_ranks = pd.Series([1,2,3,4,5,6,7,8,9,10], dtype=float)
    r_ranks_pos = pd.Series([1,2,3,4,5,6,7,8,9,10], dtype=float)
    ic = rank_ic_monthly(f_ranks, r_ranks_pos)
    assert ic > 0.95, f"完全线性应≈1.0实际={ic}"

    r_ranks_neg = pd.Series([10,9,8,7,6,5,4,3,2,1], dtype=float)
    ic_neg = rank_ic_monthly(f_ranks, r_ranks_neg)
    assert ic_neg < -0.95
