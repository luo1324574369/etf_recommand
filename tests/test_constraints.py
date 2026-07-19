import unittest
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

    def test_max_total_exposure(self):
        """总仓位上限-超额拒绝"""
        c = StrategyConstraints(max_total_exposure_pct=80)
        positions = {'510300': 50000, '510500': 25000}
        ok, reason = c.can_buy('159915', 1.0, 10000, positions, 100000, date.today(), effective_cash=25000)
        assert not ok
        assert '总仓位' in reason

    def test_max_total_exposure_pass(self):
        """总仓位上限-通过"""
        c = StrategyConstraints(max_total_exposure_pct=95)
        positions = {'510300': 30000, '510500': 30000}
        ok, reason = c.can_buy('159915', 1.0, 10000, positions, 100000, date.today(), effective_cash=40000)
        assert ok

    def test_effective_cash_check(self):
        """现金检查-不足拒绝"""
        c = StrategyConstraints(max_total_exposure_pct=100)
        positions = {'510300': 30000}
        ok, reason = c.can_buy('510500', 1.0, 80000, positions, 200000, date.today(), effective_cash=50000)
        assert not ok
        assert '可用现金' in reason

    def test_effective_cash_none_backward_compat(self):
        """现金检查-不传参时向后兼容"""
        c = StrategyConstraints(max_total_exposure_pct=100)
        positions = {'510300': 30000}
        ok, reason = c.can_buy('510500', 1.0, 80000, positions, 200000, date.today())
        assert ok

    def test_can_buy_sector_limit(self):
        """买入时风格分散检查 - 超限拒绝"""
        c = StrategyConstraints(max_per_sector=2)
        code_to_sector = {'510300': '宽基', '510500': '宽基', '512480': '科技',
                          '159995': '科技'}
        # 已持仓2只宽基
        positions = {'510300': 10000, '510500': 10000}
        # 买入第3只宽基 → 拒绝
        code_to_sector['588000'] = '宽基'
        ok, reason = c.can_buy('588000', 1.0, 20000, positions, 100000,
                                date.today(), code_to_sector=code_to_sector)
        assert not ok
        assert '宽基' in reason and '上限' in reason

    def test_can_buy_sector_add_position(self):
        """已持仓的加仓不受风格限制"""
        c = StrategyConstraints(max_per_sector=1)
        code_to_sector = {'512480': '科技'}
        positions = {'512480': 10000}
        # 加仓已持仓的科技ETF → 允许
        ok, reason = c.can_buy('512480', 1.0, 5000, positions, 100000,
                                date.today(), code_to_sector=code_to_sector)
        assert ok

    def test_can_buy_sector_no_constraint(self):
        """max_per_sector=0时不检查风格"""
        c = StrategyConstraints(max_per_sector=0)
        code_to_sector = {'510300': '宽基'}
        positions = {'510300': 10000, '510500': 10000}
        ok, reason = c.can_buy('588000', 1.0, 20000, positions, 100000,
                                date.today(), code_to_sector=code_to_sector)
        assert ok

    def test_can_buy_sector_no_mapping(self):
        """code_to_sector=None时不检查风格"""
        c = StrategyConstraints(max_per_sector=2)
        positions = {'510300': 10000, '510500': 10000}
        ok, reason = c.can_buy('588000', 1.0, 20000, positions, 100000,
                                date.today(), code_to_sector=None)
        assert ok


class TestDefaultBacktestConstraints(unittest.TestCase):
    """默认回测约束常量"""

    def test_constant_exists(self):
        from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS
        self.assertIsInstance(DEFAULT_BACKTEST_CONSTRAINTS, dict)

    def test_required_fields(self):
        from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS
        required = ['long_only', 'max_positions', 'min_positions',
                    'max_position_pct', 'max_total_exposure_pct',
                    'slippage_rate', 't_plus_one', 'min_trade_amount',
                    'max_monthly_turnover', 'max_per_sector']
        for field in required:
            self.assertIn(field, DEFAULT_BACKTEST_CONSTRAINTS)

    def test_values_match_streamlit_defaults(self):
        """与 Streamlit UI 默认值对齐"""
        from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS
        self.assertTrue(DEFAULT_BACKTEST_CONSTRAINTS['long_only'])
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['max_positions'], 5)
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['min_positions'], 0)
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['max_position_pct'], 40.0)
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['max_total_exposure_pct'], 95.0)
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['slippage_rate'], 0.1)
        self.assertTrue(DEFAULT_BACKTEST_CONSTRAINTS['t_plus_one'])
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['min_trade_amount'], 5000.0)
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['max_monthly_turnover'], 100.0)
        self.assertEqual(DEFAULT_BACKTEST_CONSTRAINTS['max_per_sector'], 2)
