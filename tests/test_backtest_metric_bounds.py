import pandas as pd


def test_backtest_metrics_ignore_warmup_period():
    from strategy import multi_factor

    dates = pd.date_range('2024-01-02', periods=260, freq='B')
    close = [10.0] * 120 + [10.0 + index * 0.05 for index in range(140)]
    prices = pd.DataFrame({
        'trade_date': dates,
        'open': close,
        'high': close,
        'low': close,
        'close': close,
        'volume': [1_000_000] * len(dates),
        'adj_factor': [1.0] * len(dates),
    })

    result = multi_factor.run_backtest(
        {'510300': prices},
        initial_capital=100_000,
        start_date='2024-06-18',
        end_date='2024-12-30',
        lookback_momentum=20,
        lookback_volatility=20,
        top_n=1,
        rebalance_freq=20,
        market_regime_switch=False,
        enable_factor_monitor=False,
        constraints={
            'max_positions': 1,
            'min_positions': 0,
            'max_position_pct': 100.0,
            'max_total_exposure_pct': 100.0,
            'slippage_rate': 0.0,
            't_plus_one': False,
            'min_trade_amount': 0,
            'max_monthly_turnover': 9999.0,
            'max_per_sector': 0,
            'max_sector_exposure_pct': 100.0,
            'core_allocation_pct': 0.0,
            'core_etf_codes': (),
            'core_weights': (),
        },
    )

    assert result['nav_df']['date'].min() >= pd.Timestamp('2024-06-18')
    assert result['annual_return'] == result['comparison']['strategy_metrics']['annual_return']
    assert result['sharpe_ratio'] == result['comparison']['strategy_metrics']['sharpe_ratio']
    assert result['max_drawdown'] == result['comparison']['strategy_metrics']['max_drawdown']
    assert result['max_drawdown_days'] <= len(result['nav_df'])
