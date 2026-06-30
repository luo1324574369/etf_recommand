import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from data.storage.db import init_db, get_db
from data.storage.signal_repo import SignalRepository


def test_signal_repo():
    db_path = 'data/test_etf.db'

    if os.path.exists(db_path):
        os.remove(db_path)

    init_db(db_path)
    db = get_db(db_path)
    repo = SignalRepository(db)

    signals = [
        {
            'signal_date': '2026-06-30',
            'strategy_name': 'test_strategy',
            'code': '510300',
            'name': '沪深300ETF',
            'rank': 1,
            'score': 95.5,
            'reason': {'factor': 'momentum', 'value': 0.85},
            'action': 'buy'
        },
        {
            'signal_date': '2026-06-30',
            'strategy_name': 'test_strategy',
            'code': '510500',
            'name': '中证500ETF',
            'rank': 2,
            'score': 90.0,
            'reason': {'factor': 'value', 'value': 0.78},
            'action': 'buy'
        },
        {
            'signal_date': '2026-06-30',
            'strategy_name': 'test_strategy',
            'code': '512100',
            'name': '中证1000ETF',
            'rank': 3,
            'score': 85.5,
            'reason': {'factor': 'quality', 'value': 0.72},
            'action': 'hold'
        }
    ]

    count = repo.batch_save_signals(signals)
    assert count == 3, f"batch_save_signals should return 3, got {count}"
    print("✓ batch_save_signals: 保存了 3 条信号")

    latest = repo.get_latest_signals('test_strategy')
    assert len(latest) == 3, f"get_latest_signals should return 3, got {len(latest)}"
    assert isinstance(latest[0]['reason'], dict), "reason should be parsed as dict"
    assert latest[0]['reason']['factor'] == 'momentum', "first signal reason factor should be momentum"
    assert latest[0]['rank'] == 1, "first signal should be rank 1"
    print("✓ get_latest_signals: 返回 3 条信号，reason 已解析为 dict")

    dates = repo.list_signal_dates('test_strategy')
    assert len(dates) == 1, f"list_signal_dates should return 1 date, got {len(dates)}"
    assert dates[0] == '2026-06-30', f"date should be 2026-06-30, got {dates[0]}"
    print("✓ list_signal_dates: 返回 1 个日期")

    by_date = repo.get_signals_by_date('test_strategy', '2026-06-30')
    assert len(by_date) == 3, f"get_signals_by_date should return 3, got {len(by_date)}"
    assert by_date[0]['code'] == '510300', "first signal code should be 510300"
    assert isinstance(by_date[1]['reason'], dict), "reason should be dict"
    print("✓ get_signals_by_date: 返回正确的信号")

    empty = repo.get_latest_signals('nonexistent_strategy')
    assert empty == [], f"nonexistent strategy should return empty list, got {empty}"
    print("✓ 不存在的策略返回空列表")

    empty_dates = repo.list_signal_dates('nonexistent_strategy')
    assert empty_dates == [], f"nonexistent strategy should return empty dates list, got {empty_dates}"
    print("✓ 不存在的策略 list_signal_dates 返回空列表")

    empty_by_date = repo.get_signals_by_date('test_strategy', '2020-01-01')
    assert empty_by_date == [], f"nonexistent date should return empty list, got {empty_by_date}"
    print("✓ 不存在的日期返回空列表")

    db.close()

    if os.path.exists(db_path):
        os.remove(db_path)
        print("✓ 已删除 test_etf.db")

    print("\n🎉 所有测试通过！")


if __name__ == '__main__':
    test_signal_repo()
