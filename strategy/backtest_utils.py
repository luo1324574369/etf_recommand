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

    # 买入持有基准（等权配置所有标的）
    benchmark_return = 0.0
    benchmark_nav_df = None
    if data_dict:
        # 构建基准净值曲线（等权买入持有）
        # 方法：计算每只ETF的日收益率，取等权平均后复利
        etf_daily_returns = {}
        for code, df in data_dict.items():
            df_copy = df.copy()
            if start_date:
                df_copy = df_copy[df_copy['trade_date'] >= start_date]
            if end_date:
                df_copy = df_copy[df_copy['trade_date'] <= end_date]
            df_copy = df_copy.sort_values('trade_date').drop_duplicates('trade_date')
            if len(df_copy) >= 2:
                df_copy['daily_return'] = df_copy['close'].pct_change()
                etf_daily_returns[code] = df_copy[['trade_date', 'daily_return']].dropna()

        if etf_daily_returns:
            # 合并所有ETF的日收益率，按日期对齐
            merged = None
            for code, df_ret in etf_daily_returns.items():
                df_ret = df_ret.rename(columns={'daily_return': code})
                if merged is None:
                    merged = df_ret
                else:
                    merged = merged.merge(df_ret, on='trade_date', how='outer')

            if merged is not None and not merged.empty:
                merged = merged.sort_values('trade_date').ffill()
                # 等权平均日收益率
                code_cols = [c for c in merged.columns if c != 'trade_date']
                merged['avg_daily_return'] = merged[code_cols].mean(axis=1)
                # 复利计算基准净值
                benchmark_nav = 1.0
                benchmark_nav_list = []
                for _, row in merged.iterrows():
                    ret = row['avg_daily_return']
                    if pd.notna(ret):
                        benchmark_nav *= (1 + ret)
                        benchmark_nav_list.append({
                            'date': pd.to_datetime(row['trade_date']),
                            'benchmark_nav': benchmark_nav,
                        })

                benchmark_nav_df = pd.DataFrame(benchmark_nav_list)
                if len(benchmark_nav_df) >= 2:
                    benchmark_return = (benchmark_nav_df.iloc[-1]['benchmark_nav'] - 1) * 100

    return {
        'final_value': cerebro.broker.getvalue(),
        'total_return': (cerebro.broker.getvalue() - initial_capital) / initial_capital * 100,
        'benchmark_return': benchmark_return,
        'excess_return': (cerebro.broker.getvalue() - initial_capital) / initial_capital * 100 - benchmark_return,
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
        'benchmark_nav_df': benchmark_nav_df,
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
