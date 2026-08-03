"""
回测公共工具函数
各策略直接调用，替代独立 backtest 层
"""
import backtrader as bt
import pandas as pd
from typing import Dict, Any


def _prepare_data(cerebro: bt.Cerebro, data_dict: Dict[str, pd.DataFrame],
                  start_date=None, end_date=None, lookback_long=120):
    for code, df in data_dict.items():
        df = df.copy()
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.sort_values('trade_date', inplace=True)
        df.drop_duplicates('trade_date', inplace=True)
        
        if end_date:
            df = df[df['trade_date'] <= end_date]
        # 保留 start_date 之前 lookback_long 天的数据作为预热期
        # 策略在 start_date 之后才开始交易
        
        df.set_index('trade_date', inplace=True)
        bt_cols = ['open', 'high', 'low', 'close', 'volume']
        df = df[[c for c in bt_cols if c in df.columns]]
        df.dropna(inplace=True)
        data = bt.feeds.PandasData(dataname=df, name=code)
        cerebro.adddata(data)


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
    _prepare_data(cerebro, data_dict, start_date, end_date, kwargs.get('lookback_long', 120))

    # 将start_date转为date对象传给策略
    start_dt = pd.to_datetime(start_date).date() if start_date else None
    strategy_kwargs = {k: v for k, v in kwargs.items() if k != 'enable_attribution'}
    strategy_kwargs['start_date'] = start_dt
    cerebro.addstrategy(strategy_cls, **strategy_kwargs)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
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
    profit_factor = trade_metrics['profit_factor']
    avg_hold = trade_metrics['avg_hold_days']
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
    dd = strat.analyzers.drawdown.get_analysis()
    drawdown = dd.get('max', {}).get('drawdown', 0) if dd else 0
    drawdown_len = dd.get('max', {}).get('len', 0) if dd else 0
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm100', 0)

    # 多基准对比
    from strategy.benchmark import build_benchmarks, DEFAULT_BENCHMARKS, PRIMARY_BENCHMARK
    from strategy.comparator import compare

    benchmark_navs = build_benchmarks(data_dict, DEFAULT_BENCHMARKS, start_date, end_date)
    comparison = compare(nav_df, benchmark_navs)

    # 换手率从 trade_list 派生（与交易明细一致）
    turnover_total = trade_metrics['turnover_total_pct']
    turnover_annual = trade_metrics['turnover_annual_pct']
    turnover_series = trade_metrics['turnover_series']

    # 归因（可选，默认关闭；失败不影响回测主体）
    attribution_result = None
    attribution_error = None
    if kwargs.get('enable_attribution', False):
        import logging
        logger = logging.getLogger(__name__)
        try:
            from strategy.attribution import run_attribution
            from config.settings import ETF_UNIVERSE

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
                benchmark_type='equal_weight',
            )
        except Exception as e:
            attribution_error = str(e)
            logger.warning(f"归因计算失败: {e}")

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
        'turnover_series': turnover_series,
        'attribution': attribution_result,
        'attribution_error': attribution_error,
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
    _prepare_data(cerebro, data_dict, start_date, end_date, kwargs.get('lookback_long', 120))

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

    sell_records = [t for t in trade_list if t.get('direction') == '卖出']
    win_sells = [t for t in sell_records if t.get('pnl', 0) > 0]
    loss_sells = [t for t in sell_records if t.get('pnl', 0) < 0]

    win_rate = len(win_sells) / len(sell_records) * 100 if sell_records else 0
    avg_win = sum(t['pnl'] for t in win_sells) / len(win_sells) if win_sells else 0
    avg_lost = abs(sum(t['pnl'] for t in loss_sells) / len(loss_sells)) if loss_sells else 0
    total_win_pnl = sum(t['pnl'] for t in win_sells)
    total_loss_pnl = abs(sum(t['pnl'] for t in loss_sells))
    profit_factor = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else 0

    avg_hold_days = _compute_avg_hold_days_from_log(trade_list)

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
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_lost': avg_lost,
        'avg_hold_days': avg_hold_days,
        'turnover_total_pct': float(turnover_total_pct),
        'turnover_annual_pct': float(turnover_annual_pct),
        'turnover_series': turnover_series,
    }


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
