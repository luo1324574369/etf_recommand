"""均衡型策略诊断：2024年9月后收益下降+跑输基准归因
输出：
1. 全时段 vs 2024-09后 绩效对比（vs 沪深300）
2. 逐月收益对比表（策略 vs 基准）
3. 2024-09后每次调仓明细（卫星持仓、权重、因子排名）
4. 市场状态切换（牛市/熊市/震荡）时间轴
5. 止损触发次数与归因
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime
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

PRESETS = {
    "⚖️ 均衡型": {
        "lookback_momentum": 120, "lookback_volatility": 60, "top_n": 5,
        "rebalance_freq": 20, "sector_penalty_factor": 1.0,
        "sector_exclude_threshold": -0.15, "max_monthly_turnover": 100.0,
        "drawdown_threshold": 15.0, "max_sector_exposure_pct": 50.0,
        "market_regime_switch": True, "enable_factor_monitor": True,
    }
}

def main():
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

    params = PRESETS["⚖️ 均衡型"]
    constraints = dict(DEFAULT_BACKTEST_CONSTRAINTS)
    constraints['max_monthly_turnover'] = params['max_monthly_turnover']
    constraints['max_sector_exposure_pct'] = params['max_sector_exposure_pct']
    constraints['max_positions'] = params['top_n'] + 2  # +2 for core (510300/510500)
    code_to_sector = {item["code"]: item["sector"] for item in ETF_UNIVERSE}

    full_params = {**params, 'constraints': constraints,
                   'valuation_repo': valuation_repo,
                   'code_to_sector': code_to_sector,
                   'enable_attribution': True}

    result = multi_factor.run_backtest(
        data_dict,
        initial_capital=BACKTEST_CONFIG['initial_capital'],
        start_date=START, end_date=END,
        **full_params,
    )

    # === 1. 构造策略与基准净值 ===
    nav_df = result.get('nav_df')
    if isinstance(nav_df, pd.DataFrame) and not nav_df.empty:
        nav_df = nav_df.copy()
        nav_df.columns = [str(c).lower() for c in nav_df.columns]
        # 定位日期列与净值列
        date_col = next((c for c in nav_df.columns if 'date' in c), None)
        if date_col is None:
            nav_df = nav_df.reset_index()
            date_col = next((c for c in nav_df.columns if 'date' in c or 'index' in c), nav_df.columns[0])
        nav_df[date_col] = pd.to_datetime(nav_df[date_col])
        nav_df = nav_df.set_index(date_col).sort_index()
        # 定位净值列: nav / total / value / equity
        val_col = next((c for c in nav_df.columns if c in ('nav', 'total', 'value', 'equity', '策略净值')), None)
        if val_col is None and len(nav_df.columns) > 0:
            val_col = nav_df.columns[0]
        if val_col:
            strat_nav = nav_df[val_col].astype(float)
            strat_nav = strat_nav / strat_nav.iloc[0]
        else:
            print('[WARN] nav_df 无净值列', nav_df.columns.tolist())
            strat_nav = pd.Series(dtype=float)
    else:
        print('[WARN] nav_df 为空，检查result键:', list(result.keys())[:15])
        strat_nav = pd.Series(dtype=float)

    # 优先用回测输出的 benchmark_navs；若没有则查本地
    bench_navs = result.get('benchmark_navs') or {}
    if isinstance(bench_navs, dict) and BENCH_CODE in bench_navs:
        bnav = bench_navs[BENCH_CODE]
        if isinstance(bnav, pd.Series) and not bnav.empty:
            bnav = bnav.copy().sort_index()
            bench_nav = bnav / bnav.iloc[0]
        elif isinstance(bnav, pd.DataFrame) and not bnav.empty:
            bnav = bnav.copy()
            if 'close' in bnav.columns:
                bnav['close'] = bnav['close'].astype(float)
                bench_nav = bnav['close'] / bnav['close'].iloc[0]
            else:
                c = bnav.columns[-1]
                bench_nav = bnav[c] / bnav[c].iloc[0]
            if hasattr(bench_nav, 'index'):
                bench_nav.index = pd.to_datetime(bench_nav.index)
        else:
            bench_nav = None
    else:
        bench_nav = None

    if bench_nav is None:
        bench_df = pd.DataFrame(price_repo.get_daily_price(BENCH_CODE))
        bench_df['trade_date'] = pd.to_datetime(bench_df['trade_date'])
        bench_df = bench_df.set_index('trade_date').sort_index()
        bench_nav = bench_df['close'] / bench_df['close'].iloc[0]

    # 对齐索引
    common_idx = strat_nav.index.intersection(bench_nav.index)
    if len(common_idx) < 10:
        # 取各自完整，按日期重索引
        all_idx = strat_nav.index.union(bench_nav.index).sort_values()
        strat_nav = strat_nav.reindex(all_idx).ffill()
        bench_nav = bench_nav.reindex(all_idx).ffill()
        common_idx = all_idx
    strat_nav = strat_nav.loc[common_idx]
    bench_nav = bench_nav.loc[common_idx]

    def perf(nav_s, nav_b, label):
        start_v = nav_s.iloc[0]; end_v = nav_s.iloc[-1]
        start_b = nav_b.iloc[0]; end_b = nav_b.iloc[-1]
        years = max(0.01, (nav_s.index[-1] - nav_s.index[0]).days / 365.25)
        ret = (end_v / start_v - 1) * 100
        ann = ((end_v / start_v) ** (1 / years) - 1) * 100 if years > 0 else 0
        dd = ((nav_s / nav_s.cummax() - 1).min()) * 100
        ret_b = (end_b / start_b - 1) * 100
        ann_b = ((end_b / start_b) ** (1 / years) - 1) * 100 if years > 0 else 0
        print(f'\n=== {label} ({nav_s.index[0].date()} ~ {nav_s.index[-1].date()}) ===')
        hdr = '{:<15} {:<12} {:<12} {:<12}'.format('', '累计收益%', '年化%', '最大回撤%')
        print(hdr)
        print('-' * len(hdr))
        print('{:<15} {:<12.2f} {:<12.2f} {:<12.2f}'.format('策略', ret, ann, dd))
        dd_b = ((nav_b / nav_b.cummax() - 1).min()) * 100
        print('{:<15} {:<12.2f} {:<12.2f} {:<12.2f}'.format('沪深300', ret_b, ann_b, dd_b))
        excess = ret - ret_b
        print('{:<15} {:<12.2f} {:<12.2f}'.format('超额', excess, ann - ann_b))
        return ret, ann, dd, excess

    print('\n' + '=' * 70)
    print('PART 1: 全时段 vs 2024-09后 绩效对比')
    print('=' * 70)
    perf(strat_nav, bench_nav, '全时段')
    bp = pd.Timestamp(BREAKPOINT)
    s2 = strat_nav.loc[bp:]
    b2 = bench_nav.loc[bp:]
    if len(s2) > 5:
        perf(s2, b2, '2024-09后')

    # === 2. 逐月超额 ===
    print('\n' + '=' * 70)
    print('PART 2: 逐月收益对比（策略% / 基准% / 超额%）')
    print('=' * 70)
    m_s = strat_nav.resample('ME').last() / strat_nav.resample('ME').first() - 1
    m_b = bench_nav.resample('ME').last() / bench_nav.resample('ME').first() - 1
    m_df = pd.DataFrame({'策略%': m_s * 100, '基准%': m_b * 100})
    m_df['超额%'] = m_df['策略%'] - m_df['基准%']
    m_df.index = m_df.index.strftime('%Y-%m')
    # 高亮2024-09后
    pd.set_option('display.max_rows', 100, 'display.width', 140,
                  'display.float_format', lambda x: f'{x:6.2f}')
    print(m_df.to_string())
    pos_m = (m_df['超额%'] > 0).sum()
    print(f'\n正超额月份: {pos_m}/{len(m_df)} = {pos_m / len(m_df) * 100:.1f}%')
    after_bp = m_df.loc['2024-09':]
    pos_after = (after_bp['超额%'] > 0).sum()
    print(f'2024-09后正超额月份: {pos_after}/{len(after_bp)} = {pos_after / max(1, len(after_bp)) * 100:.1f}%')

    # === 3. 调仓明细 2024-09 之后 ===
    print('\n' + '=' * 70)
    print('PART 3: 2024-09后调仓交易记录（含trade_type与调仓原因）')
    print('=' * 70)
    trades = result.get('trade_list') or []
    if trades:
        tdf = pd.DataFrame(trades)
        tdf['date'] = pd.to_datetime(tdf['date'])
        tdf2 = tdf[tdf['date'] >= bp].copy()
        if not tdf2.empty:
            cols = ['date', 'code', 'direction', 'trade_type', 'amount', 'pnl', 'reason']
            cols_exist = [c for c in cols if c in tdf2.columns]
            print(tdf2[cols_exist].to_string(index=False))
        else:
            print('2024-09后无交易记录')
    else:
        print('trade_list 为空')

    # === 4. 市场状态切换时间轴 ===
    print('\n' + '=' * 70)
    print('PART 4: 市场状态切换（market_regime）时间轴')
    print('=' * 70)
    mr = result.get('market_regime_log') or []
    if mr:
        mrf = pd.DataFrame(mr)
        if 'date' in mrf.columns:
            mrf['date'] = pd.to_datetime(mrf['date'])
            mrf = mrf.sort_values('date')
            pd.set_option('display.max_colwidth', 60)
            print(mrf.to_string(index=False))
        else:
            print('market_regime_log 列:', mrf.columns.tolist()[:10])
    else:
        print('market_regime_log 为空（可能未记录）')

    # === 5. 止损触发统计 ===
    print('\n' + '=' * 70)
    print('PART 5: 止损触发统计')
    print('=' * 70)
    if trades:
        sl = [t for t in trades if t.get('trade_type') == 'stoploss']
        print(f'总止损次数: {len(sl)}')
        if sl:
            sldf = pd.DataFrame(sl)
            if 'date' in sldf.columns:
                sldf['date'] = pd.to_datetime(sldf['date'])
                sldf_after = sldf[sldf['date'] >= bp]
                print(f'2024-09后止损次数: {len(sldf_after)}')
                cols = ['date', 'code', 'amount', 'pnl', 'reason']
                cols_ex = [c for c in cols if c in sldf_after.columns]
                if not sldf_after.empty:
                    print(sldf_after[cols_ex].to_string(index=False))
    else:
        print('trade_list 为空')

    # === 6. 因子诊断输出 ===
    print('\n' + '=' * 70)
    print('PART 6: 因子诊断面板汇总（每因子有效性与权重）')
    print('=' * 70)
    fd = result.get('factor_diagnostics') or {}
    stats = fd.get('factor_stats') if isinstance(fd, dict) else None
    if stats is not None and len(stats) > 0:
        print(pd.DataFrame(stats).to_string(index=False))
    else:
        print('factor_stats 为空')

    # === 7. Alpha稳定性输出 ===
    print('\n' + '=' * 70)
    print('PART 7: Alpha稳定性 - 滚动窗口超额收益')
    print('=' * 70)
    asd = result.get('alpha_stability') or {}
    rw = asd.get('rolling_windows')
    if isinstance(rw, pd.DataFrame) and not rw.empty:
        print(rw.to_string(index=False))
    elif isinstance(rw, list) and len(rw) > 0:
        print(pd.DataFrame(rw).to_string(index=False))
    else:
        print('rolling_windows 为空')

    print('\n诊断完成。')


if __name__ == '__main__':
    main()
