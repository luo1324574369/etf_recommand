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
    return nav_df, benchmark_navs, dates, nav_s, nav_b


def test_import_function_exists():
    """compute_alpha_stability 函数应可导入"""
    from strategy.backtest_utils import compute_alpha_stability
    assert callable(compute_alpha_stability)


# ---------- 必选层：日期对齐 + excess_nav ----------
def test_excess_nav_series_shape():
    from strategy.backtest_utils import compute_alpha_stability
    nav_df, benchmark_navs, *_ = make_fixture()
    result = compute_alpha_stability(nav_df, benchmark_navs)
    ens = result['excess_nav_series']
    assert isinstance(ens, pd.DataFrame)
    assert list(ens.columns) == ['date', 'excess_nav']
    assert len(ens) == 60
    # 首日 excess_nav 约=1.0（两个净值都从1起步）
    assert abs(ens['excess_nav'].iloc[0] - 1.0) < 0.001


def test_max_relative_drawdown_hand_calc():
    """用构造数据手算最大相对回撤。

    超额净值趋势：
    前20天 s涨得比b快 → excess_nav 从1.0上升到约 1.0408/1.0202≈1.0202（第20天 peak）
    之后策略慢于基准 → excess_nav 持续下降，末天约 1.0411/1.0618≈0.9805
    → 最大相对回撤≈ (0.9805 / 1.0202 - 1)*100 ≈ -3.89%
    这里只断言：末值<1.0、peak>1.0、回撤为负、幅度在[-10%, -1%]区间（避免浮点）
    """
    from strategy.backtest_utils import compute_alpha_stability
    nav_df, benchmark_navs, dates, ns, nb = make_fixture()
    result = compute_alpha_stability(nav_df, benchmark_navs)

    mdd = result['max_relative_drawdown']
    info = result['max_relative_dd_info']
    assert mdd is not None and isinstance(mdd, float)
    assert -10 < mdd < -1          # 回撤为负
    assert info is not None
    assert 'date_start' in info and 'date_peak' in info and 'date_end' in info
    # peak 应早于 end
    peak_dt = pd.to_datetime(info['date_peak'])
    end_dt = pd.to_datetime(info['date_end'])
    assert peak_dt <= end_dt
    # 回撤值与 excess_nav 的真实最小回撤一致
    ens = result['excess_nav_series']
    real_mdd = float(((ens['excess_nav'] / ens['excess_nav'].cummax()) - 1).min() * 100)
    assert abs(mdd - real_mdd) < 0.01


def test_rolling_windows_schema_and_values():
    from strategy.backtest_utils import compute_alpha_stability
    nav_df, benchmark_navs, dates, ns, nb = make_fixture()
    result = compute_alpha_stability(nav_df, benchmark_navs)
    rw = result['rolling_windows']
    assert isinstance(rw, pd.DataFrame)
    assert list(rw.columns) == ['window', 'strategy_pct', 'benchmark_pct', 'excess_pct', 'sufficient_data']
    # 窗口顺序固定
    assert list(rw['window']) == ['1月', '3月', '6月', '1年', '成立以来']
    # 超额列 = 策略-基准
    for _, row in rw.iterrows():
        assert abs(row['excess_pct'] - (row['strategy_pct'] - row['benchmark_pct'])) < 0.001
    # 60天的构造数据：1月/3月窗口充足，6月/1年不足
    suff = dict(zip(rw['window'], rw['sufficient_data']))
    assert suff['1月'] is True
    assert suff['成立以来'] is True
    # 成立以来 = 全部60天
    full = rw[rw['window'] == '成立以来'].iloc[0]
    assert abs(full['strategy_pct']  - (ns[-1] - 1) * 100) < 0.01
    assert abs(full['benchmark_pct'] - (nb[-1] - 1) * 100) < 0.01


def test_rolling_alpha_series_schema():
    from strategy.backtest_utils import compute_alpha_stability
    nav_df, benchmark_navs, *_ = make_fixture()
    result = compute_alpha_stability(nav_df, benchmark_navs)
    ra = result['rolling_alpha_series']
    assert isinstance(ra, pd.DataFrame)
    assert list(ra.columns) == ['date', 'excess_63d', 'excess_126d', 'excess_252d']
    # 60天不足63/126/252 → 全部 NaN 或 0，不应报错
    assert len(ra) == 60


def test_te_and_ir_hand_calc():
    """60天足够算日频TE/IR。

    TE = std(策略日收益 - 基准日收益) * sqrt(252) * 100 (%)
    IR = 年化超额 / TE（若TE为0返回None）
    """
    from strategy.backtest_utils import compute_alpha_stability
    nav_df, benchmark_navs, dates, ns, nb = make_fixture()
    result = compute_alpha_stability(nav_df, benchmark_navs)
    te = result['tracking_error']
    ir = result['information_ratio']
    # 手算：策略日收益 - 基准日收益
    s_d = np.diff(ns) / ns[:-1]
    b_d = np.diff(nb) / nb[:-1]
    diff = s_d - b_d
    expected_te = float(np.std(diff, ddof=1) * np.sqrt(252) * 100)
    assert te is not None
    assert abs(te - expected_te) < 0.01
    # IR 非空。本构造数据最后30天跑输，IR 应为负数
    assert ir is not None
    assert ir < 0


def test_monthly_hit_rate_and_capture():
    """构造数据跨 2024-01 与 2024-02（约两个月）。
    月度命中率= 月超额>0 的月份数 / 总月份数 × 100。
    """
    from strategy.backtest_utils import compute_alpha_stability
    nav_df, benchmark_navs, dates, ns, nb = make_fixture()
    result = compute_alpha_stability(nav_df, benchmark_navs)
    hr = result['monthly_hit_rate']
    cap = result['up_down_capture']
    assert hr is not None
    assert 0 <= hr <= 100
    assert cap is not None
    assert 'up_capture_pct' in cap and 'down_capture_pct' in cap
    assert 'up_months_count' in cap and 'down_months_count' in cap


def test_warning_level():
    """构造数据特点：
    成立以来超额≈+4.11%-6.18%≈-2.07%（累计超额为负，不触发）
    需补一个单独 fixture 验证 warning 逻辑。
    """
    from strategy.backtest_utils import compute_alpha_stability

    # 构造：累计超额+1%，但近21天-3% → severe
    # periods=300 确保能区分成立以来/1年(252天)/半年(126天)三个窗口
    dates = pd.date_range('2024-01-02', periods=300, freq='B')
    # 基准：每天稳定 +0.05%
    nb = 1.0 * (1 + np.full(300, 0.0005)).cumprod()
    # 策略：前48天大幅跑赢（确保成立以来总体正），后252天原地踏步（基准继续涨 → 近1年/半年超额为负）
    r = np.concatenate([np.full(48, 0.004), np.full(252, 0.0)])
    ns = 1.0 * (1 + r).cumprod()

    nav_df = pd.DataFrame({'date': dates, 'nav': ns})
    benchmark_navs = {'沪深300': pd.DataFrame({'date': dates, 'nav': nb})}
    result = compute_alpha_stability(nav_df, benchmark_navs)

    cumulative_excess = (ns[-1] - 1) * 100 - (nb[-1] - 1) * 100
    assert cumulative_excess > 0  # 确保累计为正
    assert result['recent_failed'] is True
    assert result['warning_level'] == 'severe'


def test_run_backtest_returns_alpha_stability_field():
    """端到端集成：调用 run_backtest 跑极小数据量，验证 alpha_stability 字段 + schema 齐全"""
    import pandas as pd
    from strategy.backtest_utils import run_backtest

    dates = pd.date_range('2023-01-03', periods=100, freq='B')
    np.random.seed(42)
    closes = 1.0 * (1 + np.random.normal(0.0005, 0.015, 100)).cumprod()
    df = pd.DataFrame({
        'trade_date': dates,
        'open': closes * (1 - np.random.uniform(0, 0.01, 100)),
        'high': closes * (1 + np.random.uniform(0, 0.02, 100)),
        'low':  closes * (1 - np.random.uniform(0, 0.02, 100)),
        'close': closes,
        'volume': np.random.randint(100000, 1000000, 100),
    })
    data_dict = {'510300': df}

    from strategy import multi_factor
    result = run_backtest(
        multi_factor.MultiFactorStrategy,
        data_dict,
        initial_capital=100000,
        commission_rate=0.0003,
        start_date='2023-01-03',
        end_date='2023-05-31',
    )
    assert 'alpha_stability' in result
    asd = result['alpha_stability']
    expected_keys = [
        'rolling_windows', 'excess_nav_series',
        'max_relative_drawdown', 'max_relative_dd_info',
        'rolling_alpha_series', 'information_ratio', 'tracking_error',
        'monthly_hit_rate', 'up_down_capture',
        'recent_failed', 'warning_level',
    ]
    for k in expected_keys:
        assert k in asd, f"missing key: {k}"
    if asd['excess_nav_series'] is not None:
        assert isinstance(asd['excess_nav_series'], pd.DataFrame)
