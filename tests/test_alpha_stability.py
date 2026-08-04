"""Alpha 稳定性模块单元测试

所有指标使用手算的构造序列，避免依赖外部数据。
策略净值 nav_s / 基准净值 nav_b 均为 60 天已知数据。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import pytest

# ---------- 构造已知数据（60 天，手算断言） ----------
def make_fixture():
    """构造 60 交易日的策略+基准净值，特点：
    - 前 30 天：策略跑赢基准（牛市+抗跌）
    - 后 30 天：策略跑输基准（单边快涨 Beta 暴露不足）
    - 累计超额: +1.2%（前半段的缓冲）
    - 近 21 天（约1月）超额: -2.4%
    - 近 42 天（约2月）超额: -3.5%
    """
    dates = pd.date_range('2024-01-02', periods=60, freq='B')  # 60 个工作日

    # 基准：每天稳定 +0.1%（累计 +6.18%）
    bench_daily = np.full(60, 0.001)
    nav_b = 1.0 * (1 + bench_daily).cumprod()

    # 策略：前20天 +0.2%/天，中间10天 -0.05%/天，后30天 0.05%/天
    strat_daily = np.concatenate([
        np.full(20, 0.002),   # 前20天: +0.2%/天  累计≈+4.08%
        np.full(10, -0.0005), # 中间10天: -0.05%/天  累计≈+3.56%
        np.full(30, 0.0005),  # 后30天: +0.05%/天   累计≈+4.11%
    ])
    nav_s = 1.0 * (1 + strat_daily).cumprod()

    nav_df = pd.DataFrame({'date': dates, 'nav': nav_s})
    benchmark_navs = {
        '沪深300': pd.DataFrame({'date': dates, 'nav': nav_b})
    }
    return nav_df, benchmark_navs, dates, nav_s.values, nav_b.values


def test_import_function_exists():
    """compute_alpha_stability 函数应可导入"""
    from strategy.backtest_utils import compute_alpha_stability
    assert callable(compute_alpha_stability)
