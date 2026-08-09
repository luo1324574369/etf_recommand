#!/usr/bin/env python3
"""方案B1验证脚本: 时序动量(momentum_120d) → 横截面动量(cross_mom_120d)

输出:
  PART 1: 新旧配置 绩效对比表 + Δ(新-旧) + 判定
  PART 2: 因子诊断对比 (RankIC均值 / ICIR / used_weight_mean / 有权重调仓日%)
  PART 3: 2024-09 ~ 2024-10 weight_history + regime log debug
  PART 4: PASS / PARTIAL / FAIL 判定

注意 (与plan API的差异, 经源码核实):
  - diagnose_balanced_202409.py 没有 run_diagnosis() 函数也没有 ANALYSIS_START_202409 常量,
    只有一个 main() + 模块级常量 START/END/BREAKPOINT/PRESETS. 本脚本直接复用其
    data_dict 加载逻辑 + multi_factor.run_backtest() 调用.
  - run_backtest() 返回的 dict 没有 full_period/post_202409 子dict, 顶层只有
    total_return/excess_return/sharpe_ratio/max_drawdown/annual_return 等全时段聚合值;
    2024-09后指标需从 nav_df + benchmark_navs 自行计算.
  - factor_diagnostics 是 dict, 含 'factor_stats'(DataFrame: factor/label/rank_ic_mean/
    rank_ic_std/icir/hit_rate_12m/status/used_weight_mean/excluded_months) 和
    'weight_history'(DataFrame: date + 各因子权重列). 无 coverage_pct 字段, 需从
    weight_history 自行统计 "有权重调仓日%".
  - 关键: multi_factor._compute_scores() 动态构建 available_factors (按数据覆盖率追加),
    并不读取 scoring.DEFAULT_FACTORS. 因此仅原地修改 DEFAULT_FACTORS 两次回测会完全相同.
    为让 A/B 真正反映因子替换, 本脚本额外 monkeypatch 真正控制点:
      OLD: patch cross_sectional_momentum → 返回 {} (禁用 cross_mom_120d 注入), 保留 momentum_120d
      NEW: patch compute_all_factors → 剥离 momentum_120d, 保留 cross_mom_120d (B1 STEP 注入)
    同时仍按任务要求原地修改 DEFAULT_FACTORS (.clear()+.extend(), 保持对象身份).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy.scoring as scoring
from config.settings import ETF_UNIVERSE, DB_PATH, BACKTEST_CONFIG
from data.storage.db import get_db
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo
from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS
from strategy import multi_factor

START = '2022-01-01'
END = '2026-12-01'
BREAKPOINT = '2024-09-01'
BENCH_CODE = '510300'

PRESET = {
    "lookback_momentum": 120, "lookback_volatility": 60, "top_n": 5,
    "rebalance_freq": 20, "sector_penalty_factor": 1.0,
    "sector_exclude_threshold": -0.15, "max_monthly_turnover": 100.0,
    "drawdown_threshold": 15.0, "max_sector_exposure_pct": 50.0,
    "market_regime_switch": True, "enable_factor_monitor": True,
}

OLD_DEFAULT = ["reversal_20d", "momentum_120d", "pe_percentile", "avg_amount_20d"]
NEW_DEFAULT = list(scoring.DEFAULT_FACTORS)  # 当前: cross_mom_120d 版


# ---------------------------------------------------------------------------
# 数据加载 (两次回测共用)
# ---------------------------------------------------------------------------
def _load_data():
    price_repo = PriceRepository(get_db(str(DB_PATH)))
    valuation_repo = ValuationRepo(str(DB_PATH))
    selected_codes = [e["code"] for e in ETF_UNIVERSE]
    data_dict = {}
    for code in selected_codes:
        prices = price_repo.get_daily_price(code)
        if prices:
            df = pd.DataFrame(prices)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            data_dict[code] = df
    # 基准净值 (回测 benchmark_navs 缺失时回退用)
    bench_df = pd.DataFrame(price_repo.get_daily_price(BENCH_CODE))
    bench_df['trade_date'] = pd.to_datetime(bench_df['trade_date'])
    bench_df = bench_df.set_index('trade_date').sort_index()
    bench_nav_full = bench_df['close'].astype(float)
    bench_nav_full = bench_nav_full / bench_nav_full.iloc[0]
    return data_dict, valuation_repo, bench_nav_full


# ---------------------------------------------------------------------------
# Patch 机制
# ---------------------------------------------------------------------------
def _patch_default(factors_list):
    """原地修改 scoring.DEFAULT_FACTORS (保持对象身份). 返回还原函数."""
    _orig = list(scoring.DEFAULT_FACTORS)
    scoring.DEFAULT_FACTORS.clear()
    scoring.DEFAULT_FACTORS.extend(factors_list)

    def _restore():
        scoring.DEFAULT_FACTORS.clear()
        scoring.DEFAULT_FACTORS.extend(_orig)
    return _restore


def _patch_factor_mode(mode):
    """控制 momentum 因子的真正开关 (因为 _compute_scores 不读 DEFAULT_FACTORS).

    mode='old': 禁用 cross_mom_120d (patch cross_sectional_momentum → {}), 保留 momentum_120d
    mode='new': 禁用 momentum_120d (patch compute_all_factors → 剥离之), 保留 cross_mom_120d
    """
    restores = []
    if mode == 'old':
        _orig_csm = scoring.cross_sectional_momentum
        scoring.cross_sectional_momentum = lambda *a, **k: {}

        def _r():
            scoring.cross_sectional_momentum = _orig_csm
        restores.append(_r)
    elif mode == 'new':
        _orig_caf = scoring.compute_all_factors

        def _wrapped_caf(*args, **kwargs):
            res = _orig_caf(*args, **kwargs)
            if isinstance(res, dict):
                res.pop('momentum_120d', None)
            return res
        scoring.compute_all_factors = _wrapped_caf

        def _r():
            scoring.compute_all_factors = _orig_caf
        restores.append(_r)

    def _restore():
        for r in restores:
            r()
    return _restore


# ---------------------------------------------------------------------------
# 回测单次运行
# ---------------------------------------------------------------------------
def _run_one(label, default_factors, mode, data_dict, valuation_repo, code_to_sector):
    restore_default = _patch_default(default_factors)
    restore_mode = _patch_factor_mode(mode)
    try:
        params = dict(PRESET)
        constraints = dict(DEFAULT_BACKTEST_CONSTRAINTS)
        constraints['max_monthly_turnover'] = params['max_monthly_turnover']
        constraints['max_sector_exposure_pct'] = params['max_sector_exposure_pct']
        constraints['max_positions'] = params['top_n'] + 2
        full_params = {**params, 'constraints': constraints,
                       'valuation_repo': valuation_repo,
                       'code_to_sector': code_to_sector,
                       'enable_attribution': True}
        print("\n" + "=" * 60)
        print(f"▶ 运行配置: {label}  (mode={mode}, DEFAULT={default_factors})")
        print("=" * 60)
        result = multi_factor.run_backtest(
            data_dict,
            initial_capital=BACKTEST_CONFIG['initial_capital'],
            start_date=START, end_date=END,
            **full_params,
        )
        return result
    finally:
        restore_mode()
        restore_default()


# ---------------------------------------------------------------------------
# 净值提取 + 绩效计算 (复用 diagnose_balanced_202409 的 nav_df 解析逻辑)
# ---------------------------------------------------------------------------
def _extract_navs(result, bench_nav_full):
    nav_df = result.get('nav_df')
    if isinstance(nav_df, pd.DataFrame) and not nav_df.empty:
        nav_df = nav_df.copy()
        nav_df.columns = [str(c).lower() for c in nav_df.columns]
        date_col = next((c for c in nav_df.columns if 'date' in c), None)
        if date_col is None:
            nav_df = nav_df.reset_index()
            date_col = next((c for c in nav_df.columns if 'date' in c or 'index' in c),
                            nav_df.columns[0])
        nav_df[date_col] = pd.to_datetime(nav_df[date_col])
        nav_df = nav_df.set_index(date_col).sort_index()
        val_col = next((c for c in nav_df.columns
                        if c in ('nav', 'total', 'value', 'equity', '策略净值')), None)
        if val_col is None and len(nav_df.columns) > 0:
            val_col = nav_df.columns[0]
        if val_col:
            strat_nav = nav_df[val_col].astype(float)
            strat_nav = strat_nav / strat_nav.iloc[0]
        else:
            strat_nav = pd.Series(dtype=float)
    else:
        print('[WARN] nav_df 为空, result keys:', list(result.keys())[:15])
        strat_nav = pd.Series(dtype=float)

    bench_navs = result.get('benchmark_navs') or {}
    bench_nav = None
    if isinstance(bench_navs, dict) and BENCH_CODE in bench_navs:
        bnav = bench_navs[BENCH_CODE]
        if isinstance(bnav, pd.Series) and not bnav.empty:
            bench_nav = bnav.copy().sort_index()
            bench_nav = bench_nav / bench_nav.iloc[0]
        elif isinstance(bnav, pd.DataFrame) and not bnav.empty:
            bnav = bnav.copy()
            if 'close' in bnav.columns:
                col = bnav['close'].astype(float)
            else:
                col = bnav[bnav.columns[-1]].astype(float)
            bench_nav = col / col.iloc[0]
            bench_nav.index = pd.to_datetime(bench_nav.index)
    if bench_nav is None or len(bench_nav) == 0:
        bench_nav = bench_nav_full.copy()
        bench_nav.index = pd.to_datetime(bench_nav.index)

    common_idx = strat_nav.index.intersection(bench_nav.index)
    if len(common_idx) < 10:
        all_idx = strat_nav.index.union(bench_nav.index).sort_values()
        strat_nav = strat_nav.reindex(all_idx).ffill()
        bench_nav = bench_nav.reindex(all_idx).ffill()
        common_idx = all_idx
    return strat_nav.loc[common_idx], bench_nav.loc[common_idx]


def _perf_block(strat_nav, bench_nav):
    """返回 dict: cum_ret / ann / dd / excess / sharpe (均为 %)"""
    if len(strat_nav) < 2:
        return dict(cum_ret=0.0, ann=0.0, dd=0.0, excess=0.0, sharpe=0.0)
    sv0, sv1 = float(strat_nav.iloc[0]), float(strat_nav.iloc[-1])
    bv0, bv1 = float(bench_nav.iloc[0]), float(bench_nav.iloc[-1])
    years = max(0.01, (strat_nav.index[-1] - strat_nav.index[0]).days / 365.25)
    cum_ret = (sv1 / sv0 - 1) * 100
    ann = ((sv1 / sv0) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    dd = float((strat_nav / strat_nav.cummax() - 1).min() * 100)
    cum_ret_b = (bv1 / bv0 - 1) * 100
    excess = cum_ret - cum_ret_b
    daily_ret = strat_nav.pct_change().dropna()
    if len(daily_ret) > 5 and daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * (252 ** 0.5))
    else:
        sharpe = 0.0
    return dict(cum_ret=cum_ret, ann=ann, dd=dd, excess=excess, sharpe=sharpe)


def compute_metrics(result, bench_nav_full):
    strat_nav, bench_nav = _extract_navs(result, bench_nav_full)
    full = _perf_block(strat_nav, bench_nav)
    bp = pd.Timestamp(BREAKPOINT)
    s2 = strat_nav.loc[bp:]
    b2 = bench_nav.loc[bp:]
    post = _perf_block(s2, b2) if len(s2) > 5 else dict(cum_ret=0.0, ann=0.0, dd=0.0,
                                                        excess=0.0, sharpe=0.0)
    # 全时段夏普优先用回测引擎 (backtrader SharpeRatio analyzer) 的值
    top_sharpe = result.get('sharpe_ratio')
    if top_sharpe:
        full['sharpe'] = float(top_sharpe)
    return {'full': full, 'post': post}


# ---------------------------------------------------------------------------
# 格式化辅助
# ---------------------------------------------------------------------------
def _fnum(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return float('nan')
    return float(v)


def _fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "NaN"
    return f"{v:.2f}"


def _fmt_signed(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "NaN"
    return f"{v:+.2f}"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("方案B1 验证: momentum_120d (时序动量) → cross_mom_120d (横截面动量)")
    print("=" * 70)
    data_dict, valuation_repo, bench_nav_full = _load_data()
    code_to_sector = {item["code"]: item["sector"] for item in ETF_UNIVERSE}
    print(f"加载 ETF 数: {len(data_dict)}  基准: {BENCH_CODE}")
    print(f"OLD_DEFAULT: {OLD_DEFAULT}")
    print(f"NEW_DEFAULT: {NEW_DEFAULT}")
    print("说明: _compute_scores() 不读 DEFAULT_FACTORS, 故额外 monkeypatch")
    print("      cross_sectional_momentum(compute_all_factors) 以真正切换动量因子.")

    old_res = _run_one("旧(momentum_120d时序)", OLD_DEFAULT, 'old',
                       data_dict, valuation_repo, code_to_sector)
    old_m = compute_metrics(old_res, bench_nav_full)

    new_res = _run_one("新(cross_mom_120d横截面)", NEW_DEFAULT, 'new',
                       data_dict, valuation_repo, code_to_sector)
    new_m = compute_metrics(new_res, bench_nav_full)

    # ===== PART 1: 绩效对比 =====
    print("\n" + "=" * 70)
    print("PART 1: 新旧配置 绩效对比")
    print("=" * 70)
    headers = ["配置", "全时段累计收益%", "全时段累计超额pp", "全时段年化%",
               "全时段夏普", "全时段最大回撤%", "2024-09后累计%", "2024-09后超额pp",
               "2024-09后最大回撤%"]

    def _row(label, m):
        f, p = m['full'], m['post']
        return [label, _fmt(f['cum_ret']), _fmt(f['excess']), _fmt(f['ann']),
                _fmt(f['sharpe']), _fmt(f['dd']),
                _fmt(p['cum_ret']), _fmt(p['excess']), _fmt(p['dd'])]

    old_row = _row("旧", old_m)
    new_row = _row("新", new_m)

    # Δ(新-旧)
    diff_row = ["Δ(新-旧)"]
    for i in range(1, len(headers)):
        try:
            d = float(new_row[i]) - float(old_row[i])
            diff_row.append(_fmt_signed(d))
        except (ValueError, TypeError):
            diff_row.append("-")

    def _print_table(rows):
        widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(len(headers))]
        sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        print(sep)
        print("|" + "|".join(f" {h:<{w}} " for h, w in zip(headers, widths)) + "|")
        print(sep)
        for r in rows:
            print("|" + "|".join(f" {str(c):<{w}} " for c, w in zip(r, widths)) + "|")
        print(sep)

    _print_table([old_row, new_row, diff_row])

    # ===== PART 4 (前置判定, 便于早看结论) =====
    post_excess_old = _fnum(old_m['post']['excess'])
    post_excess_new = _fnum(new_m['post']['excess'])
    annual_old = _fnum(old_m['full']['ann'])
    annual_new = _fnum(new_m['full']['ann'])
    post_improve = post_excess_new - post_excess_old
    annual_improve = annual_new - annual_old

    print("\n" + "=" * 70)
    print("PART 4: Pass/Fail 判定")
    print("=" * 70)
    print(f"  2024-09后超额改善 (Δ新-旧): {post_improve:+.2f}pp  (PASS门槛 ≥ +3.5pp)")
    print(f"  全时段年化改善   (Δ新-旧): {annual_improve:+.2f}pp  (PASS门槛 ≥ +1.5pp)")
    pass_post = post_improve >= 3.5
    pass_ann = annual_improve >= 1.5
    if pass_post and pass_ann:
        verdict = "PASS"
    elif post_improve >= 1.0 or annual_improve >= 1.0:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    print(f"\n  >>> 判定: {verdict} <<<")
    if verdict == "PASS":
        print("  两个目标均达成, 方案B1有效.")
    elif verdict == "PARTIAL":
        print("  部分改善, 未达双目标 (改善 1.0~3.5pp 区间).")
    else:
        print("  改善 < +1.0pp 或劣化, 建议回滚 DEFAULT_FACTORS.")

    # ===== PART 2: 因子诊断对比 =====
    print("\n" + "=" * 70)
    print("PART 2: 因子诊断对比 (RankIC均值 / ICIR / used_weight_mean / 有权重调仓日%)")
    print("=" * 70)
    for name, res in [("旧配置(momentum_120d)", old_res), ("新配置(cross_mom_120d)", new_res)]:
        fd = res.get('factor_diagnostics')
        if not isinstance(fd, dict) or fd.get('factor_stats') is None:
            print(f"\n  [{name}] ℹ️ 字段缺失, 跳过此部分")
            continue
        fs = fd['factor_stats']
        wh = fd.get('weight_history')
        if not isinstance(fs, pd.DataFrame) or fs.empty:
            print(f"\n  [{name}] ℹ️ factor_stats 为空, 跳过此部分")
            continue
        # 有权重调仓日% : 从 weight_history 统计
        coverage = {}
        if isinstance(wh, pd.DataFrame) and not wh.empty and 'date' in wh.columns:
            n_dates = len(wh)
            for col in wh.columns:
                if col == 'date':
                    continue
                n_pos = int((wh[col].fillna(0) > 0).sum())
                coverage[col] = n_pos / n_dates * 100 if n_dates else 0.0
        print(f"\n  [{name}]:")
        rows2 = []
        for _, r in fs.iterrows():
            fn = r.get('factor', '')
            rows2.append([
                fn,
                _fmt(_fnum(r.get('rank_ic_mean'))),
                _fmt(_fnum(r.get('icir'))),
                _fmt(_fnum(r.get('used_weight_mean'))),
                f"{coverage.get(fn, 0.0):.1f}",
            ])
        h2 = ["因子", "RankIC均值", "ICIR", "used_weight_mean", "有权重调仓日%"]
        widths2 = [max(len(str(r[i])) for r in rows2 + [h2]) for i in range(len(h2))]
        sep2 = "+" + "+".join("-" * (w + 2) for w in widths2) + "+"
        print("  " + sep2)
        print("  |" + "|".join(f" {h:<{w}} " for h, w in zip(h2, widths2)) + "|")
        print("  " + sep2)
        for r in rows2:
            print("  |" + "|".join(f" {str(c):<{w}} " for c, w in zip(r, widths2)) + "|")
        print("  " + sep2)

    # ===== PART 3: 2024-09 weight_history + regime log =====
    print("\n" + "=" * 70)
    print("PART 3: 2024-09 ~ 2024-10 weight_history + regime log (新配置)")
    print("=" * 70)
    # regime log
    rl = new_res.get('market_regime_log') or []
    sep_snaps = []
    for x in rl:
        d = str(x.get('date', ''))
        if d.startswith("2024-09") or d.startswith("2024-10"):
            sep_snaps.append(x)
    if sep_snaps:
        print(f"\n  📅 2024-09~10 市场状态快照 ({len(sep_snaps)} 次):")
        for s in sep_snaps:
            print(f"    {s.get('date')}: regime={s.get('regime')}  "
                  f"candidate={s.get('candidate')} streak={s.get('streak')}")
    else:
        print("\n  ℹ️ 未导出 market_regime_log 或无 2024-09~10 记录, 跳过此部分")

    # weight_history
    fd_new = new_res.get('factor_diagnostics') or {}
    wh = fd_new.get('weight_history') if isinstance(fd_new, dict) else None
    if isinstance(wh, pd.DataFrame) and not wh.empty:
        wh = wh.copy()
        wh['date'] = pd.to_datetime(wh['date'])
        wh = wh.sort_values('date')
        wh_window = wh[(wh['date'] >= pd.Timestamp('2024-09-01')) &
                       (wh['date'] <= pd.Timestamp('2024-10-31'))]
        if not wh_window.empty:
            print(f"\n  📊 2024-09~10 调仓日因子权重 ({len(wh_window)} 日):")
            cols_show = ['date', 'reversal_20d', 'momentum_120d', 'cross_mom_120d',
                         'volatility_60d', 'pe_percentile', 'dividend_yield', 'avg_amount_20d']
            cols_exist = [c for c in cols_show if c in wh_window.columns]
            print(wh_window[cols_exist].to_string(index=False))
        else:
            print("\n  ℹ️ weight_history 无 2024-09~10 记录, 跳过此部分")
    else:
        print("\n  ℹ️ weight_history 未导出, 跳过此部分")

    print("\n" + "=" * 70)
    print(f"诊断完成. 判定: {verdict}")
    print("=" * 70)


if __name__ == "__main__":
    main()
