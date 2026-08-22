"""
回测公共工具函数
各策略直接调用，替代独立 backtest 层
"""
import backtrader as bt
import pandas as pd
from typing import Dict, Any


class _SafeReturnsAnalyzer(bt.analyzers.Returns):
    """避免无有效收益 bar 时 Backtrader Returns 分析器除零。"""

    def stop(self):
        if getattr(self, '_tcount', 0) == 0:
            self.rets['rtot'] = 0.0
            self.rets['ravg'] = 0.0
            self.rets['rnorm'] = 0.0
            self.rets['rnorm100'] = 0.0
            return
        super().stop()


class SignalAwarePandasData(bt.feeds.PandasData):
    lines = ('signal_open', 'signal_high', 'signal_low', 'signal_close')
    params = (
        ('signal_open', -1),
        ('signal_high', -1),
        ('signal_low', -1),
        ('signal_close', -1),
    )


def _prepare_data(cerebro: bt.Cerebro, data_dict: Dict[str, pd.DataFrame],
                  start_date=None, end_date=None, lookback_long=120):
    prepared_rows = 0
    for code, df in data_dict.items():
        df = df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.sort_values('trade_date', inplace=True)
        df.drop_duplicates('trade_date', inplace=True)
        
        if end_date:
            df = df[df['trade_date'] <= pd.to_datetime(end_date)]
        if start_date:
            start_timestamp = pd.to_datetime(start_date)
            warmup = df[df['trade_date'] < start_timestamp].tail(lookback_long)
            trading = df[df['trade_date'] >= start_timestamp]
            df = pd.concat([warmup, trading], ignore_index=True)
        # 只保留 start_date 之前的有限 warm-up 数据，策略在 start_date 之后交易。
        
        df.set_index('trade_date', inplace=True)
        for raw_name, signal_name in (
            ('open', 'signal_open'),
            ('high', 'signal_high'),
            ('low', 'signal_low'),
            ('close', 'signal_close'),
        ):
            raw_values = pd.to_numeric(df[raw_name], errors='coerce')
            if 'adj_factor' in df.columns:
                factor = pd.to_numeric(df['adj_factor'], errors='coerce')
                valid_factor = factor.notna() & (factor > 0)
                calculated_signal = raw_values.where(~valid_factor, raw_values * factor)
            else:
                calculated_signal = raw_values
            if signal_name in df.columns:
                existing_signal = pd.to_numeric(df[signal_name], errors='coerce')
                df[signal_name] = existing_signal.where(existing_signal.notna(), calculated_signal)
            else:
                df[signal_name] = calculated_signal
        bt_cols = [
            'open', 'high', 'low', 'close', 'volume',
            'signal_open', 'signal_high', 'signal_low', 'signal_close',
        ]
        df = df[[c for c in bt_cols if c in df.columns]]
        df.dropna(inplace=True)
        if df.empty:
            continue
        prepared_rows += len(df)
        data = SignalAwarePandasData(dataname=df, name=code)
        cerebro.adddata(data)
    return prepared_rows


def compute_alpha_stability(nav_df, benchmark_navs, primary_benchmark='沪深300'):
    """计算全套 Alpha 稳定性指标。"""
    # ===== 输入校验 & 初始化 =====
    empty = {
        'rolling_windows': None, 'excess_nav_series': None,
        'max_relative_drawdown': None, 'max_relative_dd_info': None,
        'rolling_alpha_series': None, 'information_ratio': None,
        'tracking_error': None, 'monthly_hit_rate': None,
        'up_down_capture': None, 'recent_failed': False, 'warning_level': None,
    }
    if nav_df is None or nav_df.empty:
        return empty
    bench_df = benchmark_navs.get(primary_benchmark)
    if bench_df is None or bench_df.empty:
        return empty

    nav_df = nav_df.copy()
    bench_df = bench_df.copy()
    nav_df['date'] = pd.to_datetime(nav_df['date'])
    bench_df['date'] = pd.to_datetime(bench_df['date'])

    # ===== 1. 对齐日期 =====
    merged = nav_df[['date', 'nav']].merge(
        bench_df[['date', 'nav']], on='date', suffixes=('_s', '_b')
    ).sort_values('date').reset_index(drop=True)
    if len(merged) < 2:
        return empty

    n = len(merged)

    # ===== 3. 滚动窗口收益表（1月/3月/6月/1年/成立以来） =====
    # 窗口大小映射（交易日天数）
    WIN_MAP = [
        ('1月',  21),
        ('3月',  63),
        ('6月',  126),
        ('1年',  252),
        ('成立以来', n),
    ]
    rows = []
    for window_name, w_size in WIN_MAP:
        sufficient = (w_size <= n)
        take_size = min(w_size, n)
        sub = merged.tail(take_size)
        if window_name == '成立以来':
            s_ret = (sub.iloc[-1]['nav_s'] / 1.0 - 1) * 100
            b_ret = (sub.iloc[-1]['nav_b'] / 1.0 - 1) * 100
        else:
            s_ret = (sub.iloc[-1]['nav_s'] / sub.iloc[0]['nav_s'] - 1) * 100
            b_ret = (sub.iloc[-1]['nav_b'] / sub.iloc[0]['nav_b'] - 1) * 100
        e_ret = s_ret - b_ret
        rows.append({
            'window': window_name,
            'strategy_pct': round(s_ret, 4),
            'benchmark_pct': round(b_ret, 4),
            'excess_pct': round(e_ret, 4),
            'sufficient_data': sufficient,
        })
    rolling_windows = pd.DataFrame(rows, columns=['window', 'strategy_pct', 'benchmark_pct', 'excess_pct', 'sufficient_data'])

    # ===== 2. 累计超额净值 + 最大相对回撤 =====
    merged['excess_nav'] = merged['nav_s'] / merged['nav_b']
    excess_nav_series = merged[['date', 'excess_nav']].copy()

    merged['excess_peak'] = merged['excess_nav'].cummax()
    merged['rel_dd'] = (merged['excess_nav'] / merged['excess_peak'] - 1) * 100
    max_relative_drawdown = float(merged['rel_dd'].min())

    # 回撤区间信息
    if max_relative_drawdown < 0:
        end_idx = int(merged['rel_dd'].idxmin())
        peak_val = merged.loc[end_idx, 'excess_peak']
        # 找这个 peak 值首次出现位置（之前最大区间起点）
        peak_idx = int(merged.loc[:end_idx, 'excess_nav'].idxmax())
        # 起点（回撤开始前的峰值点前一天，若存在则取峰值当天）
        start_idx = max(0, peak_idx)
        max_relative_dd_info = {
            'date_start': merged.loc[start_idx, 'date'].strftime('%Y-%m-%d'),
            'date_peak':  merged.loc[peak_idx, 'date'].strftime('%Y-%m-%d'),
            'date_end':   merged.loc[end_idx, 'date'].strftime('%Y-%m-%d'),
            'drawdown_pct': round(max_relative_drawdown, 4),
        }
    else:
        max_relative_dd_info = None

    import numpy as np

    # ===== 4. 滚动 Alpha 三窗口 =====
    ra_dates = merged['date'].copy()
    ra_df = pd.DataFrame({'date': ra_dates})
    for days, col in [(63, 'excess_63d'), (126, 'excess_126d'), (252, 'excess_252d')]:
        if n >= days:
            s_roll = merged['nav_s'].pct_change(days)
            b_roll = merged['nav_b'].pct_change(days)
            ra_df[col] = (s_roll - b_roll) * 100
        else:
            ra_df[col] = np.nan
    rolling_alpha_series = ra_df[['date', 'excess_63d', 'excess_126d', 'excess_252d']]

    # ===== 5. 跟踪误差 & IR =====
    s_daily = merged['nav_s'].pct_change().dropna().values
    b_daily = merged['nav_b'].pct_change().dropna().values
    if len(s_daily) >= 2 and len(b_daily) >= 2:
        diff = s_daily - b_daily
        te_daily = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
        tracking_error = float(te_daily * np.sqrt(252) * 100)
        # 年化收益（复利）
        ann_s = (merged.iloc[-1]['nav_s'] / merged.iloc[0]['nav_s']) ** (252 / max(1, n-1)) - 1
        ann_b = (merged.iloc[-1]['nav_b'] / merged.iloc[0]['nav_b']) ** (252 / max(1, n-1)) - 1
        annual_excess = (ann_s - ann_b) * 100  # %
        information_ratio = float(annual_excess / tracking_error) if tracking_error > 0.00001 else None
    else:
        tracking_error = None
        information_ratio = None

    # ===== 6. 月度命中率 =====
    mdf = merged.copy()
    mdf['ym'] = mdf['date'].dt.to_period('M')
    monthly = []
    for ym, g in mdf.groupby('ym'):
        if len(g) < 2:
            continue
        s_m = (g.iloc[-1]['nav_s'] / g.iloc[0]['nav_s'] - 1) * 100
        b_m = (g.iloc[-1]['nav_b'] / g.iloc[0]['nav_b'] - 1) * 100
        monthly.append({'ym': str(ym), 's_ret': s_m, 'b_ret': b_m, 'excess': s_m - b_m})
    if monthly:
        m_df = pd.DataFrame(monthly)
        hits = int((m_df['excess'] > 0).sum())
        monthly_hit_rate = round(hits / len(m_df) * 100, 4)
        # Up/Down Capture: 按基准月收益正负分开月份
        up_months = m_df[m_df['b_ret'] > 0]
        down_months = m_df[m_df['b_ret'] < 0]
        up_capture = None
        down_capture = None
        if len(up_months) > 0 and up_months['b_ret'].mean() != 0:
            up_capture = round(float(up_months['s_ret'].mean() / up_months['b_ret'].mean() * 100), 4)
        if len(down_months) > 0 and down_months['b_ret'].mean() != 0:
            down_capture = round(float(down_months['s_ret'].mean() / down_months['b_ret'].mean() * 100), 4)
        up_down_capture = {
            'up_capture_pct': up_capture,
            'down_capture_pct': down_capture,
            'up_months_count': len(up_months),
            'down_months_count': len(down_months),
        }
    else:
        monthly_hit_rate = None
        up_down_capture = None

    # ===== 7. 近1年/半年超额判断 + warning_level =====
    excess_1y_val = None
    excess_half_val = None
    if rolling_windows is not None and not rolling_windows.empty:
        row_1y = rolling_windows[rolling_windows['window'] == '1年']
        if not row_1y.empty:
            excess_1y_val = float(row_1y.iloc[0]['excess_pct'])
        row_h = rolling_windows[rolling_windows['window'] == '6月']
        if not row_h.empty:
            excess_half_val = float(row_h.iloc[0]['excess_pct'])

    cumulative_excess_val = None
    if rolling_windows is not None and not rolling_windows.empty:
        row_full = rolling_windows[rolling_windows['window'] == '成立以来']
        if not row_full.empty:
            cumulative_excess_val = float(row_full.iloc[0]['excess_pct'])

    recent_failed = (excess_1y_val is not None and excess_1y_val < 0)
    if cumulative_excess_val is not None and cumulative_excess_val > 0:
        if excess_1y_val is not None and excess_1y_val < 0:
            if excess_half_val is not None and excess_half_val < 0:
                warning_level = 'severe'
            else:
                warning_level = 'mild'
        else:
            warning_level = None
    else:
        warning_level = None

    return {
        # 必选层
        'rolling_windows': rolling_windows,
        'excess_nav_series': excess_nav_series,
        'max_relative_drawdown': max_relative_drawdown,
        'max_relative_dd_info': max_relative_dd_info,
        # 强推荐层
        'rolling_alpha_series': rolling_alpha_series,
        'information_ratio': information_ratio,
        'tracking_error': tracking_error,
        'monthly_hit_rate': monthly_hit_rate,
        'up_down_capture': up_down_capture,
        # 诊断辅助
        'recent_failed': recent_failed,
        'warning_level': warning_level,
    }


def run_backtest(
    strategy_cls,
    data_dict: Dict[str, pd.DataFrame],
    initial_capital: float = 1000000,
    commission_rate: float = 0.0003,
    start_date=None,
    end_date=None,
    **kwargs
) -> Dict[str, Any]:
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_capital)
    cerebro.broker.setcommission(commission=commission_rate)
    prepared_rows = _prepare_data(cerebro, data_dict, start_date, end_date, kwargs.get('lookback_long', 120))
    if prepared_rows == 0:
        raise ValueError("回测区间没有可用行情数据，请检查日期范围、行情字段和数据源")
    if start_date:
        start_timestamp = pd.to_datetime(start_date)
        has_trading_rows = any(
            (pd.to_datetime(data.p.dataname.index) >= start_timestamp).any()
            for data in cerebro.datas
        )
        if not has_trading_rows:
            raise ValueError("回测区间没有交易日行情，请检查日期范围和数据源")

    # 将start_date转为date对象传给策略
    start_dt = pd.to_datetime(start_date).date() if start_date else None
    strategy_kwargs = {
        k: v for k, v in kwargs.items()
        if k not in {'enable_attribution', 'attribution_benchmark_type', 'csi300_source'}
    }
    strategy_kwargs['start_date'] = start_dt
    cerebro.addstrategy(strategy_cls, **strategy_kwargs)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(_SafeReturnsAnalyzer, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn', timeframe=bt.TimeFrame.Days)

    results = cerebro.run(runonce=False)
    strat = results[0]

    trade_list = getattr(strat, 'trade_log', [])

    returns = strat.analyzers.timereturn.get_analysis()
    nav = 1.0
    nav_list = []
    for date, ret in returns.items():
        nav *= (1 + ret)
        nav_list.append({'date': date, 'nav': nav})
    nav_df = pd.DataFrame(nav_list)

    # 只保留start_date之后的数据，净值从1.0重新计算
    if start_date and not nav_df.empty:
        nav_df['date'] = pd.to_datetime(nav_df['date'])
        start_dt = pd.to_datetime(start_date)
        nav_df = nav_df[nav_df['date'] >= start_dt].copy()
        if not nav_df.empty:
            first_nav = nav_df.iloc[0]['nav']
            if first_nav > 0:
                nav_df['nav'] = nav_df['nav'] / first_nav

    from strategy.performance import calc_metrics, calc_drawdown_series
    performance_metrics = calc_metrics(nav_df)

    # 交易指标从 trade_list 派生（单一数据源，与交易明细天然一致）
    days = 0
    if start_date and end_date:
        try:
            days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
        except Exception:
            days = 0
    years = days / 365.25 if days > 0 else 1

    trade_metrics = _compute_trade_metrics_from_log(
        trade_list, initial_capital=initial_capital, years=years
    )
    num_trades = trade_metrics['num_trades']
    win_rate = trade_metrics['win_rate']
    avg_win = trade_metrics['avg_win']
    avg_lost = trade_metrics['avg_lost']
    closed_trade_count = trade_metrics['closed_trade_count']
    profit_factor = trade_metrics['profit_factor']
    avg_hold = trade_metrics['avg_hold_days']
    dd = strat.analyzers.drawdown.get_analysis()
    drawdown = performance_metrics['max_drawdown']
    formal_drawdowns = calc_drawdown_series(nav_df)
    drawdown_len = 0
    current_drawdown_len = 0
    for value in formal_drawdowns.get('drawdown', []):
        if value < 0:
            current_drawdown_len += 1
            drawdown_len = max(drawdown_len, current_drawdown_len)
        else:
            current_drawdown_len = 0
    sharpe = performance_metrics['sharpe_ratio']
    annual_return = performance_metrics['annual_return']

    # 多基准对比
    from strategy.benchmark import build_benchmarks, DEFAULT_BENCHMARKS, PRIMARY_BENCHMARK
    from strategy.comparator import compare

    benchmark_navs = build_benchmarks(data_dict, DEFAULT_BENCHMARKS, start_date, end_date)
    comparison = compare(nav_df, benchmark_navs)

    # 换手率从 trade_list 派生（与交易明细一致）
    turnover_total = trade_metrics['turnover_total_pct']
    turnover_annual = trade_metrics['turnover_annual_pct']
    turnover_series = trade_metrics['turnover_series']
    constraint_config = kwargs.get('constraints') or {}
    slippage_rate_pct = float(constraint_config.get('slippage_rate', 0.0) or 0.0)
    annual_cost_pct = turnover_annual * (commission_rate * 100.0 + slippage_rate_pct) / 100.0

    # 归因（可选，默认关闭；失败不影响回测主体）
    attribution_result = None
    attribution_error = None
    attribution_status = 'not_requested'
    if kwargs.get('enable_attribution', False):
        import logging
        logger = logging.getLogger(__name__)
        try:
            from strategy.attribution import run_attribution
            from config.settings import ETF_UNIVERSE

            benchmark_type = kwargs.get('attribution_benchmark_type', 'csi300')
            csi300_source = kwargs.get('csi300_source')
            if benchmark_type == 'csi300' and csi300_source is None:
                from data.sources.csi300_source import CSI300Source
                csi300_source = CSI300Source()

            etf_codes = list(data_dict.keys())
            etf_to_sector = _build_etf_to_sector_map(ETF_UNIVERSE)
            valuation_repo = _DataDictValuationRepo(data_dict)

            attribution_result = run_attribution(
                trade_log=trade_list,
                strategy_nav=nav_df,
                etf_codes=etf_codes,
                valuation_repo=valuation_repo,
                etf_to_sector=etf_to_sector,
                start_date=start_date,
                end_date=end_date,
                rebalance_dates=_extract_rebalance_dates(trade_list),
                benchmark_type=benchmark_type,
                csi300_source=csi300_source,
                benchmark_etf_codes=['510300'] if '510300' in data_dict else [],
            )
            attribution_status = 'available'
        except Exception as e:
            attribution_error = str(e)
            attribution_status = 'unavailable'
            logger.warning(f"归因计算失败: {e}")

    # ===== Alpha 稳定性分析 =====
    alpha_stability = compute_alpha_stability(
        nav_df=nav_df,
        benchmark_navs=benchmark_navs,
        primary_benchmark=PRIMARY_BENCHMARK,
    )

    # ===== 因子诊断（ICIR加权）=====
    factor_diagnostics = None
    if hasattr(strat, 'build_factor_diagnostics'):
        try:
            factor_diagnostics = strat.build_factor_diagnostics()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"build_factor_diagnostics failed: {e}")
            factor_diagnostics = None
    elif hasattr(strat, 'factor_diagnostics') and strat.factor_diagnostics:
        factor_diagnostics = strat.factor_diagnostics

    factor_health = []
    if factor_diagnostics is not None:
        try:
            from strategy.factor_lifecycle import health_reports_from_factor_stats
            factor_health = health_reports_from_factor_stats(factor_diagnostics.get('factor_stats'))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"factor health build failed: {e}")

    return {
        'final_value': cerebro.broker.getvalue(),
        'total_return': (cerebro.broker.getvalue() - initial_capital) / initial_capital * 100,
        'benchmark_return': comparison.get('benchmark_metrics', {}).get(PRIMARY_BENCHMARK, {}).get('total_return', 0.0),
        'excess_return': comparison.get('comparison', {}).get(PRIMARY_BENCHMARK, {}).get('excess_return', 0.0),
        'sharpe_ratio': sharpe,
        'max_drawdown': drawdown,
        'max_drawdown_days': drawdown_len,
        'annual_return': annual_return,
        'num_trades': num_trades,
        'closed_trade_count': closed_trade_count,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_lost': avg_lost,
        'avg_hold_days': avg_hold,
        'trade_list': trade_list,
        'nav_df': nav_df,
        'comparison': comparison,
        'benchmark_navs': benchmark_navs,
        'turnover_total_pct': float(turnover_total),
        'turnover_annual_pct': float(turnover_annual),
        'annual_cost_pct': float(annual_cost_pct),
        'turnover_series': turnover_series,
        'attribution': attribution_result,
        'attribution_error': attribution_error,
        'attribution_status': attribution_status,
        'alpha_stability': alpha_stability,
        'factor_diagnostics': factor_diagnostics,
        'factor_health': factor_health,
        'market_regime_log': getattr(strat, '_regime_log', []),
    }


def _build_etf_to_sector_map(etf_universe):
    """构造 ETF code → 赛道名（直接用 sector 字段）"""
    mapping = {}
    for etf in etf_universe:
        mapping[etf['code']] = etf.get('sector', '未归类')
    return mapping


class _DataDictValuationRepo:
    """将 data_dict 包装为估值数据源接口"""

    def __init__(self, data_dict):
        self._data = {}
        for code, df in data_dict.items():
            price_df = df.copy()
            if 'trade_date' not in price_df.columns:
                price_df = price_df.reset_index()
                price_df = price_df.rename(columns={price_df.columns[0]: 'trade_date'})
            price_df['trade_date'] = pd.to_datetime(price_df['trade_date']).dt.strftime('%Y-%m-%d')
            self._data[code] = price_df

    def get_daily_price(self, code):
        if code not in self._data:
            return []
        return self._data[code].to_dict('records')


def _extract_rebalance_dates(trade_log):
    """从交易日志提取调仓日（去重、升序）"""
    if not trade_log:
        return []
    return sorted(set(t['date'] for t in trade_log))


def get_nav_curve(
    strategy_cls,
    data_dict: Dict[str, pd.DataFrame],
    initial_capital: float = 1000000,
    commission_rate: float = 0.0003,
    start_date=None,
    end_date=None,
    **kwargs
) -> pd.DataFrame:
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(initial_capital)
    cerebro.broker.setcommission(commission=commission_rate)
    prepared_rows = _prepare_data(cerebro, data_dict, start_date, end_date, kwargs.get('lookback_long', 120))
    if prepared_rows == 0:
        return pd.DataFrame(columns=['date', 'nav'])

    start_dt = pd.to_datetime(start_date).date() if start_date else None
    strategy_kwargs = {k: v for k, v in kwargs.items() if k != 'enable_attribution'}
    strategy_kwargs['start_date'] = start_dt
    cerebro.addstrategy(strategy_cls, **strategy_kwargs)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn', timeframe=bt.TimeFrame.Days)

    results = cerebro.run(runonce=False)
    strat = results[0]

    returns = strat.analyzers.timereturn.get_analysis()
    nav = 1.0
    nav_list = []
    for date, ret in returns.items():
        nav *= (1 + ret)
        nav_list.append({'date': date, 'nav': nav})
    nav_df = pd.DataFrame(nav_list)

    # 只保留start_date之后的数据，净值从1.0重新计算
    if start_date and not nav_df.empty:
        nav_df['date'] = pd.to_datetime(nav_df['date'])
        start_dt = pd.to_datetime(start_date)
        nav_df = nav_df[nav_df['date'] >= start_dt].copy()
        if not nav_df.empty:
            first_nav = nav_df.iloc[0]['nav']
            if first_nav > 0:
                nav_df['nav'] = nav_df['nav'] / first_nav

    return nav_df


def _compute_trade_metrics_from_log(trade_list, initial_capital, years):
    """从交易日志派生所有交易相关指标（单一数据源）

    Args:
        trade_list: 策略的 trade_log
        initial_capital: 初始资金
        years: 回测年数

    Returns:
        dict: num_trades, win_rate, profit_factor, avg_win, avg_lost,
              avg_hold_days, turnover_total_pct, turnover_annual_pct, turnover_series
    """
    num_trades = len(trade_list)

    closed_trades = _build_closed_trades_from_fills(trade_list)
    win_sells = [t for t in closed_trades if t['pnl'] > 0]
    loss_sells = [t for t in closed_trades if t['pnl'] < 0]

    win_rate = len(win_sells) / len(closed_trades) * 100 if closed_trades else 0
    avg_win = sum(t['pnl'] for t in win_sells) / len(win_sells) if win_sells else 0
    avg_lost = abs(sum(t['pnl'] for t in loss_sells) / len(loss_sells)) if loss_sells else 0
    total_win_pnl = sum(t['pnl'] for t in win_sells)
    total_loss_pnl = abs(sum(t['pnl'] for t in loss_sells))
    profit_factor = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else 0

    avg_hold_days = (
        sum(t['hold_days'] for t in closed_trades) / len(closed_trades)
        if closed_trades else 0
    )

    # 换手率：仅统计非核心建仓的买入
    buy_records = [
        t for t in trade_list
        if t.get('direction') == '买入' and t.get('trade_type') != 'core'
    ]
    total_buys = sum(t.get('amount', 0) for t in buy_records)
    turnover_total_pct = total_buys / initial_capital * 100 if initial_capital > 0 else 0
    turnover_annual_pct = total_buys / initial_capital / years * 100 if years > 0 and initial_capital > 0 else 0

    # 换手率序列：按调仓日分组
    if buy_records:
        turnover_df = pd.DataFrame(buy_records)
        if 'total_value' in turnover_df.columns:
            turnover_series = turnover_df.groupby('date').agg({
                'amount': 'sum',
                'total_value': 'first'
            }).reset_index()
            turnover_series.columns = ['date', 'buy_amount', 'total_value']
            turnover_series['turnover_pct'] = (
                turnover_series['buy_amount'] / turnover_series['total_value'].replace(0, float('nan')) * 100
            ).fillna(0)
        else:
            turnover_series = turnover_df.groupby('date')['amount'].sum().reset_index()
            turnover_series.columns = ['date', 'buy_amount']
    else:
        turnover_series = pd.DataFrame()

    return {
        'num_trades': num_trades,
        'closed_trade_count': len(closed_trades),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_lost': avg_lost,
        'avg_hold_days': avg_hold_days,
        'turnover_total_pct': float(turnover_total_pct),
        'turnover_annual_pct': float(turnover_annual_pct),
        'turnover_series': turnover_series,
    }


def _build_closed_trades_from_fills(fill_log):
    """按FIFO将成交回报配对为已闭合交易。"""
    from collections import defaultdict, deque
    from datetime import datetime

    buy_queues = defaultdict(deque)
    closed_trades = []
    for fill in fill_log:
        code = fill.get('code')
        quantity = int(fill.get('quantity', 0) or 0)
        if quantity <= 0:
            continue
        try:
            fill_date = datetime.strptime(fill.get('date'), '%Y-%m-%d').date()
        except (TypeError, ValueError):
            continue

        fee_per_share = float(fill.get('fee', 0) or 0) / quantity
        if fill.get('direction') == '买入':
            buy_queues[code].append({
                'date': fill_date,
                'shares': quantity,
                'price': float(fill.get('price', 0) or 0),
                'fee_per_share': fee_per_share,
            })
            continue
        if fill.get('direction') != '卖出':
            continue

        remaining = quantity
        sell_price = float(fill.get('price', 0) or 0)
        while remaining > 0 and buy_queues[code]:
            buy = buy_queues[code][0]
            matched = min(remaining, buy['shares'])
            reported_pnl = fill.get('pnl')
            if reported_pnl is not None:
                pnl = float(reported_pnl) * matched / quantity
            else:
                pnl = (sell_price - buy['price']) * matched
            closed_trades.append({
                'code': code,
                'pnl': pnl,
                'hold_days': (fill_date - buy['date']).days,
            })
            remaining -= matched
            buy['shares'] -= matched
            if buy['shares'] == 0:
                buy_queues[code].popleft()

    return closed_trades


def _compute_avg_hold_days_from_log(trade_list):
    """按FIFO配对计算平均持仓天数

    对每个code维护买入队列，遇到卖出时按FIFO消耗队列并累加持仓天数

    Args:
        trade_list: 交易日志

    Returns:
        float: 平均持仓天数，无配对时返回0
    """
    from collections import defaultdict, deque
    from datetime import datetime

    buy_queues = defaultdict(deque)  # {code: deque([(date, shares), ...])}
    hold_days_list = []

    for t in trade_list:
        code = t.get('code')
        direction = t.get('direction')
        date_str = t.get('date')
        shares = t.get('quantity', 0)

        try:
            trade_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue

        if direction == '买入':
            buy_queues[code].append((trade_date, shares))
        elif direction == '卖出':
            remaining = shares
            while remaining > 0 and buy_queues[code]:
                buy_date, buy_shares = buy_queues[code][0]
                matched = min(remaining, buy_shares)
                hold_days = (trade_date - buy_date).days
                hold_days_list.append(hold_days)
                remaining -= matched
                buy_shares -= matched
                if buy_shares == 0:
                    buy_queues[code].popleft()
                else:
                    buy_queues[code][0] = (buy_date, buy_shares)

    return sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0
