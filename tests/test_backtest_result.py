import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backtest.result import BacktestResult, TradeRecord


def test_trade_record_creation():
    trade = TradeRecord(
        trade_date="2025-01-15",
        code="510300",
        direction="buy",
        quantity=1000,
        price=4.5,
        commission=1.35,
    )
    assert trade.trade_date == "2025-01-15"
    assert trade.code == "510300"
    assert trade.direction == "buy"
    assert trade.quantity == 1000
    assert trade.price == 4.5
    assert trade.commission == 1.35
    print("✓ TradeRecord 正确创建")


def test_backtest_result_creation():
    result = BacktestResult(
        strategy_name="momentum_weekly",
        start_date="2025-01-01",
        end_date="2025-06-30",
        initial_capital=1000000,
        final_capital=1050000,
        daily_nav=[{"date": "2025-01-01", "nav": 1.0}, {"date": "2025-01-02", "nav": 1.05}],
        trades=[],
        final_holdings=[{"code": "510300", "quantity": 1000, "last_price": 4.5}],
        metrics={"total_return": 0.05, "annual_return": 0.1, "max_drawdown": 0.02,
                 "sharpe_ratio": 1.5, "win_rate": 0.6, "trade_count": 10},
    )
    assert result.strategy_name == "momentum_weekly"
    assert result.initial_capital == 1000000
    assert result.final_capital == 1050000
    assert len(result.daily_nav) == 2
    assert result.is_benchmark is False
    print("✓ BacktestResult 正确创建，默认非基准")


def test_backtest_result_benchmark_flag():
    result = BacktestResult(
        strategy_name="沪深300买入持有",
        start_date="2025-01-01",
        end_date="2025-06-30",
        initial_capital=1000000,
        final_capital=1020000,
        daily_nav=[],
        trades=[],
        final_holdings=[],
        metrics={},
        is_benchmark=True,
    )
    assert result.is_benchmark is True
    print("✓ BacktestResult 基准标记正确")


def main():
    print("=== 测试 BacktestResult ===")
    test_trade_record_creation()
    test_backtest_result_creation()
    test_backtest_result_benchmark_flag()
    print("\n🎉 所有测试通过！")


if __name__ == "__main__":
    main()
