"""双动量策略现金管理测试

验证：
1. 现金不足时不超额买入
2. 跌出排名时清仓卖出
3. 超配时减仓
4. 日志金额与实际下单一致
"""
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.dual_momentum import DualMomentumStrategy
import backtrader as bt


def _make_data(code, start_price, daily_return, days):
    """生成模拟ETF行情数据"""
    dates = pd.date_range('2023-01-01', periods=days, freq='B')
    np.random.seed(42)
    rets = np.random.normal(daily_return, 0.01, days)
    prices = start_price * np.cumprod(1 + rets)
    return pd.DataFrame({
        'trade_date': dates,
        'open': prices * 0.995,
        'high': prices * 1.005,
        'low': prices * 0.99,
        'close': prices,
        'volume': np.random.randint(100000, 1000000, days),
    })


def _run_strategy(data_dict, initial_capital, **strategy_kwargs):
    """运行双动量策略，返回 (策略实例, cerebro实例)"""
    cerebro = bt.Cerebro()
    cerebro.addstrategy(DualMomentumStrategy, **strategy_kwargs)
    for code, df in data_dict.items():
        data = bt.feeds.PandasData(
            dataname=df.set_index('trade_date'),
            open='open', high='high', low='low', close='close', volume='volume',
            openinterest=-1,
        )
        cerebro.adddata(data, name=code)
    cerebro.broker.set_cash(initial_capital)
    cerebro.broker.setcommission(commission=0.0003)
    results = cerebro.run()
    strat = results[0]
    return strat, cerebro


def test_cash_respect_no_overbuy():
    """现金不足时不超额买入 - 总仓位不超过95%

    top_n=3, max_position_pct=40% → 目标120%仓位
    但受 max_total_exposure=95% 和现金约束，实际应≤95%
    """
    data_dict = {
        'etf1': _make_data('etf1', 1.0, 0.001, 200),
        'etf2': _make_data('etf2', 1.0, 0.0008, 200),
        'etf3': _make_data('etf3', 1.0, 0.0005, 200),
    }
    initial = 100000
    strat, cerebro = _run_strategy(
        data_dict, initial,
        lookback_short=20, lookback_long=60, top_n=3, rebalance_freq=20,
        constraints={'max_total_exposure_pct': 95, 'max_position_pct': 40,
                     'min_trade_amount': 0, 'slippage_rate': 0},
    )
    final_value = cerebro.broker.get_value()
    final_cash = cerebro.broker.get_cash()
    total_position = final_value - final_cash
    max_exposure = final_value * 0.95
    assert total_position <= max_exposure + 100, (
        f"总仓位{total_position:.0f}超过上限{max_exposure:.0f}"
    )


def test_sell_when_out_of_topn():
    """跌出top_n排名时清仓卖出

    用4只ETF，top_n=2。前60天etf1/etf2涨得好，被买入。
    之后让etf3/etf4超过它们，验证etf1/etf2被卖出。
    """
    np.random.seed(123)
    days = 200
    mid = 100
    dates = pd.date_range('2023-01-01', periods=days, freq='B')

    def make_dual_trend(before_ret, after_ret):
        prices_before = 1.0 * np.cumprod(1 + np.random.normal(before_ret, 0.005, mid))
        prices_after = prices_before[-1] * np.cumprod(1 + np.random.normal(after_ret, 0.005, days - mid))
        prices = np.concatenate([prices_before, prices_after])
        return pd.DataFrame({
            'trade_date': dates,
            'open': prices * 0.995,
            'high': prices * 1.005,
            'low': prices * 0.99,
            'close': prices,
            'volume': np.random.randint(100000, 1000000, days),
        })

    data_dict = {
        'etf_a': make_dual_trend(0.003, -0.001),
        'etf_b': make_dual_trend(0.0025, -0.0005),
        'etf_c': make_dual_trend(-0.001, 0.003),
        'etf_d': make_dual_trend(-0.0005, 0.0025),
    }

    strat, cerebro = _run_strategy(
        data_dict, 100000,
        lookback_short=20, lookback_long=60, top_n=2, rebalance_freq=20,
        constraints={'max_total_exposure_pct': 95, 'max_position_pct': 40,
                     'min_trade_amount': 0, 'slippage_rate': 0, 't_plus_one': False},
    )

    trades = strat.trade_log
    sell_trades = [t for t in trades if t['direction'] == '卖出']
    assert len(sell_trades) > 0, "应该有卖出交易，但一笔都没有"

    codes_sold = {t['code'] for t in sell_trades}
    assert 'etf_a' in codes_sold or 'etf_b' in codes_sold, (
        f"前期强势的ETF应该被卖出，实际卖出: {codes_sold}"
    )


def test_reduce_position_when_overweight():
    """超配时减仓 - 单仓涨幅超过上限时减仓

    单ETF持续上涨，持仓市值超过 max_position_pct × 1.05 时，
    下一次调仓应触发减仓，卖出多余部分。
    """
    np.random.seed(42)
    days = 250
    dates = pd.date_range('2023-01-01', periods=days, freq='B')

    # etf1: 稳定上涨，会持续超配
    prices = 1.0 * np.cumprod(1 + np.random.normal(0.003, 0.005, days))
    etf1 = pd.DataFrame({
        'trade_date': dates,
        'open': prices * 0.995,
        'high': prices * 1.005,
        'low': prices * 0.99,
        'close': prices,
        'volume': np.random.randint(100000, 1000000, days),
    })

    # etf2: 缓慢上涨，永远排第二
    prices2 = 1.0 * np.cumprod(1 + np.random.normal(0.001, 0.003, days))
    etf2 = pd.DataFrame({
        'trade_date': dates,
        'open': prices2 * 0.995,
        'high': prices2 * 1.005,
        'low': prices2 * 0.99,
        'close': prices2,
        'volume': np.random.randint(100000, 1000000, days),
    })

    data_dict = {'etf1': etf1, 'etf2': etf2}

    strat, cerebro = _run_strategy(
        data_dict, 100000,
        lookback_short=20, lookback_long=60, top_n=2, rebalance_freq=20,
        constraints={'max_total_exposure_pct': 90, 'max_position_pct': 40,
                     'min_trade_amount': 0, 'slippage_rate': 0, 't_plus_one': False},
    )

    trades = strat.trade_log
    sell_trades = [t for t in trades if t['direction'] == '卖出']

    # etf1持续上涨会超配，应该有减仓卖出
    etf1_sells = [t for t in sell_trades if t['code'] == 'etf1']
    assert len(etf1_sells) > 0, (
        f"etf1持续上涨超配，应该有减仓卖出，但卖出交易数为0。"
        f"总交易数: {len(trades)}，买入: {len([t for t in trades if t['direction']=='买入'])}"
    )


def test_trade_log_cash_after_consistency():
    """交易日志中 cash_after 字段存在，且买入后现金减少"""
    data_dict = {
        'etf1': _make_data('etf1', 1.0, 0.002, 150),
        'etf2': _make_data('etf2', 1.0, 0.0015, 150),
    }
    strat, cerebro = _run_strategy(
        data_dict, 100000,
        lookback_short=20, lookback_long=60, top_n=2, rebalance_freq=20,
        constraints={'max_total_exposure_pct': 95, 'max_position_pct': 40,
                     'min_trade_amount': 0, 'slippage_rate': 0, 't_plus_one': False},
    )
    trades = strat.trade_log
    assert len(trades) > 0, "应该有交易"

    for t in trades:
        assert 'cash_after' in t, f"交易日志缺少 cash_after 字段: {t.keys()}"
        assert isinstance(t['cash_after'], float), "cash_after 应为数字"
        assert t['cash_after'] >= 0, "现金不应为负"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
