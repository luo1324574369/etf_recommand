import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data.storage.db import init_db, get_db
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from data.storage.signal_repo import SignalRepository
from strategy.engine import StrategyEngine
from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor
from strategy.filters.trend_filter import TrendFilter
from strategy.filters.momentum_filter import MomentumFilter
from strategy.filters.volume_filter import VolumeFilter
from service.strategy_service import _build_engine as build_strategy, FACTOR_MAP, FILTER_MAP
from scripts.run_strategy import run_strategy
from config.settings import STRATEGY_CONFIG


def _make_price_data(base_price, momentum_pct, vol_ratio, n_days=30, start_date=None):
    data = []
    if start_date is None:
        start_date = datetime(2025, 1, 1)
    else:
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    end_price = base_price * (1 + momentum_pct)
    price_step = (end_price - base_price) / (n_days - 1)
    base_volume = 100000

    for i in range(n_days):
        trade_date = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
        close = base_price + price_step * i
        if i >= n_days - 5:
            volume = int(base_volume * vol_ratio)
        else:
            volume = base_volume
        data.append({
            "trade_date": trade_date,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
            "amount": close * volume,
        })
    return data


def test_factor_map():
    assert "MomentumFactor" in FACTOR_MAP
    assert "TrendFactor" in FACTOR_MAP
    assert "VolumeFactor" in FACTOR_MAP
    assert FACTOR_MAP["MomentumFactor"] == MomentumFactor
    assert FACTOR_MAP["TrendFactor"] == TrendFactor
    assert FACTOR_MAP["VolumeFactor"] == VolumeFactor
    print("✓ FACTOR_MAP 包含所有因子类")


def test_filter_map():
    assert "TrendFilter" in FILTER_MAP
    assert "MomentumFilter" in FILTER_MAP
    assert "VolumeFilter" in FILTER_MAP
    assert FILTER_MAP["TrendFilter"] == TrendFilter
    assert FILTER_MAP["MomentumFilter"] == MomentumFilter
    assert FILTER_MAP["VolumeFilter"] == VolumeFilter
    print("✓ FILTER_MAP 包含所有筛选器类")


def test_build_strategy():
    config = {
        "factors": [
            {"class": "MomentumFactor", "period": 10},
            {"class": "TrendFactor", "period": 20},
            {"class": "VolumeFactor", "short_period": 5, "long_period": 20},
        ],
        "filters": [
            {"class": "TrendFilter", "ma_period": 20, "enabled": True},
            {"class": "VolumeFilter", "min_ratio": 1.2, "enabled": True},
        ],
        "top_n": 3,
        "score_weights": {
            "momentum": 0.6,
            "volume": 0.4,
        },
    }

    engine = build_strategy(config)
    assert isinstance(engine, StrategyEngine)
    assert len(engine.factors) == 3
    assert len(engine.filters) == 2
    assert engine.top_n == 3
    assert engine.score_weights["momentum"] == 0.6
    print("✓ build_strategy 正确构建策略引擎")


def test_build_strategy_disabled_filter():
    config = {
        "factors": [
            {"class": "MomentumFactor", "period": 10},
        ],
        "filters": [
            {"class": "TrendFilter", "enabled": True},
            {"class": "VolumeFilter", "enabled": False},
        ],
        "top_n": 5,
        "score_weights": {},
    }

    engine = build_strategy(config)
    assert len(engine.filters) == 1
    print("✓ build_strategy 正确跳过禁用的筛选器")


def test_build_strategy_with_position_max_positions():
    config = {
        "factors": [],
        "filters": [],
        "position": {
            "max_positions": 10,
        },
        "score_weights": {},
    }

    engine = build_strategy(config)
    assert engine.top_n == 10
    print("✓ build_strategy 从 position.max_positions 读取 top_n")


def test_run_strategy_integration():
    db_path = "data/test_strategy_run.db"

    if os.path.exists(db_path):
        os.remove(db_path)

    init_db(db_path)
    db = get_db(db_path)

    try:
        etf_repo = ETFRepository(db)
        price_repo = PriceRepository(db)

        etfs = [
            {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "指数"},
            {"code": "510500", "name": "中证500ETF", "sector": "宽基", "type": "指数"},
            {"code": "159915", "name": "创业板ETF", "sector": "宽基", "type": "指数"},
            {"code": "588000", "name": "科创50ETF", "sector": "宽基", "type": "指数"},
        ]
        etf_repo.batch_insert(etfs)

        signal_date = "2025-01-30"
        price_data = {
            "510300": _make_price_data(base_price=10.0, momentum_pct=0.20, vol_ratio=1.5),
            "510500": _make_price_data(base_price=10.0, momentum_pct=0.15, vol_ratio=1.3),
            "159915": _make_price_data(base_price=10.0, momentum_pct=0.10, vol_ratio=1.1),
            "588000": _make_price_data(base_price=10.0, momentum_pct=-0.10, vol_ratio=0.9),
        }
        price_repo.batch_insert(price_data)

        test_config = {
            "test_strategy": {
                "factors": [
                    {"class": "MomentumFactor", "period": 10},
                    {"class": "TrendFactor", "period": 20},
                    {"class": "VolumeFactor", "short_period": 5, "long_period": 20},
                ],
                "filters": [
                    {"class": "TrendFilter", "ma_period": 20, "enabled": True},
                ],
                "top_n": 3,
                "score_weights": {
                    "momentum": 0.6,
                    "volume": 0.4,
                },
            }
        }

        original_config = STRATEGY_CONFIG.copy()
        STRATEGY_CONFIG.update(test_config)

        try:
            results = run_strategy("test_strategy", signal_date=signal_date, db_path=db_path)
            assert len(results) > 0, "应该有选股结果"
            assert len(results) <= 3, "结果数量不超过 top_n"

            for result in results:
                assert "code" in result
                assert "rank" in result
                assert "score" in result
                assert "factor_values" in result

            codes = [r["code"] for r in results]
            assert "588000" not in codes, "下跌的ETF应该被趋势筛选器过滤掉"

            signal_repo = SignalRepository(db)
            saved_signals = signal_repo.get_signals_by_date("test_strategy", signal_date)
            assert len(saved_signals) == len(results), f"保存的信号数量应该等于结果数量"
            assert saved_signals[0]["rank"] == 1
            assert saved_signals[0]["action"] == "buy"
            assert isinstance(saved_signals[0]["reason"], dict), "reason 应该是 dict"

            print(f"✓ run_strategy 集成测试通过，返回 {len(results)} 个结果，保存 {len(saved_signals)} 条信号")
        finally:
            STRATEGY_CONFIG.clear()
            STRATEGY_CONFIG.update(original_config)
    finally:
        db.close()
        if os.path.exists(db_path):
            os.remove(db_path)


def test_run_strategy_unknown_strategy():
    try:
        run_strategy("nonexistent_strategy", db_path="data/test_nonexistent.db")
        assert False, "应该抛出 ValueError"
    except ValueError as e:
        assert "not found" in str(e)
        print("✓ 未知策略抛出 ValueError")

    db_path = "data/test_nonexistent.db"
    if os.path.exists(db_path):
        os.remove(db_path)


def main():
    print("=== 测试 FACTOR_MAP ===")
    test_factor_map()

    print("\n=== 测试 FILTER_MAP ===")
    test_filter_map()

    print("\n=== 测试 build_strategy ===")
    test_build_strategy()
    test_build_strategy_disabled_filter()
    test_build_strategy_with_position_max_positions()

    print("\n=== 测试 run_strategy 集成 ===")
    test_run_strategy_integration()

    print("\n=== 测试错误处理 ===")
    test_run_strategy_unknown_strategy()

    print("\n🎉 所有测试通过！")


if __name__ == "__main__":
    main()
