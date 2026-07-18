"""多因子轮动策略测试"""
import sys
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
