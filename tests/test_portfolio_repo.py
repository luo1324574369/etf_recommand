import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.storage.db import init_db, get_db
from data.storage.portfolio_repo import PortfolioRepository


def test_create_account():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    account = repo.create_account(initial_capital=10000.0)
    assert account["id"] == 1
    assert account["initial_capital"] == 10000.0
    assert account["cash"] == 10000.0

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_get_account():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    account = repo.get_account()
    assert account is not None
    assert account["cash"] == 10000.0

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_update_cash():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.update_cash(new_cash=5000.0)
    account = repo.get_account()
    assert account["cash"] == 5000.0

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_add_trade():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    trade_id = repo.add_trade({
        "trade_date": "2026-07-01",
        "code": "510300",
        "direction": "buy",
        "quantity": 1000,
        "price": 4.12,
        "fee": 5.0,
    })
    assert trade_id == 1

    trades = repo.list_trades(limit=5)
    assert len(trades) == 1
    assert trades[0]["code"] == "510300"

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


def test_list_trades_by_code():
    db_fd, db_path = tempfile.mkstemp()
    init_db(db_path)
    conn = get_db(db_path)
    repo = PortfolioRepository(conn)

    repo.create_account(initial_capital=10000.0)
    repo.add_trade({"trade_date": "2026-07-01", "code": "510300", "direction": "buy", "quantity": 1000, "price": 4.12, "fee": 5.0})
    repo.add_trade({"trade_date": "2026-07-02", "code": "159995", "direction": "buy", "quantity": 500, "price": 3.40, "fee": 5.0})

    trades_510300 = repo.get_trades_by_code("510300")
    assert len(trades_510300) == 1

    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


if __name__ == "__main__":
    test_create_account()
    test_get_account()
    test_update_cash()
    test_add_trade()
    test_list_trades_by_code()
    print("All account tests passed")
