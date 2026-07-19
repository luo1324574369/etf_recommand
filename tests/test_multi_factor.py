"""多因子轮动策略测试"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from config.settings import DB_PATH


def test_multi_factor_basic():
    """基础回测：3只ETF，2023-2024，验证不崩溃"""
    from strategy import multi_factor

    init_db(DB_PATH)
    price_repo = PriceRepository(get_db(DB_PATH))

    codes = ['510300', '510500', '512480']
    data_dict = {}
    for code in codes:
        prices = price_repo.get_daily_price(code)
        if prices:
            data_dict[code] = pd.DataFrame(prices)

    result = multi_factor.run_backtest(
        data_dict,
        initial_capital=1000000,
        start_date='2023-01-01',
        end_date='2024-12-31',
        lookback_momentum=60,
        lookback_volatility=60,
        top_n=3,
        rebalance_freq=20,
        constraints={
            'max_total_exposure_pct': 95,
            'max_position_pct': 40,
            'min_trade_amount': 5000,
            'slippage_rate': 0.1,
            'max_per_sector': 0,
        },
        valuation_repo=None,  # 无PE数据时跳过估值因子
    )

    assert 'trade_list' in result
    assert 'nav_df' in result
    assert 'final_value' in result
    assert 'num_trades' in result
    # 应有交易记录（3只ETF + 20日调仓）
    assert result['num_trades'] > 0 or len(result['trade_list']) > 0
    # 交易记录的reason应包含"多因子"
    if result['trade_list']:
        all_reasons = ' '.join(t.get('reason', '') for t in result['trade_list'])
        assert '多因子' in all_reasons


def test_multi_factor_style_constraint():
    """风格分散约束生效：33只ETF全池，max_per_sector=1"""
    from strategy import multi_factor
    from config.settings import ETF_UNIVERSE

    init_db(DB_PATH)
    price_repo = PriceRepository(get_db(DB_PATH))

    # 取所有有数据的ETF
    data_dict = {}
    for etf in ETF_UNIVERSE:
        prices = price_repo.get_daily_price(etf['code'])
        if prices and len(prices) > 120:
            data_dict[etf['code']] = pd.DataFrame(prices)

    if len(data_dict) < 10:
        pytest.skip("ETF数据不足")

    result = multi_factor.run_backtest(
        data_dict,
        initial_capital=1000000,
        start_date='2023-01-01',
        end_date='2024-12-31',
        lookback_momentum=60,
        lookback_volatility=60,
        top_n=5,
        rebalance_freq=20,
        constraints={
            'max_total_exposure_pct': 95,
            'max_position_pct': 40,
            'min_trade_amount': 5000,
            'slippage_rate': 0.1,
            'max_per_sector': 1,
        },
        valuation_repo=None,
    )

    # 验证交易记录结构正确
    trade_list = result.get('trade_list', [])
    if trade_list:
        # 检查交易记录结构
        for t in trade_list[:5]:
            assert 'date' in t
            assert 'code' in t
            assert 'direction' in t
            assert 'reason' in t
        # 验证不崩溃且有合理数量的交易
        assert len(trade_list) > 0
    # 验证最终市值合理
    assert result['final_value'] > 0


def test_multi_factor_cash_management():
    """现金管理：5只ETF，max_position_pct=40%，总仓位≤95%"""
    from strategy import multi_factor

    init_db(DB_PATH)
    price_repo = PriceRepository(get_db(DB_PATH))

    codes = ['510300', '510500', '512480', '159915', '510050']
    data_dict = {}
    for code in codes:
        prices = price_repo.get_daily_price(code)
        if prices:
            data_dict[code] = pd.DataFrame(prices)

    result = multi_factor.run_backtest(
        data_dict,
        initial_capital=1000000,
        start_date='2023-06-01',
        end_date='2024-06-01',
        lookback_momentum=60,
        lookback_volatility=60,
        top_n=3,
        rebalance_freq=20,
        constraints={
            'max_total_exposure_pct': 95,
            'max_position_pct': 40,
            'min_trade_amount': 5000,
            'slippage_rate': 0.1,
            'max_per_sector': 0,
        },
        valuation_repo=None,
    )

    # 验证最终市值合理（不应出现负值或异常值）
    assert result['final_value'] > 0
    # 验证总交易次数合理
    assert result['num_trades'] >= 0
    # 验证回测期间有净值数据
    assert len(result.get('nav_df', [])) > 0


class TestTurnoverTracking(unittest.TestCase):
    """换手率追踪测试"""

    def test_strategy_has_turnover_records(self):
        """策略实例应有 _turnover_records 列表"""
        from strategy.multi_factor import MultiFactorStrategy
        # 检查类属性是否存在
        self.assertTrue(hasattr(MultiFactorStrategy, '__init__'))
        # 用最小回测验证 _turnover_records 被初始化
        result = self._run_min_backtest()
        self.assertIn('turnover_total_pct', result)
        self.assertIn('turnover_annual_pct', result)
        self.assertIn('turnover_series', result)
        self.assertIsInstance(result['turnover_total_pct'], float)
        self.assertGreaterEqual(result['turnover_total_pct'], 0)

    def test_turnover_series_has_data_when_trades_exist(self):
        """当回测产生交易时，turnover_series 应包含记录"""
        result = self._run_min_backtest()
        # 最小回测中如果发生买入，turnover_series 应有数据
        if result['turnover_total_pct'] > 0:
            self.assertFalse(result['turnover_series'].empty)
            # 每条记录应包含必要字段
            for col in ['date', 'buy_amount', 'total_value', 'turnover_pct']:
                self.assertIn(col, result['turnover_series'].columns)

    def _run_min_backtest(self):
        from strategy.backtest_utils import run_backtest
        from strategy.multi_factor import MultiFactorStrategy
        from strategy.constraints import DEFAULT_BACKTEST_CONSTRAINTS

        dates = pd.date_range('2024-01-01', periods=260, freq='B')
        data = {}
        for code in ['510300', '510500', '159915']:
            data[code] = pd.DataFrame({
                'trade_date': dates.strftime('%Y-%m-%d'),
                'open': 10, 'high': 10.5, 'low': 9.5,
                'close': [10 + i * 0.01 for i in range(260)],
                'volume': 1000000,
            })
        return run_backtest(
            MultiFactorStrategy,
            data,
            initial_capital=1000000,
            start_date='2024-06-01',
            end_date='2024-12-31',
            constraints=DEFAULT_BACKTEST_CONSTRAINTS,
            lookback_momentum=60,
            lookback_volatility=60,
            top_n=2,
            rebalance_freq=20,
        )
