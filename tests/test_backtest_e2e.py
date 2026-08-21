import pandas as pd


def _price_frame(periods=280, include_signal=True, flat=False, start_date="2024-01-02"):
    dates = pd.date_range(start_date, periods=periods, freq="B")
    if flat:
        closes = [10.0] * periods
    else:
        closes = [10.0 + index * 0.02 for index in range(periods)]
    frame = pd.DataFrame({
        "trade_date": dates,
        "open": closes,
        "high": [close * 1.01 for close in closes],
        "low": [close * 0.99 for close in closes],
        "close": closes,
        "volume": [1_000_000] * periods,
    })
    if include_signal:
        frame["signal_open"] = frame["open"]
        frame["signal_high"] = frame["high"]
        frame["signal_low"] = frame["low"]
        frame["signal_close"] = frame["close"]
    return frame


def _backtest_constraints(**overrides):
    constraints = {
        "max_positions": 2,
        "min_positions": 0,
        "max_position_pct": 100.0,
        "max_total_exposure_pct": 95.0,
        "slippage_rate": 0.0,
        "t_plus_one": False,
        "min_trade_amount": 0,
        "max_monthly_turnover": 9999.0,
        "max_per_sector": 0,
        "max_sector_exposure_pct": 100.0,
        "core_allocation_pct": 0.0,
        "core_etf_codes": (),
        "core_weights": (),
    }
    constraints.update(overrides)
    return constraints


def test_mixed_local_and_source_rows_survive_backtest_preparation():
    """本地暖机行带 signal_*、主源回测行不带 signal_* 时仍应保留行情。"""
    import backtrader as bt

    from strategy.backtest_utils import _prepare_data

    warmup = _price_frame(periods=120, include_signal=True)
    source_rows = _price_frame(periods=160, include_signal=False, start_date="2024-06-18")
    prices = pd.concat([warmup, source_rows], ignore_index=True).drop_duplicates("trade_date", keep="last")
    cerebro = bt.Cerebro()

    prepared_rows = _prepare_data(
        cerebro,
        {"510300": prices},
        start_date="2024-06-17",
        end_date="2024-12-31",
        lookback_long=60,
    )

    assert prepared_rows > 0
    prepared = cerebro.datas[0].p.dataname
    assert len(prepared) > 0
    assert prepared["signal_close"].notna().all()


def test_multi_factor_backtest_handles_mixed_source_rows_end_to_end():
    from strategy import multi_factor

    warmup = _price_frame(periods=120, include_signal=True)
    source_rows = _price_frame(periods=160, include_signal=False, start_date="2024-06-18")
    prices = pd.concat([warmup, source_rows], ignore_index=True).drop_duplicates("trade_date", keep="last")

    result = multi_factor.run_backtest(
        {"510300": prices},
        initial_capital=100_000,
        start_date="2024-06-17",
        end_date="2024-12-31",
        lookback_momentum=20,
        lookback_volatility=20,
        top_n=1,
        rebalance_freq=20,
        market_regime_switch=False,
        enable_factor_monitor=False,
        constraints=_backtest_constraints(),
    )

    assert result["final_value"] > 0
    assert not result["nav_df"].empty
    assert "annual_return" in result


def test_backtest_with_no_trades_returns_a_valid_result():
    from strategy import multi_factor

    result = multi_factor.run_backtest(
        {"510300": _price_frame(flat=True)},
        initial_capital=100_000,
        start_date="2024-06-17",
        end_date="2024-12-31",
        lookback_momentum=20,
        lookback_volatility=20,
        top_n=1,
        rebalance_freq=20,
        market_regime_switch=False,
        enable_factor_monitor=False,
        constraints=_backtest_constraints(max_positions=0),
    )

    assert result["final_value"] == 100_000
    assert result["trade_list"] == []
    assert result["num_trades"] == 0
    assert not result["nav_df"].empty


def test_application_service_backtest_archives_a_real_result(tmp_path):
    from data.storage.db import get_db, init_db
    from data.storage.etf_repo import ETFRepository
    from data.storage.price_repo import PriceRepository
    from service.application_service import ApplicationService

    db_path = tmp_path / "e2e.db"
    init_db(db_path)
    connection = get_db(db_path)
    ETFRepository(connection).insert_etf("510300", "沪深300ETF", "宽基", "指数")
    rows = _price_frame(periods=280, include_signal=False)
    PriceRepository(connection).insert_daily_price(
        "510300",
        [
            {
                **row,
                "trade_date": row["trade_date"].strftime("%Y-%m-%d"),
                "adj_factor": 1.0,
                "adjustment_status": "provided",
                "amount": row["close"] * row["volume"],
            }
            for row in rows.to_dict("records")
        ],
    )
    connection.close()

    service = ApplicationService(db_path, report_root=tmp_path / "reports")
    try:
        result = service.run_backtest(
            ["510300"],
            "2024-06-17",
            "2024-12-31",
            {
                "lookback_momentum": 20,
                "lookback_volatility": 20,
                "top_n": 1,
                "rebalance_freq": 20,
                "market_regime_switch": False,
                "enable_factor_monitor": False,
            },
            _backtest_constraints(),
        )
        paths = result["report_paths"]
        assert result["report_status"] == "passed"
        assert result["final_value"] > 0
        assert all(path for path in paths.values())
        assert all(pd.notna(result["nav_df"]["nav"]))
    finally:
        service.close()
