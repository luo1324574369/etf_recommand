import pytest
import pandas as pd
from datetime import date, timedelta
from strategy.constraints import StrategyConstraints


class TestStrategyConstraints:

    def test_slippage_buy(self):
        """买入滑点"""
        c = StrategyConstraints(slippage_rate=0.1)
        price = 1.0
        assert abs(c.apply_slippage_buy(price) - 1.001) < 1e-6

    def test_slippage_sell(self):
        """卖出滑点"""
        c = StrategyConstraints(slippage_rate=0.1)
        price = 1.0
        assert abs(c.apply_slippage_sell(price) - 0.999) < 1e-6

    def test_min_trade_amount(self):
        """最低交易金额"""
        c = StrategyConstraints(min_trade_amount=5000)
        ok, reason = c.can_buy('510300', 1.0, 1000, {}, 100000, date.today())
        assert not ok
        assert '最低交易金额' in reason

    def test_min_trade_amount_pass(self):
        """最低交易金额-通过"""
        c = StrategyConstraints(min_trade_amount=5000)
        ok, reason = c.can_buy('510300', 1.0, 10000, {}, 100000, date.today())
        assert ok

    def test_max_position_pct(self):
        """单仓位上限"""
        c = StrategyConstraints(max_position_pct=30)
        ok, reason = c.can_buy('510300', 1.0, 50000, {}, 100000, date.today())
        assert not ok
        assert '超过单仓上限' in reason

    def test_max_position_pct_pass(self):
        """单仓位上限-通过"""
        c = StrategyConstraints(max_position_pct=30)
        ok, reason = c.can_buy('510300', 1.0, 20000, {}, 100000, date.today())
        assert ok

    def test_max_positions(self):
        """持仓数量上限"""
        c = StrategyConstraints(max_positions=2)
        positions = {'510300': 10000, '510500': 10000}
        ok, reason = c.can_buy('159915', 1.0, 10000, positions, 100000, date.today())
        assert not ok
        assert '已达上限' in reason

    def test_max_positions_add_to_existing(self):
        """持仓数量上限-加仓现有仓位"""
        c = StrategyConstraints(max_positions=2)
        positions = {'510300': 10000, '510500': 10000}
        ok, reason = c.can_buy('510300', 1.0, 5000, positions, 100000, date.today())
        assert ok

    def test_t_plus_one(self):
        """T+1约束"""
        c = StrategyConstraints(t_plus_one=True)
        today = date.today()
        c.record_buy('510300', today)
        ok, reason = c.can_sell('510300', 1.0, 1000, 1000, today)
        assert not ok
        assert 'T+1' in reason

    def test_t_plus_one_next_day(self):
        """T+1约束-次日可卖"""
        c = StrategyConstraints(t_plus_one=True)
        today = date.today()
        yesterday = today - timedelta(days=1)
        c.record_buy('510300', yesterday)
        ok, reason = c.can_sell('510300', 1.0, 1000, 1000, today)
        assert ok

    def test_turnover_limit(self):
        """月度换手率上限"""
        c = StrategyConstraints(max_monthly_turnover=50)
        today = date.today()
        c.record_turnover('510300', 30000, today)
        ok, reason = c.check_turnover(30000, 100000, today)
        assert not ok
        assert '超过上限' in reason

    def test_turnover_pass(self):
        """月度换手率-通过"""
        c = StrategyConstraints(max_monthly_turnover=100)
        today = date.today()
        c.record_turnover('510300', 30000, today)
        ok, reason = c.check_turnover(30000, 100000, today)
        assert ok
