"""
回测公共工具函数
各策略直接调用，替代独立 backtest 层
"""
import backtrader as bt
import pandas as pd
from typing import Dict, Any


def _prepare_data(cerebro: bt.Cerebro, data_dict: Dict[str, pd.DataFrame],
                  start_date=None, end_date=None):
    for code, df in data_dict.items():
        df = df.copy()
        if start_date:
            df = df[df['trade_date'] >= start_date]
        if end_date:
            df = df[df['trade_date'] <= end_date]
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.sort_values('trade_date', inplace=True)
        df.drop_duplicates('trade_date', inplace=True)
        df.set_index('trade_date', inplace=True)
        # 仅保留 backtrader 需要的列，丢弃 NaN 行
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
    _prepare_data(cerebro, data_dict, start_date, end_date)

    cerebro.addstrategy(strategy_cls, **kwargs)
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

    trade_analyzer = strat.analyzers.trades.get_analysis()
    num_trades = trade_analyzer.get('total', {}).get('closed', 0) if trade_analyzer else 0
    won = trade_analyzer.get('won', {}).get('total', 0) if trade_analyzer else 0
    lost = trade_analyzer.get('lost', {}).get('total', 0) if trade_analyzer else 0
    win_rate = (won / num_trades * 100) if num_trades > 0 else 0
    avg_win = trade_analyzer.get('won', {}).get('pnl', {}).get('average', 0) if trade_analyzer else 0
    avg_lost = trade_analyzer.get('lost', {}).get('pnl', {}).get('average', 0) if trade_analyzer else 0
    profit_factor = abs(avg_win * won / (avg_lost * lost)) if avg_lost and lost else 0
    avg_hold = trade_analyzer.get('len', {}).get('average', 0) if trade_analyzer else 0
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
    dd = strat.analyzers.drawdown.get_analysis()
    drawdown = dd.get('max', {}).get('drawdown', 0) if dd else 0
    drawdown_len = dd.get('max', {}).get('len', 0) if dd else 0
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm100', 0)

    # 多基准对比
    from strategy.benchmark import build_benchmarks, DEFAULT_BENCHMARKS
    from strategy.comparator import compare

    benchmark_navs = build_benchmarks(data_dict, DEFAULT_BENCHMARKS, start_date, end_date)
    comparison = compare(nav_df, benchmark_navs)

    return {
        'final_value': cerebro.broker.getvalue(),
        'total_return': (cerebro.broker.getvalue() - initial_capital) / initial_capital * 100,
        'benchmark_return': comparison.get('benchmark_metrics', {}).get('等权持有', {}).get('total_return', 0.0),
        'excess_return': comparison.get('comparison', {}).get('等权持有', {}).get('excess_return', 0.0),
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
    }


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
    _prepare_data(cerebro, data_dict, start_date, end_date)

    cerebro.addstrategy(strategy_cls, **kwargs)
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='timereturn', timeframe=bt.TimeFrame.Days)

    results = cerebro.run(runonce=False)
    strat = results[0]

    returns = strat.analyzers.timereturn.get_analysis()
    nav = 1.0
    nav_list = []
    for date, ret in returns.items():
        nav *= (1 + ret)
        nav_list.append({'date': date, 'nav': nav})

    return pd.DataFrame(nav_list)
